#!/usr/bin/env python3
"""Synthetic trace. Proves the loop without a Mac, a capture build, or a model.

Each row is one frame. The question every row answers is the only question
claudeyes exists to answer: did the world do this, or did we?
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeyes.grid import Grid, Rect
from claudeyes.actionbus import ActionBus, Action
from claudeyes.residual import Detector, Observation

W, H = 1512, 982
grid = Grid(W, H)
bus = ActionBus(grid)
det = Detector(grid, bus)

BUTTON  = {"x": 620, "y": 430, "w": 150, "h": 44}
VIEWPORT= {"x": 0,   "y": 90,  "w": W,   "h": H - 90}
CARET   = {"x": 300, "y": 700, "w": 3,   "h": 20}
BANNER  = {"x": W-380, "y": 40, "w": 360, "h": 90, "app": "Notification Center"}
FAILPANE= {"x": 40,  "y": H-260, "w": 520, "h": 220, "app": "Terminal"}

# (t, action_or_None, dirty_rects, what a human would call it)
TRACE = [
    (0.00, Action("mouse_move", 0.00, {"x0":400,"y0":300,"x1":690,"y1":450,"app":"Safari"}), [{"x":390,"y":290,"w":320,"h":180,"app":"Safari"}], "agent moves the cursor"),
    (0.10, None, [{"x":600,"y":420,"w":190,"h":64,"app":"Safari"}], "button hover highlight"),
    (0.50, Action("click", 0.50, {"bbox": BUTTON, "window": {"x":0,"y":0,"w":W,"h":H}, "app":"Safari"}), [dict(BUTTON,app="Safari")], "agent clicks Run"),
    (0.62, None, [dict(BUTTON,app="Safari"), {"x":0,"y":0,"w":W,"h":40,"app":"Safari"}], "button depresses, toolbar spinner"),
    (1.30, None, [dict(VIEWPORT,app="Safari")], "page repaints after the click"),
    (2.40, None, [dict(BANNER)], "*** Slack message arrives ***"),
    (3.00, Action("scroll", 3.00, {"viewport": VIEWPORT, "app":"Safari"}), [dict(VIEWPORT,app="Safari")], "agent scrolls"),
    (3.20, None, [dict(VIEWPORT,app="Safari")], "scroll momentum"),
    (3.90, Action("type", 3.90, {"caret": CARET, "field": {"x":280,"y":690,"w":700,"h":40}, "app":"Safari"}), [{"x":292,"y":694,"w":180,"h":32,"app":"Safari"}], "agent types a query"),
    (4.05, None, [{"x":292,"y":694,"w":240,"h":32,"app":"Safari"}], "more typing"),
    (5.60, None, [dict(FAILPANE)], "*** tests fail on their own ***"),
    (6.40, Action("click", 6.40, {"bbox": {"x":100,"y":120,"w":90,"h":30}, "window":{"x":0,"y":0,"w":W,"h":H}, "app":"Safari"}), [{"x":100,"y":120,"w":90,"h":30,"app":"Safari"}], "agent clicks a tab"),
    (6.70, None, [dict(BANNER)], "*** popup during the click's wide window ***"),
]

def main():
    print()
    print(f"  {'t':>6}  {'what happened':<44} {'obs':>4} {'self':>5} {'cons':>5} {'world':>6}  verdict")
    print("  " + "-" * 100)
    woke = 0
    for t, action, dirty, label in TRACE:
        if action is not None:
            bus.register(action)
        res = det.process(Observation(t=t, dirty=dirty, frame_id=int(t * 100)))
        obs, s_, c_, w_ = det.classify(Observation(t=t, dirty=dirty))
        if res is None or res.attribution.value == "self":
            verdict = "quiet"
        elif res.surface:
            woke += 1
            verdict = f"WAKE  <- {len(res.rects)} region(s)"
        elif res.attribution.value == "world":
            verdict = "world, but inside refractory"
        else:
            verdict = "consequence of my action"
        star = "*" if label.startswith("***") else " "
        print(f" {star}{t:>6.2f}  {label:<44} {int(obs.sum()):>4} {int(s_.sum()):>5} "
              f"{int(c_.sum()):>5} {int(w_.sum()):>6}  {verdict}")
    print("  " + "-" * 100)
    print(f"  {len(TRACE)} frames -> {woke} wake-ups")
    print()
    print("  Rows marked * are the three things the world did on its own.")
    print("  A correct run wakes on exactly those three and nothing else.")
    print()

if __name__ == "__main__":
    main()
