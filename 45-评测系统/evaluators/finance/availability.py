# -*- coding: utf-8 -*-
"""
availability.py — 金融功能与高可用评测器（P2-3）
==================================================
SPEC §5.1 F-H2：多副本 + 探活；5 类故障注入（pod-kill、网络延迟、交易所 API 超时、
DB 主备切换、磁盘写满）；订单 RPO=0、订单 RTO≤30s、行情 RTO≤60s。

本模块只负责「模板 + 判定」，不含真实注入执行：
- 模板：`template_for(kind)` 返回声明式故障模板（命令/清理/检查项/路径/时限）
- 渲染：`render_plan(kind, target, nonce)` 替换目标占位符，产出可执行命令清单
- 执行：`execute_plan(plan, runner)` 由注入的 runner 真跑命令（默认不执行，避免误伤）
- 判定：`AvailabilityEvaluator.evaluate(observations, run_id)` 产出单条 hard item F-H2
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from storage.repo import EvalItemRecord

FAULT_KINDS = (
    "pod_kill",
    "network_delay",
    "exchange_timeout",
    "db_failover",
    "disk_full",
)

ORDER_PATH = "orders"
MARKET_PATH = "market_data"
VALID_PATHS = (ORDER_PATH, MARKET_PATH)

ORDER_RTO_S = 30
MARKET_RTO_S = 60


class FaultPlanError(ValueError):
    """故障模板/渲染/执行参数非法。"""


@dataclass(frozen=True)
class FaultTemplate:
    """一类故障的声明式注入模板（命令支持 `{target}` 与 `{nonce}` 占位符）。"""

    kind: str
    scenario: str
    path: str
    max_recovery_s: int
    target_keys: tuple[str, ...]
    setup: tuple[str, ...]
    cleanup: tuple[str, ...]
    checks: tuple[str, ...]

    def validate(self) -> None:
        if self.path not in VALID_PATHS:
            raise FaultPlanError(f"{self.kind} 的 path 非法：{self.path}")


@dataclass(frozen=True)
class FaultPlan:
    """渲染后的注入计划：可直接交给执行器或人工预演。"""

    kind: str
    namespace: str
    path: str
    max_recovery_s: int
    commands: tuple[str, ...]
    cleanup: tuple[str, ...]
    checks: tuple[str, ...]


@dataclass(frozen=True)
class InjectionExecution:
    ok: bool
    executed: list[str] = field(default_factory=list)
    error: str | None = None


TEMPLATES: dict[str, FaultTemplate] = {
    "pod_kill": FaultTemplate(
        kind="pod_kill",
        scenario="随机强杀交易进程 Pod，验证多副本接管与零丢单",
        path=ORDER_PATH,
        max_recovery_s=ORDER_RTO_S,
        target_keys=("pod_selector",),
        setup=("kubectl delete pod -l {pod_selector} --grace-period=0 --force -n {nonce}",),
        cleanup=(),
        checks=("副本数恢复", "订单零丢失对账", "风控状态一致"),
    ),
    "network_delay": FaultTemplate(
        kind="network_delay",
        scenario="注入 200ms±50ms / 5% 丢包的网络延迟，验证下单链路降级",
        path=ORDER_PATH,
        max_recovery_s=ORDER_RTO_S,
        target_keys=("iface",),
        setup=("tc qdisc add dev {iface} root netem delay 200ms 50ms loss 5%",),
        cleanup=("tc qdisc del dev {iface} root",),
        checks=("下单成功率", "超时重试幂等", "熔断是否触发"),
    ),
    "exchange_timeout": FaultTemplate(
        kind="exchange_timeout",
        scenario="阻断交易所 API 出站，验证行情超时、重连与订单补偿",
        path=MARKET_PATH,
        max_recovery_s=MARKET_RTO_S,
        target_keys=("dest",),
        setup=("iptables -A OUTPUT -p tcp --dport 443 -d {dest} -j DROP",),
        cleanup=("iptables -D OUTPUT -p tcp --dport 443 -d {dest} -j DROP",),
        checks=("行情重连", "挂单补偿", "错误率曲线回落"),
    ),
    "db_failover": FaultTemplate(
        kind="db_failover",
        scenario="主库切换至备库，验证连接重连与事务不丢",
        path=ORDER_PATH,
        max_recovery_s=ORDER_RTO_S,
        target_keys=("db_host",),
        setup=("docker exec {db_host} pg_ctl promote -D /var/lib/postgresql/data",),
        cleanup=(),
        checks=("主备切换完成", "事务零丢失", "订单对账一致"),
    ),
    "disk_full": FaultTemplate(
        kind="disk_full",
        scenario="写满数据盘，验证写入失败可观测、降级与恢复",
        path=ORDER_PATH,
        max_recovery_s=ORDER_RTO_S,
        target_keys=("mount",),
        setup=("dd if=/dev/zero of={mount}/eval-fill.bin bs=1M count=1024",),
        cleanup=("rm -f {mount}/eval-fill.bin",),
        checks=("写入失败可观测", "服务不崩溃", "清理后恢复"),
    ),
}


def template_for(kind: str) -> FaultTemplate:
    try:
        template = TEMPLATES[kind]
    except KeyError as exc:
        raise FaultPlanError(f"未注册的故障类型：{kind}") from exc
    template.validate()
    return template


def render_plan(kind: str, target: dict[str, str], nonce: str = "") -> FaultPlan:
    """替换占位符；缺少目标键直接拒绝（不允许带着未替换变量上线）。"""
    template = template_for(kind)
    values = {**target, "nonce": nonce}
    try:
        commands = tuple(cmd.format_map(values) for cmd in template.setup)
        cleanup = tuple(cmd.format_map(values) for cmd in template.cleanup)
    except KeyError as exc:
        raise FaultPlanError(f"{kind} 缺少目标参数：{exc.args[0]}") from exc
    return FaultPlan(
        kind=template.kind,
        namespace=nonce,
        path=template.path,
        max_recovery_s=template.max_recovery_s,
        commands=commands,
        cleanup=cleanup,
        checks=template.checks,
    )


def execute_plan(
    plan: FaultPlan, runner: Callable[[str], None] | None = None
) -> InjectionExecution:
    """按序执行命令；runner 不存在时拒绝（防止默认误跑生产命令）。"""
    if runner is None:
        raise FaultPlanError("execute_plan 需要注入 runner，默认不执行任何命令")
    executed: list[str] = []
    for command in plan.commands:
        try:
            runner(command)
        except Exception as exc:  # noqa: BLE001 — 注入失败需保留已执行命令供人工清理
            return InjectionExecution(ok=False, executed=executed, error=str(exc))
        executed.append(command)
    return InjectionExecution(ok=True, executed=executed)


@dataclass(frozen=True)
class FaultObservation:
    """一次故障注入的观测记录（报告证据字段：起止/影响请求/错误率曲线/恢复耗时）。"""

    kind: str
    path: str
    started_at: datetime
    recovered_at: datetime | None
    orders_lost: int = 0
    impacted_requests: int = 0
    error_rate_curve: tuple[float, ...] = ()

    def recovery_s(self) -> float | None:
        if self.recovered_at is None:
            return None
        return (self.recovered_at - self.started_at).total_seconds()


class AvailabilityEvaluator:
    """F-H2 判定：5 类故障齐全 + 订单零丢失 + 订单 RTO≤30s / 行情 RTO≤60s。"""

    def __init__(self, order_rto_s: int = ORDER_RTO_S, market_rto_s: int = MARKET_RTO_S) -> None:
        self._order_rto_s = order_rto_s
        self._market_rto_s = market_rto_s

    def evaluate(self, observations: list[FaultObservation], run_id: str) -> list[EvalItemRecord]:
        codes: list[str] = []

        seen = {observation.kind for observation in observations}
        for kind in FAULT_KINDS:
            if kind not in seen:
                codes.append(f"F-H2_missing_fault:{kind}")

        for observation in observations:
            codes.extend(self._check(observation))

        status = "BLOCK" if codes else "PASS"
        return [
            EvalItemRecord(
                item_id=f"{run_id}-F-H2",
                run_id=run_id,
                name="F-H2-availability",
                kind="hard",
                score=None,
                n=None,
                ci_lower=None,
                ci_upper=None,
                weight=None,
                status=status,
                evidence_id=None,
                detail="; ".join(codes) or None,
            )
        ]

    def _check(self, observation: FaultObservation) -> list[str]:
        kind = observation.kind
        if kind not in TEMPLATES:
            return [f"F-H2_unknown_fault:{kind}"]
        if observation.path not in VALID_PATHS:
            return [f"F-H2_invalid_path:{kind}"]

        recovery = observation.recovery_s()
        if recovery is None:
            return [f"F-H2_not_recovered:{kind}"]

        codes: list[str] = []
        if not observation.error_rate_curve:
            codes.append(f"F-H2_incomplete_evidence:{kind}")

        limit = self._order_rto_s if observation.path == ORDER_PATH else self._market_rto_s
        if recovery > limit:
            label = (
                "order_rto_exceeded" if observation.path == ORDER_PATH else "market_rto_exceeded"
            )
            codes.append(f"F-H2_{label}:{kind}:{recovery}")

        if observation.orders_lost > 0:
            codes.append(f"F-H2_order_rpo_violation:{kind}")
        return codes
