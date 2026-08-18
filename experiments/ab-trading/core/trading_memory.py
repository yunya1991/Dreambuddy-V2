#!/usr/bin/env python3
"""
Trading Memory — 交易记忆闭环系统
====================================

这是 Dreambuddy OS 的核心记忆模块，围绕「建议 → 验证 → 复盘 → 进化」
构建交易记忆闭环。这是系统最重要的记忆能力，远比用户偏好、风格切换
等记忆更有价值。

核心闭环：
    上轮建议 → 本轮验证 → 验证结果 → 提炼教训 → 下轮建议

模块能力：
    1. SuggestionLifecycle — 建议生命周期管理（生成/存储/读取）
    2. VerificationEngine — 验证引擎（本轮验证上轮建议）
    3. LessonDistiller — 教训提炼（从验证结果中提炼可复用教训）
    4. PRFeedbackLoop — PR 反馈闭环（从 PR 评论读写建议）
    5. TradingMemory — 统一入口类

记忆数据结构（核心）：
    {
        "suggestion_loop": {
            "prior_cycle_suggestions": {...},   # 上轮建议（本轮验证的对象）
            "next_cycle_suggestions": {...},    # 本轮生成的下轮建议
            "verification_history": [...],      # 建议验证历史
            "verified_lessons": [...],          # 经过验证的教训（最高价值）
            "suggestion_count": 0,              # 累计建议数
            "verification_rate": 0.0,           # 建议验证率
        }
    }
"""

import json
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ──────────────────────────────────────────────────────────────────────────────
# 1. Suggestion Lifecycle — 建议生命周期管理
# ──────────────────────────────────────────────────────────────────────────────

