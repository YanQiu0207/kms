# M12 Retrieval Hot-Path Batching

## Goal

- Reduce `embedding.encode` and `reranker.score` latency on multi-query requests.
- Keep retrieval quality unchanged on the existing real benchmark suites.

## Scope

- Batch semantic query embedding for multi-query search.
- Batch semantic Chroma query for multi-query search.
- Add configurable batch sizing for embedding and reranker model calls.
- Keep current multi-query rerank semantics unchanged.

## Non-Goals

- Do not remove query expansion.
- Do not change recall / rerank / abstain thresholds.
- Do not collapse multi-query rerank into single-query rerank.

## Acceptance

- Existing targeted tests pass.
- New regression tests cover batched semantic query path and reranker batch-size behavior.
- `benchmark.ai.real10.jsonl`
- `benchmark.distributed.real10.jsonl`
- `benchmark.game.real10.jsonl`
  all keep baseline quality metrics:
  - `recall_at_k`
  - `mrr`
  - `abstain_accuracy`
  - `false_abstain_rate`
  - `false_answer_rate`

## Risks

- Batched semantic query handling may misread Chroma multi-query payload shape.
- Passing `batch_size` into vendor models may break older signatures and must fallback cleanly.
- Any semantic batching bug can silently hurt `rewrite` cases by returning the wrong query-to-result mapping.
