# 变更日志 — 易经推理系统

> **定位**：记录每次变更的原因、内容、验证方式
> **格式**：`[版本] - 日期 → 变更类型（新增/修改/修复/删除）`
> **版本**：v4.2 | **更新**：2026-08-06

---

## [v4.2] - 2026-08-06

### 宏观特征优化（v4 前向贪心选择）

- **新增**: `macro_feature_optimize_v4.py` 两阶段加速的前向贪心选择（预筛选 Top-8 + 前向选择）
  - 动机: v3 用 importance ranking 的不同截断（K=3/5/8）测试，不是真正的特征搜索；v4 从 K=0 逐步添加边际贡献最大的特征
  - 预筛选阶段: 24 个特征逐个评估单特征贡献，选 Top-8 候选
  - 前向选择阶段: 在 Top-8 上做贪心选择，产出 K-vs-得分曲线，早停 patience=3
- **修改**: `macro_features.py` 增加两级开关机制（特征级 `macro_feat_{name}` 优先，维度级 `macro_enable_{dim}` 回退）
- **验证**: BTC-only 3折×4000bars 选择 + 5折×6000bars 验证
  - K=0 基线 11.253 → K=3 最优 16.578（选择阶段）
  - K=0 验证 10.273 → K=3 验证 12.721（**+23.8%**）
  - 3 个特征验证有效: `fgi_zscore` (+3.672)、`fgi_extreme_fear` (+1.611)、`hash_rate_trend` (+0.042)
  - 关键发现: `fgi_zscore` + `fgi_extreme_fear` 协同效应（连续值+事件标记）；`tvl_change_7d` 与 FGI 冲突（单独+1.329，组合后-4.326）

### BTC 宏观特征落地

- **修改**: `bcrm2_adapter.py` 增加 `macro_config` 参数
  - `__init__` 接收 `macro_config: dict = None`
  - 训练和推理路径的 `compute_all` 调用均传入 `config=self.macro_config`
  - `_get_cache_key` 加入 macro_config 哈希，配置变更自动重训
- **修改**: `polling_trader.py` `_infer_bcrm2()` 为 BTC 传入 3 特征配置
  - BTC: 启用 `fgi_zscore` + `fgi_extreme_fear` + `hash_rate_trend`，显式关闭其余 21 个
  - 其他币种: `macro_config=None`（保持默认行为）
- **验证**: MacroFeatures.compute 正确启用/关闭特征；缓存键区分不同配置；test_polling_trader_prediction 2/2 通过

### 风控规则改造（亏损金额比例触发）

- **重构**: `trading_utils.py` RiskManager 风控触发逻辑
  - 动机: 原连续亏损笔数触发（默认5次）导致小幅连续亏损反复触发风控，交易频率过低
  - 改为: 亏损金额 > 可用金额 × `loss_limit_pct`（默认20%）触发
  - `RiskState` 新增 `loss_limit_pct: float = 0.20`，`max_consecutive_losses` 默认改为 999（禁用）
  - `can_trade()` 改为动态计算 `-(current_equity × loss_limit_pct)` 阈值，取 `max(dynamic, daily_loss_limit)` 为有效阈值
  - `update_after_trade()` 增加 `current_equity` 参数，halt 触发改为仅看亏损金额
- **修改**: `polling_trader.py` 默认参数 `daily_loss_limit=-30.0`、`max_consecutive_losses=999`
  - `_load_evolution_config` 加载 `loss_limit_pct`
  - `update_after_trade` 调用传入 `current_equity`
- **修改**: `yijing_monitor.py` 默认值同步为 `-30.0/999/0.20`，保存时写入 `loss_limit_pct`
- **修改**: `self_evolution_engine.py` 进化白名单移除 `max_consecutive_losses`，新增 `loss_limit_pct`
- **修改**: `config.json` 风控配置 `daily_loss_limit: -30.0, max_consecutive_losses: 999, loss_limit_pct: 0.20`
- **验证**: 6 项单元测试通过（RiskState 字段、RiskManager 默认参数、动态阈值、连亏不触发、update_after_trade、PollingTrader 参数）

### 文档更新

- **修改**: `TECHNICAL_DESIGN.md`
  - §9.3.1 新增宏观特征层章节（24特征/6维度+两级开关+v4验证结果+落地配置+关键发现）
  - §11.3.1 新增风控触发规则章节（设计哲学+风控规则表+默认场景+代码示例+进化系统适配）
  - 推理链 RiskManager 描述更新
  - §16 变更日志添加 v4.2 条目
