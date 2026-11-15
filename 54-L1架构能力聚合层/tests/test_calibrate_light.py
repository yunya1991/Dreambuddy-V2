# -*- coding: utf-8 -*-
"""LTL-16 点亮阈值分位标定（SPEC-54-L1交易层 §5.3 / B-LT7 / LT-AC12）。

覆盖：
  - `lit_pct = p70`、`warm_pct = p40`（线性插值，±1e-6）；
  - 默认口径 `--aggregate row`（LTL-16 定稿）：只取 `rows[].strength` 行级合成强度；
  - 样本抽取只读既有强度事实（`None`/`unavailable` 跳过，`since` 过滤）；
  - 样本不足拒绝标定（宁可保持未标定，不伪造阈值）；
  - 回写只改 `thresholds` 三键，保留注释与其余段落；`dry_run` 不落盘；重复执行字节一致；
  - 标定后 `chart_weights.load` 可复算且 `thresholds_uncalibrated=false`。
"""

import json
import os
import shutil
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)
_SCRIPTS_DIR = os.path.join(_MODULE_ROOT, "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from calibrate_light import (  # noqa: E402
    CalibrationError,
    calibrate,
    extract_row_strengths,
    extract_strengths,
    main,
    percentile,
    write_thresholds,
)
from l1agg import chart_weights  # noqa: E402
from l1agg.capabilities.lights import AXES, light_block  # noqa: E402

CONFIG_PATH = os.path.join(_MODULE_ROOT, "config", "chart_weights.yaml")


def _row(symbol, strengths, *, as_of="2026-11-14", state="warm"):
    axes = {}
    for axis, value in zip(AXES, strengths, strict=False):
        axes[axis] = {
            "strength": value,
            "state": "unavailable" if value is None else state,
        }
    return {"symbol": symbol, "as_of": as_of, "axes": axes}


@pytest.fixture()
def cfg_copy(tmp_path):
    target = tmp_path / "chart_weights.yaml"
    shutil.copyfile(CONFIG_PATH, target)
    return str(target)


# ---------------- 分位 / 标定 ----------------


def test_percentile_linear_interpolation():
    values = [float(i) for i in range(1, 11)]
    assert percentile(values, 0.70) == pytest.approx(7.3, abs=1e-9)
    assert percentile(values, 0.40) == pytest.approx(4.6, abs=1e-9)
    assert percentile(values, 0.0) == pytest.approx(1.0)
    assert percentile(values, 1.0) == pytest.approx(10.0)
    assert percentile([0.5], 0.7) == pytest.approx(0.5)
    with pytest.raises(CalibrationError):
        percentile([], 0.7)


def test_calibrate_maps_lit_to_p70_and_warm_to_p40():
    strengths = [i / 100.0 for i in range(101)]
    result = calibrate(strengths, min_samples=10)
    assert result["lit_pct"] == pytest.approx(percentile(strengths, 0.70), abs=1e-6)
    assert result["warm_pct"] == pytest.approx(percentile(strengths, 0.40), abs=1e-6)
    assert result["lit_pct"] == pytest.approx(0.70, abs=1e-6)
    assert result["warm_pct"] == pytest.approx(0.40, abs=1e-6)
    assert result["n"] == 101
    assert result["warm_pct"] <= result["lit_pct"]


def test_calibrate_rejects_insufficient_samples():
    with pytest.raises(CalibrationError):
        calibrate([0.5] * 5, min_samples=10)


def test_calibrate_warns_on_missing_axis_and_saturation():
    saturated = [1.0] * 8 + [0.2, 0.3]
    result = calibrate(
        saturated,
        min_samples=10,
        per_axis={"trend": 10, "inertia": 10, "foresight": 10},
    )
    assert result["lit_pct"] == pytest.approx(1.0)
    assert "p70_saturated_at_1.0" in result["warnings"]
    assert "axis_missing:cycle" in result["warnings"]

    healthy = calibrate(
        [i / 100.0 for i in range(101)],
        min_samples=10,
        per_axis=dict.fromkeys(AXES, 100),
    )
    assert healthy["warnings"] == []


# ---------------- 样本抽取 ----------------


def test_extract_strengths_accepts_block_list_and_rows_payload():
    rows = [
        _row("BTC", [0.8, 0.5, 0.2, 0.9]),
        _row("ETH", [None, None, None, None]),
    ]
    block_list = {"lights": rows, "meta": {"n": 2}}
    payload = {"lights": {"rows": rows}}
    plain = {"rows": rows}

    for source in (block_list, payload, plain):
        out = extract_strengths(source)
        assert out["n"] == 4
        assert out["per_axis"] == dict.fromkeys(AXES, 1)
        assert out["skipped_rows"] == 1


