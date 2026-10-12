"""ASeriesTheoryCollector — v0.5 P1 DSH 层训练数据采集器.

从 6-TRADING/skills/ 目录扫描 A0-A9 各阶段 SKILL.md 理论文档，
用规则解析提取方法论决策链作为 node_sequence，专供 DSH 层训练。

设计（SPEC v0.5 §3）:
  - 扫描 6-TRADING/skills/ 下 10 个 A 系列 SKILL.md
  - 按目录名映射到 A0-A9 阶段
  - Markdown 章节正则提取决策节点：
    - ### Step N / Phase N → 工作流步骤节点
    - ## 章节标题 → section 节点
    - 表格行 | C{N} | ... | → classify 节点
    - 铁律/规则 → iron_law 节点
  - task 构造: {phase}.{theory_workflow}.{section}
  - outcome: success (方法论 = 已验证可执行)
  - 按章节拆分生成多条 case
  - FAIL-OPEN: 目录不存在/解析异常返回空或跳过
"""
import os
import re
from typing import List, Optional, Tuple

from interfaces.training_data_provider import TrainingDataProvider, TrainingCase


# ============================================================
# A 系列 SKILL 目录名 → 阶段映射
# ============================================================
SKILL_DIR_TO_PHASE = {
    "dream-contradiction-theory": "a0",
    "dream-strategy-research": "a1",
    "dream-first-principles": "a2",
    "dream-strategy-designer": "a3",
    "dream-tactical-validator": "a4",
    "dream-tactical-executor": "a5",
    "dream-intelligence-monitor": "a6",
    "A7-practice-theory": "a7",
    "A8-theory-practice-verification": "a8",
    "dream-exit-skill-v2": "a9",
}

# 反向映射：阶段 → 默认 intent 主题
PHASE_TO_TOPIC = {
    "a0": "contradiction_theory",
    "a1": "strategy_research",
    "a2": "first_principles",
    "a3": "strategy_design",
    "a4": "tactical_validation",
    "a5": "tactical_execution",
    "a6": "intelligence_monitor",
    "a7": "practice_theory",
    "a8": "theory_practice_verification",
    "a9": "exit_decision",
}


def _detect_phase_from_dir(dir_name: str) -> Optional[str]:
    """根据 SKILL 目录名检测 A 阶段."""
    # 精确匹配
    if dir_name in SKILL_DIR_TO_PHASE:
        return SKILL_DIR_TO_PHASE[dir_name]
    # 模糊匹配
    name_lower = dir_name.lower()
    for skill_dir, phase in SKILL_DIR_TO_PHASE.items():
        if skill_dir.lower() in name_lower or name_lower in skill_dir.lower():
            return phase
    # 关键词匹配
    kw_map = {
        "a0": ["contradiction", "矛盾论"],
        "a1": ["strategy-research", "strategy_research", "调研"],
        "a2": ["first-principles", "first_principles", "第一性原理"],
        "a3": ["strategy-designer", "strategy_designer", "沙盘"],
        "a4": ["tactical-validator", "tactical_validator", "战术验证"],
        "a5": ["tactical-executor", "tactical_executor", "战术执行"],
        "a6": ["intelligence-monitor", "intelligence_monitor", "情报"],
        "a7": ["practice-theory", "practice_theory", "实践论"],
        "a8": ["theory-practice", "theory_practice", "知行"],
        "a9": ["exit-skill", "exit_skill", "离场"],
    }
    for phase, keywords in kw_map.items():
        for kw in keywords:
            if kw.lower() in name_lower:
                return phase
    return None


