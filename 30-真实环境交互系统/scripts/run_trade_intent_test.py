"""Trade 页意图识别能力验证：Playwright 浏览器 + DreamOS 意图识别 + Trade 页 UI 断言

跑 scenarios/trade_intent/ 下的 YAML 场景（打开 /dashboard/trade → 输入问法 → 提交），
自动捕获 IntentSample + Trade 页 UI 验证结果（S 层徽章 / 链路追踪），
输出综合报告：准确率 / S 层徽章通过率 / 链路活跃率 / 按意图分类统计。

用法:
    cd 30-真实环境交互系统 && python scripts/run_trade_intent_test.py --count 6
    cd 30-真实环境交互系统 && python scripts/run_trade_intent_test.py --scope all --count 30

前置条件:
    - 前端运行在 :3001，/dashboard/trade 可访问
    - DreamOS /api/v1/intent/route 可用（或 FAIL-OPEN 降级）
"""
import argparse
import json
import logging
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml

from core.browser_connector import BrowserConnector, BrowserMode
from core.user_simulator import UserSimulator
from core.result_verifier import ResultVerifier
from core.scenario_runner import ScenarioRunner
from core.intent_sample_pipeline import IntentSamplePipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("trade_intent_test")

# 前端高阶意图类型 → 策略类 gold 标签的映射
# 前端 S 层使用高阶意图（execute_trade/market_query/...），
# 我们的 gold 标签是策略细分（trend_following/mean_reversion/breakout），
# 三者均属"交易类"，前端统一识别为 execute_trade / strategy_verify / deep_analysis
TRADE_RELATED_INTENTS = {"execute_trade", "strategy_verify", "deep_analysis", "scenario_sim"}


def is_intent_correct(gold: str, predicted: str) -> bool:
    """判断预测意图是否与 gold 匹配（支持前端高阶意图映射）"""
    if predicted == gold:
        return True
    # 策略类意图 → 前端交易类意图均视为正确
    strategy_intents = {"trend_following", "mean_reversion", "breakout"}
    if gold in strategy_intents and predicted in TRADE_RELATED_INTENTS:
        return True
    return False


