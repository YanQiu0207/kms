# KMS 提示词

当用户要求查询个人知识库时，使用本地 `kms-api`：

- 地址：`http://127.0.0.1:49153`
- 协议：HTTP `curl`
- 不使用 MCP

## 规则

1. 检索资料时优先调用 `POST /search`。
2. 需要生成回答时优先调用 `POST /ask`。
3. 若 `/ask` 返回 `abstained=true`，直接输出：`资料不足，无法确认。`
4. 若 `/ask` 返回 `abstained=false`，严格依据返回的 `prompt` 和 `sources` 生成答案。
5. 如需校验引用可信度，调用 `POST /verify`。

## 常用命令

索引：

```powershell
curl.exe -s http://127.0.0.1:49153/index `
  -H "Content-Type: application/json" `
  -d "{\"mode\":\"incremental\"}"
```

搜索：

```powershell
curl.exe -s http://127.0.0.1:49153/search `
  -H "Content-Type: application/json" `
  -d "{\"queries\":[\"混合检索 优势\",\"为什么不能只做向量检索\"],\"recall_top_k\":20,\"rerank_top_k\":6}"
```

问答：

```powershell
curl.exe -s http://127.0.0.1:49153/ask `
  -H "Content-Type: application/json" `
  -d "{\"question\":\"为什么个人知识库不能只做向量检索？\",\"queries\":[\"为什么个人知识库不能只做向量检索？\",\"混合检索 优势\"],\"rerank_top_k\":6}"
```

校验：

```powershell
curl.exe -s http://127.0.0.1:49153/verify `
  -H "Content-Type: application/json" `
  -d "{\"answer\":\"混合检索结合了词法与语义检索的优势 [abc]。\",\"used_chunk_ids\":[\"abc\"]}"
```

健康检查：

```powershell
curl.exe -s http://127.0.0.1:49153/health
curl.exe -s http://127.0.0.1:49153/stats
```

详细契约见 `app/adapters/reference/api.md`。
