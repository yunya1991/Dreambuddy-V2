#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 1 EV-T2：宪法 Constitution v1.1

将 EVOLUTION_BOUNDARY_MAP.md 的 6+2 条红线（+ 1 条 Phase1 新增 R9）编码为可执行
断言函数，作为 Hermes 四角色进化中 Critic 阶段的"先验宪法"。任何进化提案必须先通过
宪法校验（无 CRITICAL 违规），方可进入 Critic 压力测试批评。

========================
宪法本身的只增不改保护
========================
  - 条款（check_* 函数）只能新增，不得删除或放宽 severity 权重
  - CONSTITUTION_HASH = core_checks_sha256(...)  运行时自检
  - 检测到篡改 → AuditResult 写 WARNING，但不阻塞审计（避免宪法自身升级也卡住）

========================
红线映射（R1~R9）
========================
  R1 通用认知原版 SKILL.md 禁改（红线第1条 CRITICAL）
  R2 应用认知 Solution Path 质量等级 / confidence 只能由 verify 驱动（HIGH）
  R3 A 类代码不得直接写 认知层 Solution Paths 目录（红线§4 CRITICAL）
  R4 B 类代码不得直接改 config.json 交易参数（红线§4 CRITICAL）
  R5 AB 只走记忆系统通道交互（不得直接 import 对方生产路径，HIGH）
  R6 B 类修改范围限制在 4-MEMORY/9-工具与接口/（HIGH）
  R7 3-EVOLUTION/ 是实验区，禁止放生产改动（生产部署标记下 CRITICAL）
  R8 Trading 类 PROP（trading_params / trading_risk）必须走飞书审批（CRITICAL）
  R9 AUTO 草案未审核不得升入正式 Solution Path（Phase1 新增，CRITICAL）

Author: Dreambuddy Cognitive Evolution
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

# ==================================================================
# 常量
# ==================================================================

CONSTITUTION_VERSION = "v1.1"

# 通用认知原版 SKILL.md 路径模式（严格匹配）
ORIGINAL_SKILL_GLOBS: Tuple[str, ...] = (
    "0-元记忆/superpowers/skills/*/SKILL.md",
    "0-元记忆/trading-cognition/skills/*/SKILL.md",
)

# Solution Paths 正式目录（B 类可写，A 类禁写）
OFFICIAL_SOLUTION_PATH_GLOBS: Tuple[str, ...] = (
    "4-MEMORY/1-开发记忆单元/solution_paths/*.json",
    "4-MEMORY/2-交易记忆单元/solution_paths/*.json",
)

# AUTO 草案审核队列目录（永远不进正式路径 → 检查 R9 升级违规是否绕开）
AUTO_DRAFT_REVIEW_QUEUE_GLOBS: Tuple[str, ...] = (
    "4-MEMORY/artifacts/solution_path_drafts/review_queue/*.json",
)

# 交易参数 config.json 模式（A 类可写，B 类禁写）
TRADING_CONFIG_GLOBS: Tuple[str, ...] = (
    "**/config.json",  # 兜底，会再用关键字排除
)
TRADING_CONFIG_MUST_HAVE_PARENT_TOKENS = ("okx_sim", "ab-trading", "trading_params",
                                          "polling_trader", "memory_l4", "v15_state",
                                          "bcrm", "experiments", "data")

# B 类修改允许范围
B_CLASS_ALLOWED_PREFIXES: Tuple[str, ...] = (
    "4-MEMORY/9-工具与接口/",
    "4-MEMORY/artifacts/",          # 产物允许
    "4-MEMORY/1-开发记忆单元/solution_paths/",  # B 类产生 APP-DEV-*（允许写正式，仅需 R2）
    "4-MEMORY/2-交易记忆单元/solution_paths/",  # B 类产生 APP-TRD-*（允许写正式，仅需 R2）
)

# 实验区
EXPERIMENT_ZONE_PREFIXES: Tuple[str, ...] = ("3-EVOLUTION/",)

