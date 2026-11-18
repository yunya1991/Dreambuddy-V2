# 11 域推理信号周期与模型重置调研（2026-11-18）

## 0. 结论摘要

1. **生产推理用的不是 5 分钟 K 线，而是 1H K 线 + 300s（5 分钟）轮询**。代码默认 `bar="1H"`，云端 unit 未覆盖 `--bar`，所以线上就是 1H。
2. 用户感知到的「5 分钟噪声」真实存在，但来源不是 5m K 线，而是三个机制：
   - 每轮推理把**未收盘的 1H bar** 当成最新 bar 输入（每小时被重算 12 次，信号会重绘）；
   - 线上特征窗口只有 **200 根**，训练窗口却是 **2000 根**，长回看特征被截断；
   - 模型缓存键含首尾 bar 时间，**每根新 K 线都会换 key 重训**，模型抖动。
3. **1H 本身是正确选择，不应改成 5m；也不建议改 4H**（4H 只有约 600 根，只能 1 折，无法做有效 walk-forward）。
4. 回测差/胜率低的主因大概率不在周期，而在**战略层把风格锁死 + 置信度校准失真 + 权重退化**：
   - `war_state` 三类资产全 `RESTRICT`，`allowed_style_mask` 只放开 mean_revert / volatility / emergency，趋势跟随、突破、动量全禁；
   - 10 月实盘 42 笔 14 胜（33.3%），累计 -19.12%；SOL 27 笔 2 胜（7.4%）、ARB 0/7、SNDK 0/4；
   - 五域子指标 IC 权重退化：`dao.cycle` 单项权重 0.9774，且底层大量字段是代理值填充；
   - 推理置信度普遍 0.88~0.98，与真实胜率明显不匹配。
5. 可以重置，但要分清「缓存」「回测产物」「交易证据」三类数据，且必须先完成口径对齐 + 同测试集对比。

---

## 1. 现状取证：推理到底用什么周期

| 证据 | 位置 | 说明 |
|---|---|---|
| `bar: str = "1H"` | `scripts/memory_l4/polling_trader.py#L887` | 构造函数默认 1H |
| `--bar` 默认 `1H` | `scripts/memory_l4/polling_trader.py#L19776` | CLI 默认 1H |
| `_load_kline_from_okx(..., bar=self.bar, limit=self.kline_limit)` | `polling_trader.py#L5660` | 推理取数用 self.bar（1H），limit=200 |
| 云端实盘参数 `interval=300 / confidence=0.7955`，无 `--bar` | `48-涌现架构/registry/human_config_hashes.json` | 5 分钟是**轮询间隔**，不是 K 线 |
| `--interval 300 轮询间隔5分钟` | `docs/POLLING_TRADER_ARCHITECTURE.md#L172` | 同上 |
| `K线周期 \| 1H` | `docs/TECHNICAL_DESIGN.md#L1366`、`#L2141` | 设计口径也是 1H |
| 历史影子冷启动才用 `--bar 5m` | `docs/superpowers/plans/2026-08-22-strategy-layer-v1p4p1-stage1-execution-plan.md#L666` | 一次性 shadow-only 验证，非生产 |

结论：**5m 是轮询节奏，1H 是数据周期**。把「轮询 5 分钟」误读成「5 分钟 K 线」是本次疑问的根源。

---

## 2. 5 分钟轮询给 1H 模型带来的三个真实缺陷

### 2.1 未收盘 1H bar 进入推理（重绘）

- `get_kline()` 直接透传 OKX `/api/v5/market/candles` 返回值，未过滤 `confirm` 字段：`22-执行引擎中心/executors/okx_client.py#L440-L461`。
- `_load_kline_from_okx()` 转换时丢弃了 `confirm`：`scripts/memory_l4/yijing_trainer.py#L441-L467`。
- `_kline_to_dataframe()` 升序排序后，最新一根（当前未收盘 bar）位于 `idx=-1`：`polling_trader.py#L5928-L5948`。
- `_infer_bcrm2()` 用 `idx=-1` 推理：`polling_trader.py#L6098`。

影响：同一根 1H bar 在 5 分钟粒度下 high/low/close/volume 持续变化，每小时会产生 12 次不同结论；而训练标签基于**已收盘** bar，训练/推理分布不一致，属于典型 look-ahead/repaint 类偏差。

### 2.2 特征窗口 200 根 vs 训练窗口 2000 根

- 线上 `kline_limit=200`：`polling_trader.py#L891`。
- `train()` 发现不足 500 根会补拉到 2000 根：`scripts/memory_l4/bcrm2_adapter.py#L277-L292`。
- `infer()` 用传入的 200 根 DataFrame 重算特征：`bcrm2_adapter.py#L578-L599`。

影响：MA200、4 年周期、斐波那契、WDH 等长回看特征在推理时被截断，线上特征分布与训练不一致。

