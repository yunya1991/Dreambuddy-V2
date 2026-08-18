#!/usr/bin/env python3
"""
三屏马丁交易执行引擎 v2
- LLM 决策：DeepSeek API，配额用尽自动回退 V9/AI-V15 基线
- 三级回退：DeepSeek LLM → AI-V15 多因子评分 → V9 基线策略
- 自主编排：事件驱动 + 4h 心跳 + 波动触发
- 策略：V9马丁基线（可动态调整 vol_mult）
"""
import json, os, subprocess, math, re, time, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import numpy as np
except ImportError:
    np = None

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / "config" / ".env")
except Exception:
    pass

BASE_DIR = Path(__file__).parent
STATE_FILE = BASE_DIR / "data" / "screen_trade_state.json"
QUOTA_FILE = BASE_DIR / "data" / "screen_llm_quota.json"
LOG_DIR = BASE_DIR / "logs" / "screen_trade"
LOG_DIR.mkdir(parents=True, exist_ok=True)

HOME_BIN = "/opt/homebrew/bin"
os.environ["PATH"] = HOME_BIN + ":" + os.environ.get("PATH", "")

OKX_PROFILE = os.environ.get("SCREEN_OKX_PROFILE", "screen_trade")
INST_SWAP = "BTC-USDT-SWAP"

MAX_ADDONS = 1
BASE_ADDON_PCT = 0.08
BASE_TP_PCT = 0.04
BASE_VOL_MULT = 1.0
V15_VOL_MULT = 1.875

MAX_POSITION_PCT = 0.25

POSITION_MIN_BUDGET_PCT = 0.05
POSITION_MAX_BUDGET_PCT = 0.60
COUNTER_TREND_ADDON_BUDGET_PCT = 0.40
TOTAL_POSITION_BUDGET_CAP = 0.80

CONFIDENCE_JUMP_THRESHOLD = 15

OPEN_CONFIDENCE_THRESHOLD = 60
TRIAL_CONFIDENCE_THRESHOLD = 45
STOP_LOSS_PCT = 0.10

_POSITION_TIERS = [
    (85, 0.60),
    (75, 0.45),
    (65, 0.30),
    (55, 0.15),
    (45, 0.05),
    (0, 0.02),   # 低于45%也有最小仓位（2%），低置信度低仓位
]


def calc_entry_budget_pct(confidence: float) -> float:
    for threshold, budget_pct in _POSITION_TIERS:
        if confidence >= threshold:
            return budget_pct
    return _POSITION_TIERS[-1][1]


def calc_actual_position_pct(budget_pct: float) -> float:
    return round(budget_pct * MAX_POSITION_PCT, 4)


def calc_target_total_budget_pct(
    entry_confidence: float,
    current_confidence: float,
    has_counter_trend: bool = False,
) -> float:
    entry_pct = calc_entry_budget_pct(entry_confidence)
    counter_pct = COUNTER_TREND_ADDON_BUDGET_PCT if has_counter_trend else 0.0
    jump = current_confidence - entry_confidence
    trend_pct = 0.0
    if jump >= CONFIDENCE_JUMP_THRESHOLD:
        new_entry_pct = calc_entry_budget_pct(current_confidence)
        trend_pct = max(0.0, new_entry_pct - entry_pct)
    total = entry_pct + counter_pct + trend_pct
    return min(total, TOTAL_POSITION_BUDGET_CAP)

SKIP_THRESHOLD_FOR_SIMPLE_MODE = 5
LOSS_THRESHOLD_FOR_SIMPLE_MODE = 3

AUTO_EXECUTE = os.environ.get("SCREEN_AUTO_EXECUTE", "true").lower() == "true"

MIN_MARGIN_USD = float(os.environ.get("MIN_MARGIN_USD", 20))
DEFAULT_LEVERAGE = float(os.environ.get("DEFAULT_LEVERAGE", 10))

# ── 交易所切换：ASTER 模式（趋势策略专用钱包） ────────────────────────────
# EXCHANGE_MODE=aster   → 使用 AsterExecutor（趋势策略独立钱包 0x6632...A）
# EXCHANGE_MODE=okx     → 使用 OKX（历史路径，已禁用，仅保留查询能力）
EXCHANGE_MODE = os.environ.get("EXCHANGE_MODE", "aster").lower()
ASTER_TREND_SYSTEM = "/home/ubuntu/Dreambuddy-V2-main/12-三屏趋势系统"
if ASTER_TREND_SYSTEM not in sys.path:
    sys.path.insert(0, ASTER_TREND_SYSTEM)

_aster_executor_instance = None


def _get_aster_executor():
    """获取 AsterExecutor 单例（趋势策略专用）"""
    global _aster_executor_instance
    if _aster_executor_instance is None:
        try:
            from live.aster_executor import AsterExecutor
            _aster_executor_instance = AsterExecutor()
            _log("INFO", f"[Aster] 执行器已加载 owner={_aster_executor_instance.config.owner[:14]}... "
                          f"dry_run={_aster_executor_instance.config.dry_run}")
        except Exception as e:
            _log("ERROR", f"[Aster] 执行器加载失败: {e}")
            return None
    return _aster_executor_instance


def _parse_coin_from_inst(inst_id: str) -> str:
    """从 inst_id（如 BTC-USDT-SWAP）解析出币种符号（BTC）"""
    if not inst_id:
        return ""
    return inst_id.split("-")[0].upper()

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
LLM_DAILY_LIMIT = int(os.environ.get("SCREEN_LLM_DAILY_LIMIT", "12"))

STRATEGY_MODE = os.environ.get("SCREEN_STRATEGY_MODE", "auto")  # auto/v9/ai_v15


def _run_okx(args):
    try:
        r = subprocess.run(
            ["okx", "--profile", OKX_PROFILE] + args,
            capture_output=True, text=True, timeout=15,
            env={**os.environ, "NO_UPDATE_CHECK": "1"}
        )
        stdout = "\n".join(l for l in r.stdout.split("\n") if "Update available" not in l and "Run: npm" not in l).strip()
        stderr = "\n".join(l for l in r.stderr.split("\n") if "Update available" not in l and "Run: npm" not in l).strip()
        if r.returncode != 0 and stderr:
            return {"ok": False, "err": stderr[:300]}
        if stdout.startswith("[") or stdout.startswith("{"):
            return {"ok": True, "data": json.loads(stdout)}
        return {"ok": True, "data": stdout}
    except Exception as e:
        return {"ok": False, "err": str(e)}


def _log(level: str, msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] [{level}] {msg}"
    print(line, flush=True)
    log_file = LOG_DIR / f"screen_trade_{datetime.now(timezone.utc).strftime('%Y%m%d')}.log"
    with open(log_file, "a") as f:
        f.write(line + "\n")


# ── LLM 配额管理 ──────────────────────────────────────────────────────────

def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load_quota() -> dict:
    if QUOTA_FILE.exists():
        try:
            with open(QUOTA_FILE) as f:
                d = json.load(f)
            if d.get("date") == _today():
                return d
        except Exception:
            pass
    return {
        "date": _today(),
        "deepseek": 0,
        "ai_v15_fallback": 0,
        "v9_fallback": 0,
    }


def _save_quota(q: dict):
    QUOTA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(QUOTA_FILE, "w") as f:
        json.dump(q, f, indent=2, ensure_ascii=False)


def _record_usage(mode: str):
    q = _load_quota()
    q[mode] = q.get(mode, 0) + 1
    _save_quota(q)


def get_quota_status() -> dict:
    q = _load_quota()
    return {
        "date": q["date"],
        "deepseek": f"{q.get('deepseek', 0)}/{LLM_DAILY_LIMIT}",
        "ai_v15_fallback": q.get("ai_v15_fallback", 0),
        "v9_fallback": q.get("v9_fallback", 0),
    }


# ── 状态管理 ──────────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                state = json.load(f)
            if "open_price" not in state:
                state["open_price"] = state.get("avg_entry", 0)
            return state
        except Exception:
            pass
    return {
        "active": False,
        "direction": None,
        "entry_levels": [],
        "current_level": 0,
        "total_size": 0,
        "avg_entry": 0,
        "open_price": 0,
        "tp_price": 0,
        "last_check_ts": 0,
        "last_action_ts": 0,
        "last_action": "",
        "last_reason": "",
        "last_mode": "v9",
        "run_count": 0,
        "trade_history": [],
        "vol_mult": BASE_VOL_MULT,
        "addon_pct": BASE_ADDON_PCT * 100,
        "tp_pct": BASE_TP_PCT * 100,
        "weekly_ref_loaded": None,
        "daily_ref_loaded": None,
        "intel_ref_loaded": None,
    }


def _convert_numpy_types(obj):
    if isinstance(obj, dict):
        return {k: _convert_numpy_types(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_convert_numpy_types(item) for item in obj]
    elif np is not None and isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)
    elif np is not None and isinstance(obj, (np.floating, np.float64, np.float32)):
        return float(obj)
    else:
        return obj


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        state_clean = _convert_numpy_types(state)
        with open(STATE_FILE, "w") as f:
            json.dump(state_clean, f, indent=2, ensure_ascii=False)
    except Exception as e:
        _log("ERROR", f"状态保存失败: {e}")
        with open(STATE_FILE, "w") as f:
            json.dump({"error": f"save failed: {e}"}, f, indent=2)