def _parse_table_rows(md_text: str, section_start: int = 0) -> List[str]:
    """从 Markdown 表格行提取分类节点.

    支持两种格式:
      | C1 | 资金面矛盾 | ETF净流入 | ETF净流出 |
      | A0-IRON-1 | 矛盾普遍存在 |
    """
    nodes = []
    for m in re.finditer(r'\|\s*([A-Za-z0-9_\-]+)\s*\|(.+?)(?=\n|$)', md_text):
        cell_a = m.group(1).strip()
        rest = m.group(2).strip()
        # 跳过表头和分隔行
        if cell_a in ("---", ":", "|", "编号", "原理"):
            continue
        if re.match(r'^[-:|\s]+$', rest):
            continue
        # 提取第二列内容
        parts = rest.split("|")
        second_col = parts[0].strip() if parts else ""
        if second_col and len(second_col) > 1:
            nodes.append(f"classify_{cell_a}({second_col[:40]})")
        else:
            nodes.append(f"classify_{cell_a}()")
    return nodes


def _parse_a0_contradiction_theory(md_text: str) -> List[Tuple[str, List[str]]]:
    """解析 A0 矛盾论 SKILL.md — 按章节拆分多条 case.

    返回 [(sub_label, node_sequence), ...]
    """
    sub_cases = []

    # Case 1: 矛盾分类体系
    classify_section = _extract_section(md_text, r'##\s*二、矛盾分类体系')
    if classify_section:
        nodes = ["a0_entry()"]
        # 表格行 C1-C7
        for m in re.finditer(r'\|\s*(C\d+)\s*\|(.+?)(?=\n|$)', classify_section):
            c_id = m.group(1)
            rest = m.group(2).strip()
            parts = rest.split("|")
            dim_name = parts[0].strip() if parts else ""
            side_a = parts[1].strip() if len(parts) > 1 else ""
            side_b = parts[2].strip() if len(parts) > 2 else ""
            nodes.append(f"classify_contradiction_{c_id}({dim_name})")
            if side_a:
                nodes.append(f"analyze_side_a_{c_id}({side_a[:30]})")
            if side_b:
                nodes.append(f"analyze_side_b_{c_id}({side_b[:30]})")
        nodes.append("a0_classify_exit()")
        if len(nodes) >= 5:
            sub_cases.append(("classify", nodes))

    # Case 2: 三步法 (Step 1-3 分别为子 case)
    for step_match in re.finditer(
        r'###\s*Step\s*(\d+)\s*[:：]\s*(.+?)(?=###\s*Step|\Z)',
        md_text, re.DOTALL
    ):
        step_num = step_match.group(1)
        step_title = step_match.group(2).strip()
        step_body = step_match.group(2)
        nodes = [f"a0_step{step_num}_entry({step_title[:40]})"]
        # 列表项作为步骤
        for item_m in re.finditer(r'^-\s+(.+)$', step_body, re.MULTILINE):
            line = item_m.group(1).strip()
            if 3 < len(line) < 80 and not line.startswith("**"):
                nodes.append(f"step{step_num}_action({line[:50]})")
        nodes.append(f"a0_step{step_num}_exit()")
        if len(nodes) >= 4:
            sub_cases.append((f"step{step_num}", nodes))

    # Case 3: 铁律
    iron_section = _extract_section(md_text, r'##\s*四、矛盾论\d+大铁律')
    if iron_section:
        nodes = ["a0_iron_laws_entry()"]
        for m in re.finditer(r'\|\s*(A0-IRON-\d+)\s*\|\s*(.+?)\s*\|', iron_section):
            law_id = m.group(1)
            law_content = m.group(2).strip()
            nodes.append(f"iron_law_{law_id}({law_content[:40]})")
        nodes.append("a0_iron_laws_exit()")
        if len(nodes) >= 5:
            sub_cases.append(("iron_laws", nodes))

    # Case 4: 哲学基础 (如果前面 case 不足)
    phil_section = _extract_section(md_text, r'##\s*一、哲学基础')
    if phil_section:
        nodes = ["a0_philosophy_entry()"]
        for m in re.finditer(r'\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|', phil_section):
            principle = m.group(1).strip()
            nodes.append(f"philosophy_principle({principle[:30]})")
        nodes.append("a0_philosophy_exit()")
        if len(nodes) >= 4:
            sub_cases.append(("philosophy", nodes))

    # 保底: 如果没有拆分出 sub_case, 整体解析
    if not sub_cases:
        full_nodes = _parse_generic_theory("a0", md_text)
        if len(full_nodes) >= 3:
            sub_cases.append(("main", full_nodes))

    return sub_cases


