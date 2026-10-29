# -*- coding: utf-8 -*-
"""P3.4 A 层: OKR 验收器 — C 层执行结果回传 A 层做节点级验收。

依据: SPEC-v1.2-SACG-orchestration.md §2.2（执行结果回传 A 层验收）。
借鉴:
  - dream-acceptance-verify SKILL: 三态判定 + 证据必录 + FAIL-OPEN 但必记录 + 红旗清单
  - CI Quality Gate: 显式 pass/fail 规则集 + warning-only 中间档（degraded）
  - 金融对账: 逐节点双向核对（非总额汇总）+ 差异分类（result_missing / extras / action_rejected）

粒度区分: Reflector（CDriveV3Router）管执行内过程决策（单步），本模块管节点级结果验收。
约束: 禁新阈值（不引入 0.7/3/0.3 之外的数值判定）、全程 FAIL-OPEN。

verdict 三态: pass / degraded / fail
  - c_action: action∉FAIL_ACTIONS 且无 error → pass；REDO 或带 error → degraded；
              EARLY_TERMINATE/FAILED 或 result 缺失 → fail
  - evidence_backed / gap_closed: 首版不做证据比对，action 正常 → degraded(evidence_pending)
整体: any fail → fail；else any degraded 或 extras → degraded；else pass；空节点 → degraded
"""
from __future__ import annotations
import json
import os

from typing import Any, Dict, List, Optional

from core.okr_nodes import VERIFY_C_ACTION

VERDICT_PASS = "pass"
VERDICT_DEGRADED = "degraded"
VERDICT_FAIL = "fail"

# C 层决策动作 → 验收硬失败（REDO 不在此列：要求重做=结果待定，记 degraded）
FAIL_ACTIONS = frozenset({"EARLY_TERMINATE", "FAILED", "NODE_FAILED"})
REDO_ACTION = "REDO"

# 验收原因码（证据必录，禁止靠感觉）
REASON_ACTION_OK = "action_ok"
REASON_ACTION_REDO = "action_redo"
REASON_ACTION_REJECTED = "action_rejected"
REASON_ERROR_RECORDED = "error_recorded"
REASON_RESULT_MISSING = "result_missing"
REASON_EVIDENCE_PENDING = "evidence_pending"

# ============================================================
# 金融调研探索四维验收（与代码开发验收分流，其余域不拓展）
# 维度: practice(实践=广义认知系统实践成果) / theory(理论支持=金融理论)
#       / backtest(回测验证) / data_source(数据真实，不能造数据)
# 证据载体: result.detail.finance_evidence = {practice, theory, backtest, data_source}
# 规则: 数据造假标记 → fail(data_fabricated，硬门)；数据无来源 → degraded(data_unverified)；
#       practice/theory/backtest 缺失 → degraded({dim}_pending，首版规则化)
# 方案A 维度细分（外部调研结论: Bailey & López de Prado 样本外纪律 +
#   FinGround 原子声明可溯源；规则化、禁新阈值）:
#   backtest:    含样本外/walk-forward 表述 → pass；仅样本内 → degraded(oos_pending)
#   data_source: 含糊来源（"公开数据"等，不可核验）→ degraded(source_vague)
# ============================================================
FINANCE_DOMAIN = "finance_research"
FINANCE_DIMENSIONS = ("practice", "theory", "backtest", "data_source")
FABRICATED_SOURCES = frozenset({"fabricated", "synthetic", "mock"})
# 样本外纪律标记（Bailey & López de Prado: 样本外是唯一算数的意见）
OOS_MARKERS = ("样本外", "walk-forward", "walk_forward", "walkforward",
               "out-of-sample", "out_of_sample", "滚动回测", "前向验证")
# 含糊来源（不可核验；精确匹配避免误伤 "OKX 公开数据导出" 这类具体来源）
VAGUE_SOURCES = frozenset({
    "网络", "互联网", "网上", "网上资料", "网络公开数据",
    "公开数据", "公开资料", "公开信息", "公开渠道",
    "public data", "online", "internet", "web",
})
REASON_DATA_FABRICATED = "data_fabricated"
REASON_DATA_UNVERIFIED = "data_unverified"
REASON_OOS_PENDING = "oos_pending"
REASON_SOURCE_VAGUE = "source_vague"


def _evaluate_finance_node(entry: Dict[str, Any],
                           result: Dict[str, Any]) -> Dict[str, Any]:
    """金融 domain 节点四维验收。动作硬失败优先；无证据载体 FAIL-OPEN 全维 degraded。"""
    detail = result.get("detail")
    evidence = (detail.get("finance_evidence")
                if isinstance(detail, dict) else None)
    evidence = evidence if isinstance(evidence, dict) else {}

    dimensions: Dict[str, str] = {}
    reasons: List[str] = []
    for dim in FINANCE_DIMENSIONS:
        value = evidence.get(dim)
        text = str(value).strip() if value else ""
        low = text.lower()
        if dim == "data_source":
            if low in FABRICATED_SOURCES:
                dimensions[dim] = VERDICT_FAIL
                reasons.append(REASON_DATA_FABRICATED)
            elif not text:
                dimensions[dim] = VERDICT_DEGRADED
                reasons.append(REASON_DATA_UNVERIFIED)
            elif low in VAGUE_SOURCES:
                dimensions[dim] = VERDICT_DEGRADED
                reasons.append(REASON_SOURCE_VAGUE)
            else:
                dimensions[dim] = VERDICT_PASS
        elif dim == "backtest":
            if not text:
                dimensions[dim] = VERDICT_DEGRADED
                reasons.append(f"{dim}_pending")
            elif any(m in low for m in OOS_MARKERS):
                dimensions[dim] = VERDICT_PASS
            else:
                dimensions[dim] = VERDICT_DEGRADED
                reasons.append(REASON_OOS_PENDING)
        elif text:
            dimensions[dim] = VERDICT_PASS
        else:
            dimensions[dim] = VERDICT_DEGRADED
            reasons.append(f"{dim}_pending")

    if VERDICT_FAIL in dimensions.values():
        verdict = VERDICT_FAIL
    elif VERDICT_DEGRADED in dimensions.values():
        verdict = VERDICT_DEGRADED
    else:
        verdict = VERDICT_PASS
        reasons.append(REASON_ACTION_OK)
    entry.update(verdict=verdict, reasons=reasons, dimensions=dimensions)
    return entry


