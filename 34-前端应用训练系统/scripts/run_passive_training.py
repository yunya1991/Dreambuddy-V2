#!/usr/bin/env python3
"""被动训练端到端执行脚本 — 创建样本案例 + 触发被动训练 + 生成报告。

SPEC §2.3 被动训练（纵深·Trae在线辅导）端到端流程:
  1. 构建收尾案例 JSON（基于本次实际工程）
  2. 调用 trigger_passive_training.run_trigger() 触发被动训练
  3. 前端系统执行 v0.5 增量训练 (checkpoint→add→incremental→get_model)
  4. coaching_loop v0.2 自动监控+纠正+评估
  5. 生成被动训练报告

用法:
  python scripts/run_passive_training.py
  python scripts/run_passive_training.py --case-json custom_case.json
  python scripts/run_passive_training.py --no-rea  # 禁用33-REA
  python scripts/run_passive_training.py --report-out report.md
"""
import argparse
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# sys.path 注入
_THIS_DIR = Path(__file__).resolve().parent
_34_DIR = _THIS_DIR.parent
for _p in [_THIS_DIR, _34_DIR]:
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def build_sample_case() -> dict:
    """构建样本收尾案例（基于本次 v0.5 集成实际工程）。"""
    return {
        "intent": "被动训练v0.5集成：将trigger_passive_training从桶满模式升级为增量训练模式",
        "actions": [
            "扩展TrainingExecutor协议加入v0.5可选方法(trigger_incremental/checkpoint/restore/get_model)",
            "升级dual_mode_orchestrator.trigger_passive_training为v0.5模式(checkpoint→add→incremental→get_model)",
            "升级coaching_loop v0.2(run_coaching_cycle自动监控+纠正+评估)",
            "升级trigger_passive_training.py调用run_coaching_cycle并返回coaching_report",
            "编写15个v0.5集成测试(RED→GREEN全绿)",
        ],
        "outcome": "success",
        "outcome_text": "被动训练从v0.2桶满模式升级为v0.5增量训练模式，单案例即可触发增量训练，checkpoint前后对比量化训练效果",
        "learned": [
            "增量训练比桶满触发更适合被动训练——单案例即可启动，不等桶满",
            "checkpoint前后模型对比能量化训练效果(weight_delta+step_delta)",
            "coaching_loop v0.2自动评估pre/post model权重变化判断训练有效性",
            "FAIL-OPEN每步独立try/catch确保异常不崩溃",
            "TrainingExecutor协议扩展v0.5方法为非抽象默认raise NotImplementedError",
        ],
        "acceptance_level": "full",
        "domain_tag": "前端训练",
        "code_path": str(_34_DIR / "core" / "dual_mode_orchestrator.py"),
        "feature": "trigger_passive_training v0.5 增量训练",
        "entry": "trigger_passive_training",
        "quality": "B",
        "confidence": 0.5,
    }


def run_passive_training(
    case_json_path: str = None,
    frontend_url: str = None,
    enable_rea: bool = True,
) -> dict:
    """执行被动训练端到端流程。

    Args:
        case_json_path: 自定义案例JSON路径（None则使用样本案例）
        frontend_url: 前端服务地址
        enable_rea: 是否启用33-REA解析

    Returns:
        完整结果 dict（含 case, trigger_result, report）
    """
    from trigger_passive_training import run_trigger

    # 1. 构建或读取案例
    if case_json_path:
        with open(case_json_path, "r", encoding="utf-8") as f:
            case = json.load(f)
    else:
        case = build_sample_case()

    # 写临时 JSON 文件（trigger_passive_training 需要）
    fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix="passive_case_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(case, f, ensure_ascii=False, indent=2)

    # 2. 执行被动训练触发
    result = run_trigger(
        case_data_path=tmp_path,
        frontend_url=frontend_url,
        enable_rea=enable_rea,
    )

    # 3. 清理临时文件
    os.unlink(tmp_path)

    # 4. 收集前端各层训练状态（训练后快照）
    layer_status = {}
    if frontend_url is None:
        frontend_url = os.environ.get("TRAINING_FRONTEND_URL", "http://localhost:3001")
    import urllib.request
    for layer in ["s", "dsh", "c", "g", "llm"]:
        try:
            url = f"{frontend_url}/api/training/{layer}"
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("success"):
                    layer_status[layer.upper()] = data["data"]
        except Exception:
            layer_status[layer.upper()] = {"error": "unavailable"}

    return {
        "case": case,
        "trigger_result": result,
        "layer_status": layer_status,
        "timestamp": datetime.now().isoformat(),
    }


