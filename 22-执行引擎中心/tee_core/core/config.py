"""TEE global configuration constants.

All values are driven by the user-approved SPEC Q3/Q4/Q5 hard constraints.
Do not alter defaults casually — each has a matching memory record in the
cognitive memory system.
"""
from __future__ import annotations

from pathlib import Path

# ── Resolve paths relative to dreambuddy-v2 project root ─────────────
# config.py lives at: 22-执行引擎中心/tee_core/core/config.py
# (4 levels up = project root / dreambuddy-v2)
PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]
LOGS_ROOT: Path = PROJECT_ROOT / "logs"
LOGS_ROOT.mkdir(parents=True, exist_ok=True)

# ── Global safety switches (NFR-5 + Business rollout) ───────────────
# Defaults are FAIL-SAFE: TEE disabled, shadow mode enabled.
ENABLE_TEE: bool = False
TEE_SHADOW_MODE: bool = True

# ── Slippage kill-switch defaults (Q4 = A) ──────────────────────────
# Regular position: 30 bps = 0.30% (approx 1/50th of 1.5% SL floor)
# Light / trial position: 50 bps = 0.50%
DEFAULT_MAX_SLIPPAGE_BPS_NORMAL: int = 30
DEFAULT_MAX_SLIPPAGE_BPS_LIGHT: int = 50

# Runtime kill-switch = max × buffer (prevents flapping)
KILL_SWITCH_BUFFER_MULT: float = 1.5

# ── Router thresholds (Q3 = A, conservative) ────────────────────────
# size_ratio = order_notional_usdt / avg_1min_volume_usdt
#   < 0.5%                      → DIRECT market (no split)
#   0.5% – 3%                   → SmartTWAP 15 min
#   3%  – 10%                   → SmartTWAP 60 min
#   > 10%                       → SmartPassive (fallback to SmartTWAP)
ROUTER_DIRECT_MAX_PCT: float = 0.005      # 0.5 %
ROUTER_TWAP15_MAX_PCT: float = 0.03       # 3 %
ROUTER_TWAP60_MAX_PCT: float = 0.10       # 10 %

# TWAP parameter defaults
TWAP_NUM_SLICES_TWAP15: int = 12
TWAP_NUM_SLICES_TWAP60: int = 30
TWAP_JITTER_PCT: float = 0.15            # ±15 % on child sizes
TWAP_ESCALATE_SEC: int = 20              # first widen after 20 s
TWAP_ESCALATE_STEP_BPS: int = 2          # +2 bps each escalation
TWAP_ESCALATE_MAX_BPS: int = 10          # stop widening after 10 bps
TWAP_TIMEOUT_TO_MARKET_SEC: int = 60     # after 60 s → market/last-price close

# Passive parameter defaults
PASSIVE_REHANG_SEC: int = 10             # refresh to top-of-book every 10s
PASSIVE_TO_TWAP_SEC: int = 120           # 2 min progress gate
PASSIVE_TO_TWAP_FILL_RATIO: float = 0.5  # need ≥50% filled by 2 min

# ── Rollout cadence (Q5 = C fast): 1 shadow + 1 grayscale → full ────
ROLLOUT_SHADOW_DAYS: int = 1
ROLLOUT_GRAYSCALE_DAYS: int = 1
FAILOPEN_SHADOW_THRESHOLD_PER_DAY: int = 3  # pause grayscale if exceeded

# ── Fail-open alerting ──────────────────────────────────────────────
FAILOPEN_ALERT_WINDOW_SEC: int = 300   # 5 min sliding window
FAILOPEN_ALERT_COUNT: int = 3          # 3 occurrences → Lark alert

# ── Idempotency ─────────────────────────────────────────────────────
IDEMPOTENCY_TTL_SEC: int = 120          # 2 min (covers 1-min bucket + jitter)

# ── Rolling metrics window ──────────────────────────────────────────
METRICS_WINDOW_SEC: int = 1800          # 30 min
METRICS_FLUSH_INTERVAL_SEC: int = 60    # flush to disk every 1 min

# ── Paths for logs / audit ──────────────────────────────────────────
AUDIT_LOG_DIR: Path = LOGS_ROOT / "tee_audit"
AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)
FAILOPEN_LOG_PATH: Path = LOGS_ROOT / "tee_failopen.log"
METRICS_JSON_PATH: Path = LOGS_ROOT / "tee_metrics.json"

# ── FAIL-OPEN fallback lookups ──────────────────────────────────────
# When orderbook endpoint is unreachable we estimate slippage from
# per-asset historical medians (bps). Values from literature + OKX
# typical 2025 market depth observation.
DEFAULT_SLIPPAGE_MEDIAN_BPS: dict[str, int] = {
    "BTC": 2,
    "ETH": 3,
    "SOL": 5,
    "AVAX": 6,
    "LINK": 7,
    "ARB": 8,
    "OP": 8,
    "ADA": 7,
    "DOT": 7,
    "DOGE": 6,
    "__DEFAULT__": 10,
}

# FAIL-OPEN when 1-min volume endpoint is unavailable (USDT notional).
# BTC-level baseline per minute for unknown coins = conservative 100k USDT.
DEFAULT_1MIN_VOLUME_USDT: dict[str, float] = {
    "BTC": 5_000_000.0,
    "ETH": 2_500_000.0,
    "SOL": 800_000.0,
    "AVAX": 300_000.0,
    "__DEFAULT__": 100_000.0,
}
