from pet.config import Config


def test_dynamic_island_defaults_are_lightweight_and_enabled(tmp_path):
    config = Config(tmp_path)
    island = config.get('dynamic_island')

    assert island['enabled'] is True
    assert island['info_mode'] == 'time'
    assert island['style'] == 'dark'
    assert island['x'] is None
    assert island['y'] is None


def test_dynamic_island_config_is_sanitized(tmp_path):
    config = Config(tmp_path)
    config.data['dynamic_island'] = {
        'enabled': 'off',
        'show_icon': 0,
        'show_name': 0,
        'show_info': 0,
        'show_status': 0,
        'info_mode': 'unknown',
        'style': 'unknown',
        'custom_text': 'x' * 100,
        'x': 'not-a-number',
    }
    config._normalize()
    island = config.get('dynamic_island')

    assert island['enabled'] is False
    assert island['show_info'] is True
    assert island['info_mode'] == 'time'
    assert island['style'] == 'dark'
    assert len(island['custom_text']) == 80
    assert island['x'] is None
