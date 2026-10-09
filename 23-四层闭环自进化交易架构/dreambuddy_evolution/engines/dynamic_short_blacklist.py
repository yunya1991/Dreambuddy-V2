"""路径A: 动态做空黑名单（滚动胜率驱动）

SPEC-自进化系统做空能力疏通探讨 §4 路径A：
  将静态 SHORT_ONLY_BLACKLIST = {"ETH", "BTC"} 升级为滚动胜率驱动的动态黑名单。

核心机制:
  1. 维护每个币种近 N=20 笔做空交易的滚动胜率
  2. Beta-Binomial 共轭先验贝叶斯估计（Beta(4,6) 先验，均值 40%）
     - 入榜: 后验 P(胜率 >= 阈值) <= 0.7 → 不确信，维持入榜
     - 出榜: 后验 P(胜率 >= 阈值) > 0.7 → 确信正期望，允许出榜
  3. 样本 < 10 → 先验主导，维持保守（入榜）
  4. 滚动窗口 N=20：只保留最近交易记录，自动丢弃旧数据

A.6 首次试探配额（打破冷启动死循环）:
  - 新币种满足 2 因子 + VOLATILE_DROP/ranging_down → 允许 1 笔 0.1x 试探
  - 30 天冷却，累计 3 笔上限
  - 3 笔后贝叶斯估计接管，进入正常动态判定

安全侧 FAIL-OPEN: 异常/缺失 → 入榜（保守，维持 SHORT_BAN 铁律）
开关: enable_dynamic_short_blacklist（默认 False → 回退静态 {"ETH", "BTC"}）
"""
from __future__ import annotations

import logging
import math
import time
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Beta 分布 CDF — 正则化不完全贝塔函数 I_x(a, b)
# Numerical Recipes 连续分数法实现（无 scipy 依赖）
# ---------------------------------------------------------------------------

def _betacf(a: float, b: float, x: float) -> float:
    """连续分数法计算不完全 Beta 函数的连续分数部分"""
    _MAXIT = 200
    _EPS = 3.0e-7
    _FPMIN = 1.0e-30

    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < _FPMIN:
        d = _FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, _MAXIT + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < _FPMIN:
            d = _FPMIN
        c = 1.0 + aa / c
        if abs(c) < _FPMIN:
            c = _FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < _FPMIN:
            d = _FPMIN
        c = 1.0 + aa / c
        if abs(c) < _FPMIN:
            c = _FPMIN
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            break
    return h


def _beta_cdf(x: float, a: float, b: float) -> float:
    """Beta 分布 CDF: P(X <= x | Beta(a, b))

    使用正则化不完全贝塔函数 I_x(a, b)。
    Numerical Recipes 6.4 实现，精度 ~1e-7。
    """
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0

    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    bt = math.exp(a * math.log(x) + b * math.log(1.0 - x) - lbeta)

    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    else:
        return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


# ---------------------------------------------------------------------------
# DynamicShortBlacklist
# ---------------------------------------------------------------------------