# ── 市场数据 ──────────────────────────────────────────────────────────────

def get_account_info() -> dict:
    r = _run_okx(["account", "balance", "--json"])
    if not r["ok"]:
        return {"equity": 0, "available": 0, "error": r["err"]}
    data = r["data"]
    equity = 0
    available = 0
    if isinstance(data, list):
        for item in data:
            for d in item.get("details", []):
                if d.get("ccy") == "USDT":
                    equity = float(d.get("eq", 0))
                    available = float(d.get("availBal", 0))
    return {"equity": equity, "available": available}


def get_position(inst_id: str = INST_SWAP) -> Optional[dict]:
    r = _run_okx(["swap", "positions", inst_id, "--json"])
    if not r["ok"]:
        return None
    data = r["data"]
    if not isinstance(data, list):
        return None
    for p in data:
        pos = float(p.get("pos", 0))
        if pos != 0:
            pos_side = p.get("posSide", "net")
            return {
                "instId": p.get("instId"),
                "side": "LONG" if pos_side == "long" else "SHORT" if pos_side == "short" else ("LONG" if pos > 0 else "SHORT"),
                "pos_side": pos_side,
                "size": abs(pos),
                "entry_px": float(p.get("avgPx", 0)),
                "upnl": float(p.get("upl", 0)),
                "leverage": float(p.get("lever", 1)),
                "mgnMode": p.get("mgnMode", ""),
            }
    return None


def get_price(inst_id: str = INST_SWAP) -> float:
    r = _run_okx(["market", "ticker", inst_id, "--json"])
    if not r["ok"] or not isinstance(r["data"], list) or not r["data"]:
        return 0
    return float(r["data"][0].get("last", 0))


# ── 价位计算 ──────────────────────────────────────────────────────────────

def _calc_levels(direction: str, current_price: float, vol_mult: float) -> Tuple[list, float, float, float]:
    addon_pct = BASE_ADDON_PCT * vol_mult
    tp_pct = BASE_TP_PCT * vol_mult

    levels = []
    if direction == "BULL":
        tp_price = current_price * (1 + tp_pct)
        levels.append({"level": 0, "label": "入场", "price": round(current_price, 2), "status": "待触发"})
        for i in range(1, MAX_ADDONS + 1):
            px = current_price * (1 - addon_pct * i)
            levels.append({"level": i, "label": f"加仓{i}", "price": round(px, 2), "status": "未到达"})
    else:
        tp_price = current_price * (1 - tp_pct)
        levels.append({"level": 0, "label": "入场", "price": round(current_price, 2), "status": "待触发"})
        for i in range(1, MAX_ADDONS + 1):
            px = current_price * (1 + addon_pct * i)
            levels.append({"level": i, "label": f"加仓{i}", "price": round(px, 2), "status": "未到达"})

    return levels, round(tp_price, 2), addon_pct, tp_pct


def _adjust_vol_mult_from_reports(base_vol: float, weekly: dict, a1_daily: dict, a6_intel: dict, mode: str = "v9") -> float:
    base = base_vol

    if weekly and weekly.get("score"):
        score = weekly["score"]
        if score >= 70:
            base *= 1.3
        elif score < 40:
            base *= 0.7

    if a1_daily:
        si = a1_daily.get("si_index", {}).get("score", 50)
        if si >= 60:
            base *= 1.2
        elif si < 30:
            base *= 0.8

        ap = a1_daily.get("action_pressure", {})
        if ap.get("level") == "HIGH":
            base *= 0.9

    if a6_intel:
        p0 = a6_intel.get("p0_alerts", 0)
        p1 = a6_intel.get("p1_alerts", 0)
        if p0 > 0:
            base *= 0.5
        elif p1 >= 3:
            base *= 0.8

    return round(max(0.3, min(3.0, base)), 2)


# ── LLM 决策层 ────────────────────────────────────────────────────────────

def _call_deepseek(prompt: str, system: str, max_tokens: int = 800) -> Optional[str]:
    if not DEEPSEEK_API_KEY:
        return None
    try:
        import requests
        s = requests.Session(); s.trust_env = False
        r = s.post(
            f"{DEEPSEEK_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                     "Content-Type": "application/json"},
            json={
                "model": DEEPSEEK_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.3,
            },
            timeout=30,
        )
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
        _log("WARN", f"DeepSeek API {r.status_code}: {r.text[:200]}")
        return None
    except Exception as e:
        _log("WARN", f"DeepSeek调用异常: {e}")
        return None


def _check_and_trigger_evolution(state: dict) -> None:
    """
    检查并触发系统自进化
    触发条件:
    1. 连续亏损超过3笔
    2. 每月定期进化
    
    进化能力: A8-做梦部—联网搜索，agent b 和系统有这个自进化系统
    """
    import subprocess
    import time
    
    consecutive_losses = state.get("consecutive_losses", 0)
    last_evolution_ts = state.get("last_evolution_ts", 0)
    now_ts = time.time()
    
    should_evolve = False
    reason = ""
    
    if consecutive_losses >= 3:
        should_evolve = True
        reason = f"连续亏损{consecutive_losses}笔，触发紧急进化"
    else:
        one_month = 30 * 24 * 3600
        if now_ts - last_evolution_ts >= one_month:
            should_evolve = True
            reason = "每月定期进化"
    
    if should_evolve:
        _log("EVOLUTION", f"触发系统进化: {reason}")
        
        try:
            subprocess.Popen(
                ["python", "-m", "evolution_scheduler", "--trigger", reason],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True
            )
            _log("EVOLUTION", "进化任务已启动")
            state["last_evolution_ts"] = now_ts
            state["evolution_count"] = state.get("evolution_count", 0) + 1
            save_state(state)
        except Exception as e:
            _log("WARN", f"进化任务启动失败: {e}")


def _simple_mode_decision(screen1: dict, screen2: dict, price: float) -> dict:
    """
    简单模式决策：基于日线+1h双维度，简化决策逻辑
    当连续跳过或连续亏损次数过多时触发，扩大交易频率
    """
    reasons = []
    confidence = 50
    
    score_pct = screen1.get("score_pct", 50)
    direction = screen1.get("direction", "NEUTRAL")
    
    daily_trend = screen2.get("trend", "FLAT")
    hourly_signal = screen2.get("hourly_signal", "FLAT")
    
    if direction in ("BULL", "BEAR"):
        if daily_trend == direction.lower():
            confidence += 15
            reasons.append(f"日线趋势{daily_trend}与Screen1方向{direction}一致")
        if hourly_signal == direction.lower():
            confidence += 10
            reasons.append(f"1h信号{hourly_signal}与Screen1方向{direction}一致")
    
    if score_pct >= 60:
        confidence += 10
        reasons.append(f"Screen1评分{score_pct:.1f}%较高")
    elif score_pct >= 45:
        confidence += 5
        reasons.append(f"Screen1评分{score_pct:.1f}%中等")
    
    confidence = min(100, max(30, confidence))
    
    if direction == "BULL" and confidence >= 40:
        action = "OPEN_BULL"
    elif direction == "BEAR" and confidence >= 40:
        action = "OPEN_BEAR"
    else:
        action = "WAIT"
        reasons.append("方向不明确或置信度不足")
    
    return {
        "action": action,
        "confidence": confidence,
        "reasons": reasons,
        "mode": "simple",
        "vol_mult": BASE_VOL_MULT,
    }


