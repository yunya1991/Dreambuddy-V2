#!/usr/bin/env python3
"""
凯利公式底仓比例优化器

基于用户提供的实战修正原则：
1. 分数凯利策略：使用半凯利(f*/2)或四分之一凯利(f*/4)，降低仓位换取资金曲线平稳
2. 保守估计参数：对胜率(p)和盈亏比(b)进行保守调整，宁可低估优势
3. 叠加硬性风控上限：单笔交易最大亏损不得超过总资金的1%-2%

凯利公式：f* = (b*p - q) / b
  p = 胜率
  q = 1 - p = 败率
  b = 盈亏比 = 平均盈利 / 平均亏损
  f* = 最优仓位比例（理论）

工作流程：
1. 从历史回测交易记录计算 p 和 b
2. 保守调整：对 p 和 b 进行收缩估计（向0.5和1.0收缩）
3. 计算凯利 f*
4. 应用分数凯利：f = f* × fraction（默认0.5即半凯利）
5. 应用硬性风控上限：单笔亏损 ≤ max_risk_pct（默认2%）
6. 与基线底仓比例(22%)对比，取较保守者
"""
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


# ── 默认参数 ──────────────────────────────────────────────────────────────

BASE_POSITION_PCT = 0.22  # 基线底仓比例（22%）
KELLY_FRACTION = 0.5      # 分数凯利系数（0.5=半凯利，0.25=四分之一凯利）
MAX_RISK_PCT = 0.02       # 单笔最大亏损占总资金比例（2%）
MIN_POSITION_PCT = 0.02   # 最小底仓比例（2%，低于此则不交易）
MAX_POSITION_PCT = 0.30   # 最大底仓比例上限（30%，硬性天花板）

# 保守估计收缩系数（向中性值收缩）
# shrinkage=0 表示不收缩，shrinkage=1 表示完全用中性值
# p 向 0.5 收缩，b 向 1.0 收缩
P_SHRINKAGE = 0.15        # 胜率收缩系数（15%权重给中性值0.5）
B_SHRINKAGE = 0.15        # 盈亏比收缩系数（15%权重给中性值1.0）

# 最小样本量要求
MIN_TRADES_FOR_KELLY = 20  # 少于此数则不启用凯利，回退到基线


@dataclass
class KellyParams:
    """凯利公式计算参数"""
    p: float              # 胜率（保守调整后）
    b: float              # 盈亏比（保守调整后）
    f_star: float         # 理论凯利比例
    f_fractional: float   # 分数凯利比例
    f_capped: float       # 风控上限后比例
    final_pct: float      # 最终底仓比例（与基线对比取保守者）
    avg_win_pct: float    # 平均盈利百分比
    avg_loss_pct: float   # 平均亏损百分比
    raw_p: float          # 原始胜率
    raw_b: float          # 原始盈亏比
    total_trades: int     # 交易总数
    win_count: int        # 盈利交易数
    loss_count: int       # 亏损交易数
    used_kelly: bool      # 是否实际启用了凯利优化
    reason: str           # 决策原因说明


