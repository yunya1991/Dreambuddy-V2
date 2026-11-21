# E1：REA 现场重建闭环实验 v0.1

> **对应命题**：P1 的仪器前置条件（开题报告 §5.3 D3；研究协议第三部分）
> **对应阶段**：阶段二「实验协议建设」→ 阶段三「小规模预实验」
> **运行日期**：2026-11-17
> **性质**：仪器链路可用性测试（smoke test），**不检验 P1 本身，不产生性能主张**
> **任务集**：`E1-tasks.jsonl`（20 题）　**逐题记录**：`E1-runs.jsonl`（20 条）

---

## 0. 结论摘要

1. REA 的 **pack 索引（符号 + 定义行号）在 263/263 模块上精确**：4 道"模块入口"题全部一次命中，行号与独立真值完全一致。
2. REA 的 **trace 调用图存在系统性漏检**：构造调用（`X(...)`）与跨包属性方法调用不建边，导致 3 道调用链题假阴性；且 **`feature` 参数不参与过滤**——两个不同问题得到字节级相同的 675 KB 调用图（哈希 `2006b23b9d4f`）。
3. REA 的 **dependencies 只有同包边**：263 模块仅 100 条边，200 条分页中仅 42 个模块有出边，跨包 import 基本缺失，`apps.cli -> []`、`evolution` 无条目。因此**"无依赖"与"有依赖"都不可判定**。
4. 综合：20 题中严格通过 **4 题（20%，Wilson 95% CI [8%, 42%]）**；含 1 道"一致但不可靠"为 5 题（25%）。全部通过项都集中在"定义位置"一类。
5. 成本：11 次工具调用、原始输出约 **1.68 MB**，单次 trace 676 KB 已超出常规上下文窗口，必须落盘再读。同等任务用 grep 定位约为每题 1 KB。
6. **对研究的直接影响**：若"零记忆 / 指针记忆"条件只挂 REA，D3 只能覆盖 20% 的代码事实题，且覆盖类型单一。REA 不能单独充当 P1 的 D3 实现，必须与源码读取/精确检索组成级联，或先修仪器。

---

## 1. 冻结信息与实验瑕疵

| 项 | 值 |
|---|---|
| 分析目标 | `1-ARCHITECTURE/dreamos` |
| REA snapshot_id | `3e78a9124091e25d` |
| REA MCP version / config_version | `0.1` / `0.5` |
| 索引规模 | 263 文件 / 263 模块 / 3134 函数 / 100 项目内依赖边 / 0 循环依赖 / 87 外部依赖 |
| git HEAD | `e24651f9b2` |
| 工作区状态 | **脏**（存在大量未提交与新增文件，如 `core/capability/plugin_*.py`、`core/compute/tripwire.py`） |

**瑕疵（必须披露）**：研究协议要求"冻结 REA 版本与 snapshot 哈希"，但本次 snapshot 索引的是**脏工作区**而非某个干净 commit，`snapshot_id` 无法通过 git 重建。因此本轮结果只用于判断仪器形态，**不可作为可复现基线**。后续正式实验前须先提交工作区，重新建索引并记录 commit + snapshot 双哈希。

---

## 2. 方法

### 2.1 任务集

20 题，5 类 × 4：

| 类别 | 题号 | 测什么 |
|---|---|---|
| 调用链 | A1–A4 | 谁调用谁、谁持有谁 |
| 字段来源 | B1–B4 | 某字段在何处被写入/计算 |
| 配置生效点 | C1–C4 | 环境变量在哪读取、语义如何 |
| 模块入口 | D1–D4 | 工厂函数/入口定义位置 |
| 依赖关系 | E1–E4 | 模块间静态 import 方向 |

每题在 `E1-tasks.jsonl` 中预置：`question`、`truth`、`truth_evidence`（file:line）、`how_to_verify`。

### 2.2 真值来源（反循环约束 1）

真值 **在调用 REA 之前**由 Grep/Read 独立确定，记录 file:line；REA 输出只作为"候选重建结果"参与比对，不参与裁定。

### 2.3 判定标准（机械可复核）

- **pass**：REA 产物中存在与真值等价的定位（符号名 + 行号一致，或边存在）。
- **pass_weak**：产物与真值一致，但因索引覆盖缺陷不能作为否证。
- **fail**：分三类——
  - `假阴性`：结构客观存在，REA 未建边/未收录；
  - `不可判定`：REA 粒度（符号级）低于题目要求（函数体/赋值点）；
  - `不覆盖`：该事实类型不在 REA 图模型内（如环境变量读取）。

### 2.4 仪器调用

| 调用 | 次数 | 用途 |
|---|---|---|
| `submit/poll_rea_analyze` | 1 | 建立 snapshot，取得规模与版本 |
| `get_rea_snapshot(section=modules)` | 1 | 模块清单（query 无效，验证用） |
| `get_rea_snapshot(section=pack)` | 5 | 全量符号 + 定义行号（分页 cursor 0/85/150/170/259） |
| `get_rea_snapshot(section=dependencies)` | 1 | 项目内依赖边（limit 200/263） |
| `submit/poll_rea_trace` | 2 | 调用图；第二次换 `feature` 做一致性对照 |
| `get_rea_snapshot(section=diagnostics)` | 1 | 失败（`missing_snapshot_id`），记录为无效调用 |

