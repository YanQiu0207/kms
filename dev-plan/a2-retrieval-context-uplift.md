# A2 检索上下文增强

## 背景

- 用户要求分析 `docs/retrieval-pipeline-gap-analysis.md` 中“第一梯队——ROI 最高，建议优先做”的改进项。
- 约束是：如果值得做就处理，但必须保证原有效果不下降。

## 本轮范围

只做两项低风险高收益改动：

1. Parent Document Retrieval
2. 非 LLM 版 Contextual Chunking

本轮明确不做：

- BGE-M3 sparse 三路召回
- 改 benchmark 样本、评测口径、golden case、断言
- 改 lexical / RRF / rerank 主排序逻辑

## 设计

### 1. Parent Document Retrieval

- 触发点：`/ask` 已经完成检索、rerank 和 guardrail 放行之后。
- 做法：
  - 以 top chunks 为锚点；
  - 从 SQLite metadata store 读取同 `document_id` 下的 chunks；
  - 优先扩展同 `section_index` 的相邻 chunk；
  - 若同 section 不足，再按 `chunk_index` 补 1 阶相邻窗口；
  - 最终仍按原命中顺序回填到 prompt source，不改 top result 排序语义。
- 风险控制：
  - 不改 `/search` 返回排序；
  - 不改 guardrail 输入，避免把“证据扩展”错误算进“是否可答”判断；
  - prompt source 仍保留原始命中 chunk 作为锚点，只扩正文窗口。

### 2. 非 LLM 版 Contextual Chunking

- 目标不是改 chunk 边界，而是给 embedding 输入补上下文前缀。
- 做法：
  - 为每个 chunk 构造 contextual embedding text：
    - 文档名
    - 标题路径 `title_path`
    - chunk 原文
  - 向量库写入时继续保存原始 `content`，只把 contextual text 用于 embedding 计算。
- 风险控制：
  - 不改 chunk 原文存储；
  - 不改 prompt / source 展示文本；
  - 不改 lexical 索引内容；
  - 仅影响 semantic embedding 输入。

## 验证策略

1. 单元测试覆盖：
   - contextual embedding text 只影响 embedding，不污染展示文本
   - parent context 扩展优先同 section，相邻补窗不越文档
   - `/ask` source 与 prompt 使用扩展后的证据窗口
2. 定向回归：
   - `tests/test_ingest_chunker.py`
   - `tests/test_answer_m3.py`
   - `tests/test_query_service.py`
   - `tests/test_indexing_service.py`
3. 全量验证：
   - 重新全量索引
   - `eval.run_benchmark_suite --suite eval/benchmark-suite.m18.json`

## 放行标准

- 定向测试通过
- benchmark suite gated entries 不回退
- 不修改 benchmark 数据与断言标准
