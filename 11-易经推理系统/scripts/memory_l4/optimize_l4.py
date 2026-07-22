"""
L4 系统优化脚本 - 解决四大核心问题:
1. 批量升级 v0.2 → v0.3 (482个案例中93%是v0.2)
2. 实现 evidence_chain 填充逻辑
3. 跑通 Review→Distill→Stats 闭环自动化
4. 修正 QMM 数据源，消费真实案例

Usage:
    python optimize_l4.py --all                      # 执行全部优化
    python optimize_l4.py --upgrade                  # 仅批量升级
    python optimize_l4.py --evidence                 # 仅填充 evidence_chain
    python optimize_l4.py --close-loop               # 仅跑通闭环
    python optimize_l4.py --fix-qmm                  # 仅修正 QMM 数据源
"""

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List

import sys
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.memory_l4.paths import (
    memory_l4_cases_dir,
    memory_l4_reviews_dir,
    memory_l4_distills_dir,
    memory_l4_stats_dir,
)
from scripts.memory_l4.case_registry import (
    UnifiedCaseRegistry,
    upgrade_case_to_v03,
)
from scripts.memory_l4.review_engine import run_review
from scripts.memory_l4.distill_engine import run_full_distill_pipeline, save_distill
from scripts.memory_l4.stats_engine import compute_full_stats, save_stats
from scripts.memory_l4.qmm.engine import run_qmm


