# obs-local

`obs-local` 是一个面向本地多项目的轻量观测服务，目标是把各项目已经落盘的结构化日志统一聚合成可读的请求、错误和耗时视图，避免在每个项目里重复开发日志页面。

第一阶段以 `mykms` 作为首个接入样本，但服务本身不绑定 `mykms`，而是围绕一套最小通用日志协议设计。

## 1. 目标

`obs-local` 要解决的问题：

- 看最近有哪些请求
- 看最近哪些请求报错
- 看每个请求里哪几个阶段最慢
- 看某个项目在最近窗口里的阶段耗时分布
- 用同一套 UI 和 API 接多个本地项目

第一阶段明确不解决：

- 远程集中采集
- 多用户权限
- 全量日志长期归档
- 完整替代 ELK / Prometheus / ClickHouse

定位：

- 单机、本地、轻量、低接入成本
- 优先读取已有 JSONL 日志文件
- 先做诊断和排障，不先做企业级日志平台

## 2. 为什么独立成服务

如果每个项目都内嵌一个日志页面，会出现几个问题：

- 重复开发请求列表、错误列表、耗时统计、过滤和时间线
- 同类埋点在不同项目里难以统一展示
- 后续想支持多个项目切换时，需要每个项目都重做
- UI 逻辑和业务服务耦合，维护成本高

独立服务后，业务项目只需要继续输出结构化日志，不需要自己维护观测页面。

对于 `mykms`，当前日志基础已经满足接入前提，关键代码在：

- [`../../app/observability.py`](../../app/observability.py)
- [`../../app/main.py`](../../app/main.py)

当前已经有这些关键字段和事件：

- `timestamp`
- `service`
- `event`
- `level`
- `logger`
- `message`
- `request_id`
- `status`
- `duration_ms`
- `http.request.start`
- `http.request.end`
- `api.ask.*` / `api.search.*` / `api.index.*`
- `retrieval.lexical_stage.*` / `retrieval.semantic_stage.*` / `reranker.score.*`

这意味着 `mykms` 不需要先为 `obs-local` 重写埋点。

## 3. 核心设计原则

### 3.1 先统一日志协议，再统一页面

公共服务的真正复用点不是 HTML，而是：

- 统一的最小字段集
- 统一的事件命名约定
- 统一的请求聚合模型

只有协议稳定，页面和 API 才能跨项目复用。

### 3.2 第一版优先拉模式

第一版不要求业务项目把日志推送到观测服务。

`obs-local` 直接读取项目本地日志文件，原因是：

- 现有问题本来就是“日志已经写入文件，不好读”
- 改造最小
- 不要求每个项目额外实现 `/ingest`
- 易于本地调试和回归

后续如果需要，再增加推模式。

### 3.3 业务项目只保留埋点，不保留页面

业务项目负责：

- 输出结构化 JSONL 日志
- 为关键链路提供 `request_id`
- 对阶段打 `.start` / `.end` / `.error` 事件

业务项目不负责：

- 日志聚合
- 统计分析
- 请求详情时间线
- 观测页面

## 4. 最小通用日志协议

### 4.1 最小字段

推荐每条日志至少包含这些字段：

```json
{
  "timestamp": "2026-04-15 11:52:02.389",
  "service": "kms-api",
  "event": "http.request.end",
  "level": "INFO",
  "logger": "kms.api",
  "message": "http.request.end",
  "request_id": "aecd0f64da57",
  "method": "POST",
  "path": "/ask",
  "status_code": 200,
  "duration_ms": 644.285,
  "error_type": null
}
```

字段说明：

- `timestamp`：事件发生时间
- `service`：服务名，用于跨项目区分
- `event`：事件名，供聚合逻辑识别
- `request_id`：单请求链路关联键
- `status`：阶段事件常见值为 `ok` / `error`，请求级事件不强制要求存在
- `duration_ms`：阶段或请求耗时
- `path` / `method`：HTTP 请求维度
- `error_type` / `exception`：错误摘要

### 4.2 事件命名约定

第一版按以下约定聚合：

- 请求开始：`http.request.start`
- 请求结束：`http.request.end`
- 请求异常：`http.request.error`
- 业务 API：`api.*.start` / `api.*.end` / `api.*.error`
- 阶段事件：`*.start` / `*.end` / `*.error`

约束：

