#!/usr/bin/env python3
"""手机预约助手 CLI：ingest / jobs / gateway / token / doctor / report / pause / resume / ask / dispatch / patrol。

消费上游命中 → 生成预约作业 → 本地网关派发给手机端 Agent → 回执落库 → reservation.v1 报告。
不 import 上游组件、不写死其路径；上游通过 --ra-cli 或 --source 注入。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import brain  # noqa: E402
import gateway as gateway_mod  # noqa: E402
import ingest as ingest_mod  # noqa: E402
import security  # noqa: E402
import store as store_mod  # noqa: E402

CN_TZ = timezone(timedelta(hours=8))

LIMITS = (
    "本组件仅做上游命中到手机端预约动作的编排与派发，停在官方下单页并预填；"
    "不代抢、不转售、不锁座、不托管支付、不破解验证码，不承诺成功率。"
)
EXIT_OK, EXIT_ARG, EXIT_GATE, EXIT_NET = 0, 2, 3, 5


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
    with open_store() as db:
        result = ingest_mod.ingest_into(db, hits)
    print(json.dumps(result, ensure_ascii=False))
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
    print(
        "网关就绪：http://{}:{}/  (Token 存于 {})".format(
            args.host, args.port, security.token_path(state_dir())
        )
    )
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
            print(
                "{}  {}  {}".format("PASS" if item["ok"] else "WARN", item["name"], item["detail"])
            )
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
            "submit_state": (
                job.get("_state") if job.get("_state") in store_mod.TERMINAL_STATES else None
            ),
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


def _reset_stuck() -> dict:
    """把卡在 dispatched 的作业复位为 pending（watchdog 接管修复动作）。"""
    with open_store() as db:
        stuck = list(db.list_jobs(state="dispatched"))
        for job in stuck:
            db.set_job_state(job["_id"], "pending")
        if stuck:
            db.add_event("warn", "reset_stuck", None, {"count": len(stuck)})
    return {"reset": len(stuck)}


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
    if action == "dispatch":
        return _dispatch(params)
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
            print(
                "  - {} {}".format(
                    step.get("action"), json.dumps(step.get("params") or {}, ensure_ascii=False)
                )
            )
        for rej in guarded["rejected"]:
            print("  [拒绝] {}：{}".format(rej.get("action"), rej.get("reason")))
    if not args.execute:
        print("\n未执行。加 --execute 由人工授权执行以上白名单计划。")
        return EXIT_OK
    results = execute_steps(guarded["plan"].get("steps", []))
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return EXIT_OK if all(item.get("ok") for item in results) else EXIT_GATE


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
                    {
                        "role": "system",
                        "content": "你是巡检诊断助手。基于证据给出简明中文诊断与建议，不要输出任何密钥。",
                    },
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
        fixes.append({"fix": "reset_stuck", "result": _reset_stuck()})
    print("修复：" + json.dumps(fixes, ensure_ascii=False))
    with open_store() as db:
        after = _jobs_summary(db)
    remaining = len([job for job in after if job["state"] == "dispatched"])
    print("验证：remaining_dispatched={}".format(remaining))
    return EXIT_OK if remaining == 0 or not stuck else EXIT_GATE


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
    print(
        "已唤醒。用自然语言下达指令，模型负责决策、程序按流程执行。输入 /help 查看，/exit 退出。\n"
    )
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
        results = execute_steps(steps)
        for item in results:
            if item.get("ok"):
                payload = json.dumps(item.get("result"), ensure_ascii=False)
                print("  ✓ {}  {}".format(item["action"], payload[:300]))
            else:
                print("  ✗ {}  {}".format(item["action"], item.get("error", "")))
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mra", description="手机预约助手：命中→手机端预约动作编排"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    ing = sub.add_parser("ingest", help="归一上游命中并入队为预约作业")
    ing.add_argument("--ra-cli", default="", help="上游 ra.py 路径（经公开 CLI 只读消费）")
    ing.add_argument("--source", default="", help="file:<path> 本地 feed（离线/测试）")
    ing.set_defaults(func=cmd_ingest)

    jobs = sub.add_parser("jobs", help="列出预约作业")
    jobs.add_argument("--json", action="store_true")
    jobs.add_argument("--state", default="", help="pending|dispatched|done|failed|unknown|cooldown")
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

    dispatch = sub.add_parser("dispatch", help="自然语言→下发一条预约作业")
    dispatch.add_argument("text", help="自然语言预约指令，如：帮我预约12月25日某演出内场")
    dispatch.add_argument("--json", action="store_true")
    dispatch.add_argument("--dry-run", action="store_true", help="只解析不写入")
    dispatch.set_defaults(func=cmd_dispatch)

    patrol = sub.add_parser("patrol", help="巡检+大模型诊断（--auto-fix 告警接管修复验证）")
    patrol.add_argument("--auto-fix", action="store_true", help="告警接管：白名单修复并验证")
    patrol.add_argument("--resume", action="store_true", help="auto-fix 时若处于暂停则恢复派发")
    patrol.set_defaults(func=cmd_patrol)

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