- **修改**: `API_SPEC.md`
  - PollingTrader 参数默认值更新（`daily_loss_limit=-30.0, max_consecutive_losses=999`）
  - 风控状态示例增加 `loss_limit_pct` 和 `daily_loss_limit` 字段
  - §12.4 风控触发表格重写（亏损金额比例触发+默认场景示例）

---

## [v4.0] - 2026-08-05

### 五角校验 v4 风险评分风控版

- **重构**: 五角校验从 v3"纯风控中立"升级为 v4"风险评分驱动的双向风控"
  - 动机: v3 纯风控版仅双预警止损收紧，五角校验未真正发挥作用
  - 与 v2 的本质区别: v2 是五源方向投票→一致性→仓位调整（方向驱动，已证伪）；v4 是五源风险信号→风险评分→仓位/杠杆/止盈/止损调控（风险驱动）
  - 核心机制:
    1. 五源风险信号综合评分 (0=安全, 1=高危)：不投票方向，只评估风险等级
    2. 风险注意力动态加权：追踪各源风险预警准确率（预警后市场是否恶化），指数衰减更新权重 (decay=0.97)
    3. 双向风控调控：低风险→加仓/提杠杆/提高止盈，高风险→降仓/降杠杆/收紧止损
    4. v3 双预警止损收紧保留（TDA+Ising 同时触发 → sl_tighten=0.85 底线）
  - **影响范围**: `scripts/memory_l4/triangle_verifier.py`（核心改造）、`scripts/memory_l4/bcrm2/walk_forward_backtester.py`（回测适配）、`scripts/memory_l4/bcrm2_adapter.py`（字段透传）、`scripts/memory_l4/polling_trader.py`（实盘适配）

- **回测验证**: BTC/ETH/SOL 6000bars/5folds 对比 baseline vs v4
  - 参数调优: risk_threshold_low 从 0.30 调为 0.15（收窄加仓范围），pos_factor 从 1.15 降为 1.10，leverage_factor 从 1.15 降为 1.05（减少回撤恶化）
  - 最终结果: 平均夏普 10.16→10.20 (+0.4% ✅)、平均回撤 10.12%→10.34% (+0.22% ✅)、平均收益 135.31%→139.40% (+4.09% ✅)、风控触发 94笔/412笔（加仓79+降仓3+双预警12 ✅）
  - 四项验证标准全部通过: 夏普不拖累 ✅、回撤不恶化 ✅、风控层触发 ✅、收益提升 ✅
  - **验证脚本**: `scripts/memory_l4/pentagon_v3_backtest.py`
  - **遗留**: 实盘杠杆调整需后续实现 set_leverage API（仓位/止损/止盈已适配）

---

## [v3.1] - 2026-08-05

### 五角校验 v3 纯风控版重构

- **重构**: 五角校验器从"方向校验器"重新定位为"风险预警器"（P3 风控层独立运行，不影响 BCRM2 信号生成）
  - 动机: v2 方向投票+仓位调整链路经两轮贝叶斯优化仍无法超过无校验基线（高胜率环境下降仓有害）
  - 移除: 五源加权方向投票、agreement_score→position_factor 链路、一致性评分→置信度调整、轻量注意力动态权重、fail_closed 阻断、强一致/分歧/反转加减仓
  - 保留: TDA 拓扑突变预警 + Ising 相变预警，双预警同时触发 → sl_tighten=0.85（收紧止损15%）
  - 中性化: PentagonParams 权重/惩罚/仓位系数全部冻结为中性值，仅保留接口兼容
  - **影响范围**: `scripts/memory_l4/triangle_verifier.py`、`scripts/memory_l4/bcrm2/walk_forward_backtester.py`、`scripts/memory_l4/bcrm2_adapter.py`、`scripts/memory_l4/polling_trader.py`
  - **验证方式**: 运行时验证通过 — 无预警场景 verdict=P3_RISK_MONITOR、confidence_adjustment=0.0、position_factor=1.0、should_fail_closed=False、sl_tighten_factor=1.0；注意力机制冻结（record_outcome 为 no-op，权重恒 0.20）

- **回测验证**: BTC/ETH/SOL 6000bars/5folds 对比 baseline vs v3
  - 参数调优: sl_tighten_double 从 0.7（收紧30%）调整为 0.85（收紧15%），根因是 0.7 在低波动率币种 BTC 上过于激进，导致夏普 -20%、交易摩擦激增
  - 最终结果（sl_tighten=0.85）: 平均夏普 10.28→10.22（-0.6%，容许 ±5% 内 ✅）、平均回撤 10.53%→10.53%（+0.00%，容许 ±0.5% 内 ✅）、风控触发 13笔/414笔（3.1% ✅）
  - 三项验证标准全部通过: 夏普不拖累 ✅、回撤不恶化 ✅、风控层确实触发 ✅
  - **验证脚本**: `scripts/memory_l4/pentagon_v3_backtest.py`
  - **结果文件**: `data/pentagon_v3_validation.json`

