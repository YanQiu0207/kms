# M18 Evaluation And Data Engineering Stage Summary

## 目标

M18 的目标不是继续修单个 case，而是把前面阶段的收益变成可持续的工程抓手，重点解决：

- benchmark 只能单组跑，难以做整体验收
- 不同配置的 benchmark 不能在一次审查里稳定复跑
- source 质量没有独立审计视角

本阶段承诺的交付是：

- benchmark suite
- HTTP benchmark / suite 支持
- source audit
- 多配置本地验收入口

## 实施内容

### 1. 新增 benchmark suite

- 新增：
  - [eval/suite.py](/E:/github/mykms/eval/suite.py)
  - [eval/run_benchmark_suite.py](/E:/github/mykms/eval/run_benchmark_suite.py)
  - [eval/benchmark-suite.m18.json](/E:/github/mykms/eval/benchmark-suite.m18.json)
- 作用：
  - 把多组 benchmark 合成一套统一的阶段验收结果
  - 支持 gate / non-gate 区分
  - 输出 failures ledger

### 2. benchmark / suite 支持 HTTP base URL

- 更新：
  - [eval/benchmark.py](/E:/github/mykms/eval/benchmark.py)
  - [eval/run_benchmark.py](/E:/github/mykms/eval/run_benchmark.py)
  - [eval/suite.py](/E:/github/mykms/eval/suite.py)
  - [eval/run_benchmark_suite.py](/E:/github/mykms/eval/run_benchmark_suite.py)
- 当前已支持：
  - `run_benchmark --base-url`
  - `run_benchmark_suite --base-url`
  - suite entry 级别 `base_url`

### 3. 新增 source audit

- 新增：
  - [eval/source_audit.py](/E:/github/mykms/eval/source_audit.py)
  - [eval/run_source_audit.py](/E:/github/mykms/eval/run_source_audit.py)
- 当前可输出：
  - `document_count`
  - `chunk_count`
  - front matter / category / tags / aliases 覆盖率
  - `by_source_id`
  - `by_top_level_path`

### 4. 新增多配置本地 review 入口

- 新增：
  - [scripts/run_kms_server.py](/E:/github/mykms/scripts/run_kms_server.py)
  - [eval/benchmark-suite.m18.local.json](/E:/github/mykms/eval/benchmark-suite.m18.local.json)
- 当前 review 方式：
  - 主语料实例：
    - `config.yaml`
    - `http://127.0.0.1:49154`
  - `notes-frontmatter` 实验实例：
    - `config.notes-frontmatter.yaml`
    - `http://127.0.0.1:49155`

### 5. 形成阶段性整体验收产物

- 结果文件：
  - [benchmark-suite.m18.local.current.json](/E:/github/mykms/eval/results/benchmark-suite.m18.local.current.json)
  - [benchmark-suite.m18.local.failures.jsonl](/E:/github/mykms/eval/results/benchmark-suite.m18.local.failures.jsonl)
  - [source-audit.m18.current.json](/E:/github/mykms/eval/results/source-audit.m18.current.json)

## 结果

### 整体验收

权威结果文件：

- [benchmark-suite.m18.local.current.json](/E:/github/mykms/eval/results/benchmark-suite.m18.local.current.json)

最终结果：

- `total_entries = 8`
- `gated_entries = 7`
- `passed_entries = 8`
- `passed_gated_entries = 7`

说明：

- `query-routing.real10` 在本地双实例 suite 中被标记为 `gate = false`
- 其余 7 组 gate 全部通过

### 单组结果

- [benchmark.ai.real10.m18.current.json](/E:/github/mykms/eval/results/benchmark.ai.real10.m18.current.json)
- [benchmark.cleaning.real10.m18.current.json](/E:/github/mykms/eval/results/benchmark.cleaning.real10.m18.current.json)
- [benchmark.ranking.real10.m18.current.json](/E:/github/mykms/eval/results/benchmark.ranking.real10.m18.current.json)
- [benchmark.notes-frontmatter.real10.m18.current.json](/E:/github/mykms/eval/results/benchmark.notes-frontmatter.real10.m18.current.json)
- [benchmark.guardrail.real10.m18.current.json](/E:/github/mykms/eval/results/benchmark.guardrail.real10.m18.current.json)

### source audit

结果文件：

- [source-audit.m18.current.json](/E:/github/mykms/eval/results/source-audit.m18.current.json)

当前快照摘要：

- `document_count = 590`
- `chunk_count = 5356`
- 主配置当前 front matter 覆盖率为 `0`
- top-level path 分布已经可直接审查主语料结构

## 问题与处理

### 问题 1：单个 `--base-url` 无法正确审查混合配置 suite

- 现象：
  - 主语料和 `notes-frontmatter` 不能共用同一个 API 进程做整组 review
- 根因：
  - 不同 benchmark 需要不同 config / index / vector store
- 处理：
  - suite entry 增加 `base_url`
  - 新增 `benchmark-suite.m18.local.json`
  - 用两台本地实例分别承载主语料和 `notes-frontmatter`

### 问题 2：之前的 `benchmark-suite.m18.current.json` 不是最终可信整体验收

- 现象：
  - 早期单实例 suite 输出存在“不同 config 混跑”的局限
- 根因：
  - 当时 suite 只有统一入口，没有 entry 级 base URL
- 处理：
  - 当前把 [benchmark-suite.m18.local.current.json](/E:/github/mykms/eval/results/benchmark-suite.m18.local.current.json) 定为权威结果
  - 单实例输出保留，但不再作为最终审查结论

### 问题 3：source 质量只能从 benchmark 侧反推，不够直接

- 现象：
  - 很难回答“当前主语料 front matter 覆盖率是多少”“哪个 top-level path chunk 最多”
- 根因：
  - 缺少 source audit 视角
- 处理：
  - 新增 `source_audit`
  - 把 source 结构信息独立输出成 JSON 审计快照

## 验证

本阶段使用的本地 review 命令：

```powershell
.\.venv\Scripts\python.exe scripts\run_kms_server.py --config config.yaml --host 127.0.0.1 --port 49154
.\.venv\Scripts\python.exe scripts\run_kms_server.py --config config.notes-frontmatter.yaml --host 127.0.0.1 --port 49155
.\.venv\Scripts\python.exe -m eval.run_benchmark_suite --suite eval/benchmark-suite.m18.local.json --output eval/results/benchmark-suite.m18.local.current.json
.\.venv\Scripts\python.exe -m eval.run_source_audit --config config.yaml --output eval/results/source-audit.m18.current.json
```

代码与回归已通过：

- `.\.venv\Scripts\python.exe -m pytest tests\test_eval_benchmark.py tests\test_eval_suite.py tests\test_query_understanding.py tests\test_query_service.py tests\test_retrieval_m2.py -q`
- `.\.venv\Scripts\python.exe -m pytest -q`

当前全量回归结果：

- `114 passed`

## 结论

M18 已完成。

本阶段真正交付的是：

- 一套能做整组阶段验收的 benchmark suite
- 支持多实例 / 多配置审查的 HTTP benchmark 与 suite
- source audit 快照
- 本地双实例 review 工作流

M18 没做的是：

- 自动从线上失败 case 回流 benchmark
- source onboarding 的全自动准入流程
