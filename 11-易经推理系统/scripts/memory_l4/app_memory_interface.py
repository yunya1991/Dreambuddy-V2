"""L4 交易记忆 — 统一接口封装

应用记忆系统标准接口实现，符合总记忆系统定义的7个标准接口。

采用适配器模式：不修改现有 L4 代码，在其上封装统一接口。

标准接口：
- search(query, filters) -> 检索记忆
- add(memory_entry) -> 添加记忆
- update(id, updates) -> 更新记忆
- get(id) -> 获取单条
- stats() -> 统计信息
- distill_candidates() -> 蒸馏候选（可上升为总记忆的候选
- healthcheck() -> 健康检查

记忆类型：
- case: 交易案例（CBR 案例库
- review: 复盘记录
- distill: 蒸馏经验
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.memory_l4.paths import (
    memory_l4_cases_dir,
    memory_l4_reviews_dir,
    memory_l4_distills_dir,
    memory_l4_stats_dir,
)
from scripts.memory_l4.l4_status_api import get_l4_status, get_l4_status_summary


# ─────────────────────────────────────────────
# 常量
# ─────────────────────────────────────────────

APP_MEMORY_ID = "AM-TRD-001"
APP_MEMORY_NAME = "交易L4记忆"
APP_MEMORY_VERSION = "1.0.0"


# ─────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────

def _list_json(dir_path: Path) -> List[Path]:
    if not dir_path.exists():
        return []
    return sorted([p for p in dir_path.glob("*.json") if p.is_file()])


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _memory_id(prefix: str, raw_id: str) -> str:
    """生成标准化记忆ID: AM-TRD-{TYPE}-{RAW_ID}"""
    return f"{APP_MEMORY_ID}-{prefix}-{raw_id}"


# ─────────────────────────────────────────────
# 统一接口实现
# ─────────────────────────────────────────────

def search(
    query: str = "",
    filters: Optional[Dict[str, Any]] = None,
    memory_type: str = "all",
    top_k: int = 10,
) -> List[Dict[str, Any]]:
    """检索记忆

    Args:
        query: 查询关键词
        filters: 过滤条件（字段语义由各应用记忆系统自行定义）
            交易记忆支持: inst_id, regime, decision, is_profit, system_source, direction
            注意: 这些是交易记忆的业务字段，不是统一规范要求
        memory_type: 记忆类型 "all" / "case" / "review" / "distill"
        top_k: 返回结果数量

    Returns:
        记忆条目列表，每条包含 id, type, score, data 等字段
    """
    filters = filters or {}
    results: List[Dict[str, Any]] = []

    # ── Case 检索 ──
    if memory_type in ("all", "case"):
        case_results = _search_cases(query, filters, top_k)
        results.extend(case_results)

    # ── Review 检索 ──
    if memory_type in ("all", "review"):
        review_results = _search_reviews(query, filters, top_k)
        results.extend(review_results)

    # ── Distill 检索 ──
    if memory_type in ("all", "distill"):
        distill_results = _search_distills(query, filters, top_k)
        results.extend(distill_results)

    # 按分数排序；score相同时做类型轮转确保多样性
    results.sort(key=lambda x: x.get("score", 0), reverse=True)

    # 当 memory_type="all" 且有多类型时，同score组内按类型轮转
    if memory_type == "all" and len(set(r["type"] for r in results)) > 1:
        from itertools import groupby
        balanced: List[Dict[str, Any]] = []
        for _score, group in groupby(results, key=lambda x: x.get("score", 0)):
            group_list = list(group)
            # 按类型分组
            by_type: Dict[str, List[Dict[str, Any]]] = {}
            for item in group_list:
                by_type.setdefault(item["type"], []).append(item)
            # 轮转取出
            max_len = max(len(v) for v in by_type.values())
            for i in range(max_len):
                for t in by_type:
                    if i < len(by_type[t]):
                        balanced.append(by_type[t][i])
        results = balanced

    return results[:top_k]


def _search_cases(
    query: str,
    filters: Dict[str, Any],
    top_k: int,
) -> List[Dict[str, Any]]:
    """检索交易案例"""
    cases_dir = memory_l4_cases_dir()
    if not cases_dir.exists():
        return []

    results = []
    case_files = _list_json(cases_dir)

    for f in case_files:
        case = _load_json(f)
        if not case:
            continue

        # 过滤
        if not _match_filters(case, filters, "case"):
            continue

        # 简单关键词匹配分数
        score = _calc_keyword_score(case, query)
        if score <= 0 and query:  # 有查询词但分数为0，跳过
            continue

        results.append({
            "id": _memory_id("CASE", case.get("case_id", f.stem)),
            "type": "case",
            "score": score,
            "title": _case_title(case),
            "summary": _case_summary(case),
            "tags": case.get("tags", []),
            "timestamp": case.get("timestamp"),
            "data": case,
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


def _search_reviews(
    query: str,
    filters: Dict[str, Any],
    top_k: int,
) -> List[Dict[str, Any]]:
    """检索复盘记录"""
    reviews_dir = memory_l4_reviews_dir()
    if not reviews_dir.exists():
        return []

    results = []
    review_files = _list_json(reviews_dir)

    for f in review_files:
        review = _load_json(f)
        if not review:
            continue

        if not _match_filters(review, filters, "review"):
            continue

        score = _calc_keyword_score(review, query)
        if score <= 0 and query:
            continue

        results.append({
            "id": _memory_id("REV", review.get("review_id", f.stem)),
            "type": "review",
            "score": score,
            "title": f"复盘: {review.get('case_id', 'unknown')}",
            "summary": review.get("summary", "")[:200],
            "tags": [review.get("direction", "")],
            "timestamp": review.get("timestamp"),
            "data": review,
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


def _search_distills(
    query: str,
    filters: Dict[str, Any],
    top_k: int,
) -> List[Dict[str, Any]]:
    """检索蒸馏经验"""
    distills_dir = memory_l4_distills_dir()
    if not distills_dir.exists():
        return []

    results = []
    distill_files = _list_json(distills_dir)

    for f in distill_files:
        distill = _load_json(f)
        if not distill:
            continue

        if not _match_filters(distill, filters, "distill"):
            continue

        score = _calc_keyword_score(distill, query)
        if score <= 0 and query:
            continue

        claim = distill.get("claim", distill.get("what_is_it", {}).get("claim", ""))
        kind = distill.get("kind", "")
        y = distill.get("quadrant", {}).get("y", 0)

        results.append({
            "id": _memory_id("DIST", distill.get("distill_id", f.stem)),
            "type": "distill",
            "score": score,
            "title": f"[{kind}] {claim[:80]}",
            "summary": claim[:200],
            "tags": distill.get("what_is_it", {}).get("classification", []),
            "timestamp": distill.get("process_trace", {}).get("optimization") or "",
            "quality_score": y,
            "data": distill,
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


def _match_filters(item: Dict[str, Any], filters: Dict[str, Any], mem_type: str) -> bool:
    """检查是否匹配过滤条件"""
    # 通用过滤
    if "inst_id" in filters:
        if mem_type == "case":
            if item.get("inst_id") != filters["inst_id"]:
                return False
        elif mem_type == "review":
            if item.get("inst_id") and item["inst_id"] != filters["inst_id"]:
                return False

    if "regime" in filters:
        env = item.get("environment_snapshot") or {}
        if env.get("regime") and filters["regime"] not in env["regime"]:
            return False

    if "decision" in filters:
        if item.get("decision") != filters["decision"]:
            return False

    if "is_profit" in filters:
        do = item.get("decision_outcome") or {}
        pnl = do.get("pnl_pct")
        is_profit = pnl is not None and pnl > 0
        if is_profit != filters["is_profit"]:
            return False

    if "system_source" in filters:
        if item.get("system_source") != filters["system_source"]:
            return False

    if "direction" in filters and mem_type == "review":
        if item.get("direction") != filters["direction"]:
            return False

    return True


def _calc_keyword_score(item: Dict[str, Any], query: str) -> float:
    """简单关键词匹配分数"""
    if not query:
        return 1.0  # 无查询词，全部返回，分数相同

    query_lower = query.lower()
    score = 0.0

    # 在各个字段中搜索
    text_fields = [
        str(item.get("case_id", "")),
        str(item.get("inst_id", "")),
        str(item.get("decision", "")),
        str(item.get("system_source", "")),
        json.dumps(item.get("tags", []), ensure_ascii=False),
        json.dumps(item.get("lessons", []), ensure_ascii=False),
        json.dumps(item.get("review", {}), ensure_ascii=False),
        str(item.get("claim", "")),
        str(item.get("summary", "")),
    ]

    for field in text_fields:
        if query_lower in field.lower():
            score += 1.0

    return score


def _case_title(case: Dict[str, Any]) -> str:
    """生成案例标题"""
    inst = case.get("inst_id", "unknown")
    direction = case.get("decision", "?")
    do = case.get("decision_outcome") or {}
    pnl = do.get("pnl_pct")
    pnl_str = f"pnl={pnl}%" if pnl is not None else "pnl=?"
    return f"{inst} {direction} {pnl_str}"


def _case_summary(case: Dict[str, Any]) -> str:
    """生成案例摘要"""
    env = case.get("environment_snapshot") or {}
    regime = env.get("regime", "")
    conf = case.get("confidence", 0)
    do = case.get("decision_outcome") or {}
    dd = do.get("drawdown", 0)

    parts = []
    if regime:
        parts.append(f"regime={regime}")
    parts.append(f"conf={conf}")
    parts.append(f"dd={dd}")

    review = case.get("review") or {}
    lessons = review.get("lessons", [])
    if lessons:
        parts.append(f"lessons={len(lessons)}")

    return " | ".join(parts)


def add(memory_entry: Dict[str, Any]) -> str:
    """添加记忆

    Args:
        memory_entry: 记忆条目，必须包含 type 字段

    Returns:
        记忆 ID
    """
    mem_type = memory_entry.get("type", "case")

    if mem_type == "case":
        return _add_case(memory_entry)
    elif mem_type == "review":
        return _add_review(memory_entry)
    elif mem_type == "distill":
        return _add_distill(memory_entry)
    else:
        raise ValueError(f"不支持的记忆类型: {mem_type}")


def _add_case(case: Dict[str, Any]) -> str:
    """添加交易案例"""
    case_id = case.get("case_id")
    if not case_id:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        case_id = f"CASE_{ts}"
        case["case_id"] = case_id

    if "timestamp" not in case:
        case["timestamp"] = datetime.now().astimezone().isoformat(timespec="seconds")

    path = memory_l4_cases_dir() / f"{case_id}.json"
    _save_json(path, case)
    return _memory_id("CASE", case_id)


def _add_review(review: Dict[str, Any]) -> str:
    """添加复盘记录"""
    review_id = review.get("review_id")
    if not review_id:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        cid = review.get("case_id", "unknown")[:12]
        review_id = f"REV_{ts}_{cid}"
        review["review_id"] = review_id

    if "timestamp" not in review:
        review["timestamp"] = datetime.now().astimezone().isoformat(timespec="seconds")

    path = memory_l4_reviews_dir() / f"{review_id}.json"
    _save_json(path, review)
    return _memory_id("REV", review_id)


def _add_distill(distill: Dict[str, Any]) -> str:
    """添加蒸馏经验"""
    distill_id = distill.get("distill_id")
    if not distill_id:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        distill_id = f"D_{ts}"
        distill["distill_id"] = distill_id

    path = memory_l4_distills_dir() / f"{distill_id}.json"
    _save_json(path, distill)
    return _memory_id("DIST", distill_id)


def update(memory_id: str, updates: Dict[str, Any]) -> bool:
    """更新记忆

    Args:
        memory_id: 记忆 ID
        updates: 要更新的字段

    Returns:
        是否成功
    """
    # 解析 memory_id 获取原始ID
    parts = memory_id.replace(f"{APP_MEMORY_ID}-", "")
    type_prefix, _, raw_id = parts.partition("-")

    type_map = {
        "CASE": ("case", memory_l4_cases_dir()),
        "REV": ("review", memory_l4_reviews_dir()),
        "DIST": ("distill", memory_l4_distills_dir()),
    }

    if type_prefix not in type_map:
        return False

    mem_type, dir_path = type_map[type_prefix]
    path = dir_path / f"{raw_id}.json"

    if not path.exists():
        return False

    data = _load_json(path)
    if not data:
        return False

    data.update(updates)
    _save_json(path, data)
    return True


def get(memory_id: str) -> Optional[Dict[str, Any]]:
    """获取单条记忆

    Args:
        memory_id: 记忆 ID

    Returns:
        完整的记忆条目，不存在返回 None
    """
    parts = memory_id.replace(f"{APP_MEMORY_ID}-", "")
    type_prefix, _, raw_id = parts.partition("-")

    type_map = {
        "CASE": memory_l4_cases_dir(),
        "REV": memory_l4_reviews_dir(),
        "DIST": memory_l4_distills_dir(),
    }

    if type_prefix not in type_map:
        return None

    dir_path = type_map[type_prefix]
    path = dir_path / f"{raw_id}.json"

    if not path.exists():
        return None

    return _load_json(path)


def stats() -> Dict[str, Any]:
    """统计信息

    Returns:
        记忆数量、类型分布、更新频率等统计信息
    """
    status = get_l4_status_summary()

    return {
        "app_memory_id": APP_MEMORY_ID,
        "app_memory_name": APP_MEMORY_NAME,
        "version": APP_MEMORY_VERSION,
        "total_memories": status.get("cases_total", 0) + status.get("reviews_total", 0) + status.get("distills_total", 0) + status.get("stats_total", 0),
        "by_type": {
            "case": status.get("cases_total", 0),
            "review": status.get("reviews_total", 0),
            "distill": status.get("distills_total", 0),
            "stats_snapshot": status.get("stats_total", 0),
        },
        "health": status.get("health", {}),
        "evolution": status.get("evolution", {}),
        "timestamp": status.get("timestamp"),
    }


def distill_candidates(
    min_quality: float = 0.7,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """蒸馏候选 — 可上升为总记忆的候选列表

    从 distill 记录中筛选高质量的、具有普适性的经验。

    Args:
        min_quality: 最低质量分数 (quadrant y)
        limit: 返回数量

    Returns:
        候选蒸馏经验列表
    """
    distills_dir = memory_l4_distills_dir()
    if not distills_dir.exists():
        return []

    candidates = []
    distill_files = _list_json(distills_dir)

    for f in distill_files:
        distill = _load_json(f)
        if not distill:
            continue

        y = distill.get("quadrant", {}).get("y", 0)
        if y < min_quality:
            continue

        # 检查是否有可上升价值
        rules = distill.get("actionable_rules", [])
        supporting = distill.get("supporting_case_ids", [])
        claim = distill.get("claim", "")

        candidates.append({
            "id": _memory_id("DIST", distill.get("distill_id", f.stem)),
            "type": "distill",
            "claim": claim,
            "kind": distill.get("kind", ""),
            "quality_score": y,
            "actionable_rules_count": len(rules),
            "supporting_cases": len(supporting),
            "why_it_works": distill.get("why_it_works", {}),
            "how_to_apply": distill.get("how_to_apply", {}),
        })

    # 按质量分数排序
    candidates.sort(key=lambda x: x["quality_score"], reverse=True)
    return candidates[:limit]


def healthcheck() -> Dict[str, Any]:
    """健康检查

    Returns:
        状态 + 最后更新时间 + 健康指标
    """
    try:
        status = get_l4_status()
        health = status.get("health", {})

        return {
            "status": "healthy" if health.get("pipeline_connected", False) else "degraded",
            "app_memory_id": APP_MEMORY_ID,
            "app_memory_name": APP_MEMORY_NAME,
            "version": APP_MEMORY_VERSION,
            "last_update": status.get("timestamp"),
            "details": health,
            "pipeline": {
                "cases": status["pipeline"]["cases"]["total"],
                "reviews": status["pipeline"]["reviews"]["total"],
                "distills": status["pipeline"]["distills"]["total"],
                "stats": status["pipeline"]["stats"]["total"],
            },
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "app_memory_id": APP_MEMORY_ID,
            "error": str(e),
            "last_check": datetime.now().astimezone().isoformat(timespec="seconds"),
        }


# ─────────────────────────────────────────────
# 便捷方法
# ─────────────────────────────────────────────

def search_similar_cases(
    inst_id: Optional[str] = None,
    regime: Optional[str] = None,
    decision: Optional[str] = None,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """便捷方法：使用 CBR 引擎检索相似案例

    相比 search()，这个方法使用语义相似度检索，更准确。
    """
    try:
        from scripts.memory_l4.cbr_engine import CBREngine, CBRQuery
        engine = CBREngine(top_k=top_k)
        engine.load(use_index=True)

        query = CBRQuery(
            inst_id=inst_id,
            regime=regime,
            decision=decision,
        )
        retrieved = engine.retrieve(query)

        return [
            {
                "id": _memory_id("CASE", r.case.case_id),
                "type": "case",
                "similarity": r.similarity,
                "rank": r.rank,
                "case": r.case,
            }
            for r in retrieved
        ]
    except Exception:
        # 如果 CBR 引擎加载失败，回退到普通搜索
        return search(
            query="",
            filters={"inst_id": inst_id, "regime": regime, "decision": decision},
            memory_type="case",
            top_k=top_k,
        )


def run_distill_from_review(review_record: Dict[str, Any]) -> Dict[str, Any]:
    """便捷方法：从复盘记录运行完整蒸馏流程"""
    from scripts.memory_l4.distill_engine import run_full_distill_pipeline, save_distill
    distill = run_full_distill_pipeline(review_record)
    save_distill(distill)
    return distill


# ─────────────────────────────────────────────
# CLI 测试入口
# ─────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description="L4交易记忆 - 统一接口测试")
    subparsers = parser.add_subparsers(dest="command", help="命令")

    # healthcheck
    subparsers.add_parser("healthcheck", help="健康检查")

    # stats
    subparsers.add_parser("stats", help="统计信息")

    # search
    p_search = subparsers.add_parser("search", help="检索记忆")
    p_search.add_argument("--query", default="", help="查询词")
    p_search.add_argument("--type", default="all", choices=["all", "case", "review", "distill"], help="记忆类型")
    p_search.add_argument("--limit", type=int, default=5, help="返回数量")

    # get
    p_get = subparsers.add_parser("get", help="获取单条记忆")
    p_get.add_argument("id", help="记忆ID")

    # candidates
    p_cand = subparsers.add_parser("candidates", help="蒸馏候选")
    p_cand.add_argument("--limit", type=int, default=5, help="返回数量")

    args = parser.parse_args()

    if args.command == "healthcheck":
        print(json.dumps(healthcheck(), ensure_ascii=False, indent=2))
    elif args.command == "stats":
        print(json.dumps(stats(), ensure_ascii=False, indent=2))
    elif args.command == "search":
        results = search(query=args.query, memory_type=args.type, top_k=args.limit)
        print(f"找到 {len(results)} 条结果:")
        for r in results:
            print(f"  [{r['type']}] {r['id']} score={r['score']:.2f} {r['title']}")
    elif args.command == "get":
        result = get(args.id)
        if result:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"未找到: {args.id}")
    elif args.command == "candidates":
        candidates = distill_candidates(limit=args.limit)
        print(f"找到 {len(candidates)} 个蒸馏候选:")
        for c in candidates:
            print(f"  {c['id']} quality={c['quality_score']:.3f} {c['claim'][:80]}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
