# Progress

## 2026-04-15 20:20 Session

- 目标：在杀掉旧进程后，用 3 组 `real10` 真实测试集验证知识库功能是否被最近一版实现破坏。
- 已确认数据集完整：
  - `eval/benchmark.ai.real10.jsonl`
  - `eval/benchmark.distributed.real10.jsonl`
  - `eval/benchmark.game.real10.jsonl`
- 已先停掉旧服务进程，再尝试默认冷启动。
- 首次冷启动失败，证据：
  - `scripts/start_kms.py` 返回 `startup_timeout`
  - `.run-logs/kms-api.stderr.log` 显示 `BAAI/bge-m3` 在 warmup 期间访问 Hugging Face 元数据并触发 SSL 错误
- 已验证用户判断成立：
  - 模型已缓存，本机 GPU 为 `RTX 3070 Ti 8GB`
  - 启动成功时显存占用约 `5164 MiB`
  - 问题不是模型未下载，而是冷启动路径错误联网
- 已修复 vendor 防腐层：
  - `app/vendors/flag_embedding.py` 现在会优先解析本地 Hugging Face snapshot
  - 对 `bge-m3` 的本地 snapshot 显式指定 `model_class=encoder-only-m3`
  - 保留旧版签名兼容 fallback
- 已补回归测试：
  - `tests/test_vendor_boundaries.py`
  - 结果：`8 passed`
- 已重新验证默认冷启动：
  - `scripts/start_kms.py` 正常启动
  - 当前服务进程：`PID 51424`
- 已基于新进程跑完 30 条 live API 回归，结果写入：
  - `eval/results/benchmark.ai.real10.http.result.json`
  - `eval/results/benchmark.distributed.real10.http.result.json`
  - `eval/results/benchmark.game.real10.http.result.json`
  - `eval/results/real10.http.run.summary.json`

## Current Findings

- AI 集：
  - `Recall@K = 1.0`
  - `MRR = 0.8438`
  - `拒答准确率 = 1.0`
- Distributed 集：
  - `Recall@K = 0.875`
  - `MRR = 0.8125`
  - `拒答准确率 = 0.8`
- Game 集：
  - `Recall@K = 1.0`
  - `MRR = 0.9444`
  - `拒答准确率 = 0.9`

## Next

- 若继续推进，下一步应聚焦误拒答与漏召回 case，而不是启动稳定性。

## 2026-04-15 20:24 Instrumentation

- 已按执行路径临时增加结构化日志：
  - `app/retrieve/hybrid.py`
  - `app/services/querying.py`
- 新增日志点：
  - `retrieval.search_and_rerank.preview`
  - `query.ask.guardrail`
- 已重启服务并复测 3 个失败 case：
  - `逻辑时钟解决了什么问题？`
  - `TrueTime 的关键价值是什么？`
  - `高并发三大利器是什么？`
- 定位结果：
  - `逻辑时钟`：检索与 rerank 都命中 `logic-clock.md`，但 top1 仅 `0.2080`，被 `top1_min=0.35` 误拒答。
  - `高并发三大利器`：top1 命中 `服务端优化.md:58-62`，分数 `0.9989`，但总证据字符数仅 `165`，被 `min_total_chars=200` 误拒答。
  - `TrueTime`：`/search` 最终只剩 2 条 `raft_learning_plan.md:31-33`，说明问题发生在 rerank/输出过滤阶段；guardrail 只是对错误结果继续拒答，不是首因。

## 2026-04-15 20:40 Threshold And Coverage Fix

- 已把新增拒答数字阈值显式放回配置：
  - `config.yaml`
  - `app/config.py`
- 新增配置项：
  - `abstain.min_query_term_count = 2`
  - `abstain.min_query_term_coverage = 0.60`
- 已在 `app/services/querying.py` 增加 query 术语覆盖检查：
  - 当 query 至少含 2 个有效术语时，要求证据对任一 query 变体的术语覆盖率达到阈值
  - 用于拦截只命中 `ZooKeeper`、却没命中 `watch` 的“半相关”误答
- 已补测试：
  - `tests/test_query_service.py`
  - 新增 `query_term_coverage_below_threshold` 场景
- 已跑回归：
  - `.\.venv\Scripts\python.exe -m pytest tests\test_retrieval_m2.py tests\test_query_service.py tests\test_answer_m3.py tests\test_query_endpoints.py tests\test_eval_benchmark.py tests\test_vendor_boundaries.py`
  - 结果：`33 passed`
- 已重启服务并重跑 30 条 HTTP 真实集：
  - 当前服务进程：`PID 32348`
  - 结果文件：
    - `eval/results/benchmark.ai.real10.http.result.json`
    - `eval/results/benchmark.distributed.real10.http.result.json`
    - `eval/results/benchmark.game.real10.http.result.json`
    - `eval/results/real10.http.run.summary.json`
