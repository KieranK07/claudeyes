"""The coarse cell grid every layer is expressed on.

Observed change, predicted change, habituation and priority are all "a value
per region of screen". Rather than four data structures we commit to one grid
and let each layer be another array over it. Exact rectangle algebra is not
worth it here: a cell is ~32 logical pixels, which is finer than any UI event
we care about and coarse enough that a full-screen op is a few thousand floats.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np

CELL = 32  # logical px per cell


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def area(self) -> float:
        return max(0.0, self.w) * max(0.0, self.h)

    def inflate(self, m: float) -> "Rect":
        return Rect(self.x - m, self.y - m, self.w + 2 * m, self.h + 2 * m)

    @staticmethod
    def from_any(v) -> "Rect":
        if isinstance(v, Rect):
            return v
        if isinstance(v, dict):
            return Rect(float(v["x"]), float(v["y"]), float(v["w"]), float(v["h"]))
        x, y, w, h = v
        return Rect(float(x), float(y), float(w), float(h))


class Grid:
    """Maps screen coordinates onto a fixed cell lattice."""

    def __init__(self, width: int, height: int, cell: int = CELL):
        self.width = int(width)
        self.height = int(height)
        self.cell = int(cell)
        self.cols = max(1, -(-self.width // self.cell))   # ceil
        self.rows = max(1, -(-self.height // self.cell))

    @property
    def shape(self) -> tuple[int, int]:
        return (self.rows, self.cols)

    @property
    def n_cells(self) -> int:
        return self.rows * self.cols

    def zeros(self, dtype=np.float32) -> np.ndarray:
        return np.zeros(self.shape, dtype=dtype)

    def bounds(self, r: Rect) -> tuple[int, int, int, int]:
        """Cell index bounds (r0, r1, c0, c1) half-open, clamped to the grid."""
        c0 = int(np.floor(r.x / self.cell))
        r0 = int(np.floor(r.y / self.cell))
        c1 = int(np.ceil((r.x + r.w) / self.cell))
        r1 = int(np.ceil((r.y + r.h) / self.cell))
        c0 = max(0, min(self.cols, c0))
        c1 = max(0, min(self.cols, c1))
        r0 = max(0, min(self.rows, r0))
        r1 = max(0, min(self.rows, r1))
        return r0, r1, c0, c1

    def stamp(self, mask: np.ndarray, r: Rect, value: float = 1.0, mode: str = "max") -> np.ndarray:
        """Write `value` into the cells a rect touches."""
        r0, r1, c0, c1 = self.bounds(r)
        if r0 >= r1 or c0 >= c1:
            return mask
        view = mask[r0:r1, c0:c1]
        if mode == "max":
            np.maximum(view, value, out=view)
        elif mode == "add":
            view += value
        else:
            view[...] = value
        return mask

    def cell_centers(self):
        """(ys, xs) screen coordinates of every cell centre. Cached."""
        if not hasattr(self, "_centers"):
            ys = (np.arange(self.rows, dtype=np.float32) + 0.5) * self.cell
            xs = (np.arange(self.cols, dtype=np.float32) + 0.5) * self.cell
            self._centers = (ys[:, None], xs[None, :])
        return self._centers

    def stamp_graded(self, mask: np.ndarray, r: Rect, peak: float,
                     center: tuple[float, float], sigma: float,
                     floor: float = 0.0) -> np.ndarray:
        """Stamp a rect whose confidence falls off with distance from a point.

        A click licenses the thing you clicked to change, and licenses the rest
        of the window to change *less* the further it is from your finger. A
        banner in the far corner is not something your click explains.
        """
        r0, r1, c0, c1 = self.bounds(r)
        if r0 >= r1 or c0 >= c1:
            return mask
        ys, xs = self.cell_centers()
        dy = ys[r0:r1] - float(center[1])
        dx = xs[:, c0:c1] - float(center[0])
        d2 = dy ** 2 + dx ** 2
        g = np.exp(-d2 / (2.0 * max(1.0, sigma) ** 2))
        val = (peak * (floor + (1.0 - floor) * g)).astype(np.float32)
        view = mask[r0:r1, c0:c1]
        np.maximum(view, val, out=view)
        return mask

    def rasterize(self, rects, value: float = 1.0) -> np.ndarray:
        m = self.zeros()
        for r in rects:
            self.stamp(m, Rect.from_any(r), value)
        return m

    def full(self) -> Rect:
        return Rect(0, 0, self.width, self.height)

    def cells_to_rects(self, mask: np.ndarray, threshold: float = 0.5) -> list[Rect]:
        """Merge lit cells into a small set of bounding rects, row-run then
        vertical coalesce. Good enough to hand a crop to a VLM."""
        lit = mask > threshold
        runs: list[tuple[int, int, int]] = []  # (row, c0, c1)
        for r in range(self.rows):
            row = lit[r]
            c = 0
            while c < self.cols:
                if row[c]:
                    c0 = c
                    while c < self.cols and row[c]:
                        c += 1
                    runs.append((r, c0, c))
                else:
                    c += 1
        out: list[Rect] = []
        open_runs: dict[tuple[int, int], tuple[int, int]] = {}  # (c0,c1) -> (r0, r_last)
        for r in range(self.rows):
            here = {(c0, c1) for (rr, c0, c1) in runs if rr == r}
            for key in list(open_runs):
                if key not in here:
                    r0, rl = open_runs.pop(key)
                    out.append(self._rect_of(r0, rl + 1, key[0], key[1]))
            for key in here:
                if key in open_runs:
                    r0, _ = open_runs[key]
                    open_runs[key] = (r0, r)
                else:
                    open_runs[key] = (r, r)
        for key, (r0, rl) in open_runs.items():
            out.append(self._rect_of(r0, rl + 1, key[0], key[1]))
        return out

    def _rect_of(self, r0: int, r1: int, c0: int, c1: int) -> Rect:
        x = c0 * self.cell
        y = r0 * self.cell
        return Rect(x, y, min(c1 * self.cell, self.width) - x,
                    min(r1 * self.cell, self.height) - y)
