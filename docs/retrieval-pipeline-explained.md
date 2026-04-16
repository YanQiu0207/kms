# 检索管线技术原理详解

> 本文面向想理解"这套 RAG 系统到底在干什么"的开发者。
> 每个阶段都会讲清楚：要解决什么问题、用了什么技术、技术原理是什么、在本项目中的效果如何。
> 所有示例均来自本项目的真实数据和代码。

---

## 全局概览

用户向知识库提一个问题（比如"两阶段提交协议的流程是什么"），系统需要：

1. 从 ~100 篇 Markdown 笔记（~2700 个文本片段）中**找到最相关的几段**
2. 判断找到的内容**够不够回答这个问题**
3. 如果够，就把问题和证据**组装成 prompt**，交给外部 LLM 生成答案

这个过程分为两大管线：

```
离线管线（索引）：Markdown 文件 → 清洗 → 分段 → 向量化 → 写入存储
在线管线（检索）：用户查询 → 查询理解 → 双路召回 → 融合 → 重排 → 过滤 → 组装 prompt
```

下面逐阶段展开。

---

## 第一部分：离线管线（索引阶段）

### 阶段 1：文档扫描与清洗

#### 要解决什么问题

原始 Markdown 文件里有很多"噪音"，直接拿来切块和检索效果会很差。

**具体例子**：

```markdown
---
title: 两阶段提交协议
tags: [分布式, 一致性]
aliases: [2PC, Two-Phase Commit]
category: 分布式系统
---

[toc]

# 两阶段提交协议

（正文……）

---
编辑于 2024-03-15 · 知乎
```

这段文本有几个问题：

- **YAML front matter**（`---` 之间的部分）：不是正文，但里面的 `title`、`tags`、`aliases` 对检索极有价值
- **`[toc]` 标记**：目录占位符，对检索毫无意义
- **页脚文字**（"编辑于……知乎"）：从知乎复制来的模板文字，如果被切入 chunk 会干扰语义匹配

#### 用了什么技术

项目自建的 `MarkdownCleaner`（`app/ingest/cleaner.py`），执行以下清洗步骤：

| 步骤 | 做了什么 | 为什么要做 |
|------|---------|-----------|
| BOM 去除 | 删掉 UTF-8 文件开头的 `\ufeff` 字节 | 某些 Windows 编辑器会加 BOM，影响解析 |
| Front matter 提取 | 解析 YAML 头部为结构化 dict，从正文中移除 | 让元数据进入检索系统，同时不污染正文内容 |
| 空白规范化 | 统一换行符为 `\n`，去除行尾空格 | 避免空白差异导致重复 chunk |
| TOC 标记删除 | 匹配 `[toc]`、`[TOC]` 等行并删除 | 无检索价值 |
| 低价值占位符删除 | 匹配"待续"、"TBD"、"WIP"等行并删除 | 空内容占 chunk 空间 |
| Markdown 表格规范化 | 将表格转为"表格行: key=value"格式 | 原始表格语法对分词和语义匹配极不友好 |
| 来源特定规则 | 按文件路径匹配，删除知乎页脚等模板文字 | 特定来源的噪音需要针对性处理 |

#### 效果

在 M13 阶段的实测中，清洗 + front matter 元数据注入后：
- `recall@K`：0.875 → 1.0
- `MRR`：0.7917 → 1.0
- `false_answer_rate`（给出了错误答案的比率）：0.5 → 0.0

---

### 阶段 2：文档分段（Section Parsing）

#### 要解决什么问题

一篇 Markdown 笔记可能有几千字，但检索需要在**段落级别**匹配。直接对整篇文章做 embedding 会导致语义被"稀释"——如果文章讲了 10 个主题，向量只能表达一个"平均"的语义方向。

**具体例子**：

一篇名为"分布式系统基础知识.md"的文章，结构为：

```markdown
# 分布式系统基础知识
## CAP 定理
（CAP 的内容……）
## 两阶段提交
（2PC 的内容……）
## Raft 共识算法
（Raft 的内容……）
```

如果用户问"两阶段提交是什么"，我们希望匹配的是 `## 两阶段提交` 这个 section，而不是整篇文章。

#### 用了什么技术

项目自建的 `MarkdownParser`（`app/ingest/markdown_parser.py`），按 Markdown 标题层级切分 section。

**工作原理**：

1. 逐行扫描文本
2. 识别 ATX 标题（`# 标题`、`## 标题` 等）和 Setext 标题（标题下方用 `===` 或 `---`）
3. 遇到新标题时，把之前积累的行作为一个 section 输出
4. 维护一个 `title_path` 栈，记录当前所处的标题层级

**关键细节**：解析器会识别代码块（反引号围栏 ```` ``` ````），代码块内的 `#` 不会被当作标题——这避免了把 Python 注释或 Shell 命令误认为 Markdown 标题。

**输出结构**：

```
MarkdownSection(
    document_id="sha1-of-filepath",
    title_path=("分布式系统基础知识", "两阶段提交"),
    heading="两阶段提交",
    heading_level=2,
    section_index=1,
    start_line=5,
    end_line=20,
    text="两阶段提交（2PC）是一种……"
)
```

