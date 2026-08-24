# 策略算法层 v1.4.1 — 阶段1（最小影子模式）实施 Spec

> **版本**：sal-stage1-v1.4.1（本 spec 版本：v1.0.0）
> **对应上游文档**：[孙子五维度评估 §一/§4.2/§11-§16](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/docs/superpowers/specs/2026-08-21-sunzi-five-domains-evaluation.md) / [策略层改造方案 v1.4.1 §十](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/docs/superpowers/specs/2026-08-21-strategy-layer-refactor-plan.md)
> **本阶段核心原则 = 零侵入实盘决策**：所有新增代码只读现有状态做计算 → 写 shadow_logger 结构化日志 → **不修改任何 ExitStrategy 开/平仓、RiskManager 仓位、ParameterMapper 注入的现有行为**；全部 2 总开关 + 7 子开关 + 3 模式开关默认 = False；冷启动时只启用 `enable_five_domain_shadow_mode=True` 做记录。
> **在线学习（§十六）本阶段不落地**：只在 FiveDomainState / StrategySelection dataclass 中预留结构化字段 `DecisionAuditRecord` 供阶段2离线预训练消费，不引入任何 β-Bandit / CUSUM 代码。阶段2触发条件见五维度评估 §16.3。

---

## 一、阶段1架构与组件清单（设计第一节，已用户确认）

### 1.1 新增 2 个独立文件（混合式：独立文件便于单测，内嵌式调用便于 polling_trader 集成）

| 落位：`11-易经推理系统/scripts/memory_l4/` | 核心职责 | 依赖边界（绝不直接 import polling_trader 实例属性，通过参数传值） | 典型输出 |
|---|---|---|---|
| **`five_domain_scorer.py`** | 启发式五维打分（仅复用系统已有指标，零新增指标 I/O）+ 决策不等式映射（war_state/mask/cap/band/position_mult/forced_close 六决策）+ 日级缓存快照到 `five_domain_state.json`。**只做离线/日级打分，不在 5min 热路径重算**。 | 只依赖：① MorphCyclePredictor.phase（天/地 proxy 输入参数）② `trade_record` 表胜率/`exit_strategy_log` 强平次数（将维度，输入参数）③ symbol_mapper.asset_class（分类 key，输入参数）④ yfinance IXIC/XAU 日线（美股/黄金 proxy，函数内部封装，caller 只传 data） | `FiveDomainState` dataclass（9 字段按类 Dict：war_state/mask/band/cap/mult/close_flags/scores/veto_flags） |
| **`strategy_algo_layer.py`** | 纯校准算法层（v1.4.1 核心：G6 Seed 表 + 统一二次校准公式 + FRONT_BAND_RULES 带宽映射）。**严格纯函数：无任何 I/O、无全局状态、无系统调用**。 | 只依赖：five_scores[cls] / regime_summary / liquidity_tier 纯值输入参数。零依赖 polling_trader / shadow_logger / DB。 | `StrategySelection` dataclass（strategy_type / style_exposures / calibration_biases / front_layer_band + 审计字段） |

### 1.2 polling_trader.py 仅 3 处增量插入（每处 ≤ 15 行，0 改动原逻辑分支）

> fail-open 保证：如果任何一处插入代码抛异常 → `try/except Exception: pass` + `shadow_logger.warn` → 原链路 100% 不受影响。

