# 优化提案：自进化引擎三点升级

> **提案编号**: PROP-20260809-SELF-EVO（含 3 个子提案）
> **提案类型**: 系统升级（交易进化引擎代码变更）
> **审批类别**: `trading`（交易进化提案 → **人工审批，永不自动批准**）
> **R 级别**: R2（须人工审核，禁止自动落地 — 宪法 H009 约束）
> **状态**: `delivered`（2026-08-09 02:10 UTC — E1 实施完成 + E2 独立审查全部修复 + 24/24 测试通过）
> **创建时间**: 2026-08-09 01:20 UTC
> **目标文件**: `11-易经推理系统/scripts/memory_l4/self_evolution_engine.py`（745 行）
> **提案来源**: 2026-08-09 自进化闭环深度拆解（会话 20260809_004026）中识别的 3 个可进化点，用户选定走正式审批流

---

## 一、背景

自进化闭环是认知系统"实践→认知升级→回测→固化基线→进化"原则的核心落地：

```
实盘统计 → 停滞检测(3条件) → 三层反思(A8/做梦部/联网)
→ 提案池 → 采纳门禁(_backtest_and_adopt) → 固化(config.json + constraints/releases/v0.1.N.json)
→ polling_trader 热重载生效
```

深度拆解（含 `self_evolution_engine.py` 全部 745 行精读）后，识别出 3 个"命名/设计意图 vs 实际实现"的 gap。三者均为**进化机制本身的升级**，不触碰 V9 基线规则，不修改仓位上限/杠杆等危险参数。

---

## 二、子提案清单

### PROP-20260809-001 ｜ Walk-Forward 门禁落实为真实提案级回测

**问题描述（代码证据）**

`_backtest_and_adopt()` 声称做 Walk-Forward 验证，实际是纯规则检查：

| 行号 | 证据 |
|:---|:---|
| L579-581 | `import WalkForwardEngine` 并实例化 `wfe = WalkForwardEngine(BCRMEngine())` |
| L592 | `if wfe and recent_decisions and len(recent_decisions) >= 5:` — **wfe 仅作真值判断，`wfe.run()` 从未被调用**（死实例化） |
| L594 | 注释自认："仅检查提案是否属于已知安全类型（不做完整回测节省时间）" |
| L595-601 | 实际逻辑 = 白名单集合成员检查（8 个安全参数直接通过） |
| L609 | `backtest_result = {"validated": True, "method": "rule_check"}` — "validated" 名不副实 |

**修复方案**

1. 对每个候选提案调用 `WalkForwardEngine.run()`（`bcrm/walk_forward.py:327`，API 已存在）：以提案参数替换当前参数，在 recent_decisions 窗口上做滚动对比回测
2. 采纳条件升级为：`白名单检查通过 AND 回测指标不劣化`（胜率/准确率不低于基线，或按提案 direction 改善）
3. `backtest_result` 记录真实指标：`{"validated": true, "method": "walk_forward", "baseline": {...}, "proposed": {...}, "delta": {...}}`
4. 数据不足分支（L603-605）保持现状：a8/dream 来源直接采纳（冷启动兜底）

**影响面**: 仅 `self_evolution_engine.py` L585-618 采纳循环；白名单边界（8 安全参数）不变；config 固化链路（4 个进化键）不变。

**风险与对策**
- ⚠️ 回测耗时增加（每提案一次滚动回测）→ 对策：提案去重后批量验证 + 单次窗口上限（复用 walk_forward 既有分片逻辑）
- ⚠️ recent_decisions 样本少时回测噪声大 → 对策：样本 <20 时降级为 rule_check 并在 backtest_result 标注 `degraded: true`

**回滚方案**: `git revert` 单 commit；config 侧无变更（本提案只改验证逻辑，不改参数值）；constraints/releases 快照机制天然支持审计。

**验收标准**
- [ ] `wfe.run()` 被实际调用（静态检查可验证）
- [ ] 非白名单提案依旧跳过（需人工确认）不变
- [ ] 白名单提案须回测不劣化才采纳；构造一个"劣化提案"测试用例验证被拒绝
- [ ] backtest_result 含真实 baseline/proposed 指标

---

### PROP-20260809-002 ｜ 提案参数值数据驱动化（接入 Optuna）

**问题描述（代码证据）**

三层反思生成的提案参数值是硬编码魔法数，非数据优化产物：

| 行号 | 硬编码值 | 参数 |
|:---|:---|:---|
| L221 | `param_value: 0.015` | velocity_threshold（卦象单一化对策） |
| L251 | `param_value: 0.015` | velocity_threshold（另一分支） |
| L321 | `param_value: 0.35` | sentiment_weight（投射对策） |

**修复方案**

1. 复用系统已有的 `bayesian_optimize.py`（`memory_l4/bayesian_optimize.py:26` 已 `import optuna`，objective/backtest 框架完整）
2. 提案生成流程改为：反思层确定**待调参数与方向**（如"降低 velocity_threshold"）→ Optuna 在方向约束的搜索空间内、以 recent_decisions 数据做小规模贝叶斯寻优（n_trials 上限控制成本，建议 ≤30）→ 输出数据支撑的 param_value
3. 优化失败/数据不足时降级为现有硬编码默认值（保持可用性），提案标注 `value_source: "optuna" | "default_fallback"`
4. 白名单边界不变：Optuna 只能在 8 个安全参数范围内寻优

