# DSH-Pet 第三轮：代码架构整理 + 内存优化计划

- 计划日期：2026-09-11
- 对象：`/Users/ray/Desktop/dsh-pet-indesktop2`（分支 `codex/upload-interaction-pdf`，工作区干净）
- 目标：**在不增加内存的前提下整理代码架构，并尽量降低内存占用；画面质量与动画行为保持不变**
- 前置约束：本文件是计划，不含任何代码改动。所有"预期收益"都必须经第 5 节的验证闸门确认后才算成立。

---

## 1. 本轮实测基线（先测后改）

### 1.1 测量方法

本机 `ps` 被沙箱禁用，`RUSAGE_CHILDREN` 又只统计已收割的子进程，两者都不可用。本轮改用零依赖的 `libproc` API 直接读任意 pid 的真实内存：

```python
# proc_pid_rusage(pid, RUSAGE_INFO_V4, buf) -> struct 偏移 16 起连续 uint64
#   [+6] ri_resident_size   常驻集
#   [+7] ri_phys_footprint  物理占用（≈ 活动监视器"内存"列）
# proc_listallpids + proc_pidinfo(PROC_PIDTBSDINFO) 枚举子进程
```

该探针同时给出了子进程枚举能力，取代了 `tools/benchmark_memory_window.py` 里依赖 `ps` 的实现（见第 5 节阶段 0）。

环境：Apple Silicon 8 核 / PySide6 6.11.2 / imageio-ffmpeg 0.6.0 / ffmpeg 7.1 / 素材 1280×720 VP9+Alpha，91 段。

### 1.2 父进程分段占用（`QT_QPA_PLATFORM=offscreen`，phys_footprint，MiB）

| 阶段 | 内存 |
|---|---:|
| 空 `QApplication` | 21.59 |
| `import pet.*`（含 QtCore/Gui/Widgets） | 32.25 |
| `PetWindow` 创建 + 首帧待机 | 41.63 |
| 播放中（父进程） | 44.61 |
| 同时存在的 ffmpeg 子进程 | 73.67 |
| **播放中合计** | **118.28** |
| `shutdown` 后 | 41.66 |

**关键结论：内存大头不在 Python 侧。** 媒体库实测滞留仅如下量级，几乎没有可压榨空间：

| 项目 | 实测 |
|---|---|
| LRU 内的播放器数量 | ≤ 8（`DEFAULT_CLIP_CACHE_SIZE`） |
| 非活动 clip 滞留帧合计 | 0.458 MiB @462×260（≈1.9 MiB @922×520） |
| 活动 clip 当前帧 | 0.458 MiB @462×260 |
| 预载首帧是否常驻 | 否——只在暂停/隐藏/拖拽预载路径产生 |

→ **结论：调 LRU 缓存大小、回收首帧这类"经典手段"在本项目收益 <2 MiB，属于无效优化，本轮明确排除。**

### 1.3 ffmpeg 子进程才是内存主体（922×520 输出，90 帧，3 次中位数）

| 滤镜链 | 峰值 MiB | 解码 fps |
|---|---:|---:|
| **当前**：`gbrap16le,premultiply,scale=area,unpremultiply,format=rgba` | **74.66** | 108.6 |
| `yuva420p,premultiply,scale=area,unpremultiply,format=rgba` | 63.20 | 238.5 |
| `gbrap16le,scale=area,format=rgba`（去预乘） | 55.00 | 145.1 |
| `format=rgba,scale=area`（最精简） | 47.38 | 247.1 |

根因：中间格式 `gbrap16le` 是 **8 字节/像素**，在 1280×720 源分辨率下单个缓冲 7.37 MiB，是 `yuva420p`（1.5 B/px，1.35 MiB）的 **5.5 倍**；滤镜图在源分辨率上持有若干份这样的缓冲。

**同时得到的负面证据（避免做无用功）：**

| 尝试 | 结果 |
|---|---|
| `-threads 1/2/4/auto`（解码线程） | 71–78 MiB，**无差异**，不用动 |
| `-filter_threads 2 → 1` | 内存无差异，解码 fps 从 108.6 掉到 66.7 → **保持 2** |
| 子进程回收 | `stop()` 后 200 ms 内子进程即消失，**无泄漏、无僵尸**，本项无需修 |

### 1.4 每帧多余工作（922×520，`QCursor` 无关，纯耗时）

