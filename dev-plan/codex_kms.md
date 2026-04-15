# 个人知识库方案评估与实施建议

## 0. 需求

我想搭建个人知识库，应该如何实现？

我的想法：
（1）先将本地的 markdown 导入到向量数据库
（2）在 claude code 加一个技能，例如 kms。
（3）当我执行 /kms questions 时，先调用大模型基于 questions 生成几个意义相近的问题，然后调用我本地的 api，用个问题去向量数据库搜索资料
（4）将原始问题和搜索到资料发给大模型，大模型给出回答，且必须是基于资料的回答，不允许基于自己的记忆或训练数据

## 1. 评估结论

当前方案可行，但如果直接按“问题扩写 + 向量检索 + 大模型回答”实现，效果大概率只能达到“能用”，很难达到“稳定、准确、可维护”。

更稳妥的方案是将它设计成一个标准的 RAG 知识库系统，核心链路为：

`Markdown -> 分块 + 元数据 -> 混合检索 -> 重排 -> 带引用回答 -> 低置信度拒答`

其中最重要的改进点有四个：

1. 不要只做向量检索，至少增加关键词检索。
2. 不要把“相近问题扩写”作为主策略，应作为补充召回手段。
3. 不要只靠提示词限制模型，必须加入引用和拒答机制。
4. 不要把能力绑死在 Claude Code 技能中，应把知识库能力放在独立本地服务中。

## 2. 对原始方案的评估

### 2.1 Markdown 导入向量数据库

这个方向是对的，但不能把整篇 Markdown 直接入库。正确做法应该是：

- 清洗 Markdown 内容。
- 按标题层级和自然语义切块。
- 保留文件路径、标题路径、标签、更新时间、段落位置等元数据。
- 对每个 chunk 单独建立 embedding。

如果不做切块和元数据设计，后续检索结果会松散，回答也难以引用来源。

### 2.2 在 Claude Code 中增加 `kms` 技能

这个思路也成立，但 `kms` 更适合作为“命令入口”，而不是承载完整知识库逻辑。

推荐拆成两层：

- `kms` 技能：只负责命令交互和请求转发。
- 本地 `kms-api` 服务：负责索引、检索、重排和回答生成。

这样做的好处是：

- 后续可复用到网页、CLI、Obsidian 或其他客户端。
- 检索逻辑独立，便于调试和演进。
- Claude Code 不会成为唯一入口，架构更干净。

### 2.3 先让大模型生成几个意义相近的问题，再去搜索

这个思路有价值，但不适合做主检索路径，原因如下：

- 扩写问题可能偏题，导致召回结果被带歪。
- 每次都先调用大模型，会增加延迟和成本。
- 如果底层检索结构不完善，扩写并不能根本解决召回问题。

更合理的方式是：

- 先用原始问题直接检索。
- 检索结果较弱时，再做轻量问题扩写。
- 扩写最多生成 2 到 3 个变体。
- 变体仅用于补充召回，不直接拿去生成答案。

### 2.4 要求模型必须只基于资料回答

这个目标是正确的，但不能仅靠一句“不要基于自己的记忆回答”实现。

工程上更稳的约束方式是：

- 只把检索到的证据片段提供给模型。
- 要求每个关键结论附带引用。
- 检索不足时必须明确拒答。
- 对低分结果设置阈值，低于阈值不进入回答阶段。

也就是说，真正的“只基于资料回答”需要靠：

- 检索质量
- 提示词约束
- 引用输出
- 拒答逻辑

这几部分共同实现，而不是只靠提示词。

## 3. 推荐的整体方案

### 3.1 系统分层

建议架构如下：

- `Claude Code /kms`：命令入口
- `kms-api`：本地 API 服务
- `docs/`：Markdown 文档目录
- `SQLite FTS5`：全文检索
- `Chroma` 或 `Qdrant`：向量检索
- 大模型：负责基于证据生成答案

### 3.2 标准链路

完整流程建议如下：

1. 读取本地 Markdown。
2. 解析结构并切成多个 chunk。
3. 将 chunk 同时写入全文索引和向量索引。
4. 用户通过 `/kms ask "问题"` 提问。
5. 系统先执行混合检索（全文 + 向量）。
6. 对候选结果做重排或精排。
7. 如果证据不足，则拒答。
8. 如果证据充分，则把“问题 + 证据片段 + 来源”发给模型生成答案。
9. 输出答案时附带引用来源。

## 4. 文档入库设计

### 4.1 建议保留的元数据

每个 chunk 至少保留以下字段：

