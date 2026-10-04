"""
C1 品种筛选节点

Classic Pipeline C0-C8 八阶段流水线第二阶段。
按 Stage A 硬过滤（流动性/数据完整性/carry risk）筛选候选币种。

迁移自 ml_trade_service.py L12053 _build_universe_stage_a 函数。

inputs:
    - 上游 C0: state.get_result("C0").outputs["env_state"] / ["regime"] / ["macro_flags"]（可选，仅用于决策上下文）
    - state.market: dict, 必须包含:
        - universe: list[dict], 全市场快照（每项含 name/szDecimals）
        - mids: dict[str, float], 币种→最新价格
        - stats: dict[str, dict], 币种→7d 统计（median_turnover/gap_rate/jump_rate/age_days）
    - state.config: dict, 可选覆盖阈值:
        - filter_min_turnover_7d: float (默认 50000.0)
        - filter_max_gap_rate: float (默认 0.02)
        - filter_min_age_days_shadow: float (默认 30.0)
        - universe_stage_a_relax_enabled: bool (默认 True)
        - universe_stage_a_relax_max_steps: int (默认 3)
        - universe_stage_a_relax_min_age_floor_days: float (默认 7.0)
        - universe_stage_a_relax_min_turnover_floor: float (默认 5000.0)
        - universe_stage_a_relax_max_gap_ceiling: float (默认 0.20)
        - universe_stage_a_target_min_candidates: int (默认 30)
outputs:
    - candidates: list[str] — 通过筛选的品种清单
    - filter_log: list[dict] — 各 relax 步骤的阈值与通过数记录
    - rejected: list[dict] — 被拒绝品种及原因，形如 {"coin": str, "reasons": list[str]}
    - symbols_total: int — universe 总数
    - mids_total: int — 有价格的币种数
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult, NodeStatus


# ── 默认阈值（与 ml_trade_service.py CONFIG 保持一致） ──────
_DEFAULT_FILTER_MIN_TURNOVER = 50000.0
_DEFAULT_FILTER_MAX_GAP = 0.02
_DEFAULT_FILTER_MIN_AGE_SHADOW = 30.0
_DEFAULT_RELAX_ENABLED = True
_DEFAULT_RELAX_MAX_STEPS = 3
_DEFAULT_RELAX_MIN_AGE_FLOOR = 7.0
_DEFAULT_RELAX_MIN_TURNOVER_FLOOR = 5000.0
_DEFAULT_RELAX_MAX_GAP_CEILING = 0.20
_DEFAULT_TARGET_MIN = 30


def _clip(value: float, low: float, high: float) -> float:
    """将 value 截断到 [low, high] 区间"""
    if not math.isfinite(float(value)):
        return float(low)
    if float(value) < float(low):
        return float(low)
    if float(value) > float(high):
        return float(high)
    return float(value)


class C1SymbolFilterNode(BaseNode):
    """C1 品种筛选节点

    Stage A 硬过滤逻辑迁移自 ml_trade_service.py _build_universe_stage_a。
    下游 C2 通过 state.get_result("C1").outputs["candidates"] 访问。

    设计原则（遵循优雅改动原则）：
    - 不依赖全局 CONFIG / UNIVERSE_STATE / _get_coin_stats_7d / _find_pair_files
    - 所有输入通过 state.market + state.config 提供
    - 无 market 时降级返回 SUCCESS + 空 candidates（FAIL-OPEN）
    - relax 阶梯与 fallback 逻辑与原实现保持一致
    """

    node_id = "C1"
    name = "品种筛选"
    description = "Stage A 硬过滤（流动性/数据完整性/carry risk）筛选候选币种"
    chain = "C"
    tags = ["classic", "classic_v2", "symbol_filter", "stage_a"]
    estimated_tokens = 0
    estimated_latency_ms = 0

    # ── 配置读取 ──────────────────────────────────────────
    @staticmethod
    def _read_config(state: State) -> Dict[str, Any]:
        """从 state.config 读取阈值，缺失则用默认值"""
        cfg = state.config or {}

        def _get_float(key: str, default: float) -> float:
            try:
                v = float(cfg.get(key, default))
                if not math.isfinite(v):
                    return float(default)
                return v
            except Exception:
                return float(default)

        def _get_int(key: str, default: int) -> int:
            try:
                return int(cfg.get(key, default) or default)
            except Exception:
                return int(default)

        def _get_bool(key: str, default: bool) -> bool:
            try:
                return bool(cfg.get(key, default))
            except Exception:
                return bool(default)

        return {
            "min_turnover": _get_float("filter_min_turnover_7d", _DEFAULT_FILTER_MIN_TURNOVER),
            "max_gap": _get_float("filter_max_gap_rate", _DEFAULT_FILTER_MAX_GAP),
            "min_age_shadow": _get_float("filter_min_age_days_shadow", _DEFAULT_FILTER_MIN_AGE_SHADOW),
            "relax_enabled": _get_bool("universe_stage_a_relax_enabled", _DEFAULT_RELAX_ENABLED),
            "relax_steps": max(0, min(10, _get_int("universe_stage_a_relax_max_steps", _DEFAULT_RELAX_MAX_STEPS))),
            "min_age_floor": max(0.0, _get_float("universe_stage_a_relax_min_age_floor_days", _DEFAULT_RELAX_MIN_AGE_FLOOR)),
            "turnover_floor": max(0.0, _get_float("universe_stage_a_relax_min_turnover_floor", _DEFAULT_RELAX_MIN_TURNOVER_FLOOR)),
            "gap_ceiling": _clip(_get_float("universe_stage_a_relax_max_gap_ceiling", _DEFAULT_RELAX_MAX_GAP_CEILING), 0.001, 0.99),
            "target_min": _get_int("universe_stage_a_target_min_candidates", _DEFAULT_TARGET_MIN),
        }

    @staticmethod
    def _build_rows(market: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], int, int]:
        """从 state.market 构造统一的 rows 表，并统计 symbols_total/mids_total"""
        universe = market.get("universe") or []
        mids = market.get("mids") or {}
        stats = market.get("stats") or {}

        if not isinstance(universe, list):
            universe = []
        if not isinstance(mids, dict):
            mids = {}
        if not isinstance(stats, dict):
            stats = {}

        symbols_total = len(universe)
        rows: List[Dict[str, Any]] = []
        mids_total = 0

        for coin_meta in universe:
            if not isinstance(coin_meta, dict):
                continue
            name = str(coin_meta.get("name") or "").strip().upper()
            if not name:
                continue
            try:
                px = float(mids.get(name, 0.0))
            except Exception:
                px = 0.0
            if px > 0:
                mids_total += 1
            coin_stats = stats.get(name) or {}
            if not isinstance(coin_stats, dict):
                coin_stats = {}
            try:
                turnover = float(coin_stats.get("median_turnover", 0.0) or 0.0)
            except Exception:
                turnover = 0.0
            try:
                gap = float(coin_stats.get("gap_rate", 1.0) or 1.0)
            except Exception:
                gap = 1.0
            try:
                jump = float(coin_stats.get("jump_rate", 0.0) or 0.0)
            except Exception:
                jump = 0.0
            try:
                age = float(coin_stats.get("age_days", 0.0) or 0.0)
            except Exception:
                age = 0.0
            rows.append({
                "coin": name,
                "px": px,
                "turnover": turnover,
                "gap": gap,
                "jump": jump,
                "age": age,
                "sz_decimals": coin_meta.get("szDecimals"),
            })

        return rows, symbols_total, mids_total

    @staticmethod
    def _apply(
        rows: List[Dict[str, Any]],
        min_turnover: float,
        max_gap: float,
        min_age_shadow: float,
    ) -> Tuple[List[str], List[Dict[str, Any]]]:
        """Stage A 硬过滤主逻辑

        返回 (valid_coins, rejected_records)
        rejected_records 形如 [{"coin": str, "reasons": [str]}, ...]
        """
        valid_coins: List[str] = []
        rejected: List[Dict[str, Any]] = []

        for r in rows:
            name = str(r.get("coin") or "").strip().upper()
            if not name:
                continue
            reasons: List[str] = []
            try:
                px = float(r.get("px") or 0.0)
            except Exception:
                px = 0.0
            if px <= 0.0:
                reasons.append("no_price")
            else:
                try:
                    turnover = float(r.get("turnover") or 0.0)
                except Exception:
                    turnover = 0.0
                try:
                    gap = float(r.get("gap") or 1.0)
                except Exception:
                    gap = 1.0
                try:
                    jump = float(r.get("jump") or 0.0)
                except Exception:
                    jump = 0.0
                try:
                    age = float(r.get("age") or 0.0)
                except Exception:
                    age = 0.0

                if turnover < float(min_turnover):
                    reasons.append(f"low_turnover_{int(turnover)}")
                if gap > float(max_gap) and gap < 0.999:
                    reasons.append(f"high_gap_{round(gap, 3)}")
                if jump > 0.10 and jump < 0.999:
                    reasons.append(f"unstable_jumps_{round(jump, 3)}")
                if age > 0.0 and age < float(min_age_shadow):
                    reasons.append(f"too_young_{int(age)}")

            if reasons:
                rejected.append({"coin": name, "reasons": reasons})
            else:
                valid_coins.append(name)

        return valid_coins, rejected

    @staticmethod
    def _fallback_to_major(mids: Dict[str, float]) -> List[str]:
        """无候选时 fallback 到 BTC/ETH/SOL 中有价格的"""
        fallback: List[str] = []
        for c in ("BTC", "ETH", "SOL"):
            try:
                if float(mids.get(c, 0.0)) > 0:
                    fallback.append(c)
            except Exception:
                continue
        return fallback

    def execute_core(self, state: State) -> NodeResult:
        """执行 Stage A 硬过滤

        流程：
            1. 读取 state.market + state.config
            2. 构造 rows 表
            3. _apply 初次过滤（strict 阈值）
            4. 若 candidates < target_min 且 relax_enabled，按 0.5^step 放宽阈值重试
            5. 若仍无候选，fallback 到 BTC/ETH/SOL
        """
        # FAIL-OPEN：无 market 时降级
        market = state.market if isinstance(state.market, dict) else None
        if market is None:
            return NodeResult(
                node_id="C1",
                status=NodeStatus.SUCCESS,
                confidence=0.0,
                outputs={
                    "candidates": [],
                    "filter_log": [],
                    "rejected": [],
                    "symbols_total": 0,
                    "mids_total": 0,
                },
                error="C1 无 market 数据，降级返回空 candidates",
            )

        # 1. 读取配置
        cfg = self._read_config(state)

        # 2. 构造 rows
        rows, symbols_total, mids_total = self._build_rows(market)

        # 3. 初次过滤（step 0, strict 阈值）
        min_turnover0 = cfg["min_turnover"]
        max_gap0 = cfg["max_gap"]
        min_age_shadow0 = cfg["min_age_shadow"]

        best_coins, best_rejected = self._apply(rows, min_turnover0, max_gap0, min_age_shadow0)
        step_counts: Dict[str, int] = {"0": len(best_coins)}
        filter_log: List[Dict[str, Any]] = [{
            "step": 0,
            "min_turnover": float(min_turnover0),
            "max_gap": float(max_gap0),
            "min_age_shadow": float(min_age_shadow0),
            "candidates": len(best_coins),
        }]
        rejected_accum: Dict[str, List[str]] = {r["coin"]: list(r["reasons"]) for r in best_rejected}

        # 4. relax 阶梯
        target_min = cfg["target_min"]
        if cfg["relax_enabled"] and len(best_coins) < int(target_min):
            for step in range(1, int(cfg["relax_steps"]) + 1):
                mult_turn = max(0.0, 0.5 ** float(step))
                min_turn = max(float(cfg["turnover_floor"]), float(min_turnover0) * float(mult_turn))
                max_gap = min(float(cfg["gap_ceiling"]), float(max_gap0) * float(2.0 ** float(step)))
                min_age = max(float(cfg["min_age_floor"]), float(min_age_shadow0) * float(mult_turn))

                coins_i, rejected_i = self._apply(rows, min_turn, max_gap, min_age)
                step_counts[str(step)] = len(coins_i)
                filter_log.append({
                    "step": int(step),
                    "min_turnover": float(min_turn),
                    "max_gap": float(max_gap),
                    "min_age_shadow": float(min_age),
                    "candidates": len(coins_i),
                })
                # 累积 rejected（更宽松步骤的拒绝原因覆盖严格步骤）
                for r in rejected_i:
                    rejected_accum[r["coin"]] = list(r["reasons"])

                if len(coins_i) > len(best_coins):
                    best_coins = coins_i
                if len(best_coins) >= int(target_min):
                    break

        # 5. fallback
        if not best_coins:
            mids = market.get("mids") or {}
            if not isinstance(mids, dict):
                mids = {}
            best_coins = self._fallback_to_major(mids)

        # 组装 rejected 列表
        rejected_list = [
            {"coin": coin, "reasons": reasons}
            for coin, reasons in rejected_accum.items()
        ]

        # 计算 confidence（候选数 / target_min, [0, 1]）
        confidence = float(_clip(len(best_coins) / max(1, int(target_min)), 0.0, 1.0))

        return NodeResult(
            node_id="C1",
            status=NodeStatus.SUCCESS,
            confidence=confidence,
            outputs={
                "candidates": best_coins,
                "filter_log": filter_log,
                "rejected": rejected_list,
                "symbols_total": int(symbols_total),
                "mids_total": int(mids_total),
            },
        )