def test_extract_strengths_filters_by_since_and_range():
    rows = [
        _row("BTC", [0.8, 0.5, 0.2, 0.9], as_of="2023-10-31"),
        _row("ETH", [1.4, 0.6, 0.3, 0.7], as_of="2026-11-14"),
    ]
    out = extract_strengths({"lights": rows}, since="2023-11-01")
    assert out["n"] == 3  # 旧样本整行剔除；越界强度 1.4 丢弃
    assert max(out["strengths"]) <= 1.0


def test_extract_strengths_pools_multiple_snapshots():
    snapshots = [
        {"lights": [_row("BTC", [0.8, 0.5, 0.2, 0.9], as_of="2026-11-13")]},
        {"lights": [_row("BTC", [0.6, 0.4, 0.3, 0.7], as_of="2026-11-14")]},
    ]
    out = extract_strengths(snapshots)
    assert out["snapshots"] == 2
    assert out["n"] == 8
    assert out["skipped_rows"] == 0


def _composite_row(symbol, strength, **kwargs):
    row = _row(symbol, [0.9, 0.1, 0.5, 0.7], **kwargs)
    row["strength"] = strength
    return row


def test_extract_row_strengths_uses_composite_and_skips_none():
    """LTL-16 定稿口径：只取行级合成 `strength`，`None` 行跳过、不补零。"""
    rows = [
        _composite_row("BTC", 0.812),
        _composite_row("ETH", None),
        _composite_row("XAU", 0.375, as_of="2026-11-13"),
    ]
    out = extract_row_strengths({"lights": {"rows": rows}})
    assert out["n"] == 2
    assert out["strengths"] == [0.812, 0.375]
    assert out["skipped_rows"] == 1
    # 参与轴统计仍按轴事实（保留 axis_missing 告警能力）
    assert out["per_axis"] == dict.fromkeys(AXES, 2)


def test_extract_row_strengths_pools_snapshots_and_filters_since():
    snapshots = [
        {"lights": [_composite_row("BTC", 0.5, as_of="2023-10-31")]},
        {"lights": [_composite_row("BTC", 0.6, as_of="2026-11-14")]},
    ]
    out = extract_row_strengths(snapshots, since="2023-11-01")
    assert out["snapshots"] == 2
    assert out["strengths"] == [0.6]
    assert out["skipped_rows"] == 0


# ---------------- 回写 ----------------


def test_write_thresholds_preserves_comments_and_other_sections(cfg_copy):
    before = chart_weights.load(cfg_copy)
    with open(cfg_copy, "r", encoding="utf-8") as fh:
        original_text = fh.read()

    written = write_thresholds(
        cfg_copy,
        {"lit_pct": 0.6532, "warm_pct": 0.3811},
        calibrated_at="2026-11-15",
    )
    after = chart_weights.load(cfg_copy)

    assert after.thresholds["lit_pct"] == pytest.approx(0.6532, abs=1e-6)
    assert after.thresholds["warm_pct"] == pytest.approx(0.3811, abs=1e-6)
    assert after.calibrated_at == "2026-11-15"
    assert after.meta()["thresholds_uncalibrated"] is False
    assert after.members == before.members
    assert after.light_weights == before.light_weights
    assert after.light_hash() != before.light_hash()
    assert written["thresholds_uncalibrated_after"] is False
    assert written["light_weights_hash_after"] == after.light_hash()

    with open(cfg_copy, "r", encoding="utf-8") as fh:
        text = fh.read()
    assert "# 图表权重（SPEC-54-L1交易层" in text

    # 阈值行尾注释按原样保留（不因回写被吞掉或改写）
    def _comment(line_text, key):
        line = next(item for item in line_text.splitlines() if item.strip().startswith(key))
        return line.split("#", 1)[1].strip()

    assert _comment(text, "lit_pct:") == _comment(original_text, "lit_pct:")
    assert _comment(text, "warm_pct:") == _comment(original_text, "warm_pct:")
    assert "0.653200" in text and "0.381100" in text
    assert original_text.split("thresholds:")[0] == text.split("thresholds:")[0]


def test_write_thresholds_dry_run_keeps_file_untouched(cfg_copy):
    with open(cfg_copy, "rb") as fh:
        before = fh.read()
    written = write_thresholds(
        cfg_copy,
        {"lit_pct": 0.70, "warm_pct": 0.40},
        calibrated_at="2026-11-15",
        dry_run=True,
    )
    with open(cfg_copy, "rb") as fh:
        after = fh.read()
    assert before == after
    assert written["dry_run"] is True
    assert written["light_weights_hash_after"] is None
    assert "0.700000" in written["text"]


def test_write_thresholds_is_idempotent(cfg_copy):
    first = write_thresholds(
        cfg_copy, {"lit_pct": 0.6532, "warm_pct": 0.3811}, calibrated_at="2026-11-15"
    )
    with open(cfg_copy, "rb") as fh:
        once = fh.read()
    second = write_thresholds(
        cfg_copy, {"lit_pct": 0.6532, "warm_pct": 0.3811}, calibrated_at="2026-11-15"
    )
    with open(cfg_copy, "rb") as fh:
        twice = fh.read()
    assert once == twice
    assert first["replaced"] == second["replaced"]