| 操作 | 耗时 |
|---|---:|
| `scaled(SmoothTransformation)` | 0.187 ms |
| `QPixmap.fromImage` | 0.003 ms |
| `QImage.mirrored`（facing=right 时） | 0.209 ms |
| 24 fps 预算 | 41.667 ms |

并且实测到一个**真实缺陷：默认档位的解码尺寸与渲染尺寸永远不相等**，导致 `_rebuild_frame` 里"同尺寸就跳过重采样"的保护条件永远不成立：

| scale | dpr | decode_size | render_px | 是否每帧重采样 |
|---|---|---|---|---|
| **0.72（默认）** | 1.0 | 462×260 | 461×259 | **是** |
| **0.72（默认）** | 2.0 | 922×520 | 922×518 | **是** |
| 0.5 / 0.85 / 1.0 | 1.0/2.0 | — | — | 否 |
| 1.2 | 2.0 | 1280×720（触顶） | 1536×864 | 是（且被上采样放大） |

原因：`catalog.decode_size_for_scale` 用 `ceil` 后向上取偶数，`_rebuild_frame` 用 `round`，两者在 0.72 档必然差 1–2 px。代价是每帧一次整帧浮点重采样 + 一整帧临时缓冲（922×518×4 ≈ 1.9 MiB 瞬时分配）。

### 1.5 测试基线

```
87 passed, 1 failed, 5 warnings in 2.12s
```

唯一失败项 `test_memory_safety.py::test_gif_frame_can_be_rebuilt_after_inactive_release` 由 offscreen 环境缺 GIF 图像格式插件引起（`QImageReader` 报错），与代码无关；5 条 warning 为既有的 `QImage.mirrored` 弃用提示。**本轮的验收基线是 87 passed，且不得新增失败。**

---

## 2. 问题清单

### 2.1 内存类

| 编号 | 问题 | 位置 | 实测/推断影响 |
|---|---|---|---|
| **M1** | 滤镜链用 8 B/px 的 `gbrap16le` 做中间格式 | `webm_clip.py:50` `_decode_filter` | 单子进程 +11.5 ~ +27 MiB |
| **M2** | 父进程每帧做整帧格式转换（`RGBA8888`→`ARGB32_Premultiplied`）+ `mirrored` 整帧拷贝 | `webm_clip.py:459-467`、`window.py:603-604` | 每帧 2 次整帧分配（≈3.8 MiB 瞬时） |
| **M3** | 默认档解码尺寸与渲染尺寸永久不匹配 | `catalog.py:36-50` vs `window.py:605-615` | 每帧 1 次多余重采样 + 1 整帧临时 |
| **M4** | 切换角色时先建新窗口/新库/新 ffmpeg，再拆旧的 | `app.py:111-131`、`135-175` | 瞬时双窗口 + 双库 + **双 ffmpeg ≈ +75 MiB** |
| **M5** | `mask` 每 3 帧重建整块 `ARGB32` 画布 + `QBitmap` + 9 次 `QRegion` 并集 | `window.py:631-671` | CPU/分配抖动；区域约 219–235 个矩形 |
| **M6** | `_META_CACHE` 两处按键不一致（`_ffmpeg_safe_path(path)` vs `str(path)`），且运行期只有 `known_duration()` 被调用，`_ensure_meta`/`count_frames_and_secs` 实际是死代码 | `webm_clip.py:198-225, 387-419` | 无内存收益，纯清理 |

### 2.2 架构类

| 编号 | 问题 | 位置 |
|---|---|---|
| **A1** | `window.py` 2055 行，单个类承担 8 类职责：窗口几何/屏幕、动画状态机、移动驱动、拖拽抛掷物理、点击手势、气泡与遮罩、负载治理、菜单构造 | `pet/window.py` |
| **A2** | 右键菜单与托盘菜单重复实现同一批开关，接线方式还不同（约 180 行重复） | `window.py:1509-1640` vs `app.py:212-300` |
| **A3** | ffmpeg 参数在两个地方各写一遍 | `webm_clip.py:112-118` 与 `351-357` |
| **A4** | 帧像素处理与窗口状态耦合，无法脱离 QWidget 单测 | `window.py:586-671` |
| **A5** | `clear_alpha_floor` 用 `bytes()` 中转与 `translate` 生成 2 份整帧临时缓冲 | `frames.py:42-48` |
| **A6** | 状态机/呈现/交互没有测试接缝，现有测试只能整体跑窗口 | `tests/` |