- 最新结果：
  - `ai`：`Recall@K=1.0`，`MRR=1.0`，`拒答准确率=1.0`
  - `distributed`：`Recall@K=1.0`，`MRR=0.9167`，`拒答准确率=1.0`
  - `game`：`Recall@K=1.0`，`MRR=0.9444`，`拒答准确率=1.0`
- 剩余非满分项说明：
  - `dist10-006` 的 top1 来自 `3pc.md` 背景段，该段原文完整复述了 `2PC` 的两个主要问题。
  - 这会拉低 benchmark 的 `MRR`，但不属于当前实现回归。

## 2026-04-15 21:05 obs-local Log Contract Compatibility

- 续跑恢复：
  - 已按 `dev-run/stage-status.md`、`progress.md`、`issue-log.md` 核对当前主线已全部通过。
  - 新增需求聚焦为：让 `mykms` 结构化日志更贴近 `obs-local` 当前消费契约。
- 已确认兼容性缺口：
  - `app/observability.py` 与 `app/main.py` 统一输出的是 `elapsed_ms`。
  - `obs-local/app/parser.py` 与聚合链路消费的是 `duration_ms`。
  - 这会导致 `obs-local` 读取 `mykms` 日志时，请求耗时与阶段耗时无法按正式协议被识别。
- 已完成修复：
  - `app/observability.py`
    - 新增 `LOG_SCHEMA_VERSION = 1`
    - 新增 `duration_fields()`，统一输出 `duration_ms` 与兼容字段 `elapsed_ms`
    - `timed_operation()` 结束事件已改为携带 `duration_ms`
  - `app/main.py`
    - `http.request.end` 已改为输出 `duration_ms`
    - `http.request.error` 已改为输出 `duration_ms`
    - 请求异常日志已补 `status=error` 与 `error_type`
- 已补回归：
  - `tests/test_observability.py`
  - 覆盖点：
    - `timed_operation` 结束事件包含 `duration_ms`
    - HTTP 请求日志包含 `duration_ms`
    - 兼容字段 `elapsed_ms` 仍保留
- 已跑验证：
  - `E:\github\mykms\.venv\Scripts\python.exe -m pytest tests\test_observability.py tests\test_api_indexing.py tests\test_query_endpoints.py -q`
  - 结果：`7 passed`
- 下一步：
  - 若继续联调，可直接让 `obs-local` 读取最新 `.run-logs/kms-api.log`，确认 requests / stages 视图开始出现真实耗时。

## 2026-04-15 22:05 M6 Host Full-File Answering Kickoff

- 续跑恢复：
  - 已核对 `dev-run/stage-status.md`、`progress.md`、`issue-log.md`，当前 M0-M5 均已通过。
  - 新需求聚焦为：新增一个宿主专用接口，只返回候选文件；再新增一个 Codex skill，在 skill 层读取本地全文作答。
- 已完成方案收敛：
  - 保留现有 `/ask` 语义不变，不把“读本地文件”塞进通用 API 假设。
  - 新接口计划命名为 `/ask-files`，复用现有检索、rerank、拒答与 coverage 判断。
  - 候选文件将从 SQLite `documents` 表读取，避免重新扫盘或依赖 chunk 拼接全文。
- 下一步：
  - 落 schema、service、route 和 API 契约。
  - 新增对应 Codex skill 与回归测试。

## 2026-04-15 22:32 M6 Host Full-File Answering Done

- 已完成接口实现：
  - `app/schemas.py`
    - 新增 `AskFilesRequest`、`AskFile`、`AskFilesResponse`
  - `app/services/querying.py`
    - 新增 `ask_files()`
    - 新增文档去重与 SQLite 文档表回查逻辑
  - `app/main.py`
    - 新增 `POST /ask-files`
- 已完成文档与样例：
  - `app/adapters/reference/api.md`
  - `README.md`
  - `scripts/ask-files-context.json`
  - `app/adapters/codex/kms-full-file.md`
- 已完成本机 skill：
  - 使用 `skill-creator` 初始化 `C:\Users\YanQi\.codex\skills\kms-full-file-assistant`
  - 已补真实 `SKILL.md` 与 `agents/openai.yaml`
  - 已跑校验：`Skill is valid!`
- 已完成回归：
  - `E:\github\mykms\.venv\Scripts\python.exe -m pytest tests\test_query_service.py tests\test_query_endpoints.py tests\test_adapter_assets.py -q`
  - 结果：`12 passed`
- 放行结论：
  - M6 当前范围已落地，未修改现有 `/ask` 语义。
  - 新模式明确限定为“宿主具备本地文件读取权限”时使用。

## 2026-04-16 00:10 obs-local Compatible Protocol Upgrade