`title_path` 保留了层级关系，后续检索时可以用来判断"这个 chunk 是在讲什么主题"。

---

### 阶段 3：文本分块（Chunking）

#### 要解决什么问题

Section 解析后，一个 section 可能仍然很长（比如一个章节有 3000 字）。Embedding 模型有输入长度限制，而且过长的文本会让向量的"语义焦点"变模糊。需要进一步切成更小的 chunk。

但切块不能"一刀切"——如果正好把一句话切成两半，两个 chunk 都不完整。

#### 用了什么技术

项目自建的 `MarkdownChunker`（`app/ingest/chunker.py`），两级策略：

**第一级：段落合并**

先按空行把 section 切成"段落块"（block），然后贪心地合并相邻块，直到总长度接近 `chunk_size`（800 字符）。

```
Block 1: "两阶段提交（2PC）是一种分布式事务协议……"（200 字）
Block 2: "阶段一：Prepare。协调者向所有参与者发送……"（300 字）
Block 3: "阶段二：Commit。如果所有参与者都回复 Yes……"（250 字）
```

Block 1 + Block 2 = 500 字 < 800，继续合并。
Block 1 + Block 2 + Block 3 = 750 字 < 800，继续合并。
→ 三个 block 合成一个 chunk。

**第二级：长块切割**

如果单个段落块本身就超过 800 字符（比如一个很长的代码示例），就按优先级寻找切割点：

```python
# 切割点优先级（从高到低）
candidates = [
    "\n\n",   # 优先在空行处切
    "\n",     # 其次在换行处切
    "。",     # 中文句号
    "！", "？",
    ". ", "! ", "? ",  # 英文句末
    " ",      # 最后在空格处切
]
```

同时，相邻 chunk 之间有 100 字符的重叠（overlap），确保切割边界处的信息不会丢失。

**输出结构**：

每个 chunk 携带完整的上下文信息：

```
MarkdownChunk(
    chunk_id="sha1(document_id + title_path + section_index + chunk_index + content_sha1)",
    document_id="...",
    file_path="E:\\notes\\分布式系统基础知识.md",
    title_path=("分布式系统基础知识", "两阶段提交"),
    section_index=1,
    chunk_index=0,
    start_line=5,
    end_line=20,
    text="两阶段提交（2PC）是一种分布式事务协议……",
    token_count=156,
    metadata={
        "front_matter_title": "分布式系统基础知识",
        "front_matter_category": "分布式系统",
        "front_matter_aliases": ["2PC", "Two-Phase Commit"],
        "front_matter_tags": ["分布式", "一致性"],
        "relative_path": "分布式系统基础知识.md",
        "path_segments": ["分布式系统基础知识"]
    }
)
```

注意 `metadata` 中包含了从 front matter 提取的结构化信息，这些信息在后续检索中会被用到。

---

### 阶段 4：向量化与存储

#### 要解决什么问题

文本 chunk 需要转换成计算机能高效计算"相似度"的格式，同时需要支持两种不同的检索方式。

#### 用了什么技术

每个 chunk 被写入三个存储：

| 存储 | 技术 | 用途 |
|------|------|------|
| SQLite 元数据表 | SQLite 3 | 存储文档和 chunk 的完整信息（内容、路径、hash、元数据） |
| FTS5 全文索引 | SQLite FTS5 扩展 | 支持关键词检索（词法检索） |
| Chroma 向量库 | Chroma（向量数据库） | 支持语义相似度检索（向量检索） |

下面重点解释两个检索存储的技术原理。

---

## 第二部分：在线管线（检索阶段）

### 阶段 5：查询理解（Query Understanding）

#### 要解决什么问题

用户的提问方式多种多样，同一个意图可以有完全不同的表述。如果只用原始查询去检索，很容易漏掉相关结果。

**具体例子**：

用户问："2PC 和 3PC 有什么区别？"

问题分析：
- 这是一个**比较型**问题（comparison），需要同时找到 2PC 和 3PC 的文档
- "2PC"是"两阶段提交"的缩写（alias），文档中可能只写了全称
- 需要生成多个查询变体来提高召回率

#### 用了什么技术

项目自建的 `query_understanding.py`，执行三步分析：

**Step 1：查询类型检测**

通过关键词规则判断查询类型：

| 查询类型 | 触发关键词 | 例子 |
|----------|-----------|------|
| `definition` | （默认） | "什么是 Raft" |
| `comparison` | 相比、区别、不同、优缺点 | "2PC 和 3PC 有什么区别" |
| `existence` | 有没有、是否有、哪篇 | "知识库里有没有讲 CAP 的笔记" |
| `procedure` | 如何、怎么、步骤 | "如何配置 GDB 调试" |
| `lookup` | 缩写、简称、哪个命令 | "查看当前进程信息的命令是什么" |

**Step 2：别名展开**

系统内置了别名映射组：

```python
_ALIAS_GROUPS = (
    ("2pc", "两阶段提交", "两阶段提交协议"),
    ("3pc", "三阶段提交"),
    ("hlc", "hybrid logical clock", "混合逻辑时钟"),
    # ...
)
```

如果查询中包含"2pc"，系统会自动生成"两阶段提交"和"两阶段提交协议"的查询变体。

**Step 3：查询变体生成**

