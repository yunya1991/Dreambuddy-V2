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
import re
import time
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
    "reconcile",    # 订单对账：列出/收敛 order_unknown（不确定结果只能人工对账）
    "consult",      # 问手机端千问 App（知识百科），用于故障排查
    "knowledge_ask",  # 千问知识工具：只读结构化问答（引用 + 置信度 + TTL 缓存）
    # 推文发布（桌面 Playwright 通道；发布本身仍需 ask --execute 人工授权）
    "twitter_post",
    "twitter_schedule",
    "twitter_list",
    "twitter_status",
    # 手机 UI 原子动作（确定性执行；动作集合需与 phone_console.PHONE_ACTIONS 保持一致）
    "open_app",
    "tap",
    "type",
    "swipe",
    "key",
    "screen",
    "shot",
    "wait",
    "pkg",
)

# 红线关键词：出现即拒绝该计划步骤
FORBIDDEN_KEYWORDS = ("支付", "付款", "锁座", "占座", "代抢", "破解", "验证码", "payment", "lock_seat")


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
    messages: list[dict],
    model: str | None = None,
    timeout: int = 60,
    temperature: float = 0.2,
    task: str = "generic",
    tier: str | None = None,
) -> str:
    """调用 OpenAI 兼容 /chat/completions，返回首条回复文本。

    task/tier 用于模型分档路由与调用遥测；不传时行为与旧版一致（默认模型）。
    """
    env = load_env()
    if not (env.get("QWEN_BASE_URL") and env.get("QWEN_API_KEY")):
        raise RuntimeError("QWEN 未配置：缺少 QWEN_BASE_URL / QWEN_API_KEY")
    url = env["QWEN_BASE_URL"].rstrip("/") + "/chat/completions"
    tier = tier or route_tier(task)
    model = model or tier_model(tier, env)
    started = time.monotonic()
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
        record_call(task, tier, str(body.get("model")), messages, started, False, str(exc))
        raise RuntimeError("QWEN 调用失败：{}".format(exc)) from exc
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        record_call(task, tier, str(body.get("model")), messages, started, False, "返回格式异常")
        raise RuntimeError("QWEN 返回格式异常") from exc
    record_call(task, tier, str(body.get("model")), messages, started, True, "")
    return content


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
- dispatch         下发一条预约作业 (adapter, target_id, session, price_tier, max_price 可选, pay_authorized 可选)
- reset_stuck      复位卡住(dispatched)的作业为 pending ()
- reconcile        订单对账：列出待对账作业 ()，或收敛某作业 (job_id, state=done|failed, order_id 可选, note 可选)
- consult          问手机端千问 App 寻求排障方案 (question)
- knowledge_ask    千问知识工具（只读）：平台规则/实名/退改/放号咨询 (question, app 可选)
- twitter_post     立即发一条推文 (text 必填, image 可选 图片路径数组, dry_run 可选=true 只预览)
- twitter_schedule 定时发推文 (text 必填, at="YYYY-MM-DD HH:MM" 或 "HH:MM" 或 "明天 09:00", 或 in="30m"/"2h"/"1d")
- twitter_list     查看推文定时队列 (state 可选 pending|posting|done|failed|cancelled, limit 可选)
- twitter_status   查看推特定时队列概览与登录状态 (offline 可选=true 不启动浏览器)
- open_app         打开手机应用 (app: xhs/jianying/douyin/qianwen/notes 或包名, restart 可选)
- tap              按文本点击 (text, timeout 可选)；按坐标用 params 里的 x/y
- type             写入当前输入框 (text, hint 可选, clear 可选)
- swipe            滑动 (direction=up|down|left|right, duration 可选)
- key              系统按键 (key=back|home|recent|enter)
- screen           读取当前页面文本与包名 (limit 可选)
- shot             截图 (tag 可选)
- wait             等待元素出现 (text, timeout 可选)
- pkg              读取当前前台包名 ()

