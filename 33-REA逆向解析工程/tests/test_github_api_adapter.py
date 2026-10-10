"""RED 测试：GitHubApiAdapter — GitHub REST API 适配器。

测试策略：使用 mock 避免真实网络调用，验证 API 解析逻辑和 Evidence 输出。
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from adapters.github_api_adapter import GitHubApiAdapter
from core.evidence import Evidence


MOCK_REPO_RESPONSE = {
    "id": 123456789,
    "name": "freqtrade",
    "full_name": "freqtrade/freqtrade",
    "description": "Free, open source crypto trading bot",
    "language": "Python",
    "stargazers_count": 5000,
    "forks_count": 1500,
    "open_issues_count": 200,
    "default_branch": "main",
    "license": {"name": "GPL-3.0"},
    "topics": ["trading", "crypto", "bot"],
    "created_at": "2019-01-01T00:00:00Z",
    "updated_at": "2026-01-01T00:00:00Z",
    "html_url": "https://github.com/freqtrade/freqtrade",
}


MOCK_CONTENTS_RESPONSE = [
    {"name": "src", "type": "dir", "path": "src"},
    {"name": "README.md", "type": "file", "path": "README.md", "size": 5000},
    {"name": "setup.py", "type": "file", "path": "setup.py", "size": 1000},
    {"name": "tests", "type": "dir", "path": "tests"},
]


def test_github_adapter_get_repo_metadata():
    """RED: 应获取远程仓库元数据。"""
    adapter = GitHubApiAdapter(token="fake_token")

    with patch.object(adapter, "_request") as mock_req:
        mock_req.return_value = MOCK_REPO_RESPONSE
        result = adapter.get_repo_metadata("freqtrade", "freqtrade")

    assert result["name"] == "freqtrade"
    assert result["language"] == "Python"
    assert result["stargazers_count"] == 5000


def test_github_adapter_metadata_returns_evidence():
    """RED: get_repo_metadata 应返回 Evidence 列表。"""
    adapter = GitHubApiAdapter(token="fake_token")

    with patch.object(adapter, "_request") as mock_req:
        mock_req.return_value = MOCK_REPO_RESPONSE
        result = adapter.get_repo_metadata("freqtrade", "freqtrade")

    assert "evidence" in result
    assert len(result["evidence"]) > 0
    e = result["evidence"][0]
    assert isinstance(e, Evidence)
    assert e.provenance is not None
    assert 0.0 <= e.confidence <= 1.0
    assert isinstance(e.known_gaps, list)


def test_github_adapter_get_directory_tree():
    """RED: 应获取远程仓库目录树。"""
    adapter = GitHubApiAdapter(token="fake_token")

    with patch.object(adapter, "_request") as mock_req:
        mock_req.return_value = MOCK_CONTENTS_RESPONSE
        result = adapter.get_directory_tree("freqtrade", "freqtrade", "")

    assert isinstance(result, dict) or isinstance(result, list)
    if isinstance(result, dict):
        entries = result.get("entries", [])
    else:
        entries = result
    names = [e.get("name") for e in entries]
    assert "src" in names
    assert "README.md" in names
    assert "setup.py" in names


def test_github_adapter_directory_tree_returns_evidence():
    """RED: get_directory_tree 应返回 Evidence 列表。"""
    adapter = GitHubApiAdapter(token="fake_token")

    with patch.object(adapter, "_request") as mock_req:
        mock_req.return_value = MOCK_CONTENTS_RESPONSE
        result = adapter.get_directory_tree("freqtrade", "freqtrade", "")

    assert "evidence" in result
    assert len(result["evidence"]) > 0


def test_github_adapter_handles_404():
    """RED: 404 应降级返回 + Evidence 标注未知。"""
    adapter = GitHubApiAdapter(token="fake_token")

    with patch.object(adapter, "_request") as mock_req:
        mock_req.side_effect = Exception("HTTP 404: Not Found")
        result = adapter.get_repo_metadata("nonexistent", "repo")

    assert "evidence" in result
    assert len(result["evidence"]) > 0
    # 错误应以 Evidence 标注为 unknown 或 observation
    has_error_evidence = any(
        "404" in str(e.result) or "not found" in str(e.result).lower()
        for e in result["evidence"]
    )
    assert has_error_evidence


def test_github_adapter_handles_no_token():
    """RED: 无 token 应仍可调用（低 rate limit），并标注 known_gaps。"""
    adapter = GitHubApiAdapter(token=None)

    with patch.object(adapter, "_request") as mock_req:
        mock_req.return_value = MOCK_REPO_RESPONSE
        result = adapter.get_repo_metadata("freqtrade", "freqtrade")

    assert result["name"] == "freqtrade"
    all_gaps = []
    for e in result.get("evidence", []):
        all_gaps.extend(e.known_gaps)
    # 无 token 时应有 rate limit 相关的 known_gap
    assert any("rate" in g.lower() or "limit" in g.lower() for g in all_gaps)


def test_github_adapter_get_repo_summary():
    """RED: 应返回可读摘要。"""
    adapter = GitHubApiAdapter(token="fake_token")

    with patch.object(adapter, "_request") as mock_req:
        mock_req.return_value = MOCK_REPO_RESPONSE
        result = adapter.get_repo_metadata("freqtrade", "freqtrade")

    assert "summary" in result
    assert len(result["summary"]) > 0


def test_github_adapter_directory_tree_summary():
    """RED: get_directory_tree 应返回摘要。"""
    adapter = GitHubApiAdapter(token="fake_token")

    with patch.object(adapter, "_request") as mock_req:
        mock_req.return_value = MOCK_CONTENTS_RESPONSE
        result = adapter.get_directory_tree("freqtrade", "freqtrade", "")

    assert "summary" in result
    assert len(result["summary"]) > 0