class SuggestionLifecycle:
    """
    建议生命周期管理

    建议的 4 个标准分类：
        next_verifications  — 待验证假设（交易假设、关键价位观察）
        risk_warnings       — 风险提示（市场风险、系统性风险）
        bac_adjustments     — BAC 链路调整建议（架构层面）
        dze_triggers        — D-Z-E 触发建议（向外学习）
    """

    SUGGESTION_TYPES = [
        "next_verifications",
        "risk_warnings",
        "bac_adjustments",
        "dze_triggers",
    ]

    @staticmethod
    def empty_suggestions() -> Dict:
        """返回空的建议结构"""
        return {
            "cycle_id": None,
            "next_verifications": [],
            "risk_warnings": [],
            "bac_adjustments": [],
            "dze_triggers": [],
            "raw_text": "",
            "generated_at": None,
        }

    @staticmethod
    def build_suggestions(
        cycle_id: str,
        action: str,
        coin: str,
        price: float,
        confidence: float,
        intent_confidence: float,
        regime: str,
        mkt: Dict,
        chain_result: Optional[object],
        memory: Dict,
    ) -> Dict:
        """
        基于本轮决策生成下轮关注建议。

        这是交易记忆闭环的「建议生成」环节。
        自动从决策结果、市场环境、系统状态中提炼 4 类建议。
        """
        sugg = SuggestionLifecycle.empty_suggestions()
        sugg["cycle_id"] = cycle_id
        sugg["generated_at"] = _now_iso()

        next_verifications = []
        risk_warnings = []
        bac_adjustments = []
        dze_triggers = []

        # ── 待验证假设：基于当前持仓/决策的关键观察点 ──
        if action in ("BUY", "LONG"):
            ema50 = mkt.get("ema50", 0)
            ema200 = mkt.get("ema200", 0)
            if ema50 and price < ema50:
                next_verifications.append(
                    f"{coin} 能否突破 EMA50({ema50:.2f}) 并放量确认趋势"
                )
            if ema200 and price < ema200:
                next_verifications.append(
                    f"{coin} 能否站上 EMA200({ema200:.2f}) 打开中期空间"
                )
            if chain_result and getattr(chain_result, "stop_loss", None):
                next_verifications.append(
                    f"关注 {coin} 止损位 {chain_result.stop_loss} 是否有效"
                )

        if action in ("SELL", "SHORT"):
            ema20 = mkt.get("ema20", 0)
            if ema20 and price > ema20:
                next_verifications.append(
                    f"{coin} 能否跌破 EMA20({ema20:.2f}) 确认下行"
                )

        if not next_verifications and action == "HOLD":
            next_verifications.append(
                f"观察 {coin} 在当前 {regime} 区间内的方向选择"
            )

        # ── 风险提示：基于市场环境的风险预警 ──
        vol_ratio = mkt.get("vol_ratio", 1)
        if vol_ratio < 0.6:
            risk_warnings.append(
                f"整体市场量能持续低迷（{vol_ratio:.1f}x），警惕假突破/假跌破"
            )

        if regime == "RANGE":
            risk_warnings.append(
                "当前 RANGE 震荡市，突破信号可靠性降低，需严格止损"
            )

        # ── BAC 调整：基于知行合一 gap 的架构优化建议 ──
        gap_score = abs(intent_confidence - confidence)
        if gap_score >= 0.3:
            level = "中度" if gap_score < 0.5 else "严重"
            bac_adjustments.append(
                f"gap_score={gap_score:.2f}（{level}背离），"
                f"建议优化意图识别模块对 {regime} 市场的敏感度"
            )

        # ── D-Z-E 触发：基于系统健康度的向外学习建议 ──
        loss_streaks = memory.get("loss_streaks", 0)
        if loss_streaks >= 3:
            dze_triggers.append(
                f"连败{loss_streaks}次，触发向外学习，重新评估策略框架"
            )

        recent = memory.get("recent_decisions", [])[-10:]
        hold_count = sum(1 for d in recent if d.get("action") == "HOLD")
        if hold_count >= 5:
            dze_triggers.append(
                f"连续{hold_count}次HOLD的强迫性重复，"
                f"建议触发向外学习优化意图识别"
            )

        recent_5 = memory.get("recent_decisions", [])[-5:]
        hold_5 = sum(1 for d in recent_5 if d.get("action") == "HOLD")
        if hold_5 >= 3 and confidence < 0.65:
            dze_triggers.append(
                f"近5轮{hold_5}次HOLD且置信度<65%，系统可能过度保守"
            )

        sugg["next_verifications"] = next_verifications
        sugg["risk_warnings"] = risk_warnings
        sugg["bac_adjustments"] = bac_adjustments
        sugg["dze_triggers"] = dze_triggers
        sugg["raw_text"] = SuggestionLifecycle._suggestions_to_text(sugg)

        return sugg

    @staticmethod
    def _suggestions_to_text(sugg: Dict) -> str:
        """将建议结构转成文本（用于 PR 展示）"""
        lines = []
        for v in sugg.get("next_verifications", []):
            lines.append(f"- 待验证: {v}")
        for r in sugg.get("risk_warnings", []):
            lines.append(f"- 风险: {r}")
        for b in sugg.get("bac_adjustments", []):
            lines.append(f"- BAC调整: {b}")
        for d in sugg.get("dze_triggers", []):
            lines.append(f"- DZE: {d}")
        return "\n".join(lines)

    @staticmethod
    def count(sugg: Dict) -> int:
        """统计建议总数"""
        return (
            len(sugg.get("next_verifications", []))
            + len(sugg.get("risk_warnings", []))
            + len(sugg.get("bac_adjustments", []))
            + len(sugg.get("dze_triggers", []))
        )

    @staticmethod
    def is_empty(sugg: Dict) -> bool:
        return SuggestionLifecycle.count(sugg) == 0


# ──────────────────────────────────────────────────────────────────────────────
# 2. Verification Engine — 验证引擎
# ──────────────────────────────────────────────────────────────────────────────