- `chunk_id`
- `doc_id`
- `file_path`
- `title_path`
- `tags`
- `updated_at`
- `chunk_index`
- `text`
- `token_count`

其中：

- `file_path` 用于最终引用来源。
- `title_path` 用于提高定位能力。
- `updated_at` 可用于后续排序和增量更新。

### 4.2 切块策略

不要简单按固定长度切块，建议采用以下规则：

- 先按 Markdown 标题拆分 section。
- section 过长时再按自然段拆分。
- 代码块、表格、列表尽量保持完整。
- 每个 chunk 控制在约 200 到 500 token。
- 相邻 chunk 保留少量 overlap。

这种切块方式比“整篇 embedding”或“纯字数切块”更适合知识库检索。

## 5. 检索设计

### 5.1 为什么不能只用向量检索

只做向量检索时，以下类型的问题容易失效：

- 专有名词
- 命令名
- 缩写
- 代码片段
- 精确术语匹配

因此必须增加全文检索能力。

### 5.2 推荐采用混合检索

推荐组合：

- 关键词检索：`SQLite FTS5`
- 语义检索：`Chroma` 或 `Qdrant`
- 结果合并：分数归一化后加权

例如可先尝试：

- 关键词检索权重：`0.45`
- 语义检索权重：`0.55`

然后：

- 先召回 top 20 到 top 30
- 再精排，最终选 top 5 到 top 8 供模型使用

### 5.3 问题扩写的触发位置

“相近问题扩写”应作为 fallback：

- 默认不启用
- 首轮检索不理想时再触发
- 限制扩写数量，避免噪声扩大

## 6. 回答生成设计

### 6.1 生成阶段输入内容

提供给大模型的内容应包括：

- 原始问题
- 检索到的证据片段
- 每个片段的来源信息

不要把整库内容交给模型，也不要给它过大的自由度。

### 6.2 提示词约束建议

提示词中至少应明确要求：

- 只能基于提供的 `Sources` 回答
- 不得补充未在证据中出现的事实
- 证据不足时必须回答“资料不足，无法确认”
- 每个关键结论后附引用
- 如果资料之间存在冲突，应明确指出冲突

### 6.3 输出格式建议

建议输出：

- `答案`
- `依据`
- `引用`

例如：

```text
答案：
...

依据：
- [notes/ai/rag.md#12]
- [notes/ai/vector-db.md#03]
```

## 7. 拒答机制

这是系统可靠性最关键的部分之一。

建议在以下场景拒答或降级回答：

- top1 检索分数低于阈值
- top3 平均分过低
- 检索证据彼此矛盾
- 命中片段与问题主题明显不相关

如果没有拒答机制，模型往往会“看起来合理地编造答案”。

## 8. 命令接口建议

建议首先实现以下 4 个命令：

### 8.1 `/kms index`

作用：

- 扫描本地 Markdown
- 做增量切块和入库

### 8.2 `/kms search "query"`

作用：

- 只返回命中的证据片段和来源
- 不生成答案

这个命令对于调试检索质量非常重要。

### 8.3 `/kms ask "question"`

作用：

- 执行检索
- 判断证据是否充分
- 在证据充分时生成带引用答案

### 8.4 `/kms doctor`

作用：

- 检查索引状态
- 检查 embedding 配置
- 检查模型连通性
- 检查文档数量和更新时间

## 9. 推荐技术栈

如果目标是“尽快做出一个真的能用的 MVP”，建议技术选型如下：

- Python 3.11+
- FastAPI
- SQLite FTS5
- Chroma
- Markdown 解析库：`mistune` 或 `markdown-it-py`
- token 统计工具：`tiktoken` 或同类库

这个组合简单、稳定、易于调试，适合个人知识库的第一版。

## 10. 推荐目录结构

```text
kms/
  app/
    main.py
    config.py
    schemas.py
    ingest/
      loader.py
      markdown_parser.py
      chunker.py
      dedup.py
    store/
      sqlite_store.py
      vector_store.py
    retrieve/
      lexical.py
      semantic.py
      hybrid.py
      rerank.py
    answer/
      prompt.py
      generator.py
      guardrail.py
    commands/
      index.py
      search.py
      ask.py
  data/
    kms.db
    chroma/
  docs/
```

## 11. 分阶段实施建议

### 11.1 第一阶段：MVP

目标是先做出可用最小版本，能力包括：

- 索引本地 Markdown
- 检索相关 chunk
- 基于 chunk 生成回答
- 回答带引用
- 证据不足时拒答

### 11.2 第二阶段：可用版本

