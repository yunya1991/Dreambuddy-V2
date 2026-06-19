#!/usr/bin/env python3
"""S 系列策略链 - 多场景压力测试（使用 curl 命令）"""
import subprocess
import json
import time
import concurrent.futures
import threading

API = "http://localhost:3000/api/chat"
curl_lock = threading.Lock()

def post_curl(data: dict, label: str = ""):
    """用 curl 发送 POST 请求"""
    import subprocess, json, time

    cmd = [
        'curl', '-s', '--max-time', '40',
        '-X', 'POST', API,
        '-H', 'Content-Type: application/json',
        '-d', json.dumps(data),
    ]

    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=45
        )
        duration_ms = int((time.time() - start) * 1000)

        if not result.stdout:
            return {"error": f"No output (stderr: {result.stderr[:100]})"}, duration_ms, 0, label

        try:
            return json.loads(result.stdout), duration_ms, 200, label
        except json.JSONDecodeError:
            return {"error": f"Invalid JSON: {result.stdout[:200]}"}, duration_ms, 0, label

    except subprocess.TimeoutExpired:
        duration_ms = int((time.time() - start) * 1000)
        return {"error": "Request timeout (45s)"}, duration_ms, 0, label
    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        return {"error": str(e)}, duration_ms, 0, label

def parse(result):
    data, dur, status, label = result
    print(f"\n{'='*55}")
    print(f"[{label}]")
    print(f"  HTTP: {status} | 耗时: {dur}ms")

    if "error" in data:
        print(f"  ❌ ERROR: {data['error']}")
        return False

    success = data.get("success", False)
    print(f"  ✅ success: {success}")

    # 找 data 字段（有些返回直接在顶层，有些在 data 下）
    top = data if data.get("data") is None else data.get("data", {})
    content = top.get("content", "") or data.get("content", "")
    intent = top.get("intent") or data.get("intent")
    llm_status = top.get("llm_status") or data.get("llm_status")
    routing = top.get("routing") or data.get("routing", {})
    scs = (top.get("strategyChainState") or data.get("strategyChainState")) or {}
    cs = (top.get("chainState") or data.get("chainState")) or {}

    print(f"  llm_status: {llm_status or 'N/A'}")
    print(f"  intent: {intent or 'N/A'}")

    current_step = scs.get('currentStep') or '(无)'
    scope = scs.get('scope') or '(无)'
    chain = routing.get('chain', []) if isinstance(routing, dict) else []

    print(f"  strategyChainState.currentStep: {current_step}")
    print(f"  strategyChainState.scope: {scope}")
    print(f"  chainState (D-Z-E): {cs.get('current_phase', '(无)')}")
    print(f"  routing.chain: {chain}")
    print(f"  needsConfirmation: {top.get('needsConfirmation') or data.get('needsConfirmation', False)}")
    print(f"  content长度: {len(content)} chars")

    # 检查样式标签
    found_style = None
    for tag in ["📊 数据驱动视角", "📖 叙事解读视角", "✅ 清单式视角",
                 "| Data-driven", "| Narrative", "| Structured"]:
        if tag in content:
            found_style = tag
            break
    print(f"  响应样式标签: {found_style or '(未检测到)'} {'✓' if found_style else ''}")

    if "LLM 调用超时" in content:
        print(f"  ⚠️ LLM 超时降级已触发")

    preview = content[:400].replace("\n", " ").strip()
    print(f"  内容预览: {preview}...")

    return success