def calculate_kelly_from_trades(
    trades: List[Dict],
    base_pct: float = BASE_POSITION_PCT,
    kelly_fraction: float = KELLY_FRACTION,
    max_risk_pct: float = MAX_RISK_PCT,
    min_trades: int = MIN_TRADES_FOR_KELLY,
    p_shrinkage: float = P_SHRINKAGE,
    b_shrinkage: float = B_SHRINKAGE,
) -> KellyParams:
    """从回测交易记录计算凯利优化后的底仓比例

    参数:
        trades: 回测交易记录列表，每条需含 pnl_pct 字段
        base_pct: 基线底仓比例（默认22%）
        kelly_fraction: 分数凯利系数（默认0.5=半凯利）
        max_risk_pct: 单笔最大亏损占比（默认2%）
        min_trades: 启用凯利的最小交易数
        p_shrinkage: 胜率保守收缩系数
        b_shrinkage: 盈亏比保守收缩系数

    返回:
        KellyParams 对象
    """
    if not trades or len(trades) < min_trades:
        return KellyParams(
            p=0.5, b=1.0, f_star=0.0, f_fractional=0.0, f_capped=0.0,
            final_pct=base_pct, avg_win_pct=0.0, avg_loss_pct=0.0,
            raw_p=0.0, raw_b=0.0,
            total_trades=len(trades) if trades else 0,
            win_count=0, loss_count=0,
            used_kelly=False,
            reason=f"交易数不足({len(trades) if trades else 0}<{min_trades})，使用基线{base_pct*100:.0f}%",
        )

    wins = [t for t in trades if t.get("pnl_pct", 0) > 0]
    losses = [t for t in trades if t.get("pnl_pct", 0) <= 0]

    total = len(trades)
    win_count = len(wins)
    loss_count = len(losses)

    # 原始参数
    raw_p = win_count / total if total > 0 else 0
    avg_win_pct = sum(t["pnl_pct"] for t in wins) / win_count if win_count else 0
    avg_loss_pct = abs(sum(t["pnl_pct"] for t in losses) / loss_count) if loss_count else 0
    raw_b = avg_win_pct / avg_loss_pct if avg_loss_pct > 0 else 0

    # ── 保守估计：收缩估计 ──
    # 胜率向0.5收缩：p_adj = p*(1-shrinkage) + 0.5*shrinkage
    p = raw_p * (1 - p_shrinkage) + 0.5 * p_shrinkage
    # 盈亏比向1.0收缩：b_adj = b*(1-shrinkage) + 1.0*shrinkage
    b = raw_b * (1 - b_shrinkage) + 1.0 * b_shrinkage

    q = 1 - p

    # ── 凯利公式：f* = (b*p - q) / b ──
    if b > 0:
        f_star = (b * p - q) / b
    else:
        f_star = 0
    f_star = max(0, f_star)  # 负值=无优势，不交易

    # ── 分数凯利 ──
    f_fractional = f_star * kelly_fraction

    # ── 硬性风控上限：单笔亏损 = 仓位比例 × 平均亏损比例 ≤ max_risk_pct ──
    # 仓位比例 ≤ max_risk_pct / (avg_loss_pct / 100)
    if avg_loss_pct > 0:
        max_f_by_risk = max_risk_pct / (avg_loss_pct / 100)
    else:
        max_f_by_risk = MAX_POSITION_PCT

    f_capped = min(f_fractional, max_f_by_risk, MAX_POSITION_PCT)
    f_capped = max(0, f_capped)

    # ── 与基线对比：取较保守者（不盲目超额）──
    # 如果凯利建议 > 基线，仍用基线（保守）
    # 如果凯利建议 < 基线，用凯利建议（降仓）
    if f_capped < base_pct:
        final_pct = f_capped
        used_kelly = True
        reason = f"凯利建议降仓: f*={f_star:.4f} → {kelly_fraction}x={f_fractional:.4f} → 风控={f_capped:.4f}"
    else:
        final_pct = base_pct
        used_kelly = False
        reason = f"凯利建议({f_capped:.4f})≥基线({base_pct:.4f})，保守取基线"

    # 最小仓位检查
    if final_pct < MIN_POSITION_PCT:
        final_pct = MIN_POSITION_PCT
        reason += f" → 触底最小{MIN_POSITION_PCT*100:.0f}%"

    return KellyParams(
        p=p, b=b, f_star=f_star, f_fractional=f_fractional, f_capped=f_capped,
        final_pct=final_pct,
        avg_win_pct=avg_win_pct, avg_loss_pct=avg_loss_pct,
        raw_p=raw_p, raw_b=raw_b,
        total_trades=total, win_count=win_count, loss_count=loss_count,
        used_kelly=used_kelly, reason=reason,
    )


def format_kelly_report(kp: KellyParams, coin: str = "") -> str:
    """格式化凯利参数报告"""
    lines = []
    header = f"  凯利公式分析报告"
    if coin:
        header += f" — {coin}"
    lines.append(header)
    lines.append("  " + "-" * 60)

    if not kp.used_kelly and "不足" in kp.reason:
        lines.append(f"  ⚠️  {kp.reason}")
        lines.append(f"  最终底仓比例: {kp.final_pct*100:.1f}% (基线)")
        return "\n".join(lines)

    lines.append(f"  样本: {kp.total_trades}笔交易 (盈{kp.win_count}/亏{kp.loss_count})")
    lines.append(f"  原始胜率: {kp.raw_p*100:.1f}%  原始盈亏比: {kp.raw_b:.2f}")
    lines.append(f"  保守胜率: {kp.p*100:.1f}%  保守盈亏比: {kp.b:.2f}")
    lines.append(f"  平均盈利: +{kp.avg_win_pct:.2f}%  平均亏损: -{kp.avg_loss_pct:.2f}%")
    lines.append("  " + "-" * 60)
    lines.append(f"  理论凯利 f*: {kp.f_star*100:.2f}%")
    lines.append(f"  分数凯利 ({KELLY_FRACTION}x): {kp.f_fractional*100:.2f}%")
    lines.append(f"  风控上限后: {kp.f_capped*100:.2f}%")
    lines.append(f"  最终底仓比例: {kp.final_pct*100:.1f}%")
    status = "✅启用凯利降仓" if kp.used_kelly else "➡️保守取基线"
    lines.append(f"  状态: {status}")
    lines.append(f"  原因: {kp.reason}")

    return "\n".join(lines)


if __name__ == "__main__":
    # 自测：模拟交易数据
    test_trades = [
        {"pnl_pct": 4.0}, {"pnl_pct": -2.0}, {"pnl_pct": 3.5}, {"pnl_pct": -1.5},
        {"pnl_pct": 4.2}, {"pnl_pct": -2.5}, {"pnl_pct": 3.8}, {"pnl_pct": -1.8},
        {"pnl_pct": 4.1}, {"pnl_pct": -2.2}, {"pnl_pct": 3.9}, {"pnl_pct": -1.6},
        {"pnl_pct": 4.3}, {"pnl_pct": -2.8}, {"pnl_pct": 3.7}, {"pnl_pct": -1.9},
        {"pnl_pct": 4.0}, {"pnl_pct": -2.1}, {"pnl_pct": 3.6}, {"pnl_pct": -2.3},
        {"pnl_pct": 4.4}, {"pnl_pct": -1.7}, {"pnl_pct": 3.5}, {"pnl_pct": -2.4},
    ]

    kp = calculate_kelly_from_trades(test_trades)
    print(format_kelly_report(kp, "TEST"))
