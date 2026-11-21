"""L4 业务编排基座：把"预约作业"编排为"L3 工具调用序列"。

分层约定：
- L3（`phone_tools/`）：平台无关的语义工具与风险策略。
- L4（本模块及 `phone_adapters/<平台>.py`）：平台业务流程编排，只允许调用已登记 L3 工具。

平台差异只允许出现在 `phone_adapters/<平台>.py`；内核（executor/gateway）不认识平台。
硬约束：任何动作序列都不得包含支付/锁座/占座步骤——构建即校验，违规直接拒绝。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from phone_tools import CommandError, assert_no_payment, build_step, validate_steps
from phone_tools.policy import FORBIDDEN_TOKENS

__all__ = [
    "BasePhoneAdapter",
    "CommandError",
    "FORBIDDEN_TOKENS",
    "PhoneAdapter",
    "assert_no_payment",
    "build_step",
    "validate_steps",
]


@runtime_checkable
class PhoneAdapter(Protocol):
    NAME: str
    APP: str

    def describe(self, job: dict) -> dict: ...


class BasePhoneAdapter:
    """标准流程：打开官方 App → 定位目标 → 进入下单页并预填 → 停在支付前（人工确认）。"""

    NAME = ""
    APP = ""            # 官方 App 包名
    ROUTE_HINT = ""     # 进入目标的路径提示（如"车票→余票查询"）
    SEARCH_FIELD = ""   # 需填写的检索字段标签
    IDENT_FIELD = ""    # 需填写的身份字段标签（观演人/就诊人）

    def _steps(self, target: dict) -> list[dict]:
        """编排 L3 工具；缺关键参数的动作不下发（避免手机端空跑）。"""
        steps: list[dict] = []
        if self.APP:
            steps.append(build_step("open_app", app=self.APP))
        if self.ROUTE_HINT:
            steps.append(build_step("goto", route=self.ROUTE_HINT))
        if target.get("target_id"):
            steps.append(build_step("search", field=self.SEARCH_FIELD, value=target["target_id"]))
        if target.get("session"):
            steps.append(build_step("select_session", value=target["session"]))
        if target.get("price_tier"):
            steps.append(build_step("select_tier", value=target["price_tier"]))
        if self.IDENT_FIELD:
            steps.append(build_step("fill_identity", field=self.IDENT_FIELD))
        steps.append(build_step("goto_order_page"))
        steps.append(build_step("stop", reason="await_human_confirm"))
        return steps

    def describe(self, job: dict) -> dict:
        target = job.get("target") or {}
        steps = validate_steps(self._steps(target))
        assert_no_payment(steps)
        return {
            "job_id": job.get("_id"),
            "adapter": self.NAME,
            "app": self.APP,
            "target": target,
            "max_price": job.get("max_price"),
            # 支付授权：默认 False；仅当用户明确说"帮我买/直接付款"时由上游置 True
            "pay_authorized": bool(job.get("pay_authorized")),
            "steps": steps,
            "stop_before": "payment",
        }
