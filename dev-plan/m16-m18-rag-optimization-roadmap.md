# M16-M18 RAG Optimization Roadmap

## 目标

这份路线图用于回答一个问题：

在 M15 解决排序偏移与近重复之后，`mykms` 后面还值得继续优化什么，先做什么，做到什么程度才算真正有价值。

整体判断是：

- M14 解决了“脏内容进检索面”
- M15 解决“命中了但排不对”
- M16-M18 要继续拉开的，是：
  - query 理解能力
  - 拒答与证据判定精细化
  - 评测与数据工程体系化

## 总体顺序

建议顺序：

1. M16：Query Understanding And Retrieval Strategy
2. M17：Answer Guardrail And Evidence Quality
3. M18：Evaluation And Data Engineering System

原因：

- 若 query 理解还弱，后面的 guardrail 和评测优化会一直被“问法噪音”干扰
- 若 guardrail 还粗糙，检索提升也会被误拒答或误答吃掉
- 若评测和数据工程体系不成型，后续优化无法稳定累积

## M16：Query Understanding And Retrieval Strategy

### 目标

解决“知识库里有，但用户问法不稳定，导致召回或排序不稳”的问题。

重点提升：

- query 改写
- 术语归一
- 问题类型识别
- 按题型切换检索策略

### 适合解决的问题

- 用户用别名、缩写、口语化表达提问
- 命令速查类问题与概念问答类问题混走同一条检索策略
- 明明有答案，但 query 太短、太泛、太歧义

### 范围

建议包含：

- query 类型识别
  - definition
  - existence
  - comparison
  - command lookup
  - table lookup
- query rewrite / expansion
- alias / abbreviation / command name normalization
- retrieval policy routing
  - 不同题型走不同 lexical / semantic / rerank 配比

不建议在 M16 做：

- 大规模改 prompt
- 新一轮清洗体系
- 复杂 agent workflow

### 目标结果

- “问法不好但知识库里有”的 case 明显下降
- `ranking-sensitive` 与 `tooling` 类题型更稳
- `avg_search_latency_ms` 不明显恶化

### 质量门

- `ai / distributed / game / notes-frontmatter / cleaning / ranking`
  六组 benchmark 不回退
- query rewrite 带来的收益要能按题型分组看见

## M17：Answer Guardrail And Evidence Quality

### 目标

解决“能答的不该拒，不能答的不该编，答的时候证据要更一致”。

重点提升：

- 分题型 guardrail
- 证据一致性
- 来源覆盖与证据完整性
- answer-level 风险控制

### 适合解决的问题

- existence question 被误拒答
- comparison question 只拿到单边证据却强答
- 多来源冲突时，系统没意识到自己证据不一致
- 命中 source 了，但 answer 组织方式不稳定

### 范围

建议包含：

- 分题型 guardrail
  - existence
  - definition
  - comparison
  - procedural / command
- evidence consistency check
- source diversity / source agreement signal
- abstain reason 细化与可解释化

不建议在 M17 做：

- 新 embedding / reranker 大换血
- 新的存储系统迁移

### 目标结果

- `false_abstain_rate` 降低
- `false_answer_rate` 降低
- answer 的来源一致性更强
- abstain 的可解释性更好

### 质量门

- `abstain_accuracy`
- `false_abstain_rate`
- `false_answer_rate`
- `evidence_hit_rate`
- `evidence_source_recall`

这些指标必须作为主门，而不是只看 `recall_at_k`

## M18：Evaluation And Data Engineering System

### 目标

把前面阶段的收益，从“单轮优化”升级成“可以长期积累的工程体系”。

重点提升：

- benchmark 扩题
- 真实失败 case 回流
- source onboarding 规范
- 数据质量审计
- 索引演进治理

### 适合解决的问题

- 每轮都靠手工记失败 case
- 新增知识源时没有质量门
- 数据越来越多，但没人知道哪一类 source 在持续拖累检索
- 索引 schema / cleaning / ranking 规则演进后，缺少迁移治理

### 范围

建议包含：

- benchmark 体系分层
  - lookup
  - abstain
  - ranking
  - metadata-sensitive
  - tooling / table
- 失败 case 自动沉淀流程
- source onboarding checklist
- 数据污染审计与质量报表
- index schema / rebuild / migration 规则

不建议在 M18 做：

- 再去卷单个 hard case 的局部补丁

### 目标结果

- 后续优化能持续累积，而不是每次都重新找问题
- 新 source 接入成本更可控
- benchmark 与真实问题之间的闭环更完整

### 质量门

- benchmark 覆盖更全
- 失败 case 能自动回流
- 数据变更有审计
- 索引演进有明确版本策略

## 各阶段关系

M16、M17、M18 不是三个孤立主题，而是逐层推进：

- M16 解决“用户怎么问”
- M17 解决“系统怎么判能不能答”
- M18 解决“后续怎么稳定持续优化”

如果跳过 M16 直接做 M17，会出现：

- guardrail 一直在为糟糕 query 擦屁股

如果跳过 M17 直接做 M18，会出现：

- 评测越来越多，但误答和误拒答的真实机制没收口

## 完成标准

当 M16-M18 全部完成后，理想状态应是：

- 检索质量不再主要受用户问法波动影响
- 拒答与作答边界更稳定
- benchmark 与真实失败 case 能持续闭环
- 新知识源接入时有明确质量与演进规范

## 当前建议

当前不建议直接立项 M16。

更合理的顺序是：

1. 先完成 M15
2. 再根据 M15 的残留问题，决定 M16 是更偏 query rewrite，还是更偏 retrieval policy routing

也就是说，这份路线图先作为后续规划，不抢 M15 当前优先级。