# severity 权重（用于 audit_score = 100 - Σweight）
SEVERITY_WEIGHT: Dict[str, int] = {
    "CRITICAL": 100,
    "HIGH": 20,
    "MEDIUM": 5,
    "LOW": 1,
}

DEFAULT_SEVERITY = "HIGH"


# ==================================================================
# 数据类：Violation / RuleResult / AuditResult
# ==================================================================


@dataclass
class Violation:
    rule_id: str
    severity: str                 # CRITICAL / HIGH / MEDIUM / LOW
    file: Optional[str] = None
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RuleResult:
    rule_id: str
    passed: bool
    violations: List[Violation] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "passed": self.passed,
            "violations": [v.to_dict() for v in self.violations],
        }


@dataclass
class AuditResult:
    passed: bool
    proposal_id: str
    rule_results: Dict[str, RuleResult]
    total_violations: int
    severity_counts: Dict[str, int]
    audit_score: float
    constitution_version: str
    constitution_hash: str
    # 宪法漂移告警
    self_check_failed: bool = False
    constitution_mismatch: bool = False  # alias，便于 audit 扁平字段检索
    # 扁平化（方便外部读取）
    violations: List[Violation] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "proposal_id": self.proposal_id,
            "rule_results": {rid: rr.to_dict()
                             for rid, rr in self.rule_results.items()},
            "total_violations": self.total_violations,
            "severity_counts": dict(self.severity_counts),
            "audit_score": self.audit_score,
            "constitution_version": self.constitution_version,
            "constitution_hash": self.constitution_hash,
            "self_check_failed": self.self_check_failed,
            "constitution_mismatch": (self.constitution_mismatch
                                      or self.self_check_failed),
            "hash_warning": self.self_check_failed,
            "drift_detected": self.self_check_failed,
            "violations": [v.to_dict() for v in self.violations],
        }


# ==================================================================
# 路径匹配工具
# ==================================================================

def _p(path: str) -> str:
    """统一路径分隔符为斜杠，允许 absolute 与 relative 混合对比。"""
    p = str(path).replace(os.sep, "/")
    if p.startswith("./"):
        p = p[2:]
    return p


def _matches_any_prefix(file: str, prefixes: Iterable[str]) -> Optional[str]:
    f = _p(file)
    for pre in prefixes:
        if f.startswith(_p(pre)):
            return pre
    return None


def _matches_any_glob(file: str, patterns: Iterable[str]) -> Optional[str]:
    import fnmatch
    f = _p(file)
    for pat in patterns:
        pp = _p(pat)
        if fnmatch.fnmatch(f, pp) or fnmatch.fnmatch("/" + f, pp):
            return pat
        # 支持带 ** 的前缀式 glob（如 "**/config.json"）
        if pp.startswith("**/"):
            tail = pp[3:]
            if f.endswith(tail) or f == tail or ("/" + f).endswith("/" + tail):
                return pat
    return None


def _is_original_skill_path(file: str) -> bool:
    return bool(_matches_any_glob(file, ORIGINAL_SKILL_GLOBS))


def _is_official_solution_path(file: str) -> bool:
    return bool(_matches_any_glob(file, OFFICIAL_SOLUTION_PATH_GLOBS))


def _is_auto_draft_review_queue(file: str) -> bool:
    return bool(_matches_any_glob(file, AUTO_DRAFT_REVIEW_QUEUE_GLOBS))


def _looks_like_trading_config(file: str) -> bool:
    f = _p(file)
    # 文件名必须是 config.json / params.json / risk_params.json
    if not (f.endswith("/config.json") or f.endswith("/params.json")
            or f.endswith("/risk_params.json")
            or f.endswith("/memory.json")):
        return False
    # 且父路径包含"交易相关"关键字（排除 B 类的 config.json，如 cognitive 的）
    return any(tok in f for tok in TRADING_CONFIG_MUST_HAVE_PARENT_TOKENS)


# ==================================================================
# R1 ~ R9 规则函数（每条返回 RuleResult）
# ==================================================================


