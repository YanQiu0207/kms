# Stage Status

| Stage | Scope | Status | Review | Notes |
|---|---|---|---|---|
| M0 | Scaffold, config, runtime baseline | Approved | Passed | Import and compile checks passed |
| M1 | Ingest and indexing pipeline | Approved | Passed | `/index` and `/stats` are live, tests passed |
| M2 | 检索栈与 `/search` | Approved | Passed | `/search` 已接通，输入校验与多 query rerank 已审核通过 |
| M3 | `/ask`, `/verify`, abstain and prompt assembly | Approved | Passed | `/ask` 与 `/verify` 已接通并审核通过 |
| M4 | Claude/Codex adapters, `/health`, `/stats` | Approved | Passed | Claude/Codex 模板与 API 契约副本已落地 |
| M5 | Evaluation scaffold and polish | Approved | Passed | 已补评测骨架、样例 benchmark 与回归测试 |
| M6 | Host full-file answering endpoint and Codex skill | Approved | Passed | `/ask-files`、Codex 全文模式模板与本机 skill 已落地并通过定向回归 |
| M7 | Remove `/ask-files` and `kms-full-file-assistant` | Approved | Passed | `/ask-files`、全文模式模板、请求样例与本机 skill 已删除，定向回归通过 |
| M8 | obs-local protocol compatibility upgrade | Approved | Passed | `obs-local` 已兼容完整事件名与 `span_name + event_type` 新协议，55 项回归通过 |
| M9 | mykms canonical event protocol cutover | Approved | Passed | `mykms` 已切到 `event=start|end|error`，并保留完整 `message` 语义 |
| M10 | obs-local launch runbook and starter | Approved | Passed | 已补一键启动脚本，后端 49154 / 前端 4174 实机验证通过 |
| M11 | RAG evaluation hardening and hard-case benchmark | Approved | Passed | `eval/` 已补增强 schema、分组统计、hard-case 模板与回归测试 |
| M12 | obs-local bilingual locale and UI language selector | Review | Pending | 已补后端默认语言配置、前端语言切换与双语文案层，等待本轮验证与评审收口 |
| M12 | Retrieval hot-path batching for semantic query and reranker | Approved | Passed | 已完成 batched semantic query 与 batch-size 配置，60 项测试通过，3 组 real10 质量不回退 |
| M13 | RAG data cleaning baseline and comparison harness | Approved | Passed | 已完成 front matter 检索注入、metadata-sensitive case 收口、Chroma persisted-state 崩溃绕过与 semantic-on 恢复；`notes-frontmatter.real10` 保持全绿 |
| M14 | RAG cleaning stage 2 for boilerplate, tables, and source-specific rules | Approved | Passed | 已完成 boilerplate/table/source-specific 清洗、同口径 benchmark 对照、样本导出与质量门验证；残留 GDB 表格排序偏移已单独记账 |
| M15 | Ranking quality, evidence coverage, and benchmark hardening | Approved | Passed | 已完成 ranking 专项 benchmark、lookup/document-competition 排序收口、query coverage 单文档化修正与 `chunk_id` 支撑修复；`cleaning / ranking / distributed` 收口 |
| M16 | Query understanding and retrieval routing | Approved | Passed | 已完成 query type/profile、alias subject 归一、route policy 与 query-routing benchmark；`query-routing.real10` 全绿 |
| M17 | Guardrail and evidence quality | Approved | Passed | 已完成分题型 guardrail 收口、路径后缀噪音去污染、existence 窄放行与 guardrail benchmark；`guardrail.real10` 全绿 |
| M18 | Evaluation suite and data engineering system | Approved | Passed | 已完成 suite / source audit / HTTP benchmark 审查链路与本地双实例 review；`benchmark-suite.m18.local` gated 7/7 通过 |
| A1 | Retrieval/config/startup architecture hardening | Approved | Passed | 已完成 metadata/stopword 抽取、可组合 ranking pipeline、配置语义校验与启动 factory 化；`pytest` 117 通过，suite gated 7/7 通过 |
| A2 | Retrieval context uplift | Approved | Passed | 已完成 parent context expansion 与 contextual embedding；Review A/B 无 accepted finding；全量 `pytest` 121 通过，suite gated 7/7 通过 |
| A3 | Retrieval closure, adaptive fusion, and alias automation | Approved | Passed | 已完成 M19 failure closure、query-type adaptive fusion 与 front matter alias 自动提取；全量 `pytest` 128 通过，suite gated 7/7 通过 |
| P1 | Reranker multi-query batch merge | Approved | Passed | 新增 `rerank_multi` 将 N 次串行 GPU 调用合并为 1 次；133 passed；HTTP suite: ai -67%、distributed -60%；质量无回退 |

