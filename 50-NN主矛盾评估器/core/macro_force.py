"""M2-1: 标的级宏观力 F_macro 四分量计算（SPEC-M2 §1.3）。

宏观力沿 L1(BTC) → L2 → L3 → L4 传导：
  F_macro(BTC) = F_cycle                      # 龙头直接承接宏观
  F_macro(s)   = F_cycle × corr0(s) × layer_gate(s)

每标的 4 分量（按层预注册权重，SPEC-M2 §1.3 表）：
  D1 趋势力  = base × w_D1[layer]
  D2 资金力  = base × w_D2[layer] × fund_layer_factor
  D4 情绪力  = base × w_D4[layer] × sentiment_factor
  洗盘力     = washout_verdicts.reversal_intent

数据来源（40 侧产出物，50 只读）：
  - cycle_state.json        → F_cycle（real_cycle + MA200 + regime）
  - resonance_matrix.json   → R(s)={corr0, lag_profile, beta, down_corr, granger_p}
  - sector_transmission.json→ layer / layer_median_momentum / transmission.state / meme_gap
  - washout_verdicts.json   → 每标的 washout verdict

fail-open：任何数据缺失 → 对应分量为 0 或恒等传导（corr0=1.0），
degraded 列表记录原因，不抛异常。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ── 层 × 分量权重表（SPEC-M2 §1.3，预注册先验）────────────────────
LAYER_COMPONENT_WEIGHTS: dict[str, dict[str, float]] = {
    "L1_anchor": {"D1": 1.0, "D2": 1.0, "D4": 0.3},
    "L2_major": {"D1": 0.9, "D2": 1.0, "D4": 0.5},
    "L3_growth": {"D1": 0.6, "D2": 1.0, "D4": 0.8},
    "L4_meme": {"D1": 0.3, "D2": 0.6, "D4": 2.0},
}

DEFAULT_WEIGHTS = {"D1": 1.0, "D2": 1.0, "D4": 0.3}

# ── G1 大类 × 分量权重表（跨类宏观力，预注册先验）──────────────────
# 与 40/asset_classes.py 的 10 大类一一对应；不得把 L4_meme 权重套到 ETF/商品。
ASSET_CLASS_WEIGHTS: dict[str, dict[str, float]] = {
    "crypto": {"D1": 1.0, "D2": 1.0, "D4": 0.3},
    "precious_metal": {"D1": 0.8, "D2": 0.5, "D4": 0.1},
    "industrial_metal": {"D1": 0.7, "D2": 0.4, "D4": 0.1},
    "energy": {"D1": 0.8, "D2": 0.5, "D4": 0.2},
    "us_index": {"D1": 1.0, "D2": 0.6, "D4": 0.2},
    "us_etf": {"D1": 0.9, "D2": 0.6, "D4": 0.3},
    "apac_index": {"D1": 0.9, "D2": 0.4, "D4": 0.2},
    "us_stock": {"D1": 0.7, "D2": 0.5, "D4": 0.6},
    "fx": {"D1": 0.6, "D2": 0.3, "D4": 0.0},
    "rates_credit": {"D1": 0.7, "D2": 0.4, "D4": 0.0},
}

DEFAULT_ASSET_WEIGHTS = {"D1": 1.0, "D2": 1.0, "D4": 0.3}

# 跨类矩阵的锚（其余 G1 龙头相对它计算 corr0 / 相对动量）
CROSS_ANCHOR = "BTC"

# 冲突触发阈值（SPEC-M2 §2.2：|双方| ≥ 0.3）
CONFLICT_THRESHOLD = 0.3

# G2 门禁：Granger 显著性阈值（p ≤ 0.05 才启用 t_arrive）
GRANGER_ALPHA = 0.05

# meme_gap 归一化分母（15% = 满量程情绪信号）
MEME_GAP_FULL_PCT = 15.0
# 层动量差归一化分母（20% = 满量程资金信号）
LAYER_MOM_DIFF_FULL_PCT = 20.0


@dataclass
class MacroForce:
    """单标的宏观力向量（4 分量 + 传导元信息）。"""

    symbol: str
    layer: str
    d1_trend: float  # [-1, 1]
    d2_fund: float  # [-1, 1]
    d4_sentiment: float  # [-1, 1]
    washout: float  # [-1, 1] 反转意图（正=洗盘看多反转，负=看空反转）
    f_cycle: float  # F_cycle 基础值（BTC 直接承接）
    corr0: float  # 共振系数 corr0
    layer_gate: float  # 层门（expanding=1.0, contracting=0.5）
    t_arrive_days: float | None  # 宏观力预期到达日（lag_profile 首个 < 0.5×corr0 的偏移）
    degraded: list[str] = field(default_factory=list)

    def component(self, dimension: str) -> float:
        """按维度取分量（D1/D2/D4/washout）。"""
        return {
            "D1": self.d1_trend,
            "D2": self.d2_fund,
            "D4": self.d4_sentiment,
            "washout": self.washout,
        }.get(dimension, 0.0)


# ── 工具函数 ──────────────────────────────────────────────────────


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_symbol(sym: str) -> str:
    """统一标的符号：BTC-USDT-SWAP / BTC/USDT → BTC。"""
    s = str(sym)
    for suffix in ("-USDT-SWAP", "/USDT", "-USDT", "-SWAP"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    return s


def f_cycle_from_state(cycle_state: dict) -> float:
    """从 cycle_state 计算 F_cycle ∈ [-1, 1]。

    综合三因素取平均：
      - 利率方向：up(hiking)=-1, down(cutting)=+1, flat=0
      - MA200：多数资产 above=+1, below=-1, 无数据=0
      - regime：bull=+1, bear=-1, 其他=0
    fail-open：cycle_state 为空 → 0.0
    """
    if not isinstance(cycle_state, dict):
        return 0.0

    rc = cycle_state.get("real_cycle") or {}
    # 利率方向：加息利空风险资产 → -1；降息利多 → +1
    last_change = str(rc.get("last_change", "flat")).lower()
    rate_dir = {"up": -1.0, "hike": -1.0, "down": 1.0, "cut": 1.0, "flat": 0.0}.get(
        last_change, 0.0
    )

    # MA200 锚点
    anchor = cycle_state.get("technical_anchor") or {}
    assets = anchor.get("assets") or {}
    above = sum(1 for a in assets.values() if isinstance(a, dict) and a.get("above") is True)
    below = sum(1 for a in assets.values() if isinstance(a, dict) and a.get("above") is False)
    if above + below > 0:
        ma200_dir = 1.0 if above > below else -1.0
    else:
        ma200_dir = 0.0

    # regime
    regime = str(anchor.get("regime") or cycle_state.get("regime") or "").lower()
    if "bull" in regime:
        regime_dir = 1.0
    elif "bear" in regime:
        regime_dir = -1.0
    else:
        regime_dir = 0.0

    return _clamp((rate_dir + ma200_dir + regime_dir) / 3.0)


# ── 核心：标的级宏观力计算 ──────────────────────────────────────────


def compute_macro_forces(
    cycle_state: dict,
    resonance_matrix: dict | None,
    sector_transmission: dict | None,
    washout_verdicts: dict | None,
) -> dict[str, MacroForce]:
    """计算每个标的的宏观力向量。

    Args:
        cycle_state: 40 cycle_state.json 内容
        resonance_matrix: 40 resonance_matrix.json 内容（可空）
        sector_transmission: 40 sector_transmission.json 内容（可空）
        washout_verdicts: 40 washout_verdicts.json 内容（可空）

    Returns:
        {normalized_symbol: MacroForce}
    """
    f_cycle = f_cycle_from_state(cycle_state)

    layers = (sector_transmission or {}).get("layers") or {}
    st_assets = (sector_transmission or {}).get("assets") or {}
    transmission = (sector_transmission or {}).get("transmission") or {}
    state = str(transmission.get("state", "neutral")).lower()
    meme_gap = _to_float(transmission.get("meme_vs_major_gap_pct"), 0.0)
    layer_medians = (sector_transmission or {}).get("layer_median_momentum_3m_pct") or {}
    l1_median = _to_float(layer_medians.get("L1_anchor"), 0.0)

    res_assets = (resonance_matrix or {}).get("assets") or {}
    washout = washout_verdicts or {}

    result: dict[str, MacroForce] = {}

    for layer_name, syms in layers.items():
        if not isinstance(syms, list):
            continue
        weights = LAYER_COMPONENT_WEIGHTS.get(layer_name, DEFAULT_WEIGHTS)
        is_l1 = layer_name == "L1_anchor"

        for raw_sym in syms:
            sym = normalize_symbol(raw_sym)
            r = res_assets.get(raw_sym, {}) or res_assets.get(sym, {}) or {}

            degraded: list[str] = []
            corr0 = _to_float(r.get("corr0"), 1.0)
            if r.get("degraded"):
                degraded.append(str(r["degraded"]))

            # 层门：contracting 时非 L1 层 ×0.5（资金缩回主流层）
            layer_gate = 0.5 if (state == "contracting" and not is_l1) else 1.0

            # 基础传导：BTC 直接 = F_cycle；其余 = F_cycle × corr0 × layer_gate
            if is_l1:
                base = f_cycle
            else:
                base = f_cycle * corr0 * layer_gate

            # D1 趋势力
            d1 = _clamp(base * weights["D1"])

            # D2 资金力：层动量相对 L1 的差（资金是否正流向本层）
            layer_med = _to_float(layer_medians.get(layer_name), 0.0)
            mom_diff = layer_med - l1_median
            fund_factor = _clamp(mom_diff / LAYER_MOM_DIFF_FULL_PCT)
            if not st_assets:
                # 无 sector 数据时，资金力跟随基础传导方向
                fund_factor = 1.0 if base >= 0 else -1.0
            d2 = _clamp(base * weights["D2"] * fund_factor)

            # D4 情绪力：meme_gap 为正（meme 跑赢主流）= 过热 → 看空情绪
            sentiment_factor = _clamp(-meme_gap / MEME_GAP_FULL_PCT)
            d4 = _clamp(base * weights["D4"] * sentiment_factor)

            # 洗盘力：washout verdict → 反转意图
            wv = washout.get(raw_sym) or washout.get(sym) or {}
            washout_force = 0.0
            if isinstance(wv, dict):
                verdict = str(wv.get("verdict") or wv.get("label") or "").lower()
                conf = _to_float(wv.get("confidence"), 0.0)
                if verdict in ("washout", "reversal", "shakeout", "accumulation"):
                    # 洗盘=尾部吸筹，反转意图与当前趋势反向
                    washout_force = _clamp(conf) if base < 0 else _clamp(-conf)
                elif verdict == "unknown":
                    degraded.append("washout_unknown")

            # t_arrive：lag_profile 中首个 |corr| < 0.5×|corr0| 的偏移日
            # G2 门禁：Granger 不显著（p 缺失或 > 0.05）→ t_arrive 禁用，
            # 传导语义降级为"宏观因子暴露"（SPEC-M1 退出标准 / PLAN §四 G2）。
            lag_profile = r.get("lag_profile") or []
            t_arrive: float | None = None
            granger_p = r.get("granger_p")
            granger_ok = granger_p is not None and _to_float(granger_p, 1.0) <= GRANGER_ALPHA
            if isinstance(lag_profile, list) and lag_profile and corr0 != 0:
                if granger_ok:
                    half = 0.5 * abs(corr0)
                    for idx, c in enumerate(lag_profile[1:], start=1):
                        if abs(_to_float(c, 0.0)) < half:
                            t_arrive = float(idx)
                            break
                elif not is_l1:
                    # 非龙头且 Granger 不显著 → 审计降级
                    degraded.append("granger_not_significant")

            result[sym] = MacroForce(
                symbol=sym,
                layer=layer_name,
                d1_trend=d1,
                d2_fund=d2,
                d4_sentiment=d4,
                washout=washout_force,
                f_cycle=f_cycle,
                corr0=corr0,
                layer_gate=layer_gate,
                t_arrive_days=t_arrive,
                degraded=degraded,
            )

    return result


# ── P1：G1 大类龙头的跨类宏观力 ────────────────────────────────────


def compute_cross_class_forces(
    cross_asset_matrix: dict | None,
    cycle_state: dict | None,
) -> dict[str, MacroForce]:
    """G1 六大类龙头的宏观力（跨类，按大类权重而不是加密层权重）。

    F_macro(s) = F_cycle × corr0(s)；BTC 为跨类锚，恒等传导（corr0=1.0）。
      D1 趋势力 = base × w_D1[class]
      D2 资金力 = base × w_D2[class] × 相对 BTC 动量因子
      D4 情绪力 = base × w_D4[class] × 拥挤因子（相对动量越热 → 情绪越负）
      washout   = 0.0（跨类龙头无洗盘判定）
    t_arrive 仍受 G2 门禁约束：Granger 不显著 → t_arrive=None + degraded。

    fail-open：矩阵缺失/为空 → 返回 {}（由 sensor 标注 degraded，不抛异常）。
    """
    if not isinstance(cross_asset_matrix, dict):
        return {}
    assets = cross_asset_matrix.get("assets") or {}
    if not isinstance(assets, dict) or not assets:
        return {}

    f_cycle = f_cycle_from_state(cycle_state or {})
    btc_entry = assets.get(CROSS_ANCHOR) or {}
    btc_mom = _to_float(btc_entry.get("momentum_3m_pct"), 0.0)

    result: dict[str, MacroForce] = {}
    for raw_sym, entry in assets.items():
        if not isinstance(entry, dict):
            continue
        sym = normalize_symbol(raw_sym)
        cls = str(entry.get("class") or "")
        weights = ASSET_CLASS_WEIGHTS.get(cls, DEFAULT_ASSET_WEIGHTS)

        degraded: list[str] = []
        raw_degraded = entry.get("degraded")
        if isinstance(raw_degraded, list):
            degraded.extend(str(x) for x in raw_degraded)
        elif raw_degraded:
            degraded.append(str(raw_degraded))

        corr0 = _to_float(entry.get("corr0"), 1.0)
        is_anchor = sym == CROSS_ANCHOR
        base = f_cycle if is_anchor else f_cycle * corr0

        rel_mom = _to_float(entry.get("momentum_3m_pct"), 0.0) - btc_mom
        fund_factor = _clamp(rel_mom / LAYER_MOM_DIFF_FULL_PCT)
        sentiment_factor = _clamp(-rel_mom / MEME_GAP_FULL_PCT)

        d1 = _clamp(base * weights["D1"])
        d2 = _clamp(base * weights["D2"] * fund_factor)
        d4 = _clamp(base * weights["D4"] * sentiment_factor)

        # t_arrive：与加密侧同口径，受 Granger 显著性门禁
        lag_profile = entry.get("lag_profile") or []
        granger_p = entry.get("granger_p")
        granger_ok = granger_p is not None and _to_float(granger_p, 1.0) <= GRANGER_ALPHA
        t_arrive: float | None = None
        if not is_anchor and isinstance(lag_profile, list) and lag_profile and corr0 != 0:
            if granger_ok:
                half = 0.5 * abs(corr0)
                for idx, c in enumerate(lag_profile[1:], start=1):
                    if abs(_to_float(c, 0.0)) < half:
                        t_arrive = float(idx)
                        break
            else:
                degraded.append("granger_not_significant")

        result[sym] = MacroForce(
            symbol=sym,
            layer=cls or "unknown",
            d1_trend=d1,
            d2_fund=d2,
            d4_sentiment=d4,
            washout=0.0,
            f_cycle=f_cycle,
            corr0=corr0,
            layer_gate=1.0,
            t_arrive_days=t_arrive,
            degraded=degraded,
        )

    return result