def _parse_a2_first_principles(md_text: str) -> List[Tuple[str, List[str]]]:
    """解析 A2 第一性原理 SKILL.md — 按 Phase 拆分."""
    sub_cases = []

    # Case 1: 阻力来源分解
    resistance_section = _extract_section(md_text, r'###\s*原理1.*?阻力最小路径')
    if not resistance_section:
        resistance_section = _extract_section(md_text, r'阻力来源分解')
    if resistance_section:
        nodes = ["a2_resistance_entry()"]
        for m in re.finditer(r'\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|', resistance_section):
            r_type = m.group(1).strip()
            r_metric = m.group(2).strip()
            if r_type and r_type not in ("阻力类型", "---"):
                nodes.append(f"analyze_resistance_{r_type}({r_metric[:30]})")
        nodes.append("a2_resistance_exit()")
        if len(nodes) >= 4:
            sub_cases.append(("resistance", nodes))

    # Case 2: 趋势延续性
    trend_section = _extract_section(md_text, r'###\s*原理2.*?趋势延续性')
    if trend_section:
        nodes = ["a2_trend_entry()"]
        stage_match = re.search(r'趋势阶段\s*[:：]\s*(.+)', trend_section)
        if stage_match:
            stages_text = stage_match.group(1).strip()
            # 解析每个阶段: 启动期 → 加速期 → 衰竭期 → 逆转/盘整
            stages = re.split(r'[→\->]+', stages_text)
            for i, stage in enumerate(stages):
                stage = stage.strip()
                if stage and len(stage) > 1:
                    nodes.append(f"determine_trend_stage_{i}({stage[:30]})")
            nodes.append(f"determine_trend_stages({stages_text[:40]})")
        # 列表项
        for item_m in re.finditer(r'^-\s+(.+)$', trend_section, re.MULTILINE):
            line = item_m.group(1).strip()
            if 3 < len(line) < 80:
                nodes.append(f"trend_action({line[:50]})")
        nodes.append("a2_trend_exit()")
        if len(nodes) >= 4:
            sub_cases.append(("trend", nodes))

    # Case 3+: 执行流程 Phase 0-8 每个 Phase 一条 case
    for phase_m in re.finditer(
        r'Phase\s*(\d+)\s*[:：]\s*(.+?)(?=Phase\s*\d+|\Z)',
        md_text, re.DOTALL
    ):
        phase_num = phase_m.group(1)
        phase_body = phase_m.group(2)
        # 提取第一行作为标题
        lines = phase_body.strip().split('\n')
        phase_title = lines[0].strip() if lines else ""
        nodes = [f"a2_phase{phase_num}_entry()"]
        if phase_title:
            nodes.append(f"phase{phase_num}_goal({phase_title[:40]})")
        # 列表项
        for item_m in re.finditer(r'^-\s+(.+)$', phase_body, re.MULTILINE):
            line = item_m.group(1).strip()
            if 3 < len(line) < 80:
                nodes.append(f"phase{phase_num}_action({line[:50]})")
        nodes.append(f"a2_phase{phase_num}_exit()")
        if len(nodes) >= 5:
            sub_cases.append((f"phase{phase_num}", nodes))

    # 保底
    if not sub_cases:
        full_nodes = _parse_generic_theory("a2", md_text)
        if len(full_nodes) >= 3:
            sub_cases.append(("main", full_nodes))

    return sub_cases