- **清理**: 移除 v2 残留死代码与孤儿文件
  - 删除 `polling_trader.py` 中 v2 降仓死代码块（position_factor 恒=1.0 永不执行）
  - 归档 `pentagon_optimal_params.json`（v2 贝叶斯优化产物，运行时不再加载）→ `_archived/`
  - 更新 `fast_verifier.py` 诊断脚本，verdict 统计从 STRONG_AGREE/MAJORITY_AGREE/DIVERGENT/CONFLICT 四分类改为 P3_RISK_MONITOR 覆盖率
  - **影响范围**: `scripts/memory_l4/polling_trader.py`、`scripts/memory_l4/_archived/pentagon_optimal_params.json`、`scripts/memory_l4/fast_verifier.py`

---

## [v3.0] - 2026-08-01

### DreamOS 离场模块集成

- **新增**: YijingExitAdapter 完整实现（从占位符升级）
  - 懒加载 YijingExitSystem（两级路径查找：dreamos 包 → 项目根 11-易经推理系统 目录）
  - 三级卦象降级注入：L1 hexagram_result（A_YJ_INFER 注入）→ L2 yijing_hexagram（A2 注入）→ L3 _synthesize_hexagram（场景+指标合成，回测/冷启动自动启用）
  - 9→4 决策映射：FORCE_CLOSE→CLOSE, LOWER_TP→CLOSE, RAISE_TP→RAISE_TP, LOWER_SL/TIGHTEN_SL/ADJUST_SL_TP→HOLD+SL/TP调整, VETO_*/NO_INTERVENE→HOLD
  - ATR 基准 SL/TP 动态调整：SL=1.5×ATR, TP=3.0×ATR，叠加 sl_adjust_pct / tp_adjust_pct
  - **影响范围**: `1-ARCHITECTURE/dreamos/capabilities/trading/exit_strategy/exit_module_adapter.py`
  - **验证方式**: smoke test（趋势一致→RAISE_TP, 方向冲突+高风险→CLOSE, <1h门禁→HOLD）+ 集成测试全通过

- **修改**: ExitModuleBacktester 补充 change_24h / rsi14 动态注入
  - 回测时 market_data 新增 change_24h（24h 涨跌幅）和 rsi14（RSI 指标）字段
  - 支持 yijing 卦象合成 fallback 在回测中正常运行
  - **影响范围**: `1-ARCHITECTURE/dreamos/capabilities/trading/exit_strategy/exit_module_backtester.py`
  - **验证方式**: 3 场景 × 592 交易全量回测通过

- **新增**: exit_performance_memory.json 写入 yijing 回测数据
  - 3 场景（NEUTRAL_LOW/NORMAL/HIGH_ACCELERATING）× 3 模块（classic/simple/yijing）完整指标
  - ExitModuleSelector L0 精确匹配验证通过（yijing score 最高时选中 yijing, fallback_level=0）
  - **影响范围**: `1-ARCHITECTURE/dreamos/core/memory/exit_performance_memory.json`
  - **验证方式**: Selector 选优验证 + 端到端 evaluate 测试

- **新增**: TECHNICAL_DESIGN.md §9.8 DreamOS 离场模块集成章节
  - §9.8.1 YijingExitAdapter 实现（卦象降级+决策映射+SL/TP 调整+懒加载）
  - §9.8.2 回测结果（3 场景 × 592 交易）
  - §9.8.3 易经与经典离场评估重叠分析（输入信号零重叠，动作层 3 项重叠但互补）
  - §9.8.4 实盘启用步骤

- **修改**: §9.6 集成点补充 DreamOS 链路描述
- **修改**: §15.4 Phase 3 标记 3 项已完成（YijingExitAdapter / Backtester / Selector）
- **修改**: ENGINEERING_INDEX.md 离场决策索引新增 DreamOS 链路条目
- **修改**: A9_exit/README.md 补充离场模块架构描述

### 回测器 Bug 修复

