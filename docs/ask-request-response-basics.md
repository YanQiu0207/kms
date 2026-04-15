# `AskRequest` / `AskResponse` 入门说明

这份文档面向第一次接触 `FastAPI + Pydantic` 的读者。

重点回答四个问题：

- `Pydantic` 是什么
- `queries: list[str] = Field(default_factory=list)` 是什么意思
- `recall_top_k: int | None = None` 是什么意思
- `BaseSchema` 和 `field_validator` 在这个项目里怎么工作

## 先看结论

在这个项目里：

- `AskRequest` 表示 `/ask` 接口“接收什么 JSON”
- `AskResponse` 表示 `/ask` 接口“返回什么 JSON”
- `Pydantic` 负责把 JSON 和 Python 对象互相转换，并在边界做校验
- `FastAPI` 负责在收到 HTTP 请求后自动调用这些模型

相关代码：

- `AskRequest` 定义在 [app/schemas.py](/E:/github/mykms/app/schemas.py:106)
- `AskResponse` 定义在 [app/schemas.py](/E:/github/mykms/app/schemas.py:147)
- `/ask` 路由定义在 [app/main.py](/E:/github/mykms/app/main.py:171)

相关阅读：

- 速查版见 [docs/ask-request-response-cheatsheet.md](/E:/github/mykms/docs/ask-request-response-cheatsheet.md:1)

## `Pydantic` 是什么

`Pydantic` 可以理解成“带类型校验和 JSON 转换能力的数据模型库”。

普通 Python 类通常只是保存数据；`Pydantic` 模型除了保存数据，还会做这些事：

1. 按类型声明校验输入数据
2. 在创建对象时执行清洗逻辑
3. 把对象序列化成 JSON 友好的结构

例如 [app/schemas.py](/E:/github/mykms/app/schemas.py:106) 里的 `AskRequest`：

```python
class AskRequest(BaseSchema):
    question: str
    queries: list[str] = Field(default_factory=list)
    recall_top_k: int | None = None
    rerank_top_k: int | None = None
```

这不只是“定义了四个属性”，还定义了：

- 哪些字段存在
- 每个字段应该是什么类型
- 哪些字段可选
- 创建对象时应不应该报错

## `AskRequest` 是什么

`AskRequest` 是 `/ask` 接口的请求体模型，也就是“客户端应该怎么传参”。

字段含义：

- `question`：必填，用户真正的问题
- `queries`：可选，额外检索词列表
- `recall_top_k`：可选，召回阶段取多少条
- `rerank_top_k`：可选，重排阶段取多少条

例如下面这个 JSON 就能被解析成一个 `AskRequest`：

```json
{
  "question": "什么是向量检索？",
  "queries": ["向量检索", "embedding search"],
  "recall_top_k": 20,
  "rerank_top_k": 5
}
```

## `AskResponse` 是什么

`AskResponse` 是 `/ask` 接口的响应模型，也就是“服务端会返回什么结构”。

定义见 [app/schemas.py](/E:/github/mykms/app/schemas.py:147)：

```python
class AskResponse(BaseSchema):
    abstained: bool
    confidence: float
    prompt: str
    sources: list[AskSource] = Field(default_factory=list)
    abstain_reason: str | None = None
```

字段含义：

- `abstained`：是否拒答
- `confidence`：置信度
- `prompt`：给宿主模型使用的提示词
- `sources`：证据来源列表
- `abstain_reason`：拒答原因

其中 `sources` 里的每一项都是 `AskSource`，表示单条证据的文件、位置、文本和分数。

## `queries: list[str] = Field(default_factory=list)` 是什么意思

这行可以拆成三段：

- `queries`：字段名
- `list[str]`：字段类型是“字符串列表”
- `Field(default_factory=list)`：默认值是“每次创建对象时新建一个空列表”

它的作用不是简单等于 `[]`，而是避免可变默认值带来的共享问题。

推荐这样写：

```python
queries: list[str] = Field(default_factory=list)
```

不推荐这样写：

```python
queries: list[str] = []
```

原因是 `list` 是可变对象。`default_factory=list` 能确保每个模型实例拿到的是自己的新列表，而不是和别的实例共用一个默认列表。

## `recall_top_k: int | None = None` 是什么意思

这行表示：

- `recall_top_k` 可以是 `int`
- 也可以是 `None`
- 如果调用方不传，默认值就是 `None`

这等价于“可选整数”。

它比直接写成 `int = 0` 更清楚，因为它区分了两种不同语义：

- `None`：调用方没有指定，让服务端决定默认行为
- 某个整数：调用方明确指定了值