| 插入位置（行号引用相对当前版本） | 动作（仅 shadow 记录，不下决策） | 唯一开关门控（除全局 `enable_five_domain_shadow_mode` 外） |
|---|---|---|
| `PollingTrader.run_once` 末尾，L7818 `add_log("轮询#%d完成" % self._round)` 之后 | 每 5min 读取 `five_domain_state.json` 日级快照 → 遍历 open_positions：`asset_cls = resolve_asset_class(pos.symbol)` → 调用 `StrategyAlgorithmLayer.select(asset_class=cls, five_scores=state.scores[cls], ...)` 生成 shadow 版本 Selection → 写 ShadowLogger schema `five_domain_decision`：12 字段（war_state[cls] / mask[cls] / cap[cls] / scores[cls] / band[cls] / calibration_biases × 8 / strategy_type / version）。 | `enable_five_domain_shadow_mode=True` 时记录（默认 False，但阶段 1 冷启动唯一 = True）；其余子开关仅影响 Selection 内的值，不触发真实决策。 |
| `PollingTrader._open_position` 头部，L7040 `def _open_position(...)` 之后，RiskManager 之前 | 预读取 `five_domain_state.war_state.get(asset_cls, "ALLOW")` → 如果是 FREEZE / COOLDOWN → 仅写 shadow 日志 "被战略层拦截（仅记录，真实拦截动作受控于 enable_five_domain_war_state）"。**阶段 1 默认 `enable_five_domain_war_state=False` → 这里永远不会真正跳过开仓，100% 维持原 RiskManager 链路**。开关语义：`enable_five_domain_war_state=False` = 写 shadow 但 0 动作；`enable_five_domain_war_state=True` = 写 shadow **且**如果 war_state≠ALLOW 则 `return None` 跳过开仓。阶段 2 晋升 AB 通过后才考虑将此开关切换为 True。 | `enable_five_domain_war_state_shadow=True` 时写日志（默认 False；阶段 1 建议打开便于统计拦截命中率反事实分析）；`enable_five_domain_war_state` 默认为 False → 100% 不拦截原链路。 |
| `ParameterMapper.export_params` 末尾（6 行 clip 辅助函数） | **仅当 `enable_five_domain_front_layer_band=True` 时执行**：`L_final = np.clip(L_raw, band.L_min, band.L_max)`；同理 T_effective、sector_weights × 2 各执行一次。**默认 False → clip 函数 0 行执行，L/T/板块权重完全保持前置层自洽输出**。开启时同时写 shadow 日志 "L_raw=X, band=[A,B]，被 clip 次数=N"，用于阶段 2 评估带宽对前置层参数的实际收紧频率。 | `enable_five_domain_front_layer_band`（默认 False，阶段 1 保持关闭，仅在专项影子实验时手动打开）。 |

---

## 二、数据链路 / 指标映射 / 决策不等式 / 15 项 TDD（设计第二节，已用户确认）

### 2.1 启发式五维评分的唯一归一化公式（禁止多口径换算漂移）

> **经验 734151 教训 #2 落地**：每个维度评分的输出公式在代码中只有一个函数 `_normalize_0_100(raw_proxy, scale=100.0)`。全维度共享，禁止不同维度写各自的 int(round(x)) 变体。shadow 日志同时记录 `raw_proxy` 和 `final_score`，便于事后审计。
```python
# five_domain_scorer.py — 全局唯一归一化函数（TDD 必测单调性+边界截断正确）
def _normalize_0_100(raw_proxy: float, scale: float = 100.0) -> int:
    """全五维共享唯一归一化函数：raw_proxy 期望范围 [-1,1] / [0,1] → scale 映射后 clip(0,100) → int round
    单调性保证：raw_proxy 大则 final 一定大；边界：任何异常值不会突破 0-100"""
    assert isinstance(raw_proxy, (int, float)), f"raw_proxy 必须数值：{type(raw_proxy)}"
    return int(np.clip(round(raw_proxy * scale), 0, 100))
```