输出结构：
{"intent": "一句话意图", "steps": [{"action": "动作名", "params": {...}}], "note": "说明"}
规则：只能使用上面动作；绝不输出支付/锁座/代抢/破解验证码类动作；无法映射时 steps 返回 []。
dispatch 的 adapter、target_id、session 必填：用户原话里出现日期/场次，必须原样写入 session，不得留空。
支付授权：仅当用户明确表达"帮我买/直接买/帮我下单付款/帮我付"时，dispatch 的 params 加 "pay_authorized": true；只说"预约/提醒/推进到付款前"时不加（默认关闭支付）。"""


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
- pay_authorized: 仅当用户明确说"帮我买/直接付款"时为 true，否则 false
输出：{"adapter":"","target_id":"","session":"","price_tier":"","max_price":null,"pay_authorized":false}"""


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
    data.setdefault("pay_authorized", False)
    return data


NOTE_SYSTEM = """你是小红书「财经技术流」博主的内容编辑。根据给定文章写一篇图文笔记，只输出 JSON，不要解释。
输出结构：{"title": "", "body": "", "topics": ["", ""]}

写作要求：
1. 标题不超过 20 字，有信息量、不夸张，不用"震惊/必看/暴涨"等标题党词。
2. 正文 300-700 字，结构：钩子（一个具体问题或反常识事实）→ 文章要点提炼（2-4 条）→ 我的做法/可复用清单 → 一句互动提问。
3. 用口语化短句，多用换行；不用 emoji 堆砌。
4. topics 给 3-6 个不带 # 的话题词，贴内容不蹭热点。
合规红线（违反即不合格，平台会判违规限流）：
- 只做金融新闻与事实描述：事件、数据、政策、行业趋势、市场现象；不做投资建议。
- 严禁出现个股名称、股票代码、基金代码、具体买卖点、目标价、止盈止损位。
- 严禁荐股、带单、跟单、代客理财、内幕消息；不承诺收益，不写"稳赚/保本/翻倍/年化X%"。
- 严禁交易动作词：买入、卖出、加仓、减仓、满仓、空仓、抄底、逃顶、建仓、清仓。
- 不晒收益截图，不制造焦虑（"再不XX就晚了"），不用"震惊/重磅/必看/暴涨/暴跌"等标题党词。
- 不搬运原文长段，必须改写提炼；涉及数据要保留来源（如"华尔街见闻"）。
- 不编造文章里没有的数字与事实；不确定就写"原文提到"或"据公开报道"。
- 结尾用中性提问引导讨论（如"你怎么看这条新闻的影响？"），不引导交易。
数据使用规则（当提供 market_data 时）：
- 引用数据必须注明"DreamBuddy 数据面板"；只取摘要里的数字，不得自行推算或外推。
- 技术图表/数据研究只陈述关系、分位与证据强度，不给方向、仓位、买卖建议。
- 单日涨跌只描述现象，不推导趋势；样本不足或降级的数据要写明"样本不足/降级"。
多篇素材规则（当 articles 多于 1 篇时）：
- 先归纳 2-4 条共性，再补 1-2 个差异或分歧；不要逐篇流水账。
- 各篇数字/观点冲突时写明分歧，不强行统一；每篇只取最有信息量的一点。
- 正文里不要出现"第一篇/第二篇"这类编号，用主题自然衔接。
风格参考规则（当提供 trend_brief 时）：
- 只借鉴选题角度、结构形式与信息密度；严禁照抄爆款标题、句子或具体表达。
- 保持"泛金融 / 经济 / 时事 / AI Agent / 数据服务"赛道定位，不追与该赛道无关的热点。
- 若 trend_brief.recommend 非空，优先按第一条的 topic / angle / format 组织内容，
  并用 articles 里的事实与数字支撑；素材支撑不足就缩小结论，不编造。"""


