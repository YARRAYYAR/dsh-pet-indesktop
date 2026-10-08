# seeky.8：保留画质与功能的内存优化

> 基线 `3bc58a702d547b0d9ab01ae18838d97ee7cc812e`（4.2.1.7 / seeky.7），候选 4.2.1.8 / seeky.8。实机对照为 macOS Apple Silicon、8 GiB、同一 Cocoa/Python/Qt/FFmpeg 和同一安装素材。遵照用户测试要求，新增对照全在后台串行执行，每次只开一只测试桌宠；已打开的 seeky.7 进程保持原样。

## 1. 实施范围与约束

- 播放首帧先查共享环，命中直接复用；未命中才创建缓存副本。Qt 播放显示仍独占绘制副本。
- 动作库缩略图从原帧先生成代表帧并缩至 128px，再建立独立缓存副本。
- 缩略图与播放/首帧复用单解码、单滤镜、单输出线程参数；首帧专用路径仅输出一帧。
- 预测预热遇到已有首帧直接返回；未命中仍保留后台二次检查、取消和原有两路并发上限。
- `PetWindow` 正确初始化 8 MiB 字节预算缩略图缓存；关闭窗口时释放缓存并唤醒等待者，延迟完成的 owner 不再回填关闭后的窗口缓存。
- 未修改素材、动作时长、分辨率、RGBA、透明像素、源帧顺序、播放速度、缓存预算、两帧播放队列、四槽共享环、设置保存语义或动作 IPC。包显示版本改为 4.2.1.8。

## 2. 单宠后台性能实测

每轮真实 Cocoa `AppShell`，只启动一只宠物；零透明度保持 Qt 绘制和帧交付路径活动，不触发 hide-pause；使用隔离配置、不与用户窗口交互。短测为基线/候选各三轮，普通 1280px 与 HQ 2560px 分别运行 35 秒。指标是测试进程树物理占用及 RSS 采样；共享内存按实际进程树采样，不以图像引用分类简单求和。原始记录在 `docs/evidence/seeky8/background-single/verified/`。

| 单宠场景 | 指标 | 基线三轮中位数 | 候选三轮中位数 | 变化 |
|---|---:|---:|---:|---:|
| 普通 1280px | 峰值物理占用 | 374.6 MiB | 269.0 MiB | -28.2% |
| 普通 1280px | 固定观察窗物理占用 | 249.6 MiB | 241.7 MiB | -3.2% |
| HQ 2560px | 峰值物理占用 | 724.1 MiB | 680.6 MiB | -6.0% |
| HQ 2560px | 固定观察窗物理占用 | 587.8 MiB | 570.7 MiB | -2.9% |

12 次对照均退出码 0；普通/HQ 每轮均达到至少 23.6fps，源帧缺口为 0，队列丢帧为 0，测试结束无 FFmpeg 子进程残留。HQ 用例强制检查选中的素材必须来自 `characters_hq` 且宽度 2560，防止误将普通素材记作高清结果。峰值收益明显大于稳态收益；稳态只小幅降低，不能据此声称长时内存增长已改善。

**620 秒单宠观察：** 基线运行覆盖采样时间 0.5–619.6 秒（1189 个进程树采样点），物理占用峰值 421.0 MiB、固定观察窗中位数 248.2 MiB，首尾窗口变化 -49.1 MiB，23.77fps、缺帧 0、退出后无 FFmpeg。候选曾采样 0.5–251.3 秒即按用户将优先级转为交付打包/上传的要求停止；验证器以退出码 1 拒绝此不完整记录及末三秒无帧情形。原始输出和 `INVALID_INCOMPLETE` 标记保留在 `background-single/verified-long/`；不作长时前后对比，也不声称候选十分钟增长趋势通过。

## 3. 图像、生命周期与回归证据

- 安装包 215 个原始/HQ 媒体、索引及图标文件与基线 SHA-256 全部一致（215/215）：`docs/evidence/seeky8/media-after-final.json`。
- 真实 Cocoa 生命周期关闭窗口用例通过：持有中的解码 owner 期间关闭窗口，等待者被唤醒、缓存为空、迟到结果不回填、无解码器残留；对应 `close-cache-green-confirmed-pass1.json`。同一缺陷的原生红灯记录为 `close-cache-red-retry.json`。
- 完整 pytest：`2979 passed, 21 skipped, 261 warnings`，203.279 秒，退出码 0；命令、环境及断言见 `full-final2-run.json`。
- Ruff 检查通过；命令与环境见 `ruff-final2-run.json`。
- 单独测试组均通过；人工拼接的非默认测试顺序曾卡在弱引用清理用例，完整项目收集顺序最终全量套件正常通过。已保留诊断记录，不将该非默认顺序当成全量失败。

## 4. 修改文件

- 新增：`pet/ffmpeg_params.py`、`pet/window_optional_services.py`、`scripts/verify_seeky8_memory.py`、`tests/test_seeky8_memory_lifecycle.py`、`tests/test_seeky8_thumbnail_lifecycle.py`。
- 修改：`pet/animation_thumbnail.py`、`pet/branding.py`、`pet/library.py`、`pet/webm_clip.py`、`pet/window.py`、`scripts/build_macos.sh`、`scripts/verify_dsr_package.py`、`scripts/verify_seeky_multi.py`、`docs/INDEX.md`。
- `pet/window.py` 最终 4620 行，低于项目 4666 行预算；缩略图服务拆入既有 service mixin。完整逐文件增删见最终 `git diff --stat`。

## 5. 交付状态与限制

按用户最新要求，优先完成打包、下载及 GitHub 分支上传。构建、包校验、ZIP 完整性检查和解包安装检查均通过。下载包：`/Users/ray/Downloads/seeky-pet-4.2.1.8-macOS-arm64.zip`，SHA-256 `10521c1ba2e927a97a016111b95fbe6353359e1ce44ca2668b5b9e35e6965ffa`，大小 1,553,295,691 字节。已从该 ZIP 安装到 `/Users/ray/Applications/seeky· pet.app`；版本 4.2.1.8，arm64，签名有效，二进制哈希与候选构建相同。安装后未自动启动 app。证据见 `package-build-run.json`、`package-verification.json`、`package-zip-verification.json`、`package-install-run.json`。候选长测仅覆盖约 251 秒且验证器拒绝，三轮 CPU 高负载复跑未开始，均不作为通过项。

按用户要求，旧 4.2.1.7 `/Users/ray/Applications/seeky· pet.app` 和 `/Users/ray/Downloads/seeky-pet-4.2.1.7-macOS-arm64.zip` 已永久删除，不留备份；删除证据见 `old-install-removal.json`。旧 app 删除前已正常退出。应用配置目录没有被删除；正常退出可能触发应用自身的常规保存流程。
