# 策略层插入改造方案

> **文档状态**：方案设计，不改代码
> **创建日期**：2026-08-21
> **关联文档**：[孙子五维度评估](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/docs/superpowers/specs/2026-08-21-sunzi-five-domains-evaluation.md) §4.10–§4.13
> **改造路径**：先 A（轻量改造）后 B（完整改造，仅限组合级，不做单笔级 36 子链）
> **修订记录**：
> - 2026-08-21 v1.0：初稿，定义路径 A（约 215 行）与路径 B（约 240 行）。
> - 2026-08-21 v1.1：根据《孙子五维度评估》§4.11–§4.13 全面校正。核心变更：
>   - **架构冲突校正（7 条红线 R1–R7）**：ExitContext 全 Optional（R1）、一次性绑定+版本（R2）、约束取更严格（R3）、RankedTp 独立循环+§4.13.3 breakout 默认保留对照表（R4）、持仓恢复兼容（R5）、将维度改为 audit_score 审计分（R6）、G4 高波动 regime 总仓×0.5 硬约束（R7）。
>   - **传统金融建议落地（7+1 条）**：R6 将维度审计分（#0）+ 风格权重向量（#1）+ 风险预算 ATR sizing + ZeroDivision 保护（#2）+ 归因一等公民（#3）+ 不出战滞回+冷却（#4）+ 回测强制滑点/手续费/相关性摩擦（#5）+ LiquidityTier × StrategyType 矩阵（#6）+ 路径 B 仅组合级反 36 子链（#7）。
>   - **GitHub 经验 G1–G10 完整落地**：RegimeSense G1-G3、regime-aware-portfolio G4/G5/G9、IssacWong0103 G6/G7、wolf-of-vibe-street G8、§4.12.3#7 G10 红线，10 项全部有对应实施步骤 + 代码落位。
>   - 路径 A 改动量从 v1.0 215 行调升至 v1.1 ~675 行；路径 B 从 240 行升至 ~300 行；路径 A 测试从 21 项增补至 28 项（净增 7 项：R6 边界 2 + R7 触发 3 + sizing 安全 1 + breakout 对照 1）。
> - 2026-08-21 v1.2：与《孙子五维度评估》§11–§13 架构深化对齐，补充模块化开关与影子 AB 接入。核心变更：
>   - **新增开关架构（2 总 + 7 子 + 3 模式）**：战略层总开关 `enable_five_domain` + 4 子开关（war_state / position_cap / style_mask / cross_asset）；策略层总开关 `enable_strategy_layer` + 3 子开关（exit_config / style_exposures / risk_budget_sizing）；3 模式开关（影子 AB / 自动晋升 / Dream OS 外部接管）。默认全关，冷启动 100% 等价改造前。
>   - **新增 4 层降级回退链路（CLI → env → 配置热加载 → 单组件 fail-open）** + **5 场景关断矩阵验证**（冷启动全关 / 只开战略 / 只开策略 / 全关+影子 / 全开子开关组合）。
>   - **兼容性审查结论**：v1.1 R1–R7 / G1–G10 与开关架构**100% 兼容**（开关是外层 gating 超集，不修改内层规则逻辑）。仅需补充 4 处代码级 gate 接入点（§九.3）。
>   - **与现有开关机制风格一致**：复用 polling_trader.py L534 既有 `enable_*` 模式、`_enable_inject_runtime` 300s 热加载、ShadowLogger 影子记录、CBR/A7/P3 fail-open 设计。
>   - **为 Dream OS 调度预留统一接口**：统一配置文件 / 结构化观测指标输出 / NodeRegistry 标准执行单元 / 双基线晋升可配置。
> - 2026-08-21 v1.3：与《孙子五维度评估》**§十四 策略算法层定位评估**对齐，**从「参数路由表模式（v1.2）」升级为「纯参数校准算法层（方案 B，推荐）」**。核心变更：
>   - **策略层输出结构性重写（核心升级 ★）**：删除 v1.2 `exit_config` 每策略独立参数表（6×10+ 字段 + 布尔开关 + ExitStrategy 三级 fallback），替换为**统一结构 `calibration_biases`（8 数值乘法系数 + 1 布尔 gate）**。每个 ExitStrategy 只维护一套 `BASE_THRESHOLDS`（核心深度研发资产），最终生效阈值 = `base × calibration_biases.xxx_factor`，**无查表分支，所有策略类型共享同一个计算公式**。
>   - **符合 6 大行业范式（Turtle + CTA + RegimeSense + QuantPulse + 风险平价 + MarketRegimeNet）**：统一基准规则 × 统一校准算法，差异化来自策略标签/regime/五计分这些算法的**输入特征**，不是独立参数路由表——复杂度从 O(策略×Exit×参数) 360+ 组合 → O(Exit + 校准算法) 线性可扩展，离场研发与策略数彻底解耦（用户核心目标）。
>   - **G6 对照表语义变更**：从「核心参数路由表」降级为「6 组校准 Seed 初始偏置」，算法层基于 regime/五计分/流动性做**统一公式的二次校准**；`timeout_factor=0` 作为 gate 跳过 Timeout（等价 v1.2 `timeout_skip:True`，数值表达可渐变）。
>   - **新增战略层向下校准前置层（用户新增点）**：战略层输出 `front_layer_calibration: {L_factor, T_factor, sector_factor}`，默认全 1.0，fail-open，只能乘法且 ±30%/20% 封顶，独立子开关 `enable_five_domain_front_layer_calibration` 管理，严格单向依赖不破坏前置层纯自洽。
>   - **v1.2 R1–R7 / G1–G10 100% 复用**：校准偏置 Optional None=1.0 天然满足 R1 兼容；R3 min 单调性、R4 RankedTp 独立循环、R6 audit_score、R7 高波动 cap 全部不变；G1–G3 权重向量 / EMA、G2 风险预算 sizing、G5 归因、G7 Chandelier、G9 聚类全部复用，G6 只改语义不改字段结构。
>   - **开关架构扩展**：战略层子开关从 4 → 5（新增 §十四 F4 `enable_five_domain_front_layer_calibration`）。其他 2 总 + 6 策略层子 + 3 模式 完全复用。
>   - **路径改动量**：v1.3 路径 A ~800 行（v1.2 ~795 行基础上，删除 exit_config 查表 + 三级 fallback 代码 ~100 行，替换为校准偏置计算 + 统一阈值乘法 ~105 行，净增 ~5 行）；路径 B 仍 ~300 行；路径 A 测试从 34 项 → **38 项**（净增 4 项：校准偏置 × seed → 阈值正确 2 + 战略层→前置层乘法校准 F1-F4 边界 1 + timeout_factor=0 gate 等价 timeout_skip 1）。
>   - **v1.2 方案标记为「备选 A：参数路由表模式」，不推荐；v1.3 方案 B（纯校准算法层）为默认推荐落地方案。**
> - 2026-08-21 v1.4：与《孙子五维度评估》**§十五 大-中-小周期关系校正**对齐，**将战略层→前置层的交互从「精确乘法校准（v1.3 §10.1 front_layer_calibration，方案 A，不推荐）」升级为「弹性约束闸门 + 偏差带宽 clip」（方案 B，默认推荐）**。核心变更：
>   - **解决用户新提出的「大周期-中周期-小周期弹性约束」定位**：战略层（大周期）不应该精确乘系数修改前置层（中周期）形态学公式内部的 L/T 参数，而应该充当三件事闸门：① `war_state` veto「不开战」、② `front_layer_band` 偏差带宽（L/T/板块权重允许的 min/max 范围）、③ `allowed_style_mask` 策略族白名单。前置层完全自洽计算 L/T，只在最后做 np.clip(...) 限制在带宽内，不被乘系数修改。
>   - **对齐 6 大行业分层范式**：桥水 Dalio PMPT Beta/Alpha 严格分离、国泰海通 SAA/TAA ±5-15% 偏差带宽治理、AQR Style Premia 因子比例区间不修改内部公式、QuantKernel v6.2 RegimeGate 只切 watchlist 不改 Donchian 参数、RegimeAwareML 只做 strategy gating 不改 backtest 公式、人大层次化双层决策 clip 不乘系数——6/6 证据支持弹性约束，反对精确乘法校准。
>   - **消除信号打架和时间粒度错位**：战略层「道」维度是周级离线批处理，前置层 L/T 是 5min 热路径在线更新——用一周更新一次的静态系数乘 5min 变化的动态参数语义错位；带宽方案完全解决：前置层算出的 L=0.85 在战略层给的 [0.40, 0.90] 带宽内 → 原样保留，只有跑出极端值才 clip，避免结论矛盾。
>   - **最小改动零 breaking-change**：删除 v1.3 `front_layer_calibration`（三乘法系数），替换为 v1.4 `front_layer_band`（6 个 min/max 范围，Optional=None 时等价无约束），前置层 ParameterMapper 末尾仅加 ~6 行 np.clip 逻辑；实现代码量反而从 ~30 行乘法降到 ~6 行 clip。
>   - **开关架构语义升级**：战略层子开关 5 从 `enable_five_domain_front_layer_calibration` 重命名为 `enable_five_domain_front_layer_band`，默认 False（冷启动保守），关断时 band=None → clip 操作完全不做，字节等价无影响。其他所有开关（2 总 + 6 策略层子 + 3 模式）100% 保持不变。
>   - **路径改动量**：v1.4 路径 A **~776 行**（v1.3 ~800 行基础上，删除 front_layer_calibration 乘法逻辑 ~24 行，替换为 front_layer_band clip 逻辑 ~6 行，净减 ~18 行）；路径 B 仍 ~300 行；路径 A 测试从 v1.3 38 项 → **39 项**（净增 1 项：front_layer_band 与 L/T/板块权重 clip 边界验证，覆盖带宽全闭/半开/全开/越界/不越界 5 场景）。
>   - **v1.3 方案 A（精确乘法校准 front_layer_calibration）标记为「历史备选」保留于文档，不作为默认落地方案。**
> - 2026-08-21 **v1.4.1（架构一致性补丁）**：与《孙子五维度评估》**§一（6 个核心问题按类独立）+ §5.3（三类不出战互相独立）+ §15.4.1（战略层完整输出结构按类 Dict）** 对齐，**将战略层所有 gate/带宽/评分的输入输出从全局值升级为按三类资产（crypto_usdt / us_stock / precious_metal）独立的 Dict 结构**。单笔 StrategySelection（持仓绑定、一次性不可变，R2 红线）本身维持原有字段不变，但上游所有消费点（开仓前 gate / 策略选择 / 校准算法 / 仓位 cap）都必须按 `position.asset_class` 从战略层 Dict 中**取对应类别的独立值**做约束。不修改策略层 v1.4 已有的 ExitStrategy 单级乘法逻辑，仅对数据流和 selector 接口做增量修正。核心增量：
>   - **StrategyAlgorithmLayer.select() 签名新增 asset_class 参数**，上游调用方 polling_trader._open_position 必须先 `asset_cls = self._resolve_asset_class(symbol)`；校准算法的庙算总分缩放使用 `scores_cls = five_scores[asset_cls]`（不是全局 scores）。
>   - **FRONT_BAND_RULES 返回的带宽按类取**：加密「道≥80」→ crypto_usdt.band = [0.55, 0.98]，美股/黄金各自独立判断，带宽互不影响。
>   - **6 个核心问题映射落地的按类语义**：`war_state[cls]` → 是否允许交易/空仓（cls=crypto/us_stock/precious_metal 独立）；`allowed_style_mask[cls]` → 允许哪类策略；`aggregate_position_cap_pct[cls] × cross_asset_multiplier[cls]` → 允许多大仓位；`forced_close_flags[cls]` → 是否必须止损；`position_mult[cls]` → 是否需要降仓——**加密 FREEZE 完全不阻止美股开仓，美股高分牛市不推高黄金的仓位 cap**。
>   - **R3 红线 min 语义保持不变**：`min(aggregate_cap[cls] × cross_mult[cls], RiskManager 原有上限, CapitalControl 通用调控上限, 后置层 sl/tp sizing)`，只是把全局 cap 替换为按类 cap，单调性成立。
>   - **Fail-open 机制保持不变**：战略层开关关断时，所有按类字段自动取 ALLOW/True/1.0/None/50 中性值，字节等价「战略层不存在」，100% 不影响策略层和离场层原有逻辑。
>   - **路径改动量**：v1.4.1 路径 A **~792 行**（v1.4 基础上净增 ~16 行：select 新增 asset_cls 参数；新增 resolve_asset_class 辅助；按类取值替换全局值）；路径 A 测试从 39 项 → **41 项**（净增 2 项：三类资产 gate 独立互不干扰 1；aggregate_cap 按类取 min 约束正确 1）。

---

## 一、现有代码结构盘点

### 1.1 涉改文件清单

| 文件 | 角色 | 关键类/方法 |
|---|---|---|
| `bcrm2/exit_manager.py` | 离场框架 | `ExitContext` / `ExitDecision` / `ExitManager.evaluate()` |
| `bcrm2/exit_strategies.py` | 离场策略 | `P3EarlyExitStrategy` / `SignalReverseStrategy` / `EvForceCloseStrategy` / `TimeoutProfitSwitchStrategy` / `RankedTpStrategy`(**已实现但不在链上**) / `EvAdjustStrategy` |
| `trading_utils.py` | 持仓记录 | `TradeRecord` (L26) / `PositionTracker.open_position()` (L1043) / `_load_open_positions()` 字段白名单 (L1015) |
| `polling_trader.py` | 交易主流程 | `_open_position()` (L7085) / `exit_manager.evaluate()` 调用 (L5990) / ExitManager 初始化 (L602) / **`_handle_ranked_tp_top1` 独立循环 (L4002, L8129)** |

### 1.2 现有数据流（**实际代码校正版**）

> ⚠️ **架构冲突评估校正点（§4.11.4 / 五维度评估文档 L777-L784）**：ExitManager 实盘注册链只有 5 个策略，`RankedTpStrategy` 并不在链上，而是由 `_handle_ranked_tp_top1` 做跨持仓独立循环处理。后续改造一律不得假设 RankedTp 走 ExitStrategy 链。

```
核心层 → direction + confidence + hexagram
    ↓
后置层 RangingMarketEnhancer.enhance()  [polling_trader.py L6824]
    → enhance_result 写入 inference["enhance_result"]
    ↓
_open_position()  [polling_trader.py L7085]
    → 读取 enhance_result 中的 sl_atr_mult / tp_atr_mult
    → 多层仓位调整（v4风控 + P2动态 + 形态乘数 + 资金调控硬上限）
    → 计算 SL/TP/仓位
    → position_tracker.open_position(... enhance_info=inference.get("enhance_result") ...)
    ↓
持仓中 exit_manager.evaluate()  [polling_trader.py L5990]
    → 构造 ExitContext（当前无 strategy_type）
    → 5 策略链式评估（P3→SignalRev→EvFC→Timeout→EvAdj，**不区分策略类型**）
    → force_close / adjust / hold / pass
    ↓
跨持仓循环 _handle_ranked_tp_top1  [polling_trader.py L8129]
    → enable_ranked_tp 开关 gate
    → 计算 gap 排名，触发 A/B/C 档排名止盈
    → **与 ExitManager 互相独立，不经过 ExitStrategy.evaluate()**
```

### 1.3 关键代码位置