class VerificationEngine:
    """
    验证引擎：本轮验证上轮建议

    输入：上轮建议 + 当前市场数据 + 本轮决策结果
    输出：每条建议的验证状态（已验证/待验证/部分验证）+ 验证结论

    这是交易记忆闭环的「验证」环节。
    """

    VERIFY_STATUS_VERIFIED = "verified"       # 已验证（有明确结论）
    VERIFY_STATUS_PARTIAL  = "partial"        # 部分验证
    VERIFY_STATUS_PENDING  = "pending"        # 待验证（市场还没走到那一步）
    VERIFY_STATUS_INVALID  = "invalid"        # 无效/不适用

    @staticmethod
    def verify_suggestions(
        prior_sugg: Dict,
        current_action: str,
        current_coin: str,
        current_price: float,
        mkt: Dict,
        confidence: float,
        gate_passed: bool,
    ) -> List[Dict]:
        """
        对上轮建议进行逐项验证，返回验证结果列表。

        每条验证结果结构：
        {
            "type": "next_verifications" | "risk_warnings" | ...,
            "content": "建议原文",
            "status": "verified" | "partial" | "pending" | "invalid",
            "conclusion": "验证结论",
        }
        """
        results = []

        # 验证待验证假设
        for v in prior_sugg.get("next_verifications", []):
            result = VerificationEngine._verify_verification(v, current_action, current_coin, current_price, mkt)
            results.append(result)

        # 验证风险提示（风险提示如果发生了就是验证了）
        for r in prior_sugg.get("risk_warnings", []):
            result = VerificationEngine._verify_risk(r, current_action, current_coin, current_price, mkt)
            results.append(result)

        # BAC调整建议（基于 gap_score 变化判断）
        for b in prior_sugg.get("bac_adjustments", []):
            results.append({
                "type": "bac_adjustments",
                "content": b,
                "status": VerificationEngine.VERIFY_STATUS_PARTIAL,
                "conclusion": "已纳入本轮 B 层蓝图输入，持续观察中",
            })

        # D-Z-E 触发建议
        for d in prior_sugg.get("dze_triggers", []):
            results.append({
                "type": "dze_triggers",
                "content": d,
                "status": VerificationEngine.VERIFY_STATUS_PARTIAL,
                "conclusion": "已记录，等待触发 D-Z-E 流程",
            })

        return results

    @staticmethod
    def _verify_verification(
        v: str,
        current_action: str,
        current_coin: str,
        current_price: float,
        mkt: Dict,
    ) -> Dict:
        """验证一条待验证假设"""
        result = {
            "type": "next_verifications",
            "content": v,
            "status": VerificationEngine.VERIFY_STATUS_PENDING,
            "conclusion": "市场尚未给出明确信号，持续观察",
        }

        # 检测「突破 EMA50 / EMA200」类建议
        if "EMA50" in v and "突破" in v:
            ema50 = mkt.get("ema50", 0)
            if ema50 and current_price > ema50:
                if mkt.get("vol_ratio", 0) > 0.8:
                    result["status"] = VerificationEngine.VERIFY_STATUS_VERIFIED
                    result["conclusion"] = f"已突破 EMA50({ema50:.2f}) 并放量，验证成立"
                else:
                    result["status"] = VerificationEngine.VERIFY_STATUS_PARTIAL
                    result["conclusion"] = f"价格突破 EMA50({ema50:.2f}) 但量能不足，需继续确认"
            return result

        if "EMA200" in v and "站上" in v:
            ema200 = mkt.get("ema200", 0)
            if ema200 and current_price > ema200:
                result["status"] = VerificationEngine.VERIFY_STATUS_VERIFIED
                result["conclusion"] = f"已站上 EMA200({ema200:.2f})，中期空间打开"
            return result

        # 如果当前动作是 BUY/LONG 且建议是关于同币种的
        if current_coin in v and current_action in ("BUY", "LONG"):
            result["status"] = VerificationEngine.VERIFY_STATUS_PARTIAL
            result["conclusion"] = "已纳入本轮分析并据此入场，持续验证中"

        return result

    @staticmethod
    def _verify_risk(
        r: str,
        current_action: str,
        current_coin: str,
        current_price: float,
        mkt: Dict,
    ) -> Dict:
        """验证一条风险提示"""
        result = {
            "type": "risk_warnings",
            "content": r,
            "status": VerificationEngine.VERIFY_STATUS_PENDING,
            "conclusion": "风险持续关注中",
        }

        if "量能" in r and "低迷" in r:
            vol_ratio = mkt.get("vol_ratio", 1)
            if vol_ratio < 0.6:
                result["status"] = VerificationEngine.VERIFY_STATUS_VERIFIED
                result["conclusion"] = f"量能仍低迷（{vol_ratio:.1f}x），风险持续，注意假突破"
            else:
                result["status"] = VerificationEngine.VERIFY_STATUS_INVALID
                result["conclusion"] = f"量能已恢复（{vol_ratio:.1f}x），此风险解除"
            return result

        if "RANGE" in r and "震荡" in r:
            if mkt.get("regime") == "RANGE":
                result["status"] = VerificationEngine.VERIFY_STATUS_VERIFIED
                result["conclusion"] = "仍在 RANGE 震荡市，突破信号需谨慎"
            else:
                result["status"] = VerificationEngine.VERIFY_STATUS_INVALID
                result["conclusion"] = f"市场已进入{mkt.get('regime')}状态，此风险已变化"
            return result

        return result

    @staticmethod
    def summary(verifications: List[Dict]) -> Dict:
        """生成验证结果摘要统计"""
        from collections import Counter
        counter = Counter(v["status"] for v in verifications)
        by_type = {}
        for v in verifications:
            t = v["type"]
            if t not in by_type:
                by_type[t] = {"total": 0, "verified": 0}
            by_type[t]["total"] += 1
            if v["status"] == VerificationEngine.VERIFY_STATUS_VERIFIED:
                by_type[t]["verified"] += 1

        total = len(verifications)
        verified = counter.get(VerificationEngine.VERIFY_STATUS_VERIFIED, 0)
        return {
            "total": total,
            "verified": verified,
            "partial": counter.get(VerificationEngine.VERIFY_STATUS_PARTIAL, 0),
            "pending": counter.get(VerificationEngine.VERIFY_STATUS_PENDING, 0),
            "invalid": counter.get(VerificationEngine.VERIFY_STATUS_INVALID, 0),
            "verify_rate": round(verified / total, 2) if total > 0 else 0.0,
            "by_type": by_type,
        }


