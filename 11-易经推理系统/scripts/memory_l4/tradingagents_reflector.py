"""TradingAgents Reflector 集成模块

借鉴 TradingAgents 的两阶段复盘机制，增强 L4 Review Engine：
- Phase A: 记录决策（决策时）
- Phase B: 延迟反思（结果已知后）
- 跨案例经验传递
- 多维度分析师视角

参考: https://github.com/TauricResearch/TradingAgents
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ── 配置 ──

# HTML comment: cannot appear in LLM prose output, safe as a hard delimiter
_SEPARATOR = "\n\n<!-- ENTRY_END -->\n\n"

# Precompiled patterns
_DECISION_RE = re.compile(r"DECISION:\n(.*?)(?=\nREFLECTION:|\Z)", re.DOTALL)
_REFLECTION_RE = re.compile(r"REFLECTION:\n(.*?)$", re.DOTALL)


# ── 工具函数 ──

def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _parse_rating(decision_text: str) -> str:
    """从决策文本中提取评级"""
    if "**BUY**" in decision_text or "BUY" in decision_text.upper():
        return "Buy"
    if "**SELL**" in decision_text or "SELL" in decision_text.upper():
        return "Sell"
    if "**HOLD**" in decision_text or "HOLD" in decision_text.upper():
        return "Hold"
    return "Unknown"


def _format_pct(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.2%}"


# ── 核心类 ──

class L4MemoryLog:
    """追加式复盘日志（TradingAgents TradingMemoryLog 的 L4 适配版）"""

    def __init__(self, log_path: Optional[Path] = None, max_entries: Optional[int] = None):
        self._log_path = log_path
        self._max_entries = max_entries
        if log_path:
            log_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Phase A: 记录决策 ──

    def store_decision(
        self,
        case_id: str,
        symbol: str,
        trade_date: str,
        direction: str,
        decision_summary: str,
        evidence_chain: Optional[Dict[str, Any]] = None,
    ) -> None:
        """在交易决策时追加 pending entry"""
        if not self._log_path:
            return

        # Idempotency guard
        if self._log_path.exists():
            raw = self._log_path.read_text(encoding="utf-8")
            for line in raw.splitlines():
                if line.startswith(f"[{trade_date} | {symbol} |") and line.endswith("| pending]"):
                    return

        tag = f"[{trade_date} | {symbol} | {direction} | pending]"
        entry = f"{tag}\n\nCASE_ID: {case_id}\n\nDECISION:\n{decision_summary}{_SEPARATOR}"
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(entry)

    # ── Phase B: 更新结果和反思 ──

    def update_with_outcome(
        self,
        case_id: str,
        symbol: str,
        trade_date: str,
        pnl_pct: float,
        pnl_usdt: float,
        holding_days: int,
        reflection: str,
    ) -> bool:
        """原子更新：替换 pending tag，追加 REFLECTION 和 OUTCOME"""
        if not self._log_path or not self._log_path.exists():
            return False

        text = self._log_path.read_text(encoding="utf-8")
        blocks = text.split(_SEPARATOR)

        pending_prefix = f"[{trade_date} | {symbol} |"
        updated = False
        new_blocks = []

        for block in blocks:
            stripped = block.strip()
            if not stripped:
                new_blocks.append(block)
                continue

            lines = stripped.splitlines()
            tag_line = lines[0].strip()

            if (
                not updated
                and tag_line.startswith(pending_prefix)
                and tag_line.endswith("| pending]")
            ):
                fields = [f.strip() for f in tag_line[1:-1].split("|")]
                direction = fields[2]
                new_tag = (
                    f"[{trade_date} | {symbol} | {direction}"
                    f" | {_format_pct(pnl_pct)} | {pnl_usdt:+.2f} USDT | {holding_days}d]"
                )
                rest = "\n".join(lines[1:])
                new_blocks.append(
                    f"{new_tag}\n\n{rest.lstrip()}\n\n"
                    f"OUTCOME:\n"
                    f"  PnL%: {_format_pct(pnl_pct)}\n"
                    f"  PnL USDT: {pnl_usdt:+.2f}\n"
                    f"  Holding: {holding_days}d\n\n"
                    f"REFLECTION:\n{reflection}"
                )
                updated = True
            else:
                new_blocks.append(block)

        if not updated:
            return False

        new_blocks = self._apply_rotation(new_blocks)
        new_text = _SEPARATOR.join(new_blocks)
        tmp_path = self._log_path.with_suffix(".tmp")
        tmp_path.write_text(new_text, encoding="utf-8")
        tmp_path.replace(self._log_path)
        return True

    # ── 读取历史 ──

    def load_entries(self) -> List[Dict[str, Any]]:
        """解析所有 entry"""
        if not self._log_path or not self._log_path.exists():
            return []

        text = self._log_path.read_text(encoding="utf-8")
        raw_entries = [e.strip() for e in text.split(_SEPARATOR) if e.strip()]
        entries = []
        for raw in raw_entries:
            parsed = self._parse_entry(raw)
            if parsed:
                entries.append(parsed)
        return entries

    def get_pending_entries(self) -> List[Dict[str, Any]]:
        return [e for e in self.load_entries() if e.get("pending")]

    def get_resolved_entries(self) -> List[Dict[str, Any]]:
        return [e for e in self.load_entries() if not e.get("pending")]

    def get_past_context(
        self,
        symbol: str,
        n_same: int = 5,
        n_cross: int = 3,
    ) -> str:
        """获取格式化历史上下文（用于 prompt 注入）

        same-symbol: 同一交易对的历史经验
        cross-symbol: 跨交易对的经验（泛化能力）
        """
        entries = self.get_resolved_entries()
        if not entries:
            return ""

        same, cross = [], []
        for e in reversed(entries):
            if len(same) >= n_same and len(cross) >= n_cross:
                break
            if e["symbol"] == symbol and len(same) < n_same:
                same.append(e)
            elif e["symbol"] != symbol and len(cross) < n_cross:
                cross.append(e)

        parts = []
        if same:
            parts.append(f"### Past analyses of {symbol} (most recent first):")
            parts.extend(self._format_full(e) for e in same)
        if cross:
            parts.append("### Recent cross-symbol lessons:")
            parts.extend(self._format_reflection_only(e) for e in cross)
        return "\n\n".join(parts)

    # ── Helpers ──

    def _apply_rotation(self, blocks: List[str]) -> List[str]:
        if not self._max_entries or self._max_entries <= 0:
            return blocks

        decisions = []
        for block in blocks:
            stripped = block.strip()
            if not stripped:
                decisions.append((block, False))
                continue
            tag_line = stripped.splitlines()[0].strip()
            is_resolved = (
                tag_line.startswith("[")
                and tag_line.endswith("]")
                and not tag_line.endswith("| pending]")
            )
            decisions.append((block, is_resolved))

        resolved_count = sum(1 for _, r in decisions if r)
        if resolved_count <= self._max_entries:
            return blocks

        to_drop = resolved_count - self._max_entries
        kept: List[str] = []
        for block, is_resolved in decisions:
            if is_resolved and to_drop > 0:
                to_drop -= 1
                continue
            kept.append(block)
        return kept

    def _parse_entry(self, raw: str) -> Optional[Dict[str, Any]]:
        lines = raw.strip().splitlines()
        if not lines:
            return None
        tag_line = lines[0].strip()
        if not (tag_line.startswith("[") and tag_line.endswith("]")):
            return None

        fields = [f.strip() for f in tag_line[1:-1].split("|")]
        if len(fields) < 4:
            return None

        entry = {
            "date": fields[0],
            "symbol": fields[1],
            "direction": fields[2],
            "pending": fields[3] == "pending",
            "pnl_pct": fields[3] if fields[3] != "pending" else None,
            "pnl_usdt": fields[4] if len(fields) > 4 else None,
            "holding": fields[5] if len(fields) > 5 else None,
        }

        body = "\n".join(lines[1:]).strip()
        decision_match = _DECISION_RE.search(body)
        reflection_match = _REFLECTION_RE.search(body)
        entry["decision"] = decision_match.group(1).strip() if decision_match else ""
        entry["reflection"] = reflection_match.group(1).strip() if reflection_match else ""
        return entry

    def _format_full(self, e: Dict[str, Any]) -> str:
        pnl = e["pnl_pct"] or "n/a"
        holding = e["holding"] or "n/a"
        tag = f"[{e['date']} | {e['symbol']} | {e['direction']} | {pnl} | {holding}]"
        parts = [tag, f"DECISION:\n{e['decision']}"]
        if e["reflection"]:
            parts.append(f"REFLECTION:\n{e['reflection']}")
        return "\n\n".join(parts)

    def _format_reflection_only(self, e: Dict[str, Any]) -> str:
        pnl = e["pnl_pct"] or "n/a"
        tag = f"[{e['date']} | {e['symbol']} | {e['direction']} | {pnl}]"
        if e["reflection"]:
            return f"{tag}\n{e['reflection']}"
        text = e["decision"][:300]
        suffix = "..." if len(e["decision"]) > 300 else ""
        return f"{tag}\n{text}{suffix}"


class MultiDimensionalAnalyzer:
    """多维度分析师（参考 TradingAgents Analysts 模式）

    从 TradeCase 中提取不同维度的分析证据：
    - 基本面 (fundamentals): 财务数据、公司信息
    - 技术面 (technical): 价格、指标、趋势
    - 情绪面 (sentiment): 市场情绪、信心度
    - 新闻面 (news): 新闻事件、宏观数据
    - 风控面 (risk): 止损、仓位、杠杆
    """

    def analyze(self, case: Dict[str, Any], episode: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "fundamentals_report": self._analyze_fundamentals(case),
            "technical_report": self._analyze_technical(case),
            "sentiment_report": self._analyze_sentiment(case),
            "risk_report": self._analyze_risk(case, episode),
            "summary": self._generate_summary(case, episode),
        }

    def _analyze_fundamentals(self, case: Dict[str, Any]) -> Dict[str, Any]:
        """基本面分析"""
        dc = case.get("decision_context", {})
        pi = case.get("position_info", {})

        return {
            "entry_price": pi.get("entry_price"),
            "exit_price": pi.get("exit_price"),
            "position_size": pi.get("position_size"),
            "leverage": pi.get("leverage"),
            "margin_usdt": pi.get("margin_usdt"),
            "decision_factors": list(dc.keys()) if isinstance(dc, dict) else [],
            "key_signals": [
                ref.get("ref", "")
                for ref in case.get("evidence_chain", {}).get("signal_refs", [])
            ],
        }

    def _analyze_technical(self, case: Dict[str, Any]) -> Dict[str, Any]:
        """技术面分析"""
        es = case.get("environment_snapshot", {})
        ec = case.get("evidence_chain", {})

        return {
            "regime": es.get("regime", "unknown"),
            "volatility": es.get("volatility"),
            "trend_strength": es.get("trend_strength"),
            "price_position": es.get("price_position"),
            "is_ranging": es.get("is_ranging"),
            "market_data_refs": [
                ref.get("ref", "")
                for ref in ec.get("market_data_refs", [])
            ],
        }

    def _analyze_sentiment(self, case: Dict[str, Any]) -> Dict[str, Any]:
        """情绪面分析"""
        dc = case.get("decision_context", {})
        confidence = None
        if isinstance(dc, dict):
            confidence = dc.get("confidence")

        # 从 evidence_chain 提取情绪信号
        sentiment_signals = []
        for ref in case.get("evidence_chain", {}).get("signal_refs", []):
            if isinstance(ref, dict) and ref.get("type") in ["confidence", "liangyi"]:
                sentiment_signals.append(ref.get("ref", ""))

        return {
            "confidence": confidence,
            "sentiment_signals": sentiment_signals,
            "overall_bullish": case.get("direction") == "long",
        }

    def _analyze_risk(self, case: Dict[str, Any], episode: Dict[str, Any]) -> Dict[str, Any]:
        """风控分析"""
        pi = case.get("position_info", {})
        out = episode.get("outcome") or {}
        do = case.get("decision_outcome", {})

        return {
            "leverage": pi.get("leverage"),
            "drawdown": do.get("drawdown") or out.get("max_drawdown"),
            "exit_reason": out.get("exit_reason") or out.get("stop_reason"),
            "stop_loss_triggered": (out.get("exit_reason") or "") in ["stop_loss", "止损"],
            "risk_events": case.get("risk_events", []),
        }

    def _generate_summary(self, case: Dict[str, Any], episode: Dict[str, Any]) -> str:
        """生成多维度分析摘要"""
        symbol = case.get("symbol", "Unknown")
        direction = case.get("direction", "unknown")
        pnl_pct = case.get("decision_outcome", {}).get("pnl_pct")

        parts = [
            f"## Multi-Dimensional Analysis: {symbol} ({direction})",
            "",
            f"**PnL%**: {_format_pct(pnl_pct)}",
            "",
            "### Key Findings",
        ]

        # 技术面
        es = case.get("environment_snapshot", {})
        if es.get("regime"):
            parts.append(f"- Market regime: {es['regime']}")

        # 情绪面
        dc = case.get("decision_context", {})
        if isinstance(dc, dict) and dc.get("confidence"):
            parts.append(f"- Confidence: {dc['confidence']}")

        # 风控
        pi = case.get("position_info", {})
        if pi.get("leverage"):
            parts.append(f"- Leverage: {pi['leverage']}x")

        return "\n".join(parts)


class Reflector:
    """复盘反思引擎（TradingAgents Reflector 的 L4 适配版）

    两阶段机制：
    Phase A: 交易决策时记录（通过 memory_log.store_decision）
    Phase B: 结果已知后生成深度反思
    """

    def __init__(self, memory_log: Optional[L4MemoryLog] = None):
        self.memory_log = memory_log

    def reflect(
        self,
        case: Dict[str, Any],
        episode: Dict[str, Any],
        analysis: Dict[str, Any],
    ) -> Dict[str, Any]:
        """生成深度反思报告

        覆盖 TradingAgents Reflector 的核心维度：
        1. 方向判断是否正确
        2. 投资论点哪些成立/失败
        3. 经验教训
        """
        pnl_pct, pnl_usdt = _extract_pnl(episode)
        if pnl_pct is None:
            do = case.get("decision_outcome", {})
            pnl_pct = do.get("pnl_pct", 0)

        direction = case.get("direction", "long")
        symbol = case.get("symbol", "Unknown")

        # 方向判断是否正确
        direction_correct = (pnl_pct > 0 and direction == "long") or (pnl_pct < 0 and direction == "short")

        # 理论验证
        theory_verification = analysis.get("theory_verification", {})
        confirmed = theory_verification.get("confirmed_theories", [])
        contradicted = theory_verification.get("contradicted_theories", [])

        # 多维度分析
        analyzer = MultiDimensionalAnalyzer()
        multi_dim = analyzer.analyze(case, episode)

        # 生成反思文本
        reflection_text = self._generate_reflection_text(
            symbol=symbol,
            direction=direction,
            pnl_pct=pnl_pct,
            direction_correct=direction_correct,
            confirmed=confirmed,
            contradicted=contradicted,
            multi_dim=multi_dim,
            analysis=analysis,
        )

        # 获取历史上下文
        past_context = ""
        if self.memory_log:
            past_context = self.memory_log.get_past_context(symbol)

        return {
            "reflection_text": reflection_text,
            "direction_correct": direction_correct,
            "confirmed_theories_count": len(confirmed),
            "contradicted_theories_count": len(contradicted),
            "multi_dimensional_analysis": multi_dim,
            "past_context": past_context,
            "lessons": self._extract_lessons(analysis, multi_dim),
        }

    def _generate_reflection_text(
        self,
        symbol: str,
        direction: str,
        pnl_pct: float,
        direction_correct: bool,
        confirmed: List[Dict],
        contradicted: List[Dict],
        multi_dim: Dict[str, Any],
        analysis: Dict[str, Any],
    ) -> str:
        """生成反思文本（TradingAgents 风格：2-4 句简洁散文）"""
        parts = []

        # 1. 方向判断
        if direction_correct:
            parts.append(f"The {direction} call on {symbol} was correct, delivering {_format_pct(pnl_pct)}.")
        else:
            parts.append(f"The {direction} call on {symbol} was wrong, resulting in {_format_pct(pnl_pct)}.")

        # 2. 投资论点
        if confirmed and not contradicted:
            parts.append(f"All {len(confirmed)} theoretical signals held up, confirming the investment thesis.")
        elif contradicted and not confirmed:
            parts.append(f"All {len(contradicted)} theoretical signals failed, invalidating the thesis.")
        elif confirmed and contradicted:
            parts.append(f"Mixed results: {len(confirmed)} signals confirmed, {len(contradicted)} contradicted.")
        else:
            parts.append("Insufficient theoretical signals to validate the thesis.")

        # 3. 经验教训
        failure_patterns = analysis.get("failure_patterns", [])
        if failure_patterns:
            pattern_desc = failure_patterns[0].get("description", "")
            parts.append(f"Key lesson: {pattern_desc} — adjust sizing or entry timing next time.")
        elif confirmed:
            parts.append("This pattern is reproducible; consider increasing conviction sizing in similar setups.")
        else:
            parts.append("Need stronger evidence chain before entering similar trades.")

        return " ".join(parts)

    def _extract_lessons(self, analysis: Dict[str, Any], multi_dim: Dict[str, Any]) -> List[Dict[str, Any]]:
        """提取结构化经验教训"""
        lessons = []

        # 从失败模式提取
        for pattern in analysis.get("failure_patterns", []):
            lessons.append({
                "type": "failure_pattern",
                "description": pattern.get("description", ""),
                "severity": pattern.get("severity", "medium"),
                "actionable": f"Avoid {pattern.get('type', 'this')} in future",
            })

        # 从理论验证提取
        for ct in analysis.get("theory_verification", {}).get("contradicted_theories", []):
            lessons.append({
                "type": "theory_refutation",
                "description": f"{ct['type']} {ct['ref']} predicted {ct['expected']} but got {ct['actual']}",
                "severity": "high",
                "actionable": f"Re-evaluate {ct['type']} {ct['ref']} weight in decision model",
            })

        # 从多维度分析提取
        risk_report = multi_dim.get("risk_report", {})
        if risk_report.get("stop_loss_triggered"):
            lessons.append({
                "type": "risk_management",
                "description": "Stop-loss was triggered",
                "severity": "high",
                "actionable": "Review stop-loss placement relative to volatility",
            })

        return lessons


# ── 辅助函数（与 review_engine 共享） ──

def _extract_pnl(episode: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    out = episode.get("outcome") or {}
    pnl_pct = out.get("realized_pnl_pct")
    if pnl_pct is None:
        pnl_pct = out.get("unrealized_pnl_pct")
    pnl_usdt = out.get("realized_pnl_usdt")
    if pnl_usdt is None:
        pnl_usdt = out.get("unrealized_pnl_usdt")

    if pnl_pct is None and "decision_outcome" in episode:
        do = episode.get("decision_outcome", {})
        pnl_pct = do.get("pnl_pct")
        if pnl_pct is None:
            pnl_pct = do.get("pnl")

    return (
        float(pnl_pct) if pnl_pct is not None else None,
        float(pnl_usdt) if pnl_usdt is not None else None,
    )


# ── 便捷函数 ──

def create_reflector(log_path: Optional[Path] = None) -> Reflector:
    """创建默认 Reflector 实例"""
    if log_path is None:
        from scripts.memory_l4.paths import memory_l4_dir
        log_path = memory_l4_dir() / "l4_memory_log.md"

    memory_log = L4MemoryLog(log_path=log_path, max_entries=200)
    return Reflector(memory_log=memory_log)
