# KMS API 契约

基础地址：`http://127.0.0.1:49153`

## `GET /health`

用途：探活。

响应字段：

- `status`
- `service`
- `version`
- `timestamp`，格式：`YYYY-MM-DD HH:MM:SS.mmm`，使用系统本地时间

## `GET /stats`

用途：查看当前索引与模型配置。

响应字段：

- `document_count`
- `chunk_count`
- `source_count`
- `embedding_model`
- `reranker_model`
- `chunker_version`
- `sqlite_path`
- `chroma_path`
- `hf_cache`
- `device`
- `dtype`
- `last_indexed_at`，格式：`YYYY-MM-DD HH:MM:SS.mmm`，使用系统本地时间

## `POST /index`

用途：执行全量或增量索引。

请求体：

```json
{
  "mode": "incremental"
}
```

响应体：

```json
{
  "mode": "incremental",
  "indexed_documents": 12,
  "indexed_chunks": 84,
  "skipped_documents": 3,
  "deleted_documents": 1,
  "message": "完成增量索引"
}
```

## `POST /search`

用途：只返回检索证据，不装配 prompt。

请求体：

```json
{
  "queries": [
    "为什么个人知识库不能只做向量检索？",
    "混合检索 优势"
  ],
  "recall_top_k": 20,
  "rerank_top_k": 6
}
```

响应体：

```json
{
  "results": [
    {
      "chunk_id": "abc",
      "file_path": "notes/rag.md",
      "location": "rag.md:12-18",
      "title_path": ["RAG", "Hybrid Retrieval"],
      "text": "混合检索结合了词法与语义检索的优势。",
      "score": 0.81,
      "doc_id": "doc-1"
    }
  ],
  "debug": {
    "queries_count": 2,
    "recall_count": 10,
    "rerank_count": 6
  }
}
```

## `POST /ask`

用途：检索、精排、拒答判断、prompt 装配。

请求体：

```json
{
  "question": "为什么个人知识库不能只做向量检索？",
  "queries": [
    "为什么个人知识库不能只做向量检索？",
    "混合检索 优势"
  ],
  "recall_top_k": 20,
  "rerank_top_k": 6
}
```

响应体：

```json
{
  "abstained": false,
  "confidence": 0.78,
  "prompt": "......",
  "sources": [
    {
      "ref_index": 1,
      "chunk_id": "abc",
      "file_path": "notes/rag.md",
      "location": "rag.md:12-18",
      "title_path": ["RAG", "Hybrid Retrieval"],
      "text": "混合检索结合了词法与语义检索的优势。",
      "score": 0.81,
      "doc_id": "doc-1"
    }
  ],
  "abstain_reason": null
}
```

约定：

- 当 `abstained=true` 时，宿主直接输出“资料不足，无法确认。”。
- 当 `prompt=""` 时，不应再调宿主 LLM。
- 玩家展示来源时应优先使用 `location + title_path`，不要直接暴露 `chunk_id`。
- `chunk_id` 仍保留在 API 中，供机器侧调用 `/verify` 使用。

## `POST /verify`

用途：校验宿主生成答案的引用覆盖率。

请求体：

```json
{
  "answer": "混合检索结合了词法与语义检索的优势 [abc]。",
  "used_chunk_ids": ["abc"]
}
```

响应体：

```json
{
  "citation_unverified": false,
  "coverage": 0.82,
  "details": [
    {
      "chunk_id": "abc",
      "matched_ngrams": 14,
      "total_ngrams": 17
    }
  ]
}
```
