# KMS

你正在通过本地 `kms-api` 使用个人知识库。

## 使用原则

- 只通过 HTTP API 调用，不使用 MCP。
- 需要回答问题时，先调用 `/ask`。
- 当 `/ask` 返回 `abstained=true` 时，直接回复：`资料不足，无法确认。`
- 当 `/ask` 返回 `abstained=false` 时，使用返回的 `prompt` 调用宿主模型生成最终答案。
- 回答完成后，可选调用 `/verify` 检查引用覆盖率。

## 索引

全量索引：

```bash
curl -s http://127.0.0.1:49153/index ^
  -H "Content-Type: application/json" ^
  -d "{\"mode\":\"full\"}"
```

增量索引：

```bash
curl -s http://127.0.0.1:49153/index ^
  -H "Content-Type: application/json" ^
  -d "{\"mode\":\"incremental\"}"
```

## 检索

```bash
curl -s http://127.0.0.1:49153/search ^
  -H "Content-Type: application/json" ^
  -d "{\"queries\":[\"为什么个人知识库不能只做向量检索？\",\"混合检索 优势\"],\"recall_top_k\":20,\"rerank_top_k\":6}"
```

## 问答

```bash
curl -s http://127.0.0.1:49153/ask ^
  -H "Content-Type: application/json" ^
  -d "{\"question\":\"为什么个人知识库不能只做向量检索？\",\"queries\":[\"为什么个人知识库不能只做向量检索？\",\"混合检索 优势\"],\"rerank_top_k\":6}"
```

## 校验

```bash
curl -s http://127.0.0.1:49153/verify ^
  -H "Content-Type: application/json" ^
  -d "{\"answer\":\"混合检索结合了词法与语义检索的优势 [abc]。\",\"used_chunk_ids\":[\"abc\"]}"
```

## 探活

```bash
curl -s http://127.0.0.1:49153/health
curl -s http://127.0.0.1:49153/stats
```

API 详细契约见 `app/adapters/reference/api.md`。
