"""
L2 Strategy Gene Schema Interface（MVP Spec §3.2 & §3.4 Public API）
4 接口：
  1. load_gene_library(root: Path)       → 校验+加载，bad genes 写日志不抛
  2. calculate_ess(combination_meta)     → ESS 4:4:2 clamp [0,1]（蓝图附录 C R-1 唯一权重）
  3. top_combinations_by_ess(library, min_sample=30) → 降序+N过滤返回 list
  4. search_genes_by_category(root, cat) → 读 gene_index.json 倒排，sorted list[gene_id]
FAIL-OPEN：任何 schema 校验异常/IO 异常 → skip + log，不 crash（FO-4）。
"""
from __future__ import annotations

import json
import logging
import math
import sys
import traceback
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from dreambuddy_evolution.weights import WEIGHTS  # 4 权重组（硬约束唯一权威源）

logger = logging.getLogger(__name__)


# ==================================================================================================
# 1. load_gene_library
# ==================================================================================================
def load_gene_library(root: str | Path) -> dict[str, Any]:
    """
    Load all conditions, actions, combinations from gene root (2-交易记忆单元).
    Returns dict:
      conditions=[{gene}], actions=[{gene}], combinations=[{combo}],
      counts={cond_valid, cond_invalid, act_valid, act_invalid, comb_valid, comb_invalid},
      bad_genes_log=Path（写入路径）
    FO-4：任何坏基因写 bad_genes.log，不 raise。
    """
    root_p = Path(root)
    cond_dir = root_p / "strategy_genes" / "conditions"
    act_dir  = root_p / "strategy_genes" / "actions"
    comb_dir = root_p / "strategy_combinations"
    schemas_dir = root_p / "schemas"

    import jsonschema  # 延迟 import（CI 需要 pip install jsonschema）

    def _schema(name: str) -> dict:
        return json.loads((schemas_dir / f"{name}.json").read_text(encoding="utf-8"))

    try:
        SCH_COND = _schema("condition")
        SCH_ACT  = _schema("action")
        SCH_COMB = _schema("combination")
    except Exception as e:  # pragma: no cover
        logger.warning("[FO-4] schemas load fail → return empty library: %s", e)
        return {"conditions": [], "actions": [], "combinations": [],
                "counts": {k: 0 for k in ("cond_valid", "cond_invalid",
                                          "act_valid", "act_invalid",
                                          "comb_valid", "comb_invalid")},
                "bad_genes_log": None,
                "root": str(root_p)}

    bad_log_path = root_p / "strategy_genes" / "bad_genes.log"
    counts = {"cond_valid": 0, "cond_invalid": 0,
              "act_valid":  0, "act_invalid":  0,
              "comb_valid": 0, "comb_invalid": 0}
    conditions: list[dict] = []
    actions: list[dict] = []
    combinations: list[dict] = []
    seen_ids: dict[str, str] = {}  # gene_id → file_path（TR-SG-04 唯一性：同 id 多次出现直接 FO-4 skip）

    def _iter_and_validate(directory: Path, schema: dict, count_key_valid: str,
                           count_key_invalid: str, id_key: str = "gene_id") -> list[dict]:
        result = []
        if not directory.exists():
            logger.warning("[FO-4] directory missing: %s — skip (return [])", directory)
            return result
        for file in sorted(directory.glob("*.json")):
            try:
                obj = json.loads(file.read_text(encoding="utf-8"))
                jsonschema.validate(obj, schema)
                gid = str(obj.get(id_key, ""))
                # TR-SG-04 唯一性：重复 id 直接记 bad_genes.log 跳过（不接受重复写）
                if gid in seen_ids and seen_ids[gid] != str(file):
                    raise ValueError(f"duplicate {id_key}={gid!r} already exists at {seen_ids[gid]}")
                if gid:
                    seen_ids[gid] = str(file)
                # TR-SG-09: parameters range low <= high 断言（每个参数都要过）
                for pname, pdef in obj.get("parameters", {}).items():
                    rng = pdef.get("range", {})
                    lo, hi = rng.get("low"), rng.get("high")
                    if lo is None or hi is None:
                        continue
                    try:
                        lo_f, hi_f = float(lo), float(hi)
                        if lo_f > hi_f:
                            raise ValueError(f"parameters.{pname} range low={lo!r} > high={hi!r}")
                    except (ValueError, TypeError):
                        # 非数值用字典序
                        if str(lo) > str(hi):
                            raise ValueError(f"parameters.{pname} range low={lo!r} > high={hi!r} (lexicographic)")
                result.append(obj)
                counts[count_key_valid] += 1
            except Exception as exc:  # noqa: BLE001 — FO-4 所有坏基因一律记日志并跳过
                counts[count_key_invalid] += 1
                try:
                    with bad_log_path.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps({
                            "file": str(file.name),
                            "kind": count_key_invalid,
                            "error": f"{type(exc).__name__}: {exc!s:.300s}",
                            "traceback": traceback.format_exc(limit=2),
                        }, ensure_ascii=False) + "\n")
                except Exception as log_err:  # pragma: no cover — 连日志都写不进来直接 stderr
                    logger.error("Cannot write bad_genes.log (%s) during FO-4: %s", bad_log_path, log_err)
        return result

    conditions   = _iter_and_validate(cond_dir, SCH_COND, "cond_valid", "cond_invalid")
    actions      = _iter_and_validate(act_dir,  SCH_ACT,  "act_valid",  "act_invalid")
    combinations = _iter_and_validate(comb_dir / "library.json", SCH_COMB, "comb_valid", "comb_invalid") if False else []
    # combinations 是一个文件 library.json（数组），不是每个文件 1 个。单独循环加载：
    comb_file = comb_dir / "library.json"
    if comb_file.exists():
        try:
            comb_list = json.loads(comb_file.read_text(encoding="utf-8"))
            if not isinstance(comb_list, list):
                comb_list = [comb_list]
        except Exception as exc:
            comb_list = []
            with bad_log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"file": "library.json", "kind": "comb_invalid",
                                     "error": f"{type(exc).__name__}: {exc!s:.300s}"}, ensure_ascii=False) + "\n")
            counts["comb_invalid"] += 1
        for c in comb_list:
            cid = str(c.get("combo_id", "")) if isinstance(c, dict) else ""
            try:
                if not isinstance(c, dict):
                    raise ValueError("combination entry not a dict")
                jsonschema.validate(c, SCH_COMB)
                if cid in seen_ids and seen_ids[cid] != str(comb_file):
                    raise ValueError(f"duplicate combo_id={cid!r}")
                if cid:
                    seen_ids[cid] = str(comb_file)
                # n_samples/ess 填充默认（缺的话用 meta.H/S/N 计算）
                if "ess" not in c or not isinstance(c["ess"], (int, float)):
                    c["ess"] = calculate_ess(c)
                if "n_samples" not in c or not isinstance(c["n_samples"], int):
                    c["n_samples"] = int(c.get("meta", {}).get("N", 0) or 0)
                combinations.append(c)
                counts["comb_valid"] += 1
            except Exception as exc:  # noqa: BLE001
                counts["comb_invalid"] += 1
                try:
                    with bad_log_path.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps({
                            "file": "library.json",
                            "combo_id": cid,
                            "kind": "comb_invalid",
                            "error": f"{type(exc).__name__}: {exc!s:.300s}",
                        }, ensure_ascii=False) + "\n")
                except Exception:  # pragma: no cover
                    pass
    return {
        "root": str(root_p),
        "conditions": conditions,
        "actions": actions,
        "combinations": combinations,
        "counts": counts,
        "bad_genes_log": bad_log_path,
    }


