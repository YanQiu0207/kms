# M9 mykms Canonical Event Protocol Cutover

## Goal

将 `mykms` 的结构化日志协议正式切到 canonical 形态：

- `event`: 仅输出 `start` / `end` / `error`
- `span_name`: 独立承载业务名，例如 `http.request`、`api.ask`
- `message`: 保留完整可读事件名，例如 `http.request.end`

这样既满足协议正交，也不牺牲本地排障时的人眼可读性。

## Scope

- `app/observability.py`
  - formatter 输出改为 canonical `event`
  - `timed_operation()` 内部 start/error/end 事件改为纯事件名
- `app/main.py`
  - HTTP middleware 的 request root span 改为纯事件名调用
- `tests/test_observability.py`
  - 回归断言切到 canonical 协议
- 台账同步
  - `dev-run/stage-status.md`
  - `dev-run/progress.md`

## Non-Goals

- 本轮不继续清理所有非核心业务字段到纯 `attributes`
- 不改 `obs-local` API 契约或前端视图
- 不处理启动脚本 / PID 记账问题

## Flow

1. 新增 M9 阶段，登记正式切协议。
2. 调整 formatter 与调用点，确保落盘事件统一为 `start|end|error`。
3. 更新 `mykms` 回归测试，验证 `span_name` / `event_type` / `message`。
4. 追加运行 `obs-local` 定向回归，确认新日志仍可被消费。

## Risks

- 若 formatter 与调用点只改了一边，可能出现 `event=start` 但 `message=start`，丢失可读语义。
- 若 request root span 的纯事件名调用漏掉 `span_name`，`obs-local` 将无法把它识别成请求生命周期。
- 现有测试大多围绕完整事件名写断言，本轮若改得不彻底会出现成片回归失败。
