# RAG 评测方案原理

本文说明 `mykms` 当前 RAG 评测方案的设计原理、指标含义与结果解释方式。

相关实现入口：

- 评测执行器：[eval/benchmark.py](/E:/github/mykms/eval/benchmark.py)
- 评测使用说明：[eval/README.md](/E:/github/mykms/eval/README.md)

## 为什么不能只看“答得像不像”

`mykms` 的 `/ask` 当前返回的是：

- `abstained`
- `confidence`
- `prompt`
- `sources`

也就是说，它更像“证据包与拒答控制器”，不是最终答案生成器。

因此，如果只看宿主模型最后一句话“像不像答案”，会混淆三件本来应该拆开的事：

1. 检索有没有找到对的证据。
2. 系统在没证据时有没有稳住拒答。
3. 返回给宿主模型的 `sources + prompt` 是否足够支撑回答。

所以当前评测方案分成 3 层：

1. 检索层
2. 拒答层
3. 证据包层

最终答案层暂不纳入自动评测主路径。

## 评测分层

### 1. 检索层

目标：确认预期文档或预期 chunk 能否进入检索结果，并尽量排到前面。

核心指标：

- `recall_at_k`
- `mrr`

含义：

- `recall_at_k` 高，说明“有没有找到”问题较少。
- `mrr` 高，说明“虽然找到了，但排得太后”问题较少。

它主要防的是：

- 明明知识库里有答案，但检索没召回。
- 召回到了正确文档，但前排是干扰项。

### 2. 拒答层

目标：当语料里没有答案，或者证据不够时，不要伪造回答。

核心指标：

- `abstain_accuracy`
- `abstain_precision`
- `abstain_recall`
- `false_abstain_rate`
- `false_answer_rate`

含义：

- `abstain_precision` 低：系统很爱拒答，但其中很多其实不该拒答。
- `abstain_recall` 低：该拒答时没拒住，容易误答。
- `false_abstain_rate` 高：有答案也不敢答，保守过头。
- `false_answer_rate` 高：没答案也继续答，风险更高。

它主要防的是两类经典 RAG 问题：

- 假阳性：搜到“有点像”的内容就硬答。
- 假阴性：其实有证据，但 guardrail 或阈值太严导致误拒答。

### 3. 证据包层

目标：不仅要检索命中，还要让 `/ask.sources` 真正覆盖预期来源和关键术语。

核心指标：

- `evidence_hit_rate`
- `evidence_source_recall`
- `source_count_satisfaction_rate`
- `expected_term_coverage`

含义：

- `evidence_hit_rate`：`/ask.sources` 是否至少命中一个预期来源。
- `evidence_source_recall`：如果预期有多个来源，返回证据覆盖了多少。
- `source_count_satisfaction_rate`：是否满足 case 里声明的最少来源数。
- `expected_term_coverage`：返回证据里是否真的出现了关键术语。

为什么需要这一层：

- 检索结果里命中文档，不代表 `/ask` 最终给宿主模型的证据也足够。
- 文档命中了，不代表关键问题点被覆盖到了。
- 多文档题里，只返回一份来源通常不够。

所以这一层主要防：

- “检索看起来对，实际证据包不够用”
- “答题依赖多来源，但只给了单来源”
- “命中文档但没命中关键术语”

## 为什么要加 `case_type` 和 `tags`

单看总体均值容易掩盖问题。

例如：

- `lookup` 题可能很好
- `rewrite` 题明显差
- `distractor` 题容易误答
- `multi_doc` 题来源不够

所以评测结果必须支持按：

- `case_type`
- `tags`

分组统计。

这样能回答：

- 系统到底是“整体都一般”，还是“只有某类题掉点”。
- 问题是出在改写鲁棒性，还是出在多文档聚合，还是出在拒答。

## 为什么 hard-case 不能只做“完全无关题”

完全无关题当然应该拒答，但这类题太容易，不能代表真实风险。

真正危险的是“半相关误导题”：

- 文档里提到了相关术语，但没提问题中的关键条件。
- 两篇文档都提到同一个词，但语义不同。
- 标题很像，但正文并不支持这个结论。

因此 hard-case 至少要覆盖：

- `rewrite`
- `multi_doc`
- `distractor`
- `abstain`

这些题型共同决定系统是不是“真能用”，而不是“关键词撞对了就能用”。

## 当前方案的边界

当前方案仍然有明确边界：

- 它评的是 `mykms` 本身，不是宿主模型最终答案质量。
- `expected_term_coverage` 是代理指标，不是事实正确率。
- `evidence_source_recall` 反映的是来源覆盖，不是答案完整度。

所以如果后续要继续升级，下一步应该是：

1. 基于 `/ask.prompt + /ask.sources` 生成宿主最终答案。
2. 增加答案级评测：
   - 事实正确率
   - 引用正确率
   - 答案完整率
   - 证据外扩写率

## 如何解读结果

建议按这个顺序看结果：

1. 先看 `false_answer_rate`
   - 这是风险最高的指标。
2. 再看 `false_abstain_rate`
   - 这决定系统是不是过度保守。
3. 再看 `recall_at_k` 与 `mrr`
   - 这决定检索基础盘。
4. 最后看 `evidence_*` 与 `expected_term_coverage`
   - 这决定证据包是否真的可用。

如果总体分数还行，但 `by_type` / `by_tag` 明显掉点，优先处理掉点题型，不要被总体平均值误导。

## 目前仓库里的落地点

方案已落地到以下文件：

- 核心实现：[eval/benchmark.py](/E:/github/mykms/eval/benchmark.py)
- 使用说明：[eval/README.md](/E:/github/mykms/eval/README.md)
- 样例集：[eval/benchmark.sample.jsonl](/E:/github/mykms/eval/benchmark.sample.jsonl)
- hard-case 模板：[eval/benchmark.hardcase.template.jsonl](/E:/github/mykms/eval/benchmark.hardcase.template.jsonl)
- 测试：[tests/test_eval_benchmark.py](/E:/github/mykms/tests/test_eval_benchmark.py)
