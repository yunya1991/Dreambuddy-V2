#!/usr/bin/env python3
"""
记分卡模块 - 结构化记录每次交易决策，计算多维度指标
"""
import json, os, time
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent / "logs"


def _cycle_id() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")


class DecisionLog:
    """每次 cron 触发时，agent 填写这个结构化决策单"""

    def __init__(self, agent_id: str, cycle_id: str):
        self.agent_id = agent_id      # "a" or "b"
        self.cycle_id = cycle_id
        self.ts_utc = datetime.utcnow().isoformat()
        self.data: Dict = {
            "agent_id": agent_id,
            "cycle_id": cycle_id,
            "ts_utc": self.ts_utc,

            # ── 市场判断 ──────────────────────────────────────
            "market_regime": None,        # TREND_UP / TREND_DOWN / RANGE / BREAKOUT
            "key_contradictions": [],     # A0 矛盾识别列表 (B专用，A可为空)
            "reasoning_steps": [],        # 推理步骤列表（字符串）
            "confidence": None,           # 0.0-1.0 置信度
            "supporting_evidence": [],    # 支撑证据

            # ── 交易决策 ──────────────────────────────────────
            "action": None,               # BUY / SELL / HOLD
            "entry_price": None,
            "position_size_usdt": None,
            "stop_loss_price": None,
            "take_profit_price": None,
            "decision_rationale": "",     # 一句话决策依据

            # ── 执行结果 ──────────────────────────────────────
            "execution": {
                "ok": False,
                "ord_id": None,
                "filled_price": None,
                "filled_size": None,
                "error": None,
            },

            # ── B专用：系统特征追踪 ───────────────────────────
            "system_features_used": [],   # 实际调用了哪些A系skill
            "graph_context_nodes": 0,     # 本轮图压缩节点数
            "memory_loaded": False,       # 是否加载了历史记忆
            "prior_lessons_applied": [],  # 应用了哪些历史教训

            # ── 事后评估（结算时填入）────────────────────────
            "pnl_pct": None,
            "exit_price": None,
            "exit_ts": None,
            "exit_reason": None,          # TP / SL / SIGNAL / MANUAL
            "was_correct": None,          # True/False
        }

    def save(self) -> Path:
        agent_dir = LOG_DIR / f"agent_{self.agent_id}"
        agent_dir.mkdir(parents=True, exist_ok=True)
        path = agent_dir / f"{self.cycle_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        return path


class Scorecard:
    """汇总计算多维度指标"""

    WEIGHTS = {
        "pnl_pct":              0.30,
        "win_rate":             0.20,
        "decision_confidence":  0.15,
        "reasoning_depth":      0.10,
        "context_continuity":   0.10,
        "risk_execution":       0.10,
        "adaptation_score":     0.05,
    }

    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.logs: List[Dict] = self._load_logs()

    def _load_logs(self) -> List[Dict]:
        agent_dir = LOG_DIR / f"agent_{self.agent_id}"
        if not agent_dir.exists():
            return []
        logs = []
        for f in sorted(agent_dir.glob("*.json")):
            with open(f) as fp:
                logs.append(json.load(fp))
        return logs

    def compute(self) -> Dict:
        if not self.logs:
            return {"agent_id": self.agent_id, "cycles": 0, "error": "no logs"}

        completed = [l for l in self.logs if l.get("pnl_pct") is not None]
        n = len(completed)
        if n == 0:
            return {"agent_id": self.agent_id, "cycles": len(self.logs),
                    "completed_cycles": 0}

        # ── PnL ──────────────────────────────────────────────
        pnl_values = [l["pnl_pct"] for l in completed]
        avg_pnl = sum(pnl_values) / n
        cumulative_pnl = (1 + sum(pnl_values))  # 简化累积（精确版需逐笔计算）

        # ── 胜率 ─────────────────────────────────────────────
        wins = [l for l in completed if l.get("pnl_pct", 0) > 0]
        win_rate = len(wins) / n

        # ── 置信度均值 ───────────────────────────────────────
        conf_vals = [l.get("confidence") or 0 for l in self.logs if l.get("confidence")]
        avg_confidence = sum(conf_vals) / len(conf_vals) if conf_vals else 0

        # ── 推理深度（推理步骤数均值）────────────────────────
        depth_vals = [len(l.get("reasoning_steps", [])) for l in self.logs]
        avg_depth = sum(depth_vals) / len(depth_vals) if depth_vals else 0

        # ── 上下文连续性（B专用：记忆加载率）────────────────
        if self.agent_id == "b":
            memory_loads = [l for l in self.logs if l.get("memory_loaded")]
            context_continuity = len(memory_loads) / len(self.logs)
        else:
            context_continuity = 0.0

        # ── 风控执行（止损触发且实际止损 / 应止损总数）──────
        sl_triggered = [l for l in completed if l.get("exit_reason") == "SL"]
        risk_execution = len(sl_triggered) / max(
            len([l for l in completed if l.get("pnl_pct", 0) < -0.02]), 1
        )

        # ── 适应性（后10轮胜率 vs 前10轮胜率）───────────────
        if n >= 20:
            first10 = [l for l in completed[:10] if l.get("pnl_pct", 0) > 0]
            last10 = [l for l in completed[-10:] if l.get("pnl_pct", 0) > 0]
            adaptation = (len(last10) - len(first10)) / 10 + 0.5
        else:
            adaptation = 0.5

        # ── 加权综合分 ───────────────────────────────────────
        raw_scores = {
            "pnl_pct":             min(max(avg_pnl / 0.02 * 0.5 + 0.5, 0), 1),
            "win_rate":            win_rate,
            "decision_confidence": avg_confidence,
            "reasoning_depth":     min(avg_depth / 10.0, 1.0),
            "context_continuity":  context_continuity,
            "risk_execution":      min(risk_execution, 1.0),
            "adaptation_score":    min(max(adaptation, 0), 1),
        }
        composite = sum(raw_scores[k] * self.WEIGHTS[k] for k in self.WEIGHTS)

        return {
            "agent_id": self.agent_id,
            "cycles_total": len(self.logs),
            "cycles_completed": n,
            "metrics": {
                "avg_pnl_pct": round(avg_pnl * 100, 2),
                "cumulative_pnl_factor": round(cumulative_pnl, 4),
                "win_rate": round(win_rate * 100, 1),
                "avg_confidence": round(avg_confidence, 3),
                "avg_reasoning_depth": round(avg_depth, 1),
                "context_continuity": round(context_continuity * 100, 1),
                "risk_execution": round(risk_execution * 100, 1),
                "adaptation_score": round(adaptation, 3),
            },
            "raw_scores": {k: round(v, 3) for k, v in raw_scores.items()},
            "composite_score": round(composite, 4),
        }


def compare_agents() -> Dict:
    sc_a = Scorecard("a").compute()
    sc_b = Scorecard("b").compute()
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "agent_a": sc_a,
        "agent_b": sc_b,
        "winner": (
            "B" if sc_b.get("composite_score", 0) > sc_a.get("composite_score", 0)
            else "A" if sc_a.get("composite_score", 0) > sc_b.get("composite_score", 0)
            else "TIE"
        ),
        "delta_composite": round(
            sc_b.get("composite_score", 0) - sc_a.get("composite_score", 0), 4
        ),
    }


if __name__ == "__main__":
    result = compare_agents()
    print(json.dumps(result, ensure_ascii=False, indent=2))
