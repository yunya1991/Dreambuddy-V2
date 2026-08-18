"""
CBR (Case-Based Reasoning) 案例检索引擎

基于 CBR 经典 4R 循环（Retrieve → Reuse → Revise → Retain），
参考 cbrkit (ICCBR 2024 Best Student Paper) 的模块化设计。

核心能力：
- 从 L4 历史案例库检索相似市态下的案例
- 复用成功案例的策略参数，规避失败案例的陷阱
- 根据当前市态和风险预算修正策略
- 新交易完成后自动保留到案例库
"""

import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import sys

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.memory_l4.cbr_similarity import (
    DEFAULT_CASE_SIM_WEIGHTS,
    build_default_case_retriever,
)
from scripts.memory_l4.paths import memory_l4_cases_dir, workbuddy_dir


# ─────────────────────────────────────────────
# 数据模型
# ─────────────────────────────────────────────

@dataclass
class CBRCase:
    """CBR 案例表示（从 TradeCase v0.3 转换）。"""
    case_id: str
    inst_id: Optional[str] = None
    regime: Optional[str] = None           # 市态，如 "recovery|sprout"
    decision: Optional[str] = None         # long / short
    confidence: float = 0.0
    volatility: float = 0.0
    entry_price: float = 0.0
    exit_price: Optional[float] = None
    pnl_pct: Optional[float] = None
    pnl_usdt: Optional[float] = None
    drawdown: float = 0.0
    leverage: float = 1.0
    quadrant: Dict[str, float] = field(default_factory=dict)
    evidence_chain: Dict[str, List[Dict]] = field(default_factory=dict)
    lessons: List[str] = field(default_factory=list)
    mistakes: List[Dict] = field(default_factory=list)
    successes: List[Dict] = field(default_factory=list)
    is_profit: bool = False
    tags: List[str] = field(default_factory=list)
    system_source: Optional[str] = None
    timestamp: Optional[str] = None
    # 原始 case 字典（保留完整信息）
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def to_feature_dict(self) -> Dict[str, Any]:
        """转换为特征字典，用于相似度计算。"""
        return {
            "inst_id": self.inst_id,
            "regime": self.regime,
            "decision": self.decision,
            "confidence": self.confidence,
            "volatility": self.volatility,
            "entry_price": self.entry_price,
            "quadrant": self.quadrant,
            "evidence_chain": self.evidence_chain,
            "pnl_pct": self.pnl_pct or 0.0,
        }


@dataclass
class CBRQuery:
    """CBR 查询（当前市场状态）。"""
    inst_id: Optional[str] = None
    regime: Optional[str] = None
    decision: Optional[str] = None         # 拟议方向
    confidence: float = 0.0                # BCRM 输出置信度
    volatility: float = 0.0                # 当前 ATR/波动率
    entry_price: float = 0.0               # 当前价格
    quadrant: Dict[str, float] = field(default_factory=dict)
    evidence_chain: Dict[str, List[Dict]] = field(default_factory=dict)
    # 风险预算
    max_drawdown: float = 0.05
    risk_budget: float = 0.02

    def to_feature_dict(self) -> Dict[str, Any]:
        return {
            "inst_id": self.inst_id,
            "regime": self.regime,
            "decision": self.decision,
            "confidence": self.confidence,
            "volatility": self.volatility,
            "entry_price": self.entry_price,
            "quadrant": self.quadrant,
            "evidence_chain": self.evidence_chain,
        }


@dataclass
class RetrievedCase:
    """检索结果：案例 + 相似度分数。"""
    case: CBRCase
    similarity: float
    rank: int = 0


@dataclass
class ReuseResult:
    """复用结果：从相似案例聚合的策略建议。"""
    suggested_leverage: float
    suggested_position_pct: float
    suggested_sl_atr: float
    suggested_tp_atr: float
    suggested_hold_bars: int
    confidence_boost: float          # 基于历史成功率的置信度调整
    profit_rate: float               # 相似案例中盈利比例
    avg_pnl: float                   # 相似案例平均收益
    risk_notes: List[str]            # 风险提示（从失败案例提取）


