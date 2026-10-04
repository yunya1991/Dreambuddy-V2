"""Dreaming Engine — 梦境式跨会话模式检测。

对标 Anthropic Dreaming：定时扫描认知记忆库，检测重复错误模式、
收敛工作流、过时/矛盾记忆，生成候选更新供人工审核。

工程约束：HC-1a（独立模块）/ FAIL-OPEN / 不自动写入
"""
from __future__ import annotations

import json
import math
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 认知记忆库路径
_REPO_ROOT = Path(__file__).resolve().parents[2]
_BAYESIAN_PATH = _REPO_ROOT / "4-MEMORY" / "2-交易记忆单元" / "bayesian_memories.json"

# 模式检测阈值
_SIMILARITY_THRESHOLD = 0.85  # TF-IDF cosine 相似度阈值
_DUPLICATE_MIN_COUNT = 3  # 重复模式最小出现次数
_STALE_CONFIDENCE_THRESHOLD = 0.3  # 过时记忆置信度阈值
_STALE_VERIFY_MIN = 5  # 过时记忆最小验证次数
_CONFLICT_CONFIDENCE_DIFF = 0.5  # 矛盾记忆置信度差异阈值


def _load_memories() -> list[dict[str, Any]]:
    """加载认知记忆库。FAIL-OPEN：失败返回空列表。"""
    try:
        if not _BAYESIAN_PATH.exists():
            return []
        data = json.loads(_BAYESIAN_PATH.read_text(encoding="utf-8"))
        return data.get("memories", [])
    except Exception:
        return []


# ─────────────────────────────── TF-IDF 相似度 ───────────────────────────────

def _tokenize(text: str) -> list[str]:
    """简单分词：按非字母数字分割，转小写，过滤短词。"""
    tokens = re.findall(r"[a-zA-Z\u4e00-\u9fff]+", text.lower())
    return [t for t in tokens if len(t) >= 2]


def _compute_tf(tokens: list[str]) -> dict[str, float]:
    """计算词频（normalized）。"""
    if not tokens:
        return {}
    counts: dict[str, int] = defaultdict(int)
    for t in tokens:
        counts[t] += 1
    total = len(tokens)
    return {t: c / total for t, c in counts.items()}


def _compute_idf(docs: list[list[str]]) -> dict[str, float]:
    """计算逆文档频率。"""
    n = len(docs)
    if n == 0:
        return {}
    df: dict[str, int] = defaultdict(int)
    for doc in docs:
        for t in set(doc):
            df[t] += 1
    return {t: math.log((n + 1) / (d + 1)) + 1 for t, d in df.items()}


