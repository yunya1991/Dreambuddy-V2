"""alert_bridge 飞书告警桥接单测（设计节 7.6）。"""
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))
from alert_bridge import send_cognitive_alert, _build_alert_message, _should_dedup


def test_build_alert_message_critical():
    msg = _build_alert_message(
        condition="认知系统崩溃",
        level="Critical",
        context={"daemon_pid": 12345, "last_log": "OOM"},
    )
    assert msg["msg_type"] == "interactive"
    card = msg["card"]
    assert card["header"]["template"] == "red"
    assert "认知系统崩溃" in card["header"]["title"]["content"]
    assert "🔴" in card["header"]["title"]["content"]


def test_build_alert_message_warning():
    msg = _build_alert_message(
        condition="path_advantage 退化",
        level="Warning",
        context={"skill_id": "tdd", "score": -0.3},
    )
    assert msg["card"]["header"]["template"] == "yellow"
    assert "🟡" in msg["card"]["header"]["title"]["content"]


def test_should_dedup_within_10_minutes():
    """设计节 7.6：同 condition + skill_id 10 分钟内只发一次。"""
    now = time.time()
    assert _should_dedup("条件A", "tdd", now, last_sent={"条件A:tdd": now - 60}) is True
    assert _should_dedup("条件A", "tdd", now, last_sent={"条件A:tdd": now - 700}) is False
    assert _should_dedup("条件A", "debug", now, last_sent={"条件A:tdd": now - 60}) is False


def test_send_cognitive_alert_calls_feishu():
    """告警应调用 feishu_alert 发送。"""
    with patch("alert_bridge._send_via_feishu") as mock_send:
        mock_send.return_value = {"status": "ok"}
        result = send_cognitive_alert(
            condition="recall 异常率 > 20%",
            level="Critical",
            context={"error_rate": 0.25, "samples": ["e1", "e2"]},
        )
        assert result["sent"] is True
        mock_send.assert_called_once()


def test_send_cognitive_alert_dedup_skips():
    """10 分钟内重复告警应跳过。"""
    import alert_bridge
    # 重置去重表，避免受其它用例影响
    alert_bridge._last_sent.clear()
    with patch("alert_bridge._send_via_feishu") as mock_send:
        mock_send.return_value = {"status": "ok"}
        # 第一次发送
        send_cognitive_alert(condition="条件B", level="Warning", context={"skill_id": "tdd"})
        # 第二次应被去重
        result = send_cognitive_alert(condition="条件B", level="Warning", context={"skill_id": "tdd"})
        assert result["sent"] is False
        assert "dedup" in result.get("reason", "").lower()
        # 只调用了一次
        assert mock_send.call_count == 1
    alert_bridge._last_sent.clear()
