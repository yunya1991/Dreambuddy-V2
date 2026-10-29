"""P3 外部最优路径获取模块（ExternalHarvester）。

SPEC-33-反思层 v0.3 §5：从成熟开源项目采集最优实践路径，
经解析与三重验证后注入回放池，为 Dreaming 阶段提供外部先验。

流程：E1 采集 → E2 解析（复用 P0 分析器）→ E3 三重验证
（网络/内容/交叉）→ E4 注入回放池（provenance=external，
动态权重初始 0.5）。

原则：FAIL-OPEN —— 任何外部依赖失败均降级返回空结果，
不阻断主流程（对齐 REA 工程原则）。
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .replay_simulator import DiscoveryTree, DiscoveryNode, ReplayPool

EXTERNAL_INIT_WEIGHT = 0.5
VERIFY_PASS_THRESHOLD = 0.6
FETCH_TIMEOUT = 30


@dataclass
class HarvestSource:
    """E1：一个待采集的外部源。"""

    source_type: str  # github_repo / local_path
    location: str
    label: str = ""
    patterns: List[str] = field(default_factory=list)


@dataclass
class HarvestOutcome:
    """P3 全链路执行结果。"""

    ok: bool = False
    injected_trees: List[str] = field(default_factory=list)
    rejected: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class ExternalHarvester:
    """P3 外部最优路径获取器。"""

    def __init__(self, pool: ReplayPool, work_dir: str = "/tmp/rea_harvest"):
        self.pool = pool
        self.work_dir = work_dir
        os.makedirs(work_dir, exist_ok=True)

    def fetch_source(self, source: HarvestSource) -> Optional[str]:
        """E1：采集单个源到本地目录；失败返回 None（FAIL-OPEN）。"""
        try:
            if source.source_type == "local_path":
                return source.location if os.path.isdir(source.location) else None
            name = source.label or source.location.rstrip("/").split("/")[-1]
            dest = os.path.join(self.work_dir, name)
            if os.path.isdir(dest) and os.listdir(dest):
                return dest
            self._run(["git", "clone", "--depth", "1", source.location, dest])
            return dest if os.path.isdir(dest) else None
        except Exception as exc:  # noqa: BLE001
            self._log(f"E1 fetch failed for {source.location}: {exc}")
            return None

    def _run(self, cmd: List[str]) -> str:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=FETCH_TIMEOUT,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip()[-500:])
        return proc.stdout

    def _log(self, msg: str) -> None:
        print(f"[harvest] {msg}", flush=True)

    # ------------------------------------------------------------------
    # E2 解析：复用 P0 分析器，将外部项目解析为发现树
    # ------------------------------------------------------------------
    def parse_source(self, source: HarvestSource, local_dir: str) -> Optional[DiscoveryTree]:
        """E2：解析外部源为发现树；失败返回 None（FAIL-OPEN）。"""
        try:
            tree = DiscoveryTree.new_tree(
                task={
                    "target": source.location,
                    "goal": "extract_best_practice_path",
                    "patterns": source.patterns,
                },
                provenance="external",
                source_label=source.label or source.location,
            )
            findings = self._analyze_dir(local_dir, source.patterns)
            if not findings:
                self._log(f"E2 no findings for {source.location}")
                return None
            root = tree.root
            for idx, item in enumerate(findings):
                node = DiscoveryNode(
                    node_id=f"dn_ext_{idx}",
                    parent_id=root.node_id if root else None,
                    action={
                        "analyzer": item.get("analyzer", "unknown"),
                        "params": {"path": item.get("path", "")},
                    },
                    evidence_refs=item.get("evidence_refs", []),
                    poe_score=float(item.get("poe_score", 0.0)),
                    cost_calls=1,
                )
                tree.add_node(node)
            return tree
        except Exception as exc:  # noqa: BLE001
            self._log(f"E2 parse failed for {source.location}: {exc}")
            return None

    def _analyze_dir(self, local_dir: str, patterns: List[str]) -> List[Dict[str, Any]]:
        """扫描目录并产出发现项（复用 P0 分析器接口，不可用时降级）。"""
        findings: List[Dict[str, Any]] = []
        try:
            from core import architecture_pattern_detector
            detect = getattr(
                architecture_pattern_detector, "detect_architecture_patterns", None
            )
            if callable(detect):
                result = detect(local_dir) or {}
                findings = self._patterns_to_findings(result)
        except Exception as exc:  # noqa: BLE001
            self._log(f"E2 analyzer unavailable, fallback scan: {exc}")
        if not findings:
            findings = self._fallback_scan(local_dir, patterns)
        return findings

    def _patterns_to_findings(self, result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """将 P0 架构模式识别结果（patterns 列表）转换为发现项。"""
        findings: List[Dict[str, Any]] = []
        for pat in result.get("patterns", []):
            if isinstance(pat, dict):
                findings.append({
                    "analyzer": "architecture_pattern_detector",
                    "path": ", ".join(pat.get("matched_dirs", [])[:5]),
                    "evidence_refs": [{
                        "type": "pattern",
                        "pattern": pat.get("pattern", ""),
                    }],
                    "poe_score": 0.5,
                })
        return findings

    def _fallback_scan(self, local_dir: str, patterns: List[str]) -> List[Dict[str, Any]]:
        """降级扫描：按模式关键词收集源码文件作为基础发现项。"""
        results: List[Dict[str, Any]] = []
        for base, _dirs, files in os.walk(local_dir):
            if ".git" in base:
                continue
            for name in files:
                if not name.endswith((".py", ".ts", ".js")):
                    continue
                rel = os.path.relpath(os.path.join(base, name), local_dir)
                if patterns and not any(p in rel for p in patterns):
                    continue
                results.append({
                    "analyzer": "fallback_scan",
                    "path": rel,
                    "evidence_refs": [{"type": "file", "path": rel}],
                    "poe_score": 0.3,
                })
            if len(results) >= 50:
                break
        return results

    # ------------------------------------------------------------------
    # E3 三重验证：网络 / 内容 / 交叉
    # ------------------------------------------------------------------
    def verify_tree(self, tree: DiscoveryTree, source: HarvestSource) -> float:
        """E3：三重验证，返回通过率 [0,1]；任一环节失败按 FAIL-OPEN 计 0。"""
        checks = [
            self._verify_network(source),
            self._verify_content(tree),
            self._verify_cross(tree),
        ]
        passed = sum(1 for c in checks if c)
        return passed / len(checks)

    def _verify_network(self, source: HarvestSource) -> bool:
        """网络验证：源可达（本地源视为通过）。"""
        if source.source_type == "local_path":
            return os.path.isdir(source.location)
        try:
            self._run(["git", "ls-remote", source.location, "HEAD"])
            return True
        except Exception as exc:  # noqa: BLE001
            self._log(f"E3 network verify failed: {exc}")
            return False

    def _verify_content(self, tree: DiscoveryTree) -> bool:
        """内容验证：树非空、节点带证据引用、分数有效。"""
        if not tree.nodes or len(tree.nodes) < 2:
            return False
        with_evidence = sum(1 for n in tree.nodes if n.evidence_refs)
        return with_evidence >= max(1, len(tree.nodes) // 2)

    def _verify_cross(self, tree: DiscoveryTree) -> bool:
        """交叉验证：与回放池已有树的动作集合存在交集（可迁移性）。"""
        existing = self.pool.list_trees()
        if not existing:
            return True  # 池为空时无法交叉，放行
        new_actions = {n.action.get("analyzer", "") for n in tree.nodes}
        for other in existing:
            old_actions = {n.action.get("analyzer", "") for n in other.nodes}
            if new_actions & old_actions:
                return True
        return False

    # ------------------------------------------------------------------
    # E4 注入：验证通过后写入回放池
    # ------------------------------------------------------------------
    def inject_tree(self, tree: DiscoveryTree, pass_rate: float) -> Optional[str]:
        """E4：注入回放池；通过率不足阈值返回 None。"""
        if pass_rate < VERIFY_PASS_THRESHOLD:
            return None
        tree.weight = EXTERNAL_INIT_WEIGHT
        tree_id = self.pool.save(tree)
        return tree_id

    # ------------------------------------------------------------------
    # 全链路：E1 → E2 → E3 → E4
    # ------------------------------------------------------------------
    def harvest(self, sources: List[HarvestSource]) -> HarvestOutcome:
        """P3 全链路：采集→解析→验证→注入（FAIL-OPEN）。"""
        outcome = HarvestOutcome()
        for source in sources:
            try:
                local_dir = self.fetch_source(source)
                if not local_dir:
                    outcome.rejected.append({"source": source.location, "stage": "E1"})
                    continue
                tree = self.parse_source(source, local_dir)
                if tree is None:
                    outcome.rejected.append({"source": source.location, "stage": "E2"})
                    continue
                pass_rate = self.verify_tree(tree, source)
                tree_id = self.inject_tree(tree, pass_rate)
                if tree_id:
                    outcome.injected_trees.append(tree_id)
                else:
                    outcome.rejected.append({
                        "source": source.location,
                        "stage": "E3/E4",
                        "pass_rate": pass_rate,
                    })
            except Exception as exc:  # noqa: BLE001
                outcome.errors.append(f"{source.location}: {exc}")
        outcome.ok = not outcome.errors
        return outcome