# ──────────────────────────────────────────────────────────────────────────────
# 3. Lesson Distiller — 教训提炼
# ──────────────────────────────────────────────────────────────────────────────

class LessonDistiller:
    """
    教训提炼引擎

    从验证结果中提炼可复用的交易教训。
    这是交易记忆闭环的「复盘/进化」环节。
    """

    @staticmethod
    def distill(verifications: List[Dict], cycle_id: str) -> List[Dict]:
        """
        从验证结果中提炼教训。

        提炼规则：
        - 已验证的待验证假设 → 提炼为「市场规律」类教训
        - 已验证的风险提示 → 提炼为「风险预警」类教训
        - BAC/DZE 调整建议验证 → 提炼为「系统优化」类教训
        """
        lessons = []

        for v in verifications:
            if v["status"] != VerificationEngine.VERIFY_STATUS_VERIFIED:
                continue

            if v["type"] == "next_verifications":
                lessons.append({
                    "id": f"lesson_{len(lessons) + 1}",
                    "category": "market_pattern",
                    "content": v["content"],
                    "conclusion": v["conclusion"],
                    "source_cycle": cycle_id,
                    "confidence": 0.6,
                    "verify_count": 1,
                    "created_at": _now_iso(),
                })

            elif v["type"] == "risk_warnings":
                lessons.append({
                    "id": f"lesson_{len(lessons) + 1}",
                    "category": "risk_warning",
                    "content": v["content"],
                    "conclusion": v["conclusion"],
                    "source_cycle": cycle_id,
                    "confidence": 0.7,
                    "verify_count": 1,
                    "created_at": _now_iso(),
                })

            elif v["type"] == "bac_adjustments":
                lessons.append({
                    "id": f"lesson_{len(lessons) + 1}",
                    "category": "system_optimization",
                    "content": v["content"],
                    "conclusion": v["conclusion"],
                    "source_cycle": cycle_id,
                    "confidence": 0.5,
                    "verify_count": 1,
                    "created_at": _now_iso(),
                })

        return lessons

    @staticmethod
    def merge_into_memory(memory: Dict, new_lessons: List[Dict]) -> Dict:
        """将新教训合并到 memory 的 verified_lessons 中，去重+优胜劣汰"""
        verified = memory.get("suggestion_loop", {}).get("verified_lessons", [])

        for nl in new_lessons:
            is_dup = False
            for vl in verified:
                if nl["content"][:30] == vl["content"][:30]:
                    vl["verify_count"] = vl.get("verify_count", 1) + 1
                    vl["confidence"] = min(0.95, vl.get("confidence", 0.6) + 0.05)
                    is_dup = True
                    break
            if not is_dup:
                verified.append(nl)

        verified.sort(key=lambda x: (x.get("confidence", 0), x.get("verify_count", 0)), reverse=True)
        verified = verified[:30]

        if "suggestion_loop" not in memory:
            memory["suggestion_loop"] = {}
        memory["suggestion_loop"]["verified_lessons"] = verified
        return memory


