"""RED 测试：CognitiveIntegration — 认知记忆集成。

测试策略：验证分析结果到认知记忆的格式转换和 record 参数准备。
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.cognitive_integration import (
    prepare_memory_content,
    prepare_record_params,
    CognitiveIntegration,
)
from core.investigation_workflow import investigate


def _get_sample_investigation():
    """获取一个样本调查结果用于测试。"""
    with tempfile.TemporaryDirectory() as d:
        Path(os.path.join(d, "main.py")).write_text(
            "def main():\n    return 42\n"
        )
        result = investigate(d)
    return result


def test_prepare_memory_content_returns_string():
    """RED: 应返回字符串内容。"""
    investigation = _get_sample_investigation()
    content = prepare_memory_content(investigation)
    assert isinstance(content, str)
    assert len(content) > 0


def test_prepare_memory_content_includes_target():
    """RED: 内容应包含目标信息。"""
    investigation = _get_sample_investigation()
    content = prepare_memory_content(investigation)
    assert investigation["target"] in content or "target" in content.lower()


def test_prepare_memory_content_includes_summary():
    """RED: 内容应包含摘要。"""
    investigation = _get_sample_investigation()
    content = prepare_memory_content(investigation)
    # 摘要或关键词应出现在内容中
    assert len(investigation.get("summary", "")) == 0 or investigation["summary"] in content


def test_prepare_record_params_returns_dict():
    """RED: 应返回 record 参数字典。"""
    investigation = _get_sample_investigation()
    params = prepare_record_params(investigation)
    assert isinstance(params, dict)
    assert "content" in params
    assert "quality_level" in params
    assert "tags" in params


def test_prepare_record_params_quality_level():
    """RED: quality_level 应为 B 或 C。"""
    investigation = _get_sample_investigation()
    params = prepare_record_params(investigation)
    assert params["quality_level"] in ("B", "C")


def test_prepare_record_params_tags_includes_rea():
    """RED: tags 应包含 33-REA 相关标签。"""
    investigation = _get_sample_investigation()
    params = prepare_record_params(investigation)
    tags = params["tags"]
    if isinstance(tags, str):
        tag_list = tags.split(",")
    else:
        tag_list = tags
    assert any("REA" in t or "逆向" in t for t in tag_list)


def test_cognitive_integration_class():
    """RED: CognitiveIntegration 类应可用。"""
    with tempfile.TemporaryDirectory() as d:
        Path(os.path.join(d, "main.py")).write_text(
            "def main():\n    return 42\n"
        )
        investigation = investigate(d)
        ci = CognitiveIntegration()
        params = ci.to_record_params(investigation)

    assert isinstance(params, dict)
    assert "content" in params
    assert "tags" in params


def test_cognitive_integration_includes_evidence_count():
    """RED: 记忆内容应包含 Evidence 数量。"""
    investigation = _get_sample_investigation()
    content = prepare_memory_content(investigation)
    assert "evidence" in content.lower() or "证据" in content


def test_cognitive_integration_includes_known_gaps():
    """RED: 记忆内容应包含 known_gaps 信息。"""
    investigation = _get_sample_investigation()
    content = prepare_memory_content(investigation)
    assert "gap" in content.lower() or "局限" in content or "未知" in content


def test_cognitive_integration_includes_phases():
    """RED: 记忆内容应包含四阶段信息。"""
    investigation = _get_sample_investigation()
    content = prepare_memory_content(investigation)
    # 应提及至少一个阶段
    assert any(
        phase in content.lower()
        for phase in ("locate", "trace", "reduce", "annotate",
                       "定位", "追踪", "还原", "标注")
    )
