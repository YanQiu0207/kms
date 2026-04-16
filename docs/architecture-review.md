# 架构审核报告：mykms（个人知识库系统）

> 审核时间：2026-04-16
> 审核范围：app/、eval/、scripts/、tests/（不含 obs-local/）

## 一、整体评价

这是一个成熟度相当高的个人 RAG 知识库系统。分层清晰，日志完善，配置可调，防腐层到位，经过 18 个开发阶段的迭代打磨，整体工程质量远超个人项目的平均水平。

## 一点五、整改回执（2026-04-16）

针对本报告中用户要求优先处理的问题，当前状态如下：

| 问题 | 状态 | 结果 |
|------|------|------|
| God Module：`hybrid.py` | 已修复 | 检索编排保留在 `hybrid.py`，排序后处理拆到 `app/retrieve/ranking_pipeline.py` |
| 元数据提取逻辑重复 | 已修复 | 抽出 `app/metadata_utils.py`，`fts_store`、`guardrail`、ranking pipeline 复用统一工具 |
| 停用词集合重复且不一致 | 已收口 | metadata constraint 与 lookup intent 已统一到共享常量；`querying.py` / `query_understanding.py` 的低信号词仍按职责保留 |
| 排序管线硬编码、不可组合 | 已修复 | 新增 `retrieval.ranking_pipeline` 配置，按 step registry 组合执行 |
| 配置缺少语义校验 | 已修复 | `chunker`、`retrieval`、`abstain`、`verify`、`server` 已补值域与顺序校验 |
| 模块级 App 单例 | 已修复 | `app.main` 已移除模块级 `app = create_app(...)`，改为 factory 启动 |

本轮验证结果：

- 全量回归：`117 passed`
- benchmark suite：`passed_entries=8/8`
- gated benchmark：`passed_gated_entries=7/7`
- 未修改 benchmark 样本、golden case 与断言口径

## 二、架构亮点

| 维度 | 评价 |
|------|------|
| 分层设计 | API -> Service -> Domain -> Store 四层明确，无跨层调用 |
| 防腐层 | `app/vendors/` 将 FlagEmbedding、Chroma、Jieba 隔离，业务代码不直接依赖第三方 SDK |
| 可观测性 | 结构化 JSON 日志 + request_id 贯穿 + `timed_operation` 上下文管理器，几乎每个关键路径都有耗时统计 |
| 配置管理 | Pydantic 验证 + YAML 外部化 + 环境变量覆盖，所有可调参数已抽出 |
| 协议接口 | `store/contracts.py` 定义了 `MetadataStore`、`FTSWriter`、`VectorWriter` 等 Protocol，为未来替换存储实现留出了空间 |
| 检索管线 | Lexical + Semantic 双路召回 -> RRF 融合 -> Rerank -> 多阶段后处理，完整的工业级 hybrid retrieval |
| Guardrail | 多维度弃权判断（top1/top3 分数、命中数、字符总量、查询词覆盖率、查询类型），层次化决策 |
| 评估体系 | 独立的 `eval/` 框架，支持多配置多实例对比，有 recall/MRR/abstain accuracy 等指标 |

## 三、需关注的问题

### 1. God Module：hybrid.py（857 行）

**严重度：高**

**当前状态：已修复**

这个文件承担了过多职责：

- RRF 融合算法
- 元数据约束过滤（`_apply_query_metadata_constraints`）
- 定义型主题亲和度排序（`_prioritize_definition_subject_candidates`）
- Lookup 意图检测与优先级（`_collect_lookup_intent`、`_prioritize_lookup_candidates`）
- 文档多样化（`_diversify_lookup_documents`）
- 多查询 rerank 编排（`_rerank_candidates`）
- 多个正则和停用词集合

`search_and_rerank()` 方法（第 804-856 行）串联了约 10 个后处理步骤，固定顺序、不可组合：

```
constrained -> reranked -> constrained_reranked -> lookup_prioritized
-> metadata_prioritized -> definition_prioritized -> diversified -> filtered -> limited
```

**整改结果**：

- `HybridRetrievalService` 现只保留召回、RRF 融合和 pipeline 编排
- 排序后处理已抽到 `app/retrieve/ranking_pipeline.py`
- step 名称与默认顺序已抽到 `app/retrieval_pipeline_config.py`