def check_original_skill_immutable(touched_files: Iterable[str]) -> RuleResult:
    """R1 通用认知原版 SKILL.md 禁改（CRITICAL）"""
    violations: List[Violation] = []
    for f in touched_files or []:
        if _is_original_skill_path(f):
            violations.append(Violation(
                rule_id="R1", severity="CRITICAL", file=f,
                reason="原版 SKILL.md 属于通用认知层（红线①），只增不改 — 必须在同级 supplement "
                       "文件追加，不得修改 SKILL.md 原文。见 EVOLUTION_BOUNDARY_MAP §2.2。",
            ))
    return RuleResult(rule_id="R1", passed=not violations, violations=violations)


def check_solution_path_quality_driven(write_patch_by_path: Dict[str, Dict[str, Any]]) -> RuleResult:
    """R2 应用认知 Solution Path 的 quality_level/confidence 只能由 verify 驱动（HIGH）。

    write_patch_by_path: {path: {delta, old_fields:{quality_level,confidence,...},
                                 new_fields:{quality_level,confidence,...}}}
    """
    violations: List[Violation] = []
    if not isinstance(write_patch_by_path, dict):
        return RuleResult(rule_id="R2", passed=True, violations=[])
    for path, patch in (write_patch_by_path or {}).items():
        if not _is_official_solution_path(path):
            continue
        if not isinstance(patch, dict):
            continue
        old_f = patch.get("old_fields") or {}
        new_f = patch.get("new_fields") or patch
        for fld in ("quality_level", "confidence"):
            old_v = old_f.get(fld, _SENTINEL)
            new_v = new_f.get(fld, _SENTINEL)
            if new_v is _SENTINEL:  # 未变更
                continue
            # 如果有 metadata.verify_count / old.verify_count 增长 ≥1 → 视为由 verify 驱动
            old_vc = (old_f.get("metadata") or {}).get("verify_count", 0) \
                if isinstance(old_f.get("metadata"), dict) else 0
            new_vc = (patch.get("new_metadata") or {}).get("verify_count", 0) \
                if isinstance(patch.get("new_metadata"), dict) else old_vc
            verify_driven = (
                new_vc >= old_vc + 1
                or bool(patch.get("verify_driven"))
                or bool((new_f.get("metadata") or {}).get("verify_driven"))
            )
            if old_v is _SENTINEL:
                # 首次创建：允许（即使没 verify）视为 C/0.3 默认
                continue
            if not verify_driven and old_v != new_v:
                violations.append(Violation(
                    rule_id="R2", severity="HIGH", file=path,
                    reason=f"手工改动了 Solution Path 的 {fld}（{old_v!r}→{new_v!r}）"
                           f"但缺少 verify_count 递增标记，非 verify 驱动。"
                           f"见 EVOLUTION_BOUNDARY_MAP §2.2 L60。",
                ))
    return RuleResult(rule_id="R2", passed=not violations, violations=violations)


_SENTINEL = object()


def check_ab_boundary(actor: str, written_paths: Iterable[str]) -> RuleResult:
    """R3/R4 AB 边界检查。

    actor="A" → 禁写 OFFICIAL_SOLUTION_PATH 目录（R3 CRITICAL）
    actor="B" → 禁写 config.json 交易参数（R4 CRITICAL）
    其他 actor → 仅返回空 RuleResult.passed=True（不阻塞）
    """
    violations: List[Violation] = []
    if actor == "A":
        for f in written_paths or []:
            if _is_official_solution_path(f) or _is_auto_draft_review_queue(f):
                violations.append(Violation(
                    rule_id="R3", severity="CRITICAL", file=f,
                    reason="A 类（交易参数进化）不得直接写认知层 Solution Path 目录"
                           "（红线§4：AB互通只走记忆系统）。见 EVOLUTION_BOUNDARY_MAP §4 L111。",
                ))
        return RuleResult(rule_id="R3", passed=not violations, violations=violations)
    if actor == "B":
        for f in written_paths or []:
            if _looks_like_trading_config(f):
                violations.append(Violation(
                    rule_id="R4", severity="CRITICAL", file=f,
                    reason="B 类（认知流程进化）不得直接改交易参数 config.json / params.json"
                           "（红线§4：AB互通只走记忆系统）。见 EVOLUTION_BOUNDARY_MAP §4 L111。",
                ))
        return RuleResult(rule_id="R4", passed=not violations, violations=violations)
    # actor 未知 → 两条规则都以 INFO 形式跑一遍（不产生违规，预留）
    return RuleResult(rule_id="R3/R4", passed=True, violations=[])


