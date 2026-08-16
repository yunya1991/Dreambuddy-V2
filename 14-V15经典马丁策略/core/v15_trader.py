#!/usr/bin/env python3
"""
V15 经典马丁策略自动交易器
- 定时轮询币种信号
- 根据资金计算器决定是否开仓
- 马丁加仓：最多4次（=总5单），资金不足时禁止开新仓
- 多空双向：DirectionGate 基于 MA128 + BTC风向标三状态模型控制方向开关
- BTC风向标智能模式：BTC用自身MA128+DirectionGate，非BTC加密币种用BTC风向标3日确认+short_only
- 非加密资产（如美股）：旧版DirectionGate + MA200止损（与BTC走势无关）
  - 做多：价格在日 MA200 上方（LONG_PREFERRED）
  - 做空：跌破日 MA200 但在周 MA200 上方（SHORT_ALLOWED，反向马丁）
  - 强制做多：跌至周 MA200（LONG_ONLY_FORCE，禁止做空）
"""
import json
import math
import signal as sig_module
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / "lib"))
sys.path.insert(0, str(BASE_DIR / "core"))

# L4 TradeEvent 注册（跨系统统一交易记录）
try:
    _L4_ROOT = Path(__file__).resolve().parents[1] / "11-易经推理系统"
    if str(_L4_ROOT) not in sys.path:
        sys.path.insert(0, str(_L4_ROOT))
    from scripts.memory_l4.case_registry import UnifiedCaseRegistry
    from scripts.memory_l4.trade_event import TradeEvent

    _L4_ENABLED = True
except Exception as _e:
    _L4_ENABLED = False

try:
    from config_loader import (
        get_config,
        get_config_bool,
        get_config_float,
        get_config_int,
        get_config_list,
        load_config,
    )

    load_config("v15")
except Exception:
    pass

# 统一交易对适配层（替代散落的 f"{coin}-USDT" / f"{coin}-USDT-SWAP" 硬编码）
try:
    from symbol_mapper import (
        get_category,
        to_spot,
        to_swap,
    )
    from symbol_mapper import (
        is_martin_safe as _coin_martin_safe,
    )
    from symbol_mapper import (
        is_supported as _coin_supported,
    )
except Exception:
    # 降级：保留原硬编码行为，保证向后兼容
    def to_spot(coin, exchange="okx"):
        return f"{coin}-USDT"

    def to_swap(coin, exchange="okx"):
        return f"{coin}-USDT-SWAP"

    def _coin_supported(coin, exchange="okx"):
        return True

    def get_category(coin):
        return "crypto"

    def _coin_martin_safe(coin, min_tier="mid", min_history_days=365):
        return True


try:
    from bounce_potential_evaluator import evaluate_signals, monitor_bounce_signals

    BOUNCE_MONITOR_ENABLED = True
except ImportError:
    BOUNCE_MONITOR_ENABLED = False

BOUNCE_FILTER_ENABLED = get_config_bool("BOUNCE_FILTER_ENABLED", False)
BOUNCE_MIN_SIGNALS = get_config_int("BOUNCE_MIN_SIGNALS", 1)

# ── Phase C 易经推理开关（默认关闭：walk-forward 验证 C 相比 B+ 无额外收益）──
# true: 启用易经 risk/value 插值（实验性，需重新验证后才可开启）
# false: 仅使用 Phase B+ 子形态微调（v15 最终形态）
V15_YIJING_ENABLED = get_config_bool("V15_YIJING_ENABLED", False)

# 多空方向控制开关
V15_ALLOW_SHORT = str(get_config("V15_ALLOW_SHORT", "false")).lower() == "true"

# Phase 2: BTC风向标力学化总开关（true=弹簧力场+Verlet+减速动态确认；false=传统above/below+3日硬确认）
V15_USE_MECHANISTIC_DIRECTION_GATE = (
    str(get_config("V15_USE_MECHANISTIC_DIRECTION_GATE", "true")).lower() == "true"
)

# Phase 3: BTC风向标 swing 势垒/势阱开关（true=swing点高斯力叠加到F_net；false=仅MA弹簧）
# 实验性：开启前需回测验证 Phase 2 vs Phase 3 有正收益提升
V15_USE_SWING_POTENTIAL = str(get_config("V15_USE_SWING_POTENTIAL", "false")).lower() == "true"

# Phase 4: TimingGate 波浪+斐波那契时机软调控总开关
# false=关闭（保持现状，只靠 DirectionGate + 指标驱动，向后兼容）
V15_USE_TIMING_GATE = str(get_config("V15_USE_TIMING_GATE", "false")).lower() == "true"

# ── Phase 4: TimingGate 细粒度参数（与 v15_backtest.py BO最优默认值1:1对齐）──
V15_TIMING_SWING_WINDOW = int(get_config("V15_TIMING_SWING_WINDOW", "2"))
V15_TIMING_STRICT = str(get_config("V15_TIMING_STRICT", "false")).lower() == "true"
V15_TIMING_THRESHOLD = float(get_config("V15_TIMING_THRESHOLD", "0.30"))
V15_TIMING_FIB_RETRACE_LO = float(get_config("V15_TIMING_FIB_RETRACE_LO", "0.23"))
V15_TIMING_FIB_RETRACE_HI = float(get_config("V15_TIMING_FIB_RETRACE_HI", "0.71"))
V15_TIMING_FIB_EXT_RATIO = float(get_config("V15_TIMING_FIB_EXT_RATIO", "1.62"))
V15_TIMING_LENIENT_UNCLEAR = float(get_config("V15_TIMING_LENIENT_UNCLEAR", "0.58"))
V15_TIMING_STRICT_UNCLEAR_SCORE = float(get_config("V15_TIMING_STRICT_UNCLEAR_SCORE", "0.20"))
V15_TIMING_RETRACE_MU = float(get_config("V15_TIMING_RETRACE_MU", "0.62"))
V15_TIMING_RETRACE_SIGMA = float(get_config("V15_TIMING_RETRACE_SIGMA", "0.34"))
V15_TIMING_UNCLEAR_RETRACE_EXT = float(get_config("V15_TIMING_UNCLEAR_RETRACE_EXT", "0.88"))
# 软调控模式（核心）：True=只缩仓位不硬门禁；False=先硬门禁再打折
V15_TIMING_SOFT_MODE = str(get_config("V15_TIMING_SOFT_MODE", "true")).lower() == "true"
# 非线性惩罚指数：timing_mult = score ** V15_TIMING_SIZE_POWER
V15_TIMING_SIZE_POWER = float(get_config("V15_TIMING_SIZE_POWER", "2.49"))
# swing融合模式: "or" / "and" / "daily_only"
V15_TIMING_SWING_FUSION_MODE = str(get_config("V15_TIMING_SWING_FUSION_MODE", "or")).lower()
V15_TIMING_INTRADAY_SWING_WINDOW = int(get_config("V15_TIMING_INTRADAY_SWING_WINDOW", "3"))
# 软调控下仓位缩到极小就跳过（避免无意义挂单）
V15_TIMING_SKIP_MULT = float(get_config("V15_TIMING_SKIP_MULT", "0.02"))

STATE_FILE = BASE_DIR / "data" / "v15_state.json"
REGIME_STATE_FILE = BASE_DIR / "data" / "regime_state.json"
LOG_DIR = BASE_DIR / "logs" / "v15"
LOG_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

POLL_INTERVAL = int(get_config("V15_POLL_INTERVAL", "3600"))
AUTO_EXECUTE = str(get_config("V15_AUTO_EXECUTE", "true")).lower() == "true"
# 币种池：从配置加载后，用 SymbolMapper 过滤出 OKX 支持的币种
_RAW_COINS = get_config_list(
    "V15_COINS", default=["BTC", "ETH", "SOL", "ARB", "OP", "UNI", "HYPE", "OKB"]
)
_OKX_SUPPORTED = [c for c in _RAW_COINS if _coin_supported(c, "okx")] or _RAW_COINS
# ── 马丁策略风控过滤：市值等级 + 上线时间 ──
# min_tier: 最低市值等级 (large/mid/small)，默认 mid（剔除 small）
# min_history_days: 最小上线天数，默认 365 天（避免新币暴涨暴跌风险）
_MARTIN_MIN_TIER = str(get_config("V15_MARTIN_MIN_TIER", "mid")).lower()
_MARTIN_MIN_HISTORY_DAYS = get_config_int("V15_MARTIN_MIN_HISTORY_DAYS", 365)
COINS = [
    c for c in _OKX_SUPPORTED if _coin_martin_safe(c, _MARTIN_MIN_TIER, _MARTIN_MIN_HISTORY_DAYS)
]
# 记录被风控剔除的币种（供启动日志输出）
_MARTIN_REJECTED = [c for c in _OKX_SUPPORTED if c not in COINS]
V15_MAX_ADDONS = get_config_int("MAX_ADDONS_PER_POSITION", 4)  # 4档加仓=总5单（实盘测试版本）
MAX_ADDONS = V15_MAX_ADDONS
BASE_TP_PCT = get_config_float("BASE_TP_PCT", 0.04)
LEVERAGE = get_config_float("LEVERAGE", 5.0)
MAX_CONCURRENT_POSITIONS = get_config_int("MAX_CONCURRENT_POSITIONS", 3)
TOTAL_BUDGET = get_config_float("TOTAL_BUDGET", 260)
ADDON_PCT = get_config_float("ADDON_PCT", 0.08)

# ── Phase D: AI 闸门总开关（默认关闭=严格等价基线，字节级别不变异） ──
# 四大铁律 ① 基线可随时回退：env/config 改为 false 则完全不运行 Phase D 分支
# 四大铁律 ② 不超基线不启用：phase_d_gateway 内 apply_iron_clamp 保证不越界
# 四大铁律 ③ 最大最小调节边界：K_bound 由 ai_boundary_scaler 持久化
# 四大铁律 ④ 边界随表现缩放：每 N 轮更新 S_bt / S_live 重算 K_bound
V15_AI_ENABLED = str(get_config("V15_AI_ENABLED", "false")).lower() == "true"
# V15_AI_SHADOW: 只出决策日志不实际生效（便于先上线观察 AI 调参倾向）
V15_AI_SHADOW = str(get_config("V15_AI_SHADOW", "false")).lower() == "true"
V15_AI_STATE_FILE = BASE_DIR / "data" / "phase_d_ai_state.json"

# ── Phase E: PPO-LSTM 强化学习（默认关闭=字节等价基线） ──
V15_AI_PHASE_E_ENABLED = str(get_config("V15_AI_PHASE_E_ENABLED", "false")).lower() == "true"
V15_AI_PHASE_E_MODEL_PATH = str(get_config("V15_AI_PHASE_E_MODEL_PATH", ""))

_PHASE_E_GW_SINGLETON = None

_PHASE_D_GW_SINGLETON = None


def _get_phase_d_gateway():
    """懒加载 PhaseDGateway 单例。关闭开关时返回 None，保证调用方直接走基线分支。"""
    global _PHASE_D_GW_SINGLETON
    if not V15_AI_ENABLED:
        return None
    if _PHASE_D_GW_SINGLETON is not None:
        return _PHASE_D_GW_SINGLETON
    try:
        from phase_d_gateway import PhaseDGateway

        _PHASE_D_GW_SINGLETON = PhaseDGateway(enabled=True)
        return _PHASE_D_GW_SINGLETON
    except Exception as _e:
        _log(f"[Phase-D] Gateway 初始化失败(降级为None=基线): {_e}")
        _PHASE_D_GW_SINGLETON = None
        return None


def _get_phase_e_gateway():
    """懒加载 PhaseEGateway 单例。关闭开关时返回 None，保证基线等价。"""
    global _PHASE_E_GW_SINGLETON
    if not V15_AI_PHASE_E_ENABLED:
        return None
    if _PHASE_E_GW_SINGLETON is not None:
        return _PHASE_E_GW_SINGLETON
    try:
        from phase_e_gateway import PhaseEGateway

        _PHASE_E_GW_SINGLETON = PhaseEGateway(
            enabled=True,
            ppo_model_path=V15_AI_PHASE_E_MODEL_PATH or None,
        )
        return _PHASE_E_GW_SINGLETON
    except Exception as _e:
        _log(f"[Phase-E] Gateway 初始化失败(降级为None=基线): {_e}")
        _PHASE_E_GW_SINGLETON = None
        return None


def _phase_e_build_s_state(coin: str, params: dict, pos: dict = None) -> dict:
    """构建 34 维状态 dict（供 PhaseEGateway 使用）。
    MVP 阶段从 params 和 pos 中提取可用字段，缺失字段用中性值填充。"""
    return {
        "timing_score": float(params.get("timing_score", 0.5)),
        "structure_match_score": float(params.get("structure_match_score", 0.5)),
        "retrace_quality_score": float(params.get("retrace_quality_score", 0.5)),
        "extension_chase_score": float(params.get("extension_chase_score", 0.5)),
        "regime": str(params.get("regime", "ACCUM")),
        "long_enabled": bool(params.get("long_enabled", True)),
        "short_enabled": bool(params.get("short_enabled", False)),
        "btc_windvane_strength": float(params.get("btc_windvane_strength", 0.5)),
        "regime_zone": int(params.get("regime_zone", 2)),
        "days_in_current_zone": int(params.get("days_in_current_zone", 10)),
        "position_level": int(pos.get("current_level", 0)) if pos else 0,
        "avg_entry_price_pct_diff": float(params.get("avg_entry_pct_diff", 0.0)),
        "unrealized_pnl_ratio": float(params.get("unrealized_pnl_ratio", 0.0)),
        "distance_to_liq_ratio": float(params.get("distance_to_liq_ratio", 0.80)),
        "atr_14_pct": float(params.get("atr_pct", 0.03)),
        "atr_14_zscore_30": 0.0,
        "realized_vol_30d": float(params.get("vol_ratio", 0.04)),
        "vol_zscore_60": 0.0,
        "btc_corr_30d": 0.8,
        "btc_rsi_14": 50.0,
        "swing_window_daily": 2,
        "swing_window_4h": 3,
        "recent_10_win_rate": float(params.get("recent_win_rate", 0.5)),
        "recent_10_avg_pnl_ratio": 0.0,
        "max_drawdown_30d": 0.05,
        "account_margin_ratio": 0.10,
        "imr": 0.05,
        "coin_total_deployed": float(params.get("coin_total_deployed", 0.0)),
        "recent_10_count": int(params.get("recent_10_count", 0)),
    }


def _phase_d_heuristic_p_bust(klines_4h, params: dict, direction: str) -> float:
    """MVP 阶段 BiLSTM 权重未完成训练：用 4H 统计特征启发式预估 p_bust。
    真实训练后只需替换为加载 .pt 模型推理即可，接口保持不变。"""
    # 简化特征：ATR% / 最近 12 根最大回撤 / 方向一致性
    closes = []
    highs = []
    lows = []
    for k in klines_4h or []:
        if isinstance(k, dict) and "c" in k:
            closes.append(float(k["c"])); highs.append(float(k.get("h", k["c"]))); lows.append(float(k.get("l", k["c"])))
        elif isinstance(k, (list, tuple)) and len(k) >= 5:
            closes.append(float(k[4])); highs.append(float(k[2])); lows.append(float(k[3]))
    if len(closes) < 12:
        return 0.10  # 数据不足 → 保守偏中性
    recent_c = closes[-12:]
    peak = max(recent_c)
    dd12 = (peak - min(recent_c)) / max(1e-9, peak)
    atr_sum = 0.0
    n = min(len(closes), 14)
    for i in range(-n, 0):
        tr = highs[i] - lows[i]
        atr_sum += tr
    atr_pct = (atr_sum / n) / max(1e-9, closes[-1])
    elder = params.get("elder_ray", 0) if isinstance(params, dict) else 0
    # 方向冲突：做多但 elder<0 或 做空但 elder>0 → 恶化爆仓风险
    direction_ok = (direction == "LONG" and elder >= 0) or (direction == "SHORT" and elder <= 0)
    risk = (dd12 * 0.55) + (atr_pct * 0.25) + (0.0 if direction_ok else 0.20)
    return float(max(0.0, min(0.99, risk)))


def _phase_d_heuristic_dd24h(klines_1h) -> float:
    """MVP 阶段 PatchTST 权重未完成训练：用 1H 波动率启发式估计未来 24 根最大回撤。
    真实训练后替换为 .pt 推理即可，接口保持不变。"""
    closes = []
    for k in klines_1h or []:
        if isinstance(k, dict) and "c" in k:
            closes.append(float(k["c"]))
        elif isinstance(k, (list, tuple)) and len(k) >= 5:
            closes.append(float(k[4]))
    n = min(len(closes), 48)
    if n < 12:
        return 0.06  # 数据不足 → 默认 6% 回撤
    win = closes[-n:]
    rets = [(win[i] / win[i - 1] - 1.0) for i in range(1, len(win))]
    import math
    var = sum(r * r for r in rets) / max(1, len(rets))
    sigma = math.sqrt(var)
    # 未来 24 根 ≈ sigma * sqrt(24) * 系数1.2（保守）
    dd = sigma * math.sqrt(24) * 1.2
    return float(max(0.0, min(0.99, dd)))


# ── 移动止盈参数（从贝叶斯优化活跃参数加载）──
def _load_trailing_params():
    """从 active_params.json 加载移动止盈参数，失败则用默认值"""
    try:
        from bayesian_optimizer import load_active_params

        params = load_active_params()
        return {
            "enabled": get_config_bool("V15_USE_TRAILING_TP", True),
            "atr_mult": params.get("trailing_atr_mult", 1.0),
            "start_ratio": params.get("trailing_start_ratio", 0.8),
        }
    except Exception:
        return {
            "enabled": get_config_bool("V15_USE_TRAILING_TP", True),
            "atr_mult": 1.0,
            "start_ratio": 0.8,
        }