### 2. 元数据提取逻辑重复 5 处

**严重度：高**

**当前状态：已修复**

以下代码段在做本质上相同的事——从 chunk 的 metadata dict 中提取 `front_matter_*`、`path_segments` 等字段：

| 位置 | 函数 |
|------|------|
| `hybrid.py:265` | `_metadata_strings()` |
| `hybrid.py:498` | `_candidate_lookup_term_set()` |
| `querying.py:556` | `_build_evidence_document_profiles()` |
| `guardrail.py:103` | `_metadata_support_chars()` |
| `fts_store.py:73` | `_iter_metadata_values()` |

每处都硬编码了相同（但不完全一致）的 key 列表，一旦新增元数据字段需要改 5 处。

**整改结果**：

- 已新增 `app/metadata_utils.py`
- `fts_store.py`、`guardrail.py`、ranking pipeline 已改为复用共享 metadata 文本提取函数
- `querying.py` 仍有证据侧的独立构造逻辑，但不再与检索链路各自维护同一套 metadata 字段枚举

### 3. 停用词集合重复且不一致

**严重度：中**

**当前状态：已收口**

| 集合 | 位置 | 条目数 |
|------|------|--------|
| `_LOW_SIGNAL_QUERY_TOKENS` | `querying.py:21` | ~32 |
| `_QUERY_COVERAGE_LOW_SIGNAL_TOKENS` | `querying.py:50` | ~62 |
| `_LOW_SIGNAL_TOKENS` | `query_understanding.py:9` | ~58 |
| `_METADATA_CONSTRAINT_STOPWORDS` | `hybrid.py:21` | ~18 |
| `_LOOKUP_QUERY_STOPWORDS` | `hybrid.py:55` | ~24 |

这些集合大量重叠但各有增减，维护时容易遗漏。

**整改结果**：

- metadata constraint 与 lookup intent 的 stopword 已统一到 `app/metadata_utils.py`
- `querying.py` / `query_understanding.py` 的低信号词集合仍保留独立定义，因为它们服务的是 query coverage 与 query understanding，不完全等价于检索后处理 stopword
- 因此该问题已从“同语义重复实现”收口为“按职责分层的多集合”

### 4. SQLite 连接无复用策略

**严重度：中**

- `querying.py:_load_chunk_texts()` 每次调用都 `SQLiteMetadataStore(config.data.sqlite)` 新建连接
- `hybrid.py:search()` 每次 `with SQLiteMetadataStore(...)` 也新建
- `stats()` 端点同理
- `IndexingService.index()` 内部也新建

虽然 SQLite 连接开销不大，但在高频请求下仍有不必要的重复。更重要的是 `HybridRetrievalService.search()` 和 `QueryService._load_chunk_texts()` 各自打开独立连接，同一请求内可能产生不一致的读视图。

**建议**：在 `QueryService` 初始化时创建一个长生命周期的 `SQLiteMetadataStore` 实例，通过依赖注入传递给 `HybridRetrievalService`。

### 5. 排序管线硬编码、不可组合

**严重度：中**

**当前状态：已修复**

`search_and_rerank()` 中的后处理步骤是线性串联的 10 个函数调用，无法通过配置选择启用哪些步骤。如果未来某类查询不需要 lookup 优先级，或者需要新增一种排序策略，必须修改这个核心方法。

**整改结果**：

- 已新增 `retrieval.ranking_pipeline`
- `search_and_rerank()` 已改为通过 step registry 逐步执行
- 默认顺序保持原有质量路径，同时支持后续按配置裁剪或重排

### 6. 配置缺少语义校验

**严重度：低**

**当前状态：已修复**

`config.py` 中的 Pydantic model 只定义了类型，没有值域校验：

- `chunk_overlap` 可以大于 `chunk_size`（导致无限循环或空 chunk）
- `rrf_k` 可以为 0（RRF 公式中作为分母）
- `min_output_score` 可以为负数
- `top1_min` 和 `top3_avg_min` 没有 0-1 范围约束

**整改结果**：

- 已为 `server.port`、`chunk_size/chunk_overlap`、`retrieval.*`、`abstain.*`、`verify.*` 增加语义校验
- 额外补了 `ranking_pipeline` 非空、无重复、顺序合法等校验
- 异常配置现在会在 `load_config()` 阶段直接失败

