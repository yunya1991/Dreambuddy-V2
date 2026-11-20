#!/usr/bin/env python3
"""沙箱场景执行器（仅标准库）。

- 按 cases/cases.json 启动 mock（或离线端口），执行 Skill 客户端脚本
- 断言退出码、输出关键字、是否出现 traceback、请求次数、请求体参数
- 输出 PASS/FAIL 汇总，可写 markdown 基线报告

用法:
    python3 platform/sandbox/run_cases.py
    python3 platform/sandbox/run_cases.py --only mdp- --verbose
    python3 platform/sandbox/run_cases.py --report platform/sandbox/BASELINE-20261120.md
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

SANDBOX = Path(__file__).resolve().parent
ROOT = SANDBOX.parents[1]
MOCK = SANDBOX / "mock" / "paid_api.py"
CASES = SANDBOX / "cases" / "cases.json"


def closed_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def start_mock(mode, delay):
    proc = subprocess.Popen(
        [sys.executable, str(MOCK), "--port", "0", "--mode", mode, "--delay", str(delay)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    line = proc.stdout.readline().strip()
    if not line.startswith("PORT "):
        proc.kill()
        raise RuntimeError("mock 启动失败：{}".format(line or proc.stderr.read()[:300]))
    port = int(line.split()[1])
    for _ in range(50):
        try:
            with urllib.request.urlopen("http://127.0.0.1:{}/health".format(port), timeout=1):
                break
        except OSError:
            time.sleep(0.05)
    return proc, port


def stop_mock(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def stats(port):
    try:
        with urllib.request.urlopen("http://127.0.0.1:{}/__stats".format(port), timeout=2) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except OSError:
        return {"requests": 0, "last_body": None}


def run_case(case, verbose=False):
    mock_cfg = case.get("mock") or {}
    mode = mock_cfg.get("mode", "none")
    delay = float(mock_cfg.get("delay", 0))
    proc = None
    if mode == "offline":
        port = closed_port()
    elif mock_cfg:
        proc, port = start_mock(mode, delay)
    else:
        port = None

    outputs = []
    started = time.time()
    try:
        for _ in range(int(case.get("repeat", 1))):
            env = dict(os.environ)
            if case.get("endpoint_env") and port:
                env[case["endpoint_env"]] = "http://127.0.0.1:{}{}".format(
                    port, case.get("endpoint_path", "/api/paid/data")
                )
            completed = subprocess.run(
                [sys.executable, str(ROOT / case["script"])] + list(case.get("args", [])),
                cwd=str(ROOT),
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
            )
            outputs.append(
                {"code": completed.returncode, "out": completed.stdout + completed.stderr}
            )
    finally:
        final_stats = stats(port) if port and proc else {"requests": 0, "last_body": None}
        if proc:
            stop_mock(proc)

    elapsed = round(time.time() - started, 2)
    combined = outputs[-1]["out"]
    expect = case.get("expect", {})
    reasons = []

    if "code" in expect and outputs[-1]["code"] != expect["code"]:
        reasons.append("退出码 {}，期望 {}".format(outputs[-1]["code"], expect["code"]))
    for text in expect.get("contains", []):
        if text not in combined:
            reasons.append("缺少输出「{}」".format(text))
    for text in expect.get("not_contains", []):
        if text in combined:
            reasons.append("不应出现「{}」".format(text))

    requested = final_stats.get("requests", 0)
    rule = expect.get("requests") or {}
    if "min" in rule and requested < rule["min"]:
        reasons.append("请求次数 {} < {}".format(requested, rule["min"]))
    if "max" in rule and requested > rule["max"]:
        reasons.append("请求次数 {} > {}".format(requested, rule["max"]))

    body = final_stats.get("last_body") or {}
    for key, want in (expect.get("body_params") or {}).items():
        got = (body.get("params") or {}).get(key)
        if got != want:
            reasons.append("请求体 params.{}={!r}，期望 {!r}".format(key, got, want))

    if verbose:
        print("    ---- output ({}s) ----".format(elapsed))
        print("    " + combined.strip().replace("\n", "\n    ")[:1500])
        print(
            "    ---- stats: requests={} body={} ----".format(
                requested, json.dumps(body, ensure_ascii=False)[:300]
            )
        )

    return {
        "id": case["id"],
        "title": case.get("title", ""),
        "ok": not reasons,
        "reasons": reasons,
        "elapsed": elapsed,
        "excerpt": " ".join(combined.split())[:180],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="沙箱场景执行器")
    parser.add_argument("--only", default="", help="按 id 前缀过滤")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--report", default="", help="写出 markdown 报告路径")
    args = parser.parse_args(argv)

    with open(CASES, "r", encoding="utf-8") as fh:
        cases = json.load(fh)["cases"]
    selected = [c for c in cases if c["id"].startswith(args.only)]

    results = []
    print("沙箱场景：{} 条\n".format(len(selected)))
    for case in selected:
        result = run_case(case, verbose=args.verbose)
        results.append(result)
        print(
            "[{}] {} — {}".format("PASS" if result["ok"] else "FAIL", result["id"], result["title"])
        )
        for reason in result["reasons"]:
            print("       × {}".format(reason))

    passed = sum(1 for item in results if item["ok"])
    print("\n合计 {} / {} 通过，{} 失败".format(passed, len(results), len(results) - passed))

    if args.report:
        lines = [
            "# 沙箱基线报告",
            "",
            "> 生成时间：{}　通过 {} / {}（失败即优化前证据）".format(
                time.strftime("%Y-%m-%d %H:%M:%S"), passed, len(results)
            ),
            "",
            "| 场景 | 标题 | 结果 | 失败原因 | 输出摘要 |",
            "|---|---|---|---|---|",
        ]
        for item in results:
            lines.append(
                "| `{}` | {} | {} | {} | {} |".format(
                    item["id"],
                    item["title"],
                    "PASS" if item["ok"] else "FAIL",
                    "；".join(item["reasons"]) or "—",
                    item["excerpt"].replace("|", "\\|") or "—",
                )
            )
        Path(args.report).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("报告已写入 {}".format(args.report))

    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
