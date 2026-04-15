# Problems

## 2026-04-15 obs-local Requests Feed 不实时更新

### 现象

`mykms` 已经正常写入新日志，`obs-local` 后端也已 ingest 并 flush，直接订阅 `/api/stream` 能看到新请求事件，但前端 `Requests Feed` 仍停留在旧数据，例如 `04/15 22:20:46` 的 `POST /ask`。

### 排查结论

问题不在 `mykms`，也不在 `obs-local` 后端推送，更不在 Vite 代理。

- `4174/api/requests` 返回的数据是新的，说明代理下普通 API 没有陈旧缓存问题。
- `49154/api/stream` 和 `4174/api/stream` 都能收到同一个非空 `stream.batch`。
- `stream.batch` 中实际包含 `health.updated`、`overview.updated`、`requests.updated`、`errors.updated`、`stages.updated`。

### 根本原因

前端对 `stream.batch` 的 wire format 解析错了。

后端在 [obs-local/app/web.py](/E:/github/mykms/obs-local/app/web.py:443) 到 [obs-local/app/web.py:452](/E:/github/mykms/obs-local/app/web.py:452) 中发送的 `stream.batch`，`data` 本身就是：

- `count`
- `topics`
- `items`

但前端在 [obs-local/frontend/src/stores/observability.ts](/E:/github/mykms/obs-local/frontend/src/stores/observability.ts:491) 到 [obs-local/frontend/src/stores/observability.ts:497](/E:/github/mykms/obs-local/frontend/src/stores/observability.ts:497) 中把它错误地当成 `StreamEnvelope<StreamBatchPayload>`，继续读取 `envelope.payload`。对真实 `stream.batch` 来说，这个字段不存在，结果导致整批更新被直接丢弃。

### 影响

- batched 的 `requests.updated` 不会进入 `state.requests`
- 首页实时区块看起来像“后端没推”
- 初始快照之后的实时刷新主路径失效

### 证据

- 真实抓包显示 `49154/api/stream` 与 `4174/api/stream` 都收到：
  - `event = stream.batch`
  - `count = 5`
  - `topics = ["health.updated", "overview.updated", "requests.updated", "errors.updated", "stages.updated"]`
- 因此前端 stale 不是后端无事件，而是前端收到 batch 后没有正确展开

### 修复方向

- 前端 `handleStreamMessage()` 在处理 `stream.batch` 时，应将 `message.data` 直接按 `StreamBatchPayload` 解析
- 不应再把 `stream.batch` 当成外层仍带 `payload` 字段的 `StreamEnvelope`

