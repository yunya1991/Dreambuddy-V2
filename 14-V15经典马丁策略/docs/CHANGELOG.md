# 变更日志 — V15 经典马丁策略

> **定位**：记录每次变更的原因、内容、验证方式
> **格式**：[版本] - 日期 → 变更类型（新增/修改/修复/删除）

---

## [v6.1] - 2026-08-10

### 新增 AI_ENHANCEMENT_ROADMAP.md：大模型增强三阶段路线图 + 四大决策铁律

**变更类型：新增技术文档（无代码改动）**

- **新增**：`docs/AI_ENHANCEMENT_ROADMAP.md` v1.0，完成联网调研 + GitHub 研究后的落地技术规范
  - **模型族谱（§2）**：金融大模型族（FinGPT/QuantLLM/FLAG-Trader/FinRL-DeepSeek）、时间序列 SOTA（PatchTST/iTransformer/TimesNet/VAIOM/BiLSTM-Attention）、强化学习算法（PPO/CPPO/TD3/FLAG-Trader）、GitHub 马丁+AI 参考项目
  - **AI 决策四大铁律（§3 = 用户四条原则的工程化）**：
    1. **§3.1 基线可随时回退**：3 级开关（总闸 + Phase 闸 + 模块闸）、关闭后内存不加载 AI、状态快照、OCO 挂单自动还原基线
    2. **§3.2 不超基线不启用**：① 全量回测总收益 ≥ 基线 +5% 且 卡尔马 ≥ 基线×1.05；② Walk-Forward 5/5 段退化 < 10% 且 ≥3 段正向；③ MDD ≤ 基线×1.10；④ OOD 极端行情 ≥ 基线×0.90
    3. **§3.3 最大最小调节边界（基线相对 + 绝对铁壳双层 clamp）**：10 个决策变量的 LOWER/UPPER 默认值；最高优先级：AI 只能否决开仓、永远不可强制开仓；max_addons 只能缩档、不能扩到第 5 档
    4. **§3.4 边界随回测+实盘表现缩放**：`S_bt`（回测稳健度）+ `S_live`（实盘跟踪得分，7 天滚动）驱动 `K_bound ∈ [0.50, 1.35]`；`S_live < 0.85` 单窗口立即回退基线
  - **Phase D（1–2 周 MVP，§4）**：BiLSTM-Attention 爆仓预警 + PatchTST 回撤预测；G-D1/G-D2/G-D3 三个离散闸门；精确代码接入点映射（v15_trader.py / timing_gate.py / v15_backtest.py）
  - **Phase E（3–6 周核心，§5）**：PPO-LSTM 强化学习接管加仓金字塔；34 维状态空间 / 5 维动作空间 / 马丁专属奖励函数；**§5.2 确定性风控盾（Deterministic Shield）6 条硬防线**直接落地 §3.3
  - **Phase F（长期架构，§6）**：FLAG-Trader 式 LLM 策略网络；SFT 模仿 V15 成功轨迹 → PPO 按收益梯度继续调参；易经桥接 Prompt 槽位与边界收紧
  - **§7 配置规范**：统一写入 `config/.env.v15`；`V15_AI_ENABLED` 总闸 + Phase D/E/F 子闸 + 模型路径 + 阈值 + K_bound 状态锚点
  - **§8 升级总门禁**：Phase D 实盘 ≥ 28 天 + S_live ≥ 1.05 才允许进 Phase E；Phase E ≥ 56 天 + S_live ≥ 1.10 才允许进 Phase F；出现 S_live<0.85 / 盾告警≥10 / MDD>基线×1.20 任一即自动降级
  - **§9 失效模式清单**：AI 越亏越补、LLM 幻觉、历史过拟合、分布外劣化、推理崩溃、配置手滑、易经+LLM 双迷信、升级过快、决策不可审计 — 共 9 类风险均对应到本文档某一节的防护机制
- **无实盘影响**：本次仅新增文档，未改动任何运行代码；`V15_AI_ENABLED` 及所有 Phase 子开关默认 `false`，实盘行为与 v15-final (v6.0) 字节等价

---

## [v6.0] - 2026-08-06

### Phase A+/B+/C 智能增强演进 & v15-final 最终形态锁定

**最终形态：Phase B+（Phase A+ 基线 + 子形态微调），Phase C 暂不启用**

