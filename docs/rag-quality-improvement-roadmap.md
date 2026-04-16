# RAG 质量提升总结与 `mykms` 落地清单

本文基于 [dev-plan/如何高效提升RAG知识库的质量？.txt](/E:/github/mykms/dev-plan/如何高效提升RAG知识库的质量？.txt) 提炼，并结合 `mykms` 当前实现现状整理为可执行版本。

相关现状文档：

- `/ask` 与索引链路：[docs/ask-and-ingest.md](/E:/github/mykms/docs/ask-and-ingest.md)
- 评测方法：[docs/rag-evaluation-methodology.md](/E:/github/mykms/docs/rag-evaluation-methodology.md)
- 最终架构方案：[dev-plan/kms_final_plan.md](/E:/github/mykms/dev-plan/kms_final_plan.md)

## 核心判断

原文最重要的观点只有一句话：

`RAG` 质量差，大多数时候不是模型和向量库不行，而是检索前半段做得不够好，尤其是数据清洗、分段、召回和评测。

对 `mykms` 来说，这个判断基本成立。当前仓库已经具备：

- Markdown 扫描、标题分段与 chunk 化
- `SQLite FTS5 + Chroma` 混合检索
- `RRF + rerank`
- `/ask` 拒答与 `/verify` 引用校验
- 分层 benchmark 与 hard-case 模板

这说明 `mykms` 的主链路已经不是“缺少 RAG 基础设施”，而是进入了“继续打磨质量细节”的阶段。

## 原文要点总结

原文可以压缩成 8 条工程建议：

1. 先区分问题是在检索端还是生成端，不要一上来盲调参数。
2. 分段优先按语义和文档结构，不要机械按固定 token 长度切。
3. 每个 chunk 不只要文本，还要有来源、层级、摘要等元数据。
4. embedding 模型选型要做小规模评测，中文和垂直领域不要直接用默认模型。
5. 不能只做向量检索，必须加关键词检索，形成 hybrid retrieval。
6. 检索后加 rerank，通常是高性价比优化。
7. 用户提问太模糊时，需要 query 改写、多 query 或 HyDE 这类补救手段。
8. 没有评测体系就没有优化闭环，最终还应考虑更智能的 Agentic RAG。

如果只看优先级，原文推荐顺序是：

1. 清洗数据
2. 更换或校准 embedding 模型
3. 加混合检索
4. 优化 chunk 策略
5. 加 rerank
6. 做 query 改写
7. 建评测体系
8. 进阶到 Supervisor Agent / Agentic RAG

## `mykms` 当前状态判断

从仓库现状看，`mykms` 已经完成了原文优先级里的中段能力：

- 已有混合检索，不是纯向量检索
- 已有 rerank，不是只做粗召回
- 已有 benchmark，不是完全靠主观感觉
- 已有标题层级切分，不是纯 token 固定切块
- 已有 query 扩展，不是完全裸问句直查

当前更值得投入的，不是重复造这些已有能力，而是补下面几类缺口。

### 1. 数据清洗仍偏轻量

按 [docs/ask-and-ingest.md](/E:/github/mykms/docs/ask-and-ingest.md) 当前说明，索引前还没有专门处理这些内容：

- YAML front matter 抽取
- Markdown 表格结构化
- 图片与链接语义提取
- HTML 块专门清洗
- 重复段落去重
- 模板噪音、页眉页脚类噪音清理

这意味着 `mykms` 现在更接近“保留原文并做结构切分”，还没有进入“面向检索质量的数据整备”阶段。

### 2. 元数据已有基础，但还不够服务检索决策

当前 chunk 元数据主要包含：

- `file_path`
- `title_path`
- `chunk_index`
- 行号
- `chunker_version`
- `embedding_model`

这已经足够做基本来源展示，但还不足以支撑更精确的过滤和排序。比如：

- 文档标签
- 年份或日期
- 文档类型
- 来源目录
- front matter 字段
- chunk 级摘要或关键词

这些字段缺失时，检索只能主要依赖文本相似度，无法更主动地缩小搜索空间。

