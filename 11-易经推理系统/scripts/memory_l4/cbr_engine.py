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


# ================================================================
# Phase1: CBRJsonlStore（JSONL 双时点建库存储，G3 文件锁 + fail-open）
#
# 职责：仅负责 JSONL 文件的半条 entry_snapshot 写入 + exit 回填，与原
#       CBREngine（4R 检索复用）职责完全解耦。
# 存储：runtime/cbr_cases_v03.jsonl（每行一条完整 JSON，UTF-8，schema=v0.3）
# 配对方式：开仓写 semi_entry（exit 全占位 null）；离场按 case_id 全量读→
#           内存更新→全量重写（atomic via temp + os.replace）
# Phase2 迁移：migrate_jsonl_to_sqlite() 空壳已预留，抛 NotImplementedError
# 约束：G1（enable=False 时零副作用）/ G2（任何异常返回 False 不 raise）/
#       G3（flock LOCK_EX|LOCK_NB 非阻塞，0.1s 超时→failopen）/
#       G6（缺 case_id 静默 False，不抛 KeyError）
# ================================================================
import fcntl as _fcntl
import tempfile as _tempfile
import os as _os
import time as _time

_JSONL_LOCK_TIMEOUT_S = 0.1
_JSONL_SCHEMA_VERSION = "v0.3"


# ── §2.3.1 五维特征 17 键规范化（Spec §2.3.1 表，用于 TDD C7 逐字对齐）──
CBR_CANONICAL_5D_KEYS = {
    # momentum 5 项
    "momentum": ["rsi_14", "macd_hist", "roc_5d", "roc_20d", "hexagram_confidence"],
    # ma_position 5 项
    "ma_position": ["dist_sma20_pct", "dist_sma50_pct", "dist_sma200_pct",
                    "ma20_50_gap_pct", "triple_ma_order"],
    # volatility 3 项
    "volatility": ["atr14_norm_pct", "atr14_20d_quantile", "bollinger_width_pct"],
    # volume 2 项
    "volume": ["vol_20d_quantile", "vol_ma20_ratio"],
    # hexagram_meta 2 项
    "hexagram_meta": ["hexagram_risk_level", "conf_decision_align"],
}


_TAG_MULTIPLIERS = {
    "MANUAL_CLASSIC": 1.05,
    "HIGH_WIN": 1.02,
    "HIGH_LOSS": 1.02,
    "NORMAL": 1.0,
}
_BASELINE_DECAY_HALF_LIFE_DAYS = 90.0
_THETA_DEFAULT = 0.80
_GAMMA_DEFAULT = 0.20


