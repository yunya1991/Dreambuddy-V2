"""GitHub API 适配器 — 获取远程仓库的元数据和源码。

通过 GitHub REST API v3 获取：
- 仓库元数据（语言、star、描述、许可证、topics 等）
- 目录树结构（文件列表 + 类型 + 大小）

设计原则（Evidence-First）：
- 每条结论带 Evidence（provenance + confidence + known_gaps）
- 网络错误降级为 Evidence(level=unknown)
- 无 token 时仍可调用（低 rate limit），标注 known_gaps
- 不修改远程仓库（只读）
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from core.evidence import Evidence

_GITHUB_API_BASE = "https://api.github.com"
_USER_AGENT = "dreambuddy-rea/0.1"


class GitHubApiAdapter:
    """GitHub REST API 客户端。

    Args:
        token: GitHub Personal Access Token（可选）。
                无 token 时仍可调用，但受 60 req/h rate limit 限制。
    """

    def __init__(self, token: str | None = None) -> None:
        self._token = token

    # ------------------------------------------------------------------
    # 公开方法
    # ------------------------------------------------------------------
    def get_repo_metadata(self, owner: str, repo: str) -> dict[str, Any]:
        """获取仓库元数据。

        Returns:
            {
                "name", "full_name", "description", "language",
                "stargazers_count", "forks_count", "open_issues_count",
                "default_branch", "license", "topics",
                "html_url", "created_at", "updated_at",
                "summary", "evidence": [Evidence],
            }
        """
        url = f"{_GITHUB_API_BASE}/repos/{owner}/{repo}"
        evidence: list[Evidence] = []
        known_gaps: list[str] = []
        if not self._token:
            known_gaps.append(
                "无 token，GitHub API rate limit 为 60 req/h，"
                "高频调用可能被限流"
            )

        try:
            data = self._request(url)
            metadata = self._parse_repo_metadata(data)
            metadata["summary"] = (
                f"GitHub 仓库 {owner}/{repo}: "
                f"{data.get('language', '?')} | "
                f"{data.get('stargazers_count', 0)} stars | "
                f"{data.get('forks_count', 0)} forks | "
                f"branch={data.get('default_branch', '?')}"
            )
            evidence.append(Evidence(
                result=f"成功获取 {owner}/{repo} 仓库元数据",
                provenance={
                    "api": "github_rest",
                    "endpoint": url,
                    "engine": "github_api",
                },
                confidence=1.0,
                known_gaps=known_gaps + [
                    "GitHub API 返回的 star/fork 数为请求时刻快照，非实时",
                    "license 字段可能为 null（仓库未声明许可证）",
                ],
                level="observation",
            ))
            metadata["evidence"] = evidence
            return metadata

        except Exception as e:
            error_msg = str(e)
            evidence.append(Evidence(
                result=f"GitHub API 请求失败: {error_msg}",
                provenance={
                    "api": "github_rest",
                    "endpoint": url,
                    "owner": owner,
                    "repo": repo,
                },
                confidence=1.0,
                known_gaps=known_gaps + [
                    "404 可能因仓库不存在或为私有（token 无权限）",
                    "403 可能因 rate limit 耗尽",
                    "无法获取仓库元数据，分析中断",
                ],
                level="unknown",
            ))
            return {
                "summary": f"GitHub API 请求失败: {error_msg}",
                "evidence": evidence,
                "error": error_msg,
            }

    def get_directory_tree(
        self, owner: str, repo: str, path: str = "",
    ) -> dict[str, Any]:
        """获取目录树结构。

        Args:
            owner: 仓库 owner
            repo: 仓库名
            path: 子路径（默认根目录）

        Returns:
            {
                "entries": [{name, type, path, size}],
                "summary", "evidence": [Evidence],
            }
        """
        url = f"{_GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}"
        evidence: list[Evidence] = []
        known_gaps: list[str] = []
        if not self._token:
            known_gaps.append(
                "无 token，GitHub API rate limit 为 60 req/h"
            )

        try:
            data = self._request(url)
            entries = self._parse_contents(data)
            n_dirs = sum(1 for e in entries if e["type"] == "dir")
            n_files = sum(1 for e in entries if e["type"] == "file")
            summary = (
                f"目录 {owner}/{repo}/{path}: "
                f"{n_dirs} 目录, {n_files} 文件"
            )
            evidence.append(Evidence(
                result=f"获取 {owner}/{repo}/{path} 目录结构",
                provenance={
                    "api": "github_rest",
                    "endpoint": url,
                    "engine": "github_api",
                },
                confidence=1.0,
                known_gaps=known_gaps + [
                    "仅返回当前层级，子目录需递归调用",
                    "GitHub API 每页最多 1000 条，超大型目录可能截断",
                    "Symlink 目标未展开",
                ],
                level="observation",
            ))
            return {
                "entries": entries,
                "summary": summary,
                "evidence": evidence,
            }

        except Exception as e:
            error_msg = str(e)
            evidence.append(Evidence(
                result=f"GitHub API 目录请求失败: {error_msg}",
                provenance={
                    "api": "github_rest",
                    "endpoint": url,
                    "owner": owner,
                    "repo": repo,
                    "path": path,
                },
                confidence=1.0,
                known_gaps=known_gaps + [
                    "404 可能因路径不存在或仓库为空",
                    "无法获取目录结构，分析中断",
                ],
                level="unknown",
            ))
            return {
                "entries": [],
                "summary": f"GitHub API 目录请求失败: {error_msg}",
                "evidence": evidence,
                "error": error_msg,
            }

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------
    def _request(self, url: str) -> Any:
        """发起 GitHub REST API GET 请求。

        Raises:
            urllib.error.HTTPError: HTTP 错误（404/403/500 等）
            urllib.error.URLError: 网络错误
        """
        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "application/vnd.github+json",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)

    @staticmethod
    def _parse_repo_metadata(data: dict) -> dict[str, Any]:
        """从 GitHub API 响应提取关键元数据。"""
        license_info = data.get("license")
        return {
            "name": data.get("name", ""),
            "full_name": data.get("full_name", ""),
            "description": data.get("description", ""),
            "language": data.get("language", ""),
            "stargazers_count": data.get("stargazers_count", 0),
            "forks_count": data.get("forks_count", 0),
            "open_issues_count": data.get("open_issues_count", 0),
            "default_branch": data.get("default_branch", ""),
            "license": license_info.get("name") if license_info else None,
            "topics": data.get("topics", []),
            "html_url": data.get("html_url", ""),
            "created_at": data.get("created_at", ""),
            "updated_at": data.get("updated_at", ""),
        }

    @staticmethod
    def _parse_contents(data: Any) -> list[dict[str, Any]]:
        """从 GitHub API contents 响应提取文件列表。

        GitHub contents API 可能返回单个对象（文件）或数组（目录）。
        """
        if isinstance(data, list):
            entries: list[dict[str, Any]] = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                entries.append({
                    "name": item.get("name", ""),
                    "type": item.get("type", "file"),
                    "path": item.get("path", ""),
                    "size": item.get("size", 0),
                })
            return entries
        elif isinstance(data, dict) and data.get("type") == "file":
            return [{
                "name": data.get("name", ""),
                "type": "file",
                "path": data.get("path", ""),
                "size": data.get("size", 0),
            }]
        return []