def _cosine_similarity(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    """计算两个 TF-IDF 向量的余弦相似度。"""
    common = set(vec_a.keys()) & set(vec_b.keys())
    if not common:
        return 0.0
    dot = sum(vec_a[t] * vec_b[t] for t in common)
    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
    norm_b = math.sqrt(sum(v * v for v in vec_b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _build_tfidf_vectors(memories: list[dict[str, Any]]) -> list[dict[str, float]]:
    """为所有记忆构建 TF-IDF 向量。"""
    docs = [_tokenize(m.get("content", "")) for m in memories]
    idf = _compute_idf(docs)
    vectors: list[dict[str, float]] = []
    for doc in docs:
        tf = _compute_tf(doc)
        vec = {t: tf.get(t, 0) * idf.get(t, 0) for t in doc}
        vectors.append(vec)
    return vectors


# ─────────────────────────────── 模式检测 ───────────────────────────────

def _detect_duplicate_patterns(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """检测重复错误模式：content 相似度 >= 0.85 且出现 >= 3 次。"""
    if len(memories) < _DUPLICATE_MIN_COUNT:
        return []

    vectors = _build_tfidf_vectors(memories)
    n = len(memories)
    visited = [False] * n
    patterns: list[dict[str, Any]] = []

    for i in range(n):
        if visited[i]:
            continue
        cluster = [i]
        for j in range(i + 1, n):
            if visited[j]:
                continue
            sim = _cosine_similarity(vectors[i], vectors[j])
            if sim >= _SIMILARITY_THRESHOLD:
                cluster.append(j)
        if len(cluster) >= _DUPLICATE_MIN_COUNT:
            for idx in cluster:
                visited[idx] = True
            source_ids = [memories[idx].get("memory_id", f"unknown-{idx}") for idx in cluster]
            # 用第一个记忆的 content 作为模式代表
            pattern_content = memories[cluster[0]].get("content", "")[:200]
            avg_confidence = sum(memories[idx].get("confidence", 0) for idx in cluster) / len(cluster)
            patterns.append({
                "pattern_type": "duplicate_error",
                "pattern": pattern_content,
                "source_memory_ids": source_ids,
                "occurrence_count": len(cluster),
                "avg_confidence": round(avg_confidence, 4),
                "suggestion": f"合并 {len(cluster)} 条相似记忆，提炼统一解决方案",
                "confidence": round(avg_confidence, 4),
            })
    return patterns


def _detect_converging_workflows(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """检测收敛工作流：多个记忆的 tags 指向同一 skill/类别。"""
    # 按 tags 分组（去掉通用标签）
    tag_groups: dict[str, list[str]] = defaultdict(list)
    generic_tags = {"交易", "认知", "skill", "SKILL", "记录", "经验", "lesson", "general"}

    for m in memories:
        tags = m.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        for tag in tags:
            if tag and tag not in generic_tags and len(tag) > 2:
                tag_groups[tag].append(m.get("memory_id", "unknown"))

    patterns: list[dict[str, Any]] = []
    for tag, ids in tag_groups.items():
        if len(ids) >= _DUPLICATE_MIN_COUNT:
            patterns.append({
                "pattern_type": "converging_workflow",
                "pattern": f"标签 '{tag}' 被 {len(ids)} 条记忆引用",
                "source_memory_ids": ids,
                "occurrence_count": len(ids),
                "suggestion": f"考虑将 '{tag}' 相关经验提炼为 procedural 记忆或 skill",
                "confidence": 0.5,
            })
    return patterns


def _detect_stale_contradictory(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """检测过时/矛盾记忆：confidence < 0.3 且 verify_count >= 5。"""
    patterns: list[dict[str, Any]] = []
    for m in memories:
        conf = m.get("confidence", 1.0)
        verify = m.get("verify_count", 0)
        if conf < _STALE_CONFIDENCE_THRESHOLD and verify >= _STALE_VERIFY_MIN:
            mid = m.get("memory_id", "unknown")
            patterns.append({
                "pattern_type": "stale_or_contradictory",
                "pattern": m.get("content", "")[:200],
                "source_memory_ids": [mid],
                "confidence": conf,
                "verify_count": verify,
                "suggestion": f"该记忆置信度({conf})低且验证次数({verify})多，建议审查或归档",
            })

    # 矛盾检测：相同 category 下 confidence 差异 > 0.5
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for m in memories:
        cat = m.get("category", "unknown")
        by_category[cat].append(m)

    for cat, mems in by_category.items():
        if len(mems) < 2:
            continue
        # 按 confidence 排序，找差异最大的对
        sorted_mems = sorted(mems, key=lambda x: x.get("confidence", 0))
        lowest = sorted_mems[0]
        highest = sorted_mems[-1]
        diff = highest.get("confidence", 0) - lowest.get("confidence", 0)
        if diff > _CONFLICT_CONFIDENCE_DIFF:
            patterns.append({
                "pattern_type": "conflict",
                "pattern": f"类别 '{cat}' 下记忆置信度差异 {round(diff, 4)}",
                "source_memory_ids": [
                    lowest.get("memory_id", "unknown"),
                    highest.get("memory_id", "unknown"),
                ],
                "confidence_diff": round(diff, 4),
                "suggestion": "同一类别下存在高置信度和低置信度记忆，建议审查矛盾",
            })
    return patterns


# ─────────────────────────────── 主入口 ───────────────────────────────

def run_dreaming_cycle() -> dict[str, Any]:
    """执行一次梦境扫描，返回候选更新列表。不自动写入，需人工审核。

    Returns:
        {
            "status": "ok" | "error",
            "timestamp": ISO 时间戳,
            "total_memories_scanned": int,
            "candidates": [候选更新列表],
            "summary": {pattern_type: count}
        }
    """
    try:
        memories = _load_memories()
        timestamp = datetime.now(timezone.utc).isoformat()

        candidates: list[dict[str, Any]] = []
        candidates.extend(_detect_duplicate_patterns(memories))
        candidates.extend(_detect_converging_workflows(memories))
        candidates.extend(_detect_stale_contradictory(memories))

        # 按 pattern_type 统计
        summary: dict[str, int] = defaultdict(int)
        for c in candidates:
            summary[c["pattern_type"]] += 1

        return {
            "status": "ok",
            "timestamp": timestamp,
            "total_memories_scanned": len(memories),
            "candidates": candidates,
            "summary": dict(summary),
            "note": "候选更新不自动写入，需人工审核后通过 cognitive record 采纳",
        }
    except Exception as e:
        return {
            "status": "error",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
            "total_memories_scanned": 0,
            "candidates": [],
            "summary": {},
        }


# ───────────────────────── 规则化自动合并 ─────────────────────────

# 自动合并阈值
_AUTO_MERGE_MIN_OCCURRENCE = 5   # 重复模式出现 >= 5 次才自动合并
_AUTO_MERGE_MIN_CONVERGING = 20  # 收敛工作流 >= 20 条才自动提炼
_AUTO_CONFLICT_DOWNGRADE = True  # 矛盾记忆自动降级低置信度方
# 泛化标签不触发收敛提取（频率高但信息密度低）
_GENERIC_TAGS = {
    "rag", "检索", "硬约束", "FAIL-OPEN", "doc-sync", "1-ARCHITECTURE",
    "1-TRADING", "6-PRODUCT-BUSINESS", "git-hook", "feature",
    "solution_path", "dreamos", "认知闭环", "认知系统",
}


def auto_merge_duplicates(dry_run: bool = False) -> dict[str, Any]:
    """规则化自动合并重复记忆。

    合并策略（纯规则，不需要 LLM）：
    1. 重复模式 occurrence >= 5 → 保留 confidence 最高的记忆，其余归档
    2. 矛盾记忆 confidence 差 > 0.5 → 低置信度方降级为 D
    3. 收敛工作流 >= 10 条 → 合并 tags，创建一条 procedural 类型记忆

    所有操作：备份优先 → 原子写入 → 审计日志。
    FAIL-OPEN：任何异常不中断。

    Args:
        dry_run: 仅模拟，不修改数据

    Returns:
        {"status": "ok", "merged": int, "downgraded": int, "created": int, ...}
    """
    from pathlib import Path
    import shutil

    timestamp = datetime.now(timezone.utc).isoformat()
    result: dict[str, Any] = {
        "status": "ok",
        "timestamp": timestamp,
        "dry_run": dry_run,
        "merged": 0,       # 合并删除的记忆数
        "downgraded": 0,   # 矛盾降级的记忆数
        "created": 0,      # 新创建的提炼记忆数
        "details": [],
    }

    try:
        memories = _load_memories()
        if not memories:
            result["status"] = "error"
            result["error"] = "记忆库为空或加载失败"
            return result

        changed = False
        ids_to_archive: set[str] = set()    # 要归档（删除）的记忆 ID
        ids_to_downgrade: set[str] = set()  # 要降级为 D 的记忆 ID
        new_memories: list[dict[str, Any]] = []  # 新创建的记忆

        # ── 1. 重复模式自动合并 ──
        dup_patterns = _detect_duplicate_patterns(memories)
        for p in dup_patterns:
            if p.get("occurrence_count", 0) >= _AUTO_MERGE_MIN_OCCURRENCE:
                source_ids = p.get("source_memory_ids", [])
                # 找到这些记忆中 confidence 最高的
                cluster_mems = [m for m in memories if m.get("memory_id") in source_ids]
                if len(cluster_mems) < 2:
                    continue
                best = max(cluster_mems, key=lambda m: m.get("confidence", 0))
                # 其余标记为归档
                to_archive = {m.get("memory_id") for m in cluster_mems if m.get("memory_id") != best.get("memory_id")}
                ids_to_archive.update(to_archive)
                result["merged"] += len(to_archive)
                result["details"].append({
                    "action": "merge_duplicates",
                    "kept": best.get("memory_id"),
                    "archived": list(to_archive),
                    "pattern": p.get("pattern", "")[:80],
                    "occurrence": p.get("occurrence_count"),
                })
                changed = True

        # ── 2. 矛盾记忆自动降级 ──
        # 重新加载（因为上面的合并可能已标记部分归档）
        active_mems = [m for m in memories if m.get("memory_id") not in ids_to_archive]
        by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for m in active_mems:
            cat = m.get("category", "unknown")
            by_category[cat].append(m)

        for cat, mems in by_category.items():
            if len(mems) < 2:
                continue
            sorted_mems = sorted(mems, key=lambda x: x.get("confidence", 0))
            lowest = sorted_mems[0]
            highest = sorted_mems[-1]
            diff = highest.get("confidence", 0) - lowest.get("confidence", 0)
            if diff > _CONFLICT_CONFIDENCE_DIFF:
                # 低置信度方降级为 D（如果还不是 D）
                if lowest.get("quality_level") != "D":
                    ids_to_downgrade.add(lowest.get("memory_id"))
                    result["downgraded"] += 1
                    result["details"].append({
                        "action": "conflict_downgrade",
                        "downgraded": lowest.get("memory_id"),
                        "kept_higher": highest.get("memory_id"),
                        "category": cat,
                        "confidence_diff": round(diff, 4),
                    })
                    changed = True

        # ── 3. 收敛工作流自动提炼 ──
        conv_patterns = _detect_converging_workflows(active_mems)
        for p in conv_patterns:
            # 提取 tag 名，检查是否为泛化标签
            pattern_str = p.get("pattern", "")
            tag_name = pattern_str.split("'")[1] if "'" in pattern_str else ""
            if tag_name in _GENERIC_TAGS:
                continue
            if p.get("occurrence_count", 0) >= _AUTO_MERGE_MIN_CONVERGING:
                source_ids = p.get("source_memory_ids", [])
                cluster_mems = [m for m in active_mems if m.get("memory_id") in source_ids]
                if not cluster_mems:
                    continue
                # 合并所有 tags
                all_tags: list[str] = []
                for m in cluster_mems:
                    tags = m.get("tags", [])
                    if isinstance(tags, str):
                        tags = [t.strip() for t in tags.split(",")]
                    all_tags.extend(tags)
                all_tags = list(dict.fromkeys(all_tags))[:20]  # 去重保序，最多 20 个

                # 平均置信度
                avg_conf = sum(m.get("confidence", 0) for m in cluster_mems) / len(cluster_mems)
                # 创建新记忆
                new_mem = {
                    "memory_id": f"VM-AUTO-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{len(new_memories):04d}",
                    "content": f"[自动提炼] {p.get('pattern', '')[:150]}",
                    "category": "auto_merged",
                    "confidence": round(avg_conf, 4),
                    "quality_level": "C",
                    "verify_count": 0,
                    "conflict_count": 0,
                    "beta_alpha": 1.0,
                    "beta_beta": 1.0,
                    "created_at": timestamp,
                    "last_updated": timestamp,
                    "source": "dreaming_auto_merge",
                    "tags": all_tags,
                }
                new_memories.append(new_mem)
                result["created"] += 1
                result["details"].append({
                    "action": "converging_extract",
                    "new_memory_id": new_mem["memory_id"],
                    "source_count": len(cluster_mems),
                    "tag": p.get("pattern", "")[:60],
                })
                changed = True

        # ── 写入 ──
        if changed and not dry_run:
            # 备份
            backup = _BAYESIAN_PATH.with_suffix(".json.bak")
            shutil.copy2(_BAYESIAN_PATH, backup)

            # 加载完整数据
            with open(_BAYESIAN_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)

            # 应用变更
            old_mems = data.get("memories", [])
            # 归档被合并的记忆
            archived_mems = [m for m in old_mems if m.get("memory_id") in ids_to_archive]
            _archive_merged_memories(archived_mems)
            # 移除归档的记忆
            new_mems = [m for m in old_mems if m.get("memory_id") not in ids_to_archive]
            # 降级矛盾记忆
            for m in new_mems:
                if m.get("memory_id") in ids_to_downgrade:
                    m["quality_level"] = "D"
                    m["last_updated"] = timestamp
            # 添加新提炼的记忆
            new_mems.extend(new_memories)
            # 原子写入
            data["memories"] = new_mems
            data["last_updated"] = timestamp
            tmp = _BAYESIAN_PATH.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            tmp.replace(_BAYESIAN_PATH)

            result["backup"] = str(backup)
            result["final_memories"] = len(new_mems)

            # 审计日志
            _log_merge_audit(result)
        else:
            result["final_memories"] = len(memories) - len(ids_to_archive) + len(new_memories)

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    return result


def _archive_merged_memories(memories: list[dict[str, Any]]) -> None:
    """将被合并的记忆归档到 JSONL。FAIL-OPEN。"""
    try:
        archive_dir = _BAYESIAN_PATH.parent.parent / "data" / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_file = archive_dir / "merged_memories.jsonl"
        with open(archive_file, "a", encoding="utf-8") as f:
            for m in memories:
                entry = {**m, "archived_at": datetime.now(timezone.utc).isoformat(), "archive_reason": "dreaming_auto_merge"}
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # FAIL-OPEN


def _log_merge_audit(report: dict[str, Any]) -> None:
    """记录合并审计日志。FAIL-OPEN。"""
    try:
        audit_dir = _BAYESIAN_PATH.parent.parent / "9-工具与接口" / "data"
        audit_dir.mkdir(parents=True, exist_ok=True)
        audit_file = audit_dir / "dreaming_merge_audit.jsonl"
        with open(audit_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(report, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ─────────────────────────────── CLI ───────────────────────────────

def _run_scheduled(interval_hours: float) -> None:
    """定时执行梦境扫描。FAIL-OPEN：异常不退出循环。

    Args:
        interval_hours: 扫描间隔（小时），默认 24 小时（每日一次）
    """
    import time
    interval_seconds = interval_hours * 3600
    print(f"[dreaming] scheduled mode: every {interval_hours}h ({interval_seconds:.0f}s)")
    while True:
        try:
            result = run_dreaming_cycle()
            status = result.get("status", "error")
            count = len(result.get("candidates", []))
            print(f"[dreaming] {result.get('timestamp')} status={status} candidates={count}")
        except Exception as e:
            print(f"[dreaming] error: {e}")
        try:
            time.sleep(interval_seconds)
        except KeyboardInterrupt:
            print("[dreaming] stopped by user")
            break


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。

    用法:
        python dreaming_engine.py              # 执行一次扫描
        python dreaming_engine.py --schedule 24  # 定时模式，每 24 小时一次
    """
    import argparse
    parser = argparse.ArgumentParser(prog="dreaming_engine", description="Dreaming Engine")
    parser.add_argument("--schedule", type=float, default=None,
                        help="定时模式：扫描间隔（小时），默认 None（执行一次）")
    parser.add_argument("--auto-merge", action="store_true",
                        help="执行规则化自动合并（重复≥5归档+矛盾降级+收敛≥10提炼）")
    parser.add_argument("--dry-run", action="store_true",
                        help="仅模拟，不修改数据")
    args = parser.parse_args(argv)

    if args.schedule is not None:
        _run_scheduled(args.schedule)
        return 0

    if args.auto_merge:
        result = auto_merge_duplicates(dry_run=args.dry_run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("status") == "ok" else 1

    result = run_dreaming_cycle()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