class CBRJsonlStore:
    """Phase1 CBR JSONL 双时点建库存储。Phase2 追加 retrieve_similar 接口。"""

    def __init__(self, runtime_dir: Optional[Path] = None, enable: bool = False):
        self.enable = bool(enable)
        if runtime_dir is None:
            runtime_dir = Path(__file__).resolve().parent / "runtime"
        self._runtime_dir: Path = runtime_dir
        self._jsonl_path: Path = self._runtime_dir / "cbr_cases_v03.jsonl"
        self._params_path: Path = self._runtime_dir / "cbr_baseline_params.json"
        # ── CBR v3.0 §2.2：θ_match*/γ_max* 动态加载（文件不存在→默认 0.80/0.20）──
        self.theta_match_star: float = _THETA_DEFAULT
        self.gamma_max_star: float = _GAMMA_DEFAULT
        try:
            if self._params_path.exists():
                _raw = json.loads(self._params_path.read_text(encoding="utf-8"))
                if isinstance(_raw.get("theta_match_star"), (int, float)):
                    self.theta_match_star = float(_raw["theta_match_star"])
                if isinstance(_raw.get("gamma_max_star"), (int, float)):
                    self.gamma_max_star = float(_raw["gamma_max_star"])
        except Exception:  # noqa: BLE001 / fail-open：任何异常回退默认
            self.theta_match_star = _THETA_DEFAULT
            self.gamma_max_star = _GAMMA_DEFAULT
        # C1 / C8: auto mkdir；异常 → force disable（fail-open 字节等价）
        if self.enable:
            try:
                self._runtime_dir.mkdir(parents=True, exist_ok=True)
                if not self._jsonl_path.exists():
                    self._jsonl_path.touch(mode=0o644, exist_ok=True)
            except Exception as _e:  # noqa: BLE001
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    f"[CBRJsonlStore] runtime init failed, force-disable: {_e}"
                )
                self.enable = False

    # ──────── internal helpers（G3 lock）────────
    def _lock_ex_nb(self, fd: int) -> bool:
        """Non-blocking exclusive flock. True=acquired, False=contention failopen."""
        try:
            _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
            return True
        except (BlockingIOError, OSError):
            return False

    @staticmethod
    def _unlock(fd: int) -> None:
        try:
            _fcntl.flock(fd, _fcntl.LOCK_UN)
        except OSError:
            pass

    # ──────── public Phase1 APIs ────────
    def append_entry_semi(self, case: Dict[str, Any]) -> bool:
        """Append half-entry (exit_* = null placeholders). Returns True on persistence."""
        if not self.enable:
            return False
        try:
            cid = str(case["case_id"])
            record: Dict[str, Any] = {
                "schema": _JSONL_SCHEMA_VERSION,
                "case_id": cid,
                "symbol": str(case.get("symbol", "")),
                "asset_class": str(case.get("asset_class", "")),
                "entry_snapshot": case["entry_snapshot"],
                "exit_snapshot": None,
                "pnl_pct": None,
                "pnl_usdt": None,
                "is_profit": None,
                "create_ts": int(case.get("create_ts") or int(_time.time() * 1000)),
                "close_ts": None,
            }
            line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
            with open(self._jsonl_path, "a", encoding="utf-8") as f:
                if not self._lock_ex_nb(f.fileno()):
                    # G3: contention, fail this round（avoid blocking hot path）
                    return False
                try:
                    f.write(line)
                    f.flush()
                    _os.fsync(f.fileno())
                finally:
                    self._unlock(f.fileno())
            return True
        except Exception:  # noqa: BLE001 / G2: never raise to caller
            return False

    def finalize_by_case_id(self, case_id: str, exit_snapshot: Dict[str, Any],
                            pnl_pct: Optional[float], pnl_usdt: Optional[float],
                            is_profit: Optional[bool]) -> bool:
        """Finalize a semi entry by case_id (read → update → atomic rewrite).

        Missing case_id → silently False (G6). Idempotent on repeated identical calls.
        """
        if not self.enable or not case_id:
            return False
        try:
            with open(self._jsonl_path, "r+", encoding="utf-8") as f:
                if not self._lock_ex_nb(f.fileno()):
                    return False
                try:
                    raw_text = f.read()
                    raw_lines = [ln for ln in raw_text.split("\n") if ln]
                    updated = False
                    new_lines: list[str] = []
                    for ln in raw_lines:
                        try:
                            rec = json.loads(ln)
                        except json.JSONDecodeError:
                            # C6: tolerate corrupt line, skip as-is（don't break others）
                            new_lines.append(ln)
                            continue
                        if rec.get("case_id") == case_id:
                            rec["exit_snapshot"] = exit_snapshot
                            rec["pnl_pct"] = pnl_pct
                            rec["pnl_usdt"] = pnl_usdt
                            rec["is_profit"] = bool(is_profit) if is_profit is not None else None
                            rec["close_ts"] = int(_time.time() * 1000)
                            updated = True
                        new_lines.append(json.dumps(rec, ensure_ascii=False, sort_keys=True))
                    if not updated:
                        # G6: missing case_id → silent skip, no crash, no raise
                        return False
                    # atomic rewrite（temp file + fsync + os.replace）
                    with _tempfile.NamedTemporaryFile(
                            "w", encoding="utf-8", dir=str(self._runtime_dir),
                            delete=False, suffix=".jsonl.tmp") as tf:
                        tf.write("\n".join(new_lines) + "\n")
                        tf.flush()
                        _os.fsync(tf.fileno())
                        tmp_path = tf.name
                    try:
                        _os.replace(tmp_path, str(self._jsonl_path))
                    except OSError:
                        # cleanup temp on failure
                        try:
                            _os.unlink(tmp_path)
                        except OSError:
                            pass
                        return False
                    return True
                finally:
                    self._unlock(f.fileno())
        except Exception:  # noqa: BLE001 / G2: any anomaly → false never raise
            return False

    # ──────── CBR v3.0 §2：_rank_score（tag 加成 + 90d 半衰时间衰减）────────
    def _rank_score(self, case: Dict[str, Any], raw_match: float) -> float:
        """Sort-only rank score（不修改真实相似度 raw_match，仅用于排序）。

        rank_score = raw_match × tag_mult × age_decay
        - tag_mult：MANUAL_CLASSIC=1.05 / HIGH_WIN|HIGH_LOSS=1.02 / NORMAL=1.00
        - age_decay：P5=90天半衰 = exp(-age_days / 90)，age_days基于case.entry_ts
        """
        tag = str(case.get("tag", "NORMAL"))
        tag_mult = _TAG_MULTIPLIERS.get(tag, 1.0)
        # age_days：entry_ts 可能是 datetime / int(ms timestamp) / 缺省（=0天）
        entry_ts = case.get("entry_ts")
        age_days = 0.0
        if isinstance(entry_ts, datetime):
            age_days = max(0.0, (datetime.now() - entry_ts).total_seconds() / 86400.0)
        elif isinstance(entry_ts, (int, float)):
            try:
                ts_sec = entry_ts / 1000.0 if entry_ts > 1e12 else entry_ts
                age_days = max(0.0, (datetime.now().timestamp() - ts_sec) / 86400.0)
            except Exception:  # noqa: BLE001
                age_days = 0.0
        age_decay = math.exp(-age_days / _BASELINE_DECAY_HALF_LIFE_DAYS)
        return float(raw_match) * tag_mult * age_decay

    # ──────── CBR v3.0 §2.5：predict_topk（θ*门槛命中 + HIGH_LOSS 负对称 boost）────────
    def predict_topk(self, top_cases: List[Dict[str, Any]],
                     raw_scores: Dict[str, float]) -> Dict[str, Any]:
        """对 topk 候选计算最终排序与 match_boost（w_B 合成项）。

        返回结构：
        {
            "top1_case_id": str,
            "top1_tag": str,
            "top1_raw_score": float,
            "ranked": [(case_id, rank_score, raw_score, tag, age_decay)],
            "match_boost": float,     # ∈ [-γ_max*, +γ_max*]，HIGH_LOSS 负对称
            "match_boost_note": str,  # 人类可读解释
        }

        match_boost 规则：
          仅当 top1 的 raw_score ≥ theta_match_star 时生效（θ*门槛命中）
          HIGH_WIN | MANUAL_CLASSIC → +γ_max* × clip(5×(score-θ*), 0, 1) × age_decay
          HIGH_LOSS                 → −γ_max* × clip(5×(score-θ*), 0, 1) × age_decay
          NORMAL 或未命中 θ*        → 0
        """
        try:
            now = datetime.now()
            ranked: List[Tuple[str, float, float, str, float]] = []
            for case in top_cases:
                cid = str(case.get("case_id", ""))
                raw = float(raw_scores.get(cid, 0.0))
                tag = str(case.get("tag", "NORMAL"))
                # age_decay（与_rank_score同公式，此处单独再算，保证可解释性）
                entry_ts = case.get("entry_ts")
                age_days = 0.0
                if isinstance(entry_ts, datetime):
                    age_days = max(0.0, (now - entry_ts).total_seconds() / 86400.0)
                elif isinstance(entry_ts, (int, float)):
                    try:
                        ts_sec = entry_ts / 1000.0 if entry_ts > 1e12 else entry_ts
                        age_days = max(0.0, (now.timestamp() - ts_sec) / 86400.0)
                    except Exception:  # noqa: BLE001
                        age_days = 0.0
                age_decay = math.exp(-age_days / _BASELINE_DECAY_HALF_LIFE_DAYS)
                rank = self._rank_score(case, raw)
                ranked.append((cid, rank, raw, tag, age_decay))
            # sort by rank_score desc
            ranked.sort(key=lambda x: x[1], reverse=True)
            top1 = ranked[0] if ranked else ("", 0.0, 0.0, "NORMAL", 1.0)
            top1_cid, _, top1_raw, top1_tag, top1_age_decay = top1
            # ── match_boost 计算 ──
            theta = self.theta_match_star
            gamma = self.gamma_max_star
            score_above = max(0.0, top1_raw - theta)
            activation = min(1.0, 5.0 * score_above)  # clip(5*(s-θ),0,1)
            if top1_raw < theta:
                match_boost = 0.0
                note = f"未命中θ*={theta:.2f}（top1={top1_raw:.3f}）"
            elif top1_tag in ("HIGH_WIN", "MANUAL_CLASSIC"):
                match_boost = +gamma * activation * top1_age_decay
                note = (f"正基线命中[{top1_tag}]：+{gamma:.2f} × {activation:.2f}(act) "
                        f"× {top1_age_decay:.2f}(decay) = {match_boost:+.4f}")
            elif top1_tag == "HIGH_LOSS":
                match_boost = -gamma * activation * top1_age_decay
                note = (f"负基线命中[HIGH_LOSS]：-{gamma:.2f} × {activation:.2f}(act) "
                        f"× {top1_age_decay:.2f}(decay) = {match_boost:+.4f}")
            else:
                match_boost = 0.0
                note = f"NORMAL 无加成（命中θ*={theta:.2f}但tag无乘数）"
            return {
                "top1_case_id": top1_cid,
                "top1_tag": top1_tag,
                "top1_raw_score": top1_raw,
                "ranked": ranked,
                "match_boost": float(match_boost),
                "match_boost_note": note,
            }
        except Exception:  # noqa: BLE001 / fail-open
            return {
                "top1_case_id": "",
                "top1_tag": "NORMAL",
                "top1_raw_score": 0.0,
                "ranked": [],
                "match_boost": 0.0,
                "match_boost_note": "fail-open：异常旁路 match_boost=0",
            }

    # ──────── Phase2 reserved shells（not implemented yet）────────
    def retrieve_similar(self, query_vec: Dict[str, float], top_k: int = 5,
                         mu: Optional[Dict[str, float]] = None,
                         sigma: Optional[Dict[str, float]] = None):
        raise NotImplementedError(
            "Phase2: call migrate_jsonl_to_sqlite() OR after sample>=50."
        )

    def migrate_jsonl_to_sqlite(self, sqlite_path: Optional[Path] = None) -> int:
        raise NotImplementedError(
            "Phase2 one-off JSONL→SQLite migration: will be delivered in next plan."
        )

