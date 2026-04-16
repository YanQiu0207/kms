# M17 Guardrail And Evidence Stage Summary

## 目标

M17 的目标是把“检索到了之后，系统怎么决定能不能答”单独收口，重点解决：

- 该答的不该误拒答
- 该拒答的不该被噪音证据放过去
- 证据要按同文档、同主题、同题型来判，而不是粗暴拼接

本阶段承诺的质量门是：

- `benchmark.guardrail.real10`
- `benchmark.ai.real10`
- `benchmark.distributed.real10`
- `benchmark.game.real10`
- `benchmark.cleaning.real10`
- `benchmark.ranking.real10`
- `benchmark.notes-frontmatter.real10`

## 实施内容

### 1. 调整 `/ask` 决策顺序

- 更新 [app/services/querying.py](/E:/github/mykms/app/services/querying.py)
- 当前 `/ask` 的 guardrail 判断顺序是：
  1. `evaluate_abstain()` 基础判定
  2. `_relax_query_profile_guardrail()` 题型窄放行
  3. `query_term_coverage` 约束
  4. `_evaluate_query_profile_guardrail()` 题型严格约束

### 2. existence 题型改成“强单文档证据”放行

- 旧问题：
  - existence 题容易因为证据短、标题短、metadata 多而被误拒答
- 当前策略：
  - 只在 `existence` 题型下启用
  - 只接受强单文档覆盖证据
  - 不允许靠跨文档拼接放行

### 3. 修正 query coverage 的证据侧构造

- 更新 [app/services/querying.py](/E:/github/mykms/app/services/querying.py)
- 新增 `_append_path_terms()`
- 作用：
  - 路径词只提 stem，不把 `.markdown` 这类后缀噪音算作有效证据
  - `relative_path / path_segments / front matter path` 会被更干净地纳入证据词集合

### 4. 清理 metadata constraint 的泛前缀噪音

- 更新 [app/retrieve/hybrid.py](/E:/github/mykms/app/retrieve/hybrid.py)
- `知识库里 / 笔记里 / 文档里` 这类泛前缀，不再被错误当成 metadata 约束词

### 5. prompt 组装改为消费预先算好的决策

- 更新：
  - [app/answer/prompt.py](/E:/github/mykms/app/answer/prompt.py)
  - [app/services/querying.py](/E:/github/mykms/app/services/querying.py)
- 作用：
  - prompt assembly 不再重复跑一套旧的 abstain 逻辑
  - `/ask` 返回与最终 guardrail 决策保持一致

### 6. 新增 guardrail 专项 benchmark

- 新增 [eval/benchmark.guardrail.real10.jsonl](/E:/github/mykms/eval/benchmark.guardrail.real10.jsonl)
- 覆盖类型：
  - score threshold
  - short evidence
  - existence
  - cross-doc abstain
  - multi-source comparison
  - procedure

## 结果

结果文件：

- [benchmark.guardrail.real10.m17.current.json](/E:/github/mykms/eval/results/benchmark.guardrail.real10.m17.current.json)

最终结果：

- `recall_at_k = 1.0`
- `mrr = 1.0`
- `abstain_accuracy = 1.0`
- `false_abstain_rate = 0.0`
- `false_answer_rate = 0.0`
- `evidence_hit_rate = 1.0`
- `evidence_source_recall = 1.0`

关键收口：

- `guard10-001`
  - `TrueTime` 不再因 guardrail 误拒答
- `guard10-002`
  - `高并发三大利器` 这类短证据题不再误拒答
- `guard10-003`
  - `timerfd` existence 题稳定回答
- `guard10-004`
  - `ZooKeeper watch` 这类跨文档拼接题保持正确拒答
- `guard10-006`
  - `2PC 和 3PC` comparison 题保持多源证据回答

## 问题与处理

### 问题 1：`cleaning10-006` 会被路径后缀和 TOC 噪音误放行

- 现象：
  - 该题本来应该拒答
  - 但旧逻辑会把路径里的 `.markdown` 和 HTML TOC 噪音算进证据
- 根因：
  - 证据词构造太宽，路径字符串按原样参与 coverage
- 处理：
  - 路径只提 stem，不再直接吃文件后缀
  - HTML TOC/comment 噪音不再被当作有效匹配证据

### 问题 2：existence 题和普通正文题共享同一套拒答阈值，导致误拒答

- 现象：
  - existence 题命中了，但因为正文很短仍会被拒答
- 根因：
  - 旧 guardrail 过度依赖 `score / chars`
- 处理：
  - 新增 `existence` 窄放行路径
  - 只有强单文档证据时才允许放行

### 问题 3：metadata / context 前缀词会污染约束判断

- 现象：
  - `知识库里有没有...`
  - `笔记里有没有...`
  这类表达会把“知识库、笔记”错误带进 metadata constraint
- 根因：
  - context constraint 提取过宽
- 处理：
  - 扩充 stopwords
  - 泛前缀只保留语气语义，不作为 metadata 命中过滤依据

## 验证

已通过：

- `.\.venv\Scripts\python.exe -m pytest tests\test_query_understanding.py tests\test_query_service.py tests\test_retrieval_m2.py tests\test_answer_m3.py -q`
- `.\.venv\Scripts\python.exe -m eval.run_benchmark --config config.yaml --benchmark eval/benchmark.guardrail.real10.jsonl --output eval/results/benchmark.guardrail.real10.m17.current.json`

## 结论

M17 已完成。

本阶段真正收口的是：

- existence / comparison / cross-doc 这几类题型的 guardrail 差异
- 证据词构造里的路径后缀噪音
- `/ask` 决策与 prompt 组装不一致的问题

M17 没做的是：

- 新模型替换
- 大规模 answer generation 风格重写
