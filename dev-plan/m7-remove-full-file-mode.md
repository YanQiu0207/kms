# M7 Remove Host Full-File Answering

## Goal

移除宿主全文模式相关能力，删除 `POST /ask-files`、对应服务逻辑、Codex 全文模式模板，以及仓库内相关示例与测试，只保留现有 `/ask` 与 `/verify` 主链路。

## Scope

- 删除 HTTP 接口：
  - `POST /ask-files`
  - 相关 request / response schema
- 删除服务层全文模式逻辑：
  - `QueryService.ask_files()`
  - 文档级去重与文件回查逻辑
- 删除仓库内适配资产：
  - `app/adapters/codex/kms-full-file.md`
  - `scripts/ask-files-context.json`
- 更新 README、API 契约与测试，移除全文模式描述
- 删除本机 skill：`C:\Users\YanQi\.codex\skills\kms-full-file-assistant`

## Non-Goals

- 不改变现有 `/ask`、`/search`、`/verify` 的输入输出语义
- 不回退其他 Codex / Claude 适配资产
- 不修改历史 M6 台账，只新增 M7 收口记录

## Flow

1. 移除仓库内 `/ask-files` 路由、schema、service 与测试。
2. 删除全文模式模板和示例请求文件。
3. 更新 README 与 API 契约，确保只暴露仍支持的接口。
4. 删除本机 `kms-full-file-assistant` skill 目录。
5. 运行定向回归，确认主链路未受影响。

## Risks

- 若有其他测试或文档仍依赖 `/ask-files`，会在回归或全文搜索时暴露遗漏。
- 本机 skill 位于仓库外，删除需要额外权限。
- 历史台账会保留 M6 已交付记录，需要通过 M7 说明当前已显式撤回该能力。
