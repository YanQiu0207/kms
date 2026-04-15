# `/ask` 链路与 Markdown 预处理说明

这份文档面向“不熟悉项目代码，但需要快速搞清楚服务怎么工作”的读者。

重点回答两个问题：

- `/ask` 请求进入后，代码按什么顺序执行
- Markdown 文档在索引前做了哪些预处理、切分和入库

## 先看结论

当前 `kms-api` 更像一个“证据检索与 prompt 编排服务”，而不是直接生成最终自然语言答案的 LLM 服务。

`/ask` 的职责是：

1. 接收问题与查询参数
2. 做混合检索与 rerank
3. 判断证据是否足够
4. 产出给宿主模型使用的 `prompt`
5. 同时返回 `sources` 供宿主展示或后续调用 `/verify`

Markdown 索引的职责是：

1. 扫描配置里的 Markdown 源目录
2. 读取文档并记录文件状态
3. 按标题切成 section
4. 按块和长度切成 chunk
5. 同时写入 SQLite 元数据、FTS5 词法索引、Chroma 向量索引

## `/ask` 链路

### 入口

HTTP 路由在 [app/main.py](/E:/github/mykms/app/main.py:171)。

请求体模型在 [app/schemas.py](/E:/github/mykms/app/schemas.py:106)：

- `question`：必填
- `queries`：可选；为空时会退回到 `question`
- `recall_top_k` / `rerank_top_k`：可选覆盖默认检索参数

路由函数本身很薄，主要做两件事：

- 记录 `api.ask` 这层耗时日志
- 调 `QueryService.ask(...)`

具体实现见 [app/services/querying.py](/E:/github/mykms/app/services/querying.py:106)。

### 第一步：规范化和扩展查询

`QueryService.ask(...)` 不会直接把原始问题扔给检索器，而是先构造 `effective_queries`。

规则在 [app/services/querying.py](/E:/github/mykms/app/services/querying.py:217)：

- 如果调用方传了 `queries`，优先使用它们
- 如果没传，就用 `question`
- 如果最终只有一个 query，会自动扩成最多 3 个变体：
  - 原始 query
  - 去掉标点和空白后的紧凑版本
  - 去掉低信息词后的关键词版本

这样做的目的，是同时兼顾：

- 原问句的语义完整性
- 词法检索对关键词的命中率

### 第二步：进入搜索主流程

`QueryService.ask(...)` 会调 [QueryService.search(...) ](/E:/github/mykms/app/services/querying.py:71)。

这一层额外做了一件事：内存 LRU 缓存。

缓存 key 由下列信息组成：

- 扩展后的 queries
- `recall_top_k`
- `rerank_top_k`

如果相同查询刚刚查过，会直接复用结果，避免重复跑检索和 rerank。

### 第三步：混合检索

核心实现是 [HybridRetrievalService.search_and_rerank(...) ](/E:/github/mykms/app/retrieve/hybrid.py:210)。

它的执行顺序是：

1. 先跑 `search(...)`
2. `search(...)` 内部对每个 query 并行概念上的两路检索
3. 用 RRF 融合结果
4. 再把融合后的候选交给 reranker 二次排序
5. 最后按最小输出分数过滤

#### 3.1 词法检索

词法检索在 [app/retrieve/lexical.py](/E:/github/mykms/app/retrieve/lexical.py:95)。

它查的是 SQLite FTS5，不是直接扫原始 Markdown 文本。

查询词先经过 [app/retrieve/lexical.py](/E:/github/mykms/app/retrieve/lexical.py:51) 构造 FTS 查询式，底层分词逻辑来自 [app/store/fts_store.py](/E:/github/mykms/app/store/fts_store.py:51) 的 `tokenize_fts(...)`。

词法检索命中的结果会附带这些信息：

- `lexical_rank`
- `lexical_score`
- `lexical_bm25`

#### 3.2 语义检索

语义检索在 [app/retrieve/semantic.py](/E:/github/mykms/app/retrieve/semantic.py:135)。

执行方式是：

1. 用 embedding 模型把 query 编码成向量
2. 去 Chroma collection 查最近邻
3. 把返回的距离转换成 `semantic_score`

Chroma collection 的惰性初始化在 [app/retrieve/semantic.py](/E:/github/mykms/app/retrieve/semantic.py:115)。

语义检索命中的结果会附带：

- `semantic_rank`
- `semantic_distance`
- `semantic_score`

#### 3.3 RRF 融合

融合逻辑在 [app/retrieve/hybrid.py](/E:/github/mykms/app/retrieve/hybrid.py:64)。

当前实现使用 Reciprocal Rank Fusion：

- 不直接比较词法分数和语义分数的绝对值
- 主要按各自检索列表里的排名做融合

融合后的 chunk 会带上：