- `stage_name = event 去掉 .start/.end/.error 后缀后的基名`
- 带 `duration_ms` 的 `.end` 事件，视为候选阶段事件，但不代表一定进入最终阶段排行
- `level=ERROR`、`status=error`、带 `exception` 的事件，视为错误事件
- `status_code>=400` 的请求，视为失败请求
- 没有 `request_id` 的事件，允许保留为系统事件，但不能进入请求链路视图

### 4.3 归一化与聚合规则

`obs-local` 不直接把原始事件原样展示，而是先做归一化。

请求级归一化：

- 请求开始事件固定为 `http.request.start`
- 请求终止事件为 `http.request.end` 或 `http.request.error`
- 如果没有 `http.request.end`，但有 `http.request.error`，则聚合器必须把 `http.request.error` 视为请求结束
- 这类异常请求的 `ended_at` 取 `http.request.error.timestamp`
- 这类异常请求的 `duration_ms` 优先取事件内字段；若缺失，则用 `ended_at - started_at` 计算
- 这类异常请求的 `status_code` 允许为 `null`

失败请求与错误事件是两个不同概念：

- 失败请求：`status_code >= 400`，或请求终止事件为 `http.request.error`
- 错误事件：`level=ERROR`，或 `status=error`，或存在 `exception`

阶段级归一化：

- `stage_name` 从 `.start/.end/.error` 事件基名提取
- 时间线展示阶段的 inclusive duration，也就是事件原始 `duration_ms`
- 阶段排行默认不直接使用所有父子阶段的 inclusive duration 混排
- MVP 优先采用叶子阶段或 `self duration` 规则，避免父阶段重复覆盖子阶段

### 4.4 时间戳与时区策略

parser 必须兼容以下时间格式：

- RFC3339 / ISO8601
- `%Y-%m-%d %H:%M:%S.%f`
- epoch milliseconds

约束：

- 如果日志时间戳自带时区，按原始时区解析
- 如果日志时间戳不带时区，按 source 配置中的 `timezone` 补齐
- `obs-local` 不应默认用自身机器本地时区去猜测其他项目日志

### 4.5 协议版本

第一版协议引入可选字段：

- `schema_version`

约定：

- 未提供时，按 `v1` 兼容模式处理
- parser 需要允许缺失 `service`、`status`、`status_code` 等非强制字段
- 后续如果协议升级，优先保证旧日志在只读分析场景下可兼容

## 5. 系统边界

### 5.1 业务项目职责

- 保持结构化日志稳定
- 保留关键事件埋点
- 配置日志文件路径

### 5.2 `obs-local` 职责

- 注册多个项目日志源
- 增量 tail 日志文件
- 解析 JSONL
- 聚合请求视图、错误视图、阶段耗时视图
- 提供统一 API 和 Web UI

### 5.3 Project / Source / Service 关系

统一关系定义如下：

- `project`：UI 和 API 的主要分组单位，例如 `mykms`
- `source`：一个可读取的日志输入源，例如某个 `log_path`
- `service`：日志记录里的服务名字段，例如 `kms-api`

约束：

- 一个 `project` 可以注册多个 `source`
- 一个 `project` 下可以出现多个 `service`
- `service` 是日志内字段，不作为 project 的唯一标识

## 6. MVP 功能范围

第一版目标是一个单机本地服务，支持多个项目切换。

必须有：

- 项目注册与切换
- 近期请求列表
- 近期错误列表
- 阶段耗时统计
- 单请求时间线详情
- UI 自动实时更新
- 手动刷新作为兜底能力

可以后置：

- 高级过滤
- 导出 CSV / JSON
- 推送采集
- WebSocket 实时流
- 告警规则

## 7. 目录设计

建议目录如下：

```text
obs-local/
  docs/
    design_v1.md
    design_v1_claude.md
  app/
    main.py
    config.py
    schemas.py
    registry.py
    tailer.py
    parser.py
    aggregator.py
    api_projects.py
    api_requests.py
    api_errors.py
    api_stages.py
    web.py
  frontend/
    index.html
    package.json
    vite.config.ts
    tsconfig.json
    src/
      main.ts
      App.vue
      router/
      stores/
      views/
      components/
      composables/
      styles/
  data/
    state.db
  dev-run/
    master-plan.md
    stage-status.md
    agent-board.md
    progress.md
    review-log.md
    bug-ledger.md
    fix-log.md
  config.yaml
```

各模块职责：