---

## 3. 结果

### 3.1 逐题结果

| 题号 | 类别 | 判定 | 失败类型 | 关键证据 |
|---|---|---|---|---|
| A1 | 调用链 | fail | 假阴性 | `callees[TradingAgent.__init__]` 无 `GraphExecutor.__init__`；`callers[GraphExecutor.__init__]` 为空 |
| A2 | 调用链 | fail | 假阴性 | `callees[GraphExecutor.__init__] = None` |
| A3 | 调用链 | fail | 不可判定 | pack 仅到符号行 187，无函数体 |
| A4 | 调用链 | fail | 假阴性 | 无 `attach_node_registry` 调用者条目 |
| B1 | 字段来源 | fail | 不可判定 | 符号 `State.update` line 165 命中，但无赋值语句 |
| B2 | 字段来源 | fail | 不可判定 | 有 `Aggregator.aggregate` 定义，无计算逻辑 |
| B3 | 字段来源 | fail | 不可判定 | 无赋值点索引 |
| B4 | 字段来源 | fail | 不可判定 | 无赋值点索引 |
| C1 | 配置生效点 | fail | 不覆盖 | 两次不同 feature 的 trace 哈希相同；环境变量不在图内 |
| C2 | 配置生效点 | fail | 不覆盖 | 同上 |
| C3 | 配置生效点 | fail | 不覆盖 | 同上；evolution 未进首批依赖分页 |
| C4 | 配置生效点 | fail | 不覆盖 | 同上 |
| D1 | 模块入口 | **pass** | — | `apps.api_server.create_app` line 75 = 真值 75 |
| D2 | 模块入口 | **pass** | — | `cli.app.get_default_app` line 126 = 真值 126 |
| D3 | 模块入口 | **pass** | — | `registry.node_registry.get_default_registry` line 266 = 真值 266 |
| D4 | 模块入口 | **pass** | — | `core.capability.registry.get_default_capability_registry` line 272 = 真值 272 |
| E1 | 依赖关系 | pass_weak | — | `core.compute.graph_executor -> [aggregator,node_runner,reflector,tripwire,types]`，无 `graph_store`；但跨包边整体缺失 |
| E2 | 依赖关系 | fail | 不可判定 | `intent_engine -> [token_budget,types]`，`shared` 边缺失，无法证明"不依赖 capabilities" |
| E3 | 依赖关系 | fail | 假阴性 | 首批 200/263 条无 evolution；跨包边缺失 |
| E4 | 依赖关系 | fail | 假阴性 | `apps.cli -> []`，真实 import 未建边 |

### 3.2 汇总指标

| 指标 | 值 |
|---|---|
| 严格重建成功率 | 4/20 = **20%**（Wilson 95% CI 8%–42%） |
| 含弱通过 | 5/20 = **25%**（CI 11%–47%） |
| 证据可定位率（符号级） | 20/20 = 100%（pack 覆盖全部 263 模块） |
| 证据可定位率（行级，定义位置） | 4/4 = 100%（D 类） |
| 证据可直接给出 file:line | **0/20**（pack 只给点分模块名 + 行号，需外部映射为路径） |

**分类别通过率**

| 类别 | 通过 | 说明 |
|---|---|---|
| 调用链 | 0/4 | 构造与属性调用不建边 |
| 字段来源 | 0/4 | 粒度停在符号，不到赋值 |
| 配置生效点 | 0/4 | 环境变量不在图模型 |
| 模块入口 | **4/4** | pack 精确 |
| 依赖关系 | 0/4（+1 弱） | 跨包边缺失 |

**失败类型分布**（失败 15 题 + 弱通过 1 题）

| 类型 | 题数 | 题号 |
|---|---|---|
| 假阴性 | 5 | A1 A2 A4 E3 E4 |
| 不可判定（粒度不足） | 5 | A3 B1 B2 B3 B4 |
| 不覆盖 | 4 | C1 C2 C3 C4 |
| 一致但不可靠 | 1 | E1 |

### 3.3 成本

| 指标 | 值 |
|---|---|
| 工具调用 | 11 次（9 次有效） |
| 原始输出总量 | ≈ 1.68 MB（trace 2×676 KB、pack 5×~68 KB、deps 16 KB） |
| 单次 trace 输出 | 691,985 B / 691,995 B |
| 单次时延 | 0.1–15.5 s（7 个样本，中位数约 7 s）；trace 两次分别 1.8 s / 15.5 s |
| 等效 grep 成本 | 每题约 1 KB、1 次调用 |

---

## 4. 仪器缺陷清单（可直接转工单）

