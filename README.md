# dsh-pet-indesktop

## 下载

无需从源码构建，直接到 [Releases](https://github.com/MerZlin/dsh-pet-indesktop/releases)
页面下载对应系统的安装包：

| 你的系统                        | 安装包                              | 说明                                                                  |
| ------------------------------- | ----------------------------------- | --------------------------------------------------------------------- |
| Windows（WebM 版）             | `dsh-pet-standalone-webm.exe`       | 包体小、画质高；首次启动解压较慢，播放加速效果不明显                  |
| Windows（GIF 版）               | `dsh-pet-standalone-gif.exe`        | 启动快、播放加速效果好；缺点是包体较大                                |
| macOS（Apple Silicon / M 系列） | `DSH-Pet-macos-arm64-1440p-master-adaptive.zip` | 解压得 `DSH-Pet.app`，首次打开需放行（见下方「macOS」章节） |
| macOS（Intel）                  | —                                   | 暂无安装包，请按「macOS」章节源码运行                                 |

> 文件名以 Release 页面实际发布为准。

## 本地 macOS 成品

当前签名后的 Apple Silicon 成品安装在 `/Applications/DSH-Pet.app`，压缩包位于
`releases/DSH-Pet-macos-arm64-1440p-master-adaptive.zip`。2560×1440 母版素材包为
`releases/dsh-pet-superres-1440p-transparent-webm-91-actions.zip`。应用使用白鲸 +
深蓝渐变圆角图标，双击 `.app` 即可运行。

本轮修复后的新包位于
`releases/dsh-pet-indesktop-macos-arm64-20260824.zip`（Apple Silicon，约 380 MB）。
解压后可先运行 `dsh-pet-indesktop-webm-20260824 --selftest` 做无 GUI 自检。

透明视频默认清理 VP9 常见的 Alpha=1 底噪，不改动真实半透明边缘；可在桌宠右键菜单或 macOS
状态栏菜单的「画面调整 → 清理透明底噪（Alpha=1）」中随时关闭，设置会自动保存。

高画质素材链包含完整 91 段 2560×1440 透明 WebM（24fps），由原作 640×360
Alpha 素材使用 Real-ESRGAN AnimeVideo-v3 4×超分生成。2560×1440 作为母版
独立保留；App 使用由母版 Lanczos 下采样的 1280×720 透明运行代理，默认 462px
档再按 Retina 需求解码到 922×520。屏幕可见细节不减少，同时避免每帧解码完整
1440p。原始素材与旧 1080p 版本也保存在独立备份目录，不会被覆盖。

超分素材可用下列命令做逐文件复核（只验证，不生成）：

```sh
./.venv/bin/python tools/superres_webm_assets.py \
  --input-root backups/shenshen-webm-original-640-91 \
  --output-root backups/shenshen-webm-superres-1440-master-91 \
  --scale 4 --verify-only
```

运行代理复核：

```sh
./.venv/bin/python tools/build_runtime_webm_assets.py \
  --input-root backups/shenshen-webm-superres-1440-master-91 \
  --output-root assets/characters/shenshen/videos --verify-only
```

> **声明与致谢**：本项目改自、源于 [dsh-pet](https://github.com/PC2005-cloud/dsh-pet)。
> 桌宠的动画素材、动画链行为模型、交互设计均来自原项目，特此声明并感谢原作者的贡献。

把 [dsh-pet](https://github.com/PC2005-cloud/dsh-pet) 插件里的桌宠，改造成一个
**跨平台的独立桌面宠物**软件（支持 **Windows** 与 **macOS**）—— 不依赖 DSH 运行时，
用 Python + PySide6 实现，双击即跑，内置 91 段母版派生的 1280×720 透明运行动画（24fps）。

当前提供两个 Windows 版本：

- **WebM 版**：使用 2560×1440 母版派生的透明运行代理，并按实际显示尺寸有界解码。
- **GIF 版**：使用 GIF/QMovie 播放，启动快、播放加速效果好，缺点是包体较大。

两个版本都支持多角色、外部扩展、切换角色、播放速率、鼠标穿透、拖动物理等功能。

Windows 用户见下方「快速开始 / 打包为 exe」，macOS 用户见「macOS」章节。

## 版本对比

| 版本     | 启动速度 | 播放加速效果 | 包体大小 | 适用场景                         |
| -------- | -------- | ------------ | -------- | -------------------------------- |
| WebM 版  | 较快     | 不明显       | App 约 460MB / ZIP 约 381MB | 追求高画质、透明边缘 |
| GIF 版   | 快       | 明显         | 约 450MB | 追求启动快、播放加速效果明显     |

> ⚠️ **注意**：GIF 版当前**不建议切换到 webm 素材角色**，切换后可能出现卡死。
> GIF 版请使用 GIF 素材；需要播放 webm 角色请使用 WebM 版。

## 近期优化

- 2560×1440 透明超分母版 + 1280×720 运行代理，默认档仅解码到 922×520
- 解码队列限制为 2 帧并采用背压，不丢帧、不让 ffmpeg 提前解完整段动画
- 媒体库先建立轻量动作索引，播放器按需创建；启动只预热移动动作，新增角色/动作无需改播放器层
- 系统持续高负载时降低待机速度、主动动作频率和命中 mask 刷新率；画面帧率不变
- 从托盘隐藏桌宠时暂停媒体解码，重新显示时自动恢复
- 性能策略、素材事实来源和媒体清理拆分，角色切换/退出统一停止后台 reader
- 支持 GIF / WebM 混合素材，GIF 版也能切换并播放 webm 角色
- 多开桌宠时不再互相清理缓存导致卡住
- 拖拽切换动画不再卡顿
- 点击 Q 弹反馈，连续点击可打断动画
- 播放速率调节（1.0x ~ 2.0x）
- 鼠标穿透开关
- 拖动物理效果（惯性、离心、抛出、重力、反弹衰减、地面摩擦）
- 转向动画开始不再出现突兀镜像

## 相关优化项目

[ianlike-ui/dsh-pet-standalone](https://github.com/ianlike-ui/dsh-pet-standalone)

这是其他开发者基于本项目做的优化实现，可能在播放性能、打包体积、多角色支持或使用体验等方面进行了改进。  
如果你希望体验社区优化版，可以前往该仓库查看说明和最新成果。

## 特性

- **高画质透明播放**：内置 1440p 母版派生的 VP9 Alpha 运行代理，保留透明边缘
- **动画链**：每个动画播完按概率选下一个 —— 30% 待机 / 10% 转向 / 40% 随机动作 / 20% 移动，永不停止
- **多形象支持**：支持用户通过外部目录添加自定义角色
- **角色热切换**：右键桌宠或托盘菜单可随时切换形象，无需重启
- **屏幕漫游**：朝面向方向行走，先检查屏幕空间、不走出屏幕（移动动画前后各 2s 准备/收尾，位置由代码驱动）
- **左右朝向**：转向动画播完翻转朝向，所有动画支持水平镜像
- **点击回应**：点击宠物随机播放当前角色配置的回应动画（链上非待机动画播放中不打断）
- **点击 Q 弹**：点击时立即产生“变矮再复原”的挤压回弹反馈；连续点击可打断当前动画并重复触发 Q 弹
- **多级点击回应**：单击、双击、长按、快速连续点击会分流到不同回应动作；双击/长按/连点可触发尖叫鸭音效
- **鼠标靠近反馈**：光标进入角色附近时，角色会自动朝向鼠标
- **主动问候**：默认每隔一段时间随机播放一次挥手问候，可从「互动反馈」关闭
- **拖拽**：按住拖动超过 5px 判定为拖拽，宠物播放"悬空反馈"动画跟手，松手停在原地
- **边缘反馈**：拖到屏幕边缘会短暂压扁并反弹离开；当前角色没有独立“趴下”素材，因此先用 Q 弹代替
- **透明穿透**：窗口逐帧按人物 alpha 生成 mask，透明区域鼠标直接穿透到下层窗口
- **右键菜单**：手动播放待机/转向/移动/点击回应/随机动作、切换角色、回到右下角、窗口置顶、不移动、开机自启、4 档大小、退出
- **系统托盘**：显示/隐藏、切换角色、开机自启、退出；位置/朝向/大小/置顶自动持久化
- **开机自启**：Windows 写 HKCU 注册表 Run 键 / macOS 写 LaunchAgents（均无需管理员权限），可随时开关
- **播放速率调节**：右键菜单可调 1.0x ~ 2.0x 动画播放速度
- **鼠标穿透**：托盘菜单可开启鼠标穿透，开启后鼠标点击会穿透桌宠到下层窗口
- **拖动物理**：可开关的拖拽物理效果，松手会抛出、带重力与反弹衰减；拖拽过程中有惯性/离心感
- **动作收藏夹 / 播放列表**：91 段动画可收藏、编辑播放列表，并选择循环或随机播放
- **性格模式**：高冷、安静、活泼、调皮、温柔会改变待机、动作、移动和主动问候概率；每种性格会把最符合的动作前 40% 设为高频动作
- **全局快捷键**：`⌃⌥⌘H/P/R/M/D` 分别控制显示隐藏、暂停、随机动作、鼠标穿透和尖叫鸭

## 自定义角色教程

你可以通过两种方式使用自定义形象：

1. **随 exe 打包**：把形象放到项目源码的 `assets/characters/<角色ID>/videos/`，重新打包 exe。
2. **用户本地外部扩展**：不需要重新打包，直接在 exe 同目录或用户数据目录放置形象文件夹。

### 方法一：随 exe 打包

在项目源码中创建：

```text
assets/characters/<角色ID>/videos/
├── idle/
├── turn/
├── move/
├── click/
├── drag/
└── random/
```

把对应分类的 `.webm` 放进去，然后重新执行打包命令即可。

### 方法二：exe 同目录外部扩展（推荐给最终用户）

在 exe 同目录下创建：

```text
<exe 所在目录>/
├── dsh-pet-standalone-webm.exe
└── characters/
    └── <角色ID>/
        └── videos/
            ├── idle/
            ├── turn/
            ├── move/
            ├── click/
            ├── drag/
            └── random/
```

也支持用户数据目录：

```text
Windows: %APPDATA%/dsh-pet-standalone/characters/<角色ID>/videos/
macOS:   ~/Library/Application Support/dsh-pet-standalone/characters/<角色ID>/videos/
```

程序启动或切换角色时会自动检测：

- 外部目录存在 → 优先使用外部形象。
- 外部目录不存在 → 回退到 exe 内置形象，不会报错。

### 如何准备自定义形象的动画（参考项目绘制方法）

推荐直接参考上游项目 [dsh-pet](https://github.com/PC2005-cloud/dsh-pet)：

1. 克隆或下载参考项目：
   ```sh
   git clone --depth 1 https://github.com/PC2005-cloud/dsh-pet.git
   ```
2. 参考项目中的透明动画位于：
   ```text
   dsh-pet/dsh-pet/assets/thumb/*.webm
   ```
   这些是 640×360 透明 webm（VP9 + 8-bit alpha）。
3. 你可以：
   - 直接复制这些 webm 作为基础形象；
   - 或参考它们的动作分类，生成自己角色的同尺寸透明 webm；
   - 或使用 ffmpeg / 图像生成工具制作新的透明动画，建议至少覆盖你的最大显示尺寸。

4. 将制作好的 webm 按分类放入对应子目录：

```text
videos/
├── idle/     # 待机动画
├── turn/     # 转向动画
├── move/     # 移动动画
├── click/    # 点击回应动画
├── drag/     # 拖拽动画（可选）
└── random/   # 随机动作动画
```

5. 如果文件名无法通过关键词自动识别，可以添加 `manifest.json` 精确指定分类。

6. 启动后在桌宠右键菜单或托盘菜单的「切换角色」中选择你的新角色 ID。

## 使用手册

### 启动与退出

- **启动**：双击 `run.bat`（或 `python -m pet` / 打包后的 exe），桌宠出现在屏幕右下角
- **退出**：右键桌宠 →「退出」，或点系统托盘图标 →「退出」

### 鼠标交互

- **单击**：随机播放一个点击回应动画，并触发 Q 弹挤压回弹效果。
- **双击**：播放更强的点击回应，并按「互动反馈 → 尖叫鸭音效」设置播放尖叫鸭。
- **长按**：按住约 0.52 秒触发被吓一跳/随机动作回应；拖动超过 5px 后会转为拖拽。
- **快速连续点击**：三次及以上连续点击会切换到随机动作回应，并播放尖叫鸭。
- **鼠标靠近**：鼠标进入角色附近约 280px 内时，角色会看向鼠标。
- **拖拽**：按住拖动超过 5px 判定为拖拽，宠物播放「悬空反馈」动画跟手，松手停在原地
- **穿透**：只有宠物本体（不透明区域）可点，其余透明区域鼠标直接穿透到下层窗口

### 新功能使用说明

- **播放速率**：右键桌宠 →「播放速率」→ 选择 `1.0x ~ 2.0x`，动画会立即按新速度播放。
- **鼠标穿透**：右键系统托盘图标 → 勾选「鼠标穿透」，开启后鼠标点击会穿透桌宠到下层窗口；取消勾选即可恢复。
- **拖动物理**：右键桌宠 → 勾选「拖动物理」，开启后：
  - 拖动时会有惯性/离心感；
  - 松手后桌宠会被抛出；
  - 碰到屏幕边缘会反弹并逐渐衰减；
  - 落地后受摩擦力影响会慢慢停下。
- **互动反馈**：右键桌宠或状态栏图标 →「互动反馈」，可开关「尖叫鸭音效」和「偶尔主动打招呼」。脚步声、休息声暂未加入。
- **动作收藏夹 / 播放列表**：右键桌宠或状态栏图标 →「动作管理」，可以编辑收藏夹和播放列表，再选择「循环播放」或「随机播放」。
- **性格模式**：右键桌宠或状态栏图标 →「性格模式」，可选「安静 / 活泼 / 调皮」。
- **全局快捷键**：默认使用 `⌃⌥⌘` 加 `H/P/R/M/D`；如果系统没有成功注册全局监听，状态栏仍可正常使用全部菜单功能。

### 右键菜单（右键点击宠物本体）

| 菜单项          | 功能                                                                                      |
| --------------- | ----------------------------------------------------------------------------------------- |
| 动画 · 待机     | 手动播放待机动画；如果待机目录有多个视频，会显示二级菜单                                  |
| 动画 · 转向     | 手动播放转向动画；如果转向目录有多个视频，会显示二级菜单                                  |
| 动画 · 移动     | 手动播放移动动画（走路姿态 + 朝面向方向真实走动；「不移动」模式下这是唯一触发移动的方式） |
| 动画 · 点击回应 | 手动播放点击回应动画                                                                      |
| 动画 · 随机动作 | 手动播放随机动作动画                                                                      |
| 切换角色        | 热切换当前形象（内置 + 外部扩展角色都会列出）                                             |
| 回到右下角      | 把宠物复位到屏幕右下角                                                                    |
| 窗口置顶        | 勾选 = 始终显示在其他窗口之上，取消 = 可被其他窗口遮挡                                    |
| 不移动          | 勾选 = 只播放原地动画（待机/转向/随机动作），不再自动走动；取消 = 恢复正常模式            |
| 开机自启        | 勾选 = 随 Windows 登录自动启动（见下方说明）                                              |
| 大小            | 4 档缩放：320px / 462px / 544px / 640px（默认 462px）                                     |
| 播放速率        | 调节动画播放速度：1.0x / 1.1x / ... / 2.0x                                               |
| 拖动物理        | 开启后拖动桌宠有惯性/离心感，松手会抛出并带重力反弹衰减                                   |
| 退出            | 关闭桌宠                                                                                  |

### 系统托盘图标

| 操作                     | 功能                     |
| ------------------------ | ------------------------ |
| 双击托盘图标             | 显示 / 隐藏宠物          |
| 右键托盘图标 → 显示/隐藏 | 同上                     |
| 右键托盘图标 → 切换角色  | 热切换当前形象           |
| 右键托盘图标 → 鼠标穿透  | 开启后鼠标点击穿透到下层窗口 |
| 右键托盘图标 → 开机自启  | 与右键菜单的开机自启同步 |
| 右键托盘图标 → 退出      | 关闭桌宠                 |

### 自动行为（无需任何操作）

桌宠会自己"生活"，挂机即可观赏：

- **动画链**：每个动画播完按概率抽下一个 —— 30% 待机 / 10% 转向 / 40% 随机动作 / 20% 移动，永不停止
- **屏幕漫游**：朝面向方向行走，先检查屏幕空间、不走出屏幕
- **朝向翻转**：播完「东张西望」后左右翻转朝向，所有动画随之镜像
- **状态记忆**：位置、朝向、大小、置顶、不移动、开机自启、当前角色均自动保存（`%APPDATA%/dsh-pet-standalone/config.json`），下次启动自动恢复

### 开机自启

勾选「开机自启」后，桌宠随系统登录自动启动；取消勾选即移除。

- **Windows**：写入注册表 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`（无需管理员权限）；
  源码运行时指向 `pythonw -m pet`；打包成 exe 后会先用 `start /D` 切到 exe 所在目录再启动 exe，
  避免开机时默认工作目录不可写导致 onefile 解压失败（旧版自启命令会在下次启动时自动升级）
- **macOS**：写入 LaunchAgents（`~/Library/LaunchAgents/`），登录后自动启动

## 实现方式

### 技术栈

- **Python 3.10+ / PySide6**（Qt for Python，LGPL 许可）
- **imageio-ffmpeg** 解码 1280×720 VP9 Alpha 运行代理，并按当前显示档位输出有界 RGBA

### 动画链状态机（1:1 移植原插件 `client.js`）

原插件是一个"链式"状态机：每个动画一次性播放，播完按概率抽下一个
（30% 待机 / 10% 转向 / 40% 动作 / 20% 移动）。本项目的 `pet/window.py`
将这套行为完整移植为 Python：

- `_pick_next()` 按概率抽下一个动画
- 转向动画播完翻转朝向（`facing=right` 时水平镜像，等效原版 `scaleX(-1)`）
- 移动动画只提供"走路姿态"，位置由 `QTimer` 驱动：开头/结尾各 2s 原地不动，
  中间按播放进度插值位移
- 点击回应/拖拽动画播完先回"待机缓冲"，待机播完再回到随机链
- 点击只在待机时响应，5px 阈值区分点击与拖拽（等效原版命中层设计）

### 透明窗口与鼠标穿透

窗口用 Qt 的 `Tool` 无边框置顶窗口 + `WA_TranslucentBackground` 实现透明背景。
每帧按人物 alpha 通道生成 `QBitmap` mask，透明区域鼠标直接穿透到下层窗口，
实现"只有宠物本体可点击"（等效原版 HIT_BOX 命中层）。

### 素材播放（webm 主路线）

本项目保存 2560×1440 透明 **webm** 母版（VP9 + 8-bit alpha），App 播放其
1280×720 透明运行代理，并由 `imageio-ffmpeg` 在解码进程内按当前显示档位缩放。
逻辑画布固定为 640×360，因此素材分辨率不会改变桌宠大小或移动参数。

关键实现：

- 解码命令核心参数：
  ```python
  imageio_ffmpeg.read_frames(
      path,
      pix_fmt="rgba",
      bits_per_pixel=32,
      input_params=["-c:v", "libvpx-vp9"],
      output_params=["-vf", "scale=...:flags=lanczos"],
  )
  ```
  `-c:v libvpx-vp9` 必须放在输入之前，否则原生 vp9 解码器会丢弃 alpha。
- 播放架构：
  - 后台 reader 线程只负责把 RGBA 帧放入 2 帧有界队列；队列满时背压解码器。
  - 主线程 `QTimer` 按视频 fps 逐帧从队列取帧。
  - 每次只取最早的一帧，**不跳帧、不追帧**，避免动画快进。
  - 所有 `QImage/QPixmap` 和窗口 mask 更新都在主线程完成。
  - Windows 下 `imageio-ffmpeg` 内部使用 `STARTUPINFO` 隐藏 ffmpeg 控制台窗口，
    避免旧 ffmpeg 子进程方案导致的“窗口反复出现/消失”。

### 多形象支持

项目支持多角色形象，每个角色一个独立目录：

```text
assets/characters/<character_id>/videos/
├── idle/     # 待机
├── turn/     # 转向
├── move/     # 移动
├── click/    # 点击回应
├── drag/     # 拖拽（可选）
└── random/   # 随机动作
```

当前内置角色：

```text
shenshen（内置） + 用户通过外部目录添加的角色
```

- 默认形象为 `shenshen`，当前动画放在 `assets/characters/shenshen/videos/`。
- 不同角色可以有**不同的动作集**：程序会递归扫描 `videos/` 下的子目录，
  按目录自动区分“待机 / 转向 / 移动 / 点击回应 / 拖拽 / 随机动作”。
- 内置角色会随 exe 一起打包。
- 同时支持用户本地外部扩展：
  - exe 同目录或当前工作目录下的 `characters/<id>/videos/`
  - 用户数据目录下的 `dsh-pet-standalone/characters/<id>/videos/`
  - 运行时自动检测，存在则优先使用，不存在则回退内置，不会报错。
- 右键桌宠或托盘菜单中的「切换角色」可热切换形象。
- 右键菜单中「动画 · 待机」和「动画 · 转向」已拆分为两个独立按钮。

#### 动作分类规则

程序按以下优先级区分“待机 / 转向 / 移动 / 点击回应 / 拖拽 / 随机动作”：

1. **优先按 `videos/` 下的子目录分类**：
   - `idle/` → 待机
   - `turn/` → 转向
   - `move/` → 移动
   - `click/` → 点击回应
   - `drag/` → 拖拽（可选）
   - `random/` → 随机动作
   - 放在这些子目录之外的 webm 会进入随机动作池。
   - 兼容旧结构：如果存在 `idle_turn/`，程序仍会尝试按文件名关键词拆分待机和转向。

2. **可选 `manifest.json` 补充/覆盖**：
   - 查找位置：
     - `<角色目录>/videos/manifest.json`
     - `<角色目录>/manifest.json`
   - 示例：
     ```json
     {
       "idle": "我的待机.webm",
       "turn": "转身动画.webm",
       "moves": ["走路1.webm", "走路2.webm"],
       "clicks": ["点击回应.webm"],
       "drag": "拖拽动画.webm"
     }
     ```
   - 当子目录无法满足精确分类时，可以用 manifest 指定。

3. **关键词兜底**：
   - 待机：包含 `待机`、`idle`、`呼吸`
   - 转向：包含 `转向`、`转身`、`东张西望`、`回头`、`turn`
   - 移动：包含 `走`、`跑`、`移动`、`move`、`walk`、`run`、`踏步`、`奔跑`
   - 点击回应：包含 `点击`、`回应`、`click`、`response`
   - 拖拽：包含 `拖拽`、`拖`、`悬空`、`drag`、`抓`

4. 如果某个角色没有可用的“待机”，程序会安全回退到该角色第一个动画，避免启动崩溃。

> 建议：新角色推荐直接使用 `idle/ turn/ move/ click/ drag/ random/` 子目录结构，
> 这样不需要 manifest 也能正确分类。

## 快速开始

### 1. 安装依赖

```sh
pip install PySide6 imageio-ffmpeg
```

### 2. 准备素材

请从上游 [dsh-pet](https://github.com/PC2005-cloud/dsh-pet) 仓库获取
`dsh-pet/assets/thumb/*.webm`（91 个 640×360 透明 webm），按分类放到本项目的
`assets/characters/shenshen/videos/` 下对应子目录：

```text
assets/characters/shenshen/videos/
├── idle/
├── turn/
├── move/
├── click/
├── drag/
└── random/
```

无需转码即可直接运行。

### 3. 运行

双击 `run.bat`，或命令行 `python -m pet`。

## 打包为 exe（可选）

```bat
python -m PyInstaller --noconfirm --clean --onefile --windowed --noupx ^
    --name dsh-pet-standalone-webm ^
    --collect-all imageio_ffmpeg ^
    --add-data "assets/characters;assets/characters" ^
    packaging/pet_entry.py
```

> 打包入口必须用 `packaging/pet_entry.py`（绝对导入）；直接用 `pet/__main__.py`
> 会因相对导入在冻结模式下失效。onefile 模式启动时会先解压素材（约 5~15 秒）。

#### GIF 版打包（可选）

如果需要打包旧 GIF 素材版本，使用：

```bat
python -m PyInstaller --noconfirm --clean --onefile --windowed --noupx ^
    --name dsh-pet-standalone-gif ^
    --collect-all imageio_ffmpeg ^
    --add-data "assets/characters_gif;assets/characters_gif" ^
    packaging/pet_entry.py
```

程序会按素材目录自动识别：

- 目录里有 `*.webm` → 使用 webm 播放
- 目录里只有 `*.gif` → 使用 GIF/QMovie 播放

## macOS

### 安装包（.app，GitHub Actions 自动构建）

无需本地 Mac，项目通过 GitHub Actions 自动打包 macOS 版本：

1. 打开仓库的 **Actions** 页 → 左侧选「Build macOS App」→ 右侧 **Run workflow** → 确认
2. 等待构建完成（约 10 分钟），在构建详情页底部下载 artifact：
   `dsh-pet-indesktop-macos-arm64.zip`（Apple Silicon / M 系列芯片）
3. 解压得到 `dsh-pet-indesktop.app`，拖入「应用程序」文件夹即可

> **Intel Mac 用户**：当前仅提供 Apple Silicon（arm64）安装包，Intel 芯片的 Mac
> 请用下方「源码运行」方式使用。

> **未签名提示**：目前为免费版（ad-hoc 签名，未经 Apple 公证），首次打开会被 macOS
> Gatekeeper 拦截。放行方法（任选其一，`<你的app路径>` 改成实际位置）：
>
> 1. 右键 app →「打开」→ 再点「打开」；若无「打开」选项，走第 2 条
> 2. 系统设置 → 隐私与安全性 → 下滑找到「已阻止 'dsh-pet-indesktop'」→ 点「仍然打开」
> 3. 终端清除隔离标记后双击（最常用）：
>    ```sh
>    sudo xattr -d com.apple.quarantine "<你的app路径>/dsh-pet-indesktop.app"
>    ```
> 4. 若第 3 条仍被拦，再补 ad-hoc 签名后双击：
>    ```sh
>    xattr -cr "<你的app路径>/dsh-pet-indesktop.app"
>    codesign --force --deep --sign - "<你的app路径>/dsh-pet-indesktop.app"
>    ```

### 源码运行

```sh
pip install PySide6 imageio-ffmpeg
# 准备素材：同「快速开始」第 2 步，把 webm 放到 assets/characters/shenshen/videos/
python -m pet
```

### macOS 已知差异

- **开机自启**：macOS 通过 LaunchAgents（`~/Library/LaunchAgents/`）实现，与 Windows 注册表等价
- **透明穿透**：Qt 的窗口 mask 鼠标穿透在 macOS 上行为与 Windows 有差异，透明区域点击穿透**可能不完全生效**，需真机验证反馈
- **配置目录**：macOS 下配置保存在 `~/Library/Application Support/dsh-pet-standalone/`

## 目录结构

```
├── pet/                 # 核心代码
│   ├── catalog.py       # 动画目录、多形象常量、分类、几何/概率常量
│   ├── library.py       # 素材索引 + WebM/GIF 播放器按需加载
│   ├── webm_clip.py     # imageio-ffmpeg 解码 webm 的播放器
│   ├── performance.py   # 系统负载采样与省资源模式迟滞策略
│   ├── window.py        # 桌宠窗口：状态机 + 动画链 + 移动驱动 + 交互
│   ├── config.py        # 配置持久化（跨平台：APPDATA / Application Support / .config）
│   ├── autostart.py     # 开机自启（跨平台：Windows 注册表 / macOS LaunchAgents）
│   └── app.py           # 入口 + 系统托盘
├── assets/characters/   # 多形象动画（每个角色一个子目录）
│   └── <character_id>/videos/*.webm
├── packaging/           # PyInstaller 打包入口
├── tools/               # 超分、透明 WebM 运行代理生成与逐文件验收
├── .github/workflows/   # GitHub Actions（macOS 自动打包）
├── tests/               # 冒烟测试 / 诊断工具
├── run.bat              # Windows 一键启动
└── requirements.txt     # PySide6 + imageio-ffmpeg
```

## 已知说明

**媒体分层**：`MovieLibrary` 先建立 `MediaSource` 轻量索引，窗口首次切换到动作时才创建
播放器；退出和角色切换由窗口统一关闭媒体库，避免后台 reader 残留。

**webm 有界解码**：内置 1440p 母版派生的 1280×720 VP9 Alpha 运行代理；
默认 462px 档解码到 922×520，最大 640px 档才使用完整代理，覆盖 2× Retina。
GIF 只作为单独导出包，不放进应用。

## 开发经验与教训

> 记录本项目开发与打包过程中踩过的坑，供后续维护者参考。

### 打包与分发

- **CI 打包成功 ≠ 能运行**：macOS 的 GitHub Actions 构建曾"绿色成功"，但产物缺 `pet`
  模块（运行时才报 `ModuleNotFoundError`）。原因：`pyinstaller` 命令不会把当前目录加进
  模块搜索路径，从 `packaging/pet_entry.py` 入口分析时找不到项目根的 `pet` 包。必须用
  `python -m PyInstaller --paths .`。教训：打包后在 CI 里加验证步骤（检查 warn 文件 /
  解压检查权限），别只看绿灯。
- **zip 会丢 macOS 可执行权限**：`zip -r` 打包 .app 后解压，二进制丢失 +x 权限，双击
  无反应、终端 `permission denied`。改用 macOS 原生 `ditto -c -k --keepParent` 打包。
- **未签名 app 必被 Gatekeeper 拦**：免费版加 ad-hoc 签名
  （`codesign --force --deep --sign -`）后，「右键打开 / 系统设置放行」可用；彻底免
  拦截需 Apple 开发者账号公证（$99/年）。放行方法见上文「macOS」章节。
- **打包前先关掉正在运行的桌宠进程**：Windows 打包时若旧 exe 进程存活，PyInstaller
  覆盖产物会报 `PermissionError: 拒绝访问`；webm 版 exe 约 340MB，但仍需结束进程后重试。

### macOS 平台特性

- **Tool 窗口置顶用 `WA_MacAlwaysShowToolWindow`**：macOS 上 Qt 的
  `WindowStaysOnTopHint` 对 `Tool` 窗口不可靠（Qt 官方已知问题 QTBUG-38580），正确
  做法是设置 `Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow`；原生 `NSWindow.setLevel`
  需等窗口重建完成后（`QTimer.singleShot(0)`）再调，否则被 Qt 覆盖。
- **ctypes 调 ObjC 必须显式声明 restype**：`sel_registerName` 返回 64 位 SEL 指针，
  不设 `restype = c_void_p` 会被 ctypes 默认按 32 位截断，损坏的 SEL 使 ObjC runtime
  段错误（SIGSEGV，try/except 拦不住）。任何返回指针的 C 函数都要显式声明返回类型。
- **屏幕坐标比例要减 `availableGeometry` 的 left/top**：macOS 上
  `availableGeometry().top()` 等于菜单栏高度（≠0），按「窗口坐标 ÷ 可用区宽高」存比例
  会偏一个菜单栏高度；正确做法是 `(坐标 - avail.left()/top()) / avail.width()/height()`。

### 素材与播放

- **ffmpeg 解码透明 webm 时 `-c:v libvpx-vp9` 必须放在 `-i` 之前**：ffmpeg 原生 vp9
  解码器会丢弃 WebM alpha 通道（上游 DESIGN.md 踩坑记录第 3 条，已实测复现）。
- **webm 播放不能“清空队列只取最新帧”**：如果每次刷新都丢弃中间帧，动画会像快进一样。
  正确做法是按视频 fps 逐帧取最早的一帧。
- **播放结束标记不能误停新动画**：最后一帧触发窗口层切换动画后，旧的结束标记不应再
  停止新动画的定时器；否则会出现“播完一个动画后卡住不动”。
- **Windows 下 ffmpeg 子进程要隐藏控制台**：使用 `imageio_ffmpeg` 自带的
  `STARTUPINFO` 或显式 `CREATE_NO_WINDOW`，避免窗口反复出现/消失。

### 验证

- **真机验证不可替代**：macOS 专属代码路径（ctypes/ObjC、窗口置顶）在 Windows 上编译
  与冒烟测试都覆盖不到，必须真机验证；诊断日志（恢复位置/回到右下角时记录
  availableGeometry 与 DPR）就是为此加的。

## 附录：旧版 GIF/QMovie 路线（已归档）

> 当前版本已改为 **webm 直解路线**。以下为旧版 GIF/QMovie 路线的完整说明，仅作历史存档，不再使用。

<details>
<summary>点击展开查看旧版 GIF 版本说明</summary>

### 已移除/变更记录

- 内置角色 `guga`、`dada`、`suansuan`、`dudu`、`mimi` 已移除（动画未能正常绘制）。当前内置角色仅保留 `shenshen`。
- 自定义角色仍可通过 exe 同目录或用户数据目录下的 `characters/<id>/videos/` 添加，并在「切换角色」菜单中热切换。

---

# dsh-pet-indesktop

## 下载

无需从源码构建，直接到 [Releases](https://github.com/MerZlin/dsh-pet-indesktop/releases)
页面下载对应系统的安装包：

| 你的系统                        | 安装包                              | 说明                                                                  |
| ------------------------------- | ----------------------------------- | --------------------------------------------------------------------- |
| Windows                         | `dsh-pet-standalone.exe`            | 双击即跑，首次启动解压需几秒                                          |
| macOS（Apple Silicon / M 系列） | `dsh-pet-indesktop-macos-arm64.zip` | 解压得 `dsh-pet-indesktop.app`，首次打开需放行（见下方「macOS」章节） |
| macOS（Intel）                  | —                                   | 暂无安装包，请按「macOS」章节源码运行                                 |

> 文件名以 Release 页面实际发布为准。

> **声明与致谢**：本项目改自、源于 [dsh-pet](https://github.com/PC2005-cloud/dsh-pet)。
> 桌宠的动画素材、动画链行为模型、交互设计均来自原项目，特此声明并感谢原作者的贡献。

把 [dsh-pet](https://github.com/PC2005-cloud/dsh-pet) 插件里的桌宠，改造成一个
**跨平台的独立桌面宠物**软件（支持 **Windows** 与 **macOS**）—— 不依赖 DSH 运行时，
用 Python + PySide6 实现，双击即跑，内置 91 段原作 640×360 手工透明动画（24fps）。

Windows 用户见下方「快速开始 / 打包为 exe」，macOS 用户见「macOS」章节。

## 特性

- **webm 原作播放**：直接运行时解码 640×360 透明 webm（VP9 + 8-bit alpha），默认显示无需放大
- **动画链**：每个动画播完按概率选下一个 —— 30% 待机 / 10% 转向 / 40% 随机动作 / 20% 移动，永不停止
- **多形象支持**：内置多个角色，并支持用户通过外部目录添加自定义角色
- **角色热切换**：右键桌宠或托盘菜单可随时切换形象，无需重启
- **屏幕漫游**：朝面向方向行走，先检查屏幕空间、不走出屏幕（移动动画前后各 2s 准备/收尾，位置由代码驱动）
- **左右朝向**：转向动画播完翻转朝向，所有动画支持水平镜像
- **点击回应**：点击宠物随机播放当前角色配置的回应动画（链上非待机动画播放中不打断）
- **拖拽**：按住拖动超过 5px 判定为拖拽，宠物播放"悬空反馈"动画跟手，松手停在原地
- **透明穿透**：窗口逐帧按人物 alpha 生成 mask，透明区域鼠标直接穿透到下层窗口
- **右键菜单**：手动播放待机/转向/移动/点击回应/随机动作、切换角色、回到右下角、窗口置顶、不移动、开机自启、4 档大小、退出
- **系统托盘**：显示/隐藏、切换角色、开机自启、退出；位置/朝向/大小/置顶自动持久化
- **开机自启**：Windows 写 HKCU 注册表 Run 键 / macOS 写 LaunchAgents（均无需管理员权限），可随时开关

## 使用手册

### 启动与退出

- **启动**：双击 `run.bat`（或 `python -m pet` / 打包后的 exe），桌宠出现在屏幕右下角
- **退出**：右键桌宠 →「退出」，或点系统托盘图标 →「退出」

### 鼠标交互

- **点击**：单击宠物本体，随机播放当前角色配置的回应动画之一。
  链上非待机动画播放中点击不会打断
- **拖拽**：按住拖动超过 5px 判定为拖拽，宠物播放「悬空反馈」动画跟手，松手停在原地
- **穿透**：只有宠物本体（不透明区域）可点，其余透明区域鼠标直接穿透到下层窗口

### 右键菜单（右键点击宠物本体）

| 菜单项          | 功能                                                                                      |
| --------------- | ----------------------------------------------------------------------------------------- |
| 动画 · 待机     | 手动播放待机动画；如果待机目录有多个视频，会显示二级菜单                                  |
| 动画 · 转向     | 手动播放转向动画；如果转向目录有多个视频，会显示二级菜单                                  |
| 动画 · 移动     | 手动播放移动动画（走路姿态 + 朝面向方向真实走动；「不移动」模式下这是唯一触发移动的方式） |
| 动画 · 点击回应 | 手动播放点击回应动画                                                                      |
| 动画 · 随机动作 | 手动播放随机动作动画                                                                      |
| 切换角色        | 热切换当前形象（内置 + 外部扩展角色都会列出）                                             |
| 回到右下角      | 把宠物复位到屏幕右下角                                                                    |
| 窗口置顶        | 勾选 = 始终显示在其他窗口之上，取消 = 可被其他窗口遮挡                                    |
| 不移动          | 勾选 = 只播放原地动画（待机/转向/随机动作），不再自动走动；取消 = 恢复正常模式            |
| 开机自启        | 勾选 = 随 Windows 登录自动启动（见下方说明）                                              |
| 大小            | 4 档缩放：320px / 462px / 544px / 640px（默认 462px）                                     |
| 退出            | 关闭桌宠                                                                                  |

### 系统托盘图标

| 操作                     | 功能                     |
| ------------------------ | ------------------------ |
| 双击托盘图标             | 显示 / 隐藏宠物          |
| 右键托盘图标 → 显示/隐藏 | 同上                     |
| 右键托盘图标 → 切换角色  | 热切换当前形象           |
| 右键托盘图标 → 开机自启  | 与右键菜单的开机自启同步 |
| 右键托盘图标 → 退出      | 关闭桌宠                 |

### 自动行为（无需任何操作）

桌宠会自己"生活"，挂机即可观赏：

- **动画链**：每个动画播完按概率抽下一个 —— 30% 待机 / 10% 转向 / 40% 随机动作 / 20% 移动，永不停止
- **屏幕漫游**：朝面向方向行走，先检查屏幕空间、不走出屏幕
- **朝向翻转**：播完「东张西望」后左右翻转朝向，所有动画随之镜像
  - **状态记忆**：位置、朝向、大小、置顶、不移动、开机自启、当前角色均自动保存（`%APPDATA%/dsh-pet-standalone/config.json`），下次启动自动恢复

### 开机自启

勾选「开机自启」后，桌宠随系统登录自动启动；取消勾选即移除。

- **Windows**：写入注册表 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`（无需管理员权限）；
  源码运行时指向 `pythonw -m pet`；打包成 exe 后会先用 `start /D` 切到 exe 所在目录再启动 exe，
  避免开机时默认工作目录不可写导致 onefile 解压失败（旧版自启命令会在下次启动时自动升级）
- **macOS**：写入 LaunchAgents（`~/Library/LaunchAgents/`），登录后自动启动

## 实现方式

### 技术栈

- **Python 3.10+ / PySide6**（Qt for Python，LGPL 许可）
- **QMovie** 播放 GIF，运行时零外部依赖（无需 ffmpeg）

### 动画链状态机（1:1 移植原插件 `client.js`）

原插件是一个"链式"状态机：每个动画一次性播放，播完按概率抽下一个
（30% 待机 / 10% 转向 / 40% 动作 / 20% 移动）。本项目的 `pet/window.py`
将这套行为完整移植为 Python：

- `_pick_next()` 按概率抽下一个动画
- 转向动画播完翻转朝向（`facing=right` 时水平镜像，等效原版 `scaleX(-1)`）
- 移动动画只提供"走路姿态"，位置由 `QTimer` 驱动：开头/结尾各 2s 原地不动，
  中间按播放进度插值位移
- 点击回应/拖拽动画播完先回"待机缓冲"，待机播完再回到随机链
- 点击只在待机时响应，5px 阈值区分点击与拖拽（等效原版命中层设计）

### 透明窗口与鼠标穿透

窗口用 Qt 的 `Tool` 无边框置顶窗口 + `WA_TranslucentBackground` 实现透明背景。
每帧按人物 alpha 通道生成 `QBitmap` mask，透明区域鼠标直接穿透到下层窗口，
实现"只有宠物本体可点击"（等效原版 HIT_BOX 命中层）。

### 素材转码（webm → GIF）

原项目的播放资源是 640×360 透明 **webm**（VP9 + 8-bit alpha）；原始 1280×720
MP4 是非透明素材。本项目可把 WebM 另行导出为同尺寸透明 **GIF**，但应用默认仍使用 WebM。
`scripts/convert.py` 的关键点是 `-c:v libvpx-vp9` 必须放在 `-i` 之前 ——
ffmpeg 原生 vp9 解码器会丢弃 alpha（原项目 DESIGN.md 踩坑记录第 3 条，已实测复现）。

## 快速开始

### 1. 安装依赖

```sh
pip install PySide6
```

### 2. 准备素材

素材体积较大（GIF 392MB，未随仓库分发）。请从上游
[dsh-pet](https://github.com/PC2005-cloud/dsh-pet) 仓库获取
`dsh-pet/assets/thumb/*.webm`（91 个 640×360 透明 webm），放到本项目的
`assets/videos/` 目录，然后转码：

```sh
pip install imageio-ffmpeg pillow
python scripts/convert.py            # 默认读 assets/videos/，输出 assets/animations/
# 或指定源目录：python scripts/convert.py --src <你的webm目录>
```

### 3. 运行

双击 `run.bat`，或命令行 `python -m pet`。

## 打包为 exe（可选）

```bat
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name dsh-pet-indesktop ^
    --add-data "assets/animations;assets/animations" ^
    packaging/pet_entry.py
```

> 打包入口必须用 `packaging/pet_entry.py`（绝对导入）；直接用 `pet/__main__.py`
> 会因相对导入在冻结模式下失效。onefile 模式启动时会先解压素材（约 5~15 秒）。
>
> `--runtime-tmpdir "."` 是按“进程当前工作目录”解析的，不是 exe 所在目录。
> 程序内部的开机自启会先切到 exe 所在目录，因此解压目录会生成在 exe 同目录；
> 若 exe 位于系统保护目录（如 `Program Files`）且无写权限，请把 exe 放到用户可写目录。

## macOS

### 安装包（.app，GitHub Actions 自动构建）

无需本地 Mac，项目通过 GitHub Actions 自动打包 macOS 版本：

1. 打开仓库的 **Actions** 页 → 左侧选「Build macOS App」→ 右侧 **Run workflow** → 确认
2. 等待构建完成（约 10 分钟），在构建详情页底部下载 artifact：
   `dsh-pet-indesktop-macos-arm64.zip`（Apple Silicon / M 系列芯片）
3. 解压得到 `dsh-pet-indesktop.app`，拖入「应用程序」文件夹即可

> **Intel Mac 用户**：当前仅提供 Apple Silicon（arm64）安装包，Intel 芯片的 Mac
> 请用下方「源码运行」方式使用。

> **未签名提示**：目前为免费版（ad-hoc 签名，未经 Apple 公证），首次打开会被 macOS
> Gatekeeper 拦截。放行方法（任选其一，`<你的app路径>` 改成实际位置）：
>
> 1. 右键 app →「打开」→ 再点「打开」；若无「打开」选项，走第 2 条
> 2. 系统设置 → 隐私与安全性 → 下滑找到「已阻止 'dsh-pet-indesktop'」→ 点「仍然打开」
> 3. 终端清除隔离标记后双击（最常用）：
>    ```sh
>    sudo xattr -d com.apple.quarantine "<你的app路径>/dsh-pet-indesktop.app"
>    ```
> 4. 若第 3 条仍被拦，再补 ad-hoc 签名后双击：
>    ```sh
>    xattr -cr "<你的app路径>/dsh-pet-indesktop.app"
>    codesign --force --deep --sign - "<你的app路径>/dsh-pet-indesktop.app"
>    ```

### 源码运行

```sh
pip install PySide6
# 准备素材：同「快速开始」第 2 步，把 webm 放到 assets/videos/ 后转码
pip install imageio-ffmpeg pillow
python scripts/convert.py
python -m pet
```

### macOS 已知差异

- **开机自启**：macOS 通过 LaunchAgents（`~/Library/LaunchAgents/`）实现，与 Windows 注册表等价
- **透明穿透**：Qt 的窗口 mask 鼠标穿透在 macOS 上行为与 Windows 有差异，透明区域点击穿透**可能不完全生效**，需真机验证反馈
- **配置目录**：macOS 下配置保存在 `~/Library/Application Support/dsh-pet-standalone/`

## 目录结构

```
├── pet/                 # 核心代码
│   ├── catalog.py       # 91 段动画目录、分类、几何/概率常量
│   ├── library.py       # QMovie 素材库（速度补偿）
│   ├── window.py        # 桌宠窗口：状态机 + 动画链 + 移动驱动 + 交互
│   ├── config.py        # 配置持久化（跨平台：APPDATA / Application Support / .config）
│   ├── autostart.py     # 开机自启（跨平台：Windows 注册表 / macOS LaunchAgents）
│   └── app.py           # 入口 + 系统托盘
├── scripts/convert.py   # 素材转码：webm → 透明 GIF
├── packaging/           # PyInstaller 打包入口
├── .github/workflows/   # GitHub Actions（macOS 自动打包）
├── tests/               # 冒烟测试 / 帧率实测 / 诊断工具
├── run.bat              # Windows 一键启动
└── requirements.txt     # PySide6
```

## 已知说明

**清晰度略糊于 web 端**：web 端直接播放 640×360 透明 webm（VP9 视频，8-bit alpha），
而本项目的 GIF 受格式本身限制 —— ① 只支持 **1-bit alpha**（每像素要么全透明要么
全不透明，无半透明过渡，发丝边缘略硬）；② 最多 **256 色调色板**（有损颜色量化）。
分辨率与帧率与 web 端一致（640×360 / 24fps），但颜色与边缘过渡略逊，属 GIF 格式的
固有限制。若追求与 web 端完全一致的画质，可改用运行时 ffmpeg 解码 webm 的方案。

## 开发经验与教训

> 记录本项目开发与打包过程中踩过的坑，供后续维护者参考。

### 打包与分发

- **CI 打包成功 ≠ 能运行**：macOS 的 GitHub Actions 构建曾"绿色成功"，但产物缺 `pet`
  模块（运行时才报 `ModuleNotFoundError`）。原因：`pyinstaller` 命令不会把当前目录加进
  模块搜索路径，从 `packaging/pet_entry.py` 入口分析时找不到项目根的 `pet` 包。必须用
  `python -m PyInstaller --paths .`。教训：打包后在 CI 里加验证步骤（检查 warn 文件 /
  解压检查权限），别只看绿灯。
- **zip 会丢 macOS 可执行权限**：`zip -r` 打包 .app 后解压，二进制丢失 +x 权限，双击
  无反应、终端 `permission denied`。改用 macOS 原生 `ditto -c -k --keepParent` 打包。
- **未签名 app 必被 Gatekeeper 拦**：免费版加 ad-hoc 签名
  （`codesign --force --deep --sign -`）后，「右键打开 / 系统设置放行」可用；彻底免
  拦截需 Apple 开发者账号公证（$99/年）。放行方法见上文「macOS」章节。
- **打包前先关掉正在运行的桌宠进程**：Windows 打包时若旧 exe 进程存活（或杀毒软件
  正在扫描 400MB 大文件），PyInstaller 覆盖产物会报 `PermissionError: 拒绝访问`，
  需结束进程并等扫描结束后重试。

### macOS 平台特性

- **Tool 窗口置顶用 `WA_MacAlwaysShowToolWindow`**：macOS 上 Qt 的
  `WindowStaysOnTopHint` 对 `Tool` 窗口不可靠（Qt 官方已知问题 QTBUG-38580），正确
  做法是设置 `Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow`；原生 `NSWindow.setLevel`
  需等窗口重建完成后（`QTimer.singleShot(0)`）再调，否则被 Qt 覆盖。
- **ctypes 调 ObjC 必须显式声明 restype**：`sel_registerName` 返回 64 位 SEL 指针，
  不设 `restype = c_void_p` 会被 ctypes 默认按 32 位截断，损坏的 SEL 使 ObjC runtime
  段错误（SIGSEGV，try/except 拦不住）。任何返回指针的 C 函数都要显式声明返回类型。
- **屏幕坐标比例要减 `availableGeometry` 的 left/top**：macOS 上
  `availableGeometry().top()` 等于菜单栏高度（≠0），按「窗口坐标 ÷ 可用区宽高」存比例
  会偏一个菜单栏高度；正确做法是 `(坐标 - avail.left()/top()) / avail.width()/height()`。

### 素材与播放

- **ffmpeg 转码透明 webm 时 `-c:v libvpx-vp9` 必须放在 `-i` 之前**：ffmpeg 原生 vp9
  解码器会丢弃 WebM alpha 通道（上游 DESIGN.md 踩坑记录第 3 条，已实测复现）。
- **QMovie 播放 GIF 偏慢约 20%**：QMovie 的定时器 + 解码开销使每帧比 GIF 原生时长慢，
  需 `setSpeed(120)` 校准（见 `pet/library.py` 的 `PLAYBACK_SPEED`）。

### 验证

- **真机验证不可替代**：macOS 专属代码路径（ctypes/ObjC、窗口置顶）在 Windows 上编译
  与冒烟测试都覆盖不到，必须真机验证；诊断日志（恢复位置/回到右下角时记录
  availableGeometry 与 DPR）就是为此加的。

</details>

## 许可与致谢

- 本项目的 Python 代码为独立实现，采用 **MIT** 许可。
- 动画素材版权与许可归属原项目 [dsh-pet](https://github.com/PC2005-cloud/dsh-pet)（MIT）。
- 再次感谢 [PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet) 原作者。
# r4 设置与动作偏好

托盘或桌宠右键 →「设置与动作预览」：调整音量（macOS）、性格、画布宽度、动作结束后的等待时间。保存才应用设置；取消不保存。恢复默认只重置本页字段，点击保存生效，保留角色、收藏和位置。动作预览会立即播放，并恢复隐藏或暂停的桌宠。

五种性格按动作标签评分，取全部随机动作中排名前 40% 为高频池；最近三个自动动作尽量不重复。外部角色可在 `manifest.json` 添加：

```json
{"action_tags": {"自定义动作名": ["calm", "gentle"]}}
```

支持 `calm`、`social`、`playful`、`active`、`gentle`、`food`。显式标签优先；未标注时按文件名关键词分类。仅加载/切换性格时排序，无逐帧评分。隐藏时关闭媒体 reader，显示时恢复。

macOS r4 ZIP 解压后运行 `install-r4.command`。自检并确认应用进程启动后，脚本将标准名称 ZIP 和解压目录移至废纸篓；重命名的下载目录保留。当前构建未做 Developer ID 公证。
