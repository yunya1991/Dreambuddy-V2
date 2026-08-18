#!/usr/bin/env python3
"""
Channel directory guard — ensures 5 trading groups persist across gateway restarts.
Run as a background daemon alongside the Hermes Gateway.
"""
import json, os, time

CHATS = [
    {"id": "oc_36c575b6f39a8df3dd75057a96685a21", "name": "Trading-Research", "type": "group"},
    {"id": "oc_36c8543cea823b7546fcaad55d111f9f", "name": "Trading-Desk", "type": "group"},
    {"id": "oc_9cf9f141613b4e6a0f34651843cf8b9b", "name": "Trading-Management", "type": "group"},
    {"id": "oc_8868a5c84f3d8427afa9ed1a9ad7fb76", "name": "Trading-Review", "type": "group"},
    {"id": "oc_20fcedf0c35035568ea8fa947380f75d", "name": "Trading-RiskControl", "type": "group"},
]

CHANNEL_DIR = os.path.expanduser("~/.hermes/channel_directory.json")

while True:
    try:
        time.sleep(30)
        if not os.path.exists(CHANNEL_DIR):
            continue

        with open(CHANNEL_DIR, 'r') as f:
            data = json.load(f)

        existing_ids = {c['id'] for c in data.get('platforms', {}).get('feishu', [])}
        needed = [c for c in CHATS if c['id'] not in existing_ids]

        if needed:
            data['platforms']['feishu'] = list(data['platforms'].get('feishu', [])) + needed
            with open(CHANNEL_DIR, 'w') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"Channel guard: added {len(needed)} groups")
    except Exception as e:
        print(f"Channel guard error: {e}")
        time.sleep(10)
