"""真实交互能力测试：Playwright 浏览器 + DreamOS /api/intent/route 端点

跑 YAML 场景（真实浏览器打开 chat → 输入问法 → 提交 → DreamOS 意图识别），
IntentSample 自动落盘到 pipeline，最后输出准确率报告。

用法:
    cd 30-真实环境交互系统 && python scripts/run_real_intent_test.py --count 6

前置条件:
    - 前端 chat 页面运行在 :3001
    - DreamOS run_api_server 运行在 :3847（/api/intent/route 可用）
"""
import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml

from core.browser_connector import BrowserConnector, BrowserMode
from core.user_simulator import UserSimulator
from core.result_verifier import ResultVerifier
from core.scenario_runner import ScenarioRunner
from core.intent_sample_pipeline import IntentSamplePipeline, IntentSample

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("real_intent_test")

# 意图关键词 → 用于从问法推断 gold_intent（验证 _extract_user_input 与 gold 一致性）
INTENT_KEYWORDS = {
    "trend_following": ["趋势", "顺势", "涨势", "追多", "上升趋势"],
    "mean_reversion": ["震荡", "高抛低吸", "均值回归", "横盘", "反向"],
    "breakout": ["突破", "突破阻力", "放量突破"],
}


def load_config():
    cfg_path = Path(__file__).parent.parent / "config.yaml"
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def select_scenarios(count: int):
    """从 120 个 YAML 中抽样：每意图取 count//3 个 train + 1 个 eval"""
    scenario_dir = Path(__file__).parent.parent / "scenarios" / "intent_training"
    selected = []
    per_intent = max(1, count // 3)
    for intent in ["trend_following", "mean_reversion", "breakout"]:
        train_files = sorted(scenario_dir.glob(f"{intent}_*_train_*.yaml"))[:per_intent]
        eval_files = sorted(scenario_dir.glob(f"{intent}_*_eval_*.yaml"))[:1]
        selected.extend(train_files)
        selected.extend(eval_files)
    return selected[:count]


def main():
    parser = argparse.ArgumentParser(description="真实交互意图识别能力测试")
    parser.add_argument("--count", type=int, default=6, help="抽样场景数（默认 6）")
    parser.add_argument("--headless", action="store_true", help="无头模式（默认 headed 可见）")
    args = parser.parse_args()

    config = load_config()
    storage_path = Path(__file__).parent.parent / "training" / "intent_samples"
    pipeline = IntentSamplePipeline(storage_path=storage_path, bucket_threshold=30)

    connector = BrowserConnector(config)
    simulator = UserSimulator(config)
    verifier = ResultVerifier(config)
    runner = ScenarioRunner(config, simulator, verifier, pipeline=pipeline)

    # PLAYWRIGHT_CHROMIUM: Playwright 内置 Chromium，沙箱内可用（系统 Chrome 受 TRAE 沙箱 Crashpad 限制）
    mode = BrowserMode.PLAYWRIGHT_CHROMIUM
    config["browser"]["headed"] = not args.headless
    logger.info("连接浏览器 (mode=%s, headless=%s)...", mode.name, args.headless)
    connector.connect(mode=mode)
    connector.new_context()

    scenarios = select_scenarios(args.count)
    logger.info("抽样 %d 个场景开始真实交互测试", len(scenarios))

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
            })
        except Exception as e:
            logger.warning("[%d/%d] %s 执行异常: %s", i, len(scenarios), sc_path.name, e)
            results.append({"file": sc_path.name, "gold": None, "scenario_passed": False, "error": str(e)})
        finally:
            try:
                page.close()
            except Exception:
                pass

    connector.close()

    # 统计 IntentSample
    train_samples = pipeline.load_split("train")
    eval_samples = pipeline.load_split("eval")
    all_samples = train_samples + eval_samples

    print("\n" + "=" * 60)
    print("真实交互能力测试报告")
    print("=" * 60)
    print(f"场景执行: {sum(1 for r in results if r['scenario_passed'])}/{len(results)} 通过")
    print(f"IntentSample 落盘: train={len(train_samples)}, eval={len(eval_samples)}")

    if all_samples:
        confirmed = sum(1 for s in all_samples if s.human_label.get("confirmed"))
        accuracy = confirmed / len(all_samples)
        print(f"意图识别准确率: {confirmed}/{len(all_samples)} = {accuracy:.2%}")
        print("\n样本明细:")
        for s in all_samples:
            pred = s.recognizer_output.get("predicted_intent")
            canon = s.recognizer_output.get("canon_intent", "-")
            conf = s.recognizer_output.get("confidence", 0) or 0.0
            ok = "✓" if s.human_label.get("confirmed") else "✗"
            print(f"  {ok} gold={s.gold['gold_intent']:<16} predicted={str(pred):<16} "
                  f"canon={str(canon):<16} conf={conf:.2f} query={s.input['user_query'][:30]}")
    else:
        print("⚠ 无 IntentSample 落盘，检查场景执行是否正常")

    print("=" * 60)
    print(f"IntentSample 存储路径: {storage_path}")


if __name__ == "__main__":
    main()
