"""ASeriesSessionCollector — v0.5 P0 DSH 层训练数据采集器.

从 6-TRADING/sessions/ 目录扫描 A0-A9 各阶段 session 产物（Markdown），
用规则解析提取决策链作为 node_sequence，专供 DSH 层训练。

设计（SPEC v0.5 §2）:
  - 扫描 6-TRADING/sessions/2026* 子目录
  - 按文件名关键词映射到 A0-A9 阶段
  - Markdown 章节正则提取决策节点：
    - ### 矛盾N/C{N} (score/10) → identify 节点
    - **分辨率** / **结论** → resolution 节点
    - 偏差标志 / BIAS_FLAG → emit_bias_flag 节点
    - 阻力来源 / 趋势阶段 → first_principles 节点
  - task 构造: {phase}.{session_topic}.{date}
  - outcome: success (session 已完成)
  - FAIL-OPEN: 目录不存在/解析异常返回空或跳过
"""
import os
import re
from typing import List, Optional

from interfaces.training_data_provider import TrainingDataProvider, TrainingCase


# ============================================================
# A 阶段关键词映射
# ============================================================
A_PHASE_KEYWORDS = {
    "a0": ["contradiction_theory", "a0", "矛盾论"],
    "a1": ["contradiction", "a1", "矛盾分析", "daily_contradiction"],
    "a2": ["first_principles", "a2", "第一性原理", "first-principles", "阻力"],
    "a3": ["scenarios", "a3", "沙盘", "simulation", "推演"],
    "a4": ["tactical", "a4", "战术", "validator", "验证"],
    "a5": ["execution", "a5", "executor", "执行"],
    "a6": ["intelligence", "a6", "情报", "monitor"],
    "a7": ["practice", "a7", "实践论"],
    "a8": ["self_criticism", "a8", "theory_practice", "知行"],
    "a9": ["exit", "a9", "离场", "risk_event"],
    "oneirology": ["dream", "oneirology", "梦境", "做梦", "潜意识"],
}


def _detect_phase(filename: str) -> Optional[str]:
    """根据文件名检测 A 阶段."""
    name_lower = filename.lower()
    # 优先匹配明确的 a0-a9 前缀 (支持 - 和 _ 分隔)
    for phase in ["a0", "a1", "a2", "a3", "a4", "a5", "a6", "a7", "a8", "a9"]:
        if (name_lower.startswith(phase + "-") or name_lower.startswith(phase + "_")
                or f"-{phase}-" in name_lower or f"_{phase}_" in name_lower
                or f"_{phase}-" in name_lower or f"-{phase}_" in name_lower):
            return phase
    # 关键词匹配
    for phase, keywords in A_PHASE_KEYWORDS.items():
        if phase == "a0":
            continue
        for kw in keywords:
            if kw.lower() in name_lower:
                return phase
    # 文件名语义映射（无A前缀的文件）
    semantic_map = {
        "weekly-direction": "a1",      # 周线方向 = 战略调研
        "order-plan": "a5",             # 下单计划 = 执行
        "execution-log": "a5",          # 执行日志
        "validation_report": "a8",      # 验证报告 = 知行合一
        "validation-report": "a8",
        "raw": "a3",                    # raw/ 目录 = 沙盘推演原始
        "review": "a8",                # review = 反思
        "algorithm_research": "a1",    # 算法研究
    }
    for key, phase in semantic_map.items():
        if key in name_lower:
            return phase
    return None


def _extract_session_id_from_path(session_root: str, md_path: str) -> str:
    """从路径提取 session_id (sessions/<session_id>/...)."""
    try:
        rel = os.path.relpath(md_path, session_root)
        parts = rel.split(os.sep)
        if parts:
            return parts[0]
    except Exception:
        pass
    return "unknown_session"


def _extract_date_from_session_id(session_id: str) -> str:
    """从 session_id 提取日期 (如 20260603-BTC-SCREEN2 → 20260603)."""
    m = re.match(r"(\d{8})", session_id)
    return m.group(1) if m else "unknown_date"


def _extract_topic_from_session_id(session_id: str) -> str:
    """从 session_id 提取主题 (如 20260603-BTC-SCREEN2 → btc_screen2)."""
    parts = session_id.split("-", 1)
    if len(parts) < 2:
        return "unknown"
    topic = parts[1].lower().replace("-", "_")
    return re.sub(r"[^a-z0-9_]", "", topic)


