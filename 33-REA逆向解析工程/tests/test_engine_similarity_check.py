"""RED 测试：P2-2 引擎相似度自动化准入检查（SPEC 维度C 评审6 + v0.3 修订）。

验收（SPEC L168）：engine_similarity_check.py 脚本实现，接入 CI
（加权 Jaccard > 0.7 告警，排除基础库）。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.engine_similarity_check import (  # noqa: E402
    EngineSimilarityChecker,
    DEFAULT_TARGET_DIR,
    main,
)


# ---------------------------------------------------------------------------
# 合成引擎样本
# ---------------------------------------------------------------------------

ENGINE_A = '''
import logging
import numpy as np
from typing import Any
from dreambuddy_evolution.core.cross_attention import CrossAttention
from dreambuddy_evolution.agi_config import is_enabled

class EngineA:
    def __init__(self):
        self.attention = CrossAttention()
        self.logger = logging.getLogger(__name__)

    def compute(self, series):
        scores = self.attention.forward(series)
        for i, x in enumerate(series):
            scores[i] = self._scale(x)
        return scores

    def _scale(self, x):
        return x * 0.8
'''

# 与 A 共享领域 import + 主调用链，仅方法名/系数不同 → 高相似
ENGINE_B = '''
import logging
import numpy as np
from typing import Any
from dreambuddy_evolution.core.cross_attention import CrossAttention
from dreambuddy_evolution.agi_config import is_enabled

class EngineB:
    def __init__(self):
        self.attention = CrossAttention()
        self.logger = logging.getLogger(__name__)

    def compute(self, series):
        scores = self.attention.forward(series)
        for i, x in enumerate(series):
            scores[i] = self._apply(x)
        return scores

    def _apply(self, x):
        return x * 0.5
'''

# 完全不同域 → 低相似
ENGINE_C = '''
import math

class EngineC:
    def transform(self, values):
        out = []
        for v in values:
            out.append(v ** 2)
        return out

    def summarize(self, data):
        total = 0.0
        for x in data:
            total += x
        return total / len(data)
'''


def _write(tmp_path, name, source):
    p = tmp_path / name
    p.write_text(source, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# 特征提取：基础库排除 + 领域模块识别
# ---------------------------------------------------------------------------

class TestFeatureExtraction:
    def setup_method(self):
        self.checker = EngineSimilarityChecker()

    def test_base_lib_imports_excluded(self):
        source = "import logging\nimport numpy as np\nimport pandas as pd\nfrom dataclasses import dataclass\nfrom typing import Any\n"
        feats = self.checker.extract_features(source)
        assert feats["imports"] == set()

    def test_domain_import_extracted(self):
        source = "from dreambuddy_evolution.core.cross_attention import CrossAttention\n"
        feats = self.checker.extract_features(source)
        assert feats["imports"] == {"core.cross_attention"}

    def test_domain_top_level_module_extracted(self):
        source = "from dreambuddy_evolution.agi_config import is_enabled\n"
        feats = self.checker.extract_features(source)
        assert feats["imports"] == {"agi_config"}

    def test_unknown_third_party_kept_full_path(self):
        source = "from event_driven.event_dominance_controller import X\n"
        feats = self.checker.extract_features(source)
        assert feats["imports"] == {"event_driven.event_dominance_controller"}

    def test_calls_extracted_with_self_prefix_stripped(self):
        source = "class A:\n    def run(self):\n        return self.detector.detect(x)\n"
        feats = self.checker.extract_features(source)
        assert "detector.detect" in feats["calls"]

    def test_plain_function_call_extracted(self):
        source = "def run():\n    return helper(x)\n"
        feats = self.checker.extract_features(source)
        assert "helper" in feats["calls"]

    def test_builtin_calls_excluded(self):
        source = "def run(xs):\n    print(len(xs))\n    return sorted(xs)\n"
        feats = self.checker.extract_features(source)
        assert feats["calls"] == set()


# ---------------------------------------------------------------------------
# 加权 Jaccard：领域模块权重 3x
# ---------------------------------------------------------------------------

class TestWeightedJaccard:
    def setup_method(self):
        self.checker = EngineSimilarityChecker()

    def test_identical_features(self):
        feats = {"imports": {"core.x"}, "calls": {"foo"}}
        assert self.checker.weighted_jaccard(feats, feats) == pytest.approx(1.0)

    def test_disjoint_features(self):
        a = {"imports": {"core.x"}, "calls": set()}
        b = {"imports": {"core.y"}, "calls": set()}
        assert self.checker.weighted_jaccard(a, b) == pytest.approx(0.0)

    def test_empty_features(self):
        empty = {"imports": set(), "calls": set()}
        other = {"imports": {"core.x"}, "calls": set()}
        assert self.checker.weighted_jaccard(empty, other) == pytest.approx(0.0)
        assert self.checker.weighted_jaccard(empty, empty) == pytest.approx(0.0)

    def test_domain_import_weights_3x(self):
        # 共享 1 个领域 import（权重3），B 多 1 个普通 call（权重1）→ 3/4 = 0.75
        # 若不加权（普通 Jaccard）则为 1/2 = 0.5
        a = {"imports": {"core.x"}, "calls": set()}
        b = {"imports": {"core.x"}, "calls": {"foo"}}
        assert self.checker.weighted_jaccard(a, b) == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# 目录扫描：相似对告警 + 排除 __init__.py
# ---------------------------------------------------------------------------

class TestScan:
    def test_scan_reports_similar_pair_only(self, tmp_path):
        _write(tmp_path, "engine_a.py", ENGINE_A)
        _write(tmp_path, "engine_b.py", ENGINE_B)
        _write(tmp_path, "engine_c.py", ENGINE_C)
        report = EngineSimilarityChecker(threshold=0.7).scan(tmp_path)

        assert report["engine_count"] == 3
        warned = {(w["a"], w["b"]) for w in report["warnings"]}
        assert ("engine_a.py", "engine_b.py") in warned
        # C 与 A/B 不相似，不应告警
        assert all("engine_c.py" not in pair for pair in warned)
        # 每条告警含"建议并入现有引擎"建议（指向行数较大的现有引擎）
        for w in report["warnings"]:
            assert w["suggestion"].startswith("建议并入现有引擎")
            assert w["similarity"] > 0.7

    def test_scan_excludes_init_and_pycache(self, tmp_path):
        _write(tmp_path, "__init__.py", ENGINE_A)
        _write(tmp_path, "engine_b.py", ENGINE_B)
        sub = tmp_path / "grid_trading"
        sub.mkdir()
        _write(sub, "engine_a.py", ENGINE_A)
        report = EngineSimilarityChecker(threshold=0.7).scan(tmp_path)
        assert report["engine_count"] == 2

    def test_scan_no_warning_below_threshold(self, tmp_path):
        _write(tmp_path, "engine_a.py", ENGINE_A)
        _write(tmp_path, "engine_c.py", ENGINE_C)
        report = EngineSimilarityChecker(threshold=0.7).scan(tmp_path)
        assert report["warnings"] == []


# ---------------------------------------------------------------------------
# CLI：非阻塞退出码 + 告警文本
# ---------------------------------------------------------------------------

class TestCli:
    def test_main_returns_zero_even_with_warnings(self, tmp_path, capsys):
        _write(tmp_path, "engine_a.py", ENGINE_A)
        _write(tmp_path, "engine_b.py", ENGINE_B)
        rc = main(["--target-dir", str(tmp_path)])
        assert rc == 0  # 非阻塞：告警不失败 CI
        out = capsys.readouterr().out
        assert "建议并入现有引擎" in out

    def test_main_writes_json_report(self, tmp_path):
        _write(tmp_path, "engine_a.py", ENGINE_A)
        _write(tmp_path, "engine_b.py", ENGINE_B)
        out_json = tmp_path / "report.json"
        rc = main(["--target-dir", str(tmp_path), "--json", str(out_json)])
        assert rc == 0
        assert out_json.exists()

    def test_main_clean_dir_no_warning_text(self, tmp_path, capsys):
        _write(tmp_path, "engine_c.py", ENGINE_C)
        rc = main(["--target-dir", str(tmp_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "建议并入现有引擎" not in out


# ---------------------------------------------------------------------------
# 默认目标目录指向 engines/
# ---------------------------------------------------------------------------

class TestDefaultTarget:
    def test_default_target_dir_is_engines(self):
        assert DEFAULT_TARGET_DIR.exists()
        assert DEFAULT_TARGET_DIR.name == "engines"
