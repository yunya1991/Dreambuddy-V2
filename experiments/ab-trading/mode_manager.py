#!/usr/bin/env python3
"""
三屏马丁 - 模式管理器
- AI 主导模式 vs 经典接管模式
- A1 研报新鲜度检测
- AI 指令配置写入/读取
- 模式切换状态持久化
"""
import json, os, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, Any

BASE_DIR = Path(__file__).resolve().parent
STATE_DIR = BASE_DIR / "data" / "mode_state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

MODE_STATE_FILE = STATE_DIR / "mode_state.json"
AI_DIRECTIVE_FILE = STATE_DIR / "ai_directive.json"
MODE_HISTORY_FILE = STATE_DIR / "mode_history.jsonl"

# 经典指标系统目录（预留接口）
CLASSIC_SYSTEM_DIR = Path(__file__).resolve().parents[2] / "10-经典指标系统"

# 新鲜度阈值（小时）
FRESHNESS_THRESHOLDS = {
    "a1_daily": 24,      # A1 日报 24 小时
    "a6_intel": 6,       # A6 情报 6 小时
    "weekly": 168,       # 周报 7 天
}

# 模式定义
MODE_AI_DIRECTED = "ai_directed"       # AI 主导模式
MODE_CLASSIC_TAKEOVER = "classic_takeover"  # 经典接管模式

_state_cache: Optional[Dict] = None
_cache_ts: float = 0
_CACHE_TTL = 60  # 60 秒缓存


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_utc().isoformat()


def _parse_ts(ts_str: str) -> Optional[datetime]:
    """解析时间戳字符串"""
    if not ts_str:
        return None
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        # 尝试解析日期字符串（如 2026-07-06）
        try:
            dt = datetime.strptime(ts_str[:10], "%Y-%m-%d")
            return dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None


