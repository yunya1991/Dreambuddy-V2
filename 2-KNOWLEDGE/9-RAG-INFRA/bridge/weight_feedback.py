# -*- coding: utf-8 -*-
"""权重反哺模块：将 verify 结果转化为 RAG 检索结果的 boost 因子。

设计原则：
- 独立 JSON 持久化，不侵入 ChromaDB / 知识图谱 / reranker；
- boost 因子范围 [BOOST_MIN, BOOST_MAX]，verify(success=True) 乘以
  BOOST_SUCCESS_FACTOR（上限 BOOST_MAX），verify(success=False) 乘以
  BOOST_FAILURE_FACTOR（下限 BOOST_MIN）；
- apply_boost_to_results 将 boost 叠加到 final_score（相乘）并重新降序排序；
- 全程 FAIL-OPEN：读取/写入失败返回中性值（1.0），不阻塞检索。

知识单元键：`source_file::heading`，与 reranker 去重键一致。
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional

# === 默认参数 ===
BOOST_MIN = 0.5
BOOST_MAX = 2.0
BOOST_SUCCESS_FACTOR = 1.1
BOOST_FAILURE_FACTOR = 0.9
DEFAULT_BOOST = 1.0

# 原生生产默认路径（9-RAG-INFRA/bridge/weight_feedback.json）
_PROD_WEIGHT_PATH = Path(__file__).resolve().parent / "weight_feedback.json"


def resolve_default_weight_path() -> Path:
    """解析默认 weight_feedback.json 路径。

    优先级：环境变量 TEST_BRIDGE_WEIGHT_PATH > 生产默认。
    测试隔离方案：pytest 用 monkeypatch 设置该 env 即可写入 tmp 目录，
    避免污染/误读生产 weight_feedback.json。
    """
    env = os.environ.get("TEST_BRIDGE_WEIGHT_PATH")
    if env:
        return Path(env)
    return _PROD_WEIGHT_PATH


def _key(source_file: str, heading: str) -> str:
    """构造知识单元键：source_file::heading。"""
    return f"{source_file}::{heading}"


def _load(weight_path: Optional[Path] = None) -> Dict[str, float]:
    """加载权重反馈表。FAIL-OPEN：失败返回空字典。"""
    p = Path(weight_path) if weight_path else resolve_default_weight_path()
    try:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {k: float(v) for k, v in data.items()}
    except Exception:
        pass
    return {}


def _save(feedback: Dict[str, float], weight_path: Optional[Path] = None) -> None:
    """持久化权重反馈表。FAIL-OPEN：写入失败静默忽略。"""
    p = Path(weight_path) if weight_path else resolve_default_weight_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(feedback, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    except Exception:
        pass


def get_boost(source_file: str, heading: str,
              weight_path: Optional[Path] = None) -> float:
    """获取知识单元的 boost 因子，默认 1.0。

    Args:
        source_file: 结果来源文件路径。
        heading: 结果标题/锚点。
        weight_path: 权重反馈文件路径，默认 bridge/weight_feedback.json。

    Returns:
        boost 因子，范围 [BOOST_MIN, BOOST_MAX]，未记录时返回 DEFAULT_BOOST。
    """
    feedback = _load(weight_path)
    return feedback.get(_key(source_file, heading), DEFAULT_BOOST)


def update_boost(source_file: str, heading: str, success: bool,
                 weight_path: Optional[Path] = None) -> float:
    """根据 verify 结果更新 boost 因子并持久化。

    success=True → boost *= BOOST_SUCCESS_FACTOR（上限 BOOST_MAX）；
    success=False → boost *= BOOST_FAILURE_FACTOR（下限 BOOST_MIN）。

    Args:
        source_file: 结果来源文件路径。
        heading: 结果标题/锚点。
        success: verify 是否成功。
        weight_path: 权重反馈文件路径。

    Returns:
        更新后的 boost 因子。
    """
    feedback = _load(weight_path)
    k = _key(source_file, heading)
    current = feedback.get(k, DEFAULT_BOOST)
    factor = BOOST_SUCCESS_FACTOR if success else BOOST_FAILURE_FACTOR
    new_boost = current * factor
    # 上下限保护
    new_boost = max(BOOST_MIN, min(BOOST_MAX, new_boost))
    # 钳位到默认值附近时避免浮点漂移（4位小数内等于1.0则取1.0）
    if abs(new_boost - DEFAULT_BOOST) < 1e-4:
        new_boost = DEFAULT_BOOST
    feedback[k] = round(new_boost, 4)
    _save(feedback, weight_path)
    return feedback[k]


def apply_boost_to_results(results: List[Dict],
                           weight_path: Optional[Path] = None) -> List[Dict]:
    """将 boost 因子叠加到检索结果的 final_score 并重新降序排序。

    对每个结果，若其 source_file/heading 对应的 boost != 1.0，
    则 final_score *= boost，并记录 feedback_boost 到 rerank_signals。
    最后按调整后的 final_score 重新排序。

    Args:
        results: hybrid_search / rerank 返回的结果列表。
        weight_path: 权重反馈文件路径。

    Returns:
        调整后的结果列表（降序），全程 FAIL-OPEN。
    """
    if not results:
        return []
    try:
        feedback = _load(weight_path)
    except Exception:
        feedback = {}

    for r in results:
        k = _key(r.get("source_file", ""), r.get("heading", ""))
        boost = feedback.get(k, DEFAULT_BOOST)
        if abs(boost - DEFAULT_BOOST) > 1e-4:
            original = r.get("final_score", r.get("score", 0))
            r["final_score"] = round(original * boost, 4)
            signals = r.get("rerank_signals", {})
            signals["feedback_boost"] = round(boost, 4)
            r["rerank_signals"] = signals
        else:
            # 未命中反馈也记录中性 boost 便于审计
            r.setdefault("rerank_signals", {})["feedback_boost"] = DEFAULT_BOOST

    results.sort(key=lambda x: x.get("final_score", 0), reverse=True)
    return results


def reset(weight_path: Optional[Path] = None) -> None:
    """清空权重反馈表（测试辅助）。"""
    p = Path(weight_path) if weight_path else resolve_default_weight_path()
    try:
        if p.exists():
            p.unlink()
    except Exception:
        pass
