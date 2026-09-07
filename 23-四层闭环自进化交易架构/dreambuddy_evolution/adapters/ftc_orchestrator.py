"""
ftc_orchestrator — 金融思维链编排器

职责:
  1. 管理 FTC 种子库（从 PathLibrary 拆解）
  2. 三轨道分轨: 利用(exploit) / 混合(mixed) / 探索(explore) / 丢弃(discard)
  3. ε 探索因子(L1): 控制探索轨道 FTC 被选中的概率权重
  4. 轨道选择: 根据 ε 和 ESS 从各轨道中选取 FTC

探索因子 ε:
  - ε ∈ [0.2, 0.6]，初始 0.3
  - 盈利(CS≥0.7 & TP) → ε × 0.95 (微降)
  - 亏损(CS≤-0.2 & SL) → ε × 1.2 (增加)
  - 连续无 ESS 提升 → ε × 1.15
  - 永不低于 0.2（周期相似但不雷同）
"""
from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Optional

from .ftc_schema import FTC
from .ftc_similarity import align_to_anchors, get_track_by_similarity
from .ftc_backtest import backtest_ftc, backtest_ftc_list
from .ftc_combiner import generate_combinations
from .path_library import PathLibrary

logger = logging.getLogger(__name__)


# 探索因子常量
EPSILON_INIT = 0.3
EPSILON_MIN = 0.2   # 结构性底线: 周期不雷同
EPSILON_MAX = 0.6
EPSILON_DECAY_PROFIT = 0.95
EPSILON_RISE_LOSS = 1.2
EPSILON_RISE_STAGNATION = 1.15


class ExplorationFactor:
    """L1 探索因子 ε — 控制组合探索力度"""

    def __init__(self, value: float = EPSILON_INIT, persist_path: Optional[str] = None):
        self.value = max(EPSILON_MIN, min(EPSILON_MAX, value))
        self._persist_path = persist_path
        self._stagnation_count = 0
        self._prev_max_ess = 0.0

    def on_trade_result(self, confidence_score: float, pnl_pct: float) -> None:
        """
        根据交易结果更新 ε

        Args:
            confidence_score: 信心分 CS (ReflectionEngine 的判断准确度)
            pnl_pct: 盈亏百分比
        """
        is_tp = pnl_pct > 0
        is_sl = pnl_pct < 0

        if confidence_score >= 0.7 and is_tp:
            # 判断准且赚 → 微降探索
            self.value *= EPSILON_DECAY_PROFIT
            self._stagnation_count = 0
        elif confidence_score <= -0.2 and is_sl:
            # 判断错且亏 → 增加探索
            self.value *= EPSILON_RISE_LOSS
            self._stagnation_count = 0
        elif is_sl:
            # 亏损但判断不一定错 → 小幅增加
            self.value *= 1.05

        # 停滞检测
        if abs(pnl_pct) < 0.001:
            self._stagnation_count += 1
        else:
            self._stagnation_count = 0

        if self._stagnation_count >= 10:
            self.value *= EPSILON_RISE_STAGNATION
            self._stagnation_count = 0

        # clamp
        self.value = max(EPSILON_MIN, min(EPSILON_MAX, self.value))
        self._save()

    def on_ess_update(self, max_ess: float) -> None:
        """ESS 更新时检测停滞"""
        if max_ess > self._prev_max_ess + 0.001:
            self._prev_max_ess = max_ess
            self._stagnation_count = 0
        else:
            self._stagnation_count += 1
            if self._stagnation_count >= 10:
                self.value *= EPSILON_RISE_STAGNATION
                self.value = max(EPSILON_MIN, min(EPSILON_MAX, self.value))
                self._stagnation_count = 0
        self._save()

    def _save(self) -> None:
        if not self._persist_path:
            return
        try:
            Path(self._persist_path).parent.mkdir(parents=True, exist_ok=True)
            with open(self._persist_path, "w") as f:
                json.dump({
                    "epsilon": round(self.value, 4),
                    "stagnation_count": self._stagnation_count,
                    "prev_max_ess": self._prev_max_ess,
                }, f, indent=2)
        except Exception as e:
            logger.debug(f"epsilon persist failed: {e}")

    def load(self) -> None:
        if not self._persist_path:
            return
        try:
            with open(self._persist_path) as f:
                data = json.load(f)
            self.value = max(EPSILON_MIN, min(EPSILON_MAX, data.get("epsilon", EPSILON_INIT)))
            self._stagnation_count = data.get("stagnation_count", 0)
            self._prev_max_ess = data.get("prev_max_ess", 0.0)
        except Exception:
            pass  # 首次运行无文件


