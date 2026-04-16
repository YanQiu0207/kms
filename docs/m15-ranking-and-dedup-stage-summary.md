# M15 Ranking And Dedup Stage Summary

## 目标

M15 的目标不是继续扩清洗规则，而是收口 M14 留下的排序问题：

- 命中了，但排不对
- 同主题文档互相抢位
- query coverage 过严或过松，导致误拒答 / 误答

本阶段承诺的质量门是：

- `benchmark.cleaning.real10`
- `benchmark.ai.real10`
- `benchmark.distributed.real10`
- `benchmark.game.real10`
- `benchmark.notes-frontmatter.real10`

同时新增一组专项 benchmark：

- [benchmark.ranking.real10.m15.final.json](/E:/github/mykms/eval/results/benchmark.ranking.real10.m15.final.json)

## 实施内容

### 1. 新增排序专项 benchmark

- 新增 [eval/benchmark.ranking.real10.jsonl](/E:/github/mykms/eval/benchmark.ranking.real10.jsonl)
- 覆盖类型：
  - 表格映射 / 命令速查
  - 同主题文档竞争
  - `distributed` 与 `notes-frontmatter` 上的排序敏感 case

### 2. 修正 lookup / document-competition 排序

- 更新 [app/retrieve/hybrid.py](/E:/github/mykms/app/retrieve/hybrid.py)
- 当前排序增强点：
  - lookup intent 识别不再只覆盖“缩写 / 参数 / 宏”，也覆盖 `缺点` 这类主题竞争题
  - lookup term 优先级继续使用：
    - query term coverage
    - `表格行:` 数量
    - path/title 聚焦度
  - rerank 之后再做 lookup / metadata / diversification，再做最终 `top_k` 截断

### 3. 修正 query coverage 的判定方式

- 更新 [app/services/querying.py](/E:/github/mykms/app/services/querying.py)
- 当前策略：
  - 保留原来的“任一 query variant 自身覆盖足够即可通过”
  - 新增跨 query variant 的 weighted coverage，用来处理：
    - 同一个主锚点在多个 variant 中重复出现
    - 但某个附加限定词只出现在单个 variant 中
  - weighted coverage 只允许在“同一文档至少 2 个证据块”时生效
  - coverage 不再允许跨文档拼凑

### 4. 工程支撑修正

- 更新 [app/ingest/chunker.py](/E:/github/mykms/app/ingest/chunker.py)
- `build_chunk_id()` 已补上 `section_index`
- 这解决了同文档重复 section 的 `chunk_id` 潜在碰撞问题

## 结果

### 排序专项 benchmark

结果文件：

- [benchmark.ranking.real10.m15.final.json](/E:/github/mykms/eval/results/benchmark.ranking.real10.m15.final.json)

最终结果：

- `recall_at_k = 1.0`
- `mrr = 1.0`
- `abstain_accuracy = 1.0`
- `false_abstain_rate = 0.0`
- `false_answer_rate = 0.0`

关键收口：

- `rank10-008`
  - `2PC 的主要问题有哪些？`
  - `rank: 3 -> 1`
  - `top_file_path: 3pc.md -> 2pc.md`
- `rank10-009`
  - `TrueTime 的关键价值是什么？`
  - `abstained: true -> false`

### cleaning 专项收益

对比文件：

- [benchmark.cleaning.real10.m14-vs-m15.diff.json](/E:/github/mykms/eval/results/benchmark.cleaning.real10.m14-vs-m15.diff.json)

核心提升：

- `recall_at_k: 0.875 -> 1.0`
- `mrr: 0.8125 -> 1.0`
- `evidence_hit_rate: 0.875 -> 1.0`
- `evidence_source_recall: 0.875 -> 1.0`

`table / tooling` 子集提升最明显：

- `table.mrr: 0.75 -> 1.0`
- `tooling.mrr: 0.25 -> 1.0`

关键 case：

- `cleaning10-003`
  - `rank: 2 -> 1`
- `cleaning10-009`
  - `search_hit: false -> true`
  - `rank: null -> 1`

### 质量门

对比文件：

