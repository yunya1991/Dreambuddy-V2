#!/usr/bin/env python3
"""
模型评分调度器 v1.0
===================
根据任务类型和模型注册表，选择最优可用模型。
无可用模型满足阈值时，回退至 base_fallback。

调用方式（Hermes 或 Python）:
    from model_dispatcher import dispatch, get_task_info

    model = dispatch("synthesis_a3")
    # → "deepseek-v4"（当前唯一可用）
    # → 将来接入更强模型后自动升级，无需改此文件

独立运行: python model_dispatcher.py
"""

import json
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional


# ── 注册表路径 ──────────────────────────────────────────────────────────────

def _registry_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "model_registry.json")


def load_registry() -> Dict:
    with open(_registry_path(), "r", encoding="utf-8") as f:
        return json.load(f)


# ── 任务类型 × 能力阈值表 ────────────────────────────────────────────────────
# 每个任务类型定义各维度的最低分要求（0 = 无要求）
# 新增任务类型：在此表追加一行，无需改其他逻辑

TASK_THRESHOLDS: Dict[str, Dict] = {

    # ── 纯代码，不需要模型 ───────────────────────────────────────────────────
    "gate_check": {
        "_code_only": True,
        "description": "门禁轮询，annotation 新鲜度检查",
        "skill": None,
    },

    # ── 数据采集层（低智能要求）───────────────────────────────────────────────
    "data_collection": {
        "reasoning_depth":    1,
        "chinese_finance":    1,
        "structured_output":  2,
        "instruction_follow": 2,
        "description": "Tavily 搜索 + 结构化数据提取",
        "skill": None,
    },

    # ── 单维度 annotation 更新（中等要求）───────────────────────────────────
    "dim_annotation_cycle": {
        "reasoning_depth":    3,
        "chinese_finance":    4,
        "structured_output":  4,
        "instruction_follow": 4,
        "description": "B 减半/库存周期 annotation 更新",
        "skill": "/screen1-halving-cycle",
    },
    "dim_annotation_miner": {
        "reasoning_depth":    3,
        "chinese_finance":    4,
        "structured_output":  4,
        "instruction_follow": 4,
        "description": "C 矿工经济 annotation 更新",
        "skill": "/screen1-miner-economics",
    },
    "dim_annotation_onchain": {
        "reasoning_depth":    3,
        "chinese_finance":    4,
        "structured_output":  4,
        "instruction_follow": 4,
        "description": "D 链上估值 annotation 更新",
        "skill": "/screen1-onchain-valuation",
    },
    "dim_annotation_macro": {
        "reasoning_depth":    3,
        "chinese_finance":    4,
        "structured_output":  4,
        "instruction_follow": 4,
        "description": "E 宏观金融 annotation 更新（依赖链起点）",
        "skill": "/screen1-macro-finance",
    },
    "dim_annotation_cross_market": {
        "reasoning_depth":    3,
        "chinese_finance":    4,
        "structured_output":  4,
        "instruction_follow": 4,
        "description": "F 跨市场周期 annotation 更新（依赖 E 完成）",
        "skill": "/screen1-cross-market",
        "depends_on": ["dim_annotation_macro"],
    },

    # ── A 系列合成层（最高要求，动态选最强可用模型）────────────────────────────
    "synthesis_a1": {
        "reasoning_depth":    5,
        "chinese_finance":    4,
        "structured_output":  3,
        "instruction_follow": 5,
        "description": "A1 矛盾论深度研究（dream-strategy-research）",
        "skill": "/dream-strategy-research",
        "prefer_highest": True,
    },
    "synthesis_a2": {
        "reasoning_depth":    5,
        "chinese_finance":    4,
        "structured_output":  3,
        "instruction_follow": 5,
        "description": "A2 第一性原理分析（dream-first-principles）",
        "skill": "/dream-first-principles",
        "prefer_highest": True,
    },
    "synthesis_a3": {
        "reasoning_depth":    5,
        "chinese_finance":    4,
        "structured_output":  4,
        "instruction_follow": 5,
        "description": "A3 沙盘推演+贝叶斯校准（dream-tactical-validator）",
        "skill": "/dream-tactical-validator",
        "prefer_highest": True,
    },
    "synthesis_cross_asset": {
        "reasoning_depth":    4,
        "chinese_finance":    5,
        "structured_output":  5,
        "instruction_follow": 5,
        "description": "跨资产配置输出（screen1-cross-asset）",
        "skill": "/screen1-cross-asset",
        "prefer_highest": True,
    },

    # ── 写入层（极低要求）─────────────────────────────────────────────────────
    "json_write": {
        "reasoning_depth":    1,
        "chinese_finance":    1,
        "structured_output":  5,
        "instruction_follow": 3,
        "description": "格式化输出并写入 annotation JSON 文件",
        "skill": None,
    },
}

# 参与调度评分的维度（忽略 description / skill / depends_on / prefer_highest）
_SCORE_DIMS = {"reasoning_depth", "chinese_finance", "structured_output", "instruction_follow"}


# ── 核心调度函数 ──────────────────────────────────────────────────────────────

