# 个人知识库（KMS）最终实施方案 v1.1

## 1. 结论

本方案采用：

`Markdown -> 结构化分块 -> 混合检索 -> rerank -> 证据装配 -> 宿主 LLM 带引用回答 -> 低置信度拒答`

并明确支持双宿主：

- `Claude Code`
- `Codex`

二者只做薄适配，核心能力统一收敛到本地 `kms-api` 服务。**双宿主统一通过 Bash `curl` 调用 HTTP API，不引入 MCP**。**答案由宿主 LLM（Claude Code 内置 / Codex 内置）生成，`kms-api` 只负责检索、装配证据、给出拒答标志，自身不依赖任何外部 LLM**。

这份方案以 `codex_kms.md` 的系统设计为主骨架，吸收 `cc_kms.md` 中可直接落地的工程拆分，同时采纳两份评审文档中的关键修正意见。

## 1.1 v1.1 关键决策（相对原稿的固化）

| 决策 | 取值 | 原因 |
|---|---|---|
| 双宿主集成 | 统一 HTTP `curl`，**不走 MCP** | 调试最简；Codex 的 MCP 支持情况不在本方案确定范围内；不需要"自动调用" |
| 问题扩写执行位置 | **宿主侧扩写**，`/search` 接收 `queries: List[str]` | 服务端保持无状态、不依赖外部 LLM |
| Answer 生成位置 | **宿主 LLM 生成**，`/ask` 返回证据 + prompt + `abstained` flag | 服务端零 LLM 依赖；两端各用自家 Claude/GPT |
| `/search` top_k 语义 | 拆为 `recall_top_k`（默认 20）和 `rerank_top_k`（默认 6） | 消除歧义 |
| 引用校验规则 | n-gram 子串匹配，覆盖率 < 50% 标 `citation_unverified` | 第一版机制可执行、可测 |

---

## 2. 设计目标

目标不是做一个“能跑的 RAG demo”，而是做一个可以长期使用的个人知识库系统。

必须满足：

1. 支持本地 Markdown 笔记入库。
2. 支持中文和英文检索。
3. 回答必须严格基于检索到的资料。
4. 资料不足时必须拒答。
5. Claude Code 和 Codex 都能调用。
6. 后续可扩展到 MCP、CLI、Obsidian 等入口。

---

## 3. 总体架构

### 3.1 分层

采用三层结构：

1. **核心服务层**
   `kms-api`

2. **宿主适配层**
   - `adapter-claude`
   - `adapter-codex`

3. **文档与索引层**
   - Markdown 文档源
   - SQLite 元数据 / FTS
   - Chroma 向量库

### 3.2 原则

- 核心服务不依赖 Claude Code 或 Codex 的目录约定。
- 宿主适配层不实现检索逻辑，只转发请求、格式化结果。
- 所有检索、重排、拒答、引用逻辑都在 `kms-api` 内部完成。

---

## 4. 推荐链路

### 4.1 索引链路

`Markdown 文件 -> 解析 -> 分块 -> 写入 SQLite 元数据 -> 写入 FTS -> 生成 embedding -> 写入 Chroma`

### 4.2 问答链路

`用户问题 -> 宿主适配层 -> kms-api -> hybrid retrieval -> rerank -> 证据门槛判断 -> 装配 prompt + 证据 + abstained flag -> 宿主 LLM 生成答案 -> 可选回调 /verify 做引用校验`

### 4.3 问题扩写策略

问题扩写不是主路径，只作为补充召回手段：

- 默认先用原问题检索。
- 首轮召回较弱时，再生成 2 到 3 个扩写问题。
- 扩写问题仅用于补充召回，不直接作为回答依据。

**执行位置**：问题扩写由**宿主 LLM** 完成（Claude Code / Codex 各自调用其内置模型），扩写后的多 query 以 `queries: List[str]` 传入 `/search`。`kms-api` 不调用任何外部 LLM。

---

## 5. 技术选型

### 5.1 后端

- Python 3.11+
- FastAPI
- uvicorn
- pydantic

### 5.2 检索与存储

- 元数据与全文索引：`SQLite + FTS5`
- 向量库：`Chroma`
- 融合策略：`RRF`

说明：

- `Chroma` 比较适合个人项目 MVP，Python 集成简单，Windows 也相对省事。
- 不采用“词法分数 + 向量分数直接加权”，避免量纲和方向不一致导致伪相关排序。

### 5.3 中文能力

FTS5 不直接依赖 `unicode61` 做中文检索。

采用：

- 写入前中文分词
- 查询前中文分词

初版建议直接使用 `jieba` 预分词，降低工程复杂度。

### 5.4 向量模型与重排模型

- 向量模型：`bge-m3`
- 重排模型：`bge-reranker-v2-m3`

