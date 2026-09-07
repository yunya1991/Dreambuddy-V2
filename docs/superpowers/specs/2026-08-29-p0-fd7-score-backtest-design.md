# P0：五维+7引擎评分回测引擎设计 Spec

> **日期**：2026-08-29
> **状态**：待用户 Review
> **前置**：Gap1/Gap2/Gap3 已完成（7 引擎 Shadow 全绿 reason=FD7_OK）
> **范围**：仅验证五维评分 + 7 引擎 boost 在历史 K 线上的评分效果，不涉交易决策

---

## §1 背景与动机

### 1.1 现状

Gap1/2/3 完成后，7 引擎 Shadow 审计已全绿（`reason_code=FD7_OK`，`fd_S_dao_mean=0.043`，`fd_A_dao_mean=0.012`）。但**无法量化评估 7 引擎接入的实际效果**——Shadow JSONL 仅记录实时审计值，不产生收益曲线，无法回答"五维评分是否能区分好坏标的"这一核心问题。

### 1.2 目标

构建独立回测引擎，从 OKX 拉取 BTC/ETH/SOL 6 个月 1H K 线历史数据，逐 bar 调用 `FiveDomainFeatureComputer.compute()` 生成五维评分，按评分生成简单信号模拟收益，用 empyrical 计算风险指标。

### 1.3 非目标

- ❌ 不做全链路交易回测（不模拟 OKX 撮合/仓位管理/止损止盈）
- ❌ 不修改生产代码（polling_trader / five_domain_feature_computer / five_domain_scorer）
- ❌ 不接入 BCRM 2.0 交易决策逻辑
- ❌ 不做参数优化（hyperopt / grid search）

---

## §2 数据源

### 2.1 K 线历史数据

| 维度 | 值 |
|---|---|
| 来源 | OKX Public API `/api/v5/market/candles` |
| 标的 | BTC-USDT-SWAP / ETH-USDT-SWAP / SOL-USDT-SWAP |
| 周期 | 1H |
| 时长 | 6 个月（约 4320 根 K 线/标的） |
| 字段 | ts, open, high, low, close, vol |
| 存储 | 内存 DataFrame（不落盘，回测结束即释放） |
| 限速 | OKX 公开 API 20 次/2s，每次返回 max 300 根，分页拉取 |

### 2.2 chain/news 数据（模拟）

`data_center.db` 仅 4 天数据，不足以覆盖 6 个月回测区间。方案：

- `_fetch_news_72h_limit200()` **mock 为固定 news_list**（5 条模拟新闻），保证 7 引擎 S 级 boost 可计算。mock news_list 内容固定为 2 条正面 + 2 条负面 + 1 条中性，覆盖 BTC/ETH/SOL 三个标的
- chain 数据用 K 线技术指标模拟构造（RSI/MACD/布林带 → coin_data 字段）
- **技术指标计算**：用 pandas 手算 RSI(14)/MACD(12,26,9)/布林带(20,2)/MA(20)/MA(60)/ATR(14)/VOL(20)，不引入 TA-Lib 依赖

### 2.3 system_state 构造

每个 bar 的 system_state 从历史滚动窗口计算：

```python
system_state = {
    "win_rate": rolling_win_rate,       # 过去 30 bar 多空胜率
    "profit_factor": rolling_pf,         # 过去 30 bar 盈亏比
    "factor_coverage_pct": 0.85,         # 固定值
}
```

---

## §3 coin_data 构造

每个 bar 的 coin_data 按资产类构造：

### 3.1 crypto_usdt 子结构

```python
coin_data = {
    "crypto_usdt": {
        "BTC-USDT": {
            "close": close_price,
            "rsi": rsi_14,                    # 14 期 RSI
            "macd": macd_value,               # MACD histogram
            "boll_upper": boll_upper,         # 布林上轨
            "boll_lower": boll_lower,          # 布林下轨
            "ma20": ma20,                     # 20 期均线
            "ma60": ma60,                     # 60 期均线
            "vol_20": volume_ma20,            # 20 期均量
            "atr_14": atr_14,                 # 14 期 ATR
            "pct_change_1h": pct_change,      # 1H 涨跌幅
            "pct_change_24h": pct_24h,        # 24H 涨跌幅
        },
        "ETH-USDT": { ... },  # 同结构
        "SOL-USDT": { ... },  # 同结构
    }
}
```

### 3.2 us_stock / precious_metal

回测区间内不构造这两类数据（设为 `None`），`_resolve_class_coin_data` 返回 `None` 时 `compute()` 会 fail-open 返回中性分 50。

---

## §4 回测引擎流程