| 维度（按类 cls） | §4.2 原设计输入 | 阶段 1 启发式映射（只用系统已有产出数据，零新增指标 I/O） |
|---|---|---|
| **道 dao（方向一致性）** | 政策 + 机构资金一致性 | crypto_usdt：`regime_summary.trend_strength ∈ [-1,1]` → `_normalize_0_100(ts, 100.0)`；us_stock：IXIC/GSPC SMA20 vs SMA50 → `_normalize_0_100( (SMA20/SMA50 - 1.0) * 20, 100)`（多头 5% 偏离时=100，空头反之）；precious_metal：XAU/USD RSI14 / 2 → `_normalize_0_100(RSI14/100, 100)` |
| **天 tian（季节性/周期）** | 宏观季节性 + 日历效应 | 三类共用：MorphCyclePredictor 4y phase → {Bull:90, Recovery:70, EarlyBear:35, Bear:10, LateBear:40, Rebound:60} → `_normalize_0_100( phase_score / 100, 100)`；叠加春节前 14 天 / 圣诞节前 14 天各 -10 分 → `_normalize_0_100( (base-10)/100, 100 )` |
| **地 di（市场结构）** | MA 位置 + 横盘天数 + 阻力支撑 | 三类取各自基准资产相对长均线位置分位：crypto → BTC/USDT `(close - MA200_low) / (MA200_high - MA200_low)` 分位 × 100；美股 → IXIC 同口径 MA200；黄金 → XAU/USD 相对 MA128；再叠加横盘天数（`realized_vol_60d < threshold` 且 `max-min < range_thr` 连续 > 20 天扣 20 分）。 |
| **将 jiang（决策质量/纪律）** | 近 30 笔胜率 + 审计分（exit_strategy_log） | 【按类 cls 独立计算胜率】70% 权重 = `trade_record` 表近 30 笔（该类）win_rate × 100；30% 权重 = `exit_strategy_log` 近 7 天（该类）触发 EvForceCloseStrategy 次数 × 5 分 / 次（最多扣 30）。 |
| **法 fa（策略库/执行规则）** | 策略库丰富度 + 执行一致性 | 阶段 1 启发式中性固定 70 分（§4.2 表中"中性"档位）：`_normalize_0_100(0.70, 100)`。**等阶段 2/3 策略库执行一致性实际数据落地后替换，不改归一化函数**。 |

### 2.2 五计加权 → 六决策映射（全部写成可代入的不等式，便于 shadow 审计）

> **经验 734151 教训 #1 落地**：每个判断条件都写成"可代入不等式"。shadow 日志强制记录 3 字段：`threshold=X`、`input_value=Y`、`final_result=ALLOW/FREEZE/...`。用户问"为什么 crypto FREEZE？"直接从日志抄："total_crypto=52 < 阈值 60（因为 dao=38<40 veto）"——50 字以内，审计秒答。
```python
# five_domain_scorer.py:FiveDomainHeuristicScorer._apply_decision_rules()
# 唯一决策入口，按类 cls 完全独立（三类互不影响，TDD 必测串值不存在）
def _weighted_total(self, scores_cls: Dict[str,int], cls: str) -> int:
    w = self.WEIGHTS_BY_CLASS[cls]  # crypto:{dao:0.30, tian:0.15, di:0.25, jiang:0.15, fa:0.15}
    assert abs(sum(w.values()) - 1.00) < 1e-6, f"[{cls}] 权重和≠1：{w}"
    return int(round(sum(scores_cls[k] * w[k] for k in w.keys())))

def _apply_decision_rules(self, scores_by_cls: Dict[str,Dict]) -> FiveDomainState:
    state = FiveDomainState.default_fail_open()  # 先中性，再覆写（保证 fail-open）
    for cls in ("crypto_usdt", "us_stock", "precious_metal"):
        s = scores_by_cls.get(cls, {"dao":50,"tian":50,"di":50,"jiang":50,"fa":70})
        total = self._weighted_total(s, cls)
        veto = state.dimension_veto_flags[cls] = {
            "dao_xiao_40":     s["dao"]   < 40,
            "jiang_xiao_40":   s["jiang"] < 40,
            "fa_xiao_40":      s["fa"]    < 40,
            "di_tian_shuang_cha": (s["di"] < 40 and s["tian"] < 40),
            "dao_jv_fou_jue":  s["dao"]   < 40,
        }
        # === 不等式1：war_state（§5.2 不出战 + 5分滞回解冻）===
        prev_ws = self._last_state.war_state.get(cls, "ALLOW")
        if prev_ws in ("FREEZE","COOLDOWN") and total < 65:               state.war_state[cls] = "COOLDOWN"
        elif (total < 60) or veto["dao_jv_fou_jue"]:                      state.war_state[cls] = "FREEZE"
        else:                                                             state.war_state[cls] = "ALLOW"
        # === 不等式2：aggregate_position_cap_pct（§5.2 四档）===
        if   total >= 85: state.aggregate_position_cap_pct[cls] = 1.00
        elif total >= 75: state.aggregate_position_cap_pct[cls] = 0.80
        elif total >= 60: state.aggregate_position_cap_pct[cls] = 0.50
        else:             state.aggregate_position_cap_pct[cls] = 0.20
        # === 不等式3：allowed_style_mask（§四策略库调用规则）===
        m = state.allowed_style_mask[cls]
        m["emergency"]     = True  # 应急策略永不下架（R7 架构红线）
        m["trend_follow"]  = (total >= 70 and not veto["di_tian_shuang_cha"])
        m["breakout"]      = (total >= 65 and s["di"] >= 60)
        m["mean_revert"]   = (40 <= s["di"] <= 60)
        m["momentum"]      = (s["dao"] >= 70)
        m["volatility"]    = veto["di_tian_shuang_cha"]
        # === 不等式4：position_mult（维度否决仓位压限）===
        if veto["dao_xiao_40"] or veto["jiang_xiao_40"]: state.position_mult[cls] = 0.30
        elif veto["fa_xiao_40"]:                         state.position_mult[cls] = 0.50
        else:                                            state.position_mult[cls] = 1.00
        # === 不等式5：forced_close_flags（维度否决的强平/保护模式）===
        fc = state.forced_close_flags[cls]
        fc["strong"]  = veto["fa_xiao_40"]   # 法<40 纪律崩溃→强平候选（阶段1仅记录）
        fc["protect"] = total < 50            # 总过低→SL收紧保护模式（阶段1仅记录）
        # === 6决策之6：front_layer_band（§15.5.3 FRONT_BAND_RULES 查表映射）===
        state.front_layer_band[cls] = StrategyAlgorithmLayer._compute_front_layer_band(s, total)
        state.five_scores[cls] = s
    # === 跨类相关性乘数（§5.3，三类都低则×0.8）===
    low_count = sum(1 for c in ("crypto_usdt","us_stock","precious_metal") if self._weighted_total(scores_by_cls.get(c, {}), c) < 60)
    mult_cross = (0.8 if low_count >= 2 else 1.0)
    for cls in state.cross_asset_multiplier:
        state.cross_asset_multiplier[cls] = mult_cross
    return state
```

