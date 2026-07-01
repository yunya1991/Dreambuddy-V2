"""
A2 第一性原理分析节点
调用 dream-first-principles SKILL 方法论（v2.6.1）
遵循"调用的不重复建设"原则

SKILL 路径: 6-TRADING/skills/dream-first-principles/SKILL.md
模块路径: core.modules.skill_loader

SKILL 方法论:
- Phase 1: 阻力最小路径计算（4分量加权）
- Phase 2: MA轨迹法趋势追踪
- Phase 3: 矛盾处理2.0
- Phase 4: 逆向信号补偿机制
- Phase 5: 综合评估
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
    执行 A2 第一性原理分析（含 A0 矛盾排序）
    
    优先调用 dream-first-principles SKILL 方法论
    失败时使用本地降级实现
    
    Args:
        mkt: 市场数据
        memory: 记忆数据
        data: 节点间共享数据（从前序节点累积，含 A0 数据）
    
    Returns:
        {
            "node": "A2_分析(含A0)",
            "direction": "LONG" | "SHORT" | "HOLD",
            "confidence": 0.0-1.0,
            "rationale": [...],
            "data": { "a0": {...}, "a2": {...} },
            "skill_used": bool,
            "skill_version": str,
        }
    """
    reasoning = []
    
    # ── 从共享数据中获取 A0 结果 ─────────────────────────────────────
    a0_data = data.get("a0", {})
    if not a0_data:
        # 尝试从其他节点数据中找
        for key, val in data.items():
            if isinstance(val, dict) and "dominant_force" in val:
                a0_data = val
                break
    
    # ── 调用 SKILL 方法论 ──────────────────────────────────────────
    skill_used = False
    skill_version = "unknown"
    skill_result = None
    
    if _SKILL_OK:
        try:
            project_root = Path(__file__).parent.parent.parent.parent.parent
            
            skill_result = execute_skill(
                "dream-first-principles",
                {
                    "mkt": mkt,
                    "memory": memory,
                    "data": data,
                    "a0": a0_data,
                },
                project_root=str(project_root),
            )
            skill_used = skill_result.used_skill
            skill_version = skill_result.version
            
            reasoning.append(f"[A2第一性原理] SKILL v{skill_version}")
            reasoning.append(f"  执行阶段: {len(skill_result.phases_executed)} 个 Phase")
            reasoning.extend(skill_result.rationale)
            
            return {
                "node": "A2_分析(含A0)",
                "direction": skill_result.direction,
                "confidence": skill_result.confidence,
                "rationale": reasoning,
                "skill_used": skill_used,
                "skill_version": skill_version,
                "phases_executed": skill_result.phases_executed,
                "data": {
                    "a0": a0_data,
                    "a2": skill_result.data,
                }
            }
        except Exception as e:
            reasoning.append(f"[A2第一性原理] SKILL调用失败: {str(e)[:60]}，使用本地降级")
    
    # ── 本地降级实现（简化版第一性原理） ────────────────────────────
    price  = mkt.get("price", 0)
    rsi    = mkt.get("rsi14", 50)
    ema20  = mkt.get("ema20", price)
    ema50  = mkt.get("ema50", price)
    ema200 = mkt.get("ema200", price)
    atr    = mkt.get("atr14", price * 0.02)
    funding = mkt.get("funding_rate", 0)
    ch24   = mkt.get("change_24h", 0)
    vol_ratio = mkt.get("vol_ratio", 1.0)
    regime = mkt.get("regime", "RANGE")
    
    a2_principles = []
    
    # 原理1: 市场结构分析
    if regime == "TREND_UP":
        structure = "上升趋势"
        if price > ema20:
            a2_principles.append(("多头结构", 0.65, "价格在 EMA20 上方，趋势健康"))
        else:
            a2_principles.append(("多头结构", 0.50, "价格在 EMA20 下方，趋势可能转弱"))
    elif regime == "TREND_DOWN":
        structure = "下降趋势"
        if price < ema20:
            a2_principles.append(("空头结构", 0.65, "价格在 EMA20 下方，趋势健康"))
        else:
            a2_principles.append(("空头结构", 0.50, "价格在 EMA20 上方，趋势可能转弱"))
    else:
        structure = "震荡市"
        a2_principles.append(("震荡结构", 0.45, "无明显趋势，等待突破确认"))
    
    # 原理2: 资金费率分析
    if funding < -0.005:
        a2_principles.append(("资金费率多头", 0.60, f"负费率{funding*100:.2f}%=空头付多头"))
    elif funding > 0.005:
        a2_principles.append(("资金费率空头", 0.60, f"正费率{funding*100:.2f}%=多头付空头"))
    
    # 原理3: RSI 动能分析
    if 40 <= rsi <= 60:
        a2_principles.append(("RSI 中性", 0.50, f"RSI={rsi:.1f} 无明显超买超卖"))
    elif rsi > 70:
        a2_principles.append(("RSI 超买", 0.35, f"RSI={rsi:.1f} 上涨动能可能衰竭"))
    elif rsi < 30:
        a2_principles.append(("RSI 超卖", 0.55, f"RSI={rsi:.1f} 反弹概率增加"))
    
    # 原理4: 风险收益比
    sl_pct = atr / price if price > 0 else 0.03
    if sl_pct > 0.05:
        a2_principles.append(("高波动风险", 0.40, f"ATR={atr:.4f} 波动较大"))
    
    # 综合评分
    valid_principles = [p for p in a2_principles if p[1] >= 0.5]
    if not valid_principles:
        a2_dir = "HOLD"
        a2_conf = 0.45
        reasoning.append("[A2本地降级] 无强信号，等待")
    else:
        long_scores = [p[1] for p in valid_principles if "多头" in p[0] or "超卖" in p[0]]
        short_scores = [p[1] for p in valid_principles if "空头" in p[0] or "超买" in p[0]]
        
        long_avg = sum(long_scores) / len(long_scores) if long_scores else 0
        short_avg = sum(short_scores) / len(short_scores) if short_scores else 0
        
        if long_avg > short_avg + 0.05:
            a2_dir = "LONG"
            a2_conf = min(long_avg, 0.75)
        elif short_avg > long_avg + 0.05:
            a2_dir = "SHORT"
            a2_conf = min(short_avg, 0.75)
        else:
            a2_dir = "HOLD"
            a2_conf = 0.50
    
    for p in a2_principles:
        reasoning.append(f"  - {p[2]}")
    
    # A0 + A2 融合
    a0_dir = "LONG" if a0_data.get("dominant_force") == "BULL" else \
             "SHORT" if a0_data.get("dominant_force") == "BEAR" else "HOLD"
    
    if a0_dir != "HOLD" and a2_dir != "HOLD":
        if a0_dir == a2_dir:
            merged_dir = a2_dir
            merged_conf = round((a2_conf + a0_data.get("confidence", 0.45)) / 2 + 0.05, 3)
            reasoning.append(f"[融合] ✅ A0({a0_dir}) + A2({a2_dir}) 一致")
        else:
            merged_dir = a2_dir
            merged_conf = round((a2_conf + a0_data.get("confidence", 0.45)) / 2 - 0.08, 3)
            reasoning.append(f"[融合] ⚠️ A0({a0_dir}) vs A2({a2_dir}) 冲突")
    elif a2_dir != "HOLD":
        merged_dir = a2_dir
        merged_conf = a2_conf
    else:
        merged_dir = a0_dir if a0_dir != "HOLD" else "HOLD"
        merged_conf = max(a2_conf, a0_data.get("confidence", 0.45))
    
    merged_conf = max(min(merged_conf, 0.90), 0.25)
    
    reasoning.insert(0, f"[A2第一性原理] 本地降级 | 结构={structure}")
    
    return {
        "node": "A2_分析(含A0)",
        "direction": merged_dir,
        "confidence": round(merged_conf, 3),
        "rationale": reasoning,
        "skill_used": False,
        "skill_version": "fallback",
        "data": {
            "a0": a0_data,
            "a2": {
                "structure": structure,
                "principles": a2_principles,
                "direction": a2_dir,
                "confidence": a2_conf,
            }
        }
    }


def a2_execute(mkt: Dict, memory: Dict, data: Dict) -> Dict[str, Any]:
    return execute(mkt, memory, data)