- `registry.py`：项目注册信息管理
- `tailer.py`：增量读取日志文件，处理 offset、轮转和截断
- `parser.py`：把原始 JSONL 行解析为统一记录
- `aggregator.py`：把记录聚合成请求、错误、阶段统计
- `web.py`：提供前端构建产物入口，开发期可代理到 Vite dev server
- `api_*`：提供前端数据接口
- `frontend/src/stores`：管理实时状态、连接状态和页面共享数据
- `frontend/src/composables`：封装 SSE、过滤、时间线更新等前端逻辑
- `frontend/src/components`：沉淀卡片、表格、标签、时间线等基础组件

## 8. 数据模型

### 8.1 ProjectSource

```json
{
  "project_id": "mykms",
  "source_id": "mykms-main",
  "name": "mykms",
  "log_path": "E:/github/mykms/.run-logs/kms-api.log",
  "format": "jsonl",
  "timezone": "Asia/Shanghai",
  "service_hint": "kms-api",
  "redact_fields": ["question"],
  "enabled": true
}
```

### 8.2 RequestSummary

```json
{
  "project_id": "mykms",
  "request_id": "aecd0f64da57",
  "started_at": "2026-04-15 11:52:01.744",
  "ended_at": "2026-04-15 11:52:02.389",
  "method": "POST",
  "path": "/ask",
  "status_code": 200,
  "status": "ok",
  "duration_ms": 644.285,
  "summary": "上下文处理包括什么？",
  "top_stages": [
    {"stage": "query.ask", "duration_ms": 635.931},
    {"stage": "retrieval.search_and_rerank", "duration_ms": 627.977}
  ],
  "error_count": 0,
  "last_event_at": "2026-04-15 11:52:02.389",
  "partial": false
}
```

说明：

- `summary` 是展示字段，不要求每个项目都原生提供
- 每个 project 可配置事件字段到 `summary` 的映射，例如 `mykms /ask -> question`
- `top_stages` 默认展示叶子阶段或 `self duration` 排名，不直接展示所有父阶段总耗时

### 8.3 ErrorSummary

```json
{
  "project_id": "mykms",
  "timestamp": "2026-04-15 03:15:45.885",
  "request_id": null,
  "event": "semantic.client_load.error",
  "path": null,
  "error_type": "RetrievalError",
  "message": "semantic.client_load.error",
  "detail": "chromadb is required for semantic retrieval"
}
```

### 8.4 StageStats

```json
{
  "project_id": "mykms",
  "stage": "retrieval.semantic_stage",
  "count": 42,
  "error_count": 1,
  "avg_ms": 118.6,
  "p95_ms": 366.2,
  "max_ms": 578.9,
  "last_seen_at": "2026-04-15 11:52:02.350"
}
```

## 9. API 设计

### 9.1 项目接口

`GET /api/projects`

- 返回已注册项目列表
- 带项目名、source、日志路径、启用状态

`POST /api/projects`

- 新增项目日志源
- 第一版可仅支持本地文件路径

配置优先级：

- `config.yaml` 是声明式配置源
- `state.db` 是运行时叠加层
- 若同名 project/source 同时存在，以 `config.yaml` 为准

### 9.2 概览接口

`GET /api/overview?project=mykms`

返回：

- 最近窗口请求数
- 最近窗口错误数
- 请求 P95
- 最慢阶段及其 P95
- 最近更新时间
- `last_event_at`
- `staleness`

`staleness` 用于区分：

- 服务最近无请求但仍在产生日志
- 上游长时间没有任何新日志，疑似已停止或失联

### 9.2.1 健康接口

`GET /api/health`

返回：

- `obs-local` 自身状态
- 每个 project/source 的 `last_event_at`
- 最近一次 tailer 错误
- 是否正在回放历史窗口

### 9.2.2 实时流接口

`GET /api/stream?project=mykms`

返回服务端实时事件流，用于把最新请求、错误、阶段统计和健康状态主动推送到 UI。

Phase 1 推荐优先使用：

- Server-Sent Events

原因：

- 服务端实现简单
- 浏览器原生支持较好
- 适合当前以服务端单向推送为主的观测场景
- 对本地工具服务足够

推送内容可以包括：

- `overview.updated`
- `requests.updated`
- `errors.updated`
- `stages.updated`
- `health.updated`
- `replay.progress`

约束：

- UI 不应依赖手动刷新才能看到最新日志变化
- 当日志源有新事件进入窗口后，UI 应在短时间内自动反映
- 若 SSE 断开，前端应自动重连
- 手动刷新只作为断线恢复和兜底能力

