"""Remove retired controls from the original settings composition.

The existing sections, tabs, row widgets and QSS remain the presentation source.
Hidden rows retain a Qt owner so dependency callbacks and original-mode saves
can still use the same control attributes.
"""
from PySide6.QtWidgets import QWidget


_RETIRED_ROWS = frozenset({
    'harness_autostart', 'music_sing', 'music_lyric', 'music_lyric_lead',
    'click_balance', 'click_self_talk_speak', 'click_self_talk_precache',
    'spawn_inherit_size', 'spawn_scale', 'clear_spawned_pets',
})
_DOMAINS = frozenset({'常规', '桌宠', '互动', '菜单', '连接'})


def visible_rows(dialog, rows):
    if not dialog.companion_mode:
        return rows
    visible = []
    for row in rows:
        key = row.objectName().removeprefix('settingRow_')
        if key in _RETIRED_ROWS or key.startswith('egg_'):
            if not hasattr(dialog, '_retired_settings'):
                dialog._retired_settings = QWidget(dialog)
                dialog._retired_settings.hide()
            row.setParent(dialog._retired_settings)
        else:
            visible.append(row)
    return visible


def slim_domains(domains) -> None:
    for label in list(domains):
        if label not in _DOMAINS:
            content = domains.pop(label)
            if content is not None:
                content.hide()
