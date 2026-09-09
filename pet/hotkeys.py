# -*- coding: utf-8 -*-
"""macOS Carbon 全局快捷键的最小封装。

不依赖 PyObjC：Qt 的 Cocoa 事件循环可以同时接收 Carbon hot key 事件。
其他平台安全降级为 disabled，状态栏菜单仍然可用。
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import sys
from dataclasses import dataclass

from PySide6.QtCore import QTimer


class _EventHotKeyID(ctypes.Structure):
    _fields_ = [
        ('signature', ctypes.c_uint32),
        ('id', ctypes.c_uint32),
    ]


@dataclass(frozen=True)
class HotkeySpec:
    name: str
    key_code: int
    action: str


class GlobalHotkeys:
    """注册一组低冲突的 Control+Option+Command 全局快捷键。"""

    MOD_COMMAND = 1 << 8
    MOD_SHIFT = 1 << 9
    MOD_OPTION = 1 << 11
    MOD_CONTROL = 1 << 12
    EVENT_CLASS_KEYBOARD = 0x6B657962  # 'keyb'
    EVENT_HOT_KEY_PRESSED = 5
    PARAM_DIRECT_OBJECT = 0x2D2D2D2D  # '----'
    TYPE_EVENT_HOT_KEY_ID = 0x686B6964  # 'hkid'

    # Carbon virtual key codes: H=4, P=35, R=15, M=46, D=2.
    DEFAULTS = (
        HotkeySpec('显示 / 隐藏', 4, 'toggle_visible'),
        HotkeySpec('暂停 / 继续', 35, 'toggle_pause'),
        HotkeySpec('随机动作', 15, 'random_action'),
        HotkeySpec('鼠标穿透', 46, 'toggle_mouse_through'),
        HotkeySpec('尖叫鸭', 2, 'duck_sound'),
    )

    def __init__(self, callback) -> None:
        self.callback = callback
        self.enabled = False
        self.error: str | None = None
        self._carbon = None
        self._handler = None
        self._hotkeys: list[ctypes.c_void_p] = []
        self._callback_ref = None

    def start(self) -> bool:
        if sys.platform != 'darwin':
            self.error = '仅 macOS 支持全局快捷键'
            return False
        if self.enabled:
            return True
        try:
            path = ctypes.util.find_library('Carbon') or (
                '/System/Library/Frameworks/Carbon.framework/Carbon'
            )
            self._carbon = ctypes.cdll.LoadLibrary(path)
            carbon = self._carbon
            carbon.GetApplicationEventTarget.restype = ctypes.c_void_p
            carbon.InstallEventHandler.argtypes = [
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_uint32,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_void_p),
            ]
            carbon.InstallEventHandler.restype = ctypes.c_int32
            carbon.RegisterEventHotKey.argtypes = [
                ctypes.c_uint32,
                ctypes.c_uint32,
                _EventHotKeyID,
                ctypes.c_void_p,
                ctypes.c_uint32,
                ctypes.POINTER(ctypes.c_void_p),
            ]
            carbon.RegisterEventHotKey.restype = ctypes.c_int32
            carbon.GetEventParameter.argtypes = [
                ctypes.c_void_p,
                ctypes.c_uint32,
                ctypes.c_uint32,
                ctypes.POINTER(ctypes.c_void_p),
                ctypes.c_uint32,
                ctypes.POINTER(ctypes.c_uint32),
                ctypes.c_void_p,
            ]
            carbon.GetEventParameter.restype = ctypes.c_int32

            event_target = carbon.GetApplicationEventTarget()
            event_spec = (ctypes.c_uint32 * 2)(
                self.EVENT_CLASS_KEYBOARD,
                self.EVENT_HOT_KEY_PRESSED,
            )
            handler_ref = ctypes.c_void_p()

            @ctypes.CFUNCTYPE(
                ctypes.c_int32,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_void_p,
            )
            def handler(_next_handler, event, _user_data):
                hotkey_id = (ctypes.c_uint32 * 2)()
                actual_size = ctypes.c_uint32()
                status = carbon.GetEventParameter(
                    event,
                    self.PARAM_DIRECT_OBJECT,
                    self.TYPE_EVENT_HOT_KEY_ID,
                    None,
                    ctypes.sizeof(hotkey_id),
                    ctypes.byref(actual_size),
                    ctypes.byref(hotkey_id),
                )
                if status == 0:
                    self._dispatch(int(hotkey_id[1]))
                return 0

            self._callback_ref = handler
            status = carbon.InstallEventHandler(
                event_target,
                ctypes.cast(handler, ctypes.c_void_p),
                1,
                ctypes.byref(event_spec),
                None,
                ctypes.byref(handler_ref),
            )
            if status != 0:
                raise OSError(f'InstallEventHandler status={status}')
            self._handler = handler_ref

            for index, spec in enumerate(self.DEFAULTS):
                hotkey_id = _EventHotKeyID(0x44534850, index + 1)
                ref = ctypes.c_void_p()
                status = carbon.RegisterEventHotKey(
                    spec.key_code,
                    self.MOD_COMMAND | self.MOD_OPTION | self.MOD_CONTROL,
                    hotkey_id,
                    event_target,
                    0,
                    ctypes.byref(ref),
                )
                if status != 0:
                    raise OSError(
                        f'RegisterEventHotKey {spec.name} status={status}'
                    )
                self._hotkeys.append(ref)
            self.enabled = True
            logging.info('全局快捷键已启用: Control+Option+Command')
            return True
        except (OSError, AttributeError, ctypes.ArgumentError) as exc:
            self.error = str(exc)
            logging.warning('全局快捷键不可用: %s', exc)
            self.stop()
            return False

    def stop(self) -> None:
        carbon = self._carbon
        if carbon is not None:
            unregister = getattr(carbon, 'UnregisterEventHotKey', None)
            if unregister is not None:
                unregister.argtypes = [ctypes.c_void_p]
                unregister.restype = ctypes.c_int32
                for ref in self._hotkeys:
                    unregister(ref)
            remove = getattr(carbon, 'RemoveEventHandler', None)
            if remove is not None and self._handler is not None:
                remove.argtypes = [ctypes.c_void_p]
                remove.restype = ctypes.c_int32
                remove(self._handler)
        self._hotkeys.clear()
        self._handler = None
        self._callback_ref = None
        self.enabled = False

    def _dispatch(self, index: int) -> None:
        if 1 <= index <= len(self.DEFAULTS):
            try:
                action = self.DEFAULTS[index - 1].action
                QTimer.singleShot(0, lambda: self.callback(action))
            except Exception:
                logging.exception('全局快捷键动作失败: %s', index)