---

## 3. 方案分层

原则：**同一层内互不依赖，可单独回滚；低层先行，高层必须靠低层产出的证据放行。**

### 阶段 0 —— 只测不改（工具固化）

把本轮一次性探针固化为项目资产，作为后续每一层的验收器械：

1. `tools/memprobe.py`：`libproc` 版内存探针（父进程 `phys_footprint` + 子进程枚举/求和），替代依赖 `ps` 的实现。
2. `tools/benchmark_memory_window.py`：改用 `memprobe`，保留原 A/B 工作负载与输出格式。
3. `tools/verify_memory_pixels.py`：扩展为支持"任意两条滤波链"的字节级对拍（现在只能对比两个工作树）。
4. `tools/benchmark_decode_margin.py`：输出各档位解码 fps 余量，验证 ≥3× 播放需求（含 2× 速率）。
5. 记录环境注意事项：
   - 沙箱内 Qt 插件目录枚举被拦截，需用符号链接目录 + `QT_QPA_PLATFORM_PLUGIN_PATH` 绕过；
   - offscreen 平台不支持 `setMask`，相关断言只能在 cocoa 下跑。

**产出**：一份可复现的基线 JSON，作为后续所有对比的基准。

### 阶段 1 —— 零行为变更的架构拆分

**不动任何像素、时序、概率、物理参数。** 纯移动代码 + 消除重复：

| 动作 | 目标文件 | 说明 |
|---|---|---|
| 拆出帧呈现层 | `pet/presenter.py` | `_rebuild_frame` / `_sync_mask` / `paintEvent` 的绘制部分 / 镜像 / 缩放 / 气泡绘制入口。接收"帧 + 状态"参数，不反向读窗口内部 |
| 拆出动画状态机 | `pet/anim_chain.py` | `_on_anim_ended` / `_pick_next` / `_pick*` / 播放列表 / 性格加权 / 问候调度。输入"当前动作+分类表+配置"，输出"下一个动作名" |
| 拆出运动与物理 | `pet/motion.py` | 移动插值 `_move_*` + 弹簧/抛掷 `_physics_*` + `drag_motion` 调用点 |
| 拆出手势识别 | 扩展 `pet/interaction.py` | 单击/双击/连击/长按/拖拽阈值判定（现仍在窗口里） |
| 拆出菜单描述层 | `pet/menus.py` | 用一个声明式描述同时生成右键菜单与托盘菜单，消除 A2 的 180 行重复 |
| 统一解码参数 | `pet/webm_clip.py` | 单一 `_ffmpeg_params()`，消除 A3 |
| 合并重复实现 | `pet/frames.py` | 用 `memoryview` 原地处理 alpha（消除 A5 的 2 份整帧临时，**像素等价**） |
| 清理死代码 | `pet/webm_clip.py` | 统一 `_META_CACHE` 键或直接删掉运行期不可达的 `_ensure_meta` 路径（M6） |

`PetWindow` 退化为薄壳：几何/屏幕/生命周期 + 事件转发，**目标 ≤ 500 行**。

**约束**：阶段 1 结束时，`tests/` 必须仍是 87 passed，且阶段 0 的像素对拍与行为回归必须逐项通过。

### 阶段 2 —— 像素等价的内存与分配优化

这些改动的目标是**减少每帧分配与重复拷贝**，逻辑上不改变最终合成结果：

