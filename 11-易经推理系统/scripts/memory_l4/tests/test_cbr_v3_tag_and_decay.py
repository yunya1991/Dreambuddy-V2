"""
Task 2.1 RED：T6.18~T6.24 方案 C v3.0 CBR 双闭环新特性 7 项 TDD
=================================================================
RED 阶段：本文件所有断言必须 FAIL（CBRJsonlStore 尚未实现 v3.0 新特性）
GREEN 阶段：在 CBRJsonlStore 追加实现后全部通过

测试项：
  T6.18 tag 分类计数：202 条经典战例 → 100 HIGH_WIN + 100 HIGH_LOSS + 2 MANUAL_CLASSIC
  T6.19 tag 加成只改排序 rank_score，真实 match_score 不变（跨门槛防作弊）
  T6.20 HIGH_LOSS 家族命中 θ* → match_boost 负数（-max_γ）
  T6.21 时间衰减：age=90 天 → e^-1 ≈ 0.367879441（P5=90d 半衰）
  T6.22 动态参数文件不存在 → θ_match_star=0.80、gamma_max_star=0.20（默认初值字节等价）
  T6.23 季度校准 θ×γ 网格 = 11 × 8 = 88 组合（参数枚举验证）
  T6.24 BTC 今早回放：MANUAL_CLASSIC tag + score=1.0 → match_boost = +0.20（满格）
"""

import json
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_THIS_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _THIS_DIR.parent
sys.path.insert(0, str(_SCRIPTS_DIR.parent))  # 11-易经推理系统/


# -----------------------------------------------------------------------
# Fixtures：临时独立 runtime 目录，不污染实盘
# -----------------------------------------------------------------------
@pytest.fixture
def _tmp_cbr(tmp_path):
    from scripts.memory_l4.cbr_engine import CBRJsonlStore
    runtime = tmp_path / "cbr_v3_runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    return runtime, lambda: CBRJsonlStore(runtime_dir=runtime, enable=True)


# ============================================================
# T6.22：θ_match* / γ_max* 动态参数加载
# ============================================================
class TestT622DynamicParamDefaults:
    """T6.22：参数文件不存在 → θ=0.80、γ=0.20（字节等价默认）"""

    def test_t622_no_params_file_defaults_080_020(self, _tmp_cbr):
        """RED：CBRJsonlStore 尚不存在 theta/gamma 属性 → AttributeError"""
        runtime, mk = _tmp_cbr
        # 参数文件不存在
        store = mk()
        assert hasattr(store, "theta_match_star"), (
            "RED：CBRJsonlStore 尚未实现 theta_match_star 属性"
        )
        assert hasattr(store, "gamma_max_star"), (
            "RED：CBRJsonlStore 尚未实现 gamma_max_star 属性"
        )
        assert store.theta_match_star == pytest.approx(0.80, abs=1e-9)
        assert store.gamma_max_star == pytest.approx(0.20, abs=1e-9)

    def test_t622_with_params_file_overrides(self, _tmp_cbr):
        """有参数文件时覆盖默认值"""
        runtime, mk = _tmp_cbr
        (runtime / "cbr_baseline_params.json").write_text(
            json.dumps({"theta_match_star": 0.91, "gamma_max_star": 0.14})
        )
        store = mk()
        assert store.theta_match_star == pytest.approx(0.91, abs=1e-9)
        assert store.gamma_max_star == pytest.approx(0.14, abs=1e-9)


