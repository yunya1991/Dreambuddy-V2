# SPEC · Shadow 验证自动放量门禁

> **版本**: v1.0 | **日期**: 2026-10-14 | **状态**: 设计已确认（用户 2026-10-14 裁定），待评审
> **模块**: 23-四层闭环自进化交易架构 / `dreambuddy_evolution`
> **关联**: [SPEC-A2-因果ATE历史样本接入.md](./SPEC-A2-因果ATE历史样本接入.md)（本门禁的首个放量目标）、`agi_config.py`、新建 `core/shadow_activation_gate.py`
> **定位**: 治理/安全设施——把「Shadow 验证 ≥7 天且正向 → 放量」从人工操作变为**自动、可审计、可回滚**。

---

## 0 · 决策摘要（用户已确认 2026-10-14）

| # | 决策点 | 裁定 |
|---|--------|------|
| D1 | 证据与「正向」判据 | **A2 门禁态自证**：影子期记录 `classify_ate_state` 三态；「正向」= 出现**态A** |
| D2 | 门禁规则 | **7 个自然日 + 出现态A**（每日 ≥1 条有效观测） |
| D3 | 评估机制 | **自包含 + 子进程隔离**：主链路只做 O(1)；评估在独立进程，交易进程零 DML 负担 |
| D4 | 门禁总开关 `enable_shadow_auto_activation` | **默认 True**（治理设施，本身不改交易行为；最坏也只是把 FAIL-OPEN 的 A2 打开） |

**硬约束（不可破坏）**: HC-AGI-02（异常→中性兜底）、HC-AGI-07（新模块默认关 / 满足条件才放量）、HC-AGI-08（因果引擎最小样本量 ≥500，不得下调）；FAIL-OPEN 铁律。

---

## 1 · 目标与非目标

### 1.1 目标
1. 目标开关（首个：`enable_causal_historical_samples`）在**影子期**（开关为 False）每日评估一次真实 ATE 门禁态，只记录、不调制。
2. 当「≥7 个自然日且出现过态A」→ **自动** `set_switch(target, True)`，记 `activated_at`。
3. **重启后自动恢复放量**（`reconcile_from_disk`），无需人工。
4. **一键回滚**：删除/清空状态文件即回到默认关；不改任何代码。

### 1.2 非目标
- 不制造因果效应：源B 是静态文件 → 恒态B → **单靠源B 永不触发**（见 §12）。
- 不改 `agi_config` 默认值、不改 A2 调制契约（态A 才调制、±1.15/0.85 有界）。
- 不复用 `shadow_backtest` 的日度统计（与 A2 门禁态无直接对接）。

---

## 2 · 关键概念

| 概念 | 定义 |
|------|------|
| **影子期** | 目标开关为 False 期间，仍每日评估但不施加调制（只记录证据） |
| **有效观测** | 某日评估成功：`method ∉ {insufficient_samples, error}` **且** `n ≥ min_n (500)`；记 `{date, gate_state, ate, lb, ub, source, n}` |
| **正向日** | `gate_state == "A"`（CI 不含 0 且 `\|ate\| ≥ τ`）；方向一致性在**放量后调制时**由现有 `_enhance_with_causal_ate` 处理，门禁本身不判方向 |
| **放量** | `set_switch(target, True)` + 状态文件写 `activated_at` + 认知 record |

---

## 3 · 架构与组件

| 文件 | 类 / 函数 | 职责 | 关键方法 |
|------|-----------|------|----------|
| `core/shadow_activation_gate.py`（新建） | `ShadowActivationGate` | **状态唯一入口**，无 DML，O(1) 读文件 | `record()`, `evaluate()`, `maybe_activate()`, `reconcile_from_disk()`, `is_activated()` |
| `core/shadow_ate_evaluator.py`（新建） | `evaluate_and_record()` | 产出当日证据（**含 DML**） | `evaluate_and_record(gate, switch_name)` |
| `scripts/shadow_ate_eval.py`（新建） | `main()` | 子进程入口 | `python -m dreambuddy_evolution.scripts.shadow_ate_eval --switch <name>` |
| `agi_config.py`（改） | `enable_shadow_auto_activation` | 门禁总开关（默认 True） | — |

**依赖方向**: `evaluate_and_record` → `ShadowActivationGate`（记录）；`ShadowActivationGate` → `agi_config.get_switch/set_switch`。门禁**不 import** evaluator（避免环），spawn 用子进程字符串。

---

## 4 · 状态文件 schema

**路径**: `dreambuddy_evolution/data/shadow_activation/<switch>.json`