# ==================================================================================================
# 2. calculate_ess（蓝图附录 C：H:S = 平权各 0.4；N 辅助 0.2 × sqrt(N/500) 上限；clamp [0,1]）
# ==================================================================================================
def calculate_ess(combination_meta: dict[str, Any]) -> float:
    """
    meta 可以包含以下字段（兼容各种位置）：
      - meta.H / meta.S / meta.N   （library.json.meta 域）
      - H / S / N                  （顶层域）
      - ess / n_samples 已存在     → 直接 return（兼容预计算）
    clamp 公式严格对齐 default_weights.WEIGHTS["ESS"]（TR-SG-05 边界断言使用）
    """
    if isinstance(combination_meta, dict) and "ess" in combination_meta:
        ess = combination_meta["ess"]
        if isinstance(ess, (int, float)):
            return max(0.0, min(1.0, float(ess)))
    meta = combination_meta.get("meta", {}) if isinstance(combination_meta, dict) else {}
    if not isinstance(meta, dict):
        meta = {}
    H = float(combination_meta.get("H", meta.get("H", 0.0)) or 0.0)
    S = float(combination_meta.get("S", meta.get("S", 0.0)) or 0.0)
    N = float(combination_meta.get("N", combination_meta.get("n_samples", meta.get("N", 0))) or 0)
    W = WEIGHTS["ESS"]
    H_w = float(W["H"]); S_w = float(W["S"])
    N_w = float(W["N_ratio"]); N_s = float(W["N_scale"])
    n_term = math.sqrt(max(N, 0.0) / max(N_s, 1.0)) if N_s > 0 else 0.0
    n_clamped = 0.0 if math.isnan(n_term) else min(1.0, max(0.0, n_term))
    raw = H_w * H + S_w * S + N_w * n_clamped
    return max(0.0, min(1.0, float(raw)))  # clamp [0,1]（TR-SG-05 全 1/全 0 边界）


