# -*- coding: utf-8 -*-
"""知识单元归档器：将检测到的调研内容按模板生成 md 并触发增量索引。

流程：
1. 按 7-EXTERNAL-RESEARCH/INDEX.md 模板生成 Markdown；
2. 调用 ingest_document 触发向量 + 图谱增量索引；
3. 落库到 knowledge_dir/7-EXTERNAL-RESEARCH/{suggested_path}/；
4. 更新 7-EXTERNAL-RESEARCH/INDEX.md（在维护规则前追加新条目）。

FAIL-OPEN：索引 / 图谱 / INDEX 更新失败不阻塞归档返回。
注意：ingest_document 对库内已存在文件会自去重（跳过索引），
故先写入库外临时文件，由 ingest 落库后再移动到目标子目录。
"""

import re
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict

# === 路径设置：将 9-RAG-INFRA 加入 sys.path，使各子包可作为顶层包导入 ===
_THIS_DIR = Path(__file__).resolve().parent
_RAG_INFRA_DIR = _THIS_DIR.parent
if str(_RAG_INFRA_DIR) not in sys.path:
    sys.path.insert(0, str(_RAG_INFRA_DIR))

from evolution.ingest import ingest_document


def _slugify(text: str) -> str:
    """将文本转为文件名 slug：保留中文/字母/数字，空格转连字符，去特殊字符。

    中文保留原字符（不依赖拼音库），满足"保留中文"的 slug 要求。
    """
    s = (text or "").strip().lower()
    s = re.sub(r"\s+", "-", s)
    # 保留中文、字母、数字、连字符
    s = re.sub(r"[^\w\-]", "", s, flags=re.UNICODE)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "research"


def _build_md(detection: Dict, research_content: str,
            research_topic: str, research_scenario: str) -> tuple:
    """按归档模板生成 Markdown 内容，返回 (md_text, date_str)。"""
    title = research_topic or f"{detection['category']}/{detection['subcategory']} 调研"
    date_str = datetime.now().strftime("%Y-%m-%d")
    tags_str = " ".join(detection["tags"]) if detection["tags"] else "#research"
    scenario = research_scenario or "对话中检测到的调研内容"
    kws = detection.get("keywords_matched", [])
    source = f"对话归档（{detection['type']}：{', '.join(kws[:5]) if kws else '关键词匹配'}）"
    excerpt = detection.get("excerpt", "")
    content_body = research_content or excerpt

    md = f"""# {title}

> **分类**: {detection['category']}/{detection['subcategory']}
> **调研日期**: {date_str}
> **调研场景**: {scenario}
> **来源**: {source}
> **标签**: {tags_str}
> **状态**: active

## 调研结论

{excerpt}

## 调研路径

匹配关键词：{', '.join(kws) if kws else '-'}

## 在DreamBuddy中的应用

{content_body}

## 关联知识

（待补充，指向2-KNOWLEDGE其他域的交叉引用）

---

_最后更新：{date_str} | 来源：对话归档_
"""
    return md, date_str


def _update_index(knowledge_dir: Path, detection: Dict, final_path: Path,
                 date_str: str, slug: str, research_topic: str) -> None:
    """更新 7-EXTERNAL-RESEARCH/INDEX.md，在维护规则前追加新条目。

    若 INDEX.md 不存在则创建最小模板；FAIL-OPEN：更新失败不阻塞归档。
    """
    index_path = knowledge_dir / "7-EXTERNAL-RESEARCH" / "INDEX.md"
    rel = final_path.relative_to(knowledge_dir)
    title = research_topic or slug
    tags_str = " ".join(detection["tags"][:5]) if detection["tags"] else "-"
    entry = (f"- [{date_str}] [{title}]({rel.as_posix()}) — "
             f"{detection['category']}/{detection['subcategory']} | 标签: {tags_str}")

    try:
        if index_path.exists():
            content = index_path.read_text(encoding="utf-8")
            if "## 归档记录" in content:
                # 在归档记录 section 内、下一个 ## 之前追加
                idx = content.find("## 归档记录")
                next_sec = content.find("\n## ", idx + 1)
                insert_pos = next_sec if next_sec != -1 else len(content)
                new_content = (content[:insert_pos].rstrip()
                               + "\n" + entry + "\n" + content[insert_pos:])
            elif "## 维护规则" in content:
                new_content = content.replace(
                    "## 维护规则",
                    f"## 归档记录\n\n{entry}\n\n## 维护规则", 1)
            else:
                new_content = (content.rstrip()
                               + f"\n\n## 归档记录\n\n{entry}\n")
            index_path.write_text(new_content, encoding="utf-8")
        else:
            index_path.parent.mkdir(parents=True, exist_ok=True)
            minimal = (f"# 7-EXTERNAL-RESEARCH — 外部资料素材库\n\n"
                       f"## 归档记录\n\n{entry}\n\n"
                       f"## 维护规则\n\n"
                       f"- INDEX更新: 每次归档时同步更新本文件\n")
            index_path.write_text(minimal, encoding="utf-8")
    except Exception:
        pass  # FAIL-OPEN：INDEX 更新失败不阻塞