def normalize_note(data: dict) -> dict:
    """笔记归一：标题截断、正文清理、话题去 # 去重限量。"""
    title = re.sub(r"\s+", " ", str(data.get("title") or "")).strip()[:20]
    body = str(data.get("body") or "").strip()
    topics = data.get("topics") or []
    if isinstance(topics, str):
        topics = re.split(r"[\s,，#]+", topics)
    cleaned: list[str] = []
    for item in topics:
        word = str(item).strip().lstrip("#").strip()
        if word and word not in cleaned:
            cleaned.append(word)
    return {"title": title, "body": body, "topics": cleaned[:6]}


def compose_note(
    article: dict,
    extra: str = "",
    data: dict | None = None,
    timeout: int = 120,
    trend: dict | None = None,
    materials: list[dict] | None = None,
) -> dict:
    """文章（可多篇）+ 云端数据 + 爆款风格参考 → 小红书笔记（标题/正文/话题）。

    extra 用于传入千问的优化意见；materials 提供时以其为准（多篇汇总）；
    trend 是 analyze_trends 的结论，只作为风格/形式参考。
    """
    docs = [item for item in (materials or []) if item] or ([article] if article else [])
    articles = []
    for item in docs[:5]:
        articles.append(
            {
                "title": str((item or {}).get("title") or ""),
                "source": str((item or {}).get("source_name") or (item or {}).get("source") or ""),
                "body": str((item or {}).get("body") or "")[:2500],
            }
        )
    payload = {
        "title": (articles[0]["title"] if articles else ""),
        "source": (articles[0]["source"] if articles else ""),
        "articles": articles,
        "optimize": extra or "",
        "market_data": data or {},
        "trend_brief": trend or {},
    }
    messages = [
        {"role": "system", "content": NOTE_SYSTEM},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)[:14000]},
    ]
    return normalize_note(extract_json(chat(messages, task="compose", timeout=timeout)))


DOUYIN_SYSTEM = """你是抖音「财经技术流」博主的内容编辑。根据给定文章写一条抖音图文作品，只输出 JSON，不要解释。
输出结构：{"title": "", "body": "", "topics": ["", ""], "pages": [{"heading": "", "points": ["", ""]}]}

写作要求：
1. title 是描述首行，不超过 30 字，前 3 个字就要有信息量（痛点/反常识/数字），不用"震惊/必看/暴涨"等标题党词。
2. body 是描述正文，300-600 字，短句多换行；结构：钩子（一个具体问题或反常识事实）→ 3 条要点 → 一句互动提问（引导评论）。
3. topics 给 3-5 个不带 # 的话题词，贴内容不蹭无关热点。
4. pages 是图文卡片（3-6 页）：每页 heading 不超过 20 字，points 2-4 条、每条不超过 40 字；
   第一页是封面页（一句钩子），最后一页放结论或互动引导。只写文案，不写排版指令。
5. 口播/字幕友好：一句话不超过 25 字，避免书面长句与生僻词。
合规红线（违反即不合格，平台会判违规限流）：
- 只做金融新闻与事实描述：事件、数据、政策、行业趋势、市场现象；不做投资建议。
- 严禁出现个股名称、股票代码、基金代码、具体买卖点、目标价、止盈止损位。
- 严禁荐股、带单、跟单、代客理财、内幕消息；不承诺收益，不写"稳赚/保本/翻倍/年化X%"。
- 严禁交易动作词：买入、卖出、加仓、减仓、满仓、空仓、抄底、逃顶、建仓、清仓。
- 不用"震惊/重磅/必看/暴涨/暴跌"等标题党词，不制造焦虑。
- 不搬运原文长段，必须改写提炼；引用数据要保留来源（如"华尔街见闻"）。
- 不编造文章里没有的数字与事实；不确定就写"原文提到"或"据公开报道"。
- 结尾用中性提问引导讨论，不引导交易。
数据使用规则（当提供 market_data 时）：
- 引用数据必须注明"DreamBuddy 数据面板"；只取摘要里的数字，不得自行推算或外推。
- 技术图表/数据研究只陈述关系、分位与证据强度，不给方向、仓位、买卖建议。
多篇素材规则（当 articles 多于 1 篇时）：
- 先归纳 2-3 条共性，再补 1 个差异或分歧；不要逐篇流水账，正文不出现"第一篇/第二篇"。
风格参考规则（当提供 trend_brief 时）：
- 只借鉴选题角度、结构形式、开头钩子与信息密度；严禁照抄爆款标题、句子或具体表达。
- 保持"泛金融 / 经济 / 时事 / AI Agent / 数据服务"赛道定位，不追与该赛道无关的热点。"""