对于"2PC 和 3PC 有什么区别"，系统会生成：

```
原始查询:  "2PC 和 3PC 有什么区别"
变体 1:    "2PC 3PC 区别"         （去标点、提取关键词）
变体 2:    "两阶段提交 三阶段提交"  （别名替换）
变体 3:    "2pc 3pc"              （比较型 anchor terms）
```

多个变体会分别送入词法检索和语义检索，增加召回率。

**Step 4：检索参数路由**

不同查询类型使用不同的检索参数：

```python
if profile.query_type == "comparison":
    routed_recall = max(routed_recall, 24)   # 比较型需要更多候选
    routed_rerank = max(routed_rerank, 8)    # 保留更多结果
elif profile.query_type == "procedure":
    routed_recall = max(routed_recall, 22)
    routed_rerank = max(routed_rerank, 8)
```

比较型问题需要同时找到两个对象的文档，所以召回数量要更大。

---

### 阶段 6：词法检索（Lexical Retrieval）

#### 要解决什么问题

当用户使用精确的术语搜索时（比如"TrueTime"、"bge-m3"、"Paxos"），需要通过**精确匹配关键词**来找到相关文档。这是语义检索的弱项——"bge-m3"和"embedding model"在语义上相关，但语义检索可能把它们排在不同位置。

#### 用了什么技术

**SQLite FTS5**（Full-Text Search 5）+ **Jieba 中文分词** + **BM25 评分**。

#### 技术原理

##### Jieba 分词

中文不像英文有天然的空格分词。"两阶段提交协议"如果不分词，系统根本不知道里面包含"两阶段"、"提交"、"协议"这些独立的词。

**Jieba**（结巴分词）是一个中文分词库，原理是：

1. 维护一个包含几十万中文词汇的词典
2. 用动态规划算法找出最可能的分词路径（使句子中每个词出现的概率之积最大）
3. 对于词典中没有的新词，用 HMM（隐马尔科夫模型）发现

```
输入: "两阶段提交协议的流程"
输出: ["两", "阶段", "提交", "协议", "的", "流程"]
```

在本项目中，Jieba 被封装在 `app/vendors/jieba_tokenizer.py`，通过防腐层调用：

```python
def cut_tokens(text: str) -> Sequence[str] | None:
    jieba = _load_jieba()
    if jieba is None:
        return None        # jieba 不可用时退回到正则分词
    return jieba.lcut(text, cut_all=False)
```

如果 Jieba 不可用，系统会退回到基于正则的分词（Unicode 字符 + CJK 二元组），确保基本功能不丢失。

##### FTS5 全文索引

FTS5 是 SQLite 的全文搜索扩展。它的核心思想是**倒排索引**（Inverted Index）：

```
正向索引（按文档组织）：
  chunk_1 → ["两阶段", "提交", "协议", "分布式", "事务"]
  chunk_2 → ["raft", "共识", "算法", "选举", "日志"]
  chunk_3 → ["提交", "回滚", "事务", "数据库"]

倒排索引（按词组织）：
  "提交"   → [chunk_1, chunk_3]
  "两阶段" → [chunk_1]
  "raft"   → [chunk_2]
  "事务"   → [chunk_1, chunk_3]
```

当用户搜索"两阶段 提交"时，系统直接查倒排索引，找到同时包含这两个词的 chunk，而不需要扫描所有文档。

在本项目中，FTS5 表的结构为（`app/store/fts_store.py`）：

```sql
CREATE VIRTUAL TABLE chunk_fts USING fts5(
    chunk_id UNINDEXED,     -- 不参与搜索，只用于关联
    document_id UNINDEXED,  -- 不参与搜索
    file_path UNINDEXED,    -- 不参与搜索
    title_path,             -- 标题路径参与搜索
    content,                -- 正文参与搜索
    metadata_text           -- 元数据文本参与搜索
);
```

写入时，文本会先经过 Jieba 分词再存入：

```python
# 原文: "两阶段提交（2PC）是一种分布式事务协议"
# 分词后写入 FTS5: "两 阶段 提交 2pc 是 一 种 分布式 事务 协议"
```

##### BM25 评分算法

找到包含关键词的 chunk 后，需要给它们**排序**——哪个 chunk 最相关？BM25（Best Matching 25）是信息检索领域最经典的排序算法。

**核心思想**：一个词对一篇文档的重要性取决于两个因素：

1. **词频（TF, Term Frequency）**：这个词在这篇文档中出现了多少次？出现越多，越可能相关。但不是线性增长——出现 10 次不比出现 5 次重要一倍（边际递减）。

2. **逆文档频率（IDF, Inverse Document Frequency）**：这个词在所有文档中有多常见？"的"在每篇文档中都出现，所以它的区分度很低；"Paxos"只在少数文档中出现，所以它的区分度很高。

**公式直觉**：

```
BM25(词, 文档) = IDF(词) × TF(词, 文档) × 调节因子

IDF(词) ≈ log(总文档数 / 包含该词的文档数)
  → "的": log(2700/2700) ≈ 0（无区分度）
  → "Paxos": log(2700/3) ≈ 6.8（高区分度）

TF(词, 文档) ≈ 词频 / (词频 + k)
  → 出现 1 次: 1/(1+1.2) ≈ 0.45
  → 出现 5 次: 5/(5+1.2) ≈ 0.81
  → 出现 100 次: 100/(100+1.2) ≈ 0.99（收益递减）
```

