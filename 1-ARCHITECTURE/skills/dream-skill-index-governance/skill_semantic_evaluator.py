"""SKILL 语义评估层 — 复用 dream-qwen-eval-collab 的千问评估环节

借鉴 dream-qwen-eval-collab 步骤 3 的 5 维评分框架，适配为 SKILL 内容质量评估：
1. 完整性 (completeness) — 必需字段是否齐全
2. 可落地性 (actionability) — triggers 是否精准、流程是否可执行
3. 工程适配性 (engineering_fit) — 是否符合 HC-1a/FAIL-OPEN/零回归
4. 风险识别 (risk_awareness) — 是否识别潜在风险
5. 表达清晰度 (clarity) — 文档是否清晰

执行：通过 bsk 调用千问（复用 dream-qwen-eval-collab 的 bsk 调用模板）
FAIL-OPEN：bsk 不可用 → 返回 None，不阻塞流程。
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Optional


# ───────────────────────────── 5 维评分定义 ─────────────────────────────

SKILL_EVAL_DIMENSIONS = [
    ("completeness", "完整性", "SKILL.md 必需字段（name/description/triggers/流程）是否齐全"),
    ("actionability", "可落地性", "triggers 是否精准、流程步骤是否可实际执行"),
    ("engineering_fit", "工程适配性", "是否符合 HC-1a（独立模块）/FAIL-OPEN/零回归约束"),
    ("risk_awareness", "风险识别", "是否识别并标注潜在风险（降级、边界条件）"),
    ("clarity", "表达清晰度", "文档结构是否清晰、描述是否无歧义"),
]


def build_eval_prompt(skill_content: str) -> str:
    """构造千问 SKILL 评审 prompt（复用 dream-qwen-eval-collab 5 维评分框架）。"""
    dims_desc = "\n".join(
        f"{i+1}. **{label}** ({key}): {desc}"
        for i, (key, label, desc) in enumerate(SKILL_EVAL_DIMENSIONS)
    )
    return f"""请作为 SKILL 质量评审专家，对以下 SKILL 文档进行 5 维评分（每项 0-10 分）。

## 评分维度
{dims_desc}

## 待评审 SKILL 内容
```markdown
{skill_content[:6000]}
```

## 输出要求
**严格返回 JSON**，不要多余文字，格式如下：
```json
{{
  "completeness": <0-10>,
  "actionability": <0-10>,
  "engineering_fit": <0-10>,
  "risk_awareness": <0-10>,
  "clarity": <0-10>,
  "overall": <5 维加权平均，保留 1 位小数>,
  "suggestions": ["改进建议1", "改进建议2"]
}}
```
"""


def parse_qwen_response(response: str) -> Optional[dict]:
    """从千问回复中解析 JSON 评分。

    支持 ```json ... ``` 代码块或裸 JSON。
    解析失败 → None（FAIL-OPEN）。
    """
    if not response:
        return None
    # 尝试提取 JSON 代码块
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response, re.DOTALL)
    json_str = m.group(1) if m else response.strip()
    # 如果不是代码块，尝试找第一个 { 到最后一个 }
    if not m:
        start = json_str.find("{")
        end = json_str.rfind("}")
        if start >= 0 and end > start:
            json_str = json_str[start:end + 1]
        else:
            return None
    try:
        data = json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        return None
    # 校验必需字段
    required = {"completeness", "actionability", "engineering_fit",
                "risk_awareness", "clarity", "overall"}
    if not required.issubset(data.keys()):
        return None
    # 确保 suggestions 是列表
    if "suggestions" not in data or not isinstance(data["suggestions"], list):
        data["suggestions"] = []
    return data


def evaluate_skill(
    skill_content: str,
    bsk_caller: Optional[Callable[[str], str]] = None,
) -> Optional[dict]:
    """评估 SKILL 内容质量。

    Args:
        skill_content: SKILL.md 全文
        bsk_caller: bsk 调用函数（接收 prompt，返回千问回复文本）
                    为 None 时返回 None（FAIL-OPEN，不阻塞）

    Returns:
        评分 dict 或 None
    """
    if bsk_caller is None:
        return None  # FAIL-OPEN
    prompt = build_eval_prompt(skill_content)
    try:
        response = bsk_caller(prompt)
    except Exception:
        return None  # FAIL-OPEN
    return parse_qwen_response(response)