### 2.3 15 项 TDD 测试矩阵（test_strategy_algo_stage1.py，TDD 原则 M1 先写全部失败）

| 编号 | 测试名 | 覆盖点（失败场景设计） |
|---|---|---|
| 1 | `test_default_strategy_selection_fail_open_byte_equivalent` | calibration_biases 全 1.0 / front_band None / strategy_exposures 中性 / version="salv1.4.1" → 字节等价 `StrategySelection()` 默认值（§15.4.1 fail-open） |
| 2 | `test_selector_disable_switch_returns_default` | `cfg.enable_strategy_layer=False` → select() 返回等价默认（§13 模块化总开关关断） |
| 3 | `test_dataclass_schema_completeness` | 所有必填字段（含 DecisionAuditRecord 预留字段）能序列化 / 反序列化，不出现 AttributeError |
| 4 | `test_front_band_clip_fully_closed_forbids_change` | crypto 带宽 `L_min=0.75, L_max=0.75`（闭）→ 任意 L_raw 必 clip 到 0.75 |
| 5 | `test_front_band_clip_half_open_preserves_inband` | T_band=[0.50, 0.80] + T_raw=0.65 → 输出 0.65（带内值 100% 保留，不被修改） |
| 6 | `test_front_band_clip_fully_open_no_op` | band=None → clip 函数 0 行执行，输出 = raw 全相等 |
| 7 | `test_front_band_clip_out_of_upper_bound_gets_clipped` | sector_weights_raw=1.35 + band max=1.20 → clip 到 1.20 |
| 8 | `test_front_band_clip_out_of_lower_bound_gets_clipped` | L_raw=0.30 + band min=0.40 → clip 到 0.40 |
| 9 | `test_independence_crypto_freezes_us_stock_unaffected` | crypto war_state=FREEZE（dao=38<40）+ 美股 dao=85,total=88 → 美股 war_state=ALLOW / mask.emergency=True / breakout=True / cap=1.0（互不污染） |
| 10 | `test_independence_mask_no_cross_contamination` | 仅 crypto `mask.emergency=True, 其余5=False`；美股 / 黄金 mask 必须全 True（§1 按类独立） |
| 11 | `test_independence_band_per_class` | crypto band=[0.5,0.9]，黄金 band=None → 读取错位（cls_黄金读 front_layer_band[crypto]）必须 FAIL（TDD先测读错位=错误，再修代码） |
| 12 | `test_cross_asset_2_low_multiplies_by_08_only_classes` | crypto + 美股 total<60（low=2）→ cross_asset_multiplier[crypto/us_stock/贵金属] = 全部 ×0.8 |
| 13 | `test_five_domain_master_switch_off_byte_equivalent` | `enable_five_domain=False` → 所有 9 字段 = 中性默认值 = `FiveDomainState.default_fail_open()` 全等 |
| 14 | `test_strategy_layer_master_switch_off_byte_equivalent` | `enable_strategy_layer=False` → Selection = `StrategySelection()` 全等 |
| 15 | `test_front_band_switch_off_skips_clip` | `enable_five_domain_front_layer_band=False` → ParameterMapper.clip 执行 0 次（mock counter=0），L/T/板块权重完全 raw |