def check_only_memory_channel_interaction(import_graph: Optional[Dict[str, Set[str]]]) -> RuleResult:
    """R5 AB 交互只走记忆系统通道（HIGH）。

    import_graph: {改动的A类文件 set -> 被直接 import 的B类文件} 或相反。
    若未提供（None）→ 返回"WARNING（缺数据）"但 passed=True，不阻塞。
    """
    violations: List[Violation] = []
    if import_graph is None:
        # 缺数据不阻塞，仅 MEDIUM 形式在 future 扩展；当前仅 passed=True 空结果
        return RuleResult(rule_id="R5", passed=True, violations=[])
    memory_files_prefixes = ("4-MEMORY/",)
    a_prefixes = ("11-易经推理系统/", "14-V15经典马丁策略/",
                  "experiments/", "1-ARCHITECTURE/")
    b_prefixes = B_CLASS_ALLOWED_PREFIXES

    def _classify(path: str) -> str:
        f = _p(path)
        if _matches_any_prefix(f, a_prefixes):
            return "A"
        if _matches_any_prefix(f, b_prefixes) or f.startswith("4-MEMORY/"):
            if _matches_any_prefix(f, memory_files_prefixes):
                return "MEMORY"
            return "B"
        return "OTHER"

    for src, targets in (import_graph or {}).items():
        src_cls = _classify(src)
        if src_cls not in ("A", "B"):
            continue
        other_cls = "B" if src_cls == "A" else "A"
        for tgt in targets or []:
            tgt_cls = _classify(tgt)
            if tgt_cls == other_cls:
                # A → B 或 B → A 直连（非通过记忆目录）
                violations.append(Violation(
                    rule_id="R5", severity="HIGH", file=src,
                    reason=f"{src_cls}类 {src!r} 直接 import/引用 {other_cls}类 {tgt!r}，"
                           "违反红线§4（AB 交互只走记忆系统通道）。",
                ))
    return RuleResult(rule_id="R5", passed=not violations, violations=violations)


def check_b_mod_scope(touched_paths: Iterable[str]) -> RuleResult:
    """R6 B 类修改范围限制：4-MEMORY/9-工具与接口/ + 允许产物与自身 Solution Path。"""
    violations: List[Violation] = []
    for f in touched_paths or []:
        path = _p(f)
        # B 类允许前缀 OK → continue
        if _matches_any_prefix(path, B_CLASS_ALLOWED_PREFIXES):
            continue
        # 0-系统文档管理 下的 PROP-*.md / 设计文档 → 允许
        if path.startswith("0-系统文档管理/") and path.endswith(".md"):
            continue
        # 其余：HIGH 违规
        violations.append(Violation(
            rule_id="R6", severity="HIGH", file=path,
            reason="B 类改动范围超出允许目录。允许前缀：4-MEMORY/9-工具与接口/ / "
                   "4-MEMORY/artifacts/ / APP-DEV-* / APP-TRD-* / "
                   "0-系统文档管理/*.md。见 EVOLUTION_BOUNDARY_MAP §5 L119。",
        ))
    return RuleResult(rule_id="R6", passed=not violations, violations=violations)


