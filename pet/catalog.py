# -*- coding: utf-8 -*-
"""
动画目录（catalog）—— 全部动画名、文件映射、分类与几何常量的"事实来源"。

素材来源：dsh-pet 插件（https://github.com/PC2005-cloud/dsh-pet）的
assets/thumb/*.webm（640×360 透明 webm，VP9 alpha）。

几何常量与原插件 client.js 完全一致：
- 画布 640×360，人物脚底 y=330
- 落地偏移 PAD = 360 - 330 = 30px（绘制时把帧下移 PAD，让脚踩在窗口底线）
"""

import os
import sys
import json
import math
import re
from pathlib import Path

# ---------------------------------------------------------------- 画布几何
# 逻辑画布尺寸。素材可以高于这个尺寸；窗口布局、移动和命中区域始终
# 使用逻辑像素，避免更换 1080p/1440p 素材时连带修改交互参数。
CANVAS_W = 640
CANVAS_H = 360

# macOS Retina 最大按 2× backing pixels 渲染。2560×1440 超分母版在备份/
# 发布素材中保留，App 使用由母版下采样的 1280×720 透明运行代理；默认档位
# 还会按显示尺寸继续有界解码，避免无效 RGBA 像素进入 Python。
RENDER_DPR_CAP = 2.0
DECODE_MAX_W = int(CANVAS_W * RENDER_DPR_CAP)
DECODE_MAX_H = int(CANVAS_H * RENDER_DPR_CAP)


def decode_size_for_scale(
    scale: float,
    dpr: float = RENDER_DPR_CAP,
) -> tuple[int, int]:
    """按显示缩放和实际屏幕 DPR 返回所需解码尺寸（偶数像素）。"""
    dpr = max(1.0, min(RENDER_DPR_CAP, float(dpr)))
    width = min(
        DECODE_MAX_W,
        (math.ceil(CANVAS_W * max(0.1, scale) * dpr) + 1) // 2 * 2,
    )
    height = min(
        DECODE_MAX_H,
        (math.ceil(CANVAS_H * max(0.1, scale) * dpr) + 1) // 2 * 2,
    )
    return max(2, width), max(2, height)

# 脚底在画布内的 y 坐标（与母版一致：640×360 画布脚底 y=330）
FEET_Y = 330 / 360 * CANVAS_H  # = 330

# 落地偏移：帧下移多少让脚底恰好落在窗口底线
PAD = CANVAS_H - FEET_Y        # = 30

# 视频帧时长（毫秒）—— 24fps → 40ms，用于时长/移动插值换算
FRAME_MS = 40

# 动画链概率（与 client.js 一致）：30% 待机 / 10% 转向 / 40% 动作 / 20% 移动
P_IDLE = 0.30
P_TURN = 0.40  # 累计阈值：<0.3 待机，<0.4 转向
P_ACTS = 0.80  # 累计阈值：<0.8 动作，>=0.8 移动

# 移动参数（与 client.js 一致）
MOVE_MIN_PX = 60
MOVE_MAX_PX = 240
MOVE_MARGIN = 20    # 屏幕边缘安全边距
MOVE_LEAD_SEC = 2   # 动画开头 2s 准备动作，位置不动
MOVE_TAIL_SEC = 2   # 动画结尾 2s 收尾动作，位置不动
MOVE_FALLBACK_DURATION_SEC = 6.0  # 素材元数据未知时避免阻塞 UI 的保守估计

# 拖拽判定阈值（像素，缩放前逻辑像素）
DRAG_THRESHOLD = 5

# 交互反馈参数：短延迟用于区分单击/双击，其他反馈保持低频且可打断。
TAP_BURST_WINDOW_MS = 320
LONG_PRESS_MS = 520
CURSOR_POLL_MS = 120
CURSOR_REACTION_RADIUS = 280
CURSOR_DEAD_ZONE = 16
PROACTIVE_GREETING_MIN_MS = 45_000
PROACTIVE_GREETING_MAX_MS = 90_000
EDGE_FEEDBACK_MARGIN = 18
EDGE_BOUNCE_SPEED = 300.0

