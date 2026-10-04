"""
25-用户策略生成系统 - 策略生成器

基于 LLM + 成熟策略模板，从用户意图生成可执行的 Freqtrade 策略代码。
生成后自动进行语法检查和 lookahead 未来函数检测。
"""
from __future__ import annotations

import ast
import re
import uuid
from pathlib import Path
from typing import Optional

from .llm_client import call_llm
from .template import STRATEGY_TEMPLATE, get_template_fields


# 策略输出目录（与 10-经典指标系统 共享策略目录）
_STRATEGY_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "10-经典指标系统" / "user_data" / "strategies"

# 未来函数模式（lookahead bias）
_LOOKAHEAD_PATTERNS = [
    (r"shift\(-\d+\)", "使用未来数据 shift(-n)"),
    (r"iloc\[-1\]", "使用最后一根K线 iloc[-1]（可能引入未来）"),
    (r"iloc\[1:\]", "使用未来数据切片 iloc[1:]"),
    (r"rolling\([^)]*\)\.shift\(-\d+\)", "未来滚动窗口"),
]


SYSTEM_PROMPT = """你是资深量化交易策略工程师，精通 Freqtrade 框架和 Python 技术分析。

你的任务是根据用户的策略意图，生成一个完整、可执行的 Freqtrade 策略代码。

要求：
1. 严格按照提供的模板结构生成
2. 指标计算必须使用 talib.abstract (ta) 或 qtpylib
3. 入场/出场条件必须明确，使用 dataframe 的指标列
4. 必须包含 Hyperopt 参数（IntParameter / DecimalParameter）
5. 禁止使用未来函数：shift(-n)、iloc[-1]、iloc[1:] 等
6. 代码必须语法正确，可以直接运行
7. 止损、止盈要合理
8. 【关键】入场条件用 AND（全部满足才入场，模板已用 x & y）；
   出场条件用 OR（任一满足即出场，模板已用 x | y）。
   不要把出场条件也写成全部满足才出场，否则极少触发出场。

只输出代码块，不要其他解释。"""


def build_prompt(intent: str, symbol: str = "", timeframe: str = "1h") -> str:
    """构造 LLM prompt。"""
    fields = get_template_fields()
    fields_desc = "\n".join(f"- {k}: {v}" for k, v in fields.items())

    return f"""请根据以下用户意图生成一个 Freqtrade 策略。

【用户意图】
{intent}

【交易标的】{symbol or "多币种通用"}
【K线周期】{timeframe}

【模板字段说明】
{fields_desc}

【模板骨架】
{STRATEGY_TEMPLATE}

【输出要求】
请直接输出完整的 Python 策略代码，包含：
1. 所有必要的 import（包括 import functools）
2. 完整的类定义
3. 具体的指标计算
4. 明确的入场/出场条件

注意：
- populate_entry_trend 中使用 functools.reduce(lambda x, y: x & y, conditions) 合并入场条件（AND 逻辑：全部满足才入场）
- populate_exit_trend 中使用 functools.reduce(lambda x, y: x | y, conditions) 合并出场条件（OR 逻辑：任一满足即出场）
- 出场条件不要用 crossed_below 作为唯一或主要条件，应结合 RSI 超买/超卖、价格跌破均线等持续有效条件"""


def extract_code(llm_output: str) -> str:
    """从 LLM 输出中提取代码块。"""
    # 尝试匹配 ```python ... ``` 或 ``` ... ```
    match = re.search(r"```(?:python)?\s*\n(.*?)```", llm_output, re.DOTALL)
    if match:
        return match.group(1).strip()

    # 如果没有代码块，尝试找 class 定义开始
    class_match = re.search(r"(class\s+\w+\s*\(.*?\))", llm_output)
    if class_match:
        # 从 import 开始截取
        import_match = re.search(r"(^# pragma|^import |^from )", llm_output, re.MULTILINE)
        if import_match:
            return llm_output[import_match.start():].strip()

    return llm_output.strip()


def validate_syntax(code: str) -> tuple[bool, str]:
    """验证 Python 语法。"""
    try:
        ast.parse(code)
        return True, ""
    except SyntaxError as e:
        return False, f"语法错误: line {e.lineno}: {e.msg}"


def check_lookahead(code: str) -> list[dict]:
    """检测未来函数（lookahead bias）。"""
    issues = []
    for pattern, desc in _LOOKAHEAD_PATTERNS:
        matches = re.finditer(pattern, code)
        for m in matches:
            line_num = code[:m.start()].count("\n") + 1
            issues.append({
                "line": line_num,
                "pattern": m.group(),
                "description": desc,
                "severity": "high",
            })
    return issues


def sanitize_class_name(name: str) -> str:
    """清理类名，确保 PascalCase。"""
    # 移除非字母数字
    name = re.sub(r"[^a-zA-Z0-9]", "", name)
    if not name:
        return "GeneratedStrategy"
    # 首字母大写
    return name[0].upper() + name[1:]


def generate_strategy(
    intent: str,
    *,
    symbol: str = "",
    timeframe: str = "1h",
    save: bool = True,
) -> dict:
    """从用户意图生成策略代码。

    Args:
        intent: 用户策略意图描述
        symbol: 交易标的
        timeframe: K线周期
        save: 是否保存到策略目录

    Returns:
        {
            ok: bool,
            strategy_name: str,
            code: str,
            file_path: str | None,
            syntax_valid: bool,
            syntax_error: str,
            lookahead_issues: list,
        }
    """
    # 1. 调用 LLM 生成策略
    prompt = build_prompt(intent, symbol, timeframe)
    llm_output = call_llm(
        prompt=prompt,
        system=SYSTEM_PROMPT,
        max_tokens=6000,
        purpose="strategy_gen",
    )

    if not llm_output:
        return {
            "ok": False,
            "error": "LLM 调用失败或返回空",
            "strategy_name": "",
            "code": "",
            "file_path": None,
            "syntax_valid": False,
            "syntax_error": "",
            "lookahead_issues": [],
        }

    # 2. 提取代码
    code = extract_code(llm_output)

    # 3. 提取类名
    class_match = re.search(r"class\s+(\w+)\s*\(", code)
    class_name = sanitize_class_name(class_match.group(1)) if class_match else "GeneratedStrategy"
    if class_match and class_name != class_match.group(1):
        code = code.replace(f"class {class_match.group(1)}", f"class {class_name}", 1)

    # 4. 确保有 import functools
    if "import functools" not in code:
        code = "import functools\n" + code

    # 5. 语法验证
    syntax_valid, syntax_error = validate_syntax(code)

    # 6. 未来函数检测
    lookahead_issues = check_lookahead(code)

    # 7. 保存到策略目录
    file_path = None
    if save and syntax_valid:
        _STRATEGY_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        file_name = f"{class_name}.py"
        file_path = _STRATEGY_OUTPUT_DIR / file_name

        # 如果文件已存在，加时间戳后缀
        if file_path.exists():
            file_name = f"{class_name}_{uuid.uuid4().hex[:6]}.py"
            file_path = _STRATEGY_OUTPUT_DIR / file_name

        file_path.write_text(code, encoding="utf-8")
        file_path = str(file_path)

    return {
        "ok": syntax_valid,
        "strategy_name": class_name,
        "code": code,
        "file_path": file_path,
        "syntax_valid": syntax_valid,
        "syntax_error": syntax_error,
        "lookahead_issues": lookahead_issues,
    }
