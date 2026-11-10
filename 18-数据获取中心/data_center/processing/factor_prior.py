"""因子先验适配器 — SPEC §2.10 A1 / §2.9.4。

把 P3-c1 的 `factor_sensitivity.jsonl` 转成 40 周期神经网络可选的
`factor_prior.json` 特征块。**只读、不改 40 内核**：

  build_factor_prior()  # 18 侧写入
  load_factor_prior()   # 40 侧读取（40 已把 18 加入 sys.path）

契约：
  - 只放 eligible=True 且 n≥MIN_N 的因子
  - sens_f 带方向（正 = 该因子利多价格反应）
  - 版本不符 / 文件缺失 / 内容损坏 / as_of 晚于当前 → load 返回 None，
    40 退回原特征（fail-open），不得抛异常

FAIL-OPEN：任何异常都返回 degraded 空块或 None，不阻断主链路。
"""

from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("data_center.processing.factor_prior")

_REPO = Path(__file__).resolve().parents[3]
DEFAULT_SENSITIVITY = _REPO / "18-数据获取中心" / "backfill" / "p3c1" / "factor_sensitivity.jsonl"
DEFAULT_OUT = _REPO / "18-数据获取中心" / "backfill" / "p3c1" / "factor_prior.json"

PRIOR_VERSION = "factor-prior-v1"
MIN_N = 30

# 快讯因子先验默认关闭：P3-c1（日线）+ P3-c1h（1h）双证——
# 9 族强度对收益的增量解释力只有 0.03%~0.11%，HAC 后族/维全不显著。
# 需要重开时显式设置 DREAM_ENABLE_NEWSFLASH_PRIOR=1（并在 SPEC 记录理由）。
ENV_SWITCH = "DREAM_ENABLE_NEWSFLASH_PRIOR"


def newsflash_prior_enabled() -> bool:
    """快讯因子先验是否启用（默认 False）。"""
    return os.environ.get(ENV_SWITCH, "0").strip() in ("1", "true", "True", "yes")


def _signed_sens(row: dict) -> float | None:
    """行 → 带符号 sens_f；非法 → None。优先用已算好的 sens_f。"""
    try:
        raw = row.get("sens_f")
        if raw is not None and math.isfinite(float(raw)):
            return float(raw)
        d = int(row.get("direction") or 0)
        if d == 0:
            return None
        pre = abs(float(row.get("mean_excess_pre") or 0.0))
        post = abs(float(row.get("mean_excess_post") or 0.0))
        return (pre + post) / 2.0 * d
    except (TypeError, ValueError):
        return None


def _dim_of(factor_id: str) -> str:
    try:
        from data_center.processing.dimension_context import DIMENSION_MAP

        return DIMENSION_MAP.get(factor_id.split(".")[0], "?")
    except Exception:  # noqa: BLE003  FAIL-OPEN
        return "?"


def build_factor_prior(
    *,
    sensitivity_path: Any = None,
    out_path: Any = None,
    min_n: int = MIN_N,
    eligible_only: bool = True,
    as_of: Any = None,
    enabled: bool | None = None,
) -> dict:
    """读 `factor_sensitivity.jsonl` → 写 `factor_prior.json`。返回产物 dict。

    `enabled` 为 None 时读环境开关（默认关闭）。关闭时直接产出 degraded 空块，
    不读源文件、不影响主链路。
    """
    src = Path(sensitivity_path or DEFAULT_SENSITIVITY)
    out = Path(out_path or DEFAULT_OUT)
    result: dict[str, Any] = {
        "version": PRIOR_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": str(as_of)[:10] if as_of else None,
        "source": str(src),
        "degraded": False,
        "n_factors": 0,
        "dims": {},
        "factors": [],
    }
    try:
        if not (newsflash_prior_enabled() if enabled is None else enabled):
            result["degraded"] = True
            result["reason"] = "newsflash_prior_disabled_by_default"
            _write(out, result)
            return result

        if not src.exists():
            result["degraded"] = True
            result["reason"] = "sensitivity_missing"
            _write(out, result)
            return result

        factors: list[dict] = []
        max_as_of = ""
        with src.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                raw_ids = row.get("factor_id")
                fids = (
                    [str(raw_ids)] if raw_ids else [str(x) for x in (row.get("factor_ids") or [])]
                )
                fids = [x.strip() for x in fids if str(x).strip()]
                if not fids:
                    continue
                n = int(row.get("n") or row.get("n_events") or 0)
                if n < min_n:
                    continue
                if eligible_only and row.get("eligible") is not True:
                    continue
                sens = _signed_sens(row)
                if sens is None:
                    continue
                gran = "factor" if raw_ids else "dim"
                for fid in fids:
                    factors.append(
                        {
                            "factor_id": fid,
                            "sens_f": round(sens, 6),
                            "n": n,
                            "p_value": row.get("p_value"),
                            "verdict": row.get("verdict"),
                            "event_family": row.get("event_family"),
                            "granularity": gran,
                        }
                    )
                d = str(row.get("as_of") or "")[:10]
                if d > max_as_of:
                    max_as_of = d

        factors.sort(key=lambda x: abs(x["sens_f"]), reverse=True)
        dims: dict[str, float] = {}
        for x in factors:
            dim = _dim_of(x["factor_id"])
            dims[dim] = round(dims.get(dim, 0.0) + abs(x["sens_f"]), 6)

        result.update(
            factors=factors,
            n_factors=len(factors),
            dims=dims,
            as_of=result["as_of"] or (max_as_of or None),
            degraded=not factors,
        )
        if not factors:
            result["reason"] = "no_eligible_factors"
        _write(out, result)
        return result
    except Exception as e:  # noqa: BLE003  FAIL-OPEN
        logger.warning("[FAIL-OPEN] build_factor_prior %s: %s", type(e).__name__, str(e)[:120])
        result.update(degraded=True, reason=f"error:{type(e).__name__}", factors=[], n_factors=0)
        return result


def _write(path: Path, payload: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:  # FAIL-OPEN：写失败不影响主链路
        logger.warning("[FAIL-OPEN] write factor_prior %s: %s", type(e).__name__, str(e)[:120])


def load_factor_prior(path: Any = None, as_of: Any = None) -> dict | None:
    """40 侧可选块读取。缺失 / 损坏 / 版本不符 / 空块 / 未来先验 → None。"""
    try:
        p = Path(path or DEFAULT_OUT)
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != PRIOR_VERSION:
            return None
        if data.get("degraded") or not data.get("factors"):
            return None
        prior_as_of = str(data.get("as_of") or "")[:10]
        if as_of and prior_as_of and prior_as_of > str(as_of)[:10]:
            return None
        return data
    except Exception as e:  # noqa: BLE003  FAIL-OPEN
        logger.warning("[FAIL-OPEN] load_factor_prior %s: %s", type(e).__name__, str(e)[:120])
        return None
