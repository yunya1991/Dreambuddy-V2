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

# ABShadowComparator 懒导入（避免循环依赖，运行时按需加载）
_AB_COMPARATOR_CLS = None


def _get_ab_comparator_cls():
    """懒加载 ABShadowComparator 类，避免 import 时循环依赖。"""
    global _AB_COMPARATOR_CLS
    if _AB_COMPARATOR_CLS is None:
        try:
            import sys as _sys
            _root = str(Path(__file__).resolve().parent.parent)
            if _root not in _sys.path:
                _sys.path.insert(0, _root)
            from ab_shadow_comparator import ABShadowComparator as _Cls
            _AB_COMPARATOR_CLS = _Cls
        except Exception:
            _AB_COMPARATOR_CLS = False  # 标记不可用
    return _AB_COMPARATOR_CLS if _AB_COMPARATOR_CLS is not False else None

# ================================================================
# 真实模型推理支撑（roadmap §4.4）— 懒加载 torch，模块导入零依赖
# ================================================================
_MODEL_CACHE: Dict[Any, Any] = {}
_AI_TRAINERS_DIR = str(Path(__file__).resolve().parent.parent / "ai_trainers")


def _candle_val(k: Any, key: str, idx: int) -> Optional[float]:
    """K线取值：兼容 dict / list|tuple 两种形态（v15 数据约定 o=1,h=2,l=3,c=4,v=5）。"""
    try:
        if isinstance(k, dict):
            v = k.get(key)
            return float(v) if v is not None else None
        if isinstance(k, (list, tuple)) and len(k) > idx:
            return float(k[idx])
    except Exception:
        return None
    return None


def _ohlcv_rows(klines: Any, limit: int) -> list:
    """取最近 limit 根 K 线 → [[o,h,l,c,v],...]；不足时首部重复填充
    （与训练生成器 phase_d_dataset_generator 的 pad 约定一致）。"""
    rows = []
    for k in (klines or [])[-limit:]:
        o = _candle_val(k, "o", 1)
        h = _candle_val(k, "h", 2)
        l = _candle_val(k, "l", 3)
        c = _candle_val(k, "c", 4)
        v = _candle_val(k, "v", 5)
        if c is None:
            continue
        rows.append([
            o if o is not None else c,
            h if h is not None else c,
            l if l is not None else c,
            c,
            v if v is not None else 0.0,
        ])
    if not rows:
        return []
    if len(rows) < limit:
        rows = [rows[0]] * (limit - len(rows)) + rows
    return rows


def _expand_4h_to_1h(klines_4h: Any) -> list:
    """确定性 4H→1H 展开（回测侧无 1H 数据时的兜底路径）：
    每根 4H 按 o→c 线性插值切 4 根 1H，上下影线均摊，成交量 /4。"""
    bars = []
    for k in (klines_4h or []):
        o = _candle_val(k, "o", 1)
        h = _candle_val(k, "h", 2)
        l = _candle_val(k, "l", 3)
        c = _candle_val(k, "c", 4)
        v = _candle_val(k, "v", 5) or 0.0
        if o is None or c is None:
            continue
        hi_wick = max(0.0, (h if h is not None else max(o, c)) - max(o, c)) / 4.0
        lo_wick = max(0.0, min(o, c) - (l if l is not None else min(o, c))) / 4.0
        for j in range(4):
            so = o + (c - o) * (j / 4.0)
            sc = o + (c - o) * ((j + 1) / 4.0)
            bars.append({
                "o": so,
                "h": max(so, sc) + hi_wick,
                "l": min(so, sc) - lo_wick,
                "c": sc,
                "v": v / 4.0,
            })
    return bars


def _atr14_pure(rows: list) -> float:
    """ATR(14) 纯 Python（与训练生成器 _atr_from_ohlcv 同语义：真实波幅均值）。"""
    trs = []
    for i in range(1, len(rows)):
        h, l, pc = rows[i][1], rows[i][2], rows[i - 1][3]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if not trs:
        return 0.0
    p = min(14, len(trs))
    return sum(trs[-p:]) / p


