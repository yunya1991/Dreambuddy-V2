# -*- coding: utf-8 -*-
"""T-DSH-P3 E2E: 常驻三件套——settle 五通道 × 离线续跑 × 投机预取。

依据: DESIGN-DSH-ARCH-UPGRADE v0.2 P3·常驻退出判据(重启后 Ticket 可续跑;
同类事件 recall 命中率提升可测) + V2(trace_id 全链一致) + V5(重启后可从
L0 恢复) + U7(预取未命中静默丢弃) + H1/H2(FAIL-OPEN/开关默认关)。

链路(全部 in-process):
  ① 事件 → 投机预取六维(零 token)→ 同类事件 consume 命中/异类未命中,
     hit_rate 可测(recall 命中率口径)
  ② Ticket live → paused(waiting_event) → 落 L0 → 模拟重启(新 store/新亲和)
     → 匹配事件唤醒回 live 并回写 → 亲和直通锚点重建
  ③ Worker 产出 → settle 五系统全通道(开启 3 通道,1 通道故障隔离)
     → 案例库沉淀带 trace_id(V2)
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.context_prefetch import PrefetchCache, consume_prefetched, prefetch_context  # noqa: E402
from core.l0_foundation import L0Foundation  # noqa: E402
from core.settle_channels import settle_via_channels  # noqa: E402
from core.thread_affinity import AffinityTable  # noqa: E402
from core.ticket_resume import recover_resumable, resume_on_event  # noqa: E402
from core.ticket_state import create_ticket, transition_ticket  # noqa: E402
from core.ticket_store import JsonlTicketStore, load_ticket, save_ticket  # noqa: E402

_TRACE = "tr-e2e-p3-001"


def test_e2e_p3_prefetch_hit_rate_measurable():
    """退出判据: 同类事件 recall 命中率可测(hits/misses/hit_rate)。"""
    l0 = L0Foundation(root="/nonexistent-root")  # 逐维 degraded 信封,FAIL-OPEN 不抛
    cache = PrefetchCache(ttl_sec=300.0)
    trig = {"trigger_id": "tg-1", "source": "cognitive", "kind": "mem_ready", "thread_id": "th-1"}

    # 投机预取(零 token 纯组装)
    assert prefetch_context(trig, l0, cache, now=1000.0, trace_id=_TRACE) is True
    # 同类事件(新 trigger_id,同 source/kind/thread)命中
    hit = consume_prefetched(dict(trig, trigger_id="tg-2"), cache, now=1001.0)
    assert hit is not None
    assert hit["data"]["trace_id"] == _TRACE  # V2 一致
    assert set(hit["data"]["six_dims"].keys()) == {
        "market",
        "skill",
        "knowledge",
        "experience",
        "cases",
        "rea",
    }
    # 异类事件未命中 → 静默丢弃(U7)
    assert consume_prefetched({"source": "s", "kind": "other"}, cache, now=1002.0) is None

    st = cache.stats()
    assert st["hits"] == 1 and st["misses"] == 1 and st["hit_rate"] == 0.5


def test_e2e_p3_restart_resume_with_affinity(tmp_path):
    """退出判据: 重启后 Ticket 可续跑(ADR-2 状态在 L0;亲和为运行时缓存可重建)。"""
    # —— 重启前: Ticket 挂起等事件,落 L0 ——
    store = JsonlTicketStore(str(tmp_path))
    ticket = create_ticket("TK-P3-1", trace_id=_TRACE)
    ticket["worker_id"] = "w-old"
    ticket["thread_id"] = "th-res"
    ticket = transition_ticket(ticket, "paused", paused_reason="waiting_event", now=1000.0)
    ticket["waiting_on"] = {"kinds": ["backtest_done"], "source": "45"}
    save_ticket(ticket, store)
    assert ticket["worker_id"] is None  # ADR-3: 挂起释放槽

    # —— 模拟重启: 进程态全失(新 store 对象/空亲和表),权威状态从 L0 恢复 ——
    store2 = JsonlTicketStore(str(tmp_path))
    affinity = AffinityTable()
    resumable = recover_resumable(store2)
    assert [t["ticket_id"] for t in resumable] == ["TK-P3-1"]

    # 无关事件不唤醒
    assert (
        resume_on_event(store2, {"trigger_id": "tg-n", "source": "45", "kind": "noise"}, now=2000.0)
        == []
    )
    # 等待事件到达 → 唤醒回 live + 回写 L0 + 亲和直通重建
    resumed = resume_on_event(
        store2,
        {"trigger_id": "tg-ok", "source": "45", "kind": "backtest_done"},
        now=2001.0,
        affinity=affinity,
        worker_id="w-new",
    )
    assert [t["ticket_id"] for t in resumed] == ["TK-P3-1"]
    back = load_ticket("TK-P3-1", store2)
    assert back["state"] == "live" and back["worker_id"] == "w-new"
    assert back["trace_id"] == _TRACE  # V2 跨重启一致
    assert affinity.lookup("th-res", now=2002.0) == {
        "worker_id": "w-new",
        "ticket_id": "TK-P3-1",
    }


def test_e2e_p3_settle_five_channels_with_failure_isolation(tmp_path):
    """settle 五系统全通道: 开启的通道逐一执行,单通道故障不阻塞(H1)。"""
    written = {"cognitive": [], "knowledge": [], "docs": []}

    def ch_cognitive(result, ctx):
        written["cognitive"].append(ctx.get("trace_id"))
        return {"memory_id": "VM-P3-1"}

    def ch_knowledge(result, ctx):
        written["knowledge"].append(ctx.get("trace_id"))
        raise RuntimeError("knowledge base down")  # 故障通道

    def ch_docs(result, ctx):
        written["docs"].append(ctx.get("trace_id"))
        return {"doc_path": "2-KNOWLEDGE/x.md"}

    channels = {"cognitive": ch_cognitive, "knowledge": ch_knowledge, "docs": ch_docs}
    flags = {
        "enable_settle_channel_cognitive": True,
        "enable_settle_channel_knowledge": True,
        "enable_settle_channel_docs": True,
        # skill/index 默认关(H2)
    }
    ctx = {"intent": "event_research", "message": "m", "trace_id": _TRACE}
    report = settle_via_channels({"success": True, "answer": "a"}, ctx, channels, flags)

    assert report["cognitive"]["status"] == "ok"
    assert report["cognitive"]["detail"] == {"memory_id": "VM-P3-1"}
    assert report["knowledge"]["status"] == "failed"  # 故障隔离
    assert report["docs"]["status"] == "ok"  # 故障不阻塞后续通道
    assert report["skill"]["status"] == "disabled"
    assert report["index"]["status"] == "disabled"
    # 三通道均真实被调用,trace_id 透传(V2)
    assert written == {"cognitive": [_TRACE], "knowledge": [_TRACE], "docs": [_TRACE]}

    # 同链路 L0.settle 案例库沉淀仍带 trace_id(与五通道并行不悖)
    l0 = L0Foundation(root=str(tmp_path))
    l0.settle({"success": True, "answer": "a", "data": {"k": 1}}, ctx)
    case_path = tmp_path / "34-前端应用训练系统" / "l1_case_store.jsonl"
    case = json.loads(case_path.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert case["trace_id"] == _TRACE
