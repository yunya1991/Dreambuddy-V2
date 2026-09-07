#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
16-调控系统 — 独立进化 Cron Runner（FIX-EV-2）

触发 EnhancedEvolutionLoop 完成完整 7 步进化周期：
  1. 决策记录统计
  2. 结果回填（如能匹配到真实市场数据）
  3. 三层反思（A8 理论校验 / 做梦部潜意识 / 数据驱动调优）
  4. 参数提议生成
  5. 回测验证
  6. Walk-Forward 观察期跟踪
  7. 观察期通过的参数采纳 / 失败的回滚

输出 JSON 报告到 artifacts/evolution_cron/ 目录，并在 stdout 打印
人类可读摘要。全程 FAIL-OPEN：单个策略异常不影响其余策略执行。

============= 用法 =============
# 正常运行：对所有已注册策略跑完整进化周期（含回测）
python 16-调控系统/scripts/evolution_cron_runner.py

# Dry-run：只分析不写回参数，不触发 adopt
python 16-调控系统/scripts/evolution_cron_runner.py --dry-run

# 只跑指定策略
python 16-调控系统/scripts/evolution_cron_runner.py --strategy-id yijing_bcrm --strategy-id v15_martin

# 自定义报告目录
python 16-调控系统/scripts/evolution_cron_runner.py --report-dir /tmp/evo-reports

# 跳过回测（快速查看提议数量，CI中用）
python 16-调控系统/scripts/evolution_cron_runner.py --no-backtest

============= 调度 =============
推荐：launchd（macOS），每日 03:00 独立执行。

--- 8< --- 8< --- plist 内容（保存为 ~/Library/LaunchAgents/com.dreambuddy.evolution-cron.plist）：
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.dreambuddy.evolution-cron</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-lc</string>
    <string>cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2 &amp;&amp; /opt/anaconda3/bin/python 16-调控系统/scripts/evolution_cron_runner.py &gt;&gt; logs/evolution_cron.log 2&gt;&amp;1</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>3</integer>
    <key>Minute</key><integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/logs/evolution_cron_stdout.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/logs/evolution_cron_stderr.log</string>
  <key>WorkingDirectory</key>
  <string>/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2</string>
  <key>RunAtLoad</key>
  <false/>
</dict>
</plist>
--- 8< --- 8< ---  plist 结束 ---

注册/卸载命令：
  launchctl unload ~/Library/LaunchAgents/com.dreambuddy.evolution-cron.plist 2>/dev/null
  launchctl load   ~/Library/LaunchAgents/com.dreambuddy.evolution-cron.plist
  launchctl start  com.dreambuddy.evolution-cron   # 立即手动触发一次

Linux/cron 等价：
  0 3 * * * cd /path/to/dreambuddy-v2 &amp;&amp; python 16-调控系统/scripts/evolution_cron_runner.py &gt;&gt; logs/evolution_cron.log 2&gt;&amp;1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# === 路径设置（和 phase3_exit_evaluator.py 一致）===
MODULE_DIR = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = MODULE_DIR / "artifacts" / "evolution_cron"
CORE_DIR = MODULE_DIR / "core"
PROJECT_ROOT = MODULE_DIR.parent

if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

# 默认 report-dir = 16-调控系统/artifacts/evolution_cron/
DEFAULT_REPORT_DIR = ARTIFACTS_DIR

# 样本门槛：少于该值跳过数据驱动提议，避免小样本过拟合
DEFAULT_MIN_SAMPLES = 5


def _load_evolution_or_none():
    """懒加载 EnhancedEvolutionLoop。FAIL-OPEN：返回 None 不阻塞流程。"""
    try:
        from enhanced_evolution import get_enhanced_evolution
        return get_enhanced_evolution()
    except Exception as e:
        print(f"[WARN] 无法加载 EnhancedEvolutionLoop: {e}", file=sys.stderr)
        return None


def _build_report_filename() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"evolution_report_{ts}.json"


