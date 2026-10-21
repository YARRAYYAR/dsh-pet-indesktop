# seeky.8：窗口生命周期、预热调度与离线常驻优化

> 基线 `7a5fed77ec4fd6b44f0e8f16bc8051b2571b41e4`；分支 `codex/seeky-pet`；2026-10-21。目标代码 `/Users/ray/Documents/New project/dsr-pet`。本轮完成局部架构优化及验证；未打包、安装、发布或提交 Git。初始工作树差异及源码快照见证据清单。

文档入口：[索引](INDEX.md#pr-报告存档)。

## 一、核心特性

角色切换与正常关闭共用幂等 `release_resources()`，新窗准备失败时回收候选并保留原窗与配置。旧窗只解绑共享服务，窗口自有服务及媒体永久释放。识屏的排队结果在关闭后被拒绝，避免写入新角色会话。

每个素材库唯一持有内部 `PrewarmScheduler`，认领代次/任务/动作首帧，合并批量与预测请求；交互最后释放通过 GUI queued signal 恢复。离线停止 1.2 秒事件轮询，保留 3 秒上线探测；恢复立即消费新增事件，再启动事件计时器。启动前历史仍被过滤，新 PID 桥文件的首批事件不会被误当历史。

原媒体、动作与分辨率不变。绘制深拷贝、两帧队列、四槽共享环、全局两路预热解码预算不变。新增调度器没有常驻线程池，没有新增用户配置项。

## 二、修改文件说明

| 文件 | 类型/增删 | 改了什么与原因 |
|---|---:|---|
| `pet/app.py` | 修改 +72/−48 | 候选构建/角色配置与会话回滚、旧窗永久释放、退出共用释放与共享服务归属 |
| `pet/dsh_state.py` | 修改 +35/−7 | 离线停事件计时器、恢复立即读取、探测代次与启动 EOF 书签 |
| `pet/library.py` | 修改 +75/−104 | 兼容入口委托调度器、跨来源首帧完成语义与原全局解码预算 |
| `pet/prewarm_scheduler.py` | 新增 +196/−0 | 新增每库调度器，统一认领、去重、交互通知、换代及失败回滚 |
| `pet/window.py` | 修改 +52/−13 | 幂等释放、部分构造回收、共享/自有服务归属与识屏迟到拒绝 |
| `scripts/dsr_proc_memory.c` | 修改 +13/−4 | 拓展进程树 CPU/唤醒原始计数；保留内存探针列，并标明 Mach ticks |
| `scripts/verify_seeky_residency.py` | 新增 +476/−0 | 新增隔离 Cocoa 播放/交互/切换验证、进程树计数、质量及退出证据 |
| `tests/test_animation_prewarm_phase2.py` | 修改 +9/−5 | 预热线程替身按新调度边界收窄，保留旧策略断言 |
| `tests/test_dsh_state.py` | 修改 +253/−2 | 离线/恢复/首批新文件/锁存/停止与旧探测代次回归 |
| `tests/test_low_priority_warm_interaction_yield.py` | 修改 +4/−4 | 等待阶段接缝兼容调度器与实际首帧完成返回值 |
| `tests/test_character_switch_lifecycle.py` | 新增 +262/−0 | 新增真实 Qt 窗口切换、失败保留、部分构造、共享归属及迟到会话写入回归 |
| `tests/test_prewarm_scheduler.py` | 新增 +428/−0 | 新增重复请求、交互恢复线程、失败回滚、旧代次与共享预测未完成回归 |
| `docs/PR-REPORT-SEEKY8-MEMORY-2026-10-08.md` | 修改 +3/−3 | 仅补齐既有门禁要求的三个标题，原证据与数字保留 |
| `docs/INDEX.md` | 修改 +1/−0 | 登记本报告入口 |
| `docs/PR-REPORT-SEEKY-RESIDENCY-2026-10-21.md` | 新增 +173/−0 | 本轮修改、占用、实机、失败记录及验收限制 |

旧 `PR-REPORT-SEEKY8-MEMORY-2026-10-08.md` 仅修正三个标题以满足既有文档门禁；其中历史数字没有用于本轮占用结论。`tests/test_architecture.py` 的 4666 行红线未调高。

## 三、实现要点

- `PetWindow.__init__` 把实际初始化包在异常收口内。释放路径兼容部分初始化，先置关闭闸门，再释放气泡、缓存、所有计时器、DPR/屏幕/输入监听、碰撞及解码订阅、素材库和交互持有。完整窗口仍调用原 `_stop_all_timers()` 清空拖拽及待重试状态。
- `PetInstance` 在构造、接线、文件处理器、音效和托盘准备成功后替换旧窗。失败恢复角色内存值/落盘配置及碰撞会话。退出应用也走同一永久释放入口。
- 调度任务先认领再启动线程；线程启动失败回滚认领并记录异常；pause 换代并通知 Condition。旧代次及已 shutdown 的库不能复活。交互期间没有 50ms GUI 重试或周期 Condition 唤醒；等待解码槽的既有 50ms 可取消检查保留。
- 首帧认领跨 high/low/predicted 来源合并。low/full 遇到尚未完成的共享预测不能提前置完成，沿用现有 2 秒未完成补跑；不以缓存当前是否还持有所有首帧判断完成，兼容 LRU 淘汰。
- DSH 跨线程探测信号携带代次，stop/restart 后排队的旧结果不能清除新探测的 inflight 状态；状态订阅者在通知中 stop 时也不能重新启用计时器。

Qt 计时器只在所属线程启停，跨线程交互恢复使用显式 queued QObject slot。依据：[Qt 官方计时器线程规则](https://doc.qt.io/qtforpython-6/overviews/qtcore-timers.html)。完成通知的真实 Qt 线程用例通过，未为未证实的线程疑点修改代码。

## 四、性能分析

环境：Apple M3、8 CPU、8 GiB；macOS 26.6.2 arm64；Python 3.13.2、PySide6/Qt 6.11.2、psutil 7.2.2。普通源宽 1280，HQ 源宽 2560。固定 seed 42，balanced 预热，禁自动移动/闲置降帧，使用隔离配置/临时角色和保留非监听环回端口。所有正式原生运行串行，未与 pytest、PNG 分析或素材哈希并发。

短测每版普通/HQ 各 3 次，每次标称 36 秒，实际各轮时长见 JSON；内存等资源样本从 12 秒后取稳态。FPS 另取 14≤t<duration−1 且 stage=steady 的帧，按相邻同窗口 epoch 的有效间隔数除以间隔总秒数计算。长测每版普通模式目标为 620 秒，实际采样时间、样本数及完成结果以本节表格和原始退出记录为准，不换算完整率。长测 CPU 峰值取稳态有效 rate 样本，物理占用、线程及 FFmpeg 峰值取全窗样本；物理增长为末 8 个稳态点中位数减首 8 个稳态点中位数。短测/长测使用透明度 0 保持 Qt 绘制活动，数据适用于单宠、共享服务/解码配置，含观测器开销；不是默认独立单窗或屏幕合成器能耗测量。另有可见窗口的 90 秒交互流程，不混入稳态比较。用户的其他应用未被关闭，后台活动/系统分配仍可能影响波动。

CPU 原始 `proc_pid_rusage` 计数是 Mach ticks，本机 `mach_timebase_info=125/3`；100% 表示一个逻辑 CPU 核满载。早期 620 秒基线原件保留，通过离线脚本统一换算，后续验证器同时保存原始 ticks 与换算纳秒。依据：[XNU CPU 赋值](https://github.com/apple-oss-distributions/xnu/blob/main/osfmk/kern/bsd_kern.c)、[rm_time_mach](https://github.com/apple-oss-distributions/xnu/blob/main/osfmk/kern/task.c)、[退出子进程累计](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/kern_exit.c)。进程树变化或计数回退区间不计算 rate；CPU/唤醒纳入父进程退出子进程累计，包含探针成本。RSS/物理 footprint 是当前进程树各进程之和，不是去重后的全系统内存。

12 次短测均为原生 QTimer 标称 36 秒，raw.elapsed_seconds 范围为 35.903–37.170 秒；各轮实际时长及完成断言见原始 JSON。

稳态物理占用：每轮取稳态中位数，再比较三轮中位数；括号为三轮范围。收益判据预先采用保守规则：下降幅度需大于两版三轮极差的较大者。

| 场景 | 基线 MiB：中位数（范围） | 候选 MiB：中位数（范围） | 候选−基线 | 波动门槛 |
|---|---:|---:|---:|---:|
| normal | 251.99（250.55–257.38） | 238.94（221.31–248.78） | -13.05 MiB | 27.48 MiB |
| hq | 571.74（544.10–575.28） | 549.94（509.53–588.02） | -21.80 MiB | 78.48 MiB |

每行其余中位数是三轮各自稳态中位数的中位数；物理占用、线程及 FFmpeg 的采样峰值取三轮全窗样本最大值。内存等稳态样本从 steady_after=12 秒开始；FPS 另取 14≤t<duration−1 且 stage=steady 的帧，相邻同窗口 epoch 的时间差为分母，FPS=有效间隔数/间隔总秒数，不代表所有阶段帧率。每轮采样时间、样本数及完成断言结果保留在 JSON 中，未计算完整率。

| 场景/版本 | RSS 稳态 MiB | 全窗物理峰值 MiB | CPU 稳态 % | 线程 median/max | FFmpeg median/max | pkg/interrupt 稳态唤醒每秒 | 选定区间 FPS 范围 | 离线事件 timeout 总数 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| normal/baseline | 301.09 | 280.02 | 40.73 | 21/25 | 1/2 | 10.16/330.64 | 23.559–23.797 | 90 |
| normal/candidate | 303.09 | 272.36 | 39.08 | 21/24 | 1/1 | 8.87/331.84 | 23.716–23.800 | 0 |
| hq/baseline | 627.80 | 670.05 | 77.45 | 21/24 | 1/1 | 6.89/311.58 | 23.646–23.793 | 89 |
| hq/candidate | 649.52 | 605.75 | 75.96 | 21/25 | 1/2 | 11.82/310.98 | 23.793–23.795 | 0 |

长测中位数均取 stage=steady 样本；物理、线程及 FFmpeg 的 max 取全窗样本，CPU max 只取稳态有效 rate 样本。物理增长定义为末 8 个稳态采样点的中位数减首 8 个稳态采样点的中位数，不是两端单点差或全窗增长。采样时间及 raw.elapsed_seconds 均相对 shell.start、初始素材哈希与环境记录完成后、observe 前的计时零点。表中记录时长截至最终保存，包含观测阶段设置、Qt 循环、收口及事后检查，不含此前准备；完整命令墙钟见外层 *-invocation.json。完成依据原始运行的完成断言和退出码，不以样本数换算完整率。

| 620 秒普通模式 | 采样数；首–末时间/raw.elapsed_seconds s | 物理稳态 median/全窗 max MiB | RSS 稳态 median MiB | CPU 稳态 median/max % | 线程稳态 median/全窗 max | FFmpeg 稳态 median/全窗 max | pkg/interrupt 稳态唤醒每秒 | 选定区间 FPS | 末8稳态点中位−首8稳态点中位 MiB | 离线事件 timeout |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | 595；1.560–620.148/621.059 | 251.72/302.05 | 231.06 | 47.99/90.90 | 21/46 | 1/3 | 8.53/280.97 | 23.060 | -12.47 | 517 |
| candidate | 605；1.019–620.376/620.680 | 241.16/280.46 | 257.70 | 40.88/90.95 | 21/24 | 1/2 | 6.88/301.32 | 23.538 | +6.16 | 0 |

正式 14 轮中全部记录的可见阶段前向源帧缺口、队列丢帧和收口后现存子进程树的 FFmpeg 数量见质量汇总；CPU/内存不依据旧报告数字。

normal：未确认超过重复波动的稳态内存下降（差值 -13.05 MiB，门槛 27.48 MiB）。 hq：未确认超过重复波动的稳态内存下降（差值 -21.80 MiB，门槛 78.48 MiB）。

新增路径与频率：每库新增 1 个 QObject 调度器；不增加常驻线程。20 次同动作预测由 20 个等待线程合并为 1 个任务，21 次 high 请求合并为 1 个批次（隔离回归输入）。批次协调/分阶段 worker 仍短暂创建，全局两个预热槽不变，故播放 reader 加预热时 FFmpeg 可超过 2。交互期间的 50ms GUI 重试移除，最后一次释放发通知；未完成 low 批次仍用既有 2 秒补跑。没有新增网络端点；启动一次建立已有桥文件 EOF 书签，此后离线只有 3 秒在线探测，在线恢复即读新事件。

baseline 4 次从切换阶段标记到切换调用返回后的退役检查（含构建、回收及约40ms调度）为 144 / 139 / 252 / 133 ms；candidate 4 次从切换阶段标记到切换调用返回后的退役检查（含构建、回收及约40ms调度）为 272 / 263 / 822 / 743 ms。该区间结束早于新窗 observe 及随后 24 帧恢复检查，不代表首次可见或完整恢复延迟。候选原生日志可见 reader 回收 join 路径的 GUI 停顿，切换调用比单纯隐藏旧窗有额外成本；不能把资源正确释放描述为切换更快。无交互时常驻开销见短/长测，未单独分离启动 EOF 书签的墙钟成本。

没有降低画质、帧数或缓存预算换取占用。正确性修复与稳态占用收益分开判断；长测每版仅 1 次，趋势描述不作为重复测量的统计结论。

## 五、实机运行记录

证据根目录：`/Users/ray/Documents/Codex/2026-10-21/w/work/seeky-optimization`。每次流程均有命令、工作目录、相关环境、输入/断言、日志和实际退出码。失败与中断保留，不改写为成功。

正式短/长测复跑：

```sh
python3 /Users/ray/Documents/Codex/2026-10-21/w/work/seeky-optimization/run_matrix.py baseline
python3 /Users/ray/Documents/Codex/2026-10-21/w/work/seeky-optimization/run_matrix.py candidate
python3 /Users/ray/Documents/Codex/2026-10-21/w/work/seeky-optimization/run_matrix.py baseline long
python3 /Users/ray/Documents/Codex/2026-10-21/w/work/seeky-optimization/run_matrix.py candidate long
```

每轮真实命令在 `*-invocation.json`。矩阵调用 `.venv/bin/python -X pycache_prefix=/tmp/seeky-residency-metrics-cache scripts/verify_seeky_residency.py`，原生 Cocoa；HQ 使用 `--scale 1.3 --require-hq`，普通 `--scale .72`。基线来自已记录清洁 HEAD 的 228 文件不可变源码快照，`assets` 链接原素材。源文件云占位先补齐；完整媒体首遍还补齐 40 个占位文件，7 处 mtime 纳秒漂移使严格首遍 exit1，稳定复读及内容对照保留在 `analysis/original-media-*`。

真实交互复跑：同验证器加 `--exercise --duration 90 --scale .72`，不加 `--background`。临时第二角色建立实际子目录和逐文件软链接，复用原视频并写临时清单。输入包括真实 QTest 鼠标按住 3 秒、隐藏 1 秒再显示、真实 QLocal IPC 动作库开关两次、角色切换 4 次。

- 基线有效复现 `baseline-exercise-v3.json`：4 次退役旧窗 `closing/library_shutdown/cleaned_clips` 均 false；exit1。操作流程本身完成。
- 候选 `candidate-exercise.json`：同样 4 次均 true，迟到检查缓存仍为零，exit0；与收口后现存子进程树的 FFmpeg 检查、源帧/队列数据一起验收。
- 构造中途/接线/托盘入口/素材库失败通过公共入口故障注入；托盘入口注入发生在真实托盘构造前，未覆盖托盘内部部分构造失败。系统线程耗尽难以安全实机制造，先写隔离回归注入 Thread.start 失败。真实 Qt 事件循环验证候选回收、旧窗保留、配置恢复与共享服务不被误停。
- 真实线程排队识屏完成结果，临时 SessionStore 验证释放后不写入新角色会话；阻塞缩略图生命周期回归覆盖关闭后迟到结果不能回填。
- DSH 使用临时桥文件及可控在线探测；验证离线零事件 timer、恢复立即消费、新 PID 首批事件、审批/问题锁存及停止后的旧代次拒绝。真实账号、会话和密钥未作为测试输入。

补充退出验收：`candidate-decoder-identities-invocation.json` 单独执行同一 90 秒候选交互流程，`measurements/candidate-decoder-identities.json` 从启动返回起登记全部 54 个 FFmpeg 的 Popen/PID/create_time；真实退出后逐一 poll 并核对进程身份，不依赖当前父进程，54 个全部 absent、exit0，Popen 包装已恢复。独立离线分析 `analysis/candidate-identities-analysis.json` 的全部可见阶段源帧缺口/队列丢帧为 0，PNG 分析通过；该补充运行持有观测对象，未纳入占用比较。原 16 轮仅具有子进程树退出证据，不把补充身份跟踪追溯为原矩阵的逐进程记录。

正式证据复核 `analysis/native-acceptance-final.json` 共 178 项，0 失败；基线交互 exit1 仍表示原始释放缺陷，未当作产品通过。

完整素材清单 216 文件，前后内容一致=True；内容摘要 `3cd8e0ab3f6929e0aeae08044ea49296910673c85458510993bae15250c55941`。本轮 PNG 的尺寸、非空角色、透明背景及半透明像素逐项通过。截图来自不同时间点，因此不作像素等值比较。FFmpeg 数量仅为应用收口完成后单次扫描时仍属于父进程现存递归子进程树的进程；不能据此排除已脱离该树的孤儿进程。

| 原生运行 | exit | 所有可见阶段源帧缺口 | 队列丢帧 | 收口后现存子树 FFmpeg | PNG 尺寸/可见/透明/半透明像素 | PNG 逐项核验 |
|---|---:|---:|---:|---:|---|---|
| baseline-normal-1 | 0 | 0 | 0 | 0 | 922×562 / 314022 / 204142 / 241471 | 尺寸：通过；非空角色：通过；透明背景：通过；半透明像素：通过 |
| baseline-normal-2 | 0 | 0 | 0 | 0 | 922×562 / 314406 / 203758 / 242104 | 尺寸：通过；非空角色：通过；透明背景：通过；半透明像素：通过 |
| baseline-normal-3 | 0 | 0 | 0 | 0 | 922×562 / 314022 / 204142 / 241471 | 尺寸：通过；非空角色：通过；透明背景：通过；半透明像素：通过 |
| baseline-hq-1 | 0 | 0 | 0 | 0 | 1664×1014 / 989943 / 697353 / 749056 | 尺寸：通过；非空角色：通过；透明背景：通过；半透明像素：通过 |
| baseline-hq-2 | 0 | 0 | 0 | 0 | 1664×1014 / 991444 / 695852 / 750656 | 尺寸：通过；非空角色：通过；透明背景：通过；半透明像素：通过 |
| baseline-hq-3 | 0 | 0 | 0 | 0 | 1664×1014 / 990000 / 697296 / 750366 | 尺寸：通过；非空角色：通过；透明背景：通过；半透明像素：通过 |
| candidate-normal-1 | 0 | 0 | 0 | 0 | 922×562 / 314516 / 203648 / 242378 | 尺寸：通过；非空角色：通过；透明背景：通过；半透明像素：通过 |
| candidate-normal-2 | 0 | 0 | 0 | 0 | 922×562 / 314061 / 204103 / 242903 | 尺寸：通过；非空角色：通过；透明背景：通过；半透明像素：通过 |
| candidate-normal-3 | 0 | 0 | 0 | 0 | 922×562 / 314022 / 204142 / 241471 | 尺寸：通过；非空角色：通过；透明背景：通过；半透明像素：通过 |
| candidate-hq-1 | 0 | 0 | 0 | 0 | 1664×1014 / 989911 / 697385 / 750212 | 尺寸：通过；非空角色：通过；透明背景：通过；半透明像素：通过 |
| candidate-hq-2 | 0 | 0 | 0 | 0 | 1664×1014 / 991392 / 695904 / 750951 | 尺寸：通过；非空角色：通过；透明背景：通过；半透明像素：通过 |
| candidate-hq-3 | 0 | 0 | 0 | 0 | 1664×1014 / 989675 / 697621 / 750266 | 尺寸：通过；非空角色：通过；透明背景：通过；半透明像素：通过 |
| baseline-long-620 | 0 | 0 | 0 | 0 | 922×562 / 313872 / 204292 / 240667 | 尺寸：通过；非空角色：通过；透明背景：通过；半透明像素：通过 |
| candidate-long-620 | 0 | 0 | 0 | 0 | 922×562 / 314498 / 203666 / 241980 | 尺寸：通过；非空角色：通过；透明背景：通过；半透明像素：通过 |
| baseline-exercise-v3 | 1 | 0 | 0 | 0 | 922×562 / 314590 / 203574 / 243820 | 尺寸：通过；非空角色：通过；透明背景：通过；半透明像素：通过 |
| candidate-exercise | 0 | 0 | 0 | 0 | 922×562 / 314527 / 203637 / 242328 | 尺寸：通过；非空角色：通过；透明背景：通过；半透明像素：通过 |

失败/排除记录：早期并发或端口隔离不完整的探索测量不纳入比较；交互 v1 未收到鼠标 hold、v2 目录软链接未被 rglob 遍历，均作为验证器失败保留。正式 v3 改为启动时关闭穿透并用实际交互区域、真实子目录/逐文件链接完成流程。`harness-versions.json` 记录 CPU 单位修正前后源码摘要；620 秒基线的原始 CPU summary 单位标签不应直接使用。

完成检查口径校准：`candidate-normal-1` 的原生 QTimer 标称 36 秒，实际 `elapsed_seconds=35.903`。检查器首遍使用严格 `elapsed_seconds>=36` 判定，产生 exit1；该失败记录保留，随后按原生 harness 的完成断言复核。此次调整是短测完成检查口径校准，不是产品修复；长测两版 `raw.elapsed_seconds` 均达到 620 秒。

## 六、测试与验证

| 门禁/记录 | 结果 | 墙钟 s | 退出码 |
|---|---|---:|---:|
| pytest-main-final | 2957 passed, 21 skipped, 262 warnings in 135.96s (0:02:15) | 137.11 | 0 |
| pytest-decoder-lifecycle | 39 passed in 22.91s | 23.53 | 0 |
| pytest-interaction-isolated | 27 passed in 61.87s (0:01:01) | 62.44 | 0 |
| pytest-loaded-1 | 157 passed, 1 warning in 74.99s (0:01:14) | 75.75 | 0 |
| pytest-loaded-2 | 157 passed, 1 warning in 72.84s (0:01:12) | 73.55 | 0 |
| pytest-loaded-3 | 157 passed, 1 warning in 74.06s (0:01:14) | 74.78 | 0 |
| ruff-final | All checks passed! | 0.05 | 0 |
| bridge | 39 tests / 39 pass / 0 fail / 0 skipped | 0.25 | 0 |
| bridge-import | 导入模拟验证通过（具体输出见日志） | 0.06 | 0 |

高负载每轮启动 8 个仅计算的子进程，结束均回收；实际命令及退出确认写入 loaded invocation。桥接 Node 门及导入门分别见 `bridge.log`、`bridge-import.log` 和对应保存记录。独立生命周期、阻塞缩略图及相关回归也在完整测试中执行。

最终测试使用 `PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring` 禁用系统密钥链后端，并设置 `PYTHONDONTWRITEBYTECODE=1`、`PYTHONPYCACHEPREFIX=/tmp/seeky-residency-test-cache` 和 `-X pycache_prefix=...` 绕开本机旧云端 pyc；pytest 默认 offscreen，原生流程 Cocoa。完整 suite 按项目既有策略把三个 decoder 生命周期族及低优交互族单独执行，未删除或禁用测试。

首轮完整记录 `pytest-main.log` 为 5 failed / 2950 passed / 21 skipped；其中 3 条清理状态失败已通过恢复原 `_stop_all_timers()` 收口修复，菜单子进程超时以继承 pycache 隔离解决，旧报告标题门禁只改标题修复。失败补跑 `pytest-failure-recheck.log` 为 73 passed。完整最终与高负载记录以本节表格为准。部分构造故障注入仍产生一次 Qt 未接线 hidden_signal 的 disconnect 警告；资源释放断言通过，警告与既有弃用警告均保留在日志中。

## 七、已知限制与后续

- 本矩阵只覆盖单宠共享服务配置，未对默认独立单窗、多宠、打包程序、Windows、真实 DSH 账号/在线会话作占用结论；平台跳过项见测试记录。
- 短测为每条件 3 次，长测每版 1 次；1 秒采样峰值可能错过更短瞬时峰值。系统内存回收、后台应用和原生 Qt 缓存都会影响绝对数字。
- 截图尺寸、非空绘制、透明背景及半透明像素依据保存的分析字段逐项报告；缺图、字段不足、分析错误或不支持布局不计通过。截图来自不同播放时刻，未把它们当作逐像素等值比较。帧检查覆盖同 epoch/path/generation 内可见阶段的前向缺口，显式隐藏/切换/回环边界单列；不声称已逐帧比对每个动作的首尾边界。
- 原 16 轮的 FFmpeg 退出记录仅覆盖收口时现存的递归子进程树。补充 90 秒流程按 PID/create_time 核对登记的 54 次 FFmpeg 启动，全数退出；身份追踪覆盖范围为该补充运行。
- 切换计时从阶段标记到切换调用返回后的旧窗退役检查，包含约 40ms 排期；终点早于新窗 observe 及后续 24 帧恢复检查，不代表首次可见或完整恢复延迟。
- 同步窗口退役的有界 reader 回收会增加切换时 GUI 停顿，见实机成本；后续若继续优化该路径，应保留 Qt 线程归属及立即关闭闸门，单独验证播放器异步回收，不在本轮更改 reader/绘制实现。

## 八、风险与回滚

变更集中在窗口、素材库调度和 DSH 生命周期；配置无迁移、新增键或素材修改。回滚只恢复本轮代码/文档差异，保留用户配置与原媒体；不可直接 reset 工作树覆盖后续用户改动。补丁及完整证据包随交付保存。