# 行为预设：概率总和为 1；问候时间用毫秒，避免在窗口层散落魔法数字。
PERSONALITY_PRESETS = {
    'cool': {
        'label': '高冷',
        'idle': 0.82,
        'turn': 0.10,
        'acts': 0.08,
        'move': 0.00,
        'greeting_min_ms': 240_000,
        'greeting_max_ms': 480_000,
        'greeting_chance': 0.20,
        'action_focus': 0.90,
    },
    'quiet': {
        'label': '安静',
        'idle': 0.70,
        'turn': 0.10,
        'acts': 0.20,
        'move': 0.00,
        'greeting_min_ms': 120_000,
        'greeting_max_ms': 240_000,
        'greeting_chance': 0.45,
        'action_focus': 0.78,
    },
    'lively': {
        'label': '活泼',
        'idle': 0.30,
        'turn': 0.10,
        'acts': 0.40,
        'move': 0.20,
        'greeting_min_ms': 45_000,
        'greeting_max_ms': 90_000,
        'greeting_chance': 0.85,
        'action_focus': 0.72,
    },
    'mischievous': {
        'label': '调皮',
        'idle': 0.15,
        'turn': 0.15,
        'acts': 0.50,
        'move': 0.20,
        'greeting_min_ms': 20_000,
        'greeting_max_ms': 45_000,
        'greeting_chance': 1.00,
        'action_focus': 0.76,
    },
    'gentle': {
        'label': '温柔',
        'idle': 0.52,
        'turn': 0.15,
        'acts': 0.25,
        'move': 0.08,
        'greeting_min_ms': 90_000,
        'greeting_max_ms': 180_000,
        'greeting_chance': 0.65,
        'action_focus': 0.80,
    },
}

PERSONALITY_ACTION_FREQUENT_RATIO = 0.40


ACTION_TAG_KEYWORDS = {
    'calm': ('小憩', '哼歌', '思考', '镜子', '摇扇', '提琴', '代码', '记录', '五子棋', '哈欠', 'sleep', 'calm'),
    'social': ('礼仪', '挥手', '礼物', '红包', '动物', '撸猫', 'hello', 'wave'),
    'playful': ('游戏', '玩', '魔', '气球', '陀螺', '水枪', '幽灵', 'Token', '拍打', '敲击', 'play'),
    'active': ('舞', '跳', '风筝', '木马', '毽', '抛接', '秋千', 'dance', 'jump'),
    'gentle': ('花', '灯', '月', '菊', '礼仪', '笛', '提琴', '哼歌', 'gentle'),
    'food': ('吃', '早餐', '午餐', '晚餐', 'food', 'eat'),
}
PERSONALITY_TAG_WEIGHTS = {
    'cool': {'calm': 6, 'food': 1, 'active': -3, 'playful': -3},
    'quiet': {'calm': 5, 'gentle': 2, 'active': -3, 'playful': -2},
    'lively': {'active': 6, 'social': 3, 'playful': 2},
    'mischievous': {'playful': 6, 'active': 2, 'calm': -2},
    'gentle': {'gentle': 6, 'social': 3, 'calm': 2},
}
PERSONALITY_DESCRIPTIONS = {
    'cool': '更多待机，偏爱安静动作，很少主动问候。',
    'quiet': '安静陪伴，偏爱休息、思考和轻柔动作。',
    'lively': '动作丰富，喜欢跳舞、运动和主动问候。',
    'mischievous': '偏爱玩耍和恶作剧，互动更频繁。',
    'gentle': '偏爱轻柔、友好的动作，偶尔主动问候。',
}


def action_tags(name: str, metadata=None) -> tuple[str, ...]:
    explicit = metadata.get(name) if isinstance(metadata, dict) else None
    if isinstance(explicit, list):
        return tuple(tag for tag in explicit if tag in ACTION_TAG_KEYWORDS)
    return tuple(tag for tag, words in ACTION_TAG_KEYWORDS.items()
                 if any(word.lower() in name.lower() for word in words))


