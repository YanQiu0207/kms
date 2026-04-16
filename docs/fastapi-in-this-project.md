# FastAPI 在这个项目里的作用

这份文档面向对 FastAPI 不熟悉、但需要快速理解本仓库服务边界的读者。

重点回答两个问题：

- FastAPI 在这个项目里到底负责什么
- 一次 `/ask` 请求进入后，代码按什么顺序执行

## 先看结论

FastAPI 在这个项目里更像“知识库能力的 Web 外壳”，而不是检索算法本身。

它主要负责：

1. 把索引、检索、问答、校验这些能力暴露成 HTTP 接口
2. 校验请求和响应的数据结构
3. 管理服务启动、预热、关闭
4. 统一记录请求日志、耗时和错误

真正的业务逻辑主要在：

- [app/services/indexing.py](/E:/github/mykms/app/services/indexing.py:97)
- [app/services/querying.py](/E:/github/mykms/app/services/querying.py:42)

可以先把职责分成两层：

- FastAPI 层：接请求、校验参数、调用服务、返回 JSON
- 业务层：做索引、检索、rerank、拒答判断、prompt 装配

## 入口在哪里

FastAPI 入口在 [app/main.py](/E:/github/mykms/app/main.py:43)。

这里最重要的函数是：

- `create_app(...)`：创建应用、注册生命周期、挂中间件和路由
- `run()`：用 `uvicorn` 启动服务

应用启动后会暴露这些接口：

- `GET /health`
- `GET /stats`
- `POST /index`
- `POST /search`
- `POST /ask`
- `POST /verify`

对应代码见 [app/main.py](/E:/github/mykms/app/main.py:114)。

## FastAPI 在这个项目里的具体职责

### 1. 提供统一的 HTTP API

项目不是让外部代码直接 `import QueryService` 来用，而是通过本地 HTTP 服务调用。

例如：

 - [README.md](/E:/github/mykms/README.md:22) 里用 `uvicorn app.main:create_app --factory` 启动服务
- [app/adapters/codex/kms.md](/E:/github/mykms/app/adapters/codex/kms.md:3) 里要求通过 `curl` 调 `/search`、`/ask`、`/verify`

这意味着 FastAPI 的一个核心价值是把知识库能力变成稳定的本地服务协议，让脚本、适配器、工具都按同一套接口访问。

### 2. 做请求/响应校验

接口的数据结构定义在 [app/schemas.py](/E:/github/mykms/app/schemas.py:14)。

例如：

- `AskRequest` 约束 `/ask` 的请求体结构，见 [app/schemas.py](/E:/github/mykms/app/schemas.py:106)
- `AskResponse` 约束 `/ask` 的返回结构，见 [app/schemas.py](/E:/github/mykms/app/schemas.py:147)

FastAPI 会自动基于这些模型做几件事：

- 检查必填字段是否存在
- 检查字段类型是否正确
- 执行自定义校验，比如 `question` 不能为空
- 把 Python 对象序列化成 JSON 响应

所以 FastAPI 不只是“收字符串”，而是在接口边界做了明确的数据契约约束。

### 3. 管理生命周期和运行时资源

在 [app/main.py](/E:/github/mykms/app/main.py:49)，项目使用了 FastAPI 的 `lifespan`。

这里负责：

- 启动时按配置决定是否执行 `query_service.warmup()`
- 关闭时执行 `query_service.close()`

这类逻辑如果没有 FastAPI 托管，通常就得手动在脚本里拼装，边界会更散。

### 4. 做中间件、日志和错误处理

HTTP middleware 在 [app/main.py](/E:/github/mykms/app/main.py:71)。

这层会：

- 为每个请求生成 `request_id`
- 记录 `http.request.start`
- 统计整个请求耗时
- 记录 `http.request.end`
- 在异常时记录 `http.request.error`

业务侧抛出异常后，路由函数会把它转成 `HTTPException`，例如 [app/main.py](/E:/github/mykms/app/main.py:145)。

所以 FastAPI 在这里还承担了“统一入口治理”的职责。

## 一次 `/ask` 请求是怎么跑的

下面用一个典型请求说明主流程：

```json
{
  "question": "为什么个人知识库不能只做向量检索？",
  "queries": [
    "为什么个人知识库不能只做向量检索？",
    "混合检索 优势"
  ],
  "rerank_top_k": 6
}
```

### 第一步：请求进入 FastAPI

入口路由在 [app/main.py](/E:/github/mykms/app/main.py:171)。

在进入路由函数前，FastAPI 会先把请求体解析为 `AskRequest`，见 [app/schemas.py](/E:/github/mykms/app/schemas.py:106)。

这一步会做基础校验，例如：

- `question` 不能为空
- `queries` 中的空字符串会被清理掉
- `recall_top_k` / `rerank_top_k` 不能是负数

如果校验失败，请求不会进入业务层。

### 第二步：HTTP middleware 记录请求日志

请求会先经过 [app/main.py](/E:/github/mykms/app/main.py:71) 的中间件。

这里会做这些事：

