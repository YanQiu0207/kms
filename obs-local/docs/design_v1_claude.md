# design_v1 评审意见（by Claude）

评审对象：[`design_v1.md`](./design_v1.md)
评审时间：2026-04-15
评审方法：对照 mykms 现有代码（[`app/observability.py`](../../app/observability.py)、[`app/main.py`](../../app/main.py)、[`app/timefmt.py`](../../app/timefmt.py)）与真实落盘日志（`.run-logs/kms-api.log`）逐项核对。

整体判断：方向（独立服务 + 拉模式 + 最小协议）是正确的，但**设计文档对 mykms 当前日志的实际形态估计得过于乐观**，存在多处"协议层"的事实性偏差；其中一部分已经在后续开发中补齐，但仍有若干关键缺口会直接影响 MVP 在真实日志上的正确性。下面按严重度降序排列。

> **修订说明（2026-04-15）**：用户确认 "希望是一个合理的实现，不是最小成本的实现，可以要求 mykms 做相应调整"。因此本文不再追求 "obs-local 单方面兜底"，而是**以协议正交为先**：需要 mykms 侧改动的地方直接要求上游改，以避免把业务特例写进通用协议。所有涉及 mykms 配合的建议都用 **[需 mykms 配合]** 标注，并汇总在文末 §六。
>
> 同时建议协议整体向 [OpenTelemetry 语义约定](https://opentelemetry.io/docs/specs/semconv/)（trace_id / span_id / parent_span_id / span.kind / span.status）对齐，而不是另造一套 "request_id + event" 模型。这样即便 obs-local 将来被替换为 Tempo / Jaeger / OTel Collector，协议也不必破。
>
> **进展同步（2026-04-15 21:05）**：`mykms` 已补一轮观测兼容性修正：
> - [`app/observability.py`](../../app/observability.py) 已显式写入 `schema_version=1`
> - `timed_operation` 结束事件已统一输出 `duration_ms`，并保留兼容字段 `elapsed_ms`
> - [`app/main.py`](../../app/main.py) 的 `http.request.error` 已补 `status="error"`、`error_type` 与 `duration_ms`
>
> **进展同步（2026-04-16 00:50）**：`mykms` 已完成 canonical event 收口：
> - 落盘 `event` 已正式切到纯 `start` / `end` / `error`
> - `span_name` 独立承载业务名，如 `http.request`、`api.ask`
> - `message` 保留完整可读事件名，如 `http.request.end`
> - `obs-local` 已完成兼容，因此后续不再需要继续依赖完整事件名作为主协议
>
> 因此本文下面的结论应理解为：**面向“合理协议收口”仍然剩余的缺口**，而不是“从零开始的改造清单”。

---

## 一、阻塞级问题（会直接影响 MVP 跑通）

### 1. ~~日志格式存在新旧两代并存~~（已由用户确认忽略）

用户已确认此条可忽略（预计旧代日志会被清理或不在 MVP 窗口内）。保留编号避免后续章节错乱。

### 2. `http.request.end` 实际上没有 `status` 字段，但协议依赖它判错

design 第 4.2 节定义："`status=error` 视为错误"，第 4.1 节示例里 `http.request.end` 也带 `"status": "ok"`。

实测日志：

```json
{..."message": "http.request.end", ..."status_code": 200, "duration_ms": 2.819}
```

埋点源码 [`app/main.py`](../../app/main.py) 里 `http.request.end` 的 `log_event` 调用目前只传了 `request_id/method/path/status_code/duration_ms`，**仍然没有 `status`**。只有走 `timed_operation` 的 API 级事件（`api.ask.end` 等）才会在 finally 分支补上 `status=ok|error`（见 [`app/observability.py`](../../app/observability.py)）。

这意味着 design 里"用 `status` 判请求成败"对 `http.request.end` **压根落不下去**。

**建议（合理方案）**：
- **[需 mykms 配合]** 修 [`app/main.py`](../../app/main.py) 的 middleware，`http.request.end` 必须补上 `status="ok" if response.status_code < 400 else "error"`；这样所有 `*.end` 事件的判错语义**完全一致**（都看 `status`），不用在协议里拆分 HTTP / 阶段两套规则。
- 协议侧硬约束：**所有 `*.end` 事件必须带 `status ∈ {"ok", "error"}`**；`status_code` 只作为 HTTP 专有附加字段，不参与判错。
- `exception` 字段继续保留，作为错误详情而不是判错依据。

> 为什么不走"组合判错"：组合规则看起来"兼容面广"，但引入了协议语义的多源依赖（一个字段缺失时要去看另外三个），parser 复杂度线性上升，且**判错结果不可复现**（同一条日志在不同 parser 版本里可能得出不同结论）。协议应该让判错成为 O(1) 的本地决策。

### 3. `http.request.error` 没有配对的 `.end`，请求时间线会"断尾"

[`app/main.py`](../../app/main.py) 的 middleware 里，请求异常分支现在虽然已经把 `http.request.error` 补成了结构化事件（含 `status="error"`、`error_type`、`duration_ms`），但仍然是**只写 `http.request.error` 后 `raise`，没有再写 `http.request.end`**。

design 第 10.3 节时间线示例和 8.2 节 `RequestSummary` 都假定有 `http.request.end` 能给出 `ended_at`/`duration_ms`/`status_code`。这类异常请求在 UI 上会表现为"没有结束时间、没有状态码的僵尸请求"。

**建议（合理方案）**：
- **[需 mykms 配合]** 修 [`app/main.py`](../../app/main.py) 的 middleware：异常分支采用 `try/except/finally` 的三段式（和 [`app/observability.py`](../../app/observability.py) 的 `timed_operation` 完全同构）——`except` 块里写 `"error"` 事件带 traceback 后 raise；`finally` 块里写 `"end"` 事件带 `status="error"` / `status_code` / `duration_ms` / `error_type`。
- 协议硬约束：**`*.start` 必须且仅必须有一条 `*.end` 与之配对**；`*.error` 降级为"错误详情附加事件"，不承担生命周期边界。
- 实际日志顺序变为 `start → error → end`，和 `timed_operation` 保持一致，风格统一。

> 为什么不让 obs-local 侧 "把 `.error` 当结束事件" 兜底：生命周期语义如果由消费端重建，**任何新接入项目都要重新验证同一套规则**；让上游保证 "每个 span 必有 start+end" 是更稳的协议契约，成本也只在 mykms 一侧改 10 行代码。

### 4. 阶段嵌套未处理，stage 统计会严重重复计时

实测阶段嵌套结构（design 第 10.3 节自己给的时间线也能看出来）：

```
api.ask(635ms)
└── query.ask(635ms)
    └── retrieval.search_and_rerank(627ms)
        ├── retrieval.semantic_stage(208ms)
        └── reranker.score(367ms)
```

design 第 4.2 节"带 `duration_ms` 的 `.end` 事件视为可统计阶段"—— 按这个规则，上面 5 个阶段**全部**会被 StageStats 收录，父子耗时重复叠加；UI "阶段耗时排行" 会变成"越靠外层的阶段排名越靠前"，完全没有诊断价值。

**建议（合理方案，三选一）**：

**方案 A：完整 span 语义（OTel 对齐，推荐）**
- **[需 mykms 配合]** 在 [`app/observability.py`](../../app/observability.py) 里新增 `_span_stack: ContextVar[list[str]]`，`timed_operation` 进入时生成 `span_id`（8 字节 hex）、从栈顶读 `parent_span_id`、push；退出时 pop。每条 `.start` / `.end` / `.error` 都带 `span_id` 和 `parent_span_id`。
- 协议字段：`trace_id`（等于现在的 `request_id`，保留兼容别名）、`span_id`、`parent_span_id`、`span_name`（= 去掉 `.start/.end/.error` 后缀的基名）。
- obs-local 侧：聚合时能重建 span tree，stage 排行默认按**自耗时**（exclusive time = total - sum(children)）排序；单请求时间线可以画瀑布图而不是列表。
- 长远价值：这是 OTel 的标准模型，未来接 Tempo / Jaeger 零改造；跨 project 的 trace 串联（比如 kms-api → 下游 worker）也能自然支持。

**方案 B：仅加 `span_depth` 字段（轻量）**
- **[需 mykms 配合]** `timed_operation` 维护一个栈，只记录当前深度；每条事件带 `span_depth: int`。
- obs-local 侧按 `(request_id, span_depth)` 判定嵌套，stage 统计只取 `span_depth == max(span_depth)` 的叶子。
- 代价：无法跨 project 串联、无法重建完整 tree；但聚合逻辑极简单。

**方案 C：事件命名白名单（纯 obs-local 侧）**
- project 注册时声明 `stage_events: ["retrieval.semantic_stage", "reranker.score", ...]`，只有白名单内的 `.end` 参与 StageStats。
- 代价：每个新阶段都要改配置；mykms 加一个新埋点 obs-local 就漏掉。

**推荐方案 A**。理由：
1. OTel 语义约定 (`trace_id` / `span_id` / `parent_span_id`) 是业界 10 年博弈出来的结果，自己再造轮子迟早绕回这里
2. mykms 侧改动不大：`timed_operation` 已经是 contextmanager，加 8 行 contextvar 栈维护即可
3. middleware 侧的 `http.request.*` 也应该纳入 span 体系（它就是 root span），统一后 `request_id` 和 `span_id` 的关系自然（root span 的 `span_id == trace_id` 的前 8 字节，或直接让 trace_id 就是 root span_id 的拓展）
4. 未来如果要做"分布式追踪"（kms-api 调外部 reranker 服务时传 traceparent header），协议零修改就能工作

### 5. `timestamp` 无时区 + 多项目聚合 = 乱序

[`app/timefmt.py:6-10`](../../app/timefmt.py) 输出 `"2026-04-15 11:52:02.388"`，**不带时区信息**。

现在 mykms 单机单服务还能跑；但 design 明确是"多项目聚合服务"，一旦接入第二个项目（哪怕都在同一台机器，如果其中一个用了 UTC formatter），跨项目的时间线就会错排，而且错得很隐蔽。

**建议（合理方案，二选一）**：

**方案 A：RFC3339 带本地 offset（推荐）**
- **[需 mykms 配合]** [`app/timefmt.py:6-10`](../../app/timefmt.py) 改为：
  ```python
  def format_local_datetime(value: datetime | None = None) -> str:
      current = (value or datetime.now()).astimezone()  # 本地时区
      return current.isoformat(timespec='milliseconds')  # "2026-04-15T19:52:02.388+08:00"
  ```
- 协议约束：`timestamp` 必须是 RFC3339 / ISO8601 带时区偏移。
- 优点：保留本地时间的可读性（开发者看 log 不用换算）；带 offset，无歧义；Python/Go/JS 都能 `fromisoformat` 直接解析。

**方案 B：UTC epoch 毫秒 + 本地展示**
- **[需 mykms 配合]** 协议里 `timestamp` 改为整数 `timestamp_ms`（UTC epoch），另加可选 `timestamp_local` 仅用于开发者肉眼看 log。
- 优点：机器读取零歧义、跨时区比较直接减法；缺点：原始日志不再人眼可读，排障体验打折。

**推荐方案 A**。理由：人眼可读性在本地服务里权重很高；方案 B 适合大规模生产，但 obs-local 的定位是"本地诊断工具"，牺牲可读性不划算。

parser 侧仍需鲁棒：除上述两种外，还要吃老格式（无时区字符串），缺时区时按 project 注册的 `tz` 字段（默认 `Asia/Shanghai`）补齐——这是兼容层，不是主路径。

---

## 二、设计层问题（不会立刻阻塞但会拖累长期演进）

### 6. "通用协议"里混入了 mykms 专属字段

第 8.2 节 `RequestSummary.detail = "上下文处理包括什么？"` 直接来自 mykms 的 `api.ask.start.question`。这违背第 3.1 节自己提的"先统一协议再统一页面"。

**建议（合理方案，三选一）**：

**方案 A：引入 `attributes` 命名空间（OTel 对齐，推荐）**
- 协议约定：根字段只保留通用元数据（`timestamp` / `service` / `span_id` / ...）；所有业务字段放进 `attributes: {...}` 子对象。
- **[需 mykms 配合]** `JsonLogFormatter` 把 `context` 里非协议字段自动归到 `attributes`；埋点处继续传 `question=...`，formatter 负责归类。
- UI 侧统一读 `attributes`，不再关心具体业务字段名。
- 长远价值：协议字段集稳定，业务字段任意扩展不污染核心；与 OTel 的 `span.attributes` 完全一致。

**方案 B：显式 `display_summary` 字段**
- **[需 mykms 配合]** `api.ask.start` 埋点改为 `log_event(..., display_summary=question[:200])`；协议里 `display_summary` 是可选通用字段。
- 比方案 A 轻量，但每增加一个"展示价值"的业务字段都要新增协议字段，会逐渐膨胀。

**方案 C：project 注册侧配置字段映射**
- `config.yaml` 里写 `summary_mapping: { "api.ask.start": "question" }`。
- 耦合度比 A/B 都低，但配置量随业务事件数线性增长。

**推荐方案 A**。理由：OTel 的 attributes 模型是被大规模验证过的隔离机制；mykms 侧改动只在 formatter 层，业务埋点代码零改动（只需要 formatter 把非协议字段自动转到 `attributes`）。未来新接入项目也能直接遵守协议。

### 7. `event` 与 `stage` 的命名映射没定义

`top_stages` 示例里写 `"stage": "query.ask"`，但埋点事件名是 `query.ask.start` / `query.ask.end`。抽 stage 是去掉 `.end` 后缀，还是整体取 start/end 之间的"基名"？

**建议（合理方案）**：
- 配合 §4 方案 A：**[需 mykms 配合]** formatter 直接写 `span_name` 字段（由 `timed_operation(LOGGER, operation=...)` 的 `operation` 参数直接得到，不带 `.start/.end/.error` 后缀）。
- 协议里 `event` 字段只保留"事件类型"（`start` / `end` / `error`），`span_name` 独立承载"业务名"。
- 这样 obs-local 侧不再需要字符串解析，直接 `group by span_name`。

### 8. `service` 字段的多义性没理清

design 第 5.1 / 8.1 节把 `service` 当成"每条日志都有"且"一个 project 一个 service"。但：

- 旧代日志里没有 `service`
- 一个 project 完全可能有多个 service（workers、CLI job、api），共用一份 log 或分多份
- `project_id` 和 `service` 是 1:1 还是 1:N？

**建议**：协议里 `service` 标记为"**日志内字段，非 project 配置**"；project 可以注册多个 `(service, log_path)` 对；UI 上允许按 service 过滤。

### 9. `.run-logs/` 下还有大量非 JSONL 日志被完全忽略

目录实际内容：

```
ask-context.json / ask-coroutine.json / ask-latest.json  # 业务产出的结构化快照
kms-api.err.log / kms-api.out.log                         # stdout/stderr 捕获
uvicorn.err.log / uvicorn.out.log                         # uvicorn 日志
gpu-test.err.log / gpu-test.out.log
kms-api.pid.json                                          # 进程标记
db-backup-20260415-113928                                 # 备份
```

- `*.err.log`、`*.out.log` 里可能有 uvicorn 访问日志或 Python traceback，排障时比 JSONL 更关键
- `*.json`（非 JSONL）是单个对象快照，不是事件流

design 第 12.3 节"非法 JSON 行直接跳过"会把这些全部吞掉，**错误排查反而会绕不开去翻 err.log**。

**建议（合理方案）**：
- **[需 mykms 配合]** 从源头统一：`uvicorn` 的 access log 和 error log 都接入 `kms-api.log` 的 JsonLogFormatter。当前 [`app/observability.py`](../../app/observability.py) 已经做了 `"uvicorn.*"` logger 的 propagate=True + 清空 handlers，但还需要给 uvicorn 的 logger 也配 JsonLogFormatter（或让它吞进 root），保证 stderr 走 root → `FileHandler(kms-api.log)`。
- 启动脚本（写到哪里的 `kms-api.out.log` / `kms-api.err.log`）停止把 stdout/stderr 重定向到单独文件；直接让进程只往 `kms-api.log` 写 JSON。
- `ask-context.json` / `ask-coroutine.json` / `kms-api.pid.json` 等单对象快照不是事件流，协议里明确："obs-local 只消费 JSONL 事件流，单对象快照归 CLI 工具或 debug endpoint 管"。
- project 注册字段不再有 `jsonl/plain_text` 类型之分 —— 只有"JSONL 事件流"一种源。

> 为什么不走 "obs-local 支持多种源": 这是把"上游日志架构不统一"的代价推给协议；长远看每接入一个新项目都要定制适配器。让上游一次性统一，换来协议的简洁和稳定。

### 10. 本地服务默认暴露接口 = 日志原文泄漏

`api.ask.start` 日志里原样保留了用户问题：

```json
{"event": "api.ask.start", "question": "上下文处理包括什么？", "request_id": "aecd0f64da57"}
```

如果 obs-local 按 FastAPI 常见默认 `0.0.0.0:PORT` 起服务，同网段任何人都能拿到用户提问原文。即便绑 `127.0.0.1`，也应该在文档里明说。

**建议**：
- 默认 bind `127.0.0.1`，文档里写死
- 协议里允许 project 配置 `redact_fields: ["question", "detail"]`，parser 层做脱敏
- `summary` 字段在 UI 默认截断 60 字符

### 11. Windows 下并发文件访问未讨论

`kms-api` 通过 `logging.FileHandler` 写日志（[`app/observability.py`](../../app/observability.py)），Windows 对打开中的文件有排他语义。obs-local 的 tailer 用 `open(..., 'r')` 一般没事，但如果将来 mykms 切到 `RotatingFileHandler` 或 Windows Handler 策略变化，就会踩 `PermissionError`。

**建议**：
- tailer 用 `open(path, 'r', encoding='utf-8', errors='replace')` + 只读模式，并在文档里标注已知 Windows 约束
- 读取失败时降级到"下次轮询重试"而不是硬崩

### 12. 日志无 rotate，"扫尾部"语义会漂移

mykms 用的是 `FileHandler`（[`app/observability.py`](../../app/observability.py)），**永不滚动**。`kms-api.log` 会无限增长，运行几周后"扫最后 N MB"会让同一天的请求落在不同轮询里看到不同切片。

**建议（合理方案，二选一）**：

**方案 A：按日切分 + 保留 N 天（推荐）**
- **[需 mykms 配合]** [`app/observability.py`](../../app/observability.py) 的 `FileHandler` 改为 `TimedRotatingFileHandler(filename=..., when='midnight', backupCount=14, encoding='utf-8')`。
- 文件命名：`kms-api.log`（当天）+ `kms-api.log.2026-04-14` / `kms-api.log.2026-04-13` ...
- obs-local tailer 识别当前活跃文件 + 扫最近 1~2 个历史文件（按需）。
- 优点：按时间切分与"最近 1h / 24h 窗口"的查询语义天然对齐；人肉排障也好找。

**方案 B：按大小切分 + 保留 N 个**
- `RotatingFileHandler(maxBytes=100MB, backupCount=10)`。
- 对高吞吐服务更可预期，对低吞吐服务（比如开发机上的 mykms）一周都不滚动一次，和查询窗口错位。

**推荐方案 A**。理由：观测的主要查询维度是时间窗口（"最近 1h"、"今天"），按日切分让文件边界和查询边界对齐，tailer 逻辑也简单。

协议侧 design 第 12.1 节的"扫最后 N 行/MB"应改为"**按 `trace_id` 聚合完整 span tree + 最近 N 个 trace**"，避免窗口切在 span start/end 之间导致数据残缺。

---

## 三、数据模型与 API 的细节问题

### 13. p95 没有最小样本量

StageStats 按 `p95_ms` 排序。统计学上，n<20 的 p95 基本等于 max，排序会被偶发慢调用污染。

**建议**：`count<10` 的 stage 在 UI 上灰化或排到末位；API 返回里附带 `p95_confidence: low|medium|high`。

### 14. `kind` 过滤字段在 API 节里凭空出现

第 9.3 节 "`GET /api/requests` 支持过滤 `path/method/status/kind`"，但 `kind` 在前文从未定义。

**建议（合理方案）**：
- 直接对齐 OTel 的 `span.kind`：`server` / `client` / `producer` / `consumer` / `internal`。
- `http.request.*`（middleware 入口）= `server`；mykms 调外部 reranker / embedding 服务（如果埋点）= `client`；内部 `timed_operation` = `internal`。
- **[需 mykms 配合]** `log_event` 和 `timed_operation` 增加 `kind` 参数（默认 `internal`）；middleware 的 `http.request.*` 埋成 `server`。
- obs-local 的 UI "最近请求列表"天然只显示 `kind=server` 的 span；`internal` span 只在单请求详情瀑布图里出现。

### 15. `/api/projects POST` 与 `config.yaml` 的冲突未约定

project 可从 yaml 静态注册，也能通过 API 动态新增，写入 `state.db`。重启时哪个优先？

**建议**：
- yaml 为**只读声明源**，DB 为**运行时叠加层**；启动时 yaml 项覆盖 DB 同名项，避免漂移
- 或者反过来，但文档必须明说

### 16. 缺自身健康检查

obs-local 自己挂了，用户看到 UI 白屏无从判断是服务挂了还是项目没日志。

**建议**：加 `GET /api/health`，返回各 project 的 `last_log_at`、`tailer_error`；UI 顶部显示 staleness 徽章（"kms-api 最近 12 秒有日志"/"已 5 分钟无日志"）。

### 17. 窗口统计缺 staleness 语义

第 9.2 节 `/api/overview` 返回"最近窗口请求数"。如果上游服务整个挂掉，这个数会变 0，**让人误以为"系统空闲"而不是"上游宕机"**。

**建议**：overview 里必须带 `last_event_at`，UI 用颜色区分"空闲"和"失联"。

### 18. 内存窗口 vs 重启丢失

第 11 节说"请求/错误/阶段保留在内存窗口"。用户预期 UI 打开就能看到"最近几小时的请求"。obs-local 重启后内存清空，必须重扫；`.run-logs/kms-api.log` 越大重扫越慢。

**建议**：
- 启动时异步重扫 + UI 显示"正在回放历史，已处理 X%"
- 或者 state.db 里增量缓存请求索引（`request_id -> {started_at, ended_at, status_code}`），内存只缓存时间线详情

### 19. 文档结构自身的问题

- 第 2 节"关键代码在..."引用 `../../app/observability.py`，但 design 现放在 `obs-local/docs/` 下，路径应按文档所在目录解析，例如 `obs-local/docs/design_v1.md`
- 第 8.3 `ErrorSummary` 的 `request_id` 示例是空串 `""`，协议里应该用 `null` 表示"无 request_id"，否则前端要分别处理 `""` 和 `null`
- 第 14 节分期把"Docker 化"放到 Phase 3，但 Phase 1 一个"本地单机 Python 服务"反而用 Docker 更省事；建议 Phase 1 就附一个极简 Dockerfile 备选（非强制）

---

## 四、建议补进 design_v1 的章节

### 新增 §4.0 协议总览：OTel 语义对齐

新协议的字段分层：

```json
{
  "timestamp": "2026-04-15T19:52:02.388+08:00",
  "schema_version": 1,
  "service": "kms-api",
  "logger": "kms.api",
  "level": "INFO",
  "event": "end",                   // "start" | "end" | "error"
  "span_name": "api.ask",
  "span_id": "a3f1c0d2",
  "parent_span_id": "7b4e9021",
  "trace_id": "aecd0f64da57",       // = 原 request_id
  "kind": "internal",               // OTel span.kind
  "status": "ok",                   // "ok" | "error"
  "duration_ms": 644.285,
  "error_type": null,
  "exception": null,
  "attributes": {
    "http.method": "POST",
    "http.path": "/ask",
    "http.status_code": 200,
    "display_summary": "上下文处理包括什么？"
  }
}
```

字段说明：

- **核心元数据**（根层）：`timestamp` / `schema_version` / `service` / `logger` / `level`
- **span 身份**（根层）：`event` / `span_name` / `span_id` / `parent_span_id` / `trace_id` / `kind`
- **span 结果**（根层）：`status` / `duration_ms` / `error_type` / `exception`
- **业务数据**（`attributes` 子对象）：任意 key，协议不约束，UI 侧展示

### 新增 §4.3 协议版本与向后兼容

- `schema_version: 1` 字段强制写入每条事件
- 协议 v1 的最小合规集：`timestamp` / `span_name` / `span_id` / `trace_id` / `event` / `status`
- v2 升级策略：新字段走 `attributes`，避免破坏根层；根层字段变更必须升版本号
- 老日志（无 schema_version）在 parser 里按 "降级展示" 处理，不进统计

### 新增 §11.1 偏移与会话标记

`.run-logs/kms-api.pid.json` 这类进程标记可以当作"上游重启边界"。建议 tailer 识别到 pid 变更时，UI 上把窗口切成多个 "session"，排障时能区分"这个错误是这次启动产生的还是上次遗留的"。

更进一步的合理方案：**[需 mykms 配合]** mykms 启动时写一条 `service.startup` 事件，携带 pid、版本、config hash；obs-local 以 `service.startup` 为 session 边界，比依赖外部 pid 文件更干净。

---

## 五、优先级建议

| 问题 | 是否 MVP 阻塞 | 需 mykms 配合 | 修复位置 | 当前状态 |
|---|---|---|---|---|
| ~~§1 新旧 schema 并存~~ | 已忽略 | — | — | 已忽略 |
| §2 `status` 字段缺失 | 是 | ✅ | `app/main.py` middleware | 已修 |
| §3 `.error` 无 `.end` | 是 | ✅ | `app/main.py` 异常分支 | 已修 |
| §4 阶段嵌套 / span_id | 是 | ✅ | `app/observability.py` timed_operation | 已修 |
| §5 时区 | 是（多 project 时） | ✅ | `app/timefmt.py` | 已修 |
| §6 attributes 命名空间 | 否（但 Phase 1 就改最划算） | ✅ | `app/observability.py` JsonLogFormatter | 未修 |
| §7 span_name 独立字段 | 否 | ✅（与 §4 同步） | `app/observability.py` | 已修 |
| §8 service 多义性 | 否 | — | 协议文档 | 未动 |
| §9 非 JSONL 源归一 | 否 | ✅ | uvicorn log 配置 + 启动脚本 | 未修 |
| §10 默认 bind + 脱敏 | 否但 Phase 1 就做 | — | obs-local 侧 | obs-local 已支持脱敏与本地绑定 |
| §11 Windows 锁 | 否 | — | obs-local 侧 | obs-local 已补容错 |
| §12 rotate | 是（会影响 tailer 正确性） | ✅ | `app/observability.py` | 已修 |
| §13 p95 最小样本 | 否 | — | obs-local 侧 | obs-local 已降级低样本展示 |
| §14 `kind` 字段对齐 span.kind | 否（与 §4 同步） | ✅ | `app/observability.py` | 已修 |
| §15-19 | 否 | — | 混合 | 部分已在 obs-local 落地 |

**结论**：`status/end/span/timezone/rotate` 这批 MVP 阻塞项已经收口，`mykms` 与 `obs-local` 当前都已具备 canonical 协议能力。剩余主要是 `attributes` 继续纯化、非 JSONL 源归一、以及 startup/session 边界等增强项。

**建议的分期**：

- **Phase 1 之前（协议冻结）**：协议核心收口已完成；若继续演进，优先完成 §6 方案 A 与 startup/session 边界事件。
- **Phase 1 开发期**：obs-local 按新协议实现 tailer + parser + aggregator；§10 bind 127.0.0.1 + 脱敏作为默认；§13 p95 样本量过滤内建。
- **Phase 2**：§9（uvicorn 日志归一，需要动启动脚本，不影响协议）；§11（Windows 锁容错）；§15-19。

---

## 六、mykms 侧剩余必须的配合改动清单

这一节把散落在各处的 **[需 mykms 配合]** 建议汇成一份可执行清单。注意其中有一部分基础兼容已完成：

- 已完成：
  - `schema_version=1`
  - `duration_ms` 标准字段补齐，并保留 `elapsed_ms` 兼容
  - `http.request.error` 的 `status/error_type/duration_ms`
- 本节只保留**仍然未完成**、且决定协议是否能一次定型的剩余项。

### 6.1 `app/timefmt.py` — 时间格式升级

改 `format_local_datetime` 返回 RFC3339 带时区 offset：

```python
def format_local_datetime(value: datetime | None = None) -> str:
    current = value or datetime.now().astimezone()
    if current.tzinfo is None:
        current = current.astimezone()  # 补本地时区
    return current.isoformat(timespec='milliseconds')
```

同时 `parse_datetime_maybe_local` 保持宽松（能吃老格式 + 新格式）。

### 6.2 `app/observability.py` — span 模型 + attributes 分层（剩余项）

主要改动点：

1. **新增 span 栈**：
   ```python
   _span_stack_var: ContextVar[tuple[dict, ...]] = ContextVar("kms_span_stack", default=())
   ```
   每个 span 记录 `{span_id, span_name, kind, started_at}`。

2. **`timed_operation` 重写**：进入时生成 `span_id`（8 字节 hex）、读栈顶作为 `parent_span_id`、push；退出时 pop。每条 `.start/.end/.error` 都带 `span_id` / `parent_span_id` / `span_name` / `kind`。

3. **`JsonLogFormatter.format` 重写**：
   - 根层输出协议核心字段（`timestamp` / `schema_version` / `service` / `logger` / `level` / `event` / `span_*` / `trace_id` / `kind` / `status` / `duration_ms` / `error_type` / `exception`）
   - 其余 `context` 字段全部归到 `attributes` 子对象
   - `event` 字段值从完整 `"api.ask.start"` 改为 `"start"`；`span_name` 字段独立承载 `"api.ask"`

4. **`log_event` 新增 `kind` 参数**，默认 `internal`。

5. **`configure_logging` 中 FileHandler 改 `TimedRotatingFileHandler`**：
   ```python
   file_handler = TimedRotatingFileHandler(
       resolved_dir / "kms-api.log",
       when='midnight', backupCount=14, encoding='utf-8',
   )
   ```

6. **启动时写 `service.startup` 事件**（可放在 `configure_logging` 末尾），携带 `pid` / 版本 / config hash，作为 session 边界标记。

补充：当前 [`app/observability.py`](../../app/observability.py) 里 `schema_version`、`duration_fields()` 和 `timed_operation -> duration_ms` 已经落地，因此这里不再需要重复实现这些基础兼容。

### 6.3 `app/main.py` — HTTP middleware 对齐 span 模型（剩余项）

`log_requests` middleware 重写为：

```python
async def log_requests(request, call_next):
    trace_id = uuid4().hex[:12]
    token = bind_request_id(trace_id)
    started_at = time.perf_counter()
    span_id = secrets.token_hex(4)

    log_event(LOGGER, "start",
              span_name="http.request", span_id=span_id, parent_span_id=None,
              trace_id=trace_id, kind="server",
              **{"http.method": request.method, "http.path": request.url.path,
                 "http.query": request.url.query,
                 "http.client": request.client.host if request.client else None})

    status = "ok"
    status_code = None
    error_type = None
    try:
        response = await call_next(request)
        status_code = response.status_code
        if status_code >= 400:
            status = "error"
        return response
    except Exception as exc:
        status = "error"
        status_code = getattr(exc, "status_code", 500)
        error_type = type(exc).__name__
        LOGGER.exception("error",
                         extra={"context": {
                             "event": "error", "span_name": "http.request",
                             "span_id": span_id, "trace_id": trace_id,
                             "kind": "server", "error_type": error_type,
                         }})
        raise
    finally:
        log_event(LOGGER, "end",
                  span_name="http.request", span_id=span_id, parent_span_id=None,
                  trace_id=trace_id, kind="server",
                  status=status, status_code=status_code, error_type=error_type,
                  duration_ms=round((time.perf_counter() - started_at) * 1000.0, 3),
                  **{"http.method": request.method, "http.path": request.url.path})
        reset_request_id(token)
```

关键改动：

- 当前已完成的基础项：
  - `http.request.error` 已带 `status="error"`、`error_type`、`duration_ms`
  - `http.request.end` / `http.request.error` 已统一带 `duration_ms`
- 异常分支在 `finally` 里**一定**写 `"end"` 事件，保证 start/end 配对
- `"error"` 事件降级为附加详情，不承担结束语义
- HTTP 相关字段（method / path / status_code）走 `attributes` 命名空间（`http.method` 等），符合 OTel HTTP 语义约定

### 6.4 uvicorn 日志归一（Phase 2 动作）

当前 [`configure_logging` 已经把 uvicorn.* logger 的 propagate 设为 True](../../app/observability.py)，但 uvicorn 默认的 access log 是纯文本，propagate 后在 JsonLogFormatter 里会被包成单行 JSON 但 `attributes` 不结构化。建议：

- 关掉 uvicorn 默认 access log（`--no-access-log`）
- 所有访问日志由 mykms middleware 自己写（即 6.3 已经做到）
- 启动脚本不再把 stderr 重定向到单独文件，让一切走 root logger → `kms-api.log`

### 6.5 兼容与验证

- 现有调用 `timed_operation(LOGGER, "api.ask", question=...)` 的业务代码**零改动**：`question` 会被 JsonLogFormatter 自动归到 `attributes.question`
- 现有 `log_event(LOGGER, "http.request.start", ...)` 式调用已完成切换，当前实现已改为 `log_event(LOGGER, "start", span_name="http.request", ...)`
- 当前已存在的基础回归：[`tests/test_observability.py`](../../tests/test_observability.py)，已覆盖 `schema_version`、`duration_ms` 与 HTTP 请求日志的兼容输出。
- 剩余建议新增 `tests/test_observability_span.py`，覆盖：span 栈正确嵌套、异常路径仍有 `.end`、attributes 字段正确分层、timestamp 带时区
