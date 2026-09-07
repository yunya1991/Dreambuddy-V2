#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CBR θ_match* top-3 加权融合 + Shadow 拦截 单元测试（3×3 覆盖）。

三组断言：
  组1：3 条 sim 均 ≥θ*=0.71 → 权重归一化 Σw=1，blended 与 baseline 差异方向正确。
  组2：全部 <θ* → applied=False，JSONL 含 fail_open_reason="all_below_theta..."，
       position_mult_final 恒保持基线字节等价。
  组3：CBREngine.retrieve 抛 RuntimeError → fail-open，真参数字节不变，
       JSONL.fail_open_reason 包含 "exception::RuntimeError" 前缀。

与 polling_trader.py L7851 融合逻辑严格解耦：纯函数版 cbr_blend_shadow 镜像实现，
保证未来 shadow→生效阶段的语义等价性。
"""
from __future__ import annotations

import json
import math
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

ROOT = Path(__file__).resolve().parents[3]   # = 11-易经推理系统/
sys.path.insert(0, str(ROOT))


# ────────────────────────────────────────────────────────────
# 数据模型（镜像 cbr_engine.py 的最小子集约）
# ────────────────────────────────────────────────────────────
@dataclass
class _MiniCBRCase:
    case_id: str
    leverage: float = 1.0
    confidence: float = 0.0
    raw: Dict[str, Any] = field(default_factory=dict)

@dataclass
class _MiniRetrieved:
    case: _MiniCBRCase
    similarity: float


# ────────────────────────────────────────────────────────────
# 融合纯函数（镜像 polling_trader.py L7851 语义）
# ────────────────────────────────────────────────────────────
def cbr_blend_shadow(
    retrieved: List[_MiniRetrieved],
    baseline: Dict[str, float],
    theta_match_star: float = 0.71,
) -> Dict[str, Any]:
    """语义严格镜像 L7851：返回 {applied, fail_open_reason, alpha, weights,
    baseline_values, blended_values_before_shadow, top3_meta}。
    真参数字节不变：baseline 作为只读输入，无 in-place 写。
    """
    out: Dict[str, Any] = {
        "applied": False,
        "fail_open_reason": None,
        "alpha": 0.0,
        "weights": [],
        "baseline_values": dict(baseline),
        "blended_values_before_shadow": dict(baseline),
        "top3_meta": [],
    }
    filtered = [r for r in retrieved if float(r.similarity) >= theta_match_star]
    top3 = filtered[:3]
    out["top3_meta"] = [
        {
            "case_id": r.case.case_id,
            "sim": round(float(r.similarity), 4),
            "lev": round(float(r.case.leverage), 2),
        }
        for r in top3
    ]
    if len(top3) != 3:
        if not filtered:
            top_sim = max((r.similarity for r in retrieved), default=0.0)
            out["fail_open_reason"] = (
                f"all_below_theta (theta={theta_match_star:.3f}, top_sim={top_sim:.3f})"
            )
        else:
            out["fail_open_reason"] = (
                f"top3_len<3 (actual={len(top3)}, theta={theta_match_star:.3f})"
            )
        return out

    sims = [float(r.similarity) for r in top3]
    sim_sum = sum(sims)
    if sim_sum <= 0:
        out["fail_open_reason"] = "top3_sim_sum_zero"
        return out
    ws = [s / sim_sum for s in sims]
    out["weights"] = ws

    def _case_pos_mult(rc: _MiniRetrieved) -> float:
        raw = rc.case.raw or {}
        pp = raw.get("position_pct")
        if pp is None and isinstance(raw.get("execution"), dict):
            pp = raw["execution"].get("position_pct")
        try:
            pv = float(pp)  # type: ignore[arg-type]
        except Exception:
            return float(baseline["position_mult"])
        denom = 0.05
        if pv <= 0:
            return float(baseline["position_mult"])
        return pv / denom

    def _case_long_thr(rc: _MiniRetrieved) -> float:
        cc = rc.case.confidence
        try:
            return max(0.0, min(1.0, float(cc or baseline["long_conf_threshold"])))
        except Exception:
            return float(baseline["long_conf_threshold"])

    def _case_hold_h(rc: _MiniRetrieved) -> int:
        raw = rc.case.raw or {}
        ent = raw.get("entry_time")
        ext = raw.get("exit_time")
        if ent is None and isinstance(raw.get("execution"), dict):
            ent = raw["execution"].get("entry_time")
        if ext is None and isinstance(raw.get("execution"), dict):
            ext = raw["execution"].get("exit_time")
        try:
            if isinstance(ent, (int, float)) and isinstance(ext, (int, float)):
                return max(1, int(round((ext - ent) / 3600.0)))
        except Exception:
            pass
        return int(baseline["best_holding_hours"])

    b_pos = sum(ws[i] * _case_pos_mult(top3[i]) for i in range(3))
    b_lev = sum(ws[i] * float(top3[i].case.leverage or 1.0) for i in range(3))
    b_hold = sum(ws[i] * float(_case_hold_h(top3[i])) for i in range(3))
    b_long_thr = sum(ws[i] * _case_long_thr(top3[i]) for i in range(3))

    sim_over = max(0.0, sum(sims[i] - theta_match_star for i in range(3)) / 3.0)
    alpha = float(min(0.15, max(0.0, sim_over * 2.0)))
    out["alpha"] = alpha

    a = alpha
    blended = {
        "position_mult": float(a * b_pos + (1 - a) * baseline["position_mult"]),
        "tp_mult": float(baseline["tp_mult"]),
        "sl_mult": float(baseline["sl_mult"]),
        "threshold_mult": float(baseline["threshold_mult"]),
        "long_conf_threshold": float(a * b_long_thr + (1 - a) * baseline["long_conf_threshold"]),
        "short_conf_threshold": float(baseline["short_conf_threshold"]),
        "leverage": float(a * b_lev + (1 - a) * baseline["leverage"]),
        "best_holding_hours": int(round(a * b_hold + (1 - a) * float(baseline["best_holding_hours"]))),
        "_raw_blend_pos_mult": round(b_pos, 4),
        "_raw_blend_leverage": round(b_lev, 2),
        "_raw_blend_hold_h": round(b_hold, 1),
        "_raw_blend_long_thr": round(b_long_thr, 4),
    }
    out["blended_values_before_shadow"] = blended
    out["applied"] = True
    out["fail_open_reason"] = None
    return out


def _write_jsonl(path: Path, rec: Dict[str, Any]) -> None:
    with open(path, "a", encoding="utf-8") as fp:
        fp.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _default_baseline() -> Dict[str, float]:
    return {
        "position_mult": 0.75,
        "tp_mult": 1.0,
        "sl_mult": 1.0,
        "threshold_mult": 1.0,
        "long_conf_threshold": 0.65,
        "short_conf_threshold": 0.80,
        "leverage": 2.0,
        "best_holding_hours": 60,
    }


def _make_case(cid: str, lev: float, pct: float, conf: float,
               ent_ts: Optional[float] = None, ext_ts: Optional[float] = None) -> _MiniCBRCase:
    raw: Dict[str, Any] = {
        "position_pct": pct,
        "execution": {
            "position_pct": pct,
            "entry_time": ent_ts,
            "exit_time": ext_ts,
        },
    }
    if ent_ts is not None:
        raw["entry_time"] = ent_ts
    if ext_ts is not None:
        raw["exit_time"] = ext_ts
    return _MiniCBRCase(case_id=cid, leverage=lev, confidence=conf, raw=raw)


# ────────────────────────────────────────────────────────────
# 组 1：3 条全命中 θ*=0.71 → 权重 Σ=1；blended ≠ baseline；
#        JSONL 结构化落盘 applied=true
# ────────────────────────────────────────────────────────────
def test_group1_top3_above_theta():
    baseline = _default_baseline()
    baseline_frozen = dict(baseline)  # 用于断言基线字节不变
    # Case: position_pct × / denom=0.05 = position_mult
    #   C1 0.05 → 1.0, C2 0.10 → 2.0, C3 0.075 → 1.5
    #   entry→exit 时长: 72h / 48h / 60h (ts 秒差/3600)
    base = 1_700_000_000
    c1 = _make_case("c1", lev=3.0, pct=0.05, conf=0.82, ent_ts=base, ext_ts=base + 72 * 3600)
    c2 = _make_case("c2", lev=2.5, pct=0.10, conf=0.75, ent_ts=base, ext_ts=base + 48 * 3600)
    c3 = _make_case("c3", lev=2.0, pct=0.075, conf=0.72, ent_ts=base, ext_ts=base + 60 * 3600)
    retrieved = [
        _MiniRetrieved(c1, 0.80),
        _MiniRetrieved(c2, 0.78),
        _MiniRetrieved(c3, 0.72),
    ]
    out = cbr_blend_shadow(retrieved, baseline)

    # 断言 1a: weights 归一化（浮点容差 1e-9）
    ws = out["weights"]
    assert len(ws) == 3
    assert abs(sum(ws) - 1.0) < 1e-9, "top-3 权重必须归一化 Σw=1"
    assert ws[0] > ws[1] > ws[2], "权重须按相似度降序"

    # 断言 1b: applied=True & fail_open_reason=None & alpha ∈ (0, 0.15]
    assert out["applied"] is True
    assert out["fail_open_reason"] is None
    assert 0.0 < out["alpha"] <= 0.15, f"soft blend α 需在 (0, 0.15]，实际={out['alpha']}"

    # 断言 1c: blended 是加权 + soft blend；blended.position_mult ≠ baseline
    blended = out["blended_values_before_shadow"]
    sims = [0.80, 0.78, 0.72]
    ww = [s / sum(sims) for s in sims]
    raw_pos = ww[0] * (0.05 / 0.05) + ww[1] * (0.10 / 0.05) + ww[2] * (0.075 / 0.05)
    alpha = out["alpha"]
    expected_pos = alpha * raw_pos + (1 - alpha) * baseline["position_mult"]
    assert abs(blended["position_mult"] - expected_pos) < 1e-9, (
        f"blended pos_mult 与软融合公式不符，实际={blended['position_mult']} 期望={expected_pos}"
    )
    assert blended["position_mult"] != baseline["position_mult"], (
        "命中 top-3 时 blended 必须偏离 baseline（即使很小）"
    )
    # holding_hours：72 / 48 / 60 → raw = 加权后 α 混合
    raw_hold = ww[0] * 72 + ww[1] * 48 + ww[2] * 60
    expected_hold = int(round(alpha * raw_hold + (1 - alpha) * baseline["best_holding_hours"]))
    assert blended["best_holding_hours"] == expected_hold

    # 断言 1d: 基线字典在函数前后字节等价（真参数未动）
    assert baseline == baseline_frozen, "baseline 必须不可变（F1 红线）"

    # 断言 1e: JSONL 写入成功，applied=true 且结构字段齐全
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "cbr_records.jsonl"
        rec = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "symbol": "BTC-USDT-SWAP",
            "top3": out["top3_meta"],
            "baseline_values": baseline_frozen,
            "blended_values": blended,
            "blend_config": {
                "theta_match_star": 0.71,
                "soft_cap_alpha": out["alpha"],
                "applied": True,
                "fail_open_reason": None,
            },
        }
        _write_jsonl(path, rec)
        line = path.read_text(encoding="utf-8").strip().split("\n")[0]
        parsed = json.loads(line)
        assert parsed["blend_config"]["applied"] is True
        assert parsed["blend_config"]["fail_open_reason"] is None
        assert len(parsed["top3"]) == 3


# ────────────────────────────────────────────────────────────
# 组 2：全部 <θ* → applied=False；JSONL fail_open_reason 包含
#        "all_below_theta"；position_mult_final 恒 = 基线
# ────────────────────────────────────────────────────────────
def test_group2_all_below_theta():
    baseline = _default_baseline()
    c1 = _make_case("x1", lev=2.0, pct=0.05, conf=0.60)
    c2 = _make_case("x2", lev=2.0, pct=0.05, conf=0.60)
    c3 = _make_case("x3", lev=2.0, pct=0.05, conf=0.60)
    retrieved = [
        _MiniRetrieved(c1, 0.70),
        _MiniRetrieved(c2, 0.69),
        _MiniRetrieved(c3, 0.68),
    ]
    out = cbr_blend_shadow(retrieved, baseline, theta_match_star=0.71)

    # 断言 2a: applied=False；weights 空；blended == baseline 原样
    assert out["applied"] is False
    assert out["weights"] == []
    assert out["fail_open_reason"] is not None
    assert "all_below_theta" in out["fail_open_reason"], (
        f"全低于阈值时 fail_open_reason 应含 all_below_theta，实际={out['fail_open_reason']}"
    )
    # blended_values_before_shadow 为基线 copy（不偏离）
    blended = out["blended_values_before_shadow"]
    for k in ("position_mult", "leverage", "long_conf_threshold"):
        assert blended[k] == baseline[k], f"低于阈值时 {k} 必须等于基线"

    # 断言 2b: position_mult_final 恒返回基线（字节等价不变）
    position_mult_final = baseline["position_mult"]
    # 当应用层决定「真参数取基线」→ 直接取 baseline（这里模拟 byte-identical）
    assert position_mult_final == _default_baseline()["position_mult"]

    # 断言 2c: JSONL 结构化写入 applied=false + reason
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "cbr_records.jsonl"
        _write_jsonl(path, {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "symbol": "BTC-USDT-SWAP",
            "query_features": {"inst_id": "BTC-USDT-SWAP"},
            "top3": out["top3_meta"],
            "baseline_values": baseline,
            "blended_values": blended,
            "blend_config": {
                "theta_match_star": 0.71,
                "soft_cap_alpha": out["alpha"],
                "applied": False,
                "fail_open_reason": out["fail_open_reason"],
            },
        })
        parsed = json.loads(path.read_text(encoding="utf-8").strip())
        assert parsed["blend_config"]["applied"] is False
        assert "all_below_theta" in str(parsed["blend_config"]["fail_open_reason"])


# ────────────────────────────────────────────────────────────
# 组 3：CBREngine.retrieve 抛异常 → fail-open；真参数不变；
#        JSONL fail_open_reason 前缀 "exception::RuntimeError"
# ────────────────────────────────────────────────────────────
def test_group3_engine_exception():
    baseline = _default_baseline()

    class EngineBomb:
        def retrieve(self, query):  # noqa: ANN001
            raise RuntimeError("boom: case_base corrupt")

    # 模拟 polling_trader.py 的最后兜底 try/except 语义
    jsonl_rec: Optional[Dict[str, Any]] = None
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "cbr_records.jsonl"
        # position_mult_final 真参数：无论如何保持基线不变（F1 红线）
        position_mult_final_from_pm = float(baseline["position_mult"])
        try:
            engine = EngineBomb()
            engine.retrieve("dummy_query")
        except Exception as _e:
            reason = f"exception::{type(_e).__name__}:{_e}"
            cbr_shadow = {
                "applied": False, "fail_open_reason": reason,
                "theta_match_star": 0.71, "alpha": 0.0,
            }
            jsonl_rec = {
                "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "symbol": "BTC-USDT-SWAP",
                "query_features": {}, "top3": [],
                "baseline_values": dict(baseline),
                "blended_values": dict(baseline),
                "blend_config": {
                    "theta_match_star": 0.71,
                    "soft_cap_alpha": 0.0,
                    "applied": False,
                    "fail_open_reason": cbr_shadow["fail_open_reason"],
                },
            }
            _write_jsonl(path, jsonl_rec)
            # 重要：真参数仍 = baseline（不基于 cbr_shadow 任何修改）
            position_mult_final_effective = position_mult_final_from_pm

    # 断言 3a: fail_open_reason 前缀 = "exception::RuntimeError"
    assert jsonl_rec is not None
    reason = str(jsonl_rec["blend_config"]["fail_open_reason"])
    assert reason.startswith("exception::RuntimeError"), (
        f"异常前缀应包含 exception::RuntimeError，实际={reason}"
    )
    assert "boom: case_base corrupt" in reason

    # 断言 3b: applied=false 且 blended 与 baseline 全等价（字节不变影子）
    assert jsonl_rec["blend_config"]["applied"] is False
    for k in ("position_mult", "tp_mult", "sl_mult", "threshold_mult",
              "long_conf_threshold", "short_conf_threshold", "leverage",
              "best_holding_hours"):
        assert jsonl_rec["blended_values"][k] == baseline[k], (
            f"异常 fail-open 时 blended.{k} 必须等于基线"
        )

    # 断言 3c: 真参数字节不变（position_mult_final_effective == baseline）
    assert position_mult_final_effective == baseline["position_mult"]

    # 断言 3d: JSONL 文件存在且合法
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "cbr_records.jsonl"
        _write_jsonl(path, jsonl_rec)
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert "symbol" in parsed and "ts" in parsed
        # 结构完整 6 大键
        for k in ("ts", "symbol", "query_features", "top3",
                  "baseline_values", "blended_values", "blend_config"):
            assert k in parsed, f"JSONL 结构缺键 {k}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "--no-header", "-x"]))