def _parse_a1_contradiction(md_text: str) -> List[str]:
    """解析 A1 矛盾分析 session 提取决策链.

    支持两种格式:
      1. ### C{N}: {title} ({score}/10) 格式
      2. ### 矛盾{N}：{title} 格式
    """
    nodes = []

    # 模式1: C1/C2 格式 (with score)
    for m in re.finditer(r'###\s+C(\d+):\s*(.+?)\((\d+)/10\)', md_text):
        idx, title, score = m.group(1), m.group(2).strip(), m.group(3)
        nodes.append(f"identify_contradiction_{idx}({title},{score}/10)")
        # 提取该矛盾块的空方/多方论据
        block_start = m.end()
        next_block = md_text.find('### C', block_start)
        if next_block < 0:
            next_block = md_text.find('## ', block_start)
        block_text = md_text[block_start:next_block if next_block > 0 else len(md_text)]
        # 空方/多方论据
        if "**空方论据**" in block_text:
            nodes.append("collect_bear_argument()")
        if "**多方论据**" in block_text:
            nodes.append("collect_bull_argument()")
        # 矛盾性质
        for pm in re.finditer(r'\*\*矛盾性质\*\*\s*[:：]\s*(.+)', block_text):
            nodes.append(f"contradiction_property({pm.group(1).strip()[:40]})")

    # 模式2: 矛盾一/矛盾二 格式
    if not nodes:
        cn_nums = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5", "六": "6", "七": "7"}
        for m in re.finditer(r'###\s+矛盾([一二三四五六七八九十])\D*?[:：]\s*(.+)', md_text):
            cn_num, title = m.group(1), m.group(2).strip()
            num = cn_nums.get(cn_num, "0")
            nodes.append(f"identify_contradiction_{num}({title})")
            # 提取空方/多方
            block_start = m.end()
            next_block = md_text.find('### 矛盾', block_start)
            block_text = md_text[block_start:next_block if next_block > 0 else len(md_text)]
            if "**空方论据**" in block_text:
                nodes.append("collect_bear_argument()")
            if "**多方论据**" in block_text:
                nodes.append("collect_bull_argument()")
            for pm in re.finditer(r'\*\*矛盾性质\*\*\s*[:：]\s*(.+)', block_text):
                nodes.append(f"contradiction_property({pm.group(1).strip()[:40]})")

    # 列表项作为分析节点 (短项)
    for m in re.finditer(r'^-\s+(.+)$', md_text, re.MULTILINE):
        line = m.group(1).strip()
        if 5 < len(line) < 100 and not line.startswith("**"):
            nodes.append(f"analyze_point({line[:50]})")

    # 提取 **分辨率**: 或 **结论**:
    for m in re.finditer(r'\*\*(?:分辨率|结论)\*\*\s*[:：]\s*(.+)', md_text):
        resolution = m.group(1).strip()
        resolution = resolution[:80] if len(resolution) > 80 else resolution
        nodes.append(f"resolution({resolution})")

    # 提取主要矛盾结论
    for m in re.finditer(r'\*\*主要矛盾\*\*\s*[:：]\s*(.+)', md_text):
        nodes.append(f"identify_primary_contradiction({m.group(1).strip()[:60]})")

    # 矛盾评分
    for m in re.finditer(r'(\d+)[：:]\s*(\d+)\s*[/：]\s*10', md_text):
        nodes.append(f"score_contradiction({m.group(1)}:{m.group(2)}/10)")
    for m in re.finditer(r'矛盾评分\*\*\s*[:：]\s*(.+)', md_text):
        nodes.append(f"final_contradiction_score({m.group(1).strip()[:30]})")

    # 提取偏差标志 (两种格式)
    for m in re.finditer(r'^-\s+`([a-z_]+)`', md_text, re.MULTILINE):
        nodes.append(f"emit_bias_flag({m.group(1)})")
    for m in re.finditer(r'\[BIAS_FLAG:\s*([^\]]+)\]', md_text):
        nodes.append(f"emit_bias_flag({m.group(1).strip()[:50]})")

    return nodes


