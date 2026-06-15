#!/usr/bin/env python3
"""
A系列产物双通道投递模块 v1.0
============================
所有 A 系列任务完成后统一调用此模块，实现：
  通道1: 飞书群消息推送（复用 feishu_notify.py 基础设施）
  通道2: 6-TRADING 本地产物归档

用法:
  from a_product_delivery import deliver_product

  deliver_product(
      phase="A9",
      title="A9 离场检查 - BTC-USDT-SWAP",
      summary="HOLD - 无触发信号，继续持有",
      detail={"decision": "HOLD", "layers": {...}},
      channels=["management", "review"],  # 飞书群组
      status="completed"
  )
"""

import json
import os
import sys
import requests
from datetime import datetime
from pathlib import Path

SEP = "=" * 60

# ── 配置 ──────────────────────────────────────────────────────────────────────
TRADING_DIR = Path("/home/ubuntu/archives/Dreambuddy-V2-main/6-TRADING")
ARTIFACTS_DIR = TRADING_DIR / "artifacts"

# 飞书凭证（与 feishu_notify.py 共享）
FEISHU_APP_ID = "cli_aa95b2dee3b85bd1"
FEISHU_APP_SECRET = "Za5TKURjkVlly5op9BGoic6620sXhemI"

# 飞书群组映射
FEISHU_CHANNELS = {
    "research":   "oc_36c575b6f39a8df3dd75057a96685a21",
    "trading":    "oc_36c8543cea823b7546fcaad55d111f9f",
    "management": "oc_9cf9f141613b4e6a0f34651843cf8b9b",
    "review":     "oc_8868a5c84f3d8427afa9ed1a9ad7fb76",
    "risk":       "oc_20fcedf0c35035568ea8fa947380f75d",
}

# A系列默认投递路由
A_PHASE_ROUTES = {
    "A1": ["research", "management"],
    "A2": ["research", "management"],
    "A3": ["research", "management"],
    "A4": ["research", "review"],
    "A5": ["trading", "management"],
    "A6": ["trading", "risk"],
    "A7": ["review"],
    "A8": ["research", "review"],
    "A9": ["management", "review", "trading"],
    "v15": ["trading"],
}

STATUS_EMOJI = {
    "completed": "✅", "success": "✅", "hold": "⏸️",
    "warning": "⚠️", "error": "❌", "alert": "🚨",
    "long": "📈", "short": "📉",
}

PHASE_EMOJI = {
    "A1": "🔍", "A2": "🧠", "A3": "🎯", "A4": "🔬",
    "A5": "⚡", "A6": "📡", "A7": "📘", "A8": "🔎",
    "A9": "🚪", "v15": "📊",
}

TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
MSG_URL = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"


# ── 飞书通道 ──────────────────────────────────────────────────────────────────
def _get_feishu_token():
    try:
        resp = requests.post(TOKEN_URL, json={
            "app_id": FEISHU_APP_ID,
            "app_secret": FEISHU_APP_SECRET,
        }, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data["code"] != 0:
            raise RuntimeError("飞书 token 获取失败: " + str(data))
        return data["tenant_access_token"]
    except Exception as e:
        print("[投递-飞书] ⚠️ Token 获取失败: " + str(e))
        return ""


def _send_feishu_card(chat_id, title, content_lines, color="blue", footer=""):
    token = _get_feishu_token()
    if not token:
        return {"error": "no token"}

    elements = [{"tag": "div", "text": {"tag": "lark_md", "content": content_lines[0]}}]
    for line in content_lines[1:]:
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": line}})

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": color,
        },
        "elements": elements,
    }
    if footer:
        elements.append({"tag": "hr"})
        elements.append({"tag": "note", "elements": [{
            "tag": "plain_text", "content": footer
        }]})

    resp = requests.post(MSG_URL, headers={
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
    }, json={
        "receive_id": chat_id,
        "msg_type": "interactive",
        "content": json.dumps(card, ensure_ascii=False),
    }, timeout=10)

    if resp.status_code == 200:
        result = resp.json()
        if result.get("code") == 0:
            print("[投递-飞书] ✅ -> " + chat_id[:8] + "...")
            return result
        else:
            print("[投递-飞书] ❌ -> " + str(result))
            return result
    else:
        print("[投递-飞书] ❌ HTTP " + str(resp.status_code) + ": " + resp.text[:200])
        return {"error": "HTTP " + str(resp.status_code)}


def _build_feishu_message(phase, title, summary, detail, status):
    emoji = PHASE_EMOJI.get(phase, "📋")
    status_emoji = STATUS_EMOJI.get(status.lower(), "📋")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    header = emoji + " **" + title + "**\n" + status_emoji + " 状态: " + status + " | " + ts

    body_lines = ["📝 " + summary]

    if detail:
        metrics = []
        for k, v in detail.items():
            if k in ("summary", "description", "note", "message"):
                continue
            if isinstance(v, (str, int, float, bool)):
                label = {"decision": "决策", "signal": "信号", "confidence": "置信度",
                         "direction": "方向", "entry_price": "入场价",
                         "exit_price": "出场价", "pnl": "盈亏",
                         "regime": "市场状态", "layer1": "技术层",
                         "layer2": "风险层", "layer3": "情报层",
                         "layer4": "审计层"}.get(k, k)
                metrics.append("• " + label + ": " + str(v))
            elif isinstance(v, dict) and k.startswith("layer"):
                layer_status = v.get("status", v.get("decision", "N/A"))
                metrics.append("• " + k + ": " + str(layer_status))
        if metrics:
            body_lines.append("")
            body_lines.append("**关键指标:**")
            body_lines.extend(metrics)

    footer = "📂 产物来源: " + phase + " | 双通道投递系统 v1.0"

    color_map = {
        "completed": "blue", "success": "green", "hold": "blue",
        "warning": "orange", "error": "red", "alert": "red",
        "long": "green", "short": "red",
    }
    color = color_map.get(status.lower(), "blue")

    return header, body_lines, color, footer


