# M19-M24 RAG 后续运营路线图

## 目标

这份路线图用于回答一个问题：

在 M16-M18 已经完成查询理解、guardrail 收口、benchmark suite 与 source audit 之后，`mykms` 后面还值得继续做什么，先做什么，做到什么程度才算真的进入长期可维护阶段。

整体判断是：

- M14 解决“脏内容进检索面”
- M15 解决“命中了但排不对”
- M16 解决“用户怎么问”
- M17 解决“系统怎么判能不能答”
- M18 解决“怎么做整组验收和 source 审计”
- M19-M24 要继续推进的是：
  - 失败 case 自动闭环
  - 新 source 准入治理
  - 近重复与主文档治理
  - 回答质量继续上探
  - 性能与成本压缩
  - 长期观测与运营化

## 总体顺序

建议顺序：

1. M19：失败闭环与 Benchmark 回填
2. M20：数据源接入与质量门
3. M21：近重复与主文档治理
4. M22：回答质量与一致性
5. M23：性能与成本优化
6. M24：观测与运营化

原因：

- 如果失败 case 还不能自动沉淀，后续优化仍然高度依赖手工记忆
- 如果新 source 还没有准入治理，知识库规模越大，质量会越不稳定
- 如果主文档治理与近重复治理缺席，后续回答质量和性能优化都要在噪音上反复做无效功
- 如果没有观测与运营化，前面的收益很难长期维持

## M19：失败闭环与 Benchmark 回填

### 目标

把“发现问题 -> 记 issue -> 补 case -> 修代码 -> 回归验证”这条链，从人工串联变成半自动闭环。

### 适合解决的问题

- 真实失败 case 只能手工记到 `issue-log`
- 某个问题修完后，没有稳定回流成 benchmark
- hard case 一直靠会话上下文记忆，不可持续

### 范围

建议包含：

- 从 benchmark failures / HTTP 调试结果生成 case 草稿
- issue 与 benchmark case 的双向关联
- “未入集失败 case” 待办清单
- case 模板自动补全：
  - `case_type`
  - `tags`
  - `expected_file_paths`
  - `notes`

不建议在 M19 做：

- 自动判定最终 benchmark 口径正确性
- 线上全自动采样直接入主 benchmark

### 目标结果

- 新失败 case 不再只停留在台账
- 每轮修复后，至少能把高价值 case 回流成专项 benchmark 或候选 case
- `issue-log` 与 benchmark 之间能互相追踪

### 质量门

- 不允许为了让结果更好看自动放宽 benchmark 口径
- 新增 case 必须能追溯来源
- case 回流流程不能破坏现有 benchmark schema

## M20：数据源接入与质量门

### 目标

给新增知识源建立正式准入标准，避免“能索引进来”被误当成“可以放心接入”。

### 适合解决的问题

- 新数据源接入前缺少质量检查
- 哪类数据源噪音最多、表格最多、模板污染最重，当前只能靠人工感觉
- 某个数据源接入后把检索拖坏了，难以及时识别

### 范围

建议包含：

- 数据源接入 checklist
- 数据源级质量门：
  - exact duplicate ratio
  - empty / near-empty chunk ratio
  - boilerplate / footer hit ratio
  - table-heavy ratio
  - metadata coverage
- 数据源级清洗策略模板
- 数据源审计快照版本化

不建议在 M20 做：

- 一上来全自动拒绝所有异常数据源
- 重写整个 ingest 流水线

### 目标结果

- 新数据源接入前有明确 checklist
- 高风险数据源可以在进入主索引前就被拦住或标红
- source audit 从“结果查看工具”升级成“准入评审工具”

### 质量门

- 数据源质量门规则配置化
- 审计输出可复现
- 主 benchmark 不因新增数据源无声回退

## M21：近重复与主文档治理

### 目标

系统处理“同主题多篇文档互相抢位”与“相似文档放大排序偏移”的问题。

### 适合解决的问题

- 同一主题的多版本文档互相竞争
- 转载、整理版、速查版混在一起后，主文档不稳定
- 近重复文档把 top rank 挤占掉

### 范围

建议包含：

- 跨文档近重复检测
- 主文档 / 辅助文档判定
- rerank 后的 document family 去竞争
- 同主题文档版本治理

不建议在 M21 做：

- 激进删除原始文档
- 没有审计输出就直接全局压制文档

### 目标结果

- 同主题相似文档不再反复抢 top1
- 主文档、速查文档、旁支文档的角色更稳定
- `ranking-sensitive` 与 `tooling` 类题型更稳

### 质量门

