# 验收报告 — 52-LobeHub 协议集成 v0.12.0（R1+R2+R3）

## 基本信息

| 项 | 值 |
|---|---|
| 验收对象 | 验收红旗修正批：R1（G4 词法误伤）/ R2（`--force` mode/route）/ R3（trace `executed`） |
| 验收时间 | 2026-11-11 20:17（本地） |
| 验收人 | AI（dream-acceptance-verify 五维门禁） |
| 关联上一轮 | `acceptance_bundles/20261111_52_lobehub_round1`（发现 R1-R5） |
| 关联 commit | 待提交（本轮改动仅工作区） |
| 范围声明 | 仅 `orchestrator/scoring.py`、`orchestrator/brainstorm_orchestrator.py`、`orchestrator/tests/test_brainstorm.py` + 文档同步；R4/R5 按用户指令留 Phase 2 |

## 五维证据矩阵

| 维度 | 状态 | 证据 | 备注 |
|---|---|---|---|
| 症状复测 | ✅ | `repro_after.log`：15/15 历史 G4 误伤旗标 → `PASS` + `notes`；11/11 守卫旗标 → `BLOCK` | 用 trace 原文重放，非构造样本 |
| 日志证据 | ✅ | `RUN_ID` 级 trace 落盘：`gates[].notes` 两条、`trace.executed=false`、`mode_basis=force`；`decision=dispatch` | 修复前同卡 G4 BLOCK → T2 → escalate |
| 回归 | ✅ | orchestrator **95 passed** / bridge **20 passed** / debate 壳 **22 passed**，三者 `exit=0`；ruff `All checks passed`、black 18 files unchanged | 新增 11 条 G4 用例 |
| 影响面 | ✅ | `fix.diff` 492 行 / 9 文件，全部在 52 模块内；无 lockfile、无跨模块改动 | 文档 5 件同步 |
| 边界 | ✅ | 否定语境（`no_live_trading`/`live_disabled`）→ notes；词边界（`delivery_risk`/`reorder_steps`/`liveness_check`）→ 不命中；空/未知 → 维持 fail-closed | 单测参数化覆盖 |

## 修改摘要

### R1 — G4 从「子串匹配」改为「三档意图判定」

- 原：`risk_flags` 任一含 `实盘|live|下单|order`（子串）→ BLOCK。
- 现（`scoring._live_trading_flag_verdict`）：
  1. 否定/规避语境（`no_/non_/not_/without/avoid/disable/_off/不/非/无/禁止/避免/仅回测`）→ `notes` 放行；
  2. 执行动作（`实盘下单|接入实盘|直接下单|place order|go live|live trading|真实账户下单`…）→ BLOCK；
  3. 裸声明（`实盘|下单|live|order|live trading|live_trading|order execution|place order`）→ BLOCK；
  4. 无否定前缀的英文标识符（如 `live_trading`）→ BLOCK；
  5. 其余自然语言风险描述 → `notes` 放行。
- **安全下限不变**：G3（trade-exec 域工具拦截）与 ADR-001 三道门仍是真实执行护栏；11 条守卫旗标实测仍全部 BLOCK。
- 降级可审计：`gate()` 新增 `notes: ["G4:live_trading_mention:<flag>"]`，trace `gates[]` 落盘。

### R2 — `mode_basis` 解释 route/mode 差异

- trace / summary / `--json-out` 新增 `mode_basis ∈ {force, user_requested_debate, route}`；`route` 保留 router 原文（审计事实）。
- 实测：`route=workers` + `--force` → `mode=debate`、`mode_basis=force`。

### R3 — trace 顶层 `executed`

- trace 记录新增 `executed`；shadow 下显式 `false`，与 summary 同源同值（此前字段缺失，审计读到 null）。

## 量化：R1 误伤的实际影响（修复前实测）

| 指标 | 值 |
|---|---|
| 扫描 trace | 77 条 / 220 张卡 |
| G4 命中 | 15 张卡 / 14 个 run |
| 命中内容性质 | **15/15 为风险描述，0 条实盘请求** |
| 阻断卡分数 > 可行最高分 | 3 个 run |
| G4 单独改变收敛结果 | 1 个 run（0.918 vs 0.891 → 由 dispatch 变 escalate_debate） |
| G3 命中 | 15 次，全部为真实 `l0.trade-exec.*`（安全网有效） |

## 红旗闭环

| 编号 | 原级别 | 状态 |
|---|---|---|
| R1 G4 词法误伤 | P1 | ✅ 已修（三档判定 + notes 留痕 + 词边界） |
| R2 `--force` mode/route | P3 | ✅ 已修（mode_basis） |
| R3 trace `executed` 缺失 | P3 | ✅ 已修（顶层显式字段） |
| R4 44 拓扑未登记 | P2 | ⏸ 按指令留 Phase 2 |
| R5 守护不跨重启 | P2 | ⏸ 按指令留 Phase 2 |

## 风险与残余局限

1. **G4 从「见词即拦」变为「见动作才拦」**，属于安全门禁收紧方向的调整；补偿措施 = `notes` 全量留痕 + 结构分 `risk_flags` 维度照旧扣分 + G3/ADR-001 不动。建议下轮云端验收复核 notes 命中率。
2. 否定词表为启发式；新语料若出现新的否定表达，应追加 `NEGATION_MARKERS` 而不是放宽动作规则。
3. 守护调度（R5）仍依赖手动/常驻进程，与本次改动无关。

## 验收结论

**五维全通过 → 验收通过**。R1/R2/R3 已闭环，R4/R5 按用户决策延后至 Phase 2。

## 证据索引

- `repro_after.json` / `repro_after.log` / `repro_stderr.log` — 症状复测原始输出
- `test.log` — 三套件回归 + ruff/black，含 exit code
- `fix.diff` — 本轮改动全量 diff
- `run/t.jsonl`、`run/t_workers_force.jsonl`、`run/o.jsonl` — 端到端 trace/outbox
- `plancard_side_a.json` — 携带 2 条历史误伤旗标的 side-A 卡
