"""The hold / double-tap gesture, driven by hand.

Time is an argument and the delay goes through a fake scheduler, so these run
instantly and deterministically — no sleeping, no keyboard.
"""

import pytest

from s2f.gesture import GestureRecogniser


class FakeScheduler:
    """Collects the pending callback so a test can fire or cancel it at will."""

    def __init__(self):
        self.pending = None
        self.cancelled = 0

    def __call__(self, delay_s, fn):
        self.pending = fn

        def _cancel():
            self.pending = None
            self.cancelled += 1

        return _cancel

    def fire(self):
        assert self.pending is not None, "nothing was scheduled"
        fn, self.pending = self.pending, None
        fn()


@pytest.fixture
def gesture():
    events, scheduler = [], FakeScheduler()
    rec = GestureRecogniser(
        on_start=lambda: events.append("start"),
        on_stop=lambda: events.append("stop"),
        hold_ms=250, double_ms=350, scheduler=scheduler,
    )
    return rec, events, scheduler


class TestHoldToTalk:
    def test_recording_starts_on_the_press_not_the_release(self, gesture):
        """Waiting to know the gesture would clip the first word."""
        rec, events, _ = gesture
        rec.press(0.0)
        assert events == ["start"]

    def test_a_long_press_transcribes_on_release(self, gesture):
        rec, events, _ = gesture
        rec.press(0.0)
        rec.release(2.0)
        assert events == ["start", "stop"]
        assert not rec.is_recording

    def test_auto_repeat_while_held_is_ignored(self, gesture):
        rec, events, _ = gesture
        rec.press(0.0)
        for t in (0.1, 0.2, 0.3):
            rec.press(t)
        rec.release(1.0)
        assert events == ["start", "stop"]


class TestDoubleTap:
    def test_two_quick_taps_keep_recording(self, gesture):
        rec, events, sched = gesture
        rec.press(0.0)
        rec.release(0.10)          # too short to be a hold
        assert events == ["start"]  # still going: might be a double tap
        rec.press(0.20)             # second tap within the window
        assert events == ["start"]
        assert rec.is_recording
        assert sched.cancelled == 1

    def test_hands_free_stops_on_the_next_press(self, gesture):
        rec, events, _ = gesture
        rec.press(0.0)
        rec.release(0.10)
        rec.press(0.20)            # hands-free
        rec.release(0.25)          # releasing means nothing now
        assert events == ["start"]
        rec.press(9.0)             # the press that ends it
        assert events == ["start", "stop"]
        assert not rec.is_recording

    def test_a_lone_tap_is_a_short_dictation(self, gesture):
        rec, events, sched = gesture
        rec.press(0.0)
        rec.release(0.10)
        sched.fire()               # the second tap never came
        assert events == ["start", "stop"]
        assert not rec.is_recording

    def test_the_wait_is_only_armed_for_a_short_press(self, gesture):
        rec, _events, sched = gesture
        rec.press(0.0)
        rec.release(1.0)           # a hold, decided immediately
        assert sched.pending is None


class TestEdges:
    def test_a_release_without_a_press_does_nothing(self, gesture):
        rec, events, _ = gesture
        rec.release(1.0)
        assert events == []

    def test_the_boundary_counts_as_a_hold(self, gesture):
        rec, events, _ = gesture
        rec.press(0.0)
        rec.release(0.250)         # exactly hold_ms
        assert events == ["start", "stop"]

    def test_cancel_forgets_a_gesture_in_progress(self, gesture):
        rec, events, sched = gesture
        rec.press(0.0)
        rec.release(0.10)
        rec.cancel()
        assert sched.cancelled == 1
        sched.pending = None
        rec.press(5.0)             # starts cleanly, as if nothing had happened
        assert events == ["start", "start"]

    def test_a_stale_timer_cannot_stop_a_new_recording(self, gesture):
        """The tap's timer must not fire into a gesture that moved on."""
        rec, events, sched = gesture
        rec.press(0.0)
        rec.release(0.10)
        pending = sched.pending
        rec.press(0.20)            # becomes hands-free, cancelling the wait
        pending()                  # the old timer fires late anyway
        assert events == ["start"]
        assert rec.is_recording