| 位置 | 说明 |
|---|---|
| `exit_manager.py` L24-42 | `ExitContext` 数据结构（当前无 strategy_type / style_exposures / strategy_version） |
| `exit_manager.py` L102-134 | `ExitManager.evaluate()` 签名（当前无 strategy_type / exit_config 参数） |
| `exit_strategies.py` L85-157 | `SignalReverseStrategy` — base_threshold=0.7, 无策略类型分支 |
| `exit_strategies.py` L167-214 | `EvForceCloseStrategy` — force_below=-0.35, 无策略类型分支 |
| `exit_strategies.py` L223-301 | `TimeoutProfitSwitchStrategy` — timeout_hours=29, 无策略类型分支 |
| `exit_strategies.py` L380-432 | `EvAdjustStrategy` — warn_lower=-0.35/warn_upper=-0.10/strong_above=0.30, 无策略类型分支 |
| `trading_utils.py` L26-56 | `TradeRecord` 已有 `strategy_source: str=""` 与 `enhance_info: Dict={}`，**暂不强制新增 schema 字段**（路径 A 先写 enhance_info，避免触发历史仓位兼容问题） |
| `trading_utils.py` L1043-1084 | `PositionTracker.open_position()` 签名 |
| `trading_utils.py` L1009-1020 | `_load_open_positions()` 字段白名单恢复机制（天然兼容缺省值） |
| `polling_trader.py` L602-615 | ExitManager 初始化（5 策略注册，**不含 RankedTpStrategy**） |
| `polling_trader.py` L5990-6002 | `exit_manager.evaluate()` 调用 |
| `polling_trader.py` L7430-7446 | `position_tracker.open_position()` 调用 |
| `polling_trader.py` L4002-4150 | `_handle_ranked_tp_top1` RankedTp 独立循环入口 |
| `polling_trader.py` L1752-1777 | `_save_exit_strategy_decision` 贡献值落表（当前缺 `strategy_type`/`regime_label`/`five_score_snapshot`） |
| `polling_trader.py` L7085-7126 | `_open_position` 资金调控约束叠加点 |

### 1.4 架构红线（来自架构冲突评估 §4.11 + 传统金融 §4.12.2，必须遵守）

| 编号 | 红线内容 | 对应校正点 |
|---|---|---|
| R1 | ExitContext 新增字段必须全部带 `Optional[...] = None` 默认值，**统一放 ExitContext dataclass 里声明**，不在各策略 evaluate() 签名里零散加参数，避免签名漂移 | §4.11.2 |
| R2 | `strategy_type` 必须是**开仓时刻一次性绑定**写进持仓元数据；持仓期间允许同一 strategy_type 内调阈值，**不得切换 strategy_type**，否则规则跳变；同步写 `strategy_version` 标记 | §4.11.6 |
| R3 | 策略层覆盖一律取**更严格者**：仓位 `min()`、SL `min()`；**禁止覆盖风控输出的日损上限 / 单票风险预算**。"庙算高分放大风控阈值"是反模式 | §4.11.5 |
| R4 | RankedTp 保持为**跨持仓独立循环**（暂不并入 ExitManager），策略层只在 `_handle_ranked_tp_top1` 入口按 strategy_type 做开关 gate，不重构 gap 计算。**默认规则（依据 §4.13.3 对照表）**：trend_follow / volatility / emergency 默认不参与（让利润跑 / 现金优先）；breakout / mean_revert / momentum 保留参与 | §4.11.4 + §4.13.3 |
| R5 | 持仓恢复兼容性：路径 A 不新增 TradeRecord 强类型字段，统一写 `enhance_info`；路径 B 再考虑强类型升级，升级时继续保留 `_load_open_positions` 白名单过滤机制 | §4.11.3 |
| R6 | **「将」维度改为 audit_score（系统行为审计分）**（§4.12.2 可行性评级 B-）：**不在打分层显式放「智信仁勇严」**，而是量化为 3 项硬指标归一：① 实际仓位越界次数、② 超时未平次数、③ 异常退出（非策略触发）次数。避免「将」维度主观化 | §4.12.2 |
| R7 | **G4 高波动 regime 总仓 ×0.5 硬约束**（regime-aware-portfolio-risk-engine 经验）：当后置层 regime ∈ {CHOPPY, RANGE_TIGHT} 且 ATR(14) 分位数 ≥ 80（高波动）时，允许总仓位上限（即 CapitalControl 输出后）再乘 0.5；此约束与 strategy 覆盖取 min 一样，只能收紧不能放宽 | §4.13.2 + §4.13.5 G4 |

---

## 二、路径 A：轻量改造（推荐先做）

### 改造原则（**已融合架构评估+金融建议+GitHub G1-G10**）

1. **向后兼容优先（R1）**：ExitContext 所有新增字段 `Optional[...] = None`；`strategy_type=None/""` 时行为完全等价现有逻辑。
2. **权重向量替代单选（G1/G2/G3）**：StrategySelection 新增 `style_exposures: Dict[str, float]`，把单笔持仓拆成若干风格暴露（`trend_follow`/`breakout`/`mean_revert`/`momentum`/`volatility`/`emergency`），在组合层做 aggregate exposure cap；`strategy_type` 仅表示"主风格"用于路由，权重和为 1.0。
3. **风险预算 sizing（§4.12.3 #2，Turtle/AHL 范式）**：StrategySelection 输出 `risk_budget_pct`（单笔风险预算占权益 %，0.25–2%），`_open_position` 用 `size = risk_budget_usdt / (ATR × sl_mult)` 反算，替代"默认仓位 × 分数倍数"的不稳健方式。
4. **一次性绑定 + 版本号（R2）**：`enhance_info` 同时写入 `strategy_type`/`style_exposures`/`exit_config`/`strategy_version`，持仓期间**不得切换 strategy_type**（允许同 type 内调参数，不允许路由跳变）。
5. **约束单调性（R3）**：仓位 `min(size_after_risk, strategy.size_after_budget, capital_control.hard_cap)`；SL `min(sl_mult_after_enhance, strategy.sl_mult)`；TP 对趋势策略允许放宽（`max(old, strategy.tp_mult)`，或 `None` 表示不封顶由 Chandelier Exit 管），对非趋势策略一律取 `min`。**禁止覆盖日损上限 / 单票风险预算**。
6. **归因一等公民（§4.12.3 #3 + G5）**：`_save_exit_strategy_decision` 扩展 `strategy_type / style_exposures / regime_label / five_score_snapshot / strategy_version` 5 列，配套月度归因报表模板（按 regime 分组的策略贡献柱状图、回撤贡献饼图）。
7. **不出战滞回 + 冷却（§4.12.3 #4）**：新增轻量冷却计数器 `_war_state_need_recover_rounds=3`，总分<60 触发不出战后必须连 3 轮 ≥60 才能重新开仓（避免频繁开关、换手成本侵蚀）。
8. **不破坏独立循环（R4，依据 §4.13.3 对照表）**：RankedTp 在 `_handle_ranked_tp_top1` 入口按 strategy_type 做 allow-list gate，不进 ExitManager 链；**默认 breakout / mean_revert / momentum 允许参与，trend_follow / volatility / emergency 自动禁止**。
9. **「将」维度改为 audit_score（R6，§4.12.2 可行性评级 B-）**：五计打分的 `jiang` 维度不再用主观「智信仁勇严」，改为 `audit_score = 100 - w1*越界次数_norm - w2*超时未平次数_norm - w3*异常退出次数_norm`（w1=0.4 / w2=0.3 / w3=0.3）；越界=实际仓位 > 风控允许上限，超时未平=持仓龄 > 策略 timeout_hours × 1.5 仍未触发离场。
10. **G4 高波动 regime 总仓 ×0.5（R7）**：在 CapitalControl 下游、策略选择器上游新增 `_apply_regime_vol_cap()`，当 `(regime ∈ {CHOPPY, RANGE_TIGHT}) AND (atr_14_percentile ≥ 0.80)` 时，对 CapitalControl 返回的 `max_position_usdt` 再乘 0.5。该约束作为额外的硬 cap，与 R3 同向叠加（两次 min 等价一次，但更安全）。

### 2.1 新增模块：策略选择器

**新文件**：`bcrm2/strategy_selector.py`

```python
# -*- coding: utf-8 -*-
"""策略选择器 — 五计评分 → 主策略类型 + 风格暴露向量 + 参数覆盖（RegimeSense 风格权重向量）

输入:
  - 五计评分 (dao/tian/di/jiang/fa, 各 0~100)
  - enhance_result.regime (后置层市场状态 5 态: RANGE_TIGHT / RANGE_NARROW / TREND_STRONG / TREND_WEAK / CHOPPY)
  - direction + confidence (核心层输出)
  - liquidity_tier (可选: HIGH / MID / LOW, 默认 HIGH, 按 24h 成交额或 coin 白名单判断)

输出（已融合 G1/G2/G3 与 风险预算 sizing）:
  - strategy_type: 主风格 "trend_follow"/"breakout"/"mean_revert"/"momentum"/"volatility"/"emergency"
  - style_exposures: Dict[str, float]  风格权重向量 (RegimeSense 风格, 和为 1.0)
  - sl_mult_override: Optional[float]     # SL 倍率覆盖; None=不改变后置层
  - tp_mult_override: Optional[float]     # TP 倍率覆盖; None=趋势策略不封顶, 用 Chandelier
  - position_mult: float                  # 仓位倍率, 默认 1.0, 仅用于应急/低分场景收紧; 常规 sizing 用 risk_budget_pct
  - risk_budget_pct: float                # 单笔风险预算占权益%, 替代 position_mult 作为 sizing 主入口
  - enable_ranked_tp_allow: bool          # 是否允许参与 RankedTp 跨持仓排名 (R4)
  - liquidity_tier: str                   # 流动性分层, 供组合聚类约束用
  - exit_config: Dict                     # 离场规则覆盖 (传给 ExitStrategy)
  - strategy_version: str                 # 策略代码版本 (R2)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
import time

STRATEGY_TYPES = [
    "trend_follow",  # 趋势跟踪
    "breakout",      # 突破
    "mean_revert",   # 均值回归
    "momentum",      # 动量轮动
    "volatility",    # 波动率
    "emergency",     # 应急
]
STYLE_DIMS = STRATEGY_TYPES  # 风格维度名称与策略类型对齐, 方便计算聚合暴露
STRATEGY_VERSION = "slv1.0"  # 策略版本号, 升级后旧持仓按旧版本离场

# LiquidityTier × StrategyType 可用性矩阵（§4.12.3 #6）
# True = 该层流动性池允许该策略
LIQUIDITY_STRATEGY_ALLOWED = {
    "HIGH": {s: True for s in STRATEGY_TYPES},                                   # BTC/ETH/SPY/QQQ/GLD 等, 所有策略允许
    "MID": {**{s: True for s in STRATEGY_TYPES}, "volatility": False},            # 主流 alt / 板块 ETF: 禁波动率 (换手高)
    "LOW": {"trend_follow": True, "mean_revert": True, "momentum": True,          # 小币 / 非活跃: 仅低换手策略
           "breakout": False, "volatility": False, "emergency": False},
}

@dataclass
class StrategySelection:
    """策略选择器输出。所有 Optional 字段带 None 默认值 → R1 兼容。"""
    strategy_type: str = "trend_follow"
    style_exposures: Dict[str, float] = field(
        default_factory=lambda: {"trend_follow": 1.0, "breakout": 0.0, "mean_revert": 0.0,
                                 "momentum": 0.0, "volatility": 0.0, "emergency": 0.0})
    sl_mult_override: Optional[float] = None   # 覆盖后置层 sl_atr_mult; None = 保持后置层
    tp_mult_override: Optional[float] = None   # 覆盖后置层 tp_atr_mult; None = 趋势策略不封顶, 用 trail
    position_mult: float = 1.0                 # 额外仓位倍率 (emergency / 应急收紧用)
    risk_budget_pct: float = 1.0               # 单笔风险预算占权益 % (§4.12.3 #2, sizing 主入口)
    enable_ranked_tp_allow: bool = True        # RankedTp 允许 gate (R4)
    liquidity_tier: str = "HIGH"               # 流动性分层 (§4.12.3 #6)
    exit_config: Dict[str, Any] = field(default_factory=dict)
    strategy_version: str = STRATEGY_VERSION
    # exit_config 示例:
    # {
    #   "signal_reverse_threshold": 0.75,   # 反转阈值覆盖
    #   "ev_force_below": -0.40,            # EV 强平阈值覆盖
    #   "timeout_hours": 48.0,              # 超时小时数覆盖; None 表示跳过超时
    #   "timeout_skip": True,               # 是否跳过超时换仓
    #   "ev_warn_lower": -0.40,             # EV 收紧阈值覆盖
    #   "ev_strong_above": 0.35,            # EV 放宽阈值覆盖
    #   "use_chandelier_exit": True,        # 趋势策略是否启用 3x ATR Chandelier Exit (G7)
    #   "chandelier_atr_mult": 3.0,         # Chandelier ATR 倍数
    # }

class StrategySelector:
    """五计评分 + regime → 策略选择 + 风格权重向量。

    路由逻辑设计要点:
    - 使用 EMA 平滑权重向量 (G3), 避免每 5 分钟跳变
    - 不做 0/1 硬路由, 用权重向量表达"此笔交易更偏向哪种风格"
    - liquidity_tier 检查通过 LIQUIDITY_STRATEGY_ALLOWED 矩阵过滤
    """

    def __init__(self, ema_alpha: float = 0.15):
        self._prev_exposures: Dict[str, float] = {s: 1.0/len(STYLE_DIMS) for s in STYLE_DIMS}
        self._ema_alpha = ema_alpha

    # ── 对外主方法 ────────────────────────────────────────────────────
    def select(
        self,
        scores: Dict[str, float],   # {"dao": 80, "tian": 65, "di": 75, "jiang": 85, "fa": 80}
        enhance_result: Optional[Dict] = None,
        direction: str = "",
        confidence: float = 0.0,
        liquidity_tier: str = "HIGH",
    ) -> StrategySelection:
        """
        选择逻辑（优先级从高到低, 输出主风格 + 平滑权重向量, 过滤流动性禁止策略）:
          1. 庙算总分 < 60 或 道 < 40 → emergency 主风格 + 权重
          2. 道高(≥70) + 地高(≥70) + regime=TREND_* → trend_follow
          3. 地压缩 regime=RANGE_TIGHT / RANGE_NARROW → breakout
          4. 道中(40-70) + regime=RANGE_NARROW/CHOPPY → mean_revert
          5. 道中(≥50) + 板块轮动/排名信号 → momentum
          6. 波动率 regime 切换 → volatility
          7. 默认 → trend_follow
        """
        dao = float(scores.get("dao", 50) or 0)
        tian = float(scores.get("tian", 50) or 0)
        di = float(scores.get("di", 50) or 0)
        jiang = float(scores.get("jiang", 50) or 0)
        fa = float(scores.get("fa", 50) or 0)
        total = dao*0.30 + tian*0.15 + di*0.25 + jiang*0.15 + fa*0.15

        regime = (enhance_result or {}).get("regime", "CHOPPY") or "CHOPPY"
        # G2: 五态 regime → 四态 baseline 权重（与 RegimeSense 对齐）
        base = self._regime_to_base_weights(regime)

        # 1. 应急/不出战
        if total < 60 or dao < 40:
            raw = self._emergency_weights(di, tian)
            sel = self._build_selection("emergency", raw, liquidity_tier, total, emergency=True)
            self._smooth_exposures(sel.style_exposures)
            return sel

        # 2~6. 按规则偏向主风格, 并把权重按 0.7/0.3 比例叠加到 regime baseline 上
        if dao >= 70 and di >= 70 and regime.startswith("TREND"):
            main = "trend_follow"
        elif regime in ("RANGE_TIGHT", "RANGE_NARROW"):
            main = "breakout"
        elif 40 <= dao < 70 and regime in ("RANGE_NARROW", "CHOPPY", "TREND_WEAK"):
            main = "mean_revert"
        elif dao >= 50 and confidence >= 0.65:
            main = "momentum"
        elif self._is_volatility_shift(enhance_result):
            main = "volatility"
        else:
            main = "trend_follow"

        # 主风格 70% + regime 基线 30% (G1 混合, 非单选)
        raw = {s: 0.30 * base.get(s, 0.0) for s in STYLE_DIMS}
        raw[main] = raw.get(main, 0.0) + 0.70

        sel = self._build_selection(main, raw, liquidity_tier, total, emergency=False)
        self._smooth_exposures(sel.style_exposures)
        return sel

    # ── 内部构建辅助 ──────────────────────────────────────────────────
    def _regime_to_base_weights(self, regime: str) -> Dict[str, float]:
        """G2: 易经后置层 5 态 → RegimeSense 风格基线权重矩阵（baseline v1）"""
        if regime == "TREND_STRONG":
            return {"trend_follow": 0.75, "breakout": 0.10, "mean_revert": 0.0,
                    "momentum": 0.10, "volatility": 0.05, "emergency": 0.0}
        if regime == "TREND_WEAK":
            return {"trend_follow": 0.45, "breakout": 0.15, "mean_revert": 0.10,
                    "momentum": 0.20, "volatility": 0.10, "emergency": 0.0}
        if regime == "RANGE_TIGHT":
            return {"trend_follow": 0.05, "breakout": 0.65, "mean_revert": 0.15,
                    "momentum": 0.05, "volatility": 0.10, "emergency": 0.0}
        if regime == "RANGE_NARROW":
            return {"trend_follow": 0.05, "breakout": 0.35, "mean_revert": 0.45,
                    "momentum": 0.05, "volatility": 0.10, "emergency": 0.0}
        # CHOPPY (默认)
        return {"trend_follow": 0.20, "breakout": 0.10, "mean_revert": 0.35,
                "momentum": 0.20, "volatility": 0.15, "emergency": 0.0}

    def _emergency_weights(self, di: float, tian: float) -> Dict[str, float]:
        """总分 < 60 时进入 emergency: 主要权重放 emergency, 配少量现金等价(=不交易) + 微量趋势 + 均值回归"""
        return {"trend_follow": 0.10, "breakout": 0.0, "mean_revert": 0.10,
                "momentum": 0.0, "volatility": 0.0, "emergency": 0.80}

    def _build_selection(self, main: str, raw_weights: Dict[str, float],
                         liquidity_tier: str, total_score: float,
                         emergency: bool = False) -> StrategySelection:
        """从主风格+原始权重, 构造 StrategySelection（含流动性过滤、归一化、退出参数、风险预算）"""
        # 流动性允许矩阵（§4.12.3 #6）
        allowed = LIQUIDITY_STRATEGY_ALLOWED.get(liquidity_tier, LIQUIDITY_STRATEGY_ALLOWED["MID"])
        for s in STYLE_DIMS:
            if not allowed.get(s, False):
                raw_weights[s] = 0.0
        # 归一化
        s_sum = sum(raw_weights.values())
        if s_sum <= 0:
            raw_weights = {"trend_follow": 1.0} if allowed.get("trend_follow") else {"mean_revert": 1.0}
            s_sum = 1.0
        exposures = {s: raw_weights.get(s, 0.0)/s_sum for s in STYLE_DIMS}

        # 主风格覆盖: 如果 main 被 liquidity tier 禁止, 回退为权重最大的那一项
        if not allowed.get(main, False):
            main = max(exposures.items(), key=lambda kv: kv[1])[0]

        # §4.13.3 参数表 (G6): 按 strategy_type 的 exit_config 默认值
        params = self._default_exit_params(main)
        sl_override = params.pop("sl_mult_override", None)
        tp_override = params.pop("tp_mult_override", None)
        pos_mult = params.pop("position_mult", 1.0)
        risk_budget = params.pop("risk_budget_pct", 1.0)
        enable_rtp = params.pop("enable_ranked_tp_allow", True)

        # 庙算总分对 risk_budget 做线性缩放 (0.25% ~ 2%, 传统 Kelly 半凯区间 §4.12.3 #2)
        score_scale = max(0.25, min(2.0, (total_score/100.0) * 2.5))
        risk_budget = max(0.25, min(2.0, risk_budget * score_scale))
        if emergency:
            risk_budget = min(risk_budget, 0.4)  # 应急期 ≤ 0.4% / 笔

        return StrategySelection(
            strategy_type=main,
            style_exposures=exposures,
            sl_mult_override=sl_override,
            tp_mult_override=tp_override,
            position_mult=pos_mult,
            risk_budget_pct=risk_budget,
            enable_ranked_tp_allow=enable_rtp,
            liquidity_tier=liquidity_tier,
            exit_config=params,
        )

    def _default_exit_params(self, main: str) -> Dict[str, Any]:
        """§4.13.3 6 类策略退出参数对照表（G6）——路径 A 核心落地表
        + G7: 趋势跟踪启用 3×ATR Chandelier Exit
        """
        if main == "trend_follow":
            return {
                "sl_mult_override": 2.5, "tp_mult_override": None,  # TP 不封顶, 用 trail
                "position_mult": 1.0, "risk_budget_pct": 1.2,
                "enable_ranked_tp_allow": False,  # R4: 趋势跟踪不参与排名止盈, 让利润奔跑
                "signal_reverse_threshold": 0.70, "ev_force_below": -0.40,
                "timeout_skip": True,  # 趋势不超时换仓
                "ev_strong_above": 0.35,
                "use_chandelier_exit": True, "chandelier_atr_mult": 3.0,  # G7
            }
        if main == "breakout":
            return {
                "sl_mult_override": 1.5, "tp_mult_override": 3.0,
                "position_mult": 0.85, "risk_budget_pct": 1.0,
                "enable_ranked_tp_allow": True,
                "signal_reverse_threshold": 0.55, "ev_force_below": -0.30,
                "timeout_hours": 29.0,
            }
        if main == "mean_revert":
            return {
                "sl_mult_override": 2.0, "tp_mult_override": 2.0,
                "position_mult": 0.65, "risk_budget_pct": 0.6,
                "enable_ranked_tp_allow": True,
                "signal_reverse_threshold": 0.55, "ev_force_below": -0.25,
                "timeout_hours": 14.0,  # §4.13.3 缩短至 14h
            }
        if main == "momentum":
            return {
                "sl_mult_override": 2.0, "tp_mult_override": 4.0,
                "position_mult": 0.85, "risk_budget_pct": 1.0,
                "enable_ranked_tp_allow": True,  # 排名优先换仓
                "signal_reverse_threshold": 0.65, "ev_force_below": -0.30,
                "timeout_hours": 22.0,
            }
        if main == "volatility":
            return {
                "sl_mult_override": 2.0, "tp_mult_override": 3.5,
                "position_mult": 0.70, "risk_budget_pct": 0.8,
                "enable_ranked_tp_allow": False,
                "signal_reverse_threshold": 0.60, "ev_force_below": -0.40,
                "timeout_hours": 22.0,
            }
        # emergency
        return {
            "sl_mult_override": 1.0, "tp_mult_override": 1.5,
            "position_mult": 0.30, "risk_budget_pct": 0.4,
            "enable_ranked_tp_allow": False,
            "signal_reverse_threshold": 0.50, "ev_force_below": -0.20,
            "timeout_hours": 7.0,
            "ev_warn_lower": -0.20, "ev_warn_upper": -0.05, "ev_strong_above": 0.20,
        }

    def _smooth_exposures(self, exposures: Dict[str, float]) -> None:
        """G3: EMA 权重平滑 (α≈0.15), 写回 exposures; 同时更新 _prev_exposures。"""
        for s in STYLE_DIMS:
            new_v = exposures.get(s, 0.0)
            prev_v = self._prev_exposures.get(s, new_v)
            smoothed = self._ema_alpha * new_v + (1.0 - self._ema_alpha) * prev_v
            exposures[s] = round(smoothed, 4)
        self._prev_exposures = dict(exposures)

    def _is_volatility_shift(self, enhance_result: Optional[Dict]) -> bool:
        """波动率 regime 是否发生切换（TODO: 接入 enhance_result 的 ATR 分位）"""
        return False
```

