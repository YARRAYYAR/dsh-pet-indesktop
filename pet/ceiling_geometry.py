"""Physical Mac notch from AppKit, cached per display geometry (logical pixels)."""
from functools import lru_cache
import logging
import platform
import sys

from PySide6.QtCore import QRect
from PySide6.QtGui import QGuiApplication


def screen_notch_rect(screen):
    if sys.platform != 'darwin' or platform.machine() != 'arm64' or QGuiApplication.platformName() != 'cocoa':
        return None
    geometry = screen.geometry()
    result = _mac_notch(tuple(geometry.getRect()), screen.devicePixelRatio())
    return QRect(*result) if result else None


@lru_cache(maxsize=8)
def _mac_notch(geometry, dpr):
    # AppKit and Qt use logical pixels; dpr only invalidates cache on scaling.
    del dpr
    import ctypes as c

    class Rect(c.Structure):
        _fields_ = [(name, c.c_double) for name in ('x', 'y', 'w', 'h')]

    class Insets(c.Structure):
        _fields_ = [(name, c.c_double) for name in ('top', 'left', 'bottom', 'right')]

    try:
        objc = c.CDLL('/usr/lib/libobjc.A.dylib')
        objc.objc_getClass.argtypes = [c.c_char_p]
        objc.objc_getClass.restype = c.c_void_p
        objc.sel_registerName.argtypes = [c.c_char_p]
        objc.sel_registerName.restype = c.c_void_p
        address = c.cast(objc.objc_msgSend, c.c_void_p).value
        # Typed function wrappers avoid mutating shared objc_msgSend signatures.
        pointer = c.CFUNCTYPE(c.c_void_p, c.c_void_p, c.c_void_p)(address)
        integer = c.CFUNCTYPE(c.c_ulong, c.c_void_p, c.c_void_p)(address)
        item = c.CFUNCTYPE(c.c_void_p, c.c_void_p, c.c_void_p, c.c_ulong)(address)
        rect = c.CFUNCTYPE(Rect, c.c_void_p, c.c_void_p)(address)
        insets = c.CFUNCTYPE(Insets, c.c_void_p, c.c_void_p)(address)
        responds = c.CFUNCTYPE(c.c_bool, c.c_void_p, c.c_void_p, c.c_void_p)(address)
        sel = objc.sel_registerName
        screens = pointer(objc.objc_getClass(b'NSScreen'), sel(b'screens'))
        if not screens or integer(screens, sel(b'count')) == 0:
            return None
        primary = rect(item(screens, sel(b'objectAtIndex:'), 0), sel(b'frame'))
        primary_top = primary.y + primary.h
        for index in range(integer(screens, sel(b'count'))):
            screen = item(screens, sel(b'objectAtIndex:'), index)
            frame = rect(screen, sel(b'frame'))
            # AppKit's y points up; Qt's y points down from primary screen top.
            qt_frame = (round(frame.x - primary.x), round(primary_top - frame.y - frame.h), round(frame.w), round(frame.h))
            if qt_frame != geometry or not responds(screen, sel(b'respondsToSelector:'), sel(b'safeAreaInsets')):
                continue
            safe = insets(screen, sel(b'safeAreaInsets'))
            if safe.top <= 0:
                return None
            left = rect(screen, sel(b'auxiliaryTopLeftArea'))
            right = rect(screen, sel(b'auxiliaryTopRightArea'))
            if left.w <= 0 or right.w <= 0:
                return None
            x = round(left.x + left.w - primary.x)
            width = round(right.x - primary.x) - x
            return (x, geometry[1], width, round(safe.top)) if width > 0 else None
    except (OSError, AttributeError, TypeError, ValueError):
        logging.getLogger('dsh-pet-standalone').exception('读取屏幕刘海失败，使用普通顶部吸附')
    return None
