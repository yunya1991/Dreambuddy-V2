"""D2-A 架构复原 holdout：模块选择、快照与排除清单。

对应 SPEC-EMERGENCE-3D v0.4 §4.1：
  - 实验单元 = 模块（顶层目录）
  - 模块选择：≥5 源码/文档文件、≥3 个下游依赖方、排除无文档/无下游/生成代码
  - 扣留：移除该模块源码与文档、删除图中该模块节点及所有边
    （「保留线索」指其他文件源码文本中的引用仍在，不由图边泄漏）
  - ground truth：完整仓的 inbound import/call 边（模块级/公开接口级，不含内部私有调用）
  - 污染控制：逐模块独立数据快照 + exclusion_manifest.json + 内嵌 canary GUID

FAIL-OPEN：单个模块构建失败跳过并计数，不中断整体。
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
import uuid
from dataclasses import dataclass, field
from pathlib import Path

# 主终点只取 import 边作为 ground truth。
# 图构建器的 call 边是「函数名级」解析（重名取路径排序首个），实测 27563 条 call 边中
# 大量是重名函数造成的假依赖（如 276 个文件「调用」一个文档检查脚本），
# 属于 SPEC §4.1「口径公平性」要求排除的不可靠内部实现细节，不作主指标。
GRAPH_KINDS_PUBLIC = ("import",)
EXCLUDE_PATH_HINTS = ("generated", "vendor", "vendored", "third_party", "node_modules")


@dataclass
class HoldoutModule:
    module: str
    files: list[str] = field(default_factory=list)
    inbound_edges: list[dict] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    canary: str = ""

    @property
    def file_count(self) -> int:
        return len(self.files)

    @property
    def inbound_source_count(self) -> int:
        return len({e["src"] for e in self.inbound_edges})

    def to_dict(self) -> dict:
        return {
            "module": self.module,
            "file_count": self.file_count,
            "inbound_edge_count": len(self.inbound_edges),
            "inbound_source_count": self.inbound_source_count,
            "canary": self.canary,
            "categories": self.categories,
        }


def module_of(path: str) -> str:
    """模块标识：优先二级目录（如 `33-REA逆向解析工程/core`），根层文件归顶层目录。

    顶层目录本身是域容器（动辄上千文件），作为实验单元粒度过粗且泄漏审计必误报；
    二级目录更接近「模块」语义。隐藏目录（`.trae` 等）同样按此规则返回，但会在
    选择阶段被排除。
    """
    parts = path.split("/")
    if len(parts) >= 3:
        return "/".join(parts[:2])
    return parts[0]


def is_excluded(path: str) -> bool:
    low = path.lower()
    if low.startswith(".") or "/." in low:
        return True
    return any(h in low for h in EXCLUDE_PATH_HINTS)


def load_graph(graph_path: Path) -> dict:
    return json.loads(graph_path.read_text(encoding="utf-8"))


def _has_doc(files: list[str]) -> bool:
    return any(f.endswith(".md") for f in files)


COMMON_BASENAMES = {
    "__init__.py",
    "README.md",
    "main.py",
    "config.py",
    "utils.py",
    "types.py",
    "index.md",
    "test.py",
    "models.py",
    "constants.py",
}


def duplicate_ratio(files: list[str], all_files: list[str]) -> float:
    """模块内「同名文件在仓内其他模块也存在」的比例（重复副本风险）。

    仅统计非通用文件名的文件；重复副本意味着扣留后内容依然可得 → 污染。
    """
    name_owners: dict[str, set[str]] = {}
    for f in all_files:
        base = f.rsplit("/", 1)[-1]
        if base in COMMON_BASENAMES:
            continue
        name_owners.setdefault(base, set()).add(module_of(f))
    risky = 0
    total = 0
    for f in files:
        base = f.rsplit("/", 1)[-1]
        if base in COMMON_BASENAMES:
            continue
        total += 1
        if len(name_owners.get(base, set())) > 1:
            risky += 1
    return risky / total if total else 0.0


def select_modules(
    graph: dict,
    max_modules: int = 5,
    min_files: int = 5,
    min_inbound_sources: int = 3,
    max_duplicate_ratio: float = 0.1,
) -> tuple[list[HoldoutModule], list[dict]]:
    """按 §4.1 选择标准挑模块，返回 (全部合格候选, 被排除原因清单)。

    调用方自行决定实际运行前几个；审计不通过时顺延下一个候选。
    """
    nodes = {n["id"]: n for n in graph.get("nodes", [])}
    edges = graph.get("edges", [])
    all_files = [nid for nid, n in nodes.items() if n["type"] in ("python_file", "markdown_doc")]

    # 模块 → 文件
    files_by_module: dict[str, list[str]] = {}
    for node_id, node in nodes.items():
        if node["type"] not in ("python_file", "markdown_doc"):
            continue
        files_by_module.setdefault(module_of(node_id), []).append(node_id)

    # inbound 边：src 在模块外、dst 在模块内、公开边类型
    inbound: dict[str, list[dict]] = {}
    for e in edges:
        if e["kind"] not in GRAPH_KINDS_PUBLIC:
            continue
        src_mod, dst_mod = module_of(e["src"]), module_of(e["dst"])
        if src_mod == dst_mod or dst_mod not in files_by_module:
            continue
        if nodes.get(e["dst"], {}).get("type") not in ("python_file", "markdown_doc"):
            continue
        inbound.setdefault(dst_mod, []).append(
            {"src": e["src"], "dst": e["dst"], "kind": e["kind"]}
        )

    rejected: list[dict] = []
    candidates: list[HoldoutModule] = []
    for mod, files in sorted(files_by_module.items()):
        reasons = []
        if len(files) < min_files:
            reasons.append(f"file_count<{min_files}")
        if not _has_doc(files):
            reasons.append("no_doc")
        if any(is_excluded(f) for f in files):
            reasons.append("generated_or_vendored")
        inb = inbound.get(mod, [])
        if len({e["src"] for e in inb}) < min_inbound_sources:
            reasons.append(f"inbound_sources<{min_inbound_sources}")
        if mod.startswith("."):
            reasons.append("hidden_dir")
        dup = duplicate_ratio(files, all_files)
        if dup > max_duplicate_ratio:
            reasons.append(f"duplicate_ratio>{max_duplicate_ratio}")
        if reasons:
            rejected.append(
                {
                    "module": mod,
                    "reasons": reasons,
                    "file_count": len(files),
                    "duplicate_ratio": round(dup, 4),
                }
            )
            continue
        candidates.append(
            HoldoutModule(
                module=mod,
                files=sorted(files),
                inbound_edges=sorted(inb, key=lambda x: (x["src"], x["dst"])),
                categories=[suffix_mod(f) for f in files],
            )
        )

    # 覆盖度优先：按 inbound 源数量降序，再按文件数降序
    candidates.sort(key=lambda m: (-m.inbound_source_count, -m.file_count, m.module))
    return candidates, rejected


def suffix_mod(path: str) -> str:
    """粗粒度类别代理：取顶层目录名（与 module_of 一致），保留以支持未来细分。"""
    return module_of(path)


def make_canary(module: str, salt: str = "") -> str:
    """为 holdout 生成唯一 canary GUID（§4.0 第 11 条第 4 重检查）。"""
    digest = hashlib.sha256(f"{module}|{salt}".encode("utf-8")).hexdigest()[:24]
    return f"CANARY-{digest.upper()}"


def _contaminating_kept_files(
    root: Path, removed_files: list[str], kept_file_ids: list[str]
) -> set[str]:
    """识别与任一被扣留文件内容高度重叠的保留文件（去污染）。

    复用 leak_audit 的 shingle/containment 口径：若某保留文件包含某被扣留文件
    ≥ CONTAINMENT_THRESHOLD 比例的 5-gram，则该保留文件属于重复副本或嵌入源码的
    文档，留在语料中会触发泄漏审计第 2 重（content），故一并移除。

    仅对 python/markdown 节点做检查；其他节点类型无文本内容，不参与。
    """
    from .leak_audit import CONTAINMENT_THRESHOLD, containment, shingles

    removed_shingles: dict[str, set[str]] = {}
    for f in removed_files:
        p = root / f
        if p.is_file():
            try:
                removed_shingles[f] = shingles(p.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue

    contaminating: set[str] = set()
    for kid in kept_file_ids:
        p = root / kid
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        ks = shingles(text)
        if not ks:
            continue
        for inner in removed_shingles.values():
            if inner and containment(inner, ks) >= CONTAINMENT_THRESHOLD:
                contaminating.add(kid)
                break
    return contaminating


def build_snapshot(
    graph: dict,
    module: HoldoutModule,
    salt: str = "",
    root: Path | None = None,
) -> dict:
    """构建单模块 holdout 快照 + exclusion_manifest（§4.1 污染控制）。

    返回 dict(snapshot, exclusion_manifest)。snapshot 不含被扣留模块任何节点/边内容。
    指向被扣留模块的边也一律不保留——线索只存在于其他文件的源码文本中。

    若传入 ``root``，额外执行去污染：移除与任一被扣留文件内容高度重叠的保留文件
    （重复副本 / 嵌入源码的文档），避免泄漏审计第 2 重（content containment）误报。
    """
    canary = make_canary(module.module, salt)
    module.canary = canary
    holdout_files = set(module.files)

    kept_nodes = [
        n
        for n in graph.get("nodes", [])
        if n["id"] not in holdout_files and module_of(n["id"]) != module.module
    ]

    # 去污染：移除内容与被扣留文件高度重叠的保留文件
    decontaminated: set[str] = set()
    if root is not None:
        kept_file_ids = [
            n["id"] for n in kept_nodes if n["type"] in ("python_file", "markdown_doc")
        ]
        decontaminated = _contaminating_kept_files(root, module.files, kept_file_ids)
        kept_nodes = [n for n in kept_nodes if n["id"] not in decontaminated]

    kept_ids = {n["id"] for n in kept_nodes}
    kept_edges = [
        {"src": e["src"], "dst": e["dst"], "kind": e["kind"]}
        for e in graph.get("edges", [])
        if e["src"] in kept_ids and e["dst"] in kept_ids
    ]
    removed_edges = [
        e for e in graph.get("edges", []) if e["src"] in holdout_files or e["dst"] in holdout_files
    ]

    snapshot = {
        "module": module.module,
        "canary": canary,
        "kept_nodes": kept_nodes,
        # 只保留两端都在 kept 内的边。指向被扣留模块的边一律剔除——
        # 若以「线索」形式保留，等于把 ground truth 直接喂给输入端。
        # 真实线索来自他处源码文本中仍存在的 import 语句，由预测器自行解析。
        "kept_edges": kept_edges,
    }
    exclusion_manifest = {
        "module": module.module,
        "canary": canary,
        "removed_files": sorted(holdout_files),
        "removed_node_count": len(holdout_files),
        "removed_edges": removed_edges,
        "removed_edge_count": len(removed_edges),
        "decontaminated_kept_files": sorted(decontaminated),
        "decontaminated_count": len(decontaminated),
        "ground_truth_edges": module.inbound_edges,
        "ground_truth_edge_count": len(module.inbound_edges),
        "note": "ground truth 从完整仓库提取，不进入输入语料；"
        "decontaminated_kept_files 为内容与被扣留文件高度重叠而一并移除的保留文件",
    }
    return {"snapshot": snapshot, "exclusion_manifest": exclusion_manifest}


def normalize_text(text: str) -> str:
    return unicodedata.normalize("NFKC", text).lower()


def snapshot_digest(snapshot: dict) -> str:
    blob = json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def new_run_id() -> str:
    return f"D2A-{uuid.uuid4().hex[:12]}"
