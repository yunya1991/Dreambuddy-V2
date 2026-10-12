"""OneirologyDreamCollector — v0.5 P2 DSH 层训练数据采集器.

从 6-TRADING/sessions/ 目录递归扫描梦境日志文件 (dream_journal_*.md)，
用规则解析提取弗洛伊德5大机制 + 创伤信号 + 梦境主题作为决策链。

设计 (SPEC v0.5 §3.4):
  - 递归扫描 sessions_root 下 dream_journal_*.md / dream_brainstorm_daily_*.md
  - 按 ## 梦境N (支持阿拉伯/中文数字) 拆分多个梦境
  - 提取节点:
    - dream_theme → dream_theme 节点
    - freud_mechanism_{凝缩/移置/象征/二次修正/投射} (支持 - 字段格式 和 **加粗** 格式)
    - detect_trauma_signal → trauma 节点
    - dream_analysis_completed → resolution 节点
    - 大胆观点/可能性 → hypothesis 节点
  - task 构造: oneirology.dream.{dream_id}
  - outcome: success
  - 质量: S
  - FAIL-OPEN
"""
import os
import re
from typing import List, Optional

from interfaces.training_data_provider import TrainingDataProvider, TrainingCase


# 弗洛伊德5大机制 (中文 → 英文标识)
FREUD_MECHANISMS = {
    "凝缩": "condensation",
    "移置": "displacement",
    "象征": "symbol",
    "二次修正": "secondary_revision",
    "投射": "projection",
}

# 中文数字映射
CN_NUM_MAP = {"一": "1", "二": "2", "三": "3", "四": "4",
              "五": "5", "六": "6", "七": "7", "八": "8",
              "九": "9", "十": "10"}


def _is_dream_journal(filename: str) -> bool:
    """判断文件是否为梦境日志."""
    name_lower = filename.lower()
    return ("dream" in name_lower or "oneirology" in name_lower
            or "brainstorm_daily" in name_lower)


def _cn_to_num(cn: str) -> str:
    """中文数字转阿拉伯数字."""
    return CN_NUM_MAP.get(cn, cn)


