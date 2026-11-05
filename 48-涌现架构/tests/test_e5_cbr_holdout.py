"""E5 CBR holdout 原语组合泛化实验测试（SPEC-EMERGENCE-EVOLUTION v0.5 §4 E5 / §1 E1）。

判据 M6（E1 金标准）：把某原语组合（regime 形态 cell）从案例库整体扣留，
测试系统能否用其余案例"组合"出对该新形态的正确响应——
组合方法（逐原语边际条件独立学习、测试时组合，SCAN 式）必须显著优于
最近邻检索复用基线，方向为正 → e1_candidate；方向负且显著 → falsified（E3 β 教训）。

覆盖：
  - 双库统一加载（washout_reversal / pump_dump_reversal → 统一原语 schema + 二值标签）
  - 原语中位数分箱 → cell 组合键
  - holdout 划分：训练集绝不含 holdout cell（SCAN 核心约束）
  - SCAN 性质 toy 检验：训练只见 (0,0,0)/(1,1,1) 类组合时，组合法能泛化到未见过
    的 (1,1,0) 而 NN 基线失败
  - 置换检验 p∈[0,1] + 方向检查（显著为负 → falsified）
  - 样本不足 → insufficient_data 如实返回 + E6 需求单联动（created_by=e5_cbr_holdout）
  - 同态误差（辅助指标）范围合理
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

_E5_DIR = Path(__file__).resolve().parents[1] / "experiments" / "e5_cbr_holdout"
if str(_E5_DIR) not in sys.path:
    sys.path.insert(0, str(_E5_DIR))

import cbr_holdout as ch  # noqa: E402

# ---------- 构造工具 ----------


def _mk_case(
    case_id: str,
    label: str,
    setup: float = 0.5,
    ending: float = 0.5,
    combined: float = 0.5,
    hold_days: float = 7.0,
    library: str = "washout_reversal",
) -> dict:
    setup_key = "washout_confidence" if library == "washout_reversal" else "weakness_confidence"
    return {
        "case_id": case_id,
        "coin": "BTC",
        "entry_time": "2023-01-01T00:00:00+00:00",
        "exit_time": "2023-01-08T00:00:00+00:00",
        "features_snapshot": {
            setup_key: setup,
            "ending_confidence": ending,
            "combined_confidence": combined,
            "entry_price": 20000.0,
            "hold_days": hold_days,
        },
        "actual_label": label,
        "pnl_pct": 0.01,
        "reward": 0.46,
        "timestamp": "2026-09-22T00:00:00+00:00",
    }


def _write_jsonl(path: Path, cases: list) -> None:
    path.write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in cases) + "\n",
        encoding="utf-8",
    )


# ---------- 加载与统一 schema ----------


def test_load_cases_unifies_two_libraries(tmp_path):
    w = tmp_path / "washout.jsonl"
    p = tmp_path / "pump.jsonl"
    _write_jsonl(w, [_mk_case("w1", "reversal_long_success", library="washout_reversal")])
    _write_jsonl(p, [_mk_case("p1", "reversal_short_fail", library="pump_dump_reversal")])
    cases = ch.load_cases({"washout_reversal": w, "pump_dump_reversal": p})
    assert len(cases) == 2
    by_id = {c["case_id"]: c for c in cases}
    assert by_id["w1"]["label"] == 1
    assert by_id["p1"]["label"] == 0
    # 统一原语向量：is_short 标志正确
    assert by_id["w1"]["features"][-1] == pytest.approx(0.0)
    assert by_id["p1"]["features"][-1] == pytest.approx(1.0)
    # entry_price 不是市场原语，不应进入特征向量
    assert len(by_id["w1"]["features"]) == len(ch.PRIMITIVES)


def test_load_cases_missing_file_returns_empty(tmp_path):
    cases = ch.load_cases({"washout_reversal": tmp_path / "nope.jsonl"})
    assert cases == []


# ---------- 分箱与 cell ----------


def test_binning_assigns_cells_by_median():
    rng = np.random.default_rng(0)
    cases = []
    for i in range(40):
        cases.append(
            {
                "case_id": f"c{i}",
                "features": np.array([rng.random(), rng.random(), rng.random(), 7.0, 0.0]),
                "label": i % 2,
            }
        )
    ch.assign_cells(cases)
    assert all("cell" in c for c in cases)
    # 每个连续原语高低两侧应大致各半
    highs = sum(1 for c in cases if c["cell"][0] == 1)
    assert 15 <= highs <= 25
    # is_short 列保持 0/1 原值
    assert {c["cell"][-1] for c in cases} == {0}


# ---------- holdout 划分 ----------


def test_holdout_split_excludes_cell_from_train():
    cases = []
    # cell A：全高原语（holdout 目标）
    for i in range(10):
        cases.append(
            {
                "case_id": f"a{i}",
                "features": np.array([0.9, 0.9, 0.9, 9.0, 0.0]),
                "label": 1,
                "cell": (1, 1, 1, 1, 0),
            }
        )
    # 其余 cell
    for i in range(70):
        cases.append(
            {
                "case_id": f"b{i}",
                "features": np.array([0.1, 0.1, 0.1, 3.0, 0.0]),
                "label": 0,
                "cell": (0, 0, 0, 0, 0),
            }
        )
    train, holdout = ch.holdout_split(cases, (1, 1, 1, 1, 0))
    assert len(holdout) == 10
    assert len(train) == 70
    assert all(c["cell"] != (1, 1, 1, 1, 0) for c in train)


def test_select_holdout_cells_respects_min_sizes():
    cases = (
        [{"cell": (1, 1, 1, 1, 0)} for _ in range(5)]
        + [{"cell": (0, 0, 0, 0, 0)} for _ in range(200)]
        + [{"cell": (0, 1, 0, 1, 0)} for _ in range(100)]
    )
    # cell (1,1,1,1,0) 只有 5 条 < min_cell=8 → 不可选
    cells = ch.select_holdout_cells(cases, min_cell=8, min_train=60)
    assert (1, 1, 1, 1, 0) not in cells
    assert (0, 0, 0, 0, 0) in cells


# ---------- SCAN 核心性质：组合泛化 > 检索复用 ----------


def _scan_toy_cases():
    """4 信息原语 + is_short=0；label = (b1+b2+b3+b4 >= 2)；扣留 cell (1,1,0,0)。

    训练 15 cell：5 个 fail cell（<2 个 1）× 5 案例 + 10 个 succ cell × 5 案例
    （fail cell 案例先入库，保证 kNN 稳定排序下同距离 fail 邻居在前）。
    组合法（逐原语贡献线性组合）应泛化到未见组合 (1,1,0,0) → success；
    kNN(k=3) 基线的最近邻为 fail cell (1,0,0,0)/(0,1,0,0) → 全部误判 fail。
    """
    fail_cells = [(0, 0, 0, 0), (1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)]
    succ_cells = [
        (1, 1, 1, 0),
        (1, 1, 0, 1),
        (1, 0, 1, 1),
        (0, 1, 1, 1),
        (1, 1, 1, 1),
        (1, 0, 1, 0),
        (0, 1, 0, 1),
        (0, 0, 1, 1),
        (1, 0, 0, 1),
        (0, 1, 1, 0),
    ]
    cases = []
    for cell in fail_cells:  # fail 在前（稳定排序决胜）
        for i in range(5):
            full = tuple(cell) + (0,)
            cases.append(
                {
                    "case_id": f"f{cell}{i}",
                    "features": np.array(full, dtype=float),
                    "label": 0,
                    "cell": full,
                }
            )
    for cell in succ_cells:
        for i in range(5):
            full = tuple(cell) + (0,)
            cases.append(
                {
                    "case_id": f"s{cell}{i}",
                    "features": np.array(full, dtype=float),
                    "label": 1,
                    "cell": full,
                }
            )
    for i in range(5):
        cases.append(
            {
                "case_id": f"h{i}",
                "features": np.array((1, 1, 0, 0, 0), dtype=float),
                "label": 1,
                "cell": (1, 1, 0, 0, 0),
            }
        )
    return cases


def test_scan_property_composition_generalizes_nn_fails():
    cases = _scan_toy_cases()
    train, holdout = ch.holdout_split(cases, (1, 1, 0, 0, 0))
    comp_probs = ch.composition_predict(train, holdout)
    knn_probs = ch.knn_baseline_predict(train, holdout, k=3)
    comp_pred = [int(p >= 0.5) for p in comp_probs]
    knn_pred = [int(p >= 0.5) for p in knn_probs]
    # 组合法：5/5 正确（泛化到未见组合）
    assert comp_pred == [1, 1, 1, 1, 1]
    # 最近邻检索复用：全部失败（最近邻多数为 fail cell）
    assert knn_pred == [0, 0, 0, 0, 0]


# ---------- 置换检验与判定 ----------


def test_permutation_test_bounds_and_direction():
    rng = np.random.default_rng(42)
    # 组合法明显优于基线
    nb_correct = np.array([1] * 18 + [0] * 2, dtype=float)
    nn_correct = np.array([1] * 8 + [0] * 12, dtype=float)
    p, obs = ch.permutation_test(nb_correct, nn_correct, n_perm=2000, rng=rng)
    assert 0.0 <= p <= 1.0
    assert obs > 0
    assert p < 0.05


def test_verdict_falsified_when_direction_negative():
    # 显著但方向为负（E3 β 原型教训回归）
    res = ch.verdict(median_improvement=-0.25, p_value=0.01, n_eval=40)
    assert res == "falsified"
    res2 = ch.verdict(median_improvement=0.25, p_value=0.01, n_eval=40)
    assert res2 == "e1_candidate"
    res3 = ch.verdict(median_improvement=0.05, p_value=0.40, n_eval=40)
    assert res3 == "inconclusive"
    res4 = ch.verdict(median_improvement=0.25, p_value=0.01, n_eval=5)
    assert res4 == "insufficient_data"


# ---------- 同态误差（辅助指标） ----------


def test_homomorphism_error_range():
    rng = np.random.default_rng(1)
    cases = []
    for i in range(30):
        cases.append(
            {
                "case_id": f"c{i}",
                "features": rng.random(5),
                "label": int(rng.random() > 0.5),
            }
        )
    val = ch.homomorphism_error(cases, rng=rng, max_pairs=200)
    assert val is None or -1.0 <= val <= 1.0


# ---------- 端到端：insufficient_data + E6 联动 ----------


def test_run_insufficient_data_emits_e6_gap(tmp_path):
    gaps = tmp_path / "capability_gaps.jsonl"
    result = ch.run(
        sources={"washout_reversal": tmp_path / "none.jsonl"},
        gaps_path=gaps,
        min_cases_total=30,
    )
    assert result["status"] == "insufficient_data"
    assert gaps.exists()
    gap = json.loads(gaps.read_text(encoding="utf-8").strip().splitlines()[0])
    assert gap["created_by"] == "e5_cbr_holdout"
    assert gap["gap_type"] == "case_sparse"


def test_run_end_to_end_on_toy(tmp_path):
    w = tmp_path / "washout.jsonl"
    cases = []
    rng = np.random.default_rng(7)
    # 生成 120 案例：success 概率随原语和上升（可组合结构）
    for i in range(120):
        b = rng.random(3)
        label = 1 if (b[0] + b[1] + b[2] >= 1.5) else 0
        if rng.random() < 0.1:
            label = 1 - label  # 10% 噪声
        cases.append(
            _mk_case(
                f"c{i}",
                "reversal_long_success" if label else "reversal_long_fail",
                setup=float(b[0]),
                ending=float(b[1]),
                combined=float(b[2]),
                hold_days=float(3 + 6 * rng.random()),
            )
        )
    _write_jsonl(w, cases)
    result = ch.run(
        sources={"washout_reversal": w},
        gaps_path=tmp_path / "gaps.jsonl",
        min_cases_total=30,
        min_cell=4,
        min_train=60,
        n_perm=500,
        seed=0,
    )
    assert result["status"] in ("ok", "insufficient_data")
    if result["status"] == "ok":
        assert result["verdict"] in ("e1_candidate", "falsified", "inconclusive")
        assert result["n_eval"] > 0
        assert 0.0 <= result["p_value"] <= 1.0
        assert "homomorphism_error" in result


# ============================================================
# shadow_rl 回填适配器（2026-11-06）
# 数据源：23 域 gene_data/shadow_rl_samples.jsonl
#   42.17 万行 / 16.59 万唯一 5 维市场状态向量（R_up/R_down/R_smooth/R_flow/R_reflexivity）
#   85% 为 WAIT 动作 → 只取入场决策（long/light_long/short），is_short 作为第 6 维
# ============================================================


def _mk_rl_sample(
    r_up: float,
    r_down: float,
    r_smooth: float,
    r_flow: float,
    r_reflex: float,
    action: str,
    reward: float,
    symbol: str = "BTC",
) -> dict:
    return {
        "symbol": symbol,
        "state": {
            "R_up": r_up,
            "R_down": r_down,
            "R_smooth": r_smooth,
            "R_flow": r_flow,
            "R_reflexivity": r_reflex,
            "quality_score": 0.9,
        },
        "action": action,
        "reward": reward,
        "next_state": {},
    }


def test_load_shadow_rl_filters_wait_and_maps_primitives(tmp_path):
    path = tmp_path / "shadow_rl.jsonl"
    rows = [
        _mk_rl_sample(0.8, 0.2, 0.1, 0.9, 0.5, "long", 0.5),
        _mk_rl_sample(0.3, 0.7, 0.2, 0.1, 0.4, "short", -0.5),
        _mk_rl_sample(0.5, 0.5, 0.0, 0.5, 0.5, "WAIT", 0.0),  # 应被过滤
        _mk_rl_sample(0.6, 0.4, 0.1, 0.7, 0.3, "light_long", 0.2),
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    cases = ch.load_shadow_rl_cases(path, label_mode="positive")
    assert len(cases) == 3  # WAIT 被过滤
    assert all(c["library"] == "shadow_rl" for c in cases)
    assert all(len(c["features"]) == 6 for c in cases)
    # 第 1-5 维为市场状态原语，第 6 维 is_short
    assert cases[0]["features"][:5] == pytest.approx([0.8, 0.2, 0.1, 0.9, 0.5])
    assert cases[0]["features"][5] == 0.0
    assert cases[1]["features"][5] == 1.0  # short
    # positive 口径：reward > 0
    assert [c["label"] for c in cases] == [1, 0, 1]


def test_load_shadow_rl_label_mode_median_balances(tmp_path):
    path = tmp_path / "shadow_rl.jsonl"
    rows = [
        _mk_rl_sample(0.8, 0.2, 0.1, 0.9, 0.5, "long", 3.0),
        _mk_rl_sample(0.7, 0.3, 0.1, 0.8, 0.5, "long", 2.0),
        _mk_rl_sample(0.2, 0.8, 0.1, 0.2, 0.5, "short", -1.0),
        _mk_rl_sample(0.1, 0.9, 0.1, 0.1, 0.5, "short", -2.0),
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    cases = ch.load_shadow_rl_cases(path, label_mode="median")
    assert sum(c["label"] for c in cases) == 2  # 中位数以上为正例


def test_load_shadow_rl_missing_file_returns_empty(tmp_path):
    assert ch.load_shadow_rl_cases(tmp_path / "nope.jsonl") == []


def test_load_shadow_rl_drops_zero_reward(tmp_path):
    """实测 reward 92.9% 为 0（未平仓占位），保留会让准确率虚高。"""
    path = tmp_path / "shadow_rl.jsonl"
    rows = [
        _mk_rl_sample(0.8, 0.2, 0.1, 0.9, 0.5, "long", 0.0),
        _mk_rl_sample(0.7, 0.3, 0.1, 0.8, 0.5, "long", 0.3),
        _mk_rl_sample(0.2, 0.8, 0.1, 0.2, 0.5, "short", 0.0),
        _mk_rl_sample(0.1, 0.9, 0.1, 0.1, 0.5, "short", -0.2),
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    dropped = ch.load_shadow_rl_cases(path, drop_zero=True)
    assert len(dropped) == 2  # 两条 reward=0 被丢弃
    kept = ch.load_shadow_rl_cases(path, drop_zero=False)
    assert len(kept) == 4


def test_assign_cells_supports_five_continuous_primitives(tmp_path):
    path = tmp_path / "shadow_rl.jsonl"
    rows = [
        _mk_rl_sample(
            0.1 * (i % 10),
            0.1 * ((i + 3) % 10),
            0.1 * ((i + 5) % 10),
            0.1 * ((i + 7) % 10),
            0.5,
            "long",
            0.1,
        )
        for i in range(40)
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    cases = ch.load_shadow_rl_cases(path, label_mode="positive")
    ch.assign_cells(cases, n_continuous=5)
    # 5 个连续原语 → cell 键长度 6（5 分箱 + is_short）
    assert all(len(c["cell"]) == 6 for c in cases)
    assert {c["cell"][5] for c in cases} == {0}  # 全 long


def test_stratified_sample_caps_total_and_keeps_cells():
    cases = []
    for cell_i in range(4):
        for j in range(25):
            cases.append(
                {
                    "case_id": f"{cell_i}-{j}",
                    "library": "shadow_rl",
                    "features": np.zeros(6),
                    "label": j % 2,
                    "cell": (cell_i, 0, 0, 0, 0, 0),
                }
            )
    rng = np.random.default_rng(0)
    sampled = ch._stratified_sample(cases, max_cases=40, rng=rng)
    assert len(sampled) <= 40
    assert {c["cell"][0] for c in sampled} == {0, 1, 2, 3}  # 每 cell 都被覆盖


def test_run_shadow_rl_source_reports_metadata(tmp_path):
    path = tmp_path / "shadow_rl.jsonl"
    rows = []
    for i in range(400):
        a = 0.01 * (i % 100)
        rows.append(
            _mk_rl_sample(
                a,
                1.0 - a,
                0.01 * ((i * 7) % 100),
                0.01 * ((i * 13) % 100),
                0.5,
                "long" if i % 3 else "short",
                0.01 * ((i * 17) % 200) - 1.0,
            )
        )
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    result = ch.run(
        source="shadow_rl",
        shadow_rl_path=path,
        gaps_path=tmp_path / "gaps.jsonl",
        max_cases=200,
        min_cell=8,
        min_train=60,
        min_eval=20,
        n_perm=200,
        seed=0,
    )
    assert result["source"] == "shadow_rl"
    assert result["label_mode"] == "positive"
    # 部分 reward=0 被丢弃（drop_zero 默认开），故 loaded < 400
    assert 350 <= result["n_cases_loaded"] < 400
    assert result["n_cases"] <= 200
    assert 0.0 <= result["pos_ratio"] <= 1.0
    assert result["status"] in ("ok", "insufficient_data")