### 2.3 模型缓存键含首尾 bar 时间 → 频繁重训

- `_get_cache_key()` = `symbol_timeframe_len_index[0]_index[-1]`：`bcrm2_adapter.py#L152-L160`。
- 每根新 1H bar 都会改变 key；平仓后还会强制重训：`polling_trader.py#L11274`、`#L11419-L11458`。

现状：`scripts/data/bcrm2_models/` 已有 **369 个**模型（245 个 4H、107 个 1H、16 个 1D、1 个 15m），说明历史上还切换过周期，且模型一直在滚动重训。

补充风险：`_trigger_bcrm2_retrain()` 用 OKX 返回的**最新在前的 200 根**直接建 DataFrame，未排序、未设时间索引（`polling_trader.py#L11442-L11458`）。`train()` 在 `len<500` 时会用 `get_klines()` 覆盖为升序 2000 根，从而掩盖问题；一旦补拉失败，就会用倒序数据训练，直接污染模型。

---

## 3. 1H / 4H / 5m 的实证对比

| 周期 | 可用历史 | Walk-Forward | 结果 |
|---|---|---|---|
| 1H | 6000 根（约 250 天） | 5 折 | 77 笔，胜率 46.75%，收益 +22.41%，PF 1.50，Sharpe 2.44；另一次 92 笔，胜率 78.26%，+83.47% |
| 4H | 600 根（约 100 天） | 1 折 | 9 笔，胜率 44.44%，收益 -10.40%，PF 0.30 |

来源：`reports/btc_timeframe_compare_20260818_021328.json`、`reports/btc_timeframe_compare_20260818_015214.json`。

判定：
- 1H 的两次结果差异极大（46.75% vs 78.26%），说明**结论对阈值/样本切分高度敏感，当前不具备统计置信度**；
- 4H 数据量连 1 折都勉强，样本 9 笔，不能作为决策依据；
- 5m 历史从未用于生产推理，也没有可信回测。

---

## 4. 低胜率的真实证据（周期之外）

### 4.1 实盘成交

`scripts/data/bcrm_trades.db`（50 笔已平仓）：

| 期间 | 笔数 | 胜 | 胜率 | 累计 pnl% |
|---|---|---|---|---|
| 2026-08 | 7 | 4 | 57.1% | +38.56% |
| 2026-10 | 42 | 14 | 33.3% | -19.12% |
| 2026-11 | 1 | 0 | 0% | 0（平出） |

分币种：ARB 0/7、SNDK 0/4、NVDA 0/3、COIN 0/2；SOL 27 笔样本中仅 2 胜（`runtime/paca_performance_cache.json`，胜率 7.4%）。

### 4.2 战略层把风格锁死

`runtime/five_domain_state.json`（2026-11-13）：

- `war_state`：crypto / precious_metal / us_stock 全为 `RESTRICT`；
- `allowed_style_mask`：三类资产均只允许 `mean_revert`、`volatility`、`emergency`，`trend_follow` / `breakout` / `momentum` 全为 false；
- `aggregate_position_cap_pct` = 0.2；`direction_bias.crypto_usdt` = -9.45。

五域评分：dao 48 / tian 56 / di 53 / jiang 72 / fa 82 → 加权约 59 分，卡在 RESTRICT（解冻线 60）。即市场偏趋势/突破时，系统只能做均值回归，胜率自然被压制。

### 4.3 权重退化 + 代理值

`runtime/five_domain_subindicator_ic_weights.json`：

- `crypto_usdt.dao.cycle = 0.9774`（几乎全部权重押在 cycle 单指标）；
- 权重优化脚本自身注明大量字段用**代理值**（VIX 代理政策情绪、价格分位代理 4 年周期等）：`five_domain_weight_optuna.py#L46-L95`。

这类权重不是从真实因果数据学到，而是对代理字段的过拟合，属于应优先「重置/回退」的对象。

### 4.4 置信度校准失真

`runtime/bcrm2_tactical_state.json` 中最新一批推理置信度为 0.66~0.98，而实盘同期胜率只有三成左右。再叠加 `--confidence 0.7955` 的高门槛，等于「只在高置信度下开仓，但高置信度并不代表高胜率」。

---

## 5. 重置范围与安全边界

