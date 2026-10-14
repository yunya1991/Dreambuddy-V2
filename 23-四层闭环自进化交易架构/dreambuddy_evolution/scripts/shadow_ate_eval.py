"""Shadow ATE 评估子进程入口（隔离 DML）.

用法: python -m dreambuddy_evolution.scripts.shadow_ate_eval --switch <name>
"""
from __future__ import annotations

import sys
from pathlib import Path

# 直接以脚本路径运行时，把模块根与仓库根加入 sys.path（支持 `python <script>`）
for _p in (Path(__file__).resolve().parents[2], Path(__file__).resolve().parents[3]):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--switch", required=True)
    args = parser.parse_args(argv)

    from dreambuddy_evolution.core.shadow_activation_gate import ShadowActivationGate
    from dreambuddy_evolution.core.shadow_ate_evaluator import evaluate_and_record

    gate = ShadowActivationGate(args.switch)
    obs = evaluate_and_record(gate, args.switch)
    return 0 if obs else 1


if __name__ == "__main__":
    raise SystemExit(main())
