# Design notes

## Why it exists

Give an agent eyes and the obvious design is: watch the screen, and when pixels
change, wake up and look. That design is useless in practice, because the agent
is the loudest thing on its own screen. It runs a test suite and the terminal
floods. It moves the mouse and a button lights up. It types and the caret
blinks. Change-triggered perception fires hardest on exactly the changes that
carry no information. The things worth seeing (a build failing on its own, a
Slack message, a dialog appearing behind the window) arrive in the same
undifferentiated stream as the agent's own echo.

The fix is an old idea from motor neuroscience. When you move your eyes, the
whole visual field sweeps across your retina, and you perceive nothing: the
brain sends a copy of the motor command, an **efference copy**, to the visual
system, which predicts the resulting sensory change and cancels it. Same reason
you cannot tickle yourself. What survives the subtraction is **exafference**:
change the world produced without you. That is the signal worth reacting to.

An agent has it far easier than a brain does. A brain has to estimate its motor
consequences from noisy corollary discharge. The agent *knows* the click was at
(x, y) and the scroll was 400 px, because it issued them. The prediction is free.

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

Everything is expressed on one coarse grid of ~32-logical-pixel cells. Observed
change, predicted change, habituation and priority are all "a value per region
of screen", so each is another array layer rather than another data structure.
A full-screen operation is a few thousand floats, and exact rectangle algebra
never has to be written.

**Predictions are envelopes, not masks.** An action licenses a region to change,
over a time window, at a confidence that decays as the window closes. A click
registers a tight, certain envelope on the thing clicked *and* a wide, weaker
one over the window, because a click sometimes opens a modal. Confidence falls
off by distance from the pointer, so a notification in the far corner still
survives the click's uncertainty window. Suppression is proportional and never
absolute: a fully suppressed region is a blind spot.

**"Did I cause this" is not one bit.** The first version had a single
suppression threshold and could not both silence a scroll repaint and surface a
notification landing mid-click. That is a modelling failure, not a tuning one.
Each changed cell is now attributed to one of three classes:

| class | meaning | what happens |
|---|---|---|
| `SELF` | high-confidence motor echo: cursor, hover, caret, scroll repaint | never surfaces |
| `CONSEQUENCE` | plausibly downstream of the action but not directly predicted, e.g. the page a click navigated to | surfaces, labelled, and routed to action verification rather than to the interrupt |
| `WORLD` | nothing the agent did explains this | the interrupt. The whole point. |

Biology does the same thing: sensory attenuation reduces gain rather than
gating, and "was that me?" is read out separately from "did something happen?".

**Ownership beats geometry.** Geometry alone cannot tell a toolbar spinner the
click triggered from a banner that arrived on its own; both are far from the
pointer. The Swift shim tags each dirty rect with the app owning the window
under it, so change in an app the agent never touched is foreign no matter how
close it landed. Geometry is the fallback when ownership is unavailable.

**A resting cursor is state, not an event.** Modelling hover as a decaying
envelope woke the agent every time it paused over a button, which is the most
common thing it does. Envelopes carry a `group`; a new one retires the old, so
where the pointer came to rest stays explained until the pointer actually moves.

**Tool calls have no coordinates, but they do have an app.** `Bash` does not
click anywhere; it floods a terminal. A Claude Code `PreToolUse` hook registers
an app-scoped envelope before the tool runs and shortens it when the tool
returns, so the agent stops waking itself on its own build output. Once that
scope has lapsed, a terminal that repaints on its own is `WORLD`: a
long-running process printing something after Claude thought it was done.

## Tuning

The envelope constants in `claudeyes/actionbus.py` are the actual content of
the model, and they were tuned against the synthetic trace, not a real desktop.
Expect to retune them. They are deliberately generous: over-predicting costs a
missed event, under-predicting costs a false wake-up, and a false wake-up is
the failure mode this whole thing exists to kill.

## Not built yet

Habituation dynamics (spontaneous recovery, generalisation gradient,
dishabituation) and the priority map's selection-history term. Both already
have their array layer allocated on the grid and are currently identity.