| 对象 | 位置 | 性质 | 建议 |
|---|---|---|---|
| BCRM2 模型缓存 | `scripts/data/bcrm2_models/`（369 个） | 纯派生缓存，可在启动时重建 | **可重置**（先归档再清空） |
| 五域最优权重 | `runtime/five_domain_optimal_weights.json` | 回测产物 | **可重置**，回退等权 0.2 更安全 |
| 五域子指标 IC 权重 | `runtime/five_domain_subindicator_ic_weights.json` | 代理值过拟合产物 | **建议重置** |
| 自适应 alpha | `data/alpha_rollout_state.json`（current_alpha=0.1，FMA 关闭） | 在线灰度状态 | 可回退 0（纯硬编码权重） |
| 交易证据 | `scripts/data/bcrm_trades.db` | 真实成交，唯一评估依据 | **禁止重置** |
| 分币胜率统计 | `runtime/paca_performance_cache.json` | 真实胜率统计（隐含交易结果） | **禁止重置**，否则永远学不到 SOL 7.4% 这类结论 |

---

## 6. 建议方案（按优先级）

### P0 口径对齐（不改周期，先消除重绘/截断）

1. 推理只用**已收盘** 1H bar：过滤 `confirm=0`，或在整点后 60s 才推理一次；同一根 bar 内只更新持仓监控，不重算方向。
2. `kline_limit` 从 200 提到 ≥1000（长回看特征需要），并对齐训练窗口。
3. 模型缓存键改为「symbol + timeframe + 最后一根已收盘 bar」，避免未收盘 bar 参与 key。
4. 修 `_trigger_bcrm2_retrain()`：显式 `sort_index()` + DatetimeIndex，避免倒序训练。

### P1 重置 + 重训 + 同测试集对比

1. 归档并清空 `bcrm2_models/`；两个五域权重文件回退等权。
2. 用已收盘 1H、≥2000 根、固定币种池重训，做 5 折 walk-forward。
3. 与现网基线在同一测试集上比：胜率、单笔期望、PF、最大回撤、样本数。
4. 只有在「期望 > 0 且 PF > 1.2 且回撤不劣化」时才切换；否则保持现状并回滚。

### P2 战略层复核

`RESTRICT` + 风格白名单 + `direction_bias` 是否符合当前行情；若长期只允许均值回归，1H/4H 的选择都不会改变结果。

### 不建议

- 改成 5m 推理：噪声更大、成本更高、无历史验证；
- 换 4H：数据只有约 600 根，1 折 9 笔，无法验证；
- 直接清空交易库/胜率缓存：会丢失唯一可信评估基准。

---

## 7. 验收标准（重置后）

- 推理输入 100% 为已收盘 bar（日志可核对 bar 时间与 confirm）；
- 特征窗口与训练窗口一致（≥1000 根）；
- walk-forward 5 折、每折 ≥30 笔；
- 胜率、单笔期望、PF、最大回撤四项与基线同表对比；
- 先 shadow 24h，无异常开仓后再切实盘。

---

## 8. 实施结果（2026-11-18）

### 8.1 战略层删除与 43 解耦

- 已删除 11 域战略层 14 个模块及对应测试（`scripts/memory_l4/tests` 12 个 + 根 `tests` 9 个）；18 域 `data-center fivedomain` CLI 同步移除。
- `polling_trader` 已移除：战略层初始化、日级五域更新、带宽影子、策略独立开仓、策略选择影子块。
- 保留 `five_domain_sqlite_reader.py` / `_five_domain_store_port.py`：BCRM2 宏观特征与诊断仍在用，不属于战略决策层。
- 43 域已解耦：`strategy_algo_layer` 改本地权重表；`five_domain_feature_computer` 修正「9-基本面分析」路径；P3 比对脚本在 11 模块缺失时归档退出。
- **额外修复**：`ExitManager` 原先把占位组合链注入 `_chains["default"]`，占位策略恒返回 pass，导致真实 7 策略被旁路。删除战略层后自动回退 legacy 链，真实离场策略恢复正常执行（`timeout_profit_switch` / `signal_reverse` 等）。

### 8.2 P0 修复

| 项 | 实现 | 状态 |
|---|---|---|
| 只用已收盘 bar | `_load_kline_from_okx(closed_only=True)`；`data_fetcher` 过滤 `confirm!=1`；`_infer_bcrm2` 双保险剔除 | 完成 |
| 按已收盘 bar 缓存 | `_get_inference_klines`，key=(inst_id, bar, 当前 bar 开盘 ts) | 完成 |
| 回看 200→1000 | `kline_limit=1000`；`limit>300` 走 `history-candles` 分页，失败回退 300 | 完成 |
| 重训时序 | `_trigger_bcrm2_retrain` 改用 `_kline_to_dataframe`（升序 DatetimeIndex + 已收盘） | 完成 |

验证：6 个改动文件 `py_compile` 通过；`import polling_trader` 成功；`closed_only` 单测 3→2 通过；`test_shadow_mode_gate` 5 passed；`test_multi_coin_scenario_verify` 通过。

待观测：下一轮实盘/影子跑批后核对「日志中推理 bar 时间 = 已收盘时间」「同一 1H 内信号不再漂移」「单轮拉取耗时可接受」。4H 与权重重置（P1）尚未执行。