| # | 缺陷 | 证据 | 影响 |
|---|---|---|---|
| I1 | `trace.feature` 不参与过滤 | 两个不同 feature 的 `call_chain` SHA 相同 | 无法按问题取子图，每题都要吞全图 |
| I2 | 构造调用不建边 | `GraphExecutor.__init__` 无 caller/callee | 调用链题假阴性 |
| I3 | 跨包属性方法调用不建边 | `attach_node_registry` 无 caller | 调用链题假阴性 |
| I4 | dependencies 仅同包边 | 100 边/263 模块；`apps.cli -> []` | 依赖题不可判定 |
| I5 | `snapshot.query` 对 modules/pack 无效 | `query=TradingAgent` 仍返回前 N 个模块 | 检索退化为全量分页（5 次调用） |
| I6 | 输出无 file:line | pack 为 `模块名 + 行号`；trace 无行号 | 证据需二次映射；无法直接引用 |
| I7 | 单次 trace 输出 676 KB | 超出上下文，强制落盘 | 仪器不可在单轮内自洽使用 |
| I8 | `diagnostics` 段要求 snapshot_id 但报错信息为 `missing_snapshot_id` | 首次调用失败 | 接口易用性问题，非阻断 |

---

## 5. 对 P1 / D3 的含义

1. **D3 不能只挂 REA**。在"零记忆"条件下，REA 实际能恢复的只有"某符号在哪个模块第几行"这类定义型事实（20%）。涉及"为什么/谁写入/何时生效"的问题全部落空。
2. **指针记忆的价值被间接支持，但机制不是 REA**。D 类 4/4 说明：只要有稳定的"模块 → 符号 → 行"索引，指针就能定位；而 REA 的 pack 正好提供该索引。指针的落点应是 **pack 级索引**，不是 trace 级全图。
3. **级联必须显式化**。合理的 D3 至少两级：
   - D3.1 结构定位：REA pack / 精确 grep 定位符号与文件；
   - D3.2 语义读取：读函数体、读配置读取点（grep `os.environ`/`getenv`）、读赋值点。
   仅 D3.1 时通过率上限约 20%–25%，与本次观测一致。
4. **P1 的可检验性未受损，但需要改写实验条件**：T-B/T-D 的"现场重建工具集"必须包含 D3.1+D3.2，否则测到的是仪器缺陷而非记忆形态差异。

---

## 6. 独立复核（协议 3.2 第 2 条）

- 抽样比例：20% → 4 题（A1、C1、D2、E3）。
- 方式：在 REA 评分完成后，用独立脚本/Grep 重新确定真值（不读取 REA 输出）。
- 结果：4/4 与预置真值一致（A1 `agent.py:95`；C1 4 处 `os.environ`；D2 `cli/app.py:126`；E3 `evolution/engine.py:50` 等）。
- **一致性系数**：κ 不可计算（单一评分者 + 机械判定，无第二评分者）。这是本轮的方法学缺口，正式实验前须补第二人盲评。

---

## 7. 结论边界

- 单仓库（`1-ARCHITECTURE/dreamos`，263 模块）、单语言（Python）、单快照（`3e78a9124091e25d`）、脏工作区。
- 题目由本研究者设计，可能存在"偏向 grep 易得事实"的选择偏差；D 类全过、A/B/C 全败的分布本身提示任务集偏向"定义位置"。
- 本轮只测"REA 能否提供可定位证据"，**不测**重建后的答案是否正确（那需要下游 agent 生成答案再评分），因此不能据此断言"重建成功率 20%"是 D3 的端到端上限。
- 不得将本结果与外部记忆系统并列比较（协议 3.2 第 5 条）。

---

## 8. 下一步（按优先级）

1. **修仪器（最小改动）**：先修 I1（feature 过滤）与 I4（跨包边），否则后续所有依赖/调用链题都不可用。
2. **定义 D3 级联基线**：D3.1 = pack 索引；D3.2 = grep 精确读取。用同一 20 题复测，预期通过率显著上升，且能分离"仪器贡献"与"读源码贡献"。
3. **补第二评分者**：对 20 题做双人盲评，报 κ；若 κ < 0.6 先修评分手册。
4. **重建纯净快照**：提交工作区 → 记录 commit + snapshot 双哈希 → 重跑 E1，形成可复现基线（E1b）。
5. 只有在 E1b 通过（例如 ≥80% 可定位）后，才把 D3 接入 T-B/T-D 条件，进入 P1 的正式对照。

---

## 9. 复现指引

```text
目标：/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos
1) submit_rea_analyze(target, scope=summary)                  → snapshot_id
2) get_rea_snapshot(section=pack, limit=200, budget_bytes=65536, cursor=0/85/150/170/259)
3) get_rea_snapshot(section=dependencies, limit=200)
4) submit_rea_trace(target, feature=<任意>, hops=2)           → call_chain
5) 用 E1-tasks.jsonl 的 truth_evidence 与产物逐题比对
```

产物：
- 任务集：`experiments/E1-tasks.jsonl`
- 逐题记录：`experiments/E1-runs.jsonl`
- 原始输出：`~/.trae-cn/work/.trae/mcp-output/`（trace 两份、pack 五份、deps 一份）
