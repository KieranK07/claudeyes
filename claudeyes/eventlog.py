"""Append-only SQLite log. Every frame's verdict, not just the events.

Keeping the suppressed frames is the point: the ratio of suppressed to
surfaced is how you tell whether the envelope constants are any good, and
you cannot tune them from the events alone.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS frames (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  t REAL NOT NULL,
  frame_id INTEGER,
  observed_cells INTEGER,
  self_cells INTEGER,
  consequence_cells INTEGER,
  world_cells INTEGER,
  attribution TEXT,
  surfaced INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS frames_t ON frames(t);
CREATE INDEX IF NOT EXISTS frames_surfaced ON frames(surfaced, t);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  t REAL NOT NULL,
  frame_id INTEGER,
  score REAL,
  rects TEXT,
  attributions TEXT,
  note TEXT
);
CREATE INDEX IF NOT EXISTS events_t ON events(t);

CREATE TABLE IF NOT EXISTS actions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  t REAL NOT NULL,
  kind TEXT NOT NULL,
  source TEXT,
  params TEXT
);
CREATE INDEX IF NOT EXISTS actions_t ON actions(t);
"""


class EventLog:
    def __init__(self, path: str | Path = "events.db"):
        self.db = sqlite3.connect(str(path), isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    def frame(self, res, surfaced: bool) -> None:
        self.db.execute(
            "INSERT INTO frames(t,frame_id,observed_cells,self_cells,consequence_cells,"
            "world_cells,attribution,surfaced) VALUES(?,?,?,?,?,?,?,?)",
            (res.t, res.frame_id, res.observed_cells, res.self_cells,
             res.consequence_cells, res.world_cells, res.attribution.value, int(surfaced)),
        )

    def event(self, res, note: str = "") -> int:
        cur = self.db.execute(
            "INSERT INTO events(t,frame_id,score,rects,attributions,note) VALUES(?,?,?,?,?,?)",
            (res.t, res.frame_id, float(res.world_cells),
             json.dumps([r.__dict__ for r in res.rects]),
             json.dumps(res.explanations), note),
        )
        return int(cur.lastrowid)

    def action(self, a) -> None:
        self.db.execute(
            "INSERT INTO actions(t,kind,source,params) VALUES(?,?,?,?)",
            (a.t, a.kind, a.source, json.dumps(a.params)),
        )

    def since(self, t: float, limit: int = 50) -> list[dict]:
        cur = self.db.execute(
            "SELECT t,frame_id,score,rects,attributions,note FROM events "
            "WHERE t > ? ORDER BY t LIMIT ?", (t, limit))
        return [
            {"t": r[0], "frame_id": r[1], "score": r[2],
             "rects": json.loads(r[3]), "attributions": json.loads(r[4]), "note": r[5]}
            for r in cur.fetchall()
        ]

    def stats(self) -> dict:
        row = self.db.execute(
            "SELECT COUNT(*), SUM(surfaced), AVG(1.0 - CAST(world_cells AS REAL)/"
            "NULLIF(observed_cells,0)) FROM frames"
        ).fetchone()
        total, surfaced, avg = row[0] or 0, row[1] or 0, row[2] or 0.0
        return {
            "frames": total,
            "surfaced": surfaced,
            "suppressed": total - surfaced,
            "suppression_rate": (1 - surfaced / total) if total else 0.0,
            "mean_explained_fraction": avg,
        }

    def close(self) -> None:
        self.db.close()
