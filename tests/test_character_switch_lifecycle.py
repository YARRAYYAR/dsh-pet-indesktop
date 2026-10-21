"""Real Qt replacement lifecycle; inject construction failures at public seams.

Media comes from the unchanged built-in clip. Failure injection is needed because
reliably provoking a constructor/tray failure on a desktop would be unsafe.
"""
import json
from pathlib import Path
from threading import Thread
from unittest.mock import Mock

import pytest
import shiboken6
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from pet import catalog
import pet.app as app_module
from pet.app import AppShell
from pet.config import Config
from pet.library import MovieLibrary


@pytest.fixture
def residency(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    source = Path(__file__).resolve().parents[1] / 'assets/characters/shenshen/videos/idle/待机呼吸休闲.webm'
    if not source.is_file():
        pytest.skip('built-in media unavailable')
    root = tmp_path / 'characters'
    for name in ('fixture-a', 'fixture-b'):
        videos = root / name / 'videos'
        (videos / 'idle').mkdir(parents=True)
        (videos / 'idle' / source.name).symlink_to(source)
        (videos / 'manifest.json').write_text(json.dumps({'name': name}))
    monkeypatch.setattr(catalog, 'external_character_dirs', lambda: [root])
    cfg = Config(tmp_path / 'config')
    cfg.data.update({'character': 'fixture-a', 'no_move': True,
                     'media_prewarm': 'minimal', 'click_sound_enabled': False,
                     'collision_sound_enabled': False, 'self_talk_enabled': False,
                     'top_flip_enabled': False, 'harness_autostart': False,
                     'experimental_single_process_spawn': True})
    cfg.save()
    shell = AppShell(app, cfg, enable_chat=False)
    shell.instance._build_window('fixture-a')
    libraries = [shell.win.lib]
    original = shell.instance._create_library

    def create(character):
        lib = original(character)
        libraries.append(lib)
        return lib

    monkeypatch.setattr(shell.instance, '_create_library', create)
    yield app, shell, libraries
    for widget in list(app.topLevelWidgets()):
        if hasattr(widget, 'lib'):
            widget.close()
    for lib in libraries:
        lib.shutdown()
    if shell.tray is not None:
        shell.tray.hide()
    shell.instance.collision_ipc.stop()
    if shell._shared is not None:
        shell._shared.stop_all()
    if shell._decode_hub is not None:
        shell._decode_hub.shutdown()


def _turn():
    loop = QEventLoop()
    QTimer.singleShot(0, loop.quit)
    loop.exec()


def test_repeated_character_switch_releases_old_window(residency):
    _, shell, _ = residency
    for character in ('fixture-b', 'fixture-a', 'fixture-b'):
        old = shell.win
        old_lib = old.lib
        shell.instance.switch_character(character)
        assert shell.win is not old
        assert old_lib._shutdown, 'replacement bypassed permanent library release'
        assert old._closing
        assert old._speech_bubble is None
        assert not any(timer.isActive() for timer in old.findChildren(QTimer))
        _turn()


def test_release_is_idempotent_and_does_not_stop_shared_services(residency, monkeypatch):
    _, shell, _ = residency
    win = shell.win
    shared_agent = win.agent_link_manager
    shared_watcher = win.proactive_watcher
    agent_shutdown, watcher_pause = Mock(), Mock()
    monkeypatch.setattr(shared_agent, 'shutdown', agent_shutdown)
    monkeypatch.setattr(shared_watcher, 'pause', watcher_pause)
    shutdown = Mock(wraps=win.lib.shutdown)
    monkeypatch.setattr(win.lib, 'shutdown', shutdown)
    win.release_resources()
    win.release_resources()
    win.close()
    assert shutdown.call_count == 1
    assert not agent_shutdown.called
    assert not watcher_pause.called


@pytest.mark.parametrize('seam', ['constructor', 'wiring', 'tray', 'library'])
def test_failed_replacement_keeps_old_window_and_config(residency, monkeypatch, seam):
    _, shell, libraries = residency
    old, old_session, old_tray = shell.win, shell.instance.collision_ipc, shell.tray
    candidate_windows = []

    def fail(*args, **kwargs):
        raise RuntimeError('injected candidate failure')

    if seam == 'constructor':
        monkeypatch.setattr(app_module, 'PetWindow', fail)
    elif seam == 'wiring':
        def fail_wiring(win):
            candidate_windows.append(win)
            fail()
        monkeypatch.setattr(shell.instance, '_wire_window', fail_wiring)
    elif seam == 'tray':
        def fail_tray(win):
            candidate_windows.append(win)
            fail()
        monkeypatch.setattr(shell, '_build_tray', fail_tray)
    else:
        monkeypatch.setattr(shell.instance, '_create_library', fail)
    monkeypatch.setattr(app_module, '_show_startup_error', Mock())
    shell.instance.switch_character('fixture-b')
    assert shell.win is old
    assert old.isVisible() and not old._closing
    assert not old.lib._shutdown
    assert shell.config.get('character') == 'fixture-a'
    assert json.loads(shell.config.path.read_text())['character'] == 'fixture-a'
    assert shell.instance.collision_ipc is old_session
    assert shell.tray is old_tray
    assert all(lib._shutdown for lib in libraries[1:])
    assert all(win._closing and win._speech_bubble is None for win in candidate_windows)
    _turn()


def test_window_owned_services_are_stopped(residency):
    _, shell, _ = residency
    # An isolated window gets its own lazy services, unlike shell-injected ones.
    from pet.window import PetWindow
    lib = MovieLibrary(character_id='fixture-b', prewarm_policy='minimal')
    win = PetWindow(lib, shell.config)
    agent = win._ensure_agent_link_manager()
    watcher = win._ensure_proactive_watcher()
    agent.shutdown = Mock(wraps=agent.shutdown)
    watcher.pause = Mock(wraps=watcher.pause)
    try:
        win.release_resources()
        assert agent.shutdown.call_count == 1
        assert watcher.pause.call_count == 1
    finally:
        win.close()
        lib.shutdown()


def test_application_exit_permanently_releases_window(residency):
    _, shell, _ = residency
    win = shell.win
    shell._on_about_to_quit()
    assert win.lib._shutdown, 'application exit only paused the library'
    assert win._speech_bubble is None
    assert win._resources_released


@pytest.mark.parametrize('seam', ['_switch', '_read_self_talk_texts'])
def test_mid_constructor_failure_releases_real_candidate_widgets(residency, monkeypatch, seam):
    """仅注入构造后半段异常，不损坏共享 HQ 索引或耗尽系统资源。

    QWidget、独立气泡及定时器均由真实构造创建，并保留候选引用，避免 GC
    偶然收尾掩盖缺口。失败必须保留旧窗，同时停掉已创建的候选资源。
    """
    _, shell, libraries = residency
    old, old_session, old_tray = shell.win, shell.instance.collision_ipc, shell.tray
    candidates = []
    original = getattr(app_module.PetWindow, seam)

    def fail_after_widget_construction(win, name, *args, **kwargs):
        if win.lib.character_id == 'fixture-b':
            bubble = win._speech_bubble
            win._animation_gap_timer.start(60_000)
            bubble.show()
            bubble._hide_timer.start(60_000)
            timers = [*win.findChildren(QTimer), *bubble.findChildren(QTimer)]
            candidates.append((win, bubble, timers))
            raise RuntimeError('injected failure after real Qt widget construction')
        return original(win, name, *args, **kwargs)

    monkeypatch.setattr(app_module.PetWindow, seam, fail_after_widget_construction)
    monkeypatch.setattr(app_module, '_show_startup_error', Mock())
    try:
        shell.instance.switch_character('fixture-b')
        assert len(candidates) == 1
        candidate, bubble, timers = candidates[0]
        assert shell.win is old
        assert old.isVisible() and not old._closing and not old.lib._shutdown
        assert shell.instance.collision_ipc is old_session
        assert shell.tray is old_tray
        assert shell.config.get('character') == 'fixture-a'
        assert json.loads(shell.config.path.read_text())['character'] == 'fixture-a'
        assert all(lib._shutdown for lib in libraries[1:])
        assert candidate._closing
        assert candidate._speech_bubble is None
        assert not shiboken6.isValid(bubble) or not bubble.isVisible()
        assert all(not shiboken6.isValid(timer) or not timer.isActive() for timer in timers)
    finally:
        # 红灯也收口保留的候选，不能把有意制造的泄漏带到下一项验证。
        for candidate, _bubble, _timers in candidates:
            if shiboken6.isValid(candidate):
                for timer in candidate.findChildren(QTimer):
                    timer.stop()
                if _bubble is not None and shiboken6.isValid(_bubble):
                    _bubble.close()
                    _bubble.deleteLater()
                # A deliberately partial object cannot use hide/close overrides.
                from PySide6.QtWidgets import QWidget
                QWidget.hide(candidate)
                candidate.deleteLater()


def test_queued_look_result_after_release_does_not_write_new_character_session(residency):
    """真实线程排队识屏完成信号，使用临时 SessionStore 检查角色切换后的落盘。"""
    from pet.chat.session_store import SessionStore

    _, shell, _ = residency
    old = shell.win
    store = SessionStore(shell.config.dir, shell.config.instance_id)
    new_session = store.create('fixture-b', 'fixture-provider', '')
    assert store.save(new_session)
    assert store.flush(timeout=2.0)
    shell.enable_chat = True
    old.on_look_synced = shell.instance.sync_look_to_chat
    old._look_busy = True
    try:
        worker = Thread(
            target=old.look_done.emit,
            args=('retired character reply', '[look] retired character', False),
        )
        worker.start()
        worker.join(timeout=2.0)
        assert not worker.is_alive()
        assert old._look_busy, '完成信号必须尚在 GUI 队列，不能在 worker 中直接应用'

        old.release_resources()
        old.hide(notify=False)
        shell.config.set('character', 'fixture-b')
        shell.config.save()
        _turn()

        assert store.flush(timeout=2.0)
        persisted = store.load(new_session.session_id, 'fixture-b')
        assert persisted is not None
        assert persisted.messages == [], '旧窗排队的识屏结果不得写入新角色会话'
    finally:
        shell.enable_chat = False