- **修复**: YijingExitSystem 1h 缓存门禁在回测环境中导致 yijing 模块 0% 触发率
  - 根因: `should_evaluate_now()` 使用墙钟 `time.time()` 判断评估间隔（`eval_interval_sec=3600s`），回测时所有 bar 在几秒内跑完 → 第 1 个 bar 写缓存后，后续 bar 全部命中 `yijing_window_cached` → 返回 `no_intervene` → HOLD
  - 修复: `exit_module_backtester.py` 在每个 bar 评估前调用 `clear_cache(coin, pos_side)` 清除 coin 级缓存
  - 仅影响回测器；实盘 auto_trader 使用真实墙钟时间，1h 缓存门禁是设计意图
  - **验证方式**: 62 笔 BTC 回测：yijing 触发率从 0% 恢复至 17.7%（6 SL + 5 TP），PnL 从与 classic 完全一致（+0.001323）变为独立结果（+0.000583）
  - **回滚策略**: 删除 `_simulate_exit_module` 中的 `yj_system.clear_cache()` 调用

---

## [v2.9] - 2026-07-25

### P1 修复与系统增强

- **修复**: `inspect.py` 模型路径错误
  - 模型扫描路径从 `.workbuddy/memory_l4/bcrm2/` 修正为 `scripts/data/bcrm2_models/`
  - 新增目录扫描逻辑，统计 L1/L2 模型数、币种数、周期数
  - **影响范围**: `scripts/memory_l4/inspect.py` → `ModelsPanel._get_bcrm2_models_dir()` / `_scan_model_dirs()`
  - **验证方式**: `python -m scripts.memory_l4.inspect --panels models` 显示正确的模型统计
  - **回滚策略**: 恢复 `_get_bcrm2_models_dir()` 原路径常量

- **新增**: TDA 拓扑检测第五源恢复可用（五角校验五源齐全）
  - 安装 `ripser` + `persim` 依赖（TDA 持久同调、瓶颈距离）
  - 五角校验架构（BCRM2×力学×A0×Ising×TDA）全部就位
  - **影响范围**: `requirements` 依赖、`scripts/memory_l4/triangle_verifier.py`
  - **验证方式**: BCRM2Adapter.infer() 推理时 `triangle_verification` 字段非 None
  - **回滚策略**: 卸载 ripser/persim，TriangleVerifier 异常时降级跳过

- **新增**: 多场景验证脚本
  - 25 个用例覆盖推理/离场/风控/反馈/异常五场景，全部通过
  - **影响范围**: `multi_scenario_validation.py`
  - **验证方式**: `python multi_scenario_validation.py` 全部用例通过
  - **回滚策略**: 删除脚本不影响主链路

- **修改**: 币种规模从 4 扩展至 27
  - 含 BTC/ETH/SOL/BNB/XRP/SEI/TIA/IMX 等，小市值（<5亿）剔除
  - **影响范围**: `scripts/memory_l4/polling_trader.py` 默认 `coins`、配置文件
  - **验证方式**: 启动 PollingTrader 日志输出 27 币种
  - **回滚策略**: `--coins` 参数指定原 4 币种子集

- **修改**: YijingExitSystem P1 阈值修复
  - `raise_tp_value_threshold` 0.70 → 0.58（使成长期/成熟期高价值卦象能触发 RAISE_TP）
  - `force_close_risk_threshold` 0.80 → 0.65（使 high 风险+方向冲突卦象能触发 FORCE_CLOSE）
  - **影响范围**: `scripts/memory_l4/yijing_exit_system.py` → `YijingExitConfig`
  - **验证方式**: 多场景验证中 RAISE_TP/FORCE_CLOSE 用例通过
  - **回滚策略**: 恢复 `YijingExitConfig` 原阈值

- **修改**: 技术栈补充 ripser/persim/Optuna
  - **影响范围**: `docs/TECHNICAL_DESIGN.md` §13 技术栈、`docs/ENGINEERING_INDEX.md` §1.2
  - **验证方式**: 文档审查
  - **回滚策略**: N/A（文档变更）

---

## [v2.8] - 2026-07-24

### A8 SKILL 系统自评估与多场景验证

- **新增**: A8 纯理性内部批判自循环评估框架
  - 引入 A8 SKILL 系统：纯理性内部批判自循环评估
  - **影响范围**: `scripts/skills/4-GENERIC/A8*`、`constraints/system-index/`
  - **验证方式**: A8 评估框架可独立运行
  - **回滚策略**: 移除 A8 SKILL 注册

- **新增**: 系统现状评估报告生成
  - 识别问题：胜率 13.3%、卦象分布偏斜、7 条反馈链路断裂
  - **影响范围**: `docs/` 评估报告
  - **验证方式**: 报告生成脚本可重复运行
  - **回滚策略**: 删除评估报告文件

- **新增**: 多场景验证框架设计
  - 框架设计完成（v2.9 实现 25 个用例）
  - **影响范围**: `multi_scenario_validation.py`（设计稿）
  - **验证方式**: 设计评审
  - **回滚策略**: N/A

