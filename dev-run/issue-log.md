# Issue Log

## 2026-04-15

### ISSUE-M7-001 删除宿主全文模式接口与 skill

- 状态：Resolved
- 需求：
  - 删除 `kms-full-file-assistant` 技能。
  - 删除仓库中的 `/ask-files` 接口及其逻辑。
- 设计决策：
  - 不改写 M6 历史记录，新增 M7 作为显式撤回阶段。
  - 直接删除 schema、service、route、模板、示例和测试，不保留软废弃壳接口。
  - 本机 skill 与仓库代码分开收口，分别验证。
- 落地：
  - `app/schemas.py`
  - `app/services/querying.py`
  - `app/main.py`
  - `app/adapters/reference/api.md`
  - `README.md`
  - `tests/test_query_service.py`
  - `tests/test_query_endpoints.py`
  - `tests/test_adapter_assets.py`
  - 删除 `app/adapters/codex/kms-full-file.md`
  - 删除 `scripts/ask-files-context.json`
  - 删除 `C:\Users\YanQi\.codex\skills\kms-full-file-assistant`
- 验证：
  - `E:\github\mykms\.venv\Scripts\python.exe -m pytest tests\test_query_service.py tests\test_query_endpoints.py tests\test_adapter_assets.py -q`
  - `Test-Path C:\Users\YanQi\.codex\skills\kms-full-file-assistant`
- 结果：
  - `/ask-files` 相关接口、实现、模板、示例和测试已全部移除。
  - 本机 `kms-full-file-assistant` skill 已删除。

### ISSUE-M6-001 宿主全文模式接口与 skill 新增

- 状态：Resolved
- 需求：
  - 新增一个接口，只返回候选文件，由 skill 层读取本地全文回答。
  - 新增一个对应的 Codex skill。
- 设计决策：
  - 不修改现有 `/ask` 语义。
  - 新增 `POST /ask-files`，复用现有检索、rerank、拒答与 coverage 逻辑。
  - 通过 SQLite `documents` 表回查文档级 `file_path`，避免重新扫盘。
- 落地：
  - `app/schemas.py`
  - `app/services/querying.py`
  - `app/main.py`
  - `app/adapters/reference/api.md`
  - `README.md`
  - `app/adapters/codex/kms-full-file.md`
  - `scripts/ask-files-context.json`
  - `C:\Users\YanQi\.codex\skills\kms-full-file-assistant`
- 验证：
  - `python C:\Users\YanQi\.codex\skills\.system\skill-creator\scripts\quick_validate.py C:\Users\YanQi\.codex\skills\kms-full-file-assistant`
  - `E:\github\mykms\.venv\Scripts\python.exe -m pytest tests\test_query_service.py tests\test_query_endpoints.py tests\test_adapter_assets.py -q`
- 结果：
  - 新接口可返回去重后的候选文件及可读本地绝对路径。
  - 新 skill 已可被 Codex 自动发现并通过结构校验。

### ISSUE-REG-001 冷启动依赖 Hugging Face 在线元数据

- 状态：Resolved
- 现象：
  - 旧进程存活时接口可用。
  - 杀掉旧进程后，默认 `scripts/start_kms.py` 冷启动失败。
  - 日志显示 warmup 阶段加载 `BAAI/bge-m3` 时访问 `huggingface.co/.../tokenizer_config.json`，并因 SSL 失败超时。
- 根因：
  - vendor 层虽然配置了 cache 目录，但冷启动仍以 repo id 触发第三方库的在线元数据探测。
  - 对本地 snapshot 路径加载时，`FlagAutoModel` 又会因为 revision hash 无法自动推断 `model_class`。
- 修复：
  - `app/vendors/flag_embedding.py`
  - 优先解析本地 Hugging Face snapshot 路径
  - 对 `bge-m3` 的本地 snapshot 显式传入 `model_class=encoder-only-m3`
  - 保留旧版签名兼容 fallback
- 验证：
  - `.\.venv\Scripts\python.exe -m pytest tests\test_vendor_boundaries.py`
  - `.\.venv\Scripts\python.exe scripts\start_kms.py`

### ISSUE-REG-002 真实集仍有误拒答与个别漏召回

- 状态：Resolved
- 现象：
  - `distributed` 集拒答准确率仅 `0.8`
  - `game` 集拒答准确率仅 `0.9`
  - `distributed` 集 `Recall@K` 为 `0.875`