在本项目中，对 FTS5 表的不同列设置了不同的 BM25 权重（`app/retrieve/lexical.py`）：

```sql
bm25(chunk_fts, 0.0, 0.0, 0.0, 2.5, 1.5, 0.2)
--                 ↑    ↑    ↑   ↑    ↑    ↑
--              chunk_id  |  file  title content metadata
--                   doc_id  path  path         text
```

`title_path` 权重 2.5 最高——如果用户的搜索词出现在标题中，说明高度相关；`metadata_text` 权重 0.2 最低，因为元数据是辅助信息。

#### 查询构造

用户输入经过分词后，用 OR 连接所有 token 作为 FTS5 查询：

```python
# 输入: "两阶段提交协议的流程"
# 分词: ["两", "阶段", "提交", "协议", "的", "流程"]
# FTS5 查询: "两 OR 阶段 OR 提交 OR 协议 OR 的 OR 流程"
```

使用 OR 而非 AND 是为了提高召回率——即使文档只匹配了部分关键词，也不会被完全排除，只是 BM25 分数会较低。

---

### 阶段 7：语义检索（Semantic Retrieval）

#### 要解决什么问题

词法检索依赖精确的关键词匹配，无法处理"同义不同词"的情况。

**具体例子**：

用户问："分布式系统如何保证数据一致性？"

文档中可能写的是："在多副本架构中，使用共识算法确保副本间的状态同步"

两段文本没有任何共同关键词（"一致性" vs "同步"，"保证" vs "确保"），词法检索会完全漏掉。但语义上，它们说的是同一件事。

#### 用了什么技术

**BGE-M3 嵌入模型** + **Chroma 向量数据库** + **余弦相似度**。

#### 技术原理

##### 文本嵌入（Text Embedding）

Embedding（嵌入）是把一段文本转换成一个固定长度的数字向量的过程。

**直觉理解**：假设我们把所有概念放在一个多维空间中。相似的概念在空间中距离近，不相似的概念距离远。

```
                    "分布式事务"
                        ●
                       ╱
                      ╱
            "2PC" ●  ╱
                    ╲╱
                     ● "两阶段提交"
                    
                    
                    
            "递归" ●              ● "冒泡排序"
```

每段文本被映射为一个 1024 维的向量（BGE-M3 的输出维度）。虽然人类无法直观理解 1024 维空间，但数学上的距离计算是完全可行的。

##### BGE-M3 模型

本项目使用的 embedding 模型是 **BAAI/bge-m3**（由北京智源人工智能研究院发布），是目前中文 embedding 领域的顶尖模型之一。

**名字含义**：M3 = Multi-Linguality（多语言）+ Multi-Functionality（多功能）+ Multi-Granularity（多粒度）。

**工作原理**：

1. 文本经过 tokenizer 切分为 subword tokens
2. Tokens 送入 Transformer 编码器（BERT 架构，12 层 self-attention）
3. 模型输出每个 token 位置的向量表示
4. 取所有 token 向量的加权平均，得到一个 1024 维的"句向量"

**为什么能理解语义**：BGE-M3 在海量的文本对上训练——比如（问题, 答案）对、（原文, 翻译）对、（同义句 A, 同义句 B）对。训练目标是让语义相似的文本对的向量距离近，不相似的距离远。经过数十亿文本对的训练后，模型学会了把"语义相似"映射为"向量距离近"。

在本项目中，BGE-M3 通过防腐层加载（`app/vendors/flag_embedding.py`）：

```python
from FlagEmbedding import FlagAutoModel
model = FlagAutoModel.from_finetuned("BAAI/bge-m3", devices="cuda", use_fp16=True)
embeddings = model.encode(["两阶段提交协议的流程是什么"])
# 输出: [[0.023, -0.156, 0.089, ...]]  (1024 维浮点数组)
```

**配置参数**（`config.yaml`）：

```yaml
models:
  embedding: BAAI/bge-m3
  device: cuda        # 使用 GPU 加速
  dtype: float16      # 半精度浮点，减少显存占用
  embedding_batch_size: 8  # 每次处理 8 个文本
```

##### Chroma 向量数据库

向量计算出来后需要存储，检索时需要快速找到"跟查询向量最近的 N 个向量"。这就是向量数据库的工作。

**Chroma** 是一个轻量级的向量数据库，本项目使用它的本地持久化模式。

**核心数据结构：HNSW 索引**

暴力搜索（把查询向量跟所有 2700 个 chunk 向量逐一比较）虽然准确，但在大规模数据下太慢。Chroma 使用 **HNSW（Hierarchical Navigable Small World）** 索引来加速。

HNSW 的直觉：想象一个社交网络，每个人（向量）只认识几个"邻居"。要找到跟你最像的人，不需要跟所有人见面——你先问你的朋友"谁跟我像？"，朋友指向一个更像的人，你再问那个人……经过几跳就能找到最相似的人。

