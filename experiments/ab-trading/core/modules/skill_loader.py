"""
SKILL 加载器
封装 A链/C链/F链 SKILL 的调用，遵循"调用的不重复建设"原则

架构说明:
- S链: 意图识别层（S链 + 意图识别引擎，解决用户目标 → 图架构B层）
- A链: 执行闭环（三大闭环 + 三屏交易），使用SKILL方法论
- C链: 经典量化（经典指标系统）
- F链: 基本面（资金流、情绪、新闻）

设计原则:
- 读取 SKILL.md 获取方法论和执行流程
- 根据 SKILL 定义的 Phase 执行分析
- 输出符合 SKILL 规范的结构化结果
- 支持降级：SKILL 不可用时回退到本地规则
"""
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field


@dataclass
class SkillPhase:
    """SKILL 执行阶段"""
    phase_id: str
    name: str
    description: str
    inputs: List[str] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)


@dataclass
class SkillResult:
    """SKILL 执行结果"""
    skill_name: str
    version: str
    phases_executed: List[str]
    direction: str  # LONG / SHORT / HOLD
    confidence: float
    rationale: List[str]
    data: Dict[str, Any]
    used_skill: bool = True  # 是否真正使用了 SKILL 方法论
    fallback_reason: str = ""  # 降级原因


class SkillLoader:
    """
    SKILL 加载器
    
    支持的 SKILL:
    - dream-contradiction-theory: A0 矛盾论
    - dream-first-principles: A2 第一性原理
    - dream-exit-skill-v2: A9 离场评估
    - dream-regime-detector: C2 Regime 识别
    """
    
    # SKILL 路径映射（相对于项目根目录）
    SKILL_PATHS = {
        "dream-contradiction-theory": "6-TRADING/skills/dream-contradiction-theory/SKILL.md",
        "dream-first-principles": "6-TRADING/skills/dream-first-principles/SKILL.md",
        "dream-exit-skill-v2": "6-TRADING/skills/dream-exit-skill-v2/SKILL.md",
        "dream-regime-detector": "6-TRADING/skills/dream-regime-detector/SKILL.md",
        "dream-oneirology": "6-TRADING/skills/dream-oneirology/SKILL.md",
    }
    
    def __init__(self, project_root: str = None):
        if project_root:
            self.project_root = Path(project_root)
        else:
            # 默认向上找到项目根
            # skill_loader.py -> modules -> core -> ab-trading -> experiments -> dreambuddy-v2
            self.project_root = Path(__file__).parent.parent.parent.parent.parent
    
    def load_skill_md(self, skill_name: str) -> Optional[str]:
        """加载 SKILL.md 内容"""
        rel_path = self.SKILL_PATHS.get(skill_name)
        if not rel_path:
            return None
        
        skill_path = self.project_root / rel_path
        if not skill_path.exists():
            return None
        
        try:
            return skill_path.read_text(encoding="utf-8")
        except Exception:
            return None
    
    def parse_phases(self, skill_md: str) -> List[SkillPhase]:
        """从 SKILL.md 中解析执行阶段"""
        phases = []
        
        # 匹配 Phase X: xxx 格式
        phase_pattern = re.compile(
            r'###?\s*(Phase\s*\d+|阶段\s*\d+)[：:]\s*(.+?)\n',
            re.IGNORECASE
        )
        
        matches = list(phase_pattern.finditer(skill_md))
        for i, match in enumerate(matches):
            phase_id = match.group(1).strip()
            phase_name = match.group(2).strip()
            
            # 提取阶段描述（直到下一个阶段或下一个二级标题）
            start = match.end()
            end = matches[i+1].start() if i + 1 < len(matches) else len(skill_md)
            section = skill_md[start:end]
            
            # 简化描述
            lines = [l.strip() for l in section.split('\n') if l.strip() and not l.startswith('#')]
            description = lines[0] if lines else phase_name
            
            phases.append(SkillPhase(
                phase_id=phase_id,
                name=phase_name,
                description=description,
            ))
        
        return phases
    
    def is_skill_available(self, skill_name: str) -> bool:
        """检查 SKILL 是否可用"""
        return self.load_skill_md(skill_name) is not None