@dataclass
class ReviseResult:
    """修正结果：根据当前市态和风险调整后的最终策略。"""
    final_leverage: float
    final_position_pct: float
    final_sl_atr: float
    final_tp_atr: float
    final_hold_bars: int
    final_confidence: float
    revision_notes: List[str]


@dataclass
class CBRCycleResult:
    """完整的 CBR 循环结果。"""
    query: CBRQuery
    retrieved: List[RetrievedCase]
    reuse: ReuseResult
    revise: ReviseResult
    duration_ms: float


# ─────────────────────────────────────────────
# 案例库管理
# ─────────────────────────────────────────────

class CaseBase:
    """CBR 案例库：从 L4 cases 加载并管理。"""

    def __init__(self, cases_dir: Optional[Path] = None):
        self.cases_dir = cases_dir or memory_l4_cases_dir()
        self.cases: List[CBRCase] = []
        self._index: Optional[Dict[str, Any]] = None

    def load(self) -> "CaseBase":
        """从 L4 cases 目录加载所有案例。"""
        self.cases = []
        if not self.cases_dir.exists():
            return self
        for p in sorted(self.cases_dir.glob("*.json")):
            if not p.is_file():
                continue
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                case = self._trade_case_to_cbr(raw)
                self.cases.append(case)
            except Exception:
                continue
        return self

    def load_from_index(self, index_path: Optional[Path] = None) -> "CaseBase":
        """从索引文件加载（复用 index_builder 的特征）。"""
        if index_path is None:
            index_path = workbuddy_dir() / "memory_l4" / "index" / "latest.json"
        if not index_path.exists():
            return self.load()
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
            case_features = data.get("case_features", {})
            self.cases = []
            for cid, feats in case_features.items():
                case = self._index_features_to_cbr(cid, feats)
                self.cases.append(case)
        except Exception:
            return self.load()
        return self

    @staticmethod
    def _trade_case_to_cbr(raw: Dict[str, Any]) -> CBRCase:
        """TradeCase v0.3 → CBRCase。"""
        do = raw.get("decision_outcome") or {}
        env = raw.get("environment_snapshot") or {}
        q = raw.get("quadrant") or {}
        ev = q.get("evidence") or {} if isinstance(q, dict) else {}
        review = raw.get("review") or {}

        return CBRCase(
            case_id=str(raw.get("case_id") or ""),
            inst_id=raw.get("inst_id"),
            regime=env.get("regime"),
            decision=raw.get("decision"),
            confidence=raw.get("confidence") or 0.0,
            volatility=env.get("volatility") or 0.0,
            entry_price=do.get("entry_price") or 0.0,
            exit_price=do.get("exit_price"),
            pnl_pct=do.get("pnl_pct"),
            pnl_usdt=do.get("pnl_usdt"),
            drawdown=do.get("drawdown") or 0.0,
            leverage=do.get("leverage") or 1.0,
            quadrant={"x": q.get("x", 0), "y": q.get("y", 0)} if isinstance(q, dict) else {},
            evidence_chain=raw.get("evidence_chain") or {},
            lessons=[str(x) for x in (review.get("lessons") or []) if str(x)],
            mistakes=review.get("mistakes") or [],
            successes=review.get("successes") or [],
            is_profit=bool(do.get("pnl_pct") and do.get("pnl_pct") > 0),
            tags=[str(x) for x in (raw.get("tags") or []) if str(x)],
            system_source=raw.get("system_source"),
            timestamp=raw.get("timestamp"),
            raw=raw,
        )

    @staticmethod
    def _index_features_to_cbr(cid: str, feats: Dict[str, Any]) -> CBRCase:
        """index_builder 特征 → CBRCase。"""
        do = feats.get("decision_outcome") or {}
        qf = feats.get("quadrant_features") or {}
        return CBRCase(
            case_id=cid,
            inst_id=feats.get("inst_id"),
            regime=feats.get("regime"),
            decision=feats.get("decision"),
            confidence=feats.get("total_score") or 0.0,
            volatility=do.get("drawdown") or 0.0,  # 近似
            entry_price=0.0,
            pnl_pct=do.get("pnl_pct"),
            is_profit=do.get("is_profit", False),
            quadrant={"x": qf.get("x", 0), "y": qf.get("y", 0)},
            evidence_chain={},  # 索引中未保留完整 evidence_chain
            tags=feats.get("tags") or [],
            system_source=feats.get("matched_strategy"),
            raw={},
        )

    def filter(self, **kwargs) -> "CaseBase":
        """按条件过滤案例库（如 inst_id="BTC", is_profit=True）。"""
        filtered = []
        for c in self.cases:
            match = True
            for key, val in kwargs.items():
                if getattr(c, key, None) != val:
                    match = False
                    break
            if match:
                filtered.append(c)
        cb = CaseBase(self.cases_dir)
        cb.cases = filtered
        return cb

    def split_by_outcome(self) -> Tuple[List[CBRCase], List[CBRCase]]:
        """按盈亏分为 (盈利案例, 亏损案例)。"""
        profits = [c for c in self.cases if c.is_profit]
        losses = [c for c in self.cases if not c.is_profit]
        return profits, losses

    def __len__(self) -> int:
        return len(self.cases)