def normalize_douyin_note(data: dict) -> dict:
    """抖音图文归一：标题/正文截断、话题去重限量、图文分页清洗。"""
    title = re.sub(r"\s+", " ", str(data.get("title") or "")).strip()[:30]
    body = str(data.get("body") or "").strip()[:800]
    topics = data.get("topics") or []
    if isinstance(topics, str):
        topics = re.split(r"[\s,，#]+", topics)
    cleaned: list[str] = []
    for item in topics:
        word = str(item).strip().lstrip("#").strip()
        if word and word not in cleaned:
            cleaned.append(word)
    pages_out: list[dict] = []
    for page in (data.get("pages") or [])[:6]:
        if isinstance(page, str):
            page = {"heading": page, "points": []}
        heading = re.sub(r"\s+", " ", str(page.get("heading") or "")).strip()[:20]
        points = [str(item).strip()[:40] for item in (page.get("points") or []) if str(item).strip()][:4]
        if heading or points:
            pages_out.append({"heading": heading, "points": points})
    return {"title": title, "body": body, "topics": cleaned[:5], "pages": pages_out}


def compose_douyin_note(
    article: dict,
    extra: str = "",
    data: dict | None = None,
    timeout: int = 120,
    trend: dict | None = None,
    materials: list[dict] | None = None,
) -> dict:
    """文章（可多篇）+ 云端数据 + 爆款风格 → 抖音图文（标题/描述/话题/图文分页）。

    结构对齐 compose_note，仅输出契约换成抖音图文（pages 用于后续多图卡片）。
    """
    docs = [item for item in (materials or []) if item] or ([article] if article else [])
    articles = []
    for item in docs[:5]:
        articles.append(
            {
                "title": str((item or {}).get("title") or ""),
                "source": str((item or {}).get("source_name") or (item or {}).get("source") or ""),
                "body": str((item or {}).get("body") or "")[:2500],
            }
        )
    payload = {
        "title": (articles[0]["title"] if articles else ""),
        "source": (articles[0]["source"] if articles else ""),
        "articles": articles,
        "optimize": extra or "",
        "market_data": data or {},
        "trend_brief": trend or {},
    }
    messages = [
        {"role": "system", "content": DOUYIN_SYSTEM},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)[:14000]},
    ]
    return normalize_douyin_note(extract_json(chat(messages, task="compose", timeout=timeout)))


REWRITE_SYSTEM = """你是金融内容合规编辑。把给定内容改写为「客观金融新闻描述」，只输出 JSON，不要解释。
输出结构与输入保持一致：{"title": "", "body": "", "topics": ["", ""], "pages": [{"heading": "", "points": ["", ""]}]}

改写规则：
1. 删除所有个股名称、股票/基金代码、交易动作（买入/卖出/加仓/减仓/满仓/空仓/抄底/逃顶/建仓/清仓）、
   目标价、止盈止损、收益承诺与收益率数字。
2. 改为描述新闻事实：发生了什么、数据如何变化、政策与机构表态、行业与市场现象。
3. 不预测涨跌、不给操作建议；可用"市场关注""机构认为""数据显示""据公开报道"等客观表述。
4. 保留原有结构与话题数量；标题保持中性、有信息量，不用标题党与焦虑词。
5. 不新增原文没有的事实与数字；不确定就删掉该句。"""


