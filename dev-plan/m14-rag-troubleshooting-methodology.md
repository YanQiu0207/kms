# RAG 问题排查方法论

## 目的

这份方法论不是讲某一个 bug，而是沉淀这轮 M13 里实际用过、证明有效的排查流程。

适用范围：

- 检索质量退化
- 误答 / 误拒答
- 排名偏移
- semantic / lexical 行为不一致
- 索引或向量库运行时异常

核心原则只有一句话：

**先把问题拆成可验证的子问题，再让每一层只回答一个问题。**

## 一、先分清“这是哪一类问题”

RAG 问题不要一上来就改模型、改 prompt、改 chunk。

第一步必须先分型：

### 1. 检索问题

表现：

- 没召回目标文档
- 召回了，但 rank 很差
- 排名被无关 chunk 抢走

典型问法：

- `search_hit` 是否为 `false`
- 目标文档是否在 Top-K
- 是 fused 前丢了，还是 rerank 后丢了

### 2. Guardrail / 拒答问题

表现：

- 检索已经对了，但 `/ask` 仍拒答
- `abstain_reason` 落在阈值规则上

典型问法：

- 是 `top1_score_below_threshold`
- 还是 `recall_hits_below_threshold`
- 还是 `evidence_chars_below_threshold`

### 3. 评测集问题

表现：

- benchmark 自己把约束语义压掉了
- query variant 和原问题不一致
- case 标注与实现目标不一致

典型例子：

- `notesfm10-008` 的 query variant 丢了“分类下”

### 4. 运行时 / 基础设施问题

表现：

- access violation
- 某路径稳定崩溃
- semantic-on 和 lexical-only 行为完全不同

典型例子：

- `chromadb.api.rust._query` 的 Windows `access violation`

## 二、先固定基线，再开始改

排查前必须先把“改前长什么样”固定住。

否则你会在一个不断变化的系统里追幽灵。

本轮证明有效的做法：

- 先产 baseline benchmark
- 先产 index stats baseline
- 先把坏 case 写进 benchmark 或 issue log

最少需要固定：

- benchmark 结果文件
- case diff
- index stats 快照
- 当前配置文件

如果没有这些，后面所有“变好了”都不可靠。

## 三、每次只缩一层，不要多层一起猜

排查时最容易犯的错误，是同时改：

- 配置
- 检索逻辑
- guardrail
- benchmark case

这样最后根本不知道是哪一项生效。

正确做法是逐层缩圈：

### 第 1 层：先看 `/search`

回答三个问题：

- 目标文档有没有被召回
- Top-K 里有哪些文档
- 问题发生在 lexical、semantic、还是 rerank

### 第 2 层：再看 `/ask`

如果 `/search` 是对的，就不要继续怀疑召回。

直接看：

- `abstained`
- `abstain_reason`
- `source_count`
- `confidence`

### 第 3 层：最后才看 benchmark 汇总

benchmark 用来证明“整组是否改善”，不是用来替代单 case 定位。

顺序应该是：

1. 单 case 定位
2. 单测或局部复现
3. 整组 benchmark 放行

## 四、优先做最小复现

复杂系统里的问题，先剥离到最小复现。

本轮用过两个非常有效的手法：

### 1. 从 benchmark case 退化成单 query 探针

比如 `notesfm10-006`：

- 先跑整组 benchmark
- 再只打这一个 case
- 再只看 `service.search()`
- 再只看 `service.ask()`

这样能快速看出：

- 是整组交互问题
- 还是这个 case 本身的阈值问题

### 2. 从主链路退化成独立探针脚本

比如 Chroma 崩溃：

- 不在主服务里查
- 单独做 `scripts/chroma_semantic_probe.py`

意义是：

- 去掉 API、QueryService、benchmark 框架干扰
- 直接验证底层 collection 是否可 query

## 五、A/B 只改一个维度

遇到复杂问题，不要“改一堆看看有没有好”。

有效的 A/B 原则是：

- 每次只改一个维度
- 每次都要有明确想验证的假设

本轮有效的 A/B 例子：

### 1. Chroma 崩溃排查

假设：

- 是不是 metadata 太重导致崩溃

A/B：

- 原 persist
- fresh persist + full metadata
- fresh persist + minimal metadata

结论：

- 不是 metadata 太重
- 是原 persisted collection 状态有问题

### 2. `notesfm10-008` 排名问题

假设：

- 是不是 benchmark query 丢了 category 语义

A/B：

- 原 query variants
- 保留原问题作为 variant

结论：