#### Phase A+：智能增强基线（v5.x 已实现，作为基线）

- **ATR动态止盈**：BTC 4%基准按ATR因子动态调整
- **移动止盈（Trailing TP）**：浮盈80%启动，回撤N×ATR止盈
- **ELDER-RAY资金调度**：0.9-1.5x 按趋势强度调整仓位
- **BTC风向标智能模式**：BTC用DirectionGate MA128，其他币用BTC风向标3日确认
- **贝叶斯8参数自动调度**：连亏3笔+月度触发，双基线版本管理

#### Phase B+：子形态微调（BULL/BEAR × Elder-ray 6类子形态）

- **新增**：子形态6分类（BULL_STRONG/BULL_NORMAL/BULL_STABLE/BEAR_STRONG/BEAR_NORMAL/BEAR_STABLE），3-bar mode 平滑
  - 基于 Elder-ray + MA128 全局BULL/BEAR
  - TP 倍数：BULL 形态×1.05-1.15（放宽止盈），BEAR 形态×0.85-0.95（收紧止盈）
  - 持仓倍数：BULL×1.05-1.10（延长持仓），BEAR×0.85-0.95（缩短持仓）
  - **影响范围**: `core/v15_backtest.py`, `core/v15_trader.py`
  - **验证方式**: 3币种（BTC/ETH/SOL）回测 vs A+基线：收益+2.07%、胜率+1.38%、Calmar+1.18、最大回撤不变

#### Phase C：易经推理桥接 & risk/value 插值（模块化实现，默认关闭）

- **新增**：易经推理桥接模块（模块化，可被外部调用）
  - `lib/yijing_bridge.py`：跨目录 importlib 加载 YijingEngine，K线转8维归一化评分（供需/技术面/资金流/情绪/趋势强度/波动率/量比/价格位置），批量/单次推理+缓存
  - `lib/yijing_param_interpolator.py`：risk/value→TP/持仓/仓位插值，与子形态倍数叠加，clamp [0.75, 1.25]，中性区（|net_value|<0.12）不调整
  - `lib/coin_selector.py`：易经因子币种过滤（DANGER剔除，net_value排序）
  - `core/walk_forward_validator.py`：5段 walk-forward 验证框架（全段退化<5%才通过）
  - **修复 Bug**：risk_score 从离散3档(0.25/0.50/0.75)→连续化（卦象档位锚点+8维评分微调），范围 0.17-0.71
  - **修复 Bug**：前向填充（最多回看3bar≈12h）解决 yijing_step=6 采样导致的命中率低（13-32%→~100%）
  - **影响范围**: `lib/yijing_bridge.py`, `lib/yijing_param_interpolator.py`, `lib/coin_selector.py`, `core/walk_forward_validator.py`, `core/v15_backtest.py`, `core/v15_trader.py`

- **新增**：双层优化节奏（60天参数空间 + 6天易经插值）
  - `lib/bayesian_optimizer.py` `SCHEDULE_CONFIG`：`param_space_recalc_days=60`（过拟合护栏），`yijing_interp_days=6`（日常微调，不碰边界）
  - 冷却期24h，连亏3笔事件驱动，收益≥2%才采用

#### Phase C 未通过验证，暂不启用

- **walk-forward 结果**：
  - BTC/ETH ✅ 5/5段通过
  - SOL ❌ 4/5段（第2段退化6%超5%容忍线）
- **C vs B+ 收益对比**：
  | 币种 | B+收益 | C收益 | C-B+ |
  |------|--------|-------|------|
  | BTC  | +26.99% | +26.94% | -0.05% |
  | ETH  | +10.50% | +10.40% | -0.10% |
  | SOL  | +7.36%  | +7.25%  | -0.11% |
- **根因**：马丁策略止盈/持仓对 tp_mult ±5-8% 的微调不敏感，Phase B+ 子形态已捕获大部分可改善空间，易经插值边际贡献为负

#### v15-final 部署 & 开关

- **新增**：`V15_YIJING_ENABLED` 配置项（默认 `false`，Phase C 关闭）
  - `.env.v15`：`V15_YIJING_ENABLED=false`
  - `core/v15_trader.py`：易经桥接仅在开启时懒加载初始化，否则直接跳过