def _bilstm_scalar_features(ctx: Dict[str, Any], rows: list) -> list:
    """7 维标量特征 — 与 phase_d_dataset_generator.generate_single_trajectory_sample 布局对齐:
    [level/4, pnl_pct, atr_z/3, vol_z/2.5, structure, retrace, extension]"""
    atr_now = _atr14_pure(rows)
    atrs = []
    for w in range(max(0, len(rows) - 60), len(rows)):
        seg = rows[max(0, w - 15): w + 1]
        if len(seg) >= 14:
            atrs.append(_atr14_pure(seg))
    if atrs:
        mu = sum(atrs) / len(atrs)
        sd = (sum((a - mu) ** 2 for a in atrs) / len(atrs)) ** 0.5
        atr_z = (atr_now - mu) / (1e-6 + sd)
    else:
        atr_z = 0.0
    atr_z = max(-3.0, min(3.0, atr_z))
    level = float(ctx.get("level", 0) or 0)
    pnl = float(ctx.get("pnl_pct", 0.0) or 0.0)
    return [
        max(0.0, min(1.0, level / 4.0)),
        max(-0.5, min(0.1, pnl)),
        atr_z / 3.0,
        0.0,  # vol_z: 真实行情无合成 ann_vol 参照 → 中性 0（训练分布均值）
        float(ctx.get("timing_score", 0.70) or 0.70),
        float(ctx.get("retrace_quality", 0.65) or 0.65),
        float(ctx.get("extension_chase", 0.75) or 0.75),
    ]


def _ensure_ai_trainers_path() -> None:
    if _AI_TRAINERS_DIR not in sys.path:
        sys.path.insert(0, _AI_TRAINERS_DIR)


def _load_bilstm_model(path: str):
    """懒加载 BiLSTM-Attention 权重（模块级缓存）。失败返回 None → 调用方降级。"""
    key = ("bilstm", path)
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]
    try:
        import torch

        payload = torch.load(path, map_location="cpu", weights_only=False)
        meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
        sd = payload.get("state_dict", payload) if isinstance(payload, dict) else payload
        _ensure_ai_trainers_path()
        from phase_d_models import BiLSTMAttentionBust

        model = BiLSTMAttentionBust(
            ohlcv_len=int(meta.get("ohlcv_len", 60)),
            n_channels=int(meta.get("n_channels", 5)),
            n_scalar=int(meta.get("n_scalar", 7)),
            hidden=int(meta.get("hidden", 48)),
            n_layers=int(meta.get("n_layers", 2)),
        )
        model.load_state_dict(sd)
        model.eval()
        _MODEL_CACHE[key] = (model, torch)
        return _MODEL_CACHE[key]
    except Exception:
        _MODEL_CACHE[key] = None
        return None