class DynamicShortBlacklist:
    """滚动胜率驱动的动态做空黑名单

    受 enable_dynamic_short_blacklist 开关控制（默认 False）。
    开关关闭时回退到静态 {"ETH", "BTC"}。
    开关开启时使用贝叶斯估计动态判定。
    """

    # --- 滚动窗口参数 ---
    ROLLING_WINDOW: int = 20           # 滚动窗口 N
    WIN_RATE_THRESHOLD: float = 0.35   # 胜率阈值
    MIN_SAMPLE_SIZE: int = 10          # 最小样本量
    COOLDOWN_DAYS: int = 7             # 出榜冷却期

    # --- 贝叶斯先验参数（Beta-Binomial 共轭先验）---
    BETA_ALPHA: float = 4.0            # 先验 alpha（等效 4 次盈利）
    BETA_BETA: float = 6.0             # 先验 beta（等效 6 次亏损）
    POSTERIOR_THRESHOLD: float = 0.7   # 后验概率阈值

    # --- A.6 首次试探配额参数 ---
    PROBE_COOLDOWN_DAYS: int = 30      # 试探冷却期
    PROBE_MAX_COUNT: int = 3           # 累计试探上限
    PROBE_MIN_FACTOR_COUNT: int = 2    # 最少因子数
    PROBE_ALLOWED_REGIMES = frozenset({"VOLATILE_DROP", "ranging_down"})

    # --- 静态回退 ---
    STATIC_BLACKLIST = frozenset({"ETH", "BTC"})

    # --- 开关名 ---
    SWITCH_NAME = "enable_dynamic_short_blacklist"

    def __init__(self, trades_store: Optional[str] = None) -> None:
        """初始化动态黑名单。

        Args:
            trades_store: 交易存储路径（预留持久化，当前内存实现）。
                           路径不存在时 FAIL-OPEN，不影响内存判定。
        """
        self._trades_store = trades_store
        # 内存交易记录: {symbol: deque([(timestamp, pnl), ...], maxlen=N)}
        self._records: Dict[str, Deque[Tuple[float, float]]] = {}
        # 试探配额记录: {symbol: {"count": int, "last_probe_ts": float}}
        self._probe_records: Dict[str, Dict] = {}

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def is_blacklisted(self, symbol: Optional[str]) -> bool:
        """检查币种是否在动态黑名单中（禁空）。

        判定逻辑:
          1. 开关关闭 → 回退静态 {"ETH", "BTC"}
          2. 开关开启 + 样本不足 (< 10) → 入榜（保守）
          3. 开关开启 + 样本充足 → 贝叶斯后验判定
             P(胜率 >= 阈值) > 0.7 → 出榜
             否则 → 入榜

        FAIL-OPEN: 异常 → 入榜（True）
        """
        try:
            sym = str(symbol or "").strip().upper()
            if not sym:
                return True  # FAIL-OPEN: 空 symbol

            # 开关检查
            if not self._is_enabled():
                return sym in self.STATIC_BLACKLIST

            # 获取滚动窗口记录
            records = self._get_records(sym)
            n = len(records)
            if n < self.MIN_SAMPLE_SIZE:
                return True  # 样本不足 → 保守

            # 贝叶斯后验估计
            wins = sum(1 for _, pnl in records if pnl > 0)
            post_a = self.BETA_ALPHA + wins
            post_b = self.BETA_BETA + (n - wins)

            # P(胜率 >= 阈值) = 1 - CDF(阈值)
            p_above = 1.0 - _beta_cdf(self.WIN_RATE_THRESHOLD, post_a, post_b)
            if p_above > self.POSTERIOR_THRESHOLD:
                return False  # 出榜

            return True  # 默认入榜

        except Exception as e:
            logger.debug("[FO] DynamicShortBlacklist is_blacklisted fail: %s", e)
            return True  # FAIL-OPEN

    def record_trade(self, symbol: Optional[str], pnl: float) -> None:
        """记录一笔做空交易结果，更新滚动胜率。

        Args:
            symbol: 币种
            pnl: 盈亏（正=盈，负=亏）
        """
        try:
            sym = str(symbol or "").strip().upper()
            if not sym:
                return
            ts = time.time()
            if sym not in self._records:
                self._records[sym] = deque(maxlen=self.ROLLING_WINDOW)
            self._records[sym].append((ts, float(pnl)))
        except Exception:
            pass  # FAIL-OPEN: 记录失败不影响交易

    def can_probe(
        self,
        symbol: Optional[str],
        regime: Optional[str],
        factor_count: int,
    ) -> bool:
        """A.6: 检查是否允许首次试探配额。

        条件:
          1. 币种无样本（新币种）
          2. 因子数 >= 2（路径B分层门槛）
          3. regime ∈ {VOLATILE_DROP, ranging_down}（正期望条件）
          4. 未达累计上限（3 笔）
          5. 冷却期外（30 天）

        Returns:
            True = 允许试探
            False = 不允许（FAIL-OPEN）
        """
        try:
            sym = str(symbol or "").strip().upper()
            if not sym:
                return False

            # 开关检查（关闭时 A.6 不生效）
            if not self._is_enabled():
                return False

            # 1. 必须是新币种（无样本）
            records = self._get_records(sym)
            if len(records) > 0:
                return False

            # 2. 因子门槛
            if int(factor_count) < self.PROBE_MIN_FACTOR_COUNT:
                return False

            # 3. regime 约束（禁止 ranging_up 等负期望条件）
            reg = str(regime or "")
            if reg not in self.PROBE_ALLOWED_REGIMES:
                return False

            # 4. 累计上限 + 冷却期
            probe_rec = self._probe_records.get(sym, {})
            count = probe_rec.get("count", 0)
            if count >= self.PROBE_MAX_COUNT:
                return False

            last_ts = probe_rec.get("last_probe_ts", 0.0)
            if count > 0:
                cooldown_s = self.PROBE_COOLDOWN_DAYS * 86400
                if time.time() - last_ts < cooldown_s:
                    return False

            return True
        except Exception:
            return False  # FAIL-OPEN

    def mark_probe_executed(self, symbol: Optional[str]) -> None:
        """标记一次试探已执行（更新计数和冷却时间）。"""
        try:
            sym = str(symbol or "").strip().upper()
            if not sym:
                return
            rec = self._probe_records.setdefault(
                sym, {"count": 0, "last_probe_ts": 0.0}
            )
            rec["count"] += 1
            rec["last_probe_ts"] = time.time()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _is_enabled(self) -> bool:
        """检查开关是否开启（FAIL-OPEN: 异常 → False → 静态回退）"""
        try:
            from dreambuddy_evolution.agi_config import get_switch
            return get_switch(self.SWITCH_NAME)
        except Exception:
            return False

    def _get_records(self, symbol: str) -> List[Tuple[float, float]]:
        """获取币种的滚动交易记录列表"""
        return list(self._records.get(symbol, deque()))

    def _skip_probe_cooldown(self, symbol: str) -> None:
        """测试辅助: 跳过试探冷却期（仅用于测试）"""
        sym = str(symbol or "").upper()
        rec = self._probe_records.get(sym)
        if rec:
            rec["last_probe_ts"] = 0.0