- 典型 case：
  - `dist10-004`：命中文档但因 `top1_score_below_threshold` 误拒答
  - `dist10-005`：未命中预期 `true-time.md`，且因 `evidence_chars_below_threshold` 拒答
  - `game10-008`：命中文档但因 `evidence_chars_below_threshold` 误拒答
- 证据：
  - `eval/results/benchmark.distributed.real10.http.result.json`
  - `eval/results/benchmark.game.real10.http.result.json`
- 下一步建议：
  - 审查 `app/answer/guardrail.py` 的拒答阈值与字符数规则
 - 复查 `TrueTime` 查询的 query expansion 与 rerank 候选策略
 - 追加定位（2026-04-15 20:24）：
   - 已通过临时结构化日志 `retrieval.search_and_rerank.preview` 与 `query.ask.guardrail` 确认：
   - `dist10-004` 根因是 guardrail 过严，不是召回失败。
   - `game10-008` 根因是 `min_total_chars=200` 导致短证据误拒答。
   - `dist10-005` 根因优先级更高的是 rerank/输出过滤错误：
     - fused 阶段能召回 `true-time.md`
     - 最终 reranked/filtered 结果只剩 `raft_learning_plan.md:31-33`
     - guardrail 在此基础上因 `total_chars=10` 再次拒答
 - 观察性缺口：
   - `app/answer/prompt.py` 在 abstain 时返回 `chunks=()`，导致 `/ask` 响应 `sources=[]`，不利于线上排障。
- 收口（2026-04-15 20:40）：
  - 已修复 `dist10-005`：
    - `app/retrieve/hybrid.py` 改为多 query 分别 rerank，再按最佳分数合并。
  - 已修复 `dist10-004` 与 `game10-008`：
    - `top1_min` 下调到 `0.20`
    - `min_total_chars` 下调到 `150`
  - 已修复 `dist10-010`：
    - `app/services/querying.py` 新增基于 query 术语覆盖的拒答拦截
    - 新配置项落到 `config.yaml`：
      - `abstain.min_query_term_count`
      - `abstain.min_query_term_coverage`
  - 验证结果：
    - 3 组 `real10` HTTP 真实集全部恢复为 `Recall@K=1.0`
    - 3 组 `real10` HTTP 真实集拒答准确率全部恢复为 `1.0`
  - 剩余说明：
    - `distributed` 的 `MRR=0.9167` 由 `dist10-006` 拉低。
    - 该 case 的 top1 是 `3pc.md` 背景段，内容本身就在解释 `2PC` 的主要问题，更像 benchmark 标注口径差异，不是当前实现缺陷。

### ISSUE-M11-001 RAG 评测骨架偏检索回归，缺少正式效果指标

- 状态：Resolved
- 现象：
  - `eval/benchmark.py` 仅统计 `Recall@K`、`MRR`、总体拒答准确率与平均耗时。
  - `eval/README.md` 未把 hard-case、分组统计、证据覆盖代理指标真正落地。
  - 历史 `eval/results/*.json` 已出现比源码 dataclass 更丰富的字段，源码与结果契约漂移。
- 设计决策：
  - 保持旧 benchmark schema 兼容，不要求历史 JSONL 先改写。
  - 新增增强字段，但把评测边界明确限定在“检索 + 拒答 + 证据包质量”，不伪装成最终答案级评测。
  - 通过 `case_type` 与 `tags` 做分组统计，让 hard-case 能直接进同一套结果框架。
- 落地：
  - `eval/benchmark.py`
  - `eval/__init__.py`
  - `eval/README.md`
  - `eval/benchmark.sample.jsonl`
  - `eval/benchmark.hardcase.template.jsonl`
  - `README.md`
  - `tests/test_eval_benchmark.py`
- 验证：
  - `E:\github\mykms\.venv\Scripts\python.exe -m py_compile eval\benchmark.py eval\run_benchmark.py tests\test_eval_benchmark.py`
  - `E:\github\mykms\.venv\Scripts\python.exe -m pytest tests\test_eval_benchmark.py tests\test_query_service.py tests\test_query_endpoints.py -q`
  - `E:\github\mykms\.venv\Scripts\python.exe -m eval.run_benchmark --config config.yaml --benchmark eval/benchmark.sample.jsonl --output E:\github\mykms\eval\results\benchmark.sample.result.json`
- 结果：
  - 旧 benchmark 文件仍可继续运行。
  - 结果摘要现在可输出拒答精确率/召回率、误答率/误拒率、证据命中率、来源覆盖率、术语覆盖率及 `by_type` / `by_tag` 分组统计。
  - 仓库内已补可直接扩展的 hard-case 模板。