# ── 本地通道 ──────────────────────────────────────────────────────────────────
def _save_local_artifact(phase, title, summary, detail, status):
    phase_dir = ARTIFACTS_DIR / phase.lower()
    phase_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = phase.lower() + "_" + ts

    payload = {
        "phase": phase,
        "title": title,
        "summary": summary,
        "detail": detail,
        "status": status,
        "timestamp": datetime.now().isoformat(),
        "delivery_channels": ["local", "feishu"],
    }

    # JSON
    json_path = phase_dir / (filename + ".json")
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print("[投递-本地] ✅ JSON -> " + str(json_path))

    # Markdown
    md_content = _generate_md_report(phase, title, summary, detail, status)
    md_path = phase_dir / (filename + ".md")
    md_path.write_text(md_content)
    print("[投递-本地] ✅ MD   -> " + str(md_path))

    # Update latest
    _update_latest(phase, payload, json_path)

    # Update phase index
    _update_phase_index(phase, filename, payload)

    return {"json": str(json_path), "md": str(md_path)}


def _generate_md_report(phase, title, summary, detail, status):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "# " + title,
        "",
        "| 项目 | 内容 |",
        "|:---|:---|",
        "| **阶段** | " + phase + " |",
        "| **状态** | status |",
        "| **时间** | " + ts + " |",
        "",
        "## 摘要",
        "",
        summary,
        "",
    ]
    # Fix status line
    lines[5] = "| **状态** | " + status + " |"

    if detail:
        lines.append("## 详细数据")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(detail, indent=2, ensure_ascii=False))
        lines.append("```")
        lines.append("")

    lines.append("---")
    lines.append("*双通道投递系统 v1.0 | 自动生成*")
    return "\n".join(lines)


def _update_latest(phase, payload, json_path):
    phase_dir = ARTIFACTS_DIR / phase.lower()
    phase_dir.mkdir(parents=True, exist_ok=True)

    latest_json = phase_dir / "latest.json"
    latest_md = phase_dir / "latest.md"

    latest_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    md_files = sorted(phase_dir.glob("*.md"))
    if md_files:
        latest_md_file = md_files[-1]
        if latest_md.exists() or latest_md.is_symlink():
            latest_md.unlink()
        os.symlink(str(latest_md_file), str(latest_md))
        print("[投递-本地] 📎 latest.md -> " + latest_md_file.name)


def _update_phase_index(phase, filename, payload):
    phase_dir = ARTIFACTS_DIR / phase.lower()
    index_path = phase_dir / "index.json"

    if index_path.exists():
        try:
            index_data = json.loads(index_path.read_text())
        except Exception:
            index_data = {"phase": phase, "entries": []}
    else:
        index_data = {"phase": phase, "entries": []}

    entry = {
        "filename": filename,
        "title": payload["title"],
        "status": payload["status"],
        "timestamp": payload["timestamp"],
    }
    index_data["entries"].append(entry)
    index_data["entries"] = index_data["entries"][-100:]
    index_data["latest"] = filename
    index_data["updated_at"] = datetime.now().isoformat()

    index_path.write_text(json.dumps(index_data, indent=2, ensure_ascii=False))
    print("[投递-本地] 📋 index.json 已更新")


# ── 统一投递入口 ──────────────────────────────────────────────────────────────
def deliver_product(phase, title, summary, detail=None, channels=None, status="completed"):
    """
    双通道产物投递入口 - 所有 A 系列任务统一调用

    Args:
        phase:    A系列阶段标识 (A1, A4, A5, A6, A9, v15, ...)
        title:    产物标题
        summary:  一句话摘要
        detail:   详细数据 dict（可选）
        channels: 飞书群组列表 ["management", "trading", ...]
                  不传则按 A_PHASE_ROUTES 自动路由
        status:   状态标识 completed/hold/warning/error/long/short
    """
    if detail is None:
        detail = {}

    print("\n" + SEP)
    print("📦 产物投递 [" + phase + "] " + title)
    print(SEP)

    # ── 通道1: 本地归档（始终执行）───
    try:
        local_result = _save_local_artifact(phase, title, summary, detail, status)
    except Exception as e:
        print("[投递-本地] ❌ 失败: " + str(e))
        local_result = {"error": str(e)}

    # ── 通道2: 飞书推送 ──
    try:
        if channels is None:
            channels = A_PHASE_ROUTES.get(phase, ["management"])

        header, body_lines, color, footer = _build_feishu_message(
            phase, title, summary, detail, status
        )

        for ch in channels:
            chat_id = FEISHU_CHANNELS.get(ch)
            if not chat_id:
                print("[投递-飞书] ⚠️ 未知群组: " + ch)
                continue
            _send_feishu_card(chat_id, header, body_lines, color, footer)
    except Exception as e:
        print("[投递-飞书] ❌ 失败: " + str(e))

    print(SEP)
    print("✅ 投递完成 [" + phase + "]")
    print(SEP + "\n")

    return {"local": local_result, "channels": channels}


# ── 独立调用测试 ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python3 a_product_delivery.py <phase> <title> [summary]")
        print("示例: python3 a_product_delivery.py A9 'A9 离场检查' 'HOLD 继续持有'")
        sys.exit(1)

    phase = sys.argv[1]
    title = sys.argv[2]
    summary = sys.argv[3] if len(sys.argv) > 3 else "产物已生成"

    deliver_product(phase=phase, title=title, summary=summary)
