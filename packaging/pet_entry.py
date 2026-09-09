# -*- coding: utf-8 -*-
"""
PyInstaller 打包入口。

不能直接用 pet/__main__.py（其中的相对导入 `from .app import main`
在 PyInstaller 冻结模式下会解析失败，导致依赖收集为空）。

Windows 构建命令见 README；macOS 使用 GitHub Actions 或项目根目录的 PyInstaller
命令构建 onedir `.app`。构建完成后应先运行：

    dsh-pet-standalone-webm --selftest

`--selftest` 不创建 GUI，只检查角色素材、WebM 解码依赖和配置目录。
"""

import sys

from pet.app import main

if __name__ == "__main__":
    sys.exit(main())
