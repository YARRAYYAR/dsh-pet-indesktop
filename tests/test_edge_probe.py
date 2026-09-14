# -*- coding: utf-8 -*-
"""边缘探头的无窗口几何回归测试。"""

from PySide6.QtCore import QRect

from pet.edge_probe import probe_window_x
from pet.window_effects import rotated_region_bounds


def test_probe_window_x_keeps_requested_exposure_at_left_edge():
    available = QRect(0, 0, 1200, 800)
    visible = QRect(50, 40, 400, 300)
    x = probe_window_x('left', 0.55, visible, available)
    assert x + visible.left() == -180


def test_rotated_bounds_expand_for_probe_pose():
    bounds = rotated_region_bounds(
        QRect(100, 20, 300, 220), QRect(0, 0, 500, 400), 45
    )
    assert bounds.width() > 300
    assert bounds.height() > 220
