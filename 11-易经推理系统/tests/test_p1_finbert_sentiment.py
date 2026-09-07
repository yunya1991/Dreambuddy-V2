"""P1 FinBERT 双引擎升级 S1 Sentiment + 时间衰减 RED→GREEN 测试套件。

Spec: docs/superpowers/specs/2026-08-29-p1-finbert-sentiment-upgrade-spec.md

8 TC:
  TC-1 接口不变铁律（返回 Dict 四键齐全）
  TC-2 正面新闻（中英文）FinBERT 返回 score>0.1
  TC-3 负面新闻（中英文）FinBERT 返回 score<-0.1
  TC-4 中性新闻 |score| ≤ 0.1
  TC-5 transformers 不存在时 fallback 旧规则不抛错
  TC-6 USE_FINBERT=0 强制走旧实现（引擎位全None）
  TC-7 time_decay_weight 黄金值四点
  TC-8 集成 news_list 5条 梯度age → D1≠0 且 ≠ 等权值（衰减生效证据）

夹具默认 monkeypatch.setenv("USE_FINBERT", "0") 防止 TC 真实触发模型下载；
TC-2/3/4 显式 unset USE_FINBERT + monkeypatch fake pipeline 验证引擎路由代码。
"""
from __future__ import annotations

import builtins
import math
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest.mock import MagicMock

import pytest

THIS_DIR = Path(__file__).resolve().parent
_REPO = THIS_DIR.parent  # 11-易经推理系统
_COMPUTER_ROOT = _REPO / "scripts" / "memory_l4"
_FUND_ROOT = _REPO.parent / "9-基本面分析"
_FUND_ENGINES = _FUND_ROOT / "engines"

