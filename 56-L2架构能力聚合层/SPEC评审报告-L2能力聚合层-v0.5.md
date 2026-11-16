# SPEC 评审报告 — 56-L2 架构能力聚合层 v0.5

- **评审对象**: [SPEC-56-L2架构能力聚合层.md](./SPEC-56-L2架构能力聚合层.md) v0.5 + [docs/TECHNICAL_DESIGN.md](./docs/TECHNICAL_DESIGN.md) v0.5
- **评审日期**: 2026-11-16
- **评审范围**: 重点检查 **§2.5 开发端闭环状态机** 与 **IF-5 / IF-6 接口契约** 的可机器判定性；附带门禁 G-L2-7/8/9 与跨文档一致性
- **评审方法**: 按「能否写出一个退出码 0/1 的校验器」逐条反推；核验被引用对象是否真实存在
- **结论**: 🔴 **不通过（针对方便机器判定这一目标）** —— 定位与路线正确，但状态机与两个新契约目前**只有散文形状，没有可执行判定**；`contracts/` 与 `tests/` 仍为空。需补 6 件产物后再审。

---

## 一、评分

| 维度 | 评分 | 说明 |
|---|---|---|
| 状态机可判定性 | **2.0 / 5** | 无迁移表；「只进不退」与回归失败后的重开冲突；无 `abandoned`；无 `attempts` |
| IF-5 台账可校验性 | **1.5 / 5** | 仅示例 JSON；`change_ref` 三型混用；无 schema/版本/签名；`settled` 枚举与 ADR-06 冲突 |
| IF-6 插件契约可校验性 | **1.0 / 5** | 伪代码；`manifest` 未定义；无错误码、超时、`rollback_token` 语义 |
| 门禁可实现性 | **1.5 / 5** | G-L2-7 引用不存在的 ID 命名空间；G-L2-8/9 的「通过」无签名与判定口径 |
| 跨文档一致性 | **3.0 / 5** | ADR-06 四分流 vs IF-5 三值；其余口径一致 |
| 定位与路线 | **4.5 / 5** | L0/L1/L2 分工、P3 先台账再 P4 自扩展的次序正确 |
| **综合** | **2.4 / 5** | **不通过** |

---

## 二、成立的部分（不返工）

1. **分层判定顺序**（§0.2.1）可直接写成函数：`needs_llm → fact_or_evidence → changes_system`，三个二值判断即可路由。
2. **P3 先于 P4** 的依赖判断正确：没有台账就无法衡量自扩展的收益与风险。
3. **Creator Mode 对照**抓住了真实差距（inspect / rollback），没有把「生成插件」误当核心。
4. **ADR-10「无回滚不开放 install」** 是可由代码强制的约束，方向正确。

---

## 三、P0 阻断项

### B1｜状态机不可判定：无迁移表，「只进不退」自相矛盾

**位置**：SPEC §2.5；IF-5 `state` 字段。

**问题**：
1. 只有一张箭头示意图，没有 `(from, to, guard)` 迁移表——校验器无法判断一次变更是否合法。
2. 文中写「`state` 只进不退」，但真实修复循环必然出现 **`fixed → 回归失败 → 回到修复`**。按现文本，这种情况没有任何合法迁移，只能作弊改历史记录。
3. 缺 `abandoned`（放弃/升级）终态：任务可以永久停在 `reproduced`，而校验器无从判定它是「进行中」还是「已烂尾」。
4. 缺 `attempts`：同一任务第 3 次回到 `root_caused` 与第 1 次在数据上不可区分。

**判定要求**：给出迁移表 + 重开策略 + 上限（建议 `attempts ≤ 3`，超限转 `abandoned` 并升级人工）。

---

### B2｜IF-5 `settled` 枚举缺 `process`，与 ADR-06 直接冲突

**位置**：SPEC §4.5 示例 `"settled": ["case", "cognition", "doc"]` vs ADR-06「四分流（案例/认知/流程/文档）」。

