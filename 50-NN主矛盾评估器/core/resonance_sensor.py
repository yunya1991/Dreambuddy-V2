"""M4-3: 共振传感器（on-demand R/F_macro/t_arrive/regime_overlay）。

SPEC-M3：正向/逆向反射弧的按需计算入口。SLA < 60s（纯本地读 + 算术，毫秒级）。

数据来源：40 侧日更产出物（本模块不联网，拉取刷新由 40 pipeline / 云端负责）：
  - resonance_matrix.json    → R(s) = {corr0, lag_profile, beta, down_corr, granger_p}
  - cycle_state.json         → F_cycle 基础 + regime_overlay
  - sector_transmission.json → 层/资金/情绪分量
  - washout_verdicts.json    → 洗盘反转力
  - cross_asset_matrix.json  → G1 大类龙头跨类 R（缺失时降级，不阻塞）

缓存：TTL 30s + 产出物 mtime 变更即失效（保证 SLA 内不重复读盘）。
fail-open：任一产出物缺失/损坏 → 返回恒等传导快照（corr0=1.0）+ degraded 标注，不抛异常。

用法：
  python3 core/resonance_sensor.py BTC/USDT
  from core.resonance_sensor import ResonanceSensor
  snap = ResonanceSensor().get_snapshot("ETH/USDT")
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# CLI 直接运行时补 50 根路径（包内导入时父目录已在 sys.path）
_50_ROOT = str(Path(__file__).resolve().parents[1])
if _50_ROOT not in sys.path:
    sys.path.insert(0, _50_ROOT)

from core.macro_force import (  # noqa: E402
    compute_cross_class_forces,
    compute_macro_forces,
    normalize_symbol,
)

_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "40-周期神经网络系统"

CACHE_TTL_SEC = 30.0

_ARTIFACTS = {
    "resonance_matrix": "resonance_matrix.json",
    "cycle_state": "cycle_state.json",
    "sector_transmission": "sector_transmission.json",
    "washout_verdicts": "washout_verdicts.json",
    "cross_asset_matrix": "cross_asset_matrix.json",
    "leader_resonance": "leader_resonance.json",
}

_GRANGER_ALPHA = 0.05


@dataclass
class SensorSnapshot:
    """单标的按需快照。"""

    symbol: str
    r: dict[str, Any]  # R(s)：corr0/lag_profile/beta/down_corr/granger_p
    f_macro: dict[str, float]  # {D1, D2, D4, washout}
    t_arrive: float | None
    regime_overlay: str  # trend / range / unknown
    layer: str
    degraded: list[str] = field(default_factory=list)
    cache_age_sec: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "r": self.r,
            "f_macro": self.f_macro,
            "t_arrive": self.t_arrive,
            "regime_overlay": self.regime_overlay,
            "layer": self.layer,
            "degraded": self.degraded,
            "cache_age_sec": round(self.cache_age_sec, 3),
        }


def derive_regime_overlay(cycle_state: dict, sector_transmission: dict | None) -> str:
    """主周期 → 策略类（trend/range）。

    优先 real_cycle.state：hiking/cutting → trend；plateau → range。
    缺失时回退 transmission.state：expanding/contracting → trend；neutral → range。
    """
    rc = (cycle_state or {}).get("real_cycle") or {}
    state = str(rc.get("state", "")).strip().lower()
    if state in ("hiking", "cutting"):
        return "trend"
    if state == "plateau":
        return "range"
    tr = (sector_transmission or {}).get("transmission") or {}
    tstate = str(tr.get("state", "")).strip().lower()
    if tstate in ("expanding", "contracting"):
        return "trend"
    if tstate:
        return "range"
    return "unknown"


def _t_arrive_from_lag(corr0: float, lag_profile: Any, granger_p: Any) -> float | None:
    """lag_profile 中首个 |corr| < 0.5×|corr0| 的偏移日（Granger 显著才计入）。"""
    try:
        p = float(granger_p)
    except (TypeError, ValueError):
        return None
    if p > _GRANGER_ALPHA or corr0 == 0 or not isinstance(lag_profile, list):
        return None
    half = 0.5 * abs(corr0)
    for idx, c in enumerate(lag_profile[1:], start=1):
        try:
            if abs(float(c)) < half:
                return float(idx)
        except (TypeError, ValueError):
            continue
    return None


class ResonanceSensor:
    """按需共振传感器（带 TTL + mtime 缓存，fail-open）。"""

    def __init__(self, data_dir: str | Path | None = None, ttl_sec: float = CACHE_TTL_SEC):
        self.data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
        self.ttl_sec = ttl_sec
        self._cache: dict[str, Any] = {}
        self._cache_ts: float = 0.0
        self._cache_mtimes: dict[str, float] = {}

    # ── 产出物读取 ────────────────────────────────────────────

    def _artifact_path(self, key: str) -> Path:
        return self.data_dir / _ARTIFACTS[key]

    def _mtimes(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for key in _ARTIFACTS:
            try:
                out[key] = os.path.getmtime(self._artifact_path(key))
            except OSError:
                out[key] = -1.0
        return out

    def _load_json(self, key: str) -> dict:
        path = self._artifact_path(key)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _refresh_if_needed(self) -> None:
        now = time.time()
        mtimes = self._mtimes()
        stale = (
            not self._cache or (now - self._cache_ts) > self.ttl_sec or mtimes != self._cache_mtimes
        )
        if not stale:
            return
        self._cache = {key: self._load_json(key) for key in _ARTIFACTS}
        self._cache_ts = now
        self._cache_mtimes = mtimes

    # ── 公开接口 ─────────────────────────────────────────────

    def get_snapshot(self, symbol: str) -> SensorSnapshot:
        """任意标的按需快照。fail-open：异常 → 恒等传导快照。"""
        sym = normalize_symbol(symbol)
        try:
            self._refresh_if_needed()
            cycle_state = self._cache.get("cycle_state") or {}
            resonance = self._cache.get("resonance_matrix") or {}
            sector = self._cache.get("sector_transmission") or {}
            washout = self._cache.get("washout_verdicts") or {}

            forces = compute_macro_forces(cycle_state, resonance, sector, washout)
            cross = self._cache.get("cross_asset_matrix") or {}
            cross_assets = cross.get("assets") or {}
            cross_forces = compute_cross_class_forces(cross, cycle_state)
            mf = forces.get(sym) or cross_forces.get(sym)
            regime_overlay = derive_regime_overlay(cycle_state, sector)

            leader_entry = ((self._cache.get("leader_resonance") or {}).get("assets") or {}).get(
                sym
            )
            if leader_entry:
                # 类内龙头共振优先：R(s) 相对自己的类别龙头，而非 BTC
                corr0 = float(leader_entry.get("corr0") or 1.0)
                degraded = list(mf.degraded) if mf else list(leader_entry.get("degraded") or [])
                return SensorSnapshot(
                    symbol=sym,
                    r={
                        "corr0": corr0,
                        "lag_profile": list(leader_entry.get("lag_profile") or []),
                        "beta": float(leader_entry.get("beta") or 1.0),
                        "down_corr": float(leader_entry.get("down_corr") or 1.0),
                        "granger_p": leader_entry.get("granger_p"),
                    },
                    f_macro=(
                        {
                            "D1": mf.d1_trend,
                            "D2": mf.d2_fund,
                            "D4": mf.d4_sentiment,
                            "washout": mf.washout,
                        }
                        if mf
                        else {"D1": 0.0, "D2": 0.0, "D4": 0.0, "washout": 0.0}
                    ),
                    t_arrive=(
                        mf.t_arrive_days
                        if mf and mf.t_arrive_days is not None
                        else _t_arrive_from_lag(
                            corr0,
                            leader_entry.get("lag_profile"),
                            leader_entry.get("granger_p"),
                        )
                    ),
                    regime_overlay=regime_overlay,
                    layer=mf.layer if mf else str(leader_entry.get("class") or "unknown"),
                    degraded=degraded,
                    cache_age_sec=time.time() - self._cache_ts,
                )

            if mf is None:
                # 既不在加密层清单，也不在跨类矩阵 → 恒等传导 + 审计
                degraded = ["symbol_not_in_layers"]
                if not cross_assets:
                    degraded.append("cross_asset_missing")
                return SensorSnapshot(
                    symbol=sym,
                    r={
                        "corr0": 1.0,
                        "lag_profile": [],
                        "beta": 1.0,
                        "down_corr": 1.0,
                        "granger_p": None,
                    },
                    f_macro={"D1": 0.0, "D2": 0.0, "D4": 0.0, "washout": 0.0},
                    t_arrive=None,
                    regime_overlay=regime_overlay,
                    layer="unknown",
                    degraded=degraded,
                    cache_age_sec=time.time() - self._cache_ts,
                )

            if sym in forces:
                res_assets = resonance.get("assets") or {}
                r = res_assets.get(symbol) or res_assets.get(sym) or {}
                missing_tag = "resonance_missing"
            else:
                r = cross_assets.get(symbol) or cross_assets.get(sym) or {}
                missing_tag = "cross_resonance_missing"
            degraded = list(mf.degraded)
            if not r:
                degraded.append(missing_tag)

            return SensorSnapshot(
                symbol=sym,
                r={
                    "corr0": mf.corr0,
                    "lag_profile": list(r.get("lag_profile") or []),
                    "beta": float(r.get("beta") or 1.0),
                    "down_corr": float(r.get("down_corr") or 1.0),
                    "granger_p": r.get("granger_p"),
                },
                f_macro={
                    "D1": mf.d1_trend,
                    "D2": mf.d2_fund,
                    "D4": mf.d4_sentiment,
                    "washout": mf.washout,
                },
                t_arrive=mf.t_arrive_days,
                regime_overlay=regime_overlay,
                layer=mf.layer,
                degraded=degraded,
                cache_age_sec=time.time() - self._cache_ts,
            )
        except Exception as exc:  # noqa: BLE001
            return SensorSnapshot(
                symbol=sym,
                r={
                    "corr0": 1.0,
                    "lag_profile": [],
                    "beta": 1.0,
                    "down_corr": 1.0,
                    "granger_p": None,
                },
                f_macro={"D1": 0.0, "D2": 0.0, "D4": 0.0, "washout": 0.0},
                t_arrive=None,
                regime_overlay="unknown",
                layer="unknown",
                degraded=[f"sensor_error:{type(exc).__name__}"],
                cache_age_sec=0.0,
            )


def main() -> int:
    import sys

    symbol = sys.argv[1] if len(sys.argv) > 1 else "BTC/USDT"
    snap = ResonanceSensor().get_snapshot(symbol)
    print(json.dumps(snap.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
