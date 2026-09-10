# DSH-Pet 保画质内存优化

## 2026-09-10 控制面板更新

- 五页导航与统一浅色样式，气泡位置按需展开；旧右键高级控制归入子菜单。
- 动作库改为目录和播放列表双栏，搜索不再限制排序；保留 JSON 校验与草稿事务。
- 复用当前播放器获取预览，不并行解码整个动作库；缩略图最多缓存 16 张 36px 图片，采样计时器有次数上限。
- 即时预览不保存配置，取消恢复大小、音量、开关、暂停和隐藏状态。修复托盘开关联动导致预览提前写盘的问题。
- 83 项自动测试通过；真实 Cocoa 窗口检查通过，截图见 `verification/control-panel-*.png`。原版按住拖动时的回弹参数和媒体处理链未改动。
- 本次未重新测量整机内存收益，下面内存数据属于之前的指定工作负载。

验证日期：2026-09-09。原项目、用户提供的修改版 ZIP、原视频均保留。

## 基线与范围

- 基线：GitHub `YARRAYYAR/dsh-pet-indesktop` 的 `codex/upload-interaction-pdf` 分支提交 `e76db9d31a8edead28ef2e5097fe84c4dcc6ef59`，从本地对应干净的已跟踪代码建立独立副本。
- 该基线的 `window.py`、`library.py`、`webm_clip.py` 与本轮核对的 GitHub main `7d18242954a63567bb26fdfe431917a83411e8f7` 一致。main 额外包含尚未接通的聊天代码与不匹配测试，本次以可运行基线做最小优化。
- 工作分支：`codex/memory-safe-refactor`。仅本地修改，未发布到 GitHub。
- 目标：减少帧内存滞留和重复分配，改善媒体代码维护边界；保留原版动画、透明边缘、分辨率、采样算法和播放策略。

## 实际修改

1. `pet/frames.py` 独立负责透明底噪清理、裁剪坐标与画布恢复。原 `pet.webm_clip` 导入路径继续可用；播放器仅负责解码、队列、播放时序。
2. 透明底噪清理沿用 Qt 分配的 Alpha8 缓冲及行步长，直接作为 DestinationOut 遮罩。省去独立 ARGB32 遮罩及设置 Alpha 的中间操作，避免修改版在宽度不是 4 的倍数时的缓冲长度错误。只清除 Alpha=1。
3. 动作切换时释放非活动播放器末帧、清空其待处理队列；保留预载首帧供拖拽使用。淘汰或关闭播放器时完整清除帧引用。GIF 包装层保留按需重建能力。
4. FFmpeg 滤镜线程限制为 2。16 位预乘、area 缩放、反预乘及 RGBA 输出与原版完全相同。

这轮未引入 `gc.freeze()`、自动低精度解码、新的色彩滤镜或聊天功能。用户 ZIP 中的这些新增内容仍完整保留在原文件中，未被覆盖；以后可按功能分别处理。原版已有的繁忙时待机策略保持原样。

## 验证证据

- 原基线回归：40 项通过。优化版完整测试：50 项通过，5 条原有 QImage.mirrored 弃用提示。
- 新增测试覆盖宽度 1/2/3/4/6/462/922/1280、Alpha 0–255、输入图像不变、动作切换释放、预载首帧恢复、GIF 重建。
- 91 段 WebM 全部 SHA-256 与原项目相同。每段前 6 帧，共 546 帧，原版与优化版原始解码字节、清理后的预乘图像字节完全一致。不是整部视频全部帧的穷举验证。
- 静态预检 `preflight: OK`。独立代码复核未发现新增缺陷，另行运行相关测试通过。
- `verification/pixel-parity.json` 保存每段视频路径、哈希、尺寸与比对帧数；`test-environment.txt` 保存测试依赖版本。
- 真实 Cocoa 窗口测试覆盖待机、12 次动作切换、隐藏、恢复；配置使用临时目录，不注册全局快捷键。原版和优化版使用同一个新建虚拟环境、相同窗口缩放 0.72，均关闭声音、主动问候和自动负载调整以控制变量。
- 真实窗口截图保存于 `verification/*-window.png`，已人工查看模型与透明边缘。

## 本轮真实窗口内存结果

两次各约 64 秒的顺序运行，每 0.5 秒采样，比较各阶段排除最初过渡后的中位数；单位 MiB，合计 RSS。

| 阶段 | 原版 | 优化版 | 减少 |
|---|---:|---:|---:|
| 待机 | 228.16 | 193.95 | 34.21 |
| 动作切换 | 257.88 | 195.16 | 62.72 |
| 隐藏 | 38.15 | 38.31 | -0.16 |
| 恢复 | 215.42 | 143.75 | 71.67 |

动作切换阶段，非活动末帧占用峰值：12.75 → 0.00 MiB。隐藏阶段两版 FFmpeg 子进程均为 0；两次运行均无捕获到的 Python 异常。瞬时两解码进程交叠仍可能发生，本轮未重写线程退出机制。

原始样本：`verification/baseline-window.json` 与 `verification/optimized-window.json`。单轮 A/B 受系统负载、缓存、内存压缩和采样时刻影响，数字仅描述该工作负载，不能宣称永久固定节省。

## 重现

```sh
cd "/Users/ray/Documents/New project/dsh-pet-memory-safe"
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
.venv/bin/python tools/verify_memory_pixels.py "/Users/ray/Documents/New project/dsh-pet-indesktop" --output verification/pixel-parity.json
QT_QPA_PLATFORM=cocoa .venv/bin/python tools/benchmark_memory_window.py "$PWD" --output verification/optimized-window.json
```

运行桌宠：双击 `run-mac.command`。项目 `.venv` 已准备好。常规启动沿用原应用的用户配置目录；仅测试使用隔离配置。

