#!/usr/bin/env python3
"""
三屏马丁交易执行引擎 v2
- LLM 决策：DeepSeek API，配额用尽自动回退 V9/V15 基线
- 三级回退：DeepSeek LLM → V15 高级规则 → V9 基线策略
- 自主编排：事件驱动 + 4h 心跳 + 波动触发
- 策略：V9马丁基线（可动态调整 vol_mult）
"""
import json, os, subprocess, math, re, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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

MAX_ADDONS = 3
BASE_ADDON_PCT = 0.08
BASE_TP_PCT = 0.04
BASE_VOL_MULT = 1.0
V15_VOL_MULT = 1.875

BASE_POSITION_PCT = 0.05
MAX_POSITION_PCT = 0.25

OPEN_CONFIDENCE_THRESHOLD = 70

AUTO_EXECUTE = os.environ.get("SCREEN_AUTO_EXECUTE", "true").lower() == "true"

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
LLM_DAILY_LIMIT = int(os.environ.get("SCREEN_LLM_DAILY_LIMIT", "12"))

STRATEGY_MODE = os.environ.get("SCREEN_STRATEGY_MODE", "auto")  # auto/v9/v15


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
        "v15_fallback": 0,
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
        "v15_fallback": q.get("v15_fallback", 0),
        "v9_fallback": q.get("v9_fallback", 0),
    }


# ── 状态管理 ──────────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "active": False,
        "direction": None,
        "entry_levels": [],
        "current_level": 0,
        "total_size": 0,
        "avg_entry": 0,
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


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


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


def llm_decision(screen1: dict, screen2: dict, screen3: dict, reports: dict) -> dict:
    """
    三级决策：DeepSeek LLM → V15 高级规则 → V9 基线策略
    返回: {"action": "OPEN_BULL/OPEN_BEAR/WAIT/HOLD", "confidence": int, "reasons": [...], "mode": "deepseek/v15/v9", "vol_mult": float}
    """
    weekly = reports.get("weekly") or {}
    a1_daily = reports.get("a1_daily") or {}
    a6_intel = reports.get("a6_intel") or {}

    # 用户强制模式
    if STRATEGY_MODE == "v9":
        result = _v9_baseline_decision(screen1, weekly, a1_daily, a6_intel)
        _record_usage("v9_fallback")
        return result
    if STRATEGY_MODE == "v15":
        result = _v15_advanced_decision(screen1, weekly, a1_daily, a6_intel)
        _record_usage("v15_fallback")
        return result

    # Level 1: DeepSeek LLM
    q = _load_quota()
    if DEEPSEEK_API_KEY and q.get("deepseek", 0) < LLM_DAILY_LIMIT:
        result = _llm_decision_deepseek(screen1, screen2, reports)
        if result:
            _record_usage("deepseek")
            return result

    # Level 2: V15 高级规则
    _log("INFO", "LLM不可用，降级到 V15 高级规则")
    result = _v15_advanced_decision(screen1, weekly, a1_daily, a6_intel)
    if result and result.get("confidence", 0) >= OPEN_CONFIDENCE_THRESHOLD:
        _record_usage("v15_fallback")
        return result

    # Level 3: V9 基线策略（兜底）
    _log("INFO", "V15置信不足，降级到 V9 基线策略")
    result = _v9_baseline_decision(screen1, weekly, a1_daily, a6_intel)
    _record_usage("v9_fallback")
    return result


def _llm_decision_deepseek(screen1: dict, screen2: dict, reports: dict) -> Optional[dict]:
    weekly = reports.get("weekly") or {}
    a1_daily = reports.get("a1_daily") or {}
    a6_intel = reports.get("a6_intel") or {}

    system_prompt = """你是专业加密货币交易分析师，负责三屏马丁策略的入场决策。
输出严格 JSON 格式，不要任何解释：
{
  "action": "OPEN_BULL" | "OPEN_BEAR" | "WAIT",
  "confidence": 0-100的整数,
  "vol_mult": 0.5到2.0之间的浮点数(默认1.0),
  "reasons": ["原因1", "原因2", "原因3"],
  "risk_note": "风险提示"
}

【核心铁律 - 必须遵守】
1. 不轻易出手原则：马丁策略无止损，方向错了就是巨亏。宁可错过，不可做错。
   - 只有高确认度（≥70%）才考虑开仓
   - 中间状态一律 WAIT，不猜方向，不赌反弹/回调
2. Screen1 方向优先：方向以 Screen1 战略层为准，Screen2/3 只做确认和时机选择，不改变大方向。
3. 多维度交叉确认：没有任何单一指标是万能的，必须多维度共振才动手。
4. P0 告警绝对禁开：A6 有 P0 告警时绝对不开仓。

决策依据：
- OPEN_BULL：Screen1 看多 + 研报确认 + 无P0告警 + 综合置信≥70%
- OPEN_BEAR：Screen1 看空 + 研报确认 + 无P0告警 + 综合置信≥70%
- WAIT：方向矛盾、置信不足、有P0告警、或处于中性震荡区

注意：置信度低于70%一律输出 WAIT，不要"试试"、"碰碰运气"。"""

    prompt = f"""三屏交易数据：

【Screen1 - 战略层】
方向: {screen1.get('direction', 'N/A')}
总分: {screen1.get('total_score', 0)}/100
置信度: {screen1.get('confidence', 'N/A')}
价格: ${screen1.get('price', 0):.2f}

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
    V15 高级规则：多因子加权评分
    - Screen1权重: 35%
    - A1日报权重: 30%
    - 周报权重: 20%
    - A6情报权重: 15%
    """
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
        return {"action": "WAIT", "confidence": 0, "reasons": ["信号不足，等待"], "mode": "v15", "vol_mult": 1.0}

    if score_bull > score_bear:
        action = "OPEN_BULL"
        confidence = int((score_bull / total) * 100)
    elif score_bear > score_bull:
        action = "OPEN_BEAR"
        confidence = int((score_bear / total) * 100)
    else:
        action = "WAIT"
        confidence = 50

    vol_mult = V15_VOL_MULT
    if confidence < 50:
        vol_mult *= 0.8
    elif confidence > 75:
        vol_mult *= 1.2

    return {
        "action": action if confidence >= 45 else "WAIT",
        "confidence": confidence,
        "reasons": reasons,
        "mode": "v15",
        "vol_mult": round(vol_mult, 2),
    }


