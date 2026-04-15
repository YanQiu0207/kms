# M11 RAG Evaluation Hardening

## Goal

把 `mykms` 当前偏“检索回归”的 `eval/` 升级为更正式的 RAG 评测框架，至少覆盖：

- 检索命中与排序质量
- 拒答精确率/召回率及误答、误拒
- `ask` 返回证据包对预期来源的覆盖情况
- 按题型/标签分组的统计结果
- 可直接扩展的 hard-case benchmark 模板

## Scope

- 代码：
  - `eval/benchmark.py`
  - `eval/run_benchmark.py`
  - `eval/__init__.py`
- 文档与数据：
  - `eval/README.md`
  - `eval/benchmark.sample.jsonl`
  - 新增 hard-case benchmark 模板文件
- 测试：
  - `tests/test_eval_benchmark.py`

## Non-Goals

- 本轮不改 `app/` 内检索、rerank、拒答主链路行为
- 不接入在线 LLM 做最终答案正确率自动评判
- 不重跑全量 live HTTP benchmark 生成新快照，除非本地回归需要

## Deliverables

- 向后兼容的 benchmark case schema：
  - 继续支持现有 `id/question/queries/expected_file_paths/should_abstain`
  - 新增题型、标签、预期来源数、关键词等字段
- 更完整的 summary 输出：
  - 总体指标
  - 拒答拆分指标
  - 证据覆盖指标
  - 按标签/题型的 breakdown
- hard-case benchmark 模板与说明
- 对应单元测试与 CLI 输出验证

## Acceptance

- 旧 benchmark 文件无需改写即可继续运行
- 新 benchmark 字段可被解析，并在结果摘要中产出额外指标
- `tests/test_eval_benchmark.py` 通过
- `eval/README.md` 能说明如何扩展“改写题、多文档题、干扰题、拒答题”

## Risks

- 历史结果 JSON 与当前源码结构不一致，升级时要优先保证输出兼容，避免已有结果解读脚本失效
- 没有宿主 LLM 自动判答时，answer-level 评测仍只能做到“证据包质量评测”，需要在文档中明确边界