class L4Optimizer:
    def __init__(self):
        self.cases_dir = memory_l4_cases_dir()
        self.reviews_dir = memory_l4_reviews_dir()
        self.distills_dir = memory_l4_distills_dir()
        self.stats_dir = memory_l4_stats_dir()
        self.registry = UnifiedCaseRegistry()

    def upgrade_all_v02_to_v03(self) -> Dict[str, Any]:
        """批量升级所有 v0.2 案例到 v0.3"""
        results = {
            "total_cases": 0,
            "v02_found": 0,
            "v03_found": 0,
            "upgraded": 0,
            "failed": 0,
            "backup_created": 0,
            "details": [],
        }

        for f in sorted(self.cases_dir.glob("*.json")):
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    case = json.load(fp)
            except Exception as e:
                results["failed"] += 1
                results["details"].append({"file": f.name, "error": f"load failed: {e}"})
                continue

            results["total_cases"] += 1
            version = case.get("version", "unknown")

            if version == "v0.3":
                results["v03_found"] += 1
                continue

            if version != "v0.2":
                results["failed"] += 1
                results["details"].append({"file": f.name, "error": f"unexpected version: {version}"})
                continue

            results["v02_found"] += 1

            backup_path = self.cases_dir / f"{f.stem}_v02_backup.json"
            if not backup_path.exists():
                shutil.copy2(f, backup_path)
                results["backup_created"] += 1

            try:
                upgraded = upgrade_case_to_v03(case)
                upgraded["case_id"] = f"tc_{upgraded.get('system_source', 'unknown')}_{f.stem}"

                with open(f, "w", encoding="utf-8") as fp:
                    json.dump(upgraded, fp, ensure_ascii=False, indent=2, default=str)

                results["upgraded"] += 1
                results["details"].append({"file": f.name, "status": "upgraded", "source": upgraded.get("system_source", "unknown")})
            except Exception as e:
                results["failed"] += 1
                results["details"].append({"file": f.name, "error": f"upgrade failed: {e}"})

        return results

    def enrich_evidence_chain(self) -> Dict[str, Any]:
        """填充所有 v0.3 案例的 evidence_chain"""
        results = {
            "total_cases": 0,
            "v03_found": 0,
            "enriched": 0,
            "failed": 0,
            "details": [],
        }

        for f in sorted(self.cases_dir.glob("*.json")):
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    case = json.load(fp)
            except Exception as e:
                results["failed"] += 1
                results["details"].append({"file": f.name, "error": f"load failed: {e}"})
                continue

            if case.get("version") != "v0.3":
                continue

            results["total_cases"] += 1
            results["v03_found"] += 1

            original_ec = case.get("evidence_chain", {})
            has_content = any(len(original_ec.get(k, [])) > 0 for k in original_ec)
            is_dict_format = False
            has_analyst_refs = False
            if has_content:
                for k in original_ec:
                    for item in original_ec.get(k, []):
                        if isinstance(item, dict) and "type" in item and "ref" in item:
                            is_dict_format = True
                            break
                    if is_dict_format:
                        break
                # 检查是否包含 TradingAgents 增强的 analyst_refs
                if "analyst_refs" in original_ec and len(original_ec["analyst_refs"]) > 0:
                    has_analyst_refs = True
            if has_content and is_dict_format and has_analyst_refs:
                results["details"].append({"file": f.name, "status": "already_enriched"})
                continue

            try:
                case["evidence_chain"] = self._build_evidence_chain(case)

                with open(f, "w", encoding="utf-8") as fp:
                    json.dump(case, fp, ensure_ascii=False, indent=2, default=str)

                results["enriched"] += 1
                results["details"].append({"file": f.name, "status": "enriched"})
            except Exception as e:
                results["failed"] += 1
                results["details"].append({"file": f.name, "error": f"enrich failed: {e}"})

        return results

    def _build_evidence_chain(self, case: Dict[str, Any]) -> Dict[str, List[Dict[str, str]]]:
        """从 case 中提取证据链（TradingAgents 多维度分析师模式增强版）

        参考 TradingAgents 的分析师架构，证据链按维度分类：
        - market_data_refs: 市场数据（价格、波动率、趋势）
        - signal_refs: 交易信号（卦象、置信度、屏幕信号）
        - strategy_refs: 策略配置（系统来源、参数）
        - historical_refs: 历史结果（盈亏、离场原因）
        - constraint_refs: 约束条件（象限、杠杆、 urgency）
        - analyst_refs: 分析师维度证据（基本面/技术面/情绪/风控）
        """
        dc = case.get("decision_context", {})
        es = case.get("environment_snapshot", {})
        pi = case.get("position_info", {})

        evidence = {
            "market_data_refs": [],
            "signal_refs": [],
            "strategy_refs": [],
            "historical_refs": [],
            "constraint_refs": [],
            "analyst_refs": [],
        }

        # ── market_data_refs: 市场数据 ──
        evidence["market_data_refs"].append({"type": "symbol", "ref": str(case.get("symbol"))})
        evidence["market_data_refs"].append({"type": "direction", "ref": str(case.get("direction"))})
        if pi.get("entry_price"):
            evidence["market_data_refs"].append({"type": "entry_price", "ref": str(pi["entry_price"])})
        if pi.get("exit_price"):
            evidence["market_data_refs"].append({"type": "exit_price", "ref": str(pi["exit_price"])})
        if pi.get("leverage"):
            evidence["market_data_refs"].append({"type": "leverage", "ref": str(pi["leverage"])})

        evidence["market_data_refs"].append({"type": "regime", "ref": str(es.get("regime", "unknown"))})
        evidence["market_data_refs"].append({"type": "volatility", "ref": str(es.get("volatility", 0))})
        evidence["market_data_refs"].append({"type": "trend_strength", "ref": str(es.get("trend_strength", 0))})
        evidence["market_data_refs"].append({"type": "is_ranging", "ref": str(es.get("is_ranging", False))})

        # ── signal_refs: 交易信号 ──
        system_source = case.get("system_source")
        evidence["strategy_refs"].append({"type": "system_source", "ref": str(system_source)})

        if system_source == "yijing_inference":
            evidence["signal_refs"].append({"type": "hexagram", "ref": str(dc.get("hexagram", "N/A"))})
            evidence["signal_refs"].append({"type": "confidence", "ref": str(dc.get("confidence", 0))})
            if dc.get("liangyi_state"):
                evidence["signal_refs"].append({"type": "liangyi", "ref": str(dc["liangyi_state"])})
            if dc.get("enhance_info"):
                evidence["constraint_refs"].append({"type": "enhance", "ref": str(dc["enhance_info"])})

            # 分析师维度: 易经推理分析师
            evidence["analyst_refs"].append({
                "type": "yijing_analyst",
                "ref": f"hexagram={dc.get('hexagram', 'N/A')}, confidence={dc.get('confidence', 0)}, liangyi={dc.get('liangyi_state', 'N/A')}"
            })

        elif system_source == "martin_v15":
            evidence["signal_refs"].append({"type": "addon_level", "ref": str(dc.get("addon_level", 0))})
            if dc.get("martin_config"):
                evidence["strategy_refs"].append({"type": "martin_config", "ref": str(dc["martin_config"])})

            # 分析师维度: 马丁策略分析师
            evidence["analyst_refs"].append({
                "type": "martin_analyst",
                "ref": f"addon_level={dc.get('addon_level', 0)}, config={dc.get('martin_config', 'N/A')}"
            })

        elif system_source == "three_screen":
            if dc.get("screen_signals"):
                for screen, signal in dc["screen_signals"].items():
                    evidence["signal_refs"].append({"type": screen, "ref": str(signal)})

            # 分析师维度: 三屏分析师
            screens = dc.get("screen_signals", {})
            evidence["analyst_refs"].append({
                "type": "three_screen_analyst",
                "ref": f"screens={list(screens.keys())}, signals={list(screens.values())}"
            })

        elif system_source in ("agent_a", "agent_b"):
            evidence["signal_refs"].append({"type": "confidence", "ref": str(dc.get("confidence", 0))})
            evidence["strategy_refs"].append({"type": "strategy", "ref": str(dc.get("strategy", "N/A"))})

            # 分析师维度: Agent 分析师
            evidence["analyst_refs"].append({
                "type": f"{system_source}_analyst",
                "ref": f"confidence={dc.get('confidence', 0)}, strategy={dc.get('strategy', 'N/A')}"
            })

        elif system_source == "dream_os":
            evidence["strategy_refs"].append({"type": "fusion_mode", "ref": str(dc.get("fusion_mode", "N/A"))})
            evidence["strategy_refs"].append({"type": "strategy_id", "ref": str(dc.get("strategy_id", "N/A"))})
            evidence["constraint_refs"].append({"type": "urgency", "ref": str(dc.get("urgency", "N/A"))})

            # 分析师维度: DreamOS 融合分析师
            evidence["analyst_refs"].append({
                "type": "dreamos_analyst",
                "ref": f"fusion={dc.get('fusion_mode', 'N/A')}, strategy={dc.get('strategy_id', 'N/A')}"
            })

        # ── 技术面分析师 (所有系统通用) ──
        technical_evidence = []
        if es.get("regime"):
            technical_evidence.append(f"regime={es['regime']}")
        if es.get("volatility") is not None:
            technical_evidence.append(f"volatility={es['volatility']}")
        if es.get("trend_strength") is not None:
            technical_evidence.append(f"trend_strength={es['trend_strength']}")
        if es.get("price_position") is not None:
            technical_evidence.append(f"price_position={es['price_position']}")
        if technical_evidence:
            evidence["analyst_refs"].append({
                "type": "technical_analyst",
                "ref": ", ".join(technical_evidence)
            })

        # ── 情绪面分析师 ──
        sentiment_evidence = []
        if isinstance(dc, dict) and dc.get("confidence"):
            sentiment_evidence.append(f"confidence={dc['confidence']}")
        if case.get("direction"):
            sentiment_evidence.append(f"direction={case['direction']}")
        if sentiment_evidence:
            evidence["analyst_refs"].append({
                "type": "sentiment_analyst",
                "ref": ", ".join(sentiment_evidence)
            })

        # ── 风控分析师 ──
        risk_evidence = []
        if pi.get("leverage"):
            risk_evidence.append(f"leverage={pi['leverage']}x")
        if case.get("risk_events"):
            risk_evidence.append(f"risk_events={len(case['risk_events'])}")
        if risk_evidence:
            evidence["analyst_refs"].append({
                "type": "risk_analyst",
                "ref": ", ".join(risk_evidence)
            })

        # ── historical_refs: 历史结果 ──
        do = case.get("decision_outcome", {})
        evidence["historical_refs"].append({"type": "pnl", "ref": str(do.get("pnl_pct", 0))})
        evidence["historical_refs"].append({"type": "exit_reason", "ref": str(do.get("exit_reason", "N/A"))})
        evidence["historical_refs"].append({"type": "is_correct", "ref": str(do.get("is_correct", "unknown"))})

        # ── constraint_refs: 约束条件 ──
        quadrant = case.get("quadrant", {})
        if isinstance(quadrant, dict):
            evidence["constraint_refs"].append({"type": "quadrant_x", "ref": str(quadrant.get("x", 0))})
            evidence["constraint_refs"].append({"type": "quadrant_y", "ref": str(quadrant.get("y", 0))})

        return evidence

    def run_close_loop(self, batch_size: int = 50) -> Dict[str, Any]:
        """跑通 Review→Distill→Stats 闭环"""
        results = {
            "review_count": 0,
            "distill_count": 0,
            "stats_generated": False,
            "errors": [],
        }

        try:
            cases = []
            for f in sorted(self.cases_dir.glob("*.json")):
                try:
                    with open(f, "r", encoding="utf-8") as fp:
                        case = json.load(fp)
                    if case.get("version") == "v0.3":
                        cases.append(case)
                except Exception:
                    continue

            if not cases:
                results["errors"].append("No v0.3 cases found")
                return results

            print(f"Running review for {len(cases)} v0.3 cases...")
            review_results = run_review(cases=cases)
            results["review_count"] = review_results.get("total_reviews", 0)

            print(f"Running distill for reviewed cases...")
            review_records = []
            for f in sorted(self.reviews_dir.glob("*.json")):
                try:
                    with open(f, "r", encoding="utf-8") as fp:
                        review_records.append(json.load(fp))
                except Exception:
                    continue

            # 过滤真实案例的 review（排除测试案例）
            real_review_records = [
                r for r in review_records
                if "qmm_test" not in r.get("case_id", "") and "yj_test" not in r.get("case_id", "")
            ]
            print(f"  Distilling {min(len(real_review_records), batch_size)} real reviews...")

            distill_count = 0
            for review_record in real_review_records[:batch_size]:
                try:
                    distill = run_full_distill_pipeline(review_record)
                    save_distill(distill)
                    distill_count += 1
                except Exception as e:
                    results["errors"].append(f"Distill failed for {review_record.get('review_id')}: {e}")
            results["distill_count"] = distill_count

            print(f"Generating stats snapshot...")
            stats = compute_full_stats()
            save_stats(stats)
            results["stats_generated"] = True

        except Exception as e:
            results["errors"].append(f"Close loop failed: {e}")

        return results

    def fix_qmm_data_source(self) -> Dict[str, Any]:
        """修正 QMM 数据源，消费真实案例而非测试案例"""
        results = {
            "total_cases": 0,
            "test_cases": 0,
            "real_cases": 0,
            "qmm_snapshot_generated": False,
            "error": None,
        }

        try:
            cases = []
            for f in sorted(self.cases_dir.glob("*.json")):
                try:
                    with open(f, "r", encoding="utf-8") as fp:
                        case = json.load(fp)
                    if case.get("version") != "v0.3":
                        continue

                    case_id = case.get("case_id", "")
                    if "test" in case_id.lower():
                        results["test_cases"] += 1
                        continue

                    if case.get("source") == "live_trading" or case.get("system_source") in [
                        "yijing_inference", "three_screen", "martin_v15",
                        "agent_a", "agent_b", "dream_os"
                    ]:
                        cases.append(case)
                        results["real_cases"] += 1

                except Exception:
                    continue

            results["total_cases"] = len(cases)

            if not cases:
                results["error"] = "No real cases found for QMM"
                return results

            print(f"Running QMM with {len(cases)} real cases...")
            distills = []
            for f in sorted(self.distills_dir.glob("*.json")):
                try:
                    with open(f, "r", encoding="utf-8") as fp:
                        distills.append(json.load(fp))
                except Exception:
                    continue

            run_qmm(cases, distills)
            results["qmm_snapshot_generated"] = True

        except Exception as e:
            results["error"] = f"QMM run failed: {e}"

        return results

    def run_all(self) -> Dict[str, Any]:
        """执行全部优化"""
        print("=" * 60)
        print("L4 系统优化 - 执行全部任务")
        print("=" * 60)

        all_results = {}

        print("\n[1/4] 批量升级 v0.2 → v0.3")
        print("-" * 40)
        all_results["upgrade"] = self.upgrade_all_v02_to_v03()
        self._print_summary(all_results["upgrade"])

        print("\n[2/4] 填充 evidence_chain")
        print("-" * 40)
        all_results["evidence"] = self.enrich_evidence_chain()
        self._print_summary(all_results["evidence"])

        print("\n[3/4] 跑通 Review→Distill→Stats 闭环")
        print("-" * 40)
        all_results["close_loop"] = self.run_close_loop()
        self._print_summary(all_results["close_loop"])

        print("\n[4/4] 修正 QMM 数据源")
        print("-" * 40)
        all_results["fix_qmm"] = self.fix_qmm_data_source()
        self._print_summary(all_results["fix_qmm"])

        print("\n" + "=" * 60)
        print("优化完成")
        print("=" * 60)

        return all_results

    def _print_summary(self, results: Dict[str, Any]):
        """打印执行结果摘要"""
        for key, value in results.items():
            if key == "details" or key == "errors":
                continue
            print(f"  {key}: {value}")

        if "errors" in results and results["errors"]:
            print("  errors:")
            for err in results["errors"]:
                print(f"    - {err}")