def _five_algo_decision(full_signal: dict, screen1: dict, screen2: dict, screen3: dict, reports: dict) -> dict:
    """
    五大算法决策：基于 compute_full_trading_signal 的完整输出做决策
    五大算法: 静态指标投票 + 三维动态融合 + 动态权重调整 + 贝叶斯概率计算 + 技术面+基本面撮合

    决策逻辑（三屏趋势系统设计理念）:
    1. 趋势一致性（Screen1）：趋势不一致时一律 WAIT — 入场前置条件
    2. 置信度评估（Screen2）：决定仓位大小 — 置信度越高仓位越大
    3. Freqtrade入场信号（Screen3）：具体入场时机触发 — 有信号才动手
    4. 方向以五大算法为准，Screen1六维评分为参考
    """
    fs = full_signal["final_signal"]
    tc = full_signal["trend_consistency"]
    bc = full_signal["bayesian_confidence"]
    tff = full_signal["technical_fundamental_fusion"]
    ft_signals = full_signal.get("freqtrade_signals", {})

    reasons = []
    action = "WAIT"
    confidence = int(round(fs["confidence"], 0))

    weekly_dir = tc.get("weekly", {}).get("final_direction", "?")
    daily_dir = tc.get("daily", {}).get("final_direction", "?")

    # 前置条件1: 趋势一致性
    if not fs["trend_consistent"]:
        reasons.append(f"趋势不一致: 周线{weekly_dir} vs 日线{daily_dir}")
        return {
            "action": "WAIT",
            "confidence": 0,
            "reasons": reasons,
            "mode": "five_algo",
            "vol_mult": BASE_VOL_MULT,
            "freqtrade_signals": ft_signals,
        }

    # 基本面一致性检查
    if not fs.get("fusion_consistent", True):
        fundamental_dir = tff.get("fundamental", {}).get("direction", "?")
        reasons.append(f"技术面{bc.get('direction', '?')} vs 基本面{fundamental_dir}矛盾，置信度已扣减")

    reasons.append(f"五大算法综合: {fs['direction']} 置信{confidence}%")
    reasons.append(f"贝叶斯置信度: {bc.get('confidence', 0):.1f}%")
    reasons.append(f"趋势一致性: {'一致' if tc.get('consistent') else '不一致'}")

    # 前置条件2: Freqtrade 入场信号（Screen3 执行层触发）
    # 1h或4h任一同向信号即可触发，4h信号权重更高
    ft_bull = False
    ft_bear = False
    ft_trigger_tf = None
    ft_trigger_conf = 0
    for tf in ["4h", "1h"]:
        sig = ft_signals.get(tf, {})
        sig_dir = sig.get("signal", "HOLD")
        sig_conf = float(sig.get("confidence", 0) or 0)
        if sig_dir == "BUY" or sig_dir == "LONG":
            ft_bull = True
            if sig_conf > ft_trigger_conf:
                ft_trigger_conf = sig_conf
                ft_trigger_tf = tf
        elif sig_dir == "SELL" or sig_dir == "SHORT":
            ft_bear = True
            if sig_conf > ft_trigger_conf:
                ft_trigger_conf = sig_conf
                ft_trigger_tf = tf

    ft_consistent = fs.get("freqtrade_consistent", False)
    if ft_signals:
        reasons.append(f"Freqtrade信号: 1h={ft_signals.get('1h', {}).get('signal', 'HOLD')} 4h={ft_signals.get('4h', {}).get('signal', 'HOLD')}")
    else:
        reasons.append("Freqtrade信号: 无（经典系统不可用）")

    # 决策逻辑：趋势一致 + 置信足够 + Freqtrade同向触发
    if fs["direction"] == "BULL":
        if ft_bull and ft_consistent:
            action = "OPEN_BULL" if confidence >= 45 else "WAIT"
            reasons.append(f"Freqtrade {ft_trigger_tf} 同向看多，触发入场")
        elif not ft_signals:
            # 经典系统不可用时降级：仅看置信度（保守）
            action = "OPEN_BULL" if confidence >= 70 else "WAIT"
            if confidence >= 70:
                reasons.append("经典系统不可用，置信度≥70%降级入场")
            else:
                reasons.append("Freqtrade信号缺失+置信不足，等待")
        else:
            action = "WAIT"
            reasons.append("Freqtrade无同向信号，等待入场时机")
    elif fs["direction"] == "BEAR":
        if ft_bear and ft_consistent:
            action = "OPEN_BEAR" if confidence >= 45 else "WAIT"
            reasons.append(f"Freqtrade {ft_trigger_tf} 同向看空，触发入场")
        elif not ft_signals:
            action = "OPEN_BEAR" if confidence >= 70 else "WAIT"
            if confidence >= 70:
                reasons.append("经典系统不可用，置信度≥70%降级入场")
            else:
                reasons.append("Freqtrade信号缺失+置信不足，等待")
        else:
            action = "WAIT"
            reasons.append("Freqtrade无同向信号，等待入场时机")
    else:
        action = "WAIT"
        reasons.append("方向中性，等待")

    # 仓位大小由置信度决定（vol_mult 影响加仓间距）
    vol_mult = BASE_VOL_MULT
    if confidence >= 75:
        vol_mult = V15_VOL_MULT * 1.2
    elif confidence >= 60:
        vol_mult = V15_VOL_MULT
    elif confidence >= 45:
        vol_mult = BASE_VOL_MULT * 0.8

    return {
        "action": action,
        "confidence": confidence,
        "reasons": reasons[:5],
        "mode": "five_algo",
        "vol_mult": round(vol_mult, 2),
        "freqtrade_signals": ft_signals,
        "freqtrade_trigger_tf": ft_trigger_tf,
    }


def llm_decision(screen1: dict, screen2: dict, screen3: dict, reports: dict) -> dict:
    """
    三级决策：DeepSeek LLM → AI-V15 多因子评分 → V9 基线策略
    支持模式: auto/v9/ai_v15
    返回: {"action": "OPEN_BULL/OPEN_BEAR/WAIT/HOLD", "confidence": int, "reasons": [...], "mode": "deepseek/ai_v15/v9", "vol_mult": float}
    """
    weekly = reports.get("weekly") or {}
    a1_daily = reports.get("a1_daily") or {}
    a6_intel = reports.get("a6_intel") or {}

    # 用户强制模式
    if STRATEGY_MODE == "v9":
        result = _v9_baseline_decision(screen1, weekly, a1_daily, a6_intel)
        _record_usage("v9_fallback")
        return result
    if STRATEGY_MODE == "ai_v15":
        result = _v15_advanced_decision(screen1, weekly, a1_daily, a6_intel)
        _record_usage("ai_v15_fallback")
        return result

    # Level 1: DeepSeek LLM
    q = _load_quota()
    if DEEPSEEK_API_KEY and q.get("deepseek", 0) < LLM_DAILY_LIMIT:
        result = _llm_decision_deepseek(screen1, screen2, reports)
        if result:
            _record_usage("deepseek")
            return result

    # Level 2: AI-V15 多因子评分
    _log("INFO", "LLM不可用，降级到 AI-V15 多因子评分")
    result = _v15_advanced_decision(screen1, weekly, a1_daily, a6_intel)
    if result and result.get("confidence", 0) >= OPEN_CONFIDENCE_THRESHOLD:
        _record_usage("ai_v15_fallback")
        return result

    # Level 3: V9 基线策略（兜底）
    _log("INFO", "AI-V15置信不足，降级到 V9 基线策略")
    result = _v9_baseline_decision(screen1, weekly, a1_daily, a6_intel)
    _record_usage("v9_fallback")
    return result


def _llm_decision_deepseek(screen1: dict, screen2: dict, reports: dict) -> Optional[dict]:
    weekly = reports.get("weekly") or {}
    a1_daily = reports.get("a1_daily") or {}
    a6_intel = reports.get("a6_intel") or {}

    system_prompt = """你是专业加密货币交易分析师，负责三屏趋势策略的入场决策。
输出严格 JSON 格式，不要任何解释：
{
  "action": "OPEN_BULL" | "OPEN_BEAR" | "WAIT",
  "confidence": 0-100的整数,
  "vol_mult": 0.5到2.0之间的浮点数(默认1.0),
  "reasons": ["原因1", "原因2", "原因3"],
  "risk_note": "风险提示"
}

【核心铁律 - 必须遵守】
1. 入场前置条件：周线和日线的趋势方向必须一致（同向），不一致一律 WAIT。
2. 不轻易出手原则：方向错了就是巨亏。宁可错过，不可做错。
   - 无衰竭信号时，高确认度（≥70%）才考虑正常仓位开仓
   - 有衰竭信号时，允许降低阈值（≥45%）轻仓入场（趋势末尾的轻仓机会）
   - 中间状态一律 WAIT，不猜方向，不赌反弹/回调
3. Screen1 方向优先：方向以 Screen1 战略层为准，Screen2/3 只做确认和时机选择，不改变大方向。
4. 多维度交叉确认：没有任何单一指标是万能的，必须多维度共振才动手。
5. P0 告警绝对禁开：A6 有 P0 告警时绝对不开仓。

决策依据：
- OPEN_BULL：趋势一致 + Screen1 看多 + 研报确认 + 无P0告警 + 综合置信≥70%（无衰竭）/ ≥45%（有衰竭）
- OPEN_BEAR：趋势一致 + Screen1 看空 + 研报确认 + 无P0告警 + 综合置信≥70%（无衰竭）/ ≥45%（有衰竭）
- WAIT：趋势不一致、方向矛盾、置信不足、有P0告警、或处于中性震荡区

注意：趋势不一致时绝对不开仓，不要"试试"、"碰碰运气"。"""

    trend_c = screen1.get("trend_consistency", {})
    trend_m = screen1.get("trend_metrics", {})
    exhaust = screen1.get("exhaustion_signals", {})

    prompt = f"""三屏交易数据：

【Screen1 - 战略层】
方向: {screen1.get('direction', 'N/A')}
总分: {screen1.get('total_score', 0)}/100
置信度: {screen1.get('confidence', 'N/A')}
价格: ${screen1.get('price', 0):.2f}

【趋势一致性评估 - 入场前置条件】
一致性: {'✅一致' if trend_c.get('consistent') else '❌不一致'}
周线方向: {trend_c.get('weekly_direction', 'N/A')}
日线方向: {trend_c.get('daily_direction', 'N/A')}

【日线趋势指标】
EMA排列: {trend_m.get('daily', {}).get('direction', 'N/A')}
7日动量: {trend_m.get('daily', {}).get('speed', {}).get('7d', 'N/A')}%
14日动量: {trend_m.get('daily', {}).get('speed', {}).get('14d', 'N/A')}%
加速度: {trend_m.get('daily', {}).get('acceleration', 'N/A')}

【周线趋势指标】
EMA排列: {trend_m.get('weekly', {}).get('direction', 'N/A')}
7周动量: {trend_m.get('weekly', {}).get('speed', {}).get('7d', 'N/A')}%
14周动量: {trend_m.get('weekly', {}).get('speed', {}).get('14d', 'N/A')}%

【衰竭信号】
{'有衰竭: ' + ', '.join(exhaust.get('signals', [])) if exhaust.get('has_exhaustion') else '无衰竭信号'}

【Screen2 - 战术层】
方向: {screen2.get('direction', 'N/A')}
vol_mult: {screen2.get('vol_mult', 1.0)}
加仓间距: {screen2.get('addon_pct', 8)}%
止盈: {screen2.get('tp_pct', 4)}%
层级: {len(screen2.get('entry_levels', []))} 层

【周报参考】
方向: {weekly.get('direction', 'N/A')}
评分: {weekly.get('score', 'N/A')}/100
策略: {weekly.get('strategy', 'N/A')}
摘要: {weekly.get('summary', 'N/A')[:200]}

【A1日报参考】
regime: {a1_daily.get('regime', 'N/A')}
置信度: {a1_daily.get('confidence', 0):.0%}
SI指数: {a1_daily.get('si_index', {}).get('score', 'N/A')}
信号净方向: {a1_daily.get('signal_sufficiency', {}).get('net_direction', 'N/A')}
主要矛盾: {a1_daily.get('primary_contradiction', {}).get('description', 'N/A')[:150]}

【A6情报参考】
regime: {a6_intel.get('regime', 'N/A')}
SI指数: {a6_intel.get('si_score', 'N/A')}
P0告警: {a6_intel.get('p0_alerts', 0)}条
P1告警: {a6_intel.get('p1_alerts', 0)}条
操作建议: {a6_intel.get('recommendation', 'N/A')[:100]}

请给出决策（仅输出JSON）："""

    reply = _call_deepseek(prompt, system_prompt, max_tokens=800)
    if not reply:
        return None

    try:
        json_str = reply
        if "```json" in reply:
            json_str = reply.split("```json")[1].split("```")[0]
        elif "```" in reply:
            json_str = reply.split("```")[1].split("```")[0]

        result = json.loads(json_str.strip())
        action = result.get("action", "WAIT").upper()
        confidence = int(result.get("confidence", 50))
        vol_mult = float(result.get("vol_mult", 1.0))
        vol_mult = max(0.5, min(2.0, vol_mult))
        reasons = result.get("reasons", [])

        if action not in ("OPEN_BULL", "OPEN_BEAR", "WAIT", "HOLD"):
            action = "WAIT"

        _log("INFO", f"LLM决策: {action} 置信{confidence}% vol_mult={vol_mult} mode=deepseek")
        return {
            "action": action,
            "confidence": confidence,
            "reasons": reasons[:5],
            "mode": "deepseek",
            "vol_mult": vol_mult,
            "risk_note": result.get("risk_note", ""),
        }
    except Exception as e:
        _log("WARN", f"LLM返回解析失败: {e}")
        return None