---

## 三、开关架构 / 阶段1里程碑 / 文件清单（设计第三节，已用户确认）

### 3.1 2 总 + 7 子 + 3 模式 开关接入表（默认全部=False，fail-open）

> 接入位置：`PollingTrader.__init__` 中，与 `enable_mode_switch / enable_ev_radar / enable_multi_horizon / enable_ranked_tp` 同级。命名保持 `enable_*` 既有惯例。
```python
# polling_trader.py PollingTrader.__init__ 开关区（与现有开关并列，约L482-L678插入）
# ===== 战略层 & 策略算法层：2总+7子+3模式，默认全部=False =====
self.enable_five_domain: bool                  = False  # ★ 战略层总开关：False→五计9字段全中性
self.enable_strategy_layer: bool               = False  # ★ 策略算法层总开关：False→Selection 全 1.0 默认
# 7子开关（可独立关断，§12.2）
self.enable_five_domain_war_state: bool        = False  # war_state 真实拦截（阶段1=False，仅做shadow统计）
self.enable_five_domain_style_mask: bool       = False  # allowed_style_mask 真实过滤（阶段1=False）
self.enable_five_domain_position_cap: bool     = False  # aggregate_position_cap_pct 真实叠加min约束
self.enable_five_domain_cross_asset: bool      = False  # cross_asset_multiplier 跨类×0.8生效
self.enable_five_domain_dimensio: bool         = False  # dimension_veto 真实触发仓位/强平
self.enable_five_domain_front_layer_band: bool = False  # ★ 前置层带宽clip生效（默认不clip）
self.enable_five_domain_ol: bool               = False  # §十六在线学习：阶段1必然=False，阶段2才启用
# 3模式开关（§12.3影子AB/降级）
self.enable_five_domain_shadow_mode: bool      = False  # ★ 冷启动唯一=True：只写shadow_log，不做真实决策
self.enable_shadow_ab_static_baseline_v15: bool = False # V15静态基线（阶段2晋升评估）
self.enable_shadow_ab_dynamic_baseline: bool   = False  # 当前最优动态基线（阶段2晋升评估）
```

| 开关 | 默认 | 关断 = fail-open 行为（字节等价该功能不存在） |
|---|---|---|
| enable_five_domain（总） | False | `FiveDomainState.default_fail_open()` 返回 |
| enable_strategy_layer（总） | False | `StrategySelection()` 默认值返回 |
| 7 子开关 × 独立关断 | 全 False | 对应字段强制 = 中性值（§15.4.1 汇总表），其余字段不受影响 |
| enable_five_domain_shadow_mode | False | ShadowLogger 不写 `five_domain_decision` 日志条目 |
| AB 双基线 × 2 | 全 False | AB 对比对象不初始化，不额外跑决策 |

### 3.2 阶段1里程碑 M1-M5（合计约 13 工作日）