### 9.3 请求接口

`GET /api/requests?project=mykms&limit=50`

返回近期请求摘要列表。

可选过滤：

- `path`
- `method`
- `status`
- `request_type`

说明：

- `status` 过滤的是请求状态，例如 `ok` / `failed`
- `request_type` 是归一化后的请求类型，例如 `ask` / `search` / `index` / `verify`

`GET /api/requests/{request_id}?project=mykms`

返回单请求详情，包括：

- 基础信息
- 事件时间线
- 阶段耗时列表
- 错误事件列表

### 9.4 错误接口

`GET /api/errors?project=mykms&limit=50`

返回近期错误事件列表。

可选过滤：

- `path`
- `error_type`
- `status_code`

### 9.5 阶段接口

`GET /api/stages?project=mykms&window=1h`

返回最近窗口的阶段统计结果，按 `p95_ms` 排序。

### 9.6 刷新接口

`POST /api/reload?project=mykms`

手动触发指定项目重扫。

## 10. UI 设计

### 10.0 视觉目标

`obs-local` 虽然是工具型本地服务，但 UI 目标不是“能看就行”，而是：

- 漂亮、克制、专业
- 信息密度高，但不拥挤
- 适合长时间盯盘和排障
- 第一眼就能看出重点，不是简陋后台页

明确避免：

- 默认浏览器风格表格
- 只有白底黑字和灰色边框的“脚手架 UI”
- 纯堆表格、没有层次的日志页
- 用大量红绿高饱和色制造噪音

视觉方向建议：

- 整体风格偏“精致监控台”，不是企业 OA 风格
- 使用明确的品牌色和语义色，但控制颜色数量
- 卡片、表格、时间线、统计区需要有清晰层级
- 字体、留白、对齐、圆角、阴影要统一

### 10.0.1 UI 验收标准

Phase 1 的 UI 至少满足：

- 桌面端第一屏能同时看到摘要卡和核心列表入口
- 主要信息层级明确，3 秒内能定位慢请求和错误请求
- 表格在高密度信息下仍保持可读，不出现“日志墙”
- 移动端或窄窗口下不破版，至少可以纵向阅读
- 视觉实现不能退化成纯默认 HTML 表单和表格样式
- 日志新增后，UI 无需手动刷新即可自动更新

### 10.0.2 设计原则

- 摘要卡优先：先看整体健康，再看明细
- 颜色节制：状态色只用于强调，不作为大面积底色
- 排版稳重：避免过小字号和过密行距
- 动效轻量：只允许轻微过渡和展开动画，不做花哨动效
- 细节统一：边框、圆角、间距、阴影、字重遵守同一套 token
- 实时优先：默认展示最新状态，而不是让用户频繁点击刷新

### 10.0.3 推荐视觉语言

建议采用：

- 浅色主界面，便于长时间阅读
- 一组明确的中性色作为背景和边框层次
- 一组低饱和主色作为品牌色
- `error / warning / success / info` 语义色单独定义
- 数字和耗时列使用等宽字体，正文使用正常 UI 字体

不建议：

- 大面积纯黑深色主题作为默认主题
- 高饱和霓虹监控风
- 紫色系默认模板化配色
- 过度依赖渐变和玻璃拟态

首页布局建议分三块：

### 10.1 顶部摘要卡

- 近期请求数
- 错误请求数
- 请求 P95
- 最慢阶段 P95

视觉要求：

- 摘要卡必须有主次层级，不是四个完全一样的白盒子
- 关键指标数字要一眼可扫
- 次级说明展示 `last_event_at`、窗口范围或 staleness
- 慢阶段和错误指标要有克制但明显的强调
- 卡片更新时可以有轻微过渡，但不应频繁闪烁或跳动

### 10.2 中部双栏

左栏：近期请求

- 时间
- `method + path`
- 状态码
- 总耗时
- 请求摘要
- 最慢几个阶段

视觉要求：

- 请求列表优先展示扫描效率，支持快速横向比较
- 状态、耗时、摘要、阶段标签需要形成稳定列节奏
- 慢请求应有低干扰高识别度的高亮方式
- 不应把每一行做成密密麻麻的日志文本
- 新请求进入时应平滑出现，并尽量保持滚动位置稳定

右栏：近期错误

- 时间
- 事件名
- 接口路径
- 错误类型
- 异常摘要

视觉要求：

