# 修复清单：R_reflexivity 恒 0.65（反射性公式 v2 重构）

> 诊断日期：2026-11-25 · 现象：云端 N2 `R_reflexivity` 24h distinct=1，恒 0.65
> 状态图例：`[ ]` 待修 · `[~]` 进行中 · `[x]` 已完成 · `[-]` 关闭（非缺陷/无需修） · `[!]` blocked（待决策）
> 改造原则：**默认行为保持 legacy 不变**，v2 走 env 开关 + 影子字段，先单测后切换

## 诊断结论（已用云端真实指标证实）

`0.4×corr_term + 0.3×liq_term + 0.3×sent_term = 0.4×0.5 + 0.3×1.0 + 0.3×0.5 = 0.65`

| 分项 | 恒值 | 原因 |
|---|---|---|
| `sent_term=0.5` | 情绪被 FO-1 兜底 | 云端 `USE_FINBERT=0` → `_SENTIMENT_FO1_ACTIVE=True` → `sent=0.5` |
| `corr_term=0.5` | 依赖 `sent-0.5` 单点 | 旧式 `tanh(slope/std×5×(sent-0.5)×4)`，`sent=0.5` ⇒ 因子恒 0 |
| `liq_term=1.0` | `spread=0` 被当成完美流动性 | `1-0/50=1.0`，30% 权重固定送满分 |

## v2 公式设计（方案 2）

**corr 项**：改为「价格动量方向 × 情绪偏离幅度」的同向性，不再被 `sent` 单点值归零。

```
m          = tanh(mean(Δclose[-w:]) / (std(Δclose[-w:])×100) × gain)     # ∈[-1,1]，w=10, gain=5
sent_dev   = sent - 0.5
|sent_dev| < eps(0.02) → corr_proxy = m × 0.75                          # momentum_only：情绪无信息，纯动量给方向
否则                    → amp = 0.5 + 0.5×min(1, |sent_dev|/0.5)
                          corr_proxy = m × amp × (+1 同向 / -1 背离)     # aligned / divergent
corr_term  = 0.5 + 0.5×corr_proxy
```

**liq 项**：`spread` 为 0 / 负 / NaN 时视为「数据缺失」，不再当满分。

```
liq_term = 0.5（中性），liq 权重 × liq_degraded_scale(0.5) → 0.15
释放出的 0.15 按 corr:sent = 4:3 比例补偿 → corr 0.4857 / liq 0.15 / sent 0.3643
```

**sent 项**：保持 `clamp(sent,0,1)` 不变；FO-1 时仍对最终值 clamp ≤0.66。

## 清单

| # | 问题 | 根因 | 修复动作 | 验收标准 | 状态 |
|---|---|---|---|---|---|
| R1 | `R_reflexivity` 恒 0.65、24h distinct=1 | 三项同时退化（见上表） | 落地 v2 公式，env 开关 `ENABLE_RV_REFLEXIVITY_V2` 默认 legacy | 单测：sent=0.5 + 有动量时 v2 ≠ legacy 且随动量方向变化 | `[x]` |
| R2 | `corr_term` 在 `sent=0.5` 时恒 0.5 | `(sent-0.5)` 作为乘子，中性情绪把整项归零 | 拆为「动量方向 m」×「情绪同向性 amp」；中性情绪走 `momentum_only` | 上行动量 `corr_term>0.5`、下行动量 `<0.5`，差值 ≥0.2 | `[x]` |
| R3 | `liq_term` 在 `spread=0` 时恒 1.0，固定送 0.3 | 0 bps 被判为「完美流动性」，实际是占位缺失值 | `spread≤1e-9` 或 NaN → `liq_term=0.5` 且权重 ×0.5，释放权重按 4:3 补给 corr/sent | 单测：spread=0 时 `liq_mode=degraded`、liq 权重≈0.15、有效权重和=1 | `[x]` |
| R4 | 直接改公式存在线上回归风险 | 无开关、无影子对比 | 新公式仅由 env 开关启用；legacy 路径代码原样保留 | 单测：开关关闭/未设置 → `formula=legacy` 且结果与旧值逐位一致（0.65） | `[x]` |
| R5 | 无法观测 v2 与 legacy 的差值 | `last_reflexivity_detail()` 只有旧分项 | 影子字段：始终计算 `R_reflexivity_v2`，并输出 `formula/corr_mode/momentum_m/liq_mode/v2_weights` | 单测：legacy 模式下 detail 仍含 `R_reflexivity_v2` | `[x]` |
| R6 | 新常量有散落硬编码风险 | R-1 硬约束：权重唯一源 `weights.py` | 新增 `WEIGHTS["R_REFL_V2"]` 承载 window/gain/eps/damp/scale | 单测：缺配置时走默认值仍可算（fail-open） | `[x]` |
| R7 | `calculate()` 9 字段 Gold Schema 不能加 key | `additionalProperties=False` | 诊断只走 thread-local detail；v2 不新增返回字段 | 单测：v2 模式下 `jsonschema` 校验通过，key 集合仍为 9 | `[x]` |
| R8 | v2 生效后 `ReflexivityConstant` 仍 firing（MSTR/BTC） | exporter `_tail_jsonl` 只读文件尾部 512KB（≈3068 行），`distinct_24h` 实际只有几分钟窗口，每 symbol 仅 1~2 点 → distinct 恒 1 | 新增 `_iter_jsonl_since`（全文件流式 + ts 过滤 + stage 预筛），`signal_calibration_metrics` 改用它；补跨 512KB 回归测试 | 指标复算与真实 24h 全量一致（distinct 3~13）；单测/ruff 通过；单次扫描 0.11s | `[x]` |
| R9 | 切换前已停更的 symbol（COIN/WIF）仍报恒定 | 24h 窗口内只剩 legacy 0.65 样本 | 非代码缺陷；样本滚出 24h 窗口后序列消失，告警自动恢复 | COIN 17:01Z / WIF 13:50Z 后 `ReflexivityConstant` 消失 | `[-]` |
| R10 | legacy 样本与 v2 样本混算：停更 symbol 恒 1 假告警 + 混合 symbol 被 legacy 抬高 distinct（掩盖真实恒定） | `refl_series` 不区分公式口径 | 只聚合与窗口内最新样本同公式的 N2 记录（`refl_components.formula`），legacy-only symbol 不再导出反射性指标 | 单测：COIN 全指标不导出；BTC（legacy 0.65 + v2 0.50）distinct=1 | `[x]` |
| R11 | 停更的 v2 symbol（LTC 24h 内仅 2 个同值样本）仍报恒定 | 样本量不足时 distinct=1 无统计意义 | 每 symbol 最新样本早于 3h（`_REFLEXIVITY_FRESH_SECONDS`）即不导出反射性指标 | 单测：LTC 不导出；云端活跃 17 symbol distinct 均 3~12 | `[x]` |

