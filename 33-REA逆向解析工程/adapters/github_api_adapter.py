"""GitHub API 适配器 — 获取远程仓库的元数据和源码。"""

from __future__ import annotations


class GitHubApiAdapter:
    """GitHub REST API 客户端。"""

    def __init__(self, token: str | None = None) -> None:
        self._token = token

    def get_repo_metadata(self, owner: str, repo: str) -> dict:
        """获取仓库元数据（语言、star、描述等）。"""
        # TODO: 调用 GET /repos/{owner}/{repo}
        raise NotImplementedError

    def get_directory_tree(self, owner: str, repo: str, path: str = "") -> list[dict]:
        """获取目录树结构。"""
        # TODO: 调用 GET /repos/{owner}/{repo}/contents/{path}
        raise NotImplementedError
