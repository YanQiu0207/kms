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
- 当前后续重点：
  - 扩 hard case benchmark
  - 持续观察 rerank 热路径耗时
