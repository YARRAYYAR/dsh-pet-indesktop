"""Short widget feedback that respects native motion preferences.

Each widget owns its transitions. No timer runs when feedback is at rest;
native preferences are queried on interaction rather than polled globally.
"""
from __future__ import annotations

import ctypes as c
import logging
import sys

from PySide6.QtCore import QEasingCurve, QVariantAnimation
from PySide6.QtWidgets import QApplication, QStyle

_log = logging.getLogger('dsh-pet-standalone')
_query_failed = False


def reduced_motion_requested() -> bool:
    global _query_failed
    try:
        if sys.platform == 'darwin':
            objc = c.CDLL('/usr/lib/libobjc.A.dylib')
            objc.objc_getClass.argtypes = [c.c_char_p]
            objc.objc_getClass.restype = c.c_void_p
            objc.sel_registerName.argtypes = [c.c_char_p]
            objc.sel_registerName.restype = c.c_void_p
            address = c.cast(objc.objc_msgSend, c.c_void_p).value
            pointer = c.CFUNCTYPE(c.c_void_p, c.c_void_p, c.c_void_p)(address)
            boolean = c.CFUNCTYPE(c.c_bool, c.c_void_p, c.c_void_p)(address)
            responds = c.CFUNCTYPE(c.c_bool, c.c_void_p, c.c_void_p, c.c_void_p)(address)
            workspace_class = objc.objc_getClass(b'NSWorkspace')
            if not workspace_class:
                return False
            workspace = pointer(workspace_class, objc.sel_registerName(b'sharedWorkspace'))
            selector = objc.sel_registerName(b'accessibilityDisplayShouldReduceMotion')
            if workspace and responds(workspace, objc.sel_registerName(b'respondsToSelector:'), selector):
                return bool(boolean(workspace, selector))
            return False
        if sys.platform == 'win32':
            # SystemParametersInfo writes a Win32 BOOL, which is four bytes.
            enabled = c.c_int(1)
            if not c.windll.user32.SystemParametersInfoW(0x1042, 0, c.byref(enabled), 0):
                raise OSError('SPI_GETCLIENTAREAANIMATION failed')
            return not enabled.value
        app = QApplication.instance()
        return bool(app is not None and not app.style().styleHint(QStyle.StyleHint.SH_Widget_Animate))
    except (OSError, AttributeError, TypeError, ValueError):
        if not _query_failed:
            _log.exception('无法读取系统动态效果偏好，使用简短交互反馈')
            _query_failed = True
        return False


class StateTransition(QVariantAnimation):
    """Continue interrupted feedback from the currently rendered value."""
    def __init__(self, widget, duration, changed, initial=0.0):
        super().__init__(widget)
        self._widget = widget
        self._changed = changed
        self._value = float(initial)
        self._target = float(initial)
        self.setDuration(duration)
        self.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.valueChanged.connect(self._advance)

    def _advance(self, value):
        self._value = float(value)
        self._changed(self._value)

    def move_to(self, value):
        self.stop()
        self._target = float(value)
        if not self._widget.isVisible() or reduced_motion_requested():
            self.snap()
            return
        if self._value == self._target:
            return
        self.setStartValue(self._value)
        self.setEndValue(self._target)
        self.start()

    def snap(self, value=None):
        self.stop()
        if value is not None:
            self._target = float(value)
        self._advance(self._target)


class RectTransition(QVariantAnimation):
    """Finite rectangle motion, retargeted from the current painted position."""
    def __init__(self, widget, duration, changed):
        from PySide6.QtCore import QRectF
        super().__init__(widget)
        self._widget = widget
        self._changed = changed
        self._value = QRectF()
        self._target = QRectF()
        self.setDuration(duration)
        self.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.valueChanged.connect(self._advance)

    def _advance(self, value):
        self._value = value
        self._changed(value)

    def move_to(self, value):
        self.stop()
        self._target = value
        if not self._widget.isVisible() or reduced_motion_requested():
            self.snap()
            return
        if self._value == self._target:
            return
        self.setStartValue(self._value)
        self.setEndValue(self._target)
        self.start()

    def snap(self, value=None):
        self.stop()
        if value is not None:
            self._target = value
        self._advance(self._target)
