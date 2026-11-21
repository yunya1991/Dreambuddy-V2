"""L3 语义工具注册表：每个工具声明入参、副作用与风险等级。

分层约定：
- L3（本模块）：语义原子工具（启动 App / 搜索 / 选择场次 / 读页面 / 截图），无平台知识。
- L4（`phone_adapters/`）：按平台把 L3 工具编排成业务动作序列。

风险纪律：
- `forbidden=True` 的工具（支付/提交订单/锁座）永不入列，构建即拒绝。
- `risk="high"` 的工具默认不允许 L4 自动编排；调用方需显式授权（当前未开放）。
"""

from __future__ import annotations

from dataclasses import dataclass

from .policy import CommandError, assert_no_payment

ALLOWED_SIDE_EFFECTS = ("read", "ui", "irreversible")
ALLOWED_RISKS = ("low", "medium", "high")


@dataclass(frozen=True)
class ToolSpec:
    name: str
    side_effect: str
    risk: str
    required: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()
    forbidden: bool = False
    description: str = ""


def _spec(name: str, side_effect: str, risk: str, required=(), optional=(), forbidden=False, description=""):
    return ToolSpec(
        name=name,
        side_effect=side_effect,
        risk=risk,
        required=tuple(required),
        optional=tuple(optional),
        forbidden=forbidden,
        description=description,
    )


TOOLS = {
    # ── 导航与操作（确定性 UI）────────────────────────────────────────────
    "open_app": _spec("open_app", "ui", "low", required=("app",), description="启动官方 App"),
    "dismiss_consent": _spec("dismiss_consent", "ui", "low", optional=("text",), description="关闭隐私弹窗"),
    "goto": _spec("goto", "ui", "low", required=("route",), description="进入业务入口"),
    "search": _spec("search", "ui", "low", required=("value",), optional=("field",), description="检索目标"),
    "select_session": _spec("select_session", "ui", "low", required=("value",), description="选择场次/日期"),
    "select_tier": _spec("select_tier", "ui", "medium", required=("value",), description="选择价位档"),
    "fill_identity": _spec("fill_identity", "ui", "medium", required=("field",), description="填写实名/观演人"),
    "goto_order_page": _spec("goto_order_page", "ui", "medium", description="进入官方下单页"),
    "goto_order_hall": _spec(
        "goto_order_hall", "ui", "low", required=("platform",), optional=("tab",), description="进入顺风车订单大厅"
    ),
    "list_orders": _spec(
        "list_orders", "read", "low", optional=("platform", "limit", "min_price"), description="列出可抢订单"
    ),
    "parse_orders": _spec("parse_orders", "read", "low", optional=("limit",), description="解析订单列表"),
    "accept_order": _spec(
        "accept_order", "ui", "high", required=("order_id",), optional=("platform", "price"), description="接单（需显式授权）"
    ),
    "stop": _spec("stop", "ui", "low", optional=("reason",), description="停在人工确认节点"),
    # ── 只读证据（回执结构化）──────────────────────────────────────────────
    "capture_screenshot": _spec("capture_screenshot", "read", "low", optional=("tag",), description="截图取证"),
    "read_page_text": _spec("read_page_text", "read", "low", optional=("limit",), description="读取页面文本"),
    "read_order_status": _spec("read_order_status", "read", "low", description="读取订单状态/订单号"),
    # ── 内容生产（读文章 → 存素材 → 写文案 → 发布前停）────────────────────
    "read_article": _spec("read_article", "read", "low", optional=("source", "limit"), description="读取资讯文章正文"),
    "save_material": _spec("save_material", "ui", "low", optional=("tag", "dir"), description="保存素材到本地目录"),
    # ── 选题侦察与笔记草稿（内容生产前置）──────────────────────────────────
    "browse_feed": _spec("browse_feed", "ui", "low", optional=("keywords", "limit"), description="按关键词浏览平台信息流"),
    "read_note": _spec("read_note", "read", "low", optional=("index",), description="读取一条笔记正文"),
    "interact_post": _spec("interact_post", "ui", "medium", optional=("actions", "limit"), description="点赞/收藏（有次数上限，不评论）"),
    "write_memo": _spec("write_memo", "ui", "low", required=("text",), optional=("tag",), description="写入手机笔记本"),
    "read_memo": _spec("read_memo", "read", "low", optional=("limit",), description="读取手机笔记本内容"),
    "generate_image": _spec("generate_image", "ui", "medium", required=("prompt",), optional=("size",), description="生成配图并保存到相册"),
    "select_material": _spec("select_material", "ui", "medium", optional=("count", "dir"), description="选择本地素材作为配图"),
    "compose_note": _spec("compose_note", "ui", "medium", optional=("title", "topic_count"), description="填写笔记标题/正文（发布前停）"),
    # ── 禁止工具（声明出来是为了给出明确拒绝，而不是「未登记」）────────────
    "pay": _spec("pay", "irreversible", "high", forbidden=True, description="支付（禁止自动执行）"),
    "submit_order": _spec("submit_order", "irreversible", "high", forbidden=True, description="提交订单（人工终态）"),
    "publish_note": _spec("publish_note", "irreversible", "high", forbidden=True, description="发布笔记（人工终态）"),
    "lock_seat": _spec("lock_seat", "irreversible", "high", forbidden=True, description="锁座/占座（禁止）"),
}


def get_tool(name: str) -> ToolSpec:
    spec = TOOLS.get(name)
    if spec is None:
        raise CommandError("未登记的手机工具：{}".format(name))
    if spec.forbidden:
        raise CommandError("禁止使用的手机工具：{}".format(name))
    return spec


def build_step(name: str, **params) -> dict:
    """构建单个工具调用；未登记/禁用/缺参/含支付词一律拒绝。"""
    spec = get_tool(name)
    if "action" in params:
        raise CommandError("工具参数不得包含 action")
    missing = [key for key in spec.required if params.get(key) in (None, "")]
    if missing:
        raise CommandError("工具 {} 缺少参数：{}".format(name, "、".join(missing)))
    step = {"action": name, **params}
    assert_no_payment(step)
    return step


def validate_steps(steps: list[dict]) -> list[dict]:
    """校验动作序列：每个 action 必须是已登记工具，且不得触碰支付红线。"""
    validated = []
    for step in steps or []:
        if not isinstance(step, dict):
            raise CommandError("动作序列元素必须是对象")
        action = str(step.get("action") or "")
        params = {key: value for key, value in step.items() if key != "action"}
        validated.append(build_step(action, **params))
    return validated
