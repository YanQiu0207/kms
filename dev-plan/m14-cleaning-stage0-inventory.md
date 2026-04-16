# M14 Stage 0 Inventory

## 目的

这份清单用于固定 M14 Stage 0 的主语料污染模式与代表样本。

作用：

- 让后续 boilerplate / table / source-specific 清洗有明确打击对象
- 为 `eval/benchmark.cleaning.real10.jsonl` 提供样本来源
- 为样本文档 diff 提供初始候选集

## 当前高频模式

基于 `scripts/audit_cleaning_candidates.py --config config.yaml` 的当前主语料扫描结果：

- `documents = 590`
- `toc_docs = 66`
- `table_docs = 35`
- `author_docs = 5`
- `reference_docs = 22`
- `placeholder_docs = 59`

按 source 分布：

- `E:/work/blog`
  - `documents = 107`
  - `toc_docs = 13`
  - `table_docs = 13`
- `E:/notes`
  - `documents = 479`
  - `toc_docs = 53`
  - `table_docs = 22`
- `E:/work/privy-blog`
  - `documents = 4`
  - 样本量很小，当前不是优先矛盾

### 1. `[TOC]` 目录占位

特点：

- 文首高频出现
- 不携带正文知识
- 会污染 lexical 命中和短 query 排名

典型样本：

- `E:/notes/高并发系统设计/0 概观.md`
- `E:/notes/apue/chapter4 文件与目录.md`
- `E:/notes/git/git.md`
- `E:/notes/c++常见问题/模板与泛型编程.md`

### 2. Markdown 表格

特点：

- 知识密度高
- 当前切块后容易被拆成“表头 / 分隔行 / 行片段”
- 对 evidence hit 和 term coverage 都有影响

典型样本：

- `E:/notes/shell/shell学习笔记.md`
- `E:/notes/apue/chapter4 文件与目录.md`
- `E:/notes/第三方软件/gdb/1.0 基础知识.md`
- `E:/notes/程序设计/多线程异步日志库.md`
- `E:/notes/网络编程/muduo学习笔记/3.0 为什么需要应用层缓冲.md`
- `E:/notes/网络编程/网络编程常见问题/4.0 应用层缓冲区.md`
- `E:/notes/线程同步/原子编程/2.0 内存屏障.md`
- `E:/notes/第三方软件/brpc/bvar/类的接口.md`

### 3. 转载 / 作者 / 尾注类文本

特点：

- 常见于外部文章摘录
- 语义上不是目标知识主体
- 容易把“作者、编辑于、知乎”等词带进检索面

典型样本：

- `E:/notes/第三方软件/brpc/作者/戈君.md`
- `E:/notes/第三方软件/brpc/作者/朱佳顺.md`
- `E:/notes/snmp/1.0 snmp安装.md`
- `E:/notes/snmp/3.0 snmp使用v3协议.md`

### 4. 参考链接 / 参考文献区

特点：

- 常位于文尾
- 有价值，但多数不是主答案正文
- 容易在短 query 下被误当成正文命中

典型样本：

- `E:/notes/snmp/4.0 使用shell脚本扩展snmpd的功能.md`
- `E:/notes/snmp/3.0 snmp使用v3协议.md`
- `E:/notes/snmp/1.0 snmp安装.md`
- `E:/notes/openssl编程/tls/session cache.md`

### 5. 占位 / 未完成文本

特点：

- 例如 `待续`
- 信息量很低
- 会形成高重复低价值 chunk

典型样本：

- `E:/notes/c++常见问题/new操作符.md`
- `E:/notes/练手项目.md`

## Stage 0 样本文档池

当前先固定 20 篇样本，后续 diff 优先从这里取：

1. `E:/notes/高并发系统设计/0 概观.md`
2. `E:/notes/高并发系统设计/1.1 通用设计方法.md`
3. `E:/notes/apue/chapter4 文件与目录.md`
4. `E:/notes/apue/chapter3 文件IO.md`
5. `E:/notes/shell/shell学习笔记.md`
6. `E:/notes/第三方软件/gdb/1.0 基础知识.md`
7. `E:/notes/程序设计/多线程异步日志库.md`
8. `E:/notes/第三方软件/brpc/bvar/类的接口.md`
9. `E:/notes/网络编程/muduo学习笔记/3.0 为什么需要应用层缓冲.md`
10. `E:/notes/网络编程/网络编程常见问题/4.0 应用层缓冲区.md`
11. `E:/notes/线程同步/原子编程/2.0 内存屏障.md`
12. `E:/notes/第三方软件/brpc/作者/戈君.md`
13. `E:/notes/第三方软件/brpc/作者/朱佳顺.md`
14. `E:/notes/snmp/1.0 snmp安装.md`
15. `E:/notes/snmp/3.0 snmp使用v3协议.md`
16. `E:/notes/snmp/4.0 使用shell脚本扩展snmpd的功能.md`
17. `E:/notes/openssl编程/tls/session cache.md`
18. `E:/notes/c++常见问题/new操作符.md`
19. `E:/notes/练手项目.md`
20. `E:/notes/git/git.md`

## Stage 0 专项 Benchmark

已新增：

- `eval/benchmark.cleaning.real10.jsonl`

覆盖范围：

- `[TOC]` 噪音误召回
- 表格类知识检索
- 尾注类噪音误答

当前修正后 baseline：

- `eval/results/benchmark.cleaning.real10.m14.corrected-baseline.json`
- 当前摘要：
  - `recall_at_k = 0.875`
  - `mrr = 0.8125`
  - `abstain_accuracy = 0.9`
  - `false_abstain_rate = 0.0`
  - `false_answer_rate = 0.5`
- baseline 关键问题：
  - `cleaning10-006`
    - `Markdown TOC` 噪音题被误答
  - `cleaning10-003`
    - `GDB` 命令缩写问题只排到 `rank = 2`
  - `cleaning10-009`
    - 保守口径下未命中 `1.0 基础知识.md`

当前 M14 final：

- `eval/results/benchmark.cleaning.real10.m14.final.json`
- `eval/results/index-stats/m14.final.json`
- `eval/results/index-stats/m14.final.diff.json`
- 当前摘要：
  - `recall_at_k = 0.875`
  - `mrr = 0.8125`
  - `abstain_accuracy = 1.0`
  - `false_abstain_rate = 0.0`
  - `false_answer_rate = 0.0`
  - `chunk_count: 5366 -> 5356`
  - `exact_duplicate_chunk_ratio: 0.016 -> 0.0155`
- 已确认收益：
  - `cleaning10-006` 已从误答收口为正确拒答
  - `toc-noise` 子集误答已清零
- 已确认残留：
  - `cleaning10-003` 仍为 `rank = 2`
  - `cleaning10-009` 在保守 benchmark 下仍未命中目标文档

## 下一步

M14 已完成，Stage 0 样本池后续继续用于：

1. 追踪 GDB 表格类排序偏移
2. 扩展 source-specific 规则覆盖面
3. 为下一阶段的排序/近重复问题提供复现样本
