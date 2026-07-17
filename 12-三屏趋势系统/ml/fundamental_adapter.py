"""基本面特征适配器

将两个基本面数据源统一适配为 AI 模型可用的特征向量：

数据源 1：6-TRADING screen1 周线六维评分
  - technical (技术面)
  - cycle (减半周期)
  - miner (矿工经济)
  - onchain (链上估值)
  - macro (宏观金融)
  - cross_market (跨市场)
  + ACH 三假设概率

数据源 2：9-基本面分析 SignalEngine / SentimentEngine
  - resistance_3d (方向/速度/加速度)
  - module_scores (flow/valuation/onchain/macro/news/sentiment/...)
  - signal_strength (信号强度)

适配器输出：标准化的基本面特征字典（全部数值化，-1~1 或 0~1 归一化）
"""

from typing import Dict, Any, Optional, List
import numpy as np


def _safe_float(v: Any, default: float = 0.0) -> float:
    """安全转换为 float"""
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _normalize_score(score: float, max_score: float = 100.0) -> float:
    """将 0~max_score 归一化到 -1~1"""
    if max_score <= 0:
        return 0.0
    normalized = (score / max_score) * 2.0 - 1.0
    return max(-1.0, min(1.0, normalized))


def _direction_to_score(direction: str) -> float:
    """方向字符串转为数值"""
    d = str(direction).upper()
    if d in ("BULL", "BULLISH", "UP", "LONG"):
        return 1.0
    elif d in ("BEAR", "BEARISH", "DOWN", "SHORT"):
        return -1.0
    else:
        return 0.0


def _confidence_to_score(confidence: str) -> float:
    """置信度字符串转为数值"""
    c = str(confidence).upper()
    if c in ("STRONG", "HIGH", "VERY_HIGH"):
        return 1.0
    elif c in ("MODERATE", "MEDIUM", "MID"):
        return 0.6
    elif c in ("LOW", "WEAK"):
        return 0.3
    else:
        return 0.0