def main():
    print("="*55)
    print("  S 系列策略链 - 多场景压力测试（curl）")
    print(f"  测试时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*55)

    scenarios = [
        ("场景1-BTC深度", {"message": "我想深度分析一下 BTC 走势，制定一个交易策略", "session_id": "st1", "thinking_mode": "deep"}),
        ("场景2-继续", {"message": "继续", "session_id": "st1", "thinking_mode": "deep"}),
        ("场景3-跳过", {"message": "跳过设计直接到验证", "session_id": "st1", "thinking_mode": "deep"}),
        ("场景4-调整", {"message": "把止损改成 1%，风险稍微提高一些", "session_id": "st1", "thinking_mode": "deep"}),
        ("场景5-摘要", {"message": "只看当前阶段的结论摘要", "session_id": "st1", "thinking_mode": "deep"}),
        ("场景6-解释", {"message": "详细解释一下当前策略的设计逻辑", "session_id": "st1", "thinking_mode": "deep"}),
        ("场景7-落地", {"message": "方案已经很完善了，直接落地执行", "session_id": "st1", "thinking_mode": "deep"}),
        ("场景8-黄金", {"message": "帮我分析一下黄金走势", "session_id": "st2", "thinking_mode": "deep"}),
        ("场景9-ETH", {"message": "分析 ETH 的交易策略", "session_id": "st3", "thinking_mode": "deep"}),
        ("场景10-快速", {"message": "快速分析一下 BTC 当前走势", "session_id": "st4", "thinking_mode": "quick"}),
        ("场景11-英文", {"message": "Analyze BTC and give me a trading strategy", "session_id": "st5", "thinking_mode": "deep"}),
        ("场景12-选项1", {"message": "1", "session_id": "st6", "thinking_mode": "deep"}),
        ("场景12-选项2", {"message": "2", "session_id": "st6", "thinking_mode": "deep"}),
        ("场景13-无效", {"message": "哈哈哈哈随便说点啥", "session_id": "st7", "thinking_mode": "deep"}),
        ("场景14-换标的", {"message": "换成分析 ETH 吧", "session_id": "st1", "thinking_mode": "deep"}),
    ]

    results = []
    for label, payload in scenarios:
        print(f"\n⏳ [{label}]...", end=" ", flush=True)
        result = post_curl(payload, label)
        ok = parse(result)
        results.append((label, ok))
        time.sleep(1)

    # 样式多样性
    print(f"\n{'='*55}")
    print(f"【场景15】样式多样性（3 次请求）")
    print(f"{'='*55}")
    styles = set()
    for i in range(3):
        print(f"\n⏳ [样式{i+1}]...", end=" ", flush=True)
        result = post_curl({"message": "分析 BTC 走势", "session_id": f"style{i}", "thinking_mode": "deep"}, f"样式{i+1}")
        parse(result)
        top = result[0].get("data") or result[0]
        content = top.get("content", "")
        for tag in ["📊 数据驱动视角", "📖 叙事解读视角", "✅ 清单式视角"]:
            if tag in content:
                styles.add(tag)
                break
        time.sleep(1)
    print(f"\n  样式多样性: {len(styles)} 种 → {styles}")

    # 并发
    print(f"\n{'='*55}")
    print(f"【场景16】5 并发")
    print(f"{'='*55}")
    paras = [{"message": f"深度分析 BTC {i}", "session_id": f"para{i}", "thinking_mode": "deep"} for i in range(5)]
    start = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        futures = [ex.submit(post_curl, p, f"并发{i+1}") for i, p in enumerate(paras)]
        pres = [f.result() for f in concurrent.futures.as_completed(futures)]
    total_ms = int((time.time() - start) * 1000)
    print(f"5 并发总耗时: {total_ms}ms")
    para_ok = sum(1 for r in pres if parse(r) and not r[0].get("error"))

    # 汇总
    print(f"\n{'='*55}")
    print(f"  📊 测试汇总")
    print(f"{'='*55}")
    seq_ok = sum(1 for _, ok in results if ok)
    print(f"\n顺序测试: {seq_ok}/{len(results)}")
    for label, ok in results:
        print(f"  {'✅' if ok else '❌'} {label}")
    print(f"\n并发测试: {para_ok}/5")
    print(f"样式多样性: {len(styles)} 种")
    total_ok = seq_ok + para_ok
    total_tests = len(results) + 5
    print(f"\n总计: {total_ok}/{total_tests}")
    if total_ok == total_tests:
        print("🎉 全部通过！")
    else:
        print(f"⚠️ {total_tests - total_ok} 个失败")

if __name__ == "__main__":
    main()