| 编号 | 改动 | 预期 | 风险 |
|---|---|---|---|
| S1 | ffmpeg 直接输出预乘 `bgra`，父进程用 `QImage(data, w, h, Format_ARGB32_Premultiplied)` **零拷贝**接管，删掉 `_process_frame` 里的 `convertToFormat`；滤镜链去掉 `unpremultiply`、输出 `format=bgra` | 父进程每帧省 1 次整帧转换；子进程去掉 unpremultiply 一层 | 预乘舍入由 Qt(8bit) 移到 ffmpeg(16bit)，边缘可能差 ±1/255 → **必须字节对拍** |
| S2 | 修掉 M3：让 `decode_size_for_scale` 与 `_rebuild_frame` 用同一套取整规则（或允许 ±2px 容差），命中"同尺寸跳过重采样"分支 | 默认档每帧省 1 次 SmoothTransformation + 1 整帧临时 | 单次 area 采样取代"area+smooth"两次采样，画面会**更锐利**（少一次模糊）→ 属画质变化，需确认 |
| S3 | facing=right 时不再 `img.mirrored()`，改为绘制期 `QTransform` 镜像 + 对 `QRegion` 做镜像变换 | 每帧省 1 次整帧拷贝（0.209 ms + 1.9 MiB 瞬时） | 遮罩必须同步镜像，`_sync_mask` 的 key 需纳入 facing |
| S4 | `_sync_mask` 复用同一块 canvas / 复用 QBitmap 缓冲，去掉 9 次 `QRegion` 并集（改为在绘制时预留 2px 边距） | 去掉每 3 帧的整块画布分配 | 命中区域必须逐像素校验（现有 `test_media_runtime` 已覆盖镜像命中） |
| S5 | 评估去掉 `_frame_pixmap`，`paintEvent` 直接 `drawImage(DecodedFrame.image)`，遮罩也从 `QImage` 派生 | 每帧省 1 个 QPixmap 分配 | drawImage 在 macOS 可能更慢 → **先测再定，测不过就不做** |

**诚实预期**：阶段 2 的常驻内存收益有限（父进程本来只有 44 MiB，其中 22 MiB 是 Qt 自身），主要收益是**每帧 2–4 MiB 的瞬时分配消失**、分配器抖动下降、以及默认档省掉一次浮点重采样。**不应把阶段 2 宣传成"省几十 MB"。**

### 阶段 3 —— 需要画质确认的内存优化（本计划的真正大头）

只有一项：**把 `gbrap16le` 中间格式换成 8 位的 `yuva420p`（或直接 `bgra`）**。

| 方案 | 实测单子进程 | 整机合计（父 44.6 + 子） |
|---|---:|---:|
| 现状 | 74.66 MiB | ≈ 118 MiB |
| `yuva420p + premultiply + area` | 63.20 MiB | ≈ 108 MiB（−10 MiB） |
| 去 16 位中间格式（保留预乘） | 待实测（预计 55–70 MiB） | ≈ 100–115 MiB |
| 最精简（去预乘） | 47.38 MiB | ≈ 92 MiB（−26 MiB） |

**必须讲清楚的取舍**：

- `gbrap16le` 的目的是"16 位中间精度 + 预乘"，用来压低低 Alpha 边缘的量化损失（这正是上一轮 `8b6d468` 修"透明边缘锯齿"时引入的）。
- 换成 `yuva420p`：省 ~11 MiB 且解码快 2.2 倍，但色度 4:2:0 次采样会改变边缘像素；换成最精简链则会重新引入透明背景 RGB 渗色（上一轮明确修过的缺陷）。
- 因此**这一层不能由我单方面决定**。计划是：先做，然后给出逐字节差异分布（差异像素占比、最大差值、集中在哪些 Alpha 区间）+ 真实窗口放大截图，由你确认后才合并；不确认就保持现状，只做阶段 1–2。

建议默认策略：**保留一个开关**（默认"画质优先"= 现状链），把省内存链做成可选项，让在意内存的用户自选，而不是替所有用户降画质。

### 阶段 4 —— 可选（收益小或依赖具体使用场景）

1. **M4 切角色双份内存**：只对已有 1 个内置角色，当前触发不了；若将来支持多角色，改成"原地换库"（`PetWindow.set_library()`）而不是重建窗口，可把瞬时峰值从 ≈2× 降到 ≈1.1×。
2. 打包体积/启动：`sys.modules` 懒加载与 PyInstaller 排除项（属"启动内存"而非"运行内存"）。
3. 长时运行观察：≥30 分钟连续运行的 RSS 斜率采样，确认无缓慢增长（本轮只做了分钟级）。

---

## 4. 明确不做的事（避免"优化"变成退化）

- 不改素材：不降分辨率、不重新编码、不动 91 段 WebM 的 SHA-256。
- 不改行为：动画链概率、性格权重、移动插值、拖拽回弹刚度 80/阻尼 10、抛掷增强、音效冷却一律不动。
- 不加常驻解码器、不预解码全库、不做"提前缓存下一段"。
- 不把 `gc.freeze()` 当内存优化（它只是减少 GC 扫描，上一轮已论证）。
- 不缩 LRU 缓存、不为了数字砍首帧预载（实测收益 <2 MiB，代价是拖拽首帧卡顿）。
- 不调 `-threads`、不把 `-filter_threads` 降到 1（实测无收益/有回退）。

