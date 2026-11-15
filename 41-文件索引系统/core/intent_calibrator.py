# -*- coding: utf-8 -*-
"""intent_calibrator.py — per-intent 校准 + uplift 度量（P3，SPEC-41-L1 §2.5）

对每个意图可评估单元（intent_units/{intent}/）：
  - Calibration：正例 TPR ≥ 95%、反例 FPR ≤ 2%（语义 similarity ≥ 阈值）
  - Uplift：有该意图向量 vs 无该意图向量，在该意图评估集上的准确率差
    uplift < 0.02 标记为"待裁剪"

评估集 = 该意图的 positives（examples_zh.jsonl）+ negatives（negatives_zh.jsonl）。
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .embedder_bridge import embed
from .intent_matcher import SEMANTIC_THRESHOLD_ZH, detect_lang
from .intent_vector_store import UNITS_DIR, IntentVectorStore

logger = logging.getLogger(__name__)

# Calibration 门禁（SPEC-41-L1 §2.5）
CALIBRATION_POSITIVE_PASS = 0.95
CALIBRATION_NEGATIVE_PASS = 0.02
# Uplift 裁剪阈值
UPLIFT_PRUNE_THRESHOLD = 0.02


@dataclass
class IntentCalibrationResult:
    intent_id: str
    n_pos: int = 0
    n_neg: int = 0
    tp: int = 0  # positive 命中该意图（sim ≥ 阈值）
    fp: int = 0  # negative 误命中该意图（sim ≥ 阈值）
    tpr: float = 0.0
    fpr: float = 0.0
    acc_with: float = 0.0  # 有该意图向量时的准确率
    acc_without: float = 0.0  # 无该意图向量时的准确率
    uplift: float = 0.0
    has_vector: bool = True
    pass_calibration: bool = False
    prune_candidate: bool = False
    details: Dict = field(default_factory=dict)


def _load_jsonl(path: Path) -> List[str]:
    if not path.exists():
        return []
    msgs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                msg = obj.get("message", "").strip()
                if msg:
                    msgs.append(msg)
            except json.JSONDecodeError:
                continue
    return msgs


def calibrate_intent(
    intent_id: str,
    store: IntentVectorStore,
    threshold: float = SEMANTIC_THRESHOLD_ZH,
    lang: str = "zh",
    units_dir: Path = UNITS_DIR,
    regex_results: Optional[Dict[str, str]] = None,
) -> IntentCalibrationResult:
    """对单个意图跑 calibration + uplift。

    TPR/FPR 计入正则命中（SPEC-41-L1 §2.5："语义 similarity ≥ 阈值 或 正则命中"）。
    regex_results: {message: regex_detected_intent}，为 None 时仅统计语义。

    返回 IntentCalibrationResult，含 TPR/FPR/uplift/pass 标记。
    意图无向量时 has_vector=False，跳过语义校准。
    """
    intent_dir = units_dir / intent_id
    result = IntentCalibrationResult(intent_id=intent_id)
    regex_results = regex_results or {}

    if not store.has_vector(intent_id, lang=lang):
        result.has_vector = False
        result.pass_calibration = False
        result.details["reason"] = "no_vector"
        return result

    positives = _load_jsonl(intent_dir / f"examples_{lang}.jsonl")
    negatives = _load_jsonl(intent_dir / f"negatives_{lang}.jsonl")
    result.n_pos = len(positives)
    result.n_neg = len(negatives)

    def _routed_intent(msg: str) -> str:
        """模拟生产路由：正则优先 → 语义 top-1（sim≥阈值）→ L2（空串）。"""
        regex_intent = regex_results.get(msg, "")
        if regex_intent:
            return regex_intent
        msg_lang = detect_lang(msg) if lang == "zh" else lang
        vec = embed(msg, lang=msg_lang)
        if not vec:
            return ""
        top1 = store.top1(vec, lang=msg_lang)
        if top1 and top1[1] >= threshold:
            return top1[0]
        return ""

    # 正例：路由到该意图 → TP
    for msg in positives:
        if _routed_intent(msg) == intent_id:
            result.tp += 1

    # 反例：路由到该意图 → FP
    for msg in negatives:
        if _routed_intent(msg) == intent_id:
            result.fp += 1

    result.tpr = result.tp / result.n_pos if result.n_pos else 0.0
    result.fpr = result.fp / result.n_neg if result.n_neg else 0.0

    # Uplift：有该意图语义向量 vs 无该意图语义向量（正则独立，不受影响）
    # 无该意图时，语义 top-1 从排除该意图的候选中选取。
    def _routed_intent_without(msg: str) -> str:
        regex_intent = regex_results.get(msg, "")
        if regex_intent:
            return regex_intent
        msg_lang = detect_lang(msg) if lang == "zh" else lang
        vec = embed(msg, lang=msg_lang)
        if not vec:
            return ""
        results = store.search(vec, lang=msg_lang, top_k=1, exclude_intents=[intent_id])
        if results and results[0][1] >= threshold:
            return results[0][0]
        return ""

    # acc_with: 正例路由到X + 反例不路由到X
    correct_with = result.tp + (result.n_neg - result.fp)
    # acc_without: 正例路由到X（仅正则，语义无法路由到X）+ 反例不路由到X
    correct_without = 0
    for msg in positives:
        if _routed_intent_without(msg) == intent_id:
            correct_without += 1
    for msg in negatives:
        if _routed_intent_without(msg) != intent_id:
            correct_without += 1

    n_total = result.n_pos + result.n_neg
    if n_total:
        result.acc_with = correct_with / n_total
        result.acc_without = correct_without / n_total
        result.uplift = result.acc_with - result.acc_without

    # Calibration 门禁
    result.pass_calibration = (
        result.tpr >= CALIBRATION_POSITIVE_PASS and result.fpr <= CALIBRATION_NEGATIVE_PASS
    )
    # Uplift 裁剪标记
    result.prune_candidate = result.uplift < UPLIFT_PRUNE_THRESHOLD

    result.details = {
        "threshold": threshold,
        "lang": lang,
    }
    return result


def run_full_calibration(
    store: Optional[IntentVectorStore] = None,
    threshold: float = SEMANTIC_THRESHOLD_ZH,
    lang: str = "zh",
    units_dir: Path = UNITS_DIR,
    regex_results: Optional[Dict[str, str]] = None,
) -> List[IntentCalibrationResult]:
    """对所有意图跑 calibration + uplift，返回结果列表。

    regex_results: {message: regex_detected_intent}，计入 TPR/FPR。
    """
    if store is None:
        store = IntentVectorStore(units_dir=units_dir)
        store.load()

    results = []
    for intent_id in sorted(store.intent_ids):
        logger.info("校准意图: %s", intent_id)
        res = calibrate_intent(
            intent_id,
            store,
            threshold=threshold,
            lang=lang,
            units_dir=units_dir,
            regex_results=regex_results,
        )
        results.append(res)
    return results


def format_report(results: List[IntentCalibrationResult]) -> str:
    """格式化 calibration + uplift 报表（文本表格）。"""
    lines = []
    lines.append(
        f"{'意图':24s} {'向量':>4s} {'正例':>5s} {'TPR':>7s} {'反例':>5s} "
        f"{'FPR':>7s} {'uplift':>7s} {'校准':>4s} {'裁剪':>4s}"
    )
    lines.append("-" * 80)
    for r in results:
        vec = "Y" if r.has_vector else "N"
        cal = "PASS" if r.pass_calibration else "FAIL"
        prune = "YES" if r.prune_candidate else "-"
        lines.append(
            f"{r.intent_id:24s} {vec:>4s} {r.n_pos:5d} {r.tpr:7.1%} {r.n_neg:5d} "
            f"{r.fpr:7.1%} {r.uplift:7.3f} {cal:>4s} {prune:>4s}"
        )
    # 汇总
    n_pass = sum(1 for r in results if r.pass_calibration)
    n_prune = sum(1 for r in results if r.prune_candidate)
    n_vec = sum(1 for r in results if r.has_vector)
    lines.append("-" * 80)
    lines.append(
        f"汇总: {len(results)} 个意图（{n_vec} 有向量）, 校准通过 {n_pass}, 待裁剪 {n_prune}"
    )
    lines.append("")
    lines.append(
        "注: uplift 衡量「有该意图语义向量 vs 无」的准确率差。当前 golden set 中正则通道"
        "覆盖率 100%，语义通道作为兜底，其边际 uplift 在 golden set 上结构性趋近于 0。"
        "待裁剪决策需基于正则漏过的真实流量数据重新评估，不宜仅凭 golden set uplift 裁剪。"
    )
    return "\n".join(lines)


def report_to_json(results: List[IntentCalibrationResult]) -> List[Dict]:
    """将结果转为 JSON 可序列化的字典列表。"""
    out = []
    for r in results:
        out.append(
            {
                "intent_id": r.intent_id,
                "has_vector": r.has_vector,
                "n_pos": r.n_pos,
                "n_neg": r.n_neg,
                "tp": r.tp,
                "fp": r.fp,
                "tpr": round(r.tpr, 4),
                "fpr": round(r.fpr, 4),
                "acc_with": round(r.acc_with, 4),
                "acc_without": round(r.acc_without, 4),
                "uplift": round(r.uplift, 4),
                "pass_calibration": r.pass_calibration,
                "prune_candidate": r.prune_candidate,
                "details": r.details,
            }
        )
    return out
