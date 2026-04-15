# Real10 Regression Eval

## Goal

- 基于 3 组真实数据集各 10 条用例，验证 `kms-api` 在真实冷启动后的 `/health`、`/stats`、`/search`、`/ask` 行为。
- 确认“旧进程掩盖问题”是否成立。
- 若发现冷启动回归，优先在 vendor 防腐层修复。

## Scope

- 数据集：
  - `eval/benchmark.ai.real10.jsonl`
  - `eval/benchmark.distributed.real10.jsonl`
  - `eval/benchmark.game.real10.jsonl`
- 接口：
  - `GET /health`
  - `GET /stats`
  - `POST /search`
  - `POST /ask`
- 额外验证：
  - 冷启动是否依赖 Hugging Face 在线元数据探测

## Deliverables

- 回归结果快照：
  - `eval/results/benchmark.ai.real10.http.result.json`
  - `eval/results/benchmark.distributed.real10.http.result.json`
  - `eval/results/benchmark.game.real10.http.result.json`
  - `eval/results/real10.http.run.summary.json`
- 冷启动修复：
  - `app/vendors/flag_embedding.py`
  - `tests/test_vendor_boundaries.py`

## Acceptance

- 默认环境下旧进程已杀掉后，`scripts/start_kms.py` 能成功启动服务。
- 30 条真实用例可通过 live API 批量跑完。
- 启动期不再因为缓存已存在的模型触发 Hugging Face SSL 探测失败。

## Risks

- 当前结果仍显示部分误拒答与个别召回漏检，后续需单独处理检索/拒答阈值。