def _parse_a5_tactical_executor(md_text: str) -> List[Tuple[str, List[str]]]:
    """解析 A5 战术执行 SKILL.md."""
    sub_cases = []

    # Case 1: 决策链路
    decision_section = _extract_section(md_text, r'##\s*决策链路')
    if decision_section:
        nodes = ["a5_decision_chain_entry()"]
        for item_m in re.finditer(r'^-\s+(.+)$', decision_section, re.MULTILINE):
            line = item_m.group(1).strip()
            if 3 < len(line) < 80:
                nodes.append(f"decision_step({line[:50]})")
        nodes.append("a5_decision_chain_exit()")
        if len(nodes) >= 4:
            sub_cases.append(("decision_chain", nodes))

    # Case 2: 执行前检查
    check_section = _extract_section(md_text, r'##\s*执行前检查')
    if check_section:
        nodes = ["a5_pre_check_entry()"]
        for m in re.finditer(r'^\d+\.\s+(.+)$', check_section, re.MULTILINE):
            line = m.group(1).strip()
            if 3 < len(line) < 80:
                nodes.append(f"pre_check({line[:50]})")
        nodes.append("a5_pre_check_exit()")
        if len(nodes) >= 4:
            sub_cases.append(("pre_check", nodes))

    # Case 3+: 执行流程 Phase
    for phase_m in re.finditer(
        r'Phase\s*(\d+)\s*[:：]\s*(.+?)(?=Phase\s*\d+|\Z)',
        md_text, re.DOTALL
    ):
        phase_num = phase_m.group(1)
        phase_title = phase_m.group(2).strip()
        nodes = [f"a5_phase{phase_num}_entry({phase_title[:40]})"]
        nodes.append(f"a5_phase{phase_num}_exit()")
        if len(nodes) >= 3:
            sub_cases.append((f"phase{phase_num}", nodes))

    # 保底
    if not sub_cases:
        full_nodes = _parse_generic_theory("a5", md_text)
        if len(full_nodes) >= 3:
            sub_cases.append(("main", full_nodes))

    return sub_cases


def _parse_a9_exit_skill(md_text: str) -> List[Tuple[str, List[str]]]:
    """解析 A9 离场决策 SKILL.md — 按四层拆分."""
    sub_cases = []

    # 四层决策链
    for layer_m in re.finditer(
        r'###\s*第([一二三四五六七八九十])层\s*[:：]\s*(.+?)(?=###\s*第|\Z)',
        md_text, re.DOTALL
    ):
        cn_num = layer_m.group(1)
        layer_title = layer_m.group(2).strip()
        layer_body = layer_m.group(2)
        cn_to_num = {"一": "1", "二": "2", "三": "3", "四": "4",
                     "五": "5", "六": "6", "七": "7", "八": "8"}
        layer_num = cn_to_num.get(cn_num, "0")
        nodes = [f"a9_layer{layer_num}_entry({layer_title[:40]})"]
        for item_m in re.finditer(r'^-\s+(.+)$', layer_body, re.MULTILINE):
            line = item_m.group(1).strip()
            if 3 < len(line) < 80:
                nodes.append(f"layer{layer_num}_trigger({line[:50]})")
        nodes.append(f"a9_layer{layer_num}_exit()")
        if len(nodes) >= 4:
            sub_cases.append((f"layer{layer_num}", nodes))

    # 保底
    if not sub_cases:
        full_nodes = _parse_generic_theory("a9", md_text)
        if len(full_nodes) >= 3:
            sub_cases.append(("main", full_nodes))

    return sub_cases


def _parse_generic_theory(phase: str, md_text: str) -> List[str]:
    """通用 A 阶段理论解析: 提取章节+列表项+步骤作为决策节点."""
    nodes = [f"{phase}_entry()"]

    # ## 章节标题作为步骤
    for m in re.finditer(r'^##\s+(.+)$', md_text, re.MULTILINE):
        title = m.group(1).strip()
        if title and not title.startswith("#"):
            nodes.append(f"section({title[:50]})")

    # ### 子章节
    for m in re.finditer(r'^###\s+(.+)$', md_text, re.MULTILINE):
        title = m.group(1).strip()
        if title and not title.startswith("#"):
            nodes.append(f"subsection({title[:50]})")

    # Step N / Phase N 步骤
    for m in re.finditer(r'(?:Step|Phase)\s*(\d+)\s*[:：]\s*(.+)', md_text):
        step_num = m.group(1)
        step_title = m.group(2).strip()
        nodes.append(f"step{step_num}({step_title[:40]})")

    # 列表项 (短项)
    for m in re.finditer(r'^-\s+(.+)$', md_text, re.MULTILINE):
        line = m.group(1).strip()
        if 3 < len(line) < 80 and not line.startswith("*"):
            nodes.append(f"action({line[:50]})")

    # 决议/结论
    for m in re.finditer(r'\*\*(?:结论|决议|结果)\*\*\s*[:：]\s*(.+)', md_text):
        nodes.append(f"resolution({m.group(1).strip()[:60]})")

    nodes.append(f"{phase}_exit()")
    return nodes


