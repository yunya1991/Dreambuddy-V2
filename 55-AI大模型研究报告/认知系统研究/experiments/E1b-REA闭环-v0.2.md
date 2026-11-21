# E1b：REA 仪器修复与闭环复跑 v0.2

> **前置**：`E1-REA闭环-v0.1.md`（首轮 4/20）
> **本轮目标**：修 I1（feature 不参与过滤）与 I4（依赖图跨包边缺失），用**干净快照**复跑同一 20 题任务集
> **日期**：2026-11-17
> **性质**：仪器修复 + 受控复跑；不检验 P1，不产生记忆形态相关结论
> **产物**：`E1b-runs.jsonl`（逐题）、`E1b-trace-raw.json`（trace 原始指标）

---

## 0. 结论摘要

| 指标 | E1（旧仪器/脏树） | E1b（新仪器/干净树） |
|---|---|---|
| 严格通过 | 4/20 = 20% | **7/20 = 35%** |
| 含弱通过（E1） | 5/20 = 25% | **8/20 = 40%** |
| 模块入口 | 4/4 | 4/4 |
| 依赖关系 | 0/4（+1 弱） | **3/4（+1 弱）** |
| 调用链 / 字段来源 / 配置生效点 | 0/4 · 0/4 · 0/4 | 0/4 · 0/4 · 0/4 |
| trace 输出总量（20 题） | 13.41 MB | **0.17 MB（−98.7%）** |
| 单次 trace 最大输出 | 690 KB | **28 KB（−95.9%）** |
| trace 中位时延 | ~1.8 s | 1.57 s |

同目标对照（旧版 vs 新版，同一 `/tmp/e1b_clean`）：

| 证据 | 旧版 | 新版 |
|---|---|---|
| `apps.cli` 依赖 | `['__future__','dreamos','sys']` | `['cli.analyze_commands','cli.app','cli.commands']` |
| `evolution.engine` 依赖 | `['__future__','dreamos','gap_analyzer','lesson_distiller','logging','node_optimizer','types','typing']` | 含 `core.graph_store.types`、`core.memory.*`、`shared.state` |
| `core.sense.intent_engine` 依赖 | `['__future__','dreamos','evaluators','recognizers','token_budget','types','typing']` | 含 `shared.llm_client`、`shared.utils`、`core.sense.recognizers.*` |
| 项目内依赖边（analyze 口径） | 100（工作树）/ 无跨包 | **542** |
| trace 是否按 feature 裁剪 | 否（20/20 返回全图） | **是（15/20 裁剪；5 题无种子）** |

**净效果**：I1/I4 修复成立，依赖类问题从"全不可判定"变为可判定，成本下降约两个数量级。调用链与字段来源仍为 0/4，因为 I2（构造调用不建边）与 I3（跨包属性调用不建边）本轮未修，属于下一轮范围。

---

## 1. 仪器改动（未提交，工作树）

| 文件 | md5 | 改动 |
|---|---|---|
| `33-REA逆向解析工程/core/dependency_graph.py` | `5afa8639658fce1e60c6c0c23a262664` | +121/−? 重写依赖解析：先建模块全集，再解析 import；支持根包名剥离、符号回溯、相对导入 |
| `33-REA逆向解析工程/dsh_nodes.py` | `0254638cb259781e37e9ce650b986d9b` | +117/−22 新增种子匹配与有界子图；无种子时不再回退全图（上限 400 个函数名） |

合计 `+216 / −22` 行，`python3 -m py_compile` 通过。**改动未提交**，因此"仪器版本"目前只能以 md5 标识；正式复现前应单独提交。

### 1.1 I4 修复方式（依赖图）

原实现只取 import 的顶层包名（`from dreamos.core.x import Y` → `dreamos`），而项目模块是相对根目录的 `core.x`，两者永不相等，导致跨包边全部丢失。新实现：

1. 先收集全部项目模块名，建立 `module_set`；
2. `dreamos.core.x` 剥掉根包名后按**最长后缀**匹配 `core.x`；
3. `from <pkg> import Symbol` 无法直接命中包时，用"类/函数定义索引"把 `Symbol` 回溯到定义模块；
4. 相对导入按当前模块所在包拼接后再解析；
5. 仍无法解析的才记为外部依赖（保留顶层名）。