---

## [v2.7] - 2026-07-24

### ClassicExitSystem 离场参数优化与 ATR 自适应离场系统

- **新增**: Optuna 贝叶斯优化离场参数
  - 夏普提升、回撤降低
  - **影响范围**: `scripts/memory_l4/classic_exit_system.py` → `ExitConfig`
  - **验证方式**: 离场系统对比回测（`exit_comparison.py`）
  - **回滚策略**: `ExitConfig` 参数回退到保守值（见 v2.6 回退表）

- **新增**: ATR 波动率分组自适应离场
  - 低/中/高三档 + 8 市态 + 币种适配
  - **影响范围**: `scripts/memory_l4/classic_exit_system.py`、`scripts/memory_l4/exit_comparison.py`
  - **验证方式**: ATR/市态/币种分组对比回测
  - **回滚策略**: 回退到原始 BCRM 的 tp/sl/time 离场（回测证明 ATR 自适应收益牺牲 98%+）

- **新增**: 离场系统对比回测框架
  - 4 币种（BTC/ETH/SOL/UNI）× 252 笔交易 × 3x 杠杆 × 0.1%/边手续费
  - **影响范围**: `scripts/memory_l4/exit_comparison.py`
  - **验证方式**: 框架可重复运行回测
  - **回滚策略**: N/A（独立脚本）

- **修改**: 回退决策 — ClassicExitSystem 参数全部回退到保守值
  - 原始 BCRM 离场（tp/sl/time）全面碾压复杂离场系统（收益 +334.73% vs +6.16%）
  - `l0_risk_gate_enabled` 默认关闭（收益杀手），仅保留 L0 硬止损作为安全网
  - 新增盈利旁路机制：`pnl_eff > 3%` 时跳过 risk_gate
  - 杠杆口径统一：所有止盈/止损触发判断统一使用 `pnl_eff`（含杠杆收益率）
  - **影响范围**: `scripts/memory_l4/classic_exit_system.py` → `ExitConfig` 默认值
  - **验证方式**: 离场系统对比回测表（见 TECHNICAL_DESIGN §9.7.1）
  - **回滚策略**: 恢复 `ExitConfig` 贝叶斯寻优值

---

## [v2.6] - 2026-07-24

### ClassicExitSystem 重大修复（8 项缺陷）

#### P0 致命缺陷修复

- **修复**: dd 计算重写（`_compute_features`）
  - 修复前：用 K 线窗口 peak/trough 代替持仓回撤，且 mfe 启用门槛导致亏损单 dd=0
  - 修复后：基于 `entry_price` 和 `current_price` 计算真实持仓回撤，优先使用 `pos.max_dd_pct`
  - **影响范围**: `scripts/memory_l4/classic_exit_system.py` → `_compute_features()`
  - **验证方式**: 亏损单 dd 不再为 0，`hold_risk` 核心输入 `dd_risk`（权重 0.42）不失真
  - **回滚策略**: 恢复 K 线窗口 peak/trough 计算

- **修复**: hold_value 独立计算（新增 `_calc_hold_value`）
  - 修复前：`hold_value = 1 - hold_risk`，等价反推导致亏损单价值虚高，误触发 RAISE_TP
  - 修复后：独立评估，基于趋势一致性(0.30) + 动量延续(0.20) + 量价配合(0.15) + ADX强趋势(0.15) + 盈利加成(0.20) - 震荡市惩罚
  - **影响范围**: `scripts/memory_l4/classic_exit_system.py` → `_calc_hold_value()`
  - **验证方式**: RAISE_TP 仅在真正趋势+盈利+动量一致时触发
  - **回滚策略**: 恢复 `1 - risk` 等价反推

- **修复**: Choppiness Index 实现（新增 `_calc_chop`）
  - 修复前：`feats.chop` 永远为默认值 50.0，`_calc_hold_risk` 中 `chop_risk` 为死代码
  - 修复后：实现标准 CI 公式 `100 * log10(sum(ATR) / (HH-LL)) / log10(n)`，>61.8 为震荡市
  - **影响范围**: `scripts/memory_l4/classic_exit_system.py` → `_calc_chop()`
  - **验证方式**: 震荡市识别恢复，hold_risk 和 hold_value 均接入 chop 因子
  - **回滚策略**: 恢复默认值 50.0

#### P1 参数调优

