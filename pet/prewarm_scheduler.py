"""Private MovieLibrary task coordination; clips retain decoder ownership."""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, Signal, Slot

from .webm_clip import session_ending

if TYPE_CHECKING:
    from .library import MovieLibrary


class PrewarmScheduler(QObject):
    """Coalesce transient tasks and resume deferred work on the GUI thread.

    The library's existing state fields remain the observation seam used by
    its callers/tests; all generation and interaction transitions happen here.
    No persistent worker pool or decoder lifecycle is introduced.
    """

    interaction_cleared = Signal(int)

    def __init__(self, library: MovieLibrary) -> None:
        super().__init__(library)
        self._library = library
        self._tasks: set[tuple[int, str]] = set()
        self._frame_claims: dict[tuple[int, str], tuple[int, str]] = {}
        self._running_frames: set[tuple[int, str]] = set()
        self._deferred_low_generation: int | None = None
        self.interaction_cleared.connect(
            self._resume_deferred_low, Qt.ConnectionType.QueuedConnection,
        )

    def active(self, generation: int | None = None) -> bool:
        library = self._library
        return (
            not library._shutdown
            and not library._warm_paused
            and library._prewarm_enabled
            and not session_ending()
            and (generation is None or generation == library._warm_generation)
        )

    def start(
        self,
        key: str,
        run: Callable[[int], None],
        *,
        frame_names: tuple[str, ...] = (),
        require_frame_claim: bool = False,
    ) -> bool:
        """Claim before Thread.start so delayed workers keep their old generation."""
        library = self._library
        with library._warm_state_lock:
            generation = library._warm_generation
            task = generation, key
            if not self.active(generation) or task in self._tasks:
                return False
            frames = tuple((generation, name) for name in frame_names)
            if require_frame_claim and any(frame in self._frame_claims for frame in frames):
                return False
            self._tasks.add(task)
            claimed = []
            for frame in frames:
                if frame not in self._frame_claims:
                    self._frame_claims[frame] = task
                    claimed.append(frame)

        def finish() -> None:
            with library._warm_state_lock:
                self._tasks.discard(task)
                for frame in claimed:
                    if self._frame_claims.get(frame) == task:
                        del self._frame_claims[frame]

        def worker() -> None:
            try:
                run(generation)
            except Exception:
                logging.exception('动画预热任务失败: %s', key)
            finally:
                finish()

        try:
            threading.Thread(target=worker, daemon=True).start()
        except Exception:
            finish()
            logging.exception('启动动画预热线程失败: %s', key)
            return False
        return True

    def warm_frame(
        self, name: str, generation: int, source: str, warm: Callable[[], None],
    ) -> bool:
        """Share an action's first frame across bulk and predictive requests.

        Batch claims are reserved before starting their worker, including the
        metadata phase. Metadata-only policies reserve no first-frame work.
        Direct internal warm calls claim just their current decode operation.
        False means this caller did not finish its frame operation; in
        particular a pending foreign claim is not a completed bulk batch.
        """
        library = self._library
        frame = generation, name
        task = generation, source
        with library._warm_state_lock:
            if not self.active(generation):
                return False
            owner = self._frame_claims.get(frame)
            if (owner is not None and owner != task) or frame in self._running_frames:
                return False
            temporary_claim = owner is None
            if temporary_claim:
                self._frame_claims[frame] = task
            self._running_frames.add(frame)
        try:
            if self.active(generation):
                warm()
                return True
            return False
        finally:
            with library._warm_state_lock:
                self._running_frames.discard(frame)
                if temporary_claim and self._frame_claims.get(frame) == task:
                    del self._frame_claims[frame]

    def pause(self) -> None:
        library = self._library
        library._low_warm_timer.stop()
        with library._interaction_cond:
            library._warm_paused = True
            library._warm_generation += 1
            library._interaction_holders = 0
            library._interaction_active.clear()
            self._deferred_low_generation = None
            library._interaction_cond.notify_all()

    def begin_interaction(self) -> int:
        library = self._library
        with library._interaction_cond:
            if not library._shutdown:
                library._interaction_holders += 1
                library._interaction_active.set()
            return library._warm_generation

    def end_interaction(self, token: int | None) -> None:
        library = self._library
        with library._interaction_cond:
            generation = library._warm_generation
            if token is not None and token != generation:
                return
            if library._interaction_holders <= 0:
                return
            library._interaction_holders -= 1
            if library._interaction_holders:
                return
            library._interaction_active.clear()
            library._interaction_cond.notify_all()
            deferred = self._deferred_low_generation == generation
        if deferred:
            # The release may originate in a worker. A QObject receiver plus an
            # explicit queued connection keeps timer/clip access on the GUI thread.
            self.interaction_cleared.emit(generation)

    def defer_low_during_interaction(self) -> bool:
        library = self._library
        with library._interaction_cond:
            if library._interaction_holders <= 0:
                return False
            self._deferred_low_generation = library._warm_generation
            return True

    def await_interaction_clear(self, generation: int) -> bool:
        library = self._library
        with library._interaction_cond:
            while library._interaction_holders > 0:
                if not self.active(generation):
                    return False
                # Both the final release and cancellation notify under this lock.
                library._interaction_cond.wait()
            return self.active(generation)

    @Slot(int)
    def _resume_deferred_low(self, generation: int) -> None:
        library = self._library
        with library._interaction_cond:
            if (not self.active(generation)
                    or self._deferred_low_generation != generation
                    or library._interaction_holders > 0):
                return
            self._deferred_low_generation = None
        library._warm_low_priority_background()
