# M10 obs-local Launch Runbook and Starter

## Goal

让 `obs-local` 的本地启动路径可直接执行，避免用户再手动猜：

- 后端模块路径
- 前端端口
- 是否需要额外设置 `VITE_OBS_API_BASE_URL`
- 启动后打开哪个地址才能看到界面

## Scope

- 新增一键启动脚本：`scripts/start_obs_local.py`
- 修正 `obs-local/README.md` 的启动命令、端口和页面地址
- 台账同步：`dev-run/stage-status.md`、`dev-run/progress.md`

## Non-Goals

- 本轮不实现 `obs-local` 停止脚本
- 不处理 `npm install` 依赖安装
- 不改 `obs-local` 前后端实现逻辑

## Flow

1. 增加 `start_obs_local.py`，负责起后端和前端，并等待健康检查可用。
2. 修正 README，使文档与脚本、Vite 配置、后端真实模块路径一致。
3. 运行脚本，验证 `/api/health` 与前端页面地址都能打开。

## Risks

- 若前端 `npm` 不在 PATH，中途会启动失败，需要给出明确报错。
- 若 49154 / 4174 已被占用，脚本应复用现有监听，而不是盲目重复启动。