def rewrite_compliant(note: dict, findings: dict | None = None, timeout: int = 120) -> dict:
    """按合规规则重写内容：只做事实描述，去掉标的、交易动作与收益承诺。

    保留输入的结构（笔记或抖音图文），输出仍走对应归一函数。
    """
    payload = {
        "content": note,
        "violations": findings or {},
        "rule": "只做金融新闻客观描述，零交易建议、零标的、零收益承诺",
    }
    messages = [
        {"role": "system", "content": REWRITE_SYSTEM},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)[:12000]},
    ]
    data = extract_json(chat(messages, task="compose", timeout=timeout))
    if note.get("pages") or data.get("pages"):
        out = normalize_douyin_note(data)
    else:
        out = normalize_note(data)
        out["pages"] = note.get("pages") or []
    if not out.get("topics"):
        out["topics"] = note.get("topics") or []
    return out


def douyin_image_prompt(note: dict, style: str = "", heading: str = "") -> str:
    """由抖音图文生成单页配图提示词（确定性模板，避免多一次模型调用）。"""
    title = str(heading or (note or {}).get("title") or "").strip()
    extra = (" 风格：" + style.strip()) if style.strip() else ""
    return (
        "生成一张竖版 3:4 的抖音图文知识卡片，主题：{title}。"
        "画面干净、单一视觉焦点，适合手机全屏浏览；左上角留白放标题文字区域，"
        "不出现真实公司 Logo、股票代码、收益数字，不含水印与二维码。{extra}"
    ).format(title=title or "财经研究方法", extra=extra)


TREND_SYSTEM = """你是小红书内容策略分析师，赛道聚焦「泛金融 / 经济 / 时事 / AI Agent / 数据服务」。输入是近期爆款笔记样本（标题、关键词、互动量、正文摘录），只输出 JSON，不要解释。
输出结构：
{
  "themes": [], "formats": [], "directions": [], "style_brief": "", "do": [], "avoid": [],
  "titles": {"patterns": [], "examples": []},
  "style": {"tone": "", "structure": "", "density": "", "hooks": []},
  "learn": [],
  "recommend": [{"topic": "", "angle": "", "format": "", "why": ""}]
}

分析要求：
1. themes：爆款在讲什么主题（3-6 条），归到具体问题，不写空泛词。
2. formats：内容形式（如"数据拆解清单""一条新闻+一个方法""对比表""亲测复盘"），3-6 条。
3. titles.patterns：标题的句式规律（如"数字+反差""时间窗口+结果""提问式"），3-5 条；
   titles.examples：只给规律示例，不照抄原爆款标题。
4. style：语气（tone）、结构（structure）、信息密度（density）、开头钩子（hooks），各 1-3 条短语。
5. learn：可以学习并复用的写法/结构（3-6 条，具体到动作，如"开头先给一个可验证的数字"）。
6. recommend：今天最适合发的 1-3 条内容，每条给 topic（选题）、angle（切入角度）、
   format（形式）、why（为什么今天适合，结合时事/情绪/数据）。
7. directions：可延展方向（2-5 条）；style_brief：给写稿用的一段风格提示（120 字内）。
8. do / avoid：可复用做法与要避开的表达各 2-5 条。

合规红线：不推荐个股/基金/买卖点，不承诺收益；不鼓励搬运、洗稿、标题党；
只做形式、结构与选题层面的归纳；recommend 不得指向具体标的买卖。"""