```
┌─────────────────────────────────────────────┐
│ 1. 拉取 OKX K 线（BTC/ETH/SOL 6 个月 1H）    │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│ 2. 逐 bar 遍历（t = 0, 1, ..., N-1）         │
│    a. 用 t 之前的数据构造 coin_data          │
│    b. 用 t 之前 30 bar 构造 system_state     │
│    c. 调 compute(coin_data, system_state)    │
│    d. 记录五维评分 + 7引擎 boost（mock news） │
│    e. 按 dao 评分生成信号                    │
│       dao > 60 → signal = +1（看多）         │
│       dao < 40 → signal = -1（看空）         │
│       40 ≤ dao ≤ 60 → signal = 0（中性）     │
│    f. 计算 bar 收益：                         │
│       bar_return = signal × pct_change(t→t+1)│
│    g. 累积净值曲线                            │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│ 3. 用 empyrical 计算风险指标                  │
│    sharpe_ratio / sortino_ratio              │
│    max_drawdown / calmar_ratio               │
│    annual_return / annual_volatility          │
│    tail_ratio / omega_ratio                  │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│ 4. 输出回测报告                               │
│    a. 控制台摘要表                             │
│    b. JSON 报告文件                            │
│    c. 净值曲线 CSV                             │
└─────────────────────────────────────────────┘
```

### 4.1 Point-in-Time 防泄漏

**铁律**：每个 bar t 的 `compute()` 调用只使用 `[0, t-1]` 区间的数据。具体：

- RSI/MACD/MA 等技术指标用 `df.iloc[:t+1]` 计算（含当前 bar 的 close）
- system_state 的 win_rate 用 `[t-30, t-1]` 窗口
- 信号在 bar t 收盘后生成，收益在 `[t, t+1]` 实现
- **不使用未来数据**（`df.iloc[t+1:]` 不可访问）

### 4.2 7 引擎 boost 的回测参与

- S1 Sentiment：`_fetch_news_72h_limit200()` mock 为固定 5 条新闻 → `fd_S_dao_mean` 非零
- A6 LeastResistance：从 result dao 评分构造 r3d（Gap3 已实现）
- A7 SignalEngine：从 system_state win_rate/profit_factor 构造 signal（Gap3 已实现）
- **生产注入红线保持 False**：回测中 `enable_fundamental_7engines_production_injection = False`，7 引擎只影响 Shadow 审计值，不影响 result 评分

### 4.3 评分信号映射

| dao 评分区间 | 信号 | 含义 |
|---|---|---|
| > 60 | +1 | 看多（持有多头） |
| < 40 | -1 | 看空（持有空头） |
| 40-60 | 0 | 中性（空仓） |

**收益计算**：`bar_return = signal × (close[t+1] / close[t] - 1)`

**净值**：`nav[t+1] = nav[t] × (1 + bar_return)`

---

## §5 输出指标

### 5.1 empyrical 风险指标（每个标的一个）

| 指标 | empyrical API | 含义 |
|---|---|---|
| Sharpe Ratio | `sharpe_ratio(returns)` | 风险调整后收益（>1 合格，>2 优秀） |
| Sortino Ratio | `sortino_ratio(returns)` | 下行风险调整后收益 |
| Max Drawdown | `max_drawdown(returns)` | 最大回撤（越接近 0 越好） |
| Calmar Ratio | `calmar_ratio(returns)` | 年收益 / 最大回撤 |
| Annual Return | `annual_return(returns)` | 年化收益率 |
| Annual Volatility | `annual_volatility(returns)` | 年化波动率 |
| Tail Ratio | `tail_ratio(returns)` | 尾部盈亏比 |
| Omega Ratio | `omega_ratio(returns)` | 概率加权盈亏比 |

### 5.2 自定义统计

| 指标 | 计算 |
|---|---|
| 胜率 | `signal != 0 且 bar_return > 0 的比例` |
| 盈亏比 | `mean(盈利 bar) / abs(mean(亏损 bar))` |
| 信号覆盖率 | `signal != 0 的 bar 占比` |
| 多头占比 | `signal == +1 的 bar 占比` |
| 空头占比 | `signal == -1 的 bar 占比` |
| 总交易次数 | `signal 变化的次数` |

### 5.3 对比基准

| 基准 | 计算 |
|---|---|
| Buy & Hold | `nav_bh = close[-1] / close[0]` |
| 随机信号 | `signal = random.choice([-1, 0, 1])`（跑 1000 次取均值） |

---

## §6 文件结构

```
11-易经推理系统/
├── tests/
│   ├── test_p0_backtest_engine.py      # TDD 测试（8 TC）
│   └── backtest_fd7_score.py           # 回测引擎实现
├── scripts/
│   └── runtime/
│       └── backtest_reports/            # 回测报告输出目录
│           ├── btc_backtest_20260829.json
│           ├── eth_backtest_20260829.json
│           ├── sol_backtest_20260829.json
│           └── btc_nav_curve_20260829.csv
```

### 6.1 回测引擎接口