_TRAILING = _load_trailing_params()


# ── 通用风控引擎（13-通用风控模块接入）──
# 影子模式：只输出风控结果，不阻断交易
# 正式模式：RISK_GATE_ENABLED=true 时启用门禁
# 实盘风控参数（2026-07-31 用户要求落地）
V15_COOLDOWN_HOURS = get_config_int("V15_COOLDOWN_HOURS", 48)
V15_FEISHU_ALERT_ENABLED = get_config_bool("V15_FEISHU_ALERT_ENABLED", True)
V15_SYSTEM_NAME = "V15马丁实盘"


# ── 飞书告警接入（复用 15-监控告警系统 模块）──
def _init_feishu_alert():
    """懒加载飞书告警模块，失败降级为本地日志"""
    if not V15_FEISHU_ALERT_ENABLED:
        return None
    try:
        alert_path = BASE_DIR.parent / "15-监控告警系统"
        if str(alert_path) not in sys.path:
            sys.path.insert(0, str(alert_path))
        import feishu_alert as _feishu_module

        _log("[飞书告警] 初始化成功")
        # 直接持有模块，避免 type() 创建的实例把函数当方法调用(self注入)
        return _feishu_module
    except Exception as e:
        _log(f"[飞书告警] 初始化失败，降级为本地日志: {e}")
        return None


_FEISHU_ALERT = None


def _get_feishu_alert():
    global _FEISHU_ALERT
    if _FEISHU_ALERT is None:
        _FEISHU_ALERT = _init_feishu_alert()
    return _FEISHU_ALERT


def _feishu_alert_v15(alert_type, level, message, details=None):
    """V15飞书告警统一入口，失败静默降级"""
    alert = _get_feishu_alert()
    if alert is None:
        _log(f"[告警-local][{level}] {message}")
        return None
    try:
        return alert.send_alert(alert_type, level, message, details or {}, V15_SYSTEM_NAME)
    except Exception as e:
        _log(f"[飞书告警] 发送失败，降级为本地日志: {e} | {alert_type}|{level}|{message}")
        return None


# ── 冷却状态管理 ──
def is_in_cooldown(state):
    """判断是否处于交易冷却暂停期，返回 (是否暂停, 剩余小时, 原因)"""
    cd_until = state.get("cooldown_until", "")
    if not cd_until:
        return False, 0.0, ""
    try:
        cd_dt = datetime.fromisoformat(cd_until.replace("Z", "+00:00"))
    except Exception:
        return False, 0.0, ""
    now_utc = datetime.now(timezone.utc)
    remain_sec = (cd_dt - now_utc).total_seconds()
    if remain_sec <= 0:
        return False, 0.0, ""
    return True, remain_sec / 3600.0, state.get("cooldown_reason", "连续亏损超限")


def enter_cooldown(state, reason: str, hours: int = None):
    """进入交易冷却期，自动飞书告警（只在首次触发时告警）

    并发安全：操作前从磁盘 reload 最新 state（避免多进程旧快照覆盖），
    操作后立即 save_state 落盘。
    """
    hours = hours or V15_COOLDOWN_HOURS
    now_utc = datetime.now(timezone.utc)
    cd_until = now_utc.timestamp() + hours * 3600
    # 从磁盘 reload 最新冷却状态，避免并发进程旧快照覆盖
    latest = load_state()
    if latest.get("cooldown_until"):
        # 已有冷却记录，仅同步到传入的 state 对象，不重复写入
        state["cooldown_until"] = latest["cooldown_until"]
        state["cooldown_reason"] = latest.get("cooldown_reason", "")
        state["cooldown_triggered_at"] = latest.get("cooldown_triggered_at", "")
        return
    cd_until_str = datetime.fromtimestamp(cd_until, tz=timezone.utc).isoformat()
    state["cooldown_until"] = cd_until_str
    state["cooldown_reason"] = reason
    state["cooldown_triggered_at"] = now_utc.isoformat()
    latest["cooldown_until"] = cd_until_str
    latest["cooldown_reason"] = reason
    latest["cooldown_triggered_at"] = now_utc.isoformat()
    save_state(latest)
    _log(f"[风控-冷却] 进入{hours}小时交易冷却暂停，原因: {reason}")
    _log(f"[风控-冷却] 冷却至: {state['cooldown_until']}")
    # 飞书告警：critical级别
    consec = state.get("consecutive_losses", 0)
    daily_pnl = state.get("daily_pnl", 0.0)
    details = {
        "连续亏损": f"{consec}次",
        "冷却时长": f"{hours}小时",
        "冷却至": state["cooldown_until"],
        "日盈亏": f"{daily_pnl:.2f} USDT",
        "持仓数": len(state.get("positions", {})),
        "原因": reason,
    }
    alert = _get_feishu_alert()
    if alert is not None:
        try:
            alert.notify_trading_halted(V15_SYSTEM_NAME, reason, consec, daily_pnl)
        except Exception as e:
            _log(f"[飞书告警] 暂停通知发送失败: {e}")
    # 兜底再发一条（防止 notify_trading_halted 路径异常）
    _feishu_alert_v15("trading", "critical", f"⚠️ 交易暂停{hours}h！{reason}", details)


def exit_cooldown_if_expired(state):
    """冷却期结束自动恢复交易，飞书通知恢复

    并发安全：从磁盘 reload 最新冷却状态判断，避免旧快照误清冷却。
    """
    # 从磁盘 reload 最新冷却状态，避免旧快照导致误判
    latest = load_state()
    cd_until_disk = latest.get("cooldown_until", "")
    if not cd_until_disk:
        # 磁盘上无冷却记录，同步传入的 state 并返回
        state["cooldown_until"] = ""
        state["cooldown_reason"] = ""
        return False
    # 用磁盘最新值判断是否仍在冷却期
    in_cd, remain, reason = is_in_cooldown(latest)
    if in_cd:
        # 仍在冷却期，同步到传入的 state，不可退出
        state["cooldown_until"] = cd_until_disk
        state["cooldown_reason"] = latest.get("cooldown_reason", "")
        state["cooldown_triggered_at"] = latest.get("cooldown_triggered_at", "")
        return False
    # 冷却确已过期（磁盘时间已过）→ 清零并落盘
    _log(f"[风控-冷却] 冷却期已结束，恢复正常交易（原因: {reason or '连续亏损超限'}）")
    details = {
        "冷却结束时间": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "原暂停原因": reason or "连续亏损超限",
        "连续亏损清零": "是",
    }
    state["consecutive_losses"] = 0
    state["cooldown_until"] = ""
    state["cooldown_reason"] = ""
    latest["consecutive_losses"] = 0
    latest["cooldown_until"] = ""
    latest["cooldown_reason"] = ""
    save_state(latest)
    _feishu_alert_v15("trading", "info", "✅ 冷却结束，恢复交易", details)
    return True


def _init_risk_engine():
    """初始化通用风控引擎（懒加载）"""
    try:
        risk_module_path = BASE_DIR.parent / "13-通用风控模块"
        if str(risk_module_path) not in sys.path:
            sys.path.insert(0, str(risk_module_path))
        from core.engine import RiskEngine

        engine = RiskEngine(
            {
                "max_daily_drawdown_pct": 0.10,
                "risk_per_trade_pct": 0.02,
                "max_concurrent_positions": MAX_CONCURRENT_POSITIONS,
                "gate": {
                    "max_concurrent_positions": MAX_CONCURRENT_POSITIONS,
                    "max_daily_loss_usd": abs(get_config_float("V15_DAILY_LOSS_LIMIT", -50)),
                    "max_consecutive_losses": get_config_int("V15_MAX_CONSECUTIVE_LOSSES", 5),
                },
            }
        )
        engine.register_default_rules()
        _log("[风控引擎] 通用风控引擎初始化成功（影子模式）")
        return engine
    except Exception as e:
        _log(f"[风控引擎] 初始化失败，降级: {e}")
        return None


_RISK_ENGINE = None
RISK_GATE_ENABLED = get_config_bool("V15_RISK_GATE_ENABLED", False)


def _get_risk_engine():
    """获取风控引擎单例"""
    global _RISK_ENGINE
    if _RISK_ENGINE is None:
        _RISK_ENGINE = _init_risk_engine()
    return _RISK_ENGINE


def _log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    log_file = LOG_DIR / f"v15_{datetime.now(timezone.utc).strftime('%Y%m%d')}.log"
    with open(log_file, "a") as f:
        f.write(line + "\n")


def _register_martin_trade_to_l4(
    coin: str,
    pos: dict,
    exit_price: float,
    exit_reason: str,
    pnl: float = None,
    pnl_pct: float = None,
):
    """将马丁策略交易记录注册到 L4 统一案例库"""
    if not _L4_ENABLED:
        return None, False

    try:
        trade_id = f"martin_{int(datetime.now(timezone.utc).timestamp())}_{coin}"

        direction = pos.get("direction", "LONG")
        addons = pos.get("addons", 0)
        entry_price = pos.get("entry_price", 0)

        if pnl_pct is None:
            if direction == "SHORT":
                pnl_pct = (entry_price - exit_price) / entry_price if entry_price > 0 else 0
            else:
                pnl_pct = (exit_price - entry_price) / entry_price if entry_price > 0 else 0

        if pnl is None:
            pnl = pnl_pct * pos.get("sz", 0) * entry_price

        event = TradeEvent(
            event_id=TradeEvent.generate_event_id(),
            system_source="martin_v15",
            trade_id=trade_id,
            ts_entry=pos.get("open_time", datetime.now(timezone.utc).isoformat()),
            ts_exit=datetime.now(timezone.utc).isoformat(),
            symbol=pos.get("inst_id", to_swap(coin)),
            direction=direction.lower(),
            entry_price=entry_price,
            exit_price=exit_price,
            position_size=pos.get("sz", 0),
            pnl=pnl,
            pnl_pct=pnl_pct * 100 if abs(pnl_pct) < 10 else pnl_pct,
            exit_reason=exit_reason,
            decision_context={
                "addon_level": addons,
                "martin_config": {
                    "max_addons": MAX_ADDONS,
                    "base_tp_pct": BASE_TP_PCT,
                    "leverage": LEVERAGE,
                },
                "grid_params": pos.get("grid_params", {}),
                "take_profit_pct": pos.get("take_profit_pct"),
                "stop_loss_price": pos.get("stop_loss_price"),
            },
            market_snapshot={
                "regime": pos.get("regime", "unknown"),
                "volatility": pos.get("volatility", 0.02),
            },
            leverage=LEVERAGE,
            margin_usdt=pos.get("margin_usdt", 0),
        )

        registry = UnifiedCaseRegistry()
        case_id, success = registry.register_trade_event(event)

        if success:
            _log(f"[{coin}] L4 案例已注册: {case_id}")
        else:
            _log(f"[{coin}] L4 案例注册失败")

        return case_id, success
    except Exception as e:
        _log(f"[{coin}] L4 注册异常: {e}")
        return None, False


# ── 启动日志：币种池风控过滤结果 ──
_log(
    f"马丁策略币种池: 原始={len(_RAW_COINS)}个, OKX支持={len(_OKX_SUPPORTED)}个, "
    f"风控通过={len(COINS)}个 (min_tier={_MARTIN_MIN_TIER}, min_history_days={_MARTIN_MIN_HISTORY_DAYS})"
)
if _MARTIN_REJECTED:
    _log(
        f"马丁风控剔除币种({len(_MARTIN_REJECTED)}个): {','.join(_MARTIN_REJECTED)} - 原因: 小市值或上线时间不足"
    )
_log(f"最终马丁币种池: {','.join(COINS)}")


def _get_okx_client():
    # PROP-20260816C 模块2（用户批准 2026-08-16）：Paper 执行开关
    # V15_EXECUTION=paper 时替换为本地纸面执行客户端（HL 行情 + 本地账本，无真实下单通道）
    exec_mode = get_config("V15_EXECUTION", "").strip().lower()
    if exec_mode == "paper":
        try:
            from v15_paper_client import V15PaperClient
            return V15PaperClient()
        except Exception as e:
            _log(f"Paper客户端初始化失败: {e}")
            return None
    # 硬安全闸：HL 数据源（网络封锁环境标志）只允许配合 paper 执行，
    # 禁止构造 OKX 实盘客户端 —— 配置错误时快速失败而非静默降级
    if get_config("V15_DATA_SOURCE", "").strip().lower() == "hyperliquid":
        raise RuntimeError(
            "硬安全闸: V15_DATA_SOURCE=hyperliquid 必须配合 V15_EXECUTION=paper, "
            "禁止在网络封锁环境构造 OKX 实盘客户端")
    try:
        from okx_client import OKXSimulatedClient

        config = {
            "api_key": get_config("OKX_API_KEY", ""),
            "secret_key": get_config("OKX_SECRET_KEY", ""),
            "passphrase": get_config("OKX_PASSPHRASE", ""),
            "simulated": False,
            "dry_run": False,
            "base_url": "https://www.okx.com",
            "default_inst_id": "BTC-USDT-SWAP",
            "default_usdt_amount": 100,
            "default_leverage": 5.0,
        }
        client = OKXSimulatedClient(config=config)
        _log(f"OKX实盘客户端已连接 | simulated={client.simulated} dry_run={client.dry_run}")
        return client
    except Exception as e:
        _log(f"OKX客户端连接失败: {e}")
        return None


def load_state():
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                state = json.load(f)
            for _coin, pos in state.get("positions", {}).items():
                if "open_price" not in pos:
                    pos["open_price"] = pos.get("entry_price", 0)
                if "vol_mult" not in pos:
                    pos["vol_mult"] = 1.0
            # 兼容旧 state: 补充冷却/风控相关新字段
            for f in ("cooldown_until", "cooldown_reason", "cooldown_triggered_at"):
                if f not in state:
                    state[f] = ""
            if "consecutive_losses" not in state:
                state["consecutive_losses"] = 0
            if "total_equity" not in state:
                state["total_equity"] = TOTAL_BUDGET
            return state
        except Exception:
            pass
    return {
        "positions": {},
        "total_trades": 0,
        "total_wins": 0,
        "daily_pnl": 0.0,
        "last_poll": "",
        "consecutive_losses": 0,
        "last_capital_rebuild": "",
        "cooldown_until": "",
        "cooldown_reason": "",
        "cooldown_triggered_at": "",
    }


def save_state(state):
    now_iso = datetime.now(timezone.utc).isoformat()
    state["last_poll"] = now_iso
    state["last_sync"] = now_iso
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def _on_win_trade(state, coin: str, reason: str):
    """统一的盈利交易处理：胜场计数+1、连亏清零、记录日盈亏。
    返回：(total_wins, consecutive_losses_reset_to_0)
    """
    state["total_wins"] = state.get("total_wins", 0) + 1
    state["consecutive_losses"] = 0
    _log(f"[{coin}] ✅ 胜场记录: wins={state['total_wins']}, 连亏已清零 ({reason})")
    return state["total_wins"], 0


def _on_loss_trade(state, coin: str, reason: str):
    """统一的亏损交易处理：连亏计数递增、告警、触发冷却（≥6次则48h暂停）。
    返回：(consecutive_losses, triggered_cooldown)
    """
    consec = state.get("consecutive_losses", 0) + 1
    state["consecutive_losses"] = consec
    threshold = get_config_int("V15_MAX_CONSECUTIVE_LOSSES", 6)

    # 连亏告警（warning 或 critical）
    if consec >= 3:
        details = {
            "币种": coin,
            "连续亏损": f"{consec}/{threshold}次",
            "原因": reason,
            "日盈亏": f"{state.get('daily_pnl', 0.0):.2f} USDT",
        }
        alert = _get_feishu_alert()
        if alert is not None:
            try:
                alert.notify_consecutive_losses(V15_SYSTEM_NAME, coin, consec, threshold)
            except Exception as e:
                _log(f"[飞书告警] 连亏通知失败: {e}")
        if consec >= threshold:
            _feishu_alert_v15(
                "trading",
                "critical",
                f"🔴 {coin} 连续亏损 {consec}/{threshold} 次，达到阈值！",
                details,
            )
        else:
            _feishu_alert_v15(
                "trading",
                "warning",
                f"⚠️ {coin} 连续亏损 {consec}/{threshold} 次，接近阈值",
                details,
            )

    # 达到阈值 → 进入冷却（只在首次触发时进入，避免重复告警）
    triggered_cooldown = False
    if consec >= threshold and not state.get("cooldown_until"):
        enter_cooldown(state, reason=f"连续{consec}次亏损达到阈值{threshold}笔")
        triggered_cooldown = True

    # 连亏触发资金优化（原有逻辑，保留）
    if consec >= MAX_CONSECUTIVE_LOSSES_REBUILD:
        trigger_capital_rebuild(state, reason=f"连续{consec}次亏损")

    return consec, triggered_cooldown


def get_v15_decision(coin):
    """获取单个币种的V15经典马丁策略决策（含多空方向控制）"""
    try:
        from v15_signal import v15_decision

        # 获取方向控制上下文
        direction_ctx = None
        if V15_ALLOW_SHORT:
            direction_ctx = _get_direction_ctx(coin)

        # 美股个股永续在 OKX 无现货，用 swap 合约拉 K 线
        from symbol_mapper import AssetCategory

        inst = to_swap(coin) if get_category(coin) == AssetCategory.STOCK else to_spot(coin)
        result = v15_decision(inst, direction_ctx=direction_ctx)
        if direction_ctx:
            result["direction_ctx"] = direction_ctx
        return result
    except Exception as e:
        _log(f"[{coin}] 决策失败: {e}")
        return {"action": "WAIT", "confidence": 0, "reasons": [str(e)]}


