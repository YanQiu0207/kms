# A3 检索闭环、自适应融合与别名自动提取

## 背景

- 用户明确要求连续完成 3 项：
  1. M19 失败 case 自动闭环
  2. Query-type 自适应融合
  3. 别名自动提取
- 约束：
  - 必须补足测试用例
  - 质量不能回退
  - 不能通过修改既有 benchmark / golden case / 断言口径来换取更好指标

## 本轮范围

### 1. M19 失败 case 自动闭环

- 增加 failure record -> case draft / backlog 的转换能力
- 支持 benchmark case 携带 `linked_issue_ids`
- 支持按现有 benchmark 覆盖情况生成“未入集失败 case” backlog
- 提供 CLI 入口，输出 summary JSON 与 candidate case JSONL

### 2. Query-type 自适应融合

- 为 `definition / lookup / existence / procedure / comparison` 引入可配置 lexical / semantic RRF 权重
- 保持现有 RRF、rerank、guardrail 总流程不变
- 只改 fusion 贡献权重，不改 benchmark 口径

### 3. 别名自动提取

- 从 SQLite 文档 metadata 的 front matter `aliases` 自动构建 alias groups
- QueryService 负责加载和缓存动态 alias groups
- Query understanding 与 ranking pipeline 一致消费动态 alias groups
- 保留静态 alias groups 作为 fallback，避免现有能力退化

## 验证策略

1. 单元测试：
   - failure draft / backlog 生成
   - query-type 融合权重生效
   - alias 自动提取、缓存与 query expansion
2. 定向回归：
   - `tests/test_eval_benchmark.py`
   - `tests/test_eval_suite.py`
   - `tests/test_query_understanding.py`
   - `tests/test_query_service.py`
   - `tests/test_retrieval_m2.py`
3. 全量回归：
   - `pytest -q`
4. 权威质量门：
   - `eval.run_benchmark_suite --suite eval/benchmark-suite.m18.json`

## 放行标准

- 新增测试全部通过
- 全量 `pytest` 通过
- suite `passed_entries=8/8`
- suite `passed_gated_entries=7/7`
- 未修改既有 benchmark 样本、golden case 或断言口径