```python
# backtest_fd7_score.py

class FD7ScoreBacktester:
    """五维+7引擎评分回测引擎。"""

    def __init__(self, symbol: str, timeframe: str = "1H", period_days: int = 180):
        self.symbol = symbol
        self.timeframe = timeframe
        self.period_days = period_days

    def fetch_klines(self) -> "pd.DataFrame":
        """从 OKX 拉取 K 线历史数据。"""
        ...

    def build_coin_data(self, df: "pd.DataFrame", t: int) -> dict:
        """用 [0, t] 区间数据构造 coin_data（PIT 防泄漏）。"""
        ...

    def build_system_state(self, df: "pd.DataFrame", t: int) -> dict:
        """用 [t-30, t-1] 窗口构造 system_state。"""
        ...

    def run_backtest(self) -> dict:
        """执行完整回测，返回指标报告。

        返回结构：
        {
            "symbol": "BTC-USDT",
            "bars": 4320,
            "empyrical": {
                "sharpe_ratio": float,
                "sortino_ratio": float,
                "max_drawdown": float,
                "calmar_ratio": float,
                "annual_return": float,
                "annual_volatility": float,
                "tail_ratio": float,
                "omega_ratio": float,
            },
            "custom": {
                "win_rate": float,
                "profit_factor": float,
                "signal_coverage": float,
                "long_ratio": float,
                "short_ratio": float,
                "total_trades": int,
            },
            "benchmark": {
                "buy_hold_return": float,
                "random_signal_mean_sharpe": float,
            },
            "nav_curve": list[float],   # 净值曲线（长度 = bars）
        }
        """
        ...

    def generate_report(self, results: dict, output_dir: str) -> str:
        """生成 JSON 报告 + CSV 净值曲线，返回报告路径。"""
        ...
```

---

## §7 TDD 测试清单（8 TC）

| TC | 描述 | 验证点 |
|---|---|---|
| TC-1 | OKX K 线拉取 | `fetch_klines()` 返回 DataFrame，len ≥ 4000，含 ts/open/high/low/close/vol 列 |
| TC-2 | coin_data 构造 PIT 防泄漏 | `build_coin_data(df, t=100)` 只含前 100 bar 的数据，不含 t=101+ |
| TC-3 | system_state 构造 | `build_system_state(df, t=50)` 返回 win_rate ∈ [0,1]、profit_factor > 0 |
| TC-4 | compute() 返回五维评分 | `compute(coin_data, system_state)` 返回 dict 含 dao/tian/di/jiang/fa，值 ∈ [0, 100] |
| TC-5 | 信号生成 | dao > 60 → signal=+1；dao < 40 → signal=-1；40-60 → signal=0 |
| TC-6 | 净值曲线计算 | nav[0]=1.0；nav 单调连续；无 NaN |
| TC-7 | empyrical 指标计算 | 返回含 sharpe/max_drawdown/calmar/annual_return 的 dict，无 NaN |
| TC-8 | 报告生成 | JSON 报告文件含全部指标 + CSV 净值曲线文件可读 |

---

## §8 依赖

| 依赖 | 安装方式 | 用途 |
|---|---|---|
| empyrical-reloaded | `pip install empyrical-reloaded` | 风险指标计算（Sharpe/Sortino/MaxDD/Calmar） |
| pandas | 已有 | K 线数据处理 |
| numpy | 已有 | 数值计算 |
| requests | 已有 | OKX API 调用 |

### 8.1 empyrical-reloaded 选用理由

- 原版 `quantopian/empyrical` 已停止维护
- `stefan-jansen/empyrical-reloaded` 是活跃 fork，Apache-2.0
- API 100% 兼容原版：`sharpe_ratio()` / `max_drawdown()` / `calmar_ratio()`
- 轻量纯 Python，无 C 编译依赖

---

## §9 风险与约束

| 风险 | 级别 | 缓解 |
|---|---|---|
| OKX API 限速 | 低 | 分页拉取，每次 300 根，间隔 200ms |
| K 线数据不完整 | 低 | 校验 len ≥ 4000，不足时 skip 该标的 |
| empyrical 安装失败 | 低 | fallback 到 numpy 手算（已有 walk_forward_backtester 的公式） |
| 回测结果失真（mock news） | 中 | 报告中标注"news 数据为 mock"，后续接入真实数据再对比 |
| compute() 耗时过长 | 中 | 4320 bar × 3 标的 = 12960 次调用，预估 < 5min |

---

## §10 后续扩展

| 扩展项 | 条件 | 说明 |
|---|---|---|
| 全链路交易回测 | P0 评分回测验证有效后 | 接入 walk_forward_backtester，模拟 OKX 撮合 |
| 真实 news 数据回测 | data_center.db 积累 ≥ 2 周 | 取消 mock，用真实 72h news_list |
| 参数优化 | P0 回测 Sharpe > 0 | 用 hyperopt 搜索最优 dao 阈值（60/40） |
| 多标的扩展 | P0 验证通过 | 扩展到 20+ 实盘标的 |
| vectorbt 向量化加速 | 回测耗时 > 10min | 用矩阵化替代逐 bar 循环 |
