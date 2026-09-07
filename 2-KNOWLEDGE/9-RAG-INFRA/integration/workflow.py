# -*- coding: utf-8 -*-
"""开发流程集成：对话中检测调研内容 → 提示归档 → 触发 ingest。

对外暴露：
- check_and_prompt：检测并生成提示消息；
- archive_from_conversation：执行完整归档流程；
- batch_detect：批量检测。
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional

# === 路径设置 ===
_THIS_DIR = Path(__file__).resolve().parent
_RAG_INFRA_DIR = _THIS_DIR.parent
if str(_RAG_INFRA_DIR) not in sys.path:
    sys.path.insert(0, str(_RAG_INFRA_DIR))

from vector_store.config import KNOWLEDGE_BASE_DIR
from .detector import detect_research
from .archiver import archive_research


def check_and_prompt(content: str) -> Dict:
    """检测内容并返回是否需要提示归档。

    Returns:
        {need_archive: bool, detections: list, prompt_message: str}
        prompt_message 为给用户的提示，如"检测到finance调研内容，建议归档到
        finance/quant-methods，标签#kalman #量化，是否归档？"。
    """
    detections = detect_research(content)
    if not detections:
        return {"need_archive": False, "detections": [], "prompt_message": ""}

    parts = []
    for d in detections:
        tags_str = " ".join(d["tags"][:5]) if d["tags"] else ""
        tag_clause = f"，标签{tags_str}" if tags_str else ""
        parts.append(
            f"检测到{d['type']}调研内容，建议归档到{d['suggested_path']}{tag_clause}"
        )
    prompt = "；".join(parts) + "。是否归档？(Y/N)"
    return {"need_archive": True, "detections": detections, "prompt_message": prompt}


def archive_from_conversation(content: str, research_topic: str = "",
                             research_scenario: str = "",
                             knowledge_dir: Path = None,
                             enable_memory: bool = True,
                             enable_verify: bool = True,
                             map_path: Optional[Path] = None) -> Dict:
    """执行完整归档流程：检测 → 逐条归档 → 触发 ingest → 记录记忆 → 自动verify → 汇总。

    在原归档流程基础上，新增两个认知闭环步骤（均 FAIL-OPEN）：
    1. record：归档成功的新知识单元 record 为 C 级记忆，进入检索→记忆→verify→boost 闭环；
    2. verify：归档状态 = indexed/duplicate（即内容有效、被成功采纳入库）时，
       自动对映射的记忆执行 verify(success=True)，触发 boost 权重正反馈反哺。
       归档状态 = failed 时不 verify，避免错误内容被正反馈。
    认知系统不可用时以上两步均静默跳过，不影响归档主流程。

    Args:
        content: 对话文本。
        research_topic: 调研主题。
        research_scenario: 调研场景。
        knowledge_dir: 知识库根目录，默认 2-KNOWLEDGE（基于 config.py 解析）。
        enable_memory: 是否记录归档结果为 C 级记忆，默认 True。
        enable_verify: 归档成功后是否自动 verify(success=True)，默认 True。
        map_path: 映射表路径，默认 bridge/retrieval_memory_map.jsonl。

    Returns:
        {status, archived: list, detections: list,
         memory_recorded: int, memory_verified: int}
    """
    if knowledge_dir is None:
        knowledge_dir = Path(KNOWLEDGE_BASE_DIR)
    knowledge_dir = Path(knowledge_dir)

    detections = detect_research(content)
    if not detections:
        return {"status": "no_research", "archived": [], "detections": [],
                "memory_recorded": 0, "memory_verified": 0}

    archived: List[Dict] = []
    memory_recorded = 0
    memory_verified = 0
    for d in detections:
        try:
            r = archive_research(d, content, knowledge_dir,
                                 research_topic, research_scenario)
            archived.append(r)
            # 归档成功后，将新知识单元 record 为 C 级记忆（FAIL-OPEN）
            archive_status = r.get("status")
            if enable_memory and archive_status not in ("failed",):
                try:
                    mem_count, mappings = _record_archive_as_memory(
                        d, r, research_topic, map_path,
                        return_mappings=True)
                    memory_recorded += mem_count

                    # FIX-EV-0: 归档有效（indexed/duplicate）时自动 verify(success=True)
                    if (enable_verify and mem_count > 0 and mappings
                            and archive_status in ("indexed", "duplicate")):
                        try:
                            from bridge.memory_bridge import verify_and_feedback
                            verify_count = 0
                            for m in mappings:
                                mid = m.get("memory_id") if isinstance(m, dict) else None
                                if not mid:
                                    continue
                                # FIX-EV-0：verify_and_feedback 接受单个 memory_id
                                # 返回结构 {status, success, boost_updated, ...}
                                # 当 status='done' 或 cle.verify 明确成功时，
                                # 计数为一次有效正反馈
                                vr = verify_and_feedback(
                                    mid, success=True,
                                    map_path=map_path)
                                if (isinstance(vr, dict)
                                        and vr.get("status") == "done"):
                                    verify_count += 1
                                elif (isinstance(vr, dict)
                                      and vr.get("status") == "skipped"
                                      and vr.get("error") == "mapping_not_found"):
                                    # mapping 写入后立即读取可能存在时序问题，
                                    # 但 record_retrieval_as_memory 已
                                    # _append_map，所以实际不应该触发此分支
                                    pass
                            memory_verified += verify_count
                        except Exception:
                            # verify 失败不阻塞归档，也不影响已记录的记忆
                            pass
                except Exception:
                    # 记忆写入失败不阻塞归档
                    pass
        except Exception as e:
            # FAIL-OPEN：单条归档失败不阻塞其余归档
            archived.append({
                "status": "failed",
                "error": str(e),
                "type": d.get("type"),
            })
    return {"status": "done", "archived": archived, "detections": detections,
            "memory_recorded": memory_recorded,
            "memory_verified": memory_verified}


def _record_archive_as_memory(detection: Dict, archive_result: Dict,
                               research_topic: str,
                               map_path: Optional[Path] = None,
                               return_mappings: bool = False):
    """将归档的新知识单元 record 为 C 级记忆。

    构造伪检索结果，调用 record_retrieval_as_memory 写入记忆系统。

    Args:
        detection: detect_research 返回的单条检测结果。
        archive_result: archive_research 返回的结果。
        research_topic: 调研主题。
        map_path: 映射表路径，默认 bridge/retrieval_memory_map.jsonl。
        return_mappings: 如果 True，返回 (count, mappings) 元组，
            便于调用方后续进行 verify_and_feedback。默认 False，
            仅返回 count，保持向后字节等价（原调用行为不变）。

    Returns:
        默认：len(mappings) 计数（0 表示认知系统不可用或失败）。
        return_mappings=True：(count, mappings) 元组。
    """
    mappings = []
    try:
        from bridge.memory_bridge import record_retrieval_as_memory
    except ImportError:
        return (0, mappings) if return_mappings else 0

    # 构造伪检索结果，使记忆内容携带归档信息
    pseudo_query = f"归档: {research_topic or detection.get('suggested_path', '')}"
    pseudo_result = {
        "source_file": archive_result.get("file_path", ""),
        "heading": research_topic or detection.get("suggested_path", ""),
        "domain": detection.get("category", ""),
        "final_score": 1.0,
        "content": (f"[归档] {detection.get('type', '')}/"
                    f"{detection.get('subcategory', '')} | "
                    f"tags: {' '.join(detection.get('tags', [])[:5])}"),
    }
    try:
        mappings = record_retrieval_as_memory(
            pseudo_query, [pseudo_result], map_path=map_path)
    except Exception:
        mappings = []

    count = len(mappings)
    return (count, mappings) if return_mappings else count


def batch_detect(contents: List[str]) -> List[List[Dict]]:
    """批量检测多条内容，返回每条的检测结果列表。"""
    return [detect_research(c) for c in contents]
