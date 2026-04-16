# M14 RAG Cleaning Stage Summary

## 目标

M14 的目标不是继续修 `front matter` 或 semantic 稳定性，而是把清洗重点拉回主语料里更高频、更真实的检索污染源：

- boilerplate / 导航 / 固定模板噪音
- Markdown 表格信息失真
- source-specific 尾注、转载、参考区

同时要求：

- 不改 benchmark 口径来“做漂亮数据”
- `ai / distributed / game / notes-frontmatter` 四组质量门不回退
- 每轮都能产出 benchmark、index stats、样本文档 diff

## 实施内容

### 1. 先固定对照基线

- 新增独立基线配置：[config.m14.baseline.yaml](/E:/github/mykms/config.m14.baseline.yaml)
- 该配置保留 M13 能力，但关闭 M14 新增清洗规则，用来做同代码、不同清洗配置的对照
- 基线结果：
  - [benchmark.cleaning.real10.m14.corrected-baseline.json](/E:/github/mykms/eval/results/benchmark.cleaning.real10.m14.corrected-baseline.json)
  - [m14.corrected-baseline.json](/E:/github/mykms/eval/results/index-stats/m14.corrected-baseline.json)

### 2. 落地主语料清洗规则

- 新增 [app/ingest/boilerplate_rules.py](/E:/github/mykms/app/ingest/boilerplate_rules.py)
  - 支持按 `path_globs / source_root_globs` 挂 source-specific 规则
  - 支持删行和删文尾参考区
- 新增 [app/ingest/table_normalizer.py](/E:/github/mykms/app/ingest/table_normalizer.py)
  - 把 Markdown 表格转为稳定文本
  - 当前格式为：
    - `表格列: ...`
    - `表格行: 列名是 值；列名是 值`
- 更新 [app/ingest/cleaner.py](/E:/github/mykms/app/ingest/cleaner.py)
  - 接入 `[TOC]`、低价值占位、表格结构化、source-specific 规则
  - 把清洗元数据写回 `document.metadata["cleaning"]`
- 更新 [config.yaml](/E:/github/mykms/config.yaml)
  - 启用 `normalize_markdown_tables`
  - 配置 `drop-zhihu-edit-footer`
  - 配置 `drop-reference-tail-sections`

### 3. 补样本与审阅抓手

- 新增 [scripts/export_cleaning_samples.py](/E:/github/mykms/scripts/export_cleaning_samples.py)
- 样本产物：
  - [m14.final.samples.json](/E:/github/mykms/eval/results/cleaning-samples/m14.final.samples.json)
- 额外做了 footer 定位样本：
  - [m14.footer-check.json](/E:/github/mykms/eval/results/cleaning-samples/m14.footer-check.json)
  - 该文件用于解释单文件导出时 `relative_path` 不命中 glob 的假阴性，不代表正式 ingest 链路失效

## 结果

### 清洗专项 benchmark

基线：

- `recall_at_k = 0.875`
- `mrr = 0.8125`
- `abstain_accuracy = 0.9`
- `false_answer_rate = 0.5`

最终：

- 结果文件：[benchmark.cleaning.real10.m14.final.json](/E:/github/mykms/eval/results/benchmark.cleaning.real10.m14.final.json)
- diff 文件：[m14.final.diff.json](/E:/github/mykms/eval/results/index-stats/m14.final.diff.json)
- 指标：
  - `recall_at_k = 0.875`
  - `mrr = 0.8125`
  - `abstain_accuracy = 1.0`
  - `false_answer_rate = 0.0`

核心收益：

- `cleaning10-006`
  - 从 false answer 收口为正确拒答
- `toc-noise` 子集
  - `abstain_accuracy: 0.6667 -> 1.0`
  - `false_answer_rate: 1.0 -> 0.0`

未改善项：

- `cleaning10-003`
  - `GDB backtrace` 仍为 `rank=2`
