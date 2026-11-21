"""顺风车抢单 L4 适配器：三平台共用一套动作序列，差异只在包名/大厅入口。

默认只扫描并解析订单；仅当作业显式带 `accept_authorized=True` 时才追加接单步骤。
授权门禁写在 `describe` 内：注册表不拦 `risk="high"`，必须由适配器自身兜底。
"""

from __future__ import annotations

from phone_tools import CommandError, build_step, validate_steps

# 平台 → 官方 App 包名。legacy autojs 配置里的 key 与此保持一致（didi/dida/hello）。
PLATFORMS = {
    "didi": "com.sdu.didi.psnger",
    "dida": "com.didapinche.booking",
    "hello": "com.hellobike.hitch",
}

DEFAULT_MIN_PRICE = 0.0
DEFAULT_MAX_ACCEPT = 1


class CarpoolPhone:
    """顺风车订单大厅：打开 App → 进大厅 → 拉列表 → 解析 →（可选）接单 → 截图 → 停。"""

    NAME = "carpool"
    APP = ""
    STOP_BEFORE = "payment"

    def _platform(self, target: dict, job: dict) -> str:
        platform = str(target.get("platform") or job.get("platform") or "didi").strip()
        if platform not in PLATFORMS:
            raise CommandError("未登记的顺风车平台：{}".format(platform))
        return platform

    def _accept_steps(self, target: dict, job: dict) -> list[dict]:
        if not job.get("accept_authorized"):
            return []
        order_id = str(target.get("order_id") or "").strip()
        if not order_id:
            raise CommandError("接单缺少 order_id")
        max_accept = int(job.get("max_accept") or DEFAULT_MAX_ACCEPT)
        accepted_today = int(job.get("accepted_today") or 0)
        if accepted_today >= max_accept:
            raise CommandError("今日接单已达上限（{}/{}）".format(accepted_today, max_accept))
        min_price = float(target.get("min_price") or job.get("min_price") or DEFAULT_MIN_PRICE)
        price = target.get("price")
        if price is not None and float(price) < min_price:
            raise CommandError("订单价格低于下限：{} < {}".format(price, min_price))
        return [build_step("accept_order", order_id=order_id, platform=str(target.get("platform") or ""))]

    def describe(self, job: dict) -> dict:
        target = job.get("target") or {}
        platform = self._platform(target, job)
        app = PLATFORMS[platform]
        limit = int(target.get("limit") or job.get("limit") or 20)
        min_price = target.get("min_price") or job.get("min_price")

        steps: list[dict] = [
            build_step("open_app", app=app),
            build_step("goto_order_hall", platform=platform),
            build_step("list_orders", platform=platform, limit=limit, min_price=min_price or DEFAULT_MIN_PRICE),
            build_step("parse_orders", limit=limit),
        ]
        accepted = self._accept_steps(target, job)
        steps.extend(accepted)
        if accepted:
            steps.append(build_step("capture_screenshot", tag="accepted"))
        steps.append(build_step("stop", reason="await_human_confirm"))

        return {
            "job_id": job.get("_id"),
            "adapter": self.NAME,
            "platform": platform,
            "app": app,
            "target": target,
            "accept_authorized": bool(job.get("accept_authorized")),
            "max_accept": int(job.get("max_accept") or DEFAULT_MAX_ACCEPT),
            "steps": validate_steps(steps),
            "stop_before": self.STOP_BEFORE,
        }