- 错误区要明显，但不能压过主工作区
- 错误摘要默认截断，支持展开
- 错误类型、事件名、请求路径之间要有清晰层级
- 避免整块大红底，优先用边框、标签、图标或局部强调
- 新错误出现时可以短暂强调，但不能造成持续视觉噪音

### 10.3 底部统计区

- 阶段耗时排行
- 点击请求后展开单请求时间线

时间线与排行的语义不同：

- 时间线展示原始阶段 inclusive duration
- 阶段排行优先展示叶子阶段或 `self duration`
- 样本量过小的阶段可以灰化展示，避免 `p95` 被偶发值污染

视觉要求：

- 时间线需要有明显的时间流动感，不能只是普通列表
- 阶段排行要兼顾统计感和可读性，允许使用条形对比或微型可视化
- 请求详情展开后应形成“摘要 -> 时间线 -> 明细”的稳定阅读顺序
- 页面整体应更像产品化观测台，而不是开发临时调试页

### 10.3.1 实时交互要求

UI 默认处于实时更新模式。

要求：

- 页面加载后自动连接实时流
- 概览、请求列表、错误列表、阶段排行自动刷新
- 若用户正在查看单请求详情，该详情在对应 request 有新增事件时应局部更新
- 若用户主动暂停实时模式，UI 要有明确状态提示，并允许一键恢复

为了减少干扰：

- 非关键区域更新可批量合并后再渲染
- 列表刷新时尽量保持滚动位置和焦点稳定
- 只对新增或变化项做局部更新，而不是整页重绘

### 10.3.2 连接状态反馈

UI 顶部应显示实时连接状态，例如：

- `Live`
- `Reconnecting`
- `Paused`
- `Replay`

这些状态需要清晰但不喧宾夺主。

### 10.4 组件与样式约束

Phase 1 就应建立基础设计 token：

- `color.background.*`
- `color.surface.*`
- `color.border.*`
- `color.text.*`
- `color.semantic.*`
- `space.*`
- `radius.*`
- `shadow.*`
- `font.size.*`

基础组件至少包括：

- `StatCard`
- `StatusBadge`
- `LatencyPill`
- `StageTag`
- `ErrorTag`
- `DataTable`
- `Timeline`
- `EmptyState`
- `StalenessBadge`
- `LiveBadge`

前端工程实现要求：

- 使用 `Vue 3`
- 使用 `Vite`
- 使用 `TypeScript`
- 使用 Composition API 组织实时数据和 UI 状态
- 样式可以采用 `CSS Modules`、`Scoped CSS` 或集中式 token 文件，但必须统一设计 token
- 不使用现成后台模板直接拼装页面

### 10.5 主题与后续扩展

第一版可以只交付一个高质量浅色主题，但样式组织上应允许后续扩展：

- 可增加暗色模式
- 可增加项目品牌色
- 可支持更高密度表格模式

前提是：

- Phase 1 的默认主题必须已经足够漂亮
- 不能把“以后再美化”作为当前降低 UI 标准的理由

单请求时间线示例：

```text
http.request.start
api.ask.start
query.search.start
retrieval.semantic_stage.end      208 ms
reranker.score.end               367 ms
query.ask.end                    635 ms
http.request.end                 644 ms
```

## 11. 状态存储设计

第一版使用 SQLite 保存轻量状态，不保存所有原始日志。

建议状态表：

- `projects`
  - 项目注册信息
- `file_offsets`
  - 文件路径、上次读取 offset、文件大小、mtime
- `snapshots`
  - 可选，缓存最近一次概览结果

第一版可以把“请求、错误、阶段统计”保留在内存窗口里，每次增量刷新后重算，不必先做全量持久化索引。

补充约束：

- `state.db` 至少保存 project/source 配置和文件 offset
- `config.yaml` 与 `state.db` 冲突时，以 `config.yaml` 为准
- 重启后允许先显示“正在回放历史窗口”，再逐步恢复最近请求视图

### 11.1 会话与偏移

对于带进程标记的项目，可以把进程元信息视为 session 边界。

例如 `mykms` 可利用 `.run-logs/kms-api.pid.json`：

- 识别服务重启
- 在 UI 上区分不同 session 的请求
- 辅助判断错误属于本次启动还是上次残留

## 12. 日志读取策略

### 12.1 第一版策略

- 读取日志尾部最近 `N` 行或最近 `N` MB
- 建立内存窗口
- 聚合最近请求、错误和阶段统计

说明：