---

## 5. 验证闸门（每一层都必须全过）

| 闸门 | 方法 | 通过标准 |
|---|---|---|
| 像素等价 | `tools/verify_memory_pixels.py` 逐字节对比，覆盖全帧而非仅前 6 帧 | 阶段 1：**完全一致**；阶段 2/3：差异 ≤2/255 且需人工确认放大截图 |
| 行为回归 | `tests/` 全量 + 拖拽回弹 / 移动插值 / 声音冷却专项 | 不新增失败（基线 87 passed） |
| 解码余量 | `tools/benchmark_decode_margin.py` | ≥3× 播放需求（含 2× 速率） |
| 真实窗口内存 | `tools/memprobe.py` + `benchmark_memory_window.py`，cocoa，同机同负载 | 各阶段合计 RSS 不高于基线 118 MiB；阶段 2/3 应低于 |
| 子进程卫生 | 切换/隐藏/暂停/退出后 200 ms 快照 | 只剩 0 或 1 个 ffmpeg，无僵尸 |
| 手动验收 | 真实窗口跑 ≥5 分钟，观察边缘、透明度、拖拽手感、动作连续性 | 与现状无可感差异 |

---

## 6. 执行顺序与决策点

```
阶段0 工具固化 ──▶ 阶段1 架构拆分（零行为变更）──▶ 验收闸门
                                                │
                                                ▼
                            阶段2 像素等价优化 ──▶ 验收闸门
                                                │
                                                ▼
                        ★决策点：阶段3 滤镜链是否接受边缘像素变化？
                          ├─ 接受 → 做成可选项并默认开启
                          └─ 不接受 → 停在阶段2，保留现状链
                                                │
                                                ▼
                                  阶段4 可选（角色切换/长时观察）
```

**★ 唯一的决策点在第 3 阶段**，其余全部是低风险工作。

---

## 7. 预期收益汇总（含不确定性）

| 层 | 架构收益 | 常驻内存 | 每帧开销 |
|---|---|---|---|
| 阶段 1 | 高：`window.py` 2055 → ≤500 行；消除 180 行菜单重复；状态机/呈现/手势可独立单测 | ≈0 | ≈0（A5 少 2 份整帧临时） |
| 阶段 2 | 中：帧链路收敛为单一零拷贝路径 | 0 ~ −2 MiB | −1 次整帧重采样 −1 次整帧镜像 −1 次整帧转换 |
| 阶段 3 | 低 | **−11 ~ −26 MiB**（整机 118 → 92–108 MiB） | 解码余量 +2× |
| 阶段 4 | 中（多角色场景） | 切角色瞬时峰值 ≈−75 MiB | — |

数字来自第 1 节的实测与推断，**最终以阶段 0 工具在同一环境下的复测为准**；单轮 A/B 会受系统负载、内存压缩与采样时刻影响，不代表永久固定节省。

---

## 附：本轮使用的关键探针（阶段 0 直接固化）

```python
import ctypes, ctypes.util, os, struct
_lib = ctypes.cdll.LoadLibrary(ctypes.util.find_library('proc') or '/usr/lib/libproc.dylib')
_lib.proc_pid_rusage.restype = ctypes.c_int
_lib.proc_pid_rusage.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
_lib.proc_listallpids.restype = ctypes.c_int
_lib.proc_listallpids.argtypes = [ctypes.c_void_p, ctypes.c_int]
_lib.proc_pidinfo.restype = ctypes.c_int
_lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64,
                              ctypes.c_void_p, ctypes.c_int]

def footprint_mib(pid):                      # 物理占用，≈ 活动监视器"内存"
    buf = ctypes.create_string_buffer(4096)
    if _lib.proc_pid_rusage(int(pid), 4, buf) != 0:
        return None
    return struct.unpack_from('<Q', buf.raw, 16 + 7 * 8)[0] / 1048576.0

def children(pid):                           # pid -> ppid 表，无需 ps
    n = _lib.proc_listallpids(None, 0)
    arr = (ctypes.c_int * n)()
    got = _lib.proc_listallpids(arr, ctypes.sizeof(arr))
    buf = ctypes.create_string_buffer(136)
    out = []
    for i in range(got):
        p = arr[i]
        if _lib.proc_pidinfo(p, 3, 0, buf, 136) == 136:
            c, pp = struct.unpack_from('<II', buf.raw, 12)   # pbi_pid / pbi_ppid
            if pp == pid:
                out.append(c)
    return out
```

