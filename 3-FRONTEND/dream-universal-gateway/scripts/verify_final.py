import sys, json, urllib.request, time

def test_api(msg, sid):
    print("="*60)
    print("测试: " + msg[:50])
    print("="*60)
    req = urllib.request.Request(
        'http://localhost:3000/api/task',
        data=json.dumps({'message': msg, 'session_id': sid}).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    try:
        resp = urllib.request.urlopen(req, timeout=120)
        data = json.loads(resp.read())
    except Exception as e:
        print("  ❌ 网络错误:", str(e)[:50])
        return False

    if not data.get('success'):
        print("  ❌ API 错误:", str(data.get('error'))[:50])
        return False

    d = data['data']
    actual_intent = d['intent']['type']
    chain = d['execution_summary'].get('chain_executed', [])
    artifacts = d.get('artifacts_produced', [])
    gr = d['execution_summary'].get('graph_reflection')
    sm = d['metadata'].get('step_metadata')
    executor = d['metadata'].get('executor')
    exec_time = d.get('execution_time_ms', 0)

    print("  意图:", actual_intent)
    print("  链:", len(chain), "步")
    print("  产物:", len(artifacts), "个")
    if artifacts:
        types = []
        for a in artifacts[:3]:
            types.append(a.get('type', 'unknown'))
        print("    类型:", types)
    if gr:
        print("  graph_reflection: ✅ total_nodes=", gr.get('total_nodes'), ", avg_conf=", gr.get('avg_confidence'), ", hv_nodes=", gr.get('high_value_nodes'))
    else:
        print("  graph_reflection: ❌ 缺失")
    if sm and isinstance(sm, list) and len(sm) > 0:
        print("  step_metadata: ✅ count=", len(sm))
        for s in sm[:2]:
            if isinstance(s, dict):
                print("    -", s.get('step', '?'), ": conf=", s.get('confidence', '?'))
    else:
        print("  step_metadata: ❌ 缺失或空")
    print("  执行器:", executor)
    print("  时间:", exec_time, "ms")
    return True

tests = [
    ('深度分析 BTC 当前趋势', 'deep_analysis'),
    ('推演 ETH 如果跌破关键支撑位', 'scenario_sim'),
    ('验证 BTC 均线交叉策略的有效性', 'strategy_verify'),
    ('BTC 现在的价格是多少', 'market_query'),
]

for i, (msg, expected) in enumerate(tests):
    print()
    print("【" + str(i+1) + "/" + str(len(tests)) + "】预期: " + expected)
    timestamp = int(time.time())
    result = test_api(msg, 'vtest_' + str(i) + '_' + str(timestamp))
    if i < len(tests)-1:
        time.sleep(8)

print()
print("="*60)
print("测试完成！")
print("="*60)
