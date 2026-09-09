# -*- coding: utf-8 -*-
"""
WebM-backed clip library（webm 主路线）。

使用 imageio-ffmpeg 自带的静态 ffmpeg 解码透明 webm：
- read_frames(..., pix_fmt='rgba', bits_per_pixel=32, input_params=['-c:v','libvpx-vp9'])
  可正确保留 VP9 alpha，输出 RGBA 原始帧。
- imageio_ffmpeg 内部在 Windows 上使用 STARTUPINFO 隐藏控制台窗口，
  避免旧 ffmpeg 子进程方案导致的“窗口反复出现/消失”。

线程模型：
- 后台 reader 线程只负责把元数据/ RGBA 字节放入有界队列；
- 主线程 QTimer 按视频 fps 从队列取帧，只构造裁边 QImage 并发出 frameChanged；
- 所有 QObject、Signal 和状态写入只发生在主线程。
"""

from __future__ import annotations

from dataclasses import dataclass
import ctypes
import logging
import queue
import sys
import threading

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QBitmap, QImage, QPainter, QPixmap, QRegion

from . import catalog

logger = logging.getLogger(__name__)
TRANSPARENT_CROP_PADDING = 8
ALPHA_FLOOR_MASK = bytes(255 if value == 1 else 0 for value in range(256))


@dataclass(frozen=True, slots=True)
class DecodedFrame:
    """裁掉透明边缘后的图像，以及它在原解码画布中的位置。"""

    image: QImage
    x: int
    y: int
    canvas_width: int
    canvas_height: int

    @property
    def offset(self) -> tuple[int, int]:
        return self.x, self.y

    @property
    def canvas_size(self) -> tuple[int, int]:
        return self.canvas_width, self.canvas_height


