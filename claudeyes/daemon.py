"""Glue. Capture frames in on stdin, events out.

    ./capture/.build/release/claudeyes-capture | python3 -m claudeyes.daemon

Every frame is logged, not just the surfaced ones. The suppressed:surfaced
ratio is the only way to tell whether the envelope constants in actionbus are
any good, and you cannot recover it from the events alone.
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from .grid import Grid
from .actionbus import ActionBus, Action
from .residual import Detector, Observation, Attribution
from .eventlog import EventLog
from .sources.socket_source import SocketActionSource, DEFAULT_PATH


def main() -> int:
    ap = argparse.ArgumentParser(prog="claudeyes")
    ap.add_argument("--db", default="events.db")
    ap.add_argument("--sock", default=DEFAULT_PATH)
    ap.add_argument("--width", type=int, default=0, help="override; else from first frame")
    ap.add_argument("--height", type=int, default=0)
    ap.add_argument("--quiet", action="store_true", help="log only, do not print")
    ap.add_argument("--stats-every", type=float, default=30.0)
    args = ap.parse_args()

    grid: Grid | None = None
    bus: ActionBus | None = None
    det: Detector | None = None
    log = EventLog(args.db)
    pending: list[dict] = []

    def on_action(msg: dict) -> None:
        pending.append(msg)

    src = SocketActionSource(on_action, args.sock)
    src.start()
    if not args.quiet:
        print(f"claudeyes: actions on {args.sock}, log {args.db}", file=sys.stderr)

    last_stats = time.time()
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                frame = json.loads(line)
            except json.JSONDecodeError:
                continue

            if frame.get("type") == "hello" or grid is None:
                w = args.width or int(frame.get("width", 1512))
                h = args.height or int(frame.get("height", 982))
                grid = Grid(w, h)
                bus = ActionBus(grid)
                det = Detector(grid, bus)
                if not args.quiet:
                    print(f"claudeyes: grid {grid.cols}x{grid.rows} for {w}x{h}", file=sys.stderr)
                if frame.get("type") == "hello":
                    continue

            while pending:
                m = pending.pop(0)
                a = Action(kind=m.get("kind", ""), t=float(m.get("t", time.time())),
                           params=m.get("params", {}), source=m.get("source", "agent"))
                bus.register(a)
                log.action(a)

            dirty = frame.get("dirty") or []
            if not dirty:
                continue
            obs = Observation(t=float(frame.get("t", time.time())),
                              dirty=dirty, frame_id=int(frame.get("frame", 0)),
                              meta=frame)
            res = det.process(obs)
            if res is None:
                continue
            log.frame(res, surfaced=res.surface)
            if res.surface:
                eid = log.event(res, note="unattributed")
                if not args.quiet:
                    r = res.rects[0] if res.rects else None
                    where = f"{int(r.x)},{int(r.y)} {int(r.w)}x{int(r.h)}" if r else "?"
                    print(json.dumps({"event": eid, "t": round(res.t, 3),
                                      "cells": res.world_cells, "where": where,
                                      "competing": res.explanations[:3]}), flush=True)

            now = time.time()
            if args.stats_every and now - last_stats > args.stats_every:
                last_stats = now
                if not args.quiet:
                    print(f"claudeyes: {log.stats()}", file=sys.stderr)
    except KeyboardInterrupt:
        pass
    finally:
        src.stop()
        if not args.quiet:
            print(f"claudeyes: final {log.stats()}", file=sys.stderr)
        log.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
