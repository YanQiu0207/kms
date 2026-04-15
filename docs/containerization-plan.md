# Containerization Plan

## 1. 目标

本文用于沉淀 `mykms` 与 `obs-local` 的容器化方案，先给出可实施的设计基线，不在本文中直接引入 `Dockerfile`、`compose` 或运行时代码改动。

目标分两层：

- 让 `kms-api` 能以容器方式稳定运行，并保留索引数据、模型缓存、结构化日志。
- 让 `obs-local` 能继续观测 `kms-api` 的真实日志，并以生产构建后的前端页面对外提供观测台。

## 2. 当前现状

### 2.1 `kms-api`

- Python/FastAPI 服务，入口在 [app/main.py](/E:/github/mykms/app/main.py)。
- 默认配置在 [config.yaml](/E:/github/mykms/config.yaml)。
- 当前默认端口为 `127.0.0.1:49153`。
- 数据目录默认位于：
  - `./data/meta.db`
  - `./data/chroma`
  - `./data/hf-cache`
- 运行日志默认位于：
  - `./.run-logs/kms-api.log`
  - `./.run-logs/kms-api.stdout.log`
  - `./.run-logs/kms-api.stderr.log`
- 检索与模型默认配置为：
  - embedding: `BAAI/bge-m3`
  - reranker: `BAAI/bge-reranker-v2-m3`
  - device: `cuda`
  - dtype: `float16`

### 2.2 `obs-local`

- 后端也是 Python/FastAPI，入口在 [obs-local/app/main.py](/E:/github/mykms/obs-local/app/main.py)。
- 前端为 Vue + Vite，当前开发配置在 [obs-local/frontend/vite.config.ts](/E:/github/mykms/obs-local/frontend/vite.config.ts)。
- 前端 API 基地址支持 `VITE_OBS_API_BASE_URL`，实现见 [obs-local/frontend/src/api/client.ts](/E:/github/mykms/obs-local/frontend/src/api/client.ts)。
- 当前默认端口：
  - 后端 `127.0.0.1:49154`
  - 前端开发页 `127.0.0.1:4174`
- `obs-local` 当前通过配置文件直接读取日志文件，默认日志源配置见 [obs-local/config.yaml](/E:/github/mykms/obs-local/config.yaml)。

### 2.3 已识别的环境特征

- 当前配置文件包含 Windows 本地绝对路径，例如：
  - `E:\work\blog`
  - `E:/github/mykms/.run-logs/kms-api.log`
- 当前仓库没有现成的：
  - `Dockerfile`
  - `docker-compose.yml`
  - `obs-local` 独立 Python 打包元数据
- 当前 `data/` 体积较大，主要由模型缓存和 Chroma 数据组成，不适合直接烤入通用镜像。

## 3. 结论

项目可以容器化，但建议按多容器拆分，不建议首版做成单容器。

推荐形态：

1. `kms-api` 一个容器
2. `obs-local-api` 一个容器
3. `obs-local-web` 一个容器

原因：

- `kms-api` 与 `obs-local` 的职责不同，生命周期和资源需求不同。
- `kms-api` 可能需要 GPU、模型缓存和较大的持久卷。
- `obs-local` 需要读取 `kms-api` 产出的日志文件，天然适合通过共享日志卷解耦。
- `obs-local` 前端已经具备生产构建条件，没有必要继续依赖 Vite dev server。

## 4. 主要约束与风险

### 4.1 路径不可直接复用

当前配置中的 Windows 路径无法直接用于 Linux 容器。

因此首版容器化必须新增容器专用配置文件，不能直接复用现有本地 `config.yaml`。

### 4.2 GPU 依赖不可默认假设

`kms-api` 当前默认配置是 `cuda + float16`。这对于：

- 无 GPU 的开发机
- 普通 Linux 服务器
- 未接入 `nvidia-container-toolkit` 的 Docker 环境

都不是安全默认值。

因此容器方案必须至少分为两档：

- CPU 默认档
- GPU 可选档

### 4.3 模型与缓存体积较大

模型缓存和向量索引目前不适合直接打进镜像层。否则会带来：

- 镜像体积过大
- 拉取耗时高
- 模型升级成本高
- 数据和镜像耦合