def _extract_section(md_text: str, heading_pattern: str) -> str:
    """提取 Markdown 章节内容 (从匹配标题到下一个同级标题).

    Args:
        md_text: 完整 Markdown 文本
        heading_pattern: 章节标题正则 (如 r'##\\s*二、矛盾分类体系')

    Returns:
        章节内容 (标题行之后到下一个同级标题之前)
    """
    m = re.search(heading_pattern, md_text)
    if not m:
        return ""
    start = m.end()
    # 找到下一个同级标题
    heading_level = 0
    level_m = re.match(r'^(#+)', m.group(0).strip())
    if level_m:
        heading_level = len(level_m.group(1))

    # 搜索下一个同级或更高级标题
    next_heading = re.compile(r'^#{1,' + str(heading_level) + r'}\s+', re.MULTILINE)
    rest = md_text[start:]
    next_m = next_heading.search(rest)
    if next_m:
        return rest[:next_m.start()].strip()
    return rest.strip()


def _split_into_sub_cases(phase: str, md_text: str) -> List[Tuple[str, List[str]]]:
    """将 SKILL.md 理论文档按章节拆分为多条 sub_case.

    每个 sub_case 返回 (sub_label, node_sequence).
    """
    if phase == "a0":
        return _parse_a0_contradiction_theory(md_text)
    elif phase == "a2":
        return _parse_a2_first_principles(md_text)
    elif phase == "a5":
        return _parse_a5_tactical_executor(md_text)
    elif phase == "a9":
        return _parse_a9_exit_skill(md_text)
    else:
        # 通用解析: 按主要章节拆分
        return _parse_generic_with_split(phase, md_text)


def _parse_generic_with_split(phase: str, md_text: str) -> List[Tuple[str, List[str]]]:
    """通用理论解析: 按 ## 章节拆分多条 case."""
    sub_cases = []

    # 按 ## 章节拆分
    sections = re.split(r'(?=^##\s+)', md_text, flags=re.MULTILINE)
    for section in sections:
        title_m = re.match(r'^##\s+(.+)$', section, re.MULTILINE)
        if not title_m:
            continue
        title = title_m.group(1).strip()
        # 跳过不重要的章节 (如 Autonomy Boundary, 合规要求)
        skip_titles = ["autonomy", "合规", "版本记录", "faq", "踩坑", "邮件",
                       "投递", "调度", "约束", "集成"]
        if any(sk in title.lower() for sk in skip_titles):
            continue

        nodes = [f"{phase}_section_entry({title[:40]})"]
        # ### 子章节
        for m in re.finditer(r'^###\s+(.+)$', section, re.MULTILINE):
            sub_title = m.group(1).strip()
            if sub_title and not sub_title.startswith("#"):
                nodes.append(f"subsection({sub_title[:50]})")
        # 列表项
        for m in re.finditer(r'^-\s+(.+)$', section, re.MULTILINE):
            line = m.group(1).strip()
            if 3 < len(line) < 80 and not line.startswith("*"):
                nodes.append(f"action({line[:50]})")
        # Step/Phase
        for m in re.finditer(r'(?:Step|Phase)\s*(\d+)\s*[:：]\s*(.+)', section):
            nodes.append(f"step{m.group(1)}({m.group(2).strip()[:40]})")
        nodes.append(f"{phase}_section_exit()")

        if len(nodes) >= 4:
            # 从标题提取 label
            label = re.sub(r'[^a-zA-Z0-9_\u4e00-\u9fff]', '_', title[:20]).strip("_").lower()
            if not label:
                label = "section"
            sub_cases.append((label, nodes))

    # 保底
    if not sub_cases:
        full_nodes = _parse_generic_theory(phase, md_text)
        if len(full_nodes) >= 3:
            sub_cases.append(("main", full_nodes))

    return sub_cases