def _print_human_summary(report: Dict[str, Any], dry_run: bool) -> None:
    """在 stdout 打印人类可读摘要（10行内）。"""
    banner = "==== 16-调控系统 Evolution Cron REPORT" + (" [DRY-RUN]" if dry_run else "") + " ===="
    print(banner)
    print(f"  时间(UTC)       : {report.get('timestamp','N/A')}")
    print(f"  策略总数        : {report.get('strategy_count', 0)}")
    layers = report.get("layers_run") or []
    print(f"  已执行层        : {', '.join(layers) if layers else '(none)'}")
    print(f"  提议生成数      : {report.get('proposals_generated', 0)}")
    print(f"  回测通过提议数  : {report.get('proposals_backtested', 0)}")
    print(f"  采纳提议数      : {report.get('proposals_adopted', 0)}")
    per = report.get("per_strategy") or {}
    if per:
        print(f"  每策略提议数    :", end="")
        tokens = [f"{sid}={d.get('proposals_generated', '?')}"
                  if isinstance(d, dict) else f"{sid}=?"
                  for sid, d in list(per.items())[:5]]
        print(" " + ", ".join(tokens) + (" …" if len(per) > 5 else ""))
    errors = report.get("errors") or []
    print(f"  错误数          : {len(errors)}")
    if errors:
        for e in errors[:3]:
            print(f"    - {e}")
        if len(errors) > 3:
            print(f"    …省略其余 {len(errors) - 3} 条错误，详见 JSON 报告")
    print("=" * len(banner))
    print(f"[INFO] 完整 JSON 报告: {report.get('report_path', '(未写入)')}")