- `ranking.real10`
- `cleaning.real10`
- `distributed.real10`
- `notes-frontmatter.real10`

这些组不能回退，并且要能看到近重复治理带来的 MRR 改善

## M22：回答质量与一致性

### 目标

从“检索和拒答大体正确”继续上探到“回答更稳定、更一致、更像一套成熟系统”。

### 适合解决的问题

- comparison 题只回答单边信息
- procedure 题虽然命中，但步骤组织不稳
- definition 题答案风格不一致
- 多来源之间存在冲突时，系统没有显式约束

### 范围

建议包含：

- 分题型 answer 组织策略：
  - definition
  - existence
  - comparison
  - procedure
  - command / lookup
- evidence consistency / source agreement 检查
- answer-level 评测样本
- abstain reason 继续细化

不建议在 M22 做：

- 大规模换模型
- 无验证地重写整套 prompt 风格

### 目标结果

- 回答更稳定
- comparison / procedure 题的组织质量更高
- “命中了但答得乱”这类问题减少

### 质量门

- `false_abstain_rate`
- `false_answer_rate`
- `evidence_source_recall`
- answer-level sample review

answer-level 评测在这一阶段开始引入，但先以小规模专项集为主

## M23：性能与成本优化

### 目标

在不伤质量的前提下，把延迟、资源占用和重复计算成本压下来。

### 适合解决的问题

- semantic / rerank 仍然偏重
- 热 query 重复计算
- benchmark suite 跑起来成本高
- 索引更新与重建耗时偏长

### 范围

建议包含：

- 热 query / 热 benchmark cache
- rerank 预算控制
- 分层 recall / early exit
- 索引增量更新提速
- suite 执行耗时压缩

不建议在 M23 做：

- 为了速度直接削掉关键质量门
- 没有 profiling 就大规模改热路径

### 目标结果

- `avg_search_latency_ms` 降低
- `avg_ask_latency_ms` 降低
- suite 执行更稳定
- 本地 review 成本更低

### 质量门

- `ai / distributed / game / cleaning / ranking / notes-frontmatter / guardrail / query-routing`
  不回退
- 同时必须记录性能前后对比

## M24：观测与运营化

### 目标

把前面的能力从“能开发、能调试”推进到“能长期运行、能持续维护、能快速回溯”。

### 适合解决的问题

- benchmark 趋势变化没人看
- source 质量变化没人告警
- 索引版本和配置演进缺少记录
- 回归失败后，很难快速知道是哪一类能力退化

### 范围

建议包含：

- benchmark 趋势报表
- source audit 趋势报表
- gate failure 汇总视图
- index / config / suite 版本台账
- 阶段验收 runbook 固化

不建议在 M24 做：

- 直接上复杂外部平台迁移
- 没有本地最小闭环就先做重观测平台接入

### 目标结果

- benchmark、source、index 演进都有时间序列记录
- 出问题时可以先看报表，再看单 case
- 审查与回归流程更接近正式工程体系

### 质量门

- 关键报表可复现
- 问题能定位到 benchmark / source / config / index 哪一层
- 阶段验收流程文档化

## 各阶段关系

M19-M24 不是六个孤立主题，而是逐步把系统从“可用”推进到“长期可维护”：

- M19 解决“失败怎么进系统”
- M20 解决“新数据怎么准入”
- M21 解决“相似文档怎么治理”
- M22 解决“回答怎么更稳”
- M23 解决“效果够好后怎么降成本”
- M24 解决“怎么长期看住它”

如果跳过 M19 直接做 M20，会出现：

- 数据治理做了，但真实失败 case 还是沉不下来

如果跳过 M20 直接做 M21，会出现：

- 近重复治理刚做好，新接入 source 又把质量重新污染

如果跳过 M24，会出现：

- 前面阶段都做过，但没有一套长期观测与验收视图

## 完成标准

当 M19-M24 全部完成后，理想状态应是：

- 真实失败 case 能稳定回流 benchmark
- 新数据源接入有正式准入门
- 相似文档与主文档关系更稳定
- 回答质量不只“能答”，还“答得稳”
- 成本和延迟有明确优化结果
- benchmark / source / index 演进可审计、可回溯

## 当前建议

当前最值得优先立项的是：

1. M19：失败闭环与 Benchmark 回填
2. M20：数据源接入与质量门

原因：

- M16-M18 已经把“怎么修”和“怎么验收”打通了
- 下一步最值钱的是让问题能持续进入系统，让新数据不会重新把质量拖坏

也就是说，这份路线图当前先作为后续规划，其中：

- M19 是最优先的下一阶段
- M20 是紧随其后的配套阶段
