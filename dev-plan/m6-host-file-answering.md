# M6 Host Full-File Answering

## Goal

新增一个宿主专用接口，让 `kms-api` 返回按检索结果挑选出的候选文件，由 Codex skill 在本地读取全文后作答；保留现有 `/ask` 的 `prompt + sources` 语义不变。

## Scope

- 新增 HTTP 接口：
  - 输入沿用 `question + queries + top_k`
  - 输出 `abstained + confidence + files + abstain_reason`
- 服务层复用现有检索、拒答与 query coverage 逻辑
- 从 SQLite `documents` 表读取文档级元数据和全文摘要
- 新增 Codex skill，指导宿主调用新接口并读取本地文件
- 补充测试与 API 契约

## Non-Goals

- 不修改现有 `/ask` 行为
- 不在服务端把整篇文档直接塞进 prompt
- 不要求通用宿主一定具备本地文件读取能力

## API Draft

建议接口：`POST /ask-files`

请求体：

- `question`
- `queries`
- `recall_top_k`
- `rerank_top_k`
- `max_files`

响应体：

- `abstained`
- `confidence`
- `files[]`
  - `ref_index`
  - `document_id`
  - `file_path`
  - `file_name`
  - `title_path`
  - `score`
  - `location`
  - `hit_text`
- `abstain_reason`

## Flow

1. 复用现有 `/ask` 的检索与拒答判定。
2. 通过命中的 chunk 去重选出 top N 文档。
3. 从 SQLite 文档表读取文档，返回文件路径与文档级元数据。
4. Skill 调用新接口后，在本地读取返回的绝对路径文件，再基于全文回答。

## Risks

- 宿主读全文会增加 token，需要在 skill 侧限制文件数量。
- 已索引文件可能已被删除；接口应返回仍可定位的文件，skill 侧仍需处理读文件失败。
- 文档很长时，skill 侧不能无脑读取太多文件。
