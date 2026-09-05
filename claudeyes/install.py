"""Wire claudeyes into Claude Code.

    python3 -m claudeyes.install          # show what would change
    python3 -m claudeyes.install --apply  # do it

Merges into ~/.claude/settings.json rather than overwriting it. Your existing
hooks are preserved; a claudeyes entry that is already there is replaced, not
duplicated.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "hooks", "claudeyes-hook.py")
SETTINGS = os.path.expanduser("~/.claude/settings.json")
HOME = os.path.expanduser("~/.claudeyes")

# Everything Claude Code does that repaints something. Read/Glob/Grep are in
# because their output scrolls the terminal too.
MATCHER = "Bash|BashOutput|Edit|Write|NotebookEdit|Read|Glob|Grep|WebFetch|WebSearch|Task"


def hook_entry() -> dict:
    return {"matcher": MATCHER,
            "hooks": [{"type": "command",
                       "command": f"{sys.executable} {HOOK}",
                       "timeout": 5000}]}


def is_ours(block: dict) -> bool:
    return any("claudeyes-hook" in (h.get("command") or "")
               for h in block.get("hooks", []))


def merge(settings: dict) -> dict:
    hooks = settings.setdefault("hooks", {})
    for event in ("PreToolUse", "PostToolUse"):
        lst = hooks.setdefault(event, [])
        hooks[event] = [b for b in lst if not is_ours(b)] + [hook_entry()]
    return settings


def main() -> int:
    ap = argparse.ArgumentParser(prog="claudeyes.install")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--editor", help='App name of your editor, e.g. "Code"')
    args = ap.parse_args()

    os.makedirs(HOME, exist_ok=True)
    cfg_path = os.path.join(HOME, "apps.json")
    if args.editor:
        cfg = json.load(open(cfg_path)) if os.path.exists(cfg_path) else {}
        cfg["editor"] = args.editor
        if args.apply:
            json.dump(cfg, open(cfg_path, "w"), indent=2)

    settings = {}
    if os.path.exists(SETTINGS):
        try:
            settings = json.load(open(SETTINGS))
        except json.JSONDecodeError:
            print(f"! {SETTINGS} is not valid JSON. Fix it first; not touching it.")
            return 1
    merged = merge(json.loads(json.dumps(settings)))

    print(f"\nsettings file : {SETTINGS}")
    print(f"hook script   : {HOOK}")
    print(f"\nwould add to hooks.PreToolUse and hooks.PostToolUse:\n")
    print(json.dumps(hook_entry(), indent=2))

    if not args.apply:
        print("\n(dry run) re-run with --apply to write it.\n")
    else:
        os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
        if os.path.exists(SETTINGS):
            shutil.copy2(SETTINGS, SETTINGS + ".claudeyes-backup")
            print(f"\nbacked up -> {SETTINGS}.claudeyes-backup")
        json.dump(merged, open(SETTINGS, "w"), indent=2)
        print("written.")

    print("\nThen register the MCP server (once):\n")
    print(f"  claude mcp add --scope user \\\n"
          f"    --env CLAUDEYES_DB={HOME}/events.db \\\n"
          f"    claudeyes -- {sys.executable} -m claudeyes.mcp.server\n")
    print("And run the daemon (it must be running for any of this to do anything):\n")
    print(f"  cd {ROOT}/capture && swift build -c release\n"
          f"  {ROOT}/capture/.build/release/claudeyes-capture | \\\n"
          f"    {sys.executable} -m claudeyes.daemon --db {HOME}/events.db\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
