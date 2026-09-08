#!/usr/bin/env python3
"""从 dsh-pet 源 MP4 生成高质量透明 WebM。

处理链：
1. 用原项目 watermark_mask_v5.mkv 填充水印区域；
2. 在 1280x720 原始分辨率上做 YCbCr 色差抠图和边缘连通清理；
3. 沿背景色差方向做绿色溢色抑制；
4. 以 1280x720、24fps、VP9 alpha 输出，运行时再缩放到窗口尺寸。

用法示例：
    python tools/build_hq_webm.py \
      --src-dir /private/tmp/dsh-quality/sources \
      --mask /private/tmp/dsh-quality/sources/watermark_mask_v5.mkv \
      --out-dir /private/tmp/dsh-quality/step-hq
"""

from __future__ import annotations

import argparse
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from scipy.ndimage import convolve, distance_transform_edt, label

W, H, FPS = 1280, 720, 24
CRF = 24
WATERMARK_CLEAR_W, WATERMARK_CLEAR_H = 240, 130
CHROMA_IN, CHROMA_OUT = 8.0, 28.0
FLOOD_TOL, DESPILL_BAND = 16.0, 42.0

# Release 中的源视频使用拼音名，运行时素材使用中文名。
SOURCE_TO_ANIM = {
    'beiluoye-yanmo': '被落叶淹没',
    'beishubiao-tuozhuai-xuankong-fankui': '被鼠标拖拽悬空反馈',
    'beixiayitiao-zhamao': '被吓一跳（炸毛）',
    'chaoda-shenlanyao': '超大伸懒腰',
    'chi-baifan': '吃白饭',
    'chi-bingqilin-ronghua': '吃冰淇淋融化',
    'chi-token': '吃Token',
    'chi-wancan': '吃晚餐',
    'chi-wucan': '吃午餐',
    'chi-zaocan': '吃早餐',
    'chui-qiqiu': '吹气球',
    'da-keshui-bei-jingxing': '打瞌睡被惊醒',
    'daiji-huxi-xiuxian': '待机呼吸休闲',
    'dakou-chi-lingshi': '大口吃零食',
    'dianji-huiying-aojiao-shengqi-ceshen-zhanshi': '点击回应 - 傲娇生气（侧身展示）',
    'dianji-huiying-haixiu-jingya': '点击回应 - 害羞惊讶',
    'dianji-huiying-kaixin-yuedong': '点击回应 - 开心跃动',
    'dongwu-huanrao': '动物环绕',
    'dongzhangxiwang': '东张西望',
    'duixueren': '堆雪人',
    'fang-fengzheng': '放风筝',
    'haqian-liantian': '哈欠连天',
    'jingyu-tu-paopao-texiao': '鲸鱼吐泡泡特效',
    'keai-zhaiwu': '可爱宅舞',
    'lanjing-xianshi': '蓝鲸现世',
    'nvpu-quxi-liyi': '女仆屈膝礼仪',
    'pangxie-zoulu': '螃蟹走路',
    'qingkuai-jilu': '轻快记录',
    'qingkuai-yaobaiwu': '轻快摇摆舞',
    'shendu-sikao-suisuinian': '深度思考碎碎念',
    'touchi-lingshi-bei-zhuazhu': '偷吃零食被抓住',
    'wan-shuiqiang': '玩水枪',
    'wan-youxi-qijibaituai': '玩游戏气急败坏',
    'xiaofudu-yuandi-360du-xuanzhuan-zhanshi': '小幅度原地 360 度旋转展示',
    'xiaotiqin-yanzou': '小提琴演奏',
    'xie-daima': '写代码',
    'yaoshan-naliang': '摇扇纳凉',
    'yong-jingyu-weiba-paidadi': '用鲸鱼尾巴拍打地面',
    'youxian-hengga': '悠闲哼歌',
    'youya-nvpuwu': '优雅女仆舞',
    'yuandi-dunxia-wan-wanju-qiche': '原地蹲下玩玩具汽车',
    'yuandi-piaofu-tabu': '原地漂浮踏步',
    'yuandi-qiaoji-zhuomian-hudong': '原地敲击桌面互动',
    'yuandi-tiaoyue-zhuasui-touding-wupin': '原地跳跃抓碎头顶物品',
    'yuandi-xiaoqi-chenmian': '原地小憩沉眠',
    'yuandi-zhongli-xiadun-yasuo': '原地重力下蹲压缩',
    'yuandi-zhuanxin-wan-mofang': '原地专心玩魔方',
    'yuandi-zuozhuan-benpao': '原地左转奔跑',
    'zhao-jingzi': '照镜子',
    'zhengti-huanzhuang-shise': '整体换装试色',
    'zhongqiu-shangyue-chi-yuebing': '中秋赏月吃月饼',
}


