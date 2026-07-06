"""阻力最小方向 (MRD)：基于象限密度计算 UP/DOWN 方向阻力。"""

from typing import List

from .types import CleanedEvent, MDRResult


def compute_mrd(
    events: List[CleanedEvent],
    threshold: float = 20.0,
) -> MDRResult:
    """计算阻力最小方向。

    算法:
    1. benefit_density = count(x>0.3 & y>0.5) / N
    2. harm_density    = count(x<-0.3 & y>0.5) / N
    3. R_UP   = harm_density * 100
    4. R_DOWN = benefit_density * 100
    5. net = R_DOWN - R_UP  (正数=UP 更容易)
    """
    if not events:
        return MDRResult(
            direction="NEUTRAL", resistance_up=50, resistance_down=50,
            net=0, confidence=0,
        )

    n = len(events)
    benefit_count = sum(
        1 for e in events
        if e.quadrant_x > 0.3 and e.quadrant_y > 0.5
    )
    harm_count = sum(
        1 for e in events
        if e.quadrant_x < -0.3 and e.quadrant_y > 0.5
    )

    benefit_density = benefit_count / n
    harm_density = harm_count / n

    r_up = harm_density * 100
    r_down = benefit_density * 100
    net = r_down - r_up

    if net > threshold:
        direction = "UP"
    elif net < -threshold:
        direction = "DOWN"
    else:
        direction = "NEUTRAL"

    total = r_up + r_down
    confidence = abs(net) / max(total, 1) if total > 0 else 0

    return MDRResult(
        direction=direction,
        resistance_up=round(r_up, 2),
        resistance_down=round(r_down, 2),
        net=round(net, 2),
        confidence=round(max(0, min(1, confidence)), 4),
    )