- `rrf_score`
- `source_hits`

#### 3.4 Rerank

rerank 实现在 [app/retrieve/rerank.py](/E:/github/mykms/app/retrieve/rerank.py:146)。

流程是：

1. 把多个 query 合并成一个 rerank query
2. 取前若干候选
3. 用 reranker 模型重新评分
4. 把分数归一化到 `0-1`
5. 按 rerank 后的分数重新排序

如果配置的是 debug 模型，则会退回 [DebugReranker](/E:/github/mykms/app/retrieve/rerank.py:59)。

### 第四步：拒答判定

检索结果回到 `QueryService.ask(...)` 后，会先做拒答判断，见 [app/answer/guardrail.py](/E:/github/mykms/app/answer/guardrail.py:68)。

当前判定维度有 4 个：

- `top1_score`
- `top3_avg_score`
- 命中条数 `min_hits`
- 证据总字符数 `min_total_chars`

只要任一条件不满足，就返回：

- `abstained=true`
- `abstain_reason=...`
- `prompt=""`
- `sources=[]`

### 第五步：组装 prompt 和 sources

如果不拒答，就进入 [app/answer/prompt.py](/E:/github/mykms/app/answer/prompt.py:212)。

这里会做两件事：

1. 把检索到的 chunk 整理成标准化证据源 `sources`
2. 用固定模板把问题和证据拼成 `prompt`

证据源构建在 [app/answer/prompt.py](/E:/github/mykms/app/answer/prompt.py:123)。

每条 source 里会包含：

- `chunk_id`
- `file_path`
- `location`
- `title_path`
- `text`
- `score`
- `doc_id`

prompt 渲染逻辑在 [app/answer/prompt.py](/E:/github/mykms/app/answer/prompt.py:188)。

它会要求宿主模型：

- 只能基于证据回答
- 每条结论都要标注 `[1]`、`[2]`
- 证据不足时直接输出“资料不足，无法确认。”
- 回答末尾追加“来源列表”

### `/ask` 返回的到底是什么

返回模型在 [app/schemas.py](/E:/github/mykms/app/schemas.py:147)。

也就是说，`/ask` 当前返回的核心不是“最终答案正文”，而是：

- 是否拒答
- 检索置信度
- 给宿主模型的 prompt
- 证据 sources

如果上层是 Claude Code / Codex 适配器，通常是：

1. 先调 `/ask`
2. 如果 `abstained=true`，就拒答
3. 如果 `abstained=false`，严格依据 `prompt + sources` 生成最终回答

## Markdown 预处理与索引

### 入口

索引入口在 [app/main.py](/E:/github/mykms/app/main.py:142)，对应 `POST /index`。

主流程实现是 [app/services/indexing.py](/E:/github/mykms/app/services/indexing.py:121)。

它负责把 ingest、SQLite、FTS5、Chroma、embedding 服务串起来。

### 第一步：扫描 Markdown 文件

扫描器在 [app/ingest/loader.py](/E:/github/mykms/app/ingest/loader.py:145)。

当前只会纳入这些扩展名：

- `.md`
- `.markdown`
- `.mdown`
- `.mkdn`
- `.mdtxt`

扫描时会：

- 遍历 `config.yaml` 里的 `sources`
- 应用 `excludes`
- 为每个 source root 生成稳定的 `source_id`

### 第二步：读取文档并记录文件状态

文档读取逻辑在 [app/ingest/loader.py](/E:/github/mykms/app/ingest/loader.py:58)。

这里做的是轻量规范化，不是内容改写：

- 读取原始字节
- 计算 `file_hash`
- 尝试按 `utf-8-sig`、`utf-8` 解码
- 统一得到文本内容
- 记录：
  - `document_id`
  - `file_path`
  - `relative_path`
  - `mtime_ns`
  - `size`
  - `encoding`

增量索引依赖这些文件状态，比较逻辑由 `build_incremental_plan(...)` 驱动，见 [app/ingest/loader.py](/E:/github/mykms/app/ingest/loader.py:185)。

### 第三步：按标题切成 section

Markdown 解析器在 [app/ingest/markdown_parser.py](/E:/github/mykms/app/ingest/markdown_parser.py:62)。

它不是完整 Markdown AST 解析器，而是一个“面向检索切分”的轻量 section parser。

当前识别：

- ATX 标题：`#` 到 `######`
- Setext 标题：`===` / `---`

解析结果会保留：

- `title_path`
- `heading`
- `heading_level`
- `section_index`
- `start_line`
- `end_line`
- `text`

有一个重要细节：

- fenced code block 内不会把 `#` 误判为标题

### 第四步：按块和长度切成 chunk

chunker 在 [app/ingest/chunker.py](/E:/github/mykms/app/ingest/chunker.py:176)。

