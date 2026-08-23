# -*- coding: utf-8 -*-
"""目录/常量完整性测试（无需 GUI）。"""

from pet import catalog
from pet.interaction import classify_tap_burst, cursor_facing, edge_contacts
from pet.hotkeys import GlobalHotkeys
from pet.performance import LoadGovernor
from pet.sound import DuckScream


def test_catalog_integrity():
    assert len(catalog.ANIM_FILES) == 91
    assert len(catalog.ACTS) == 80
    assert len(catalog.CLICKS) == 5
    assert len(catalog.MOVES) == 3
    assert catalog.IDLE in catalog.ANIM_FILES
    assert catalog.TURN in catalog.ANIM_FILES
    assert catalog.DRAG in catalog.ANIM_FILES
    assert all(n in catalog.ANIM_FILES for n in catalog.CLICKS + catalog.MOVES)
    assert catalog.FRAME_MS > 0
    assert (catalog.DECODE_MAX_W, catalog.DECODE_MAX_H) == (1280, 720)
    assert catalog.decode_size_for_scale(0.72) == (922, 520)
    assert catalog.decode_size_for_scale(1.0) == (1280, 720)
    assert catalog.BUSY_MASK_FRAME_INTERVAL == 2


def test_load_governor_hysteresis():
    governor = LoadGovernor()
    assert governor.observe(0.80) is False
    assert governor.observe(0.80) is True
    assert governor.constrained is True
    assert governor.observe(0.40) is False
    assert governor.observe(0.40) is False
    assert governor.observe(0.40) is True
    assert governor.constrained is False


def test_interaction_gesture_classification():
    assert classify_tap_burst(1) == "single"
    assert classify_tap_burst(2) == "double"
    assert classify_tap_burst(5) == "rapid"
    assert cursor_facing((100, 100), (250, 110), 200) == "right"
    assert cursor_facing((100, 100), (-50, 110), 200) == "left"
    assert cursor_facing((100, 100), (105, 100), 200) is None
    assert cursor_facing((100, 100), (400, 100), 200) is None


def test_interaction_edge_contacts():
    assert edge_contacts((0, 20, 100, 100), (0, 0, 800, 600), 18) == {"left"}
    assert edge_contacts((700, 500, 100, 100), (0, 0, 800, 600), 18) == {
        "right",
        "bottom",
    }


def test_duck_sound_generates_small_wav(tmp_path):
    sound = DuckScream(tmp_path)
    sound._ensure_wave()
    assert sound.path.is_file()
    assert sound.path.stat().st_size > 1_000
    sound.close()


def test_personality_presets_and_global_hotkeys_are_stable():
    assert set(catalog.PERSONALITY_PRESETS) == {'quiet', 'lively', 'mischievous'}
    for profile in catalog.PERSONALITY_PRESETS.values():
        assert abs(
            profile['idle'] + profile['turn'] + profile['acts'] + profile['move']
            - 1.0
        ) < 1e-6
    assert [spec.action for spec in GlobalHotkeys.DEFAULTS] == [
        'toggle_visible',
        'toggle_pause',
        'random_action',
        'toggle_mouse_through',
        'duck_sound',
    ]
