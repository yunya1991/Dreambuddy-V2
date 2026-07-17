"""三屏趋势系统 — 验证报告生成器

生成策略对比报告，可视化绩效差异。
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
import pandas as pd


class ValidationReport:
    """验证报告生成器"""

    def __init__(self, data_dir: Optional[str] = None):
        """
        参数:
            data_dir: 数据目录
        """
        self.data_dir = Path(data_dir) if data_dir else Path(__file__).parent / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def load_trading_logs(self) -> List[Dict]:
        """加载所有交易日志"""
        logs = []
        for f in self.data_dir.glob("trading_log_*.json"):
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    log = json.load(fp)
                    log["filepath"] = str(f)
                    logs.append(log)
            except Exception as e:
                print(f"  [WARN] 加载失败 {f}: {e}")

        # 按时间排序
        logs.sort(key=lambda x: x.get("timestamp", ""))
        return logs

    def generate_report(self) -> Dict[str, Any]:
        """生成验证报告"""
        logs = self.load_trading_logs()

        if not logs:
            return {"error": "无交易日志数据"}

        # 汇总各策略表现
        strategies = {}
        for log in logs:
            for name, data in log.get("strategies", {}).items():
                if name not in strategies:
                    strategies[name] = {
                        "name": name,
                        "returns": [],
                        "timestamps": [],
                        "order_counts": [],
                        "total_pnls": [],
                    }

                strategies[name]["returns"].append(data.get("return_pct", 0))
                strategies[name]["timestamps"].append(log.get("timestamp", ""))
                strategies[name]["order_counts"].append(data.get("order_count", 0))
                strategies[name]["total_pnls"].append(data.get("total_pnl", 0))

        # 计算统计指标
        report = {
            "generated_at": datetime.now().isoformat(),
            "period": {
                "start": logs[0].get("timestamp", "") if logs else "",
                "end": logs[-1].get("timestamp", "") if logs else "",
            },
            "strategies": {},
            "comparison": {},
        }

        for name, data in strategies.items():
            returns = data["returns"]
            if not returns:
                continue

            report["strategies"][name] = {
                "name": name,
                "final_return": returns[-1] if returns else 0,
                "max_return": max(returns) if returns else 0,
                "min_return": min(returns) if returns else 0,
                "total_orders": sum(data["order_counts"]),
                "total_pnl": data["total_pnls"][-1] if data["total_pnls"] else 0,
                "timestamps": len(returns),
            }

        # 对比分析
        if len(report["strategies"]) > 1:
            sorted_strategies = sorted(
                report["strategies"].values(),
                key=lambda x: x["final_return"],
                reverse=True
            )
            report["comparison"]["ranking"] = [s["name"] for s in sorted_strategies]
            report["comparison"]["best"] = sorted_strategies[0]["name"] if sorted_strategies else None
            report["comparison"]["best_return"] = sorted_strategies[0]["final_return"] if sorted_strategies else 0

        return report

    def print_report(self, report: Optional[Dict] = None) -> None:
        """打印报告"""
        if report is None:
            report = self.generate_report()

        print("\n" + "=" * 70)
        print("  三屏趋势系统 — 策略验证报告")
        print("=" * 70)

        if "error" in report:
            print(f"\n  错误: {report['error']}")
            return

        print(f"\n  生成时间: {report['generated_at']}")
        print(f"  验证期间: {report['period']['start']} ~ {report['period']['end']}")

        print("\n  策略表现对比:")
        print("-" * 70)

        # 表头
        header = f"{'策略名':<20} {'收益率':>10} {'最大收益':>10} {'最大亏损':>10} {'交易次数':>10}"
        print(f"  {header}")
        print(f"  {'-'*60}")

        for name, data in report["strategies"].items():
            row = f"{name:<20} {data['final_return']:>9.2f}% {data['max_return']:>9.2f}% {data['min_return']:>9.2f}% {data['total_orders']:>10d}"
            print(f"  {row}")

        # 排名
        if "comparison" in report and report["comparison"].get("ranking"):
            print("\n  排名:")
            for i, name in enumerate(report["comparison"]["ranking"], 1):
                ret = report["strategies"][name]["final_return"]
                print(f"    {i}. {name}: {ret:.2f}%")

        print("\n" + "=" * 70)

    def save_report(self, filepath: Optional[str] = None) -> str:
        """保存报告"""
        report = self.generate_report()

        fname = filepath or f"validation_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        fpath = self.data_dir / fname

        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        print(f"\n  报告已保存: {fpath}")
        return str(fpath)


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="验证报告生成器")
    parser.add_argument("--data-dir", type=str, help="数据目录")
    parser.add_argument("--save", action="store_true", help="保存报告")
    args = parser.parse_args()

    reporter = ValidationReport(data_dir=args.data_dir)

    if args.save:
        reporter.save_report()
    else:
        reporter.print_report()


if __name__ == "__main__":
    main()