def _load_json(path: Path) -> Dict:
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_json(path: Path, data: Dict):
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _append_history(entry: Dict):
    """追加模式切换历史"""
    try:
        with open(MODE_HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ── 研报新鲜度检测 ──────────────────────────────────────────────────────

def check_reports_freshness() -> Dict[str, Any]:
    """
    检查所有研报的新鲜度
    返回: {
        a1_daily: {fresh: bool, age_hours: float, timestamp: str},
        a6_intel: {...},
        weekly: {...},
        any_fresh: bool,
        a1_fresh: bool,  # 关键：A1 是否新鲜（模式切换的核心依据）
        all_expired: bool,
    }
    """
    try:
        from report_loader import get_all_reports
        reports = get_all_reports()
    except Exception as e:
        return {
            "error": str(e),
            "a1_fresh": False,
            "any_fresh": False,
            "all_expired": True,
        }

    now = _now_utc()
    result = {}
    fresh_count = 0

    for key, max_age_h in FRESHNESS_THRESHOLDS.items():
        rpt = reports.get(key) or {}
        entry = {"fresh": False, "age_hours": None, "timestamp": None, "error": None}

        if rpt.get("error"):
            entry["error"] = rpt["error"]
            result[key] = entry
            continue

        ts_str = rpt.get("timestamp") or rpt.get("date") or ""
        entry["timestamp"] = ts_str

        dt = _parse_ts(ts_str)
        if dt:
            age_h = (now - dt).total_seconds() / 3600
            entry["age_hours"] = round(age_h, 1)
            entry["fresh"] = age_h <= max_age_h
            if entry["fresh"]:
                fresh_count += 1
        else:
            entry["error"] = "无法解析时间戳"

        result[key] = entry

    result["a1_fresh"] = result.get("a1_daily", {}).get("fresh", False)
    result["any_fresh"] = fresh_count > 0
    result["all_expired"] = fresh_count == 0
    result["checked_at"] = _now_iso()

    return result


def get_deterministic_mode() -> str:
    """
    根据研报新鲜度确定性判断模式
    - A1 日报 < 24h → AI 主导模式
    - A1 日报 > 24h 或缺失 → 经典接管模式
    """
    freshness = check_reports_freshness()
    if freshness.get("a1_fresh"):
        return MODE_AI_DIRECTED
    else:
        return MODE_CLASSIC_TAKEOVER


# ── 模式状态管理 ────────────────────────────────────────────────────────

def get_current_state() -> Dict[str, Any]:
    """
    获取当前模式状态（带缓存）
    返回: {
        mode: ai_directed | classic_takeover,
        mode_label: 中文标签,
        since: 模式开始时间,
        reason: 切换原因,
        freshness: 研报新鲜度,
        ai_directive: AI 指令（AI 主导模式下）,
        last_checked: 上次检测时间,
        switch_count: 切换次数,
    }
    """
    global _state_cache, _cache_ts
    import time

    now_ts = time.time()
    if _state_cache and (now_ts - _cache_ts) < _CACHE_TTL:
        return _state_cache

    state = _load_json(MODE_STATE_FILE)

    # 如果没有状态，初始化
    if not state.get("mode"):
        mode = get_deterministic_mode()
        state = {
            "mode": mode,
            "mode_label": "AI 主导" if mode == MODE_AI_DIRECTED else "经典接管",
            "since": _now_iso(),
            "reason": "初始检测",
            "last_checked": _now_iso(),
            "switch_count": 0,
        }
        _save_json(MODE_STATE_FILE, state)
        _append_history({
            "action": "init",
            "mode": mode,
            "timestamp": _now_iso(),
            "reason": "初始检测",
        })

    # 补充新鲜度信息
    state["freshness"] = check_reports_freshness()

    # 补充 AI 指令
    if state["mode"] == MODE_AI_DIRECTED:
        state["ai_directive"] = get_ai_directive()
    else:
        state["ai_directive"] = None

    # 补充持仓冲突检测（AI 主导模式下）
    if state["mode"] == MODE_AI_DIRECTED and state.get("previous_mode") == MODE_CLASSIC_TAKEOVER:
        try:
            conflict = _check_position_conflict_on_switch()
            state["position_conflict"] = conflict
        except Exception:
            state["position_conflict"] = None

    _state_cache = state
    _cache_ts = now_ts
    return state


def check_and_switch_mode() -> Dict[str, Any]:
    """
    检测研报新鲜度，必要时切换模式
    返回切换结果
    """
    global _state_cache, _cache_ts

    current = _load_json(MODE_STATE_FILE)
    current_mode = current.get("mode", MODE_AI_DIRECTED)
    expected_mode = get_deterministic_mode()
    freshness = check_reports_freshness()

    if current_mode == expected_mode:
        # 模式未变，更新检测时间
        current["last_checked"] = _now_iso()
        current["freshness"] = freshness
        _save_json(MODE_STATE_FILE, current)
        _state_cache = current
        _cache_ts = __import__("time").time()
        return {
            "switched": False,
            "current_mode": current_mode,
            "reason": "模式未变化",
            "freshness": freshness,
        }

    # 模式切换
    old_mode = current_mode
    new_mode = expected_mode
    switch_count = current.get("switch_count", 0) + 1

    reason_parts = []
    if not freshness.get("a1_fresh"):
        a1_age = freshness.get("a1_daily", {}).get("age_hours", "未知")
        reason_parts.append(f"A1日报过期({a1_age}h)")
    else:
        reason_parts.append("A1日报恢复新鲜")

    reason = " → ".join(reason_parts) if reason_parts else "模式切换"

    # 回切检查（经典接管 → AI 主导）
    position_conflict = None
    if old_mode == MODE_CLASSIC_TAKEOVER and new_mode == MODE_AI_DIRECTED:
        position_conflict = _check_position_conflict_on_switch()
        if position_conflict:
            reason += f" | 持仓方向冲突: {position_conflict}"

    new_state = {
        "mode": new_mode,
        "mode_label": "AI 主导" if new_mode == MODE_AI_DIRECTED else "经典接管",
        "since": _now_iso(),
        "reason": reason,
        "last_checked": _now_iso(),
        "switch_count": switch_count,
        "previous_mode": old_mode,
    }

    _save_json(MODE_STATE_FILE, new_state)

    # 记录历史
    _append_history({
        "action": "switch",
        "old_mode": old_mode,
        "new_mode": new_mode,
        "timestamp": _now_iso(),
        "reason": reason,
        "switch_count": switch_count,
    })

    # 通知经典指标系统（预留接口）
    _notify_classic_system_mode_change(new_mode)

    # 清缓存
    _state_cache = None
    _cache_ts = 0

    return {
        "switched": True,
        "old_mode": old_mode,
        "new_mode": new_mode,
        "reason": reason,
        "switch_count": switch_count,
        "freshness": freshness,
        "position_conflict": position_conflict,
        "switch_type": "takeover" if old_mode == MODE_AI_DIRECTED and new_mode == MODE_CLASSIC_TAKEOVER else "revert",
    }


def _check_position_conflict_on_switch() -> Optional[str]:
    """
    检测回切时的持仓方向冲突
    经典接管模式下的持仓方向可能与新的 AI 指令方向不一致
    返回: 冲突描述（如 "BTC LONG vs AI short"），无冲突返回 None
    """
    try:
        from classic_executor import get_open_positions
        positions = get_open_positions()
        if not positions:
            return None

        directive = get_ai_directive()
        ai_direction = directive.get("direction")
        if not ai_direction:
            return None

        conflicts = []
        for p in positions:
            pos_side = p["pos_side"]
            if pos_side != ai_direction:
                conflicts.append(f"{p['symbol']} {pos_side.upper()} vs AI {ai_direction}")

        if conflicts:
            return ", ".join(conflicts)
        return None
    except Exception:
        return None


def _notify_classic_system_mode_change(new_mode: str):
    """
    通知经典指标系统模式变更（预留接口）
    通过写入配置文件的方式，Freqtrade 策略可读取
    """
    try:
        # 写入状态文件供经典指标系统读取
        classic_state_dir = CLASSIC_SYSTEM_DIR / "user_data" / "ai_integration"
        classic_state_dir.mkdir(parents=True, exist_ok=True)

        state_file = classic_state_dir / "mode_state.json"
        state = {
            "mode": new_mode,
            "updated_at": _now_iso(),
            "source": "dreambuddy_v2",
        }
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # 静默失败，不影响主流程


def set_mode_override(mode: str, reason: str = "手动切换") -> Dict[str, Any]:
    """
    手动强制切换模式（用于测试/调试）
    """
    global _state_cache, _cache_ts

    if mode not in [MODE_AI_DIRECTED, MODE_CLASSIC_TAKEOVER]:
        return {"error": f"无效模式: {mode}"}

    current = _load_json(MODE_STATE_FILE)
    old_mode = current.get("mode", "unknown")
    switch_count = current.get("switch_count", 0) + 1

    position_conflict = None
    if old_mode == MODE_CLASSIC_TAKEOVER and mode == MODE_AI_DIRECTED:
        position_conflict = _check_position_conflict_on_switch()
        if position_conflict:
            reason += f" | 持仓方向冲突: {position_conflict}"

    new_state = {
        "mode": mode,
        "mode_label": "AI 主导" if mode == MODE_AI_DIRECTED else "经典接管",
        "since": _now_iso(),
        "reason": reason,
        "last_checked": _now_iso(),
        "switch_count": switch_count,
        "previous_mode": old_mode,
        "manual_override": True,
        "position_conflict": position_conflict,
    }

    _save_json(MODE_STATE_FILE, new_state)

    _append_history({
        "action": "manual_switch",
        "old_mode": old_mode,
        "new_mode": mode,
        "timestamp": _now_iso(),
        "reason": reason,
        "switch_count": switch_count,
    })

    _notify_classic_system_mode_change(mode)

    _state_cache = None
    _cache_ts = 0

    switch_type = "takeover" if old_mode == MODE_AI_DIRECTED and mode == MODE_CLASSIC_TAKEOVER else "revert"

    return {
        "switched": True,
        "old_mode": old_mode,
        "new_mode": mode,
        "reason": reason,
        "switch_count": switch_count,
        "switch_type": switch_type,
        "position_conflict": position_conflict,
    }


# ── AI 指令管理 ─────────────────────────────────────────────────────────

def get_ai_directive() -> Dict[str, Any]:
    """
    获取当前 AI 指令
    """
    directive = _load_json(AI_DIRECTIVE_FILE)
    if not directive:
        # 默认指令
        directive = {
            "mode": MODE_AI_DIRECTED,
            "direction": None,
            "symbol_pool": ["BTC", "ETH"],
            "confidence": 0.5,
            "risk_level": "medium",
            "max_position_pct": 2.0,
            "blacklist": [],
            "generated_at": None,
            "source": "default",
        }
    return directive


def set_ai_directive(directive: Dict[str, Any]) -> Dict[str, Any]:
    """
    设置 AI 指令（由 Agent A / A1日报 / A6情报 生成）
    同时通知经典指标系统
    """
    current = get_ai_directive()
    updated = {**current, **directive}
    updated["updated_at"] = _now_iso()
    updated["source"] = updated.get("source", "ai")

    _save_json(AI_DIRECTIVE_FILE, updated)

    # 同步到经典指标系统
    _sync_ai_directive_to_classic(updated)

    return updated


def _sync_ai_directive_to_classic(directive: Dict[str, Any]):
    """
    将 AI 指令同步到经典指标系统（写入配置文件）
    Freqtrade 策略可以读取此文件来约束交易行为
    """
    try:
        classic_dir = CLASSIC_SYSTEM_DIR / "user_data" / "ai_integration"
        classic_dir.mkdir(parents=True, exist_ok=True)

        out_file = classic_dir / "ai_directive.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(directive, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ── 历史记录 ────────────────────────────────────────────────────────────

def get_mode_history(limit: int = 20) -> list:
    """获取模式切换历史"""
    entries = []
    try:
        if MODE_HISTORY_FILE.exists():
            with open(MODE_HISTORY_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except Exception:
                            pass
    except Exception:
        pass
    return entries[-limit:] if limit else entries


# ── 主入口（测试用） ────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="模式管理器")
    parser.add_argument("action", choices=["status", "check", "history", "set_ai", "force"],
                        help="操作类型")
    parser.add_argument("--mode", help="强制模式 (ai_directed / classic_takeover)")
    parser.add_argument("--direction", help="AI 指令方向 (long/short/neutral)")
    parser.add_argument("--symbols", help="AI 币种池，逗号分隔")
    args = parser.parse_args()

    if args.action == "status":
        state = get_current_state()
        print(json.dumps(state, ensure_ascii=False, indent=2, default=str))
    elif args.action == "check":
        result = check_and_switch_mode()
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    elif args.action == "history":
        history = get_mode_history(20)
        print(json.dumps(history, ensure_ascii=False, indent=2, default=str))
    elif args.action == "set_ai":
        directive = {}
        if args.direction:
            directive["direction"] = args.direction
        if args.symbols:
            directive["symbol_pool"] = args.symbols.split(",")
        result = set_ai_directive(directive)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    elif args.action == "force":
        if not args.mode:
            print("请指定 --mode")
            sys.exit(1)
        result = set_mode_override(args.mode, "命令行手动切换")
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