**问题**：3 个值 vs 4 个值。校验器无论按哪边写都会与另一边冲突；这也是「文档写了但不可执行」的典型。

**判定要求**：统一为 `case | cognition | process | doc` 四值枚举，并规定是否允许缺省（建议四项必填，允许值为 `done`/`skipped` 而非数组删项，便于机器判断覆盖度）。

---

### B3｜IF-5 关键字段是多型/自由文本，无法校验

**位置**：SPEC §4.5；TD §4.4。

| 字段 | 现状 | 问题 |
|---|---|---|
| `change_ref` | `"commit / PR / diff 摘要"` | 一个字段三种类型，无法解析；摘要无结构 |
| `evidence.regression` | `{"cmd":"...", "passed":true}` | 没有执行者签名，L2 可以自己写 `passed=true`，G-L2-8 形同虚设 |
| `metrics.before/after` | `{}` 自由对象 | 无指标名、单位、样本量，无法比较 |
| `trigger.ref` | 自由字符串 | 见 B4 |

**判定要求**：
- `change_ref` 拆为 `{type: commit|pr|diff, sha|url, summary}`；
- `evidence.*` 统一为签名对象 `{runner, cmd, exit_code, passed, ts, log_uri, artifact_hash}`，其中 `runner ∈ {pytest, ci, gate45, manual}`，`manual` 不得用于 `regression_passed`；
- `metrics` 改为 `[{name, unit, before, after, n, ci_low, ci_high}]`。

---

### B4｜G-L2-7 引用了不存在的 ID 命名空间

**位置**：SPEC §4.5 `"ref": "F-2026-xx | issue#123"`；G-L2-7「`ref` 可解析」。

**核验结果**：全仓不存在 `F-*` 形式的 L1 finding ID。真实可用的锚点只有两处：
- 48 涌现：`experiment_id`（实测格式 `D2B-<run_id>` / `XA-<run_id>` / `D3B-<run_id>`）；
- 54 发现：`reports/discovery/<YYYYMMDD-HHMM>/`（D-K02 只读出口）。

**后果**：门禁现在无法实现——解析器找不到对象，只能恒拒或恒放。

**判定要求**：把 `trigger` 改为带解析器的三型：
```json
{"source":"l1_finding|bug_report","resolver":"48.experiment_id|54.discovery_path|github.issue","ref":"D2B-20261116-1","resolved_at":"..."}
```
并规定解析失败即 `reported` 不成立（拒绝开工）。

---

### B5｜IF-6 是伪代码，无法生成校验器

**位置**：SPEC §4.6。

**缺失**：`manifest` 结构、请求/响应字段类型、错误码枚举、超时、`rollback_token` 的有效期与幂等语义、`side_effects_reverted` 的枚举（现在是无类型数组）。`experiment` 的「不落盘」也没有可验证判据。

**判定要求**：补两份 JSON Schema（request/response），错误码至少 `E_MANIFEST_INVALID / E_DEP_MISSING / E_CHANNEL_CONFLICT / E_ROLLBACK_FAILED / E_TIMEOUT`；`side_effects_reverted` 枚举为 `subscription|connection|handle|timer` 四项；`experiment` 返回 `disk_writes: 0` 作为可断言字段。

---

### B6｜「可机器判定」缺少载体：`contracts/` 与 `tests/` 为空

**核验**：`56-L2架构能力聚合层/contracts` 与 `tests` 目录均为空，无任何 schema 或校验脚本。

**后果**：所有「契约」都只存在于散文里，`G-L2-X` 无法被 CI 执行，也无法阻止文档与实现漂移（违反本文 §0.6 规则 2）。

**判定要求**：交付 `contracts/*.schema.json` + `contracts/state_machine.yaml` + `scripts/validate_contracts.py`（参照 47 的 `validate_mcp_registry.py`：`0` 通过 / `1` 失败 / 负例必红）。