- 的确是 query 变体先把约束语义压掉了

### 3. semantic-on 误拒答

假设：

- 是不是 semantic 召回错了

A/B：

- 先比 `/search`
- 再比 `/ask`

结论：

- 不是召回错
- 是 guardrail 对 metadata 存在性证据过严

## 六、把“症状”和“根因”分开记录

很多时候症状是真的，但根因不是你第一眼看到的那个。

比如：

- 症状：`notesfm10-006` semantic-on 下误拒答
- 非根因：semantic 召回坏了
- 真根因：只剩同文档标题型 chunk，guardrail 仍按正文字符阈值拒答

所以 issue 记录至少分四段：

- 现象
- 当前影响
- 根因
- 修复与验证

如果不拆开，后面很容易重复排同一个问题。

## 七、优先用“真实证据”而不是猜

排查时，优先看真实产物：

- benchmark case result
- `search_result.to_payload()`
- `abstain_reason`
- `source_hits`
- `semantic_score`
- 实际命中的 chunk 内容

不要只看：

- 变量名
- 设计意图
- 代码注释

本项目还有一条额外原则：

- 涉及协议、流式、前后端消费链路时，必须看真实 wire payload

这个原则同样适用于 RAG：

- 不要假设“semantic 应该召回更多”
- 要直接看它到底召回了什么

## 八、修复要尽量窄，不要全局放松

高质量修复不是“把阈值全调低”。

高质量修复应该是：

- 只放开真正该放开的场景
- 不改变无关 case 的行为

本轮最典型的例子：

### 错误修法

- 直接全局降低 `min_total_chars`

风险：

- 会把其他本该拒答的 case 放出来

### 正确修法

- 只对“同文档、多 chunk、一致 metadata 约束且带 semantic 支持”的证据簇做窄场景放行

效果：

- `notesfm10-006` 恢复
- `notesfm10-009` 不回退

## 九、先修单点，再跑整组

顺序不能反：

1. 单点 case 定位
2. 单测补住
3. 定向验证
4. 全量回归
5. benchmark diff

如果直接跳到整组 benchmark：

- 你只能知道“坏了/好了”
- 但不知道是哪条规则在起作用

## 十、把“放行标准”提前写死

每轮改动前就要写清楚哪些指标不能退。

本轮有效的质量门：

- `recall_at_k`
- `mrr`
- `abstain_accuracy`
- `false_abstain_rate`
- `false_answer_rate`

覆盖集：

- `ai.real10`
- `distributed.real10`
- `game.real10`
- `notes-frontmatter.real10`

这一步非常关键，因为它决定了：

- 哪些改动可以保留
- 哪些改动必须回退

## 十一、台账不是附属品，是排查主线的一部分

真正复杂的问题，如果不写台账，过两轮你自己都会忘。

这轮实践证明必须维护三份东西：

- `dev-run/issue-log.md`
  - 记录问题、根因、修复、验证
- `dev-run/progress.md`
  - 记录每轮做了什么、跑了什么
- `dev-run/stage-status.md`
  - 记录当前阶段是否已通过、剩余关注点是什么

它们的作用不是“留痕”，而是：

- 防止重复排查
- 防止结论漂移
- 防止旧状态和新状态混在一起

## 十二、本轮可复用的标准排查流程

后续再遇到 RAG 问题，可以直接按下面流程走：

1. 先分型
- 检索问题、拒答问题、benchmark 问题、还是运行时问题

2. 固定基线
- 产 baseline benchmark、index stats、case diff

3. 找单个坏 case
- 不要一上来就看整组均值

4. 缩到最小复现
- 单 query
- 单 case
- 必要时单独探针脚本

5. 做单维度 A/B
- 每次只验证一个假设

6. 看真实证据
- 命中的 chunk、source_hits、abstain_reason、真实 payload

7. 做窄修复
- 不用全局放松去掩盖单点问题

8. 先补单测
- 把坏 case 变成可重复的回归测试

9. 再跑整组 benchmark
- 只用整组结果做放行，不用它代替定位

10. 更新台账
- issue、progress、stage-status 同步收口

## 十三、这套方法论的边界

这套方法论擅长解决：

- 工程型 RAG 问题
- 检索与拒答链路问题
- 配置 / 索引 / 运行时交叉问题

它不直接替代：

- 模型能力评估
- 语义标注本身是否合理
- 长期产品体验研究

一句话说：

**它是“把问题定位清楚并安全修掉”的方法，不是“拍脑袋调参求玄学提升”的方法。**
