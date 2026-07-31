"""Where the status pill ends up. Pure geometry: no Tk, so it runs anywhere."""

import pytest

from stt.config import OVERLAY_POSITIONS
from stt.ui.overlay import _MARGIN, _place

# A 1920x1080 screen with a 40 px taskbar along the bottom.
AREA = (0, 0, 1920, 1040)
W, H = 200, 40


class TestPlace:
    @pytest.mark.parametrize("position", OVERLAY_POSITIONS)
    def test_every_configurable_position_stays_inside_the_work_area(self, position):
        x, y = _place(position, W, H, AREA)
        left, top, right, bottom = AREA
        assert left <= x and x + W <= right
        assert top <= y and y + H <= bottom

    @pytest.mark.parametrize("position", ["bottom-center", "top-center"])
    def test_centred_positions_leave_equal_margins(self, position):
        x, _ = _place(position, W, H, AREA)
        assert x == (1920 - W) // 2
        assert x - AREA[0] == AREA[2] - (x + W)

    def test_a_centred_pill_keeps_its_middle_as_it_grows(self):
        narrow = _place("bottom-center", 100, H, AREA)[0] + 100 / 2
        wide = _place("bottom-center", 300, H, AREA)[0] + 300 / 2
        assert narrow == wide

    def test_corners_keep_their_margin_from_the_edges(self):
        assert _place("bottom-right", W, H, AREA) == (1920 - W - _MARGIN, 1040 - H - _MARGIN)
        assert _place("top-left", W, H, AREA) == (_MARGIN, _MARGIN)

    def test_the_work_area_offset_is_respected(self):
        """A taskbar on the left shifts the origin: the centre moves with it."""
        area = (80, 0, 1920, 1080)
        assert _place("bottom-center", W, H, area)[0] == 80 + (1840 - W) // 2
        assert _place("bottom-left", W, H, area)[0] == 80 + _MARGIN
