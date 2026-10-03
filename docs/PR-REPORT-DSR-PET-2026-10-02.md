# seeky· pet：内存、透明边缘与设置 UI 交付报告

> 基线：v4.2.1 纯桌宠修复提交 `1c3a59cd4a03730c86250172c118b561ab2c5d24`
> 当前分支：`codex/seeky-pet`；初版：2026-10-02；最新：2026-10-03（seeky.5）；下方保留前阶段记录
> 独立源码：`/Users/ray/Documents/New project/dsr-pet`
> 当前 App：`/Users/ray/Applications/seeky· pet.app`；桌面同名符号链接指向此 App。旧安装版及桌面入口已移除。

## 一、核心特性

- 解码队列 8 → 2 帧，生产者可中断地等待，不因队列满丢掉当前帧。
- 成功切换动作后停止被打断的旧播放器及计时器，硬停止解除缓存clip对旧队列的引用；启动失败可回退，自然圈末不重复停止。
- 两处缩略图缓存分别复用既有 ByteBudgetLru，单处预算 8 MiB，按项淘汰。
- 保留完整 RGBA、帧序、源素材、Qt 绘制隔离副本、预乘 Alpha 与 Retina 平滑缩放。
- 原生窗口覆盖区保留半透明轮廓并加 1 逻辑像素保护；碰撞锚点沿用旧边界。
- 设置固定中性黑灰；一级导航与二级动作入口、140ms 状态反馈、底部保存/退出/版本。
- 动作库静态列表，搜索/分类/当前动作/单次请求均通过实例隔离本地通道，设置进程没有播放器。
- 完全移除顶部胶囊及展开面板；旧配置 enabled=true 不会恢复界面。
- 用户原图保留，macOS 图标采用圆角、透明四角及标准外留白。
- 恢复原本地项目的头顶吸附/180°倒立，支持探出比例；倒立时不自行走离顶边。
- 连接页显示最近活跃Codex主会话工作状态、提问和本轮完成；问题保持到回复或关闭连接，按钮打开对应Codex会话。
- 表单去掉重复齿轮、二级导航用文字缩进；一级入口保留独立语义图标。

## 二、修改文件说明

