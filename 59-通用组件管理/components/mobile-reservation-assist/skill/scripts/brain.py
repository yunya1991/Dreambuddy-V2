"""阿里大模型（Qwen）接入：复用 `~/.local/share/dreambuddy/qwen.env`。

设计原则（对应产品决策）：
- 默认「白名单计划执行」：自然语言先由大模型转成结构化计划 JSON，
  只允许有限动作集合，再由本地执行器执行；模型不直接跑任意代码。
- 例外一（告警接管）：patrol 检测到异常时，允许模型参与诊断与修复，
  修复动作仍走白名单（复位卡住作业、恢复派发等），并做修复后验证。
- 例外二（人工授权）：CLI `ask --execute` 由人工显式授权，允许模型直接驱动工具。

OpenAI 兼容端点：`{QWEN_BASE_URL}/chat/completions`，Bearer 鉴权。
仅用标准库（urllib），无第三方依赖；不打印任何密钥。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

ENV_FILE = Path(os.path.expanduser("~/.local/share/dreambuddy/qwen.env"))

# 允许被计划/执行的动作（白名单）。支付/锁座/抢票类动作永不入列。
ALLOWED_ACTIONS = (
    "doctor",
    "jobs",
    "report",
    "pause",
    "resume",
    "dispatch",
    "reset_stuck",  # 复位卡在 dispatched 的作业（watchdog 接管场景）
)

# 红线关键词：出现即拒绝该计划步骤
FORBIDDEN_KEYWORDS = (
    "支付",
    "付款",
    "锁座",
    "占座",
    "代抢",
    "破解",
    "验证码",
    "payment",
    "lock_seat",
)


def load_env() -> dict:
    """读取 qwen.env；环境变量优先覆盖。"""
    values: dict[str, str] = {}
    try:
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            values[key.strip()] = val.strip()
    except FileNotFoundError:
        pass
    for key in ("QWEN_BASE_URL", "QWEN_API_KEY", "QWEN_DEFAULT_MODEL"):
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


def available() -> bool:
    env = load_env()
    return bool(env.get("QWEN_BASE_URL") and env.get("QWEN_API_KEY"))


def chat(
    messages: list[dict], model: str | None = None, timeout: int = 60, temperature: float = 0.2
) -> str:
    """调用 OpenAI 兼容 /chat/completions，返回首条回复文本。"""
    env = load_env()
    if not (env.get("QWEN_BASE_URL") and env.get("QWEN_API_KEY")):
        raise RuntimeError("QWEN 未配置：缺少 QWEN_BASE_URL / QWEN_API_KEY")
    url = env["QWEN_BASE_URL"].rstrip("/") + "/chat/completions"
    body = {
        "model": model or env.get("QWEN_DEFAULT_MODEL", "qwen3.7-plus"),
        "messages": messages,
        "temperature": temperature,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + env["QWEN_API_KEY"],
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError("QWEN 调用失败：{}".format(exc)) from exc
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise RuntimeError("QWEN 返回格式异常") from exc


def extract_json(text: str) -> dict:
    """从模型输出中抽取 JSON 对象（兼容 ```json 代码块与前后解释文字）。"""
    text = (text or "").strip()
    if text.startswith("```"):
        # 去掉首行 ```json 与末行 ```
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("模型未返回可解析的 JSON")
    return json.loads(text[start : end + 1])


PLAN_SYSTEM = """你是一个手机预约助手的指令规划器。把用户的中文指令转成严格的 JSON 计划，只输出 JSON，不要解释。
可用动作（白名单，params 见括号）：
- doctor           环境自检 ()
- jobs             列出预约作业 (state 可选)
- report           生成 reservation.v1 报告 ()
- pause            暂停派发 ()
- resume           恢复派发 ()
- dispatch         下发一条预约作业 (adapter, target_id, session, price_tier, max_price 可选)
- reset_stuck      复位卡住(dispatched)的作业为 pending ()

输出结构：
{"intent": "一句话意图", "steps": [{"action": "动作名", "params": {...}}], "note": "说明"}
规则：只能使用上面动作；绝不输出支付/锁座/代抢/破解验证码类动作；无法映射时 steps 返回 []。"""


def plan(nl: str, context: dict | None = None, history: list[dict] | None = None) -> dict:
    """自然语言 → 白名单计划 JSON（可带多轮对话历史）。"""
    ctx = json.dumps(context or {}, ensure_ascii=False)
    messages = [{"role": "system", "content": PLAN_SYSTEM}]
    for turn in history or []:
        messages.append(turn)
    messages.append({"role": "user", "content": "当前状态：{}\n用户指令：{}".format(ctx, nl)})
    return extract_json(chat(messages))


DISPATCH_SYSTEM = """你是预约参数抽取器。从用户中文里抽取一条预约作业参数，只输出 JSON，不要解释。
字段：
- adapter: 平台标识（B站会员购=bilibili，12306/铁路=railway，未知留空）
- target_id: 目标（艺人/车次/商品名）
- session: 场次/日期/时间（原样保留，如 "2026-12-25" 或 "12月25日 19:30"）
- price_tier: 价位档（如 内场/看台/二等座），未知留空
- max_price: 最高可接受价格（数字，未知填 null）
输出：{"adapter":"","target_id":"","session":"","price_tier":"","max_price":null}"""


def parse_dispatch(nl: str) -> dict:
    """自然语言 → 预约作业参数。"""
    messages = [
        {"role": "system", "content": DISPATCH_SYSTEM},
        {"role": "user", "content": nl},
    ]
    data = extract_json(chat(messages))
    data.setdefault("adapter", "")
    data.setdefault("target_id", "")
    data.setdefault("session", "")
    data.setdefault("price_tier", "")
    data.setdefault("max_price", None)
    return data


def guard_plan(plan_obj: dict) -> dict:
    """校验计划：过滤非白名单动作与红线步骤，返回 {plan, rejected}。"""
    steps = plan_obj.get("steps") or []
    kept, rejected = [], []
    for step in steps:
        action = str(step.get("action", "")).strip()
        blob = json.dumps(step, ensure_ascii=False)
        if action not in ALLOWED_ACTIONS:
            rejected.append({"action": action, "reason": "非白名单动作"})
            continue
        if any(k in blob for k in FORBIDDEN_KEYWORDS):
            rejected.append({"action": action, "reason": "触碰红线关键词"})
            continue
        kept.append(step)
    return {
        "plan": {
            "intent": plan_obj.get("intent", ""),
            "steps": kept,
            "note": plan_obj.get("note", ""),
        },
        "rejected": rejected,
    }