def _parse_dream_section(dream_text: str, dream_id: str) -> List[str]:
    """解析单个梦境段落，提取决策节点.

    支持两种格式:
      1. 字段格式: - freud_mechanism_凝缩: 内容
      2. 加粗格式: **凝缩效应**: 内容 / **移置追踪**: 内容
    """
    nodes = [f"dream_{dream_id}_entry()"]

    # dream_theme (字段格式)
    theme_m = re.search(r'dream_theme\s*[:：]\s*(.+)', dream_text)
    theme = ""
    if theme_m:
        theme = theme_m.group(1).strip()
        nodes.append(f"dream_theme({theme[:50]})")
    else:
        # 尝试从梦境标题提取主题
        title_m = re.search(r'^[>#\s]*(.+?)(?:的|——|—|-|\n)', dream_text)
        if title_m:
            theme = title_m.group(1).strip()[:50]
            if theme and len(theme) > 2:
                nodes.append(f"dream_theme({theme})")

    # freud_mechanism (5大机制) — 支持字段格式和加粗格式
    for cn_name, en_name in FREUD_MECHANISMS.items():
        # 格式1: - freud_mechanism_凝缩: 内容
        pattern1 = (
            r'freud_mechanism[_\s]*(?:' + cn_name + r'|' + en_name + r')\s*[:：]\s*(.+)'
        )
        m1 = re.search(pattern1, dream_text, re.IGNORECASE)
        if m1:
            nodes.append(f"freud_mechanism_{en_name}({m1.group(1).strip()[:50]})")
            continue

        # 格式2: **凝缩效应** 或 **凝缩** 后跟内容
        pattern2 = r'\*\*' + cn_name + r'(?:效应|机制|追踪|分析)?\*\*\s*[:：]?\s*(.+?)(?:\n|$)'
        m2 = re.search(pattern2, dream_text)
        if m2:
            nodes.append(f"freud_mechanism_{en_name}({m2.group(1).strip()[:50]})")
            continue

        # 格式3: 纯文本提及 "凝缩" 作为列表项
        pattern3 = r'^-\s+\*\*' + cn_name + r'(?:\*\*)?\s*[:：]?\s*(.+?)(?:\n|$)'
        m3 = re.search(pattern3, dream_text, re.MULTILINE)
        if m3:
            nodes.append(f"freud_mechanism_{en_name}({m3.group(1).strip()[:50]})")

    # detect_trauma_signal (支持字段格式和加粗格式)
    trauma_patterns = [
        r'detect_trauma_signal\s*[:：]\s*(.+)',
        r'\*\*创伤源头\*\*\s*[:：]?\s*(.+?)(?:\n|$)',
        r'\*\*创伤(?:信号|源)\*\*\s*[:：]?\s*(.+?)(?:\n|$)',
    ]
    trauma_found = False
    for pat in trauma_patterns:
        tm = re.search(pat, dream_text)
        if tm:
            trauma = tm.group(1).strip()
            if trauma and trauma.lower() not in ("无", "none", "n/a"):
                nodes.append(f"detect_trauma_signal({trauma[:50]})")
            else:
                nodes.append("detect_trauma_signal(none)")
            trauma_found = True
            break
    if not trauma_found:
        # 检查是否有强迫性重复
        comp_m = re.search(r'强迫性重复', dream_text)
        if comp_m:
            # 提取上下文
            ctx_m = re.search(r'强迫性重复[——：:\s]*(.+?)(?:\n|$)', dream_text)
            if ctx_m:
                nodes.append(f"detect_trauma_signal(强迫性重复:{ctx_m.group(1).strip()[:40]})")

    # dream_analysis_completed
    analysis_m = re.search(
        r'dream_analysis_completed\s*[:：]\s*(.+)', dream_text
    )
    if analysis_m:
        nodes.append(f"dream_analysis_completed({analysis_m.group(1).strip()[:60]})")

    # 大胆观点/可能性 (额外节点)
    hypothesis_m = re.search(r'\*\*大胆观点\*\*\s*[:：]?\s*(.+?)(?:\n|$)', dream_text)
    if hypothesis_m:
        nodes.append(f"dream_hypothesis({hypothesis_m.group(1).strip()[:50]})")

    # 可能性
    poss_m = re.search(r'可能性\s*[:：]\s*(\d+%)', dream_text)
    if poss_m:
        nodes.append(f"dream_possibility({poss_m.group(1)})")

    # 额外列表项作为补充节点 (排除已处理的字段)
    exclude_kw = ("dream_theme", "freud_mechanism", "detect_trauma",
                  "dream_analysis", "大胆观点", "可能性")
    for item_m in re.finditer(r'^-\s+(.+)$', dream_text, re.MULTILINE):
        line = item_m.group(1).strip()
        if 3 < len(line) < 80 and not any(kw in line for kw in exclude_kw):
            # 去掉 ** 标记
            clean = re.sub(r'\*\*', '', line)
            nodes.append(f"dream_observation({clean[:50]})")

    nodes.append(f"dream_{dream_id}_exit()")
    return nodes


def _split_dreams(md_text: str) -> List[tuple]:
    """将梦境日志按 ## 梦境N 拆分 (支持阿拉伯和中文数字).

    返回 [(dream_num, dream_title, dream_text), ...]
    """
    dreams = []

    # 格式1: ## 梦境1: 标题 (阿拉伯数字)
    for m in re.finditer(
        r'##\s*梦境\s*(\d+)\s*[:：]\s*(.+?)(?=##\s*梦境|\Z)',
        md_text, re.DOTALL
    ):
        dreams.append((m.group(1), m.group(2).strip(), m.group(2)))

    if not dreams:
        # 格式2: ## 梦境一：标题 (中文数字)
        for m in re.finditer(
            r'##\s*梦境\s*([一二三四五六七八九十])\s*[:：]\s*(.+?)(?=##\s*梦境|\Z)',
            md_text, re.DOTALL
        ):
            cn_num = m.group(1)
            num = _cn_to_num(cn_num)
            dreams.append((num, m.group(2).strip(), m.group(2)))

    if not dreams:
        # 格式3: ## Dream 1: title (英文)
        for m in re.finditer(
            r'##\s*[Dd]ream\s*(\d+)\s*[:：]\s*(.+?)(?=##\s*[Dd]ream|\Z)',
            md_text, re.DOTALL
        ):
            dreams.append((m.group(1), m.group(2).strip(), m.group(2)))

    return dreams


