# seeky.6：共享首帧预热、固定侧栏与动作库反馈

> 基线：`1197997863640209595a49aa6498db6f0d33fa05`，seeky.5。
> 分支：`codex/seeky-pet`；日期：2026-10-04；运行平台：macOS Apple Silicon，8 GiB RAM，Python 3.13.2，PySide6 / Qt 6.11.2，Cocoa，Retina DPR 2。
> 本轮补充 [seeky.5 优化报告](PR-REPORT-DSR-PET-2026-10-02.md)，沿用 [设置变更门禁](SETTINGS-CHANGE-GATES.md) 与 [打包入口](ONEDIR_PACKAGING.md)。本报告包含成功、失败及未达到的验收门；最终安装与发布结果在下文记录。

## 一、用户可见变化与边界

- 截图指定的侧栏保持 200 logical px；品牌、搜索、七个导航域、二级文字缩进和底部保存、退出、版本的位置不变。
- 齿轮、爪印、鼠标点击、菜单列表、链条、流程节点、扬声器表达对应功能。品牌原图保留。缺少的三个图形来自 Lucide 官方 SVG，完整许可随资源和应用打包。
- 导航复用按钮；悬停 120 ms、选中 140 ms、按下 80 ms，重复操作从当前绘制值继续。隐藏停止，减少动态效果直接呈现目标状态。
- 动作库分别显示选择、请求、排队、实际播放。列表刷新保留仍可见的选择和滚动位置；同名一次性动作重播能同时显示“正在播放”和“已排队”；实际播放由主进程 watch 推送确认。
- 同素材并发预热只有一个首帧解码者，后台等待能取消。失败、换代、素材替换、会话结束释放认领，其他活跃消费者可重试。
- 输入 VP9 解码器仍为单线程；显式限制原先自动扩大的过滤器与 rawvideo 输出线程池。Qt 原生掩码替代 Pillow 多平面拷贝，并保持像素覆盖规则。

高清素材、RGBA/透明像素、源帧序、Qt 绘制隔离副本、环容量 4、播放器队列容量、动作 IPC、设置保存和配置格式沿用现状。没有新增依赖或持久配置键。

