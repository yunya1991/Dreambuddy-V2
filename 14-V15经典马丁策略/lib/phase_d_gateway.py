"""
Phase D Gateway — BiLSTM-Attention 爆仓预警 + PatchTST 回撤预测 的三大闸门实现

严格对齐 AI_ENHANCEMENT_ROADMAP.md §4.2 输出空间 & §3.3 边界：
  G-D1 (Skip Open)  : PatchTST 预测回撤 ≤ -32%  或  BiLSTM P_bust ≥ 0.60 → 不开首单
  G-D2 (Trim Addons): BiLSTM P_bust ≥ 0.55 → max_addons_eff = max(1, baseline-1)（丢弃最深档）
  G-D3 (Timing Relax): regime=UNCLEAR  AND  patchtst_drawdown > -10%  AND  P_bust < 0.30
                        → timing_score × ≤1.05 放宽，size_power × ≥0.90 放宽（惩罚减弱）

最高优先级铁律 (§3.3 最后一行):
    **AI 只能否决开仓或微调，永远不能在基线判定 WAIT 时强制开仓**
"""

from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


# ================================================================
# §3.3 双层 clamp（相对边界 + 绝对铁壳）—— 纯函数独立导出
# ================================================================
def apply_iron_clamp(
    ai_value: float,
    baseline_value: float,
    relative_lower: float,
    relative_upper: float,
    absolute_lo: float,
    absolute_hi: float,
) -> float:
    """§3.3 通用 clamp 公式：先相对边界，再绝对铁壳

    Args:
        ai_value:          模型输出原始建议
        baseline_value:    v15-final 基线决策值 (X_base)
        relative_lower:    下边界倍率，如 0.70 表示最多降到基线 70%
        relative_upper:    上边界倍率，如 1.20 表示最多升到基线 120%
        absolute_lo:       外层铁壳下限（任何情况不能低于此绝对值）
        absolute_hi:       外层铁壳上限（任何情况不能高于此绝对值）

    Returns:
        双层 clamp 后的最终生效值
    """
    if baseline_value == 0:
        # 防除 0：退化为只有绝对铁壳
        lo, hi = absolute_lo, absolute_hi
    else:
        lo = baseline_value * relative_lower
        hi = baseline_value * relative_upper
    step1 = max(lo, min(hi, float(ai_value)))
    step2 = max(float(absolute_lo), min(float(absolute_hi), step1))
    return step2


def clamp_max_addons_delta(ai_delta: int, current_max: int) -> int:
    """§3.3 max_addons 专用 clamp：只允许 {-1, 0}，绝不允许 +1（扩到第 5 档）

    同时 -1 是最小缩档（不能一下缩 2 档）。
    """
    if ai_delta >= 1:
        # 硬拒绝：AI 试图扩档到 5（或更多）→ 完全不生效，保持 current_max 不变
        return current_max
    if ai_delta <= -2:
        # 一下缩 2 档太激进，只允许 -1（按 LOWER=-1 档）
        return max(1, current_max - 1)
    # ai_delta in (-1, 0)
    return max(1, current_max + int(ai_delta))


