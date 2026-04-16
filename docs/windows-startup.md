# Windows 开机自启动说明

本文说明如何让 `mykms` 与 `obs-local` 在 Windows 开机后自动启动，包括“无人登录也启动”和“登录后启动”两种模式。

## 适用范围

- 仓库根目录：`E:\github\mykms`
- Python 运行时：仓库内 `.venv\Scripts\python.exe`
- 启动脚本：
  - [scripts/start_kms.py](/E:/github/mykms/scripts/start_kms.py)
  - [scripts/start_obs_local.py](/E:/github/mykms/scripts/start_obs_local.py)
- 安装脚本：
  - [scripts/install_windows_startup.ps1](/E:/github/mykms/scripts/install_windows_startup.ps1)
  - [scripts/uninstall_windows_startup.ps1](/E:/github/mykms/scripts/uninstall_windows_startup.ps1)

## 默认模式：开机后无人登录也启动

默认安装模式是：

- 触发器：`AtStartup`
- 运行账户：`SYSTEM`

这意味着机器开机后即使没有用户登录，也会自动尝试启动：

- `mykms-start-kms`
- `mykms-start-obs-local`

必须在“管理员 PowerShell”中，到仓库根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows_startup.ps1
```

只安装单个任务：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows_startup.ps1 -Target kms
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows_startup.ps1 -Target obs-local
```

## 兼容模式：用户登录后启动

如果你不需要无人值守启动，只想在用户登录后自动启动，可执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows_startup.ps1 -TriggerMode logon
```

此时任务会改为：

- 触发器：`AtLogOn`
- 运行账户：当前用户

## 卸载

移除两个自动启动任务：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\uninstall_windows_startup.ps1
```

只移除单个任务：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\uninstall_windows_startup.ps1 -Target kms
powershell -ExecutionPolicy Bypass -File .\scripts\uninstall_windows_startup.ps1 -Target obs-local
```

## 验证

查看任务是否存在：

```powershell
Get-ScheduledTask -TaskName mykms-start-kms,mykms-start-obs-local | Select-Object TaskName,State
```

查看任务详情：

```powershell
Get-ScheduledTask -TaskName mykms-start-kms,mykms-start-obs-local | Format-List TaskName,State,Author,Description
```

服务侧验证：

```powershell
curl http://127.0.0.1:49153/health
curl http://127.0.0.1:49154/api/health
```

## 手动验收命令

建议在 PowerShell 中优先使用 `Invoke-WebRequest -UseBasicParsing`，避免 `curl` 别名触发网页脚本安全提示。

1. 确认计划任务已注册且处于 `Ready` 或 `Running`

```powershell
Get-ScheduledTask -TaskName mykms-start-kms,mykms-start-obs-local | Select-Object TaskName,State
```

2. 如需模拟一次计划任务启动，手动触发任务

```powershell
Start-ScheduledTask -TaskName mykms-start-kms
Start-ScheduledTask -TaskName mykms-start-obs-local
```

3. 验证 `mykms` 健康检查

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:49153/health | Select-Object StatusCode, Content
```

4. 验证 `obs-local` 健康检查

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:49154/api/health | Select-Object StatusCode, Content
```

5. 如接口未通过，检查关键日志

```powershell
Get-Content .\.run-logs\kms-api.stderr.log -Tail 80
Get-Content .\obs-local\data\logs\obs-local-backend.stderr.log -Tail 80
Get-Content .\obs-local\data\logs\obs-local-frontend.stderr.log -Tail 80
```

## 日志与排障

`mykms` 日志：

- `.run-logs/kms-api.pid.json`
- `.run-logs/kms-api.stdout.log`
- `.run-logs/kms-api.stderr.log`
- `.run-logs/kms-api.log`

`obs-local` 日志：

- `obs-local/data/logs/obs-local-backend.stdout.log`
- `obs-local/data/logs/obs-local-backend.stderr.log`
- `obs-local/data/logs/obs-local-frontend.stdout.log`
- `obs-local/data/logs/obs-local-frontend.stderr.log`
- `obs-local/data/logs/obs-local.log`

常见排障点：

- 默认无人登录模式需要管理员 PowerShell；非管理员会被安装脚本直接拒绝。
- `obs-local` 前端依赖 Node.js / npm；当前启动脚本已优先尝试固定路径，例如 `C:\Program Files\nodejs\npm.cmd`。
- 如果机器上的 npm 不在默认位置，可为启动任务所在环境补充 `OBS_NPM_PATH`。

## 说明

- 两个计划任务最终复用的仍然是仓库内现有启动脚本，不存在平行启动链路。
- `obs-local` 先于 `mykms` 启动时不会因为日志暂时为空而直接崩溃，但界面健康态可能短暂显示为 `idle` 或 `degraded`，待 `mykms` 开始写日志后会恢复。