class ASeriesTheoryCollector(TrainingDataProvider):
    """A0-A9 理论文档采集器.

    扫描 6-TRADING/skills/ 目录的 SKILL.md 理论文档,
    按目录名映射到 A0-A9 阶段, 用规则解析提取方法论决策链作为 DSH 训练数据.
    """

    def __init__(self):
        _this_dir = os.path.dirname(os.path.abspath(__file__))
        _34_dir = os.path.dirname(_this_dir)
        _project_root = os.path.dirname(_34_dir)
        self.skills_root = os.path.join(_project_root, "6-TRADING", "skills")

    def get_source_name(self) -> str:
        return "a_series_theory"

    def get_quality_threshold(self) -> str:
        return "A"

    def fetch_cases(
        self, limit: int = 100, since: Optional[str] = None
    ) -> List[TrainingCase]:
        """从 6-TRADING/skills/ 采集 TrainingCase.

        Args:
            limit: 最大返回数量
            since: 增量采集时间戳(可选)

        Returns:
            训练案例列表(FAIL-OPEN)
        """
        cases: List[TrainingCase] = []

        if not os.path.isdir(self.skills_root):
            return cases

        # 收集所有 SKILL.md 文件
        skill_files = []
        try:
            for entry in os.listdir(self.skills_root):
                skill_dir = os.path.join(self.skills_root, entry)
                if not os.path.isdir(skill_dir):
                    continue
                skill_md = os.path.join(skill_dir, "SKILL.md")
                if os.path.isfile(skill_md):
                    skill_files.append((entry, skill_md))
        except Exception:
            return cases

        # 按目录名排序保证稳定
        skill_files.sort(key=lambda x: x[0])

        for skill_dirname, skill_md_path in skill_files:
            if len(cases) >= limit:
                break
            try:
                phase = _detect_phase_from_dir(skill_dirname)
                if phase is None:
                    continue  # 不是 A 系列理论 SKILL

                # 读取文件内容
                with open(skill_md_path, "r", encoding="utf-8", errors="ignore") as f:
                    md_text = f.read()

                if not md_text.strip():
                    continue

                # 从 frontmatter 提取 name
                name_match = re.search(r'^name:\s*(.+)$', md_text, re.MULTILINE)
                skill_name = name_match.group(1).strip() if name_match else skill_dirname

                # 从标题提取
                title_match = re.search(r'^#\s+(.+)$', md_text, re.MULTILINE)
                title = title_match.group(1).strip()[:60] if title_match else f"{phase}.{skill_dirname}"

                topic = PHASE_TO_TOPIC.get(phase, "theory")

                # 按章节拆分生成多条 case
                sub_cases_raw = _split_into_sub_cases(phase, md_text)

                for sub_label, sub_nodes in sub_cases_raw:
                    if len(sub_nodes) < 3:
                        continue
                    if len(cases) >= limit:
                        break

                    intent = f"{phase}.{topic}.{sub_label}"

                    cases.append(TrainingCase(
                        intent=intent,
                        actions=sub_nodes,
                        outcome_text="success",
                        learned=[
                            f"phase={phase}",
                            f"skill={skill_name}",
                            f"sub_case={sub_label}",
                            f"node_count={len(sub_nodes)}",
                        ],
                        layer_tags=["DSH"],
                        quality="A",
                        confidence=0.75,
                        source="a_series_theory",
                        metadata={
                            "outcome": "success",
                            "theory_skill": skill_name,
                            "phase": phase,
                            "skill_dir": skill_dirname,
                            "file": skill_md_path,
                            "title": title,
                            "sub_case": sub_label,
                            "node_count": len(sub_nodes),
                        },
                    ))
            except Exception:
                # FAIL-OPEN: 单个 SKILL 异常跳过
                continue

        return cases[:limit]
