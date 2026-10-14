# 验收报告 — Shadow 验证自动放量门禁

> **时间**: 2026-10-14 18:18
> **范围**: `SPEC-Shadow验证自动放量门禁.md` / `PLAN-Shadow验证自动放量门禁.md` Task 1-6
> **结论**: **通过**（新增 19 项测试全绿 + 定向非回归 133 项全绿 + 端到端真跑子进程隔离链路验证 + 4 组真实复现对照全部符合预期）

---

## 1. 交付物清单

| 类型 | 路径 | 说明 |
|------|------|------|
| 新增 | `dreambuddy_evolution/core/shadow_activation_gate.py` | 门禁状态唯一入口（O(1)、无 DML、原子写、FAIL-OPEN）|
| 新增 | `dreambuddy_evolution/core/shadow_ate_evaluator.py` | 当日证据评估（**含 DML**，仅子进程调用）|
| 新增 | `dreambuddy_evolution/scripts/shadow_ate_eval.py` | 子进程入口（argparse `--switch`）|
| 新增 | `dreambuddy_evolution/tests/test_shadow_activation_gate.py` | #1-#12 + spawn 正/反向 |
| 新增 | `dreambuddy_evolution/tests/test_shadow_ate_evaluator.py` | #13-#14 |
| 新增 | `dreambuddy_evolution/tests/test_shadow_gate_wiring.py` | 接线 2 项 |
| 修改 | `dreambuddy_evolution/agi_config.py` | 新增 `enable_shadow_auto_activation`（默认 True）|
| 修改 | `dreambuddy_evolution/evolution_pipeline.py` | `__init__` → `reconcile_from_disk` |
| 修改 | `dreambuddy_evolution/core/contradiction_identifier.py` | `identify()` 头部 → `maybe_activate` |
| 修改 | `docs/ENGINEERING_INDEX.md` / `docs/CHANGELOG.md` | 登记 + v1.15 |

---

## 2. 门禁规则（复述 SPEC 契约）

- `valid_days` = 去重有效观测日；有效 = `method ∉ {insufficient_samples, error}` 且 `n ≥ 500`
- `has_positive` = 观测中出现 **态A**
- `eligible = valid_days ≥ 7 且 has_positive`
- 满足 → `set_switch(target, True)` + 持久化 `activated_at` + 认知 record（B 级）
- 门禁总开关 `enable_shadow_auto_activation` 默认 **True**（治理设施，本身不改交易行为）

---

## 3. 验收证据

### 3.1 单测（新增，全绿）

```
python -m pytest dreambuddy_evolution/tests/test_shadow_activation_gate.py \
  dreambuddy_evolution/tests/test_shadow_ate_evaluator.py \
  dreambuddy_evolution/tests/test_shadow_gate_wiring.py -q
→ ................... [100%]   (19 passed)
```

### 3.2 定向非回归（10 个测试文件，全绿）

```
python -m pytest dreambuddy_evolution/tests/test_phase2_causal.py \
  test_causal_engine.py test_causal_sample_store.py test_contradiction_identifier.py \
  test_primary_contradiction_detector.py test_contradiction_feedback.py \
  test_counterfactual_transfer.py + 3 个新增 -q
→ 133 passed (exit 0)
```

### 3.3 端到端真跑子进程（隔离链路）

```
python -m dreambuddy_evolution.scripts.shadow_ate_eval --switch enable_causal_historical_samples
→ EXIT=0
```

落库状态文件（真实源B n=279,688）：

```json
{ "date": "2026-10-14", "gate_state": "B",
  "ate": 0.001630, "lb": -0.001882, "ub": 0.005143,
  "source": "bootstrap", "n": 279688 }
```

- 无 `method` 字段 → 持久化剥离 method 契约生效
- `activated_at: null` → **未提前放量**（符合源B 恒态B 的预期）

### 3.4 真实复现对照（真实 gate 实例 + 临时状态目录）

| 场景 | 预期 | 实测 |
|------|------|------|
| 对照1：7 天全态B | 不激活 | `valid_days=7 has_positive=False eligible=False maybe_activate=False target=False` ✅ |
| 对照2：6 天态B + 今日态A | 激活 | `valid_days=7 has_positive=True eligible=True maybe_activate=True target=True activated_at=True` ✅ |
| #8：状态文件损坏（FAIL-OPEN）| 不抛、不激活 | `不抛=True eligible=False maybe_activate=False target=False` ✅ |
| #7：`activated_at` 已存在 → reconcile | 放量 | `r=True target=True` ✅ |
| #5/#6：无效观测拒写 | 拒 | `insufficient=False small_n=False today_has_obs=False` ✅ |

> 备注：#8 复现中 `CognitiveLoopEntry load fail: No module named 'cognitive_loop_entry'` 为认知桥 FAIL-OPEN 调试日志（隔离上下文下模块不可导入），**不影响激活判定**（对照2 仍成功放量），符合 HC-AGI-02。

---

## 4. 硬约束核对

| 约束 | 核对结果 |
|------|---------|
| HC-AGI-02（异常 → 中性兜底，不抛） | ✅ 损坏状态 / 认知桥不可用 / spawn 失败均 FAIL-OPEN，无异常外泄 |
| HC-AGI-07（新模块默认关 / 满足条件才放量） | ✅ `enable_causal_historical_samples` 配置默认值保持 `False`；仅运行期放量 |
| HC-AGI-08（min_n = 500 不得下调） | ✅ `min_n=500`，`n<500` 观测被拒（#5 复现）|
| 主链路零 DML | ✅ `ShadowActivationGate` 不 import evaluator/causal；DML 仅在子进程 |
| 测试绝不起真实评估子进程 | ✅ 全部单测/复现 monkeypatch `_spawn_evaluator` |

---

## 5. 已知边界（诚实披露）

1. **源B 为静态文件 → 恒态B → 单靠源B 永不触发**。门禁只保证「真实态A 出现即自动放量」，**不制造效应**。真正可走通的放量路径是源A（实时矛盾样本）累积出真实态A。
2. **预存在失败（与本变更无关）**：`dreambuddy_evolution/tests/test_gene_governance.py::test_gene_audit_schema_validation` — `GeneAuditGate.validate_schema` 对「额外字段」未拒绝（v1.13 基因治理遗留），实际拒绝逻辑与测试断言不一致。已复现确认；**不属本次 Shadow 变更范围**，建议单独开单修复。
3. `set_switch` 仅运行期生效（内存，不落盘）；跨进程/重启一致性由 `reconcile_from_disk()` 补齐。

---

## 6. 结论

Task 1-6 全部落地并通过验收。门禁「≥7 自然日 + 出现态A → 自动放量」链路（状态入口 → 子进程评估 → 放量 → 持久化 → 启动恢复）端到端可跑通，且全程 FAIL-OPEN、不越 HC-AGI-07/08。
