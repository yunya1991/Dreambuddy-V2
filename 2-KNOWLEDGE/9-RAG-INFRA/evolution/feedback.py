# -*- coding: utf-8 -*-
"""反馈机制（阶段3·持续进化）：记录用户对检索结果的正负反馈。

正反馈 feedback_weight +0.1，负反馈 feedback_weight -0.1。
权重持久化到 feedback_weights.json，键为 "{source_file}::{heading}"。
后续可用于重排序时的反馈加权。
"""

import json
import sys
from pathlib import Path
from typing import Dict

# === 路径设置 ===
_THIS_DIR = Path(__file__).resolve().parent
_RAG_INFRA_DIR = _THIS_DIR.parent
if str(_RAG_INFRA_DIR) not in sys.path:
    sys.path.insert(0, str(_RAG_INFRA_DIR))

from knowledge_graph.schema import DEFAULT_GRAPH_PATH

# 默认反馈权重文件（存储在 9-RAG-INFRA/ 目录）
DEFAULT_WEIGHTS_FILE = _RAG_INFRA_DIR / "feedback_weights.json"

# 反馈步长
FEEDBACK_STEP = 0.1

# 权重边界
WEIGHT_MIN = -1.0
WEIGHT_MAX = 2.0


def _weights_file(graph_path=None) -> Path:
    """确定反馈权重文件路径。

    若提供 graph_path，权重文件与其同目录（便于测试隔离）；
    否则使用默认路径 9-RAG-INFRA/feedback_weights.json。
    """
    if graph_path:
        return Path(graph_path).parent / "feedback_weights.json"
    return DEFAULT_WEIGHTS_FILE


def _load_weights(weights_file: Path) -> Dict[str, float]:
    """加载反馈权重，文件不存在返回空字典。"""
    if not weights_file.exists():
        return {}
    try:
        return json.loads(weights_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_weights(weights_file: Path, weights: Dict[str, float]) -> None:
    """保存反馈权重到 JSON 文件。"""
    weights_file.parent.mkdir(parents=True, exist_ok=True)
    weights_file.write_text(
        json.dumps(weights, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def record_feedback(source_file: str, heading: str, is_positive: bool,
                    graph_path: Path = None) -> Dict:
    """记录用户对检索结果的反馈，更新反馈权重。

    Args:
        source_file: 检索结果来源文件路径。
        heading: 检索结果标题。
        is_positive: True 为正反馈（+0.1），False 为负反馈（-0.1）。
        graph_path: 图谱路径，其父目录用于存放 feedback_weights.json
                    （便于测试隔离），默认使用 9-RAG-INFRA/ 目录。

    Returns:
        dict 含 source_file / heading / new_weight。
    """
    wfile = _weights_file(graph_path)
    weights = _load_weights(wfile)

    key = f"{source_file}::{heading}"
    current = weights.get(key, 0.0)
    delta = FEEDBACK_STEP if is_positive else -FEEDBACK_STEP
    new_weight = round(current + delta, 4)

    # 边界约束
    new_weight = max(WEIGHT_MIN, min(WEIGHT_MAX, new_weight))

    weights[key] = new_weight
    _save_weights(wfile, weights)

    return {
        "source_file": source_file,
        "heading": heading,
        "new_weight": new_weight,
    }


if __name__ == "__main__":
    import sys

    sf = sys.argv[1] if len(sys.argv) > 1 else "1-TRADING/BCRM推理引擎.md"
    hd = sys.argv[2] if len(sys.argv) > 2 else "核心架构"
    pos = sys.argv[3] != "neg" if len(sys.argv) > 3 else True
    result = record_feedback(sf, hd, is_positive=pos)
    print(json.dumps(result, ensure_ascii=False))
