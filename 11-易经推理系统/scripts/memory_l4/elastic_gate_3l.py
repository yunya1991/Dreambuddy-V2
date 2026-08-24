"""
方案 C v3.0 子系统 2：ElasticGate3L
====================================
三层弹性放行矩阵（P1 大周期 × Elder 中周期 × BCRM 小周期 Score_B）。

输入：
  - p1_out："STANDARD" / "WEAK" / "BLOCK"
  - elder_grade：ALIGN_FULL / ALIGN_BASIC / NEUTRAL / DIVERGE_BASIC / DIVERGE_SEVERE
  - score_b：Score_B ∈ [0.30, 1.0]，连续性 60% + 单笔置信 40%
  - weights：ThreeLayerWeights（w_p:w_e:w_b，Σ=1）

输出：
  - base_pos_mult ∈ [0.05, 1.50]（不叠加 F1~F4 铁则）
  - fail-open → 0.10（§十 L3 固定 10% 仓位）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ElasticGate3LOutput:
    base_pos_mult: float
    score_p: float
    score_e: float
    score_b: float
    score_consensus: float
    source: str = "normal"


class ElasticGate3L:
    """
    三层弹性放行矩阵：

    步骤：
      ① 独立评分 → ② 加权共识 → ③ base_pos_mult 映射 → ④ F1~F4 铁则叠加（调用方负责）
    """

    # ----------------
    # P1 档位分值
    # ----------------
    _P1_SCORES = {
        "STANDARD": 1.00,
        "WEAK": 0.60,
        "BLOCK": 0.10,    # F1 BLOCK 也给 10% 试错仓底
    }

    # ----------------
    # Elder-ray 五级分值
    # ----------------
    _ELDER_SCORES = {
        "ALIGN_FULL": 1.00,
        "ALIGN_BASIC": 0.85,
        "NEUTRAL": 0.65,
        "DIVERGE_BASIC": 0.45,
        "DIVERGE_SEVERE": 0.30,
    }

    def __init__(self, enable: bool = False):
        self.enable = bool(enable)
        self._last_failopen_logged_hour: str = ""
        # 动态参数（P14* / P15* 等回测校准值），无文件时用常量默认
        self._params: dict = self._load_params_defaults()

    @staticmethod
    def _load_params_defaults() -> dict:
        """从 runtime/phase_c_default_params.json 加载，失败返回空 dict（走常量兜底）"""
        try:
            import json as _json
            from pathlib import Path as _Path
            p = _Path(__file__).resolve().parent / "runtime" / "phase_c_default_params.json"
            if p.exists():
                data = _json.loads(p.read_text(encoding="utf-8"))
                return {k: float(v) for k, v in data.items()}
        except Exception:
            pass
        return {}

    # -------- 辅助：分值 --------
    def _score_p1(self, p1_out: str) -> float:
        return float(self._P1_SCORES.get(str(p1_out).upper(), 0.60))

    def _score_elder(self, elder_grade: str) -> float:
        return float(self._ELDER_SCORES.get(str(elder_grade).upper(), 0.65))

    @staticmethod
    def _consensus_to_base(score_consensus: float) -> float:
        """
        §四.3 三段式 base_pos_mult 映射：
          score_cons < 0.20  → 0.05（紧贴 F1 底线）
          0.20 ≤ s < 0.70    → 线性插值 0.05 ~ 0.85
          s ≥ 0.70           → 线性 0.85 ~ 1.50
        """
        if score_consensus < 0.20:
            return 0.05
        if score_consensus < 0.70:
            t = (score_consensus - 0.20) / 0.50
            return 0.05 + (0.85 - 0.05) * t
        t = (score_consensus - 0.70) / 0.30
        return 0.85 + (1.50 - 0.85) * min(1.0, max(0.0, t))

    # -------- 公共：核心方法 --------
    def apply_fuses(self,
                    base_pos_mult: float,
                    p1_out: str,
                    elder_grade: str,
                    f4_hit: bool,
                    f4_similarity: float,
                    ) -> float:
        """
        §五 5.3 F1~F4 铁则叠加（按顺序：F3 → F4 → F2 → 全局clip[F1]）。

        顺序：
          ① F3 折扣：Elder=DIVERGE_SEVERE → × 0.70
          ② F4 红利：f4_hit=True 且 similarity ≥ F4_BASELINE_SIM_THRESHOLD → × 1.20
          ③ F2 顶 cap：P1=BLOCK → final ≤ F2_P1_BLOCK_CAP_DEFAULT (0.10)
          ④ 全局 clip + F1 底：final ∈ [0.05, 1.50]（F1 永不 BLOCK 通过下 clip=0.05 实现）

        Args:
            base_pos_mult: compute() 返回的基础仓位倍率
            p1_out: P1 档位（用于 F2）
            elder_grade: Elder 五级（用于 F3）
            f4_hit: CBR top1 是否命中家族（seed_case_001/002 等）
            f4_similarity: CBR top1 真实相似度（用于 F4 门槛）

        Returns:
            float: 最终 final_pos_mult，可直接 × position_usdt 使用
        """
        from . import phase_c_constants as C
        final = float(base_pos_mult)

        # ① F3：Elder 严重反信 0.70 折扣
        if str(elder_grade).upper() == "DIVERGE_SEVERE":
            final = final * C.F3_DIVERGE_SEVERE_MULT

        # ② F4：CBR 基线家族 1.20 红利（双条件）
        f4_sim = float(f4_similarity or 0.0)
        if bool(f4_hit) and f4_sim >= C.F4_BASELINE_SIM_THRESHOLD:
            final = final * C.F4_BASELINE_BONUS_MULT

        # ③ F2：P1 BLOCK 硬上限（即使 F3/F4 全满也不能超 0.10）
        if str(p1_out).upper() == "BLOCK":
            p1_cap = float(self._load_global_p1_cap())
            if final > p1_cap:
                final = p1_cap

        # ④ 全局 clip + F1 底（F1=永不 BLOCK 通过下边界 0.05 实现）
        clip_low = float(C.FINAL_POS_MULT_CLIP_LOW)
        clip_high = float(self._load_global_clip_high())
        final = max(clip_low, min(clip_high, final))
        return final

    # -------- 辅助：动态参数加载（支持 P14*/P15* 季度校准覆盖）--------
    def _load_global_p1_cap(self) -> float:
        """P14* F2 顶 cap，默认 0.10，runtime 参数可覆盖"""
        try:
            from . import phase_c_constants as C
            # runtime 动态参数优先（回测校准后覆盖）
            default_cap = float(C.F2_P1_BLOCK_CAP_DEFAULT)
            dp = getattr(self, "_params", None)
            if dp and isinstance(dp, dict):
                return float(dp.get("p1_block_cap", default_cap))
            return default_cap
        except Exception:
            return 0.10

    def _load_global_clip_high(self) -> float:
        """P15* 全局 clip 上界，默认 1.50，runtime 参数可覆盖"""
        try:
            from . import phase_c_constants as C
            default_high = float(C.FINAL_POS_MULT_CLIP_HIGH_DEFAULT)
            dp = getattr(self, "_params", None)
            if dp and isinstance(dp, dict):
                return float(dp.get("global_clip_high", default_high))
            return default_high
        except Exception:
            return 1.50

    def compute_with_fuses(self,
                           p1_out: str,
                           elder_grade: str,
                           score_b: float,
                           weights: Optional[Any] = None,
                           f4_hit: bool = False,
                           f4_similarity: float = 0.0,
                           direction: Optional[str] = None,
                           ) -> float:
        """
        一站式：compute() → apply_fuses()，直接返回 final_pos_mult。

        典型调用：
          final_mult = gate.compute_with_fuses(
              "WEAK", "ALIGN_BASIC", score_b=0.82,
              weights=weights_dict, f4_hit=False, f4_similarity=0.0,
              direction="SHORT",
          )
          position_usdt = base_position_usdt * final_mult
        """
        out = self.compute(
            p1_out=p1_out, elder_grade=elder_grade,
            score_b=score_b, weights=weights, direction=direction,
        )
        # 做空收紧时 apply_fuses 的 elder_grade 用实际参与 compute 的降档版（若被改写则体现在 out.score_e 上；此处保持一致）
        eg_for_fuses = elder_grade
        try:
            _src = str(getattr(out, "source", "") or "")
            if _src.startswith("short_tightened:") and "Elder→" in _src:
                import re as _re
                _m = _re.search(r"Elder→([A-Z_]+)", _src)
                if _m:
                    eg_for_fuses = _m.group(1)
        except Exception:
            pass
        return self.apply_fuses(
            base_pos_mult=out.base_pos_mult,
            p1_out=p1_out, elder_grade=eg_for_fuses,
            f4_hit=f4_hit, f4_similarity=f4_similarity,
        )

    def compute(self,
                p1_out: str,
                elder_grade: str,
                score_b: float,
                weights: Optional[Any] = None,
                direction: Optional[str] = None,
                ) -> ElasticGate3LOutput:
        """
        计算三层弹性放行 base_pos_mult。

        Args:
            p1_out: P1 大周期档位 "STANDARD"/"WEAK"/"BLOCK"
            elder_grade: Elder-ray 五级标签
            score_b: Score_B（BCRM 连续性 + 单笔置信合成）∈ [0,1]
            weights: ThreeLayerWeights 对象或 dict 含 w_p/w_e/w_b
            direction: 可选 "LONG"/"SHORT" —— SHORT 时启用做空动态收紧：
                       ① Score_B < 0.70 → 向下 clip 到 0.55（降低小周期权重贡献）
                       ② Elder_grade == NEUTRAL → 降档到 DIVERGE_BASIC（必须中周期基本对齐才允许做空）

        Returns:
            ElasticGate3LOutput：含 base_pos_mult 及各层分值
        """
        try:
            from . import phase_c_constants as C

            # 1) 提取权重（支持 dict 或 dataclass）
            if weights is None:
                w_p, w_e, w_b = C.FAILOPEN_WP, C.FAILOPEN_WE, C.FAILOPEN_WB
            elif isinstance(weights, dict):
                w_p = float(weights.get("w_p", C.FAILOPEN_WP))
                w_e = float(weights.get("w_e", C.FAILOPEN_WE))
                w_b = float(weights.get("w_b", C.FAILOPEN_WB))
            else:
                w_p = float(getattr(weights, "w_p", C.FAILOPEN_WP))
                w_e = float(getattr(weights, "w_e", C.FAILOPEN_WE))
                w_b = float(getattr(weights, "w_b", C.FAILOPEN_WB))

            # 2) 做空方向动态收紧（用户 COIN 亏损教训：做空必须更严格）
            _dir = str(direction or "").upper()
            _short_tightened_log = None
            sb_in = max(0.0, min(1.0, float(score_b)))
            eg_in = str(elder_grade).upper()
            if _dir == "SHORT":
                # ① BCRM 小周期权重（Score_B）下调：未达 0.70 → 压到 0.55（防止单笔 conf 高但连续性弱）
                if sb_in < 0.70:
                    _old_sb = sb_in
                    sb_in = min(sb_in, 0.55)
                    _short_tightened_log = f"SHORT收紧: Score_B {_old_sb:.3f}→{sb_in:.3f}"
                # ② Elder 中周期底线：NEUTRAL 及以下 → 降一档（必须对齐才允许做空）
                if eg_in in ("NEUTRAL", "DIVERGE_BASIC", "DIVERGE_SEVERE"):
                    if eg_in == "NEUTRAL":
                        eg_in = "DIVERGE_BASIC"
                    elif eg_in == "DIVERGE_BASIC":
                        eg_in = "DIVERGE_SEVERE"
                    # DIVERGE_SEVERE 保持不变（已是最严）
                    if _short_tightened_log:
                        _short_tightened_log += f" / Elder→{eg_in}"
                    else:
                        _short_tightened_log = f"SHORT收紧: Elder→{eg_in}"

            # 3) 独立评分
            sp = self._score_p1(p1_out)
            se = self._score_elder(eg_in)

            # 4) 做空方向权重二次调节：SHORT 时 w_b 降到 0.7×原值（放大 w_p:w_e）
            if _dir == "SHORT":
                w_b *= 0.70
                # 归一化：w_p + w_e 同比放大维持 Σ=1
                _w_others = w_p + w_e
                if _w_others > 0:
                    _rescale = (1.0 - w_b) / _w_others
                    w_p = w_p * _rescale
                    w_e = w_e * _rescale
                if _short_tightened_log:
                    _short_tightened_log += f" / w_b×0.70 归一"
                else:
                    _short_tightened_log = "SHORT收紧: w_b×0.70 归一"

            # 5) 加权共识
            w_sum = w_p + w_e + w_b
            if w_sum <= 0:
                w_sum = 1.0
            score_cons = (w_p * sp + w_e * se + w_b * sb_in) / w_sum
            score_cons = max(0.0, min(1.0, score_cons))

            # 6) 映射 → base_pos_mult
            base_mult = self._consensus_to_base(score_cons)

            _src = "normal" if not _short_tightened_log else f"short_tightened:{_short_tightened_log}"
            return ElasticGate3LOutput(
                base_pos_mult=base_mult,
                score_p=sp,
                score_e=se,
                score_b=sb_in,
                score_consensus=score_cons,
                source=_src,
            )

        except Exception as e:  # noqa: BLE001 - fail-open 兜底
            from . import phase_c_constants as C
            import datetime as _dt
            hour_tag = _dt.datetime.now().strftime("%Y-%m-%dT%H")
            if self._last_failopen_logged_hour != hour_tag:
                logger.warning(
                    "[ElasticGate3L] fail-open（每小时最多 1 次），原因=%s，返回 0.10",
                    type(e).__name__,
                )
                self._last_failopen_logged_hour = hour_tag
            # 中性评分：SP=0.60, SE=0.65, SB=0.65 → 约 0.63 consensus
            return ElasticGate3LOutput(
                base_pos_mult=float(C.FAILOPEN_ELASTIC_MULT),
                score_p=0.60,
                score_e=0.65,
                score_b=0.65,
                score_consensus=0.63,
                source=f"fail_open:{type(e).__name__}",
            )
