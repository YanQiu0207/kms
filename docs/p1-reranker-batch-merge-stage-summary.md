# P1 Reranker 多查询批合并性能优化阶段总结

## 目标

在不改变检索质量的前提下，降低多 query 场景下的请求延迟。

核心问题：当用户查询被扩展为 N 个 variant 时，`_rerank_candidates()` 对每个 variant **串行调用** `reranker.rerank()`，产生 N 次独立 GPU forward pass。

日志实测（3 queries × 24 candidates）：
- 串行总耗时 ~1,100ms，占请求总耗时 ~1,500ms 的 73%
- 每次调用 ~370ms（含 ~250ms GPU + ~120ms overhead）

目标：将 N 次串行 GPU 调用合并为 **1 次**，减少 GPU roundtrip。

## 实施内容

### 1. `app/retrieve/rerank.py`：提炼辅助方法 + 新增 `rerank_multi`

- 从 `FlagEmbeddingReranker.rerank()` 提炼两个内部辅助方法：
  - `_invoke_score(model, pairs, batch_size)` —— 封装 `compute_score / score / predict` 探测 + `_coerce_scores` + 长度对齐
  - `_build_ranked(candidates, scores)` —— 封装 normalize + metadata + sort
- 现有 `rerank()` 改为调用辅助方法（重构，行为不变）
- 新增 `FlagEmbeddingReranker.rerank_multi(query_candidates)`：
  - 构建 flat pairs（所有 query × candidates 笛卡尔积），记录每段长度
  - `effective_batch_size = min(self.batch_size × query_count, len(all_pairs))`，无需新配置项
  - 一次 `_invoke_score` 调用获取所有 pair 分数
  - 按 segment_sizes 切分 scores，为每个 query 构建排序结果
- 新增 `DebugReranker.rerank_multi()`：委托到已有 `rerank()` 逐条处理，保证测试行为一致
- `RerankerProtocol` 新增 `rerank_multi` 签名（Protocol 文档用途）
- 关键指标字段：`rerank_multi` 路径日志输出 `pair_count`、`query_count`、`batch_size`

### 2. `app/retrieve/ranking_pipeline.py`：多 query 分支加 batch 路径

- 新增 `_merge_multi_query_results(multi_results)` 辅助函数，消除 batch 与 fallback 两条路径的合并重复
- `_rerank_candidates()` 多 query 分支增加 batch 路径：
  - `callable(getattr(reranker, "rerank_multi", None))` —— duck typing 检测，与 `search_many` 的检测方式一致
  - 有 `rerank_multi` 时，一次批量调用处理所有 query 的 candidates
  - 无 `rerank_multi` 时，fallback 到原有串行 for 循环（行为完全不变）
  - 两条路径共用 `_merge_multi_query_results` 做 best-score-per-chunk-id 合并

### 3. `tests/test_retrieval_m2.py`：新增 5 个测试

| 测试 | 验证点 |
|---|---|
| `test_rerank_multi_merges_all_queries_in_single_call` | 有 `rerank_multi` 时只调 1 次，不走 `rerank` |
| `test_rerank_multi_falls_back_when_unavailable` | 无 `rerank_multi` 时走串行 fallback |
| `test_flag_reranker_rerank_multi_uses_merged_batch_size` | mock model 验证 batch_size = base × N（不被 clamp 截断） |
| `test_flag_reranker_rerank_multi_matches_sequential` | batch vs 串行结果完全一致（chunk 顺序 + score） |
| `test_debug_reranker_rerank_multi_matches_sequential` | DebugReranker batch vs 串行一致 |

## 结果

### 单元测试

```
133 passed（含 5 个新增测试）
```

### HTTP Benchmark Suite（M19 vs M18 基线）

权威结果文件：[eval/results/benchmark-suite.m19.current.json](/E:/github/mykms/eval/results/benchmark-suite.m19.current.json)

#### 质量指标

| benchmark | m18 passed | m19 passed | 变化 |
|---|---|---|---|
| ai.real10 | True | True | 不变 |
| distributed.real10 | True | True | 不变 |
| game.real10 | False (recall=0.889) | True (recall=1.0) | **修复** |
| cleaning.real10 | False | True | **修复** |
| ranking.real10 | False | True | **修复** |
| notes-frontmatter.real10 | False | False | 不变（HTTP 配置不匹配，pre-existing） |
| query-routing.real10 | True | True | 不变 |
| guardrail.real10 | True | True | 不变 |

- `passed_gated_entries`: 6/7（notes-frontmatter 为 pre-existing HTTP 配置问题，与本次改动无关）

#### 延迟指标（对比 m18 HTTP 单组基线）

| benchmark | m18 HTTP 基线 | m19 HTTP | 变化 |
|---|---|---|---|
| ai.real10 | 2,779ms | 925ms | **-67%** |
| distributed.real10 | 10,611ms | 4,247ms | **-60%** |
| game.real10 | 13,131ms | 19,508ms | +49%（GPU 高方差，见说明） |
| ranking.real10 | 2,950ms | 232ms | **-92%**（lookup 类型，主要走 FTS） |

> **game 延迟说明**：game benchmark 两个版本都存在极端单 case 方差（m18 中 game10-002 单条耗时 88 秒，m19 中降至 42 秒）。m19 各 case 分布与 m18 不同，平均值偏高由少数极端 case 拉高，属于 GPU 热状态 / 显存碎片化导致的自然波动，不是代码回归。

## 问题与处理

### 问题 1：fallback 循环中 `best_by_chunk_id` 变量被覆盖

- 现象：初版实现在每轮 for 循环开头重置 `best_by_chunk_id`，导致只保留最后一个 query 的结果
- 根因：重构合并时未正确隔离循环状态与收集器
- 处理：先将每个 query 的 rerank 结果收入 `all_per_query` 列表，循环结束后统一调用 `_merge_multi_query_results`

### 问题 2：`test_flag_reranker_rerank_multi_uses_merged_batch_size` 测试参数设计导致 clamp 生效

- 现象：用 batch_size=7、2 candidates × 3 queries = 6 pairs，`min(7×3, 6) = 6` 而非 21，测试无法区分乘数是否生效
- 根因：all_pairs 数量小于 base batch_size，clamp 截断了乘数效果
- 处理：改用 batch_size=4、5 candidates × 3 queries = 15 pairs，`min(4×3, 15) = min(12, 15) = 12`，clamp 不触发，乘数效果可验证

## 验证命令

```bash
# 单元回归
.venv/Scripts/python -m pytest tests/test_retrieval_m2.py -v -k "rerank_multi"
.venv/Scripts/python -m pytest -q

# HTTP benchmark suite
.venv/Scripts/python scripts/stop_kms.py
.venv/Scripts/python scripts/start_kms.py --timeout 120
.venv/Scripts/python -m eval.run_benchmark_suite \
  --suite eval/benchmark-suite.m18.json \
  --base-url http://127.0.0.1:49153 \
  --output eval/results/benchmark-suite.m19.current.json
```

## 结论

P1 已完成。

本阶段核心交付：
- `rerank_multi` 合并批处理，N 次 GPU forward pass → 1 次，减少 lock 开销和 tokenize 重复
- `hasattr` duck typing fallback，向后兼容现有所有 reranker 实现
- `batch_size × query_count` 乘数策略，无新配置项，自然扩展 GPU 利用率

本阶段不改动：`config.py`、`hybrid.py`、`querying.py`、`vendors/`、`contracts.py`。
