#!/usr/bin/env python3
"""6-TRADING Feishu Group Poller v2 — REST API polling → pending file → Agent handles"""
import json, os, time, requests
from datetime import datetime
from pathlib import Path

DOMAIN = "open.feishu.cn"
BOT_OPEN_ID = "ou_bcf92b6057e502054ca32bcd8ebf6570"

WATCHED_GROUPS = [
    {"id": "oc_36c575b6f39a8df3dd75057a96685a21", "name": "Trading-Research"},
    {"id": "oc_36c8543cea823b7546fcaad55d111f9f", "name": "Trading-Desk"},
    {"id": "oc_9cf9f141613b4e6a0f34651843cf8b9b", "name": "Trading-Management"},
    {"id": "oc_8868a5c84f3d8427afa9ed1a9ad7fb76", "name": "Trading-Review"},
    {"id": "oc_20fcedf0c35035568ea8fa947380f75d", "name": "Trading-RiskControl"},
]

POLL_INTERVAL = 12
STATE_FILE = Path(os.path.expanduser("~/.hermes/feishu_poller_state.json"))
PENDING_FILE = Path(os.path.expanduser("~/.hermes/pending_group_mentions.jsonl"))
seen_ids = set()


def _env():
    p = os.path.expanduser("~/.hermes/.env")
    d = {}
    with open(p) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip()
    return d


def _token():
    e = _env()
    r = requests.post(
        f"https://{DOMAIN}/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": e["FEISHU_APP_ID"], "app_secret": e["FEISHU_APP_SECRET"]},
        timeout=10,
    ).json()
    return r["tenant_access_token"]


def _hdrs():
    return {"Authorization": f"Bearer {_token()}"}


def poll(chat_id, limit=5):
    r = requests.get(
        f"https://{DOMAIN}/open-apis/im/v1/messages"
        f"?container_id_type=chat&container_id={chat_id}"
        f"&page_size={limit}&sort_type=ByCreateTimeDesc",
        headers=_hdrs(),
        timeout=10,
    ).json()
    return r.get("data", {}).get("items", [])


def send(chat_id, text):
    c = json.dumps({"text": text})
    r = requests.post(
        f"https://{DOMAIN}/open-apis/im/v1/messages?receive_id_type=chat_id",
        headers={**_hdrs(), "Content-Type": "application/json"},
        json={"receive_id": chat_id, "msg_type": "text", "content": c},
        timeout=10,
    ).json()
    return r.get("data", {}).get("message_id", "")


def load_state():
    global seen_ids
    if STATE_FILE.exists():
        d = json.loads(STATE_FILE.read_text())
        seen_ids = set(d.get("seen_ids", []))
        if len(seen_ids) > 500:
            seen_ids = set(list(seen_ids)[-500:])


def save_state():
    STATE_FILE.write_text(
        json.dumps(
            {
                "seen_ids": list(seen_ids),
                "last_save": datetime.now().isoformat(),
            },
            ensure_ascii=False,
        )
    )


def save_pending(name, chat_id, sender, text, msg_id):
    entry = {
        "ts": datetime.now().isoformat(),
        "group_name": name,
        "chat_id": chat_id,
        "sender": sender,
        "text": text,
        "msg_id": msg_id,
        "status": "pending",
    }
    with open(PENDING_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def main():
    global seen_ids
    print(f"[poller v2] watching {len(WATCHED_GROUPS)} groups, interval={POLL_INTERVAL}s")
    print(f"[poller v2] writing to: {PENDING_FILE}")
    load_state()
    print(f"[poller v2] {len(seen_ids)} seen ids loaded")

    while True:
        try:
            for g in WATCHED_GROUPS:
                msgs = poll(g["id"], 5)
                for msg in msgs:
                    mid = msg.get("message_id")
                    if mid in seen_ids:
                        continue
                    seen_ids.add(mid)

                    mentions = msg.get("mentions", [])
                    if not any(m.get("id") == BOT_OPEN_ID for m in mentions):
                        continue

                    sender = msg.get("sender", {}).get("id", "?")
                    body = json.loads(msg.get("body", {}).get("content", "{}"))
                    text = body.get("text", "")

                    print(f"[poller v2] @mentioned in {g['name']}: {text[:80]}")
                    save_pending(g["name"], g["id"], sender, text, mid)

                    ack = "👀 收到 @mention，Agent 处理中...（群聊轮询模式）"
                    send(g["id"], ack)
                    print(f"[poller v2] ack sent to {g['name']}")

            save_state()
            time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            save_state()
            break
        except Exception as e:
            print(f"[poller v2] error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