### 1.2 I1 修复方式（trace 过滤）

原实现完全没有使用 `feature`（只把它原样回显）。新实现：

1. `entry` 精确命中 + `feature` 的 ASCII 词元（去掉下划线）对函数全名做包含匹配，取最短命中的至多 5 个种子；
2. 以种子为中心，沿 `callers`/`callees` 双向扩展 `hops`（默认 2，上限 3），节点上限 240；
3. 输出新增 `seeds`、`filtered`、`full_stats`；未命中时不返回全图，改为 `fallback=no_seed_match` + 前 400 个函数名（≈28 KB）；
4. 未命中会在 `known_gaps` 明确写出。

---

## 2. 实验设置

| 项 | 值 |
|---|---|
| 目标 | `/tmp/e1b_clean/1-ARCHITECTURE/dreamos`（`git archive HEAD` 导出，非工作树） |
| git HEAD | `551435b1b9c0c90694e78322ea3ccfd537f371fd` |
| 快照 | `snapshot_id=788fcf230b0e111a` |
| 规模 | 258 模块 / 3130 函数 / 542 项目内依赖边 / 5 循环依赖 / 81 外部依赖 |
| 任务集 | `E1-tasks.jsonl`（与 E1 相同 20 题，真值未改） |
| 判定 | 与 E1 相同的机械规则；E1 记为弱通过 |
| 对照 | 旧版仪器（`git archive HEAD` 的 `33-REA`）+ 同一干净目标，跑同一 20 题 |

**为什么要用 `git archive` 而不是工作树**：E1 的 snapshot 索引的是脏工作区（295 个 .py，含未提交新文件），无法用 commit 重建。E1b 改用 HEAD 导出，`snapshot_id` 可由 commit 复现。

**基线漂移披露**：E1 运行时 HEAD 为 `e24651f9b2`，E1b 时为 `551435b1b9`（期间仓库有提交）。因此 E1 与 E1b 的绝对值不可直接相减；本轮有效对比是第 0 节的"旧版 vs 新版，同目标"。

---

## 3. 逐题结果

完整记录见 `E1b-runs.jsonl`，摘要：

| 题号 | 类别 | 判定 | 关键证据 |
|---|---|---|---|
| A1 | 调用链 | fail | 子图 6 节点，无 `TradingAgent.__init__`（I2） |
| A2 | 调用链 | fail | 子图 12 节点，无 `GraphExecutor.__init__ → NodeRunner.__init__`（I2） |
| A3 | 调用链 | fail | 粒度停在符号，无函数体（不可判定） |
| A4 | 调用链 | fail | `attach_node_registry` 节点存在但无 caller（I3） |
| B1–B4 | 字段来源 | fail | 子图只到符号，无赋值/计算逻辑（不可判定） |
| C1–C4 | 配置生效点 | fail | 无种子命中，回退函数名清单（不覆盖） |
| D1 | 模块入口 | **pass** | `apps.api_server.create_app` line=75 |
| D2 | 模块入口 | **pass** | `cli.app.get_default_app` line=126 |
| D3 | 模块入口 | **pass** | `registry.node_registry.get_default_registry` line=266 |
| D4 | 模块入口 | **pass** | `core.capability.registry.get_default_capability_registry` line=272 |
| E1 | 依赖关系 | pass_weak | `graph_executor` 无 `graph_store` 边（与真值一致） |
| E2 | 依赖关系 | **pass** | `intent_engine` 有 `shared.*`、无 `capabilities.*` |
| E3 | 依赖关系 | **pass** | `evolution.engine → core.graph_store.types` |
| E4 | 依赖关系 | **pass** | `apps.cli → cli.app` |

分类通过率：调用链 0/4、字段来源 0/4、配置生效点 0/4、模块入口 4/4、依赖关系 3/4（+1 弱）。

---

## 4. 成本对比（20 题，trace 口径）

