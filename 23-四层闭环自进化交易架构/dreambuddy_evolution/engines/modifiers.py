"""
三修饰子外部增强模块 (§1.9.4 公式设计)
R_sentiment 非线性 80/20 + R_capital 资金流方向 + R_narrative 叙事驱动力

设计约束 (§1.9.6 硬约束):
- 修饰子不进入 g_diag 对角阵（g_diag 永久 5×5）
- 权重上限 α/β/γ ∈ [0, 0.2]
- crash → 0.0（不增强 = 等价 baseline）
- 修饰子不计入 FO-2 n_fb 阈值
- R_sentiment 必须非线性 80/20 分段
- 三角验证①必跑：R_narrative 增强前必须检查 R_capital
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)


def apply_sentiment_modifier(
    r_reflexivity: float,
    sentiment: float | None,
    beta: float = 0.2,
) -> float:
    """
    §1.9.4 R_sentiment → 修饰 R_reflexivity（非线性 80/20 逆向）

    - sentiment > 0.8: 极度贪婪 → 逆向减分（巴菲特：别人贪婪我恐慌）
    - sentiment < 0.2: 极度恐慌 → 逆向加分（巴菲特：别人恐慌我贪婪）
    - 0.2 ≤ sentiment ≤ 0.8: 正常区间 → 顺向增强（偏离中性越远增强越多）
    - sentiment None/crash → 返回原值（不修饰）
    """
    try:
        if sentiment is None or isinstance(sentiment, float) and (sentiment != sentiment):  # NaN check
            return float(r_reflexivity)

        s = float(sentiment)
        beta = max(0.0, min(0.2, float(beta)))  # 硬上限 clamp

        if s > 0.8:
            # 极度贪婪 → 逆向减分
            # 越贪婪减越多: mod = -beta × (s - 0.8) / 0.2
            mod = -beta * (s - 0.8) / 0.2
        elif s < 0.2:
            # 极度恐慌 → 逆向加分
            # 越恐慌加越多: mod = +beta × (0.2 - s) / 0.2
            mod = +beta * (0.2 - s) / 0.2
        else:
            # 正常区间 → 顺向增强
            # 偏离中性(0.5)越远增强越多: mod = +beta × (s - 0.5)
            mod = beta * (s - 0.5)

        result = float(r_reflexivity) * (1.0 + mod)
        return max(0.0, min(1.0, result))

    except Exception as e:
        logger.warning("[FO-1] sentiment modifier crash: %s", e)
        return float(r_reflexivity)


def apply_capital_modifier(
    r_dim: float,
    capital_flow: float | None,
    gamma: float = 0.2,
) -> float:
    """
    §1.9.4 R_capital → 修饰 R_up / R_down（资金流方向）

    capital_flow ∈ [-1, +1]:
    - 正值（净流入）→ 降低 R_up（上涨阻力减小）
    - 负值（净流出）→ 降低 R_down（下跌阻力减小）
    - 0 → 不修饰
    - None/crash → 返回原值

    公式: r_dim × (1 - γ × |capital_flow|) 当方向匹配时
    简化: r_dim × (1 - γ × max(0, capital_flow))  # 用于 R_up
          r_dim × (1 - γ × max(0, -capital_flow)) # 用于 R_down
    """
    try:
        if capital_flow is None:
            return float(r_dim)

        cf = float(capital_flow)
        gamma = max(0.0, min(0.2, float(gamma)))  # 硬上限 clamp

        # 对 R_up: 资金流入(正) → 减小上涨阻力
        # 对 R_down: 资金流出(负) → 减小下跌阻力
        # 统一用 abs(): 流入减小 R_up，流出减小 R_down，方向由调用方决定
        reduction = gamma * abs(cf)
        result = float(r_dim) * (1.0 - reduction)
        return max(0.0, min(1.0, result))

    except Exception as e:
        logger.warning("[FO-1] capital modifier crash: %s", e)
        return float(r_dim)


def apply_narrative_modifier(
    r_flow: float,
    narrative: float | None,
    capital: float | None,
    alpha: float = 0.2,
) -> float:
    """
    §1.9.4 R_narrative → 修饰 R_flow（叙事 = 动力源附加）

    公式: R_flow × (1 + α × R_narrative × capital_validation)
    capital_validation = 1.0 if R_capital > 0.5 else 0.3  # 三角验证①

    - 叙事 + 资金验证 → 增强
    - 叙事 + 资金缺失 → 打折（capital_validation=0.3）
    - 无叙事 → 不修饰
    - crash → 返回原值
    """
    try:
        if narrative is None:
            return float(r_flow)

        n = float(narrative)
        alpha = max(0.0, min(0.2, float(alpha)))  # 硬上限 clamp

        # 三角验证①: 叙事必须有资金验证
        cap_val = float(capital) if capital is not None else 0.0
        capital_validation = 1.0 if cap_val > 0.5 else 0.3

        enhancement = alpha * n * capital_validation
        result = float(r_flow) * (1.0 + enhancement)
        return max(0.0, min(1.0, result))

    except Exception as e:
        logger.warning("[FO-1] narrative modifier crash: %s", e)
        return float(r_flow)


def apply_all_modifiers(
    r_vector: dict[str, Any],
    sentiment: float | None = None,
    capital_flow: float | None = None,
    narrative: float | None = None,
    alpha: float = 0.0,
    beta: float = 0.0,
    gamma: float = 0.0,
) -> dict[str, float]:
    """
    联合应用三修饰子到 R 向量。

    修饰规则:
    - R_capital → R_up (流入减小) / R_down (流出减小)
    - R_narrative → R_flow (叙事增强动力源)
    - R_sentiment → R_reflexivity (非线性 80/20)
    - R_smooth 永远不修饰（无对应修饰子）

    α=β=γ=0 → 完全退化为 baseline（零风险回退）
    """
    try:
        result = dict(r_vector)  # 浅拷贝

        # R_smooth 永远不修饰
        # R_up: 资金流入 → 减小上涨阻力
        if gamma > 0 and capital_flow is not None:
            cf = float(capital_flow)
            result["R_up"] = apply_capital_modifier(
                float(r_vector.get("R_up", 0.5)),
                capital_flow=max(0.0, cf),  # 流入部分
                gamma=gamma,
            )
            # R_down: 资金流出 → 减小下跌阻力
            result["R_down"] = apply_capital_modifier(
                float(r_vector.get("R_down", 0.5)),
                capital_flow=max(0.0, -cf),  # 流出部分
                gamma=gamma,
            )

        # R_flow: 叙事增强
        if alpha > 0 and narrative is not None:
            cap_val = capital_flow if capital_flow is not None else 0.0
            result["R_flow"] = apply_narrative_modifier(
                float(r_vector.get("R_flow", 0.5)),
                narrative=narrative,
                capital=cap_val,
                alpha=alpha,
            )

        # R_reflexivity: 情绪非线性修饰
        if beta > 0 and sentiment is not None:
            result["R_reflexivity"] = apply_sentiment_modifier(
                float(r_vector.get("R_reflexivity", 0.5)),
                sentiment=sentiment,
                beta=beta,
            )

        return result

    except Exception as e:
        logger.warning("[FO] apply_all_modifiers crash: %s", e)
        return dict(r_vector)  # 返回原始向量
