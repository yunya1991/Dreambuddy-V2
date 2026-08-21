#!/usr/bin/env python3
"""
易经推理轮询交易器（P2 完整版）

集成功能：
- P2-1a: 平仓后自动生成 case 存入 L4
- P2-1b: 定期重训 LiangyiEngine + QMM
- P2-2a: 动态仓位（置信度 + 波动率）
- P2-2b: 日最大亏损限制 + 连续亏损熔断
- P2-3: 交易绩效统计 + PnL 持久化
- P2-4: BCRM 矛盾格式修复
- P2-5: 进程守护 + 异常告警 + 日志持久化

用法:
  python -m scripts.memory_l4.polling_trader --once
  python -m scripts.memory_l4.polling_trader --interval 300 --coins BTC,ETH
"""
import argparse
import json
import os
import signal as signal_module
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
from scripts.memory_l4.bcrm.bagua_engine import BaguaEngine
from scripts.memory_l4.bcrm.engine import BCRMEngine
from scripts.memory_l4.bcrm2.incremental_learner import IncrementalLearner
from scripts.memory_l4.bcrm2.shadow_logger import ShadowLogger, SHADOW_LOGGER_ENABLED
from scripts.memory_l4.bcrm2.parameter_mapper import (
    ALPHA_BLEND_ENABLED, DEFAULT_ALPHA_BLEND, ALPHA_BLEND_MAX,
)
from scripts.memory_l4.bcrm2_adapter import BCRM2Adapter
from scripts.memory_l4.classic_exit_system import (
    ClassicExitSystem,
    ExitAction,
    ExitConfig,
)
from scripts.memory_l4.classic_exit_system import (
    PositionState as ExitPositionState,
)
from scripts.memory_l4.knowledge_bridge import KnowledgeBridge
from scripts.memory_l4.learning_scheduler import LearningScheduler
from scripts.memory_l4.okx_simulated import OKXSimulatedClient
from scripts.memory_l4.paths import episodes_dir as _episodes_dir
from scripts.memory_l4.process_guardian import ProcessGuardian
from scripts.memory_l4.ranging_market_enhancer import (
    HexagramDataDrivenCalibrator,
    RangingMarketEnhancer,
)
from scripts.memory_l4.trading_utils import (
    PerformanceTracker,
    PositionTracker,
    RiskManager,
    register_trade_to_l4,
)
from scripts.memory_l4.review_engine import (
    BULLISH_HEXAGRAMS,
    BEARISH_HEXAGRAMS,
    NEUTRAL_HEXAGRAMS,
)
from scripts.memory_l4.yijing_exit_system import (
    YijingExitAction,
    YijingExitConfig,
    YijingExitSystem,
)
from scripts.memory_l4.yijing_feishu_alert import notify_model_error, notify_system_error
from scripts.memory_l4.yijing_trainer import (
    _build_contradiction_list,
    _build_research_contradictions,
    _contradictions_to_bcrm_format,
    _detect_ranging_market,
    _kline_to_snapshot,
    _load_kline_from_okx,
)
import pandas as pd

# ── 公共代币池加载器（方案B：运行时读取，8h自动刷新）──
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_REGISTRY_PATHS = [
    Path(os.environ.get("TOKEN_REGISTRY_PATH", ""))
    if os.environ.get("TOKEN_REGISTRY_PATH")
    else None,
    _PROJECT_ROOT / "config" / "token_registry.json",
]
_POOL_TTL = 28800  # 8小时


def _load_registry_symbols():
    """从 token_registry.json 加载启用的币种列表。文件不存在/损坏时返回 None。"""
    for p in _REGISTRY_PATHS:
        if p is None or not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            tokens = data.get("tokens", [])
            syms = []
            for t in tokens:
                if isinstance(t, dict):
                    if not t.get("enabled", True):
                        continue
                    s = str(t.get("symbol", "")).strip().upper()
                    if s:
                        syms.append(s)
                elif isinstance(t, str) and t.strip():
                    syms.append(t.strip().upper())
            if syms:
                return syms
        except Exception:
            continue
    return None


class PollingTrader:
    """易经推理轮询交易器（P2 完整版）"""

    # config.json 中与进化阈值相关的键
    _EVOLUTION_CONFIG_KEYS = (
        "confidence_threshold",
        "daily_loss_limit",
        "max_consecutive_losses",
        "default_position_pct",
    )

    # 统一冷静期：平仓后 N 秒内禁止该币种任何方向新开仓（含反手）
    # 防止"平仓→立即反手→又亏→再反手"的频繁来回割肉循环
    COOLDOWN_SEC = 28800  # 8 小时

    # --------- 做空置信度分层阈值（bearish_score → multiplier）---------
    # 注意：有效阈值 = 基础阈值 × 乘数
    #   → 乘数 < 1 = 降低门槛（放宽）；乘数 > 1 = 抬高门槛（收紧）
    #
    # STRONG: 5均线严格空头排列 → ×0.91 ≈ 1/1.10 降低门槛（强趋势，允许较低置信度入场）
    # NORMAL: 3~4均线空头       → ×1.00 标准
    # WEAK  : 仅1~2均线短周期空头 → ×1.18 ≈ 1/0.85 抬高门槛（弱趋势，要求更高置信度避免诱空）
    SHORT_CONF_MULTI_MA_STRONG: float = 0.9091  # ≈ 1/1.10
    SHORT_CONF_MULTI_MA_NORMAL: float = 1.0000
    SHORT_CONF_MULTI_MA_WEAK:   float = 1.1765  # ≈ 1/0.85

    # --------- market_regime 阈值调节器（基于回测胜率反比）---------
    # 理论：regime 反映市场形态，不同形态下做空胜率差异显著
    #       回测数据：TREND_BEAR 28.6% < STRONG_TREND_BEAR 50.0% < RANGING 68.6%
    #       乘数 > 1.0 = 抬高阈值 = 抑制做空；乘数 < 1.0 = 降低阈值 = 放宽做空
    #       与 bearish_score 乘数叠加：final_threshold = base × score_multi × regime_multi
    REGIME_SHORT_CONF_MULTI_TREND_BULL:        float = 1.15  # 胜率 42.9%，抑制（几乎禁止）
    REGIME_SHORT_CONF_MULTI_TREND_BEAR:        float = 1.15  # 胜率 28.6%，强抑制
    REGIME_SHORT_CONF_MULTI_STRONG_TREND_BEAR: float = 1.00  # 胜率 50.0%，中性
    REGIME_SHORT_CONF_MULTI_MEAN_REVERTING:    float = 1.00  # 无回测数据，中性
    REGIME_SHORT_CONF_MULTI_RANGING:           float = 0.90  # 胜率 68.6%，放宽（≈1/1.11）

    # --------- 做空仓位规模分层（bearish_score → position_multiplier）---------
    # 理论：周期越短可信度越低，但趋势识别越早 → 不禁开，而是控制资金规模
    #       随着跌破更多均线，弹簧压力越来越重 → 置信度越来越强 → 仓位越来越大
    #   STRONG: 5均线空头+3日确认 → 弹簧压力最重 → 标准仓位 ×1.0
    #   NORMAL: 3~4均线空头       → 中等压力     → ×0.7
    #   WEAK  : 1~2均线短周期空头 → 压力轻       → ×0.4（小仓试水）
    SHORT_POSITION_MULTI_STRONG: float = 1.0
    SHORT_POSITION_MULTI_NORMAL: float = 0.7
    SHORT_POSITION_MULTI_WEAK:   float = 0.4

    # ================================================================
    # H1 / H4 补充：长多 UP 方向（与做空方向对称）的弹簧力场阈值+仓位分层常量
    # 回测逻辑：胜率反比 → 抑制追顶，放宽震荡蓄势
    # ================================================================
    # --------- 长多置信度阈值乘数（基于 MA 评分档位）---------
    # STRONG: 5均线多头排列       → ×0.9091 ≈ 1/1.10 略微放宽阈值（顺势，但避免追极强顶）
    # NORMAL: 3~4均线多头         → ×1.0000 标准
    # WEAK  : 仅1~2均线短周期多头 → ×1.1111 ≈ 1/0.90 提高门槛（弱趋势/反抽诱多）
    LONG_CONF_MULTI_MA_STRONG: float = 0.9091
    LONG_CONF_MULTI_MA_NORMAL: float = 1.0000
    LONG_CONF_MULTI_MA_WEAK:   float = 1.1111

    # --------- market_regime 长多阈值调节器（基于回测/经验胜率反比）---------
    #   乘数 > 1.0 = 抬高阈值 = 抑制做多；乘数 < 1.0 = 降低阈值 = 放宽做多
    #   TREND_BULL        ：胜率 ~55% → ×1.05（略微抑制：避免末端追顶）
    #   STRONG_TREND_BULL ：胜率 ~45% → ×1.10（强抑制：强趋势末端大概率顶背离诱多）
    #   TREND_BEAR        ：胜率 ~30% → ×1.15（强抑制：逆势抄底）
    #   MEAN_REVERTING    ：无回测 → ×1.00（中性）
    #   RANGING           ：胜率 ~68% → ×0.85（放宽：震荡蓄势向上突破）
    REGIME_LONG_CONF_MULTI_TREND_BULL:        float = 1.05
    REGIME_LONG_CONF_MULTI_STRONG_TREND_BULL: float = 1.10
    REGIME_LONG_CONF_MULTI_TREND_BEAR:        float = 1.15
    REGIME_LONG_CONF_MULTI_MEAN_REVERTING:    float = 1.00
    REGIME_LONG_CONF_MULTI_RANGING:           float = 0.85

    # --------- 长多仓位规模分层（bullish_score → position_multiplier）---------
    #   理论：突破越多均线弹簧恢复力越强→仓位越大；强顶背离/末端追涨反而降仓
    #   STRONG: 5均线多头排列确认 → 顺势 → 标准仓位 ×1.0（保守，不主动加杠杆追）
    #   NORMAL: 3~4均线多头       → 中等 → ×0.7
    #   WEAK  : 1~2短周期多头反抽 → 轻仓 → ×0.4
    LONG_POSITION_MULTI_STRONG: float = 1.0
    LONG_POSITION_MULTI_NORMAL: float = 0.7
    LONG_POSITION_MULTI_WEAK:   float = 0.4

    # --------- 五均线分层弹簧力场：组权重（sum=1.00）---------
    # 短中期组 (MA30 + MA65)   : 0.35
    # 中期组   (MA128 + MA200) : 0.40
    # 长期组   (MA1400 ≈ 周MA200): 0.25
    FMA_GROUP_WEIGHT_SHORT: float = 0.35
    FMA_GROUP_WEIGHT_MID:   float = 0.40
    FMA_GROUP_WEIGHT_LONG:  float = 0.25

    # --------- 动态弹簧力场升级（Phase C++）---------
    # ① inter-MA力：均线间相对距离产生的趋势力
    #    F_inter = -k_inter × (MA_short - MA_long) / MA_long
    #    k_inter < k（趋势力弱于回复力）
    FMA_INTER_K_RATIO: float = 0.5  # k_inter = k × 0.5

    # ② MA斜率调制k：k_eff = k × (1 + α × tanh(slope_norm))
    #    slope > 0（MA上升）→ k_eff > k → 趋势方向弹簧更硬（不易反弹）
    #    slope < 0（MA下降）→ k_eff > k → 反趋势方向弹簧更硬
    FMA_SLOPE_ALPHA: float = 0.3   # 调制强度
    FMA_SLOPE_WINDOW: int = 5     # 斜率计算窗口（线性回归）

    # ③ 势能阈值：U = ½kx²，用于超卖/超买检测
    #    回测修正：U 大 = 价格偏离均线远 = 超卖/超买 → 禁止做空（均值回归概率高）
    #    U 小 = 价格接近均线 → 趋势早期，可做空
    FMA_POTENTIAL_OVERSOLD: float = 0.010  # U > 0.010 → 超卖，禁止做空（回测验证）
    FMA_POTENTIAL_LOW: float = 0.005       # U < 0.005 → 蓄势不足

    # ④ F_total 变化率（趋势加速度）阈值
    #    F_dot = F_total(t) - F_total(t-1)
    #    F_dot > 0 → 偏离在加速（趋势延续）→ 可做空
    #    F_dot < 0 → 偏离在收敛（均值回归）→ 禁止做空
    FMA_F_DOT_THRESHOLD: float = -0.005  # F_dot < 此值 → 收敛中，禁止做空

    # 五均线 + 3日跌破确认：最短期跌破需要 N 日收盘价 ≤ MA30
    FMA_SHORT_TIER_BREAKDOWN_BARS: int = 3

    # --------- Phase D：市场形态判定（Market Regime Classification）---------
    # 4维度形态判定器 → 5种 regime → 差异化做空过滤
    #   ① 趋势强度比 TR  = |F_inter| / (|F_net| + |F_inter| + ε)
    #      高 TR → 均线排列主导（趋势市）；低 TR → 价格偏离主导（均值回归）
    #   ② 均线发散度 CV  = std(MA30/65/128/200) / mean
    #      高 CV → 均线发散（趋势明确）；低 CV → 均线纠缠（震荡）
    #   ③ 斜率强度 |slope_avg|（MA 倾斜度，%）
    #   ④ F_dot（F_total 变化率）
    FMA_REGIME_TR_STRONG: float    = 0.60   # TR > 0.60 → 强趋势
    FMA_REGIME_TR_TREND: float     = 0.50   # TR > 0.50 → 弱趋势
    FMA_REGIME_TR_REVERT: float    = 0.40    # TR < 0.40 → 均值回归
    FMA_REGIME_CV_STRONG: float    = 0.030   # CV > 0.030 → 发散趋势
    FMA_REGIME_CV_TREND: float     = 0.020   # CV > 0.020 → 弱趋势发散
    FMA_REGIME_CV_REVERT: float    = 0.025   # CV < 0.025 → 均线纠缠
    FMA_REGIME_SLOPE_STRONG: float = 0.030   # |slope_avg| > 0.030% → 强趋势
    FMA_REGIME_SLOPE_TREND: float  = 0.020   # |slope_avg| > 0.020% → 弱趋势
    FMA_REGIME_FDOT_STRONG: float  = -0.002  # F_dot > -0.002 → 偏离加速扩大
    FMA_REGIME_FDOT_REVERT: float  = -0.003  # F_dot < -0.003 → 偏离快速收敛

    # --------- 各 regime 的做空过滤阈值（差异化）---------
    # 注: U_threshold 基于 U_short（仅短期组MA30/65势能），尺度远小于 U_potential
    #   U_short ≈ 0.35 × ½ × k_eff × (x30² × w30 + x65² × w65)
    #   价格偏离MA30 5% → U_short ≈ 0.002；偏离10% → U_short ≈ 0.006
    # STRONG_TREND_BEAR：宽松（顺势做空，均线成阻力）
    FMA_ALLOW_SCORE_STRONG_TREND: tuple = ("STRONG", "NORMAL", "WEAK")
    FMA_U_THRESHOLD_STRONG_TREND: float  = 0.010   # 趋势市允许更大偏离(~10% below MA30)
    FMA_FDOT_STRONG_TREND: float        = -0.002
    # TREND_BEAR：收紧（弱趋势市假突破多，回测胜率仅 28.6%）
    #   仅允许 STRONG/NORMAL 档（剔除 WEAK），更严超卖和加速过滤
    FMA_ALLOW_SCORE_TREND: tuple = ("STRONG", "NORMAL")
    FMA_U_THRESHOLD_TREND: float  = 0.003           # ~5% below MA30（收紧）
    FMA_FDOT_TREND: float         = -0.003          # 要求偏离仍在加速
    # MEAN_REVERTING：严格（反向，F>0 = 超卖 = 禁止做空）
    FMA_ALLOW_SCORE_REVERT: tuple = ("WEAK",)      # 仅刚跌破才允许
    FMA_U_THRESHOLD_REVERT: float = 0.002           # ~4% below MA30
    FMA_FDOT_REVERT: float        = -0.003
    # RANGING：放宽（震荡市跌破信号胜率 68.6% 最高，允许全档位）
    #   回测显示 RANGING 做空胜率最高但旧过滤仅放行 12/51，过度过滤
    FMA_ALLOW_SCORE_RANGE: tuple  = ("STRONG", "NORMAL", "WEAK")
    FMA_U_THRESHOLD_RANGE: float  = 0.003            # ~5% below MA30（放宽）
    FMA_FDOT_RANGE: float         = -0.003           # 放宽收敛限制

    # 偏见底兜底窗口：MA1400（长期组）± N% 内 → 禁止做空
    #   接近长期MA往往是大周期支撑位附近，直接禁止做空
    FMA_LONG_TERM_BOTTOM_BUFFER: float = 0.02

    # 弹簧力场形态过滤开关（回测验证效果不佳，默认关闭）
    #   False: 走简单趋势确认逻辑（偏见底兜底 + valid_breakdown + price<MA128）
    #   True : 走 _regime_short_filter 形态差异化过滤（仅用于实验/对比）
    FMA_REGIME_FILTER_ENABLED: bool = False

    def __init__(
        self,
        interval: int = 3600,
        coins: list = None,
        bar: str = "1H",
        confidence_threshold: float = 0.70,
        short_confidence_threshold: float = 0.80,
        max_positions: int = 3,
        kline_limit: int = 200,
        initial_equity: float = 100.0,
        daily_loss_limit: float = -30.0,
        max_consecutive_losses: int = 999,
        default_position_pct: float = 0.10,
        guardian: ProcessGuardian = None,
        shared_dir=None,
        use_bcrm2: bool = True,
    ):
        self.interval = interval
        default_coins = _load_registry_symbols() or [
            "UNI",
            "PUMP",
            "MU",
            "SKHYNIX",
            "HYPE",
            "BTC",
            "SOL",
            "XAU",
            "XAG",
            "GOOGL",
            "NVDA",
            "AMZN",
            "OKB",
            "SNDK",
            "SPCX",
            "CRCL",
            "COIN",
            "BMNR",
            "MSTR",
        ]
        # P4 修复：币种规范化映射
        # 实际 OKX 合约：
        #   XAU-USDT-SWAP  (黄金现货杠杆代币, ticker code=0, 存在)
        #   XAUT-USDT-SWAP (Tether黄金代币,          ticker code=51001, 不存在/已下线)
        #   XSNDK → SNDK-USDT-SWAP (闪迪, OKX用SNDK而非XSNDK)
        #   XSPCX → SPCX-USDT-SWAP  (SpaceX, OKX用SPCX而非XSPCX)
        # 所以如果用户/旧启动命令写了 XAUT/XSNDK/XSPCX，必须映射，避免 K线拉取失败。
        _NORMALIZE_COIN = {"XAUT": "XAU", "XSNDK": "SNDK", "XSPCX": "SPCX"}

        def _norm(c):
            cu = str(c).strip().upper()
            return _NORMALIZE_COIN.get(cu, cu)

        self.coins = [_norm(c) for c in (coins or default_coins)]
        self._last_pool_refresh = 0.0  # 公共代币池8h刷新时间戳
        self.bar = bar
        self.confidence_threshold = confidence_threshold
        self.short_confidence_threshold = short_confidence_threshold  # 做空独立阈值（高于做多）
        self.max_positions = max_positions
        self.kline_limit = kline_limit

        # A-1修复：启动时从 OKX_SIM/config.json 加载进化后的阈值，覆盖默认值
        # 注意：需要在 risk_manager 创建后调用，才能同时更新 risk_manager.state
        self._evolution_config_path = None

        self.bcrm_engine = BCRMEngine.from_config()  # PROP-20260810
        self.bagua_engine = BaguaEngine()
        self.okx_client = OKXSimulatedClient()

        self.use_bcrm2 = use_bcrm2
        self.bcrm2_adapters = {}
        # v3.0：per-coin降级机制，替代全局use_bcrm2=False
        # 记录BCRM 2.0训练失败的币种 + 失败时间戳，避免一个币种失败影响其他币种
        self.bcrm2_failed_coins: dict = {}  # {coin: fail_ts}
        self.bcrm2_retry_interval_sec: int = 86400  # 训练失败后24h才重试
        self.bcrm2_min_samples: int = 100  # BCRM 2.0训练所需最小有效样本数

        # P0-2: 动态币种黑名单 — 连续2次亏损自动加入黑名单3日
        # 到期后自动释放（有趋势过滤保护，不需要永久封禁）
        # 可被 config.json 的 blacklist_coins 字段热重载覆盖（追加手动黑名单）
        # 静态永久封禁（回测验证历史表现极差，即使趋势过滤下仍持续亏损）
        self.blacklist_coins: set = {"NEAR", "XRP", "DOT", "ADA", "AVAX", "ETH", "LINK", "BNB"}  # 手动永久黑名单
        self.dynamic_blacklist: dict = {}  # {coin: {"expire_ts": float, "reason": str, "added_ts": float}}
        self.DYNAMIC_BLACKLIST_CONSECUTIVE_LOSSES = 2  # 连续亏损次数阈值
        self.DYNAMIC_BLACKLIST_DURATION_SEC = 3 * 86400  # 3日（秒）

        # P0-3: 卦象黑名单 — 历史回测胜率0%的卦象，强制HOLD
        # 数据来源：坤为地(7/7亏) 震为雷(5/5亏) 火地晋(2/2亏) 地雷复(2/2亏) 全部100%亏损
        # 可被 config.json 的 hexagram_blacklist 字段热重载覆盖
        self.hexagram_blacklist: set = {"坤为地", "震为雷", "火地晋", "地雷复"}

        # P1-1: BTC趋势缓存（5分钟刷新一次，避免每币种重复拉取BTC日线K线）
        self._btc_trend_cache: dict = {"ts": 0, "result": None}

        if self.use_bcrm2:
            # 措施1：启动时主动验证 BCRM 2.0 模块导入与核心依赖可用性
            # 避免运行时才发现 "No module named 'bcrm2'" 等导入错误
            healthy, reason = self._health_check_bcrm2()
            if not healthy:
                # ⚠️ 严格模式：BCRM 2.0 不可用时绝不回退到 BCRM 1.0
                # 启动告警但保持 use_bcrm2=True，运行时各币种因推理失败直接跳过
                self._log(
                    f"[BCRM2.0] 启动健康检查失败: {reason} | "
                    f"严格模式启用：不降级BCRM 1.0，所有币种推理失败将直接跳过",
                    "ERROR",
                )
                try:
                    notify_system_error(
                        f"BCRM2.0 启动健康检查失败（严格模式，不降级BCRM 1.0）: {reason}",
                        component="BCRM2.0健康检查",
                    )
                except Exception as e:
                    self._log(f"[BCRM2.0] 飞书告警发送失败: {e}", "WARN")
            else:
                self._log("[BCRM2.0] 模式已启用（严格：禁用BCRM 1.0降级），健康检查通过", "INFO")

        self.running = False
        self.cycle_count = 0
        self.last_date = datetime.now().strftime("%Y-%m-%d")

        self.perf_tracker = PerformanceTracker(initial_equity=initial_equity)
        self.risk_manager = RiskManager(
            daily_loss_limit_usdt=daily_loss_limit,
            max_consecutive_losses=max_consecutive_losses,
            default_position_pct=default_position_pct,
            min_position_usdt=20.0,
        )

        # A-1修复：risk_manager 创建后，从 config.json 加载进化后的阈值覆盖默认值
        self._load_evolution_config(initial=True)
        self.position_tracker = PositionTracker()
        self.learning_scheduler = LearningScheduler(
            bcrm_engine=self.bcrm_engine,
            retrain_interval_cases=10,
            retrain_interval_hours=4,
            on_retrain_complete=self._on_retrain_complete,
            shared_dir=shared_dir,
        )
        self.guardian = guardian

        self.knowledge_bridge = KnowledgeBridge(shared_dir=shared_dir)
        self.external_knowledge = {}

        # 经典指标离场系统（2026-08-06 放宽：减少频繁扫损，支持高置信度长持）
        exit_cfg = ExitConfig(
            l0_max_hold_sec=172800,
            l0_max_loss_pct=-0.05,  # 最后防线不变
            tb_enabled=True,
            tb_sl_atr_mult=2.5,  # 原 1.5 → 2.5：放宽ATR-based止损，避免震荡洗出
            tb_tp_atr_mult=5.0,  # 原 3.0 → 5.0：盈亏比保持~2:1
            tb_sl_min_pct=0.06,  # 原 0.045 → 0.06：订单级最小止损 6%（对应价格0.6%@10x）
            tb_tp_min_pct=0.06,  # 原 0.04 → 0.06：同放宽
            trailing_enabled=True,
            trailing_arm_profit_pct=0.06,  # 原 0.04 → 0.06：达到6%订单盈利才启用追踪止盈，避免过早启动
            trailing_retrace_pct=0.05,  # 原 0.035 → 0.05：允许5%回调而非3.5%，减少利润锁定过急
            tstp_enabled=True,
            l1_enabled=True,
            l2_close_threshold=0.75,
            l2_reduce_threshold=0.55,
            apply_leverage_to_thresholds=True,
            inflight_cooldown_sec=180,
            l0_risk_gate_enabled=True,
            l0_risk_gate_close_enabled=False,
            l0_risk_gate_cooldown_min=60.0,
            l0_risk_gate_confirm_n=3,
            # Bug2修复: L0_RISK_GATE过度敏感（回测95.6%触发率）
            # 提高long阈值0.5→0.65：避免hold_risk刚过0.5就仓促减仓（正常波动就会触发）
            l0_risk_gate_long_thr=0.65,
            # 同步提高short阈值保持比例一致
            l0_risk_gate_short_thr=0.60,
            # Bug2修复: 新增最小持仓时间3600s=1h
            # 开仓初期hold_risk计算不稳定（K线样本少、ATR异常），给1h保护期
            l0_risk_gate_min_hold_sec=3600.0,
            # 提高盈利旁路阈值：pnl_eff>5%才跳过risk_gate（原3%太低，盈利3%可能只是噪音）
            l0_risk_gate_profit_bypass_pct=0.05,
        )
        self.exit_system = ClassicExitSystem(config=exit_cfg)
        self._exit_cfg_base = exit_cfg

        # 震荡市增强器（优化1-5统一入口）
        # 包含：5种市场状态、布林带双信号确认、MA200方向性偏向、动态止损宽度、置信度校准
        self.ranging_enhancer = RangingMarketEnhancer()
        # 优化5：卦象数据驱动校准器（500+样本后重新校准64卦参数）
        self.ranging_enhancer.hex_calibrator = HexagramDataDrivenCalibrator()

        # 易经专属离场系统：基于卦象风险-价值评估，可否决 classic 的噪音止损
        self.yijing_exit_system = YijingExitSystem(config=YijingExitConfig())
        self.yijing_exit_system.set_log_callback(self._log)

        self.log_dir = Path("data/polling_trader")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / f"trader_{datetime.now().strftime('%Y%m%d')}.jsonl"

        self.incremental_learner = IncrementalLearner(
            retrain_trade_threshold=100,
            retrain_win_rate_threshold=0.5,
            retrain_sharpe_threshold=1.0,
        )

        # 异常检测引擎 (Phase 2.1)
        from scripts.memory_l4.bcrm2.anomaly_detector import HybridAnomalyDetector

        self.anomaly_detector = HybridAnomalyDetector(
            if_contamination=0.02,
            enable_if=True,
            enable_lgb=True,
            enable_dl=False,
        )
        self._kline_cache = {}  # 缓存K线数据用于异常检测

        # CBR 案例检索增强（2026-07-21 修复：接入历史案例检索到决策流程）
        try:
            from scripts.memory_l4.cbr_adapter import CBRToBCRMBridge

            self.cbr_bridge = CBRToBCRMBridge()
            self.cbr_bridge.initialize()
            self._log("[CBR] 案例检索增强已初始化", "INFO")
        except Exception as e:
            self._log(f"[CBR] 初始化失败: {e}，继续运行", "WARN")
            self.cbr_bridge = None

        # A7 实践论门禁（代码驱动，不依赖大模型）
        try:
            from scripts.memory_l4.a7_practice_gate import A7PracticeGate

            self.a7_gate = A7PracticeGate()
            self._log("[A7] 实践论门禁已初始化", "INFO")
        except Exception as e:
            self._log(f"[A7] 门禁初始化失败: {e}，继续运行", "WARN")
            self.a7_gate = None

        # P3: 认知召回桥接（A 系列 Cron 执行前注入认知召回）
        self.cognitive_recall_enabled = True
        self._trading_recall_fn = None
        try:
            import sys as _sys

            _cog_path = str(Path(__file__).resolve().parents[2] / "4-MEMORY" / "9-工具与接口")
            if _cog_path not in _sys.path:
                _sys.path.insert(0, _cog_path)
            from cognitive_loop_entry import trading_recall as _trading_recall

            self._trading_recall_fn = _trading_recall
            self._log("[P3] 认知召回桥接已初始化", "INFO")
        except Exception as e:
            self._log(f"[P3] 认知召回桥接初始化失败: {e}，继续运行", "WARN")
            self.cognitive_recall_enabled = False

        self._sync_existing_positions()

        self._run_startup_inspection()

        # ──────────────────────────────────────────────────────
        # Phase A: 4 个 Feature Flag（选项 A 双轨并行核心）
        # 每个开关关闭时：对应分支 100% 走旧路径
        # ──────────────────────────────────────────────────────
        self.enable_mode_switch: bool = True        # S1: MODE 算力重分配（Phase A）
        self.enable_ev_radar: bool = True           # S2: EV 雷达四档决策（Phase B）
        self.enable_multi_horizon: bool = True      # S3: 多horizon 预测（Phase C）
        self.enable_ranked_tp: bool = True          # S4: 排名止盈三档（Phase C）

        # ──────────────────────────────────────────────────────
        # Phase A: MODE 阈值常量（Spec §3.2）
        # ──────────────────────────────────────────────────────
        self.MODE_OCCUPANCY_MODE3: float = 1.00     # 满仓 → MODE3（100% 占用率）
        self.MODE_OCCUPANCY_MODE2: float = 2 / 3    # 半仓 → MODE2（2/3≈0.6667 占用率，避免 0.67 时 2of3=0.666…<0.67 误判）
        self.MODE3_COARSE_CANDIDATE_TOPN: int = 3   # MODE3 粗推理候选 TopN
        self.MODE_COARSE_KLINE_LIMIT: int = 40       # MODE3 粗推理短 K 线探针（不跑 160 根）

        # ──────────────────────────────────────────────────────
        # Phase A: 缓存 TTL 常量（用 _cycle_idx 轮次计数，非 wall-clock，Spec §3.3）
        # ──────────────────────────────────────────────────────
        self.MODE_CACHE_TTL_ANOMALY: int = 2            # 异常检测缓存 TTL (轮次)
        self.MODE_CACHE_TTL_INFER_COARSE: int = 1       # 粗推理缓存 TTL (轮次)
        self.MODE_CACHE_TTL_KLINE_SHORT: int = 1        # 短K线缓存 TTL (轮次)
        self.MODE_CACHE_TTL_HORIZON_PREDS: int = 2      # 多horizon 预测缓存 TTL
        self.MODE_CACHE_TTL_POSITION_EV: int = 2        # 持仓 EV 缓存 TTL
        self._cycle_idx: int = 0                        # 轮次计数（缓存 TTL 时间基）
        self._mode_cache: Dict[Any, Tuple[Any, int]] = {}  # {key: (payload, written_cycle)}

        # ──────────────────────────────────────────────────────
        # Phase B: EV 雷达阈值与权重（Spec §4 默认值）
        # ──────────────────────────────────────────────────────
        self.EV_FORCE_CLOSE_BELOW: float = -0.35   # EV < -0.35 → 强制离场（非保护期）
        self.EV_WARN_LOWER_BOUND: float = -0.35    # -0.35 ≤ EV < -0.10 → 收紧止损
        self.EV_WARN_UPPER_BOUND: float = -0.10
        self.EV_STRONG_HOLD_ABOVE: float = +0.30   # EV > +0.30 → 放宽止损
        self.ev_weights: Dict[str, float] = {      # 7 子分权重，合计 1.0
            "confidence_s": 0.22,
            "direction_consistency_s": 0.18,
            "trend_alignment_s": 0.15,
            "pnl_momentum_s": 0.14,
            "regime_friendly_s": 0.11,
            "holding_age_s": 0.10,
            "liquidity_risk_s": 0.10,
        }

        # ── 持仓与离场管理层：ExitManager 策略链（v4.4 新增） ──
        # Spec: docs/superpowers/specs/2026-08-20-exit-manager-design.md
        # 5 个 per-position 策略（RankedTp 由全局跨持仓循环处理）
        from scripts.memory_l4.bcrm2.exit_manager import ExitManager
        from scripts.memory_l4.bcrm2.exit_strategies import (
            P3EarlyExitStrategy, SignalReverseStrategy,
            EvForceCloseStrategy, TimeoutProfitSwitchStrategy,
            EvAdjustStrategy,
        )
        _timeout_hours = 29.0
        try:
            _veto_sec = self.yijing_exit_system.config.veto_max_hold_sec
            if _veto_sec and _veto_sec > 0:
                _timeout_hours = _veto_sec / 3600.0
        except Exception:
            pass
        self._ev_force_close_strategy = EvForceCloseStrategy(
            force_below=self.EV_FORCE_CLOSE_BELOW,
            exit_confirm_required=self.EXIT_CONFIRM_REQUIRED,
            enabled=self.enable_ev_radar,
        )
        self._ev_adjust_strategy = EvAdjustStrategy(
            warn_lower=self.EV_WARN_LOWER_BOUND,
            warn_upper=self.EV_WARN_UPPER_BOUND,
            strong_above=self.EV_STRONG_HOLD_ABOVE,
            enabled=self.enable_ev_radar,
        )
        self.exit_manager = ExitManager(strategies=[
            P3EarlyExitStrategy(
                exit_confirm_required=self.EXIT_CONFIRM_REQUIRED,
                protected_p3_min_loss_pct=self.PROTECTED_P3_MIN_LOSS_PCT,
            ),
            SignalReverseStrategy(
                base_threshold=float(self.confidence_threshold),
                protected_conf_boost=self.PROTECTED_REVERSE_CONF_BOOST,
                exit_confirm_required=self.EXIT_CONFIRM_REQUIRED,
            ),
            self._ev_force_close_strategy,
            TimeoutProfitSwitchStrategy(timeout_hours=_timeout_hours),
            self._ev_adjust_strategy,
        ])
        # ── 注入 storage 适配器，用于 exit_strategy_log 贡献值统计 ──
        try:
            from scripts.memory_l4.bcrm2.run_evolution_pipeline import get_storage
            _exit_storage = get_storage()
            if _exit_storage is not None:
                self.exit_manager.set_storage(_exit_storage)
        except Exception as _e:
            self._log(f"[ExitManager] storage 注入失败，贡献值统计降级关闭: {_e}", "WARN")
        self._log(
            f"[ExitManager] 策略链初始化 | 5 策略 | "
            f"P3(10)→SignalRev(20)→EvFC(30)→Timeout(40)→EvAdj(60) | "
            f"timeout={_timeout_hours:.1f}h",
            "INFO",
        )

        # ──────────────────────────────────────────────────────
        # Phase C: 多 horizon 预测 + 排名止盈 默认参数
        # ──────────────────────────────────────────────────────
        # S3: 多 horizon（Spec §4.3.1 — horizon 集合对齐 spec）
        self.HORIZON_BAR_CANDIDATES: List[int] = [1, 2, 3, 6, 10, 20, 30]  # Spec §4.3.1
        self.HORIZON_PREP_EXIT_MARGIN: int = 3   # best_k_bar 与 held 差在 ±3 内 → PREP_EXIT

        # S4: 排名止盈（Spec §4.3）
        self.RANKED_TP_GAP_RATIO: float = 0.70       # 落差阈值 0.7 → Top1 远领先
        self.RANKED_TP_MIN_PROFIT_USDT: float = 5.0  # Top1 至少盈利 5U（防噪声）

        # Phase C S3: PREP_EXIT 跨轮一致率触发（C11）
        self.S3_PREP_EXIT_CONFIRM_WINDOW: int = 3      # 回看最近 3 轮预测
        self.S3_PREP_EXIT_CONFIRM_RATE: float = 0.67   # ≥ 2/3 轮一致 → 允许进入离场确认
        self.EXIT_ACT_S3_PREP_EXIT = "s3_prep_exit"    # 离场确认 tag

        # ──────────────────────────────────────────────────────
        # H3-FMA 渐进自动开关：RolloutManager 状态（与 data_server 共用 phase_c_rollout_state.json）
        #   • phase_c_rollout_state_path 存路径 + phase_c_rollout_mgr 存实例（懒加载）
        #   • FMA 最后检查时间戳（避免每1小时轮询都调一次评估，每天最多1次）
        # ──────────────────────────────────────────────────────
        self._fma_phase_c_state_path = None
        self._fma_phase_c_mgr = None        # 懒加载：AB闸门口才创建（异常不影响主流程）
        self._fma_last_auto_check_ts: float = 0.0   # 上次自动调 evaluate_fma_toggle 时间戳
        self._FMA_AUTO_CHECK_INTERVAL_SEC = 20 * 3600   # 每 20 小时评估一次（保守，每天至多1次切换扰动）

        # ──────────────────────────────────────────────────────
        # Phase B: ShadowLogger 影子模式初始化
        # 开关 SHADOW_LOGGER_ENABLED 默认 False，关闭时 _shadow_logger=None
        # 确保 CLI 字节等价（不影响任何交易逻辑）
        # ──────────────────────────────────────────────────────
        self._shadow_logger: ShadowLogger = None  # type: ignore[assignment]
        self._init_shadow_logger()

        # ──────────────────────────────────────────────────────
        # Phase C: α blend 前瞻参数上线初始化
        # 开关 ALPHA_BLEND_ENABLED 默认 False，关闭时 _alpha_blend=0.0
        # 确保 CLI 字节等价（α=0 时 ParameterMapper 输出不变）
        # ──────────────────────────────────────────────────────
        self._alpha_blend_enabled: bool = False
        self._alpha_blend: float = 0.0
        self._init_alpha_blend()

        # T4: enable_inject 融合层开关（进程级，从文件读取）
        self._enable_inject_runtime: bool = False
        self._enable_inject_last_reload: float = 0.0
        self._enable_inject_reload_interval: float = 300.0  # 每 5 分钟重读一次
        self._init_enable_inject()

        # ──────────────────────────────────────────────────────
        # H3-FMA 渐进：冷启动时从 rollout_state.json 还原 FMA_REGIME_FILTER_ENABLED
        #   优先级：rollout state 中的 fma_enabled（人工/自动渐进切换） > 类默认 False
        #   失败：兜底保留类默认 False（不影响交易）
        # ──────────────────────────────────────────────────────
        self._fma_load_from_rollout()

        # ──────────────────────────────────────────────────────
        # Phase C+: 大小周期 MorphCyclePredictor + ParameterMapper 单例
        #   目的：① 日志审计（大小周期→形态→六维→注入BCRM闭环）
        #         ② 后续 enable_inject=True 时直接复用
        #   约束：无论开关状态，均不改变任何交易参数（字节等价）
        # ──────────────────────────────────────────────────────
        self._morph_predictor = None
        self._param_mapper = None
        self._init_morph_and_param_mapper()

    # ================================================================
    # Phase C+: 大小周期预测器 + ParameterMapper 初始化
    # 设计原则：失败降级为 None，仅影响日志，不影响交易逻辑
    # ================================================================

    def _init_morph_and_param_mapper(self):
        """初始化大小周期 MorphCyclePredictor（单例）与 ParameterMapper。

        storage 优先复用 bcrm2_adapters（所有 adapter 共享同一 storage），
        兜底使用 run_evolution_pipeline.get_storage()。异常被 catch，
        self._morph_predictor / self._param_mapper 置为 None，后续方法会安全 return。
        """
        try:
            from scripts.memory_l4.bcrm2.morph_cycle_predictor import MorphCyclePredictor
            from scripts.memory_l4.bcrm2.parameter_mapper import ParameterMapper
            from scripts.memory_l4.bcrm2.run_evolution_pipeline import get_storage
        except Exception as e:
            self._log(f"[Morph] 导入失败，大小周期预测日志降级关闭: {e}", "WARN")
            return

        storage = None
        try:
            if hasattr(self, "bcrm2_adapters") and self.bcrm2_adapters:
                first_adapter = next(iter(self.bcrm2_adapters.values()))
                if hasattr(first_adapter, "storage"):
                    storage = first_adapter.storage
        except Exception:
            storage = None
        if storage is None:
            try:
                storage = get_storage()
            except Exception:
                storage = None

        if storage is not None:
            try:
                self._morph_predictor = MorphCyclePredictor(storage)
            except Exception as e:
                self._log(f"[Morph] Predictor 构造失败: {e}", "WARN")
                self._morph_predictor = None
        else:
            self._log(f"[Morph] storage 不可用，大小周期预测日志降级关闭", "WARN")

        try:
            self._param_mapper = ParameterMapper()
        except Exception as e:
            self._log(f"[Morph] ParameterMapper 构造失败: {e}", "WARN")
            self._param_mapper = None

        # 初始化结果 INFO 日志（审计要求：启动时明确知道大小周期/六维已加载）
        predictor_ready = getattr(self._morph_predictor, "storage", None) is not None
        mapper_ready = self._param_mapper is not None
        self._log(
            f"[Morph] 大小周期预测器/ParameterMapper 初始化完成 "
            f"(predictor={'ON' if predictor_ready else 'OFF'}, "
            f"mapper={'ON' if mapper_ready else 'OFF'})",
            "INFO",
        )

    def _log_morph_cycle_for_coin(self, coin: str, inst_id: str) -> None:
        """对单个币种运行大小周期预测并打 INFO 日志（只读，不影响交易逻辑）。

        日志覆盖：大周期 4y t_rel/阶段 + 小周期主周期/振幅/L/T +
        FFT 权重修正 + Hermite 切线修正 + 大周期边界约束(phase/level/amp_cap/decay)。
        与 data_server tab-morph 的 /cycle + /cycle_bounds 输出对齐，
        用于「大小周期 → 市场形态 → 六维参数」传递链的闭环审计。

        异常直接被吞，不影响主流程。
        """
        predictor = getattr(self, "_morph_predictor", None)
        if predictor is None:
            return
        try:
            _full = inst_id or f"{coin.upper()}USDT"
            mp = predictor.predict_with_fallback(_full, hist_days=60, forecast_days=5)
            if not mp.get("ok"):
                # 样本不足 / BTC fallback 失败 -> 降级记录（也算审计闭环：大小周期已执行）
                err = mp.get("error") or "未知"
                fallback = mp.get("fallback_used", False)
                self._log(
                    f"[{coin}] 大小周期预测(只读)未就绪 | fallback={fallback} | reason={err}",
                    "INFO",
                )
                return
            params = mp.get("params") or {}
            # 大周期 4 年：tab-morph 的 cycle4y + bounds（如果 predictor 内部附了）
            c4y = mp.get("cycle_4y") or {}
            bounds = mp.get("bounds") or {}
            t_rel = c4y.get("t_rel_current") or (bounds.get("t_rel_current") if isinstance(bounds, dict) else None)
            phase = (bounds.get("phase_hint") if isinstance(bounds, dict) else None) or c4y.get("stage")
            # 权重修正 / 切线修正
            corr = mp.get("correction_applied") or {}
            wc_pre = corr.get("weight_correction_pre") or {}
            tc_pre = corr.get("tangent_correction_pre") or {}
            # 边界约束三类动作（predictor 返回）
            fft_scale = mp.get("fft_scale_result") or {}
            pullback = mp.get("pullback_result") or {}
            overshoot = mp.get("overshoot_events") or []
            anchor = mp.get("anchor_correction_result")
            auto = mp.get("auto_correction_result")
            # 小周期主周期/振幅
            top3 = mp.get("top3_components") or []
            main_p = top3[0]["period"] if top3 else params.get("detected_period")
            main_a = top3[0]["amplitude"] if top3 else params.get("amplitude")

            wc_keys_n = len(wc_pre)
            tc_str = (f"m0×{float(tc_pre.get('m0_mul',1.0)):.3f} m1×{float(tc_pre.get('m1_mul',1.0)):.3f} "
                      f"bias={float(tc_pre.get('bias',0.0)):+.4f}" if tc_pre else "n/a")
            fft_a = f"amp×{float(fft_scale.get('scale_factor',1.0)):.3f}(orig={float(fft_scale.get('original_amp',0)):.3f})" if isinstance(fft_scale,dict) and fft_scale.get("applied") else "未触发"
            pb = f"回拉{int(pullback.get('overshoot_count',0))}次" if isinstance(pullback,dict) and pullback.get("applied") else "未越界"
            anchor_note = ""
            if isinstance(anchor, dict):
                tag = "OK" if anchor.get("ok") or anchor.get("applied") else "冷却"
                anchor_note = f" | 锚定大修正={tag}"
            auto_note = ""
            if isinstance(auto, dict):
                if auto.get("ok") or auto.get("reason"):
                    auto_note = f" | 在线小修正={auto.get('reason') or 'OK'}"
            overshoot_n = len(overshoot) if isinstance(overshoot, list) else 0

            self._log(
                f"[{coin}] 大小周期预测(只读) | "
                f"大周期 t_rel={t_rel} phase={phase or '-'} | "
                f"小周期 主周期={main_p}d amp={main_a} L={params.get('current_L','-')} T={params.get('current_T','-')} | "
                f"权重修正={wc_keys_n}键 | 切线修正=[{tc_str}] | "
                f"边界约束[FFT {fft_a} | 预测{pb} | 越界事件={overshoot_n}]{anchor_note}{auto_note}",
                "INFO",
            )
        except Exception:
            # 全分支兜底，任何异常都不影响主轮询
            return

    def _log_param_mapper_snapshot(self, coin: str, inst_id: str, inference: dict) -> None:
        """对齐 tab-morph /api/morph/params：ParameterMapper 六维参数快照（只读）。

        目的：审计「市场形态 → 六维参数 → 注入 BCRM 2.0」段③的理论值日志。
        优先使用 inference.snapshot.level_smooth/trend_smooth/consensus（若存在），
        否则兜底：大小周期预测 current_L/current_T + C=0.5（保守中性）。
        结果只打日志，不改变任何交易参数。
        """
        mapper = getattr(self, "_param_mapper", None)
        if mapper is None:
            return
        try:
            snap = (inference or {}).get("snapshot") or {}
            L = float(snap.get("level_smooth", 0.0) or 0.0)
            T = float(snap.get("trend_smooth", 0.0) or 0.0)
            C = float(snap.get("consensus", 0.0) or 0.0)
            src_tag = "snapshot"
            if L == 0.0 and T == 0.0 and C == 0.0:
                # 兜底：从大小周期预测器取 L/T，C 默认 0.5（中性），让日志可闭环
                predictor = getattr(self, "_morph_predictor", None)
                if predictor is not None:
                    try:
                        _full = inst_id or f"{coin.upper()}USDT"
                        _cy = predictor.predict_with_fallback(_full, hist_days=60, forecast_days=5)
                        if _cy.get("ok"):
                            _pa = _cy.get("params") or {}
                            _L = _pa.get("current_L")
                            _T = _pa.get("current_T")
                            if _L is not None and _T is not None:
                                L = float(_L); T = float(_T)
                                C = 0.5
                                src_tag = f"predictor(consensus=default0.5)"
                    except Exception:
                        pass
            if L == 0.0 and T == 0.0 and C == 0.0:
                return

            global_params = mapper.map_global_parameters(L, T, C)
            sw_full = mapper.map_sector_weights(L, T, C, sector_betas=getattr(mapper, "_DEFAULT_IDENTITY_BETAS", None) or {
                "defi": (1.0,0.0,0.0),"ai":(1.0,0.0,0.0),"rwa":(1.0,0.0,0.0),"meme":(1.0,0.0,0.0),"l2":(1.0,0.0,0.0),
            })
            if isinstance(sw_full, dict) and "weights" in sw_full:
                sw = sw_full["weights"]
                tp_m = sw_full.get("sector_tp_mult") or {}
                sl_m = sw_full.get("sector_sl_mult") or {}
            else:
                sw, tp_m, sl_m = sw_full or {}, {}, {}

            def _gp(name):
                rng = global_params.get(name)
                if isinstance(rng, tuple) and len(rng) == 2:
                    lo, hi = map(float, rng)
                    return round((lo + hi) / 2.0, 5)
                return float(rng or 1.0)
            pos_c = _gp("global_position_mult")
            lscap_c = _gp("ls_ratio_cap")
            lb_c = _gp("long_bias")
            sb_c = _gp("short_bias")
            lt_c = _gp("long_threshold_mult")
            st_c = _gp("short_threshold_mult")
            sw_sorted = sorted(sw.items(), key=lambda kv: -float(kv[1]))[:3] if isinstance(sw, dict) else []
            sw_str = ",".join(f"{k}={float(v):.3f}(tp×{float(tp_m.get(k,1.0)):.2f}/sl×{float(sl_m.get(k,1.0)):.2f})" for k,v in sw_sorted) or "n/a"
            self._log(
                f"[{coin}] ParameterMapper 六维(只读对齐tab-morph src={src_tag}) | L={L:+.4f} T={T:+.4f} C={C:.4f} | "
                f"pos×{pos_c:.3f} ls_cap={lscap_c:.3f} "
                f"long_bias={lb_c:+.3f}/sh_bias={sb_c:+.3f} "
                f"long_thr×{lt_c:.3f}/short_thr×{st_c:.3f} | "
                f"sector_top3=[{sw_str}]",
                "INFO",
            )
        except Exception:
            return

    def _log_regime_hold_confirmation(self, coin: str, inference: dict, pos_info: dict) -> None:
        """已持仓形态乘数中性确认日志（段④ 注入 BCRM：持仓配置/资金风控）。

        即便没有新开仓（形态仓位调整/SL/TP 日志因为在 _open_position 未走而缺失），
        也在持仓路径打印一条确认：当前形态 regime 的 pos/tp/sl 乘数 × 实际持仓方向/持仓金额/
        实际 S2 调整后 SLTP ROI 是否与乘数单调一致（=1.0 也算「生效路径闭环」）。
        纯描述性 INFO，不修改任何变量。
        """
        try:
            _reg = inference.get("_regime_pred") or "UNKNOWN"
            _rm = dict(inference.get("_regime_multipliers") or {})
            pm_pos = float(_rm.get("position_mult", 1.0))
            pm_tp  = float(_rm.get("tp_mult", 1.0))
            pm_sl  = float(_rm.get("sl_mult", 1.0))
            pm_thr = float(_rm.get("threshold_mult", 1.0))
            pos_side = pos_info.get("pos_side") or "-"
            upl = float(pos_info.get("upl", 0) or 0)
            upl_pct = float(pos_info.get("upl_ratio", 0) or 0)
            entry_px = float(pos_info.get("entry_px", 0) or inference.get("price", 0) or 0)
            pos_sz = float(pos_info.get("position_size", 0) or 0)
            self._log(
                f"[{coin}] 已持仓形态乘数作用确认 | regime={_reg} "
                f"pos×{pm_pos:.3f} tp×{pm_tp:.3f} sl×{pm_sl:.3f} thr×{pm_thr:.3f} | "
                f"持仓={pos_side} 金额≈{pos_sz*entry_px:+.1f}U 盈亏={upl:+.2f}({upl_pct:+.2%}) "
                f"(基线路径，乘数仅用于记录/后续promote对比，不改变当前持仓)",
                "INFO",
            )
        except Exception:
            return

    def _run_polling_level_learning_and_ab(self):
        """每轮轮询结束时执行：段⑤在线学习 + 段⑥AB闸门状态（只读审计日志）。

        对应 data_server 的 /api/morph/correct?min=3 与 /api/eval/baseline：
          - 在线学习：对 BTC 执行一次 evaluate_and_correct（最小样本由方法内兜底判断不足 3 条会返回 reason 不修正）
            + 再对持仓币种（self.position_tracker.open）尝试运行（对 fallback_used=False 且 trajectory>=20 的币）
          - AB 闸门：读 RolloutManager 的 dual baseline 评估结果（与 data_server 共用 state）
        全部只记录日志，不做任何 promote 动作（promote 保留为 data_server 手动 API 触发，避免自动升级）。
        """
        # --- [段①②③ 核心锚定币种 BTCUSDT：对齐 tab-morph /api/morph/cycle+/params] ---
        # 用户指定以 http://127.0.0.1:8765 市场形态预测 tab 数据为基准 → 直接复用
        # data_server_fixed.get_morph_cycle() + get_morph_params() 同一函数（与 tab HTTP
        # 路由共享实现），确保 BTC 的 大小周期 / 六维 值与 tab 完全一致，不留偏差。
        # 其他币种的大小周期&六维已经在 _execute_trade 内 _log_morph_cycle_for_coin +
        # _log_param_mapper_snapshot 兜底生成。此处 BTC 作为基准锚，强制使用 tab 同源函数。
        try:
            try:
                from data_server_fixed import get_morph_cycle, get_morph_params  # type: ignore
            except Exception:
                # 若主包路径 import 失败（不同 CWD 场景），补 sys.path 再试
                import sys as _sys
                import pathlib as _pl
                _sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent.parent))
                from data_server_fixed import get_morph_cycle, get_morph_params  # type: ignore

            mc = get_morph_cycle("BTCUSDT", hist_days=60, forecast_days=5) or {}
            mp = get_morph_params("BTCUSDT") or {}
            if mc.get("ok") or mp.get("ok"):
                # 段①：大小周期预测（tab-morph 同源）
                _p = mc.get("params") or {}
                _t3 = mc.get("top3_components") or []
                _t4y = mc.get("cycle_4y") or {}
                _trel = (_t4y.get("t_rel_current")
                         or ((mc.get("bounds") or {}).get("t_rel_current")
                             if isinstance(mc.get("bounds"), dict) else None))
                _ph = (((mc.get("bounds") or {}).get("phase_hint")
                        if isinstance(mc.get("bounds"), dict) else None)
                       or _t4y.get("stage"))
                _corr = mc.get("correction_applied") or {}
                _wc_n = len(_corr.get("weight_correction_pre") or {})
                _tct = _corr.get("tangent_correction_pre") or {}
                _tcs = (f"m0×{float(_tct.get('m0_mul',1.0)):.3f} m1×{float(_tct.get('m1_mul',1.0)):.3f} "
                        f"bias={float(_tct.get('bias',0.0)):+.4f}" if _tct else "n/a")
                _fs = mc.get("fft_scale_result") or {}
                _pb = mc.get("pullback_result") or {}
                _oa = len(mc.get("overshoot_events") or [])
                _t3s = [(round(c['period'],1), round(c['amplitude'],4)) for c in _t3] if _t3 else []
                self._log(
                    f"[BTC] 大小周期预测(锚定tab-morph同源) | "
                    f"大周期 t_rel={_trel} phase={_ph or '-'} halving_days_left={_t4y.get('halving_days_left')} | "
                    f"小周期 top3={_t3s} main={(_t3[0]['period'] if _t3 else '-')}d amp={(_t3[0]['amplitude'] if _t3 else '-')} | "
                    f"形态三维 L={_p.get('current_L','-')} T={_p.get('current_T','-')} | "
                    f"权重修正={_wc_n}键 | 切线修正=[{_tcs}] | "
                    f"边界约束[FFT amp×{_fs.get('scale_factor',1.0):.3f} applied={_fs.get('applied')} | "
                    f"预测pullback applied={_pb.get('applied')} | 越界事件={_oa}] | "
                    f"fallback={mc.get('fallback_used')} final_sym={mc.get('final_symbol')}",
                    "INFO",
                )
                # 段②③：六维参数（tab-morph 同源 / api/morph/params inputs 与 BTC 六维）
                if mp.get("ok"):
                    _ins = mp.get("inputs") or {}
                    _L = _ins.get("level_smooth")
                    _T = _ins.get("trend_smooth")
                    _C = _ins.get("consensus")
                    _gp = mp.get("global_params") or []
                    _gpd = {g["name"]: (g["center"], g.get("identity_center")) for g in _gp}
                    _pos = (_gpd.get("global_position_mult") or (1.0, 1.0))[0]
                    _lsc = (_gpd.get("ls_ratio_cap") or (1.15, 0.5))[0]
                    _lbi = (_gpd.get("long_bias") or (0.0, 0.0))[0]
                    _sbi = (_gpd.get("short_bias") or (0.0, 0.0))[0]
                    _ltt = (_gpd.get("long_threshold_mult") or (1.0, 1.0))[0]
                    _stt = (_gpd.get("short_threshold_mult") or (1.0, 1.0))[0]
                    _sw = mp.get("sector_weights") or []
                    _sws = sorted(_sw, key=lambda s: -float(s.get("weight", 0)))[:3]
                    _sw_str = ",".join(
                        f"{s.get('name','?')}={float(s.get('weight',0)):.3f}"
                        f"(tp×{float(s.get('tp_mult',1.0)):.2f}/sl×{float(s.get('sl_mult',1.0)):.2f})"
                        for s in _sws
                    ) or "n/a"
                    _sw_sum = round(sum(float(s.get("weight", 0)) for s in _sw), 6)
                    self._log(
                        f"[BTC] ParameterMapper 六维(锚定tab-morph同源 inputs) | "
                        f"L={_L} T={_T} C={_C} | "
                        f"pos×{_pos:.3f} ls_cap={_lsc:.3f} "
                        f"long_bias={_lbi:+.3f}/sh_bias={_sbi:+.3f} "
                        f"long_thr×{_ltt:.3f}/short_thr×{_stt:.3f} | "
                        f"sector_top3=[{_sw_str}] Σsw={_sw_sum}",
                        "INFO",
                    )
        except Exception:
            # 同源函数异常时，降级回 polling_trader 内部 predictor 生成（仍能闭环，只是数值与 tab 有差异）
            try:
                self._log_morph_cycle_for_coin("BTC", "BTCUSDT")
                self._log_param_mapper_snapshot("BTC", "BTCUSDT", {})
            except Exception:
                pass

        # --- ⑤ 在线学习：MorphCyclePredictor.evaluate_and_correct ---
        predictor = getattr(self, "_morph_predictor", None)
        if predictor is not None:
            # 目标币种列表：BTC(主) + 实际持仓币 + self.coins 列表头部 3 个
            targets: list = []
            if "BTC" not in targets:
                targets.append(("BTCUSDT", 3))
            try:
                for pos in (self.position_tracker.all_open_positions() if hasattr(self.position_tracker,"all_open_positions") else []):
                    inst = f"{pos.coin.upper()}USDT"
                    if inst not in [t[0] for t in targets]:
                        targets.append((inst, 3))
            except Exception:
                pass
            for coin_i in (getattr(self, "coins", []) or [])[:3]:
                inst = f"{str(coin_i).upper()}USDT"
                if inst not in [t[0] for t in targets]:
                    targets.append((inst, 3))
            for (inst, min_s) in targets:
                try:
                    res = predictor.evaluate_and_correct(inst, min_filled_samples=min_s)
                    backfilled = int(res.get("backfilled", 0) or 0)
                    filled_total = int(res.get("filled_total", 0) or 0)
                    mae_before = res.get("mae_before")
                    mae_after = res.get("mae_after")
                    reason = res.get("reason") or ""
                    corr = res.get("correction") or {}
                    wc_n = len(corr.get("weight_correction") or {})
                    tc = corr.get("tangent_correction") or {}
                    tc_str = (f"m0×{float(tc.get('m0_mul',1.0)):.3f} m1×{float(tc.get('m1_mul',1.0)):.3f} bias={float(tc.get('bias',0.0)):+.4f}"
                              if tc else "-")
                    if filled_total >= min_s:
                        self._log(
                            f"[Morph][在线学习] {inst} 执行修正 | "
                            f"backfilled={backfilled} filled={filled_total} "
                            f"MAE {mae_before}->{mae_after} | "
                            f"weight修正={wc_n}键 tangent修正=[{tc_str}]",
                            "INFO",
                        )
                    else:
                        self._log(
                            f"[Morph][在线学习] {inst} 跳过修正 | "
                            f"backfilled={backfilled} filled={filled_total}/{min_s} reason={reason or '样本不足'}",
                            "INFO",
                        )
                except Exception:
                    continue

        # --- ⑥ AB 闸门：RolloutManager allow_promotion / 当前α / shadow样本数 ---
        try:
            from scripts.memory_l4.bcrm2.scripts.phase_c_rollout_manager import RolloutManager  # type: ignore
            import os
            from pathlib import Path
            # 统一使用 alpha_rollout_state.json（与 data_server API 共享）
            state_path = Path(os.environ.get(
                "V15_AI_ROLLOUT_STATE_PATH",
                str(Path(__file__).resolve().parent.parent.parent / "data" / "alpha_rollout_state.json"),
            ))
            mgr = RolloutManager(state_path=state_path)
            status = mgr.get_status()
            # 同步刷新实盘 alpha_blend 值（每次 AB 闸门检查时重新读取）
            _latest_alpha = status.get("current_alpha")
            if _latest_alpha is not None and self._alpha_blend_enabled:
                _new_alpha = min(float(_latest_alpha), ALPHA_BLEND_MAX)
                if abs(_new_alpha - self._alpha_blend) > 1e-6:
                    self._log(
                        f"[AlphaBlend] AB闸门刷新 α: {self._alpha_blend:.4f} → {_new_alpha:.4f}",
                        "INFO",
                    )
                    self._alpha_blend = _new_alpha
        except Exception as e:
            status = {"error": str(e)}

        # Shadow 记录数（直接用 RolloutManager 内部 window 统计，若没有则从 shadow DB 估算）
        try:
            from data_server_fixed import get_dual_baseline_report  # type: ignore
            report = get_dual_baseline_report(days=7)
            inject_stats = (report.get("inject_run_stats") or {}) if report.get("ok") else {}
            ev = (report.get("evaluation") or {}) if report.get("ok") else {}
            n_shadow = report.get("window_records", 0) if report.get("ok") else 0
            allow_promo = ev.get("allow_promotion", False)
            reasons = ev.get("reasons") or []
            enable_true = inject_stats.get("enable_true", 0)
            enable_false = inject_stats.get("enable_false", 0)
            inject_ratio = inject_stats.get("inject_ratio", 0.0)
        except Exception:
            n_shadow = 0
            allow_promo = False
            reasons = ["AB报告读取失败"]
            enable_true = enable_false = 0
            inject_ratio = 0.0

        cur_alpha = None
        if isinstance(status, dict) and "error" not in status:
            cur_alpha = status.get("current_alpha")
            hist_n = status.get("history_length", 0)
        else:
            cur_alpha = status.get("current_alpha") if isinstance(status, dict) else None
            hist_n = 0
        reasons_str = "；".join(str(r) for r in reasons) if reasons else "n/a"
        # H3(P1)：FMA_REGIME_FILTER_ENABLED（后置层 5态差异化过滤开关）目前默认 False（回测验证效果不佳），
        #          在 AB闸门日志中显示，避免审计时遗漏能力状态；等 Shadow ≥60 条再评估是否打开 True。
        fma_on = bool(getattr(self, "FMA_REGIME_FILTER_ENABLED", False))

        # ── H3-FMA 渐进自动检查：每 20h 评估一次，若样本≥60+达标则自动切 FMA=ON
        try:
            _all_7d_records = []
            try:
                # 直接从 data_server 复用 shadow_records_7d（若 data_server_fixed 模块有缓存）
                from data_server_fixed import _shadow_logs_window  # type: ignore
                _all_7d_records = list(_shadow_logs_window(days=7))
            except Exception:
                _all_7d_records = []
            _fma_check = self._fma_auto_check(n_shadow_total=n_shadow,
                                               shadow_records_7d=_all_7d_records)
        except Exception as _e1:
            _fma_check = {"triggered": False, "action": "ERROR", "delta": 0.0,
                          "shadow_off_total": 0, "shadow_on_total": 0,
                          "win_rate_off": 0.0, "win_rate_on": 0.0,
                          "reason": f"调用失败: {_e1}"}
        self._log(
            f"[AB闸门][双基线评估] 样本={n_shadow}/30 | inject={enable_true}T/{enable_false}F(ratio={inject_ratio:.2f}) | "
            f"α={self._alpha_blend:.4f} "
            f"allow_promotion={'ALLOW' if allow_promo else 'BLOCK'} | "
            f"原因: {reasons_str} | "
            f"FMA_5态过滤开关={'ON(实验/对比)' if fma_on else 'OFF(默认双均线确认趋势)'}",
            "INFO",
        )
        _fma_triggered = bool(_fma_check.get("triggered", False))
        _fma_action = str(_fma_check.get("action", "SKIP"))
        _fma_delta = float(_fma_check.get("delta", 0.0) or 0.0)
        _fma_off_total = int(_fma_check.get("shadow_off_total", 0) or 0)
        _fma_on_total = int(_fma_check.get("shadow_on_total", 0) or 0)
        _fma_min_samples = 60
        try:
            _fm = self._fma_get_rollout_manager()
            if _fm is not None:
                _fma_min_samples = int(getattr(_fm, "fma_min_samples", 60) or 60)
        except Exception:
            pass
        self._log(
            f"[FMA渐进自动检查] 触发={'YES' if _fma_triggered else 'BLOCK'} "
            f"action={_fma_action} | "
            f"FMA_OFF样本={_fma_off_total}/{_fma_min_samples}(≥触发门槛) | "
            f"FMA_ON样本={_fma_on_total} | "
            f"Δ={_fma_delta:+.2%}(ON-OFF胜率差) | "
            f"当前={'ON' if fma_on else 'OFF'} | "
            f"说明: {_fma_check.get('reason','n/a')}",
            "INFO" if _fma_action in ("KEEP", "SKIP", "SKIP_TIME_GATE") else "WARN",
        )

    # ================================================================
    # Phase B: ShadowLogger 影子模式集成
    # 设计原则：
    #   • SHADOW_LOGGER_ENABLED 默认 False → _shadow_logger=None → 字节等价
    #   • 只记录，不改变任何交易参数
    #   • 异常被 catch，不影响主流程
    # ================================================================

    def _init_shadow_logger(self):
        """初始化 ShadowLogger（若开关开启）。

        开关关闭时：_shadow_logger = None，后续 _record_shadow_log 直接 return。
        开关开启时：尝试构造 ShadowLogger，失败降级为 None（不抛异常）。
        """
        if not SHADOW_LOGGER_ENABLED:
            self._shadow_logger = None
            return
        try:
            from scripts.memory_l4.bcrm2.morph_cycle_predictor import MorphCyclePredictor
            from scripts.memory_l4.bcrm2.parameter_mapper import ParameterMapper

            # 复用 bcrm2_adapters 中的 storage（若已初始化）
            storage = None
            if hasattr(self, "bcrm2_adapters") and self.bcrm2_adapters:
                # 取第一个 adapter 的 storage（所有 adapter 共享同一 storage）
                first_adapter = next(iter(self.bcrm2_adapters.values()))
                if hasattr(first_adapter, "storage"):
                    storage = first_adapter.storage
            if storage is None:
                # 兜底：新建一个 storage（Phase B 影子模式独立 DB）
                from scripts.memory_l4.bcrm2.run_evolution_pipeline import get_storage
                storage = get_storage()

            predictor = MorphCyclePredictor(storage)
            mapper = ParameterMapper()
            self._shadow_logger = ShadowLogger(storage, predictor, mapper)
            self._log("[ShadowLogger] 影子模式已启用（只记录，不影响交易）", "INFO")
        except Exception as e:
            self._shadow_logger = None
            self._log(f"[ShadowLogger] 初始化失败，降级为关闭: {e}", "WARN")

    def _record_shadow_log(self, coin: str, inference: dict,
                            actual_params: dict):
        """记录一条 Shadow 日志（若开关开启且 logger 可用）。

        异常被 catch，不影响主流程。开关关闭或 logger 为 None 时直接 return。
        """
        if not SHADOW_LOGGER_ENABLED:
            return
        if not getattr(self, "_shadow_logger", None):
            return
        try:
            enable_inject = getattr(self, "_enable_inject_runtime", False)
            alpha_blend = getattr(self, "_alpha_blend", 0.0)
            fma_shadow_allowed = inference.get("fma_shadow_allowed")
            fma_shadow_eff_thr = inference.get("fma_shadow_eff_threshold")
            self._shadow_logger.record_polling(
                coin, inference, actual_params,
                enable_inject=enable_inject, alpha_blend=alpha_blend,
                fma_on_allowed=fma_shadow_allowed,
                fma_on_eff_threshold=fma_shadow_eff_thr,
            )
        except Exception as e:
            self._log(f"[{coin}] Shadow 记录失败（已忽略）: {e}", "DEBUG")

    # ================================================================
    # Phase C: α blend 前瞻参数上线集成
    # 设计原则：
    #   • ALPHA_BLEND_ENABLED 默认 False → _alpha_blend=0.0 → 字节等价
    #   • α blend 在 ParameterMapper 层实现，交易层只传值
    #   • DEFAULT_ALPHA_BLEND 受 ALPHA_BLEND_MAX=0.5 硬约束
    # ================================================================

    def _init_alpha_blend(self):
        """初始化 α blend 参数（若开关开启）。

        开关关闭时：_alpha_blend=0.0（字节等价 Phase 0）。
        开关开启时：从 RolloutManager 状态文件读取 current_alpha（受 ALPHA_BLEND_MAX 约束），
                   若状态文件不存在或读取失败则回退到 DEFAULT_ALPHA_BLEND。
        """
        if not ALPHA_BLEND_ENABLED:
            self._alpha_blend_enabled = False
            self._alpha_blend = 0.0
            return
        # 开关开启：优先从 RolloutManager 状态文件读取 current_alpha
        self._alpha_blend_enabled = True
        _alpha = DEFAULT_ALPHA_BLEND
        try:
            import os
            from pathlib import Path
            # 与 data_server_fixed.py _get_rollout_manager() 使用同一状态文件
            _state_path = Path(os.environ.get(
                "V15_AI_ROLLOUT_STATE_PATH",
                str(Path(__file__).resolve().parent.parent.parent / "data" / "alpha_rollout_state.json"),
            ))
            from scripts.memory_l4.bcrm2.scripts.phase_c_rollout_manager import RolloutManager  # type: ignore
            _mgr = RolloutManager(state_path=_state_path)
            _mgr.load()
            if _mgr.current_alpha is not None:
                _alpha = float(_mgr.current_alpha)
                self._log(
                    f"[AlphaBlend] 从状态文件读取 α={_alpha:.4f} "
                    f"(path={_state_path.name})",
                    "INFO",
                )
        except Exception as _e:
            self._log(f"[AlphaBlend] 状态文件读取失败，回退到默认 α={DEFAULT_ALPHA_BLEND}: {_e}", "WARN")
        self._alpha_blend = min(_alpha, ALPHA_BLEND_MAX)
        self._log(
            f"[AlphaBlend] 前瞻参数上线已启用，当前 α={self._alpha_blend:.4f} "
            f"(max={ALPHA_BLEND_MAX})",
            "INFO",
        )

    # ================================================================
    # H3-FMA 渐进自动开关：还原 + 懒加载 RolloutManager + 自动评估
    # 设计原则：
    #   • 任何错误被 catch，默认 FMA=False（不影响主交易）
    #   • RolloutManager 通过 phase_c_rollout_state.json 与 data_server / CLI 共享状态
    #   • 冷启动时只做一次 restore；自动评估只在 AB闸门口 + 样本≥60 + 距上次≥20h 触发
    # ================================================================

    def _fma_get_rollout_state_path(self):
        """返回 alpha_rollout_state.json 路径（与 data_server API 共享同一文件）。"""
        if self._fma_phase_c_state_path:
            return self._fma_phase_c_state_path
        import os
        from pathlib import Path
        # 统一使用 alpha_rollout_state.json（与 data_server_fixed.py _get_rollout_manager 一致）
        # RolloutManager 同时管理 alpha_blend 和 fma_enabled 字段
        path = Path(os.environ.get(
            "V15_AI_ROLLOUT_STATE_PATH",
            str(Path(__file__).resolve().parent.parent.parent / "data" / "alpha_rollout_state.json"),
        ))
        self._fma_phase_c_state_path = path
        return path

    def _fma_get_rollout_manager(self, force_new: bool = False):
        """懒加载 RolloutManager（单例）。失败返回 None。"""
        if (not force_new) and self._fma_phase_c_mgr is not None:
            return self._fma_phase_c_mgr
        try:
            from scripts.memory_l4.bcrm2.scripts.phase_c_rollout_manager import RolloutManager  # type: ignore
            mgr = RolloutManager(state_path=self._fma_get_rollout_state_path())
            self._fma_phase_c_mgr = mgr
            return mgr
        except Exception as e:
            self._log(f"[FMA渐进] RolloutManager 初始化失败（保持默认开关）: {e}", "WARN")
            return None

    def _fma_load_from_rollout(self):
        """冷启动：从 phase_c_rollout_state.json 读 fma_enabled 覆盖类默认 False。"""
        try:
            mgr = self._fma_get_rollout_manager()
            if mgr is None:
                return
            prev = bool(getattr(self, "FMA_REGIME_FILTER_ENABLED", False))
            new = bool(getattr(mgr, "fma_enabled", False))
            self.FMA_REGIME_FILTER_ENABLED = new
            if prev != new:
                self._log(
                    f"[FMA渐进] 冷启动还原开关: FMA={'ON' if new else 'OFF'} "
                    f"(类默认={'ON' if prev else 'OFF'} → rollout同步={'ON' if new else 'OFF'}) "
                    f"min_samples={getattr(mgr,'fma_min_samples',60)} "
                    f"delta={getattr(mgr,'fma_required_delta',0.05):.0%}",
                    "INFO",
                )
            else:
                self._log(
                    f"[FMA渐进] 冷启动开关未变更: {'ON' if new else 'OFF'} "
                    f"(类默认=rollout一致) min_samples={getattr(mgr,'fma_min_samples',60)}",
                    "DEBUG",
                )
        except Exception as e:
            self._log(f"[FMA渐进] 冷启动加载失败（保留类默认）: {e}", "WARN")

    def _fma_auto_check(self, n_shadow_total: int,
                        shadow_records_7d: list = None) -> dict:
        """AB闸门口调用：距上次≥20h 且 shadow_off_total ≥ mgr.fma_min_samples 时，
        调 evaluate_fma_toggle 并 自动切换 self.FMA_REGIME_FILTER_ENABLED + 写回 rollout_state。

        返回当前 check 结果 dict（用于打印日志）。
        """
        import time
        now = time.time()
        fallback = {"triggered": False, "action": "SKIP_TIME_GATE",
                    "prev_enabled": bool(getattr(self, "FMA_REGIME_FILTER_ENABLED", False)),
                    "new_enabled": bool(getattr(self, "FMA_REGIME_FILTER_ENABLED", False)),
                    "shadow_off_total": 0, "win_rate_off": 0.0,
                    "shadow_on_total": 0, "win_rate_on": 0.0, "delta": 0.0,
                    "reason": f"评估冷却期未到（剩余 {int(self._FMA_AUTO_CHECK_INTERVAL_SEC - (now - self._fma_last_auto_check_ts)) // 3600}h）"}
        if (now - self._fma_last_auto_check_ts) < self._FMA_AUTO_CHECK_INTERVAL_SEC:
            return fallback
        self._fma_last_auto_check_ts = now
        try:
            mgr = self._fma_get_rollout_manager()
            if mgr is None:
                return {**fallback, "reason": "RolloutManager不可用"}
            # 如果调用方没传 records，自行从 storage 拉 7 天（所有币种）
            if shadow_records_7d is None:
                shadow_records_7d = []
                try:
                    # 复用 _init_shadow_logger 里的 storage（懒加载）
                    storage = None
                    if hasattr(self, "_shadow_logger") and getattr(self, "_shadow_logger", None):
                        storage = getattr(self._shadow_logger, "storage", None)
                    if storage is None:
                        if hasattr(self, "bcrm2_adapters") and self.bcrm2_adapters:
                            first_adapter = next(iter(self.bcrm2_adapters.values()))
                            storage = getattr(first_adapter, "storage", None)
                    if storage is None:
                        try:
                            from scripts.memory_l4.bcrm2.run_evolution_pipeline import get_storage  # type: ignore
                            storage = get_storage()
                        except Exception:
                            storage = None
                    if storage:
                        for sym in list(getattr(self, "coins", []) or []):
                            try:
                                shadow_records_7d.extend(storage.get_shadow_log(sym, days=7))
                            except Exception:
                                continue
                except Exception:
                    shadow_records_7d = shadow_records_7d or []

            prev = bool(getattr(self, "FMA_REGIME_FILTER_ENABLED", False))
            result = mgr.evaluate_fma_toggle(shadow_records_7d)
            new_enabled = bool(result.get("new_enabled", prev))
            # 应用到 trader 实例（内存实时生效，下一轮 threshold 段就自动走到 FMA=ON 差异化过滤）
            if new_enabled != prev:
                self.FMA_REGIME_FILTER_ENABLED = new_enabled
                self._log(
                    f"[FMA渐进] 自动切换: {'ON' if prev else 'OFF'} → {'ON' if new_enabled else 'OFF'} | "
                    f"{result.get('reason','')}",
                    "WARN",
                )
            else:
                self.FMA_REGIME_FILTER_ENABLED = new_enabled
            # 持久化回 rollout_state.json（下次冷启动可还原；data_server API 同步可见）
            try:
                mgr.save()
            except Exception as _es:
                self._log(f"[FMA渐进] rollout_state.json 保存失败（仅内存生效）: {_es}", "WARN")
            # 附带当前样本数给日志
            result["n_shadow_total"] = int(n_shadow_total or 0)
            result.setdefault("reason", result.get("reason") or "n/a")
            return result
        except Exception as e:
            self._log(f"[FMA渐进] 自动评估失败（已忽略）: {e}", "WARN")
            return {**fallback, "reason": f"异常: {e}"}

    def _enable_inject_file_path(self):
        """返回 enable_inject 状态文件路径（与 data_server 共用）。"""
        import os
        return os.environ.get(
            "V15_AI_INJECT_STATE_PATH",
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)
            ))), "data/enable_inject_state.json"),
        )

    def _reload_enable_inject_if_stale(self, force: bool = False) -> bool:
        """周期性刷新 enable_inject 开关（5 分钟缓存，避免磁盘 IO）。"""
        import os as _os
        import json as _json
        import time as _time
        now = _time.time()
        if (not force) and (now - self._enable_inject_last_reload
                            < self._enable_inject_reload_interval):
            return bool(self._enable_inject_runtime)
        fp = self._enable_inject_file_path()
        enabled = False
        try:
            if _os.path.exists(fp):
                with open(fp, "r", encoding="utf-8") as f:
                    data = _json.load(f)
                enabled = bool(data.get("enabled", False))
        except Exception as _e:
            self._log(f"[Inject] 读取 enable_inject 文件失败（使用默认 False）: {_e}",
                      "WARN")
            enabled = False
        was = self._enable_inject_runtime
        self._enable_inject_runtime = enabled
        self._enable_inject_last_reload = now
        if was != enabled:
            self._log(
                f"[Inject] 融合层 enable_inject 切换：{was} → {enabled} "
                f"（{('字节等价模式' if not enabled else 'AI 注入模式')}）",
                "INFO",
            )
        return enabled

    def _init_enable_inject(self):
        """初始化 enable_inject 开关（启动时从磁盘文件加载）。"""
        # 默认 False = 字节等价安全模式，完全不注入
        self._enable_inject_runtime = False
        self._reload_enable_inject_if_stale(force=True)

    def _check_dynamic_blacklist(self, coin: str) -> tuple:
        """检查币种是否在动态黑名单中（未过期则拦截）

        Returns:
            (blocked: bool, reason: str)
        """
        # 1. 静态手动黑名单（config.json 配置）
        if coin in self.blacklist_coins:
            return True, f"手动黑名单({coin})"

        # 2. 动态黑名单检查
        info = self.dynamic_blacklist.get(coin)
        if not info:
            return False, ""

        now = time.time()
        if now < info["expire_ts"]:
            remaining_hours = (info["expire_ts"] - now) / 3600
            return True, (
                f"动态黑名单({coin}) 连亏{info.get('streak', '?')}次 "
                f"剩余{remaining_hours:.1f}h"
            )
        else:
            # 过期自动释放
            del self.dynamic_blacklist[coin]
            self._log(f"[{coin}] 动态黑名单到期释放 | 可恢复交易")
            return False, ""

    def _add_to_dynamic_blacklist(self, coin: str, streak: int, reason: str = ""):
        """将币种加入动态黑名单（连续亏损达标时调用）"""
        now = time.time()
        expire_ts = now + self.DYNAMIC_BLACKLIST_DURATION_SEC
        self.dynamic_blacklist[coin] = {
            "expire_ts": expire_ts,
            "added_ts": now,
            "streak": streak,
            "reason": reason or f"连续{streak}次亏损",
        }
        self._log(
            f"[{coin}] ⛔ 加入动态黑名单 | 原因: {reason or f'连续{streak}次亏损'} | "
            f"封禁3日(至{time.strftime('%Y-%m-%d %H:%M', time.localtime(expire_ts))})"
        )

    def _update_dynamic_blacklist_on_close(self, coin: str, pnl: float):
        """平仓后更新动态黑名单状态

        - 盈利：清除该币种的连亏计数
        - 亏损：连亏+1，达到阈值(2次)则加入黑名单3日
        """
        if not hasattr(self, '_coin_consecutive_losses'):
            self._coin_consecutive_losses = {}

        if pnl >= 0:
            if coin in self._coin_consecutive_losses:
                self._coin_consecutive_losses[coin] = 0
        else:
            current = self._coin_consecutive_losses.get(coin, 0) + 1
            self._coin_consecutive_losses[coin] = current

            if current >= self.DYNAMIC_BLACKLIST_CONSECUTIVE_LOSSES:
                info = self.dynamic_blacklist.get(coin)
                if not info or time.time() >= info["expire_ts"]:
                    self._add_to_dynamic_blacklist(coin, current)
                self._coin_consecutive_losses[coin] = 0

    def _sync_existing_positions(self):
        """同步 OKX 已有持仓到本地跟踪器"""
        self._log("[持仓同步] 检查 OKX 已有持仓...", "INFO")
        for coin in self.coins:
            inst_id = f"{coin}-USDT-SWAP"
            pos_result = self.okx_client.get_positions(inst_id)
            if not pos_result.get("ok"):
                continue
            positions = pos_result.get("positions", [])
            for pos in positions:
                if float(pos["pos"]) <= 0:
                    continue
                if self.position_tracker.has_open_position(inst_id):
                    continue
                self.position_tracker.open_position(
                    coin=coin,
                    inst_id=inst_id,
                    direction=pos["pos_side"],
                    entry_price=float(pos["avg_px"]),
                    confidence=0.8,
                    hexagram="已存在持仓",
                    market_snapshot={"price": float(pos.get("mark_px", pos["avg_px"]))},
                    strategy_source="bcrm",
                )
                self._log(
                    f"[持仓同步] 已同步 {coin} {pos['pos_side']} @ {pos['avg_px']} [易经推理持仓·启动同步]",
                    "INFO",
                )

        # 反向清理：本地有但 OKX 已无持仓的记录（已止损/止盈/手动平仓）
        for p in self.position_tracker.all_open_positions():
            inst_id = p.inst_id
            pos_result = self.okx_client.get_positions(inst_id)
            if not pos_result.get("ok"):
                continue
            okx_positions = [pp for pp in pos_result.get("positions", []) if float(pp["pos"]) > 0]
            if not okx_positions:
                self.position_tracker.close_position(
                    inst_id,
                    exit_price=0.0,
                    exit_reason="OKX持仓已不存在，清理本地残留",
                )
                self._log(f"[持仓同步] 清理本地残留 {inst_id} (OKX已无持仓)", "WARN")

        open_count = len(self.position_tracker.all_open_positions())
        external_count = sum(
            1 for p in self.position_tracker.all_open_positions() if p.strategy_source == "external"
        )
        self._log(
            f"[持仓同步] 完成，共 {open_count} 个持仓 (BCRM={open_count-external_count} 外部={external_count})",
            "INFO",
        )

        # ══════════════════════════════════════════════════════════════
        # v5.0 离场防频繁优化：离场确认状态机 + 持仓保护门禁
        # ══════════════════════════════════════════════════════════════
        # 离场动作2次确认状态机：避免单根K线假信号/瞬时波动直接平仓
        # key = f"{coin}:{action_type}"  value = {confirm_count: int, first_ts: float}
        self._exit_confirm_state: Dict[str, Dict[str, Any]] = {}
        # 确认窗口：2次轮询(约2min)内连续触发才执行
        self.EXIT_CONFIRM_WINDOW_SEC = 300  # 5分钟窗口
        self.EXIT_CONFIRM_REQUIRED = 2  # 需要2次连续触发
        # 离场动作类型
        self.EXIT_ACT_SIGNAL_REVERSE = "signal_reverse"
        self.EXIT_ACT_YIJING_FORCE_CLOSE = "yijing_force_close"
        self.EXIT_ACT_P3_EARLY_EXIT = "p3_early_exit"
        self.EXIT_ACT_EV_FORCE_CLOSE = "ev_force_close"       # Phase B: EV 雷达强制离场
        self.EXIT_ACT_RANKED_TP = "ranked_tp"                 # Phase C: 排名止盈离场 tag

        # 持仓保护期门禁（开仓后N小时内仅硬离场生效）
        # 保护期内：信号反转需更高置信度；易经TIGHTEN_SL/LOWER_TP/LOWER_SL/RAISE_TP全部屏蔽；
        #          P3提前退出需确认；仅保留开仓静态SL/TP + P0硬止损
        self.POSITION_PROTECTION_HOURS = 6.0  # 开仓后前6小时为保护期
        # P2 总开关：形态预测器（S5）+ 爆仓/期权宏观特征（仅 True 时网络调用 + 乘数注入 + call site 注入）
        #   False 时所有新代码路径 zero-byte 触达，字节等价旧路径，可随时回滚
        self.ENABLE_REGIME_AND_MACRO_S5 = True
        # 保护期内信号反转所需额外置信度(在effective_threshold之上再加)
        self.PROTECTED_REVERSE_CONF_BOOST = 0.12  # 如原阈值0.7→保护期需≥0.82
        # 保护期内最小亏损比例才允许P3提前退出（否则假预警会走）
        self.PROTECTED_P3_MIN_LOSS_PCT = -0.08  # 浮亏≥8%才允许P3退出（保护期内）
        self._log(
            f"[离场防频繁] v5.0优化已启用：保护期={self.POSITION_PROTECTION_HOURS:.0f}h "
            f"| 离场确认={self.EXIT_CONFIRM_REQUIRED}次/{self.EXIT_CONFIRM_WINDOW_SEC//60:.0f}min "
            f"| 保护期反转置信+{self.PROTECTED_REVERSE_CONF_BOOST:.0%}",
            "INFO",
        )

    def _save_exit_strategy_decision(
        self, coin: str, decision, age_hours: float,
        in_protection: bool, ev, confidence: float,
        pnl=None, win=None,
    ) -> None:
        """记录 ExitManager 策略决策到 exit_strategy_log（异常不阻断主流程）。

        Spec: docs/superpowers/specs/2026-08-20-exit-manager-design.md §5
        """
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
            })
        except Exception as _e:
            self._log(f"[{coin}] exit_strategy_log 记录失败（不阻断）: {_e}", "WARN")

    def _run_startup_inspection(self):
        """启动时运行 inspect 诊断命令，快速检查系统状态"""
        self._log("[系统诊断] 启动时执行状态检查...", "INFO")
        try:
            from scripts.memory_l4.inspect import SystemInspector

            inspector = SystemInspector()
            report = inspector.inspect(
                panel_ids=["system", "positions", "models", "connections", "risk"]
            )

            for panel in report.panels:
                status_icon = {"ok": "✅", "warn": "⚠️", "error": "❌"}.get(panel.status, "ℹ️")
                self._log(f"  {status_icon} [{panel.name}] {panel.summary}", panel.status.upper())
                for key, val in panel.details.items():
                    if isinstance(val, (int, float, str)) and len(str(val)) <= 50:
                        self._log(f"    └─ {key}: {val}")

            if report.overall_status == "error":
                self._log("[系统诊断] 发现错误，请检查相关组件", "WARN")
            else:
                self._log("[系统诊断] 启动检查通过", "INFO")

        except Exception as e:
            self._log(f"[系统诊断] 执行失败: {e}，继续运行", "WARN")

    def _log(self, msg: str, level: str = "INFO"):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] [{level}] {msg}"
        print(line, flush=True)
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(
                    json.dumps({"ts": ts, "level": level, "msg": msg}, ensure_ascii=False) + "\n"
                )
        except Exception:
            pass

    def _health_check_bcrm2(self) -> tuple:
        """措施1：BCRM 2.0 启动健康检查

        主动验证 BCRM 2.0 关键模块导入路径与核心依赖可用性，
        避免运行时才发现 "No module named 'bcrm2'" 等问题导致静默回退。

        Returns:
            (healthy: bool, reason: str) — healthy=True 表示检查通过
        """
        checks = []

        # 1. 验证核心模块导入路径
        try:
            from scripts.memory_l4.bcrm2_adapter import BCRM2Adapter  # noqa: F401

            checks.append(("BCRM2Adapter 导入", True, ""))
        except Exception as e:
            checks.append(("BCRM2Adapter 导入", False, str(e)))

        # 2. 验证辩证ML引擎可加载
        try:
            checks.append(("DialecticalMLEngine 导入", True, ""))
        except Exception as e:
            checks.append(("DialecticalMLEngine 导入", False, str(e)))

        # 3. 验证八卦特征引擎可加载
        try:
            checks.append(("BaguaFeatureEngine 导入", True, ""))
        except Exception as e:
            checks.append(("BaguaFeatureEngine 导入", False, str(e)))

        # 4. 验证增量学习器可加载
        try:
            checks.append(("IncrementalLearner 导入", True, ""))
        except Exception as e:
            checks.append(("IncrementalLearner 导入", False, str(e)))

        # 5. 验证关键依赖库 (lightgbm / pandas / numpy)
        try:
            import lightgbm  # noqa: F401

            checks.append(("lightgbm 依赖", True, f"v{lightgbm.__version__}"))
        except Exception as e:
            checks.append(("lightgbm 依赖", False, str(e)))

        # 汇总
        failed = [c for c in checks if not c[1]]
        if failed:
            reason = "; ".join(f"{name}失败: {msg}" for name, _, msg in failed)
            return (False, reason)

        passed_summary = ", ".join(name for name, _, _ in checks)
        self._log(f"[BCRM2.0] 健康检查项: {passed_summary}", "INFO")
        return (True, "all checks passed")

    def _on_retrain_complete(self, result: dict):
        """重训完成回调"""
        self._log(
            f"[学习调度] 重训完成 | case={result.get('case_count')} "
            f"两仪更新={result.get('liangyi_updated')} "
            f"QMM更新={result.get('qmm_updated')} "
            f"第{result.get('retrain_count')}次"
        )

    def _check_date_rollover(self):
        """检查是否跨天，重置每日风控"""
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self.last_date:
            # F2修正：跨天时输出前一天的每日聚合摘要到监控
            self._emit_daily_summary(self.last_date)
            self._log(f"[风控] 新的一天 {today}，重置每日风控统计")
            self.risk_manager.reset_daily()
            self.last_date = today

    def _emit_daily_summary(self, date_str: str):
        """F2修正：输出每日聚合绩效摘要到监控文件。

        将 PerformanceTracker 的日统计 + 整体统计写入
        .workbuddy/memory_l4/stats/daily_summary_{date}.json
        供 yijing_monitor / 飞书推送消费。
        """
        if not date_str:
            return
        try:
            today_stats = self.perf_tracker.get_today_stats()
            overall = self.perf_tracker.get_overall_stats()

            summary = {
                "date": date_str,
                "generated_at": datetime.now().isoformat(),
                "daily": {
                    "total_trades": today_stats.get("total_trades", 0),
                    "win_trades": today_stats.get("win_trades", 0),
                    "loss_trades": today_stats.get("loss_trades", 0),
                    "total_pnl": today_stats.get("total_pnl", 0),
                    "win_rate": today_stats.get("win_rate", 0),
                    "max_drawdown": today_stats.get("max_drawdown", 0),
                    "consecutive_losses": today_stats.get("current_consecutive_losses", 0),
                },
                "overall": {
                    "total_trades": overall.get("total_trades", 0),
                    "win_rate": overall.get("win_rate", 0),
                    "total_pnl": overall.get("total_pnl", 0),
                    "profit_factor": overall.get("profit_factor", 0),
                    "max_drawdown": overall.get("max_drawdown", 0),
                    "current_equity": overall.get("current_equity", 0),
                    "sharpe_ratio": overall.get("sharpe_ratio", 0),
                    "trading_days": overall.get("trading_days", 0),
                },
            }

            summary_file = self.perf_tracker.stats_dir / f"daily_summary_{date_str}.json"
            summary_file.write_text(
                json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            self._log(
                f"[每日摘要] {date_str} 已落盘: {summary_file.name} | "
                f"日交易{summary['daily']['total_trades']}笔 盈亏{summary['daily']['total_pnl']:.2f}U "
                f"整体夏普{summary['overall']['sharpe_ratio']:.2f}"
            )
        except Exception as e:
            self._log(f"[每日摘要] 生成失败: {e}", "WARN")

    def _fetch_and_infer(self, coin: str) -> dict:
        """获取实时行情并执行 BCRM + 八卦双引擎推理"""
        inst_id = f"{coin}-USDT-SWAP"

        kline_data = _load_kline_from_okx(inst_id=inst_id, bar=self.bar, limit=self.kline_limit)
        if not kline_data:
            return {"ok": False, "error": f"获取 {inst_id} K线失败"}

        # BCRM 2.0 推理路径（严格模式：不允许降级到 BCRM 1.0）
        if self.use_bcrm2:
            # v3.0：per-coin 失败重试间隔检查 → 严格模式：间隔内直接跳过，不降级
            fail_ts = self.bcrm2_failed_coins.get(coin)
            if fail_ts is not None and (time.time() - fail_ts) < self.bcrm2_retry_interval_sec:
                remain_min = (self.bcrm2_retry_interval_sec - (time.time() - fail_ts)) / 60
                return {
                    "ok": False,
                    "error": (
                        f"BCRM2.0 失败冷却中(剩余{remain_min:.0f}min)，"
                        f"严格模式：不降级BCRM 1.0，本轮跳过"
                    ),
                }

            # 未失败或已过重试间隔，尝试 BCRM 2.0
            if fail_ts is not None:
                self._log(f"[{coin}] BCRM2.0 失败重试间隔已过，重新尝试", "INFO")
                self.bcrm2_failed_coins.pop(coin, None)
                if coin in self.bcrm2_adapters:
                    del self.bcrm2_adapters[coin]
            try:
                return self._infer_bcrm2(coin, inst_id, kline_data)
            except Exception as e:
                self._log(
                    f"[{coin}] BCRM2.0 运行异常: {e} | "
                    f"严格模式：不降级BCRM 1.0，本轮跳过",
                    "ERROR",
                )
                try:
                    notify_model_error(
                        f"BCRM2.0 运行异常（严格模式：跳过，不降级BCRM 1.0）: {type(e).__name__}: {e}",
                        symbol=coin,
                    )
                except Exception as alert_err:
                    self._log(f"[{coin}] 飞书告警发送失败: {alert_err}", "WARN")
                self.bcrm2_failed_coins[coin] = time.time()
                # ⚠️ 严格模式：直接返回失败，绝不落到 BCRM 1.0
                return {"ok": False, "error": f"BCRM2.0 运行异常({type(e).__name__}: {e})，严格模式禁用BCRM 1.0降级"}

        # ================================================================
        # ⛔ BCRM 1.0 fallback 路径 — 严格模式下永久不可达
        # （当 use_bcrm2=True 时，上面的分支已经全部 return；
        #  若未来强制 use_bcrm2=False，则此处代码会触发保护告警）
        # ================================================================
        self._log(
            f"[{coin}] 尝试进入BCRM 1.0路径，已被严格模式阻断！"
            f" | 请确认 use_bcrm2=True 且 BCRM 2.0 可用",
            "ERROR",
        )
        try:
            notify_system_error(
                "BCRM 1.0 fallback 路径被严格模式阻断，请排查 BCRM 2.0 可用性",
                component="BCRM严格模式保护",
            )
        except Exception:
            pass
        return {"ok": False, "error": "BCRM 1.0 fallback 已被严格模式阻断，只允许BCRM 2.0"}

        # —— 以下为原始 BCRM 1.0 代码，保留但永不执行 ——
        snapshot = _kline_to_snapshot(kline_data, idx=0)
        if not snapshot:
            return {"ok": False, "error": "构造 snapshot 失败"}
        snapshot["symbol"] = inst_id

        contradictions_raw = _build_contradiction_list(snapshot)
        contradictions_raw.extend(_build_research_contradictions(snapshot))
        contradictions = _contradictions_to_bcrm_format(contradictions_raw, snapshot)

        closes_window = [kline_data[j]["c"] for j in range(min(60, len(kline_data)))]
        volumes_window = [kline_data[j].get("v", 0) for j in range(min(60, len(kline_data)))]
        ranging_info = _detect_ranging_market(snapshot, closes_window)
        snapshot["is_ranging"] = ranging_info.get("is_ranging", False)
        snapshot["ranging_confidence"] = ranging_info.get("confidence", 0)

        # P0修复: 每币种推理前重置 ForceEngine 速度状态，防止跨币种污染
        if hasattr(self.bcrm_engine, "force_engine") and hasattr(
            self.bcrm_engine.force_engine, "reset_velocity"
        ):
            self.bcrm_engine.force_engine.reset_velocity()

        qmm_output = {"uncertainty": 0.3}
        try:
            bcrm_result = self.bcrm_engine.infer(
                market_snapshot=snapshot,
                contradiction_list=contradictions,
                qmm_output=qmm_output,
            )
        except Exception as e:
            if self.guardian:
                self.guardian.record_error(e, context=f"bcrm_infer:{coin}")
            return {"ok": False, "error": f"BCRM 推理失败: {e}"}

        direction = bcrm_result.next_state.direction
        confidence = bcrm_result.next_state.confidence
        hex_cn = bcrm_result.hexagram.hexagram_name_cn or bcrm_result.hexagram.hexagram_name
        fail_closed = bcrm_result.is_fail_closed()

        bagua_result = None
        try:
            bagua_result = self.bagua_engine.infer(
                snapshot=snapshot,
                closes=closes_window,
                volumes=volumes_window,
            )
        except Exception:
            pass

        bagua_dir = bagua_result.primary_direction if bagua_result else "neutral"
        bagua_conf = bagua_result.primary_confidence if bagua_result else 0

        bcrm_dir_num = 1 if direction == "UP" else (-1 if direction == "DOWN" else 0)
        bagua_dir_num = 1 if bagua_dir == "long" else (-1 if bagua_dir == "short" else 0)

        if bcrm_dir_num != 0 and bagua_dir_num != 0:
            if bcrm_dir_num == bagua_dir_num:
                confidence = min(0.95, confidence * 0.5 + bagua_conf * 0.5 + 0.1)
            else:
                confidence = confidence * 0.4
                if bagua_conf > confidence + 0.2:
                    direction = "UP" if bagua_dir == "long" else "DOWN"
                    confidence = bagua_conf * 0.7
        elif bcrm_dir_num == 0 and bagua_dir_num != 0:
            direction = "UP" if bagua_dir == "long" else "DOWN"
            confidence = bagua_conf * 0.6
        elif bagua_dir_num == 0 and bcrm_dir_num != 0:
            confidence = confidence * 0.7

        if bagua_result and bagua_result.hexagram_name_cn:
            hex_cn = bagua_result.hexagram_name_cn

        # 卦象名与方向一致性检查 (修复: 2026-07-13)
        hex_consistent = True
        if hex_cn:
            gua_direction = self._get_hexagram_direction(hex_cn)
            actual_direction = "long" if direction == "UP" else "short"
            if gua_direction and gua_direction != "neutral" and gua_direction != actual_direction:
                hex_consistent = False
                # 尝试使用变卦或互卦作为替代卦象
                if bcrm_result and hasattr(bcrm_result, "hexagram"):
                    bcrm_hex = bcrm_result.hexagram
                    # 使用变卦替代
                    if hasattr(bcrm_hex, "changed_hexagram_cn") and bcrm_hex.changed_hexagram_cn:
                        hex_cn = bcrm_hex.changed_hexagram_cn
                        self._log(f"[{coin}] 卦象校准 | {hex_cn}(变卦) 替代原卦象", "INFO")
                    else:
                        self._log(
                            f"[{coin}] 卦象警告 | 卦象{hex_cn}({gua_direction})与决策方向({actual_direction})不一致",
                            "WARN",
                        )

        sl_px, tp_px, reduce_ratio = 0, 0, 0
        if bcrm_result.strategy_branches:
            b1 = next((b for b in bcrm_result.strategy_branches if b.branch_id == "B1"), None)
            if b1:
                sl_px = b1.stop_loss_px
                tp_px = b1.take_profit_px
                reduce_ratio = b1.reduce_ratio

        # 经典指标离场回退：BCRM 未产生止盈止损时，用 ATR 计算止损止盈
        # 2026-08-06 上调：ATR 倍数 2.0→3.0 / 4.0→6.0（过近止损导致频繁扫损，高置信度仓位建议长期持有）
        if sl_px == 0 or tp_px == 0:
            price = snapshot.get("price", 0)
            volatility = snapshot.get("volatility", 0.03)
            if price > 0:
                # ATR 近似：用波动率 × 价格作为 ATR 估计
                atr = max(price * volatility, price * 0.005)  # 至少 0.5%
                # P3: 波动率自适应 ATR 倍率（连续插值，替代固定 3.0/6.0）
                # 低波→紧止损(2.0×ATR)，高波→宽止损(3.5+×ATR)，盈亏比保持 2:1
                atr_mult_sl, atr_mult_tp = RiskManager.volatility_adaptive_atr_mult(volatility)
                # 高置信度进一步放宽：置信度 ≥0.9 时 SL/TP 再 ×1.3
                if confidence >= 0.9:
                    atr_mult_sl *= 1.3
                    atr_mult_tp *= 1.3
                if direction == "UP":
                    fallback_sl = round(price - atr * atr_mult_sl, 4)
                    fallback_tp = round(price + atr * atr_mult_tp, 4)
                else:
                    fallback_sl = round(price + atr * atr_mult_sl, 4)
                    fallback_tp = round(price - atr * atr_mult_tp, 4)
                if sl_px == 0:
                    sl_px = fallback_sl
                if tp_px == 0:
                    tp_px = fallback_tp
                self._log(
                    f"[{coin}] 经典指标离场(P3自适应) | ATR={atr:.2f} vol={volatility:.4f} "
                    f"(conf={confidence:.2f}→SL={atr_mult_sl:.1f}×ATR TP={atr_mult_tp:.1f}×ATR) | "
                    f"SL={sl_px} TP={tp_px} (盈亏比={atr_mult_tp/atr_mult_sl:.1f}:1)",
                    "INFO",
                )

        liangyi_dict = {}
        if hasattr(bcrm_result, "liangyi_state") and bcrm_result.liangyi_state:
            if hasattr(bcrm_result.liangyi_state, "to_dict"):
                liangyi_dict = bcrm_result.liangyi_state.to_dict()
            elif isinstance(bcrm_result.liangyi_state, dict):
                liangyi_dict = bcrm_result.liangyi_state

        scale_dict = {}
        if hasattr(bcrm_result, "scale_params") and bcrm_result.scale_params:
            if hasattr(bcrm_result.scale_params, "to_dict"):
                scale_dict = bcrm_result.scale_params.to_dict()
            elif isinstance(bcrm_result.scale_params, dict):
                scale_dict = bcrm_result.scale_params

        # P0修复：注入 regime 到 snapshot（卦象+is_ranging+closes推断）
        # P2-06: 当 ENABLE_REGIME_AND_MACRO_S5 时，拉取全局宏观特征并注入；
        #        False 时完全不传参，_infer_regime 走旧路径，字节等价
        _p2_macro_feats = None
        if self.ENABLE_REGIME_AND_MACRO_S5:
            try:
                _p2_macro_feats = self._fetch_global_macro_features_once()
            except Exception:
                _p2_macro_feats = None
        snapshot["regime"] = self._infer_regime(
            hex_cn, snapshot.get("is_ranging", False), direction, closes_window,
            macro_features=_p2_macro_feats,
            enable_macro_correction=self.ENABLE_REGIME_AND_MACRO_S5,
        )

        return {
            "ok": True,
            "coin": coin,
            "inst_id": inst_id,
            "price": snapshot.get("price", 0),
            "direction": direction,
            "confidence": round(confidence, 4),
            "hexagram": hex_cn,
            "hex_consistent": hex_consistent,  # 卦象方向一致性标志
            "fail_closed": fail_closed,
            "is_ranging": snapshot.get("is_ranging", False),
            "bagua_direction": bagua_dir,
            "bagua_confidence": round(bagua_conf, 4),
            "stop_loss_px": sl_px,
            "take_profit_px": tp_px,
            "reduce_ratio": reduce_ratio,
            "liangyi_state": liangyi_dict,
            "scale_params": scale_dict,
            "snapshot": snapshot,
            "contradictions": contradictions,
            "volatility": snapshot.get("volatility", 0.03),
            "kline_data": kline_data,
        }

    def _kline_to_dataframe(self, kline_data: list) -> "pd.DataFrame":
        """将 OKX K线数据转换为 pandas DataFrame"""
        import pandas as pd

        data = []
        for c in kline_data:
            data.append(
                {
                    "timestamp": c.get("ts", 0),
                    "open": float(c.get("o", 0)),
                    "high": float(c.get("h", 0)),
                    "low": float(c.get("l", 0)),
                    "close": float(c.get("c", 0)),
                    "volume": float(c.get("v", 0)),
                }
            )
        df = pd.DataFrame(data)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)
        df.sort_index(inplace=True)
        return df

    def _infer_bcrm2(self, coin: str, inst_id: str, kline_data: list) -> dict:
        """使用 BCRM 2.0 (辩证ML) 执行推理"""

        if coin not in self.bcrm2_adapters:
            # BTC 启用 v4 前向选择验证有效的 3 个宏观特征
            # (fgi_zscore + fgi_extreme_fear + hash_rate_trend，BTC验证得分 +23.8%)
            # 其他币种保持默认（不传 macro_config = 全部启用默认行为）
            btc_macro_config = None
            if coin.upper() == "BTC":
                btc_macro_config = {
                    "macro_feat_fgi_zscore": True,
                    "macro_feat_fgi_extreme_fear": True,
                    "macro_feat_hash_rate_trend": True,
                    # 其余 21 个特征显式关闭
                    "macro_feat_fgi_trend_7d": False,
                    "macro_feat_fgi_extreme_greed": False,
                    "macro_feat_fgi_divergence": False,
                    "macro_feat_funding_rate_zscore": False,
                    "macro_feat_funding_extreme_positive": False,
                    "macro_feat_funding_extreme_negative": False,
                    "macro_feat_oi_change_rate": False,
                    "macro_feat_funding_divergence": False,
                    "macro_feat_stablecoin_growth": False,
                    "macro_feat_liquidity_expanding": False,
                    "macro_feat_liquidity_contracting": False,
                    "macro_feat_tvl_change_7d": False,
                    "macro_feat_miner_accumulation": False,
                    "macro_feat_miners_revenue_zscore": False,
                    "macro_feat_smart_money_direction": False,
                    "macro_feat_smart_money_divergence": False,
                    "macro_feat_social_hype_zscore": False,
                    "macro_feat_hype_extreme": False,
                    "macro_feat_market_cap_rank": False,
                    "macro_feat_ath_drop_pct": False,
                    "macro_feat_undervalued": False,
                }
            self.bcrm2_adapters[coin] = BCRM2Adapter(
                symbol=coin,
                timeframe=self.bar,
                tp_atr=3.0,
                sl_atr=2.5,  # P1-2: 原1.5→2.5，与外层SL=3.0×ATR口径一致（2.5~3 ATR区间）
                max_hold_bars=60,
                macro_config=btc_macro_config,
            )

        adapter = self.bcrm2_adapters[coin]

        try:
            df = self._kline_to_dataframe(kline_data)
        except Exception as e:
            return {"ok": False, "error": f"K线转换失败: {e}"}

        # 首次推理时自动训练
        if adapter.engine is None:
            # 严格模式：K线数据不足则直接跳过该币种，绝不回退 BCRM 1.0
            # max_hold_bars=60，需要至少 100+60=160 根K线才能产生100个有效样本
            min_klines_needed = self.bcrm2_min_samples + adapter.max_hold_bars
            if len(df) < min_klines_needed:
                self._log(
                    f"[{coin}] BCRM2.0 跳过: K线数据不足({len(df)}<{min_klines_needed}根) "
                    f"| 严格模式：不降级BCRM 1.0，本轮跳过",
                    "WARN",
                )
                self.bcrm2_failed_coins[coin] = time.time()
                return {"ok": False, "error": f"BCRM2.0 K线数据不足({len(df)}<{min_klines_needed})，严格模式禁用BCRM 1.0降级"}

            self._log(f"[{coin}] BCRM2.0 首次推理，开始训练模型...", "INFO")
            train_result = adapter.train(df)
            if train_result is not True:
                # 严格模式：区分原因但统一选择"跳过"，绝不回退 BCRM 1.0
                is_data_insufficient = train_result == "insufficient_data"
                self.bcrm2_failed_coins[coin] = time.time()

                if is_data_insufficient:
                    self._log(
                        f"[{coin}] BCRM2.0 样本不足，严格模式跳过（不降级BCRM 1.0，24h后重试）",
                        "WARN",
                    )
                else:
                    self._log(
                        f"[{coin}] BCRM2.0 训练失败(异常)，严格模式跳过（不降级BCRM 1.0）",
                        "ERROR",
                    )
                    try:
                        notify_model_error(
                            "BCRM2.0 训练异常（严格模式：跳过，不降级BCRM 1.0）",
                            symbol=coin,
                        )
                    except Exception as e:
                        self._log(f"[{coin}] 飞书告警发送失败: {e}", "WARN")
                return {"ok": False, "error": f"BCRM2.0 训练失败({train_result})，严格模式禁用BCRM 1.0降级"}

        # 执行推理
        bcrm_result = adapter.infer(df, idx=-1)

        if not bcrm_result.get("ok"):
            # 措施2：推理失败时立即发送飞书告警（fail_closed 也会走这里）
            fail_reason = bcrm_result.get("fail_closed_reason", "未知")
            self._log(f"[{coin}] BCRM2.0 推理失败: {fail_reason}", "WARN")
            try:
                notify_model_error(
                    f"BCRM2.0 推理失败 (fail_closed): {fail_reason}",
                    symbol=coin,
                )
            except Exception as e:
                self._log(f"[{coin}] 飞书告警发送失败: {e}", "WARN")
            return {"ok": False, "error": "BCRM2.0 推理失败"}

        direction = bcrm_result["next_state"]["direction"]
        confidence = bcrm_result["next_state"]["confidence"]
        hex_cn = bcrm_result["hexagram"]["hexagram_name_cn"]
        fail_closed = bcrm_result["is_fail_closed"]()

        # 计算波动率（用于止盈止损）— 必须在 CBR 增强前完成，供 CBR 使用
        closes = df["close"].values
        atr = 0
        if len(df) >= 14:
            highs = df["high"].values
            lows = df["low"].values
            tr = np.maximum(
                highs[1:] - lows[1:],
                np.maximum(np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1])),
            )
            atr = np.mean(tr[-14:])
        volatility = atr / closes[-1] if closes[-1] > 0 else 0.03

        # 检测震荡市
        closes_window = list(closes[-60:])
        snapshot_simple = {"price": closes[-1], "volatility": volatility}
        ranging_info = _detect_ranging_market(snapshot_simple, closes_window)
        is_ranging = ranging_info.get("is_ranging", False)

        price = closes[-1]

        # CBR 案例检索增强（2026-07-21 修复：price/volatility 必须先计算好再调用）
        if self.cbr_bridge and not fail_closed:
            try:
                bcrm_output = {
                    "inst_id": inst_id,
                    "direction": (
                        "long"
                        if direction == "UP"
                        else ("short" if direction == "DOWN" else "flat")
                    ),
                    "confidence": confidence,
                    "current_price": price,
                    "regime": bcrm_result.get("hexagram", {})
                    .get("liangyi_state", {})
                    .get("macro_phase", ""),
                    "volatility": volatility,
                    "hexagram": hex_cn,
                }
                enhanced = self.cbr_bridge.enhance_bcrm_signal(bcrm_output)
                # 应用 CBR 增强的参数
                if enhanced.get("cbr_fusion_method") != "bcrm_only":
                    confidence = enhanced.get("confidence", confidence)
                    self._log(
                        f"[{coin}] CBR 增强 | 历史胜率={enhanced.get('cbr_historical_win_rate', 0):.1%} "
                        f"Top-1相似度={enhanced.get('cbr_similarity_top1', 0):.2f} "
                        f"融合模式={enhanced.get('cbr_fusion_method')} "
                        f"风险提示={enhanced.get('cbr_risk_notes', [])}",
                        "INFO",
                    )
            except Exception as e:
                self._log(f"[{coin}] CBR 增强失败: {e}", "WARN")

        # 计算 ATR 止盈止损
        # P1-2: 统一ATR止损倍率为2.5~3.0区间（adapter=2.5, 主SL=3.0, ExitConfig=2.5）
        # 高置信度(≥0.9)再×1.3放宽至3.9×ATR，盈亏比保持~2:1
        sl_px, tp_px = 0, 0
        if atr > 0:
            sl_mult = 3.0  # 主止损线 3.0×ATR
            tp_mult = 6.0  # 止盈 6.0×ATR
            if confidence >= 0.9:
                sl_mult *= 1.3
                tp_mult *= 1.3
            if direction == "UP":
                sl_px = round(price - atr * sl_mult, 4)
                tp_px = round(price + atr * tp_mult, 4)
            elif direction == "DOWN":
                sl_px = round(price + atr * sl_mult, 4)
                tp_px = round(price - atr * tp_mult, 4)

        self._log(
            f"[{coin}] BCRM2.0 推理 | 方向={direction} 置信度={confidence:.2f} "
            f"卦象={hex_cn} fail_closed={fail_closed}",
            "INFO",
        )

        # ── 前置层注入：从 MorphCyclePredictor 获取 level_smooth/trend_smooth/consensus ──
        # BCRM 2.0 推理结果不含前置层 6 层流水线输出，需主动调用预测器获取 L/T/C
        # 使 ParameterMapper / ShadowLogger / α blend 能正确读取 reactive 参数
        _morph_L = 0.0
        _morph_T = 0.0
        _morph_C = 0.0
        _morph_src = "none"
        _predictor = getattr(self, "_morph_predictor", None)
        if _predictor is not None:
            try:
                _full_sym = inst_id or f"{coin.upper()}USDT"
                _cy = _predictor.predict_with_fallback(_full_sym, hist_days=60, forecast_days=5)
                if _cy.get("ok"):
                    _pa = _cy.get("params") or {}
                    _L_val = _pa.get("current_L")
                    _T_val = _pa.get("current_T")
                    if _L_val is not None and _T_val is not None:
                        _morph_L = float(_L_val)
                        _morph_T = float(_T_val)
                        _morph_C = 0.5  # 保守中性共识
                        _morph_src = "predictor"
            except Exception as _e:
                self._log(f"[{coin}] 前置层 L/T/C 注入失败: {_e}", "DEBUG")

        return {
            "ok": True,
            "coin": coin,
            "inst_id": inst_id,
            "price": price,
            "direction": direction,
            "confidence": round(confidence, 4),
            "hexagram": hex_cn,
            "hex_consistent": True,
            "fail_closed": fail_closed,
            "is_ranging": is_ranging,
            "bagua_direction": "neutral",
            "bagua_confidence": 0,
            "stop_loss_px": sl_px,
            "take_profit_px": tp_px,
            "reduce_ratio": 0,
            "liangyi_state": {},
            "scale_params": {},
            "snapshot": {
                "price": price,
                "volatility": volatility,
                "is_ranging": is_ranging,
                # ── 前置层 6 层流水线输出（L/T/C 双维坐标）──
                "level_smooth": _morph_L,
                "trend_smooth": _morph_T,
                "consensus": _morph_C,
                "morph_src": _morph_src,
                "regime": self._infer_regime(
                    hex_cn,
                    is_ranging,
                    direction,
                    list(closes[-60:]) if len(closes) >= 60 else list(closes),
                    macro_features=(self._fetch_global_macro_features_once()
                                    if self.ENABLE_REGIME_AND_MACRO_S5 else None),
                    enable_macro_correction=self.ENABLE_REGIME_AND_MACRO_S5,
                ),
            },
            "contradictions": bcrm_result.get("a0_analysis", {}).get("contradictions", []),
            "a0_analysis": bcrm_result.get("a0_analysis"),
            "a0_warnings": bcrm_result.get("a0_warnings", []),
            "triangle_verification": bcrm_result.get("triangle_verification"),
            # v4 风险评分风控参数（五角校验输出）
            "position_factor": bcrm_result.get("position_factor", 1.0),
            "sl_tighten_factor": bcrm_result.get("sl_tighten_factor", 1.0),
            "early_exit_signal": bcrm_result.get("early_exit_signal", False),
            "leverage_factor": bcrm_result.get("leverage_factor", 1.0),
            "tp_adjustment": bcrm_result.get("tp_adjustment", 1.0),
            "risk_score": bcrm_result.get("risk_score", 0.0),
            "risk_level": bcrm_result.get("risk_level", "NORMAL"),
            "volatility": volatility,
            "sl_atr": 1.5,
            "kline_data": kline_data,
        }

    def _get_hexagram_direction(self, hexagram_name: str) -> str:
        """根据卦象名查询卦象方向

        Args:
            hexagram_name: 卦象中文名 (如 "巽为风")

        Returns:
            卦象方向: "long" / "short" / "neutral" / "" (未知)
        """
        # 卦象名到方向的映射 (基于SIXTY_FOUR_GUAS)
        HEX_TO_DIRECTION = {
            "乾为天": "long",
            "坤为地": "short",
            "水雷屯": "neutral",
            "山水蒙": "neutral",
            "水天需": "long",
            "天水讼": "neutral",
            "地水师": "short",
            "水地比": "long",
            "风雷益": "long",
            "雷风恒": "neutral",
            "离为火": "long",
            "泽火革": "neutral",
            "火风鼎": "long",
            "巽为风": "long",
            "兑为泽": "long",
            "艮为山": "neutral",
            "山地剥": "short",
            "地雷复": "long",
            "坎为水": "short",
            "水火既济": "neutral",
            "火水未济": "neutral",
            "地天泰": "long",
            "天地否": "short",
            "天雷无妄": "neutral",
            "山天大畜": "long",
            "山雷颐": "neutral",
            "泽天夬": "long",
            "天风姤": "short",
            "泽地萃": "long",
            "地泽临": "long",
            "风天小畜": "neutral",
            "风地观": "neutral",
            "风火家人": "long",
            "风山渐": "long",
            "风泽中孚": "long",
            "雷天大壮": "long",
            "雷地豫": "long",
            "震为雷": "long",
            "雷水解": "long",
            "雷火丰": "long",
            "雷山小过": "short",
            "雷泽归妹": "short",
            "水风井": "neutral",
            "火天大有": "long",
            "火地晋": "long",
            "火雷噬嗑": "long",
            "火山旅": "short",
            "火泽睽": "short",
            "山水蒙_dup"  # noqa: F601 - intentional duplicate per 易经修复说明: "short",
            "山风蛊": "short",
            "山火贲": "long",
            "山泽损": "short",
            "泽水困": "short",
            "泽山咸": "long",
            "泽风大过": "short",
        }
        return HEX_TO_DIRECTION.get(hexagram_name, "")

    # 64卦名首字 → 八卦元素映射（上卦/下卦提取）
    _HEX_CHAR_TO_GUA = {
        "乾": "qian",
        "天": "qian",
        "坤": "kun",
        "地": "kun",
        "震": "zhen",
        "雷": "zhen",
        "巽": "xun",
        "风": "xun",
        "坎": "kan",
        "水": "kan",
        "离": "li",
        "火": "li",
        "艮": "gen",
        "山": "gen",
        "兑": "dui",
        "泽": "dui",
    }

    # ──────────────────────────────────────────────────────────────
    # P2-02 重构：把原推断逻辑抽为 _infer_regime_base（字节等价原实现）
    #           外层 _infer_regime 加 macro correction 开关包裹
    # ──────────────────────────────────────────────────────────────
    def _infer_regime_base(
        self, hexagram_name: str, is_ranging: bool, direction: str = "", closes: list = None
    ) -> str:
        """[BYTE-EQUIVALENT 原实现] 从卦象名+市场状态推断 regime（8态之一）

        轻量级推断，不依赖 MarketRegimeClassifier 训练。
        """
        from scripts.memory_l4.bcrm2.market_regime import GUA_REGIME_MAP

        if not hexagram_name or hexagram_name == "已存在持仓":
            # 无卦象时用 is_ranging + direction 兜底
            if is_ranging:
                return "RANGE_BOUND"
            if direction == "UP":
                return "TREND_UP_MILD"
            if direction == "DOWN":
                return "VOLATILE_DROP"
            return "CONSOLIDATION"

        # 纯卦格式："X为Y"（如"乾为天"）→ 取首字
        if "为" in hexagram_name:
            first_gua = self._HEX_CHAR_TO_GUA.get(hexagram_name[0], "")
            if first_gua and first_gua in GUA_REGIME_MAP:
                regime = GUA_REGIME_MAP[first_gua]
                # 震荡市降级
                if is_ranging and regime in ("TREND_UP_STRONG", "TREND_UP_MILD", "BREAKOUT"):
                    return "RANGE_BOUND"
                return regime

        # 组合卦：取前两字作为上下卦（如"水山蹇"→上坎下艮）
        # 下卦（第1字）为主，上卦（第2字）为辅
        if len(hexagram_name) >= 2:
            lower_gua = self._HEX_CHAR_TO_GUA.get(hexagram_name[0], "")
            upper_gua = self._HEX_CHAR_TO_GUA.get(hexagram_name[1], "")

            # 优先用下卦（主卦）映射
            if lower_gua and lower_gua in GUA_REGIME_MAP:
                regime = GUA_REGIME_MAP[lower_gua]
                # 震荡市降级：强趋势/突破类 → 震荡
                if is_ranging and regime in (
                    "TREND_UP_STRONG",
                    "TREND_UP_MILD",
                    "BREAKOUT",
                    "FOMO_RALLY",
                ):
                    return "RANGE_BOUND"
                return regime

            # 下卦未命中，尝试上卦
            if upper_gua and upper_gua in GUA_REGIME_MAP:
                return GUA_REGIME_MAP[upper_gua]

        # 价格趋势兜底
        if closes and len(closes) >= 20:
            if closes[-1] > closes[-20]:
                return "TREND_UP_MILD" if not is_ranging else "RANGE_BOUND"
            elif closes[-1] < closes[-20]:
                return "VOLATILE_DROP" if not is_ranging else "RANGE_BOUND"

        return "CONSOLIDATION"

    def _infer_regime(
        self,
        hexagram_name: str,
        is_ranging: bool,
        direction: str = "",
        closes: list = None,
        macro_features: dict = None,
        enable_macro_correction: bool = True,
    ) -> str:
        """[外层] 从卦象名 + 市场状态 + macro(爆仓/期权) 推断 8 态

        Args:
            hexagram_name:   卦象名（如 乾为天 / 水山蹇 / 已存在持仓）
            is_ranging:      是否震荡市
            direction:       价格方向（UP/DOWN/空）
            closes:          收盘价序列（最长 20 根以上，用于无卦兜底）
            macro_features:  collect_global() 顶层字段字典，缺省为 {}
            enable_macro_correction: S5 开关，False 时字节等价旧路径
        """
        # ① 先跑基础推断（100% 字节等价旧实现，开关关时直接返回）
        base = self._infer_regime_base(hexagram_name, is_ranging, direction, closes)

        if not enable_macro_correction:
            return base
        if not macro_features:
            return base

        # ② 爆仓/期权 macro overlay 校正
        from scripts.memory_l4.bcrm2.market_regime import apply_macro_regime_correction
        try:
            return apply_macro_regime_correction(base, macro_features)
        except Exception:
            # graceful：校正器任何异常 → 回退基础推断（不影响交易主链路）
            return base

    # ──────────────────────────────────────────────────────────────
    # P2-03：FreeMarketFeed 集成 + 5 分钟缓存 + graceful 失败
    # ──────────────────────────────────────────────────────────────
    def _get_macro_feed_instance(self):
        """获取 FreeMarketFeed 单例（懒加载，仅首次调用时实例化 + 注入 sys.path）

        单独抽出来是为了 P2-03 T4 monkeypatch mock 测试覆盖异常分支。
        """
        import sys as _sys, os as _os
        if not hasattr(self, "_macro_feed_singleton") or self._macro_feed_singleton is None:
            # 注入 1-ARCHITECTURE 包路径到 sys.path（项目跨 package 引用）
            _proj_root = _os.path.abspath(_os.path.join(
                _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                "..", "..", "..", "1-ARCHITECTURE"
            ))
            if _proj_root not in _sys.path:
                _sys.path.insert(0, _proj_root)
            from dreamos.capabilities.trading.free_market_feed import FreeMarketFeed
            self._macro_feed_singleton = FreeMarketFeed()
        return self._macro_feed_singleton

    def _fetch_global_macro_features_once(
        self,
        cache_ttl_sec: int = 300,
        _test_skip_network: bool = False,
    ) -> dict:
        """形态预测器专用：从 FreeMarketFeed.collect_global 取顶层 liq_/crypto_vix_/btc_option_* 字段

        Cache：5 分钟 TTL（形态慢变量，过高频调用会被 OKX/Binance rate-limit）
        Graceful：任何异常 → 返回空 {}，不冒泡阻塞主链路
        """
        import time as _time
        # lazy 初始化 cache 结构（不写 __init__ 防旧实例化路径崩）
        if not hasattr(self, "_macro_feature_cache") or self._macro_feature_cache is None:
            self._macro_feature_cache = {"ts": 0, "data": {}}

        now = _time.time()
        # TTL 命中缓存直接返回
        if (now - self._macro_feature_cache.get("ts", 0)) < cache_ttl_sec:
            return dict(self._macro_feature_cache["data"])  # 浅拷贝避免外部污染

        if _test_skip_network:
            # TTL 失效 + 跳过网络调用（测试模式）→ 返回空 dict，不写入 cache
            return {}

        # 真实调用 FMF
        try:
            feed = self._get_macro_feed_instance()
            global_snap = feed.collect_global()
            # 只取形态预测器消费的顶层字段（约 10 个），避免整包序列化开销
            whitelist = [
                "liq_panic_score_0_to_1", "liq_panic_level", "liq_regime_hint",
                "liq_long_short_ratio", "liq_cascade_hours", "liq_total_24h_usd",
                "crypto_vix_proxy_pct", "options_regime_hint",
                "btc_option_atm_iv_pct", "btc_option_pc_skew_25d_pct",
                "btc_option_iv_level", "btc_option_skew_sentiment",
                "eth_option_atm_iv_pct", "eth_option_pc_skew_25d_pct",
                "eth_option_iv_level", "eth_option_skew_sentiment",
            ]
            filtered = {k: global_snap.get(k) for k in whitelist if k in global_snap}
        except Exception:
            # 任何错误（网络/路径/实例化/超时）→ 空 dict，不写 cache（下次重试）
            return {}

        # 写 cache，ts 记录成功调用时刻
        self._macro_feature_cache = {"ts": now, "data": filtered}
        return dict(filtered)

    # ──────────────────────────────────────────────────────────────
    # P2-04：REGIME_MULTIPLIERS（8 态 × 4 维参数乘数）+ 查询接口
    # ──────────────────────────────────────────────────────────────
    REGIME_MULTIPLIERS: dict = {
        # Spec §5.1 表：强趋势 → 加仓、放止盈、松止损、宽门槛
        "TREND_UP_STRONG": {
            "position_mult":  1.20,
            "tp_mult":        1.30,
            "sl_mult":        1.15,
            "threshold_mult": 0.80,
        },
        "TREND_UP_MILD": {
            "position_mult":  1.05,
            "tp_mult":        1.10,
            "sl_mult":        1.05,
            "threshold_mult": 0.92,
        },
        "BREAKOUT": {
            "position_mult":  1.10,
            "tp_mult":        1.20,
            "sl_mult":        1.00,
            "threshold_mult": 0.85,
        },
        # 震荡类 → 减仓、紧止盈、宽止损（震荡别追、别打止损）
        "RANGE_BOUND": {
            "position_mult":  0.80,
            "tp_mult":        0.85,
            "sl_mult":        1.20,
            "threshold_mult": 1.15,
        },
        "CONSOLIDATION": {
            "position_mult":  0.70,
            "tp_mult":        0.80,
            "sl_mult":        1.25,
            "threshold_mult": 1.20,
        },
        # 风险/反转类 → 极度保守
        "VOLATILE_DROP": {
            "position_mult":  0.35,
            "tp_mult":        0.75,
            "sl_mult":        0.65,
            "threshold_mult": 1.30,
        },
        "FOMO_RALLY": {
            "position_mult":  0.85,
            "tp_mult":        0.60,
            "sl_mult":        0.70,
            "threshold_mult": 1.15,
        },
        "REVERSAL": {
            "position_mult":  0.50,
            "tp_mult":        0.75,
            "sl_mult":        0.80,
            "threshold_mult": 1.25,
        },
    }

    def _get_regime_pred_multipliers(
        self,
        regime: str,
        enable_regime_pred: bool = True,
    ) -> dict:
        """查 8 态乘数表；开关关 / regime 非法 → 全 1.0

        返回格式: {position_mult, tp_mult, sl_mult, threshold_mult}

        注意：弹簧力场分类器（5 态：TREND_BULL/TREND_BEAR/...）与形态预测
        S5 REGIME_MULTIPLIERS（8 态：TREND_UP_STRONG/BREAKOUT/...）是两套独立标签
        体系；这里通过 FMA5→S5 映射桥兼容，保证「S5 形态乘数永远=1.0」的问题不会出现。
        """
        # 开关关 → 字节等价旧路径（全 1.0）
        if not enable_regime_pred:
            return {"position_mult": 1.0, "tp_mult": 1.0,
                    "sl_mult": 1.0, "threshold_mult": 1.0}

        # ── FMA5→S5 标签桥（5 态 → 8 态，保守映射）─────────────────
        #   映射原则：强度对齐 + 风险偏好偏保守（宁可低估牛市也不错误高估）
        _FMA_TO_S5 = {
            "TREND_BULL":        "TREND_UP_MILD",    # 普通多头趋势
            "STRONG_TREND_BULL": "TREND_UP_STRONG",  # 若上游未来新增强牛标签
            "STRONG_TREND_BEAR": "VOLATILE_DROP",    # 强空头趋势 → 视为暴跌态（保守）
            "TREND_BEAR":        "REVERSAL",         # 弱空头 → 反转态
            "MEAN_REVERTING":    "CONSOLIDATION",    # 均值回归 → 整理（偏保守）
            "RANGING":           "RANGE_BOUND",      # 震荡 → 区间震荡
        }
        _resolved = regime
        if isinstance(regime, str) and (regime not in self.REGIME_MULTIPLIERS):
            _mapped = _FMA_TO_S5.get(regime)
            if _mapped and _mapped in self.REGIME_MULTIPLIERS:
                _resolved = _mapped

        # regime 未命中表 → 全 1.0 fallback，不抛异常
        if not isinstance(_resolved, str) or (_resolved not in self.REGIME_MULTIPLIERS):
            return {"position_mult": 1.0, "tp_mult": 1.0,
                    "sl_mult": 1.0, "threshold_mult": 1.0}

        # 返回一份副本，避免外部改动污染 class 常量
        return dict(self.REGIME_MULTIPLIERS[_resolved])

    # ══════════════════════════════════════════════════════════════
    # v5.0 离场防频繁：离场确认状态机 + 持仓保护期门禁
    # ══════════════════════════════════════════════════════════════

    def _is_position_protected(self, position_age_sec: float) -> bool:
        """判断持仓是否在保护期内（开仓后前N小时）

        保护期内：仅P0硬止损/静态SL/TP生效；易经动态SL/TP调整屏蔽；
        信号反转/P3提前退出需要更高门槛 + 离场确认。
        """
        return position_age_sec < (self.POSITION_PROTECTION_HOURS * 3600.0)

    def _exit_confirm(self, coin: str, action_type: str) -> Tuple[bool, int]:
        """离场动作2次确认状态机。

        Args:
            coin: 币种
            action_type: 动作类型（signal_reverse / yijing_force_close / p3_early_exit）

        Returns:
            (confirmed: bool, current_count: int)
                confirmed: 是否达到确认次数（可执行离场）
                current_count: 当前累计确认次数
        """
        now = time.time()
        key = f"{coin}:{action_type}"

        state = self._exit_confirm_state.get(key)
        if state is None:
            # 第一次触发：记录，未确认
            self._exit_confirm_state[key] = {
                "confirm_count": 1,
                "first_ts": now,
            }
            return False, 1

        # 检查是否在确认窗口内
        elapsed = now - state["first_ts"]
        if elapsed > self.EXIT_CONFIRM_WINDOW_SEC:
            # 窗口超时：重置为第一次
            self._exit_confirm_state[key] = {
                "confirm_count": 1,
                "first_ts": now,
            }
            return False, 1

        # 窗口内：累计+1
        state["confirm_count"] += 1
        self._exit_confirm_state[key] = state
        confirmed = state["confirm_count"] >= self.EXIT_CONFIRM_REQUIRED
        return confirmed, state["confirm_count"]

    def _clear_exit_confirm(self, coin: str, action_type: str = ""):
        """清除某币种的离场确认状态。

        离场执行后、或条件不再满足时调用，避免状态污染。
        """
        if action_type:
            key = f"{coin}:{action_type}"
            self._exit_confirm_state.pop(key, None)
        else:
            # 清除该币种所有动作类型
            prefix = f"{coin}:"
            keys = [k for k in self._exit_confirm_state if k.startswith(prefix)]
            for k in keys:
                self._exit_confirm_state.pop(k, None)

    def _check_positions(self, coin: str) -> dict:
        """检查指定币种的持仓。
        Bug修复：返回 open_time（开仓时间戳,秒），供离场系统计算持仓年龄。
        优先从本地 PositionTracker.entry_time 读取（更准确），缺失时回退 OKX ctime。
        OKX API 限流时回退 position_tracker，确保 EV/S3 离场管理不被跳过。
        """
        inst_id = f"{coin}-USDT-SWAP"
        pos_result = self.okx_client.get_positions(inst_id)
        if not pos_result.get("ok"):
            # OKX API 失败（限流等）→ 回退 position_tracker 本地记录
            tracker_rec = self.position_tracker.get_open_position(inst_id)
            if tracker_rec:
                open_time_sec = 0.0
                if tracker_rec.entry_time:
                    try:
                        if tracker_rec.entry_time.endswith("Z"):
                            ts = tracker_rec.entry_time.replace("Z", "+00:00")
                        else:
                            ts = tracker_rec.entry_time
                        from datetime import datetime as _dt
                        open_time_sec = _dt.fromisoformat(ts).timestamp()
                    except Exception:
                        open_time_sec = 0.0
                return {
                    "has_position": True,
                    "pos_side": tracker_rec.direction,
                    "pos_size": 0.0,  # OKX 限流时无法获取真实持仓量；下游 EV/S3 不依赖此字段
                    "avg_px": tracker_rec.entry_price,
                    "upl": 0.0,  # OKX 限流时无法获取实时 upl
                    "upl_ratio": 0.0,
                    "mark_px": 0.0,
                    "open_time": open_time_sec,
                    "query_failed": True,  # 标记数据来源为本地回退
                }
            return {"has_position": False, "query_failed": True}
        positions = pos_result.get("positions", [])
        if not positions:
            return {"has_position": False}
        pos = positions[0]

        open_time_sec = 0.0
        tracker_rec = self.position_tracker.get_open_position(inst_id)
        if tracker_rec and tracker_rec.entry_time:
            try:
                if tracker_rec.entry_time.endswith("Z"):
                    ts = tracker_rec.entry_time.replace("Z", "+00:00")
                else:
                    ts = tracker_rec.entry_time
                from datetime import datetime as _dt

                open_time_sec = _dt.fromisoformat(ts).timestamp()
            except Exception:
                open_time_sec = 0.0
        if open_time_sec <= 0:
            # OKX 回退：取 ctime（字符串秒）
            ctime = pos.get("cTime") or pos.get("ctime") or pos.get("created_at", "0")
            try:
                open_time_sec = float(ctime) / 1000 if float(ctime) > 1e12 else float(ctime)
            except Exception:
                open_time_sec = 0.0

        return {
            "has_position": True,
            "pos_side": pos["pos_side"],
            "pos_size": pos["pos"],
            "avg_px": pos["avg_px"],
            "upl": pos["upl"],
            "upl_ratio": pos["upl_ratio"],
            "mark_px": pos["mark_px"],
            "open_time": open_time_sec,
        }

    def _count_total_positions(self) -> int:
        # 单次批量查询OKX全部持仓，避免逐个查询因限流/超时导致计数偏低、超额开仓
        pos_result = self.okx_client.get_positions()
        if pos_result.get("ok"):
            return len(pos_result.get("positions", []))
        # API失败时回退到本地持仓跟踪器
        return len(self.position_tracker.all_open_positions())

    # ──────────────────────────────────────────────────────────
    # Phase A: MODE 算力重分配工具函数（Spec §3.2 / §3.3）
    # ──────────────────────────────────────────────────────────

    def _default_candidate_rank(self, candidate_pool: list) -> list:
        """候选池默认排序（Spec §3.2）：先波动率缓存 → 历史交易次数倒序 → 字母序 fallback。

        只用于币种集构造阶段的 TopN 截断，不决定最终开仓排名（最终排名仍走 A7+五角+置信度）。
        """
        # 纯静态 fallback：按字母序（让测试可复现，且与当前代码简单等价）
        return sorted(candidate_pool)

    def _held_coins_union(self) -> set:
        """实际持仓币种集合 = position_tracker ∪ OKX 去重并集。

        避免单边数据源漏单导致 occupancy 误判（例如 OKX API 成功但 tracker 没同步、或反过来）。
        """
        tracker = getattr(self.position_tracker, "all_open_positions", lambda: [])
        held_from_tracker = {p.coin for p in (tracker() or [])}

        okx_fn = getattr(self.okx_client, "get_positions", lambda: {"ok": False})
        okx_result = okx_fn() or {}
        held_from_okx = set()
        if okx_result.get("ok"):
            for p in okx_result.get("positions", []) or []:
                inst_id = p.get("instId") or ""
                base = inst_id.split("-")[0]
                if base:
                    held_from_okx.add(base)
        return held_from_tracker | held_from_okx

    def _is_dynamic_blacklisted(self, coin: str) -> bool:
        """动态黑名单检查的统一包装，兼容 tuple(blocked,reason) / bool 两种返回值。"""
        fn = getattr(self, "_check_dynamic_blacklist", None)
        if not callable(fn):
            return False
        result = fn(coin)
        if isinstance(result, tuple):
            return bool(result[0]) if result else False
        return bool(result)

    def _decide_mode_coins(self) -> Tuple[str, list, list, list]:
        """返回 (mode_tag, anom_coins, infer_full_coins, infer_coarse_coins)

        - enable_mode_switch=False → MODE-OFF，anom/infer_full 全量 coins，coarse 空
        - enable_mode_switch=True  → MODE1/MODE2/MODE3 按 occupancy 分支
        """
        held_coins = self._held_coins_union()

        # 候选池 = 全量 coins ∩ 非持仓 ∩ 非静态黑名单 ∩ 非动态黑名单
        candidate_pool = [
            c for c in self.coins
            if c not in held_coins
            and c not in getattr(self, "blacklist_coins", set())
            and not self._is_dynamic_blacklisted(c)
        ]
        candidate_pool = self._default_candidate_rank(candidate_pool)

        N_max = getattr(self, "max_positions", 1) or 1
        actual_held_n = max(
            len(held_coins),
            self._count_total_positions() if callable(getattr(self, "_count_total_positions", None)) else 0,
        )
        occupancy = (actual_held_n / N_max) if N_max else 0.0

        # 开关 OFF → 旧路径（MODE-OFF）
        if not getattr(self, "enable_mode_switch", False):
            return ("MODE-OFF", list(self.coins), list(self.coins), [])

        # 三档 MODE 阈值分支（MODE_OCCUPANCY_MODE2 默认 = 2/3 ≈ 0.6667）
        if occupancy >= self.MODE_OCCUPANCY_MODE3:
            mode = "MODE3_FULL"
            anom_candidate_n = self.MODE3_COARSE_CANDIDATE_TOPN
            infer_full_candidate_n = 0
            infer_coarse_candidate_n = self.MODE3_COARSE_CANDIDATE_TOPN
        elif occupancy >= self.MODE_OCCUPANCY_MODE2:
            mode = "MODE2_HALF"
            anom_candidate_n = 4
            infer_full_candidate_n = 5
            infer_coarse_candidate_n = 0
        else:
            mode = "MODE1_LIGHT"
            anom_candidate_n = len(candidate_pool)
            infer_full_candidate_n = len(candidate_pool)
            infer_coarse_candidate_n = 0

        anom_coins = list(held_coins) + candidate_pool[:anom_candidate_n]
        infer_full_coins = list(held_coins) + candidate_pool[:infer_full_candidate_n]
        infer_coarse_coins = candidate_pool[
            infer_full_candidate_n: infer_full_candidate_n + infer_coarse_candidate_n
        ]
        return mode, anom_coins, infer_full_coins, infer_coarse_coins

    def _infer_coarse(self, coin: str) -> Dict:
        """MODE3 粗推理（S1 快速路径）。

        相比 _fetch_and_infer（Full BCRM2.0 全链路：拉K线→特征→训练/推理→卦象→五角→三角证伪），
        本方法仅做：缓存命中 → 简化特征（close/volatility/is_ranging/MA方向）→ 估算粗置信度。
        只产出 _fetch_and_infer 的子集字段（足够 MODE3 粗排序 + 补全门禁判断）。

        返回结构对齐 _fetch_and_infer（但省略深度字段 bagua_confidence/triangle_verification 等）：
          {"ok": bool, "coin": str, "inst_id": str, "direction": str,
           "confidence": float, "fail_closed": bool, "price": float,
           "volatility": float, "is_ranging": bool, "hexagram": str, "_coarse": True}
        """
        inst_id = f"{coin}-USDT-SWAP"
        cache_key = ("infer_coarse", coin)
        ttl = getattr(self, "MODE_CACHE_TTL_INFER_COARSE", 2)
        hit, cached = self._cache_get(cache_key, ttl)
        if hit and isinstance(cached, dict):
            return dict(cached)

        try:
            # ── 最小探针：短 K 线 40 根（MODE3 快速路径，不做 160 根全量请求）──
            short_limit = getattr(self, "MODE_COARSE_KLINE_LIMIT", 40)
            kline_data = _load_kline_from_okx(inst_id=inst_id, bar=self.bar, limit=short_limit)
            if not kline_data or len(kline_data) < 20:
                # K 线不足 → fail_closed=True（保守：粗推理不交易，等补全）
                stub = {"ok": True, "coin": coin, "inst_id": inst_id,
                        "direction": "NEUTRAL", "confidence": 0.0, "fail_closed": True,
                        "price": 0.0, "volatility": 0.03, "is_ranging": True, "hexagram": "",
                        "_coarse": True, "kline_data": []}
                self._cache_set(cache_key, stub)
                return stub

            closes = [float(c.get("c", 0.0)) for c in kline_data if c.get("c") is not None]
            highs = [float(c.get("h", c.get("C", 0.0))) for c in kline_data]
            lows = [float(c.get("l", c.get("L", 0.0))) for c in kline_data]
            price = float(closes[-1]) if closes else 0.0

            # ── 波动率粗算（简化 std，不做 EWM）──
            import math
            rets = []
            for i in range(1, len(closes)):
                if closes[i - 1] > 0:
                    rets.append((closes[i] - closes[i - 1]) / closes[i - 1])
            volatility = float(np.std(rets)) if rets else 0.03
            if volatility <= 0 or not math.isfinite(volatility):
                volatility = 0.03

            # ── 震荡/趋势：用 high-low std vs close std 比值粗分 ──
            is_ranging = False
            try:
                hl_range = np.array(highs) - np.array(lows)
                if closes and np.mean(closes) > 0:
                    hl_rel_std = float(np.std(hl_range) / np.mean(closes))
                    is_ranging = hl_rel_std < volatility * 1.4
            except Exception:
                pass

            # ── 方向粗算（短 MA20 vs MA5 交叉，无 BCRM2.0 训练/推理）──
            direction = "NEUTRAL"
            confidence = 0.40  # 粗置信度基线（待补全后才开仓）
            try:
                if len(closes) >= 20:
                    ma5 = float(np.mean(closes[-5:])) if len(closes) >= 5 else closes[-1]
                    ma20 = float(np.mean(closes[-20:]))
                    diff = (ma5 - ma20) / ma20 if ma20 > 0 else 0.0
                    if diff > volatility * 0.5:
                        direction = "UP"
                        confidence = min(0.70, 0.40 + abs(diff) * 5)
                    elif diff < -volatility * 0.5:
                        direction = "DOWN"
                        confidence = min(0.70, 0.40 + abs(diff) * 5)
            except Exception:
                pass

            result = {
                "ok": True, "coin": coin, "inst_id": inst_id,
                "direction": direction, "confidence": round(confidence, 4),
                "fail_closed": False if direction in ("UP", "DOWN") else True,
                "price": price, "volatility": round(volatility, 6),
                "is_ranging": is_ranging, "hexagram": "",
                "_coarse": True, "kline_data": kline_data,
                "bagua_direction": "neutral", "bagua_confidence": 0.0,
            }
            self._cache_set(cache_key, result)
            return result
        except Exception as e:
            self._log(f"[{coin}] _infer_coarse 异常: {e}，降级为 fail_closed", "WARN")
            stub = {"ok": False, "coin": coin, "inst_id": inst_id,
                    "direction": "NEUTRAL", "confidence": 0.0, "fail_closed": True,
                    "price": 0.0, "volatility": 0.03, "is_ranging": True, "hexagram": "",
                    "_coarse": True, "kline_data": [], "error": str(e)}
            return stub

    def _cache_get(self, key: tuple, ttl_cycles: int):
        """命中返回 (True, payload)；未命中或过期返回 (False, None)。

        TTL 用 self._cycle_idx 轮次计数（而非 wall-clock），确保测试可复现。
        """
        if key not in self._mode_cache:
            return False, None
        payload, written_cycle = self._mode_cache[key]
        if self._cycle_idx - written_cycle > ttl_cycles:
            del self._mode_cache[key]
            return False, None
        return True, payload

    def _cache_set(self, key: tuple, payload):
        """写入缓存并按轮次打时间戳。每 30 轮 purge 一次超 TTL×4 的条目防 OOM。"""
        self._mode_cache[key] = (payload, self._cycle_idx)
        if self._cycle_idx % 30 == 0:
            max_ttl = max(
                getattr(self, "MODE_CACHE_TTL_ANOMALY", 2),
                getattr(self, "MODE_CACHE_TTL_INFER_COARSE", 1),
                getattr(self, "MODE_CACHE_TTL_KLINE_SHORT", 1),
                getattr(self, "MODE_CACHE_TTL_HORIZON_PREDS", 2),
                getattr(self, "MODE_CACHE_TTL_POSITION_EV", 2),
            )
            cutoff = self._cycle_idx - max_ttl * 4
            self._mode_cache = {k: v for k, v in self._mode_cache.items() if v[1] >= cutoff}

    def _advance_cycle_idx(self) -> int:
        """B4 防御：推进轮次计数，若发生回退（日期 rollover / 手工 reset）自动清 MODE 缓存。

        关键机制：
        - 用 self._last_cycle_seen 记住上次推进后的值（不因外部修改 cycle_idx 而丢失）。
        - 如果外部传入的当前 cycle_idx < _last_cycle_seen，说明有外部把计数回退了。
        - 回退会导致缓存条目 written_cycle 全部 > new_cycle → TTL 失效判定永远为 False →
          缓存永不过期、S1 异常评分永远不重算（整个系统假活）。
        """
        last_seen = getattr(self, "_last_cycle_seen", -1)
        current_before_advance = getattr(self, "_cycle_idx", 0)

        if last_seen >= 1 and current_before_advance < last_seen:
            # 发现回退：清缓存
            if getattr(self, "_mode_cache", None):
                cache_len_before = len(self._mode_cache)
                try:
                    self._log(
                        f"[缓存TTL] cycle_idx 回退 {last_seen} → {current_before_advance}，"
                        f"清空 {cache_len_before} 条缓存以避免 TTL 错乱",
                        "WARN",
                    )
                except Exception:
                    pass
                self._mode_cache.clear()

        new_idx = max(0, current_before_advance) + 1
        self._cycle_idx = new_idx
        self._last_cycle_seen = new_idx
        return new_idx

    def _pick_topup_from_coarse(self, infer_coarse_coins: list, coarse_inferences: Dict[str, dict]) -> list:
        """粗推理 Top1 选补全推理。Spec §3.1 Phase2: 粗置信度排序后仅 Top1 需补全。

        注意：只返回列表（长度 0 或 1），实际 _fetch_and_infer 调用由主循环负责。
        """
        if not infer_coarse_coins:
            return []
        ranked = sorted(
            infer_coarse_coins,
            key=lambda c: coarse_inferences.get(c, {}).get("confidence", 0.0),
            reverse=True,
        )
        return ranked[:1]

    def _mark_coarse_inference(self, inference: dict):
        """为粗推理结果打 _coarse=True 标记（原地修改）。"""
        inference["_coarse"] = True

    def _format_confidence(self, conf) -> str:
        """置信度 float→2位小数 字符串；非数值返回 'N/A'。"""
        return f"{conf:.2f}" if isinstance(conf, (int, float)) else "N/A"

    def _apply_topup_full(self, all_inferences: Dict[str, dict], topup_coin: str,
                          full_inference: dict, coarse_confidence: float = None):
        """将补全推理（完整版）覆盖 all_inferences[topup_coin]，清除 _coarse 标，打日志。"""
        cleaned = dict(full_inference)
        cleaned.pop("_coarse", None)
        all_inferences[topup_coin] = cleaned

        full_conf = (
            full_inference.get("confidence")
            or full_inference.get("next_state", {}).get("confidence")
        )
        a7_pass = bool(full_inference.get("a7_pass", True))
        pentagon_pass = bool(full_inference.get("pentagon_pass", True))
        self._log(
            f"[MODE3][补全推理] {topup_coin} 粗→完整版 "
            f"粗置信度={self._format_confidence(coarse_confidence)} "
            f"完整置信度={self._format_confidence(full_conf)} "
            f"A7={'PASS' if a7_pass else 'FAIL'} "
            f"五角={'PASS' if pentagon_pass else 'FAIL'}",
            "INFO",
        )

    def _guard_coarse_not_toppedup(self, coin: str, inference: dict, toppedup_history: set) -> bool:
        """Phase3 开仓门禁：粗结果 + 未补全 → 返回 False（禁止开仓）+ 打 WARN。

        Returns:
            True → 可以继续（非 coarse 或已补全）
            False → 必须跳过该币（禁止进入 _open_position）
        """
        if not bool(inference.get("_coarse", False)):
            return True
        if coin in toppedup_history:
            return True
        # 粗 + 未补全 → 拦截
        conf = inference.get("confidence") or inference.get("next_state", {}).get("confidence")
        conf_str = self._format_confidence(conf)
        self._log(
            f"[MODE3][门禁] {coin} 粗推理结果未补全，跳过开仓 "
            f"(coarse=True 且不在 toppedup_history，粗置信度={conf_str})",
            "WARN",
        )
        return False

    def _get_leverage(self) -> float:
        """获取当前默认杠杆倍数"""
        return float(self.okx_client.cfg.get("default_leverage", 3))

    def _compute_p2_dynamic_sizing_factors(self, hexagram: str,
                                           lookback: int = 30,
                                           min_samples: int = 5) -> Dict:
        """P2 动态仓位管理：计算三因子（凯利/连亏/卦象）。

        - kelly_factor: 半凯利 f 换算的仓位系数；样本不足时返回 1.0
        - consecutive_loss_factor: 连亏缩仓；从 risk_manager.state 读取 current_consecutive_losses
        - hexagram_factor: 卦象类型系数；基于 BULLISH/BEARISH/NEUTRAL
        - hexagram_class: 卦象分类名 bullish/bearish/neutral（用于日志）

        Args:
            hexagram: 当前卦名（如"泰"/"否"）
            lookback: 取最近多少笔算 win_rate / avg_win / avg_loss
            min_samples: 少于该样本数不启用凯利（保守保持默认仓位）

        Returns:
            Dict {kelly_factor, consecutive_loss_factor, hexagram_factor, hexagram_class,
                  vol_regime_factor, vol_regime_class, vol_adaptive_sl_mult, vol_adaptive_tp_mult,
                  win_rate, avg_win, avg_loss, win_streak, loss_streak}
        """
        # 1. 连亏缩仓
        streak = getattr(self.risk_manager.state, "current_consecutive_losses", 0) or 0
        con_loss_f = RiskManager.consecutive_loss_factor(streak)

        # 2. 卦象类型系数
        hex_f, hex_cls = RiskManager.hexagram_class_factor(
            hexagram,
            bullish_hexagrams=set(BULLISH_HEXAGRAMS),
            bearish_hexagrams=set(BEARISH_HEXAGRAMS),
        )

        # 3. 半凯利动态仓位
        kelly_f = 1.0
        wr = aw = al = 0.0
        trades = list(getattr(self.perf_tracker, "trades", []) or [])
        if trades:
            recent = trades[-lookback:] if len(trades) > lookback else trades
            pnls = [t.pnl for t in recent if t.pnl is not None]
            total = len(pnls)
            if total >= min_samples:
                wins = [p for p in pnls if p >= 0]
                losses = [abs(p) for p in pnls if p < 0]
                wr = len(wins) / total if total else 0.0
                aw = (sum(wins) / len(wins)) if wins else 0.0
                al = (sum(losses) / len(losses)) if losses else 0.0
                kelly_f = RiskManager.kelly_half_factor(wr, aw, al)

        # 4. P3 波动率自适应：仓位因子 + ATR 止损/止盈倍率
        # 从最近一次 inference 快照中取波动率（优先 risk_manager.state，否则用默认 0.03）
        vol_raw = getattr(self, "_last_volatility", None) or 0.03
        vol_rf = RiskManager.volatility_position_factor(vol_raw)
        vol_cls = RiskManager.volatility_regime(vol_raw)
        vol_sl, vol_tp = RiskManager.volatility_adaptive_atr_mult(vol_raw)

        # 连胜/连亏（用于日志，不直接做仓位放大；连亏已用）
        win_streak = 0
        loss_streak_current = 0
        for t in reversed(trades):
            if t.pnl is None:
                continue
            if t.pnl >= 0 and loss_streak_current == 0:
                win_streak += 1
            elif t.pnl < 0 and win_streak == 0:
                loss_streak_current += 1
            else:
                break

        return {
            "kelly_factor": kelly_f,
            "consecutive_loss_factor": con_loss_f,
            "hexagram_factor": hex_f,
            "hexagram_class": hex_cls,
            "vol_regime_factor": vol_rf,
            "vol_regime_class": vol_cls,
            "vol_adaptive_sl_mult": vol_sl,
            "vol_adaptive_tp_mult": vol_tp,
            "win_rate": wr,
            "avg_win": aw,
            "avg_loss": al,
            "win_streak": win_streak,
            "loss_streak": streak,
        }

    def _get_base_sl_roi(self, inst_id: str, entry_price: float = 0.0) -> float:
        """读取开仓时 ATR 基线止损收益率。

        优先级（避免 B3 连锁漂移 bug）：
          1. PositionTracker.base_sl_roi（开仓时记录的可靠基线）
          2. stable_base_sl_roi 缓存（旧持仓首次调 SL 前反向推导出的基线，跨轮冻结）
          3. 回退：从 entry_price 和 当前 stop_loss_px 反算（注意：此基线会随 _adjust_sl_tp 漂移！仅首次 fallback 用）
        """
        rec = self.position_tracker.get_open_position(inst_id)
        if rec and rec.base_sl_roi > 0:
            return rec.base_sl_roi
        # 新增 B3：稳定缓存优先（TTL 99999，整个持仓生命周期都冻结）
        chit, cval = self._cache_get(("stable_base_sl_roi", inst_id), ttl_cycles=99999)
        if chit and isinstance(cval, (int, float)) and cval > 0:
            return float(cval)
        # 回退：从 entry_price 和 stop_loss 反算（如果有的话）
        if rec and entry_price > 0 and rec.market_snapshot:
            sl_px = rec.market_snapshot.get("stop_loss_px", 0)
            if sl_px > 0:
                leverage = self._get_leverage()
                price_pct = abs(sl_px - entry_price) / entry_price
                return self._price_change_to_roi(price_pct, leverage)
        return 0.0

    def _get_base_tp_roi(self, inst_id: str, entry_price: float = 0.0) -> float:
        """读取开仓时 ATR 基线止盈收益率。（同 _get_base_sl_roi，三重优先级）"""
        rec = self.position_tracker.get_open_position(inst_id)
        if rec and rec.base_tp_roi > 0:
            return rec.base_tp_roi
        chit, cval = self._cache_get(("stable_base_tp_roi", inst_id), ttl_cycles=99999)
        if chit and isinstance(cval, (int, float)) and cval > 0:
            return float(cval)
        if rec and entry_price > 0 and rec.market_snapshot:
            tp_px = rec.market_snapshot.get("take_profit_px", 0)
            if tp_px > 0:
                leverage = self._get_leverage()
                price_pct = abs(tp_px - entry_price) / entry_price
                return self._price_change_to_roi(price_pct, leverage)
        return 0.0

    def _roi_to_price_change(self, roi_pct: float, leverage: float = None) -> float:
        """订单收益率 → 价格涨跌幅（不含杠杆）

        公式：price_change = roi / leverage
        例子：杠杆10x、订单收益率 +5% → 价格涨跌幅 +0.5%
        """
        if leverage is None:
            leverage = self._get_leverage()
        if leverage <= 0:
            leverage = 1.0
        return roi_pct / leverage

    def _price_change_to_roi(self, price_change_pct: float, leverage: float = None) -> float:
        """价格涨跌幅（不含杠杆） → 订单收益率（含杠杆）

        公式：roi = price_change * leverage
        例子：杠杆10x、价格涨 0.5% → 订单收益率 +5%
        """
        if leverage is None:
            leverage = self._get_leverage()
        return price_change_pct * leverage

    def _calc_sl_price(
        self, entry_price: float, pos_side: str, sl_roi_pct: float, leverage: float = None
    ) -> float:
        """根据订单止损收益率计算止损价格

        Args:
            entry_price: 开仓价
            pos_side: long/short
            sl_roi_pct: 订单止损收益率（正数，如 0.03 = -3% 亏损）
            leverage: 杠杆倍数

        Returns:
            止损价格
        """
        if leverage is None:
            leverage = self._get_leverage()
        price_change = self._roi_to_price_change(sl_roi_pct, leverage)
        if pos_side == "long":
            return entry_price * (1 - price_change)
        else:
            return entry_price * (1 + price_change)

    def _calc_tp_price(
        self, entry_price: float, pos_side: str, tp_roi_pct: float, leverage: float = None
    ) -> float:
        """根据订单止盈收益率计算止盈价格

        Args:
            entry_price: 开仓价
            pos_side: long/short
            tp_roi_pct: 订单止盈收益率（正数，如 0.06 = +6% 盈利）
            leverage: 杠杆倍数

        Returns:
            止盈价格
        """
        if leverage is None:
            leverage = self._get_leverage()
        price_change = self._roi_to_price_change(tp_roi_pct, leverage)
        if pos_side == "long":
            return entry_price * (1 + price_change)
        else:
            return entry_price * (1 - price_change)

    # ── Phase B: EV 风险价值雷达（四档决策）───────────────────
    def _build_ev_subscores(self,
                            pos_side: str,
                            position_age_sec: float,
                            upl_ratio: float,
                            inference: Dict) -> Dict[str, float]:
        """构造 EV 的 7 个归一化子分 s_i ∈ [0,1]（Phase C 细化完成）。

        返回 key 与 self.ev_weights 的 key 严格对齐（少算一项 → 权重为 0）。

        Phase C 真化项：
          - trend_alignment_s（子分3）：bagua_direction + BTC弹簧力场趋势 + bagua_confidence 三因子
          - liquidity_risk_s（子分7）：kline volume 稳定性 + 放量倍数 + 波动率惩罚 三因子
        """
        import numpy as np

        conf = float(inference.get("confidence", 0.5))
        direction = str(inference.get("direction", "UP"))
        vol = float(inference.get("volatility", 0.03))

        # 1. 置信度（直接 clamp 到 [0,1]）
        confidence_s = max(0.0, min(1.0, conf))

        # 2. 方向一致性：持仓方向与本次推理方向是否对齐
        if (pos_side == "long" and direction == "UP") or \
           (pos_side == "short" and direction == "DOWN"):
            direction_consistency_s = 1.0
        elif (pos_side == "long" and direction == "DOWN") or \
             (pos_side == "short" and direction == "UP"):
            direction_consistency_s = 0.0
        else:
            direction_consistency_s = 0.5

        # 3. 趋势对齐度（Phase C C13：三因子加权）
        #    因子 A(0.4)：持仓 vs bagua_direction（卦象趋势）
        #    因子 B(0.4)：持仓 vs BTC 日线大势（_check_btc_trend 双均线弹簧力场）
        #    因子 C(0.2)：bagua_confidence（卦象自身置信度作为强度放大）
        bagua_dir = str(inference.get("bagua_direction", "neutral")).lower()
        if bagua_dir == "neutral":
            bagua_align = 0.5
        elif (pos_side == "long" and bagua_dir == "long") or \
             (pos_side == "short" and bagua_dir == "short"):
            bagua_align = 1.0
        else:
            bagua_align = 0.0
        try:
            btc_bearish, _ = self._check_btc_trend()
        except Exception:
            btc_bearish = None
        if btc_bearish is None:
            btc_trend_align = 0.5
        elif (pos_side == "long" and not btc_bearish) or \
             (pos_side == "short" and btc_bearish):
            btc_trend_align = 1.0
        else:
            btc_trend_align = 0.0
        bagua_conf = max(0.0, min(1.0, float(inference.get("bagua_confidence", 0.5))))
        trend_alignment_s = max(0.0, min(1.0,
            0.4 * bagua_align + 0.4 * btc_trend_align + 0.2 * bagua_conf
        ))

        # 4. PnL 动量：浮盈 → 高分；浮亏 10% → 接近 0
        pnl_momentum_s = max(0.0, min(1.0, 0.5 + float(upl_ratio) * 10.0))

        # 5. 市况友好度：波动率越低越友好（低波→0.9；正常→0.6；高波→0.3）
        if vol <= 0.02:
            regime_friendly_s = 0.9
        elif vol <= 0.05:
            regime_friendly_s = 0.6
        else:
            regime_friendly_s = 0.3

        # 6. 持仓年龄：以 60h（1H 周期 60 根 ≈ 2.5 天）为中轴线性衰减
        hold_h = max(0.0, position_age_sec / 3600.0)
        holding_age_s = max(0.0, min(1.0, 1.0 - hold_h / 60.0))

        # 7. 流动性风险（Phase C C14：三因子加权 → 越高代表流动性越好，风险越低）
        #    因子 A(0.5)：volume 稳定性 mean/std（越大越稳定）
        #    因子 B(0.3)：最近 volume 较均值放量倍数（越大 → 参与度高 → 好）
        #    因子 C(0.2)：1 - vol/0.10（波动率越低 → 滑点风险越低 → 好）
        kline_data = inference.get("kline_data") or []
        try:
            volumes = [float(k.get("v", k.get("V", 0))) for k in kline_data if k]
            # 取最近 60 根（不足则全取，最少 5 根有效）
            volumes = volumes[:60]
            if len(volumes) >= 5 and sum(volumes) > 0:
                v_arr = np.array(volumes, dtype=float)
                mean_v = float(np.mean(v_arr))
                std_v = float(np.std(v_arr)) + 1e-9
                # 稳定性 = mean/std，典型区间 [0.5, 5.0]，norm 至 [0.2, 1.0]
                stability_raw = mean_v / std_v
                vol_stability_norm = max(0.2, min(1.0, 0.2 + 0.8 * min(1.0, stability_raw / 3.0)))
                # 放量 = last / mean，典型 [0.5, 3.0]，norm 至 [0.2, 1.0]
                last_v = float(v_arr[-1]) if len(v_arr) else mean_v
                spike_ratio = last_v / mean_v if mean_v > 0 else 1.0
                volume_spike_norm = max(0.2, min(1.0, 0.2 + 0.8 * min(1.0, spike_ratio / 2.5)))
                # 波动率惩罚：vol=0 → 1.0；vol=0.10 → 0.0
                vol_liquidity_norm = max(0.0, min(1.0, 1.0 - vol / 0.10))
                liquidity_risk_s = max(0.0, min(1.0,
                    0.5 * vol_stability_norm + 0.3 * volume_spike_norm + 0.2 * vol_liquidity_norm
                ))
            else:
                liquidity_risk_s = 0.5  # 数据不足 → 中性中值
        except Exception:
            liquidity_risk_s = 0.5  # 异常降级 → 中性中值

        return {
            "confidence_s": round(confidence_s, 4),
            "direction_consistency_s": round(direction_consistency_s, 4),
            "trend_alignment_s": round(trend_alignment_s, 4),
            "pnl_momentum_s": round(pnl_momentum_s, 4),
            "regime_friendly_s": round(regime_friendly_s, 4),
            "holding_age_s": round(holding_age_s, 4),
            "liquidity_risk_s": round(liquidity_risk_s, 4),
        }

    def _handle_ev_four_tier(self,
                             coin: str,
                             inst_id: str,
                             pos_side: str,
                             position_age_sec: float,
                             in_protection: bool,
                             upl: float,
                             upl_ratio: float,
                             inference: Dict,
                             all_inferences: Dict) -> Dict:
        """EV 四档决策（Spec §4.3）。

        四档：
          T1 FORCE_CLOSE:   EV < EV_FORCE_CLOSE_BELOW，非保护期 → 2/2 确认强制离场
          T2 WARN:          EV_WARN_LOWER_BOUND ≤ EV < EV_WARN_UPPER_BOUND → 收紧止损
          T3 NORMAL:        EV_WARN_UPPER_BOUND ≤ EV ≤ EV_STRONG_HOLD_ABOVE → 按原计划
          T4 STRONG_HOLD:   EV > EV_STRONG_HOLD_ABOVE → 放宽止损/放大止盈

        Feature Flag: enable_ev_radar=False 时短路 return，不调 calc_position_ev。
        Protection:  in_protection=True 时禁止 FORCE_CLOSE/WARN 动作，仅日志 skip。

        返回 decision dict:
          {"tier": "FORCE_CLOSE"|"WARN"|"NORMAL"|"STRONG_HOLD"|"BYPASS",
           "ev": float, "subs": dict, "action": str|None}
        """
        # S2 开关短路：calc_position_ev 必须从未被调用（对应 TestEVSwitchOffBypasses）
        if not getattr(self, "enable_ev_radar", False):
            self._log(f"[{coin}] EV BYPASS (S2=off)", "INFO")
            return {"tier": "BYPASS", "ev": None, "subs": {}, "action": None}

        from scripts.memory_l4.trading_utils import RiskManager

        # ── 构造 7 归一化子分 + EV 合成 ──
        subscores = self._build_ev_subscores(pos_side, position_age_sec,
                                             upl_ratio, inference)
        weights = getattr(self, "ev_weights", None) or {k: 1/7 for k in subscores}
        ev, subs = RiskManager.calc_position_ev(subscores, weights)

        # ── 保护期门禁：EV < WARN_UPPER 时 T1/T2 绝对禁用，仅日志 skip ──
        if in_protection and ev < getattr(self, "EV_WARN_UPPER_BOUND", -0.10):
            self._log(
                f"[{coin}] EV={ev:.3f} < WARN(EV<"
                f"{getattr(self, 'EV_WARN_UPPER_BOUND', -0.10):.2f}) "
                f"but protected (hold={position_age_sec/3600:.1f}h<"
                f"{getattr(self, 'POSITION_PROTECTION_HOURS', 6.0):.0f}h) → "
                f"skip EV_force / EV_warn actions",
                "INFO",
            )
            return {"tier": "PROTECTED_SKIP", "ev": ev, "subs": subs, "action": None}

        # ── 四档阈值 ──
        force_below = getattr(self, "EV_FORCE_CLOSE_BELOW", -0.35)
        warn_lower = getattr(self, "EV_WARN_LOWER_BOUND", -0.35)
        warn_upper = getattr(self, "EV_WARN_UPPER_BOUND", -0.10)
        strong_above = getattr(self, "EV_STRONG_HOLD_ABOVE", +0.30)
        current_price = float(inference.get("price", 0.0))

        # T1: FORCE_CLOSE（EV 深度低，非保护期 → 2/2 离场确认）
        if ev < force_below and not in_protection:
            confirmed, cnt = self._exit_confirm(coin, self.EXIT_ACT_EV_FORCE_CLOSE)
            if confirmed:
                self._clear_exit_confirm(coin, self.EXIT_ACT_EV_FORCE_CLOSE)
                reason = f"ev_force_close|ev={ev:.3f}<{force_below:.2f}|cnt={cnt}"
                self._handle_close_position(
                    inst_id=inst_id, coin=coin, pos_side=pos_side,
                    exit_price=current_price, exit_reason=reason,
                    pnl=upl, pnl_pct=upl_ratio,
                )
                return {"tier": "FORCE_CLOSE", "ev": ev, "subs": subs,
                        "action": f"closed|{reason}"}
            else:
                self._log(
                    f"[{coin}] EV={ev:.3f} T1 FORCE_CLOSE 1/"
                    f"{self.EXIT_CONFIRM_REQUIRED} (cnt={cnt})，等待下一轮确认",
                    "WARN",
                )
                return {"tier": "FORCE_CLOSE_PENDING", "ev": ev, "subs": subs,
                        "action": "pending_confirm"}

        # T2: WARN（收紧止损）
        if warn_lower <= ev < warn_upper:
            self._log(
                f"[{coin}] EV={ev:.3f} T2 WARN | "
                f"trend_align={subs.get('trend_alignment_s', 0):.2f} "
                f"liquidity={subs.get('liquidity_risk_s', 0):.2f} "
                f"dir_consist={subs.get('direction_consistency_s', 0):.2f} "
                f"pnl_mom={subs.get('pnl_momentum_s', 0):.2f} → 收紧止损",
                "WARN",
            )
            adj = getattr(self, "_adjust_sl_tp", None)
            if adj and callable(adj):
                try:
                    adj(coin, inst_id, pos_side, mode="tighten")
                except Exception:
                    pass
            return {"tier": "WARN", "ev": ev, "subs": subs, "action": "tighten_sl"}

        # T4: STRONG_HOLD（放宽止损/止盈）
        if ev > strong_above:
            self._log(
                f"[{coin}] EV={ev:.3f} T4 STRONG_HOLD | "
                f"trend_align={subs.get('trend_alignment_s', 0):.2f} "
                f"liquidity={subs.get('liquidity_risk_s', 0):.2f} "
                f"dir_consist={subs.get('direction_consistency_s', 0):.2f} "
                f"pnl_mom={subs.get('pnl_momentum_s', 0):.2f} → 放宽止损/止盈",
                "INFO",
            )
            adj = getattr(self, "_adjust_sl_tp", None)
            if adj and callable(adj):
                try:
                    adj(coin, inst_id, pos_side, mode="relax")
                except Exception:
                    pass
            return {"tier": "STRONG_HOLD", "ev": ev, "subs": subs, "action": "relax_sl"}

        # T3: NORMAL（不动作，按原计划）
        self._log(
            f"[{coin}] EV={ev:.3f} T3 NORMAL | "
            f"trend_align={subs.get('trend_alignment_s', 0):.2f} "
            f"liquidity={subs.get('liquidity_risk_s', 0):.2f} "
            f"dir_consist={subs.get('direction_consistency_s', 0):.2f} "
            f"pnl_mom={subs.get('pnl_momentum_s', 0):.2f} → 按原计划持有",
            "INFO",
        )
        return {"tier": "NORMAL", "ev": ev, "subs": subs, "action": None}

    def _adjust_sl_tp(self, coin: str, inst_id: str, pos_side: str, mode: str) -> bool:
        """S2 EV雷达真实调 SL/TP（WARN收紧 / STRONG_HOLD放宽）。
        基于开仓时 ATR 基线 ROI × modulation 因子 + ATR floor 保护。
        同一 inst_id+mode 2 轮内只调一次（防 OKX API 重复触发）。
        返回 True 表示成功下发（或 dry-run 日志）；False = 跳过。
        """
        assert mode in ("tighten", "relax"), f"_adjust_sl_tp 未知 mode={mode}"
        # ── 防重复：2 轮 TTL 缓存 ──────────────────────────
        cache_key = ("s2_adjust_sl_tp", inst_id, mode)
        prev_hit, _ = self._cache_get(cache_key, ttl_cycles=2)
        if prev_hit:
            return False
        # ── 读取基线 SL/TP ROI（开仓 ATR 基线） ─────────────
        rec = self.position_tracker.get_open_position(inst_id)
        if rec is None or rec.entry_price is None or rec.entry_price <= 0:
            self._log(f"[S2调整SLTP] {coin} {inst_id} 取不到持仓 entry_price，跳过", "DEBUG")
            return False
        entry_price = rec.entry_price
        leverage = self._get_leverage()
        base_sl_roi = self._get_base_sl_roi(inst_id, entry_price)
        base_tp_roi = self._get_base_tp_roi(inst_id, entry_price)
        if base_sl_roi <= 0 or base_tp_roi <= 0:
            self._log(
                f"[S2调整SLTP] {coin} {inst_id} 基线SL/TP ROI缺失 "
                f"(sl={base_sl_roi:.4f}, tp={base_tp_roi:.4f})，旧持仓不调",
                "WARN",
            )
            return False
        # ── modulation 因子 + floor 保护 ────────────────────
        if mode == "tighten":
            sl_k, tp_k = 0.7, 0.85     # 收紧：止损近30%、止盈降15%
        else:  # relax
            sl_k, tp_k = 1.3, 1.25     # 放宽：止损远30%、止盈提25%
        ATR_FLOOR_ROI = 0.015          # 1.5% ROI 绝对下限：避免过度收紧到开仓价附近
        new_sl_roi = max(base_sl_roi * sl_k, ATR_FLOOR_ROI)
        new_tp_roi = base_tp_roi * tp_k
        # ── 换算真实价格 ──────────────────────────────────
        new_sl_px = self._calc_sl_price(entry_price, pos_side, new_sl_roi, leverage)
        new_tp_px = self._calc_tp_price(entry_price, pos_side, new_tp_roi, leverage)
        # ── 方向合理性校验（顺序不可乱） ───────────────────
        if pos_side == "long":
            ok = (new_sl_px < entry_price < new_tp_px)
        else:  # short
            ok = (new_tp_px < entry_price < new_sl_px)
        if not ok:
            self._log(
                f"[S2调整SLTP] {coin} {pos_side} 方向校验失败："
                f"sl={new_sl_px:.3f}, entry={entry_price:.3f}, tp={new_tp_px:.3f}，跳过",
                "ERROR",
            )
            return False
        # ── 取消旧 algo → 下新 SL/TP ──────────────────────
        try:
            self._log(
                f"[S2调整SLTP:{mode}] {coin} {pos_side} {inst_id} "
                f"| baseline SL/TP ROI = {base_sl_roi*100:.2f}% / {base_tp_roi*100:.2f}%"
                f" → x{sl_k:.2f}/x{tp_k:.2f} = {new_sl_roi*100:.2f}% / {new_tp_roi*100:.2f}%"
                f" | price SL={new_sl_px:.3f}, TP={new_tp_px:.3f} (entry={entry_price:.3f})",
                "INFO",
            )
            try:
                if self.okx_client and hasattr(self.okx_client, "cancel_all_algo_orders"):
                    self.okx_client.cancel_all_algo_orders(instId=inst_id)
            except Exception as ce:
                self._log(f"[S2调整SLTP] 取消旧algo（可能无）：{ce}", "DEBUG")
            if self.okx_client and hasattr(self.okx_client, "place_stop_loss_take_profit"):
                self.okx_client.place_stop_loss_take_profit(
                    inst_id=inst_id,
                    pos_side=pos_side,
                    stop_loss_px=new_sl_px,
                    take_profit_px=new_tp_px,
                    reason=f"ev_adjust_sl_tp:{mode}",
                )
            else:
                self._log(
                    f"[S2调整SLTP] DRY-RUN okx_client.place_stop_loss_take_profit 未配置",
                    "INFO",
                )
            # ── B3 冻结基线：旧持仓(base_roi=0) 首次调节后，把基线"钉死"，避免下一轮反算漂移 ──
            # 没有这步时：WARN tighten → SL 降到 64545 → 下轮 fallback 反算把 64545 当"基线"
            # → 再次 tighten ×0.7 → SL 再缩 30%（连锁漂移 bug）
            try:
                if getattr(rec, "base_sl_roi", 0) <= 0:
                    try:
                        rec.base_sl_roi = float(base_sl_roi)
                    except Exception:
                        self._cache_set(("stable_base_sl_roi", inst_id), float(base_sl_roi))
                if getattr(rec, "base_tp_roi", 0) <= 0:
                    try:
                        rec.base_tp_roi = float(base_tp_roi)
                    except Exception:
                        self._cache_set(("stable_base_tp_roi", inst_id), float(base_tp_roi))
            except Exception:
                pass  # 冻结失败不影响主流程
            self._cache_set(cache_key, self._cycle_idx)
            return True
        except Exception as e:
            self._log(f"[S2调整SLTP] {coin} 失败：{e}", "ERROR")
            return False

    # ── Phase C: 多 horizon 最佳离场 K 线推荐（S3）──────────────
    def _recommend_exit_bars(self,
                             coin: str,
                             pos_side: str,
                             held_k_bar: int,
                             inference: Dict,
                             k_candidates: List[int] = None) -> Dict:
        """结合当前已持仓 K 线数，推荐 HOLD/PREP_EXIT/EXTEND_TRACK（S3）。

        逻辑（Spec §4.2）：
          1. S3=OFF → 短路 BYPASS，predict_multi_horizon 从未被调用
          2. 调 RiskManager.predict_multi_horizon 计算各候选 K-bar 的置信度
          3. 取 max(confidence) 条目的 k_bar 作为 best_k_bar
          4. best_k_bar > held_k_bar + margin → 尚未到站 → HOLD
             best_k_bar ≈ held_k_bar ± margin → 接近离场站 → PREP_EXIT
             best_k_bar << held_k_bar 且 best.direction 反向 → 已经过站 → PREP_EXIT
             其余 → EXTEND_TRACK（延长观察）

        返回: {"best_k_bar": int, "recommended_action": str,
               "best_direction": str, "best_confidence": float}
        """
        # S3 开关短路（switch-off 测试断言 predict 不被调）
        if not getattr(self, "enable_multi_horizon", False):
            return {"best_k_bar": -1, "recommended_action": "BYPASS",
                    "best_direction": "", "best_confidence": 0.0}

        from scripts.memory_l4.trading_utils import RiskManager

        if k_candidates is None:
            # Spec §4.3.1: 默认 horizon 列表对齐 BCRM2 多 horizon 训练/预测
            k_candidates = list(getattr(
                self, "HORIZON_BAR_CANDIDATES", [1, 2, 3, 6, 10, 20, 30]))
        margin = int(getattr(self, "HORIZON_PREP_EXIT_MARGIN", 3))

        # ── 真实 BCRM 多 horizon（Phase C §4.3.1 接入）──────────────
        # 优先：从 adapter 调 engine.predict_multi_horizon（每 horizon 独立 LGBM）
        # 失败：回退 RiskManager.predict_multi_horizon 合成（pentagon_score 启发式）
        source_tag = "synthetic"
        horizons = []
        try:
            adapter = getattr(self, "bcrm2_adapters", {}).get(coin)
            kline_data = inference.get("kline_data")
            if adapter is not None and kline_data:
                df = self._kline_to_dataframe(kline_data)
                # 缓存：同币种同周期 S3 不重复算（避免 MODE3 每轮 N^2）
                cache_key = ("s3_mh", coin, pos_side, len(df),
                             float(df["close"].iloc[-1]) if len(df) else 0.0)
                cached_hit, cached_payload = self._cache_get(cache_key, ttl_cycles=1)
                if cached_hit and isinstance(cached_payload, dict):
                    horizons = cached_payload.get("horizons") or []
                    source_tag = cached_payload.get("source", "bcrm2")
                else:
                    mh_result = adapter.predict_multi_horizon(
                        df, horizons=list(k_candidates), idx=-1
                    )
                    if mh_result.get("ok"):
                        mh_dict = mh_result.get("multi_horizon", {})
                        synthesis = mh_result.get("synthesis", {}) or {}
                        mh_dir = mh_result.get("direction", "UP")
                        for h in k_candidates:
                            probs = mh_dict.get(h, {"P_up": 0.5, "P_down": 0.5})
                            if pos_side == "long":
                                p_correct = float(probs.get("P_up", 0.5))
                                h_dir = "UP" if p_correct >= 0.5 else "DOWN"
                            else:
                                p_correct = float(probs.get("P_down", 0.5))
                                h_dir = "DOWN" if p_correct >= 0.5 else "UP"
                            # expected_roi_pct：用 synthesis 的 S(k) 值近似，区间 [-0.05, 0.10]
                            s_curve = synthesis.get("S_curve", {})
                            s_k = float(s_curve.get(h, 0.0))
                            roi = max(-0.05, min(0.10, s_k * 0.05 + 0.01))
                            horizons.append({
                                "k_bar": int(h),
                                "confidence": round(p_correct, 4),
                                "direction": h_dir,
                                "expected_roi_pct": round(roi, 6),
                            })
                        source_tag = "bcrm2"
                    else:
                        horizons = []
                    self._cache_set(cache_key, {"horizons": horizons, "source": source_tag})

        except Exception as _s3e:
            horizons = []  # 触发 fallback

        if not horizons:
            pred = RiskManager.predict_multi_horizon(inference, k_candidates)
            horizons = pred.get("horizons", [])
            source_tag = "synthetic"

        if not horizons:
            return {"best_k_bar": -1, "recommended_action": "NOOP",
                    "best_direction": "", "best_confidence": 0.0,
                    "source": source_tag}

        best_h = max(horizons, key=lambda x: x["confidence"])
        best_k = int(best_h["k_bar"])
        best_dir = str(best_h["direction"])
        best_conf = float(best_h["confidence"])

        # 持仓方向 pos_side 与 best_dir 是否一致
        pos_is_long = (pos_side == "long")
        best_is_up = (best_dir == "UP")
        direction_consistent = (pos_is_long == best_is_up)

        if best_k > held_k_bar + margin and direction_consistent:
            # 最佳站在后面 → 继续持有
            action = "HOLD"
        elif abs(best_k - held_k_bar) <= margin:
            # 接近最佳站 → 准备离场
            action = "PREP_EXIT"
        elif best_k < held_k_bar - margin and not direction_consistent:
            # 已过站且反向（原预测 UP 过久变为 DOWN 等）→ PREP_EXIT
            action = "PREP_EXIT"
        elif best_k < held_k_bar and not direction_consistent:
            # 已过站 + 反向（宽松版）
            action = "PREP_EXIT"
        else:
            action = "EXTEND_TRACK"

        return {
            "best_k_bar": best_k,
            "recommended_action": action,
            "best_direction": best_dir,
            "best_confidence": round(best_conf, 4),
            "source": source_tag,  # "bcrm2" | "synthetic"
        }

    # ── Phase C: S4 排名止盈前构造持仓列表 ─────────────────────
    def _build_ranked_positions(self, all_inferences: Dict[str, dict]) -> List[Dict]:
        """遍历当前所有持仓 + 从 all_inferences 取对应 inference，构建 S4 输入。

        每个元素至少包含：coin, inst_id, pos_side, upl, upl_ratio, mark_price,
                          in_protection, position_age_sec, inference(可选)
        按 upl 从高到低排序返回（Top1 最大盈利在 [0]）。
        """
        result: List[Dict] = []
        if not all_inferences:
            return result

        for coin, inference in all_inferences.items():
            try:
                pos_info = self._check_positions(coin)
                if not pos_info.get("has_position"):
                    continue
                tracker_pos = self.position_tracker.get_open_position(pos_info.get("inst_id", f"{coin}-USDT-SWAP"))
                is_external = tracker_pos and tracker_pos.strategy_source == "external"
                if is_external:
                    continue

                inst_id = pos_info.get("inst_id", f"{coin}-USDT-SWAP")
                pos_side = pos_info.get("pos_side", "long")
                upl = float(pos_info.get("upl", 0.0))
                upl_ratio = float(pos_info.get("upl_ratio", 0.0))
                mark_price = float(pos_info.get("mark_px", inference.get("price", 0.0)) or 0.0)

                open_time = pos_info.get("open_time", 0)
                position_age_sec = (time.time() - open_time) if open_time > 0 else 0.0
                in_protection = self._is_position_protected(position_age_sec)

                result.append({
                    "coin": coin, "inst_id": inst_id, "pos_side": pos_side,
                    "upl": upl, "upl_ratio": upl_ratio, "mark_price": mark_price,
                    "in_protection": in_protection, "position_age_sec": position_age_sec,
                    "inference": inference,
                })
            except Exception as _e:
                self._log(f"[{coin}] _build_ranked_positions 异常: {_e}", "WARN")
                continue

        # 按 upl 从高到低排序（Top1 盈利最大在前）
        result.sort(key=lambda x: float(x.get("upl", 0.0)), reverse=True)
        return result

    # ── Phase C: 排名止盈 Top1 执行（S4）──────────────────────
    def _handle_ranked_tp_top1(self,
                               positions_with_pnl: List[Dict],
                               gap_threshold: float = None) -> Dict:
        """排名止盈 A/B/C 三档（Spec §4.3.2）。

        A 档（立即止盈换仓）：gap ≥ 阈值 + 非保护期 → 2/2 确认后平仓
        B 档（排队止盈）：gap < 阈值 + 持仓≥12h + 浮盈>0 → 写 reduce_plan 到 PositionRecord
        C 档（不参与）：保护期内 / 浮盈<min_profit / gap 极小 → 无动作

        逻辑：
          1. S4=OFF → 短路 BYPASS
          2. 调 calc_ranked_tp_gap → gap+trigger
          3. trigger=True → A 档路径（保护期门禁 → 2/2 确认 → close）
          4. trigger=False + B 档条件满足 → 写 reduce_plan
          5. 否则 → C 档无动作
        """
        # S4 开关短路
        if not getattr(self, "enable_ranked_tp", False):
            return {"triggered": False, "reason": "S4_DISABLED"}

        if not positions_with_pnl or len(positions_with_pnl) < 2:
            return {"triggered": False, "reason": "LESS_THAN_2_POSITIONS",
                    "tier": "SKIP", "gap_ratio": 0.0, "top1_coin": ""}

        from scripts.memory_l4.trading_utils import RiskManager

        if gap_threshold is None:
            gap_threshold = float(getattr(self, "RANKED_TP_GAP_RATIO", 0.70))
        min_profit = float(getattr(self, "RANKED_TP_MIN_PROFIT_USDT", 5.0))

        gap_result = RiskManager.calc_ranked_tp_gap(positions_with_pnl,
                                                     min_profit_usdt=min_profit)
        top1_idx = int(gap_result.get("top1_idx", -1))
        gap_ratio = float(gap_result.get("gap_ratio", 0.0))
        trigger_raw = bool(gap_result.get("trigger", False))

        # 用 gap_threshold 二次判定
        trigger = trigger_raw and (gap_ratio >= gap_threshold)

        if top1_idx < 0:
            return {"triggered": False, "reason": "NO_TOP1",
                    "gap_ratio": gap_ratio, "top1_idx": top1_idx,
                    "tier": "SKIP", "top1_coin": ""}

        top1 = positions_with_pnl[top1_idx]
        coin = str(top1.get("coin", ""))
        in_protection = bool(top1.get("in_protection", False))
        upl = float(top1.get("upl", 0.0))
        age_h = float(top1.get("position_age_sec", 0.0)) / 3600.0

        # ── B 档检查：reduce_plan 到期触发 ──
        # 如果之前写了 reduce_plan，检查是否到 wait_cycles
        inst_id = str(top1.get("inst_id", ""))
        rec = None
        if hasattr(self, "position_tracker") and self.position_tracker:
            try:
                rec = self.position_tracker.get_open_position(inst_id)
            except Exception:
                rec = None
        if rec and getattr(rec, "reduce_plan", None):
            plan = rec.reduce_plan
            wait = int(plan.get("wait_cycles", 2))
            set_at = int(plan.get("set_at_cycle", 0))
            current_cycle = getattr(self, "_cycle_idx", 0)
            if current_cycle - set_at >= wait:
                # 到期 → 升级为 A 档执行（绕过 gap 阈值）
                self._log(
                    f"[{coin}] ranked_tp B档→到期执行 (waited {current_cycle - set_at}/{wait} cycles, "
                    f"gap={gap_ratio:.2f})",
                    "INFO",
                )
                trigger = True
                gap_ratio = max(gap_ratio, gap_threshold)  # 强制达标
                # 清理 reduce_plan
                try:
                    rec.reduce_plan = None
                except Exception:
                    pass
            else:
                self._log(
                    f"[{coin}] ranked_tp B档排队中 ({current_cycle - set_at}/{wait} cycles, "
                    f"gap={gap_ratio:.2f})",
                    "INFO",
                )

        # ── A 档：gap 达标 → 立即止盈 ──
        if not trigger:
            # ── B 档：gap 不够但持仓老 + 有盈利 → 写 reduce_plan ──
            # Spec §4.3.2 B 档条件：持仓 ≥ 12h + 浮盈 > 0
            b_tier_age_threshold = 12.0
            tier_label = "B" if (upl > 0 and age_h >= b_tier_age_threshold and gap_ratio > 0) else "C"
            # C/B 档无动作日志（便于长期监控 gap_ratio 变化趋势）
            self._log(
                f"[{coin}] ranked_tp {tier_label}档 (gap={gap_ratio:.2f}<{gap_threshold:.2f}, "
                f"upl={upl:.2f}, age={age_h:.1f}h) → 无动作",
                "INFO",
            )
            if (not in_protection and upl > 0 and age_h >= b_tier_age_threshold
                    and gap_ratio > 0 and rec is not None):
                if not getattr(rec, "reduce_plan", None):
                    plan = {
                        "type": "ranked_tp",
                        "wait_cycles": 2,
                        "trigger_rank": round(gap_ratio, 4),
                        "set_at_cycle": getattr(self, "_cycle_idx", 0),
                    }
                    try:
                        rec.reduce_plan = plan
                        self._log(
                            f"[{coin}] ranked_tp B档排队写入 (age={age_h:.1f}h, "
                            f"upl={upl:.2f}, gap={gap_ratio:.2f}<{gap_threshold:.2f}, "
                            f"wait=2 cycles)",
                            "INFO",
                        )
                    except Exception:
                        pass  # PositionRecord 不可写时静默
            return {"triggered": False, "reason": f"NO_TRIGGER|gap={gap_ratio:.3f}",
                    "gap_ratio": gap_ratio, "top1_idx": top1_idx,
                    "tier": tier_label, "top1_coin": coin}

        # ── 保护期门禁 ──
        if in_protection:
            self._log(
                f"[{coin}] ranked_tp gap={gap_ratio:.2f}≥{gap_threshold:.2f} "
                f"but protected (hold={age_h:.1f}h<"
                f"{getattr(self, 'POSITION_PROTECTION_HOURS', 6.0):.0f}h) → "
                f"skip ranked_tp close",
                "INFO",
            )
            return {"triggered": False, "reason": "PROTECTED_SKIP",
                    "gap_ratio": gap_ratio, "top1_idx": top1_idx}

        # ── 2/2 离场确认（复用 EXIT_CONFIRM 状态机）──────
        confirmed, cnt = self._exit_confirm(coin, self.EXIT_ACT_RANKED_TP)
        if not confirmed:
            self._log(
                f"[{coin}] ranked_tp gap={gap_ratio:.2f}≥{gap_threshold:.2f} "
                f"1/{self.EXIT_CONFIRM_REQUIRED} (cnt={cnt})，等待下一轮确认",
                "WARN",
            )
            return {"triggered": False, "reason": f"PENDING_CONFIRM|cnt={cnt}",
                    "gap_ratio": gap_ratio, "top1_idx": top1_idx}

        # 2/2 确认 → 执行止盈平仓
        self._clear_exit_confirm(coin, self.EXIT_ACT_RANKED_TP)
        pos_side = str(top1.get("pos_side", "long"))
        exit_price = float(top1.get("mark_price") or top1.get("inference", {}).get("price") or 0.0)
        upl_ratio = float(top1.get("upl_ratio", 0.0))
        reason = f"ranked_tp|gap={gap_ratio:.2f}≥{gap_threshold:.2f}|top1={coin}|cnt={cnt}"

        self._handle_close_position(
            inst_id=inst_id, coin=coin, pos_side=pos_side,
            exit_price=exit_price, exit_reason=reason,
            pnl=upl, pnl_pct=upl_ratio,
        )
        # 清理 reduce_plan（如果之前有 B 档计划）
        if rec and getattr(rec, "reduce_plan", None):
            try:
                rec.reduce_plan = None
            except Exception:
                pass
        return {"triggered": True, "reason": reason,
                "gap_ratio": gap_ratio, "top1_idx": top1_idx,
                "coin": coin, "tier": "A"}

    def _archive_s4_eval(self, ranked_list: List[Dict], tp_result: Dict):
        """S4 评估结果归档到 JSONL（供 s4_stats.py 长期统计）。

        每条记录包含：ts, cycle, 持仓快照, top1, gap_ratio, tier, triggered, reason
        """
        import json as _json
        archive_path = self.log_dir / "s4_eval_log.jsonl"
        record = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "cycle": int(getattr(self, "_cycle_idx", 0)),
            "positions": [
                {"coin": r.get("coin", ""), "upl": round(float(r.get("upl", 0)), 2),
                 "upl_pct": round(float(r.get("upl_ratio", 0)), 4)}
                for r in ranked_list
            ],
            "top1_coin": str(tp_result.get("top1_coin") or tp_result.get("coin", "")),
            "gap_ratio": round(float(tp_result.get("gap_ratio", 0)), 4),
            "tier": str(tp_result.get("tier", "?")),
            "triggered": bool(tp_result.get("triggered", False)),
            "reason": str(tp_result.get("reason", "")),
        }
        try:
            with open(archive_path, "a", encoding="utf-8") as f:
                f.write(_json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _handle_close_position(
        self,
        inst_id: str,
        coin: str,
        pos_side: str,
        exit_price: float,
        exit_reason: str,
        pnl: float,
        pnl_pct: float,
    ):
        """处理平仓：生成交易记录、更新绩效、生成 case、更新风控、增量学习

        Returns:
            trade summary dict
        """
        # v3.0：平仓后立即清除易经离场系统的评估缓存，
        # 避免下次开仓的前1小时评估被上次持仓的1h窗口缓存污染
        try:
            self.yijing_exit_system.clear_cache(coin=coin, pos_side=pos_side)
        except Exception:
            pass

        trade_rec = self.position_tracker.close_position(
            inst_id=inst_id,
            exit_price=exit_price,
            exit_reason=exit_reason,
            pnl=pnl,
            pnl_pct=pnl_pct,
        )

        if trade_rec:
            perf_summary = self.perf_tracker.record_trade(trade_rec)
            self.risk_manager.update_after_trade(
                pnl, pnl >= 0, current_equity=self.perf_tracker.current_equity
            )

            # P0-2: 动态黑名单更新（连续2次亏损→封禁3日）
            self._update_dynamic_blacklist_on_close(coin, pnl)

            case_id, saved = register_trade_to_l4(trade_rec)

            self._log(
                f"[{coin}] 平仓记录 | {'盈利' if pnl >= 0 else '亏损'} {pnl:.2f}USDT "
                f"({pnl_pct:.2%}) | case={case_id} saved={saved} | "
                f"日盈亏={perf_summary['daily_total_pnl']:.2f} "
                f"连亏={perf_summary['consecutive_losses']}"
            )

            try:
                hold_bars = 0
                if trade_rec.entry_time and trade_rec.exit_time:
                    try:
                        from datetime import datetime

                        entry_dt = datetime.fromisoformat(
                            trade_rec.entry_time.replace("Z", "+00:00")
                        )
                        exit_dt = datetime.fromisoformat(trade_rec.exit_time.replace("Z", "+00:00"))
                        delta = exit_dt - entry_dt
                        hold_bars = int(delta.total_seconds() / 3600)
                    except Exception:
                        pass

                trade_data = {
                    "symbol": coin,
                    "direction": trade_rec.direction,
                    "entry_time": trade_rec.entry_time,
                    "exit_time": trade_rec.exit_time,
                    "entry_price": trade_rec.entry_price,
                    "exit_price": trade_rec.exit_price,
                    "pnl_pct": trade_rec.pnl_pct,
                    "hold_bars": hold_bars,
                    "exit_reason": trade_rec.exit_reason,
                    "confidence": trade_rec.confidence,
                    "hexagram": trade_rec.hexagram,
                    "upper_gua": "",
                    "lower_gua": "",
                    "position_factor": 1.0,
                }
                self.incremental_learner.log_trades_batch([trade_data])

                should_retrain, reason = self.incremental_learner.should_retrain(coin)
                if should_retrain:
                    self._log(f"[{coin}] 增量学习触发再训练: {reason}")
                    retrain_ok = self._trigger_bcrm2_retrain(coin)
                    if retrain_ok:
                        self._log(f"[{coin}] BCRM2.0 增量重训完成")
            except Exception as e:
                self._log(f"[{coin}] 增量学习记录失败: {e}", "WARN")

            retrain_result = self.learning_scheduler.trigger_retrain()
            if retrain_result.get("retrained"):
                self._log(f"[{coin}] 触发重训: {retrain_result.get('reason')}")

            # 优化4：更新置信度校准表
            # 优化5：更新卦象数据驱动校准统计
            try:
                if hasattr(self, "ranging_enhancer") and self.ranging_enhancer:
                    enhance_info = (
                        trade_rec.enhance_info if hasattr(trade_rec, "enhance_info") else None
                    )
                    regime_val = (
                        enhance_info.get("regime", "sideways") if enhance_info else "sideways"
                    )

                    # 置信度校准
                    trade_for_cal = {
                        "confidence": trade_rec.confidence,
                        "pnl_pct": trade_rec.pnl_pct,
                        "regime": regime_val,
                        "hexagram": trade_rec.hexagram or "",
                        "direction": "UP" if trade_rec.direction == "long" else "DOWN",
                    }
                    self.ranging_enhancer.update_calibration([trade_for_cal])

                    # 卦象数据驱动校准（优化5）
                    if (
                        hasattr(self.ranging_enhancer, "hex_calibrator")
                        and self.ranging_enhancer.hex_calibrator
                    ):
                        self.ranging_enhancer.hex_calibrator.record_trade(
                            hexagram=trade_rec.hexagram or "",
                            direction="UP" if trade_rec.direction == "long" else "DOWN",
                            pnl_pct=trade_rec.pnl_pct,
                            confidence=trade_rec.confidence,
                        )
            except Exception as e:
                self._log(f"[{coin}] 校准更新失败: {e}", "WARN")

            # P2-1a增强: 平仓后自动触发L4 Pipeline (M1-M4)
            try:
                self._trigger_l4_pipeline_for_trade(trade_rec, case_id, saved)
            except Exception as e:
                self._log(f"[{coin}] L4 Pipeline自动触发失败: {e}", "WARN")

            return perf_summary
        else:
            self._log(f"[{coin}] 警告：平仓但无对应开仓记录 {inst_id}", "WARN")
            return {}

    def _trigger_bcrm2_retrain(self, coin: str) -> bool:
        """触发 BCRM 2.0 增量重训

        使用最新K线数据重新训练模型，并记录到增量学习版本管理。
        """
        if not self.use_bcrm2:
            return False

        adapter = self.bcrm2_adapters.get(coin)
        if not adapter:
            return False

        try:

            inst_id = f"{coin}-USDT-SWAP"
            kline_resp = self.okx_client.get_kline(inst_id, bar=self.bar, limit=self.kline_limit)
            candles = kline_resp.get("candles", []) if isinstance(kline_resp, dict) else kline_resp
            if not candles or len(candles) < 100:
                self._log(
                    f"[{coin}] BCRM2重训失败：K线不足 {len(candles) if candles else 0}", "WARN"
                )
                return False

            import pandas as pd

            df = pd.DataFrame(
                [
                    {
                        "open": float(c["o"]),
                        "high": float(c["h"]),
                        "low": float(c["l"]),
                        "close": float(c["c"]),
                        "volume": float(c.get("vol", c.get("v", 0))),
                        "timestamp": c.get("ts", ""),
                    }
                    for c in candles
                ]
            )

            retrained = adapter.train(df, force_retrain=True)
            if retrained:
                perf = self.incremental_learner.db.get_recent_performance(coin)
                self.incremental_learner.version_manager.save_version(
                    adapter.engine,
                    coin,
                    version_id=None,
                    metrics={
                        "win_rate": perf.get("win_rate", 0) / 100 if perf.get("win_rate") else 0,
                        "total_trades": perf.get("n_trades", 0),
                    },
                    notes="增量学习自动重训",
                )
                return True
            return False
        except Exception as e:
            self._log(f"[{coin}] BCRM2增量重训异常: {e}", "WARN")
            return False

    def _trigger_l4_pipeline_for_trade(self, trade_rec, case_id: str, saved: bool):
        """平仓后自动触发L4 Pipeline (M1-M4)

        将平仓交易构建为episode文件，执行L4全链路：
        M1(复盘) → M2(蒸馏) → M3(统计) → M3.5(KG同步) → M4(候选)
        """
        if not saved or not case_id:
            return

        import json
        from datetime import datetime

        # 构建episode文件
        episode = {
            "case_id": case_id,
            "ts": trade_rec.exit_time
            or trade_rec.entry_time
            or datetime.now(timezone.utc).isoformat(),
            "regime": getattr(trade_rec, "regime", "unknown") or "unknown",
            "summary": {
                "total_pnl": trade_rec.pnl,
                "wins": 1 if trade_rec.pnl > 0 else 0,
                "losses": 0 if trade_rec.pnl > 0 else 1,
                "total_trades": 1,
            },
            "trades": [
                {
                    "trade_id": case_id,
                    "symbol": trade_rec.inst_id,
                    "inst_id": trade_rec.inst_id,
                    "direction": (
                        trade_rec.direction.upper()
                        if isinstance(trade_rec.direction, str)
                        else "LONG"
                    ),
                    "entry_price": trade_rec.entry_price,
                    "exit_price": trade_rec.exit_price,
                    "position_size": getattr(trade_rec, "position_size", 0.01),
                    "leverage": getattr(trade_rec, "leverage", 10),
                    "margin_usdt": getattr(trade_rec, "margin_usdt", 100),
                    "pnl": trade_rec.pnl,
                    "pnl_pct": trade_rec.pnl_pct,
                    "exit_reason": trade_rec.exit_reason or "unknown",
                    "ts_entry": trade_rec.entry_time,
                    "ts_exit": trade_rec.exit_time,
                    "system_source": "yijing_inference",
                    "decision_context": {
                        "confidence": trade_rec.confidence,
                        "hexagram": trade_rec.hexagram or "",
                    },
                    "market_snapshot": {
                        "regime": getattr(trade_rec, "regime", "unknown") or "unknown",
                    },
                    "risk_events": [],
                }
            ],
        }

        # 保存episode文件
        episodes_dir = _episodes_dir()
        episodes_dir.mkdir(parents=True, exist_ok=True)
        ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        ep_path = episodes_dir / f"live_{trade_rec.inst_id}_{ts_str}.json"
        ep_path.write_text(json.dumps(episode, ensure_ascii=False, indent=2, default=str))

        self._log(f"[L4] Episode保存: {ep_path.name}")

        # 异步执行L4 Pipeline (M1-M4)
        try:
            from scripts.memory_l4.pipeline import run_pipeline

            result = run_pipeline(ep_path)
            l4_status = result.get("case", {}).get("l4_status", "unknown")
            self._log(f"[L4] Pipeline完成: case={case_id} status={l4_status}")
        except Exception as e:
            self._log(f"[L4] Pipeline执行失败: {e}", "WARN")

    # ===== P1-1: 做空趋势过滤器 =====
    # 加密货币用BTC趋势确认（参考V15马丁策略DirectionGate力学化模式）
    # 非加密货币用自身日MA50趋势（未来可升级为标普500趋势线过滤）
    CRYPTO_COINS = frozenset({
        "BTC", "SOL", "UNI", "OKB", "HYPE", "PUMP",
    })

    # 美股代币（OKX 上以 USDT-SWAP 交易的美股代币化合约）
    # 做空这些币种时需要纳斯达克/标普500大盘趋势确认
    US_STOCK_COINS = frozenset({
        "AAPL", "AMZN", "GOOGL", "NVDA", "MSFT", "TSLA",
        "META", "NFLX", "BABA", "MU", "SKHYNIX", "SNDK", "SPCX",
        "COIN", "MSTR", "PLTR", "CRCL", "BMNR",
    })

    @staticmethod
    def _ma_spring_force(price: float, ma: float, k: float = 2.0) -> float:
        """双均线弹簧力：F = -k × (price - MA) / MA

        符号语义:
          F > 0 → 做多倾向（价格在MA下方时，MA作为支撑，弹簧向上推）
          F < 0 → 做空倾向（价格在MA上方时，MA作为阻力，弹簧向下压）
        来源: V15 direction_gate._ma_spring_force
        """
        if ma is None or ma <= 0:
            return 0.0
        return -k * (price - ma) / ma

    @staticmethod
    def _distance_weight(abs_dist_pct: float) -> float:
        """距离权重函数: w = 1 / (1 + |dist%|)

        距离越近权重越大 → 价格接近周MA200时，周线支撑权重大 → 偏见底
        来源: V15 direction_gate._distance_weight
        """
        return 1.0 / (1.0 + abs(abs_dist_pct))

    def _calc_ma_slope(self, closes: list, period: int, window: int = 5) -> float:
        """计算 MA 的斜率（线性回归法）

        取最近 window 期的 MA 值序列，做线性回归求斜率。
        返回归一化百分比斜率: slope_pct = slope / MA_current * 100

        物理含义: MA 斜率 = 均线（均衡位置）的运动速度
          slope > 0 → 均线上升 → 做多势能方向
          slope < 0 → 均线下降 → 做空势能方向
        """
        if len(closes) < period + window:
            return 0.0
        # 取最近 window 期的 MA 值（从当前往前推）
        # closes[0]=最新, closes[1]=1日前...
        # ma_series[0] = MA(t), ma_series[1] = MA(t-1), ..., ma_series[n-1] = MA(t-n+1)
        ma_series = []
        for i in range(window):
            if len(closes) - i >= period:
                ma_series.append(sum(closes[i:i+period]) / period)
        if len(ma_series) < 2:
            return 0.0
        # 反转序列使 x 轴方向正确: x=0=最旧, x=n-1=最新
        # 这样 bear 趋势（MA 下降）→ slope < 0；bull 趋势（MA 上升）→ slope > 0
        ma_series = ma_series[::-1]
        # 线性回归: y = a + b*x, 求 b (slope)
        n = len(ma_series)
        x_mean = (n - 1) / 2.0  # 0..n-1 的均值
        y_mean = sum(ma_series) / n
        numerator = sum((i - x_mean) * (ma_series[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        if denominator == 0 or y_mean == 0:
            return 0.0
        slope = numerator / denominator
        # 归一化为百分比: slope_pct = slope / MA_current * 100
        return slope / y_mean * 100

    def _calc_5ma_spring_force(self, closes: list, k: float = 2.0,
                                 tier: str = "daily_btc") -> dict:
        """五均线分层弹簧力场 + 均线多空排列评分（Phase C++ 动态升级）

        核心改进（Phase C++ 新增三个维度）:
          ① inter-MA力: F_inter = -k_inter × (MA_short - MA_long) / MA_long
             → 均线排列本身产生趋势力（不是只看价格位置）
          ② MA斜率调制k: k_eff = k × (1 + α × tanh(slope_norm))
             → MA上升时趋势方向弹簧更硬（不易反弹），MA下降时反之
          ③ 势能: U = ½ × k × x²
             → 量化蓄势程度（偏离大=蓄势多，即将释放）

        原有结构:
          短中期组(MA30/MA65, w=0.35) + 中期组(MA128/MA200, w=0.40)
          + 长期组(MA1400≈周MA200, w=0.25)

        均线多空排列评分 bearish_score:
          STRONG: 5均线严格空头排列 + 3日跌破MA30
          NORMAL: 3~4均线空头 + 3日跌破确认
          WEAK  : 1~2均线短周期空头 + 3日跌破确认

        Arguments:
            closes: newest-first list of close prices
            k: spring constant (default 2.0)
            tier: "daily_btc" / "daily_self" / "daily_index"

        Returns:
            dict with keys:
              F_net, F_inter_net, F_total,
              U_potential (势能), slope_avg (平均MA斜率),
              spring_details, group_details, inter_ma_details,
              bearish_score, bearish_n, valid_breakdown,
              current_price, ma_values, ma_slopes, tier
        """
        if not closes:
            return {"F_net": 0.0, "F_total": 0.0, "bearish_score": "NONE", "bearish_n": 0}

        # 1. 取各层级 MA 周期（按 tier 自适应）
        ma_periods = [30, 65, 128, 200]
        if tier in ("daily_btc", "daily_self", "daily_index"):
            ma_periods.append(min(1400, len(closes)))
        actual_periods = [p for p in ma_periods if len(closes) >= p + 1]
        if len(actual_periods) < 2:
            return {"F_net": 0.0, "F_total": 0.0, "bearish_score": "NONE", "bearish_n": 0,
                    "error": f"closes太少({len(closes)})"}

        current_price = closes[0]
        ma_values = {}
        for p in actual_periods:
            ma_values[f"ma{p}"] = sum(closes[:p]) / p

        # ① 计算每条 MA 的斜率（线性回归法）
        ma_slopes = {}
        for p in actual_periods:
            ma_slopes[f"ma{p}"] = self._calc_ma_slope(closes, p, self.FMA_SLOPE_WINDOW)
        slope_avg = sum(ma_slopes.values()) / len(ma_slopes) if ma_slopes else 0.0

        # ② 斜率调制 k → k_eff
        # k_eff = k × (1 + α × tanh(slope_norm))
        # tanh 保证调制幅度有界 [-1, 1]
        import math
        slope_modulation = 1.0 + self.FMA_SLOPE_ALPHA * math.tanh(slope_avg / 0.5)  # 0.5% 作为归一化基准
        k_eff = k * slope_modulation

        # 2. 分组（按周期长度聚类）
        def _p_from_key(k_str: str) -> int:
            return int(k_str.replace("ma", ""))

        group_short = {p: v for p, v in ma_values.items() if _p_from_key(p) < 80}
        group_mid   = {p: v for p, v in ma_values.items() if 80 <= _p_from_key(p) < 1000}
        group_long  = {p: v for p, v in ma_values.items() if _p_from_key(p) >= 1000}
        group_weights_config = {
            "short": self.FMA_GROUP_WEIGHT_SHORT,
            "mid":   self.FMA_GROUP_WEIGHT_MID,
            "long":  self.FMA_GROUP_WEIGHT_LONG,
        }

        # 3. 每个组内按距离权重分配组内权重（使用 k_eff 代替 k）
        def _group_internal(group_dict):
            items = []
            for p_str, ma in group_dict.items():
                dist_pct = (current_price - ma) / ma * 100
                F = -k_eff * (current_price - ma) / ma  # ← 使用 k_eff
                w = self._distance_weight(abs(dist_pct))
                p = _p_from_key(p_str)
                slope = ma_slopes.get(p_str, 0.0)
                items.append((p, p_str, ma, dist_pct, F, w, slope))
            w_sum = sum(i[5] for i in items) if items else 1.0
            internal = []
            for p, p_str, ma, d, F, w, slope in items:
                internal.append((p, p_str, ma, d, F, w, slope, w/w_sum if w_sum else 0.0))
            return internal

        short_items = _group_internal(group_short)
        mid_items   = _group_internal(group_mid)
        long_items  = _group_internal(group_long)

        # 4. 计算 F_net（price-to-MA 回复力，使用 k_eff）
        F_net = 0.0
        group_details = {}
        for name, items, gw_cfg in [
            ("short", short_items, group_weights_config["short"]),
            ("mid",   mid_items,   group_weights_config["mid"]),
            ("long",  long_items,  group_weights_config["long"]),
        ]:
            if not items:
                continue
            contrib = 0.0
            for p, _pstr, _ma, _d, F, _w, _slope, internal_pct in items:
                effective_w = gw_cfg * internal_pct
                contrib += F * effective_w
            F_net += contrib
            group_details[name] = contrib

        # ① inter-MA力：均线间相对距离产生趋势力
        # F_inter = -k_inter × (MA_short - MA_long) / MA_long
        # MA_short > MA_long → F_inter < 0（多头排列→做多方向力）
        # MA_short < MA_long → F_inter > 0（空头排列→做空方向力）
        k_inter = k_eff * self.FMA_INTER_K_RATIO
        F_inter_net = 0.0
        inter_ma_details = {}

        # 组内 inter-MA（如 MA30 vs MA65, MA128 vs MA200）
        for name, items in [("short", short_items), ("mid", mid_items), ("long", long_items)]:
            if len(items) < 2:
                continue
            # 按 MA 周期排序（短在前）
            sorted_items = sorted(items, key=lambda x: x[0])
            for i in range(len(sorted_items) - 1):
                p1, p_str1, ma1 = sorted_items[i][0], sorted_items[i][1], sorted_items[i][2]
                p2, p_str2, ma2 = sorted_items[i+1][0], sorted_items[i+1][1], sorted_items[i+1][2]
                inter_dist = (ma1 - ma2) / ma2  # 短周期 - 长周期
                F_inter = -k_inter * inter_dist
                gw = group_weights_config.get(name, 0.3)
                F_inter_net += F_inter * gw
                inter_ma_details[f"{p_str1}-{p_str2}"] = {
                    "inter_dist%": round(inter_dist * 100, 2),
                    "F_inter": round(F_inter, 4),
                    "direction": "多头排列(短>长)" if inter_dist > 0 else "空头排列(短<长)",
                }

        # 跨组 inter-MA（组间最近邻：MA65 vs MA128, MA200 vs MA1400）
        cross_pairs = []
        if short_items and mid_items:
            cross_pairs.append((max(short_items, key=lambda x: x[0]),
                                min(mid_items, key=lambda x: x[0]), "short-mid"))
        if mid_items and long_items:
            cross_pairs.append((max(mid_items, key=lambda x: x[0]),
                                min(long_items, key=lambda x: x[0]), "mid-long"))
        for item1, item2, cross_name in cross_pairs:
            p1, p_str1, ma1 = item1[0], item1[1], item1[2]
            p2, p_str2, ma2 = item2[0], item2[1], item2[2]
            inter_dist = (ma1 - ma2) / ma2
            F_inter = -k_inter * inter_dist
            F_inter_net += F_inter * 0.15  # 跨组权重 0.15
            inter_ma_details[f"{p_str1}-{p_str2}"] = {
                "inter_dist%": round(inter_dist * 100, 2),
                "F_inter": round(F_inter, 4),
                "direction": "多头排列(短>长)" if inter_dist > 0 else "空头排列(短<长)",
            }

        # F_total = F_net（回复力）+ F_inter_net（趋势力）
        F_total = F_net + F_inter_net

        # ③ 势能 U = ½ × k_eff × x²（x = 归一化偏离）
        # U_potential: 总势能（含所有组，用于日志/调试）
        # U_short: 仅短期组(MA30/65)势能，用于超卖检测（价格离即时均衡的距离）
        #   原因：趋势市中价格远离长期MA是正常现象，不应触发超卖过滤
        U_potential = 0.0
        U_short = 0.0
        for name, items, gw_cfg in [
            ("short", short_items, group_weights_config["short"]),
            ("mid",   mid_items,   group_weights_config["mid"]),
            ("long",  long_items,  group_weights_config["long"]),
        ]:
            if not items:
                continue
            for p, _pstr, ma, _d, _F, _w, _slope, internal_pct in items:
                x = (current_price - ma) / ma  # 归一化偏离
                U_i = 0.5 * k_eff * x * x
                U_potential += U_i * gw_cfg * internal_pct
                if name == "short":
                    U_short += U_i * gw_cfg * internal_pct

        # 5. 均线多空排列评分 bearish_score（保持原有逻辑）
        below_count = 0
        for _, ma in ma_values.items():
            if current_price <= ma:
                below_count += 1

        # 5b) 跌破确认：3日收盘价 ≤ 最短期被跌破均线
        mas_sorted_by_val = sorted(ma_values.items(), key=lambda x: -x[1])
        all_passes = [ma for _, ma in mas_sorted_by_val if current_price <= ma]
        if all_passes:
            highest_broken_ma = max(all_passes)
            recent_n = min(self.FMA_SHORT_TIER_BREAKDOWN_BARS, len(closes))
            valid_breakdown = all(closes[i] <= highest_broken_ma for i in range(recent_n))
        else:
            valid_breakdown = False

        # 5b2) MA128 专属3日跌破确认（双轨方案：趋势市简化两均线过滤用）
        #   传统金融定义：3日收盘价 ≤ MA128 → 有效跌破 → 熊市确认
        ma128_val = ma_values.get("ma128")
        if ma128_val and len(closes) >= self.FMA_SHORT_TIER_BREAKDOWN_BARS:
            valid_breakdown_ma128 = all(
                closes[i] <= ma128_val
                for i in range(self.FMA_SHORT_TIER_BREAKDOWN_BARS)
            )
        else:
            valid_breakdown_ma128 = False

        # 5c) 排列类型
        mas_list = sorted(ma_values.items(), key=lambda x: x[1])
        ascending = all(mas_list[i][1] <= mas_list[i+1][1] for i in range(len(mas_list)-1))
        all_strictly = current_price < mas_list[0][1] if mas_list else False
        strict_bearish = ascending and all_strictly and len(mas_list) >= 3
        strict_bullish = all(current_price > ma for _, ma in mas_list) and len(mas_list) >= 3

        # 5d) 评分映射（增加势能辅助）
        if strict_bearish and valid_breakdown and len(mas_list) >= 4:
            bearish_score = "STRONG"
        elif below_count >= 3 and valid_breakdown:
            bearish_score = "NORMAL"
        elif below_count >= 1 and valid_breakdown:
            bearish_score = "WEAK"
        else:
            bearish_score = "NONE"

        # 6. 偏见底窗口
        in_long_term_window = False
        if group_long:
            for p, ma in group_long.items():
                dist = abs(current_price - ma) / ma
                if dist <= self.FMA_LONG_TERM_BOTTOM_BUFFER:
                    in_long_term_window = True
                    break

        # spring_details（增加斜率和势能）
        spring_details = {}
        for items in [short_items, mid_items, long_items]:
            for p, p_str, ma, d, F, _w, slope, _ in items:
                x = (current_price - ma) / ma
                U_i = 0.5 * k_eff * x * x
                spring_details[p_str] = {
                    "value": round(ma, 2), "dist%": round(d, 2),
                    "F": round(F, 4), "role": "支撑" if current_price > ma else "阻力",
                    "slope%": round(slope, 4),
                    "U": round(U_i, 6),
                }

        # ④ F_dot：F_total 的变化率（趋势加速度）
        # F_dot = F_total(t) - F_total(t-1)
        # 需要 t-1 时刻的 F_total，用 closes[1] 代替 closes[0] 重新计算
        F_dot = 0.0
        if len(closes) >= 2:
            prev_closes = closes[1:]  # 去掉最新一根
            if len(prev_closes) >= max(actual_periods) + 1:
                prev_res = self._calc_5ma_spring_force(prev_closes, k=k, tier=tier)
                F_dot = F_total - prev_res.get("F_total", F_total)

        # ⑤ Phase D：4维度市场形态判定（Market Regime Classification）
        # 维度1: 趋势强度比 TR = |F_inter| / (|F_net_short| + |F_inter| + ε)
        #   仅用短期组F_net（价格vs MA30/65的回复力），不含长期MA偏离
        #   原因：趋势市中价格远离长期MA是正常现象，不应让长期偏离压低TR
        #   高 TR → 均线排列主导（趋势市）；低 TR → 价格偏离主导（均值回归）
        eps_tr = 1e-6
        F_net_short = group_details.get("short", 0.0)
        abs_F_net_short = abs(F_net_short)
        abs_F_inter = abs(F_inter_net)
        trend_ratio = abs_F_inter / (abs_F_net_short + abs_F_inter + eps_tr)

        # 维度2: 均线发散度 CV = std(MA30/65/128/200) / mean
        #   仅用可比较的 MA 值，避免长期 MA 缺失导致 CV 失真
        cv_ma_keys = [k for k in ("ma30", "ma65", "ma128", "ma200") if k in ma_values]
        cv_dispersion = 0.0
        if len(cv_ma_keys) >= 2:
            cv_vals = [ma_values[k] for k in cv_ma_keys]
            cv_mean = sum(cv_vals) / len(cv_vals)
            if cv_mean > 0:
                cv_var = sum((v - cv_mean) ** 2 for v in cv_vals) / len(cv_vals)
                cv_dispersion = (cv_var ** 0.5) / cv_mean

        # 维度3: 斜率强度 abs_slope = |slope_avg|
        abs_slope = abs(slope_avg)

        # 维度4: F_dot（已计算）

        # 形态分类器（优先级：多头趋势 > 强空头趋势 > 弱空头趋势 > 均值回归 > 震荡）
        # 多头趋势：F_inter < 0（均线多头排列）+ 斜率向上 + 发散
        if (F_inter_net < 0 and abs_slope > self.FMA_REGIME_SLOPE_TREND
                and trend_ratio > self.FMA_REGIME_TR_TREND
                and cv_dispersion > self.FMA_REGIME_CV_TREND):
            market_regime = "TREND_BULL"
        # 强空头趋势：TR 高 + CV 发散 + 斜率向下 + F_dot 偏离加速
        elif (F_inter_net > 0 and trend_ratio > self.FMA_REGIME_TR_STRONG
                and cv_dispersion > self.FMA_REGIME_CV_STRONG
                and abs_slope > self.FMA_REGIME_SLOPE_STRONG
                and slope_avg < 0
                and F_dot > self.FMA_REGIME_FDOT_STRONG):
            market_regime = "STRONG_TREND_BEAR"
        # 弱空头趋势：TR 中高 + CV 略发散 + 斜率向下
        elif (F_inter_net > 0 and trend_ratio > self.FMA_REGIME_TR_TREND
                and cv_dispersion > self.FMA_REGIME_CV_TREND
                and abs_slope > self.FMA_REGIME_SLOPE_TREND
                and slope_avg < 0):
            market_regime = "TREND_BEAR"
        # 均值回归：TR 低 + CV 纠缠 + F_dot 收敛
        elif (trend_ratio < self.FMA_REGIME_TR_REVERT
                and cv_dispersion < self.FMA_REGIME_CV_REVERT
                and F_dot < self.FMA_REGIME_FDOT_REVERT):
            market_regime = "MEAN_REVERTING"
        # 震荡/筑底：剩余情况
        else:
            market_regime = "RANGING"

        return {
            "tier": tier,
            "F_net": F_net,                    # price-to-MA 回复力（全部组）
            "F_net_short": round(F_net_short, 4),  # 短期组回复力（用于TR计算）
            "F_inter_net": F_inter_net,        # inter-MA 趋势力
            "F_total": F_total,                # 总力 = F_net + F_inter_net
            "F_dot": F_dot,                    # F_total 变化率（趋势加速度）
            "U_potential": U_potential,        # 弹性势能（全部组，日志/调试用）
            "U_short": round(U_short, 6),      # 短期组势能（超卖检测用）
            "slope_avg": slope_avg,            # 平均MA斜率
            "k_eff": k_eff,                     # 调制后的弹簧系数
            "spring_details": spring_details,
            "group_details": {k: round(v, 4) for k, v in group_details.items()},
            "inter_ma_details": inter_ma_details,
            "bearish_score": bearish_score,
            "bearish_n": below_count,
            "valid_breakdown": valid_breakdown,
            "valid_breakdown_ma128": valid_breakdown_ma128,  # MA128专属3日跌破确认（双轨方案）
            "current_price": current_price,
            "ma_values": {k: round(v, 2) for k, v in ma_values.items()},
            "ma_slopes": {k: round(v, 4) for k, v in ma_slopes.items()},
            "strict_bearish": strict_bearish,
            "strict_bullish": strict_bullish,
            "in_long_term_window": in_long_term_window,
            # Phase D 形态判定输出
            "trend_ratio": round(trend_ratio, 4),           # 趋势强度比 TR
            "cv_dispersion": round(cv_dispersion, 4),        # 均线发散度 CV
            "abs_slope": round(abs_slope, 4),               # 斜率强度
            "market_regime": market_regime,                 # 形态分类
            "threshold": 0.02,
        }

    def _trend_regime_short_filter(self, ma_values: dict, current_price: float,
                                     valid_bd_ma128: bool) -> tuple:
        """双轨方案：趋势市简化两均线过滤（MA128 + 周线MA200）

        传统金融逻辑：
          - 价格 > MA128 → 牛市/反弹，禁止做空
          - 3日收盘 ≤ MA128（有效跌破）→ 熊市确认
          - 接近周线MA200 ±N% → 熊市底部，禁止做空（可能反弹）
          - 熊市中且远离周线MA200 → 允许做空

        Args:
            ma_values: {"ma128": ..., "ma1400": ...} (ma1400 ≈ 周线MA200)
            current_price: 当前价格
            valid_bd_ma128: MA128 的3日跌破确认

        Returns:
            (allow_short: bool, reason_tag: str)
        """
        ma128 = ma_values.get("ma128")
        ma200_week = ma_values.get("ma1400")  # 周线MA200 ≈ 日线MA1400

        # 1) 数据不足 → 保守禁止
        if not ma128:
            return False, "趋势市 MA128数据缺失"

        # 2) 价格 > MA128 → 牛市/反弹，禁止做空
        if current_price > ma128:
            return False, f"趋势市 价({current_price:.0f})>MA128({ma128:.0f}) 牛市/反弹"

        # 3) 未有效跌破 MA128（3日收盘 < MA128）→ 跌破未确认
        if not valid_bd_ma128:
            return False, "趋势市 MA128未有效跌破(3日收盘<MA128)"

        # 4) 接近周线MA200 ±N% → 熊市底部，禁止做空
        if ma200_week:
            dist_to_bottom = abs(current_price - ma200_week) / ma200_week
            if dist_to_bottom <= self.FMA_LONG_TERM_BOTTOM_BUFFER:
                return False, (f"趋势市 接近周线MA200底部(价={current_price:.0f}"
                               f"≈MA1400({ma200_week:.0f})±{self.FMA_LONG_TERM_BOTTOM_BUFFER*100:.0f}%)")

        # 5) 熊市中且远离周线MA200 → 允许做空
        bottom_str = f" 距周线MA200({ma200_week:.0f})={((current_price-ma200_week)/ma200_week*100):+.1f}%" if ma200_week else ""
        return True, f"趋势市 熊市做空(价<MA128有效跌破){bottom_str}"

    def _regime_short_filter(self, regime: str, score: str, U: float,
                              F_dot: float, valid_bd: bool,
                              ma_values: dict = None,
                              current_price: float = 0.0,
                              valid_bd_ma128: bool = False) -> tuple:
        """Phase D 形态差异化做空过滤（双轨方案）

        双轨分流：
          - 趋势市（TREND_BULL/STRONG_TREND_BEAR/TREND_BEAR）→ 两均线简化过滤
          - 均值回归/震荡（MEAN_REVERTING/RANGING）→ 多均线差异化过滤

        Returns:
            (allow_short: bool, reason_tag: str)
        """
        # 多头趋势：任何情况都不做空
        if regime == "TREND_BULL":
            return False, "TREND_BULL 禁止做空"
        if regime == "STRONG_TREND_BULL":
            return False, "STRONG_TREND_BULL 禁止做空"

        # 趋势市（强空头/弱空头）→ 走两均线简化过滤
        if regime in ("STRONG_TREND_BEAR", "TREND_BEAR"):
            if not ma_values or current_price <= 0:
                return False, f"{regime} 缺少ma_values/current_price参数"
            allow, trend_reason = self._trend_regime_short_filter(
                ma_values=ma_values,
                current_price=current_price,
                valid_bd_ma128=valid_bd_ma128,
            )
            prefix = "STRONG_TREND_BEAR" if regime == "STRONG_TREND_BEAR" else "TREND_BEAR"
            return allow, f"{prefix} | {trend_reason}"

        # 均值回归：严格（F>0 = 超卖 = 禁止做空）
        if regime == "MEAN_REVERTING":
            if not valid_bd:
                return False, "MEAN_REVERTING 无3日跌破确认"
            if score not in self.FMA_ALLOW_SCORE_REVERT:
                return False, f"MEAN_REVERTING 仅WEAK允许，score={score}"
            if U > self.FMA_U_THRESHOLD_REVERT:
                return False, f"MEAN_REVERTING 超卖 U={U:.5f}>{self.FMA_U_THRESHOLD_REVERT}"
            if F_dot < self.FMA_FDOT_REVERT:
                return False, f"MEAN_REVERTING 收敛 F_dot={F_dot:.4f}<{self.FMA_FDOT_REVERT}"
            return True, "MEAN_REVERTING 谨慎做空（仅WEAK档）"

        # 震荡/筑底：放宽（回测胜率 68.6% 最高，允许全档位）
        if regime == "RANGING":
            if not valid_bd:
                return False, "RANGING 无3日跌破确认"
            if score not in self.FMA_ALLOW_SCORE_RANGE:
                return False, f"RANGING score={score} 未达档"
            if U > self.FMA_U_THRESHOLD_RANGE:
                return False, f"RANGING 超卖 U={U:.5f}>{self.FMA_U_THRESHOLD_RANGE}"
            if F_dot < self.FMA_FDOT_RANGE:
                return False, f"RANGING 收敛 F_dot={F_dot:.4f}<{self.FMA_FDOT_RANGE}"
            return True, "RANGING 放宽做空（全档位+低U+加速）"

        return False, f"未知 regime={regime}"

    def _regime_long_filter(self, regime: str, bullish_score: str,
                             U_long: float, F_dot: float,
                             valid_breakout_up: bool,
                             ma_values: dict = None,
                             current_price: float = 0.0) -> tuple:
        """Phase D 形态差异化做多过滤（与 _regime_short_filter 对称；FMA=ON 影子路径专用）。

        Returns:
            (allow_long: bool, reason_tag: str)
        """
        if not bullish_score or bullish_score == "NONE":
            return False, f"bullish_score={bullish_score} 未达档"

        # 熊市趋势：任何情况都不追多
        if regime in ("TREND_BEAR", "STRONG_TREND_BEAR"):
            return False, f"{regime} 熊市禁止追多"

        # 多头趋势 → 对称做空两均线过滤：要求价格>MA128 + 有效向上突破
        if regime in ("TREND_BULL", "STRONG_TREND_BULL"):
            if not ma_values or current_price <= 0:
                return False, f"{regime} 缺少ma_values/current_price参数"
            ma128 = float(ma_values.get("ma128", 0) or 0)
            if ma128 <= 0:
                return False, f"{regime} 缺少ma128"
            if current_price <= ma128:
                return False, f"{regime} 价格{current_price:.2f}≤MA128={ma128:.2f}(未站在牛市上方)"
            prefix = "STRONG_TREND_BULL" if regime == "STRONG_TREND_BULL" else "TREND_BULL"
            # STRONG档允许放宽U限制；NORMAL档需要当前价不破MA128
            allow_scores = ("STRONG", "NORMAL") if regime == "STRONG_TREND_BULL" else ("STRONG", "NORMAL", "WEAK")
            if bullish_score not in allow_scores:
                return False, f"{prefix} bullish_score={bullish_score} 未达档"
            return True, f"{prefix} 趋势牛市做多（价>MA128站在牛线上）"

        # 均值回归：严格（F<0 = 超买 → 禁止追多；仅刚从下跌拐头向上突破允许）
        if regime == "MEAN_REVERTING":
            if not valid_breakout_up:
                return False, "MEAN_REVERTING 无3日向上突破确认"
            if bullish_score not in ("WEAK",):
                return False, f"MEAN_REVERTING 仅WEAK档允许（刚拐头），score={bullish_score}"
            if U_long > self.FMA_U_THRESHOLD_REVERT:
                return False, f"MEAN_REVERTING 超买 U={U_long:.5f}>{self.FMA_U_THRESHOLD_REVERT}"
            if F_dot > self.FMA_FDOT_REVERT:  # 反向：F_dot>0 表示F收敛（回落压力）→ 禁止
                return False, f"MEAN_REVERTING 回落收敛 F_dot={F_dot:.4f}>{self.FMA_FDOT_REVERT}"
            return True, "MEAN_REVERTING 保守做多（仅WEAK档+拐头向上）"

        # 震荡/筑底：放宽（回测 RANGING 胜率最高）
        if regime == "RANGING":
            if bullish_score not in self.FMA_ALLOW_SCORE_RANGE:
                return False, f"RANGING bullish_score={bullish_score} 未达档"
            if U_long > self.FMA_U_THRESHOLD_RANGE:
                return False, f"RANGING 超买 U={U_long:.5f}>{self.FMA_U_THRESHOLD_RANGE}"
            # RANGING 不严格要求 3日向上突破（震荡区间内上下均可）
            return True, "RANGING 放宽做多（震荡区间内尝试）"

        return False, f"未知 regime={regime}"

    def _check_btc_trend(self, _force_regime_filter_on: bool = False) -> tuple:
        """BTC日线趋势判定（Phase D：形态差异化做空过滤）

        核心改进：
          1. 4维度市场形态判定 → 5种 regime（TREND_BULL/STRONG_TREND_BEAR/TREND_BEAR/MEAN_REVERTING/RANGING）
          2. 按 regime 走差异化做空过滤阈值（解决弹簧力 F 双重身份问题）：
             - 趋势市：F>0 = 均线阻力 = 顺势做空（宽松，U阈值放宽）
             - 均值回归市：F>0 = 超卖 = 禁止做空（严格，U阈值收紧）
          3. 兜底：价格在长期MA ±2% 的窄窗口 → 偏见底，禁止做空

        Returns:
            (bearish: bool, reason: str — 末尾附 SHORT_ALLOWED + regime + score)
        """
        now = time.time()
        cached = self._btc_trend_cache
        if cached["result"] and (now - cached["ts"]) < 300:
            return cached["result"]

        try:
            btc_klines = _load_kline_from_okx(inst_id="BTC-USDT-SWAP", bar="1D", limit=1500)
            if not btc_klines or len(btc_klines) < 131:
                result = (False, f"BTC日线数据不足(limit={len(btc_klines) if btc_klines else 0})")
                self._btc_trend_cache = {"ts": now, "result": result}
                return result

            closes = [float(k.get("c", 0)) for k in btc_klines if k.get("c")]
            if len(closes) < 131:
                result = (False, f"BTC收盘价不足({len(closes)})")
                self._btc_trend_cache = {"ts": now, "result": result}
                return result

            res = self._calc_5ma_spring_force(closes, tier="daily_btc")

            F_total = res.get("F_total", res.get("F_net", 0.0))
            F_net = res.get("F_net", 0.0)
            F_inter = res.get("F_inter_net", 0.0)
            U_total = res.get("U_potential", 0.0)
            U_short = res.get("U_short", 0.0)
            slope_avg = res.get("slope_avg", 0.0)
            k_eff = res.get("k_eff", 2.0)
            score = res["bearish_score"]
            in_bottom = res["in_long_term_window"]
            F_dot = res.get("F_dot", 0.0)
            regime = res.get("market_regime", "RANGING")
            TR = res.get("trend_ratio", 0.0)
            CV = res.get("cv_dispersion", 0.0)

            # 构造简短日志
            mav = res["ma_values"]
            bd_summary = f"{res['bearish_n']}/5均线被跌破 score={score}"
            breakdown_tag = "3日跌破确认" if res["valid_breakdown"] else "无3日确认"
            roles_summary = " ".join(
                f"MA{p}={'支' if current_price>ma else '阻'}"
                for p, ma in sorted(mav.items(), key=lambda x: int(x[0].replace('ma','')))
                for current_price in [res["current_price"]]  # one-shot hack
            )
            # Phase D 动态信息（含形态判定4维度）
            dynamics = (f"regime={regime} TR={TR:.3f} CV={CV:.4f}"
                        f" F_total={F_total:+.3f}(F_net={F_net:+.3f}+F_inter={F_inter:+.3f})"
                        f" F_dot={F_dot:+.4f}"
                        f" U_short={U_short:.5f}(U_total={U_total:.5f})"
                        f" slope={slope_avg:+.3f}% k_eff={k_eff:.2f}")

            # 5) 兜底：长期MA ±2% 偏见底
            if in_bottom:
                long_ma = min([ma for p, ma in mav.items() if int(p.replace('ma','')) >= 1000] or [0])
                result = (
                    False,
                    f"BTC长期均线偏见底(价={res['current_price']:.0f}≈MA{int(long_ma) if long_ma else '?'}±{self.FMA_LONG_TERM_BOTTOM_BUFFER*100:.0f}%)"
                    f" | {dynamics} | {bd_summary} | {breakdown_tag}"
                )
                self._btc_trend_cache = {"ts": now, "result": result}
                return result

            # 6) 做空过滤：开关控制
            #    FMA_REGIME_FILTER_ENABLED=False（默认）→ 简单趋势确认
            #    FMA_REGIME_FILTER_ENABLED=True         → 形态差异化过滤（实验用）
            #    _force_regime_filter_on=True           → 强制走形态差异化（H3-FMA影子决策专用，即便当前全局OFF）
            fma_switch = bool(self.FMA_REGIME_FILTER_ENABLED) or bool(_force_regime_filter_on)
            if fma_switch:
                # 形态差异化过滤（双轨方案，回测效果不佳，仅实验用）
                allow_short, filter_reason = self._regime_short_filter(
                    regime=regime,
                    score=score,
                    U=U_short,
                    F_dot=F_dot,
                    valid_bd=res["valid_breakdown"],
                    ma_values=mav,
                    current_price=res["current_price"],
                    valid_bd_ma128=res.get("valid_breakdown_ma128", False),
                )
            else:
                # 无过滤（回测验证：无过滤胜率56.8% > 所有过滤方案，信号整体更好）
                # 历史方案：曾尝试3日跌破确认+price<MA128，均过滤掉高胜率信号
                allow_short, filter_reason = True, "无趋势过滤(回测验证最优)"

            if allow_short:
                result = (
                    True,
                    f"[SHORT_ALLOWED] BTC做空允许 {dynamics} | {bd_summary} | {breakdown_tag} | {roles_summary}"
                    f" | {filter_reason}"
                    f" | 价={res['current_price']:.0f} MA30={mav.get('ma30',0):.0f} MA65={mav.get('ma65',0):.0f}"
                    f" MA128={mav.get('ma128',0):.0f} MA200={mav.get('ma200',0):.0f}"
                )
            else:
                result = (
                    False,
                    f"BTC做空禁止 {dynamics} | {bd_summary} | {breakdown_tag} | {filter_reason}"
                )

            self._btc_trend_cache = {"ts": now, "result": result}
            return result
        except Exception as e:
            import traceback
            return False, f"BTC趋势检查异常: {e} | {traceback.format_exc(limit=1)}"

    def _check_self_trend(self, coin: str, _force_regime_filter_on: bool = False) -> tuple:
        """非加密货币自身日K线趋势（Phase D 形态差异化做空过滤）

        与 BTC 算法同构，用 MA30/65/128/200 + 可用长期均线；
        按 market_regime 走差异化做空过滤（与 _check_btc_trend 共用 _regime_short_filter）。

        Returns:
            (bearish: bool, reason: str — 若允许做空则含 SHORT_ALLOWED + regime + score)
        """
        try:
            inst_id = f"{coin}-USDT-SWAP"
            klines = _load_kline_from_okx(inst_id=inst_id, bar="1D", limit=1500)
            if not klines or len(klines) < 66:
                return False, f"{coin}日线数据不足(<66)"
            closes = [float(k.get("c", 0)) for k in klines if k.get("c")]
            if len(closes) < 66:
                return False, f"{coin}收盘价数据不足"

            res = self._calc_5ma_spring_force(closes, tier="daily_self")
            score = res["bearish_score"]
            F_net = res["F_net"]
            F_total = res.get("F_total", F_net)
            F_inter = res.get("F_inter_net", 0.0)
            U_total = res.get("U_potential", 0.0)
            U_short = res.get("U_short", 0.0)
            F_dot = res.get("F_dot", 0.0)
            regime = res.get("market_regime", "RANGING")
            TR = res.get("trend_ratio", 0.0)
            CV = res.get("cv_dispersion", 0.0)
            slope_avg = res.get("slope_avg", 0.0)

            dynamics = (f"regime={regime} TR={TR:.3f} CV={CV:.4f}"
                        f" F_total={F_total:+.3f}(F_net={F_net:+.3f}+F_inter={F_inter:+.3f})"
                        f" F_dot={F_dot:+.4f} U_short={U_short:.5f}(U_total={U_total:.5f})"
                        f" slope={slope_avg:+.3f}%")
            bd_summary = f"{res['bearish_n']}/N均线被跌破 score={score}"
            breakdown_tag = "3日跌破确认" if res["valid_breakdown"] else "无3日确认"

            # 长期MA兜底
            if res["in_long_term_window"]:
                mav = res["ma_values"]
                long_ma = min([ma for p, ma in mav.items() if int(p.replace('ma','')) >= 1000] or [0])
                return False, (
                    f"{coin}长期均线偏见底(价={res['current_price']:.2f}≈MA{long_ma if long_ma else '?'}"
                    f" ±{self.FMA_LONG_TERM_BOTTOM_BUFFER*100:.0f}%) | {dynamics} | {bd_summary}"
                )

            # 做空过滤：开关控制（与 _check_btc_trend 同构）
            _fma_on = bool(self.FMA_REGIME_FILTER_ENABLED) or bool(_force_regime_filter_on)
            if _fma_on:
                # 形态差异化过滤（双轨方案，回测效果不佳，仅实验用）
                allow_short, filter_reason = self._regime_short_filter(
                    regime=regime,
                    score=score,
                    U=U_short,
                    F_dot=F_dot,
                    valid_bd=res["valid_breakdown"],
                    ma_values=res["ma_values"],
                    current_price=res["current_price"],
                    valid_bd_ma128=res.get("valid_breakdown_ma128", False),
                )
            else:
                # 无过滤（与 _check_btc_trend 同构，回测验证无过滤最优）
                allow_short, filter_reason = True, "无趋势过滤(回测验证最优)"

            if allow_short:
                return True, (
                    f"[SHORT_ALLOWED] {coin}趋势看空 {dynamics} | {bd_summary} | {breakdown_tag}"
                    f" | {filter_reason} | 价={res['current_price']:.2f}"
                )
            return False, (
                f"{coin}做空禁止 {dynamics} | {bd_summary} | {breakdown_tag} | {filter_reason}"
            )
        except Exception as e:
            return False, f"{coin}趋势检查异常: {e}"

    def _check_us_index_trend(self, _force_regime_filter_on: bool = False) -> tuple:
        """美股大盘趋势判定（Phase C+ 两指数各五均线后平均）

        对 IXIC / GSPC 各自计算五均线评分，取 F 平均；任一指数 STRICT 空头排列即允许，
        平均 score≥WEAK+valid_breakdown 也允许。

        Returns:
            (bearish: bool, reason: str)
        """
        now = time.time()
        cached = getattr(self, "_us_index_trend_cache", None)
        if cached and cached.get("result") and (now - cached["ts"]) < 300:
            # _force_regime_filter_on=True 时不使用缓存（需要重跑 FMA=ON 差异化过滤）
            if not _force_regime_filter_on:
                return cached["result"]

        try:
            import yfinance as yf

            indices = {"IXIC": "^IXIC", "GSPC": "^GSPC"}
            results_idx = {}
            for name, ticker in indices.items():
                hist = yf.Ticker(ticker).history(period="5y")
                if hist.empty or len(hist) < 131:
                    continue
                closes_oa = list(hist["Close"].values)  # oldest-first
                closes_nf = closes_oa[::-1]              # newest-first
                res = self._calc_5ma_spring_force(closes_nf, tier="daily_index")
                results_idx[name] = res

            if not results_idx:
                result = (False, "美股大盘数据拉取失败(IXIC/GSPC均不可用)")
                self._us_index_trend_cache = {"result": result, "ts": now}
                return result

            # 任意一个 STRICT=STRONG → 允许
            any_strict = any(r["bearish_score"] == "STRONG" and r["valid_breakdown"]
                             for r in results_idx.values())
            # 或者 F_avg < -0.02 + score!=NONE + valid_breakdown → 允许
            F_avg = sum(r["F_net"] for r in results_idx.values()) / len(results_idx)
            any_weak_plus = any(r["bearish_score"] != "NONE" and r["valid_breakdown"]
                                for r in results_idx.values())
            # 任一长期均线触底 → 全部禁止
            any_bottom = any(r["in_long_term_window"] for r in results_idx.values())

            name_score = " ".join(
                f"{n}[score={r['bearish_score']} F={r['F_net']:+.3f}]"
                for n, r in results_idx.items()
            )

            if any_bottom:
                result = (False, f"美股大盘偏见底 | {name_score}")
            elif any_strict or (F_avg < -0.02 and any_weak_plus):
                result = (True, f"[SHORT_ALLOWED] 美股大盘趋势看空 F_avg={F_avg:+.3f} | {name_score}")
            else:
                result = (False, f"美股大盘无看空确认 F_avg={F_avg:+.3f} | {name_score}")

            self._us_index_trend_cache = {"result": result, "ts": now}
            return result
        except Exception as e:
            return False, f"美股大盘检查异常: {e}"

    def _parse_bearish_score_from_reason(self, reason: str) -> str:
        """从各类 trend reason 字符串中抽取 bearish_score（NONE/WEAK/NORMAL/STRONG）"""
        if not reason:
            return "NONE"
        import re
        # 新算法格式: score=STRONG / score=NORMAL / score=WEAK
        m = re.search(r"score=(STRONG|NORMAL|WEAK|NONE)", reason)
        if m:
            return m.group(1)
        return "NONE"

    def _compute_short_conf_multiplier(self, bearish_score: str) -> float:
        """根据 bearish_score 返回做空置信度乘数（有效阈值=基础阈值×乘数）

        STRONG(5均线严格空头): ×0.9091 ≈1/1.10 → 降低门槛（强趋势可放宽）
        NORMAL(3~4均线空头) : ×1.0000          → 标准
        WEAK(1~2均线短周期) : ×1.1765 ≈1/0.85  → 抬高门槛（弱趋势要求更高置信度）
        NONE                : ×0.00            → 直接禁止
        """
        if bearish_score == "STRONG":
            return self.SHORT_CONF_MULTI_MA_STRONG
        elif bearish_score == "NORMAL":
            return self.SHORT_CONF_MULTI_MA_NORMAL
        elif bearish_score == "WEAK":
            return self.SHORT_CONF_MULTI_MA_WEAK
        return 0.00

    def _get_regime_short_multiplier(self, regime: str) -> float:
        """根据 market_regime 返回做空阈值调节乘数（阈值调节器）

        理论：regime 反映市场形态，不同形态下做空胜率差异显著
              回测数据：TREND_BEAR 28.6% < STRONG_TREND_BEAR 50.0% < RANGING 68.6%
              乘数 > 1.0 = 抬高阈值 = 抑制做空；乘数 < 1.0 = 降低阈值 = 放宽做空

        与 bearish_score 乘数叠加使用：
            final_threshold = base_threshold × score_multiplier × regime_multiplier
        """
        mapping = {
            "TREND_BULL":         self.REGIME_SHORT_CONF_MULTI_TREND_BULL,
            "TREND_BEAR":         self.REGIME_SHORT_CONF_MULTI_TREND_BEAR,
            "STRONG_TREND_BEAR":  self.REGIME_SHORT_CONF_MULTI_STRONG_TREND_BEAR,
            "MEAN_REVERTING":     self.REGIME_SHORT_CONF_MULTI_MEAN_REVERTING,
            "RANGING":            self.REGIME_SHORT_CONF_MULTI_RANGING,
        }
        return mapping.get(regime, 1.00)

    def _parse_regime_from_reason(self, reason: str) -> str:
        """从 trend_reason 日志中解析 market_regime

        日志格式示例：
            "... regime=TREND_BEAR TR=0.599 ..."
            "... regime=RANGING TR=0.396 ..."
        """
        import re
        m = re.search(r"regime=(\w+)", reason)
        return m.group(1) if m else "RANGING"

    def _compute_short_position_multiplier(self, bearish_score: str) -> float:
        """根据 bearish_score 返回做空仓位规模乘数

        理论：周期越短可信度越低，但趋势识别越早 → 不禁开，而是控制资金规模
              随着跌破更多均线，弹簧压力越来越重 → 仓位越来越大

        STRONG: 5均线空头+3日确认 → ×1.0 标准仓位
        NORMAL: 3~4均线空头       → ×0.7
        WEAK  : 1~2均线短周期空头 → ×0.4 小仓试水
        NONE  : 不应到达此分支
        """
        if bearish_score == "STRONG":
            return self.SHORT_POSITION_MULTI_STRONG
        elif bearish_score == "NORMAL":
            return self.SHORT_POSITION_MULTI_NORMAL
        elif bearish_score == "WEAK":
            return self.SHORT_POSITION_MULTI_WEAK
        return 0.3  # 兜底：极小仓位

    # ================================================================
    # H1 / H4 新增：长多方向 弹簧力场 评分解析 + 阈值+仓位 乘数方法
    # 设计原则：与做空方向对称（牛市形态为做空熊市的镜像）
    # ================================================================

    def _parse_bullish_score_from_reason(self, reason: str) -> str:
        """从趋势确认 reason 解析长多评分 STRONG/NORMAL/WEAK/NONE（对称 bearish）"""
        if not reason:
            return "NONE"
        if "5均线多头" in reason or "5条长周期均线多头" in reason or ("全部" in reason and "均线多头" in reason):
            return "STRONG"
        if "4条均线多头" in reason or "4均线多头" in reason:
            return "NORMAL"
        if "3条均线多头" in reason or "3均线多头" in reason:
            return "NORMAL"
        if "2条均线多头" in reason or "2均线多头" in reason:
            return "WEAK"
        if "1条均线多头" in reason or "1均线多头" in reason:
            return "WEAK"
        if "纳斯达克100" in reason or "标普500" in reason:
            if "强牛" in reason or "5均线多头" in reason:
                return "STRONG"
            if "牛市" in reason:
                return "NORMAL"
            return "NONE"
        return "NONE"

    def _compute_long_conf_multiplier(self, bullish_score: str) -> float:
        if bullish_score == "STRONG":
            return self.LONG_CONF_MULTI_MA_STRONG
        elif bullish_score == "NORMAL":
            return self.LONG_CONF_MULTI_MA_NORMAL
        elif bullish_score == "WEAK":
            return self.LONG_CONF_MULTI_MA_WEAK
        return 1.0

    def _get_regime_long_multiplier(self, regime: str) -> float:
        """5态 spring regime → 长多阈值乘数（基于回测胜率反比，与 _short 对称）"""
        if not regime:
            return 1.0
        mapping = {
            "TREND_BULL":        self.REGIME_LONG_CONF_MULTI_TREND_BULL,
            "STRONG_TREND_BULL": self.REGIME_LONG_CONF_MULTI_STRONG_TREND_BULL,
            "TREND_BEAR":        self.REGIME_LONG_CONF_MULTI_TREND_BEAR,
            "MEAN_REVERTING":    self.REGIME_LONG_CONF_MULTI_MEAN_REVERTING,
            "RANGING":           self.REGIME_LONG_CONF_MULTI_RANGING,
        }
        return float(mapping.get(regime, 1.0))

    def _compute_long_position_multiplier(self, bullish_score: str) -> float:
        """弹簧力场评分 → 长多仓位规模分层（H4：对称做空仓位分层）"""
        if bullish_score == "STRONG":
            return self.LONG_POSITION_MULTI_STRONG
        elif bullish_score == "NORMAL":
            return self.LONG_POSITION_MULTI_NORMAL
        elif bullish_score == "WEAK":
            return self.LONG_POSITION_MULTI_WEAK
        return 1.0

    def _check_long_trend_filter(self, coin: str, inference: dict = None,
                                  _force_regime_filter_on: bool = False):
        """长多 UP 方向弹簧力场过滤（对称 _check_short_trend_filter；H1 缺口修复）。

        Returns:
            (allow_long: bool, reason: str, conf_multiplier: float)
            - 与做空过滤返回签名完全一致，调用方兼容三解包
        """
        coin_upper = coin.upper()
        # Step 1: 大盘/自身 趋势原因（复用 _check_*_trend；bearish/bullish 共享同一 reason 文本）
        if coin_upper in self.CRYPTO_COINS:
            _, trend_reason = self._check_btc_trend(_force_regime_filter_on=_force_regime_filter_on)
        elif coin_upper in self.US_STOCK_COINS:
            _, trend_reason = self._check_us_index_trend(_force_regime_filter_on=_force_regime_filter_on)
        else:
            _, trend_reason = self._check_self_trend(coin, _force_regime_filter_on=_force_regime_filter_on)

        # spring_regime 5 态 + bullish_score：
        #   ① 先按 5均线多头结构化理由解析
        #   ② 兜底：按 regime 代理（TREND_BULL 系列 & RANGING 视作多头结构；其余反转/熊市禁止追多）
        bullish_score = self._parse_bullish_score_from_reason(trend_reason)
        regime = self._parse_regime_from_reason(trend_reason)
        if bullish_score == "NONE":
            if regime == "STRONG_TREND_BULL":
                bullish_score = "STRONG"
            elif regime == "TREND_BULL":
                bullish_score = "NORMAL"
            elif regime == "RANGING":
                bullish_score = "WEAK"
            else:
                return False, f"趋势未确认(多头代理={regime} 属反转/熊市，禁止追多): {trend_reason}", 0.00

        conf_multiplier = self._compute_long_conf_multiplier(bullish_score)
        regime_multi = self._get_regime_long_multiplier(regime)
        final_multiplier = conf_multiplier * regime_multi

        # Step 2: 短周期共振（SMA20 > SMA50 > SMA200 多头排列）
        kline_data = (inference or {}).get("kline_data", [])
        if kline_data and len(kline_data) >= 200:
            closes = [float(c.get("c", 0)) for c in kline_data if c.get("c")]
            if len(closes) >= 200:
                sma20 = sum(closes[:20]) / 20
                sma50 = sum(closes[:50]) / 50
                sma200 = sum(closes[:200]) / 200
                if sma20 > sma50 > sma200:
                    if bullish_score == "WEAK":
                        bullish_score = "NORMAL"
                        conf_multiplier = self.LONG_CONF_MULTI_MA_NORMAL
                    elif bullish_score == "NORMAL":
                        bullish_score = "STRONG"
                        conf_multiplier = self.LONG_CONF_MULTI_MA_STRONG
                    final_multiplier = conf_multiplier * regime_multi
                    return (
                        True,
                        f"趋势确认+共振(SMA20>50>200) score={bullish_score} ×{conf_multiplier:.2f} regime={regime} ×{regime_multi:.2f} =×{final_multiplier:.2f} | {trend_reason}",
                        final_multiplier,
                    )
                return (
                    False,
                    f"共振失败(SMA20={sma20:.2f}/50={sma50:.2f}/200={sma200:.2f}非多头排列) score={bullish_score}",
                    0.00,
                )
        # 无共振数据时降级：仅趋势确认
        return (
            True,
            f"趋势确认(无共振数据) score={bullish_score} ×{conf_multiplier:.2f} regime={regime} ×{regime_multi:.2f} =×{final_multiplier:.2f} | {trend_reason}",
            final_multiplier,
        )

    def _check_short_trend_filter(self, coin: str, inference: dict, _force_regime_filter_on: bool = False) -> tuple:
        """P1-1: 做空趋势确认过滤器（Phase C+ 五均线版）

        三道关卡：
        1. 大盘趋势确认：
           - 加密货币 → BTC 五均线(MA30/65/128/200/MA1400)弹簧力场+排列评分
           - 美股代币 → 纳斯达克^IXIC + 标普500^GSPC 各五均线后平均
           - 其他 → 自身日K五均线(MA30/65/128/200/MA1400)
           → 输出 bearish_score (STRONG/NORMAL/WEAK/NONE) + 做空阈值乘数
        2. 短周期共振：当前K线SMA20<SMA50<SMA200 空头排列
        3. 将 bearish_score + 乘数 封装进返回值，供 _execute_trade 计算有效阈值

        Returns:
            (allow_short: bool, reason: str, conf_multiplier: float)
            - 旧调用只解包前两项，兼容
        """
        # Step 1: 大盘趋势确认
        coin_upper = coin.upper()
        if coin_upper in self.CRYPTO_COINS:
            trend_bearish, trend_reason = self._check_btc_trend(_force_regime_filter_on=_force_regime_filter_on)
        elif coin_upper in self.US_STOCK_COINS:
            trend_bearish, trend_reason = self._check_us_index_trend(_force_regime_filter_on=_force_regime_filter_on)
        else:
            trend_bearish, trend_reason = self._check_self_trend(coin, _force_regime_filter_on=_force_regime_filter_on)

        bearish_score = self._parse_bearish_score_from_reason(trend_reason)
        conf_multiplier = self._compute_short_conf_multiplier(bearish_score)

        # market_regime 阈值调节器：解析 regime 并叠加调节乘数
        regime = self._parse_regime_from_reason(trend_reason)
        regime_multi = self._get_regime_short_multiplier(regime)
        # 最终乘数 = bearish_score 乘数 × regime 乘数
        final_multiplier = conf_multiplier * regime_multi

        if not trend_bearish:
            return False, f"趋势未确认: {trend_reason}", 0.00

        # Step 2: 短周期共振（SMA20<SMA50<SMA200 空头排列）
        kline_data = inference.get("kline_data", [])
        if kline_data and len(kline_data) >= 200:
            closes = [float(c.get("c", 0)) for c in kline_data if c.get("c")]
            if len(closes) >= 200:
                sma20 = sum(closes[:20]) / 20
                sma50 = sum(closes[:50]) / 50
                sma200 = sum(closes[:200]) / 200
                if sma20 < sma50 < sma200:
                    # 共振成功 → 提升 score 一级（WEAK→NORMAL / NORMAL→STRONG）
                    if bearish_score == "WEAK":
                        bearish_score = "NORMAL"
                        conf_multiplier = self.SHORT_CONF_MULTI_MA_NORMAL
                    elif bearish_score == "NORMAL":
                        bearish_score = "STRONG"
                        conf_multiplier = self.SHORT_CONF_MULTI_MA_STRONG
                    # 共振提升 score 后重新计算 final 乘数
                    final_multiplier = conf_multiplier * regime_multi
                    return (
                        True,
                        f"趋势确认+共振(SMA20<50<200) score={bearish_score} ×{conf_multiplier:.2f} regime={regime} ×{regime_multi:.2f} =×{final_multiplier:.2f} | {trend_reason}",
                        final_multiplier,
                    )
                return (
                    False,
                    f"共振失败(SMA20={sma20:.2f}/50={sma50:.2f}/200={sma200:.2f}非空头排列) score={bearish_score}",
                    0.00,
                )

        # 无共振数据时降级：仅趋势确认
        return (
            True,
            f"趋势确认(无共振数据) score={bearish_score} ×{conf_multiplier:.2f} regime={regime} ×{regime_multi:.2f} =×{final_multiplier:.2f} | {trend_reason}",
            final_multiplier,
        )

    def _execute_trade(self, inference: dict, confidence_threshold: float = None,
                       all_inferences: dict = None):
        """根据推理结果执行交易决策（P2 完整版）"""
        coin = inference["coin"]
        inst_id = inference["inst_id"]
        direction = inference["direction"]
        confidence = inference["confidence"]
        fail_closed = inference["fail_closed"]
        is_ranging = inference["is_ranging"]
        inference.get("volatility", 0.03)

        # P2-05: 形态乘数快照（仅 S5 打开时注入，关闭时 inference 不带字段 → 1.0 全程）
        #   写入 inference 私有字段 _regime_pred / _regime_multipliers，供下游 _open_position 读取
        if self.ENABLE_REGIME_AND_MACRO_S5:
            try:
                _snap = inference.get("snapshot", {}) or {}
                # H2(P1)：优先级 snapshot.regime（BCRM2.0 内部判定）> inference.regime >
                #         spring_regime_5（后置层弹簧力场输出）经 _FMA_TO_S5 桥映射 → S5 8态
                #   目的：两套标签体系对齐审计；当 BCRM 未给出 regime 时，用后置层 5 态兜底
                _pred = _snap.get("regime") or inference.get("regime")
                _src_label = "snapshot" if _snap.get("regime") else ("inference.regime" if inference.get("regime") else None)
                if not _pred:
                    _sp5 = inference.get("spring_regime_5")
                    if isinstance(_sp5, str):
                        try:
                            _FMA_TO_S5 = {
                                "TREND_BULL":        "TREND_UP_MILD",
                                "STRONG_TREND_BULL": "TREND_UP_STRONG",
                                "STRONG_TREND_BEAR": "VOLATILE_DROP",
                                "TREND_BEAR":        "REVERSAL",
                                "MEAN_REVERTING":    "CONSOLIDATION",
                                "RANGING":           "RANGE_BOUND",
                            }
                            if _sp5 in _FMA_TO_S5 and _FMA_TO_S5[_sp5] in self.REGIME_MULTIPLIERS:
                                _pred = _FMA_TO_S5[_sp5]
                                _src_label = f"spring_bridge({_sp5}→{_pred})"
                        except Exception:
                            _pred, _src_label = None, None
                _mult = self._get_regime_pred_multipliers(
                    _pred, enable_regime_pred=True
                )
                inference["_regime_pred"] = _pred
                inference["_regime_multipliers"] = _mult
                if _src_label:
                    inference["_regime_pred_source"] = _src_label
            except Exception:
                inference["_regime_pred"] = None
                inference["_regime_multipliers"] = {
                    "position_mult": 1.0, "tp_mult": 1.0,
                    "sl_mult": 1.0, "threshold_mult": 1.0,
                }
        else:
            inference["_regime_pred"] = None
            inference["_regime_multipliers"] = {
                "position_mult": 1.0, "tp_mult": 1.0,
                "sl_mult": 1.0, "threshold_mult": 1.0,
            }

        # ── T4 融合层：调用 ParameterMapper._resolve_effective_params 注入 6 参数+板块乘数 ──
        #   设计 A.5 不变量：enable_inject=False → 完全字节等价于 regime 查表（单测验证）
        #   1. 每 5 分钟重读一次 enable_inject 文件
        #   2. 构建 ranges / stats_row / sector_weights_result（从 inference 读，缺失则安全兜底）
        #   3. 覆盖 effective_threshold / _regime_multipliers / 后续 TP/SL 计算使用乘数
        self._reload_enable_inject_if_stale()
        _inject = bool(getattr(self, "_enable_inject_runtime", False))
        _eff_params: dict | None = None
        try:
            if _inject and getattr(self, "_param_mapper", None) is not None:
                # 输入准备
                _snap = inference.get("snapshot", {}) or {}
                _stats_row = (inference.get("stats_row")
                              or _snap.get("stats_row")
                              or {"L_p10_252d": -3.0, "L_p90_252d": 3.0,
                                  "T_p10_252d": -2.5, "T_p90_252d": 2.5})
                _reactive_L = float(_snap.get("level_smooth", 0.0))
                _reactive_T = float(_snap.get("trend_smooth", 0.0))
                _reactive_C = float(_snap.get("consensus", 0.0))
                # forecast：若 inference 自带则直接用，否则按形态预测兜底
                _forecast_L = inference.get("forecast_L")
                _forecast_T = inference.get("forecast_T")
                if _forecast_L is None and getattr(self, "_morph_predictor", None):
                    try:
                        _full = inst_id  # 形如 BTCUSDT
                        _mp = self._morph_predictor.predict_with_fallback(
                            _full, hist_days=60, forecast_days=5
                        )
                        if _mp.get("ok"):
                            _series = _mp.get("series", {}) or {}
                            _fc = _series.get("forecast", []) or []
                            if _fc:
                                _forecast_L = float(_fc[-1])
                                if len(_fc) >= 2:
                                    _forecast_T = float(_fc[-1] - _fc[0])
                    except Exception:
                        _forecast_L, _forecast_T = None, None
                # ranges / sector_weights：优先用 inference 内缓存的（forecast 输入）
                try:
                    if inference.get("ai_global_ranges"):
                        _ranges = inference["ai_global_ranges"]
                    else:
                        _ranges = self._param_mapper.map_global_parameters(
                            _forecast_L if _forecast_L is not None else _reactive_L,
                            _forecast_T if _forecast_T is not None else _reactive_T,
                            _reactive_C, stats_row=_stats_row,
                        )
                except Exception:
                    _ranges = {}
                try:
                    if inference.get("ai_sector_weights"):
                        _sector_w = inference["ai_sector_weights"]
                    else:
                        # 兜底 betas：identity（无真实 betas 时均匀权重 + 1.0 乘数）
                        _def_betas = {"defi": (1.0, 0.0, 0.5), "ai": (1.0, 0.0, 0.5),
                                      "rwa": (1.0, 0.0, 0.5), "meme": (1.0, 0.0, 0.5),
                                      "l2": (1.0, 0.0, 0.5)}
                        _sector_w = self._param_mapper.map_sector_weights(
                            _forecast_L if _forecast_L is not None else _reactive_L,
                            _forecast_T if _forecast_T is not None else _reactive_T,
                            _reactive_C, _def_betas,
                        )
                except Exception:
                    _sector_w = {}

                _symbol_sector = (inference.get("sector")
                                  or _snap.get("sector"))
                _reg_mult = dict(inference.get("_regime_multipliers", {}) or {})
                # 把 regime_baselines（global_position_mult/ls_ratio_cap/long_bias/...）注入
                _rb = dict(getattr(self, "_param_mapper", None)
                           and getattr(self._param_mapper, "REGIME_BASE_PARAMS", {})
                           or {})
                # 如果 inference 提供过 baseline，则用 inference 的（保证 shadow 一致）
                if inference.get("_regime_baselines"):
                    _rb.update(dict(inference["_regime_baselines"]))
                inference["_regime_baselines"] = _rb
                # 暴露 stats_row / sector 到 inference（ShadowLogger 需要）
                inference["stats_row"] = _stats_row
                inference["sector"] = _symbol_sector
                inference["base_long_threshold"] = float(self.confidence_threshold)
                inference["base_short_threshold"] = float(self.short_confidence_threshold)

                _eff_params = self._param_mapper._resolve_effective_params(
                    ranges=_ranges,
                    stats_row=_stats_row,
                    forecast_L=_forecast_L,
                    forecast_T=_forecast_T,
                    alpha_blend=getattr(self, "_alpha_blend", 0.0),
                    regime_baselines=_rb,
                    sector_weights_result=_sector_w,
                    symbol_sector=_symbol_sector,
                    regime_multipliers=_reg_mult,
                    enable_inject=True,
                    base_long_threshold=float(self.confidence_threshold),
                    base_short_threshold=float(self.short_confidence_threshold),
                )
        except Exception as _e:
            self._log(f"[{coin}] 融合层调用失败（已降级为不注入）：{_e}", "WARN")
            _eff_params = None
            _inject = False

        if _inject and _eff_params:
            # ⚡ 注入生效：覆盖 regime_multipliers（下游 _open_position 读）
            _reg = dict(inference.get("_regime_multipliers", {}) or {})
            _reg["position_mult"] = float(_eff_params["position_mult_final"])
            _reg["tp_mult"] = float(_eff_params["tp_mult_final"])
            _reg["sl_mult"] = float(_eff_params["sl_mult_final"])
            _reg["threshold_mult"] = float(_eff_params["threshold_mult_final"])
            inference["_regime_multipliers"] = _reg
            inference["_effective_params"] = _eff_params
            # ⚡ 覆盖 threshold（多空各自独立阈值：long_conf / short_conf 实际）
            if direction == "DOWN":
                effective_threshold = float(_eff_params["short_conf_threshold"])
            else:
                effective_threshold = float(_eff_params["long_conf_threshold"])
            self._log(
                f"[{coin}] 融合层 T4 注入生效 | pos={_reg['position_mult']:.3f}"
                f" tp={_reg['tp_mult']:.3f} sl={_reg['sl_mult']:.3f}"
                f" thr_mult={_reg['threshold_mult']:.3f}"
                f" long_thr={_eff_params['long_conf_threshold']:.4f}"
                f" short_thr={_eff_params['short_conf_threshold']:.4f}"
                f" ls_cap={_eff_params['ls_ratio_cap']:.3f}"
                f" (α={getattr(self, '_alpha_blend', 0.0):.2f})",
                "INFO",
            )
        else:
            # 融合层未生效：初始化 effective_threshold 与原逻辑一致
            effective_threshold = confidence_threshold or self.confidence_threshold
            # 做空方向使用独立的更高阈值（原版逻辑）
            if direction == "DOWN":
                effective_threshold = max(effective_threshold, self.short_confidence_threshold)

            # ── 基线模式下统一暴露「六维参数 + 形态乘数」（审计要求：日志中可见）
            #    即便乘数=1.0 也要打一条汇总，让实盘日志明确看到：spec §10.6 的 Layer0 参数
            #    已通过 _regime_multipliers 传递链（阈值×/仓位×/SL×/TP×）生效到核心层
            try:
                _rbs = getattr(self, "_param_mapper", None) and \
                       getattr(self._param_mapper, "REGIME_BASE_PARAMS", {}) or {}
                _rbs_merged = dict(_rbs)
                if inference.get("_regime_baselines"):
                    _rbs_merged.update(dict(inference["_regime_baselines"]))
                _reg_mult2 = dict(inference.get("_regime_multipliers", {}) or {})
                _sector_w = (inference.get("ai_sector_weights")
                             or (inference.get("_effective_params") or {}).get("sector_weights_result")
                             or None)
                _base_long = float(getattr(self, "confidence_threshold", 0.35))
                _base_short = float(getattr(self, "short_confidence_threshold", 0.80))
                _thr_mult_2 = float(_reg_mult2.get("threshold_mult", 1.0))
                _eff_long = _base_long * _thr_mult_2
                _eff_short = max(_base_long, _base_short) * _thr_mult_2
                # sector 若存在：取前 3 个最高权重
                _sector_str = "n/a(均匀分配)"
                if isinstance(_sector_w, dict) and len(_sector_w):
                    _sorted = sorted(_sector_w.items(), key=lambda kv: float(kv[1]), reverse=True)[:3]
                    _sector_str = ", ".join(f"{k}={float(v):.2f}" for k, v in _sorted)
                self._log(
                    f"[{coin}] 形态查表参数（基线模式，S5={self.ENABLE_REGIME_AND_MACRO_S5} "
                    f"α={getattr(self, '_alpha_blend', 0.0):.2f}） | "
                    f"regime={inference.get('_regime_pred') or 'UNKNOWN'} "
                    f"src={inference.get('_regime_pred_source') or 'n/a'} "
                    f"pos=×{float(_reg_mult2.get('position_mult', 1.0)):.3f} "
                    f"tp=×{float(_reg_mult2.get('tp_mult', 1.0)):.3f} "
                    f"sl=×{float(_reg_mult2.get('sl_mult', 1.0)):.3f} "
                    f"thr_mult=×{_thr_mult_2:.3f} "
                    f"long_thr={_eff_long:.4f} short_thr={_eff_short:.4f} "
                    f"ls_cap={float(_rbs_merged.get('ls_ratio_cap', 1.15)):.3f} "
                    f"sector_top3=[{_sector_str}]",
                    "INFO",
                )
            except Exception:
                pass

        # ── 段①②③ 只读审计日志：大小周期→市场形态→六维（对齐 tab-morph /cycle+/params）──
        # 无论基线/融合层开启状态，均只读取并记录，不修改任何交易参数
        self._log_morph_cycle_for_coin(coin, inst_id)
        self._log_param_mapper_snapshot(coin, inst_id, inference)

        pos_info = self._check_positions(coin)

        if pos_info.get("has_position"):
            # ── 段④ 注入BCRM（持仓路径）：形态乘数作用到 SLTP/仓位 中性确认日志 ──
            self._log_regime_hold_confirmation(coin, inference, pos_info)
            pos_side = pos_info["pos_side"]
            upl = pos_info.get("upl", 0)
            upl_ratio = pos_info.get("upl_ratio", 0)

            tracker_pos = self.position_tracker.get_open_position(inst_id)
            is_external = tracker_pos and tracker_pos.strategy_source == "external"

            if is_external:
                self._log(f"[{coin}] 外部策略持仓，BCRM 不干预", "INFO")
                return

            # 计算持仓年龄（供保护期门禁、离场确认等使用）
            position_age_sec = 0
            open_time = pos_info.get("open_time", 0)
            if open_time > 0:
                position_age_sec = time.time() - open_time
            in_protection = self._is_position_protected(position_age_sec)

            # ════════════════════════════════════════════════════════════════
            # ── 持仓与离场管理层：ExitManager 策略链（v4.4 重构）──
            #    替换原 ① 信号反转 + ② P3提前退出 + Phase B EV 雷达四档决策
            #    优先级：P3(10) → SignalRev(20) → EvFC(30) → Timeout(40) → EvAdj(60)
            #    全部 pass → 继续走 Phase C (S3) → 核心层（卦象主离场 + Classic 兜底）
            #    Spec: docs/superpowers/specs/2026-08-20-exit-manager-design.md
            # ════════════════════════════════════════════════════════════════

            # ── 计算 EV（如果 EV 雷达开启，供 EvForceClose/EvAdjust 策略使用）──
            _ev = None
            _ev_subs: Dict = {}
            if getattr(self, "enable_ev_radar", False):
                try:
                    from scripts.memory_l4.trading_utils import RiskManager
                    _ev_subs = self._build_ev_subscores(
                        pos_side, position_age_sec, upl_ratio, inference
                    )
                    _weights = getattr(self, "ev_weights", None) or {
                        k: 1 / 7 for k in _ev_subs
                    }
                    _ev, _ev_subs = RiskManager.calc_position_ev(_ev_subs, _weights)
                    self._log(
                        f"[{coin}] EV={_ev:.3f} | "
                        f"trend={_ev_subs.get('trend_alignment_s', 0):.2f} "
                        f"liq={_ev_subs.get('liquidity_risk_s', 0):.2f} "
                        f"dir={_ev_subs.get('direction_consistency_s', 0):.2f} "
                        f"pnl_mom={_ev_subs.get('pnl_momentum_s', 0):.2f}",
                        "INFO",
                    )
                except Exception as _e:
                    self._log(f"[{coin}] EV 计算异常: {_e}", "WARN")
                    _ev = None
            else:
                self._log(f"[{coin}] EV BYPASS (S2=off)", "INFO")

            # ── 构造 held_coins 集合（供 TimeoutProfitSwitch 排除已持仓币种）──
            _held_coins = {coin}
            for _inst in getattr(self.position_tracker, "open_positions", {}):
                _c = _inst.split("-")[0] if _inst else ""
                if _c:
                    _held_coins.add(_c)

            # ── 调用 ExitManager（按优先级链评估扩展层离场策略）──
            _exit_decision = self.exit_manager.evaluate(
                coin=coin,
                inference=inference,
                pos_info=pos_info,
                tracker_pos=tracker_pos,
                in_protection=in_protection,
                age_hours=position_age_sec / 3600.0,
                ev=_ev,
                confidence=confidence,
                all_inferences=all_inferences or {},
                held_coins=_held_coins,
                effective_threshold=effective_threshold,
            )

            # ── 处理 ExitManager 决策 ──
            _act = _exit_decision.action
            _sname = _exit_decision.strategy_name or "exit_manager"
            _ev_str = f"{_ev:.3f}" if _ev is not None else "N/A"

            if _act == "force_close":
                # 执行平仓（P3/SignalReverse/EvForceClose/TimeoutProfitSwitch）
                _exit_price = pos_info.get("mark_px", inference["price"])
                _exit_reason = _exit_decision.reason or _sname
                self._log(
                    f"[{coin}] [{_sname}] FORCE_CLOSE✅ | reason={_exit_reason} | "
                    f"{'[保护期]' if in_protection else ''} "
                    f"卦象={inference.get('hexagram', '-')} "
                    f"盈亏={upl:.2f}({upl_ratio:.2%}) "
                    f"持仓={position_age_sec/3600:.1f}h",
                    "WARN",
                )
                if pos_side == "long":
                    _r = self.okx_client.market_close_long(
                        inst_id, reason=_exit_reason
                    )
                else:
                    _r = self.okx_client.market_close_short(
                        inst_id, reason=_exit_reason
                    )
                if _r.get("ok") or _r.get("dry_run"):
                    self._handle_close_position(
                        inst_id=inst_id, coin=coin, pos_side=pos_side,
                        exit_price=_exit_price, exit_reason=_exit_reason,
                        pnl=upl, pnl_pct=upl_ratio,
                    )
                    # ── 记录 exit_strategy_log（含 pnl/win 贡献值回填）──
                    self._save_exit_strategy_decision(
                        coin=coin, decision=_exit_decision,
                        age_hours=position_age_sec / 3600.0,
                        in_protection=in_protection, ev=_ev,
                        confidence=confidence, pnl=upl, win=(upl > 0),
                    )
                    # 信号反转特殊处理：平仓后开反手仓
                    if _sname == "signal_reverse":
                        _side_map = {"UP": "long", "DOWN": "short"}
                        _want_side = _side_map.get(direction)
                        _in_cd, _cd_reason = self.position_tracker.is_in_cooldown(
                            inst_id, _want_side, self.COOLDOWN_SEC
                        )
                        if _in_cd:
                            self._log(
                                f"[{coin}] 信号反转已平仓，但统一冷静期生效，跳过反手开仓: {_cd_reason}",
                                "INFO",
                            )
                            return
                        _risk_check = self.risk_manager.can_trade(
                            self.perf_tracker.current_equity
                        )
                        if not _risk_check["allowed"]:
                            self._log(
                                f"[{coin}] 风控拦截反手开仓: {_risk_check['reason']}",
                                "WARN",
                            )
                            return
                        _total_pos = self._count_total_positions()
                        if _total_pos >= self.max_positions:
                            self._log(
                                f"[{coin}] 已达最大持仓数 {self.max_positions}，跳过反手",
                                "INFO",
                            )
                            return
                        self._open_position(inference, is_reverse=True)
                return

            elif _act == "hold":
                # 等待确认（P3/SignalReverse/EvForceClose 待确认状态）
                self._log(
                    f"[{coin}] [{_sname}] HOLD 待确认 | "
                    f"{_exit_decision.reason} | "
                    f"{'[保护期]' if in_protection else ''} "
                    f"盈亏={upl:.2f}({upl_ratio:.2%}) "
                    f"持仓={position_age_sec/3600:.1f}h",
                    "INFO",
                )
                # ── 记录 exit_strategy_log（pnl/win 留空，待确认）──
                self._save_exit_strategy_decision(
                    coin=coin, decision=_exit_decision,
                    age_hours=position_age_sec / 3600.0,
                    in_protection=in_protection, ev=_ev,
                    confidence=confidence, pnl=None, win=None,
                )
                return

            elif _act == "adjust_sl_tp":
                # 调用 _adjust_sl_tp（T2 收紧 / T4 放宽）
                _mode = (_exit_decision.params or {}).get("mode", "tighten")
                self._log(
                    f"[{coin}] [{_sname}] ADJUST_SL_TP | mode={_mode} | "
                    f"reason={_exit_decision.reason} | EV={_ev_str} | "
                    f"盈亏={upl:.2f}({upl_ratio:.2%})",
                    "INFO",
                )
                try:
                    self._adjust_sl_tp(coin, inst_id, pos_side, mode=_mode)
                except Exception as _e:
                    self._log(f"[{coin}] _adjust_sl_tp 异常: {_e}", "WARN")
                # ── 记录 exit_strategy_log（SL/TP 调整无 pnl/win）──
                self._save_exit_strategy_decision(
                    coin=coin, decision=_exit_decision,
                    age_hours=position_age_sec / 3600.0,
                    in_protection=in_protection, ev=_ev,
                    confidence=confidence, pnl=None, win=None,
                )
                # 继续走 Phase C (S3) 和核心层（不 return）

            # action == "pass": 继续走 Phase C (S3) 和核心层

            # ── Phase C (S3): 多 horizon 最佳离场 K 线推荐 ──
            # 三档动作：
            #   - HOLD / EXTEND_TRACK / BYPASS / NOOP → 仅日志
            #   - PREP_EXIT → 跨轮一致率统计 → 达标后 EXIT_CONFIRM → 执行平仓 return
            try:
                held_k_bar = max(
                    1, int(round(position_age_sec / 3600.0))
                ) if position_age_sec > 0 else 1
                horizon_info = self._recommend_exit_bars(
                    coin=coin, pos_side=pos_side,
                    held_k_bar=held_k_bar, inference=inference,
                )
                h_action = str(horizon_info.get("recommended_action", ""))
                if h_action and h_action in ("BYPASS", "NOOP"):
                    self._log(
                        f"[{coin}] [S3多horizon] 已持仓≈{held_k_bar}h → "
                        f"{h_action}（src={horizon_info.get('source', '?')}）",
                        "INFO",
                    )
                if h_action and h_action not in ("BYPASS", "NOOP"):
                    self._log(
                        f"[{coin}] [S3多horizon] 已持仓≈{held_k_bar}h → "
                        f"best_k={horizon_info.get('best_k_bar')} "
                        f"conf={horizon_info.get('best_confidence', 0):.2f} "
                        f"dir={horizon_info.get('best_direction', '')} "
                        f"src={horizon_info.get('source', '?')} → "
                        f"{h_action}",
                        "INFO",
                    )
                    # Phase C C11：PREP_EXIT → 跨轮一致率 → 离场确认 → 平仓
                    if h_action == "PREP_EXIT" and not in_protection:
                        prep_window = int(getattr(self, "S3_PREP_EXIT_CONFIRM_WINDOW", 3))
                        prep_rate = float(getattr(self, "S3_PREP_EXIT_CONFIRM_RATE", 0.67))
                        # 写入本轮 PREP_EXIT 记录（滑动窗口按 cycle 尾端维护 prep_window 个样本）
                        hist_key = ("s3_prep_exit_hist", coin, pos_side)
                        _h_hit, _h_load = self._cache_get(hist_key, ttl_cycles=prep_window + 2)
                        hist = list(_h_load) if isinstance(_h_load, list) else []
                        hist.append({
                            "cycle": int(getattr(self, "_cycle_idx", 0)),
                            "action": "PREP_EXIT",
                            "best_k": int(horizon_info.get("best_k_bar", -1)),
                        })
                        # 只保留最近 prep_window 条
                        hist = hist[-prep_window:]
                        self._cache_set(hist_key, hist)

                        n = len(hist)
                        n_prep = sum(1 for h in hist if h.get("action") == "PREP_EXIT")
                        rate = (n_prep / n) if n > 0 else 0.0
                        if rate >= prep_rate and n >= 2:
                            # 一致率达标 → EXIT_CONFIRM（2/2 双确认，保持与全系统一致）
                            confirmed, cnt = self._exit_confirm(
                                coin, self.EXIT_ACT_S3_PREP_EXIT
                            )
                            if confirmed:
                                self._clear_exit_confirm(coin, self.EXIT_ACT_S3_PREP_EXIT)
                                exit_price = float(
                                    inference.get("price") or pos_info.get("avg_px") or 0.0
                                )
                                best_k = int(horizon_info.get("best_k_bar", -1))
                                reason = (
                                    f"s3_prep_exit|consistency={n_prep}/{n}="
                                    f"{rate:.2f}≥{prep_rate:.2f}|"
                                    f"best_k={best_k}|held≈{held_k_bar}|cnt={cnt}"
                                )
                                self._log(
                                    f"[{coin}] [S3多horizon] PREP_EXIT 跨轮一致 "
                                    f"{n_prep}/{n}={rate:.2f}≥{prep_rate:.2f} → 执行离场",
                                    "WARN",
                                )
                                self._handle_close_position(
                                    inst_id=inst_id, coin=coin, pos_side=pos_side,
                                    exit_price=exit_price, exit_reason=reason,
                                    pnl=upl, pnl_pct=upl_ratio,
                                )
                                return  # S3 强制离场 → 跳过后续所有离场分支
                            else:
                                self._log(
                                    f"[{coin}] [S3多horizon] PREP_EXIT 一致率达标 "
                                    f"1/{self.EXIT_CONFIRM_REQUIRED} (cnt={cnt})，等待下轮确认",
                                    "WARN",
                                )
                    # SPEC §6.1：整轮 horizon_info 存缓存（用于诊断/回放）
                    self._cache_set(
                        ("horizon_eval", coin, pos_side),
                        dict(horizon_info),
                    )
            except Exception as _e:
                self._log(f"[{coin}] [S3多horizon] 评估异常: {_e}", "WARN")

            # 经典指标离场系统评估（完整四大优先级）
            current_price = inference["price"]
            entry_price = pos_info.get("avg_px", 0)
            # position_age_sec 和 open_time 已在上方计算
            kline_data = inference.get("kline_data", [])
            is_ranging = inference.get("is_ranging", False)
            regime = "chop" if is_ranging else "trend"

            exit_pos = ExitPositionState(
                coin=coin,
                side=pos_side,
                entry_price=float(entry_price) if entry_price else 0,
                current_price=float(current_price),
                position_age_sec=position_age_sec,
                unrealized_pnl_pct=float(upl_ratio),
                leverage=float(self.okx_client.cfg.get("default_leverage", 3)),
                atr_pct=float(inference.get("volatility", 0.03)),
                mfe_pnl_pct=max(0.0, float(upl_ratio)),
                metadata={"reduce_count": tracker_pos.reduce_count if tracker_pos else 0},
            )

            candles_1h = None
            if kline_data and len(kline_data) >= 20:
                candles_1h = [
                    {
                        "t": c.get("ts", c.get("t", 0)),
                        "o": c.get("o", 0),
                        "h": c.get("h", 0),
                        "l": c.get("l", 0),
                        "c": c.get("c", 0),
                        "v": c.get("v", 0),
                    }
                    for c in kline_data
                ]

            # ── v3.1: 29h持仓超时全局门控（回测最佳持仓时间）──
            # TimeoutProfitSwitchStrategy (ExitManager priority=40) 已处理"有更强候选→force_close"
            # 此处仅处理：超时+盈利+无更强候选→继续持有 / 超时+亏损→走classic备用离场
            position_timeout_sec = self.yijing_exit_system.config.veto_max_hold_sec  # 104400 = 29h
            position_timed_out = position_age_sec > position_timeout_sec
            if position_timed_out:
                if upl > 0 and all_inferences:
                    # 超时+盈利+无更强候选（ExitManager 已检查）→ 继续持有追求更大利润
                    self._log(
                        f"[{coin}] 超时继续持有(>{position_timeout_sec/3600:.0f}h) | "
                        f"盈利={upl:.2f}({upl_ratio:.2%}) | "
                        f"当前信号仍为最强，继续持有追求更大利润",
                        "INFO",
                    )
                    return
                else:
                    # 亏损 → 走 classic 备用离场（跳过 yijing 评估）
                    self._log(
                        f"[{coin}] 持仓超时(>{position_timeout_sec/3600:.0f}h)启用经典备用离场 | "
                        f"持仓={position_age_sec/3600:.1f}h | "
                        f"亏损={upl:.2f} | 跳过yijing评估，直接走classic备用离场",
                        "WARN",
                    )
                    # fall through to core layer (yijing_available=False)

            # ── 主离场层：易经推理专属离场（基于卦象风险-价值评估）──
            # 架构反转：yijing 作为主决策，classic 降为备用（仅在 yijing 不可用或信号中性时调用）
            yijing_hexagram = self._infer_current_hexagram(coin, inference, kline_data)
            yijing_decision = None
            # Bug1修复: 超时后直接标记yijing不可用，强制走classic降级路径
            yijing_available = (not position_timed_out) and (yijing_hexagram is not None)

            if yijing_available:
                yijing_decision = self.yijing_exit_system.evaluate(
                    hexagram=yijing_hexagram,
                    pos_side=pos_side,
                    entry_price=float(entry_price) if entry_price else 0,
                    current_price=float(current_price),
                    position_age_sec=position_age_sec,
                    unrealized_pnl_pct=float(upl_ratio),
                    classic_decision=None,  # 主离场模式：不再否决 classic
                    mfe_pnl_pct=max(0.0, float(upl_ratio)),
                    coin=coin,  # v3.0：1h节奏缓存key
                    open_time_sec=float(open_time) if open_time else 0.0,  # v3.0：开仓时间戳
                )

            # 1) 易经强制平仓：卦象风险极高 + 方向冲突 → 离场确认后执行
            if yijing_decision and yijing_decision.action == YijingExitAction.FORCE_CLOSE:
                # v5.0：FORCE_CLOSE 加2次离场确认（避免卦象波动误平仓，尤其是中高风险时）
                fc_confirmed, fc_cnt = self._exit_confirm(coin, self.EXIT_ACT_YIJING_FORCE_CLOSE)
                if not fc_confirmed:
                    self._log(
                        f"[{coin}] 易经FORCE_CLOSE待确认 [{fc_cnt}/{self.EXIT_CONFIRM_REQUIRED}] "
                        f"{'[保护期]' if in_protection else ''} | "
                        f"{yijing_decision.reason} | 卦象={yijing_decision.hexagram_name} "
                        f"风险={yijing_decision.yijing_risk_score:.2f} "
                        f"盈亏={upl:.2f}({upl_ratio:.2%})",
                        "WARN",
                    )
                    return  # 未确认，等待下次
                # 确认通过：执行
                self._clear_exit_confirm(coin, self.EXIT_ACT_YIJING_FORCE_CLOSE)
                self._log(
                    f"[{coin}] 易经主离场 [FORCE_CLOSE✅已确认] {yijing_decision.reason} | "
                    f"卦象={yijing_decision.hexagram_name} "
                    f"风险={yijing_decision.yijing_risk_score:.2f} "
                    f"价值={yijing_decision.yijing_value_score:.2f} "
                    f"持仓={position_age_sec/3600:.1f}h 盈亏={upl:.2f}({upl_ratio:.2%})"
                )
                if pos_side == "long":
                    r = self.okx_client.market_close_long(
                        inst_id, reason=f"易经离场:{yijing_decision.reason}"
                    )
                else:
                    r = self.okx_client.market_close_short(
                        inst_id, reason=f"易经离场:{yijing_decision.reason}"
                    )
                if r.get("ok") or r.get("dry_run"):
                    self._handle_close_position(
                        inst_id=inst_id,
                        coin=coin,
                        pos_side=pos_side,
                        exit_price=current_price,
                        exit_reason=f"yijing_exit:{yijing_decision.reason}",
                        pnl=upl,
                        pnl_pct=upl_ratio,
                    )
                return
            else:
                # FORCE_CLOSE条件不满足：清除累计确认（避免污染）
                self._clear_exit_confirm(coin, self.EXIT_ACT_YIJING_FORCE_CLOSE)

            # ── v5.0：持仓保护期门禁 ──
            # 开仓后6h内：屏蔽易经的SL/TP动态调整（TIGHTEN_SL/LOWER_SL/RAISE_TP/LOWER_TP）
            # 原因：开仓初期卦象/指标不稳定，频繁调SL/TP反而适得其反；
            #       保护期内仅依赖开仓时设置的静态SL/TP + FORCE_CLOSE(极端) + 信号反转
            _PROTECTED_YIJING_ACTIONS = {
                YijingExitAction.RAISE_TP,
                YijingExitAction.LOWER_SL,
                YijingExitAction.LOWER_TP,
                YijingExitAction.TIGHTEN_SL,
            }
            if (
                in_protection
                and yijing_decision
                and yijing_decision.action in _PROTECTED_YIJING_ACTIONS
            ):
                self._log(
                    f"[{coin}] 易经{str(yijing_decision.action).split('.')[-1]} [保护期屏蔽] "
                    f"持仓={position_age_sec/3600:.1f}h<{self.POSITION_PROTECTION_HOURS:.0f}h | "
                    f"原动作原因={yijing_decision.reason} 卦象={yijing_decision.hexagram_name or '-'} | "
                    f"保护期内仅用静态SL/TP，跳过动态调整",
                    "INFO",
                )
                # NO_INTERVENE 语义：维持持仓
                yijing_decision.action = YijingExitAction.NO_INTERVENE
                yijing_decision.reason = "protected_hold:" + yijing_decision.reason

            # 2) 易经提高止盈：价值高 + 成长期 → 上调止盈位（保护期内已屏蔽）
            # 2026-08-06 修复：基于 ATR 基线 × 价值调制因子（非硬编码 15%）
            if yijing_decision and yijing_decision.action == YijingExitAction.RAISE_TP:
                leverage = self._get_leverage()
                entry_price = float(pos_info.get("avg_px", current_price))
                # 读取开仓时 ATR 基线止盈收益率
                base_tp_roi = self._get_base_tp_roi(inst_id, entry_price)
                if base_tp_roi <= 0:
                    self._log(
                        f"[{coin}] 易经主离场 [RAISE_TP] 跳过: base_tp_roi=0（旧持仓无ATR基线）",
                        "WARN",
                    )
                    return
                # 价值分 → TP 调制因子（连续函数）
                tp_modulation = YijingExitSystem.value_to_tp_modulation(
                    yijing_decision.yijing_value_score
                )
                target_tp_roi = base_tp_roi * tp_modulation
                # ATR 基线下限保护
                target_tp_roi = YijingExitSystem.apply_atr_floor(target_tp_roi, base_tp_roi)
                new_tp_price = self._calc_tp_price(entry_price, pos_side, target_tp_roi, leverage)
                tp_price_change_pct = self._roi_to_price_change(target_tp_roi, leverage)
                self._log(
                    f"[{coin}] 易经主离场 [RAISE_TP] {yijing_decision.reason} | "
                    f"卦象={yijing_decision.hexagram_name} 杠杆={leverage}x "
                    f"ATR基线={base_tp_roi:.2%} × 调制{tp_modulation:.2f} = {target_tp_roi:.2%} "
                    f"(价{tp_price_change_pct:.2%}) "
                    f"新止盈={new_tp_price:.2f} 盈亏={upl:.2f}({upl_ratio:.2%})"
                )
                try:
                    tp_result = self.okx_client.place_stop_loss_take_profit(
                        inst_id=inst_id,
                        pos_side=pos_side,
                        stop_loss_px=None,
                        take_profit_px=new_tp_price,
                        reason=f"yijing_raise_tp:{yijing_decision.reason}",
                    )
                    if tp_result.get("ok"):
                        self._log(f"[{coin}] 易经止盈价已上调至 {new_tp_price:.2f}")
                    else:
                        self._log(
                            f"[{coin}] 易经上调止盈失败: {tp_result.get('error', 'unknown')}",
                            "WARN",
                        )
                except Exception as e:
                    self._log(f"[{coin}] 易经上调止盈异常: {e}", "WARN")
                return

            # 3) 易经降低止损：风险低 + 趋势初期 → 放宽止损空间，避免被洗出去
            # 2026-08-06 修复：基于 ATR 基线 × 风险调制因子（非硬编码 2%）
            if yijing_decision and yijing_decision.action == YijingExitAction.LOWER_SL:
                leverage = self._get_leverage()
                entry_price = float(pos_info.get("avg_px", current_price))
                # 读取开仓时 ATR 基线止损收益率
                base_sl_roi = self._get_base_sl_roi(inst_id, entry_price)
                if base_sl_roi <= 0:
                    self._log(
                        f"[{coin}] 易经主离场 [LOWER_SL] 跳过: base_sl_roi=0（旧持仓无ATR基线）",
                        "WARN",
                    )
                    return
                # 风险分 → SL 调制因子（连续函数，风险低 → >1.0 放宽）
                sl_modulation = YijingExitSystem.risk_to_sl_modulation(
                    yijing_decision.yijing_risk_score
                )
                new_sl_roi = base_sl_roi * sl_modulation
                # ATR 基线下限保护
                new_sl_roi = YijingExitSystem.apply_atr_floor(new_sl_roi, base_sl_roi)
                new_sl_price = self._calc_sl_price(entry_price, pos_side, new_sl_roi, leverage)
                sl_price_change_pct = self._roi_to_price_change(new_sl_roi, leverage)
                self._log(
                    f"[{coin}] 易经主离场 [LOWER_SL] {yijing_decision.reason} | "
                    f"卦象={yijing_decision.hexagram_name} 杠杆={leverage}x "
                    f"ATR基线={base_sl_roi:.2%} × 调制{sl_modulation:.2f} = {new_sl_roi:.2%} "
                    f"(价{sl_price_change_pct:.2%}) "
                    f"新止损={new_sl_price:.2f} 盈亏={upl:.2f}({upl_ratio:.2%})"
                )
                try:
                    sl_result = self.okx_client.place_stop_loss_take_profit(
                        inst_id=inst_id,
                        pos_side=pos_side,
                        stop_loss_px=new_sl_price,
                        take_profit_px=None,
                        reason=f"yijing_lower_sl:{yijing_decision.reason}",
                    )
                    if sl_result.get("ok"):
                        self._log(f"[{coin}] 易经止损价已放宽至 {new_sl_price:.2f}")
                    else:
                        self._log(
                            f"[{coin}] 易经放宽止损失败: {sl_result.get('error', 'unknown')}",
                            "WARN",
                        )
                except Exception as e:
                    self._log(f"[{coin}] 易经放宽止损异常: {e}", "WARN")
                return

            # 4) 易经降低止盈：风险升高 + 已有利润 → 提前锁定利润
            # 2026-08-06 修复：基于 ATR 基线 × 价值调制因子（非硬编码 9%）
            if yijing_decision and yijing_decision.action == YijingExitAction.LOWER_TP:
                leverage = self._get_leverage()
                entry_price = float(pos_info.get("avg_px", current_price))
                base_tp_roi = self._get_base_tp_roi(inst_id, entry_price)
                if base_tp_roi <= 0:
                    self._log(
                        f"[{coin}] 易经主离场 [LOWER_TP] 跳过: base_tp_roi=0（旧持仓无ATR基线）",
                        "WARN",
                    )
                    return
                # 价值分低 → tp_modulation < 1.0（降低止盈）
                tp_modulation = YijingExitSystem.value_to_tp_modulation(
                    yijing_decision.yijing_value_score
                )
                target_tp_roi = base_tp_roi * tp_modulation
                # ATR 基线下限保护
                target_tp_roi = YijingExitSystem.apply_atr_floor(target_tp_roi, base_tp_roi)
                new_tp_price = self._calc_tp_price(entry_price, pos_side, target_tp_roi, leverage)
                tp_price_change_pct = self._roi_to_price_change(target_tp_roi, leverage)
                self._log(
                    f"[{coin}] 易经主离场 [LOWER_TP] {yijing_decision.reason} | "
                    f"卦象={yijing_decision.hexagram_name} 杠杆={leverage}x "
                    f"ATR基线={base_tp_roi:.2%} × 调制{tp_modulation:.2f} = {target_tp_roi:.2%} "
                    f"(价{tp_price_change_pct:.2%}) "
                    f"新止盈={new_tp_price:.2f} 盈亏={upl:.2f}({upl_ratio:.2%})"
                )
                try:
                    tp_result = self.okx_client.place_stop_loss_take_profit(
                        inst_id=inst_id,
                        pos_side=pos_side,
                        stop_loss_px=None,
                        take_profit_px=new_tp_price,
                        reason=f"yijing_lower_tp:{yijing_decision.reason}",
                    )
                    if tp_result.get("ok"):
                        self._log(f"[{coin}] 易经止盈价已下调至 {new_tp_price:.2f}")
                    else:
                        self._log(
                            f"[{coin}] 易经下调止盈失败: {tp_result.get('error', 'unknown')}",
                            "WARN",
                        )
                except Exception as e:
                    self._log(f"[{coin}] 易经下调止盈异常: {e}", "WARN")
                return

            # 5) 易经收紧止损：风险升高 + 未盈利/微利 → 收紧止损保本
            # 2026-08-06 修复：基于 ATR 基线 × 风险调制因子（非硬编码 2%）
            if yijing_decision and yijing_decision.action == YijingExitAction.TIGHTEN_SL:
                leverage = self._get_leverage()
                entry_price = float(pos_info.get("avg_px", current_price))
                base_sl_roi = self._get_base_sl_roi(inst_id, entry_price)
                if base_sl_roi <= 0:
                    self._log(
                        f"[{coin}] 易经主离场 [TIGHTEN_SL] 跳过: base_sl_roi=0（旧持仓无ATR基线）",
                        "WARN",
                    )
                    return
                # 风险分高 → sl_modulation < 1.0（收紧止损）
                sl_modulation = YijingExitSystem.risk_to_sl_modulation(
                    yijing_decision.yijing_risk_score
                )
                new_sl_roi = base_sl_roi * sl_modulation
                # ATR 基线下限保护（收紧不低于基线的 0.7 倍）
                new_sl_roi = YijingExitSystem.apply_atr_floor(new_sl_roi, base_sl_roi)
                new_sl_price = self._calc_sl_price(entry_price, pos_side, new_sl_roi, leverage)
                sl_price_change_pct = self._roi_to_price_change(new_sl_roi, leverage)
                self._log(
                    f"[{coin}] 易经主离场 [TIGHTEN_SL] {yijing_decision.reason} | "
                    f"卦象={yijing_decision.hexagram_name} 杠杆={leverage}x "
                    f"ATR基线={base_sl_roi:.2%} × 调制{sl_modulation:.2f} = {new_sl_roi:.2%} "
                    f"(价{sl_price_change_pct:.2%}) "
                    f"新止损={new_sl_price:.2f} 盈亏={upl:.2f}({upl_ratio:.2%})"
                )
                try:
                    sl_result = self.okx_client.place_stop_loss_take_profit(
                        inst_id=inst_id,
                        pos_side=pos_side,
                        stop_loss_px=new_sl_price,
                        take_profit_px=None,
                        reason=f"yijing_tighten_sl:{yijing_decision.reason}",
                    )
                    if sl_result.get("ok"):
                        self._log(f"[{coin}] 易经止损价已收紧至 {new_sl_price:.2f}")
                    else:
                        self._log(
                            f"[{coin}] 易经收紧止损失败: {sl_result.get('error', 'unknown')}",
                            "WARN",
                        )
                except Exception as e:
                    self._log(f"[{coin}] 易经收紧止损异常: {e}", "WARN")
                return

            # 6) 易经主决策 NO_INTERVENE：持仓<29h维持持仓，不降级classic
            #    v3.1: 经典离场仅在持仓>29h且易经离场不工作时启用（用户需求）
            #    持仓<29h时，NO_INTERVENE即维持持仓，仅依赖开仓静态SL/TP+易经动态调整
            if yijing_decision and yijing_decision.action == YijingExitAction.NO_INTERVENE:
                if not position_timed_out:
                    # 持仓<29h：维持持仓，不降级classic
                    self._log(
                        f"[{coin}] 易经主离场 [HOLD] {yijing_decision.reason} | "
                        f"卦象={yijing_decision.hexagram_name or '-'} "
                        f"风险={yijing_decision.yijing_risk_score:.2f} "
                        f"价值={yijing_decision.yijing_value_score:.2f} "
                        f"盈亏={upl:.2f}({upl_ratio:.2%}) 持仓={position_age_sec/3600:.1f}h "
                        f"行情={regime} | 维持持仓（<29h不启用经典备用）"
                    )
                    return
                # 持仓>29h但yijing仍返回NO_INTERVENE（防御性，正常超时后yijing_available=False）
                self._log(
                    f"[{coin}] 易经信号中性(超时>29h)，降级经典备用离场 | "
                    f"卦象={yijing_decision.hexagram_name or '-'} "
                    f"风险={yijing_decision.yijing_risk_score:.2f} "
                    f"价值={yijing_decision.yijing_value_score:.2f} "
                    f"盈亏={upl_ratio:.2%} 持仓={position_age_sec/3600:.1f}h"
                )
            elif not yijing_available:
                # yijing不可用有两种原因：超时(>29h) 或 无卦象数据
                if position_timed_out:
                    self._log(
                        f"[{coin}] 易经卦象不可用(超时>29h)，启用经典离场备用层 | "
                        f"盈亏={upl:.2f}({upl_ratio:.2%})",
                        "WARN",
                    )
                else:
                    self._log(
                        f"[{coin}] 易经卦象不可用(无卦象数据)，持仓<29h仅依赖静态SL/TP | "
                        f"盈亏={upl:.2f}({upl_ratio:.2%})",
                        "WARN",
                    )

            # ── v3.1: 备用离场层门禁 ──
            # 经典离场仅在持仓>29h且易经离场不工作时启用（用户需求）
            # 持仓<29h时完全跳过经典离场，仅依赖易经主离场+开仓静态SL/TP
            if not position_timed_out:
                # 持仓<29h：经典离场不启用，已通过上方HOLD return或yijing动态调整处理
                return

            # ── 备用离场层：经典指标离场（仅在持仓>29h且易经不工作时调用）──
            # v3.1: 到这里说明 position_timed_out=True（持仓>29h），classic 全四优先级启用
            # 短期修复 2：震荡市动态放宽止损（is_ranging / 弱趋势 → 止损更宽）
            # 注意：传入 dict（含 is_ranging/adx/trend_strength），而非字符串 regime
            self._adjust_exit_config_for_regime(
                {
                    "is_ranging": is_ranging,
                    "adx": float(inference.get("adx", 0) or 0),
                    "trend_strength": inference.get("trend_strength", 0.5),
                }
            )

            # 持仓>29h，classic 启用全部四大优先级（P0/P1/P2/P3）
            exit_decision = self.exit_system.evaluate_full(
                pos=exit_pos,
                candles_1h=candles_1h,
                regime=regime,
                p0_only=False,
            )

            # VETO_CLOSE/VETO_REDUCE 检查：classic 决定离场前，易经二次评估可否决
            # 注意：超时后 yijing_available=False，此否决分支不会触发
            if (
                yijing_available
                and yijing_decision
                and exit_decision.action in (ExitAction.CLOSE, ExitAction.REDUCE)
            ):
                veto_decision = self.yijing_exit_system.evaluate(
                    hexagram=yijing_hexagram,
                    pos_side=pos_side,
                    entry_price=float(entry_price) if entry_price else 0,
                    current_price=float(current_price),
                    position_age_sec=position_age_sec,
                    unrealized_pnl_pct=float(upl_ratio),
                    classic_decision=exit_decision,  # 传入 classic 决策用于否决判断
                    mfe_pnl_pct=max(0.0, float(upl_ratio)),
                    coin=coin,
                    open_time_sec=float(open_time) if open_time else 0.0,
                    mode="veto",  # P0修复：veto 模式绕过 1h 门禁 + 不写缓存，避免被主评估缓存吞掉
                )
                if veto_decision.action == YijingExitAction.VETO_CLOSE:
                    self._log(
                        f"[{coin}] 易经否决 [VETO_CLOSE] {veto_decision.reason} | "
                        f"卦象={veto_decision.hexagram_name} "
                        f"风险={veto_decision.yijing_risk_score:.2f} "
                        f"价值={veto_decision.yijing_value_score:.2f} "
                        f"经典离场原因={exit_decision.reason} "
                        f"盈亏={upl:.2f}({upl_ratio:.2%}) 持仓={position_age_sec/3600:.1f}h | "
                        f"否决 classic 离场，维持持仓"
                    )
                    return
                if veto_decision.action == YijingExitAction.VETO_REDUCE:
                    self._log(
                        f"[{coin}] 易经否决 [VETO_REDUCE] {veto_decision.reason} | "
                        f"卦象={veto_decision.hexagram_name} "
                        f"风险={veto_decision.yijing_risk_score:.2f} "
                        f"价值={veto_decision.yijing_value_score:.2f} "
                        f"经典减仓原因={exit_decision.reason} "
                        f"盈亏={upl:.2f}({upl_ratio:.2%}) | "
                        f"否决 classic 减仓，维持持仓"
                    )
                    return

            # 执行 classic 决策
            if exit_decision.action == ExitAction.CLOSE:
                self._log(
                    f"[{coin}] 经典备用离场 [CLOSE] {exit_decision.reason} | "
                    f"优先级={exit_decision.priority.value} "
                    f"置信度={exit_decision.confidence:.2f} "
                    f"盈亏={upl:.2f}({upl_ratio:.2%})"
                )
                if pos_side == "long":
                    r = self.okx_client.market_close_long(
                        inst_id, reason=f"经典备用离场:{exit_decision.reason}"
                    )
                else:
                    r = self.okx_client.market_close_short(
                        inst_id, reason=f"经典备用离场:{exit_decision.reason}"
                    )
                if r.get("ok") or r.get("dry_run"):
                    self._handle_close_position(
                        inst_id=inst_id,
                        coin=coin,
                        pos_side=pos_side,
                        exit_price=current_price,
                        exit_reason=f"classic_backup:{exit_decision.reason}",
                        pnl=upl,
                        pnl_pct=upl_ratio,
                    )
                return

            if exit_decision.action == ExitAction.REDUCE:
                self._log(
                    f"[{coin}] 经典备用离场 [REDUCE] {exit_decision.reason} | "
                    f"减仓比例={exit_decision.reduce_frac:.0%} "
                    f"盈亏={upl:.2f}({upl_ratio:.2%})"
                )
                reduce_result = self.okx_client.reduce_position(
                    inst_id=inst_id,
                    pos_side=pos_side,
                    reduce_ratio=exit_decision.reduce_frac,
                    reason=f"classic_backup:{exit_decision.reason}",
                )
                if reduce_result.get("ok"):
                    # E项优化：递增减仓次数并持久化
                    if tracker_pos:
                        tracker_pos.reduce_count += 1
                        self.position_tracker._save_open_position(inst_id)
                    self._log(
                        f"[{coin}] 减仓成功 | "
                        f"原持仓={reduce_result.get('original_pos')} "
                        f"减仓量={reduce_result.get('reduce_sz')} "
                        f"剩余={reduce_result.get('remaining_pos')} "
                        f"累计减仓={tracker_pos.reduce_count if tracker_pos else '?'}/{self.exit_system.config.max_reduce_count}"
                    )
                else:
                    self._log(f"[{coin}] 减仓失败: {reduce_result.get('error', 'unknown')}", "WARN")
                return

            if exit_decision.action == ExitAction.RAISE_TP:
                new_tp_price = exit_decision.new_tp_price
                new_tp_pct = exit_decision.new_tp_pct
                self._log(
                    f"[{coin}] 经典备用离场 [RAISE_TP] {exit_decision.reason} | "
                    f"新止盈={new_tp_price:.2f}({new_tp_pct:.2%}) "
                    f"盈亏={upl:.2f}({upl_ratio:.2%})"
                )
                try:
                    tp_result = self.okx_client.place_stop_loss_take_profit(
                        inst_id=inst_id,
                        pos_side=pos_side,
                        stop_loss_px=None,
                        take_profit_px=new_tp_price,
                        reason=f"raise_tp_backup:{exit_decision.reason}",
                    )
                    if tp_result.get("ok"):
                        self._log(f"[{coin}] 止盈价已上调至 {new_tp_price:.2f}")
                    else:
                        self._log(
                            f"[{coin}] 上调止盈失败: {tp_result.get('error', 'unknown')}", "WARN"
                        )
                except Exception as e:
                    self._log(f"[{coin}] 上调止盈异常: {e}", "WARN")
                return

            # 维持持仓日志（含易经风险评估）
            hold_risk = (
                exit_decision.features.hold_risk
                if exit_decision and exit_decision.features
                else 0.5
            )
            hold_value = (
                exit_decision.features.hold_value
                if exit_decision and exit_decision.features
                else 0.5
            )
            yijing_risk = yijing_decision.yijing_risk_score if yijing_decision else 0.5
            yijing_value = yijing_decision.yijing_value_score if yijing_decision else 0.5
            hex_display = (
                yijing_decision.hexagram_name if yijing_decision else "无卦象"
            ) or "无卦象"
            yijing_phase = (yijing_decision.current_phase if yijing_decision else "") or "-"
            self._log(
                f"[{coin}] 持仓中 {pos_side} | "
                f"浮动盈亏={upl:.2f}({upl_ratio:.2%}) | "
                f"卦象={hex_display} 易经风险={yijing_risk:.2f} 易经价值={yijing_value:.2f} "
                f"阶段={yijing_phase} "
                f"持有风险={hold_risk:.2f} 持有价值={hold_value:.2f} "
                f"行情={regime} | 维持持仓"
            )
            return

        trend_strength = inference.get("trend_strength", 0.5)
        ranging_confidence = inference.get("ranging_confidence", 0.0)
        is_trial = False

        # A项过滤：可配置 confidence 最低门槛（原贝叶斯寻优值 0.7955 改为可热 reload）
        # - 优先使用 self.confidence_threshold（构造参数 args.confidence
        #   → 被 _load_evolution_config 从 config.json 热 reload
        #   → 被 _adjust_confidence_threshold 按外部知识小幅上调）
        # - A_SAFETY_FLOOR = 0.40 兜底：防止进化配置损坏/参数手误传成 0.01 导致阈值失控
        #
        # 回测基线（原硬编码 0.7955）：过滤掉 37% 低质量交易，
        # 胜率 76.6% -> 84.8%，策略收益 5.23% -> 5.59%；
        # 当 config.json 的 confidence_threshold 偏离较大时，
        # 仍以 safety floor=0.40 作为最低边界。
        try:
            adjusted_threshold = self._adjust_confidence_threshold()
        except Exception:
            adjusted_threshold = self.confidence_threshold
        A_SAFETY_FLOOR = 0.70
        effective_a_floor = max(float(adjusted_threshold), A_SAFETY_FLOOR)
        if confidence < effective_a_floor:
            self._log(
                f"[{coin}] A项过滤 | confidence={confidence:.4f} < "
                f"effective_a_floor={effective_a_floor:.4f}("
                f"adjusted={adjusted_threshold:.4f}, safety_floor={A_SAFETY_FLOOR}) | "
                f"方向={direction} 卦象={inference['hexagram']} 跳过"
            )
            return

        # P0-3: 卦象黑名单 — 历史胜率0%的卦象强制HOLD
        hex_name = inference.get("hexagram", "")
        if hex_name in self.hexagram_blacklist:
            self._log(
                f"[{coin}] P0卦象黑名单 | {hex_name} 历史胜率0% | "
                f"confidence={confidence:.4f} 方向={direction} 跳过"
            )
            return

        # ===== 震荡市增强器（优化1-5统一入口）=====
        # 包含：
        #   优化1: MA200方向性偏向 + 阻力支撑确认
        #   优化2: 布林带双信号确认
        #   优化3: 动态止损宽度（震荡市2.5-3×ATR）
        #   优化4: 置信度校准（框架，数据积累后生效）
        #   优化5: 5种市场状态自适应
        enhance_result = None
        kline_data = inference.get("kline_data", [])
        if kline_data and len(kline_data) >= 20:
            try:
                closes = [float(c.get("c", 0)) for c in kline_data if c.get("c")]
                highs = [float(c.get("h", 0)) for c in kline_data if c.get("h")]
                lows = [float(c.get("l", 0)) for c in kline_data if c.get("l")]
                price = float(inference.get("price", 0))
                vol = inference.get("volatility", 0.03)
                atr_val = price * vol if price > 0 else 0

                if len(closes) >= 20 and price > 0:
                    enhance_result = self.ranging_enhancer.enhance(
                        price=price,
                        direction=direction,
                        confidence=confidence,
                        closes=closes,
                        highs=highs if len(highs) == len(closes) else None,
                        lows=lows if len(lows) == len(closes) else None,
                        atr=atr_val,
                        is_ranging=is_ranging,
                        ranging_confidence=ranging_confidence,
                        trend_strength=trend_strength,
                        coin=coin,
                    )
            except Exception as e:
                self._log(f"[{coin}] 增强器调用异常: {e}，回退到P0简单逻辑", "WARN")

        if enhance_result:
            # 记录市场状态
            regime_label = enhance_result.regime.value
            boll_sig = enhance_result.bollinger.signal.value
            self._log(
                f"[{coin}] 增强器 | 状态={regime_label} "
                f"布林信号={boll_sig} "
                f"偏向={enhance_result.directional_bias:+.2f} "
                f"止损={enhance_result.recommended_sl_atr_mult:.1f}×ATR"
            )

            # 保存增强结果到inference，供开仓时使用（动态止损）
            inference["enhance_result"] = {
                "regime": regime_label,
                "sl_atr_mult": enhance_result.recommended_sl_atr_mult,
                "tp_atr_mult": enhance_result.recommended_tp_atr_mult,
                "bollinger_signal": boll_sig,
                "bollinger_confirms": enhance_result.bollinger_confirms,
                "directional_bias": enhance_result.directional_bias,
                "ma200_above": enhance_result.mas.price_above_ma200,
            }

            # 更新有效阈值（增强器推荐的方向差异化阈值）
            if direction == "UP":
                effective_threshold = max(
                    effective_threshold, enhance_result.recommended_long_threshold
                )
            elif direction == "DOWN":
                effective_threshold = max(
                    effective_threshold, enhance_result.recommended_short_threshold
                )

            # 综合判断：是否应该开仓
            if not enhance_result.should_trade:
                self._log(
                    f"[{coin}] 增强器过滤 | 原因={enhance_result.reject_reason} "
                    f"置信度={confidence:.2f} 方向={direction} 卦象={inference['hexagram']} 跳过"
                )
                return
        else:
            # ===== 回退：P0简单逻辑（当增强器不可用时）=====
            if is_ranging and ranging_confidence >= 0.75:
                self._log(
                    f"[{coin}] P0-强震荡市强制空仓 | ranging_confidence={ranging_confidence:.2f} "
                    f"置信度={confidence:.2f} 方向={direction} 卦象={inference['hexagram']} 跳过"
                )
                return
            elif is_ranging and ranging_confidence >= 0.5:
                effective_threshold = max(effective_threshold, 0.7)
                self._log(
                    f"[{coin}] P0-中震荡市 | ranging_confidence={ranging_confidence:.2f} "
                    f"置信度要求提高至 {effective_threshold}"
                )
            elif is_ranging:
                effective_threshold = max(effective_threshold, 0.6)
                self._log(
                    f"[{coin}] P0-弱震荡市 | ranging_confidence={ranging_confidence:.2f} "
                    f"置信度要求提高至 {effective_threshold}"
                )
            elif trend_strength > 0.6:
                effective_threshold = max(0.3, self.confidence_threshold - 0.1)
                self._log(
                    f"[{coin}] 趋势明确(强度={trend_strength:.2f}) | 置信度要求放宽至 {effective_threshold}"
                )

        if fail_closed:
            # P0修复: fail-closed 硬约束，BCRM判定不交易则直接跳过，不用八卦方向软化
            bagua_dir = inference.get("bagua_direction", "neutral")
            self._log(
                f"[{coin}] fail-closed 跳过 | 卦象={inference['hexagram']} "
                f"BCRM不确定，不开仓 (八卦方向={bagua_dir} 不作为开仓依据)"
            )
            return

        # P1-1: 做空趋势过滤器（Phase C+ 五均线版）
        # 加密货币用BTC 5均线排列，美股用IXIC/GSPC 5均线，其他用自身5均线；+做空阈值乘数+仓位规模乘数
        short_conf_multi = 1.00
        short_bearish_score = "NONE"
        short_regime_from_spring = None
        if direction == "DOWN":
            # 兼容: 旧版返回2元组, 新版返回3元组(allow, reason, multiplier)
            filter_result = self._check_short_trend_filter(coin, inference)
            if len(filter_result) >= 3:
                trend_ok, trend_reason, short_conf_multi = filter_result
            else:
                trend_ok, trend_reason = filter_result
                short_conf_multi = 1.00
            short_bearish_score = self._parse_bearish_score_from_reason(trend_reason)
            short_regime_from_spring = self._parse_regime_from_reason(trend_reason)
            if not trend_ok:
                self._log(
                    f"[{coin}] P1做空趋势过滤 | {trend_reason} | "
                    f"置信度={confidence:.2f} 方向={direction} 卦象={inference['hexagram']} 跳过"
                )
                return
            # 做空阈值 = (short_confidence_threshold 或 confidence_threshold) × 乘数
            # 关键：×0.9091(STRONG)=降低门槛=放宽；×1.1765(WEAK)=抬高门槛=收紧
            raw_short_thr = max(
                confidence_threshold or self.confidence_threshold,
                self.short_confidence_threshold,
            )
            effective_short_threshold = raw_short_thr * short_conf_multi
            self._log(
                f"[{coin}] P1做空阈值分层 | 基础阈值={raw_short_thr:.4f} ×{short_conf_multi:.2f}"
                f" = 有效阈值={effective_short_threshold:.4f}",
                "INFO",
            )
            # 覆盖全局 effective_threshold（仅DOWN方向有效）
            effective_threshold = effective_short_threshold

        # H1(P0)新增：P1 长多趋势过滤器（与做空对称，UP方向弹簧力场阈值分层）
        long_conf_multi = 1.00
        long_bullish_score = "NONE"
        long_regime_from_spring = None
        if direction == "UP":
            filter_result = self._check_long_trend_filter(coin, inference)
            if len(filter_result) >= 3:
                trend_ok_up, trend_reason_up, long_conf_multi = filter_result
            else:
                trend_ok_up, trend_reason_up = filter_result
                long_conf_multi = 1.00
            long_bullish_score = self._parse_bullish_score_from_reason(trend_reason_up)
            long_regime_from_spring = self._parse_regime_from_reason(trend_reason_up)
            if not trend_ok_up:
                self._log(
                    f"[{coin}] P1长多趋势过滤 | {trend_reason_up} | "
                    f"置信度={confidence:.2f} 方向={direction} 卦象={inference['hexagram']} 跳过"
                )
                return
            raw_long_thr = confidence_threshold or self.confidence_threshold
            effective_long_threshold = raw_long_thr * long_conf_multi
            self._log(
                f"[{coin}] P1长多阈值分层 | 基础阈值={raw_long_thr:.4f} ×{long_conf_multi:.2f}"
                f" = 有效阈值={effective_long_threshold:.4f}",
                "INFO",
            )
            effective_threshold = effective_long_threshold

        # H2(P1)：弹簧力场 5态/评分 双向写入 inference，后续 _get_regime_pred_multipliers / AB审计 可追溯
        spring_regime_5 = long_regime_from_spring if direction == "UP" else (short_regime_from_spring if direction == "DOWN" else None)
        if spring_regime_5:
            inference["spring_regime_5"] = spring_regime_5
        if direction == "UP" and long_bullish_score:
            inference["spring_bullish_score"] = long_bullish_score
        if direction == "DOWN" and short_bearish_score:
            inference["spring_bearish_score"] = short_bearish_score

        # P2-05: 形态乘数作用到置信度阈值（放在所有阈值调整之后、最终比对之前）
        #   高风险 regime（VOLATILE_DROP/FOMO_RALLY）抬高门槛，强势趋势放宽门槛
        _reg_mult = inference.get("_regime_multipliers", {})
        _thr_mult = _reg_mult.get("threshold_mult", 1.0)
        if _thr_mult != 1.0:
            _orig_thr = effective_threshold
            effective_threshold = effective_threshold * _thr_mult
            self._log(
                f"[{coin}] 形态阈值调整 | regime={inference.get('_regime_pred','')} ×{_thr_mult:.2f}"
                f" 阈值 {_orig_thr:.4f}→{effective_threshold:.4f}",
                "INFO",
            )

        # ── H3-FMA 影子决策：无论当前 FMA_REGIME_FILTER_ENABLED 是否开启，
        #    强制跑一遍 FMA=True 的差异化过滤流程，得到 fma_on_allow + fma_on_effective_threshold
        #    写入 inference.fma_shadow_* 供 ShadowLogger 入库 → 未来评估 FMA 渐进自动开关。
        fma_shadow_allowed = None
        fma_shadow_eff_thr = None
        try:
            # 当前实际生效的 effective_threshold（作为 FMA=ON 的保底 baseline 阈值）
            _fma_shadow_base_thr = float(effective_threshold)
            if direction == "UP":
                _fma_res = self._check_long_trend_filter(coin, inference, _force_regime_filter_on=True)
                if len(_fma_res) >= 3:
                    _fma_ok, _fma_reason, _fma_conf_multi = _fma_res
                else:
                    _fma_ok, _fma_reason = _fma_res
                    _fma_conf_multi = 1.00
                if _fma_ok:
                    _raw_thr = (confidence_threshold or self.confidence_threshold) * _fma_conf_multi
                    # 再 × 形态乘数（完全对称上方实际阈值）
                    _fma_eff = _raw_thr * float(_thr_mult or 1.0)
                    fma_shadow_allowed = True
                    fma_shadow_eff_thr = round(_fma_eff, 6)
                else:
                    fma_shadow_allowed = False
                    fma_shadow_eff_thr = _fma_shadow_base_thr
            elif direction == "DOWN":
                _fma_res = self._check_short_trend_filter(coin, inference, _force_regime_filter_on=True)
                if len(_fma_res) >= 3:
                    _fma_ok, _fma_reason, _fma_conf_multi = _fma_res
                else:
                    _fma_ok, _fma_reason = _fma_res
                    _fma_conf_multi = 1.00
                if _fma_ok:
                    _raw_thr = max(
                        confidence_threshold or self.confidence_threshold,
                        self.short_confidence_threshold,
                    ) * _fma_conf_multi
                    _fma_eff = _raw_thr * float(_thr_mult or 1.0)
                    fma_shadow_allowed = True
                    fma_shadow_eff_thr = round(_fma_eff, 6)
                else:
                    fma_shadow_allowed = False
                    fma_shadow_eff_thr = _fma_shadow_base_thr
            else:
                fma_shadow_allowed = False
                fma_shadow_eff_thr = _fma_shadow_base_thr
        except Exception as _ef:
            self._log(f"[{coin}] FMA影子决策计算失败(已忽略): {_ef}", "DEBUG")
        inference["fma_shadow_allowed"] = fma_shadow_allowed
        inference["fma_shadow_eff_threshold"] = fma_shadow_eff_thr

        # 做空试错区间更窄（减少低置信度做空）
        if direction == "DOWN":
            trial_threshold = max(0.40, effective_threshold - 0.10)
        else:
            trial_threshold = max(0.25, effective_threshold - 0.15)
        if confidence >= effective_threshold:
            pass
        elif confidence >= trial_threshold:
            is_trial = True
            self._log(
                f"[{coin}] 轻仓试错模式 | 置信度={confidence:.2f} 在试错区间 [{trial_threshold}, {effective_threshold}) 方向={direction}"
            )
        else:
            self._log(
                f"[{coin}] 置信度不足 "
                f"{confidence:.2f} < {trial_threshold} | "
                f"方向={direction} 卦象={inference['hexagram']}"
            )
            return

        if direction not in ("UP", "DOWN"):
            self._log(f"[{coin}] 方向不明确 {direction} 跳过")
            return

        risk_check = self.risk_manager.can_trade(self.perf_tracker.current_equity)
        if not risk_check["allowed"]:
            self._log(f"[{coin}] 风控拦截: {risk_check['reason']}", "WARN")
            return

        if self._count_total_positions() >= self.max_positions:
            self._log(f"[{coin}] 已达最大持仓数 {self.max_positions} 跳过")
            return

        self._open_position(inference, is_reverse=False, is_trial=is_trial)

    def _open_position(self, inference: dict, is_reverse: bool = False, is_trial: bool = False):
        """开仓（动态仓位 + 持仓跟踪）"""
        coin = inference["coin"]
        inst_id = inference["inst_id"]
        direction = inference["direction"]
        confidence = inference["confidence"]
        volatility = inference.get("volatility", 0.03)
        # P3: 缓存当前波动率，供 _compute_p2_dynamic_sizing_factors 中波动率自适应使用
        self._last_volatility = volatility

        # H1/H2/H4: 从 inference 读取前置层已缓存的弹簧评分/5态（避免 _open_position 访问不到 _execute_trade 局部变量）
        #   若 inference 未填（如手工调用 _open_position），则安全回退 "NONE"，仓位乘数保持 1.0
        short_bearish_score = inference.get("spring_bearish_score", "NONE") or "NONE"
        long_bullish_score = inference.get("spring_bullish_score", "NONE") or "NONE"

        leverage = self.okx_client.cfg.get("default_leverage", 3)
        td_mode = self.okx_client.cfg.get("td_mode", "isolated")

        # v4 风险评分风控：杠杆调整
        leverage_factor = inference.get("leverage_factor", 1.0)
        effective_leverage = max(1, round(leverage * leverage_factor))
        risk_level = inference.get("risk_level", "NORMAL")
        if leverage_factor != 1.0:
            self._log(
                f"[{coin}] v4杠杆调整 | risk_level={risk_level} factor={leverage_factor:.2f} "
                f"leverage {leverage}→{effective_leverage}",
                "INFO",
            )

        balance = self.okx_client.get_balance()

        available_equity = self.perf_tracker.current_equity
        if balance.get("ok"):
            avail_usdt = balance.get("assets", {}).get("USDT", {}).get("avail", 0)
            if td_mode == "isolated":
                available_equity = avail_usdt
            else:
                total_eq = balance.get("total_eq", 0)
                pos_result = self.okx_client.get_positions()
                total_imr = 0
                if pos_result.get("ok"):
                    for p in pos_result.get("positions", []):
                        if float(p.get("pos", 0)) > 0:
                            total_imr += float(p.get("imr", 0))
                available_equity = total_eq - total_imr

        # P2+P3 动态仓位：计算四因子（凯利/连亏/卦象/波动率）并注入 calc_position_size
        # 样本量阈值 5 笔（启动初期不足 5 笔时，凯利=1.0 保持保守默认）
        p2_hex = inference.get("hexagram", "") or ""
        p2_f = self._compute_p2_dynamic_sizing_factors(p2_hex, lookback=30, min_samples=5)

        pos_size_info = self.risk_manager.calc_position_size(
            confidence=confidence,
            volatility=volatility,
            current_equity=available_equity,
            kelly_factor=p2_f["kelly_factor"],
            consecutive_loss_factor=p2_f["consecutive_loss_factor"],
            hexagram_factor=p2_f["hexagram_factor"],
            vol_regime_factor=p2_f["vol_regime_factor"],
        )
        position_usdt = pos_size_info["position_usdt"]
        position_pct = pos_size_info["position_pct"]

        # P2+P3 动态仓位：日志输出
        try:
            self._log(
                f"[{coin}] P3动态仓位 | 卦={p2_hex}({p2_f['hexagram_class']}) "
                f"凯利={p2_f['kelly_factor']:.2f}(wr={p2_f['win_rate']:.0%} "
                f"avg_win={p2_f['avg_win']:.2f} avg_loss={p2_f['avg_loss']:.2f}) "
                f"连亏={p2_f['loss_streak']}(×{p2_f['consecutive_loss_factor']:.2f}) "
                f"卦象系数=×{p2_f['hexagram_factor']:.2f} "
                f"波动率={volatility:.4f}({p2_f['vol_regime_class']},×{p2_f['vol_regime_factor']:.2f},"
                f"SL={p2_f['vol_adaptive_sl_mult']:.1f}×ATR TP={p2_f['vol_adaptive_tp_mult']:.1f}×ATR) "
                f"P3基准倍率=×{pos_size_info.get('p2_base_multiplier', 1.0):.2f} "
                f"-> {position_usdt:.2f}USDT ({position_pct:.1%})",
                "INFO",
            )
        except Exception:
            pass

        if is_trial:
            position_usdt *= 0.4
            position_pct *= 0.4

        # Phase C+: 做空仓位规模分层（弹簧力场→仓位）
        # 理论：周期短可信度低但识别早 → 不禁开，而是控制资金规模
        #       跌破更多均线 → 弹簧压力更重 → 仓位更大
        if direction == "DOWN" and short_bearish_score != "NONE":
            pos_multi = self._compute_short_position_multiplier(short_bearish_score)
            old_usdt = position_usdt
            position_usdt *= pos_multi
            position_pct *= pos_multi
            self._log(
                f"[{coin}] P1做空仓位分层 | score={short_bearish_score} ×{pos_multi:.1f} "
                f"仓位 {old_usdt:.2f}→{position_usdt:.2f}USDT",
                "INFO",
            )

        # H4(P2): 长多仓位规模分层（弹簧力场→仓位，与做空方向对称）
        #   score=STRONG/NORMAL/WEAK → ×1.0/0.7/0.4 保守策略；避免追顶
        if direction == "UP" and long_bullish_score != "NONE":
            pos_multi = self._compute_long_position_multiplier(long_bullish_score)
            old_usdt = position_usdt
            position_usdt *= pos_multi
            position_pct *= pos_multi
            self._log(
                f"[{coin}] P1长多仓位分层 | score={long_bullish_score} ×{pos_multi:.1f} "
                f"仓位 {old_usdt:.2f}→{position_usdt:.2f}USDT",
                "INFO",
            )

        # v4 风险评分风控：仓位调整
        position_factor = inference.get("position_factor", 1.0)
        if position_factor != 1.0:
            old_usdt = position_usdt
            position_usdt *= position_factor
            position_pct *= position_factor
            self._log(
                f"[{coin}] v4仓位调整 | risk_level={risk_level} factor={position_factor:.2f} "
                f"仓位 {old_usdt:.2f}→{position_usdt:.2f}USDT",
                "INFO",
            )

        # P2-05: 形态乘数 → 仓位规模（乘在所有仓位调整之后，最终下单前）
        _reg_mult = inference.get("_regime_multipliers", {})
        _pos_mult = _reg_mult.get("position_mult", 1.0)
        _regime_pred = inference.get("_regime_pred")
        if _pos_mult != 1.0:
            _old = position_usdt
            position_usdt *= _pos_mult
            position_pct *= _pos_mult
            self._log(
                f"[{coin}] 形态仓位调整 | regime={_regime_pred or ''} ×{_pos_mult:.2f}"
                f" 仓位 {_old:.2f}→{position_usdt:.2f}USDT",
                "INFO",
            )

        action = "open_long" if direction == "UP" else "open_short"
        pos_side = "long" if direction == "UP" else "short"
        sl_px = inference["stop_loss_px"]
        tp_px = inference["take_profit_px"]
        price = inference["price"]

        # v4 风险评分风控：止损收紧
        sl_tighten_factor = inference.get("sl_tighten_factor", 1.0)
        if sl_tighten_factor < 1.0 and sl_px and price > 0:
            old_sl = sl_px
            sl_px = round(price + (sl_px - price) * sl_tighten_factor, 4)
            self._log(
                f"[{coin}] v4止损收紧 | factor={sl_tighten_factor:.2f} SL {old_sl}→{sl_px}", "WARN"
            )

        # P2-05: 形态乘数 → SL/TP 价格距离（乘在所有 v4 风控之后，SLTP 冻结前）
        #   VOLATILE_DROP → sl_mult=0.65（紧止损）、TREND_UP_STRONG → tp_mult=1.30（放止盈）
        _sl_mult = _reg_mult.get("sl_mult", 1.0)
        _tp_mult = _reg_mult.get("tp_mult", 1.0)
        if _sl_mult != 1.0 and sl_px and price > 0:
            _old_sl = sl_px
            sl_px = round(price + (sl_px - price) * _sl_mult, 6)
            self._log(
                f"[{coin}] 形态SL调整 | regime={_regime_pred or ''} ×{_sl_mult:.2f}"
                f" SL {_old_sl}→{sl_px}",
                "INFO",
            )
        if _tp_mult != 1.0 and tp_px and price > 0:
            _old_tp = tp_px
            tp_px = round(price + (tp_px - price) * _tp_mult, 6)
            self._log(
                f"[{coin}] 形态TP调整 | regime={_regime_pred or ''} ×{_tp_mult:.2f}"
                f" TP {_old_tp}→{tp_px}",
                "INFO",
            )

        # v4 风险评分风控：止盈调整
        tp_adjustment = inference.get("tp_adjustment", 1.0)
        if tp_adjustment != 1.0 and tp_px and price > 0:
            old_tp = tp_px
            tp_px = round(price + (tp_px - price) * tp_adjustment, 4)
            self._log(
                f"[{coin}] v4止盈调整 | factor={tp_adjustment:.2f} TP {old_tp}→{tp_px}", "INFO"
            )

        # ── v4 风险评分：汇总级（即便全=1.0 也打印一次，方便审计「前置层评分功能已跑」）
        try:
            lf = float(inference.get("leverage_factor", 1.0))
            pf = float(inference.get("position_factor", 1.0))
            stf = float(inference.get("sl_tighten_factor", 1.0))
            taf = float(inference.get("tp_adjustment", 1.0))
            rl = inference.get("risk_level", "NORMAL") or "NORMAL"
            if lf == 1.0 and pf == 1.0 and stf == 1.0 and taf == 1.0:
                self._log(
                    f"[{coin}] v4风险评分中性 | risk_level={rl} "
                    f"lev×{lf:.2f} pos×{pf:.2f} sl×{stf:.2f} tp×{taf:.2f}（无异常收紧/放宽）",
                    "INFO",
                )
        except Exception:
            pass

        # 优化3：动态止损宽度（如果增强器有推荐，覆盖默认值）
        # 关键口径：先按"订单收益率"定义，再通过 leverage 换算成价格
        #   ATR 倍数（市场态）→ 价格波动% → 订单收益率% = 价格波动% × leverage
        # 2026-08-06 上调：默认倍率 1.5/3.0 → 2.5/5.0，与 ExitConfig/BCRM2_ATR 口径保持一致
        enhance_info = inference.get("enhance_result")
        if enhance_info and price > 0 and volatility > 0:
            sl_mult = enhance_info.get("sl_atr_mult", 2.5)
            tp_mult = enhance_info.get("tp_atr_mult", 5.0)
            price * volatility
            if sl_mult != 1.5 or tp_mult != 3.0:
                # 1) 先按"订单收益率"定义：1.5×ATR → 价格波动 sl_mult×volatility
                #    对应订单止损收益率 = sl_mult × volatility × leverage
                sl_price_change_pct = sl_mult * volatility
                tp_price_change_pct = tp_mult * volatility
                sl_roi_pct = self._price_change_to_roi(sl_price_change_pct, leverage)
                tp_roi_pct = self._price_change_to_roi(tp_price_change_pct, leverage)
                # 2) 由订单收益率 + 入场价反推止损止盈价
                if direction == "UP":
                    new_sl = self._calc_sl_price(price, "long", sl_roi_pct, leverage)
                    new_tp = self._calc_tp_price(price, "long", tp_roi_pct, leverage)
                else:
                    new_sl = self._calc_sl_price(price, "short", sl_roi_pct, leverage)
                    new_tp = self._calc_tp_price(price, "short", tp_roi_pct, leverage)
                if new_sl > 0 and new_tp > 0:
                    old_sl_pct = abs(sl_px - price) / price * 100 if sl_px else 0
                    abs(new_sl - price) / price * 100
                    sl_px = new_sl
                    tp_px = new_tp
                    self._log(
                        f"[{coin}] 动态止损 | {enhance_info.get('regime','')} "
                        f"杠杆={leverage}x "
                        f"SL={sl_mult:.1f}×ATR(订单亏{sl_roi_pct:.2%}/价格{sl_price_change_pct:.2%}) "
                        f"TP={tp_mult:.1f}×ATR(订单盈{tp_roi_pct:.2%}/价格{tp_price_change_pct:.2%}) "
                        f"(原SL={old_sl_pct:.1f}%)"
                    )

        # 输出：换算订单收益率（杠杆×价格波动%）
        # 同时记录 ATR 基线 SL/TP 收益率，供易经离场系统调制使用
        base_sl_roi = 0.0
        base_tp_roi = 0.0
        if price > 0 and leverage > 0 and sl_px and tp_px:
            sl_pct = abs(sl_px - price) / price
            tp_pct = abs(tp_px - price) / price
            sl_roi = self._price_change_to_roi(sl_pct, leverage)
            tp_roi = self._price_change_to_roi(tp_pct, leverage)
            # 记录 ATR 基线 ROI（供易经离场系统 1h 后调制使用）
            base_sl_roi = sl_roi
            base_tp_roi = tp_roi
            if pos_side == "long":
                sl_label = f"亏{sl_roi:.2%}(价{sl_pct:.2%})"
                tp_label = f"盈{tp_roi:.2%}(价{tp_pct:.2%})"
            else:
                sl_label = f"亏{sl_roi:.2%}(价{sl_pct:.2%})"
                tp_label = f"盈{tp_roi:.2%}(价{tp_pct:.2%})"
            self._log(
                f"[{coin}] {'反手' if is_reverse else ''}开仓 {'[轻仓试错]' if is_trial else ''} {action} | "
                f"置信度={confidence:.2f}(factor={pos_size_info.get('confidence_factor', 0):.2f}) "
                f"卦象={inference['hexagram']} 杠杆={leverage}x | "
                f"仓位={position_usdt:.2f}USDT ({position_pct:.1%}) | "
                f"价格={inference['price']} SL={sl_px}({sl_label}) TP={tp_px}({tp_label}) | "
                f"原因={pos_size_info['reason']} | "
                f"可用余额={available_equity:.2f}USDT"
            )
        else:
            self._log(
                f"[{coin}] {'反手' if is_reverse else ''}开仓 {'[轻仓试错]' if is_trial else ''} {action} | "
                f"置信度={confidence:.2f}(factor={pos_size_info.get('confidence_factor', 0):.2f}) "
                f"卦象={inference['hexagram']} 杠杆={leverage}x | "
                f"仓位={position_usdt:.2f}USDT ({position_pct:.1%}) | "
                f"价格={inference['price']} 止损={sl_px} 止盈={tp_px} | "
                f"原因={pos_size_info['reason']} | "
                f"可用余额={available_equity:.2f}USDT"
            )

        margin_needed = position_usdt / leverage

        if balance.get("ok"):
            total_eq = balance.get("total_eq", 0)
            avail_usdt = balance.get("assets", {}).get("USDT", {}).get("avail", 0)

            if td_mode == "isolated":
                if margin_needed > avail_usdt:
                    self._log(
                        f"[{coin}] 可用保证金不足（逐仓） | 需要={margin_needed:.2f}USDT 可用={avail_usdt:.2f}USDT 总权益={total_eq:.2f}USDT 杠杆={leverage}x 跳过",
                        "WARN",
                    )
                    return
            else:
                pos_result = self.okx_client.get_positions()
                total_imr = 0
                if pos_result.get("ok"):
                    for p in pos_result.get("positions", []):
                        if float(p.get("pos", 0)) > 0:
                            total_imr += float(p.get("imr", 0))

                cross_available = total_eq - total_imr

                if margin_needed > cross_available:
                    self._log(
                        f"[{coin}] 可用保证金不足（全仓） | 需要={margin_needed:.2f}USDT 可用={cross_available:.2f}USDT 总权益={total_eq:.2f}USDT 已用IMR={total_imr:.2f}USDT 杠杆={leverage}x 跳过",
                        "WARN",
                    )
                    return

        # 检查下单量是否满足最小合约单位
        sz = self.okx_client._usdt_to_sz(inst_id, position_usdt)
        if sz <= 0:
            self._log(
                f"[{coin}] 下单量不足最小合约单位 | 金额={position_usdt:.2f}USDT 跳过", "WARN"
            )
            return

        if direction == "UP":
            order_result = self.okx_client.market_open_long(
                inst_id, usdt_amount=position_usdt, reason=f"yijing_open_long conf={confidence:.2f}"
            )
        else:
            order_result = self.okx_client.market_open_short(
                inst_id,
                usdt_amount=position_usdt,
                reason=f"yijing_open_short conf={confidence:.2f}",
            )

        ok = order_result.get("ok", False)
        ord_id = order_result.get("ord_id", "") or order_result.get("ordId", "")
        entry_price = order_result.get("estimated_price", inference["price"])

        if ok or order_result.get("dry_run"):
            self.position_tracker.open_position(
                coin=coin,
                inst_id=inst_id,
                direction=pos_side,
                entry_price=entry_price,
                confidence=confidence,
                hexagram=inference["hexagram"],
                liangyi_state=inference.get("liangyi_state"),
                scale_params=inference.get("scale_params"),
                market_snapshot=inference.get("snapshot"),
                contradiction_list=inference.get("contradictions"),
                enhance_info=inference.get("enhance_result"),
                base_sl_roi=base_sl_roi,
                base_tp_roi=base_tp_roi,
                regime_pred=inference.get("_regime_pred"),
                regime_multipliers=inference.get("_regime_multipliers"),
            )
            self._log(f"[{coin}] 开仓成功 | ordId={ord_id} | " f"入场价≈{entry_price}")

            # L4 轻量开仓事件（M0 注册预览 + A0 创伤追踪）
            self._record_opening_event(inference, entry_price, pos_side, confidence)

            if sl_px and tp_px:
                sltp_result = self.okx_client.place_stop_loss_take_profit(
                    inst_id=inst_id,
                    pos_side=pos_side,
                    stop_loss_px=sl_px,
                    take_profit_px=tp_px,
                    sz=sz,
                    reason="yijing_risk_management",
                )
                if sltp_result.get("ok"):
                    self._log(f"[{coin}] 止盈止损已设置 | SL={sl_px} TP={tp_px}")
                else:
                    self._log(
                        f"[{coin}] 止盈止损设置失败 | SL={sl_px} TP={tp_px} | "
                        f"错误={sltp_result.get('error', sltp_result.get('msg', 'unknown'))}",
                        "ERROR",
                    )
        else:
            err = order_result.get("error", "") or order_result.get("sMsg", "")
            self._log(f"[{coin}] 开仓失败 | {err}", "ERROR")
            if self.guardian:
                self.guardian.record_error(
                    RuntimeError(f"开仓失败: {err}"), context=f"open_position:{coin}"
                )

    def _inject_cognitive_recall(self, coin: str, inference: dict) -> dict:
        """
        P3: 构建交易上下文并调用认知系统召回，返回认知建议。

        设计原则:
          - 建议而非约束: 召回结果注入 inference，不阻断交易决策
          - 失败安全: 认知系统不可用时返回空结果，不影响交易
          - 上下文构建: 从 inference 提取关键字段组装召回上下文
        """
        if not self._trading_recall_fn:
            return {"ok": False, "reason": "recall_fn not initialized"}

        # 构建召回上下文（从 inference 提取关键字段）
        direction = inference.get("direction", "")
        confidence = inference.get("confidence", 0.0)
        hexagram = inference.get("hexagram", "")
        is_ranging = inference.get("is_ranging", False)
        volatility = inference.get("volatility", 0.0)
        a0_warnings = inference.get("a0_warnings", [])

        ctx_parts = [f"{coin}", f"方向={direction}", f"置信度={confidence:.2f}"]
        if hexagram:
            ctx_parts.append(f"卦象={hexagram}")
        if is_ranging:
            ctx_parts.append("震荡市场")
        if volatility > 0:
            ctx_parts.append(f"波动率={volatility:.4f}")
        if a0_warnings:
            ctx_parts.append(f"矛盾预警={len(a0_warnings)}项")
        context = " ".join(ctx_parts)

        try:
            result = self._trading_recall_fn(
                context=context,
                task_type="strategy-execution",
                top_k_mem=3,
                top_meta=2,
                top_applied=2,
            )
            if result.get("ok"):
                mem_count = result.get("count", 0)
                meta_count = len(result.get("processes", {}).get("meta", []))
                applied_count = len(result.get("processes", {}).get("applied", []))
                self._log(
                    f"[{coin}] P3认知召回: 记忆={mem_count}条 | "
                    f"T系列Skill={meta_count}个 | 历史路径={applied_count}条",
                    "INFO",
                )
            return result
        except Exception as e:
            self._log(f"[{coin}] P3认知召回失败: {e}", "WARN")
            return {"ok": False, "error": str(e)}

    @staticmethod
    def _summarize_cognitive_recall(inference: dict) -> dict:
        """P3: 从 inference 中提取认知召回摘要（轻量，供开仓事件存档）"""
        cr = inference.get("cognitive_recall")
        if not cr or not cr.get("ok"):
            return {"ok": False}
        return {
            "ok": True,
            "mem_count": cr.get("count", 0),
            "meta_skills": [m.get("skill_id") for m in cr.get("processes", {}).get("meta", [])],
            "applied_count": len(cr.get("processes", {}).get("applied", [])),
        }

    def _record_opening_event(
        self, inference: dict, entry_price: float, pos_side: str, confidence: float
    ):
        """开仓时轻量记录：A0 创伤追踪 + 开仓事件存档（供平仓后 L4 使用）"""
        import json
        from datetime import datetime

        coin = inference.get("coin", "")
        inst_id = inference.get("inst_id", "")
        direction = inference.get("direction", "")

        # A0 创伤追踪：记录决策方向（平仓后会更新对错）
        try:
            from scripts.memory_l4.a0_contradiction_engine import A0ContradictionEngine

            if not hasattr(self, "_a0_engine"):
                self._a0_engine = A0ContradictionEngine()
            self._a0_engine.record_decision(
                inst_id=inst_id,
                direction=direction,
                was_correct=True,  # 开仓时未知，平仓后更新
                ts=datetime.now().isoformat(),
            )
        except Exception:
            pass

        # 轻量开仓事件存档
        try:
            # P2-9: 事前预测（对齐 Friston 主动推理，失败静默不阻断开仓记录）
            prediction_data = None
            try:
                from scripts.memory_l4.prediction_bridge import generate_prediction_dict

                prediction_data = generate_prediction_dict(inference)
            except Exception:
                pass

            event = {
                "ts": datetime.now().isoformat(),
                "type": "position_opened",
                "inst_id": inst_id,
                "coin": coin,
                "direction": direction,
                "pos_side": pos_side,
                "entry_price": entry_price,
                "confidence": confidence,
                "a0_analysis": inference.get("a0_analysis"),
                "a0_warnings": inference.get("a0_warnings", []),
                "volatility": inference.get("volatility", 0),
                "hexagram": inference.get("hexagram", ""),
                # P3: 认知召回摘要（供平仓后 L4 回溯分析）
                "cognitive_recall": self._summarize_cognitive_recall(inference),
                # P2-9: 事前预测快照（供平仓后计算 prediction_error 驱动贝叶斯）
                "prediction": prediction_data,
            }
            event_dir = (
                Path(self.data_dir) / "l4_events"
                if hasattr(self, "data_dir")
                else Path("data/l4_events")
            )
            event_dir.mkdir(parents=True, exist_ok=True)
            event_file = event_dir / f"open_{inst_id}_{int(datetime.now().timestamp())}.json"
            event_file.write_text(json.dumps(event, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _load_external_knowledge(self):
        """加载 AB Trading 导出的外部知识"""
        try:
            self.external_knowledge = self.knowledge_bridge.get_knowledge_summary()
            if self.external_knowledge["evolved_params_count"] > 0:
                self._log(
                    f"[外部知识] 已加载 {self.external_knowledge['evolved_params_count']} 个进化参数 | "
                    f"灵敏度={self.external_knowledge['trend_sensitivity']:.2f} | "
                    f"风险厌恶={self.external_knowledge['risk_aversion']:.2f} | "
                    f"市场倾向={self.external_knowledge['market_bias']}"
                )
        except Exception as e:
            self._log(f"[外部知识] 加载失败: {e}", "ERROR")
            self.external_knowledge = {}

    def _infer_current_hexagram(self, coin: str, inference: dict, kline_data: list):
        """离场时推理当前卦象（轻量级，复用 YijingEngine + HexagramKnowledge）

        P1修复：
        - 优先复用开仓时的卦象名（inference["hexagram"]），保证卦象一致性
        - 从 HexagramKnowledge 获取固有的 risk_level/direction_hint（不依赖简化参数）
        - 用 YijingEngine.infer() 推理 current_phase/development_stage（动态判断）
        - 修正 supply_demand/capital_flow 不再固定0.5，改用价格位置+成交量比

        失败时返回 None（YijingExitSystem 会 fail-open 不干预）
        """
        try:
            from scripts.memory_l4.bcrm.sixty_four_guas import get_hexagram_knowledge
            from scripts.memory_l4.bcrm.yijing_engine import YijingEngine

            if not hasattr(self, "_yijing_engine_for_exit"):
                self._yijing_engine_for_exit = YijingEngine()

            # 从 inference 提取可用字段
            trend_strength = float(inference.get("trend_strength", 0.5) or 0.5)
            volatility = float(inference.get("volatility", 0.03) or 0.03)
            confidence = float(inference.get("confidence", 0.5) or 0.5)
            is_ranging = bool(inference.get("is_ranging", False))
            current_price = float(inference.get("price", 0) or 0)
            # 开仓时已推理的卦象名（如"巽为风"）
            hex_name_cn = inference.get("hexagram", "") or ""

            # ── 价格位置 + 成交量比（不再固定0.5）──
            price_position = 0.5
            volume_ratio = 1.0
            closes = []
            if kline_data and len(kline_data) >= 20 and current_price > 0:
                try:
                    closes = [float(c.get("c", 0)) for c in kline_data[-20:]]
                    if closes and max(closes) > min(closes):
                        price_position = (current_price - min(closes)) / (max(closes) - min(closes))
                        price_position = max(0.0, min(1.0, price_position))
                    # 成交量比：近5根 vs 前20根均值
                    vols = [float(c.get("v", 0)) for c in kline_data[-20:]]
                    if vols and len(vols) >= 10:
                        recent_vol = sum(vols[-5:]) / 5
                        base_vol = sum(vols[:-5]) / max(len(vols) - 5, 1)
                        volume_ratio = recent_vol / base_vol if base_vol > 0 else 1.0
                except Exception:
                    pass

            # 供需评分：价格位置 >0.7 偏多，<0.3 偏空，中间中性
            supply_demand_score = max(0.0, min(1.0, price_position))
            # 资金面：放量=资金流入，缩量=流出
            capital_flow_score = max(0.0, min(1.0, 0.5 + (volume_ratio - 1.0) * 0.3))
            # 技术面
            technical_score = max(0.0, min(1.0, trend_strength))
            # 情绪面
            sentiment_score = max(
                0.0, min(1.0, confidence * 0.7 + (0.3 if not is_ranging else 0.1))
            )
            vol_norm = max(0.0, min(1.0, volatility * 20))

            # ── 用 YijingEngine 推理 current_phase / development_stage ──
            result = self._yijing_engine_for_exit.infer(
                supply_demand_score=supply_demand_score,
                technical_score=technical_score,
                capital_flow_score=capital_flow_score,
                sentiment_score=sentiment_score,
                trend_strength=trend_strength,
                volatility=vol_norm,
                volume_ratio=volume_ratio,
                price_position=price_position,
                close_price=current_price,
            )

            # ── P1修复：用 HexagramKnowledge 覆盖固有属性（risk_level/direction_hint）──
            # YijingEngine.infer() 用简化参数推理时，risk_level 可能不准
            # HexagramKnowledge 的 risk_level/direction_hint 是卦象固有属性，更可靠
            if hex_name_cn and hex_name_cn != "已存在持仓":
                hex_kb = get_hexagram_knowledge(hex_name_cn)
                if hex_kb:
                    # 覆盖固有属性
                    result.risk_level = hex_kb.risk_level or result.risk_level
                    result.direction_hint = hex_kb.direction_hint or result.direction_hint
                    # 确保 hexagram_name_cn 一致
                    result.hexagram_name_cn = hex_name_cn

            return result
        except Exception as e:
            self._log(f"[{coin}] 离场卦象推理失败: {e}", "WARN")
            return None

    def _adjust_exit_config_for_regime(self, regime: dict):
        """短期修复 2：根据市场状态动态调整 ExitConfig

        - 震荡市（is_ranging=true / 弱趋势）：止损放宽到 5%，跟踪回撤 3.5% → 4%
        - 趋势市：恢复基准配置（4.5% / 3.5%）
        """
        if not regime or not hasattr(self, "_exit_cfg_base"):
            return
        try:
            is_ranging = bool(regime.get("is_ranging", False))
            # 弱趋势判定：adx < 20 或 trend_strength 为 weak/range
            adx = float(regime.get("adx", 0) or 0)
            trend_strength = str(regime.get("trend_strength", "")).lower()
            weak_trend = (adx < 20) or (trend_strength in ("weak", "range", "ranging"))

            cfg = self.exit_system.config
            if is_ranging or weak_trend:
                # 震荡市：放宽止损
                if cfg.tb_sl_min_pct != 0.05:
                    cfg.tb_sl_min_pct = 0.05
                    cfg.trailing_retrace_pct = 0.04
                    self._log(
                        f"[离场动态调整] 震荡市(is_ranging={is_ranging},adx={adx:.1f}) "
                        f"→ tb_sl_min=5% trailing_retrace=4%"
                    )
            else:
                # 趋势市：恢复基准
                if cfg.tb_sl_min_pct != self._exit_cfg_base.tb_sl_min_pct:
                    cfg.tb_sl_min_pct = self._exit_cfg_base.tb_sl_min_pct
                    cfg.trailing_retrace_pct = self._exit_cfg_base.trailing_retrace_pct
                    self._log(
                        f"[离场动态调整] 趋势市恢复基准 "
                        f"→ tb_sl_min={cfg.tb_sl_min_pct:.1%} trailing_retrace={cfg.trailing_retrace_pct:.1%}"
                    )
        except Exception as e:
            self._log(f"[离场动态调整失败] {e}")

    def _load_evolution_config(self, initial: bool = False):
        """A-1修复：从 OKX_SIM/config.json 加载进化后的阈值，覆盖默认值。

        - initial=True: __init__ 时调用，覆盖构造参数默认值
        - initial=False: run_once 每轮调用，热 reload 进化后的新阈值

        只更新 4 个进化键：confidence_threshold / daily_loss_limit /
        max_consecutive_losses / default_position_pct。
        其余字段（api_key 等）不受影响。
        """
        try:
            from scripts.memory_l4.paths import workspace_root as _ws

            cfg_path = _ws() / "data" / "okx_sim" / "config.json"
            self._evolution_config_path = cfg_path
            if not cfg_path.exists():
                return
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

            updated = []

            # confidence_threshold
            new_conf = cfg.get("confidence_threshold")
            if new_conf is not None and new_conf != self.confidence_threshold:
                self.confidence_threshold = new_conf
                updated.append(f"confidence_threshold={new_conf}")

            # PROP-20260810: 引擎层阈值同步（进化采纳值热重载到引擎）
            if (
                hasattr(self, "bcrm_engine")
                and self.bcrm_engine is not None
                and new_conf is not None
            ):
                try:
                    new_conf_f = float(new_conf)
                    if (
                        0.01 <= new_conf_f <= 0.95
                        and new_conf_f != self.bcrm_engine.min_confidence_threshold
                    ):
                        self.bcrm_engine.min_confidence_threshold = new_conf_f
                        updated.append(f"engine.min_confidence_threshold={new_conf_f}")
                except (TypeError, ValueError):
                    pass

            # risk_manager 相关 3 个字段（init 后 risk_manager 才存在）
            if hasattr(self, "risk_manager") and self.risk_manager is not None:
                state = self.risk_manager.state
                new_dll = cfg.get("daily_loss_limit")
                if new_dll is not None and new_dll != state.daily_loss_limit:
                    state.daily_loss_limit = new_dll
                    updated.append(f"daily_loss_limit={new_dll}")
                new_mcl = cfg.get("max_consecutive_losses")
                if new_mcl is not None and new_mcl != state.max_consecutive_losses:
                    state.max_consecutive_losses = int(new_mcl)
                    updated.append(f"max_consecutive_losses={new_mcl}")
                new_dpp = cfg.get("default_position_pct")
                if new_dpp is not None and new_dpp != state.position_size_pct:
                    state.position_size_pct = new_dpp
                    updated.append(f"default_position_pct={new_dpp}")
                new_llp = cfg.get("loss_limit_pct")
                if new_llp is not None and new_llp != state.loss_limit_pct:
                    state.loss_limit_pct = float(new_llp)
                    updated.append(f"loss_limit_pct={new_llp}")

            # ── Phase C S4: 排名止盈阈值热配置 ─────────────────
            new_gap = cfg.get("ranked_tp_gap_ratio")
            if new_gap is not None and float(new_gap) != getattr(self, "RANKED_TP_GAP_RATIO", 0.70):
                self.RANKED_TP_GAP_RATIO = float(new_gap)
                updated.append(f"RANKED_TP_GAP_RATIO={new_gap}")
            new_minp = cfg.get("ranked_tp_min_profit_usdt")
            if new_minp is not None and float(new_minp) != getattr(self, "RANKED_TP_MIN_PROFIT_USDT", 5.0):
                self.RANKED_TP_MIN_PROFIT_USDT = float(new_minp)
                updated.append(f"RANKED_TP_MIN_PROFIT_USDT={new_minp}")

            # ── Phase C S3: 多 horizon PREP_EXIT 边际热配置 ─────────
            # 注意：HORIZON_BAR_CANDIDATES 不做热配置（变更需重训多 horizon 模型，
            #       会破坏模型对齐）；仅热配 HORIZON_PREP_EXIT_MARGIN 安全阈值。
            new_margin = cfg.get("horizon_prep_exit_margin")
            if new_margin is not None:
                try:
                    new_margin_int = int(new_margin)
                    if 0 < new_margin_int <= 20 and new_margin_int != getattr(self, "HORIZON_PREP_EXIT_MARGIN", 3):
                        self.HORIZON_PREP_EXIT_MARGIN = new_margin_int
                        updated.append(f"HORIZON_PREP_EXIT_MARGIN={new_margin_int}")
                except (TypeError, ValueError):
                    pass

            if updated:
                tag = "init" if initial else "reload"
                self._log(f"[进化阈值/{tag}] 从 config.json 加载: {', '.join(updated)}")
        except Exception as e:
            if initial:
                # init 阶段失败静默（config 可能尚不存在）
                pass
            else:
                self._log(f"[进化阈值/reload] 加载失败: {e}", "WARN")

    def _adjust_confidence_threshold(self) -> float:
        """根据外部知识调整置信度阈值"""
        base_threshold = self.confidence_threshold

        if self.external_knowledge.get("risk_aversion", 0.5) > 0.8:
            adjusted = base_threshold + 0.05
            self._log(f"[外部知识] 风险厌恶高，置信度阈值提高至 {adjusted:.2f}")
            return adjusted

        if self.external_knowledge.get("market_bias") == "bear":
            adjusted = base_threshold + 0.03
            self._log(f"[外部知识] 熊市环境，置信度阈值提高至 {adjusted:.2f}")
            return adjusted

        return base_threshold

    def _maybe_refresh_coins(self):
        """8h 刷新公共代币池，保留有持仓的币种（不从池中移除有仓位的币）"""
        now = time.time()
        if now - self._last_pool_refresh < _POOL_TTL:
            return
        self._last_pool_refresh = now
        new_syms = _load_registry_symbols()
        if not new_syms:
            return
        new_coins = [self._norm(c) for c in new_syms]
        for coin in self.coins:
            inst_id = f"{coin}-USDT-SWAP"
            try:
                if self.position_tracker.has_open_position(inst_id):
                    if coin not in new_coins:
                        new_coins.append(coin)
                        self._log(f"[币池刷新] 保留持仓币种: {coin}")
            except Exception:
                pass
        old_set = set(self.coins)
        new_set = set(new_coins)
        added = new_set - old_set
        removed = old_set - new_set
        if added or removed:
            self._log(
                f"[币池刷新] 新增={sorted(added)} 移除={sorted(removed)} "
                f"最终={len(new_coins)}币"
            )
        self.coins = new_coins

    def run_once(self):
        """执行一轮推理 + 交易"""
        self._maybe_refresh_coins()
        self._check_date_rollover()
        self._load_external_knowledge()
        # A-1修复：每轮热 reload 进化后的阈值
        self._load_evolution_config(initial=False)
        self.cycle_count += 1
        self._log(f"═══ 轮询 #{self.cycle_count} 开始 ═══")

        risk_state = self.risk_manager.get_state()
        perf_stats = self.perf_tracker.get_today_stats()
        self._log(
            f"[状态] 日盈亏={risk_state['daily_pnl']:.2f} | "
            f"连亏={risk_state['consecutive_losses']}/{risk_state['max_consecutive_losses']} | "
            f"交易暂停={risk_state['trading_halted']} | "
            f"今日交易={perf_stats.get('total_trades', 0)}笔"
        )

        effective_threshold = self._adjust_confidence_threshold()

        # ══ Phase A (S1): MODE 算力重分配入口 ══════════════════════════════
        # 在执行任何昂贵操作（anomaly检测/BCRM2全推理）之前先决定 MODE：
        #   MODE-OFF（S1关） ：anom/full/coarse 全沿用 self.coins（旧路径等价）
        #   MODE3_FULL（100%）：anom 精简，只跑持仓+Top3粗推理候选；Full 仅持仓；Coarse 3 候选粗排后补Top1全推理
        #   MODE2_HALF（2/3+）：anom 选 持仓+Top4；Full 选 持仓+Top5；不跑 Coarse
        #   MODE1_LIGHT（<2/3）：anom/full 遍历全部候选（空仓轻压力，等价旧路径）
        # ── B4 防御：轮次计数推进 + 回退自动清缓存 ───────────
        # 正常情况下 _cycle_idx 单调递增；若因日期 rollover 或手工重置发生回退，
        # 所有缓存的 written_cycle 将与 TTL 判定方向相反（缓存永不过期）。
        self._advance_cycle_idx()
        mode_tag, anom_coins_mode, infer_full_coins, infer_coarse_coins = self._decide_mode_coins()
        self._log(
            f"[MODE] {mode_tag} | anomaly探针N={len(anom_coins_mode)} "
            f"Full推理N={len(infer_full_coins)} Coarse推理N={len(infer_coarse_coins)} | "
            f"Full币种={infer_full_coins} Coarse={infer_coarse_coins}"
        )

        # 异常检测 (Phase 2.1) —— 仅遍历 anom_coins_mode（MODE3 时精简到 持仓+Top3，避免 N^2 K线探针）
        anomaly_detected = False
        anomaly_coins = []
        try:
            for coin in anom_coins_mode:
                kline_data = _load_kline_from_okx(
                    inst_id=f"{coin}-USDT-SWAP", bar=self.bar, limit=self.kline_limit
                )
                if kline_data and len(kline_data) > 100:
                    import pandas as pd

                    df = pd.DataFrame(kline_data)
                    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
                    df.set_index("timestamp", inplace=True)
                    df.rename(
                        columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"},
                        inplace=True,
                    )

                    summary = self.anomaly_detector.get_summary(df, symbol=coin)
                    critical_count = summary["by_severity"].get("critical", 0)
                    high_count = summary["by_severity"].get("high", 0)

                    if critical_count > 0 or high_count >= 2:
                        anomaly_detected = True
                        anomaly_coins.append(coin)
                        self._log(
                            f"[异常检测] {coin}: 检测到 {critical_count} 个严重异常, {high_count} 个高等级异常"
                        )

            if anomaly_detected:
                self._log(f"[异常检测] 市场环境异常，提高风控等级 | 涉及币种: {anomaly_coins}")
                effective_threshold = min(0.8, effective_threshold + 0.15)
        except Exception as e:
            self._log(f"[异常检测] 检测失败: {e}", "WARN")

        # ===== 第一阶段：收集所有币种推理结果（Phase A MODE-aware）=====
        # 分三路顺序执行：Full(完整BCRM2.0) → Coarse(快速粗排) → MODE3 Top1 补全Full
        cycle_success = True
        all_inferences: Dict[str, dict] = {}
        coarse_inferences: Dict[str, dict] = {}
        toppedup_history: set = set()  # 补全过 Full 的币种（第三阶段开仓门禁用）

        # ── Step 1: Full 推理（infer_full_coins = 持仓 + MODE1/2 的候选TopN）──
        for coin in infer_full_coins:
            # P0-2: 动态币种黑名单过滤（连续2次亏损→封禁3日，到期自动释放）
            blocked, bl_reason = self._check_dynamic_blacklist(coin)
            if blocked:
                self._log(f"[{coin}] 币种黑名单 | 跳过（{bl_reason}）")
                continue
            try:
                inference = self._fetch_and_infer(coin)
                if not inference.get("ok"):
                    self._log(f"[{coin}] 推理失败: {inference.get('error')}", "ERROR")
                    cycle_success = False
                    continue

                self._log(
                    f"[{coin}] 价格={inference['price']} | "
                    f"卦象={inference['hexagram']} | "
                    f"方向={inference['direction']} | "
                    f"置信度={inference['confidence']:.2f} | "
                    f"八卦={inference['bagua_direction']}({inference['bagua_confidence']:.2f}) | "
                    f"震荡={inference['is_ranging']} | "
                    f"波动率={inference.get('volatility', 0):.4f} | "
                    f"fail={inference['fail_closed']}"
                )

                # P3: 反向召回接入 — A 系列 Cron 执行前注入认知召回（建议而非约束）
                if self.cognitive_recall_enabled and self._trading_recall_fn:
                    inference["cognitive_recall"] = self._inject_cognitive_recall(coin, inference)

                # A7 实践论门禁检查（代码驱动，执行前拦截）
                if self.a7_gate and not inference.get("fail_closed", False):
                    current_positions = self._count_total_positions()
                    cbr_engine = getattr(self.cbr_bridge, "cbr", None) if self.cbr_bridge else None
                    gate_report = self.a7_gate.check_before_execute(
                        inference=inference,
                        risk_manager=self.risk_manager,
                        cbr_engine=cbr_engine,
                        current_equity=self.perf_tracker.current_equity,
                        max_positions=self.max_positions,
                        current_positions=current_positions,
                    )
                    if not gate_report.passed:
                        self._log(
                            f"[{coin}] A7门禁拦截: " f"{'; '.join(gate_report.blocking_reasons)}",
                            "WARN",
                        )
                        continue

                all_inferences[coin] = inference

            except Exception as e:
                cycle_success = False
                self._log(f"[{coin}] 异常: {e}", "ERROR")
                if self.guardian:
                    self.guardian.record_error(e, context=f"cycle:{coin}")

        # ── Step 2: Coarse 粗推理（MODE3_FULL 时有候选 infer_coarse_coins = Top3）──
        if infer_coarse_coins:
            self._log(
                f"[MODE3][Step2] {len(infer_coarse_coins)} 个粗推理候选 → 快速MA交叉粗排"
            )
            for coin in infer_coarse_coins:
                blocked, bl_reason = self._check_dynamic_blacklist(coin)
                if blocked:
                    self._log(f"[{coin}] [MODE3][Coarse] 黑名单跳过（{bl_reason}）")
                    continue
                try:
                    coarse_inf = self._infer_coarse(coin)
                    if not coarse_inf.get("ok"):
                        self._log(
                            f"[{coin}] [MODE3][Coarse] 粗推理失败: {coarse_inf.get('error')}",
                            "WARN",
                        )
                        continue
                    all_inferences[coin] = coarse_inf
                    coarse_inferences[coin] = coarse_inf
                    self._log(
                        f"[{coin}] [MODE3][Coarse] 粗置信度={coarse_inf.get('confidence', 0):.2f} "
                        f"dir={coarse_inf.get('direction', 'NEUTRAL')} fail={coarse_inf.get('fail_closed', True)}"
                    )
                except Exception as e:
                    self._log(f"[{coin}] [MODE3][Coarse] 异常: {e}", "ERROR")

        # ── Step 3: MODE3 补全推理门禁（粗推理 Top1 → 重新跑完整版 BCRM2.0）──
        topup_list = self._pick_topup_from_coarse(infer_coarse_coins, coarse_inferences)
        if topup_list:
            self._log(
                f"[MODE3][Step3] Top1 补全推理 → {topup_list}（其他粗结果禁止开仓）"
            )
        for topup_coin in topup_list:
            blocked, bl_reason = self._check_dynamic_blacklist(topup_coin)
            if blocked:
                self._log(f"[{topup_coin}] [MODE3][补全] 黑名单跳过（{bl_reason}）")
                continue
            try:
                coarse_conf = coarse_inferences.get(topup_coin, {}).get("confidence", None)
                full_inf = self._fetch_and_infer(topup_coin)
                if full_inf and full_inf.get("ok"):
                    # A7 门禁也需要再检查一次（补全版本需要满足同 Full 路径一致的约束）
                    a7_ok = True
                    if self.a7_gate and not full_inf.get("fail_closed", False):
                        cbr_engine = getattr(self.cbr_bridge, "cbr", None) if self.cbr_bridge else None
                        gp = self.a7_gate.check_before_execute(
                            inference=full_inf,
                            risk_manager=self.risk_manager,
                            cbr_engine=cbr_engine,
                            current_equity=self.perf_tracker.current_equity,
                            max_positions=self.max_positions,
                            current_positions=self._count_total_positions(),
                        )
                        a7_ok = gp.passed
                        if not a7_ok:
                            self._log(
                                f"[{topup_coin}] [MODE3][补全] A7拦截: "
                                f"{'; '.join(gp.blocking_reasons)}",
                                "WARN",
                            )
                    if a7_ok:
                        self._apply_topup_full(all_inferences, topup_coin, full_inf, coarse_conf)
                        toppedup_history.add(topup_coin)
                else:
                    self._log(
                        f"[{topup_coin}] [MODE3][补全] Full推理失败，仍保留粗结果（但禁止开仓）",
                        "WARN",
                    )
            except Exception as e:
                self._log(f"[{topup_coin}] [MODE3][补全] 异常: {e}", "ERROR")

        # ── Phase C (S4): 全局排名止盈 Top1（跨持仓统一比较） ──
        # 原因：S4 需要比较"当前所有持仓 upl 的全局排名"，
        # 若放在 _execute_trade 的单币种循环里，会重复计算且无法做全局 gap 判定。
        # 因此在第二阶段前统一执行一次：若 gap≥0.7 且 Top1≥5U → 2/2 确认后立即平仓
        # （后续第二阶段该币种 has_position 自动为 False，跳过持仓管理）
        if getattr(self, "enable_ranked_tp", False) and all_inferences:
            try:
                ranked_list = self._build_ranked_positions(all_inferences)
                if ranked_list and len(ranked_list) >= 2:
                    _log_rank = " | ".join(
                        f"{r['coin']}={r['upl']:.1f}U({r['upl_ratio']:.2%})" for r in ranked_list
                    )
                    self._log(f"[S4 排名止盈] 当前持仓排名（盈利高→低）：{_log_rank}", "INFO")
                    tp_result = self._handle_ranked_tp_top1(ranked_list)
                    # 归档 S4 评估结果到 JSONL（供 s4_stats.py 长期统计）
                    self._archive_s4_eval(ranked_list, tp_result)
                    if tp_result.get("triggered"):
                        self._log(
                            f"[S4 排名止盈] ✅ 已止盈 {tp_result.get('coin')} "
                            f"gap={tp_result.get('gap_ratio', 0):.2f} "
                            f"reason={tp_result.get('reason')}",
                            "INFO",
                        )
            except Exception as _e:
                self._log(f"[S4 排名止盈] 评估异常: {_e}", "WARN")

        # ===== 第二阶段：先处理持仓管理（平仓/反手/离场），按币种顺序 =====
        # 持仓管理按币种顺序即可（无需排名），关键是不要打乱离场时机
        for coin, inference in all_inferences.items():
            try:
                pos_info = self._check_positions(coin)
                if pos_info.get("has_position"):
                    # 有持仓：执行持仓管理（离场评估、信号反转等）
                    self._execute_trade(inference, confidence_threshold=effective_threshold,
                                        all_inferences=all_inferences)
                    # ── Phase B: ShadowLogger 影子记录（只记录，不影响交易）──
                    self._record_shadow_log(coin, inference, {
                        "direction": inference.get("direction"),
                        "confidence": inference.get("confidence"),
                        "position_usdt": inference.get("position_usdt"),
                        "tp_px": inference.get("take_profit_px"),
                        "sl_px": inference.get("stop_loss_px"),
                        "threshold": effective_threshold,
                    })
            except Exception as e:
                cycle_success = False
                self._log(f"[{coin}] 持仓管理异常: {e}", "ERROR")
                if self.guardian:
                    self.guardian.record_error(e, context=f"cycle_manage:{coin}")

        # ===== 第三阶段：新开仓候选按置信度排名执行 =====
        # 规则：默认根据置信度排名开仓，高置信度优先，仓位大小也根据置信度调控
        open_candidates = []
        for coin, inference in all_inferences.items():
            try:
                pos_info = self._check_positions(coin)
                if pos_info.get("has_position"):
                    continue  # 已有持仓，不在新开仓阶段处理

                # ── Phase A MODE3 门禁：粗推理未补全 Full → 禁止进入开仓候选 ──
                # 说明：toppedup_history 包含 Step3 已补全为 Full 的币种；
                #       _coarse=True 且不在 toppedup 里的币种在本步直接跳过，不参与排名
                if not self._guard_coarse_not_toppedup(coin, inference, toppedup_history):
                    continue

                # 运行时残留清理：本地有记录但 OKX 已无持仓（OKX端 SL/TP 触发）
                # 清理残留并记录平仓时间，用于统一冷静期判断
                # 注意：查询失败（限流）时不清理，避免误删本地持仓记录
                inst_id = f"{coin}-USDT-SWAP"
                if pos_info.get("query_failed"):
                    self._log(f"[{coin}] OKX 持仓查询失败（可能限流），跳过残留清理", "WARN")
                elif self.position_tracker.has_open_position(inst_id):
                    stale_rec = self.position_tracker.get_open_position(inst_id)
                    stale_side = stale_rec.direction if stale_rec else None
                    self.position_tracker.close_position(
                        inst_id,
                        exit_price=float(pos_info.get("mark_px", 0.0)) or 0.0,
                        exit_reason="运行时检测OKX持仓消失",
                    )
                    self._log(
                        f"[{coin}] 运行时清理本地残留 " f"(OKX端已平仓, side={stale_side})", "WARN"
                    )

                direction = inference["direction"]
                confidence = inference["confidence"]
                fail_closed = inference["fail_closed"]

                if direction not in ("UP", "DOWN"):
                    continue
                if fail_closed:
                    continue

                # 统一冷静期检查：平仓后 8h 内禁止该币种任何方向新开仓
                _side_map = {"UP": "long", "DOWN": "short"}
                want_side = _side_map.get(direction)
                in_cd, cd_reason = self.position_tracker.is_in_cooldown(
                    inst_id, want_side, self.COOLDOWN_SEC
                )
                if in_cd:
                    self._log(f"[{coin}] 跳过开仓候选: {cd_reason}", "INFO")
                    continue

                # 基础阈值筛选
                short_threshold = (
                    max(effective_threshold, self.short_confidence_threshold)
                    if direction == "DOWN"
                    else effective_threshold
                )
                if confidence < short_threshold:
                    continue

                # 风控检查
                risk_check = self.risk_manager.can_trade(self.perf_tracker.current_equity)
                if not risk_check["allowed"]:
                    self._log(f"[{coin}] 风控拦截开仓候选: {risk_check['reason']}", "WARN")
                    continue

                # 计算"置信度调整后优先级" = confidence * 方向偏好
                # 做空难度更高，进一步乘以 0.95 作轻微折减
                direction_bias = 0.95 if direction == "DOWN" else 1.0
                priority_score = confidence * direction_bias

                open_candidates.append(
                    {
                        "coin": coin,
                        "inference": inference,
                        "priority_score": priority_score,
                        "confidence": confidence,
                        "direction": direction,
                    }
                )
            except Exception as e:
                cycle_success = False
                self._log(f"[{coin}] 候选评估异常: {e}", "ERROR")

        # 按置信度（优先级）从高到低排序
        open_candidates.sort(key=lambda c: c["priority_score"], reverse=True)

        if open_candidates:
            ranking_display = " | ".join(
                f"{c['coin']}({c['direction']} conf={c['confidence']:.2f})" for c in open_candidates
            )
            self._log(
                f"[开仓排名] 共 {len(open_candidates)} 个候选，"
                f"按置信度从高到低：{ranking_display}"
            )

        # 依次按排名执行开仓
        for candidate in open_candidates:
            coin = candidate["coin"]
            inference = candidate["inference"]
            confidence = candidate["confidence"]

            try:
                # 再次检查风控和持仓数（在排名执行过程中可能变化）
                risk_check = self.risk_manager.can_trade(self.perf_tracker.current_equity)
                if not risk_check["allowed"]:
                    self._log(f"[{coin}] 排名开仓前风控拦截: {risk_check['reason']}", "WARN")
                    break

                current_positions = self._count_total_positions()
                if current_positions >= self.max_positions:
                    self._log(
                        f"[{coin}] 已达最大持仓数 {self.max_positions}，"
                        f"剩余 {len(open_candidates) - open_candidates.index(candidate) - 1} 个候选跳过"
                    )
                    break

                self._log(
                    f"[{coin}] 排名 #{open_candidates.index(candidate) + 1} 开仓 | "
                    f"置信度={confidence:.2f} 方向={candidate['direction']}"
                )
                self._execute_trade(inference, confidence_threshold=effective_threshold)
                # ── Phase B: ShadowLogger 影子记录（只记录，不影响交易）──
                self._record_shadow_log(coin, inference, {
                    "direction": inference.get("direction"),
                    "confidence": inference.get("confidence"),
                    "position_usdt": inference.get("position_usdt"),
                    "tp_px": inference.get("take_profit_px"),
                    "sl_px": inference.get("stop_loss_px"),
                    "threshold": effective_threshold,
                })
            except Exception as e:
                cycle_success = False
                self._log(f"[{coin}] 排名开仓异常: {e}", "ERROR")
                if self.guardian:
                    self.guardian.record_error(e, context=f"cycle_open:{coin}")

        open_pos = self.position_tracker.all_open_positions()
        self._log(f"[持仓跟踪] 记录中持仓数: {len(open_pos)}")
        for pos in open_pos:
            self._log(
                f"  - {pos.coin}: {pos.direction} @ {pos.entry_price} "
                f"(conf={pos.confidence:.2f})"
            )

        learn_state = self.learning_scheduler.get_state()
        self._log(
            f"[学习] 当前案例={learn_state['current_case_count']} | "
            f"新增自上次重训={learn_state['new_cases_since']} | "
            f"上次重训={learn_state['last_retrain_time_str']}"
        )

        # ── 段⑤+段⑥ 审计：在线学习 evaluate_and_correct + AB双基线闸门状态（只读，不做 promote）──
        self._run_polling_level_learning_and_ab()

        if self.guardian:
            self.guardian.record_heartbeat(
                status="running",
                cycle_count=self.cycle_count,
            )
            if cycle_success:
                self.guardian.record_success()

        self._log(f"═══ 轮询 #{self.cycle_count} 结束 ═══\n")

    def run_loop(self):
        """主轮询循环"""
        self.running = True
        cfg = self.okx_client.cfg
        self._log(
            f"轮询交易器启动 | "
            f"间隔={self.interval}s 币种={self.coins} 周期={self.bar} | "
            f"置信度阈值={self.confidence_threshold} 最大持仓={self.max_positions} | "
            f"dry_run={cfg.get('dry_run')} simulated={cfg.get('simulated')}"
        )
        self._log(
            f"[风控] 日亏损上限={self.risk_manager.state.daily_loss_limit}USDT | "
            f"最大连续亏损={self.risk_manager.state.max_consecutive_losses} | "
            f"默认仓位={self.risk_manager.state.position_size_pct:.1%}"
        )
        self._log(
            f"[绩效] 初始权益={self.perf_tracker.initial_equity} | "
            f"当前权益={self.perf_tracker.current_equity:.2f} | "
            f"历史交易={self.perf_tracker.get_overall_stats()['total_trades']}笔"
        )

        def _shutdown(signum, frame):
            _sig_names = {
                getattr(signal_module, k, 0): k
                for k in ("SIGINT", "SIGTERM", "SIGHUP", "SIGPIPE",
                          "SIGXCPU", "SIGXFSZ", "SIGUSR1", "SIGUSR2")
            }
            _sn = _sig_names.get(signum, f"SIG#{signum}")
            self._log(f"收到退出信号 {_sn}，正在停止...", "WARN")
            self.running = False

        signal_module.signal(signal_module.SIGINT, _shutdown)
        signal_module.signal(signal_module.SIGTERM, _shutdown)
        # macOS setsid 后仍然可能收到的信号，全部统一捕获写日志，避免静默退出
        for _sn_name in ("SIGHUP", "SIGPIPE", "SIGXCPU", "SIGXFSZ", "SIGUSR1", "SIGUSR2"):
            try:
                signal_module.signal(getattr(signal_module, _sn_name), _shutdown)
            except (AttributeError, OSError, ValueError):
                pass

        # ══════════════════════════════════════════════════════════════
        # 内置 yijing_monitor 调度线程（每 6 小时触发一次健康检查 + 自进化）
        # 替代 launchd 定时调度，避免 macOS 沙箱权限问题
        # ══════════════════════════════════════════════════════════════
        MONITOR_INTERVAL_SEC = 6 * 3600  # 6 小时

        def _monitor_worker():
            first_run = True
            while self.running:
                try:
                    if first_run:
                        # 首次延迟 1 小时启动：避免和首轮 18 币种 BCRM2 训练/推理重叠导致内存压力
                        wait_sec = 60 * 60
                        desc = "首次延迟 1h"
                    else:
                        # 之后每 6 小时一次
                        wait_sec = MONITOR_INTERVAL_SEC
                        desc = "定期"
                    # 以 1s 为粒度响应 shutdown
                    for _ in range(wait_sec):
                        if not self.running:
                            return
                        time.sleep(1)
                    first_run = False
                    self._log(f"[Monitor] {desc}触发监控周期（健康检查 + 自进化）", "INFO")
                    # 延迟导入，避免模块加载冲突
                    from scripts.memory_l4 import yijing_monitor
                    try:
                        healthy, status, detail = yijing_monitor.check_yijing_health()
                        self._log(
                            f"[Monitor] 健康: {'✅ 正常' if healthy else '⚠️ 异常'} | {status}",
                            "INFO" if healthy else "WARN",
                        )
                    except Exception as _e:
                        self._log(f"[Monitor] 健康检查异常: {_e}", "WARN")
                    try:
                        evo, perf, evolved = yijing_monitor.run_evolution()
                        self._log(
                            f"[Monitor] 进化完成 | 累计次数={evo.get('evolution_count', 0)} "
                            f"| 胜率={perf.get('win_rate', 0):.0%} | 总盈亏={perf.get('total_pnl', 0):.2f}USDT",
                            "INFO",
                        )
                    except Exception as _e:
                        self._log(f"[Monitor] 自进化异常: {_e}", "ERROR")
                        if self.guardian:
                            self.guardian.record_error(_e, context="monitor_evolution")
                except Exception as _e:
                    # 线程级别兜底：不能让监控线程挂了
                    self._log(f"[Monitor] 调度线程异常: {_e}", "ERROR")
                    for _ in range(300):
                        if not self.running:
                            return
                        time.sleep(1)

        import threading as _threading
        monitor_thread = _threading.Thread(
            target=_monitor_worker, name="yijing_monitor", daemon=True
        )
        monitor_thread.start()
        self._log(f"[Monitor] 内置调度线程已启动 | 周期={MONITOR_INTERVAL_SEC//3600}h", "INFO")

        while self.running:
            try:
                self.run_once()
            except Exception as e:
                self._log(f"轮询异常: {e}", "ERROR")
                if self.guardian:
                    self.guardian.record_error(e, context="main_loop")

            if not self.running:
                break

            for _ in range(self.interval):
                if not self.running:
                    break
                time.sleep(1)

        if self.guardian:
            self.guardian.stop()
        self._log("轮询交易器已停止")

    def get_status(self) -> dict:
        """获取完整运行状态（供 API 查询）"""
        return {
            "cycle_count": self.cycle_count,
            "running": self.running,
            "interval": self.interval,
            "coins": self.coins,
            "bar": self.bar,
            "confidence_threshold": self.confidence_threshold,
            "max_positions": self.max_positions,
            "risk": self.risk_manager.get_state(),
            "performance_today": self.perf_tracker.get_today_stats(),
            "performance_overall": self.perf_tracker.get_overall_stats(),
            "open_positions": [
                {
                    "coin": p.coin,
                    "inst_id": p.inst_id,
                    "direction": p.direction,
                    "entry_price": p.entry_price,
                    "confidence": p.confidence,
                    "hexagram": p.hexagram,
                    "entry_time": p.entry_time,
                }
                for p in self.position_tracker.all_open_positions()
            ],
            "learning": self.learning_scheduler.get_state(),
            "guardian": self.guardian.get_status() if self.guardian else {},
        }


def main():
    parser = argparse.ArgumentParser(description="易经推理轮询交易器（P2 完整版）")
    parser.add_argument("--interval", type=int, default=3600, help="轮询间隔（秒），默认 3600(1h)")
    parser.add_argument(
        "--coins",
        type=str,
        default=",".join(_load_registry_symbols() or [
            "UNI", "PUMP", "MU", "SKHYNIX", "HYPE", "ETH", "BTC", "SOL",
            "XAU", "XAG", "GOOGL", "NVDA", "AMZN", "OKB", "BNB",
            "CRCL", "COIN", "BMNR", "MSTR",
        ]),
        help="币种列表，逗号分隔，默认读取公共代币池(config/token_registry.json)，可override",
    )
    parser.add_argument("--bar", type=str, default="1H", help="K线周期，默认 1H")
    parser.add_argument("--confidence", type=float, default=0.35, help="置信度阈值，默认 0.35")
    parser.add_argument(
        "--short-confidence",
        type=float,
        default=0.80,
        help="做空置信度阈值（高于做空以减少做空频率），默认 0.80",
    )
    parser.add_argument("--max-positions", type=int, default=3, help="最大同时持仓数，默认 3")
    parser.add_argument("--once", action="store_true", help="只执行一次，不循环")
    parser.add_argument(
        "--initial-equity",
        type=float,
        default=None,
        help="初始权益（USDT），不指定则从 OKX 读取实际余额",
    )
    parser.add_argument(
        "--daily-loss-limit",
        type=float,
        default=-30.0,
        help="日最大亏损兜底值（USDT），默认 -30（150U可用金的20%）",
    )
    parser.add_argument(
        "--max-consecutive-losses",
        type=int,
        default=999,
        help="最大连续亏损次数（已禁用，默认999不再触发），风控改以亏损金额为准",
    )
    parser.add_argument(
        "--position-pct",
        type=float,
        default=0.20,
        help="默认单笔仓位比例，默认 0.20(20%%)（C项优化）",
    )
    parser.add_argument("--no-guardian", action="store_true", help="不启用进程守护")
    parser.add_argument(
        "--use-bcrm2",
        action="store_true",
        default=True,
        help="使用 BCRM 2.0 (辩证ML引擎)，默认启用",
    )
    parser.add_argument("--use-bcrm1", action="store_true", help="使用 BCRM 1.0 (矛盾力学引擎)")
    args = parser.parse_args()

    coins = [c.strip().upper() for c in args.coins.split(",")]
    # P4 修复：币种规范化（XAUT → XAU，因为 OKX 实际存在的是 XAU-USDT-SWAP，XAUT 已下架）
    # 在 CLI 层做一次，配合 PollingTrader.__init__ 内的二次规范化形成双保险。
    _NORM_MAIN = {"XAUT": "XAU"}
    coins = [_NORM_MAIN.get(c, c) for c in coins]

    if args.initial_equity is None:
        print("[初始化] 从 OKX 读取实际余额...")
        try:
            from scripts.memory_l4.okx_simulated import OKXSimulatedClient

            client = OKXSimulatedClient()
            balance = client.get_balance()
            if balance.get("ok"):
                args.initial_equity = balance.get("total_eq", 100.0)
            else:
                args.initial_equity = 100.0
        except Exception as e:
            print(f"[初始化] 读取余额失败，使用默认值: {e}")
            args.initial_equity = 100.0
        print(f"[初始化] 实际余额={args.initial_equity:.2f} USDT")

    guardian = None
    if not args.no_guardian:
        guardian = ProcessGuardian(
            process_name="yijing_polling_trader",
            heartbeat_timeout=max(args.interval * 3, 300),
            max_consecutive_errors=args.max_consecutive_losses,
        )
        existing = guardian.check_existing_heartbeat()
        if existing and existing.get("is_alive"):
            print(f"警告：检测到已有运行中的进程 (PID={existing.get('pid')})")
            print(f"上次心跳: {existing.get('ts_str')}")

    trader = PollingTrader(
        interval=args.interval,
        coins=coins,
        bar=args.bar,
        confidence_threshold=args.confidence,
        short_confidence_threshold=args.short_confidence,
        max_positions=args.max_positions,
        initial_equity=args.initial_equity,
        daily_loss_limit=args.daily_loss_limit,
        max_consecutive_losses=args.max_consecutive_losses,
        default_position_pct=args.position_pct,
        guardian=guardian,
        use_bcrm2=not args.use_bcrm1,
    )

    if guardian:
        guardian.start()

    if args.once:
        trader.run_once()
        status = trader.get_status()
        print("\n═══ 运行状态 ═══")
        print(
            json.dumps(
                {k: v for k, v in status.items() if k not in ("open_positions_detail",)},
                indent=2,
                ensure_ascii=False,
                default=str,
            )
        )
    else:
        trader.run_loop()

    if guardian:
        guardian.stop()


if __name__ == "__main__":
    main()
