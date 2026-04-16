# M15 Ranking And Dedup Quality Plan

## 目标

M15 的目标不是继续加新的清洗规则，而是收口 M14 留下的“检索已命中，但排序不稳、相似文档互相抢位、重复内容放大错误排序”这类问题。

本阶段重点解决：

- 表格类 / tooling 类 case 的排序偏移
- 同主题相邻文档之间的 source-aware 排序
- 跨文档近重复对 top rank 的干扰
- 后续去重与排序演进需要的工程支撑问题

目标结果：

- 收掉 `ISSUE-M14-002`
- 提升主语料 `ranking-sensitive` 场景的 `mrr`
- 不允许通过放宽 benchmark 口径制造“假提升”
- `ai / distributed / game / notes-frontmatter / cleaning.real10` 五组质量门不回退

## 背景

M14 已经收掉了主语料里最明显的 boilerplate / `[TOC]` / footer-noise 问题，也完成了 Markdown 表格结构化与 source-specific 清洗框架。

当前残留问题已经从“脏内容进检索面”转成了“好内容已经进来，但排序仍不够聪明”：

- `cleaning10-003`
  - `GDB 常用调试命令里 backtrace 的缩写是什么？`
  - 目标文档仍为 `rank=2`
- `cleaning10-009`
  - `GDB 里哪个命令可以查看断点或线程等信息？`
  - 保守 benchmark 口径下，仍被 `2.0 常用命令详解.md` 压过

这类问题的本质不是“没召回”，而是：

- 同主题文档之间的正文强匹配压过了更匹配的表格映射文档
- 相似 chunk 与相似文档缺少合理的去重/抑制
- rerank 缺少 source-aware 和 document-support-aware 的补充信号

## 范围

本阶段只做以下内容：

- 排序偏移问题盘点与专项 benchmark 补强
- 同主题文档间的 source-aware 排序信号设计
- 跨文档近重复抑制方案
- `chunk_id` / document-support / duplicate signal 等工程支撑项
- 对应 benchmark / retrieval case diff / index stats 对照

本阶段不做：

- 新的清洗规则大扩张
- 新一轮 front matter 语义方案
- 通用 Agentic RAG 工作流
- 大规模 chunker 重写
- 为了让指标更好看去改 benchmark 口径

## 核心问题

### 问题 1：相邻文档之间的主题竞争导致排序偏移

典型表现：

- 一篇“概览/详解”文档，正文更直接，容易压过另一篇“基础表格/映射”文档
- 但用户问的其实更适合后者

这类问题不能只靠更高的 lexical score 解决，需要补：

- source-aware 信号
- document-level 支持信号
- 查询类型感知

### 问题 2：跨文档近重复会放大错误 top rank

当前 index stats 虽然已经比 M13 干净，但仍有明显重复内容：

- 重复标题
- 重复知识点摘录
- 同主题多份笔记的重复段落

这类内容本身不一定是脏数据，但如果不加控制，会让：

- 同一语义在 top-k 里重复出现
- 某个错误文档因重复块多而被放大

### 问题 3：后续去重与排序还缺少稳定工程支撑

M13 时已经暴露过一个工程风险：

- `build_chunk_id()` 不含 `section_index`

如果 M15 要引入更积极的文档级支持度或近重复抑制，这类底层标识问题要先收口，否则：

- 难以稳定做重复聚类
- 难以解释排序行为
- 容易把真实不同 chunk 误当成同一项

## 设计原则

### 1. 先做排序诊断，再做排序修复

M15 不允许直接“拍脑袋加 boost”。

每个排序修复前，至少要先回答：

- 问题发生在 lexical、semantic、fused 还是 rerank
- 目标文档是否已经在 top-k 中
- 是单 chunk 误排，还是整篇文档支持度不够

### 2. 修复尽量窄，不做全局放松

优先做：

- query type 识别后的窄场景排序补丁
- metadata / path / table-aware 的局部信号
- document-support-aware 的保守重排

避免做：

- 全局加大某类权重
- 全局降低阈值
- 让更多“解释性强但来源不对”的文档上位

### 3. benchmark 口径不能跟着功能跑

M15 延续 M14 的纪律：

- benchmark 默认不可改
- 若 case 本身有问题，必须单独立项维护
- benchmark 修订不计入功能收益

### 4. 先单点收口，再整组放行

执行顺序必须是：

1. 单 case 最小复现
2. retrieval case diff
3. 对应 benchmark 子集
4. 全组 benchmark
5. 全量测试

## 实施阶段

### Stage 0：排序与重复模式盘点

目标：

- 把当前剩余问题从“现象”拆成可执行分型

输出：

- 至少 10 条 `ranking / duplicate` 专项 benchmark case
- 至少 10 份 retrieval case diff
- 至少 10 个高风险样本文档/文档对