# ================================================================
# Phase D Gateway 类
# ================================================================
@dataclass
class PhaseDGateway:
    """
    实盘/回测通用闸门。加载失败时 Phase 关闭保证字节等价基线。

    Args:
        enabled:              V15_AI_ENABLED and V15_AI_PHASE_D_ENABLED（默认 False，等价基线）
        bilstm_model_path:    模型权重文件路径；None = 走 mock 或禁用
        patchtst_model_path:  同上
        g_d1_drawdown_threshold:   PatchTST 触发 G-D1 的阈值（默认 -32% = 5 单马丁总跨度）
        g_d1_bust_threshold:       BiLSTM 爆仓概率触发 G-D1 的阈值（默认 0.60）
        g_d2_bust_threshold:       BiLSTM 爆仓概率触发 G-D2 缩档（默认 0.55）
        g_d3_drawdown_threshold:   UNCLEAR 放松所需「浅回撤」阈值（默认 > -10%）
        g_d3_bust_threshold:       UNCLEAR 放松所需「低爆仓风险」阈值（默认 < 0.30）
        g_d3_max_score_relax:      G-D3 最多放松 timing_score 的倍数（默认 ≤1.05）
        g_d3_min_power_shrink:     G-D3 最多放宽 size_power 的比率（默认 ≥0.90，乘到原值上得更小=更宽容）
    """

    enabled: bool = False
    bilstm_model_path: Optional[str] = None
    patchtst_model_path: Optional[str] = None
    g_d1_drawdown_threshold: float = -0.32
    g_d1_bust_threshold: float = 0.60
    g_d2_bust_threshold: float = 0.55
    g_d3_drawdown_threshold: float = -0.10
    g_d3_bust_threshold: float = 0.30
    g_d3_max_score_relax: float = 1.05
    g_d3_min_power_shrink: float = 0.90

    # ---- TDD / 诊断辅助字段（不参与启用逻辑） ----
    last_gate_code: Optional[str] = field(default=None, repr=False)
    _mock_bilstm: Optional[float] = field(default=None, repr=False)  # 仅 _for_testing_use_mock_predictor 用
    _mock_patchtst: Optional[float] = field(default=None, repr=False)

    # ---- 真实模型懒加载缓存（首次推理时加载，之后复用） ----
    _bilstm_model: Any = field(default=None, repr=False)
    _bilstm_meta: Optional[Dict] = field(default=None, repr=False)
    _patchtst_model: Any = field(default=None, repr=False)
    _patchtst_meta: Optional[Dict] = field(default=None, repr=False)

    # ================================================================
    # TDD 工厂：用 mock 预测值（不加载真实模型），便于单测
    # ================================================================
    @classmethod
    def _for_testing_use_mock_predictor(
        cls,
        mock_patchtst_drawdown: float,
        mock_bilstm_p_bust: float,
    ) -> "PhaseDGateway":
        return cls(
            enabled=True,
            _mock_patchtst=float(mock_patchtst_drawdown),
            _mock_bilstm=float(mock_bilstm_p_bust),
        )

    # ================================================================
    # 预测函数：真实模型优先 → mock → heuristic ctx → 中性兜底
    # ================================================================
    def _predict_patchtst_drawdown(self, ctx: Dict[str, Any]) -> float:
        """PatchTST: 预测未来 24 根 1H K 线 max drawdown (负值, -1=-100%)"""
        if not self.enabled:
            return -0.0
        # 1. 真实模型推理（权重存在时优先）
        if self.patchtst_model_path and os.path.isfile(self.patchtst_model_path):
            try:
                return self._run_real_patchtst(ctx)
            except Exception:
                pass  # 推理失败 → 降级
        # 2. Mock（TDD 场景）
        if self._mock_patchtst is not None:
            return float(self._mock_patchtst)
        # 3. Heuristic ctx 预估值（MVP 桥接）
        if ctx and "p_dd" in ctx:
            _v = float(ctx["p_dd"])
            return -abs(_v) if _v > 0 else _v
        return -0.0

    def _predict_bilstm_p_bust(self, ctx: Dict[str, Any]) -> float:
        """BiLSTM-Attention: 爆仓概率 P([0,1])"""
        if not self.enabled:
            return 0.0
        # 1. 真实模型推理（权重存在时优先）
        if self.bilstm_model_path and os.path.isfile(self.bilstm_model_path):
            try:
                return self._run_real_bilstm(ctx)
            except Exception:
                pass  # 推理失败 → 降级
        # 2. Mock（TDD 场景）
        if self._mock_bilstm is not None:
            return float(self._mock_bilstm)
        # 3. Heuristic ctx 预估值（MVP 桥接）
        if ctx and "p_bust" in ctx:
            return float(ctx["p_bust"])
        return 0.0

    # ================================================================
    # 真实模型推理：懒加载 + 特征工程 + 前向传播
    # ================================================================

    @staticmethod
    def _parse_klines(raw_klines: list, key_map: dict = None) -> list:
        """将 OKX/Hyperliquid klines 统一为 [{o,h,l,c,v}, ...] 列表"""
        if not raw_klines:
            return []
        default_map = {"o": "o", "h": "h", "l": "l", "c": "c", "v": "vol"}
        km = key_map or default_map
        out = []
        for k in raw_klines:
            if isinstance(k, dict):
                o = float(k.get(km["o"], k.get("o", 0)))
                h = float(k.get(km["h"], k.get("h", 0)))
                lo = float(k.get(km["l"], k.get("l", 0)))
                c = float(k.get(km["c"], k.get("c", 0)))
                v = float(k.get(km["v"], k.get("v", k.get("vol", 0))))
                out.append({"o": o, "h": h, "l": lo, "c": c, "v": v})
            elif isinstance(k, (list, tuple)) and len(k) >= 5:
                out.append({"o": float(k[1]), "h": float(k[2]), "l": float(k[3]),
                            "c": float(k[4]), "v": float(k[5]) if len(k) > 5 else 0.0})
        return out

    @staticmethod
    def _ohlcv_to_array(candles: list, n_bars: int) -> "Any":
        """从 candle list 取最后 n_bars 根，转为 (1, n_bars, 5) numpy float32"""
        import numpy as np
        if len(candles) < n_bars:
            pad = [candles[0]] * (n_bars - len(candles)) if candles else \
                [{"o": 1.0, "h": 1.0, "l": 1.0, "c": 1.0, "v": 0.0}] * n_bars
            candles = pad + candles
        arr = np.array(
            [[b["o"], b["h"], b["l"], b["c"], b["v"]] for b in candles[-n_bars:]],
            dtype=np.float32,
        )
        return arr[None, :, :]  # (1, n_bars, 5)

    @staticmethod
    def _compute_atr(candles_4h: list, period: int = 14) -> float:
        """从 4H candle list 计算 ATR"""
        if len(candles_4h) < period + 1:
            return abs(candles_4h[-1]["h"] - candles_4h[-1]["l"]) if candles_4h else 0.0
        trs = []
        for i in range(len(candles_4h) - period, len(candles_4h)):
            h, l, pc = candles_4h[i]["h"], candles_4h[i]["l"], candles_4h[i - 1]["c"]
            tr = max(h - l, abs(h - pc), abs(l - pc))
            trs.append(tr)
        return sum(trs) / len(trs)

    def _build_bilstm_scalar(self, ctx: Dict[str, Any], candles_4h: list) -> "Any":
        """构造 BiLSTM 7 维标量特征（对齐 phase_d_dataset_generator.py）"""
        import numpy as np

        # 0: level / 4.0
        level = float(ctx.get("level", 0))
        # 1: 未实现盈亏比
        pnl_pct = float(ctx.get("pnl_pct", 0.0))
        # 2: atr_z / 3.0 — 对最近 30 根 4H 滚动 ATR 求 z-score
        atr_now = self._compute_atr(candles_4h, 14)
        atrs_rolling = []
        for w in range(max(0, len(candles_4h) - 60), len(candles_4h)):
            seg = candles_4h[max(0, w - 15): w + 1]
            if len(seg) >= 14:
                atrs_rolling.append(self._compute_atr(seg, 14))
        if atrs_rolling:
            atr_mean = sum(atrs_rolling) / len(atrs_rolling)
            atr_std = float(np.std(atrs_rolling))
        else:
            atr_mean, atr_std = atr_now, 1.0
        atr_z = (atr_now - atr_mean) / max(1e-6, atr_std)
        atr_z = max(-3.0, min(3.0, atr_z))
        # 3: vol_z / 2.5 — 用 4H 收盘价对数收益近似
        closes = [b["c"] for b in candles_4h[-60:]] if len(candles_4h) >= 10 else [b["c"] for b in candles_4h]
        rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0]
        vol_30 = float(np.std(rets)) * math.sqrt(365 * 6) if len(rets) >= 10 else 0.6  # 4H → 年化
        vol_z = (vol_30 - 0.6) / max(0.6 * 0.3, 1e-4)
        vol_z = min(2.5, max(-2.5, vol_z))
        # 4-6: TimingGate 三维评分（ctx 传入或默认占位）
        structure = float(ctx.get("timing_structure", 0.70))
        retrace = float(ctx.get("timing_retrace", 0.65))
        extension = float(ctx.get("timing_extension", 0.75))

        return np.array(
            [level / 4.0, pnl_pct, atr_z / 3.0, vol_z / 2.5, structure, retrace, extension],
            dtype=np.float32,
        )[None, :]  # (1, 7)

    def _load_bilstm_model(self):
        """懒加载 BiLSTM 模型权重"""
        import torch
        ai_trainers_path = str(Path(__file__).resolve().parent.parent / "ai_trainers")
        if ai_trainers_path not in sys.path:
            sys.path.insert(0, ai_trainers_path)
        from phase_d_models import BiLSTMAttentionBust

        payload = torch.load(self.bilstm_model_path, map_location="cpu", weights_only=False)
        meta = payload.get("meta", {})
        model = BiLSTMAttentionBust(
            ohlcv_len=meta.get("ohlcv_len", 60),
            n_channels=meta.get("n_channels", 5),
            n_scalar=meta.get("n_scalar", 7),
            hidden=meta.get("hidden", 48),
            n_layers=meta.get("n_layers", 2),
        )
        model.load_state_dict(payload["state_dict"])
        model.eval()
        self._bilstm_model = model
        self._bilstm_meta = meta

    def _load_patchtst_model(self):
        """懒加载 PatchTST 模型权重"""
        import torch
        ai_trainers_path = str(Path(__file__).resolve().parent.parent / "ai_trainers")
        if ai_trainers_path not in sys.path:
            sys.path.insert(0, ai_trainers_path)
        from phase_d_models import PatchTSTForDrawdown

        payload = torch.load(self.patchtst_model_path, map_location="cpu", weights_only=False)
        meta = payload.get("meta", {})
        model = PatchTSTForDrawdown(
            c_in=meta.get("c_in", 5),
            seq_len=meta.get("seq_len", 120),
            patch_len=meta.get("patch_len", 12),
            stride=meta.get("stride", 6),
            d_model=meta.get("d_model", 32),
            n_layers=meta.get("n_layers", 2),
            n_heads=meta.get("n_heads", 4),
        )
        model.load_state_dict(payload["state_dict"])
        model.eval()
        self._patchtst_model = model
        self._patchtst_meta = meta

    def _run_real_bilstm(self, ctx: Dict[str, Any]) -> float:
        """BiLSTM-Attention 实盘推理：加载权重 → 构造输入 → 前向传播 → P_bust"""
        import torch

        if self._bilstm_model is None:
            self._load_bilstm_model()
        if self._bilstm_model is None:
            raise ValueError("BiLSTM 模型加载失败")

        candles_4h = self._parse_klines(ctx.get("klines_4h", []))
        if len(candles_4h) < 10:
            raise ValueError("klines_4h 不足，无法推理 BiLSTM")

        ohlcv = self._ohlcv_to_array(candles_4h, 60)  # (1, 60, 5)
        scalar = self._build_bilstm_scalar(ctx, candles_4h)  # (1, 7)

        with torch.no_grad():
            p = self._bilstm_model(
                torch.from_numpy(ohlcv),
                torch.from_numpy(scalar),
            )
        return float(max(0.0, min(1.0, p.item())))

    def _run_real_patchtst(self, ctx: Dict[str, Any]) -> float:
        """PatchTST 实盘推理：加载权重 → 构造输入 → 前向传播 → 回撤预测值（负值）"""
        import torch

        if self._patchtst_model is None:
            self._load_patchtst_model()
        if self._patchtst_model is None:
            raise ValueError("PatchTST 模型加载失败")

        candles_1h = self._parse_klines(ctx.get("klines_1h", []))
        if len(candles_1h) < 10:
            raise ValueError("klines_1h 不足，无法推理 PatchTST")

        x = self._ohlcv_to_array(candles_1h, 120)  # (1, 120, 5)

        with torch.no_grad():
            p = self._patchtst_model(torch.from_numpy(x))
        val = float(p.item())
        return max(-1.0, min(0.0, val))  # clamp 到 [-1, 0]

    # ================================================================
    # G-D1 · Skip Open（含 §3.3 最高优先级铁律：baseline_wait 必须 Skip）
    # ================================================================
    def should_skip_open(self, ctx: Dict[str, Any]) -> bool:
        """只看 AI 模型本身信号（不含 baseline_wait 覆盖），供测试/诊断使用。"""
        self.last_gate_code = None
        if not self.enabled:
            return False
        p_dd = self._predict_patchtst_drawdown(ctx)
        p_bust = self._predict_bilstm_p_bust(ctx)
        try:
            p_dd_f = float(p_dd)
            p_bust_f = float(p_bust)
        except (TypeError, ValueError):
            # 异常类型降级：不开闸门（安全）
            return False
        if p_dd_f <= self.g_d1_drawdown_threshold:
            self.last_gate_code = "G-D1-SKIP-DRAWDOWN"
            return True
        if p_bust_f >= self.g_d1_bust_threshold:
            self.last_gate_code = "G-D1-SKIP-BUST"
            return True
        return False

    def should_skip_open_with_baseline(self, ctx: Dict[str, Any]) -> Tuple[bool, str]:
        """实盘真正调用版本：结合基线信号，保证最高优先级铁律。

        ctx 必须含键 baseline_can_open (bool) = v15 基线 16 层决策 + DirectionGate 判定的「是否能开」。
        返回 (must_skip, reason)
        """
        baseline_can_open = bool(ctx.get("baseline_can_open", False))

        # ---- 最高优先级铁律：基线不同意开 → 必须 Skip（AI 不得强开） ----
        if not baseline_can_open:
            self.last_gate_code = "G-D1-FORCED-BY-BASELINE-WAIT"
            return True, "baseline_wait: AI 不得违反 §3.3 最高优先级规则强制开仓"

        # 基线同意开的情况下，AI 可以否决
        skip_ai = self.should_skip_open(ctx)
        if skip_ai:
            return True, f"ai_{self.last_gate_code or 'unknown'}"
        return False, "baseline_agrees_and_ai_has_no_objection"

    # ================================================================
    # G-D2 · Trim Addons（缩最深档 addon4）
    # ================================================================
    def compute_effective_max_addons(
        self,
        coin: str,
        pos: Dict[str, Any],
        baseline_max_addons: int,
        addon_budgets: Dict[str, float],
    ) -> Tuple[int, Dict[str, float]]:
        """返回 (effective_max_addons, trimmed_addon_budgets)

        - BiLSTM P_bust ≥ g_d2_bust_threshold 时，max_addons = clamp_max_addons_delta(-1, baseline)
        - 最深档（最高编号 addonN_usd）设为 0
        """
        self.last_gate_code = None
        if not self.enabled:
            return int(baseline_max_addons), dict(addon_budgets)

        _ctx = {"coin": coin, "pos": pos}
        # 透传外部 heuristic 预估 + klines（MVP 桥接 + 真实模型推理）
        if isinstance(pos, dict):
            if "p_bust" in pos:
                _ctx["p_bust"] = pos["p_bust"]
            if "p_dd" in pos:
                _ctx["p_dd"] = pos["p_dd"]
            if "klines_4h" in pos:
                _ctx["klines_4h"] = pos["klines_4h"]
            if "klines_1h" in pos:
                _ctx["klines_1h"] = pos["klines_1h"]
            if "level" in pos:
                _ctx["level"] = pos["level"]
            if "pnl_pct" in pos:
                _ctx["pnl_pct"] = pos["pnl_pct"]
        p_bust = self._predict_bilstm_p_bust(_ctx)
        try:
            p_bust_f = float(p_bust)
        except (TypeError, ValueError):
            p_bust_f = 0.0
        if p_bust_f >= self.g_d2_bust_threshold:
            eff = clamp_max_addons_delta(-1, int(baseline_max_addons))
            trimmed = dict(addon_budgets)
            # 丢弃最高编号 addon：addon4 > addon3 > ...
            keys_sorted = sorted(
                (k for k in trimmed if k.startswith("addon") and k.endswith("_usd")),
                key=lambda k: int("".join(ch for ch in k if ch.isdigit()) or "0"),
                reverse=True,
            )
            # 多退少补：从高编号开始按 (baseline - eff) 个清零
            to_remove = max(0, int(baseline_max_addons) - eff)
            for k in keys_sorted[:to_remove]:
                trimmed[k] = 0.0
            self.last_gate_code = f"G-D2-TRIM-ADDON{4 if to_remove and 4<=baseline_max_addons else baseline_max_addons}"
            return eff, trimmed

        return int(baseline_max_addons), dict(addon_budgets)

    # ================================================================
    # G-D3 · Timing Relaxation（UNCLERA 浅回撤 低爆仓风险 才放行）
    # ================================================================
    def apply_timing_relaxation(
        self,
        symbol: str,
        timing_score: float,
        size_power: float,
        regime: str,
        ctx: Optional[Dict[str, Any]] = None,
    ) -> Tuple[float, float]:
        """返回 (adjusted_timing_score, adjusted_size_power)

        若不满足 UNCLEAR + 浅回撤 + 低爆仓，严格原值返回。
        ctx 可携带外部 heuristic 预估（p_bust / p_dd），用于 MVP 桥接。
        """
        self.last_gate_code = None
        orig_score, orig_power = float(timing_score), float(size_power)

        if not self.enabled:
            return orig_score, orig_power
        if str(regime).upper() != "UNCLEAR":
            return orig_score, orig_power

        _ctx = {"symbol": symbol, "regime": regime}
        if ctx:
            _ctx.update(ctx)
        try:
            p_dd = float(self._predict_patchtst_drawdown(_ctx))
            p_bust = float(self._predict_bilstm_p_bust(_ctx))
        except Exception:
            # 任何异常（模型推理/类型转换）都降级不放松
            return orig_score, orig_power

        if not (p_dd > self.g_d3_drawdown_threshold and p_bust < self.g_d3_bust_threshold):
            return orig_score, orig_power

        # ---- 满足 G-D3 条件：按 §3.3 边界内做轻微放松 ----
        relax_score_mul = self.g_d3_max_score_relax  # 1.05 default
        shrink_power_mul = self.g_d3_min_power_shrink  # 0.90 default

        new_score = apply_iron_clamp(
            ai_value=orig_score * relax_score_mul,
            baseline_value=orig_score,
            relative_lower=1.0,  # G-D3 只放松，不收紧（LOWER 1.0 保证不会比基线更小）
            relative_upper=relax_score_mul,
            absolute_lo=0.0,
            absolute_hi=1.0,  # timing_score 绝对 ∈[0,1]
        )
        # size_power: LOWER=0.60 来自 §3.3 表第 2 行；这里我们只往 0.9 倍的最小方向挪
        new_power = apply_iron_clamp(
            ai_value=orig_power * shrink_power_mul,
            baseline_value=orig_power,
            relative_lower=0.60,
            relative_upper=1.0,  # G-D3 只放宽（往更小 size_power），不收紧
            absolute_lo=1.00,   # §3.3 外层铁壳 [1.00, 4.00]
            absolute_hi=4.00,
        )
        self.last_gate_code = "G-D3-RELAX-UNCLEAR"
        return new_score, new_power
