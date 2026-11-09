#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""42 层总线运行入口（C 阶段小步启用）。

默认白名单只跑不依赖上游快照的两个源：
- 40-cycle（cycle_state.json，宏观周期约束）
- 29-event（29 事件驱动状态）

其余 6 个源（43/23/11-bcrm/11-bdsm/11-washout/11-event-arbitrage）
当前因源快照缺失或 stale 走 fail-open，待上游数据恢复后再逐步加入白名单。

行为：
- 强制开启 SIGNAL_BUS_PERSIST=1 + SIGNAL_BUS_METRICS=1（可观测、可累积）
- 逐个执行白名单源的 publisher 适配器（fail-open：单源异常不影响其余）
- 结束兜底 flush 一次，保证 bus_state.json 与 metrics.json 必然产出

用法：python3 run_bus.py [--dry-run]
"""

import argparse
import importlib
import json
import os
import sys
import traceback

_42_ROOT = os.path.dirname(os.path.abspath(__file__))
_ADAPTERS_DIR = os.path.join(_42_ROOT, "adapters")
_DEFAULT_REGISTRY = os.path.join(_42_ROOT, "registry.yaml")

if _42_ROOT not in sys.path:
    sys.path.insert(0, _42_ROOT)
if _ADAPTERS_DIR not in sys.path:
    sys.path.insert(0, _ADAPTERS_DIR)

# R0-03 白名单扩展（2026-11-08）：加入数据已验证新鲜的 4 源，共 6 源。
# F1（SPEC-M1 M1）：43 canonical source 更名 strategic_extension → 43-strategic；
# SOURCE_ALIAS_MODE=1 时双写过渡，50 侧别名表兼容两旧名。
DEFAULT_WHITELIST = (
    "40-cycle",
    "40-divergence",
    "29-event",
    "43-strategic",
    "23-contradiction",
    "11-bcrm",
    "11-bdsm",
    "11-bcrm-tactical",
    "11-washout",
    "11-event-arbitrage",
)

# M3-1：bus_history 归档上限（滚动覆盖，原子写）
BUS_HISTORY_CAP = 500
_BUS_HISTORY_PATH = os.path.join(_42_ROOT, "runtime", "bus_history.jsonl")


def _append_bus_history(snapshot: dict, cap: int = BUS_HISTORY_CAP) -> None:
    """将一次 bus snapshot 追加到 bus_history.jsonl（滚动上限 cap，原子写）。

    M3-1：为 pit_replay 提供回放数据底座。
    fail-open：任何 IO 异常静默忽略，不影响主流程。
    """
    try:
        os.makedirs(os.path.dirname(_BUS_HISTORY_PATH), exist_ok=True)
        existing: list[str] = []
        if os.path.exists(_BUS_HISTORY_PATH):
            with open(_BUS_HISTORY_PATH, encoding="utf-8") as f:
                existing = f.read().splitlines()
        # 滚动截断：保留最新 cap-1 条 + 新 1 条
        if len(existing) >= cap:
            existing = existing[-(cap - 1) :]
        line = json.dumps(snapshot, ensure_ascii=False)
        existing.append(line)
        tmp = _BUS_HISTORY_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(existing) + "\n")
        os.replace(tmp, _BUS_HISTORY_PATH)
    except Exception:  # noqa: BLE001
        pass


def select_subsystems(registry_path: str = None, whitelist=DEFAULT_WHITELIST) -> list:
    """从 registry 读取 enabled 且 name 在白名单内的子系统（保序、fail-open）。"""
    import yaml

    try:
        with open(registry_path or _DEFAULT_REGISTRY, encoding="utf-8") as f:
            reg = yaml.safe_load(f)
    except Exception:  # noqa: BLE001
        return []

    allowed = set(whitelist)
    subs = []
    for sub in (reg or {}).get("subsystems") or []:
        if not isinstance(sub, dict):
            continue
        if not sub.get("enabled", True):
            continue
        if sub.get("name") not in allowed:
            continue
        subs.append(
            {
                "name": sub.get("name"),
                "publisher": sub.get("publisher"),
                "horizon": sub.get("horizon"),
            }
        )
    # 按白名单顺序返回，保证执行顺序稳定
    order = {name: i for i, name in enumerate(whitelist)}
    return sorted(subs, key=lambda s: order.get(s["name"], 999))


def _default_runner(sub: dict) -> int:
    """执行单个适配器：import 模块并调用 main()（fail-open 由 run 捕获）。"""
    module_name = os.path.splitext(os.path.basename(sub["publisher"]))[0]
    module = importlib.import_module(module_name)
    try:
        return module.main()
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 0


def run(
    whitelist=DEFAULT_WHITELIST,
    registry_path: str = None,
    runner=None,
    flush: bool = True,
    bus_state_path: str = None,
    metrics_path: str = None,
) -> dict:
    """按白名单执行适配器并兜底 flush 总线状态与指标。"""
    os.environ.setdefault("SIGNAL_BUS_PERSIST", "1")
    os.environ.setdefault("SIGNAL_BUS_METRICS", "1")

    subs = select_subsystems(registry_path, whitelist)
    runner = runner or _default_runner
    executed, errors = [], []

    for sub in subs:
        try:
            rc = runner(sub)
            executed.append(sub["name"])
            if rc not in (0, None):
                errors.append({"name": sub["name"], "exit": rc})
                try:
                    from degraded_events import record_degraded_event

                    record_degraded_event(
                        "42",
                        sub["name"],
                        "adapter_error",
                        f"exit_code={rc}",
                    )
                except Exception:  # noqa: BLE001
                    pass
        except Exception as exc:  # noqa: BLE001  fail-open：单源异常不阻断
            errors.append({"name": sub["name"], "error": "{}: {}".format(type(exc).__name__, exc)})
            traceback.print_exc()
            try:
                from degraded_events import record_degraded_event

                record_degraded_event(
                    "42",
                    sub["name"],
                    "adapter_error",
                    f"{type(exc).__name__}: {exc}",
                )
            except Exception:  # noqa: BLE001
                pass

    if flush:
        from signal_bus import SignalBus

        bus = SignalBus(state_path=bus_state_path) if bus_state_path else SignalBus()
        state = bus.flush(metrics_path=metrics_path)
        # M3-1：归档 bus snapshot 到 bus_history.jsonl（回放底座）
        _append_bus_history(state)

    return {
        "status": "degraded" if errors else "ok",
        "executed": executed,
        "errors": errors,
        "whitelist": list(whitelist),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="42 总线运行入口（C 阶段）")
    parser.add_argument("--dry-run", action="store_true", help="只列出将执行的源，不执行")
    parser.add_argument(
        "--sources",
        default=",".join(DEFAULT_WHITELIST),
        help="逗号分隔的白名单源名（默认 40-cycle,29-event）",
    )
    args = parser.parse_args()

    whitelist = tuple(s.strip() for s in args.sources.split(",") if s.strip())
    if args.dry_run:
        subs = select_subsystems(whitelist=whitelist)
        print(
            json.dumps(
                {"whitelist": list(whitelist), "will_run": subs}, ensure_ascii=False, indent=2
            )
        )
        return 0

    result = run(whitelist=whitelist)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
