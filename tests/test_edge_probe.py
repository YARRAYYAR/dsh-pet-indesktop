# -*- coding: utf-8 -*-
"""边缘探头的无窗口几何回归测试。"""

from PySide6.QtCore import QRect

from pet.edge_probe import edge_side_at_rest, probe_window_x
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


def test_edge_side_at_rest_accepts_drag_release_target_on_both_sides():
    class Window:
        def character_local_region(self):
            return QRect(46, 325, 92, 129)

        def frameGeometry(self):
            return QRect(600, 300, 200, 500)

    available = QRect(0, 0, 2000, 1600)
    window = Window()
    assert edge_side_at_rest(window, available, window_x=-46) == 'left'
    assert edge_side_at_rest(window, available, window_x=2000 - 92 - 46) == 'right'
    assert edge_side_at_rest(window, available, window_x=600) is None
