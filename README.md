# claudeyes

A macOS perception daemon for Claude Code that only tells the agent about
screen changes **it did not cause**.

## Why it exists

Give an agent eyes and the obvious design is: watch the screen, and when pixels
change, wake up and look. That design is useless in practice, because the agent
is the loudest thing on its own screen. It runs a test suite and the terminal
floods. It moves the mouse and a button lights up. It types and the caret
blinks. Change-triggered perception fires hardest on exactly the changes that
carry no information, and the one thing you actually wanted — a build failing on
its own, a Slack message, a dialog appearing behind the window — arrives in the
same undifferentiated stream as the agent's own echo.

The fix is an old idea from motor neuroscience. When you move your eyes, the
whole visual field sweeps across your retina, and you perceive nothing: the
brain sends a copy of the motor command — an **efference copy** — to the visual
system, which predicts the resulting sensory change and cancels it. Same reason
you cannot tickle yourself. What survives the subtraction is **exafference**:
change the world produced without you. That is the signal worth reacting to.

An agent has it far easier than a brain does. A brain has to estimate its motor
consequences from noisy corollary discharge. We *know* the click was at (x, y)
and the scroll was 400 px, because we issued it. The prediction is free.

## How it works

Before an action runs, it registers a **predicted** screen delta. The capture
loop reports the **observed** delta. Subtract, and what is left is the residual.

```
   action ──► predicted delta ──┐
                                ▼
   screen ──► observed delta ──(−)──► residual ──► gate ──► wake the agent
                                          │
                                          └── suppressed (most of it)
```

Everything is expressed on one coarse grid of ~32-logical-pixel cells — observed
change, predicted change, habituation, priority are all "a value per region of
screen", so each is another array layer rather than another data structure. A
full-screen operation is a few thousand floats, and exact rectangle algebra
never has to be written.

**Predictions are envelopes, not masks.** An action licenses a region to change,
over a time window, at a confidence that decays as the window closes. A click
registers a tight, certain envelope on the thing you clicked *and* a wide,
weaker one over the window — because a click sometimes opens a modal — with the
confidence falling off by distance from the pointer, so a notification in the
far corner still survives the click's uncertainty window. Suppression is
proportional and never absolute: a fully suppressed region is a blind spot.

**"Did I cause this" is not one bit.** The first version had a single
suppression threshold and could not both silence a scroll repaint and surface a
notification landing mid-click. That is a modelling failure, not a tuning one.
Each changed cell is now attributed to one of three classes:

| class | meaning | what happens |
|---|---|---|
| `SELF` | high-confidence motor echo — cursor, hover, caret, scroll repaint | never surfaces |
| `CONSEQUENCE` | plausibly downstream of your action but not directly predicted — the page your click navigated to | surfaces, but labelled, and routed to action verification rather than to the interrupt |
| `WORLD` | nothing you did explains this | the interrupt. The whole point. |

Biology does the same thing: sensory attenuation reduces gain rather than
gating, and "was that me?" is read out separately from "did something happen?".

**Ownership beats geometry.** Geometry alone cannot tell a toolbar spinner your
click triggered from a banner that arrived on its own — both are far from your
finger. The Swift shim tags each dirty rect with the app owning the window under
it, so change in an app you never touched is foreign no matter how close it
landed. Geometry is the fallback for when ownership is unavailable.

**A resting cursor is state, not an event.** Modelling hover as a decaying
envelope woke the agent every time it paused over a button, which is the most
common thing it does. Envelopes carry a `group`; a new one retires the old, so
where the pointer came to rest stays explained until the pointer actually moves.

**Tool calls have no coordinates, but they do have an app.** `Bash` does not
click anywhere — it floods a terminal. A Claude Code `PreToolUse` hook registers
an app-scoped envelope before the tool runs and shortens it when the tool
returns, so the agent stops waking itself on its own build output. One useful
consequence: once that scope has lapsed, a terminal that repaints on its own is
`WORLD`. That is a long-running process printing something after Claude thought
it was done.

## What Claude gets

Three MCP tools, backed by an append-only SQLite log:

