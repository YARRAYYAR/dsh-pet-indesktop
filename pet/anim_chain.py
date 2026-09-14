# -*- coding: utf-8 -*-
"""动画链决策：把"下一段播什么"从窗口里分离出来。

这里只放决策规则，不做任何 Qt 调用、不持有窗口引用，因此可以脱离
QWidget 单测。随机源由调用方显式传入，保证随机数调用顺序与原实现
逐个对应——顺序一旦改变就等于换了行为。

分类概率与性格预设仍然是 `catalog` 的事实来源，本模块只负责"阈值 → 类别"
与"池 → 具体动画名"这两步映射。
"""

from __future__ import annotations

import random
from typing import Iterable, Mapping, Sequence

from . import catalog

CATEGORY_IDLE = 'idle'
CATEGORY_TURN = 'turn'
CATEGORY_ACTS = 'acts'
CATEGORY_MOVE = 'move'

RECENT_ACTION_MEMORY = 3


def pick(
    pool: Sequence[str],
    *,
    exclude: str | None = None,
    failed: Iterable[str] = (),
    rng: random.Random | None = None,
) -> str | None:
    """从池中挑一个。

    优先排除"当前动作"；若因此空了，则退回整池（仍然排除已判定失败的动作，
    避免坏素材造成切换风暴）。
    """
    failed = failed if isinstance(failed, (set, frozenset)) else set(failed)
    entries = [n for n in pool if n != exclude and n not in failed]
    if not entries:
        entries = [n for n in pool if n not in failed]
    if not entries:
        return None
    return (rng or random).choice(entries)


def pick_available(
    pool: Sequence[str],
    fallback_pools: Iterable[Sequence[str]] = (),
    *,
    exclude: str | None = None,
    failed: Iterable[str] = (),
    rng: random.Random | None = None,
) -> str | None:
    """从目标池选择；角色缺少该类动作时按顺序回退到其它已有动作。"""
    picked = pick(pool, exclude=exclude, failed=failed, rng=rng)
    if picked is not None:
        return picked
    for fallback in fallback_pools:
        picked = pick(fallback, exclude=exclude, failed=failed, rng=rng)
        if picked is not None:
            return picked
    return None


def pick_personality_action(
    acts: Sequence[str],
    frequent: Sequence[str],
    *,
    personality: str,
    focus: float,
    exclude: str | None = None,
    recent: Sequence[str] = (),
    failed: Iterable[str] = (),
    fallback_pools: Iterable[Sequence[str]] = (),
    rng: random.Random | None = None,
) -> str | None:
    """按性格提高高匹配动作的出现频率。

    调用方负责把返回的结果记入"最近播放"；本函数不产生副作用，
    因此同一个随机种子下可以反复复现同一串选择。
    """
    rng = rng or random
    if personality == 'random' and acts:
        return pick(acts, failed=failed, rng=rng)
    if not acts:
        return pick_available(acts, fallback_pools, exclude=exclude,
                              failed=failed, rng=rng)
    available = [n for n in acts if n != exclude and n not in recent]
    if not available:
        available = [n for n in acts if n != exclude] or list(acts)
    preferred = [n for n in frequent if n in available]
    if frequent and rng.random() < focus:
        pool = preferred or available
    else:
        pool = available
    return pick(pool, failed=failed, rng=rng)


def remember(recent: Sequence[str], name: str) -> list[str]:
    """把动作记入最近播放窗口（与重构前的 3 项滑动窗口一致）。"""
    return list((list(recent) + [name])[-RECENT_ACTION_MEMORY:])


def category_edges(profile: Mapping[str, float], *,
                   no_move: bool) -> tuple[float, float, float]:
    """返回 (待机上界, 转向上界, 动作上界)；no_move 时把移动概率并入动作。"""
    idle_edge = float(profile['idle'])
    turn_edge = idle_edge + float(profile['turn'])
    acts_edge = turn_edge + float(profile['acts'])
    if no_move:
        acts_edge += float(profile['move'])
    return idle_edge, turn_edge, acts_edge


def category_for_roll(roll: float, profile: Mapping[str, float], *,
                      no_move: bool) -> str:
    """按累计概率阈值把一次随机数映射成分类。"""
    idle_edge, turn_edge, acts_edge = category_edges(profile, no_move=no_move)
    if roll < idle_edge:
        return CATEGORY_IDLE
    if roll < turn_edge:
        return CATEGORY_TURN
    if roll < acts_edge:
        return CATEGORY_ACTS
    return CATEGORY_MOVE


def busy_category_for_roll(roll: float, *, has_idles: bool,
                           has_turns: bool) -> str:
    """省资源模式：大幅抬高中待机概率，转向次之，其余落到随机动作。"""
    if roll < catalog.BUSY_IDLE_PROBABILITY and has_idles:
        return CATEGORY_IDLE
    if roll < catalog.BUSY_TURN_PROBABILITY and has_turns:
        return CATEGORY_TURN
    return CATEGORY_ACTS


def greeting_delay_ms(profile: Mapping[str, float],
                      rng: random.Random | None = None) -> int:
    """主动问候的下次触发间隔。"""
    low = int(profile['greeting_min_ms'])
    high = int(profile['greeting_max_ms'])
    return (rng or random).randint(low, high)
