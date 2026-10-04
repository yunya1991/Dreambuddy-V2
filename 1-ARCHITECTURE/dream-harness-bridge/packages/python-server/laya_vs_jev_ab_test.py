#!/usr/bin/env python3
"""Laya vs Jev A/B 对比测试脚本

评估 Laya（本地开源模型）在我们典型场景下的表现，与 Jev（模拟其官方宣称性能）对比。

评估维度:
    1. 准确率（Accuracy）—— 预测是否与 ground truth 一致
    2. 校准误差（ECE）—— 置信度是否可信（越低越好）
    3. 置信度分布 —— 高/中/低置信度样本占比
    4. 延迟 —— 单次推理耗时

场景覆盖（与 jev_judge 使用场景对齐）:
    - 工作验收（noul: 任务是否完成）
    - 步骤质量（noul: 步骤是否合格）
    - 意图路由（choice: 5 类意图分类）
    - 完成质量（score: 4 级评分）

注意: Jev 部分使用 mock 模拟其官方宣称性能特征（高校准、高准确率），
      重点是评估 Laya 自身的校准质量和准确率。

运行: ENABLE_LAYA_JUDGE=1 python3 laya_vs_jev_ab_test.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import statistics
from typing import Any

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

import laya_judge


# ============================================================
# 测试用例集（含 ground truth）
# ============================================================

# noul 用例: (state, instructions, ground_truth: 0/1)
NOUL_CASES = [
    # --- 工作验收 ---
    ({"task": "实现用户登录", "output": "已完成页面+API+测试"}, "这个任务是否已经完成？", 1),
    ({"task": "实现用户登录", "output": "partial: 只写了页面"}, "这个任务是否已经完成？", 0),
    ({"task": "写一个排序算法", "output": "完成了快排，有测试覆盖"}, "这个任务是否已经完成？", 1),
    ({"task": "写一个排序算法", "output": "刚写了个函数签名"}, "这个任务是否已经完成？", 0),
    ({"task": "重构数据库连接池", "output": "已重构完成，所有测试通过"}, "这个任务是否已经完成？", 1),
    ({"task": "重构数据库连接池", "output": "还在改配置文件"}, "这个任务是否已经完成？", 0),
    # --- 步骤质量 ---
    ({"step": 3, "output": "函数正确返回预期结果"}, "这个步骤的产出是否合格？", 1),
    ({"step": 3, "output": "error: 函数抛出异常"}, "这个步骤的产出是否合格？", 0),
    ({"step": 5, "output": "测试全部通过，无报错"}, "这个步骤的产出是否合格？", 1),
    ({"step": 5, "output": "有3个测试失败"}, "这个步骤的产出是否合格？", 0),
    ({"step": 2, "output": "代码已提交，CI通过"}, "这个步骤的产出是否合格？", 1),
    ({"step": 2, "output": "代码有语法错误"}, "这个步骤的产出是否合格？", 0),
    # --- 额外 noul（意图判断）---
    ("我想做多比特币", "这是一个交易请求吗？", 1),
    ("比特币现在多少钱", "这是一个交易请求吗？", 0),
    ("帮我开仓做空以太坊", "这是一个交易请求吗？", 1),
    ("分析一下当前趋势", "这是一个交易请求吗？", 0),
]

# choice 用例: (state, instructions, criteria_dict, ground_truth_key)
CHOICE_CASES = [
    ({"user_input": "我想做交易，开仓做多比特币"}, "用户意图？",
     {"market_query": "行情", "trend_analysis": "趋势", "trading_decision": "交易", "risk_analysis": "风险", "other": "其他"},
     "trading_decision"),
    ({"user_input": "比特币现在价格多少"}, "用户意图？",
     {"market_query": "行情", "trend_analysis": "趋势", "trading_decision": "交易", "risk_analysis": "风险", "other": "其他"},
     "market_query"),
    ({"user_input": "当前仓位风险如何"}, "用户意图？",
     {"market_query": "行情", "trend_analysis": "趋势", "trading_decision": "交易", "risk_analysis": "风险", "other": "其他"},
     "risk_analysis"),
    ({"user_input": "分析一下比特币的趋势"}, "用户意图？",
     {"market_query": "行情", "trend_analysis": "趋势", "trading_decision": "交易", "risk_analysis": "风险", "other": "其他"},
     "trend_analysis"),
    ({"user_input": "帮我写一个交易策略"}, "用户意图？",
     {"market_query": "行情", "trend_analysis": "趋势", "trading_decision": "交易", "risk_analysis": "风险", "other": "其他"},
     "other"),
    ({"user_input": "以太坊的支撑位是多少"}, "用户意图？",
     {"market_query": "行情", "trend_analysis": "趋势", "trading_decision": "交易", "risk_analysis": "风险", "other": "其他"},
     "market_query"),
    ({"user_input": "我要做空 BTC"}, "用户意图？",
     {"market_query": "行情", "trend_analysis": "趋势", "trading_decision": "交易", "risk_analysis": "风险", "other": "其他"},
     "trading_decision"),
    ({"user_input": "帮我评估一下这个仓位的风险"}, "用户意图？",
     {"market_query": "行情", "trend_analysis": "趋势", "trading_decision": "交易", "risk_analysis": "风险", "other": "其他"},
     "risk_analysis"),
]

# score 用例: (state, instructions, criteria_list, ground_truth_score_index)
SCORE_CASES = [
    ({"task": "实现登录", "output": "完成了所有功能，有完整测试"}, "完成质量如何？",
     ["未完成", "部分完成", "基本完成", "高质量完成"], 3),
    ({"task": "实现登录", "output": "只完成了页面，没有API"}, "完成质量如何？",
     ["未完成", "部分完成", "基本完成", "高质量完成"], 1),
    ({"task": "实现登录", "output": "完成了页面和API，但没有测试"}, "完成质量如何？",
     ["未完成", "部分完成", "基本完成", "高质量完成"], 2),
    ({"task": "实现登录", "output": "什么都没做"}, "完成质量如何？",
     ["未完成", "部分完成", "基本完成", "高质量完成"], 0),
    ({"task": "写排序算法", "output": "快排实现，边界条件都处理了，有测试"}, "完成质量如何？",
     ["未完成", "部分完成", "基本完成", "高质量完成"], 3),
    ({"task": "写排序算法", "output": "写了冒泡排序，能跑但没测试"}, "完成质量如何？",
     ["未完成", "部分完成", "基本完成", "高质量完成"], 2),
]


# ============================================================
# Jev Mock（模拟 Jev 官方宣称的高性能特征）
# ============================================================

def jev_mock_predict(state: Any, questions: dict) -> dict:
    """模拟 Jev 的输出（高准确率、高校准）

    基于输入内容做简单规则判断，模拟 Jev 在这些场景下的表现。
    这不是真实 Jev，只是用于对比基线。
    """
    answers = {}
    state_str = str(state)

    for name, q in questions.items():
        qtype = q.get("type")
        instr = q.get("instructions", "")

        if qtype == "noul":
            # 模拟 Jev 的高准确率判断
            if "完成" in instr:
                gt = 1 if ("完成" in state_str and "partial" not in state_str.lower()
                           and "只" not in state_str and "没" not in state_str) else 0
            elif "合格" in instr or "通过" in instr:
                gt = 1 if ("error" not in state_str.lower() and "失败" not in state_str
                           and "错误" not in state_str) else 0
            elif "交易" in instr:
                gt = 1 if ("做多" in state_str or "做空" in state_str or "开仓" in state_str) else 0
            else:
                gt = 0
            # 模拟 Jev 的高校准：正确时 0.85-0.95，错误时 0.10-0.25
            noul = 0.92 if gt == 1 else 0.15
            answers[name] = {"type": "noul", "noul": noul, "confidence": noul}

        elif qtype == "choice":
            criteria = q.get("criteria", {})
            # 简单关键词匹配
            choice = "other"
            for key, desc in criteria.items():
                if key in state_str or desc in state_str:
                    choice = key
                    break
            # 模拟 Jev 的高校准
            probs = {k: 0.03 for k in criteria}
            probs[choice] = 0.88
            answers[name] = {
                "type": "choice",
                "choice": choice,
                "confidence": 0.85,
                "probabilities": probs,
            }

        elif qtype == "score":
            criteria = q.get("criteria", [])
            n = len(criteria)
            if "高质量" in state_str or "完整测试" in state_str or "都处理" in state_str:
                score_idx = n - 1
            elif "没测试" in state_str or "能跑" in state_str:
                score_idx = n - 2
            elif "只" in state_str or "没有" in state_str:
                score_idx = 1
            else:
                score_idx = 0
            probs = {str(i): 0.05 for i in range(n)}
            probs[str(score_idx)] = 0.85
            answers[name] = {
                "type": "score",
                "score": float(score_idx),
                "legend": {str(i): c for i, c in enumerate(criteria)},
                "probabilities": probs,
                "confidence": 0.82,
            }

    return {"model": "jev-mock", "answers": answers, "usage": {"input_tokens": 200, "output_tokens": 0}}


# ============================================================
# 指标计算
# ============================================================

def compute_ece(confidences: list[float], corrects: list[int], n_bins: int = 10) -> float:
    """计算 Expected Calibration Error (ECE)

    ECE = sum( |bin_acc - bin_conf| * bin_size / N )

    Args:
        confidences: 每个预测的置信度 [0, 1]
        corrects: 每个预测是否正确 (0/1)
        n_bins: 分箱数量

    Returns:
        ECE 值（越低越好，0=完美校准）
    """
    if not confidences:
        return 0.0

    bin_boundaries = [i / n_bins for i in range(n_bins + 1)]
    ece = 0.0
    n = len(confidences)

    for i in range(n_bins):
        lo, hi = bin_boundaries[i], bin_boundaries[i + 1]
        bin_confs = []
        bin_corrects = []
        for conf, corr in zip(confidences, corrects):
            if lo <= conf < hi or (i == n_bins - 1 and conf == 1.0):
                bin_confs.append(conf)
                bin_corrects.append(corr)

        if bin_confs:
            bin_acc = sum(bin_corrects) / len(bin_corrects)
            bin_conf = sum(bin_confs) / len(bin_confs)
            ece += abs(bin_acc - bin_conf) * len(bin_confs) / n

    return ece


def confidence_distribution(confidences: list[float]) -> dict:
    """统计置信度分布"""
    bins = {"0.0-0.3": 0, "0.3-0.5": 0, "0.5-0.7": 0, "0.7-0.9": 0, "0.9-1.0": 0}
    for c in confidences:
        if c < 0.3:
            bins["0.0-0.3"] += 1
        elif c < 0.5:
            bins["0.3-0.5"] += 1
        elif c < 0.7:
            bins["0.5-0.7"] += 1
        elif c < 0.9:
            bins["0.7-0.9"] += 1
        else:
            bins["0.9-1.0"] += 1
    total = len(confidences)
    return {k: {"count": v, "pct": f"{v / total * 100:.1f}%"} for k, v in bins.items()} if total else bins


# ============================================================
# A/B 测试执行
# ============================================================

def run_ab_test() -> dict:
    """运行 A/B 测试，返回对比结果"""
    laya_judge.ENABLE_LAYA_JUDGE = True

    results = {
        "noul": {"laya": {"acc": 0, "ece": 0, "confs": [], "corrects": [], "latencies": []},
                 "jev": {"acc": 0, "ece": 0, "confs": [], "corrects": [], "latencies": []}},
        "choice": {"laya": {"acc": 0, "ece": 0, "confs": [], "corrects": [], "latencies": []},
                   "jev": {"acc": 0, "ece": 0, "confs": [], "corrects": [], "latencies": []}},
        "score": {"laya": {"acc": 0, "ece": 0, "confs": [], "corrects": [], "latencies": []},
                  "jev": {"acc": 0, "ece": 0, "confs": [], "corrects": [], "latencies": []}},
    }

    # --- noul 测试 ---
    print(f"\n[1/3] 运行 noul 测试 ({len(NOUL_CASES)} 用例)...")
    for state, instr, gt in NOUL_CASES:
        questions = {"q": {"type": "noul", "instructions": instr}}

        # Laya
        t0 = time.time()
        r = laya_judge.judge(state, questions)
        dt = time.time() - t0
        if not r["degraded"]:
            noul = r["answers"]["q"]["noul"]
            pred = 1 if noul >= 0.5 else 0
            results["noul"]["laya"]["confs"].append(noul if pred == 1 else 1 - noul)
            results["noul"]["laya"]["corrects"].append(1 if pred == gt else 0)
            results["noul"]["laya"]["latencies"].append(dt)

        # Jev mock
        t0 = time.time()
        r_j = jev_mock_predict(state, questions)
        dt = time.time() - t0
        noul_j = r_j["answers"]["q"]["noul"]
        pred_j = 1 if noul_j >= 0.5 else 0
        results["noul"]["jev"]["confs"].append(noul_j if pred_j == 1 else 1 - noul_j)
        results["noul"]["jev"]["corrects"].append(1 if pred_j == gt else 0)
        results["noul"]["jev"]["latencies"].append(dt)

    # --- choice 测试 ---
    print(f"[2/3] 运行 choice 测试 ({len(CHOICE_CASES)} 用例)...")
    for state, instr, criteria, gt in CHOICE_CASES:
        questions = {"q": {"type": "choice", "instructions": instr, "criteria": criteria}}

        # Laya
        t0 = time.time()
        r = laya_judge.judge(state, questions)
        dt = time.time() - t0
        if not r["degraded"]:
            choice = r["answers"]["q"]["choice"]
            conf = r["answers"]["q"].get("confidence", r["answers"]["q"].get("answer_confidence", 0))
            results["choice"]["laya"]["confs"].append(conf)
            results["choice"]["laya"]["corrects"].append(1 if choice == gt else 0)
            results["choice"]["laya"]["latencies"].append(dt)

        # Jev mock
        t0 = time.time()
        r_j = jev_mock_predict(state, questions)
        dt = time.time() - t0
        choice_j = r_j["answers"]["q"]["choice"]
        conf_j = r_j["answers"]["q"]["confidence"]
        results["choice"]["jev"]["confs"].append(conf_j)
        results["choice"]["jev"]["corrects"].append(1 if choice_j == gt else 0)
        results["choice"]["jev"]["latencies"].append(dt)

    # --- score 测试 ---
    print(f"[3/3] 运行 score 测试 ({len(SCORE_CASES)} 用例)...")
    for state, instr, criteria, gt in SCORE_CASES:
        questions = {"q": {"type": "score", "instructions": instr, "criteria": criteria}}

        # Laya
        t0 = time.time()
        r = laya_judge.judge(state, questions)
        dt = time.time() - t0
        if not r["degraded"]:
            score = r["answers"]["q"]["score"]
            pred_idx = round(score)
            conf = r["answers"]["q"].get("confidence", r["answers"]["q"].get("answer_confidence", 0))
            results["score"]["laya"]["confs"].append(conf)
            results["score"]["laya"]["corrects"].append(1 if pred_idx == gt else 0)
            results["score"]["laya"]["latencies"].append(dt)

        # Jev mock
        t0 = time.time()
        r_j = jev_mock_predict(state, questions)
        dt = time.time() - t0
        score_j = r_j["answers"]["q"]["score"]
        pred_idx_j = round(score_j)
        conf_j = r_j["answers"]["q"]["confidence"]
        results["score"]["jev"]["confs"].append(conf_j)
        results["score"]["jev"]["corrects"].append(1 if pred_idx_j == gt else 0)
        results["score"]["jev"]["latencies"].append(dt)

    # 计算汇总指标
    summary = {}
    for qtype in ["noul", "choice", "score"]:
        summary[qtype] = {}
        for model in ["laya", "jev"]:
            d = results[qtype][model]
            acc = sum(d["corrects"]) / len(d["corrects"]) if d["corrects"] else 0
            ece = compute_ece(d["confs"], d["corrects"])
            avg_lat = statistics.mean(d["latencies"]) if d["latencies"] else 0
            summary[qtype][model] = {
                "accuracy": f"{acc:.3f}",
                "ece": f"{ece:.4f}",
                "avg_latency_ms": f"{avg_lat * 1000:.1f}",
                "confidence_dist": confidence_distribution(d["confs"]),
            }

    return summary


# ============================================================
# 报告输出
# ============================================================

def print_report(summary: dict):
    """打印 A/B 对比报告"""
    print("\n" + "=" * 80)
    print("  Laya vs Jev A/B 对比报告")
    print("=" * 80)

    for qtype in ["noul", "choice", "score"]:
        print(f"\n{'─' * 80}")
        print(f"  【{qtype.upper()}】")
        print(f"{'─' * 80}")
        print(f"  {'指标':<20} {'Laya':<20} {'Jev(mock)':<20}")
        print(f"  {'-'*20} {'-'*20} {'-'*20}")
        print(f"  {'准确率':<20} {summary[qtype]['laya']['accuracy']:<20} {summary[qtype]['jev']['accuracy']:<20}")
        print(f"  {'ECE(校准误差)':<20} {summary[qtype]['laya']['ece']:<20} {summary[qtype]['jev']['ece']:<20}")
        print(f"  {'平均延迟(ms)':<20} {summary[qtype]['laya']['avg_latency_ms']:<20} {summary[qtype]['jev']['avg_latency_ms']:<20}")

        print(f"\n  置信度分布:")
        laya_dist = summary[qtype]["laya"]["confidence_dist"]
        jev_dist = summary[qtype]["jev"]["confidence_dist"]
        for bin_key in laya_dist:
            laya_pct = laya_dist[bin_key].get("pct", "0%")
            jev_pct = jev_dist[bin_key].get("pct", "0%")
            print(f"    {bin_key:<12} Laya: {laya_pct:<10} Jev: {jev_pct}")

    print("\n" + "=" * 80)
    print("  结论建议")
    print("=" * 80)
    print("""
  ECE 解读:
    - < 0.05: 校准优秀，置信度可信
    - 0.05 ~ 0.10: 校准良好
    - 0.10 ~ 0.20: 校准一般，需温度校准
    - > 0.20: 校准较差，置信度不可信

  准确率解读:
    - > 0.85: 可用于非关键决策路径
    - 0.70 ~ 0.85: 需人工审核兜底
    - < 0.70: 不建议用于决策
    """)

    # 保存 JSON 报告
    report_path = os.path.join(SERVER_DIR, "laya_vs_jev_ab_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"  详细报告已保存: {report_path}")


if __name__ == "__main__":
    print("Laya vs Jev A/B 对比测试")
    print(f"模型: {laya_judge.LAYA_MODEL_ID} (subfolder={laya_judge.LAYA_SUBFOLDER}, device={laya_judge.LAYA_DEVICE})")
    print("=" * 80)

    summary = run_ab_test()
    print_report(summary)