设计采用清晰层级、一致对齐、分组、可读性和短反馈；具体时长为本项目参数。参考 [Apple Layout](https://developer.apple.com/design/human-interface-guidelines/layout)、[Apple Motion](https://developer.apple.com/design/human-interface-guidelines/motion)、[WCAG 文字](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html) 与 [非文字对比度](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html)。没有将黄金比例用作机械布局公式。

## 二、修改文件说明

最终逐文件增删行数与证据文件清单见本文末尾及 manifest；以下说明代码归属与目的。

| 文件 | 改动与原因 |
|---|---|
| `pet/webm_clip.py` | 以原有素材身份键协调在飞首帧，保留播放器各自的代次、取消、进程和显示状态；首帧及播放两处 FFmpeg 管线限制过滤/输出线程。 |
| `pet/frame_edges.py` | Qt 掩码表达 alpha > 0 且排除精确黑色 A=1；保留一像素扩展、裁剪和旋转后的既有覆盖。 |
| `pet/ui_motion.py` | 控件自持的有限动画；native 减少动态效果查询，静止状态没有动画轮询。 |
| `pet/settings_navigation.py` | 120/140/80 ms 状态反馈、可逆动画、隐藏收口、DPR 图标与字体放大。 |
| `pet/settings_brand.py` | 侧栏只创建一次并更新状态，功能图标使用设置专用键。 |
| `pet/settings_actions.py` | 弱回调、代次、请求取消；列表位置保留；watch 与播放确认分离；断线刷新恢复订阅。 |
| `pet/settings_widgets.py` | 开关复用有限动画；当前页面独立尺寸，避免隐藏表单把动作库撑成异常长页。 |
| `pet/settings_theme_qss.py` | 中性灰播放按钮、焦点标记与可读说明/占位文字，不改变侧栏几何。 |
| `pet/context_menus/icons.py` | 设置专用 SVG 键，复用已有矢量图形；右键菜单图标语义保持原样。 |
| `pet/resources/settings-icons/*`、`THIRD_PARTY_NOTICES` | 三个官方图标及完整 ISC / Feather 许可、来源。 |
| `pet/branding.py`、`scripts/build_macos.sh` | 显示 seeky.6，bundle version 4.2.1.6。 |
| `scripts/verify_dsr_package.py` | 验证新模块、SVG 和许可实际进入包；检查源字节码、版本、素材与签名。 |
| `scripts/verify_seeky_multi.py` | 原生公开多开、帧序与生命周期、物理占用/RSS、去重后的缓冲成本、不同动作/尺寸/缩放/关闭重生。 |
| `scripts/verify_seeky6_prewarm.py` | 实际 FFmpeg 并发预热与原始/最终画面哈希；参考/候选/当前管线字节比较。 |
| `scripts/verify_seeky_settings_ui.py` | 原生尺寸/字体矩阵、真实动作 IPC、失败恢复、交互和空闲成本。 |
| `tests/test_webm_first_frame_lock.py` | 实现前添加八种并发、取消、失败、素材替换与会话结束边界。 |
| `tests/test_dsr_rendering.py` | 优化掩码前添加独立像素 oracle，验证全部 alpha、颜色、填充及输入不变。 |
| `tests/test_seeky6_settings.py` | UI 实现前写入控制客户端边界；另在修复迟到初始 watch 快照之前补其顺序失败用例。 |
| `README.md`、`docs/INDEX.md`、本报告、`docs/evidence/seeky6-*` | 当前交付说明、索引与成功/失败证据。 |

## 三、实现与所有权

首帧 `_first_frame_flights` 是进程级临时认领表。只有解码 owner 创建 FFmpeg；等待者在后台以 Event 等待，每次复查自身代次、关闭、会话结束和素材身份。提交与取消共同使用播放器 reader lock；owner 的 finally 始终摘除认领并唤醒等待者。临时结果仅供已经等待的消费者使用，结束后没有新增永久图像缓存。

共享环和队列原本就保存同一 bytes 引用，因此没有缩小它们来冒充内存收益。成本记录按 bytes 对象身份和 QImage cacheKey 去重；显示图像、窗口缩放图像另外列出，QPixmap 的隐式共享别名不再重复相加。进程物理占用包含分配器和 FFmpeg，不能等同于这些引用分类之和。

动作确认和 watch 使用不同 socket。确认只解除请求状态；新的 watch 播放事件确认开始。同名旧播放不能用名称相等判断重播开始；初始 watch 快照也必须与后续播放事件区分。hide/delete 会取消所有命令并使迟到回调失效。

## 四、性能分析

### 4.1 预热并发压力：三轮真实 FFmpeg 前后对比

同一 2560×1440 素材，三个后台消费者同时进入。脚本刻意同步进入预热函数；该实验绕过正常 MovieLibrary 的两路预热门，仅证明重复解码峰值的收益。

| 指标 | seeky.5 | seeky.6 |
|---|---:|---:|
| 每轮实际首帧解码次数 | 3 / 3 / 3 | 1 / 1 / 1 |
| 进程树物理峰值 MiB | 625.2 / 979.0 / 1337.3 | 175.5 / 197.6 / 196.5 |
| 三轮峰值中位数 MiB | 979.0 | 196.5 |

两端三轮 RGBA 和最终 Qt 合成哈希相同；等待者复用同一首帧存储，清理后在飞表与子进程均为零。此压力实验的约 80% 峰值下降不代表正常两路预热、长期占用或任意素材的收益。完整命令、输入、PNG、断言及退出码见 [prewarm](evidence/seeky6-performance/prewarm/)。

### 4.2 FFmpeg 与轮廓成本

官方 [FFmpeg 文档](https://ffmpeg.org/ffmpeg.html) 说明 `filter_threads` 默认按可用 CPU 创建线程池。现有输入 `threads=1` 不限制过滤与 rawvideo 输出池。本机三种素材、每种连续八帧，共 24 帧：30 → 6 OS 线程；参考与当前 RGBA 每帧 hash 相同。短样本不能证明长期吞吐，须以原生播放结果判断。见 [pipeline-after.json](evidence/seeky6-performance/pipeline-after.json)。

九种尺寸/旋转的覆盖区域与显示字节一致。1.3 倍轮廓微基准原中位数约 1.98–2.12 ms，当前约 1.50–1.61 ms；不把微基准折算为全应用 FPS。首次 Qt 实现出现掩码调色板反转，失败原图和日志已保存，修正后像素 oracle 与原生区域比较通过。见 [coverage-after-2.json](evidence/seeky6-performance/coverage-after-2.json)。

### 4.3 高清三宠与长时观察

六轮原生公开多开、full 预热、1.3 倍三宠的 110 秒冷启动观测已完成，固定 42–109 秒窗口仍包含预热和内存换页，尚未全部达到 22 fps；不能把此窗口称为已经稳定的稳态。全部源帧前向缺口为零，退出无 FFmpeg 残留。完整原始数据见 [public-spawn](evidence/seeky6-performance/public-spawn/)。

实际安装偏好为 balanced。按同机同配置、公开多开、1.3 倍、100 秒 / 固定 37–99 秒帧率窗口，各三轮完成。库级低分辨率首帧预热在 2.3–4.3 秒结束；窗口仍包含自然动作重播和预测预热的实际成本。

| 轮次 | 基线三宠 fps | 当前三宠 fps | 基线/当前固定窗口物理中位数 MiB | 基线/当前物理峰值 MiB |
|---|---|---|---|---|
| 1 | 21.26 / 21.34 / 21.38 | 23.40 / 23.59 / 23.41 | 1126.8 / 854.2 | 2049.1 / 1586.9 |
| 2 | 23.26 / 23.37 / 23.26 | 22.70 / 22.57 / 22.49 | 948.6 / 1307.4 | 1723.5 / 1913.7 |
| 3 | 21.92 / 21.92 / 22.09 | 23.35 / 23.34 / 23.50 | 1203.3 / 971.5 | 1816.2 / 1626.8 |

首批已发布实现的三轮全部 >=22 fps、源帧缺口/队列丢帧为零、关闭无 FFmpeg 残留；基线三轮中的两轮未达到全部三宠门槛。三轮物理峰值中位数 1816.2 → 1626.8 MiB（约 10.4%），固定窗口占用中位数 1126.8 → 971.5 MiB（约 13.8%）。第二轮当前内存高于基线，不能声称每次占用必降或仅由首帧去重造成此差值。原始 RSS、实际 FFmpeg/缓存/环/队列/窗口成本与逐帧记录见 [balanced](evidence/seeky6-performance/balanced/)。

成本分类使用同一固定窗口每轮中位数，再取三轮中位数（MiB）：

| 分类 | 基线 | 当前 |
|---|---:|---:|
| 进程树 RSS | 1065.6 | 1052.1 |
| FFmpeg 物理占用 | 612.9 | 480.5 |
| 主进程物理占用 | 510.3 | 487.8 |
| 首帧 QImage 唯一存储 | 24.6 | 24.6 |
| 播放器队列引用字节 | 70.3 | 84.4 |
| 环引用字节中位数 | 0.0 | 0.0 |
| 队列/环 raw bytes 去重后 | 42.2 | 42.2 |
| 播放器当前图像 | 42.2 | 42.2 |
| 窗口缩放图像 | 17.8 | 17.8 |

中位数不能逐项相加得到总量。环在部分采样点非空，0.0 中位数不表示从未共享；初始拓扑和每个采样点已记录。队列引用量波动且指向共享 bytes，未当作实际分配。RSS 的变化很小；物理占用收益不能表述为相同幅度的 RSS 降低。常驻首帧、raw bytes 和绘制图像未减少。

620 秒长时观察完成，但帧率门未通过：三宠 21.85 / 21.84 / 21.76 fps，缺口与队列丢帧为零，预热并发最多两路，结束后解码子进程为零。370–450 秒发生明显降速，随后恢复；整段物理峰值 2432.6 MiB，100–620 秒物理中位数 1182.0 MiB。首/末一分钟物理中位数 1243.4 → 915.3 MiB，未见单调增长；不能由这一轮宣称排除所有泄漏。RSS 与逐分钟摘要见 [long-summary](evidence/seeky6-performance/long-summary.json)，逐帧、采样、耗时、原生截图和失败断言见 [optimized-long](evidence/seeky6-performance/balanced/optimized-long.json)。

不同真实动作、混合尺寸、四次缩放、关闭第三窗到两窗并公开新增回三窗均完成；原始/HQ 到下一动作边界切换，没有中途重启。三宠最终源宽都是 2560，帧序与队列丢失为零、并发预热两路、退出清理通过，但窗口帧率 21.43 / 21.46 / 21.45 fps，未达到 22 门槛。见 [mixed](evidence/seeky6-performance/balanced/optimized-mixed.json)。单宠放大/缩回流程 23.83 fps、源宽 1280 → 2560 → 1280、时长均 10.04 秒，旧 HQ queue=0 且释放；见 [quality-final](evidence/seeky6-performance/quality-final.json)。

降速期的单帧 mask 2.49 → 2.96 ms、scale 2.44 → 4.10 ms、consume 1.43 → 2.91 ms；多个步骤一起升高，无法将原因只归于掩码。事后系统显示 8.8 GiB swap 已使用，pmset 没有记录温度/性能告警；该事后快照不能证明降速时系统压力的因果关系。两种候选 Qt Indexed8 转换路径均通过已有像素 oracle，但原生 832/1664/2304 宽度、各 100 次比较都慢于当前实现，已拒绝且没有改产品源码。完整可重复实验见 [experiments](evidence/seeky6-performance/experiments/)。本轮不通过改帧率窗口、跳动作边界、减帧或降画质消除这些失败；长时和复合场景的 22 fps 要求仍未全部实现。

早期脚本对刚构造的新窗重复 `switch_clip`，会额外拆除共享源；该批失败记录完整保留，不作为公开多开最终比较。固定同动作每圈重播仍使用产品真实切换路径，保留已有 draining/回退语义；没有绕过动作边界以提高测得 FPS。新脚本从真实 `_on_frame` 入口记录 Movie 换代前的末帧与缩放边界；不同动作从 idle / turn / act 选取并断言三种名称，避免本素材包仅一个“待机”导致伪造多动作场景。

### 4.4 UI 静止成本与新增路径

最终设置独立窗口空闲 2.008 秒消耗 CPU 0.0402 秒，RSS 119439360 → 69419008 bytes，运行中动画为零。真实桌宠同时运行时的 CPU/RSS包含播放器，另见 final-live，不作为静止 UI 成本。

导航只在构造时读取三个 SVG；每个动画只在交互时查询系统偏好。没有每帧网络、磁盘或偏好轮询，没有新增持续线程。首帧协调不新增线程；复用既有后台预热线程，取消检查为等待期间约 50 ms 一次。新增 Event、表条目和临时 QImage 引用仅在并发预热期间存在。

## 五、实机运行记录

- 原生 720×500、1000×680、1100×760、720×500 字体 125% / DPR 2：56 个对应截图、392 个尺寸/搜索/保存/退出/导航行高/DPR 字段相等。见 [geometry-comparison.json](evidence/seeky6-ui/geometry-comparison.json)。
- 实际 106 个动作的 list/search/play/watch；一次性动作播放期间请求另一动作、同名重播、真实排队与开始、刷新保留选择与滚动、键盘与快速反向反馈。见 [最终真实 IPC](evidence/seeky6-ui/final-live-root/result.json)。
- 关闭实际 command server，UI 清理旧播放并显示错误；重建 server 后刷新恢复订阅，新的实际播放推送更新界面。
- 将本次临时配置目标换为目录制造真实磁盘替换失败；原生错误对话框可见，设置仍打开；恢复目标后保存关闭成功。没有修改用户配置制造错误。
- 实际 polished QWidget 调色板：搜索占位字 4.945:1、动作搜索 4.693:1，说明 6.889:1、版本 5.291:1；必需图标与焦点 >=3:1。采用 alpha 合成后的 sRGB 相对亮度。首次 palette 尝试被 QSS 覆盖，保留失败后改用 Qt 的 `placeholder-text-color`。见最终 UI JSON 的 contrast。
- 全部 106 份原始和 106 份 HQ、质量索引、两份品牌原图与冻结基线逐字节 SHA-256 一致；见 [asset-integrity.json](evidence/seeky6-performance/asset-integrity.json)。

## 六、测试与验证

| 门 | 实测状态 |
|---|---|
| 首帧故障断言红/绿 | 实现前 4 failed / 4 passed；实现后相关 34 passed。 |
| 解码/取消/生命周期/渲染回归 | 121 passed。 |
| UI 初始 snapshot 顺序红/绿 | 修复前 2 failed / 1 passed；最终设置相关 42 passed，真实 IPC 验收通过。 |
| 全量 pytest | 初批2935 passed；后续最终2949 passed /21 skipped /262 warnings，188.25秒。 |
| Ruff / diff / 报告门 | 最终 Ruff 与源码/文档 diff --check 通过，报告规则测试 21 passed；原始日志尾随空白按原样保留。 |
| 受影响时序族 CPU 满载三轮 | 8 个本次拥有的负载进程，CPU 采样中位数 100%；初批三轮各138 passed；后续三轮各159 passed，36.11 /39.22 /38.95秒，负载进程全部退出。 |
| 原生画质、默认三宠、不同动作与缩放新增关闭 | 单宠画质与 balanced 三轮通过；620 秒长时和复合缩放场景帧率约 21.4–21.8，22 fps 门未全通过，帧序与清理通过。 |
| 包内源代码/素材/许可/版本/签名与实际 IPC | cache 与安装位置均通过；30 个产品模块字节码、212 素材、索引/品牌/三 SVG/许可、arm64、4.2.1.6、ad-hoc 签名；实际 106 list/play/error/quit、子进程零残留。 |
| 安装与授权分支推送 | 已安装并打开；原 seeky.5 完整保留，安装未改用户配置；分支推送结果见交付节。 |

每次 E2E 的 JSON/日志记录命令、cwd、输入、断言、实际结果、退出状态与清理。失败保留，包括 UI 高度、保存断言、qWait 事件循环饥饿、同名重播和对比度；后续改为 QEventLoop.exec/QTimer 驱动真实事件循环，没有修改播放源来掩盖验收饥饿。

## 七、限制与回滚

安装后 [应用原生截图](evidence/seeky6-performance/installed-native.png) 与 [打包设置截图](evidence/seeky6-performance/package-settings-native.png) 已保存。

本轮真实平台为 macOS；Windows/Linux 原生运行和系统减少动态效果入口未在这些平台核验。macOS 减少动态效果查询读原生偏好；true 分支通过 Qt 控件回归和验收 provider 验证，没有改动用户的系统偏好。字体 125% 是本次验收显式字体放大，未改用户系统字体设置。

动作 IPC 的 list/watch 现有协议只提供当前动作，不提供主进程待播队列。动作库隐藏时取消本地请求并清理已确认的队列提示；返回后重新订阅当前播放。如果隐藏期间仍有待播动作，返回页无法恢复其排队提示，直到实际开始的 watch 推送到达。本轮未扩展协议，也不声称跨页面隐藏恢复待播队列。刷新和播放响应期间的选择、滚动及普通动作的排队反馈已经验收。主进程边缘探头/飞行等效果还可能将请求动作替换为待机；现有成功 ACK 仍返回原 requested，此时页面的“已排队”推断不能证明原动作确实待播。外部联动覆盖待播动作也没有对应队列推送。该限制由只读源码链确认，特殊效果场景未做原生验收；本轮不将其宣称为已通过。

8 GiB 机器冷启动 full 预热仍可能低于 22 fps，必须把预热峰值与稳定播放分开。Mac 包使用本地 ad-hoc 签名，没有 Developer ID 公证。回退可使用保存的原应用或 revert 本轮提交；本轮没有配置迁移，保留已有偏好和素材。

## 八、交付记录

- 当前应用：`/Users/ray/Applications/seeky· pet.app`，bundle 4.2.1.6；已实际打开，主进程通过真实 IPC 返回 106 个动作。
- 缓存构建：`/Users/ray/Library/Caches/dsr-pet-build/macos/seeky· pet.app`。
- 原应用完整备份：`/Users/ray/Library/Caches/seeky-pet-backups/seeky.5-20261004-140941.app`；安装时用户 Config 的字节哈希未变，没有配置迁移。
- 构建命令：`PYTHON_BIN=.venv/bin/python scripts/build_macos.sh --variants webm`；静态与运行命令见 [package-cache](evidence/seeky6-performance/package-cache.json)、[package-installed](evidence/seeky6-performance/package-installed.json)、[实际安装 IPC](evidence/seeky6-performance/package-installed-ipc.json)、[原生设置保存](evidence/seeky6-performance/package-settings-native.json)。运行脚本需 `PYTHONPATH=.`；首次漏设导致 import 失败，原始日志保留后正确重跑通过。
- 极高思考子代理只读审查完成，线程/取消/动效/包装源码未发现新的阻断问题，队列协议限制已列出。见 [source-review](evidence/seeky6-performance/final-source-review.json)。
- 发布目标：个人仓库 `YARRAYYAR/dsh-pet-indesktop` 的 `codex/seeky-pet`，保留历史、不 force push。源码/验收提交 `90f488112486b79c120fa91d397ca4e8d3cd97b2` 已推送并通过远端 SHA 核对；见 [publish-source](evidence/seeky6-performance/publish-source.json)。后续交付记录为纯文档提交，未改产品或安装包。

本轮实现、Mac 安装和普通 UI 流程已交付；长时/复合高清场景的 22 fps 以及特殊效果的待播提示仍有明确未完成项，不称为全部验收通过。

原始 stdout 的尾随空白使包含日志的 `git diff --check` 返回 2；这是证据文本格式，未清洗或隐藏。排除仅 `docs/evidence/**/*.log` 后，基线到源码提交的源码、文档、JSON 与资源 diff 检查返回 0，两份输出均已保存。


### 后续批次：掩码转换与扩展成本

在已发布 `35078cb093c06c35e67d147d6f9a2d2a1fcad864` 的 seeky.6 基础上继续处理长时/混合场景帧率差距。本批仅改 `frame_edges.coverage_region`：合法 Qt `ARGB32_Premultiplied` 画布直接比较零像素与黑 A1；其他格式沿用 alpha 隔离转换。3×3 覆盖扩展分成水平、垂直两步，区域 union 从八次减为四次。素材、播放器队列、帧序、碰撞边界、Qt 绘制隔离及 IPC 均沿用现状，无新增缓存、线程、依赖、网络或磁盘路径。

依据 [Qt QImage 格式说明](https://doc.qt.io/qt-6/qimage.html#Format-enum) 与 [Qt 6.11 掩码源码](https://github.com/qt/qtbase/blob/6.11/src/gui/image/qimage.cpp)，合法预乘像素 A=0 的 RGB 为零，黑 A1 在转换前后的位值相同；非预乘透明 colored 输入不能直接比较 raw zero。像素 oracle 在实施前补充单行/单列、1/8/31/32/33 宽度、稀疏边角、黑 A1、colored A1、空图及输入字节不变；这些少见组合无法可靠从现有媒体 E2E 穷举，所以使用独立确定性图像检查。优化契约红例为 **1 failed / 20 passed**（旧路径仍调用格式转换），实现后 **21 passed**。原生三个尺寸×三种旋转 **9/9** 覆盖一致、显示字节不变，最大 2.05 ms；记录见 [continuation](evidence/seeky6-performance/continuation/)。

每种宽度 100 次的 Cocoa 独立比较（ms）：

| 宽度 | 已发布 seeky.6 | 直接预乘 | 分离扩展 | 两者组合 |
|---|---:|---:|---:|---:|
| 832 | 1.199 | 0.923 | 1.098 | 0.844 |
| 1664 | 4.561 | 3.614 | 3.812 | 3.218 |
| 2304 | 7.436 | 6.183 | 7.322 | 6.039 |

这只证明掩码函数成本下降，不能替代最终帧率检查。Big-int 位图扩展虽像素覆盖相同但更慢；Alpha8 直接生成掩码同样更慢，均未用于产品。改变镜像/缩放顺序会改变最终像素，即使较快也未采用。Big-int 首次 native 对照的 `QRegion ==` 断言失败：矩形拆分 428/440 不同，但 XOR 空且逐点覆盖相同。后续原生检查用 XOR 空验证覆盖；保留失败与诊断记录，不将其误报为像素损失。已写的密集随机 oracle 仍保留原断言并通过。

本批三轮前后对照、620 秒长测和混合场景已完成，但帧率仍失败：

| 轮次 | 修改前 fps | 修改后 fps |
|---|---|---|
| 1 | 23.28 / 23.49 / 23.24 | 14.13 / 14.12 / 14.22 |
| 2 | 14.71 / 14.52 / 14.55 | 3.44 / 3.62 / 3.63 |
| 3 | 5.28 / 5.29 / 5.28 | 3.88 / 3.92 / 3.81 |

620 秒为 5.47 / 5.49 / 5.48 fps，混合场景为 3.35 / 7.02 / 3.34 fps。所有轮次源帧缺口、队列丢帧、重复首帧缓冲和退出 FFmpeg 残留均为零；不同动作、四次缩放及2→3窗生命周期按原脚本完成。后续旧实现也显著降速，且 decode/scale/consume 多步骤一起升高，不能由这些轮次声称新掩码改善了整体帧率或降低了稳态占用。

增加同时记录系统指标的单次100秒复测：15.89 / 15.85 / 15.80 fps；系统 CPU 中位数88.8%、峰值98.3%，同期 swap-in 增加4055.8 MiB，可用内存首末1239 /1048 MiB。该观测支持“测量期间有明显系统压力”，不证明全部降速由压力造成；没有关闭其他应用或更改系统设置以制造通过结果。原始数据见 [observed-system](evidence/seeky6-performance/continuation/observed-system.json) 与同目录逐帧原生记录。10分钟帧率门仍未满足。

为减少轮次间环境变化的影响，又做100轮交错次序的真实 Cocoa QWidget 对照：同一个HQ帧的两份1px位移画布，每次改变掩码，计入计算、setMask、绘制与事件分发。修改前中位数2.182 ms，修改后1.985 ms（约9.1%）；掩码覆盖一致。见 [native_mask_cost](evidence/seeky6-performance/continuation/native_mask_cost.json)。这是一条局部路径收益，未被包装成多宠整体帧率达标。

最终源检查2949 passed /21 skipped /262 warnings，188.25秒；Ruff通过。CPU满载三轮各159 passed，36.11 /39.22 /38.95秒，8个本次负载进程全部结束；改动范围门通过。新安装包构建、缓存/已安装的静态字节码/215份素材与品牌文件/签名检查及两次真实IPC list106→play→invalid→quit→无子进程残留均通过。已更新 `/Users/ray/Applications/seeky· pet.app`，build4.2.1.6；此前seeky.6整包备份为 `/Users/ray/Library/Caches/seeky-pet-backups/seeky.6-before-mask-20261004-232913.app`，最初seeky.5备份仍保留。安装时默认Config字节哈希不变。CUA重新打开实际已安装程序，真实主进程再次返回106个动作，保留运行；新原生截图见 [installed-native](evidence/seeky6-performance/continuation/installed-native.png)。本批未改变UI源码，沿用首批56截图/392geometry字段与实际设置保存/失败恢复验收。测试前正常退出本任务打开的已安装主进程，ACK 与进程退出成功；“配置字节不变”断言失败，原有 `AppShell._on_about_to_quit → save_position` 会保存位置。没有保存具体字段的退出前快照，因此只记录字节检查失败，不宣称已经逐字段核对；未重写或回滚用户配置。完成后重新打开已安装程序。

后续队列字段扩展仍未应用：当前协议保持原样，隐藏后队列恢复和特效改写请求的提示限制仍按前文记录。兼容扩展需要同时覆盖一次性等待与切换重试两种主进程状态；等待用户对可选字段的答复，不从“继续”推断新的协议授权。

后续最终范围门一次因 raw Git index 指纹变化失败；逐项核对1597条 mode/blob/stage 与 HEAD tree 全相同、无 staged/unmerged 改动后，仅刷新 stat 指纹，复跑通过。失败日志、语义证明与复跑均保留在 continuation。

### 最终增删行数与文件清单

逐文件数值来自 `git diff --numstat -z`；新增文本按实际行数计算。没有删除文件。另有 652 份验收文本/截图/实验资源，逐个路径、字节数与 SHA-256 在 [change-manifest.json](evidence/seeky6-performance/change-manifest.json)；二进制记为 null。manifest 自身不作递归哈希。

| 文件 | 状态 | + / − 行 |
|---|---|---:|
| `README.md` | modified | 2 / 0 |
| `THIRD_PARTY_NOTICES` | modified | 53 / 0 |
| `docs/INDEX.md` | modified | 1 / 0 |
| `docs/PR-REPORT-SEEKY6-2026-10-04.md` | new | 235 / 0 |
| `pet/branding.py` | modified | 1 / 1 |
| `pet/context_menus/icons.py` | modified | 13 / 1 |
| `pet/frame_edges.py` | modified | 25 / 22 |
| `pet/resources/settings-icons/LICENSE` | new | 43 / 0 |
| `pet/resources/settings-icons/list-tree.svg` | new | 17 / 0 |
| `pet/resources/settings-icons/mouse-pointer-click.svg` | new | 17 / 0 |
| `pet/resources/settings-icons/workflow.svg` | new | 15 / 0 |
| `pet/settings_actions.py` | modified | 172 / 46 |
| `pet/settings_brand.py` | modified | 50 / 33 |
| `pet/settings_navigation.py` | modified | 48 / 22 |
| `pet/settings_theme_qss.py` | modified | 10 / 5 |
| `pet/settings_widgets.py` | modified | 51 / 15 |
| `pet/ui_motion.py` | new | 87 / 0 |
| `pet/webm_clip.py` | modified | 69 / 9 |
| `scripts/build_macos.sh` | modified | 1 / 1 |
| `scripts/verify_dsr_package.py` | modified | 10 / 3 |
| `scripts/verify_seeky6_prewarm.py` | new | 199 / 0 |
| `scripts/verify_seeky_coverage.py` | modified | 2 / 1 |
| `scripts/verify_seeky_multi.py` | modified | 145 / 18 |
| `scripts/verify_seeky_settings_ui.py` | new | 456 / 0 |
| `tests/test_dsr_rendering.py` | modified | 90 / 0 |
| `tests/test_seeky6_settings.py` | new | 193 / 0 |
| `tests/test_webm_first_frame_lock.py` | modified | 158 / 0 |
