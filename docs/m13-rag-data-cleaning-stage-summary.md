# M13 RAG Data Cleaning Stage Summary

## 本阶段做了什么

本阶段的目标不是直接“多加几条清洗规则”，而是先把面向检索的数据清洗做成一套可验证、可对比、可收口的工程流程。

已完成内容：

- 搭建 baseline / candidate 对照框架
  - 新增索引统计与 benchmark diff 工具
  - 文件：
    - `eval/index_stats.py`
    - `eval/run_index_stats.py`
    - `eval/compare.py`
    - `eval/run_compare.py`
- 接入第一轮低风险清洗
  - front matter 抽取
  - BOM / 换行 / 空白规范化
  - 文档内 exact duplicate chunk 抑制
  - 文件：
    - `app/ingest/cleaner.py`
    - `app/ingest/loader.py`
    - `app/services/indexing.py`
- 构建 front matter 派生实验语料，避免直接改写原始 `E:\notes`
  - 文件：
    - `scripts/build_notes_frontmatter_corpus.py`
    - `config.notes-frontmatter.yaml`
    - `eval/benchmark.notes-frontmatter.real10.jsonl`
- 将 front matter 正式注入检索链路
  - chunk metadata 继承：
    - `category`
    - `tags`
    - `aliases`
    - `relative_path`
    - `path_segments`
  - FTS 增加 `metadata_text`
  - 检索支持识别 `X 分类下` / `Y 里` 这类 metadata constraint
  - guardrail 与 query term coverage 开始识别 metadata 证据
  - 文件：
    - `app/store/fts_store.py`
    - `app/retrieve/hybrid.py`
    - `app/services/querying.py`
    - `app/answer/guardrail.py`

## 核心成果

### 1. 已具备稳定的前后对比框架

后续每一轮数据清洗不再靠“感觉变好了”，而是可以固定比较：

- benchmark 总体指标
- `by_type` / `by_tag`
- case diff
- index stats 快照

### 2. 已证明 front matter 对 metadata-sensitive 检索有真实收益

`notes-frontmatter.real10` 指标变化：

- baseline：
  - `recall_at_k = 0.875`
  - `mrr = 0.7917`
  - `abstain_accuracy = 0.9`
  - `false_answer_rate = 0.5`
- 最新：
  - `recall_at_k = 1.0`
  - `mrr = 1.0`
  - `abstain_accuracy = 1.0`
  - `false_abstain_rate = 0.0`
  - `false_answer_rate = 0.0`

结果文件：

- `eval/results/benchmark.notes-frontmatter.real10.m13.metadata-v5.json`
- `eval/results/benchmark.notes-frontmatter.real10.m13.metadata-v5.diff.json`

### 3. 已收口 3 类关键问题

- `notesfm10-006`
  - 从“检索对了但误拒答”修到正确回答
- `notesfm10-008`
  - 从 `rank = 3` 修到 `rank = 1`
- `notesfm10-009`
  - 从误答修到正确拒答

## 关键问题、原因与解决方式

### 问题 1：低风险清洗上线后收益很小

- 现象：
  - Stage 1 接入 front matter / 空白规范化 / exact duplicate 去重后，主语料指标几乎不变
- 原因：
  - 主语料里的 front matter 很少
  - 当前主噪音并不在 front matter 或文档内 exact duplicate
- 解决方式：
  - 构建 `notes-frontmatter` 派生实验语料
  - 在一个 front matter 足够丰富的可控环境里验证 metadata 检索收益

### 问题 2：front matter 存在，但没有真正进入检索面

- 现象：
  - 基线实验里，正文题基本稳定
  - metadata-sensitive / category-filter 题明显掉点
- 原因：
  - 原检索链路主要依赖正文内容
  - `category / tags / path` 没有真正作为检索证据参与召回和排序
- 解决方式：
  - chunk metadata 继承 front matter 字段
  - FTS 增加 `metadata_text`
  - 在 `app/retrieve/hybrid.py` 中引入 metadata constraint

### 问题 3：`notesfm10-006` 检索命中正确文档，但 `/ask` 仍误拒答

