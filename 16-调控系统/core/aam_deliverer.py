#!/usr/bin/env python3
"""
AAM 产物投递模块 — 16-调控系统 Phase 3

Artifact Alignment Manager — 产物对齐管理器

负责：
  1. 标准化产物 frontmatter 格式
  2. 双通道投递（秘书邮箱 + 前端产物中心）
  3. index.json 更新
  4. 投递验证与审计日志

投递通道：
  - 秘书邮箱通道：~/.workbuddy/skills/boss-secretary/reports/trading/
  - 前端产物中心通道：~/.workbuddy/artifacts/trading/

遵循 AAM SKILL 规范：
  https://a36bd7e9e7c746c18b294feae730dc67-400805925.cn-shanghai.fc.devapps.volces.com/skill/019a5a61-a4ed-72e6-8d8b-8e8b1f2ac5e7
"""

import json
import os
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from dataclasses import dataclass, field

BASE_DIR = Path(__file__).parent.parent.parent
HOME = Path(os.path.expanduser("~"))

DEFAULT_CHANNELS = {
    "secretary_mailbox": HOME / ".workbuddy" / "skills" / "boss-secretary" / "reports" / "trading",
    "frontend_artifact_center": HOME / ".workbuddy" / "artifacts" / "trading",
}

LOCAL_ARTIFACTS_DIR = BASE_DIR / "16-调控系统" / "artifacts" / "exit-evaluations"


@dataclass
class DeliveryResult:
    """投递结果"""
    success: bool
    channels: Dict[str, bool] = field(default_factory=dict)
    artifact_paths: Dict[str, List[str]] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    index_updated: bool = False
    timestamp: str = ""


def generate_frontmatter(
    title: str,
    dept: str = "trading",
    artifact_type: str = "report",
    chain_phase: str = "A9",
    status: str = "completed",
    tags: List[str] = None,
    by_a_phase: str = "A1+A2+A3+A9",
) -> str:
    """
    生成标准 AAM frontmatter

    Args:
        title: 产物标题（包含日期）
        dept: 部门/分类
        artifact_type: 类型 report/analysis/decision/skill/artifact
        chain_phase: 链阶段 A1/A2/A3/A9 等
        status: completed/pending/failed
        tags: 标签列表
        by_a_phase: 执行阶段组合

    Returns:
        YAML frontmatter 字符串
    """
    now = datetime.now(timezone.utc).isoformat()
    tags_str = ", ".join(tags) if tags else "exit-evaluation, macro-analysis, a9-decision"

    lines = [
        "---",
        f'title: "{title}"',
        f"department: {dept}",
        f"chain_phase: {chain_phase}",
        f'date: "{now}"',
        f"type: {artifact_type}",
        f"status: {status}",
        f'tags: "{tags_str}"',
        f"by_a_phase: {by_a_phase}",
        "---",
        "",
    ]
    return "\n".join(lines)


