# M13 RAG Data Cleaning Plan

## Goal

为 `mykms` 增加一轮真正面向检索的数据清洗能力，但不以“看起来更干净”为目标，而以“检索质量可量化提升、误伤可控、可回滚”为目标。

本阶段优先解决：

- YAML front matter 混入正文，污染检索
- Markdown 表格、导航块、模板噪音未结构化处理
- 完全重复或高度重复 chunk 进入索引，稀释排序
- 缺少稳定的前后对比基线，优化效果只能靠感觉判断

## Scope

本阶段覆盖：

- `app/ingest/`
- `app/services/indexing.py`
- `config.yaml` 与对应 config model
- `eval/` 基准集与结果快照
- 必要的测试与文档

本阶段不覆盖：

- 宿主答案生成逻辑
- `/ask` 提示词模板大改
- 新增 Agentic RAG / Supervisor
- 大规模替换现有检索架构

## Current State

当前索引主链路是：

`read file -> parse markdown sections -> split blocks/chunks -> persist metadata/fts/vector`

现状核对：

- [app/ingest/loader.py](/E:/github/mykms/app/ingest/loader.py:71) 只负责读文件和解码
- [app/ingest/markdown_parser.py](/E:/github/mykms/app/ingest/markdown_parser.py:62) 主要按标题切 section
- [app/ingest/chunker.py](/E:/github/mykms/app/ingest/chunker.py:94) 主要按空行、代码块和长度切 block/chunk
- [app/services/indexing.py](/E:/github/mykms/app/services/indexing.py:37) 到 [app/services/indexing.py](/E:/github/mykms/app/services/indexing.py:103) 会把当前 document/chunk 元数据写入 SQLite / FTS / Chroma

因此本阶段的关键不是重写索引服务，而是在 ingest 链路中插入一个可控的 cleaning/enrichment 层。

## Open Source Reuse Decision

结论：采用“轻量复用 + 项目内编排”，不直接引入重型通用 ETL 框架作为主链路。

### 优先复用

1. `PyYAML`
   - 仓库已依赖
   - 用于 front matter 抽取即可
   - 不需要为此单独引入新的 front matter 库

2. `markdown-it-py` + `mdit-py-plugins`
   - 用于增强 Markdown 结构识别，尤其是表格、front matter、块级结构
   - 定位是“可选结构解析器”，不是一上来就强制替换整个 parser

3. `simhash`
   - 作为高相似 chunk 去重的候选方案
   - 第一版只在 L2/L3 使用，不进入首批最低风险清洗

### 暂不采用

1. `unstructured`
   - 能做 `partition_md`，但依赖偏重
   - 对当前纯 Markdown 知识库来说收益不一定匹配复杂度
   - 容易和现有 `title_path`、行号、chunk id、增量索引语义冲突

2. 重型通用去重框架
   - 当前规模下没有必要
   - 先做轻量规则和小样本对比

## Design Principles

1. 先保守，再增强。
   第一版只上低风险清洗，不做会大幅改写正文语义的动作。

2. 先做前后对比，再默认开启。
   所有清洗动作都要能关闭，并能在同一批语料和 benchmark 上做前后对照。

3. 清洗是“为检索服务”，不是“为排版服务”。
   任何规则只要降低证据可追溯性、破坏标题路径或行号稳定性，都要谨慎。

4. source-specific 规则只能建立在通用规则之后。
   先抽出通用清洗层，再为某些 source root 增加局部规则。

## Phase Plan

## Stage 0: Baseline and Comparison Harness

### Goal

先建立可靠对照组，确保后续每一步都能量化收益和风险。

### Deliverables

- 基线 benchmark 集合与结果快照
- 语料级索引统计快照
- 前后对比脚本或命令约定
- 对照报告模板

### Actions

1. 固定一组语料快照
   - 从当前 `config.yaml` 的 source 中选取稳定样本
   - 至少覆盖：
     - 普通技术笔记
     - 含 front matter 的 Markdown
     - 含表格的 Markdown
     - 含模板导航或重复页脚的 Markdown

