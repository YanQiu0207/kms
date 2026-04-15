# 个人 Markdown 知识库（kms）实施计划

## 背景

你希望把本地 Markdown 笔记变成一个可被 Claude Code 随时检索的个人知识库：通过 `/kms <question>` 触发时，先让大模型扩展问题、再用本地向量库检索，然后让大模型**严格基于检索资料**作答，不允许自由发挥。

已确认的关键决策（均取推荐项）：

| 维度 | 选择 |
|---|---|
| 向量模型 | **bge-m3**（本地，1024 维，8k 上下文，中英俱佳，MIT） |
| 向量库 | **Chroma**（嵌入式，Windows 原生支持） |
| 重排模型 | **bge-reranker-v2-m3**（top-20 → top-5） |
| 后端架构 | **常驻 FastAPI 服务**（技能侧通过 curl 调用） |
| 索引更新 | **手动命令增量**（基于 mtime + 内容 hash） |
| 源范围 | **多目录 + glob 排除规则** |

**参与人数：1 人**（你 + Claude Code 协作，无团队并行开发）。如与预期不符请在审核时指出。

---

## 总体架构

```
┌──────────────────────────────────────────────────────────────┐
│  Claude Code                                                  │
│   └─ /kms <q>  ──►  kms 技能（SKILL.md）                      │
│                      ├─ 1. 健康检查  curl :8765/health         │
│                      ├─ 2. Claude 扩展出 3 个同义问题           │
│                      ├─ 3. curl :8765/search × 4 (原始+扩展)   │
│                      ├─ 4. 合并去重 chunks                     │
│                      └─ 5. Claude 基于 chunks 作答 + 引用源     │
└──────────────────────────────────────────────────────────────┘
                              │ HTTP
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  FastAPI 服务（127.0.0.1:8765，本机唯一访问）                   │
│   ├─ POST /search       向量召回 top-20 → rerank → top-5       │
│   ├─ POST /index        增量/全量构建索引                      │
│   ├─ GET  /stats        索引元信息                             │
│   └─ GET  /health       就绪探针                               │
│                                                                │
│  模型：bge-m3（embed） + bge-reranker-v2-m3（rerank）           │
│  存储：Chroma（向量） + SQLite（文件 hash/mtime 元数据）        │
└──────────────────────────────────────────────────────────────┘
```

---

## 目录结构

**技能端**（Claude Code 侧，遵循 `~/.claude/skills/` 约定）：

```
~/.claude/skills/kms/
  SKILL.md                       # 主技能：流程编排 + curl 调用
  agents/
    kms-retriever.md             # 子 agent：负责问题扩展 + 检索调用
  reference/
    api.md                       # FastAPI 接口文档（供 SKILL.md 引用）
```

**后端服务**（独立项目，位于 `E:\github\cckms\`，已是空的 git 仓库）：

```
E:\github\cckms\
  pyproject.toml                 # uv 管理依赖
  config.yaml                    # 源目录、排除 glob、端口、模型路径
  .python-version
  app/
    __init__.py
    main.py                      # FastAPI 入口、路由注册
    config.py                    # 读取 config.yaml
    models.py                    # 懒加载 bge-m3 / bge-reranker
    chunker.py                   # MarkdownHeader + Recursive 二级分块
    indexer.py                   # 扫描文件、增量对比、写入 Chroma
    search.py                    # 检索 + rerank 管线
    state.py                     # SQLite：files(path, mtime, sha1, indexed_at)
  data/                          # gitignore
    chroma/                      # Chroma 持久化
    meta.db                      # SQLite 元数据
  scripts/
    serve.ps1 / serve.sh         # 启动 FastAPI（uvicorn）
    reindex.py                   # CLI：手动触发索引（也可走 HTTP）
```

---

## 关键实现要点

### 1. 分块策略（`app/chunker.py`）
参考 LangChain 官方推荐：
- 一级：`MarkdownHeaderTextSplitter` 按 `#/##/###` 切，保留标题层级作为元数据
- 二级：超长块再用 `RecursiveCharacterTextSplitter`（chunk_size=800，overlap=100）细切
- 每个 chunk 的元数据：`{path, heading_path, chunk_index, sha1}`

### 2. 增量索引（`app/indexer.py` + `app/state.py`）
- 遍历配置目录，按 glob 过滤排除
- 对每个文件算 SHA1，查 `meta.db`：
  - **新增**：分块 → embed → 写 Chroma + 写 meta
  - **修改**（hash 变）：按 `path` 删除旧 chunks → 重新索引
  - **删除**（文件已不存在但 meta 里有）：清理对应 chunks
- 返回 `{added, updated, removed, skipped}` 供技能侧汇报

### 3. 检索管线（`app/search.py`）
- 输入 `queries: List[str]`（通常是原问题 + 3 个改写），每条 embed → Chroma top-20
- 合并去重（按 chunk id）→ 送入 bge-reranker-v2-m3 打分 → 取 top-5
- 返回 `[{path, heading_path, content, score}]`

