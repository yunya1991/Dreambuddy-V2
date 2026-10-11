"""架构模式识别器 — 基于目录结构、命名约定、import 关系识别常见架构模式。

PoE Task 1：识别 MVC / 分层 / 事件驱动 / 管道过滤 / 插件化 / 微内核，
每条模式结论输出 Evidence（provenance + level + confidence + known_gaps）。

Evidence-First 硬约束：无证据的结论禁止输出（NFR-1）。
FAIL-OPEN：异常/无模式时返回 level=unknown 的 Evidence（NFR-7）。
"""
from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field
from typing import Any

from .evidence import Evidence, EvidenceLevel


# ---------- 模式定义 ----------

@dataclass
class PatternRule:
    """架构模式识别规则。"""
    pattern: str                  # 模式名（如 "MVC"）
    required_dirs: list[str]      # 必须同时出现的目录关键字
    confidence: float = 0.8       # 命中时置信度
    level: str = "derivation"    # 默认 derivation 级（基于目录结构推导）
    known_gaps: list[str] = field(default_factory=list)


# 内置规则集 — 基于目录命名约定
_DEFAULT_RULES: list[PatternRule] = [
    PatternRule(
        pattern="MVC",
        required_dirs=["models", "views", "controllers"],
        confidence=0.85,
        known_gaps=["目录名匹配不等于严格 MVC 架构，需人工确认是否符合模型-视图-控制器职责分离"],
    ),
    PatternRule(
        pattern="Layered",
        required_dirs=["services", "repositories"],
        confidence=0.8,
        known_gaps=["分层模式可能与其他模式叠加（如 MVC + Service Layer），需结合依赖图确认"],
    ),
    PatternRule(
        pattern="Layered-API",
        required_dirs=["api", "services"],
        confidence=0.75,
        known_gaps=["api/services 命名也可能出现在非分层架构中"],
    ),
    PatternRule(
        pattern="EventDriven",
        required_dirs=["events", "handlers"],
        confidence=0.7,
        known_gaps=["events/handlers 目录可能仅是辅助模块，需结合装饰器（@handler）或消息队列代码确认"],
    ),
    PatternRule(
        pattern="Pipeline",
        required_dirs=["stages", "pipeline"],
        confidence=0.7,
        known_gaps=["需结合调用链确认各 stage 顺序连接"],
    ),
    PatternRule(
        pattern="Plugin",
        required_dirs=["plugins", "core"],
        confidence=0.7,
        known_gaps=["需确认 plugins 目录下的模块符合统一注册契约"],
    ),
    PatternRule(
        pattern="Microkernel",
        required_dirs=["kernel", "extensions"],
        confidence=0.65,
        known_gaps=["微内核需确认核心模块最小化且扩展隔离"],
    ),
]


# ---------- 结果数据结构 ----------

@dataclass
class PatternConclusion:
    """架构模式结论（带 Evidence 引用）。"""
    pattern: str
    evidence: Evidence
    matched_dirs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern": self.pattern,
            "matched_dirs": self.matched_dirs,
            "evidence": self.evidence,
        }


# ---------- 识别器 ----------

class ArchitecturePatternDetector:
    """架构模式识别器。

    识别策略：
    1. 扫描目标目录的子目录结构
    2. 比对预定义模式规则（基于目录命名约定）
    3. 命中规则即输出 PatternConclusion + Evidence
    4. 无命中时输出 level=unknown 的 Evidence 说明降级原因
    """

    def __init__(self, rules: list[PatternRule] | None = None) -> None:
        self.rules = rules if rules is not None else _DEFAULT_RULES

    def detect(self, target: str) -> dict[str, Any]:
        """识别目标目录的架构模式。

        Args:
            target: 目标工程根路径

        Returns:
            {
                "target": str,
                "patterns": [PatternConclusion...],
                "evidence": [Evidence...],   # 全部 Evidence（含 unknown 降级）
                "raw": { "matched_dirs": [...], "scanned_dirs": [...] },
            }
        """
        if not os.path.isdir(target):
            return self._failopen_unknown(
                target,
                f"目标不是目录或不存在: {target}",
                gaps=["目标路径不存在或不是目录，无法识别架构模式"],
            )

        scanned_dirs = self._scan_subdirs(target)
        conclusions: list[PatternConclusion] = []
        all_evidence: list[Evidence] = []

        for rule in self.rules:
            matched = self._match_rule(rule, scanned_dirs)
            if matched:
                ev = Evidence(
                    result=f"检测到 {rule.pattern} 架构模式（命中目录: {', '.join(matched)}）",
                    level=EvidenceLevel.DERIVATION,
                    provenance={
                        "target": target,
                        "matched_dirs": matched,
                        "rule": rule.pattern,
                        "analysis": "directory_naming_convention",
                    },
                    confidence=rule.confidence,
                    known_gaps=list(rule.known_gaps),
                )
                conclusions.append(PatternConclusion(
                    pattern=rule.pattern,
                    evidence=ev,
                    matched_dirs=matched,
                ))
                all_evidence.append(ev)

        # 无任何模式命中 → 输出 unknown Evidence
        if not conclusions:
            all_evidence.append(Evidence(
                result="未检测到已知架构模式",
                level=EvidenceLevel.UNKNOWN,
                provenance={
                    "target": target,
                    "scanned_dirs": scanned_dirs,
                    "analysis": "directory_naming_convention",
                },
                confidence=0.3,
                known_gaps=[
                    "目标目录的子目录命名不匹配任何预定义模式",
                    "可能采用非标准命名或自定义架构，需结合 import 关系和代码内容人工确认",
                ],
            ))

        return {
            "target": target,
            "patterns": [c.to_dict() for c in conclusions],
            "evidence": all_evidence,
            "raw": {
                "matched_dirs": [d for c in conclusions for d in c.matched_dirs],
                "scanned_dirs": scanned_dirs,
            },
        }

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @staticmethod
    def _scan_subdirs(root: str) -> list[str]:
        """扫描一级子目录名（小写）。"""
        try:
            entries = sorted(os.listdir(root))
        except OSError:
            return []
        dirs = []
        for name in entries:
            full = os.path.join(root, name)
            if os.path.isdir(full) and not name.startswith(".") and not name.startswith("__"):
                dirs.append(name.lower())
        return dirs

    @staticmethod
    def _match_rule(rule: PatternRule, scanned_dirs: list[str]) -> list[str]:
        """规则匹配：required_dirs 全部出现在 scanned_dirs 中即命中（子串匹配）。"""
        matched: list[str] = []
        for required in rule.required_dirs:
            hit = next(
                (d for d in scanned_dirs if required in d or d in required),
                None,
            )
            if hit is None:
                return []
            matched.append(hit)
        return matched

    def _failopen_unknown(
        self,
        target: str,
        result: str,
        gaps: list[str],
    ) -> dict[str, Any]:
        """FAIL-OPEN：返回带 unknown Evidence 的降级结果。"""
        ev = Evidence(
            result=result,
            level=EvidenceLevel.UNKNOWN,
            provenance={"target": target, "analysis": "architecture_pattern_detector"},
            confidence=0.0,
            known_gaps=gaps,
        )
        return {
            "target": target,
            "patterns": [],
            "evidence": [ev],
            "raw": {"error": "failopen"},
        }


# ---------- 模块级入口 ----------

def detect_architecture_patterns(target: str) -> dict[str, Any]:
    """架构模式识别的模块级入口。

    Args:
        target: 目标工程根路径

    Returns:
        见 ArchitecturePatternDetector.detect
    """
    detector = ArchitecturePatternDetector()
    return detector.detect(target)
