# 动作库与播放列表

当前成品：`dist/DSH-Pet-Control-Panel-macOS-arm64.zip`。新版控制面板分为桌宠、动作库、互动、声音、设置五页。保留原版弹簧参数的来回回弹及 0.18 秒轻量回弹音效。首页可切换回弹；音效跟随总声音开关和音量，微小抖动不触发。

对话框开关：右键菜单或菜单栏中切换“显示对话框（气泡）”，也可在设置中调整。关闭立即停止气泡显示和相关动画计时器，取消预览覆盖，并保存到本地配置。

入口：桌宠右键 / 状态栏菜单 → 控制面板 → 动作库。右键的旧高级功能收纳在“更多控制”中。

- 名称搜索：左栏支持中文、英文片段，英文忽略大小写，可筛选已有收藏。选中后“加入列表”，双击也可添加；重复添加自动去重。
- 排序：右栏始终显示完整播放列表，搜索时也能拖动排序，或使用“上移 / 下移 / 按名称”。“移除”仅移出播放列表，不删除视频。
- 保存 / 取消：保存应用列表和顺序；取消放弃本次草稿。大小、音量和开关即时预览，取消恢复，包括暂停和隐藏状态。
- 播放：在“动作管理 → 播放列表”选择循环或随机。顺序仅对循环播放生效；导入不会修改当前播放模式。
- 导入：载入 JSON 后先检查草稿，保存后应用。重复名称去重；当前角色缺少的动作会提示并跳过。全部不匹配、格式错误、未知版本、超过 1 MB 的文件不会覆盖原列表。
- 导出：导出右侧完整列表顺序。文件只包含动作名称，不含视频、设置或个人路径。另一台机器仍需有对应角色素材。
- 设置中的动作搜索覆盖当前角色的全部类别；搜索无结果时预览不触发播放。

## JSON 格式

```json
{
  "format": "dsh-pet-playlist",
  "version": 1,
  "actions": ["动作名称甲", "动作名称乙"]
}
```

## 本地开发与构建

运行：使用项目 `.venv`，安装 `requirements.txt`，执行 `python tools/build_macos.py --prepare-only` 准备 macOS Qt 插件，再运行 `run-mac.command`。

验证：

```sh
QT_PLUGIN_PATH="$PWD/qt-plugins" QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
QT_PLUGIN_PATH="$PWD/qt-plugins" QT_QPA_PLATFORM=cocoa .venv/bin/python tools/verify_action_library.py
```

构建 Apple Silicon 应用需要 PyInstaller：

```sh
.venv/bin/python tools/build_macos.py --archive-name DSH-Pet-Control-Panel-macOS-arm64.zip
```

构建脚本拒绝覆盖已存在的同名 ZIP。应用在临时目录完成本地签名和归档，产物复制至 `dist`。原 WebM 素材直接打包，不重编码。