### 3. 评测框架已具备，但真实基准集还应继续扩

当前 `eval/` 已能覆盖：

- 检索命中与排序
- 拒答质量
- 证据覆盖
- 按题型与标签分组

但如果要真正指导后续优化，仍然需要更多来自真实知识源的 benchmark，尤其是：

- 口语化改写题
- 多文档联合题
- 半相关误导题
- 应拒答但容易误答的题
- 带精确标识符的题，例如文件名、API 名、错误码、术语名

### 4. Query 改写已有基础，但还不算“策略化”

`mykms` 当前会自动扩展 query 变体，这已经比单 query 强很多。

但它还主要是规则型扩展，距离“基于问题类型动态选择 exact match、multi-query、HyDE、metadata filter”的策略式检索还有一段距离。

## `mykms` 落地行动清单

下面按投入产出比排序，优先做最值得做的事。

## P0：先补高 ROI 缺口

### 1. 做一轮真正面向检索的数据清洗

目标：减少噪音 chunk 与伪相关召回。

建议落点：

- `app/ingest/loader.py`
- `app/ingest/markdown_parser.py`
- `app/ingest/chunker.py`

建议动作：

- 抽取 YAML front matter 到结构化 metadata，不再把它整块混入正文。
- 对 Markdown 表格增加“结构转文本”步骤，至少保留表头与行内容的可检索表达。
- 清理明显的模板噪音，例如固定免责声明、导航文本、重复页脚。
- 对完全重复或高度重复 chunk 做去重或降权。
- 为 source root 增加可选预处理规则，避免不同目录内容一刀切。

验收标准：

- `eval` 中 `distractor` 与 `rewrite` 类题型的 `MRR`、`evidence_hit_rate` 有提升。
- 索引后 chunk 总量不上升太多，但低价值噪音片段明显减少。

### 2. 把 benchmark 扩成“能指导优化”的真实数据集

目标：让每次改动都能看到明确收益或回退。

建议落点：

- `eval/benchmark.*.jsonl`
- `eval/README.md`
- `tests/test_eval_benchmark.py`

建议动作：

- 每个主要知识源目录至少补一组 benchmark。
- 明确覆盖 `lookup`、`rewrite`、`multi_doc`、`distractor`、`abstain`。
- 单独增加“精确标识符类题目”标签，例如 `identifier`、`api-name`、`filename`、`error-code`。
- 把当前真实误答 case 反灌成 regression benchmark，而不是只保留样例题。

验收标准：

- 新增 benchmark 后，`by_type` 与 `by_tag` 能清晰暴露短板。
- 后续每次改 chunk、检索、阈值时都能跑同一组对照。

### 3. 针对精确标识符做检索增强

目标：补齐 hybrid retrieval 对“精确字符串命中”的优势。

建议落点：

- `app/services/querying.py`
- `app/retrieve/lexical.py`
- `app/retrieve/hybrid.py`

建议动作：

- 增加 query 意图识别，区分自然语言问句和精确标识符问句。
- 对文件名、函数名、API 名、错误码、版本号、英文缩写启用更强的 lexical boost。
- 对疑似精确匹配 query 降低语义扩写权重，避免“相关但不准确”的噪音结果冲到前面。

验收标准：

- `identifier` 标签题目的 `recall_at_k` 和 `MRR` 明显提升。
- 精确查找类问题的误召回数量下降。

## P1：把已有主链路打磨得更稳

### 4. 升级 chunk 元数据，支持更主动的过滤与排序

目标：让检索不仅靠正文相似度。

建议落点：

- `app/ingest/contracts.py`
- `app/store/sqlite_store.py`
- `app/store/fts_store.py`
- `app/store/vector_store.py`

建议动作：

- 存储 front matter 中可检索字段，例如 `tags`、`date`、`aliases`、`category`。
- 为 chunk 生成短摘要或关键词串，作为辅助检索字段。
- 把 `source_id`、相对路径、文档类型暴露到检索排序与调试输出。
- 在 `/search` 或内部检索层预留 metadata filter 能力。