def personality_action_candidates(personality: str, names, metadata=None) -> list[str]:
    """返回当前角色中按性格符合度排序的动作候选。"""
    weights = PERSONALITY_TAG_WEIGHTS.get(personality, {})
    return sorted(dict.fromkeys(names), key=lambda name: -sum(
        weights.get(tag, 0) for tag in action_tags(name, metadata)
    ))


def personality_frequent_actions(personality: str, names, metadata=None) -> list[str]:
    """取符合度候选的前 40%，作为切换性格后的高频动作池。"""
    candidates = personality_action_candidates(personality, names, metadata)
    if not candidates:
        return []
    count = max(1, math.ceil(len(candidates) * PERSONALITY_ACTION_FREQUENT_RATIO))
    return candidates[:count]

# 默认显示缩放与右下角边距
# 目标显示宽度 ≈ 462px（与 DSH web 端一致）→ 462 / 640 ≈ 0.72
DEFAULT_SCALE = 0.72
CORNER_MARGIN = 24  # 距屏幕右缘的默认间距

# 可选的显示缩放档位（相对 640 宽：320px / 462px / 544px / 640px）
SCALE_STEPS = (0.5, 0.72, 0.85, 1.0)

# 系统繁忙时减少主动动作与解码频率。负载判断使用迟滞，避免频繁切换。
BUSY_IDLE_PROBABILITY = 0.82
BUSY_TURN_PROBABILITY = 0.88
BUSY_IDLE_SPEED_FACTOR = 0.70
BUSY_IDLE_PAUSE_MS = 1800
# 窗口 mask 只负责鼠标命中范围，不参与透明画面合成；每 2 帧同步一次
# 足够跟随动画，同时避免每帧重复构造 QBitmap/QRegion。
MASK_FRAME_INTERVAL = 3
BUSY_MASK_FRAME_INTERVAL = 3
LOAD_SAMPLE_MS = 5000

# ---------------------------------------------------------------- 多形象
# 当前内置形象与未来扩展形象 ID（目录名建议使用稳定 ASCII）
DEFAULT_CHARACTER = 'shenshen'
CHARACTERS = ('shenshen',)
CHARACTER_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
MANIFEST_FILENAME = 'manifest.json'
# videos 下的分类子目录
DIR_IDLE = 'idle'
DIR_TURN = 'turn'
DIR_IDLE_TURN = 'idle_turn'  # 兼容旧结构：待机+转向合并目录
DIR_MOVE = 'move'
DIR_CLICK = 'click'
DIR_DRAG = 'drag'
DIR_RANDOM = 'random'


# ---------------------------------------------------------------- 动画映射
# 内置动作以实际素材目录为事实来源。这样新增原作动作时不必再手工维护
# 一份容易漏项的 90+ 行文件名清单；值保留相对 videos/ 的分类路径。
_DEFAULT_VIDEO_ROOT = (
    Path(__file__).resolve().parent.parent
    / 'assets' / 'characters' / DEFAULT_CHARACTER / 'videos'
)
ANIM_FILES: dict[str, str] = {
    path.stem: path.relative_to(_DEFAULT_VIDEO_ROOT).as_posix()
    for path in sorted(_DEFAULT_VIDEO_ROOT.rglob('*.webm'))
}

# 兼容旧字段名：webm 文件名映射
WEBM_FILES: dict[str, str] = ANIM_FILES

# 动画分组（语义与 client.js 一致）
IDLE = '待机呼吸休闲'
TURN = '东张西望'
MOVES = ['螃蟹走路', '原地漂浮踏步', '原地左转奔跑']
CLICKS = [
    '点击回应-开心跃动',
    '点击回应-害羞惊讶',
    '点击回应-傲娇生气',
    '点击回应-元气挥手',
    '点击回应-挠痒咯咯笑',
]
DRAG = '被鼠标拖拽悬空反馈'
ACTS = [n for n in ANIM_FILES if n not in (IDLE, TURN, DRAG, *MOVES, *CLICKS)]