def _v15_advanced_decision(screen1: dict, weekly: dict, a1_daily: dict, a6_intel: dict) -> dict:
    """
    AI-V15 多因子评分：多因子加权评分
    - Screen1权重: 35%
    - A1日报权重: 30%
    - 周报权重: 20%
    - A6情报权重: 15%
    前置条件：周线和日线趋势一致性
    """
    # 前置条件1：趋势一致性
    consistency = screen1.get("trend_consistency", {})
    if not consistency.get("consistent", True):
        return {
            "action": "WAIT",
            "confidence": 0,
            "reasons": [f"趋势不一致: {consistency.get('reason', '周线vs日线方向矛盾')}"],
            "mode": "ai_v15",
            "vol_mult": 1.0,
        }

    s1_dir = screen1.get("direction", "NEUTRAL")
    s1_score = screen1.get("total_score", 50)

    score_bull = 0
    score_bear = 0
    reasons = []

    # Screen1 (35%)
    if s1_dir == "BULL":
        score_bull += 35 * (s1_score / 100)
        reasons.append(f"Screen1看多({s1_score}分, +{35*(s1_score/100):.0f})")
    elif s1_dir == "BEAR":
        score_bear += 35 * (s1_score / 100)
        reasons.append(f"Screen1看空({s1_score}分, +{35*(s1_score/100):.0f})")
    else:
        reasons.append("Screen1中性")

    # A1日报 (30%)
    a1_net = a1_daily.get("signal_sufficiency", {}).get("net_direction", "")
    a1_conf = a1_daily.get("confidence", 0.5)
    a1_si = a1_daily.get("si_index", {}).get("score", 50)
    if a1_net == "UP":
        score_bull += 30 * a1_conf
        reasons.append(f"A1净方向UP(置信{a1_conf:.0%}, +{30*a1_conf:.0f})")
    elif a1_net == "DOWN":
        score_bear += 30 * a1_conf
        reasons.append(f"A1净方向DOWN(置信{a1_conf:.0%}, +{30*a1_conf:.0f})")
    else:
        reasons.append("A1信号不足")

    # 周报 (20%)
    wk_score = weekly.get("score")
    wk_dir = weekly.get("direction", "")
    if wk_score:
        if "牛" in str(wk_dir) or "BULL" in str(wk_dir).upper() or wk_score >= 65:
            score_bull += 20 * (min(wk_score, 100) / 100)
            reasons.append(f"周报偏多({wk_score}分, +{20*(min(wk_score,100)/100):.0f})")
        elif "熊" in str(wk_dir) or "BEAR" in str(wk_dir).upper() or wk_score <= 35:
            score_bear += 20 * ((100 - min(wk_score, 100)) / 100)
            reasons.append(f"周报偏空({wk_score}分, +{20*((100-min(wk_score,100))/100):.0f})")
        else:
            reasons.append("周报中性")

    # A6情报 (15%)
    p0 = a6_intel.get("p0_alerts", 0)
    a6_si = a6_intel.get("si_score", 0)
    rec = a6_intel.get("recommendation", "")
    if p0 > 0:
        score_bull -= 10
        score_bear -= 10
        reasons.append(f"A6有P0告警({p0}条, -10)")
    else:
        if a6_si > 10:
            score_bull += 15 * min(a6_si / 50, 1)
            reasons.append(f"A6 SI偏多({a6_si}, +{15*min(a6_si/50,1):.0f})")
        elif a6_si < -10:
            score_bear += 15 * min(abs(a6_si) / 50, 1)
            reasons.append(f"A6 SI偏空({a6_si}, +{15*min(abs(a6_si)/50,1):.0f})")

    # 计算最终方向和置信度
    total = score_bull + score_bear
    if total == 0:
        return {"action": "WAIT", "confidence": 0, "reasons": ["信号不足，等待"], "mode": "ai_v15", "vol_mult": 1.0}

    if score_bull > score_bear:
        action = "OPEN_BULL"
        confidence = int((score_bull / total) * 100)
    elif score_bear > score_bull:
        action = "OPEN_BEAR"
        confidence = int((score_bear / total) * 100)
    else:
        action = "WAIT"
        confidence = 50

    # 衰竭信号：降低置信度但允许轻仓入场
    exhaustion = screen1.get("exhaustion_signals", {})
    if exhaustion.get("has_exhaustion", False):
        adj = exhaustion.get("confidence_adjustment", 0)
        old_conf = confidence
        confidence = max(30, confidence + adj)
        reasons.append(f"衰竭信号({', '.join(exhaustion['signals'])}), 置信{old_conf}%→{confidence}%")

    vol_mult = V15_VOL_MULT
    if confidence < 50:
        vol_mult *= 0.8
    elif confidence > 75:
        vol_mult *= 1.2

    # 有衰竭信号时降低入场阈值（允许轻仓）
    entry_threshold = 35 if exhaustion.get("has_exhaustion", False) else 45

    return {
        "action": action if confidence >= entry_threshold else "WAIT",
        "confidence": confidence,
        "reasons": reasons,
        "mode": "ai_v15",
        "vol_mult": round(vol_mult, 2),
    }


def _v9_baseline_decision(screen1: dict, weekly: dict, a1_daily: dict, a6_intel: dict) -> dict:
    """
    V9 基线策略：纯 Screen1 驱动，vol_mult=1.0，简单可靠
    入场条件：趋势一致 + Screen1 非中性 + 无 P0 告警
    """
    # 前置条件：趋势一致性
    consistency = screen1.get("trend_consistency", {})
    if not consistency.get("consistent", True):
        return {
            "action": "WAIT",
            "confidence": 0,
            "reasons": [f"趋势不一致: {consistency.get('reason', '周线vs日线方向矛盾')}"],
            "mode": "v9",
            "vol_mult": BASE_VOL_MULT,
        }

    s1_dir = screen1.get("direction", "NEUTRAL")
    s1_score = screen1.get("total_score", 50)
    p0 = a6_intel.get("p0_alerts", 0) if a6_intel else 0

    reasons = []
    confidence = 50

    if p0 > 0:
        reasons.append(f"有P0告警({p0}条)，保守观望")
        return {"action": "WAIT", "confidence": 20, "reasons": reasons, "mode": "v9", "vol_mult": BASE_VOL_MULT}

    # 衰竭信号处理
    exhaustion = screen1.get("exhaustion_signals", {})
    has_exhaustion = exhaustion.get("has_exhaustion", False)

    if s1_dir == "BULL":
        confidence = min(70, s1_score)
        if has_exhaustion:
            adj = exhaustion.get("confidence_adjustment", 0)
            confidence = max(30, confidence + adj)
            reasons.append(f"Screen1看多({s1_score}分), 衰竭信号({', '.join(exhaustion['signals'])}), 置信→{confidence}%")
        else:
            reasons.append(f"Screen1看多({s1_score}分)")
        entry_threshold = 35 if has_exhaustion else 50
        action = "OPEN_BULL" if confidence >= entry_threshold else "WAIT"
        return {"action": action, "confidence": confidence, "reasons": reasons, "mode": "v9", "vol_mult": BASE_VOL_MULT}
    elif s1_dir == "BEAR":
        confidence = min(70, s1_score)
        if has_exhaustion:
            adj = exhaustion.get("confidence_adjustment", 0)
            confidence = max(30, confidence + adj)
            reasons.append(f"Screen1看空({s1_score}分), 衰竭信号({', '.join(exhaustion['signals'])}), 置信→{confidence}%")
        else:
            reasons.append(f"Screen1看空({s1_score}分)")
        entry_threshold = 35 if has_exhaustion else 50
        action = "OPEN_BEAR" if confidence >= entry_threshold else "WAIT"
        return {"action": action, "confidence": confidence, "reasons": reasons, "mode": "v9", "vol_mult": BASE_VOL_MULT}
    else:
        reasons.append("Screen1中性，观望")
        return {"action": "WAIT", "confidence": 30, "reasons": reasons, "mode": "v9", "vol_mult": BASE_VOL_MULT}


