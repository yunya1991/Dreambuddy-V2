#!/usr/bin/env python3
"""认知系统飞书告警桥接（设计节 7.6）。

集成 15-监控告警系统/feishu_alert.py，定义认知系统专属告警规则：
  - 触发条件与设计节 6.4 回滚条件一一对应
  - 同 condition + skill_id 10 分钟去重
  - Critical/Warning 两级
"""
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_SCRIPT_DIR = Path(__file__).parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent
_FEISHU_ALERT_DIR = _PROJECT_ROOT / "15-监控告警系统"
if str(_FEISHU_ALERT_DIR) not in sys.path:
    sys.path.insert(0, str(_FEISHU_ALERT_DIR))

# 去重窗口（设计节 7.6）
DEDUP_WINDOW_SECONDS = 600  # 10 分钟
_last_sent: Dict[str, float] = {}


def _build_alert_message(condition: str, level: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """设计节 7.6 告警消息格式（接入 feishu_alert.py 的 interactive card）。"""
    is_critical = level == "Critical"
    emoji = "🔴" if is_critical else "🟡"
    template = "red" if is_critical else "yellow"
    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": f"{emoji} 认知系统告警 · {condition}"},
                "template": template,
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": f"**触发时间**: {datetime.now().isoformat()}"}},
                {"tag": "div", "text": {"tag": "lark_md", "content": f"**触发条件**: {condition}"}},
                {"tag": "div", "text": {"tag": "lark_md",
                    "content": f"**上下文**: ```{json.dumps(context, ensure_ascii=False, indent=2)}```"}},
                {"tag": "div", "text": {"tag": "lark_md",
                    "content": "**建议操作**: 见 superpowers-integration-design.md 附录 D"}},
            ],
        },
    }


def _dedup_key(condition: str, skill_id: Optional[str]) -> str:
    sid = skill_id or "*"
    return f"{condition}:{sid}"


def _should_dedup(condition: str, skill_id: Optional[str], now: float,
                  last_sent: Dict[str, float]) -> bool:
    """设计节 7.6：同 condition + skill_id 10 分钟内只发一次。"""
    key = _dedup_key(condition, skill_id)
    last = last_sent.get(key)
    if last is None:
        return False
    return (now - last) < DEDUP_WINDOW_SECONDS


def _send_via_feishu(message: Dict[str, Any]) -> Dict[str, Any]:
    """调用 15-监控告警系统/feishu_alert.py 发送。"""
    try:
        import feishu_alert  # type: ignore
        if hasattr(feishu_alert, "send_interactive_card"):
            return feishu_alert.send_interactive_card(message)
        elif hasattr(feishu_alert, "send_card"):
            return feishu_alert.send_card(message)
        else:
            logger.warning("feishu_alert 无 send_interactive_card/send_card 方法，仅记录日志")
            return {"status": "logged_only"}
    except ImportError:
        logger.warning("feishu_alert 模块未找到，告警仅记录日志: %s", message["card"]["header"]["title"]["content"])
        return {"status": "logged_only"}


def send_cognitive_alert(
    condition: str,
    level: str,
    context: Dict[str, Any],
    skill_id: Optional[str] = None,
) -> Dict[str, Any]:
    """发送认知系统告警（含去重）。

    Args:
        condition: 触发条件描述（如 "recall 异常率 > 20%"）
        level: "Critical" 或 "Warning"
        context: 上下文数据（写入卡片）
        skill_id: 关联的 Skill ID（用于去重）

    Returns:
        {"sent": bool, "reason": str, ...}
    """
    now = time.time()
    if _should_dedup(condition, skill_id, now, _last_sent):
        logger.info("告警去重跳过: %s (skill=%s)", condition, skill_id)
        return {"sent": False, "reason": "dedup within 10 minutes"}

    message = _build_alert_message(condition, level, context)
    try:
        result = _send_via_feishu(message)
        _last_sent[_dedup_key(condition, skill_id)] = now
        return {"sent": True, "result": result}
    except Exception as e:
        logger.error("飞书告警发送失败: %s: %s", condition, e)
        return {"sent": False, "reason": f"send error: {e}"}