- **新增**：`data/v15_final_deployment.json` — 最终部署状态快照（决策依据+激活配置+模块保留状态）
- **实盘重启**：旧进程PID=7329 → 新进程PID=84567，Phase B+ 代码加载，下次开仓时生效
- **Phase C 模块化保留**：4个模块完整保留，后续可通过 `V15_YIJING_ENABLED=true` 启用或被其他系统调用

---

## [v5.2] - 2026-08-01

### 技术文档与代码实现一致性对齐（A8 理论-实践一致性）

- **修复**: `TECHNICAL_DESIGN.md` 多处历史遗留与 `direction_gate.py` 实现不一致
  - DirectionGate 已升级为 **MA128 + BTC风向标** 模型，但文档前半部分仍描述旧的"日/周MA200三状态模型"
  - §1.2 模块表：多空方向控制描述 → "基于MA128+BTC风向标三状态模型"
  - §1.3 设计原则：方向控制原则对齐新模型，补交叉引用 §11.2.2
  - §12.1 风控链路：第一层入场风控 DirectionGate 描述 → "MA128+BTC风向标三状态模型"
  - §12.2 风控参数表：方向缓冲带说明 → "MA附近缓冲（日MA128+周MA200）"
  - §12.3 多空方向验证链：状态触发条件从"价格在日MA200上方→LONG_PREFERRED"等旧逻辑，改为"BTC做空闸门关闭→LONG_PREFERRED"等新模型逻辑
  - §12.3 测试统计：25项 → 26项（边界情况5项→6项，新增 `_check_valid_breakdown` 3日有效跌破判定用例）
  - **影响范围**: docs/TECHNICAL_DESIGN.md

- **修复**: `tests/test_short_selling.py` DirectionGate 参数名历史遗留清理
  - 测试文件停留在旧模型（`daily_ma200`/`last_daily_close`/`last_weekly_close`），导致 15 个用例 `TypeError`
  - `TestDirectionGateStates` (4项)：参数名 `daily_ma200`→`daily_ma128`，语义从"跌破日MA200"改为"BTC风向标闸门开关"
  - `TestDirectionGateEdgeCases` (5项→6项)：参数名对齐 + 语义调整 + 新增 `_check_valid_breakdown` 用例
  - `TestGateResultDict` (2项)：`to_dict()` 字段 `daily_ma200`→`daily_ma128`，新增 `price_vs_*` 字段断言
  - `TestStateTransitions` (3项)：状态转移触发条件从"跌破MA200"改为"BTC闸门打开/关闭"
  - 附带清理：`execute_open_position` 已升级为开仓+3档加仓网格预挂单，2 个用例 `assert_called_once()` 改为 `call_args_list[0]` 验证开仓单方向
  - **影响范围**: tests/test_short_selling.py
  - **验证方式**: `pytest tests/test_short_selling.py -v` → 26/26 全部通过

---

## [v5.1] - 2026-07-17

### 实盘移动止盈集成 + RAISE_TP 修复

- **新增**: 实盘移动止盈（Trailing TP）集成
  - `core/v15_trader.py` → `check_take_profit()` 中集成移动止盈逻辑
  - 参数从 `active_params.json` 加载（`trailing_atr_mult=1.0`, `trailing_start_ratio=0.8`）
  - 配置开关：`V15_USE_TRAILING_TP=true`（默认启用）
  - 持仓状态新增字段：`trailing_active`, `trailing_price`, `peak_price`
  - 移动止盈在固定止盈之前检查，优先级更高
  - ATR 从 4H K线实时计算（`calc_atr_pct()`），与回测引擎一致
  - 兼容旧持仓：轮询时自动补充移动止盈状态字段
  - **影响范围**: core/v15_trader.py, config/.env.v15

- **修复**: RAISE_TP 提高止盈功能（3处bug）
  - `check_take_profit()` 使用 `pos["take_profit_pct"]`（RAISE_TP 提高后的值），不再忽略
  - RAISE_TP 后调用 `_sync_tp_sl_orders()` 同步更新交易所 OCO 挂单
  - `_update_tp_sl_dynamic()` 也使用 `pos["take_profit_pct"]` 保持一致
  - **影响范围**: core/v15_trader.py

