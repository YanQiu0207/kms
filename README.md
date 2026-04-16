# KMS — 个人知识库服务

一个生产级别的本地 RAG 服务，专为个人知识库场景设计。从 Markdown 文档扫描到答案生成，全链路自研实现，并提供开箱即用的 Claude Code 与 Codex 适配。

## 能力亮点

**混合检索 + 神经重排**

- SQLite FTS5 词法检索 × Chroma 语义检索，RRF 融合排名
- BGE 神经 reranker 对候选段落精排
- 支持增量索引，实时感知文档变更

**证据驱动的答案生成**

- 基于检索证据装配上下文，验证证据质量后再交给 LLM 生成答案
- 内置拒答判定：无相关证据时主动拒绝，而不是幻觉
- `/verify` 接口支持引用校验，每个来源可追溯到原始行号

**完整评测体系**

- 覆盖 Recall@K、MRR、拒答准确率 / 精确率 / 召回率、误拒率、误答率
- 支持按 `case_type` / `tags` 分组统计，量化每轮迭代效果

**扎实的工程基座**

- 完整防腐层（`app/vendors/`），Chroma / FlagEmbedding / jieba 均可无痛替换
- JSON Line 结构化日志，关键链路全覆盖，毫秒级耗时可追踪
- Claude Code 与 Codex 原生适配模板

## 架构

```
Markdown 文档
     ↓
扫描 → 两级分块 → 增量索引
                      ↓
    FTS5 词法检索 ──┬── Chroma 语义检索
                   ↓
              RRF 融合
                   ↓
            BGE 神经 reranker
                   ↓
         证据装配 → 拒答判定 → 答案生成
```

## 快速启动

```bash
pip install -e .
kms-api                  # 默认监听 127.0.0.1:49153
```

后台启动（保留 pid 与日志）：

```bash
python scripts/start_kms.py
python scripts/stop_kms.py
```

## API

| 接口 | 说明 |
|------|------|
| `GET /health` | 健康探活 |
| `GET /stats` | 索引统计 |
| `POST /index` | 触发增量 / 全量索引 |
| `POST /search` | 混合检索，返回带来源位置的候选段落 |
| `POST /ask` | 检索 + 答案生成（含拒答判定） |
| `POST /verify` | 引用来源校验 |

完整接口说明：[app/adapters/reference/api.md](app/adapters/reference/api.md)

## 文档导读

- 检索链路与文档预处理：[docs/ask-and-ingest.md](docs/ask-and-ingest.md)
- RAG 评测方案：[docs/rag-evaluation-methodology.md](docs/rag-evaluation-methodology.md)
- 质量优化路线图：[docs/rag-quality-improvement-roadmap.md](docs/rag-quality-improvement-roadmap.md)

## 配置

配置读取顺序：`KMS_CONFIG_PATH` → 根目录 `config.yaml` → 内置默认值

默认端口：`127.0.0.1:49153`，可通过 `KMS_HOST` / `KMS_PORT` 环境变量覆盖。

## 测试

```bash
.\.venv\Scripts\python.exe -m pytest
```

## 适配模板

- Claude Code：[app/adapters/claude/SKILL.md](app/adapters/claude/SKILL.md)
- Codex：[app/adapters/codex/kms.md](app/adapters/codex/kms.md)