```json
{
  "switch": "enable_causal_historical_samples",
  "shadow_started_at": "2026-10-14T18:00:00+08:00",
  "min_days": 7,
  "min_n": 500,
  "last_eval_attempt_date": "2026-10-14",
  "activated_at": null,
  "observations": [
    {"date": "2026-10-14", "gate_state": "B", "ate": 0.00163,
     "lb": -0.00185, "ub": 0.00512, "source": "bootstrap", "n": 279570}
  ]
}
```

- **写入**: 原子替换（`tempfile` 同目录 + `os.replace`）。
- **有效性门禁**: 仅 `n ≥ min_n` 且 `method ∉ {insufficient_samples, error}` 的观测才会被 `record()` 写入；无效观测**不落库**（§8）。
- **去重**: 同 `date` 保留**最后**一条。
- **损坏**: JSON 解析失败 → 视为空状态（FAIL-OPEN，不激活）。

---

## 5 · 门禁规则（精确）

```
# 未通过有效性校验（method∉{ok} 或 n<min_n）的观测在 record() 阶段即被拒写入（§4），
# 因此 observations 中每条都是有效观测。
valid_obs    = list(observations)                   # 均已通过有效性校验
valid_days   = len({o.date for o in valid_obs})
has_positive = any(o.gate_state == "A" for o in valid_obs)
eligible     = (valid_days >= min_days) and has_positive
```

`maybe_activate(target)`:
```
if not get_switch("enable_shadow_auto_activation"): return False
if get_switch(target):  return False          # 已开（或已被外部开启）
if today_has_no_valid_obs() and last_eval_attempt_date != today:
    spawn_evaluator()                          # 子进程，失败也写 last_eval_attempt_date
    invalidate_cache()                         # 丢弃 mtime 缓存，强制重读新观测
if evaluate().eligible:                        # gate 本地 O(1) 读文件算 eligible
    set_switch(target, True)
    state["activated_at"] = now_iso(); save()
    cognitive_record(...)                     # B 级：自动放量事件
    return True
return False
```

> 名称辨析: gate 的 `evaluate()` 是 **O(1) 读状态文件判 eligible**；evaluator 的 `evaluate_and_record()` 才**含 DML**。两者不同名不同物，`maybe_activate` 只调用前者。

---

## 6 · 数据流与时序

```
[进程启动] EvolutionPipeline.__init__ → gate.reconcile_from_disk()   （已 activated_at → set_switch(True)）
     │
[每次识别] PrimaryContradictionIdentifier.identify() → gate.maybe_activate()   （O(1)，含 mtime 内存缓存）
     │   └─ 若 门禁开 且 目标关 且 今日无有效观测 且 last_eval_attempt_date≠今日
     │        → subprocess(scripts/shadow_ate_eval.py, timeout=300)   （隔离进程，每日≤1 次）
     │             └─ evaluator: build_ate_samples() → estimate_ate() → classify_ate_state()
     │                  → gate.record(obs)  （子进程写 observations）
     │
[下次识别] gate.maybe_activate() → 读到新观测 → 判 eligible → set_switch(True) + activated_at
```

---

## 7 · 触发点与防阻塞

| 项 | 设计 |
|----|------|
| reconcile 接入点 | `evolution_pipeline.py` `EvolutionPipeline.__init__`（启动恢复放量） |
| maybe_activate 接入点 | `contradiction_identifier.py` `PrimaryContradictionIdentifier.identify()` 头部 |
| 惰性 spawn 守卫 | `last_eval_attempt_date != today`（**失败也写该字段**，避免反复起进程） |
| 子进程 | `subprocess.run([sys.executable, "<脚本>", "--switch", name], timeout=300, check=False, capture_output)` |
| 主链路成本 | 仅读 JSON（mtime 缓存）= O(1)，**不含 DML** |
| 并发写 | 评估子进程 = observations **唯一写入者**；主进程仅写 `activated_at`（原子替换）；碰撞概率极低，记已知局限 |

---

## 8 · 错误处理与硬约束（FAIL-OPEN）

| 场景 | 行为 |
|------|------|
| 状态文件缺失 / 损坏 | 视为空状态；不激活；不抛（HC-AGI-02） |
| 子进程失败 / 超时 | 不记录有效观测；写 `last_eval_attempt_date`；不激活 |
| `build_ate_samples()` 返回 None | 当日无有效观测（不算观测日） |
| `estimate_ate` 抛异常 | `method="error"` → 无效观测 |
| 目标开关已被外部开启 | `maybe_activate` 直接返回（幂等） |
| `min_n` 校验 | 沿用 **500**，不得下调（HC-AGI-08） |

---

## 9 · 开关与持久化语义

