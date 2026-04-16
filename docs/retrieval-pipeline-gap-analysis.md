# 检索管线与成熟实践的差距分析

> 审核时间：2026-04-16
> 基线：当前系统 ~107 文档、~2700 chunks

## 前提

很多"工业级"技术在个人知识库规模下 ROI 极低，本文对每项建议标注了实际收益等级。

## 1. 分块（Chunking）

**当前做法**：

- Markdown heading 解析 -> section -> 段落块合并 -> 超长块按字符切割（800 字符 + 100 overlap）
- 保留 title_path、行号、section_index

**差距**：

| 缺失能力 | 说明 | 收益 |
|----------|------|------|
| Contextual Chunking | Anthropic 在 2024 年提出的方法：给每个 chunk 前面加一段由 LLM 生成的文档级上下文摘要，然后再做 embedding。解决的核心问题是——孤立的 chunk 丢失了"它属于哪篇文章在讲什么"的语境。当前用 title_path 和 metadata 做了部分补偿，但 embedding 本身没有携带上下文。 | **高** |
| Parent Document Retrieval | 检索时命中 chunk，返回时向上扩展到整个 section 或相邻 chunks。当前 chunk 是独立的，`/ask` 拿到的证据就只有 chunk 本身的 800 字符。如果答案需要的信息跨越了 chunk 边界，就会丢失。 | **高** |
| Token-aware 切分 | `chunk_size=800` 实际是字符数，不是 token 数。中英混排时 800 字符对应的 token 数差异很大。BGE-M3 最大输入 8192 tokens，但 chunk 实际可能只用了几百 tokens 的容量。 | **中** |

**不需要追的**：Late Chunking（把整篇文档先过 transformer 再切 embedding）——研究阶段技术，工程复杂度高，收益不确定。

## 2. 向量检索（Semantic）

**当前做法**：

- BGE-M3 dense embedding -> Chroma cosine search
- 支持 batch search（`search_many`）

**差距**：

| 缺失能力 | 说明 | 收益 |
|----------|------|------|
| BGE-M3 多向量未利用 | BGE-M3 原生支持三种表示：dense、sparse（学习型稀疏向量）、ColBERT（token 级交互）。但当前只用了 dense。BGE-M3 的 sparse 向量在中文场景下往往比 BM25 效果更好，因为它是学习出来的，不依赖分词质量。 | **高** |
| 查询 Embedding 缓存 | 同一个查询（或 variant）可能在同一请求内被 embed 多次。`search_many` 做了 batch，但 `/ask` 流程中 search 和后续的 term coverage 评估可能重复计算。 | **低**（当前规模） |

## 3. 词法检索（Lexical）

**当前做法**：

- FTS5 + Jieba 分词 + BM25
- 手动调的 BM25 权重：title_path=2.5, content=1.5, metadata_text=0.2
- OR 连接所有 token

**差距**：

| 缺失能力 | 说明 | 收益 |
|----------|------|------|
| 短语匹配 / 近邻匹配 | 当前所有 token 都是 OR 连接，"两阶段提交协议"被拆成独立 token 后，"两" OR "阶段" OR "提交" OR "协议" 会召回大量无关文档。FTS5 支持 `NEAR` 操作符和短语查询 `"token1 token2"`，可以提高精度。 | **中** |
| BM25 权重可配置化 | 当前权重硬编码在 SQL 里（`lexical.py:108`），无法通过 config.yaml 调整。 | **低** |

**不需要追的**：学习型 BM25 权重——数据量不够训练。

## 4. 融合（Fusion）

**当前做法**：

- 标准 RRF，k=60，静态权重

**差距**：

| 缺失能力 | 说明 | 收益 |
|----------|------|------|
| Query-type 自适应融合 | 已有 `QueryProfile.query_type`（definition/comparison/existence/procedure/lookup），但融合阶段完全不看它。成熟系统会根据查询类型调整 lexical vs semantic 的权重——例如 lookup 型查询更依赖精确匹配（lexical 权重拉高），definition 型更依赖语义（semantic 权重拉高）。 | **中** |
| Weighted RRF / Convex Combination | 标准 RRF 对所有列表等权。可以改为 `w_lex * RRF_lex + w_sem * RRF_sem`，其中权重由 query_type 决定。 | **中** |

## 5. 重排（Rerank）

**当前做法**：

- BGE-reranker-v2-m3 cross-encoder
- 多查询时取每个 chunk 在所有查询上的最高分
- Sigmoid 归一化

**差距**：

| 缺失能力 | 说明 | 收益 |
|----------|------|------|
| 多查询分数聚合策略 | 当前用 `max(scores)`（`hybrid.py:688`）。对于 comparison 型查询，应该用 `mean` 或加权组合——因为一个好的比较类证据应该同时跟两个比较对象都相关，而不是只跟其中一个极度相关。 | **中** |
| Rerank 候选池动态调整 | `rerank_candidate_limit=24` 是固定的。对于 comparison/procedure 型查询，`route_retrieval` 已经调了 recall_top_k 和 rerank_top_k，但 `rerank_candidate_limit` 没跟着调。 | **低** |

