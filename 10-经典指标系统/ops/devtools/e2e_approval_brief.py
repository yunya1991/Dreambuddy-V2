import json
import os
import time
import urllib.request
import urllib.error


def _get(base: str, path: str):
    try:
        with urllib.request.urlopen(base + path) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode()
        except Exception:
            body = ""
        raise RuntimeError(f"GET {path} -> HTTP {e.code} {body[:2000]}") from None


def _post(base: str, path: str, payload: dict):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode()
        except Exception:
            body = ""
        raise RuntimeError(f"POST {path} -> HTTP {e.code} {body[:2000]}") from None


def _find_draft_entry_id_by_trace_id(base: str, trace_id: str) -> str | None:
    out = _get(base, "/agent/outbox/read?name=changeset_drafts.jsonl&tail=true&limit=50")
    items = out.get("items") or []
    for it in reversed(items):
        obj = (it or {}).get("item") or {}
        draft = (obj.get("draft") if isinstance(obj.get("draft"), dict) else {}) or {}
        if str(draft.get("trace_id") or "").strip() == trace_id:
            did = str(obj.get("id") or "").strip()
            return did or None
    return None


def main():
    base = str(os.environ.get("BASE_URL", "") or "").strip() or "http://127.0.0.1:8093"

    reg = _get(base, "/strategy/registry")
    entries = reg.get("entries") or []
    if not entries:
        raise SystemExit("no strategy registry entries")

    e0 = entries[0] or {}
    strategy_id = str(e0.get("strategy_id") or "").strip()
    source_zip = str(e0.get("source_zip") or "").strip()
    if not strategy_id or not source_zip:
        raise SystemExit(f"bad strategy entry: {e0}")

    trace_id = f"e2e-brief-{int(time.time())}"
    draft = _post(
        base,
        "/agent/changeset/draft",
        {
            "trace_id": trace_id,
            "strategy_id": strategy_id,
            "source_zip": source_zip,
            "label": "test:approval_brief",
            "reason": "e2e approval brief generation",
            "config_patch": {},
        },
    )
    draft_id = draft.get("draft_id")
    if not (isinstance(draft_id, str) and draft_id.strip()):
        draft_id = _find_draft_entry_id_by_trace_id(base, trace_id)

    approval_id = f"appr_{int(time.time())}"
    appr = _post(
        base,
        "/approvals/log",
        {
            "id": approval_id,
            "trace_id": trace_id,
            "draft_id": draft_id,
            "approver": "seed",
            "decision": "pending",
            "action": "config.apply",
            "reason": "seed pending for brief",
            "expires_at": int(time.time() * 1000) + 3600 * 1000,
            "ttl_ms": 3600 * 1000,
        },
    )

    gen = _post(base, "/agent/approvals/brief/generate", {"id": approval_id, "force": True})
    brief = _get(base, f"/agent/approvals/brief/get?id={approval_id}")

    outbox = _get(base, "/agent/outbox/read?name=approval_briefs.jsonl&tail=true&limit=1")
    hist = _get(base, "/approvals/history?limit=10&decision=pending")
    reminder = _post(base, "/agent/approvals/reminder/run", {"max_pending": 10})

    print(json.dumps(
        {
            "strategy": {"strategy_id": strategy_id, "source_zip": source_zip},
            "draft": {"ok": bool(draft.get("ok")), "draft_id_present": ("draft_id" in draft), "draft_id": draft_id},
            "approval": {"ok": bool(appr.get("ok")), "approval_id": appr.get("id")},
            "brief_generate": {"ok": bool(gen.get("ok")), "skipped": bool(gen.get("skipped"))},
            "brief_get": {"ok": bool(brief.get("ok")), "brief_id": (brief.get("brief") or {}).get("id"), "decision": ((brief.get("brief") or {}).get("recommendation") or {}).get("decision")},
            "outbox": {"ok": bool(outbox.get("ok")), "count": outbox.get("count"), "last_type": (((outbox.get("items") or [{}])[-1]).get("item") or {}).get("type")},
            "approvals_pending_history": {"returned": hist.get("returned"), "total_matched": hist.get("total_matched")},
            "reminder_run": reminder,
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ))


if __name__ == "__main__":
    main()
