#!/usr/bin/env python3
"""Claude Code hook -> claudeyes efference copy.

Claude Code's tools have no screen coordinates: `Bash` does not click anywhere.
But they do have a screen *effect* -- a Bash command floods the terminal, an
edit repaints the editor -- and that effect is exactly the reafference we want
cancelled, so the agent stops waking itself up on its own build output.

Wire it into ~/.claude/settings.json (see `python3 -m claudeyes.install`).
Contract: always exit 0, always fast, never block a tool call. Perception is
best-effort; a broken hook must never break the session.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CONFIG = os.path.expanduser("~/.claudeyes/apps.json")

# How long each tool's screen echo plausibly lasts. Generous on purpose:
# over-predicting costs a missed event, under-predicting costs a false wake-up,
# and false wake-ups are the thing this project exists to kill.
EXPECT = {"Bash": 45.0, "BashOutput": 20.0, "Edit": 8.0, "Write": 8.0,
          "NotebookEdit": 8.0, "Read": 4.0, "Glob": 4.0, "Grep": 4.0,
          "WebFetch": 6.0, "WebSearch": 6.0, "Task": 90.0}

TERM_APPS = {"ghostty": "Ghostty", "iterm.app": "iTerm2", "iterm2": "iTerm2",
             "apple_terminal": "Terminal", "warpterminal": "Warp",
             "vscode": "Code", "hyper": "Hyper", "alacritty": "Alacritty",
             "kitty": "kitty", "wezterm": "WezTerm", "tabby": "Tabby"}


def apps() -> dict:
    cfg = {}
    if os.path.exists(CONFIG):
        try:
            cfg = json.load(open(CONFIG))
        except Exception:
            cfg = {}
    if not cfg.get("terminal"):
        tp = (os.environ.get("TERM_PROGRAM") or "").lower()
        cfg["terminal"] = TERM_APPS.get(tp, "Terminal")
    return cfg


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    tool = payload.get("tool_name") or ""
    event = payload.get("hook_event_name") or ""
    cfg = apps()

    # Which app is about to repaint because of this tool?
    if tool in ("Edit", "Write", "NotebookEdit") and cfg.get("editor"):
        app = cfg["editor"]
    else:
        app = cfg.get("terminal", "Terminal")

    try:
        from claudeyes.sources.socket_source import post
        if event == "PreToolUse":
            post({"kind": "tool_use", "source": "claude-code",
                  "params": {"app": app, "tool": tool,
                             "expect_seconds": EXPECT.get(tool, 20.0)}})
        elif event in ("PostToolUse", "PostToolUseFailure"):
            post({"kind": "tool_done", "source": "claude-code",
                  "params": {"app": app, "tool": tool}})
    except Exception as e:
        # Daemon not running, socket gone, anything. Not our problem to escalate.
        print(f"claudeyes-hook: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
