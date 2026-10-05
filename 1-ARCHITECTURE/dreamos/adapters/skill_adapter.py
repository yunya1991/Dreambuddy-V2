"""
Dreambuddy OS — SKILL 适配器

将 SKILL.md 包装为 Node。

工作原理:
    1. 读取 SKILL.md 元信息（frontmatter + 标题 + 内容）
    2. 将 SKILL.md 中的系统指令 + 执行步骤构建为 LLM Prompt
    3. 调用 LLM 执行（通过 dreamos.shared.llm_client）
    4. 解析 LLM 输出为 NodeResult（direction / confidence / outputs）
"""

from __future__ import annotations

import os
import re
import json
from pathlib import Path
from typing import Any, Dict, Optional, List

from .base import BaseAdapter
from ..registry.base import BaseNode
from dreamos.shared.state import State, NodeResult, NodeStatus
from dreamos.shared.llm_client import get_default_client, LLMMessage, make_messages


def parse_skill_metadata(skill_md_path: str) -> Dict[str, Any]:
    """解析 SKILL.md 的元信息

    从 frontmatter / 标题 / 内容中提取:
        - node_id
        - name
        - chain (A/C/F/G/T)
        - description
        - estimated_tokens
        - entry_point
        - system_prompt (从 ## System / ## 系统指令 段落提取)
    """
    path = Path(skill_md_path)
    if not path.exists():
        return {}

    content = path.read_text(encoding="utf-8")
    meta: Dict[str, Any] = {
        "skill_path": str(path),
        "node_id": path.stem,
        "name": "",
        "chain": "",
        "description": "",
        "estimated_tokens": 0,
        "entry_point": "",
        "system_prompt": "",
        "autonomy_boundary": "",
        "skill_content": content,
    }

    fm = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if fm:
        for line in fm.group(1).split("\n"):
            if ":" in line:
                k, _, v = line.partition(":")
                k = k.strip().lower()
                v = v.strip()
                if k in ("node_id", "id"):
                    meta["node_id"] = v
                elif k in ("name", "title"):
                    meta["name"] = v
                elif k in ("chain", "domain"):
                    meta["chain"] = v
                elif k in ("tokens", "estimated_tokens"):
                    meta["estimated_tokens"] = int(v) if v.isdigit() else 0
                elif k == "entry":
                    meta["entry_point"] = v
                elif k in ("description", "desc"):
                    meta["description"] = v

    if not meta["name"]:
        m = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        if m:
            meta["name"] = m.group(1).strip()

    if not meta["description"]:
        m = re.search(r"^##\s+(?:Description|描述|简介)\s*\n(.+?)(?=^##|\Z)",
                      content, re.MULTILINE | re.DOTALL)
        if m:
            meta["description"] = m.group(1).strip()[:200]

    sys_match = re.search(
        r"^##\s+(?:System|系统指令|System Prompt)\s*\n(.+?)(?=^##|\Z)",
        content, re.MULTILINE | re.DOTALL,
    )
    if sys_match:
        meta["system_prompt"] = sys_match.group(1).strip()

    boundary_match = re.search(
        r"^##\s+(?:Autonomy Boundary|自主性边界)\s*\n(.+?)(?=^##|\Z)",
        content, re.MULTILINE | re.DOTALL,
    )
    if boundary_match:
        meta["autonomy_boundary"] = boundary_match.group(1).strip()

    if not meta["chain"]:
        parent = path.parent.name.lower()
        if parent.startswith("a"):
            meta["chain"] = "A"
        elif parent.startswith("c"):
            meta["chain"] = "C"
        elif parent.startswith("f"):
            meta["chain"] = "F"
        elif parent.startswith("g"):
            meta["chain"] = "G"

    return meta


# ============================================================
# SKILL 节点
# ============================================================

RESULT_TEMPLATE = """
你是一个交易分析节点。根据 SKILL 描述和当前状态，执行分析并返回结构化结果。

输出分为两个通道：

## Commentary（执行过程）
用简短文字描述你的分析推理过程（1-3 句），可包含中间观察。
此部分仅供日志记录，不会被解析为结果。

## Final（最终结果）
在 "Final:" 标记后输出严格的 JSON 格式，不要包含任何额外文本：
{{
  "direction": "LONG" | "SHORT" | "NEUTRAL" | "HOLD",
  "confidence": 0.0 ~ 1.0,
  "rationale": ["理由1", "理由2", ...],
  "outputs": {{
    "key1": "value1",
    ...
  }}
}}

SKILL 说明:
{skill_content}

---

当前状态摘要:
{state_summary}

请先输出 Commentary 分析过程，再输出 Final JSON 结果。
""".strip()


