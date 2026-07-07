#!/usr/bin/env python3
"""
进化引擎核心 — 管理三层进化系统
三层进化体系：
1. A8理论与实践验证进化 - 内部自我批评自循环
2. 做梦部外部反思进化 - 潜意识层外部视角
3. GitHub成熟经验搜索进化 - 外部成熟经验验证
"""
import json, os, time
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timezone
from enum import Enum

from .backtest_engine import SimpleBacktestEngine

BASE_DIR = Path(__file__).parent.parent.parent
EVOLUTION_DATA_DIR = BASE_DIR / "data" / "evolution"
EVOLUTION_DATA_DIR.mkdir(parents=True, exist_ok=True)


class EvolutionSource(str, Enum):
    A8_THEORY_PRACTICE = "a8_theory_practice"
    DREAM_ONEIROLOGY = "dream_oneirology"
    GITHUB_BEST_PRACTICE = "github_best_practice"


class EvolutionStatus(str, Enum):
    PROPOSED = "proposed"
    BACKTESTING = "backtesting"
    OBSERVATION = "observation"
    ADOPTED = "adopted"
    REJECTED = "rejected"
    ROLLED_BACK = "rolled_back"


class EvolutionEngine:
    """
    进化引擎 - 管理所有进化提议的生命周期
    """

    def __init__(self, agent_id: str = "a"):
        self.agent_id = agent_id
        self.pool_file = EVOLUTION_DATA_DIR / f"{agent_id}_evolution_pool.json"
        self.history_file = EVOLUTION_DATA_DIR / f"{agent_id}_evolution_history.json"
        self.backtest_engine = SimpleBacktestEngine()
        self._init_pool()

    def _init_pool(self):
        """初始化进化池"""
        if not self.pool_file.exists():
            self._save_pool({"proposals": [], "adopted": []})
        if not self.history_file.exists():
            self._save_history({"history": []})

    def _load_pool(self) -> Dict:
        try:
            with open(self.pool_file) as f:
                return json.load(f)
        except Exception:
            return {"proposals": [], "adopted": []}

    def _save_pool(self, pool: Dict):
        with open(self.pool_file, "w") as f:
            json.dump(pool, f, indent=2, ensure_ascii=False)

    def _load_history(self) -> Dict:
        try:
            with open(self.history_file) as f:
                return json.load(f)
        except Exception:
            return {"history": []}

    def _save_history(self, history: Dict):
        with open(self.history_file, "w") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)

    def propose_evolution(
        self,
        source: EvolutionSource,
        title: str,
        description: str,
        strategy_params: Dict,
        rationale: str,
        priority: str = "medium",
    ) -> Dict:
        """
        提交一个进化提议

        Args:
            source: 进化来源（A8/做梦部/GitHub）
            title: 提议标题
            description: 详细描述
            strategy_params: 策略参数变更
            rationale: 改进理由
            priority: 优先级 high/medium/low

        Returns:
            提议详情
        """
        pool = self._load_pool()

        proposal = {
            "id": f"evo_{int(time.time())}_{len(pool.get('proposals', []))}",
            "source": source.value,
            "title": title,
            "description": description,
            "strategy_params": strategy_params,
            "rationale": rationale,
            "priority": priority,
            "status": EvolutionStatus.PROPOSED.value,
            "created_at": self._now_iso(),
            "backtest_result": None,
            "observation_start": None,
            "observation_end": None,
            "observation_result": None,
            "adopted_at": None,
            "rejected_at": None,
            "rejection_reason": None,
        }

        pool["proposals"].append(proposal)
        self._save_pool(pool)

        self._record_history(proposal["id"], "proposed", {
            "source": source.value,
            "title": title,
        })

        print(f"[进化] 新提议: {title} (来源: {source.value}, ID: {proposal['id']})")
        return proposal

    def run_backtest(self, proposal_id: str, coins: List[str]) -> Dict:
        """
        对提议进行回测验证

        Args:
            proposal_id: 提议ID
            coins: 回测币种列表

        Returns:
            回测结果汇总
        """
        pool = self._load_pool()
        proposal = self._find_proposal(proposal_id, pool)

        if not proposal:
            return {"error": f"提议 {proposal_id} 不存在"}

        proposal["status"] = EvolutionStatus.BACKTESTING.value
        self._save_pool(pool)

        baseline_params = self._get_baseline_params()
        improved_params = {**baseline_params, **proposal["strategy_params"]}

        all_results = []
        for coin in coins:
            result = self.backtest_engine.compare_strategies(
                coin, baseline_params, improved_params
            )
            all_results.append(result)

        avg_improvement = self._calc_avg_improvement(all_results)

        proposal["backtest_result"] = {
            "coins_tested": coins,
            "per_coin_results": all_results,
            "avg_improvement": avg_improvement,
            "overall_improvement": avg_improvement["total_pnl_change_pct"] > 0,
            "tested_at": self._now_iso(),
        }

        if avg_improvement["total_pnl_change_pct"] > 2 and avg_improvement["sharpe_change"] > 0:
            proposal["status"] = EvolutionStatus.OBSERVATION.value
            proposal["observation_start"] = self._now_iso()
            print(f"[进化] 回测通过，进入观察期: {proposal['title']}")
        else:
            proposal["status"] = EvolutionStatus.REJECTED.value
            proposal["rejected_at"] = self._now_iso()
            proposal["rejection_reason"] = f"回测未达标: PnL变化{avg_improvement['total_pnl_change_pct']:.2f}%, Sharpe变化{avg_improvement['sharpe_change']:.4f}"
            print(f"[进化] 回测未通过: {proposal['title']} - {proposal['rejection_reason']}")

        self._save_pool(pool)
        self._record_history(proposal_id, "backtested", proposal["backtest_result"])

        return proposal["backtest_result"]

    def check_observation(self, proposal_id: str) -> Dict:
        """
        检查观察期进展

        观察期规则：
        - 观察期：7天
        - 通过条件：模拟盘PnL正向 + Sharpe提升
        """
        pool = self._load_pool()
        proposal = self._find_proposal(proposal_id, pool)

        if not proposal or proposal["status"] != EvolutionStatus.OBSERVATION.value:
            return {"error": "提议不在观察期"}

        obs_start = proposal.get("observation_start")
        if not obs_start:
            return {"error": "观察期未开始"}

        obs_start_ts = datetime.fromisoformat(obs_start).timestamp()
        elapsed_days = (time.time() - obs_start_ts) / 86400
        observation_days = 7

        if elapsed_days >= observation_days:
            return self._finalize_observation(proposal, pool)
        else:
            return {
                "proposal_id": proposal_id,
                "status": "in_observation",
                "elapsed_days": round(elapsed_days, 1),
                "remaining_days": round(observation_days - elapsed_days, 1),
                "title": proposal["title"],
            }

    def _finalize_observation(self, proposal: Dict, pool: Dict) -> Dict:
        """完成观察期评估"""
        baseline_params = self._get_baseline_params()
        improved_params = {**baseline_params, **proposal["strategy_params"]}

        coins = proposal.get("backtest_result", {}).get("coins_tested", ["BTC", "ETH"])
        all_results = []
        for coin in coins:
            result = self.backtest_engine.compare_strategies(
                coin, baseline_params, improved_params
            )
            all_results.append(result)

        avg_improvement = self._calc_avg_improvement(all_results)

        proposal["observation_end"] = self._now_iso()
        proposal["observation_result"] = {
            "avg_improvement": avg_improvement,
            "final_verdict": "passed" if avg_improvement["total_pnl_change_pct"] > 1 else "failed",
        }

        if avg_improvement["total_pnl_change_pct"] > 1 and avg_improvement["sharpe_change"] >= 0:
            proposal["status"] = EvolutionStatus.ADOPTED.value
            proposal["adopted_at"] = self._now_iso()
            pool["adopted"].append({
                "id": proposal["id"],
                "title": proposal["title"],
                "source": proposal["source"],
                "strategy_params": proposal["strategy_params"],
                "adopted_at": proposal["adopted_at"],
                "backtest_result": proposal.get("backtest_result"),
                "observation_result": proposal.get("observation_result"),
            })
            print(f"[进化] ✅ 提议已采纳: {proposal['title']}")
        else:
            proposal["status"] = EvolutionStatus.REJECTED.value
            proposal["rejected_at"] = self._now_iso()
            proposal["rejection_reason"] = f"观察期未通过: PnL变化{avg_improvement['total_pnl_change_pct']:.2f}%"
            print(f"[进化] ❌ 观察期未通过: {proposal['title']}")

        self._save_pool(pool)
        self._record_history(proposal["id"], "observation_finalized", proposal["observation_result"])

        return proposal["observation_result"]

    def get_adopted_params(self) -> Dict:
        """获取所有已采纳的参数变更"""
        pool = self._load_pool()
        params = {}
        for adopted in pool.get("adopted", []):
            params.update(adopted.get("strategy_params", {}))
        return params

    def get_pending_proposals(self) -> List[Dict]:
        """获取待处理的提议"""
        pool = self._load_pool()
        return [
            p for p in pool.get("proposals", [])
            if p["status"] in (EvolutionStatus.PROPOSED.value, EvolutionStatus.BACKTESTING.value)
        ]

    def get_observation_proposals(self) -> List[Dict]:
        """获取观察期中的提议"""
        pool = self._load_pool()
        return [
            p for p in pool.get("proposals", [])
            if p["status"] == EvolutionStatus.OBSERVATION.value
        ]

    def get_evolution_stats(self) -> Dict:
        """获取进化统计"""
        pool = self._load_pool()
        history = self._load_history()

        proposals = pool.get("proposals", [])
        adopted = pool.get("adopted", [])

        by_source = {}
        for p in proposals:
            src = p.get("source", "unknown")
            if src not in by_source:
                by_source[src] = {"total": 0, "adopted": 0, "rejected": 0}
            by_source[src]["total"] += 1
            if p["status"] == EvolutionStatus.ADOPTED.value:
                by_source[src]["adopted"] += 1
            elif p["status"] == EvolutionStatus.REJECTED.value:
                by_source[src]["rejected"] += 1

        return {
            "total_proposals": len(proposals),
            "adopted_count": len(adopted),
            "rejected_count": sum(1 for p in proposals if p["status"] == EvolutionStatus.REJECTED.value),
            "in_observation": sum(1 for p in proposals if p["status"] == EvolutionStatus.OBSERVATION.value),
            "adoption_rate": round(len(adopted) / len(proposals), 2) if proposals else 0,
            "by_source": by_source,
            "history_count": len(history.get("history", [])),
        }

    def _find_proposal(self, proposal_id: str, pool: Dict) -> Optional[Dict]:
        for p in pool.get("proposals", []):
            if p["id"] == proposal_id:
                return p
        return None

    def _get_baseline_params(self) -> Dict:
        """获取基线策略参数"""
        return {
            "momentum_threshold": 0.02,
            "volume_threshold": 1.2,
            "rsi_oversold": 40,
            "rsi_overbought": 60,
            "stop_loss_pct": 0.04,
            "take_profit_pct": 0.08,
            "use_ema_cross": True,
        }

    def _calc_avg_improvement(self, results: List[Dict]) -> Dict:
        """计算平均改进幅度"""
        if not results:
            return {
                "win_rate_change": 0,
                "profit_factor_change": 0,
                "total_pnl_change_pct": 0,
                "max_drawdown_change_pct": 0,
                "sharpe_change": 0,
                "trade_count_change": 0,
            }

        improvements = [r.get("improvement", {}) for r in results]
        keys = [
            "win_rate_change",
            "profit_factor_change",
            "total_pnl_change_pct",
            "max_drawdown_change_pct",
            "sharpe_change",
            "trade_count_change",
        ]

        avg = {}
        for key in keys:
            values = [imp.get(key, 0) for imp in improvements]
            avg[key] = round(sum(values) / len(values), 4)

        return avg

    def _record_history(self, proposal_id: str, action: str, details: Dict):
        """记录进化历史"""
        history = self._load_history()
        history["history"].append({
            "proposal_id": proposal_id,
            "action": action,
            "timestamp": self._now_iso(),
            "details": details,
        })
        if len(history["history"]) > 500:
            history["history"] = history["history"][-500:]
        self._save_history(history)

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()