因此模型缓存、Chroma 数据、SQLite 数据都应走挂卷。

### 4.4 `obs-local` 依赖真实日志文件

当前 `obs-local` 不是读取 Docker stdout，而是直接 tail 日志文件。

这意味着容器化后必须满足以下条件之一：

- `kms-api` 容器把 `.run-logs` 作为共享卷输出给 `obs-local-api`
- 后续扩展 `obs-local`，让它支持 Docker log driver 或其他日志接入方式

首版建议采用第一种，改动最小。

### 4.5 现有前端仍以开发代理为主叙述

当前 [obs-local/README.md](/E:/github/mykms/obs-local/README.md) 主要描述的是开发模式和 Vite proxy。

容器化时，生产环境不应继续依赖：

- `npm run dev`
- Vite dev server
- 开发代理端口 `4174`

## 5. 推荐架构

### 5.1 服务拆分

#### `kms-api`

职责：

- 提供 `/health`、`/stats`、`/index`、`/search`、`/ask`、`/verify`
- 读取知识源目录
- 维护 SQLite / Chroma / Hugging Face 缓存
- 输出结构化日志

建议暴露：

- 内网端口 `49153`

#### `obs-local-api`

职责：

- 读取共享日志文件
- 做聚合、SSE、REST 查询
- 维护自己的状态库 `state.db`

建议暴露：

- 内网端口 `49154`

#### `obs-local-web`

职责：

- 承载构建后的静态前端资源
- 反向代理 `/api/*` 和 `/api/stream` 到 `obs-local-api`

建议暴露：

- 外网或宿主机端口 `8080` 或 `80`

### 5.2 卷设计

建议卷拆分如下：

- `kms_sources`
  - 挂载知识源目录
  - 例如容器内路径 `/workspace/sources`
- `kms_data`
  - 挂载 `meta.db`、`chroma`、`hf-cache`
  - 例如容器内路径 `/app-data`
- `kms_logs`
  - 挂载 `kms-api` 结构化日志
  - 例如容器内路径 `/shared-logs`
- `obs_state`
  - 挂载 `obs-local` 的 `state.db` 和自身日志
  - 例如容器内路径 `/obs-data`

### 5.3 网络设计

- 三个容器加入同一内部网络。
- `obs-local-web` 通过服务名访问 `obs-local-api`。
- `obs-local-api` 不直接调用 `kms-api` 业务接口，首版只读其日志卷。
- 如无必要，不直接把 `kms-api` 暴露给公网。

## 6. 配置改造建议

### 6.1 新增容器专用配置

建议新增：

- `config.container.yaml`
- `obs-local/config.container.yaml`

其中：

- 保留现有本地开发配置不动
- 容器配置只描述容器内路径
- 端口、host、日志目录允许继续被环境变量覆盖

### 6.2 `kms-api` 容器配置建议

建议默认值：

- `server.host = 0.0.0.0`
- `server.port = 49153`
- `sources[].path = /workspace/sources`
- `data.sqlite = /app-data/meta.db`
- `data.chroma = /app-data/chroma`
- `data.hf_cache = /app-data/hf-cache`
- `models.device = cpu`
- `models.dtype = float32`

说明：

- CPU 档先保证可运行和可移植。
- GPU 档后续再通过独立 profile 或覆盖配置开启。

### 6.3 `obs-local` 容器配置建议

建议默认值：

- `server.host = 0.0.0.0`
- `server.port = 49154`
- `storage.state_db_path = /obs-data/state.db`
- `logging.log_dir = /obs-data/logs`
- `projects[].sources[].log_path = /shared-logs/kms-api.log`

### 6.4 前端构建建议

前端走生产构建，不走开发服务。

建议约束：

- 构建阶段执行 `npm ci`
- 执行 `npm run build`
- 运行阶段只提供静态资源与反向代理
- 通过 `VITE_OBS_API_BASE_URL` 或反向代理约定统一 API 基地址

首版更推荐反向代理，这样前端无需写死容器内服务名。

## 7. 运行模式建议

### 7.1 第一阶段：CPU 开发/验收版

目标：