**不需要追的**：Listwise reranking、LLM-based reranking——2700 chunks 规模下 cross-encoder 已经足够。

## 6. 查询理解（Query Understanding）

**当前做法**：

- 基于关键词规则的 query_type 检测
- 硬编码的 alias_groups（6 组）
- 查询变体展开（标点去除、关键词提取、别名替换）

**差距**：

| 缺失能力 | 说明 | 收益 |
|----------|------|------|
| LLM 查询改写 | 当用户问"之前那个分布式一致性的笔记在哪"，规则系统很难理解指代和意图。LLM 可以将其改写为 `["分布式一致性协议", "Paxos Raft 共识算法", "两阶段提交"]` 这样的多查询。这是当前最大的可提升空间之一。 | **高** |
| HyDE | Hypothetical Document Embeddings——让 LLM 先生成一段"假想的理想答案"，用这段文本做 embedding 去检索。对 semantic search 的召回有显著提升，尤其当用户用口语化表述而文档是技术文档时。 | **中** |
| 别名/同义词从知识库自动学习 | 当前 `_ALIAS_GROUPS` 是手写的 6 组。有 107 篇文档的 front_matter（包含 aliases 字段），可以在索引时自动构建同义词表。 | **中** |

## 7. 答案生成与验证（Answer）

**当前做法**：

- 构建 prompt + 证据 -> 交给外部 LLM
- `/verify` 用 n-gram 覆盖率验证引用准确性
- 多阶段 abstain 判断

**差距**：

| 缺失能力 | 说明 | 收益 |
|----------|------|------|
| 迭代检索 | 当前是 one-shot：检索一次 -> 生成答案。成熟系统支持"检索 -> 尝试生成 -> 发现信息不足 -> 补充检索 -> 再生成"。对复杂问题的完整性有显著提升。 | **中** |
| 证据窗口扩展 | 当前传给 LLM 的证据就是 chunk 原文（最多 1200 字符截断）。如果能向上扩展到 parent section 或相邻 chunk，LLM 的上下文理解会好很多。与 Parent Document Retrieval 是配套的。 | **高** |

## 总结：优先级排序

按"实际收益 / 实现成本"排序，分三档。

### 第一梯队——ROI 最高，建议优先做

| # | 改进项 | 涉及模块 | 核心思路 |
|---|--------|----------|----------|
| 1 | Parent Document Retrieval | `querying.py`, `prompt.py` | 检索命中 chunk 后，从 SQLite 加载同 document_id 的相邻 chunks 拼接为扩展上下文，传入 prompt |
| 2 | Contextual Chunking | `chunker.py`, `indexing.py` | 索引时给每个 chunk 前面拼接文档标题 + 所属 section 的 heading 路径 + 摘要（可以先不用 LLM，用 title_path 拼接即可） |
| 3 | BGE-M3 Sparse 向量 | `vendors/flag_embedding.py`, `semantic.py` | `FlagAutoModel` encode 时取 `sparse_vecs`，融合到 RRF 中作为第三路召回 |

### 第二梯队——中等收益，条件成熟时做

| # | 改进项 | 涉及模块 | 核心思路 |
|---|--------|----------|----------|
| 4 | LLM 查询改写 | `query_understanding.py` | `/ask` 时先用 LLM 将用户问题改写为 2-3 个检索查询，替代当前的规则展开 |
| 5 | Query-type 自适应融合 | `hybrid.py` | RRF 时根据 query_type 给 lexical/semantic 列表分配不同权重 |
| 6 | FTS5 短语/近邻查询 | `lexical.py` | 对多字词（如"两阶段提交"）生成 NEAR 查询，提高精度 |
| 7 | 别名自动提取 | `query_understanding.py`, `indexing.py` | 从 front_matter aliases 字段构建同义词表，替代硬编码 |

### 第三梯队——锦上添花，当前不急

| # | 改进项 | 说明 |
|---|--------|------|
| 8 | HyDE | 增加延迟和 LLM 成本，当前查询复杂度还不需要 |
| 9 | 迭代检索 | 架构改动大，当前 one-shot 已经 recall=1.0 |
| 10 | Token-aware 切分 | 需要引入 tokenizer 依赖，当前字符切分够用 |

## 核心结论

管线在"召回 -> 融合 -> 排序 -> 过滤"这条主线上已经很完整了，最大的差距不在管线本身，而在管线两端——上游的"chunk 带的上下文太少"和下游的"证据窗口太窄"。Parent Document Retrieval + Contextual Chunking 这两项改完，答案质量会有明显的台阶式提升。
