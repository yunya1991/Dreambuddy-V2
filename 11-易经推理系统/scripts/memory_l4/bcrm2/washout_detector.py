"""WashoutDetector — 洗盘 vs 真弱势判定器（BCRM2.0 侧）.

Spec: docs/superpowers/specs/2026-09-21-washout-detector-design.md §4

开关形式默认关闭（ENABLE_WASHOUT_DETECTOR=False），触发条件激活后输出 WashoutVerdict。
关断时返回 WashoutVerdict.unknown()，BCRM2.0 链路字节等价「洗盘判定不存在」。

W1 阶段：仅落地 WashoutVerdict 数据契约 + WashoutDetector 骨架 + 触发门接入。
W2-W5 阶段逐步补充：8 维特征融合器 → 4 加密独有维度 → WashoutClassifier → 三层防御整合。

FAIL-OPEN 铁律: 任何异常 → WashoutVerdict.unknown() + 6 层堆栈日志，绝不阻塞交易。
"""
from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional

import pandas as pd

from .washout_trigger_gate import WashoutTriggerGate

__all__ = ["WashoutLabel", "WashoutVerdict", "WashoutDetector", "WASHOUT_CONFIG"]


# ============================================================
# 开关架构配置（§3.3）
# ============================================================
WASHOUT_CONFIG: Dict = {
    "enable_volume_dim": True,
    "enable_support_dim": True,
    "enable_amplitude_dim": True,
    "enable_oi_dim": True,
    "enable_position_dim": True,
    "enable_rebound_dim": True,
    "enable_news_dim": True,
    "enable_market_dim": True,
    "enable_oi_price_quadrant": True,
    "enable_funding_rate": True,
    "enable_cvd": True,
    "enable_ofi": True,
    "enable_wyckoff_climax": True,
}


# ============================================================
# WashoutVerdict 数据契约（§4.2）
# ============================================================
class WashoutLabel(Enum):
    """洗盘判定结果标签。"""
    WASHOUT = "washout"    # 洗盘 → 持有
    WEAKNESS = "weakness"  # 真弱势 → 加速离场
    UNKNOWN = "unknown"   # 不确定 → 维持现状


