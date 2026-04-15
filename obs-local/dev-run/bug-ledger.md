# Bug 与问题台账

这里记录两类内容：

- 审核后被主会话接受的问题
- 开发过程中主动发现的 bug

| ID | 来源 | review_round_id | 阶段 | 严重级别 | 问题摘要 | accepted_by | Owner | 状态 | 修复方案 | verified_by | 验证结果 | 关闭时间 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BUG-0-001 | review | STAGE0-REVIEW-A-001 | 0 | 中 | `design_v1.md` 目录示意图未体现文档边界 | main-session | main-session | closed | 修正目录示意图 | main-session | 已核对修正后的目录树包含 `docs/` 与 `dev-run/` | 2026-04-15 |
| BUG-0-002 | review | STAGE0-REVIEW-B-001 | 0 | 高 | `agent-board.md` / `progress.md` 缺少任务与 ownership 审计字段 | main-session | main-session | closed | 增加 task id、写入范围、交接状态、执行记录模板 | main-session | 已核对新增字段与模板存在 | 2026-04-15 |
| BUG-0-003 | review | STAGE0-REVIEW-B-001 | 0 | 高 | review / bug / fix 台账缺少审计字段 | main-session | main-session | closed | 增加 review_round_id、accepted_by、verified_by 等字段 | main-session | 已核对三类台账的审计字段存在 | 2026-04-15 |
| BUG-0-004 | review | STAGE0-REVIEW-B-001 | 0 | 中 | `stage-status.md` 缺少阻塞原因与待清理 bug 字段 | main-session | main-session | closed | 增加 blocked_reason 与待清理 bug 列 | main-session | 已核对状态板可直接指向待清理 bug | 2026-04-15 |
| BUG-1-001 | review | STAGE1-REVIEW-A-001 / STAGE1-REVIEW-B-001 | 1 | 高 | `source_id` 被当作全局唯一，跨项目会串写 source 和 health | main-session | main-session | closed | 将 `sources` / `source_health` 调整为 `(project_id, source_id)` 语义 | main-session | 多项目重复 `source_id=main` 测试通过 | 2026-04-15 |
| BUG-1-002 | review | STAGE1-REVIEW-A-001 | 1 | 中 | `last_event_at` 用字符串比较，时间顺序可能错误 | main-session | main-session | closed | 按时间解析后再比较最新事件 | main-session | Stage 1 health 测试与编译检查通过 | 2026-04-15 |
| BUG-1-003 | review | STAGE1-REVIEW-A-001 | 1 | 中 | `ProjectHealth.status` 不会进入 `degraded` | main-session | main-session | closed | 根据 project staleness 推导 degraded | main-session | health 状态回归测试通过 | 2026-04-15 |
| BUG-1-004 | review | STAGE1-REVIEW-B-001 | 1 | 高 | `replace_project_sources()` 非原子，可能写出半成品配置 | main-session | main-session | closed | 改为单事务替换 project sources | main-session | Stage 1 测试和导入验证通过 | 2026-04-15 |
| BUG-1-005 | review | STAGE1-REVIEW-B-001 | 1 | 中 | 缺少多项目与 reload 场景测试 | main-session | main-session | closed | 补多项目 health 与 registry reload 测试 | main-session | `pytest obs-local/tests/test_stage1_health.py` 4 例通过 | 2026-04-15 |
| BUG-2-001 | review | STAGE2-REVIEW-A-001 / STAGE2-REVIEW-B-001 | 2 | 高 | `file_offsets` 只按 `log_path` 隔离，跨项目共享路径会串写 offset | main-session | main-session | closed | 将 offset 主键改为 `(project_id, source_id)`，tailer 按 source 读写并补历史迁移 | main-session | Stage 1 + Stage 2 测试 9 例通过；共享路径回归测试通过 | 2026-04-15 |
| BUG-2-002 | review | STAGE2-REVIEW-A-001 | 2 | 中 | `replace_project_sources()` 未拒绝重复 `source_id`，可能静默覆盖 source 配置 | main-session | main-session | closed | 在 state store 替换入口增加重复 `source_id` 显式校验 | main-session | 重复 source_id 回归测试通过 | 2026-04-15 |
| BUG-2-003 | review | STAGE2-REVIEW-A-001 | 2 | 中 | naive ISO8601 时间被误标成 `rfc3339`，丢失原始格式边界 | main-session | main-session | closed | parser 将无时区 ISO8601 标记为 `iso8601_naive` | main-session | parser 时间格式回归测试通过 | 2026-04-15 |
| BUG-2-004 | review | STAGE2-REVIEW-B-001 | 2 | 高 | 增量尾读会跳过下一轮才补全的尾部半行 | main-session | main-session | closed | 增量模式仅推进到最后一个已确认完整换行边界，未完成尾行保留到下轮重读 | main-session | 尾部半行补全回归测试通过 | 2026-04-15 |
| BUG-2-005 | review | STAGE2-REVIEW-B-001 | 2 | 中 | Stage 2 缺少共享路径 offset 隔离和尾部半行的关键回归测试 | main-session | main-session | closed | 增加共享路径、多项目、尾部半行、重复 source_id、naive ISO 时间测试 | main-session | `pytest obs-local/tests/test_stage2_ingestion.py` 5 例通过 | 2026-04-15 |
| BUG-3-001 | review | STAGE3-REVIEW-A-001 / STAGE3-REVIEW-B-001 | 3 | 高 | 聚合结果与公共 schema 契约不一致，`stages` / `top_stages` / `overview` 无法直接对齐 Stage 4 | main-session | main-session | closed | 对齐 aggregator 输出与 schema，补 `AggregationOverview`，将 `top_stages` / `stages` 统一为 `StageTiming` | main-session | Stage 1-3 测试 14 例通过；`py_compile` 通过 | 2026-04-15 |
| BUG-3-002 | review | STAGE3-REVIEW-B-001 | 3 | 高 | 有错误事件但无 terminal 的请求被误判成 `partial` | main-session | main-session | closed | 将 error signal 纳入请求失败判定，并避免把此类请求标成 partial | main-session | 新增回归测试通过 | 2026-04-15 |
| BUG-3-003 | review | STAGE3-REVIEW-B-001 | 3 | 高 | `build_request_detail()` 走全量重算路径且 lookup fallback 有边界 bug | main-session | main-session | closed | 改为按目标 request 过滤记录，并修正 `find_request_detail()` fallback | main-session | detail lookup 回归测试通过 | 2026-04-15 |
| BUG-3-004 | review | STAGE3-REVIEW-B-001 | 3 | 中 | Stage 3 缺少契约、detail lookup、无 terminal 失败请求的关键回归测试 | main-session | main-session | closed | 补充 2 个回归测试，覆盖失败请求误判与 detail 查询行为 | main-session | `pytest obs-local/tests/test_stage3_aggregator.py` 5 例通过 | 2026-04-15 |
| BUG-3-005 | review | STAGE3-REVIEW-A-001 | 3 | 中 | `request_type` 归一化优先级偏离设计，优先用了 path | main-session | main-session | closed | 调整为优先从 `api.*` 事件推导，再回退 path | main-session | Stage 3 测试与全量后端测试通过 | 2026-04-15 |
| BUG-4-006 | review | STAGE4-REVIEW-C-001 | 4 | 高 | `window` 过滤会放行 `timestamp=None` 的记录 | main-session | main-session | closed | `main.py` 的窗口过滤改为显式排除 `timestamp=None`，并补主链路回归 | main-session | `pytest obs-local/tests/test_stage4_main.py` 与全量后端 36 例通过 | 2026-04-15 |
| BUG-4-007 | review | STAGE4-REVIEW-C-001 | 4 | 中 | disabled source 因旧 `last_event_at` 被标成 `live` | main-session | main-session | closed | `main.py` 与 `api_projects.py` 统一 disabled source/offline 语义，并补 health/API 回归 | main-session | `pytest obs-local/tests/test_stage1_health.py obs-local/tests/test_stage4_api.py` 与全量后端 36 例通过 | 2026-04-15 |
| BUG-4-008 | review | STAGE4-REVIEW-C-001 | 4 | 高 | `/api/reload` 缺少 SSE 推送回归 | main-session | main-session | closed | 补 `/api/reload` -> `StreamHub` 推送测试，并保持 reload 发布 `health/overview/requests/errors/stages` | main-session | `pytest obs-local/tests/test_stage4_main.py` 与全量后端 36 例通过 | 2026-04-15 |
| BUG-4-009 | review | STAGE4-REVIEW-C-001 | 4 | 中 | 实时日志追加后，聚合与 stream hub 更新缺少回归覆盖 | main-session | main-session | closed | 增加日志追加后的 watcher/stream 回归，并实现后台 tail -> 聚合 -> 推送链路 | main-session | `pytest obs-local/tests/test_stage4_main.py obs-local/tests/test_stage4_stream.py` 与全量后端 36 例通过 | 2026-04-15 |
| BUG-5-001 | review | STAGE5-REVIEW-A-001 | 5 | 高 | 全局视图 `project=null` 会在下一次快照同步时被自动切回首个项目 | main-session | main-session | closed | 在前端 store 增加显式选择锁定，保留用户对 “All Projects” 的选择 | main-session | `npm run typecheck`、`npm run build` 通过 | 2026-04-15 |
| BUG-5-002 | review | STAGE5-REVIEW-B-001 | 5 | 高 | 快照并发请求存在竞态，旧响应可覆盖新状态 | main-session | main-session | closed | 在 `fetchSnapshot()` 引入 sequence 保护，只应用最新请求结果 | main-session | `npm run typecheck`、`npm run build` 通过 | 2026-04-15 |
| BUG-5-003 | review | STAGE5-REVIEW-B-001 | 5 | 中 | SSE 的 `health/overview` 更新后未同步 staleness/projectMeta，徽章状态陈旧 | main-session | main-session | closed | 在流更新路径补充 `applyProjectMetaFromCurrentSelection()` 回填逻辑 | main-session | `npm run typecheck`、`npm run build` 通过 | 2026-04-15 |
| BUG-10-001 | user-review | USER-AUDIT-2026-04-15-A | 10 | 高 | `obs-local` 整体缺少结构化日志输出，TailerError 被静默吞掉 | main-session | main-session | closed | 新增 `app/observability.py`，接入 startup/shutdown/http/reload/tail/source load 日志，并为 tail/load 错误显式记录 error log | main-session | `pytest obs-local/tests/test_stage4_main.py` 与全量后端 43 例通过 | 2026-04-15 |
| BUG-10-002 | user-review | USER-AUDIT-2026-04-15-A | 10 | 中 | `app/tailer.py` 的 `chunk_size` 硬编码为 64KB，未配置化 | main-session | main-session | closed | 引入 `tailer.chunk_size` 配置并由 `main.py` 传入 `FileTailer` | main-session | 聚焦回归与全量后端 43 例通过 | 2026-04-15 |
| BUG-10-003 | user-review | USER-AUDIT-2026-04-15-A | 10 | 中 | `app/web.py` 的 `StreamHub.max_queue_size` 硬编码为 256，未配置化 | main-session | main-session | closed | 引入 `stream.max_queue_size` 配置并由 `create_app()` 传入 `StreamHub` | main-session | 新增配置与日志回归，`pytest obs-local/tests` 43 例通过 | 2026-04-15 |
| BUG-10-004 | user-review | USER-AUDIT-2026-04-15-A | 10 | 中 | `poll_interval`、`top_n`、`request_stage_limit` 硬编码在主链路 | main-session | main-session | closed | 引入 `runtime.tail_poll_interval_seconds` 与 `aggregation.*` 配置，并在聚合主链路显式使用 | main-session | 新增 aggregation limit 回归，`pytest obs-local/tests` 43 例通过 | 2026-04-15 |
| BUG-10-005 | user-review | USER-AUDIT-2026-04-15-A | 10 | 中 | `StreamBatcher.window_ms/max_items` 硬编码，未配置化 | main-session | main-session | closed | 引入 `stream.batch_window_ms` / `stream.batch_max_items` 并接入 SSE router 和 batcher | main-session | `pytest obs-local/tests/test_stage4_stream.py` 与全量 43 例通过 | 2026-04-15 |
| BUG-11-001 | user-review | USER-AUDIT-2026-04-15-B | 11 | 高 | `app/state_store.py` 的 `file_offsets` 迁移失败后会破坏原子性，留下不可恢复的中间态 | main-session | main-session | closed | 移除迁移 `executescript`，并为 `file_offsets` 升级添加显式 `SAVEPOINT` 回滚保护 | main-session | `pytest obs-local/tests/test_stage2_ingestion.py::test_state_store_migration_rolls_back_when_file_offsets_upgrade_fails` 与全量 52 例通过 | 2026-04-15 |
| BUG-11-002 | user-review | USER-AUDIT-2026-04-15-B | 11 | 高 | `app/main.py` 中 `parsed_records` 常驻追加，长期运行会无界增长 | main-session | main-session | closed | 新增 `runtime.max_cached_records` 配置，并在 rebuild/tail 主链路统一裁剪缓存 | main-session | `pytest obs-local/tests/test_stage4_main.py::test_stage4_main_caps_cached_records_to_runtime_limit` 与全量 52 例通过 | 2026-04-15 |
| BUG-11-003 | user-review | USER-AUDIT-2026-04-15-B | 11 | 高 | `POST /api/projects` 可接受任意 `log_path`，存在越权读取任意文件风险 | main-session | main-session | closed | 对动态项目注册增加允许根目录校验，仅允许工作目录、state db 目录与既有日志目录下的路径 | main-session | `pytest obs-local/tests/test_stage4_api.py::test_post_project_rejects_log_path_outside_allowed_roots` 与全量 52 例通过 | 2026-04-15 |
| BUG-11-004 | user-review | USER-AUDIT-2026-04-15-B | 11 | 中 | `OBS_LOCAL_PORT=abc` 会直接触发原始转换异常，配置入口缺少容错与回归 | main-session | main-session | closed | 将 server 环境变量覆盖统一走校验路径，并为非法端口返回明确配置错误 | main-session | `pytest obs-local/tests/test_stage0_config.py` 与全量 52 例通过 | 2026-04-15 |
| BUG-11-005 | user-review | USER-AUDIT-2026-04-15-B | 11 | 中 | parser / aggregator / tailer 的关键边界路径缺少回归，问题定位成本高 | main-session | main-session | closed | 补时区 fallback、epoch_s、bool 时间、错误判定组合、无换行/无尾换行尾读等回归测试 | main-session | `pytest obs-local/tests` 52 例通过 | 2026-04-15 |

## 状态定义

- `open`
- `修复中`
- `待验证`
- `closed`
- `rejected`

## 规则

- 凡是“接受”的审核意见，都必须写入这里。
- 没有验证结果，不得关闭。
- 若拒绝某条意见，理由必须写回 `review-log.md`。
