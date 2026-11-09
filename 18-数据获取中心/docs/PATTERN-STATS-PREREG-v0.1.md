# 预注册 — P3 模式库统计口径 v0.1（冻结）

> **状态**：🔒 冻结（2026-11-10）。任何口径修改必须升版本号并保留本文件。
> **归属**：SPEC-D1-NARRATIVE-PRIMITIVES §2.5（模式库）+ SPEC-EMERGENCE-3D §2.1 D1 多重比较三层防线（附录 E-T1.4 预注册内执行）
> **适用范围**：18-数据获取中心 shadow 模式库（events_d1.jsonl → patterns_d1.jsonl），FAIL-OPEN，不进生产链路。

## 0. 数据单元

- 模式 cell = `(event_type, regime_bucket)`，事件来源 events_d1.jsonl（EventStore）。
- 观测值 = 事件的 `reaction["T+24h"]`（T+7d 只作佐证，不进检验）。无 T+24h 的事件不计入 cell。
- regime_bucket 由价格序列在事件时刻现算（不回写 event store，保持事件库不可变）：
  - `ret30 = close(t) / close(t-30d) - 1`
  - `bull`: ret30 > +5%；`bear`: ret30 < −5%；否则 `chop`；历史不足 30 天 → `unknown`（cell 报告但不参与候选判定）。
- 无条件基准 μ0 = 全部日 K 的日前向收益（T+24h 口径，即日收益）均值，覆盖整个价格序列。

## 1. 第一层：批内 Holm 校正

- family = 同一 `event_type` 下全部 regime cell（含 n<8 的 cell，一并计入比较集，诚实暴露多重性）。
- 每 cell 原始 p 值：单样本双侧 t 检验，`H0: mean(reaction) = μ0`（scipy `ttest_1samp`）；n<2 或方差=0 且均值≠μ0 时退化为符号判定，均值=μ0 时 p=1.0。
- family 内 Holm-Bonferroni 校正（口径同 23-四层闭环 `framework_comparison.holm_bonferroni`，含单调性约束）。
- **候选判据**：`n_events ≥ 8` 且 `holm_p < 0.05`。

## 2. 第二层：批级 PBO / CSCV

- 粒度：每个 event_type family 单独计算。family 内 n≥8 的 cell **≥3 个**才可计算（2 个时 CSCV 退化：IS 最优的 OOS 分位恒为 0.5，必判过拟合，无信息量）；否则记 `pbo=null` + `insufficient_data`（不跳过记录，参照 SPEC-EMERGENCE-3D 估计器不可用口径）。
- 轴口径（冻结）：CSCV 在**事件序号轴**上执行（非日历轴——稀疏不等长事件无公共日历轴）。各 cell 事件按 trigger_ts 升序；K = family 内合格 cell 的最小 n；S = min(16, ⌊K/2⌋ 向下取偶)，下限 4（K≥8 由合格门槛保证）；每 cell 截断至 S×⌊K/S⌋ 个事件（尾部舍弃）。
- 算法与 45-评测系统 `backtest.pbo_cscv` 一致：IS 半块组合选 Sharpe 最优 cell，看其 OOS 分位 ≤0.5 记过拟合；PBO = 过拟合比例。块大小 <2 时 Sharpe 不可算 → 该组合跳过。
- **整批拒入**：`PBO > 0.50` → 该 family 全部 cell 不得晋级 verified（candidate 保留，family 标 `blocked`）。`insufficient_data` 同样不得晋级 verified（保守口径）。

## 3. 第三层：胜出者 SPA / DSR

- 仅对通过第一层的 candidate 集合执行。
- **SPA（主判）**：Hansen(2005) 重定中心 bootstrap 口径——
  - 每 cell 统计量 `t_k = (mean(r_k) − μ0) / (sd(r_k)/√n_k)`（sd=0 时 t=±inf 按均值方向，均值=μ0 时 t=0）；
  - bootstrap：cell 内事件有放回重抽样，抽样前各 cell 减去自身观测均值（强加零假设），B=5000，seed=42；
  - `spa_p[k] = fraction(max_j(t_j^b) ≥ t_k^obs)`（White RC 形式的 per-cell 保守 p）。
  - 晋级要求 `spa_p < 0.05`。
- **DSR（佐证，不作门禁）**：`deflated_sharpe(sharpe=mean/sd, n_obs=n, n_trials=trials_count)`，口径同 45-评测系统 `backtest.deflated_sharpe_ratio`。写入 evidence。
- **trials_count（冻结）**：本轮发现运行中参与检验的全部 cell 数（含 n<8、含 unknown 以外的所有 regime cell）。写入每条 pattern 的 evidence。

## 4. status 流转（本层判定）

| status | 判据（全部满足） |
|---|---|
| `candidate` | n_events ≥ 8 且 holm_p < 0.05 |
| `verified` | candidate 且 family PBO ≤ 0.50 且 spa_p < 0.05 且方向稳定（时序对半切，两半均值同号且与全体同号） |
| `falsified` | 复测方向翻转（本期初建不产生，留待后续复测周期） |
| 无 status | 不满足 candidate 的 cell 仍落盘（status 缺省），保证发现过程可审计 |

- 方向稳定窗口：按 trigger_ts 中位数切半（冻结为 2 窗；SPEC §2.5 的「≥2 独立时间窗」按下限执行）。
- **退出纪律**：任一 family 全灭或 0 candidate，如实报告，不为过关凑数（Fail-open 退出原则，SPEC §4）。

## 5. 复用声明

- Holm：算法对齐 23-四层闭环 `dreambuddy_evolution/core/framework_comparison.py::holm_bonferroni`。
- PBO/CSCV、PSR/DSR：算法对齐 45-评测系统 `evaluators/finance/backtest.py::pbo_cscv / deflated_sharpe_ratio`。
- SPA：仓内无既有实现，本模块新建（Hansen 2005 / White 2000 文献口径）。
- 跨域代码不互相 import（域独立部署），以 vendored 函数 + parity 校验保证一致。