- [benchmark.ai.real10.m14-vs-m15.diff.json](/E:/github/mykms/eval/results/benchmark.ai.real10.m14-vs-m15.diff.json)
- [benchmark.distributed.real10.m14-vs-m15.diff.json](/E:/github/mykms/eval/results/benchmark.distributed.real10.m14-vs-m15.diff.json)
- [benchmark.game.real10.m14-vs-m15.diff.json](/E:/github/mykms/eval/results/benchmark.game.real10.m14-vs-m15.diff.json)
- [benchmark.notes-frontmatter.real10.m14-vs-m15.diff.json](/E:/github/mykms/eval/results/benchmark.notes-frontmatter.real10.m14-vs-m15.diff.json)

结果：

- `ai.real10`
  - 核心质量不回退
- `distributed.real10`
  - `mrr: 0.9167 -> 1.0`
  - `abstain_accuracy: 0.8 -> 1.0`
  - `false_answer_rate: 0.5 -> 0.0`
- `game.real10`
  - 核心质量不回退
- `notes-frontmatter.real10`
  - 核心质量不回退

## 问题与处理

### 问题 1：`2PC` / `GDB` 这类 case 不是召回失败，而是 lookup intent 触发不够

- 现象：
  - `2PC` 被 `3pc.md` 背景段压过
  - `GDB info / backtrace` 被详解正文压过
- 根因：
  - 这类问题本质是“查值 / 主题主文档竞争”
  - 原 lookup intent 主要覆盖“缩写 / 参数 / 宏”，对 `缺点` 这类题型不敏感
- 处理：
  - 扩 lookup intent
  - 保留 table-aware / title-aware / path-aware 的窄排序信号
  - 最终 `top_k` 截断后移到 lookup / metadata / diversification 之后

### 问题 2：`TrueTime` 被误拒答，根因不是召回，而是 query coverage 太死

- 现象：
  - `TrueTime` 已 `rank=1`
  - 但 `/ask` 仍因 `query_term_coverage_below_threshold` 拒答
- 根因：
  - query variants 为 `TrueTime 价值` 与 `Google TrueTime`
  - 真正稳定重复出现的是 `TrueTime`
  - `Google` 只是单个 variant 的附加限定词
- 处理：
  - 新增 weighted cross-variant coverage
  - 让重复主锚点的权重高于单次附加限定词

### 问题 3：weighted coverage 第一版会跨文档拼凑，导致 `ZooKeeper watch` 误答

- 现象：
  - 第一版 weighted coverage 修完 `TrueTime` 后，`dist10-010` 从正确拒答变成误答
- 根因：
  - coverage 按全局 evidence 并集算分
  - `ZooKeeper` 与 `watch` 可以被不同文档分别命中，再被错误拼起来
- 处理：
  - coverage 改为按“单文档最佳覆盖”计算
  - weighted coverage 进一步收窄到：
    - 同一文档
    - 至少 2 个证据块
  - 这样 `TrueTime` 这种同文档证据簇能通过，`ZooKeeper watch` 这种跨文档拼凑过不了

## 未做与边界

M15 计划里原本包含“跨文档近重复抑制”。

本轮没有单独落一个通用的 near-duplicate 抑制器，原因是：

- 当前阻塞质量门的问题，根因已经被定位为：
  - lookup/document-competition 排序
  - query coverage 证据判定
- 在这些问题收口后：
  - `cleaning.real10`
  - `ranking.real10`
  - `distributed.real10`
  已经达成阶段目标

因此 M15 实际完成的是：

- 排序专项 benchmark
- source-aware / lookup-aware 排序收口
- query coverage 收口
- `chunk_id` 工程支撑修正

而“通用 near-duplicate 抑制器”没有被记入本阶段收益。

## 验证

已通过：

- `.\.venv\Scripts\python.exe -m pytest tests\test_retrieval_m2.py tests\test_query_service.py tests\test_ingest_chunker.py -q`
- `.\.venv\Scripts\python.exe -m pytest -q`

当前全量回归结果：

- `94 passed`

## 结论

M15 已完成。

本阶段真实收口的是：

- M14 残留的 `GDB` 表格类排序偏移
- `distributed` 中的 `2PC / TrueTime / ZooKeeper watch` 三类排序与证据判定问题
- 面向排序问题的专项 benchmark 与回归抓手
- `chunk_id` 稳定性问题

本阶段没有被写成收益的是：

- 通用跨文档近重复抑制器