2. 固定一组 benchmark
   - 在现有 `eval/benchmark.*.jsonl` 基础上扩题
   - 至少补：
     - `rewrite`
     - `distractor`
     - `multi_doc`
     - `abstain`
     - `identifier`

3. 固定比较指标
   - 检索质量：
     - `recall_at_k`
     - `mrr`
     - `evidence_hit_rate`
     - `evidence_source_recall`
     - `expected_term_coverage`
   - 风险指标：
     - `false_answer_rate`
     - `false_abstain_rate`
   - 索引侧指标：
     - document count
     - chunk count
     - avg chunk length
     - median chunk length
     - duplicated chunk ratio
     - top repeated snippets

4. 固定输出位置
   - benchmark 结果快照写入 `eval/results/`
   - 索引统计快照写入建议新增目录 `eval/results/index-stats/`
   - 文件名使用统一前缀：
     - `baseline.*`
     - `cleaning-v1.*`
     - `cleaning-v2.*`

### Acceptance

- 能在不改业务逻辑的前提下稳定重跑同一组 benchmark
- 能拿到一份 baseline benchmark 结果和一份 baseline 索引统计
- 后续每个 cleaning 版本都能和 baseline 一对一比较

## Stage 1: Low-Risk Cleaning

### Goal

先落最低风险、最高确定性的清洗，不改变主要语义边界。

### Deliverables

- 新增 `app/ingest/cleaner.py`
- loader 接入 document cleaning
- front matter 抽取
- 规范化与完全重复去重
- 配置开关

### Actions

1. 新增 document cleaner 层
   - 输入：原始 Markdown 文本
   - 输出：
     - `cleaned_text`
     - `front_matter`
     - `cleaning_flags`
     - `cleaning_report`

2. 第一版清洗规则只做：
   - 提取并移除 YAML front matter
   - 统一换行、去 BOM、压缩异常空白
   - 过滤纯空 section / chunk
   - 对完全重复 chunk 做去重或降权标记

3. front matter 进入 metadata
   - 文档级建议保留：
     - `title`
     - `tags`
     - `date`
     - `aliases`
     - `category`
   - 未识别字段可先保存在原始 `front_matter` 映射中

4. 配置化
   - 在 `config.yaml` 增加 `cleaning:` 段
   - 示例开关：
     - `enabled`
     - `extract_front_matter`
     - `drop_front_matter_from_content`
     - `dedupe_exact_chunks`
     - `normalize_whitespace`

### Acceptance

- benchmark 主指标不回退，至少不能出现显著下降
- chunk 总量合理下降或持平
- front matter 不再污染正文检索
- 代码、配置、测试都支持关闭 cleaning，保证可回滚

## Stage 2: Structured Markdown Cleaning

### Goal

增强对表格、导航块、模板噪音的处理能力。

### Deliverables

- 可选 `markdown-it-py` 结构解析接入
- 表格文本化策略
- boilerplate 检测规则
- source-specific 规则框架

### Actions

1. 评估并引入 `markdown-it-py`
   - 不要求一开始替换整个 `MarkdownParser`
   - 可先只用于：
     - front matter 检测兜底
     - 表格识别
     - list / block 结构识别辅助

2. 表格处理策略
   - 将表格保留为可追溯文本表达
   - 至少保留：
     - 表头
     - 每一行的键值语义
   - 避免把表格直接压成无结构长文本

3. boilerplate 噪音清洗
   - 通用规则优先识别：
     - 目录块
     - 导航块
     - 固定免责声明
     - 重复页脚/站点尾注
   - 对高风险规则只先打标，不默认删除

4. source-specific 规则
   - 在 `cleaning:` 中支持按 source root 配规则
   - 例如：
     - 某目录特有页脚
     - 某类文档特有目录模板

### Acceptance

