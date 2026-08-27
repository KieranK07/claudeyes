# claudeyes

Perception for an agent that can tell **what it did** from **what happened to it**.

Every screen-watching agent today sees one thing: "pixels changed." It cannot
distinguish the change it caused by clicking from the change the world caused on
its own. So change-triggered perception fires hardest on exactly the changes that
carry the least information.

claudeyes fixes that with an **efference copy**. Before an action executes it
registers a *predicted* screen delta. The capture loop reports the *observed*
delta. Subtract one from the other and the residual is **exafference**: change
the world produced without you. That residual is the only thing worth waking an
expensive model for.

```
   action ──► predicted delta ──┐
                                ▼
   screen ──► observed delta ──(−)──► residual ──► gate ──► wake the VLM
                                          │
                                          └── suppressed (most of it)
```

## Layout

| path | what |
|---|---|
| `capture/` | Swift ScreenCaptureKit shim. Emits one JSON line per frame. macOS only. |
| `claudeyes/grid.py` | The coarse cell grid everything else is expressed on. |
| `claudeyes/actionbus.py` | Live predicted-delta envelopes with confidence decay. |
| `claudeyes/residual.py` | observed − predicted. The core. |
| `claudeyes/eventlog.py` | SQLite append-only log. |
| `claudeyes/daemon.py` | Glue. Reads capture JSONL, writes events. |
| `claudeyes/sources/` | Where actions come from (socket, synthetic). |
| `tools/demo.py` | Synthetic trace. Runs anywhere, no Mac needed. |

## Why one grid

Observed change, predicted change, habituation state, and the priority map are
all the *same shape*: a value per screen cell. Committing to one coarse grid up
front makes phases 3 and 4 nearly free, because each is another array layer
rather than another data structure.

## Try it without a Mac

    python3 tools/demo.py

## Run it for real

    cd capture && swift build -c release
    ./.build/release/claudeyes-capture | python3 -m claudeyes.daemon

## Three things the demo taught us

1. **"Did I cause this" is not one bit.** A single suppression threshold cannot
   both silence a scroll repaint and surface a notification that lands during a
   click's uncertainty window. Cells are attributed to SELF / CONSEQUENCE /
   WORLD instead, and only WORLD interrupts.
2. **Ownership beats geometry.** A click cannot explain change in an app you
   never touched, however close it landed. Once the capture layer tags dirty
   rects with the owning app, the geometric model can be relaxed and both cases
   come out right. Geometry is the fallback, not the primary signal.
3. **A resting cursor is state, not an event.** Modelling hover as a decaying
   envelope woke the agent every time it paused over a button. Envelopes in the
   same `group` retire each other, so the resting place persists until the
   pointer actually moves.

## Status

Done: capture shim, action bus with graded and sticky envelopes, three-way
attribution, event log, tests, end-to-end smoke on any platform.

Next: habituation dynamics (spontaneous recovery, generalisation gradient,
dishabituation), the priority map's selection-history term, and the MCP surface
(`what_changed`, `recent_events`, `watch_for`).

Untested on real hardware: everything in `capture/`. It has never been
compiled -- it was written against the ScreenCaptureKit docs, not against a
running Mac. Expect to fight it.
