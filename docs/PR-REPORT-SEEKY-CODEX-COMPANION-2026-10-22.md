# seeky· Codex companion：修改文件说明、性能分析、实机运行记录

> **基线**：`7a5fed77`（seeky.8 优化基线）  
> **分支**：`codex/seeky-pet`　**日期**：2026-10-22  
> **范围**：Codex companion 连接、原版 UI 收口、生命周期优化、测试与证据文档

文档入口：[索引](INDEX.md#pr-报告存档)。本报告记录本轮交付和当前验证边界；高负载失败证据保留在 `docs/evidence/codex-companion/final-checks/loaded-1.*`。

## 一、核心特性

入口使用原版设置 UI 的侧栏、卡片、QSS、间距和动效，只收起意义不明或本轮不需要的入口。可见域为常规、桌宠、互动、菜单、连接；旧配置仍保留，不会因隐藏控件被重写。

「连接 → Codex」同时支持两条边界清晰的路径：已有 Codex Desktop 会话只读观察并提供打开入口；桌宠显式创建的任务通过官方 `codex app-server --listen stdio://` 独立连接，支持新建、发送、回答问题、审批、停止，以及累计 Token、最近一次响应和额度窗口展示。桌宠任务不借用 Desktop 会话的 Token 统计。

窗口切换、正常关闭和候选构造失败共用幂等资源释放；素材库内部集中预热申请、去重和代次取消；DSH 离线时停止事件轮询，恢复在线立即补读新增事件后再恢复计时器。

**红线 / 不变量**：动作、分辨率、透明边缘、播放节奏、原始媒体和隐藏配置保持不变；Qt 对象、定时器和跨线程通知仍在所属线程处理；迟到结果不得回填新角色或新任务。

## 二、修改文件说明

### 实现

| 文件/目录 | 改动意图 |
|---|---|
| `pet/app.py`、`pet/window.py`、`pet/window_optional_services.py` | 接入 companion profile；统一旧窗替换、关闭和候选失败的释放；共享服务只解绑，不被旧窗误停。 |
| `pet/codex_client.py`、`pet/codex_companion.py`、`pet/codex_usage.py`、`pet/codex_link.py` | 增加 stdio app-server 客户端、任务/问答/审批/停止状态机、Desktop 只读发现及 Token/额度归一化。 |
| `pet/settings_codex.py`、`pet/settings_companion.py`、`pet/settings_legacy.py` | 复用原版控件与布局，加入 Codex 任务工作区、Token/额度卡片和必要设置，保留旧配置。 |
| `pet/__main__.py`、`pet/context_menu.py`、`pet/context_menus/modern.py`、`pet/context_menus/registry.py` | companion 启动参数、菜单入口和动作注册。 |
| `pet/modern_settings_dialog.py`、`pet/settings_interaction.py`、`pet/settings_menu_layout_editor.py` | 通过 profile 过滤退休域和菜单，不复制第二套 UI 合同。 |
| `scripts/capture_settings_pages.py` | 支持 companion 页面原生截图与布局证据。 |

### 测试与证据

| 文件/目录 | 覆盖 |
|---|---|
| `tests/test_codex_client.py`、`test_codex_companion_flow.py`、`test_codex_companion_ui.py`、`test_codex_discovery.py`、`test_codex_usage.py` | JSON-RPC 生命周期、任务交互、问题/审批、状态发现和 Token/额度缺失值语义。 |
| `tests/test_companion_menu_editor.py`、`test_companion_retired_controls.py`、`test_settings_process_isolation.py` | 菜单收口、退休控件、独立设置进程和页面导航。 |
| `tests/fixtures/` | 隔离协议 peer、临时角色和本地测试输入；不读取真实会话或密钥。 |
| `docs/evidence/codex-companion/`、`docs/evidence/dsr-pet/` | 每次原生验证的命令、环境、输入、断言、结果、退出码及失败日志。 |

## 三、实现要点

- `CodexCompanion` 由 `AppShell` 单例持有。`CodexMonitor` 只扫描本机 Desktop rollout 元数据；`CodexClient` 仅在用户新建任务或发送消息时拉起独立 app-server。请求响应绑定 session、turn、连接代次和 JSON-RPC request id，旧响应不能回填。
- companion 设置通过 `companion_mode` 过滤显示域和主动服务。音乐、报时、节日/待办、识屏闲聊及其他模型入口不在主界面装配，但原配置键仍可读写保留。
- `PetWindow.release_resources()` 幂等且兼容部分构造；角色切换先建立候选窗，成功后释放旧窗，失败时释放候选并保留旧窗。窗口自有素材、预热、缩略图、气泡和定时器与应用共享 Agent/识屏/解码服务分离。
- 预热申请集中到素材库调度器，按库、代次和动作去重。交互最后一个持有者释放时通过 GUI queued 信号恢复，不再每 50ms 轮询 GUI。
- `DshStateTracker` 离线停止 1.2 秒事件定时器，只保留 3 秒上线探测；上线边沿先消费新增事件，再恢复事件计时器，并拒绝停止期间排队的旧代次结果。

## 四、性能分析

**方法（可复现）**：

```text
./.venv/bin/python docs/evidence/codex-companion/settings-native/run_evidence.py \
  --output docs/evidence/codex-companion/settings-native/measurements-final --duration 5
```

环境：macOS 26.6.2 arm64、Apple M3、8 CPU、Python 3.13.2、PySide6/Qt 6.11.2。每种设置模式串行 3 轮，临时配置、隔离 Python home、null keyring；不读取真实任务、会话或密钥。该短测比较设置进程 presentation，不等价于长期桌宠 RSS 收益。

| 指标 | original median | companion median | 说明 |
|---|---:|---:|---|
| 稳态 RSS | 45.21 MiB | 38.55 MiB | 三轮中位数；短测差异低于长期收益判定门槛，不宣称稳定内存下降。 |
| 可见设置域 | 9 | 5 | companion 收口后减少页面及控件装配。 |
| Codex server 常驻 | 0 | 0 | 未连接/未提交任务时不拉起；由用户动作触发。 |

本轮旧窗口释放、预热去重和离线轮询属于正确性与后台唤醒治理；没有把短时 RSS 差异直接归因于这些改动。动作源帧缺口和队列丢帧在原生验收分析中均为 0，源媒体摘要保持一致。

## 五、实机运行记录

**真实 Cocoa 设置运行**：`docs/evidence/codex-companion/settings-native/visuals/` 保存 baseline `7a5fed77` 与 companion 的布局 JSON、截图和像素比较。常规/桌宠页与基线像素一致，无横向滚动、裁切或遮挡。

**真实 Codex 连接边界**：`docs/evidence/codex-companion/native-cli.json` 与 `settings-entry/` 保存 CLI 探测、独立设置进程、页面导航和协议 peer 记录。测试使用临时 Codex home 和确定性 stdio peer，没有真实账号、会话或密钥；已有 Desktop 会话只读，无法通过本项目 transport 直接回答或审批。

**失败路径**：

- `.venv/bin/python docs/evidence/codex-companion/verify_checks.py --phase loaded` 在 8 个 CPU burner 下第 1 轮退出码 1：`285 passed, 23 failed`，耗时 101.81 秒。失败集中在预热调度、离线恢复、窗口 DeferredDelete 时序和 ffmpeg 元数据探测对照组；原始日志和 JSON 保留，未修改断言绕过。
- 普通完整主套件、聚焦接线族、独立 decoder 生命周期和交互族均通过；满载失败不能被写成项目正确性通过，后续应降低外部 burn 竞争后分组复跑。

## 六、测试与验证

| 门 | 命令/证据 | 结果 |
|---|---|---|
| 静态检查 | `.venv/bin/ruff check pet tests scripts docs/evidence/codex-companion/` | 通过 |
| diff | `git diff --check` | 通过 |
| 聚焦 | `docs/evidence/codex-companion/final-checks/focused.json` | 117 passed |
| 受影响接线族 | `docs/evidence/codex-companion/final-checks/pytest-main.json` 及相关记录 | 通过 |
| 完整主套件 | `.venv/bin/python -m pytest -q --ignore=tests/test_webm_reader_lifecycle.py --ignore=tests/test_webm_clip_lifecycle.py --ignore=tests/test_webm_first_frame_lock.py --ignore=tests/test_low_priority_warm_interaction_yield.py` | 3039 passed, 21 skipped |
| 独立 decoder 生命周期 | `pytest-decoder-lifecycle.json` | 39 passed |
| 独立交互族 | `pytest-interaction-isolated.json` | 27 passed |
| 高负载三轮 | `verify_checks.py --phase loaded` | 第 1 轮失败，23 项失败证据已保存；未宣称通过 |

## 七、已知限制与后续

- 高负载三轮尚未完成；当前不能把满载时序门标记为通过。应在资源竞争较低的同机环境按预热、DSH、切换、ffmpeg 四组分别复跑，并保留失败/中断证据。
- 本轮不包含打包、安装、GitHub release 或真实在线 Codex 账号验证。Codex Desktop 现有会话的回答/审批仍需点击「打开 Codex」。
- RSS 三轮设置短测仅用于比较装配规模；长期单宠占用应使用独立生命周期验证器重新测量，不能沿用历史 MB 数字。

## 八、风险与回滚

新增配置仅使用已有 Codex 连接键和任务展示状态，不迁移或删除旧配置。回滚使用本提交的 `git revert`，保留用户配置、会话和原始媒体；不要用 reset 覆盖工作树中的其他用户修改。推送前保留本报告及 `docs/evidence/` 证据包。