class FundamentalFeatureAdapter:
    """基本面特征适配器

    将多种格式的基本面数据统一转换为 AI 模型可用的特征向量。

    输出特征（约 30+ 维）：
    - screen1 六维评分 + 权重 + 归一化分数
    - screen1 ACH 三假设概率
    - 9-基本面 resistance_3d 三维度
    - 9-基本面 模块分数（10个模块）
    - 信号强度与方向
    """

    def __init__(self):
        self.feature_names: List[str] = []

    def adapt_screen1(self, screen1_data: Dict[str, Any]) -> Dict[str, float]:
        """适配 6-TRADING screen1 六维评分数据

        参数:
            screen1_data: screen1_synthesis.json 格式的数据

        返回:
            特征字典
        """
        feats: Dict[str, float] = {}

        # 总评分
        total_score = _safe_float(screen1_data.get("total_score", 50))
        max_score = _safe_float(screen1_data.get("max_score", 100))
        feats["screen1_total_score"] = _normalize_score(total_score, max_score)
        feats["screen1_direction"] = _direction_to_score(screen1_data.get("direction", "NEUTRAL"))
        feats["screen1_confidence"] = _confidence_to_score(screen1_data.get("confidence", "MODERATE"))

        # 六维评分
        dimensions = screen1_data.get("dimensions", {})
        dim_names = ["technical", "cycle", "miner", "onchain", "macro", "cross_market"]

        for dim_name in dim_names:
            dim = dimensions.get(dim_name, {})
            if not dim:
                feats[f"s1_{dim_name}_score"] = 0.0
                feats[f"s1_{dim_name}_weight"] = 0.0
                feats[f"s1_{dim_name}_anchor"] = 0.0
                continue

            # 分数归一化到 -1~1
            raw_score = _safe_float(dim.get("score", 50))
            dim_max = _safe_float(dim.get("max_score", 100))
            if dim_max <= 0:
                dim_max = 100.0
            feats[f"s1_{dim_name}_score"] = _normalize_score(raw_score, dim_max)

            # 权重（归一化到 0~1）
            weight = _safe_float(dim.get("weight", 0))
            feats[f"s1_{dim_name}_weight"] = min(1.0, weight / 100.0) if weight > 0 else 0.0

            # 锚定方向
            feats[f"s1_{dim_name}_anchor"] = _direction_to_score(dim.get("anchor", "NEUTRAL"))

        # ACH 三假设概率
        ach = screen1_data.get("ach", {})
        for h_key in ["h1", "h2", "h3"]:
            h = ach.get(h_key, {})
            feats[f"s1_ach_{h_key}_prob"] = _safe_float(h.get("probability", 0))

        return feats

    def adapt_fundamental_9(self, fundamental_9_data: Dict[str, Any]) -> Dict[str, float]:
        """适配 9-基本面分析 数据

        参数:
            fundamental_9_data: 包含 resistance_3d / metrics / signals 的数据

        返回:
            特征字典
        """
        feats: Dict[str, float] = {}

        # resistance_3d 三维度
        res_3d = fundamental_9_data.get("resistance_3d", {})
        if res_3d:
            direction_score = _safe_float(res_3d.get("direction_score", 0))
            velocity = _safe_float(res_3d.get("velocity", 0))
            acceleration = _safe_float(res_3d.get("acceleration", 0))
            confidence = _safe_float(res_3d.get("confidence", 0))

            feats["f9_res_direction"] = max(-1.0, min(1.0, direction_score))
            feats["f9_res_velocity"] = max(-1.0, min(1.0, velocity))
            feats["f9_res_acceleration"] = max(-1.0, min(1.0, acceleration))
            feats["f9_res_confidence"] = max(0.0, min(1.0, confidence))
        else:
            for k in ["f9_res_direction", "f9_res_velocity", "f9_res_acceleration", "f9_res_confidence"]:
                feats[k] = 0.0

        # 模块分数
        metrics = fundamental_9_data.get("metrics", {})
        core = metrics.get("core", metrics)  # 兼容新旧格式

        module_keys = [
            "flow", "valuation", "onchain", "macro",
            "news", "sentiment", "breadth", "intermarket",
            "narrative", "calendar"
        ]

        for mod in module_keys:
            val = _safe_float(core.get(mod, 0))
            # 假设分数在 0~100 范围，归一化到 -1~1
            feats[f"f9_mod_{mod}"] = _normalize_score(val, 100.0)

        # 信号强度（从 signals 列表提取）
        signals = fundamental_9_data.get("signals", [])
        if signals:
            total_strength = 0.0
            total_direction = 0.0
            for sig in signals:
                strength = _safe_float(sig.get("strength", 0))
                direction = _safe_float(sig.get("direction", 0))
                total_strength += strength
                total_direction += direction * strength
            feats["f9_sig_count"] = min(1.0, len(signals) / 10.0)
            feats["f9_sig_strength"] = min(1.0, total_strength)
            feats["f9_sig_net_direction"] = max(-1.0, min(1.0, total_direction / max(total_strength, 0.01)))
        else:
            feats["f9_sig_count"] = 0.0
            feats["f9_sig_strength"] = 0.0
            feats["f9_sig_net_direction"] = 0.0

        # 情绪分数
        sentiment = core.get("sentiment", 50)
        feats["f9_sentiment"] = _normalize_score(_safe_float(sentiment, 50), 100.0)

        return feats

    def adapt_all(
        self,
        screen1_data: Optional[Dict[str, Any]] = None,
        fundamental_9_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, float]:
        """适配所有可用的基本面数据

        参数:
            screen1_data: 6-TRADING screen1 数据（可选）
            fundamental_9_data: 9-基本面分析 数据（可选）

        返回:
            合并后的特征字典（缺失的特征填 0）
        """
        all_feats: Dict[str, float] = {}

        if screen1_data:
            all_feats.update(self.adapt_screen1(screen1_data))

        if fundamental_9_data:
            all_feats.update(self.adapt_fundamental_9(fundamental_9_data))

        self.feature_names = list(all_feats.keys())
        return all_feats

    def get_feature_names(self) -> List[str]:
        """获取所有已知特征名"""
        return self.feature_names.copy()

    def get_expected_feature_count(self) -> int:
        """获取预期的特征总数（用于维度校验）"""
        # screen1: 3 总览 + 6维×3 + 3 ACH = 3+18+3 = 24
        # f9: 4 resistance_3d + 10 modules + 3 signals + 1 sentiment = 18
        # 合计约 42 个（实际可用数量取决于数据）
        return 42
