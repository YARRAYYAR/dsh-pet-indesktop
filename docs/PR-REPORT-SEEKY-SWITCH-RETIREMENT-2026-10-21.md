# 角色切换：移除 reader 等待并在退出时完成回收

基线：`244d472b90b1dfc00fe2e9c0a1943483e01e87a7`；分支：`codex/seeky-pet`。
前一轮：[窗口、预热及离线轮询优化](PR-REPORT-SEEKY-RESIDENCY-2026-10-21.md)。
本轮只处理前一轮实测发现的切换等待；不包含打包、安装或 GitHub Release。

## 一、核心特性

角色替换发出停止信号、清空缓存、登记存活 reader 后返回。旧 QObject 销毁和
Python GC 不再执行等待 reader 的 join；应用退出时显式完成遗留回收。
播放器仍独占其进程 finally，GUI 不接管管道关闭或 wait/kill，不增加清理线程。
Qt 对象、timer 和注册表编排仍遵守[官方线程规则](https://doc.qt.io/qtforpython-6/overviews/qtcore-timers.html)。

这是取消特定 reader 等待，首帧取消、锁和新窗口构建仍有同步成本。
定时 sweep 沿用既有有界等待；本轮不承诺所有 GUI 路径完全无阻塞。

## 二、修改文件说明

| 文件 | 增删行 | 修改及原因 |
|---|---|---|
| `pet/app.py` | +8 / −1 | 替换旧窗不等待 reader；应用退出后显式 drain。 |
| `pet/library.py` | +5 / −2 | shutdown 透传等待策略，默认保持同步兼容。 |
| `pet/webm_clip.py` | +21 / −7 | 非阻塞退休、析构零等待；退出用有限宽限完成回收。 |
| `pet/window.py` | +5 / −2 | release_resources 接收并透传等待策略。 |
| `scripts/verify_seeky_residency.py` | +4 / −1 | 记录公共角色切换同步耗时。 |
| `tests/test_character_switch_lifecycle.py` | +65 / −1 | 真实 Qt 切换、DeferredDelete 和退出回收两种参数回归。 |
| `docs/INDEX.md` | +1 / −0 | 登记本报告。 |
| 本报告（新增） | +146 / −0 | 保存本轮实测、失败、测试及限制。 |

无删除文件。原视频、分辨率、透明边缘、源帧、播放速度、两帧队列、共享环和
Qt 深拷贝隔离保持原有实现。

## 三、性能分析

环境：macOS 26.6.2 arm64、8 核、8 GiB、Python 3.13.2、PySide/Qt 6.11.2。
对照与候选各 3×90 秒，合计 24 次真实切换；全部原生及进程身份断言通过。

| 指标 | 对照 | 候选 |
|---|---:|---:|
| 切换同步调用中位耗时 | 691.8 ms | 100.6 ms |
| 12 次切换范围 | 187.1–754.0 ms | 72.5–156.7 ms |
| 各轮稳态物理内存中位数的中位数 | 267.39 MiB | 259.24 MiB |
| 各轮稳态 RSS 中位数的中位数 | 281.38 MiB | 257.25 MiB |
| 观测到的进程树物理内存最大值 | 323.74 MiB | 314.08 MiB |
| 稳态 CPU（一个核为 100%） | 41.41% | 39.81% |
| 稳态线程数 | 21 | 21 |
| pkg-idle 唤醒/秒 | 19.52 | 12.80 |
| interrupt 唤醒/秒 | 325.14 | 331.04 |
| 各轮稳态 FPS | 23.70–23.79 | 23.07–23.78 |

切换中位耗时减少 **85.5%**；它包含新窗构建，
不能等同于 reader join 的独立耗时。物理内存差 8.16 MiB，
小于对照各轮中位数范围 27.55 MiB；
**不认定稳定内存下降**。CPU 与唤醒范围亦有重叠，不宣称稳态 CPU/唤醒收益。
汇总数据与输入 SHA-256 在 `comparison.json`，由 `summarize.py` 生成。

方法：原生 Cocoa，隔离 Config、Python `Path.home` 和 `DSH_HOME`，seed 42，
单宠，原始素材，普通缩放 `.72`。两侧使用同一个不可变 harness；对照源码来自
上述 Git 提交。各三轮 90 秒，每轮包含持续交互、隐藏恢复、两次动作库开关、
四次角色切换。串行执行，不与 pytest、CPU 压测或素材哈希计算并发。
`switch_call_ms` 仅计真实 `PetInstance.switch_character()` 同步调用耗时，
不是首帧呈现延迟。物理内存与 RSS 口径不同；CPU/唤醒包含采样成本及已退出子进程。

新增路径每次替换只传递 keyword 参数并把未退出 reader 留在既有注册表中；
退出时才触发显式 drain。未引入线程、进程种类、网络或磁盘写入。
既有 reader、FFmpeg 和缓存可能短暂存活到 timer 回收，不能把延后 join
直接宣称为常驻内存下降。原生报告保留进程树峰值及稳态样本以评估其代价。

## 四、实机运行记录

仓库内复跑（绝对路径可替换为当前 clone）：

```sh
clang -O2 scripts/dsr_proc_memory.c -o /tmp/seeky-probe
QT_QPA_PLATFORM=cocoa PYTHONDONTWRITEBYTECODE=1 \
PYTHONPYCACHEPREFIX=/tmp/seeky-residency-metrics-cache \
.venv/bin/python -X pycache_prefix=/tmp/seeky-residency-metrics-cache \
scripts/verify_seeky_residency.py --root "$PWD" --output /tmp/seeky-exercise.json \
--probe /tmp/seeky-probe --duration 90 --steady-after 12 --scale .72 --background --exercise
```

纯 HQ 播放删除 `--exercise` 并改为 `--scale 1.3 --require-hq`；普通模式长测改为 `--duration 620`。
测试复用原视频的临时角色清单，退出删除临时目录，完全不读取真实会话或密钥。
命令、环境、输入、断言、逐帧信息、退出状态和失败记录保存在本次证据目录：
`/Users/ray/Documents/Codex/2026-10-21/w/work/seeky-followup/`。
`run_native.py` 可按 `before` / `after` / `after hq` / `after long` 复跑；
`verify_decoder_identity.py` 逐个保留 FFmpeg 的 PID/create_time，检查退出身份，
避免只枚举当前子进程漏掉已经重新挂接的进程。

普通对照/候选各三轮、纯 HQ 90 秒、候选 620.92 秒长测全部退出 0。
完整逐帧离线分析（`all-visible-analysis.json`）覆盖全部记录到的可见阶段，8 次运行
源帧缺口均为 0；各次 queue drops 为 0。长测完成 4 次角色替换和两次动作库开关，
4 个旧窗 closing/library_shutdown/cleaned_clips 均为 true，缩略图均为 0；
离线事件 timeout 为 0。退出身份检查覆盖长测全部 92 次 FFmpeg 创建，
均已退出且 PID/create_time 不再存在，没有迟到注册或观察错误。

| 补充运行 | FPS | 稳态物理内存中位 / 峰值 | RSS 中位 | CPU 中位 | 线程中位 / 峰值 | FFmpeg 中位 / 峰值 |
|---|---:|---:|---:|---:|---:|---:|
| HQ 90 秒 | 23.72 | 600.62 / 670.83 MiB | 630.27 MiB | 70.06% | 21 / 22 | 1 / 1 |
| 普通 620.92 秒 | 22.87 | 281.06 / 372.14 MiB | 246.16 MiB | 44.82% | 21 / 29 | 1 / 2 |

长测 pkg-idle / interrupt 唤醒中位为 6.87 / 295.58 次每秒。
物理内存后段与前段窗口差：HQ +64.01 MiB、长测 +19.55 MiB；不能宣称无增长或
据此推断泄漏，报告保留原始曲线。两组不作为完整同条件长测 A/B 收益比较。

216 个原素材文件共 1,451,675,342 字节再次完整哈希，与上一轮 manifest 完全一致；
内容 manifest SHA-256 为 `3cd8e0ab3f6929e0aeae08044ea49296910673c85458510993bae15250c55941`。
8 张真实 Cocoa 捕获均含非空角色、透明背景和半透明边缘；人工查看了普通长测与
HQ 截图，角色正常可见。截图源帧时刻不同，不用 PNG 像素差声称边缘完全相同。

初次 HQ 调用误带 `--exercise`，触发脚本对临时普通素材的参数拒绝，退出 1；
失败完整保存在 `after-hq-exercise-unsupported*`，未进入播放，后续改为纯 HQ 验证。
成功文件名仍为 `after-hq-exercise.json`，其 inputs.exercise=false，以实际命令为准。

真实 OS 管道无法安全稳定地强制卡死，因此边界用真实 Qt 事件循环、真实窗口
切换和 DeferredDelete，加 Event 控制的 reader 注入验证；不是伪造耗时。
两个实现前红测在 `followup-retirement-red-v2.log`，正 join 超时触发失败。
第一版红测还暴露了测试直接删除 QObject 与排队 deleteLater 回调的冲突；
修正测试为真实 DeferredDelete 后重新确认红灯，再开始实现。
初次候选回归又发现：真实 reader 在退出时 0.5 秒内偶尔仍存活；
`retirement-green-diagnostic.log` 保留证据，随后在退出 drain 中复用既有有限宽限。

## 五、测试与限制

完整流程：证据目录中的 `python3 run_final_checks.py`，逐个命令及退出码均已保存。

| 检查 | 结果 |
|---|---|
| 生命周期聚焦回归 | 52 passed |
| 全量 pytest 主族 | 2961 passed / 21 skipped，135.02 秒 |
| 独立解码生命周期 | 39 passed，22.93 秒 |
| 独立低优交互 | 27 passed，61.92 秒 |
| pytest 合计（不把复跑重复计数） | **3027 passed / 21 skipped** |
| 8 个 CPU burner，受影响时序族 ×3 | 每轮 198 passed；97.61 / 97.14 / 97.32 秒 |
| Ruff：`pet/ tests/ scripts/verify_seeky_residency.py` | passed |
| Node bridge | 39 passed；独立 import smoke passed |

三轮压测的 burner 均在 finally 中 terminate/wait，调用记录确认全部退出。
沿用项目独立进程拆分的生命周期和交互测试，没有删除、跳过新增失败用例。
主族现有 262 条警告主要为弃用 API；故意触发构造失败的用例还报告一次
PySide hidden_signal 断连警告，未把它描述成零警告运行。
Windows、依赖缺失等原有跳过项仍为 21 项，不能把它们计为已验证。

只做本机 macOS 实测；未验证 Windows 真机关机/注销。
测试中的病态无法回收进程仍按原规则保留追踪并告警，不承诺强制终止任意卡死驱动。
GitHub 上传以远端提交 SHA 为准，不等同于重新安装的应用或已发布安装包。
