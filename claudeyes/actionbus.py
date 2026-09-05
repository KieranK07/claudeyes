"""Efference copy: what the agent (or the human) just did, and what it should
therefore expect to see change.

The biology this imitates has to *estimate* its own motor consequences from
noisy corollary discharge. We don't. We know the click was at (x, y) and the
scroll was 400px. That is the whole reason this is cheap.

An action registers one or more Envelopes. An envelope is a region of screen
that this action licenses to change, over a time window, at a confidence that
decays as the window runs out. Confidence matters: a click *usually* changes
only the thing you clicked, but it may open a modal or navigate, so a click
also registers a wide, low-confidence envelope. Suppression is proportional,
never absolute -- a fully-suppressed region is a blind spot.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable
import numpy as np

from .grid import Grid, Rect

HOLD_FRAC = 0.4  # fraction of the window held at peak confidence before decay


@dataclass
class Envelope:
    rect: Rect
    t_start: float
    t_end: float
    peak: float = 1.0
    label: str = ""
    center: tuple[float, float] | None = None  # falloff origin, screen coords
    sigma: float = 0.0                         # falloff scale in px
    floor: float = 0.0                         # confidence far from centre
    group: str = ""                            # same group -> newer replaces older
    app: str = ""                              # scope to an app instead of a rect

    def confidence(self, t: float) -> float:
        if t < self.t_start or t >= self.t_end:
            return 0.0
        dur = self.t_end - self.t_start
        hold_until = self.t_start + HOLD_FRAC * dur
        if t <= hold_until:
            return self.peak
        remaining = (self.t_end - t) / max(1e-6, self.t_end - hold_until)
        return self.peak * max(0.0, remaining)


@dataclass
class Action:
    kind: str
    t: float
    params: dict = field(default_factory=dict)
    source: str = "agent"   # "agent" | "human" -- the bus does not care which


def _click_point(p: dict) -> tuple[float, float]:
    if "bbox" in p:
        b = Rect.from_any(p["bbox"])
        return (b.x + b.w / 2, b.y + b.h / 2)
    return (float(p.get("x", 0)), float(p.get("y", 0)))


def envelopes_for(action: Action, grid: Grid) -> list[Envelope]:
    """Map an action to what it licenses to change.

    These constants are the actual content of the model. They are deliberately
    generous: over-predicting costs you a missed event, under-predicting costs
    you a false wake-up, and a false wake-up is the failure mode this project
    exists to kill. Tune them against a real trace, not against intuition.
    """
    t, p = action.t, action.params
    k = action.kind
    screen = grid.full()

    if k == "click":
        env: list[Envelope] = []
        if "bbox" in p:
            env.append(Envelope(Rect.from_any(p["bbox"]).inflate(8), t, t + 0.35, 1.0, "click:target"))
        else:
            x, y = float(p.get("x", 0)), float(p.get("y", 0))
            env.append(Envelope(Rect(x - 48, y - 24, 96, 48), t, t + 0.35, 1.0, "click:point"))
        # A click may navigate, open a menu or raise a modal, so it licenses the
        # whole window -- but less and less the further from your finger. This
        # falloff is what lets a corner notification survive a click's window.
        cx, cy = _click_point(p)
        env.append(Envelope(Rect.from_any(p.get("window", screen)), t + 0.03, t + 1.8,
                            0.95, "click:consequence",
                            center=(cx, cy), sigma=420.0, floor=0.40))
        return env

    if k == "scroll":
        vp = Rect.from_any(p.get("viewport", screen))
        return [
            Envelope(vp, t, t + 0.30, 1.0, "scroll"),
            Envelope(vp, t + 0.20, t + 1.10, 0.9, "scroll:momentum"),
        ]

    if k == "type":
        if "caret" in p:
            c = Rect.from_any(p["caret"])
            line = Rect(c.x - 8, c.y - 6, max(c.w, 24) + 900, c.h + 12)
        else:
            line = Rect.from_any(p.get("field", screen))
        return [
            Envelope(line, t, t + 0.22, 1.0, "type:caret"),
            Envelope(Rect.from_any(p.get("field", line)), t, t + 0.6, 0.9, "type:field"),
        ]

    if k == "key":
        # Shortcuts legitimately repaint everything. Wide, but never certain.
        return [Envelope(screen, t, t + 0.6, 0.8, f"key:{p.get('combo','')}")]

    if k == "mouse_move":
        # The single largest source of false wake-ups if left unmodelled.
        x0, y0 = float(p.get("x0", 0)), float(p.get("y0", 0))
        x1, y1 = float(p.get("x1", x0)), float(p.get("y1", y0))
        r = Rect(min(x0, x1) - 24, min(y0, y1) - 24, abs(x1 - x0) + 48, abs(y1 - y0) + 48)
        rest = Rect(x1 - 40, y1 - 40, 80, 80)
        return [
            # The travel path repaints briefly.
            Envelope(r, t, t + 0.25, 1.0, "cursor:travel", group="cursor"),
            # Where the pointer came to REST is sticky. A hover highlight lasts
            # as long as the cursor sits there, not for some decay constant, so
            # this envelope does not expire -- the next mouse_move retires it.
            # Modelling hover as a decaying event woke the agent every time it
            # paused over a button, which is the most common thing it does.
            Envelope(rest.inflate(72), t, t + 3600.0, 0.95, "cursor:rest", group="cursor"),
        ]

    if k in ("window_move", "window_resize"):
        a = Rect.from_any(p["from"])
        b = Rect.from_any(p["to"])
        u = Rect(min(a.x, b.x), min(a.y, b.y),
                 max(a.x + a.w, b.x + b.w) - min(a.x, b.x),
                 max(a.y + a.h, b.y + b.h) - min(a.y, b.y))
        return [Envelope(u, t, t + 0.45, 1.0, k)]

    if k == "tool_use":
        # An agent's tool call has no screen coordinates. Its screen effect is
        # "the app hosting this is about to repaint": a Bash command fills the
        # terminal, an edit redraws the editor. So the envelope is scoped to an
        # app rather than to a rectangle, and ownership does the rest.
        app = p.get("app") or ""
        if not app:
            return []
        hold = float(p.get("expect_seconds", 20.0))
        return [Envelope(screen, t, t + hold, 0.95, f"tool:{p.get('tool','?')}",
                         group=f"tool:{app}", app=app)]

    if k == "app_switch":
        return [Envelope(screen, t, t + 0.9, 0.9, "app_switch")]

    # Unknown action: license nothing. Better to wake up spuriously than to
    # silently blind yourself on an action kind you forgot to model.
    return []


class ActionBus:
    """Holds live envelopes and renders the predicted-change mask."""

    def __init__(self, grid: Grid, horizon: float = 3.0):
        self.grid = grid
        self.horizon = horizon
        self._env: list[Envelope] = []
        self._log: list[Action] = []

    def register(self, action: Action) -> list[Envelope]:
        envs = envelopes_for(action, self.grid)
        groups = {e.group for e in envs if e.group}
        if groups:
            self._env = [e for e in self._env if e.group not in groups]
        self._env.extend(envs)
        self._log.append(action)
        return envs

    def prune(self, now: float) -> None:
        self._env = [e for e in self._env if e.group or e.t_end > now - self.horizon]

    def active(self, t: float) -> list[tuple[Envelope, float]]:
        out = [(e, e.confidence(t)) for e in self._env]
        return [(e, c) for e, c in out if c > 0.0]

    def predicted_mask(self, t: float) -> np.ndarray:
        """Per-cell confidence that any change here is self-caused."""
        m = self.grid.zeros()
        for env, conf in self.active(t):
            if env.center is not None and env.sigma > 0:
                self.grid.stamp_graded(m, env.rect, conf, env.center, env.sigma, env.floor)
            else:
                self.grid.stamp(m, env.rect, conf, mode="max")
        return m

    def app_confidence(self, t: float) -> dict[str, float]:
        """Apps that something we did has licensed to repaint, and how sure."""
        out: dict[str, float] = {}
        for env, conf in self.active(t):
            if env.app:
                out[env.app] = max(out.get(env.app, 0.0), conf)
        return out

    def close_app_scope(self, app: str, t: float, tail: float = 1.5) -> None:
        """A tool finished. Its echo should be over shortly, so shorten rather
        than cut -- the last of the output is still arriving."""
        for e in self._env:
            if e.app == app and e.t_end > t + tail:
                e.t_end = t + tail

    def recent_apps(self, t: float, window: float = 2.5) -> set[str]:
        """Apps this actor has touched lately. Change outside them is foreign."""
        apps = {a.params.get("app") for a in self._log if 0 <= t - a.t <= window}
        apps |= set(self.app_confidence(t))   # long-running tool scopes count too
        apps.discard(None)
        apps.discard("")
        return apps

    def explain(self, t: float) -> list[str]:
        return [f"{e.label}@{c:.2f}" for e, c in sorted(self.active(t), key=lambda x: -x[1])]
