# claudeyes

A macOS perception daemon for Claude Code that only tells the agent about
screen changes **it did not cause**.

```
       t  what happened                                 obs  self  cons  world  verdict
    0.00  agent moves the cursor                         66    66     0      0  quiet
    0.62  button depresses, toolbar spinner             108    12    96      0  consequence of my action
    1.30  page repaints after the click                1392    95  1297      0  consequence of my action
 *  2.40  *** Slack message arrives ***                  48     0     0     48  WAKE  <- 1 region(s)
    3.00  agent scrolls                                1392  1392     0      0  quiet
 *  5.60  *** tests fail on their own ***               136     0     0    136  WAKE  <- 1 region(s)
 *  6.70  *** popup during the click's wide window ***   48     0     0     48  WAKE  <- 1 region(s)
  13 frames -> 3 wake-ups
```

<sub>Excerpt of `tools/demo.py` output on a synthetic trace.</sub>

An agent is the loudest thing on its own screen, so naive change detection
wakes it on its own echo. claudeyes borrows the **efference copy** from motor
neuroscience: every action registers a predicted screen delta, the capture loop
reports the observed delta, and only the residual can wake the agent. Each
changed region is labelled `SELF` (suppressed), `CONSEQUENCE` (downstream of an
action, used for verification) or `WORLD` (the interrupt).
See [docs/design.md](docs/design.md) for the full model.

## Try it without a Mac

```
pip install -e .    # installs numpy
python3 tools/demo.py
```

Runs a synthetic 13-frame trace (cursor moves, hover, click, repaint, scroll,
typing) with three outside events dropped in. A correct run wakes on exactly
those three.

## Run it for real

```
cd capture && swift build -c release        # macOS 13+, Xcode toolchain
cd .. && ./run.sh                           # capture | daemon -> ~/.claudeyes/events.db
python3 -m claudeyes.install --apply --editor "Code"
python3 -m claudeyes.doctor
```

Grant Screen Recording permission when asked, or ScreenCaptureKit returns empty
frames without erroring. `install` merges the `PreToolUse`/`PostToolUse` hooks
into `~/.claude/settings.json` (with a backup) and prints the `claude mcp add`
command to run. `doctor` checks every link in the chain, since most failures
here are silent.

## MCP tools

| tool | for |
|---|---|
| `what_changed(since_seconds)` | Ambient context: what happened that the agent did not cause. |
| `watch_for(timeout_seconds, app)` | Blocks until the world does something. Replaces sleep-and-screenshot while waiting on a build. |
| `perception_status()` | Whether it is watching, and whether the suppression rate is healthy. |

## Layout

| path | what |
|---|---|
| `capture/` | Swift ScreenCaptureKit shim: dirty rects plus owning app, one JSON line per frame. |
| `claudeyes/actionbus.py` | Predicted-delta envelopes. |
| `claudeyes/residual.py` | Observed minus predicted, and the three-way attribution. |
| `claudeyes/daemon.py` | Capture JSONL in, events to an append-only SQLite log out. |
| `claudeyes/mcp/` | MCP server. |
| `hooks/` | Claude Code tool hook. |
| `bridge/` | Unrelated: a small allowlisted stdio MCP shell for running `swift build` from a cloud session. |

## Status

Prototype. The model, event log, MCP server, hooks, installer and doctor work,
and 12 unit tests pass (`python3 -m unittest discover -s tests`). The Swift
shim compiles but has not yet run a real session with Screen Recording
granted, so frame rate and dirty-rect fidelity are unproven on a live desktop.

## License

MIT. See [LICENSE](LICENSE).
