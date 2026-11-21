#!/usr/bin/env python3
"""手机预约助手 CLI：ingest / jobs / gateway / token / doctor / report / pause / resume / ask / dispatch / patrol / reconcile / knowledge。

消费上游命中 → 生成预约作业 → 本地网关派发给手机端 Agent → 回执落库 → reservation.v1 报告。
不 import 上游组件、不写死其路径；上游通过 --ra-cli 或 --source 注入。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import brain  # noqa: E402
import cloud_data  # noqa: E402
import content_guard  # noqa: E402
import explore  # noqa: E402
import gateway as gateway_mod  # noqa: E402
import ingest as ingest_mod  # noqa: E402
import knowledge  # noqa: E402
import phone_driver  # noqa: E402
import regression  # noqa: E402
import security  # noqa: E402
import store as store_mod  # noqa: E402

CN_TZ = timezone(timedelta(hours=8))

LIMITS = (
    "本组件仅做上游命中到手机端预约动作的编排与派发，停在官方下单页并预填；"
    "不代抢、不转售、不锁座、不托管支付、不破解验证码，不承诺成功率。"
)
EXIT_OK, EXIT_ARG, EXIT_GATE, EXIT_NET = 0, 2, 3, 5


class ContentGuardError(ValueError):
    """内容风控拒绝：命中个股/交易动作/收益承诺等高风险表达，禁止下发发布。"""


def state_dir() -> Path:
    return Path(os.environ.get("MRA_STATE_DIR") or (Path.home() / ".mobile-reservation-assist"))


def open_store() -> store_mod.Store:
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    try:
        directory.chmod(0o700)
    except PermissionError:
        pass
    return store_mod.Store(directory / "state.db")


def envelope(command: str, tasks=None, hits=None, events=None, missing=None) -> dict:
    return {
        "schema_version": "1.0",
        "command": command,
        "generated_at": datetime.now(CN_TZ).isoformat(timespec="seconds"),
        "tasks": tasks or [],
        "hits": hits or [],
        "events": security.redact_obj(events or []),
        "missing": missing or [],
        "limits": LIMITS,
    }


# ---------------------------------------------------------------------------


def cmd_ingest(args) -> int:
    try:
        hits = ingest_mod.load_hits(ra_cli=args.ra_cli, source=args.source)
    except (RuntimeError, ValueError) as exc:
        print("E_NET：{}".format(exc), file=sys.stderr)
        return EXIT_NET if "失败" in str(exc) else EXIT_ARG
    device_id = str(getattr(args, "device_id", "") or "").strip()
    if device_id:
        for hit in hits:
            hit["preferred_device"] = device_id
    with open_store() as db:
        result = ingest_mod.ingest_into(db, hits)
    print(json.dumps(result, ensure_ascii=False))
    return EXIT_OK


def cmd_devices(args) -> int:
    """多设备并发：设备心跳与在线状态。"""
    with open_store() as db:
        devices = db.list_devices(offline_after=args.offline_after)
    if args.json:
        print(json.dumps({"devices": devices}, ensure_ascii=False, indent=2))
    else:
        for device in devices:
            print(
                "{:<16} {:<8} dispatched={:<3} last_seen={}".format(
                    device["device_id"],
                    "online" if device["online"] else "offline",
                    device["dispatched"],
                    time.strftime("%H:%M:%S", time.localtime(device["last_seen"] / 1000)),
                )
            )
    return EXIT_OK


def cmd_jobs(args) -> int:
    with open_store() as db:
        jobs = db.list_jobs(state=args.state)
    if args.json:
        payload = envelope(
            "jobs",
            tasks=[
                {
                    "id": str(job["_id"]),
                    "adapter": job.get("adapter", ""),
                    "status": job.get("_state", ""),
                    "window_start": None,
                    "window_end": None,
                    "submit_enabled": 0,
                }
                for job in jobs
            ],
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return EXIT_OK
    if not jobs:
        print("暂无预约作业")
        return EXIT_OK
    for job in jobs:
        target = job.get("target") or {}
        print(
            "{:<6} {:<9} {:<10} {} / {} / {}".format(
                job["_id"],
                job.get("_state", ""),
                job.get("adapter", ""),
                target.get("target_id", ""),
                target.get("session", ""),
                target.get("price_tier", ""),
            )
        )
    return EXIT_OK


def cmd_gateway(args) -> int:
    token = security.load_token(state_dir())
    print("网关就绪：http://{}:{}/  (Token 存于 {})".format(args.host, args.port, security.token_path(state_dir())))
    with open_store() as db:
        server = gateway_mod.serve(db, token, host=args.host, port=args.port)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    return EXIT_OK


def cmd_token(args) -> int:
    token = security.load_token(state_dir())
    if args.show:
        if not sys.stdin.isatty():
            print("E_GATE：--show 必须在 tty 中查看", file=sys.stderr)
            return EXIT_GATE
        print(token)
    else:
        print("Token 已配置于 {}".format(security.token_path(state_dir())))
    return EXIT_OK


def cmd_pause(args) -> int:
    with open_store() as db:
        db.set_meta("paused", "1")
        db.add_event("info", "switch_off", "", {})
    print("已暂停：网关不再派发作业")
    return EXIT_OK


def cmd_resume(args) -> int:
    with open_store() as db:
        db.set_meta("paused", "0")
        db.add_event("info", "switch_on", "", {})
    print("已恢复：网关开始派发作业")
    return EXIT_OK


def _doctor_checks() -> list[dict]:
    checks: list[dict] = []
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    try:
        directory.chmod(0o700)
    except PermissionError:
        pass

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    add("state_dir", directory.is_dir(), str(directory))
    mode = directory.stat().st_mode & 0o777
    add("state_dir_mode", mode & 0o077 == 0, oct(mode))

    integrity = "unavailable"
    try:
        with open_store() as db:
            integrity = db.conn.execute("PRAGMA quick_check").fetchone()[0]
    except Exception as exc:  # noqa: BLE001
        integrity = str(exc)
    add("sqlite", integrity == "ok", integrity)
    add("token", bool(security.load_token(directory)), str(security.token_path(directory)))
    add("container", not security.is_container(), "容器/云主机内不派发")
    return checks


def cmd_doctor(args) -> int:
    checks = _doctor_checks()
    missing = [
        {"key": item["name"], "code": "E_ENV", "detail": item["detail"]}
        for item in checks
        if not item["ok"]
    ]
    if args.json:
        payload = envelope("doctor", missing=missing)
        payload["checks"] = checks
        print(json.dumps(security.redact_obj(payload), ensure_ascii=False, indent=2))
    else:
        for item in checks:
            print("{}  {}  {}".format("PASS" if item["ok"] else "WARN", item["name"], item["detail"]))
        print("\n" + LIMITS)
    return EXIT_OK if not missing else EXIT_GATE


def cmd_report(args) -> int:
    with open_store() as db:
        jobs = db.list_jobs()
        results = db.list_results()
        events = db.list_events()
    tasks = [
        {
            "id": str(job["_id"]),
            "adapter": job.get("adapter", ""),
            "status": job.get("_state", ""),
            "window_start": None,
            "window_end": None,
            "submit_enabled": 0,
        }
        for job in jobs
    ]
    hits = [
        {
            "task_id": job.get("task_id", ""),
            "fingerprint": job.get("fingerprint", ""),
            "at": int(job.get("at") or 0),
            "result": job.get("_state", ""),
            "notified_at": None,
            "submit_state": job.get("_state") if job.get("_state") in store_mod.TERMINAL_STATES else None,
        }
        for job in jobs
    ]
    payload = envelope("report", tasks=tasks, hits=hits, events=events)
    payload["results"] = results
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return EXIT_OK
    print("作业 {} 个，结果 {} 条，事件 {} 条".format(len(tasks), len(results), len(events)))
    for job in jobs:
        print("  #{} {} {}".format(job["_id"], job.get("_state", ""), job.get("adapter", "")))
    print("\n" + LIMITS)
    return EXIT_OK


def _jobs_summary(db) -> list[dict]:
    return [
        {
            "id": str(job["_id"]),
            "state": job.get("_state", ""),
            "adapter": job.get("adapter", ""),
            "target": (job.get("target") or {}).get("target_id", ""),
        }
        for job in db.list_jobs()
    ]


def _reset_counts(db) -> dict:
    """统计每个作业已被复位次数（用于异步回执验收的重试上限）。"""
    counts: dict[str, int] = {}
    for event in db.list_events():
        if event.get("code") != "reset_stuck":
            continue
        job_id = (event.get("payload") or {}).get("job_id")
        if job_id is None:
            continue
        counts[str(job_id)] = counts.get(str(job_id), 0) + 1
    return counts


def _reset_stuck(seconds: int = 0, max_retries: int = 2) -> dict:
    """异步回执验收：超时无回执判不合格→复位重派；超过重试上限置 failed，避免死循环。

    seconds=0 表示不按时间过滤，复位所有 dispatched（人工显式调用）。
    P0 约束：已有订单证据（订单号/已判未知）的作业不得复位重派，只能转 order_unknown 等对账。
    """
    with open_store() as db:
        stuck = db.list_stuck(seconds) if seconds > 0 else db.list_jobs(state="dispatched")
        counts = _reset_counts(db)
        reset: list[int] = []
        exhausted: list[int] = []
        unknown: list[int] = []
        for job in stuck:
            if db.has_order_evidence(job["_id"]):
                db.set_job_state(job["_id"], "order_unknown")
                db.add_event(
                    "warn",
                    "order_unknown_pending_reconcile",
                    job.get("task_id"),
                    {"job_id": job["_id"], "reason": "已有订单证据，禁止重试，等待对账"},
                )
                unknown.append(job["_id"])
                continue
            if counts.get(str(job["_id"]), 0) >= max_retries:
                db.set_job_state(job["_id"], "failed")
                db.add_event("warn", "acceptance_failed", job.get("task_id"), {"job_id": job["_id"], "reason": "超时无回执且重试次数用尽"})
                exhausted.append(job["_id"])
            else:
                db.set_job_state(job["_id"], "pending")
                db.add_event("warn", "reset_stuck", job.get("task_id"), {"job_id": job["_id"]})
                reset.append(job["_id"])
        if stuck:
            db.add_event(
                "info",
                "acceptance_verdict",
                None,
                {"stuck": len(stuck), "reset": reset, "failed": exhausted, "order_unknown": unknown},
            )
    return {"reset": reset, "failed": exhausted, "order_unknown": unknown}


def _reconcile(params: dict) -> dict:
    """订单对账：不带 job_id 时列出待对账作业；带 job_id+state 时收敛为 done/failed。"""
    job_id = params.get("job_id")
    if job_id in (None, ""):
        with open_store() as db:
            jobs = db.list_order_unknown()
            unresolved = []
            for job in jobs:
                latest = db.latest_result(job["_id"]) or {}
                unresolved.append(
                    {
                        "job_id": job["_id"],
                        "task_id": job.get("task_id", ""),
                        "adapter": job.get("adapter", ""),
                        "stage": latest.get("stage", ""),
                        "order_id": latest.get("order_id", ""),
                        "screenshot": latest.get("screenshot", ""),
                    }
                )
        return {"unresolved": unresolved, "count": len(unresolved)}
    state = str(params.get("state") or "").strip()
    with open_store() as db:
        return db.reconcile(
            int(job_id),
            state,
            order_id=str(params.get("order_id") or ""),
            note=str(params.get("note") or ""),
        )


def accept_execution(nl: str, results: list[dict], retry: bool = True) -> dict:
    """AI 验收官：对执行结果做合格判定；不合格按白名单补救后复检（最多 2 轮）。"""
    rounds: list[dict] = []
    verdict = brain.verify(nl, "execute_plan", results)
    rounds.append({"round": 1, "qualified": verdict["qualified"], "score": verdict["score"], "issues": verdict["issues"]})
    if verdict["qualified"] or not retry:
        return {"qualified": verdict["qualified"], "rounds": rounds, "guidance": verdict["guidance"]}
    fix = _reset_stuck()
    with open_store() as db:
        fresh = _jobs_summary(db)
    verdict2 = brain.verify(nl, "retry_after_reset", {"jobs": fresh, "fix": fix})
    rounds.append({"round": 2, "qualified": verdict2["qualified"], "score": verdict2["score"], "issues": verdict2["issues"], "fix": fix})
    return {"qualified": verdict2["qualified"], "rounds": rounds, "guidance": verdict2["guidance"]}


def print_acceptance(report: dict) -> None:
    """打印验收结论（合格/不合格、逐轮问题、建议）。"""
    print("验收：{}（{} 轮）".format("合格" if report["qualified"] else "不合格", len(report["rounds"])))
    for item in report["rounds"]:
        detail = "；".join(item.get("issues") or []) or "无问题"
        print("  第{}轮 score={} {}".format(item["round"], item.get("score", 0), detail))
    if report.get("guidance"):
        print("  建议：{}".format(report["guidance"]))


def _consult_sync(question: str, timeout: int = 150, dedupe: bool = True) -> dict:
    """把问题交给手机端千问 App 并等待答案（同步）。供 CLI 与大模型白名单动作复用。

    dedupe=True 时同一问题复用已有答案；dedupe=False 强制重新询问（加时间戳指纹）。
    """
    question = (question or "").strip()
    if not question:
        return {"state": "failed", "answer": "", "note": "缺少问题"}
    base = hashlib.sha1(question.encode("utf-8")).hexdigest()[:16]
    if dedupe:
        fingerprint = base
    else:
        fingerprint = "{}-{}".format(base, int(time.time() * 1000))
    task_id = "consult:{}".format(fingerprint)
    hit = ingest_mod.build_hit(
        adapter="qianwen",
        task_id=task_id,
        fingerprint=fingerprint,
        at=int(time.time()),
        target={"target_id": "qianwen"},
        max_price=None,
    )
    hit["question"] = question
    with open_store() as db:
        added = db.enqueue_job(hit)
        if added:
            db.add_event("info", "consult_enqueued", task_id, {"chars": len(question)})
        row = db._fetchone("SELECT id FROM jobs WHERE task_id=? ORDER BY id DESC LIMIT 1", (task_id,))
        if not added:
            # 幂等：同一问题已咨询过，直接复用最近一次答案，而不是报失败
            prior = db._fetchone(
                "SELECT id FROM jobs WHERE adapter='qianwen' AND fingerprint=? ORDER BY id DESC LIMIT 1",
                (fingerprint,),
            )
            prev = (
                db._fetchone(
                    "SELECT state, detail_json FROM results WHERE job_id=? ORDER BY id DESC LIMIT 1",
                    (prior["id"],),
                )
                if prior
                else None
            )
            if prev:
                detail = json.loads(prev["detail_json"] or "{}")
                state = "done" if prev["state"] in ("ok", "done") else prev["state"]
                return {
                    "state": state,
                    "answer": detail.get("answer", ""),
                    "note": detail.get("note", ""),
                    "reused": True,
                }
    if not added:
        return {"state": "failed", "answer": "", "note": "同一问题已咨询过（幂等去重）"}
    job_id = row["id"] if row else None
    deadline = time.time() + timeout
    while time.time() < deadline:
        with open_store() as db:
            res = db._fetchone(
                "SELECT state, detail_json FROM results WHERE job_id=? ORDER BY id DESC LIMIT 1", (job_id,)
            )
        if res:
            detail = json.loads(res["detail_json"] or "{}")
            state = "done" if res["state"] in ("ok", "done") else res["state"]
            return {"state": state, "answer": detail.get("answer", ""), "note": detail.get("note", "")}
        time.sleep(2)
    return {"state": "timeout", "answer": "", "note": "等待千问答复超时（{}s）".format(timeout)}


def cmd_consult(args) -> int:
    """把问题交给手机端千问 App，等待答案回传（知识百科通道）。"""
    result = _consult_sync(" ".join(args.question), args.timeout)
    print(json.dumps(result, ensure_ascii=False))
    return EXIT_OK if result["state"] == "done" else EXIT_GATE


def _knowledge_ask(params: dict) -> dict:
    """knowledge.ask：只读结构化知识（结论 + 引用 + 置信度 + TTL 缓存）。"""
    question = knowledge.normalize_question(params.get("question"))
    if not question:
        raise ValueError("knowledge ask 需要 question")
    app = str(params.get("app") or "").strip()
    ttl = int(params.get("max_age") or knowledge.DEFAULT_TTL_SECONDS)
    key = knowledge.cache_key(question, app)
    if not params.get("no_cache"):
        with open_store() as db:
            cached = db.get_knowledge(key)
        if cached:
            return cached
    result = _consult_sync(
        knowledge.build_prompt(question, app),
        int(params.get("timeout") or 150),
        dedupe=not params.get("no_cache"),
    )
    if result.get("state") != "done":
        return {
            "schema": knowledge.SCHEMA,
            "question": question,
            "app": app,
            "ok": False,
            "answer": "",
            "citations": [],
            "confidence": 0.0,
            "side_effect": "none",
            "source": "qianwen-app",
            "cached": False,
            "unsafe_actions_detected": False,
            "note": result.get("note", ""),
        }
    envelope = knowledge.build_envelope(question, result.get("answer", ""), app=app)
    envelope["ok"] = True
    with open_store() as db:
        db.put_knowledge(key, app, question, envelope, ttl_seconds=ttl)
        db.add_event("info", "knowledge_asked", None, {"app": app, "confidence": envelope["confidence"]})
    return envelope


def cmd_knowledge(args) -> int:
    """knowledge ask：结构化知识问答（引用 + 置信度，只读）。"""
    if args.knowledge_command != "ask":
        print("E_ARG：仅支持 knowledge ask", file=sys.stderr)
        return EXIT_ARG
    try:
        result = _knowledge_ask(
            {
                "question": args.question,
                "app": args.app,
                "max_age": args.max_age,
                "no_cache": args.no_cache,
                "timeout": args.timeout,
            }
        )
    except ValueError as exc:
        print("E_ARG：{}".format(exc), file=sys.stderr)
        return EXIT_ARG
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("结论：{}".format(result.get("answer") or result.get("note") or "（无）"))
        if result.get("citations"):
            print("引用：")
            for item in result["citations"]:
                print("  - [{}] {}".format(item.get("type", ""), item.get("value", "")))
        print("置信度：{}（{}）".format(result.get("confidence", 0), "缓存" if result.get("cached") else "实时"))
    return EXIT_OK if result.get("ok") else EXIT_GATE


def _dispatch(params: dict) -> dict:
    """按参数下发一条预约作业（幂等：同 task_id+fingerprint 不重复）。"""
    adapter = str(params.get("adapter", "")).strip()
    target_id = str(params.get("target_id", "")).strip()
    session = str(params.get("session", "")).strip()
    price_tier = str(params.get("price_tier", "")).strip()
    max_price = params.get("max_price")
    if not adapter or not target_id:
        raise ValueError("dispatch 需要 adapter 与 target_id")
    task_id = "nl:{}:{}".format(adapter, target_id)
    fingerprint = hashlib.sha1(
        "{}|{}|{}".format(task_id, session, price_tier).encode("utf-8")
    ).hexdigest()[:16]
    hit = ingest_mod.build_hit(
        adapter=adapter,
        task_id=task_id,
        fingerprint=fingerprint,
        at=int(time.time()),
        target={"target_id": target_id, "session": session, "price_tier": price_tier},
        max_price=max_price,
    )
    # 支付授权：默认关闭；仅用户明确说"帮我买/直接付款"时置 True（随作业持久化下发）
    hit["pay_authorized"] = bool(params.get("pay_authorized"))
    with open_store() as db:
        added = db.enqueue_job(hit)
        if added:
            db.add_event("info", "job_enqueued_nl", task_id, {"target_id": target_id})
    return {"enqueued": added, "job": {"task_id": task_id, "target": hit["target"]}}


def _run_action(action: str, params: dict):
    """执行单个白名单动作；未知动作抛错（由 execute_steps 捕获）。"""
    if action == "doctor":
        return _doctor_checks()
    if action == "jobs":
        with open_store() as db:
            return _jobs_summary(db)
    if action == "report":
        with open_store() as db:
            return {"jobs": len(db.list_jobs()), "results": len(db.list_results())}
    if action == "pause":
        with open_store() as db:
            db.set_meta("paused", "1")
            db.add_event("info", "switch_off", "", {})
        return "paused"
    if action == "resume":
        with open_store() as db:
            db.set_meta("paused", "0")
            db.add_event("info", "switch_on", "", {})
        return "resumed"
    if action == "reset_stuck":
        return _reset_stuck()
    if action == "reconcile":
        return _reconcile(params)
    if action == "dispatch":
        return _dispatch(params)
    if action == "consult":
        return _consult_sync(str(params.get("question") or ""), int(params.get("timeout") or 120))
    if action == "knowledge_ask":
        return _knowledge_ask(params)
    raise ValueError("未知动作：{}".format(action))


def execute_steps(steps: list[dict]) -> list[dict]:
    """顺序执行白名单步骤，逐步记录结果（单步失败不影响后续）。"""
    results: list[dict] = []
    for step in steps:
        action = str(step.get("action", ""))
        params = step.get("params") or {}
        try:
            results.append({"action": action, "ok": True, "result": _run_action(action, params)})
        except Exception as exc:  # noqa: BLE001 - 单步失败透传
            results.append({"action": action, "ok": False, "error": str(exc)})
    return results


def _agent_log_tail(limit: int = 40) -> list[str]:
    """读取手机端 Agent 日志本地镜像（若配置了 MRA_AGENT_LOG 或状态目录内有 agent.log）。"""
    candidates = []
    env_path = os.environ.get("MRA_AGENT_LOG", "")
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(state_dir() / "agent.log")
    for path in candidates:
        try:
            if path.is_file():
                return path.read_text(encoding="utf-8", errors="ignore").splitlines()[-limit:]
        except OSError:
            continue
    return []


def cmd_ask(args) -> int:
    if not brain.available():
        print("E_ENV：未找到 QWEN 配置（~/.local/share/dreambuddy/qwen.env）", file=sys.stderr)
        return EXIT_NET
    with open_store() as db:
        context = {"paused": db.get_meta("paused", ""), "jobs": _jobs_summary(db)}
    try:
        raw = brain.plan(args.text, context)
    except (RuntimeError, ValueError) as exc:
        print("E_NET：{}".format(exc), file=sys.stderr)
        return EXIT_NET
    guarded = brain.guard_plan(raw)
    if args.json:
        print(json.dumps(guarded, ensure_ascii=False, indent=2))
    else:
        print("意图：{}".format(guarded["plan"].get("intent", "")))
        for step in guarded["plan"].get("steps", []):
            print("  - {} {}".format(step.get("action"), json.dumps(step.get("params") or {}, ensure_ascii=False)))
        for rej in guarded["rejected"]:
            print("  [拒绝] {}：{}".format(rej.get("action"), rej.get("reason")))
    if not args.execute:
        print("\n未执行。加 --execute 由人工授权执行以上白名单计划。")
        return EXIT_OK
    # 执行前参数预检：缺关键参数直接拦下，避免手机端空跑
    check = brain.precheck_plan(guarded["plan"])
    if not check["ok"]:
        for problem in check["problems"]:
            print("E_ARG：第{}步 {} 缺少 {}".format(problem["index"] + 1, problem["action"], "、".join(problem["missing"])), file=sys.stderr)
        return EXIT_ARG
    results = execute_steps(guarded["plan"].get("steps", []))
    print(json.dumps(results, ensure_ascii=False, indent=2))
    # AI 验收官：执行后验收，不合格按白名单补救复检
    report = accept_execution(args.text, results)
    print_acceptance(report)
    return EXIT_OK if report["qualified"] and all(item.get("ok") for item in results) else EXIT_GATE


def cmd_dispatch(args) -> int:
    if not brain.available():
        print("E_ENV：未找到 QWEN 配置（~/.local/share/dreambuddy/qwen.env）", file=sys.stderr)
        return EXIT_NET
    try:
        parsed = brain.parse_dispatch(args.text)
    except (RuntimeError, ValueError) as exc:
        print("E_NET：{}".format(exc), file=sys.stderr)
        return EXIT_NET
    print("解析：" + json.dumps(parsed, ensure_ascii=False))
    if args.dry_run:
        print("dry-run：不写入作业。")
        return EXIT_OK
    try:
        result = _dispatch(parsed)
    except ValueError as exc:
        print("E_INPUT：{}".format(exc), file=sys.stderr)
        return EXIT_ARG
    print(json.dumps(result, ensure_ascii=False))
    return EXIT_OK


CARPOOL_PLATFORMS = ("didi", "dida", "hello")
CARPOOL_KINDS = {
    "start": "scan_session",
    "refresh": "scan_once",
    "accept": "accept_order",
    "stop": "stop_scan",
}


def _carpool_enqueue(
    db,
    verb: str,
    platform: str,
    order_id: str = "",
    price=None,
    min_price=0,
    max_accept: int = 1,
    accept_authorized: bool = False,
    device_id: str = "",
) -> dict:
    kind = CARPOOL_KINDS[verb]
    suffix = order_id or str(int(time.time() * 1000))
    task_id = "carpool:{}:{}".format(verb, suffix)
    fingerprint = hashlib.sha1(
        "{}|{}|{}".format(task_id, platform, kind).encode("utf-8")
    ).hexdigest()[:16]
    hit = {
        "adapter": "carpool",
        "task_id": task_id,
        "fingerprint": fingerprint,
        "at": int(time.time()),
        "target": {"platform": platform, "order_id": order_id, "price": price, "min_price": min_price},
        "kind": kind,
        "accept_authorized": bool(accept_authorized),
        "max_accept": int(max_accept),
        "accepted_today": db.count_today_accept(),
        "preferred_device": device_id,
    }
    added = db.enqueue_job(hit)
    job = db.get_job_by_task(task_id, fingerprint)
    if added:
        db.add_event("info", "carpool_job_enqueued", task_id, {"kind": kind, "platform": platform})
    return {
        "enqueued": added,
        "job_id": job["_id"] if job else None,
        "kind": kind,
        "platform": platform,
        "accept_authorized": bool(accept_authorized),
    }


def cmd_carpool(args) -> int:
    """顺风车抢单：默认只扫描；`accept` 必须显式 `--accept` 才下发接单。"""
    sub = args.carpool_cmd
    if sub == "status":
        with open_store() as db:
            jobs = [job for job in db.list_jobs() if job.get("adapter") == "carpool"]
            payload = {
                "today_accept": db.count_today_accept(),
                "jobs": [
                    {
                        "id": job["_id"],
                        "kind": job.get("kind", ""),
                        "platform": (job.get("target") or {}).get("platform", ""),
                        "state": job.get("_state", ""),
                        "order_id": (job.get("target") or {}).get("order_id", ""),
                    }
                    for job in jobs
                ],
            }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print("今日已接单：{}".format(payload["today_accept"]))
            for item in payload["jobs"]:
                print(
                    "{:<4} {:<14} {:<6} {:<12} {}".format(
                        item["id"], item["kind"], item["platform"], item["state"], item["order_id"] or "-"
                    )
                )
        return EXIT_OK

    platform = str(args.platform or "")
    if platform not in CARPOOL_PLATFORMS:
        print("E_ARG：未登记的顺风车平台：{}".format(platform), file=sys.stderr)
        return EXIT_ARG
    if sub == "accept" and not args.accept:
        print("E_GATE：接单需显式 --accept 授权", file=sys.stderr)
        return EXIT_GATE

    with open_store() as db:
        result = _carpool_enqueue(
            db,
            sub,
            platform,
            order_id=str(getattr(args, "order_id", "") or ""),
            price=getattr(args, "price", None),
            min_price=getattr(args, "min_price", 0) or 0,
            max_accept=getattr(args, "max_accept", 1) or 1,
            accept_authorized=bool(getattr(args, "accept", False)),
            device_id=str(getattr(args, "device_id", "") or ""),
        )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            "{}：job={} kind={} platform={}{}".format(
                "已入队" if result["enqueued"] else "已存在",
                result["job_id"],
                result["kind"],
                result["platform"],
                "（已授权接单）" if result["accept_authorized"] else "（仅扫描）",
            )
        )
    return EXIT_OK


def cmd_reconcile(args) -> int:
    """订单对账：列出 order_unknown 作业，或按人工结论收敛为 done/failed。"""
    if args.job is None:
        payload = _reconcile({})
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        elif not payload["unresolved"]:
            print("无待对账作业")
        else:
            for item in payload["unresolved"]:
                print(
                    "{:<6} {:<10} stage={:<14} order_id={}".format(
                        item["job_id"], item["adapter"], item["stage"] or "-", item["order_id"] or "-"
                    )
                )
        return EXIT_OK
    if not args.state:
        print("E_ARG：收敛时必须指定 --state done|failed", file=sys.stderr)
        return EXIT_ARG
    try:
        result = _reconcile(
            {
                "job_id": args.job,
                "state": args.state,
                "order_id": args.order_id,
                "note": args.note,
            }
        )
    except ValueError as exc:
        print("E_ARG：{}".format(exc), file=sys.stderr)
        return EXIT_ARG
    print(json.dumps(result, ensure_ascii=False))
    return EXIT_OK


def _explore_start(params: dict) -> dict:
    """开始探索录制；同设备已有录制会话时复用，避免孤儿会话。"""
    app = str(params.get("app") or "").strip()
    goal = str(params.get("goal") or "").strip()
    if not app:
        raise ValueError("explore start 需要 --app")
    device_id = str(params.get("device_id") or "").strip()
    with open_store() as db:
        active = db.get_active_exploration(device_id or None)
        if active:
            return {"ok": True, "reused": True, "exploration": active}
        exp_id = db.create_exploration(app, goal, device_id)
        db.add_event(
            "info", "explore_started", "explore:{}".format(exp_id), {"app": app, "goal": goal[:60]}
        )
        return {"ok": True, "reused": False, "exploration": db.get_exploration(exp_id)}


def _explore_snapshot(exploration_id: int, payload: dict) -> dict:
    """写入一帧页面快照（CLI/测试用；手机端走 POST /snapshots）。"""
    with open_store() as db:
        return db.add_snapshot(
            int(exploration_id),
            package=str(payload.get("package") or ""),
            activity=str(payload.get("activity") or ""),
            page_text=str(payload.get("page_text") or ""),
            screenshot=str(payload.get("screenshot") or ""),
            nodes=payload.get("nodes") or [],
        )


def _explore_stop(params: dict) -> dict:
    try:
        exp_id = int(params.get("exploration_id"))
    except (TypeError, ValueError):
        raise ValueError("explore stop 需要 --id") from None
    with open_store() as db:
        exploration = db.get_exploration(exp_id)
        if exploration is None:
            raise ValueError("录制会话不存在：{}".format(exp_id))
        exploration = db.stop_exploration(exp_id) or exploration
        count = len(db.list_snapshots(exp_id))
        db.add_event("info", "explore_stopped", "explore:{}".format(exp_id), {"snapshots": count})
        return {"ok": True, "exploration": exploration, "snapshots": count}


def _explore_draft(params: dict) -> dict:
    """由快照生成适配器草案；`--out` 时把源码草案落盘（默认不写文件）。"""
    try:
        exp_id = int(params.get("exploration_id"))
    except (TypeError, ValueError):
        raise ValueError("explore draft 需要 --id") from None
    with open_store() as db:
        exploration = db.get_exploration(exp_id)
        if exploration is None:
            raise ValueError("录制会话不存在：{}".format(exp_id))
        snapshots = db.list_snapshots(exp_id)
    if not snapshots:
        raise ValueError("没有快照，无法生成草案")
    draft = explore.build_draft(exploration, snapshots)
    draft["adapter_source"] = explore.render_adapter(draft)
    out = str(params.get("out") or "").strip()
    if out:
        path = Path(out).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(draft["adapter_source"], encoding="utf-8")
        draft["out"] = str(path)
        with open_store() as db:
            db.add_event(
                "info",
                "explore_drafted",
                "explore:{}".format(exp_id),
                {"out": str(path), "ready": draft["ready"]},
            )
    return draft


def _explore_baseline(params: dict) -> dict:
    """把一次录制固化为适配器基线，供平台改版后做兼容门禁。"""
    name = str(params.get("name") or "").strip()
    if not name:
        raise ValueError("explore baseline 需要 --name")
    try:
        exp_id = int(params.get("exploration_id"))
    except (TypeError, ValueError):
        raise ValueError("explore baseline 需要 --id") from None
    with open_store() as db:
        exploration = db.get_exploration(exp_id)
        if exploration is None:
            raise ValueError("录制会话不存在：{}".format(exp_id))
        snapshots = db.list_snapshots(exp_id)
        if not snapshots:
            raise ValueError("没有快照，无法建立基线")
        baseline = explore.build_baseline(exploration, snapshots, name)
        db.save_baseline(name, exploration["app"], exp_id, baseline["steps"], baseline["assertions"])
        db.add_event(
            "info",
            "explore_baseline_saved",
            "explore:{}".format(exp_id),
            {"name": name, "assertions": len(baseline["assertions"])},
        )
    return baseline


def _explore_check(params: dict) -> dict:
    """回放兼容门禁：用基线断言比对一次新录制，判断适配器是否失效。"""
    name = str(params.get("name") or "").strip()
    if not name:
        raise ValueError("explore check 需要 --name")
    try:
        exp_id = int(params.get("exploration_id"))
    except (TypeError, ValueError):
        raise ValueError("explore check 需要 --id") from None
    threshold = float(params.get("threshold") or explore.DEFAULT_THRESHOLD)
    with open_store() as db:
        baseline = db.get_baseline(name)
        if baseline is None:
            raise ValueError("基线不存在：{}（先执行 explore baseline）".format(name))
        exploration = db.get_exploration(exp_id)
        if exploration is None:
            raise ValueError("录制会话不存在：{}".format(exp_id))
        snapshots = db.list_snapshots(exp_id)
    result = explore.check_compatibility(baseline, snapshots, threshold=threshold)
    result["name"] = name
    result["exploration_id"] = exp_id
    with open_store() as db:
        db.add_event(
            "info" if result["compatible"] else "warn",
            "explore_gate",
            "explore:{}".format(exp_id),
            {"name": name, "coverage": result["coverage"], "step_misses": len(result["step_misses"])},
        )
    return result


def _regression_add(params: dict) -> dict:
    case_id = str(params.get("case_id") or "").strip()
    baseline = str(params.get("baseline") or "").strip()
    if not case_id:
        raise ValueError("regression add 需要 --case-id")
    if not baseline:
        raise ValueError("regression add 需要 --baseline")
    try:
        exploration_id = int(params.get("exploration_id"))
    except (TypeError, ValueError):
        raise ValueError("regression add 需要 --id") from None
    expect = str(params.get("expect") or "compatible").strip().lower() != "incompatible"
    tags = str(params.get("tags") or "").strip()
    with open_store() as db:
        if db.get_baseline(baseline) is None:
            raise ValueError("基线不存在：{}".format(baseline))
        if db.get_exploration(exploration_id) is None:
            raise ValueError("录制会话不存在：{}".format(exploration_id))
        return regression.add_case(db, case_id, baseline, exploration_id, expect, tags)


def _regression_list(params: dict) -> dict:
    with open_store() as db:
        cases = db.list_regression_cases(tag=str(params.get("tag") or ""))
        runs = db.list_regression_runs(limit=int(params.get("limit") or 10))
    return {"schema": regression.SCHEMA + ".list", "cases": cases, "runs": runs}


def _regression_run(params: dict) -> dict:
    with open_store() as db:
        return regression.run_suite(
            db,
            tag=str(params.get("tag") or ""),
            threshold=float(params.get("threshold") or explore.DEFAULT_THRESHOLD),
        )


def cmd_regression(args) -> int:
    params = {
        "case_id": getattr(args, "case_id", ""),
        "baseline": getattr(args, "baseline", ""),
        "exploration_id": getattr(args, "id", None),
        "expect": getattr(args, "expect", "compatible"),
        "tags": getattr(args, "tags", ""),
        "tag": getattr(args, "tag", ""),
        "threshold": getattr(args, "threshold", explore.DEFAULT_THRESHOLD),
        "limit": getattr(args, "limit", 10),
    }
    command = getattr(args, "regression_command", "")
    try:
        if command == "add":
            payload = _regression_add(params)
        elif command == "run":
            payload = _regression_run(params)
        else:
            payload = _regression_list(params)
    except ValueError as exc:
        print("E_ARG：{}".format(exc), file=sys.stderr)
        return EXIT_ARG

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif command == "run":
        print(
            "回归：{}（{} 通过 / {} 失败 / {} 错误，共 {}）".format(
                "PASS" if payload["ok"] else "FAIL",
                payload["passed"],
                payload["failed"],
                payload["errors"],
                payload["total"],
            )
        )
        for case in payload["cases"]:
            if case["verdict"] != "pass":
                print(
                    "  {}：{} 期望兼容={} 实际={} 覆盖={}".format(
                        case["case_id"],
                        case["verdict"],
                        case["expect_compatible"],
                        case["compatible"],
                        case["coverage"],
                    )
                )
    elif command == "add":
        print("已登记回归用例：{}".format(payload["case_id"]))
    else:
        for case in payload["cases"]:
            print("{:<10} {:<12} exp={}".format(case["case_id"], case["baseline_name"], case["expect_compatible"]))
        for run in payload["runs"][:5]:
            print("run#{:<4} total={} passed={} failed={} ok={}".format(
                run["_id"], run["total"], run["passed"], run["failed"], run["ok"]))
    if command == "run" and not payload["ok"]:
        return EXIT_GATE
    return EXIT_OK


def cmd_explore(args) -> int:
    """explore start|stop|list|show|draft。"""
    params = {
        "app": getattr(args, "app", ""),
        "goal": getattr(args, "goal", ""),
        "device_id": getattr(args, "device_id", ""),
        "exploration_id": getattr(args, "id", None),
        "out": getattr(args, "out", ""),
        "name": getattr(args, "name", ""),
        "threshold": getattr(args, "threshold", explore.DEFAULT_THRESHOLD),
    }
    command = getattr(args, "explore_command", "")
    try:
        if command == "start":
            payload = _explore_start(params)
        elif command == "stop":
            payload = _explore_stop(params)
        elif command == "draft":
            payload = _explore_draft(params)
        elif command == "baseline":
            payload = _explore_baseline(params)
        elif command == "check":
            payload = _explore_check(params)
        elif command == "list":
            with open_store() as db:
                payload = {"ok": True, "explorations": db.list_explorations()}
        elif command == "show":
            with open_store() as db:
                exploration = db.get_exploration(int(params["exploration_id"]))
                if exploration is None:
                    raise ValueError("录制会话不存在：{}".format(params["exploration_id"]))
                payload = {
                    "ok": True,
                    "exploration": exploration,
                    "snapshots": db.list_snapshots(int(params["exploration_id"])),
                }
        else:
            print("E_ARG：未知 explore 子命令", file=sys.stderr)
            return EXIT_ARG
    except ValueError as exc:
        print("E_ARG：{}".format(exc), file=sys.stderr)
        return EXIT_ARG
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif command == "draft":
        print("草案步骤：{}".format(" → ".join(s["action"] for s in payload["steps"])))
        print("就绪：{}；告警 {} 条".format(payload["ready"], len(payload["warnings"])))
    elif command == "check":
        print(
            "兼容：{}｜覆盖率 {}（阈值 {}）｜缺失断言 {}｜缺失步骤 {}".format(
                payload["compatible"],
                payload["coverage"],
                payload["threshold"],
                len(payload["missing"]),
                len(payload["step_misses"]),
            )
        )
        for miss in payload["step_misses"]:
            print("  失效步骤：{} 取值未出现：{}".format(miss["action"], miss["value"]))
    elif command == "list":
        for item in payload["explorations"]:
            print("#{:<4} {:<10} {:<10} {}".format(item["_id"], item["app"], item["state"], item["goal"]))
    else:
        print(json.dumps(payload, ensure_ascii=False))
    if command == "draft" and not payload["ready"]:
        return EXIT_GATE
    if command == "check" and not payload["compatible"]:
        return EXIT_GATE
    return EXIT_OK


def cmd_patrol(args) -> int:
    """巡检：采集证据 → 大模型诊断 →（--auto-fix）告警接管修复 → 验证。"""
    with open_store() as db:
        jobs = _jobs_summary(db)
        paused = db.get_meta("paused", "")
    evidence = {
        "paused": paused,
        "jobs": jobs,
        "checks": _doctor_checks(),
        "agent_log": _agent_log_tail(),
    }
    if brain.available():
        try:
            diagnosis = brain.chat(
                [
                    {"role": "system", "content": "你是巡检诊断助手。基于证据给出简明中文诊断与建议，不要输出任何密钥。"},
                    {"role": "user", "content": json.dumps(evidence, ensure_ascii=False)[:6000]},
                ]
            )
        except RuntimeError as exc:
            diagnosis = "（模型不可用：{}）".format(exc)
    else:
        diagnosis = "（QWEN 未配置，跳过模型诊断）"
    print("诊断：\n" + diagnosis)
    if not args.auto_fix:
        return EXIT_OK
    # 告警接管：白名单修复 + 修复后验证
    fixes = []
    if paused == "1" and args.resume:
        fixes.append({"fix": "resume", "result": _run_action("resume", {})})
    stuck = [job for job in jobs if job["state"] == "dispatched"]
    if stuck:
        fixes.append({"fix": "reset_stuck", "result": _reset_stuck(args.stuck_seconds, args.max_retries)})
    print("修复：" + json.dumps(fixes, ensure_ascii=False))
    with open_store() as db:
        after = _jobs_summary(db)
    remaining = [job for job in after if job["state"] == "dispatched"]
    print("验证：remaining_dispatched={}".format(len(remaining)))
    # 仍有异常：问千问要排障建议（知识百科通道），供下一次修复参考
    if remaining and args.consult:
        question = "手机预约助手巡检异常：{} 个作业卡在 dispatched，证据：{}".format(
            len(remaining), json.dumps(after, ensure_ascii=False)[:1500]
        )
        answer = _consult_sync(question, timeout=120)
        print("千问建议：" + (answer.get("answer") or answer.get("note") or ""))
    return EXIT_OK if not remaining or not stuck else EXIT_GATE


CHAT_HELP = """可用意图（自然语言即可）：
- 查看作业 / 检查环境 / 生成报告
- 暂停派发 / 恢复派发
- 复位卡住的作业
- 下发预约：例如“预约12月25日某演出内场，最高1280”
指令：/help 帮助，/state 当前状态，/exit 退出（或 Ctrl-D）"""


def cmd_chat(args) -> int:
    """会话模式：唤醒预约助手，由大模型决策 → 白名单动作 → 程序按流程执行，循环对话。"""
    if not brain.available():
        print("E_ENV：未找到 QWEN 配置（~/.local/share/dreambuddy/qwen.env）", file=sys.stderr)
        return EXIT_NET
    print("═══ 手机预约助手 · 会话模式 ═══")
    print("已唤醒。用自然语言下达指令，模型负责决策、程序按流程执行。输入 /help 查看，/exit 退出。\n")
    history: list[dict] = []
    while True:
        try:
            line = input("dream> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in ("/exit", "/quit", "exit", "quit"):
            break
        if line in ("/help", "help"):
            print(CHAT_HELP)
            continue
        with open_store() as db:
            state = {"paused": db.get_meta("paused", ""), "jobs": _jobs_summary(db)}
        if line in ("/state", "state"):
            print(json.dumps(state, ensure_ascii=False, indent=2))
            continue
        try:
            raw = brain.plan(line, state, history)
        except (RuntimeError, ValueError) as exc:
            print("E_NET：{}".format(exc))
            continue
        guarded = brain.guard_plan(raw)
        steps = guarded["plan"].get("steps", [])
        intent = guarded["plan"].get("intent", "")
        if not steps:
            print("（未映射到可执行动作）意图：{}".format(intent))
            for rej in guarded["rejected"]:
                print("  [拒绝] {}：{}".format(rej.get("action"), rej.get("reason")))
            continue
        print("意图：{}".format(intent))
        check = brain.precheck_plan(guarded["plan"])
        if not check["ok"]:
            for problem in check["problems"]:
                print("  [预检] 第{}步 {} 缺少 {}".format(problem["index"] + 1, problem["action"], "、".join(problem["missing"])))
            continue
        results = execute_steps(steps)
        for item in results:
            if item.get("ok"):
                payload = json.dumps(item.get("result"), ensure_ascii=False)
                print("  ✓ {}  {}".format(item["action"], payload[:300]))
            else:
                print("  ✗ {}  {}".format(item["action"], item.get("error", "")))
        # AI 验收官：不合格时按白名单补救并复检
        report = accept_execution(line, results)
        print_acceptance(report)
        for rej in guarded["rejected"]:
            print("  [拒绝] {}：{}".format(rej.get("action"), rej.get("reason")))
        history.append({"role": "user", "content": line})
        history.append(
            {
                "role": "assistant",
                "content": json.dumps(
                    [{"action": item["action"], "ok": item["ok"]} for item in results],
                    ensure_ascii=False,
                ),
            }
        )
        history = history[-8:]
        print()
    print("会话结束。")
    return EXIT_OK


# ── 小红书图文流水线：采集 → 分析/优化 → 生图 → 发布前填写 ──────────────────

NOTE_SOURCES = ("wallstreetcn", "sina")


def notes_dir() -> Path:
    directory = state_dir() / "notes"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _persist_note(kind: str, payload: dict) -> str:
    """把中间产物落盘，便于分步复跑与追溯。"""
    path = notes_dir() / "{}_{}.json".format(kind, time.strftime("%Y%m%d_%H%M%S"))
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def _guard_note(note: dict, timeout: int = 120) -> tuple[dict, dict]:
    """内容风控：扫描高风险表达；命中阻断项时让千问改写一次，仍不通过则保留原文交调用方拒绝。"""
    initial = content_guard.scan_note(note)
    report = {"initial": initial, "rewritten": False, "final": initial}
    if not initial["block"]:
        return note, report
    if not brain.available():
        report["error"] = "QWEN 未配置，无法自动改写"
        return note, report
    try:
        fixed = brain.rewrite_compliant(note, initial, timeout=timeout)
    except (RuntimeError, ValueError) as exc:
        report["error"] = str(exc)
        return note, report
    final = content_guard.scan_note(fixed)
    report.update({"rewritten": True, "final": final})
    return (fixed, report) if not final["block"] else (note, report)


def _run_phone_job(hit: dict, timeout: int = 180) -> dict:
    """入队一条手机作业并同步等待回执（采集/生图/发帖共用）。

    并存路由：剪映/抖音走本地 u2 驱动（不依赖无障碍），其余继续走网关 + Auto.js。
    切换：MRA_PHONE_DRIVER=auto（默认）| gateway（全走旧通道）| u2（强制本地）。
    """
    adapter = str(hit.get("adapter") or "")
    if phone_driver.use_local_driver(adapter):
        return phone_driver.run_local_job(hit, timeout=timeout)
    with open_store() as db:
        added = db.enqueue_job(hit)
        if added:
            db.add_event("info", "job_enqueued_note", hit.get("task_id"), {"adapter": hit.get("adapter")})
        row = db._fetchone("SELECT id FROM jobs WHERE task_id=? ORDER BY id DESC LIMIT 1", (hit["task_id"],))
    if not added:
        return {"state": "failed", "detail": {}, "note": "同一作业已存在（幂等去重）"}
    job_id = row["id"] if row else None
    deadline = time.time() + timeout
    while time.time() < deadline:
        with open_store() as db:
            res = db._fetchone(
                "SELECT state, detail_json FROM results WHERE job_id=? ORDER BY id DESC LIMIT 1", (job_id,)
            )
        if res:
            detail = json.loads(res["detail_json"] or "{}")
            state = "done" if res["state"] in ("ok", "done") else res["state"]
            return {"state": state, "detail": detail, "job_id": job_id}
        time.sleep(2)
    return {
        "state": "timeout",
        "detail": {},
        "note": "等待手机回执超时（{}s）".format(timeout),
        "job_id": job_id,
    }


def _generate_cover(prompt: str, timeout: int = 300) -> dict:
    task_id = "note:cover:{}".format(int(time.time() * 1000))
    fingerprint = hashlib.sha1(task_id.encode("utf-8")).hexdigest()[:16]
    hit = ingest_mod.build_hit(
        adapter="qianwen",
        task_id=task_id,
        fingerprint=fingerprint,
        at=int(time.time()),
        target={"target_id": "qianwen"},
        max_price=None,
    )
    hit["question"] = prompt
    hit["mode"] = "image"
    result = _run_phone_job(hit, timeout)
    result["materials"] = (result.get("detail") or {}).get("materials") or []
    return result


def _post_note(
    note: dict, images: list[str], publish: bool, timeout: int = 240,
    adapter: str = "xiaohongshu", media: str = "image",
) -> dict:
    # 发布前最后一道门禁：命中个股/交易动作/收益承诺一律拒绝下发
    findings = content_guard.scan_note(note)
    if findings["block"]:
        raise ContentGuardError(content_guard.describe(findings))
    title = str(note.get("title") or "").strip()
    if not title:
        raise ValueError("笔记缺少标题")
    task_id = "note:post:{}".format(int(time.time() * 1000))
    fingerprint = hashlib.sha1((task_id + title).encode("utf-8")).hexdigest()[:16]
    hit = ingest_mod.build_hit(
        adapter=adapter,
        task_id=task_id,
        fingerprint=fingerprint,
        at=int(time.time()),
        target={"target_id": adapter},
        max_price=None,
    )
    hit["note"] = {
        "title": title,
        "body": str(note.get("body") or ""),
        "topics": note.get("topics") or [],
        "images": images,
    }
    hit["publish_authorized"] = bool(publish)
    hit["media"] = "video" if str(media).lower() == "video" else "image"
    _warm_launch(adapter)
    return _run_phone_job(hit, timeout)


def _warm_launch(adapter: str) -> None:
    """下发前用 adb 启动目标 App：MIUI 上 Auto.js 的 app.launch 可能被带到无障碍设置页。"""
    activities = {
        "jianying": "com.lemon.lv/com.vega.main.MainActivity",
        "douyin": "com.ss.android.ugc.aweme/.splash.SplashActivity",
        "xiaohongshu": "com.xingin.xhs/.index.v2.IndexActivityV2",
    }
    activity = activities.get(adapter)
    if not activity:
        return
    try:
        subprocess.run(
            ["adb", "shell", "am", "start", "-n", activity],
            capture_output=True, timeout=12, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def _make_video(note: dict, timeout: int = 900, publish: bool = False) -> dict:
    """剪映 AI 文字成片：标题+正文 → 竖版口播视频 → 导出到相册；publish=True 时直接分享到抖音发布。"""
    title = str(note.get("title") or "").strip()
    body = str(note.get("body") or "").strip()
    if not title and not body:
        raise ValueError("视频缺少文案")
    text = (title + "\n" + body).strip()
    task_id = "video:make:{}".format(int(time.time() * 1000))
    fingerprint = hashlib.sha1((task_id + text[:200]).encode("utf-8")).hexdigest()[:16]
    hit = ingest_mod.build_hit(
        adapter="jianying",
        task_id=task_id,
        fingerprint=fingerprint,
        at=int(time.time()),
        target={"target_id": "jianying"},
        max_price=None,
    )
    hit["note"] = {"title": title, "body": body, "topics": note.get("topics") or []}
    hit["text"] = text[:2000]
    hit["share_douyin"] = bool(publish)
    _warm_launch("jianying")
    result = _run_phone_job(hit, timeout)
    if result.get("state") in ("ok", "done"):
        detail = result.get("detail") or {}
        result["video"] = detail.get("video") or ""
        result["video_path"] = _persist_note(
            "video", {"note": hit["note"], "video": result["video"], "steps": detail.get("steps") or []}
        )
    return result


DEFAULT_TRACKS = ("财经", "经济", "时事", "AI Agent", "数据服务")


def _source_list(value) -> list[str]:
    """把 --source / --sources 归一为合法资讯源列表（保序去重）。"""
    raw = value if isinstance(value, (list, tuple)) else str(value or "").replace("，", ",").split(",")
    out: list[str] = []
    for item in raw:
        name = str(item).strip()
        if name and name in NOTE_SOURCES and name not in out:
            out.append(name)
    return out or [NOTE_SOURCES[0]]


def _track_list(value) -> list[str]:
    raw = value if isinstance(value, (list, tuple)) else str(value or "").replace("，", ",").split(",")
    out: list[str] = []
    for item in raw:
        name = str(item).strip()
        if name and name not in out:
            out.append(name)
    return out[:5] or list(DEFAULT_TRACKS)


def _split_counts(total: int, parts: int) -> list[int]:
    total, parts = max(1, int(total)), max(1, int(parts))
    base, extra = divmod(total, parts)
    return [base + (1 if index < extra else 0) for index in range(parts)]


def _memo_text(title: str, body: str) -> str:
    return "[{}] {}\n{}".format(time.strftime("%m-%d %H:%M"), title.strip(), str(body or "").strip())


def _memo(op: str, text: str = "", tag: str = "", limit: int = 5, timeout: int = 120) -> dict:
    """手机笔记本：append 记录 / list 看标题 / read 读最近一条。"""
    task_id = "note:memo:{}".format(int(time.time() * 1000))
    fingerprint = hashlib.sha1(task_id.encode("utf-8")).hexdigest()[:16]
    hit = ingest_mod.build_hit(
        adapter="notes",
        task_id=task_id,
        fingerprint=fingerprint,
        at=int(time.time()),
        target={"target_id": "notes"},
        max_price=None,
    )
    hit["mode"] = op
    hit["text"] = str(text or "")
    hit["tag"] = str(tag or "")
    hit["limit"] = int(limit)
    return _run_phone_job(hit, timeout)


def _scout(
    tracks: list[str], limit: int, interact: bool, timeout: int = 420, adapter: str = "xiaohongshu"
) -> dict:
    """爆款侦察：按赛道关键词浏览平台信息流，读前 N 篇，可选点赞/收藏。"""
    task_id = "note:scout:{}".format(int(time.time() * 1000))
    fingerprint = hashlib.sha1(task_id.encode("utf-8")).hexdigest()[:16]
    hit = ingest_mod.build_hit(
        adapter=adapter,
        task_id=task_id,
        fingerprint=fingerprint,
        at=int(time.time()),
        target={"target_id": adapter},
        max_price=None,
    )
    hit["mode"] = "scout"
    hit["track"] = list(tracks)
    hit["limit"] = max(1, min(5, int(limit)))
    hit["interact"] = bool(interact)
    result = _run_phone_job(hit, timeout)
    if result["state"] == "done":
        detail = result.get("detail") or {}
        result["items"] = detail.get("items") or []
        result["interactions"] = detail.get("interactions") or []
        result["scout_path"] = _persist_note(
            "scout" if adapter == "xiaohongshu" else "{}_scout".format(adapter),
            {
                "track": list(tracks),
                "limit": hit["limit"],
                "items": result["items"],
                "interactions": result["interactions"],
            },
        )
    return result


def _trends(items: list[dict], extra: str = "", timeout: int = 120) -> tuple[dict, str]:
    trend = brain.analyze_trends(items, timeout=timeout)
    if extra:
        trend["extra_request"] = extra
    return trend, _persist_note("trend", trend)


def _collect_articles(
    sources: list[str],
    count: int,
    timeout: int,
    memo: bool = False,
    memo_tag: str = "素材",
    focus: str = "",
) -> dict:
    """多篇采集：按源分配篇数，逐篇落盘；每采完一篇立即写手机笔记本，避免中途遗忘。"""
    sources = _source_list(sources)
    counts = _split_counts(count, len(sources))
    articles: list[dict] = []
    paths: list[str] = []
    memo_states: list[str] = []
    errors: list[dict] = []
    seen_titles: set[str] = set()
    duplicates: list[str] = []
    degraded: list[str] = []
    for source, each in zip(sources, counts):
        if each <= 0:
            continue
        task_id = "note:collect:{}:{}".format(source, int(time.time() * 1000))
        fingerprint = hashlib.sha1(task_id.encode("utf-8")).hexdigest()[:16]
        hit = ingest_mod.build_hit(
            adapter="news",
            task_id=task_id,
            fingerprint=fingerprint,
            at=int(time.time()),
            target={"target_id": source, "source": source},
            max_price=None,
        )
        hit["source"] = source
        hit["count"] = each
        if focus:
            hit["focus"] = focus   # 千问推荐的今日选题，进 App 后先搜它
        result = _run_phone_job(hit, timeout)
        if result["state"] != "done":
            errors.append({"source": source, "state": result["state"], "note": result.get("note") or ""})
            continue
        detail = result.get("detail") or {}
        for step in detail.get("steps") or []:
            if step.get("action") == "news_search" and not step.get("ok"):
                degraded.append(source)   # 搜索没走通，已降级首页，明确记录
        batch = detail.get("articles") or ([detail.get("article")] if detail.get("article") else [])
        for article in batch:
            if not article:
                continue
            title_key = str(article.get("title") or "").strip()[:40]
            if re.search(r"请刷新|检查网络|暂无|没有更多|加载失败", title_key):
                errors.append({"source": source, "state": "skip", "note": "空态卡片：" + title_key})
                continue
            if title_key and title_key in seen_titles:
                duplicates.append(title_key)
                continue
            if title_key:
                seen_titles.add(title_key)
            articles.append(article)
            paths.append(_persist_note("article", article))
            if memo and (article.get("title") or article.get("body")):
                record = _memo(
                    "append",
                    text=_memo_text("素材：" + str(article.get("title") or source), str(article.get("body") or "")[:800]),
                    tag=memo_tag,
                    timeout=min(timeout, 120),
                )
                memo_states.append(record.get("state", ""))
    return {
        "state": "done" if articles else "failed",
        "focus": focus,
        "articles": articles,
        "article_paths": paths,
        "memo": memo_states,
        "errors": errors,
        "duplicates": duplicates,
        "degraded": degraded,
    }


def _load_json_arg(path: str) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("读取 JSON 失败：{}".format(exc)) from exc


def _print_note(result: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print("状态：{}".format(result.get("state", "")))
    if result.get("article_path"):
        print("文章已保存：{}".format(result["article_path"]))
        article = result.get("article") or {}
        if article.get("title"):
            print("文章标题：{}".format(article["title"]))
    note = result.get("note")
    if result.get("note_path") and isinstance(note, dict):
        print("标题：{}".format(note.get("title", "")))
        print("话题：{}".format(" ".join("#" + t for t in note.get("topics") or [])))
        print("正文：\n" + str(note.get("body", "")))
        print("已保存：{}".format(result["note_path"]))
    if result.get("materials"):
        print("素材：{}".format("、".join(result["materials"])))
    if result.get("prompt"):
        print("生图提示词：{}".format(result["prompt"]))
    if result.get("screenshot"):
        print("截图：{}".format(result["screenshot"]))
    if result.get("note_text"):
        print("说明：{}".format(result["note_text"]))
    elif isinstance(note, str) and note:
        print("说明：{}".format(note))


def cmd_xhs(args) -> int:
    """小红书图文流水线：采集文章 → 千问优化文案 → 千问生图 → 发布前填写。"""
    sub = getattr(args, "xhs_cmd", "")

    if sub == "scout":
        result = _scout(_track_list(args.track), args.limit, not args.no_interact, args.timeout)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("状态：{}（爆款 {} 篇，互动 {} 次）".format(
                result.get("state", ""), len(result.get("items") or []), len(result.get("interactions") or [])))
            for index, item in enumerate(result.get("items") or [], 1):
                print("{}. {} ｜ {} ｜ {}赞".format(
                    index, item.get("title", ""), item.get("keyword", ""), item.get("likes", "")))
            if result.get("scout_path"):
                print("已保存：{}".format(result["scout_path"]))
            if result.get("note"):
                print("说明：{}".format(result["note"]))
        return EXIT_OK if result["state"] == "done" else EXIT_GATE

    if sub == "memo":
        if getattr(args, "memo_cmd", "") == "add":
            text = args.text or ""
            if not text and args.file:
                text = Path(args.file).read_text(encoding="utf-8")
            if not text.strip():
                print("E_ARG：memo add 需要 --text 或 --file", file=sys.stderr)
                return EXIT_ARG
            result = _memo("append", text=text, tag=args.tag, timeout=args.timeout)
        else:
            result = _memo("list", limit=args.limit, timeout=args.timeout)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("状态：{}".format(result.get("state", "")))
            detail = result.get("detail") or {}
            if detail.get("notes"):
                for note in detail["notes"][: args.limit]:
                    print("· {}".format(note.get("title") or note))
            if detail.get("text"):
                print(str(detail["text"])[:800])
            if result.get("note"):
                print("说明：{}".format(result["note"]))
        return EXIT_OK if result["state"] == "done" else EXIT_GATE

    if sub == "trends":
        scout = _load_json_arg(args.scout)
        items = scout.get("items") or scout.get("samples") or []
        if not items:
            print("E_ARG：侦察结果里没有 items", file=sys.stderr)
            return EXIT_ARG
        if not brain.available():
            print("E_ENV：未找到 QWEN 配置（~/.local/share/dreambuddy/qwen.env）", file=sys.stderr)
            return EXIT_NET
        try:
            trend, path = _trends(items, args.extra, args.timeout)
        except (RuntimeError, ValueError) as exc:
            print("E_NET：{}".format(exc), file=sys.stderr)
            return EXIT_NET
        if args.json:
            print(json.dumps({"state": "done", "trend": trend, "trend_path": path}, ensure_ascii=False, indent=2))
        else:
            print("主题：{}".format("；".join(trend.get("themes") or [])))
            print("形式：{}".format("；".join(trend.get("formats") or [])))
            print("可扩展方向：")
            for item in trend.get("directions") or []:
                print("· {}".format(item))
            print("风格提示：{}".format(trend.get("style_brief", "")))
            print("已保存：{}".format(path))
        return EXIT_OK

    if sub == "collect":
        result = _collect_articles(
            _source_list(args.sources or args.source), args.count, args.timeout, memo=args.memo
        )
        if result["articles"] and not result.get("article"):
            result["article"] = result["articles"][0]
            result["article_path"] = result["article_paths"][0]
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("状态：{}（共 {} 篇）".format(result["state"], len(result["articles"])))
            for index, article in enumerate(result["articles"], 1):
                print("{}. {}（{} 字）".format(index, article.get("title", ""), len(article.get("body") or "")))
            for path in result["article_paths"]:
                print("已保存：{}".format(path))
            if result.get("memo"):
                print("笔记本：{}".format("、".join(result["memo"])))
            for error in result.get("errors") or []:
                print("WARN：{} {}".format(error.get("source"), error.get("state")))
        return EXIT_OK if result["state"] == "done" else EXIT_GATE

    if sub == "data":
        try:
            digest = cloud_data.collect(timeout=args.timeout)
        except cloud_data.CloudDataError as exc:
            print("E_NET：{}".format(exc), file=sys.stderr)
            return EXIT_NET
        path = _persist_note("data", digest)
        if args.json:
            print(json.dumps({"state": "done", "data": digest, "data_path": path}, ensure_ascii=False, indent=2))
            return EXIT_OK
        market = digest.get("market") or {}
        print("数据源：{}".format(digest.get("source")))
        print("基准：{} {}（24h {}%）".format(
            market.get("标的", ""), market.get("价格", ""), market.get("24h涨跌%", "")))
        print("基本面模块：{}".format("、".join((digest.get("fundamentals") or {}).keys())))
        research = digest.get("research") or {}
        print("研究评估：{}".format(json.dumps(research.get("评估") or {}, ensure_ascii=False)))
        print("技术图表：历史分位 {}；{}".format(
            (digest.get("technical") or {}).get("历史分位"), (digest.get("technical") or {}).get("点亮投影", "")[:80]))
        for error in digest.get("errors") or []:
            print("WARN：{}".format(error))
        print("已保存：{}".format(path))
        return EXIT_OK

    if sub == "compose":
        if not brain.available():
            print("E_ENV：未找到 QWEN 配置（~/.local/share/dreambuddy/qwen.env）", file=sys.stderr)
            return EXIT_NET
        article_args = args.article if isinstance(args.article, list) else [args.article]
        materials = [_load_json_arg(path) for path in article_args if path]
        if not materials:
            print("E_ARG：compose 至少需要一篇 --article", file=sys.stderr)
            return EXIT_ARG
        data = _load_json_arg(args.data) if args.data else None
        trend = _load_json_arg(args.trend) if args.trend else None
        try:
            note = brain.compose_note(
                materials[0], extra=args.extra, data=data, timeout=args.timeout,
                trend=trend, materials=materials,
            )
        except (RuntimeError, ValueError) as exc:
            print("E_NET：{}".format(exc), file=sys.stderr)
            return EXIT_NET
        result = {"state": "done", "note": note, "materials_used": len(materials), "guard": {}}
        note, result["guard"] = _guard_note(note, timeout=args.timeout)
        result["note"] = note
        result["guard_text"] = content_guard.describe(result["guard"]["final"])
        if result["guard"]["final"]["block"]:
            print("E_GATE：内容风控未通过 —— {}".format(result["guard_text"]), file=sys.stderr)
        result["note_path"] = _persist_note("note", note)
        result["prompt"] = brain.image_prompt(note, args.style)
        _print_note(result, args.json)
        return EXIT_OK if not result["guard"]["final"]["block"] else EXIT_GATE

    if sub == "cover":
        result = _cover(args)
        _print_note(result, args.json)
        return EXIT_OK if result["state"] in ("done", "ok") else EXIT_GATE

    if sub == "post":
        note = _load_json_arg(args.note)
        images = [args.image] if args.image else ["album_first"]
        try:
            result = _post_note(note, images, args.publish, args.timeout)
        except ContentGuardError as exc:
            print("E_GATE：内容风控未通过，禁止发布 —— {}".format(exc), file=sys.stderr)
            return EXIT_GATE
        result["screenshot"] = (result.get("detail") or {}).get("screenshot", "")
        result["note_text"] = (result.get("detail") or {}).get("note", "")
        _print_note(result, args.json)
        return EXIT_OK if result["state"] in ("done", "pending_human") else EXIT_GATE

    if sub == "run":
        steps: dict[str, dict] = {}
        collected = _collect_articles(_source_list(args.source), args.count, args.timeout)
        steps["collect"] = {
            "state": collected["state"],
            "articles": [article.get("title", "") for article in collected["articles"]],
        }
        if collected["state"] != "done":
            print(json.dumps({"steps": steps, "result": collected}, ensure_ascii=False, indent=2))
            return EXIT_GATE
        if not brain.available():
            print("E_ENV：未找到 QWEN 配置（~/.local/share/dreambuddy/qwen.env）", file=sys.stderr)
            return EXIT_NET
        data = None
        if not args.no_data:
            try:
                data = cloud_data.collect(timeout=args.data_timeout)
            except cloud_data.CloudDataError as exc:
                print("WARN：云端取数失败，继续用文章写稿：{}".format(exc), file=sys.stderr)
            else:
                steps["data"] = {
                    "state": "done",
                    "path": _persist_note("data", data),
                    "errors": data.get("errors") or [],
                    "market": (data.get("market") or {}).get("价格"),
                }
        trend = _load_json_arg(args.trend) if getattr(args, "trend", "") else None
        try:
            note = brain.compose_note(
                collected["articles"][0], extra=args.extra, data=data, timeout=args.timeout,
                trend=trend, materials=collected["articles"],
            )
        except (RuntimeError, ValueError) as exc:
            print("E_NET：{}".format(exc), file=sys.stderr)
            return EXIT_NET
        steps["compose"] = {"state": "done", "title": note["title"]}
        cover = _cover(
            argparse.Namespace(
                note="", title=note["title"], style=args.style, image="", timeout=args.cover_timeout
            )
        )
        steps["cover"] = {"state": cover["state"], "materials": cover.get("materials", [])}
        if cover["state"] not in ("done", "ok"):
            print(json.dumps({"steps": steps, "result": cover}, ensure_ascii=False, indent=2))
            return EXIT_GATE
        posted = _post_note(note, cover.get("materials") or ["album_first"], args.publish, args.timeout)
        steps["post"] = {"state": posted["state"], "screenshot": (posted.get("detail") or {}).get("screenshot", "")}
        payload = {"steps": steps, "note": note, "note_path": _persist_note("note", note)}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return EXIT_OK if posted["state"] in ("done", "pending_human") else EXIT_GATE

    if sub == "chain":
        return _chain(args)

    raise ValueError("未知子命令：{}".format(sub))


def _trend_memo(trend: dict | None) -> str:
    """把爆款分析结论整理成适合写进手机笔记本的短文本。"""
    trend = trend or {}
    parts: list[str] = []
    if trend.get("themes"):
        parts.append("主题：" + "；".join(trend["themes"]))
    if trend.get("formats"):
        parts.append("形式：" + "；".join(trend["formats"]))
    if trend.get("directions"):
        parts.append("可扩展方向：\n" + "\n".join("· " + str(item) for item in trend["directions"]))
    if trend.get("title_patterns"):
        parts.append("标题规律：" + "；".join(trend["title_patterns"]))
    style = trend.get("style") or {}
    style_parts = [str(style.get(key) or "") for key in ("tone", "structure", "density") if style.get(key)]
    if style.get("hooks"):
        style_parts.append("钩子：" + "；".join(style["hooks"]))
    if style_parts:
        parts.append("内容风格：" + "；".join(style_parts))
    if trend.get("learn"):
        parts.append("如何学习：" + "；".join(trend["learn"]))
    if trend.get("recommend"):
        lines = []
        for item in trend["recommend"][:3]:
            topic = str(item.get("topic") or "")
            angle = str(item.get("angle") or "")
            fmt = str(item.get("format") or "")
            why = str(item.get("why") or "")
            lines.append("· {}（{} / {}）{}".format(topic, angle, fmt, why))
        parts.append("今日推荐：\n" + "\n".join(lines))
    if trend.get("style_brief"):
        parts.append("风格：" + str(trend["style_brief"]))
    if trend.get("avoid"):
        parts.append("避开：" + "；".join(trend["avoid"]))
    return "\n".join(parts) or "暂无爆款结论"


def _chain(args) -> int:
    """完整链路：爆款侦察 → 笔记本 → 千问分析 → 笔记本 → 多篇采集（逐篇记录）→ 汇总 → 写稿 → 生图 → 发布。"""
    steps: dict[str, dict] = {}
    memo_states: list[str] = []

    scout = _scout(_track_list(args.track), args.scout_limit, not args.no_interact, args.scout_timeout)
    items = scout.get("items") or []
    steps["scout"] = {
        "state": scout["state"],
        "items": len(items),
        "interactions": len(scout.get("interactions") or []),
        "path": scout.get("scout_path", ""),
    }
    if scout["state"] != "done":
        print("WARN：爆款侦察未成功（{}），跳过风格分析继续".format(scout["state"]), file=sys.stderr)
    else:
        summary = "；".join(
            "{}({}赞｜{})".format(item.get("title", ""), item.get("likes", ""), item.get("keyword", ""))
            for item in items[:5]
        )
        memo_states.append(_memo("append", text=_memo_text("爆款侦察", summary), tag="爆款").get("state", ""))

    trend, trend_path = None, ""
    if items and brain.available():
        try:
            trend, trend_path = _trends(items, args.extra, args.trend_timeout)
        except (RuntimeError, ValueError) as exc:
            print("WARN：千问爆款分析失败，跳过风格参考：{}".format(exc), file=sys.stderr)
        else:
            steps["trend"] = {
                "state": "done",
                "path": trend_path,
                "themes": trend.get("themes") or [],
                "recommend": [item.get("topic", "") for item in trend.get("recommend") or []],
            }
            memo_states.append(
                _memo("append", text=_memo_text("发文模式与扩展方向", _trend_memo(trend)), tag="方向").get("state", "")
            )

    # 千问推荐的今日选题 → 去财经 App 搜素材；搜不到时降级读首页
    focus = ""
    if trend and trend.get("recommend"):
        focus = str((trend["recommend"][0] or {}).get("topic") or "").strip()
    collected = _collect_articles(
        _source_list(args.sources), args.count, args.timeout, memo=True, focus=focus
    )
    steps["collect"] = {
        "state": collected["state"],
        "focus": collected.get("focus", ""),
        "articles": [article.get("title", "") for article in collected["articles"]],
        "memo": collected.get("memo") or [],
        "errors": collected.get("errors") or [],
        "duplicates": collected.get("duplicates") or [],
        "degraded": collected.get("degraded") or [],
    }
    if collected["state"] != "done":
        print(json.dumps({"steps": steps, "result": collected}, ensure_ascii=False, indent=2))
        return EXIT_GATE
    if not brain.available():
        print("E_ENV：未找到 QWEN 配置（~/.local/share/dreambuddy/qwen.env）", file=sys.stderr)
        return EXIT_NET

    data = None
    if not args.no_data:
        try:
            data = cloud_data.collect(timeout=args.data_timeout)
        except cloud_data.CloudDataError as exc:
            print("WARN：云端取数失败，继续用文章写稿：{}".format(exc), file=sys.stderr)
        else:
            steps["data"] = {
                "state": "done",
                "path": _persist_note("data", data),
                "market": (data.get("market") or {}).get("价格"),
            }

    titles = "\n".join("- " + str(article.get("title") or "") for article in collected["articles"])
    memo_states.append(
        _memo(
            "append",
            text=_memo_text("发文汇总", "{}\n素材：\n{}".format(_trend_memo(trend), titles)),
            tag="汇总",
        ).get("state", "")
    )

    try:
        note = brain.compose_note(
            collected["articles"][0], extra=args.extra, data=data, timeout=args.timeout,
            trend=trend, materials=collected["articles"],
        )
    except (RuntimeError, ValueError) as exc:
        print("E_NET：{}".format(exc), file=sys.stderr)
        return EXIT_NET
    note, guard = _guard_note(note, timeout=args.timeout)
    steps["compose"] = {
        "state": "done", "title": note["title"], "materials": len(collected["articles"]),
        "guard": content_guard.describe(guard["final"]),
    }
    if guard["final"]["block"]:
        print("E_GATE：内容风控未通过，停止链路 —— {}".format(content_guard.describe(guard["final"])), file=sys.stderr)
        print(json.dumps({"steps": steps, "guard": guard, "note": note}, ensure_ascii=False, indent=2))
        return EXIT_GATE
    memo_states.append(
        _memo(
            "append",
            text=_memo_text("定稿：" + note["title"], str(note.get("body") or "")[:1200]),
            tag="定稿",
        ).get("state", "")
    )

    cover = _cover(
        argparse.Namespace(note="", title=note["title"], style=args.style, image="", timeout=args.cover_timeout)
    )
    steps["cover"] = {"state": cover["state"], "materials": cover.get("materials", [])}
    if cover["state"] not in ("done", "ok"):
        print(json.dumps({"steps": steps, "result": cover}, ensure_ascii=False, indent=2))
        return EXIT_GATE

    try:
        posted = _post_note(note, cover.get("materials") or ["album_first"], args.publish, args.timeout)
    except ContentGuardError as exc:
        print("E_GATE：内容风控未通过，禁止发布 —— {}".format(exc), file=sys.stderr)
        return EXIT_GATE
    steps["post"] = {
        "state": posted["state"],
        "screenshot": (posted.get("detail") or {}).get("screenshot", ""),
        "note_text": (posted.get("detail") or {}).get("note", ""),
    }
    payload = {
        "steps": steps,
        "memo": memo_states,
        "note": note,
        "note_path": _persist_note("note", note),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return EXIT_OK if posted["state"] in ("done", "pending_human") else EXIT_GATE


def _cover(args) -> dict:
    """封面：可直接指定现成图片，否则让千问生成并保存到相册。"""
    if args.image:
        path = Path(args.image).expanduser()
        if not path.is_file():
            raise ValueError("封面图片不存在：{}".format(args.image))
        return {"state": "done", "materials": [str(path)], "note": "使用指定图片"}
    title = args.title
    prompt = ""
    if args.note:
        note = _load_json_arg(args.note)
        title = title or str(note.get("title") or "")
        prompt = brain.image_prompt(note, args.style)
    if not prompt:
        prompt = brain.image_prompt({"title": title or "财经研究方法"}, args.style)
    result = _generate_cover(prompt, args.timeout)
    result["prompt"] = prompt
    return result


def _douyin_cover(note: dict, style: str, count: int, timeout: int = 300) -> dict:
    """抖音图文配图：按 pages 生成 N 张竖版卡片并保存到相册。

    生成顺序刻意反向：先出正文页、最后出封面页，让相册时间倒序的第一张就是封面。
    """
    count = max(1, min(6, int(count)))
    pages = [page for page in (note.get("pages") or []) if page.get("heading") or page.get("points")]
    if not pages:
        pages = [{"heading": str(note.get("title") or ""), "points": []}]
    targets = pages[:count][::-1]
    materials: list[str] = []
    prompts: list[str] = []
    for page in targets:
        prompt = brain.douyin_image_prompt(note, style, str(page.get("heading") or ""))
        prompts.append(prompt)
        result = _generate_cover(prompt, timeout)
        if result["state"] not in ("done", "ok"):
            return {
                "state": result["state"],
                "materials": materials,
                "prompts": prompts,
                "note": result.get("note") or "千问生图失败",
            }
        materials.extend(result.get("materials") or [])
    if not materials:
        return {"state": "needs_human", "materials": [], "prompts": prompts, "note": "未取到配图素材"}
    return {"state": "done", "materials": materials, "prompts": prompts, "count": len(materials)}


def _douyin_compose(args, materials: list[dict], trend: dict | None, data: dict | None) -> dict:
    return brain.compose_douyin_note(
        materials[0], extra=args.extra, data=data, timeout=args.timeout,
        trend=trend, materials=materials,
    )


def cmd_video(args) -> int:
    """剪映 AI 文字成片：文案 → 竖版视频 → 导出到相册。"""
    sub = getattr(args, "video_cmd", "")
    if sub != "make":
        raise ValueError("未知子命令：{}".format(sub))
    note = _load_json_arg(args.note)
    try:
        result = _make_video(note, args.timeout, getattr(args, "publish", False))
    except ValueError as exc:
        print("E_ARG：{}".format(exc), file=sys.stderr)
        return EXIT_ARG
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("状态：{}".format(result.get("state", "")))
        if result.get("video"):
            print("视频：{}".format(result["video"]))
        detail = result.get("detail") or {}
        for item in detail.get("steps") or []:
            print("- {} ok={} {}".format(item.get("action"), item.get("ok"), item.get("note") or ""))
        if detail.get("note"):
            print("说明：{}".format(detail["note"]))
    return EXIT_OK if result.get("state") in ("ok", "done") else EXIT_GATE


def cmd_douyin(args) -> int:
    """抖音图文流水线：采集文章 → 千问优化 → 千问配图 → 发布前填写（P0 图文）。"""
    sub = getattr(args, "douyin_cmd", "")

    if sub == "scout":
        result = _scout(
            _track_list(args.track), args.limit, not args.no_interact, args.timeout, adapter="douyin"
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("状态：{}（爆款 {} 条，互动 {} 次）".format(
                result.get("state", ""), len(result.get("items") or []), len(result.get("interactions") or [])))
            for index, item in enumerate(result.get("items") or [], 1):
                print("{}. {} ｜ {} ｜ {}赞".format(
                    index, item.get("title", ""), item.get("keyword", ""), item.get("likes", "")))
            if result.get("scout_path"):
                print("已保存：{}".format(result["scout_path"]))
            if result.get("note"):
                print("说明：{}".format(result["note"]))
        return EXIT_OK if result["state"] == "done" else EXIT_GATE

    if sub == "memo":
        if getattr(args, "memo_cmd", "") == "add":
            text = args.text or ""
            if not text and args.file:
                text = Path(args.file).read_text(encoding="utf-8")
            if not text.strip():
                print("E_ARG：memo add 需要 --text 或 --file", file=sys.stderr)
                return EXIT_ARG
            result = _memo("append", text=text, tag=args.tag, timeout=args.timeout)
        else:
            result = _memo("list", limit=args.limit, timeout=args.timeout)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("状态：{}".format(result.get("state", "")))
            detail = result.get("detail") or {}
            for note in (detail.get("notes") or [])[: args.limit]:
                print("· {}".format(note.get("title") or note))
            if detail.get("text"):
                print(str(detail["text"])[:800])
        return EXIT_OK if result["state"] == "done" else EXIT_GATE

    if sub == "trends":
        scout = _load_json_arg(args.scout)
        items = scout.get("items") or scout.get("samples") or []
        if not items:
            print("E_ARG：侦察结果里没有 items", file=sys.stderr)
            return EXIT_ARG
        if not brain.available():
            print("E_ENV：未找到 QWEN 配置（~/.local/share/dreambuddy/qwen.env）", file=sys.stderr)
            return EXIT_NET
        try:
            trend, path = _trends(items, args.extra, args.timeout)
        except (RuntimeError, ValueError) as exc:
            print("E_NET：{}".format(exc), file=sys.stderr)
            return EXIT_NET
        if args.json:
            print(json.dumps({"state": "done", "trend": trend, "trend_path": path}, ensure_ascii=False, indent=2))
        else:
            print("主题：{}".format("；".join(trend.get("themes") or [])))
            print("形式：{}".format("；".join(trend.get("formats") or [])))
            print("可扩展方向：")
            for item in trend.get("directions") or []:
                print("· {}".format(item))
            print("风格提示：{}".format(trend.get("style_brief", "")))
            print("已保存：{}".format(path))
        return EXIT_OK

    if sub == "collect":
        result = _collect_articles(
            _source_list(args.sources or args.source), args.count, args.timeout, memo=args.memo
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("状态：{}（共 {} 篇）".format(result["state"], len(result["articles"])))
            for index, article in enumerate(result["articles"], 1):
                print("{}. {}（{} 字）".format(index, article.get("title", ""), len(article.get("body") or "")))
            for path in result["article_paths"]:
                print("已保存：{}".format(path))
            for error in result.get("errors") or []:
                print("WARN：{} {}".format(error.get("source"), error.get("state")))
        return EXIT_OK if result["state"] == "done" else EXIT_GATE

    if sub == "data":
        try:
            digest = cloud_data.collect(timeout=args.timeout)
        except cloud_data.CloudDataError as exc:
            print("E_NET：{}".format(exc), file=sys.stderr)
            return EXIT_NET
        path = _persist_note("data", digest)
        if args.json:
            print(json.dumps({"state": "done", "data": digest, "data_path": path}, ensure_ascii=False, indent=2))
            return EXIT_OK
        market = digest.get("market") or {}
        print("数据源：{}".format(digest.get("source")))
        print("基准：{} {}（24h {}%）".format(
            market.get("标的", ""), market.get("价格", ""), market.get("24h涨跌%", "")))
        print("已保存：{}".format(path))
        return EXIT_OK

    if sub == "compose":
        if not brain.available():
            print("E_ENV：未找到 QWEN 配置（~/.local/share/dreambuddy/qwen.env）", file=sys.stderr)
            return EXIT_NET
        article_args = args.article if isinstance(args.article, list) else [args.article]
        materials = [_load_json_arg(path) for path in article_args if path]
        if not materials:
            print("E_ARG：compose 至少需要一篇 --article", file=sys.stderr)
            return EXIT_ARG
        data = _load_json_arg(args.data) if args.data else None
        trend = _load_json_arg(args.trend) if args.trend else None
        try:
            note = _douyin_compose(args, materials, trend, data)
        except (RuntimeError, ValueError) as exc:
            print("E_NET：{}".format(exc), file=sys.stderr)
            return EXIT_NET
        result = {"state": "done", "note": note, "materials_used": len(materials), "guard": {}}
        note, result["guard"] = _guard_note(note, timeout=args.timeout)
        result["note"] = note
        result["guard_text"] = content_guard.describe(result["guard"]["final"])
        if result["guard"]["final"]["block"]:
            print("E_GATE：内容风控未通过 —— {}".format(result["guard_text"]), file=sys.stderr)
        result["note_path"] = _persist_note("douyin_note", note)
        _print_note(result, args.json)
        return EXIT_OK if not result["guard"]["final"]["block"] else EXIT_GATE

    if sub == "cover":
        note = _load_json_arg(args.note) if args.note else {"title": args.title, "pages": []}
        result = _douyin_cover(note, args.style, args.count, args.timeout)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("状态：{}（{} 张）".format(result.get("state", ""), len(result.get("materials") or [])))
            for path in result.get("materials") or []:
                print("素材：{}".format(path))
            if result.get("note"):
                print("说明：{}".format(result["note"]))
        return EXIT_OK if result["state"] in ("done", "ok") else EXIT_GATE

    if sub == "post":
        note = _load_json_arg(args.note)
        images = [args.image] if args.image else ["album_first"]
        try:
            result = _post_note(note, images, args.publish, args.timeout, adapter="douyin", media=args.media)
        except ContentGuardError as exc:
            print("E_GATE：内容风控未通过，禁止发布 —— {}".format(exc), file=sys.stderr)
            return EXIT_GATE
        result["screenshot"] = (result.get("detail") or {}).get("screenshot", "")
        result["note_text"] = (result.get("detail") or {}).get("note", "")
        _print_note(result, args.json)
        return EXIT_OK if result["state"] in ("done", "pending_human") else EXIT_GATE

    if sub == "chain":
        return _douyin_chain(args)

    raise ValueError("未知子命令：{}".format(sub))


def _douyin_chain(args) -> int:
    """抖音图文完整链路：爆款侦察 → 千问分析 → 多篇采集 → 写稿 → 配图 → 发布前填写。"""
    steps: dict[str, dict] = {}
    memo_states: list[str] = []

    scout = _scout(
        _track_list(args.track), args.scout_limit, not args.no_interact, args.scout_timeout,
        adapter="douyin",
    )
    items = scout.get("items") or []
    steps["scout"] = {
        "state": scout["state"],
        "items": len(items),
        "interactions": len(scout.get("interactions") or []),
        "path": scout.get("scout_path", ""),
    }
    if scout["state"] != "done":
        print("WARN：爆款侦察未成功（{}），跳过风格分析继续".format(scout["state"]), file=sys.stderr)
    else:
        summary = "；".join(
            "{}({}赞｜{})".format(item.get("title", ""), item.get("likes", ""), item.get("keyword", ""))
            for item in items[:5]
        )
        memo_states.append(_memo("append", text=_memo_text("抖音爆款侦察", summary), tag="爆款").get("state", ""))

    trend, trend_path = None, ""
    if items and brain.available():
        try:
            trend, trend_path = _trends(items, args.extra, args.trend_timeout)
        except (RuntimeError, ValueError) as exc:
            print("WARN：千问爆款分析失败，跳过风格参考：{}".format(exc), file=sys.stderr)
        else:
            steps["trend"] = {
                "state": "done",
                "path": trend_path,
                "themes": trend.get("themes") or [],
                "recommend": [item.get("topic", "") for item in trend.get("recommend") or []],
            }
            memo_states.append(
                _memo("append", text=_memo_text("抖音写作方向", _trend_memo(trend)), tag="方向").get("state", "")
            )

    focus = ""
    if trend and trend.get("recommend"):
        focus = str((trend["recommend"][0] or {}).get("topic") or "").strip()
    collected = _collect_articles(
        _source_list(args.sources), args.count, args.timeout, memo=True, focus=focus
    )
    steps["collect"] = {
        "state": collected["state"],
        "focus": collected.get("focus", ""),
        "articles": [article.get("title", "") for article in collected["articles"]],
        "memo": collected.get("memo") or [],
        "errors": collected.get("errors") or [],
        "duplicates": collected.get("duplicates") or [],
        "degraded": collected.get("degraded") or [],
    }
    if collected["state"] != "done":
        print(json.dumps({"steps": steps, "result": collected}, ensure_ascii=False, indent=2))
        return EXIT_GATE
    if not brain.available():
        print("E_ENV：未找到 QWEN 配置（~/.local/share/dreambuddy/qwen.env）", file=sys.stderr)
        return EXIT_NET

    data = None
    if not args.no_data:
        try:
            data = cloud_data.collect(timeout=args.data_timeout)
        except cloud_data.CloudDataError as exc:
            print("WARN：云端取数失败，继续用文章写稿：{}".format(exc), file=sys.stderr)
        else:
            steps["data"] = {
                "state": "done",
                "path": _persist_note("data", data),
                "market": (data.get("market") or {}).get("价格"),
            }

    note = None
    try:
        note = _douyin_compose(args, collected["articles"], trend, data)
    except (RuntimeError, ValueError) as exc:
        print("E_NET：{}".format(exc), file=sys.stderr)
        return EXIT_NET
    note, guard = _guard_note(note, timeout=args.timeout)
    steps["compose"] = {
        "state": "done", "title": note["title"], "pages": len(note.get("pages") or []),
        "guard": content_guard.describe(guard["final"]),
    }
    if guard["final"]["block"]:
        print("E_GATE：内容风控未通过，停止链路 —— {}".format(content_guard.describe(guard["final"])), file=sys.stderr)
        print(json.dumps({"steps": steps, "guard": guard, "note": note}, ensure_ascii=False, indent=2))
        return EXIT_GATE
    memo_states.append(
        _memo("append", text=_memo_text("抖音定稿：" + note["title"], str(note.get("body") or "")[:1200]), tag="定稿")
        .get("state", "")
    )

    cover = _douyin_cover(note, args.style, args.image_count, args.cover_timeout)
    steps["cover"] = {"state": cover["state"], "materials": cover.get("materials", [])}
    if cover["state"] not in ("done", "ok"):
        print(json.dumps({"steps": steps, "result": cover}, ensure_ascii=False, indent=2))
        return EXIT_GATE

    try:
        posted = _post_note(note, cover.get("materials") or ["album_first"], args.publish, args.timeout, adapter="douyin")
    except ContentGuardError as exc:
        print("E_GATE：内容风控未通过，禁止发布 —— {}".format(exc), file=sys.stderr)
        return EXIT_GATE
    steps["post"] = {
        "state": posted["state"],
        "screenshot": (posted.get("detail") or {}).get("screenshot", ""),
        "note_text": (posted.get("detail") or {}).get("note", ""),
    }
    payload = {
        "steps": steps,
        "memo": memo_states,
        "note": note,
        "note_path": _persist_note("douyin_note", note),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return EXIT_OK if posted["state"] in ("done", "pending_human") else EXIT_GATE


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mra", description="手机预约助手：命中→手机端预约动作编排")
    sub = parser.add_subparsers(dest="command", required=True)

    ing = sub.add_parser("ingest", help="归一上游命中并入队为预约作业")
    ing.add_argument("--ra-cli", default="", help="上游 ra.py 路径（经公开 CLI 只读消费）")
    ing.add_argument("--source", default="", help="file:<path> 本地 feed（离线/测试）")
    ing.add_argument("--device-id", default="", help="绑定到指定设备执行（多设备并发）")
    ing.set_defaults(func=cmd_ingest)

    devices = sub.add_parser("devices", help="设备心跳与在线状态（多设备并发）")
    devices.add_argument("--offline-after", type=int, default=60, help="超过多少秒无心跳视为离线")
    devices.add_argument("--json", action="store_true")
    devices.set_defaults(func=cmd_devices)

    reg = sub.add_parser("regression", help="回归任务集：基线 + 录制批量回归")
    reg_sub = reg.add_subparsers(dest="regression_command", required=True)
    r_add = reg_sub.add_parser("add", help="登记回归用例")
    r_add.add_argument("--case-id", required=True)
    r_add.add_argument("--baseline", required=True, help="适配器基线名")
    r_add.add_argument("--id", type=int, required=True, help="录制会话 ID")
    r_add.add_argument("--expect", choices=("compatible", "incompatible"), default="compatible")
    r_add.add_argument("--tags", default="", help="逗号分隔标签，便于 --tag 过滤")
    r_add.add_argument("--json", action="store_true")
    r_add.set_defaults(func=cmd_regression)
    r_list = reg_sub.add_parser("list", help="用例与运行历史")
    r_list.add_argument("--tag", default="")
    r_list.add_argument("--limit", type=int, default=10)
    r_list.add_argument("--json", action="store_true")
    r_list.set_defaults(func=cmd_regression)
    r_run = reg_sub.add_parser("run", help="批量执行回归（失败退出码 3）")
    r_run.add_argument("--tag", default="")
    r_run.add_argument("--threshold", type=float, default=0.8)
    r_run.add_argument("--json", action="store_true")
    r_run.set_defaults(func=cmd_regression)

    jobs = sub.add_parser("jobs", help="列出预约作业")
    jobs.add_argument("--json", action="store_true")
    jobs.add_argument(
        "--state",
        default="",
        help="pending|dispatched|done|failed|unknown|cooldown|pending_human|takeover|order_unknown",
    )
    jobs.set_defaults(func=cmd_jobs)

    gw = sub.add_parser("gateway", help="启动本地指令网关（前台）")
    gw.add_argument("--host", default="127.0.0.1")
    gw.add_argument("--port", type=int, default=8765)
    gw.set_defaults(func=cmd_gateway)

    token = sub.add_parser("token", help="查看/生成网关 Token")
    token.add_argument("--show", action="store_true")
    token.set_defaults(func=cmd_token)

    doctor = sub.add_parser("doctor", help="环境自检")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=cmd_doctor)

    report = sub.add_parser("report", help="reservation.v1 报告")
    report.add_argument("--json", action="store_true")
    report.set_defaults(func=cmd_report)

    pause = sub.add_parser("pause", help="暂停派发")
    pause.set_defaults(func=cmd_pause)

    resume = sub.add_parser("resume", help="恢复派发")
    resume.set_defaults(func=cmd_resume)

    ask = sub.add_parser("ask", help="自然语言→白名单计划（--execute 人工授权执行）")
    ask.add_argument("text", help="自然语言指令")
    ask.add_argument("--json", action="store_true")
    ask.add_argument("--execute", action="store_true", help="人工授权：执行该白名单计划")
    ask.set_defaults(func=cmd_ask)

    consult = sub.add_parser("consult", help="问手机端千问 App（知识百科通道），等待答案")
    consult.add_argument("question", nargs="+", help="要咨询的问题")
    consult.add_argument("--timeout", type=int, default=150, help="等待答复秒数（默认 150）")
    consult.set_defaults(func=cmd_consult)

    knowledge_parser = sub.add_parser("knowledge", help="结构化知识问答（引用 + 置信度，只读）")
    knowledge_sub = knowledge_parser.add_subparsers(dest="knowledge_command", required=True)
    k_ask = knowledge_sub.add_parser("ask", help="问千问并返回 knowledge.v1 结构化结果")
    k_ask.add_argument("question", help="问题")
    k_ask.add_argument("--app", default="", help="关联平台（如 bilibili），用于缓存隔离与提问上下文")
    k_ask.add_argument("--max-age", type=int, default=knowledge.DEFAULT_TTL_SECONDS, help="缓存有效期秒数")
    k_ask.add_argument("--no-cache", action="store_true", help="忽略缓存强制实时询问")
    k_ask.add_argument("--timeout", type=int, default=150, help="等待答复秒数（默认 150）")
    k_ask.add_argument("--json", action="store_true")
    k_ask.set_defaults(func=cmd_knowledge)

    dispatch = sub.add_parser("dispatch", help="自然语言→下发一条预约作业")
    dispatch.add_argument("text", help="自然语言预约指令，如：帮我预约12月25日某演出内场")
    dispatch.add_argument("--json", action="store_true")
    dispatch.add_argument("--dry-run", action="store_true", help="只解析不写入")
    dispatch.set_defaults(func=cmd_dispatch)

    reconcile = sub.add_parser("reconcile", help="订单对账：列出/收敛 order_unknown 作业")
    reconcile.add_argument("--job", type=int, default=None, help="作业 ID（不传则只列出待对账作业）")
    reconcile.add_argument("--state", default="", choices=["", "done", "failed"], help="对账终态")
    reconcile.add_argument("--order-id", default="", help="对账确认的订单号")
    reconcile.add_argument("--note", default="", help="对账说明/证据")
    reconcile.add_argument("--json", action="store_true")
    reconcile.set_defaults(func=cmd_reconcile)

    explore_parser = sub.add_parser("explore", help="探索录制：采集页面快照并生成适配器草案")
    explore_sub = explore_parser.add_subparsers(dest="explore_command", required=True)
    e_start = explore_sub.add_parser("start", help="开始录制会话")
    e_start.add_argument("--app", required=True, help="平台/包名标识，如 bilibili")
    e_start.add_argument("--goal", required=True, help="录制目标，如 买周杰伦演唱会门票")
    e_start.add_argument("--device-id", default="", help="设备标识（多设备时隔离）")
    e_start.add_argument("--json", action="store_true")
    e_start.set_defaults(func=cmd_explore)
    e_stop = explore_sub.add_parser("stop", help="结束录制会话")
    e_stop.add_argument("--id", type=int, required=True, help="录制会话 ID")
    e_stop.add_argument("--json", action="store_true")
    e_stop.set_defaults(func=cmd_explore)
    e_list = explore_sub.add_parser("list", help="列出录制会话")
    e_list.add_argument("--json", action="store_true")
    e_list.set_defaults(func=cmd_explore)
    e_show = explore_sub.add_parser("show", help="查看录制会话与快照")
    e_show.add_argument("--id", type=int, required=True)
    e_show.add_argument("--json", action="store_true")
    e_show.set_defaults(func=cmd_explore)
    e_draft = explore_sub.add_parser("draft", help="由快照生成适配器草案")
    e_draft.add_argument("--id", type=int, required=True, help="录制会话 ID")
    e_draft.add_argument("--out", default="", help="源码草案输出路径（默认只打印 JSON）")
    e_draft.add_argument("--json", action="store_true")
    e_draft.set_defaults(func=cmd_explore)
    e_baseline = explore_sub.add_parser("baseline", help="把录制固化为适配器基线")
    e_baseline.add_argument("--id", type=int, required=True, help="录制会话 ID")
    e_baseline.add_argument("--name", required=True, help="基线/适配器名")
    e_baseline.add_argument("--json", action="store_true")
    e_baseline.set_defaults(func=cmd_explore)
    e_check = explore_sub.add_parser("check", help="回放兼容门禁：基线 vs 新录制")
    e_check.add_argument("--name", required=True, help="基线名")
    e_check.add_argument("--id", type=int, required=True, help="新录制会话 ID")
    e_check.add_argument("--threshold", type=float, default=0.8, help="断言命中率阈值（默认 0.8）")
    e_check.add_argument("--json", action="store_true")
    e_check.set_defaults(func=cmd_explore)

    patrol = sub.add_parser("patrol", help="巡检+大模型诊断（--auto-fix 告警接管修复验证）")
    patrol.add_argument("--auto-fix", action="store_true", help="告警接管：白名单修复并验证")
    patrol.add_argument("--resume", action="store_true", help="auto-fix 时若处于暂停则恢复派发")
    patrol.add_argument("--stuck-seconds", type=int, default=180, help="派发超时判卡住的秒数（默认 180）")
    patrol.add_argument("--max-retries", type=int, default=2, help="单作业复位重试上限（默认 2）")
    patrol.add_argument("--consult", action="store_true", help="仍有异常时问千问 App 要排障建议")
    patrol.set_defaults(func=cmd_patrol)

    xhs = sub.add_parser("xhs", help="小红书图文流水线：采集→云端数据→千问优化/生图→发布前填写")
    xhs_sub = xhs.add_subparsers(dest="xhs_cmd", required=True)

    xs = xhs_sub.add_parser("scout", help="爆款侦察：按赛道关键词浏览小红书，读前 N 篇并可点赞/收藏")
    xs.add_argument("--track", default="财经,经济,时事,AI Agent,数据服务", help="赛道关键词，逗号分隔")
    xs.add_argument("--limit", type=int, default=5, help="读取篇数（1-8）")
    xs.add_argument("--no-interact", action="store_true", help="只浏览不点赞/收藏")
    xs.add_argument("--timeout", type=int, default=420, help="等待手机回执秒数（默认 420）")
    xs.add_argument("--json", action="store_true")
    xs.set_defaults(func=cmd_xhs)

    xm = xhs_sub.add_parser("memo", help="手机笔记本：记录素材/结论，或回看最近笔记")
    xm_sub = xm.add_subparsers(dest="memo_cmd", required=True)
    xm_add = xm_sub.add_parser("add", help="新建一条笔记")
    xm_add.add_argument("--text", default="", help="要写入的文本")
    xm_add.add_argument("--file", default="", help="从本地文件读入文本")
    xm_add.add_argument("--tag", default="", help="标签（如 素材/方向/汇总）")
    xm_add.add_argument("--timeout", type=int, default=120)
    xm_add.add_argument("--json", action="store_true")
    xm_add.set_defaults(func=cmd_xhs)
    xm_list = xm_sub.add_parser("list", help="读取最近笔记标题")
    xm_list.add_argument("--limit", type=int, default=5)
    xm_list.add_argument("--timeout", type=int, default=120)
    xm_list.add_argument("--json", action="store_true")
    xm_list.set_defaults(func=cmd_xhs)

    xt = xhs_sub.add_parser("trends", help="千问分析爆款样本：主题/形式/可扩展方向/风格提示")
    xt.add_argument("--scout", required=True, help="scout 产出的 JSON 路径")
    xt.add_argument("--extra", default="", help="额外分析要求")
    xt.add_argument("--timeout", type=int, default=120)
    xt.add_argument("--json", action="store_true")
    xt.set_defaults(func=cmd_xhs)

    xc = xhs_sub.add_parser("collect", help="采集财经文章（支持多源多篇）")
    xc.add_argument("--source", default="wallstreetcn", choices=list(NOTE_SOURCES), help="单一来源（兼容旧用法）")
    xc.add_argument("--sources", default="", help="多来源，逗号分隔：wallstreetcn,sina")
    xc.add_argument("--count", type=int, default=1, help="采集总篇数（默认 1，至少 3 篇建议 3）")
    xc.add_argument("--memo", action="store_true", help="每采完一篇立即写手机笔记本")
    xc.add_argument("--timeout", type=int, default=300, help="等待手机回执秒数（默认 300）")
    xc.add_argument("--json", action="store_true")
    xc.set_defaults(func=cmd_xhs)

    xd = xhs_sub.add_parser("data", help="从云端数据面板取基本面/数据研究/技术图表摘要")
    xd.add_argument("--timeout", type=int, default=60, help="单接口超时秒数（默认 60）")
    xd.add_argument("--json", action="store_true")
    xd.set_defaults(func=cmd_xhs)

    xp = xhs_sub.add_parser("compose", help="文章(可多篇)+云端数据+爆款风格 → 千问写小红书笔记")
    xp.add_argument("--article", required=True, action="append", help="collect 产出的文章 JSON 路径（可重复）")
    xp.add_argument("--data", default="", help="data 产出的摘要 JSON 路径（可选）")
    xp.add_argument("--trend", default="", help="trends 产出的风格参考 JSON 路径（可选）")
    xp.add_argument("--extra", default="", help="额外的优化要求（如：更口语化/突出数据）")
    xp.add_argument("--style", default="", help="封面风格提示")
    xp.add_argument("--timeout", type=int, default=120)
    xp.add_argument("--json", action="store_true")
    xp.set_defaults(func=cmd_xhs)

    xv = xhs_sub.add_parser("cover", help="生成封面图（千问生图并保存到相册）")
    xv.add_argument("--note", default="", help="笔记 JSON 路径")
    xv.add_argument("--title", default="", help="无笔记文件时用标题生成提示词")
    xv.add_argument("--style", default="", help="封面风格")
    xv.add_argument("--image", default="", help="直接指定现成图片，跳过千问生图")
    xv.add_argument("--timeout", type=int, default=300, help="等待生图秒数（默认 300）")
    xv.add_argument("--json", action="store_true")
    xv.set_defaults(func=cmd_xhs)

    xq = xhs_sub.add_parser("post", help="填标题正文并停在发布前（--publish 才点发布）")
    xq.add_argument("--note", required=True, help="笔记 JSON 路径")
    xq.add_argument("--image", default="", help="指定素材路径（默认相册第一张）")
    xq.add_argument("--publish", action="store_true", help="人工授权：直接点发布")
    xq.add_argument("--timeout", type=int, default=240)
    xq.add_argument("--json", action="store_true")
    xq.set_defaults(func=cmd_xhs)

    xr = xhs_sub.add_parser("run", help="完整流水线：采集→数据→优化→生图→发布前填写")
    xr.add_argument("--source", default="wallstreetcn", choices=list(NOTE_SOURCES))
    xr.add_argument("--count", type=int, default=1, help="采集篇数（默认 1）")
    xr.add_argument("--trend", default="", help="爆款风格参考 JSON（可选）")
    xr.add_argument("--extra", default="", help="额外优化要求")
    xr.add_argument("--style", default="", help="封面风格")
    xr.add_argument("--no-data", action="store_true", help="跳过云端数据（只用文章）")
    xr.add_argument("--data-timeout", type=int, default=60)
    xr.add_argument("--cover-timeout", type=int, default=300)
    xr.add_argument("--publish", action="store_true", help="人工授权：最后直接点发布")
    xr.add_argument("--timeout", type=int, default=240)
    xr.set_defaults(func=cmd_xhs)

    xch = xhs_sub.add_parser(
        "chain", help="完整链路：爆款侦察→笔记本→千问分析→多篇采集(逐篇记录)→汇总→写稿→生图→发布"
    )
    xch.add_argument("--track", default="财经,经济,时事,AI Agent,数据服务", help="赛道关键词，逗号分隔")
    xch.add_argument("--scout-limit", type=int, default=5, help="爆款读取篇数（1-8）")
    xch.add_argument("--no-interact", action="store_true", help="爆款笔记只浏览不点赞/收藏")
    xch.add_argument("--scout-timeout", type=int, default=420)
    xch.add_argument("--sources", default="wallstreetcn,sina", help="资讯来源，逗号分隔")
    xch.add_argument("--count", type=int, default=3, help="采集总篇数（默认 3）")
    xch.add_argument("--extra", default="", help="额外优化要求")
    xch.add_argument("--style", default="", help="封面风格提示")
    xch.add_argument("--no-data", action="store_true", help="跳过云端数据")
    xch.add_argument("--data-timeout", type=int, default=60)
    xch.add_argument("--trend-timeout", type=int, default=120)
    xch.add_argument("--cover-timeout", type=int, default=300)
    xch.add_argument("--publish", action="store_true", help="人工授权：最后直接点发布")
    xch.add_argument("--timeout", type=int, default=360, help="等待手机回执秒数（默认 360）")
    xch.set_defaults(func=cmd_xhs)

    dy = sub.add_parser("douyin", help="抖音图文流水线：侦察→采集→千问写稿/配图→发布前填写（P0 图文）")
    dy_sub = dy.add_subparsers(dest="douyin_cmd", required=True)

    ds = dy_sub.add_parser("scout", help="爆款侦察：按赛道关键词搜索，读前 N 条视频卡片")
    ds.add_argument("--track", default="财经,经济,时事,AI Agent,数据服务", help="赛道关键词，逗号分隔")
    ds.add_argument("--limit", type=int, default=5, help="读取条数（1-8）")
    ds.add_argument("--no-interact", action="store_true", help="只浏览不点赞")
    ds.add_argument("--timeout", type=int, default=420, help="等待手机回执秒数（默认 420）")
    ds.add_argument("--json", action="store_true")
    ds.set_defaults(func=cmd_douyin)

    dm = dy_sub.add_parser("memo", help="手机笔记本：记录素材/结论，或回看最近笔记")
    dm_sub = dm.add_subparsers(dest="memo_cmd", required=True)
    dm_add = dm_sub.add_parser("add", help="新建一条笔记")
    dm_add.add_argument("--text", default="", help="要写入的文本")
    dm_add.add_argument("--file", default="", help="从本地文件读入文本")
    dm_add.add_argument("--tag", default="", help="标签（如 素材/方向/汇总）")
    dm_add.add_argument("--timeout", type=int, default=120)
    dm_add.add_argument("--json", action="store_true")
    dm_add.set_defaults(func=cmd_douyin)
    dm_list = dm_sub.add_parser("list", help="读取最近笔记标题")
    dm_list.add_argument("--limit", type=int, default=5)
    dm_list.add_argument("--timeout", type=int, default=120)
    dm_list.add_argument("--json", action="store_true")
    dm_list.set_defaults(func=cmd_douyin)

    dt = dy_sub.add_parser("trends", help="千问分析爆款样本：主题/形式/可扩展方向/风格提示")
    dt.add_argument("--scout", required=True, help="scout 产出的 JSON 路径")
    dt.add_argument("--extra", default="", help="额外分析要求")
    dt.add_argument("--timeout", type=int, default=120)
    dt.add_argument("--json", action="store_true")
    dt.set_defaults(func=cmd_douyin)

    dc = dy_sub.add_parser("collect", help="采集财经文章（支持多源多篇）")
    dc.add_argument("--source", default="wallstreetcn", choices=list(NOTE_SOURCES), help="单一来源（兼容旧用法）")
    dc.add_argument("--sources", default="", help="多来源，逗号分隔：wallstreetcn,sina")
    dc.add_argument("--count", type=int, default=1, help="采集总篇数（默认 1）")
    dc.add_argument("--memo", action="store_true", help="每采完一篇立即写手机笔记本")
    dc.add_argument("--timeout", type=int, default=300, help="等待手机回执秒数（默认 300）")
    dc.add_argument("--json", action="store_true")
    dc.set_defaults(func=cmd_douyin)

    dd = dy_sub.add_parser("data", help="从云端数据面板取基本面/数据研究/技术图表摘要")
    dd.add_argument("--timeout", type=int, default=60, help="单接口超时秒数（默认 60）")
    dd.add_argument("--json", action="store_true")
    dd.set_defaults(func=cmd_douyin)

    dp = dy_sub.add_parser("compose", help="文章(可多篇)+云端数据+爆款风格 → 千问写抖音图文")
    dp.add_argument("--article", required=True, action="append", help="collect 产出的文章 JSON 路径（可重复）")
    dp.add_argument("--data", default="", help="data 产出的摘要 JSON 路径（可选）")
    dp.add_argument("--trend", default="", help="trends 产出的风格参考 JSON 路径（可选）")
    dp.add_argument("--extra", default="", help="额外的优化要求（如：更口语化/突出数据）")
    dp.add_argument("--timeout", type=int, default=120)
    dp.add_argument("--json", action="store_true")
    dp.set_defaults(func=cmd_douyin)

    dv = dy_sub.add_parser("cover", help="生成图文配图（千问生图并保存到相册）")
    dv.add_argument("--note", default="", help="图文 JSON 路径")
    dv.add_argument("--title", default="", help="无图文文件时用标题生成提示词")
    dv.add_argument("--style", default="", help="配图风格")
    dv.add_argument("--count", type=int, default=1, help="生成张数（1-6，默认 1）")
    dv.add_argument("--timeout", type=int, default=300, help="等待生图秒数（默认 300）")
    dv.add_argument("--json", action="store_true")
    dv.set_defaults(func=cmd_douyin)

    dq = dy_sub.add_parser("post", help="选图文素材并填描述，停在发布前（--publish 才点发布）")
    dq.add_argument("--note", required=True, help="图文 JSON 路径")
    dq.add_argument("--image", default="", help="指定素材路径（默认相册第一张）")
    dq.add_argument("--media", default="image", choices=["image", "video"], help="发布素材类型：图文/视频")
    dq.add_argument("--publish", action="store_true", help="人工授权：直接点发布")
    dq.add_argument("--timeout", type=int, default=300)
    dq.add_argument("--json", action="store_true")
    dq.set_defaults(func=cmd_douyin)

    dch = dy_sub.add_parser(
        "chain", help="完整链路：爆款侦察→千问分析→多篇采集→写稿→配图→发布前填写"
    )
    dch.add_argument("--track", default="财经,经济,时事,AI Agent,数据服务", help="赛道关键词，逗号分隔")
    dch.add_argument("--scout-limit", type=int, default=5, help="爆款读取条数（1-8）")
    dch.add_argument("--no-interact", action="store_true", help="爆款只浏览不点赞")
    dch.add_argument("--scout-timeout", type=int, default=420)
    dch.add_argument("--sources", default="wallstreetcn,sina", help="资讯来源，逗号分隔")
    dch.add_argument("--count", type=int, default=3, help="采集总篇数（默认 3）")
    dch.add_argument("--extra", default="", help="额外优化要求")
    dch.add_argument("--style", default="", help="配图风格提示")
    dch.add_argument("--image-count", type=int, default=1, help="图文配图张数（1-6，默认 1）")
    dch.add_argument("--no-data", action="store_true", help="跳过云端数据")
    dch.add_argument("--data-timeout", type=int, default=60)
    dch.add_argument("--trend-timeout", type=int, default=120)
    dch.add_argument("--cover-timeout", type=int, default=300)
    dch.add_argument("--publish", action="store_true", help="人工授权：最后直接点发布")
    dch.add_argument("--timeout", type=int, default=360, help="等待手机回执秒数（默认 360）")
    dch.set_defaults(func=cmd_douyin)

    vd = sub.add_parser("video", help="剪映 AI 文字成片：文案→竖版视频→导出相册")
    vd_sub = vd.add_subparsers(dest="video_cmd", required=True)
    vm = vd_sub.add_parser("make", help="用小红书笔记文案生成视频并导出")
    vm.add_argument("--note", required=True, help="笔记 JSON 路径（title/body）")
    vm.add_argument("--timeout", type=int, default=900, help="等待生成+导出秒数（默认 900）")
    vm.add_argument("--publish", action="store_true", help="导出后经剪映「分享到抖音」直接发布")
    vm.add_argument("--json", action="store_true")
    vm.set_defaults(func=cmd_video)

    carpool = sub.add_parser("carpool", help="顺风车抢单：扫描/刷新/接单（默认只扫描，接单需 --accept）")
    cp_sub = carpool.add_subparsers(dest="carpool_cmd", required=True)
    for name, help_text in (
        ("start", "开始扫描订单大厅"),
        ("refresh", "刷新一次订单列表"),
        ("stop", "停止扫描"),
    ):
        cp = cp_sub.add_parser(name, help=help_text)
        cp.add_argument("--platform", default="didi", choices=list(CARPOOL_PLATFORMS))
        cp.add_argument("--min-price", type=float, default=0, help="价格下限（元）")
        cp.add_argument("--max-accept", type=int, default=1, help="当日接单上限（默认 1）")
        cp.add_argument("--device-id", default="", help="绑定设备")
        cp.add_argument("--json", action="store_true")
        cp.set_defaults(func=cmd_carpool)
    cp_accept = cp_sub.add_parser("accept", help="接单（必须显式 --accept 授权）")
    cp_accept.add_argument("--platform", default="didi", choices=list(CARPOOL_PLATFORMS))
    cp_accept.add_argument("--order-id", required=True, help="订单号")
    cp_accept.add_argument("--price", type=float, default=None, help="订单价格（用于下限校验）")
    cp_accept.add_argument("--min-price", type=float, default=0, help="价格下限（元）")
    cp_accept.add_argument("--max-accept", type=int, default=1, help="当日接单上限（默认 1）")
    cp_accept.add_argument("--accept", action="store_true", help="人工授权：允许下发接单")
    cp_accept.add_argument("--device-id", default="", help="绑定设备")
    cp_accept.add_argument("--json", action="store_true")
    cp_accept.set_defaults(func=cmd_carpool)
    cp_status = cp_sub.add_parser("status", help="今日接单数与抢单作业状态")
    cp_status.add_argument("--json", action="store_true")
    cp_status.set_defaults(func=cmd_carpool)

    chat = sub.add_parser("chat", help="会话模式：唤醒助手，自然语言→大模型决策→程序按流程执行")
    chat.set_defaults(func=cmd_chat)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ValueError as exc:
        print("E_INPUT：{}".format(exc), file=sys.stderr)
        return EXIT_ARG


if __name__ == "__main__":
    sys.exit(main())