在 MVP 基础上增加：

- 混合检索
- metadata 过滤
- 拒答阈值调优
- `/kms search` 与 `/kms ask` 分离

### 11.3 第三阶段：稳定版本

后续再增加：

- reranker
- query rewrite
- 增量索引
- 命中日志
- 效果评估
- 检索可观测性

## 12. 最终建议

如果目标是“先搭建一个真正能长期使用的个人知识库”，推荐路线应是：

`Markdown -> chunk + metadata -> FTS + vector hybrid retrieval -> rerank -> cited answer -> abstain on low confidence`

与你最初方案相比，这条路线的优势是：

- 检索更稳
- 更容易调试
- 更容易迭代
- 可以更接近“只基于资料回答”

当前最务实的起步方案建议固定为：

- 文档目录：`docs/`
- 服务：`FastAPI`
- 检索：`SQLite FTS5 + Chroma`
- 命令：`/kms index`、`/kms search`、`/kms ask`

这版足够作为第一版产品落地。

## 13. 可直接开工的实现蓝图

这一节将方案进一步收敛为“第一版可以直接实现”的工程设计。

目标是：

- 尽量少的模块
- 尽量清晰的数据流
- 先做稳，再做复杂

## 14. MVP 的边界

第一版只解决以下问题：

1. 扫描本地 Markdown 文档。
2. 对文档进行切块和索引。
3. 支持关键词检索和向量检索。
4. 支持基于证据回答问题。
5. 回答必须带引用。
6. 证据不足时明确拒答。

第一版暂不做：

- 多用户
- 权限系统
- Web UI
- 自动摘要整库
- 文档协作同步
- 高级 Agent 编排
- 复杂 reranker 服务化

## 15. API 设计

建议本地服务命名为 `kms-api`，先提供以下接口。

### 15.1 `POST /index/rebuild`

用途：

- 全量重建索引

请求示例：

```json
{
  "docs_path": "E:/work/interview/docs"
}
```

响应示例：

```json
{
  "ok": true,
  "mode": "rebuild",
  "docs": 128,
  "chunks": 2641,
  "elapsed_ms": 18342
}
```

### 15.2 `POST /index/update`

用途：

- 增量更新索引
- 仅处理新增、修改、删除的 Markdown 文件

请求示例：

```json
{
  "docs_path": "E:/work/interview/docs"
}
```

### 15.3 `POST /search`

用途：

- 只做检索
- 返回候选片段，不生成答案

请求示例：

```json
{
  "query": "如何设计混合检索",
  "top_k": 8,
  "tags": ["rag"],
  "paths": []
}
```

响应示例：

```json
{
  "query": "如何设计混合检索",
  "hits": [
    {
      "chunk_id": "notes/rag.md#7",
      "file_path": "notes/rag.md",
      "title_path": ["RAG", "Hybrid Retrieval"],
      "score": 0.83,
      "text": "..."
    }
  ]
}
```

### 15.4 `POST /ask`

用途：

- 检索 + 回答

请求示例：

```json
{
  "question": "个人知识库为什么不能只做向量检索？",
  "top_k": 6,
  "allow_query_rewrite": true
}
```

响应示例：

```json
{
  "question": "个人知识库为什么不能只做向量检索？",
  "answer": "不能只做向量检索，因为专有名词、命令名、缩写和代码片段往往更依赖精确匹配，单纯语义检索会漏掉这些内容。[来源: notes/kb/rag.md#4]",
  "citations": [
    {
      "chunk_id": "notes/kb/rag.md#4",
      "file_path": "notes/kb/rag.md"
    }
  ],
  "used_chunks": [
    "notes/kb/rag.md#4",
    "notes/kb/search.md#2"
  ],
  "confidence": 0.79,
  "abstained": false
}
```

### 15.5 `GET /health`

用途：

- 健康检查
- 供 `/kms doctor` 使用

响应示例：

```json
{
  "ok": true,
  "sqlite": true,
  "vector_store": true,
  "embedding_model": "configured",
  "answer_model": "configured"
}
```

## 16. 命令层设计

`/kms` 只是入口，建议做如下映射：

- `/kms index`
  - 调用 `POST /index/update`
- `/kms reindex`
  - 调用 `POST /index/rebuild`
- `/kms search "query"`
  - 调用 `POST /search`
- `/kms ask "question"`
  - 调用 `POST /ask`
- `/kms doctor`
  - 调用 `GET /health`

这样 CLI 层会非常薄，调试成本低。

## 17. 数据库设计

第一版可以全部落在 `SQLite + Chroma` 上。