| 里程碑 | 交付物 | 验收标准（不达标不进入下一个） |
|---|---|---|
| **M1（3天）TDD Red基座** | `tests/test_strategy_algo_stage1.py` 15 项测试先写失败；3 个核心 dataclass（FiveDomainState / StrategySelection / DecisionAuditRecord）定义 + `_normalize_0_100()` 空壳占位 | `pytest tests/test_strategy_algo_stage1.py -q` **15项全部红（FAIL/ERROR）**，不是跳过。 |
| **M2（4天）绿：纯函数实现** | `five_domain_scorer.py` 启发式打分 + 决策不等式实现；`strategy_algo_layer.py` 纯校准算法（G6表+统一校准+FRONT_BAND_RULES）；`FiveDomainHeuristicScorer` 单测覆盖 100% 分支 | 15 项 TDD **全部绿（PASS）**；`py_compile 5个文件` 无语法错误；单测独立跑（不依赖 polling_trader 实例）。 |
| **M3（3天）插入点集成** | run_once / _open_position / ParameterMapper.export_params 3 处插入 ≤ 15+15+6 行增量；ShadowLogger 新增 `five_domain_decision` schema（12字段）；新增 polling_trader 开关 12 个属性初始化。 | 冷启动实盘进程 **2小时内无崩溃**；每5分钟shadow日志完整写入12字段，枚举值不出现 NaN/null。 |
| **M4（2天）核心回归无破坏** | `84项核心 + 13项资金调控 + 4项递归修复 + 15项新增 = 116项全绿`；验证 fail-open：所有开关=False 时，对比改造前 2 轮轮询的关键字段（direction/confidence/size/sl/tp）**逐字节相等**。 | 116 项测试 100% 通过；改造前后对照日志比对 = 字节等价 diff = 0 行。 |
| **M5（1天）实盘影子冷启动验证** | 实盘进程启动：`--interval 300s --enable-shadow-mode`（其他开关默认 False）；观察 2 轮 10 分钟。 | ① 不产生任何新的开平仓动作（与改造前行为一致）；② shadow_log 每轮5分钟≈写入9类字段；③ 内存/CPU无异常增长。 |
| **阶段1完成** | 3个月影子数据积累期（≥60条/类决策-奖励配对） | 生成《离线反事实评估报告v0.1》→ 决定是否启动阶段2。 |

### 3.3 全部文件清单（3新 + 2改 + 1新增测试 = 6 个文件）

| 文件 | 操作 | 行数估算 | 职责 |
|---|---|---|---|
| `scripts/memory_l4/five_domain_scorer.py` | **NEW** | ~260行 | FiveDomainHeuristicScorer 唯一归一化函数 + 打分指标映射 + 决策不等式 + five_domain_state.json 快照 I/O |
| `scripts/memory_l4/strategy_algo_layer.py` | **NEW** | ~220行 | StrategyAlgorithmLayer（纯函数无I/O）+ G6_SEED_TABLE + 统一二次校准公式 + FRONT_BAND_RULES 带宽表 + select() 接口（v1.4.1，含asset_class参数） |
| `scripts/memory_l4/tests/test_strategy_algo_stage1.py` | **NEW** | ~450行 | 15项TDD（§2.3 矩阵）+ 额外单测：归一化单调性、权重和=1断言、开关关断字节等价、按类独立性、band clip场景 |
| `scripts/memory_l4/polling_trader.py` | **MODIFY 3处** | ~75行净增 | 12个enable_*开关初始化；run_once末尾影子快照调用；_open_position头部war_state shadow日志；ParameterMapper.export_params末尾6行band clip（默认关断不执行） |
| `scripts/memory_l4/shadow_logger.py`（或polling_trader内的ShadowLogger封装） | **MODIFY schema** | ~40行净增 | 新增five_domain_decision schema 12字段；新增写入接口；保证与现有shadow记录的向后兼容（白名单过滤未识别字段） |
| `five_domain_state.json`（落位：system_state/ 同级缓存目录） | **RUNTIME 自动生成** | ~2KB/天 | FiveDomainState 日级快照持久化；冷启动缺失时自动从 `default_fail_open()` 初始化，不阻塞轮询。 |
| **合计** | | **~1045行，测试≈43%** | 净业务代码≈595行，纯测试≈450行 |

