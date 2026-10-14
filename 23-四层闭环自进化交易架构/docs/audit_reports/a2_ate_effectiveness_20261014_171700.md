# A2 验收证据 · 因果 ATE 历史样本接入效果报告

> **任务：** SPEC-A2-因果ATE历史样本接入.md（v5 落地：T2/T3/T4）
> **生成：** 2026-10-14 17:17 CST
> **代码基线：** git `619a646407`（变更未提交）
> **结论：** 验收①（估计成功）✅、验收②（如实报告）✅、验收③（对照可复现）✅
> **净收益边界（v5 §0.5）：** 源B 阶段 A2 的实证净收益 = **消除「恒定 ×0.95 下偏」副作用 + 建立可估计/可复现/可审计的因果诊断管线**；**正向调制收益需待 P1（CATE/regime 分桶）或源A 累积 ≥500**。不得表述为「已带来显著因果增益」。

***

## 一 · 主证据：全量源B 真实数据 ATE（`R_up>median` 预注册口径）

**数据源：** `dreambuddy_evolution/gene_data/shadow_rl_samples.jsonl`（71 MB，2026-10-14 16:59）
**装载：** `CausalSampleStore.build_ate_samples()`（源A 磁盘 0 条 → 独用源B）

| 字段 | 值 |
| :--- | :--- |
| source | `bootstrap` |
| n（有效样本） | **279,570** |
| method | `causalml_dml` ✅（非 insufficient_samples / error） |
| **ate** | **0.0016314** |
| lower_bound | −0.0018543 |
| **upper_bound** | 0.0051170 |
| **ci_method** | **`block_bootstrap`**（stationary，块长≈⌈n^(1/3)⌉）✅ |
| significant | **False**（CI 含 0） |
| **effect_size（Cohen's d = ate/std(y)）** | **0.0227**（std(y)=0.07190） |
| trial_count | 1（预注册 treatment 定义数） |
| fdr_adjusted | False（单一预注册检验，无多重比较） |

**positivity / overlap 诊断（仅诊断不阻断）：**

| 指标 | 值 |
| :--- | :--- |
| tail_ratio（倾向得分 p<0.05 或 p>0.95 占比） | 0.3634（n_tail=101,609） |
| ate_trimmed（trimming p∈[0.05,0.95] 后 ATE） | −0.0001471 |
| trimmed_n | 177,961 |

> **解读：** 尾部占比 36.3% 偏高，trimming 后 ATE **符号由 + 翻转为 −**（≈0）→ 提示重叠不足、估计对权重敏感。这构成「不显著」的**合法理由**（SPEC §2.5），报告须显式声明「数据不支撑强可比对照」。

***

## 二 · 经济显著性三态门禁判定（TOST / SESOI）

**τ 来源：** 交易成本折算（双边换手+滑点 ≈5–10bps → reward 尺度），**独立预注册、禁止事后反推**。**默认 τ=0.05**。

| τ 档位 | 判据 | 判定态 | 动作 |
| :--- | :--- | :--- | :--- |
| **0.02** | CI=[−0.00185, 0.00512] ⊆ (−0.02, 0.02) | **态B** | no-op |
| **0.05** | 同上 ⊆ (−0.05, 0.05) | **态B** | no-op |
| **0.10** | 同上 ⊆ (−0.10, 0.10) | **态B** | no-op |

> **三档判定态一致 = 结论稳健**（SPEC §6.2 #19）。观测性源落 **态B「经济等价于零」→ no-op**，**替代旧 A1 恒定 ×0.95**（回收系统性 5% 下偏）。

***

## 三 · 对照实验（可复现）

### 对照 A：开关 True vs False（同一 identifier/paths）

| 组 | 输入 | method | strength（base 0.8） |
| :--- | :--- | :--- | :--- |
| True（历史样本可用） | 800 条合成源B | `causalml_dml` | **0.8（态B no-op）** |
| False（退回 live paths） | 2 条路径 | `insufficient_samples` | 0.8 |

- **断言：** True 组 `causal_ate.method` 变化（insufficient → causalml_dml）✅；strength 因落态B **不偏移**（诚实反映「不确定/经济等价于零」）。
- 测试：`test_real_ate_from_historical_samples_adjusts_strength`（#10）、`test_switch_off_reverts_to_live_paths`（#12）。

### 对照 B：有效样本 ≥500 vs <500 / treatment 退化