理由：

- 中文和英文混合场景适配较好。
- 可本地部署。
- 适合个人知识库隐私场景。

### 5.5 部署配置（定稿）

- **监听地址**：`127.0.0.1`（仅本机访问，无鉴权）
- **端口**：`49153`（IANA 私有/动态端口附近，避开常用范围）
- **文档源**：`config.yaml` 中 `sources` 为数组，支持多目录与 glob 排除；第一版填 `E:\work\blog`，`excludes` 留空
- **GPU**：目标机可用，`bge-m3` 与 reranker 默认走 `cuda + float16`；CPU 作为降级路径保留
- **模型缓存**：`HF_HOME` 指向项目本地 `data/hf-cache`，避免污染用户目录

---

## 6. 文档处理设计

### 6.1 分块策略

采用两级切块：

1. 先按 Markdown 标题层级切 section。
2. section 过长时再按段落和递归字符切块。

要求：

- 代码块、表格、列表尽量保持完整。
- chunk 尽量控制在适合 embedding 和引用的长度。
- 记录 `title_path`，便于定位和引用。

### 6.2 每个分块的元数据

至少保留：

- `chunk_id`
- `doc_id`
- `file_path`
- `title_path`
- `chunk_index`
- `text`
- `token_count`
- `updated_at`
- `file_hash`
- `chunker_version`
- `embedding_model`

### 6.3 分块 ID 规则

建议：

`sha1(path + title_path + chunk_index + content_sha1)`

这样可以兼顾稳定性与去重能力。

---

## 7. 检索设计

### 7.1 采用混合检索

检索分两路：

1. `lexical retrieval`
   基于 SQLite FTS5

2. `semantic retrieval`
   基于 Chroma + `bge-m3`

### 7.2 融合方式

采用 `RRF`：

`final_score(d) = Σ 1 / (k + rank_i(d))`

默认 `k = 60`。

理由：

- 不依赖不同检索器的原始分值量纲。
- 对个人知识库这种小规模检索更稳。

### 7.3 重排

对 hybrid retrieval 的候选结果做 rerank：

- 召回 top 20
- rerank 后取 top 5 到 top 8

Rerank 应进入第一版可用版本，不建议拖到很后面。

---

## 8. 证据装配与拒答机制

### 8.1 职责边界

`kms-api` 不直接产出答案，而是产出"答案生成所需的全部物料"：

1. 检索 + rerank 后的 top-N 证据片段，带稳定 `chunk_id`、`file_path`、`title_path`、`score`
2. 一份固定的 prompt 模板（在服务端拼好，强制：只引证据、每条结论必带 `[chunk_id]`、资料不足必须拒答）
3. 一个布尔字段 `abstained`：服务端已判断证据不足时为 `true`，宿主可直接输出"资料不足"，不再调 LLM

宿主收到后自行调本机 LLM 生成最终答案。`kms-api` 零 LLM 依赖。

### 8.2 拒答条件（定稿阈值）

`abstained = true` 的触发条件（任一满足）：

- rerank 后 top1 `score` < `0.35`
- rerank 后 top3 平均 `score` < `0.30`
- 召回结果数 < `2`
- 所有入选证据片段总字符数 < `200`

以上阈值全部暴露在 `config.yaml` 的 `abstain:` 段，运行期可调。初版按上述值。

拒答时统一返回：

- `abstained = true`
- `prompt = ""`（宿主见到空 prompt 不再调 LLM）
- `abstain_reason`：命中的触发条件字符串，用于排查

### 8.3 引用校验（`POST /verify`）

宿主 LLM 生成答案后，**回调 `/verify`** 做后置校验：

1. 解析答案中的 `[chunk_id]` 标号，取回对应证据原文
2. 把答案按句号/换行切句，每句提取 >= 8 字符的 n-gram（中文按字滑窗，英文按词滑窗）
3. 对每个 n-gram 在被引 chunk 原文中做规范化（去空白、去标点、小写化）子串匹配
4. 命中 n-gram 数 / 总 n-gram 数 < `50%` → 标记 `citation_unverified = true`
5. 校验标志透传给宿主，由宿主决定是否在输出中提示用户"引用可能未被资料支撑"

阈值 `50%` 与 n-gram 最小长度 `8` 均在 `config.yaml` 的 `verify:` 段可调。

---

## 9. 双宿主适配

### 9.1 设计原则

`Claude Code` 和 `Codex` 都可以用，但都只做薄壳。

核心逻辑不能写死在：

- `~/.claude/skills/`
- 某个宿主专属命令目录

### 9.2 Claude Code 适配层

形态固定为：

