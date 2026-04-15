# 容器化方案（kms-api + obs-local）

本文是容器化落地前的设计稿。**尚未实施**，待关键风险项（见 §5）逐条拍板后，才生成 Dockerfile / compose / 相关配置。

## 1. 现状事实

容器化难度由下列事实决定，均来自仓库现状核对（`config.yaml`、`pyproject.toml`、`app/main.py`、`obs-local/config.yaml`、`obs-local/frontend/vite.config.ts`、`scripts/start_kms.py` 以及 `data/` 目录体积）。

| 维度 | 现状 | 容器化影响 |
|---|---|---|
| `kms-api` 运行时 | FastAPI + uvicorn，监听 `127.0.0.1:49153` | 要改成 `0.0.0.0` 监听 |
| 主要依赖 | `chromadb`、`jieba`、`FlagEmbedding`、`torch`；`models.device=cuda`、`dtype=float16` | 强 GPU 偏好，需区分 `cpu` / `cuda` 两个 profile |
| 数据目录 | `data/meta.db` 11 M、`data/chroma` 49 M、`data/hf-cache` **7.1 G** | HF 模型缓存必须挂 volume，不能打进镜像 |
| 源文档 | `config.yaml` 里 `sources[0].path = E:\work\blog`（Windows 绝对路径）| 必须改成容器内挂载点 |
| 日志 | `.run-logs/kms-api.log` 等 4 个文件 | 需要共享卷给 obs-local 读 |
| `obs-local` 后端 | FastAPI，端口 49154，读取 `E:/github/mykms/.run-logs/kms-api.log` + 自己的 `state.db`，`POST /api/projects` 有路径边界限制 | 日志卷要共享；路径边界要与容器内路径匹配 |
| `obs-local` 前端 | Vue 3 + Vite，开发走 proxy → 49154，生产构建 `dist/` | 生产模式用 Nginx 托管 + 反代 |
| 启动入口 | `scripts/start_kms.py` / `scripts/start_obs_local.py` 假定 Windows + `.venv` | 容器里直接走 `uvicorn`，这两个脚本容器内不使用 |

结论：**可以容器化**。GPU 版本需要宿主有 NVIDIA Container Toolkit / Docker Desktop WSL2 GPU 支持；CPU 版本无障碍。

## 2. 总体架构（docker compose）

```
┌─────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│ obs-local-web   │ ──► │ obs-local-api    │ ──► 读 kms-logs (ro)    │
│ nginx :4174     │     │ uvicorn :49154   │                         │
│ (静态 dist)     │     │                  │     ┌──────────────────┐│
└─────────────────┘     └──────────────────┘     │ kms-api          ││
                                                 │ uvicorn :49153   ││
                                                 │ (可选 GPU)        ││
                                                 └──────────────────┘│
卷：                                                                  │
  kms-logs   （kms-api 写、obs-local-api 只读挂载）◄──────────────────┘
  kms-data   （sqlite + chroma，持久化）
  hf-cache   （模型缓存，首启动下载 7 G）
  obs-data   （obs-local state.db）
  blog-src   （bind mount 用户本地文档目录，只读）
```

3 个镜像、5 个卷、1 个 compose 文件。

## 3. 镜像设计

### 3.1 `kms-api`

- **base 候选**：
  - CPU：`python:3.11-slim`
  - GPU：`nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04` + 手装 Python 3.11
- 走多阶段 / 多 target：`FROM ... AS base-cpu` / `AS base-gpu`，compose 用 build args 选择
- 安装：`pip install -e ".[models]"`
- 环境变量：`HF_HOME=/var/kms/hf-cache`、`KMS_HOST=0.0.0.0`、`KMS_CONFIG_PATH=/etc/kms/config.yaml`
- 启动：`uvicorn app.main:app --host 0.0.0.0 --port 49153`
- 健康检查：`GET /health`

### 3.2 `obs-local-api`

- base：`python:3.11-slim`（无 GPU）
- 装 obs-local 自身依赖（**当前仓库未发现 `obs-local/pyproject.toml` 或 `requirements.txt`**，需确认依赖清单如何管理，见 §5 R5）
- 启动：`uvicorn app.main:app --host 0.0.0.0 --port 49154`