- 续跑恢复：
  - 已复核 `obs-local/docs/design_v1_claude.md` 当前剩余协议缺口。
  - 已确认若直接把 `event` 改成纯 `start/end/error`，会立刻破坏 `obs-local` 当前 parser / aggregator 对 `http.request.*` 的识别。
  - 本轮改为“兼容式升级”路线：在不打断现有 `obs-local` 消费链路的前提下，先补完剩余阻塞项里的可兼容部分。
- 已完成兼容式协议升级：
  - `app/main.py`
    - `http.request.end` 现在显式带 `status`
    - 异常请求现在会产出配对的 `http.request.end`
    - `http.request.start/error/end` 全部补 `trace_id/span_id/span_name/kind`
    - root request span 会作为应用内 `timed_operation` 的父 span
  - `app/observability.py`
    - 新增 span 栈：`bind_span()/reset_span()/current_span()`
    - `timed_operation()` 现在会自动补 `span_id/parent_span_id/span_name/kind/trace_id`
    - `JsonLogFormatter` 现在会补：
      - `event_type`
      - `trace_id`
      - `attributes`
    - 文件日志已从 `FileHandler` 升级为 `TimedRotatingFileHandler`
  - `app/timefmt.py`
    - `format_local_datetime()` 现在输出 RFC3339 / ISO8601 带时区 offset
- 本轮刻意保留的兼容约束：
  - 仍保留完整事件名，如 `http.request.start`、`api.ask.end`
  - 仍保留 `request_id`
  - 仍保留 `elapsed_ms` 兼容字段
  - 这样 `obs-local` 当前版本无需同时改 parser/aggregator 也能继续消费
- 已补/已更新回归：
  - `tests/test_observability.py`
    - 新增 span 元数据断言
    - 新增 rotate handler 断言
    - 新增异常请求 `error + end` 成对断言
    - 新增 request root span 与 `api.stats` parent span 断言
  - `tests/test_sqlite_timestamp_migration.py`
    - 预期时间格式已同步到 RFC3339 带 offset
- 已跑验证：
  - `E:\github\mykms\.venv\Scripts\python.exe -m pytest tests\test_observability.py tests\test_sqlite_timestamp_migration.py tests\test_api_indexing.py tests\test_query_endpoints.py -q`
  - 结果：`15 passed`
- 当前剩余未做：
  - 还未把协议彻底切到 `event=start|end|error + span_name`
  - 还未把业务字段完全收拢到纯 `attributes` 根层最小集
  - 还未补 `service.startup` session 边界事件
  - 这几项若继续推进，需要同步改 `obs-local` parser / aggregator / tests，而不是只改 `mykms`

## 2026-04-15 21:28 M7 Remove Full-File Mode Kickoff

- 续跑恢复：
  - 已按 `dev-run/stage-status.md`、`progress.md`、`issue-log.md` 核对当前 M0-M6 均已通过。
  - 新需求聚焦为：删除 `kms-full-file-assistant` 技能，以及仓库中的 `/ask-files` 接口与相关逻辑。
- 已完成方案收敛：
  - 不改历史 M6 记录，新增 M7 作为显式撤回阶段。
  - 仓库侧需要同步删除 schema、service、route、测试、README、API 契约、Codex 全文模板与请求样例。
  - 本机 skill 位于仓库外，需要单独删除并补验证。
- 下一步：
  - 直接删除仓库内实现与资产。
  - 清点剩余引用后删除本机 skill，并跑定向回归。

## 2026-04-15 21:42 M7 Remove Full-File Mode Done

- 已完成仓库侧删除：
  - `app/schemas.py`
    - 删除 `AskFilesRequest`、`AskFile`、`AskFilesResponse`
  - `app/services/querying.py`
    - 删除 `AskFilesServiceResult`
    - 删除 `ask_files()`
    - 删除文档级文件回查与相关死代码
  - `app/main.py`
    - 删除 `POST /ask-files`
  - `app/adapters/reference/api.md`
  - `README.md`
  - `tests/test_query_service.py`
  - `tests/test_query_endpoints.py`
  - `tests/test_adapter_assets.py`
- 已删除仓库资产：
  - `app/adapters/codex/kms-full-file.md`
  - `scripts/ask-files-context.json`
- 已删除本机 skill：
  - `C:\Users\YanQi\.codex\skills\kms-full-file-assistant`
  - 校验结果：`Test-Path ...` 返回 `False`
- 已跑定向回归：
  - `E:\github\mykms\.venv\Scripts\python.exe -m pytest tests\test_query_service.py tests\test_query_endpoints.py tests\test_adapter_assets.py -q`
  - 结果：`10 passed`
- 放行结论：
  - M7 当前范围已收口。
  - 服务当前只保留 `/ask`、`/search`、`/verify` 等主链路接口，不再暴露全文模式。

## 2026-04-16 00:36 M8 obs-local Protocol Compatibility Done