### ISSUE-M12-001 `embedding.encode` 与 `reranker.score` 热路径重复计算

- 状态：Resolved
- 现象：
  - 单次 `embedding.encode` 平均耗时约 `100ms`。
  - 多 query 请求会对每个 query 单独做语义 embedding，并对每个 query 单独跑全量 rerank。
  - 当前 `reranker.score` 也是主要热路径之一。
- 设计决策：
  - 先做保守优化，不改多 query rerank 语义。
  - 仅把多 query semantic 路径改成 batched embedding 与 batched vector query。
  - 增加 embedding / reranker batch size 配置，并保留对旧 vendor 签名的 fallback。
  - 以 3 组 `real10` benchmark 作为质量门；若质量回退则回退本轮代码。
- 目标质量门：
  - `benchmark.ai.real10`
  - `benchmark.distributed.real10`
  - `benchmark.game.real10`
  均不允许以下指标回退：
  - `recall_at_k`
  - `mrr`
  - `abstain_accuracy`
  - `false_abstain_rate`
  - `false_answer_rate`
- 落地：
  - `app/config.py`
  - `config.yaml`
  - `app/services/embeddings.py`
  - `app/retrieve/semantic.py`
  - `app/retrieve/rerank.py`
  - `app/retrieve/hybrid.py`
  - `app/services/indexing.py`
  - `tests/test_retrieval_m2.py`
  - `dev-plan/m12-retrieval-hotpath-batching.md`
- 验证：
  - `E:\github\mykms\.venv\Scripts\python.exe -m py_compile app\config.py app\services\embeddings.py app\retrieve\semantic.py app\retrieve\rerank.py app\retrieve\hybrid.py app\services\indexing.py tests\test_retrieval_m2.py`
  - `E:\github\mykms\.venv\Scripts\python.exe -m pytest tests\test_retrieval_m2.py tests\test_query_service.py tests\test_runtime_behaviors.py -q`
  - `Get-ChildItem .\tests -Filter 'test_*.py' | ForEach-Object { $_.FullName } | python -m pytest ... -q`
  - `E:\github\mykms\.venv\Scripts\python.exe -m eval.run_benchmark --config config.yaml --benchmark eval/benchmark.ai.real10.jsonl --output eval/results/benchmark.ai.real10.m12.result.json`
  - `E:\github\mykms\.venv\Scripts\python.exe -m eval.run_benchmark --config config.yaml --benchmark eval/benchmark.distributed.real10.jsonl --output eval/results/benchmark.distributed.real10.m12.result.json`
  - `E:\github\mykms\.venv\Scripts\python.exe -m eval.run_benchmark --config config.yaml --benchmark eval/benchmark.game.real10.jsonl --output eval/results/benchmark.game.real10.m12.result.json`
- 结果：
  - 多 query 语义检索现在会 batched 做 embedding 与 Chroma query。
  - embedding / reranker 现在支持配置化 `batch_size`，并保留旧签名 fallback。
  - 3 组 real10 benchmark 的核心质量指标均未回退。
  - `ai` / `distributed` 平均 `search` 延迟下降，`game` 平均 `search` 延迟有轻微波动，但未触发质量回退门。
  - 未触发回退条件，本轮代码保留。

### ISSUE-M12-002 根目录默认 `pytest` 收集被 `obs-local` 子项目污染

- 状态：Resolved
- 现象：
  - `E:\github\mykms\.venv\Scripts\python.exe -m pytest -q` 在仓库根目录会报收集错误。
  - 根因不是缺少 `pytest`，而是默认同时收集了 `tests/` 与 `obs-local/tests/`。
  - `obs-local/tests` 会在导入期把 `obs-local` 根路径插到 `sys.path[0]`，与主项目同名顶层包 `app` 产生冲突。
- 设计决策：
  - 根目录默认 pytest 仅服务主项目 `kms-api` 主链路。
  - `obs-local` 作为独立子项目，继续通过显式路径单独跑测试。
- 落地：
  - `pyproject.toml`
  - `README.md`
- 验证：
  - `E:\github\mykms\.venv\Scripts\python.exe -m pytest -q`
  - `E:\github\mykms\.venv\Scripts\python.exe -m pytest tests -q`
  - `E:\github\mykms\.venv\Scripts\python.exe -m pytest obs-local\tests -q`
- 结果：
  - 根目录默认 pytest 已恢复通过。
  - 主项目与 `obs-local` 子项目仍可分别独立回归。