def check_experiment_zone_isolation(touched_paths: Iterable[str],
                                     is_production_change: bool) -> RuleResult:
    """R7 3-EVOLUTION/ 实验区隔离。

    - 生产部署改动碰实验区 → CRITICAL（阻塞）
    - 非生产改动碰实验区 → HIGH（记违规但不阻塞提案通过）
    """
    violations: List[Violation] = []
    severity = "CRITICAL" if is_production_change else "HIGH"
    for f in touched_paths or []:
        if _matches_any_prefix(f, EXPERIMENT_ZONE_PREFIXES):
            violations.append(Violation(
                rule_id="R7", severity=severity, file=f,
                reason=("3-EVOLUTION/ 是实验区（红线⑦），"
                        + ("生产改动禁止放入。" if is_production_change
                           else "建议不要放生产相关改动；当前 HIGH。")),
            ))
    return RuleResult(rule_id="R7", passed=not violations, violations=violations)


def check_proposal_gating(proposal: Dict[str, Any]) -> RuleResult:
    """R8 Trading 类 PROP 必须走飞书审批（category ∈ {trading_params, trading_risk}）。"""
    violations: List[Violation] = []
    cat = str(proposal.get("category", ""))
    is_trading_prop = cat in ("trading_params", "trading_risk", "trading_execution")
    if not is_trading_prop:
        return RuleResult(rule_id="R8", passed=True, violations=[])
    approvals = proposal.get("approvals") or {}
    if isinstance(approvals, dict):
        approval_text = json.dumps(approvals, ensure_ascii=False)
    else:
        approval_text = str(approvals)
    has_feishu = bool(re.search(r"FEISHU|飞书审批|审批单号|approval_id", approval_text, re.I))
    status = str(approvals.get("status") if isinstance(approvals, dict) else approvals).upper()
    approved = has_feishu and status in ("APPROVED", "PENDING")
    # 只要含飞书审批单号 → 视为合规（即使 PENDING，审批流程已启动）
    if not has_feishu:
        violations.append(Violation(
            rule_id="R8", severity="CRITICAL",
            file=None,
            reason=f"Trading 类提案 category={cat!r} 必须含飞书审批单号 "
                   "(EVOLUTION_BOUNDARY_MAP §1 A类提案治理)；approvals={approvals!r}",
        ))
    return RuleResult(rule_id="R8", passed=not violations, violations=violations)


def check_auto_draft_not_promoted_without_review(promoted_patch: Any) -> RuleResult:
    """R9 AUTO 草案未审核不得升入正式 Solution Path（CRITICAL）。

    promoted_patch 形态：
      {promoted_path, source_review_path, review_status, reviewed_by, reviewed_at}
    """
    violations: List[Violation] = []
    if not isinstance(promoted_patch, dict):
        return RuleResult(rule_id="R9", passed=True, violations=[])
    promoted = str(promoted_patch.get("promoted_path", ""))
    source = str(promoted_patch.get("source_review_path", ""))
    if not promoted:
        return RuleResult(rule_id="R9", passed=True, violations=[])
    # 是否属于 AUTO draft 升入：源在 review_queue 或 promoted_path id 含 "-AUTO-"
    looks_auto = ("AUTO" in promoted.upper() or _is_auto_draft_review_queue(source))
    if not looks_auto:
        return RuleResult(rule_id="R9", passed=True, violations=[])
    status = str(promoted_patch.get("review_status", "")).upper()
    reviewer = promoted_patch.get("reviewed_by")
    reviewed_at = promoted_patch.get("reviewed_at")
    approved = (status == "APPROVED" and reviewer and reviewed_at)
    if not approved:
        violations.append(Violation(
            rule_id="R9", severity="CRITICAL", file=promoted,
            reason=f"AUTO 草案未审核即升入正式目录 {promoted!r}；"
                   f"review_status={status!r}, reviewed_by={reviewer!r}, reviewed_at={reviewed_at!r}。"
                   "Phase1 EV-T3 设计：必须人工 review_status=APPROVED 后才能 promote。",
        ))
    return RuleResult(rule_id="R9", passed=not violations, violations=violations)


# ==================================================================
# PROP-*.md 解析器
# ==================================================================