### 17.1 SQLite 表设计

建议至少包含三张表。

#### `documents`

用于记录文档级信息。

```sql
CREATE TABLE documents (
  doc_id TEXT PRIMARY KEY,
  file_path TEXT NOT NULL UNIQUE,
  title TEXT,
  tags_json TEXT,
  file_hash TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  indexed_at TEXT NOT NULL
);
```

#### `chunks`

用于记录 chunk 元数据与正文。

```sql
CREATE TABLE chunks (
  chunk_id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,
  chunk_index INTEGER NOT NULL,
  title_path_json TEXT,
  text TEXT NOT NULL,
  token_count INTEGER,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (doc_id) REFERENCES documents(doc_id)
);
```

#### `ingest_log`

用于记录每次索引结果，方便排错。

```sql
CREATE TABLE ingest_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  mode TEXT NOT NULL,
  docs_count INTEGER NOT NULL,
  chunks_count INTEGER NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT NOT NULL,
  status TEXT NOT NULL,
  message TEXT
);
```

### 17.2 FTS5 索引

建议对 `chunks.text` 建立 FTS5 虚拟表：

```sql
CREATE VIRTUAL TABLE chunks_fts USING fts5(
  chunk_id UNINDEXED,
  text,
  content='',
  tokenize='unicode61'
);
```

索引写入时同步把 `chunk_id` 和 `text` 写入 `chunks_fts`。

### 17.3 向量存储

向量库中每条记录建议至少保存：

- `id = chunk_id`
- `embedding`
- `text`
- `metadata`

`metadata` 建议包括：

- `doc_id`
- `file_path`
- `title_path`
- `chunk_index`
- `updated_at`
- `tags`

## 18. 文档处理流程

建议将入库流程拆成以下步骤。

### 18.1 扫描文件

- 扫描 `docs/` 下所有 `.md`
- 计算文件哈希
- 与 `documents.file_hash` 比较，决定新增、更新或删除

### 18.2 解析 Markdown

处理内容时至少识别：

- 标题
- 段落
- 列表
- 代码块
- 引用块
- 表格

第一版不需要完整 AST 级精细处理，但需要保证代码块和表格不会被截断。

### 18.3 切块

推荐伪规则：

1. 按标题切 section
2. section 太长时按段落切
3. 每块控制在 200 到 500 token
4. 过短片段与相邻片段合并
5. 代码块尽量和前导说明保留在同一 chunk

### 18.4 写入索引

对每个 chunk 执行：

1. 写入 `chunks`
2. 写入 `chunks_fts`
3. 生成 embedding
4. 写入 Chroma

如果文档已更新，应先删除旧 chunk 再写入新 chunk。

## 19. 检索与合并逻辑

### 19.1 lexical 检索

通过 FTS5 查询：

- 输入原始 query
- 返回 top N chunk
- 记录 lexical score

### 19.2 semantic 检索

通过向量库：

- 对 query 生成 embedding
- 返回 top N chunk
- 记录 semantic score

### 19.3 混合结果合并

先对两类分数归一化，再按加权合并：

```text
final_score = lexical_score * 0.45 + semantic_score * 0.55
```

然后：

- 去重
- 保留最高分版本
- 按 `final_score` 排序
- 取 top 20

### 19.4 可选重排

MVP 可以先不用独立重排器，但接口要预留：

- `rerank(query, chunks) -> reranked_chunks`

后续如果效果不够，再引入 cross-encoder 或模型 rerank。

## 20. 回答生成与约束

### 20.1 提供给模型的上下文

建议传给模型的内容结构如下：

```text
Question:
{question}

Sources:
[1] {file_path}#{chunk_id}
{chunk_text}

[2] {file_path}#{chunk_id}
{chunk_text}
```

### 20.2 推荐提示词模板

```text
你是一个严格基于资料回答问题的助手。

规则：
1. 只能依据提供的 Sources 回答。
2. 不得补充 Sources 中没有明确出现的事实。
3. 如果 Sources 无法支持完整回答，必须明确说“资料不足，无法确认”。
4. 每个关键结论后都要附上来源引用，格式为 [来源: 文件路径#chunk_id]。
5. 如果不同 Sources 之间存在冲突，必须指出冲突，而不是自行消解。

请回答用户问题。
```

### 20.3 拒答逻辑

建议在进入生成前做一层 guard：

- 如果 top1 < 阈值，例如 `0.35`，拒答
- 如果 top3 平均分 < 阈值，例如 `0.30`，拒答
- 如果 top 命中内容长度太短，拒答
- 如果候选块之间语义分散严重，谨慎拒答