def _parse_a2_first_principles(md_text: str) -> List[str]:
    """解析 A2 第一性原理 session."""
    nodes = ["a2_entry()"]

    # 阻力来源表格行 (两种格式: 数值 bps / 文字描述)
    for m in re.finditer(r'\|\s*(.+?)\s*\|\s*([\d.]+)\s*bps\s*\|', md_text):
        nodes.append(f"analyze_resistance_{m.group(1).strip().lower()}({m.group(2)}bps)")
    for m in re.finditer(r'\|\s*(.+?)\s*\|\s*(高|低|中|无)\s*\|', md_text):
        nodes.append(f"analyze_resistance_{m.group(1).strip().lower()}({m.group(2)})")

    # 章节标题作为分析步骤
    for m in re.finditer(r'^##\s+(阻力来源|趋势阶段|趋势判断).+', md_text, re.MULTILINE):
        section = m.group(1).strip()
        nodes.append(f"analyze_{section}()")

    # 趋势阶段
    stage_match = re.search(r'当前阶段\s*[:：]\s*(.+)', md_text)
    if stage_match:
        nodes.append(f"determine_trend_stage({stage_match.group(1).strip()[:40]})")

    reverse_match = re.search(r'反向阻力\s*[:：]\s*(.+)', md_text)
    if reverse_match:
        nodes.append(f"assess_reverse_resistance({reverse_match.group(1).strip()[:40]})")

    # 结论
    for m in re.finditer(r'\*\*结论\*\*\s*[:：]\s*(.+)', md_text):
        nodes.append(f"resolution({m.group(1).strip()[:60]})")

    nodes.append("a2_exit()")
    return nodes


def _parse_a3_scenarios(md_text: str) -> List[str]:
    """解析 A3 沙盘推演 session."""
    nodes = []
    # 情景标记
    for m in re.finditer(r'##\s+情景[一二三四12345]\D*?[:：]\s*(.+)', md_text):
        nodes.append(f"simulate_scenario({m.group(1).strip()[:50]})")
    # S1/S2/S3 场景
    for m in re.finditer(r'###\s+S(\d+)\s*[:：]\s*(.+)', md_text):
        nodes.append(f"simulate_s{m.group(1)}_scenario({m.group(2).strip()[:50]})")
    # 推演结论
    for m in re.finditer(r'\*\*(?:推演结论|结论)\*\*\s*[:：]\s*(.+)', md_text):
        nodes.append(f"resolution({m.group(1).strip()[:60]})")
    return nodes


def _parse_oneirology(md_text: str) -> List[str]:
    """解析做梦部梦境 session (规则降级版,无LLM)."""
    nodes = []
    # 梦境标题
    for m in re.finditer(r'##\s+梦境[一二三四五六七八九十]+\D*?[:：]\s*(.+)', md_text):
        nodes.append(f"dream_theme({m.group(1).strip()[:50]})")
    # 弗洛伊德五机制关键词
    mechanisms = ["凝缩", "移置", "象征", "二次修正", "投射", "强迫性重复"]
    for mech in mechanisms:
        if mech in md_text:
            nodes.append(f"freud_mechanism_{mech}")
    # 创伤信号
    if "强迫性重复" in md_text or "创伤" in md_text:
        nodes.append("detect_trauma_signal()")
    # 解析章节
    if "**解析**" in md_text:
        nodes.append("dream_analysis_completed()")
    return nodes


def _parse_generic_a_phase(phase: str, md_text: str) -> List[str]:
    """通用 A 阶段解析: 提取章节+列表项作为决策节点."""
    nodes = [f"{phase}_entry()"]
    # 章节标题作为步骤
    for m in re.finditer(r'^##\s+(.+)$', md_text, re.MULTILINE):
        title = m.group(1).strip()
        if title and not title.startswith("#"):
            nodes.append(f"section({title[:50]})")
    # 决议/结论
    for m in re.finditer(r'\*\*(?:结论|决议|结果|执行)\*\*\s*[:：]\s*(.+)', md_text):
        nodes.append(f"resolution({m.group(1).strip()[:60]})")
    # 列表项 (短项)
    for m in re.finditer(r'^-\s+(.+)$', md_text, re.MULTILINE):
        line = m.group(1).strip()
        if len(line) < 80 and not line.startswith("*"):
            nodes.append(f"item({line[:50]})")
    nodes.append(f"{phase}_exit()")
    return nodes


