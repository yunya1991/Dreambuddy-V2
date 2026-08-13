"""B-series Yijing signal generator — I Ching reasoning engine for DreamOS.

Core responsibility:
    1. Receive market data (scores, indicators, price position)
    2. Build inner/outer trigrams from four-dimensional scores
    3. Combine into 64-hexagram, compute moving yaos
    4. Produce directional signal (LONG/SHORT/HOLD) with confidence

Integration:
    - Input: CoinSelector pools + market data
    - Output: YijingSignal with direction, confidence, hexagram info
    - Node: YijingSignalGeneratorNode for DreamOS orchestration
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import math


# ── Trigram constants (3-bit → 8 trigrams) ─────────────────────

TRIGRAM_NAMES = [
    "Qian",   # 111 - Heaven
    "Dui",    # 110 - Lake
    "Li",     # 101 - Fire
    "Zhen",   # 100 - Thunder
    "Xun",    # 011 - Wind
    "Kan",    # 010 - Water
    "Gen",    # 001 - Mountain
    "Kun",    # 000 - Earth
]

TRIGRAM_DIRECTIONS = {
    "Qian": "UP",
    "Dui": "UP",
    "Li": "UP",
    "Zhen": "UP",
    "Xun": "DOWN",
    "Kan": "DOWN",
    "Gen": "DOWN",
    "Kun": "DOWN",
}

# 64 hexagram names (inner=rows, outer=cols)
HEXAGRAM_NAMES = {
    ("Qian", "Qian"): "Qian_1",
    ("Kun", "Kun"): "Kun_2",
    ("Zhen", "Qian"): "Da_Zhuang_34",
    ("Kun", "Qian"): "Pi_12",
    ("Qian", "Kun"): "Tai_11",
    ("Qian", "Zhen"): "Da_Yu_14",
    ("Zhen", "Kun"): "Yu_16",
    ("Qian", "Xun"): "Xiao_Xu_9",
    ("Xun", "Qian"): "Gu_18",
    ("Qian", "Kan"): "Xu_5",
    ("Kan", "Qian"): "Song_6",
    ("Qian", "Gen"): "Da_Xu_26",
    ("Gen", "Qian"): "Bo_23",
    ("Qian", "Dui"): "Guai_43",
    ("Dui", "Qian"): "Lin_19",
    ("Qian", "Li"): "Da_You_14",
    ("Li", "Qian"): "Tong_Ren_13",
    ("Kun", "Zhen"): "Fu_24",
    ("Zhen", "Zhen"): "Zhen_51",
    ("Xun", "Zhen"): "Yi_27",
    ("Kan", "Zhen"): "Tun_3",
    ("Gen", "Zhen"): "Xiao_Guo_62",
    ("Dui", "Zhen"): "Gui_Mei_54",
    ("Li", "Zhen"): "Feng_55",
    ("Kun", "Xun"): "Guan_20",
    ("Zhen", "Xun"): "Heng_32",
    ("Xun", "Xun"): "Xun_57",
    ("Kan", "Xun"): "Jing_48",
    ("Gen", "Xun"): "Jian_39",
    ("Dui", "Xun"): "Zhong_Fu_61",
    ("Li", "Xun"): "Jia_Ren_37",
    ("Kun", "Kan"): "Shi_7",
    ("Zhen", "Kan"): "Jie_40",
    ("Xun", "Kan"): "Huan_59",
    ("Kan", "Kan"): "Kan_29",
    ("Gen", "Kan"): "Meng_4",
    ("Dui", "Kan"): "Kun_47",
    ("Li", "Kan"): "Wei_Ji_64",
    ("Kun", "Gen"): "Sheng_46",
    ("Zhen", "Gen"): "Xiao_Guo_62",
    ("Xun", "Gen"): "Jian_39",
    ("Kan", "Gen"): "Meng_4",
    ("Gen", "Gen"): "Gen_52",
    ("Dui", "Gen"): "Sun_41",
    ("Li", "Gen"): "Lü_56",
    ("Kun", "Dui"): "Lin_19",
    ("Zhen", "Dui"): "Gui_Mei_54",
    ("Xun", "Dui"): "Zhong_Fu_61",
    ("Kan", "Dui"): "Kun_47",
    ("Gen", "Dui"): "Sun_41",
    ("Dui", "Dui"): "Dui_58",
    ("Li", "Dui"): "Kui_38",
    ("Kun", "Li"): "Ming_Yi_36",
    ("Zhen", "Li"): "Feng_55",
    ("Xun", "Li"): "Jia_Ren_37",
    ("Kan", "Li"): "Wei_Ji_64",
    ("Gen", "Li"): "Lü_56",
    ("Dui", "Li"): "Kui_38",
    ("Li", "Li"): "Li_30",
}

# Phase boundaries for six-yao positioning
PHASE_BOUNDARIES = [0.15, 0.30, 0.45, 0.55, 0.70, 0.85]


class YijingSignalGenerator:
    """Yijing-based signal generator for DreamOS.

    Encapsulates I Ching reasoning: four-dimensional scores → trigrams →
    hexagram → moving yaos → directional signal with confidence.
    """

    def __init__(self, seed: Optional[int] = None):
        """Initialize the signal generator.

        Args:
            seed: Optional PRNG seed for reproducible hexagram casting.
        """
        self._seed = seed
        self._inner_thresholds: Tuple[float, float, float] = (0.35, 0.55, 0.65)
        self._outer_thresholds: Tuple[float, float, float] = (0.35, 0.55, 0.65)

    def generate(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a Yijing signal from market data.

        Args:
            market_data: Dict with keys:
                symbol, supply_demand_score, technical_score,
                capital_flow_score, sentiment_score,
                trend_strength, volatility, volume_ratio,
                price_position, ma5, ma10, ma20,
                momentum_direction, close_price

        Returns:
            {
                "symbol": "BTC",
                "direction": "LONG" | "SHORT" | "HOLD",
                "confidence": 0.0-1.0,
                "hexagram": {
                    "original_gua": "Qian_1",
                    "changed_gua": "...",
                    "moving_yaos": [2, 4],
                    "inner_gua": "Qian",
                    "outer_gua": "Kun",
                },
                "phase": "see-dragon",
                "risk_level": "medium",
                "timestamp": "...",
                "source": "yijing",
            }
        """
        symbol = market_data.get("symbol", "UNKNOWN")

        # Extract four-dimensional scores
        sd = market_data.get("supply_demand_score", 0.5)
        tech = market_data.get("technical_score", 0.5)
        cap = market_data.get("capital_flow_score", 0.5)
        sent = market_data.get("sentiment_score", 0.5)

        trend = market_data.get("trend_strength", 0.5)
        vol = market_data.get("volatility", 0.3)
        vr = market_data.get("volume_ratio", 1.0)
        pp = market_data.get("price_position", 0.5)

        ma5 = market_data.get("ma5", 0.0)
        ma10 = market_data.get("ma10", 0.0)
        ma20 = market_data.get("ma20", 0.0)
        mom_dir = market_data.get("momentum_direction", "FLAT")

        # Build inner trigram (essence: supply_demand + technical)
        inner_bits = self._score_to_trigram(sd, tech)
        inner_gua = TRIGRAM_NAMES[inner_bits]

        # Build outer trigram (environment: capital_flow + sentiment)
        outer_bits = self._score_to_trigram(cap, sent)
        outer_gua = TRIGRAM_NAMES[outer_bits]

        # Combine into 64-hexagram
        original_name = HEXAGRAM_NAMES.get(
            (inner_gua, outer_gua),
            f"{inner_gua}_{outer_gua}",
        )

        # Compute moving yaos
        moving_yaos = self._compute_moving_yaos(
            trend, vol, vr, pp, self._seed
        )

        # Compute changed hexagram
        changed_gua = self._compute_changed_gua(
            inner_gua, outer_gua, moving_yaos
        )
        changed_name = HEXAGRAM_NAMES.get(
            (changed_gua[0], changed_gua[1]),
            f"{changed_gua[0]}_{changed_gua[1]}",
        )

        # Direction via weighted voting
        direction = self._compute_direction(
            sd, tech, cap, sent, ma5, ma10, ma20, mom_dir,
            inner_gua, outer_gua, changed_gua,
        )

        # Confidence
        confidence = self._compute_confidence(
            direction, trend, vol, sd, tech, cap, sent,
            inner_gua, outer_gua, moving_yaos,
        )

        # Phase positioning
        phase = self._compute_phase(pp, direction)

        # Risk level
        risk = self._compute_risk(vol, pp, confidence)

        return {
            "symbol": symbol,
            "direction": direction,
            "confidence": round(confidence, 4),
            "hexagram": {
                "original_gua": original_name,
                "changed_gua": changed_name,
                "moving_yaos": moving_yaos,
                "inner_gua": inner_gua,
                "outer_gua": outer_gua,
            },
            "phase": phase,
            "risk_level": risk,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "source": "yijing",
        }

    def generate_from_pools(
        self,
        pools: Dict[str, Any],
        market_data_batch: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Generate Yijing signals for all symbols in coin pools.

        Args:
            pools: CoinSelector output with long_pool and short_pool.
            market_data_batch: Dict mapping symbol to market_data dict.

        Returns:
            {
                "long_signals": [signal, ...],
                "short_signals": [signal, ...],
                "timestamp": "...",
                "source": "yijing",
            }
        """
        long_signals: List[Dict[str, Any]] = []
        short_signals: List[Dict[str, Any]] = []

        for item in pools.get("long_pool", []):
            sym = item.get("symbol", "")
            md = market_data_batch.get(sym)
            if md is None:
                continue
            signal = self.generate(md)
            signal["pool_score"] = item.get("score", 0.0)
            signal["pool_reasons"] = item.get("reasons", [])
            long_signals.append(signal)

        for item in pools.get("short_pool", []):
            sym = item.get("symbol", "")
            md = market_data_batch.get(sym)
            if md is None:
                continue
            signal = self.generate(md)
            signal["pool_score"] = item.get("score", 0.0)
            signal["pool_reasons"] = item.get("reasons", [])
            short_signals.append(signal)

        return {
            "long_signals": long_signals,
            "short_signals": short_signals,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "source": "yijing",
        }

    def _score_to_trigram(self, score1: float, score2: float) -> int:
        """Convert two scores to a 3-bit trigram index.

        Uses thresholds to determine yin (0) / yang (1) lines.
        Bottom line: score1 vs threshold[0]
        Middle line: score2 vs threshold[1]
        Top line: combined avg vs threshold[2]
        """
        t0, t1, t2 = self._inner_thresholds
        bottom = 1 if score1 > t0 else 0
        middle = 1 if score2 > t1 else 0
        avg = (score1 + score2) / 2
        top = 1 if avg > t2 else 0
        return (top << 2) | (middle << 1) | bottom

    def _compute_moving_yaos(
        self, trend: float, vol: float, vr: float,
        pp: float, seed: Optional[int],
    ) -> List[int]:
        """Compute moving yaos using coin-cast method with market modulation."""
        import random
        rng = random.Random(seed) if seed is not None else random.Random()

        # Base probability from coin method
        base_p = 0.375

        # Market modulation
        mod = 1.0 + (vol - 0.3) * 0.5 + (vr - 1.0) * 0.2 + (trend - 0.5) * 0.3
        mod = max(0.5, min(2.0, mod))

        moving = []
        for i in range(6):
            p = min(0.85, base_p * mod)
            if rng.random() < p:
                moving.append(i)

        # Price position determines primary moving yao
        if pp < 0.15:
            primary = 0  # bottom yao
        elif pp < 0.30:
            primary = 1
        elif pp < 0.45:
            primary = 2
        elif pp < 0.55:
            primary = 3
        elif pp < 0.70:
            primary = 4
        elif pp < 0.85:
            primary = 5
        else:
            primary = 5  # top yao

        if primary not in moving and len(moving) < 3:
            moving.append(primary)

        # Limit to 3 moving yaos
        return sorted(moving[:3])

    def _compute_changed_gua(
        self, inner: str, outer: str, moving: List[int],
    ) -> Tuple[str, str]:
        """Compute changed hexagram by flipping moving yaos."""
        # Get trigram bits
        inner_idx = TRIGRAM_NAMES.index(inner)
        outer_idx = TRIGRAM_NAMES.index(outer)

        # Full 6-yao: bottom 3 = inner, top 3 = outer
        yaos = []
        for i in range(3):
            yaos.append((inner_idx >> i) & 1)
        for i in range(3):
            yaos.append((outer_idx >> i) & 1)

        # Flip moving yaos
        for idx in moving:
            if idx < 6:
                yaos[idx] = 1 - yaos[idx]

        # Reconstruct trigrams
        new_inner = sum(yaos[i] << i for i in range(3))
        new_outer = sum(yaos[i + 3] << i for i in range(3))

        new_inner_name = TRIGRAM_NAMES[new_inner]
        new_outer_name = TRIGRAM_NAMES[new_outer]

        return (new_inner_name, new_outer_name)

    def _compute_direction(
        self, sd: float, tech: float, cap: float, sent: float,
        ma5: float, ma10: float, ma20: float, mom_dir: str,
        inner: str, outer: str, changed: Tuple[str, str],
    ) -> str:
        """Compute direction via weighted voting."""
        # Four-dimensional score (weight: 0.35)
        four_dim = (sd + tech + cap + sent) / 4
        four_dim_dir = 1 if four_dim > 0.5 else -1

        # MA alignment (weight: 0.25)
        if ma5 > ma10 > ma20:
            ma_dir = 1
        elif ma5 < ma10 < ma20:
            ma_dir = -1
        else:
            ma_dir = 0

        # Hexagram direction (weight: 0.20)
        inner_dir = TRIGRAM_DIRECTIONS.get(inner, "UP")
        outer_dir = TRIGRAM_DIRECTIONS.get(outer, "UP")
        hex_dir = 1 if (inner_dir == "UP" and outer_dir == "UP") else \
                  (-1 if (inner_dir == "DOWN" and outer_dir == "DOWN") else 0)

        # Changed hexagram direction (weight: 0.15)
        changed_inner_dir = TRIGRAM_DIRECTIONS.get(changed[0], "UP")
        changed_outer_dir = TRIGRAM_DIRECTIONS.get(changed[1], "UP")
        changed_dir = 1 if (changed_inner_dir == "UP" and changed_outer_dir == "UP") else \
                      (-1 if (changed_inner_dir == "DOWN" and changed_outer_dir == "DOWN") else 0)

        # Momentum direction (weight: 0.05)
        mom = 1 if mom_dir == "UP" else (-1 if mom_dir == "DOWN" else 0)

        # Weighted sum
        score = (
            four_dim_dir * 0.35 +
            ma_dir * 0.25 +
            hex_dir * 0.20 +
            changed_dir * 0.15 +
            mom * 0.05
        )

        if score > 0.15:
            return "LONG"
        elif score < -0.15:
            return "SHORT"
        else:
            return "HOLD"

    def _compute_confidence(
        self, direction: str, trend: float, vol: float,
        sd: float, tech: float, cap: float, sent: float,
        inner: str, outer: str, moving: List[int],
    ) -> float:
        """Compute confidence score."""
        # Base confidence from hexagram clarity
        inner_dir = TRIGRAM_DIRECTIONS.get(inner, "UP")
        outer_dir = TRIGRAM_DIRECTIONS.get(outer, "UP")
        if inner_dir == outer_dir:
            base = 0.75
        else:
            base = 0.50

        # Moving yao penalty
        yao_penalty = 1.0 - len(moving) * 0.10

        # Trend strength
        trend_factor = max(0.3, min(1.0, trend))

        # Four-dim consistency
        scores = [sd, tech, cap, sent]
        avg = sum(scores) / 4
        variance = sum((s - avg) ** 2 for s in scores) / 4
        consistency = 1.0 - min(1.0, variance * 4)

        # Direction clarity
        if direction == "HOLD":
            clarity = 0.5
        else:
            clarity = 0.8

        confidence = base * yao_penalty * trend_factor * consistency * clarity
        return max(0.0, min(1.0, confidence))

    def _compute_phase(self, price_position: float, direction: str) -> str:
        """Compute six-yao phase from price position."""
        if price_position < 0.15:
            return "hidden-dragon"  # qian long wu yong
        elif price_position < 0.30:
            return "see-dragon"  # jian long zai tian
        elif price_position < 0.45:
            return "active-dragon"  # jun zi zhong ri qian qian
        elif price_position < 0.55:
            return "leaping-dragon"  # huo yuan zai yuan
        elif price_position < 0.70:
            return "flying-dragon"  # fei long zai tian
        elif price_position < 0.85:
            return "over-reaching"  # kang long you hui
        else:
            return "excessive"  # beyond

    def _compute_risk(
        self, vol: float, price_position: float, confidence: float,
    ) -> str:
        """Compute risk level."""
        risk_score = vol * 0.4 + abs(price_position - 0.5) * 0.3 + (1 - confidence) * 0.3
        if risk_score < 0.3:
            return "low"
        elif risk_score < 0.6:
            return "medium"
        else:
            return "high"