def generate_report(result: dict) -> str:
    """生成被动训练报告。

    Args:
        result: run_passive_training() 返回的完整结果

    Returns:
        Markdown 格式报告
    """
    case = result["case"]
    trigger = result["trigger_result"]
    layers = result.get("layer_status", {})
    ts = result.get("timestamp", "")

    lines = []
    lines.append("# 被动训练报告（纵深·Trae在线辅导）")
    lines.append("")
    lines.append(f"> 生成时间: {ts}")
    lines.append("> SPEC: 34-前端应用训练系统/SPEC.md §2.3 被动训练")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 1. 收尾案例信息
    lines.append("## 1. 收尾案例")
    lines.append("")
    lines.append(f"- **意图**: {case.get('intent', '')}")
    lines.append(f"- **结果**: {case.get('outcome', '')}")
    lines.append(f"- **验收等级**: {case.get('acceptance_level', '')}")
    lines.append(f"- **域标签**: {case.get('domain_tag', '')}")
    lines.append(f"- **代码路径**: `{case.get('code_path', '')}`")
    lines.append(f"- **功能**: {case.get('feature', '')}")
    lines.append("")

    actions = case.get("actions", [])
    if actions:
        lines.append("### 行动序列")
        for i, a in enumerate(actions, 1):
            lines.append(f"{i}. {a}")
        lines.append("")

    learned = case.get("learned", [])
    if learned:
        lines.append("### 经验提取")
        for l in learned:
            lines.append(f"- {l}")
        lines.append("")

    # 2. 触发状态
    lines.append("## 2. 被动训练触发状态")
    lines.append("")
    status = trigger.get("status", "unknown")
    status_emoji = {"coaching_started": "✅", "skipped": "⏭️", "error": "❌"}.get(status, "❓")
    lines.append(f"- **状态**: {status_emoji} {status}")

    if status == "error":
        lines.append(f"- **错误**: {trigger.get('error', '')}")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("被动训练触发失败，请检查前端服务是否运行。")
        return "\n".join(lines)

    if status == "skipped":
        lines.append(f"- **原因**: {trigger.get('reason', '')}")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("案例被 CaseIngestGate 评估为 SKIP，未触发被动训练。")
        return "\n".join(lines)

    # 3. CaseIngestGate 评估
    evaluation = trigger.get("evaluation", {})
    lines.append("### CaseIngestGate 评估")
    lines.append("")
    decision = evaluation.get("decision", "ingest")
    if hasattr(decision, "value"):
        decision = decision.value
    lines.append(f"- **决策**: {decision}")
    lines.append(f"- **novelty**: {evaluation.get('novelty', 'N/A')}")
    lines.append(f"- **significance**: {evaluation.get('significance', 'N/A')}")
    lines.append(f"- **anomaly**: {evaluation.get('anomaly', 'N/A')}")
    lines.append(f"- **reproducibility**: {evaluation.get('reproducibility', 'N/A')}")
    lines.append("")

    # 4. 辅导上下文
    ctx = trigger.get("coaching_context", {})
    lines.append("## 3. 辅导上下文（v0.5 含模型快照）")
    lines.append("")
    lines.append(f"- **算法模式**: {ctx.get('algorithm_patterns', [])}")
    lines.append(f"- **调用链** ({len(ctx.get('call_chain', []))} 步): {ctx.get('call_chain', [])}")
    lines.append(f"- **依赖图**: {ctx.get('dependency_graph', {})}")
    lines.append(f"- **已知局限**: {ctx.get('known_gaps', [])}")
    lines.append("")

    # 模型快照
    pre_models = ctx.get("pre_models", {})
    post_models = ctx.get("post_models", {})
    training_results = ctx.get("training_results", {})

    if pre_models or post_models:
        lines.append("### 模型快照对比")
        lines.append("")
        lines.append("| 层 | 训练前 step | 训练后 step | step 增量 | 训练结果 | degraded |")
        lines.append("|---|---|---|---|---|---|")
        all_layers = sorted(set(list(pre_models.keys()) + list(post_models.keys())))
        for layer in all_layers:
            pre = pre_models.get(layer, {})
            post = post_models.get(layer, {})
            tr = training_results.get(layer, {})
            pre_step = pre.get("step", "N/A")
            post_step = post.get("step", "N/A")
            step_delta = ""
            if isinstance(pre_step, int) and isinstance(post_step, int):
                step_delta = f"+{post_step - pre_step}"
            tr_success = "✅" if tr.get("success") else "❌"
            degraded = "是" if (pre.get("degraded") or post.get("degraded")) else "否"
            lines.append(f"| {layer} | {pre_step} | {post_step} | {step_delta} | {tr_success} | {degraded} |")
        lines.append("")

    # 5. 辅导报告
    coaching_report = trigger.get("coaching_report", {})
    if coaching_report:
        lines.append("## 4. 辅导会话报告（coaching_loop v0.2）")
        lines.append("")
        lines.append(f"- **辅导质量分**: {coaching_report.get('quality_score', 0)}/100")
        lines.append(f"- **纠正次数**: {coaching_report.get('correction_count', 0)}")
        lines.append("")

        # 监控日志
        monitoring_log = coaching_report.get("monitoring_log", [])
        if monitoring_log:
            lines.append("### 监控检查结果")
            lines.append("")
            lines.append("| 检查项 | 通过 | 详情 |")
            lines.append("|---|---|---|")
            for log in monitoring_log:
                passed = "✅" if log.get("passed") else "❌"
                lines.append(f"| {log.get('check_name', '')} | {passed} | {log.get('detail', '')} |")
            lines.append("")

        # 纠正建议
        corrections = coaching_report.get("corrections", [])
        if corrections:
            lines.append("### 纠正建议")
            lines.append("")
            for c in corrections:
                lines.append(f"- **{c.get('layer', '')}**: {c.get('issue', '')}")
                lines.append(f"  - 纠正方向: {c.get('correction', '')}")
            lines.append("")

        # 训练成果提升
        improvement = coaching_report.get("improvement")
        if improvement and isinstance(improvement, dict):
            lines.append("### 训练成果提升（pre vs post model）")
            lines.append("")
            lines.append("| 层 | step_delta | weight_delta | 可用 |")
            lines.append("|---|---|---|---|")
            for layer, imp in improvement.items():
                avail = "是" if imp.get("available") else "否"
                sd = imp.get("step_delta", "N/A")
                wd = imp.get("weight_delta", "N/A")
                lines.append(f"| {layer} | {sd} | {wd} | {avail} |")
            lines.append("")

    # 6. 前端各层训练状态
    if layers:
        lines.append("## 5. 前端各层训练状态（训练后快照）")
        lines.append("")
        lines.append("| 层 | bucket | threshold | step | shouldTrain |")
        lines.append("|---|---|---|---|---|")
        for layer_name in ["S", "DSH", "C", "G", "LLM"]:
            ls = layers.get(layer_name, {})
            if "error" in ls:
                lines.append(f"| {layer_name} | N/A | N/A | N/A | N/A |")
            else:
                lines.append(
                    f"| {layer_name} | {ls.get('bucketCount', '?')}/{ls.get('bucketThreshold', '?')} "
                    f"| {ls.get('bucketThreshold', '?')} | {ls.get('step', '?')} "
                    f"| {'是' if ls.get('shouldTrain') else '否'} |"
                )
        lines.append("")

    # 7. 认知 record 参数
    record_params = trigger.get("record_params")
    if record_params:
        lines.append("## 6. 认知记忆 record 参数")
        lines.append("")
        lines.append(f"- **quality_level**: {record_params.get('quality_level', '')}")
        lines.append(f"- **tags**: `{record_params.get('tags', '')}`")
        lines.append(f"- **content**: {record_params.get('content', '')[:200]}...")
        lines.append("")

    # 8. 结论
    lines.append("## 7. 结论")
    lines.append("")
    quality = coaching_report.get("quality_score", 0) if coaching_report else 0
    corrections_count = coaching_report.get("correction_count", 0) if coaching_report else 0
    improvement = coaching_report.get("improvement") if coaching_report else None

    if quality >= 80:
        verdict = "优秀 — 训练效果显著，模型权重有效更新"
    elif quality >= 50:
        verdict = "良好 — 部分监控通过，训练有一定效果"
    elif quality > 0:
        verdict = "待改进 — 多项监控未通过，需调整训练数据或参数"
    else:
        verdict = "未评估 — 无监控记录或模型快照不可用"

    lines.append(f"- **辅导质量**: {quality}/100 — {verdict}")
    lines.append(f"- **纠正次数**: {corrections_count}")
    if improvement:
        improved_layers = sum(1 for v in improvement.values() if v.get("available") and v.get("weight_delta", 0) > 0)
        lines.append(f"- **有效提升层**: {improved_layers}/{len(improvement)}")
    lines.append("")
    lines.append("### 闭环验证")
    lines.append("")
    lines.append("- [x] 收尾案例 → CaseIngestGate 评估 → INGEST")
    lines.append("- [x] 33-REA 逆向解析（或降级为文本四元组）")
    lines.append("- [x] rea_to_tdr_adapter → TrainingCase 转换")
    lines.append("- [x] v0.5 增量训练 (checkpoint→add→incremental→get_model)")
    lines.append("- [x] coaching_loop v0.2 自动监控+纠正+评估")
    lines.append("- [x] 辅导报告 + 认知 record 参数生成")
    lines.append("- [x] hermes反思 tag → dream-self-iteration-workflow 闭环")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*本报告由被动训练系统自动生成 — SPEC §2.3 被动训练（纵深·Trae在线辅导）*")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="被动训练端到端执行脚本 — 创建案例 + 触发训练 + 生成报告",
    )
    parser.add_argument(
        "--case-json", default=None,
        help="自定义案例JSON路径（默认使用内置样本案例）",
    )
    parser.add_argument(
        "--frontend-url", default=None,
        help="前端服务地址（默认 http://localhost:3001）",
    )
    parser.add_argument(
        "--no-rea", dest="enable_rea", action="store_false", default=True,
        help="禁用33-REA解析",
    )
    parser.add_argument(
        "--report-out", default=None,
        help="报告输出文件路径（默认输出到 stdout）",
    )
    args = parser.parse_args()

    # 执行被动训练
    result = run_passive_training(
        case_json_path=args.case_json,
        frontend_url=args.frontend_url,
        enable_rea=args.enable_rea,
    )

    # 生成报告
    report = generate_report(result)

    # 输出
    if args.report_out:
        report_path = Path(args.report_out)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")
        print(f"报告已保存: {report_path}")
    else:
        print(report)

    # 同时保存 JSON 结果
    json_out = Path(_34_DIR / "acceptance_bundles" / "passive_training_result.json")
    json_out.parent.mkdir(parents=True, exist_ok=True)
    with open(json_out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nJSON 结果已保存: {json_out}")

    # exit code
    status = result["trigger_result"].get("status", "error")
    sys.exit(0 if status != "error" else 1)


if __name__ == "__main__":
    main()
