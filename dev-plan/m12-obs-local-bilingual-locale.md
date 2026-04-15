# M12 obs-local Bilingual Locale

## Goal

为 `obs-local` 增加正式的多语言展示能力，支持：

- 后端配置默认语言模式
- 前端用户手动切换
- `zh` / `en` / `bilingual` 三种展示模式
- 技术标识保留原值，产品文案走统一翻译层

## Scope

- `obs-local/app/schemas.py`
- `obs-local/app/main.py`
- `obs-local/config.yaml`
- `obs-local/tests/test_stage4_api.py`
- `obs-local/frontend/src/api/client.ts`
- `obs-local/frontend/src/types/observability.ts`
- `obs-local/frontend/src/stores/ui-locale.ts`
- `obs-local/frontend/src/utils/i18n.ts`
- `obs-local/frontend/src/utils/labels.ts`
- `obs-local/frontend/src/views/DashboardView.vue`
- `obs-local/frontend/src/components/*`

## Design

### Backend

- 新增 `ui.default_locale`
- 新增 `/api/ui-settings`
- 前端初始化时读取后端默认语言

### Frontend

- 代码内部使用稳定英文 key
- 文案展示统一通过 locale store + translation map
- 用户切换语言后写入 `localStorage`
- 若没有本地覆盖，则回退到后端默认语言

### Rendering Rule

- 产品文案：`zh` / `en` / `bilingual`
- 技术标识：保留原文作为技术语义，不硬翻
- 语义标签：使用 `labels.ts` 输出本地化标签

## Acceptance

- 可通过 `/api/ui-settings` 读取默认语言
- 页面右上角可切换 `中文 / English / 双语`
- 标题、按钮、空态、状态标签、详情面板可随语言切换
- `/ask`、`query.plan.fetch` 等技术字段保留原值
- 前端类型检查和构建通过
- `obs-local` API 回归通过