def _parse_session_md(phase: str, md_text: str) -> List[str]:
    """根据 phase 分发到对应解析器."""
    if phase == "a1":
        nodes = _parse_a1_contradiction(md_text)
    elif phase == "a2":
        nodes = _parse_a2_first_principles(md_text)
    elif phase == "a3":
        nodes = _parse_a3_scenarios(md_text)
    elif phase == "oneirology":
        nodes = _parse_oneirology(md_text)
    else:
        nodes = _parse_generic_a_phase(phase, md_text)
    # 保底: 如果解析不出足够节点, 加 fallback
    if len(nodes) < 3:
        nodes.append(f"{phase}_minimal_parse()")
    return nodes


def _split_into_sub_cases(phase: str, md_text: str) -> List[tuple]:
    """将长 session 拆分为多个 sub_case, 每个返回 (sub_label, node_sequence).

    - A1 session 含多个 C1/C2/C3 矛盾块 → 每个独立 case
    - A3 session 含多个情景 → 每个独立 case
    - 做梦部含多个梦境 → 每个独立 case
    - 其他 phase 返回 [(None, full_node_seq)] 单条 case
    """
    sub_cases = []

    if phase == "a1":
        # 按矛盾块拆分
        # 模式1: ### C{N}: ... (score/10)
        c_blocks = re.split(r'(?=###\s+C\d+[:：])', md_text)
        if len(c_blocks) > 1:
            for block in c_blocks[1:]:  # 跳过前置部分
                m = re.match(r'###\s+C(\d+)', block)
                if not m:
                    continue
                c_idx = m.group(1)
                sub_nodes = _parse_a1_contradiction(block)
                # 补齐 entry/exit
                if not any("entry" in n for n in sub_nodes):
                    sub_nodes = ["a1_entry()"] + sub_nodes
                if not any("exit" in n for n in sub_nodes):
                    sub_nodes = sub_nodes + ["a1_exit()"]
                if len(sub_nodes) >= 3:
                    sub_cases.append((f"c{c_idx}", sub_nodes))
            # 合并: 主结论作为单独 case
            main_nodes = _parse_a1_contradiction(md_text)
            if len(main_nodes) >= 3:
                sub_cases.append(("main", main_nodes))
            return sub_cases if sub_cases else [(None, _parse_session_md(phase, md_text))]

        # 模式2: 矛盾一/矛盾二
        cn_blocks = re.split(r'(?=###\s+矛盾[一二三四五六七八九十])', md_text)
        if len(cn_blocks) > 1:
            cn_nums = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5"}
            for block in cn_blocks[1:]:
                m = re.match(r'###\s+矛盾([一二三四五六七八九十])', block)
                if not m:
                    continue
                num = cn_nums.get(m.group(1), "0")
                sub_nodes = _parse_a1_contradiction(block)
                if not any("entry" in n for n in sub_nodes):
                    sub_nodes = ["a1_entry()"] + sub_nodes
                if not any("exit" in n for n in sub_nodes):
                    sub_nodes = sub_nodes + ["a1_exit()"]
                if len(sub_nodes) >= 3:
                    sub_cases.append((f"contradict{num}", sub_nodes))
            if sub_cases:
                return sub_cases

    elif phase == "a3":
        # 按情景拆分
        scn_blocks = re.split(r'(?=##\s+情景[一二三四五六七八九十12345])', md_text)
        if len(scn_blocks) > 1:
            for block in scn_blocks[1:]:
                m = re.match(r'##\s+情景([一二三四五六七八九十12345])', block)
                if not m:
                    continue
                scn_label = m.group(1)
                sub_nodes = _parse_a3_scenarios(block)
                if len(sub_nodes) >= 3:
                    sub_cases.append((f"scenario_{scn_label}", sub_nodes))
            if sub_cases:
                return sub_cases
        # S1/S2/S3 模式
        s_blocks = re.split(r'(?=###\s+S\d+)', md_text)
        if len(s_blocks) > 1:
            for block in s_blocks[1:]:
                m = re.match(r'###\s+S(\d+)', block)
                if not m:
                    continue
                s_num = m.group(1)
                sub_nodes = _parse_a3_scenarios(block)
                if len(sub_nodes) >= 3:
                    sub_cases.append((f"s{s_num}", sub_nodes))
            if sub_cases:
                return sub_cases

    elif phase == "oneirology":
        # 按梦境拆分
        dream_blocks = re.split(r'(?=##\s+梦境[一二三四五六七八九十])', md_text)
        if len(dream_blocks) > 1:
            for block in dream_blocks[1:]:
                m = re.match(r'##\s+梦境([一二三四五六七八九十])', block)
                if not m:
                    continue
                d_num = m.group(1)
                sub_nodes = _parse_oneirology(block)
                if len(sub_nodes) >= 3:
                    sub_cases.append((f"dream_{d_num}", sub_nodes))
            if sub_cases:
                return sub_cases

    # 默认: 返回单条完整 case
    return [(None, _parse_session_md(phase, md_text))]