输出格式建议统一为：

- `abstained = true/false`
- `confidence = 0~1`
- `answer`
- `citations`

## 21. Python 模块职责

### 21.1 `app/main.py`

职责：

- FastAPI 入口
- 路由注册
- 初始化配置和服务

### 21.2 `app/config.py`

职责：

- 读取环境变量
- 管理模型和索引路径配置

建议配置项：

- `DOCS_PATH`
- `SQLITE_PATH`
- `CHROMA_PATH`
- `EMBEDDING_MODEL`
- `ANSWER_MODEL`
- `TOP_K`
- `LEXICAL_WEIGHT`
- `SEMANTIC_WEIGHT`
- `MIN_SCORE`

### 21.3 `app/ingest/*`

职责：

- 扫描文档
- 解析 Markdown
- 切块
- 去重

### 21.4 `app/store/*`

职责：

- SQLite 读写
- FTS5 读写
- 向量库读写

### 21.5 `app/retrieve/*`

职责：

- lexical 检索
- semantic 检索
- 混合合并
- 可选重排

### 21.6 `app/answer/*`

职责：

- 构造 prompt
- 执行回答
- 拒答判断

## 22. 关键伪代码

### 22.1 索引

```python
def update_index(docs_path: str):
    files = scan_markdown_files(docs_path)
    changes = diff_files_with_db(files)

    for file in changes.deleted:
        delete_document(file)

    for file in changes.added_or_updated:
        raw = load_markdown(file)
        sections = parse_markdown(raw)
        chunks = chunk_sections(sections)

        delete_document(file)
        upsert_document(file)

        for chunk in chunks:
            save_chunk_to_sqlite(chunk)
            save_chunk_to_fts(chunk)
            emb = embed(chunk.text)
            save_chunk_to_vector_store(chunk, emb)
```

### 22.2 检索

```python
def search(query: str, top_k: int = 8):
    lexical_hits = lexical_search(query, limit=20)
    semantic_hits = semantic_search(query, limit=20)
    merged = hybrid_merge(lexical_hits, semantic_hits)
    return merged[:top_k]
```

### 22.3 问答

```python
def ask(question: str):
    hits = search(question, top_k=8)
    if should_abstain(hits):
        return {
            "abstained": True,
            "answer": "资料不足，无法确认。",
            "citations": []
        }

    prompt = build_prompt(question, hits[:6])
    answer = generate_answer(prompt)
    return {
        "abstained": False,
        "answer": answer,
        "citations": extract_citations(hits[:6])
    }
```

## 23. 环境变量建议

```env
DOCS_PATH=E:/work/interview/docs
SQLITE_PATH=E:/work/interview/kms/data/kms.db
CHROMA_PATH=E:/work/interview/kms/data/chroma
EMBEDDING_MODEL=text-embedding-3-large
ANSWER_MODEL=gpt-5.4-mini
TOP_K=8
LEXICAL_WEIGHT=0.45
SEMANTIC_WEIGHT=0.55
MIN_SCORE=0.35
```

如果你后续接的是本地模型或其他 API，只要保持这组配置可替换即可。

## 24. 第一版测试策略

至少准备一组小型测试文档集，例如 20 到 50 篇 Markdown，并手工构造一批问题。

测试分三类：

### 24.1 检索命中测试

检查：

- 问题是否能命中正确 chunk
- top3 是否包含正确来源

### 24.2 引用测试

检查：

- 回答中的关键结论是否都有来源
- 引用路径是否能回溯到具体文件

### 24.3 拒答测试

检查：

- 知识库没有相关内容时，是否会老实拒答
- 低相关内容时，是否会错误编造

## 25. 当前最推荐的开工顺序

如果现在开始实现，建议严格按这个顺序推进：

1. 建立项目骨架和配置管理
2. 实现 Markdown 扫描、解析、切块
3. 实现 SQLite 存储和 FTS5 检索
4. 实现 Chroma 向量检索
5. 实现 hybrid merge
6. 实现 `/search`
7. 实现 `/ask`
8. 实现引用和拒答
9. 最后再补 query rewrite 和 rerank

不要一开始就做复杂扩写、复杂 agent 或复杂 UI。

## 26. 下一步建议

到这里，方案已经足够进入编码阶段。

建议下一步直接产出三样东西：

1. 项目初始化目录
2. FastAPI 最小代码骨架
3. SQLite 表结构和索引脚本

如果继续推进，下一轮就可以直接开始在本地创建 `kms/` 项目骨架。
