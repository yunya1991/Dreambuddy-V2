"""
4-MEMORY tests conftest.py
TDD fixtures:
  - tmp_gene_dir:     临时目录结构 = schemas/ + strategy_genes/{conditions,actions}/ + strategy_combinations/
                      内含最小合法样本 & 非法恶意样本（用于 TR-SG-01/04/08/09）
  - fake_alerts:      monkeypatch dreambuddy_core/alert_bridge → 计数（避免 Lark API 依赖）
  - fake_sentiment_0: SentimentEngine monkeypatch USE_FINBERT=0 → sent=0.5（TR-RV-06 场景）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]  # 4-MEMORY/tests -> 4-MEMORY -> repo root
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ROOT = Path(__file__).resolve().parents[2]  # repo root（4-MEMORY 是 repo 子目录，parents[1]=repo root）
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# --------------------------------------------------------------------------------
# 1. tmp_gene_dir: 临时目录 完整结构 + 合法样本/非法样本/恶意注入样本
# --------------------------------------------------------------------------------
@pytest.fixture
def tmp_gene_dir(tmp_path, monkeypatch):
    """构造最小基因库结构（用于 TR-SG-01~09/10 验收）"""
    schemas_dir = tmp_path / "schemas"
    cond_dir = tmp_path / "strategy_genes" / "conditions"
    act_dir = tmp_path / "strategy_genes" / "actions"
    comb_dir = tmp_path / "strategy_combinations"
    schemas_dir.mkdir(parents=True)
    cond_dir.mkdir(parents=True)
    act_dir.mkdir(parents=True)
    comb_dir.mkdir(parents=True)

    # 复制真实 schemas（MVP Spec §3.2，已经写在 dreambuddy_core/data 或 4-MEMORY/.../schemas/）——此处先留最小合法 schema：
    real_schemas = ROOT / "4-MEMORY" / "2-交易记忆单元" / "schemas"
    if real_schemas.exists():
        for f in real_schemas.glob("*.json"):
            (schemas_dir / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")

    # 1. 最小合法 CONDITION 样本（schema_pass_rate 测试基础通过）
    ok_cond = {
        "gene_id": "CD-MA200-GT-FIB0786",
        "category": "trend",
        "condition_type": "indicator",
        "expression": "ma_200 > fib_retrace_0786",
        "parameters": {
            "ma_window": {"value": 200, "range": {"low": 100, "high": 300}},
            "fib_level": {"value": 0.786, "range": {"low": 0.382, "high": 0.886}},
        },
        "code_ref": {
            "file": "21-特征工程中心/feature_hub/modules/classic_indicators.py",
            "lines": {"low": 12, "high": 45},
        },
        "version": "1.0",
    }
    (cond_dir / "CD-MA200-GT-FIB0786.json").write_text(json.dumps(ok_cond, indent=2), encoding="utf-8")

    # 2. 最小合法 ACTION 样本
    ok_action = {
        "gene_id": "AC-LONG-3SL-6TP-05SIZE",
        "category": "entry_long",
        "action_kind": "open",
        "direction": "long",
        "sl_template": 0.03,
        "tp_template": 0.06,
        "size_pct": 0.50,
        "parameters": {
            "sl_atr_mult": {"value": 1.5, "range": {"low": 1.0, "high": 2.5}},
            "tp_rr": {"value": 2.0, "range": {"low": 1.2, "high": 4.0}},
        },
        "code_ref": {
            "file": "13-通用风控模块/rules/gate_rules.py",
            "lines": {"low": 20, "high": 80},
        },
        "version": "1.0",
    }
    (act_dir / "AC-LONG-3SL-6TP-05SIZE.json").write_text(json.dumps(ok_action, indent=2), encoding="utf-8")

    # 3. 恶意注入 CONDITION 样本（TR-SG-08 恶意注入 不 crash 只跳过）
    bad_cond_xss = {
        "gene_id": "XSS-INJECT-01",
        "category": "<script>alert('xss')</script>",
        "condition_type": "indicator",
        "expression": "1 > 0",
        "parameters": {},
        "code_ref": {"file": f"<script src='evil.js'>{'.'*1000}</script>",
                     "lines": {"low": 1, "high": 2}},
        "version": "1.0",
    }
    (cond_dir / "BAD-XSS.json").write_text(json.dumps(bad_cond_xss, indent=2), encoding="utf-8")

    # 4. 参数 range 非法 CONDITION（low > high TR-SG-09）
    bad_cond_range = {
        "gene_id": "BAD-RANGE-01",
        "category": "trend",
        "condition_type": "indicator",
        "expression": "a > b",
        "parameters": {"x": {"value": 5, "range": {"low": 300, "high": 100}}},  # low>high 非法
        "code_ref": {"file": "a.py", "lines": {"low": 1, "high": 10}},
        "version": "1.0",
    }
    (cond_dir / "BAD-RANGE.json").write_text(json.dumps(bad_cond_range, indent=2), encoding="utf-8")

    # 5. 合法最小组合
    ok_comb = {
        "combo_id": "CB-TREND-LONG-001",
        "condition_ids": ["CD-MA200-GT-FIB0786"],
        "action_ids": ["AC-LONG-3SL-6TP-0.5SIZE"],
        "meta": {"H": 0.7, "S": 0.75, "N": 400},
        "version": "1.0",
    }
    (comb_dir / "library.json").write_text(json.dumps([ok_comb], indent=2), encoding="utf-8")
    (comb_dir / "ess_scores.csv").write_text(
        "combo_id,H,S,N,ESS\nCB-TREND-LONG-001,0.70,0.75,400,0.823\n",
        encoding="utf-8",
    )

    yield tmp_path


# --------------------------------------------------------------------------------
# 2. fake_alerts: monkeypatch alert bridge -> 计数 (TR-RV-08 5min3次 触发)
# --------------------------------------------------------------------------------
@pytest.fixture
def fake_alerts(monkeypatch):
    class FakeAlert:
        counts: dict[str, int] = {"warn": 0, "critical": 0, "error": 0, "info": 0}
        last_messages: list[str] = []

        @classmethod
        def send(cls, level: str, message: str, **_kwargs):
            cls.counts[level] = cls.counts.get(level, 0) + 1
            cls.last_messages.append(message[:120])

    # 尝试 monkeypatch 项目 alert_bridge（如存在）；无论 import 是否成功，fake 都作为 fixture 提供给测试
    try:
        from dreambuddy_core import alert_bridge as ab
        monkeypatch.setattr(ab, "send_alert", FakeAlert.send, raising=False)
    except Exception:
        pass  # CI 环境可能没有真实 alert module；所有测试 accept FakeAlert 注入
    return FakeAlert


# --------------------------------------------------------------------------------
# 3. fake_sentiment_0: SentimentEngine USE_FINBERT=0 monkeypatch (TR-RV-06)
# --------------------------------------------------------------------------------
@pytest.fixture
def fake_sentiment_0(monkeypatch):
    class FakeSentimentEngine:
        USE_FINBERT: int = 0
        def get_sentiment(self, *args, **kwargs):
            return 0.5  # L1 默认降级 55/45 → quality_score 扣0.15
    try:
        from 九基本面分析.engines import sentiment_engine as sent_mod
        monkeypatch.setattr(sent_mod, "USE_FINBERT", 0, raising=False)
    except Exception:
        pass
    return FakeSentimentEngine()
