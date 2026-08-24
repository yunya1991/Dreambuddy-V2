"""M4 收口切换回归测试 — 验证调用方已切换 + 老模块已废弃。

验收标准：
1. 调用方文件不再直接 import 老模块（flow_collector / data_collector / market_data）
2. 调用方文件 import from data_center.compat
3. 老模块有 @deprecated 标记
"""
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 调用方文件列表
CALLERS = [
    PROJECT_ROOT / "9-基本面分析" / "ops" / "nanoclaw" / "core_task1" / "flow" / "scripts" / "run_flow_analysis.py",
    PROJECT_ROOT / "12-三屏趋势系统" / "live" / "strategy_runner.py",
    PROJECT_ROOT / "9-基本面分析" / "ml_trade_service_v2.py",
]

# 老模块名（不应出现在调用方的 import 行中）
OLD_MODULES = ["flow_collector", "data_collector", "market_data"]


def _read_imports(filepath: Path) -> list[str]:
    """读取文件中所有 import 行。"""
    if not filepath.exists():
        return []
    lines = filepath.read_text(encoding="utf-8").splitlines()
    return [l.strip() for l in lines if re.match(r"^\s*(from|import)\s", l)]


def test_callers_use_data_center_compat():
    """调用方应 import from data_center.compat，不再直接 import 老模块。"""
    for caller in CALLERS:
        imports = _read_imports(caller)
        assert any("data_center.compat" in line for line in imports), (
            f"{caller.name} 未切换到 data_center.compat: {imports}"
        )


def test_callers_no_direct_old_module_import():
    """调用方不应直接 import 老模块。"""
    for caller in CALLERS:
        imports = _read_imports(caller)
        for line in imports:
            # 排除 data_center.compat 自身的 import
            if "data_center" in line:
                continue
            for mod in OLD_MODULES:
                assert mod not in line, (
                    f"{caller.name} 仍有老模块 import: {line}"
                )


def test_old_modules_have_deprecated_marker():
    """老模块文件应有 @deprecated 标记。"""
    old_files = [
        PROJECT_ROOT / "9-基本面分析" / "ops" / "nanoclaw" / "core_task1" / "flow" / "scripts" / "flow_collector.py",
        PROJECT_ROOT / "9-基本面分析" / "data_collector.py",
        PROJECT_ROOT / "12-三屏趋势系统" / "data" / "market_data.py",
    ]
    for f in old_files:
        content = f.read_text(encoding="utf-8")
        assert "@deprecated" in content.lower() or "已废弃" in content, (
            f"{f.name} 缺少 @deprecated 标记"
        )


def test_compat_exports_all_functions():
    """data_center.compat 应导出所有兼容函数。"""
    from data_center.compat import (
        fetch_candles,
        resample_candles,
        fetch_tavily_news,
        fetch_yahoo_symbol,
        fetch_fred_series,
        run_full_collection,
        DataCollector,
        generate_timeseries,
    )
    assert callable(fetch_candles)
    assert callable(resample_candles)
    assert callable(fetch_tavily_news)
    assert callable(fetch_yahoo_symbol)
    assert callable(fetch_fred_series)
    assert callable(run_full_collection)
    assert DataCollector is not None
    assert callable(generate_timeseries)