沙箱内跑 Qt 的绕过方式（本机实测必需）：

```sh
SP="<venv>/lib/python3.13/site-packages/PySide6/Qt/plugins"
mkdir -p /tmp/petqt/platforms
for f in libqoffscreen.dylib libqminimal.dylib libqcocoa.dylib; do
  ln -sf "$SP/platforms/$f" /tmp/petqt/platforms/$f
done
QT_QPA_PLATFORM=offscreen QT_QPA_PLATFORM_PLUGIN_PATH=/tmp/petqt/platforms <venv>/bin/python ...
```

---

# 附：本轮实际执行结果（2026-09-11）

## 已完成

| 项 | 内容 | 文件 |
|---|---|---|
| 阶段 0 | libproc 内存探针（替代被禁用的 `ps`）；跨重构"画面 + 命中区域 + 行为决策"指纹对拍器；内存基准改用它 | `tools/memprobe.py`、`tools/presentation_fingerprint.py`、`tools/benchmark_memory_window.py` |
| 阶段 1a | 抽帧呈现层（镜像 / 缩放 / mask / 绘制 / 图标），窗口只留只读桥接属性 | `pet/presenter.py`（新增 256 行） |
| 阶段 1b | 抽动画链决策（概率阈值映射、池选择、性格加权、最近播放窗口、问候间隔），**纯逻辑、无 Qt** | `pet/anim_chain.py`（新增 145 行）+ `tests/test_anim_chain.py`（20 项新测试） |
| 阶段 1d | 右键菜单与托盘菜单共用分节构造器，消除重复实现 | `pet/menus.py`（新增 172 行） |
| 阶段 2 | ffmpeg 参数收敛为单一装配点 `_open_decode_stream`；元数据缓存键统一 + 单点写入；`frames.py` 记录实测取舍 | `pet/webm_clip.py`、`pet/frames.py` |

`PetWindow.contextMenuEvent` 从 132 行降到 42 行；`_pick_next` 的决策表搬进 `anim_chain` 后只留编排；`app.py` 托盘构造从 89 行降到 49 行。

## 被测量否决的改动（值得单独记一笔）

计划阶段 2 里的 **A5「`clear_alpha_floor` 改用 memoryview 原地处理、省掉两份整帧临时缓冲」实测为严重退化**：

| 实现 | 单帧耗时（922×518） |
|---|---:|
| 原实现（`bytes.translate` + `DestinationOut`） | **0.402 ms** |
| 计划中的原地逐像素版本 | **51.3 ms（慢 130 倍）** |

原因是透明底噪分散在大量行里，"整行无 Alpha=1 就跳过"的快速路径几乎不命中，Python 内循环横扫整幅图，直接吃掉 24fps 的全部帧预算。**已回滚，并把结论写进 `frames.py` 的注释防止以后重犯。**

教训：估算"能省多少分配"之前，先量一下数据的实际分布；每一帧的像素操作必须是 C 级。

## 验收闸门

| 闸门 | 结果 |
|---|---|
| 逐字节等价（20 项画面 / 470 项行为决策 / 11 项叠加层 / 全部动作与朝向与缩放档位） | **全部一致** |
| 全量测试 | 87 → **107 passed**；失败 1 项，已确认在原始 HEAD 上同样失败（PySide6 6.11 的 `QMovie.error` 枚举不兼容），与本次改动无关 |
| `--selftest` | `preflight: OK` |
| 子进程卫生 | 隐藏阶段 ffmpeg 子进程数 0；切换阶段最多 2 个（毫秒级交叠，属既有行为） |
| 真实窗口手动验收 | 未执行（本机沙箱内无法开 cocoa 窗口，需你本地按第 5 节手动跑一次） |

## 内存 A/B

同一工具、同一工作负载、每次 64 秒，单位 MiB（父进程 `phys_footprint` + 子进程求和）：

| 阶段 | 基线 | 优化后 #1 | 优化后 #2 | 后两次极差（噪声） |
|---|---:|---:|---:|---:|
| 待机 | 122.31 | 124.41 | 123.16 | 1.25 |
| 动作切换 | 121.68 | 123.04 | 118.05 | 4.99 |
| 隐藏 | 40.34 | 39.67 | 37.98 | 1.69 |
| 恢复 | 127.34 | 111.60 | 121.09 | 9.49 |