建议覆盖：

- 同主题概览 vs 详解
- 表格映射文档 vs 正文解释文档
- 同知识点跨 source 重复摘录
- 同文档多 chunk 支持 vs 单条概念 chunk 抢位

建议新增：

- `eval/benchmark.ranking.real10.jsonl`

放行标准：

- 每类排序问题至少有 2 个稳定复现 case
- 每个 case 都能明确掉点发生层级

### Stage 1：Source-Aware 排序

目标：

- 让“更适合回答该问题的文档类型”在同主题竞争中更稳定地胜出

建议方向：

- 基于 `relative_path / title_path / document metadata` 做轻量 source-aware 信号
- 识别 `表格查值 / 命令映射 / 缩写解释` 这类 query 类型
- 对“映射型”问题优先更结构化、更聚焦的文档

代码落点建议：

- `app/retrieve/hybrid.py`
- `app/services/querying.py`
- 必要时新增独立排序辅助模块

放行标准：

- `cleaning10-003`、`cleaning10-009` 至少收口 1 个
- 不得拉坏 `real10` 其它题型

### Stage 2：跨文档近重复抑制

目标：

- 降低近重复 chunk 对 top-k 和 rerank 的污染

建议策略：

- 先做低风险：
  - exact / near-exact 文档级聚类标记
  - top-k 内相似候选去重
- 再做中风险：
  - rerank 后的 diversity / document de-dup

实现建议：

- 先不引入重型方案
- 优先用规范化文本 hash、轻量相似度、已有 metadata 做聚类
- 如果不够，再考虑 `simhash` 类方案

放行标准：

- 排名前列的重复文档/重复 chunk 数量下降
- 不得导致 evidence hit 回退

### Stage 3：工程支撑与标识修复

目标：

- 给后续排序与去重提供稳定基础

候选项：

- `chunk_id` 生成策略修正，补上 `section_index`
- 文档级支持度统计的统一结构
- retrieval debug 输出增强
- duplicate cluster 标记与 explainability 字段

放行标准：

- 标识稳定
- 回归可覆盖
- 不引入历史索引兼容性失控

## Benchmark 补强

M15 建议新增一套排序专项 benchmark：

- `eval/benchmark.ranking.real10.jsonl`

至少覆盖：

- 表格映射问题被详解文档压过
- 缩写 / 命令速查类问题排序偏移
- 相似文档重复上榜
- 同文档多 chunk 支持输给单 chunk 概念总结
- 跨 source 重复摘录导致的 top rank 偏移

同时保留现有质量门：

- `eval/benchmark.ai.real10.jsonl`
- `eval/benchmark.distributed.real10.jsonl`
- `eval/benchmark.game.real10.jsonl`
- `eval/benchmark.notes-frontmatter.real10.jsonl`
- `eval/benchmark.cleaning.real10.jsonl`

## 对比产物

每轮至少产出：

- `benchmark.ranking.real10` 结果
- `benchmark.cleaning.real10` 对比
- 至少 10 条 retrieval case diff
- index stats 快照
- 重复候选统计
- 样本文档/样本 query 的 before/after 排序对照

建议命名：

- `eval/results/benchmark.ranking.real10.m15.<stage>.json`
- `eval/results/index-stats/m15.<stage>.json`

## 质量门

以下指标不允许回退：

- `recall_at_k`
- `mrr`
- `abstain_accuracy`
- `false_abstain_rate`
- `false_answer_rate`

额外目标：

- `benchmark.ranking.real10` 要有可量化收益
- `benchmark.cleaning.real10` 的 `table / tooling` 子集要优于 M14

## 风险点

### 风险 1：为了解决个别 case，把全局排序搞歪

应对：

- 只做窄场景排序补丁
- 每轮都复跑五组质量门

### 风险 2：近重复抑制误伤有效证据

应对：

- 先做 top-k 去重，不直接删索引内容
- 优先“降权/去重展示”，而不是“全局删除”

### 风险 3：底层标识变更影响历史索引

应对：

- 先做显式迁移判断
- 必要时通过 schema/version 触发重建

## 建议执行顺序

1. Stage 0：盘点排序与重复问题，并补专项 benchmark
2. Stage 1：先做 source-aware 排序，收口 `ISSUE-M14-002`
3. Stage 2：做近重复抑制
4. Stage 3：补工程支撑与标识修复

## 本阶段完成标准

- `ISSUE-M14-002` 已收口或被拆成更小且有明确证据的残留
- `benchmark.ranking.real10` 已建立
- `benchmark.cleaning.real10` 的 `table / tooling` 子集有可量化提升
- `ai / distributed / game / notes-frontmatter / cleaning` 五组质量门不回退
- 台账、diff、验证命令完整记录
