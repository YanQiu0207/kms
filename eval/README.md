# RAG 评测

本目录用于评估 `mykms` 的 RAG 效果，当前重点覆盖：

- 检索命中与排序质量
- `/ask` 的拒答正确性
- `/ask` 返回证据包对预期来源的覆盖度
- 按题型与标签的分组统计

边界说明：

- 当前评测的是 `mykms` 自身的检索、拒答与证据包质量。
- 由于 `/ask` 返回的是 `prompt + sources`，不是宿主模型最终答案，所以这里还不是完整的 answer-level 评测。
- 若后续要评“最终答案正确率”，需要再接宿主模型生成和人工/模型裁判链路。

## 文件

- `benchmark.sample.jsonl`：最小可跑样例，演示增强字段
- `benchmark.hardcase.template.jsonl`：hard-case 模板，供扩题时复制
- `benchmark.ai*.jsonl`：AI 主题基准集
- `benchmark.distributed*.jsonl`：分布式主题基准集
- `benchmark.game*.jsonl`：游戏开发主题基准集
- `run_benchmark.py`：本地 benchmark CLI
- `results/*.json`：最近一次 benchmark 结果快照

## Case Schema

每行一个 JSON 对象。最低兼容字段仍然是：

```json
{
  "id": "q-001",
  "question": "为什么个人知识库不能只做向量检索？",
  "queries": ["为什么个人知识库不能只做向量检索？", "混合检索 优势"],
  "expected_file_paths": ["E:/work/blog/ai/prompt-engineering.md"],
  "should_abstain": false
}
```

推荐使用增强字段：

```json
{
  "id": "rewrite-001",
  "question": "混合检索为什么更稳？",
  "queries": ["混合检索为什么更稳？", "hybrid retrieval 优势"],
  "expected_file_paths": ["E:/work/blog/ai/prompt-engineering.md"],
  "should_abstain": false,
  "case_type": "rewrite",
  "tags": ["rewrite", "ai"],
  "min_expected_sources": 1,
  "expected_terms": ["词法检索", "语义检索"],
  "notes": "用于验证改写问法下的证据命中与术语覆盖"
}
```

字段说明：

- `id`：唯一 case 标识
- `question`：传给 `/ask` 的问题
- `queries`：传给 `/search` / `/ask` 的查询变体；为空时会退回 `question`
- `expected_chunk_ids`：更细粒度的预期 chunk 标识
- `expected_file_paths`：文档级预期来源路径；常用于真实集
- `should_abstain`：语料中应拒答时设为 `true`
- `case_type`：题型，例如 `lookup`、`rewrite`、`multi_doc`、`distractor`、`abstain`
- `tags`：自由标签，例如主题、难度、风险点
- `min_expected_sources`：非拒答题最少希望返回多少条来源
- `expected_terms`：希望在返回证据中出现的关键术语，用于证据覆盖代理指标
- `notes`：备注，不参与评分

约束建议：

- `expected_chunk_ids` 和 `expected_file_paths` 二选一即可；若同时使用，结果会按两套目标一起计数。
- 对 hard-case，优先补 `case_type`、`tags`、`expected_terms`，否则分组统计价值有限。

## 输出指标

`eval.run_benchmark` 当前会输出：

- `recall_at_k`：非拒答题中，预期来源是否进入检索结果
- `mrr`：非拒答题中，预期来源排名质量
- `abstain_accuracy`：总体拒答判断是否正确
- `abstain_precision`：系统判拒答的样本里，有多少真的该拒答
- `abstain_recall`：所有该拒答样本里，有多少被系统拒答
- `false_abstain_rate`：本该回答却被拒答的比例
- `false_answer_rate`：本该拒答却继续回答的比例
- `evidence_hit_rate`：非拒答题中，`ask.sources` 是否命中至少一个预期来源
- `evidence_source_recall`：非拒答题中，返回证据对预期来源的平均覆盖率
- `source_count_satisfaction_rate`：满足 `min_expected_sources` 的比例
- `expected_term_coverage`：返回证据对 `expected_terms` 的平均覆盖率
- `avg_search_latency_ms`
- `avg_ask_latency_ms`
- `by_type`
- `by_tag`

说明：

- `evidence_*` 与 `expected_term_coverage` 是“证据包质量代理指标”，不是最终答案质量。
- `by_type` 与 `by_tag` 可用来观察改写题、多文档题、拒答题、干扰题在哪些类别上掉点。

## Hard Case 设计

建议至少覆盖以下题型：

- `rewrite`
  - 同义改写、口语化、英文缩写、大小写变化
- `multi_doc`
  - 需要两个或更多文档共同支撑的问题
- `distractor`
  - 文档里有高度相关术语，但缺关键条件，容易误答
- `abstain`
  - 主题相关但语料里没有答案，验证是否稳住拒答

建议补题方式：

1. 每个主题至少 10 条基础题，再补 10 条 hard-case。
2. 每类 hard-case 至少保留 2 到 3 条可复现样本。
3. 负样本不要只做完全无关题，更要做“半相关误导题”。
4. 对多文档题，尽量补 `min_expected_sources` 与多个 `expected_file_paths`。

## 运行方式

```powershell
.\.venv\Scripts\python.exe -m eval.run_benchmark `
  --config config.yaml `
  --benchmark eval/benchmark.sample.jsonl
```

输出结果写文件：

```powershell
.\.venv\Scripts\python.exe -m eval.run_benchmark `
  --config config.yaml `
  --benchmark eval/benchmark.sample.jsonl `
  --output eval/results/benchmark.sample.result.json
```

可选重建索引：

```powershell
.\.venv\Scripts\python.exe -m eval.run_benchmark `
  --config config.yaml `
  --benchmark eval/benchmark.sample.jsonl `
  --reindex incremental
```

## 当前状态

- 已兼容旧 benchmark schema
- 已支持增强字段、分组统计与 hard-case 模板
- 已保留真实主题 benchmark 结果快照：
  - `eval/results/benchmark.ai.result.json`
  - `eval/results/benchmark.distributed.result.json`
  - `eval/results/benchmark.game.result.json`