def _ensure_dir(path: Path) -> bool:
    """确保目录存在"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        return True
    except Exception:
        return False


def _update_index_json(directory: Path, artifact_file: str, metadata: Dict[str, Any]) -> bool:
    """
    更新目录下的 index.json

    Args:
        directory: 目录路径
        artifact_file: 产物文件名
        metadata: 产物元数据

    Returns:
        是否更新成功
    """
    try:
        index_path = directory / "index.json"

        index_data = {"artifacts": []}
        if index_path.exists():
            try:
                with open(index_path, "r", encoding="utf-8") as f:
                    index_data = json.load(f)
                    if "artifacts" not in index_data:
                        index_data["artifacts"] = []
            except (json.JSONDecodeError, IOError):
                index_data = {"artifacts": []}

        entry = {
            "filename": artifact_file,
            "title": metadata.get("title", ""),
            "type": metadata.get("type", "report"),
            "date": metadata.get("date", ""),
            "status": metadata.get("status", "completed"),
            "tags": metadata.get("tags", []),
            "size_kb": 0,
        }

        full_path = directory / artifact_file
        if full_path.exists():
            entry["size_kb"] = round(full_path.stat().st_size / 1024, 1)

        found = False
        for i, art in enumerate(index_data["artifacts"]):
            if art.get("filename") == artifact_file:
                index_data["artifacts"][i] = entry
                found = True
                break
        if not found:
            index_data["artifacts"].insert(0, entry)

        index_data["artifacts"] = index_data["artifacts"][:200]
        index_data["last_updated"] = datetime.now(timezone.utc).isoformat()
        index_data["total_count"] = len(index_data["artifacts"])

        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index_data, f, ensure_ascii=False, indent=2)

        return True
    except Exception:
        return False


def deliver_artifact(
    content: str,
    filename: str,
    metadata: Dict[str, Any] = None,
    channels: Dict[str, Path] = None,
    update_index: bool = True,
) -> DeliveryResult:
    """
    投递产物到双通道

    Args:
        content: 产物内容（Markdown 带 frontmatter）
        filename: 文件名
        metadata: 产物元数据（用于 index.json）
        channels: 自定义通道，None 则使用默认双通道
        update_index: 是否更新 index.json

    Returns:
        DeliveryResult
    """
    if channels is None:
        channels = DEFAULT_CHANNELS

    if metadata is None:
        metadata = {}

    result = DeliveryResult(
        success=False,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    for channel_name, channel_dir in channels.items():
        try:
            if not _ensure_dir(channel_dir):
                result.errors.append(f"{channel_name}: 目录创建失败")
                result.channels[channel_name] = False
                continue

            dest_path = channel_dir / filename
            with open(dest_path, "w", encoding="utf-8") as f:
                f.write(content)

            result.channels[channel_name] = True
            if channel_name not in result.artifact_paths:
                result.artifact_paths[channel_name] = []
            result.artifact_paths[channel_name].append(str(dest_path))

            if update_index:
                idx_ok = _update_index_json(channel_dir, filename, metadata)
                if idx_ok and channel_name == "frontend_artifact_center":
                    result.index_updated = True

        except Exception as e:
            result.errors.append(f"{channel_name}: {str(e)}")
            result.channels[channel_name] = False

    success_count = sum(1 for v in result.channels.values() if v)
    result.success = success_count > 0

    return result


def deliver_exit_evaluation(
    markdown_content: str,
    json_data: Dict[str, Any],
    evaluation_id: str,
    date_str: str = None,
) -> DeliveryResult:
    """
    投递离场评估报告（便捷函数）

    Args:
        markdown_content: Markdown 报告内容
        json_data: JSON 格式完整数据
        evaluation_id: 评估 ID
        date_str: 日期字符串（默认今天）

    Returns:
        DeliveryResult
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    md_filename = f"exit_evaluation_{date_str}_{evaluation_id}.md"
    json_filename = f"exit_evaluation_{date_str}_{evaluation_id}.json"

    title = f"离场战略评估报告 {date_str}"
    frontmatter = generate_frontmatter(
        title=title,
        dept="trading",
        artifact_type="report",
        chain_phase="A9",
        status="completed",
        tags=["exit-evaluation", "macro-analysis", "a1-a2-a3", "a9-decision", "phase3"],
        by_a_phase="A1+A2+A3+A9+Tech",
    )

    full_md = frontmatter + markdown_content.lstrip("\n")

    metadata = {
        "title": title,
        "type": "report",
        "date": datetime.now(timezone.utc).isoformat(),
        "status": "completed",
        "tags": ["exit-evaluation", "macro-analysis", "a9-decision"],
    }

    md_result = deliver_artifact(full_md, md_filename, metadata)

    json_meta = dict(metadata)
    json_meta["type"] = "data"
    json_content = json.dumps(json_data, ensure_ascii=False, indent=2)
    json_result = deliver_artifact(json_content, json_filename, json_meta)

    combined = DeliveryResult(
        success=md_result.success or json_result.success,
        timestamp=md_result.timestamp,
        index_updated=md_result.index_updated or json_result.index_updated,
    )

    for ch in set(list(md_result.channels.keys()) + list(json_result.channels.keys())):
        combined.channels[ch] = md_result.channels.get(ch, False) and json_result.channels.get(ch, False)

    for ch, paths in md_result.artifact_paths.items():
        combined.artifact_paths.setdefault(ch, []).extend(paths)
    for ch, paths in json_result.artifact_paths.items():
        combined.artifact_paths.setdefault(ch, []).extend(paths)

    combined.errors = md_result.errors + json_result.errors

    LOCAL_ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        local_md = LOCAL_ARTIFACTS_DIR / md_filename
        local_json = LOCAL_ARTIFACTS_DIR / json_filename
        with open(local_md, "w", encoding="utf-8") as f:
            f.write(full_md)
        with open(local_json, "w", encoding="utf-8") as f:
            f.write(json_content)
        combined.artifact_paths["local_artifacts"] = [str(local_md), str(local_json)]
    except Exception as e:
        combined.errors.append(f"local: {str(e)}")

    return combined


def list_delivered_artifacts(channel: str = "frontend_artifact_center",
                              limit: int = 20) -> List[Dict[str, Any]]:
    """
    列出已投递的产物

    Args:
        channel: 通道名称
        limit: 最大数量

    Returns:
        产物列表
    """
    channel_dir = DEFAULT_CHANNELS.get(channel)
    if not channel_dir:
        return []

    index_path = channel_dir / "index.json"
    if index_path.exists():
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("artifacts", [])[:limit]
        except (json.JSONDecodeError, IOError):
            pass

    artifacts = []
    if channel_dir.exists():
        for fp in sorted(channel_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
            artifacts.append({
                "filename": fp.name,
                "title": fp.stem,
                "date": datetime.fromtimestamp(fp.stat().st_mtime).isoformat(),
                "size_kb": round(fp.stat().st_size / 1024, 1),
            })
    return artifacts


if __name__ == "__main__":
    test_content = """
# 测试报告

这是一份测试报告。

## 概览
- 测试项 1: 通过
- 测试项 2: 通过
"""

    result = deliver_exit_evaluation(
        markdown_content=test_content,
        json_data={"test": True, "items": [1, 2, 3]},
        evaluation_id="test001",
    )

    print(f"投递成功: {result.success}")
    print(f"通道状态: {result.channels}")
    print(f"Index 更新: {result.index_updated}")
    for ch, paths in result.artifact_paths.items():
        print(f"{ch}:")
        for p in paths:
            print(f"  - {p}")
    if result.errors:
        print(f"错误: {result.errors}")

    recent = list_delivered_artifacts(limit=5)
    print(f"\n最近产物 ({len(recent)} 个):")
    for art in recent[:3]:
        print(f"  - {art.get('filename', art.get('title', 'N/A'))}")