def _load_patchtst_model(path: str):
    """懒加载 PatchTST 权重（模块级缓存）。失败返回 None → 调用方降级。"""
    key = ("patchtst", path)
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]
    try:
        import torch

        payload = torch.load(path, map_location="cpu", weights_only=False)
        meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
        sd = payload.get("state_dict", payload) if isinstance(payload, dict) else payload
        _ensure_ai_trainers_path()
        from phase_d_models import PatchTSTForDrawdown

        model = PatchTSTForDrawdown(
            c_in=int(meta.get("c_in", 5)),
            seq_len=int(meta.get("seq_len", 120)),
            patch_len=int(meta.get("patch_len", 12)),
            stride=int(meta.get("stride", 6)),
            d_model=int(meta.get("d_model", 32)),
            n_layers=int(meta.get("n_layers", 2)),
            n_heads=int(meta.get("n_heads", 4)),
            d_ff=int(meta.get("d_ff", 64)),
        )
        model.load_state_dict(sd)
        model.eval()
        _MODEL_CACHE[key] = (model, torch)
        return _MODEL_CACHE[key]
    except Exception:
        _MODEL_CACHE[key] = None
        return None


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
    # A/B 影子对比器（None=不记录，设置后自动记录 G-D1/G-D2/G-D3 决策）
    ab_comparator: Optional[Any] = field(default=None, repr=False)

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
    # 预测函数：真实加载模型 & 推理；或走 mock（TDD 场景）
    # 此处先以 mock + 随机兜底实现，真实模型权重在训练脚本交付后注入
    # ================================================================
    def _predict_patchtst_drawdown(self, ctx: Dict[str, Any]) -> float:
        """PatchTST: 预测未来 24 根 1H K 线 max drawdown (负值, -1=-100%)

        优先级（训练权重交付后）: TDD mock → 真实模型 → ctx heuristic 桥接 → 中性
        铁律1: 任一环节异常 → 调用方 except 兜底 → 等价基线
        """
        if not self.enabled:
            return -0.0
        if self._mock_patchtst is not None:
            return float(self._mock_patchtst)
        # 真实模型优先（权重存在且加载成功时）
        if self.patchtst_model_path and os.path.isfile(self.patchtst_model_path):
            try:
                return self._run_real_patchtst(ctx)
            except Exception:
                pass  # 模型推理失败 → 降级到 heuristic 桥接
        # MVP heuristic 桥接兜底
        if ctx and "p_dd" in ctx:
            _v = float(ctx["p_dd"])
            return -abs(_v) if _v > 0 else _v  # 确保负值（drawdown 约定）
        return -0.0

    def _predict_bilstm_p_bust(self, ctx: Dict[str, Any]) -> float:
        """BiLSTM-Attention: 爆仓概率 P([0,1])

        优先级: TDD mock → 真实模型 → ctx heuristic 桥接 → 中性
        """
        if not self.enabled:
            return 0.0
        if self._mock_bilstm is not None:
            return float(self._mock_bilstm)
        if self.bilstm_model_path and os.path.isfile(self.bilstm_model_path):
            try:
                return self._run_real_bilstm(ctx)
            except Exception:
                pass  # 降级到 heuristic 桥接
        if ctx and "p_bust" in ctx:
            return float(ctx["p_bust"])
        return 0.0

    # ================================================================
    # 真实模型推理接线（roadmap §4.4 — 训练权重 v1 交付后注入）
    # 特征构造与 phase_d_dataset_generator.generate_single_trajectory_sample
    # 字节级对齐；任何异常向上抛出由调用方 except 兜底（铁律1: 失败=基线）
    # ================================================================
    def _run_real_patchtst(self, ctx: Dict[str, Any]) -> float:
        model_t = _load_patchtst_model(self.patchtst_model_path)
        if model_t is None:
            raise RuntimeError("PatchTST 模型加载失败")
        model, torch = model_t
        klines_1h = ctx.get("klines_1h") if ctx else None
        if klines_1h:
            rows = _ohlcv_rows(klines_1h, 120)
        else:
            # 回测侧无 1H 数据：用 4H 确定性展开（训练/推理一致性兜底路径）
            rows = _ohlcv_rows(_expand_4h_to_1h(ctx.get("klines_4h") if ctx else None), 120)
        if not rows:
            return -0.0
        with torch.no_grad():
            x = torch.tensor([rows], dtype=torch.float32)
            d = float(model(x).squeeze(-1).item())
        return -abs(d) if d > 0 else d  # drawdown 约定为负值

    def _run_real_bilstm(self, ctx: Dict[str, Any]) -> float:
        model_t = _load_bilstm_model(self.bilstm_model_path)
        if model_t is None:
            raise RuntimeError("BiLSTM 模型加载失败")
        model, torch = model_t
        rows = _ohlcv_rows(ctx.get("klines_4h") if ctx else None, 60)
        if not rows:
            return 0.0
        scalar = _bilstm_scalar_features(ctx or {}, rows)
        with torch.no_grad():
            x = torch.tensor([rows], dtype=torch.float32)
            s = torch.tensor([scalar], dtype=torch.float32)
            p = float(model(x, s).squeeze(-1).item())
        return max(0.0, min(1.0, p))

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
        if p_dd <= self.g_d1_drawdown_threshold:
            self.last_gate_code = "G-D1-SKIP-DRAWDOWN"
            return True
        if p_bust >= self.g_d1_bust_threshold:
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
            if self.ab_comparator:
                _p_dd = self._predict_patchtst_drawdown(ctx)
                _p_bust = self._predict_bilstm_p_bust(ctx)
                _symbol = ctx.get("symbol", ctx.get("coin", "UNKNOWN"))
                self.ab_comparator.record_decision(
                    symbol=_symbol,
                    baseline_action="OPEN",
                    ai_action="SKIP",
                    baseline_confidence=1.0,
                    ai_confidence=1.0 - _p_bust,
                    baseline_pnl=0.0,
                    ai_predicted_pnl=0.0,
                    ai_p_bust=_p_bust,
                    ai_drawdown=_p_dd,
                    decision_diff=f"G-D1 skip: {self.last_gate_code or 'unknown'}",
                )
            return True, f"ai_{self.last_gate_code or 'unknown'}"
        if self.ab_comparator:
            _p_dd = self._predict_patchtst_drawdown(ctx)
            _p_bust = self._predict_bilstm_p_bust(ctx)
            _symbol = ctx.get("symbol", ctx.get("coin", "UNKNOWN"))
            self.ab_comparator.record_decision(
                symbol=_symbol,
                baseline_action="OPEN",
                ai_action="OPEN",
                baseline_confidence=1.0,
                ai_confidence=1.0 - _p_bust,
                baseline_pnl=0.0,
                ai_predicted_pnl=0.0,
                ai_p_bust=_p_bust,
                ai_drawdown=_p_dd,
                decision_diff="G-D1 agree: baseline and AI both open",
            )
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
        # 透传外部 heuristic 预估（MVP 桥接）
        if isinstance(pos, dict):
            if "p_bust" in pos:
                _ctx["p_bust"] = pos["p_bust"]
            if "p_dd" in pos:
                _ctx["p_dd"] = pos["p_dd"]
        p_bust = self._predict_bilstm_p_bust(_ctx)
        if p_bust >= self.g_d2_bust_threshold:
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
            if self.ab_comparator:
                self.ab_comparator.record_decision(
                    symbol=coin,
                    baseline_action="ADDON",
                    ai_action="ADDON",
                    baseline_confidence=1.0,
                    ai_confidence=1.0 - p_bust,
                    baseline_pnl=0.0,
                    ai_predicted_pnl=0.0,
                    ai_p_bust=p_bust,
                    ai_drawdown=0.0,
                    decision_diff=f"G-D2 trim: {self.last_gate_code}, max_addons {baseline_max_addons}→{eff}",
                )
            return eff, trimmed

        if self.ab_comparator:
            self.ab_comparator.record_decision(
                symbol=coin,
                baseline_action="ADDON",
                ai_action="ADDON",
                baseline_confidence=1.0,
                ai_confidence=1.0 - p_bust,
                baseline_pnl=0.0,
                ai_predicted_pnl=0.0,
                ai_p_bust=p_bust,
                ai_drawdown=0.0,
                decision_diff="G-D2 agree: no trim needed",
            )
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
        p_dd = self._predict_patchtst_drawdown(_ctx)
        p_bust = self._predict_bilstm_p_bust(_ctx)

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
        if self.ab_comparator:
            self.ab_comparator.record_decision(
                symbol=symbol,
                baseline_action="TIMING",
                ai_action="TIMING_RELAX",
                baseline_confidence=orig_score,
                ai_confidence=new_score,
                baseline_pnl=0.0,
                ai_predicted_pnl=0.0,
                ai_p_bust=p_bust,
                ai_drawdown=p_dd,
                decision_diff=f"G-D3 relax: timing {orig_score:.4f}→{new_score:.4f}, power {orig_power:.4f}→{new_power:.4f}",
            )
        return new_score, new_power