# ──────────────────────────────────────────────────────────────────────────────
# 4. PR Feedback Loop — PR 评论反馈闭环
# ──────────────────────────────────────────────────────────────────────────────

class PRFeedbackLoop:
    """
    PR 评论反馈闭环

    从 PR 评论中读取上轮建议，将本轮建议写入 PR 评论。
    这是交易记忆闭环的「外部持久化/可视化」环节。
    """

    def __init__(self, gh_token: str, pr_number: str, repo: str = "yunya1991/Dreambuddy-V2"):
        self.gh_token = gh_token
        self.pr_number = pr_number
        self.repo = repo

    def fetch_comments(self) -> List[Dict]:
        """获取 PR 所有评论（按时间升序）"""
        if not self.gh_token:
            return []
        import requests
        url = f"https://api.github.com/repos/{self.repo}/issues/{self.pr_number}/comments"
        headers = {
            "Authorization": f"token {self.gh_token}",
            "Accept": "application/vnd.github.v3+json",
        }
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code == 200:
                return sorted(r.json(), key=lambda c: c.get("created_at", ""))
        except Exception:
            pass
        return []

    def find_last_agent_b_comment(self, comments: List[Dict]) -> Optional[Dict]:
        """
        找到最新的 Agent B 交易报告评论。
        优先找包含「下轮关注建议」的长格式报告（含结构化建议）。
        """
        for c in reversed(comments):
            body = c.get("body", "")
            if "Agent B 交易报告" in body and "下轮关注" in body:
                return c
        for c in reversed(comments):
            body = c.get("body", "")
            if "Agent B 交易报告" in body or "🧠 Agent B" in body:
                return c
        return None

    def extract_suggestions(self, comment_body: str) -> Dict:
        """
        从 Agent B 交易报告评论中提取「下轮关注建议」。
        返回结构同 SuggestionLifecycle.empty_suggestions()。
        """
        result = SuggestionLifecycle.empty_suggestions()

        if not comment_body:
            return result

        m = re.search(r"cycle:\s*([0-9_]+)", comment_body)
        if m:
            result["cycle_id"] = m.group(1)

        next_section = ""
        lines = comment_body.split("\n")
        in_next_section = False
        section_level = 0

        for line in lines:
            if "下轮关注建议" in line or ("🔮" in line and ("关注" in line or "建议" in line)):
                in_next_section = True
                section_level = len(line) - len(line.lstrip("#"))
                continue

            if in_next_section:
                stripped = line.lstrip()
                if stripped.startswith("###") and len(line) - len(stripped) <= section_level:
                    break
                if stripped.startswith("##") and len(line) - len(stripped) < section_level:
                    break
                next_section += line + "\n"

        result["raw_text"] = next_section.strip()

        current_list = None
        for line in next_section.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue

            if "待验证假设" in stripped:
                current_list = "next_verifications"
                m2 = re.search(r"[：:](.+)", stripped)
                if m2 and m2.group(1).strip():
                    result["next_verifications"].append(m2.group(1).strip())
                continue

            if re.match(r"^\d+\.\s*\*\*风险提示\*\*", stripped) or ("风险提示" in stripped and "潜在机会" not in stripped):
                current_list = "risk_warnings"
                m2 = re.search(r"[：:](.+)", stripped)
                if m2 and m2.group(1).strip():
                    result["risk_warnings"].append(m2.group(1).strip())
                continue

            if "潜在机会" in stripped:
                current_list = None
                continue

            if re.match(r"^\d+\.\s*\*\*BAC", stripped) or ("BAC" in stripped and ("调整" in stripped or "链路" in stripped)):
                current_list = "bac_adjustments"
                m2 = re.search(r"[：:](.+)", stripped)
                if m2 and m2.group(1).strip():
                    result["bac_adjustments"].append(m2.group(1).strip())
                continue

            if re.match(r"^\d+\.\s*\*\*D-Z-E", stripped) or re.match(r"^\d+\.\s*\*\*DZE", stripped) or ("D-Z-E" in stripped and "触发" in stripped):
                current_list = "dze_triggers"
                m2 = re.search(r"[：:](.+)", stripped)
                if m2 and m2.group(1).strip():
                    result["dze_triggers"].append(m2.group(1).strip())
                continue

            if stripped.startswith("-") or stripped.startswith("*") or re.match(r"^\d+[\.\)、]", stripped):
                item = re.sub(r"^[-*\d\.\)、]+\s*", "", stripped).strip()
                if item and current_list and current_list in result:
                    if item.startswith("**") and item.endswith("**"):
                        continue
                    result[current_list].append(item)

        return result

    def load_prior_suggestions(self) -> Dict:
        """一键加载上轮 PR 建议（如果没有则返回空）"""
        comments = self.fetch_comments()
        if not comments:
            return SuggestionLifecycle.empty_suggestions()
        last_comment = self.find_last_agent_b_comment(comments)
        if not last_comment:
            return SuggestionLifecycle.empty_suggestions()
        return self.extract_suggestions(last_comment.get("body", ""))