验收标准：

- 同主题多文档场景下，来源筛选更稳定。
- `multi_doc` 与 `rewrite` 类题型的证据覆盖率提升。

### 5. 升级 chunker 到更明确的“结构优先”版本

目标：减少答案被切碎，减少表格和列表信息丢失。

建议落点：

- `app/ingest/chunker.py`
- `tests/test_indexing_service.py`

建议动作：

- 对标题很短但正文很长的 section 增强二级切分策略。
- 对列表、表格、代码块尽量整块保留，不和相邻段落混切。
- 对过短 chunk 做合并，对过长 chunk 做更稳的语义边界拆分。
- 用 `chunker.version` 驱动可回滚的全量重建。

验收标准：

- `expected_term_coverage` 提升。
- 检索命中后返回的证据更完整，减少“只命中半截答案”。

### 6. 把 query 改写从“默认扩展”升级为“条件触发”

目标：减少无效改写带来的噪音召回。

建议落点：

- `app/services/querying.py`
- `config.yaml`

建议动作：

- 对短问句、口语化问句、低覆盖问句才触发更强扩展。
- 对精确标识符类 query 关闭激进改写。
- 预留 `multi_query`、`hyde` 这类策略开关，但先通过 benchmark 验证再默认开启。

验收标准：

- `rewrite` 题提升，同时 `lookup` 和 `identifier` 不被拖累。

## P2：做进阶能力，而不是过早重构

### 7. 用 benchmark 反推拒答阈值，而不是静态拍脑袋

目标：让 `abstain` 更像工程调参结果，而不是固定经验值。

建议落点：

- `config.yaml`
- `eval/`
- `app/answer/guardrail.py`

建议动作：

- 针对不同 benchmark 切片观察 `false_answer_rate` 与 `false_abstain_rate`。
- 以误答风险优先，逐步调 `top1_min`、`top3_avg_min`、`min_hits`、`min_total_chars`。
- 必要时把“query term coverage”分场景调节，而不是一刀切。

验收标准：

- `false_answer_rate` 优先下降。
- 不出现明显的整体误拒激增。

### 8. 追加答案级评测，而不是只停在证据包层

目标：补齐“检索对了，但宿主最终回答未必对”的观测盲区。

建议落点：

- `eval/`
- 宿主适配层脚本或离线评测脚本

建议动作：

- 基于 `/ask.prompt + /ask.sources` 生成宿主最终答案样本。
- 增加人工或半自动评审：
  - 事实是否正确
  - 是否遗漏关键条件
  - 引用是否真正支撑结论
- 先做小规模人工集，不急着接自动裁判模型。

### 9. 最后再考虑 Agentic RAG

目标：在多轮对话或复杂任务场景下，提升检索规划能力。

对 `mykms` 的判断是：

- 当前仓库还没到必须引入 Supervisor Agent 的阶段。
- 在数据清洗、元数据增强、benchmark 扩充、标识符检索优化做完前，直接上 Agentic RAG 的收益未必最高。

更合理的顺序是先把静态检索链路打磨到稳定，再评估是否需要：

- 检索规划 agent
- 会话摘要
- 多阶段证据收集
- 多轮任务型工作流

## 建议的实施顺序

如果只给 `mykms` 安排接下来 3 个迭代，建议顺序如下：

1. 先做数据清洗 + benchmark 扩题。
2. 再做标识符检索增强 + 元数据增强。
3. 最后做 chunker v2、拒答阈值回调和答案级评测。

原因很简单：

- 第一轮先把“垃圾进垃圾出”问题压住。
- 第二轮解决真实使用里最常见的精确匹配和过滤问题。
- 第三轮再收敛排序、拒答和最终回答质量。

## 一句话结论

对 `mykms` 来说，下一阶段最重要的不是“再加一个更花哨的 RAG 技术名词”，而是把已有混合检索链路继续工程化：先清洗数据、补评测集、加强标识符检索和元数据，再考虑更重的 Agentic RAG 设计。
