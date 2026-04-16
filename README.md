# KMS API

本仓库实现了个人知识库服务 `kms-api`。
本项目由 OpenAI Codex 开发与整理，当前仓库内容已按对外发布场景维护。

当前已完成：

- Markdown 文档扫描、两级分块、增量索引
- `SQLite + FTS5 + Chroma` 混合检索
- RRF 融合与 rerank
- `/ask` 证据装配、拒答判定、`/verify` 引用校验
- Claude Code / Codex 适配模板资产
- 第三方库防腐层：`app/vendors/`

代码导读：

- `/ask` 链路与 Markdown 预处理说明：[docs/ask-and-ingest.md](/E:/github/mykms/docs/ask-and-ingest.md)
- `RAG` 评测方案原理：[docs/rag-evaluation-methodology.md](/E:/github/mykms/docs/rag-evaluation-methodology.md)
- `RAG` 质量提升总结与落地清单：[docs/rag-quality-improvement-roadmap.md](/E:/github/mykms/docs/rag-quality-improvement-roadmap.md)
- `M13` 数据清洗阶段总结：[docs/m13-rag-data-cleaning-stage-summary.md](/E:/github/mykms/docs/m13-rag-data-cleaning-stage-summary.md)
- `M14` 主语料清洗阶段总结：[docs/m14-rag-cleaning-stage-summary.md](/E:/github/mykms/docs/m14-rag-cleaning-stage-summary.md)
- `M15` 排序与证据判定阶段总结：[docs/m15-ranking-and-dedup-stage-summary.md](/E:/github/mykms/docs/m15-ranking-and-dedup-stage-summary.md)
- `M16` Query understanding 阶段总结：[docs/m16-query-understanding-stage-summary.md](/E:/github/mykms/docs/m16-query-understanding-stage-summary.md)
- `M17` Guardrail 与证据判定阶段总结：[docs/m17-guardrail-and-evidence-stage-summary.md](/E:/github/mykms/docs/m17-guardrail-and-evidence-stage-summary.md)
- `M18` 评测与数据工程阶段总结：[docs/m18-evaluation-and-data-engineering-stage-summary.md](/E:/github/mykms/docs/m18-evaluation-and-data-engineering-stage-summary.md)

## 启动

```bash
pip install -e .
uvicorn app.main:create_app --factory --host 127.0.0.1 --port 49153
```

或：

```bash
kms-api
```

若需要手动后台启动 / 关闭，并保留 pid 与日志，优先使用仓库内脚本：

```bash
python scripts/start_kms.py
python scripts/stop_kms.py
```

若需要单独探活或手动触发索引，可直接使用：

```bash
python scripts/probe_kms.py
python scripts/update_index.py --mode incremental
```

说明：

- `scripts/probe_kms.py` 默认访问当前配置对应的 `GET /health`，成功时返回简化后的健康 JSON，失败时返回错误 JSON 并以非 `0` 退出。
- `scripts/update_index.py` 默认触发 `POST /index` 的增量索引；可用 `--mode full` 执行全量重建。
- 两个脚本都支持 `--config`、`--host`、`--port` 覆盖目标地址。

若需要按不同配置启动多台本地实例做 review，可使用：

```bash
python scripts/run_kms_server.py --config config.yaml --host 127.0.0.1 --port 49154
python scripts/run_kms_server.py --config config.notes-frontmatter.yaml --host 127.0.0.1 --port 49155
```

说明：

- `scripts/run_kms_server.py` 适合 M18 这类多配置 benchmark / suite 审查场景。
- 当前本地双实例 suite 规格见：[eval/benchmark-suite.m18.local.json](/E:/github/mykms/eval/benchmark-suite.m18.local.json)

