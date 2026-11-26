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