### 4. 技能流程（`SKILL.md`）
SKILL.md 指示 Claude：
1. 用 Bash `curl -sf http://127.0.0.1:8765/health` 探活，失败则提示用户手动启动服务并退出
2. 基于 `{{input}}` 生成 3 个同义改写（prompt 中明确"保持检索意图、换说法/换术语"）
3. 一次 POST `/search`（body: `{queries: [原问题, 改写1, 改写2, 改写3], top_k: 20, rerank_top_k: 5}`）
4. 在回答 prompt 中严格约束：**"仅基于下列资料回答；若资料不足以回答，必须明确说'资料中未找到相关内容'，不得调用训练数据或推测"**
5. 答案末尾列出 `来源：` + 每条 chunk 的 `path#heading_path`

### 5. 技术选型依据
- Chroma 嵌入式：[chromadb 官方文档](https://docs.trychroma.com/)
- bge-m3：[HuggingFace model card](https://huggingface.co/BAAI/bge-m3)（1024 维/8192 token/MIT）
- bge-reranker-v2-m3：[HuggingFace model card](https://huggingface.co/BAAI/bge-reranker-v2-m3)
- MarkdownHeaderTextSplitter：[LangChain 文档](https://docs.langchain.com/oss/python/integrations/splitters/markdown_header_metadata_splitter)
- FastAPI 常驻服务：业界通用做法，无 Anthropic 官方“技能调 API”规范（已核查）

---

## 开发计划（4 个里程碑）

### M1：后端骨架 + 分块 + 索引（先不接真实模型）
- 初始化 uv 项目、FastAPI、配置读取、SQLite 元数据
- 实现 MD 扫描 + 分块 + 增量对比逻辑
- 向量模型先用假向量（随机 1024 维）跑通流程
- 验证：对 5-10 个 MD 能正确建索引，修改后增量只处理变化文件

### M2：接入 bge-m3 + bge-reranker-v2-m3
- 懒加载模型（启动时异步预热或首次请求加载）
- 实测中文 + 英文混合查询的相关性
- 验证：top-5 结果在人工判断下有 ≥3 条相关

### M3：技能端
- 编写 `~/.claude/skills/kms/SKILL.md`（主流程）与 `agents/kms-retriever.md`
- 设计问题扩展 prompt，约束扩展数量与风格
- 设计作答 prompt，强制"仅基于资料"
- 验证：`/kms xxx` 能完整跑通，答案只引用检索内容

### M4：打磨
- `scripts/serve.ps1` 启动脚本；README 写明手动启停
- `/kms index`、`/kms stats` 等管理子命令（可选，走 curl）
- 错误处理：服务未启、Chroma 损坏、模型下载失败的友好提示
- 一个简单的 `config.yaml` 示例，带注释

---

## 需要你提供的输入（开始 M1 前）

1. **MD 源目录清单**（绝对路径）与 **排除 glob**（例：`**/node_modules/**`、`drafts/**`）
2. ~~后端代码位置~~（已定：`E:\github\cckms\`）
3. **FastAPI 端口**（默认 8765，避开常用端口）
4. **是否有 GPU 可用**（有则加载 fp16，快很多；无则 CPU 模式，首次查询 5-15 秒预热）

这些可以在审核阶段直接回复，或我在 M1 启动前再次问你。

---

## 验证方案

**端到端冒烟测试**（M3 完成后执行）：
1. 准备 5 个样本 MD（2 中文、2 英文、1 中英混）放入测试目录
2. `curl -X POST :8765/index -d '{"full":true}'` → 应返回 `added` ≥ 5
3. `curl :8765/stats` → 确认 chunk 数合理
4. 在 Claude Code 执行 `/kms <某个笔记里实际提到的问题>`
   - 答案应包含资料原文的关键信息
   - 末尾应列出正确的来源文件
5. 问一个**笔记里完全没有**的问题 → 答案必须是"资料中未找到相关内容"，不得给常识性回答
6. 修改一个 MD 文件一行 → `curl :8765/index` → 应只报告 1 个 `updated`

**回归与质量检查**（M2 完成后）：
- 准备 10 对 `(问题, 期望文件)` 作为检索基准样例
- 计算 recall@5：top-5 里命中期望文件的比例应 ≥ 80%

---

## 关键文件清单（实施时会创建/修改）

| 路径 | 作用 |
|---|---|
| `E:\github\cckms\pyproject.toml` | 依赖定义（fastapi, uvicorn, chromadb, FlagEmbedding, langchain-text-splitters, pyyaml） |
| `E:\github\cckms\config.yaml` | 源目录、排除、端口、模型路径配置 |
| `E:\github\cckms\app\main.py` | FastAPI 路由入口 |
| `E:\github\cckms\app\chunker.py` | Markdown 二级分块 |
| `E:\github\cckms\app\indexer.py` | 增量索引逻辑 |
| `E:\github\cckms\app\search.py` | 检索 + rerank |
| `E:\github\cckms\app\models.py` | 模型加载封装 |
| `E:\github\cckms\app\state.py` | SQLite 元数据层 |
| `~/.claude/skills/kms/SKILL.md` | 主技能流程 |
| `~/.claude/skills/kms/agents/kms-retriever.md` | 检索子 agent |
| `~/.claude/skills/kms/reference/api.md` | API 文档（供 `SKILL.md` 引用） |
