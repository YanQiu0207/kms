# obs-local 开发总计划

## 总目标

交付一个本地可运行的 `obs-local`，具备以下能力：

- 读取多个项目的本地结构化日志
- 聚合请求、报错、阶段耗时
- 通过 SSE 向前端实时推送更新
- 使用 `Vue 3 + Vite + TypeScript` 构建正式前端
- UI 达到“漂亮、专业、可长期使用”的质量标准
- 全流程采用“多 agent 并行开发 + 每阶段双评审闸门”

## 总体协作方式

- 主会话：协调、拆任务、合并、定闸门、维护 md 台账
- 实现 agent：按文件范围并行开发
- 审核 agent A：重点看协议、边界、数据语义
- 审核 agent B：重点看实现、回归风险、测试缺口

任何阶段都必须满足：

1. 开发完成
2. 本地验证完成
3. 两个审核 agent 都完成审核
4. 审核中被接受的问题全部修复
5. 修复验证完成
6. 主会话批准后才能进入下一阶段

## 计划依据

本计划默认以以下文档为准：

- `obs-local/docs/design_v1.md`
- `obs-local/docs/design_v1_claude.md`

其中需要强制吸收的设计约束包括：

- 请求失败与错误事件分开建模
- `http.request.error` 视为请求终止事件之一
- 阶段统计不能直接把父子阶段 inclusive duration 混排
- 时间戳要支持无时区输入并按 source 配置补齐
- health / staleness 要在后端阶段就定清
- 前端默认采用 `Vue 3 + Vite + TypeScript`
- UI 默认支持实时更新，不依赖手动刷新

## 阶段总览

| 阶段 | 名称 | 目标 |
|---|---|---|
| 0 | 治理与工作区整理 | 把目录、文档、台账和协作规则定住 |
| 1 | 后端基础骨架 | 配置、schema、registry、状态存储、健康模型 |
| 2 | 日志接入 | tailer、parser、offset、回放、时间戳归一化 |
| 3 | 聚合语义 | 请求、错误、阶段统计，补齐 partial/error/self duration 语义 |
| 4 | 后端 API 与 SSE | 对前端提供 REST API 和实时流 |
| 5 | 前端基础骨架与设计系统 | Vue 工程、tokens、布局壳、共享状态模型 |
| 6 | 首页仪表盘 | 摘要卡、请求列表、错误列表、阶段排行、健康状态 |
| 7 | 单请求详情与实时交互 | 时间线、详情视图、实时更新、断线恢复 |
| 8 | 视觉打磨与集成加固 | 响应式、动效、稳定性、集成测试、运行说明 |
| 9 | Phase 2 过滤能力 | 列表过滤、过滤状态联动、过滤回归验证 |
| 10 | 配置化与日志加固 | 运行参数配置化、结构化日志、TailerError 可观测性 |

---

## Stage 0：治理与工作区整理

目标：

- 建立稳定目录结构
- 把设计文档和代码目录分开
- 建立开发进度、审核、bug、fix 的 md 台账

交付物：

- `obs-local/docs/`
- `obs-local/app/`
- `obs-local/frontend/`
- `obs-local/data/`
- `obs-local/dev-run/`
- 运行手册与阶段计划

适合并行的 agent：

- agent A：目录整理与文档迁移
- agent B：开发治理台账
- agent C：前后端空目录骨架

阶段风险：

- 文档与代码混放，后续结构继续混乱
- 没有把评审与修复流程写死，后面很快失控

通过标准：

- 工作区结构清晰
- 开发台账可直接使用
- 主流程规则已经写入 md

---

## Stage 1：后端基础骨架

目标：

- 把后端基础模型和配置体系先立住

交付物：

- `app/config.py`
- `app/schemas.py`
- `app/registry.py`
- 状态库基础表结构
- source 加载模型
- `/api/health` 的基础契约

适合并行的 agent：

- agent A：配置与 schema
- agent B：registry 与 source 模型
- agent C：状态存储与 health 契约

重点审核风险：

- `project / source / service` 关系定义错误
- `config.yaml` 与本地状态库优先级不清
- health 模型过早写死，后续很难扩展
- 后端目录和运行入口没有定好，后续集成时冲突

通过标准：

- 后端基础对象已稳定
- 能支撑 Stage 2 的 tailer / parser 开发

---

## Stage 2：日志接入

目标：

- 稳定读取本地 JSONL 日志，并处理 offset、坏行、截断、回放