def _evaluate_node(node: Dict[str, Any],
                   result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """单节点验收：按 verify 类型分派规则，产出 verdict + reason（证据）。"""
    node_id = str(node.get("node_id") or "N?")
    verify = str(node.get("verify") or VERIFY_C_ACTION)
    action = str((result or {}).get("action") or "")
    entry: Dict[str, Any] = {
        "node_id": node_id,
        "verify": verify,
        "action": action or None,
    }

    if result is None:
        entry.update(verdict=VERDICT_FAIL, reason=REASON_RESULT_MISSING)
        return entry
    if action in FAIL_ACTIONS:
        entry.update(verdict=VERDICT_FAIL, reason=REASON_ACTION_REJECTED)
        return entry
    if action == REDO_ACTION:
        entry.update(verdict=VERDICT_DEGRADED, reason=REASON_ACTION_REDO)
        return entry
    if result.get("error"):
        entry.update(verdict=VERDICT_DEGRADED, reason=REASON_ERROR_RECORDED)
        return entry
    if str(node.get("domain") or "") == FINANCE_DOMAIN:
        return _evaluate_finance_node(entry, result)
    if verify == VERIFY_C_ACTION:
        entry.update(verdict=VERDICT_PASS, reason=REASON_ACTION_OK)
    else:
        # evidence_backed / gap_closed 首版规则化：不做证据比对，标记待验
        entry.update(verdict=VERDICT_DEGRADED, reason=REASON_EVIDENCE_PENDING)
    return entry


def evaluate_nodes(nodes: Optional[List[Dict[str, Any]]],
                   node_results: Optional[List[Dict[str, Any]]]
                   ) -> Dict[str, Any]:
    """C 层结果回传验收：逐节点核对（对账式），汇总整体 verdict。

    FAIL-OPEN: 任何非法输入返回 degraded 骨架，绝不抛错。
    """
    try:
        nodes = list(nodes or [])
        node_results = list(node_results or [])
        by_id = {str(r.get("node_id")): r for r in node_results
                 if isinstance(r, dict) and r.get("node_id")}

        verdicts: List[Dict[str, Any]] = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("node_id") or "N?")
            verdicts.append(_evaluate_node(node, by_id.get(node_id)))

        node_ids = {str(n.get("node_id")) for n in nodes if isinstance(n, dict)}
        extras = [nid for nid in by_id if nid not in node_ids]

        counts = {
            VERDICT_PASS: sum(1 for v in verdicts if v["verdict"] == VERDICT_PASS),
            VERDICT_DEGRADED: sum(1 for v in verdicts if v["verdict"] == VERDICT_DEGRADED),
            VERDICT_FAIL: sum(1 for v in verdicts if v["verdict"] == VERDICT_FAIL),
        }
        red_flags = [v["node_id"] for v in verdicts if v["verdict"] == VERDICT_FAIL]

        if counts[VERDICT_FAIL] > 0:
            overall = VERDICT_FAIL
        elif counts[VERDICT_DEGRADED] > 0 or extras or not verdicts:
            overall = VERDICT_DEGRADED
        else:
            overall = VERDICT_PASS

        # P1.5 埋点（spec §9.1 三层架构域采集点）：验收收尾写入案例库，FAIL-OPEN

        try:

            from datetime import datetime as _dt

            _results = verdicts if isinstance(verdicts, list) else []

            _case = {

                "ts": _dt.now().isoformat(timespec="seconds"),

                "schema_version": "v2",

                "case_type": "arch_layer",

                "payload": {

                    "node_count": len(nodes) if nodes else 0,

                    "result_count": len(_results),

                    "overall": overall,
                    "counts": counts,

                },

            }

            _store = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "l1_case_store.jsonl")

            with open(_store, "a", encoding="utf-8") as _f:

                _f.write(json.dumps(_case, ensure_ascii=False) + "\n")

        except Exception:

            pass

        return {
            "verdict": overall,
            "node_verdicts": verdicts,
            "red_flags": red_flags,
            "counts": counts,
            "extras": extras,
        }
    except Exception as e:  # FAIL-OPEN 兜底
        return {
            "verdict": VERDICT_DEGRADED,
            "node_verdicts": [],
            "red_flags": [],
            "counts": {VERDICT_PASS: 0, VERDICT_DEGRADED: 0, VERDICT_FAIL: 0},
            "extras": [],
            "error": f"{type(e).__name__}:{e}",
        }