def normalize_trends(data: dict) -> dict:
    """爆款分析结论归一：列表去重限量、风格提示截断。"""

    def _list(key: str, limit: int) -> list[str]:
        value = data.get(key) or []
        if isinstance(value, str):
            value = re.split(r"[\n;；]+", value)
        out: list[str] = []
        for item in value:
            word = str(item).strip()
            if word and word not in out:
                out.append(word)
        return out[:limit]

    def _list_from(container: dict, key: str, limit: int) -> list[str]:
        value = (container or {}).get(key) or []
        if isinstance(value, str):
            value = re.split(r"[\n;；]+", value)
        out: list[str] = []
        for item in value:
            word = str(item).strip()
            if word and word not in out:
                out.append(word)
        return out[:limit]

    titles = data.get("titles") or {}
    style = data.get("style") or {}
    recommend = data.get("recommend") or []
    if isinstance(recommend, str):
        recommend = [recommend]
    recommend_out: list[dict] = []
    for item in recommend[:3]:
        if isinstance(item, dict):
            topic = str(item.get("topic") or "").strip()
            if not topic:
                continue
            recommend_out.append(
                {
                    "topic": topic[:80],
                    "angle": str(item.get("angle") or "").strip()[:120],
                    "format": str(item.get("format") or "").strip()[:60],
                    "why": str(item.get("why") or "").strip()[:160],
                }
            )
        else:
            word = str(item).strip()
            if word:
                recommend_out.append({"topic": word[:80], "angle": "", "format": "", "why": ""})
    return {
        "themes": _list("themes", 8),
        "formats": _list("formats", 8),
        "directions": _list("directions", 6),
        "style_brief": str(data.get("style_brief") or "").strip()[:600],
        "do": _list("do", 8),
        "avoid": _list("avoid", 8),
        "title_patterns": _list("title_patterns", 6) or _list_from(titles, "patterns", 6),
        "title_examples": _list_from(titles, "examples", 6),
        "style": {
            "tone": str(style.get("tone") or "").strip()[:120],
            "structure": str(style.get("structure") or "").strip()[:200],
            "density": str(style.get("density") or "").strip()[:120],
            "hooks": _list_from(style, "hooks", 4),
        },
        "learn": _list("learn", 8),
        "recommend": recommend_out,
    }


def analyze_trends(samples: list[dict], timeout: int = 120) -> dict:
    """爆款样本 → 主题/形式/可扩展方向/风格提示（只做形式归纳，不复制内容）。"""
    items = []
    for item in (samples or [])[:20]:
        items.append(
            {
                "title": str((item or {}).get("title") or "")[:60],
                "keyword": str((item or {}).get("keyword") or ""),
                "likes": str((item or {}).get("likes") or ""),
                "author": str((item or {}).get("author") or "")[:30],
                "body": str((item or {}).get("body") or "")[:800],
            }
        )
    payload = {"track": "泛金融 / 经济 / 时事 / AI Agent / 数据服务", "samples": items}
    messages = [
        {"role": "system", "content": TREND_SYSTEM},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)[:14000]},
    ]
    return normalize_trends(extract_json(chat(messages, task="compose", timeout=timeout)))


def image_prompt(note: dict, style: str = "") -> str:
    """由笔记生成封面图提示词（给千问生图用，确定性模板，避免多一次模型调用）。"""
    title = str((note or {}).get("title") or "").strip()
    extra = (" 风格：" + style.strip()) if style.strip() else ""
    return (
        "生成一张竖版 3:4 的小红书知识卡片封面图，主题：{title}。"
        "画面简洁有质感，深色科技感背景，留出大面积留白方便叠加标题文字，"
        "不要出现真人、真实品牌 logo、股票代码和收益数字。{extra}"
    ).format(title=title or "财经研究方法", extra=extra)


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
        if action not in ("consult", "knowledge_ask") and any(k in blob for k in FORBIDDEN_KEYWORDS):
            rejected.append({"action": action, "reason": "触碰红线关键词"})
            continue
        kept.append(step)
    return {"plan": {"intent": plan_obj.get("intent", ""), "steps": kept, "note": plan_obj.get("note", "")}, "rejected": rejected}