---

## 四、P1 问题

| # | 问题 | 影响 | 判定要求 |
|---|---|---|---|
| B7 | G-L2-8 的 `passed=true` 无执行器签名、无 `exit_code` 映射、无超时与环境声明 | 不可复现，L2 可自证 | 签名对象 + 固定 `exit_code==0 ⇔ passed` |
| B8 | G-L2-9「四类副作用验证通过」无测试契约（谁跑、跑什么、什么算 pass） | ADR-10 无法强制执行 | 提供 `unload` 验证用例模板与断言字段 |
| B9 | 优化类「前后对照」无统计口径（n/effect/p_adj），与 45 verdict 关系未定 | 要么被规避，要么误杀 | 二选一：`gate45=PASS` **或** L1 统计报告（n≥30 且 p_adj<0.05） |
| B10 | 台账缺 `run_id`，与 `L2Envelope` 无关联键 | `tokens_used` 无法追溯 | 增加 `run_ids: []` 并规定与信封 1:N |
| B11 | `reported` 缺最小字段（repo / base_commit / env） | 无法复现，后续状态无法验证 | 纳入必填 |

---

## 五、P2 建议

- **B12** 两份契约都缺 `schema_version` 与迁移策略（建议 `1.0` 起步，破坏性变更升主版本）。
- **B13** `settled` 回写 L0 的落点未定（表名/JSONL 路径/字段映射），P3 无法开工。
- **B14** 无停滞检测（`paused`/`reproduced` 超过 N 天应告警或转 `abandoned`）。

---

## 六、可机器判定改造清单（复审门槛）

| # | 产物 | 通过判据 |
|---|---|---|
| 1 | `contracts/repair_ledger.schema.json` | 必填/枚举/签名/`settled` 四值；Draft 2020-12 校验器可跑 |
| 2 | `contracts/plugin_extension.schema.json` | inspect/experiment/install/unload 四组 request/response + 错误码枚举 |
| 3 | `contracts/state_machine.yaml` | states / transitions / guards / reopen / terminal 五段齐全 |
| 4 | `scripts/validate_contracts.py` | 真实台账通过（0）；5 个负例（跳步、退化、`settled` 缺 `process`、自填 `passed`、`ref` 不可解析）全部失败（1） |
| 5 | 迁移表（写进 SPEC §2.5） | 7 态 + 8 条合法边 + 重开边带 `attempts+1` |
| 6 | 契约版本与落点 | `schema_version` 存在；台账落点写明（表或路径） |

**建议的迁移表（供修订直接采用）**：

| from → to | guard | 备注 |
|---|---|---|
| reported → reproduced | `evidence.repro.cmd` 存在且 `fails_on_base=true` | 基线必须失败 |
| reported → abandoned | 无法复现且超时 | — |
| reproduced → root_caused | `root_cause` 非空 + 引用 ≥1 条证据 | — |
| root_caused → fixed | `change_ref.sha` 存在 | — |
| fixed → regression_passed | `evidence.regression.runner≠manual` 且 `exit_code=0` | — |
| fixed → root_caused | 回归失败，`reason` 必填，`attempts+1` | **重开边（修正 B1）** |
| regression_passed → settled | `settled` 四值齐全 + `run_ids` 非空 | — |
| 任意 → abandoned | `attempts>3` 或超 SLA | 终态 |

---

## 七、结论与下一步

1. **定位与路线通过；契约与状态机不通过**。当前版本可以指导人读，但不能指导 CI 判。
2. 先按 §六 交付 6 件产物（schema ×2 + 迁移表 + 校验脚本 + 版本/落点），再开 P3 台账实现；**不要先写业务代码再补 schema**，否则会把散文里的歧义固化进实现。
3. 复审只检查一件事：**`scripts/validate_contracts.py` 能否用 5 个负例把它们全部判红**。