| tool | for |
|---|---|
| `what_changed(since_seconds)` | ambient context. What happened that we did not cause. |
| `watch_for(timeout_seconds, app)` | blocks until the world does something. Use instead of sleep-and-screenshot when waiting on a build or a deploy. Past ~2 minutes it auto-backgrounds and returns as a notification. |
| `perception_status()` | is it actually watching, and is the suppression rate healthy. |

`watch_for` is the one that changes how it feels: the agent stops polling and
starts getting woken.

## Try it without a Mac

```
pip install -e .    # installs numpy
python3 tools/demo.py
```

Runs a synthetic 13-frame trace — cursor moves, hover, click, page repaint,
scroll, typing — with three things the world does on its own dropped into it.
A correct run wakes on exactly those three:

```
 *  2.40  *** Slack message arrives ***        48   0   0   48  WAKE
 *  5.60  *** tests fail on their own ***     136   0   0  136  WAKE
 *  6.70  *** popup during the click's ... ***  48   0   0   48  WAKE
    13 frames -> 3 wake-ups
```

## Run it for real

```
cd capture && swift build -c release        # macOS 13+, Xcode toolchain
cd .. && ./run.sh                           # capture | daemon -> ~/.claudeyes/events.db
```

Grant Screen Recording permission when macOS asks, or ScreenCaptureKit returns
empty frames without erroring.

Wire it into Claude Code:

```
python3 -m claudeyes.install --apply --editor "Code"
```

That merges the `PreToolUse`/`PostToolUse` hooks into `~/.claude/settings.json`
(with a backup) and prints the two commands you still run yourself: the
`claude mcp add`, and the daemon.

```
python3 -m claudeyes.doctor
```

checks every link in the chain. Worth having, because the failure modes are
mostly silent — ScreenCaptureKit returns empty results rather than erroring
when it lacks permission, the hook exits 0 by design when it cannot reach the
socket, and an unregistered MCP server just never appears.

## Layout

| path | what |
|---|---|
| `capture/` | Swift ScreenCaptureKit shim. One JSON line per frame: dirty rects plus the owning app. macOS only. |
| `claudeyes/grid.py` | The coarse cell grid everything else is expressed on. |
| `claudeyes/actionbus.py` | Predicted-delta envelopes: decay, distance falloff, sticky groups, app scopes. |
| `claudeyes/residual.py` | observed − predicted, and the three-way attribution. The core. |
| `claudeyes/eventlog.py` | Append-only SQLite log. Every frame, not just surfaced ones. |
| `claudeyes/daemon.py` | Glue. Capture JSONL in, events out. |
| `claudeyes/mcp/` | The MCP server and a small JSON-RPC stdio implementation. |
| `claudeyes/install.py` | Merges the hooks into `~/.claude/settings.json`. |
| `claudeyes/doctor.py` | Diagnoses the pipeline. |
| `hooks/` | The `PreToolUse`/`PostToolUse` hook itself. |
| `tools/demo.py` | Synthetic trace. Runs anywhere, no Mac needed. |
| `bridge/` | Unrelated side tool: a deliberately tiny allowlisted stdio MCP shell, so a cloud session can run `swift build` on this Mac. Read it before you register it. |

## Status

Prototype. The model is the finished part; the plumbing is not.

Working: the grid, the action bus, three-way attribution, the event log, the
MCP server, the Claude Code hooks, the installer and the doctor. 12 unit tests
pass (`python3 -m unittest discover -s tests`) covering confidence decay,
attribution, the sticky-cursor case and the gate. `tools/demo.py` runs the
whole loop end to end on any platform with no Mac and no capture binary.

The Swift shim compiles clean against the current toolchain, but **it has not
been run through a real session with Screen Recording granted**, so the frame
rate, the dirty-rect fidelity and the window-ownership index are all unproven
against a live desktop. That is the gap between this being a nice model and
being usable daily.

Not built: habituation dynamics (spontaneous recovery, generalisation gradient,
dishabituation) and the priority map's selection-history term. Both already have
their array layer allocated on the grid and are currently identity.

The envelope constants in `actionbus.py` are the actual content of the model and
they were tuned against the synthetic trace, not against a real desktop. Expect
to retune them. They are deliberately generous — over-predicting costs a missed
event, under-predicting costs a false wake-up, and a false wake-up is the
failure mode this whole thing exists to kill.

## License

MIT. See [LICENSE](LICENSE).