- `cleaning10-009`
  - 在保守 benchmark 口径下，仍未命中期望文档 `1.0 基础知识.md`

### 索引统计

最终索引快照：

- [m14.final.json](/E:/github/mykms/eval/results/index-stats/m14.final.json)

对比基线：

- `chunk_count: 5366 -> 5356`
- `exact_duplicate_groups: 59 -> 58`
- `exact_duplicate_chunk_count: 86 -> 83`
- `exact_duplicate_chunk_ratio: 0.016 -> 0.0155`

这说明 M14 的收益主要在：

- 去掉一部分固定噪音 chunk
- 降低重复片段
- 减少由 `[TOC]` 和尾注带来的误答

### 质量门

M14 没有把其它评测集拉坏：

- [benchmark.ai.real10.m14.final.json](/E:/github/mykms/eval/results/benchmark.ai.real10.m14.final.json)
  - 核心质量不回退
- [benchmark.distributed.real10.m14.final.json](/E:/github/mykms/eval/results/benchmark.distributed.real10.m14.final.json)
  - 核心质量不回退
- [benchmark.game.real10.m14.final.json](/E:/github/mykms/eval/results/benchmark.game.real10.m14.final.json)
  - `mrr: 0.9444 -> 1.0`
- [benchmark.notes-frontmatter.real10.m14.final.json](/E:/github/mykms/eval/results/benchmark.notes-frontmatter.real10.m14.final.json)
  - 保持全绿，且平均检索延迟下降

## 问题与处理

### 问题 1：benchmark 口径不能被功能开发污染

- 现象：
  - `cleaning10-009` 一度被改成更宽松的目标文档
- 根因：
  - benchmark 维护和功能开发被混在了一轮里
- 处理：
  - 已把 case 改回保守口径
  - 已把纪律落到 [AGENTS.md](/E:/github/mykms/AGENTS.md)
  - 已单独记录到 [dev-run/issue-log.md](/E:/github/mykms/dev-run/issue-log.md)

### 问题 2：单文件样本导出会对 source-specific 规则给出假阴性

- 现象：
  - `m14.footer-check.json` 里 `戈君.md` 的 `source_rule_dropped_lines = 0`
- 根因：
  - 单文件导出时把该文件本身当 `source_root`
  - `relative_path` 退化成 `戈君.md`
  - 不会命中 `第三方软件/brpc/作者/*.md`
- 处理：
  - 已用真实 `E:/notes` source root 复核正式 ingest 链路
  - 结果为：
    - `source_rule_dropped_lines = 1`
    - `source_rules_applied = ['drop-zhihu-edit-footer']`
    - 清洗后正文不再包含 `编辑于`

### 问题 3：表格结构化没有拉动 GDB 两个保守 case

- 现象：
  - `cleaning10-003` 与 `cleaning10-009` 仍被 `2.0 常用命令详解.md` 压过
- 根因：
  - 当前问题不是“表格完全丢失”，而是相邻主题文档之间的排序偏移
  - `2.0 常用命令详解.md` 的正文解释更直接，仍比 `1.0 基础知识.md` 的命令映射表更占优
- 处理：
  - M14 内已完成表格结构化，但没有为这两个 case 做额外排序特化
  - 该问题作为残留单独记录，不混入“已提升”结论

## 验证

已通过：

- `pytest tests/test_ingest_cleaner.py tests/test_indexing_service.py -q`
- `pytest tests/test_ingest_cleaner.py -q`
- `pytest -q`

当前全量回归结果：

- `86 passed`

## 结论

M14 已完成。

本阶段真实收口的是：

- 主语料 `[TOC]` / boilerplate / footer-noise 的误答
- Markdown 表格的稳定结构化接入
- source-specific 清洗规则框架
- 同口径 benchmark 与 index stats 对照

本阶段没有收口的是：

- `GDB` 表格类保守 case 的排序偏移

这属于后续排序或 source-aware 检索优化问题，不再归到 M14 已完成收益里。