def _is_crypto_asset(coin):
    """判断币种是否为加密资产（基于V15_ASSET_TYPES配置）

    加密资产 → BTC风向标智能模式（§16）
    非加密资产（如美股）→ 旧版MA200止损+DirectionGate
    """
    asset_types_str = str(get_config("V15_ASSET_TYPES", ""))
    if not asset_types_str:
        # 配置为空时默认全部为加密资产（向后兼容）
        return True
    for entry in asset_types_str.split(","):
        entry = entry.strip()
        if ":" in entry:
            symbol, asset_type = entry.split(":", 1)
            if symbol.strip().upper() == coin.upper():
                return asset_type.strip().lower() == "crypto"
    # 未在配置中找到的币种，默认为非加密资产（安全默认）
    return False


def _get_direction_ctx(coin):
    """获取币种的多空方向控制上下文（含BTC风向标机制 + Phase A 连续3日确认 + Phase2力学化）

    双模式方向控制：
    - 加密资产：BTC风向标智能模式（§16）
      BTC用自身MA128+DirectionGate，非BTC加密币用BTC风向标3日确认+short_only
    - 非加密资产（如美股）：旧版DirectionGate（日/周MA200三状态模型）
    """
    # 非加密资产 → 旧版DirectionGate逻辑
    if not _is_crypto_asset(coin):
        try:
            from direction_gate import DirectionGate
            from strategy_params import calc_daily_ma128, get_coin_strategy_params

            params = get_coin_strategy_params(coin, "LONG")
            if "error" in params:
                return {"short_enabled": False, "long_enabled": True, "regime": "unknown"}

            klines_1d = params.get("klines_1d", [])
            daily_ma128 = calc_daily_ma128(klines_1d)
            recent_closes = [float(k["c"]) for k in klines_1d[-5:] if "c" in k]

            sl = params["stop_loss"]
            gate = DirectionGate(allow_short=V15_ALLOW_SHORT)
            result = gate.evaluate(
                current_price=params["current_price"],
                daily_ma128=daily_ma128,
                weekly_ma200=sl.get("weekly_ma200"),
                recent_daily_closes=recent_closes,
                btc_short_enabled=V15_ALLOW_SHORT,
            )
            ctx = result.to_dict()
            ctx["btc_short_enabled"] = V15_ALLOW_SHORT
            ctx["btc_confirmed_regime"] = result.regime.value
            ctx["regime_in_cooldown"] = False
            ctx["use_btc_windvane"] = False
            _log(f"[{coin}] 非加密资产模式: regime={result.regime.value}, 做多={result.long_enabled}, 做空={result.short_enabled}")
            ctx["short_enabled"] = False  # 选项3硬闸（用户确认 2026-08-16）：保持做空关闭
            return ctx
        except Exception as e:
            _log(f"[{coin}] 方向控制评估失败(非加密): {e}, 默认只做多")
            return {"short_enabled": False, "long_enabled": True, "regime": "error"}

    # 加密资产 → BTC风向标智能模式（§16）
    try:
        from direction_gate import DirectionGate, VelocityIntegrator
        from regime_manager import RegimeManager
        from strategy_params import calc_daily_ma128, get_coin_strategy_params

        # Phase A: 加载 RegimeManager 状态 + (Phase2) VelocityIntegrator 状态
        rm = RegimeManager(confirm_days=3, initial_regime="LONG_ONLY")
        btc_vi = None  # Phase2: BTC风向标专用速度积分器
        state_blob = None
        try:
            if REGIME_STATE_FILE.exists():
                with open(REGIME_STATE_FILE) as f:
                    state_blob = json.load(f)
                    rm.load_state(state_blob)
                # Phase2: 从同一 state 文件加载 vi state
                if V15_USE_MECHANISTIC_DIRECTION_GATE:
                    vi_saved = (
                        state_blob.get("velocity_integrator_state")
                        if isinstance(state_blob, dict)
                        else None
                    )
                    if vi_saved:
                        btc_vi = VelocityIntegrator.load_state(vi_saved)
                    else:
                        btc_vi = VelocityIntegrator()
        except Exception:
            pass  # 文件不存在或损坏，用默认值
        if V15_USE_MECHANISTIC_DIRECTION_GATE and btc_vi is None:
            btc_vi = VelocityIntegrator()

        # 先获取BTC的方向控制结果作为风向标
        btc_short_enabled = False
        btc_confirmed_regime = "LONG_PREFERRED"
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if V15_ALLOW_SHORT:
            try:
                btc_params = get_coin_strategy_params("BTC", "LONG")
                if "error" not in btc_params:
                    btc_klines_1d = btc_params.get("klines_1d", [])
                    btc_daily_ma128 = calc_daily_ma128(btc_klines_1d)
                    if btc_daily_ma128 is not None:
                        btc_recent_closes = [float(k["c"]) for k in btc_klines_1d[-5:] if "c" in k]
                        # Phase3: swing 检测需要更长的序列（30条日线≈足够 3-6 个 swing 点）
                        btc_closes_30 = [float(k["c"]) for k in btc_klines_1d[-30:] if "c" in k]
                        swing_for_evaluate = btc_closes_30 if V15_USE_SWING_POTENTIAL else None

                        # Phase2: BTC风向标启用力学化
                        btc_gate = DirectionGate(
                            allow_short=True,
                            use_mechanistic=bool(V15_USE_MECHANISTIC_DIRECTION_GATE),
                        )
                        btc_result = btc_gate.evaluate(
                            current_price=btc_params["current_price"],
                            daily_ma128=btc_daily_ma128,
                            weekly_ma200=btc_params["stop_loss"].get("weekly_ma200"),
                            recent_daily_closes=btc_recent_closes,
                            btc_short_enabled=True,  # 自举：BTC风向标先允许，RM确认后再覆盖
                            velocity_integrator=(
                                btc_vi if V15_USE_MECHANISTIC_DIRECTION_GATE else None
                            ),
                            recent_closes_for_swing=swing_for_evaluate,  # Phase3: swing 势场
                            swing_weight=0.5,
                        )
                        # Phase A: 通过 RegimeManager 做确认 + sticky
                        # Phase2: 传 mechanistic_ctx → 动态 1/3/5 天减速检测
                        raw_regime = btc_result.regime.value
                        mechanistic_ctx = None
                        diag = btc_result.mechanistic_diag
                        if V15_USE_MECHANISTIC_DIRECTION_GATE and diag:
                            mechanistic_ctx = {
                                "a": float(diag.get("acceleration", 0.0) or 0.0),
                                "v": float(diag.get("velocity", 0.0) or 0.0),
                                "threshold": float(diag.get("threshold", 0.02) or 0.02),
                            }
                        confirmed_regime = rm.update(
                            raw_regime,
                            date_str=today,
                            mechanistic_ctx=mechanistic_ctx,
                        )
                        btc_confirmed_regime = confirmed_regime
                        btc_short_enabled = confirmed_regime in ("SHORT_ALLOWED",)
                        extra_log = ""
                        if mechanistic_ctx and rm.last_zone:
                            extra_log = (
                                f" [mechanistic zone={rm.last_zone},"
                                f" v={mechanistic_ctx['v']:+.4f}, a={mechanistic_ctx['a']:+.4f}]"
                            )
                        if btc_short_enabled != btc_result.short_enabled or extra_log:
                            _log(
                                f"[PhaseA] BTC形态确认: raw={raw_regime} →"
                                f" confirmed={confirmed_regime} (sticky){extra_log}"
                            )
            except Exception as e:
                _log(f"[BTC风向标] 获取失败: {e}")

        # Phase A: 保存 RegimeManager 状态 + (Phase2) vi state
        try:
            save_blob = rm.save_state()
            if V15_USE_MECHANISTIC_DIRECTION_GATE and btc_vi is not None:
                save_blob["velocity_integrator_state"] = btc_vi.save_state()
            with open(REGIME_STATE_FILE, "w") as f:
                json.dump(save_blob, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

        # Phase A+: 形态切换冷却期检查（切换后2天内不开新仓）
        regime_cooldown_days = 2  # 12根4H bar ≈ 2天
        in_cooldown = rm.is_in_cooldown(regime_cooldown_days, today_str=today)
        if in_cooldown:
            _log(f"[PhaseA+] 形态切换冷却中（距上次切换<{regime_cooldown_days}天），暂停开新仓")

        # 获取当前币种的方向控制（BTC风向标已对闸门位做过滤）
        # BTC风向标智能模式（§16）：BTC用自身MA128+DirectionGate，非BTC加密币用BTC风向标3日确认+short_only
        params = get_coin_strategy_params(coin, "LONG")
        if "error" in params:
            return {"short_enabled": False, "long_enabled": True, "regime": "unknown"}

        # 存量bug修复（用户批准 2026-08-16 选项3）：此3行原误缩进在上方 return
        # 之后成为死代码，daily_ma128/recent_closes 从未赋值 → UnboundLocalError
        # → 方向控制永远降级"只做多"，BTC风向标从未真正生效
        klines_1d = params.get("klines_1d", [])
        daily_ma128 = calc_daily_ma128(klines_1d)
        recent_closes = [float(k["c"]) for k in klines_1d[-5:] if "c" in k]

        sl = params["stop_loss"]
        gate = DirectionGate(allow_short=True)
        result = gate.evaluate(
            current_price=params["current_price"],
            daily_ma128=daily_ma128,
            weekly_ma200=sl.get("weekly_ma200"),
            recent_daily_closes=recent_closes,
            btc_short_enabled=btc_short_enabled,
        )
        ctx = result.to_dict()
        ctx["btc_short_enabled"] = btc_short_enabled
        ctx["btc_confirmed_regime"] = btc_confirmed_regime
        ctx["regime_in_cooldown"] = in_cooldown
        ctx["use_btc_windvane"] = False

        # Phase 4: TimingGate 波浪+斐波那契时机软调控
        # - gate_result 作为方向先验 → TimingGate 方向匹配评分 & 三浪结构 & fib回撤
        # - timing_score → timing_mult = score^V15_TIMING_SIZE_POWER 决定仓位缩放（核心软调控）
        # - soft_mode=True(推荐/BO最优): 不改变 long_enabled 闸门位，只靠 timing_mult 非线性缩仓位
        #   （避免硬门禁丢失交易机会，与回测完全同构）
        # - soft_mode=False(旧模式): long_timing_ok AND DirectionGate，强门禁+线性打折
        if V15_USE_TIMING_GATE:
            try:
                from timing_gate import TimingGate

                # TimingGate 需要更长日线序列（至少 30 条，优先 60 条）用于 swing 检测
                coin_recent_daily = [float(k["c"]) for k in klines_1d[-60:] if "c" in k]
                # 小时级（4H）收盘价序列，用于 swing_fusion_mode="or" 的日线/小时级融合
                coin_recent_4h = [
                    float(k["c"])
                    for k in params.get("klines_4h", [])[-60:]
                    if "c" in k
                ]
                if len(coin_recent_daily) >= 20:
                    tg = TimingGate(
                        swing_window=V15_TIMING_SWING_WINDOW,
                        strict=V15_TIMING_STRICT,
                        threshold=V15_TIMING_THRESHOLD,
                        fib_retrace_lo=V15_TIMING_FIB_RETRACE_LO,
                        fib_retrace_hi=V15_TIMING_FIB_RETRACE_HI,
                        fib_ext_ratio=V15_TIMING_FIB_EXT_RATIO,
                        lenient_unclear=V15_TIMING_LENIENT_UNCLEAR,
                        strict_unclear_score=V15_TIMING_STRICT_UNCLEAR_SCORE,
                        retrace_mu=V15_TIMING_RETRACE_MU,
                        retrace_sigma=V15_TIMING_RETRACE_SIGMA,
                        unclear_retrace_ext=V15_TIMING_UNCLEAR_RETRACE_EXT,
                        swing_fusion_mode=V15_TIMING_SWING_FUSION_MODE,
                        intraday_swing_window=V15_TIMING_INTRADAY_SWING_WINDOW,
                    )
                    # 日线序列 + 小时级序列（用于 OR/AND 融合），与回测 L1747-L1755 参数同构
                    intraday_arg = (
                        coin_recent_4h if len(coin_recent_4h) >= 15 else None
                    )
                    tres = tg.evaluate(
                        result,
                        coin_recent_daily,
                        price_now=params["current_price"],
                        intraday_closes=intraday_arg,
                    )
                    if V15_TIMING_SOFT_MODE:
                        # ── 软调控模式（BO最优，与回测一致）──
                        # 保持 DirectionGate 的 long/short 闸门位不变，不在此处硬阻断
                        # 只把 timing_score 透传给 execute_open_position，用 score^power 非线性缩仓位
                        # （score极低时，mult < V15_TIMING_SKIP_MULT 由 execute_open_position 层跳过）
                        ctx.setdefault("timing_long_ok", bool(tres.long_timing_ok))
                        ctx.setdefault("timing_short_ok", bool(tres.short_timing_ok))
                    else:
                        # ── 硬门禁兼容模式（旧行为，双重惩罚）──
                        ctx["long_enabled"] = (
                            bool(ctx.get("long_enabled", True)) and tres.long_timing_ok
                        )
                        ctx["short_enabled"] = (
                            bool(ctx.get("short_enabled", False)) and tres.short_timing_ok
                        )
                    # 基础评分（线性，幂次在仓位层 compute_timing_mult 处统一应用）
                    ctx["timing_score"] = float(max(0.0, min(1.0, tres.timing_score)))

                    # ── Phase D: G-D3 放宽时机评分（AI 仅可"放宽基线"；收紧不允许） ──
                    _pd_gw2 = _get_phase_d_gateway()
                    if _pd_gw2 is not None:
                        try:
                            # 用 PatchTST 启发式 dd24h 估计作为"未来高波动 → 放宽入场评分"的信号
                            _pd_klines_1h = [
                                float(k["c"]) if isinstance(k, dict) and "c" in k else (float(k[4]) if isinstance(k, (list, tuple)) and len(k) >= 5 else None)
                                for k in params.get("klines_1h", [])
                            ]
                            _pd_klines_1h = [v for v in _pd_klines_1h if v is not None]
                            _pd_dd24h = _phase_d_heuristic_dd24h(_pd_klines_1h)
                            _pd_old_score = ctx["timing_score"]
                            _pd_regime = str(tres.structure.kind if tres.structure else "UNCLEAR")
                            _pd_ctx3 = {"p_bust": _phase_d_p_bust or 0.0, "p_dd": _pd_dd24h}
                            _new_score, _new_power = _pd_gw2.apply_timing_relaxation(
                                coin, _pd_old_score, V15_TIMING_SIZE_POWER, _pd_regime, ctx=_pd_ctx3
                            )
                            if V15_AI_SHADOW:
                                if abs(_new_score - _pd_old_score) > 1e-6:
                                    _log(
                                        f"[Phase-D-SHADOW][{coin}] G-D3 timing_score {_pd_old_score:.3f}→{_new_score:.3f} power {V15_TIMING_SIZE_POWER:.2f}→{_new_power:.2f} (dd24h={_pd_dd24h:.3f} regime={_pd_regime}) 未生效"
                                    )
                            else:
                                ctx["timing_score"] = _new_score
                                if abs(_new_score - _pd_old_score) > 1e-6:
                                    _log(
                                        f"[Phase-D][{coin}] G-D3 放宽时机评分: {_pd_old_score:.3f}→{_new_score:.3f} power {V15_TIMING_SIZE_POWER:.2f}→{_new_power:.2f} (dd24h={_pd_dd24h:.3f} regime={_pd_regime})"
                                    )
                        except Exception as _pd_e2:
                            _log(f"[Phase-D][{coin}] G-D3 评分放宽异常(降级原评分): {_pd_e2}")

                    ctx["timing_zone"] = tres.fib_zone
                    ctx["timing_structure"] = tres.structure.kind if tres.structure else "UNCLEAR"
                    ctx["timing_reason"] = tres.reason
                    # breakdown 透传到 dashboard
                    ctx["timing_breakdown"] = (
                        tres.score_breakdown._asdict() if tres.score_breakdown else {}
                    )
                    # 透传 diagnostic（整包）
                    ctx["timing_diag"] = tres.to_diagnostic()
                    # 软调控 meta：执行层不必重复算，直接在这里给出 timing_mult（score^power）
                    _raw = max(0.0, min(1.0, ctx["timing_score"]))
                    timing_mult = (
                        (_raw ** float(V15_TIMING_SIZE_POWER))
                        if V15_TIMING_SIZE_POWER > 0 and _raw > 0
                        else 0.0
                    )
                    ctx["timing_mult"] = float(timing_mult)
                    ctx["timing_size_power"] = float(V15_TIMING_SIZE_POWER)
                    ctx["timing_soft_mode"] = bool(V15_TIMING_SOFT_MODE)
                    ctx["timing_skip_mult"] = float(V15_TIMING_SKIP_MULT)
                else:
                    ctx["timing_score"] = 1.0  # 日线太少，降级：不调控
                    ctx["timing_mult"] = 1.0
                    ctx["timing_size_power"] = float(V15_TIMING_SIZE_POWER)
                    ctx["timing_zone"] = "NONE"
                    ctx["timing_structure"] = "UNCLEAR"
                    ctx["timing_reason"] = "日线样本不足(<20)，跳过时机评估"
                    ctx["timing_soft_mode"] = bool(V15_TIMING_SOFT_MODE)
                    ctx["timing_skip_mult"] = float(V15_TIMING_SKIP_MULT)
            except Exception as e:
                _log(f"[{coin}] TimingGate 时机评估失败(降级放行): {e}")
                # 失败降级：放行（timing_score=1.0）保持原 ctx 不变，避免影响生产
                ctx.setdefault("timing_score", 1.0)
                ctx.setdefault("timing_mult", 1.0)
        else:
            ctx.setdefault("timing_score", 1.0)  # 关闭时 1.0 表示不调控
            ctx.setdefault("timing_mult", 1.0)

        # Phase2: 将BTC力学诊断透传到返回值，方便监控页面展示
        if V15_USE_MECHANISTIC_DIRECTION_GATE and btc_vi is not None:
            ctx["btc_mechanistic"] = {
                "velocity": btc_vi.velocity,
                "step_count": btc_vi.step_count,
                "last_zone": rm.last_zone,
            }

        # ── BTC风向标智能模式：非BTC加密币种覆盖方向控制（§16）──
        # 非BTC加密币种：使用BTC风向标3日确认 + short_only模式
        # 覆盖DirectionGate的结果，由BTC风向标状态决定多空方向
        if coin.upper() != "BTC" and _is_crypto_asset(coin):
            if btc_confirmed_regime == "SHORT_ALLOWED":
                ctx["short_enabled"] = True
                ctx["long_enabled"] = False  # short_only：SHORT_ALLOWED时只做空不做多
                ctx["regime"] = "SHORT_ALLOWED"
                ctx["use_btc_windvane"] = True
            elif btc_confirmed_regime == "LONG_ONLY_FORCE":
                ctx["short_enabled"] = False
                ctx["long_enabled"] = True  # 强制做多
                ctx["regime"] = "LONG_ONLY_FORCE"
                ctx["use_btc_windvane"] = True
            else:
                # LONG_PREFERRED：默认只做多
                ctx["short_enabled"] = False
                ctx["long_enabled"] = True
                ctx["regime"] = "LONG_PREFERRED"
                ctx["use_btc_windvane"] = True
            _log(f"[{coin}] BTC风向标模式: regime={btc_confirmed_regime}, 做多={ctx['long_enabled']}, 做空={ctx['short_enabled']}")
        else:
            ctx["use_btc_windvane"] = False

        # 选项3硬闸（用户确认 2026-08-16）：保持做空关闭。
        # 风向标正常评估并影响做多质量（熊市形态→山寨观望 long_enabled=False），
        # 但 short_enabled 恒为 False → v15_signal 跳过全部 OPEN_BEAR 分支。
        # 未来恢复做空：删除此行并重新走提案审批。
        ctx["short_enabled"] = False

        return ctx
    except Exception as e:
        _log(f"[{coin}] 方向控制评估失败: {e}, 默认只做多")
        return {"short_enabled": False, "long_enabled": True, "regime": "error"}


# ── Phase B+: 子形态参数微调倍数表 ──────────────────────────────────────
# 宏观(BULL/BEAR) × 微观(Elder-ray 子形态) → tp_mult / holding_mult
# 设计原则：小幅微调(±15~20%)，不做整组参数硬覆盖，避免 Phase B 退化
# - STRONG: 趋势强劲 → 放宽TP+延长持仓，让利润跑
# - WEAK:   动能衰竭/逆转 → 收紧TP+缩短持仓，快速离场
# - NORMAL: 基准
_SUBREGIME_MULTS = {
    "BULL_STRONG": {"tp_mult": 1.10, "holding_mult": 1.20},
    "BULL_WEAK": {"tp_mult": 0.85, "holding_mult": 0.70},
    "BULL_NORMAL": {"tp_mult": 1.00, "holding_mult": 1.00},
    "BEAR_STRONG": {"tp_mult": 1.10, "holding_mult": 1.20},
    "BEAR_WEAK": {"tp_mult": 0.85, "holding_mult": 0.70},
    "BEAR_NORMAL": {"tp_mult": 1.00, "holding_mult": 1.00},
}


def _compute_subregime_live(elder_ray: dict, btc_short_enabled: bool):
    """实盘子形态计算（基于当前 Elder-ray 方向 + 宏观 BTC 形态）

    实盘不依赖历史序列平滑，直接用当前 Elder-ray 方向判定子形态。
    Elder-ray 本身已基于日线 EMA13 斜率 + Bull/Bear Power 计算，具备一定稳定性；
    宏观 BTC MA128 已经过 3 日确认 + sticky，切换频率低。

    Args:
        elder_ray: strategy_params.calc_elder_ray() 返回的 dict（含 direction 字段）
        btc_short_enabled: 宏观 BTC 做空闸门是否打开（True=BEAR 态）

    Returns:
        (subregime_label, tp_mult, holding_mult)
    """
    if elder_ray is None or not isinstance(elder_ray, dict):
        return ("NORMAL", 1.0, 1.0)

    d = elder_ray.get("direction", "SIDEWAYS")
    macro = "BEAR" if btc_short_enabled else "BULL"

    if macro == "BEAR":
        if d in ("STRONG_BEAR", "BEAR_TREND"):
            sub = "BEAR_STRONG"
        elif d == "BEAR_REVERSAL":
            sub = "BEAR_WEAK"
        else:
            sub = "BEAR_NORMAL"
    else:
        if d in ("STRONG_BULL", "BULL_TREND"):
            sub = "BULL_STRONG"
        elif d == "BULL_REVERSAL":
            sub = "BULL_WEAK"
        else:
            sub = "BULL_NORMAL"

    mults = _SUBREGIME_MULTS.get(sub, {"tp_mult": 1.0, "holding_mult": 1.0})
    return (sub, mults["tp_mult"], mults["holding_mult"])


# ── Phase C: 易经推理桥接（懒加载，首次使用时初始化）──────────────────────
_yiji_bridge = None
_yiji_bridge_initialized = False


def _get_yiji_bridge():
    """懒加载 YijingBridge（避免模块加载时初始化失败影响整体）"""
    global _yiji_bridge, _yiji_bridge_initialized
    if not _yiji_bridge_initialized:
        _yiji_bridge_initialized = True
        try:
            from yijing_bridge import YijingBridge

            _yiji_bridge = YijingBridge()
            if not _yiji_bridge.available:
                _log("Phase C: 易经桥接不可用（YijingEngine 加载失败），降级为仅子形态")
                _yiji_bridge = None
        except Exception as e:
            _log(f"Phase C: 易经桥接初始化失败: {e}，降级为仅子形态")
            _yiji_bridge = None
    return _yiji_bridge


def check_capital():
    """检查资金是否允许开新仓"""
    try:
        from capital_manager import calculate_capital_allocation

        alloc = calculate_capital_allocation()
        return alloc["recommendations"]["allow_open_new_position"], alloc
    except Exception as e:
        _log(f"资金检查失败: {e}")
        return False, {}


def execute_open_position(client, coin, decision, state):
    """执行开仓 - 支持多空方向"""
    inst_id = to_swap(coin)
    conf = decision.get("confidence", 0)
    action = decision.get("action", "WAIT")

    # 判断多空方向
    is_short = action == "OPEN_BEAR"
    direction = "SHORT" if is_short else "LONG"

    if conf < 60:
        _log(f"[{coin}] 置信度不足({conf}<60), 跳过")
        return False

    # ── Phase D: G-D1 跳过开仓闸门（铁律：默认关闭时整段跳过） ──
    # 这里必须保证 V15_AI_ENABLED=False 时，以下代码无任何副作用（状态文件不创建、变量值不变异）
    # V15_AI_SHADOW=True 时：只记录决策日志不实际跳过，便于上线前后对比 AI 判断
    _phase_d_gw = _get_phase_d_gateway()
    _phase_d_p_bust = None
    _phase_d_effective_max_addons = None
    if _phase_d_gw is not None:
        try:
            # 预取 dynamic params 里的 klines_4h / elder_ray 用于构造预估（不影响后续 params 取数）
            _pd_params = _get_dynamic_params(client, coin, direction)
            _phase_d_p_bust = _phase_d_heuristic_p_bust(
                _pd_params.get("klines_4h"), _pd_params, direction
            )
            _pd_dd24h = _phase_d_heuristic_dd24h([
                float(k["c"]) if isinstance(k, dict) and "c" in k else (float(k[4]) if isinstance(k, (list, tuple)) and len(k) >= 5 else None)
                for k in _pd_params.get("klines_1h", [])
            ])
            # ctx dict 携带 heuristic 预估，gateway 内部 predict 函数会优先读取
            _pd_ctx = {"p_bust": _phase_d_p_bust, "p_dd": _pd_dd24h, "coin": coin}
            if V15_AI_SHADOW:
                _skip_shadow = _phase_d_gw.should_skip_open(_pd_ctx)
                _log(
                    f"[Phase-D-SHADOW][{coin}] G-D1 bust_prob={_phase_d_p_bust:.3f} dd24h={_pd_dd24h:.3f} should_skip={_skip_shadow}（SHADOW 不生效）"
                )
            else:
                if _phase_d_gw.should_skip_open(_pd_ctx):
                    _log(f"[Phase-D][{coin}] G-D1 跳过开仓: BiLSTM 爆仓概率={_phase_d_p_bust:.3f}")
                    return False
            # G-D2：effective_max_addons 保存起来，稍后在加仓预算/网格处使用
            _addon_budgets = {f"addon{k}_usd": 0 for k in [1, 2, 3, 4]}  # 占位，实际预算在 alloc 后填入
            _eff, _ = _phase_d_gw.compute_effective_max_addons(
                coin, _pd_ctx, MAX_ADDONS, _addon_budgets
            )
            _phase_d_effective_max_addons = int(_eff)
            if _phase_d_effective_max_addons != MAX_ADDONS:
                _log(
                    f"[Phase-D][{coin}] G-D2 加仓档数: 基线={MAX_ADDONS} → 实际={_phase_d_effective_max_addons} (bust_prob={_phase_d_p_bust:.3f}){' [SHADOW]' if V15_AI_SHADOW else ''}"
                )
        except Exception as _pd_e:
            _log(f"[Phase-D][{coin}] G-D1/G-D2 评估异常(降级基线): {_pd_e}")
            _phase_d_p_bust = None
            _phase_d_effective_max_addons = None

    # ── 通用事前风控检查（13-通用风控模块）──
    risk_engine = _get_risk_engine()
    if risk_engine:
        try:
            from core.context import Direction, RiskContext
            from core.context import Signal as RiskSignal

            direction_val = Direction.SHORT if is_short else Direction.LONG
            risk_signal = RiskSignal(
                coin=coin,
                direction=direction_val,
                confidence=conf / 100.0,
                strategy="v15_martin",
            )

            daily_pnl = state.get("daily_pnl", 0.0)
            total_equity = state.get("total_equity", TOTAL_BUDGET)
            consecutive_losses = state.get("consecutive_losses", 0)

            risk_ctx = RiskContext(
                total_equity=total_equity,
                available_balance=total_equity * 0.5,
                daily_pnl=daily_pnl,
                consecutive_losses=consecutive_losses,
                total_trades=state.get("total_trades", 0),
                total_wins=state.get("total_wins", 0),
            )

            risk_result = risk_engine.pre_trade_check(risk_signal, risk_ctx)

            mode = "门禁" if RISK_GATE_ENABLED else "影子"
            status = "PASS" if risk_result.passed else "BLOCK"
            _log(
                f"[风控-{mode}][{coin}] {status} "
                f"reason={risk_result.reason_code.value} "
                f"modifier={risk_result.position_modifier:.2f} "
                f"msg={risk_result.message}"
            )

            if RISK_GATE_ENABLED and not risk_result.passed:
                _log(f"[风控-门禁][{coin}] 阻断开仓: {risk_result.message}")
                return False

            if risk_result.position_modifier != 1.0:
                _log(f"[风控-{mode}][{coin}] 仓位调整系数: " f"{risk_result.position_modifier:.2f}")
        except Exception as e:
            _log(f"[风控] 检查异常，跳过风控: {e}")

    try:
        params = _get_dynamic_params(client, coin, direction)
        price = params["current_price"]
        if price <= 0:
            _log(f"[{coin}] 价格异常: {price}")
            return False

        effective_conf = conf
        if BOUNCE_FILTER_ENABLED and BOUNCE_MONITOR_ENABLED and not is_short:
            klines_4h = params.get("klines_4h")
            if klines_4h:
                bounce_signal = evaluate_signals(coin, klines_4h, lookback=60)
                if bounce_signal["valid"] and bounce_signal["n_triggered"] >= BOUNCE_MIN_SIGNALS:
                    triggers = ", ".join(bounce_signal["triggered_list"])
                    effective_conf = conf + bounce_signal["n_triggered"] * 10
                    _log(
                        f"[{coin}] 反弹信号加持({triggers}): n_triggered={bounce_signal['n_triggered']}, 置信度从{conf}%增强至{effective_conf}%"
                    )
                else:
                    _log(
                        f"[{coin}] 无反弹信号(n_triggered={bounce_signal.get('n_triggered', 0)})，保持原始置信度{conf}%"
                    )
            else:
                _log(f"[{coin}] 无4H K线数据，保持原始置信度{conf}%")
        else:
            _log(f"[{coin}] 反弹检测未启用或做空方向，保持原始置信度{conf}%")

        # 维度错配修复 v2（2026-07-31）：
        # stop_loss_triggered 用日/周 MA200 判断，而开仓信号用 4H SMA 判断
        # 马丁策略本就是逆势抄底，单均线触发时日/周 MA200 下方开多是正常场景
        # 但 BELOW_ALL_MA_CONFIRMED（所有均线确认跌破）= 强下跌趋势，开仓即触发止损
        # 逻辑矛盾：开仓允许 + 平仓立即止损 → 死循环（高频亏损根因）
        # 修复：BELOW_ALL_MA_CONFIRMED 时拒绝开仓；其他单均线触发时仓位减半
        #
        # BTC风向标智能模式（§16）：
        # - 非BTC加密币种已移除MA200止损（sl_type=BTC_WINDVANE），跳过此检查
        # - 非加密资产（如美股）保留MA200止损检查
        risk_mult = 1.0
        if params["stop_loss_triggered"] and params["stop_loss_type"] != "BTC_WINDVANE":
            sl_type = params["stop_loss_type"]
            if sl_type == "BELOW_ALL_MA_CONFIRMED":
                _log(
                    f"[{coin}] 拒绝开仓: {sl_type}触发(所有均线确认跌破,强下跌趋势), "
                    f"开仓即触发止损,避免死循环"
                )
                return False
            risk_mult = 0.5
            _log(
                f"[{coin}] 风控提示: {sl_type}触发(日/周MA200下方), "
                f"维度错配修复: 仓位倍数降至{risk_mult}x"
            )

        tp_pct = params["take_profit_pct"]
        addon_pct = params["addon_pct"]
        sl_price = params["stop_loss_price"]
        sl_type = params["stop_loss_type"]

        # ── 智能资金分配（使用增强置信度）──
        from capital_manager import calculate_per_coin_allocation

        elder_ray = params.get("elder_ray")
        alloc = calculate_per_coin_allocation(coin, effective_conf, elder_ray)

        if not alloc.get("allowed"):
            _log(f"[{coin}] 资金分配不允许: {alloc.get('reason', '资金不足')}")
            return False

        # ── Phase D: G-D2 缩减加仓档（裁剪多余 addon*_usd 预算） ──
        # V15_AI_SHADOW=True 时不修改预算值，仅打印日志
        _pd_original_addons = {f"addon{k}_usd": alloc.get(f"addon{k}_usd", 0) for k in [1, 2, 3, 4]}
        if (
            _phase_d_effective_max_addons is not None
            and _phase_d_effective_max_addons < MAX_ADDONS
            and not V15_AI_SHADOW
        ):
            for _k in range(_phase_d_effective_max_addons + 1, MAX_ADDONS + 1):
                alloc[f"addon{_k}_usd"] = 0

        # ── Phase E: PPO-LSTM 加仓金字塔动作（默认关闭=基线等价） ──
        _phase_e_gw = _get_phase_e_gateway()
        if _phase_e_gw is not None:
            try:
                _pe_s_state = _phase_e_build_s_state(coin, params)
                _pe_alloc_before = {k: alloc.get(k, 0) for k in ["base_usd", "addon1_usd", "addon2_usd", "addon3_usd", "addon4_usd", "total_usd", "per_coin_budget"]}
                alloc = _phase_e_gw.apply_size_multipliers(alloc, _pe_s_state)
                _pe_alloc_after = {k: alloc.get(k, 0) for k in ["base_usd", "addon1_usd", "addon2_usd", "addon3_usd", "addon4_usd"]}
                _log(f"[Phase-E][{coin}] PPO 动作: {_pe_alloc_before.get('total_usd', 0):.1f} → {alloc.get('total_usd', 0):.1f}  action={alloc.get('ai_action', {})}")
            except Exception as _pe_e:
                _log(f"[Phase-E][{coin}] apply_size_multipliers 异常(降级基线): {_pe_e}")

        # ── Phase B+: 子形态参数微调（TP + 持仓时间，±15~20%）──
        dir_ctx = decision.get("direction_ctx") or {}
        btc_short_enabled = dir_ctx.get("btc_short_enabled", False)
        subregime, tp_mult, holding_mult = _compute_subregime_live(elder_ray, btc_short_enabled)

        # ── Phase C: 易经 risk/value 插值（在子形态基础上叠加）──
        # v15 最终形态：默认关闭（V15_YIJING_ENABLED=False），仅使用 Phase B+ 子形态
        yiji_risk = None
        yiji_value = None
        yiji_hex = ""
        bridge = _get_yiji_bridge() if V15_YIJING_ENABLED else None
        _yiji_klines = params.get("klines_4h")
        if bridge and _yiji_klines:
            try:
                yiji_result = bridge.infer_current(_yiji_klines)
                yiji_risk = yiji_result["risk_score"]
                yiji_value = yiji_result["value_score"]
                yiji_hex = yiji_result.get("hexagram", "")
                from yijing_param_interpolator import interpolate_params

                sr_mults = {"tp_mult": tp_mult, "holding_mult": holding_mult, "size_mult": 1.0}
                final_mults = interpolate_params(yiji_risk, yiji_value, subregime_mults=sr_mults)
                # 用最终倍数覆盖子形态倍数
                tp_mult = final_mults["tp_mult"]
                holding_mult = final_mults["holding_mult"]
            except Exception as e:
                _log(f"[{coin}] Phase C 易经插值失败: {e}，降级为仅子形态")

        if tp_mult != 1.0:
            tp_pct = tp_pct * tp_mult
            log_parts = [f"PhaseB+ 子形态={subregime}"]
            if yiji_hex:
                log_parts.append(f"卦={yiji_hex} risk={yiji_risk:.2f} value={yiji_value:.2f}")
            log_parts.append(
                f"tp_mult={tp_mult:.2f} hold_mult={holding_mult:.2f} → TP={tp_pct*100:.2f}%"
            )
            _log(f"[{coin}] {' '.join(log_parts)}")

        base_margin = alloc["base_usd"]
        vol_mult = decision.get("vol_mult", 1.0) * risk_mult
        # ── Phase 4: 波浪+fib 时机评分软调控（与回测 v15_backtest.py L1877-L1884 完全同构）──
        # 优先用上层已计算的 timing_mult（=score^V15_TIMING_SIZE_POWER），缺失时回退自算
        timing_score = float(dir_ctx.get("timing_score", 1.0) or 1.0)
        timing_score = max(0.0, min(1.0, timing_score))
        _ctx_mult = dir_ctx.get("timing_mult")
        if _ctx_mult is not None:
            timing_mult = float(_ctx_mult)
        else:
            # 降级：自算幂次，保持语义一致
            _pow = float(dir_ctx.get("timing_size_power", V15_TIMING_SIZE_POWER) or V15_TIMING_SIZE_POWER)
            timing_mult = (timing_score ** _pow) if _pow > 0 and timing_score > 0 else 0.0
        timing_mult = max(0.0, min(1.0, timing_mult))
        soft_mode = bool(dir_ctx.get("timing_soft_mode", V15_TIMING_SOFT_MODE))
        skip_mult = float(dir_ctx.get("timing_skip_mult", V15_TIMING_SKIP_MULT) or V15_TIMING_SKIP_MULT)

        # 软调控模式下，非线性惩罚到极小仓位时直接跳过
        # （回测 v15_backtest.py L1883: if timing_mult < 0.02 → continue）
        if soft_mode and timing_mult < skip_mult:
            _log(
                f"[{coin}] TimingGate 软调控跳过: "
                f"score={timing_score:.3f} mult={timing_mult:.5f} (< skip={skip_mult})"
                f" 结构={dir_ctx.get('timing_structure','UNCLEAR')} zone={dir_ctx.get('timing_zone','NONE')}"
                f" | {dir_ctx.get('timing_reason', '')}"
            )
            return False

        order_margin = base_margin * vol_mult * timing_mult
        order_notional = order_margin * LEVERAGE

        lot_sz, ct_val = get_contract_info(client, inst_id)
        sz = calc_lot_sz(order_notional, price, lot_sz, ct_val)
        if sz < lot_sz:
            _log(f"[{coin}] 下单数量({sz}张)小于最小单位({lot_sz}张), 跳过")
            return False

        actual_notional = sz * ct_val * price
        actual_margin = actual_notional / LEVERAGE

        adj = alloc.get("adjustments", {})
        sl_display = f"${sl_price:.4f}" if sl_price else "无(仅止盈)"
        # 展示 timing_mult（真正乘到仓位的幂次后值）+ 原始线性score用于诊断
        if dir_ctx.get("timing_score") is not None:
            _pow_shown = dir_ctx.get("timing_size_power", V15_TIMING_SIZE_POWER)
            timing_display = (
                f" timing={timing_mult:.3f}x (score={timing_score:.2f}^pow={_pow_shown})"
                f" zone={dir_ctx.get('timing_zone','NONE')}"
                f" str={dir_ctx.get('timing_structure','UNCLEAR')}"
                + (" [SOFT]" if soft_mode else " [HARD]")
            )
        else:
            timing_display = ""
        _log(
            f"[{coin}] 开仓 {direction} sz={sz}张 price={price} 保证金=${actual_margin:.2f} 名义=${actual_notional:.2f} "
            f"TP={tp_pct*100:.2f}% SL={sl_type}@{sl_display} conf={conf}% "
            f"资金分配: 趋势={adj.get('strength_mult', 1.0):.2f}x 置信={adj.get('conf_mult', 1.0):.2f}x "
            f"波动={adj.get('vol_adjust', 1.0):.2f}x 综合={adj.get('combined_mult', 1.0):.2f}x "
            f"EMA={adj.get('elder_ray_direction', 'N/A')} "
            f"Dir={adj.get('elder_ray_ema_trend', 'N/A')} "
            f"强度={adj.get('elder_ray_strength', 0):.1f}"
            f"{timing_display}"
        )

        if AUTO_EXECUTE:
            # 做空: side="sell", pos_side="short"; 做多: side="buy", pos_side="long"
            side = "sell" if is_short else "buy"
            pos_side = "short" if is_short else "long"
            r = client.place_order(
                inst_id=inst_id,
                side=side,
                sz=sz,
                td_mode="isolated",
                pos_side=pos_side,
            )
            if r.get("ok"):
                _log(f"[{coin}] 开仓成功: {r.get('data', {})}")
                state["positions"][coin] = {
                    "inst_id": inst_id,
                    "direction": direction,
                    "entry_price": price,
                    "open_price": price,
                    "sz": sz,
                    "addons": 0,
                    "confidence": conf,
                    "open_time": datetime.now(timezone.utc).isoformat(),
                    "take_profit_pct": tp_pct,
                    "addon_pct": addon_pct,
                    "stop_loss_price": sl_price,
                    "stop_loss_type": sl_type,
                    "vol_mult": vol_mult,
                    "per_coin_budget": alloc.get("per_coin_budget", 0),
                    "base_usd": alloc.get("base_usd", 0),
                    "addon1_usd": alloc.get("addon1_usd", 0),
                    "addon2_usd": alloc.get("addon2_usd", 0),
                    "addon3_usd": alloc.get("addon3_usd", 0),
                    "addon4_usd": alloc.get("addon4_usd", 0),
                    # 移动止盈状态
                    "trailing_active": False,
                    "trailing_price": None,
                    "peak_price": price,
                    # Phase B+: 子形态微调记录（持仓超时检查时使用 holding_mult）
                    "subregime": subregime,
                    "tp_mult": tp_mult,
                    "holding_mult": holding_mult,
                    # Phase C: 易经推理记录（便于后续分析监控，None 表示桥接降级）
                    "yiji_risk": yiji_risk,
                    "yiji_value": yiji_value,
                    "yiji_hexagram": yiji_hex,
                    # Phase 4: TimingGate 时机评分（整仓保持，含加仓继承）
                    "timing_score": timing_score,
                    "timing_mult": timing_mult,
                    "timing_size_power": dir_ctx.get("timing_size_power", V15_TIMING_SIZE_POWER),
                    "timing_zone": dir_ctx.get("timing_zone", "NONE"),
                    "timing_structure": dir_ctx.get("timing_structure", "UNCLEAR"),
                    # Phase D: AI 决策记录（便于分析与跨轮询生效；None=未启用）
                    # 影子模式下 ai_effective_max_addons=None → execute_addon / grid 回退 MAX_ADDONS（基线）
                    "ai_p_bust": _phase_d_p_bust,
                    "ai_effective_max_addons": None if V15_AI_SHADOW else _phase_d_effective_max_addons,
                    # BTC风向标智能模式：记录开仓时的BTC风向标状态（供止损检查对比）
                    "btc_regime_at_open": dir_ctx.get("btc_confirmed_regime", "LONG_PREFERRED"),
                    "use_btc_windvane": dir_ctx.get("use_btc_windvane", False),
                }
                state["total_trades"] += 1
                _sync_tp_sl_orders(client, coin, state["positions"][coin], price, tp_pct, sl_price)
                _place_addon_grid_orders(client, coin, state["positions"][coin])
                return True
            else:
                _log(f"[{coin}] 开仓失败: {r.get('error', r)}")
                return False
        else:
            _log(f"[{coin}] 模拟模式: 不执行实盘下单")
            return False
    except Exception as e:
        _log(f"[{coin}] 开仓异常: {e}")
        return False


def execute_addon(client, coin, pos, state):
    """执行加仓 - 使用持仓时分配的加仓预算（支持多空方向）

    做多：价格下跌到加仓间距时加仓（经典马丁）
    做空：价格上涨到加仓间距时加仓（反向马丁）
    """
    inst_id = pos["inst_id"]
    addons = pos.get("addons", 0)
    direction = pos.get("direction", "LONG")
    is_short = direction == "SHORT"

    # Phase D: G-D2 缩减加仓档 → effective_max_addons（未启用时回退 MAX_ADDONS）
    eff_max = pos.get("ai_effective_max_addons")
    if eff_max is None:
        eff_max = MAX_ADDONS
    eff_max = int(max(0, min(MAX_ADDONS, eff_max)))
    if addons >= eff_max:
        _log(f"[{coin}] 已达最大加仓次数(当前={addons} 上限={eff_max} 基线MAX={MAX_ADDONS})")
        return False

    try:
        from capital_manager import calculate_capital_allocation

        alloc = calculate_capital_allocation()
        if not alloc["recommendations"]["allow_addon"]:
            _log(f"[{coin}] 资金不足, 跳过加仓")
            return False

        params = _get_dynamic_params(client, coin, direction)
        addon_pct = params["addon_pct"]
        current_price = params["current_price"]
        if current_price <= 0:
            return False

        # 使用开仓时分配的加仓预算（同时继承入场时 timing_mult，保持整仓尺度一致，与回测同构）
        # 优先用开仓时已计算好的 timing_mult（=score^pow），否则退化自算（兼容老持仓）
        _saved_mult = pos.get("timing_mult")
        if _saved_mult is not None:
            timing_mult = float(_saved_mult)
        else:
            _raw_score = float(pos.get("timing_score", 1.0) or 1.0)
            _pow = float(pos.get("timing_size_power", V15_TIMING_SIZE_POWER) or V15_TIMING_SIZE_POWER)
            timing_mult = ((max(0.0, min(1.0, _raw_score)) ** _pow) if _pow > 0 else 0.0)
        timing_mult = max(0.0, min(1.0, timing_mult))
        addon_budgets = [
            pos.get("addon1_usd", 0),
            pos.get("addon2_usd", 0),
            pos.get("addon3_usd", 0),
            pos.get("addon4_usd", 0),
        ]
        addon_usd = addon_budgets[addons] if addons < len(addon_budgets) else 0
        if addon_usd <= 0:
            # 回退到旧逻辑
            base_margin = alloc["single_position_cost"]["base_usd"]
            vol_mult = pos.get("vol_mult", 1.0)
            addon_usd = base_margin * vol_mult * (addon_pct * (addons + 1)) * timing_mult
        else:
            # 预算来自 alloc 未乘 timing，这里补乘 timing_mult
            addon_usd = addon_usd * timing_mult

        vol_mult = pos.get("vol_mult", 1.0)
        addon_margin = addon_usd * vol_mult
        addon_notional = addon_margin * LEVERAGE

        open_price = pos.get("open_price", pos["entry_price"])
        target_pct = addon_pct * (addons + 1)
        if is_short:
            # 做空：价格上涨才加仓（反向马丁）
            move_pct = (current_price - open_price) / open_price
            if move_pct < target_pct:
                _log(
                    f"[{coin}] 涨幅不足({move_pct:.2%}<{target_pct:.2%}), 跳过加空 (第{addons+1}层)"
                )
                return False
        else:
            # 做多：价格下跌才加仓（经典马丁）
            move_pct = (open_price - current_price) / open_price
            if move_pct < target_pct:
                _log(
                    f"[{coin}] 跌幅不足({move_pct:.2%}<{target_pct:.2%}), 跳过加仓 (第{addons+1}层)"
                )
                return False

        lot_sz, ct_val = get_contract_info(client, inst_id)
        sz = calc_lot_sz(addon_notional, current_price, lot_sz, ct_val)
        if sz < lot_sz:
            _log(f"[{coin}] 加仓数量({sz}张)小于最小单位({lot_sz}张), 跳过")
            return False

        actual_notional = sz * ct_val * current_price
        actual_margin = actual_notional / LEVERAGE
        move_label = "涨幅" if is_short else "跌幅"
        _log(
            f"[{coin}] 加仓#{addons+1} {direction} sz={sz}张 price={current_price} 保证金=${actual_margin:.2f} 名义=${actual_notional:.2f} "
            f"开仓价=${open_price:.2f} {move_label}={move_pct:.2%} 预算=${addon_usd:.2f}"
        )

        if AUTO_EXECUTE:
            # 做空加仓: side="sell", pos_side="short"; 做多加仓: side="buy", pos_side="long"
            side = "sell" if is_short else "buy"
            pos_side = "short" if is_short else "long"
            r = client.place_order(
                inst_id=inst_id,
                side=side,
                sz=sz,
                td_mode="isolated",
                pos_side=pos_side,
            )
            if r.get("ok"):
                pos["addons"] = addons + 1
                pos["entry_price"] = (pos["entry_price"] * pos["sz"] + current_price * sz) / (
                    pos["sz"] + sz
                )
                pos["sz"] += sz
                pos["last_addon_time"] = datetime.now(timezone.utc).isoformat()
                _log(f"[{coin}] 加仓成功, 总仓位={pos['sz']} 均价=${pos['entry_price']:.2f}")
                tp_pct = pos.get("take_profit_pct", addon_pct)
                sl_price = pos.get("stop_loss_price", params.get("stop_loss_price"))
                _sync_tp_sl_orders(client, coin, pos, pos["entry_price"], tp_pct, sl_price)
                return True
            else:
                _log(f"[{coin}] 加仓失败: {r.get('error', r)}")
                return False
        return False
    except Exception as e:
        _log(f"[{coin}] 加仓异常: {e}")
        return False


def _get_dynamic_params(client, coin, direction="LONG"):
    """获取币种的动态策略参数（止盈、加仓、止损）

    BTC风向标智能模式（§16）：
    - BTC：保留自身MA200/EMA200动态止损
    - 非BTC币种：移除自身MA200止损，止损由BTC风向标状态控制
      → BTC触发SHORT_ALLOWED时平掉非BTC多仓
      → BTC触发LONG_ONLY_FORCE时平掉非BTC空仓
    """
    from strategy_params import get_coin_strategy_params

    params = get_coin_strategy_params(coin, direction)
    if "error" in params:
        raise ValueError(params["error"])

    sl = params["stop_loss"]
    vol = params["volatility"]

    # ── BTC风向标智能模式：加密资产非BTC币种移除自身MA200止损 ──
    # 非加密资产（如美股）保留旧版MA200止损
    if coin.upper() != "BTC" and _is_crypto_asset(coin):
        # 非BTC加密币种：不使用自身MA200止损，由BTC风向标状态控制平仓
        # 止损价格设为None，止损触发由check_take_profit中的BTC风向标状态检查处理
        return {
            "current_price": params["current_price"],
            "take_profit_pct": params["take_profit_pct"] / 100,
            "addon_pct": params["addon_pct"] / 100,
            "stop_loss_price": None,
            "stop_loss_pct": None,
            "stop_loss_type": "BTC_WINDVANE",
            "stop_loss_triggered": False,  # 由BTC风向标状态动态判断
            "daily_ma200": sl["daily_ma200"],
            "daily_ema200": sl["daily_ema200"],
            "weekly_ma200": sl["weekly_ma200"],
            "weekly_ema200": sl["weekly_ema200"],
            "above_daily_ma200": sl["above_daily_ma200_close"],
            "above_daily_ema200": sl["above_daily_ema200_close"],
            "above_weekly_ma200": sl["above_weekly_ma200_close"],
            "above_weekly_ema200": sl["above_weekly_ema200_close"],
            "last_daily_close": params.get("last_daily_close"),
            "last_weekly_close": params.get("last_weekly_close"),
            "volatility": vol,
            "elder_ray": params.get("elder_ray"),
            "klines_4h": params.get("klines_4h"),
        }

    # BTC：保留自身MA200/EMA200动态止损
    return {
        "current_price": params["current_price"],
        "take_profit_pct": params["take_profit_pct"] / 100,
        "addon_pct": params["addon_pct"] / 100,
        "stop_loss_price": sl["stop_loss_price"],
        "stop_loss_pct": sl["stop_loss_pct"],
        "stop_loss_type": sl["stop_type"],
        "stop_loss_triggered": sl["is_triggered"],
        "daily_ma200": sl["daily_ma200"],
        "daily_ema200": sl["daily_ema200"],
        "weekly_ma200": sl["weekly_ma200"],
        "weekly_ema200": sl["weekly_ema200"],
        "above_daily_ma200": sl["above_daily_ma200_close"],
        "above_daily_ema200": sl["above_daily_ema200_close"],
        "above_weekly_ma200": sl["above_weekly_ma200_close"],
        "above_weekly_ema200": sl["above_weekly_ema200_close"],
        "last_daily_close": params.get("last_daily_close"),
        "last_weekly_close": params.get("last_weekly_close"),
        "volatility": vol,
        "elder_ray": params.get("elder_ray"),
        "klines_4h": params.get("klines_4h"),
    }


def _place_addon_grid_orders(client, coin, pos):
    """开仓时预挂4档加仓限价单（马丁网格，1首单+4加仓=总5单）

    做多：在开仓价下方 -8%/-16%/-24%/-32% 挂买入限价单
    做空：在开仓价上方 +8%/+16%/+24%/+32% 挂卖出限价单

    每档加仓数量按金字塔资金分配（addon1_usd/addon2_usd/addon3_usd/addon4_usd）计算。
    挂单 ord_id 记录到 pos["addon_grid"] 供轮询时检查与调整。

    Args:
        client: OKX 客户端
        coin: 币种
        pos: 持仓信息 dict（含 open_price, direction, addon*_usd, inst_id）
    """
    if not AUTO_EXECUTE:
        return

    inst_id = pos["inst_id"]
    direction = pos.get("direction", "LONG")
    is_short = direction == "SHORT"
    open_price = pos.get("open_price", pos.get("entry_price", 0))
    if open_price <= 0:
        return

    addon_pct = pos.get("addon_pct", ADDON_PCT)
    addon_budgets = [
        pos.get("addon1_usd", 0),
        pos.get("addon2_usd", 0),
        pos.get("addon3_usd", 0),
        pos.get("addon4_usd", 0),
    ]
    vol_mult = pos.get("vol_mult", 1.0)
    # 继承入场时 timing_mult：整组加仓预算同比例缩放（与回测 v15_backtest.py L2214-L2220 同构）
    _saved_mult = pos.get("timing_mult")
    if _saved_mult is not None:
        timing_mult = float(_saved_mult)
    else:
        _raw_score = float(pos.get("timing_score", 1.0) or 1.0)
        _pow = float(pos.get("timing_size_power", V15_TIMING_SIZE_POWER) or V15_TIMING_SIZE_POWER)
        timing_mult = ((max(0.0, min(1.0, _raw_score)) ** _pow) if _pow > 0 else 0.0)
    timing_mult = max(0.0, min(1.0, timing_mult))

    lot_sz, ct_val = get_contract_info(client, inst_id)
    pos_side = "short" if is_short else "long"
    side = "buy" if not is_short else "sell"  # 做多加仓=买入, 做空加仓=卖出

    # Phase D: G-D2 缩减加仓档（未启用时 → eff_max = MAX_ADDONS → 基线）
    eff_max = pos.get("ai_effective_max_addons")
    if eff_max is None:
        eff_max = MAX_ADDONS
    eff_max = int(max(0, min(MAX_ADDONS, eff_max)))

    grid_orders = []
    for i in range(eff_max):
        addon_usd_raw = addon_budgets[i] if i < len(addon_budgets) else 0
        if addon_usd_raw <= 0:
            continue
        # 补乘 timing_mult：capital_manager 给出的 addon*_usd 是基线预算，尚未考虑时机缩放
        addon_usd = addon_usd_raw * timing_mult
        addon_margin = addon_usd * vol_mult
        addon_notional = addon_margin * LEVERAGE
        # 第 i 档触发价格：开仓价下跌 (i+1)*addon_pct（做多）/ 上涨（做空）
        trigger_pct = addon_pct * (i + 1)
        if is_short:
            grid_px = open_price * (1 + trigger_pct)
        else:
            grid_px = open_price * (1 - trigger_pct)
        if grid_px <= 0:
            continue
        sz = calc_lot_sz(addon_notional, grid_px, lot_sz, ct_val)
        if sz < lot_sz:
            _log(f"[{coin}] 加仓网格#{i+1} 数量({sz}张)<最小单位({lot_sz}张), 跳过挂单 (timing_mult={timing_mult:.3f})")
            continue
        r = client.place_order(
            inst_id=inst_id,
            side=side,
            ord_type="limit",
            sz=sz,
            px=grid_px,
            td_mode="isolated",
            pos_side=pos_side,
            tag="v15addongrid",
            reason=f"v15_martin_addon_grid_{i+1}",
        )
        if r.get("ok") or r.get("ord_id"):
            ord_id = r.get("ord_id") or (r.get("raw") or {}).get("data", [{}])[0].get("ordId")
            grid_orders.append(
                {
                    "tier": i + 1,
                    "ord_id": ord_id,
                    "px": grid_px,
                    "sz": sz,
                    "addon_usd": addon_usd,
                    "trigger_pct": trigger_pct,
                    "status": "pending",
                }
            )
            _log(
                f"[{coin}] 加仓网格#{i+1} 挂单成功 {direction} {side} "
                f"sz={sz}张 px=${grid_px:.4f} ({trigger_pct*100:.0f}%档) "
                f"预算=${addon_usd:.2f} ord_id={ord_id}"
            )
        else:
            _log(f"[{coin}] 加仓网格#{i+1} 挂单失败: {r.get('error', r)}")
            grid_orders.append(
                {
                    "tier": i + 1,
                    "ord_id": None,
                    "px": grid_px,
                    "sz": sz,
                    "addon_usd": addon_usd,
                    "trigger_pct": trigger_pct,
                    "status": "failed",
                }
            )

    pos["addon_grid"] = grid_orders


def _check_addon_grid_status(client, coin, pos):
    """轮询时检查加仓网格挂单状态并动态调整

    1. 查询 OKX 未成交订单，对比 pos["addon_grid"] 每档状态
    2. 已成交档位 → 更新持仓（addons++, entry_price, sz），同步 TP/SL
    3. 未成交但价格偏离 → 撤旧单重挂（动态调整）
    4. 返回已成交的档位数（供 execute_addon 判断是否跳过）

    Returns:
        int: 本次轮询新成交的加仓档数
    """
    if not AUTO_EXECUTE:
        return 0

    grid = pos.get("addon_grid")
    if not grid:
        return 0

    inst_id = pos["inst_id"]
    direction = pos.get("direction", "LONG")
    is_short = direction == "SHORT"
    open_price = pos.get("open_price", pos.get("entry_price", 0))
    addon_pct = pos.get("addon_pct", ADDON_PCT)

    # 查询当前未成交订单
    pending_r = client.get_pending_orders(inst_id)
    pending_ord_ids = set()
    if pending_r.get("ok"):
        for o in pending_r.get("orders", []):
            pending_ord_ids.add(o.get("ord_id"))

    new_filled = 0
    for entry in grid:
        tier = entry["tier"]
        ord_id = entry.get("ord_id")
        status = entry.get("status", "pending")

        if status in ("filled", "cancelled", "failed"):
            continue

        # 判断挂单是否已成交：ord_id 不在未成交列表中 = 已成交或已撤销
        if ord_id and ord_id not in pending_ord_ids:
            # 查询订单最终状态
            ord_r = client.get_order(inst_id, ord_id)
            if ord_r.get("ok"):
                state_code = ord_r.get("state", "")
                filled_sz = ord_r.get("filled_sz", 0)
                avg_px = ord_r.get("avg_px", 0)
                if state_code == "filled" and filled_sz > 0:
                    # 已成交 → 更新持仓
                    old_sz = pos["sz"]
                    old_entry = pos["entry_price"]
                    pos["addons"] = pos.get("addons", 0) + 1
                    pos["entry_price"] = (old_entry * old_sz + avg_px * filled_sz) / (
                        old_sz + filled_sz
                    )
                    pos["sz"] += filled_sz
                    pos["last_addon_time"] = datetime.now(timezone.utc).isoformat()
                    entry["status"] = "filled"
                    entry["fill_px"] = avg_px
                    new_filled += 1
                    _log(
                        f"[{coin}] 加仓网格#{tier} 限价单已成交 "
                        f"sz={filled_sz}张 px=${avg_px:.4f} 总仓位={pos['sz']} 均价=${pos['entry_price']:.4f}"
                    )
                    # 同步 TP/SL（均价变化后需更新）
                    tp_pct = pos.get("take_profit_pct", addon_pct)
                    sl_price = pos.get("stop_loss_price", 0)
                    _sync_tp_sl_orders(client, coin, pos, pos["entry_price"], tp_pct, sl_price)
                    continue
                elif state_code in ("canceled", "cancelled"):
                    entry["status"] = "cancelled"
                    _log(f"[{coin}] 加仓网格#{tier} 挂单已撤销(交易所侧), 跳过")
                    continue

        # 未成交的挂单 → 检查是否需要动态调整价格
        # 调整条件：当前价格已越过挂单价格（应该已成交但未成交）或偏离过大
        if status == "pending" and ord_id:
            try:
                params = _get_dynamic_params(client, coin, direction)
                params["current_price"]
                grid_px = entry.get("px", 0)
                trigger_pct = entry.get("trigger_pct", addon_pct * tier)
                # 期望触发价（基于开仓价）
                if is_short:
                    expected_px = open_price * (1 + trigger_pct)
                else:
                    expected_px = open_price * (1 - trigger_pct)
                # 价格偏离超过 2% → 撤旧单重挂
                if grid_px > 0 and abs(grid_px - expected_px) / expected_px > 0.02:
                    cr = client.cancel_order(inst_id, ord_id)
                    if cr.get("ok"):
                        _log(
                            f"[{coin}] 加仓网格#{tier} 价格偏离, 撤单重挂 "
                            f"旧=${grid_px:.4f} 期望=${expected_px:.4f}"
                        )
                        # 重新计算数量并挂单
                        addon_usd = entry.get("addon_usd", 0)
                        vol_mult = pos.get("vol_mult", 1.0)
                        lot_sz, ct_val = get_contract_info(client, inst_id)
                        addon_notional = addon_usd * vol_mult * LEVERAGE
                        new_sz = calc_lot_sz(addon_notional, expected_px, lot_sz, ct_val)
                        if new_sz >= lot_sz:
                            side = "sell" if is_short else "buy"
                            pos_side = "short" if is_short else "long"
                            r = client.place_order(
                                inst_id=inst_id,
                                side=side,
                                ord_type="limit",
                                sz=new_sz,
                                px=expected_px,
                                td_mode="isolated",
                                pos_side=pos_side,
                                tag="v15_addon_grid",
                                reason=f"v15_martin_addon_grid_{tier}_adjust",
                            )
                            if r.get("ok") or r.get("ord_id"):
                                new_ord_id = r.get("ord_id") or r.get("data", {}).get("ordId")
                                entry["ord_id"] = new_ord_id
                                entry["px"] = expected_px
                                entry["sz"] = new_sz
                                _log(
                                    f"[{coin}] 加仓网格#{tier} 重挂成功 "
                                    f"sz={new_sz}张 px=${expected_px:.4f} ord_id={new_ord_id}"
                                )
                            else:
                                entry["status"] = "failed"
                                _log(f"[{coin}] 加仓网格#{tier} 重挂失败: {r.get('error', r)}")
                    else:
                        _log(f"[{coin}] 加仓网格#{tier} 撤单失败: {cr.get('error', cr)}")
            except Exception as e:
                _log(f"[{coin}] 加仓网格#{tier} 状态检查异常: {e}")

    return new_filled


def _cancel_addon_grid_orders(client, coin, pos):
    """平仓时撤销所有未成交的加仓网格限价单"""
    if not AUTO_EXECUTE:
        return
    grid = pos.get("addon_grid")
    if not grid:
        return
    inst_id = pos["inst_id"]
    for entry in grid:
        if entry.get("status") == "pending" and entry.get("ord_id"):
            try:
                cr = client.cancel_order(inst_id, entry["ord_id"])
                if cr.get("ok"):
                    entry["status"] = "cancelled"
                    _log(f"[{coin}] 加仓网格#{entry['tier']} 平仓撤单成功")
                else:
                    _log(f"[{coin}] 加仓网格#{entry['tier']} 平仓撤单失败: {cr.get('error', cr)}")
            except Exception as e:
                _log(f"[{coin}] 加仓网格#{entry['tier']} 平仓撤单异常: {e}")


def _sync_tp_sl_orders(client, coin, pos, entry_price, tp_pct, sl_price):
    """同步设置/更新 OCO 止盈止损条件单

    开仓后立即调用，加仓后再次调用（先取消旧单，再下新单）。
    挂单止盈止损 + 软件监控止盈止损双重保障。

    Args:
        client: OKX 客户端
        coin: 币种
        pos: 持仓信息 dict
        entry_price: 当前均价
        tp_pct: 止盈比例（小数，如 0.04 = 4%）
        sl_price: 止损价格（None 表示不设止损）
    """
    if not AUTO_EXECUTE:
        return

    inst_id = pos["inst_id"]
    direction = pos.get("direction", "LONG")
    is_short = direction == "SHORT"
    pos_side = "short" if is_short else "long"

    try:
        # 止盈价
        if is_short:
            tp_price = entry_price * (1 - tp_pct)
        else:
            tp_price = entry_price * (1 + tp_pct)

        # 先取消旧的条件单，避免多单冲突
        client.cancel_algo_orders(inst_id)

        # 止损价校验：必须与方向一致
        valid_sl = sl_price is not None and sl_price > 0
        if valid_sl:
            if is_short and sl_price <= entry_price:
                valid_sl = False
            elif not is_short and sl_price >= entry_price:
                valid_sl = False

        if valid_sl:
            r = client.place_stop_loss_take_profit(
                inst_id=inst_id,
                pos_side=pos_side,
                stop_loss_px=sl_price,
                take_profit_px=tp_price,
                sz=pos["sz"],
                reason=f"v15_{direction.lower()}_tp_sl_sync",
            )
            if r.get("ok"):
                _log(
                    f"[{coin}] {direction} OCO止盈止损挂单成功 TP=${tp_price:.4f} SL=${sl_price:.4f} sz={pos['sz']}"
                )
            else:
                _log(f"[{coin}] {direction} OCO止盈止损挂单失败: {r.get('error', r)}")
        else:
            # 止损价无效时，只挂止盈单
            r = client.place_stop_loss_take_profit(
                inst_id=inst_id,
                pos_side=pos_side,
                take_profit_px=tp_price,
                sz=pos["sz"],
                reason=f"v15_{direction.lower()}_tp_only",
            )
            if r.get("ok"):
                _log(f"[{coin}] {direction} 仅止盈挂单成功 TP=${tp_price:.4f} sz={pos['sz']}")
            else:
                _log(f"[{coin}] {direction} 仅止盈挂单失败: {r.get('error', r)}")
    except Exception as e:
        _log(f"[{coin}] 止盈止损挂单异常: {e}")


def _update_tp_sl_dynamic(client, coin, pos):
    """每次轮询动态检查并更新止盈止损挂单

    当止盈/止损价格发生显著变化时（如动态止损线移动），
    重新同步挂单，确保挂单与策略计算一致。

    变化阈值：止损价变动 > 0.5% 或止盈价变动 > 0.5% 时才更新，避免频繁撤单。
    """
    if not AUTO_EXECUTE:
        return

    direction = pos.get("direction", "LONG")
    try:
        params = _get_dynamic_params(client, coin, direction)
        current_price = params["current_price"]
        tp_pct = pos.get("take_profit_pct", params["take_profit_pct"])
        sl_price = params["stop_loss_price"]
        if current_price <= 0:
            return

        # BTC风向标智能模式：非BTC加密币种无MA200止损价格，跳过止损更新
        use_btc_windvane = pos.get("use_btc_windvane", False)
        if use_btc_windvane and sl_price is None:
            # 仅检查止盈价是否需要更新
            entry_price = pos["entry_price"]
            last_tp = pos.get("last_tp_price")
            is_short = direction == "SHORT"
            if is_short:
                current_tp = entry_price * (1 - tp_pct)
            else:
                current_tp = entry_price * (1 + tp_pct)
            if last_tp is None or (last_tp > 0 and abs(current_tp - last_tp) / last_tp > 0.005):
                _sync_tp_sl_orders(client, coin, pos, entry_price, tp_pct, None)
                pos["last_tp_price"] = current_tp
            return

        entry_price = pos["entry_price"]
        last_sl = pos.get("last_sl_price")
        last_tp = pos.get("last_tp_price")

        # 计算当前止盈价
        is_short = direction == "SHORT"
        if is_short:
            current_tp = entry_price * (1 - tp_pct)
        else:
            current_tp = entry_price * (1 + tp_pct)

        # 判断是否需要更新
        need_update = False
        if last_sl is None or last_tp is None:
            need_update = True
        else:
            if sl_price and last_sl and last_sl > 0:
                sl_change = abs(sl_price - last_sl) / last_sl
                if sl_change > 0.005:
                    need_update = True
            elif (sl_price is None) != (last_sl is None):
                need_update = True
            if last_tp and last_tp > 0:
                tp_change = abs(current_tp - last_tp) / last_tp
                if tp_change > 0.005:
                    need_update = True

        if need_update:
            _sync_tp_sl_orders(client, coin, pos, entry_price, tp_pct, sl_price)
            pos["last_sl_price"] = sl_price
            pos["last_tp_price"] = current_tp
    except Exception as e:
        _log(f"[{coin}] 动态更新止盈止损异常: {e}")


def check_take_profit(client, coin, pos, state):
    """检查止盈（含移动止盈）和动态止损（支持多空方向）

    做多：价格上涨到止盈线盈利；止损线在价格下方
    做空：价格下跌到止盈线盈利；止损线在价格上方

    止盈优先级：
      1. 移动止盈（启用且激活时）：价格从峰值回撤 N×ATR → 止盈
      2. 固定止盈：profit_pct >= tp_pct（使用 pos 中 RAISE_TP 提高后的值）
    """
    inst_id = pos["inst_id"]
    direction = pos.get("direction", "LONG")
    is_short = direction == "SHORT"
    try:
        params = _get_dynamic_params(client, coin, direction)
        current_price = params["current_price"]
        if current_price <= 0:
            return False

        entry_price = pos["entry_price"]
        if is_short:
            profit_pct = (entry_price - current_price) / entry_price
        else:
            profit_pct = (current_price - entry_price) / entry_price

        # 使用 pos 中保存的 tp_pct（RAISE_TP 提高后的值），回退到动态计算值
        tp_pct = pos.get("take_profit_pct", params["take_profit_pct"])
        sl_price = params["stop_loss_price"]
        sl_type = params["stop_loss_type"]
        sl_triggered = params["stop_loss_triggered"]

        # ── BTC风向标智能模式：加密资产非BTC币种由BTC风向标状态控制止损 ──
        # 非加密资产（如美股）使用旧版MA200止损，不进入此分支
        if coin.upper() != "BTC" and _is_crypto_asset(coin) and sl_type == "BTC_WINDVANE":
            # 获取当前BTC风向标状态
            btc_ctx = _get_direction_ctx("BTC")
            btc_regime = btc_ctx.get("btc_confirmed_regime", "LONG_PREFERRED")
            pos_regime = pos.get("btc_regime_at_open", "LONG_PREFERRED")

            # BTC风向标状态变化导致方向反转 → 触发平仓
            if not is_short and btc_regime == "SHORT_ALLOWED":
                # 持有多仓但BTC风向标转为SHORT_ALLOWED → 平多仓
                _log(
                    f"[{coin}] BTC风向标止损触发: 持有多仓但BTC regime={btc_regime} "
                    f"(开仓时={pos_regime})，平多仓"
                )
                sl_triggered = True
                sl_type = "BTC_WINDVANE_SHORT_ALLOWED"
            elif is_short and btc_regime == "LONG_ONLY_FORCE":
                # 持有空仓但BTC风向标转为LONG_ONLY_FORCE → 平空仓
                _log(
                    f"[{coin}] BTC风向标止损触发: 持有空仓但BTC regime={btc_regime} "
                    f"(开仓时={pos_regime})，平空仓"
                )
                sl_triggered = True
                sl_type = "BTC_WINDVANE_LONG_ONLY_FORCE"
            elif is_short and btc_regime == "LONG_PREFERRED":
                # 持有空仓但BTC风向标回到LONG_PREFERRED → 平空仓
                _log(
                    f"[{coin}] BTC风向标止损触发: 持有空仓但BTC regime={btc_regime} "
                    f"(开仓时={pos_regime})，平空仓"
                )
                sl_triggered = True
                sl_type = "BTC_WINDVANE_BACK_TO_LONG"

        # ── 移动止盈检查（在固定止盈之前）──
        if _TRAILING["enabled"] and profit_pct > 0:
            klines_4h = params.get("klines_4h")
            atr_pct = None
            if klines_4h:
                try:
                    from strategy_params import calc_atr_pct

                    atr_pct = calc_atr_pct(klines_4h)
                except Exception:
                    pass

            if atr_pct and atr_pct > 0:
                atr_price = current_price * (atr_pct / 100)
                start_threshold = tp_pct * _TRAILING["start_ratio"]

                # 更新峰值价格
                if is_short:
                    peak = min(pos.get("peak_price", entry_price), current_price)
                else:
                    peak = max(pos.get("peak_price", entry_price), current_price)
                pos["peak_price"] = peak

                # 计算峰值浮盈
                if is_short:
                    peak_profit_pct = (entry_price - peak) / entry_price
                else:
                    peak_profit_pct = (peak - entry_price) / entry_price

                # 浮盈达到启动阈值 → 激活移动止盈
                if peak_profit_pct >= start_threshold:
                    if is_short:
                        new_trailing = peak + _TRAILING["atr_mult"] * atr_price
                        # 做空：移动止盈价只下移不上移
                        if (
                            pos.get("trailing_price") is None
                            or new_trailing < pos["trailing_price"]
                        ):
                            pos["trailing_price"] = new_trailing
                            _log(
                                f"[{coin}] 移动止盈激活 peak={peak:.4g} trailing={new_trailing:.4g} ATR={atr_pct:.2f}%"
                            )
                    else:
                        new_trailing = peak - _TRAILING["atr_mult"] * atr_price
                        # 做多：移动止盈价只上移不下移
                        if (
                            pos.get("trailing_price") is None
                            or new_trailing > pos["trailing_price"]
                        ):
                            pos["trailing_price"] = new_trailing
                            _log(
                                f"[{coin}] 移动止盈激活 peak={peak:.4g} trailing={new_trailing:.4g} ATR={atr_pct:.2f}%"
                            )
                    pos["trailing_active"] = True

                # 检查移动止盈触发
                trailing_price = pos.get("trailing_price")
                if pos.get("trailing_active") and trailing_price is not None:
                    if (not is_short and current_price <= trailing_price) or (
                        is_short and current_price >= trailing_price
                    ):
                        _log(
                            f"[{coin}] {direction} 移动止盈触发 price=${current_price:.4g} 回撤至 trailing=${trailing_price:.4g} "
                            f"(peak=${peak:.4g}, profit={profit_pct:.2%})"
                        )
                        if AUTO_EXECUTE:
                            _cancel_addon_grid_orders(client, coin, pos)
                            client.cancel_algo_orders(inst_id)
                            lot_sz, ct_val = get_contract_info(client, inst_id)
                            close_sz = math.floor(pos["sz"] / lot_sz) * lot_sz
                            decimals = len(str(lot_sz).split(".")[-1]) if "." in str(lot_sz) else 0
                            close_sz = round(close_sz, decimals)
                            side = "buy" if is_short else "sell"
                            pos_side = "short" if is_short else "long"
                            r = client.place_order(
                                inst_id=inst_id,
                                side=side,
                                sz=close_sz,
                                td_mode="isolated",
                                pos_side=pos_side,
                            )
                            if r.get("ok"):
                                _log(f"[{coin}] 移动止盈平仓成功")
                                state["total_wins"] += 1
                                state["consecutive_losses"] = 0
                                del state["positions"][coin]
                                return True
                            else:
                                _log(f"[{coin}] 移动止盈平仓失败: {r.get('error', r)}")
                        return False

        # ── 固定止盈检查 ──
        if profit_pct >= tp_pct:
            _log(f"[{coin}] {direction} 止盈触发 profit={profit_pct:.2%} >= {tp_pct:.2%}")

            if AUTO_EXECUTE:
                _cancel_addon_grid_orders(client, coin, pos)
                client.cancel_algo_orders(inst_id)
                lot_sz, ct_val = get_contract_info(client, inst_id)
                close_sz = math.floor(pos["sz"] / lot_sz) * lot_sz
                decimals = len(str(lot_sz).split(".")[-1]) if "." in str(lot_sz) else 0
                close_sz = round(close_sz, decimals)
                # 做空平仓: side="buy", pos_side="short"; 做多平仓: side="sell", pos_side="long"
                side = "buy" if is_short else "sell"
                pos_side = "short" if is_short else "long"
                r = client.place_order(
                    inst_id=inst_id,
                    side=side,
                    sz=close_sz,
                    td_mode="isolated",
                    pos_side=pos_side,
                )
                if r.get("ok"):
                    _log(f"[{coin}] 止盈平仓成功")
                    state["total_wins"] += 1
                    state["consecutive_losses"] = 0
                    del state["positions"][coin]
                    return True
                else:
                    _log(f"[{coin}] 止盈平仓失败: {r.get('error', r)}")
            return False

        if sl_triggered:
            if is_short:
                if sl_price is not None:
                    _log(
                        f"[{coin}] {direction} 动态止损触发({sl_type}) 价格=${current_price:.2f} >= 止损线=${sl_price:.2f}"
                    )
                else:
                    _log(
                        f"[{coin}] {direction} 动态止损触发({sl_type}) 价格涨破所有均线，无条件止损"
                    )
            else:
                if sl_price is not None:
                    _log(
                        f"[{coin}] {direction} 动态止损触发({sl_type}) 价格=${current_price:.2f} <= 止损线=${sl_price:.2f}"
                    )
                else:
                    _log(
                        f"[{coin}] {direction} 动态止损触发({sl_type}) 价格跌破所有均线，无条件止损"
                    )

            if AUTO_EXECUTE:
                _cancel_addon_grid_orders(client, coin, pos)
                client.cancel_algo_orders(inst_id)
                lot_sz, ct_val = get_contract_info(client, inst_id)
                close_sz = math.floor(pos["sz"] / lot_sz) * lot_sz
                decimals = len(str(lot_sz).split(".")[-1]) if "." in str(lot_sz) else 0
                close_sz = round(close_sz, decimals)
                side = "buy" if is_short else "sell"
                pos_side = "short" if is_short else "long"
                r = client.place_order(
                    inst_id=inst_id,
                    side=side,
                    sz=close_sz,
                    td_mode="isolated",
                    pos_side=pos_side,
                )
                if r.get("ok"):
                    _log(f"[{coin}] 止损平仓 ({sl_type})")
                    _on_loss_trade(state, coin, reason=f"止损平仓({sl_type})")
                    if coin in state["positions"]:
                        del state["positions"][coin]
                    return True
                else:
                    err_str = str(r.get("error", r)) + str(r.get("raw", ""))
                    _log(f"[{coin}] 止损平仓失败: {r.get('error', r)}")
                    # 交易所已无持仓（sCode 51169）→ 视为已被外部止损平仓，按亏损清理
                    if "51169" in err_str or "don't have any positions" in err_str:
                        _log(f"[{coin}] 检测到交易所无持仓，按外部止损平仓处理")
                        _on_loss_trade(state, coin, reason=f"外部止损平仓({sl_type})")
                        if coin in state["positions"]:
                            del state["positions"][coin]
                        return True
            return False

        return False
    except Exception as e:
        _log(f"[{coin}] 止盈止损检查异常: {e}")
        return False


def check_time_exit(client, coin, pos, state):
    """
    分层超时离场评估（V15 自有逻辑，不依赖经典离场系统）。

    分层计时：
      - 有加仓：从最后一次加仓(last_addon_time)计时，先过黄金窗口再过超时阈值
      - 无加仓：从开仓(open_time)计时，过底仓超时阈值

    超时后 V15 自有决策：
      - 盈利 → 提高止盈价（让利润奔跑，不超过原始止盈2倍）
      - 亏损未触发止损 → 继续持有（马丁策略允许较长持仓+较高波动）
      止损由 check_tp_sl 的动态止损线（日/周MA200）和 OCO 硬单保护
    """
    try:
        direction = pos.get("direction", "LONG")
        is_short = direction == "SHORT"
        params = _get_dynamic_params(client, coin, direction)
        current_price = params["current_price"]
        if current_price <= 0:
            return False

        now_utc = datetime.now(timezone.utc)
        addons = pos.get("addons", 0)

        # ── 分层计时 ──────────────────────────────────────────────
        if addons > 0 and pos.get("last_addon_time"):
            # 有加仓 → 从最后一次加仓计时
            base_time = datetime.fromisoformat(pos["last_addon_time"])
            max_hours = get_config_float("V15_MAX_POST_ADDON_HOURS", 24.0)
            golden_window = get_config_float("V15_GOLDEN_WINDOW_HOURS", 12.0)
        else:
            # 无加仓 → 从开仓计时
            open_time_str = pos.get("open_time")
            if not open_time_str:
                return False
            base_time = datetime.fromisoformat(open_time_str)
            max_hours = get_config_float("V15_MAX_BASE_HOLDING_HOURS", 48.0)
            golden_window = 0.0  # 底仓阶段无黄金窗口

        # Phase B+: 子形态持仓时间微调（±15~20%）
        holding_mult = pos.get("holding_mult", 1.0)
        if holding_mult != 1.0:
            max_hours *= holding_mult
            golden_window *= holding_mult

        if base_time.tzinfo is None:
            base_time = base_time.replace(tzinfo=timezone.utc)

        hold_hours = (now_utc - base_time).total_seconds() / 3600.0

        # 有加仓时：黄金窗口内不触发（让黑天鹅反弹充分发展）
        if golden_window > 0 and hold_hours < golden_window:
            return False

        # 未超时不触发
        if hold_hours < max_hours:
            return False

        # ── V15 自有超时决策（不调用经典离场系统）──
        entry_price = pos["entry_price"]
        if is_short:
            profit_pct = (entry_price - current_price) / entry_price
        else:
            profit_pct = (current_price - entry_price) / entry_price

        _log(
            f"[{coin}] 持仓超时 {hold_hours:.1f}h (阈值={max_hours:.0f}h, 加仓={addons}), "
            f"盈亏={profit_pct:+.2%}"
        )

        if profit_pct > 0:
            # 盈利超时：提高止盈价 50%，让利润奔跑（上限为原始止盈的2倍）
            original_tp = pos.get("take_profit_pct", BASE_TP_PCT)
            new_tp = original_tp * 1.5
            capped_tp = min(new_tp, original_tp * 2.0)
            if capped_tp > original_tp:
                pos["take_profit_pct"] = capped_tp
                sl_price = params.get("stop_loss_price")
                _sync_tp_sl_orders(client, coin, pos, entry_price, capped_tp, sl_price)
                _log(
                    f"[{coin}] 超时盈利, 提高止盈 {original_tp:.2%} → {capped_tp:.2%}, OCO挂单已同步"
                )
            else:
                _log(f"[{coin}] 超时盈利, 止盈已达上限 {original_tp:.2%}, 继续持有")
        else:
            # 亏损超时：未触发止损线则继续持有（马丁策略允许较长持仓等反弹）
            sl_price = params.get("stop_loss_price")
            sl_triggered = params.get("stop_loss_triggered", False)
            if sl_triggered:
                _log(f"[{coin}] 超时且已触发止损条件, 将由 check_tp_sl 处理平仓")
            else:
                _log(f"[{coin}] 超时亏损 {profit_pct:.2%}, 未触发止损线, 继续持有等反弹")

        return False

    except Exception as e:
        _log(f"[{coin}] 超时离场检查异常: {e}")
        return False


def _execute_close_position(client, coin, pos, state, reason="", exit_price=None):
    """平仓（支持多空方向）- 平仓前取消所有条件单 + 按实际PnL判定胜负"""
    inst_id = pos["inst_id"]
    direction = pos.get("direction", "LONG")
    is_short = direction == "SHORT"
    try:
        entry_price = pos.get("entry_price", 0)
        final_exit_price = exit_price or pos.get("current_price", entry_price)

        # 计算盈亏百分比
        if entry_price > 0 and final_exit_price > 0:
            if is_short:
                profit_pct = (entry_price - final_exit_price) / entry_price
            else:
                profit_pct = (final_exit_price - entry_price) / entry_price
        else:
            profit_pct = pos.get("unrealized_pnl", 0) / max(1.0, pos.get("per_coin_budget", 1.0))

        if AUTO_EXECUTE:
            _cancel_addon_grid_orders(client, coin, pos)
            client.cancel_algo_orders(inst_id)

        lot_sz, ct_val = get_contract_info(client, inst_id)
        close_sz = math.floor(pos["sz"] / lot_sz) * lot_sz
        decimals = len(str(lot_sz).split(".")[-1]) if "." in str(lot_sz) else 0
        close_sz = round(close_sz, decimals)

        if AUTO_EXECUTE:
            # 做空平仓: side="buy", pos_side="short"; 做多平仓: side="sell", pos_side="long"
            side = "buy" if is_short else "sell"
            pos_side = "short" if is_short else "long"
            r = client.place_order(
                inst_id=inst_id,
                side=side,
                sz=close_sz,
                td_mode="isolated",
                pos_side=pos_side,
            )
            if r.get("ok"):
                is_profit = profit_pct >= 0
                pnl_label = f"盈利 {profit_pct:+.2%}" if is_profit else f"亏损 {profit_pct:+.2%}"
                _log(f"[{coin}] {direction} 平仓成功 ({reason}) | {pnl_label}")

                # 按实际盈亏判定胜场或败场
                if is_profit:
                    _on_win_trade(state, coin, reason=f"平仓({reason}) {pnl_label}")
                else:
                    _on_loss_trade(state, coin, reason=f"平仓({reason}) {pnl_label}")

                if coin in state["positions"]:
                    # 注册到 L4
                    _register_martin_trade_to_l4(
                        coin=coin,
                        pos=pos,
                        exit_price=final_exit_price,
                        exit_reason=reason,
                    )
                    del state["positions"][coin]
                return True
            else:
                _log(f"[{coin}] 平仓失败: {r.get('error', r)}")
                return False
        return False
    except Exception as e:
        _log(f"[{coin}] 平仓异常: {e}")
        return False


def _execute_reduce_position(client, coin, pos, state, reduce_frac):
    """减仓（供 check_time_exit 调用，支持多空方向）"""
    inst_id = pos["inst_id"]
    direction = pos.get("direction", "LONG")
    is_short = direction == "SHORT"
    try:
        lot_sz, ct_val = get_contract_info(client, inst_id)
        reduce_sz = math.floor((pos["sz"] * reduce_frac) / lot_sz) * lot_sz
        decimals = len(str(lot_sz).split(".")[-1]) if "." in str(lot_sz) else 0
        reduce_sz = round(reduce_sz, decimals)

        if reduce_sz < lot_sz:
            _log(f"[{coin}] 减仓数量({reduce_sz})小于最小单位({lot_sz}), 跳过")
            return False

        if AUTO_EXECUTE:
            # 做空减仓: side="buy", pos_side="short"; 做多减仓: side="sell", pos_side="long"
            side = "buy" if is_short else "sell"
            pos_side = "short" if is_short else "long"
            r = client.place_order(
                inst_id=inst_id,
                side=side,
                sz=reduce_sz,
                td_mode="isolated",
                pos_side=pos_side,
            )
            if r.get("ok"):
                pos["sz"] -= reduce_sz
                _log(
                    f"[{coin}] {direction} 减仓成功 frac={reduce_frac:.0%} sz={reduce_sz} 剩余={pos['sz']}"
                )
                return True
            else:
                _log(f"[{coin}] 减仓失败: {r.get('error', r)}")
                return False
        return False
    except Exception as e:
        _log(f"[{coin}] 减仓异常: {e}")
        return False


ADDON_PCT_CHECK = ADDON_PCT  # 向后兼容别名

MAX_CONSECUTIVE_LOSSES_REBUILD = get_config_int("V15_MAX_CONSECUTIVE_LOSSES", 3)
_capital_rebuild_running = False


def trigger_capital_rebuild(state, reason=""):
    """异步触发资金管理引擎月度优化（不阻塞主循环）"""
    global _capital_rebuild_running
    if _capital_rebuild_running:
        _log("[资金管理] 优化已在运行中，跳过")
        return

    def _run():
        global _capital_rebuild_running
        try:
            _capital_rebuild_running = True
            _log(f"[资金管理] 触发资金优化，原因: {reason}")
            script = BASE_DIR / "run.py"
            cmd = [sys.executable, str(script), "capital_engine", "monthly"]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(BASE_DIR),
                timeout=7200,
            )
            if result.returncode == 0:
                _log("[资金管理] 优化完成")
                state["last_capital_rebuild"] = datetime.now(timezone.utc).isoformat()
                state["consecutive_losses"] = 0
                save_state(state)
            else:
                _log(f"[资金管理] 优化失败: {result.stderr[-500:]}")
        except subprocess.TimeoutExpired:
            _log("[资金管理] 优化超时（>2小时）")
        except Exception as e:
            _log(f"[资金管理] 优化异常: {e}")
        finally:
            _capital_rebuild_running = False

    threading.Thread(target=_run, daemon=True).start()


