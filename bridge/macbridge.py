#!/usr/bin/env python3
"""macbridge -- a deliberately small shell for Claude, on this Mac.

Why this exists: Cowork sessions run in the cloud. They reach your files
through a mounted folder, but that mount is a Linux VM, so `swift build`,
`claude mcp add`, and anything else macOS-specific cannot run there. Computer
use cannot fill the gap either: terminals are restricted to click-only, on
purpose. This is the sanctioned way across, and it is scoped on purpose.

WHAT IT ALLOWS, and nothing else:
  * commands whose working directory is inside an allowed root
  * a fixed allowlist of executables (see ALLOWED)
  * a hard timeout, and captured output

WHAT IT REFUSES:
  * anything outside the roots
  * any executable not on the list
  * shell metacharacters that chain commands (; | & ` $( ) < > newline)
  * sudo, in any form

Run it yourself, from your own terminal, and read it first. It is short so
that reading it is realistic.

    python3 bridge/macbridge.py --print-config     # what to register
    python3 bridge/macbridge.py                    # run it (stdio MCP)

Widen the allowlist by editing this file. That is intentional friction: an
allowlist you can extend from a config file is an allowlist an attacker can
extend from a config file.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from claudeyes.mcp.jsonrpc import Server  # noqa: E402

ROOTS = [os.path.expanduser(p) for p in
         os.environ.get("MACBRIDGE_ROOTS", "~/Projects").split(":")]

# Everything needed to build and install claudeyes, and little else.
# Notably absent: rm, mv, cp, chmod, curl, ssh, and every shell.
ALLOWED = {
    "swift", "xcrun", "xcode-select", "sw_vers", "uname", "arch",
    "python3", "pip3",
    "git", "make",
    "claude",
    "ls", "cat", "head", "tail", "wc", "find", "grep", "file", "which",
    "pwd", "env", "date", "echo", "mkdir", "sqlite3", "defaults",
}

FORBIDDEN_CHARS = set(";|&`$<>\n\r")
MAX_OUTPUT = 60_000

srv = Server("macbridge", "0.1.0")


def _resolve(cwd: str) -> str:
    path = os.path.realpath(os.path.expanduser(cwd or ROOTS[0]))
    for root in ROOTS:
        r = os.path.realpath(root)
        if path == r or path.startswith(r + os.sep):
            return path
    raise ValueError(
        f"cwd {path!r} is outside the allowed roots {ROOTS}. "
        "Restart macbridge with MACBRIDGE_ROOTS if this is deliberate.")


def _parse(command: str) -> list[str]:
    bad = FORBIDDEN_CHARS & set(command)
    if bad:
        raise ValueError(
            f"refusing: command contains {''.join(sorted(bad))!r}. "
            "This bridge runs ONE program with arguments. It does not run a "
            "shell, so pipes, redirects and chaining are unavailable by design. "
            "Send the steps as separate calls.")
    argv = shlex.split(command)
    if not argv:
        raise ValueError("empty command")
    prog = os.path.basename(argv[0])
    if prog == "sudo":
        raise ValueError("refusing: sudo is never allowed through this bridge.")
    if prog not in ALLOWED:
        raise ValueError(
            f"refusing: {prog!r} is not on the allowlist. Allowed: "
            f"{', '.join(sorted(ALLOWED))}. Edit ALLOWED in bridge/macbridge.py "
            "if you want it, and restart the bridge.")
    return argv


@srv.tool(
    "run",
    "Run ONE allowlisted program on this Mac, inside an allowed project directory. "
    "There is no shell: no pipes, redirects, chaining, globs or variable expansion. "
    "Send multi-step work as multiple calls. Use this for macOS-specific work that "
    "the cloud sandbox cannot do, such as swift build or claude mcp add.",
    {"type": "object", "required": ["command"], "properties": {
        "command": {"type": "string", "description": 'e.g. "swift build -c release"'},
        "cwd": {"type": "string", "description": "Absolute path inside an allowed root."},
        "timeout": {"type": "number", "default": 180,
                    "description": "Seconds. Max 900."}}},
)
def run(a: dict):
    try:
        cwd = _resolve(a.get("cwd", ""))
        argv = _parse(a["command"])
    except (ValueError, KeyError) as e:
        return f"REFUSED: {e}"
    timeout = max(1.0, min(float(a.get("timeout", 180)), 900.0))
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                           timeout=timeout, env=os.environ.copy())
    except FileNotFoundError:
        return f"REFUSED: {argv[0]} is on the allowlist but not installed."
    except subprocess.TimeoutExpired:
        return f"TIMEOUT after {timeout:.0f}s: {' '.join(argv)}"
    out = (p.stdout or "")[:MAX_OUTPUT]
    err = (p.stderr or "")[:MAX_OUTPUT]
    return {"exit_code": p.returncode, "cwd": cwd,
            "command": " ".join(argv), "stdout": out, "stderr": err}


@srv.tool(
    "info",
    "What this bridge will and will not do: allowed roots, allowed programs.",
    {"type": "object", "properties": {}},
)
def info(a: dict):
    return {"roots": ROOTS, "allowed_programs": sorted(ALLOWED),
            "shell": False, "sudo": False,
            "note": "Edit bridge/macbridge.py to change any of this."}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--print-config", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.print_config:
        print(json.dumps({"mcpServers": {"macbridge": {
            "command": sys.executable,
            "args": [os.path.abspath(__file__)],
            "env": {"MACBRIDGE_ROOTS": ":".join(ROOTS)}}}}, indent=2))
        return
    if args.self_test:
        for cmd in ["swift --version", "rm -rf /", "echo hi ; echo bye",
                    "sudo swift build", "git status"]:
            r = run({"command": cmd, "cwd": ROOTS[0], "timeout": 10})
            verdict = r if isinstance(r, str) else f"exit={r['exit_code']}"
            print(f"  {cmd:<28} -> {str(verdict)[:96]}")
        return
    srv.log(f"macbridge: roots={ROOTS}")
    srv.run()


if __name__ == "__main__":
    main()