for _p in [str(_COMPUTER_ROOT), str(_REPO), str(_FUND_ENGINES), str(_FUND_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ---------------------------------------------------------------------------
# 夹具：默认 USE_FINBERT=0，阻止 TC 意外下载模型
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _default_no_finbert_download(monkeypatch):
    """TC 夹具默认环境变量：禁止 FinBERT 引擎位初始化。
    需要引擎的 TC（TC-2/3/4）手动 monkeypatch.delenv("USE_FINBERT")。
    """
    monkeypatch.setenv("USE_FINBERT", "0")
    yield


# ---------------------------------------------------------------------------
# 导入辅助：动态加载 sentiment_engine 模块（每次 importlib.reload 保证 TC 独立）
# ---------------------------------------------------------------------------
def _reload_sentiment():
    """强制重新加载 engines.sentiment_engine（因为 env/monkeypatch 只在 import 时读一次）。"""
    import importlib
    import engines.sentiment_engine as se_mod  # type: ignore
    importlib.reload(se_mod)
    return se_mod


def _reload_computer():
    import importlib
    import five_domain_feature_computer as fc_mod  # type: ignore
    importlib.reload(fc_mod)
    return fc_mod


# ===========================================================================
# TC-1 接口不变铁律
# ===========================================================================
def test_TC1_interface_signature_unchanged(monkeypatch):
    """SentimentEngine.analyze_text 返回 Dict，且必须包含 score/sentiment/categories/matches 四键。
    测试 USE_FINBERT=0 场景（旧规则分支）。
    """
    monkeypatch.setenv("USE_FINBERT", "0")
    se_mod = _reload_sentiment()
    engine = se_mod.SentimentEngine()

    r_empty = engine.analyze_text("")
    _assert_dict_shape(r_empty, allow_score_zero=True)

    r_neutral = engine.analyze_text("Bitcoin spot trading volume remains stable in Q3.")
    _assert_dict_shape(r_neutral)
    assert -1.0 <= r_neutral["score"] <= 1.0


def _assert_dict_shape(r: Any, allow_score_zero: bool = False) -> None:
    assert isinstance(r, dict), f"返回必须是 dict，实际 {type(r).__name__}"
    for k in ("score", "sentiment", "categories", "matches"):
        assert k in r, f"返回 dict 缺少必须键 '{k}'"
    assert isinstance(r["score"], (int, float)), "score 必须是数字"
    assert isinstance(r["sentiment"], str), "sentiment 必须是 str"
    assert r["sentiment"] in ("positive", "neutral", "negative"), \
        f"sentiment 必须是三值之一，实际 {r['sentiment']!r}"
    assert isinstance(r["categories"], list), "categories 必须是 list"
    assert isinstance(r["matches"], dict), "matches 必须是 dict"
    # matches 必须有 positive/negative 两 int 键
    for mk in ("positive", "negative"):
        assert mk in r["matches"], f"matches 缺少键 '{mk}'"
        assert isinstance(r["matches"][mk], int)
    # score 范围
    assert -1.0 <= float(r["score"]) <= 1.0, f"score={r['score']} 超出[-1,1]"


# ===========================================================================
# TC-2 正面新闻 score > 0.1
# ===========================================================================
def test_TC2_positive_news_eng(monkeypatch):
    """Fake 双引擎返回 positive 标签 → score > 0.1 + sentiment == positive。
    中英文各跑 1 条。
    """
    # 解除 USE_FINBERT=0，但不在 real pipeline 上跑：monkeypatch pipeline 返回 fake
    monkeypatch.delenv("USE_FINBERT", raising=False)
    se_mod = _reload_sentiment()
    engine = se_mod.SentimentEngine()

    # 强制 eng_ready = True + 注入 fake _en_pipe / _zh_pipe（不真实 load 模型）
    engine._eng_ready = True
    engine._en_pipe = _make_fake_pipe([{"label": "positive", "score": 0.95}])
    engine._zh_pipe = _make_fake_pipe([{"label": "利好", "score": 0.90}])

    en_txt = "BlackRock IBIT spot bitcoin ETF inflow surges to $1B, highest in 2026."
    r_en = engine.analyze_text(en_txt)
    _assert_dict_shape(r_en)
    assert r_en["score"] > 0.1, f"英文正面 score={r_en['score']} 应 >0.1"
    assert r_en["sentiment"] == "positive"

    zh_txt = "贝莱德比特币现货ETF单日净流入10亿美元创历史新高，机构看涨情绪强烈。"
    r_zh = engine.analyze_text(zh_txt)
    _assert_dict_shape(r_zh)
    assert r_zh["score"] > 0.1, f"中文正面 score={r_zh['score']} 应 >0.1"
    assert r_zh["sentiment"] == "positive"


# ===========================================================================
# TC-3 负面新闻 score < -0.1
# ===========================================================================
def test_TC3_negative_news_eng(monkeypatch):
    """Fake 双引擎返回 negative 标签 → score < -0.1 + sentiment == negative。"""
    monkeypatch.delenv("USE_FINBERT", raising=False)
    se_mod = _reload_sentiment()
    engine = se_mod.SentimentEngine()
    engine._eng_ready = True
    engine._en_pipe = _make_fake_pipe([{"label": "negative", "score": 0.92}])
    engine._zh_pipe = _make_fake_pipe([{"label": "利空", "score": 0.93}])

    en_txt = "SEC sues Binance for unregistered securities offering, BTC liquidates $200M."
    r_en = engine.analyze_text(en_txt)
    _assert_dict_shape(r_en)
    assert r_en["score"] < -0.1, f"英文负面 score={r_en['score']} 应 <-0.1"
    assert r_en["sentiment"] == "negative"

    zh_txt = "黑客盗取1亿美元USDT，恐慌抛售导致短时清算超2亿美元。"
    r_zh = engine.analyze_text(zh_txt)
    _assert_dict_shape(r_zh)
    assert r_zh["score"] < -0.1, f"中文负面 score={r_zh['score']} 应 <-0.1"
    assert r_zh["sentiment"] == "negative"


# ===========================================================================
# TC-4 中性新闻 |score| ≤ 0.1
# ===========================================================================
def test_TC4_neutral_news_eng(monkeypatch):
    """Fake 双引擎返回 neutral 标签 → |score| ≤ 0.1 + sentiment == neutral。"""
    monkeypatch.delenv("USE_FINBERT", raising=False)
    se_mod = _reload_sentiment()
    engine = se_mod.SentimentEngine()
    engine._eng_ready = True
    engine._en_pipe = _make_fake_pipe([{"label": "neutral", "score": 0.99}])
    engine._zh_pipe = _make_fake_pipe([{"label": "中性", "score": 0.98}])

    en_txt = "Fed holds rates steady as CPI matches consensus forecast 2.1%."
    r_en = engine.analyze_text(en_txt)
    _assert_dict_shape(r_en)
    assert abs(r_en["score"]) <= 0.1, f"英文中性 score={r_en['score']} 应 |s|≤0.1"
    assert r_en["sentiment"] == "neutral"

    zh_txt = "美联储按兵不动，CPI符合市场预期2.1%。"
    r_zh = engine.analyze_text(zh_txt)
    _assert_dict_shape(r_zh)
    assert abs(r_zh["score"]) <= 0.1, f"中文中性 score={r_zh['score']} 应 |s|≤0.1"
    assert r_zh["sentiment"] == "neutral"


def _make_fake_pipe(return_value: List[Dict[str, Any]]) -> MagicMock:
    """构造 fake pipeline：pipeline(text) 返回固定 List[Dict]（transformers pipeline 标准签名）。"""
    m = MagicMock(name="fake_pipeline")
    m.return_value = list(return_value)
    return m


# ===========================================================================
# TC-5 transformers 不存在时 fallback 旧实现不抛错
# ===========================================================================
def test_TC5_transformers_import_error_fallback(monkeypatch):
    """拦截 builtins.__import__，当模块名是 'transformers' 或其子模块时抛 ImportError。
    验证：构造 SentimentEngine + 调用 analyze_text 不抛 Exception；返回合法 Dict（旧规则）。
    """
    # 允许 USE_FINBERT=1（否则 TC 变测 USE_FINBERT=0 分支，不是 import 失败分支）
    monkeypatch.setenv("USE_FINBERT", "1")

    real_import = builtins.__import__

    def _wrapped_import(name, *args, **kwargs):
        if name == "transformers" or name.startswith("transformers."):
            raise ImportError("No module named 'transformers' (TC-5 fake block)")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _wrapped_import)

    se_mod = _reload_sentiment()
    engine = se_mod.SentimentEngine()

    # eng_ready 必须 False（因为 transformers 被拦，import 失败）
    assert getattr(engine, "_eng_ready", True) is False, \
        "import 失败时 _eng_ready 应为 False"

    texts = [
        "BTC 突破 80000 创新高 机构增持",
        "SEC 起诉 抛售 爆仓",
        "美联储按兵不动 符合预期",
        "",
    ]
    for t in texts:
        r = engine.analyze_text(t)
        _assert_dict_shape(r, allow_score_zero=True)
        assert -1.0 <= float(r["score"]) <= 1.0


# ===========================================================================
# TC-6 USE_FINBERT=0 强制走旧实现
# ===========================================================================
def test_TC6_use_finbert_env_zero_forces_old(monkeypatch):
    """USE_FINBERT=0 时，即使 transformers 可用，_eng_ready 也是 False；
    同时正面关键词能触发旧规则（非 0 中性常量）。
    """
    monkeypatch.setenv("USE_FINBERT", "0")
    se_mod = _reload_sentiment()
    engine = se_mod.SentimentEngine()

    # _eng_ready=False，管道全None
    assert engine._eng_ready is False, "USE_FINBERT=0 必须 _eng_ready=False"
    assert getattr(engine, "_en_pipe", None) is None, "USE_FINBERT=0 时 _en_pipe 必须 None"
    assert getattr(engine, "_zh_pipe", None) is None, "USE_FINBERT=0 时 _zh_pipe 必须 None"

    # 正面关键词（旧规则命中：机构/流入/创新高/ETF批准...
    # "ETF 批准 创新高 机构 流入" → POSITIVE_KEYWORDS 多次命中 → score > 0.1
    r_pos = engine.analyze_text("贝莱德 ETF 批准 比特币 创新高 机构增持 资金流入")
    _assert_dict_shape(r_pos)
    assert r_pos["score"] > 0.1, f"旧规则正面应得分>0.1，实际 {r_pos['score']}"
    assert r_pos["sentiment"] == "positive"

    # 负面关键词
    r_neg = engine.analyze_text("SEC 起诉 抛售 爆仓 黑客 被黑 禁令")
    _assert_dict_shape(r_neg)
    assert r_neg["score"] < -0.1, f"旧规则负面应得分<-0.1，实际 {r_neg['score']}"
    assert r_neg["sentiment"] == "negative"


# ===========================================================================
# TC-7 time_decay_weight 黄金值四点
# ===========================================================================
def test_TC7_time_decay_golden_values(monkeypatch):
    """四点：age=0→1.0；age=24→0.3679；age=72→0.0498；负数age→1.0。tol=1e-3。"""
    monkeypatch.setenv("USE_FINBERT", "0")
    se_mod = _reload_sentiment()
    tdw = se_mod.time_decay_weight

    def _close(a: float, b: float, tol: float = 1e-3) -> bool:
        return abs(a - b) <= tol

    # age=0
    assert _close(tdw(0.0), 1.0), f"age=0 → {tdw(0)}, 期待 1.0"
    # age=24h
    assert _close(tdw(24.0), math.exp(-1)), f"age=24 → {tdw(24)}, 期待 {math.exp(-1):.6f}"
    assert _close(tdw(24.0), 0.3679, 1e-3)
    # age=72h
    assert _close(tdw(72.0), math.exp(-3)), f"age=72 → {tdw(72)}, 期待 {math.exp(-3):.6f}"
    assert _close(tdw(72.0), 0.0498, 1e-3)
    # 负数 age → 当做0处理 → 1.0
    assert _close(tdw(-5.0), 1.0), f"负数age={tdw(-5)} → 期待 1.0"
    assert _close(tdw(-0.0), 1.0)


# ===========================================================================
# TC-8 集成：5条混合news_list 梯度age → D1≠0且≠等权值（衰减生效）
# ===========================================================================
def test_TC8_integration_d1_decay_effect(monkeypatch, tmp_path):
    """全链路打通：构造 5 条 news_list 梯度 age；分别跑「衰减版」vs「强制等权版」。
    断言：D1 ≠ 0，|D1| ≤ 0.10，衰减版 ≠ 等权版。
    """
    # 配置：禁止 FinBERT，SentimentEngine 走旧规则（避免下载模型）
    monkeypatch.setenv("USE_FINBERT", "0")

    # 时间锚点：钉死 time.time() = BASELINE_T（epoch 秒），相对现在是固定值
    #   选 2026-08-29 12:00:00 UTC = 1788081600
    BASELINE_T = 1_788_081_600.0

    import time as _t_mod
    monkeypatch.setattr(_t_mod, "time", lambda: BASELINE_T)

    # Helper 根据小时偏移造 timestamp_ms
    def _ts_ms(hours_ago: float) -> int:
        return int((BASELINE_T - hours_ago * 3600.0) * 1000)

    # 5 条夹具新闻：titles 按旧规则关键词会返回 偏+/偏-/中/偏-/偏+ 五档
    NEWS_FIXTURE: List[Dict[str, Any]] = [
        # 0h age（最新）：强正
        {"source": "test", "category": "news", "sub_category": "t",
         "title": "BTC ETF 批准 创新高 机构增持", "content": "贝莱德IBIT 单日净流入10亿美元",
         "timestamp_ms": _ts_ms(0)},
        # 3h age：强负
        {"source": "test", "category": "news", "sub_category": "t",
         "title": "SEC 起诉 抛售 爆仓", "content": "黑客盗取1亿美元USDT",
         "timestamp_ms": _ts_ms(3)},
        # 24h age：中性（无任何关键词 → score=0）
        {"source": "test", "category": "news", "sub_category": "t",
         "title": "美联储按兵不动 符合市场预期", "content": "CPI 2.1% 符合预期",
         "timestamp_ms": _ts_ms(24)},
        # 48h age：强负
        {"source": "test", "category": "news", "sub_category": "t",
         "title": "监管禁令 抛售 清算 爆仓", "content": "某交易所暂停提款",
         "timestamp_ms": _ts_ms(48)},
        # 72h age：强正
        {"source": "test", "category": "news", "sub_category": "t",
         "title": "ETF 通过 创新高 机构增持 资金流入", "content": "富达FBTC 获批准",
         "timestamp_ms": _ts_ms(72)},
    ]

    # 加载 computer + 强制 news_list 返回夹具值（monkeypatch 替换 _fetch_news_72h_limit200）
    fc_mod = _reload_computer()

    # 构造 computer：enable=True（默认），通过 monkeypatch 环境变量注入开关
    # （FiveDomainFeatureComputer.__init__ 签名只有 enable: bool=True）
    monkeypatch.setenv("FUND_7ENGINES_BOOST", "1")
    monkeypatch.setenv("ODAILY_ENGINE_BOOST", "0")
    # 强制重新加载，新 env 生效
    fc_mod = _reload_computer()
    computer = fc_mod.FiveDomainFeatureComputer(enable=True)
    # 生产红线显式 False（保险）
    computer.enable_fundamental_7engines_production_injection = False
    # 注入 news 夹具
    monkeypatch.setattr(computer, "_fetch_news_72h_limit200", lambda: list(NEWS_FIXTURE))

    # 1) 跑 D1 计算（代码里自带 time.time = BASELINE_T → _now_ms = BASELINE_T*1000）
    d1_decay = computer._fd_S_dao_boost(None)
    assert isinstance(d1_decay, float), f"D1 返回不是 float: {type(d1_decay).__name__}"
    assert d1_decay != 0.0, f"D1=0，5条夹具混合应该有非零值"
    assert abs(d1_decay) <= 0.10, f"D1={d1_decay} 超出 clamp 限制 ±0.10"

    # 2) 强制等权：把 se_mod.time_decay_weight 替换为 lambda *_: 1.0 → 再跑一次
    se_mod = _reload_sentiment()
    monkeypatch.setattr(se_mod, "time_decay_weight", lambda age, tau=24.0: 1.0)
    # 同时重载 computer 的模块级导入（若 computer 已 from ... import tdw，则需在 computer 实例属性上补刀）
    #   安全：直接在 five_domain_feature_computer 模块替换
    monkeypatch.setattr(fc_mod, "time_decay_weight", lambda age, tau=24.0: 1.0, raising=False)

    d1_equal = computer._fd_S_dao_boost(None)
    assert isinstance(d1_equal, float)
    assert abs(d1_equal) <= 0.10

    # 3) 两个值必须不相等：因为 0h 强正 w=1.0 vs 72h 强正 w=0.05；等权版老新闻权重占比大 → 分数差异
    assert d1_decay != d1_equal, (
        f"衰减版D1={d1_decay} 与 等权版D1={d1_equal} 相等 → 时间衰减未生效！\n"
        "原因可能：five_domain_feature_computer 内部没有用 time_decay_weight 做加权。"
    )
