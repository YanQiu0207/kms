# M14 RAG Cleaning Stage 2 Plan

## 目标

把 M13 的“front matter 注入与实验链路修复”推进到主语料上的真实清洗收益。

本阶段不再把重点放在 semantic 稳定性，而是聚焦三类更高 ROI 的检索污染源：

- boilerplate / 导航 / 转载署名 / 固定模板噪音
- 表格信息丢失或被错误切块
- source-specific 污染规则缺失

目标结果：

- 主语料检索误召回下降
- 表格类问题的 evidence hit 提升
- 不引入 `real10` 与 `notes-frontmatter.real10` 的质量回退

## 范围

本阶段只做以下内容：

- 主语料噪音模式盘点与规则分层
- boilerplate / 导航 / 转载署名类清洗
- Markdown 表格结构化文本化
- source-specific 清洗规则框架
- 对应 benchmark / case diff / index stats 对照

本阶段不做：

- 新一轮 front matter 语义设计
- 新的 rerank 算法实验
- 跨文档近重复大规模抑制
- 大范围 chunker 重写

## 核心问题

### 问题 1：当前主语料的主要污染源不是 front matter

M13 已经证明：

- front matter 注入对 metadata-sensitive 题有效
- 但对主语料 index stats 的改善很有限

说明当前主语料更大的问题在：

- 导航块
- 固定转载/署名
- 模板说明
- 表格内容失真

### 问题 2：缺少针对真实污染模式的专项基准

当前 benchmark 已能覆盖：

- metadata-sensitive
- abstain
- ranking-sensitive

但还缺少对以下问题的直接刻画：

- 模板噪音误召回
- 表格信息漏召回
- 转载说明抢排位
- 固定导航块反复命中

## 设计原则

### 1. 清洗规则必须分层

- `L1` 低风险：
  - 明确可删的固定噪音
  - 不改变正文语义结构
- `L2` 中风险：
  - 表格结构化
  - source-specific 规则
- `L3` 高风险：
  - 跨文档近重复抑制
  - 激进重写 chunk 边界

M14 只做 `L1 + L2`，不碰 `L3`。

### 2. 所有规则都必须可解释

每条规则至少要回答：

- 删除/改写了什么
- 为什么它是噪音
- 会不会伤正文
- benchmark / diff 里改善了哪个 case

### 3. 一切以对比产物放行

放行不靠体感，必须看：

- benchmark 对比
- index stats 对比
- 样本文档 diff
- retrieval case diff

## 实施阶段

### Stage 0：噪音盘点与样本集建立

目标：

- 先确认主语料最常见的污染模式
- 建一个专门用于清洗验证的样本集

输出：

- `docs` 或 `dev-plan` 中的污染模式清单
- 至少 20 篇样本文档
- 至少 10 条主语料清洗专项 benchmark case

建议样本覆盖：

- 含转载署名的文档
- 含目录/导航块的文档
- 含 Markdown 表格的文档
- 含固定模板提示的文档
- 同主题但结构风格不同的 source

放行标准：

- 每类污染至少有 2 个代表样本
- benchmark case 可稳定复现问题

### Stage 1：Boilerplate / 导航 / 转载署名清洗

目标：

- 去掉明显不该参与检索的固定噪音

建议规则：

- 文首/文尾固定转载说明
- 固定作者署名
- 固定导航标题块
- 空列表项 / 分隔占位文本
- 明显模板废话

代码落点建议：

- `app/ingest/cleaner.py`
- 新增 `app/ingest/boilerplate_rules.py`
- `config.yaml` 增加可配置规则开关

放行标准：

- `real10` 不回退
- `notes-frontmatter.real10` 不回退
- 新增主语料清洗专项 case 至少有 3 条改善
- index stats 中重复噪音片段数量下降

### Stage 2：Markdown 表格结构化

目标：

- 把当前对检索不友好的 Markdown 表格改造成稳定文本表示

建议策略：

- 保留表头语义
- 行转句或键值对展开
- 尽量保留列关系，不做自由改写

优先格式：

- `列名: 值 | 列名: 值`
- 或
- `表格行: xxx`

代码落点建议：

- `app/ingest/markdown_parser.py`
- 或新增 `app/ingest/table_normalizer.py`

放行标准：

- 表格专项 case 的 evidence hit 提升
- 不恶化普通正文题的 `mrr`
- 样本文档 diff 可读且稳定

### Stage 3：Source-Specific 规则框架

目标：

- 允许按 source / path / corpus 套不同清洗规则

必要性：

- 通用规则无法安全覆盖所有笔记风格
- 某些噪音只在少数 source 中重复出现

建议设计：

- 规则按 source matcher 挂载
- 每条规则有：
  - `id`
  - `scope`
  - `pattern`
  - `action`
  - `enabled`

放行标准：

- 不引入“全局误删”
- 可以单独开关与回滚

## Benchmark 补强

M14 必须新增一套主语料清洗专项 case。

建议新增文件：

- `eval/benchmark.cleaning.real10.jsonl`

至少覆盖：

- boilerplate 抢排位
- 导航块命中高于正文
- 表格信息未被正确命中
- 固定转载说明导致误答
- source-specific 模板噪音干扰

## 对比产物

每轮至少产出：

- benchmark 结果
- benchmark diff
- index stats 快照
- index stats diff
- 至少 5 篇样本文档的 before/after diff
- 至少 5 条 retrieval case diff

建议命名：

- `eval/results/benchmark.cleaning.real10.m14.<stage>.json`
- `eval/results/index-stats/m14.<stage>.json`

## 质量门

以下指标不允许回退：

- `eval/benchmark.ai.real10.jsonl`
- `eval/benchmark.distributed.real10.jsonl`
- `eval/benchmark.game.real10.jsonl`
- `eval/benchmark.notes-frontmatter.real10.jsonl`

核心门槛：

- `recall_at_k`
- `mrr`
- `abstain_accuracy`
- `false_abstain_rate`
- `false_answer_rate`

额外目标：

- 主语料清洗专项 benchmark 至少有可量化正收益

## 风险点

### 风险 1：误删正文

应对：

- 规则默认从 `L1` 开始
- 保留样本文档 diff 审核

### 风险 2：表格展开过度改写

应对：

- 只做结构化转写
- 不做摘要化改写

### 风险 3：source-specific 规则失控

应对：

- 每条规则显式绑定 source matcher
- 所有规则可配置化开关

## 建议执行顺序

1. Stage 0：盘点污染模式并补专项 benchmark
2. Stage 1：boilerplate / 导航 / 转载署名清洗
3. Stage 2：表格结构化
4. Stage 3：source-specific 规则框架

## 本阶段完成标准

- 主语料清洗专项 benchmark 已建立
- 至少一轮 boilerplate 清洗落地
- 至少一轮表格结构化落地
- `real10` 与 `notes-frontmatter.real10` 无质量回退
- 台账、diff、验证命令完整记录
