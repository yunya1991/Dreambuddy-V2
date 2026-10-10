"""RED 测试：ReaMcpAdapter — morluto/rea MCP 适配器。

测试策略：mock subprocess + shutil.which，避免依赖真实 rea 安装。
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from adapters.rea_mcp_adapter import ReaMcpAdapter
from core.evidence import Evidence


def test_rea_adapter_not_available():
    """RED: rea 未安装时 is_available 返回 False。"""
    with patch("shutil.which", return_value=None):
        adapter = ReaMcpAdapter()
        assert adapter.is_available() is False


def test_rea_adapter_available_when_rea_exists():
    """RED: rea 安装时 is_available 返回 True。"""
    with patch("shutil.which", return_value="/usr/local/bin/rea"):
        adapter = ReaMcpAdapter()
        assert adapter.is_available() is True


def test_rea_adapter_analyze_binary_not_available():
    """RED: rea 未安装时 analyze_native_binary 返回降级 + Evidence。"""
    with patch("shutil.which", return_value=None):
        adapter = ReaMcpAdapter()
        result = adapter.analyze_native_binary("/path/to/binary")

    assert isinstance(result, dict)
    assert "evidence" in result
    assert len(result["evidence"]) > 0
    e = result["evidence"][0]
    assert isinstance(e, Evidence)
    # 未安装时应标注 unknown 或有 known_gaps 说明
    assert e.level in ("unknown", "observation")


def test_rea_adapter_analyze_binary_returns_metadata():
    """RED: rea 可用时 analyze_native_binary 应返回分析结果。"""
    with patch("shutil.which", return_value="/usr/local/bin/rea"):
        adapter = ReaMcpAdapter()

        with patch.object(adapter, "_call_mcp") as mock_mcp:
            mock_mcp.return_value = {
                "functions": [
                    {"name": "main", "address": "0x1000"},
                    {"name": "helper", "address": "0x2000"},
                ],
                "sections": [".text", ".data"],
            }
            result = adapter.analyze_native_binary("/path/to/binary")

    assert "functions" in result
    assert len(result["functions"]) >= 2
    assert any(f["name"] == "main" for f in result["functions"])


def test_rea_adapter_analyze_binary_returns_evidence():
    """RED: analyze_native_binary 应返回 Evidence 列表。"""
    with patch("shutil.which", return_value="/usr/local/bin/rea"):
        adapter = ReaMcpAdapter()

        with patch.object(adapter, "_call_mcp") as mock_mcp:
            mock_mcp.return_value = {
                "functions": [{"name": "main", "address": "0x1000"}],
                "sections": [".text"],
            }
            result = adapter.analyze_native_binary("/path/to/binary")

    assert "evidence" in result
    assert len(result["evidence"]) > 0
    e = result["evidence"][0]
    assert isinstance(e, Evidence)
    assert e.provenance is not None
    assert 0.0 <= e.confidence <= 1.0
    assert isinstance(e.known_gaps, list)


def test_rea_adapter_summary():
    """RED: analyze_native_binary 应返回摘要。"""
    with patch("shutil.which", return_value="/usr/local/bin/rea"):
        adapter = ReaMcpAdapter()

        with patch.object(adapter, "_call_mcp") as mock_mcp:
            mock_mcp.return_value = {
                "functions": [{"name": "main"}],
                "sections": [".text"],
            }
            result = adapter.analyze_native_binary("/path/to/binary")

    assert "summary" in result
    assert len(result["summary"]) > 0


def test_rea_adapter_known_gaps_for_binary_analysis():
    """RED: Evidence 应标注二进制分析的已知局限。"""
    with patch("shutil.which", return_value="/usr/local/bin/rea"):
        adapter = ReaMcpAdapter()

        with patch.object(adapter, "_call_mcp") as mock_mcp:
            mock_mcp.return_value = {
                "functions": [{"name": "main"}],
                "sections": [".text"],
            }
            result = adapter.analyze_native_binary("/path/to/binary")

    all_gaps = []
    for e in result["evidence"]:
        all_gaps.extend(e.known_gaps)
    # 应有关于反编译/二进制分析的局限说明
    assert len(all_gaps) > 0


def test_rea_adapter_provider_selection():
    """RED: analyze_native_binary 支持 provider 参数。"""
    with patch("shutil.which", return_value="/usr/local/bin/rea"):
        adapter = ReaMcpAdapter()

        with patch.object(adapter, "_call_mcp") as mock_mcp:
            mock_mcp.return_value = {
                "functions": [],
                "sections": [],
            }
            adapter.analyze_native_binary("/path/to/binary", provider="ghidra")
            adapter.analyze_native_binary("/path/to/binary", provider="hopper")

    # 验证 _call_mcp 被调用了两次（不同 provider）
    assert mock_mcp.call_count == 2