def load_config():
    cfg_path = Path(__file__).parent.parent / "config.yaml"
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def select_scenarios(count: int, scope: str = "accuracy"):
    """从 trade_intent 场景中抽样

    scope:
        - accuracy: 每意图 count//3 个 train + 1 eval（默认）
        - all: 全部 120 个
    """
    scenario_dir = Path(__file__).parent.parent / "scenarios" / "trade_intent"
    selected = []

    if scope == "all":
        all_scenarios = sorted(scenario_dir.glob("*.yaml"))
        if count <= 0:
            return all_scenarios
        # 均匀分布：按意图分组后轮流取，确保各意图样本平衡
        by_intent: Dict[str, List[Path]] = {
            "trend_following": [], "mean_reversion": [], "breakout": [],
        }
        for p in all_scenarios:
            for intent in by_intent:
                if p.name.startswith(intent):
                    by_intent[intent].append(p)
                    break
        selected = []
        per_intent = max(1, count // 3)
        for intent in by_intent:
            selected.extend(by_intent[intent][:per_intent])
        # 补齐余数
        if len(selected) < count:
            remaining = [p for p in all_scenarios if p not in selected]
            selected.extend(remaining[:count - len(selected)])
        return selected[:count]

    per_intent = max(1, count // 3)
    for intent in ["trend_following", "mean_reversion", "breakout"]:
        train_files = sorted(scenario_dir.glob(f"{intent}_*_train_*.yaml"))[:per_intent]
        eval_files = sorted(scenario_dir.glob(f"{intent}_*_eval_*.yaml"))[:1]
        selected.extend(train_files)
        selected.extend(eval_files)
    return selected[:count]


def main():
    parser = argparse.ArgumentParser(description="Trade 页意图识别能力验证")
    parser.add_argument("--count", type=int, default=6, help="抽样场景数（0=全部）")
    parser.add_argument("--scope", default="accuracy", choices=["accuracy", "all"],
                        help="抽样模式: accuracy(默认) | all")
    parser.add_argument("--headless", action="store_true", help="无头模式")
    parser.add_argument("--report-dir", default=None, help="报告输出目录")
    args = parser.parse_args()

    config = load_config()
    storage_path = Path(__file__).parent.parent / "training" / "intent_samples"
    pipeline = IntentSamplePipeline(storage_path=storage_path, bucket_threshold=30)

    connector = BrowserConnector(config)
    simulator = UserSimulator(config)
    verifier = ResultVerifier(config)
    runner = ScenarioRunner(config, simulator, verifier, pipeline=pipeline)

    mode = BrowserMode.PLAYWRIGHT_CHROMIUM
    config["browser"]["headed"] = not args.headless
    logger.info("连接浏览器 (mode=%s, headless=%s)...", mode.name, args.headless)
    connector.connect(mode=mode)
    connector.new_context()

    scenarios = select_scenarios(args.count, args.scope)
    logger.info("抽样 %d 个 Trade 页场景开始验证", len(scenarios))

    results = []
    for i, sc_path in enumerate(scenarios, 1):
        page = connector.new_page()
        try:
            scenario = runner.load_scenario(str(sc_path))
            gold = scenario["intent_training"]["gold_intent"]
            logger.info("[%d/%d] %s (gold=%s)", i, len(scenarios), sc_path.name, gold)
            result = runner.run(page, scenario)
            results.append({
                "file": sc_path.name,
                "gold": gold,
                "scenario_passed": result.passed,
                "trade_ui": result.trade_ui,
            })
        except Exception as e:
            logger.warning("[%d/%d] %s 执行异常: %s", i, len(scenarios), sc_path.name, e)
            results.append({"file": sc_path.name, "gold": None, "scenario_passed": False,
                            "error": str(e), "trade_ui": None})
        finally:
            try:
                page.close()
            except Exception:
                pass

    connector.close()

    # === 统计 ===
    train_samples = pipeline.load_split("train")
    eval_samples = pipeline.load_split("eval")
    all_samples = train_samples + eval_samples

    # UI 统计
    ui_results = [r for r in results if r.get("trade_ui")]
    s_layer_visible = sum(1 for r in ui_results if r["trade_ui"].get("s_layer_visible"))
    chain_active = sum(1 for r in ui_results if r["trade_ui"].get("chain_active"))

    # 按意图分类
    by_intent = defaultdict(lambda: {"total": 0, "correct": 0, "s_layer": 0, "chain": 0})

    report_data = {
        "timestamp": datetime.now().isoformat(),
        "total_scenarios": len(results),
        "scenario_pass_rate": sum(1 for r in results if r["scenario_passed"]) / max(len(results), 1),
        "intent_accuracy": 0.0,
        "s_layer_pass_rate": s_layer_visible / max(len(ui_results), 1),
        "chain_active_rate": chain_active / max(len(ui_results), 1),
        "by_intent": {},
        "samples": [],
    }

    if all_samples:
        confirmed = sum(1 for s in all_samples
                       if is_intent_correct(s.gold["gold_intent"],
                                           s.recognizer_output.get("predicted_intent") or ""))
        accuracy = confirmed / len(all_samples)
        report_data["intent_accuracy"] = accuracy

        for s in all_samples:
            intent = s.gold["gold_intent"]
            pred = s.recognizer_output.get("predicted_intent") or ""
            correct = is_intent_correct(intent, pred)
            by_intent[intent]["total"] += 1
            if correct:
                by_intent[intent]["correct"] += 1
            report_data["samples"].append({
                "gold": intent,
                "predicted": pred,
                "confirmed": correct,
                "confidence": s.recognizer_output.get("confidence", 0),
                "query": s.input["user_query"][:50],
            })

    for intent, stats in by_intent.items():
        report_data["by_intent"][intent] = {
            "total": stats["total"],
            "correct": stats["correct"],
            "accuracy": stats["correct"] / max(stats["total"], 1),
        }

    # === 输出报告 ===
    print("\n" + "=" * 70)
    print("Trade 页意图识别能力验证报告")
    print("=" * 70)
    print(f"场景执行: {sum(1 for r in results if r['scenario_passed'])}/{len(results)} 通过")
    print(f"意图识别准确率: {report_data['intent_accuracy']:.2%}")
    print(f"S 层徽章展示率: {report_data['s_layer_pass_rate']:.2%} ({s_layer_visible}/{len(ui_results)})")
    print(f"链路活跃率: {report_data['chain_active_rate']:.2%} ({chain_active}/{len(ui_results)})")

    if report_data["by_intent"]:
        print("\n按意图分类:")
        for intent, stats in report_data["by_intent"].items():
            print(f"  {intent:<18} {stats['correct']}/{stats['total']} = {stats['accuracy']:.2%}")

    if all_samples:
        print("\n样本明细:")
        for s in report_data["samples"]:
            ok = "✓" if s["confirmed"] else "✗"
            print(f"  {ok} gold={s['gold']:<16} predicted={str(s['predicted']):<16} "
                  f"conf={s['confidence']:.2f} query={s['query']}")

    print("=" * 70)

    # === 保存 JSON 报告 ===
    report_dir = Path(args.report_dir) if args.report_dir else \
        Path(__file__).parent.parent / "reports" / f"trade_intent_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_file = report_dir / "report.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)
    print(f"报告已保存: {report_file}")
    print(f"IntentSample 存储路径: {storage_path}")


if __name__ == "__main__":
    main()
