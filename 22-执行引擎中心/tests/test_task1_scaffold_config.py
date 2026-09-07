"""RED Phase — Task 1 tests.

Task 1 TRs:
- TR-1.1 (rule): package importable, config constants exist with default values,
    protocol and contracts importable.
- TR-1.2 (rule): tee_core must NOT import V15/易经/三屏 strategy directories
    (verify via static grep on source tree).
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

# ── Project root ────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[3]  # dreambuddy-v2/
MODULE_DIR = PROJECT_ROOT / "22-执行引擎中心"
PACKAGE_DIR = MODULE_DIR / "tee_core"
sys.path.insert(0, str(MODULE_DIR))


# ─────────────────────────────────────────────────────────────────────
# TR-1.1   Imports & default config values
# ─────────────────────────────────────────────────────────────────────
class TestPackageImports:
    def test_import_tee_core_package(self):
        """package `tee_core` must be importable with no syntax errors."""
        import tee_core  # noqa: F401

    def test_import_config(self):
        """tee_core.config exposes all required defaults."""
        from tee_core import config

        # Global switches
        assert hasattr(config, "ENABLE_TEE")
        assert isinstance(config.ENABLE_TEE, bool)
        assert config.ENABLE_TEE is False  # NFR-5 default off (safe rollback)

        assert hasattr(config, "TEE_SHADOW_MODE")
        assert isinstance(config.TEE_SHADOW_MODE, bool)
        assert config.TEE_SHADOW_MODE is True  # Business: shadow by default

        # Slippage gates (Q4 = A: 30/50 bps)
        assert hasattr(config, "DEFAULT_MAX_SLIPPAGE_BPS_NORMAL")
        assert config.DEFAULT_MAX_SLIPPAGE_BPS_NORMAL == 30
        assert hasattr(config, "DEFAULT_MAX_SLIPPAGE_BPS_LIGHT")
        assert config.DEFAULT_MAX_SLIPPAGE_BPS_LIGHT == 50

        # Paths
        assert hasattr(config, "AUDIT_LOG_DIR")
        assert "tee_audit" in str(config.AUDIT_LOG_DIR)
        assert hasattr(config, "FAILOPEN_LOG_PATH")
        assert "tee_failopen" in str(config.FAILOPEN_LOG_PATH)
        assert hasattr(config, "METRICS_JSON_PATH")
        assert "tee_metrics" in str(config.METRICS_JSON_PATH)

        # Router thresholds (Q3 = A conservative: 0.5 / 3 / 10 pct)
        assert hasattr(config, "ROUTER_DIRECT_MAX_PCT")
        assert config.ROUTER_DIRECT_MAX_PCT == pytest.approx(0.005)
        assert hasattr(config, "ROUTER_TWAP15_MAX_PCT")
        assert config.ROUTER_TWAP15_MAX_PCT == pytest.approx(0.03)
        assert hasattr(config, "ROUTER_TWAP60_MAX_PCT")
        assert config.ROUTER_TWAP60_MAX_PCT == pytest.approx(0.10)

        # TWAP & algo defaults
        assert hasattr(config, "TWAP_JITTER_PCT")
        assert config.TWAP_JITTER_PCT == pytest.approx(0.15)
        assert hasattr(config, "TWAP_ESCALATE_SEC")
        assert config.TWAP_ESCALATE_SEC == 20
        assert hasattr(config, "PASSIVE_REHANG_SEC")
        assert config.PASSIVE_REHANG_SEC == 10
        assert hasattr(config, "PASSIVE_TO_TWAP_SEC")
        assert config.PASSIVE_TO_TWAP_SEC == 120
        assert hasattr(config, "KILL_SWITCH_BUFFER_MULT")
        assert config.KILL_SWITCH_BUFFER_MULT == pytest.approx(1.5)

        # Shadow / rollout windows (Q5 = C: 1 + 1 days)
        assert hasattr(config, "ROLLOUT_SHADOW_DAYS")
        assert config.ROLLOUT_SHADOW_DAYS == 1
        assert hasattr(config, "ROLLOUT_GRAYSCALE_DAYS")
        assert config.ROLLOUT_GRAYSCALE_DAYS == 1
        assert hasattr(config, "FAILOPEN_SHADOW_THRESHOLD_PER_DAY")
        assert config.FAILOPEN_SHADOW_THRESHOLD_PER_DAY == 3

        # Fail-open thresholds
        assert hasattr(config, "FAILOPEN_ALERT_WINDOW_SEC")
        assert config.FAILOPEN_ALERT_WINDOW_SEC == 300
        assert hasattr(config, "FAILOPEN_ALERT_COUNT")
        assert config.FAILOPEN_ALERT_COUNT == 3

        # Idempotency
        assert hasattr(config, "IDEMPOTENCY_TTL_SEC")
        assert config.IDEMPOTENCY_TTL_SEC == 120

        # Metrics window
        assert hasattr(config, "METRICS_WINDOW_SEC")
        assert config.METRICS_WINDOW_SEC == 1800

        # Slippage fallback medians (per coin, bps)
        assert hasattr(config, "DEFAULT_SLIPPAGE_MEDIAN_BPS")
        medians = config.DEFAULT_SLIPPAGE_MEDIAN_BPS
        assert isinstance(medians, dict)
        assert medians["BTC"] == 2
        assert medians["ETH"] == 3
        assert medians["SOL"] == 5
        assert medians["AVAX"] == 6
        assert medians["__DEFAULT__"] == 10

        # Default 1min volume fallback (FAIL-OPEN)
        assert hasattr(config, "DEFAULT_1MIN_VOLUME_USDT")
        assert isinstance(config.DEFAULT_1MIN_VOLUME_USDT, dict)
        assert "__DEFAULT__" in config.DEFAULT_1MIN_VOLUME_USDT

    def test_import_protocol(self):
        """ExchangeClient protocol is a runtime_checkable Protocol."""
        import typing
        from tee_core.core.protocol import ExchangeClient  # type: ignore

        assert isinstance(ExchangeClient, type(typing.Protocol))
        # Should be runtime checkable
        assert hasattr(ExchangeClient, "__protocol_attrs__") or getattr(
            ExchangeClient, "_is_protocol", False
        )
        # Must define at least the 5 required methods.
        required = {"get_orderbook", "get_ticker", "place_order",
                    "cancel_order", "get_order", "get_contract_info"}
        protocol_methods = {a for a in dir(ExchangeClient) if not a.startswith("_")}
        for method_name in required:
            assert method_name in protocol_methods, (
                f"ExchangeClient missing required method '{method_name}'"
            )

    def test_import_contracts(self):
        """ParentRequest / ExecutionResult / EstimateResult dataclasses
        exist with required fields."""
        from tee_core.core.contract import (
            ExecutionResult,
            ParentRequest,
            Urgency,
        )

        # ParentRequest: required fields per FR-2.1
        pr_fields = {f.name for f in ParentRequest.__dataclass_fields__.values()}
        for f in ("inst_id", "side", "sz", "pos_side", "td_mode",
                  "leverage", "decision_px", "source"):
            assert f in pr_fields, f"ParentRequest missing field '{f}'"
        # optional fields (presence)
        for f in ("notional_usdt", "algo_override", "algo_params_override",
                  "max_slippage_bps", "urgency"):
            assert f in pr_fields, f"ParentRequest missing optional field '{f}'"

        # Urgency enum LOW / MEDIUM / HIGH
        assert Urgency.LOW.value == "LOW"
        assert Urgency.MEDIUM.value == "MEDIUM"
        assert Urgency.HIGH.value == "HIGH"

        # ExecutionResult: FR-2.1 fields
        er_fields = {f.name for f in ExecutionResult.__dataclass_fields__.values()}
        for f in ("ok", "parent_id", "final_vwap", "final_slippage_bps",
                  "total_filled_sz", "remaining_sz", "duration_ms",
                  "kill_switch_triggered", "fail_open_reason", "child_count"):
            assert f in er_fields, f"ExecutionResult missing field '{f}'"


# ─────────────────────────────────────────────────────────────────────
# TR-1.2   No coupling to V15 / 易经 / 三屏 / 其他 strategy dirs
# ─────────────────────────────────────────────────────────────────────
FORBIDDEN_TOKEN_REFS = [
    ("v15", ["V15", "v15_trader", "v15_paper", "v15_signal"]),
    ("yijing", ["易经", "yijing", "YiJing"]),
    ("three_screen", ["三屏", "三屏系统", "three_screen"]),
]


def _grep_tokens_occurrences(package_dir: Path, tokens):
    """Return number of source lines (in *.py files) containing any token.
    Excludes test directories."""
    hits = []
    for py in package_dir.rglob("*.py"):
        if "test" in str(py).lower():
            continue
        try:
            text = py.read_text(encoding="utf-8")
        except OSError:
            continue
        for idx, line in enumerate(text.splitlines(), start=1):
            for tok in tokens:
                if tok in line:
                    hits.append(f"{py}:{idx}: {line.strip()[:120]}")
    return hits


class TestNoStrategyCoupling:
    @pytest.mark.parametrize("group,tokens", FORBIDDEN_TOKEN_REFS,
                             ids=[g for g, _ in FORBIDDEN_TOKEN_REFS])
    def test_no_strategy_imports(self, group, tokens):
        """tee_core source must not reference V15/易经/三屏 by name."""
        hits = _grep_tokens_occurrences(PACKAGE_DIR, tokens)
        assert hits == [], (
            f"Found forbidden {group} references in tee_core:\n  "
            + "\n  ".join(hits[:20])
        )

    def test_adapters_do_not_import_v15_client_directly(self):
        """adapters/okx_adapter must accept an ExchangeClient-instance via DI,
        NOT hard-import from 14-V15经典马丁策略/lib/okx_client.py.
        This test asserts the module-level import graph is clean."""
        import tee_core.adapters.okx_adapter as okx_adapter  # type: ignore

        import_module = types.ModuleType("okx_adapter_snapshot")
        import_module.__dict__.update(vars(okx_adapter))
        # Scanning globals for path-like strings that leak into strategy dirs
        for name, value in vars(okx_adapter).items():
            if isinstance(value, str):
                assert "V15经典马丁策略" not in value, (
                    f"adapter global '{name}' contains path to V15 dir."
                )