class SkillNode(BaseNode):
    """SKILL 节点 — 包装 SKILL.md 定义的能力

    通过 LLM 执行 SKILL.md 中的指令，输出 NodeResult。
    """

    def __init__(self, skill_path: str, node_id: str = "",
                 name: str = "", chain: str = "",
                 estimated_tokens: int = 0,
                 system_prompt: str = "",
                 autonomy_boundary: str = "",
                 skill_content: str = "",
                 **kwargs):
        super().__init__(config=kwargs)
        self.skill_path = skill_path
        self.node_id = node_id
        self.name = name
        self.chain = chain
        self.estimated_tokens = estimated_tokens or 500
        self._system_prompt = system_prompt
        self._autonomy_boundary = autonomy_boundary
        self._skill_content = skill_content

    def _load_content(self) -> str:
        if self._skill_content:
            return self._skill_content
        path = Path(self.skill_path)
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def _build_state_summary(self, state: State) -> str:
        lines = []
        mkt = getattr(state, "market_data", {}) or {}
        if mkt:
            symbol = mkt.get("symbol", "UNKNOWN")
            price = mkt.get("price", 0)
            lines.append(f"币种: {symbol}")
            lines.append(f"价格: {price}")
            for key in ("rsi14", "ema20", "ema50", "volume", "atr_pct", "macd"):
                if key in mkt and mkt[key] is not None:
                    lines.append(f"{key}: {mkt[key]}")

        intent = getattr(state, "intent", {}) or {}
        if intent:
            lines.append(f"意图类型: {intent.get('intent_type', '')}")
            lines.append(f"推荐链: {intent.get('recommended_chain', '')}")

        results = getattr(state, "results", {}) or {}
        if results:
            lines.append(f"\n前序节点结果 ({len(results)} 个):")
            for nid, res in list(results.items())[-5:]:
                direction = getattr(res, "direction", "N/A")
                conf = getattr(res, "confidence", 0)
                lines.append(f"  {nid}: {direction} (conf={conf:.2f})")

        return "\n".join(lines)

    def execute_core(self, state: State) -> NodeResult:
        skill_content = self._load_content()
        if not skill_content:
            return NodeResult(
                node_id=self.node_id,
                status=NodeStatus.DEGRADED,
                confidence=0.0,
                error=f"SKILL 文件不存在: {self.skill_path}",
            )

        state_summary = self._build_state_summary(state)

        base_prompt = (
            self._system_prompt
            or "你是一个专业的交易分析助手，严格按照 SKILL 说明执行分析。"
        )
        # 注入自主性边界（借鉴 Codex 沙箱边界机制）
        if self._autonomy_boundary:
            system_msg = f"{base_prompt}\n\n## 自主性边界\n{self._autonomy_boundary}"
        else:
            system_msg = base_prompt

        user_msg = RESULT_TEMPLATE.format(
            skill_content=skill_content[:4000],
            state_summary=state_summary,
        )

        try:
            llm = get_default_client()
            messages = make_messages(system=system_msg, user=user_msg)
            response = llm.chat(messages, temperature=0.3, max_tokens=1000)

            content = response.content.strip()
            parsed = self._parse_output(content)

            direction = parsed.get("direction", "NEUTRAL")
            confidence = float(parsed.get("confidence", 0.0))
            confidence = max(0.0, min(1.0, confidence))
            rationale = parsed.get("rationale", [])
            outputs = parsed.get("outputs", {})
            if isinstance(rationale, str):
                rationale = [rationale]
            outputs["rationale"] = rationale
            outputs["skill_path"] = self.skill_path

            return NodeResult(
                node_id=self.node_id,
                status=NodeStatus.SUCCESS,
                confidence=confidence,
                direction=direction,
                tokens_used=response.tokens_total,
                outputs=outputs,
            )

        except Exception as e:
            return NodeResult(
                node_id=self.node_id,
                status=NodeStatus.DEGRADED,
                confidence=0.0,
                error=f"SKILL 执行失败: {e}",
                outputs={"skill_path": self.skill_path},
            )

    def _parse_output(self, content: str) -> Dict[str, Any]:
        """解析 LLM 输出为结构化结果

        支持双通道输出（Commentary + Final）：
        - 若存在 "Final:" 标记，优先解析其后的 JSON
        - 否则回退到全文 JSON 解析（向后兼容）
        """
        text = content.strip()

        # 双通道：优先提取 Final 标记后的内容
        final_match = re.search(r"Final\s*[:：]\s*(.+)", text, re.DOTALL | re.IGNORECASE)
        if final_match:
            text = final_match.group(1).strip()

        match = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        direction = "NEUTRAL"
        confidence = 0.0
        rationale = [text[:500]]

        if re.search(r"(?i)\bLONG\b|做多|看涨|买入", text):
            direction = "LONG"
        elif re.search(r"(?i)\bSHORT\b|做空|看跌|卖出", text):
            direction = "SHORT"
        elif re.search(r"(?i)\bHOLD\b|持有|观望", text):
            direction = "HOLD"

        conf_match = re.search(r"confidence[^\d]*([0-9]*\.?[0-9]+)", text, re.IGNORECASE)
        if conf_match:
            try:
                confidence = float(conf_match.group(1))
                if confidence > 1:
                    confidence = confidence / 100.0
            except ValueError:
                pass

        return {
            "direction": direction,
            "confidence": confidence,
            "rationale": rationale,
            "outputs": {},
        }


