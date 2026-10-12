"""MasterSeminarCollector — v0.5 P3 DSH 层训练数据采集器.

从 6-TRADING/skills/master-seminar/reports/ 扫描 SEM_*.md 研讨报告，
按辩论 Round 拆分提取大师决策链。

设计 (SPEC v0.5 §3.5):
  - 扫描 master-seminar/reports/ 下 SEM_*.md 文件
  - 按 ### Round N 拆分，每个 Round 一条 case
  - 提取节点:
    - round_entry → Round 入口
    - master_statement({master}: {观点}) → 大师发言
    - camp_summary({阵营}: {总结}) → 阵营总结
    - key_dispute({争议点}) → 关键争议
    - final_position/concession/recommendation → 最终陈述
    - bias/conference → 结论
  - task: seminar.{seminar_id}.round{N}
  - outcome: success
  - 质量: A
  - FAIL-OPEN
"""
import os
import re
from typing import List, Optional

from interfaces.training_data_provider import TrainingDataProvider, TrainingCase


def _extract_seminar_id(md_text: str, filename: str) -> str:
    """从文本或文件名提取 seminar_id."""
    m = re.search(r'(?:研讨ID|SEM)[:：\s]*`?(SEM_\d+_\d+)`?', md_text)
    if m:
        return m.group(1)
    # 从文件名提取
    fn_m = re.search(r'(SEM_\d+_\d+)', filename)
    if fn_m:
        return fn_m.group(1)
    return "SEM_unknown"


def _extract_regime(md_text: str) -> str:
    """提取当前 Regime."""
    m = re.search(r'(?:当前Regime|regime)[:：\s]*`?(\w+)`?', md_text)
    return m.group(1) if m else "unknown"


def _parse_camp_assignment(md_text: str) -> List[str]:
    """解析阵营分配，提取大师节点."""
    nodes = []
    # 多方阵营
    bull_section = _extract_section(md_text, r'###\s*[🟢]*\s*多方阵营')
    if bull_section:
        for m in re.finditer(r'\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|', bull_section):
            master = m.group(1).strip()
            style = m.group(2).strip()
            if master and master not in ("大师", ":", "---") and len(master) > 1:
                nodes.append(f"camp_bull_master({master}:{style[:20]})")
    # 中立阵营
    neutral_section = _extract_section(md_text, r'###\s*[🟡]*\s*中立阵营')
    if neutral_section:
        for m in re.finditer(r'\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|', neutral_section):
            master = m.group(1).strip()
            style = m.group(2).strip()
            if master and master not in ("大师", ":", "---") and len(master) > 1:
                nodes.append(f"camp_neutral_master({master}:{style[:20]})")
    # 空方阵营
    bear_section = _extract_section(md_text, r'###\s*[🔴]*\s*空方阵营')
    if bear_section:
        for m in re.finditer(r'\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|', bear_section):
            master = m.group(1).strip()
            style = m.group(2).strip()
            if master and master not in ("大师", ":", "---") and len(master) > 1:
                nodes.append(f"camp_bear_master({master}:{style[:20]})")
    return nodes


def _parse_rounds(md_text: str) -> List[tuple]:
    """按 ### Round N 拆分辩论段落.

    返回 [(round_num, round_title, round_text), ...]
    """
    rounds = []
    for m in re.finditer(
        r'###\s*Round\s*(\d+)\s*[:：]\s*(.+?)(?=###\s*Round|\Z)',
        md_text, re.DOTALL
    ):
        rounds.append((m.group(1), m.group(2).strip(), m.group(2)))
    return rounds