- **更新**: 技术文档和工程索引
  - `TECHNICAL_DESIGN.md` v5.1：§15.3 移动止盈章节新增实盘集成说明
  - `ENGINEERING_INDEX.md` v5.1：配置参数新增 `V15_USE_TRAILING_TP`
  - **影响范围**: docs/TECHNICAL_DESIGN.md, docs/ENGINEERING_INDEX.md

---

## [v5.0] - 2026-07-16

### 智能系统增强 + 双基线版本管理 + 贝叶斯优化自动调度

- **新增**: 智能系统增强层 — 四项增强机制全开
  - ATR动态止盈：`strategy_params.py` 新增 `calc_atr()` + `calc_atr_pct()`，BTC 4%基准按ATR因子动态调整
  - 移动止盈（Trailing TP）：`v15_backtest.py` 新增 `use_trailing_tp` 参数，浮盈达80%启动，回撤N×ATR止盈
  - ELDER-RAY资金调度：`v15_backtest.py` 新增 `calc_elder_ray_size_mult()` + 模块级变量 `_elder_ray_floor`(0.9) / `_elder_ray_ceil`(1.5)
  - 凯利公式底仓优化：`kelly_optimizer.py` 半凯利+收缩估计（默认关闭，可选启用）
  - **影响范围**: lib/strategy_params.py, lib/kelly_optimizer.py, core/v15_backtest.py
  - **验证方式**: 6币种回测（BTC/ETH/SOL/ARB/OP/UNI），总收益从138%提升至210.4%

- **新增**: BTC风向标智能模式选择
  - BTC走DirectionGate（自身MA128+MA200），其他币走BTC风向标3日确认+short_only
  - `v15_backtest.py` 新增 `use_btc_windvane`, `btc_windvane_confirm_days`, `btc_windvane_short_only` 参数
  - 智能模式自动选择：非BTC币种自动启用风向标模式
  - **影响范围**: core/v15_backtest.py
  - **验证方式**: 总收益从+124.50%提升至+134.28%（风向标模式）

- **新增**: 双基线版本管理体系
  - `bayesian_optimizer.py` 新增 `FIXED_BASELINE_PARAMS`（138%，纯马丁策略，无智能增强）
  - `bayesian_optimizer.py` 新增 `SMART_BASELINE_PARAMS`（210.4%，智能系统+贝叶斯优化最优参数）
  - `BASELINE_PARAMS = SMART_BASELINE_PARAMS.copy()`（向后兼容）
  - 新增 `VERSION_INFO` 版本元数据（双基线对比信息）
  - 三级回退策略：贝叶斯优化参数 → 智能参数基线(210.4%) → 固定参数基线(138%)
  - **影响范围**: lib/bayesian_optimizer.py

- **新增**: 贝叶斯优化8参数智能系统空间
  - 优化参数从旧的资金分配参数（addon1/2/3_pct等）切换为智能系统核心参数
  - 新8参数：trailing_atr_mult, trailing_start_ratio, elder_ray_floor, elder_ray_ceil, btc_windvane_confirm_days, max_base_holding_hours, max_post_addon_hours, golden_window_hours
  - 目标函数：卡尔马比率(40%) + 夏普(20%) + 胜率(15%) + 资金效率(25%)
  - **影响范围**: lib/bayesian_optimizer.py

- **新增**: 贝叶斯优化自动调度（orchestrator集成）
  - `orchestrator.py` 新增 `check_bayesian_optimization_trigger()` 触发判断
  - `orchestrator.py` 新增 `run_bayesian_optimization()` 后台启动（PID锁防重复，不阻塞交易）
  - `bayesian_optimizer.py` 新增 `should_trigger_optimization()` 触发条件判断
  - `bayesian_optimizer.py` 新增 `run_optimization_with_rollback()` 4步自动回退验证
  - **影响范围**: core/orchestrator.py, lib/bayesian_optimizer.py

- **新增**: 冷却期机制
  - 距上次优化24小时内不重复触发（连亏触发也受冷却期约束，但有最高优先级）
  - `SCHEDULE_CONFIG` 新增 `cooldown_hours: 24`
  - **影响范围**: lib/bayesian_optimizer.py, config/.env.v15