**影响面**: `self_evolution_engine.py` 提案生成段（L200-330 区域）+ 新增对 bayesian_optimize 的调用封装。

**风险与对策**
- ⚠️ Optuna 寻优耗时 → 对策：n_trials≤30 + 仅在停滞触发后运行（非每轮）；超时降级默认值
- ⚠️ 小样本过拟合 → 对策：寻优目标函数含保守正则（惩罚激进参数值），且最终仍过 PROP-001 的 Walk-Forward 门禁
- ⚠️ 依赖 optuna 包 → 对策：import 失败自动降级 default_fallback（与现有 LLM 降级纯规则模式同模式）

**回滚方案**: `git revert` 单 commit；寻优只影响提案值生成，config 固化/约束快照/热重载链路不变。

**验收标准**
- [ ] 至少一个提案的 param_value 来自 Optuna（value_source="optuna" 可审计）
- [ ] 无 optuna 环境时降级默认值，流程不中断
- [ ] 寻优空间严格限定在白名单参数 + 反思层指定方向内（构造越界测试用例验证被拒绝）

---

### PROP-20260809-003 ｜ 做梦部四象限概率接入 Regime 信息

**问题描述（代码证据）**

做梦部（弗洛伊德层）四象限情景预言的概率分布是静态写死的：

| 行号 | 象限 | 固定概率 |
|:---|:---|:---|
| L365 | optimistic（突破阻力） | 0.15 |
| L366 | neutral（区间震荡） | 0.35 |
| L367 | pessimistic（趋势反转） | 0.30 |
| L368 | ignored（假突破急反转等） | 0.20 |

四象限概率本应反映**当前市场状态**，静态值导致做梦部在任何 regime 下做同样的情景加权——牛市顶部与熊市底部的"被忽视情景"权重完全一样。

**修复方案**

1. 接入市态（regime）信息：读取 A 系列 regime 分类结果（memory_l4 已有 a0a9_bridge/ab_bridge 等桥接先例；`12-三屏趋势系统/ml/regime_param_optimization.py` 提供 regime 参数化先例）
2. 建立 regime → 四象限概率的映射表（初始值由现有静态值按 regime 语义微调，例如：
   - 强趋势上行：optimistic↑ neutral↓ ignored↑（防踏空主升浪）
   - 高波动转折：pessimistic↑ ignored↑（防假突破急反转）
   - 区间震荡：维持现有 15/35/30/20 近似值）
3. regime 不可得时降级为现有静态值（`prob_source: "regime" | "static_fallback"`）
4. 映射表作为**配置文件**而非硬编码（便于后续进化调整），初始版本须人工审定

**影响面**: `self_evolution_engine.py` L360-375 四象限生成段 + 新增 regime 读取封装 + 新增映射配置文件。

**风险与对策**
- ⚠️ regime 误判传导至情景加权 → 对策：概率调整幅度设上下限（单象限 ±0.10 以内），且映射表初始值保守
- ⚠️ A 系列 regime 数据时效性（cron 停摆时无新鲜 regime）→ 对策：regime 数据超过 48h 视为过期，降级静态值

**回滚方案**: `git revert` 单 commit + 删除映射配置文件；降级路径保证回滚后行为与现状完全一致。

**验收标准**
- [ ] 有 regime 输入时四象限概率随 regime 变化（至少 2 种 regime 的映射值不同）
- [ ] regime 缺失/过期时降级静态值，数值与现状完全一致
- [ ] 概率四象限和恒为 1.0（含浮点容差断言）

---

## 三、实施顺序与依赖

```
PROP-001（真实回测门禁）── 先行，为后续提供安全阀
    ↓
PROP-002（Optuna 数据驱动值）── 依赖 PROP-001 门禁兜底
    ↓
PROP-003（regime 四象限）── 独立，可与 PROP-002 并行
```

批准后按 D-Z-E 三链执行（Z1 扫描 → Z3 路径 → E1 执行 → E2 独立上下文验证 → E3 交付），每链门禁照常。

## 四、合规声明

- ✅ 不触碰 V9 基线（8%×vol_mult 加仓间隔 / 4%×vol_mult 止盈 / 最多 3 次加仓）
- ✅ 不触碰危险参数（仓位上限、杠杆永不自动进化 — 白名单机制保持）
- ✅ config 固化仍限 4 个进化键；constraints/releases 快照 + constraint_rollback.py 回滚链路不变
- ✅ 三个提案均为 R2，禁止 G3 自动落地（宪法 H009）

## 五、审批流转

| 步骤 | 状态 |
|:---|:---|
| 1. 提案文档创建 | ✅ 本文档 |
| 2. 人工审批（用户确认） | ✅ **已批准** — 用户 2026-08-09 01:30 UTC 回复"1，全部批准"（001+002+003，按依赖顺序走 D-Z-E 三链实施） |
| 3. D-Z-E 三链实施 | ▶️ 进行中 |
| 4. E2 独立验证 + 交付 | ⬜ |

> 备注：本机当前 Feishu 审批模板/治理 Base 对新 App（cli_aa95b2...）不可访问（91402 NOTEXIST），审批以本飞书会话人工确认为准，批准记录归档于本文档 §五。

---
*提案生成: 云涯Hermes ｜ 证据验证时间: 2026-08-09 01:15 UTC（全部行号经代码精读核实）*
