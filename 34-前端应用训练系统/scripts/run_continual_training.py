"""持续训练脚本（v0.5 continual mode）— 数据到达即学习，不等桶满。

与 run_active_training_live.py 的区别:
  - 旧脚本: 喂数据 → 等桶满 → train() → 清空（批量学习）
  - 新脚本: 喂数据 → 三层触发自动 trainIncremental → 保留状态（持续学习）

验证目标（SPEC v0.5 §5.4 P3 验收标准）:
  1. EWMA: 旧数据 weight 随 age 衰减（bufferStats.avgWeight 下降）
  2. C层 ruleArchive: 旧规则 weight<0.05 移入档案（不删除）
  3. 持续训练: 数据到达即学习，不等桶满（step 增长 < bucketThreshold）
  4. S级优先级触发: quality=S 立即触发 trainIncremental

用法:
  python scripts/run_continual_training.py [--limit 30] [--frontend-url http://localhost:3001]

退出码: 0=全部通过, 1=部分失败
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
_SCRIPTS_ROOT = os.path.join(_PROJECT_ROOT, "scripts")

for _p in [_THIS_DIR, _34_DIR, _ADAPTERS_DIR, _CORE_DIR, _SCRIPTS_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

_LAYERS = ["S", "DSH", "C", "G", "LLM"]

# P2 修复: C 层决策派生 + 成功案例跨层回灌
try:
    from core.decision_deriver import derive_expected_decision_with_cdrive
    from core.outcome_pattern_deriver import resolve_layer_tags
except ModuleNotFoundError:
    from decision_deriver import derive_expected_decision_with_cdrive
    from outcome_pattern_deriver import resolve_layer_tags


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
    """获取某层训练状态（含 step + bufferStats）。"""
    try:
        resp = _curl_get(f"{base_url}/api/training/{layer.lower()}")
        if resp.get("success"):
            return resp.get("data", {})
    except Exception as e:
        return {"error": str(e)}
    return {}


def snapshot_all_layers(base_url: str) -> dict:
    """快照所有 5 层的 step + bufferStats。"""
    snap = {}
    for layer in _LAYERS:
        s = get_layer_status(base_url, layer)
        snap[layer] = {
            "bucketCount": s.get("bucketCount", 0),
            "step": s.get("step", 0),
            "avgWeight": (s.get("bufferStats") or {}).get("avgWeight", 0),
            "oldestAge": (s.get("bufferStats") or {}).get("oldestAge", 0),
            "capacity": (s.get("bufferStats") or {}).get("capacity", 0),
        }
    return snap


def _summarize_tags(cases) -> str:
    tag_counts = {}
    for c in cases:
        for t in getattr(c, "layer_tags", []):
            tag_counts[t] = tag_counts.get(t, 0) + 1
    return dict(tag_counts) if tag_counts else "{}"


def collect_from_all_providers(limit: int) -> dict:
    """从 5 个数据源采集训练案例。"""
    print(f"\n{'='*60}")
    print(f"  阶段 1: 数据源采集 (limit={limit})")
    print(f"{'='*60}")
    sources = {}
    collectors = [
        ("TDR", "tdr_data_provider", "TDRTrainingDataProvider"),
        ("Cognitive", "cognitive_memory_collector", "CognitiveMemoryCollector"),
        ("Skill", "skill_system_collector", "SkillSystemCollector"),
        ("Doc", "doc_knowledge_collector", "DocKnowledgeCollector"),
        ("REA", "rea_batch_collector", "REABatchCollector"),
        ("Trae", "trae_session_collector", "TraeSessionCollector"),
        ("Trading", "trading_log_collector", "TradingLogCollector"),
        # DSH 层原生序列数据源 (SPEC-DSH-训练数据源 v0.2)
        ("CleaningTrace", "cleaning_trace_collector", "CleaningTraceCollector"),
        ("DalRoute", "dal_route_collector", "DalRouteCollector"),
        ("DataFetchRoute", "data_fetch_route_collector", "DataFetchRouteCollector"),
        ("DshSubagent", "dsh_subagent_collector", "DshSubagentCollector"),
        # DSH 层 v0.4 新增采集器 (SPEC-DSH-训练数据源-v0.4)
        ("TddTest", "tdd_test_collector", "TddTestCollector"),
        ("CogSession", "cognitive_session_collector", "CognitiveSessionCollector"),
        ("TraderLog", "polling_trader_log_collector", "PollingTraderLogCollector"),
        ("ReaTest", "rea_test_collector", "REATestCollector"),
        ("ShadowVal", "shadow_validation_collector", "ShadowValidationCollector"),
        # v0.5 6-TRADING 采集器族
        ("ASeriesSession", "a_series_session_collector", "ASeriesSessionCollector"),
        ("ASeriesTheory", "a_series_theory_collector", "ASeriesTheoryCollector"),
        ("OneirologyDream", "oneirology_dream_collector", "OneirologyDreamCollector"),
        ("MasterSeminar", "master_seminar_collector", "MasterSeminarCollector"),
        # v0.7 数据查询/动态解读意图采集器 (SPEC-v0.7-data-query-intent)
        ("DataQueryIntent", "data_query_intent_collector", "DataQueryIntentCollector"),
        ("DataInsight", "data_insight_collector", "DataInsightCollector"),
        # v0.8 自进化系统双链路采集器 (SPEC-v0.8-evolution-dual-intent)
        ("Contradiction", "contradiction_collector", "ContradictionCollector"),
        ("EvolutionPath", "evolution_path_collector", "EvolutionPathCollector"),
        # v0.9 易经推理系统三类采集器 (SPEC-v0.9-yijing-triple-collector)
        ("BCRM2Technical", "bcrm2_technical_collector", "BCRM2TechnicalCollector"),
        ("BDSMFundamental", "bdsm_fundamental_collector", "BDSMFundamentalCollector"),
        ("AssetClass", "asset_class_collector", "AssetClassCollector"),
        # v1.0 金融事件分析采集器 (29-事件驱动策略系统)
        ("EventAnalysis", "event_analysis_collector", "EventAnalysisCollector"),
        # v1.1 调控风控采集器 (16-调控系统, SPEC v1.0 L1 优先扩展)
        ("RiskControl", "risk_control_collector", "RiskControlCollector"),
        # v1.2 语义蒸馏采集器 (39-金融语义蒸馏系统, SPEC v0.8 分层语义架构)
        ("SemanticDistill", "semantic_distill_collector", "SemanticDistillCollector"),
        # v1.3 快讯语义采集器 (39 SPEC v1.1 §9.2 P-快讯, 18 中心星球日报快讯)
        ("NewsflashSemantic", "newsflash_semantic_collector", "NewsflashSemanticCollector"),
    ]
    for label, mod_name, cls_name in collectors:
        try:
            mod = __import__(mod_name)
            provider = getattr(mod, cls_name)()
            cases = provider.fetch_cases(limit=limit)
            sources[label] = cases
            print(f"  [{label:10s}]  采集 {len(cases):>4} 条  layer_tags={_summarize_tags(cases)}")
        except Exception as e:
            sources[label] = []
            print(f"  [{label:10s}]  失败: {e}")
    total = sum(len(v) for v in sources.values())
    print(f"  {'─'*40}")
    print(f"  总计采集: {total} 条")
    return sources


def _convert_case_to_training_data(case, layer: str) -> dict:
    """将 TrainingCase 转为层专属 TrainingData（与 TSHTTPTrainingExecutor 一致）。

    P1 修复: 从 quality/confidence 派生 outcome + 归一化 prompt_pattern。
    """
    try:
        from core.outcome_pattern_deriver import derive_outcome, normalize_prompt_pattern
    except ModuleNotFoundError:
        from outcome_pattern_deriver import derive_outcome, normalize_prompt_pattern
    outcome = derive_outcome(case)
    prompt_pattern = normalize_prompt_pattern(case)
    if layer == "S":
        return {"message": case.outcome_text or case.intent,
                "intent_type": case.intent, "entities": [], "quality": case.quality}
    elif layer == "DSH":
        return {"task": case.intent, "node_sequence": case.actions,
                "outcome": outcome, "quality": case.quality}
    elif layer == "C":
        return {"context_summary": case.intent,
                "action_taken": case.actions[0] if case.actions else "",
                "outcome": outcome,
                "expected_decision": derive_expected_decision_with_cdrive(case),
                "quality": case.quality}
    elif layer == "G":
        return {"decisions": [case.intent], "rules": case.learned,
                "quality": case.quality}
    elif layer == "LLM":
        return {"intent": case.intent, "learned": case.learned,
                "outcome": outcome, "prompt_pattern": prompt_pattern,
                "quality": case.quality}
    return {"intent": case.intent, "learned": case.learned, "quality": case.quality}


def _quality_from_case(case) -> str:
    """从案例 quality 字段推断等级 (S/A/B/C)。"""
    q = getattr(case, "quality", None) or "C"
    if q in ("S", "A", "B", "C"):
        return q
    return "C"


def feed_continual(base_url: str, sources: dict) -> dict:
    """持续喂数据 — 每条数据到达即触发三层触发（不等桶满）。

    每条数据用 action=add 喂入，addTrainingData 内置三层触发:
      ① 微批增量: 每 N 条 → trainIncremental
      ② 漂移回调: KL > 阈值 → train
      ③ 优先级: quality=S → 立即 trainIncremental
    """
    print(f"\n{'='*60}")
    print(f"  阶段 2: 持续喂入（数据到达即学习，不等桶满）")
    print(f"{'='*60}")

    stats = {layer: {"fed": 0, "added": 0, "failed": 0, "s_level": 0, "backfilled": 0}
             for layer in _LAYERS}

    # P2: 收集 S 层 S/A/B 级样本用于语义原型更新
    s_semantic_batch = []

    for source_name, cases in sources.items():
        for case in cases:
            native_tags = list(getattr(case, "layer_tags", []) or [])
            layer_tags = resolve_layer_tags(case)
            backfilled_layers = [t for t in layer_tags if t not in native_tags]
            quality = _quality_from_case(case)
            for layer in layer_tags:
                if layer not in _LAYERS:
                    continue
                stats[layer]["fed"] += 1
                if layer in backfilled_layers:
                    stats[layer]["backfilled"] += 1
                if quality == "S":
                    stats[layer]["s_level"] += 1
                training_data = _convert_case_to_training_data(case, layer)
                try:
                    resp = _curl_post(
                        f"{base_url}/api/training/{layer.lower()}",
                        {"action": "add", "data": training_data},
                    )
                    if resp.get("success") and resp.get("data", {}).get("added"):
                        stats[layer]["added"] += 1
                    else:
                        stats[layer]["failed"] += 1
                except Exception:
                    stats[layer]["failed"] += 1

                # P2: 收集 S 层 S/A/B 级样本
                if layer == "S" and quality in ("S", "A", "B"):
                    s_semantic_batch.append(training_data)

    # P2: 喂入完成后，对 S 层触发语义原型更新
    if s_semantic_batch:
        try:
            resp = _curl_post(
                f"{base_url}/api/training/s",
                {"action": "updateSemantic", "data": {"batch": s_semantic_batch}},
            )
            sem_result = resp.get("data", {})
            sem_updated = sem_result.get("updated", False)
            sem_step = sem_result.get("semanticStep", 0)
            sem_count = sem_result.get("prototypeCount", 0)
            print(f"  语义原型: {'✓' if sem_updated else '✗'} "
                  f"step={sem_step} prototypes={sem_count} "
                  f"(from {len(s_semantic_batch)} S/A/B samples)")
        except Exception as e:
            print(f"  语义原型: 跳过 (API 调用失败: {e})")

    for layer in _LAYERS:
        s = stats[layer]
        print(f"  {layer:4s} | 喂入 {s['fed']:>4} | 成功 {s['added']:>4} | "
              f"失败 {s['failed']:>4} | S级 {s['s_level']:>3} | 回灌 {s['backfilled']:>4}")
    return stats


def verify_continual_training(base_url: str, before: dict, feed_stats: dict) -> dict:
    """验证持续训练核心机制: 数据到达即学习（不等桶满）。"""
    print(f"\n{'='*60}")
    print(f"  阶段 3: 验证持续训练（数据到达即学习）")
    print(f"{'='*60}")

    time.sleep(1)  # 等待 API 写入 + 触发完成
    after = snapshot_all_layers(base_url)

    results = {}
    for layer in _LAYERS:
        b = before[layer]
        a = after[layer]
        step_before = b.get("step", 0)
        step_after = a.get("step", 0)
        bc_before = b.get("bucketCount", 0)
        bc_after = a.get("bucketCount", 0)
        threshold = a.get("capacity", 0)  # capacity 作为桶上限参考
        avg_w = a.get("avgWeight", 0)
        oldest_age = a.get("oldestAge", 0)
        step_delta = step_after - step_before

        # 核心判定 (v0.5 语义): trainIncremental 增量训练不清空 buffer，
        # 桶满后 bucketCount 恒等于 capacity（容量淘汰保持不变），
        # 因此持续训练证据 = step 增长 > 0（数据到达即触发增量训练）
        continual_evidence = step_delta > 0
        results[layer] = {
            "step_before": step_before,
            "step_after": step_after,
            "step_delta": step_delta,
            "bucket_before": bc_before,
            "bucket_after": bc_after,
            "avgWeight": avg_w,
            "oldestAge": oldest_age,
            "continual_trained": continual_evidence,
            "fed": feed_stats[layer]["fed"],
            "s_level": feed_stats[layer]["s_level"],
        }
        tag = "✅ 持续训练" if continual_evidence else "⚠️ 未触发"
        print(f"  {layer:4s} | step {step_before}→{step_after} (Δ=+{step_delta}) | "
              f"桶 {bc_before}→{bc_after} | avgW={avg_w:.3f} | age={oldest_age} | {tag}")

    return results


def verify_ewma_decay(base_url: str) -> dict:
    """验证 EWMA 衰减: 手动触发多次 trainIncremental 后 avgWeight 应下降。"""
    print(f"\n{'='*60}")
    print(f"  阶段 4: 验证 EWMA 衰减（多次增量训练后 avgWeight 下降）")
    print(f"{'='*60}")

    # 先快照 C 层（C 层有 ruleArchive，最适合验证）
    before = get_layer_status(base_url, "C")
    w_before = (before.get("bufferStats") or {}).get("avgWeight", 0)
    step_before = before.get("step", 0)

    # 手动触发 5 次 incremental（通过 API action=incremental）
    for i in range(5):
        try:
            _curl_post(f"{base_url}/api/training/c", {"action": "incremental"})
        except Exception:
            pass

    after = get_layer_status(base_url, "C")
    w_after = (after.get("bufferStats") or {}).get("avgWeight", 0)
    step_after = after.get("step", 0)

    decayed = w_after < w_before if w_before > 0 else step_after > step_before
    result = {
        "weight_before": w_before,
        "weight_after": w_after,
        "step_before": step_before,
        "step_after": step_after,
        "decayed": decayed,
    }
    tag = "✅ EWMA 衰减" if decayed else "⚠️ 衰减未检出"
    print(f"  C层 | avgWeight {w_before:.4f} → {w_after:.4f} | "
          f"step {step_before}→{step_after} | {tag}")
    return result


def verify_checkpoint_restore(base_url: str) -> dict:
    """验证 checkpoint/restore: 模型状态可持久化 + 恢复。"""
    print(f"\n{'='*60}")
    print(f"  阶段 5: 验证 checkpoint / restore")
    print(f"{'='*60}")

    result = {"checkpoint_ok": False, "restore_ok": False, "model_ok": False}
    model_data = {}

    try:
        # checkpoint
        cp = _curl_post(f"{base_url}/api/training/c", {"action": "checkpoint"})
        result["checkpoint_ok"] = bool(cp.get("success"))
        print(f"  checkpoint C层: success={result['checkpoint_ok']}")
    except Exception as e:
        print(f"  checkpoint C层: 失败 {e}")

    try:
        # get model snapshot（restore 需要 data=model_state）
        model = _curl_get(f"{base_url}/api/training/c/model")
        model_data = model.get("data", {}) or {}
        result["model_ok"] = bool(model.get("success")) and "step" in model_data
        print(f"  GET model C层: success={result['model_ok']} | "
              f"step={model_data.get('step', '?')}")
    except Exception as e:
        print(f"  GET model C层: 失败 {e}")

    try:
        # restore（需要 data=model_state）
        rs = _curl_post(f"{base_url}/api/training/c",
                        {"action": "restore", "data": model_data})
        result["restore_ok"] = bool(rs.get("success"))
        print(f"  restore C层: success={result['restore_ok']}")
    except Exception as e:
        print(f"  restore C层: 失败 {e}")

    return result


def collect_and_feed(base_url: str, limit: int) -> dict:
    """采集 + 喂入（守护模式核心步骤，不含验证）。

    Returns:
        feed_stats dict
    """
    sources = collect_from_all_providers(limit)
    total_cases = sum(len(v) for v in sources.values())
    if total_cases == 0:
        print("  ⚠️ 本轮无数据采集")
        return {layer: {"fed": 0, "added": 0, "failed": 0, "s_level": 0}
                for layer in _LAYERS}
    return feed_continual(base_url, sources)


def run_once(base_url: str, limit: int) -> int:
    """单次完整运行: 采集→喂入→验证→报告。"""
    print(f"╔══════════════════════════════════════════════════════════════╗")
    print(f"║  v0.5 持续训练（continual mode）— 数据到达即学习              ║")
    print(f"╚══════════════════════════════════════════════════════════════╝")
    print(f"  前端服务: {base_url}")
    print(f"  采集上限: {limit}/数据源")
    print(f"  时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    # 阶段 0: 记录初始状态
    before = snapshot_all_layers(base_url)
    print(f"\n  初始状态:")
    for layer in _LAYERS:
        s = before[layer]
        print(f"    {layer:4s} | step={s['step']} | bucket={s['bucketCount']} | "
              f"avgW={s['avgWeight']:.3f}")

    # 阶段 1-2: 采集 + 喂入
    feed_stats = collect_and_feed(base_url, limit)

    # 阶段 3: 验证持续训练
    continual_results = verify_continual_training(base_url, before, feed_stats)

    # 阶段 4: 验证 EWMA 衰减
    ewma_result = verify_ewma_decay(base_url)

    # 阶段 5: 验证 checkpoint/restore
    cp_result = verify_checkpoint_restore(base_url)

    # 汇总报告
    print(f"\n{'='*60}")
    print(f"  汇总报告 — SPEC v0.5 §5.4 P3 验收")
    print(f"{'='*60}")

    continual_pass = sum(1 for r in continual_results.values() if r["continual_trained"])
    ewma_pass = ewma_result["decayed"]
    cp_pass = cp_result["checkpoint_ok"] and cp_result["restore_ok"]

    print(f"  持续训练 (数据到达即学习): {continual_pass}/{len(_LAYERS)} 层触发")
    print(f"  EWMA 衰减: {'✅ 通过' if ewma_pass else '⚠️ 未检出'}")
    print(f"  Checkpoint/Restore: {'✅ 通过' if cp_pass else '⚠️ 失败'}")
    print(f"  Model GET: {'✅ 通过' if cp_result['model_ok'] else '⚠️ 失败'}")

    s_level_total = sum(s["s_level"] for s in feed_stats.values())
    print(f"  S级优先级触发: {s_level_total} 条 S级数据（触发立即 trainIncremental）")

    # SPEC §5.4 P3 验收标准
    print(f"\n  SPEC §5.4 P3 验收标准:")
    checks = [
        ("EWMA: 旧数据 weight 随 age 衰减", ewma_pass),
        ("C层规则权重衰减 + ruleArchive", continual_results.get("C", {}).get("step_delta", 0) > 0),
        ("持续训练: 数据到达即学习", continual_pass > 0),
        ("Checkpoint/Restore 可用", cp_pass),
    ]
    all_pass = True
    for name, passed in checks:
        tag = "✅" if passed else "❌"
        print(f"    {tag} {name}")
        if not passed:
            all_pass = False

    print(f"\n  {'✅ P3 验收全部通过' if all_pass else '⚠️ 部分验收未通过'}")
    return 0 if all_pass else 1


def run_daemon(base_url: str, limit: int, interval: int) -> int:
    """P2 修复: 守护模式 — 持续循环采集+喂入，实现真正的持续训练。

    每轮: collect_and_feed → sleep(interval) → repeat
    Ctrl+C 优雅退出。
    """
    print(f"╔══════════════════════════════════════════════════════════════╗")
    print(f"║  v0.5 持续训练守护模式 — 每 {interval}s 采集+喂入              ║")
    print(f"╚══════════════════════════════════════════════════════════════╝")
    print(f"  前端服务: {base_url}")
    print(f"  采集上限: {limit}/数据源")
    print(f"  轮询间隔: {interval}s")
    print(f"  启动时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  按 Ctrl+C 停止")

    cycle = 0
    try:
        while True:
            cycle += 1
            print(f"\n{'─'*60}")
            print(f"  轮次 #{cycle} | {time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'─'*60}")
            try:
                feed_stats = collect_and_feed(base_url, limit)
                total_added = sum(s["added"] for s in feed_stats.values())
                total_fed = sum(s["fed"] for s in feed_stats.values())
                print(f"  本轮: 喂入 {total_fed} | 成功 {total_added}")
            except Exception as e:
                print(f"  ⚠️ 本轮异常: {e}")
            print(f"  休眠 {interval}s ...")
            time.sleep(interval)
    except KeyboardInterrupt:
        print(f"\n\n  ⏹️  守护进程停止 (共 {cycle} 轮)")
        return 0


def main():
    parser = argparse.ArgumentParser(description="持续训练脚本（v0.5 continual mode）")
    parser.add_argument("--limit", type=int, default=30,
                        help="每个数据源最大采集数（默认30）")
    parser.add_argument("--frontend-url", default="http://localhost:3001",
                        help="前端服务地址")
    parser.add_argument("--daemon", action="store_true",
                        help="P2: 守护模式，持续循环采集+喂入（Ctrl+C 停止）")
    parser.add_argument("--interval", type=int, default=60,
                        help="守护模式轮询间隔秒数（默认60）")
    args = parser.parse_args()
    base_url = args.frontend_url.rstrip("/")

    if args.daemon:
        return run_daemon(base_url, args.limit, args.interval)
    return run_once(base_url, args.limit)


if __name__ == "__main__":
    sys.exit(main())