class FTCOrchestrator:
    """FTC 编排器 — 管理种子库、分轨、探索因子"""

    def __init__(
        self,
        path_library: Optional[PathLibrary] = None,
        epsilon_persist_path: Optional[str] = None,
    ):
        self._path_lib = path_library or PathLibrary()
        self._ftcs: dict[str, FTC] = {}
        self._epsilon = ExplorationFactor(persist_path=epsilon_persist_path)
        self._epsilon.load()

    def initialize_seeds(self) -> int:
        """从 PathLibrary 拆解全部路径为 FTC 种子，返回种子数"""
        ftcs = self._path_lib.decompose_to_ftc()
        for ftc in ftcs:
            self._ftcs[ftc.ftc_id] = ftc
        logger.info(f"[FTC] 拆解 {len(ftcs)} 条经验路径为 FTC 种子")
        return len(ftcs)

    def get_ftc(self, ftc_id: str) -> Optional[FTC]:
        return self._ftcs.get(ftc_id)

    def get_all_ftcs(self) -> list[FTC]:
        return list(self._ftcs.values())

    def get_by_track(self, track: str) -> list[FTC]:
        """按轨道获取 FTC"""
        return [f for f in self._ftcs.values() if f.track == track]

    def recompute_tracks(self) -> None:
        """根据最大相似度重新计算所有 FTC 的轨道"""
        for ftc in self._ftcs.values():
            ftc.track = get_track_by_similarity(ftc.max_similarity)

    @property
    def epsilon(self) -> float:
        return self._epsilon.value

    def update_epsilon_on_trade(self, confidence_score: float, pnl_pct: float) -> None:
        """交易结果驱动 ε 更新"""
        self._epsilon.on_trade_result(confidence_score, pnl_pct)

    def update_epsilon_on_ess(self, max_ess: float) -> None:
        """ESS 更新驱动 ε 停滞检测"""
        self._epsilon.on_ess_update(max_ess)

    def select_ftc(self, top_n: int = 3) -> list[FTC]:
        """
        根据 ε 从各轨道中选取 FTC

        选择策略:
          - 以 (1-ε) 概率从利用轨道选 (按 ESS 排序)
          - 以 ε 概率从探索轨道选 (随机/低 ESS 优先探索)
          - 混合轨道作为补充
        """
        exploit = sorted(
            self.get_by_track("exploit"),
            key=lambda f: f.ess or 0,
            reverse=True,
        )
        mixed = sorted(
            self.get_by_track("mixed"),
            key=lambda f: f.ess or 0,
            reverse=True,
        )
        explore = self.get_by_track("explore")

        selected: list[FTC] = []

        # 决定探索 vs 利用
        if random.random() < self._epsilon.value and explore:
            # 探索: 从探索轨道随机选
            random.shuffle(explore)
            selected.extend(explore[:top_n])
        else:
            # 利用: 从利用轨道选 top
            selected.extend(exploit[:top_n])

        # 补充: 如果不够，从混合轨道补
        if len(selected) < top_n:
            selected.extend(mixed[: top_n - len(selected)])

        return selected[:top_n]

    def get_track_summary(self) -> dict:
        """返回各轨道的 FTC 数量统计"""
        return {
            "exploit": len(self.get_by_track("exploit")),
            "mixed": len(self.get_by_track("mixed")),
            "explore": len(self.get_by_track("explore")),
            "discard": len(self.get_by_track("discard")),
            "epsilon": round(self._epsilon.value, 4),
            "total": len(self._ftcs),
        }

    def to_dict(self) -> dict:
        """导出全部 FTC 状态（用于持久化/调试）"""
        return {
            "ftcs": [f.to_dict() for f in self._ftcs.values()],
            "epsilon": round(self._epsilon.value, 4),
            "track_summary": self.get_track_summary(),
        }

    # ─── Phase 2: 回测 + 组合 + 晋升降级 ────────────────────────

    def run_backtest_all(self, symbol: str = "BTC") -> list[dict]:
        """对全部 FTC 跑回测，更新 ess/n_samples 字段，返回按 ESS 排序的结果"""
        ftcs = self.get_all_ftcs()
        results = backtest_ftc_list(ftcs, symbol)

        # 回写 ess/n_samples 到 FTC
        for r in results:
            ftc = self._ftcs.get(r["ftc_id"])
            if ftc:
                ftc.ess = r["ess"]
                ftc.n_samples = r["N"]

        # 更新 ε（ESS 停滞检测）
        max_ess = results[0]["ess"] if results else 0.0
        self._epsilon.on_ess_update(max_ess)

        return results

    def run_backtest_one(self, ftc_id: str, symbol: str = "BTC") -> dict | None:
        """对单条 FTC 跑回测"""
        ftc = self._ftcs.get(ftc_id)
        if not ftc:
            return None
        result = backtest_ftc(ftc, symbol)
        ftc.ess = result["ess"]
        ftc.n_samples = result["N"]
        return result

    def generate_new_combinations(self, n: int = 5, gmax: float = 0.3) -> list[FTC]:
        """
        从现有 FTC 池中生成新组合（基因重组 + gmax 变异）。
        新 FTC 自动对齐知识锚点并分轨。
        """
        pool = self.get_all_ftcs()
        new_ftcs = generate_combinations(pool, n_combinations=n, gmax=gmax)

        for ftc in new_ftcs:
            # 对齐知识锚点 + 分轨
            ftc.knowledge_alignment = align_to_anchors(ftc, top_k=3)
            ftc.track = get_track_by_similarity(ftc.max_similarity)
            self._ftcs[ftc.ftc_id] = ftc

        logger.info(f"[FTC] 生成 {len(new_ftcs)} 条新组合 FTC")
        return new_ftcs

    def promote_demote(self) -> dict:
        """
        探索池晋升/降级机制:
          - explore 轨道: ess >= 0.5 且 n_samples >= 300 → 升入 exploit
          - 任意轨道: ess < 0.3 且 n_samples >= 50 → 降级 discard
          - mixed 轨道: ess >= 0.6 且 n_samples >= 50 → 升入 exploit

        返回晋升/降级统计。
        """
        stats = {"promoted": 0, "demoted": 0, "unchanged": 0}

        for ftc in self._ftcs.values():
            if ftc.ess is None:
                stats["unchanged"] += 1
                continue

            old_track = ftc.track
            ess = ftc.ess
            n = ftc.n_samples

            # 晋升规则
            if old_track == "explore" and ess >= 0.5 and n >= 300:
                ftc.track = "exploit"
                stats["promoted"] += 1
            elif old_track == "mixed" and ess >= 0.6 and n >= 50:
                ftc.track = "exploit"
                stats["promoted"] += 1
            # 降级规则
            elif ess < 0.3 and n >= 50 and old_track != "discard":
                ftc.track = "discard"
                stats["demoted"] += 1
            else:
                stats["unchanged"] += 1

        logger.info(f"[FTC] 晋升/降级: {stats}")
        return stats

    def get_top_ftcs(self, n: int = 5) -> list[FTC]:
        """按 ESS 降序返回 top n FTC（仅 exploit 轨道）"""
        exploit = self.get_by_track("exploit")
        exploit = [f for f in exploit if f.ess is not None]
        exploit.sort(key=lambda f: f.ess, reverse=True)
        return exploit[:n]