| 文件 | 增删 | 改动与原因 |
|---|---|---|
| `.gitignore` | +1 / −0 | 忽略本地运行时 .venv，避免将可替换缓存环境纳入源码。 |
| `THIRD_PARTY_NOTICES` | +26 / −0（新增） | 保留Codenotch样式代码来源及MIT许可证。 |
| `assets/icon.ico` | 二进制替换 | 品牌图标的ICO派生，Mac使用ICNS。 |
| `docs/INDEX.md` | +1 / −0 | 登记交付报告。 |
| `docs/PR-REPORT-DSR-PET-2026-10-02.md` | +236 / −0（新增） | 记录实现、复用、性能及原生验收证据。 |
| `pet/__main__.py` | +3 / −12 | 源码入口固定纯桌宠，独立设置仍在导入主进程前分流。 |
| `pet/animation_thumbnail.py` | +5 / −7 | 复用 ByteBudgetLru 替代达到128项全部清空，预算8MiB。 |
| `pet/app.py` | +63 / −49 | 动作控制通道与当前动作推送、关闭清理；移除胶囊构建；纯版避免聊天存储导入；跳过已销毁提示对象。 |
| `pet/branding.py` | +26 / −0（新增） | dsr · pet品牌、实际派生版本dsr.2及保留原图的Mac圆角派生。 |
| `pet/chat/widgets.py` | +1 / −1 | 延迟提示定时器绑定接收QObject，避免窗口销毁后回调。 |
| `pet/codex_link.py` | +207 / −0（新增） | 按本地rollout增量读取最近主会话，处理工作/问题/完成与文件轮转；兼容本机custom_tool_call格式，打开官方线程链接。 |
| `pet/config.py` | +13 / −17 | 新增贴顶、探出比例和Codex开关；独立配置目录复制迁移，胶囊禁用。 |
| `pet/context_menus/icons.py` | +10 / −0 | 统一退出和链条连接矢量图标。 |
| `pet/context_menus/shared.py` | +10 / −13 | 音乐后台信号桥延长到worker完成，防宿主销毁时原生emit崩溃。 |
| `pet/decode_fanout.py` | +9 / −2 | 弱引用发布者，补实际HD源尺寸供订阅reader读帧。 |
| `pet/frame_edges.py` | +36 / −0（新增） | Qt行跨度读取、精确Alpha覆盖LUT及1逻辑像素保护边，像素不改。 |
| `pet/gui_stall_sampler.py` | +1 / −1 | 修正弱引用清理回调的错误默认对象构造，实际停止采样器。 |
| `pet/modern_settings_dialog.py` | +44 / −226 | 纯版保留可用入口；两级导航、动作库、贴顶设置与Codex页装配，保存语义保持。 |
| `pet/resources/app-icon-mac.png` | 二进制新增 | 原图派生圆角Mac图标，透明角和外留白。 |
| `pet/resources/app-icon.png` | 二进制新增 | 用户提供原图原样保留。 |
| `pet/settings_actions.py` | +144 / −0（新增） | 静态分类/搜索/播放动作列表，实时当前动作推送，隐藏取消watch。 |
| `pet/settings_brand.py` | +163 / −0（新增） | 品牌头部、固定底部按钮、一级/二级导航与页说明。 |
| `pet/settings_codex.py` | +98 / −0（新增） | 连接开关保存失败反馈、实时状态卡片；隐藏页停止轮询。 |
| `pet/settings_commands.py` | +150 / −0（新增） | 实例隔离本地命令server/client、短请求超时、事件watch与完整关闭。 |
| `pet/settings_navigation.py` | +103 / −0（新增） | Codenotch状态opacity/填充/边框移植，140ms有限动画和键盘焦点。 |
| `pet/settings_pet_controls.py` | +8 / −46 | 删除胶囊控件，增加贴顶开关和探出比例控件。 |
| `pet/settings_theme_qss.py` | +35 / −12 | 中性黑灰层次、单层导航选中高亮、圆角卡片与控件状态。 |
| `pet/settings_widgets.py` | +52 / −11 | 有限140ms开关反馈、连接导航；移除表单重复齿轮图标，保留键盘焦点。 |
| `pet/top_flip.py` | +250 / −0（新增） | 复用用户原项目TopFlipController，稳定角色体框判断吸附及倒立。 |
| `pet/webm_clip.py` | +26 / −12 | 实际HD解码尺寸；队列2帧；可中断背压保持当前帧到成功入队；保留绘制副本；硬停止不保留旧队列，自然park保持队列。 |
| `pet/window.py` | +32 / −14 | 覆盖区与碰撞边界分离、字节LRU；接动作通知、贴顶释放及服务关闭；成功切换后停旧clip，保留失败回退与自然续圈。 |
| `pet/window_optional_services.py` | +76 / −2 | 复用原控制器，统一倒立绘制/遮罩/命中旋转轴；接只读Codex状态与气泡生命周期。 |
| `pet/window_placement.py` | +14 / −0 | 用物理屏幕顶部吸附；macOS允许窗口越过顶边，保持倒立探出比例。 |
| `scripts/build_macos.sh` | +29 / −5 | 纯桌宠品牌/图标/资源及模块排除；Apple Silicon构建和本地缓存签名输出。 |
| `scripts/compare_dsr_memory.py` | +50 / −0（新增） | 交替执行三轮基线/新版，保存每轮命令、UTC时间、setup/reset、结果及退出码；失败停止。 |
| `scripts/dsr_proc_memory.c` | +13 / −0（新增） | 读取macOS proc_pid_rusage footprint与resident，不修改目标进程。 |
| `scripts/make_icon.py` | +30 / −16 | 通过同一Qt圆角函数生成PNG/ICO/ICNS，保留原图。 |
| `scripts/summarize_dsr_memory.py` | +90 / −0（新增） | 从六轮原始记录生成稳态/峰值/进程分项/短期趋势/帧交付统计，保留逐轮波动。 |
| `scripts/verify_dsr_actions.py` | +166 / −0（新增） | 通过原生主进程和实际独立设置入口，分类搜索、等待当前动作推送并录制界面；失败正确退出。 |
| `scripts/verify_dsr_features.py` | +166 / −0（新增） | 真实Cocoa主进程、本地事件文件和QLocalServer验证倒立/两种工具事件/状态/关闭清理；失败保存证据。 |
| `scripts/verify_dsr_media.py` | +71 / −0（新增） | 全106动作逐帧验证RGBA、Retina缩放、哈希、帧序和播放间隔。 |
| `scripts/verify_dsr_package.py` | +105 / −0（新增） | 只读核验24个关键模块字节码、106素材哈希、模块排除、arm64和深层严格签名。 |
| `scripts/verify_dsr_packaged_runtime.py` | +124 / −0（新增） | 用此前未使用slot启动实际安装包，核对动作目录/播放/错误/退出与已知子进程清理。 |
| `scripts/verify_dsr_runtime.py` | +256 / −0（新增） | 实际进程树footprint/RSS及可见源帧采样；构造前配置穿透，设置串行开关，采样错误正确失败。 |
| `scripts/verify_dsr_switch_cleanup.py` | +82 / −0（新增） | 真实QLocalServer播放请求，检查旧timer/reader/队列缓冲释放；等待实际异步资源回收。 |
| `tests/test_animation_thumbnail_cache.py` | +1 / −1 | 检查LRU项数与字节预算，适配缓存接口。 |
| `tests/test_architecture.py` | +7 / −2 | 按新增接线净行数校准文件预算，新算法移出宿主类；旧clip释放为2行接线，行为断言未改。 |
| `tests/test_chat_subsystem.py` | +3 / −2 | 新配置目录迁移并验证旧配置文件未覆盖。 |
| `tests/test_clip_restart_paths.py` | +3 / −0 | 测试屏幕替身补QScreen.geometry，以覆盖物理屏幕顶边；原行为断言保留。 |
| `tests/test_config_schema.py` | +3 / −0 | 校准三个新增持久设置键的精确schema断言。 |
| `tests/test_decode_fanout_integration.py` | +7 / −2 | 共享HD源尺寸、源帧序与清理事件同步。 |
| `tests/test_desktop_pet_features.py` | +10 / −51 | 移除胶囊设置控件旧契约，断言入口缺失。 |
| `tests/test_dsr_codex_and_ceiling.py` | +137 / −0（新增） | 公共配置、原生Qt贴顶、真实本地事件文件、保存失败及轮转回归。 |
| `tests/test_dsr_rendering.py` | +73 / −0（新增） | 新旧解码完整帧序/像素、覆盖边缘、字节缓存、背压中断回归。 |
| `tests/test_dsr_settings.py` | +166 / −0（新增） | 原生设置/命令服务、动作搜索播放、无播放器、品牌及两级导航断言。 |
| `tests/test_file_eater.py` | +2 / −0 | 动作状态Signal测试替身支持既有文件吃入路径。 |
| `tests/test_harness_launcher.py` | +2 / −0 | 隔离本机全局Node/dsh路径，保持fallback用例封闭。 |
| `tests/test_island_chat.py` | +9 / −138 | 已移除胶囊的AppShell不再构建聊天岛；旧算法测试仍保留。 |
| `tests/test_island_shell_wiring.py` | +15 / −157 | legacy enabled=true不能创建胶囊或碰撞协调器。 |
| `tests/test_menu_layout.py` | +6 / −6 | 删除桌面组件域契约，AI索引用语义查找，保留功能分组。 |
| `tests/test_music_player_cache.py` | +5 / −3 | 后台bridge通过真实宿主销毁验证，无竞态原生崩溃。 |
| `tests/test_pet_interaction_locks.py` | +3 / −0 | 测试屏幕替身补QScreen.geometry，以覆盖物理屏幕顶边；原行为断言保留。 |
| `tests/test_proactive.py` | +2 / −2 | 派生状态文件从Config目录读取，避免硬编码旧品牌路径。 |
| `tests/test_requested_regressions.py` | +7 / −7 | 固定深色设置与中性颜色、菜单外观不再改变设置主题。 |
| `tests/test_settings_and_resources.py` | +1 / −3 | 移除胶囊设置控件期望；保留资源与保存回归。 |
| `tests/test_settings_interaction_tabs.py` | +1 / −1 | 导航清单移除桌面组件域，其余动作标签语义保留。 |
| `tests/test_settings_process_isolation.py` | +1 / −1 | 适配新增页装配方法的import隔离测试桩。 |
| `tests/test_single_process_shared.py` | +0 / −37 | 删除已移除胶囊多实例断言，保留共享玩家全套用例。 |
| `tests/test_webm_clip_broker_feed.py` | +5 / −3 | 共享源尺寸与背压契约的测试替身，验证回退不变。 |
| `tests/test_webm_clip_loop.py` | +3 / −0 | 测试屏幕替身补QScreen.geometry，以覆盖物理屏幕顶边；原行为断言保留。 |
| `tests/test_windows_node_env.py` | +1 / −0 | 隔离本机全局路径，验证Windows运行时路径本身。 |
| `assets/characters/shenshen/videos/` | 106项二进制替换 | 采用用户已有1280×720运行代理；完整逐文件目录见modified-assets.json，原文件未改写。 |
| `docs/evidence/dsr-pet/` | 验收产物 | 完整文件清单见artifact-manifest.json，包含原始数据、命令、失败记录、图像和录像；不是产品运行资源。 |

## 三、实现要点

### 复用与取舍

