#!/usr/bin/env python3
"""
认知触发层 — CognitiveHook

IDE无关的自动接入层核心。通过git hooks自动触发认知闭环：
  git commit → extract_commit_info → generate_experience → record + verify

设计原则：
  - 不修改cognitive_loop_entry.py任何代码（Adapter Pattern）
  - dry_run模式支持预览不产生副作用
  - 失败不阻塞git操作（hook静默失败）

用法（git hook自动调用）:
  # .git/hooks/post-commit
  #!/bin/sh
  python3 /path/to/cognitive_hook.py --post-commit

用法（手动测试）:
  python3 cognitive_hook.py --post-commit --dry-run
  python3 cognitive_hook.py --post-commit --verbose
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# 添加同目录到路径
_SCRIPT_DIR = Path(__file__).parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from cognitive_loop_entry import CognitiveLoopEntry


# ============================================================
# Step 1: 从git commit提取信息
# ============================================================

def extract_commit_info() -> Dict[str, Any]:
    """
    从最近的git commit提取结构化信息。
    
    Returns:
        {
            "commit_hash": str,      # 短hash
            "message": str,          # commit message全文
            "files": List[str],      # 变更文件列表
            "insertions": int,       # 新增行数
            "deletions": int,        # 删除行数
            "author": str,           # 作者
        }
    """
    # commit hash
    hash_result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    commit_hash = hash_result.stdout.strip()

    # commit message (subject + body)
    msg_result = subprocess.run(
        ["git", "log", "-1", "--format=%B"],
        capture_output=True, text=True, check=True,
    )
    message = msg_result.stdout.strip()

    # 变更文件列表 (--root 支持首次commit无parent的情况)
    files_result = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "--root", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    files = [f.strip() for f in files_result.stdout.strip().split("\n") if f.strip()]

    # 行数统计
    stat_result = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "--numstat", "-r", "--root", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    insertions = 0
    deletions = 0
    for line in stat_result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 3:
            try:
                insertions += int(parts[0])
                deletions += int(parts[1])
            except ValueError:
                pass  # 二进制文件显示为 -

    # 作者
    author_result = subprocess.run(
        ["git", "log", "-1", "--format=%an"],
        capture_output=True, text=True, check=True,
    )
    author = author_result.stdout.strip()

    return {
        "commit_hash": commit_hash,
        "message": message,
        "files": files,
        "insertions": insertions,
        "deletions": deletions,
        "author": author,
    }


# ============================================================
# Step 2: 分类变更类型
# ============================================================

def classify_change_type(message: str) -> str:
    """
    根据commit message前缀分类变更类型。
    支持 conventional commits 和中文前缀。
    """
    msg_lower = message.lower().strip()

    # 英文 conventional commits
    if re.match(r"^(feat|feature)[\(:]", msg_lower):
        return "feature"
    if re.match(r"^fix[\(:]", msg_lower):
        return "bugfix"
    if re.match(r"^refactor[\(:]", msg_lower):
        return "refactor"
    if re.match(r"^docs?[\(:]", msg_lower):
        return "docs"
    if re.match(r"^test[\(:]", msg_lower):
        return "test"
    if re.match(r"^chore[\(:]", msg_lower):
        return "chore"
    if re.match(r"^(perf|performance)[\(:]", msg_lower):
        return "perf"
    if re.match(r"^(ci|build)[\(:]", msg_lower):
        return "ci"

    # 中文前缀
    if re.match(r"^(新增|添加|实现|创建)", message):
        return "feature"
    if re.match(r"^(修复|解决|修正)", message):
        return "bugfix"
    if re.match(r"^(重构|调整|优化)", message):
        return "refactor"
    if re.match(r"^(文档|说明)", message):
        return "docs"
    if re.match(r"^(测试|单测)", message):
        return "test"

    return "other"


# ============================================================
# Step 3: 生成经验描述
# ============================================================

def _parse_commit_message(message: str) -> Dict[str, Any]:
    """
    深度解析commit message，提取结构化语义。

    支持格式：
    - conventional: feat(scope): description\n\nbody
    - 中文前缀: 修复：description\n\nbody
    - 纯文本: description

    Returns:
        {
            "type": str,          # feature/bugfix/refactor/...
            "scope": str,         # 作用域（如模块名），无则为空
            "subject": str,       # 第一行描述
            "body": str,          # body全文（第二行之后）
            "body_summary": str,  # body的前100字符摘要
            "has_reason": bool,   # body是否包含原因说明
        }
    """
    lines = message.strip().split("\n")
    first_line = lines[0].strip()
    body = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""

    change_type = classify_change_type(message)

    # 尝试提取scope: type(scope): description
    scope = ""
    subject = first_line
    scope_match = re.match(r'^(?:feat|feature|fix|refactor|docs?|test|chore|perf|ci|build|新增|修复|重构|文档|测试|优化)[\(:]\s*([^\)\：]+)[\)\：][\s:：]*\s*(.+)', first_line)
    if scope_match:
        scope = scope_match.group(1).strip()
        subject = scope_match.group(2).strip()
    else:
        # 去掉类型前缀，只保留描述
        prefix_match = re.match(r'^(?:feat|feature|fix|refactor|docs?|test|chore|perf|ci|build|新增|修复|重构|文档|测试|优化)[\：:]\s*(.+)', first_line)
        if prefix_match:
            subject = prefix_match.group(1).strip()

    # body摘要
    body_summary = body[:100].replace("\n", " ").strip() if body else ""
    # 检查body是否包含原因说明
    reason_keywords = ["因为", "由于", "导致", "原因", "问题", "bug", "为了", "所以", "修复了", "解决了"]
    has_reason = any(kw in body.lower() for kw in reason_keywords) if body else False

    return {
        "type": change_type,
        "scope": scope,
        "subject": subject,
        "body": body,
        "body_summary": body_summary,
        "has_reason": has_reason,
    }


def generate_experience_description(commit_info: Dict[str, Any]) -> str:
    """
    从commit信息生成结构化的经验描述（v2：深度语义提取）。

    格式: [类型][scope] subject | 原因: body摘要 | 变更文件: file1, file2 | +N -M
    """
    parsed = _parse_commit_message(commit_info["message"])
    type_labels = {
        "feature": "新功能",
        "bugfix": "Bug修复",
        "refactor": "重构",
        "docs": "文档",
        "test": "测试",
        "chore": "杂项",
        "perf": "性能",
        "ci": "CI/CD",
        "other": "其他",
    }
    type_label = type_labels.get(parsed["type"], parsed["type"])

    # 类型+scope
    header = f"[{type_label}]"
    if parsed["scope"]:
        header += f"[{parsed['scope']}]"

    # 主题
    desc = f"{header} {parsed['subject']}"

    # 原因（如果有body摘要）
    if parsed["body_summary"]:
        desc += f" | 原因: {parsed['body_summary']}"

    # 文件列表（最多显示5个）
    files = commit_info["files"][:5]
    files_str = ", ".join(Path(f).name for f in files)
    if len(commit_info["files"]) > 5:
        files_str += f" 等{len(commit_info['files'])}个文件"
    desc += f" | 文件: {files_str}"

    # 行数统计
    stats = f"+{commit_info['insertions']} -{commit_info['deletions']}"
    desc += f" | {stats}"

    return desc


# ============================================================
# Step 4: 触发认知闭环
# ============================================================

def find_daemon_memories_for_files(
    commit_files: List[str],
    cle: Any = None,
) -> List[Dict[str, Any]]:
    """
    接力第1步：根据commit涉及的文件，搜索daemon记录的同类未验证记忆。

    搜索策略（扩大范围，避免跨目录遗漏）:
      1. 文件名作为关键词搜索
      2. 顶层目录名作为补充关键词
      3. 用 tags=["daemon"] 过滤缩小范围
      4. 最终按 source=cognitive-daemon 精确过滤

    Args:
        commit_files: commit涉及的文件路径列表
        cle: 可选的CognitiveLoopEntry实例（避免重复创建）

    Returns:
        daemon记录的记忆列表（source=cognitive-daemon）
    """
    own_cle = False
    if cle is None:
        cle = CognitiveLoopEntry()
        own_cle = True

    try:
        # 收集搜索关键词：文件名 + 顶层目录名
        search_terms = []
        top_dirs = set()
        for f in commit_files[:5]:
            search_terms.append(Path(f).name)
            parts = Path(f).parts
            if parts:
                top_dirs.add(parts[0])
        search_terms.extend(top_dirs)

        query = " ".join(search_terms) if search_terms else "file change"

        # 先用 tags 过滤缩小范围，无结果则回退到无tag过滤
        results = cle.search(query, top_k=15, tags=["daemon"])
        if not results:
            results = cle.search(query, top_k=15, tags=None)

        # 过滤出daemon来源的记忆（source在metadata字段内）
        daemon_memories = []
        for r in results:
            meta = r.get("metadata", {})
            src = str(meta.get("source", "")).lower() if meta else ""
            if src == "cognitive-daemon":
                daemon_memories.append(r)

        return daemon_memories
    finally:
        if own_cle:
            try:
                cle.close()
            except Exception:
                pass


def relay_verify_daemon_memories(
    daemon_memories: List[Dict[str, Any]],
    cle: Any = None,
) -> Dict[str, Any]:
    """
    接力第2步：对daemon记录的记忆执行verify(success=True)。

    git commit是对文件变更的"验证通过"信号——代码变更被commit了，
    说明开发者确认了这些变更是有意义的。因此对daemon记录的记忆执行verify。

    跳过已验证过的记忆（verify_count > 0），避免重复验证。

    Args:
        daemon_memories: daemon记录的记忆列表
        cle: 可选的CognitiveLoopEntry实例

    Returns:
        {
            "verified_count": int,
            "skipped_count": int,
            "memory_ids": List[str],
        }
    """
    if not daemon_memories:
        return {"verified_count": 0, "skipped_count": 0, "memory_ids": []}

    own_cle = False
    if cle is None:
        cle = CognitiveLoopEntry()
        own_cle = True

    verified_ids = []
    skipped_count = 0

    try:
        for mem in daemon_memories:
            mem_id = mem.get("id", "")
            meta = mem.get("metadata", {})
            verify_count = meta.get("verify_count", 0) if meta else 0

            # 跳过已验证的记忆（verify_count > 0）
            if verify_count and verify_count > 0:
                skipped_count += 1
                continue

            # 执行verify（git commit = 验证成功）
            try:
                cle.verify(mem_id, success=True)
                verified_ids.append(mem_id)
            except Exception:
                pass

        return {
            "verified_count": len(verified_ids),
            "skipped_count": skipped_count,
            "memory_ids": verified_ids,
        }
    finally:
        if own_cle:
            try:
                cle.close()
            except Exception:
                pass


def trigger_cognitive_loop(
    commit_info: Dict[str, Any],
    dry_run: bool = False,
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    触发认知闭环：record(经验) → verify(贝叶斯更新) → 接力verify daemon记忆。

    Args:
        commit_info: extract_commit_info()的返回值
        dry_run: 预览模式，不产生副作用
        verbose: 详细输出

    Returns:
        {
            "dry_run": bool,
            "recorded": bool,
            "memory_id": str | None,
            "verified": bool,
            "experience": str,
            "relay_verified": int,  # 接力验证的daemon记忆数
        }
    """
    experience = generate_experience_description(commit_info)
    parsed = _parse_commit_message(commit_info["message"])
    change_type = parsed["type"]

    if dry_run:
        if verbose:
            print(f"[DRY-RUN] 经验: {experience}")
        return {
            "dry_run": True,
            "recorded": False,
            "memory_id": None,
            "verified": False,
            "experience": experience,
            "relay_verified": 0,
        }

    # 调用认知闭环
    cle = CognitiveLoopEntry()

    # Step 1: record — 记录经验
    tags = [change_type, "git-hook"]
    if parsed["scope"]:
        tags.append(parsed["scope"])
    # 从文件路径提取领域标签
    for f in commit_info["files"][:3]:
        parts = Path(f).parts
        if parts:
            tags.append(parts[0])  # 顶层目录名作为标签

    # 质量分级策略（v2）：
    # - 有scope + 有原因说明(body) → B级，confidence=0.5（高质量commit）
    # - 有scope 或 有原因说明 → C级，confidence=0.4
    # - 纯文本commit → C级，confidence=0.3
    if parsed["scope"] and parsed["has_reason"]:
        quality_level = "B"
        confidence = 0.5
    elif parsed["scope"] or parsed["has_reason"]:
        quality_level = "C"
        confidence = 0.4
    else:
        quality_level = "C"
        confidence = 0.3

    memory_id = cle.record(
        content=experience,
        quality_level=quality_level,
        confidence=confidence,
        tags=tags,
        source="git-post-commit",
    )

    # Step 2: verify — 触发贝叶斯更新（git commit视为一次成功验证）
    verify_result = cle.verify(memory_id, success=True)

    if verbose:
        print(f"[认知闭环] 经验已记录: {memory_id}")
        print(f"[认知闭环] 贝叶斯更新完成: {verify_result}")

    # Step 3: 接力verify — 搜索daemon记录的同文件记忆并验证
    daemon_memories = find_daemon_memories_for_files(commit_info["files"], cle=cle)
    relay_result = relay_verify_daemon_memories(daemon_memories, cle=cle)

    if verbose and relay_result["verified_count"] > 0:
        print(f"[接力] 验证了 {relay_result['verified_count']} 条daemon记忆: {relay_result['memory_ids']}")

    # Step 4: 通知session manager — commit触发会话结束，生成解决路径
    # 独立创建session manager实例，不依赖daemon进程
    # __init__时自动从磁盘恢复未结束的会话（跨进程恢复）
    try:
        from cognitive_session import CognitiveSessionManager
        mgr = CognitiveSessionManager()
        mgr.on_commit(commit_info)
    except Exception:
        pass  # 静默失败，不阻塞git hook

    try:
        cle.close()
    except Exception:
        pass

    return {
        "dry_run": False,
        "recorded": True,
        "memory_id": memory_id,
        "verified": True,
        "experience": experience,
        "relay_verified": relay_result["verified_count"],
    }


# ============================================================
# 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="认知触发层 — git hook自动接入")
    parser.add_argument("--post-commit", action="store_true", help="git post-commit hook入口")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不写入记忆")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    args = parser.parse_args()

    if not args.post_commit:
        parser.print_help()
        sys.exit(1)

    try:
        commit_info = extract_commit_info()
        if args.verbose:
            print(f"[触发层] Commit: {commit_info['commit_hash']}")
            print(f"[触发层] Message: {commit_info['message'][:80]}")
            print(f"[触发层] Files: {len(commit_info['files'])}个, "
                  f"+{commit_info['insertions']} -{commit_info['deletions']}")

        result = trigger_cognitive_loop(
            commit_info,
            dry_run=args.dry_run,
            verbose=args.verbose,
        )

        if args.verbose:
            print(f"[触发层] 结果: {json.dumps(result, ensure_ascii=False, indent=2)}")

        # hook静默成功（不阻塞git操作）
        sys.exit(0)

    except Exception as e:
        # hook静默失败（不阻塞git操作）
        if args.verbose:
            print(f"[触发层] 错误: {e}", file=sys.stderr)
        sys.exit(0)  # 始终返回0，不阻塞git


if __name__ == "__main__":
    main()