- 续跑恢复：
  - 已按 `dev-run/stage-status.md`、`progress.md`、`issue-log.md` 复核 M0-M7 均已通过。
  - 已补 `dev-plan/m8-obs-local-protocol-compat.md`，将 `obs-local` 协议兼容升级登记为正式阶段 M8。
- 已完成 `obs-local` 兼容升级：
  - `obs-local/app/aggregator.py`
    - 请求生命周期识别现在同时支持：
      - 旧协议：`event="http.request.start|end|error"`
      - 新协议：`event="start|end|error"` + `span_name="http.request"`
    - stage 名归一改为优先使用 `span_name`，继续兼容旧事件名剥后缀
    - 聚合输出的 `event` 会规范化为完整事件名，避免对外退化成裸 `start/end/error`
    - `summary_mapping` 现在同时支持按：
      - 原始 `event`
      - 规范化后的完整事件名
      - `span_name`
      进行匹配，因此旧配置如 `api.ask.start -> question` 对新协议仍然有效
    - request type、request failed / partial 判定已兼容 canonical root span
  - `obs-local/tests/test_stage2_ingestion.py`
    - 新增 canonical span 协议解析测试，覆盖 `trace_id -> request_id` fallback
  - `obs-local/tests/test_stage3_aggregator.py`
    - 新增 canonical request span 聚合测试
    - 新增 canonical request error 终止测试
    - 扩展聚合 helper，允许在测试中注入 `summary_mapping_by_project`
- 已跑验证：
  - `E:\github\mykms\.venv\Scripts\python.exe -m pytest obs-local\tests\test_stage2_ingestion.py obs-local\tests\test_stage3_aggregator.py -q`
  - 结果：`19 passed`
  - `E:\github\mykms\.venv\Scripts\python.exe -m pytest obs-local\tests -q`
  - 结果：`55 passed`
- 放行结论：
  - M8 当前范围已收口。
  - `obs-local` 已具备承接 `mykms` 后续纯 `span_name + event_type` 协议收口的消费能力。
  - 本轮未改变现有 API 语义，也未要求 `mykms` 立即切断旧事件名兼容层。

## 2026-04-16 00:50 M9 mykms Canonical Event Protocol Done

- 续跑恢复：
  - 已按 `dev-run/stage-status.md`、`progress.md`、`issue-log.md` 复核 M0-M8 均已通过。
  - 已补 `dev-plan/m9-mykms-canonical-event-protocol.md`，将 `mykms` 正式切 canonical event 协议登记为 M9。
- 已完成 canonical event 切换：
  - `app/observability.py`
    - formatter 现在对 `.start/.end/.error` 事件统一落盘：
      - `event`: 纯 `start|end|error`
      - `span_name`: 独立业务名
      - `message`: 保留完整可读事件名，如 `api.ask.end`
    - `timed_operation()` 内部 start / error / end 事件已全部改成纯事件名调用
  - `app/main.py`
    - HTTP middleware 的 `http.request` root span 已改为：
      - `log_event(LOGGER, "start", span_name="http.request", ...)`
      - `LOGGER.exception("error", extra={"context": {"event": "error", ...}})`
      - `log_event(LOGGER, "end", span_name="http.request", ...)`
    - 因此 root request span 现在正式遵守 canonical 协议，不再依赖完整事件名
  - `tests/test_observability.py`
    - 已将断言切到 canonical 契约：
      - `event` 断言纯类型
      - `message` 断言完整可读事件名
      - `span_name` 断言业务名
- 已同步文档：
  - `obs-local/docs/design_v1_claude.md`
    - 已将 canonical `event` 切换标记为完成
    - 已将 `status/end/span/timezone/rotate` 阻塞项状态同步为已修
- 已跑验证：
  - `E:\github\mykms\.venv\Scripts\python.exe -m pytest tests\test_observability.py tests\test_sqlite_timestamp_migration.py tests\test_api_indexing.py tests\test_query_endpoints.py -q`
  - 结果：`14 passed`
  - `E:\github\mykms\.venv\Scripts\python.exe -m pytest obs-local\tests -q`
  - 结果：`55 passed`
- 放行结论：
  - M9 当前范围已收口。
  - `mykms` 与 `obs-local` 现在都已切到 canonical 协议主路径。
  - 后续若继续优化，重点应转向 `attributes` 进一步纯化、`service.startup` session 边界和非 JSONL 源归一。

## 2026-04-16 01:05 M10 obs-local Launch Runbook and Starter Done

- 续跑恢复：
  - 已按 `dev-run/stage-status.md`、`progress.md`、`issue-log.md` 复核 M0-M9 均已通过。
  - 已补 `dev-plan/m10-obs-local-launch-runbook.md`，将启动入口和界面访问收口登记为 M10。
