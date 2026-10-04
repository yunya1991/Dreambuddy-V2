#!/usr/bin/env python3
"""Jev Judge IPC 端到端验证脚本

通过 stdin/stdout 与 server.py 通信，验证 jev_judge IPC 路由完整链路。
覆盖降级路径（不需要真实 API Key）。

运行: python3 verify_jev_ipc_e2e.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_PY = os.path.join(SERVER_DIR, "server.py")


def send_request(proc, method, params, req_id):
    """发送 IPC 请求"""
    request = {
        "schema_version": "1.0.0",
        "message_type": "request",
        "method": method,
        "params": params,
        "id": req_id,
        "timestamp": "2026-09-22T00:00:00Z",
    }
    proc.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
    proc.stdin.flush()


def read_response(proc, timeout=10):
    """读取 IPC 响应（按行过滤，只取 message_type=response 的行）"""
    start = time.time()
    while time.time() - start < timeout:
        line = proc.stdout.readline()
        if not line:
            continue
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
            if parsed.get("schema_version") and parsed.get("message_type") == "response":
                return parsed
        except json.JSONDecodeError:
            continue
    return None


def run_e2e_scenarios():
    """运行 E2E 场景"""
    scenarios = [
        {
            "name": "E2E-开关关闭降级",
            "env": {"ENABLE_JEV_JUDGE": "0"},
            "params": {"state": "test", "questions": {"q": {"type": "noul", "instructions": "x"}}},
            "check": lambda r: r["result"]["degraded"] is True and r["result"]["reason"] == "jev_judge_disabled",
        },
        {
            "name": "E2E-缺APIKey降级",
            "env": {"ENABLE_JEV_JUDGE": "1", "TYPESAFE_API_KEY": ""},
            "params": {"state": "test", "questions": {"q": {"type": "noul", "instructions": "x"}}},
            "check": lambda r: r["result"]["degraded"] is True and r["result"]["reason"] == "missing TYPESAFE_API_KEY",
        },
        {
            "name": "E2E-无效question类型",
            "env": {"ENABLE_JEV_JUDGE": "1", "TYPESAFE_API_KEY": "fake"},
            "params": {"state": "test", "questions": {"q": {"type": "bogus", "instructions": "x"}}},
            "check": lambda r: r["result"]["degraded"] is True and "invalid type" in r["result"]["reason"],
        },
        {
            "name": "E2E-空questions",
            "env": {"ENABLE_JEV_JUDGE": "1", "TYPESAFE_API_KEY": "fake"},
            "params": {"state": "test", "questions": {}},
            "check": lambda r: r["result"]["degraded"] is True and "invalid_questions" in r["result"]["reason"],
        },
        {
            "name": "E2E-choice缺criteria",
            "env": {"ENABLE_JEV_JUDGE": "1", "TYPESAFE_API_KEY": "fake"},
            "params": {"state": "test", "questions": {"q": {"type": "choice", "instructions": "x"}}},
            "check": lambda r: r["result"]["degraded"] is True and "criteria" in r["result"]["reason"],
        },
        {
            "name": "E2E-score缺criteria",
            "env": {"ENABLE_JEV_JUDGE": "1", "TYPESAFE_API_KEY": "fake"},
            "params": {"state": "test", "questions": {"q": {"type": "score", "instructions": "x"}}},
            "check": lambda r: r["result"]["degraded"] is True and "criteria" in r["result"]["reason"],
        },
        {
            "name": "E2E-多问题并行(noul+choice+score)",
            "env": {"ENABLE_JEV_JUDGE": "1", "TYPESAFE_API_KEY": "fake"},
            "params": {
                "state": "test",
                "questions": {
                    "n1": {"type": "noul", "instructions": "is done?"},
                    "c1": {"type": "choice", "instructions": "which?", "criteria": {"a": "x", "b": "y"}},
                    "s1": {"type": "score", "instructions": "how good?", "criteria": ["low", "high"]},
                },
            },
            # 有 fake key 但会调用真实 API → 401 → degraded
            "check": lambda r: r["result"]["degraded"] is True,
        },
    ]

    print("=" * 70)
    print("Jev Judge IPC 端到端验证（通过 server.py 完整路由）")
    print("=" * 70)

    passed = 0
    failed = 0

    for i, scenario in enumerate(scenarios, 1):
        name = scenario["name"]
        env = os.environ.copy()
        env.update(scenario["env"])

        # 启动 server.py 子进程
        proc = subprocess.Popen(
            [sys.executable, SERVER_PY],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
            text=True,
            bufsize=1,
        )

        try:
            # 等待 server 启动
            time.sleep(0.5)

            req_id = f"e2e-{i}"
            send_request(proc, "jev_judge", scenario["params"], req_id)
            response = read_response(proc)

            if response is None:
                print(f"\n[{i:2d}/{len(scenarios)}] FAIL - {name}")
                print(f"     无响应（超时）")
                failed += 1
                continue

            if not response.get("ok"):
                print(f"\n[{i:2d}/{len(scenarios)}] FAIL - {name}")
                print(f"     IPC ok=False: {response.get('error')}")
                failed += 1
                continue

            # 验证响应
            try:
                ok = scenario["check"](response)
                if ok:
                    print(f"\n[{i:2d}/{len(scenarios)}] PASS - {name}")
                    print(f"     degraded={response['result'].get('degraded')}, reason={response['result'].get('reason', 'N/A')}")
                    passed += 1
                else:
                    print(f"\n[{i:2d}/{len(scenarios)}] FAIL - {name}")
                    print(f"     实际结果: {json.dumps(response['result'], ensure_ascii=False)}")
                    failed += 1
            except Exception as e:
                print(f"\n[{i:2d}/{len(scenarios)}] FAIL - {name}")
                print(f"     校验异常: {e}")
                print(f"     实际结果: {json.dumps(response['result'], ensure_ascii=False)}")
                failed += 1

        finally:
            proc.terminate()
            proc.wait(timeout=5)

    print("\n" + "=" * 70)
    print(f"结果: {passed} passed, {failed} failed, 共 {len(scenarios)} E2E 场景")
    print("=" * 70)

    if failed > 0:
        print("\n存在失败场景 ❌")
        return 1
    print("\n所有 E2E 场景验证通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(run_e2e_scenarios())