def _parse_round_nodes(round_num: str, round_text: str) -> List[str]:
    """解析单个 Round 的决策节点."""
    nodes = [f"round{round_num}_entry()"]

    # 大师发言: **Master**: statement 或 🟢 **Master**: statement
    for m in re.finditer(
        r'[🟢🟡🔴]?\s*\*\*(.+?)\*\*\s*[:：]\s*(.+?)(?=\n[🟢🟡🔴]|\n---|\n阵营|\Z)',
        round_text, re.DOTALL
    ):
        master = m.group(1).strip()
        statement = m.group(2).strip().replace('\n', ' ')[:60]
        if master and len(master) > 1 and master not in ("关键争议",):
            nodes.append(f"master_statement({master}:{statement[:40]})")

    # 阵营总结
    for m in re.finditer(
        r'[🟢🟡🔴]?\s*[_]?\s*阵营总结\s*[:：]\s*(.+?)(?=\n---|\n###|\Z)',
        round_text, re.DOTALL
    ):
        summary = m.group(1).strip().replace('\n', ' ')[:50]
        nodes.append(f"camp_summary({summary})")

    # 关键争议
    dispute_section = re.search(r'(?:关键争议|⚖️\s*关键争议)\s*[:：]?\s*(.+?)(?=###|\Z)',
                                 round_text, re.DOTALL)
    if dispute_section:
        for item_m in re.finditer(r'^-\s+(.+)$', dispute_section.group(1), re.MULTILINE):
            dispute = item_m.group(1).strip()
            if dispute and len(dispute) > 3:
                nodes.append(f"key_dispute({dispute[:50]})")

    # 最终陈述: 坚守/让步/建议
    for m in re.finditer(r'^-\s+(坚守|让步|建议)\s*[:：]\s*(.+)$', round_text, re.MULTILINE):
        action_type = m.group(1)
        action_content = m.group(2).strip()
        nodes.append(f"final_{action_type}({action_content[:40]})")

    nodes.append(f"round{round_num}_exit()")
    return nodes


def _parse_conclusion(md_text: str) -> List[str]:
    """解析研讨结论."""
    nodes = ["conclusion_entry()"]
    concl_section = _extract_section(md_text, r'##\s*[📋]*\s*研讨结论')
    if concl_section:
        # 多空倾向
        bias_m = re.search(r'(?:倾向|bias)\s*[:：]\s*(.+)', concl_section)
        if bias_m:
            nodes.append(f"seminar_bias({bias_m.group(1).strip()[:40]})")
        # 置信度
        conf_m = re.search(r'(?:置信度|confidence)\s*[:：]\s*(\d+%)', concl_section)
        if conf_m:
            nodes.append(f"seminar_confidence({conf_m.group(1)})")
        # 大师一致性
        agree_m = re.search(r'(?:大师一致性|agreement)\s*[:：]\s*(\d+%)', concl_section)
        if agree_m:
            nodes.append(f"master_agreement({agree_m.group(1)})")
        # 可执行建议
        for m in re.finditer(r'^\d+\.\s+(.+)$', concl_section, re.MULTILINE):
            suggestion = m.group(1).strip()
            if suggestion and len(suggestion) > 3:
                nodes.append(f"actionable_suggestion({suggestion[:50]})")
        # 多方信号
        bull_section = _extract_section(concl_section, r'###\s*[🟢]*\s*多方信号')
        if bull_section:
            for m in re.finditer(r'^-\s+(.+)$', bull_section, re.MULTILINE):
                nodes.append(f"bull_signal({m.group(1).strip()[:40]})")
        # 空方信号
        bear_section = _extract_section(concl_section, r'###\s*[🔴]*\s*空方信号')
        if bear_section:
            for m in re.finditer(r'^-\s+(.+)$', bear_section, re.MULTILINE):
                nodes.append(f"bear_signal({m.group(1).strip()[:40]})")
        # 风险警告
        risk_section = _extract_section(concl_section, r'###\s*[⚠️]*\s*风险警告')
        if risk_section:
            for m in re.finditer(r'^-\s+(.+)$', risk_section, re.MULTILINE):
                nodes.append(f"risk_warning({m.group(1).strip()[:40]})")
    nodes.append("conclusion_exit()")
    return nodes


def _extract_section(md_text: str, heading_pattern: str) -> str:
    """提取 Markdown 章节内容."""
    m = re.search(heading_pattern, md_text)
    if not m:
        return ""
    start = m.end()
    heading_level = 0
    level_m = re.match(r'^(#+)', m.group(0).strip())
    if level_m:
        heading_level = len(level_m.group(1))
    next_heading = re.compile(r'^#{1,' + str(heading_level) + r'}\s+', re.MULTILINE)
    rest = md_text[start:]
    next_m = next_heading.search(rest)
    if next_m:
        return rest[:next_m.start()].strip()
    return rest.strip()