交付物：

- `app/tailer.py`
- `app/parser.py`
- offset 持久化
- 重扫与回放逻辑
- 时间戳解析与时区归一化
- 坏行降级处理

适合并行的 agent：

- agent A：tailer 与文件偏移
- agent B：parser 与时间戳归一化
- agent C：回放、截断、容错逻辑

重点审核风险：

- 数据重复读或漏读
- 无时区时间被错误解释
- 日志截断、轮转、回放行为不稳定
- parser 对旧日志、新日志和缺字段日志的兼容不一致

通过标准：

- 能稳定读取 `mykms` 的真实日志
- offset / replay 行为可复现

---

## Stage 3：聚合语义

目标：

- 把原始事件变成稳定、可读、可供 UI 使用的聚合视图

交付物：

- `app/aggregator.py`
- 请求摘要
- 错误摘要
- 阶段统计
- `summary` 映射
- `partial` 请求支持
- `leaf stage` 或 `self duration` 规则

适合并行的 agent：

- agent A：请求聚合
- agent B：阶段统计与嵌套去重
- agent C：错误语义、partial、summary 映射

重点审核风险：

- `http.request.error` 断尾处理错误
- `status` 和 `status_code` 语义混淆
- 父阶段和子阶段重复计时，导致排行失真
- `summary` 映射与 UI 字段假设脱节

通过标准：

- 请求 / 错误 / 阶段三类聚合口径一致
- 设计文档里定义的特殊语义已落地

---

## Stage 4：后端 API 与 SSE

目标：

- 把聚合结果稳定提供给前端，并支持实时推送

交付物：

- `/api/projects`
- `/api/overview`
- `/api/health`
- `/api/requests`
- `/api/requests/{request_id}`
- `/api/errors`
- `/api/stages`
- `/api/reload`
- `/api/stream`

适合并行的 agent：

- agent A：REST API
- agent B：SSE 流和节流
- agent C：health / staleness / replay 状态输出

重点审核风险：

- API 契约不稳定
- SSE 推送粒度失控
- 前端无法区分“空闲”和“失联”
- `/api/health` 与 `/api/overview` 的状态口径不一致

通过标准：

- 前端能稳定消费 API 和 SSE
- 实时流断线重连语义已定

---

## Stage 5：前端基础骨架与设计系统

目标：

- 先把 `Vue 3 + Vite + TS` 工程、设计 tokens、共享状态模型定住

交付物：

- Vue 工程骨架
- App Shell
- 基础路由壳
- 设计 tokens
- 基础组件雏形
- SSE / store 状态模型

适合并行的 agent：

- agent A：脚手架与构建配置
- agent B：设计 tokens 与全局样式
- agent C：共享 store 与 SSE composable

重点审核风险：

- 组件接口定义太死
- transport 状态和 UI 状态耦合
- 视觉体系过弱，后续要大改

通过标准：

- 前端项目可运行
- tokens 生效
- 状态模型能接 Stage 6 页面

---

## Stage 6：首页仪表盘

目标：

- 先把用户第一眼看到的主界面做出来

交付物：

- 摘要卡
- 最近请求列表
- 最近错误列表
- 阶段排行
- 健康状态与 staleness 提示
- 空状态与加载态

适合并行的 agent：

- agent A：摘要卡与健康区
- agent B：请求 / 错误列表
- agent C：阶段排行与低样本展示

重点审核风险：

- 首页像拼出来的，不像完整产品
- 摘要卡和列表口径不一致
- 可读性差，信息太挤

通过标准：

- 首屏信息层级成立
- 静态数据下也已经像正式产品页，不是工具页

---

## Stage 7：单请求详情与实时交互

目标：

- 把请求链路看清楚，并真正实现“日志变更即 UI 更新”

交付物：

- 请求详情抽屉或详情页
- 事件时间线
- 阶段详情
- 错误详情
- SSE 驱动的局部更新
- 连接状态指示
- 暂停 / 恢复实时模式
- 断线重连

适合并行的 agent：

- agent A：详情页布局与交互
- agent B：时间线可视化
- agent C：实时更新、连接状态、重连逻辑

重点审核风险：

- 详情页和列表页状态不一致
- 高频更新时 UI 闪烁或滚动跳动
- 请求异常时详情链路读不懂

通过标准：

- 单请求从开始到结束可读
- UI 无需手动刷新即可更新
- 断线后可恢复

