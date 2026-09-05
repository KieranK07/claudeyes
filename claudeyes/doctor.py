"""Check every link in the chain and say exactly what to do about the broken one.

    python3 -m claudeyes.doctor

Written because the failure modes here are mostly silent: ScreenCaptureKit
returns empty results rather than erroring when it lacks permission, a hook
that cannot reach the socket exits 0 by design, and an MCP server that is not
registered simply never appears. Nothing tells you. This does.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.expanduser("~/.claudeyes")
DB = os.path.join(HOME, "events.db")
SOCK = os.path.join(HOME, "actions.sock")
BIN = os.path.join(ROOT, "capture", ".build", "release", "claudeyes-capture")
SETTINGS = os.path.expanduser("~/.claude/settings.json")

OK, WARN, BAD = "  ok  ", " warn ", " FAIL "
results: list[tuple[str, str, str, str]] = []


def check(status: str, name: str, detail: str = "", fix: str = "") -> None:
    results.append((status, name, detail, fix))


def run(cmd: list[str], timeout: float = 10.0) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", "not found"
    except subprocess.TimeoutExpired as e:
        return -1, (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or ""), "timeout"


def main() -> int:
    print("\nclaudeyes doctor\n" + "-" * 62)

    # --- environment ---
    check(OK if sys.version_info >= (3, 10) else BAD, "python",
          f"{sys.version.split()[0]} at {sys.executable}",
          "need 3.10+")
    try:
        import numpy
        check(OK, "numpy", numpy.__version__)
    except ImportError:
        check(BAD, "numpy", "missing", f"{sys.executable} -m pip install numpy")

    if sys.platform != "darwin":
        check(WARN, "platform", sys.platform,
              "capture is macOS only; the Python core runs anywhere")
    else:
        rc, out, _ = run(["sw_vers", "-productVersion"])
        check(OK, "macOS", out.strip())
        if shutil.which("swift"):
            rc, out, _ = run(["swift", "--version"])
            check(OK, "swift", out.strip().splitlines()[0] if out else "present")
        else:
            check(BAD, "swift", "not found", "xcode-select --install")

    # --- capture binary ---
    if os.path.exists(BIN):
        check(OK, "capture built", BIN)
        # Does it actually get frames? Only a real run answers that, and the
        # permission failure is silent, so run it briefly and look for output.
        rc, out, err = run([BIN], timeout=6.0)
        if "SCShareableContent returned nothing" in err:
            check(BAD, "screen recording", "permission denied (silently)",
                  "System Settings > Privacy & Security > Screen Recording,\n"
                  "         enable your terminal app, then RESTART the terminal")
        elif '"type": "hello"' in out or '"type":"hello"' in out:
            frames = out.count('"dirty"')
            check(OK, "screen recording", f"granted; {frames} frame(s) in 6s")
        elif rc == 127:
            check(BAD, "capture runs", "binary not executable")
        else:
            check(WARN, "screen recording", "no hello line seen",
                  f"run {BIN} directly and read stderr")
    else:
        check(BAD, "capture built", "not compiled",
              f"cd {ROOT}/capture && swift build -c release")

    # --- daemon ---
    if os.path.exists(SOCK):
        check(OK, "action socket", SOCK)
    else:
        check(BAD, "action socket", "not listening",
              "the daemon is not running (see 'run it' below)")

    if os.path.exists(DB):
        try:
            import sqlite3
            c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=2)
            n, s, last = c.execute(
                "SELECT COUNT(*), SUM(surfaced), MAX(t) FROM frames").fetchone()
            acts = c.execute("SELECT COUNT(*) FROM actions").fetchone()[0]
            c.close()
            age = time.time() - (last or 0)
            if last and age < 120:
                rate = 1 - (s or 0) / n if n else 0
                st = OK if rate >= 0.8 else WARN
                check(st, "perceiving", f"{n} frames, suppression {rate:.0%}",
                      "" if rate >= 0.8 else
                      "under 80% means the envelopes in actionbus.py are too tight;\n"
                      "         widen the constants for whatever keeps appearing in events")
            else:
                check(WARN, "perceiving", f"log is {age/60:.0f} min stale")
            check(OK if acts else WARN, "efference copy",
                  f"{acts} actions logged",
                  "" if acts else "no actions received: hooks are not firing, or nothing\n"
                                  "         has run since the daemon started")
        except Exception as e:
            check(WARN, "event log", str(e))
    else:
        check(WARN, "event log", "no database yet", "it appears once the daemon runs")

    # --- claude code wiring ---
    if os.path.exists(SETTINGS):
        try:
            st = json.load(open(SETTINGS))
            blocks = [b for ev in ("PreToolUse", "PostToolUse")
                      for b in st.get("hooks", {}).get(ev, [])
                      for h in b.get("hooks", [])
                      if "claudeyes-hook" in (h.get("command") or "")]
            check(OK if len(blocks) >= 2 else BAD, "hooks installed",
                  f"{len(blocks)} of 2 events",
                  "" if len(blocks) >= 2 else
                  f"{sys.executable} -m claudeyes.install --apply")
        except json.JSONDecodeError:
            check(BAD, "hooks installed", "settings.json is not valid JSON")
    else:
        check(BAD, "hooks installed", "no ~/.claude/settings.json",
              f"{sys.executable} -m claudeyes.install --apply")

    if shutil.which("claude"):
        rc, out, err = run(["claude", "mcp", "list"], timeout=25.0)
        blob = out + err
        if "claudeyes" in blob:
            good = "claudeyes" in blob and "✓" in blob or "onnected" in blob
            check(OK if good else WARN, "mcp registered",
                  "claudeyes present" + ("" if good else " but may not be connected"))
        else:
            check(BAD, "mcp registered", "not in `claude mcp list`",
                  f"claude mcp add --scope user --env CLAUDEYES_DB={DB} \\\n"
                  f"           claudeyes -- {sys.executable} -m claudeyes.mcp.server")
    else:
        check(WARN, "mcp registered", "`claude` not on PATH")

    # --- report ---
    for status, name, detail, fix in results:
        print(f"[{status}] {name:<18} {detail}")
        if fix and status != OK:
            for line in fix.splitlines():
                print(f"         -> {line}" if not line.startswith("      ") else line)
    bad = sum(1 for r in results if r[0] == BAD)
    print("-" * 62)
    if bad:
        print(f"{bad} thing(s) to fix above.\n")
    else:
        print("All good. Ask Claude to call perception_status to confirm from its side.\n")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