def test_write_thresholds_rejects_invalid_order(cfg_copy):
    with open(cfg_copy, "rb") as fh:
        before = fh.read()
    with pytest.raises(CalibrationError):
        write_thresholds(cfg_copy, {"lit_pct": 0.40, "warm_pct": 0.70}, calibrated_at="2026-11-15")
    with open(cfg_copy, "rb") as fh:
        assert fh.read() == before


def test_write_thresholds_requires_thresholds_block(tmp_path):
    target = tmp_path / "no_thresholds.yaml"
    target.write_text("version: cw-1.0.0\nchart_weights:\n  BTC: 1.0\n", encoding="utf-8")
    with pytest.raises(CalibrationError):
        write_thresholds(str(target), {"lit_pct": 0.7, "warm_pct": 0.4}, calibrated_at="2026-11-15")


# ---------------- 端到端：标定 → 点亮 ----------------


def test_calibrated_config_feeds_light_block(cfg_copy):
    strengths = [i / 100.0 for i in range(101)]
    result = calibrate(strengths, min_samples=10)
    write_thresholds(cfg_copy, result, calibrated_at="2026-11-15")
    cfg = chart_weights.load(cfg_copy)

    entry = {
        "symbol": "BTC",
        "class": "crypto",
        "as_of": "2026-11-14",
        "n": 400,
        "axes": {axis: {"strength": 0.5} for axis in AXES},
    }
    block = light_block([entry], weights=cfg)
    assert block["gate"] == "ok"
    assert block["meta"]["thresholds_uncalibrated"] is False
    assert block["meta"]["thresholds"]["lit_pct"] == pytest.approx(result["lit_pct"], abs=1e-6)
    assert block["meta"]["light_weights_hash"] == cfg.light_hash()


def test_cli_dry_run_reports_without_writing(cfg_copy, tmp_path):
    rows = [_composite_row(f"S{i}", 0.5 + i / 1000.0) for i in range(300)]
    source = tmp_path / "overview.json"
    source.write_text(json.dumps({"lights": {"rows": rows}}), encoding="utf-8")
    with open(cfg_copy, "rb") as fh:
        before = fh.read()

    code = main(
        [
            "--input",
            str(source),
            "--path",
            cfg_copy,
            "--min-samples",
            "10",
            "--dry-run",
        ]
    )
    with open(cfg_copy, "rb") as fh:
        after = fh.read()
    assert code == 0
    assert before == after


def test_cli_defaults_to_row_level_composite(cfg_copy, tmp_path):
    """默认口径 = 行级合成（LTL-16）：写回的阈值必须来自 `rows[].strength` 而非轴强度。"""
    rows = []
    for index in range(300):
        row = _row(f"S{index}", [0.9, 0.9, 0.9, 0.9])
        row["strength"] = 0.30 + index / 1000.0
        rows.append(row)
    source = tmp_path / "snapshots.json"
    source.write_text(json.dumps([{"lights": {"rows": rows}}]), encoding="utf-8")

    code = main(
        [
            "--input",
            str(source),
            "--path",
            cfg_copy,
            "--min-samples",
            "10",
            "--calibrated-at",
            "2026-11-15",
        ]
    )
    assert code == 0
    cfg = chart_weights.load(cfg_copy)
    expected_lit = percentile([0.30 + index / 1000.0 for index in range(300)], 0.70)
    expected_warm = percentile([0.30 + index / 1000.0 for index in range(300)], 0.40)
    assert cfg.thresholds["lit_pct"] == pytest.approx(expected_lit, abs=1e-6)
    assert cfg.thresholds["warm_pct"] == pytest.approx(expected_warm, abs=1e-6)
    assert cfg.thresholds["lit_pct"] < 0.9  # 若退化为轴池化会取到 0.9


def test_cli_axis_mode_keeps_legacy_pooling(cfg_copy, tmp_path):
    rows = [_row(f"S{index}", [0.9, 0.9, 0.9, 0.9]) for index in range(300)]
    rows[0]["strength"] = 0.1
    source = tmp_path / "overview.json"
    source.write_text(json.dumps({"lights": rows}), encoding="utf-8")

    code = main(
        ["--input", str(source), "--path", cfg_copy, "--aggregate", "axis", "--min-samples", "10"]
    )
    assert code == 0
    cfg = chart_weights.load(cfg_copy)
    assert cfg.thresholds["lit_pct"] == pytest.approx(0.9, abs=1e-6)


def test_cli_returns_error_when_samples_insufficient(cfg_copy, tmp_path):
    source = tmp_path / "tiny.json"
    source.write_text(json.dumps({"lights": [_row("BTC", [0.5, 0.5, 0.5, 0.5])]}))
    code = main(["--input", str(source), "--path", cfg_copy, "--min-samples", "10"])
    assert code == 2
