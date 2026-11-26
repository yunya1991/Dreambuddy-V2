# FIXLIST · 数据供给 / Ripple Quantum / Granger 放宽（2026-11-26）

## 1. 调查结论（云端取证，2026-11-26 01:00 CST）

### 1.1 清算数据「有，但 23 读错库」
- 18 域已迁 PostgreSQL：`data_center` 库 `records` 表；23 `entry_runner` 仍传 sqlite 路径
  `18-数据获取中心/data_center.db`，该文件仅剩 1 条 bgeometrics 记录。
- PG 实际数据（新鲜）：
  - `panewslab` / `derivatives_spot`：205 条，最新 2026-11-26T01:03Z，4h 一次；
    含 `fut_liq_total_24h_usd`、`fut_liq_long_24h_usd`、`fut_liq_short_24h_usd`、
    `fut_open_interest_usd`、`futN_{SYM}_liq24`。
  - `okx_derivatives`：445 条，最新 01:00Z；仅 funding / 多空比 / OI / 主动买卖量，
    **无清算字段**（OKX/Binance 公开 REST 不提供历史清算聚合；Binance 仅 WS forceOrder）。
  - `coinglass`：仅 `funding_rate`（628 条）；清算端点需付费 Key，云端未配置。
- 结论：清算 24h 聚合以 panewslab（Coinglass 代理）为源，不新增 OKX/Binance 采集器。

### 1.2 情绪数据「有，但查询条件漂移」
- PG `odaily_newsflash`：5500 条，最新与当前时间同步；正文在 `metrics.description`（HTML）。
- 23 `SentimentBridge` 查的是 `source='odaily' AND sub_category='newsflash'` —— 源名不匹配，
  且读 sqlite 旧库 → 恒返回 0.5（N2 `news_sentiment_score=0.5` 的直接原因）。
- 39 域 FinBERT 链路正常；23 复用 `9-基本面分析/engines/sentiment_engine.py`，
  云端 venv-trading 已有 transformers 5.20 / torch 2.14，模型目录
  `18-数据获取中心/models/finbert-tone-chinese` 存在。

### 1.3 Granger
- `no_significant_granger` 71.9% 的主因是多重比较校正（per_dim α=0.0167），
  不是维度数据缺失。云端实测通过率：per_dim 28.7% → 原始 0.05 47.4% → 0.10 65.9%。

## 2. 本次代码改动
| 文件 | 改动 |
| --- | --- |
| `adapters/data_center.py` | 新增 PG 后端（`EVOLUTION_DATA_CENTER_PG=1` 启用，psycopg2；密码复用 `~/.dreambuddy-pg.env`），sqlite 兼容回退；`liq_index_change` 改为「最新记录 vs 上一条采集记录」（冷启动即有值）；per-coin 支持云端扁平键 `futN_{SYM}_liq24/oi`；新增 `query_recent_newsflash()`（odaily_newsflash 优先 + HTML 剥离） |
| `adapters/sentiment_bridge.py` | 复用 `query_recent_newsflash()`，修正源名与正文字段 |
| `engines/ripple_engine.py` | Quantum 默认纳入龙头检测；`EVOLUTION_RIPPLE_INCLUDE_QUANTUM=0` 可恢复 §0.7.5 排除 |
| `core/granger_pipeline_adapter.py` | `DEFAULT_CORRECTION` per_dim → none（α=0.05） |
| `evolution_pipeline.py` | 修复 `_normalize_close_key` 对 numpy 序列做真值判断的 ambiguous truth 崩溃 |

## 3. 部署（云端，需用户确认后执行）
1. 代码走 GitHub → 云端 `git pull`。
2. 追加 systemd drop-in：
   ```
   Environment="EVOLUTION_DATA_CENTER_PG=1"
   ```
   （密码由 `/home/luke/.dreambuddy-pg.env` 发现，无需写入 unit）
3. 重启 `dreambuddy-entry23.service`；观察 N2 `liq_mode`、`news_sentiment_score` 不再恒 0.5、
   `ripple_is_source_ratio` 上升。

## 4. d_star 重裁决证据（云端 `backtest_ri_gate.py --klines`，2026-11-26）

真实 1H K 线 walk-forward（BTC/ETH/SOL × 1000 bars，R_reflexivity 按脚本代理固定 0.65）：

| 口径 | h=4h WAIT | h=4h 每样本 | h=24h WAIT | h=24h 每样本 | h=24h MDD |
| --- | --- | --- | --- | --- | --- |
| legacy `sm×rf` | 71.2% | +0.0087% | 66.7% | -0.5825% | 83.30% |
| calibrated margin 0 | 89.6% | -0.0553% | 86.8% | -0.3446% | 55.02% |
| calibrated margin 0.10 | 96.5% | -0.0266% | 95.6% | -0.1299% | 26.01% |
| calibrated margin ≥0.20 | 100% | 0 | 100% | 0 | 0 |

结论：
- 在当前 wait 公式 `(1-R_smooth)×R_reflexivity` 下，margin ≥0.20 会把全部样本判为 WAIT；
  云端 0.30 与实测 0 成交一致，0.10 也仅剩零星成交 —— **问题在 wait 量纲，不在 margin 数值**。
- 该脚本的 R_reflexivity 是固定代理（不含真实 liq/sentiment），无法用于重拟公式。
  正确顺序：先部署本次数据修复 → 采集 1–2 天真实 N2 `R_reflexivity` 分布 → 再重拟 wait
  归一化并重跑网格。