def _read_exact(stream, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b''.join(chunks)


def _kth_nearest(mask: np.ndarray, k: int = 5) -> tuple[np.ndarray, np.ndarray]:
    current = mask.copy()
    iy = ix = None
    for _ in range(k):
        _, indices = distance_transform_edt(current, return_indices=True)
        iy, ix = indices
        used = np.zeros_like(current, dtype=bool)
        used[iy[mask], ix[mask]] = True
        current |= used
    assert iy is not None and ix is not None
    return iy, ix


def _fill_watermark(src: Path, mask_path: Path, dst: Path, ffmpeg: str) -> None:
    raw = W * H * 3
    mask_raw = W * H
    reader = subprocess.Popen(
        [ffmpeg, '-hide_banner', '-loglevel', 'error', '-i', str(src),
         '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
        stdout=subprocess.PIPE,
    )
    mask_reader = subprocess.Popen(
        [ffmpeg, '-hide_banner', '-loglevel', 'error', '-i', str(mask_path),
         '-f', 'rawvideo', '-pix_fmt', 'gray', '-'],
        stdout=subprocess.PIPE,
    )
    writer = subprocess.Popen(
        [ffmpeg, '-y', '-hide_banner', '-loglevel', 'error',
         '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
         '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '18', '-preset', 'fast', str(dst)],
        stdin=subprocess.PIPE,
    )
    frames = 0
    try:
        while True:
            buf = _read_exact(reader.stdout, raw)
            if len(buf) < raw:
                break
            mbuf = _read_exact(mask_reader.stdout, mask_raw)
            if len(mbuf) < mask_raw:
                raise RuntimeError(f'mask 帧数不足: {mask_path}')
            frame = np.frombuffer(buf, np.uint8).reshape(H, W, 3).copy()
            wm = np.frombuffer(mbuf, np.uint8).reshape(H, W) == 255
            if wm.any():
                iy, ix = _kth_nearest(wm)
                frame[wm] = frame[np.clip(iy[wm], 0, H - 1), np.clip(ix[wm], 0, W - 1)]
            writer.stdin.write(frame.tobytes())
            frames += 1
    finally:
        reader.stdout.close()
        mask_reader.stdout.close()
        writer.stdin.close()
        rc = (reader.wait(), mask_reader.wait(), writer.wait())
    if rc != (0, 0, 0):
        raise RuntimeError(f'去水印失败 {src.name}: returncodes={rc}')
    if frames < 2:
        raise RuntimeError(f'去水印没有生成有效帧: {src.name}')


def _rgb_to_yuv(frame: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    r = frame[..., 0].astype(np.float32)
    g = frame[..., 1].astype(np.float32)
    b = frame[..., 2].astype(np.float32)
    y = np.clip(16 + 0.257 * r + 0.504 * g + 0.098 * b, 16, 235).astype(np.uint8)
    u = np.clip(128 - 0.148 * r - 0.291 * g + 0.439 * b, 16, 240)
    v = np.clip(128 + 0.439 * r - 0.368 * g - 0.071 * b, 16, 240)
    u = u.reshape(H // 2, 2, W // 2, 2).mean(axis=(1, 3)).astype(np.uint8)
    v = v.reshape(H // 2, 2, W // 2, 2).mean(axis=(1, 3)).astype(np.uint8)
    return y, u, v


def _rgb_to_ycbcr(frame: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rgb = frame.astype(np.float32)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    y = 0.299 * r + 0.587 * g + 0.114 * b
    cb = (b - y) * 0.564 + 128.0
    cr = (r - y) * 0.713 + 128.0
    return y, cb, cr


def _ycbcr_to_rgb(y: np.ndarray, cb: np.ndarray, cr: np.ndarray) -> np.ndarray:
    r = y + 1.402 * (cr - 128.0)
    g = y - 0.344136 * (cb - 128.0) - 0.714136 * (cr - 128.0)
    b = y + 1.772 * (cb - 128.0)
    return np.clip(np.stack((r, g, b), axis=-1), 0, 255).astype(np.uint8)


def _detect_background_chroma(frame: np.ndarray) -> tuple[float, float]:
    """用四角色差直方图估计低饱和绿幕的 Cb/Cr 键值。"""
    h, w = frame.shape[:2]
    cw, ch = max(2, w // 5), max(2, h // 5)
    step = 4
    sample = np.concatenate((
        frame[:ch:step, :cw:step].reshape(-1, 3),
        frame[:ch:step, -cw::step].reshape(-1, 3),
        frame[-ch::step, :cw:step].reshape(-1, 3),
        frame[-ch::step, -cw::step].reshape(-1, 3),
    ), axis=0)
    _, cb, cr = _rgb_to_ycbcr(sample)
    cb_bin = np.clip(cb.astype(np.int16) // 8, 0, 31)
    cr_bin = np.clip(cr.astype(np.int16) // 8, 0, 31)
    bins = cb_bin * 32 + cr_bin
    mode = int(np.bincount(bins, minlength=1024).argmax())
    selected = bins == mode
    return float(cb[selected].mean()), float(cr[selected].mean())


def _encode_alpha(src: Path, dst: Path, ffmpeg: str) -> None:
    raw = W * H * 3
    reader = subprocess.Popen(
        [ffmpeg, '-hide_banner', '-loglevel', 'error', '-i', str(src),
         '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
        stdout=subprocess.PIPE,
    )
    writer = subprocess.Popen(
        [ffmpeg, '-y', '-hide_banner', '-loglevel', 'error',
         '-f', 'rawvideo', '-pix_fmt', 'yuva420p', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
         '-c:v', 'libvpx-vp9', '-pix_fmt', 'yuva420p', '-crf', str(CRF), '-b:v', '0',
         '-auto-alt-ref', '0', '-row-mt', '1', '-deadline', 'good', '-cpu-used', '4', '-an', str(dst)],
        stdin=subprocess.PIPE,
    )
    frames = 0
    try:
        while True:
            buf = _read_exact(reader.stdout, raw)
            if len(buf) < raw:
                break
            frame = np.frombuffer(buf, np.uint8).reshape(H, W, 3).copy()
            y, cb, cr = _rgb_to_ycbcr(frame)
            key_cb, key_cr = _detect_background_chroma(frame)
            dist = np.hypot(cb - key_cb, cr - key_cr)
            t = np.clip((dist - CHROMA_IN) / (CHROMA_OUT - CHROMA_IN), 0, 1)
            alpha = (t * t * (3.0 - 2.0 * t) * 255.0).astype(np.uint8)

            # PerfectPixel 的色差空间 despill：只沿绿幕的 Cb/Cr 方向回收边缘绿，不压暗角色。
            key_vec_cb, key_vec_cr = key_cb - 128.0, key_cr - 128.0
            key_len = max(float(np.hypot(key_vec_cb, key_vec_cr)), 1.0)
            pcb, pcr = cb - 128.0, cr - 128.0
            proj = (pcb * key_vec_cb + pcr * key_vec_cr) / key_len
            band = np.clip((DESPILL_BAND - dist) / DESPILL_BAND, 0, 1)
            weight = band * band * (3.0 - 2.0 * band) * 0.92
            spill = (proj > 0) & (dist < DESPILL_BAND)
            amount = proj * weight * spill
            pcb -= (key_vec_cb / key_len) * amount
            pcr -= (key_vec_cr / key_len) * amount
            frame = _ycbcr_to_rgb(y, pcb + 128.0, pcr + 128.0)

            # 从四边连通的背景色做 flood fill，清除地面阴影和压缩噪声，但保留主体内部同色细节。
            key_connected = dist <= FLOOD_TOL
            components, component_count = label(key_connected, structure=np.array(
                [[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=np.uint8,
            ))
            border_labels = np.unique(np.concatenate((
                components[0, :], components[-1, :], components[:, 0], components[:, -1],
            )))
            border_labels = border_labels[border_labels > 0]
            background = np.isin(components, border_labels)
            alpha[background] = 0

            # 清掉孤立压缩点，并填补被噪声包围的 1px 小孔。
            opaque = alpha > 20
            neighbors = convolve(opaque.astype(np.uint8), np.ones((3, 3), np.uint8), mode='constant') - opaque
            alpha[(alpha > 20) & (neighbors == 0)] = 0
            alpha[(alpha <= 20) & (neighbors >= 7)] = 255

            # 源片左上角固定水印在少数帧会留下 1px 残点；该区域不可能出现角色主体。
            alpha[:WATERMARK_CLEAR_H, :WATERMARK_CLEAR_W] = 0
            frame[:WATERMARK_CLEAR_H, :WATERMARK_CLEAR_W] = 0

            y, u, v = _rgb_to_yuv(frame)
            writer.stdin.write(y.tobytes() + u.tobytes() + v.tobytes() + alpha.tobytes())
            frames += 1
    finally:
        reader.stdout.close()
        writer.stdin.close()
        rc = (reader.wait(), writer.wait())
    if rc != (0, 0):
        raise RuntimeError(f'抠图编码失败 {src.name}: returncodes={rc}')
    if frames < 2:
        raise RuntimeError(f'抠图没有生成有效帧: {src.name}')


def _process_one(job: tuple[Path, Path, Path, str, bool]) -> str:
    source, mask, out_dir, ffmpeg, force = job
    name = SOURCE_TO_ANIM[source.stem]
    output = out_dir / f'{name}.webm'
    if not force and output.exists() and output.stat().st_size > 100_000:
        probe = subprocess.run(
            [str(Path(ffmpeg).with_name('ffprobe')), '-v', 'error', '-show_entries',
             'stream=codec_name,width,height', '-of', 'csv=p=0', str(output)],
            capture_output=True, text=True,
        )
        if probe.returncode == 0 and 'vp9,1280,720' in probe.stdout:
            return f'{name}: SKIP'

    step01 = out_dir / f'.{name}.step01.mp4'
    _fill_watermark(source, mask, step01, ffmpeg)
    _encode_alpha(step01, output, ffmpeg)
    step01.unlink(missing_ok=True)
    return f'{name}: {output.stat().st_size / 1e6:.2f} MB'


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--src-dir', type=Path, required=True)
    parser.add_argument('--mask', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--ffmpeg', default='ffmpeg')
    parser.add_argument('--workers', type=int, default=min(4, os.cpu_count() or 1))
    parser.add_argument('--force', action='store_true', help='覆盖已有输出')
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    sources = sorted(args.src_dir.glob('*.mp4'))
    if len(sources) != len(SOURCE_TO_ANIM):
        raise SystemExit(f'源视频数量不正确: {len(sources)}，期望 {len(SOURCE_TO_ANIM)}')
    missing = [p.stem for p in sources if p.stem not in SOURCE_TO_ANIM]
    if missing:
        raise SystemExit(f'缺少名称映射: {missing}')

    jobs = [(source, args.mask, args.out_dir, args.ffmpeg, args.force) for source in sources]
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        for index, result in enumerate(executor.map(_process_one, jobs), start=1):
            print(f'[{index}/{len(sources)}] {result}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