def clear_alpha_floor(image: QImage) -> QImage:
    """清除 VP9 Alpha 常见的精确 1 阶底噪，不改变真实半透明边缘。"""
    result = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    if result.isNull():
        return result

    # 用 C 实现的 bytes.translate 生成“仅 Alpha=1 可见”的清除遮罩，
    # 再用 DestinationOut 清掉这些像素。这样 Alpha=2 及以上（真实抗锯齿
    # 边缘）完全原样保留，且会同步清掉透明像素里残留的 RGB。
    alpha = result.convertToFormat(QImage.Format.Format_Alpha8)
    alpha_bytes = bytes(alpha.constBits())
    if b'\x01' not in alpha_bytes:
        return result
    mask_alpha = QImage(
        result.width(),
        result.height(),
        QImage.Format.Format_Alpha8,
    )
    mask_alpha.bits()[:] = alpha_bytes.translate(ALPHA_FLOOR_MASK)
    mask = QImage(
        result.width(),
        result.height(),
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    mask.fill(0xFFFFFFFF)
    mask.setAlphaChannel(mask_alpha)
    painter = QPainter(result)
    painter.setCompositionMode(
        QPainter.CompositionMode.CompositionMode_DestinationOut
    )
    painter.drawImage(0, 0, mask)
    painter.end()
    return result


def trim_transparent_frame(
    image: QImage,
    *,
    padding: int = TRANSPARENT_CROP_PADDING,
    soften_edges: bool = False,
) -> DecodedFrame:
    """裁掉透明压缩噪声，并保留安全边与原画布坐标。"""
    canvas_width, canvas_height = image.width(), image.height()
    if image.isNull():
        return DecodedFrame(QImage(), 0, 0, canvas_width, canvas_height)

    # Alpha=1 必须在计算边界前清掉；否则它虽然不会进入最终画面，仍会把
    # 每一帧的裁剪范围撑大，造成动画边缘/尺寸在播放时抖动。
    working = clear_alpha_floor(image) if soften_edges else image
    bounds = QRegion(QBitmap.fromImage(working.createAlphaMask())).boundingRect()
    if bounds.isEmpty():
        transparent = QImage(
            1,
            1,
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        transparent.fill(0)
        return DecodedFrame(transparent, 0, 0, canvas_width, canvas_height)

    padding = max(0, int(padding))
    if padding:
        bounds = bounds.adjusted(-padding, -padding, padding, padding).intersected(
            image.rect()
        )

    cropped = working.copy(bounds).convertToFormat(
        QImage.Format.Format_ARGB32_Premultiplied
    )

    return DecodedFrame(
        cropped,
        bounds.x(),
        bounds.y(),
        canvas_width,
        canvas_height,
    )


def frame_canvas_image(frame: DecodedFrame) -> QImage:
    """兼容接口需要完整画布时才还原；动画热路径不调用。"""
    if frame.canvas_width <= 0 or frame.canvas_height <= 0:
        return QImage()
    canvas = QImage(
        frame.canvas_width,
        frame.canvas_height,
        QImage.Format.Format_ARGB32,
    )
    canvas.fill(0)
    painter = QPainter(canvas)
    painter.drawImage(frame.x, frame.y, frame.image)
    painter.end()
    return canvas

# 解码输出最多 1280×720，RGBA 单帧约 3.5 MiB。2 帧覆盖约 83ms（24fps），
# 在保留短时调度缓冲的同时，把队列峰值控制在约 7 MiB。
FRAME_QUEUE_SIZE = 2

# 在解码进程内先预乘 Alpha，再面积采样，避免透明背景 RGB 混入边缘。
# 16 位中间格式减小低 Alpha 的量化损失；输出仍是普通 8 位 RGBA。
# 面积采样不产生锐化振铃，较小的外部角色不会被反向放大。
def _decode_filter(width: int, height: int) -> str:
    return (
        "format=gbrap16le,premultiply=inplace=1,"
        "scale=w='min(%d,iw)':h='min(%d,ih)':"
        "force_original_aspect_ratio=decrease:force_divisible_by=2:flags=area,"
        "unpremultiply=inplace=1,format=rgba"
    ) % (width, height)

# 进程内元数据缓存：避免反复切换角色时重复调用 count_frames_and_secs
_META_CACHE: dict[str, tuple[int, float]] = {}
META_CACHE_LIMIT = 256


def _ffmpeg_safe_path(path) -> str:
    """Windows 上尽量转换非 ASCII 路径为短路径，降低 ffmpeg 编码页风险。"""
    value = str(path)
    if sys.platform != 'win32' or value.isascii():
        return value
    try:
        buffer = ctypes.create_unicode_buffer(32_768)
        length = ctypes.windll.kernel32.GetShortPathNameW(
            value,
            buffer,
            len(buffer),
        )
        return buffer.value if length else value
    except (AttributeError, OSError, TypeError):
        return value


def _queue_item(
    frame_queue: queue.Queue,
    item: tuple[str, object],
    stop_evt: threading.Event,
) -> bool:
    """向有界队列写入消息；停止后立即放弃，避免阻塞退出。"""
    while not stop_evt.is_set():
        try:
            frame_queue.put(item, timeout=0.02)
            return True
        except queue.Full:
            continue
    return False


def _reader_loop(
    path: str,
    decode_filter: str,
    bpp: int,
    stop_evt: threading.Event,
    frame_queue: queue.Queue,
) -> None:
    """纯后台解码循环：不访问 QObject，只向队列写消息。"""
    if imageio_ffmpeg is None:
        _queue_item(
            frame_queue,
            ('error', str(_IMPORT_ERROR or 'imageio_ffmpeg 不可用')),
            stop_evt,
        )
        return
    gen = None
    try:
        gen = imageio_ffmpeg.read_frames(
            path,
            pix_fmt='rgba',
            bits_per_pixel=bpp * 8,
            input_params=['-c:v', 'libvpx-vp9'],
            output_params=['-vf', decode_filter],
        )
        meta = dict(next(gen))
        if not _queue_item(frame_queue, ('meta', meta), stop_evt):
            return
        for frame in gen:
            if not _queue_item(frame_queue, ('frame', frame), stop_evt):
                return
        if not stop_evt.is_set():
            _queue_item(frame_queue, ('end', None), stop_evt)
    except Exception as exc:
        _queue_item(frame_queue, ('error', str(exc)), stop_evt)
        if not stop_evt.is_set():
            _queue_item(frame_queue, ('end', None), stop_evt)
    finally:
        if gen is not None:
            try:
                gen.close()
            except Exception:
                pass

try:
    import imageio_ffmpeg
except Exception as exc:  # pragma: no cover - 依赖缺失时无法使用 webm 路线
    imageio_ffmpeg = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


class WebMClip(QObject):
    """与窗口层期望的媒体播放器接口兼容。"""

    available = imageio_ffmpeg is not None

    frameChanged = Signal(int)
    finished = Signal()
    errorOccurred = Signal(str)

    def __init__(
        self,
        path,
        parent: QObject | None = None,
        *,
        decode_size: tuple[int, int] | None = None,
        soft_edges: bool = False,
    ) -> None:
        super().__init__(parent)
        self.path = path
        self._bpp = 4  # RGBA
        self._decode_max_w, self._decode_max_h = (
            decode_size or catalog.decode_size_for_scale(catalog.DEFAULT_SCALE)
        )
        self._decode_filter = _decode_filter(self._decode_max_w, self._decode_max_h)
        self._soft_edges = bool(soft_edges)
        self._source_w = catalog.CANVAS_W
        self._source_h = catalog.CANVAS_H
        self._frame_w = catalog.CANVAS_W
        self._frame_h = catalog.CANVAS_H

        # 元数据（惰性填充；由 MovieLibrary 并行 warm 或首次使用时读取）
        self._frame_count = 0
        self._duration = 0.0
        self._fps = 24.0
        self.playback_speed = 1.0

        # 播放状态
        self._queue: queue.Queue = queue.Queue(maxsize=FRAME_QUEUE_SIZE)
        self._stop_evt = threading.Event()
        self._thread: threading.Thread | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(self._timer_interval())
        self._timer.timeout.connect(self._poll)

        self._current_frame: DecodedFrame | None = None
        self._first_frame: DecodedFrame | None = None
        self._frame_index = 0
        self._ended_fired = False
        self._running = False

    # ------------------------------------------------------------ metadata
    def _ensure_meta(self) -> None:
        if self._duration > 0 or imageio_ffmpeg is None:
            return
        key = _ffmpeg_safe_path(self.path)
        cached = _META_CACHE.get(key)
        if cached is not None:
            self._frame_count, self._duration = cached
            if self._frame_count > 0 and self._duration > 0:
                self._fps = self._frame_count / self._duration
            return
        try:
            frames, secs = imageio_ffmpeg.count_frames_and_secs(key)
            if frames and frames > 0:
                self._frame_count = int(frames)
            if secs and secs > 0:
                self._duration = float(secs)
            if self._frame_count > 0 and self._duration > 0:
                self._fps = self._frame_count / self._duration
            _META_CACHE[key] = (self._frame_count, self._duration)
            while len(_META_CACHE) > META_CACHE_LIMIT:
                _META_CACHE.pop(next(iter(_META_CACHE)))
        except Exception as exc:
            logger.warning('webm 元数据读取失败 %s: %s', self.path, exc)
            # 保留默认值，后续 reader 会尝试从 read_frames 的 meta 补充

    def warm_meta(self) -> None:
        """预取元数据（可被线程池并行调用）。"""
        self._ensure_meta()

    def _timer_interval(self) -> int:
        if self._fps > 0:
            return max(1, int(round(1000 / (self._fps * self.playback_speed))))
        return max(1, int(round(catalog.FRAME_MS / self.playback_speed)))

    def frameCount(self) -> int:
        if self._frame_count <= 0:
            self._ensure_meta()
        return max(1, self._frame_count)

    def duration(self) -> float:
        if self._duration <= 0:
            self._ensure_meta()
        return self._duration / self.playback_speed if self._duration > 0 else 0.0

    def known_duration(self) -> float:
        """返回已知时长，不触发同步 ffmpeg 元数据扫描。"""
        return self._duration / self.playback_speed if self._duration > 0 else 0.0

    def currentFrameNumber(self) -> int:
        return self._frame_index

    def currentTimeSeconds(self) -> float:
        if self._fps <= 0:
            return 0.0
        return self._frame_index / (self._fps * self.playback_speed)

    def currentFrame(self) -> DecodedFrame | None:
        return self._current_frame

    def currentPixmap(self):
        """旧诊断接口；运行时窗口直接消费 currentFrame()，不做往返转换。"""
        if self._current_frame is None:
            return QPixmap()
        return QPixmap.fromImage(frame_canvas_image(self._current_frame))

    def sourceSize(self) -> tuple[int, int]:
        """编码素材尺寸；用于诊断和验收，不影响逻辑画布。"""
        return self._source_w, self._source_h

    def decodedSize(self) -> tuple[int, int]:
        """送入 Qt 的有界 RGBA 帧尺寸。"""
        return self._frame_w, self._frame_h

    def set_decode_size(self, width: int, height: int) -> None:
        """更新显示所需解码上限；下次播放按新尺寸重建首帧与 reader。"""
        width, height = max(2, int(width)), max(2, int(height))
        if (width, height) == (self._decode_max_w, self._decode_max_h):
            return
        self.stop()
        self._decode_max_w, self._decode_max_h = width, height
        self._decode_filter = _decode_filter(width, height)
        self._first_frame = None
        self._current_frame = None

    # ------------------------------------------------------------ lifecycle
    def set_playback_speed(self, speed: float) -> None:
        self.playback_speed = max(0.1, float(speed))
        if self._timer.isActive():
            self._timer.setInterval(self._timer_interval())

    def start(self) -> None:
        if self._running:
            return
        if imageio_ffmpeg is None:
            self.errorOccurred.emit(str(_IMPORT_ERROR or 'imageio_ffmpeg 不可用'))
            return

        self._stop_evt = threading.Event()
        self._queue = queue.Queue(maxsize=FRAME_QUEUE_SIZE)
        self._frame_index = 0
        self._ended_fired = False
        self._running = True

        frame_queue = self._queue
        self._thread = threading.Thread(
            target=_reader_loop,
            args=(_ffmpeg_safe_path(self.path), self._decode_filter, self._bpp, self._stop_evt, frame_queue),
            daemon=True,
        )
        self._thread.start()
        self._timer.start()

    def stop(self) -> None:
        self._running = False
        self._timer.stop()
        if self._stop_evt is not None:
            self._stop_evt.set()
        self._thread = None
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def rewind(self, *, preload: bool = False) -> None:
        """重置播放位置；播放中的切换不再同步解码首帧。"""
        self.stop()
        self._frame_index = 0
        if preload:
            if self._first_frame is not None:
                self._current_frame = self._first_frame
            else:
                self._current_frame = None
                self._decode_first_frame_sync()

    def jumpToFrame(self, frame_index: int) -> bool:
        # 本项目只需要回到首帧；完整 seek 通过重启 reader + 丢弃帧实现。
        if frame_index <= 0:
            self.stop()
            self._frame_index = 0
            if self._first_frame is not None:
                self._current_frame = self._first_frame
            else:
                self._current_frame = None
                self._decode_first_frame_sync()
            return True
        return False

    def _decode_first_frame_sync(self) -> None:
        """同步解码首帧，保证 jumpToFrame(0)/currentPixmap 在 start() 前有画面。"""
        if imageio_ffmpeg is None:
            return
        gen = None
        try:
            gen = imageio_ffmpeg.read_frames(
                _ffmpeg_safe_path(self.path),
                pix_fmt='rgba',
                bits_per_pixel=self._bpp * 8,
                input_params=['-c:v', 'libvpx-vp9'],
                output_params=['-vf', self._decode_filter],
            )
            meta = next(gen)
            self._apply_stream_meta(meta)
            frame = next(gen)
            if meta.get('fps'):
                self._fps = float(meta['fps'])
            if meta.get('duration'):
                self._duration = float(meta['duration'])
            if self._frame_count <= 0 and self._fps > 0 and self._duration > 0:
                self._frame_count = int(round(self._fps * self._duration))
            expect = self._frame_w * self._frame_h * self._bpp
            if len(frame) == expect:
                img = QImage(frame, self._frame_w, self._frame_h, self._frame_w * self._bpp,
                             QImage.Format.Format_RGBA8888)
                if not img.isNull():
                    self._current_frame = trim_transparent_frame(
                        img,
                        soften_edges=self._soft_edges,
                    )
                    self._first_frame = self._current_frame
        except Exception as exc:
            logger.warning('webm 首帧预解码失败 %s: %s', self.path, exc)
        finally:
            if gen is not None:
                try:
                    gen.close()
                except Exception:
                    pass

    # ------------------------------------------------------------ reader
    def _apply_stream_meta(self, meta: dict) -> None:
        source_size = meta.get('source_size') or meta.get('size')
        frame_size = meta.get('size') or source_size
        if isinstance(source_size, (tuple, list)) and len(source_size) == 2:
            try:
                width, height = int(source_size[0]), int(source_size[1])
                if width > 0 and height > 0:
                    self._source_w, self._source_h = width, height
            except (TypeError, ValueError):
                pass
        if isinstance(frame_size, (tuple, list)) and len(frame_size) == 2:
            try:
                width, height = int(frame_size[0]), int(frame_size[1])
                if width > 0 and height > 0:
                    self._frame_w, self._frame_h = width, height
            except (TypeError, ValueError):
                pass

        try:
            fps = float(meta.get('fps') or 0.0)
            duration = float(meta.get('duration') or 0.0)
        except (TypeError, ValueError):
            fps = duration = 0.0
        if fps > 0:
            self._fps = fps
        if duration > 0:
            self._duration = duration
        if self._frame_count <= 0 and self._fps > 0 and self._duration > 0:
            self._frame_count = int(round(self._fps * self._duration))
        if self._frame_count > 0 and self._duration > 0:
            _META_CACHE[str(self.path)] = (self._frame_count, self._duration)
            while len(_META_CACHE) > META_CACHE_LIMIT:
                _META_CACHE.pop(next(iter(_META_CACHE)))

    def _poll(self) -> None:
        """主线程按视频帧率逐帧取帧，不跳帧、不积压追帧。

        注意：不能一次清空队列只处理最新帧，否则会把中间帧丢弃，
        导致动画视觉上“快进”。这里每次只取最早的一帧。
        """
        try:
            item = self._queue.get_nowait()
        except queue.Empty:
            return

        kind, payload = item
        if kind == 'meta':
            self._apply_stream_meta(payload)
            self._timer.setInterval(self._timer_interval())
            return
        if kind == 'error':
            self.errorOccurred.emit(str(payload))
            return
        if kind == 'end':
            if not self._ended_fired:
                self._ended_fired = True
                self._running = False
                self._timer.stop()
                self.finished.emit()
            return
        if kind == 'frame' and isinstance(payload, bytes):
            self._process_frame(payload)

    def _process_frame(self, data: bytes) -> None:
        expect = self._frame_w * self._frame_h * self._bpp
        if len(data) != expect:
            logger.warning('webm 帧长度异常: got=%d expect=%d', len(data), expect)
            return
        img = QImage(data, self._frame_w, self._frame_h, self._frame_w * self._bpp,
                     QImage.Format.Format_RGBA8888)
        if img.isNull():
            return
        # 窗口按固定画布绘制；先裁边再补回画布会额外扫描并复制整帧。
        image = (
            clear_alpha_floor(img) if self._soft_edges else
            img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        )
        self._current_frame = DecodedFrame(
            image, 0, 0, self._frame_w, self._frame_h,
        )
        self._frame_index += 1
        self.frameChanged.emit(self._frame_index)