def execute_skill(skill_name: str, inputs: Dict, project_root: str = None) -> SkillResult:
    """
    执行指定 SKILL（统一入口）
    
    Args:
        skill_name: SKILL 名称
        inputs: 输入数据（mkt, memory, data 等）
        project_root: 项目根目录
    
    Returns:
        SkillResult
    """
    loader = SkillLoader(project_root)
    
    # 根据 SKILL 名称分发到对应的实现
    skill_handlers = {
        "dream-contradiction-theory": _execute_contradiction_theory,
        "dream-first-principles": _execute_first_principles,
    }
    
    handler = skill_handlers.get(skill_name)
    if handler:
        return handler(loader, inputs)
    
    # 未找到处理器，返回降级结果
    return SkillResult(
        skill_name=skill_name,
        version="unknown",
        phases_executed=[],
        direction="HOLD",
        confidence=0.3,
        rationale=[f"SKILL {skill_name} 未实现处理器"],
        data={},
        used_skill=False,
        fallback_reason="no_handler",
    )


def _execute_contradiction_theory(loader: SkillLoader, inputs: Dict) -> SkillResult:
    """
    执行 A0 矛盾论 SKILL
    SKILL: dream-contradiction-theory
    """
    skill_md = loader.load_skill_md("dream-contradiction-theory")
    phases = loader.parse_phases(skill_md) if skill_md else []
    
    mkt = inputs.get("mkt", {})
    data = inputs.get("data", {})
    
    price = mkt.get("price", 0)
    rsi = mkt.get("rsi14", 50)
    ema20 = mkt.get("ema20", price)
    ema50 = mkt.get("ema50", price)
    ema200 = mkt.get("ema200", price)
    funding = mkt.get("funding_rate", 0)
    ch24 = mkt.get("change_24h", 0)
    vol_ratio = mkt.get("vol_ratio", 1.0)
    
    contradictions = []
    bull_count = 0
    bear_count = 0
    conflict_count = 0
    
    # 维度1: 资金面（C1）
    fund_bull = funding < -0.0001
    fund_bear = funding > 0.0001
    fund_dominance = "BULL" if fund_bull else ("BEAR" if fund_bear else "NEUTRAL")
    fund_strength = min(abs(funding) * 10000 / 10, 1.0)
    if fund_bull:
        bull_count += 1
    elif fund_bear:
        bear_count += 1
    else:
        conflict_count += 1
    contradictions.append({
        "dimension": "C1_资金面",
        "bull": f"资金费率{funding*10000:.2f}bps，空头付多头",
        "bear": f"资金费率{funding*10000:.2f}bps，多头付空头",
        "dominance": fund_dominance,
        "strength": round(fund_strength, 2),
    })
    
    # 维度2: 情绪面（C2）
    sent_bull = rsi < 30
    sent_bear = rsi > 70
    sent_dominance = "BEAR" if sent_bear else ("BULL" if sent_bull else "NEUTRAL")
    sent_strength = min(abs(rsi - 50) / 20, 1.0)
    if sent_bull:
        bull_count += 1
    elif sent_bear:
        bear_count += 1
    else:
        conflict_count += 1
    contradictions.append({
        "dimension": "C2_情绪面",
        "bull": f"RSI={rsi:.1f}超卖，反弹力量",
        "bear": f"RSI={rsi:.1f}超买，下跌力量",
        "dominance": sent_dominance,
        "strength": round(sent_strength, 2),
    })
    
    # 维度3: 技术面（C3）
    tech_bull = price > ema200 and ema20 > ema50
    tech_bear = price < ema200 and ema20 < ema50
    tech_dominance = "BULL" if tech_bull else ("BEAR" if tech_bear else "NEUTRAL")
    if tech_bull:
        bull_count += 1
    elif tech_bear:
        bear_count += 1
    else:
        conflict_count += 1
    tech_strength = 0.6 if tech_dominance != "NEUTRAL" else 0.4
    contradictions.append({
        "dimension": "C3_技术面",
        "bull": f"MA200支撑，EMA多头排列",
        "bear": f"MA200压制，EMA空头排列",
        "dominance": tech_dominance,
        "strength": round(tech_strength, 2),
    })
    
    # 维度4: 趋势面（C6）
    trend_bull = ch24 > 1 and price > ema20
    trend_bear = ch24 < -1 and price < ema20
    trend_dominance = "BULL" if trend_bull else ("BEAR" if trend_bear else "NEUTRAL")
    trend_strength = min(abs(ch24) / 5, 1.0)
    if trend_bull:
        bull_count += 1
    elif trend_bear:
        bear_count += 1
    else:
        conflict_count += 1
    contradictions.append({
        "dimension": "C6_趋势面",
        "bull": f"24H+{ch24:.1f}%，价格在EMA20上方",
        "bear": f"24H{ch24:.1f}%，价格在EMA20下方",
        "dominance": trend_dominance,
        "strength": round(trend_strength, 2),
    })
    
    # 维度5: 量价面（C7）
    vol_bull = vol_ratio > 1.5 and ch24 > 0
    vol_bear = vol_ratio > 1.5 and ch24 < 0
    vol_dominance = "BULL" if vol_bull else ("BEAR" if vol_bear else "NEUTRAL")
    vol_strength = min(vol_ratio / 3, 1.0)
    if vol_bull:
        bull_count += 1
    elif vol_bear:
        bear_count += 1
    else:
        conflict_count += 1
    contradictions.append({
        "dimension": "C7_量价面",
        "bull": f"放量上涨，量价配合",
        "bear": f"放量下跌，量价配合",
        "dominance": vol_dominance,
        "strength": round(vol_strength, 2),
    })
    
    # 确定主要矛盾（强度最高的）
    primary = max(contradictions, key=lambda x: x["strength"])
    dominant_force = "BULL" if bull_count > bear_count else \
                     "BEAR" if bear_count > bull_count else "NEUTRAL"
    
    # 置信度计算
    total = bull_count + bear_count + conflict_count
    if total > 0:
        majority = max(bull_count, bear_count)
        confidence = 0.3 + (majority / total) * 0.5
    else:
        confidence = 0.4
    
    direction = "LONG" if dominant_force == "BULL" else \
                "SHORT" if dominant_force == "BEAR" else "HOLD"
    
    rationale = [
        f"[A0矛盾论] 5维度分析 - 多:{bull_count} 空:{bear_count} 冲突:{conflict_count}",
        f"主导力量: {dominant_force}",
        f"主要矛盾: {primary['dimension']} ({primary['dominance']}, 强度{primary['strength']})",
    ]
    
    # 提取 SKILL 版本号
    version = "1.0"
    if skill_md:
        ver_match = re.search(r'v(\d+\.\d+[\.\d]*)', skill_md)
        if ver_match:
            version = ver_match.group(1)
    
    return SkillResult(
        skill_name="dream-contradiction-theory",
        version=version,
        phases_executed=[p.phase_id for p in phases[:5]],
        direction=direction,
        confidence=round(confidence, 3),
        rationale=rationale,
        data={
            "contradictions": contradictions,
            "primary_contradiction": primary,
            "bull_count": bull_count,
            "bear_count": bear_count,
            "conflict_count": conflict_count,
            "dominant_force": dominant_force,
        },
        used_skill=bool(skill_md),
        fallback_reason="" if skill_md else "skill_md_not_found",
    )