- `~/.claude/skills/kms/SKILL.md`（主流程编排）
- `~/.claude/skills/kms/reference/api.md`（API 契约副本）
- 调用方式：Bash `curl http://127.0.0.1:49153/...`
- **不使用 MCP**。后续如需"日常对话自动调用"，再叠加一层 MCP 薄包装，不改核心。

### 9.3 Codex 适配层

形态固定为：

- `~/.codex/prompts/kms.md`（或项目级 `AGENTS.md` 中的 `kms` 段）
- 调用方式：Shell `curl http://127.0.0.1:49153/...`，与 Claude Code 共用同一份 `reference/api.md` 契约
- 仅做参数整形与结果渲染，不实现检索逻辑

### 9.4 协议统一

宿主统一调用相同 API：

- `POST /index`
- `POST /search`
- `POST /ask`
- `POST /verify`
- `GET /stats`
- `GET /health`

这样后续新增宿主时不影响核心实现。

---

## 10. API 建议

### 10.1 `POST /index`

作用：

- 全量或增量索引

请求示例：

```json
{
  "mode": "incremental"
}
```

### 10.2 `POST /search`

作用：

- 只返回证据，不装配 prompt、不生成答案
- 接收宿主已扩写好的多 query（不扩写时传长度为 1 的数组即可）

请求示例：

```json
{
  "queries": ["混合检索为什么比纯向量检索更稳", "为什么不能只用语义检索", "hybrid retrieval 优势"],
  "recall_top_k": 20,
  "rerank_top_k": 6
}
```

响应示例：

```json
{
  "results": [
    {
      "chunk_id": "...",
      "file_path": "...",
      "title_path": ["..."],
      "text": "...",
      "score": 0.83
    }
  ],
  "debug": {
    "queries_count": 3,
    "recall_count": 47
  }
}
```

### 10.3 `POST /ask`

作用：

- 检索 + rerank + 证据装配 + 拒答判定
- **不调用任何 LLM**；返回宿主 LLM 可直接使用的 `prompt` 字符串

请求示例：

```json
{
  "question": "为什么个人知识库不能只做向量检索？",
  "queries": ["为什么个人知识库不能只做向量检索？", "纯向量检索的局限"],
  "rerank_top_k": 6
}
```

响应示例（命中充分）：

```json
{
  "abstained": false,
  "confidence": 0.78,
  "prompt": "<服务端拼好的完整 prompt，含系统约束 + 证据 + 引用格式要求>",
  "sources": [
    {
      "chunk_id": "notes/rag.md#7",
      "file_path": "notes/rag.md",
      "title_path": ["RAG", "Hybrid Retrieval"],
      "text": "...",
      "score": 0.83
    }
  ],
  "abstain_reason": null
}
```

拒答示例：

```json
{
  "abstained": true,
  "confidence": 0.12,
  "prompt": "",
  "sources": [],
  "abstain_reason": "top1_score_below_threshold"
}
```

宿主侧行为约定：`abstained=true` 时直接输出"资料不足，无法确认。"，不再调 LLM。

### 10.4 `POST /verify`

作用：

- 宿主 LLM 生成答案后回调，做引用 n-gram 校验
- 规则见 §8.3

请求示例：

```json
{
  "answer": "混合检索结合了词法与语义检索的优势 [notes/rag.md#7] ...",
  "used_chunk_ids": ["notes/rag.md#7", "notes/rag.md#4"]
}
```

响应示例：

```json
{
  "citation_unverified": false,
  "coverage": 0.82,
  "details": [
    {"chunk_id": "notes/rag.md#7", "matched_ngrams": 14, "total_ngrams": 17}
  ]
}
```

### 10.5 `GET /stats`

作用：

- 返回文档数、chunk 数、模型信息、索引版本

### 10.6 `GET /health`

作用：

- 健康检查
- 宿主启动前探活

---

## 11. 目录结构建议

```text
E:\github\cckms\
  pyproject.toml
  README.md
  config.yaml
  app/
    main.py
    config.py
    schemas.py
    ingest/
      loader.py
      markdown_parser.py
      chunker.py
      state.py
    store/
      sqlite_store.py
      fts_store.py
      vector_store.py
    retrieve/
      lexical.py
      semantic.py
      hybrid.py
      rerank.py
    answer/
      prompt.py           # 装配宿主用 prompt
      guardrail.py        # 拒答阈值判定
      citation_check.py   # /verify 的 n-gram 校验
    adapters/
      claude/             # SKILL.md 模板
      codex/              # prompts/kms.md 模板
  data/
    meta.db
    chroma/
    hf-cache/             # HF_HOME 指向此处
```

说明：

- 仓库内不再有 `answer/generator.py`（生成答案的职责已转交宿主 LLM）。
- `adapters/` 放仓库里作为模板，部署时再拷贝或软链到 `~/.claude/skills/kms/` 和 `~/.codex/prompts/`。