def archive_research(detection: Dict, research_content: str,
                    knowledge_dir: Path, research_topic: str = "",
                    research_scenario: str = "") -> Dict:
    """归档单条调研检测结果：生成 md、触发 ingest、更新 INDEX。

    Args:
        detection: detect_research 返回的单条检测结果。
        research_content: 调研原文（对话内容）。
        knowledge_dir: 知识库根目录。
        research_topic: 调研主题（用于标题与文件名）。
        research_scenario: 调研场景描述。

    Returns:
        dict 含 status/file_path/chunks_indexed/nodes_extracted/
        index_status/graph_status。
    """
    knowledge_dir = Path(knowledge_dir)
    md_text, date_str = _build_md(detection, research_content,
                                 research_topic, research_scenario)
    slug = _slugify(research_topic or (detection.get("keywords_matched") or ["research"])[0])
    filename = f"{date_str}-{slug}.md"

    rel_dir = Path("7-EXTERNAL-RESEARCH") / detection["suggested_path"]
    final_path = knowledge_dir / rel_dir / filename
    final_path.parent.mkdir(parents=True, exist_ok=True)

    # 写入库外临时文件 → 调用 ingest_document 触发增量索引
    # （ingest 对库内文件会自去重，故先写库外，由 ingest 落库后再移动）
    tmp_dir = Path(tempfile.mkdtemp(prefix="archive_"))
    tmp_file = tmp_dir / filename
    result: Dict
    try:
        tmp_file.write_text(md_text, encoding="utf-8")
        result = ingest_document(tmp_file, knowledge_dir)
    except Exception as e:
        # ingest 异常时 FAIL-OPEN：直接写入最终路径
        try:
            final_path.write_text(md_text, encoding="utf-8")
        except Exception:
            pass
        result = {
            "status": "failed",
            "chunks_indexed": 0,
            "nodes_extracted": 0,
            "index_status": "failed",
            "graph_status": "failed",
            "error": str(e),
        }
    else:
        # ingest 将文件平铺写入 knowledge_dir/{filename}，移动到目标子目录
        flat_dest = knowledge_dir / filename
        try:
            if flat_dest.exists():
                shutil.move(str(flat_dest), str(final_path))
            elif not final_path.exists():
                # ingest 因去重未落库时，确保最终文件存在
                final_path.write_text(md_text, encoding="utf-8")
        except Exception:
            if not final_path.exists():
                final_path.write_text(md_text, encoding="utf-8")
    finally:
        try:
            tmp_file.unlink(missing_ok=True)
            tmp_dir.rmdir()
        except Exception:
            pass

    # 更新 INDEX.md
    _update_index(knowledge_dir, detection, final_path, date_str,
                 slug, research_topic)

    return {
        "status": result.get("status", "indexed"),
        "file_path": str(final_path),
        "chunks_indexed": result.get("chunks_indexed", 0),
        "nodes_extracted": result.get("nodes_extracted", 0),
        "index_status": result.get("index_status", "ok"),
        "graph_status": result.get("graph_status", "ok"),
    }