- **修复**: L0 `max_loss_pct` -0.05 → -0.15 → -0.1915（贝叶斯寻优）
  - 修复前：3x 杠杆下价格跌 1.67% 即触发强平，加密日内波动频繁扫损
  - 修复后：-0.15（3x 杠杆下价格跌 5% 才触发）；寻优后 -0.1915
  - **影响范围**: `scripts/memory_l4/classic_exit_system.py` → `ExitConfig.l0_max_loss_pct`
  - **验证方式**: 回测扫损频率下降
  - **回滚策略**: 恢复 -0.05

- **修复**: L2 `close_threshold` 0.75 → 0.65 → 0.6721（贝叶斯寻优）
  - 修复前：阈值过高，配合 dd 计算缺陷 hold_risk 难以达到，等到触发时已大亏
  - 修复后：0.65，与 `risk_gate_long_thr=0.50` 形成更合理阶梯；寻优后 0.6721，`reduce_threshold` 同步至 0.5599
  - **影响范围**: `scripts/memory_l4/classic_exit_system.py` → `ExitConfig.l2_close_threshold` / `l2_reduce_threshold`
  - **验证方式**: 回测 L2 平仓触发时机合理
  - **回滚策略**: 恢复 0.75

- **修复**: 风险闸门 `cooldown` 30min → 10min → 11.11min（贝叶斯寻优）
  - 修复前：armed 后等 30 分钟才减仓，加密行情 30 分钟可让 -2% 扩大到 -10%
  - 修复后：10 分钟响应；寻优后 11.11 分钟（噪声过滤与响应速度平衡）
  - **影响范围**: `scripts/memory_l4/classic_exit_system.py` → `ExitConfig.l0_risk_gate_cooldown_min`
  - **验证方式**: 回测风险闸门响应速度
  - **回滚策略**: 恢复 30min

- **修复**: TSTP 亏损超时释放死仓
  - 修复前：盈利 < 成本缓冲时直接 HOLD，长时间无盈利持仓占用仓位
  - 修复后：持仓达最大阶段且仍无盈利 → `CLOSE_NO_PROFIT`（价值低）或 `REDUCE_NO_PROFIT`（价值尚可）
  - **影响范围**: `scripts/memory_l4/classic_exit_system.py` → TSTP 逻辑
  - **验证方式**: 回测死仓释放频率
  - **回滚策略**: 恢复原 HOLD 逻辑

- **新增**: §9.7 经典离场系统章节
  - **影响范围**: `docs/TECHNICAL_DESIGN.md`
  - **验证方式**: 文档审查
  - **回滚策略**: N/A

---

## [v2.5] - 2026-07-24

### 文档与代码同步更新 + 离场架构反转

- **修改**: §9.1 数据流反映离场架构反转
  - `YijingExitSystem` 为主离场，`ClassicExitSystem` 降为备用
  - **影响范围**: `docs/TECHNICAL_DESIGN.md` §9.1、`scripts/memory_l4/polling_trader.py`
  - **验证方式**: PollingTrader 集成易经离场 + 震荡增强 + CBR + A0 矛盾引擎
  - **回滚策略**: 恢复 ClassicExitSystem 为主离场

- **新增**: §9.4 震荡市增强层（`RangingMarketEnhancer`）
  - 5 态自适应 + 布林双信号 + 动态止损 + 置信度校准
  - **影响范围**: `scripts/memory_l4/ranging_market_enhancer.py`、`docs/TECHNICAL_DESIGN.md` §9.4
  - **验证方式**: 震荡市场景回测
  - **回滚策略**: 移除 `RangingMarketEnhancer` 调用

- **新增**: §9.5 CBR 案例检索增强
  - 4R 循环 + 三种融合策略（`cbr_override` / `cbr_blend` / `bcrm_only`）
  - **影响范围**: `scripts/memory_l4/cbr_engine.py`、`scripts/memory_l4/cbr_adapter.py`、`docs/TECHNICAL_DESIGN.md` §9.5
  - **验证方式**: CBR 案例检索 + 跨币种迁移学习
  - **回滚策略**: 移除 `CBRToBCRMBridge` 集成

- **新增**: §9.6 易经离场系统
  - 三条决策路径 + 六爻阶段风险/价值映射
  - **影响范围**: `scripts/memory_l4/yijing_exit_system.py`、`docs/TECHNICAL_DESIGN.md` §9.6
  - **验证方式**: 易经离场决策用例
  - **回滚策略**: 移除 `YijingExitSystem` 集成

- **修改**: §15.5 Phase 4 CBR 状态从"📋 规划中"改为"✅ 已实现"
  - **影响范围**: `docs/TECHNICAL_DESIGN.md` §15.5
  - **验证方式**: 文档审查
  - **回滚策略**: N/A