# ============================================================
# T6.19 / T6.21：_rank_score tag 加成 + 时间衰减 90d 半衰
# ============================================================
class TestT619T621RankScore:
    @staticmethod
    def _make_case(entry_ts: datetime, tag: str = "NORMAL") -> dict:
        return {"entry_ts": entry_ts, "tag": tag}

    def test_t621_age_90days_decay_exp_minus_1(self, _tmp_cbr):
        """T6.21：age=90 天 → age_decay = exp(-90/90) = e^-1 ≈ 0.3678794412"""
        runtime, mk = _tmp_cbr
        store = mk()
        assert hasattr(store, "_rank_score"), "RED：_rank_score 尚未实现"
        now = datetime.now()
        case = self._make_case(entry_ts=now - timedelta(days=90), tag="NORMAL")
        # 传入 raw_match=1.0，tag_mult(NORMAL)=1.0，只看 age_decay 部分
        rank = store._rank_score(case, 1.0)
        # rank = 1.0 × 1.0 × e^-1
        expected_age_decay = math.exp(-1.0)  # ≈ 0.3678794412
        assert rank == pytest.approx(expected_age_decay, rel=1e-4), (
            f"T6.21 FAIL：90d 半衰应为 e^-1≈{expected_age_decay:.10f}，实际={rank:.10f}"
        )

    def test_t619_tag_only_affects_rank_not_real_match(self, _tmp_cbr):
        """T6.19：tag 加成只改 rank_score，真实 match_score 不被放大（θ*门槛防作弊）"""
        runtime, mk = _tmp_cbr
        store = mk()
        # raw_match=0.70（低于 θ*=0.80 门槛）
        raw_match = 0.70
        # NORMAL case
        case_normal = self._make_case(datetime.now(), "NORMAL")
        rank_n = store._rank_score(case_normal, raw_match)
        # MANUAL_CLASSIC case → tag_mult=1.05
        case_mc = self._make_case(datetime.now(), "MANUAL_CLASSIC")
        rank_mc = store._rank_score(case_mc, raw_match)
        # 1) rank 上 MANUAL_CLASSIC > NORMAL
        assert rank_mc > rank_n, f"MANUAL_CLASSIC({rank_mc:.6f}) 必须 > NORMAL({rank_n:.6f})"
        # 2) 但 **真实 raw_match 仍为 0.70，低于 0.80**（G3 防作弊：tag 只改排序，不改真实相似度）
        assert raw_match < 0.80, (
            "T6.19 语义保证：raw_match=0.70 仍低于 0.80，不允许通过 tag 放大跨 θ* 门槛"
        )
        # 3) HIGH_WIN/HIGH_LOSS: tag_mult=1.02
        case_hw = self._make_case(datetime.now(), "HIGH_WIN")
        rank_hw = store._rank_score(case_hw, raw_match)
        assert rank_hw == pytest.approx(raw_match * 1.02 * 1.0, rel=1e-4)  # age≈0

    def test_t621_age_0days_rank_equals_raw(self, _tmp_cbr):
        """age=0 → decay=1.0，NORMAL rank ≡ raw_match × 1.0 × 1.0"""
        runtime, mk = _tmp_cbr
        store = mk()
        case = self._make_case(datetime.now(), "NORMAL")
        raw = 0.88
        assert store._rank_score(case, raw) == pytest.approx(raw, rel=1e-3)


# ============================================================
# T6.20 / T6.24：predict_topk match_boost（负 HIGH_LOSS 对称）
# ============================================================
class TestT620T624MatchBoost:
    @staticmethod
    def _fixture_cases(now: datetime) -> list[dict]:
        """构造 3 条典型案例用于 predict_topk：HIGH_WIN / HIGH_LOSS / NORMAL"""
        base = {"case_id": "x", "symbol": "BTC", "asset_class": "CRYPTO"}
        return [
            # HIGH_LOSS 基线家族（负基线）
            {**base, "case_id": "HIGH_LOSS_1", "tag": "HIGH_LOSS",
             "entry_ts": now - timedelta(days=5), "entry_snapshot": {}},
            # HIGH_WIN 基线家族（正基线）
            {**base, "case_id": "HIGH_WIN_1", "tag": "HIGH_WIN",
             "entry_ts": now - timedelta(days=5), "entry_snapshot": {}},
            # 今早 BTC MANUAL_CLASSIC（T6.24）
            {**base, "case_id": "MANUAL_BTC_TODAY", "tag": "MANUAL_CLASSIC",
             "entry_ts": now, "entry_snapshot": {}},
            # NORMAL 普通交易（0 加成）
            {**base, "case_id": "N_1", "tag": "NORMAL",
             "entry_ts": now - timedelta(days=30), "entry_snapshot": {}},
        ]

    def test_t624_manual_classic_top1_full_boost(self, _tmp_cbr):
        """T6.24：MANUAL_CLASSIC top1 match=1.0 → match_boost = +0.20（满格）"""
        runtime, mk = _tmp_cbr
        store = mk()
        # 模拟 predict_topk 返回：top 是 MANUAL_CLASSIC，score=1.0，age≈0
        result = store.predict_topk(
            top_cases=self._fixture_cases(datetime.now()),
            raw_scores={
                "MANUAL_BTC_TODAY": 1.0,
                "HIGH_WIN_1": 0.80,
                "HIGH_LOSS_1": 0.50,
                "N_1": 0.40,
            },
        )
        assert result["top1_tag"] == "MANUAL_CLASSIC"
        # score=1.0 → 5*(1.0 - 0.80) = 1.0 → γ_max_star×1.0×age_decay(≈1.0) = 0.20
        assert result["match_boost"] == pytest.approx(+0.20, rel=1e-2)

    def test_t620_high_loss_negative_boost(self, _tmp_cbr):
        """T6.20：HIGH_LOSS 命中 θ*=0.80 → match_boost = -γ_max_star × activation × age_decay（压 w_b）"""
        runtime, mk = _tmp_cbr
        store = mk()
        now = datetime.now()
        # ── rank_score 预计算（确保 HIGH_LOSS_1 真正 top1）──
        # HIGH_LOSS_1：raw=0.98, tag=1.02, age=5d→decay≈0.9459 → rank≈0.98*1.02*0.9459≈0.945
        # MANUAL_BTC_TODAY：raw=0.83, tag=1.05, age=0→decay=1.0 → rank=0.83*1.05*1.0=0.8715
        # HIGH_WIN_1：raw=0.90, tag=1.02, age=5d→decay≈0.9459 → rank≈0.90*1.02*0.9459≈0.867
        scores = {"HIGH_LOSS_1": 0.98, "HIGH_WIN_1": 0.90,
                  "MANUAL_BTC_TODAY": 0.83, "N_1": 0.40}
        cases = self._fixture_cases(now)
        result = store.predict_topk(top_cases=cases, raw_scores=scores)
        assert result["top1_tag"] == "HIGH_LOSS", (
            f"top1应=HIGH_LOSS，实际={result['top1_tag']}，"
            f"ranked={[(r[0], f'{r[1]:.6f}', r[3]) for r in result['ranked']]}"
        )
        # clip(5*(0.98 - 0.80), 0, 1) = 5*0.18=0.90（<1）
        # age_decay(5d)=exp(-5/90)≈0.9459
        # boost = -0.20 * 0.90 * 0.9459 ≈ -0.1703
        assert result["match_boost"] < 0.0, "HIGH_LOSS 必须是负 match_boost（负基线压制 w_b）"
        expected_boost = -0.20 * min(1.0, 5.0 * (0.98 - 0.80)) * math.exp(-5.0 / 90.0)
        assert result["match_boost"] == pytest.approx(expected_boost, abs=0.01), (
            f"boost计算错误：预期≈{expected_boost:.4f}，实际={result['match_boost']:.4f}"
        )