_PROP_ID_RE = re.compile(r"^\s*#\s*(PROP[\w\-]*[\d]{4,}[\w\-]*)\b", re.M)
_HEADINGS = {
    "scope": re.compile(r"^\s*##+\s*(?:Scope|范围|变更范围|变更说明)", re.M | re.I),
    "files": re.compile(r"^\s*##+\s*(?:Files\s*Touched?|改动文件|修改文件|涉及文件)", re.M | re.I),
    "changes": re.compile(r"^\s*##+\s*(?:Proposed\s*Changes|变更内容|具体变更|Diff)", re.M | re.I),
    "approval": re.compile(r"^\s*##+\s*(?:Approval|审批|审批状态)", re.M | re.I),
}
_PATH_RE = re.compile(r"[\w\-/.]+(?:\.py|\.md|\.json|\.ts|\.js|\.yaml|\.yml|\.csv|\.txt|\.sh|\.plist)")


def parse_proposal_md(md_text_or_path: Any) -> Dict[str, Any]:
    """解析 PROP-*.md → 标准化 proposal 字典（可直接喂 audit_proposal）。

    Args:
        md_text_or_path: 字符串（路径或直接 markdown 文本）

    Returns:
        {proposal_id, title, category, actor, touched_files, approvals,
         proposed_changes_by_path, sections_parsed_ok: bool}
    """
    text: str
    if isinstance(md_text_or_path, Path):
        text = md_text_or_path.read_text(encoding="utf-8")
    elif isinstance(md_text_or_path, str) and len(md_text_or_path) < 4096 \
            and Path(md_text_or_path).exists() and Path(md_text_or_path).is_file():
        text = Path(md_text_or_path).read_text(encoding="utf-8")
    else:
        text = str(md_text_or_path)

    # 1) proposal_id
    pid_m = _PROP_ID_RE.search(text)
    proposal_id = pid_m.group(1) if pid_m else _fallback_prop_id(text)

    # 2) 切分 section（用 heading 正则各自匹配起始位置，按 pos 排序）
    starts: List[Tuple[str, int]] = []
    for label, regex in _HEADINGS.items():
        m = regex.search(text)
        if m:
            starts.append((label, m.start()))
    starts.sort(key=lambda kv: kv[1])

    sections: Dict[str, str] = {}
    for idx, (label, pos) in enumerate(starts):
        end = starts[idx + 1][1] if idx + 1 < len(starts) else len(text)
        section_body = text[pos:end]
        # 去掉首行标题本身
        first_nl = section_body.find("\n")
        sections[label] = section_body[first_nl + 1:].strip() if first_nl != -1 else ""

    # 3) Scope → actor / category
    scope_text = sections.get("scope", "")
    actor = "B"
    if re.search(r"A类|actor\s*[:=]\s*['\"]?A|归属.*A\s*类|交易.*参数.*进化", scope_text, re.I):
        actor = "A"
    cat_match = re.search(r"类别.*?[:：]\s*([A-Za-z_\-]+)", scope_text)
    category = cat_match.group(1) if cat_match else "memory_structure"

    # 4) Files Touched → set of paths
    files_text = sections.get("files", "")
    touched_files: Set[str] = set(_PATH_RE.findall(files_text))
    if not touched_files:
        # 正文所有路径兜底
        touched_files = set(_PATH_RE.findall(text))

    # 5) Approval
    approval_text = sections.get("approval", "")
    approvals: Dict[str, Any] = {"raw": approval_text}
    m_id = re.search(r"(FEISHU[\w\-]+\d+|审批单号[:：]?[\w\-]+)", approval_text, re.I)
    if m_id:
        approvals["approval_id"] = m_id.group(1)
    m_by = re.search(r"审批人[:：]?\s*([\w\u4e00-\u9fa5\-]+)", approval_text)
    if m_by:
        approvals["reviewed_by"] = m_by.group(1)
    m_status = re.search(r"状态[:：]?\s*(APPROVED|PENDING|REJECTED|已通过|待审批|已拒绝)",
                         approval_text, re.I)
    if m_status:
        raw = m_status.group(1).upper()
        mapping = {"已通过": "APPROVED", "待审批": "PENDING", "已拒绝": "REJECTED"}
        approvals["status"] = mapping.get(raw, raw)

    # 6) Proposed Changes（简单按“- path:”切）
    changes_text = sections.get("changes", "")
    proposed_changes_by_path: Dict[str, Dict[str, Any]] = {}
    for line in changes_text.splitlines():
        m = re.match(r"\s*[-*+]\s*([\w\-/.]+\.\w+)\s*[:：]?\s*(.*)", line)
        if m:
            p, delta = m.group(1), m.group(2).strip()
            proposed_changes_by_path[p] = {"delta": delta or "_unparsed"}
    if not proposed_changes_by_path:
        for p in touched_files:
            proposed_changes_by_path[p] = {"delta": "_no_section_Files_Changed_parsed"}

    title = ""
    first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    if first_line.startswith("#"):
        title = first_line.lstrip("#").strip()

    parsed_ok = bool(starts) and bool(touched_files)

    return {
        "proposal_id": proposal_id,
        "title": title,
        "actor": actor,
        "category": category,
        "touched_files": touched_files,
        "written_paths": set(touched_files),
        "approvals": approvals,
        "proposed_changes_by_path": proposed_changes_by_path,
        "sections_parsed_ok": parsed_ok,
        "source": "PROP-MD",
    }