- 已完成启动入口收口：
  - `scripts/start_obs_local.py`
    - 新增 `obs-local` 一键启动脚本
    - 会读取 `obs-local/config.yaml` 的后端 host/port
    - 会启动：
      - 后端：`uvicorn app.main:app`（cwd=`obs-local/`）
      - 前端：`npm run dev -- --host 127.0.0.1 --port 4174`
    - 会等待：
      - 后端 `http://127.0.0.1:49154/api/health`
      - 前端 `http://127.0.0.1:4174`
    - 会输出前后端 URL 与日志文件位置
  - `obs-local/README.md`
    - 修正后端模块路径，不再使用错误的 `obs-local.app.main:app`
    - 修正后端端口为 `49154`
    - 修正前端页面地址为 `http://127.0.0.1:4174`
    - 明确开发模式默认走 Vite proxy，不需要额外设置 `VITE_OBS_API_BASE_URL`
- 已跑验证：
  - `E:\github\mykms\.venv\Scripts\python.exe -m py_compile scripts\start_obs_local.py`
  - `E:\github\mykms\.venv\Scripts\python.exe scripts\start_obs_local.py`
  - `GET http://127.0.0.1:49154/api/health`
  - `GET http://127.0.0.1:49154/api/overview?project=mykms`
  - `GET http://127.0.0.1:4174`
- 实机结果：
  - 后端已启动并可用：`http://127.0.0.1:49154`
  - 前端已启动并可访问：`http://127.0.0.1:4174`
  - 首页 HTML 已返回 `<title>obs-local</title>` 与 `<div id="app"></div>`
  - overview API 已返回 `mykms` 项目聚合数据，可在界面上看到内容
- 放行结论：
  - M10 当前范围已收口。
  - `obs-local` 现在已经具备“按脚本启动、按地址打开即看到界面”的最短路径。

## 2026-04-16 01:20 M11 RAG Evaluation Hardening Start

- 续跑恢复：
  - 已按 `dev-run/stage-status.md`、`progress.md`、`issue-log.md` 复核 M0-M10 均已通过。
  - 本轮新增需求聚焦为：把 `mykms` 的 RAG 效果评测从“小样本定向回归”升级为更正式的评测框架，并落地到仓库。
- 已确认当前基线：
  - `eval/benchmark.py` 当前只统计 `Recall@K`、`MRR`、总体拒答准确率与平均耗时。
  - `eval/results/*.json` 历史输出已出现比源码 dataclass 更丰富的 case 字段，源码与结果契约存在漂移。
  - `eval/README.md` 只定义了基础 benchmark，尚未把 hard-case、分组统计、拒答精确率/召回率等评测口径真正落地。
- 本轮目标：
  - 统一并扩展评测 schema，兼容现有 benchmark 文件。
  - 落地更正式的 RAG 指标：拒答精确率/召回率、误答率、误拒率、证据命中与来源覆盖。
  - 新增 hard-case benchmark 模板与使用说明。
  - 补回归测试，确保 `eval/` 输出结构稳定。
- 下一步：
  - 先补 `dev-plan/m11-rag-eval-hardening.md`。
  - 再改 `eval/benchmark.py`、`eval/run_benchmark.py`、`tests/test_eval_benchmark.py` 与 `eval/README.md`。

## 2026-04-16 01:40 M11 RAG Evaluation Hardening Done

- 已完成评测框架升级：
  - `eval/benchmark.py`
    - 继续兼容旧 benchmark schema
    - 新增增强字段：
      - `case_type`
      - `tags`
      - `min_expected_sources`
      - `expected_terms`
      - `notes`
    - 新增 case 级结果字段：
      - `question`
      - `rank`
      - `top_location`
      - `confidence`
      - `abstain_reason`
      - `source_count`
      - `expected_source_count`
      - `matched_source_count`
      - `evidence_hit`
      - `evidence_source_recall`
      - `source_count_ok`
      - `expected_term_coverage`
    - 新增总体指标：
      - `abstain_precision`
      - `abstain_recall`
      - `false_abstain_rate`
      - `false_answer_rate`
      - `evidence_hit_rate`
      - `evidence_source_recall`
      - `source_count_satisfaction_rate`
      - `expected_term_coverage`
    - 新增 `by_type`、`by_tag` 分组统计
    - 跑完 benchmark 后会显式 `close()` QueryService
  - `eval/__init__.py`
    - 导出 `MetricBreakdown`
- 已完成文档与模板收口：
  - `eval/README.md`
    - 明确当前评测边界是“检索 + 拒答 + 证据包质量”，不是宿主最终答案质量
    - 补充增强 schema、指标说明与 hard-case 设计规则
  - `eval/benchmark.sample.jsonl`
    - 改为演示增强字段的最小样例
  - `eval/benchmark.hardcase.template.jsonl`
    - 新增改写题、多文档题、干扰题、拒答题模板
  - `README.md`
    - 同步补充 `eval/` 能力说明与模板入口
- 已补测试：
  - `tests/test_eval_benchmark.py`
    - 新增增强字段解析断言
    - 新增扩展指标与 `by_type` / `by_tag` 断言