def _find_dream_files(root: str) -> List[str]:
    """递归扫描目录下的梦境日志文件."""
    result = []
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            for fn in filenames:
                if fn.endswith(".md") and _is_dream_journal(fn):
                    result.append(os.path.join(dirpath, fn))
    except Exception:
        pass
    return sorted(result)


class OneirologyDreamCollector(TrainingDataProvider):
    """梦境日志采集器.

    递归扫描 6-TRADING/sessions/ 下的 dream_journal_*.md 文件,
    按梦境拆分提取弗洛伊德机制+创伤信号+梦境主题作为 DSH 训练数据.
    """

    def __init__(self):
        _this_dir = os.path.dirname(os.path.abspath(__file__))
        _34_dir = os.path.dirname(_this_dir)
        _project_root = os.path.dirname(_34_dir)
        self.sessions_root = os.path.join(_project_root, "6-TRADING", "sessions")

    def get_source_name(self) -> str:
        return "oneirology_dream"

    def get_quality_threshold(self) -> str:
        return "S"

    def fetch_cases(
        self, limit: int = 100, since: Optional[str] = None
    ) -> List[TrainingCase]:
        """从梦境日志采集 TrainingCase (FAIL-OPEN)."""
        cases: List[TrainingCase] = []

        if not os.path.isdir(self.sessions_root):
            return cases

        dream_files = _find_dream_files(self.sessions_root)

        for dream_file in dream_files:
            if len(cases) >= limit:
                break
            try:
                with open(dream_file, "r", encoding="utf-8", errors="ignore") as f:
                    md_text = f.read()

                if not md_text.strip():
                    continue

                date_m = re.search(r'(\d{8})', os.path.basename(dream_file))
                file_date = date_m.group(1) if date_m else "unknown"

                dreams = _split_dreams(md_text)

                for dream_num, dream_title, dream_body in dreams:
                    if len(cases) >= limit:
                        break

                    dream_id = f"{file_date}_{dream_num}"
                    nodes = _parse_dream_section(dream_body, dream_id)

                    if len(nodes) < 3:
                        continue

                    theme = ""
                    theme_m = re.search(r'dream_theme\s*[:：]\s*(.+)', dream_body)
                    if theme_m:
                        theme = theme_m.group(1).strip()
                    if not theme:
                        theme = dream_title[:50] if dream_title else "unspecified"

                    intent = f"oneirology.dream.{dream_id}"

                    cases.append(TrainingCase(
                        intent=intent,
                        actions=nodes,
                        outcome_text="success",
                        learned=[
                            f"dream_id={dream_id}",
                            f"dream_theme={theme}",
                            f"node_count={len(nodes)}",
                        ],
                        layer_tags=["DSH"],
                        quality="S",
                        confidence=0.85,
                        source="oneirology_dream",
                        metadata={
                            "outcome": "success",
                            "dream_theme": theme,
                            "dream_id": dream_id,
                            "file": dream_file,
                            "file_date": file_date,
                            "dream_title": dream_title[:60] if dream_title else "",
                            "node_count": len(nodes),
                        },
                    ))

                # 保底: 无梦境拆分时整体解析
                if not dreams and len(cases) < limit:
                    nodes = _parse_dream_section(md_text, file_date)
                    if len(nodes) >= 5:
                        theme = ""
                        theme_m = re.search(r'dream_theme\s*[:：]\s*(.+)', md_text)
                        if theme_m:
                            theme = theme_m.group(1).strip()
                        cases.append(TrainingCase(
                            intent=f"oneirology.dream.{file_date}",
                            actions=nodes,
                            outcome_text="success",
                            learned=[f"dream_id={file_date}",
                                     f"dream_theme={theme}"],
                            layer_tags=["DSH"],
                            quality="S",
                            confidence=0.85,
                            source="oneirology_dream",
                            metadata={
                                "outcome": "success",
                                "dream_theme": theme if theme else "unspecified",
                                "dream_id": file_date,
                                "file": dream_file,
                                "file_date": file_date,
                                "node_count": len(nodes),
                            },
                        ))

            except Exception:
                continue

        return cases[:limit]