# ─────────────────────────────────────────────
# CBR 引擎核心
# ─────────────────────────────────────────────

class CBREngine:
    """CBR 案例检索引擎：实现 4R 循环。"""

    def __init__(
        self,
        case_base: Optional[CaseBase] = None,
        top_k: int = 5,
        similarity_threshold: float = 0.1,
        use_sharded: bool = False,
    ):
        self.case_base = case_base or CaseBase()
        self.top_k = top_k
        self.similarity_threshold = similarity_threshold
        self.retriever = build_default_case_retriever()
        self.use_sharded = use_sharded
        self._sharded_retriever = None
        self._sharded_base = None

    def load(self, use_index: bool = True) -> "CBREngine":
        """加载案例库。"""
        if use_index:
            self.case_base.load_from_index()
        else:
            self.case_base.load()

        if self.use_sharded:
            from scripts.memory_l4.cbr_sharded_retriever import (
                ShardedCaseBase,
                ShardedRetriever,
            )

            self._sharded_base = ShardedCaseBase(self.case_base.cases)
            self._sharded_retriever = ShardedRetriever(
                sharded_base=self._sharded_base,
                retriever=self.retriever,
                top_k=self.top_k,
                similarity_threshold=self.similarity_threshold,
            )

        return self

    # ── Retrieve ──────────────────────────────

    def retrieve(self, query: CBRQuery) -> List[RetrievedCase]:
        """检索最相似的 Top-K 案例。"""
        if self._sharded_retriever:
            return self._sharded_retriever.retrieve(query)

        qdict = query.to_feature_dict()
        scored: List[Tuple[CBRCase, float]] = []

        for case in self.case_base.cases:
            cdict = case.to_feature_dict()
            sim = self.retriever(qdict, cdict)
            if sim >= self.similarity_threshold:
                scored.append((case, sim))

        scored.sort(key=lambda x: x[1], reverse=True)

        results = []
        for rank, (case, sim) in enumerate(scored[: self.top_k], start=1):
            results.append(RetrievedCase(case=case, similarity=sim, rank=rank))

        return results

    # ── Reuse ─────────────────────────────────

    def reuse(self, retrieved: List[RetrievedCase]) -> ReuseResult:
        """从检索到的案例复用策略参数。

        逻辑：
        1. 分离盈利案例和亏损案例
        2. 盈利案例：加权平均其策略参数（权重 = 相似度）
        3. 亏损案例：提取风险警示，用于规避风险
        """
        if not retrieved:
            return self._default_reuse_result()

        profit_cases = [r for r in retrieved if r.case.is_profit]
        loss_cases = [r for r in retrieved if not r.case.is_profit]

        # 盈利案例参数聚合
        if profit_cases:
            weights = [r.similarity for r in profit_cases]
            total_w = sum(weights)

            def _wavg(key: str, default: float) -> float:
                vals = []
                for r in profit_cases:
                    v = getattr(r.case, key, None)
                    if v is not None:
                        vals.append((v, r.similarity))
                if not vals:
                    return default
                return sum(v * w for v, w in vals) / sum(w for _, w in vals)

            suggested_leverage = _wavg("leverage", 3.0)
            # position_pct 从 raw 中提取
            position_pcts = []
            for r in profit_cases:
                raw = r.case.raw
                pct = raw.get("position_pct") if raw else None
                if pct is None:
                    pct = (raw.get("execution") or {}).get("position_pct") if raw else None
                if pct is not None:
                    position_pcts.append((pct, r.similarity))
            suggested_position_pct = (
                sum(v * w for v, w in position_pcts) / sum(w for _, w in position_pcts)
                if position_pcts else 0.1
            )

            # SL/TP ATR 倍数（从 lessons 中推断或默认值）
            suggested_sl_atr = 2.0
            suggested_tp_atr = 3.0
            suggested_hold_bars = 60

            profit_rate = len(profit_cases) / len(retrieved)
            avg_pnl = _wavg("pnl_pct", 0.0)
            # 置信度提升：历史成功率越高，提升越大
            confidence_boost = min(profit_rate * 0.15, 0.10)
        else:
            suggested_leverage = 1.0
            suggested_position_pct = 0.05
            suggested_sl_atr = 2.5
            suggested_tp_atr = 2.5
            suggested_hold_bars = 40
            profit_rate = 0.0
            avg_pnl = 0.0
            confidence_boost = -0.05  # 无成功案例，降低置信度

        # 从亏损案例提取风险警示
        risk_notes: List[str] = []
        for r in loss_cases:
            case = r.case
            for m in case.mistakes:
                note = m.get("description") or m.get("category")
                if note and note not in risk_notes:
                    risk_notes.append(str(note))
            for lesson in case.lessons:
                if "止损" in lesson or "风控" in lesson or "杠杆" in lesson:
                    if lesson not in risk_notes:
                        risk_notes.append(lesson)

        return ReuseResult(
            suggested_leverage=round(suggested_leverage, 2),
            suggested_position_pct=round(suggested_position_pct, 4),
            suggested_sl_atr=round(suggested_sl_atr, 2),
            suggested_tp_atr=round(suggested_tp_atr, 2),
            suggested_hold_bars=suggested_hold_bars,
            confidence_boost=round(confidence_boost, 4),
            profit_rate=round(profit_rate, 3),
            avg_pnl=round(avg_pnl, 4),
            risk_notes=risk_notes[:5],
        )

    @staticmethod
    def _default_reuse_result() -> ReuseResult:
        return ReuseResult(
            suggested_leverage=3.0,
            suggested_position_pct=0.1,
            suggested_sl_atr=2.0,
            suggested_tp_atr=3.0,
            suggested_hold_bars=60,
            confidence_boost=0.0,
            profit_rate=0.0,
            avg_pnl=0.0,
            risk_notes=["案例库为空，使用默认参数"],
        )

    # ── Revise ────────────────────────────────

    def revise(self, query: CBRQuery, reuse: ReuseResult) -> ReviseResult:
        """根据当前市态和风险预算修正策略参数。

        修正规则：
        1. 波动率修正：高波动 → 降低杠杆、放宽止损
        2. 风险预算修正：风险预算紧 → 降低仓位
        3. 市态修正：不同市态有预设的仓位因子
        4. 回撤修正：历史回撤大 → 收紧止损
        """
        notes: List[str] = []
        lev = reuse.suggested_leverage
        pos_pct = reuse.suggested_position_pct
        sl = reuse.suggested_sl_atr
        tp = reuse.suggested_tp_atr
        hold = reuse.suggested_hold_bars
        conf_boost = reuse.confidence_boost

        # 1. 波动率修正
        vol = query.volatility
        if vol > 0.3:
            lev *= 0.7
            sl *= 1.3
            notes.append(f"高波动率({vol:.2f})→杠杆降至{lev:.1f}x，止损放宽至{sl:.1f}x ATR")
        elif vol < 0.05:
            lev *= 1.1
            notes.append(f"低波动率({vol:.2f})→杠杆微升至{lev:.1f}x")

        # 2. 风险预算修正
        risk = query.risk_budget
        if risk < 0.01:
            pos_pct *= 0.5
            notes.append(f"风险预算紧张({risk:.2%})→仓位减半至{pos_pct:.2%}")
        elif risk > 0.05:
            pos_pct *= 1.2
            notes.append(f"风险预算充裕({risk:.2%})→仓位提升至{pos_pct:.2%}")

        # 3. 市态修正（参考 BCRM 2.0 市态表）
        regime = query.regime or ""
        if "FOMO" in regime or "RALLY" in regime:
            lev *= 0.8
            tp *= 1.5
            hold = int(hold * 0.7)
            notes.append("FOMO 市态→降低杠杆、提高止盈、缩短持仓")
        elif "CONSOLIDATION" in regime or "RANGE" in regime:
            lev *= 0.6
            pos_pct *= 0.8
            tp *= 0.7
            sl *= 1.2
            notes.append("盘整市态→降低杠杆和仓位，收紧止盈")
        elif "BREAKOUT" in regime:
            lev *= 1.1
            tp *= 1.3
            notes.append("突破市态→提高杠杆和止盈")

        # 4. 最大回撤修正
        if query.max_drawdown < 0.03:
            sl *= 0.8
            notes.append(f"严格回撤限制({query.max_drawdown:.1%})→收紧止损")

        # 边界限制
        lev = max(1.0, min(lev, 10.0))
        pos_pct = max(0.01, min(pos_pct, 0.5))
        sl = max(0.5, min(sl, 5.0))
        tp = max(1.0, min(tp, 6.0))
        hold = max(10, min(hold, 120))

        return ReviseResult(
            final_leverage=round(lev, 1),
            final_position_pct=round(pos_pct, 4),
            final_sl_atr=round(sl, 2),
            final_tp_atr=round(tp, 2),
            final_hold_bars=hold,
            final_confidence=round(min(1.0, max(0.0, query.confidence + conf_boost)), 4),
            revision_notes=notes,
        )

    # ── Retain ────────────────────────────────

    def retain(self, new_case: CBRCase) -> None:
        """将新案例保留到案例库（通过 L4 pipeline 自动处理）。

        注意：实际 retention 由 L4 pipeline 的 M0→M4 完成。
        此处仅将新案例追加到内存中的案例库，以便实时检索。
        """
        self.case_base.cases.append(new_case)

    # ── Full Cycle ────────────────────────────

    def cycle(self, query: CBRQuery) -> CBRCycleResult:
        """执行完整的 CBR 4R 循环。"""
        import time
        start = time.perf_counter()

        retrieved = self.retrieve(query)
        reuse = self.reuse(retrieved)
        revise = self.revise(query, reuse)

        duration_ms = (time.perf_counter() - start) * 1000

        return CBRCycleResult(
            query=query,
            retrieved=retrieved,
            reuse=reuse,
            revise=revise,
            duration_ms=round(duration_ms, 2),
        )

    # ── 辅助方法 ──────────────────────────────

    def search_similar(
        self,
        inst_id: Optional[str] = None,
        regime: Optional[str] = None,
        decision: Optional[str] = None,
        top_k: int = 5,
    ) -> List[RetrievedCase]:
        """便捷方法：按条件构造查询并检索。"""
        query = CBRQuery(inst_id=inst_id, regime=regime, decision=decision)
        return self.retrieve(query)

    def get_case_stats(self) -> Dict[str, Any]:
        """案例库统计信息。"""
        total = len(self.case_base.cases)
        profits, losses = self.case_base.split_by_outcome()
        regimes: Dict[str, int] = {}
        for c in self.case_base.cases:
            r = c.regime or "UNKNOWN"
            regimes[r] = regimes.get(r, 0) + 1

        return {
            "total_cases": total,
            "profit_cases": len(profits),
            "loss_cases": len(losses),
            "win_rate": round(len(profits) / total, 3) if total > 0 else 0.0,
            "regime_distribution": regimes,
        }