### 11.1 `config.yaml` 定稿示例

```yaml
server:
    host: 127.0.0.1
    port: 49153

sources:
    - path: E:\work\blog
      excludes: []
    # 支持多个源目录；后续新增直接追加

data:
    sqlite: ./data/meta.db
    chroma: ./data/chroma
    hf_cache: ./data/hf-cache

models:
    embedding: BAAI/bge-m3
    reranker: BAAI/bge-reranker-v2-m3
    device: cuda            # cuda / cpu
    dtype: float16          # float16 / float32

chunker:
    version: v1
    chunk_size: 800
    chunk_overlap: 100

retrieval:
    recall_top_k: 20
    rerank_top_k: 6
    rrf_k: 60

abstain:
    top1_min: 0.35
    top3_avg_min: 0.30
    min_hits: 2
    min_total_chars: 200

verify:
    min_ngram_len: 8
    coverage_threshold: 0.50
```

---

## 12. 增量索引与一致性

### 12.1 增量判断

基于：

- `path`
- `mtime`
- `file_hash`

### 12.2 强制全量重建条件

以下任一变化都强制 full reindex：

- `chunker_version` 变化
- `embedding_model` 变化
- `embedding_dim` 变化
- 向量库 schema 变化

### 12.3 重命名处理

文件重命名按：

- 删除旧文档
- 新增新文档

处理，避免残留脏 chunk。

---

## 13. 实施顺序

### M0 环境验收

先验证：

- Windows + CUDA 环境上 `torch`、`FlagEmbedding`、`Chroma` 可安装
- `bge-m3` 和 `bge-reranker-v2-m3` 能在 GPU 上真实加载并跑通一次 embedding / rerank
- CPU-only 路径作为降级保留，不作为正式支持场景
- 锁定 `torch` / `FlagEmbedding` / `chromadb` / `langchain-text-splitters` / `jieba` 版本

### M1 索引基础能力

- 配置管理（读 `config.yaml`）
- 文档扫描（多 `sources` + glob 排除）
- Markdown 两级分块 + chunk_id 规则
- SQLite 元数据（documents / chunks / ingest_log）
- FTS5 入库（jieba 预分词）
- Chroma 入库（bge-m3 embedding）

### M2 检索 API

- lexical retrieval（FTS5）
- semantic retrieval（Chroma）
- RRF 融合（k=60）
- `POST /search`（`queries: List[str]` + `recall_top_k` / `rerank_top_k`）

### M3 证据装配 API

- rerank（bge-reranker-v2-m3）
- 拒答判定（§8.2 四条阈值）
- prompt 装配（强约束模板）
- `POST /ask`（返回 `prompt` + `sources` + `abstained`）
- `POST /verify`（n-gram 引用校验）

### M4 双宿主适配

- Claude Code adapter（`SKILL.md` + curl）
- Codex adapter（`prompts/kms.md` 或 `AGENTS.md` + curl）
- `/kms index` / `/kms search` / `/kms ask` / `/kms doctor` 命令
- `GET /health` + `GET /stats`

### M5 评估与打磨

- 评测数据集（20-50 正样本 + 5-10 负样本）
- Recall@k / MRR
- 拒答准确率
- 引用校验命中率
- 耗时与冷启动指标

---

## 14. 测试与评估

至少准备一份小型评测集：

- 20 到 50 条正样本问题
- 5 到 10 条负样本问题

评估指标：

- `Recall@5`
- `MRR`
- 正确引用率
- 拒答准确率
- 平均检索耗时
- 冷启动耗时

---

## 15. 最终推荐

最终采用以下固定路线：

- 核心架构：独立 `kms-api`（`127.0.0.1:49153`，零 LLM 依赖）
- 文档处理：Markdown 标题分块 + 元数据，多 `sources` 可配
- 检索：`SQLite FTS5 + Chroma`
- 中文处理：`jieba` 预分词
- embedding：`bge-m3`（GPU + fp16）
- rerank：`bge-reranker-v2-m3`
- 融合：`RRF(k=60)`
- 回答：**宿主 LLM 生成**，服务端只装配 prompt + 证据
- 可信性：阈值拒答（`abstained`）+ n-gram 引用校验（`citation_unverified`）
- 集成：`Claude Code + Codex` 双宿主薄适配，统一 HTTP `curl`，不走 MCP

这版比原始两套方案更稳，原因是：

- 保留了可直接落地的工程拆分
- 修正了中文检索与分数融合问题
- 把"严格基于资料"从口号变成了机制（拒答 + 引用校验双保险）
- 明确支持双宿主，避免后续返工
- 服务端零 LLM 依赖，答案生成交给宿主，隐私与成本都更友好
