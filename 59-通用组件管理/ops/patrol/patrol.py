#!/usr/bin/env python3
"""付费服务巡检：每 5 分钟检查三个服务的云端状态、计费入口与上游取数。

发现异常时：
1. 汇总证据（结构化，不含密钥）；
2. 调用千问生成诊断建议，写入日志；
3. 可选 --auto-fix：服务未运行则尝试重启，重启后再复检一次。

安全边界：只读探测 + 受限重启；不改代码、不写生产库、不回显任何凭证。
退出码：0 正常 / 1 有异常 / 2 配置缺失
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import incident  # noqa: E402

BASE = "https://www.neodrm.com"
SSH_HOST = os.environ.get("PATROL_SSH", "tencent-cloud")
ENV_FILE = os.path.expanduser("~/.local/share/dreambuddy/qwen.env")
LOG_DIR = os.environ.get("PATROL_STATE_DIR") or os.path.expanduser("~/.local/share/dreambuddy/patrol")
TZ = timezone(timedelta(hours=8))

ENDPOINTS = [
    ("market-data", "/api/paid/data",
     {"skill": "market-data-hub", "cmd": "macro", "params": {"series": "DGS10"}}, "2.99"),
    ("event-context", "/api/paid/data",
     {"skill": "event-context", "cmd": "events", "params": {"subject": "AAPL", "since": "30"}}, "2.99"),
    ("cogsteward", "/api/paid/cogsteward",
     {"metrics": {"broken_links": 0}, "inventory": {"documents": 10}}, "0.99"),
]


def now():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def http_json(url, payload=None, timeout=25, headers=None):
    data = json.dumps(payload).encode() if payload is not None else None
    hs = {"accept": "application/json"}
    if data:
        hs["content-type"] = "application/json"
    hs.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=hs, method="POST" if data else "GET")
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.headers, json.loads(resp.read().decode()), round((time.time() - start) * 1000)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"raw": raw[:300]}
        return exc.code, exc.headers, body, round((time.time() - start) * 1000)
    except Exception as exc:  # 超时/连接失败
        return 0, {}, {"error": type(exc).__name__, "detail": str(exc)[:200]}, round((time.time() - start) * 1000)


def ssh(cmd, timeout=25, attempts=2):
    last = (0, "", "ssh failed")
    for index in range(attempts):
        try:
            out = subprocess.run(["ssh", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes", SSH_HOST, cmd],
                                 capture_output=True, text=True, timeout=timeout)
            result = (out.returncode, (out.stdout or "").strip()[:500], (out.stderr or "").strip()[:300])
        except subprocess.TimeoutExpired:
            result = (124, "", "ssh timeout")
        except FileNotFoundError:
            return 127, "", "ssh not found"
        if result[0] == 0:
            return result
        last = result
        if index + 1 < attempts:
            time.sleep(2)
    return last


def check_service():
    issues = []
    code, active, err = ssh("systemctl is-active skillhub-audit-api")
    if code != 0 or active != "active":
        issues.append({"check": "systemd", "detail": active or err or "ssh failed"})

    code, health, err = ssh("curl -sS -m 8 http://127.0.0.1:8788/health")
    if code != 0 or not health:
        issues.append({"check": "health", "detail": err or "no response"})
    else:
        try:
            payload = json.loads(health)
            paths = {r.get("path") for r in payload.get("resources", [])}
            missing = {"/api/paid/data", "/api/paid/cogsteward", "/api/audit"} - paths - {"/api/data", "/api/cogsteward"}
            if payload.get("status") != "ok":
                issues.append({"check": "health", "detail": "status=" + str(payload.get("status"))})
            if not {"/api/data", "/api/cogsteward"} <= paths:
                issues.append({"check": "resources", "detail": "missing " + ",".join(sorted(missing))})
        except json.JSONDecodeError:
            issues.append({"check": "health", "detail": "non-json"})

    code, disk, _ = ssh("df -P / | tail -1 | awk '{print $5}'")
    if code == 0 and disk.endswith("%"):
        try:
            if int(disk.rstrip("%")) >= 85:
                issues.append({"check": "disk", "detail": "root usage " + disk})
        except ValueError:
            pass
    return issues


def check_endpoints():
    results, issues = [], []
    for name, path, payload, expect in ENDPOINTS:
        status, headers, body, ms = http_json(BASE + path, payload)
        ok = status == 402 and str(body.get("amount")) == expect
        results.append({"name": name, "http": status, "ms": ms, "amount": body.get("amount")})
        if not ok:
            issues.append({"check": "billing:" + name, "detail": "http={} amount={}".format(status, body.get("amount"))})
            continue
        try:
            bill = headers.get("payment-needed") or ""
            if not bill:
                issues.append({"check": "billing:" + name, "detail": "缺少 Payment-Needed"})
        except Exception:
            pass
    return results, issues


def check_upstream():
    """上游取数只在服务器侧探（需要 PARTNER_TOKEN）。"""
    script = (
        "sudo -n bash -c 'set -a; . /etc/skillhub-audit/audit.env 2>/dev/null; set +a; "
        "for q in \"skill=market-data-pro&cmd=macro&series=DGS10\" "
        "\"skill=event-context&cmd=events&subject=AAPL&since=30\"; do "
        "curl -sS -m 30 -o /dev/null -w \"%{http_code} \" "
        "-H \"X-Partner-Token: $PARTNER_TOKEN\" \"https://www.neodrm.com/api/partner/v1/run?$q\"; done'"
    )
    code, out, err = ssh(script, timeout=75)
    codes = out.split()
    issues = []
    if code != 0 or len(codes) < 2:
        issues.append({"check": "upstream", "detail": (err or out or "ssh failed")[:160]})
    else:
        for label, value in zip(("market-data", "event-context"), codes):
            if value != "200":
                issues.append({"check": "upstream:" + label, "detail": "http=" + value})
    return {"codes": codes}, issues


def load_qwen():
    if not os.path.exists(ENV_FILE):
        return None
    values = {}
    with open(ENV_FILE, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip()
    if not values.get("QWEN_BASE_URL") or not values.get("QWEN_API_KEY"):
        return None
    return values


def diagnose(qwen, evidence):
    if not qwen:
        return "（未配置千问，跳过智能诊断）"
    prompt = (
        "你是付费 Skill 服务的值班工程师。下面是 5 分钟巡检结果（JSON）。"
        "请用中文给出：1) 最可能的根因（按可能性排序，最多 3 条）；2) 每条对应的验证命令；"
        "3) 最小修复动作；4) 是否需要立即回滚。只输出结论，不超过 250 字。\n\n"
        + json.dumps(evidence, ensure_ascii=False)
    )
    status, _, body, ms = http_json(
        qwen["QWEN_BASE_URL"].rstrip("/") + "/chat/completions",
        {"model": qwen.get("QWEN_DEFAULT_MODEL", "qwen3.7-plus"),
         "messages": [{"role": "user", "content": prompt}],
         "max_tokens": 600},
        timeout=60,
        headers={"Authorization": "Bearer " + qwen["QWEN_API_KEY"]},
    )
    if status == 200 and body.get("choices"):
        return str(body["choices"][0]["message"]["content"]).strip()
    return "（千问诊断失败：http={}）".format(status)


def auto_fix(issues):
    names = {i["check"] for i in issues}
    if "systemd" not in names:
        return False, "无需重启（systemd 正常）"
    detail = next((i["detail"] for i in issues if i["check"] == "systemd"), "")
    if detail.startswith("ssh") or "timed out" in detail or "端" in detail:
        # 连不上主机时不做任何动作，避免网络抖动触发误重启
        return False, "ssh 不可达，跳过重启：" + detail
    code, out, err = ssh("sudo -n systemctl restart skillhub-audit-api && sleep 3 && systemctl is-active skillhub-audit-api")
    return code == 0 and out == "active", (out or err or "restart failed")


def notify(item):
    """新事件时弹一条本地通知，失败不影响巡检。"""
    text = "{}：{}".format(item["id"], ",".join(item.get("checks") or []))
    script = 'display notification "{}" with title "付费服务巡检异常"'.format(text.replace('"', "'"))
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
    except Exception:
        pass


def write_log(record):
    os.makedirs(LOG_DIR, exist_ok=True)
    path = os.path.join(LOG_DIR, "patrol-" + datetime.now(TZ).strftime("%Y%m%d") + ".jsonl")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    latest = os.path.join(LOG_DIR, "latest.json")
    with open(latest, "w", encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False, indent=2)


def main(argv=None):
    parser = argparse.ArgumentParser(description="付费服务巡检")
    parser.add_argument("--auto-fix", action="store_true", help="服务未运行时尝试重启并复检")
    parser.add_argument("--quiet", action="store_true", help="正常时不输出")
    args = parser.parse_args(argv)

    started = time.time()
    service_issues = check_service()
    billing, billing_issues = check_endpoints()
    upstream, upstream_issues = check_upstream()
    issues = service_issues + billing_issues + upstream_issues

    fixed = None
    if issues and args.auto_fix:
        ok, detail = auto_fix(service_issues)
        if ok:
            service_issues = check_service()
            billing, billing_issues = check_endpoints()
            issues = service_issues + billing_issues + upstream_issues
            fixed = {"attempted": True, "ok": not issues, "detail": detail}
        else:
            fixed = {"attempted": True, "ok": False, "detail": detail}

    record = {
        "ts": now(),
        "ok": not issues,
        "elapsed_s": round(time.time() - started, 1),
        "billing": billing,
        "upstream": upstream,
        "issues": issues,
    }
    if fixed:
        record["auto_fix"] = fixed
    if issues:
        record["diagnosis"] = diagnose(load_qwen(), record)
    write_log(record)

    if issues:
        item, is_new = incident.report(record)
        record["incident_id"] = item["id"]
        if is_new:
            notify(item)
        print("[{}] 巡检异常 {} 项 → 事件 {}".format(record["ts"], len(issues), item["id"]))
        for issue in issues:
            print("  - {}: {}".format(issue["check"], issue["detail"]))
        if record.get("diagnosis"):
            print("\n诊断建议：\n" + record["diagnosis"])
        return 1

    closed = incident.resolve_open("巡检恢复")
    if closed:
        print("[{}] 巡检恢复，关闭事件：{}".format(record["ts"], ", ".join(closed)))
    if not args.quiet:
        print("[{}] 巡检正常：3 个入口 402 正确，上游 200，服务 active，耗时 {}s".format(
            record["ts"], record["elapsed_s"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