- `distractor`、`rewrite`、`multi_doc` 类题型有稳定提升
- 表格相关 query 的证据覆盖率提升
- 模板噪音相关 chunk 显著减少
- 对照报告能列出被删除或降权的典型片段

## Stage 3: Near-Duplicate Suppression

### Goal

减少高相似内容在结果列表中互相挤占排名。

### Deliverables

- 近重复检测策略
- `simhash` 接入或自实现候选方案
- 去重或降权策略

### Actions

1. 先只做离线分析
   - 统计高度相似 chunk 对
   - 抽样人工确认是否属于真正噪音重复

2. 再决定运行时策略
   - 方案 A：索引时过滤
   - 方案 B：保留入库但检索时降权

3. 优先保守策略
   - 第一版更建议“保留入库 + 检索阶段降权”
   - 避免误删真实不同但相似的知识片段

### Acceptance

- `MRR` 与 `evidence_source_recall` 提升
- 不出现大规模误删导致的 `recall_at_k` 明显下降

## Data Comparison Requirements

本项目的数据对比是强制项，不是可选附加项。

### Comparison Dimensions

每一轮 cleaning 版本都必须输出以下对比：

1. benchmark 对比
   - baseline vs candidate
   - overall
   - `by_type`
   - `by_tag`

2. 索引统计对比
   - 文档数
   - chunk 数
   - 每文档 chunk 数分布
   - chunk 长度分布
   - top 重复片段

3. retrieval case diff
   - 至少抽 10 条代表性 query
   - 对比：
     - top-k 命中来源
     - 排名变化
     - `ask.sources` 变化
     - 是否从误答变为拒答，或反之

4. 样本文档 diff
   - 至少抽 5 篇文档
   - 对比原文、cleaned text、最终 chunk
   - 要能解释“为什么这个规则有益且没伤语义”

### Pass / Fail Rule

默认放行条件：

- `false_answer_rate` 不升高
- `recall_at_k` 不出现明显回退
- 至少 1 个核心指标有实质改善：
  - `mrr`
  - `evidence_hit_rate`
  - `expected_term_coverage`
- 索引清洗后没有出现大规模误删

默认拦截条件：

- `false_answer_rate` 明显升高
- `recall_at_k` 明显下降
- 大量样本文档出现关键信息丢失
- cleaning 规则无法通过配置关闭或回滚

## Suggested Config Additions

建议在 `config.yaml` 中新增：

```yaml
cleaning:
  enabled: true
  extract_front_matter: true
  drop_front_matter_from_content: true
  normalize_whitespace: true
  dedupe_exact_chunks: true
  parse_markdown_tables: false
  boilerplate:
    enabled: false
    patterns: []
  near_duplicate:
    enabled: false
    mode: mark_only
    simhash_distance: 3
  source_overrides: []
```

说明：

- `parse_markdown_tables`、`boilerplate.enabled`、`near_duplicate.enabled` 初版建议默认关闭，经过对比后再决定是否打开。
- `mode: mark_only` 表示先只打标和统计，不直接删。

## Risks

1. 清洗过度，误删有效证据
2. front matter 字段格式不统一，抽取后 metadata 质量不稳定
3. 表格文本化不当，反而破坏可检索性
4. 近重复检测误伤版本差异文档
5. 新增解析依赖后 Windows 环境复杂度上升

## Review Focus

Review A 重点看：

- cleaning 规则是否破坏真实文档语义
- metadata 设计是否支持后续检索过滤
- 对比方法是否真实可复现

Review B 重点看：

- 增量索引是否保持稳定
- 测试是否覆盖关闭开关、回滚和误删风险
- 新依赖是否必要、是否引入过重负担

## Acceptance

- `dev-plan` 中的阶段、对比方法、放行条件已明确
- 开源复用边界已拍板：轻量复用，不引入重型主链路框架
- 后续实现默认按 Stage 0 -> Stage 1 -> Stage 2 -> Stage 3 顺序推进
- 任何阶段上线前都必须产出前后对比结果