```
层 2（粗粒度）:    A ------- D ------- G
                   |                   |
层 1（中粒度）:    A --- C --- D --- F --- G
                   |   |   |   |   |   |
层 0（细粒度）:    A - B - C - D - E - F - G - H
```

搜索从最顶层开始（节点少，跳跃快），逐层向下，每层都在更精细的邻居图中寻找更近的节点。最终在第 0 层找到最近邻。

**相似度度量：余弦相似度**

本项目配置了 `hnsw:space = cosine`，意味着使用**余弦相似度**来衡量向量间的距离。

```
余弦相似度 = cos(θ) = (A · B) / (|A| × |B|)

其中 A · B 是向量点积，|A| 和 |B| 是向量的模

范围: [-1, 1]
  1  = 完全相同方向（最相似）
  0  = 正交（无关）
  -1 = 完全相反方向（最不相似）
```

为什么用余弦而非欧氏距离？因为余弦只看"方向"，不看"长度"。两段语义相同但长度不同的文本（一段 50 字，一段 500 字），欧氏距离可能很大，但余弦相似度会很高。

在本项目中，Chroma 返回的是距离（distance），再转换为分数：

```python
# distance 越小越相似
score = 1.0 / (1.0 + max(0.0, distance))
# distance=0 → score=1.0（完全匹配）
# distance=1 → score=0.5
# distance=9 → score=0.1
```

在本项目中，Chroma 被封装在 `app/vendors/chroma.py` 和 `app/store/vector_store.py`，通过防腐层调用。

---

### 阶段 8：融合（RRF — Reciprocal Rank Fusion）

#### 要解决什么问题

现在我们有了两路检索结果——词法检索给了一个排名，语义检索给了另一个排名。问题是：**怎么把两个排名合并成一个？**

直接比较分数是不行的，因为两路的分数不在同一个尺度上：
- BM25 分数可能是 -5.2（FTS5 的 BM25 分数是负数，越小越好）
- 余弦距离可能是 0.35

它们没有可比性。

#### 用了什么技术

**RRF（Reciprocal Rank Fusion）**——一种只看排名、不看分数的融合方法。

#### 技术原理

RRF 的思想极其简单：**在多个排名中都排在前面的结果，一定是好结果。**

公式：

```
RRF_score(chunk) = Σ 1 / (k + rank_i)

其中：
  k = 常数（本项目中 k=60）
  rank_i = chunk 在第 i 个排名列表中的位置（从 1 开始）
  Σ = 对所有排名列表求和
```

**具体例子**：

假设用户查询"两阶段提交协议"，生成了两个查询变体。每个变体在词法和语义两路各得到一个排名：

```
lexical:"两阶段提交协议"   → [chunk_A(rank=1), chunk_B(rank=2), chunk_C(rank=3)]
semantic:"两阶段提交协议"  → [chunk_B(rank=1), chunk_A(rank=2), chunk_D(rank=3)]
lexical:"2pc 提交 协议"    → [chunk_A(rank=1), chunk_D(rank=2), chunk_E(rank=3)]
semantic:"2pc 提交 协议"   → [chunk_A(rank=1), chunk_B(rank=2), chunk_C(rank=3)]
```

计算各 chunk 的 RRF 分数（k=60）：

```
chunk_A: 1/(60+1) + 1/(60+2) + 1/(60+1) + 1/(60+1) = 0.0164 + 0.0161 + 0.0164 + 0.0164 = 0.0653
chunk_B: 1/(60+2) + 1/(60+1) + 0        + 1/(60+2) = 0.0161 + 0.0164 + 0       + 0.0161 = 0.0486
chunk_C: 1/(60+3) + 0        + 0        + 1/(60+3) = 0.0159 + 0       + 0       + 0.0159 = 0.0318
chunk_D: 0        + 1/(60+3) + 1/(60+2) + 0        = 0       + 0.0159 + 0.0161 + 0       = 0.0320
chunk_E: 0        + 0        + 1/(60+3) + 0        = 0.0159
```

排序：chunk_A > chunk_B > chunk_D > chunk_C > chunk_E

**为什么 k=60？**

k 控制"排名位置差异的敏感度"：
- k 越大，前几名和后几名的分数差异越小，融合结果越"民主"
- k 越小，排名第 1 的结果会远远高于排名第 2 的，融合结果越"独裁"

k=60 是原始论文推荐的默认值，在大多数场景下表现稳健。

**RRF 的优势**：
- 不需要校准不同检索系统的分数
- 对异常值不敏感（一路给出离谱高分不会主导结果）
- 实现极其简单

在本项目中，RRF 实现在 `app/retrieve/hybrid.py` 的 `reciprocal_rank_fusion()` 函数。

---

### 阶段 9：重排（Reranking）

#### 要解决什么问题

RRF 融合后的排名是一个"粗排"——它基于两路检索的排名位置，但没有精细地衡量"查询和 chunk 之间到底有多相关"。

**为什么需要二次排序？**

因为召回阶段（词法 + 语义）为了速度做了妥协：

- **词法检索**：只看关键词是否出现，不理解语义
- **语义检索**：用的是双塔模型（Bi-Encoder），查询和文档**分别**编码为向量再比较，无法捕捉细粒度的交互