### 3.3 `obs-local-web`

- 多阶段：`node:20-alpine` → `npm ci && npm run build` → `nginx:alpine` 托管 `dist/`
- Nginx 反代 `/api/*` 与 `/api/stream`（SSE，需要关闭 buffering）到 `obs-local-api:49154`
- 暴露端口：4174（与现有 dev 端口对齐）

## 4. 配置改造清单

### 4.1 `config.yaml` 模板化

新增 `config.docker.yaml`，或扩展 env 覆盖能力：

- `server.host: 0.0.0.0`
- `sources[].path`: `/docs/blog`（容器内挂载点）
- `data.sqlite`: `/var/kms/data/meta.db`
- `data.chroma`: `/var/kms/data/chroma`
- `data.hf_cache`: `/var/kms/hf-cache`
- `models.device`: 通过 env `KMS_DEVICE=cpu|cuda` 注入（**当前代码仅 host / port / log 支持 env 覆盖，device/dtype 未支持**，见 §5 R4）

### 4.2 `obs-local/config.yaml` 模板化

- `projects[0].sources[0].log_path`: `/var/kms/logs/kms-api.log`
- `storage.state_db_path`: `/var/obs/data/state.db`
- 验证 `POST /api/projects` 的路径边界在容器内仍能正常工作

### 4.3 日志落盘

- `KMS_LOG_DIR=/var/kms/logs`

## 5. 风险与待确认项（R 系列）

写代码前必须先逐条拍板。

| 编号 | 项 | 需要的决定 |
|---|---|---|
| R1 | GPU or CPU | 是否必须支持 GPU？宿主没 NVIDIA + WSL2 GPU 时，先做 CPU 版本更稳 |
| R2 | 模型镜像源 | 国内网络下 `BAAI/bge-m3` 首次下载可能受限，是否预配置 `HF_ENDPOINT` 镜像 |
| R3 | 源文档挂载 | `E:\work\blog` 是 bind mount 进容器，还是拷贝到项目内某个目录 |
| R4 | `models.device` 环境变量覆盖 | 当前代码只支持 `KMS_HOST/PORT/LOG_*`，`device/dtype` 还没有 env override，是否顺手加 |
| R5 | `obs-local` 依赖清单 | 未发现 `obs-local/pyproject.toml` 或 `requirements.txt`，依赖共用根 `pyproject` 还是独立管理 |
| R6 | 生产 vs 开发 | 是否同时提供 dev compose（bind mount 源码 + `--reload`） |
| R7 | 镜像大小 | GPU 版 base 镜像 ~3 G + torch ~2 G，最终镜像会很大，是否可接受 |
| R8 | `.run-logs/kms-api.pid.json` | 容器模式下无意义；`start_kms.py` / `stop_kms.py` 容器内不用，仅本地开发保留 |

## 6. 分期计划（建议）

- **Stage 0（设计确认）**：逐条拍板 R1–R8，完善本文档
- **Stage 1（最小可用）**：CPU 版 `kms-api` Dockerfile + 基础 compose，验证 `/health`、`/ask` 跑通
- **Stage 2（obs 链路）**：加 `obs-local-api` + `obs-local-web`，验证共享日志卷 + SSE
- **Stage 3（GPU 可选）**：加 `kms-api` 的 GPU target 与 compose profile
- **Stage 4（收尾）**：文档 `docs/docker-plan.md` 升级为实施版、回归命令、`.dockerignore`、镜像体积优化（slim base、多阶段、layer 合并）

## 7. 参与人数

1 人（主会话）即可承接，不需要并行多 worker。Stage 2 如需同时修改 `obs-local` 代码与前端 Nginx 配置，可并行派 2 个 worker；但 compose 依赖调试更适合串行。

## 8. 交付物清单（实施阶段产出）

- `docker/kms-api.Dockerfile`（cpu / gpu 两个 target）
- `docker/obs-local-api.Dockerfile`
- `docker/obs-local-web.Dockerfile` + `docker/nginx.conf`
- `docker-compose.yaml`
- `docker/.env.example`
- `config.docker.yaml` 或模板渲染脚本
- `.dockerignore`
- 本文档升级为实施版（记录最终选型与回归命令）
