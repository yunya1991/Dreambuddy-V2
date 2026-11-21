"""A/B 验证：复用 platform/bench/routing/run_bench.py，不重写指标。

只负责编排与判定：
    - dry-run 直接校验夹具；
    - 真实运行按 repeats 复跑，计算均值与 2σ 噪声带；
    - 基线覆盖命中 ≥ 90% 时提示 headroom 不足，建议改用 name-only 或加难例。
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path
from typing import Dict, List

from .loaders import MODULE_ROOT

BENCH_PATH = MODULE_ROOT / "platform" / "bench" / "routing" / "run_bench.py"
HEADROOM_THRESHOLD = 0.9
NOISE_SIGMA_MS = 2.2


def _load_bench():
    spec = importlib.util.spec_from_file_location("optimizer_run_bench", str(BENCH_PATH))
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载基准：{}".format(BENCH_PATH))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bench_argv(
    ids: str,
    catalog_fields: str,
    name_style: str,
    model: str,
    retries: int,
    output: Path,
    dry_run: bool,
) -> List[str]:
    argv = ["--catalog-fields", catalog_fields, "--name-style", name_style]
    if ids:
        argv.extend(["--ids", ids])
    if model:
        argv.extend(["--model", model])
    if retries:
        argv.extend(["--retries", str(retries)])
    if dry_run:
        argv.append("--dry-run")
    else:
        argv.extend(["--router", "qwen", "--json", str(output)])
    return argv


def run_ab(
    ids: str = "",
    catalog_fields: str = "full",
    name_style: str = "current",
    model: str = "",
    repeats: int = 2,
    retries: int = 1,
    dry_run: bool = False,
) -> Dict[str, object]:
    bench = _load_bench()
    runs: List[Dict[str, object]] = []
    codes: List[int] = []
    if dry_run:
        output = Path(tempfile.gettempdir()) / "optimizer-ab-dry-run.json"
        code = bench.main(
            _bench_argv(ids, catalog_fields, name_style, model, retries, output, True)
        )
        return {
            "mode": "dry-run",
            "exit_code": code,
            "repeats": 0,
            "runs": [],
            "verdict": "fixtures-ok" if code == 0 else "fixtures-failed",
        }

    for index in range(max(1, repeats)):
        output = Path(tempfile.gettempdir()) / "optimizer-ab-{}.json".format(index + 1)
        code = bench.main(
            _bench_argv(ids, catalog_fields, name_style, model, retries, output, False)
        )
        codes.append(code)
        if code != 0 or not output.exists():
            return {
                "mode": "live",
                "exit_code": 2,
                "repeats": repeats,
                "runs": runs,
                "verdict": "env-error",
                "detail": "第 {} 轮基准失败（exit={}），按环境问题处理，不判退化".format(
                    index + 1, code
                ),
            }
        runs.append(json.loads(output.read_text(encoding="utf-8")))

    metrics = [run.get("metrics") or {} for run in runs]
    averaged = {
        key: round(sum(float(item.get(key, 0)) for item in metrics) / len(metrics), 4)
        for key in (
            "coverage_hit_rate",
            "ours_selection_rate",
            "false_positive_rate",
            "avg_latency_ms",
        )
    }
    latency_values = [float(item.get("avg_latency_ms", 0)) for item in metrics]
    spread = max(latency_values) - min(latency_values) if latency_values else 0.0
    headroom_ok = averaged["coverage_hit_rate"] < HEADROOM_THRESHOLD
    return {
        "mode": "live",
        "exit_code": 0,
        "repeats": repeats,
        "runs": len(runs),
        "averaged": averaged,
        "latency_spread_ms": round(spread, 1),
        "noise_band_ms": round(2 * NOISE_SIGMA_MS, 1),
        "headroom_ok": headroom_ok,
        "headroom_hint": (
            "" if headroom_ok else "基线覆盖命中 ≥ 90%，改用 --catalog-fields name 或补难例后再测"
        ),
        "verdict": "ok",
    }