- 本机或普通 Linux 主机可直接启动
- 不依赖 GPU
- 先跑通容器边界、共享卷、日志观测链路

配置建议：

- `embedding` / `reranker` 仍可保留真实模型
- `device=cpu`
- `dtype=float32`
- 预热可以视启动耗时决定是否保留

### 7.2 第二阶段：GPU 生产版

目标：

- 在具备 NVIDIA 容器运行时的机器上启用 GPU
- 保持与 CPU 版相同的卷布局和服务拓扑

配置建议：

- 增加 `compose` profile，例如 `gpu`
- 覆盖：
  - `device=cuda`
  - `dtype=float16`
- 需要补充宿主机前置条件说明

### 7.3 第三阶段：离线或半离线版

目标：

- 将模型下载步骤前置
- 运行期不依赖外网拉模型

建议方式：

- 优先复用挂载好的 `hf-cache` 卷
- 如确有发布需求，再考虑制作带模型快照的专用基础镜像

## 8. 不建议的首版方案

以下方案不建议作为第一版：

### 8.1 单容器打包全部服务

问题：

- Python 后端、前端 dev server、日志观测混在一起
- 资源隔离差
- 生命周期耦合
- 不利于后续扩展 GPU/CPU 差异

### 8.2 把 `data/` 整体烤进镜像

问题：

- 镜像层过大
- 数据变更会导致重新构建镜像
- Chroma、SQLite、模型缓存与镜像版本强耦合

### 8.3 让 `obs-local` 继续依赖 Vite dev server

问题：

- 开发服务器不适合作为生产运行面
- 端口和代理行为不稳定
- 日志、缓存、静态资源策略都不适合作为正式部署面

## 9. 推荐实施顺序

### 阶段 A：文档与配置基线

- 新增容器化设计文档
- 新增容器专用配置文件
- 明确卷路径和容器内目录约定

### 阶段 B：`kms-api` 容器化

- 增加 `kms-api` 的 `Dockerfile`
- 验证 CPU 模式可启动
- 验证 `meta.db`、`chroma`、`hf-cache` 走挂卷
- 验证 `.run-logs/kms-api.log` 正常写出

### 阶段 C：`obs-local-api` 容器化

- 增加 `obs-local-api` 的 `Dockerfile`
- 接入共享日志卷
- 验证 `/api/health`、`/api/overview`、`/api/stream`

### 阶段 D：`obs-local-web` 容器化

- 增加前端多阶段构建
- 静态托管构建产物
- 反向代理 `/api/*`
- 验证浏览器端实时更新

### 阶段 E：Compose 编排

- 增加 `docker-compose.yml`
- 串联三服务、卷、网络、profile
- 补充运行文档

### 阶段 F：GPU 档

- 增加 GPU profile
- 补充宿主机要求与验证步骤

## 10. 验收标准

容器化完成后，至少满足以下验收条件：

1. `kms-api` 容器启动后可通过 `/health` 返回正常状态。
2. `kms-api` 可在挂载卷上读写 `meta.db`、`chroma`、`hf-cache`。
3. `kms-api` 可持续写出 `.run-logs/kms-api.log`。
4. `obs-local-api` 能通过共享日志卷看到 `kms-api.log` 的新增事件。
5. `obs-local-api` 的 `/api/overview` 与 `/api/stream` 能反映新增日志。
6. `obs-local-web` 可在浏览器中展示实时更新的请求、错误、阶段数据。
7. 停止并重新拉起容器后，索引数据、模型缓存、`obs-local` 状态库不会丢失。

## 11. 建议的后续产物

本文之后建议依次补齐：

- `docker/Dockerfile.kms`
- `docker/Dockerfile.obs-local-api`
- `docker/Dockerfile.obs-local-web`
- `docker-compose.yml`
- `config.container.yaml`
- `obs-local/config.container.yaml`
- `docs/containerization-runbook.md`

## 12. 当前建议

当前最合理的下一步不是直接写单体镜像，而是：

1. 先补容器专用配置文件
2. 再补三份 `Dockerfile`
3. 最后用 `compose` 串起来

这样可以先把路径、卷、日志和 CPU/GPU 分层问题理顺，避免一开始就把实现耦死。