---

## Stage 8：视觉打磨与集成加固

目标：

- 把产品从“能用”收口到“稳定、好看、长期可用”

交付物：

- 响应式适配
- 动效与细节收口
- 视觉一致性修订
- 稳定性修复
- 集成测试
- 本地运行说明

适合并行的 agent：

- agent A：视觉打磨与响应式
- agent B：运行时加固与边界修复
- agent C：集成测试与开发运行流

重点审核风险：

- 最后阶段局部好看但整体割裂
- 修稳定性时破坏实时流
- 视觉打磨导致布局回归

通过标准：

- 视觉质量符合 `docs/design_v1.md`
- 核心链路稳定
- 可供后续迭代继续开发

---

## Stage 9：Phase 2 过滤能力

目标：

- 落地设计文档中 Phase 2 的首批过滤能力
- 不破坏已有实时流、详情抽屉和窗口切换语义

交付物：

- 请求过滤：路径、方法、状态、请求类型
- 错误过滤：路径、错误类型、状态码
- 阶段过滤：阶段名
- 前端过滤工具栏与空态提示
- 过滤查询参数接线与回归测试

适合并行的 agent：

- agent A：store / API client 过滤状态接线
- agent B：Requests / Errors / Stages UI 过滤工具栏
- agent C：过滤 API 回归测试与文档

重点审核风险：

- 过滤状态与 SSE 更新互相覆盖
- 过滤后空态仍沿用“无数据”文案，误导诊断
- 过滤参数遗漏，导致窗口切换或项目切换后结果回退
- 过滤 UI 只做前端假筛选，和后端真实数据口径不一致

通过标准：

- 三个主工作区都可直接操作过滤
- 过滤后切换 `window / project / reload` 仍保持口径一致
- 过滤开启时 SSE 更新不会把列表刷回未过滤状态

---

## Stage 10：配置化与日志加固

目标：

- 收口未配置化的运行参数
- 为 `obs-local` 补齐结构化日志与 TailerError 可观测性

交付物：

- `logging / runtime / tailer / stream / aggregation` 配置段
- `obs-local/app/observability.py` 结构化日志模块
- 启动、关闭、reload、tail、HTTP 请求日志
- TailerError / source load error 显式日志
- 配置与日志回归测试

适合并行的 agent：

- agent A：配置 schema 与运行时接线
- agent B：结构化日志与异常可观测性
- agent C：回归测试与 README

重点审核风险：

- 新配置只写入 schema，没有真正接线到运行路径
- logging handler 与 pytest / uvicorn 冲突
- TailerError 虽记录 health，但日志仍缺失
- 调整聚合函数签名后，回归测试未同步

通过标准：

- 相关运行参数不再硬编码在主链路
- 启动 / 请求 / reload / tail 错误具备结构化日志
- 全量 `obs-local/tests` 通过

---

## Stage 11：稳定性与安全补缺

目标：

- 收口用户审查指出的高风险稳定性与安全问题
- 为 parser / aggregator / tailer / config 增补缺失边界回归

交付物：

- `file_offsets` 迁移显式回滚保护
- `parsed_records` 内存缓存上界与裁剪日志
- `POST /api/projects` 的 `log_path` 允许根目录校验
- `OBS_LOCAL_PORT` 配置容错
- parser / aggregator / tailer / config 边界测试

适合并行的 agent：

- agent A：状态存储迁移与主链路缓存治理
- agent B：API 路径边界与配置容错
- agent C：parser / aggregator / tailer 回归测试

重点审核风险：

- 迁移失败后仍残留 `file_offsets_legacy`
- 缓存上界引入后，请求详情或过滤口径退化
- 动态项目注册拦截过宽或过窄，误伤合法路径
- 配置容错只补提示，未真正走到运行入口

通过标准：

- 迁移失败后数据库可回到迁移前状态
- `parsed_records` 不再无界增长
- 动态项目注册无法越权接入任意文件路径
- 全量 `obs-local/tests` 通过

---

## 台账使用规则

- `stage-status.md`：记录每个阶段是否已开发、已审核、已放行
- `agent-board.md`：记录当前有哪些 agent、各自负责哪些文件
- `progress.md`：按时间记录执行进展
- `review-log.md`：记录每个阶段的双评审结果
- `bug-ledger.md`：记录被接受的问题和 bug
- `fix-log.md`：记录 bug / 审核问题是如何被修复和验证的