def check_monthly_rebuild(state):
    """检查是否需要运行月度资金优化（每月1号运行一次）"""
    now = datetime.now(timezone.utc)
    last_rebuild = state.get("last_capital_rebuild", "")

    if now.day != 1:
        return False

    if last_rebuild:
        try:
            last_dt = datetime.fromisoformat(last_rebuild.replace("Z", "+00:00"))
            if last_dt.year == now.year and last_dt.month == now.month:
                return False
        except Exception:  # noqa: E722 - 允许宽捕获以兼容外部异常
            pass

    return True


_lot_size_cache = {}
_ct_val_cache = {}


def get_contract_info(client, inst_id):
    """获取合约信息（lotSz, ctVal）带缓存"""
    if inst_id in _lot_size_cache and inst_id in _ct_val_cache:
        return _lot_size_cache[inst_id], _ct_val_cache[inst_id]
    try:
        r = client._get(
            "/api/v5/public/instruments", {"instId": inst_id, "instType": "SWAP"}, auth=False
        )
        if r.get("code") == "0" and r.get("data"):
            lot_sz = float(r["data"][0].get("lotSz", 1))
            ct_val = float(r["data"][0].get("ctVal", 1))
            _lot_size_cache[inst_id] = lot_sz
            _ct_val_cache[inst_id] = ct_val
            return lot_sz, ct_val
    except Exception:
        pass
    _lot_size_cache[inst_id] = 0.01
    _ct_val_cache[inst_id] = 1.0
    return 0.01, 1.0