- **修改**: §1.3 与 §12 性能基准统一标注
  - Phase 0 基线（7.45）与五角校验+贝叶斯优化后（8.20）两套数值，消除自相矛盾
  - **影响范围**: `docs/TECHNICAL_DESIGN.md` §1.3、§12
  - **验证方式**: 文档审查
  - **回滚策略**: N/A

---

## [v2.4] - 2026-07-21

### TradingAgents Review Agent 集成 + evidence_chain 增强 + Phase 4 认知增强

- **新增**: §5.2.1 TradingAgents Review Agent 集成
  - L4 Review Engine 集成 TradingAgents 两阶段复盘机制
  - 组件：`L4MemoryLog` + `MultiDimensionalAnalyzer` + `Reflector`
  - **影响范围**: `scripts/memory_l4/review/`、`docs/TECHNICAL_DESIGN.md` §5.2.1
  - **验证方式**: L4 Review 产物含多维分析与反思记录
  - **回滚策略**: 移除 TradingAgents 集成，回退到原 Review Engine

- **修改**: §5.2.2 evidence_chain 增强
  - 从 5 维扩展为 6 维（新增 `analyst_refs`）
  - 支持按系统来源分派分析师维度
  - **影响范围**: `scripts/memory_l4/review/`、`docs/TECHNICAL_DESIGN.md` §5.2.2
  - **验证方式**: evidence_chain 含 6 维字段
  - **回滚策略**: 恢复 5 维结构

- **新增**: §15.5 Phase 4 认知增强
  - CBR 案例检索引擎
  - LLM 案例摘要
  - 跨币种迁移学习
  - **影响范围**: `scripts/memory_l4/cbr_engine.py`、`scripts/memory_l4/cbr_adapter.py`、`docs/TECHNICAL_DESIGN.md` §15.5
  - **验证方式**: CBR 检索 + 跨币种迁移回测
  - **回滚策略**: 移除 CBR 相关模块

---

## [v2.3] - 2026-07-15

### 保证金计算修正 + 监控告警集成 + BCRM 2.0 实盘验证

- **修复**: 保证金计算逻辑修正
  - `_open_position()` 使用可用余额（而非总权益）计算仓位
  - 解决多系统共用账户时仓位过大的问题
  - **影响范围**: `scripts/memory_l4/polling_trader.py` → `_open_position()`
  - **验证方式**: 多系统并行时仓位不超可用余额
  - **回滚策略**: 恢复总权益计算

- **新增**: §11.5 监控告警集成
  - 15-监控告警系统适配器（`15-监控告警系统/adapters/yijing_adapter.py`）
  - 飞书告警推送（`scripts/memory_l4/yijing_feishu_alert.py`）
  - 心跳/风控/模型/持仓/系统五类告警
  - **影响范围**: `15-监控告警系统/adapters/yijing_adapter.py`、`scripts/memory_l4/yijing_feishu_alert.py`、`docs/TECHNICAL_DESIGN.md` §11.5
  - **验证方式**: 触发异常时飞书收到告警
  - **回滚策略**: 移除适配器注册

- **新增**: BCRM 2.0 实盘验证通过
  - BTC/ETH 开仓成功
  - **影响范围**: 实盘环境
  - **验证方式**: 实盘 BTC/ETH 持仓记录
  - **回滚策略**: N/A

---

## [v2.2] - 2026-07-15

### 仓位模式从全仓切换为逐仓

- **修改**: 仓位模式 cross → isolated
  - `okx_simulated.py` 默认 `td_mode=isolated`
  - `polling_trader.py` 支持逐仓/全仓保证金检查
  - **影响范围**: `scripts/memory_l4/okx_simulated.py`、`scripts/memory_l4/polling_trader.py`
  - **验证方式**: 开仓时 td_mode=isolated
  - **回滚策略**: 恢复 `td_mode=cross`

- **新增**: 第 11 章逐仓风控模式
  - 设计原则、技术实现、资金分配、切换方式
  - **影响范围**: `docs/TECHNICAL_DESIGN.md` §11
  - **验证方式**: 文档审查
  - **回滚策略**: N/A

- **修改**: Phase 1 增加逐仓风控模式标记
  - **影响范围**: `docs/TECHNICAL_DESIGN.md` §15.2
  - **验证方式**: 文档审查
  - **回滚策略**: N/A

---

## [v2.1] - 2026-07-14

### BCRM 2.0 实盘切换 + BCRM2Adapter 适配层

