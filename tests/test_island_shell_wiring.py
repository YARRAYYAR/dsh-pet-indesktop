"""dsr · pet must never recreate the removed capsule from legacy settings."""
from PySide6.QtWidgets import QApplication
from pet.app import AppShell
from pet.config import Config


def test_legacy_enabled_island_stays_absent(tmp_path, qapp):
    shell = AppShell(qapp, Config(tmp_path), enable_chat=False)
    shell.config.set("dynamic_island", {"enabled": True, "collision_enabled": True})
    shell._sync_dynamic_island()
    assert shell.island is None
    assert shell.island_collision is None
    assert not any(widget.objectName() == "dynamic-island"
                   for widget in QApplication.topLevelWidgets())


def test_repeated_sync_never_allocates_island(tmp_path, qapp):
    shell = AppShell(qapp, Config(tmp_path), enable_chat=False)
    for enabled in (False, True, False, True):
        shell.config.set("dynamic_island", {"enabled": enabled})
        shell._sync_dynamic_island()
        assert shell.island is None
        assert shell.island_collision is None
