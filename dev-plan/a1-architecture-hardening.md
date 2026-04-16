# A1 检索与运行时架构治理

## 背景

`docs/architecture-review.md` 指出了当前检索与启动链路的 6 个可维护性问题：

1. `app/retrieve/hybrid.py` 过大，职责混杂
2. 元数据文本提取逻辑重复
3. 停用词集合重复且不一致
4. 排序后处理步骤硬编码、不可组合
5. 配置缺少语义校验
6. `app/main.py` 存在模块级 `app` 单例

本轮要求先修这些工程问题，再重新执行测试与 benchmark，确认行为与效果不回退。

## 目标

- 把 `hybrid.py` 缩回“检索编排器”角色
- 抽出共享元数据文本工具，统一字段口径
- 把排序后处理改成可配置 pipeline
- 为配置增加语义校验，尽早失败
- 去掉模块导入即初始化的 FastAPI 单例
- 不修改 benchmark 样本与判定口径

## 实施范围

- `app/metadata_utils.py`
- `app/retrieval_pipeline_config.py`
- `app/retrieve/ranking_pipeline.py`
- `app/retrieve/hybrid.py`
- `app/config.py`
- `app/store/fts_store.py`
- `app/answer/guardrail.py`
- `app/main.py`
- `README.md`
- `docs/fastapi-in-this-project.md`
- `docs/docker-plan.md`
- 相关回归测试

## 验收标准

- `pytest -q` 全量通过
- `eval.run_benchmark_suite --suite eval/benchmark-suite.m18.json` 通过
- gated entries 仍为 `7/7`
- 不改 benchmark 数据、样例和断言口径
