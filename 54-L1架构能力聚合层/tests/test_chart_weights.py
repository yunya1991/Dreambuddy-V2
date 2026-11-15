# -*- coding: utf-8 -*-
"""P0-2 图表权重（chart_weights / light_weights / 三权分立 / 短样本裁剪）。

覆盖评审阻断项与硬约束：
  - B-LT3：`chart_weights` / `light_weights` / 交易 `axis_weights` 三者互不共用（域分离 hash）
  - LT-G2：决策层入参与 signal 字段禁止出现 chart_weights（递归断言）
  - LT-G3：同输入同 hash 必须字节一致（可回放）
  - §4.3 规则 3/5：短样本成员权重置 0 并重归一；加载期 fail-closed、运行期降级等权
  - §4.1：chart_weights 默认 on（无否决门），off 为回滚档
"""

import inspect
import json
import os
import sys

import pytest
import yaml

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg import chart_weights as CW  # noqa: E402
from l1agg import leader_registry as R  # noqa: E402
from l1agg.trading import weights as TW  # noqa: E402

MODULE_DIR = os.path.dirname(CW.__file__)


@pytest.fixture(scope="module")
def cfg():
    return CW.load()


def _write(tmp_path, data):
    path = tmp_path / "chart_weights.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return str(path)


def _valid_raw():
    return {
        "version": "cw-test",
        "mode": "on",
        "constraints": {
            "min_weight": 0.0,
            "max_weight": 0.60,
            "sum_tolerance": 1e-6,
            "min_rows": 250,
        },
        "chart_weights": {"BTC": 0.60, "XAU": 0.40},
        "views": {"加密": 0.60, "避险": 0.40},
        "light_weights": {"trend": 0.40, "inertia": 0.25, "cycle": 0.15, "foresight": 0.20},
        "thresholds": {"lit_pct": 0.70, "warm_pct": 0.40, "calibrated_at": ""},
    }


# ============================================================ 配置契约
def test_config_loads_and_normalized(cfg):
    assert cfg.version == "cw-1.0.0"
    assert cfg.mode == "on" and cfg.enabled is True
    assert cfg.source == "config"
    assert abs(sum(cfg.members.values()) - 1.0) < 1e-6
    assert abs(sum(cfg.views.values()) - 1.0) < 1e-6
    assert abs(sum(cfg.light_weights.values()) - 1.0) < 1e-6
    assert cfg.min_rows == 250


def test_members_match_default_pool(cfg):
    """成员权重必须与首屏池一一对应（多/少都会让聚合曲线口径漂移）。"""
    assert set(cfg.members) == set(R.DEFAULT_POOL)


def test_views_match_five_views(cfg):
    assert set(cfg.views) == {"加密", "避险", "大宗", "美股", "情绪"}


def test_thresholds_uncalibrated_meta(cfg):
    meta = cfg.meta()
    assert meta["thresholds_uncalibrated"] is True
    assert meta["chart_weights_mode"] == "on"
    assert len(meta["chart_weights_hash"]) == 64


# ============================================================ 三权分立 / 域分离（B-LT3）
def test_hash_domain_separation(cfg):
    """同一组数值在 chart / light 两个域必须得到不同指纹（禁止跨层复用权重）。"""
    same = {axis: cfg.light_weights[axis] for axis in CW.LIGHT_AXES}
    assert CW.chart_weights_hash(same) != CW.light_weights_hash(same)
    assert cfg.hash() != cfg.light_hash()
    assert CW.CHART_WEIGHTS_VERSION != TW.WEIGHTS_VERSION


def test_hash_is_order_independent_and_deterministic():
    a = {"BTC": 0.6, "XAU": 0.4}
    b = {"XAU": 0.4, "BTC": 0.6}
    assert CW.chart_weights_hash(a) == CW.chart_weights_hash(b)
    assert CW.chart_weights_hash(a) == CW.chart_weights_hash(dict(a))


def test_hash_changes_with_weights():
    base = {"BTC": 0.6, "XAU": 0.4}
    tuned = {"BTC": 0.55, "XAU": 0.45}
    assert CW.chart_weights_hash(base) != CW.chart_weights_hash(tuned)


def test_light_hash_includes_thresholds():
    axes = {"trend": 0.4, "inertia": 0.3, "cycle": 0.1, "foresight": 0.2}
    a = CW.light_weights_hash(axes, {"lit_pct": 0.70, "warm_pct": 0.40})
    b = CW.light_weights_hash(axes, {"lit_pct": 0.75, "warm_pct": 0.45})
    assert a != b


def test_no_trading_hash_import():
    """图表权重不得复用交易权重的 hash/常量（LT-G2 源码级断言）。"""
    source = open(CW.__file__, encoding="utf-8").read()
    assert "trading import" not in source
    assert "import trading" not in source
    assert "TW." not in source


# ============================================================ 加载期 fail-closed（§4.3 规则 5）
@pytest.mark.parametrize(
    "mutate,message",
    [
        (lambda d: d["chart_weights"].update({"XAU": 0.50}), "权重和"),
        (lambda d: d["chart_weights"].update({"XAU": 0.10, "BTC": 0.90}), "越界"),
        (lambda d: d["chart_weights"].update({"XAU": -0.40, "BTC": 1.40}), "越界"),
        (lambda d: d.update({"mode": "auto"}), "mode 非法"),
        (lambda d: d["light_weights"].pop("cycle"), "light_weights 缺少轴"),
        (lambda d: d["thresholds"].update({"lit_pct": 0.30, "warm_pct": 0.60}), "阈值非法"),
    ],
)
def test_invalid_config_fails_closed(tmp_path, mutate, message):
    data = _valid_raw()
    mutate(data)
    with pytest.raises(CW.ChartWeightsError, match=message):
        CW.load(_write(tmp_path, data))