# ── 交易执行 ──────────────────────────────────────────────────────────────

def _place_order(inst_id: str, side: str, pos_side: str, size: float,
                 reduce_only: bool = False, td_mode: str = "isolated",
                 leverage: float = 5.0) -> dict:
    """下单入口

    根据 EXCHANGE_MODE 切换：
      - aster → AsterExecutor（趋势策略专用钱包 0x6632...A）
      - okx   → OKX CLI（历史路径，已禁用）
    """
    if EXCHANGE_MODE == "aster":
        # ── Aster 路径：使用趋势策略专用钱包 ──
        executor = _get_aster_executor()
        if executor is None:
            return {"ok": False, "err": "AsterExecutor 加载失败"}

        coin = _parse_coin_from_inst(inst_id)
        if not coin:
            return {"ok": False, "err": f"无法解析币种: {inst_id}"}

        # OKX side: buy/sell, pos_side: long/short
        # AsterExecutor 需要 long/short/buy/sell 任一
        aster_side = pos_side if pos_side in ("long", "short") else side

        try:
            # 计算名义价值（USDT）
            price_now = get_price(inst_id)
            notional_usd = float(size) * float(price_now) if price_now > 0 else 0.0

            # Aster 最小名义价值约 64 USDT，若低于则按数量下单兜底
            if notional_usd >= 64.0 and not reduce_only:
                result = executor.place_market_order(
                    coin=coin, side=aster_side,
                    notional_usd=notional_usd,
                    reduce_only=reduce_only,
                    leverage=int(leverage) if leverage else None,
                )
            else:
                # 数量下单（用于 reduce_only 平仓，或小额场景）
                result = executor.place_market_order_qty(
                    coin=coin, side=aster_side,
                    qty=float(size),
                    reduce_only=reduce_only,
                    leverage=int(leverage) if leverage else None,
                )

            if result.get("ok"):
                resp = result.get("resp", {})
                ord_id = resp.get("orderId") or resp.get("ordId") or "aster_ok"
                return {"ok": True, "ordId": str(ord_id),
                        "msg": f"aster {result.get('symbol','')} {result.get('side','')}"}
            return {"ok": False, "err": result.get("error", "aster_failed")}

        except Exception as e:
            _log("ERROR", f"[Aster] 下单异常 {inst_id} {side}: {e}")
            return {"ok": False, "err": str(e)}

    # ── OKX 路径（默认禁用）──
    _log("ERROR", f"[OKX] 下单路径已被禁用（EXCHANGE_MODE=aster）：{inst_id} {side} {size}")
    return {"ok": False, "err": "okx_path_disabled_aster_mode_only"}


_lot_size_cache = {}

def get_lot_size(inst_id: str) -> float:
    """获取合约最小下单数量（lot size），带缓存"""
    global _lot_size_cache
    if inst_id in _lot_size_cache:
        return _lot_size_cache[inst_id]

    r = _run_okx(["market", "instruments", "--instId", inst_id, "--instType", "SWAP", "--json"])
    lot_sz = 0.001
    if r["ok"] and isinstance(r["data"], list) and r["data"]:
        lot_sz = float(r["data"][0].get("lotSz", 0.001))
    _lot_size_cache[inst_id] = lot_sz
    return lot_sz


def _calc_position_size(equity: float, level: int, direction: str, entry_price: float, 
                        inst_id: str = INST_SWAP, position_pct: float = None,
                        leverage: float = 5.0, max_position_pct: float = 0.50) -> float:
    pct = position_pct if position_pct is not None else calc_actual_position_pct(0.30)
    pct = min(pct, max_position_pct)
    margin_usdt = equity * pct
    margin_usdt = max(margin_usdt, MIN_MARGIN_USD)
    notional_usdt = margin_usdt * leverage
    size = notional_usdt / entry_price
    lot_sz = get_lot_size(inst_id)
    size = math.floor(size / lot_sz) * lot_sz
    size = max(lot_sz, size)
    return round(size, 6)


# ── 主执行循环 ────────────────────────────────────────────────────────────

