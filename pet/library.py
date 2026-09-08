# -*- coding: utf-8 -*-
"""
Media library —— 多形象，自动识别 webm / gif。

支持按角色 ID 加载不同形象：
- 默认从内置 assets/characters/<character_id>/videos/ 加载
- 也支持外部扩展目录（exe 同目录/用户数据目录下的 characters/<id>/videos）
- 如果目录里是 *.webm 则用 WebMClip；如果是 *.gif 则用 GifClip

对外保持与窗口层一致的形状：
- movie(name) -> clip object
- movies() -> name -> clip mapping
- frames(name) / duration(name)（秒）

WebMClip 基于 imageio-ffmpeg 解码高分辨率透明 webm（RGBA），运行时再按窗口尺寸平滑缩放。
GifClip 基于 QMovie 播放透明 GIF（兼容旧 GIF 路线）。
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QMovie, QPixmap

from . import catalog
from .webm_clip import (
    DecodedFrame,
    WebMClip,
    frame_canvas_image,
    trim_transparent_frame,
)


# QMovie 播放速度补偿（%）：GIF 路线使用，校准 QMovie 偏慢问题
PLAYBACK_SPEED = 120
DEFAULT_CLIP_CACHE_SIZE = 8


@dataclass(frozen=True)
class MediaSource:
    """一个动作的轻量索引记录。

    目录扫描阶段只保留路径和格式，不创建 QMovie/QTimer/ffmpeg reader。
    这样新增角色或动作时，索引层不再被具体播放器实现绑死。
    """

    name: str
    path: Path
    media_type: str
    folder: str = ''


class GifClip(QObject):
    """QMovie 包装：与 WebMClip 接口兼容的 GIF 播放器。"""

    frameChanged = Signal(int)
    finished = Signal()
    errorOccurred = Signal(str)

    def __init__(
        self,
        path: Path,
        parent: QObject | None = None,
        *,
        soft_edges: bool = False,
    ) -> None:
        super().__init__(parent)
        self.path = path
        self._soft_edges = bool(soft_edges)
        self._movie = QMovie(str(path))
        self._movie.setCacheMode(QMovie.CacheMode.CacheNone)
        self._movie.setSpeed(PLAYBACK_SPEED)
        self._movie.frameChanged.connect(self._on_frame_changed)
        self._movie.finished.connect(self.finished)
        self._movie.error.connect(lambda err: self.errorOccurred.emit(str(err)))
        self._frame_count = 0
        self._current_frame: DecodedFrame | None = None
        self.playback_speed = 1.0
        self._movie.jumpToFrame(0)
        self._refresh_frame()
        self._frame_count = max(0, self._movie.frameCount())

    def frameCount(self) -> int:
        if self._frame_count <= 0:
            self._frame_count = max(0, self._movie.frameCount())
        return max(1, self._frame_count)

    def duration(self) -> float:
        return self.frameCount() * catalog.FRAME_MS / 1000.0 / self.playback_speed

    def known_duration(self) -> float:
        return self.duration()

    def currentFrameNumber(self) -> int:
        return self._movie.currentFrameNumber()

    def currentTimeSeconds(self) -> float:
        n = self._movie.currentFrameNumber()
        frames = self.frameCount()
        if frames <= 0:
            return 0.0
        return n * (self.duration() / frames)

    def currentFrame(self) -> DecodedFrame | None:
        if self._current_frame is None:
            self._refresh_frame()
        return self._current_frame

    def currentPixmap(self):
        """旧诊断接口；窗口热路径直接消费 currentFrame()。"""
        frame = self.currentFrame()
        return QPixmap() if frame is None else QPixmap.fromImage(frame_canvas_image(frame))

    def set_playback_speed(self, speed: float) -> None:
        self.playback_speed = max(0.1, float(speed))
        self._movie.setSpeed(int(round(PLAYBACK_SPEED * self.playback_speed)))

    def start(self) -> None:
        self._movie.start()

    def stop(self) -> None:
        self._movie.stop()

    def jumpToFrame(self, frame_index: int) -> bool:
        if frame_index < 0:
            frame_index = 0
        total = self._movie.frameCount()
        if total > 0 and frame_index >= total:
            frame_index = total - 1
        changed = self._movie.jumpToFrame(frame_index)
        if changed:
            self._refresh_frame()
        return changed

    def warm_meta(self) -> None:
        # GIF 由 QMovie 直接管理元数据，无需额外预热
        return

    def _on_frame_changed(self, n: int) -> None:
        self._refresh_frame()
        fc = self._movie.frameCount()
        if fc > 0:
            self._frame_count = fc
        self.frameChanged.emit(n)

    def _refresh_frame(self) -> None:
        image = self._movie.currentImage()
        if image is not None and not image.isNull():
            self._current_frame = trim_transparent_frame(
                image,
                soften_edges=self._soft_edges,
            )


class MovieLibrary(QObject):
    """素材库：加载指定形象的 webm 或 gif 动画。"""

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        character_id: str | None = None,
        asset_dir: Path | str | None = None,
        manifest: Mapping[str, str] | None = None,
        decode_size: tuple[int, int] | None = None,
        cache_limit: int = DEFAULT_CLIP_CACHE_SIZE,
        soft_edges: bool = False,
    ) -> None:
        super().__init__(parent)
        self.character_id = character_id or catalog.DEFAULT_CHARACTER
        if asset_dir is not None:
            self._asset_dir = Path(asset_dir)
        else:
            self._asset_dir = catalog.resolve_character_video_dir(self.character_id)
        self._file_map = None if manifest is None else dict(manifest)
        self._decode_size = decode_size or catalog.decode_size_for_scale(catalog.DEFAULT_SCALE)
        self._cache_limit = max(1, int(cache_limit))
        self._soft_edges = bool(soft_edges)
        self._active_name: str | None = None
        self.category_hints = catalog.load_character_manifest(self.character_id, self._asset_dir)
        self.manifest = self.category_hints  # 兼容旧窗口/插件调用
        self.folder_map: dict[str, str] = {}
        self.folder_files: dict[str, list[str]] = {}
        self._sources: dict[str, MediaSource] = {}
        self._movies: OrderedDict[str, object] = OrderedDict()
        self.media_type: str = 'webm'

        self._load_all()

    def _load_all(self) -> None:
        if self._file_map is None:
            # 自动扫描该形象目录下的 webm 或 gif，支持不同角色有不同动作集
            if not self._asset_dir.is_dir():
                raise FileNotFoundError(
                    f"角色素材目录不存在: {self._asset_dir}（character_id={self.character_id}）"
                )
            webm_files = sorted(self._asset_dir.rglob('*.webm'))
            gif_files = sorted(self._asset_dir.rglob('*.gif'))
            files = webm_files + gif_files
            if not files:
                raise FileNotFoundError(
                    f"角色素材目录中没有 webm/gif 文件: {self._asset_dir}"
                )
            if webm_files and gif_files:
                self.media_type = 'mixed'
            elif webm_files:
                self.media_type = 'webm'
            else:
                self.media_type = 'gif'
            self._file_map = {}
            self.folder_map = {}
            self.folder_files = {}
            for f in files:
                rel = f.relative_to(self._asset_dir)
                name = f.stem
                if name in self._file_map:
                    previous = self._asset_dir / self._file_map[name]
                    raise ValueError(
                        f'动画名冲突：{name!r} 同时对应 {previous} 和 {f}'
                    )
                self._file_map[name] = rel.as_posix()
                folder = rel.parts[0].lower() if len(rel.parts) > 1 else ''
                self.folder_map[name] = folder
                self.folder_files.setdefault(folder, []).append(name)

        missing: list[str] = []
        resolved: dict[str, Path] = {}
        base = self._asset_dir.resolve()
        for name, fname in self._file_map.items():
            try:
                path = (base / fname).resolve()
            except (OSError, RuntimeError):
                path = base / fname
            if not path.is_relative_to(base):
                missing.append(f"{name}: 非法素材路径 {fname}")
                continue
            if not path.is_file():
                missing.append(f"{name}: {path}")
                continue
            resolved[name] = path

        if missing:
            raise FileNotFoundError("缺少素材文件: " + ", ".join(missing))

        for name, path in resolved.items():
            folder = self.folder_map.get(name, '')
            media_type = 'gif' if path.suffix.lower() == '.gif' else 'webm'
            self._sources[name] = MediaSource(name, path, media_type, folder)

    def movie(self, name: str):
        """按需创建并缓存播放器；索引不存在时保持原有 KeyError 语义。"""
        if name not in self._sources:
            raise KeyError(name)
        movie = self._movies.get(name)
        if movie is not None:
            self._movies.move_to_end(name)
            return movie
        source = self._sources[name]
        if source.media_type == 'gif':
            movie = GifClip(
                source.path,
                parent=self,
                soft_edges=self._soft_edges,
            )
        else:
            movie = WebMClip(
                source.path,
                parent=self,
                decode_size=self._decode_size,
                soft_edges=self._soft_edges,
            )
        self._movies[name] = movie
        self._trim_cache()
        return movie

    def activate(self, name: str):
        """取得并保护当前播放器，LRU 只淘汰非活动动作。"""
        previous = self._active_name
        self._active_name = name
        try:
            movie = self.movie(name)
        except Exception:
            self._active_name = previous
            raise
        self._trim_cache()
        return movie

    def deactivate(self, name: str | None = None) -> None:
        if name is None or name == self._active_name:
            self._active_name = None

    def _trim_cache(self) -> None:
        while len(self._movies) > self._cache_limit:
            candidate = next(
                (name for name in self._movies if name != self._active_name),
                None,
            )
            if candidate is None:
                return
            self._discard(candidate)

    def _discard(self, name: str) -> None:
        clip = self._movies.pop(name, None)
        if clip is None:
            return
        clip.stop()
        clip.deleteLater()

    def frames(self, name: str) -> int:
        return self.movie(name).frameCount()

    def duration(self, name: str) -> float:
        return self.movie(name).duration()

    def names(self) -> list[str]:
        return list(self._sources.keys())

    def movies(self) -> dict[str, object]:
        """返回已经创建的播放器；未播放动作不会被强制实例化。"""
        return dict(self._movies)

    def loaded_count(self) -> int:
        """当前已创建的播放器数量，供诊断和性能回归测试使用。"""
        return len(self._movies)

    def stop_all(self) -> None:
        """停止全部媒体 reader；角色切换和退出共用这一处清理逻辑。"""
        for clip in self._movies.values():
            clip.stop()

    def close(self) -> None:
        """关闭媒体库并释放已创建播放器；可重复调用。"""
        self._active_name = None
        for name in list(self._movies):
            self._discard(name)

    def set_decode_size(self, width: int, height: int) -> None:
        """同步更新所有 WebM clip 的显示解码上限。"""
        self._decode_size = (int(width), int(height))
        for clip in self._movies.values():
            setter = getattr(clip, 'set_decode_size', None)
            if setter is not None:
                setter(*self._decode_size)

    def set_soft_edges(self, enabled: bool) -> None:
        """切换 Alpha=1 底噪清理；释放旧播放器，确保后续帧统一处理。"""
        enabled = bool(enabled)
        if enabled == self._soft_edges:
            return
        self.close()
        self._soft_edges = enabled