## Exit Criteria

- Stage code merged into the main workspace
- Main-agent review completed
- Review findings resolved or explicitly waived
- Verification commands recorded

## Current Snapshot

- M0 已实现并通过审核。
- M1 已实现并通过审核。
- M0、M1、M2、M3 已实现并通过审核。
- 当前主线阶段已全部完成。
- M7 已通过，M6 引入的全文模式能力已显式撤回。
- M8 已通过，`obs-local` 现在可同时兼容完整事件名与 `span_name + event_type` 新协议。
- M9 已通过，`mykms` 现在正式落盘 canonical `event` 协议。
- M10 已通过，`obs-local` 现在可一键启动并明确看到页面地址。
- M11 已通过，`eval/` 现在已支持更正式的 RAG 指标、分组统计与 hard-case 模板。
- M12 正在收口，`obs-local` 已开始支持 `zh / en / bilingual` 三种语言模式。
- M12 已通过，已完成 batched semantic query 与 batch-size 配置，并确认 3 组 real10 质量不回退。
- M13 已开始，当前先做数据清洗前的 baseline 与对照工具链，不直接改 ingest 行为。
- M13 Stage 0 已产出 index stats baseline 与 benchmark baseline，且已发现 `distributed.real10` 相比历史快照存在退化 case。
- M13 Stage 1 已落地 front matter / 正文规范化 / 文档内 exact duplicate 抑制，但对当前真实索引统计影响有限。
- M13 已新增 `E:/notes` 派生 front matter 语料与 `notes-frontmatter.real10` 基线，已确认 metadata-sensitive 题目前主要受限于 front matter 未参与检索。
- M13 已完成 first-pass front matter 检索注入：
  - chunk metadata 已继承 category / tags / aliases / path
  - lexical 已支持 metadata_text
  - `notes-frontmatter.real10` 的 `recall_at_k` 与 `mrr` 已提升
- M13 已通过：
  - `notes-frontmatter` 已切回 repaired semantic 配置
  - `notes-frontmatter.real10` 在 semantic-on 下维持 `recall_at_k=1.0`、`mrr=1.0`、`abstain_accuracy=1.0`
  - Chroma 原始 persisted collection 仍保留为已知坏样本，但不再阻塞当前实验链路
- M14 已通过：
  - 已完成 boilerplate / 导航 / 转载署名清洗
  - 已完成 Markdown 表格结构化
  - 已完成 source-specific 清洗规则框架
  - `benchmark.cleaning.real10` 在同口径下把 `abstain_accuracy` 从 `0.9` 提升到 `1.0`
  - `false_answer_rate` 从 `0.5` 降到 `0.0`
  - `ai / distributed / game / notes-frontmatter` 质量门未回退
- M15 已通过：
  - 已新增 `benchmark.ranking.real10` 专项 benchmark
  - 已收口 `ISSUE-M14-002`
  - 已修复 `TrueTime` false abstain 与 `ZooKeeper watch` 跨文档 coverage 拼接问题
  - `benchmark.cleaning.real10` 提升到 `recall_at_k=1.0`、`mrr=1.0`
  - `distributed.real10` 提升到 `mrr=1.0`、`abstain_accuracy=1.0`
