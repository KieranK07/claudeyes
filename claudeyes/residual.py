"""observed - predicted = exafference.

The first version of this file had a single suppression threshold, and it could
not simultaneously silence a scroll repaint and surface a notification that
landed during a click's uncertainty window. That is not a tuning problem, it is
a modelling problem: "did I cause this" is not one bit.

So each changed cell is attributed to one of three classes:

  SELF         high-confidence motor echo -- the cursor, the hover, the caret,
               the scroll repaint. Zero information. Never surfaces.
  CONSEQUENCE  plausibly downstream of your action but not directly predicted --
               the page your click navigated to. Surfaces, but labelled, and
               routed to action-effect verification rather than to the interrupt.
  WORLD        nothing you did explains this. The interrupt. The whole point.

Biology does the same thing: sensory attenuation reduces gain, it does not gate,
and "was that me?" is read out separately from "did something happen?".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import numpy as np

from .grid import Grid, Rect
from .actionbus import ActionBus

SELF_CONF = 0.85         # at or above: direct motor echo
CONSEQUENCE_CONF = 0.30  # at or above: plausibly downstream of an action


class Attribution(str, Enum):
    SELF = "self"
    CONSEQUENCE = "consequence"
    WORLD = "world"


@dataclass
class Observation:
    t: float
    dirty: list
    frame_id: int = 0
    meta: dict = field(default_factory=dict)


@dataclass
class Residual:
    t: float
    frame_id: int
    observed_cells: int
    self_cells: int
    consequence_cells: int
    world_cells: int
    attribution: Attribution
    surface: bool
    rects: list                  # bounding rects of the WORLD region
    consequence_rects: list
    explanations: list

    @property
    def explained_fraction(self) -> float:
        if not self.observed_cells:
            return 1.0
        return 1.0 - self.world_cells / self.observed_cells


class Detector:
    def __init__(
        self,
        grid: Grid,
        bus: ActionBus,
        min_cells: int = 2,        # ~64x32 logical px; ignore specks
        refractory: float = 0.20,  # enforced quiet after surfacing
    ):
        self.grid = grid
        self.bus = bus
        self.min_cells = min_cells
        self.refractory = refractory
        self._last_surfaced_t = -1e9
        # Phase 3 rides on the same grid. Identity until then.
        self.habituation = grid.zeros()
        self.priority = np.ones(grid.shape, dtype=np.float32)

    def classify(self, obs: Observation):
        """Per-cell attribution for one frame. Cheap: a few array ops.

        Geometry alone cannot tell a toolbar spinner triggered by your click
        from a notification banner that arrived on its own -- both are far from
        your finger. Ownership can. If the capture layer tags a dirty rect with
        the app that owns the window under it, and that app is not the one you
        acted on, then no action of yours explains it, whatever the distance.
        Geometry is the fallback for when ownership is unavailable.
        """
        self.bus.prune(obs.t)
        observed = self.grid.rasterize(obs.dirty) > 0.5
        predicted = self.bus.predicted_mask(obs.t)

        acted_apps = self.bus.recent_apps(obs.t)
        if acted_apps:
            foreign = self.grid.zeros()
            tagged = False
            for r in obs.dirty:
                app = r.get("app") if isinstance(r, dict) else None
                if app is None:
                    continue
                tagged = True
                if app not in acted_apps:
                    self.grid.stamp(foreign, Rect.from_any(r), 1.0)
            if tagged:
                predicted = predicted * (1.0 - foreign)

        gain = (1.0 - self.habituation) * self.priority
        live = observed & (gain > 0.15)

        is_self = live & (predicted >= SELF_CONF)
        is_cons = live & (predicted >= CONSEQUENCE_CONF) & ~is_self
        is_world = live & ~is_self & ~is_cons
        return observed, is_self, is_cons, is_world

    def process(self, obs: Observation) -> Residual | None:
        observed, is_self, is_cons, is_world = self.classify(obs)

        n_obs = int(observed.sum())
        n_self = int(is_self.sum())
        n_cons = int(is_cons.sum())
        n_world = int(is_world.sum())

        if n_world >= self.min_cells:
            attr = Attribution.WORLD
        elif n_cons >= self.min_cells:
            attr = Attribution.CONSEQUENCE
        else:
            attr = Attribution.SELF

        surface = attr is Attribution.WORLD
        if surface and obs.t - self._last_surfaced_t < self.refractory:
            surface = False
        elif surface:
            self._last_surfaced_t = obs.t

        res = Residual(
            t=obs.t, frame_id=obs.frame_id, observed_cells=n_obs,
            self_cells=n_self, consequence_cells=n_cons, world_cells=n_world,
            attribution=attr, surface=surface,
            rects=self.grid.cells_to_rects(is_world.astype(np.float32)),
            consequence_rects=self.grid.cells_to_rects(is_cons.astype(np.float32)),
            explanations=self.bus.explain(obs.t),
        )

        return res