# ──────────────────────────────────────────────────────────────────────────────
# 5. TradingMemory — 统一入口类
# ──────────────────────────────────────────────────────────────────────────────

class TradingMemory:
    """
    交易记忆系统 — 统一入口

    核心闭环：
        load_prior() → verify() → distill() → generate_next() → save()

    这是系统最重要的记忆能力，围绕交易建议生命周期构建。
    """

    def __init__(
        self,
        memory_path: Path,
        gh_token: str = "",
        pr_number: str = "52",
    ):
        self.memory_path = memory_path
        self.pr_loop = PRFeedbackLoop(gh_token, pr_number) if gh_token else None
        self.memory = self._load_memory()

    def _load_memory(self) -> Dict:
        """从磁盘加载记忆"""
        if self.memory_path.exists():
            try:
                with open(self.memory_path) as f:
                    mem = json.load(f)
            except Exception:
                mem = {}
        else:
            mem = {}

        if "suggestion_loop" not in mem:
            mem["suggestion_loop"] = {
                "prior_cycle_suggestions": SuggestionLifecycle.empty_suggestions(),
                "next_cycle_suggestions": SuggestionLifecycle.empty_suggestions(),
                "verification_history": [],
                "verified_lessons": [],
                "suggestion_count": 0,
                "verify_count": 0,
            }

        sl = mem["suggestion_loop"]
        if "prior_cycle_suggestions" not in sl:
            sl["prior_cycle_suggestions"] = SuggestionLifecycle.empty_suggestions()
        if "next_cycle_suggestions" not in sl:
            sl["next_cycle_suggestions"] = SuggestionLifecycle.empty_suggestions()
        if "verification_history" not in sl:
            sl["verification_history"] = []
        if "verified_lessons" not in sl:
            sl["verified_lessons"] = []

        return mem

    def save(self):
        """保存记忆到磁盘"""
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.memory_path, "w") as f:
            json.dump(self.memory, f, ensure_ascii=False, indent=2)

    # ── 闭环步骤 1：加载上轮建议 ──

    def load_prior_suggestions(self) -> Dict:
        """
        加载上轮建议。

        优先级：
        1. memory 中已有的 prior_cycle_suggestions（最快，零网络开销）
        2. PR 评论在线读取（兜底，首次执行用）
        3. 空建议（都不行时）
        """
        sl = self.memory.get("suggestion_loop", {})
        prior = sl.get("prior_cycle_suggestions", {})

        if not SuggestionLifecycle.is_empty(prior) and prior.get("cycle_id"):
            return prior

        if self.pr_loop:
            pr_sugg = self.pr_loop.load_prior_suggestions()
            if not SuggestionLifecycle.is_empty(pr_sugg):
                sl["prior_cycle_suggestions"] = pr_sugg
                return pr_sugg

        return SuggestionLifecycle.empty_suggestions()

    # ── 闭环步骤 2：验证上轮建议 ──

    def verify_prior_suggestions(
        self,
        current_action: str,
        current_coin: str,
        current_price: float,
        mkt: Dict,
        confidence: float,
        gate_passed: bool,
    ) -> Tuple[List[Dict], Dict]:
        """
        验证上轮建议，返回验证结果列表 + 摘要统计。

        同时将验证结果记入 verification_history。
        """
        prior = self.load_prior_suggestions()
        if SuggestionLifecycle.is_empty(prior):
            return [], {"total": 0, "verify_rate": 0.0}

        verifications = VerificationEngine.verify_suggestions(
            prior, current_action, current_coin, current_price, mkt, confidence, gate_passed
        )
        summary = VerificationEngine.summary(verifications)

        history = self.memory["suggestion_loop"].get("verification_history", [])
        history.append({
            "cycle_id": prior.get("cycle_id"),
            "verified_at": _now_iso(),
            "summary": summary,
            "details": verifications,
        })
        self.memory["suggestion_loop"]["verification_history"] = history[-50:]
        self.memory["suggestion_loop"]["verify_count"] = (
            self.memory["suggestion_loop"].get("verify_count", 0) + 1
        )

        return verifications, summary

    # ── 闭环步骤 3：提炼教训 ──

    def distill_lessons(self, verifications: List[Dict], cycle_id: str) -> List[Dict]:
        """从验证结果中提炼教训，合并到 verified_lessons"""
        new_lessons = LessonDistiller.distill(verifications, cycle_id)
        LessonDistiller.merge_into_memory(self.memory, new_lessons)
        return new_lessons

    # ── 闭环步骤 4：生成本轮建议（供下轮验证） ──

    def generate_next_suggestions(
        self,
        cycle_id: str,
        action: str,
        coin: str,
        price: float,
        confidence: float,
        intent_confidence: float,
        regime: str,
        mkt: Dict,
        chain_result: Optional[object],
    ) -> Dict:
        """
        生成本轮的下轮建议。

        同时将建议：
        1. 存入 next_cycle_suggestions（供下轮作为 prior 使用）
        2. 更新 suggestion_count 统计
        """
        sugg = SuggestionLifecycle.build_suggestions(
            cycle_id, action, coin, price, confidence,
            intent_confidence, regime, mkt, chain_result, self.memory,
        )

        sl = self.memory["suggestion_loop"]
        sl["next_cycle_suggestions"] = sugg
        sl["prior_cycle_suggestions"] = sugg
        sl["suggestion_count"] = sl.get("suggestion_count", 0) + 1

        return sugg

    # ── 辅助方法 ──

    def get_verified_lessons(self, category: Optional[str] = None, limit: int = 10) -> List[Dict]:
        """获取经过验证的教训，可按类别过滤"""
        lessons = self.memory["suggestion_loop"].get("verified_lessons", [])
        if category:
            lessons = [l for l in lessons if l.get("category") == category]
        return lessons[:limit]

    def get_stats(self) -> Dict:
        """获取记忆系统统计信息"""
        sl = self.memory.get("suggestion_loop", {})
        prior = sl.get("prior_cycle_suggestions", {})
        next_s = sl.get("next_cycle_suggestions", {})
        return {
            "total_suggestions": sl.get("suggestion_count", 0),
            "total_verifications": sl.get("verify_count", 0),
            "verified_lessons_count": len(sl.get("verified_lessons", [])),
            "prior_suggestions_count": SuggestionLifecycle.count(prior),
            "next_suggestions_count": SuggestionLifecycle.count(next_s),
            "prior_cycle": prior.get("cycle_id"),
            "next_cycle": next_s.get("cycle_id"),
        }
