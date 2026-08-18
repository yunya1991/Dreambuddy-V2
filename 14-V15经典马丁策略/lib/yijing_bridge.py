#!/usr/bin/env python3
"""
易经推理桥接模块 (Yijing Bridge)

职责：
  1. 隔离跨目录 importlib 加载（绕过 11-易经 inspect.py 与标准库冲突）
  2. 将 V15 K线数据转换为 YijingEngine 所需的 8 维归一化评分
  3. 调用 YijingEngine.infer() 获取卦象
  4. 将卦象的 risk_level/direction_hint/development_stage 映射为数值化
     risk_score(0-1) / value_score(0-1)

设计原则：
  - 单一职责：只做"K线 → risk/value 评分"，不做参数调整
  - 零外部交易依赖：不依赖 OKX / 持仓 / v15_trader
  - 可被回测(infer_klines 批量)和实盘(infer_current 单次)共用
  - 内置缓存：相同评分量化 key 直接返回，避免重复起卦

用法：
  from yijing_bridge import YijingBridge
  bridge = YijingBridge()
  # 回测批量
  results = bridge.infer_klines(klines)  # List[dict] 每根 bar 一条
  # 实盘单次
  result = bridge.infer_current(klines)  # dict
"""
import importlib.util
import sys
import types
from pathlib import Path
from typing import Dict, List, Optional

# ── 跨目录加载 YijingEngine ──────────────────────────────────────────────

_V15_DIR = Path(__file__).resolve().parent.parent  # 14-V15经典马丁策略/
_PROJECT_ROOT = _V15_DIR.parent                     # dreambuddy-v2/
_BCRM_DIR = _PROJECT_ROOT / "11-易经推理系统" / "scripts" / "memory_l4" / "bcrm"


def _load_yijing_engine():
    """importlib 加载 YijingEngine，绕过 bcrm/__init__.py → inspect.py 冲突

    bcrm/__init__.py 导入 output_contract → dataclasses → inspect，
    但 memory_l4/inspect.py 影子化了标准库 inspect 导致循环引用。
    解决：创建假 bcrm 包跳过 __init__.py，直接加载需要的子模块。
    """
    if not _BCRM_DIR.exists():
        return None

    # 避免重复加载
    if "bcrm.yijing_engine" in sys.modules:
        return sys.modules["bcrm.yijing_engine"].YijingEngine

    bcrm_pkg = types.ModuleType("bcrm")
    bcrm_pkg.__path__ = [str(_BCRM_DIR)]
    sys.modules["bcrm"] = bcrm_pkg

    for name in ["_constants", "sixty_four_guas", "yijing_engine"]:
        mod_path = _BCRM_DIR / f"{name}.py"
        if not mod_path.exists():
            return None
        spec = importlib.util.spec_from_file_location(f"bcrm.{name}", mod_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"bcrm.{name}"] = mod
        spec.loader.exec_module(mod)

    return sys.modules["bcrm.yijing_engine"].YijingEngine


# ── 轻量指标计算（独立于 v15_backtest，避免循环依赖）──────────────────────


