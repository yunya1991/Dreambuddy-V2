"""战略层阶段4：生产灰度管理

功能：
1. 检查影子模式运行状态
2. 收集影子数据统计（war_state 分布、cap 分布、IC 加权分数）
3. 评估晋升门槛（实盘天数、FinBERT A/B 样本、IC 重训练次数）
4. 灰度推进工具（war_state → style_mask → position_cap）

用法：
    python stage4_grayscale_manager.py --status     # 查看状态
    python stage4_grayscale_manager.py --gate-check  # 晋升门槛检查
    python stage4_grayscale_manager.py --promote war_state  # 推进 war_state 灰度
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent.parent
_RUNTIME = _REPO / "11-易经推理系统" / "scripts" / "memory_l4" / "runtime"
_STATE_CACHE = _RUNTIME / "five_domain_state.json"
_SHADOW_LOG = _RUNTIME / "shadow_param_log.jsonl"
_AB_LOG = _RUNTIME / "finbert_ab_records.jsonl"
_IC_WEIGHTS = _RUNTIME / "five_domain_subindicator_ic_weights.json"
_PROMOTE_STATE = _RUNTIME / "stage4_grayscale_state.json"

if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


# ============================================================
# 阶段4 灰度阶段定义
# ============================================================
GRAYSCALE_STAGES = {
    "shadow": {"desc": "影子模式（仅记录，不影响实盘）", "gate": "实盘影子数据积累"},
    "war_state": {"desc": "开启 war_state 拦截（FREEZE/COOLDOWN/ALLOW）", "gate": "≥30天影子+war_state命中率≥70%"},
    "style_mask": {"desc": "开启 style_mask 过滤（策略白名单）", "gate": "war_state稳定≥14天"},
    "position_cap": {"desc": "开启 position_cap 仓位上限", "gate": "style_mask稳定≥14天"},
    "full": {"desc": "全部开关生效", "gate": "position_cap稳定≥14天+回撤≤基线1.05×"},
}

GRAYSCALE_ORDER = ["shadow", "war_state", "style_mask", "position_cap", "full"]


def load_jsonl(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                records.append(json.loads(line))
            except Exception:
                pass
    return records


def load_promote_state() -> Dict:
    if _PROMOTE_STATE.exists():
        with open(_PROMOTE_STATE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"current_stage": "shadow", "promotions": []}


def save_promote_state(state: Dict) -> None:
    _RUNTIME.mkdir(parents=True, exist_ok=True)
    with open(_PROMOTE_STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def get_shadow_stats() -> Dict[str, Any]:
    """收集影子数据统计（从 five_domain_state.json + shadow_param_log）。"""
    # 从 five_domain_state.json 读取最新状态
    latest = {}
    if _STATE_CACHE.exists():
        try:
            with open(_STATE_CACHE, "r", encoding="utf-8") as f:
                latest = json.load(f)
        except Exception:
            pass

    # 从 shadow_param_log.jsonl 读取历史
    records = load_jsonl(_SHADOW_LOG)

    stats = {
        "count": len(records),
        "latest_updated": latest.get("_meta", {}).get("updated_date", "N/A"),
        "latest_war_state": latest.get("war_state", {}),
        "latest_cap": latest.get("aggregate_position_cap_pct", {}),
        "latest_five_scores": latest.get("five_scores", {}),
        "by_class": {},
    }

    for cls in ("crypto_usdt", "us_stock", "precious_metal"):
        cls_recs = [r for r in records if r.get("asset_class") == cls]
        if cls_recs:
            war_states = [r.get("fd_war_state", "UNKNOWN") for r in cls_recs if "fd_war_state" in r]
            from collections import Counter
            stats["by_class"][cls] = {
                "count": len(cls_recs),
                "war_state_dist": dict(Counter(war_states)) if war_states else {},
            }
    return stats


def get_ab_stats() -> Dict[str, Any]:
    """FinBERT A/B 统计。"""
    records = load_jsonl(_AB_LOG)
    if not records:
        return {"count": 0, "message": "暂无 A/B 数据"}

    stats = {"count": len(records), "by_class": {}}
    for cls in ("crypto_usdt", "us_stock", "precious_metal"):
        diffs = [r[cls]["sentiment_diff"] for r in records
                 if cls in r and isinstance(r[cls], dict) and r[cls].get("sentiment_diff") is not None]
        if diffs:
            import statistics
            stats["by_class"][cls] = {
                "samples": len(diffs),
                "mean_diff": round(statistics.mean(diffs), 4),
                "std_diff": round(statistics.stdev(diffs), 4) if len(diffs) > 1 else 0.0,
            }
    return stats


def check_gates() -> Dict[str, Any]:
    """检查晋升门槛。"""
    state = load_promote_state()
    shadow_stats = get_shadow_stats()
    ab_stats = get_ab_stats()

    # 影子数据天数
    shadow_days = shadow_stats.get("count", 0)

    # FinBERT A/B 样本
    ab_samples = sum(v.get("samples", 0) for v in ab_stats.get("by_class", {}).values())

    # IC 重训练文件时间
    ic_retrain_count = 0
    if _IC_WEIGHTS.exists():
        ic_mtime = datetime.fromtimestamp(_IC_WEIGHTS.stat().st_mtime)
        # 简单用文件修改次数近似，实际需记录重训练日志
        ic_retrain_count = 1

    gates = {
        "shadow_days": {"value": shadow_days, "threshold": 90, "pass": shadow_days >= 90},
        "finbert_ab_samples": {"value": ab_samples, "threshold": 30, "pass": ab_samples >= 30},
        "ic_retrain_count": {"value": ic_retrain_count, "threshold": 2, "pass": ic_retrain_count >= 2},
    }

    all_pass = all(g["pass"] for g in gates.values())
    return {
        "current_stage": state["current_stage"],
        "gates": gates,
        "all_pass": all_pass,
        "next_stage": GRAYSCALE_ORDER[GRAYSCALE_ORDER.index(state["current_stage"]) + 1]
                      if state["current_stage"] in GRAYSCALE_ORDER[:-1] else "full",
    }


def promote_stage(stage: str) -> Dict[str, Any]:
    """推进到指定灰度阶段。"""
    state = load_promote_state()
    current = state["current_stage"]

    if stage not in GRAYSCALE_STAGES:
        return {"error": f"未知阶段: {stage}，可选: {list(GRAYSCALE_STAGES.keys())}"}

    current_idx = GRAYSCALE_ORDER.index(current)
    target_idx = GRAYSCALE_ORDER.index(stage)

    if target_idx <= current_idx:
        return {"error": f"不能回退或重复推进，当前={current}，目标={stage}"}

    # 检查门槛
    gate_result = check_gates()
    if not gate_result["all_pass"]:
        return {
            "error": "晋升门槛未通过",
            "gates": gate_result["gates"],
            "hint": "通过所有门槛后再执行 --promote",
        }

    # 推进
    state["current_stage"] = stage
    state["promotions"].append({
        "stage": stage,
        "timestamp": datetime.now().isoformat(),
        "gates": gate_result["gates"],
    })
    save_promote_state(state)

    return {
        "success": True,
        "stage": stage,
        "desc": GRAYSCALE_STAGES[stage]["desc"],
        "next_action": f"请手动在 polling_trader.py 中开启 enable_five_domain_{stage}（如需）",
    }


def print_status() -> None:
    state = load_promote_state()
    shadow_stats = get_shadow_stats()
    ab_stats = get_ab_stats()

    print("=" * 60)
    print(f"战略层阶段4 灰度状态")
    print("=" * 60)
    print(f"当前阶段: {state['current_stage']} — {GRAYSCALE_STAGES[state['current_stage']]['desc']}")
    print()
    print(f"影子数据更新: {shadow_stats.get('latest_updated', 'N/A')}")
    print(f"最新 war_state: {shadow_stats.get('latest_war_state', {})}")
    print(f"最新 cap: {shadow_stats.get('latest_cap', {})}")
    fs = shadow_stats.get('latest_five_scores', {})
    if fs:
        for cls, scores in fs.items():
            print(f"  {cls}: dao={scores.get('dao')} tian={scores.get('tian')} di={scores.get('di')}")
    if shadow_stats.get('count', 0) > 0:
        print(f"历史影子日志: {shadow_stats['count']} 条")
    print()
    print(f"FinBERT A/B: {ab_stats.get('count', 0)} 天记录")
    if "by_class" in ab_stats:
        for cls, s in ab_stats["by_class"].items():
            print(f"  {cls}: {s.get('samples', 0)} 样本, 均值差异={s.get('mean_diff', 'N/A')}")
    print()
    print("灰度阶段:")
    for s in GRAYSCALE_ORDER:
        marker = "◀ 当前" if s == state["current_stage"] else ""
        print(f"  [{s}] {GRAYSCALE_STAGES[s]['desc']} {marker}")
    print()


def print_gate_check() -> None:
    result = check_gates()
    print("=" * 60)
    print("晋升门槛检查")
    print("=" * 60)
    print(f"当前阶段: {result['current_stage']}")
    print(f"下一阶段: {result['next_stage']}")
    print()
    for name, g in result["gates"].items():
        status = "✅" if g["pass"] else "❌"
        print(f"  {status} {name}: {g['value']} / {g['threshold']}")
    print()
    if result["all_pass"]:
        print(f"✅ 全部门槛通过，可推进到 {result['next_stage']}")
        print(f"   执行: python stage4_grayscale_manager.py --promote {result['next_stage']}")
    else:
        print("❌ 部分门槛未通过，继续积累数据")


if __name__ == "__main__":
    if "--status" in sys.argv:
        print_status()
    elif "--gate-check" in sys.argv:
        print_gate_check()
    elif "--promote" in sys.argv:
        idx = sys.argv.index("--promote")
        if idx + 1 < len(sys.argv):
            result = promote_stage(sys.argv[idx + 1])
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("用法: --promote <stage>")
    else:
        print_status()
        print()
        print_gate_check()