- 这里的窗口语义是“最近事件窗口”，不是严格历史全量窗口
- 若窗口切在某个请求的中间，请求可被标记为 `partial=true`
- UI 与 API 应明确暴露这种不完整状态

### 12.2 增量策略

- 保存每个日志文件的 offset
- 文件增长时从上次位置继续读
- 文件被截断或轮转时自动回退到重扫尾部

增量读取与 UI 刷新联动要求：

- tailer 检测到新日志后，应尽快触发聚合更新
- 聚合结果变化后，应推送到实时流订阅端
- 推送频率需要节流，避免高频日志导致 UI 抖动
- 在高频更新场景下，允许按短时间片批量推送

### 12.3 容错

- 非法 JSON 行直接跳过
- 缺失字段的记录按降级方式处理
- 时间解析失败时仍保留原始字符串

第一版范围约束：

- MVP 只聚合主 JSONL 日志源
- `.err.log` / `.out.log` / 单对象 JSON 快照暂不进入统计
- 若后续需要，可为 plain text source 增加“仅 tail 展示，不做聚合”的模式

## 13. 与 `mykms` 的接入方式

`mykms` 当前主结构化日志在：

- [`../../README.md`](../../README.md) 中说明的 `.run-logs/kms-api.log`

第一版接入配置示例：

```yaml
projects:
  - name: mykms
    sources:
      - source_id: main
        log_path: E:/github/mykms/.run-logs/kms-api.log
        format: jsonl
        timezone: Asia/Shanghai
        service_hint: kms-api
        redact_fields:
          - question
        enabled: true
```

只要 `mykms` 继续保持现有结构化日志约定，就可以直接接入 `obs-local`。

## 14. 分期实施

### Phase 1: MVP

- 建项目注册
- 建日志 tailer
- 建统一 parser
- 建请求 / 错误 / 阶段聚合
- 提供基础 API
- 提供 SSE 实时流
- 搭建 `Vue + Vite` 前端
- 提供单页 UI
- 默认仅绑定 `127.0.0.1`

### Phase 2: 强化可用性

- 支持路径、状态码、错误类型过滤
- 支持时间窗口切换
- 支持导出 JSON / CSV
- 支持刷新节流与缓存

### Phase 3: 扩展接入方式

- 支持推送采集 `/ingest`
- 支持 WebSocket 实时流
- 支持简单规则告警
- 支持 Docker 化运行

## 15. 技术取舍

后端：

- 使用 FastAPI
- 使用 SQLite 保存项目配置和文件状态
- 不引入重型可观测性栈

前端：

- 使用 `Vue 3 + Vite + TypeScript`
- 采用组件化前端结构，不使用原生 HTML 拼接整页 UI
- 使用 Composition API 处理 SSE、筛选状态、局部更新和详情面板联动
- 样式层建立自己的 design tokens 与组件样式，不直接套用 admin 模板

原因：

- 这是一个高交互、实时更新、强调视觉质量的本地产品界面
- 原生 HTML + JS 难以稳定支撑复杂状态管理、局部更新和高质量 UI
- `Vue + Vite` 能在控制工程复杂度的同时，显著提升可维护性和交互质量

安全默认值：

- HTTP 服务默认绑定 `127.0.0.1`
- 支持按 source 配置 `redact_fields`
- UI 默认截断 `summary`

## 16. 风险与约束

### 16.1 不同项目字段不一致

解决方式：

- 以最小字段协议为准
- 缺字段时降级展示

### 16.2 没有 `request_id`

解决方式：

- 保留原子事件
- 不进入请求时间线视图

### 16.3 日志文件过大

解决方式：

- 默认只扫尾部窗口
- 后续再考虑增量索引或冷热分层

### 16.4 日志轮转

解决方式：

- 保存 offset 与文件特征
- 检测变化后回退重扫

### 16.5 Windows 文件访问

解决方式：

- tailer 仅使用只读方式打开日志
- 遇到 `PermissionError` 时记录 tailer 错误并在下次轮询重试

### 16.6 样本量过小的统计失真

解决方式：

- 对低样本量阶段降低展示优先级
- 在 API 中返回样本量，必要时附带统计置信提示

## 17. 当前结论

这件事更适合做成独立服务，而不是在每个项目里重复加页面。

`mykms` 已经具备作为首个接入项目的条件。下一步可以直接按本 README 的目录和边界，在 `obs-local/app/` 下开始搭 MVP 骨架。