# ─────────────────────────────────────────────
# CLI / 测试入口
# ─────────────────────────────────────────────

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="CBR 案例检索引擎")
    parser.add_argument("--inst", default="BTC-USDT-SWAP", help="币种")
    parser.add_argument("--regime", default="recovery|sprout", help="市态")
    parser.add_argument("--decision", default="long", help="方向")
    parser.add_argument("--confidence", type=float, default=0.85, help="置信度")
    parser.add_argument("--volatility", type=float, default=0.15, help="波动率")
    parser.add_argument("--price", type=float, default=65000.0, help="当前价格")
    parser.add_argument("--top-k", type=int, default=5, help="检索数量")
    parser.add_argument("--threshold", type=float, default=0.3, help="相似度阈值")
    args = parser.parse_args()

    engine = CBREngine(top_k=args.top_k, similarity_threshold=args.threshold)
    engine.load(use_index=True)

    print(f"案例库统计: {engine.get_case_stats()}")
    print(f"---")

    query = CBRQuery(
        inst_id=args.inst,
        regime=args.regime,
        decision=args.decision,
        confidence=args.confidence,
        volatility=args.volatility,
        entry_price=args.price,
    )

    result = engine.cycle(query)

    print(f"检索耗时: {result.duration_ms}ms")
    print(f"检索到 {len(result.retrieved)} 个相似案例:")
    for r in result.retrieved:
        print(f"  #{r.rank} {r.case.case_id} sim={r.similarity:.3f} "
              f"pnl={r.case.pnl_pct} regime={r.case.regime}")

    print(f"---")
    print(f"复用结果:")
    print(f"  建议杠杆: {result.reuse.suggested_leverage}x")
    print(f"  建议仓位: {result.reuse.suggested_position_pct:.2%}")
    print(f"  建议止损: {result.reuse.suggested_sl_atr}x ATR")
    print(f"  建议止盈: {result.reuse.suggested_tp_atr}x ATR")
    print(f"  历史胜率: {result.reuse.profit_rate:.1%}")
    print(f"  平均收益: {result.reuse.avg_pnl:.2%}")
    print(f"  置信度调整: {result.reuse.confidence_boost:+.2%}")
    if result.reuse.risk_notes:
        print(f"  风险提示: {result.reuse.risk_notes}")

    print(f"---")
    print(f"修正结果:")
    print(f"  最终杠杆: {result.revise.final_leverage}x")
    print(f"  最终仓位: {result.revise.final_position_pct:.2%}")
    print(f"  最终止损: {result.revise.final_sl_atr}x ATR")
    print(f"  最终止盈: {result.revise.final_tp_atr}x ATR")
    print(f"  最终持仓: {result.revise.final_hold_bars} bars")
    print(f"  最终置信度: {result.revise.final_confidence}")
    if result.revise.revision_notes:
        print(f"  修正说明: {result.revise.revision_notes}")


if __name__ == "__main__":
    main()