它的目标是把 section 变成更适合 embedding 和检索的片段。

处理规则大致是：

1. 先把换行统一成 `\n`，并去掉首尾空白
2. 用空行把 section 拆成多个 block
3. fenced code block 尽量作为整体保留
4. 多个 block 在不超过 `chunk_size` 的前提下合并进同一个 chunk
5. 如果单个 block 过长，就调用 [app/ingest/chunker.py](/E:/github/mykms/app/ingest/chunker.py:51) 再次切分

长文本切分时优先找这些断点：

- 双换行
- 单换行
- 中文句号、感叹号、问号
- 英文句号、感叹号、问号
- 空格

切完后的 chunk 会保留：

- `chunk_id`
- `document_id`
- `title_path`
- `section_index`
- `chunk_index`
- `start_line`
- `end_line`
- `text`
- `token_count`
- `chunker_version`
- `embedding_model`

`chunk_id` 由 [app/ingest/chunker.py](/E:/github/mykms/app/ingest/chunker.py:146) 生成，依赖：

- `document_id`
- `title_path`
- `chunk_index`
- `chunk` 文本内容的 SHA1

### 第五步：写入三套存储

持久化逻辑在 [app/services/indexing.py](/E:/github/mykms/app/services/indexing.py:272)。

一份 chunk 最终会进入三套地方：

1. SQLite 元数据
2. FTS5 词法索引
3. Chroma 向量索引

#### 5.1 SQLite

SQLite 主要保存：

- documents
- chunks
- ingest_log

这里存的是原始 chunk 文本和检索要用的元数据，比如：

- `file_path`
- `title_path`
- `start_line`
- `end_line`
- `chunker_version`

#### 5.2 FTS5

FTS5 写入在 [app/store/fts_store.py](/E:/github/mykms/app/store/fts_store.py:124)。

写入前不会直接存原样 Markdown，而是先分词，分词入口在 [app/store/fts_store.py](/E:/github/mykms/app/store/fts_store.py:51)。

当前策略是：

- 优先用 `app.vendors.cut_tokens(...)`
- 如果拿不到结果，就退回内置 fallback
- ASCII token 会转小写
- 中文长词在 fallback 下会额外拆出 2-gram

FTS5 里索引的是：

- `title_path`
- `content`

这也是为什么词法检索命中效果更依赖标题和关键词覆盖，而不是完整 Markdown 语义。

#### 5.3 Chroma

向量写入由 [app/services/indexing.py](/E:/github/mykms/app/services/indexing.py:298) 驱动。

流程是：

1. 取每个 chunk 的原始文本
2. 调 embedding 模型生成向量
3. 以 `chunk_id` 为主键写入 Chroma

### 当前 Markdown 预处理“没有做什么”

这部分很重要，因为直觉上大家容易以为 Markdown 会被“深度清洗”。

按当前代码实现，下面这些都没有看到专门语义化处理：

- YAML front matter 单独抽取
- Markdown 表格结构化
- 图片语义提取
- 链接目标单独建索引
- HTML 块专门清洗
- 列表层级专门重写

它更接近：

- 保留原始文本
- 按标题和空行做结构切分
- 保留行号与标题路径
- 把 chunk 文本同时喂给词法索引和向量索引

## 建议怎么读代码

如果你只想先理解主流程，建议按这个顺序读：

1. [app/main.py](/E:/github/mykms/app/main.py:41)
2. [app/services/querying.py](/E:/github/mykms/app/services/querying.py:62)
3. [app/retrieve/hybrid.py](/E:/github/mykms/app/retrieve/hybrid.py:131)
4. [app/answer/prompt.py](/E:/github/mykms/app/answer/prompt.py:212)
5. [app/services/indexing.py](/E:/github/mykms/app/services/indexing.py:115)
6. [app/ingest/loader.py](/E:/github/mykms/app/ingest/loader.py:110)
7. [app/ingest/markdown_parser.py](/E:/github/mykms/app/ingest/markdown_parser.py:62)
8. [app/ingest/chunker.py](/E:/github/mykms/app/ingest/chunker.py:168)

## 对照日志看链路

如果你边跑服务边看日志，最值得关注的事件大致是：

- `/ask`
  - `api.ask`
  - `query.ask`
  - `query.search`
  - `retrieval.lexical_stage`
  - `retrieval.semantic_stage`
  - `retrieval.search_and_rerank`
  - `query.ask.abstain`
  - `query.ask.prompt_build`
- `/index`
  - `index.run`
  - `index.incremental.plan`
  - `index.persist.metadata`
  - `index.persist.fts`
  - `index.persist.vector`

最常用的排查方式是：

- 看 `kms-api.log`：理解业务链路和耗时
- 看 `kms-api.stderr.log`：补充 traceback、warnings、第三方库报错