class ASeriesSessionCollector(TrainingDataProvider):
    """A 系列 session 产物采集器.

    扫描 6-TRADING/sessions/ 目录的 Markdown session 产物,
    按阶段关键词映射到 A0-A9, 用规则解析提取决策链作为 DSH 训练数据.
    """

    def __init__(self):
        # 默认 sessions 路径
        _this_dir = os.path.dirname(os.path.abspath(__file__))
        _34_dir = os.path.dirname(_this_dir)
        _project_root = os.path.dirname(_34_dir)
        self.sessions_root = os.path.join(_project_root, "6-TRADING", "sessions")

    def get_source_name(self) -> str:
        return "a_series_session"

    def get_quality_threshold(self) -> str:
        return "B"

    def fetch_cases(
        self, limit: int = 100, since: Optional[str] = None
    ) -> List[TrainingCase]:
        """从 6-TRADING/sessions/ 采集 TrainingCase.

        Args:
            limit: 最大返回数量
            since: 增量采集时间戳(可选)

        Returns:
            训练案例列表(FAIL-OPEN)
        """
        cases: List[TrainingCase] = []

        if not os.path.isdir(self.sessions_root):
            return cases

        # 收集所有 md 文件
        md_files = []
        try:
            for dirpath, _, filenames in os.walk(self.sessions_root):
                # 跳过 README 和 _template
                if "README" in dirpath or "_template" in dirpath:
                    continue
                for fn in filenames:
                    if fn.lower().endswith(".md") and fn.lower() != "readme.md":
                        md_files.append(os.path.join(dirpath, fn))
        except Exception:
            return cases

        # 按文件路径排序保证稳定
        md_files.sort()

        for md_path in md_files:
            if len(cases) >= limit:
                break
            try:
                filename = os.path.basename(md_path)
                phase = _detect_phase(filename)
                if phase is None:
                    continue  # 不是 A 系列 session 文件

                # 读取文件内容
                with open(md_path, "r", encoding="utf-8", errors="ignore") as f:
                    md_text = f.read()

                if not md_text.strip():
                    continue

                # 提取元数据
                session_id = _extract_session_id_from_path(self.sessions_root, md_path)
                date = _extract_date_from_session_id(session_id)
                topic = _extract_topic_from_session_id(session_id)

                # 从 frontmatter 或文本提取标题
                title_match = re.search(r'^#\s+(.+)$', md_text, re.MULTILINE)
                title = title_match.group(1).strip()[:60] if title_match else f"{phase}.{topic}"

                # 参数化生成: A1 session 含多个矛盾块 → 每个矛盾块独立 case
                sub_cases_raw = _split_into_sub_cases(phase, md_text)

                for sub_idx, (sub_label, sub_nodes) in enumerate(sub_cases_raw):
                    if len(sub_nodes) < 3:
                        continue
                    if len(cases) >= limit:
                        break

                    intent = f"{phase}.{topic}.{date}.{sub_label}" if sub_label else f"{phase}.{topic}.{date}"

                    cases.append(TrainingCase(
                        intent=intent,
                        actions=sub_nodes,
                        outcome_text="success",
                        learned=[
                            f"phase={phase}",
                            f"session_id={session_id}",
                            f"sub_case={sub_label or 'main'}",
                            f"node_count={len(sub_nodes)}",
                        ],
                        layer_tags=["DSH"],
                        quality="B",
                        confidence=0.6,
                        source="a_series_session",
                        metadata={
                            "outcome": "success",  # session 已完成 = ground truth
                            "session_id": session_id,
                            "phase": phase,
                            "date": date,
                            "topic": topic,
                            "file": md_path,
                            "title": title,
                            "sub_case": sub_label or "main",
                            "node_count": len(sub_nodes),
                        },
                    ))
            except Exception:
                # FAIL-OPEN: 单个文件异常跳过
                continue

        return cases[:limit]