1. 生成 `request_id`
2. 记录请求开始日志
3. 调用真正的路由处理函数
4. 记录请求结束日志和耗时

这一层是典型的 FastAPI 运行时职责，不负责检索逻辑本身。

### 第三步：`/ask` 路由调用 `QueryService`

路由函数本身很薄，代码在 [app/main.py](/E:/github/mykms/app/main.py:172)。

它主要做三件事：

1. 记录 `api.ask` 这层耗时
2. 调 `app.state.query_service.ask(...)`
3. 把返回结果组装成 `AskResponse`

这里的 `app.state.query_service` 在应用创建时挂到 FastAPI 实例上，见 [app/main.py](/E:/github/mykms/app/main.py:67)。

这说明 FastAPI 在本项目里是“编排层”，不是检索实现层。

### 第四步：业务层规范化查询

真正的查询逻辑在 [app/services/querying.py](/E:/github/mykms/app/services/querying.py:91)。

`QueryService.ask(...)` 会先确定有效查询词：

- 如果调用方传了 `queries`，优先用它们
- 如果没传，就回退到 `question`
- 如果最终只有一个 query，还会自动扩展出几个变体

扩展逻辑在 [app/services/querying.py](/E:/github/mykms/app/services/querying.py:183)。

这样做的目的，是同时兼顾：

- 原始问句的语义完整性
- 词法检索的关键词命中率

### 第五步：进入搜索主流程

`ask(...)` 会继续调用 `search(...)`，见 [app/services/querying.py](/E:/github/mykms/app/services/querying.py:53)。

这一步先查一个内存 LRU 缓存：

- 命中缓存：直接复用结果
- 未命中：进入真正的检索流程

这仍然属于业务层，不是 FastAPI 提供的能力。

### 第六步：混合检索和 rerank

这里的核心目标是找出最相关的证据块，而不是直接生成最终答案。

主流程在 [docs/ask-and-ingest.md](/E:/github/mykms/docs/ask-and-ingest.md:81) 也有详细说明，大体顺序是：

1. 词法检索：查 SQLite FTS5
2. 语义检索：查 Chroma 向量库
3. RRF 融合：把两路结果合并
4. rerank：用 reranker 再排一次序

因此 `/ask` 背后并不是“把问题直接扔给大模型”，而是先完成证据检索和排序。

### 第七步：拒答判断

检索结果回来后，`QueryService.ask(...)` 会判断证据是否足够，见 [app/services/querying.py](/E:/github/mykms/app/services/querying.py:111)。

如果证据不足，就会返回：

- `abstained=true`
- `prompt=""`
- `sources=[]`

也就是让上层调用方直接拒答。

### 第八步：组装 `prompt` 和 `sources`

如果证据足够，就继续进入 prompt 装配。

项目当前的 `/ask` 不是直接返回“最终回答正文”，而是返回：

- 是否拒答
- 检索置信度
- 给宿主模型使用的 `prompt`
- 证据 `sources`

返回结构定义在 [app/schemas.py](/E:/github/mykms/app/schemas.py:147)。

这个设计说明项目当前更像“证据检索与 prompt 编排服务”。

### 第九步：FastAPI 返回标准 JSON

业务层结果返回到路由函数后，FastAPI 会把它序列化成 JSON 响应。

如果过程中抛出运行时异常，路由函数会转成 HTTP 500，见 [app/main.py](/E:/github/mykms/app/main.py:181)。

到这里，一次 `/ask` 请求的主流程就结束了。

## 为什么这里要用 FastAPI

如果没有 FastAPI，这个项目当然也能写成纯 Python 函数调用，但会有几个明显问题：

1. 外部适配器不容易复用  
   现在 Claude Code、Codex、脚本都可以直接走 HTTP 协议，而不是耦合 Python 内部实现。

2. 接口边界不清晰  
   通过 `AskRequest`、`AskResponse` 这些模型，输入输出契约是显式的。

3. 生命周期管理更分散  
   warmup、close、日志、中间件都需要自己拼。

4. 运行和排障不方便  
   现在可以直接通过 `/health`、`/stats` 探活和看配置，也能按 `request_id` 查日志。

所以在这个仓库里，FastAPI 的价值不是“让代码更高级”，而是：

- 把知识库能力包装成稳定的本地服务
- 把接口边界、生命周期和可观测性统一起来

## 读代码建议

如果你刚接触这个项目，建议按下面顺序读：

1. [app/main.py](/E:/github/mykms/app/main.py:43)
2. [app/schemas.py](/E:/github/mykms/app/schemas.py:49)
3. [app/services/querying.py](/E:/github/mykms/app/services/querying.py:42)
4. [app/services/indexing.py](/E:/github/mykms/app/services/indexing.py:97)
5. [docs/ask-and-ingest.md](/E:/github/mykms/docs/ask-and-ingest.md:10)

如果只想抓重点，可以先记一句话：

FastAPI 负责“把能力变成服务”，`services/`、`retrieve/`、`answer/` 负责“真正把问题处理掉”。