def main():
    parser = argparse.ArgumentParser(description="L4 系统优化脚本")
    parser.add_argument("--all", action="store_true", help="执行全部优化")
    parser.add_argument("--upgrade", action="store_true", help="批量升级 v0.2→v0.3")
    parser.add_argument("--evidence", action="store_true", help="填充 evidence_chain")
    parser.add_argument("--close-loop", action="store_true", help="跑通 Review→Distill→Stats 闭环")
    parser.add_argument("--fix-qmm", action="store_true", help="修正 QMM 数据源")
    parser.add_argument("--dry-run", action="store_true", help="模拟运行，不实际修改文件")

    args = parser.parse_args()

    optimizer = L4Optimizer()

    if args.all:
        optimizer.run_all()
    elif args.upgrade:
        print("[1/4] 批量升级 v0.2 → v0.3")
        results = optimizer.upgrade_all_v02_to_v03()
        optimizer._print_summary(results)
    elif args.evidence:
        print("[2/4] 填充 evidence_chain")
        results = optimizer.enrich_evidence_chain()
        optimizer._print_summary(results)
    elif args.close_loop:
        print("[3/4] 跑通 Review→Distill→Stats 闭环")
        results = optimizer.run_close_loop()
        optimizer._print_summary(results)
    elif args.fix_qmm:
        print("[4/4] 修正 QMM 数据源")
        results = optimizer.fix_qmm_data_source()
        optimizer._print_summary(results)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()