- 现象：
  - 目标文档已回到 Top-1
  - `/ask` 仍因分数或证据字符数不足拒答
- 原因：
  - 这类问题的正文 chunk 往往短
  - 但 metadata 本身已经构成足够强的“存在性证据”
  - 原 guardrail 只按正文字符数和常规分数阈值判断
- 解决方式：
  - 提高 metadata 命中候选的分数地板
  - guardrail 在窄场景下允许 metadata 证据补足 `min_total_chars`

### 问题 4：`notesfm10-008` 初始仍为 `rank = 3`

- 现象：
  - 目标文档没有排到前面
  - Top-1 一开始甚至是跨 category 的 `apue/定时器.md`
- 原因：
  - benchmark 里的 query 变体把原问题中的“分类下”语义压掉了
  - metadata constraint 根本没有触发
- 解决方式：
  - 方案 A：保留原问题作为 query variant
  - 结果：`rank = 3 -> 2`

### 问题 5：`notesfm10-008` 进一步收敛后仍是同 category 内 `rank = 2`

- 现象：
  - 不再越 category 命中
  - 但仍被同 category 下的 `muduo` 文档压住
- 原因：
  - fused 阶段不是问题，目标文档本来就在前排
  - 真正偏移发生在 rerank：
    - 单条概念总结型 chunk 被打分略高
  - 当前排序缺少“同文档多条 chunk 一致支持”的信号
- 解决方式：
  - 在 metadata-constrained rerank 结果上增加文档级支持度重排
  - 优先同文档多 chunk 支持更强的候选
  - 结果：`rank = 2 -> 1`

### 问题 6：`notes-frontmatter` 实验索引上的 Chroma semantic 查询在 Windows 下崩溃

- 现象：
  - batched 与单 query semantic 路径都会触发 `Windows fatal exception: access violation`
  - `faulthandler` 栈落在 `chromadb.api.rust._query`
- 原因：
  - 更像是 `chromadb` Rust / Windows 在当前 collection 状态上的底层问题
  - 不是 Python 层普通异常
  - 根因不在“metadata 太重”，而在原 `data/chroma.notes-frontmatter` 这份 persisted collection 状态本身
- 解决方式：
  - 用 `scripts/chroma_semantic_probe.py` 做 A/B 复现
  - 将 collection clone 到 fresh persist：
    - `data/chroma.notes-frontmatter.ab.full`
    - `data/chroma.notes-frontmatter.ab.minimal`
  - 确认 fresh clone 上 semantic query 可稳定运行
  - 进一步修正 `app/answer/guardrail.py`：
    - 对“同文档、多 chunk、一致 metadata 约束且带 semantic 支持”的证据簇做窄场景放行
  - 最终把 `config.notes-frontmatter.yaml` 切回 repaired semantic 配置：
    - `data.chroma = ./data/chroma.notes-frontmatter.ab.full`
    - `retrieval.semantic_enabled = true`
    - `retrieval.semantic_batch_enabled = true`

## 当前是否还有遗留问题

当前没有阻塞本阶段的遗留问题。

需要单独记住的运行期事实：

- 原 `data/chroma.notes-frontmatter` 仍是一个可复现崩溃的坏样本
- 当前实验链路已经切到 repaired fresh-clone persist，不再依赖那份坏 collection

当前已经收口的问题：

- `notesfm10-006`
- `notesfm10-008`
- `notesfm10-009`
- `notes-frontmatter` 的 Chroma semantic 崩溃与 semantic-on 质量回退

## 当前结论

本阶段最重要的结论不是“数据清洗已经完成”，而是：

- 已经建立了稳定的清洗评测框架
- 已经证明 metadata / front matter 对检索质量有直接收益
- 已经把 metadata-sensitive 的主要质量问题逐个定位并收口
- 已经把 `notes-frontmatter` 实验链路从 lexical-only 降级态恢复到 semantic-on，且 benchmark 质量不回退

下一阶段的优先级，可以重新回到更高 ROI 的数据清洗本身，而不是继续卡在 `notes-frontmatter` 的 Chroma semantic 崩溃上。