### 2.2 改造 ExitContext（严格遵守 R1）

**文件**：`bcrm2/exit_manager.py`

```python
# ExitContext 新增字段 (L24-42) — 全部 Optional + None 默认值, 确保所有调用点无需改造即通过 (R1)
@dataclass
class ExitContext:
    """传入各 ExitStrategy 的上下文快照。"""
    # ... 现有字段保持不变 ...
    coin: str
    inference: Dict[str, Any]
    pos_info: Dict[str, Any]
    tracker_pos: Any
    in_protection: bool
    age_hours: float
    ev: Optional[float] = None
    multi_horizon: Optional[Dict[str, Any]] = None
    confidence: float = 0.0
    all_inferences: Optional[Dict[str, Any]] = None
    held_coins: Optional[Any] = None
    effective_threshold: Optional[float] = None
    # ↓ 新增（全部 Optional + 默认值，R1） ↓
    strategy_type: Optional[str] = None       # 主策略类型 ("trend_follow"/...)
    style_exposures: Optional[Dict[str, float]] = None  # 风格权重向量 (G1)
    exit_config: Optional[Dict[str, Any]] = None        # 策略特定离场覆盖
    strategy_version: Optional[str] = None   # 策略代码版本号 (R2)
    regime_label: Optional[str] = None       # 后置层 regime 标签 (供归因用)
    five_score_snapshot: Optional[Dict[str, float]] = None  # 五计分快照 (供归因用, 可选)
```

### 2.3 改造 ExitManager.evaluate()

**文件**：`bcrm2/exit_manager.py`

```python
# evaluate() 方法新增 strategy_type / style_exposures / exit_config /
# strategy_version / regime_label / five_score_snapshot 参数 (L102-134)
# —— 全部默认 None → 保持签名向前兼容, 旧调用点零改动能编译 (R1)
def evaluate(
    self,
    coin: str,
    inference: Dict[str, Any],
    pos_info: Dict[str, Any],
    tracker_pos: Any,
    in_protection: bool,
    age_hours: float,
    strategy_type: Optional[str] = None,        # 新增 (R1)
    style_exposures: Optional[Dict[str, float]] = None,  # 新增 (G1)
    exit_config: Optional[Dict[str, Any]] = None,        # 新增
    strategy_version: Optional[str] = None,     # 新增 (R2)
    regime_label: Optional[str] = None,         # 新增 (归因)
    five_score_snapshot: Optional[Dict[str, float]] = None,  # 新增 (归因)
    **kwargs: Any,
) -> ExitDecision:
    ctx = ExitContext(
        # ... 现有字段不变 ...
        coin=coin,
        inference=inference,
        pos_info=pos_info,
        tracker_pos=tracker_pos,
        in_protection=in_protection,
        age_hours=age_hours,
        ev=kwargs.get("ev"),
        multi_horizon=kwargs.get("multi_horizon"),
        confidence=kwargs.get("confidence", 0.0),
        all_inferences=kwargs.get("all_inferences"),
        held_coins=kwargs.get("held_coins"),
        effective_threshold=kwargs.get("effective_threshold"),
        # ↓ 新增 ↓
        strategy_type=strategy_type,
        style_exposures=style_exposures,
        exit_config=exit_config,
        strategy_version=strategy_version,
        regime_label=regime_label,
        five_score_snapshot=five_score_snapshot,
    )
    # 后续策略链逻辑保持不变 (与原方案一致)
    for strategy in self._strategies:
        if not strategy.enabled:
            continue
        decision = strategy.evaluate(ctx)
        if decision.action != "pass":
            decision.strategy_name = strategy.name
            return decision
    return ExitDecision.pass_()
```

### 2.4 改造各 ExitStrategy

**文件**：`bcrm2/exit_strategies.py`

原则：策略内部读取 `ctx.exit_config`（优先）→ 其次按 `ctx.strategy_type` 默认分支（§4.13.3 对照表） → 再其次使用构造参数（完全等价现有逻辑）。三级 fallback 保证 R1 向后兼容。

#### 2.4.1 SignalReverseStrategy（L85-157）

```python
class SignalReverseStrategy(ExitStrategy):
    name = "signal_reverse"
    priority = 20

    def __init__(
        self,
        base_threshold: float = 0.7,
        protected_conf_boost: float = 0.12,
        protected_min_threshold: float = 0.85,
        exit_confirm_required: int = 2,
    ):
        self.base_threshold = base_threshold
        self.protected_conf_boost = protected_conf_boost
        self.protected_min_threshold = protected_min_threshold
        self.exit_confirm_required = exit_confirm_required
        self._confirm_counts: Dict[str, int] = {}

    def _reverse_threshold(self, in_protection: bool,
                           effective_threshold: Optional[float] = None,
                           strategy_type: Optional[str] = None,
                           exit_config: Optional[Dict] = None) -> float:
        """三级 fallback: exit_config → strategy_type 默认 → base_threshold (等价现有)"""
        base = effective_threshold if effective_threshold is not None else self.base_threshold

        if exit_config and "signal_reverse_threshold" in exit_config:
            base = exit_config["signal_reverse_threshold"]
        elif strategy_type == "trend_follow":
            base = max(base, 0.70)          # §4.13.3 对照表
        elif strategy_type == "mean_revert" or strategy_type == "breakout":
            base = min(base, 0.55)
        elif strategy_type == "emergency":
            base = min(base, 0.50)
        elif strategy_type == "momentum":
            base = max(base, 0.65)
        elif strategy_type == "volatility":
            base = min(base, 0.60)  # 与 0.60 取更紧(更小)

        if not in_protection:
            return base
        return max(base + self.protected_conf_boost, self.protected_min_threshold)

    def evaluate(self, ctx: ExitContext) -> ExitDecision:
        pos_side = ctx.pos_info.get("pos_side", "")
        direction = ctx.inference.get("direction", "")
        confidence = float(ctx.confidence or 0.0)
        threshold = self._reverse_threshold(
            ctx.in_protection, ctx.effective_threshold,
            ctx.strategy_type, ctx.exit_config,
        )
        # ... 其余逻辑与原方案保持一致; None/s="" 分支 → base_threshold (完全等价现状)
```

#### 2.4.2 EvForceCloseStrategy / TimeoutProfitSwitchStrategy / EvAdjustStrategy

- 同上三级 fallback 模式，默认参数按 §4.13.3 对照表（§4.12 五维度评估文档 L920-L927）：
  - **EvForceClose**：trend_follow EV<−0.40，emergency EV<−0.20，mean_revert/volatility <−0.25 / <−0.40。
  - **TimeoutProfitSwitch**：trend_follow **跳过超时**；mean_revert 14h；emergency 7h；momentum 22h；breakout 29h；volatility 22h。
  - **EvAdjust**：trend_follow strong_above=0.35；emergency warn_lower=−0.20 / warn_upper=−0.05 / strong_above=0.20。
- 代码片段与原方案 §2.4.2-2.4.4 等价，只是将硬编码数字替换为 §4.13.3 对照表（即 StrategySelector._default_exit_params 的值）。此处不再重复粘贴。

#### 2.4.3 新增 `ChandelierExitStrategy`（G7，趋势跟踪用）

路径 A 可选新增（建议先在 `exit_strategies.py` 中作为**默认禁用策略**，通过 exit_config `use_chandelier_exit=True` 打开，不影响现有 5 策略链长度），代码骨架：

```python
class ChandelierExitStrategy(ExitStrategy):
    """3×ATR Chandelier Exit (G7, IssacWong0103 + CTA 行业文章)。
    仅当 strategy_type == "trend_follow" 且 exit_config.use_chandelier_exit=True 时生效。
    """
    name = "chandelier_exit"
    priority = 25  # 在 EvFC(30) 之前, SignalReverse(20) 之后

    def __init__(self, atr_mult_default: float = 3.0, enabled: bool = False):
        self.atr_mult_default = atr_mult_default
        self.enabled = enabled  # 链上默认禁用, 由 exit_config 软启用

    def evaluate(self, ctx: ExitContext) -> ExitDecision:
        if not self.enabled and not (ctx.exit_config or {}).get("use_chandelier_exit"):
            return ExitDecision.pass_()
        if ctx.strategy_type != "trend_follow":
            return ExitDecision.pass_()
        atr_mult = float(
            (ctx.exit_config or {}).get("chandelier_atr_mult", self.atr_mult_default)
        )
        # 实现: 从 inference 读取 closes / atr_series → highest_high_since_entry - atr_mult*ATR
        # → 当前 close < chandelier_stop → force_close (趋势破坏离场)
        # ... (细节实现见 G7 对应 §4.13.3 的 trend_follow 栏)
        return ExitDecision.pass_()
```