## 执行记录

| 时间 | 项 | 动作 | 结果 |
|---|---|---|---|
| 2026-11-25 | R1~R7 | 生成 FIXLIST + v2 设计定稿 | `[x]` |
| 2026-11-25 | R1/R2 | `resistance_vector.py` 抽出 `_refl_momentum` / `_refl_corr_v2`，sent=0.5 走 momentum_only；新增 TR-RV-12/13 | `[x]` 18 passed（含既有 11 项） |
| 2026-11-25 | R3 | `_refl_liq_v2` + `_refl_v2_weights`：spread≤1e-9 → 中性 0.5 且权重 0.3→0.15，释放权重按 4:3 补给；TR-RV-14 | `[x]` 有效权重和=1 |
| 2026-11-25 | R4/R5 | legacy 路径原样保留，`ENABLE_RV_REFLEXIVITY_V2` 默认关；detail 恒输出 `R_reflexivity_v2` 影子；TR-RV-15/17 | `[x]` legacy 仍精确 0.65 |
| 2026-11-25 | R6/R7 | `weights.py` 新增 `R_REFL_V2`（window/gain/eps/damp/scale）；9 字段 Schema 未被污染；TR-RV-16/18 | `[x]` ruff 全通过 |
| 2026-11-25 | 回归 | `test_weights.py` + `test_kline_event_handler.py` | `[x]` 57 passed |
| 2026-11-25 | 提交 | `52b3406c94` 推送 GitHub；云端快进 `52b3406c9`，重启 entry23（01:30:04 CST） | `[x]` 默认 legacy 实测 0.65 / 影子 v2=0.682 |
| 2026-11-25 | 切换 | 云端 drop-in `/etc/systemd/system/dreambuddy-entry23.service.d/10-refl-v2.conf` 设 `ENABLE_RV_REFLEXIVITY_V2=1`，daemon-reload + 重启（01:36:15 CST） | `[x]` 进程 env 已含该变量 |
| 2026-11-25 | 复诊 | 告警仍 firing：云端 N2 全量 1612 条，v2 有 205 个不同取值（最新 0.4983，momentum_only / liq degraded），确认公式正常；定位为 exporter 指标窗口 bug | `[x]` 尾部截断复算与 Prometheus 逐项一致 |
| 2026-11-25 | R8 | `52b3406c9`→`502177e41`：新增 `_iter_jsonl_since` + 回归测试，15 域 37 tests / ruff 通过 | `[x]` |
| 2026-11-25 | 部署 | 云端 ff-only 至 `502177e41`，重启 `dreambuddy-metrics-exporter`（18:16:02 CST） | `[x]` distinct_24h 恢复 3~13 |
| 2026-11-25 | 复验 | MSTR/BTC 等 12 个 firing/pending 告警消除；仅 COIN/WIF 剩 pending（切换前停更样本，到期自动消失） | `[x]` |
| 2026-11-25 | R10 | `8363bc3fa`：口径隔离（只聚合当前公式样本），38 tests / ruff / black 通过 | `[x]` COIN/WIF 告警消除 |
| 2026-11-25 | R11 | `411cdc8bb`：3h 新鲜度门槛；云端 dry-run 17 个活跃 symbol distinct 3~12 | `[x]` |
| 2026-11-25 | 部署复验 | 云端 ff-only 至 `411cdc8bb`，重启 exporter（18:22:46 CST）；`ReflexivityConstant` 全清（0 条） | `[x]` |