def _run(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=("16-调控系统进化Cron Runner：独立触发 EnhancedEvolutionLoop，"
                     "生成进化提议、回测、采纳，并产出JSON报告。"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="仅分析不写回参数（不触发 adopt 持久化），适合首次跑或开发调试。",
    )
    parser.add_argument(
        "--strategy-id", action="append", dest="strategy_ids", default=[],
        help="只对指定 strategy_id 执行进化，可多次传递；不传则遍历所有已注册策略。",
    )
    parser.add_argument(
        "--report-dir", type=Path, default=DEFAULT_REPORT_DIR,
        help=f"报告输出目录，默认 {DEFAULT_REPORT_DIR}",
    )
    parser.add_argument(
        "--no-backtest", action="store_true",
        help="跳过回测步骤（只生成提议，不验证/采纳）。",
    )
    parser.add_argument(
        "--min-samples", type=int, default=DEFAULT_MIN_SAMPLES,
        help=f"数据驱动调优的最小决策样本门槛，默认 {DEFAULT_MIN_SAMPLES}。",
    )
    parser.add_argument(
        "--no-report-file", action="store_true",
        help="仅 stdout 打印摘要，不写 JSON 报告文件。",
    )
    parser.add_argument(
        "--no-artifacts", action="store_true",
        help="兼容旧版别名：等价于 --no-report-file（用于最小测试）。",
    )

    args = parser.parse_args(argv)

    # 兼容别名
    if args.no_artifacts:
        args.no_report_file = True

    dry_run: bool = args.dry_run
    run_backtest: bool = not args.no_backtest
    report_dir: Path = args.report_dir
    strategy_ids: List[str] = list(dict.fromkeys(args.strategy_ids))  # 去重保序
    write_report: bool = not args.no_report_file

    errors: List[str] = []
    report: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "run_backtest": run_backtest,
        "strategy_count": 0,
        "layers_run": [],
        "proposals_generated": 0,
        "proposals_backtested": 0,
        "proposals_adopted": 0,
        "per_strategy": {},
        "errors": errors,
        "exit_code": 0,
    }

    evo = _load_evolution_or_none()
    if evo is None:
        errors.append("EnhancedEvolutionLoop 加载失败，已降级为安全退出（FAIL-OPEN）。")
        report["exit_code"] = 2
    else:
        # 1. 策略收集
        if strategy_ids:
            explicit_ids = strategy_ids
        else:
            # 进化引擎默认策略 + params 中已有记录的策略（并集）
            explicit_ids = list(getattr(evo, "params", {}).keys()) or [
                "v15_martin", "screen_trend", "yijing_bcrm",
                "agent_a", "agent_b", "agent_c",
            ]
        # 过滤空值
        explicit_ids = [s for s in explicit_ids if s]
        report["strategy_count"] = len(explicit_ids)

        # 2. 遍历执行（单策略 FAIL-OPEN：一个异常不影响其他策略）
        cycle_errors_before = len(errors)

        # dry-run 时，不写回任何持久化变更：
        #   简单起见，先备份原 params/history/pool，结束后还原
        backup_params = backup_history = backup_pool = None
        if dry_run:
            try:
                backup_params = json.loads(json.dumps(evo.params, ensure_ascii=False, default=str))
                backup_history = json.loads(json.dumps(evo.history, ensure_ascii=False, default=str))
                backup_pool = json.loads(json.dumps(evo.pool, ensure_ascii=False, default=str))
            except Exception as e:
                errors.append(f"[DRY-RUN] 无法备份进化状态（仍将继续，但结果可能写回）: {e}")

        try:
            cycle_report = evo.run_full_evolution_cycle(
                strategy_ids=explicit_ids or None,
                min_samples=args.min_samples,
                run_backtest=run_backtest,
            )
            # 合并 cycle_report 结果到报告
            for k in ("layers_run", "proposals_generated",
                      "proposals_backtested", "proposals_adopted",
                      "per_strategy"):
                if k in cycle_report:
                    report[k] = cycle_report[k]
            # per_strategy 里补齐 proposals_generated 汇总（用于摘要）
            per = report.get("per_strategy") or {}
            for sid, d in per.items():
                if isinstance(d, dict):
                    a8p = (d.get("a8_inspection") or {}).get("proposals", 0)
                    drp = (d.get("dream_analysis") or {}).get("proposals", 0)
                    ddp = (d.get("data_driven") or {}).get("proposals", 0)
                    try:
                        d["proposals_generated"] = int(a8p) + int(drp) + int(ddp)
                    except (TypeError, ValueError):
                        d["proposals_generated"] = 0
        except Exception as e:
            tb = traceback.format_exc(limit=3).strip().replace("\n", " | ")
            errors.append(f"run_full_evolution_cycle 异常: {e} ({tb})")
        finally:
            if dry_run and (backup_params is not None
                            and backup_history is not None
                            and backup_pool is not None):
                # 还原状态（尽力而为；即便失败也不抛出）
                try:
                    evo.params = backup_params
                    evo.history = backup_history
                    evo.pool = backup_pool
                except Exception as e_r:
                    errors.append(f"[DRY-RUN] 状态还原失败: {e_r}")

        if len(errors) > cycle_errors_before and report["strategy_count"] == 0:
            # 所有策略都失败时标记 exit_code=1（部分失败仍=0，有报告可看）
            report["exit_code"] = 1

    # 3. 写 JSON 报告
    report_path: Optional[str] = None
    if write_report:
        try:
            report_dir = Path(report_dir)
            report_dir.mkdir(parents=True, exist_ok=True)
            full = report_dir / _build_report_filename()
            report["report_path"] = str(full)
            with open(full, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2, default=str)
            report_path = str(full)
        except Exception as e:
            errors.append(f"写报告失败: {e}")

    # 摘要打印
    _print_human_summary(report, dry_run=dry_run)

    exit_code = int(report.get("exit_code", 0))
    # 部分成功（有1个以上策略运行完毕，即使有错误）也 exit=0，避免触发 cron 假告警
    if exit_code == 1 and report.get("proposals_generated", 0) > 0:
        exit_code = 0
    return exit_code


def main(argv: Optional[List[str]] = None) -> int:
    """入口：捕获顶层异常并安全退出（cron任务禁止未捕获异常导致launchd标记崩溃）。"""
    try:
        return _run(argv)
    except KeyboardInterrupt:
        print("[ABORT] 用户中断 Evolution Cron", file=sys.stderr)
        return 130
    except Exception as e:
        tb = traceback.format_exc(limit=5).strip()
        print(f"[FATAL] Evolution Cron 顶层异常（已FAIL-OPEN）: {e}\n{tb}",
              file=sys.stderr)
        # 即使顶层异常也写一份最小 JSON（若可写）
        try:
            rd = Path(os.environ.get("EVOLUTION_REPORT_DIR") or DEFAULT_REPORT_DIR)
            rd.mkdir(parents=True, exist_ok=True)
            crash = rd / f"crash_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
            with open(crash, "w", encoding="utf-8") as f:
                json.dump({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "fatal_error": str(e),
                    "traceback": tb,
                }, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        return 2


if __name__ == "__main__":
    sys.exit(main())