- 复用既有 ByteBudgetLru、首帧缓存、非活动帧清理、共享解码、动作调度和退出入口。
- 参考 [Codenotch](https://github.com/vinzdg/codenotch) 的 `SettingsView.swift` 中 SettingsPalette / SidebarRow；参考提交 `6e8b0f828741233240d5fb10f7d52cf8eaf6efe4`。SwiftUI 状态样式移植到 Qt，许可证保留于 THIRD_PARTY_NOTICES。
- QImage.copy 的所有权隔离保持；未启用存在绘制重入风险的零复制。
- 透明像素通过预乘变为透明黑；Qt 行跨度真实读取。HD 素材存在精确 RGBA(0,0,0,1) 背景，仅覆盖区排除此样本，显示像素不改。
- 原生覆盖区与 collision bounds 分离；统一腐蚀、提高整角色 Alpha 阈值和整图模糊未纳入。
- QLocalServer 使用按配置绝对路径哈希命名、用户权限、QLockFile 与残留监听探测。动作 watch 使用事件推送，隐藏页面取消；短请求超时 2s；退出关闭全部 socket。
- 原生动作切换先出现旧clip仍运行的红结果；修复后实际QLocalServer切换确认旧clip及timer停止、新clip运行。进一步原生检查发现硬停止后缓存clip仍持有7,372,800字节旧队列；新队列隔离后等待实际reader异步退役，缓冲为0、旧队列释放。自然结束曾出现重复stop，被原测试发现；保留失败日志，改为仅停止被打断的clip后全量通过。
- 音乐查找 worker 的 Qt 信号桥独立保留到完成，解决窗口销毁时后台 emit 的原生崩溃。 GUI 卡顿采样器弱引用清理修正同步用于比较基线。

## 四、性能分析

### 三轮同机结果

单位MiB；稳态为三轮阶段中位数的中位数，峰值为三轮1Hz采样最大值。

| 场景 | 基线稳态 | 新版稳态 | 变化 | 基线采样峰值 | 新版采样峰值 |
|---|---:|---:|---:|---:|---:|
| 单宠 | 204.2 | 187.8 | -8.0% | 226.2 | 214.1 |
| 三宠 | 306.8 | 315.8 | +2.9% | 540.9 | 1121.3 |
| 连续切换 | 581.5 | 198.6 | -65.9% | 705.8 | 278.6 |
| 设置开关8次 | 354.8 | 349.4 | -1.5% | 1038.5 | 388.1 |
| 关闭设置后单宠 | 251.3 | 224.3 | -10.8% | 268.1 | 256.2 |

| 场景 | 基线三轮稳态 | 新版三轮稳态 | 新版阶段末−初趋势（三轮） |
|---|---|---|---|
| 单宠 | 215.1 / 195.5 / 204.2 | 193.1 / 187.8 / 169.7 | -8.9 / 2.2 / -17.8 |
| 三宠 | 306.8 / 323.2 / 299.9 | 317.9 / 272.4 / 315.8 | -127.0 / -124.3 / -206.6 |
| 连续切换 | 581.5 / 585.6 / 574.8 | 198.6 / 221.4 / 190.8 | -54.6 / -30.2 / -6.4 |
| 设置开关8次 | 354.8 / 377.6 / 349.6 | 349.4 / 334.7 / 365.9 | 5.9 / -14.2 / 8.6 |
| 关闭设置后单宠 | 254.1 / 251.3 / 248.2 | 224.3 / 214.8 / 227.9 | -9.8 / 0.7 / -17.4 |

队列满丢帧：基线三轮1 /1 /0；新版0 /0 /0。新版所有阶段实际可见源帧的向前跳号均为0。单宠交付约23.79–23.80fps，两版相同24fps目标/Qt定时器间隔；三宠新版约23.51–23.81fps、基线23.65–23.82fps，强制切换新版22.96–23.15fps、基线23.08–23.17fps，包含动作启动/切换等待，不能把队列丢帧为0解释为绝无调度抖动。

连续切换主要收益来自停止旧播放器和释放其队列，而非降低素材质量。设置关闭后的短阶段未观察到持续增长，不能替代数小时泄漏测试。设置进程自身新增UI成本仍存在，分项原始数据同时列出main/settings/ffmpeg。

**多宠未达到降低占用的目标。** 三宠稳态中位数+2.9%，逐轮波动较大；新版启动采样峰值更高，最高样本中main约266.6MiB、9个FFmpeg约854.7MiB，基线峰值样本为3个FFmpeg。不能宣称所有场景均节省内存；并发预热/短期解码重叠与采样相位仍需更高频率跟踪。保留原预热策略及共享解码环，本轮没有通过削减动作、降帧或关闭预热去压低这项结果。

所有六轮exit 0、errors=[]。完整进程分项、FPS、增长信号、时长及原始采样见memory-comparison.json与*-1/2/3.json、*.run.json。

### 方法与环境

macOS 26.6.2 arm64；Python 3.13.2；PySide6 6.11.2；Pillow 12.3；imageio-ffmpeg 0.6；同机同运行时、同 106 段 1280×720 / 24fps WebM。基线为 `/Users/ray/Library/Caches/dsr-pet-baseline-1c3a59c`：官方提交补 HD 实际解码尺寸兼容与采样器清理前提；共享尺寸通过弱引用读取，避免兼容补丁增加publisher所有权。补丁逐行留在 baseline-compatibility.patch.gz（gzip 原始补丁）。

每版重复 3 次，交替执行基线/新版。阶段：预热10秒；单宠20秒；三宠共享解码20秒；返回单宠连续切换20秒；通过实际`_exec_settings`入口，独立设置进程串行开关8次（每次显示2.4秒，退出后再打开下一次）；返回单宠20秒。每阶段时钟在资源创建/回收完成后才启动，总时长随启动耗时变化，转换阶段单列。两版都关闭省电降帧、语音、自动移动、贴顶效果、Codex联动和旧胶囊；测试窗口在构造前通过Config开启输入穿透，避免桌面操作改变负载和运行期改windowFlags造成的hide/show。只统计当前可见播放器发出的帧事件，排除非活动clip。后台每秒统计主进程、设置子进程与 FFmpeg 进程树。

```sh
clang scripts/dsr_proc_memory.c -o /tmp/dsr-proc-memory
.venv/bin/python scripts/compare_dsr_memory.py --baseline /Users/ray/Library/Caches/dsr-pet-baseline-1c3a59c --probe /tmp/dsr-proc-memory
.venv/bin/python scripts/summarize_dsr_memory.py
```

macOS physical footprint 为主要指标，RSS 同时记录；每阶段前 5 秒后样本的中位数作为稳态，峰值包括完整阶段，为1Hz采样观察到的最大值，不保证捕捉亚秒瞬时峰值。原始采样和每轮结果在 evidence/dsr-pet/*-1/2/3.json，汇总见 memory-comparison.json。早期受桌面点击退出或设置并发开启影响的测量均排除；设置现在严格串行，窗口输入穿透。旧的三组窗口flag改动/非活动帧统计受扰测量另存`.scratch/dsr-pet/evidence/pre-switch-cleanup-measurements`；仅停止clip、但未解除队列引用的三组结果另存`pre-queue-release-measurements`。后者验证了切换占用下降、关闭设置后仍偏高，因此继续修复；两批均不作为最终表依据。临时目录丢失导致的一次启动失败也单独存档；重建基线放在持久Cache目录。报告缺失、采样线程出错或任一设置进程异常退出均返回失败。每轮命令、开始UTC时间、setup/reset、退出码另存*-1/2/3.run.json。

### 路径成本与触发频率

- 缩小队列的理论满队列数据容量减少：6 × 1280 × 720 × 4 = 21.09 MiB / reader；不是整机内存下降承诺。
- 缓存单处有界 8 MiB，两处独立缓存总预算可达 16 MiB；原播放器、首帧、缩放图像与共享环继续计入进程总量。
- 新增覆盖区每个实际重建帧执行；12 背景/变换组合，每组合 20 次，实测 0.86–1.65ms / 调用；同帧快路径不执行。它增加编译 LUT 和 QRegion 合并成本，未新增常驻线程、网络请求或磁盘写入。
- IPC 在打开动作页、播放、退出时发消息；当前动作改变才推送，不做周期轮询。增加本地 socket/锁文件，目录/文件读写沿用现有配置保存；无新增公网请求。
- 悬停/切换动画只在 140ms 动画期间刷新，结束停止；动作库只有文字和矢量图标，不解码视频缩略动画。
- 图标圆角仅在构建时生成，不在播放帧路径运行。
- 贴顶复用原控制器，直接180°姿态，稳定后计时器停止；不创建线程/网络/文件服务。
- Codex主进程启用后每秒增量读本地事件文件，每5秒枚举UTC今天/昨天会话。单次记录缓冲上限1MiB，增量最多256KiB；不创建模型、网络请求或线程。设置连接页可见时每1.5秒请求本地状态，隐藏后停止。
- Codex路径成本见native-features.json：100次稳态轮询、一次真实本地会话初始发现；它是单个短采样，未把它当成持续工作负载下的平均CPU百分比。

## 五、实机运行记录

- 原生 Cocoa / DPR=2：设置默认 1000×680、最小 720×500，动作106、分类点击回应、搜索挥手、播放后当前动作推送与选择一致、底部退出可见、旧胶囊入口缺失；见 native-ui.json / native-ui.mp4 与 settings-*.png。
- 打包 App 使用真实 QLocalServer：读取106动作，播放请求返回成功；不存在的动作返回“动作不存在，请刷新动作库”；退出请求成功，主进程和 FFmpeg 结束；见 packaged-ipc.json。
- 安装版dsr.2：搜索Codex显示1/1并跳到连接页，开启后真实会话显示“Codex · 正在工作 / New project”；搜索贴顶吸附显示1/1，开关已开、探出50%；保存关闭结束独立设置进程。public codex_status和106动作目录再次核验。见packaged-features.json。最终队列和事件格式修复后的安装版再次通过搜索/状态显示及public codex_status，见installed-final-ui.json。
- 最新安装包24个关键模块字节码与当前源码一致，106个HD文件哈希一致、arm64和深层严格签名通过；见package-verification.json。实际安装包按未使用slot启动，播放/非法动作/退出完成，已知子进程无残留，见packaged-ipc.json。
- 本机点击“打开Codex”未出现失败提示；工具禁止读取com.openai.codex界面，目标聊天的可见UI未核验。联动依赖本地rollout事件格式（非稳定公共状态API）；覆盖当前task_started/function_call/custom_tool_call/问题/完成，并保留兼容性限制。采用[官方线程深链接](https://learn.chatgpt.com/docs/reference/commands) `codex://threads/<id>`。
- 原生贴顶：实际PetWindow上180°、水平位置保留、稳定后计时器关闭，向下移后回正0°；截图ceiling-inverted/restored.png。CUA直接拖动无边框角色未改变位置，因此OS鼠标拖放尚未核验。最新安装版更换坐标映射、Raise并临时关闭光标隐藏穿透后仍未驱动窗口移动，已恢复该偏好，见native-mouse-unverified.json。
- Codex提问/完成消息通过实际本地rollout文件驱动；提问置顶、带打开按钮、回复后完成消息有限8秒；关闭连接取消气泡并停止轮询。消息内容为明确标注的验收fixture，真实用户会话另验证“working”状态。
- Qt 原生图像在白、黑、灰、蓝背景，以静止 .85、镜像1.0、旋转20°/.65 比较旧/新覆盖区；透明角保持不在覆盖区。见 edge-comparison.png / edge-checks.json。此对比是原生 Qt 合成，不能充当 OS 点击穿透的全部验收。
- 106动作25,423帧：源文件 SHA-256、实际 reader 源帧序、完整 RGBA 以及1088×612 Retina预乘缩放哈希全一致；所有Qt播放定时器间隔相同。容器/帧数推算的内部 fps 最大差 .03259，内部 duration 最大差 .01s，未宣称估算字段逐字相同。见 media-comparison.json。
- 全帧校验两次耗时161.6s /1028.8s；冷/热元数据缓存触发既有 FFmpeg readrate 路径不同，因此这些校验墙钟时间不作为解码性能比较。

## 六、测试与验证

| 检查 | 结果 |
|---|---|
| 全量 pytest（最终串行复跑） | 2914 passed /21 skipped /261 warnings，154.88s；exit 0 |
| 原生贴顶/Codex/关闭连接流程 | PASS；native-features.json errors=[] / exit 0 |
| 所有改动Python文件 ruff | All checks passed |
| macOS构建与编码/Bridge冒烟 | PASS |
| 原生106动作、静态列表播放/当前推送 | PASS，native-ui.json errors=[] |
| 全部106 WebM /25,423帧像素与Retina哈希 | PASS |
| 本机 App adhoc 深层签名 | PASS |

测试/构建/静态日志保留在 evidence/dsr-pet/ 下。并行负载下曾有1项旧聊天滚动测试失败；单项复跑通过，最终全套串行复跑全部通过，失败日志也保留。最后单层高亮和卡片样式属于呈现调整，通过原生新截图/录像再次验收。

### 放大后像素感：2026-10-02 追加调查

用户确认“放大后整体都明显”。在不使用任何窗口遮罩的相同首帧上，比较当前 720p Qt 平滑放大、720p 预乘 Lanczos、既有1440p母版。大尺寸1440p母版线条更清楚，说明此处包含源分辨率与重采样限制，不能仅靠窗口覆盖算法解决。见 [upscale-comparison.png](evidence/dsr-pet/upscale-comparison.png) / upscale-comparison.json。

单帧1280×720→2560×1440：Qt约7.94ms；Pillow预乘Lanczos约45.91ms（含转回RGBA），单样本初步测量，不能当全面基准。Lanczos实时路径超出24fps预算，未纳入 App。既有母版来自用户本地 Real-ESRGAN 动漫超分链，按文件名可匹配91/106动作，缺15个事件动作，时序尚未全部校验；未直接替换运行素材。

相关 GitHub 方案：

| 项目 | 用途 | 本项目判断 |
|---|---|---|
| [libvips](https://github.com/libvips/libvips/wiki/HOWTO----Image-shrinking) | 预乘Alpha、高质量重采样 | 借鉴正确合成次序，已有预乘实现；不直接引入新运行依赖 |
| [PyMatting](https://github.com/pymatting/pymatting) | trimap引导Alpha及前景估计 | 素材残边的离线候选，需要已知背景/前景，不能从透明PNG凭空恢复被删除细节 |
| [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) | 动漫视频超分、Alpha输入 | 本地已有AnimeVideo-v3母版，优先复用；仍需全动作时序/细节/内存验收 |
| [RobustVideoMatting](https://github.com/PeterL1n/RobustVideoMatting) | 时序一致真人视频抠图 | 官方明确针对真人，对动漫需要实测，不直接接实时主进程 |

### 原生流程复跑

```sh
QT_QPA_PLATFORM=cocoa PYTHONPATH=. .venv/bin/python scripts/verify_dsr_features.py
QT_QPA_PLATFORM=cocoa PYTHONPATH=. .venv/bin/python scripts/verify_dsr_actions.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
QT_QPA_PLATFORM=cocoa PYTHONPATH=. .venv/bin/python scripts/verify_dsr_switch_cleanup.py
PYTHON_BIN=.venv/bin/python scripts/build_macos.sh --variants webm
.venv/bin/python scripts/verify_dsr_package.py --app "/Users/ray/Applications/dsr · pet.app"
PYTHONPATH=. .venv/bin/python scripts/verify_dsr_packaged_runtime.py --app "/Users/ray/Applications/dsr · pet.app"
```

执行目录为独立源码目录；两个原生流程每次新建临时Config，Codex流程使用临时CODEX_HOME，不覆盖用户配置。输入为同106HD素材和明确本地事件fixture；断言、实际结果、exit保存在native-features.json/native-ui.json。原动作录像脚本固定时刻检查曾错过动作，且失败退出码为0；保留native-ui-timing-failed.json/log，重写为等待实际状态并正确失败退出的新流程后通过。关闭Codex气泡残留的红/绿记录保留codex-disable-red.json/log和最终native-features.json。实际本机custom_tool_call初次未识别工作状态，原生红/绿记录为codex-custom-tool-red.json/log与最终native-features.json；真实本地会话已显示working。旧clip释放红/绿记录为switch-cleanup-red.json/log与switch-cleanup.json；自然圈末重复stop的中间失败记录tests-natural-stop-failed.log。队列保留红记录switch-queue-red.json/log；仅解除引用后300ms读线程尚未结束的过早检查记录switch-queue-detached-failed.json/log（JSON按工具返回记录恢复，注明来源），最终改为等待实际资源释放，switch-cleanup.json/log已确认旧缓冲为0。打包验收脚本初次错误使用仅设置入口支持的--instance，导致无法连到目标实例；未改产品CLI，改用已有--slot后通过，失败记录packaged-instance-argument-failed.json/log。

## 七、已知限制与后续

三宠启动采样峰值及稳态没有得到改善，原始结果如实保留；并发预热需要单独继续验证。

本版保留现有HD素材，未承诺放大超过源分辨率后完全无像素感。1440p大尺寸资源路径需后续核对所有动作后接入，并重新测解码与图像驻留成本。现有素材残边逐帧离线修复同样需有原背景/前景证据。

Retina合成、旋转与透明角已自动检查；真实OS背景点击穿透、连续手动拖拽和碰撞仍需覆盖更广桌面场景。共享扇出环保持已有落后订阅者策略；队列满不丢帧的新保证适用于本地/订阅reader入队，不代表任意停滞订阅者无限期保存全部历史帧。

## 八、风险与回滚

原项目、旧配置和原图均保留；独立配置目录为 `~/Library/Application Support/dsr-pet`，首次迁移只复制旧配置。移走新App即可回到原项目；源码可切回基线，但无需覆盖HD素材。上一交付App另存`~/Library/Caches/dsr-pet-build/previous-delivery-dsr1-20261003.app`；本次旧clip修复前的dsr.2另存`previous-delivery-dsr2-before-cleanup-20261003.app`，队列引用修复前另存`previous-delivery-dsr2-before-queue-20261003.app`。没有推送仓库或创建PR。App采用本地adhoc签名，供本机运行；未申请Developer ID或公证。


## 九、2026-10-03：seeky· pet 最终交付

此前章节是 dsr 阶段的历史记录，本节描述本次实际安装版。品牌改为 **seeky· pet**，UI 版本 **4.2.1 · seeky.3**，CFBundleVersion **4.2.1.3**。新 Seeky artwork 原字节保留；ICO、Mac PNG 与 ICNS 均已更新，1024px 图标采用 896px 圆角板和 64px 外留白。配置目录、实例通道与 bundle identifier 保持兼容。

### 修改文件说明

本表行数是当前源码相对稳定基线的累计增删，不是仅本轮的差分；上一节表格是上一阶段快照。额外新增证据、截图与日志由 artifact-manifest.json 逐项登记。

| 文件 | 增删 | 改动与原因 |
|---|---|---|
| `.github/workflows/build-macos.yml` | +10 / −3 | 纯桌宠 CI 产物改用 Seeky 名称，其他上游变体保持原名；本轮只验证本机构建。 |
| `.gitignore` | +3 / −0 | 保留品牌原图归档，忽略可替换本地环境。 |
| `README.md` | +31 / −0 | 新增 Seeky 功能、构建入口、配置保留和平台限制；上游文档及归属保留。 |
| `assets/brand/archive/deepseek-source.png` | 二进制新增 | 保留之前使用的用户原图，换标可追溯。 |
| `assets/icon.ico` | 二进制替换 | 由新 Seeky artwork 生成，供已有图标入口使用。 |
| `pet/resources/app-icon.png` | 二进制新增 | 新用户 artwork 原字节保留，原图 SHA256 验证。 |
| `pet/resources/app-icon-mac.png` | 二进制新增 | Mac 圆角板、透明四角和外留白派生。 |
| `pet/branding.py` | +26 / −0（新增） | 统一 seeky· pet / 4.2.1 · seeky.3；保持配置目录与 bundle id，避免偏好丢失。 |
| `pet/__main__.py` | +3 / −12 | 品牌文案与纯桌宠入口；设置进程继续提前分流。 |
| `pet/config.py` | +17 / −17 | 新增嵌套 codex_task_appearance 默认、白名单与归一化，保留已有功能配置。 |
| `pet/task_bubble_style.py` | +37 / −0（新增） | 六位十六进制校验、80–160% 边界、预设、WCAG 文字对比与损坏配置恢复。 |
| `pet/task_bubble.py` | +159 / −0（新增） | 任务消息复用原气泡位置与生命周期；全文显示、同比例文字/按钮、8 秒完成收起；旧预览按钮立即隐藏。 |
| `pet/settings_task_appearance.py` | +180 / −0（新增） | 设置行单一拥有配色/大小；实渲染预览、原生选色、结束编辑保存、失败反馈及回滚；控件保留共享最小高度。 |
| `pet/settings_codex.py` | +101 / −0（新增） | 连接页装配任务框外观；保持本地状态与单一开关保存语义。 |
| `pet/settings_commands.py` | +150 / −0（新增） | 断连提示使用 Seeky 名称；按实例控制通道不变。 |
| `pet/ceiling_geometry.py` | +70 / −0（新增） | 缓存读取 AppKit 安全区和左右辅助顶区，识别物理刘海并换算 Qt 逻辑坐标。 |
| `pet/top_flip.py` | +267 / −0（新增） | 根据身体中心区分刘海/普通顶边，藏入约一半；关闭倒立恢复完整身体。 |
| `pet/window.py` | +35 / −19 | 气泡工厂与独立绘制/覆盖函数接线；保持行数预算及原渲染测试兼容面。 |
| `pet/window_optional_services.py` | +107 / −2 | 工作/提问/完成使用同一任务消息队列，配置即时刷新；绘制和覆盖区域一致裁切。 |
| `pet/window_placement.py` | +13 / −0 | 补偿 Cocoa Tool 窗口的菜单栏位置限制，虚拟位置、绘制偏移和点击区域一致。 |
| `pet/modern_settings_dialog.py` | +44 / −226 | 倒立设置文案描述藏入顶部、半身比例与刘海/菜单栏差别。 |
| `scripts/build_macos.sh` | +29 / −5 | 应用名、实际派生版本和图标接入打包；本机构建签名通过。 |
| `scripts/verify_dsr_package.py` | +118 / −0（新增） | 关键模块字节码、新图标/ICNS、arm64、106 素材与严格深层签名验证。 |
| `scripts/verify_dsr_packaged_runtime.py` | +124 / −0（新增） | 使用新的实际可执行名，保留真实控制通道目录/播放/非法动作/退出验收。 |
| `scripts/verify_seeky_task_frame.py` | +195 / −0（新增） | 原生设置→文件保存→Codex fixture→真实气泡，保留红/绿及保存失败/长文本/收起证据。 |
| `scripts/verify_seeky_ceiling.py` | +122 / −0（新增） | 原生左右顶边/物理刘海、重复移动、蒙版、关闭与拉下恢复验收。 |
| `tests/test_config_schema.py` | +4 / −0 | 只同步配置键快照契约。 |
| `tests/test_desktop_pet_features.py` | +10 / −51 | 同步纯桌宠界面及品牌契约，保留剩余稳定版功能断言。 |
| `tests/test_dsr_settings.py` | +166 / −0（新增） | 同步 Seeky 标题/版本身份断言。 |

### 实现与交互

- 「连接 → Codex → 任务框外观」提供中性黑灰、海洋蓝、暖纸白和自定义；背景、边框、80–160% 大小、原生选色、实时预览、恢复默认。编辑结束才保存；失败显示错误并恢复实际上次值。
- 文字依据背景选黑/白，提高可读性；字号、按钮、内边距一起缩放；提问全文显示、按钮可重复打开 Codex，完成消息即使带按钮也在 8 秒内收起。工作消息有限时展示；普通台词继续沿用原样式。
- 预览复用同一渲染器，无第二套动作播放器；预览按钮禁用并解释用途。旧按钮在 deleteLater 前隐藏，避免快速编辑时出现重叠描边。控件容器保留共享 32px 最小高度，修复先测量、后 QSS polish 导致的下边裁切。
- 原生物理刘海根据 [Apple safeAreaInsets](https://developer.apple.com/documentation/appkit/nsscreen/safeareainsets) 与 [auxiliaryTopLeftArea](https://developer.apple.com/documentation/appkit/nsscreen/auxiliarytopleftarea) / 右区间隙识别；Qt 逻辑坐标与 AppKit y 方向做转换。角色身体中心在刘海区内时选刘海下沿，否则选可用桌面上沿；半身藏入且保留头部。
- Cocoa 会限制 Tool 窗口进入菜单栏，因此通过原有虚拟位置和 draw_delta 补偿，同时裁切绘制及覆盖区域。拉下回正、关闭倒立恢复完整身体；稳定后动画计时器停止。

### 性能分析

本机 M3 / 8GiB / Cocoa / DPR=2；命令与数据见任务框和倒立 E2E JSON。以下为短采样，不作为整机内存节省承诺。

- 100 次任务框 80/160% 预览交替：最终中位数 **4.898ms**，最大 **21.842ms**；RSS 差 **4,587,520 bytes**。期间主桌宠既有 WebM 播放仍运行，不能把启动解码波动算为预览释放收益。此前轮次 RSS 既有正值也有负值，未宣称长时无增长。
- 三个顶区各 100 次移动：平均 **0.026ms**、最大 **0.230ms**；刘海查询每显示几何/DPR 缓存，最多 8 项。稳定吸附没有持续旋转计时器。
- 新增任务样式仅在消息显示或设置编辑时计算；预览无新线程、FFmpeg、网络、常驻更新计时器。磁盘写入仅在结束编辑/选色确认/恢复默认时保存；真实状态页沿用可见时 1.5 秒本地 IPC，隐藏后停止。Codex 主服务沿用每秒本地增量读取。
- 保留原 106 HD 素材与既有绘制隔离副本。本轮不改解码分辨率、动作帧序或画质；第 4 节三轮内存数据及多宠增长限制仍有效。

### 实机运行记录与检查

```sh
QT_QPA_PLATFORM=cocoa PYTHONPATH=. .venv/bin/python scripts/verify_seeky_task_frame.py --label task-frame-controls-final
QT_QPA_PLATFORM=cocoa PYTHONPATH=. .venv/bin/python scripts/verify_seeky_ceiling.py --label ceiling-final
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
PYTHON_BIN=.venv/bin/python scripts/build_macos.sh --variants webm
.venv/bin/python scripts/verify_dsr_package.py --app "/Users/ray/Applications/seeky· pet.app"
PYTHONPATH=. .venv/bin/python scripts/verify_dsr_packaged_runtime.py --app "/Users/ray/Applications/seeky· pet.app"
```

- 任务框：保存→重新打开、真实不可写目录回滚、损坏颜色/NaN 恢复、216 字提问完整显示、打开按钮维持提问、完成自动隐藏；errors=[] / exit 0。颜色容器 32px，两个子控件完整在容器内；预览没有可见旧按钮。截图 task-color-control.png、task-frame-settings-preview.png、task-frame-settings-minimum.png、task-frame-question.png。
- 刘海：本机 QRect(665,0,185,32)，两侧上沿33、刘海下沿32，左右与中央头部截图 ceiling-left/notch/right.png；重复移动不漂移、半身比例、拉下恢复、关闭倒立恢复均通过。E2E 使用真实 PetWindow 公共移动方法；OS 鼠标拖动限制仍未全覆盖。
- 全量现有 pytest：**2914 passed / 21 skipped / 262 warnings，169.86s，exit 0**；68 个改动/新增 Python 文件 ruff 通过，git diff --check 通过。
- 修改后高 CPU 负载 8 个 worker，原 Qt/IPC/clip 生命周期族连续三轮 exit 0：4.432 / 3.678 / 3.870s；逐轮日志与 setup/reset 见 stress-seeky-final.json。
- 新安装包：28 个关键模块字节码和当前源码一致（实际数量见 package-verification.json）；新图标原始/派生/ICNS 与包内一致，106 HD 哈希一致，arm64 与 codesign 深层严格校验通过。真实实例控制通道读取106动作、播放、非法动作返回错误、退出及 FFmpeg 子进程无残留，packaged-ipc.json exit 0。
- 安装版原生 CUA：搜索任务框，键盘 120%→恢复100%，打开/取消原生 Colors，实时 Codex 正在工作可见，Seeky 名字/圆角图标/实际版本可见，底部退出同时结束设置和主进程；seeky-installed-native.json exit 0。测试后重新启动供使用。
- 红结果保留：最初缺任务默认值；ModernSelect 接口与 harness 配置父目录误用；Cocoa 窗口钳位导致半身坐标偏差；关闭倒立后未恢复身体；架构行数预算与旧渲染 fake 接口；最后颜色容器24px/子控件30px的裁切。分别修正并保留失败日志，未禁用测试。旧安装版收到退出已关闭解码子进程，但主进程10秒未结束，限定旧 executable 的 SIGTERM 清理；新安装版底部退出正常。
- 固定深色是用户指定范围，浅色主题验收不适用；暖纸白任务框自身的文字对比和渲染已实测。

### 安装、发布与边界

- 当前安装：`/Users/ray/Applications/seeky· pet.app`；桌面 Seeky 同名入口。旧 `/Users/ray/Applications/dsr · pet.app` 与桌面旧入口均已移除；旧包可在废纸篓恢复，配置和原始项目保留。autostart_wanted=false，无需迁移自动启动入口。
- 源码上传目标：[个人 GitHub fork 的 Seeky 分支](https://github.com/YARRAYYAR/dsh-pet-indesktop/tree/codex/seeky-pet)。保留 origin 指向上游，新增 personal 指向自己的 fork；不覆盖上游或个人 main。Git 直连超时后使用本机已配置代理进行传输。
- 发布证据去除真实本地会话标识，原记录存放忽略目录 .scratch/private-evidence；无需 API 密钥。Codex 本地 rollout 格式兼容性及打开目标会话可见性限制仍见第5节。
- 原素材放大像素感仍受源分辨率限制；未交付实时 ML 超分或完整1440p替换。三宠内存采样没有改善、真实 OS 点击穿透/拖放尚未完整核验；未把所有功能描述为无条件保证。
- 本机 ad-hoc 签名，无 Developer ID 公证；本轮 Windows/Linux 原生运行与 GitHub Actions 构建未核验。

## 十、seeky.4：最新图标、放大素材与多宠实测（2026-10-03）

### 10.1 本轮实现

- 最新用户原图 SHA256：`f94c0056d3f5e467d904b18f9a6dda1b0bd3dd80ba61bf5785115c5db2653f2a`。源 PNG 原样保留，Mac 派生图保持圆角、透明角和外留白；之前两张图移入品牌归档。
- 多窗的元数据/首帧后台预热共用两路信号量；等待可因关闭、隐藏、会话结束、换代而退出。预测预热也计入同一预算。播放 reader 不受此预算限制。
- 同路径、mtime、大小的首帧 QImage 共享只读像素存储。弱池不强持有图像；关闭某子窗后，从仍存活的首帧 LRU 登记中找到同一缓冲，防止重生子窗重复分配。Qt 绘制隔离副本继续保留。
- 放大时只在下一动作开始选用 2560×1440 变体；当前动作不中断、不改变帧序。回到常规尺寸，在下一动作开始恢复 1280×720 并清理旧高清播放器。外部角色包沿用自己的素材和 manifest。
- 91 个高清变体来自用户原项目保留的母版；其余 15 个复用原项目的离线 [Real-ESRGAN NCNN](https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan) / `realesr-animevideov3` 流程补齐。固定视频可见区域加 64 源像素上下文做推理，然后恢复原画布；Alpha 独立由原帧平滑缩放，不腐蚀或提高阈值。引擎、模型不随 App 分发，也不在运行时执行。
- 实际用户配置原先关闭 `experimental_single_process_spawn`，因此多宠走独立进程。本机交付启用已经存在的单进程多窗与同角色共享解码；源码保留原默认和独立进程回退。每个桌宠仍有自己的设置和退出入口。

### 10.2 多宠内存和播放性能

环境：M3、8 GiB、macOS Cocoa、Retina DPR=2；相同运行时与 106 个原素材；随机种子 42；三宠同角色待机动作，真实 `AppShell.spawn_pet()` 入口。基线为上一版 `f483c72`（seeky.3），两端均启用共享模式，以隔离本轮代码收益。物理占用统计包含主进程和 FFmpeg 子进程，每 0.5 秒采样。

| 轮次 | 基线 12–32 秒占用中位数 MiB | 新版占用中位数 MiB | 基线采样峰值 MiB | 新版采样峰值 MiB |
|---|---:|---:|---:|---:|
| 1 | 417.6 | 339.8 | 680.7 | 631.6 |
| 2 | 376.8 | 347.6 | 648.1 | 564.3 |
| 3 | 419.5 | 309.9 | 674.1 | 569.5 |
| 三轮中位数 | **417.6** | **339.8** | **674.1** | **569.5** |

采样占用中位数下降 **18.63%**，采样峰值中位数下降 **15.51%**。这不是整机所有负载的保证；12–32 秒内仍可能包含预热。三次两端均约 23.68–23.81 fps，没有前向源帧缺口，队列丢帧计数 0。首帧缓冲重复从 7 个动作降为 0；新版首帧后台解码同时最多 2 路。

补充原生流程：

- **80 秒三宠观察**：45–80 秒占用中位数 275.2 MiB，后段相对前段下降 23.1 MiB；23.77–23.80 fps，帧缺口/队列丢帧均 0。该时长不能证明任意长时间无增长。
- **关闭第二子窗再重新新增**：窗口数 3 → 2 → 3，共享首帧重复 0，23.16–23.48 fps，帧缺口/队列丢帧均 0；其他桌宠继续播放。
- **三个放大桌宠**：三个源宽均 2560，23.53–23.63 fps，帧缺口/队列丢帧均 0。12–32 秒占用中位数 **943.5 MiB**，采样峰值 **1958.2 MiB**，预热收尾时下降。高清解码和图像占用明显更高，不能套用常规尺寸的内存降幅。

失败证据保留：早期 Documents 源码路径存在数秒文件读取卡顿，关闭重生流程一轮约 12.8 fps；另一次叠加测试和离线推理负载低于验收帧率。相同源码复制到非同步本地缓存后，真实新增/关闭流程和上述三次交替比较通过。此结果区分了运行位置及负载，没有证明某一个后台进程是唯一原因。读取不存在 `_size` 字段的观测脚本失败也保留，修复采样脚本后重跑，失败轮不计入收益。

证据：[三轮汇总](evidence/seeky4-memory/summary.json)、[80 秒观察](evidence/seeky4-memory/long-observation.json)、[实际新增与关闭](evidence/seeky4-memory/public-spawn-local.json)、[三宠高清成本](evidence/seeky4-memory/large-three.json)。每次 JSON 包含命令、目录、输入、检查、退出状态，日志同目录保留。

### 10.3 画质与资源成本

- [原素材完整性](evidence/seeky4-quality/source-integrity.json)确认原 106 个 WebM 的 SHA256 全部与基线相同；最新图标与用户文件逐字节相同。
- [同帧视觉比较](evidence/seeky4-quality/comparison-idle.png)在白、灰、彩色背景比较相同头部局部、同尺寸、相同预乘 Alpha / Qt 平滑缩放。高清版本改善头发和眼睛轮廓，原画缺失的细节仍有上限。
- [原生放大首轮](evidence/seeky4-quality/native-green-first.json)核验当前动作不重启、源宽 1280 → 2560 → 1280、时长相同、旧高清队列清空，放大播放约 23.82 fps。
- [遮罩诊断](evidence/seeky4-quality/coverage-diagnostic.json)使用真实素材，在三种尺寸、三种旋转、每例八次检查精确区域及画面字节；单帧遮罩约 0.6–4.4 ms。没有足够证据把之前全部卡顿归因于遮罩，因此本轮不改遮罩算法。

新增运行成本：首次读取 HQ 索引一次，动作边界检查候选文件；没有新增网络请求、实时模型推理或额外播放线程。后台等待最多每 50 ms 检查一次退出条件，沿用原有预热线程。首帧共享键在首帧路径做 stat，池失效时扫描存活登记；每帧绘制路径不扫描该池。高清像素数量是原图四倍，画质收益有对应的解码、缓存和包体成本。

### 10.4 逐文件说明与检查

| 文件 | 改动及原因 |
|---|---|
| `.gitignore` | 允许独立 HQ 目录纳入源码，保留其他素材忽略规则。 |
| `pet/branding.py` | 派生版本升级为 seeky.4，软件名保持 seeky· pet。 |
| `pet/resources/app-icon.png` | 最新用户原图，原样保留。 |
| `pet/resources/app-icon-mac.png`、`assets/icon.ico` | 派生平台图标，Mac 采用圆角留白。 |
| `assets/brand/archive/seeky-source-v3.png`、`seeky-source-v4-first.png` | 保存本轮替换的两张旧图。 |
| `pet/library.py` | 两路后台预热、动作边界 HQ 选择、旧播放器清理；避免默认尺寸加载高清队列。 |
| `pet/webm_clip.py` | 首帧弱共享与存活登记回找；子窗关闭和重生不重复保存同一像素。 |
| `pet/window.py` | 切换/回退动作使用按尺寸选择；成功后释放退役变体。 |
| `pet/window_optional_services.py` | 连接按播放器对象识别、忽略旧对象帧、清理迟到完成；移到已有 mixin，满足 window 行数预算。 |
| `scripts/build_macos.sh` | 包含 HQ 数据；bundle 版本 4.2.1.4。 |
| `scripts/superres_webm_assets.py` | 复用离线流程，固定上下文裁切和原 Alpha 回填；输出验证失败时拒绝提交素材。 |
| `scripts/verify_seeky_media.py` | 全部素材的精确帧数/帧率/时长/透明标记及哈希核验，成功才写 HQ 索引。 |
| `scripts/verify_seeky_multi.py` | 真正多窗公共入口、关闭重生、FPS、帧缺口和进程树内存测量。 |
| `scripts/verify_seeky_quality.py` | 原生尺寸切换、动作不断播、高清播放器释放检查，支持本地非同步源码目录。 |
| `scripts/compare_seeky_quality.py` | 真实 Qt 同帧同背景视觉比较。 |
| `scripts/verify_seeky_coverage.py` | 真实素材遮罩区域、画面不变和耗时诊断；不构造新的单元测试。 |
| `scripts/verify_dsr_package.py` | 新增 library 字节码匹配、106 HQ/索引哈希与版本校验；单独输出保留上一版证据。 |
| `scripts/verify_dsr_packaged_runtime.py` | 单独输出原生包运行证据，保留上一轮记录。 |
| `README.md` | 说明共享模式启用、实测范围及高清放大成本。 |
| `THIRD_PARTY_NOTICES` | 补充离线引擎与模型软件出处及原许可证。 |
| `assets/characters_hq/**`、`docs/evidence/seeky4-*/**` | 每一项的路径、用途、增删数见本轮 change-files 清单；素材哈希和证据哈希分别可核验。 |

已完成门禁：全仓 Ruff 通过；全量 pytest **2914 通过、21 跳过**；8 个自有 CPU 负载进程下，相关时序族复跑三遍，分别 **171/171/171 通过**。没有新增单元测试，沿用已有门禁与原生验收流程。日志和重跑命令在 `evidence/seeky4-memory`。

## 十一、seeky.5：恢复鼠标位置驱动的身体转向（2026-10-03）

对照项目 GitHub 历史提交 [`910e773`](https://github.com/YARRAYYAR/dsh-pet-indesktop/blob/910e773f2be8259b38251195c60c9dfc8f7a0c1f/pet/window.py)，恢复原有行为：每 120ms 检查鼠标与桌宠窗口中心的位置；横向差小于 16px 或距离超过 280px 时维持当前朝向，其余情况直接更新整帧左右镜像。没有眼球追踪或渐变过渡。当前 v4.2.1 官方稳定源码已不含这段轮询，因此以该仓库保留的原提交作为行为依据。

原生 Cocoa 验收实际移动系统指针到 -320、-140、0、+140、+320px 五处；方向外、左、死区、右、方向外五例全部通过，测试结束恢复原光标位置。可复跑：`.venv/bin/python scripts/verify_seeky_cursor.py`。结果见 [cursor-facing.json](evidence/seeky4-quality/cursor-facing.json)。此前模拟点击没有移动系统指针的失效记录及 macOS 指针事件延迟的首轮失败均单独保留，不计为通过。

全仓 Ruff 通过；完整 pytest **2914 通过、21 跳过**。构建出的 macOS 包通过源码字节码、106 个原素材/106 个高清素材哈希、图标、模块排除、版本及签名检查；包内真实动作目录/播放/错误/退出流程通过，子进程退出。证据分别为 [installed package](evidence/seeky4-quality/package-verification-4.2.1.5-installed.json) 与 [packaged IPC](evidence/seeky4-quality/packaged-ipc-4.2.1.5.json)。

本次版本为 `4.2.1.5` / `4.2.1 · seeky.5`。没有强杀旧桌宠进程；确认旧版进程已退出后，旧 `.4` bundle 被可恢复地移入废纸篓，新版安装到 `/Users/ray/Applications/seeky· pet.app` 并已打开。

### 10.5 最终素材和原生尺寸切换验收

[全部素材检查](evidence/seeky4-quality/media-final.json) **106/106 通过**：尺寸正好两倍、逐文件精确帧数及帧率一致、时长差小于 5 ms、AlphaMode=1；索引包含全部哈希及源时间线。91 个旧母版的哈希也原样保留（[来源记录](evidence/seeky4-quality/hq-provenance.json)）。高清目录合计约 **1000.7 MiB**，最大单文件约 17.3 MiB。

[最终 Cocoa 尺寸切换](evidence/seeky4-quality/native-final.json)通过：源宽 1280 → 2560 → 1280，动作时长均 10.04 秒，放大约 23.81 fps，源帧缺口 0，旧高清队列为 0。两张原生截图见 [放大前](evidence/seeky4-quality/native-final-before.png) / [放大后](evidence/seeky4-quality/native-final-after.png)。[忙碌动作同帧对比](evidence/seeky4-quality/comparison-busy.png)包含白、灰、彩色背景；新生成版本改善轮廓清晰度，推理可能产生细微线条变化，不声称与原画 RGB 逐像素相同。内存优化本身没有改原帧像素。
