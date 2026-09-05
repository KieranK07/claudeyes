"""claudeyes MCP server. Gives Claude Code eyes it does not have to poll for.

    claude mcp add --scope user claudeyes -- python3 -m claudeyes.mcp.server

Reads the same SQLite log the daemon writes. Read-only: this process never
touches perception, it only answers questions about it.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time

from .jsonrpc import Server

DB = os.environ.get("CLAUDEYES_DB", os.path.expanduser("~/.claudeyes/events.db"))
srv = Server("claudeyes")


def _db() -> sqlite3.Connection | None:
    if not os.path.exists(DB):
        return None
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=2.0)
    c.row_factory = sqlite3.Row
    return c


def _events(conn, since_t: float, app: str | None, min_cells: int, limit: int) -> list[dict]:
    rows = conn.execute(
        "SELECT t, score, rects, attributions AS a, note FROM events "
        "WHERE t > ? AND score >= ? ORDER BY t DESC LIMIT ?",
        (since_t, float(min_cells), limit)).fetchall()
    out = []
    for r in rows:
        rects = json.loads(r["rects"] or "[]")
        if app and not any(str(app).lower() in json.dumps(x).lower() for x in rects):
            continue
        out.append({
            "seconds_ago": round(time.time() - r["t"], 1),
            "changed_cells": int(r["score"]),
            "where": rects[:3],
            "competing_explanations": json.loads(r["a"] or "[]")[:3],
        })
    return out


NO_DAEMON = ("claudeyes is not running. Start it with:\n"
             "  ./capture/.build/release/claudeyes-capture | python3 -m claudeyes.daemon "
             "--db ~/.claudeyes/events.db")


@srv.tool(
    "what_changed",
    "What has happened on this screen that the user's and the agent's own actions do NOT "
    "explain. Use this to pick up ambient context before answering: a notification arrived, "
    "a build finished, a window appeared. Self-caused change (typing, scrolling, your own "
    "tool output) is already filtered out and will never appear here.",
    {"type": "object", "properties": {
        "since_seconds": {"type": "number", "description": "Look back this far. Default 120.", "default": 120},
        "app": {"type": "string", "description": "Only changes in this app, e.g. 'Slack'."},
        "limit": {"type": "integer", "default": 20}}},
)
def what_changed(a: dict):
    conn = _db()
    if conn is None:
        return NO_DAEMON
    since = time.time() - float(a.get("since_seconds", 120))
    ev = _events(conn, since, a.get("app"), 2, int(a.get("limit", 20)))
    conn.close()
    if not ev:
        return f"Nothing unattributed in the last {a.get('since_seconds', 120)}s. The screen was quiet, or everything that moved was us."
    return {"unattributed_events": ev}


@srv.tool(
    "watch_for",
    "Block until something happens on screen that no action of ours explains, then return it. "
    "Use this INSTEAD of polling with sleep+screenshot when waiting on a build, a test run, a "
    "deploy, or a page load. Returns as soon as the world does something, or when the timeout "
    "expires. A call longer than ~2 minutes moves to a background task and its result arrives "
    "as a notification, which is fine and usually what you want.",
    {"type": "object", "properties": {
        "timeout_seconds": {"type": "number", "default": 90},
        "app": {"type": "string", "description": "Only wake for changes in this app."},
        "min_cells": {"type": "integer", "description": "Ignore changes smaller than this many "
                      "32px cells. Default 4 (~one small dialog).", "default": 4}}},
)
def watch_for(a: dict):
    conn = _db()
    if conn is None:
        return NO_DAEMON
    timeout = max(1.0, min(float(a.get("timeout_seconds", 90)), 900.0))
    app = a.get("app")
    min_cells = int(a.get("min_cells", 4))
    start = time.time()
    deadline = start + timeout
    try:
        while time.time() < deadline:
            ev = _events(conn, start, app, min_cells, 5)
            if ev:
                return {"woke_after_seconds": round(time.time() - start, 1), "events": ev}
            time.sleep(0.25)
    finally:
        conn.close()
    return (f"Waited {timeout:.0f}s. Nothing the world did, in {app or 'any app'}. "
            f"Either it is still working or it finished without repainting anything.")


@srv.tool(
    "perception_status",
    "Is claudeyes actually watching, and is its attribution model any good? The suppression "
    "rate is the health metric: it should be high, because most screen change is self-caused.",
    {"type": "object", "properties": {}},
)
def perception_status(a: dict):
    conn = _db()
    if conn is None:
        return NO_DAEMON
    row = conn.execute(
        "SELECT COUNT(*) n, SUM(surfaced) s, MAX(t) last FROM frames").fetchone()
    by = conn.execute(
        "SELECT attribution, COUNT(*) n FROM frames GROUP BY attribution").fetchall()
    conn.close()
    n, s, last = row["n"] or 0, row["s"] or 0, row["last"] or 0
    age = time.time() - last if last else None
    return {
        "watching": bool(age is not None and age < 60),
        "seconds_since_last_frame": round(age, 1) if age is not None else None,
        "frames_seen": n,
        "woke_the_agent": s,
        "suppression_rate": round(1 - s / n, 3) if n else None,
        "attribution_breakdown": {r["attribution"]: r["n"] for r in by},
    }


def main() -> None:
    srv.log(f"claudeyes mcp: reading {DB}")
    srv.run()


if __name__ == "__main__":
    main()
