# -*- coding: utf-8 -*-
"""T6：L1 embedder 健康断言（SPEC-41-L1-新闻意图检索 §9）。

为什么需要：embedder 静默退化（换成 bge-small 512 维、或模型未加载）时，
语义通道会「不报错但永不命中」，是最难发现的假绿。本组断言把三件事钉死：
  1. 可用性 —— 常驻服务 ready，或本地依赖可用（`is_inproc_available()`）
  2. 维度   —— 中文向量必须是 bge-base 的 768 维（512 维即已回退 bge-small）
  3. 判别力 —— 同义改写的余弦显著高于无关文本（防「向量塌缩成常数」）

环境无模型/无服务时用 skip 而非 fail，避免在无 GPU/无网络的机器上误报。
"""

import importlib.util
import math
import os
import urllib.request

import pytest

_BRIDGE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "..",
    "41-文件索引系统",
    "core",
    "embedder_bridge.py",
)

PARAPHRASE = ("最近有什么新闻", "今天有啥新消息")
UNRELATED = ("最近有什么新闻", "美联储加息对股市有什么影响")
SIM_FLOOR = 0.60  # 实测同义对 0.6745，留 0.07 余量
SIM_GAP_FLOOR = 0.25  # 实测同义-无关差 0.34，留 0.09 余量
EXPECTED_DIM = 768  # bge-base-zh-v1.5；512 即已静默回退 bge-small


def _load_bridge():
    spec = importlib.util.spec_from_file_location("l1_embedder_bridge_health", _BRIDGE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BRIDGE = _load_bridge()


def _deps_installed():
    try:
        import sentence_transformers  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def _service_ready(server=None):
    url = (server or BRIDGE.EMBED_SERVER or "").rstrip("/")
    if not url:
        return False
    try:
        with urllib.request.urlopen(url + "/health", timeout=2) as resp:
            import json

            return bool(json.loads(resp.read() or b"{}").get("ready"))
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(scope="module")
def vectors():
    texts = [PARAPHRASE[0], PARAPHRASE[1], UNRELATED[1]]
    vecs = BRIDGE.embed_batch(texts, "zh")
    if not vecs:
        pytest.skip("embedder 不可用：既无常驻服务也无本地依赖，本机跳过 T6")
    return vecs


def test_embedder_reachable():
    """可用性：常驻服务 ready 或本地 in-process 可用，二者至少其一。"""
    if _service_ready():
        return
    if not _deps_installed():
        pytest.skip("无 sentence-transformers 且常驻服务未就绪")
    assert BRIDGE.is_inproc_available() is True


def test_vector_dim_is_bge_base(vectors):
    """维度守卫：768 维才说明用的是 bge-base，512 维即已静默退化。"""
    assert all(len(v) == EXPECTED_DIM for v in vectors), [len(v) for v in vectors]


def _cos(a, b):
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return sum(x * y for x, y in zip(a, b, strict=False)) / (na * nb)


def test_similarity_floor_and_gap(vectors):
    """判别力：同义改写余弦须高于下限，且显著高于无关文本。"""
    para = _cos(vectors[0], vectors[1])
    unrel = _cos(vectors[0], vectors[2])
    assert para >= SIM_FLOOR, f"同义余弦 {para:.4f} < 下限 {SIM_FLOOR}"
    assert para - unrel >= SIM_GAP_FLOOR, f"同义-无关差 {para - unrel:.4f} < 下限 {SIM_GAP_FLOOR}"
