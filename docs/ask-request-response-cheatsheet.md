# `AskRequest` / `AskResponse` 速查

这是一份面向初学者的精简版说明，只保留最关键的概念。

更完整的版本见 [docs/ask-request-response-basics.md](/E:/github/mykms/docs/ask-request-response-basics.md:1)。

相关阅读：

- 完整版见 [docs/ask-request-response-basics.md](/E:/github/mykms/docs/ask-request-response-basics.md:1)

## 一句话理解

在这个项目里：

- `AskRequest` 定义 `/ask` 接口“收什么数据”
- `AskResponse` 定义 `/ask` 接口“回什么数据”
- `Pydantic` 负责校验和转换这些数据

相关代码：

- [app/schemas.py](/E:/github/mykms/app/schemas.py:106)
- [app/main.py](/E:/github/mykms/app/main.py:171)

## 1. `Pydantic` 是什么

可以把 `Pydantic` 理解成：

- 带类型校验的数据模型库
- 能把 JSON 转成 Python 对象
- 也能把 Python 对象转回 JSON

所以它不只是“定义类”，还负责接口边界的数据检查。

## 2. `queries: list[str] = Field(default_factory=list)` 是什么

意思是：

- `queries` 是字符串列表
- 默认值是空列表
- 这个空列表会在每次创建对象时重新生成

为什么不用 `queries: list[str] = []`：

- 因为 `list` 是可变对象
- `default_factory=list` 更安全，避免多个实例共用同一个默认列表

## 3. `recall_top_k: int | None = None` 是什么

意思是：

- 这个字段可以是整数
- 也可以是 `None`
- 默认不传时就是 `None`

这样能区分两种情况：

- `None`：调用方没指定
- `20`：调用方明确指定了值

这比直接写成 `int = 0` 更清楚。

## 4. `BaseSchema` 是什么

`BaseSchema` 是所有 schema 的公共父类，定义在 [app/schemas.py](/E:/github/mykms/app/schemas.py:11)。

它继承自 `Pydantic` 的 `BaseModel`，并统一加了一条配置：

```python
extra = "ignore"
```

意思是：如果请求里多传了没定义的字段，就直接忽略。

## 5. `field_validator` 是什么

它是字段校验器。

例如：

```python
@field_validator("question")
@classmethod
def _validate_question(cls, value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("question cannot be empty")
    return stripped
```

这段的作用是：

- 先去掉 `question` 首尾空格
- 如果去掉后为空，就报错

所以：

- `"  hello  "` 会变成 `"hello"`
- `"   "` 会校验失败

## 6. FastAPI 是怎么用它们的

看 [app/main.py](/E:/github/mykms/app/main.py:171)：

```python
@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest) -> AskResponse:
```

可以直接这样理解：

1. 请求 JSON 进来
2. FastAPI 用 `AskRequest` 解析和校验
3. 业务代码处理
4. 返回 `AskResponse`
5. FastAPI 把它转成 JSON 响应

## 最短记忆版

- `AskRequest`：入参模型
- `AskResponse`：出参模型
- `BaseSchema`：公共父类
- `field_validator`：字段清洗和校验
- `Field(default_factory=list)`：安全的列表默认值
- `int | None = None`：可选整数