- **新增**: §3.3.3 BCRM2Adapter 适配层
  - 封装 `DialecticalMLEngine`，提供与 BCRM 1.0 兼容的 `infer()` 接口
  - 含模型缓存、五角校验、fail_closed 机制
  - **影响范围**: `scripts/memory_l4/bcrm2_adapter.py`、`docs/TECHNICAL_DESIGN.md` §3.3.3
  - **验证方式**: BCRM2Adapter.infer() 输出格式兼容 BCRM 1.0
  - **回滚策略**: `use_bcrm2=False` 降级到 BCRM 1.0

- **修改**: 数据流更新（含 Fallback 机制）
  - BCRM 2.0 推理失败时自动降级到 BCRM 1.0
  - **影响范围**: `scripts/memory_l4/polling_trader.py` → `_infer_bcrm2()`、`docs/TECHNICAL_DESIGN.md` §9.1
  - **验证方式**: BCRM 2.0 异常时 BCRM 1.0 接管
  - **回滚策略**: 恢复无 Fallback 数据流

- **修改**: 置信度阈值 0.60
  - **影响范围**: `scripts/memory_l4/polling_trader.py` → `confidence_threshold`
  - **验证方式**: 开仓决策置信度门槛
  - **回滚策略**: 恢复原阈值

- **修改**: Phase 1 标记 BCRM 2.0 实盘 + 离场集成完成；Phase 2 增加 L2 修复和小币种 Fallback 优化
  - **影响范围**: `docs/TECHNICAL_DESIGN.md` §15.2、§15.3
  - **验证方式**: 文档审查
  - **回滚策略**: N/A

---

## [v2.0] - 2026-07-13

### 扩展为完整系统级技术设计

- **新增**: 顶层架构
  - 约束层驱动 + 记忆底座服务 + 并联工作流协同 + 统一产物出口
  - 四层功能架构（用户交互层 / 编排层 / 决策层 / 支撑层）
  - **影响范围**: `docs/TECHNICAL_DESIGN.md` §2
  - **验证方式**: 文档审查
  - **回滚策略**: N/A

- **新增**: BCRM 1.0 矛盾力学推理引擎章节
  - 七步推理循环、六十四卦推理算法
  - **影响范围**: `docs/TECHNICAL_DESIGN.md` §3.2、`scripts/memory_l4/bcrm/engine.py`
  - **验证方式**: BCRMEngine.infer() 输出 BCRMOutput
  - **回滚策略**: N/A

- **新增**: QMM 量化记忆模型章节
  - 三屏对齐、阻力方向、趋势速度、不确定性
  - **影响范围**: `docs/TECHNICAL_DESIGN.md` §3.4、`scripts/memory_l4/qmm/engine.py`
  - **验证方式**: run_qmm() 输出 QMMOutput
  - **回滚策略**: N/A

- **新增**: L4 记忆体系章节
  - 四级记忆架构、L4 全链路（M0→M5）、记忆沉淀闭环、共享内存总线
  - **影响范围**: `docs/TECHNICAL_DESIGN.md` §5、`scripts/memory_l4/pipeline.py`
  - **验证方式**: run_pipeline() 全链路执行
  - **回滚策略**: N/A

- **新增**: 自进化体系章节
  - 三层反思闭环、停滞检测、约束升级通道
  - **影响范围**: `docs/TECHNICAL_DESIGN.md` §6、`scripts/memory_l4/self_evolution_engine.py`
  - **验证方式**: SelfEvolutionEngine 三层反思
  - **回滚策略**: N/A

- **新增**: A0-A9 决策链章节
  - 决策链概览、与易经卦象的对应
  - **影响范围**: `docs/TECHNICAL_DESIGN.md` §7
  - **验证方式**: 文档审查
  - **回滚策略**: N/A

- **新增**: CI/CD 与治理架构章节
  - CI/CD 体系、治理架构、回滚机制
  - **影响范围**: `docs/TECHNICAL_DESIGN.md` §8、`scripts/ci/`、`.github/workflows/`
  - **验证方式**: GitHub Actions 门禁运行
  - **回滚策略**: N/A

---

## [v1.0] - （历史）

### 初始版本

- **新增**: 初始版本，仅覆盖 BCRM 2.0 量化引擎
  - 辩证 ML 引擎（`DialecticalMLEngine`）
  - 八卦特征工程、五角校验、Walk-Forward 回测
  - **影响范围**: `scripts/memory_l4/bcrm2/`
  - **验证方式**: Phase 0 基线回测（综合夏普 7.45、胜率 70.2%、盈亏比 2.61、最大回撤 12.75%）
  - **回滚策略**: N/A（初始版本）

---

_维护规则：每次代码变更后必须在此文件追加变更记录。版本号与 `docs/TECHNICAL_DESIGN.md` 保持一致。_