def calc_lot_sz(notional_usd, price, lot_sz, ct_val):
    """根据名义价值计算张数（OKX合约sz是张数，不是币数）"""
    if ct_val <= 0 or price <= 0:
        return 0
    sz_raw = notional_usd / (ct_val * price)
    sz_adj = math.floor(sz_raw / lot_sz) * lot_sz
    if sz_adj < lot_sz:
        return 0
    decimals = len(str(lot_sz).split(".")[-1]) if "." in str(lot_sz) else 0
    return round(sz_adj, decimals)


def run_light_poll_cycle():
    """轻量轮询：只同步持仓状态+盈亏，不做交易决策

    用途：
    - 每5分钟执行一次，同步交易所真实持仓到state
    - 检测外部平仓（手动操作等）
    - 更新持仓盈亏信息（current_price, unrealized_pnl, profit_pct）
    - 为1小时完整轮询提供准确的持仓状态，避免策略基于过期持仓做决策

    与完整轮询的区别：
    - 不做信号计算（不调用 get_v15_decision）
    - 不执行交易（不开仓、不加仓、不平仓）
    - 不挂OCO条件单
    - 只查仓+对比+更新state

    防误删保护：
    - API 调用失败（限流/网络）时，保留 state 中的持仓记录，不视为"外部平仓"
    - 只有 API 明确返回成功且持仓数为 0 时，才判定为外部平仓
    """
    state = load_state()
    client = _get_okx_client()

    if not client:
        _log("[轻量轮询] OKX客户端不可用, 跳过")
        return

    _log("=== 轻量轮询开始 ===")

    # 单次 API 拉取账户所有持仓（避免 30 次循环触发 OKX 限流）
    all_resp = client.get_all_positions()
    api_ok = all_resp.get("ok", False)
    exchange_positions = all_resp.get("positions", {}) if api_ok else {}

    if not api_ok:
        # API 失败 — 保留 state 原状，只更新 last_poll
        _log(
            f"[轻量轮询] ⚠️ 持仓查询失败: {all_resp.get('error', 'unknown')} — 保留 state 原状，不删除任何持仓"
        )
        state["last_poll"] = datetime.now(timezone.utc).isoformat()
        save_state(state)
        remaining = list(state.get("positions", {}).keys())
        _log(f"=== 轻量轮询完成(降级) | 持仓:{len(remaining)} (state 未变更) ===")
        for coin in remaining:
            pos = state["positions"][coin]
            pnl = pos.get("unrealized_pnl", 0)
            pnl_pct = pos.get("profit_pct", 0)
            _log(
                f"  [{coin}] mark=${pos.get('current_price', 0):.4f} pnl=${pnl:.2f} ({pnl_pct:+.2%}) [stale]"
            )
        return

    state_positions = set(state.get("positions", {}).keys())
    exchange_pos_keys = set(exchange_positions.keys())

    # 1. state中有但交易所没有 → 外部平仓（手动操作、强平、OCO自动止盈止损等）
    externally_closed = state_positions - exchange_pos_keys
    for coin in externally_closed:
        pos = state["positions"][coin]
        direction = pos.get("direction", "LONG")
        is_short = direction == "SHORT"
        entry_price = pos.get("entry_price", 0)
        current_price = pos.get("current_price", entry_price)

        # 估算盈亏百分比
        if entry_price > 0 and current_price > 0:
            if is_short:
                profit_pct = (entry_price - current_price) / entry_price
            else:
                profit_pct = (current_price - entry_price) / entry_price
        else:
            profit_pct = 0.0

        is_profit = profit_pct >= 0
        pnl_label = f"盈利 {profit_pct:+.2%}" if is_profit else f"亏损 {profit_pct:+.2%}"
        _log(f"[{coin}] ⚠️ 检测到外部平仓: entry={entry_price:.4f} sz={pos['sz']} | {pnl_label}")

        # 按实际盈亏更新统计
        if is_profit:
            _on_win_trade(state, coin, reason=f"外部平仓(external_close) {pnl_label}")
        else:
            _on_loss_trade(state, coin, reason=f"外部平仓(external_close) {pnl_label}")

        # 注册外部平仓到 L4
        _register_martin_trade_to_l4(
            coin=coin,
            pos=pos,
            exit_price=current_price,
            exit_reason="external_close",
        )
        if coin in state["positions"]:
            del state["positions"][coin]

    # 2. 交易所中有但state中没有 → 外部开仓（策略不负责，仅记录）
    externally_opened = exchange_pos_keys - state_positions
    for coin in externally_opened:
        p = exchange_positions[coin]
        _log(
            f"[{coin}] ⚠️ 检测到外部开仓: avg_px={p['avg_px']:.4f} pos={p['pos']} upl={p['upl']:.2f}"
        )

    # 3. 两边都有 → 更新盈亏信息
    for coin in state_positions & exchange_pos_keys:
        p = exchange_positions[coin]
        pos = state["positions"][coin]
        pos["current_price"] = p.get("mark_px", 0)
        pos["unrealized_pnl"] = p.get("upl", 0)
        pos["upl_ratio"] = p.get("upl_ratio", 0)

        # 计算盈亏百分比
        entry = pos.get("entry_price", 0)
        mark = p.get("mark_px", 0)
        if entry > 0 and mark > 0:
            direction = pos.get("direction", "LONG")
            if direction == "SHORT":
                profit_pct = (entry - mark) / entry
            else:
                profit_pct = (mark - entry) / entry
            pos["profit_pct"] = profit_pct

    state["last_poll"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    # 输出监控摘要
    remaining = list(state.get("positions", {}).keys())
    _log(
        f"=== 轻量轮询完成 | 持仓:{len(remaining)} 外部平仓:{len(externally_closed)} 外部开仓:{len(externally_opened)} ==="
    )
    if remaining:
        for coin in remaining:
            pos = state["positions"][coin]
            pnl = pos.get("unrealized_pnl", 0)
            pnl_pct = pos.get("profit_pct", 0)
            _log(
                f"  [{coin}] mark=${pos.get('current_price', 0):.4f} pnl=${pnl:.2f} ({pnl_pct:+.2%})"
            )


def run_poll_cycle():
    """执行一次完整轮询（信号计算+交易执行）"""
    state = load_state()
    client = _get_okx_client()

    if not client:
        _log("OKX客户端不可用, 跳过本轮")
        save_state(state)
        return

    # ── 冷却状态检查（每轮必检）──
    exit_cooldown_if_expired(state)
    in_cd, remain_hours, cd_reason = is_in_cooldown(state)
    if in_cd:
        _log(
            f"[风控-冷却] 交易暂停中，剩余 {remain_hours:.1f}h "
            f"(原因: {cd_reason})，跳过开仓，仅监控现有持仓"
        )

    if check_monthly_rebuild(state):
        trigger_capital_rebuild(state, reason="月度定时优化（每月1号）")

    _log(f"=== 开始轮询 ({len(COINS)}币种) ===")

    # 异常信号监控（影子模式：只输出不决策）
    if BOUNCE_MONITOR_ENABLED:
        _log("--- 反弹潜力监控（影子模式）---")
        try:
            signal_result = monitor_bounce_signals(COINS, lookback=60, min_signals=1)
            if signal_result["highlighted_count"] > 0:
                for r in signal_result["highlighted"]:
                    triggers = ", ".join(r["triggered_list"])
                    _log(f"[{r['coin']}] 信号触发({triggers}): n_triggered={r['n_triggered']}")
                highlighted_coins = ", ".join([r["coin"] for r in signal_result["highlighted"]])
                _log(f"潜在高价值币种({signal_result['highlighted_count']}个): {highlighted_coins}")
            else:
                _log("无信号触发币种")
        except Exception as e:
            _log(f"信号监控异常: {e}")
        _log("--- 监控结束 ---")

    for coin in COINS:
        try:
            if coin in state["positions"]:
                pos = state["positions"][coin]

                # 兼容旧持仓：补充移动止盈状态字段
                if "trailing_active" not in pos:
                    pos["trailing_active"] = False
                    pos["trailing_price"] = None
                    pos["peak_price"] = pos.get("entry_price", 0)

                if not check_take_profit(client, coin, pos, state):
                    if not check_time_exit(client, coin, pos, state):
                        # 先检查加仓网格挂单状态（已成交则更新持仓）
                        _check_addon_grid_status(client, coin, pos)
                        # execute_addon 作为兜底：网格未覆盖或挂单失败时市价加仓
                        added = execute_addon(client, coin, pos, state)
                        if not added:
                            _update_tp_sl_dynamic(client, coin, pos)
            else:
                decision = get_v15_decision(coin)
                action = decision.get("action", "WAIT")
                conf = decision.get("confidence", 0)

                # 支持多空开仓信号：OPEN_BULL（做多）和 OPEN_BEAR（做空）
                if action in ("OPEN_BULL", "OPEN_BEAR") and conf >= 60:
                    _log(f"[{coin}] 信号触发: {action} conf={conf}%")

                    # 门禁0: 形态切换冷却期禁止开新仓（Phase A+）
                    dir_ctx = decision.get("direction_ctx") or {}
                    if dir_ctx.get("regime_in_cooldown"):
                        # 死锁修复(2026-08-09): 冷却期只应阻止与形态切换方向一致的开仓
                        # 当V15_ALLOW_SHORT=false且形态切到SHORT_ALLOWED时，
                        # 做多开仓不应被阻止（因为系统本来就不做空，做多是逆势抄底）
                        regime = dir_ctx.get("regime", "")
                        is_short_signal = action == "OPEN_BEAR"
                        allow_short = V15_ALLOW_SHORT

                        # 场景1: 做空信号 + 冷却期 → 允许（因为做空被禁用，此分支不会执行到）
                        # 场景2: 做多信号 + 冷却期 + V15_ALLOW_SHORT=false + 形态SHORT_ALLOWED
                        #   → 放行：做多是逆势抄底，不受形态切换影响
                        if is_short_signal and not allow_short:
                            # 做空信号但做空被禁用，跳过
                            _log(f"[{coin}] 做空信号但V15_ALLOW_SHORT=false，跳过")
                            continue

                        # 冷却期只在以下场景阻止开仓：
                        # 1. 做多信号 + 形态刚从LONG切到其他 → 不做逆势
                        # 2. 做空信号（已在上面处理）
                        # 如果形态是SHORT_ALLOWED但做空被禁用，做多信号放行
                        if regime == "short_allowed" and not allow_short and not is_short_signal:
                            _log(
                                f"[{coin}] 形态SHORT_ALLOWED但V15_ALLOW_SHORT=false，放行做多（逆势抄底）"
                            )
                            # 放行，继续后续检查
                        elif dir_ctx.get("regime_in_cooldown"):
                            _log(f"[{coin}] 形态切换冷却期，暂停开新仓")
                            continue

                    # 门禁1: 冷却期禁止开新仓
                    if in_cd:
                        _log(f"[{coin}] 冷却期禁止开仓，" f"剩余 {remain_hours:.1f}h，跳过")
                    else:
                        # 门禁2: 单次轮询/全局最多3仓（MAX_CONCURRENT_POSITIONS）
                        pos_count = len(state.get("positions", {}))
                        if pos_count >= MAX_CONCURRENT_POSITIONS:
                            _log(
                                f"[风控-门禁][{coin}] 持仓数上限 ({pos_count}/"
                                f"{MAX_CONCURRENT_POSITIONS})，禁止开新仓"
                            )
                            _feishu_alert_v15(
                                "trading",
                                "warning",
                                f"⚠️ 持仓数达到上限 {pos_count}/{MAX_CONCURRENT_POSITIONS}，"
                                f"拒绝 {coin} 开新仓",
                                {
                                    "持仓上限": MAX_CONCURRENT_POSITIONS,
                                    "当前持仓数": pos_count,
                                    "币种池": list(state["positions"].keys()),
                                },
                            )
                        else:
                            execute_open_position(client, coin, decision, state)
                else:
                    _log(f"[{coin}] 等待: {action} conf={conf}%")

            save_state(state)

        except Exception as e:
            _log(f"[{coin}] 轮询异常: {e}")

    win_rate = (
        (state["total_wins"] / state["total_trades"] * 100) if state["total_trades"] > 0 else 0
    )
    _log(
        f"=== 轮询完成 | 持仓:{len(state['positions'])} 总交易:{state['total_trades']} 胜率:{win_rate:.1f}% ==="
    )
    save_state(state)


def main():
    _log("V15 经典马丁策略自动交易器启动")
    _log(f"  币种: {COINS}")
    _log(f"  轮询间隔: {POLL_INTERVAL}s")
    _log(f"  自动执行: {AUTO_EXECUTE}")
    _log(f"  最大加仓: {MAX_ADDONS}次")
    _log(f"  止盈: {BASE_TP_PCT:.0%}")
    _log(f"  允许做空: {V15_ALLOW_SHORT}")
    # ── 实盘风控配置（2026-07-31）──
    consec_threshold = get_config_int("V15_MAX_CONSECUTIVE_LOSSES", 6)
    cooldown_h = get_config_int("V15_COOLDOWN_HOURS", 48)
    gate_enabled = get_config_bool("V15_RISK_GATE_ENABLED", True)
    max_pos = get_config_int("MAX_CONCURRENT_POSITIONS", 3)
    _log(
        f"  实盘风控: 连亏≥{consec_threshold}笔 → {cooldown_h}h冷却 | "
        f"最大持仓 {max_pos} 笔 | 门禁: {'开启' if gate_enabled else '影子模式'} "
        f"| 飞书告警: {'开启' if V15_FEISHU_ALERT_ENABLED else '关闭'}"
    )
    # 启动飞书通知
    details = {
        "币种池": f"{len(COINS)}个",
        "轮询间隔": f"{POLL_INTERVAL}s",
        "最大持仓": f"{max_pos}笔",
        "连亏阈值": f"{consec_threshold}笔",
        "冷却时长": f"{cooldown_h}h",
        "自动执行": AUTO_EXECUTE,
        "门禁模式": "实盘阻断" if gate_enabled else "影子模式",
        "允许做空": V15_ALLOW_SHORT,
    }
    alert = _get_feishu_alert()
    if alert is not None:
        try:
            alert.notify_system_start(V15_SYSTEM_NAME, details)
        except Exception as e:
            _log(f"[飞书告警] 启动通知失败: {e}")
    _feishu_alert_v15("system", "info", "🚀 V15马丁策略交易器已启动", details)

    def handle_signal(signum, frame):
        _log("收到退出信号, 保存状态...")
        state = load_state()
        save_state(state)
        sys.exit(0)

    sig_module.signal(sig_module.SIGINT, handle_signal)
    sig_module.signal(sig_module.SIGTERM, handle_signal)

    while True:
        try:
            run_poll_cycle()
        except Exception as e:
            _log(f"轮询周期异常: {e}")

        _log(f"等待 {POLL_INTERVAL}s 后下一轮...")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
