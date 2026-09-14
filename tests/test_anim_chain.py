# -*- coding: utf-8 -*-
"""动画链决策的纯逻辑测试（不需要 QApplication / 窗口）。"""

import random

import pytest

from pet import anim_chain, catalog


def test_category_edges_are_cumulative_probabilities():
    for key, profile in catalog.PERSONALITY_PRESETS.items():
        idle_edge, turn_edge, acts_edge = anim_chain.category_edges(
            profile, no_move=False)
        assert idle_edge == pytest.approx(profile['idle'])
        assert turn_edge == pytest.approx(profile['idle'] + profile['turn'])
        assert acts_edge == pytest.approx(
            profile['idle'] + profile['turn'] + profile['acts'])
        if key != 'random':
            total = profile['idle'] + profile['turn'] + profile['acts'] + profile['move']
            assert total == pytest.approx(1.0)


def test_no_move_folds_move_probability_into_actions():
    profile = catalog.PERSONALITY_PRESETS['lively']
    with_move = anim_chain.category_edges(profile, no_move=False)
    without_move = anim_chain.category_edges(profile, no_move=True)
    assert without_move[2] == pytest.approx(with_move[2] + profile['move'])
    assert without_move[2] == pytest.approx(1.0)


@pytest.mark.parametrize('profile_name', sorted(catalog.PERSONALITY_PRESETS))
def test_roll_boundaries_map_to_expected_categories(profile_name):
    """按累计阈值切出的每个区间取中点，验证落在正确分类。

    边界用中点而不是端点：判定是严格小于，端点本身的浮点误差
    会让测试变成在测 IEEE754 而不是在测逻辑。
    """
    profile = catalog.PERSONALITY_PRESETS[profile_name]
    idle_edge, turn_edge, acts_edge = anim_chain.category_edges(profile, no_move=False)
    bands = (
        (0.0, idle_edge, anim_chain.CATEGORY_IDLE),
        (idle_edge, turn_edge, anim_chain.CATEGORY_TURN),
        (turn_edge, acts_edge, anim_chain.CATEGORY_ACTS),
        (acts_edge, 1.0, anim_chain.CATEGORY_MOVE),
    )
    for low, high, expected in bands:
        if high - low <= 1e-12:
            continue                      # 该预设下这个区间宽度为 0
        roll = (low + high) / 2
        assert anim_chain.category_for_roll(
            roll, profile, no_move=False) == expected
    # random.random() 的取值范围是 [0, 1)，最大值必然落在最后一段
    assert anim_chain.category_for_roll(1.0 - 1e-12, profile, no_move=False) in {
        anim_chain.CATEGORY_ACTS, anim_chain.CATEGORY_MOVE
    }


def test_busy_category_requires_available_pools():
    assert anim_chain.busy_category_for_roll(0.1, has_idles=True, has_turns=True) \
        == anim_chain.CATEGORY_IDLE
    # 没有待机池时不能落在待机
    assert anim_chain.busy_category_for_roll(0.1, has_idles=False, has_turns=True) \
        == anim_chain.CATEGORY_TURN
    assert anim_chain.busy_category_for_roll(0.1, has_idles=False, has_turns=False) \
        == anim_chain.CATEGORY_ACTS
    assert anim_chain.busy_category_for_roll(0.99, has_idles=True, has_turns=True) \
        == anim_chain.CATEGORY_ACTS


def test_pick_excludes_current_then_falls_back_to_whole_pool():
    rng = random.Random(7)
    assert anim_chain.pick(['a'], exclude='a', rng=rng) == 'a'
    assert anim_chain.pick([], rng=rng) is None


def test_pick_never_returns_failed_entries():
    rng = random.Random(11)
    for _ in range(50):
        assert anim_chain.pick(['a', 'b', 'c'], failed={'a', 'b'}, rng=rng) == 'c'


def test_pick_available_follows_fallback_order():
    rng = random.Random(3)
    pools = [['i1'], ['t1'], ['a1']]
    assert anim_chain.pick_available([], pools, rng=rng) == 'i1'
    assert anim_chain.pick_available(['x'], pools, rng=rng) == 'x'
    # 目标池整体是失败动作时继续往下找
    assert anim_chain.pick_available(
        ['bad'], [['ok']], failed={'bad'}, rng=rng
    ) == 'ok'
    assert anim_chain.pick_available([], [], rng=rng) is None


def test_personality_random_mode_ignores_focus_and_exclude():
    rng = random.Random(5)
    picked = anim_chain.pick_personality_action(
        ['a', 'b'], ['a'], personality='random', focus=0.0,
        exclude='a', rng=rng,
    )
    assert picked in {'a', 'b'}


def test_personality_focus_roll_selects_preferred_pool():
    # focus=1.0 时必然走 preferred 池
    rng = random.Random(13)
    for _ in range(20):
        picked = anim_chain.pick_personality_action(
            ['a', 'b', 'c'], ['b'], personality='lively', focus=1.0, rng=rng,
        )
        assert picked == 'b'
    # focus=0.0 时只从全量池里选
    rng = random.Random(13)
    seen = {
        anim_chain.pick_personality_action(
            ['a', 'b', 'c'], ['b'], personality='lively', focus=0.0, rng=rng,
        )
        for _ in range(60)
    }
    assert seen == {'a', 'b', 'c'}


def test_personality_prefers_actions_outside_recent_window():
    rng = random.Random(17)
    for _ in range(20):
        picked = anim_chain.pick_personality_action(
            ['a', 'b'], ['a', 'b'], personality='gentle', focus=0.0,
            recent=['a', 'a', 'a'], rng=rng,
        )
        assert picked == 'b'   # 'a' 被最近窗口排除


def test_personality_falls_back_when_recent_covers_everything():
    rng = random.Random(19)
    picked = anim_chain.pick_personality_action(
        ['a'], [], personality='gentle', focus=0.0, recent=['a'], rng=rng,
    )
    assert picked == 'a'


def test_personality_without_actions_uses_fallback_pools():
    rng = random.Random(23)
    assert anim_chain.pick_personality_action(
        [], [], personality='gentle', focus=0.5,
        fallback_pools=[['idle1']], rng=rng,
    ) == 'idle1'
    assert anim_chain.pick_personality_action(
        [], [], personality='gentle', focus=0.5, rng=rng,
    ) is None


def test_remember_keeps_three_item_sliding_window():
    recent = []
    for name in 'abcd':
        recent = anim_chain.remember(recent, name)
    assert recent == ['b', 'c', 'd']


def test_greeting_delay_stays_inside_preset_bounds():
    rng = random.Random(29)
    for profile in catalog.PERSONALITY_PRESETS.values():
        delay = anim_chain.greeting_delay_ms(profile, rng)
        assert int(profile['greeting_min_ms']) <= delay <= int(profile['greeting_max_ms'])


def test_decisions_are_reproducible_for_a_fixed_seed():
    """同一随机种子必须给出同一串选择——这是跨重构对比行为的前提。"""
    def sequence():
        rng = random.Random(20260911)
        out = []
        for _ in range(30):
            out.append(anim_chain.category_for_roll(
                rng.random(), catalog.PERSONALITY_PRESETS['lively'], no_move=False))
            out.append(anim_chain.pick_personality_action(
                ['a', 'b', 'c'], ['b'], personality='lively', focus=0.72, rng=rng))
        return out

    assert sequence() == sequence()