而 Reranker 是**交叉编码器**（Cross-Encoder），它把查询和文档**拼接在一起**送入 Transformer，能够捕捉两者之间每个 token 级别的交互关系。

#### 用了什么技术

**BAAI/bge-reranker-v2-m3**——与 BGE-M3 同系列的交叉编码器重排模型。

#### 技术原理

##### Bi-Encoder vs Cross-Encoder

这是理解"为什么需要重排"的关键对比：

**Bi-Encoder（双塔模型，用于召回阶段）**：

```
查询: "两阶段提交的流程"  →  Encoder  →  向量 Q
文档: "2PC 分为 prepare 和 commit 两个阶段"  →  Encoder  →  向量 D

相似度 = cosine(Q, D)
```

- 查询和文档**独立编码**，互不影响
- 文档向量可以**离线预计算**，查询时只需算查询向量 + 向量比较
- 速度快，适合从 2700 个 chunk 中召回 top 20
- 但精度有限——因为编码时看不到对方

**Cross-Encoder（交叉编码器，用于重排阶段）**：

```
输入: "[CLS] 两阶段提交的流程 [SEP] 2PC 分为 prepare 和 commit 两个阶段 [SEP]"
  ↓
Transformer（12 层 self-attention）
  ↓
相关性分数: 0.92
```

- 查询和文档**拼接后一起编码**
- 每个 token 都能看到对方所有 token（通过 self-attention）
- 比如"两阶段"这个词能直接 attend 到文档中的"两个阶段"和"2PC"
- 精度高——能理解"两阶段提交"和"prepare + commit 两个阶段"说的是同一件事
- 但速度慢——每个（查询, 文档）对都要过一遍 Transformer
- 所以只能对召回后的 top 20~24 个候选做重排，不能对全部 2700 个 chunk 做

##### 分数归一化

Cross-Encoder 输出的是一个原始 logit 分数（可能是 -10 到 +10 的范围），需要转换到 [0, 1] 区间。本项目使用 **Sigmoid 函数**：

```python
def _normalize_score(score: float) -> float:
    bounded = max(min(float(score), 20.0), -20.0)  # 防止溢出
    return 1.0 / (1.0 + math.exp(-bounded))

# score=0  → 0.5（中性）
# score=5  → 0.993（强相关）
# score=-5 → 0.007（不相关）
```

Sigmoid 函数的形状像一个 S 曲线，把任意实数压缩到 (0, 1) 区间。

##### 多查询重排

当有多个查询变体时，每个变体都会和所有候选 chunk 配对做一次 Cross-Encoder 打分。对于每个 chunk，取所有变体中的**最高分**作为最终分数：

```python
# 查询变体 1: "两阶段提交的流程" × chunk_A → 0.92
# 查询变体 2: "2pc 提交 协议"   × chunk_A → 0.88
# 查询变体 3: "两阶段提交协议"   × chunk_A → 0.95
# 
# chunk_A 的最终分数 = max(0.92, 0.88, 0.95) = 0.95
```

在本项目中，重排实现在 `app/retrieve/rerank.py`，核心类 `FlagEmbeddingReranker` 负责调用模型。

---

### 阶段 10：多阶段后处理

#### 要解决什么问题

重排后的结果在大多数情况下已经不错了，但有些特殊场景仍然会出问题。

**具体例子**：

1. **元数据约束场景**：用户问"分布式系统分类下有哪些笔记？"——这不是在问内容，而是在问**分类元数据**。需要根据 chunk 的 `front_matter_category` 来过滤。

2. **定义型查询的主题亲和度**：用户问"什么是 HLC？"——文档 A 的标题就叫"HLC（混合逻辑时钟）"，文档 B 只是在某段提了一句 HLC。即使 B 的 rerank 分数更高，也应该优先返回 A。

3. **Lookup 型查询的表格优先**：用户问"GDB 查看当前线程信息的命令是什么？"——答案往往在一个表格中，应该优先返回包含表格的 chunk。

4. **文档多样性**：如果 top 6 个结果全来自同一篇文档的不同 chunk，对于 lookup 型查询应该交错排列，避免单一文档垄断。

#### 用了什么技术

项目在 `hybrid.py` 的 `search_and_rerank()` 方法中串联了多个后处理步骤：

```
重排结果
  ↓
1. 元数据约束过滤（_apply_query_metadata_constraints）
  ↓
2. Lookup 意图优先（_prioritize_lookup_candidates）
  ↓
3. 元数据文档支持度（_prioritize_metadata_document_support）
  ↓
4. 定义主题亲和度（_prioritize_definition_subject_candidates）
  ↓
5. 文档多样化（_diversify_lookup_documents）
  ↓
6. 低分过滤（min_output_score=0.1）
  ↓
7. 截断（rerank_top_k=6）
  ↓
最终结果
```

每个步骤解决一个特定问题，以确保最终返回的 top K 结果是最有用的。

---

### 阶段 11：弃权判断（Guardrail / Abstain）

#### 要解决什么问题

检索系统并不总能找到好的答案。如果知识库里根本没有相关内容，硬要生成答案只会得到"幻觉"（LLM 编造的内容）。**宁可不答，也不错答。**

**具体例子**：