- **新增**: CLI版本管理命令
  - `--version-info`：查看双基线版本管理信息
  - `--reset-to-smart`：重置为智能参数基线（210.4%）
  - `--reset-to-fixed`：终极回退到固定参数基线（138%）
  - `--check-trigger`：检查是否应该触发优化
  - `--with-rollback`：优化+自动回退验证（调度推荐）
  - **影响范围**: lib/bayesian_optimizer.py

- **新增**: 活跃参数与调度状态持久化
  - `data/bayesian_opt/active_params.json`：当前生效参数 + 来源 + 评分 + 时间戳
  - `data/bayesian_opt/schedule_state.json`：上次优化时间 + 动作 + 收益改善
  - **影响范围**: data/bayesian_opt/

- **修改**: 触发频率调整
  - 从"连亏3笔+每周+每月"调整为"连亏3笔+每月"（去掉每周触发，避免过拟合）
  - `BAYESIAN_OPT_WEEKLY` 从 `true` 改为 `false`
  - 新增 `BAYESIAN_OPT_COOLDOWN_HOURS=24`
  - **影响范围**: config/.env.v15, core/orchestrator.py, lib/bayesian_optimizer.py

- **修改**: 技术文档全面更新
  - `TECHNICAL_DESIGN.md` 新增第15章「智能系统增强」、第16章「BTC风向标智能模式选择」、第17章「贝叶斯优化自动调度与双基线版本管理」，更新§7.2 ELDER-RAY范围说明(0.9-1.5x)，更新§7.4/§10贝叶斯优化8参数表，更新版本至 v5.0
  - `ENGINEERING_INDEX.md` 核心架构从10模块扩展至13模块，§5贝叶斯优化参数更新为8参数智能系统，新增§8「智能系统增强与双基线版本管理」，更新版本至 v5.0
  - **影响范围**: docs/

---

## [v4.8] - 2026-07-15

### 币种风控过滤系统：市值等级 + 上线时间双重过滤

- **新增**: `symbol_mapper.py` 币种风控过滤系统
  - 新增 `MarketCapTier` 枚举：LARGE（大市值Top20）/ MID（中等市值Top20-60）/ SMALL（小市值/meme币）
  - `AssetInfo` 数据类新增 `market_cap_tier` 和 `listing_date` 字段
  - 为全部 50 个注册币种标注市值等级和上线日期
  - 新增 `is_martin_safe()` 方法：市值等级 + 上线时间双重过滤
  - 新增 `filter_martin_safe()` 方法：批量过滤
  - 新增 `get_market_cap_tier()` / `get_listing_date()` 查询方法
  - 小市值币种（PEPE/SHIB/SUSHI/WLD/APE）自动设 `martin_enabled=False`
  - **影响范围**: lib/symbol_mapper.py

- **修改**: `v15_trader.py` COINS 加载逻辑增加风控过滤
  - 导入 `is_martin_safe` 并新增降级兼容函数
  - COINS 加载链：V15_COINS配置 → OKX支持过滤 → 马丁风控过滤
  - 新增启动日志：输出原始/OKX支持/风控通过币种数 + 剔除币种及原因
  - **影响范围**: core/v15_trader.py

- **修改**: `config/.env.v15` 币种池精简 + 新增风控参数
  - `V15_COINS` 从 34 个精简至 30 个（剔除 PEPE/SHIB/SUSHI/WLD/APE）
  - 新增 `V15_MARTIN_MIN_TIER=mid`（最低市值等级）
  - 新增 `V15_MARTIN_MIN_HISTORY_DAYS=365`（最小上线天数）
  - **影响范围**: config/.env.v15

- **修改**: HYPE 从 SMALL 提升至 MID
  - HYPE（Hyperliquid）上线 2024-11-29，距今 >365 天，通过时间检测
  - 用户指定保留（平台币潜力大），市值等级 SMALL → MID
  - `martin_enabled` 从 False 恢复为 True
  - **影响范围**: lib/symbol_mapper.py, config/.env.v15

- **新增**: `tests/test_symbol_mapper.py` 新增 `TestMartinSafeFilter` 测试类
  - 16 项测试：市值等级查询/单币种风控/批量过滤/时间检测/HYPE特殊处理
  - 更新原有测试适配 HYPE 等级变更
  - **影响范围**: tests/test_symbol_mapper.py
  - **验证方式**: 46/48 测试通过（2个失败为改动前已存在的预存问题）

