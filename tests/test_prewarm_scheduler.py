"""MovieLibrary scheduling through a real Qt event loop, without decoder I/O.

The clip boundary records decoder requests. OS thread exhaustion is unsafe to
provoke in a desktop flow, so start failures are injected before implementation:
the claim must roll back, be logged, and permit the next request to succeed.
"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

import pet.library as library_mod
import pet.prewarm_scheduler as scheduler_mod
from pet import catalog


class RecordingClip:
    def __init__(self, path, parent=None):
        self.path = Path(path)
        self.created_on = threading.get_ident()
        self.meta_calls = 0
        self.frame_calls = 0

    def warm_meta(self):
        self.meta_calls += 1

    def warm_first_frame(self):
        self.frame_calls += 1

    def first_frame_ready(self):
        return self.frame_calls > 0


@pytest.fixture
def library(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(library_mod, "WebMClip", RecordingClip)
    videos = tmp_path / "videos"
    for folder, name in (("click", catalog.CLICKS[0]), ("random", "写代码")):
        target = videos / folder / f"{name}.webm"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"temporary decoder boundary")
    lib = library_mod.MovieLibrary(asset_dir=videos, prewarm_policy="full")
    yield lib
    lib.shutdown()
    app.processEvents()


def spin_until(predicate, *, timeout_ms=10000):
    """Pump Qt until an observed event, with a generous bounded deadline."""
    loop = QEventLoop()
    check = QTimer()
    check.setInterval(5)
    check.timeout.connect(lambda: loop.quit() if predicate() else None)
    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    check.start()
    deadline.start(timeout_ms)
    if not predicate():
        loop.exec()
    check.stop()
    deadline.stop()
    assert predicate(), "Qt flow did not reach the expected state"


def drain_window(milliseconds=150):
    # A bounded negative-observation window, not a sleep used to guess progress.
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def is_scheduler_thread(thread):
    # Instrument only the actual scheduler boundary. Qt may dispatch unrelated
    # application callbacks while these flows pump the shared event loop.
    target = getattr(thread, "_target", None)
    return getattr(target, "__module__", None) == scheduler_mod.__name__


def test_deferred_low_batch_has_no_gui_retry_timer(library):
    library.begin_interaction()
    library._warm_low_priority_background()
    assert "写代码" not in library._movies
    assert not any(timer.isActive() for timer in library.findChildren(QTimer)), (
        "interaction suspension must wait for a release signal, without GUI polling"
    )


def test_last_holder_release_from_worker_resumes_on_gui_thread(library):
    first = library.begin_interaction()
    last = library.begin_interaction()
    library._warm_low_priority_background()
    library.end_interaction(first)
    drain_window()
    assert "写代码" not in library._movies
    finished = threading.Event()

    def release():
        library.end_interaction(last)
        finished.set()

    worker = threading.Thread(target=release, daemon=True)
    worker.start()
    spin_until(lambda: finished.is_set() and library._low_first_frames_done)
    worker.join(timeout=5)
    assert library._movies["写代码"].created_on == threading.get_ident()


def test_predicted_burst_uses_one_waiting_thread(library, monkeypatch):
    token = library.begin_interaction()
    starts = []
    real_start = threading.Thread.start

    def record_start(thread, *args, **kwargs):
        if is_scheduler_thread(thread):
            starts.append(thread)
        return real_start(thread, *args, **kwargs)

    monkeypatch.setattr(threading.Thread, "start", record_start)
    try:
        for _ in range(20):
            library.warm_predicted("写代码")
        assert len(starts) == 1, "identical pending predictions must share one task"
    finally:
        library.end_interaction(token)
        for worker in starts:
            worker.join(timeout=5)
    assert library._movies["写代码"].frame_calls == 1


def test_high_priority_burst_shares_one_inflight_batch(library, monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    starts = []
    real_start = threading.Thread.start

    def warm(*args, **kwargs):
        entered.set()
        assert release.wait(10)

    def record_start(thread, *args, **kwargs):
        if is_scheduler_thread(thread):
            starts.append(thread)
        return real_start(thread, *args, **kwargs)

    monkeypatch.setattr(library, "_warm_clips", warm)
    monkeypatch.setattr(threading.Thread, "start", record_start)
    try:
        library.schedule_high_priority_warm()
        spin_until(entered.is_set)
        for _ in range(20):
            library.schedule_high_priority_warm()
        assert len(starts) == 1, "repeated requests must not create waiting batches"
    finally:
        release.set()
        for worker in starts:
            worker.join(timeout=5)


def test_high_batch_captures_generation_before_worker_starts(library, monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    warmed = []
    real_run = threading.Thread.run

    def gated_run(thread):
        if not is_scheduler_thread(thread):
            return real_run(thread)
        entered.set()
        try:
            assert release.wait(10)
            return real_run(thread)
        finally:
            finished.set()

    monkeypatch.setattr(threading.Thread, "run", gated_run)
    monkeypatch.setattr(library, "_warm_clips", lambda *a, **kw: warmed.append(kw))
    try:
        library.schedule_high_priority_warm()
        spin_until(entered.is_set)
        library.pause_warm()
        library.resume_warm()
    finally:
        release.set()
    spin_until(finished.is_set)
    assert not warmed, "a delayed worker must not adopt the resumed generation"


def test_stale_release_cannot_resume_new_hold(library):
    old = library.begin_interaction()
    library._warm_low_priority_background()
    library.pause_warm()
    library.resume_warm()
    current = library.begin_interaction()
    library._low_warm_timer.stop()
    library._warm_low_priority_background()
    library.end_interaction(old)
    drain_window()
    assert "写代码" not in library._movies
    library.end_interaction(current)
    spin_until(lambda: library._low_first_frames_done)


def test_shutdown_discards_queued_release_and_rejects_rescheduling(library):
    token = library.begin_interaction()
    library._warm_low_priority_background()
    library.end_interaction(token)
    library.shutdown()
    library.resume_warm()
    library.schedule_low_priority_warm()
    library.schedule_high_priority_warm()
    library.warm_predicted("写代码")
    drain_window()
    assert "写代码" not in library._movies
    assert not any(timer.isActive() for timer in library.findChildren(QTimer))


@pytest.mark.parametrize("kind", ["high", "predicted"])
def test_start_failure_releases_claim_for_next_request(library, monkeypatch, caplog, kind):
    real_start = threading.Thread.start
    calls = 0

    def fail_once(thread, *args, **kwargs):
        nonlocal calls
        if is_scheduler_thread(thread):
            calls += 1
            if calls == 1:
                raise RuntimeError("injected thread start failure")
        return real_start(thread, *args, **kwargs)

    monkeypatch.setattr(threading.Thread, "start", fail_once)
    request = (library.schedule_high_priority_warm if kind == "high"
               else lambda: library.warm_predicted("写代码"))
    request()
    assert "injected thread start failure" in caplog.text
    request()
    clip = library.movie(catalog.CLICKS[0] if kind == "high" else "写代码")
    spin_until(lambda: clip.frame_calls == 1)


@pytest.mark.parametrize("source", ["high", "low"])
@pytest.mark.parametrize("include_frames", [True, False])
def test_bulk_frame_claim_merges_predictions_only_when_it_warms_frames(
    library, monkeypatch, source, include_frames,
):
    """Share action work across sources without changing metadata-only policies."""
    library._prewarm_policy = (
        "full" if include_frames else "minimal" if source == "high" else "balanced"
    )
    name = catalog.CLICKS[0] if source == "high" else "写代码"
    clip = library.movie(name)
    entered = threading.Event()
    release = threading.Event()
    starts = []
    real_start = threading.Thread.start

    def blocking_meta():
        clip.meta_calls += 1
        entered.set()
        assert release.wait(10)

    def record_start(thread, *args, **kwargs):
        if is_scheduler_thread(thread):
            starts.append(thread)
        return real_start(thread, *args, **kwargs)

    monkeypatch.setattr(clip, "warm_meta", blocking_meta)
    monkeypatch.setattr(threading.Thread, "start", record_start)
    try:
        if source == "high":
            library.schedule_high_priority_warm()
        else:
            library._warm_low_priority_background()
        spin_until(entered.is_set)
        count_before_prediction = len(starts)
        for _ in range(20):
            library.warm_predicted(name)
        if include_frames:
            assert len(starts) == count_before_prediction, (
                "a bulk batch already owns this generation/action's first frame"
            )
        else:
            spin_until(lambda: clip.frame_calls == 1)
            assert len(starts) == count_before_prediction + 1
    finally:
        release.set()
        for worker in starts:
            worker.join(timeout=5)
    assert clip.frame_calls == 1


def test_prediction_inflight_is_not_repeated_by_high_batch(library, monkeypatch):
    name = catalog.CLICKS[0]
    clip = library.movie(name)
    entered = threading.Event()
    release = threading.Event()
    batch_finished = threading.Event()
    starts = []
    real_start = threading.Thread.start
    real_high = library._warm_all_meta_background

    def blocking_frame():
        clip.frame_calls += 1
        if clip.frame_calls == 1:
            entered.set()
            assert release.wait(10)

    def high(*args, **kwargs):
        try:
            return real_high(*args, **kwargs)
        finally:
            batch_finished.set()

    def record_start(thread, *args, **kwargs):
        if is_scheduler_thread(thread):
            starts.append(thread)
        return real_start(thread, *args, **kwargs)

    # A frame is not ready until the decoder returns; the test boundary must
    # model that rather than treating entry into decode as a populated cache.
    monkeypatch.setattr(clip, "first_frame_ready", lambda: False)
    monkeypatch.setattr(clip, "warm_first_frame", blocking_frame)
    monkeypatch.setattr(library, "_warm_all_meta_background", high)
    monkeypatch.setattr(threading.Thread, "start", record_start)
    try:
        library.warm_predicted(name)
        spin_until(entered.is_set)
        library.schedule_high_priority_warm()
        spin_until(batch_finished.is_set)
        assert clip.frame_calls == 1, "the high batch must share the in-flight prediction"
    finally:
        release.set()
        for worker in starts:
            worker.join(timeout=5)


def test_cancelled_batch_completion_rearms_timer_on_gui_thread(library, monkeypatch):
    """The worker completion receiver must own every QTimer operation it makes."""
    entered = threading.Event()
    release = threading.Event()
    timer_threads = []
    gui_thread = threading.get_ident()
    real_start = library._low_warm_timer.start

    def blocked_objects(*args, **kwargs):
        entered.set()
        assert release.wait(10)

    def record_timer_start(*args):
        timer_threads.append(threading.get_ident())
        return real_start(*args)

    monkeypatch.setattr(library, "_warm_objects", blocked_objects)
    monkeypatch.setattr(library._low_warm_timer, "start", record_timer_start)
    try:
        library._warm_low_priority_background()
        spin_until(entered.is_set)
        library.pause_warm()
        library.resume_warm()
        library._low_warm_timer.stop()
        timer_threads.clear()  # Ignore the synchronous resume on the GUI thread.
        release.set()
        spin_until(lambda: bool(timer_threads))
        assert timer_threads == [gui_thread]
    finally:
        release.set()


@pytest.mark.parametrize("resolution", ["decode_failure", "pause"])
def test_full_low_batch_retries_an_unfinished_shared_prediction(
    library, monkeypatch, resolution,
):
    """A pending delegated frame is not a completed full-policy warm batch."""
    clip = library.movie("写代码")
    prediction_waiting = threading.Event()
    release_prediction = threading.Event()
    prediction_finished = threading.Event()
    gate_lock = threading.Lock()
    first_gate = True
    attempts = 0
    real_gate = library._await_interaction_clear

    def controlled_gate(generation):
        nonlocal first_gate
        with gate_lock:
            hold_prediction = first_gate
            first_gate = False
        if hold_prediction:
            prediction_waiting.set()
            assert release_prediction.wait(10)
        return real_gate(generation)

    def fail_first_decode():
        nonlocal attempts
        attempts += 1
        if attempts == 1 and resolution == "decode_failure":
            prediction_finished.set()
            raise RuntimeError("injected shared prediction decode failure")
        clip.frame_calls += 1

    monkeypatch.setattr(library, "_await_interaction_clear", controlled_gate)
    monkeypatch.setattr(clip, "warm_first_frame", fail_first_decode)
    try:
        library.warm_predicted("写代码")
        spin_until(prediction_waiting.is_set)
        library._warm_low_priority_background()
        spin_until(lambda: clip.meta_calls > 0 and not library._low_warm_in_flight)
        assert not library._low_first_frames_done, (
            "full-policy completion must wait for the delegated first frame"
        )
        assert not clip.first_frame_ready()
        if resolution == "pause":
            library.pause_warm()
            library.resume_warm()
        release_prediction.set()
        if resolution == "decode_failure":
            spin_until(prediction_finished.is_set)
        spin_until(lambda: clip.first_frame_ready() and library._low_first_frames_done)
        assert clip.frame_calls == 1
    finally:
        release_prediction.set()