若需要在 Windows 下开机后无人登录也自动启动 `mykms` 与 `obs-local`，可在“管理员 PowerShell”中执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows_startup.ps1
```

说明：

- 默认会注册两个计划任务：
  - `mykms-start-kms`
  - `mykms-start-obs-local`
- 默认触发方式是 `AtStartup`，运行账户是 `SYSTEM`，因此机器开机后即使没人登录也会启动。
- 两个任务都会复用仓库内已有启动脚本。
- 若只安装单个任务，可用：
  - `powershell -ExecutionPolicy Bypass -File .\scripts\install_windows_startup.ps1 -Target kms`
  - `powershell -ExecutionPolicy Bypass -File .\scripts\install_windows_startup.ps1 -Target obs-local`
- 若你仍然想改回“用户登录时启动”，可用：
  - `powershell -ExecutionPolicy Bypass -File .\scripts\install_windows_startup.ps1 -TriggerMode logon`
- 卸载可用：
  - `powershell -ExecutionPolicy Bypass -File .\scripts\uninstall_windows_startup.ps1`
- 详细说明见：[docs/windows-startup.md](/E:/github/mykms/docs/windows-startup.md)

若需要把历史 SQLite 时间字段一次性迁移为本地时间字符串，可使用：

```bash
python scripts/migrate_db_timestamps.py
```

说明：

- 默认迁移 `data/meta.db`
- 默认会先备份 `meta.db`、`meta.db-wal`、`meta.db-shm` 到 `.run-logs/db-backup-时间戳/`
- 可先用 `--dry-run` 只扫描不写入

说明：

- `scripts/start_kms.py` 会优先使用仓库 `.venv` 里的 Python 解释器启动服务，避免误用系统 Python。
- 启动成功后会写入 `.run-logs/kms-api.pid.json`。
- 默认日志文件分工如下：
  - `.run-logs/kms-api.pid.json`：后台进程元信息，包含 `pid`、监听地址、配置路径、Python 路径、日志目录与启动时间。
  - `.run-logs/kms-api.stdout.log`：进程标准输出；通常只有显式 `print(...)`、第三方库写到 stdout 的内容，当前服务正常运行时这个文件通常很少内容，甚至为空。
  - `.run-logs/kms-api.stderr.log`：进程标准错误；会包含控制台结构化日志，以及未捕获异常、原生 traceback、warnings、第三方库直接写到 stderr 的输出。
  - `.run-logs/kms-api.log`：应用主日志文件；由 `app/observability.py` 写入 JSON line 结构化日志，适合按字段检索和排查服务行为。

## 测试

优先使用仓库自带虚拟环境运行测试：

```bash
.\.venv\Scripts\python.exe -m pytest
```

说明：

- 不要默认使用系统 Python 跑 `python -m pytest`。
- 当前项目测试依赖仓库 `.venv` 中已安装的真实依赖，例如 `pytest`、`chromadb`、`FlagEmbedding`、`torch`。
- 如果误用系统 Python，常见现象是报 `No module named pytest`、`chromadb is not installed`，这通常是环境问题，不是项目本身测试失败。
- 根目录默认 `pytest` 只收集主项目 `tests/`；`obs-local` 子项目请单独执行 `.\.venv\Scripts\python.exe -m pytest obs-local\tests`。

## 配置

配置读取顺序：

1. `KMS_CONFIG_PATH`
2. 项目根目录 `config.yaml`
3. 内置默认值

默认端口：`127.0.0.1:49153`

说明：

- 默认开启 `warmup_on_startup`，服务启动时会预热 embedding / reranker。
- 首次启动通常会比过去更慢一些，但启动完成后的首个查询延迟会更稳定。
- 可通过环境变量覆盖主机与端口：
  - `KMS_HOST`
  - `KMS_PORT`
- 可通过环境变量覆盖日志目录与日志级别：
  - `KMS_LOG_DIR`
  - `KMS_LOG_LEVEL`

## 日志与耗时

服务使用 JSON line 日志，便于后续分析、检索与聚合。常见字段包括：

- `timestamp`
- `service`
- `event`
- `level`
- `logger`
- `message`
- `request_id`
- `status`
- `duration_ms`

如果你不熟悉代码，但想把日志事件和实际执行流程对上，先看：

- [docs/ask-and-ingest.md](/E:/github/mykms/docs/ask-and-ingest.md)

按文件看，建议这样理解：

- 查“服务发生了什么、哪一步慢、哪个请求出错”：优先看 `.run-logs/kms-api.log`
- 查“为什么后台启动失败、有没有原始 traceback / 警告 / 第三方库报错”：优先看 `.run-logs/kms-api.stderr.log`
- 查“某段代码是不是直接 print 了内容”：看 `.run-logs/kms-api.stdout.log`
- 查“当前后台服务到底是谁启动的、监听哪个端口、pid 是多少”：看 `.run-logs/kms-api.pid.json`

当前已覆盖的关键链路包括：

- 服务生命周期：`app.startup.*`、`app.shutdown.*`
- HTTP 请求：`http.request.start`、`http.request.end`
- 查询链路：`api.search`、`api.ask`、`query.search`、`query.ask`
- 检索分阶段：`retrieval.lexical_stage`、`retrieval.semantic_stage`、`retrieval.search_and_rerank`
- 索引链路：`index.run`、`index.persist.metadata`、`index.persist.fts`、`index.persist.vector`
- 模型与资源：`embedding.model_load`、`embedding.encode`、`embedding.close`、`reranker.model_load`、`reranker.score`、`reranker.close`

示例用途：

- 看服务启动耗时：过滤 `event=app.startup.end`
- 看预热耗时：过滤 `event=query.warmup.end`
- 看某次请求端到端耗时：按 `request_id` 聚合 `http.request.*` 与其间的链路日志
- 看检索瓶颈：比较 `retrieval.lexical_stage.end`、`retrieval.semantic_stage.end`、`reranker.score.end` 的 `duration_ms`

## API

已实现接口：

- `GET /health`
- `GET /stats`
- `POST /index`
- `POST /search`
- `POST /ask`
- `POST /verify`

接口副本见 [app/adapters/reference/api.md](/E:/github/mykms/app/adapters/reference/api.md)。

## 适配模板

- Claude Code 模板：[app/adapters/claude/SKILL.md](/E:/github/mykms/app/adapters/claude/SKILL.md)
- Codex 模板：[app/adapters/codex/kms.md](/E:/github/mykms/app/adapters/codex/kms.md)

## 评测

评测骨架位于：

- [docs/rag-evaluation-methodology.md](/E:/github/mykms/docs/rag-evaluation-methodology.md)
- [eval/README.md](/E:/github/mykms/eval/README.md)
- [eval/benchmark.sample.jsonl](/E:/github/mykms/eval/benchmark.sample.jsonl)
- [eval/benchmark.hardcase.template.jsonl](/E:/github/mykms/eval/benchmark.hardcase.template.jsonl)

当前 `eval/` 已支持：

- `Recall@K`、`MRR`
- 拒答准确率、拒答精确率/召回率、误拒率、误答率
- 证据命中率、来源覆盖率、关键术语覆盖率
- 按 `case_type`、`tags` 的分组统计

## 请求样例

仓库内已提供可直接发送的 JSON 请求样例：

- [scripts/ask-vector-clock.json](/E:/github/mykms/scripts/ask-vector-clock.json)
- [scripts/ask-context.json](/E:/github/mykms/scripts/ask-context.json)
- [scripts/search-context.json](/E:/github/mykms/scripts/search-context.json)
- [scripts/verify-context.json](/E:/github/mykms/scripts/verify-context.json)

在 `git bash` 中可直接使用：

```bash
curl -s http://127.0.0.1:49153/ask \
  -H 'Content-Type: application/json; charset=utf-8' \
  --data-binary @scripts/ask-context.json
```

返回说明：

- `/search.results[*].location` 与 `/ask.sources[*].location` 为人类可读来源位置，格式为 `文件名:起止行`。
- `/ask.sources[*].chunk_id` 仍保留在 API 中，供机器侧调用 `/verify` 时使用；玩家展示不应直接暴露它。

## 第三方库防腐层

当前项目实际直接依赖的第三方库大致分为三层：

- Web / 配置层：`fastapi`、`uvicorn`、`pydantic`、`PyYAML`
- 检索 / 中文处理层：`chromadb`、`jieba`
- 模型层：`FlagEmbedding`，以及其运行时依赖 `torch`

为了降低替换成本，项目已新增 `app/vendors/`：

- `app/vendors/chroma.py`
- `app/vendors/flag_embedding.py`
- `app/vendors/jieba_tokenizer.py`

约束：

- 业务层不应再直接 `import chromadb` / `jieba` / `FlagEmbedding`
- 后续若替换为其他向量库、分词器、embedding/rerank 实现，优先修改 `app/vendors/`
