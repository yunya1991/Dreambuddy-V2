"""T20 · fh CLI 四命令测试

T20-1: fh list — 列出5模块+3集合
T20-2: fh inspect --set alt_trend_ensemble — 输出含列数/模块/血缘OK
T20-3: fh run-sample --set btc_morph_v6 — 输出含 Rows/Columns/Modules
T20-4: fh export-schema --set equity_classic_trend — JSON 含 columns/column_count
"""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

_21_ROOT = Path(__file__).resolve().parents[2]
for _p in [str(_21_ROOT), str(_21_ROOT / "feature_hub")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ============================================================
# T20-1  fh list
# ============================================================
def test_t20_1_list():
    from feature_hub.cli.app import main

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["list"])
    out = buf.getvalue()
    assert rc == 0
    # 5 个模块
    for mod in ("crypto_morphology", "elder_ray", "triple_screen_trend",
                "classic_indicators", "five_domain_fc"):
        assert mod in out, f"模块 {mod} 未列出"
    # 3 个集合
    for s in ("btc_morph_v6", "alt_trend_ensemble", "equity_classic_trend"):
        assert s in out, f"集合 {s} 未列出"


# ============================================================
# T20-2  fh inspect --set alt_trend_ensemble
# ============================================================
def test_t20_2_inspect():
    from feature_hub.cli.app import main

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["inspect", "--set", "alt_trend_ensemble"])
    out = buf.getvalue()
    assert rc == 0
    assert "Actual columns" in out
    assert "Lineage: OK" in out
    assert "modules_run" in out or "Modules run" in out


# ============================================================
# T20-3  fh run-sample --set btc_morph_v6
# ============================================================
def test_t20_3_run_sample():
    from feature_hub.cli.app import main

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["run-sample", "--set", "btc_morph_v6", "--symbol", "BTC"])
    out = buf.getvalue()
    assert rc == 0
    assert "Rows:" in out
    assert "Columns:" in out
    assert "Modules run" in out


# ============================================================
# T20-4  fh export-schema --set equity_classic_trend
# ============================================================
def test_t20_4_export_schema():
    from feature_hub.cli.app import main

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["export-schema", "--set", "equity_classic_trend"])
    out = buf.getvalue()
    assert rc == 0
    # 输出是 JSON
    schema = json.loads(out)
    assert schema["set_name"] == "equity_classic_trend"
    assert "columns" in schema
    assert schema["column_count"] >= 30
    assert len(schema["columns"]) == schema["column_count"]