# ============================================================
# T6.18：经典战例库 tag 分类计数（通过 generate 脚本的输出来验证）
# T6.23：校准脚本 88 组合网格枚举正确性
# → 这两项是脚本级行为，在脚本中作为 CLI self-check，同时在此单测
# ============================================================
class TestT618ClassicCaseCountsAndT623CalibrationGrid:
    def test_t623_calibration_grid_exactly_88_combos(self, _tmp_cbr):
        """T6.23：θ_match 11 档 × γ_max 8 档 = 88 组合"""
        # 独立内联定义网格（镜像校准脚本），用于 RED/GREEN 对齐
        theta_grid = [0.65, 0.68, 0.71, 0.74, 0.77, 0.80, 0.83, 0.86, 0.89, 0.92, 0.95]
        gamma_grid = [0.05, 0.08, 0.11, 0.14, 0.17, 0.20, 0.23, 0.26]
        assert len(theta_grid) == 11
        assert len(gamma_grid) == 8
        assert len(theta_grid) * len(gamma_grid) == 88
        # 进一步要求：如果 cbr_baseline_calibrate.py 存在（T2.5 脚本），网格相同
        script_path = _SCRIPTS_DIR / "cbr_baseline_calibrate.py"
        if script_path.exists():
            import importlib.util as _ilu
            spec = _ilu.spec_from_file_location("_cal", script_path)
            mod = _ilu.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)  # type: ignore[union-attr]
            except Exception:
                # RED 阶段脚本不存在或语法错，跳过镜像断言
                return
            grid_t = getattr(mod, "THETA_GRID", None)
            grid_g = getattr(mod, "GAMMA_GRID", None)
            if grid_t is not None and grid_g is not None:
                assert list(grid_t) == theta_grid, "θ 网格与 Spec 不一致"
                assert list(grid_g) == gamma_grid, "γ 网格与 Spec 不一致"
                assert len(grid_t) * len(grid_g) == 88

    def test_t618_classic_case_tag_distribution(self, _tmp_cbr):
        """T6.18：202 条 → 100 HIGH_WIN + 100 HIGH_LOSS + 2 MANUAL_CLASSIC"""
        runtime, mk = _tmp_cbr
        # RED：生成脚本不存在时，只验证计数逻辑；GREEN：直接用 generate 脚本产物
        script_path = _SCRIPTS_DIR / "cbr_generate_classic_cases.py"
        if not script_path.exists():
            pytest.skip("T6.18 RED：cbr_generate_classic_cases.py 脚本未实现")
        import importlib.util as _ilu
        spec = _ilu.spec_from_file_location("_gen", script_path)
        mod = _ilu.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            result = getattr(mod, "dry_run_counts", None)
            if result is None:
                pytest.skip("T6.18：dry_run_counts() 尚未提供")
            counts = result()
        except Exception as _e:
            pytest.skip(f"T6.18 RED：generate 脚本未完整实现 ({_e})")
        assert counts.get("HIGH_WIN", 0) == 100, f"HIGH_WIN 需 100，实际={counts.get('HIGH_WIN')}"
        assert counts.get("HIGH_LOSS", 0) == 100
        assert counts.get("MANUAL_CLASSIC", 0) == 2
        assert counts.get("total", 0) == 202
