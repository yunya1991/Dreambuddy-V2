"""
A7 实践论门禁节点

基于实践论的决策验证能力：
    - 历史表现验证
    - 策略胜率检查
    - 置信度校准
    - 实战记录匹配
    - 65% 置信度门槛

输入: state.intent + state.history + state.prior_conclusions
输出: direction / confidence / gate_result / confidence_threshold / rationale
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult


class A7PracticeGateNode(BaseNode):
    """A7 实践论门禁节点

    基于历史实战记录验证当前决策的有效性，65% 置信度门槛。
    """

    node_id = "A7"
    name = "实践论门禁"
    description = "历史实战验证（策略胜率/置信度校准/65%门槛/实战记录匹配）"
    chain = "A"
    tags = ["practice", "gate", "validation", "confidence", "history"]
    estimated_tokens = 0
    estimated_latency_ms = 100

    # 对称门槛：多空同等置信度要求
    LONG_THRESHOLD = 0.62
    SHORT_THRESHOLD = 0.62

    def execute_core(self, state: State) -> NodeResult:
        intent = state.intent if isinstance(state.intent, dict) else {}
        prior_conclusions = self._get_prior_conclusions(state)
        history = self._get_history(state)
        rationale: List[str] = []
        scores = []

        proposed_direction = intent.get("direction", "HOLD")
        proposed_confidence = intent.get("confidence", 0.5)
        confidence_threshold = (
            self.SHORT_THRESHOLD if proposed_direction == "SHORT" else self.LONG_THRESHOLD
        )

        # ── 1. 获取历史表现 ──────────────────────────────
        total_trades = history.get("total_trades", 0)
        win_trades = history.get("win_trades", 0)
        win_rate = win_trades / max(total_trades, 1) * 100

        # ── 2. 策略胜率检查 ──────────────────────────────
        if win_rate > 60:
            scores.append(("LONG", 0.20, f"历史胜率高({win_rate:.1f}%)"))
        elif win_rate < 40:
            scores.append(("HOLD", 0.25, f"历史胜率低({win_rate:.1f}%)，需要提高置信度"))

        # ── 3. 置信度校准 ────────────────────────────────
        calibrated_confidence = proposed_confidence
        if total_trades > 10:
            calibrated_confidence = proposed_confidence * (0.5 + win_rate / 200)

        # ── 4. 实战记录匹配 ──────────────────────────────
        similar_trades = history.get("similar_trades", [])
        similar_win_rate = 0
        if similar_trades:
            similar_win_rate = sum(1 for t in similar_trades if t.get("win", False)) / len(similar_trades) * 100
            if similar_win_rate > 65:
                scores.append(("LONG", 0.20, f"相似场景胜率高({similar_win_rate:.1f}%)"))
            elif similar_win_rate < 45:
                scores.append(("HOLD", 0.20, f"相似场景胜率低({similar_win_rate:.1f}%)"))

        # ── 5. 65% 置信度门槛检查 ────────────────────────
        gate_passed = calibrated_confidence >= confidence_threshold

        if gate_passed:
            scores.append(("LONG", 0.30, f"置信度达标({calibrated_confidence:.1%} >= {confidence_threshold:.1%})"))
        else:
            scores.append(("HOLD", 0.35, f"置信度未达标({calibrated_confidence:.1%} < {confidence_threshold:.1%})"))

        # ── 6. 连续亏损检查 ──────────────────────────────
        loss_streak = history.get("loss_streak", 0)
        if loss_streak >= 3:
            scores.append(("HOLD", 0.20, f"连续亏损{loss_streak}次，建议观望"))
            gate_passed = False

        # ── 7. 与前期结论一致性检查 ────────────────────────
        recent_directions = []
        if prior_conclusions:
            recent_directions = [c.get("direction") for c in prior_conclusions[-5:] if c.get("direction")]
            if recent_directions and all(d == proposed_direction for d in recent_directions):
                scores.append(("LONG", 0.10, "与前期结论一致"))
            elif len(set(recent_directions)) > 1:
                scores.append(("HOLD", 0.10, "前期结论不一致"))

        # ── 8. RAG 知识库检索（Phase 3 集成）────────────────
        rag_insights = self._query_knowledge_base(state, proposed_direction)
        if rag_insights:
            for insight in rag_insights[:3]:
                insight_dir = insight.get("direction", "HOLD")
                insight_weight = insight.get("weight", 0.15)
                insight_text = insight.get("text", "")[:80]
                scores.append((insight_dir, insight_weight, f"[知识库] {insight_text}"))

        # ── 9. 索引系统查询（G7+G8 集成）────────────────────
        index_insights = self._query_index_system(state, proposed_direction)
        if index_insights:
            for insight in index_insights[:3]:
                insight_dir = insight.get("direction", "HOLD")
                insight_weight = insight.get("weight", 0.10)
                insight_text = insight.get("text", "")[:80]
                scores.append((insight_dir, insight_weight, f"[索引] {insight_text}"))

        # ── 综合计算 ────────────────────────────────────
        long_score = sum(w for d, w, _ in scores if d == "LONG")
        short_score = sum(w for d, w, _ in scores if d == "SHORT")
        hold_score = sum(w for d, w, _ in scores if d == "HOLD")
        total = long_score + short_score + hold_score

        if gate_passed:
            direction = proposed_direction
            confidence = calibrated_confidence
        else:
            direction = "HOLD"
            confidence = calibrated_confidence

        gate_result = "passed" if gate_passed else "blocked"

        rationale = [r for _, _, r in scores[:6]]
        rationale.insert(0, f"[A7实践论门禁] 门禁={gate_result} | 校准置信度={calibrated_confidence:.1%}")
        rationale.append(f"  方向: {direction} | 门槛: {confidence_threshold:.1%}")

        outputs = {
            "gate_result": gate_result,
            "gate_passed": gate_passed,
            "confidence_threshold": confidence_threshold,
            "proposed_confidence": proposed_confidence,
            "calibrated_confidence": round(calibrated_confidence, 3),
            "direction": direction,
            "history": {
                "total_trades": total_trades,
                "win_trades": win_trades,
                "win_rate": round(win_rate, 2),
                "loss_streak": loss_streak,
                "similar_trades_count": len(similar_trades),
                "similar_win_rate": round(similar_win_rate, 2),
            },
            "prior_conclusions_consistency": len(set(recent_directions)) == 1 if recent_directions else True,
            "scores": {"long": round(long_score, 3), "short": round(short_score, 3), "hold": round(hold_score, 3)},
            "rationale": rationale,
        }

        return NodeResult(
            node_id="A7",
            confidence=round(confidence, 3),
            direction=direction,
            outputs=outputs,
        )

    def _get_prior_conclusions(self, state: State) -> List[Dict]:
        if hasattr(state, "prior_conclusions") and state.prior_conclusions:
            return state.prior_conclusions
        if isinstance(state.intent, dict) and "prior_conclusions" in state.intent:
            return state.intent["prior_conclusions"]
        return []

    def _get_history(self, state: State) -> Dict[str, Any]:
        if hasattr(state, "history") and state.history:
            return state.history
        if isinstance(state.intent, dict) and "history" in state.intent:
            return state.intent["history"]
        return {"total_trades": 0, "win_trades": 0, "loss_streak": 0, "similar_trades": []}

    def _query_knowledge_base(self, state: State, direction: str) -> List[Dict[str, Any]]:
        """RAG 知识库检索（Phase 3 集成）

        从 2-KNOWLEDGE/9-RAG-INFRA/ 检索与当前决策相关的知识。
        FAIL-OPEN: 检索失败返回空列表，不影响 A7 主流程。
        """
        try:
            import sys
            import os
            rag_path = os.path.join(
                os.path.dirname(__file__), "..", "..", "..", "..", "..",
                "2-KNOWLEDGE", "9-RAG-INFRA", "vector_store"
            )
            if rag_path not in sys.path:
                sys.path.insert(0, rag_path)
            from search import semantic_search

            # 构建查询
            intent = state.intent if isinstance(state.intent, dict) else {}
            symbol = intent.get("symbol", "BTC")
            query = f"{symbol} {direction} 交易策略 风险管理"

            results = semantic_search(query, top_k=3)
            insights = []
            for r in results:
                insights.append({
                    "direction": direction,
                    "weight": 0.15,
                    "text": r.get("content", "")[:120],
                })
            return insights
        except Exception:
            return []  # FAIL-OPEN

    def _query_index_system(self, state: State, direction: str) -> List[Dict[str, Any]]:
        """索引系统查询（G7+G8 集成）

        查询产物索引和交易索引，为 A7 提供全景反思输入。
        G7: 产物索引 — 查询产物关系/阶段分组，了解研究链路状态
        G8: 交易索引 — 查询历史交易记录，获取经验数据

        FAIL-OPEN: 查询失败返回空列表，不影响 A7 主流程。
        """
        try:
            import os
            import json
            from pathlib import Path

            project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
            insights: list[dict[str, Any]] = []

            # G7: 产物索引 — 查询产物关系
            artifacts_root = Path.home() / ".workbuddy" / "artifacts"
            if artifacts_root.is_dir():
                # 统计各阶段产物数量
                phase_counts: dict[str, int] = {}
                for entry in artifacts_root.iterdir():
                    if not entry.is_dir() or entry.name.startswith("_"):
                        continue
                    # 查找 index.json
                    idx_file = entry / "index.json"
                    if idx_file.exists():
                        try:
                            data = json.loads(idx_file.read_text(encoding="utf-8"))
                            if isinstance(data, list):
                                phase_counts[entry.name] = len(data)
                        except Exception:
                            pass

                if phase_counts:
                    total = sum(phase_counts.values())
                    top_cats = sorted(phase_counts.items(), key=lambda x: x[1], reverse=True)[:3]
                    cats_str = ", ".join(f"{c}={n}" for c, n in top_cats)
                    insights.append({
                        "direction": direction,
                        "weight": 0.08,
                        "text": f"产物索引: {total}个产物, Top: {cats_str}",
                    })

            # G8: 交易索引 — 查询历史交易统计
            trade_index_path = project_root / ".workbuddy" / "trade_index" / "all_trades_index.jsonl"
            if trade_index_path.exists():
                trades: list[dict[str, Any]] = []
                with open(trade_index_path, "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            trades.append(json.loads(line.strip()))
                        except Exception:
                            pass

                if trades:
                    wins = sum(1 for t in trades if t.get("pnl", 0) > 0)
                    win_rate = wins / len(trades) if trades else 0
                    # 检查当前方向的历史胜率
                    dir_trades = [t for t in trades if t.get("direction", "").upper() == direction]
                    if dir_trades:
                        dir_wins = sum(1 for t in dir_trades if t.get("pnl", 0) > 0)
                        dir_rate = dir_wins / len(dir_trades)
                        insights.append({
                            "direction": direction if dir_rate >= 0.4 else "HOLD",
                            "weight": 0.10,
                            "text": f"交易索引: {direction}历史{len(dir_trades)}笔,胜率{dir_rate:.0%}",
                        })
                    else:
                        insights.append({
                            "direction": direction,
                            "weight": 0.05,
                            "text": f"交易索引: 无{direction}历史交易,总{len(trades)}笔",
                        })

            return insights
        except Exception:
            return []  # FAIL-OPEN