- 已跑验证：
  - `E:\github\mykms\.venv\Scripts\python.exe -m py_compile eval\benchmark.py eval\run_benchmark.py tests\test_eval_benchmark.py`
  - `E:\github\mykms\.venv\Scripts\python.exe -m pytest tests\test_eval_benchmark.py -q`
  - `E:\github\mykms\.venv\Scripts\python.exe -m pytest tests\test_eval_benchmark.py tests\test_query_service.py tests\test_query_endpoints.py -q`
  - `E:\github\mykms\.venv\Scripts\python.exe -m eval.run_benchmark --config config.yaml --benchmark eval/benchmark.sample.jsonl --output E:\github\mykms\eval\results\benchmark.sample.result.json`
- 验证结果：
  - `tests/test_eval_benchmark.py`：`2 passed`
  - 关联回归：`10 passed`
  - CLI 已输出增强后的 benchmark JSON，并写入 `eval/results/benchmark.sample.result.json`
- 放行结论：
  - M11 当前范围已收口。
  - `mykms` 现在已具备更正式的 RAG 评测骨架，可继续往 hard-case 数据扩充与宿主答案级评测演进。

## 2026-04-16 06:16 M10 Follow-up SSE Realtime Flush Fix

- 问题复现：
  - 用户反馈 `mykms` 已写入新日志，但 `obs-local` 界面没有实时更新。
  - 排查确认 ingest、聚合和 `/api/requests` 数据都正常，问题集中在 `/api/stream`。
- 根因收口：
  - `obs-local/app/web.py`
    - 运行时更新事件已先前修复为直接保留原始 `StreamEnvelope` payload 形态，不再二次包裹。
    - 进一步确认 `_iter_sse_events()` 在有 pending batch 时仍按 heartbeat 超时等待，导致更新可能要等到下一次 heartbeat 才真正发给前端。
    - 同时存在边界分支：pending flush 超时但尚未 `drain_due()` 时，会误发 heartbeat，继续推迟真实更新。
- 已完成修复：
  - `obs-local/app/web.py`
    - 增加 `batch_window_seconds`，当 batcher 已有 pending 更新时，SSE 等待时间改为 `min(heartbeat, batch_window)`
    - timeout 后优先 `drain_due()` 并立即发送 ready events
    - 若当前 timeout 是为 pending flush 服务且尚未 ready，则继续等待，不再错误发送 heartbeat
  - `obs-local/tests/test_stage4_stream.py`
    - 新增回归：`test_iter_sse_events_flushes_pending_updates_on_batch_window_before_heartbeat`
    - 覆盖“单次更新也必须在 batch window 内推送，而不是卡到 heartbeat”这一场景
- 已跑验证：
  - `E:\github\mykms\.venv\Scripts\python.exe -m pytest obs-local\tests\test_stage4_stream.py -q`
  - `E:\github\mykms\.venv\Scripts\python.exe -m pytest obs-local\tests -q`
  - 停旧进程并重启 `obs-local`
  - 实际订阅 `GET /api/stream?project=mykms&heartbeat_ms=10000&batch_window_ms=50`
  - 触发 `GET http://127.0.0.1:49153/stats`
- 实机结果：
  - SSE 已在触发请求后立即返回 `stream.batch`
  - batch 内包含 `health.updated`、`overview.updated`、`requests.updated`、`errors.updated`、`stages.updated`
  - 说明界面实时更新链路已恢复

## 2026-04-16 07:05 M12 Bilingual Locale Start

- 新需求：
  - `obs-local` 需要支持双语界面。
  - 后端可配置默认语言，前端用户可手动切换。
  - 代码内部保持英文语义 key，界面按当前语言模式动态映射。
- 本轮方案：
  - 后端新增 `ui.default_locale` 与 `/api/ui-settings`。
  - 前端新增 locale store，从后端默认值初始化，并允许 `localStorage` 覆盖。
  - 标题、按钮、空态、状态 badge、详情面板、筛选标签统一接入翻译层。
  - 技术标识如 `/ask`、`query.plan.fetch` 保持原值。
- 下一步：
  - 跑 `obs-local` API 回归。
  - 跑前端 `typecheck` / `build`。
  - 收口本轮验证结果。

## 2026-04-16 07:22 M12 Bilingual Locale Verification

- 已完成后端契约：
  - `obs-local/app/schemas.py`
    - 新增 `UiLocaleMode`
    - 新增 `UiConfig`
    - 新增 `UiSettingsResponse`
  - `obs-local/config.yaml`
    - 新增 `ui.default_locale: bilingual`
  - `obs-local/app/main.py`
    - 新增 `GET /api/ui-settings`