## 参考与边界

- [Qt QImage](https://doc.qt.io/qt-6/qimage.html)：依据 `bytesPerLine`、Alpha8 和隐式共享规则处理缓冲，不能假设每行字节数等于像素宽度。
- [imageio-ffmpeg 官方实现](https://github.com/imageio/imageio-ffmpeg/blob/main/README.md)：保留后台生成器和 `finally: gen.close()` 的解码子进程退出机制。
- [Python GC](https://docs.python.org/3/library/gc.html#gc.freeze)：冻结对象会让其不再参与后续循环垃圾回收，因此这里不将 freeze 当作通用内存优化。

内存数据为本机短时 RSS 抽样，主进程加其 FFmpeg 直接子进程，包含共享页重复计数的可能，不能等同于活动监视器物理占用。结果不代表长时间无泄漏、跨平台验证或安全审计认证；Windows/Linux 尚未真机运行。原始和高分辨率母版仍在原目录，未转码、删除或覆盖。

## 2026-09-10 本地拖拽优化与 debug

- 原生 Qt 弹性拖拽：首个拖动事件先移动窗口，再切换动画；精确阻尼弹簧按实际时间计算。抛掷使用单独的鼠标速度采样，停住后释放不沿用过期速度。
- 暂停时保持直接拖动，不重启视频或物理计时器；隐藏、暂停、鼠标穿透清理按压、抓手和相关计时器。
- WebM 元数据与已就绪首帧在同一次轮询处理，后续每轮仍只显示一帧，不跳帧。
- 自动测试：60 passed；5 条现有 QImage.mirrored 弃用警告。
- Cocoa 原生窗口验证：真实 WebM 拖动目标在 160ms 后误差不超过 3px；暂停与隐藏停止物理；恢复后视频帧可用。异常列表为空。此为合成输入检查，不代表人手体验或端到端延迟测量。
- macOS arm64 软件包已生成：dist/DSH-Pet Smooth-macOS-arm64.zip。解压后 codesign --verify --deep --strict 与 --selftest 均通过，91 段 WebM 与源码文件 SHA256 一致。使用本地 ad-hoc 签名，未做 Apple 公证。
- 打包在临时目录完成签名和归档，避免 Documents 的 FileProvider 为 bundle 添加 FinderInfo 导致签名校验失败。原始素材不修改。
- 证据：verification/debug-native.json、verification/package-verification.json、verification/build-macos.log。
- GitHub 暂缓：当前仅完成本地代码和软件包；远程仓库之前已创建，但不能据此认为代码上传完成。

## 2026-09-10 动作库交付

- 动作编辑窗口支持名称搜索、原生行拖动、上下移动、名称排序。重开保留选择顺序；搜索不丢失隐藏勾选，搜索中禁用排序以避免隐藏行位置歧义。
- 播放列表以带格式标识及版本的 JSON 导入导出，仅引用当前角色的动作名称。限定 1 MB 输入、检查类型与版本、去重并提示缺失名称；无效文件保持草稿不变。完成才保存，取消不修改原列表。导出使用 QSaveFile 原子提交。
- 设置预览可搜索所有动作类别，并提供编辑器入口；新增滚动区域，保存按钮保持可见。没有新增常驻播放器或计时器。
- 73 项自动测试通过；Cocoa 真实窗口覆盖 91 个动作，检查了搜索、顺序、JSON 往返与设置布局，异常列表为空。
- 新包：dist/DSH-Pet-Action-Library-macOS-arm64.zip。解压后的严格签名验证、自检通过，91 段视频 SHA256 与源码相同。打包版也已实际启动并显示宠物；新编辑器功能在原生源码窗口及测试中验证。
- 证据：verification/action-library-native.json、action-library-package.json、build-action-library.log；界面图 action-library-native.png、action-settings-native.png。
- 修改前源码快照：verification/source-before-action-library.zip。原项目 dsh-pet-indesktop 的已跟踪文件未修改；本地旧软件包保留。

## 2026-09-10 原版回弹、音效与对话框开关

- 用户明确要求保留按住拖动时来回回弹。恢复原版弹簧刚度 80、阻尼 10；用解析积分保持刷新率一致性。保留第一下拖动立即移动、独立鼠标速度采样和暂停清理。先前“不超调”的拖拽设计已被这项偏好替代。
- 拖动跟随阶段不再播放声音；真正撞到边缘或地面时复用系统异步播放器，支持原版柔和、复古跳跃 CC0、可爱弹簧 CC0 和随机混合。新增音效均为短单声道 24kHz PCM WAV，不引入解码库；160ms 冷却，静止落地不发声，跟随总音量、静音、暂停、隐藏及退出。
- Cocoa 实际拖拽检查：目标 x=380，回弹峰值 x=397，最后回到 x=380；系统音频播放器退出码 0。早期固定等待检查曾失败，其中一次未找到可交互的首帧；验证工具改为等待真实视频帧和回弹结束后通过。
- 右键和菜单栏新增顶层“显示对话框（气泡）”，与设置同步。关闭立即清除气泡及其计时器，并取消预览覆盖；选择持久化。
- 设置、动作编辑器、右键菜单用完后销毁，避免反复打开积累窗口与信号连接。
- 证据：verification/drag-rebound-native.json，tests/test_bounce_feedback.py，tests/test_action_library.py。
- 最终自动测试：80 passed；原生动作库与菜单栏气泡开关检查通过，状态同步和持久化通过。最终交付包为 dist/DSH-Pet-Rebound-Sound-Bubble-macOS-arm64.zip；完整源码与视频包为 dist/DSH-Pet-Rebound-Sound-Bubble-source.zip。
