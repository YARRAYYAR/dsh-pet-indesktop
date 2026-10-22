"""Exercise companion menu editing through real Qt widgets and commands."""
from copy import deepcopy

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from pet.context_menus.registry import COMPANION_ACTION_IDS, MENU_ACTIONS
from pet.settings_menu_layout_editor import MenuLayoutEditor


@pytest.fixture
def menu_layout(monkeypatch):
    layout = {
        "schema_version": 1,
        "layout_id": "user",
        "nodes": [
            {"type": "action", "id": "chat", "alias": "旧聊天", "icon": "chat", "visible": False},
            {"type": "submenu", "id": "user.mixed", "label": "我的操作", "visible": True, "children": [
                {"type": "action", "id": "no_move", "visible": True},
                {"type": "action", "id": "music", "alias": "旧音乐", "icon": "play", "visible": False},
                {"type": "action", "id": "on_top", "visible": True},
            ]},
            {"type": "submenu", "id": "user.retired", "label": "旧功能", "alias": "原分组", "visible": False, "children": [
                {"type": "action", "id": "look_screen", "visible": True},
                {"type": "action", "id": "todo_panel", "visible": False},
            ]},
            {"type": "action", "id": "modern_settings", "visible": True},
            {"type": "action", "id": "quit", "visible": True},
        ],
    }
    # Keep this workflow's inputs fixed when later releases add default actions.
    monkeypatch.setattr("pet.menu_layout.load_default_menu_layout", lambda: deepcopy(layout))
    return layout


@pytest.fixture
def editors():
    app = QApplication.instance() or QApplication([])
    created = []

    def create(layout, **kwargs):
        editor = MenuLayoutEditor(deepcopy(layout), **kwargs)
        editor.resize(900, 650)
        editor.show()
        app.processEvents()
        created.append(editor)
        return editor

    yield app, create
    for editor in created:
        editor.close()
        editor.deleteLater()
    app.processEvents()


def _items(tree, *, visible_only=True):
    def visit(parent):
        for index in range(parent.childCount()):
            item = parent.child(index)
            if visible_only and item.isHidden():
                continue
            yield item
            yield from visit(item)
    return list(visit(tree.invisibleRootItem()))


def _ids(tree):
    return [
        (item.data(0, Qt.ItemDataRole.UserRole) or {}).get("id")
        for item in _items(tree)
    ]


def _node(layout, node_id):
    def find(nodes):
        for node in nodes:
            if node["id"] == node_id:
                return node
            found = find(node.get("children", []))
            if found is not None:
                return found
        return None
    return find(layout["nodes"])


def test_default_view_still_exposes_unavailable_actions(menu_layout, editors):
    app, create = editors
    editor = create(menu_layout, available_actions=COMPANION_ACTION_IDS)

    assert "music" in _ids(editor.tree)
    assert editor.item_for_action("music").text(1) == "此平台不可用"
    assert editor.value() == menu_layout
    assert len(editor.toolbar_buttons) == 5


def test_companion_view_and_preview_hide_retired_nodes(menu_layout, editors):
    app, create = editors
    editor = create(menu_layout, visible_actions=COMPANION_ACTION_IDS)

    assert _ids(editor.tree) == ["user.mixed", "no_move", "on_top", "modern_settings", "quit"]
    assert [item.text(0) for item in _items(editor.preview)] == [
        "我的操作", MENU_ACTIONS.label("no_move"), MENU_ACTIONS.label("on_top"),
        MENU_ACTIONS.label("modern_settings"), MENU_ACTIONS.label("quit"),
    ]
    assert all(item.text(1) != "此平台不可用" for item in _items(editor.tree))
    assert editor.value() == menu_layout
    assert len(editor.toolbar_buttons) == 5


def test_companion_commands_preserve_hidden_configuration(menu_layout, editors):
    app, create = editors
    editor = create(menu_layout, visible_actions=COMPANION_ACTION_IDS)
    item = editor.item_for_action("on_top")
    editor.tree.setCurrentItem(item)

    # Use the actual sorting command: a hidden retired sibling must not consume
    # the click or leave the visible order unchanged.
    editor.move_up_action.trigger()
    app.processEvents()
    assert _ids(editor.tree)[:3] == ["user.mixed", "on_top", "no_move"]
    editor.set_item_alias("on_top", "保持置顶")
    item.setCheckState(0, Qt.CheckState.Unchecked)
    app.processEvents()

    draft = editor.value()
    for node_id in ("chat", "music", "user.retired"):
        assert _node(draft, node_id) == _node(menu_layout, node_id)
    assert _node(draft, "on_top")["alias"] == "保持置顶"
    assert _node(draft, "on_top")["visible"] is False

    # A retired-only group must not leak through the destination picker.
    editor._rebuild_move_menu()
    assert [action.data() for action in editor.move_menu.actions()] == ["__root__", "user.mixed"]
    editor.move_menu.actions()[0].trigger()
    app.processEvents()
    assert _node(editor.value(), "user.mixed")["children"] == [
        _node(menu_layout, "no_move"), _node(menu_layout, "music"),
    ]
    assert _node(editor.value(), "user.retired") == _node(menu_layout, "user.retired")

    editor.set_layout(editor.value())
    editor.set_enabled_actions({"modern_settings", "quit"})
    app.processEvents()
    assert "music" not in _ids(editor.tree)
    assert "user.retired" not in _ids(editor.tree)
    assert _node(editor.value(), "music") == _node(menu_layout, "music")


def test_empty_visible_actions_hides_all_actions_without_dropping_them(menu_layout, editors):
    app, create = editors
    editor = create(menu_layout, visible_actions=frozenset())

    assert _ids(editor.tree) == []
    assert _items(editor.preview) == []
    assert editor.value() == menu_layout