- **修改**: 技术文档全面更新
  - `TECHNICAL_DESIGN.md` 新增第 14 章「币种风控过滤系统」，风控体系从五层扩展至六层（新增第零层币种风控），更新版本至 v4.8
  - `ENGINEERING_INDEX.md` 核心架构从 9 模块扩展至 10 模块（新增币种风控过滤），币种池从 34 更新至 30，新增 2 个配置参数，更新版本至 v4.3
  - **影响范围**: docs/

---

## [v4.7] - 2026-07-14

### OCO止盈止损挂单系统 + 多空方向控制v2上线

- **新增**: OCO止盈止损挂单同步机制 — 交易所层面条件单保护
  - `v15_trader.py` 新增 `_sync_tp_sl_orders()` 函数：开仓/加仓后同步挂 OKX OCO 条件单
  - `v15_trader.py` 新增 `_update_tp_sl_dynamic()` 函数：轮询动态更新挂单（止损线移动 > 0.5% 时自动同步）
  - `v15_trader.py` `execute_open_position()` 开仓成功后自动挂 OCO 单
  - `v15_trader.py` `execute_addon()` 加仓成功后撤旧单+挂新单
  - `v15_trader.py` `check_take_profit()` / `_execute_close_position()` 平仓前自动取消条件单
  - `v15_trader.py` `run_poll_cycle()` 每次轮询动态检查止盈止损价格变化
  - **影响范围**: core/v15_trader.py
  - **验证方式**: 51项核心测试全通过

- **修复**: `okx_client.py` TP-only/SL-only 条件单参数
  - 仅止盈单参数从 `triggerPx` 改为 `tpTriggerPx` + `tpOrdPx`
  - 仅止损单参数从 `triggerPx` 改为 `slTriggerPx` + `slOrdPx`
  - **影响范围**: lib/okx_client.py

- **修改**: `config/.env.v15` `V15_ALLOW_SHORT` 从 `false` 改为 `true`
  - 系统切换为最新马丁策略（MA128 + BTC风向标做空机制）
  - **影响范围**: config/.env.v15

- **修改**: 实盘 5 币种持仓止盈止损挂单（NEAR 已手动平仓）
  - BTC: OCO 单，TP=$65,119 (4%), SL=$57,000 (安全网)
  - INJ: OCO 单，TP=$5.434 (9%), SL=$4.613 (日EMA200)
  - TIA: OCO 单，TP=$0.4442 (9.6%), SL=$0.3844 (日MA200)
  - WLD: OCO 单，TP=$0.4424 (10%), SL=$0.3927 (日MA200)
  - ZEC: OCO 单，TP=$554.80 (10%), SL=$424.32 (日EMA200)
  - **影响范围**: data/v15_state.json

- **修改**: 技术文档全面更新
  - `TECHNICAL_DESIGN.md` 新增第 13 章「OCO止盈止损挂单系统」，更新版本至 v4.7
  - `ENGINEERING_INDEX.md` 更新交易方向为多空双向，核心架构从 7 模块扩展至 9 模块，更新版本至 v4.2
  - **影响范围**: docs/

---

## [v4.0] - 2026-07-13

### 文档规范化
- **新增**: `docs/CHANGELOG.md` 变更日志文档
- **修改**: README.md 清除V15-CT"当前主力运行版本"描述，更新为独立V15系统为当前运行版本
- **修改**: README.md §2 目录结构补充 `lib/capital_manager_engine.py`、`lib/bayesian_optimizer.py`、`lib/symbol_mapper.py`
- **修改**: README.md §9.1 指标来源从 `v15ct_signal.py` 修正为 `v15_signal.py`
- **修改**: README.md §3 补充 `capital_engine` 子命令使用说明
- **修改**: README.md §12 更新测试文件列表，补充 `test_multi_scenario.py`、`test_symbol_mapper.py`
- **修改**: ENGINEERING_INDEX.md §2.2 标记V15-CT为已废弃
- **修改**: API_SPEC.md §10 路径从 `experiments/ab-trading/` 修正为 `lib/`
- **影响范围**: docs/ 全部文档 + README.md
- **验证方式**: 文档审查，路径与实际代码文件对照

---

## [v3.0] - 2026-07-12