def dispatch(task_type: str, registry: Optional[Dict] = None) -> str:
    """
    根据任务类型返回最优可用模型名称。

    规则:
      1. task_type = gate_check → 返回 "__code__"（调用方直接用代码）
      2. 筛选 available=True 且所有维度 >= 阈值的模型
      3. prefer_highest=True 时，优先 reasoning_depth 最高；同分取 cost_tier 最低
      4. 否则直接取 cost_tier 最低（省钱优先）
      5. 无候选 → 返回 base_fallback
    """
    if registry is None:
        registry = load_registry()

    threshold = TASK_THRESHOLDS.get(task_type)
    if threshold is None:
        return registry.get("base_fallback", "deepseek-v4")

    if threshold.get("_code_only"):
        return "__code__"

    prefer_highest = threshold.get("prefer_highest", False)
    req = {k: v for k, v in threshold.items() if k in _SCORE_DIMS}

    candidates = []
    for model_name, meta in registry["models"].items():
        if not meta.get("available"):
            continue
        scores = meta.get("scores", {})
        if all(scores.get(dim, 0) >= req_score for dim, req_score in req.items()):
            candidates.append((model_name, meta))

    if not candidates:
        return registry.get("base_fallback", "deepseek-v4")

    if prefer_highest:
        # 选 reasoning_depth 最高，同分取 cost_tier 最低
        return min(
            candidates,
            key=lambda x: (-x[1]["scores"].get("reasoning_depth", 0), x[1]["cost_tier"])
        )[0]
    else:
        # 省钱优先
        return min(candidates, key=lambda x: x[1]["cost_tier"])[0]


def get_task_info(task_type: str) -> Dict:
    """返回任务元信息（description / skill / depends_on）."""
    t = TASK_THRESHOLDS.get(task_type, {})
    return {
        "task_type":   task_type,
        "description": t.get("description", ""),
        "skill":       t.get("skill"),
        "depends_on":  t.get("depends_on", []),
        "prefer_highest": t.get("prefer_highest", False),
        "code_only":   t.get("_code_only", False),
    }


def dispatch_screen1_plan(registry: Optional[Dict] = None) -> List[Dict]:
    """
    生成 Screen 1 完整执行计划（任务列表 + 每个任务对应的模型）。
    Hermes 可直接消费此列表驱动任务队列。

    返回:
    [
      {"step": 1, "task_type": "gate_check",    "model": "__code__",    "skill": None,    "depends_on": []},
      {"step": 2, "task_type": "dim_annotation_cycle",  "model": "deepseek-v4", ...},
      ...
    ]
    """
    if registry is None:
        registry = load_registry()

    screen1_tasks = [
        "gate_check",
        "dim_annotation_cycle",
        "dim_annotation_miner",
        "dim_annotation_onchain",
        "dim_annotation_macro",
        "dim_annotation_cross_market",   # 依赖 macro 完成
        "synthesis_a1",
        "synthesis_a2",
        "synthesis_a3",
        "synthesis_cross_asset",
    ]

    plan = []
    for i, tt in enumerate(screen1_tasks, start=1):
        model = dispatch(tt, registry)
        info  = get_task_info(tt)
        plan.append({
            "step":       i,
            "task_type":  tt,
            "model":      model,
            "skill":      info["skill"],
            "description": info["description"],
            "depends_on": info["depends_on"],
        })
    return plan


def update_model_availability(model_name: str, available: bool) -> None:
    """Hermes 检测到模型上线/下线时调用，更新注册表."""
    reg = load_registry()
    if model_name not in reg["models"]:
        raise ValueError(f"模型 {model_name!r} 不在注册表中")
    reg["models"][model_name]["available"] = available
    reg["updated"] = datetime.now().strftime("%Y-%m-%d")
    with open(_registry_path(), "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=2)


def update_process_d_score(model_name: str, accuracy: float) -> None:
    """ProcessD 复盘后写回预测准确率，供未来自动评分演进."""
    if not (0.0 <= accuracy <= 1.0):
        raise ValueError("accuracy 必须在 [0, 1]")
    reg = load_registry()
    if model_name not in reg["models"]:
        raise ValueError(f"模型 {model_name!r} 不在注册表中")
    reg["models"][model_name]["process_d_accuracy"] = round(accuracy, 4)
    reg["models"][model_name]["last_evaluated"]     = datetime.now().strftime("%Y-%m-%d")
    reg["updated"] = datetime.now().strftime("%Y-%m-%d")
    with open(_registry_path(), "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=2)


# ── 格式化报告 ─────────────────────────────────────────────────────────────

def format_dispatch_plan(plan: List[Dict]) -> str:
    lines = [
        "=" * 68,
        "  Screen 1 模型调度执行计划",
        "=" * 68,
        f"  {'步骤':4s}  {'任务类型':32s}  {'模型':20s}  {'SKILL'}",
        "─" * 68,
    ]
    for p in plan:
        dep = f"  (依赖: {','.join(p['depends_on'])})" if p["depends_on"] else ""
        skill_label = p["skill"] or "—"
        lines.append(
            f"  {p['step']:2d}.   {p['task_type']:32s}  {p['model']:20s}  {skill_label}{dep}"
        )
    lines.append("=" * 68)
    return "\n".join(lines)


# ── 独立运行 ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    reg = load_registry()
    print(f"\n注册表版本: {reg['registry_version']}  更新: {reg['updated']}")
    print(f"base_fallback: {reg['base_fallback']}\n")

    print("可用模型:")
    for name, meta in reg["models"].items():
        status = "✅" if meta["available"] else "—"
        print(f"  {status} {name:20s}  cost_tier={meta['cost_tier']}  "
              f"reasoning={meta['scores']['reasoning_depth']}")

    plan = dispatch_screen1_plan(reg)
    print()
    print(format_dispatch_plan(plan))