待裁决：
1. 临时是否把 drop-in 的 0.10 收编进仓库 unit（消除配置漂移），或恢复 0.30？
2. wait 公式修法二选一：①对 `R_reflexivity` 做历史分位归一化后再乘；②改为机会成本形式
   `wait = R_smooth × (1 - R_reflexivity)`。两者都需真实分布回归后定。

## 5. 最终裁决（2026-11-26，用户批准后已上云）

### 5.1 margin
drop-in 0.10 已收编进仓库 unit（`EVOLUTION_DSTAR_WAIT_MARGIN=0.10`），消除漂移。

### 5.2 R_reflexivity 历史分位归一化（方案①）
实现：`core/reflexivity_normalizer.py`
- 因果 ECDF（滚动 2000 样本，`runtime/reflexivity_history.json` 持久化，写盘节流）
- 样本 <50 时线性回退（0.35→0，0.85→1），冷启动可用
- calibrated wait = `(1-R_smooth) × pct × WAIT_SCALE`，`WAIT_SCALE` 默认 2.0
- 开关 `EVOLUTION_DSTAR_REFL_NORM=1`（仓库默认关，保持旧行为；云端 drop-in 开启）
- N4 事件新增 `R_reflexivity_pct` / `wait_scale` 可观测字段

### 5.3 回测（云端真实 1H K 线，BTC/ETH/SOL × 1000 bars）
`scripts/backtest_ri_gate.py --klines-norm`（因果滚动 ECDF，h=4h/24h）：

| 口径 | h=4h 成交率 | h=4h 每样本 | h=4h MDD |
| --- | --- | --- | --- |
| legacy | 0.0% | 0 | 0 |
| flip raw +10% | 0.0% | 0 | 0 |
| norm ×1.0 ~ ×1.5 | 0.0% | 0 | 0 |
| norm ×1.75 | 3.8% | -0.036% | 10.5% |
| norm ×2.0 +10% | 14.2% | -0.125% | 33.4% |
| norm ×2.0 +15% | 8.0% | -0.093% | 24.4% |

说明与取舍：
- 该回测的 `R_smooth = 1-r²` 在趋势段≈0.05，远低于生产实测 p50≈0.58，
  因此“解锁阈值”被推到 ×1.75 以上；**不能直接用其收益结论定 scale**。
- 按生产 `R_smooth` p50=0.58、`R_reflexivity` 分位中位 0.5 计算：
  ×2.0 → wait≈0.42，与方向代价中位≈0.45 同尺度，符合“可比”目标，故取 **scale=2.0**。
- 该窗口（288/228 样本、3 品种、仅趋势方向代理）呈负期望，尚不足以证明策略 edge；
  本次定位是**结构性量纲校准**，用于让 N8 不再恒 WAIT 并开始积累真实分布。
- 复评条件：`runtime/reflexivity_history.json` ≥500 条且 N8 实际成交 ≥30 笔后，
  用真实 `R_reflexivity`/`R_smooth` 分布重跑网格，再决定 scale 与 margin。

### 5.4 Quantum 放量门槛
`RippleEngine` 对 `scale_class=Quantum` 取 `min(调用门槛, 1.5)`，
环境变量 `EVOLUTION_RIPPLE_QUANTUM_VOL_RATIO`（默认 1.5）可覆盖；
`EVOLUTION_RIPPLE_INCLUDE_QUANTUM=0` 可回退旧排除口径。

### 5.5 云端生效状态
drop-in：`10-dstar.conf`(calibrated/0.10)、`10-refl-v2.conf`、`20-datacenter-pg.conf`、
`30-dstar-refnorm.conf`(REFL_NORM=1, WAIT_SCALE=2.0)；entry23 已重启并 active。

### 5.6 分位映射去噪（2026-11-26 追加）

现象：entry23 11-26 03:00–11:55 CST 连续 8.5h 全 WAIT 触发 `DstarCalibratedAllWait`(P2)，
重启（03:55Z）后恢复。实测 `R_reflexivity` 24h 分布 n=370：
`p25=0.54658 / p50=0.54702 / p75=0.54787`，**IQR/|p50| = 0.0024（0.24%）**。

判定：ECDF 会把 0.1% 量级的抖动放大成 0~1 的秩，wait 因此近乎按秩随机 → d_star 抖动。
去噪实现（默认关闭，行为不变）：
- `reflexivity_normalizer.percentile` 增加离散度门槛 `EVOLUTION_DSTAR_REFL_MIN_REL_IQR`（默认 0=关）；
  当 `IQR/|p50| < 门槛` 时退化为**线性锚点映射**（沿用冷启动 0.35→0 / 0.85→1），
  即 0.547→0.394，wait=(1-R_smooth)×0.788——与 03:55Z 重启后实际恢复成交的口径一致且无秩抖动。
- 建议云端取 **0.02**（当前实测 0.0024 必然触发退化），观察 N4 `d_star_calibrated` 抖动率后再定。
- 未做：`R_reflexivity` 本身近乎常数（AVGO/XPT 触发 `ReflexivityConstant`），根因在
  sentiment/spread/corr 分项输入，属上游数据问题，不在本次口径调整范围。

可观测量补齐：N4 `d_star_shadow` 之前只写 5 字段，已补 `R_reflexivity_pct` / `wait_scale`
（`kline_event_handler.py`），与 §5.2 描述一致。

