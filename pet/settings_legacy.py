"""Save settings hidden by the Codex companion profile only in the original UI.

Called after Config.reload(): skipping these writes preserves the latest on-disk
values, including unknown nested keys, without replaying hidden-control effects.
"""
from . import settings_music
from .fun_image_popup import store_fun_asset, oijingjing_image_path


def save_legacy_settings(dialog) -> None:
    dialog.config.set("spawn_inherit_size", dialog.spawn_inherit_size_check.isChecked())
    dialog.config.set("spawn_scale", float(dialog.spawn_scale_combo.currentData()))
    dialog.config.set("dynamic_island", {**dialog.config.get("dynamic_island"), "enabled": False})
    if dialog.click_balance_check is not None:
        dialog.config.set("click_show_balance", dialog.click_balance_check.isChecked())
    dialog.config.set("self_talk_speak_enabled", dialog.click_self_talk_speak_check.isChecked())
    dialog.config.set("self_talk_voice_precache_enabled",
                    dialog.self_talk_voice_precache_check.isChecked())
    dialog.config.set("music_sing_enabled", dialog.music_sing_check.isChecked())
    if getattr(dialog, "music_lyric_check", None) is not None:
        dialog.config.set("music_lyric_enabled", dialog.music_lyric_check.isChecked())
    if getattr(dialog, "agent_cost_check", None) is not None:
        dialog.config.set("agent_cost_enabled", dialog.agent_cost_check.isChecked())
    if getattr(dialog, "music_lyric_lead_spin", None) is not None:
        dialog.config.set(
            "music_lyric_lead_seconds", float(dialog.music_lyric_lead_spin.value())
        )
    # Agent 联动：自定义 thinking 文案与音效（合并写回，不覆盖 agent_link 其他开关）
    dialog.config.set("dialogue_mode", str(dialog.dialogue_mode_select.currentData() or "legacy"))
    # 统一预设：编辑区当前层 flush 后，global 层 + agents delta 分层写回
    dialog._dialogue_flush_scope()
    new_global = dialog._dialogue_scope_values("")
    agents_delta: dict[str, dict[str, list[str]]] = {}
    for scope in dialog._dialogue_scope_buffer:
        if scope == "":
            continue
        values = dialog._dialogue_scope_values(str(scope))
        if values:
            agents_delta[str(scope)] = values
    # 兼容旧扁平存储：双层仅当存在 agents delta 或原配置已是双层时启用
    current_phrases = dialog.config.get("dialogue_phrases", {})
    was_preset = isinstance(current_phrases, dict) and ("global" in current_phrases or "agents" in current_phrases)
    if agents_delta or was_preset:
        dialog.config.set("dialogue_phrases", {"global": new_global, "agents": agents_delta})
    else:
        dialog.config.set("dialogue_phrases", new_global)
    # 记住上次编辑层：下次打开设置直接回到该 Agent 专属层（未知值回落全局）
    dialog.config.set("dialogue_last_scope", str(getattr(dialog, "_dialogue_scope", "") or ""))
    agent_cfg = dict(dialog.config.get("agent_link", {}))
    # 循环检测设置页（合并写回，不覆盖 agent_link 其他字段）
    if dialog.watchdog_page is not None:
        agent_cfg = dialog.watchdog_page.apply_to_config(agent_cfg)

    # Agent 联动音效写回
    agent_cfg["sound_enabled"] = dialog.agent_sound_check.isChecked()
    agent_cfg["sound_start_enabled"] = dialog.agent_sound_start_check.isChecked()
    agent_cfg["sound_start_path"] = dialog.agent_sound_start_picker.text().strip() or "builtin:agent-start"
    agent_cfg["sound_done_enabled"] = dialog.agent_sound_done_check.isChecked()
    agent_cfg["sound_done_path"] = dialog.agent_sound_done_picker.text().strip() or "builtin:agent-done"
    agent_cfg["sound_error_enabled"] = dialog.agent_sound_error_check.isChecked()
    agent_cfg["sound_error_path"] = dialog.agent_sound_error_picker.text().strip() or "builtin:agent-error"
    agent_cfg["sound_volume"] = float(dialog.agent_sound_volume_spin.value()) / 100.0
    agent_cfg["sound_cooldown_seconds"] = float(dialog.agent_sound_cooldown_spin.value())
    # 事件汇报概率门：滑块值即通过概率（0.00–1.00，步长 0.05），逐类写回。
    report_gates = dict(agent_cfg.get("report_gates") or {})
    for gate, slider in dialog.report_gate_sliders.items():
        report_gates[gate] = round(float(slider.value()), 2)
    agent_cfg["report_gates"] = report_gates

    dialog.config.set("agent_link", agent_cfg)
    dialog.config.set("todo_reminder_enabled", dialog.todo_reminder_check.isChecked())
    dialog.config.set("todo_reminder_lead_minutes", int(dialog.todo_reminder_lead_spin.value()))
    # 语音报时设置页写回（仅写 voice_chime_* 11 键）
    if dialog.voice_chime_page is not None:
        dialog.voice_chime_page.apply_to_config()
    # 节日提醒设置页写回（仅写 festival_reminder_* / festival_custom_* 10 键）
    if dialog.festival_page is not None:
        dialog.festival_page.apply_to_config()
    dialog.config.set(
        "menu_easter_egg",
        {
            "enabled": dialog.egg_enabled_check.isChecked(),
            "title": dialog.egg_title_edit.text(),
            "hint": dialog.egg_hint_edit.text(),
            # 内置 assets 内的路径归一化回相对值，保持 portable（目录移动/自更新后仍可用）
            "avatar": store_fun_asset(dialog.egg_avatar_picker.text(), oijingjing_image_path()),
            "image_dir": store_fun_asset(dialog.egg_image_dir_picker.text(), oijingjing_image_path().parent),
        },
    )
    dialog.config.set("quick_launch_apps", dialog.quick_launch_editor.apps())
    settings_music.save_music_player_settings(dialog)
    dialog.config.set("harness_autostart", dialog.harness_autostart_check.isChecked())
