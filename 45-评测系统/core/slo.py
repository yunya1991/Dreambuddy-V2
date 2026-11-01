# -*- coding: utf-8 -*-
"""
slo.py — SLO 看板与告警（P4-5，SPEC §17 + §14.5）
==================================================
9 项 KPI：有信号给实测值，无信号标 no_data（绝不填 0 伪装达标）。
告警：队列积压 ≥ 阈值（默认 10）、SLA 达标率 < 90%。

数据来源：
- backlog 由 Metrics 从 repo 自动推导
- 其余 8 项为外部实测信号（API 可用性、p95 延迟、误拦截率、证据完整率、
  复算一致率、分支覆盖率），通过 `--signals` JSON 或调用方注入
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml
from storage.repo import EvalRepo, zulu

from core.metrics import Metrics

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "slo.yaml"


class SLOError(ValueError):
    """SLO 配置或信号非法（未知 KPI key / 类型错误 / 配置字段非法）。"""


@dataclass(frozen=True)
class KpiSpec:
    key: str
    name: str
    unit: str  # ratio / ms / count
    operator: str  # >= / <= / < / ==
    threshold: float
    source: str  # metrics / signals


KPI_DEFINITIONS: tuple[KpiSpec, ...] = (
    KpiSpec("api_availability", "API 可用性", "ratio", ">=", 0.995, "signals"),
    KpiSpec("accepted_latency_p95_ms", "受理延迟 p95", "ms", "<=", 2000.0, "signals"),
    KpiSpec("l1_latency_p95_ms", "L1 完成 p95", "ms", "<=", 60000.0, "signals"),
    KpiSpec("sla_attainment_rate", "SLA 达标率", "ratio", ">=", 0.95, "signals"),
    KpiSpec("misblock_rate_upper", "误拦截率 Wilson 上界", "ratio", "<=", 0.01, "signals"),
    KpiSpec("evidence_complete_rate", "证据完整率", "ratio", "==", 1.0, "signals"),
    KpiSpec("recompute_match_rate", "同 spec 复算一致率", "ratio", ">=", 0.95, "signals"),
    KpiSpec("branch_coverage_rate", "分支覆盖率", "ratio", "==", 1.0, "signals"),
    KpiSpec("backlog", "队列积压", "count", "<", 10.0, "metrics"),
)

EXTERNAL_KPI_KEYS = frozenset(spec.key for spec in KPI_DEFINITIONS if spec.source == "signals")


@dataclass(frozen=True)
class SLOConfig:
    """SLO 目标与告警阈值（config/slo.yaml 可覆盖）。"""

    sla_target: float = 0.95
    gray_sla_target: float = 0.90
    backlog_threshold: int = 10
    sla_alert_threshold: float = 0.90

    @classmethod
    def load(cls, path: str | Path | None = None) -> "SLOConfig":
        config_path = Path(path) if path else DEFAULT_CONFIG_PATH
        if not config_path.exists():
            return cls()
        try:
            data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise SLOError(f"slo 配置解析失败：{exc}") from exc
        if not isinstance(data, dict):
            raise SLOError("slo 配置必须是映射")

        known = {"sla_target", "gray_sla_target", "backlog_threshold", "sla_alert_threshold"}
        unknown = set(data) - known
        if unknown:
            raise SLOError(f"slo 配置含未知字段：{sorted(unknown)}")

        values = cls()
        try:
            return cls(
                sla_target=float(data.get("sla_target", values.sla_target)),
                gray_sla_target=float(data.get("gray_sla_target", values.gray_sla_target)),
                backlog_threshold=int(data.get("backlog_threshold", values.backlog_threshold)),
                sla_alert_threshold=float(
                    data.get("sla_alert_threshold", values.sla_alert_threshold)
                ),
            )
        except (TypeError, ValueError) as exc:
            raise SLOError(f"slo 配置字段类型非法：{exc}") from exc


class SLODashboard:
    """repo + Metrics 推导 backlog，叠加外部信号后输出 KPI 与告警。"""

    def __init__(
        self,
        repo: EvalRepo,
        metrics: Metrics | None = None,
        config: SLOConfig | None = None,
        shadow: bool | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._metrics = metrics or Metrics(repo=repo, shadow=shadow, clock=self._clock)
        self._config = config or SLOConfig()
        self._shadow = shadow

    def snapshot(self, signals: dict[str, float] | None = None) -> dict[str, Any]:
        return build_snapshot(
            metrics=self._metrics,
            config=self._config,
            signals=signals,
            shadow=self._shadow,
            clock=self._clock,
        )


def build_snapshot(
    metrics: Metrics,
    config: SLOConfig,
    signals: dict[str, float] | None = None,
    shadow: bool | None = None,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """生成 9 项 KPI 快照与告警；缺失信号记 no_data，不伪造数值。"""
    signals = dict(signals or {})
    unknown = set(signals) - EXTERNAL_KPI_KEYS
    if unknown:
        raise SLOError(f"未知 KPI 信号：{sorted(unknown)}")

    metrics_snapshot = metrics.snapshot()
    backlog = int(metrics_snapshot["backlog"])
    sla_target = config.gray_sla_target if shadow else config.sla_target

    kpis: list[dict[str, Any]] = []
    for spec in KPI_DEFINITIONS:
        if spec.source == "metrics":
            value = float(backlog)
            threshold = float(config.backlog_threshold) if spec.key == "backlog" else spec.threshold
        else:
            raw = signals.get(spec.key)
            value = None if raw is None else float(raw)
            threshold = sla_target if spec.key == "sla_attainment_rate" else spec.threshold
        kpis.append(
            {
                "key": spec.key,
                "name": spec.name,
                "unit": spec.unit,
                "source": spec.source,
                "target": _format_target(spec.unit, spec.operator, threshold),
                "threshold": threshold,
                "value": value,
                "status": _status(spec.operator, value, threshold),
            }
        )

    alerts: list[dict[str, Any]] = []
    if backlog >= config.backlog_threshold:
        alerts.append(
            {
                "key": "backlog",
                "value": backlog,
                "threshold": config.backlog_threshold,
                "severity": "warning",
            }
        )
    sla = signals.get("sla_attainment_rate")
    if sla is not None and float(sla) < config.sla_alert_threshold:
        alerts.append(
            {
                "key": "sla_attainment_rate",
                "value": float(sla),
                "threshold": config.sla_alert_threshold,
                "severity": "critical",
            }
        )

    generated_clock = clock or (lambda: datetime.now(timezone.utc))
    return {
        "generated_at": zulu(generated_clock()),
        "gate_shadow": shadow if shadow is not None else metrics_snapshot.get("gate_shadow"),
        "backlog": backlog,
        "kpis": kpis,
        "alerts": alerts,
    }


def _status(operator: str, value: float | None, threshold: float) -> str:
    if value is None:
        return "no_data"
    if operator == ">=":
        return "ok" if value >= threshold else "breach"
    if operator == "<=":
        return "ok" if value <= threshold else "breach"
    if operator == "<":
        return "ok" if value < threshold else "breach"
    if operator == "==":
        return "ok" if value == threshold else "breach"
    raise SLOError(f"未知比较运算符：{operator}")


def _format_target(unit: str, operator: str, threshold: float) -> str:
    if unit == "ratio":
        return f"{operator}{threshold * 100:.1f}%"
    if unit == "ms":
        return f"{operator}{int(threshold)}ms"
    return f"{operator}{int(threshold)}"