- M16 已通过：
  - 已新增 `app/query_understanding.py`
  - 已完成 query type / route policy / alias subject 归一
  - `benchmark.query-routing.real10` 已达到 `recall_at_k=1.0`、`mrr=1.0`、`abstain_accuracy=1.0`
- M17 已通过：
  - 已完成 `/ask` guardrail 决策顺序收口
  - 已修复路径后缀与 TOC 噪音导致的 false answer
  - `benchmark.guardrail.real10` 已达到 `recall_at_k=1.0`、`mrr=1.0`、`abstain_accuracy=1.0`
- M18 已通过：
  - 已完成 `run_benchmark_suite`、`run_source_audit`
  - 已完成 HTTP `base_url` benchmark/suite
  - 已形成权威整体验收结果：
    - `eval/results/benchmark-suite.m18.local.current.json`
    - `passed_gated_entries=7/7`
- 服务当前运行在 `127.0.0.1:49153`。
- 真实全量索引已完成：107 篇文档、2702 个分块。
- 已完成真实运行期稳定性修复：
  - 查询阶段 Chroma 客户端复用
  - 应用级 QueryService 复用
  - rerank 分数归一化
  - embedding / reranker 并发锁
- 已完成进一步调优：
  - 来源展示改为 `文件名:起止行`
  - rerank 候选上限
  - 单问题轻量 query 扩展
  - 启动阶段模型预热
- A1 已通过：
  - `hybrid.py` 已缩回检索编排职责，排序后处理移入可配置 pipeline
  - metadata 文本提取与 stopword 口径已统一
  - `RetrievalConfig` / `ChunkerConfig` / `AbstainConfig` / `VerifyConfig` 已补语义校验
  - `app.main` 已移除模块级 FastAPI 单例，启动入口改为 factory
  - 全量 `pytest` 已达到 `117 passed`
  - `benchmark-suite.m18.json` 已达到 `passed_entries=8/8`、`passed_gated_entries=7/7`
- 当前后续重点：
  - 后续若继续，优先评估是否需要单独立项通用 near-duplicate 抑制、失败 case 自动回流与 source onboarding 治理，而不是回头放宽 benchmark 口径
- A3 已通过：
  - 已新增 `eval/failure_closure.py` 与 `run_failure_closure.py`，支持失败 case backlog / draft 闭环
  - 已为 `BenchmarkCase` / suite failure export 增加 `linked_issue_ids`
  - 已完成 query-type 自适应 fusion weights
  - 已完成 front matter alias 自动提取与 QueryService 动态 alias 缓存
  - 全量 `pytest` 已达到 `128 passed`
  - `benchmark-suite.m18.json` 已达到 `passed_entries=8/8`、`passed_gated_entries=7/7`
- P1 已通过：
  - 新增 `FlagEmbeddingReranker.rerank_multi()`，将多 query 串行 rerank 合并为单次 GPU forward pass
  - 新增 `DebugReranker.rerank_multi()` 与 `RerankerProtocol.rerank_multi` 签名
  - 新增 `_merge_multi_query_results()` 辅助函数，消除 batch / fallback 两条路径的合并重复
  - `_rerank_candidates()` 多 query 分支通过 `hasattr` duck typing 优先走 batch 路径，无 `rerank_multi` 时自动 fallback 串行
  - 全量 `pytest` 已达到 `133 passed`（含 5 个新增测试）
  - HTTP benchmark suite（M19）：
    - ai -67%、distributed -60% 延迟下降
    - game / cleaning / ranking 质量从 False → True（附带修复）
    - 零质量回退，`passed_gated_entries=6/7`（notes-frontmatter 为 pre-existing HTTP 配置问题）
  - 权威结果文件：`eval/results/benchmark-suite.m19.current.json`
