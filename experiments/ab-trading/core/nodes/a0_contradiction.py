"""
A0 矛盾论节点
调用 dream-contradiction-theory SKILL 方法论
遵循"调用的不重复建设"原则

SKILL 路径: 6-TRADING/skills/dream-contradiction-theory/SKILL.md
模块路径: core.modules.skill_loader
"""

from typing import Dict, Any
from pathlib import Path

try:
    from core.modules.skill_loader import execute_skill
    _SKILL_OK = True
except ImportError:
    _SKILL_OK = False
    execute_skill = None


def execute(mkt: Dict, memory: Dict, data: Dict) -> Dict[str, Any]:
    """
    执行 A0 矛盾论分析
    
    优先调用 SKILL 方法论，失败时使用本地降级
    
    Args:
        mkt: 市场数据
        memory: 记忆数据
        data: 节点间共享数据
    
    Returns:
        {
            "node": "A0_矛盾论",
            "direction": "LONG" | "SHORT" | "HOLD",
            "confidence": 0.0-1.0,
            "rationale": [...],
            "data": {...矛盾分析详情...},
            "skill_used": bool,
            "skill_version": str,
        }
    """
    reasoning = []
    
    # ── 调用 SKILL 方法论 ────────────────────────────────────────────
    skill_used = False
    skill_version = "unknown"
    skill_result = None
    
    if _SKILL_OK:
        try:
            # 确定项目根目录
            project_root = Path(__file__).parent.parent.parent.parent.parent
            
            skill_result = execute_skill(
                "dream-contradiction-theory",
                {"mkt": mkt, "memory": memory, "data": data},
                project_root=str(project_root),
            )
            skill_used = skill_result.used_skill
            skill_version = skill_result.version
            
            reasoning.append(f"[A0矛盾论] SKILL v{skill_version} | 执行阶段: {len(skill_result.phases_executed)}")
            reasoning.extend(skill_result.rationale)
            
            return {
                "node": "A0_矛盾论",
                "direction": skill_result.direction,
                "confidence": skill_result.confidence,
                "rationale": reasoning,
                "skill_used": skill_used,
                "skill_version": skill_version,
                "phases_executed": skill_result.phases_executed,
                "data": skill_result.data,
            }
        except Exception as e:
            reasoning.append(f"[A0矛盾论] SKILL调用失败: {str(e)[:50]}，使用本地降级")
    
    # ── 本地降级实现 ─────────────────────────────────────────────────
    price  = mkt.get("price", 0)
    rsi    = mkt.get("rsi14", 50)
    ema20  = mkt.get("ema20", price)
    ema50  = mkt.get("ema50", price)
    ema200 = mkt.get("ema200", price)
    funding = mkt.get("funding_rate", 0)
    ch24   = mkt.get("change_24h", 0)
    vol_ratio = mkt.get("vol_ratio", 1.0)
    
    contradictions = []
    bull_count = 0
    bear_count = 0
    conflict_count = 0
    
    # 维度1: 资金面
    fund_dominant = "BULL" if funding < -0.0001 else ("BEAR" if funding > 0.0001 else "NEUTRAL")
    if fund_dominant == "BULL":
        bull_count += 1
    elif fund_dominant == "BEAR":
        bear_count += 1
    else:
        conflict_count += 1
    contradictions.append({
        "dimension": "C1_资金面",
        "dominance": fund_dominant,
        "strength": 0.5,
    })
    
    # 维度2: 情绪面
    sent_dominant = "BEAR" if rsi > 70 else ("BULL" if rsi < 30 else "NEUTRAL")
    if sent_dominant == "BULL":
        bull_count += 1
    elif sent_dominant == "BEAR":
        bear_count += 1
    else:
        conflict_count += 1
    contradictions.append({
        "dimension": "C2_情绪面",
        "dominance": sent_dominant,
        "strength": 0.5,
    })
    
    # 维度3: 技术面
    tech_dominant = "BULL" if price > ema200 and ema20 > ema50 else \
                    "BEAR" if price < ema200 and ema20 < ema50 else "NEUTRAL"
    if tech_dominant == "BULL":
        bull_count += 1
    elif tech_dominant == "BEAR":
        bear_count += 1
    else:
        conflict_count += 1
    contradictions.append({
        "dimension": "C3_技术面",
        "dominance": tech_dominant,
        "strength": 0.6,
    })
    
    # 维度4: 趋势面
    trend_dominant = "BULL" if ch24 > 1 and price > ema20 else \
                     "BEAR" if ch24 < -1 and price < ema20 else "NEUTRAL"
    if trend_dominant == "BULL":
        bull_count += 1
    elif trend_dominant == "BEAR":
        bear_count += 1
    else:
        conflict_count += 1
    contradictions.append({
        "dimension": "C6_趋势面",
        "dominance": trend_dominant,
        "strength": 0.5,
    })
    
    # 确定主要矛盾
    primary = max(contradictions, key=lambda x: x["strength"])
    dominant_force = "BULL" if bull_count > bear_count else \
                     "BEAR" if bear_count > bull_count else "NEUTRAL"
    
    total = bull_count + bear_count + conflict_count
    confidence = 0.3 + (max(bull_count, bear_count) / total) * 0.5 if total > 0 else 0.4
    
    direction = "LONG" if dominant_force == "BULL" else \
                "SHORT" if dominant_force == "BEAR" else "HOLD"
    
    reasoning.append(f"[A0矛盾论] 本地降级 | 4维度分析")
    reasoning.append(f"  多:{bull_count} 空:{bear_count} 冲突:{conflict_count}")
    reasoning.append(f"  主导力量: {dominant_force}")
    reasoning.append(f"  主要矛盾: {primary['dimension']} ({primary['dominance']})")
    
    return {
        "node": "A0_矛盾论",
        "direction": direction,
        "confidence": round(confidence, 3),
        "rationale": reasoning,
        "skill_used": False,
        "skill_version": "fallback",
        "data": {
            "contradictions": contradictions,
            "primary_contradiction": primary,
            "bull_count": bull_count,
            "bear_count": bear_count,
            "conflict_count": conflict_count,
            "dominant_force": dominant_force,
        },
    }


def a0_execute(mkt: Dict, memory: Dict, data: Dict) -> Dict[str, Any]:
    return execute(mkt, memory, data)