# 不在导入阶段锁死动作数量。默认形象当前是 91 段，但后续新增动作或
# 外部角色不应因为 catalog import 失败；当前素材完整性由测试/打包验收负责。


def assets_dir() -> Path:
    """兼容旧调用：默认形象 shenshen 的 webm 素材目录。"""
    return webm_dir()


def characters_dir() -> Path:
    """内置多形象根目录（项目根/assets/characters）。"""
    return Path(__file__).resolve().parent.parent / 'assets' / 'characters'


def character_video_dir(character_id: str) -> Path:
    """内置某个形象的 webm 目录：assets/characters/<id>/videos。"""
    return characters_dir() / character_id / 'videos'


def characters_gif_dir() -> Path:
    """内置 GIF 多形象根目录（项目根/assets/characters_gif）。"""
    return Path(__file__).resolve().parent.parent / 'assets' / 'characters_gif'


def character_gif_video_dir(character_id: str) -> Path:
    """内置某个形象的 GIF 目录：assets/characters_gif/<id>/videos。"""
    return characters_gif_dir() / character_id / 'videos'


def is_valid_character_id(character_id: str) -> bool:
    return isinstance(character_id, str) and bool(CHARACTER_ID_RE.fullmatch(character_id))


def external_character_dirs() -> list[Path]:
    """外部可扩展形象根目录（不存在时返回空列表，不报错）。

    顺序：
    1. exe 同目录 / 当前工作目录下的 characters/
    2. 用户数据目录下的 dsh-pet-standalone/characters/
    """
    dirs: list[Path] = []
    if getattr(sys, 'frozen', False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path.cwd()
    dirs.append(base / 'characters')

    if sys.platform == 'win32':
        data_root = Path(os.environ.get('APPDATA', Path.home())) / 'dsh-pet-standalone'
    elif sys.platform == 'darwin':
        data_root = Path.home() / 'Library' / 'Application Support' / 'dsh-pet-standalone'
    else:
        data_root = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'dsh-pet-standalone'
    dirs.append(data_root / 'characters')
    return dirs


def resolve_character_video_dir(character_id: str) -> Path:
    """按 外部 > 内置(webm) > 内置(gif) 返回形象视频目录；都不存在时回退 webm 路径，不报错。"""
    if not is_valid_character_id(character_id):
        character_id = DEFAULT_CHARACTER
    for root in external_character_dirs():
        candidate = root / character_id / 'videos'
        if candidate.is_dir() and (
            any(candidate.rglob('*.webm')) or any(candidate.rglob('*.gif'))
        ):
            return candidate
    webm_dir_path = character_video_dir(character_id)
    if webm_dir_path.is_dir() and any(webm_dir_path.rglob('*.webm')):
        return webm_dir_path
    gif_dir_path = character_gif_video_dir(character_id)
    if gif_dir_path.is_dir() and any(gif_dir_path.rglob('*.gif')):
        return gif_dir_path
    return webm_dir_path


def list_available_characters() -> list[str]:
    """返回可切换角色列表：内置角色 + 外部目录中额外检测到的角色。

    外部目录不存在时静默跳过，不会报错。
    """
    ids: list[str] = list(CHARACTERS)
    seen = set(ids)
    for root in external_character_dirs():
        if not root.is_dir():
            continue
        try:
            entries = sorted(root.iterdir())
        except OSError:
            continue
        for child in entries:
            video_dir = child / 'videos'
            if child.is_dir() and video_dir.is_dir() and (
                any(video_dir.rglob('*.webm')) or any(video_dir.rglob('*.gif'))
            ):
                cid = child.name
                if is_valid_character_id(cid) and cid not in seen:
                    seen.add(cid)
                    ids.append(cid)
    return ids


def webm_dir() -> Path:
    """默认形象 shenshen 的 webm 素材目录（兼容旧调用）。"""
    return character_video_dir(DEFAULT_CHARACTER)


def legacy_assets_dir() -> Path:
    """兼容旧名称：默认形象 webm 素材目录。"""
    return webm_dir()


def load_character_manifest(character_id: str, asset_dir: Path | str | None = None) -> dict | None:
    """读取角色目录下的 manifest.json（可选）。

    查找位置（按优先级）：
    1. <角色目录>/videos/manifest.json
    2. <角色目录>/manifest.json

    不存在或解析失败时返回 None，不影响运行。
    """
    if asset_dir is not None:
        video_dir = Path(asset_dir)
    else:
        video_dir = resolve_character_video_dir(character_id)
    candidates = [
        video_dir / MANIFEST_FILENAME,
        video_dir.parent / MANIFEST_FILENAME,
    ]
    for path in candidates:
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
                if isinstance(data, dict):
                    return data
            except Exception:
                return None
    return None


def _manifest_name(value, names: set[str]) -> str | None:
    """把 manifest 中的文件名/动画名解析为实际存在的动画名。"""
    if not isinstance(value, str):
        return None
    stem = Path(value).stem
    if stem in names:
        return stem
    if value in names:
        return value
    return None


def _manifest_names(values, names: set[str]) -> list[str]:
    if not isinstance(values, list):
        values = [values]
    result: list[str] = []
    for v in values:
        name = _manifest_name(v, names)
        if name is not None and name not in result:
            result.append(name)
    return result


def _keyword_match(name: str, keywords) -> bool:
    low = name.lower()
    return any(k.lower() in low for k in keywords)


def build_categories(names, manifest: dict | None = None, folder_map: dict | None = None, folder_files: dict | None = None) -> dict:
    """根据某个形象实际拥有的动画名，动态计算分类。

    分类优先级：
    1. 如果提供 folder_map（来自 videos/ 下的子目录），优先按子目录分类；
    2. 如果角色目录存在 manifest.json，则按 manifest 指定分类（可补充/覆盖）；
    3. 否则按内置已知名称 + 文件名关键词自动识别；
    4. 未进入核心分类的动画自动归入“随机动作池”。

    推荐的 videos 目录结构：
        videos/
        ├── idle/     # 待机（可多个）
        ├── turn/     # 转向（可多个）
        ├── move/     # 移动
        ├── click/    # 点击回应
        ├── drag/     # 拖拽（可选）
        └── random/   # 随机动作
    """
    ordered_names = list(dict.fromkeys(names))
    names = set(ordered_names)
    if not ordered_names:
        return {
            'idle': None, 'turn': None,
            'idles': [], 'turns': [],
            'moves': [], 'clicks': [], 'drag': None, 'acts': [],
        }

    idles: list[str] = []
    turns: list[str] = []
    moves: list[str] = []
    clicks: list[str] = []
    drag = None

    if folder_files is not None:
        by_folder: dict[str, list[str]] = {k: list(v) for k, v in folder_files.items()}
    elif folder_map:
        by_folder: dict[str, list[str]] = {}
        for name in ordered_names:
            by_folder.setdefault(folder_map.get(name, ''), []).append(name)
    else:
        by_folder = {}

    if folder_files is not None or folder_map:
        idles = list(by_folder.get(DIR_IDLE, []))
        turns = list(by_folder.get(DIR_TURN, []))
        legacy_idle_turn = by_folder.get(DIR_IDLE_TURN, [])

        if not idles and legacy_idle_turn:
            idle_candidates = [
                n for n in legacy_idle_turn
                if n == IDLE or _keyword_match(n, ['待机', 'idle', '呼吸'])
            ]
            idles = idle_candidates or (legacy_idle_turn[:1] if legacy_idle_turn else [])

        if not turns and legacy_idle_turn:
            turn_candidates = [
                n for n in legacy_idle_turn
                if n == TURN or _keyword_match(n, ['转向', '转身', '东张西望', 'turn', '回头', '转'])
            ]
            turns = turn_candidates
            if not turns and idles and len(legacy_idle_turn) > 1:
                turns = [n for n in legacy_idle_turn if n != idles[0]][:1]

        moves = list(by_folder.get(DIR_MOVE, []))
        clicks = list(by_folder.get(DIR_CLICK, []))
        drag_names = by_folder.get(DIR_DRAG, [])
        if drag_names:
            drag = drag_names[0]

    # manifest 补充/覆盖
    if manifest:
        if not idles:
            m = _manifest_name(manifest.get('idle'), names)
            if m:
                idles = [m]
        if not turns:
            m = _manifest_name(manifest.get('turn'), names)
            if m:
                turns = [m]
        if not moves:
            moves = _manifest_names(manifest.get('moves', []), names)
        if not clicks:
            clicks = _manifest_names(manifest.get('clicks', []), names)
        if drag is None:
            drag = _manifest_name(manifest.get('drag'), names)

    # 关键词兜底
    if not idles:
        m = IDLE if IDLE in names else next(
            (n for n in ordered_names if _keyword_match(n, ['待机', 'idle', '呼吸'])), None
        )
        if m:
            idles = [m]
    if not turns:
        m = TURN if TURN in names else next(
            (n for n in ordered_names if _keyword_match(n, ['转向', '转身', '东张西望', 'turn', '回头', '转'])), None
        )
        if m:
            turns = [m]
    if drag is None:
        drag = DRAG if DRAG in names else next(
            (n for n in ordered_names if _keyword_match(n, ['拖拽', '拖', '悬空', 'drag', '抓'])), None
        )
    if not moves:
        moves = [n for n in MOVES if n in names]
        if not moves:
            moves = [n for n in ordered_names if _keyword_match(n, ['走', '跑', '移动', 'move', 'walk', 'run', '踏步', '奔跑'])]
    if not clicks:
        clicks = [n for n in CLICKS if n in names]
        if not clicks:
            clicks = [n for n in ordered_names if _keyword_match(n, ['点击', '回应', 'click', 'response'])]

    # 如果没有明确 idle，安全回退到第一个动画，避免启动崩溃
    if not idles:
        first = ordered_names[0] if ordered_names else None
        if first:
            idles = [first]

    core = set(idles) | set(turns) | set(moves) | set(clicks)
    if drag:
        core.add(drag)

    # 平铺目录（folder == ''）只是兼容旧素材结构，不应把所有动画
    # 当成“随机动作”。只有真正存在子目录时，才按目录分类处理。
    has_folder_layout = folder_files is not None and any(by_folder)
    if has_folder_layout:
        # 子目录模式下，random/ 和未知目录的内容都进入随机动作池；
        # 允许同一文件同时出现在多个分类中（例如测试时复制同一视频到多个文件夹）
        acts = []
        known = {DIR_IDLE, DIR_TURN, DIR_MOVE, DIR_CLICK, DIR_DRAG}
        for folder, ns in by_folder.items():
            # folder == '' 是旧版平铺素材的重复入口，不应覆盖结构化分类。
            if folder == DIR_RANDOM or (folder and folder not in known):
                acts.extend(ns)
        seen_acts = set()
        unique_acts = []
        for n in acts:
            if n not in seen_acts:
                seen_acts.add(n)
                unique_acts.append(n)
        acts = unique_acts
    else:
        acts = [n for n in ordered_names if n not in core]
    return {
        'idle': idles[0] if idles else None,
        'turn': turns[0] if turns else None,
        'idles': idles,
        'turns': turns,
        'moves': moves,
        'clicks': clicks,
        'drag': drag,
        'acts': acts,
    }


def resolve_asset_path(name: str, filename: str, base_dir: Path | None = None) -> Path:
    """解析 webm 素材路径；不存在时返回预期路径以便上层报错。"""
    base_dir = Path(base_dir) if base_dir is not None else webm_dir()
    path = base_dir / WEBM_FILES.get(name, filename)
    return path