@dataclass(frozen=True)
class WashoutVerdict:
    """WashoutDetector 输出契约。

    Attributes:
        label: 判定标签 (WASHOUT/WEAKNESS/UNKNOWN)
        confidence: 置信度 [0.0, 1.0]
        trigger_activated: 是否通过触发门
        feature_snapshot: 8+4 维特征快照
        reason: 触发原因摘要
        timestamp: ISO 8601 UTC 时间戳
    """
    label: WashoutLabel
    confidence: float
    trigger_activated: bool
    feature_snapshot: Dict[str, float]
    reason: str
    timestamp: str

    def __post_init__(self):
        # confidence 边界裁剪 [0.0, 1.0]
        c = float(self.confidence)
        if c < 0.0:
            c = 0.0
        elif c > 1.0:
            c = 1.0
        object.__setattr__(self, "confidence", c)
        # feature_snapshot 深拷贝确保 frozen 安全
        snap = dict(self.feature_snapshot) if self.feature_snapshot else {}
        object.__setattr__(self, "feature_snapshot", snap)

    @staticmethod
    def unknown() -> "WashoutVerdict":
        """FAIL-OPEN 兜底返回。"""
        return WashoutVerdict(
            label=WashoutLabel.UNKNOWN,
            confidence=0.0,
            trigger_activated=False,
            feature_snapshot={},
            reason="unknown_fallback",
            timestamp="",
        )

    def to_dict(self) -> Dict:
        """序列化用于 log/传输。"""
        return {
            "label": self.label.value,
            "confidence": self.confidence,
            "trigger_activated": self.trigger_activated,
            "feature_snapshot": dict(self.feature_snapshot),
            "reason": self.reason,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "WashoutVerdict":
        """反序列化，1000 roundtrip 无损。FAIL-OPEN: 异常 → unknown()。"""
        try:
            if not isinstance(d, dict):
                return cls.unknown()
            # label
            label_val = d.get("label", "unknown")
            valid_labels = {e.value for e in WashoutLabel}
            if label_val not in valid_labels:
                label_val = "unknown"
            label = WashoutLabel(label_val)
            # confidence [0, 1]
            conf = float(d.get("confidence", 0.0))
            conf = max(0.0, min(1.0, conf))
            # trigger_activated
            trigger = bool(d.get("trigger_activated", False))
            # feature_snapshot
            snap_raw = d.get("feature_snapshot", {})
            snap: Dict[str, float] = {}
            if isinstance(snap_raw, dict):
                for k, v in snap_raw.items():
                    try:
                        snap[str(k)] = float(v)
                    except (TypeError, ValueError):
                        pass
            # reason
            reason = str(d.get("reason", "from_dict_fallback"))
            # timestamp
            ts = str(d.get("timestamp", ""))
            return cls(
                label=label,
                confidence=conf,
                trigger_activated=trigger,
                feature_snapshot=snap,
                reason=reason,
                timestamp=ts,
            )
        except Exception:
            return cls.unknown()


# ============================================================
# WashoutDetector 主类（§4.5）
# ============================================================
class WashoutDetector:
    """洗盘 vs 真弱势判定器（BCRM2.0 侧）。

    开关形式默认关闭，触发条件激活后输出 WashoutVerdict。
    W1 阶段：仅接入触发门，特征融合器和分类器待 W2-W4 实现。
    """

    def __init__(
        self,
        config: Optional[Dict] = None,
        enable: bool = False,
        trigger_gate: Optional[WashoutTriggerGate] = None,
        classifier: Optional[object] = None,
        feature_extractor: Optional[object] = None,
    ):
        self.enable = bool(enable)
        self.config = dict(config) if config else dict(WASHOUT_CONFIG)
        self.trigger_gate = trigger_gate if trigger_gate is not None else WashoutTriggerGate()
        self.classifier = classifier  # W4 阶段注入，W1-W3 为 None
        self.feature_extractor = feature_extractor  # W4 阶段注入特征提取器
        self._logger = logging.getLogger(__name__)

    def run(self, coin: str, df: pd.DataFrame, macro_data: Dict) -> WashoutVerdict:
        """主入口。

        Args:
            coin: 币种符号
            df: OHLCV DataFrame，至少 365d 历史
            macro_data: 宏观特征字典（含 OI/funding/news 等）

        Returns:
            WashoutVerdict。enable=False 或触发门未通过或异常 → unknown()。
        """
        if not self.enable:
            return WashoutVerdict.unknown()
        try:
            if df is None:
                raise TypeError(f"df must not be None (coin={coin})")
            if not isinstance(df, pd.DataFrame):
                raise TypeError(f"df must be DataFrame, got {type(df).__name__} (coin={coin})")

            activated = self.trigger_gate.should_activate(df)
            if not activated:
                return WashoutVerdict.unknown()

            # W4 阶段: classifier 注入后走 KNN/Bayesian 路径
            if self.classifier is not None:
                # 提取特征 (使用 feature_extractor 如果注入, 否则空 dict)
                features: Dict[str, float] = {}
                if self.feature_extractor is not None:
                    try:
                        features = self.feature_extractor.extract_all(df, macro_data) or {}
                    except Exception as fe:
                        self._logger.warning(
                            "washout_detector feature_extractor FAIL-OPEN: %s", fe
                        )
                        features = {}
                # 调用 classifier.predict()
                verdict = self.classifier.predict(features)
                if verdict is None:
                    # classifier FAIL-OPEN 返回 None → unknown
                    return WashoutVerdict.unknown()
                return verdict

            # W1-W3 阶段：触发门通过，但分类器（W4）尚未注入。
            # 返回 trigger_activated=True 的 unknown，表明触发门已激活但判定待实现。
            return WashoutVerdict(
                label=WashoutLabel.UNKNOWN,
                confidence=0.0,
                trigger_activated=True,
                feature_snapshot={},
                reason="w1_trigger_passed_classifier_pending",
                timestamp="",
            )
        except Exception as e:
            # FAIL-OPEN 铁律: 异常 → unknown() + 6 层堆栈日志
            tb = traceback.format_exc()
            self._logger.error(
                "washout_detector FAIL-OPEN coin=%s err=%s\n%s",
                coin,
                e,
                tb,
            )
            return WashoutVerdict.unknown()