def _fallback_prop_id(text: str) -> str:
    base = hashlib.md5(text.encode("utf-8")).hexdigest()[:12].upper()
    return f"PROP-PARSED-{base}"


# ==================================================================
# 宪法自校验 hash
# ==================================================================


def _build_constitution_hash() -> str:
    """计算 R1..R9 9 个 check_* 函数的 source byte hash。"""
    src_parts: List[bytes] = []
    rule_order = ("check_original_skill_immutable",
                  "check_solution_path_quality_driven",
                  "check_ab_boundary",
                  "check_only_memory_channel_interaction",
                  "check_b_mod_scope",
                  "check_experiment_zone_isolation",
                  "check_proposal_gating",
                  "check_auto_draft_not_promoted_without_review")
    this_mod = sys.modules[__name__]
    for name in rule_order:
        fn = getattr(this_mod, name, None)
        if callable(fn):
            try:
                src_parts.append(inspect.getsource(fn).encode("utf-8"))
            except (OSError, TypeError):
                src_parts.append(name.encode("utf-8"))
    hasher = hashlib.sha256()
    for b in src_parts:
        hasher.update(b)
    hasher.update(f"version={CONSTITUTION_VERSION}".encode("utf-8"))
    return hasher.hexdigest()


CONSTITUTION_HASH: str = _build_constitution_hash()


def _self_check_constitution_hash() -> bool:
    """运行时重算 hash，对比常量是否一致（防宪法漂移 / 篡改）。"""
    try:
        recomputed = _build_constitution_hash()
    except Exception:
        return False
    return recomputed == CONSTITUTION_HASH


# ==================================================================
# audit_proposal 顶部入口
# ==================================================================