# ── 模型分档路由（确定性规则，可由 qwen.env 覆盖）──────────────────────────
TIER_ORDER = ("fast", "standard", "strong")
TIER_ENV_KEYS = {
    "fast": "QWEN_MODEL_FAST",
    "standard": "QWEN_MODEL_STANDARD",
    "strong": "QWEN_MODEL_STRONG",
}
DEFAULT_TIER_MODELS = {
    "fast": "qwen3.8-flash",
    "standard": "qwen3.7-plus",
    "strong": "qwen3.7-max",
}
TASK_BASE_TIER = {
    "plan": "standard",
    "extract": "fast",
    "verify": "strong",
    "diagnose": "standard",
    "consult": "fast",
    "compose": "standard",
    "generic": "standard",
}
SIMPLE_WORDS = ("查看", "看一下", "看下", "列出", "检查", "自检", "报告", "暂停", "恢复", "复位", "帮助")
MULTI_MARKERS = ("然后", "并且", "同时", "顺便", "以及", "还有", "；", ";")
DISPATCH_WORDS = ("预约", "下单", "抢")


def complexity_score(text: str, history: list[dict] | None = None) -> int:
    """确定性复杂度打分：长度、多意图连接词、多日期、价位、多轮上下文。"""
    text = (text or "").strip()
    score = 0
    if len(text) > 40:
        score += 1
    if len(text) > 90:
        score += 1
    score += sum(1 for marker in MULTI_MARKERS if marker in text)
    dates = len(re.findall(r"\d{1,2}\s*月|\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}", text))
    score += min(2, dates)
    if re.search(r"\d+\s*(元|块)", text):
        score += 1
    if history and len(history) >= 6:
        score += 1
    return score


def route_tier(task: str, text: str = "", history: list[dict] | None = None) -> str:
    """按任务场景与指令复杂度选档；plan 场景允许简单指令降档。"""
    tier = TASK_BASE_TIER.get(task or "generic", "standard")
    if task == "plan":
        score = complexity_score(text, history)
        simple = any(word in (text or "") for word in SIMPLE_WORDS) and not any(
            word in (text or "") for word in DISPATCH_WORDS
        )
        if score >= 4:
            return "strong"
        if score <= 1 and simple:
            return "fast"
    return tier


def escalate_tier(tier: str) -> str:
    """升一档；已是最高档则保持不变。"""
    try:
        return TIER_ORDER[min(TIER_ORDER.index(tier) + 1, len(TIER_ORDER) - 1)]
    except ValueError:
        return "strong"


def tier_model(tier: str, env: dict | None = None) -> str:
    env = load_env() if env is None else env
    return env.get(TIER_ENV_KEYS.get(tier, "QWEN_MODEL_STANDARD"), "") or DEFAULT_TIER_MODELS.get(
        tier, "qwen3.7-plus"
    )


def telemetry_path() -> Path:
    base = Path(os.environ.get("MRA_STATE_DIR") or (Path.home() / ".mobile-reservation-assist"))
    return base / "model_calls.jsonl"


def record_call(task: str, tier: str, model: str, messages: list[dict], started: float, ok: bool, error: str) -> None:
    """记录调用元数据（不含提示词内容），供后续按场景做模型对照校准。"""
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "task": task or "generic",
        "tier": tier,
        "model": model,
        "prompt_chars": sum(len(str(item.get("content", ""))) for item in messages),
        "latency_ms": int((time.monotonic() - started) * 1000),
        "ok": bool(ok),
        "error": error or "",
    }
    try:
        path = telemetry_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


# ── AI 验收官 ────────────────────────────────────────────────────────────
VERIFY_SYSTEM = """你是手机预约助手的验收官。判断"程序执行结果"是否达成用户意图，只输出 JSON，不要解释。
输出结构：{"qualified": true/false, "score": 0-100, "issues": ["问题"], "guidance": "下一步建议"}

验收规则：
1. 意图一致：动作与用户意图匹配（查看类要真列出；下发类要真的入队）。
2. 结果有效：必须含可核验证据（作业ID、作业列表、检查项）；报错/空结果/未执行均不合格。作业已 dispatched/pending 视为动作已执行，手机端排队或执行中不判不合格。
3. 安全边界：绝不建议点击支付/提交订单、锁座、代抢、破解验证码；但"推进到官方确认订单页、支付前停下"是合规目标，不得因此判不合格。
4. 正常停下：手机回执 needs_human 且说明到支付前/已结束/售罄/需登录，属按设计停下，判合格。
5. 补救动作禁止 pause/resume（会阻断派发）；需重试时只用 reset_stuck 或 dispatch。
6. 只有证据确实不满足意图时才判不合格；不确定时倾向合格并在 guidance 里写明待确认点。"""