- **不改 `agi_config` 默认值**（`enable_causal_historical_samples` 保持 `False`）。
- 放量靠**运行时** `set_switch`（内存，遵既有语义）。
- **持久化由状态文件的 `activated_at` + 启动时 `reconcile_from_disk` 承担**（补齐 `set_switch` 不落盘的缺口）。
- **回滚**: 删除状态文件即回默认关；`ENABLE_SHADOW_AUTO_ACTIVATION=0` 可临时禁用门禁。

---

## 10 · 测试计划（TDD，`tests/test_shadow_activation_gate.py`）

| # | 用例 | 断言 |
|---|------|------|
| 1 | 未满 7 天 | 不激活；目标开关仍 False |
| 2 | 满 7 天但无态A | 不激活 |
| 3 | 满 7 天 + 出现态A | 激活 + `set_switch(True)` + `activated_at` 落盘 |
| 4 | 同 date 重复 record | 去重，只计 1 天 |
| 5 | `n < 500` 观测 | 不计有效观测日 |
| 6 | `method=insufficient_samples/error` | 不计有效观测日 |
| 7 | `reconcile_from_disk` 且 `activated_at` 已存在 | 启动即 `set_switch(True)` |
| 8 | 状态文件损坏 | 不激活、不抛异常（FAIL-OPEN） |
| 9 | 门禁总开关关 | `maybe_activate` 返回 False、不起子进程 |
| 10 | 今日已有有效观测 | **不** spawn 子进程（mock subprocess） |
| 11 | 目标已开 | `maybe_activate` 幂等返回 False |
| 12 | 默认值 | 断言 `AGI_SWITCHES["enable_causal_historical_samples"] is False`；`enable_shadow_auto_activation is True` |

新文件 `tests/test_shadow_ate_evaluator.py`：
| # | 用例 | 断言 |
|---|------|------|
| 13 | 合成源B（态A） | `record` 收到 `gate_state=="A"` |
| 14 | 源不足 | 不记录有效观测 |

---

## 11 · 验收证据（落地后产出）

- `docs/audit_reports/shadow_activation_<ts>.md`：门禁规则逐条复现（含 #3 放量路径、#7 reconcile、#8 FAIL-OPEN）；
- 对照：状态文件注入 7 天态B → 不激活；注入 6 天 + 第 7 天态A → 激活。

---

## 12 · 风险与诚实边界

1. **源B 静态 → 恒态B → 永不触发**：机制只保证「一旦真实效应出现就自动放量」，**不制造效应**。真正能放量的路径是**源A（实时矛盾样本）累积出真实态A**。
2. **子进程 DML ≈35s**（实测 `build 9.3s + estimate 25.2s`）：隔离在独立进程，交易进程零负担；但每日唯一一次后台进程会占用 CPU，注意与交易/训练进程的资源错峰。
3. **两写入者**（主进程写 `activated_at`、子进程写 `observations`）理论上有丢更新窗口；用原子替换缓解，记已知局限。
4. **"7 天"是自然日**：缺观测的日子不计入；不要求连续。
5. 门禁**不替代评审**：自动放量是 HC-AGI-07 允许的既定路径（满足条件即放量），但 `activated_at` 必须可审计。

---

## 13 · 任务分解（TDD）

| 任务 | 内容 |
|------|------|
| T1 | RED：`test_shadow_activation_gate.py`（#1-#12）+ `test_shadow_ate_evaluator.py`（#13-#14），确认红 |
| T2 | GREEN：`core/shadow_activation_gate.py`（record/evaluate/maybe_activate/reconcile，原子写，FAIL-OPEN） |
| T3 | GREEN：`core/shadow_ate_evaluator.py` + `scripts/shadow_ate_eval.py` + `agi_config` 新增 `enable_shadow_auto_activation=True` |
| T4 | 接线：`EvolutionPipeline.__init__` → `reconcile_from_disk`；`PrimaryContradictionIdentifier.identify()` → `maybe_activate`（惰性 spawn） |
| T5 | REFACTOR + 全量非回归（覆盖 causal/contradiction/pipeline 消费面） |
| T6 | 验收报告 + INDEX/CHANGELOG + commit + 认知闭环 |

---

## 14 · 认知闭环

- **落地后**：`record(content="[硬约束][自进化/治理] Shadow 自动放量门禁: 7 自然日+出现态A→自动 set_switch(True)+activated_at 持久化+reconcile; 门禁总开关 enable_shadow_auto_activation 默认 True; 评估子进程隔离; FAIL-OPEN 不激活", quality_level="B", tags="硬约束,HC-AGI-07,自进化,治理,自动放量,Shadow验证")` + `verify`。
- **前置**: 已 `recall(context="Shadow 验证 自动放量 自动激活门禁")`（命中 A2-M4 硬约束 + 三范式跃迁 shadow 期满放量先例）。