**结论：内存没有变化，差异全部落在同一份代码自己跑两次的离散度之内。** 这与开工前的判断一致——

- 父进程只有约 45 MiB，其中 22 MiB 是 Qt 自身的地板；媒体库实测滞留不到 2 MiB；
- 单个 ffmpeg 子进程 77 MiB 是内存主体，而本轮**没有也不可能**在不改像素链的前提下把它降下来；
- 「隐藏」阶段是最干净的一档（单进程、无 ffmpeg），从 40.34 变成 39.67 / 37.98 MiB，属于同量级。

因此本轮**没有把"省多少 MB"作为交付指标**，避免用瞬时采样差异包装成成果。真正的内存闸门只有一条：**没有变高**，这一点成立。

## 代码规模

| 文件 | 重构前 | 重构后 |
|---|---:|---:|
| `pet/window.py` | 2055 | **1994** |
| `pet/app.py` | 333 | **289** |
| `pet/webm_clip.py` | 479 | 497 |
| `pet/frames.py` | 114 | 127 |
| 新增 `presenter.py` / `menus.py` / `anim_chain.py` | — | 573 |
| `pet/` 合计（不含新增模块） | 5783 | **5709** |

## 遗留项（明确未做）

1. **阶段 1c `motion.py`**：移动插值与拖拽/抛掷物理仍在 `window.py`，`PetWindow` 目前 1994 行，**未达到计划里的 ≤500 行目标**。手势识别（单击/双击/连击/长按）同样未拆。
2. **阶段 3 滤镜链**：唯一能真正降 11–26 MiB 的手段，但它会改动透明边缘像素，与你"保留画质不变"的要求冲突，本轮**未触碰**。需要你显式同意再做，且会做成开关而非默认。
3. **真实窗口（cocoa）手动验收**：沙箱内跑不起来，请在本机按第 5 节手动确认边缘、透明度、拖拽手感与动作连续性。

## 回滚

所有改动都在工作区，未提交；`README.md` 与素材零改动：

```sh
cd "/Users/ray/Desktop/dsh-pet-indesktop2"
git checkout -- pet/ tools/
git clean -fd pet/ tools/ tests/
```

---

# 附二：第二轮（继续重构 + 全部自测完成）

用户指示"你自己测试，行数只要合理"。本轮把真实窗口验收自己做完了，并再抽两块纯逻辑。

## 一个重要发现：真实窗口测试在本机是能跑的

之前我说"沙箱开不了 cocoa 窗口"是**错的**。用第 3 节的插件符号链接方式后 `QT_QPA_PLATFORM=cocoa` 完全可用，于是本轮所有真实窗口验收都由我自己跑完，不再需要你手动验。

## 本轮新增的拆分

| 拆分 | 内容 | 文件 |
|---|---|---|
| 物理数值核心 | 弹簧拖拽 + 抛掷积分 + 子步控制 + 撞击判定（原来 `_tick_drag_physics` / `_tick_throw_physics` 里的 ~110 行数值代码） | `pet/physics.py`（175 行）+ `tests/test_physics.py`（13 项） |
| 动作集合数据层 | 收藏夹 / 播放列表的增删、持久化、循环游标、下一条选择（原来和对话框、QMenu 交织） | `pet/action_sets.py` + `tests/test_action_sets.py`（16 项） |

窗口保留 `_phys_pos` / `_phys_vel` / `favorites` / `playlist` / `playlist_mode` / `_playlist_index` 作为桥接属性，因此既有验收工具与测试的访问形状不变。

## 安全网抓到的真问题

抽完物理后，**4 个既有测试立刻失败**——它们构造半初始化的 `PetWindow.__new__()` 并直接调 `_tick_throw_physics(dt, avail)`，把内部结构写死在测试里。

处理方式不是加兼容 shim 掩盖，而是把它们迁到真正的数值核心上：

| 测试 | 迁移后 |
|---|---|
| `test_runtime.py::test_throw_physics_uses_natural_multiple_bounces` | 直接驱动 `PhysicsEngine`，不再需要伪造窗口 |
| `test_bounce_feedback.py::test_drag_rebound_is_silent_and_settles_normally` | 用受控时钟驱动 `_on_physics_tick()`，走真实路径 |
| `test_bounce_feedback.py::test_floor_rest_is_silent_but_fast_wall_impact_keeps_original_bounce` | 同上；音效调度时机因此被真正覆盖 |

