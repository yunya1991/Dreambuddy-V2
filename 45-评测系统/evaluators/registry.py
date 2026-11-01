# -*- coding: utf-8 -*-
"""
registry.py — 评测器注册与版本锁定（P2-9）
============================================
- 每个评测器以 (name, version) 唯一注册；重复注册拒绝
- `resolve(name, version)` 精确解析；未注册评测器/版本 → EvaluatorNotFoundError（拒绝执行）
- `lock(name)` 把「当前最新版本」钉住，后续注册新版本不影响已锁定引用
- `load_defaults()` 注册 P2 全部内置评测器（1.0.0）

版本格式采用 `MAJOR.MINOR.PATCH` 三段数字，保证可比较与可审计。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from evaluators.ai.judge import JudgeCalibrationEvaluator
from evaluators.ai.stress import StressEvaluator
from evaluators.common.e3 import E3Validator
from evaluators.engineering.scan import EngineeringScanEvaluator
from evaluators.engineering.tests import EngineeringTestsEvaluator
from evaluators.finance.availability import AvailabilityEvaluator
from evaluators.finance.backtest import BacktestStatisticsEvaluator

VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


class RegistryError(ValueError):
    """注册参数非法（名称/版本格式/重复注册）。"""


class EvaluatorNotFoundError(LookupError):
    """请求的评测器或版本未注册，禁止执行。"""


@dataclass(frozen=True)
class EvaluatorRef:
    """锁定后的评测器引用（写入报告，保证可复算）。"""

    name: str
    version: str


def _version_key(version: str) -> tuple[int, int, int]:
    major, minor, patch = version.split(".")
    return int(major), int(minor), int(patch)


class EvaluatorRegistry:
    def __init__(self) -> None:
        self._registry: dict[str, dict[str, object]] = {}

    def register(self, name: str, version: str, evaluator: object) -> None:
        if not isinstance(name, str) or not name.strip():
            raise RegistryError("评测器名称必须为非空字符串")
        if not isinstance(version, str) or not VERSION_PATTERN.match(version):
            raise RegistryError(f"版本必须为 MAJOR.MINOR.PATCH，收到 {version!r}")
        versions = self._registry.setdefault(name, {})
        if version in versions:
            raise RegistryError(f"评测器 {name}@{version} 已注册，禁止覆盖")
        versions[version] = evaluator

    def resolve(self, name: str, version: str | None = None) -> object:
        versions = self._registry.get(name)
        if not versions:
            raise EvaluatorNotFoundError(f"评测器未注册：{name}")
        target = version or self.versions(name)[-1]
        if target not in versions:
            raise EvaluatorNotFoundError(
                f"评测器版本未注册：{name}@{target}（已注册：{', '.join(self.versions(name))}）"
            )
        return versions[target]

    def lock(self, name: str, version: str | None = None) -> EvaluatorRef:
        """钉住当前版本；未指定时锁定最新版本。"""
        resolved = version or self.versions(name)[-1]
        self.resolve(name, resolved)
        return EvaluatorRef(name=name, version=resolved)

    def versions(self, name: str) -> tuple[str, ...]:
        versions = self._registry.get(name)
        if not versions:
            raise EvaluatorNotFoundError(f"评测器未注册：{name}")
        return tuple(sorted(versions, key=_version_key))

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._registry))


def load_defaults() -> EvaluatorRegistry:
    """注册 P2 全部内置评测器（版本 1.0.0）。"""
    registry = EvaluatorRegistry()
    builtins = {
        "e3": E3Validator,
        "finance-availability": AvailabilityEvaluator,
        "finance-backtest-stats": BacktestStatisticsEvaluator,
        "ai-judge-calibration": JudgeCalibrationEvaluator,
        "ai-stress": StressEvaluator,
        "engineering-scan": EngineeringScanEvaluator,
        "engineering-tests": EngineeringTestsEvaluator,
    }
    for name, evaluator in builtins.items():
        registry.register(name, "1.0.0", evaluator)
    return registry