def _sma(values: List[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _ema(values: List[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = v * k + ema * (1 - k)
    return ema


def _rsi(closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    recent = deltas[-period:]
    gains = [max(d, 0) for d in recent]
    losses = [max(-d, 0) for d in recent]
    avg_g = sum(gains) / period
    avg_l = sum(losses) / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return 100 - 100 / (1 + rs)


def _atr(klines: List[Dict], period: int = 14) -> float:
    if len(klines) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(klines)):
        h = float(klines[i].get("h", 0))
        l = float(klines[i].get("l", 0))
        prev_c = float(klines[i - 1].get("c", 0))
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        trs.append(tr)
    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0.0
    return sum(trs[-period:]) / period


def _adx(closes: List[float], period: int = 14) -> float:
    """简化 ADX（仅返回趋势强度数值，0-100）"""
    if len(closes) < period * 2 + 1:
        return 20.0
    plus_dm, minus_dm, tr = [], [], []
    for i in range(1, len(closes)):
        up = closes[i] - closes[i - 1]
        down = closes[i - 1] - closes[i]
        plus_dm.append(up if up > 0 and up > down else 0)
        minus_dm.append(down if down > 0 and down > up else 0)
        tr.append(abs(closes[i] - closes[i - 1]))

    def wilder(data, n):
        if len(data) < n:
            return data
        s = [sum(data[:n])]
        for i in range(n, len(data)):
            s.append(s[-1] - s[-1] / n + data[i])
        return s

    pdm = wilder(plus_dm, period)
    mdm = wilder(minus_dm, period)
    atr_v = wilder(tr, period)
    dx = []
    for i in range(min(len(pdm), len(mdm), len(atr_v))):
        if atr_v[i] > 0:
            dp = 100 * pdm[i] / atr_v[i]
            dm = 100 * mdm[i] / atr_v[i]
            denom = dp + dm
            dx.append(100 * abs(dp - dm) / denom if denom > 0 else 0)
        else:
            dx.append(0)
    if len(dx) < period:
        return sum(dx) / len(dx) if dx else 0
    return sum(dx[-period:]) / period


# ── 桥接主体 ─────────────────────────────────────────────────────────────


class YijingBridge:
    """易经推理桥接 - K线 → risk/value 评分

    可被 v15_backtest.py（回测 infer_klines）和 v15_trader.py（实盘 infer_current）共用。
    """

    # risk_level 文本 → 基础锚点（连续化计算的起点，非最终值）
    # 降低"高"档锚点：加密货币普遍高波动，0.75 过度惩罚
    _RISK_BASE = {
        "高": 0.62, "high": 0.62,
        "中": 0.42, "medium": 0.42, "med": 0.42,
        "低": 0.22, "low": 0.22,
    }
    # 向后兼容
    _RISK_MAP = _RISK_BASE

    def __init__(self):
        self._YijingEngine_cls = _load_yijing_engine()
        self._engine = None
        if self._YijingEngine_cls:
            try:
                self._engine = self._YijingEngine_cls()
            except Exception:
                self._engine = None
        self._cache: Dict[str, dict] = {}
        self._cache_hits = 0

    @property
    def available(self) -> bool:
        return self._engine is not None

    # ── K线 → 8 维评分 ──────────────────────────────────────────────────

    @staticmethod
    def klines_to_scores(klines: List[Dict], idx: int, lookback: int = 30) -> Dict[str, float]:
        """将第 idx 根 bar 的 K线数据转为 YijingEngine 所需的 8 维归一化评分

        Args:
            klines: K线列表（含 o/c/h/l/v 字段）
            idx: 当前 bar 索引
            lookback: 指标回看窗口

        Returns:
            dict 含 supply_demand_score / technical_score / capital_flow_score /
                  sentiment_score / trend_strength / volatility /
                  volume_ratio / price_position
        """
        if idx < 5 or idx >= len(klines):
            return {
                "supply_demand_score": 0.5, "technical_score": 0.5,
                "capital_flow_score": 0.5, "sentiment_score": 0.5,
                "trend_strength": 0.5, "volatility": 0.3,
                "volume_ratio": 1.0, "price_position": 0.5,
            }

        window = klines[max(0, idx - lookback + 1): idx + 1]
        closes = [float(k["c"]) for k in window]
        highs = [float(k["h"]) for k in window]
        lows = [float(k["l"]) for k in window]
        vols = [float(k.get("v", 0)) for k in window]
        cur_close = closes[-1]

        # 1. supply_demand_score: 价格变动方向 + 成交量配合
        #    放量上涨=需求旺盛，缩量下跌=需求不足
        if len(closes) >= 2:
            price_chg = (closes[-1] - closes[-5]) / closes[-5] if closes[-5] > 0 else 0
            vol_ma = _sma(vols, min(20, len(vols))) or 1
            vol_ratio_raw = vols[-1] / vol_ma if vol_ma > 0 else 1.0
            sd = 0.5 + price_chg * 5 * 0.5  # 价格变动贡献
            if vol_ratio_raw > 1.0 and price_chg > 0:
                sd = min(1.0, sd + 0.1)  # 放量上涨加成
            elif vol_ratio_raw > 1.0 and price_chg < 0:
                sd = max(0.0, sd - 0.1)  # 放量下跌惩罚
        else:
            sd = 0.5
        sd = max(0.0, min(1.0, sd))

        # 2. technical_score: MACD hist 方向 + ADX 趋势强度
        adx_val = _adx(closes, 14) if len(closes) >= 30 else 20
        rsi_val = _rsi(closes, 14)
        # RSI 50 为中性，ADX>25 为有趋势
        tech = 0.4 + (rsi_val - 50) / 100  # RSI 贡献 ±0.4
        if adx_val > 25:
            tech += 0.15  # 趋势确认加成
        tech = max(0.0, min(1.0, tech))

        # 3. capital_flow_score: OBV 简化（价格上涨日累计量 vs 下跌日）
        if len(closes) >= 10:
            up_vol = sum(vols[i] for i in range(1, len(closes)) if closes[i] > closes[i - 1])
            dn_vol = sum(vols[i] for i in range(1, len(closes)) if closes[i] < closes[i - 1])
            total = up_vol + dn_vol
            cf = (up_vol / total * 0.6 + 0.2) if total > 0 else 0.5
        else:
            cf = 0.5
        cf = max(0.0, min(1.0, cf))

        # 4. sentiment_score: RSI 归一化（RSI>50 偏乐观）
        sm = rsi_val / 100.0
        sm = max(0.0, min(1.0, sm))

        # 5. trend_strength: ADX/100
        ts = adx_val / 100.0
        ts = max(0.0, min(1.0, ts))

        # 6. volatility: ATR% 归一化（ATR/price，再映射到 0-1）
        atr_val = _atr(window, 14)
        atr_pct = atr_val / cur_close if cur_close > 0 else 0.02
        # 加密货币典型 ATR% 0.5%-5%，映射到 0.1-0.9
        vol = 0.1 + min(0.8, atr_pct * 16)
        vol = max(0.0, min(1.0, vol))

        # 7. volume_ratio: 当前量 / MA(量, 20)
        vol_ma = _sma(vols, min(20, len(vols))) or 1
        vr = vols[-1] / vol_ma if vol_ma > 0 else 1.0

        # 8. price_position: (close - low_N) / (high_N - low_N)
        swing_high = max(highs) if highs else cur_close
        swing_low = min(lows) if lows else cur_close
        rng = swing_high - swing_low
        pp = (cur_close - swing_low) / rng if rng > 0 else 0.5
        pp = max(0.0, min(1.0, pp))

        return {
            "supply_demand_score": round(sd, 3),
            "technical_score": round(tech, 3),
            "capital_flow_score": round(cf, 3),
            "sentiment_score": round(sm, 3),
            "trend_strength": round(ts, 3),
            "volatility": round(vol, 3),
            "volume_ratio": round(vr, 3),
            "price_position": round(pp, 3),
        }

    # ── risk_level → risk_score ──────────────────────────────────────────

    @classmethod
    def risk_level_to_score(cls, risk_level: str) -> float:
        """卦象 risk_level(高/中/低) → 基础 risk_score(0-1)

        仅返回基础锚点，连续化请用 _compute_continuous_risk。
        0=安全，1=高危
        """
        if not risk_level:
            return 0.45
        return cls._RISK_BASE.get(risk_level.lower().strip(), 0.45)

    @staticmethod
    def _compute_continuous_risk(
        risk_level: str,
        scores: Dict[str, float],
        result_dict: dict,
    ) -> float:
        """连续化 risk_score：卦象档位为锚 + 8维评分微调

        解决 risk_level 只有3档离散值、加密货币普遍判"高"导致 risk_score 无区分度的问题。

        微调项（合计 ±0.20 范围）：
          - volatility: 高波动加风险（加密货币 ATR% 高时风险显著）
          - price_position: 价格极端位置加风险（高位追涨/低位接刀）
          - trend_strength: 强趋势 + 反转警告时加风险
          - confidence: 低置信度时收缩风险信号（不确定性高→风险适中）

        Args:
            risk_level: 卦象风险等级（高/中/低）
            scores: 8维归一化评分
            result_dict: 卦象结果 dict（含 confidence）

        Returns:
            连续 risk_score (0.05-0.95)
        """
        # 基础锚点
        base = YijingBridge._RISK_BASE.get(
            risk_level.lower().strip() if risk_level else "中", 0.42
        )

        vol = scores.get("volatility", 0.5)
        pos = scores.get("price_position", 0.5)
        ts = scores.get("trend_strength", 0.5)
        conf = result_dict.get("confidence", 0.5)

        # 波动率微调：vol>0.5 加风险，<0.5 减风险（±0.09）
        vol_adj = (vol - 0.5) * 0.18

        # 价格极端位置微调：偏离中点越远风险越高（0 ~ +0.06）
        pos_adj = abs(pos - 0.5) * 0.12

        # 趋势强度 + 反转警告：强趋势伴随反转信号时加风险（0 ~ +0.04）
        is_high_risk = risk_level in ("高", "high")
        trend_adj = ts * conf * 0.08 if is_high_risk else 0.0

        # 置信度收缩：低置信度时风险向中性靠拢（-0.03 ~ 0）
        conf_adj = -(0.5 - conf) * 0.06 if conf < 0.5 else 0.0

        risk = base + vol_adj + pos_adj + trend_adj + conf_adj
        return round(max(0.05, min(0.95, risk)), 3)

    # ── 卦象 → value_score ───────────────────────────────────────────────

    @staticmethod
    def compute_value_score(result_dict: dict) -> float:
        """从卦象结果计算价值评分(0-1)

        逻辑：方向(UP/DOWN/FLAT) × 发展阶段(萌芽/成长/成熟/衰退) × 置信度
        - UP + 成长/萌芽 → 高价值（趋势初期，值得持有）
        - UP + 成熟 → 中高价值（趋势中期，仍有空间）
        - UP + 衰退 → 中价值（趋势末端，注意见顶）
        - DOWN + 衰退 → 低价值（下跌末端，但可能抄底机会）
        - DOWN + 萌芽 → 中价值（可能见底）
        - FLAT → 中性
        """
        direction = result_dict.get("direction_hint", "FLAT")
        stage = result_dict.get("development_stage", "")
        confidence = result_dict.get("confidence", 0.5)

        base = 0.5
        # 方向贡献
        if direction in ("UP", "DIR_UP"):
            base += 0.15
        elif direction in ("DOWN", "DIR_DOWN"):
            base -= 0.10
        # 阶段贡献
        if "萌芽" in stage:
            base += 0.05
        elif "成长" in stage:
            base += 0.15
        elif "成熟" in stage:
            base += 0.03
        elif "衰退" in stage:
            base -= 0.15
        # 置信度微调
        base += (confidence - 0.5) * 0.2

        return max(0.0, min(1.0, base))

    # ── 推理接口 ─────────────────────────────────────────────────────────

    def _infer_with_cache(self, scores: dict) -> dict:
        """带缓存的推理（8 维评分量化后作为 key）"""
        # 量化 key（3 位小数），相同评分不重复起卦
        key = "|".join(f"{v:.3f}" for v in scores.values())
        if key in self._cache:
            self._cache_hits += 1
            return self._cache[key]

        result = self._engine.infer(**scores)
        rdict = result.to_dict()

        risk_level = rdict.get("risk_level", "中")
        # 连续化 risk_score：卦象档位为锚 + 8维评分微调（解决离散3档无区分度问题）
        risk_score = self._compute_continuous_risk(risk_level, scores, rdict)
        value_score = self.compute_value_score(rdict)

        out = {
            "hexagram": rdict.get("hexagram_name_cn", ""),
            "direction_hint": rdict.get("direction_hint", "FLAT"),
            "risk_level": rdict.get("risk_level", "中"),
            "risk_score": round(risk_score, 3),
            "value_score": round(value_score, 3),
            "confidence": round(rdict.get("confidence", 0.5), 3),
            "development_stage": rdict.get("development_stage", ""),
        }
        self._cache[key] = out
        return out

    def infer_bar(self, klines: List[Dict], idx: int) -> dict:
        """单根 bar 推理

        Args:
            klines: 完整 K线列表
            idx: 当前 bar 索引

        Returns:
            dict 含 risk_score / value_score / direction_hint / hexagram 等
        """
        if not self.available:
            return {
                "hexagram": "", "direction_hint": "FLAT",
                "risk_level": "中", "risk_score": 0.5,
                "value_score": 0.5, "confidence": 0.5,
                "development_stage": "",
            }
        scores = self.klines_to_scores(klines, idx)
        return self._infer_with_cache(scores)

    def infer_klines(self, klines: List[Dict], step: int = 1) -> List[Optional[dict]]:
        """批量推理（回测用）

        Args:
            klines: 完整 K线列表
            step: 采样步长（默认每根 bar，step=6 则每 6 根取一次以加速）

        Returns:
            等长列表，未推理的位置为 None
        """
        n = len(klines)
        results: List[Optional[dict]] = [None] * n
        if not self.available:
            return results
        for i in range(0, n, step):
            results[i] = self.infer_bar(klines, i)
        return results

    def infer_current(self, klines: List[Dict]) -> dict:
        """最新 bar 推理（实盘用）

        Args:
            klines: K线列表（最新 bar 在末尾）

        Returns:
            dict 含 risk_score / value_score 等
        """
        if not klines:
            return self.infer_bar([], 0)
        return self.infer_bar(klines, len(klines) - 1)

    def stats(self) -> dict:
        """缓存统计"""
        return {
            "cache_size": len(self._cache),
            "cache_hits": self._cache_hits,
            "available": self.available,
        }
