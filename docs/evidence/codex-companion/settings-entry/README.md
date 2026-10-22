# 设置入口与跨进程导航验证

本目录只覆盖精简模式传递、Codex 设置页路由及导航通道生命周期，不代表整项桌宠优化验收或资源占用收益。

## 复跑

在仓库根目录执行：

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_settings_process_isolation.py
QT_QPA_PLATFORM=offscreen .venv/bin/python docs/evidence/codex-companion/settings-entry/verify_process_navigation.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_architecture.py::test_window_private_surface_frozen
.venv/bin/python -m ruff check pet/__main__.py pet/app.py pet/settings_process_navigation.py tests/test_settings_process_isolation.py docs/evidence/codex-companion/settings-entry/verify_process_navigation.py
git diff --check
```

测试使用临时配置，跨进程 runner 显式关闭 Codex 连接，不读取真实会话或密钥。各 JSON 记录命令、环境、输入、断言和退出码；对应日志保留完整输出。

## 最终结果

- `green-family-public-final.log/json`：设置入口测试族 36 项通过。
- `architecture-public-green.log/json`：跨模块窗口私有成员约束 1 项通过。
- `ruff-final.log/json`、`diff-check-final.log/json`：退出码均为 0。
- `native-process.json`：真实 `ModernSettingsDialog` 的三个独立子进程串行通过。验证精简模式、首次 Codex 深链、重置页面后的跨进程导航、raise/activate 请求、进程退出及配置锁释放。三轮导航约 101.33 / 87.98 / 101.17 ms，均退出 0。

环境：Python 3.13.2、PySide6 6.11.2、macOS 26.6.2 arm64。Qt 使用 `offscreen`，未验证可见 macOS 窗口或真实前台焦点；上述耗时也不是 CPU 或内存优化结果。

## 失败记录

- `red.log/json`：先建立模式及语义路由失败用例，7 项失败。
- `green-family.log/json`：首次运行整族时发生原生崩溃；文件名前缀不表示通过。
- `diagnose-no-ipc.log/json`、`diagnose-ipc-next.log/json`：定位 IPC 用例后的 Qt 延迟析构问题。
- `cleanup-pair.log/json`：仅关闭客户端仍会原生崩溃，保留此失败尝试。
- `socket-slots-pair.log/json`：socket 回调改为 Qt slot，关闭时屏蔽信号后，相邻回归通过。
- `green-family-final.log/json`：公共窗口接口修正前，设置入口测试族已通过；最终结果以上述 `green-family-public-final` 为准。

修复避免 socket 信号 lambda 捕获自身造成析构重入；服务端关闭时不再在 abort 过程中触发重复 disconnected 清理。未对全量 pytest、独立生命周期测试族或性能长测作完成声明。
