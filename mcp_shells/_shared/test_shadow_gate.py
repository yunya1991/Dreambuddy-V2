#!/usr/bin/env python3
"""test_shadow_gate.py — 数据门禁 / 自动推进 / S1 签名提取器验收

覆盖：
  - 提取器：维度契约、lead-lag 滞后、窗口不足 FAIL-OPEN、无 NaN
  - 门禁：数据不足不推进 / 满足阈值推进 S1 / 消融未通过不推进 S3 / 开关默认关
  - 影子：S1 开启后 observe 返回 signatures，默认关闭不返回
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mcp_shells._shared import shadow_gate as gate_mod  # noqa: E402
from mcp_shells._shared.agent_mail_shadow import AgentMailShadow  # noqa: E402
from mcp_shells._shared.temporal_signature_extractor import (  # noqa: E402
    TemporalSignatureExtractor,
)


def _steps(domain: str, n: int, start_ts: float, step_sec: float, lag: int = 0) -> list:
    """构造 n 步窗口：poe 为正弦，延迟 lag 步 → 用于验证 lead-lag 符号。"""
    out = []
    for i in range(n):
        phase = 2.0 * math.pi * max(0, i - lag) / 8.0
        out.append(
            {
                "ts": start_ts + i * step_sec,
                "poe_score": round(math.sin(phase) + 1.0, 4),
                "latency_ms": round(10.0 + 2.0 * math.cos(phase), 4),
                "messages_sent": 1.0,
                "cross_domain_refs": 0.0,
                "n": 1,
            }
        )
    return out


def test_extractor_dimension_and_lead_lag():
    extractor = TemporalSignatureExtractor()
    windows = {
        "data": _steps("data", 24, 1_700_000_000.0, 300.0, lag=0),
        "eval": _steps("eval", 24, 1_700_000_000.0, 300.0, lag=2),
    }
    out = extractor.extract(windows)
    assert out["ready"] is True
    assert out["domains"] == ["data", "eval"]
    assert out["dim"] == 2 * 2 * 5 + 1 * 2
    assert len(out["vector"]) == out["dim"]
    assert all(isinstance(x, float) and math.isfinite(x) for x in out["vector"])
    pair = out["pairs"]["data↔eval"]
    assert pair["lag_steps"] == 2.0
    assert pair["levy_area"] != 0.0


def test_extractor_fail_open_on_insufficient_steps():
    extractor = TemporalSignatureExtractor(min_steps=8)
    out = extractor.extract({"data": _steps("data", 3, 1.7e9, 60.0)})
    assert out["ready"] is False
    assert out["reason"] == "insufficient_domains_or_steps"
    assert len(out["vector"]) == 0


def _write_store(path: Path, domains: list, obs_per_domain: int, span_days: float) -> None:
    """生成满足门槛的轨迹（每域 obs 条，覆盖 span_days 天，断档 < 72h）。"""
    span_sec = span_days * 86400.0
    step = span_sec / max(1, obs_per_domain - 1)
    with path.open("w", encoding="utf-8") as fh:
        for d_idx, domain in enumerate(domains):
            for i in range(obs_per_domain):
                ts = 1_700_000_000.0 + i * step + d_idx  # 域间微偏移，保持单调
                fh.write(
                    json.dumps(
                        {
                            "ts": ts,
                            "agent_domain": domain,
                            "poe_score": 1.0 if i % 3 else 0.0,
                            "cost": {"messages_sent": 1, "latency_ms": 5.0 + i % 7},
                            "cross_domain_refs": 0,
                            "degraded": False,
                        }
                    )
                    + "\n"
                )


def test_gate_not_ready_with_sparse_store(tmp_path):
    store = tmp_path / "t.jsonl"
    _write_store(store, ["data", "eval"], obs_per_domain=20, span_days=0.01)
    report = gate_mod.evaluate_readiness(str(store))
    assert report["ready"] is False
    assert any("coverage_days" in f for f in report["failed"])


def test_gate_ready_and_promotes_s1(tmp_path, monkeypatch):
    store = tmp_path / "t.jsonl"
    # 4 域 × 4 信号 = 16 条连续流；覆盖 181 天；每域断档 ≈ 21.8h < 72h
    _write_store(store, ["data", "eval", "rea", "store-admin"], 200, 181.0)
    report = gate_mod.evaluate_readiness(str(store))
    assert report["ready"] is True
    assert report["continuous_streams"] == 16

    monkeypatch.setattr(gate_mod, "S1_FLAG", tmp_path / "S1_ENABLED")
    state_path = tmp_path / "STATE.json"
    out = gate_mod.maybe_promote(store_path=str(store), state_path=str(state_path), enabled=True)
    assert out["promoted"] is True
    assert out["stage_after"] == "S1_READY"
    assert (tmp_path / "S1_ENABLED").exists()
    assert json.loads(state_path.read_text(encoding="utf-8"))["stage"] == "S1_READY"


def test_gate_s3_requires_ablation_evidence(tmp_path, monkeypatch):
    store = tmp_path / "t.jsonl"
    _write_store(store, ["data", "eval", "rea", "store-admin"], 200, 181.0)
    monkeypatch.setattr(gate_mod, "S1_FLAG", tmp_path / "S1_ENABLED")
    state_path = tmp_path / "STATE.json"
    ablation = tmp_path / "ablation.json"
    gate_mod.maybe_promote(store_path=str(store), state_path=str(state_path), enabled=True)

    out = gate_mod.maybe_promote(
        store_path=str(store),
        ablation_path=str(ablation),
        state_path=str(state_path),
        enabled=True,
    )
    assert out["stage_after"] == "S1_READY"
    assert out["skipped"] == "ablation_not_passed"

    ablation.write_text(json.dumps({"f1_pass": True, "f2_pass": True}), encoding="utf-8")
    out = gate_mod.maybe_promote(
        store_path=str(store),
        ablation_path=str(ablation),
        state_path=str(state_path),
        enabled=True,
    )
    assert out["stage_after"] == "S3_READY"
    assert json.loads(state_path.read_text(encoding="utf-8"))["stage"] == "S3_READY"


def test_gate_switch_off_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_MAIL_AUTO_PROMOTE", raising=False)
    monkeypatch.setattr(gate_mod, "AUTO_PROMOTE_FLAG", tmp_path / "AUTO_PROMOTE")
    out = gate_mod.maybe_promote(store_path=str(tmp_path / "missing.jsonl"))
    assert out["enabled"] is False
    assert out["skipped"] == "auto_promote_disabled"


def test_shadow_attaches_signatures_only_when_enabled(tmp_path):
    def batch(i: int) -> list:
        # 同批同域折叠为 1 步；每批各域 1 条 → 8 批后每域 8 步
        return [
            {
                "ok": True,
                "degraded": False,
                "source": source,
                "meta": {"poe_score": 0.5 + 0.5 * (i % 2), "latency_ms": 5.0 + i},
            }
            for source in ("l0.data.mcp", "l0.eval.mcp")
        ]

    on = AgentMailShadow(
        trajectory_store_path=str(tmp_path / "on.jsonl"), head_infer=False, signature_enabled=True
    )
    for i in range(7):
        result_on = on.observe(batch(i))
        assert "signatures" not in result_on  # 每域仅 7 步，不足 min_steps=8
    result_on = on.observe(batch(7))
    assert result_on["signatures"]["ready"] is True
    assert result_on["signatures"]["dim"] == 2 * 2 * 5 + 2

    off = AgentMailShadow(
        trajectory_store_path=str(tmp_path / "off.jsonl"), head_infer=False, signature_enabled=False
    )
    for i in range(8):
        assert "signatures" not in off.observe(batch(i))
