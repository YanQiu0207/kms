# Session Handoff

## Approved State

- M0 completed and approved.
- FastAPI scaffold, config loader, schema layer, package skeleton, and baseline config file are in place.
- Main review already fixed:
  - package export gaps
  - `app.answer` boundary drift
  - local `pydantic` v1/v2 compatibility issue

## Verified Commands

- `python -m py_compile app\__init__.py app\config.py app\schemas.py app\main.py app\ingest\__init__.py app\ingest\contracts.py app\store\__init__.py app\store\contracts.py app\retrieve\__init__.py app\retrieve\contracts.py app\answer\__init__.py app\answer\contracts.py app\adapters\__init__.py app\adapters\contracts.py`
- `python -c "from app.main import app; print(app.title); print(app.state.config.server.port)"`

## 当前状态

- M0、M1、M2、M3、M4、M5 已完成并审核通过。
- `/index`、`/stats`、`/search`、`/ask`、`/verify` 已接入真实实现。
- Claude/Codex 适配模板、API 契约副本、评测骨架均已落地。
- `dev-plan` 目录已统一转为中文。
- 服务当前运行在 `http://127.0.0.1:49153`。
- 旧端口 `49152` 已停用。
- 文档源仍为 `E:\work\blog`。
- `.venv` 中已安装真实依赖：`torch`、`FlagEmbedding`。
- 已修复 `FlagEmbedding` 与 `transformers` 的版本兼容问题。
- 已成功执行真实全量索引：
  - `document_count = 107`
  - `chunk_count = 2702`
  - `embedding_model = BAAI/bge-m3`
  - `reranker_model = BAAI/bge-reranker-v2-m3`
  - `device = cuda`
- 当前服务启动策略已改为：
  - `warmup_on_startup = true`
  - 启动时预热 embedding / reranker，避免首个查询吃到完整冷启动
- 当前玩家可读来源展示已改为：
  - `文件名:起止行`
  - 不再在 prompt / 来源列表里暴露 `chunk_id`
  - API 内部仍保留 `chunk_id` 供 `/verify` 使用
- 已新增第三方库防腐层：
  - `app/vendors/chroma.py`
  - `app/vendors/flag_embedding.py`
  - `app/vendors/jieba_tokenizer.py`
  - 业务层不再直接依赖 `chromadb` / `FlagEmbedding` / `jieba`

## 下一步

1. 若继续提准，优先扩充 benchmark hard case，验证自动 query 扩展是否稳定增益。
2. 评估是否给 `/search` 增加显式“低置信度”标记，而不仅是过滤。
3. 若继续提速，可考虑更细粒度 profile `bge-reranker-v2-m3` 的 batch 行为与候选数上限。
4. 如需继续增强，可把 benchmark 跑批接到 CI 或夜间任务。

## 本轮完成

- 完成 `app/retrieve/**`、`app/answer/**` 与 `app/services/querying.py` 的主集成。
- 修复多 query rerank、top_k 校验、prompt 字段映射、RRF 来源标记等审核问题。
- 新增适配模板、API 契约副本与评测骨架。
- 当前测试总计 `20 passed`。
- 端口已从 `49152` 迁移到 `49153`，代码、配置与文档均已同步。
- 已启动真实服务并完成全量索引验证。
- 已修复真实查询阶段的 Chroma 客户端复用问题，`/search`、`/ask` 不再因 `PersistentClient` 报错返回 `500`。
- 已将 `QueryService` 改为应用级复用，避免每次请求重建查询链路。
- 已将真实 reranker 分数拆分为：
  - `rerank_raw_score`：保留模型原始分数
  - `score` / `rerank_score`：归一化到 `0..1`，供 `/search` 输出与 `/ask` guardrail 使用
- 已为 embedding 与 reranker 增加进程内锁，降低并发请求时的模型调用不稳定问题。
- 已为 `/search` 增加低分结果过滤：
  - `retrieval.min_output_score = 0.1`
  - 对明显无关的低分结果直接不返回，减少偏题展示
- 已把 rerank 候选上限落到配置：
  - `retrieval.rerank_candidate_limit = 24`
  - 热路径里不再对过多候选做 cross-encoder 精排
- 已为单问题检索补充轻量 query 扩展：
  - 原问题
  - 去标点紧凑变体
  - 关键词变体
- 已把服务启动改为模型预热：
  - 首次启动会更慢
  - 启动完成后的首个查询显著更稳
- 已把来源展示改成 `文件名:起止行`，并将行号透传到 chunk 元数据与检索结果
- 已补 benchmark 执行脚本与 3 份真实语料基准集：
  - `eval/benchmark.ai.jsonl`
  - `eval/benchmark.distributed.jsonl`
  - `eval/benchmark.game.jsonl`
- 已生成 benchmark 结果文件：
  - `eval/results/benchmark.ai.result.json`
  - `eval/results/benchmark.distributed.result.json`
  - `eval/results/benchmark.game.result.json`
- 已完成真实验收：
  - 对“语料中存在”的问题：`/ask` 可返回高置信证据包
  - 对“语料中不存在”的问题：`/ask` 会稳定拒答，而不是超时或报错
- 当前测试总计 `29 passed`。
- 当前测试总计 `32 passed`。
- 当前测试总计 `34 passed`。

## 运行快照

- 健康检查：
  - `curl.exe -s http://127.0.0.1:49153/health`
- 统计信息：
  - `curl.exe -s http://127.0.0.1:49153/stats`

## 已知问题

- `/search` 对“语料中不存在”的问题已改为优先返回空结果；后续仍可考虑增加更细的低置信标记，而不是只靠过滤。
- 真实语料 `E:\work\blog` 中几乎没有“个人知识库 / 混合检索 / 向量检索”主题内容，因此这类问题更适合作为拒答验收，而不是正确回答验收。
- 当前热路径主要耗时仍然集中在 rerank；实测 warm query 通常在 `0.6s ~ 1.0s`，而不是词法或向量召回。