| 组 | 输入 | strength | 说明 |
| :--- | :--- | :--- | :--- |
| 有效 ≥500 | 600 条源B | 按态门禁（此处态B→不变） | 被调制（进入门禁） |
| <500 / 无文件 | 空 | **逐位不变 0.8** | A1 契约（`insufficient_samples` no-op） |
| treatment 退化 | R_up 恒定 | **返回 None → no-op** | 退化保护（#8） |

- 测试：`test_insufficient_still_noop`（#11）、`test_degenerate_treatment_returns_insufficient`（#8）、`test_both_insufficient_returns_none`（#4）。

***

## 四 · 复现命令与种子

```bash
# 工作目录：23-四层闭环自进化交易架构
# 1) 单元/契约测试（含三态门禁 #14-#20）
python -m pytest dreambuddy_evolution/tests/test_causal_sample_store.py \
                 dreambuddy_evolution/tests/test_contradiction_identifier.py \
                 dreambuddy_evolution/tests/test_causal_engine.py -q

# 2) 全量源B 真实数据 ATE（本文 §一 数值）
#    CausalSampleStore() 默认读 gene_data/shadow_rl_samples.jsonl；
#    CausalEngine().estimate_ate(X, treatment, y, method="dml")；
#    treatment=R_up>median(R_up) 预注册；block bootstrap seed=42，n_boot=200，块长=⌈n^(1/3)⌉。
```

**固定种子：** block bootstrap `default_rng(seed=42)`；合成 fixture `default_rng(2026)`。
**可复现性：** 同一数据切片 + 同种子 → 数值逐位可复现（#9 断言 `significant=True` 合成强效应）。

***

## 五 · 硬约束守门

| 约束 | 状态 | 证据 |
| :--- | :--- | :--- |
| HC-AGI-08（MIN_SAMPLES=500 不得下调） | ✅ | `test_min_samples_remains_500`（#13） |
| HC-AGI-02（异常→中性兜底） | ✅ | `estimate_ate` 异常→`method="error"`→态C no-op；`build_ate_samples` FAIL-OPEN 返回 None（#6） |
| HC-AGI-07（新模块默认关） | ✅ | `enable_causal_historical_samples=False`（agi_config.py） |
| FAIL-OPEN 铁律 | ✅ | 文件缺失/装载异常/门禁口径不符 → no-op |

***

## 六 · 诚实边界声明（必读）

1. **源B 为观察性代理，非干预因果**（SPEC §1.2）：`R_up` 是观测到的状态属性，非随机分配干预 → ATE 是「观察性关联的因果近似」，存在反向因果/混淆风险。
2. **效应量实务≈0**：Cohen's d≈0.023，trimming 后 ATE≈0 → **不得表述为「显著提升收益」**，也**不得作为「ATE 已验证有效」的依据**。
3. **positivity 不足（tail_ratio 36.3%）**：数据重叠不足，trimming 改变符号 → 本判定**不支撑强因果主张**。
4. **CI 口径**：`block_bootstrap`（自相关稳健）替代 causalml 默认 i.i.d. bootstrap；点估计仍取 causalml DML，CI 标准误由线性 ATE 代理的 block bootstrap 给出（记录为方法学折中，SPEC §2.5）。
5. **A2 净收益**：源B 阶段实证净收益 = 去偏（回收恒定 ×0.95）+ 建立可审计因果诊断管线；**正向调制收益待 P1 或源A ≥500**。
6. **regime 漂移**：本次全量（无截断），未做 regime 分桶 → 后续 P1 处理。

***

## 七 · 附：本报告对应的代码与测试增量

| 文件 | 变更 |
| :--- | :--- |
| `dreambuddy_evolution/core/causal_sample_store.py` | 新增（双源/优先级/退化保护/单例缓存/FAIL-OPEN） |
| `dreambuddy_evolution/core/causal_engine.py` | `estimate_ate` 增补 `ci_method/effect_size/positivity/trial_count`；新增 stationary block bootstrap CI |
| `dreambuddy_evolution/core/contradiction_identifier.py` | 新增 `classify_ate_state` 三态门禁 + `SESOI_TAU_*`；`label_previous` 落盘；`_enhance_with_causal_ate` 接入历史样本 + TTL 缓存 |
| `dreambuddy_evolution/agi_config.py` | 新增开关 `enable_causal_historical_samples=False` |
| `dreambuddy_evolution/tests/test_causal_sample_store.py` | #1-#9 + #13 |
| `dreambuddy_evolution/tests/test_contradiction_identifier.py` | #10-#12 + #14-#20（v5 门禁契约） |
