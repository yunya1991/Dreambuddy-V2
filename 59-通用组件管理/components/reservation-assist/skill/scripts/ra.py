#!/usr/bin/env python3
"""预约助手 CLI：watch / notify / doctor / reconcile / report / install。"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import inbox as inbox_mod  # noqa: E402
import notify as notify_mod  # noqa: E402
import security  # noqa: E402
import store as store_mod  # noqa: E402
from adapters import (  # noqa: E402
    ADAPTERS,
    AdapterError,
    GateDenied,
    Hit,
    SubmitUnknown,
    get_adapter,
)
from adapters.base import CN_TZ, HttpTransport, now_ms, target_fingerprint  # noqa: E402
from scheduler import Backoff, VirtualClock, effective_interval, in_window  # noqa: E402

import launchd  # noqa: E402

LIMITS = (
    "本工具仅做余票/号源监控与官方页面跳转，不代抢、不转售、不支付，也不承诺成功率；"
    "观测结果以平台官方页面为准，数据缺口见 missing[]。"
)
EXIT_OK, EXIT_ARG, EXIT_GATE, EXIT_AUTH, EXIT_NET, EXIT_RECONCILE = 0, 2, 3, 4, 5, 6


def state_dir() -> Path:
    return Path(os.environ.get("RA_STATE_DIR") or (Path.home() / ".reservation-assist"))


def open_store() -> store_mod.Store:
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    try:
        directory.chmod(0o700)
    except PermissionError:
        # 目录已存在且被系统策略保护时保持原权限；不影响读写
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


def parse_stamp(text: str) -> int:
    text = text.strip()
    if text.lstrip("-").isdigit():
        return int(text)
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=CN_TZ)
    return int(moment.timestamp() * 1000)


def parse_window(text: str) -> tuple[int, int]:
    if "/" not in text:
        raise ValueError("--window 需要 <start>/<end>")
    start, end = text.split("/", 1)
    return parse_stamp(start), parse_stamp(end)


def load_json_arg(text: str) -> dict:
    if text.startswith("@"):
        return json.loads(Path(text[1:]).read_text(encoding="utf-8"))
    return json.loads(text)


def task_summary(task: dict) -> dict:
    target = task.get("target") or {}
    return {
        "id": task["id"],
        "adapter": task["adapter"],
        "target_id": target.get("target_id", ""),
        "session": target.get("session", ""),
        "price_tier": target.get("price_tier", ""),
        "max_price": (task.get("rule") or {}).get("max_price"),
        "window_start": task.get("window_start"),
        "window_end": task.get("window_end"),
        "submit_enabled": int(task.get("submit_enabled") or 0),
    }


# ---------------------------------------------------------------------------
# watch
# ---------------------------------------------------------------------------


def cmd_watch_add(args) -> int:
    adapter = get_adapter(args.adapter)
    target = load_json_arg(args.target)
    rule = load_json_arg(args.rule)
    start, end = parse_window(args.window)
    if end <= start:
        print("E_INPUT：窗口 end 必须晚于 start", file=sys.stderr)
        return EXIT_ARG
    if not target.get("target_id"):
        print("E_INPUT：target 缺少 target_id", file=sys.stderr)
        return EXIT_ARG
    if args.notify:
        rule["notify"] = args.notify
    task = {
        "id": uuid.uuid4().hex[:12],
        "adapter": adapter.NAME,
        "target": target,
        "rule": rule,
        "window_start": start,
        "window_end": end,
        "interval_ms": args.interval,
        "submit_enabled": bool(args.submit),
        "max_orders": 1,
        "created_at": now_ms(),
    }
    with open_store() as db:
        db.add_task(task)
        db.add_event("info", "task_added", task["id"], {"adapter": adapter.NAME})
    print(task["id"])
    return EXIT_OK


def cmd_watch_list(args) -> int:
    with open_store() as db:
        tasks = [task_summary(task) for task in db.list_tasks()]
    if args.json:
        print(json.dumps(envelope("watch.list", tasks=tasks), ensure_ascii=False, indent=2))
        return EXIT_OK
    if not tasks:
        print("暂无监控任务")
        return EXIT_OK
    for task in tasks:
        print(
            "{id}  {adapter}  {target_id}  {session}  上限 {max_price}  {submit}".format(
                submit="可提交" if task["submit_enabled"] else "仅监控", **task
            )
        )
    return EXIT_OK


def cmd_watch_rm(args) -> int:
    with open_store() as db:
        removed = db.delete_task(args.task_id)
        db.add_event("info", "task_removed", args.task_id, {"removed": removed})
    if not removed:
        print("E_INPUT：任务不存在", file=sys.stderr)
        return EXIT_ARG
    return EXIT_OK


def cmd_watch_grant(args) -> int:
    if not sys.stdin.isatty():
        print("E_GATE：grant 必须在 tty 中签发", file=sys.stderr)
        return EXIT_GATE
    with open_store() as db:
        task = db.get_task(args.task_id)
        if not task:
            print("E_INPUT：任务不存在", file=sys.stderr)
            return EXIT_ARG
        fp = target_fingerprint(task)
        summary = task_summary(task)
        print("平台：{}".format(summary["adapter"]))
        print("目标：{} / {}".format(summary["target_id"], summary["session"]))
        print("价格上限：{}".format(summary["max_price"]))
        print("指纹末 6 位：{}".format(fp[-6:]))
        answer = input("输入指纹末 6 位确认签发 ≤2h grant：").strip()
        if answer != fp[-6:]:
            print("E_GATE：确认不匹配，已取消", file=sys.stderr)
            return EXIT_GATE
        grant = security.issue_grant(task["id"], fp, security.secret_for(state_dir()))
        db.put_grant(grant)
        db.add_event("info", "grant_issued", task["id"], {"expires_at": grant["expires_at"]})
        print(
            "grant 已签发，到期时间：{}".format(
                datetime.fromtimestamp(grant["expires_at"] / 1000, CN_TZ).isoformat(
                    timespec="seconds"
                )
            )
        )
    return EXIT_OK


def cmd_watch_revoke(args) -> int:
    with open_store() as db:
        removed = db.revoke_grant(args.task_id)
        db.add_event("info", "grant_revoked", args.task_id, {"removed": removed})
    print("已撤销" if removed else "无有效 grant")
    return EXIT_OK


def _notifier_for(task: dict):
    names = (task.get("rule") or {}).get("notify") or "feishu,local"
    return notify_mod.build_notifier(names)


def _message(task: dict, hit: Hit) -> str:
    summary = hit.summary()
    return (
        "[预约助手] {adapter} 命中\n"
        "{target_id} / {session} / {tier}\n"
        "余量 {remaining}，价格 {price}\n"
        "官方页面：{url}\n"
        "仅监控提醒，不代抢不支付。"
    ).format(
        adapter=summary["adapter"],
        target_id=summary["target_id"],
        session=summary["session"],
        tier=summary["price_tier"],
        remaining=summary["remaining"],
        price=summary["price"],
        url=summary["url"],
    )


def _maybe_submit(db, task: dict, adapter, hit: Hit, transport, secret: bytes) -> None:
    if not int(task.get("submit_enabled") or 0):
        return
    try:
        grant = security.evaluate_submit(task, adapter, db, secret, fingerprint=hit.fingerprint)
        result = adapter.submit(hit, grant, transport)
        state = "submitted" if result.state == "ok" else "unknown"
    except GateDenied as exc:
        db.add_event("warn", "submit_denied", task["id"], {"reason": str(exc)})
        return
    except SubmitUnknown as exc:
        db.add_event("warn", "submit_unknown", task["id"], {"detail": str(exc)})
        state = "unknown"
    except AdapterError as exc:
        db.add_event("warn", exc.code, task["id"], {"detail": str(exc)})
        state = "unknown"
    db.set_submit_state(task["id"], hit.fingerprint, state)
    db.add_event("info", "submit_state", task["id"], {"state": state})


def cmd_watch_run(args) -> int:
    with open_store() as db:
        if db.get_meta("paused", "0") == "1":
            print("预约已停止：等待开关恢复（每 15 分钟复查一次）")
            time.sleep(900)
            return EXIT_OK
        if args.task:
            task = db.get_task(args.task)
            if not task:
                print("E_INPUT：任务不存在", file=sys.stderr)
                return EXIT_ARG
            tasks = [task]
        else:
            tasks = db.list_tasks()
        if not tasks:
            print("暂无监控任务")
            return EXIT_OK

        transport = HttpTransport()
        clock = VirtualClock()
        backoff = Backoff()
        secret = security.secret_for(state_dir())
        notifiers = {}
        closed: set[str] = set()
        login_warned: set[str] = set()
        while True:
            now = clock.now_ms()
            active = []
            for task in tasks:
                adapter = get_adapter(task["adapter"])
                if getattr(adapter, "REQUIRES_LOGIN", False) and not adapter.cookie:
                    adapter.cookie = security.load_cookie(adapter.NAME)
                if not in_window(now, task.get("window_start"), task.get("window_end")):
                    if (
                        task.get("window_end")
                        and now > task["window_end"]
                        and task["id"] not in closed
                    ):
                        closed.add(task["id"])
                        db.add_event("info", "window_closed", task["id"])
                    continue
                if getattr(adapter, "REQUIRES_LOGIN", False) and not adapter.cookie:
                    if task["id"] not in login_warned:
                        login_warned.add(task["id"])
                        db.add_event("warn", "login_missing", task["id"], {"adapter": adapter.NAME})
                        notifiers.setdefault(task["id"], _notifier_for(task)).send(
                            "预约助手：{} 登录态缺失，请先在 Keychain 配置 Cookie".format(
                                adapter.NAME
                            )
                        )
                    continue
                active.append((task, adapter))
                try:
                    snap = adapter.probe(task["target"], transport)
                    backoff.record_success()
                except AdapterError as exc:
                    delay = backoff.record_failure(now)
                    db.add_event("warn", exc.code, task["id"], {"retry_ms": delay})
                    if exc.code == "E_RATE":
                        backoff.cooldown(now, 24 * 3600 * 1000)
                    if exc.code == "E_AUTH" and task["id"] not in login_warned:
                        login_warned.add(task["id"])
                        notifiers.setdefault(task["id"], _notifier_for(task)).send(
                            "预约助手：{} 登录态失效，请更新 Keychain Cookie".format(adapter.NAME)
                        )
                    continue
                hits = adapter.match(snap, task["rule"], task["id"])
                for hit in hits:
                    if db.upsert_hit(task["id"], hit.fingerprint, snap.fetched_at, snap.digest):
                        db.add_event("info", "hit", task["id"], hit.summary())
                    key = task["id"]
                    if key not in notifiers:
                        notifiers[key] = _notifier_for(task)
                    notify_mod.deliver_once(
                        db, notifiers[key], task["id"], hit.fingerprint, _message(task, hit)
                    )
                    _maybe_submit(db, task, adapter, hit, transport, secret)
            if args.once:
                break
            if not active:
                upcoming = [
                    task["window_start"]
                    for task in tasks
                    if task.get("window_start") and task["window_start"] > now
                ]
                wait_ms = min(60_000, min(upcoming) - now) if upcoming else 60_000
                time.sleep(max(1, wait_ms) / 1000)
                continue
            interval = min(
                effective_interval(adapter, task.get("interval_ms")) for task, adapter in active
            )
            time.sleep(interval / 1000)
    return EXIT_OK


def _set_paused(value: str) -> int:
    with open_store() as db:
        db.set_meta("paused", value)
    print("已暂停全部任务" if value == "1" else "已恢复全部任务")
    return EXIT_OK


# ---------------------------------------------------------------------------
# notify / doctor / reconcile / report
# ---------------------------------------------------------------------------


def cmd_notify_test(args) -> int:
    channel = notify_mod.build_notifier([args.channel])
    failures = channel.send("预约助手通知测试")
    if failures:
        print(json.dumps(envelope("notify.test", missing=failures), ensure_ascii=False, indent=2))
        return EXIT_NET
    print("通知通道 {} 可用".format(args.channel))
    return EXIT_OK


def _doctor_checks() -> list[dict]:
    checks: list[dict] = []
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)

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

    if sys.platform == "darwin" and shutil.which("security"):
        try:
            subprocess.run(
                ["security", "find-generic-password", "-s", "reservation-assist"],
                capture_output=True,
                timeout=3,
            )
            add("keychain", True, "security 可用（无条目属正常）")
        except subprocess.TimeoutExpired:
            add("keychain", False, "Keychain 读取超时，提交已禁用")
    else:
        add("keychain", True, "跳过：非 macOS")

    for name, adapter_cls in sorted(ADAPTERS.items()):
        if not getattr(adapter_cls, "REQUIRES_LOGIN", False):
            add("login:{}".format(name), True, "公开页面，无需登录")
            continue
        cookie = security.load_cookie(name)
        add(
            "login:{}".format(name),
            True,
            "已配置" if cookie else "未配置（该平台监控会跳过）",
        )

    free = shutil.disk_usage(str(directory)).free
    add("disk_free", free >= 512 * 1024 * 1024, "剩余 {:.0f}MB".format(free / 1024 / 1024))

    problems = launchd.validate(launchd.render())
    add("launchd_template", not problems, "；".join(problems) or "占位符完整、无人值守禁提交")

    add("container", not security.is_container(), "容器/云主机内禁止提交")
    return checks


def cmd_doctor(args) -> int:
    checks = _doctor_checks()
    purged = {}
    if args.purge:
        with open_store() as db:
            purged = db.purge()
    missing = [
        {"key": item["name"], "code": "E_ENV", "detail": item["detail"]}
        for item in checks
        if not item["ok"]
    ]
    if args.json:
        payload = envelope("doctor", missing=missing)
        payload["checks"] = checks
        payload["purged"] = purged
        print(json.dumps(security.redact_obj(payload), ensure_ascii=False, indent=2))
    else:
        for item in checks:
            print(
                "{}  {}  {}".format("PASS" if item["ok"] else "WARN", item["name"], item["detail"])
            )
        if purged:
            print("清理：{}".format(purged))
        print("\n" + LIMITS)
    return EXIT_OK if not missing else EXIT_GATE


def cmd_reconcile(args) -> int:
    with open_store() as db:
        task = db.get_task(args.task_id)
        if not task:
            print("E_INPUT：任务不存在", file=sys.stderr)
            return EXIT_ARG
        unknown = [hit for hit in db.list_hits(task["id"]) if hit.get("submit_state") == "unknown"]
        if not unknown:
            print("无 unknown 记录，无需对账")
            return EXIT_OK
        for hit in unknown:
            print("{}  {}  指纹 {}".format(hit["at"], task["id"], hit["fingerprint"][:12]))
            if args.close:
                db.set_submit_state(task["id"], hit["fingerprint"], "closed")
                db.add_event(
                    "info", "reconciled", task["id"], {"fingerprint": hit["fingerprint"][:12]}
                )
        if not args.close:
            print("\n请先在官方订单页人工确认，再执行 `ra reconcile {} --close`".format(task["id"]))
            return EXIT_RECONCILE
    return EXIT_OK


def _day_start_ms(day: str) -> int:
    moment = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=CN_TZ)
    return int(moment.timestamp() * 1000)


def cmd_drill_login(args) -> int:
    get_adapter(args.adapter)
    with open_store() as db:
        db.add_drill(
            args.adapter, "login", args.state == "ok", {"state": args.state, "note": args.note}
        )
    print("已记录登录态采样：{} {}".format(args.adapter, args.state))
    return EXIT_OK


def cmd_drill_submit(args) -> int:
    get_adapter(args.adapter)
    with open_store() as db:
        db.add_drill(
            args.adapter,
            "submit",
            args.result == "ok",
            {
                "result": args.result,
                "captcha": args.captcha,
                "order_ref": args.order_ref,
                "note": args.note,
            },
        )
    print("已记录演练：{} {} captcha={}".format(args.adapter, args.result, args.captcha))
    return EXIT_OK


def cmd_drill_check(args) -> int:
    get_adapter(args.adapter)
    with open_store() as db:
        samples = db.list_drills(args.adapter, kind="login")
        drills = db.list_drills(args.adapter, kind="submit")
    readiness = security.evaluate_readiness(args.adapter, samples, drills)
    if args.json:
        payload = envelope("drill.check")
        payload["readiness"] = readiness
        print(json.dumps(security.redact_obj(payload), ensure_ascii=False, indent=2))
    else:
        print(
            "适配器 {} 就绪实验：{}".format(
                args.adapter, "通过" if readiness["ready"] else "未通过"
            )
        )
        for item in readiness["checks"]:
            print(
                "{}  {}  {}".format("PASS" if item["ok"] else "WARN", item["name"], item["detail"])
            )
        print(
            "\n通过后请手动把适配器类的 SUBMIT_READY 改为 True，并在 references/adapters.md 记录。"
        )
    return EXIT_OK if readiness["ready"] else EXIT_GATE


def cmd_report(args) -> int:
    with open_store() as db:
        tasks = db.list_tasks()
        hits = db.list_hits()
        events = db.list_events()
    if args.date:
        start = _day_start_ms(args.date)
        end = start + 86400 * 1000
        hits = [hit for hit in hits if start <= hit["at"] < end]
        events = [event for event in events if start <= event["at"] < end]
    hits_by_task: dict[str, list[dict]] = {}
    for hit in hits:
        hits_by_task.setdefault(hit["task_id"], []).append(hit)
    task_rows = []
    for task in tasks:
        task_hits = hits_by_task.get(task["id"], [])
        states = [hit.get("submit_state") for hit in task_hits]
        if "submitted" in states:
            status = "submitted"
        elif "unknown" in states:
            status = "unknown"
        elif task_hits and all(hit.get("notified_at") for hit in task_hits):
            status = "notified"
        elif task_hits:
            status = "hit"
        else:
            status = "armed"
        task_rows.append(
            {
                "id": task["id"],
                "adapter": task["adapter"],
                "status": status,
                "window_start": task.get("window_start"),
                "window_end": task.get("window_end"),
                "submit_enabled": int(task.get("submit_enabled") or 0),
            }
        )
    hit_rows = [
        {
            "task_id": hit["task_id"],
            "fingerprint": hit["fingerprint"],
            "at": hit["at"],
            "result": hit.get("submit_state") or ("notified" if hit.get("notified_at") else "hit"),
            "notified_at": hit.get("notified_at"),
            "submit_state": hit.get("submit_state"),
        }
        for hit in hits
    ]
    payload = envelope("report", tasks=task_rows, hits=hit_rows, events=events)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return EXIT_OK

    print("任务 {} 个，命中 {} 条，事件 {} 条".format(len(task_rows), len(hit_rows), len(events)))
    for row in task_rows:
        print("{id}  {adapter}  {status}".format(**row))
    for row in hit_rows[:20]:
        print("  命中 {task_id} {at} {result}".format(**row))
    print("\n数据源：平台官方页面（DC-2 内部例外，仅内部自用，不再分发）")
    print("方法 ID：T01 命中计数 / T02 探测延迟（见 skill/references/methods.md）")
    print(LIMITS)
    return EXIT_OK


def cmd_install(args) -> int:
    for path in launchd.install():
        print("已安装：{}".format(path))
    return EXIT_OK


def cmd_uninstall(args) -> int:
    removed = launchd.uninstall()
    print("已卸载" if removed else "未安装")
    return EXIT_OK


def cmd_auth_set(args) -> int:
    get_adapter(args.adapter)
    value = sys.stdin.readline().strip()
    if not value:
        print(
            "E_INPUT：未从 stdin 读到 Cookie（示例：pbpaste | ra auth set --adapter <name>）",
            file=sys.stderr,
        )
        return EXIT_ARG
    if not security.store_cookie(args.adapter, value):
        print("E_ENV：Keychain 写入失败（security 不可用或未授权）", file=sys.stderr)
        return EXIT_GATE
    print("已写入 Keychain：{}（值不回显）".format(security.keychain_service(args.adapter)))
    return EXIT_OK


def cmd_auth_status(args) -> int:
    rows = []
    for name, adapter_cls in sorted(ADAPTERS.items()):
        if not getattr(adapter_cls, "REQUIRES_LOGIN", False):
            rows.append({"adapter": name, "status": "public"})
            continue
        rows.append({"adapter": name, "status": "set" if security.load_cookie(name) else "missing"})
    if args.json:
        payload = envelope("auth.status")
        payload["accounts"] = rows
        print(json.dumps(security.redact_obj(payload), ensure_ascii=False, indent=2))
        return EXIT_OK
    for row in rows:
        print("{}  {}".format(row["adapter"], row["status"]))
    return EXIT_OK


def cmd_auth_clear(args) -> int:
    removed = security.delete_cookie(args.adapter)
    print("已删除 Keychain 条目" if removed else "无该条目或删除失败")
    return EXIT_OK


# ---------------------------------------------------------------------------


def cmd_watch_notify(args) -> int:
    names = [item.strip() for item in args.channels.split(",") if item.strip()]
    if not names or set(names) - {"feishu", "feishu_app", "local"}:
        print("E_INPUT：通道只能是 feishu / feishu_app / local", file=sys.stderr)
        return EXIT_ARG
    with open_store() as db:
        if not db.set_task_notify(args.task_id, ",".join(names)):
            print("E_INPUT：任务不存在", file=sys.stderr)
            return EXIT_ARG
        db.add_event("info", "notify_channels_changed", args.task_id, {"channels": names})
    print("{} -> {}".format(args.task_id, ",".join(names)))
    return EXIT_OK


def cmd_auth_feishu(args) -> int:
    prefix = "https://open.feishu.cn/open-apis/bot/v2/hook/"
    url = sys.stdin.readline().strip()
    if not url.startswith(prefix):
        print("E_INPUT：webhook 需以 {} 开头".format(prefix), file=sys.stderr)
        return EXIT_ARG
    if not security.store_cookie("feishu", url):
        print("E_ENV：Keychain 写入失败（security 不可用或未授权）", file=sys.stderr)
        return EXIT_GATE
    print("已写入 Keychain：{}（值不回显）".format(security.keychain_service("feishu")))
    return EXIT_OK


def cmd_inbox_pull(args) -> int:
    config = inbox_mod.load_app_config()
    if not (config.get("app_id") and config.get("chat_id")):
        print("E_ENV：未配置飞书应用凭据（com.reservation-assist.feishu-app）", file=sys.stderr)
        return EXIT_GATE
    with open_store() as db:
        if db.get_meta("paused", "0") == "1":
            print("预约已停止（ra 开启预约 恢复），本次跳过入站")
            return EXIT_OK
        result = inbox_mod.pull(db, config, minutes=args.minutes)
    lines = inbox_mod.summarize(result["added"])
    print(
        "扫描 {} 条，新增 {} 人，累计 {} 人".format(
            result["scanned"], len(result["added"]), result["total"]
        )
    )
    for line in lines:
        print("  " + line)
    if lines and not args.no_notify:
        try:
            notify_mod.FeishuAppChannel(config).send("已接收参观人：\n" + "\n".join(lines))
        except Exception as exc:  # noqa: BLE001 - 通知失败不影响入库
            print("E_CHANNEL：确认消息发送失败 {}".format(exc), file=sys.stderr)
    return EXIT_OK


def cmd_inbox_show(args) -> int:
    visitors = inbox_mod.load_visitors()
    if not visitors:
        print("暂无参观人（发一条「姓名 张三 110… 手机 138…」到群里后执行 ra inbox pull）")
        return EXIT_OK
    for line in inbox_mod.summarize(visitors):
        print("  " + line)
    return EXIT_OK


def cmd_start(args) -> int:
    with open_store() as db:
        db.set_meta("paused", "0")
        count = len(db.list_tasks())
        db.add_event("info", "switch_on", "", {"tasks": count})
    plist = Path.home() / "Library" / "LaunchAgents" / "com.reservation-assist.watch.plist"
    if plist.is_file():
        launchd.bootstrap_all()
    else:
        for path in launchd.install():
            print("已安装：{}".format(path))
    print("预约已开启：{} 个任务，进入时间窗后开始轮询".format(count))
    return EXIT_OK


def cmd_stop(args) -> int:
    with open_store() as db:
        db.set_meta("paused", "1")
        db.add_event("info", "switch_off", "", {})
    launchd.bootout_all()
    print("预约已停止：轮询已关闭，任务与命中记录保留")
    return EXIT_OK


def cmd_switch_status(args) -> int:
    with open_store() as db:
        paused = db.get_meta("paused", "0") == "1"
        tasks = db.list_tasks()
        hits = db.get_meta("hits_total", "0")
    print("状态：{}".format("已停止" if paused else "已开启"))
    print("任务：{} 个".format(len(tasks)))
    print("launchd：{}".format(launchd.status().replace("\n", " | ")))
    if hits != "0":
        print("累计命中：{}".format(hits))
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ra", description="预约助手：余票/号源监控与通知")
    groups = parser.add_subparsers(dest="group", required=True)

    watch = groups.add_parser("watch", help="监控任务管理")
    watch_sub = watch.add_subparsers(dest="action", required=True)

    add = watch_sub.add_parser("add", help="新增任务")
    add.add_argument("--adapter", required=True, choices=sorted(ADAPTERS))
    add.add_argument("--target", required=True, help="JSON 或 @file")
    add.add_argument("--rule", required=True, help="JSON 或 @file")
    add.add_argument("--window", required=True, help="<start>/<end>，ISO 或 epoch ms")
    add.add_argument("--interval", type=int, default=None, help="请求间隔 ms（受平台下限约束）")
    add.add_argument("--notify", default="", help="feishu,local")
    add.add_argument("--submit", action="store_true", help="允许自动提交（仍需 grant）")
    add.set_defaults(func=cmd_watch_add)

    listing = watch_sub.add_parser("list", help="列出任务")
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(func=cmd_watch_list)

    rm = watch_sub.add_parser("rm", help="删除任务")
    rm.add_argument("task_id")
    rm.set_defaults(func=cmd_watch_rm)

    watch_notify = watch_sub.add_parser("notify", help="修改任务通知通道")
    watch_notify.add_argument("task_id")
    watch_notify.add_argument("--channels", default="feishu,local")
    watch_notify.set_defaults(func=cmd_watch_notify)

    grant = watch_sub.add_parser("grant", help="签发一次性 grant（必须 tty）")
    grant.add_argument("task_id")
    grant.set_defaults(func=cmd_watch_grant)

    revoke = watch_sub.add_parser("revoke", help="撤销 grant")
    revoke.add_argument("task_id")
    revoke.set_defaults(func=cmd_watch_revoke)

    run = watch_sub.add_parser("run", help="运行监控循环")
    run.add_argument("--task", default="")
    run.add_argument("--once", action="store_true", help="只探测一轮（调试/自检）")
    run.add_argument("--foreground", action="store_true")
    run.set_defaults(func=cmd_watch_run)

    pause = watch_sub.add_parser("pause-all", help="全局刹车")
    pause.set_defaults(func=lambda args: _set_paused("1"))

    resume = watch_sub.add_parser("resume-all", help="恢复全部")
    resume.set_defaults(func=lambda args: _set_paused("0"))

    start = groups.add_parser(
        "开启预约", aliases=["开始预约", "start"], help="开启轮询（等价 resume-all + 确保已安装）"
    )
    start.set_defaults(func=cmd_start)

    stop = groups.add_parser(
        "关闭预约", aliases=["停止预约", "stop"], help="停止轮询（等价 pause-all）"
    )
    stop.set_defaults(func=cmd_stop)

    switch = groups.add_parser("状态", aliases=["switch-status"], help="查看开关与运行状态")
    switch.set_defaults(func=cmd_switch_status)

    notify_group = groups.add_parser("notify", help="通知通道")
    notify_sub = notify_group.add_subparsers(dest="action", required=True)
    test = notify_sub.add_parser("test")
    test.add_argument("--channel", default="local", choices=["feishu", "feishu_app", "local"])
    test.set_defaults(func=cmd_notify_test)

    doctor = groups.add_parser("doctor", help="环境自检")
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument("--purge", action="store_true")
    doctor.set_defaults(func=cmd_doctor)

    reconcile = groups.add_parser("reconcile", help="人工对账 unknown")
    reconcile.add_argument("task_id")
    reconcile.add_argument("--close", action="store_true")
    reconcile.set_defaults(func=cmd_reconcile)

    inbox_group = groups.add_parser("inbox", help="群消息入站（实验：只读+本地 Keychain）")
    inbox_sub = inbox_group.add_subparsers(dest="action", required=True)
    inbox_pull = inbox_sub.add_parser("pull")
    inbox_pull.add_argument("--minutes", type=int, default=60)
    inbox_pull.add_argument("--no-notify", action="store_true")
    inbox_pull.set_defaults(func=cmd_inbox_pull)
    inbox_show = inbox_sub.add_parser("show")
    inbox_show.set_defaults(func=cmd_inbox_show)

    drill = groups.add_parser("drill", help="就绪实验记录与判定（不发请求）")
    drill_sub = drill.add_subparsers(dest="action", required=True)

    drill_login = drill_sub.add_parser("login", help="记录一次登录态采样")
    drill_login.add_argument("--adapter", required=True, choices=sorted(ADAPTERS))
    drill_login.add_argument("--state", required=True, choices=["ok", "expired", "unknown"])
    drill_login.add_argument("--note", default="")
    drill_login.set_defaults(func=cmd_drill_login)

    drill_submit = drill_sub.add_parser("submit", help="记录一次不付款演练")
    drill_submit.add_argument("--adapter", required=True, choices=sorted(ADAPTERS))
    drill_submit.add_argument(
        "--result", required=True, choices=["ok", "wrong_target", "duplicate"]
    )
    drill_submit.add_argument("--captcha", default="none", choices=["none", "manual", "blocked"])
    drill_submit.add_argument("--order-ref", default="")
    drill_submit.add_argument("--note", default="")
    drill_submit.set_defaults(func=cmd_drill_submit)

    drill_check = drill_sub.add_parser("check", help="判定是否达到 SUBMIT_READY 条件")
    drill_check.add_argument("--adapter", required=True, choices=sorted(ADAPTERS))
    drill_check.add_argument("--json", action="store_true")
    drill_check.set_defaults(func=cmd_drill_check)

    auth = groups.add_parser("auth", help="Keychain 登录态维护")
    auth_sub = auth.add_subparsers(dest="action", required=True)

    auth_set = auth_sub.add_parser("set", help="从 stdin 读取 Cookie 写入 Keychain")
    auth_set.add_argument("--adapter", required=True, choices=sorted(ADAPTERS))
    auth_set.set_defaults(func=cmd_auth_set)

    auth_status = auth_sub.add_parser("status", help="查看各平台登录态是否已配置")
    auth_status.add_argument("--json", action="store_true")
    auth_status.set_defaults(func=cmd_auth_status)

    auth_clear = auth_sub.add_parser("clear", help="删除某平台 Keychain 条目")
    auth_clear.add_argument("--adapter", required=True, choices=sorted(ADAPTERS))
    auth_clear.set_defaults(func=cmd_auth_clear)

    auth_feishu = auth_sub.add_parser("feishu", help="从 stdin 读取飞书 webhook 写入 Keychain")
    auth_feishu.set_defaults(func=cmd_auth_feishu)

    report = groups.add_parser("report", help="reservation.v1 报告")
    report.add_argument("--date", default="")
    report.add_argument("--json", action="store_true")
    report.set_defaults(func=cmd_report)

    install = groups.add_parser("install", help="安装 launchd")
    install.set_defaults(func=cmd_install)

    uninstall = groups.add_parser("uninstall", help="卸载 launchd")
    uninstall.set_defaults(func=cmd_uninstall)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except GateDenied as exc:
        print("E_GATE：{}".format(exc), file=sys.stderr)
        return EXIT_GATE
    except AdapterError as exc:
        print("{}：{}".format(exc.code, exc), file=sys.stderr)
        return EXIT_AUTH if exc.code == "E_AUTH" else EXIT_NET
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        print("E_INPUT：{}".format(exc), file=sys.stderr)
        return EXIT_ARG


if __name__ == "__main__":
    sys.exit(main())
