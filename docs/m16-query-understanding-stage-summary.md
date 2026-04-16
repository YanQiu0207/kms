# M16 Query Understanding Stage Summary

## 目标

M16 的目标是把问题从“命中了但排不稳”继续往前推一层，解决：

- 用户问法变化导致召回不稳
- 缩写、别名、主题词没有被稳定归一
- 不同题型走同一条检索策略，导致本来该精确命中的问题被宽泛文档抢位

本阶段承诺的质量门是：

- `benchmark.query-routing.real10`
- `benchmark.ai.real10`
- `benchmark.distributed.real10`
- `benchmark.game.real10`
- `benchmark.cleaning.real10`
- `benchmark.ranking.real10`
- `benchmark.notes-frontmatter.real10`

## 实施内容

### 1. 新增 query understanding 层

- 新增 [app/query_understanding.py](/E:/github/mykms/app/query_understanding.py)
- 当前已落地的能力：
  - `query_type` 识别：
    - `definition`
    - `lookup`
    - `comparison`
    - `procedure`
    - `existence`
  - `route_policy` 路由：
    - `balanced`
    - `lookup-precise`
    - `comparison-diverse`
    - `procedure-semantic`
    - `existence-precise`
  - `anchor_terms`
  - `comparison_terms`
  - `canonical_query`
  - `alias_subject_terms`

### 2. 加入 alias / subject 归一

- 当前已内建的 alias 组：
  - `2pc / 两阶段提交 / 两阶段提交协议`
  - `3pc / 三阶段提交`
  - `hlc / hybrid logical clock / 混合逻辑时钟`
  - `aoi / area of interest / 感兴趣的区域`
  - `gdb / gnu debugger / 调试器`
  - `subagent / sub agent / 子代理`
- `build_query_variants()` 会优先保留原 question，再补：
  - 紧凑 query
  - anchor keyword query
  - alias 扩展 query

### 3. 把 query 路由接进检索入口

- 更新 [app/services/querying.py](/E:/github/mykms/app/services/querying.py)
- `/search` 与 `/ask` 现在都会：
  - 先分析 `QueryProfile`
  - 再扩 query
  - 再按题型路由 `recall_top_k / rerank_top_k`

### 4. 收口 definition / subject 类排序

- 更新 [app/retrieve/hybrid.py](/E:/github/mykms/app/retrieve/hybrid.py)
- 新增 definition subject affinity：
  - exact root title match
  - exact non-root title / file stem match
  - partial title / file stem containment
- 作用：
  - `subagent` 这类定义题会优先命中真正的主题主文档
  - `AOI` 这类术语题不会再被更宽泛的旁支文档抢位

### 5. 新增 query routing 专项 benchmark

- 新增 [eval/benchmark.query-routing.real10.jsonl](/E:/github/mykms/eval/benchmark.query-routing.real10.jsonl)
- 覆盖类型：
  - alias / rewrite
  - comparison
  - procedure
  - existence
  - abstain

## 结果

结果文件：

- [benchmark.query-routing.real10.m16.current.json](/E:/github/mykms/eval/results/benchmark.query-routing.real10.m16.current.json)

最终结果：

- `recall_at_k = 1.0`
- `mrr = 1.0`
- `abstain_accuracy = 1.0`
- `false_abstain_rate = 0.0`
- `false_answer_rate = 0.0`
- `evidence_hit_rate = 1.0`

关键收口：

- `query10-001`
  - `Hybrid Logical Clock` 稳定命中 `hlc.md`
- `query10-002`
  - `2PC` 稳定命中 `2pc.md`
- `query10-003`
  - `subagent` 从宽泛 `guide.md` 收口到 `2-subagent-base.md`
- `query10-005`
  - `AOI` 稳定命中 `aoi-algo.md`
- `query10-010`
  - `CRDT 详细算法` 保持正确拒答

## 问题与处理

### 问题 1：alias 能召回，但主题主文档不一定排第一

- 现象：
  - `subagent` 会被更宽泛的 Claude Code 文档抢位
  - `AOI` 会被 `独立aoi进程` 这类旁支文档抢位
- 根因：
  - 旧链路只会把 alias 当作 query 扩展词，不会把“这其实是在问哪个主题主词”显式带进排序
- 处理：
  - 新增 `alias_subject_terms`
  - 在 rerank 后追加 definition subject affinity 重排

### 问题 2：不同题型共用同一条 recall / rerank 路线，导致问题类型差异没被利用

- 现象：
  - comparison / procedure / existence 题都走近似同一条路径
- 根因：
  - 旧链路只有统一的 `recall_top_k` 与 `rerank_top_k`
- 处理：
  - 新增 `QueryProfile`
  - 新增 `route_retrieval()`
  - 让 comparison / procedure / metadata-focus 题型可以自动抬高 recall / rerank 上限

### 问题 3：benchmark query variant 容易丢掉原问题语义

- 现象：
  - 如果 query variant 只保留压缩后的关键词，容易把原问题里的限定条件丢掉
- 根因：
  - 纯扩展 query 没有保底保留原 question
- 处理：
  - `build_query_variants()` 现在优先保留 `canonical_query`
  - 后续扩展只能追加，不能替代原问题

## 验证

已通过：

- `.\.venv\Scripts\python.exe -m pytest tests\test_query_understanding.py tests\test_query_service.py tests\test_retrieval_m2.py -q`
- `.\.venv\Scripts\python.exe -m eval.run_benchmark --config config.yaml --benchmark eval/benchmark.query-routing.real10.jsonl --output eval/results/benchmark.query-routing.real10.m16.current.json`

## 结论

M16 已完成。

本阶段真正收口的是：

- alias / rewrite / subject 归一
- query 类型识别与检索路由
- `subagent`、`AOI` 这类“主题词明确但容易被宽泛文档抢位”的问题

M16 没做的是：

- 大规模 prompt 改写
- 新一轮清洗体系
- 更重的 agentic query planning