def _v9_baseline_decision(screen1: dict, weekly: dict, a1_daily: dict, a6_intel: dict) -> dict:
    """
    V9 基线策略：纯 Screen1 驱动，vol_mult=1.0，简单可靠
    入场条件：Screen1 非中性 + 无 P0 告警
    """
    s1_dir = screen1.get("direction", "NEUTRAL")
    s1_score = screen1.get("total_score", 50)
    p0 = a6_intel.get("p0_alerts", 0) if a6_intel else 0

    reasons = []
    confidence = 50

    if p0 > 0:
        reasons.append(f"有P0告警({p0}条)，保守观望")
        return {"action": "WAIT", "confidence": 20, "reasons": reasons, "mode": "v9", "vol_mult": BASE_VOL_MULT}

    if s1_dir == "BULL":
        confidence = min(70, s1_score)
        reasons.append(f"Screen1看多({s1_score}分)")
        return {"action": "OPEN_BULL", "confidence": confidence, "reasons": reasons, "mode": "v9", "vol_mult": BASE_VOL_MULT}
    elif s1_dir == "BEAR":
        confidence = min(70, s1_score)
        reasons.append(f"Screen1看空({s1_score}分)")
        return {"action": "OPEN_BEAR", "confidence": confidence, "reasons": reasons, "mode": "v9", "vol_mult": BASE_VOL_MULT}
    else:
        reasons.append("Screen1中性，观望")
        return {"action": "WAIT", "confidence": 30, "reasons": reasons, "mode": "v9", "vol_mult": BASE_VOL_MULT}


# ── 交易执行 ──────────────────────────────────────────────────────────────

def _place_order(inst_id: str, side: str, pos_side: str, size: float, reduce_only: bool = False) -> dict:
    args = [
        "swap", "place",
        "--instId", inst_id,
        "--side", side,
        "--posSide", pos_side,
        "--ordType", "market",
        "--sz", str(size),
        "--tdMode", "cross",
        "--json",
    ]
    if reduce_only:
        args.append("--reduceOnly")

    r = _run_okx(args)
    if r["ok"] and isinstance(r["data"], list) and r["data"]:
        item = r["data"][0]
        if item.get("sCode") == "0":
            return {"ok": True, "ordId": item.get("ordId"), "msg": item.get("sMsg")}
        return {"ok": False, "err": item.get("sMsg", "unknown")}
    return {"ok": False, "err": r.get("err", str(r))}


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


