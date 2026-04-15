# obs-local 本地运行说明

`obs-local` 提供本地日志观测能力：聚合请求、错误、阶段耗时，并通过 REST + SSE 驱动前端实时页面。
该子项目由 OpenAI Codex 开发与整理，文档已按 GitHub 展示场景更新。

## 运行前提

- Python 虚拟环境：`E:\github\mykms\.venv`
- Node.js 18+
- 已配置 `obs-local/config.yaml`，且日志路径可读

## 启动后端

推荐直接在仓库根目录执行一键启动脚本：

```powershell
E:\github\mykms\.venv\Scripts\python.exe scripts\start_obs_local.py
```

脚本会：

- 启动 `obs-local` 后端：`http://127.0.0.1:49154`
- 启动前端开发页：`http://127.0.0.1:4174`
- 等待后端 `/api/health` 与前端首页都可访问后再返回

如果你只想手工启动后端，必须先进入 `obs-local/` 目录，再执行：

```powershell
cd E:\github\mykms\obs-local
E:\github\mykms\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 49154
```

## 启动前端（开发模式）

```powershell
cd E:\github\mykms\obs-local\frontend
npm run dev
```

打开 `http://127.0.0.1:4174`。

开发模式默认通过 Vite proxy 把 `/api/*` 转发到 `http://127.0.0.1:49154`，因此本地联调**不需要**额外设置 `VITE_OBS_API_BASE_URL`。

## 可用性检查

```powershell
curl http://127.0.0.1:49154/api/health
curl http://127.0.0.1:49154/api/overview?project=mykms
```

## 前端生产构建

```powershell
cd E:\github\mykms\obs-local\frontend
npm run typecheck
npm run build
```

## 关键配置项

`obs-local/config.yaml` 现已支持以下运行期参数：

- `logging.level` / `logging.log_dir`：结构化日志级别与落盘目录
- `runtime.tail_poll_interval_seconds` / `runtime.max_cached_records`：后台 tail 轮询周期与内存缓存记录上限
- `tailer.chunk_size`：尾读块大小
- `stream.heartbeat_ms` / `stream.batch_window_ms` / `stream.batch_max_items` / `stream.max_queue_size`：SSE 心跳、批量窗口、批次大小与订阅队列上限
- `aggregation.top_n` / `aggregation.request_stage_limit`：聚合概览 Top N 与请求摘要阶段数上限

默认日志文件会写到 `obs-local/data/logs/obs-local.log`。

## 项目注册边界

`POST /api/projects` 的动态项目注册现在只接受位于以下范围内的 `log_path`：

- 当前工作目录
- `storage.state_db_path` 所在目录
- 已存在项目日志目录

这样可以阻止通过 API 注入任意文件路径。

## 回归命令（Stage 9）

```powershell
E:\github\mykms\.venv\Scripts\python.exe -m pytest obs-local\tests
cd E:\github\mykms\obs-local\frontend
npm run typecheck
npm run build
```

## 已实现交互

- 首页摘要卡、请求/错误/阶段区
- 请求列表点击打开详情抽屉
- 详情抽屉展示时间线、阶段明细、错误明细
- Requests / Errors / Stages 三块区域支持过滤
- SSE 实时刷新与断线重连状态提示
- `window / reload / pause-live / resume-live`
