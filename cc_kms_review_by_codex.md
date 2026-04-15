# `dev-plan/cc_kms.md` 评审结果

## 结论

方案主线是成立的：`Markdown -> 分块 -> 向量召回 -> rerank -> 受限回答` 这条链路足够小，也适合单人逐步落地。  
但当前文档里有几处会直接影响实施正确性或导致后续返工的问题，建议先修正再进入 M1。

## 主要问题

### 1. Skill 运行环境假设不一致，落地对象不明确

文档一方面写的是“给 Claude Code 用”，另一方面本次评审和当前工作环境实际是 Codex，且目录约定写成了 `~/.claude/skills/kms/`。这不是文案问题，而是实施边界问题：

- 如果目标真的是 Claude Code，那么当前仓库只需要实现本地服务，Skill 目录与触发方式应按 Claude Code 生态验证。
- 如果目标是当前环境里的 Codex，那么这套 `~/.claude/skills/`、`/kms`、`agents/*.md` 的方案不能直接照搬。

这部分如果不先定死，M3 很容易整段返工。

建议：

- 在文档开头明确“目标宿主”是 Claude Code 还是 Codex，只保留一套集成方案。
- 如果后端希望对多宿主复用，建议把“检索服务”和“宿主适配层”分开写，后端不绑定某个 Skill 目录约定。

### 2. `/search` 的调用设计前后矛盾

“总体架构”里写的是：

- Claude 扩展 3 个问题
- `curl :8765/search × 4`
- 客户端合并去重 chunks

但“检索管线”和“Skill 流程”里又写成：

- 一次 POST `/search`
- body 里直接传 `queries: [原问题, 改写1, 改写2, 改写3]`
- 服务端合并去重并 rerank

这两种模式在职责划分、网络开销、去重位置、可观测性上都不同，不能同时成立。

建议：

- 固定为“单次 `/search`，服务端接收多 query 并完成 merge + rerank”。
- Skill 端只负责 query expansion，不负责检索结果拼接。
- API 文档里明确输入输出，例如：
  - 输入：`queries`, `recall_top_k`, `rerank_top_k`
  - 输出：`results`, `debug.queries`, `debug.recall_count`

### 3. “严格基于资料回答”目前只靠 prompt，不足以保证

方案里把约束主要放在回答 prompt 上，但这只能降低幻觉概率，不能构成可靠约束。尤其是用户问法接近常识题时，模型仍可能补全未检索到的信息。

建议：

- 在服务端返回结果里提供稳定引用标识，例如 `chunk_id`, `path`, `heading_path`, `score`。
- 回答阶段要求“每个结论必须带引用”，引用不到就拒答。
- 增加最小证据门槛，例如：
  - rerank top1 分数低于阈值则直接判定资料不足
  - topN 结果都来自弱相关 chunk 时触发拒答
- 对“资料不足”定义成明确可测试行为，而不是仅写一句 prompt。

### 4. Windows 本地模型运行风险被低估

文档把 Windows 原生支持主要归因于 Chroma，但真正更脆弱的是模型侧：

- `FlagEmbedding` / `torch` / 本地 reranker 在 Windows 上的安装和首轮加载比 Chroma 更容易出问题
- GPU、CPU、fp16、模型下载路径、HF cache、首次启动时长都还没收口
- `bge-m3` + reranker 同机常驻，对内存和冷启动都会有明显影响

这不是实现细节，直接影响 M2 是否能按计划推进。

建议：

- 在方案里补一节“运行前提”：
  - Python 版本
  - 是否要求 CUDA
  - CPU-only 是否作为正式支持路径
  - 模型下载目录和缓存目录
- 明确版本钉死策略，至少锁定：
  - `torch`
  - `FlagEmbedding`
  - `chromadb`
  - `langchain-text-splitters`
- 在 M1/M2 之间增加一个“环境验收”检查点，先验证模型能在目标机稳定加载，再继续做集成。

### 5. 索引一致性设计还不够闭环

当前增量索引只描述了 `path + mtime + sha1` 和“按 path 删除旧 chunks”，但几个关键点没写清楚：

- chunk 的稳定 id 如何生成
- 文件重命名是否视为 delete + add
- 分块策略变化后如何触发全量重建
- Chroma collection schema 或 embedding 维度变更后如何迁移

这些问题如果实现时临时决定，后续很容易留下脏数据。

建议：

- 明确 chunk id 规则，例如：`sha1(path + heading_path + chunk_index + content_sha1)`。
- 在 `meta.db` 或 collection metadata 里记录：
  - `embedding_model`
  - `embedding_dim`
  - `chunk_strategy_version`
  - `reranker_model`
- 任一关键版本变化时，强制 full reindex，而不是尝试增量兼容。

## 次要问题

### 6. `curl` 作为 Skill 固定调用方式，对 Windows 不够稳

文档里多处直接写 Bash `curl`。如果目标环境长期在 Windows，本地命令兼容性和 shell 差异需要更保守。

建议：

- 如果宿主支持 HTTP 工具调用，优先走宿主原生能力。
- 否则至少把 Windows 和 Unix 的调用方式分开写清楚，不要默认 Bash。

### 7. 验证指标偏弱，容易“能跑但不好用”

当前 benchmark 主要看 file-level recall@5，这对真实问答质量不够。

建议：

- 除了“命中文件”，再加一层“命中正确 chunk/标题”的指标。
- 增加 5 到 10 条负样本问题，验证拒答是否稳定。
- 记录平均检索耗时和冷启动耗时，否则后续很难判断体验是否可接受。

## 建议调整后的实施顺序

建议把里程碑改成下面这样：

1. 先确定宿主环境和集成方式，只保留一套 Skill/命令约定。
2. 先做 M0：环境验收，验证 Windows 目标机上模型可安装、可加载、可跑一次真实 embedding/rerank。
3. 再做 M1：分块、元数据、全量索引，先不用增量。
4. 然后做 M2：检索 API，固定为“服务端多 query merge + rerank”。
5. 再做 M3：增量索引与版本化重建策略。
6. 最后做 M4：宿主 Skill 集成、拒答约束、管理命令和错误处理。

这样可以把最大的不确定性提前暴露，避免先把外围流程写完，最后卡在模型或集成层。

## 总评

这是一个方向正确、规模合适的个人 KMS 方案，后端技术栈也基本合理。  
当前最需要修正的不是模型选型，而是三件事：

- 先明确宿主到底是 Claude Code 还是 Codex
- 统一 `/search` 的职责边界
- 把“严格基于资料”从 prompt 口号改成可验证的机制

这三点收紧后，方案就能进入实现阶段。
