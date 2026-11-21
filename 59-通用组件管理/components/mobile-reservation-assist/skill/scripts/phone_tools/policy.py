"""L3 工具策略：禁用词、构建错误、支付/锁座的结构性禁止。

本层不认识任何平台；平台差异只允许出现在 L4（`phone_adapters/`）。
"""

from __future__ import annotations

# 出现即拒绝的动作/参数词（支付、锁座、占座、代付）
FORBIDDEN_TOKENS = (
    "pay", "payment", "支付", "付款", "代付",
    "lockset", "lock_seat", "occupy", "hold_seat", "锁座", "占座",
)


class CommandError(Exception):
    """工具/动作序列构建失败（含违规步骤）。"""


def _iter_text(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _iter_text(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_text(item)


def assert_no_payment(steps: list[dict]) -> None:
    """结构性禁止：动作序列出现支付/锁座词即拒绝。"""
    for text in _iter_text(steps):
        lowered = text.lower()
        for token in FORBIDDEN_TOKENS:
            if token in lowered:
                raise CommandError("动作序列包含禁止步骤：{}".format(token))