---

## 四、架构红线合规检查（自证本 spec 不违反已确认的 18 条约束）

| 红线来源 | 要求 | 本 spec 如何满足 |
|---|---|---|
| **R1（策略层改造方案 §四架构红线）** | ExitContext 新字段必须 Optional[...] = None，避免历史仓位兼容性问题 | 阶段1不改 ExitContext/TradeRecord 现有字段；StrategySelection 是内存中临时对象，仅绑定开仓时写入 TradeRecord.strategy_source（该字段已存在 §已验证事实），新字段 calibration_biases 写入 enhance_info（Dict 字段天然兼容缺失键）。 |
| **R2** | strategy_type 必须在开仓时一次性绑定，持仓期间不可变；需附带 strategy_version | StrategyAlgorithmLayer.select() 返回的 StrategySelection.strategy_type / strategy_version="salv1.4.1" 仅在 `_open_position` 成功后写入 TradeRecord，持仓期间不重算；持仓期间 ExitManager 重新获取 Selection 时从 TradeRecord.enhance_info 反序列化，不重新调用 select()。 |
| **R3** | 仓位 / SL / TP 阈值叠加取更严格的 min（不是取大） | 叠加公式：`final_cap = min( RiskManager.risk_cap, CapitalControl.max_position_usdt, PostLayer.sizing_cap, five_domain.aggregate_position_cap_pct[cls] × cross_mult[cls] )`（min 单调性保证，新增约束只会更严不会放松，符合 §13.2 修正1代码）。 |
| **R4** | RankedTpStrategy 仅允许 breakout 策略参与，不在 ExitManager 主链注册，独立循环处理 | allowed_style_mask.breakout 未通过时，RankedTp 不启动（但阶段1 mask 全True，不影响现有 RankedTp 行为）。 |
| **R5** | audit_score（战略层输出）× 离场校准系数 ≤ 1.0（防止放宽阈值） | 统一校准公式：`calibration_bias_raw = clip(seed × regime_factor × liquidity_factor, 0.30, 2.00)`，其中 [0.30, 2.00] 只是**物理截断防止极端值**；随后落地**硬门限**：`calibration_bias_final = calibration_bias_raw if (enable_strategy_layer_relax_allowed is True or calibration_bias_raw <= 1.0) else 1.0`，即：子开关 `enable_strategy_layer_relax_allowed` 默认 **False**（本 spec 阶段 1 不启用）→ 任何 >1.0 的"放宽阈值"方向值都会被强制写回 1.0，保证改造前后离场阈值不被放宽，只有"收紧方向"<1.0 的校准实际生效，零破坏安全底线。 |
| **R6** | 高波动 G4 regime → 所有仓位 × 0.5 | G4 高波动已内聚到 `regime_summary.liquidity_tier = G4` → 统一校准公式的 liquidity_factor = 0.50（G6 对照表 v1.4.1 Seed）；且 liquidity_factor × 0.5 < 1.0 → 走 R5 收紧方向自动生效，不需额外门。 |
| **R7** | 应急策略 emergency 永不下架（allowed_style_mask.emergency = True） | _apply_decision_rules 中 `m["emergency"] = True` 强制赋值，无任何条件分支可将其改为 False。 |
| **§11.2 周期-职责矩阵** | 战略层：日级；前置层：中周期；策略层：5min 轮询对齐持仓；核心层：5min信号 | five_domain_scorer：日级快照写入 JSON（热路径只读）；StrategyAlgorithmLayer.select：5min 调用；前置层 ParameterMapper：5min 调用；核心层：5min 推理。严格对齐。 |
| **§12.1 fail-open（F1）** | 异常/关断 = 字节等价原链路 = 中性值返回 | 所有函数开头：`if not enabled: return DEFAULT_VALUE_OBJECT`；所有插入点 `try/except Exception: shadow_logger.warn + pass`；FiveDomainState.default_fail_open() / StrategySelection() 默认值 = 中性值。 |
| **§15.4 方案B（弹性闸门不乘系数）** | 战略层只输出 min/max 带宽（front_layer_band），前置层末尾 np.clip，不修改内部公式 | strategy_algo_layer._compute_front_layer_band 返回 L_min/max × T_min/max × sector_min/max 的 6 个带宽数；ParameterMapper.export_params 末尾 6 行 clip，不修改 L/T 计算公式，关闭时0行执行。 |
| **§15.5.2 按类独立性** | 三类资产的 6 决策完全独立（加密FREEZE不影响美股） | `for cls in 三类:` 独立循环，cls 间无共享变量；按类独立性的 4 项 TDD（#9-#12）显式检测串值问题。 |
| **§16 在线学习不影响阶段1** | 阶段1启发式硬规则 + 结构化预留字段，不落地OL | enable_five_domain_ol 默认 False；仅在 StrategySelection 中声明 `audit: Optional[DecisionAuditRecord] = None` 预留字段，不做任何更新。阶段2再单独落 adpative_gate.py。 |
| **GitHub G1** | EMA 平滑 style_exposures 权重避免频繁切换 | StrategyAlgorithmLayer.select() 内 `style_exposures = EMA(last=0.8, new=0.2, span=10)` 平滑存储到 `last_style_exposures_state.json`。 |
| **GitHub G3** | regime-based position sizing（G4×0.5） | 统一校准公式 × liquidity_factor（G4=0.50）。 |
| **GitHub G6** | 维度否决仓位 cap（道/将<40→≤30%） | position_mult=0.30，`final_cap = min(..., position_mult)`。 |
| **GitHub G10** | 每周日离线算"道"维度，不阻塞5min热路径 | five_domain_scorer 的 dao/jiang/fa 三个维度日级只跑一次（可在每周日 02:00 cron 重算），热路径只读 five_domain_state.json 快照。 |
| **F2（双基线晋升）** | 版本晋升必须通过 AB 双基线（V15 静态 + 当前最优动态）才允许 promote | 3 模式开关：`enable_shadow_ab_static_baseline_v15 + enable_shadow_ab_dynamic_baseline`，本阶段1 不启用（默认False），阶段2晋升评估时启用。 |
| **F3（影子强→promote流程）** | 首版本必须强制走 shadow→promote，初始化动态基线 | enable_five_domain_shadow_mode=True（阶段1唯一=True），跑3个月影子→阶段2双基线评估→promote。 |