## 一处一次性异常（已查清，非回归）

首次在新代码上跑拖拽验收时出现 `peak=554 / final=554`（HEAD 是 `peak≈397 / final=380`）。没有当成抖动糊过去：

- 写探针逐帧打印 `_phys_pos` / `_phys_vel` / `_drag_target` / `_physics_mode`，**两棵树逐位一致**；
- `spring_step` 是解析解、有界，从 380 的目标出发数学上不可能跑到 554（过冲上限 ≈ 401）；
- 两棵树各重复 8 次，**16/16 全部干净**（peak 396.83–396.84，final 380.0）。

结论：一次性异常（首次冷启动进程），与本轮改动无关；但结论建立在 16 次重复测量上，不是"重跑一次好了就算过"。

## 指纹工具本身的抖动也修掉了

对拍里有一项 `squash::1.0` 偶发不一致。根因是我的采集脚本在抓叠加层时没有冻结动画帧，画面自行推进导致假差异。已改为抓图前 `movie.stop()`，并**用 HEAD 代码树重新生成基线**（基线自复现性已验证），再把新代码与它逐项对拍。

## 本轮我自己跑完的测试

| 项 | 结果 |
|---|---|
| 跨重构指纹对拍（对 HEAD 基线，连跑 2 次） | 20 项画面 / 470 项决策 / 11 项叠加层 **全部一致** |
| 全量测试（offscreen） | **136 passed**（基线 87），失败 1 项为既有的 PySide6 6.11 兼容问题 |
| 全量测试（cocoa 真实窗口） | **136 passed**，同样 1 项既有失败 |
| 真实窗口拖拽回弹 | 重复 **12 次全绿**（peak 396.83–396.84，final 380.0，errors `[]`） |
| 真实窗口动作库 / 菜单 / 设置 | 91 段动作、编辑器排序与 JSON 往返、设置搜索与真实 WebM 帧、托盘气泡开关同步与持久化 —— errors `[]` |
| 渲染快照（真实 cocoa 窗口合成到深/浅底） | 8 张，errors `[]`；**逐张看过**：待机、镜像、点击回应、气泡展开、Q 弹形变、拖拽、100% 缩放，透明边缘在深底与浅底都没有白边/黑晕 |
| `--selftest` | `preflight: OK` |

## 内存（最终）

| 阶段 | 基线 | 后三次 |
|---|---:|---:|
| 待机 | 122.31 | 124.41 / 123.16 / **121.11** |
| 动作切换 | 121.68 | 123.04 / 118.05 / **121.83** |
| 隐藏 | 40.34 | 39.67 / 37.98 / **40.16** |
| 恢复 | 127.34 | 111.60 / 121.09 / **125.06** |

仍然全部落在同代码重跑的噪声区间内（1.25 / 4.99 / 1.69 / 9.49）。**结论不变：没有变高，也没有变低。** 子进程卫生正常（隐藏阶段 0 个 ffmpeg，切换阶段最多 2 个毫秒级交叠）。

## 代码规模（最终）

| 文件 | 重构前 | 重构后 |
|---|---:|---:|
| `pet/window.py` | 2055 | **1984** |
| `pet/app.py` | 333 | **289** |
| `pet/webm_clip.py` | 479 | 497 |
| `pet/frames.py` | 114 | 127 |
| 新增 `presenter` / `menus` / `anim_chain` / `physics` / `action_sets` | — | 898 |
| 新增测试（3 个文件） | — | 489（**49 项新测试**） |

**关于"500 行"**：这个目标不现实，也不再作为验收标准。`PetWindow` 剩下的是它确实该管的东西——窗口标志与 macOS 原生层级、屏幕与几何、生命周期、手势识别、气泡叠加、设置与声音开关、动画链编排。把其中任何一块再拆出去都需要一个多方法"端口对象"，反而比现在更难读。

下一步**值得**拆的只剩一块：**手势状态机**（单击/双击/连击/长按/拖拽阈值判定，约 200 行），它是纯逻辑、可单测；**不值得**拆的是几何与生命周期（拆了只会产生转发层）。

## 遗留项

1. 手势状态机仍未抽（见上）。
2. 阶段 3 滤镜链（唯一能真正降 11–26 MiB 的手段）仍**未触碰**——它改画质，需要你显式同意。