def check_and_execute(trigger_reason: str = "scheduled") -> dict:
    state = load_state()
    state["run_count"] = state.get("run_count", 0) + 1
    state["last_check_ts"] = datetime.now(timezone.utc).timestamp()

    _log("INFO", f"=== 第{state['run_count']}轮巡检 | 触发: {trigger_reason} ===")

    from screen_engine import scan_candidates, select_best_candidate, compute_screen3
    from report_loader import get_all_reports
    
    trend_system_path = "/home/ubuntu/Dreambuddy-V2-main/12-三屏趋势系统"
    if trend_system_path not in sys.path:
        sys.path.insert(0, trend_system_path)
    from engine import compute_full_trading_signal

    try:
        reports = get_all_reports()
        weekly = reports.get("weekly") or {}
        a1_daily = reports.get("a1_daily") or {}
        a6_intel = reports.get("a6_intel") or {}
        if weekly and not weekly.get("error"):
            state["weekly_ref_loaded"] = weekly.get("date", "")
        if a1_daily and not a1_daily.get("error"):
            state["daily_ref_loaded"] = a1_daily.get("timestamp", "")
        if a6_intel and not a6_intel.get("error"):
            state["intel_ref_loaded"] = a6_intel.get("date", "")
        _log("INFO", f"研报: 周报={bool(weekly and not weekly.get('error'))}, A1={bool(a1_daily and not a1_daily.get('error'))}, A6={bool(a6_intel and not a6_intel.get('error'))}")
    except Exception as e:
        _log("WARN", f"研报加载失败: {e}")
        weekly, a1_daily, a6_intel = {}, {}, {}
        reports = {"error": str(e)}

    try:
        candidates = scan_candidates()
        if not candidates:
            _log("ERROR", "没有可用候选币种")
            save_state(state)
            return {"ok": False, "error": "no candidates"}

        state["candidates"] = [
            {"symbol": c["symbol"], "direction": c["direction"], "score_pct": c["score_pct"], "vol_mult": c["vol_mult"]}
            for c in candidates
        ]

        active_symbol = state.get("active_symbol")
        active_inst = None
        if active_symbol:
            for c in candidates:
                if c["symbol"] == active_symbol:
                    active_inst = c
                    break

        if active_inst:
            s1 = active_inst["screen1"]
            s2 = active_inst["screen2"]
            current_symbol = active_symbol
            _log("INFO", f"持仓币种: {active_symbol}, 继续监控")
        else:
            # 遍历所有候选币种，找到第一个满足三屏入场条件的
            best_candidate = None
            best_signal = None
            for c in candidates:
                spot_inst = c.get("spot", f"{c['symbol']}-USDT")
                try:
                    sig = compute_full_trading_signal(spot_inst, c.get("is_btc", True))
                    if not sig.get("error"):
                        fs = sig["final_signal"]
                        if fs["action"] in ("ENTER_LONG", "ENTER_SHORT"):
                            best_candidate = c
                            best_signal = sig
                            _log("INFO", f"三屏入场信号: {c['symbol']} action={fs['action']} conf={fs['confidence']:.1f}% pos={fs['position']['position_pct']*100:.0f}%")
                            break
                except Exception:
                    continue

            if best_candidate:
                s1 = best_candidate["screen1"]
                s2 = best_candidate["screen2"]
                current_symbol = best_candidate["symbol"]
                state["full_trading_signal"] = best_signal
                _log("INFO", f"选中标的: {current_symbol} (三屏信号触发)")
            else:
                # 无三屏信号触发，回退到评分最优
                best, _ = select_best_candidate(min_score_pct=70.0)
                if best:
                    s1 = best["screen1"]
                    s2 = best["screen2"]
                    current_symbol = best["symbol"]
                    _log("INFO", f"最优标的: {current_symbol} {s1['direction']} 评分{s1['score_pct']:.1f}% vol_mult={best['vol_mult']}")
                else:
                    top = candidates[0]
                    s1 = top["screen1"]
                    s2 = top["screen2"]
                    current_symbol = top["symbol"]
                    _log("INFO", f"无达标标的，展示候选首: {current_symbol} {s1['direction']} {s1['score_pct']:.1f}%")

        price = s1["price"]
        _log("INFO", f"Screen1 [{current_symbol}]: {s1['direction']} {s1['score_pct']:.1f}%, 价格=${price}")

        s3 = compute_screen3(s2)
        current_swap = s2.get("inst_id", INST_SWAP)

        full_signal = None
        current_candidate = None
        for c in candidates:
            if c["symbol"] == current_symbol:
                current_candidate = c
                break
        
        if current_candidate:
            spot_inst = current_candidate.get("spot", f"{current_symbol}-USDT")
            try:
                full_signal = compute_full_trading_signal(spot_inst, current_candidate.get("is_btc", True))
                if not full_signal.get("error"):
                    fs_dir = full_signal["final_signal"]["direction"]
                    fs_conf = full_signal["final_signal"]["confidence"]
                    _log("INFO", f"五大算法信号 [{current_symbol}]: {fs_dir} 置信{fs_conf:.1f}%")
                    state["full_trading_signal"] = full_signal
                else:
                    _log("WARN", f"五大算法计算失败: {full_signal['error']}")
            except Exception as e:
                _log("WARN", f"五大算法调用异常: {e}")

        # ── 集成推理层：LightGBM 集成 + LLM 辩证推理 ──
        ensemble_pred = None
        reasoning_result = None
        if full_signal and not full_signal.get("error"):
            try:
                from ml.algo_ensemble import predict_ensemble, collect_sample
                from ml.llm_reasoning import reason_if_needed

                # LightGBM 集成推理
                ensemble_pred = predict_ensemble(full_signal)

                # LLM 辩证推理（仅在不确定时触发）
                reasoning_result = reason_if_needed(full_signal, ensemble_pred)

                src = reasoning_result.get("source", "unknown")
                rdir = reasoning_result.get("direction", "N/A")
                rconf = reasoning_result.get("confidence", 0)
                trigger = reasoning_result.get("trigger_reason", "N/A")
                _log("INFO", f"集成推理 [{current_symbol}]: source={src}, "
                      f"方向={rdir}, 置信={rconf:.1f}%, 触发={trigger}")

                if reasoning_result.get("contradictions"):
                    _log("INFO", f"矛盾检测: {'; '.join(reasoning_result['contradictions'])}")
                if reasoning_result.get("reasoning"):
                    _log("INFO", f"推理分析: {reasoning_result['reasoning'][:200]}")

                # 收集训练样本（后续回测标注 future_return）
                collect_sample(full_signal, symbol=current_symbol)

                state["ensemble_pred"] = {
                    "direction": ensemble_pred.get("direction"),
                    "confidence": ensemble_pred.get("confidence"),
                    "source": ensemble_pred.get("source"),
                }
                state["reasoning_result"] = {
                    "source": src,
                    "direction": rdir,
                    "confidence": rconf,
                    "trigger_reason": trigger,
                }
            except Exception as e:
                _log("WARN", f"集成推理层异常: {e}")

        acct = get_account_info()
        equity = acct.get("equity", 0)
        available = acct.get("available", 0)
        pos = get_position(current_swap)

        pos_str = f"{pos['side']} {pos['size']} {current_symbol}" if pos else "无"
        _log("INFO", f"账户: 权益=${equity:.2f}, 可用=${available:.2f}, 持仓={pos_str}")

        simple_mode = False
        consecutive_skips = state.get("consecutive_skips", 0)
        consecutive_losses = state.get("consecutive_losses", 0)
        
        if consecutive_skips >= SKIP_THRESHOLD_FOR_SIMPLE_MODE or consecutive_losses >= LOSS_THRESHOLD_FOR_SIMPLE_MODE:
            simple_mode = True
            _log("INFO", f"进入简单模式: 连续跳过{consecutive_skips}次, 连续亏损{consecutive_losses}次")
        
        state["simple_mode"] = simple_mode
        
        if full_signal and not full_signal.get("error"):
            fs = full_signal["final_signal"]

            # 集成推理增强：优先使用 LightGBM + LLM 推理结果
            if reasoning_result and reasoning_result.get("source") not in ("ensemble_fallback",):
                r_dir = reasoning_result["direction"]
                r_conf = reasoning_result["confidence"]

                # 推理方向与五大算法 action 对齐验证
                if r_dir == "BULL" and fs["action"] == "ENTER_LONG":
                    action = "OPEN_BULL"
                elif r_dir == "BEAR" and fs["action"] == "ENTER_SHORT":
                    action = "OPEN_BEAR"
                elif r_dir == "NEUTRAL":
                    action = "WAIT"
                else:
                    # 推理方向与五大算法不一致 → 安全起见 WAIT
                    action = "WAIT"

                decision = {
                    "action": action,
                    "confidence": r_conf,
                    "reasons": [
                        fs.get("decision_reason", ""),
                        f"推理来源: {reasoning_result['source']}",
                        reasoning_result.get("reasoning", "")[:200],
                    ],
                    "mode": "ensemble_llm",
                    "vol_mult": BASE_VOL_MULT,
                    "freqtrade_signals": full_signal.get("freqtrade_signals", {}),
                    "reasoning_source": reasoning_result["source"],
                    "contradictions": reasoning_result.get("contradictions", []),
                }
                _log("INFO", f"集成推理决策: mode={decision['mode']}, action={action}, "
                      f"置信={r_conf:.1f}%, source={reasoning_result['source']}")
            else:
                # 回退到原始五大算法
                decision = {
                    "action": "OPEN_BULL" if fs["action"] == "ENTER_LONG" else "OPEN_BEAR" if fs["action"] == "ENTER_SHORT" else "WAIT",
                    "confidence": fs["confidence"],
                    "reasons": [fs.get("decision_reason", "")],
                    "mode": "five_algo",
                    "vol_mult": BASE_VOL_MULT,
                    "freqtrade_signals": full_signal.get("freqtrade_signals", {}),
                }
                _log("INFO", f"五大算法决策: mode={decision['mode']}, action={decision['action']}, 置信{decision['confidence']}%")
            if fs.get("decision_reason"):
                _log("INFO", f"决策理由: {fs['decision_reason']}")
        elif simple_mode:
            decision = _simple_mode_decision(s1, s2, price)
        else:
            decision = llm_decision(s1, s2, s3, reports)

        # ── ML第三屏（AI屏）：用基线模型预测修正决策置信度 ──
        try:
            from ml_inference import get_ml_signal, adjust_decision_with_ml
            spot_inst_ml = current_candidate.get("spot", f"{current_symbol}-USDT") if current_candidate else f"{current_symbol}-USDT"
            ml_signal = get_ml_signal(spot_inst_ml)
            if not ml_signal.get("error"):
                original_conf = decision.get("confidence", 50.0)
                decision = adjust_decision_with_ml(decision, ml_signal, ml_weight=0.15)
                _log("INFO", f"ML第三屏 [{current_symbol}]: 方向={ml_signal['direction']}, "
                      f"上涨概率={ml_signal['prob_up']:.2f}, 置信={ml_signal['confidence']:.2f}")
                if decision.get("ml_boost"):
                    _log("INFO", f"ML调整: {decision['ml_boost']} (原{original_conf:.1f}% → {decision['confidence']:.1f}%)")
                state["ml_signal"] = ml_signal
            else:
                _log("WARN", f"ML信号异常: {ml_signal.get('error')}")
                state["ml_signal"] = {"error": ml_signal.get("error")}
        except Exception as e:
            _log("WARN", f"ML推理模块异常: {e}")
            state["ml_signal"] = {"error": str(e)}

        state["last_mode"] = decision.get("mode", "v9")
        state["last_symbol"] = current_symbol
        _log("INFO", f"决策层: mode={decision['mode']}, action={decision['action']}, 置信{decision['confidence']}%, 简单模式={simple_mode}")

        vol_mult = decision.get("vol_mult", BASE_VOL_MULT)
        vol_mult = _adjust_vol_mult_from_reports(vol_mult, weekly, a1_daily, a6_intel, decision.get("mode", "v9"))
        state["vol_mult"] = vol_mult
        state["addon_pct"] = round(BASE_ADDON_PCT * vol_mult * 100, 2)
        state["tp_pct"] = round(BASE_TP_PCT * vol_mult * 100, 2)

        if pos and state.get("active") and state["direction"]:
            _log("INFO", f"持仓监控: {state['direction']} 层级{state['current_level']}/{MAX_ADDONS}, 开仓=${state.get('open_price', 0):.2f}, 均价=${state.get('avg_entry', 0):.2f}, 止盈=${state.get('tp_price', 0):.2f}")

            open_price = state.get("open_price", state.get("avg_entry", price))
            levels, _, _, _ = _calc_levels(state["direction"], open_price, vol_mult)
            pos_side = "long" if state["direction"] == "BULL" else "short"
            long_dir = "LONG" if state["direction"] == "BULL" else "SHORT"

            leverage = state.get("leverage", 5.0)
            max_addon_position_pct = state.get("max_position_pct", 0.50) * 1.4
            max_addon_position_pct = min(max_addon_position_pct, 0.70)

            unrealized_pnl_pct = 0.0
            if pos and pos.get("upnl") is not None and state.get("avg_entry", 0) > 0:
                notional = state["avg_entry"] * state.get("total_size", 0)
                if notional > 0:
                    unrealized_pnl_pct = pos["upnl"] / notional * 100

            current_position_pct = state.get("current_budget_pct", state.get("entry_budget_pct", 0.30))

            has_counter_addon = state.get("has_counter_trend_addon", False)
            has_trend_addon = state.get("has_trend_follow_addon", False)
            total_addons = (1 if has_counter_addon else 0) + (1 if has_trend_addon else 0)

            if total_addons < 2 and current_position_pct < max_addon_position_pct:
                addon_decision = None
                try:
                    trend_system_path = "/home/ubuntu/Dreambuddy-V2-main/12-三屏趋势系统"
                    if trend_system_path not in sys.path:
                        sys.path.insert(0, trend_system_path)
                    from engine import evaluate_addon_decision

                    is_btc = state.get("active_symbol", "") == "BTC"
                    full_signal = state.get("full_trading_signal", {})
                    daily_df = None
                    btc_daily_df = None

                    addon_decision = evaluate_addon_decision(
                        symbol=state.get("active_symbol", ""),
                        direction=state["direction"],
                        current_price=price,
                        entry_price=state.get("avg_entry", price),
                        is_btc=is_btc,
                        daily_df=daily_df,
                        btc_daily_df=btc_daily_df,
                        unrealized_pnl_pct=unrealized_pnl_pct,
                        current_position_pct=current_position_pct,
                        max_position_cap=max_addon_position_pct,
                    )
                except Exception as e:
                    _log("WARN", f"加仓决策计算异常: {e}")

                if addon_decision and addon_decision.get("can_add"):
                    addon_type = addon_decision.get("addon_type", "")
                    addon_pct = addon_decision.get("addon_pct", 0) / 100
                    addon_price = addon_decision.get("addon_price", price)
                    addon_reason = addon_decision.get("reason", "")

                    if addon_type == "divergence_counter_trend" and not has_counter_addon:
                        add_budget_pct = addon_pct
                        current_budget = state.get("current_budget_pct", state.get("entry_budget_pct", 0.30))
                        new_budget = min(current_budget + add_budget_pct, max_addon_position_pct)
                        actual_add = new_budget - current_budget

                        if actual_add > 0.01:
                            add_size = _calc_position_size(equity, 1, state["direction"], addon_price, 
                                                           current_swap, position_pct=actual_add,
                                                           leverage=leverage, max_position_pct=max_addon_position_pct)
                            _log("ACTION", f"逆势加仓(背离): ${price:.2f}, 原因={addon_reason}, "
                                  f"+{add_size}币, 预算{current_budget*100:.0f}%→{new_budget*100:.0f}%")

                            if AUTO_EXECUTE:
                                side = "buy" if state["direction"] == "BULL" else "sell"
                                res = _place_order(current_swap, side, pos_side, add_size,
                                                   td_mode="isolated", leverage=leverage)
                                if res["ok"]:
                                    state["current_level"] = state.get("current_level", 0) + 1
                                    state["total_size"] = round(state.get("total_size", 0) + add_size, 6)
                                    total_cost = state.get("avg_entry", 0) * state.get("total_size", 0) + addon_price * add_size
                                    state["avg_entry"] = round(total_cost / state["total_size"], 2)
                                    state["has_counter_trend_addon"] = True
                                    state["current_budget_pct"] = new_budget
                                    state["last_action"] = "DIVERGENCE_ADDON"
                                    state["last_action_ts"] = datetime.now(timezone.utc).timestamp()
                                    state["last_reason"] = addon_reason
                                    _log("SUCCESS", f"逆势加仓成功: ordId={res['ordId']}, 均价=${state['avg_entry']:.2f}")
                                    state["trade_history"].append({
                                        "ts": datetime.now(timezone.utc).isoformat(),
                                        "action": "DIVERGENCE_ADDON",
                                        "side": state["direction"],
                                        "price": addon_price,
                                        "size": add_size,
                                        "budget_pct": actual_add,
                                        "total_budget_pct": new_budget,
                                        "mode": "value_risk",
                                        "reason": addon_reason,
                                        "addon_type": addon_type,
                                    })
                                else:
                                    _log("ERROR", f"逆势加仓失败: {res.get('err')}")
                            else:
                                _log("INFO", "[模拟] AUTO_EXECUTE=false，跳过")

                    elif addon_type == "trend_follow" and not has_trend_addon:
                        add_budget_pct = addon_pct
                        current_budget = state.get("current_budget_pct", state.get("entry_budget_pct", 0.30))
                        new_budget = min(current_budget + add_budget_pct, max_addon_position_pct)
                        actual_add = new_budget - current_budget

                        if actual_add > 0.01:
                            add_size = _calc_position_size(equity, 1, state["direction"], addon_price,
                                                           current_swap, position_pct=actual_add,
                                                           leverage=leverage, max_position_pct=max_addon_position_pct)
                            _log("ACTION", f"顺势加仓(趋势强度): ${price:.2f}, 原因={addon_reason}, "
                                  f"+{add_size}币, 预算{current_budget*100:.0f}%→{new_budget*100:.0f}%")

                            if AUTO_EXECUTE:
                                side = "buy" if state["direction"] == "BULL" else "sell"
                                res = _place_order(current_swap, side, pos_side, add_size,
                                                   td_mode="isolated", leverage=leverage)
                                if res["ok"]:
                                    state["total_size"] = round(state.get("total_size", 0) + add_size, 6)
                                    total_cost = state.get("avg_entry", 0) * state.get("total_size", 0) + addon_price * add_size
                                    state["avg_entry"] = round(total_cost / state["total_size"], 2)
                                    state["has_trend_follow_addon"] = True
                                    state["current_budget_pct"] = new_budget
                                    state["last_action"] = "TREND_STRENGTH_ADDON"
                                    state["last_action_ts"] = datetime.now(timezone.utc).timestamp()
                                    state["last_reason"] = addon_reason
                                    _log("SUCCESS", f"顺势加仓成功: ordId={res['ordId']}, 均价=${state['avg_entry']:.2f}")
                                    state["trade_history"].append({
                                        "ts": datetime.now(timezone.utc).isoformat(),
                                        "action": "TREND_STRENGTH_ADDON",
                                        "side": state["direction"],
                                        "price": addon_price,
                                        "size": add_size,
                                        "budget_pct": actual_add,
                                        "total_budget_pct": new_budget,
                                        "mode": "value_risk",
                                        "reason": addon_reason,
                                        "addon_type": addon_type,
                                    })
                                else:
                                    _log("ERROR", f"顺势加仓失败: {res.get('err')}")
                            else:
                                _log("INFO", "[模拟] AUTO_EXECUTE=false，跳过")

            side_close = "sell" if state["direction"] == "BULL" else "buy"
            reached_tp = False
            tp_target = state.get("tp_price", 0)
            if state["direction"] == "BULL" and price >= tp_target and tp_target > 0:
                reached_tp = True
            elif state["direction"] == "BEAR" and price <= tp_target and tp_target > 0:
                reached_tp = True

            if reached_tp and pos:
                pnl = pos.get("upnl", 0)
                _log("ACTION", f"止盈: ${price:.2f}到达${tp_target:.2f}, PnL=${pnl:.2f}")

                if AUTO_EXECUTE:
                    close_size = pos["size"]
                    res = _place_order(current_swap, side_close, pos_side, close_size, reduce_only=True)
                    if res["ok"]:
                        _log("SUCCESS", f"止盈成功: PnL≈${pnl:.2f}")
                        state["active"] = False
                        state["active_symbol"] = None
                        state["active_swap"] = None
                        state["direction"] = None
                        state["current_level"] = 0
                        state["total_size"] = 0
                        state["avg_entry"] = 0
                        state["tp_price"] = 0
                        state["entry_levels"] = []
                        state["last_action"] = "TP_CLOSE"
                        state["last_action_ts"] = datetime.now(timezone.utc).timestamp()
                        state["last_reason"] = f"止盈@${price:.2f}, PnL=${pnl:.2f}"
                        state["trade_history"].append({
                            "ts": datetime.now(timezone.utc).isoformat(),
                            "action": "TP_CLOSE",
                            "side": "N/A",
                            "price": price,
                            "size": close_size,
                            "pnl": pnl,
                            "mode": decision["mode"],
                            "reason": state["last_reason"],
                        })
                    else:
                        _log("ERROR", f"平仓失败: {res.get('err')}")
                else:
                    _log("INFO", "[模拟] AUTO_EXECUTE=false，跳过")

            reached_sl = False
            sl_target = state.get("sl_price", 0)
            if sl_target > 0:
                if state["direction"] == "BULL" and price <= sl_target:
                    reached_sl = True
                elif state["direction"] == "BEAR" and price >= sl_target:
                    reached_sl = True

            if reached_sl and pos and not reached_tp:
                pnl = pos.get("upnl", 0)
                _log("ACTION", f"止损: ${price:.2f}跌破${sl_target:.2f}, PnL=${pnl:.2f}")

                if AUTO_EXECUTE:
                    close_size = pos["size"]
                    res = _place_order(current_swap, side_close, pos_side, close_size, reduce_only=True)
                    if res["ok"]:
                        _log("SUCCESS", f"止损成功: PnL≈${pnl:.2f}")
                        state["active"] = False
                        state["active_symbol"] = None
                        state["active_swap"] = None
                        state["direction"] = None
                        state["current_level"] = 0
                        state["total_size"] = 0
                        state["avg_entry"] = 0
                        state["tp_price"] = 0
                        state["sl_price"] = 0
                        state["entry_levels"] = []
                        state["last_action"] = "SL_CLOSE"
                        state["last_action_ts"] = datetime.now(timezone.utc).timestamp()
                        state["last_reason"] = f"止损@${price:.2f}, PnL=${pnl:.2f}"
                        state["trade_history"].append({
                            "ts": datetime.now(timezone.utc).isoformat(),
                            "action": "SL_CLOSE",
                            "side": "N/A",
                            "price": price,
                            "size": close_size,
                            "pnl": pnl,
                            "mode": decision["mode"],
                            "reason": state["last_reason"],
                        })
                    else:
                        _log("ERROR", f"平仓失败: {res.get('err')}")
                else:
                    _log("INFO", "[模拟] AUTO_EXECUTE=false，跳过")

        else:
            action = decision.get("action", "WAIT")
            conf = decision.get("confidence", 0)
            reasons = decision.get("reasons", [])
            mode = decision.get("mode", "v9")

            _log("INFO", f"开仓评估: {action} 置信{conf}% mode={mode}")
            for r in reasons:
                _log("INFO", f"  - {r}")

            # 引擎已做完整三屏决策（趋势一致+Freqtrade同向→入场），执行器直接执行
            if action in ("OPEN_BULL", "OPEN_BEAR") and not pos:
                direction = "BULL" if "BULL" in action else "BEAR"
                long_dir = "LONG" if direction == "BULL" else "SHORT"
                levels, tp_price, addon_pct, tp_pct = _calc_levels(direction, price, vol_mult)

                full_signal = state.get("full_trading_signal", {})
                fs_pos = full_signal.get("final_signal", {}).get("position", {})
                if fs_pos and fs_pos.get("position_pct", 0) > 0:
                    position_pct = fs_pos["position_pct"]
                    entry_budget_pct = position_pct / MAX_POSITION_PCT if MAX_POSITION_PCT > 0 else position_pct
                else:
                    entry_budget_pct = calc_entry_budget_pct(conf)
                    position_pct = calc_actual_position_pct(entry_budget_pct)
                is_trial = conf < OPEN_CONFIDENCE_THRESHOLD

                leverage = 5.0
                max_position_pct = 0.50
                if full_signal and full_signal.get("final_signal"):
                    leverage = full_signal["final_signal"].get("leverage", 5.0)
                    max_position_pct = full_signal["final_signal"].get("max_position_pct", 0.50)

                position_pct = min(position_pct, max_position_pct)

                vr = full_signal.get("value_risk_assessment", {}) if full_signal else {}
                if vr and vr.get("take_profit_stop_loss"):
                    tp_sl = vr["take_profit_stop_loss"]
                    tp_price = tp_sl.get("take_profit_price", tp_price)
                    sl_price = tp_sl.get("stop_loss_price", 0)
                    tp_pct = tp_sl.get("take_profit_pct", tp_pct)
                    sl_pct = tp_sl.get("stop_loss_pct", STOP_LOSS_PCT * 100)
                    vol_ratio = vr.get("volatility", {}).get("vol_ratio", 1.0)
                else:
                    sl_price = price * (1 - STOP_LOSS_PCT) if direction == "BULL" else price * (1 + STOP_LOSS_PCT)
                    sl_pct = STOP_LOSS_PCT * 100
                    vol_ratio = 1.0

                entry_size = _calc_position_size(equity, 0, direction, price, current_swap, 
                                                  position_pct=position_pct, leverage=leverage,
                                                  max_position_pct=max_position_pct)
                pos_side = "long" if direction == "BULL" else "short"
                side = "buy" if direction == "BULL" else "sell"

                mode_text = f"置信{conf}%预算占{entry_budget_pct*100:.0f}%"
                _log("ACTION", f"开仓[{mode_text}]: {direction} {current_symbol} ${price:.2f}, "
                      f"止盈${tp_price:.2f}({tp_pct:.1f}%), 止损${sl_price:.2f}({sl_pct:.1f}%), "
                      f"首仓{entry_size}, 杠杆{leverage}x, 逐仓模式, 账户占比{position_pct*100:.1f}%, "
                      f"波动率比{vol_ratio:.2f}")

                if AUTO_EXECUTE:
                    res = _place_order(current_swap, side, pos_side, entry_size, 
                                       td_mode="isolated", leverage=leverage)
                    if res["ok"]:
                        state["active"] = True
                        state["active_symbol"] = current_symbol
                        state["active_swap"] = current_swap
                        state["direction"] = direction
                        state["current_level"] = 0
                        state["total_size"] = entry_size
                        state["avg_entry"] = price
                        state["open_price"] = price
                        state["tp_price"] = tp_price
                        state["sl_price"] = sl_price
                        state["entry_levels"] = [l["price"] for l in levels]
                        state["is_trial"] = is_trial
                        state["entry_confidence"] = conf
                        state["current_confidence"] = conf
                        state["entry_budget_pct"] = entry_budget_pct
                        state["current_budget_pct"] = entry_budget_pct
                        state["has_counter_trend_addon"] = False
                        state["has_trend_follow_addon"] = False
                        state["leverage"] = leverage
                        state["margin_mode"] = "isolated"
                        state["max_position_pct"] = max_position_pct
                        state["vol_ratio"] = vol_ratio
                        state["last_action"] = "OPEN_" + direction
                        state["last_action_ts"] = datetime.now(timezone.utc).timestamp()
                        state["last_reason"] = f"{decision['mode']}决策{mode_text}置信{conf}%"
                        _log("SUCCESS", f"开仓成功: ordId={res['ordId']}, 逐仓模式, 杠杆{leverage}x")
                        state["trade_history"].append({
                            "ts": datetime.now(timezone.utc).isoformat(),
                            "action": "OPEN_" + direction,
                            "side": direction,
                            "price": price,
                            "size": entry_size,
                            "confidence": conf,
                            "budget_pct": entry_budget_pct,
                            "position_pct": position_pct,
                            "mode": decision["mode"],
                            "reasons": reasons,
                            "is_trial": is_trial,
                            "tp_price": tp_price,
                            "sl_price": sl_price,
                            "leverage": leverage,
                            "margin_mode": "isolated",
                        })
                    else:
                        _log("ERROR", f"开仓失败: {res.get('err')}")
                else:
                    _log("INFO", "[模拟] AUTO_EXECUTE=false，仅记录信号")
                    state["last_action"] = "SIGNAL_" + direction
                    state["last_action_ts"] = datetime.now(timezone.utc).timestamp()
                    state["last_reason"] = f"{decision['mode']}决策{mode_text}置信{conf}% (模拟)"

    except Exception as e:
        _log("ERROR", f"执行异常: {e}")
        import traceback
        _log("ERROR", traceback.format_exc())
        save_state(state)
        return {"ok": False, "error": str(e)}

    action = decision.get("action", "WAIT")
    last_action = state.get("last_action", "")
    
    if action == "WAIT" and not pos:
        state["consecutive_skips"] = state.get("consecutive_skips", 0) + 1
        _log("INFO", f"连续跳过次数: {state['consecutive_skips']}")
    elif action in ("OPEN_BULL", "OPEN_BEAR"):
        state["consecutive_skips"] = 0
    
    if "CLOSE" in last_action and "PnL" in state.get("last_reason", ""):
        pnl_str = state["last_reason"]
        if "-" in pnl_str and "$" in pnl_str:
            pnl_parts = pnl_str.split("$")
            for part in pnl_parts:
                if part and part.replace("-", "").replace(".", "").isdigit():
                    pnl_val = float(part.replace(",", ""))
                    if pnl_val < 0:
                        state["consecutive_losses"] = state.get("consecutive_losses", 0) + 1
                        _log("INFO", f"连续亏损次数: {state['consecutive_losses']}")
                    else:
                        state["consecutive_losses"] = 0
                    break
    
    save_state(state)
    _log("INFO", f"=== 第{state['run_count']}轮完成 | action={state.get('last_action', 'NONE')} mode={state.get('last_mode', '?')} ===")

    _check_and_trigger_evolution(state)

    return {
        "ok": True,
        "state": state,
        "price": price if 'price' in dir() else 0,
        "auto_execute": AUTO_EXECUTE,
        "mode": state.get("last_mode", "v9"),
    }


def get_executor_state() -> dict:
    state = load_state()
    state["quota"] = get_quota_status()
    state["auto_execute"] = AUTO_EXECUTE
    state["strategy_mode"] = STRATEGY_MODE

    # 集成经典指标执行器状态
    try:
        from classic_executor import get_executor_state as get_classic_state
        state["classic_executor"] = get_classic_state()
    except Exception as e:
        state["classic_executor"] = {"error": str(e)}

    return state


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        reason = sys.argv[2] if len(sys.argv) > 2 else "manual"
        result = check_and_execute(trigger_reason=reason)
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    else:
        state = get_executor_state()
        print(json.dumps(state, indent=2, ensure_ascii=False))