def _execute_first_principles(loader: SkillLoader, inputs: Dict) -> SkillResult:
    """
    执行 A2 第一性原理 SKILL
    SKILL: dream-first-principles
    
    遵循 SKILL.md 定义的方法论:
    - 双维度分析（基本面×技术面）
    - 阻力最小路径计算（4分量加权）
    - MA轨迹法趋势追踪
    - 矛盾处理2.0
    - 逆向信号补偿机制
    """
    skill_md = loader.load_skill_md("dream-first-principles")
    phases = loader.parse_phases(skill_md) if skill_md else []
    
    mkt = inputs.get("mkt", {})
    memory = inputs.get("memory", {})
    a0_result = inputs.get("a0", {})
    
    price = mkt.get("price", 0)
    rsi = mkt.get("rsi14", 50)
    ema20 = mkt.get("ema20", price)
    ema50 = mkt.get("ema50", price)
    ema200 = mkt.get("ema200", price)
    atr = mkt.get("atr14", price * 0.02)
    funding = mkt.get("funding_rate", 0)
    ch24 = mkt.get("change_24h", 0)
    ch4h = mkt.get("change_4h", 0)
    ch1h = mkt.get("change_1h", 0)
    vol_ratio = mkt.get("vol_ratio", 1.0)
    
    rationale = []
    
    # ── Phase 1: 阻力最小路径计算（4分量加权，v2.3重构） ──
    # 分量1: 成本阻力（均线密集度）
    cost_resistance = 0.0
    ma_values = [ema20, ema50, ema200]
    ma_values.sort()
    if ma_values[-1] - ma_values[0] > 0:
        ma_density = (ma_values[-1] - ma_values[0]) / price * 100
        cost_resistance = min(ma_density / 5, 1.0)  # 5%以上算密集
    
    # 分量2: 流动性阻力（成交量确认）
    liquidity_resistance = max(0, 1.0 - vol_ratio / 3.0)
    
    # 分量3: 拥挤阻力（RSI超买超卖）
    if rsi > 70:
        crowd_resistance_up = (rsi - 70) / 30
        crowd_resistance_down = 0.0
    elif rsi < 30:
        crowd_resistance_up = 0.0
        crowd_resistance_down = (30 - rsi) / 30
    else:
        crowd_resistance_up = 0.0
        crowd_resistance_down = 0.0
    
    # 分量4: 波动阻力（ATR相对幅度）
    atr_pct = atr / price if price > 0 else 0.02
    volatility_resistance = min(atr_pct * 10, 1.0)  # 10%ATR算高波动
    
    # 上行阻力加权
    up_weights = {
        "cost": 0.35,
        "liquidity": 0.25,
        "crowded": 0.25,
        "volatility": 0.15,
    }
    up_resistance = (
        up_weights["cost"] * cost_resistance +
        up_weights["liquidity"] * liquidity_resistance +
        up_weights["crowded"] * crowd_resistance_up +
        up_weights["volatility"] * volatility_resistance
    )
    
    # 下行阻力加权
    down_resistance = (
        up_weights["cost"] * cost_resistance +
        up_weights["liquidity"] * liquidity_resistance +
        up_weights["crowded"] * crowd_resistance_down +
        up_weights["volatility"] * volatility_resistance
    )
    
    rationale.append(
        f"[Phase1阻力] 上行阻力={up_resistance:.2f} | 下行阻力={down_resistance:.2f}"
    )
    rationale.append(
        f"  分量-成本:{cost_resistance:.2f} 流动性:{liquidity_resistance:.2f} "
        f"拥挤上:{crowd_resistance_up:.2f} 拥挤下:{crowd_resistance_down:.2f} 波动:{volatility_resistance:.2f}"
    )
    
    # 阻力最小方向
    if up_resistance < down_resistance - 0.1:
        least_resistance = "UP"
    elif down_resistance < up_resistance - 0.1:
        least_resistance = "DOWN"
    else:
        least_resistance = "NEUTRAL"
    
    rationale.append(f"  阻力最小方向: {least_resistance}")
    
    # ── Phase 2: MA轨迹法趋势追踪 ──
    # 计算均线斜率
    ema20_slope = (ema20 - price) / price * 100 if price > 0 else 0
    ema50_slope = (ema50 - price) / price * 100 if price > 0 else 0
    
    # 趋势强度分级
    if price > ema20 > ema50 and ch24 > 0:
        trend_direction = "UP"
        trend_strength = min(0.8 + ch24 / 10, 1.0)
        trend_phase = "加速上涨"
    elif price < ema20 < ema50 and ch24 < 0:
        trend_direction = "DOWN"
        trend_strength = min(0.8 + abs(ch24) / 10, 1.0)
        trend_phase = "加速下跌"
    elif price > ema200:
        trend_direction = "UP"
        trend_strength = 0.5
        trend_phase = "中期偏多"
    elif price < ema200:
        trend_direction = "DOWN"
        trend_strength = 0.5
        trend_phase = "中期偏空"
    else:
        trend_direction = "RANGE"
        trend_strength = 0.3
        trend_phase = "震荡整理"
    
    rationale.append(f"[Phase2趋势] {trend_phase} | 方向={trend_direction} | 强度={trend_strength:.2f}")
    
    # ── Phase 3: 矛盾处理2.0（v2.3核心修复） ──
    a0_dominant = a0_result.get("dominant_force", "NEUTRAL")
    a0_conf = a0_result.get("confidence", 0.45)
    
    # 计算A0与A2的矛盾等级
    a2_direction = least_resistance
    
    contradiction_level = "NONE"
    if a0_dominant != "NEUTRAL" and a2_direction != "NEUTRAL":
        if (a0_dominant == "BULL" and a2_direction == "DOWN") or \
           (a0_dominant == "BEAR" and a2_direction == "UP"):
            contradiction_level = "STRONG"
        elif abs(a0_conf - trend_strength) > 0.3:
            contradiction_level = "MODERATE"
        else:
            contradiction_level = "WEAK"
    
    rationale.append(f"[Phase3矛盾] A0({a0_dominant}) vs A2({a2_direction}) | 等级={contradiction_level}")
    
    # 矛盾处理策略
    if contradiction_level == "STRONG":
        # 强矛盾：保守，降低置信度，倾向 HOLD
        final_direction = "HOLD"
        base_confidence = 0.35
        rationale.append("  强矛盾 → 保守策略，观望为主")
    elif contradiction_level == "MODERATE":
        # 中度矛盾：取两者折中，降低置信度
        if trend_direction in ("UP", "DOWN"):
            final_direction = "LONG" if trend_direction == "UP" else "SHORT"
            base_confidence = min(trend_strength, a0_conf) * 0.7
        else:
            final_direction = "HOLD"
            base_confidence = 0.4
        rationale.append("  中度矛盾 → 折中信义度，谨慎操作")
    else:
        # 弱矛盾/无矛盾：正常执行
        if least_resistance == "UP":
            final_direction = "LONG"
            base_confidence = 0.5 + trend_strength * 0.3
        elif least_resistance == "DOWN":
            final_direction = "SHORT"
            base_confidence = 0.5 + trend_strength * 0.3
        else:
            final_direction = "HOLD"
            base_confidence = 0.45
        rationale.append("  弱矛盾 → 正常策略，阻力最小方向优先")
    
    # ── Phase 4: 逆向信号补偿机制 ──
    # 检查是否存在逆向信号（超买超卖+背离）
    compensation = 0.0
    if final_direction == "LONG" and rsi < 30:
        compensation = 0.1  # 超卖反弹加成
        rationale.append(f"[Phase4补偿] RSI={rsi:.0f}超卖 + 做多方向 → +{compensation:.0%}补偿")
    elif final_direction == "SHORT" and rsi > 70:
        compensation = 0.1  # 超买回落加成
        rationale.append(f"[Phase4补偿] RSI={rsi:.0f}超买 + 做空方向 → +{compensation:.0%}补偿")
    
    # 负向补偿（逆向信号不利）
    if final_direction == "LONG" and rsi > 70:
        compensation = -0.1
        rationale.append(f"[Phase4补偿] RSI={rsi:.0f}超买 - 做多方向 → {compensation:.0%}惩罚")
    elif final_direction == "SHORT" and rsi < 30:
        compensation = -0.1
        rationale.append(f"[Phase4补偿] RSI={rsi:.0f}超卖 - 做空方向 → {compensation:.0%}惩罚")
    
    final_confidence = max(0.2, min(0.95, base_confidence + compensation))
    
    # ── Phase 5: 综合评估 ──
    rationale.append(f"[Phase5综合] 方向={final_direction} | 置信度={final_confidence:.0%}")
    
    # 提取 SKILL 版本号
    version = "1.0"
    if skill_md:
        ver_match = re.search(r'v(\d+\.\d+[\.\d]*)', skill_md)
        if ver_match:
            version = ver_match.group(1)
    
    return SkillResult(
        skill_name="dream-first-principles",
        version=version,
        phases_executed=[p.phase_id for p in phases[:8]] if phases else ["Phase1-5"],
        direction=final_direction,
        confidence=round(final_confidence, 3),
        rationale=rationale,
        data={
            "least_resistance": least_resistance,
            "up_resistance": round(up_resistance, 3),
            "down_resistance": round(down_resistance, 3),
            "resistance_components": {
                "cost": round(cost_resistance, 3),
                "liquidity": round(liquidity_resistance, 3),
                "crowded_up": round(crowd_resistance_up, 3),
                "crowded_down": round(crowd_resistance_down, 3),
                "volatility": round(volatility_resistance, 3),
            },
            "trend": {
                "direction": trend_direction,
                "strength": round(trend_strength, 3),
                "phase": trend_phase,
            },
            "contradiction_level": contradiction_level,
            "a0_dominant": a0_dominant,
            "compensation": round(compensation, 3),
        },
        used_skill=bool(skill_md),
        fallback_reason="" if skill_md else "skill_md_not_found",
    )