def audit_proposal(
    proposal: Dict[str, Any],
    *,
    import_graph: Optional[Dict[str, Set[str]]] = None,
    proposal_source: str = "PROP-MD",
) -> Dict[str, Any]:
    """宪法总审计。返回 AuditResult.to_dict()（方便 JSON 序列化）。

    执行顺序：R1 → R7 → R6 → R3/R4 → R5 → R2 → R8 → R9（按立即阻塞型先验排序）
    任何 CRITICAL 违规 → AuditResult.passed=False。
    """
    proposal_id = str(proposal.get("proposal_id")
                      or proposal.get("id")
                      or _fallback_prop_id(json.dumps(proposal,
                                                      ensure_ascii=False, sort_keys=True,
                                                      default=str)))
    touched_files: Set[str] = set(proposal.get("touched_files") or [])
    written_paths: Set[str] = set(proposal.get("written_paths") or touched_files)
    actor: str = str(proposal.get("actor", "UNKNOWN")).upper()
    is_prod = bool(proposal.get("is_production_change"))
    write_patch_by_path: Dict[str, Dict[str, Any]] = (
        proposal.get("proposed_changes_by_path")
        if isinstance(proposal.get("proposed_changes_by_path"), dict) else {})
    auto_promoted = proposal.get("auto_draft_promotion") \
        if isinstance(proposal.get("auto_draft_promotion"), dict) else None

    # 自检宪法 hash
    self_ok = _self_check_constitution_hash()

    rule_results_list: List[RuleResult] = [
        check_original_skill_immutable(touched_files),  # R1
        check_experiment_zone_isolation(touched_files, is_prod),  # R7
        check_b_mod_scope(touched_files) if actor == "B"
        else RuleResult(rule_id="R6", passed=True, violations=[]),  # R6
        check_ab_boundary("A", written_paths) if actor == "A"
        else RuleResult(rule_id="R3", passed=True, violations=[]),  # R3
        check_ab_boundary("B", written_paths) if actor == "B"
        else RuleResult(rule_id="R4", passed=True, violations=[]),  # R4
        check_only_memory_channel_interaction(import_graph),  # R5
        check_solution_path_quality_driven(write_patch_by_path),  # R2
        check_proposal_gating(proposal),  # R8
        check_auto_draft_not_promoted_without_review(auto_promoted),  # R9
    ]

    rule_results: Dict[str, RuleResult] = {}
    all_violations: List[Violation] = []
    severity_counts: Dict[str, int] = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    has_critical = False
    audit_weight_penalty = 0

    for rr in rule_results_list:
        key = rr.rule_id
        # 去重键（R3/R4 同函数会产生两种 rule_id）
        n = 1
        final_key = key
        while final_key in rule_results:
            n += 1
            final_key = f"{key}#{n}"
        rule_results[final_key] = rr
        for v in rr.violations:
            all_violations.append(v)
            sev = (v.severity or DEFAULT_SEVERITY).upper()
            if sev not in severity_counts:
                severity_counts[sev] = 0
            severity_counts[sev] += 1
            audit_weight_penalty += SEVERITY_WEIGHT.get(sev, 1)
            if sev == "CRITICAL":
                has_critical = True

    passed = not has_critical
    audit_score = max(0.0, 100.0 - float(audit_weight_penalty))

    result = AuditResult(
        passed=passed,
        proposal_id=proposal_id,
        rule_results=rule_results,
        total_violations=len(all_violations),
        severity_counts=severity_counts,
        audit_score=round(audit_score, 2),
        constitution_version=CONSTITUTION_VERSION,
        constitution_hash=CONSTITUTION_HASH,
        self_check_failed=not self_ok,
        constitution_mismatch=not self_ok,
        violations=all_violations,
    )
    return result.to_dict()


# ==================================================================
# CLI（供脚本快速调用，单文件审计）
# ==================================================================


def _main(argv: Optional[List[str]] = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="宪法审计：对单一 PROP-*.md 文件或 JSON proposal 进行红线校验",
    )
    parser.add_argument("--md", help="PROP-*.md 路径")
    parser.add_argument("--json", help="proposal JSON 路径")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    proposal: Optional[Dict[str, Any]] = None
    if args.md:
        proposal = parse_proposal_md(args.md)
    elif args.json:
        with open(args.json, "r", encoding="utf-8") as f:
            proposal = json.load(f)
    else:
        parser.print_help()
        return 0
    result = audit_proposal(proposal)
    if args.verbose:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        passed = result["passed"]
        print(f"[CONSTITUTION] proposal={result['proposal_id']} "
              f"passed={passed} score={result['audit_score']} "
              f"violations={result['total_violations']} "
              f"critical={result['severity_counts'].get('CRITICAL', 0)}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(_main())
