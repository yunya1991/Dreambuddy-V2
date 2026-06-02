#!/usr/bin/env python3
"""
飞书通知推送模块 - Dreambuddy-V2 6-TRADING
用法:
  python feishu_notify.py screen1 <session_dir>
  python feishu_notify.py screen1 6-TRADING/sessions/20260602-BTC-SCREEN1
"""
import json
import sys
import os
import requests
from datetime import datetime
from pathlib import Path

# ── 配置 ────────────────────────────────────────────────────────────────────
FEISHU_APP_ID     = "cli_aa9442bde4b89be9"
FEISHU_APP_SECRET = "dnHO43AQ68jua7Z8XEAQ3gJwNoMeYQ70"

CHAT_IDS = {
    "screen1":   "oc_98f080b50e2ac52634e3f1f18d118efe",
    "screen2":   "",   # 待填
    "execution": "",   # 待填
    "review":    "",   # 待填
}

TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
MSG_URL   = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"

# ── Token ────────────────────────────────────────────────────────────────────
def get_token() -> str:
    resp = requests.post(TOKEN_URL, json={
        "app_id": FEISHU_APP_ID,
        "app_secret": FEISHU_APP_SECRET,
    }, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data["code"] != 0:
        raise RuntimeError(f"飞书token获取失败: {data}")
    return data["tenant_access_token"]


def send_message(chat_id: str, msg_type: str, content: dict) -> dict:
    token = get_token()
    resp = requests.post(MSG_URL, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }, json={
        "receive_id": chat_id,
        "msg_type": msg_type,
        "content": json.dumps(content),
    }, timeout=10)
    resp.raise_for_status()
    result = resp.json()
    if result["code"] != 0:
        raise RuntimeError(f"发送失败: {result}")
    return result

# ── Signal / Direction 样式 ───────────────────────────────────────────────────
SIGNAL_EMOJI = {"BULL": "🟢", "BEAR": "🔴", "NEUTRAL": "🟡"}
DIR_EMOJI    = {"LONG": "📈", "SHORT": "📉"}

def score_bar(score: int, total: int = 100) -> str:
    filled = max(0, min(10, round(abs(score) / total * 10)))
    bar = "█" * filled + "░" * (10 - filled)
    return f"[{bar}] {score:+d}"

# ── Screen1 卡片 ──────────────────────────────────────────────────────────────
def build_screen1_card(session_dir: str) -> dict:
    base = Path(session_dir)
    meta_path     = base / "meta.json"
    strategy_path = base / "team-a" / "screen1" / "strategy-type.json"
    raw_dir       = base / "team-a" / "screen1" / "raw"

    meta     = json.loads(meta_path.read_text(encoding="utf-8"))
    strategy = json.loads(strategy_path.read_text(encoding="utf-8"))

    session_id = meta.get("session_id", "UNKNOWN")
    score      = strategy.get("weighted_total", strategy.get("score", 0))
    direction  = strategy.get("direction", "?")
    regime     = strategy.get("skill_regime", "?")
    clock      = strategy.get("clock_stage", "?")
    price      = meta.get("screen1_price", 0)
    valid_until = strategy.get("valid_until", meta.get("valid_until", "?"))
    vm         = strategy.get("position_multiplier", meta.get("position_multiplier", "?"))

    # 维度分
    cb = strategy.get("confidence_breakdown", {})
    dim_lines = []
    dim_map = {
        "A_tech_detector":   ("技术检测器", "40%"),
        "B_halving_cycle":   ("减半周期",   "15%"),
        "C_miner_economics": ("矿工经济",   "15%"),
        "D_onchain_valuation":("链上估值",  "15%"),
        "E_macro_finance":   ("宏观金融",   "10%"),
        "F_cross_market":    ("跨市场",     "5%"),
    }
    for key, (name, weight) in dim_map.items():
        if key in cb:
            d = cb[key]
            sig   = d.get("signal", "?")
            s     = d.get("score", 0)
            emoji = SIGNAL_EMOJI.get(sig, "⚪")
            dim_lines.append(f"{emoji} **{name}**({weight})  {s:+d}")

    # 配置
    alloc = strategy.get("allocation", {})
    alloc_text = "  ".join([f"{k} {v}" for k, v in alloc.items()]) if alloc else "—"

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    dir_emoji = DIR_EMOJI.get(direction, "")

    # 飞书卡片 JSON (card kit v2)
    card = {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"📊 Screen1 周线研判 — {session_id}"
            },
            "template": "red" if direction == "SHORT" else "green"
        },
        "body": {
            "elements": [
                {
                    "tag": "markdown",
                    "content": (
                        f"**方向** {dir_emoji} `{direction}`　"
                        f"**总分** `{score}/100`　"
                        f"**制度** `{regime}`\n"
                        f"**价格** `${price:,}`　"
                        f"**象限** `{clock}`　"
                        f"**仓位乘数** `{vm}`"
                    )
                },
                {"tag": "hr"},
                {
                    "tag": "markdown",
                    "content": "**七维度信号**\n" + "\n".join(dim_lines)
                },
                {"tag": "hr"},
                {
                    "tag": "markdown",
                    "content": f"**配置**  {alloc_text}\n**有效期至** `{valid_until}`"
                },
                {"tag": "hr"},
                {
                    "tag": "markdown",
                    "content": f"*生成时间: {now_str} | [GitHub]"
                               f"(https://github.com/yunya1991/Dreambuddy-V2/tree/main/"
                               f"6-TRADING/sessions/{session_id})*"
                }
            ]
        }
    }
    return card


# ── 主入口 ────────────────────────────────────────────────────────────────────
def notify_screen1(session_dir: str):
    chat_id = CHAT_IDS["screen1"]
    if not chat_id:
        raise ValueError("screen1 chat_id 未配置")

    card = build_screen1_card(session_dir)
    result = send_message(chat_id, "interactive", card)
    msg_id = result['data']['message_id']
    print(f"[OK] Screen1 Feishu notify sent: {msg_id}")
    return result


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python feishu_notify.py <type> <session_dir>")
        print("示例: python feishu_notify.py screen1 ../sessions/20260602-BTC-SCREEN1")
        sys.exit(1)

    notify_type  = sys.argv[1]
    session_path = sys.argv[2]

    # 支持相对路径（相对于仓库根目录）
    if not os.path.isabs(session_path):
        base = Path(__file__).parent.parent.parent  # Dreambuddy-V2/
        session_path = str(base / session_path)

    if notify_type == "screen1":
        notify_screen1(session_path)
    else:
        print(f"未知类型: {notify_type}，目前支持: screen1")
        sys.exit(1)