- 已完成前端能力：
  - `obs-local/frontend/src/stores/ui-locale.ts`
    - 新增 locale store
    - 启动时读取后端默认语言
    - 用户手动切换后写入 `localStorage`
  - `obs-local/frontend/src/utils/i18n.ts`
    - 新增统一翻译 key 与 `zh / en / bilingual` 渲染逻辑
  - `obs-local/frontend/src/utils/labels.ts`
    - 请求类型、接口名、阶段名、事件名支持本地化标签
  - `obs-local/frontend/src/views/DashboardView.vue`
    - 新增语言选择器
    - 标题、统计卡、空态、筛选器、状态说明接入双语渲染
  - `obs-local/frontend/src/components/*`
    - `AppShell`、`LiveBadge`、`ProjectRail`、`RequestList`、`ErrorList`、`StageBoard`、`RequestDetailDrawer` 已接入 locale
  - `obs-local/frontend/src/stores/observability.ts`
    - `liveNotice` 改为内部 key，不再在 store 里写死中文文案
- 已跑验证：
  - `npm run typecheck`
  - `npm run build`
  - `E:\github\mykms\.venv\Scripts\python.exe -m pytest obs-local\tests\test_stage4_api.py -q`
- 验证结果：
  - 前端类型检查通过
  - 前端生产构建通过
  - `obs-local/tests/test_stage4_api.py`：`9 passed`
- 当前结论：
  - `obs-local` 已支持后端默认语言 + 前端手动切换。
  - 当前实现已满足 `中文 / English / 双语` 三种模式。
  - 技术标识仍保留原始值，未被硬翻。

## 2026-04-16 07:48 M12 Headless Dropdown Refactor

- 用户反馈：
  - 语言切换之外，页面其余下拉控件仍带明显浏览器默认气质，与当前控制台视觉不协调。
- 处理策略：
  - 采用 headless 交互底座，不再继续手搓原生下拉。
  - 在 `obs-local/frontend/package.json` 引入 `@headlessui/vue`。
  - 新增统一控件：
    - `obs-local/frontend/src/components/ControlSelect.vue`
    - `obs-local/frontend/src/components/ControlCombobox.vue`
  - `DashboardView.vue` 中所有原生 `select` 与 `datalist` 已替换为上述组件。
- 当前覆盖：
  - 时间窗选择
  - 请求筛选：路径、方法、状态、类型
  - 错误筛选：路径、错误类型、状态码
  - 阶段筛选：阶段名
- 已跑验证：
  - `npm run typecheck`
  - `npm run build`
  - `rg -n "<select|datalist|HTMLSelectElement" obs-local/frontend/src -S`
- 结果：
  - 前端源码中已无原生 `select` / `datalist`
  - Headless UI 替换后类型检查与构建均通过

## 2026-04-15 M12 Retrieval Hot-Path Batching Start

- 续跑恢复：
  - 已按 `dev-run/stage-status.md`、`progress.md`、`issue-log.md` 复核 M0-M11 已通过。
  - 本轮新增需求聚焦为：优化 `embedding.encode` 与 `reranker.score` 热路径，但不接受真实集质量回退。
- 已确认当前质量门基线：
  - `eval/results/benchmark.ai.real10.m11.result.json`
    - `recall_at_k=1.0`
    - `mrr=1.0`
    - `abstain_accuracy=1.0`
    - `false_abstain_rate=0.0`
    - `false_answer_rate=0.0`
  - `eval/results/benchmark.distributed.real10.m11.result.json`
    - `recall_at_k=1.0`
    - `mrr=0.9167`
    - `abstain_accuracy=1.0`
    - `false_abstain_rate=0.0`
    - `false_answer_rate=0.0`
  - `eval/results/benchmark.game.real10.m11.result.json`
    - `recall_at_k=1.0`
    - `mrr=0.9444`
    - `abstain_accuracy=1.0`
    - `false_abstain_rate=0.0`
    - `false_answer_rate=0.0`
- 本轮实施范围：
  - 多 query 语义检索改为 batched embedding + batched Chroma query。
  - embedding / reranker 增加 batch size 配置。
  - 保持当前多 query 分别 rerank 再合并的语义不变。
- 下一步：
  - 改 `app/retrieve/semantic.py`、`app/retrieve/hybrid.py`、`app/services/embeddings.py`、`app/retrieve/rerank.py`、`app/config.py`。
  - 补回归测试并跑 3 组 real10 benchmark。

## 2026-04-15 M12 Retrieval Hot-Path Batching Done

- 已完成实现：
  - `app/retrieve/semantic.py`
    - 新增 batched `search_many()`，对多 query 一次做 embedding、一次做 Chroma query，再按 query 拆结果。
  - `app/retrieve/hybrid.py`
    - 多 query 检索时优先走 batched semantic 路径。
    - 保持原有“多 query 分别 rerank，再按最佳分数合并”的语义不变。
  - `app/services/embeddings.py`
    - 增加 `batch_size` 配置，并兼容不支持该参数的旧签名 fallback。
  - `app/retrieve/rerank.py`
    - 增加 `batch_size` 配置，并优先使用带 `batch_size` 的 scoring 调用。
  - `app/config.py` / `config.yaml`
    - 新增：
      - `models.embedding_batch_size`
      - `models.reranker_batch_size`
  - `app/services/indexing.py`
    - 索引期 embedding 复用统一 batch 配置。