class MasterSeminarCollector(TrainingDataProvider):
    """大师研讨报告采集器.

    扫描 master-seminar/reports/ 下的 SEM_*.md 文件,
    按 Round 拆分提取大师辩论决策链作为 DSH 训练数据.
    """

    def __init__(self):
        _this_dir = os.path.dirname(os.path.abspath(__file__))
        _34_dir = os.path.dirname(_this_dir)
        _project_root = os.path.dirname(_34_dir)
        self.reports_root = os.path.join(
            _project_root, "6-TRADING", "skills", "master-seminar", "reports"
        )

    def get_source_name(self) -> str:
        return "master_seminar"

    def get_quality_threshold(self) -> str:
        return "A"

    def fetch_cases(
        self, limit: int = 100, since: Optional[str] = None
    ) -> List[TrainingCase]:
        """从研讨报告采集 TrainingCase (FAIL-OPEN)."""
        cases: List[TrainingCase] = []

        if not os.path.isdir(self.reports_root):
            return cases

        sem_files = []
        try:
            for fn in os.listdir(self.reports_root):
                if fn.endswith(".md") and "SEM" in fn:
                    sem_files.append(os.path.join(self.reports_root, fn))
        except Exception:
            return cases

        sem_files.sort()

        for sem_file in sem_files:
            if len(cases) >= limit:
                break
            try:
                with open(sem_file, "r", encoding="utf-8", errors="ignore") as f:
                    md_text = f.read()
                if not md_text.strip():
                    continue

                sem_id = _extract_seminar_id(md_text, os.path.basename(sem_file))
                regime = _extract_regime(md_text)

                # Case 1: 阵营分配 (camp_assignment)
                camp_nodes = _parse_camp_assignment(md_text)
                if len(camp_nodes) >= 3:
                    full_camp_nodes = ["camp_assignment_entry()"] + camp_nodes + ["camp_assignment_exit()"]
                    if len(full_camp_nodes) >= 5:
                        cases.append(TrainingCase(
                            intent=f"seminar.{sem_id}.camp",
                            actions=full_camp_nodes,
                            outcome_text="success",
                            learned=[f"seminar_id={sem_id}", f"regime={regime}",
                                     f"phase=camp_assignment"],
                            layer_tags=["DSH"],
                            quality="A",
                            confidence=0.75,
                            source="master_seminar",
                            metadata={
                                "outcome": "success",
                                "seminar_id": sem_id,
                                "regime": regime,
                                "phase": "camp_assignment",
                                "file": sem_file,
                                "node_count": len(full_camp_nodes),
                            },
                        ))

                # Case 2+: 每个 Round 一条 case
                rounds = _parse_rounds(md_text)
                for round_num, round_title, round_text in rounds:
                    if len(cases) >= limit:
                        break
                    round_nodes = _parse_round_nodes(round_num, round_text)
                    if len(round_nodes) >= 4:
                        # 补充节点到 ≥5
                        if len(round_nodes) < 5:
                            round_nodes.insert(1, f"round{round_num}_topic({round_title[:30]})")
                        cases.append(TrainingCase(
                            intent=f"seminar.{sem_id}.round{round_num}",
                            actions=round_nodes,
                            outcome_text="success",
                            learned=[f"seminar_id={sem_id}", f"regime={regime}",
                                     f"round={round_num}"],
                            layer_tags=["DSH"],
                            quality="A",
                            confidence=0.75,
                            source="master_seminar",
                            metadata={
                                "outcome": "success",
                                "seminar_id": sem_id,
                                "regime": regime,
                                "phase": f"round{round_num}",
                                "round_title": round_title[:60],
                                "file": sem_file,
                                "node_count": len(round_nodes),
                            },
                        ))

                # Case N: 结论
                concl_nodes = _parse_conclusion(md_text)
                if len(concl_nodes) >= 5:
                    cases.append(TrainingCase(
                        intent=f"seminar.{sem_id}.conclusion",
                        actions=concl_nodes,
                        outcome_text="success",
                        learned=[f"seminar_id={sem_id}", f"regime={regime}",
                                 f"phase=conclusion"],
                        layer_tags=["DSH"],
                        quality="A",
                        confidence=0.75,
                        source="master_seminar",
                        metadata={
                            "outcome": "success",
                            "seminar_id": sem_id,
                            "regime": regime,
                            "phase": "conclusion",
                            "file": sem_file,
                            "node_count": len(concl_nodes),
                        },
                    ))

            except Exception:
                continue

        return cases[:limit]