# ==================================================================================================
# 3. top_combinations_by_ess → 按 ESS 降序，N ≥ min_sample
# ==================================================================================================
def top_combinations_by_ess(library: dict[str, Any], min_sample: int = 30) -> list[dict]:
    """
    library 是 load_gene_library() 的返回值（包含 combinations 列表）。
    返回: list of dict（按 ess 严格降序；每个 dict 至少含 combo_id, ess, n_samples, condition_ids, action_ids）
    """
    out: list[dict] = []
    for c in library.get("combinations", []) or []:
        n = int(c.get("n_samples", 0) or c.get("meta", {}).get("N", 0) or 0)
        if n < min_sample:
            continue
        ess = calculate_ess(c)
        out.append({
            "combo_id":     str(c.get("combo_id", "")),
            "ess":          ess,
            "n_samples":    n,
            "condition_ids": list(c.get("condition_ids", []) or []),
            "action_ids":   list(c.get("action_ids", []) or []),
            "strategy_type": (c.get("meta", {}) or {}).get("strategy_type"),
            "ess_raw_source": c.get("ess"),
        })
    out.sort(key=lambda x: x["ess"], reverse=True)  # 严格降序（TR-SG-07 断言顺序）
    return out


# ==================================================================================================
# 4. search_genes_by_category → 读 gene_index.json 倒排索引
# ==================================================================================================
def search_genes_by_category(root: str | Path, category: str) -> list[str]:
    """
    返回: category 下所有 condition gene_id 的 sorted 列表（空列表表示该 cat 无 gene 或 category 不存在）。
    TR-SG-10 零漏零误判：倒排 100% 由 gene_index.json 权威提供。
    """
    root_p = Path(root)
    idx_path = root_p / "strategy_genes" / "gene_index.json"
    cat_norm = str(category).strip()
    if not idx_path.exists():
        return []
    try:
        payload = json.loads(idx_path.read_text(encoding="utf-8"))
        index = payload.get("index", {})
        if cat_norm not in index:
            return []
        return sorted({str(g) for g in index[cat_norm]})  # sorted unique（TR-SG-10 确定性顺序）
    except Exception as e:  # FO-4 不 crash
        logger.warning("[FO-4] gene_index.json parse fail (%s): %s", idx_path, e)
        return []
