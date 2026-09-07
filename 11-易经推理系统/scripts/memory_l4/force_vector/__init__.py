"""战略层力向量最小阻力方向模块。

对应 Spec: 2026-08-30-strategic-force-vector-design.md
模块组成:
  - models: 数据结构（ForceVector / FeatureCorrelation / ... ）
  - adapters: 9-基本面引擎复用适配层
  - force_vector_calculator: 五维统计 + Kalman 平滑
  - feature_correlation_calculator: IC + MI + 排名 + 权重
  - pca_resonance_analyzer: PCA 五维共振分析
  - elasticity_beta_calculator: 弹性系数β
  - contradiction_transform_detector: 6类转化条件
  - regime_conditional_calibrator: CBR 条件期望
  - cycle_comparator: 7d+30d 双窗口
  - strategic_mapper: 映射 war_state/cap/mask
"""
import dataclasses as _dc
import logging as _logging
from typing import Any

_log = _logging.getLogger("force_vector.init")

# =========================================================================
# FAIL-OPEN 友好：9 个顶层包绝对导入（from force_vector.xxx import）
# 作为兄弟子包 scripts.memory_l4.force_vector 被加载时 顶层
# force_vector 包不存在，__init__ 抛异常 → 整个子模块不可 import。
# 封装进 try/except，失败仅打 WARN，不阻塞（9 个 models/calculators 对
# BDSM 相关文件 coin_fundamental_ranker / bdsm_snapshot_writer 无
# 内部依赖；上层 战略层 代码用顶层包路径（import force_vector）
# 依然 100% 可用，不会进这个失败分支。）
# =========================================================================
_exported_cls = []  # type: ignore[var-annotated]
try:
    from force_vector.models import (
        ForceVector,
        FeatureCorrelation,
        PrimaryContradiction,
        PCAResonance,
        CycleComparison,
        ElasticityBeta,
        ContradictionTransform,
        StrategicLayerOutput,
    )
    from force_vector.force_vector_calculator import ForceVectorCalculator
    from force_vector.feature_correlation_calculator import FeatureCorrelationCalculator
    from force_vector.pca_resonance_analyzer import PCAResonanceAnalyzer
    from force_vector.cycle_comparator import CycleComparator
    from force_vector.elasticity_beta_calculator import ElasticityBetaCalculator
    from force_vector.contradiction_transform_detector import ContradictionTransformDetector
    from force_vector.regime_conditional_calibrator import RegimeConditionalCalibrator
    from force_vector.strategic_mapper import StrategicMapper

    _exported_cls = [
        ForceVector, FeatureCorrelation, PrimaryContradiction, PCAResonance,
        CycleComparison, ElasticityBeta, ContradictionTransform, StrategicLayerOutput,
    ]
except Exception as _e:  # pragma: no cover - 兄弟子包环境 顶层 force_vector 不存在
    _log.warning(
        "[force_vector.__init__ FAIL-OPEN] 顶层包导入失败（兄弟子包环境或缺失）"
        " — 将跳过 9 个 calculator/models 导出，BDSM_COINS/快照 功能不受影响。"
        " err=%s: %s", type(_e).__name__, _e,
    )
    ForceVector = FeatureCorrelation = PrimaryContradiction = None  # type: ignore
    PCAResonance = CycleComparison = ElasticityBeta = None  # type: ignore
    ContradictionTransform = StrategicLayerOutput = None  # type: ignore
    ForceVectorCalculator = FeatureCorrelationCalculator = None  # type: ignore
    PCAResonanceAnalyzer = CycleComparator = None  # type: ignore
    ElasticityBetaCalculator = ContradictionTransformDetector = None  # type: ignore
    RegimeConditionalCalibrator = StrategicMapper = None  # type: ignore
    _exported_cls = []


def to_dict(obj: Any) -> Any:
    """统一 dataclass → dict（Shadow 审计专用；深度转换，处理 list/dict/nesting）。"""
    if obj is None:
        return None
    if isinstance(obj, (int, float, str, bool)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [to_dict(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): to_dict(v) for k, v in obj.items()}
    if _dc.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_dict(getattr(obj, f.name)) for f in _dc.fields(obj)}
    try:
        return dict(obj)
    except Exception:
        return str(obj)


# 为各 dataclass 附动态方法（shadow 导出方便；等价于静态 to_dict）
# 兄弟子包 FAIL-OPEN：_exported_cls 可能为空，不做 monkey-patch
for _cls in _exported_cls:
    if _cls is None:
        continue
    _cls.to_dict = lambda self, _fn=to_dict, _c=_cls: _fn(self)  # type: ignore[attr-defined]


__all__ = [
    "ForceVector",
    "FeatureCorrelation",
    "PrimaryContradiction",
    "PCAResonance",
    "CycleComparison",
    "ElasticityBeta",
    "ContradictionTransform",
    "StrategicLayerOutput",
    "ForceVectorCalculator",
    "FeatureCorrelationCalculator",
    "PCAResonanceAnalyzer",
    "CycleComparator",
    "ElasticityBetaCalculator",
    "ContradictionTransformDetector",
    "RegimeConditionalCalibrator",
    "StrategicMapper",
    "to_dict",
]
