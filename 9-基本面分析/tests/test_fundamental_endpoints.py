"""用 python urllib 测试各端点。"""
import json
import urllib.request

BASE = "http://127.0.0.1:9093"

endpoints = [
    "/fundamental/news/brief/latest",
    "/fundamental/flows/regime/latest",
    "/fundamental/flows/brief/latest",
    "/fundamental/narrative/registry/latest",
    "/fundamental/narrative/brief/latest",
    "/fundamental/news/event_ledger/latest",
]

for path in endpoints:
    try:
        with urllib.request.urlopen(BASE + path, timeout=15) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"[ERR] {path}: {e}")
        continue
    ok = data.get("ok")
    # 列出关键字
    summary = {}
    for k in ("regime", "overall_sentiment", "generated_at", "name"):
        if k in data:
            summary[k] = data[k]
    content_len = len(str(data.get("content", "")))
    if isinstance(data.get("record"), dict):
        summary["record_keys"] = list(data["record"].keys())[:8]
    items = data.get("items") if "items" in data else None
    if isinstance(items, list):
        summary["items_count"] = len(items)
    if isinstance(data.get("record"), dict):
        rec = data["record"]
        if isinstance(rec.get("narratives"), list):
            titles = [n.get("name") for n in rec["narratives"][:3]]
            print("   top narratives:", titles, "overall_sentiment:", rec.get("overall_sentiment"))
    print(f"[OK={ok}] {path} | content_len={content_len} | summary={summary} | keys={list(data.keys())[:10]}")

    # print first line of content (if string)
    content = data.get("content") or ""
    if isinstance(content, str) and content:
        print("   content[:120]:", content[:120].replace("\n", "\\n"))
    print()