### 修复
- **修复**: 杠杆倍数不一致问题 — 全局统一为5x
  - `.env.common` LEVERAGE 从10修改为5.0
  - `v15_trader.py` 默认杠杆从10修改为5
  - `okx_client.py` 默认杠杆从10修改为5
  - `capital_manager.py` 默认杠杆从10修改为5
  - `strategy_params.py` 默认杠杆从10修改为5
  - `bayesian_optimizer.py` 硬编码5x杠杆（不参与优化）
  - **影响范围**: config/ + lib/ + core/
  - **验证方式**: 全局搜索10x引用确认清除，测试通过
  - **回滚策略**: 恢复各文件中的LEVERAGE默认值

### 新增
- **新增**: RAISE_TP离场动作 — 强势反弹时提高止盈价
  - `classic_exit_system.py` 新增RAISE_TP评估逻辑
  - `v15_trader.py` `check_time_exit()` 支持RAISE_TP动作
  - `v15_backtest.py` 回测支持RAISE_TP模拟
  - **验证方式**: 集成测试确认RAISE_TP在hold_value=0.791时触发，new_tp=4.0xATR

### 修改
- **修改**: 持仓超时与离场系统 — 新增分层计时机制
  - 底仓阶段：max_base_holding_hours（默认48h）
  - 加仓后阶段：golden_window_hours（12h）+ max_post_addon_hours（24h）
  - 三个时间参数均纳入贝叶斯优化
  - **影响范围**: core/v15_trader.py, lib/bayesian_optimizer.py, config/.env.v15
  - **验证方式**: 多场景测试89项100%通过

---

## [v2.0] - 2026-07-12

### 新增
- **新增**: 16层入场信号系统从V15CT迁移到独立V15系统
  - `core/v15_signal.py` 从7层扩展到16层
  - 新增9项技术指标：Pivot Points, OBV, SuperTrend, Keltner Channel, StochRSI, Vortex, TEMA, GoldenCross, EMA Align
  - **影响范围**: core/v15_signal.py
  - **验证方式**: 信号测试通过，TIA成功以Pivot支撑区信号开仓

### 修改
- **修改**: 趋势过滤系统调整
  - 周线/日线MA200趋势过滤 → 改为三屏趋势信号（both_bear + MA104）
  - 保留4H均线系统用于价格位置判定
  - **影响范围**: lib/strategy_params.py
  - **验证方式**: COMP被三屏趋势过滤阻止开多（熊市禁止做多）

---

## [v1.0] - 2026-07-11

### 新增
- **新增**: V15独立系统初始版本
  - 从 `experiments/ab-trading/v15ct_*.py` 迁移到 `14-V15经典马丁策略/`
  - 统一入口 `run.py`（signal/backtest/trader/capital_engine/test/config）
  - 配置体系：`.env.common` + `.env.v15`（include语法）
  - 状态持久化：`data/v15_state.json`
  - launchd配置：`com.dreambuddy.v15_trader.plist`

### 新增
- **新增**: Elder-ray趋势强度计算器
  - 基于Alexander Elder三重滤网系统
  - 日线级别EMA13斜率 + Bull/Bear Power + 背离检测
  - 8类趋势分类，强度评分0-100
  - **影响范围**: lib/strategy_params.py

### 新增
- **新增**: 贝叶斯参数优化系统（8参数）
  - 资金分配参数：base_position_pct, addon1/2/3_pct, max_concurrent_positions
  - 持仓时间参数：max_base_holding_hours, max_post_addon_hours, golden_window_hours
  - 目标函数：最大化卡尔马比率
  - **影响范围**: lib/bayesian_optimizer.py

### 新增
- **新增**: 资金管理引擎（月度优化）
  - 整合回测+趋势过滤+贝叶斯优化+资金管理
  - HTTP API（端口8770）
  - 连续亏损3次自动触发重新优化
  - **影响范围**: lib/capital_manager_engine.py

---

## 历史版本（V15-CT实验版）

> 以下版本在 `experiments/ab-trading/` 目录中开发，已迁移到独立系统

### [v0.x] - 2026-06 ~ 2026-07

- V15-CT实验版开发与迭代
- 16项技术指标逐步引入
- AB测试对比V15独立版与V15-CT版
- master_daemon hourly调度 `v15ct_trader.py --poll-once`
- **状态**: 已废弃，代码保留作为AB对照参考

---

_维护规则：每次代码变更后必须在此文件追加变更记录_
