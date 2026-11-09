"""NPE Snorkel 标注函数层测试 — SPEC-D1 §5 D2。

预注册聚合口径：正票>负票且正票≥3 → 1；负票>正票 → -1；其他 → 0。
"""

from data_center.processing.npe_lfs import (
    LABELING_FUNCTIONS,
    aggregate,
    apply_lfs,
    weak_label_sentence,
)

PROP_SENT = "美联储降息50bp将推动BTC和ETH上涨，因为流动性宽松意味着风险资产估值提升。"
COND_SENT = "如果资金费率超过0.1%且持仓量创新高，那么短期回调的概率较大。"
PLAIN_SENT = "今天天气晴朗，大家一起吃了顿饭。"


def test_lf_count():
    """8 个标注函数（预注册清单）。"""
    assert len(LABELING_FUNCTIONS) == 8


def test_causal_sentence_positive():
    """因果命题句 → 弱标签 1。"""
    r = weak_label_sentence(PROP_SENT)
    assert r["label"] == 1
    assert r["needs_arbitration"] is False


def test_conditional_sentence_positive():
    r = weak_label_sentence(COND_SENT)
    assert r["label"] == 1


def test_plain_sentence_negative():
    """无触发词句 → 反例 LF 生效 → -1。"""
    r = weak_label_sentence(PLAIN_SENT)
    assert r["label"] == -1


def test_aggregate_preregistered_rules():
    """聚合口径：正票≥3 且多数 → 1；负票多数 → -1；平票 → 0。"""
    assert aggregate([1, 1, 1, 0, 0, 0, 0, 0]) == 1
    assert aggregate([1, 1, 0, 0, 0, 0, 0, -1]) == 0  # 正票 2 < MIN_POS_VOTES
    assert aggregate([-1, 0, 0, 0, 0, 0, 0, 0]) == -1
    assert aggregate([1, -1, 0, 0, 0, 0, 0, 0]) == 0  # 平票 → 仲裁
    assert aggregate([0] * 8) == 0


def test_apply_lfs_failopen():
    """FAIL-OPEN：异常输入不抛，返回全弃权向量。"""
    assert apply_lfs(None) == [0] * 8
    assert apply_lfs(12345) == [0] * 8


def test_needs_arbitration_flag():
    """有投票但聚合弃权 → 进仲裁队列。"""
    # 只有方向词，无触发词：方向 LF 正票 1，no_trigger 负票 1 → 平票仲裁
    r = weak_label_sentence("价格上涨了。")
    assert r["label"] == 0
    assert r["needs_arbitration"] is True
