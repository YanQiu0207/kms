# Review Log

## M0

- Status: Approved
- Findings:
  - `app` package exports were incomplete; placeholder classes were not re-exported consistently.
  - `app.answer` abstraction drifted from the final plan and modeled answer generation instead of evidence assembly plus citation verification.
  - Runtime import failed on the local machine because the installed `pydantic` was not v2-compatible with the initial code.
- Resolution:
  - Re-exported placeholder contracts from package `__init__` files.
  - Realigned `app.answer` contracts to prompt assembly and citation verification.
  - Added `pydantic` v1/v2 compatibility in `app.config` and `app.schemas`.
  - Added `config.yaml` baseline file.
  - Verification completed with `python -m py_compile ...` and `python -c "from app.main import app; print(app.title); print(app.state.config.server.port)"`.

## M1

- Status: Approved
- Findings:
  - 存储层最初缺少删除旧文档和列出旧 chunk 的能力，增量索引无法正确清理历史索引。
  - FTS 预分词最初对 token 去重，会损失词频信息，影响后续词法检索质量。
  - 审核初版只覆盖服务层，没有覆盖真实 API 路由。
- Resolution:
  - 为 `SQLiteMetadataStore` 增加了 `delete_documents()`、`list_chunk_ids()`、`list_file_states()`。
  - 主 agent 新增 `app/services/indexing.py` 与本地 embedding 服务，并将 `/index`、`/stats` 接入真实流程。
  - 修正 FTS 分词逻辑，保留重复 token。
  - 新增 API 级测试 `tests/test_api_indexing.py`。
- 验证通过：`.venv\\Scripts\\python -m pytest -q tests\\test_api_indexing.py tests\\test_indexing_service.py tests\\test_package_scaffold.py tests\\test_health_config_scaffold.py`

## M2-M3

- Status: Approved
- Findings:
  - `chunk_index` 在跨 section 时重复，触发 SQLite `UNIQUE(document_id, chunk_index)` 冲突。
  - prompt 装配最初没有优先读取 `RetrievedChunk` 自带字段。
  - RRF 元数据最初没有正确区分 `lexical` / `semantic` 来源。
  - 多 query 精排最初只把第一个 query 传给 reranker。
  - `recall_top_k` / `rerank_top_k` 最初没有非负校验。
  - 端到端测试最初没有覆盖“证据过短拒答”和“负值 top_k 拒绝”。
- Resolution:
  - 在 `app/services/indexing.py` 中把落库 `chunk_index` 调整为文档内全局递增。
  - 修正 `app/answer/prompt.py` 的字段映射。
  - 修正 `app/retrieve/hybrid.py` 的来源标记和多 query rerank 输入。
  - 在 `app/schemas.py` 中增加 `top_k` 非负校验。
  - 接通 `POST /search`、`POST /ask`、`POST /verify`。
  - 新增测试：`tests/test_query_endpoints.py`、`tests/test_retrieval_m2.py`。
- 已验证：
  - `.venv\\Scripts\\python -m pytest -q tests\\test_retrieval_m2.py tests\\test_query_endpoints.py tests\\test_answer_m3.py tests\\test_api_indexing.py tests\\test_indexing_service.py tests\\test_package_scaffold.py tests\\test_health_config_scaffold.py`

## M4-M5

- Status: Approved
- Findings:
  - 适配层最初只有占位协议，没有可直接部署的 Claude/Codex 模板资产。
  - 仓库最初缺少 API 契约副本和基础评测样例，M5 无法真正起步。
- Resolution:
  - 新增 `app/adapters/reference/api.md`。
  - 新增 `app/adapters/claude/SKILL.md`。
  - 新增 `app/adapters/codex/kms.md`。
  - 新增 `eval/README.md` 与 `eval/benchmark.sample.jsonl`。
  - 新增 `tests/test_adapter_assets.py`。
- 已验证：
  - `.venv\\Scripts\\python -m pytest -q tests\\test_adapter_assets.py tests\\test_retrieval_m2.py tests\\test_query_endpoints.py tests\\test_answer_m3.py tests\\test_api_indexing.py tests\\test_indexing_service.py tests\\test_package_scaffold.py tests\\test_health_config_scaffold.py`

## Resume Checklist

- Review `dev-run/stage-status.md` for the last approved milestone.
- Resume from M4 adapter work, not from M2/M3.
- 主线功能已完成；后续如继续，优先处理 `dev-plan` 中文化与完整 benchmark 脚本。

## 当前待跟进问题

- 真实 `/search` 对语料中不存在的问题会返回低分偏题结果，后续可考虑增加最小分数过滤或显式低置信度标记。
- 端口已迁移到 `49153`，后续所有命令与文档都应以新端口为准。

## 检索展示优化（2026-04-15）

- Status: Approved
- Findings:
  - `/search` 在“语料中不存在答案”的场景下仍会吐出明显低分且偏题的结果，影响使用体验。
  - 现有稳定性修复后，问题已经从“服务错误”收敛为“结果展示策略不够保守”。
- Resolution:
  - 在 `app/config.py` / `config.yaml` 中新增 `retrieval.min_output_score`。
  - 在 `app/retrieve/hybrid.py` 中对 rerank 后结果按最小分数阈值过滤。
  - 新增回归测试，确保低分结果会被过滤，同时不影响已有接口测试基线。
- 已验证：
  - `.venv\\Scripts\\python -m pytest -q`
  - `POST http://127.0.0.1:49153/search` 对“个人知识库/混合检索”问题返回空结果
  - `POST http://127.0.0.1:49153/ask` 对“上下文处理包括什么？”仍可返回有效证据包

## 运行期修复（2026-04-15）