def test_unknown_source_rejected(cfg):
    with pytest.raises(CW.ChartWeightsError, match="source 非法"):
        CW.load(source="slider")


def test_ui_override_changes_hash(cfg):
    tuned = dict(cfg.members)
    tuned["BTC"] = 0.25
    tuned["NVDA"] = 0.0
    tuned = CW.normalize(tuned)
    slider = CW.load(override_members=tuned, source="ui")
    assert slider.source == "ui"
    assert slider.hash() != cfg.hash()
    assert abs(sum(slider.members.values()) - 1.0) < 1e-6


# ============================================================ 短样本裁剪（§4.3 规则 3）
def test_prune_short_members_renormalizes(cfg):
    sample = dict.fromkeys(cfg.members, 800)
    sample["GEV"] = 179  # 若被加进成员权重，必须被裁掉
    members = dict(cfg.members)
    members["GEV"] = 0.0
    members = CW.normalize(members)
    result = CW.prune_short_members(members, sample)
    assert [d["symbol"] for d in result["dropped"]] == ["GEV"]
    assert result["dropped"][0]["reason"] == "insufficient_history"
    assert "GEV" not in result["weights"]
    assert abs(sum(result["weights"].values()) - 1.0) < 1e-6


def test_prune_all_members_degrades(cfg):
    result = CW.prune_short_members(cfg.members, dict.fromkeys(cfg.members, 100))
    assert result["degraded"] is True
    assert result["reason"] == "all_members_insufficient"
    assert result["weights"] == {}


# ============================================================ 运行期解析（FAIL-OPEN）
def test_resolve_members_active(cfg):
    sample = dict.fromkeys(cfg.members, 800)
    resolved = CW.resolve_members(cfg, sample)
    assert resolved["weights"] == cfg.members
    assert resolved["chart_weights_hash"] == cfg.hash()
    assert resolved["weights_degraded"] is False
    assert all(m["status"] == "active" for m in resolved["members"])


def test_resolve_members_drops_short_and_renormalizes(cfg):
    sample = dict.fromkeys(cfg.members, 800)
    sample["XAG"] = 290  # ≥250 保留
    sample["VIX"] = 0  # not_collected → 裁掉
    resolved = CW.resolve_members(cfg, sample)
    assert [d["symbol"] for d in resolved["dropped"]] == ["VIX"]
    assert abs(sum(resolved["weights"].values()) - 1.0) < 1e-6
    assert resolved["pruned"] is True
    assert resolved["weights_degraded"] is False


def test_resolve_members_mode_off_equal_weights(cfg):
    resolved = CW.resolve_members(cfg, dict.fromkeys(cfg.members, 800), mode="off")
    assert resolved["chart_weights_source"] == "equal"
    assert "chart_weights_off" in resolved["flags"]
    assert resolved["chart_weights_hash"] == CW.chart_weights_hash(resolved["weights"])


def test_resolve_members_invalid_runtime_degrades(cfg):
    bad = {"BTC": "oops", "XAU": 0.4}
    resolved = CW.resolve_members(bad, {"BTC": 800, "XAU": 800})
    assert resolved["weights_degraded"] is True
    assert resolved["chart_weights_source"] == "equal"
    assert "chart_weights_degraded" in resolved["flags"]
    assert abs(sum(resolved["weights"].values()) - 1.0) < 1e-6


def test_resolve_members_missing_state_degrades():
    resolved = CW.resolve_members({"BTC": 0.5, "XAU": 0.5}, {"BTC": 0, "XAU": 0})
    assert resolved["weights_degraded"] is True
    assert abs(sum(resolved["weights"].values()) - 1.0) < 1e-6


# ============================================================ LT-G2：决策层隔离
def test_assert_no_chart_weights_blocks_nested(cfg):
    payload = {"symbol": "BTC", "meta": {"chart_weights": cfg.members}}
    with pytest.raises(CW.ChartWeightsError, match="chart_weights"):
        CW.assert_no_chart_weights(payload)


def test_assert_no_chart_weights_blocks_signal_envelope(cfg):
    signal = {"side": "long", "items": [{"light_weights_hash": "x"}]}
    with pytest.raises(CW.ChartWeightsError, match="light_weights_hash"):
        CW.assert_no_chart_weights(signal)


def test_assert_no_chart_weights_passes_signal(cfg):
    signal = {
        "symbol": "BTC",
        "axis_weights": {"trend": 0.4, "adx": 0.25, "inertia": 0.2, "coherence": 0.15},
        "weights_hash": "abc",
    }
    CW.assert_no_chart_weights(signal)  # 不抛错


def test_trading_modules_do_not_accept_chart_weights():
    """交易层任何公开函数都不得出现 chart 相关入参（LT-G2 机器断言）。"""
    offenders = []
    for name in sorted(os.listdir(os.path.join(MODULE_DIR, "trading"))):
        if not name.endswith(".py") or name.startswith("__"):
            continue
        module_name = f"l1agg.trading.{name[:-3]}"
        module = __import__(module_name, fromlist=["*"])
        for attr, fn in vars(module).items():
            if getattr(fn, "__module__", "") != module_name:
                continue
            if not (inspect.isfunction(fn) or inspect.isclass(fn)):
                continue
            try:
                params = inspect.signature(fn).parameters
            except (TypeError, ValueError):
                continue
            for param in params:
                if "chart" in param or "light_weight" in param:
                    offenders.append(f"{module_name}.{attr}({param})")
    assert offenders == []


# ============================================================ 可回放（LT-G3）
def test_meta_is_json_stable(cfg):
    a = json.dumps(cfg.meta(), sort_keys=True)
    b = json.dumps(CW.load().meta(), sort_keys=True)
    assert a == b
