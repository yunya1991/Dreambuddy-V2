"""
X-A 真实跨域 A/B 验证框架。

与 evaluate.py（代理增益）的区别：
- evaluate.py: 用各实验主指标（E3 coupling/D2-A F1/D3-B step reduction）归一化做 gain
- real_ab.py: 用真实 session trajectory 数据，按 task_type 重叠度匹配跨域 session 对，
  对每对计算三维涌现指标，直接跑 2×2×2 因子设计

核心流程：
  1. 从 session_memory 目录扫描 JSONL → 提取每条的 task_type / task_domain / 指标字典
  2. 域 A × 域 B 按 task_type Jaccard overlap 匹配 session 对
  3. 对每对 session 算 (d1_gain, d2_gain, d3_gain) 三维涌现指标
  4. 聚合所有匹配对 → build_arms / estimate_g123 / omega_o_information
  5. 输出 verdict（candidate / falsified / inconclusive）

FAIL-OPEN：
  - session 数据目录不存在或为空 → status=deferred，附带代理增益结果作 proxy
  - 单条 session 解析失败跳过并计入 skipped
  - 匹配对不足 min_pairs（默认 10）→ status=deferred
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG_ROOT = HERE.parent.parent
for p in (str(HERE), str(PKG_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

# 复用 evaluate.py 的统计函数
from evaluate import (  # noqa: E402
    bootstrap_g123,
    build_arms,
    estimate_g123,
    estimate_main_effects,
    estimate_two_way,
    omega_o_information,
)


@dataclass
class SessionRecord:
    """从 JSONL 解析出的 session 记录（FAIL-OPEN：字段缺失用默认值）。"""

    session_id: str
    task_type: str  # 如 "trading", "engineering", "intent"
    task_domain: str  # 域标签："A" / "B" / 其他
    metrics: dict  # 三维涌现指标 dict，key ∈ {"d1", "d2", "d3"}
    source_file: str


# ---------------------------------------------------------------------------
# 1. Session 扫描与解析
# ---------------------------------------------------------------------------


def _extract_task_type(record: dict) -> str:
    """从 session record 中提取 task_type，支持多种字段名。"""
    for key in ("task_type", "taskType", "primary_task", "primaryTask", "intent_domain"):
        val = record.get(key)
        if val and isinstance(val, str):
            return val.lower()
    # 从 tags 中推断
    tags = record.get("tags") or record.get("tag_list") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]
    for tag in tags:
        if isinstance(tag, str) and tag.lower() in (
            "trading",
            "engineering",
            "intent",
            "data",
            "eval",
        ):
            return tag.lower()
    return "unknown"


def _extract_task_domain(record: dict) -> str:
    """提取域标签 A/B，用于真实跨域匹配。"""
    for key in ("task_domain", "domain", "session_domain"):
        val = record.get(key)
        if val and isinstance(val, str):
            return val.upper()
    # 没有域标签 → 用 task_type 映射（trading→A, engineering→B, intent→C）
    return _extract_task_type(record)


def _extract_metrics(record: dict) -> dict:
    """提取三维涌现指标。每个指标 ∈ [0,1]。FAIL-OPEN 缺失时返回默认 0。"""
    metrics = {}
    # D1: 交易耦合改进率 proxy
    metrics["d1"] = float(
        record.get("d1_gain")
        or record.get("coupling_improvement")
        or record.get("e3_improvement")
        or 0.0
    )
    # D2: 工程架构 F1 proxy
    metrics["d2"] = float(
        record.get("d2_gain") or record.get("engineering_f1") or record.get("arch_f1") or 0.0
    )
    # D3: 意图路由 step reduction proxy
    metrics["d3"] = float(
        record.get("d3_gain")
        or record.get("intent_step_reduction")
        or record.get("route_step_reduction")
        or 0.0
    )
    # 归一化到 [0,1]
    for k in ("d1", "d2", "d3"):
        metrics[k] = max(0.0, min(1.0, metrics[k]))
    return metrics


def scan_sessions(session_dirs: list[Path]) -> tuple[list[SessionRecord], dict]:
    """扫描目录下所有 JSONL 文件 → SessionRecord 列表 + 统计 dict。

    支持两种数据源：
      1. 认知 session memory（.trae/memory/projects/.../YYYYMMDD/session_memory_*.jsonl）
      2. 实验输出（48-涌现架构/events/**/*.jsonl）

    每条 JSONL 行期望包含 task_type + task_domain + metrics 字段。
    """
    records: list[SessionRecord] = []
    stats = {
        "files_scanned": 0,
        "records_parsed": 0,
        "records_skipped": 0,
        "by_task_type": defaultdict(int),
        "by_domain": defaultdict(int),
    }

    for dir_path in session_dirs:
        if not dir_path or not dir_path.exists():
            continue
        for jl in dir_path.rglob("*.jsonl"):
            stats["files_scanned"] += 1
            try:
                for line in jl.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        raw = json.loads(line)
                    except json.JSONDecodeError:
                        stats["records_skipped"] += 1
                        continue
                    if not isinstance(raw, dict):
                        stats["records_skipped"] += 1
                        continue
                    sid = raw.get("session_id") or raw.get("sessionId") or raw.get("id") or jl.stem
                    task_type = _extract_task_type(raw)
                    domain = _extract_task_domain(raw)
                    metrics = _extract_metrics(raw)
                    rec = SessionRecord(
                        session_id=str(sid),
                        task_type=task_type,
                        task_domain=domain,
                        metrics=metrics,
                        source_file=str(jl),
                    )
                    records.append(rec)
                    stats["records_parsed"] += 1
                    stats["by_task_type"][task_type] += 1
                    stats["by_domain"][domain] += 1
            except OSError:
                continue

    stats["by_task_type"] = dict(stats["by_task_type"])
    stats["by_domain"] = dict(stats["by_domain"])
    return records, stats


# ---------------------------------------------------------------------------
# 2. 跨域 Session 匹配
# ---------------------------------------------------------------------------


def jaccard_overlap(set_a: set, set_b: set) -> float:
    """Jaccard 相似度 = |A∩B| / |A∪B|，空集返回 0。"""
    if not set_a and not set_b:
        return 0.0
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / len(union)


def match_cross_domain_pairs(
    records: list[SessionRecord],
    domain_a: str,
    domain_b: str,
    min_task_overlap: float = 0.0,
    max_pairs: int = 500,
) -> list[tuple[SessionRecord, SessionRecord, float]]:
    """在域 A 和域 B 之间匹配 session 对，按 task_type 重叠度排序。

    返回 [(rec_a, rec_b, overlap_score), ...]，按 overlap 降序，最多 max_pairs 对。
    """
    a_recs = [r for r in records if r.task_domain == domain_a.upper()]
    b_recs = [r for r in records if r.task_domain == domain_b.upper()]
    if not a_recs or not b_recs:
        return []

    pairs: list[tuple[SessionRecord, SessionRecord, float]] = []
    for ra in a_recs:
        for rb in b_recs:
            # task_type 重叠：同一 task_type 或共享 tags
            overlap = 0.0
            if ra.task_type == rb.task_type:
                overlap = 1.0
            elif ra.task_type != "unknown" and rb.task_type != "unknown":
                overlap = 0.5  # 不同 task_type 但都已知 → 部分重叠
            if overlap >= min_task_overlap:
                pairs.append((ra, rb, overlap))

    # 按 overlap 降序取 top-N
    pairs.sort(key=lambda t: t[2], reverse=True)
    if len(pairs) > max_pairs:
        pairs = pairs[:max_pairs]
    return pairs


# ---------------------------------------------------------------------------
# 3. 真实 G_123 计算
# ---------------------------------------------------------------------------


def compute_real_gains(
    pairs: list[tuple[SessionRecord, SessionRecord, float]],
    min_overlap_weight: float = 0.0,
) -> tuple[dict[str, float], dict]:
    """从跨域 session 对计算真实三维增益（加权均值，overlap 作权重）。

    返回 (arms_dict, meta_dict)：
      - arms_dict: 8 臂增益表（与 evaluate.py 相同 key）
      - meta_dict: 统计信息（对数、权重分布、每臂样本数）
    """
    if not pairs:
        return {}, {"n_pairs": 0, "status": "no_pairs"}

    # 用每对 session 的 (metrics_a + metrics_b) / 2 做三维增益估计
    # overlap 越高权重越大
    d1_vals, d2_vals, d3_vals = [], [], []
    weights: list[float] = []

    for ra, rb, overlap in pairs:
        w = max(overlap, min_overlap_weight)
        weights.append(w)
        d1_vals.append((ra.metrics["d1"] + rb.metrics["d1"]) / 2 * w)
        d2_vals.append((ra.metrics["d2"] + rb.metrics["d2"]) / 2 * w)
        d3_vals.append((ra.metrics["d3"] + rb.metrics["d3"]) / 2 * w)

    total_w = sum(weights) or 1.0
    d1 = sum(d1_vals) / total_w
    d2 = sum(d2_vals) / total_w
    d3 = sum(d3_vals) / total_w

    arms = build_arms(d1, d2, d3)
    meta = {
        "n_pairs": len(pairs),
        "mean_overlap": sum(p[2] for p in pairs) / len(pairs),
        "weight_sum": total_w,
        "d1_real": d1,
        "d2_real": d2,
        "d3_real": d3,
    }
    return arms, meta


def evaluate_real_ab(
    session_dirs: list[Path] | None = None,
    domain_a: str = "A",
    domain_b: str = "B",
    min_pairs: int = 10,
    session_memory_root: str | None = None,
) -> dict:
    """真实跨域 A/B 评估主入口。

    返回 dict 含 status:
      - "ok": 有足够匹配对，真实 G_123_real / Ω_real 可用
      - "deferred": session 数据不足或无匹配对，附带 proxy 结果
      - "error": 数据源不可用
    """
    if session_dirs is None:
        session_dirs = _default_session_dirs(session_memory_root)

    records, scan_stats = scan_sessions(session_dirs)

    if not records:
        return _deferred_result("no_session_data", scan_stats, session_dirs)

    pairs = match_cross_domain_pairs(records, domain_a, domain_b)

    if len(pairs) < min_pairs:
        return _deferred_result(
            "insufficient_pairs",
            scan_stats,
            session_dirs,
            meta={
                "n_pairs": len(pairs),
                "min_pairs_required": min_pairs,
                "domain_a": domain_a,
                "domain_b": domain_b,
            },
        )

    arms, meta = compute_real_gains(pairs)
    main = estimate_main_effects(arms)
    two_way = estimate_two_way(arms)
    g123 = estimate_g123(arms)
    g123_mean, ci_lo, ci_hi = bootstrap_g123(arms)
    omega = omega_o_information(arms)

    g_ij_positive = any(v > 0 for v in two_way.values())
    if ci_lo > 0 and omega > 0 and g_ij_positive:
        verdict = "candidate"
        reason = f"G_123_real 95% CI [{ci_lo:.4f}, {ci_hi:.4f}] > 0, Ω_real={omega:.4f} > 0"
    elif ci_hi <= 0:
        verdict = "falsified"
        reason = f"G_123_real CI 上界 {ci_hi:.4f} <= 0，无三阶协同"
    else:
        verdict = "inconclusive"
        reason = f"G_123_real CI [{ci_lo:.4f}, {ci_hi:.4f}] 跨 0 或 Ω_real={omega:.4f} <= 0"

    return {
        "status": "ok",
        "verdict": verdict,
        "reason": reason,
        "domain_a": domain_a,
        "domain_b": domain_b,
        "scan_stats": scan_stats,
        "match_meta": meta,
        "dimension_gains_real": {
            "D1": meta["d1_real"],
            "D2": meta["d2_real"],
            "D3": meta["d3_real"],
        },
        "arms_real": arms,
        "main_effects_real": main,
        "two_way_interactions_real": two_way,
        "g123_real": g123,
        "g123_bootstrap_real": {"mean": g123_mean, "ci_low": ci_lo, "ci_high": ci_hi},
        "omega_real": omega,
    }


# ---------------------------------------------------------------------------
# 4. 辅助：默认 session 目录 + deferred 构建
# ---------------------------------------------------------------------------


def _default_session_dirs(session_memory_root: str | None = None) -> list[Path]:
    """默认 session 数据搜索目录列表。"""
    dirs: list[Path] = []
    if session_memory_root:
        dirs.append(Path(session_memory_root))
    # 认知 session memory（trae 会话）
    trae_memory = Path.home() / ".trae-cn" / "memory" / "projects"
    if trae_memory.exists():
        dirs.append(trae_memory)
    # 实验 shadow 数据
    shadow = PKG_ROOT / "events"
    if shadow.exists():
        dirs.append(shadow)
    return dirs


def _deferred_result(
    reason: str,
    scan_stats: dict,
    session_dirs: list[Path],
    meta: dict | None = None,
) -> dict:
    """FAIL-OPEN deferred 结果：附带代理增益作 proxy。"""
    try:
        from evaluate import evaluate as _proxy_eval  # noqa: E402

        proxy = _proxy_eval()
    except Exception:
        proxy = None

    out = {
        "status": "deferred",
        "deferred_reason": reason,
        "verdict": "deferred",
        "reason": f"真实 A/B 数据不可用：{reason}",
        "scan_stats": scan_stats,
        "session_dirs_searched": [str(d) for d in session_dirs],
        "proxy_result": proxy,
    }
    if meta:
        out["match_meta"] = meta
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="X-A 真实跨域 A/B 验证框架")
    p.add_argument("--domain-a", default="A", help="域 A 标签")
    p.add_argument("--domain-b", default="B", help="域 B 标签")
    p.add_argument("--min-pairs", type=int, default=10, help="最少匹配对阈值")
    p.add_argument("--session-root", default=None, help="session 数据根目录（覆盖默认）")
    args = p.parse_args()

    result = evaluate_real_ab(
        domain_a=args.domain_a,
        domain_b=args.domain_b,
        min_pairs=args.min_pairs,
        session_memory_root=args.session_root,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