def _calc_position_size(equity: float, level: int, direction: str, entry_price: float, inst_id: str = INST_SWAP) -> float:
    pos_usdt = equity * BASE_POSITION_PCT
    size = pos_usdt / entry_price
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

        acct = get_account_info()
        equity = acct.get("equity", 0)
        available = acct.get("available", 0)
        pos = get_position(current_swap)

        pos_str = f"{pos['side']} {pos['size']} {current_symbol}" if pos else "无"
        _log("INFO", f"账户: 权益=${equity:.2f}, 可用=${available:.2f}, 持仓={pos_str}")

        decision = llm_decision(s1, s2, s3, reports)
        state["last_mode"] = decision.get("mode", "v9")
        state["last_symbol"] = current_symbol
        _log("INFO", f"决策层: mode={decision['mode']}, action={decision['action']}, 置信{decision['confidence']}%")

        vol_mult = decision.get("vol_mult", BASE_VOL_MULT)
        vol_mult = _adjust_vol_mult_from_reports(vol_mult, weekly, a1_daily, a6_intel, decision.get("mode", "v9"))
        state["vol_mult"] = vol_mult
        state["addon_pct"] = round(BASE_ADDON_PCT * vol_mult * 100, 2)
        state["tp_pct"] = round(BASE_TP_PCT * vol_mult * 100, 2)

        if pos and state.get("active") and state["direction"]:
            _log("INFO", f"持仓监控: {state['direction']} 层级{state['current_level']}/{MAX_ADDONS}, 入场=${state.get('avg_entry', 0):.2f}, 止盈=${state.get('tp_price', 0):.2f}")

            levels, tp_price, _, _ = _calc_levels(state["direction"], price, vol_mult)
            pos_side = "long" if state["direction"] == "BULL" else "short"

            next_level = state["current_level"] + 1
            if next_level <= MAX_ADDONS:
                next_px = levels[next_level]["price"]
                should_add = False
                if state["direction"] == "BULL" and price <= next_px:
                    should_add = True
                elif state["direction"] == "BEAR" and price >= next_px:
                    should_add = True

                if should_add:
                    add_size = _calc_position_size(equity, next_level, state["direction"], next_px, current_swap)
                    _log("ACTION", f"加仓{next_level}: ${price:.2f}触发${next_px:.2f}, +{add_size}BTC")

                    if AUTO_EXECUTE:
                        side = "buy" if state["direction"] == "BULL" else "sell"
                        res = _place_order(current_swap, side, pos_side, add_size)
                        if res["ok"]:
                            state["current_level"] = next_level
                            state["total_size"] = round(state.get("total_size", 0) + add_size, 6)
                            total_cost = state.get("avg_entry", 0) * state.get("total_size", 0) + next_px * add_size
                            state["avg_entry"] = round(total_cost / state["total_size"], 2)
                            state["last_action"] = f"ADDON_{next_level}"
                            state["last_action_ts"] = datetime.now(timezone.utc).timestamp()
                            state["last_reason"] = f"价格${price:.2f}触发加仓{next_level}@${next_px:.2f} ({decision['mode']})"
                            _log("SUCCESS", f"加仓成功: ordId={res['ordId']}")
                            state["trade_history"].append({
                                "ts": datetime.now(timezone.utc).isoformat(),
                                "action": f"ADDON_{next_level}",
                                "side": state["direction"],
                                "price": next_px,
                                "size": add_size,
                                "mode": decision["mode"],
                                "reason": state["last_reason"],
                            })
                        else:
                            _log("ERROR", f"加仓失败: {res.get('err')}")
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

        else:
            action = decision.get("action", "WAIT")
            conf = decision.get("confidence", 0)
            reasons = decision.get("reasons", [])

            _log("INFO", f"开仓评估: {action} 置信{conf}% mode={decision['mode']}")
            for r in reasons:
                _log("INFO", f"  - {r}")

            if action in ("OPEN_BULL", "OPEN_BEAR") and conf >= OPEN_CONFIDENCE_THRESHOLD and not pos:
                direction = "BULL" if "BULL" in action else "BEAR"
                levels, tp_price, addon_pct, tp_pct = _calc_levels(direction, price, vol_mult)
                entry_size = _calc_position_size(equity, 0, direction, price, current_swap)
                pos_side = "long" if direction == "BULL" else "short"
                side = "buy" if direction == "BULL" else "sell"

                _log("ACTION", f"开仓: {direction} {current_symbol} ${price:.2f}, 止盈${tp_price:.2f}, 首仓{entry_size}, vol_mult={vol_mult}")

                if AUTO_EXECUTE:
                    res = _place_order(current_swap, side, pos_side, entry_size)
                    if res["ok"]:
                        state["active"] = True
                        state["active_symbol"] = current_symbol
                        state["active_swap"] = current_swap
                        state["direction"] = direction
                        state["current_level"] = 0
                        state["total_size"] = entry_size
                        state["avg_entry"] = price
                        state["tp_price"] = tp_price
                        state["entry_levels"] = [l["price"] for l in levels]
                        state["last_action"] = "OPEN_" + direction
                        state["last_action_ts"] = datetime.now(timezone.utc).timestamp()
                        state["last_reason"] = f"{decision['mode']}决策置信{conf}%"
                        _log("SUCCESS", f"开仓成功: ordId={res['ordId']}")
                        state["trade_history"].append({
                            "ts": datetime.now(timezone.utc).isoformat(),
                            "action": "OPEN_" + direction,
                            "side": direction,
                            "price": price,
                            "size": entry_size,
                            "confidence": conf,
                            "mode": decision["mode"],
                            "reasons": reasons,
                        })
                    else:
                        _log("ERROR", f"开仓失败: {res.get('err')}")
                else:
                    _log("INFO", "[模拟] AUTO_EXECUTE=false，仅记录信号")
                    state["last_action"] = "SIGNAL_" + direction
                    state["last_action_ts"] = datetime.now(timezone.utc).timestamp()
                    state["last_reason"] = f"{decision['mode']}决策置信{conf}% (模拟)"

    except Exception as e:
        _log("ERROR", f"执行异常: {e}")
        import traceback
        _log("ERROR", traceback.format_exc())
        save_state(state)
        return {"ok": False, "error": str(e)}

    save_state(state)
    _log("INFO", f"=== 第{state['run_count']}轮完成 | action={state.get('last_action', 'NONE')} mode={state.get('last_mode', '?')} ===")

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