- 已补回归测试：
  - `tests/test_retrieval_m2.py`
    - 覆盖 batched semantic query 只做一次 embedding
    - 覆盖多 query 检索优先走 `search_many()`
    - 覆盖 reranker 使用配置化 `batch_size`
- 已跑验证：
  - `E:\github\mykms\.venv\Scripts\python.exe -m py_compile app\config.py app\services\embeddings.py app\retrieve\semantic.py app\retrieve\rerank.py app\retrieve\hybrid.py app\services\indexing.py tests\test_retrieval_m2.py`
  - `E:\github\mykms\.venv\Scripts\python.exe -m pytest tests\test_retrieval_m2.py tests\test_query_service.py tests\test_runtime_behaviors.py -q`
  - `Get-ChildItem .\tests -Filter 'test_*.py' | ForEach-Object { $_.FullName } | python -m pytest ... -q`
  - `E:\github\mykms\.venv\Scripts\python.exe -m eval.run_benchmark --config config.yaml --benchmark eval/benchmark.ai.real10.jsonl --output eval/results/benchmark.ai.real10.m12.result.json`
  - `E:\github\mykms\.venv\Scripts\python.exe -m eval.run_benchmark --config config.yaml --benchmark eval/benchmark.distributed.real10.jsonl --output eval/results/benchmark.distributed.real10.m12.result.json`
  - `E:\github\mykms\.venv\Scripts\python.exe -m eval.run_benchmark --config config.yaml --benchmark eval/benchmark.game.real10.jsonl --output eval/results/benchmark.game.real10.m12.result.json`
- 验证结果：
  - 定向回归：`22 passed`
  - `tests/` 显式文件列表全量回归：`60 passed`
  - 3 组 real10 质量门均未回退：
    - `ai`
      - `recall_at_k=1.0`
      - `mrr=1.0`
      - `abstain_accuracy=1.0`
      - `false_abstain_rate=0.0`
      - `false_answer_rate=0.0`
      - `avg_search_latency_ms: 2282.32 -> 1983.76`
    - `distributed`
      - `recall_at_k=1.0`
      - `mrr=0.9167`
      - `abstain_accuracy=1.0`
      - `false_abstain_rate=0.0`
      - `false_answer_rate=0.0`
      - `avg_search_latency_ms: 1953.81 -> 1947.04`
    - `game`
      - `recall_at_k=1.0`
      - `mrr=0.9444`
      - `abstain_accuracy=1.0`
      - `false_abstain_rate=0.0`
      - `false_answer_rate=0.0`
      - `avg_search_latency_ms: 1875.27 -> 1917.23`
- 评审记录：
  - Review A（协议 / 数据语义 / 边界）：
    - 确认 batched semantic query 仍按 query 维度拆回结果，没有改变 RRF 与多 query rerank 的输入语义。
  - Review B（实现 / 回归 / 运行时）：
    - 确认 embedding / reranker 的 `batch_size` 都保留旧签名 fallback。
    - 确认 `tests/` 全量显式文件回归与 3 组 real10 benchmark 均通过。
- 额外说明：
  - `python -m pytest -q` 在当前仓库仍存在既有收集问题：会按 `tests.test_*` 形式导入失败。
  - 本轮改用显式文件列表执行 `tests/` 全量回归，不把该既有问题视为本轮阻塞。
- 放行结论：
  - M12 当前范围已收口。
  - 已完成保守性能优化，当前不需要回退本轮代码。

## 2026-04-15 M12.1 默认 pytest 收集修复

- 背景：
  - 根目录 `python -m pytest -q` 会同时收集 `tests/` 与 `obs-local/tests/`。
  - `obs-local/tests` 在模块导入时会把 `obs-local` 插到 `sys.path[0]`，与主项目顶层包 `app` 冲突，导致根项目默认 pytest 行为不稳定。
- 处理：
  - 在 `pyproject.toml` 新增 `[tool.pytest.ini_options] testpaths = ["tests"]`。
  - 在 `README.md` 明确：根目录默认 pytest 只跑主项目，`obs-local` 子项目单独执行。
- 验证：
  - `E:\github\mykms\.venv\Scripts\python.exe -m pytest -q`
  - `E:\github\mykms\.venv\Scripts\python.exe -m pytest tests -q`
  - `E:\github\mykms\.venv\Scripts\python.exe -m pytest obs-local\tests -q`
- 结果：
  - 根目录默认 pytest 已恢复为 `60 passed`。
  - `obs-local` 子项目独立回归仍为 `58 passed`。
