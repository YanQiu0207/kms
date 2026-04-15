# M8 obs-local Protocol Compatibility Upgrade

## Goal

让 `obs-local` 在不打断现有 `mykms` 日志消费的前提下，同时支持两种协议形态：

- 旧形态：`event="http.request.start"` / `event="api.ask.end"`
- 新形态：`event="start|end|error"` + `span_name="http.request|api.ask"`

重点收口请求生命周期识别、阶段名归一、summary 映射和 `trace_id` 驱动的请求聚合。

## Scope

- 升级 `obs-local/app/aggregator.py`
  - 请求 root span 识别改为兼容 `event` 和 `span_name + event_type`
  - stage 归一优先使用 `span_name`
  - summary mapping 兼容 `api.ask.start` 这类旧 key 与新协议输入
  - request status / request type 推断兼容新协议
- 补回归测试
  - `obs-local/tests/test_stage2_ingestion.py`
  - `obs-local/tests/test_stage3_aggregator.py`
- 台账同步
  - `dev-run/stage-status.md`
  - `dev-run/progress.md`

## Non-Goals

- 本轮不把 `mykms` 的 `event` 字段正式切成纯 `start|end|error`
- 不重写 `obs-local` API schema 或前端视图
- 不处理启动脚本 / PID 记账问题

## Flow

1. 为本轮兼容升级登记新阶段 `M8`。
2. 修改 `obs-local` 聚合逻辑，优先使用 `span_name + event_type`，但继续兼容完整事件名。
3. 补 parser / aggregator 定向回归，覆盖 `trace_id` fallback 与 canonical request span。
4. 运行 `obs-local` 定向测试，确认旧协议不回归、新协议可被正确聚合。

## Risks

- 旧版 `summary_mapping` 大多按完整事件名配置，若兼容逻辑不完整会导致 request summary 丢失。
- request root span 与普通业务 span 的区分如果做得过宽，会把非 HTTP 事件错误归入请求视图。
- stage 名称归一改为优先 `span_name` 后，若某些日志错误写入了 span 名，会直接影响排行和详情页。
