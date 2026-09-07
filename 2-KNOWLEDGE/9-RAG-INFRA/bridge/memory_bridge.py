# -*- coding: utf-8 -*-
"""RAG ↔ 4-MEMORY 桥接核心。

职责：
1. record_retrieval_as_memory：将 RAG 检索结果 record 为 C 级记忆，
   并持久化 memory_id ↔ (source_file, heading) 映射到 JSONL；
2. verify_and_feedback：查映射 → 调用认知系统 verify → 更新知识库 boost 因子。

设计原则：
- FAIL-OPEN：认知系统不可用时 record 返回空列表、verify 返回安全结果，
  不阻塞 RAG 检索与归档主流程；
- 解耦：不修改 CognitiveLoopEntry 与 RAG 现有代码，仅做适配调用；
- 映射表 JSONL：每行 {memory_id, source_file, heading, query, timestamp}，
  便于增量追加与审计；
- 记忆内容格式：`[RAG检索] query=<query> | source=<source_file> | heading=<heading>`，
  tags 标注 rag/检索/知识域，source 标注 "rag-bridge"。
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# === 路径设置 ===
_THIS_DIR = Path(__file__).resolve().parent
_RAG_INFRA_DIR = _THIS_DIR.parent
if str(_RAG_INFRA_DIR) not in sys.path:
    sys.path.insert(0, str(_RAG_INFRA_DIR))

from .weight_feedback import update_boost, resolve_default_weight_path

# 原生生产映射表路径（9-RAG-INFRA/bridge/retrieval_memory_map.jsonl）
_PROD_MAP_PATH = _THIS_DIR / "retrieval_memory_map.jsonl"


def resolve_default_map_path() -> Path:
    """解析默认 retrieval_memory_map.jsonl 路径。

    优先级：环境变量 TEST_BRIDGE_MAP_PATH > 生产默认。
    """
    env = os.environ.get("TEST_BRIDGE_MAP_PATH")
    if env:
        return Path(env)
    return _PROD_MAP_PATH


def resolve_default_paths() -> Dict[str, Path]:
    """统一返回 {map_path, weight_path}，便于测试与诊断。

    两个路径分别从各自 env 变量 + 生产默认解析，彼此独立。
    """
    return {
        "map_path": resolve_default_map_path(),
        "weight_path": resolve_default_weight_path(),
    }


# 认知系统入口路径（4-MEMORY/9-工具与接口）
# 注：__file__=.../2-KNOWLEDGE/9-RAG-INFRA/bridge/memory_bridge.py
# parents[2]=.../2-KNOWLEDGE / parents[3]=项目根（=4-MEMORY 的上一级），故必须用 parents[3]
_COGNITIVE_DIR = Path(__file__).resolve().parents[3] / "4-MEMORY" / "9-工具与接口"


def _get_cle():
    """懒加载 CognitiveLoopEntry 单例。

    FAIL-OPEN：导入或初始化失败返回 None。
    """
    try:
        if str(_COGNITIVE_DIR) not in sys.path:
            sys.path.insert(0, str(_COGNITIVE_DIR))
        from cognitive_loop_entry import get_cle
        return get_cle()
    except Exception:
        return None


def _append_map(record: Dict, map_path: Optional[Path] = None) -> None:
    """追加一条映射记录到 JSONL。FAIL-OPEN：写入失败静默忽略。"""
    p = Path(map_path) if map_path else resolve_default_map_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _load_map(map_path: Optional[Path] = None) -> List[Dict]:
    """加载映射表。FAIL-OPEN：失败返回空列表。"""
    p = Path(map_path) if map_path else resolve_default_map_path()
    records: List[Dict] = []
    try:
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
    except Exception:
        pass
    return records


def _find_mapping(memory_id: str,
                  map_path: Optional[Path] = None) -> Optional[Dict]:
    """在映射表中查找 memory_id 对应的记录。"""
    for r in _load_map(map_path):
        if r.get("memory_id") == memory_id:
            return r
    return None


def _build_memory_content(query: str, result: Dict) -> str:
    """将 RAG 检索结果转为记忆内容文本。

    F8 格式升级：
    1. snippet 上限 200 → 500 字符，保留更完整的语义上下文；
    2. 若 result 带 summary/conclusion 字段，优先在 [核心结论] 段前置注入，
       避免纯元数据包裹导致 recall 二度检索无法命中真正语义。
    """
    source = result.get("source_file", "")
    heading = result.get("heading", "")
    domain = result.get("domain", "")
    score = result.get("final_score", result.get("score", 0))

    # [F8-A] 优先抽核心结论摘要：summary > conclusion > result 里的结论段落
    summary = (
        result.get("summary")
        or result.get("conclusion")
        or result.get("核心结论")
        or result.get("key_findings")
        or ""
    )
    if isinstance(summary, (list, tuple)):
        summary = "；".join(str(x) for x in summary if x)
    summary = (summary or "").strip().replace("\n", " ")
    if len(summary) > 600:
        summary = summary[:600] + "..."

    # [F8-B] snippet 从 200→500 字符
    snippet = (result.get("content", "") or "").strip().replace("\n", " ")
    if len(snippet) > 500:
        snippet = snippet[:500] + "..."

    parts = [
        f"[RAG检索] query={query}",
        f"source={source}",
        f"heading={heading}",
        f"domain={domain}",
        f"score={score}",
    ]
    if summary:
        parts.insert(1, f"[核心结论] {summary}")
    parts.append(f"snippet={snippet}")
    return " | ".join(parts)


def record_retrieval_as_memory(
    query: str,
    results: List[Dict],
    cle: Any = None,
    map_path: Optional[Path] = None,
) -> List[Dict]:
    """将 RAG 检索结果 record 为 C 级记忆，返回映射记录列表。

    对每个检索结果：
    1. 构造记忆内容（含 query/source/heading/score/snippet）；
    2. 调用 CognitiveLoopEntry.record 写入 C 级记忆（confidence=0.3）；
    3. 追加 memory_id ↔ (source_file, heading, query) 映射到 JSONL。

    Args:
        query: RAG 检索查询文本。
        results: hybrid_search 返回的结果列表。
        cle: CognitiveLoopEntry 实例，None 时懒加载。
        map_path: 映射表 JSONL 路径，默认 bridge/retrieval_memory_map.jsonl。

    Returns:
        映射记录列表，每项含 memory_id/source_file/heading/query/timestamp。
        认知系统不可用时返回空列表（FAIL-OPEN）。
    """
    if not query or not results:
        return []

    if cle is None:
        cle = _get_cle()
    if cle is None:
        # 认知系统不可用，FAIL-OPEN
        return []

    mappings: List[Dict] = []
    ts = int(time.time())
    for r in results:
        try:
            content = _build_memory_content(query, r)
            tags = ["rag", "检索", r.get("domain", "") or "unknown"]
            tags = [t for t in tags if t]
            memory_id = cle.record(
                content=content,
                quality_level="C",
                confidence=0.3,
                tags=tags,
                source="rag-bridge",
            )
            if not memory_id:
                continue
            mapping = {
                "memory_id": memory_id,
                "source_file": r.get("source_file", ""),
                "heading": r.get("heading", ""),
                "query": query,
                "final_score": r.get("final_score", r.get("score", 0)),
                "timestamp": ts,
            }
            _append_map(mapping, map_path)
            mappings.append(mapping)
        except Exception:
            # 单条 record 失败不阻塞其余
            continue
    return mappings


def verify_and_feedback(
    memory_id: str,
    success: bool,
    cle: Any = None,
    map_path: Optional[Path] = None,
    weight_path: Optional[Path] = None,
) -> Dict:
    """verify 记忆并反哺知识库权重。

    流程：
    1. 从映射表查找 memory_id 对应的 source_file/heading；
    2. 调用 CognitiveLoopEntry.verify(memory_id, success)；
    3. 根据映射更新 weight_feedback.json 中对应知识单元的 boost 因子。

    Args:
        memory_id: 认知记忆ID。
        success: verify 是否成功。
        cle: CognitiveLoopEntry 实例，None 时懒加载。
        map_path: 映射表路径。
        weight_path: 权重反馈文件路径。

    Returns:
        {status, memory_id, success, boost_updated, source_file, heading, error}。
        映射不存在或 verify 失败时 status=failed/skipped（FAIL-OPEN）。
    """
    result: Dict[str, Any] = {
        "status": "failed",
        "memory_id": memory_id,
        "success": success,
        "boost_updated": False,
        "source_file": "",
        "heading": "",
        "error": None,
    }

    # 1. 查映射
    mapping = _find_mapping(memory_id, map_path)
    if mapping is None:
        result["status"] = "skipped"
        result["error"] = "mapping_not_found"
        return result

    result["source_file"] = mapping.get("source_file", "")
    result["heading"] = mapping.get("heading", "")

    # 2. verify
    if cle is None:
        cle = _get_cle()
    if cle is not None:
        try:
            verify_result = cle.verify(memory_id, success=success)
            if isinstance(verify_result, dict) and verify_result.get("success") is False \
                    and "error" in verify_result:
                # verify 本身失败（如记忆不存在）
                result["error"] = verify_result.get("error", "verify_failed")
                result["status"] = "failed"
                return result
        except Exception as e:
            result["error"] = f"verify_exception: {e}"
            result["status"] = "failed"
            return result
    # cle 为 None 时仍尝试更新 boost（verify 跳过但反哺不阻塞）

    # 3. 反哺权重
    try:
        new_boost = update_boost(
            result["source_file"], result["heading"], success, weight_path)
        result["boost_updated"] = True
        result["new_boost"] = new_boost
        result["status"] = "done"
    except Exception as e:
        result["error"] = f"boost_update_failed: {e}"
        result["status"] = "failed"
    return result


# ============================================================
# F1: pytest 临时路径垃圾清理
# ============================================================

# macOS pytest 临时目录前缀匹配（命中任一条即判定为pytest垃圾路径）
_TEMP_PATH_PREFIXES = (
    "/tmp/",
    "/private/var/",
    "/var/folders/",
)


def _is_temp_path(value: str) -> bool:
    """判断字符串是否包含pytest临时目录前缀。"""
    if not value:
        return False
    v = value.strip()
    return any(v.startswith(p) or f"{p}" in v for p in _TEMP_PATH_PREFIXES)


def purge_temporary_entries(
    weight_path: Optional[Path] = None,
    map_path: Optional[Path] = None,
    dry_run: bool = False,
) -> Dict[str, int]:
    """清理 weight_feedback.json 和 retrieval_memory_map.jsonl 中的 pytest 临时路径垃圾。

    判定规则：source_file / key 以 /tmp/、/private/var/、/var/folders/ 开头
              或中间包含这些 pytest 临时目录段。

    Args:
        weight_path: weight_feedback.json 路径，None 时跳过权重清理。
        map_path: retrieval_memory_map.jsonl 路径，None 时跳过映射清理。
        dry_run:  True 时仅统计不修改文件，默认 False。

    Returns:
        {weight_removed, weight_kept, map_removed, map_kept} 四项统计。
        文件不存在或为空时对应项为 0（FAIL-OPEN）。
    """
    stats: Dict[str, int] = {
        "weight_removed": 0,
        "weight_kept": 0,
        "map_removed": 0,
        "map_kept": 0,
    }

    # ---------- 1. 清理 weight_feedback.json ----------
    if weight_path is not None:
        p = Path(weight_path)
        try:
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    kept: Dict[str, float] = {}
                    removed_count = 0
                    for k, v in data.items():
                        if _is_temp_path(k):
                            removed_count += 1
                        else:
                            kept[k] = v
                    stats["weight_removed"] = removed_count
                    stats["weight_kept"] = len(kept)
                    if not dry_run:
                        p.write_text(
                            json.dumps(kept, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
        except Exception:
            # FAIL-OPEN：清理失败不抛出，保持统计为 0
            pass

    # ---------- 2. 清理 retrieval_memory_map.jsonl ----------
    if map_path is not None:
        p = Path(map_path)
        try:
            if p.exists():
                raw_lines = p.read_text(encoding="utf-8").splitlines()
                kept_lines: List[str] = []
                removed_count = 0
                for line in raw_lines:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        # 非法 JSON 行视为垃圾
                        removed_count += 1
                        continue
                    sf = str(rec.get("source_file", ""))
                    if _is_temp_path(sf):
                        removed_count += 1
                    else:
                        kept_lines.append(json.dumps(rec, ensure_ascii=False))
                stats["map_removed"] = removed_count
                stats["map_kept"] = len(kept_lines)
                if not dry_run:
                    p.write_text("\n".join(kept_lines) + "\n", encoding="utf-8")
        except Exception:
            # FAIL-OPEN
            pass

    return stats