用户问："Kubernetes 的 Pod 调度策略是什么？"——但知识库里没有任何 K8s 相关的笔记。

检索系统会返回一些"勉强沾边"的结果（比如一篇讲 Docker 容器的笔记），但这些结果的分数很低，不应该被当作证据。

#### 用了什么技术

项目自建的多维度弃权决策系统（`app/answer/guardrail.py` + `app/services/querying.py`）。

#### 技术原理

弃权决策分四个层次，逐层评估：

```
第一层：基础分数检查（evaluate_abstain）
  ├── top1 分数 < 0.20？ → 弃权（最佳结果都不够好）
  ├── top3 平均分 < 0.30？ → 弃权（整体质量太差）
  ├── 有效命中数 < 2？ → 弃权（证据太少）
  └── 证据总字数 < 150？ → 弃权（内容太短）
      ↓
第二层：查询类型特定放宽（_relax_query_profile_guardrail）
  └── 如果是 existence 型 + 有单文档强证据 → 取消弃权
      ↓
第三层：查询词覆盖率检查（_evaluate_query_term_coverage）
  └── 关键词在证据中的覆盖率 < 60%？ → 弃权
      ↓
第四层：查询类型特定收紧（_evaluate_query_profile_guardrail）
  └── comparison 型但证据不覆盖所有比较对象 → 弃权
      ↓
最终决策：回答 or 弃权
```

**查询词覆盖率的直觉**：

```
用户问: "Raft 和 Paxos 的区别是什么？"
关键词: ["raft", "paxos", "区别"]

证据 chunk 中:
  - "raft" 出现了 ✓
  - "paxos" 没出现 ✗
  - "区别" 出现了 ✓

覆盖率 = 2/3 = 66.7% ≥ 60% → 通过
```

但如果用户问的是三个概念的比较，而证据只覆盖了其中一个，覆盖率就会低于阈值，系统会选择弃权。

**所有阈值都在 config.yaml 中可调**：

```yaml
abstain:
  top1_min: 0.20            # 最佳结果的最低分
  top3_avg_min: 0.30        # 前三名的平均最低分
  min_hits: 2               # 最少需要几个有效证据
  min_total_chars: 150      # 证据的最少总字数
  min_query_term_count: 2   # 触发覆盖率检查的最少关键词数
  min_query_term_coverage: 0.60  # 关键词覆盖率阈值
```

---

### 阶段 12：Prompt 组装

#### 要解决什么问题

通过了弃权检查后，需要把用户的问题和检索到的证据拼接成一个结构化的 prompt，交给外部 LLM（如 Claude）生成最终答案。

**关键设计决策**：本系统（kms-api）**不直接调用 LLM**，而是把 prompt 和证据源返回给调用方（如 Claude Code skill），由调用方负责调用 LLM。这让系统保持了灵活性——可以接入任何 LLM。

#### Prompt 结构

```
你是 KMS 的答案编排器。
你必须只基于下方"证据"回答用户问题。
（系统指令……）

问题：两阶段提交协议的流程是什么？

证据：

[证据 1]
ref: [1]
location: 分布式系统基础知识.md:5-20
file_path: E:\notes\分布式系统基础知识.md
title_path: 分布式系统基础知识 / 两阶段提交
score: 0.9500
text:
两阶段提交（2PC）是一种分布式事务协议……

[证据 2]
ref: [2]
location: 分布式事务.md:12-25
（……）

输出要求：
1. 只能基于证据回答。
2. 每条结论都必须带 [1]、[2] 这类数字引用。
3. 若证据不足，必须直接回复"资料不足，无法确认。"
（……）

来源列表：
[1] 分布式系统基础知识.md:5-20 | 分布式系统基础知识 / 两阶段提交
[2] 分布式事务.md:12-25 | 分布式事务 / 2PC 流程详解
```

---

### 阶段 13：引用验证（Citation Verification）

#### 要解决什么问题

LLM 生成的答案可能"看起来引用了证据，实际上在编造内容"。需要一个独立的校验机制来验证答案是否真的基于提供的证据。

#### 用了什么技术

基于 **n-gram 覆盖率**的引用验证（`app/answer/citation_check.py`）。

#### 技术原理

**n-gram** 是连续 n 个字符（或词）组成的片段。

```
文本: "两阶段提交协议"
8-gram: ["两阶段提交协议xx", ...]  （取 8 个字符的滑动窗口）
```

验证步骤：
1. 把 LLM 的答案按句子切分
2. 对每个句子提取所有 8-gram
3. 检查每个 8-gram 是否在对应的证据 chunk 原文中出现
4. 计算覆盖率 = 匹配的 8-gram 数 / 总 8-gram 数

```yaml
verify:
  min_ngram_len: 8          # n-gram 长度
  coverage_threshold: 0.5   # 覆盖率阈值
```

如果覆盖率低于 50%，说明答案的大部分内容在证据中找不到依据，标记为 `citation_unverified`。

---

## 第三部分：各技术组件与第三方库速查