在接口设计里，这种区分很常见，因为“未传”和“传了 0”通常不是一回事。

## `BaseSchema` 是怎么实现的

定义见 [app/schemas.py](/E:/github/mykms/app/schemas.py:11)：

```python
class BaseSchema(BaseModel):
    if ConfigDict is None:
        class Config:
            extra = "ignore"
    else:
        model_config = ConfigDict(extra="ignore")
```

它本质上是所有接口模型的公共父类：

- `BaseModel` 是 `Pydantic` 提供的基础模型
- `BaseSchema` 在 `BaseModel` 上加了统一配置
- `AskRequest`、`AskResponse` 等模型再继承 `BaseSchema`

最关键的配置是：

```python
extra = "ignore"
```

这表示如果请求里多传了模型里没有定义的字段，`Pydantic` 会忽略它，而不是直接报错。

例如：

```json
{
  "question": "什么是向量检索？",
  "unknown_field": "ignored"
}
```

这里的 `unknown_field` 不会进入模型，也不会让接口炸掉。

### 为什么同时写了 `ConfigDict` 和 `Config`

这段代码还做了一层 `Pydantic v1 / v2` 兼容：

- v2 常用 `ConfigDict` 和 `field_validator`
- v1 常用内部 `Config` 类和 `validator`

所以项目里先尝试导入新写法；如果失败，就退回旧写法。这样同一份 schema 代码能在两个主版本上都正常工作。

## `field_validator` 是怎么工作的

看 [app/schemas.py](/E:/github/mykms/app/schemas.py:112)：

```python
@field_validator("question")
@classmethod
def _validate_question(cls, value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("question cannot be empty")
    return stripped
```

它表示：在 `question` 字段写入模型之前，先执行这个函数。

这个函数做了两件事：

1. 去掉首尾空格
2. 如果结果为空字符串，直接报错

所以：

- 输入 `"  什么是向量检索？  "`，最终会被清洗成 `"什么是向量检索？"`
- 输入 `"   "`，会校验失败

同样的思路也用于：

- `queries`：去掉空格并过滤空字符串，见 [app/schemas.py](/E:/github/mykms/app/schemas.py:120)
- `recall_top_k` / `rerank_top_k`：阻止负数，见 [app/schemas.py](/E:/github/mykms/app/schemas.py:126)

## 为什么要写 `@classmethod`

`@classmethod` 表示这是一个“类方法”，第一个参数是 `cls`，不是实例方法里的 `self`。

在字段校验阶段，模型实例通常还没完全构造好，所以把校验器写成类方法更自然，也符合 `Pydantic` 的常见写法。

这里虽然没有真正用到 `cls`，但保留这个签名是标准写法。

## FastAPI 怎么把 JSON 变成 `AskRequest`

`/ask` 路由定义在 [app/main.py](/E:/github/mykms/app/main.py:171)：

```python
@app.post("/ask", response_model=AskResponse, tags=["answer"])
def ask(request: AskRequest) -> AskResponse:
```

这里最关键的是 `request: AskRequest`。

FastAPI 看到这个类型标注后，会自动执行下面这条链路：

1. 收到 `POST /ask` 的 JSON 请求体
2. 把 JSON 交给 `Pydantic`
3. 按 `AskRequest` 的字段定义解析数据
4. 执行 `field_validator`
5. 如果校验成功，把结果作为 `request` 传进函数
6. 如果校验失败，直接返回 `422`

所以进入路由函数后，代码可以直接这样用：

```python
request.question
request.queries
request.recall_top_k
```

不需要再手动 `json.loads(...)`、判空、判类型、清洗字符串。

## `AskResponse` 是怎么返回出去的

在 [app/main.py](/E:/github/mykms/app/main.py:183) 里，路由函数把业务层返回的结果组装成 `AskResponse`：

```python
return AskResponse(
    abstained=result.abstained,
    confidence=result.confidence,
    prompt=result.prompt,
    sources=[...],
    abstain_reason=result.abstain_reason,
)
```

然后 FastAPI 再把这个 `AskResponse` 对象序列化成 JSON 发回客户端。

可以把整个过程理解成：

1. 请求 JSON -> `AskRequest`
2. `AskRequest` -> 业务逻辑
3. 业务结果 -> `AskResponse`
4. `AskResponse` -> 响应 JSON

## 一句话记忆

可以先用这组映射记住它们的职责：

- `Pydantic`：数据模型、校验、序列化
- `AskRequest`：`/ask` 的入参契约
- `AskResponse`：`/ask` 的出参契约
- `field_validator`：字段级清洗和校验
- `BaseSchema`：所有 schema 的公共父类和统一配置
