# -*- coding: utf-8 -*-
"""收藏夹/播放列表数据层的纯单元测试（不需要窗口）。"""

import pytest

from pet.action_sets import MODE_LOOP, MODE_OFF, MODE_RANDOM, ActionSets


class FakeConfig:
    """最小配置替身：记录写入次数，便于验证持久化时机。"""

    def __init__(self, data=None):
        self.data = dict(data or {})
        self.saves = 0

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def save(self):
        self.saves += 1


NAMES = ['待机', '转向', '走路', '吃饭']


def make(**data):
    return FakeConfig(data)


def test_loads_and_drops_names_missing_from_the_character():
    config = make(favorites=['待机', '不存在', 42, '转向'],
                  playlist=['走路', '也不存在'])
    sets = ActionSets(config, NAMES)
    assert sets.favorites == ['待机', '转向']
    assert sets.playlist == ['走路']


def test_invalid_mode_falls_back_to_off():
    sets = ActionSets(make(playlist_mode='bogus'), NAMES)
    assert sets.mode == MODE_OFF


@pytest.mark.parametrize('mode', [MODE_OFF, MODE_LOOP, MODE_RANDOM])
def test_valid_modes_are_preserved(mode):
    sets = ActionSets(make(playlist=['待机'], playlist_mode=mode), NAMES)
    assert sets.mode == mode


def test_toggle_favorite_adds_then_removes_and_persists():
    config = make()
    sets = ActionSets(config, NAMES)
    sets.toggle_favorite('待机')
    assert sets.favorites == ['待机']
    assert config.data['favorites'] == ['待机']
    assert config.saves == 1
    sets.toggle_favorite('待机')
    assert sets.favorites == []
    assert config.saves == 2


def test_apply_filters_unknown_names():
    sets = ActionSets(make(), NAMES)
    assert sets.apply('favorites', ['走路', '幽灵动作'], NAMES) == ['走路']
    assert sets.playlist == []


def test_clearing_the_playlist_turns_the_mode_off():
    sets = ActionSets(make(playlist=['待机', '转向'], playlist_mode=MODE_LOOP), NAMES)
    sets.apply('playlist', [], NAMES)
    assert sets.playlist == []
    assert sets.mode == MODE_OFF
    assert sets._config.data['playlist_mode'] == MODE_OFF


def test_apply_resets_the_loop_cursor():
    sets = ActionSets(make(playlist=['待机', '转向']), NAMES)
    sets.index = 5
    sets.apply('playlist', ['走路'], NAMES)
    assert sets.index == -1


def test_playlist_from_favorites_copies_and_resets_cursor():
    sets = ActionSets(make(favorites=['待机', '转向']), NAMES)
    sets.index = 3
    assert sets.playlist_from_favorites() == ['待机', '转向']
    assert sets.index == -1


def test_set_mode_rejects_unknown_mode_and_empty_playlist():
    sets = ActionSets(make(), NAMES)
    assert sets.set_mode('bogus') is False
    assert sets.set_mode(MODE_LOOP) is False       # 空列表不允许开启
    assert sets.mode == MODE_OFF
    sets.apply('playlist', ['待机'], NAMES)
    assert sets.set_mode(MODE_LOOP) is True
    assert sets.mode == MODE_LOOP


def test_loop_mode_advances_in_order_and_wraps():
    playlist = ['a', 'b', 'c']
    sets = ActionSets(make(playlist=playlist, playlist_mode=MODE_LOOP), playlist)
    picked = [sets.next_name(current='x', picker=lambda *_: 'picker') for _ in range(5)]
    assert picked == ['a', 'b', 'c', 'a', 'b']     # 循环模式不使用 picker


def test_random_mode_delegates_to_the_picker():
    playlist = ['a', 'b']
    sets = ActionSets(make(playlist=playlist, playlist_mode=MODE_RANDOM), playlist)
    calls = []

    def picker(pool, current):
        calls.append((list(pool), current))
        return 'b'

    assert sets.next_name(current='a', picker=picker) == 'b'
    assert calls == [(['a', 'b'], 'a')]
    assert sets.index == -1                        # 随机模式不动游标


def test_next_name_is_none_for_an_empty_playlist():
    sets = ActionSets(make(playlist_mode=MODE_LOOP), NAMES)
    assert sets.next_name(current='a', picker=lambda *_: 'x') is None


def test_mark_current_moves_the_cursor_only_for_known_names():
    playlist = ['a', 'b']
    sets = ActionSets(make(playlist=playlist), playlist)
    sets.mark_current('b')
    assert sets.index == 1
    sets.index = 0
    sets.mark_current('不在列表里')
    assert sets.index == 0


def test_reload_keeps_only_what_the_new_character_has():
    config = make(favorites=['待机'], playlist=['走路'], playlist_mode=MODE_LOOP)
    sets = ActionSets(config, NAMES)
    sets.reload(['待机'])
    assert sets.favorites == ['待机']
    assert sets.playlist == []
    assert sets.index == -1
    # 播放模式本身保留（是否可用由 set_mode/上层决定）
    assert sets.mode == MODE_LOOP
