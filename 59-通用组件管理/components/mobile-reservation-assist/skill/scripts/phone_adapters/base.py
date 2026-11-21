"""手机端操作适配器基座：把"预约作业"翻译为"手机动作序列"。

平台差异只允许出现在 `phone_adapters/<平台>.py`；内核（executor/gateway）不认识平台。
硬约束：任何动作序列都不得包含支付/锁座/占座步骤——构建即校验，违规直接拒绝。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

# 出现即拒绝的动作/参数词（支付、锁座、占座、代付）
FORBIDDEN_TOKENS = (
    "pay",
    "payment",
    "支付",
    "付款",
    "代付",
    "lockset",
    "lock_seat",
    "occupy",
    "hold_seat",
    "锁座",
    "占座",
)


class CommandError(Exception):
    """动作序列构建失败（含违规步骤）。"""


def _iter_text(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield str(k)
            yield from _iter_text(v)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_text(item)


def assert_no_payment(steps: list[dict]) -> None:
    for text in _iter_text(steps):
        lowered = text.lower()
        for token in FORBIDDEN_TOKENS:
            if token in lowered:
                raise CommandError("动作序列包含禁止步骤：{}".format(token))


@runtime_checkable
class PhoneAdapter(Protocol):
    NAME: str
    APP: str

    def describe(self, job: dict) -> dict: ...


class BasePhoneAdapter:
    """标准流程：打开官方 App → 定位目标 → 进入下单页并预填 → 停在支付前（人工确认）。"""

    NAME = ""
    APP = ""  # 官方 App 包名
    ROUTE_HINT = ""  # 进入目标的路径提示（如"车票→余票查询"）
    SEARCH_FIELD = ""  # 需填写的检索字段标签
    IDENT_FIELD = ""  # 需填写的身份字段标签（观演人/就诊人）

    def _steps(self, target: dict) -> list[dict]:
        steps = [
            {"action": "open_app", "app": self.APP},
            {"action": "goto", "route": self.ROUTE_HINT},
            {"action": "search", "field": self.SEARCH_FIELD, "value": target.get("target_id", "")},
            {"action": "select_session", "value": target.get("session", "")},
            {"action": "select_tier", "value": target.get("price_tier", "")},
        ]
        if self.IDENT_FIELD:
            steps.append({"action": "fill_identity", "field": self.IDENT_FIELD})
        steps.append({"action": "goto_order_page"})
        steps.append({"action": "stop", "reason": "await_human_confirm"})
        return steps

    def describe(self, job: dict) -> dict:
        target = job.get("target") or {}
        steps = self._steps(target)
        assert_no_payment(steps)
        return {
            "job_id": job.get("_id"),
            "adapter": self.NAME,
            "app": self.APP,
            "target": target,
            "max_price": job.get("max_price"),
            "steps": steps,
            "stop_before": "payment",
        }
