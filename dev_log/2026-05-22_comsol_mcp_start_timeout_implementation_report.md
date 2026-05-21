TL;DR: 已按计划实现 COMSOL MCP 启动超时排查与修复方案。`comsol_start` 现在默认走 MCP 自己托管的 client-server 启动路径，具备硬超时、运行目录重定向、失败报告和进程清理能力；新增 `comsol_startup_preflight` 可在不启动 COMSOL 的情况下定位路径、权限、端口、backend 和残留进程问题。真实验证显示原先的无限等待问题已被消除，当前剩余阻塞点是 COMSOL server 登录态返回“用户名或密码错误”。

# COMSOL MCP Start Timeout Implementation Report

## Summary

本次实施目标是解决 MCP 中 `comsol_start` 启动 COMSOL 时长时间无响应或超时不可诊断的问题。实现后，启动链路从原先的同步 `mph.Client(...)` 调用，改为默认使用本项目代码托管 `comsolmphserver.exe` 进程，再用 `mph.Client(port=...)` 连接该本地 server。

新的启动器会在后台线程读取 COMSOL stdout，主线程按 `timeout_seconds` 执行硬超时控制。若 server 没有在限定时间内输出端口，或启动后 client 连接失败，MCP 会清理本地 COMSOL server 进程，并把启动命令、最后输出、目录权限、backend、端口、进程快照写入诊断报告。

## Implemented Changes

- 新增 `ManagedComsolServer`：绕过 `mph.Server` 内部阻塞式 `readline()` 的超时风险，由 MCP 自己管理 `subprocess.Popen`、stdout 读取、端口解析、超时和 stop/kill。
- 改造 `SessionManager.start()`：新增 `timeout_seconds`、`mode`、`port`、`redirect_user_dirs` 参数；默认 `mode="client-server"`、`port=0`、`timeout_seconds=120`。
- 新增运行目录重定向：默认将 `-prefsdir`、`-configuration`、`-data`、`-tmpdir`、`-recoverydir` 指向仓库内 `.comsol_runtime`，避免沙箱写入 `C:\Users\Huayun\.comsol\v64` 受限目录。
- 新增 `comsol_startup_preflight` MCP 工具：返回 COMSOL executables、MPh/JPype 版本、MPh backend、目录写权限、2036-2040 端口占用和相关进程快照。
- 增强失败报告：启动失败会写入 `dev_log/comsol_start_timeout_YYYYMMDD_HHMMSS.json`，包含请求参数、server 参数、server 诊断和 preflight 信息。
- 改造 `comsol_disconnect()`：即使 client clear/disconnect 失败，也会继续尝试停止本地 COMSOL server，减少残留进程。
- 更新 `.gitignore`：忽略 `.comsol_runtime/` 和自动生成的 `dev_log/comsol_start_timeout_*.json`，避免提交本机缓存、登录状态或大体积运行产物。

## Verification

已执行并通过的验证：

- `.\.venv\python.exe -m compileall src tests`
- 手动 smoke tests：覆盖 runtime 参数组装、目录写权限探测、mock client-server 启动成功、mock 超时失败报告、disconnect server 清理。
- `build_startup_preflight(version="6.4", create_runtime_dirs=True)`：确认 COMSOL 6.4 backend 可发现，`comsolmphserver.exe` 存在，`.comsol_runtime` 可写。
- 真实启动验证：`SessionManager().start(version="6.4", cores=2, timeout_seconds=90)` 不再长时间卡死；约 14 秒内返回结构化失败，并生成诊断报告。
- 真实启动后进程检查：未发现残留 `comsolmphserver.exe` 或 `java.exe` 进程。

未完整执行的验证：

- `pytest` 未能运行，因为当前 `.venv` 中没有安装 `pytest`，系统 PATH 里也没有 `pytest` 命令。

## Observed Runtime Result

真实 preflight 明确复现原先的沙箱权限问题：

```text
C:\Users\Huayun\.comsol\v64\tomcat\logs      writable=False
C:\Users\Huayun\.comsol\v64\configuration    writable=False
C:\Users\Huayun\.comsol\v64\workspace        writable=False
E:\hycodespace\Forks\COMSOL_Multiphysics_MCP\.comsol_runtime writable=True
```

真实启动时，COMSOL server 已能启动并输出随机端口，例如报告中记录到 `port=54190`，说明启动等待链路已从“不可控阻塞”变成“可观测、有端口、有失败报告”。随后 `mph.Client(port=...)` 连接阶段失败，错误为：

```text
用户名或密码错误。
```

这表明本次修复已经越过原先的 stdout/权限/超时不可诊断问题，剩余问题转移为 COMSOL Multiphysics Server 登录凭据或登录策略问题。

## Files Changed

- `.gitignore`
- `src/tools/session.py`
- `tests/test_basic.py`

生成但被忽略的本机运行产物：

- `.comsol_runtime/`
- `dev_log/comsol_start_timeout_20260522_175023.json`
- `dev_log/comsol_start_timeout_20260522_175322.json`

## Next Steps

- 重启 Codex MCP server，使当前会话加载新版 `comsol_start` 参数和 `comsol_startup_preflight` 工具。
- 排查 COMSOL server 登录态：检查 `.comsol_runtime/prefs/login.properties`、COMSOL `-login auto` 行为，以及是否需要先在普通 PowerShell 中重置或保存 mphserver 登录信息。
- 如需临时绕过 MCP 启动，仍可在普通 PowerShell 手动运行 `comsolmphserver.exe -port 2036 -multi on`，再通过 MCP `comsol_connect(host="localhost", port=2036)` 连接。
- 安装测试依赖后运行完整 `pytest`，确认新增单元测试在标准 runner 下通过。