---

## 五、阶段2/3（§十六在线学习）的触发门槛和代码隔离

> **本 spec 范围只到阶段1 M5 完成**。这里明确阶段2/3的 **准入门槛** 和 **代码隔离边界**，避免scope creep。全部在线学习代码放 `adaptive_gate.py`（与五个现有文件完全独立，阶段1甚至不需要创建这个空文件占位）。

| 阶段 | 准入门槛（全部满足才允许进入代码编写阶段） | 代码边界 |
|---|---|---|
| **阶段2 TS Beta Bandit + CUSUM** | ① 每类≥60日decision-reward配对；② 离线模拟显示Beta方案与启发式决策重合度≥75%；③ FREEZE场景下累计 reward 比启发式高出≥15%（且95% CI不含0）；④ M4核心回归仍100%通过 | 新增 `adaptive_gate.py`（~220行，纯numpy/scipy，0新依赖）。修改 strategy_algo_layer 的 arm 映射表增加 ol_arm_id 字段。不修改其他4个现有文件。 |
| **阶段3 Contextual BootstrappedTS + HMM** | ① 阶段2 Doubly-Robust 离线评估（OffsetTree）显示加入context比纯Bandit累计reward提升≥5%且95% CI不含0；② 至少500条/类离线样本（≥9个月累计）；③ AB 影子跑 1 个月无崩溃；④ 核心 116 项测试 + 阶段2新增 ≈130项全通过 | 新增 `contextualbandits` 纯Python版 + `hmmlearn` 两个依赖。修改 `adaptive_gate.py` 包装 BootstrappedTS + HMM特征工程。其他4个现有文件不修改（保持隔离）。 |

---

*本 spec = 阶段1（最小影子模式）的完整实施蓝本，不含阶段2/3实际代码实现。任何对本 spec 的变更，必须同时通过「架构红线合规检查表（§四）」的自证一致性。*
