# 接口规格文档 — 易经推理系统

> **定位：** 全部公开 CLI / Python API / HTTP 接口的签名、参数、返回值、调用示例
> **版本：** v2.9 | **更新：** 2026-07-25

---

## 目录

- [1. 接口概览](#1-接口概览)
- [2. 认证方式](#2-认证方式)
- [3. PollingTrader 轮询交易器 (scripts/memory_l4/polling_trader.py)](#3-pollingtrader-轮询交易器)
- [4. YijingExitSystem 易经离场系统 (scripts/memory_l4/yijing_exit_system.py)](#4-yijingexitsystem-易经离场系统)
- [5. BCRM2Adapter 辩证ML适配器 (scripts/memory_l4/bcrm2_adapter.py)](#5-bcrm2adapter-辩证ml适配器)
- [6. BCRM 1.0 矛盾力学引擎 (scripts/memory_l4/bcrm/engine.py)](#6-bcrm-10-矛盾力学引擎)
- [7. QMM 量化记忆引擎 (scripts/memory_l4/qmm/engine.py)](#7-qmm-量化记忆引擎)
- [8. L4 记忆管道 (scripts/memory_l4/pipeline.py)](#8-l4-记忆管道)
- [9. 系统诊断 CLI (scripts/memory_l4/inspect.py)](#9-系统诊断-cli)
- [10. BCRM 2.0 回测 CLI (scripts/memory_l4/bcrm2/run_phase0_validation.py)](#10-bcrm-20-回测-cli)
- [11. data_server HTTP 接口 (data_server_fixed.py)](#11-data_server-http-接口)
- [12. 错误码](#12-错误码)
- [13. 版本管理](#13-版本管理)

---

## 1. 接口概览

易经推理系统的对外接口分为三类：

| 类型 | 入口 | 调用方 | 说明 |
|------|------|--------|------|
| **CLI** | `python -m scripts.memory_l4.polling_trader` | launchd / 手动 | 实盘交易主循环，A0-A9 决策链 |
| **CLI** | `python -m scripts.memory_l4.inspect` | 手动 / 启动自检 | 系统健康诊断 |
| **CLI** | `python -m scripts.memory_l4.bcrm2.run_phase0_validation` | 手动 | BCRM 2.0 Phase 0 基线回测 |
| **CLI** | `python -m scripts.memory_l4.pipeline` | 事件触发 | L4 记忆沉淀全链路 |
| **Python API** | `PollingTrader` | 顶层编排 | 实盘交易主类 |
| **Python API** | `YijingExitSystem` | PollingTrader 调用 | 易经离场决策（主离场） |
| **Python API** | `BCRM2Adapter` | PollingTrader 调用 | BCRM 2.0 训练/推理/缓存 |
| **Python API** | `BCRMEngine` / `default_engine()` | PollingTrader 调用 | BCRM 1.0 矛盾力学（Fallback） |
| **Python API** | `run_qmm()` / `run_qmm_with_gate()` | 记忆工作流 | QMM 量化记忆离线内核 |
| **Python API** | `run_pipeline()` | 事件触发 | L4 记忆沉淀管道 |
| **HTTP** | `data_server_fixed.py`（端口 8765） | 前端 / 监控 | 前端数据服务（只读） |

> 生产链路通过 launchd 调度 `polling_trader.py`，**无对外 HTTP 交易服务**。HTTP 接口仅用于前端数据展示，不参与交易决策。

---

## 2. 认证方式

### 2.1 OKX 实盘交易鉴权

- **方式**：API Key + Secret Key + Passphrase（OKX V5 协议）
- **配置来源**：环境变量 / `data/okx_sim/config.json`
- **加载入口**：`OKXSimulatedClient`（`scripts/memory_l4/okx_simulated.py`）
- **支持模式**：实盘 / 模拟盘（`simulated=True/False`）
- **权限要求**：合约交易（SWAP）读取 + 下单 + 平仓 + 查询持仓/余额

### 2.2 HTTP 接口鉴权

- **方式**：**无鉴权**（本地局域网服务，仅监听 `0.0.0.0:8765`）
- **用途**：前端监控面板数据展示（只读）
- **安全约束**：不暴露交易操作，不暴露 API Key；仅返回持仓/状态/统计聚合数据

### 2.3 飞书告警鉴权

- **方式**：飞书机器人 Webhook URL（环境变量配置）
- **用途**：系统异常 / 风控触发 / 模型降级时推送告警
- **入口**：`scripts/memory_l4/yijing_feishu_alert.py` → `notify_system_error()`

---

## 3. PollingTrader 轮询交易器

**文件**：`scripts/memory_l4/polling_trader.py`
**角色**：易经推理系统的实盘交易主循环，编排 BCRM 2.0 / BCRM 1.0 / 八卦力学 / 离场系统 / 风控 / 学习调度。

### 3.1 类签名

```python
class PollingTrader:
    """易经推理轮询交易器（P2 完整版）"""

    def __init__(self,
                 interval: int = 3600,
                 coins: list = None,
                 bar: str = "1H",
                 confidence_threshold: float = 0.55,
                 short_confidence_threshold: float = 0.70,
                 max_positions: int = 3,
                 kline_limit: int = 200,
                 initial_equity: float = 100.0,
                 daily_loss_limit: float = -30.0,
                 max_consecutive_losses: int = 999,
                 default_position_pct: float = 0.10,
                 guardian: ProcessGuardian = None,
                 shared_dir=None,
                 use_bcrm2: bool = True)
```

**参数说明：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| interval | int | 3600 | 轮询间隔（秒），默认 1 小时 |
| coins | list | None | 币种列表（默认 `["BTC","ETH","SOL","BNB","XRP","DOGE"]`） |
| bar | str | "1H" | K线周期 |
| confidence_threshold | float | 0.55 | 做多置信度阈值 |
| short_confidence_threshold | float | 0.70 | 做空置信度阈值（高于做多以减少做空频率） |
| max_positions | int | 3 | 最大同时持仓数 |
| kline_limit | int | 200 | K线获取数量 |
| initial_equity | float | 100.0 | 初始权益（USDT） |
| daily_loss_limit | float | -30.0 | 日亏损兜底固定阈值（USDT），默认-30（150U可用金的20%） |
| max_consecutive_losses | int | 999 | ~~最大连续亏损次数~~ 已禁用（v4.2改为亏损金额比例触发） |
| default_position_pct | float | 0.10 | 默认单笔仓位比例（10%） |
| guardian | ProcessGuardian | None | 进程守护器 |
| shared_dir | Path | None | 共享内存目录 |
| use_bcrm2 | bool | True | 启用 BCRM 2.0（False 则降级 BCRM 1.0） |

**初始化侧载组件**：`BCRMEngine`、`BaguaEngine`、`OKXSimulatedClient`、`PerformanceTracker`、`RiskManager`、`PositionTracker`、`LearningScheduler`、`KnowledgeBridge`、`ClassicExitSystem`、`RangingMarketEnhancer`、`YijingExitSystem`、`IncrementalLearner`、`HybridAnomalyDetector`、`CBRToBCRMBridge`、`A7PracticeGate`。

### 3.2 run_once

```python
def run_once(self) -> None
```

执行一轮完整推理 + 交易。流程：
1. 日期翻转检查 + 外部知识加载
2. 风控状态 + 绩效统计查询
3. 动态置信度阈值调整（`_adjust_confidence_threshold`）
4. 异常检测（Phase 2.1）：遍历币种 K线，`HybridAnomalyDetector` 检测，严重异常时提高阈值 +0.15
5. 遍历币种：`_fetch_and_infer()` → A7 实践论门禁 → `_execute_trade()`
6. 持仓跟踪 + 学习调度状态刷新
7. 守护进程心跳上报

### 3.3 run_loop

```python
def run_loop(self) -> None
```

主轮询循环。注册 `SIGINT` / `SIGTERM` 信号处理，循环调用 `run_once()`，间隔 `self.interval` 秒。退出时停止守护进程。

### 3.4 get_status

```python
def get_status(self) -> dict
```

获取完整运行状态（供 API 查询）。

**返回值：**

```python
{
    "cycle_count": 12,                      # int: 已执行轮次
    "running": True,                        # bool: 是否在循环中
    "interval": 3600,                       # int: 轮询间隔
    "coins": ["BTC", "ETH", ...],           # list[str]: 币种列表
    "bar": "1H",                            # str: K线周期
    "confidence_threshold": 0.55,           # float: 置信度阈值
    "max_positions": 5,                     # int: 最大持仓数
    "risk": {                               # dict: 风控状态
        "daily_pnl": -12.5,
        "consecutive_losses": 1,
        "max_consecutive_losses": 999,      # 已禁用（v4.2改为亏损金额比例触发）
        "loss_limit_pct": 0.20,             # 亏损比例阈值（20%）
        "daily_loss_limit": -30.0,          # 兜底固定阈值（USDT）
        "trading_halted": False,
        # ...其他 RiskManager 字段
    },
    "performance_today": {...},             # dict: 今日绩效
    "performance_overall": {...},           # dict: 历史总绩效
    "open_positions": [                     # list[dict]: 持仓列表
        {
            "coin": "BTC",
            "inst_id": "BTC-USDT-SWAP",
            "direction": "long",
            "entry_price": 67000.0,
            "confidence": 0.72,
            "hexagram": "火天大有",
            "entry_time": "2026-07-25T...",
        },
    ],
    "learning": {...},                      # dict: 学习调度状态
    "guardian": {...},                      # dict: 守护进程状态
}
```

### 3.5 CLI 入口

```bash
python -m scripts.memory_l4.polling_trader [options]
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--interval` | int | 3600 | 轮询间隔（秒） |
| `--coins` | str | "UNI,PUMP,MU,SKHYNIX,HYPE,ETH,BTC,SOL,XAU,XAG,GOOGL,NVDA,AMZN,OKB,BNB" | 币种列表（逗号分隔，15币种固定候选池） |
| `--bar` | str | "1H" | K线周期 |
| `--confidence` | float | 0.35 | 做多置信度阈值 |
| `--short-confidence` | float | 0.70 | 做空置信度阈值 |
| `--max-positions` | int | 5 | 最大同时持仓数 |
| `--once` | flag | False | 只执行一次，不循环 |
| `--initial-equity` | float | None | 初始权益（不指定则从 OKX 读取实际余额） |
| `--daily-loss-limit` | float | -50.0 | 日最大亏损（USDT） |
| `--max-consecutive-losses` | int | 5 | 最大连续亏损次数 |
| `--position-pct` | float | 0.10 | 默认单笔仓位比例 |
| `--no-guardian` | flag | False | 不启用进程守护 |
| `--use-bcrm2` | flag | True | 使用 BCRM 2.0（默认启用） |
| `--use-bcrm1` | flag | False | 使用 BCRM 1.0（降级模式） |

**典型用法：**

```bash
# 单次执行（launchd 调度常用）
python -m scripts.memory_l4.polling_trader --once --coins BTC,ETH

# 长驻轮询
python -m scripts.memory_l4.polling_trader

# 降级到 BCRM 1.0
python -m scripts.memory_l4.polling_trader --use-bcrm1
```

---

## 4. YijingExitSystem 易经离场系统

**文件**：`scripts/memory_l4/yijing_exit_system.py`
**角色**：基于易经卦象的风险-价值评估离场系统。v2 架构反转后为**主离场模块**，可否决 `ClassicExitSystem` 的噪音止损。

### 4.1 YijingExitAction 枚举

```python
class YijingExitAction(Enum):
    """易经离场决策动作"""
    NO_INTERVENE = "no_intervene"    # 不干预，保持 classic 决策
    VETO_CLOSE = "veto_close"        # 否决 close，保持持仓
    VETO_REDUCE = "veto_reduce"      # 否决 reduce
    RAISE_TP = "raise_tp"            # 提高止盈位（价值高时）
    LOWER_SL = "lower_sl"            # 降低止损（风险低时，放宽止损空间）
    LOWER_TP = "lower_tp"            # 降低止盈（风险升高时，提前锁定利润）
    ADJUST_SL_TP = "adjust_sl_tp"    # 同时调整止损止盈
    FORCE_CLOSE = "force_close"      # 强制离场（卦象极度危险）
```

### 4.2 YijingExitDecision 数据类

```python
@dataclass
class YijingExitDecision:
    action: YijingExitAction = YijingExitAction.NO_INTERVENE
    reason: str = ""
    yijing_risk_score: float = 0.5       # 0-1，越高越危险
    yijing_value_score: float = 0.5      # 0-1，越高越有价值
    hexagram_name: str = ""
    risk_level: str = ""                 # 高/中/低
    current_phase: str = ""              # 潜龙勿用/见龙在田/.../亢龙有悔
    development_stage: str = ""          # 萌芽期/成长期/成熟期/衰退期
    direction_consistent: bool = True    # 卦象方向与持仓方向是否一致
    tp_adjust_pct: float = 0.0           # RAISE_TP/LOWER_TP 时的调整比例
    sl_adjust_pct: float = 0.0           # LOWER_SL 时的调整比例（正数表示放宽）
    confidence: float = 0.5
    should_log: bool = True
```

### 4.3 YijingExitConfig 数据类

包含风险评分权重（`weight_risk_level=0.35` / `weight_phase=0.25` / `weight_development=0.20` / `weight_direction_consistency=0.20`）、否决阈值、提高止盈阈值、降低止损阈值、降低止盈阈值、强制离场阈值，以及卦象阶段映射表（`phase_risk_map` / `phase_value_map` / `stage_risk_map` / `stage_value_map` / `risk_level_map` / `direction_consistency_map`）。

**关键阈值（v2.9 P1 修复后）：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `veto_risk_threshold` | 0.35 | 风险分 < 此值才允许否决 |
| `veto_value_threshold` | 0.60 | 价值分 > 此值才允许否决 |
| `raise_tp_value_threshold` | 0.58 | 价值分 > 0.58 才提高 TP（P1 从 0.70 下调） |
| `force_close_risk_threshold` | 0.65 | 风险分 > 0.65 且方向冲突 → 强制 close（P1 从 0.80 下调） |
| `raise_tp_adjust_pct` | 0.30 | TP 上浮 30% |
| `lower_sl_adjust_pct` | 0.50 | SL 放宽 50% |

### 4.4 类与方法

```python
class YijingExitSystem:
    def __init__(self, config: Optional[YijingExitConfig] = None)
    def set_log_callback(self, callback) -> None
    def evaluate(self,
                 hexagram: Any,
                 pos_side: str,
                 entry_price: float,
                 current_price: float,
                 position_age_sec: float,
                 unrealized_pnl_pct: float,
                 classic_decision: Any = None,
                 mfe_pnl_pct: float = 0.0) -> YijingExitDecision
    def calibrate_from_trades(self, trades: List[Any], min_samples: int = 5) -> Dict[str, Any]
    def snapshot_config(self, label: str = "") -> Dict[str, Any]
    def restore_config(self, snapshot: Dict[str, Any]) -> bool
```

### 4.5 evaluate 参数

| 参数 | 类型 | 说明 |
|------|------|------|
| hexagram | Any | 卦象对象（YijingResult 或 dict），需含 `risk_level`/`current_phase`/`development_stage`/`direction_hint` |
| pos_side | str | 持仓方向 `long` / `short` |
| entry_price | float | 入场价 |
| current_price | float | 当前价 |
| position_age_sec | float | 持仓时长（秒） |
| unrealized_pnl_pct | float | 未实现盈亏比例（如 0.02 = +2%） |
| classic_decision | Any | `classic_exit_system` 的决策（可选，用于否决判断） |
| mfe_pnl_pct | float | 最大盈利幅度（默认 0.0） |

**决策路径：**
1. 无卦象数据 → `NO_INTERVENE`（fail-open）
2. 卦象 `risk_level=高` + 方向冲突 + 风险分 ≥ 0.65 → `FORCE_CLOSE`
3. 价值分 > 0.58 + 成长期/成熟期 + 飞龙在天/或跃在渊 + 已盈利 → `RAISE_TP`
4. classic 决策为 CLOSE/REDUCE + 风险低 + 价值高 + 未破关键位 → `VETO_CLOSE` / `VETO_REDUCE`

**调用示例：**

```python
from scripts.memory_l4.yijing_exit_system import YijingExitSystem, YijingExitAction

yijing_exit = YijingExitSystem(config=YijingExitConfig())
yijing_exit.set_log_callback(lambda msg, level: print(f"[{level}] {msg}"))

decision = yijing_exit.evaluate(
    hexagram=inference.get("hexagram_result"),
    pos_side="long",
    entry_price=67000.0,
    current_price=68500.0,
    position_age_sec=3600,
    unrealized_pnl_pct=0.022,
    classic_decision=classic_decision,
    mfe_pnl_pct=0.035,
)

if decision.action == YijingExitAction.VETO_CLOSE:
    # 否决 classic 的 CLOSE，保持持仓
    pass
elif decision.action == YijingExitAction.FORCE_CLOSE:
    # 卦象极度危险，强制离场
    trader.close_position(...)
```

---

## 5. BCRM2Adapter 辩证ML适配器

**文件**：`scripts/memory_l4/bcrm2_adapter.py`
**角色**：封装 `DialecticalMLEngine`，提供与 BCRM 1.0 兼容的 `infer()` 接口；含模型缓存、五角校验 v4（BCRM2×力学×A0×Ising×TDA 五源风险信号综合评分→双向风控）。

### 5.1 类签名

```python
class BCRM2Adapter:
    def __init__(self,
                 symbol: str,
                 timeframe: str = "1H",
                 model_cache_dir: str = None,
                 train_bars: int = 2000,
                 tp_atr: float = 3.0,
                 sl_atr: float = 1.5,
                 max_hold_bars: int = 60)
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| symbol | str | — | 交易对符号（如 "BTC"） |
| timeframe | str | "1H" | 时间周期 |
| model_cache_dir | str | None | 模型缓存目录（默认 `data/bcrm2_models/`） |
| train_bars | int | 2000 | 训练用 K 线数量 |
| tp_atr | float | 3.0 | 止盈 ATR 倍数 |
| sl_atr | float | 1.5 | 止损 ATR 倍数 |
| max_hold_bars | int | 60 | 最大持仓 K 线数 |

### 5.2 train

```python
def train(self, df: pd.DataFrame, force_retrain: bool = False) -> bool
```

训练 BCRM 2.0 模型。数据不足 200 根返回 False；不足 500 根时尝试通过 `bcrm2.data_fetcher.get_klines` 拉取更多。计算八卦特征 + 经典经验特征 + 斐波那契 + 枢轴点 + RSI 情绪 + WDH 特征，调用 `DialecticalMLEngine` 训练并缓存。

| 参数 | 类型 | 说明 |
|------|------|------|
| df | pd.DataFrame | K线数据，需含 `open/high/low/close/volume` |
| force_retrain | bool | 强制重新训练（忽略缓存） |

**返回：** True=训练/加载成功，False=数据不足或失败

### 5.3 infer

```python
def infer(self, df: pd.DataFrame, idx: int = -1, auto_train: bool = True) -> Dict[str, Any]
```

执行推理，返回与 BCRM 1.0 兼容的格式。模型未就绪时按 `auto_train` 决定是否自动训练。推理链含：BCRM2 ML 推理 → KG 知识图谱校准 → A0 矛盾分析 → 五角校验 v4 风险评分风控（TriangleVerifier）→ fail_closed 判定。

**返回值（成功）：**

```python
{
    "ok": True,
    "next_state": {
        "direction": "UP",              # "UP" | "DOWN" | "FLAT"
        "confidence": 0.72,             # float: 0-1
        "derivation": "BCRM2.0 L1=0.68 L2=0.75 A0_adj=+0.020 TRI_adj=-0.005",
    },
    "hexagram": {                       # 卦象信息
        "hexagram_name": "大有",
        "hexagram_name_cn": "火天大有",
        "changed_hexagram_cn": None,
    },
    "is_fail_closed": <callable>,       # lambda -> bool
    "strategy_branches": [],
    "liangyi_state": None,
    "scale_params": None,
    "a0_analysis": {...},               # A0 矛盾分析结果
    "a0_warnings": [...],               # list[str]: A0 预警
    "triangle_verification": {...},     # 五角校验 v4 结果
    "fail_closed_reason": "",           # str: fail_closed 时的原因
    "position_factor": 1.0,             # v4 风险评分风控：仓位因子（0.60-1.10）
    "sl_tighten_factor": 1.0,           # v4 风险评分风控：止损收紧因子（0.85-1.0）
    "early_exit_signal": False,         # v3 保留：TDA+Ising双预警提前离场
    "leverage_factor": 1.0,             # v4 新增：杠杆因子（0.70-1.05）
    "tp_adjustment": 1.0,               # v4 新增：止盈调整因子（0.90-1.10）
    "risk_score": 0.0,                  # v4 新增：综合风险评分（0=安全, 1=高危）
    "risk_level": "NORMAL",             # v4 新增：风险等级 LOW/NORMAL/MID/HIGH
}
```

**返回值（fail_closed）：**

```python
{
    "ok": False,
    "next_state": {"direction": "FLAT", "confidence": 0.0, "derivation": "<reason>"},
    "hexagram": {"hexagram_name": "未济", "hexagram_name_cn": "火水未济", "changed_hexagram_cn": None},
    "is_fail_closed": <callable returning True>,
    "fail_closed_reason": "<reason>",   # "模型未训练" / "置信度不足" / "三源严重分歧" / "A0创伤信号降级" / "推理失败: ..."
    # ...其他字段为默认值
}
```

**fail_closed 触发条件：**
- 置信度 < 0.3
- A0 创伤信号（连续3次同方向错误）且置信度 < 0.4

> 注：v4 五角校验不再触发 fail_closed（`should_fail_closed` 恒为 False），仅通过风险评分调整仓位/杠杆/止盈/止损。

### 5.4 maybe_retrain

```python
def maybe_retrain(self, df: pd.DataFrame) -> bool
```

检查是否需要重训模型（距上次训练超过 `_train_interval=86400` 秒即 24 小时）。需要时调用 `train(df, force_retrain=True)`。

---

## 6. BCRM 1.0 矛盾力学引擎

**文件**：`scripts/memory_l4/bcrm/engine.py`
**角色**：BCRM 2.0 的 Fallback。基于唯物辩证法 + 矛盾论 + 易经六十四卦的推理引擎。

### 6.1 BCRMEngine

```python
@dataclass
class BCRMEngine:
    min_confidence_threshold: float = 0.25
    qualitative_threshold: float = DEFAULT_QUALITATIVE_THRESHOLD
    sixiang_weights: Dict[str, float] = field(default_factory=dict)

    def infer(self,
              market_snapshot: Dict[str, Any],
              contradiction_list: List[Dict] = None,
              memory_cases: List[Dict] = None,
              qmm_output: Dict = None,
              knowledge_base: Any = None) -> BCRMOutput
```

| 参数 | 类型 | 说明 |
|------|------|------|
| market_snapshot | dict | 市场快照（供需/技术/资金/情绪四维评分） |
| contradiction_list | list[dict] | A0 矛盾列表 |
| memory_cases | list[dict] | L4 历史记忆案例 |
| qmm_output | dict | QMM 量化记忆输出 |
| knowledge_base | Any | 知识库 |

**返回：** `BCRMOutput`（含 `bcrm_version`、`next_state.direction`、`next_state.confidence`、`hexagram` 等）

**七步推理循环**：矛盾识别 → 张力量化 → 质变判定 → 正反合裁决 → 易经翻译 → 阻力方向 → 决策输出。

### 6.2 default_engine

```python
def default_engine() -> BCRMEngine
```

获取默认引擎实例（工厂函数）。

---

## 7. QMM 量化记忆引擎

**文件**：`scripts/memory_l4/qmm/engine.py`
**角色**：QMM 离线内核，从 L4 记忆事件中提取趋势/阻力/不确定性特征。

### 7.1 run_qmm

```python
def run_qmm(
    cases: List[Dict[str, Any]],
    distills: List[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
) -> QMMOutput
```

| 参数 | 类型 | 说明 |
|------|------|------|
| cases | list[dict] | L4 案例列表 |
| distills | list[dict] | L4 蒸馏记录列表 |
| config | dict | 可选的 `ScreenConfig` 参数 |

**执行流程**：数据准备 → 三屏对齐 → 阻力方向 → 趋势速度 + 变化点 → 不确定性 → 输出写入。

**返回 `QMMOutput` 字段：**

```python
{
    "snapshot_ts": "2026-07-25T...",
    "data_version": "...",
    "feature_def_version": "fd-1.0",
    "qmm_version": "qmm-v1.0",
    "trend_state": "UP",                 # "UP" | "DOWN" | "RANGE" | "UNKNOWN"
    "trend_change_point": "STABLE",      # "STABLE" | "ACCELERATING" | "DECELERATING" | "REVERSING"
    "mrd_vector": {
        "direction": "NEUTRAL",          # "UP" | "DOWN" | "NEUTRAL"
        "resistance_up": 50,             # 0-100
        "resistance_down": 50,           # 0-100
        "confidence": 0,                 # 0-1
    },
    "uncertainty": 1.0,                  # 0-1
    "triple_screen": {"long": {...}, "mid": {...}, "short": {...}, "alignment": "..."},
    "velocity": 0.0,
    "acceleration": 0.0,
    "reason_codes": [...],               # list[str]
    "evidence_refs": [...],              # list[str]: 最近10条事件ID
    "system_source_stats": {...},
}
```

> 事件数 < 3 时返回 `UNKNOWN` 趋势 + `INSUFFICIENT_DATA` 原因码。

### 7.2 run_qmm_with_gate

```python
def run_qmm_with_gate(
    cases: List[Dict[str, Any]],
    distills: List[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
    gate_config: Optional[Dict[str, Any]] = None,
) -> tuple
```

QMM 内核 + 门禁联合入口。

**返回：** `(QMMOutput, GateResult)`。门禁不通过时 `gate_status` 标记为 `FAILED`。

---

## 8. L4 记忆管道

**文件**：`scripts/memory_l4/pipeline.py`
**角色**：L4 记忆沉淀全链路（case → review → distill → stats → index → emit）。

### 8.1 run_pipeline

```python
def run_pipeline(
    episode_path: Path,
    steps: Optional[List[str]] = None,
) -> Dict[str, Any]
```

| 参数 | 类型 | 说明 |
|------|------|------|
| episode_path | Path | episode JSON 文件路径 |
| steps | list[str] | 要执行的步骤（默认全部）。可选：`register`、`a0a9`、`review`、`distill`、`stats`、`rebuild_index`、`emit` |

**返回值：**

```python
{
    "episode": "/path/to/episode.json",
    "steps_executed": ["register", "a0a9", "review", "distill", "stats", "rebuild_index", "emit"],
    "case": {...},          # 案例数据
    "review": {...},        # 复盘记录
    "distill": {...},       # 蒸馏结果
    "stats": {...},         # 统计
    "index": {...},         # 索引重建结果
    "candidate": {...},     # 约束升级候选
}
```

### 8.2 CLI 入口

```bash
python -m scripts.memory_l4.pipeline --episode <path> [--steps register a0a9 ...] [--out <path>]
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `--episode` | str | 是 | Episode JSON 文件路径 |
| `--steps` | nargs=* | 否 | 要执行的步骤（默认全部） |
| `--out` | str | 否 | 输出结果 JSON 文件路径 |

---

## 9. 系统诊断 CLI

**文件**：`scripts/memory_l4/inspect.py`
**角色**：系统健康检查（启动自检 + 手动排障），输出 8 个面板的诊断报告。

### 9.1 SystemInspector

```python
class SystemInspector:
    def __init__(self)
    def inspect(self, panel_ids: Optional[List[str]] = None) -> InspectReport
```

### 9.2 诊断面板（PANEL_REGISTRY）

| panel_id | 名称 | 检查内容 |
|----------|------|----------|
| `system` | 🏛️ 系统状态 | 守护进程心跳、PID、进程存活 |
| `positions` | 📊 持仓状态 | OKX 持仓同步、未实现盈亏 |
| `knowledge` | 📚 知识库 | L4 案例数、约束版本、索引状态 |
| `models` | 🤖 模型状态 | BCRM 2.0 模型目录扫描（`scripts/data/bcrm2_models/`），统计 L1/L2 模型数、币种数、周期数 |
| `skills` | 🧩 技能体系 | A0-A9 技能注册状态 |
| `risk` | ⚠️ 风控状态 | 日亏损、连续亏损、交易暂停 |
| `connections` | 🔗 连接状态 | OKX API、飞书、共享内存总线 |
| `alerts` | 🚨 告警状态 | 飞书告警最近推送记录 |

### 9.3 InspectReport

```python
class InspectReport:
    overall_status: str                  # "ok" | "warn" | "error"
    def to_dict(self) -> Dict
    def to_json(self) -> str
    def to_brief(self) -> str            # 摘要模式
    def to_table(self) -> str            # 表格模式（默认）
```

### 9.4 CLI 入口

```bash
python -m scripts.memory_l4.inspect [options]
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--brief` | flag | False | 摘要模式输出 |
| `--json` | flag | False | JSON 格式输出 |
| `--watch` | int | 0 | 持续监控模式，指定刷新间隔（秒） |
| `--panels` | str | "" | 指定检查面板（逗号分隔，如 `system,risk`） |

**典型用法：**

```bash
# 完整诊断（表格输出）
python -m scripts.memory_l4.inspect

# JSON 输出（供脚本解析）
python -m scripts.memory_l4.inspect --json

# 只检查系统状态和风控
python -m scripts.memory_l4.inspect --brief --panels system,risk

# 持续监控（每 30 秒刷新）
python -m scripts.memory_l4.inspect --watch 30
```

**退出码：** `overall_status == "error"` 时退出码 1，否则 0。

---

## 10. BCRM 2.0 回测 CLI

**文件**：`scripts/memory_l4/bcrm2/run_phase0_validation.py`
**角色**：BCRM 2.0 Phase 0 基线回测验证。

```bash
python -m scripts.memory_l4.bcrm2.run_phase0_validation [options]
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--symbols` | str | "BTC,ETH" | 回测币种（逗号分隔） |
| `--timeframe` | str | "1H" | K线周期 |
| `--n-folds` | int | 5 | Walk-Forward 折数 |
| `--conf-threshold` | float | 0.40 | 置信度阈值 |
| `--tp-atr` | float | 3.0 | 止盈 ATR 倍数 |
| `--sl-atr` | float | 2.0 | 止损 ATR 倍数 |
| `--max-hold-bars` | int | 60 | 最大持仓 K 线数 |
| `--max-bars` | int | 3000 | 回测 K 线数量 |
| `--refresh` | flag | False | 强制刷新数据 |
| `--output` | str | None | 输出报告文件路径 |
| `--no-pivot` | flag | False | 禁用枢轴点特征 |
| `--no-rsi` | flag | False | 禁用 RSI 情绪特征 |
| `--no-wdh` | flag | False | 禁用 WDH 特征 |
| `--wdh-weekly-only` | flag | False | WDH 仅用周线 |
| `--feature-selection` | flag | True | 启用特征选择 |
| `--no-feature-selection` | flag | False | 禁用特征选择 |
| `--fs-imp-threshold` | float | 0.05 | 特征重要性阈值 |
| `--fs-corr-threshold` | float | 0.85 | 特征相关性阈值 |
| `--portfolio` | flag | False | 组合回测 |
| `--enable-incremental` | flag | False | 启用增量学习 |

---

## 11. data_server HTTP 接口

**文件**：`data_server_fixed.py`
**端口**：8765（监听 `0.0.0.0`）
**角色**：前端监控面板数据服务（只读）。基于 `http.server` + `ThreadingMixIn`。

### 11.1 与易经推理系统相关的路由

| 方法 | 路径 | 缓存 | 说明 |
|------|------|------|------|
| GET | `/api/yijing` | 是 | 易经推理系统综合状态（推理/卦象/持仓） |
| GET | `/api/yijing-positions` | 否 | 易经系统当前持仓列表 |
| GET | `/api/yijing/account-overview` | 是 | 易经账户总览（余额/权益/持仓汇总） |
| GET | `/api/l4-status` | 是（10s） | L4 认知闭环状态仪表盘 |
| GET | `/api/global-trade-stats` | 是（30s） | 跨系统交易统计（从 L4 案例库聚合） |

### 11.2 响应格式

所有接口返回 JSON。缓存未就绪时返回：

```json
{"error": "yijing data loading, please wait"}
```

**`/api/l4-status` 返回（示例）：**

```json
{
  "cases": {"total": 125, "last_24h": 8},
  "reviews": {"total": 120, "pending": 2},
  "distills": {"total": 115},
  "constraints_version": "v2.9",
  "index": {"rebuilt_at": "2026-07-25T..."}
}
```

**`/api/global-trade-stats` 返回（示例）：**

```json
{
  "total_cases": 250,
  "systems": {
    "yijing_inference": {"name": "易经推理", "cases": 125, "win_rate": 0.70, "pnl": 15.5},
    "martin_v15": {"name": "马丁策略 V15", "cases": 80, "win_rate": 0.65, "pnl": 8.2}
  },
  "summary": {...},
  "timestamp": "2026-07-25T..."
}
```

### 11.3 启动方式

```bash
python data_server_fixed.py
# 输出: 监控服务已启动: http://localhost:8765
```

---

## 12. 错误码

### 12.1 推理 fail_closed 原因

| 原因码 | 触发条件 | 处理方式 |
|--------|----------|----------|
| `模型未训练` | BCRM 2.0 模型未就绪且 `auto_train=False` | 返回 FLAT，不下单 |
| `模型未就绪` | 模型加载失败且训练失败 | 同上 |
| `置信度不足` | 推理置信度 < 0.3 | 返回 FLAT，不下单 |
| `A0创伤降级` | A0 创伤信号且置信度 < 0.4 | 返回 FLAT，不下单 |

> 注：v4 五角校验不再触发 fail_closed（"三源严重分歧"已废弃）。五角校验改为通过风险评分调整仓位/杠杆/止盈/止损，不阻断开仓。
| `推理失败: <异常>` | 推理过程抛异常 | 返回 FLAT，记录堆栈 |

### 12.2 诊断面板状态

| 状态 | 含义 | 退出码影响 |
|------|------|------------|
| `ok` | 正常 | 0 |
| `warn` | 警告（心跳超时/文件缺失等） | 0 |
| `error` | 错误（进程死亡/连接失败等） | 1 |

### 12.3 HTTP 错误

| HTTP Code | 含义 | 说明 |
|-----------|------|------|
| 200 | 成功 | 返回 JSON 数据 |
| 404 | 路径不存在 | 未知路由 |
| - | `{"error": "..."}` | 数据加载中或异常 |

### 12.4 风控触发

**v4.2 改造**：风控以**亏损金额**为唯一触发准则，不再以连续亏损笔数为准。

| 触发条件 | 判定逻辑 | 行为 |
|----------|----------|------|
| 亏损金额超限 | `daily_pnl ≤ -(current_equity × loss_limit_pct)` | `trading_halted=True`，停止开新仓 |
| 兜底固定阈值 | `daily_pnl ≤ daily_loss_limit` | 同上 |
| 有效阈值 | `max(dynamic_limit, daily_loss_limit)` | 取更严格者 |
| ~~连续亏损笔数~~ | ~~`consecutive_losses ≥ max_consecutive_losses`~~ | 已禁用（`max_consecutive_losses=999`） |
| 持仓数 >= `max_positions` | — | 拒绝开新仓 |
| A7 门禁未通过 | — | 拦截当前币种下单 |

**默认场景**（可用资金 150U，`loss_limit_pct=0.20`）：
- 亏25U（16.7%）→ 允许交易
- 亏30U（20.0%）→ 触发拦截
- 亏35U（23.3%）→ 触发拦截 + `trading_halted=True`

---

## 13. 版本管理

### 13.1 当前版本

- **API 版本**：v2.9
- **更新日期**：2026-07-25
- **SSoT 来源**：`docs/TECHNICAL_DESIGN.md`（v2.9）、`docs/ENGINEERING_INDEX.md`（v2.6）

### 13.2 版本策略

- **版本号**：`v<major>.<minor>`，重大架构变更升 major，功能迭代升 minor
- **变更记录**：见 [CHANGELOG.md](./CHANGELOG.md)
- **SSoT 层级**：约束层 > 本文件（API_SPEC）> 模块内联注释
- **向后兼容**：BCRM 2.0 接口与 BCRM 1.0 保持兼容（`BCRM2Adapter.infer()` 输出格式对齐 `BCRMEngine.infer()`）；`YijingExitSystem` 与 `ClassicExitSystem` 通过 veto 机制协同，互不破坏对方接口

### 13.3 相关文档

- [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md) — 技术架构与设计原则
- [ENGINEERING_INDEX.md](./ENGINEERING_INDEX.md) — 工程索引与文件级导航
- [CHANGELOG.md](./CHANGELOG.md) — 版本变更日志

---

_最后更新：2026-07-25 | 来源：11-易经推理系统（v2.9）_
