import json

with open('artifact-stress-tests/stress-test-20260619162830.json') as f:
    results = json.load(f)

print("=== deep_analysis 样本 (index 0) ===")
r = results[0]
print(f"keys:", list(r.keys()))
print(f"chain_executed:", r.get('chain_executed'))
print(f"graph_reflection_data:", r.get('graph_reflection_data'))
print(f"has_graph_reflection:", r.get('has_graph_reflection'))
print(f"artifacts_produced:", r.get('artifacts_produced'))
print(f"artifact_count:", r.get('artifact_count'))
print(f"step_metadata_count:", r.get('step_metadata_count'))
print(f"success:", r.get('success'))
print()

print("=== market_query 样本 (index 20) ===")
r2 = results[20]
print(f"chain_executed:", r2.get('chain_executed'))
print(f"graph_reflection_data:", r2.get('graph_reflection_data'))
print(f"has_graph_reflection:", r2.get('has_graph_reflection'))
print(f"step_metadata_count:", r2.get('step_metadata_count'))
print(f"artifacts_produced:", r2.get('artifacts_produced'))
print()

print("=== execute_trade 样本 (index 12) - 期望但不匹配 ===")
r3 = results[12]
print(f"actual_intent:", r3.get('actual_intent'))
print(f"expected intent: execute_trade")
print(f"chain_executed:", r3.get('chain_executed'))
print(f"success:", r3.get('success'))
print()

print("=== 各类意图的 chain_executed 格式 ===")
for idx in [0, 4, 8, 12, 16, 20, 23, 26]:
    r = results[idx]
    print(f"{r['intent']}: chain_len={len(r['chain_executed'])}, chain={r['chain_executed'][:3]}")
print()

print("=== 总体统计 ===")
total = len(results)
success = sum(1 for r in results if r['success'])
intents_match = sum(1 for r in results if r['intent_match'])
has_graph = sum(1 for r in results if r['has_graph_reflection'])
total_artifacts = sum(r['artifact_count'] for r in results)
print(f"Total: {total}")
print(f"Success: {success} ({success/total*100:.0f}%)")
print(f"Intent match: {intents_match} ({intents_match/total*100:.0f}%)")
print(f"Has graph_reflection: {has_graph} ({has_graph/total*100:.0f}%)")
print(f"Total artifacts: {total_artifacts}")