- Status: Approved
- Findings:
  - 查询阶段反复初始化 Chroma 客户端，在当前 `chromadb 1.5.7` 环境下会触发 `PersistentClient` / tenant 相关异常，导致 `/search` 与 `/ask` 返回 `500`。
  - `QueryService` 原先按请求重建，真实模型路径下会重复构造查询链路对象，放大首轮请求耗时。
  - `FlagEmbedding` reranker 原始分数可能为负值，直接塞进 `chunk.score` 会让 `/ask` 的 guardrail 置信度判断失真。
  - embedding / reranker 在并发请求下偶发编码失败，属于运行期稳定性问题。
- Resolution:
  - 在 `app/retrieve/semantic.py` 与 `app/store/vector_store.py` 中改为复用持久化 Chroma client。
  - 在 `app/main.py` 中把 `QueryService` 与 `IndexingService` 挂到应用级复用。
  - 在 `app/services/querying.py` 与 `app/retrieve/hybrid.py` 中复用长期存活的查询链路对象。
  - 在 `app/retrieve/rerank.py` 中保留 `rerank_raw_score`，并将对外 `score` 归一化到 `0..1`。
  - 在 `app/services/embeddings.py` 与 `app/retrieve/rerank.py` 中为真实模型调用增加进程内锁。
  - 新增测试覆盖真实 rerank 分数归一化行为。
- 已验证：
  - `.venv\\Scripts\\python -m pytest -q`
  - `GET http://127.0.0.1:49153/health`
  - `POST http://127.0.0.1:49153/ask` 对真实存在语料问题可返回证据包
  - `POST http://127.0.0.1:49153/ask` 对语料不存在问题可稳定拒答

## Benchmark 与边界补强（2026-04-15）

- Status: Approved
- Findings:
  - 原有评测层只有样例格式，没有可直接运行的 benchmark 脚本和真实语料集。
  - 词法检索对 `Few-Shot` 这类 query 会产出非法 FTS `OR` 表达式。
  - 空库时缺少 `chunk_fts` 表会导致 `/search` 返回 `500`，边界行为不安全。
- Resolution:
  - 新增 `eval/benchmark.py`、`eval/run_benchmark.py`。
  - 新增 3 份真实语料基准集：AI、分布式、游戏开发。
  - 新增结果快照目录 `eval/results/`。
  - 修复 `app/retrieve/lexical.py` 的 query token 清洗问题，忽略非法运算符 token。
  - 修复空库场景下缺少 FTS 表时的检索行为，改为安全返回空结果。
  - 新增 benchmark、运行期、边界回归测试。
- 已验证：
  - `.venv\\Scripts\\python -m pytest -q` -> `29 passed`
  - `eval/results/benchmark.ai.result.json`
- `eval/results/benchmark.distributed.result.json`
- `eval/results/benchmark.game.result.json`

## 来源展示与热路径优化（2026-04-15）

- Status: Approved
- Findings:
  - 玩家可读来源列表此前直接暴露 `chunk_id`，不适合作为正式展示。
  - chunk 行号虽然在 Markdown 解析层存在，但没有传递到 chunk、存储、检索和回答展示链路。
  - 热路径中最贵的是 rerank；当前架构会对过多候选做 cross-encoder 精排。
  - 服务重启后的首个查询仍会吃到完整模型冷启动，首个请求体验差。
- Resolution:
  - 为 `MarkdownChunk` 增加 `start_line` / `end_line`，并把行号透传到 SQLite / Chroma 元数据。
  - `/search` 与 `/ask` 增加 `location` 字段，格式为 `文件名:起止行`。
  - `prompt` / 来源列表改为输出 `[n] 文件名:行号 | 标题路径`，不再展示 `chunk_id`。
  - 保留 API 内部 `chunk_id`，供 `/verify` 继续使用。
  - 新增 `retrieval.rerank_candidate_limit = 24`，限制进入 reranker 的候选数。
  - 为单问题检索新增轻量 query 扩展，补充紧凑变体和关键词变体。
  - 新增 `server.warmup_on_startup = true`，服务启动时预热 embedding / reranker。
- 已验证：
  - `.venv\\Scripts\\python -m pytest -q` -> `32 passed`
  - 停旧进程后用 `.venv\\Scripts\\python -m uvicorn app.main:app --host 127.0.0.1 --port 49153` 启动新服务
  - `POST http://127.0.0.1:49153/index` 全量重建成功：`107 docs / 2702 chunks`
  - `POST http://127.0.0.1:49153/ask` 返回来源位置示例：`vector-clock.md:2-6`
  - 预热后首次 `/search` 实测约 `0.933s`

## 第三方库防腐层（2026-04-15）

- Status: Approved
- Findings:
  - `chromadb`、`FlagEmbedding`、`jieba` 仍直接散落在业务模块中，后续替换库会牵动多处实现。
  - 当前虽有协议层，但外部库 API 形状仍直接渗透到 store / retrieve / services 模块。
- Resolution:
  - 新增 `app/vendors/` 作为第三方库防腐层。
  - 将 `chromadb` 依赖收口到 `app/vendors/chroma.py`。
  - 将 `FlagEmbedding` 依赖收口到 `app/vendors/flag_embedding.py`。
  - 将 `jieba` 依赖收口到 `app/vendors/jieba_tokenizer.py`。
  - 新增测试，约束核心模块不再直接 import 这些第三方库。
- 已验证：
  - `.venv\\Scripts\\python -m pytest -q` -> `34 passed`

## Review Checklist

- Architecture matches `dev-plan/kms_final_plan.md`
- Runtime imports cleanly
- Config defaults are explicit and validated
- API schemas cover planned endpoints without overcommitting behavior
- Skeleton modules are safe placeholders, not dead imports
- Basic verification commands are recorded per stage