| 组件 | 第三方库 | 角色 | 在项目中的位置 |
|------|---------|------|---------------|
| 中文分词 | Jieba | 把中文句子切成词，供 FTS5 索引和搜索使用 | `app/vendors/jieba_tokenizer.py` |
| 全文搜索引擎 | SQLite FTS5 | 倒排索引 + BM25 排序，支持关键词匹配检索 | `app/store/fts_store.py` |
| Embedding 模型 | FlagEmbedding（BAAI/bge-m3） | 把文本转为 1024 维语义向量 | `app/vendors/flag_embedding.py` |
| 向量数据库 | Chroma | 存储向量 + HNSW 近似最近邻搜索 | `app/vendors/chroma.py`, `app/store/vector_store.py` |
| Reranker 模型 | FlagEmbedding（BAAI/bge-reranker-v2-m3） | Cross-Encoder 精排，对查询-文档对做精细相关性打分 | `app/vendors/flag_embedding.py`, `app/retrieve/rerank.py` |
| YAML 解析 | PyYAML | 解析 config.yaml 和 Markdown front matter | `app/config.py`, `app/ingest/cleaner.py` |
| HTTP 框架 | FastAPI + Uvicorn | 提供 REST API 服务 | `app/main.py` |
| 数据校验 | Pydantic | 配置和请求/响应模型的类型校验 | `app/config.py`, `app/schemas.py` |

---

## 第四部分：一次完整的 `/ask` 请求示例

用下面这个例子串联所有阶段：

**用户请求**：

```json
{
    "question": "两阶段提交协议的流程是什么？",
    "queries": ["两阶段提交协议的流程是什么？"]
}
```

**阶段 5 — 查询理解**：

```
query_type: "definition"
route_policy: "balanced"
alias_subject_terms: ["2pc", "两阶段提交", "两阶段提交协议"]
查询变体:
  1. "两阶段提交协议的流程是什么？"（原始）
  2. "两阶段提交协议 流程"（去标点）
  3. "两阶段提交 协议 流程"（关键词）
  4. "2pc 流程"（别名替换）
```

**阶段 6 — 词法检索**（每个变体分别查询 FTS5）：

```
变体 1 → FTS5 MATCH "两 OR 阶段 OR 提交 OR 协议 OR 流程"
  → chunk_A(BM25=-8.2), chunk_C(BM25=-5.1), chunk_F(BM25=-3.8), ...

变体 4 → FTS5 MATCH "2pc OR 流程"
  → chunk_A(BM25=-9.1), chunk_D(BM25=-4.2), ...
```

**阶段 7 — 语义检索**（每个变体分别 embed + Chroma 搜索）：

```
变体 1 → embed("两阶段提交协议的流程是什么？") → [0.023, -0.156, ...]
  → Chroma top 20: chunk_B(dist=0.15), chunk_A(dist=0.18), chunk_E(dist=0.31), ...
```

**阶段 8 — RRF 融合**：

```
4 个变体 × 2 路检索 = 8 个排名列表
RRF(k=60) 合并后:
  chunk_A: 0.0653（4 个列表都出现，综合排名最高）
  chunk_B: 0.0486
  chunk_C: 0.0318
  ...
```

**阶段 9 — 重排**：

```
取 top 24 候选，用 BGE-reranker-v2-m3 精排:
  chunk_A × "两阶段提交协议的流程是什么？" → logit=6.2 → sigmoid=0.998
  chunk_A × "2pc 流程"                   → logit=5.8 → sigmoid=0.997
  chunk_A 最终分数 = max(0.998, 0.997) = 0.998

  chunk_B × ... → 0.823
  chunk_C × ... → 0.654
  ...
```

**阶段 10 — 后处理**：

```
定义型查询 → 检查主题亲和度:
  chunk_A title_path 含"两阶段提交" → affinity=3（最高）
  → chunk_A 保持第一

低分过滤: min_output_score=0.1 → 所有结果都高于阈值
截断: rerank_top_k=6 → 保留前 6 个
```

**阶段 11 — 弃权判断**：

```
top1_score = 0.998 ≥ 0.20 ✓
top3_avg = 0.825 ≥ 0.30 ✓
hit_count = 6 ≥ 2 ✓
total_chars = 3200 ≥ 150 ✓
query_term_coverage = 100% ≥ 60% ✓
→ 决策: 不弃权，生成 prompt
```

**阶段 12 — Prompt 组装**：

```
返回 AskResponse:
  abstained: false
  confidence: 0.912
  prompt: "你是 KMS 的答案编排器……\n问题：两阶段提交协议的流程是什么？\n证据：……"
  sources: [chunk_A, chunk_B, ..., chunk_F]（共 6 条）
```

调用方拿到 prompt 后送入 LLM（如 Claude），LLM 基于证据生成带引用的答案。

---

## 附录：关键算法公式速查

| 算法 | 公式 | 用途 |
|------|------|------|
| BM25 | `IDF(t) × (tf × (k1+1)) / (tf + k1 × (1-b+b×dl/avgdl))` | 词法检索排序 |
| 余弦相似度 | `cos(θ) = (A·B) / (‖A‖×‖B‖)` | 语义检索的距离度量 |
| RRF | `Σ 1/(k + rank_i)` | 多路检索结果融合 |
| Sigmoid | `1 / (1 + e^(-x))` | Cross-Encoder 分数归一化 |
| n-gram 覆盖率 | `matched_ngrams / total_ngrams` | 引用验证 |