P3EarlyExitStrategy 仍保持不变（系统性 TDA+Ising 预警，与策略类型无关）。

### 2.5 持仓元数据写入（R5：路径 A 不新增强类型字段）

**文件**：`trading_utils.py`

**路径 A 不改动 TradeRecord dataclass schema**（R5：避免触发历史仓位兼容风险）。改为统一写入 `enhance_info` 字典：

- 写入 key：`strategy_type / style_exposures / exit_config / strategy_version / regime_label / five_score_snapshot / liquidity_tier`
- `strategy_source` 字段复用：原值 "bcrm" / 外部不变，区分五计策略路由不使用该槽位，避免与外部策略（马丁等）来源混淆。

`PositionTracker.open_position()` 签名在路径 A 阶段**不新增参数**。`_open_position()` 调用时把策略层输出塞进 `enhance_info`，随后 `position_tracker.open_position(..., enhance_info=enhance_info, ...)` 即完成落盘。这与现有 [polling_trader.py L33](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/docs/superpowers/specs/2026-08-21-strategy-layer-refactor-plan.md#L33) 数据流完全一致，调用点改动降到最少。

> **路径 B 后续再升级强类型**（R5）：当实盘验证无问题后，在 TradeRecord 里追加字段，并在 `_load_open_positions` 中继续保留白名单过滤——`TradeRecord.__dataclass_fields__` 自动识别新字段，旧 JSON 不会报错（因为被 filter 掉），字段默认值也保证缺省安全。

### 2.6 改造 `_open_position()`：约束叠加单调性（R3）+ 风险预算 sizing（§4.12.3 #2）

**文件**：`polling_trader.py`

在 `_open_position()` 方法中，后置层 enhance 之后、资金调控约束**之后**、仓位计算之前，依次插入 G4 高波动硬约束（R7）→ 策略选择器。

```python
def _open_position(self, inference: dict, is_reverse: bool = False, is_trial: bool = False):
    # ... 现有 L7085-7240 不变: 后置层 enhance + 资金调控 CapitalControl.allowed / max_position_usdt
    #      + RiskManager.check_risk + 日损上限 min(dynamic_limit, daily_loss_limit)
    #      + P2 动态仓位 / 形态乘数 + 做多/做空分层

    # ═══════════════════════════════════════════════════════════════
    # ★ R7 (G4): 高波动 regime 总仓 ×0.5 硬约束（新增，资金调控之后、策略层之前）
    # ═══════════════════════════════════════════════════════════════
    max_position_usdt_after_cc = max_position_usdt  # CapitalControl 返回的硬上限
    max_position_usdt = self._apply_regime_vol_cap(
        max_position_usdt_after_cc, enhance_info=enhance_info or {}, inference=inference
    )

    # ═══════════════════════════════════════════════════════════════
    # ★ 策略层：五计评分 → 策略选择（新增，G4 约束之后）
    # ═══════════════════════════════════════════════════════════════
    _scores = self._compute_five_domain_scores(inference, enhance_info)
    _sel = self._select_strategy(
        scores=_scores,
        enhance_result=enhance_info,
        direction=inference.get("direction", ""),
        confidence=float(inference.get("confidence", 0.0)),
        coin=coin,
    )

    # ── 写入 enhance_info（落盘到持仓元数据，R5 路径 A 做法） ──
    enhance_info = enhance_info or {}
    enhance_info["strategy_type"] = _sel.strategy_type
    enhance_info["style_exposures"] = _sel.style_exposures
    enhance_info["exit_config"] = _sel.exit_config
    enhance_info["strategy_version"] = _sel.strategy_version
    enhance_info["regime_label"] = enhance_info.get("regime")
    enhance_info["five_score_snapshot"] = _scores
    enhance_info["liquidity_tier"] = _sel.liquidity_tier
    inference["enhance_result"] = enhance_info

    # ── 约束叠加 R3：一律取更严格（不放大、不绕过） ──
    # SL 倍率: 取 min
    if _sel.sl_mult_override is not None:
        _old_sl = enhance_info.get("sl_atr_mult", 2.5)
        enhance_info["sl_atr_mult"] = min(_old_sl, _sel.sl_mult_override)
    # TP 倍率: 趋势策略允许 None(不封顶) → 只在非 None 时叠加; 对非趋势策略取 min
    if _sel.tp_mult_override is not None:
        _old_tp = enhance_info.get("tp_atr_mult", 5.0)
        if _sel.strategy_type == "trend_follow":
            enhance_info["tp_atr_mult"] = max(_old_tp, _sel.tp_mult_override)  # 趋势可放宽 TP
        else:
            enhance_info["tp_atr_mult"] = min(_old_tp, _sel.tp_mult_override)  # 非趋势收紧

    # 仓位 sizing: 先用风险预算反算（§4.12.3 #2）, 再与 risk/p2 之后的 size 取 min
    _atr = float(enhance_info.get("atr_14_series", [0])[-1] or 0)
    _sl_mult = float(enhance_info.get("sl_atr_mult", 2.5) or 0)
    _risked_usdt_from_budget = 0.0
    if _atr > 0 and _sl_mult > 0 and price > 0:
        _equity_est = max(float(self.account_snapshot.get("total_equity", 0) or 0), 0.0) or 0.0
        _risked_usdt_from_budget = max(0.0, _equity_est * (_sel.risk_budget_pct / 100.0))
        _stop_distance_usdt = _atr * _sl_mult                          # 1 个仓位对应的止损额度 (USDT/仓位单位)
        if _stop_distance_usdt > 0:
            _sz_from_budget = _risked_usdt_from_budget / _stop_distance_usdt
            _sz_usdt_from_budget = _sz_from_budget * price
            # R3: 与 risk/p2 之后的 size 取 min（不允许绕过风控放大仓位）
            if position_usdt > 0:
                position_usdt = min(position_usdt, _sz_usdt_from_budget)
                position_pct = min(position_pct, _sz_usdt_from_budget / max(_equity_est, 1e-9))

    # position_mult 进一步收紧（emergency 场景用）
    if _sel.position_mult != 1.0 and position_usdt > 0:
        position_usdt *= _sel.position_mult
        position_pct *= _sel.position_mult
        position_usdt = min(position_usdt, ...)  # 资金调控 hard cap 再次保留(两次 min 等价一次, 但更安全)

    # 写入 inference 供离场层读取
    inference["strategy_type"] = _sel.strategy_type
    inference["style_exposures"] = _sel.style_exposures
    inference["strategy_exit_config"] = _sel.exit_config
    inference["strategy_version"] = _sel.strategy_version

    # ... 现有 SL/TP 计算 + 下单逻辑 + position_tracker.open_position() 保持不变
    # position_tracker.open_position(... enhance_info=enhance_info ...) 即把策略信息落盘 (R5)
```

辅助方法（含 G4 高波动硬约束、**不出战滞回+冷却** §4.12.3 #4、R6 audit_score、以及 G8 "道"维度离线批量打分入口）：

```python
# 类属性: 不出战冷却计数器
# self._war_state: int = 0  # 0=正常, >0=冷却中; 每轮轮询 -1, >0 时仍然禁止开新仓
# self._war_state_need_recover_rounds: int = 3  # 连 3 轮 ≥60 才重开 (§4.12.3 #4)

def _apply_regime_vol_cap(self, max_position_usdt: float, enhance_info: dict,
                          inference: Optional[dict] = None) -> float:
    """R7 (G4): 高波动 regime 总仓 ×0.5 硬约束（只能收紧，不能放宽）。
    触发条件:
      1. regime ∈ {CHOPPY, RANGE_TIGHT}（震荡/压缩区间，最容易假突破+高换手）
      2. ATR(14) 的滚动分位数 ≥ 0.80（相对于近 252 轮/约 21 天）
    两个条件同时成立时，把 CapitalControl 返回的 max_position_usdt 再乘 0.5。
    """
    try:
        regime = (enhance_info or {}).get("regime", "") or ""
        if regime not in ("CHOPPY", "RANGE_TIGHT"):
            return max_position_usdt
        # ATR(14) 百分位: 优先读 enhance_info 中已计算的 atr_percentile_252
        atr_pct = None
        if enhance_info and "atr_percentile_252" in enhance_info:
            atr_pct = float(enhance_info["atr_percentile_252"])
        elif inference is not None:
            atr_pct = float((inference.get("technical_indicators") or {}).get("atr_percentile_252") or 0.5)
        if atr_pct is None or atr_pct < 0.80:
            return max_position_usdt
        # 触发: ×0.5 收紧
        capped = max(0.0, float(max_position_usdt or 0.0)) * 0.5
        self._log(f"[G4 高波动约束] regime={regime}, ATR分位={atr_pct:.2f} → 仓位上限 {max_position_usdt:.2f} → {capped:.2f} USTD")
        return capped
    except Exception as _e:
        self._log(f"[G4 高波动约束] 异常降级（不收紧）: {_e}", "WARN")
        return max_position_usdt  # fail-open: 异常时不额外收紧

def _select_strategy(self, scores: dict, enhance_result: Optional[dict],
                     direction: str, confidence: float,
                     coin: Optional[str] = None) -> 'StrategySelection':
    """策略选择器调用（fail-open：异常时返回默认 trend_follow + 风险预算 1%）"""
    try:
        if not hasattr(self, "_strategy_selector"):
            from scripts.memory_l4.bcrm2.strategy_selector import StrategySelector
            self._strategy_selector = StrategySelector()
        liquid = self._classify_liquidity_tier(coin)  # §4.12.3 #6
        return self._strategy_selector.select(
            scores=scores, enhance_result=enhance_result,
            direction=direction, confidence=confidence,
            liquidity_tier=liquid,
        )
    except Exception as e:
        self._log(f"[策略选择器] 异常降级为 trend_follow: {e}", "WARN")
        from scripts.memory_l4.bcrm2.strategy_selector import StrategySelection
        return StrategySelection()  # 默认 trend_follow + 全 None + 风险预算 1%

def _compute_five_domain_scores(self, inference: dict, enhance_info: Optional[dict]) -> dict:
    """构造五计评分。优先级:
    1) 离线批量周级 "道" 打分缓存 (G8: 周末 Fed/FOMC + 稳定币发行量周环比 + ETF 资金流)
    2) 在线实时评分代理 (地=regime/MA结构, 天=日内时段+季节性字典, 将=audit_score, 法=策略库命中率)
    """
    # G8: 优先读 "道" 离线路径预生成缓存 (不进热路径 LLM), 路径示例 YAML:
    #   /path/to/offline/five_domain_dao_weekly.yaml 里 per-asset dao_score
    dao_offline = self._cached_offline_dao_score(inference.get("market", "crypto"), coin=...)
    confidence = float(inference.get("confidence", 0.0))
    risk_level = inference.get("risk_level", "NORMAL")
    dao = dao_offline if dao_offline is not None else int(confidence * 100)
    regime = (enhance_info or {}).get("regime", "")
    di = {"TREND_STRONG": 85, "TREND_WEAK": 70,
          "RANGE_TIGHT": 60, "RANGE_NARROW": 55,
          "CHOPPY": 45}.get(regime, 50)
    tian = self._offline_tian_score_or_default(default=50)
    # R6 §4.12.2: 将 (jiang) 改为 audit_score = 100 - 加权惩罚
    #   越界次数 (w1=0.4) + 超时未平 (w2=0.3) + 异常退出 (w3=0.3)，滚动窗口近 7 天
    jiang = self._realtime_audit_score(default=85 if risk_level == "LOW" else 60 if risk_level == "HIGH" else 70)
    fa = self._offline_fa_score_or_default(default=70)  # 近 N 日各策略胜率加权
    return {"dao": dao, "tian": tian, "di": di, "jiang": jiang, "fa": fa}

def _classify_liquidity_tier(self, coin: Optional[str]) -> str:
    """§4.12.3 #6: LiquidityTier 分层 — HIGH/MID/LOW (白名单或 24h vol 分位)"""
    if not coin:
        return "MID"
    if coin.upper() in ("BTC", "ETH", "SPY", "QQQ", "GLD", "SLV", "USDT", "USDC"):
        return "HIGH"
    return "MID"  # 其它后续按 24h 成交额分位细化

def _realtime_audit_score(self, default: float = 75.0) -> float:
    """R6 §4.12.2: 「将」维度 = audit_score（系统行为审计分）。
    规则: audit_score = 100 - 40*越界_norm - 30*超时_norm - 30*异常_norm。
    统计滚动窗口 = 近 7 天（按轮询轮数 ≈ 7*24h/5min = 2016 轮）。
    归一方式: 每类惩罚 = min(1.0, 实际次数 / 阈值次数)。
    """
    try:
        audit = getattr(self, "_audit_window", None)
        if audit is None:
            # 首次初始化（实盘会把审计窗口持久化到 state.json；这里仅 MVP 的内存版）
            self._audit_window = {
                "over_bound_cnt": 0,   # 仓位越界次数（实际仓位 > 风控上限 × 1.02）
                "timeout_cnt": 0,      # 超时未平次数（持仓龄 > timeout_hours × 1.5）
                "abnormal_exit_cnt": 0, # 异常退出次数（非 6 个 ExitStrategy/易经卦象/RankedTp 触发，即 force_close_type="external"）
                "window_start_ts": time.time(),
            }
            audit = self._audit_window
        W1, W2, W3 = 0.40, 0.30, 0.30
        THR1, THR2, THR3 = 10.0, 6.0, 4.0  # 7天内阈值：越界 >10 / 超时 >6 / 异常 >4 分别把该类惩罚拉满 1.0
        over_norm = min(1.0, float(audit["over_bound_cnt"]) / THR1)
        timeout_norm = min(1.0, float(audit["timeout_cnt"]) / THR2)
        abnormal_norm = min(1.0, float(audit["abnormal_exit_cnt"]) / THR3)
        score = 100.0 - 100.0 * (W1*over_norm + W2*timeout_norm + W3*abnormal_norm)
        return max(0.0, min(100.0, score))
    except Exception:
        return max(0.0, min(100.0, float(default)))

def _war_state_should_skip(self, total_score: float) -> bool:
    """§4.12.3 #4: 不出战滞回 + 冷却计数器。返回 True 表示本轮不应开新仓。
    规则: 总分 < 60 → 触发进入冷却(连 3 轮≥60 才恢复)。也可按日级: 当日触发后当日冻结。
    """
    need_rounds = getattr(self, "_war_state_need_recover_rounds", 3)
    state = getattr(self, "_war_state", 0)
    if total_score < 60:
        self._war_state = need_rounds
        return True
    if state > 0:
        if total_score >= 60:
            self._war_state = max(0, state - 1)
            if self._war_state > 0:
                return True  # 还没恢复到 0 → 继续冻结
            return False  # 刚恢复
        else:  # < 60 但计数器状态未清零, 按新触发重置(等价)
            self._war_state = need_rounds
            return True
    return False
```

### 2.7 改造 `exit_manager.evaluate()` 调用

**文件**：`polling_trader.py` L5990

```python
# 读取持仓元数据（优先从 tracker_pos.enhance_info，R2 一次性绑定 + 版本）
_meta = (
    (tracker_pos.enhance_info if hasattr(tracker_pos, "enhance_info") and tracker_pos else None)
    or inference.get("enhance_result")
    or {}
)
_strat_type = _meta.get("strategy_type") or inference.get("strategy_type") or None
_style_exp = _meta.get("style_exposures") or inference.get("style_exposures")
_exit_cfg = _meta.get("exit_config") or inference.get("strategy_exit_config") or {}
_strat_ver = _meta.get("strategy_version") or inference.get("strategy_version")
_regime_lbl = _meta.get("regime_label") or (inference.get("enhance_result") or {}).get("regime")
_five_sc = _meta.get("five_score_snapshot")

_exit_decision = self.exit_manager.evaluate(
    coin=coin, inference=inference, pos_info=pos_info, tracker_pos=tracker_pos,
    in_protection=in_protection, age_hours=position_age_sec / 3600.0,
    ev=_ev, confidence=confidence, all_inferences=all_inferences or {},
    held_coins=_held_coins, effective_threshold=effective_threshold,
    # ↓ 新增（全部 Optional, 旧分支缺字段不会报错 R1） ↓
    strategy_type=_strat_type,
    style_exposures=_style_exp,
    exit_config=_exit_cfg,
    strategy_version=_strat_ver,
    regime_label=_regime_lbl,
    five_score_snapshot=_five_sc,
)
```

### 2.8 RankedTp 独立循环接入（R4，不并入 ExitManager）

**文件**：`polling_trader.py` `_handle_ranked_tp_top1` 入口（L4002 附近）

```python
def _handle_ranked_tp_top1(self, ...):
    if not getattr(self, "enable_ranked_tp", False):
        return
    # ★ 新增: 先过滤 strategy_type 的 allow-list（R4 / StrategySelection.enable_ranked_tp_allow）
    filtered = []
    for coin, pnl, entry_price, pos_usdt, tracker_pos in positions_with_pnl:
        # R4: 读取 enhance_info 里的策略配置 (开仓时一次性绑定 R2)
        _meta = (
            (tracker_pos.enhance_info if tracker_pos and hasattr(tracker_pos, "enhance_info") else None)
            or {}
        )
        _allow = _meta.get("enable_ranked_tp_allow", True)
        # §4.11.4 默认规则: trend_follow / volatility / emergency 不参与 RankedTp (让利润跑 / 现金优先)
        if _allow is None:
            _stype = _meta.get("strategy_type") or ""
            _allow = _stype not in ("trend_follow", "volatility", "emergency")
        if _allow:
            filtered.append((coin, pnl, entry_price, pos_usdt, tracker_pos))
    # 后续原逻辑: 使用 filtered 取代原始 positions_with_pnl 计算 gap / 触发排名止盈
    # ...
```

### 2.9 归因 schema 扩展（§4.12.3 #3，策略层一等公民）

**文件**：`polling_trader.py` `_save_exit_strategy_decision`（L1752）

```python
def _save_exit_strategy_decision(
    self, coin, decision, age_hours, in_protection, ev, confidence,
    pnl=None, win=None,
    strategy_type: Optional[str] = None,    # ★ 新增
    style_exposures=None,                   # ★ 新增
    regime_label: Optional[str] = None,     # ★ 新增
    five_score_snapshot=None,               # ★ 新增
    strategy_version: Optional[str] = None, # ★ 新增
):
    try:
        _storage = getattr(self.exit_manager, "_storage", None)
        if _storage is None:
            return
        _storage.save_exit_strategy_log(coin, {
            "strategy_name": decision.strategy_name or "",
            "action": decision.action,
            "reason": decision.reason,
            "age_hours": age_hours,
            "in_protection": in_protection,
            "ev": ev,
            "confidence": confidence,
            "pnl": pnl,
            "win": win,
            # ↓ 新增 (v2 schema, 为月度归因报表提供分组维度 §4.12.3 #3) ↓
            "strategy_type": strategy_type or "",
            "style_exposures": style_exposures if isinstance(style_exposures, dict) else None,
            "regime_label": regime_label or "",
            "five_score_snapshot": five_score_snapshot if isinstance(five_score_snapshot, dict) else None,
            "strategy_version": strategy_version or "",
        })
    except Exception as _e:
        self._log(f"[{coin}] exit_strategy_log 记录失败（不阻断）: {_e}", "WARN")
```

> `save_exit_strategy_log` 的底层存储（SQLite 列或 JSON）需同步做 schema v+1，兼容旧行缺列时填 `""`/`None`。

### 2.10 路径 A 改动汇总（v1.1 修订版）

| 文件 | 改动点 | 改动量（估算） |
|---|---|---|
| `bcrm2/strategy_selector.py` | **全新文件**：权重向量（G1）+ regime baseline（G2）+ EMA 平滑（G3）+ 风险预算 sizing + 流动性（§4.12.3#6）+ 6 策略退出参数表（G6） | ~320 行 |
| `bcrm2/exit_manager.py` | ExitContext +6 字段（R1，全 Optional）；evaluate() +6 参数（全 Optional）；ChandelierExitStrategy 可选注册（G7，默认关） | ~25 行 |
| `bcrm2/exit_strategies.py` | 4 个策略加三级 fallback；新增 ChandelierExitStrategy（G7，默认禁用） | ~80 行 |
| `trading_utils.py` | **路径 A 不改 schema**；后续路径 B 可加字段（R5） | 0 行（A） |
| `polling_trader.py` | _open_position 顺序注入：G4 高波动硬约束（R7）→ 策略选择器 + R3 min 叠加 + 风险预算 sizing（§4.12.3#2）；R6 将维度 audit_score 审计窗口（§4.12.2）；_war_state 冷却（§4.12.3#4）；exit_manager.evaluate 传参；_handle_ranked_tp_top1 gate（R4，含 breakout 默认保留说明）；_save_exit_strategy_decision 扩列（归因 5 列）；_compute_five_domain_scores / _classify_liquidity_tier / _apply_regime_vol_cap / _realtime_audit_score / _war_state_should_skip | ~240 行 |
| `exit_strategy_log` 存储 | schema v+1 扩列（strategy_type/style_exposures/regime_label/five_score_snapshot/strategy_version，可选，不阻塞热路径） | ~10 行 |
| **合计** |  | **~675 行**（相较原 v1.0 的 215 行主要多了 G1-G10 + R1-R7：权重向量与平滑、流动性分层、ATR 风险预算 sizing、归因 schema 扩展、不出战冷却、audit_score 审计窗口、G4 高波动硬约束；这是换取 80% 架构稳健性 + 避免传统金融经典反模式的合理成本） |

### 2.11 向后兼容性保证（R1+R2+R4+R5）

- `strategy_type=None/""` + `exit_config=None` → 所有 ExitStrategy 走原有构造参数阈值，**行为完全等价现状**（R1）。
- 策略选择器任何异常 → fail-open 为默认 `StrategySelection()`（trend_follow，position_mult=1.0、风险预算 1%、exit_config 空）。
- 历史持仓 JSON 中无 strategy 字段 → 加载时 `enhance_info.get("strategy_type")=None` → 离场层按现状执行（R5）；**不中途切换策略规则**。
- RankedTp 保持为独立跨持仓循环（R4）：`enable_ranked_tp_allow` 缺省 True；strategy_type ∈ {trend_follow, volatility, emergency} 自动按 allow=False gate。
- `_war_state` 冷缺计数器初始值 0 → 默认不影响现有开仓；触发不出战后才开启冻结。

---

## 三、路径 B：完整改造（后期可选，**仅在组合级使用**）

### 改造原则（红线来自 §4.12.3 #7 + G10）

1. **G10 红线约束**：路径 B 的多 Exit 子链**仅在组合级（整个账户的策略切换）**维护（比如 "账户进入 Risk-Off 模式" → emergency 子链；"CTA 模式" / "均值回归模式"），**不得把单笔交易拆成 6×6=36 条子链**。单笔交易的策略差异化全部通过路径 A 的 `ExitContext.strategy_type + exit_config lookup table` 实现。这样可以避免"配置漂移"（某条子链改了阈值、其它没改，导致回测与实盘不一致）这一经典多策略反模式。
2. **单笔级差异化**：继续用路径 A 的 lookup table（§4.13.3），组合级才切换 ExitManager 的策略子链。
3. **G9 聚类约束**：路径 B 在 CapitalControlComponent 下游新增**"持仓聚类约束"**硬约束（PCA / Hierarchical Clustering 或简化按 coin 白名单分桶），同方向同风格总仓 ≤ 总仓位 cap X%，该约束对组合风险贡献远大于单笔退出规则。
4. **流动性池 × 策略矩阵（§4.12.3 #6）**：在路径 A 已有 LIQUIDITY_STRATEGY_ALLOWED 基础上，路径 B 增加 "流动性分档 → 单笔上限 USDt → 总仓上限" 的硬约束表。
5. **RankedTp 继续独立循环（R4）**：即使路径 B 也不把 RankedTp 并入 ExitManager 链，避免破坏已验证的 gap 计算。路径 B 只能为跨持仓循环提供 "组合级 enable_ranked_tp_allow 路由表"。

### 3.1 ExitManager 结构改造（**组合级切换专用**）

```python
class ExitManager:
    """离场策略链管理器（路径 B：按组合级策略模式分组 + 默认单笔 type 路由）。
    - 组合模式: "default" / "cta_risk_on" / "mean_revert_mode" / "risk_off_emergency"
    - 单笔差异化: 仍按 ctx.strategy_type + exit_config（路径 A）
    """
    def __init__(self, portfolio_chains: Dict[str, List[ExitStrategy]] = None):
        # 组合模式 → 策略子链
        self._chains: Dict[str, List[ExitStrategy]] = {}
        if portfolio_chains:
            for k, strategies in portfolio_chains.items():
                self._chains[k] = sorted(strategies, key=lambda s: s.priority)
        self.portfolio_mode: str = "default"  # 可在轮询开头按五计总分 / 账户回撤动态切换 (G10)
        self._log_buffer: List[Dict[str, Any]] = []
        self._storage: Any = None

    def evaluate(self, coin, inference, pos_info, tracker_pos,
                 in_protection, age_hours,
                 strategy_type=None, style_exposures=None,
                 exit_config=None, strategy_version=None,
                 regime_label=None, five_score_snapshot=None,
                 **kwargs):
        ctx = ExitContext(coin=coin, inference=inference, pos_info=pos_info,
                          tracker_pos=tracker_pos, in_protection=in_protection,
                          age_hours=age_hours, ev=kwargs.get("ev"),
                          multi_horizon=kwargs.get("multi_horizon"),
                          confidence=kwargs.get("confidence", 0.0),
                          all_inferences=kwargs.get("all_inferences"),
                          held_coins=kwargs.get("held_coins"),
                          effective_threshold=kwargs.get("effective_threshold"),
                          strategy_type=strategy_type, style_exposures=style_exposures,
                          exit_config=exit_config, strategy_version=strategy_version,
                          regime_label=regime_label, five_score_snapshot=five_score_snapshot)
        chain = self._chains.get(self.portfolio_mode, self._chains.get("default", []))
        for strategy in chain:
            if not strategy.enabled:
                continue
            decision = strategy.evaluate(ctx)
            if decision.action != "pass":
                decision.strategy_name = strategy.name
                return decision
        return ExitDecision.pass_()
```

### 3.2 组合模式子链注册（G10，示例）

路径 B 注册的是**组合级模式**（4 种），而不是单笔 6 种 strategy_type 的 6×6 组合：

- `"default"`（日常模式）：沿用路径 A 的 5 策略链 + 可选 ChandelierExitStrategy
- `"cta_risk_on"`（趋势模式）：更激进强持 EV strong_above=0.40；Timeout 全局延长；RankedTp 在组合级关闭（即 `enable_ranked_tp=False` 直接设置主开关）
- `"mean_revert_mode"`（震荡模式）：Timeout 缩短；EvForceClose 收紧到 −0.25；RankedTp 开启
- `"risk_off_emergency"`（Risk-Off 模式）：所有子策略阈值最紧；Timeout 6h；EvAdjust warn_upper=−0.05；只允许最多 1 个新仓/小时

> 单笔级的 breakout_fail / mean_revert_target / volatility_shift 策略（原方案 §3.3）依旧作为路径 A 的 lookup 可选方案，但**不独立成链**——它们通过 `exit_config` + `if ctx.strategy_type == "breakout"` 的内部分支触发，避免 36 条子链维护。

### 3.3 聚类约束（G9，路径 B 真正产生价值的增量）

在 CapitalControl 之后、`_open_position` 之前新增组合硬约束：

```python
def _enforce_cluster_cap(self, new_coin: str, new_direction: str, new_style_exp: Dict[str, float],
                         new_size_usdt: float) -> bool:
    """G9: 同方向 + 同风格聚类总仓上限。
    简化版实现: 按 (direction, argmax(style_exp)) 分桶;
    高级版实现: 计算组合 net_exposure = Σ direction_i * size_i * style_exposures_i[s] per style.
    """
    cap_pct = 0.50  # 同方向同风格不超过权益 50%
    equity = max(float(self.account_snapshot.get("total_equity", 0) or 0), 1.0)
    style_bucket = max(new_style_exp.items(), key=lambda kv: kv[1])[0] if new_style_exp else "trend_follow"
    current_total = new_size_usdt
    for pos in self.position_tracker.open_positions.values():
        if pos.direction != new_direction:
            continue
        meta = pos.enhance_info or {}
        exp = meta.get("style_exposures") or {}
        if max(exp.items(), key=lambda kv: kv[1])[0] if exp else "trend_follow" == style_bucket:
            current_total += abs(float(pos.entry_price) * float(pos.amount) * float(pos.leverage or 1))
    return current_total <= equity * cap_pct  # True=通过, False=拒绝开仓
```

### 3.4 路径 B 改动汇总（修订版）

| 文件 | 改动点 | 改动量（估算） |
|---|---|---|
| `bcrm2/exit_manager.py` | 引入 `portfolio_mode`（4 档）与组合子链切换 | ~35 行 |
| `polling_trader.py` ExitManager 初始化 | 注册 4 档组合模式子链（非 36 单笔组合） | ~40 行 |
| `polling_trader.py` | `_enforce_cluster_cap`（G9 聚类约束）；流动性分档→单笔/总仓上限；组合 RankedTp 开关联动 | ~100 行 |
| `exit_strategies.py` | 内部分支实现 breakout_fail / mean_revert_target / volatility_shift（通过 `if ctx.strategy_type == x`），不独立成链（避免 36 子链） | ~120 行 |
| `exit_strategy_log` 存储 | schema v+1 的 `portfolio_mode` 列 | ~5 行 |
| **合计** |  | **~300 行（相较原方案 240 行，换来了更稳的组合风险控制 + 避免 36 链配置漂移反模式）** |

---

## 四、测试方案

### 4.1 路径 A 测试（v1.1 增补至 28 项）

**新增测试文件**：`tests/test_strategy_layer.py`

| 类别 | 测试用例 | 验证目标 |
|---|---|---|
| 策略选择器核心 | test_strategy_selector_trend_follow | 道高+地高 → main=trend_follow, style_exposures.trend_follow≈0.73 |
| 策略选择器核心 | test_strategy_selector_emergency | 总分 < 60 → emergency, risk_budget_pct ≤ 0.4% |
| G1 权重向量 | test_style_exposures_sum_to_one | 任何情况下 Σ style_exposures = 1.0 (G1) |
| G3 EMA 平滑 | test_weights_ema_smooth | 连调 5 次 select，权重向量 EMA 无跳变 (G3，Δ < 0.15) |
| G2 regime 基线 | test_regime_5_state_to_base_weights | TREND_STRONG / RANGE_TIGHT / CHOPPY 基线权重与 G2 矩阵一致 (G2) |
| §4.12.3#6 流动性 | test_liquidity_tier_filter | LOW 层 breakout/volatility/emergency 过滤 → 权重=0 |
| R1 向后兼容 | test_exit_context_none_fields_default | ExitContext 全缺省值编译通过、构造零报错 |
| R1 三级 fallback | test_signal_reverse_three_level_fallback | exit_config > strategy_type 默认 > 构造 base_threshold |
| G6 参数表 | test_timeout_skip_for_trend_follow | trend_follow → TimeoutProfitSwitch pass (跳过超时) |
| R4 RankedTp gate | test_ranked_tp_gate_trend_follow_disallowed | trend_follow/volatility/emergency → enable_ranked_tp_allow=False |
| R4 对照表 | test_ranked_tp_gate_breakout_allowed (新增) | breakout/mean_revert/momentum 默认允许参与 RankedTp (§4.13.3) |
| R3 单调性 | test_open_position_min_monotonic | 策略层 sl_mult 取 min(后置层, 策略层) (不放大) |
| §4.12.3#2 sizing | test_risk_budget_sizing_no_override_risk | 风险预算 sizing 出的 size < risk 后 size 时, 仍不会放大 (R3) |
| §4.12.3#2 sizing | test_risk_budget_sizing_atr_division (新增) | atr=0 / sl_mult=0 时 sizing 安全降级 (ZeroDivision 保护) |
| R2 一次性绑定 | test_strategy_type_once_binded_on_open | 开仓后 enhance_info 存 strategy_type，load_open_position 恢复不丢 |
| R2 版本号 | test_strategy_version_tagged | 开仓落盘 strategy_version = "slv1.0" |
| §4.12.3#4 冷却 | test_war_state_cool_down_freeze | 总分<60 → 连 3 轮 ≥60 才恢复开仓 |
| §4.12.3#4 冷却 | test_war_state_default_no_freeze | war_state=0 + 60 分以上 → 正常开仓 (不影响现状) |
| G8 离线道评分 | test_offline_dao_score_preferred | 离线缓存 dao=85 存在时，优先用离线路径 |
| §4.12.3#3 归因 | test_exit_strategy_log_expanded_cols | 落表时含 strategy_type/regime_label/five_score_snapshot/strategy_version/style_exposures |
| Fail-Open | test_selector_fail_open_default | 异常 → 默认 StrategySelection() (trend_follow + 风险预算 1%) |
| G7 Chandelier | test_chandelier_exit_disabled_by_default | 默认 enabled=False 不触发 |
| G7 Chandelier | test_chandelier_exit_trend_follow_gate | 仅 trend_follow + use_chandelier_exit=True 才生效 |
| **R6 audit_score** | test_audit_score_perfect_when_no_violations (新增) | 越界=超时=异常=0 → audit_score=100 分 (满分) |
| **R6 audit_score** | test_audit_score_saturates_at_zero (新增) | 三类违规次数全部超阈值 → audit_score=0 (拉满惩罚) |
| **R7 G4 高波动约束** | test_regime_vol_cap_triggers_correctly (新增) | regime=CHOPPY 且 atr_percentile≥0.8 → 上限 ×0.5 |
| **R7 G4 高波动约束** | test_regime_vol_cap_no_trigger_when_low_vol (新增) | TREND_STRONG regime / atr_percentile=0.5 → 不修改上限 |
| **R7 G4 高波动约束** | test_regime_vol_cap_fail_open (新增) | 函数异常 → 返回原值不额外收紧 (Fail-Open) |

### 4.2 路径 B 测试（补充聚类/组合模式相关）

| 测试用例 | 验证目标 |
|---|---|
| test_portfolio_mode_default_chain | mode="default" → 子链 = 5 现有策略 + 可选 Chandelier |
| test_portfolio_mode_risk_off_emergency_tighten | Risk-Off 模式 → timeout=6h / EvFC=-0.20 / 阈值最紧 |
| test_cluster_cap_blocks_same_bucket_excess | 同方向同风格超限 → _enforce_cluster_cap 返回 False (G9) |
| test_cluster_cap_allows_diversified_bucket | 跨风格分散 → 允许开仓 (G9) |
| test_breakout_fail_internal_branch | ctx.strategy_type=="breakout" 触发失败检测内部分支 |
| test_mean_revert_target_internal_branch | ctx.strategy_type=="mean_revert" 触发回归达标内部分支 |
| test_portfolio_mode_ranked_tp_cta_mode | cta_risk_on → 组合级 enable_ranked_tp=False |
| test_single_trade_still_routed_by_type | mode=cta_risk_on, 一笔 breakout 单 → 仍按 breakout exit_config 路由 (路径 A 仍在) |

---

## 五、实施路径（整合 R1-R7 红线 + G1-G10 落地清单）

```
 路径 A（轻量改造，v1.1 ~675 行）                    路径 B（组合级改造，~300 行，红线 G10）
 ────────────────────────────────────                ───────────────────────────────────────────
 Step A1: strategy_selector.py 新建                   Step B6: ExitManager 加 portfolio_mode
      ├─ G1 权重向量替代单选 (style_exposures)            (4 档模式, 不是 36 单笔链)
      ├─ G2 五态 regime → 四态基线矩阵                   G10: 仅组合级, 避免配置漂移反模式
      ├─ G3 EMA 平滑权重向量 (α≈0.15)
      ├─ §4.12.3#6 Liquidity×Strategy 允许矩阵
      └─ G6 6 策略退出参数对照表 (§4.13.3)
                                                        Step B7: 子策略内部分支实现
 Step A2: ExitContext +6 字段 (R1, 全 Optional)              breakout_fail / mean_revert_target
 Step A3: 4 ExitStrategy 三级 fallback (R1)                  / volatility_shift (内部分支, 非独立成链)
        + G7 新增 ChandelierExitStrategy (默认禁用, 趋势策略 3×ATR 移动止盈)
                                                        Step B8: ExitManager 初始化 4 模式链
 Step A4: _open_position 约束链路升级 (R2+R3+R6+R7)           + 组合级 RankedTp 开关联动
        ├─ ★ R7(G4) _apply_regime_vol_cap 高波动×0.5
        ├─ 策略选择器 → StrategySelection
        ├─ R3 min 单调性 (仓位/SL 取更严格, TP 趋势可放宽)
        ├─ §4.12.3#2 风险预算 sizing (risk_budget / (ATR×sl_mult))
        ├─ R6 将维度 audit_score 审计窗口 (越界/超时/异常 w1-w3)
        ├─ §4.12.3#4 _war_state 不出战滞回 + 冷却计数器
        ├─ G8 离线 dao 周批量评分优先 (不进 5min 热路径)
        └─ R2 一次性绑定: enhance_info 写入 strategy_type / style_exposures /
           exit_config / strategy_version / regime_label / five_score_snapshot

 Step A5: exit_manager.evaluate() 扩参 (R1, 全 Optional)  Step B9: G9 聚类约束 _enforce_cluster_cap
 Step A6: _handle_ranked_tp_top1 allow-gate (R4)               (同方向同风格总仓位 cap ≤ 50%)
        默认保留: breakout / mean_revert / momentum
        默认禁止: trend_follow / volatility / emergency
 Step A7: exit_strategy_log 扩 5 列 (§4.12.3#3 + G5)     Step B10: 路径 B 测试
        strategy_type / style_exposures / regime_label        组合模式 / 聚类约束 / 内部分支
        / five_score_snapshot / strategy_version              回测对比 A→B 的夏普/回撤
 Step A8: 路径 A 测试 (28 项 + 回测摩擦 §4.12.3#5)          回测必含: 滑点 + 手续费 + 同风格相关性
        28 项: 选择器(2)/G1G2G3(3)/流动性(1)/R1(2)/R4(2)
              /R3(1)/sizing(2,含 ZeroDivision 保护)/R2(2)
              /冷却(2)/G8 离线(1)/归因(1)/Fail-Open(1)
              /G7 Chandelier(2)
              /★R6 audit_score(2)
              /★R7 G4 高波动 cap(3,含触发/不触发/Fail-Open)
        回测: 加密 2-5 bps 滑点 / 美股 1-3 bps + maker-taker 手续费
              + 同方向同风格聚类总仓 cap (与 B9 一致的摩擦模拟)
```

---

## 六、GitHub 经验 G1-G10 落地映射表（来自五维度评估 §4.13.5，v1.1 校正）

| 编号 | 落地项 | 借鉴来源 | 本方案位置（路径 A / 路径 B） |
|---|---|---|---|
| G1 | 用 style_exposure 权重向量替代 strategy_type 单选（避免单点路由判错全盘错） | RegimeSense (moh1tt) | A: §2.1 StrategySelection.style_exposures / Step A1 |
| G2 | 易经五态 regime → RegimeSense 四态权重矩阵 baseline 映射（v1 首版矩阵现成可用） | RegimeSense | A: §2.1 StrategySelector._regime_to_base_weights / Step A1 |
| G3 | 权重 EMA 平滑（α≈0.15），避免 5 分钟轮询每轮跳变（减少换手+交易成本） | RegimeSense | A: §2.1 StrategySelector._smooth_exposures / Step A1 |
| **G4** | **高波动 regime 总仓位自动 ×0.5 硬约束（只能收紧不放宽）** <br> 触发条件: `regime ∈ {CHOPPY, RANGE_TIGHT} AND atr_percentile ≥ 0.8` | regime-aware-portfolio-risk-engine (jimech) | A: **R7 红线** `_apply_regime_vol_cap()` 放在 CapitalControl 下游（§2.6 / Step A4），fail-open 异常时不收紧 <br> B: 结合 G9 聚类做 regime-conditional covariance 动态 cap |
| G5 | 按 regime 分组的归因报表（策略贡献柱、回撤贡献饼、风格暴露雷达图） | regime-aware-portfolio-risk-engine | A: §2.9 exit_strategy_log 扩 5 列（strategy_type/style_exposures/regime_label/five_score_snapshot/strategy_version）/ Step A7 <br> 月度离线报表模板 |
| G6 | 6 类策略 × 退出参数对照表（Timeout/反转阈值/EV 阈值/RankedTp 开关/TP 类型）——路径 A 的 80% 价值所在 | IssacWong0103 ADX 路由 §4.13.3 | A: §2.1 StrategySelector._default_exit_params 6 分支（§4.13.3 的值） / Step A1 |
| G7 | 3×ATR Chandelier Exit 作为 trend_follow 策略的移动止盈（不设固定 TP，默认关由 exit_config 软启用） | IssacWong0103 + CTA 行业文献 | A: §2.4.3 ChandelierExitStrategy（priority=25，默认 enabled=False，由 exit_config.use_chandelier_exit=True 触发）/ Step A3 |
| G8 | "道"维度离线路径周批量评分（周末 Fed/FOMC + 稳定币周环比 + ETF 资金流 + LLM 文本），**绝不放进 5 分钟热路径** | wolf-of-vibe-street knowledge.md 三层架构 | A: §2.6 _compute_five_domain_scores → `_cached_offline_dao_score()` 读 YAML 缓存；热路径只用代理 dao=confidence×100 / Step A4 |
| G9 | 组合级聚类约束（同方向 + 同风格 = 同一桶，总仓位 ≤ 权益 50%），控制相关性风险 | regime-aware-portfolio-risk-engine | B: §3.3 `_enforce_cluster_cap()`（简化版按 argmax 分桶，高级版 Σ direction × size × style_exposures）/ Step B9 |
| **G10** | **反 36 子链红线：路径 B 的多 Exit 子链仅在组合级维护（4 档模式）**；单笔差异化用路径 A 的 lookup table（G6 表 + ctx.strategy_type 内部分支），避免配置漂移反模式 | 传统金融 §4.12.3 #7 + RegimeSense | A: 所有单笔差异化走 G6 exit_config 表 <br> B: §3.1 ExitManager._chains 只注册 4 档组合模式 / Step B6+B8 |

---

## 七、传统金融 7+1 条建议执行清单（来自五维度评估 §4.12.2 可行性评级 + §4.12.3 改进建议）

| 编号 | 建议（含可行性评级） | 本方案对应实现 |
|---|---|---|
| 0 (§4.12.2) | **将维度改为 audit_score**（可行性 B-）：放弃「智信仁勇严」主观量化，用「系统行为审计」硬指标归一 | R6 红线 / §2.6 `_realtime_audit_score`：越界次数(0.4)+超时未平(0.3)+异常退出(0.3)；滚动窗口 7 天 |
| 1 (§4.12.3 #1) | style_exposures 权重向量替代单选（避免单点路由判错） | G1 / §2.1 StrategySelection.style_exposures；Σ = 1.0；组合层做暴露聚合 |
| 2 (§4.12.3 #2) | 风险预算 sizing（0.25%~2% Kelly 半凯区间） ÷ (ATR × sl_mult) 反算仓位（Turtle/AHL 范式）；**禁止直接「分数 × 默认仓位」** | §2.1 risk_budget_pct + §2.6 _open_position 中 `risked_usdt / stop_distance_usdt` 反算；ATR / sl_mult 为 0 时安全降级 |
| 3 (§4.12.3 #3) | 归因一等公民：strategy_type / regime_label / five_score_snapshot → exit_strategy_log 扩列 + 月度归因报表（按 regime 分组） | §2.9 扩 5 列 + G5 / Step A7；报表模板：贡献柱 / 回撤饼 / 风格雷达 |
| 4 (§4.12.3 #4) | 「不出战」熔断双阈值（滞回） + 冷却计数器（连 3 轮 ≥ 60 才恢复 Risk-On） | §2.6 `_war_state_should_skip`；`_war_state_need_recover_rounds=3` |
| 5 (§4.12.3 #5) | 回测强制三项现实摩擦：滑点（加密 2-5 bps / 美股 1-3 bps）、手续费（maker/taker 档位）、同风格相关性（G9 聚类约束） | Step A8 / B10 回测要求；均值回归/波动率策略必显式模拟（换手高易吃光 α） |
| 6 (§4.12.3 #6) | LiquidityTier × StrategyType 可用性矩阵：低流动性池禁高换手策略（breakout/volatility） | §2.1 LIQUIDITY_STRATEGY_ALLOWED 3×6 矩阵 + §2.6 `_classify_liquidity_tier` 白名单；低池仅允许 trend_follow/mean_revert/momentum |
| 7 (§4.12.3 #7) | 路径 B 反模式红线：多 Exit 子链**仅组合级（4 档）**，单笔差异化走路径 A lookup table（G6 表）；严禁 6×6=36 单笔子链（配置漂移经典坑） | §3 改造原则 / G10 红线；ExitManager._chains 只注册 default/cta_risk_on/mean_revert_mode/risk_off_emergency |

---

## 八、风险与注意事项（v1.1：融合 R1-R7 红线 + 评估校正）

1. **全链路 Fail-Open**：策略选择器 / G4 `_apply_regime_vol_cap` / R6 `_realtime_audit_score` 任何一个函数异常时，都降级为"不改现状"的行为（选择器→默认 trend_follow+风险预算 1%；G4→返回原值不收紧；R6→返回 default 分），**绝不因为策略层新增功能阻塞交易**。
2. **向后兼容（R1+R5）**：`strategy_type=None/""` + ExitContext 新字段全 `Optional[...] = None` → 所有旧调用点和测试零改动能编译；TradeRecord 不改 schema（路径 A）→ 历史持仓 JSON 全部可通过 `_load_open_positions` 白名单恢复。
3. **持仓期间不改 strategy_type（R2）**：任何中途 type 切换都会导致规则跳变（趋势单被均值回归强制平是经典事故）。允许的是同 type 内调阈值参数（timeout 延长/缩短、EV 阈值微调），同步落盘 `strategy_version`，代码升级后旧持仓按旧版本规则。
4. **RankedTp 保持独立循环（R4）**：A/B 都不移动 RankedTp 的 gap 计算逻辑。默认规则严格遵循 §4.13.3 对照表：**breakout / mean_revert / momentum 保留参与；trend_follow / volatility / emergency 自动禁止**。emergency 模式下优先现金，不做跨仓换仓。
5. **约束单调性（R3）**：所有叠加一律取**更严格者**（仓位 min、SL min）；趋势策略 TP 可放宽或 None（由 Chandelier Exit 管），但**严禁覆盖风控输出的日损上限 / 单票风险预算**。"庙算高分放大风控阈值"是反模式。
6. **R6 audit_score 的持久化与滚动窗口（新增）**：`_audit_window` 内存版仅 MVP；实盘必须持久化到 `state.json` 并在进程重启后恢复；7 天滚动窗口需按轮询时间戳剔除过期数据（避免内存版计数器无限增长导致 score 永远 <40 触发不出战）。
7. **R7 G4 高波动约束的指标依赖（新增）**：`atr_percentile_252` 需要后置层提前在 `enhance_info` 中输出（ATR(14) 相对近 252 根 K 线的分位数）；若后置层暂未输出则用 inference 中 technical_indicators 作为 fallback，全部缺失时 G4 自动降级（不触发 cap）——避免因缺少指标导致 G4 永不触发或误触发。
8. **§4.12.3 #2 风险预算 sizing 的 ZeroDivision 保护（新增）**：`ATR=0` 或 `sl_mult=0` 时绝不能 `risk_budget / 0`；必须有安全降级分支 → 此时放弃风险预算 sizing，保留 risk/p2 之后的 size（等价现状）。
9. **_compute_five_domain_scores 的代理版是过渡**："道"维度必须尽快改为 G8 离线周批量打分（周末 Fed/FOMC + 稳定币周环比 + ETF 资金流 + LLM 文本），**绝不进 5 分钟热路径**；"天"接入季节性因子；"将"= R6 audit_score；"法"= 策略库近 N 日各策略胜率加权。
10. **SL/TP 覆盖顺序（自顶向下取严格）**：CapitalControl → G4 高波动 cap → 后置层推荐阈值 → 策略层（min 叠加，TP 趋势可放宽）→ RiskManager 最终否决。策略层只在后置层之上做收紧或等宽，不绕过。
11. **路径 A 是路径 B 的前置条件**：路径 B 的 4 档组合模式链中，单笔差异化仍走路径 A 的 `exit_config + strategy_type` lookup（G6 表 + 内部分支）。路径 B 不是路径 A 的替代，而是组合级风险的增量。
12. **回测强制 3 项现实摩擦（§4.12.3 #5）**：滑点（加密 2-5 bps、美股 1-3 bps，按规模分档）、手续费（合约 maker -0.02% / taker 0.05%，现货 0.1% / 0.4%）、相关性（G9 同风格同方向聚类总仓 cap）。均值回归和波动率策略必须显式模拟，否则回测 α 全部是摩擦幻觉。
13. **路径 B 配置漂移反模式（G10 红线）**：严格 4 档组合模式，绝对禁止 6×6 单笔子链。任何阈值参数统一收敛到 `_default_exit_params` 一张表（G6），避免某条链改了阈值、另一条忘了改导致回测-实盘不一致。
14. **权重 EMA 平滑（G3）**：即使 regime 判错了一次，style_exposures 也不会从 0→1 硬切（α≈0.15 约需 6-7 轮才接近稳态），保护了 sizing 稳定性和换手率（避免买卖频繁吃掉利润）。
15. **五计庙算跨类相关性约束（新增提醒）**：庙算的"不出战"需按加密 / 美股 / 黄金白银三类独立判断；三类同时低分进入全面防御模式；两类低分时第三类仓位再 × 0.8。该约束在 `_war_state_should_skip` 外层调用时实现（不属于路径 A MVP 第一优先级，但需列入归因维度）。

---

## 九、模块化开关与影子 AB 接入（v1.2 新增，对齐《五维度评估》§12–§13）

> **定位**：本方案的 R1–R7 / G1–G10 是内层规则（开/关不改动逻辑正确性），开关架构是外层 gating（默认关闭=零影响，开了之后内层规则才生效）。两者是**超集关系，无冲突**。冷启动默认全关 → 先影子 AB 2-4 周 → 子开关逐个打开 → 最后总开关全开。

### 9.1 开关总览（2 总 + 7 子 + 3 模式，默认全 False）

| 归属 | 开关名 | 默认 | 关断后等价 | 接入位置 |
|---|---|---|---|---|
| 战略层 总 | `enable_five_domain` | **False** | `five_scores` 返回默认高灰区 `{dao:70, tian:70, di:70, jiang:80, fa:75}`（庙算 72.75，<60 不出战不触发）；`war_state` 永远允许；仓位/风格 mask/跨类约束 全旁路 | 路径 A §2.6 `_open_position` 最外层 gate：`if getattr(self, "enable_five_domain", False):` |
| 战略层 子 1 | `enable_five_domain_war_state` | True（总开后生效） | 「不出战+滞回冷却」永久允许 | 同上内部：`if getattr(self, "enable_five_domain_war_state", True): _war_state_should_skip()` |
| 战略层 子 2 | `enable_five_domain_position_cap` | True | §5.2 仓位映射 + 维度否决规则 旁路 | `_open_position`，五计分之后 |
| 战略层 子 3 | `enable_five_domain_style_mask` | True | `allowed_style_mask` 永久全开放 | StrategySelector.select() 入口 |
| 战略层 子 4 | `enable_five_domain_cross_asset` | True | 三类资产相关性约束（×0.5/×0.8）旁路 | `_war_state_should_skip` 外层 |
| 策略层 总 | `enable_strategy_layer` | **False** | `StrategySelection()` 默认空值；所有 SL/TP/exit_config/style 覆盖 = None；_open_position 不叠加；ExitContext 新字段全 None → R1 提供完全向后兼容 | §2.6 `_open_position` 战略层 gate 之后：`if getattr(self, "enable_strategy_layer", False): _sel = _select_strategy(...) else: _sel = StrategySelection()` |
| 策略层 子 1 | `enable_strategy_exit_config` | True（总开后生效） | ExitStrategy 三级 fallback 跳过 exit_config / strategy_type 分支 → 只用 base 阈值 | §2.4 各 ExitStrategy.evaluate() 入口（或更简洁：构造 ExitContext 前把 `exit_config={}`, `strategy_type=None` 覆盖空） |
| 策略层 子 2 | `enable_strategy_style_exposures` | True | `style_exposures` 强制 `{trend_follow:1.0}`；G9 聚类约束 不计算 | StrategySelector._build_selection() 末尾 + G9 聚类入口 |
| 策略层 子 3 | `enable_strategy_risk_budget_sizing` | True | §2.6 风险预算 ATR sizing 块 全跳过 → 保留 risk/p2 之后的旧 sizing | §2.6 `_open_position` 内 sizing 块最外层 |
| 模式 1 影子 AB | `enable_strategy_shadow_mode` | **False** | 真实链路等价「两总全关」；战略+策略层并行跑，结果写独立 `strategy_shadow_records` 表，不执行 | polling_trader.py run_once 结尾新增 shadow 分支 |
| 模式 2 自动晋升 | `enable_strategy_auto_promote` | False | Shadow 连续 N 周跑赢双基线（静态=v15 / 动态=当前最优）→ 提交 promote | `_evaluate_promote_candidate()` 新增（与前置层 RolloutManager 对齐） |
| 模式 3 Dream OS | `enable_external_orchestration` | False | 开关状态只读 Dream OS 配置文件（300s 热加载），忽略 CLI/env | `_reload_switches_from_config()` 新增（复用 `_enable_inject_runtime` 的 300s 机制） |

### 9.2 四层降级回退链路（Layer 0 → Layer 3）

```
CLI --no-five-domain / --no-strategy-layer       # Layer 0：进程级强制关断（最高优先）
         ↓
.env ENABLE_FIVE_DOMAIN / ENABLE_STRATEGY_LAYER  # Layer 1：默认配置
         ↓
运行时文件 runtime/strategy_switches.yaml（300s 热加载）  # Layer 2：Dream OS / 人工动态调
         ↓
单组件 try/except → 降级默认值（最后保险）         # Layer 3
  _compute_five_domain_scores() 异常 → {dao:70, tian:70, di:70, jiang:80, fa:75}
  StrategySelector.select() 异常 → StrategySelection() 默认值
  _apply_regime_vol_cap() 异常 → 返回原值（不收紧）
  ExitStrategy 读 exit_config 异常 → 回 strategy_type → 回 base_threshold
  历史持仓缺 strategy_type → behavior = 100% 等价改造前
```

### 9.3 v1.1 代码清单的 4 处 gate 补充（§13.2 修正 1–4 精简落位）

| 编号 | 原代码（v1.1） | 补充 gate（v1.2） |
|---|---|---|
| ① 策略层入口（§2.6 `_open_position`） | 直接调用 `_compute_five_domain_scores` + `_select_strategy` | 外层加 `if enable_five_domain:` / `if enable_strategy_layer:`；关断时 `_scores=None` + `_sel=StrategySelection()` |
| ② 五计打分函数（§2.6 `_compute_five_domain_scores`） | 直接进入打分逻辑 | 函数首行：`if not enable_five_domain: return {dao:70, tian:70, di:70, jiang:80, fa:75}`（关断时不能返回低分，避免误触发不出战） |
| ③ ExitStrategy 差异化离场（§2.4） | `exit_config → strategy_type → base` 三级 fallback | 更简洁：构造 ExitContext 前若 `enable_strategy_exit_config=false`，把 `exit_config={}` 和 `strategy_type=None` 覆盖空；利用 R1 Optional=None 天然兼容，无需改每个策略 |
| ④ 影子 AB 记录 | （v1.1 未列入） | 复用 ShadowLogger 存储框架，新增 `strategy_shadow_records` 独立表（schema v2：ts/coin/war_state_real_vs_shadow/five_scores_shadow/strategy_real_vs_shadow/style_exp_shadow/sl_mult_shadow/risk_budget_shadow/exit_config_shadow/decision_real_vs_shadow）。冷启动先开影子 2-4 周，再 promote。 |

### 9.4 关断矩阵（5 场景验证，冷启动=场景 1 最安全）

| 场景 | `enable_five_domain` | `enable_strategy_layer` | 其他模式 | 系统行为 | 等价改造前？ |
|---|---|---|---|---|---|
| **场景 1（冷启动默认）** | False | False | — | 战略+策略 100% 旁路；所有新增字段 None；ExitStrategy 全部退回 base 阈值链 | ✅ **完全等价** |
| **场景 2（只测战略）** | True | False | — | 只在开仓层面加「不出战/仓位 cap/跨类约束」；单笔入离场参数（SL/TP/Timeout/EV 阈值）完全不动 | ⚠️ 非等价但安全（只多一层过滤，不改变单笔规则） |
| **场景 3（只测策略）** | False | True | — | 五计分默认 72.75（不出战不触发）；策略层按 regime → strategy_type + 差异化 exit + 风险预算 sizing；不被战略层拦截 | ⚠️ 非等价但可观测（单笔规则变，但不被战略拦截） |
| **场景 4（先影子 AB）** | False | False | shadow=True | 真实链路=场景 1（完全等价现状）；影子链路并行跑战略+策略，结果写 strategy_shadow_records 表不执行 | ✅ **真实链路完全等价**（仅观测） |
| **场景 5（全开+归因）** | True | True | 子开关逐个 toggle | 可独立验证：不出战机制贡献 / 差异化离场贡献 / 风险预算 sizing 贡献 / 聚类约束贡献 / 跨类约束 等子模块的 Alpha / 夏普 / 回撤差异 | 不追求等价，追求归因 |

### 9.5 渐进上线路径（安全优先）

```
Step 0：代码合并前 → 确保 28 项路径 A 测试 + 8 项路径 B 测试 全过（含 gate 关断场景）
Step 1：实盘部署 → 默认两总开关全 False → 先观察至少 2 天，确保字节等价不影响现有稳定收益
Step 2：开 `enable_strategy_shadow_mode=True` → 影子跑 2–4 周，每周出《影子 vs 真实》归因对比报表
Step 3（影子优于双基线才走）：先开 `enable_strategy_layer=True` + `子开关逐个开`：
          → 先开 exit_config（差异化离场 G6） → 稳定 3 天 → 再开 risk_budget_sizing（G2）
          → 稳定 3 天 → 最后开 style_exposures（G1 + 聚类 G9，路径 B）
Step 4：策略层稳定至少 1 周后，再开 `enable_five_domain=True` + 子开关：
          → 先 position_cap（仓位映射） → 稳定 → 再 style_mask → 稳定 → 再 war_state（不出战机制）
          → 最后 cross_asset（三类相关性约束）
Step 5：稳定至少 2 周，夏普不下降 / 最大回撤改善 ≥10% → `enable_strategy_auto_promote=True` 进入自动晋升
```

---

## 十、v1.4 架构升级：纯参数校准算法层 + 大-中-小周期弹性约束（默认推荐）代码结构落位

> **定位变更两步走（v1.2 → v1.3 → v1.4 核心）**：① v1.3 完成策略层内部升级：`exit_config` 查表路由 → 统一 `calibration_biases`（8 数值 + 1 gate）单级乘法；② **v1.4 完成战略层-前置层边界校正**：战略层→前置层从「精确 L_factor/T_factor 乘法校准（方案 A，不推荐）」→「弹性约束闸门 + 偏差带宽 clip（方案 B，默认推荐）」。战略层只做三件事：① veto 闸门 ② 偏差带宽 ③ 策略 mask；绝不修改前置层形态学内部公式参数。对齐桥水 Dalio PMPT / AQR Style Premia / 国泰海通 SAA-TAA / QuantKernel / RegimeAwareML / 人大双层决策 6 大行业范式。

### 10.1 核心数据结构替换（StrategySelection → 新增 front_layer_band，替代 v1.3 front_layer_calibration）

```python
# bcrm2/strategy_algorithm_layer.py （★ 重命名文件，替换原 strategy_selector.py）

@dataclass
class StrategySelection:
    """v1.4 输出。R1 所有 Optional 默认 None/全带宽 → 100% 向后兼容（关断=零影响）。"""
    # 保留（v1.3 不变，R2 一次性绑定，G9 聚类用）
    strategy_type: str = "trend_follow"                     # 主风格标签（仅作校准算法分类特征 / G9聚类 / R4 RankedTp gate，不再作参数路由 key）
    style_exposures: Dict[str, float] = field(default_factory=lambda: {"trend_follow": 1.0})  # G1/G3 权重向量（不变）
    position_mult: float = 1.0                               # emergency 应急收紧（不变）
    risk_budget_pct: float = 1.0                             # G2 风险预算 sizing 主入口（不变）
    enable_ranked_tp_allow: bool = True                      # R4 RankedTp allow-gate（不变）
    liquidity_tier: str = "HIGH"                             # §4.12.3 #6 流动性分层（不变）
    strategy_version: str = "salv1.4"                        # R2 版本（v1.3→v1.4 升级）
    # ★ 删除 v1.2 的 sl_mult_override / tp_mult_override / exit_config（不再直接输出阈值或查表路由）
    # ★ v1.3 新增：统一结构校准偏置（全部乘法系数，1.0=无改动）——v1.4 不变
    calibration_biases: Optional[Dict[str, float]] = None    # R1 Optional：None 时全部取 1.0（默认值实现）
    # calibration_biases schema（统一 8 数值 + 1 布尔 gate，不区分策略类型）：
    # {
    #   "sl_mult_factor": 1.0, "tp_mult_factor": 1.0,
    #   "min_holding_hours_factor": 1.0,  # 新增：最低持仓保护系数（Timeout策略）
    #   "reverse_confidence_factor": 1.0,  # SignalReverse base × 系数
    #   "ev_force_factor": 1.0, "ev_warn_factor": 1.0,
    #   "timeout_hours_factor": 1.0,       # 0.0 = 跳过 Timeout（等价 timeout_skip）
    #   "risk_budget_factor": 1.0,
    #   "enable_chandelier_gate": False     # 仅一个布尔 gate（=trend_follow 时 True）
    # }
    # ★ v1.4 变更（方案 B，默认推荐）：战略层→前置层从「精确乘法校准」→「弹性偏差带宽」
    # （替代 v1.3 front_layer_calibration：{"L_factor":1.0, "T_factor":1.0} 乘法系数）
    front_layer_band: Optional[Dict[str, float]] = None      # Optional=None → 默认全带宽[0,1]等价无约束
    # front_layer_band schema（允许范围，只 clip 不乘系数）：
    # {
    #   "L_min": 0.40, "L_max": 0.90,     # L_effective 允许的 min/max 范围
    #   "T_min": 0.40, "T_max": 0.90,     # T_effective 允许的 min/max 范围
    #   "sector_weights_min": 0.80,        # 板块权重 × 允许最小倍数（相对原值）
    #   "sector_weights_max": 1.20         # 板块权重 × 允许最大倍数（相对原值）
    # }
    # ⚠️ v1.3 front_layer_calibration（乘法系数方案）标记为「历史备选方案 A」，不推荐落地
```

### 10.2 校准算法流程（统一公式，G6=Seed → 二次校准；新增 front_layer_band 生成）

```python
class StrategyAlgorithmLayer:
    """v1.4：策略标签/regime/五计分 → 统一校准偏置向量 + 前置层偏差带宽。"""

    # G6：从「参数路由表」→「6 组 Seed 初始校准偏置」（行数不变，语义变；v1.3→v1.4 不变）
    G6_SEED_TABLE = {
        "trend_follow": {"sl_mult_factor":1.10, "tp_mult_factor":1.80,
                         "min_holding_hours_factor":1.30, "reverse_confidence_factor":1.05,
                         "ev_force_factor":1.15, "ev_warn_factor":1.10,
                         "timeout_hours_factor":0.00,  # 0 = gate 跳过
                         "risk_budget_factor":1.20,
                         "enable_chandelier_gate": True},
        "breakout":     {"sl_mult_factor":0.90, "tp_mult_factor":1.00,
                         "min_holding_hours_factor":0.90, "reverse_confidence_factor":0.85,
                         "ev_force_factor":0.90, "ev_warn_factor":0.90,
                         "timeout_hours_factor":1.00, "risk_budget_factor":1.00,
                         "enable_chandelier_gate": False},
        # mean_revert / momentum / volatility / emergency 同理（同 §十四.4 方案 B Seed 表）
    }

    # ★ v1.4 新增：战略层带宽 seed 映射表（同 §15.4，从庙算状态→带宽范围，不是乘系数）
    FRONT_BAND_RULES = [
        # (match_condition → L_band, T_band, sector_band)；按顺序匹配第一条命中
        (lambda s: (s.get("dao",0)>=80 and s.get("di",0)>=75),
            (0.55, 0.98), (0.55, 0.98), (0.90, 1.20)),  # 三击：最宽带宽
        (lambda s: _total_score(s) >= 75,
            (0.50, 0.95), (0.50, 0.95), (0.85, 1.15)),  # 正常开战：宽
        (lambda s: _total_score(s) >= 60,
            (0.45, 0.85), (0.45, 0.85), (0.85, 1.15)),  # 防御：中带宽
        (lambda s: (s.get("dao",0)<40 or s.get("jiang",0)<40),
            (0.35, 0.70), (0.35, 0.70), (0.80, 1.10)),  # 维度否决：最严带宽
        (lambda s: s.get("tian",0)<40,
            (0.40, 0.80), (0.40, 0.80), (0.80, 1.10)),  # 天时极差：收紧带宽
        # 最后一条默认（总分<60 但没被不出战 veto 挡住的边缘情况）
        (lambda s: True,
            (0.40, 0.85), (0.40, 0.85), (0.80, 1.10)),
    ]

    def _apply_secondary_calibration(self, seed: Dict, five_scores: Dict, regime: str,
                                     liquidity_tier: str) -> Dict:
        """★ 统一二次校准公式（v1.3→v1.4 不变，所有策略类型共用）：
        1. 庙算总分线性缩放 factor（min 0.70 / max 1.30）；
        2. regime 平滑偏移（TREND_STRONG 再 × 趋势友好 1.05 等）；
        3. liquidity_tier 收紧因子（LOW 流动性低风险项 × 0.85）；
        4. clip 到 ±30%/50% 硬约束（避免极端跳变）。
        """
        total = five_scores["dao"]*0.30 + five_scores["tian"]*0.15 + five_scores["di"]*0.25 + \
                five_scores["jiang"]*0.15 + five_scores["fa"]*0.15
        score_factor = max(0.70, min(1.30, 0.70 + (total/100.0)*0.60))  # 0分→0.7, 100分→1.3
        regime_shift = self._regime_shift_table(regime)
        liq_factor = 1.0 if liquidity_tier == "HIGH" else (0.92 if liquidity_tier == "MID" else 0.85)

        out = dict(seed)
        for k, v in seed.items():
            if k == "enable_chandelier_gate":  # 布尔 gate 不参与乘法校准
                continue
            out[k] = float(np.clip(v * score_factor * regime_shift.get(k, 1.0) * liq_factor, 0.30, 2.00))
        return out

    def _compute_front_layer_band(self, five_scores: Dict) -> Optional[Dict]:
        """★ v1.4 新增：前置层偏差带宽（不是乘系数，是允许范围 clip 上下限）。
        子开关关断 / 异常时返回 None（等价无约束）。"""
        if not self._cfg.enable_five_domain_front_layer_band:  # 独立子开关 gate
            return None
        try:
            for rule_match, (L_min, L_max), (T_min, T_max), (s_min, s_max) in self.FRONT_BAND_RULES:
                if rule_match(five_scores):
                    return {"L_min": L_min, "L_max": L_max,
                            "T_min": T_min, "T_max": T_max,
                            "sector_weights_min": s_min, "sector_weights_max": s_max}
        except Exception:  # fail-open：任何异常→None等价无带宽
            return None
        return None  # 理论上不会走到（默认规则兜底）

    def select(self, scores, enhance_result, direction, confidence,
               liquidity_tier="HIGH",
               asset_class: str = "crypto_usdt",          # ★ v1.4.1 新增：按资产类别选约束
               five_domain_state: Optional[Dict] = None):  # ★ v1.4.1 新增：战略层按类快照（含 war_state / style_mask / aggregate_cap / cross_mult 等）
        """v1.4.1：所有战略层消费点必须通过 asset_class 按类取独立值。
        scores = five_scores[asset_class]（已经按类拆分，不是全局值）。"""
        # 0. ★ v1.4.1 按类 allowed_style_mask 过滤（如果关断则等价全 True，fail-open）
        if five_domain_state and getattr(self._cfg, "enable_five_domain_style_mask", True):
            mask = (five_domain_state.get("allowed_style_mask") or {}).get(asset_class, {})
            self._style_allowlist = {k: mask.get(k, True) for k in self._ALL_STYLES}
        else:
            self._style_allowlist = {k: True for k in self._ALL_STYLES}  # fail-open 全开放

        # ① 策略标签选择（主风格）：v1.2/v1.3 路由逻辑不变，但是经过 allowlist 过滤
        main_type, exposures = self._select_main_style_and_weights(scores, enhance_result)
        # ② 查 G6 Seed 表（仅初始偏置，不是最终阈值）
        seed = dict(self.G6_SEED_TABLE.get(main_type, self.G6_SEED_TABLE["trend_follow"]))
        # ③ 统一二次校准（核心算法层，所有策略共用一套公式）
        biases = self._apply_secondary_calibration(seed, scores, enhance_result.get("regime","CHOPPY"), liquidity_tier)
        # ④ ★ v1.4 变更：战略层 → 前置层偏差带宽（★ v1.4.1 通过 asset_class 从 five_domain_state.front_layer_band[cls] 取独立带宽）
        if five_domain_state and (five_domain_state.get("front_layer_band") or {}).get(asset_class):
            front_band = five_domain_state["front_layer_band"][asset_class]
        else:
            front_band = self._compute_front_layer_band(scores)  # 兼容路径：无快照时退化到单类规则表
        # ⑤ 组装最终 Selection（StrategySelection 本身是单笔持仓绑定，R2 一次性不可变——不变更内部字段结构）
        return StrategySelection(
            strategy_type=main_type, style_exposures=exposures,
            risk_budget_pct=self._scale_risk_budget(scores, seed.get("risk_budget_factor",1.0), biases["risk_budget_factor"]),
            enable_ranked_tp_allow=(main_type not in ("trend_follow", "volatility")),  # R4 直接映射
            calibration_biases=biases, front_layer_band=front_band,  # v1.4: front_layer_band
            strategy_version="salv1.4.1",  # v1.4.1 版本号
        )
```

### 10.3 ExitStrategy 改造：删除三级 fallback，统一 base × calibration_factor 单级

```python
# bcrm2/exit_strategies.py  （6 个 ExitStrategy 做同样的结构改造，示例以 SignalReverseStrategy 为例）
# 注意：本节 v1.3 → v1.4 **完全不变**，离场逻辑与战略层带宽是严格解耦的两个正交方向。

class SignalReverseStrategy(ExitStrategy):
    """v1.3/v1.4：BASE_THRESHOLDS 一套基准 + calibration_biases.reverse_confidence_factor 单级乘法。
    ★ 删除 v1.2 的 exit_config lookup / strategy_type 分支 / 三级 fallback 代码。"""
    enabled: bool = True
    priority: int = 20

    # ★ 核心深度研发资产：一套全局基准阈值（不区分策略类型），所有差异化通过校准系数叠加
    BASE_THRESHOLDS = {
        "base_threshold": 0.70,        # v1.2 硬编码在 self.base_threshold（统一收敛到 dataclass-like 表）
        "protected_conf_boost": 0.05,
        "protected_min_threshold": 0.65,
    }

    def _effective_base(self, exit_ctx: ExitContext) -> float:
        base = self.BASE_THRESHOLDS["base_threshold"]
        # ★ v1.3：单级乘法（校准偏置），无任何查表/分支 → 复杂度 O(1)
        if exit_ctx.calibration_biases and "reverse_confidence_factor" in exit_ctx.calibration_biases:
            base = base * float(exit_ctx.calibration_biases["reverse_confidence_factor"])
        if exit_ctx.in_protection_mode:
            base = max(base + self.BASE_THRESHOLDS["protected_conf_boost"],
                       self.BASE_THRESHOLDS["protected_min_threshold"])
        return base

    def evaluate(self, exit_ctx: ExitContext) -> ExitDecision:
        # evaluate 逻辑完全不变，唯一变化：上面的 _effective_base 从三级 fallback → 单级乘法
        ...
```

> **其他 5 个 ExitStrategy 改造要点（一一对应，v1.3→v1.4 不变）**：
> - `EvForceCloseStrategy` → `force_below = BASE["force_below"] × calibration_biases.ev_force_factor`
> - `EvAdjustStrategy` → `warn_lower/warn_upper = BASE × ev_warn_factor`；`strong_above = BASE × 1.0`
> - `TimeoutProfitSwitchStrategy` → `effective_timeout_hours = BASE["timeout_hours"] × max(0.0, calibration_biases.timeout_hours_factor)`；★ **新增 gate：`effective_timeout_hours <= 0 → 直接 pass_()`（等价 v1.2 `timeout_skip: True`）**
> - `P3EarlyExitStrategy` → `threshold = BASE["p3_threshold"] × calibration_biases.sl_mult_factor`（SL 更严格 → P3 更早触发）
> - `EvAdjustStrategy` → 同上。**新增最低持仓保护 gate：`holding_hours < BASE.min_holding_hours × calibration_biases.min_holding_hours_factor → 跳过 Timeout / Signal 类退出，只允许 Ev 类强平 / 超紧急退出`**（用户「最低持仓时间优化」诉求正式落位）
> - `ChandelierExitStrategy`（G7）→ ★ **直接读 calibration_biases.enable_chandelier_gate：False → enabled 立即关闭**，不做任何计算（等价 v1.2 `use_chandelier_exit: False`，但通过布尔 gate 直接映射，不需要 exit_config 查表）

### 10.4 开关架构扩展（子开关语义升级：calibration → band）

| 层级 | 开关 | v1.3 名（v1.4 状态） | v1.4 变更 | 默认 |
|---|---|---|---|---|
| 战略层 子 5（§十五校正） | `enable_five_domain_front_layer_band` | `enable_five_domain_front_layer_calibration`（旧名，方案 A） | ⚠️ **重命名+语义升级**：从「战略层精确乘法校准前置层参数」（方案 A）→「战略层给前置层偏差带宽 clip」（方案 B，默认推荐）。关断=front_layer_band=None→clip 全不做 | **False**（冷启动保守） |
| 策略层 子 1 | `enable_strategy_calibration_layer` | 不变 | 不变 | True |
| 其他 2 总 + 策略层子 2/3 + 3 模式 | 不变 | 复用 | 无改动 | 同 v1.2 |

---

*本文档为改造方案设计，不含代码落地。方案版本 **v1.4.1**，已根据《孙子五维度评估》**§4.11–§4.13 + §11–§13 + §十四 策略算法层定位评估 + §十五 大-中-小周期关系校正 + §一&§5.3 按类独立输出一致性补丁** 完成五轮全面校正。默认推荐方案 **B：纯参数校准算法层 + 弹性带宽约束 + 按资产类独立 gate**（v1.4.1 落位）。v1.2「参数路由表模式（备选方案 A）」与 v1.3「front_layer_calibration 精确乘法校准（历史备选）」保留但不推荐，如需对比基线可参考，但长期应迁移到 v1.4.1。

版本核心里程碑：
- **v1.0（2026-08-21）**：初稿路径 A/B。
- **v1.1（2026-08-21）**：+ 架构冲突校正 R1–R7 + 传统金融 7+1 + GitHub G1–G10。
- **v1.2（2026-08-21）**：+ 模块化开关（2总+7子+3模式）+ 4 层降级 + 5 关断矩阵 + Dream OS 接入。
- **v1.3（2026-08-21）**：**架构定位升级 → 策略校准算法层（方案 B）**：统一 `calibration_biases` 替代 exit_config 查表路由；ExitStrategy 单级乘法替代三级 fallback；G6 变 Seed 表；新增战略层→前置层校准 F1–F4；符合 Turtle/CTA/RegimeSense/QuantPulse/风险平价 6 大行业范式，离场研发与策略类型数彻底解耦。
- **v1.4（2026-08-21）**：**大-中-小周期弹性约束校正（用户核心洞察）**：战略层→前置层从精确乘法校准→弹性偏差带宽 clip；战略层显式做三件事（veto 闸门/带宽范围/策略 mask），绝不修改前置层形态学公式参数；对齐桥水 Dalio PMPT Beta/Alpha 严格分离、国泰海通 SAA/TAA ±5-15% 偏差带宽治理、AQR 因子区间、QuantKernel RegimeGate 不改参数、RegimeAwareML 只做 gating、人大双层 clip 6 大行业范式；代码量从 ~30 行乘法降到 ~6 行 clip；消除信号打架与时间粒度错位问题。
- **v1.4.1（2026-08-21，★ 当前推荐）**：**按资产类别独立输出一致性补丁**（响应用户「五计 6 个核心问题 + §5.3 三类不出战互相独立」的落地要求）：战略层所有 gate/带宽/评分从全局值升级为按三类资产（crypto_usdt / us_stock / precious_metal）独立 Dict；select() 接口新增 asset_class + five_domain_state 参数；aggregate_cap / war_state / style_mask / forced_close_flags / position_mult 全部按 cls 取独立值——加密熊市 FREEZE 完全不阻止美股开仓，美股高分牛市不推高黄金的仓位 cap。ExitStrategy 单级乘法逻辑（v1.4 核心资产）0 改动，零 breaking-change。

路径 A 改动量：v1.4.1 **~792 行**（删除旧查表/降级/乘法代码约 124 行，替换为校准算法+统一阈值乘法+front_band clip+按类接口约 116 行，净增约 -8 行）；路径 B **~300 行**（不变）；路径 A 测试从 v1.3 38 项 → v1.4 **39 项** → v1.4.1 **41 项**（净增 2 项：三类资产 gate 独立互不干扰 1；aggregate_cap 按类取 min 约束单调性 1）。架构保证：ExitManager 实盘 5 策略链、RankedTp 独立循环、TradeRecord 白名单恢复机制、polling_trader.py L534 `enable_*` 开关体系 **100% 一致，零 breaking-change。**