# ============================================================
# SKILL 适配器
# ============================================================

class SkillAdapter(BaseAdapter):
    """SKILL 适配器 — 将 SKILL.md 包装为 Node

    用法:
        adapter = SkillAdapter()
        node = adapter.to_node({
            "type": "skill",
            "path": "6-TRADING/skills/A0_contradiction/SKILL.md",
        })
    """

    adapter_type = "skill"

    def can_handle(self, config: Dict[str, Any]) -> bool:
        return config.get("type") == "skill" and "path" in config

    def to_node(self, config: Dict[str, Any]) -> SkillNode:
        skill_path = config["path"]

        meta = parse_skill_metadata(skill_path) if os.path.exists(skill_path) else {}

        return SkillNode(
            skill_path=skill_path,
            node_id=config.get("node_id") or meta.get("node_id", ""),
            name=config.get("name") or meta.get("name", ""),
            chain=config.get("chain") or meta.get("chain", ""),
            estimated_tokens=meta.get("estimated_tokens", 500),
            system_prompt=meta.get("system_prompt", ""),
            autonomy_boundary=meta.get("autonomy_boundary", ""),
            skill_content=meta.get("skill_content", ""),
        )


# ── SKILL 治理系统接入 ──────────────────────────────────

# DreamOS chain 映射（从 SKILL category 推断）
_CHAIN_MAP = {
    "trade": "T",
    "trading": "T",
    "intelligence": "G",
    "support": "G",
    "core": "C",
    "orchestration": "F",
    "governance": "F",
    "memory": "G",
    "uncategorized": "G",
}


def _infer_chain_from_category(category: str) -> str:
    """从 SKILL category 推断 DreamOS chain（A/C/F/G/T）。"""
    if not category:
        return "G"
    cat = category.lower().strip()
    return _CHAIN_MAP.get(cat, "G")


def _resolve_governance_dir() -> Optional[Path]:
    """定位 dream-skill-index-governance 目录。"""
    # dreamos/adapters/skill_adapter.py → dreamos → 1-ARCHITECTURE → repo root
    repo_root = Path(__file__).resolve().parents[3]
    candidate = repo_root / "1-ARCHITECTURE" / "skills" / "dream-skill-index-governance"
    if candidate.exists():
        return candidate
    return None


def load_skills_from_governance(registry) -> int:
    """通过 dream-skill-index-governance 统一索引加载 SKILL 节点。

    复用治理系统的 scan_skills()（覆盖 14 个 SKILL 根目录），
    用 parse_skill_metadata + SkillNode 创建可执行节点，
    注册到 NodeRegistry。

    FAIL-OPEN：治理系统不可用时返回 0，不阻塞启动。

    Args:
        registry: NodeRegistry 实例

    Returns:
        成功注册的 SKILL 节点数量
    """
    governance_dir = _resolve_governance_dir()
    if governance_dir is None:
        return 0

    try:
        import sys
        if str(governance_dir) not in sys.path:
            sys.path.insert(0, str(governance_dir))
        from skill_indexer import ALL_SKILL_ROOTS, scan_skills
    except Exception:
        return 0  # FAIL-OPEN：治理系统不可用

    try:
        entries = scan_skills(ALL_SKILL_ROOTS)
    except Exception:
        return 0  # FAIL-OPEN

    registered = 0
    for entry in entries:
        # 只加载 active 状态的 SKILL（治理系统生命周期过滤）
        if getattr(entry, "status", "active") != "active":
            continue

        skill_path = getattr(entry, "path", None)
        if skill_path is None or not Path(skill_path).exists():
            continue

        try:
            meta = parse_skill_metadata(str(skill_path))
            node_id = f"SKILL_{entry.name}"

            # 避免重复注册
            if registry.get(node_id) is not None:
                continue

            chain = _infer_chain_from_category(getattr(entry, "category", ""))

            node = SkillNode(
                skill_path=str(skill_path),
                node_id=node_id,
                name=entry.name,
                chain=chain,
                estimated_tokens=500,
                system_prompt=meta.get("system_prompt", ""),
                autonomy_boundary=meta.get("autonomy_boundary", ""),
                skill_content=meta.get("skill_content", ""),
            )
            registry.register(node)
            registered += 1
        except Exception:
            continue  # FAIL-OPEN：单个 SKILL 加载失败不阻塞其他

    return registered
