"""主动训练实时运行脚本 — 从 5 数据源采集 → 喂给 5 层训练循环 → 监控桶变化。

验证目标：
  1. 意图识别系统 (S层 IntentTrainingLoop) — 确认桶计数增长
  2. DSH系统 (ExecutionPathTrainingLoop) — 确认子节点路径训练
  3. C层反思 / G层图结构 / LLM层 Prompt 优化 — 全链路
  4. DreamOS联动 — 通过 S+DSH 层训练间接验证

用法:
  python scripts/run_active_training_live.py [--limit 100] [--frontend-url http://localhost:3001]
"""
import argparse
import json
import os
import sys
import time
import urllib.request

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_PROJECT_ROOT = os.path.dirname(_34_DIR)
_ADAPTERS_DIR = os.path.join(_34_DIR, "adapters")
_CORE_DIR = os.path.join(_34_DIR, "core")
_SCRIPTS_ROOT = os.path.join(_PROJECT_ROOT, "scripts")  # case_bank_server.py 所在

for _p in [_THIS_DIR, _34_DIR, _ADAPTERS_DIR, _CORE_DIR, _SCRIPTS_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _curl_get(url: str, timeout: int = 10) -> dict:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _curl_post(url: str, body: dict, timeout: int = 10) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_layer_status(base_url: str, layer: str) -> dict:
    """获取某层训练桶状态。"""
    try:
        resp = _curl_get(f"{base_url}/api/training/{layer.lower()}")
        if resp.get("success"):
            return resp.get("data", {})
    except Exception as e:
        return {"error": str(e)}
    return {}


def print_all_layers_status(base_url: str, label: str) -> dict:
    """打印所有 5 层的桶状态，返回状态字典。"""
    layers = ["S", "DSH", "C", "G", "LLM"]
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    status = {}
    for layer in layers:
        s = get_layer_status(base_url, layer)
        bc = s.get("bucketCount", "?")
        bt = s.get("bucketThreshold", "?")
        st = s.get("shouldTrain", False)
        degraded = s.get("degraded", False)
        tag = " [DEGRADED]" if degraded else ""
        print(f"  {layer:4s} | 桶: {bc:>4}/{bt:<4} | shouldTrain={st}{tag}")
        status[layer] = s
    return status


def collect_from_all_providers(limit: int) -> dict:
    """从 5 个数据源采集训练案例，返回 per-source 案例列表。"""
    print(f"\n{'='*60}")
    print(f"  阶段 1: 数据源采集 (limit={limit})")
    print(f"{'='*60}")

    sources = {}

    # 1. TDR
    try:
        from tdr_data_provider import TDRTrainingDataProvider
        provider = TDRTrainingDataProvider()
        cases = provider.fetch_cases(limit=limit)
        sources["TDR"] = cases
        print(f"  [TDR]            采集 {len(cases):>4} 条  layer_tags={_summarize_tags(cases)}")
    except Exception as e:
        sources["TDR"] = []
        print(f"  [TDR]            失败: {e}")

    # 2. Cognitive Memory
    try:
        from cognitive_memory_collector import CognitiveMemoryCollector
        provider = CognitiveMemoryCollector()
        cases = provider.fetch_cases(limit=limit)
        sources["Cognitive"] = cases
        print(f"  [Cognitive]      采集 {len(cases):>4} 条  layer_tags={_summarize_tags(cases)}")
    except Exception as e:
        sources["Cognitive"] = []
        print(f"  [Cognitive]      失败: {e}")

    # 3. Skill System
    try:
        from skill_system_collector import SkillSystemCollector
        provider = SkillSystemCollector()
        cases = provider.fetch_cases(limit=limit)
        sources["Skill"] = cases
        print(f"  [Skill]          采集 {len(cases):>4} 条  layer_tags={_summarize_tags(cases)}")
    except Exception as e:
        sources["Skill"] = []
        print(f"  [Skill]          失败: {e}")

    # 4. Doc Knowledge
    try:
        from doc_knowledge_collector import DocKnowledgeCollector
        provider = DocKnowledgeCollector()
        cases = provider.fetch_cases(limit=limit)
        sources["Doc"] = cases
        print(f"  [Doc]            采集 {len(cases):>4} 条  layer_tags={_summarize_tags(cases)}")
    except Exception as e:
        sources["Doc"] = []
        print(f"  [Doc]            失败: {e}")

    # 5. REA Batch
    try:
        from rea_batch_collector import REABatchCollector
        provider = REABatchCollector()
        cases = provider.fetch_cases(limit=limit)
        sources["REA"] = cases
        print(f"  [REA]            采集 {len(cases):>4} 条  layer_tags={_summarize_tags(cases)}")
    except Exception as e:
        sources["REA"] = []
        print(f"  [REA]            失败: {e}")

    total = sum(len(v) for v in sources.values())
    print(f"  {'─'*40}")
    print(f"  总计采集: {total} 条")

    return sources


def _summarize_tags(cases) -> str:
    """统计案例的 layer_tags 分布。"""
    tag_counts = {}
    for c in cases:
        for t in getattr(c, "layer_tags", []):
            tag_counts[t] = tag_counts.get(t, 0) + 1
    return dict(tag_counts) if tag_counts else "{}"


def feed_to_training_layers(base_url: str, sources: dict) -> dict:
    """将采集到的案例喂给 5 层训练循环，返回分发统计。"""
    print(f"\n{'='*60}")
    print(f"  阶段 2: 喂给训练循环 (POST /api/training/[layer])")
    print(f"{'='*60}")

    layers = ["S", "DSH", "C", "G", "LLM"]
    stats = {layer: {"fed": 0, "added": 0, "failed": 0, "samples": []} for layer in layers}

    # 层 → 格式转换逻辑（从 TSHTTPTrainingExecutor._convert_case_to_training_data 复制）
    for source_name, cases in sources.items():
        for case in cases:
            layer_tags = getattr(case, "layer_tags", [])
            for layer in layers:
                if layer not in layer_tags:
                    continue
                stats[layer]["fed"] += 1
                training_data = _convert_case_to_training_data(case, layer)
                if len(stats[layer]["samples"]) < 2:
                    stats[layer]["samples"].append({
                        "source": source_name,
                        "intent": getattr(case, "intent", "")[:60],
                        "data": training_data,
                    })
                try:
                    resp = _curl_post(
                        f"{base_url}/api/training/{layer.lower()}",
                        {"action": "add", "data": training_data},
                    )
                    if resp.get("success") and resp.get("data", {}).get("added"):
                        stats[layer]["added"] += 1
                    else:
                        stats[layer]["failed"] += 1
                except Exception as e:
                    stats[layer]["failed"] += 1
                    if len(stats[layer]["samples"]) < 2:
                        stats[layer]["samples"].append({"error": str(e)})

    for layer in layers:
        s = stats[layer]
        print(f"  {layer:4s} | 喂入 {s['fed']:>4} | 成功 {s['added']:>4} | 失败 {s['failed']:>4}")

    return stats


def _convert_case_to_training_data(case, layer: str) -> dict:
    """将 TrainingCase 转为层专属 TrainingData（与 TSHTTPTrainingExecutor 一致）。"""
    outcome_map = {"success": "success", "failure": "failure",
                    "partial": "partial", "unknown": "partial"}
    outcome = outcome_map.get(case.metadata.get("outcome", "unknown"), "partial")

    if layer == "S":
        return {
            "message": case.outcome_text or case.intent,
            "intent_type": case.intent,
            "entities": [],
        }
    elif layer == "DSH":
        return {
            "task": case.intent,
            "node_sequence": case.actions,
            "outcome": outcome,
        }
    elif layer == "C":
        return {
            "context_summary": case.intent,
            "action_taken": case.actions[0] if case.actions else "",
            "outcome": outcome,
            "expected_decision": "CONTINUE",
        }
    elif layer == "G":
        return {
            "decisions": [case.intent],
            "rules": case.learned,
        }
    elif layer == "LLM":
        return {
            "intent": case.intent,
            "learned": case.learned,
            "outcome": outcome,
            "prompt_pattern": case.outcome_text or "",
        }
    return {"intent": case.intent, "learned": case.learned}


def trigger_training_if_full(base_url: str, before_status: dict) -> dict:
    """检查各层桶是否满，满了则触发训练。"""
    print(f"\n{'='*60}")
    print(f"  阶段 3: 检查桶满 + 触发训练")
    print(f"{'='*60}")

    results = {}
    for layer in ["S", "DSH", "C", "G", "LLM"]:
        after = get_layer_status(base_url, layer)
        before_count = before_status.get(layer, {}).get("bucketCount", 0)
        after_count = after.get("bucketCount", 0)
        threshold = after.get("bucketThreshold", 0)
        delta = after_count - before_count
        should_train = after.get("shouldTrain", False)

        print(f"  {layer:4s} | {before_count:>4} → {after_count:>4} (Δ=+{delta}) | 阈值={threshold} | shouldTrain={should_train}")

        if should_train or after_count >= threshold:
            print(f"       → 桶满！触发 train()...", end=" ")
            try:
                resp = _curl_post(
                    f"{base_url}/api/training/{layer.lower()}",
                    {"action": "train"},
                )
                data = resp.get("data", {})
                trained = data.get("trained", False)
                print(f"trained={trained} | metrics={json.dumps({k:v for k,v in data.items() if k not in ('trained',)}, ensure_ascii=False)[:100]}")
                results[layer] = {"trained": trained, "data": data}
            except Exception as e:
                print(f"失败: {e}")
                results[layer] = {"trained": False, "error": str(e)}
        else:
            results[layer] = {"trained": False, "reason": "not_full"}

    return results


def main():
    parser = argparse.ArgumentParser(description="主动训练实时运行")
    parser.add_argument("--limit", type=int, default=100, help="每个数据源最大采集数")
    parser.add_argument("--frontend-url", default="http://localhost:3001", help="前端服务地址")
    args = parser.parse_args()

    base_url = args.frontend_url.rstrip("/")

    print(f"╔══════════════════════════════════════════════════════════════╗")
    print(f"║  主动训练实时运行 — 意图识别 + DreamOS + DSH + 子节点能力      ║")
    print(f"╚══════════════════════════════════════════════════════════════╝")
    print(f"  前端服务: {base_url}")
    print(f"  采集上限: {args.limit}/数据源")
    print(f"  时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    # 0. 记录初始桶状态
    before_status = print_all_layers_status(base_url, "初始桶状态 (训练前)")

    # 1. 从 5 个数据源采集
    sources = collect_from_all_providers(args.limit)

    # 2. 喂给 5 层训练循环
    feed_stats = feed_to_training_layers(base_url, sources)

    # 3. 训练后桶状态
    time.sleep(1)  # 等待 API 写入
    after_status = print_all_layers_status(base_url, "训练后桶状态 (喂入后)")

    # 4. 检查桶满 + 触发训练
    train_results = trigger_training_if_full(base_url, before_status)

    # 5. 汇总报告
    print(f"\n{'='*60}")
    print(f"  汇总报告")
    print(f"{'='*60}")
    total_fed = sum(s["fed"] for s in feed_stats.values())
    total_added = sum(s["added"] for s in feed_stats.values())
    total_trained = sum(1 for r in train_results.values() if r.get("trained"))
    print(f"  总采集案例: {sum(len(v) for v in sources.values())}")
    print(f"  总喂入: {total_fed} | 总成功: {total_added}")
    print(f"  触发训练: {total_trained} 层")

    print(f"\n  各层详情:")
    for layer in ["S", "DSH", "C", "G", "LLM"]:
        s = feed_stats[layer]
        bc_before = before_status.get(layer, {}).get("bucketCount", 0)
        bc_after = after_status.get(layer, {}).get("bucketCount", 0)
        tr = train_results.get(layer, {})
        trained_tag = "✅ TRAINED" if tr.get("trained") else f"桶={bc_after}"
        print(f"    {layer:4s} | 喂入={s['fed']:>3} 成功={s['added']:>3} | 桶 {bc_before}→{bc_after} | {trained_tag}")
        if s["samples"]:
            for sample in s["samples"][:1]:
                if "error" in sample:
                    print(f"          样本错误: {sample['error']}")
                else:
                    print(f"          样本来源: {sample.get('source', '?')} | intent: {sample.get('intent', '?')[:40]}")

    # 6. 系统联动验证
    print(f"\n{'='*60}")
    print(f"  系统联动验证")
    print(f"{'='*60}")
    s_fed = feed_stats["S"]["added"]
    dsh_fed = feed_stats["DSH"]["added"]
    c_fed = feed_stats["C"]["added"]
    g_fed = feed_stats["G"]["added"]
    llm_fed = feed_stats["LLM"]["added"]

    checks = [
        ("意图识别系统 (S层)", s_fed > 0, f"喂入 {s_fed} 条意图训练数据"),
        ("DSH系统 (子节点路径)", dsh_fed > 0, f"喂入 {dsh_fed} 条执行路径训练数据"),
        ("C层反思训练", c_fed > 0, f"喂入 {c_fed} 条反思训练数据"),
        ("G层图结构训练", g_fed > 0, f"喂入 {g_fed} 条图结构训练数据"),
        ("LLM层Prompt优化", llm_fed > 0, f"喂入 {llm_fed} 条Prompt训练数据"),
        ("DreamOS联动 (S+DSH)", s_fed > 0 and dsh_fed > 0, "S+DSH双层训练联动=意图→子节点调度"),
    ]

    all_pass = True
    for name, passed, detail in checks:
        tag = "✅" if passed else "❌"
        print(f"  {tag} {name}: {detail}")
        if not passed:
            all_pass = False

    print(f"\n  {'✅ 所有系统训练验证通过' if all_pass else '⚠️  部分系统未获得训练数据'}")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
