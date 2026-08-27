"""The properties that must hold or the idea does not work."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudeyes.grid import Grid, Rect
from claudeyes.actionbus import ActionBus, Action
from claudeyes.residual import Detector, Observation, Attribution

W, H = 1512, 982


def rig():
    g = Grid(W, H)
    b = ActionBus(g)
    return g, b, Detector(g, b)


class TestGrid(unittest.TestCase):
    def test_rect_roundtrip_covers_original(self):
        g = Grid(W, H)
        r = Rect(100, 100, 200, 50)
        out = g.cells_to_rects(g.rasterize([r]))
        self.assertEqual(len(out), 1)
        o = out[0]
        self.assertLessEqual(o.x, r.x)
        self.assertLessEqual(o.y, r.y)
        self.assertGreaterEqual(o.x + o.w, r.x + r.w)
        self.assertGreaterEqual(o.y + o.h, r.y + r.h)

    def test_out_of_bounds_is_clamped_not_crashed(self):
        g = Grid(W, H)
        m = g.rasterize([Rect(-500, -500, 100, 100), Rect(W + 10, H + 10, 50, 50)])
        self.assertEqual(float(m.sum()), 0.0)


class TestDecay(unittest.TestCase):
    def test_confidence_decays_to_zero(self):
        _, b, _ = rig()
        b.register(Action("click", 0.0, {"bbox": {"x": 10, "y": 10, "w": 40, "h": 40}}))
        confs = [b.predicted_mask(t).max() for t in (0.0, 0.3, 1.0, 5.0)]
        self.assertAlmostEqual(confs[0], 1.0, places=3)
        self.assertEqual(confs[-1], 0.0)
        self.assertTrue(all(a >= b_ for a, b_ in zip(confs, confs[1:])), confs)

    def test_stale_action_explains_nothing(self):
        _, b, d = rig()
        b.register(Action("click", 0.0, {"bbox": {"x": 600, "y": 400, "w": 100, "h": 40}}))
        res = d.process(Observation(t=30.0, dirty=[{"x": 600, "y": 400, "w": 100, "h": 40}]))
        self.assertTrue(res.surface)
        self.assertIs(res.attribution, Attribution.WORLD)


class TestAttribution(unittest.TestCase):
    def test_motor_echo_is_silent(self):
        _, b, d = rig()
        for kind, params, dirty in [
            ("mouse_move", {"x0": 100, "y0": 100, "x1": 300, "y1": 200},
             {"x": 110, "y": 110, "w": 180, "h": 80}),
            ("scroll", {"viewport": {"x": 0, "y": 0, "w": W, "h": H}},
             {"x": 0, "y": 0, "w": W, "h": H}),
            ("type", {"caret": {"x": 300, "y": 700, "w": 3, "h": 20}},
             {"x": 305, "y": 700, "w": 120, "h": 20}),
        ]:
            with self.subTest(kind=kind):
                b.register(Action(kind, 100.0, params))
                r = d.process(Observation(t=100.02, dirty=[dirty]))
                self.assertFalse(r.surface, f"{kind} woke it up: {r}")
                self.assertIs(r.attribution, Attribution.SELF)

    def test_unprovoked_change_wakes(self):
        _, _, d = rig()
        res = d.process(Observation(t=5.0, dirty=[{"x": 1100, "y": 40, "w": 360, "h": 90}]))
        self.assertTrue(res.surface)
        self.assertIs(res.attribution, Attribution.WORLD)

    def test_foreign_app_beats_geometry(self):
        """A click cannot license change in an app it never touched, even if
        the change lands right next to the click."""
        _, b, d = rig()
        b.register(Action("click", 0.0, {"bbox": {"x": 600, "y": 400, "w": 100, "h": 40},
                                         "window": {"x": 0, "y": 0, "w": W, "h": H},
                                         "app": "Safari"}))
        near_same = d.process(Observation(t=0.3, dirty=[
            {"x": 640, "y": 460, "w": 200, "h": 80, "app": "Safari"}]))
        near_other = d.process(Observation(t=0.3, dirty=[
            {"x": 640, "y": 460, "w": 200, "h": 80, "app": "Notification Center"}]))
        self.assertIsNot(near_same.attribution, Attribution.WORLD)
        self.assertIs(near_other.attribution, Attribution.WORLD)

    def test_wide_uncertainty_is_not_a_blind_spot(self):
        """The failure mode this must not have: a keyboard shortcut licenses
        the whole screen, and an injected dialog rides in behind it."""
        _, b, d = rig()
        b.register(Action("key", 0.0, {"combo": "cmd+tab", "app": "Finder"}))
        res = d.process(Observation(t=0.1, dirty=[
            {"x": 500, "y": 400, "w": 400, "h": 200, "app": "Evil Updater"}]))
        self.assertTrue(res.surface)
        self.assertIs(res.attribution, Attribution.WORLD)


class TestStickyCursor(unittest.TestCase):
    """Regression: hover was modelled as a decaying event, so an agent that
    paused over a button woke itself up ~450ms later. A resting cursor is
    state, not an event, and only the next mouse_move retires it."""

    def test_hover_stays_suppressed_long_after_the_move(self):
        _, b, d = rig()
        b.register(Action("mouse_move", 0.0, {"x0": 400, "y0": 300, "x1": 690, "y1": 450}))
        highlight = [{"x": 660, "y": 420, "w": 80, "h": 50}]
        for t in (0.05, 0.5, 2.0, 30.0):
            with self.subTest(t=t):
                self.assertFalse(d.process(Observation(t=t, dirty=highlight)).surface)

    def test_moving_away_retires_the_old_resting_place(self):
        _, b, d = rig()
        b.register(Action("mouse_move", 0.0, {"x0": 400, "y0": 300, "x1": 690, "y1": 450}))
        b.register(Action("mouse_move", 1.0, {"x0": 690, "y0": 450, "x1": 200, "y1": 800}))
        # something repaints where the cursor used to be: nothing explains it now
        res = d.process(Observation(t=1.5, dirty=[{"x": 660, "y": 420, "w": 120, "h": 60}]))
        self.assertIs(res.attribution, Attribution.WORLD)


class TestGate(unittest.TestCase):
    def test_refractory_suppresses_a_burst(self):
        _, _, d = rig()
        banner = [{"x": 1100, "y": 40, "w": 360, "h": 90}]
        first = d.process(Observation(t=0.0, dirty=banner))
        second = d.process(Observation(t=0.05, dirty=banner))
        third = d.process(Observation(t=1.0, dirty=banner))
        self.assertTrue(first.surface)
        self.assertFalse(second.surface, "refractory period did not hold")
        self.assertTrue(third.surface)

    def test_specks_are_ignored(self):
        _, _, d = rig()
        r = d.process(Observation(t=0.0, dirty=[{"x": 5, "y": 5, "w": 3, "h": 3}]))
        self.assertFalse(r.surface)


if __name__ == "__main__":
    unittest.main(verbosity=2)