def normalize_verdict(data: dict) -> dict:
    """把模型验收结论归一：qualified/score/issues/guidance。"""
    qualified = data.get("qualified")
    if qualified is None:
        qualified = data.get("ok", data.get("verdict") in ("pass", "合格", "通过"))
    issues = data.get("issues") or []
    if isinstance(issues, str):
        issues = [issues]
    try:
        score = int(data.get("score") or (100 if qualified else 0))
    except (TypeError, ValueError):
        score = 100 if qualified else 0
    return {
        "qualified": bool(qualified),
        "score": max(0, min(100, score)),
        "issues": [str(item) for item in issues][:5],
        "guidance": str(data.get("guidance") or data.get("note") or ""),
    }


def verify(nl: str, command: str, result, timeout: int = 90) -> dict:
    """AI 验收：对一次执行/回执做合格判定。"""
    payload = {"user_intent": nl, "command": command, "result": result}
    messages = [
        {"role": "system", "content": VERIFY_SYSTEM},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)[:8000]},
    ]
    return normalize_verdict(extract_json(chat(messages, task="verify", timeout=timeout)))


# ── 执行前参数预检 ───────────────────────────────────────────────────────
BOOKING_ADAPTERS = ("bilibili", "railway", "damai", "maoyan", "medical", "gov")


def precheck(action: str, params: dict) -> dict:
    """单步参数预检：缺关键参数就不要下发（避免手机端空跑）。"""
    params = params or {}
    missing: list[str] = []
    if action == "dispatch":
        if not str(params.get("adapter") or "").strip():
            missing.append("adapter")
        if not str(params.get("target_id") or "").strip():
            missing.append("target_id")
        if str(params.get("adapter") or "") in BOOKING_ADAPTERS and not str(params.get("session") or "").strip():
            missing.append("session")
        price = params.get("max_price")
        if price not in (None, "") and not isinstance(price, (int, float)):
            try:
                float(price)
            except (TypeError, ValueError):
                missing.append("max_price")
    elif action == "consult":
        if not str(params.get("question") or "").strip():
            missing.append("question")
    elif action == "knowledge_ask":
        if not str(params.get("question") or "").strip():
            missing.append("question")
    elif action == "open_app":
        if not str(params.get("app") or "").strip():
            missing.append("app")
    elif action == "tap":
        if not str(params.get("text") or "").strip() and None in (params.get("x"), params.get("y")):
            missing.append("text 或 x/y")
    elif action in ("type", "wait"):
        if not str(params.get("text") or "").strip():
            missing.append("text")
    elif action == "reconcile":
        if params.get("job_id") not in (None, ""):
            if str(params.get("state") or "").strip() not in ("done", "failed"):
                missing.append("state(done|failed)")
    elif action in ("twitter_post", "twitter_schedule"):
        if not str(params.get("text") or "").strip():
            missing.append("text")
        if action == "twitter_schedule" and not (
            str(params.get("at") or "").strip() or str(params.get("in") or "").strip()
        ):
            missing.append("at 或 in")
    return {"ok": not missing, "missing": missing}


def precheck_plan(plan_obj: dict) -> dict:
    """整份计划预检：逐步骤校验并汇总缺失项。"""
    problems = []
    for index, step in enumerate(plan_obj.get("steps") or []):
        check = precheck(str(step.get("action", "")), step.get("params") or {})
        if not check["ok"]:
            problems.append({"index": index, "action": step.get("action"), "missing": check["missing"]})
    return {"ok": not problems, "problems": problems}