| 指标 | 旧版 | 新版 | 变化 |
|---|---|---|---|
| 输出总字节 | 13,414,600 | 172,119 | −98.7% |
| 单题最大 | 670,762 | 28,041 | −95.8% |
| 单题最小 | 670,762 | 222 | — |
| 中位时延 | ~1.8 s | 1.57 s | −13% |
| 有效裁剪题数 | 0/20 | 15/20 | — |

5 题未裁剪：B2（`final_confidence` 不是函数名）、C1–C4（环境变量不是符号）。这类问题的正确响应是"不在调用图模型内"，新版已通过 `fallback=no_seed_match` 与 `known_gaps` 显式表达，而不是静默回退全图。

---

## 5. MCP 与本地一致性

MCP 壳进程（`mcp_shells/l0_rea/server.py`）与本地回放使用同一份代码。抽 3 题比对：

| 题 | 本地 | MCP | 一致 |
|---|---|---|---|
| A2 | 12 节点 | 12 节点，同边集 | ✓ |
| D2 | 1 节点（`cli.app.get_default_app`） | 1 节点 | ✓ |
| C1 | 28,041 B（400 函数名兜底） | 29.5 KB 信封（同结构） | ✓ |

说明：修改 `dsh_nodes.py` 后必须重启 `l0_rea` 壳进程才会生效（壳为长驻进程）。本轮通过终止旧壳触发重拉验证，重启后 MCP 行为与本地一致。

---

## 6. 仍未解决的问题（下一轮）

| # | 缺陷 | 影响 | 建议 |
|---|---|---|---|
| I2 | 构造调用 `X(...)` 不建边（`_call_name` 只解析 `Name.id`/`Attribute.attr`，且只在同文件符号表内匹配） | A1/A2 假阴性 | 建全局符号表 + 类名映射到 `Class.__init__`，按"同文件 > 同包 > 唯一全局"消歧 |
| I3 | 跨包属性方法调用不建边 | A4 假阴性 | 同上，用 import 别名表解析 `module.Class.method` |
| I4b | `entry` 只做精确全名匹配 | 用短名传 entry 会静默失效 | 与种子匹配共用同一归一化逻辑（已部分实现，需补 entry 分支测试） |
| I5 | `snapshot.query` 对 modules/pack 仍无效 | 只能分页翻全量 | 后续单独修 |
| I6 | 产物无 `file:line` | 证据需二次映射 | pack 增加路径后缀，或 trace 节点附带定义行 |

**判定**：I1、I4 已修复并在 MCP 上验证；I2、I3 未修，因此 A/B/C 三类仍为 0/4。当前 D3.1（结构定位）可用，D3.2（语义读取）仍需源码读取或精确检索。

---

## 7. 对研究计划的影响

1. **E1b 未达到"仪器可独立支撑 D3"的门槛**（35%–40%，低于 80%）。但这不再是"仪器噪声"，而是**能力边界清晰**：结构定位准、语义恢复缺失。
2. **依赖类事实可以作为 P1 的稳定题源**：4 类中 3 类可判定，适合批量生成"可再推导事实"题。
3. **调用链题的题源需要等 I2/I3**；在此之前，任务集应偏向"定义位置 + 依赖方向"，避免把仪器缺陷计入 P1 的失败率。
4. 成本已可接受（单题 ≤28 KB），可以进入 20 题 × 多次重复的稳定性测试（E1c），而不必担心上下文爆炸。

---

## 8. 复现指引

```text
# 1) 干净目标
git -C <repo> archive HEAD 1-ARCHITECTURE/dreamos | tar -x -C /tmp/e1b_clean
# 2) 旧版对照（未修改的仪器）
git -C <repo> archive HEAD 33-REA逆向解析工程 | tar -x -C /tmp/rea_old
# 3) 新版：直接 import 工作树 33-REA逆向解析工程
# 4) 逐题：S33_rea_trace({target, feature, hops:2})
# 5) 依赖：DependencyGraph().build(target)
# 6) 评分：experiments/E1b-runs.jsonl 的 verdict 字段
```

**已披露瑕疵**
- 仪器改动未提交（md5 见 §1），严格意义上仍非"冻结版本"。
- 无第二评分者，κ 不可计算；本轮判定为机械规则 + 脚本，已排除人工改判。
- 单仓库、单语言、单快照；结论不外推。