### 7. 模块级 App 单例

**严重度：低**

**当前状态：已修复**

旧实现：

```python
app = create_app(load_config())
```

旧实现会在模块导入时执行 `load_config()` 和全部初始化，导致：

- 测试中 `import app.main` 触发副作用
- 多配置场景下需要额外处理

**整改结果**：

- 已移除模块级 `app`
- 运行入口改为在 `run()` 中显式创建 app
- `uvicorn` 启动方式相应改为 `uvicorn app.main:create_app --factory`

### 8. /health 不检查依赖健康

**严重度：低**

当前 `/health` 只返回版本和时间戳，不验证 SQLite 可用性、Chroma 可连接、模型是否加载成功。对于个人部署场景影响不大，但如果后续加入 Claude Code skill 的自动探测或监控，可能需要更丰富的健康检查。

### 9. 全局环境变量副作用

**严重度：低**

`vendors/flag_embedding.py:_apply_hf_cache()` 调用 `environ.setdefault("HF_HOME", ...)`，这是进程级副作用。如果同进程中需要使用不同的 HF cache 路径（如多实例评测场景），会产生冲突。

## 四、架构图

```
+------------------------------------------------------+
|  HTTP / API Layer  (app/main.py - FastAPI)           |
|  /health  /stats  /index  /search  /ask  /verify     |
+------------------------------------------------------+
|  Service Layer                                        |
|  +--------------+  +---------------+  +-------------+ |
|  | QueryService |  |IndexingService|  |EmbeddingServ| |
|  |  (search,    |  |  (full,       |  |  (encode,   | |
|  |   ask,       |  |   incremental)|  |   model mgmt| |
|  |   verify)    |  |               |  |            )| |
|  +------+-------+  +-------+-------+  +------+-----+ |
+---------+------------------+------------------+-------+
|  Domain Logic                                         |
|  +------------+ +--------------+ +------------------+ |
|  | answer/    | | retrieve/    | |query_understanding| |
|  | guardrail  | | hybrid       | | (profile, route, | |
|  | prompt     | | rerank       | |  alias expand)   | |
|  | citation   | | lexical      | +------------------+ |
|  +------------+ | semantic     | +------------------+ |
|                 | ranking_pipe | | ingest/          | |
|                 +--------------+ | loader, chunker  | |
|                                  | cleaner          | |
|                                  +------------------+ |
+------------------------------------------------------+
|  Storage Layer  (app/store/)                          |
|  +------------+ +----------+ +---------------------+ |
|  |SQLiteMeta  | |FTS5Writer| |ChromaVectorStore    | |
|  |Store       | |          | |                     | |
|  +------------+ +----------+ +---------------------+ |
+------------------------------------------------------+
|  Vendor Adapters  (app/vendors/)                      |
|  +--------------+ +--------+ +--------------------+  |
|  |flag_embedding | | chroma | | jieba_tokenizer   |  |
|  +--------------+ +--------+ +--------------------+  |
+------------------------------------------------------+
     * `hybrid.py` 已完成职责收缩，排序后处理已拆到 `ranking_pipeline.py`
```

## 五、总结

| 类别 | 评分 | 说明 |
|------|------|------|
| 分层与职责划分 | 9/10 | 层次清晰，`hybrid.py` 已完成职责收缩 |
| 第三方隔离 | 9/10 | vendors 防腐层做得好 |
| 可观测性 | 9/10 | 结构化日志 + 全链路追踪 |
| 配置管理 | 9/10 | 已补语义校验与 pipeline 顺序校验 |
| 代码复用 | 8/10 | metadata 提取已统一，stopword 已做检索链路收口 |
| 可扩展性 | 9/10 | 排序管线已配置化，新增策略不必再挤进核心方法 |
| 测试覆盖 | 8/10 | 32 个测试文件 + 评估框架 |

**后续优先改进建议**（按 ROI 排序）：

1. SQLite 连接复用，减少同请求内的重复建连
2. 继续审视 `querying.py` / `query_understanding.py` 的低信号词集合，决定是否抽成更明确的注册表
3. 若后续进入多实例 / 多配置常驻场景，再评估 HF cache 环境变量副作用的隔离方案
