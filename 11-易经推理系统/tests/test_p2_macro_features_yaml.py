#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P2 宏观特征 YAML 配置化 — TDD 6 TC

Spec: docs/superpowers/specs/2026-08-30-p2-macro-features-yaml-config-design.md

TC 清单：
  TC1 接口不变 — FEATURE_TO_DIM/ALL_FEATURES/REQUIRED_COLS 类型和内容
  TC2 YAML 正常加载 — monkeypatch 路径指向临时文件，reload() 返回 True
  TC3 YAML 缺失 FAIL-OPEN — 路径不存在，reload() 返回 False，回退默认值
  TC4 YAML 语法错误 FAIL-OPEN — 乱码内容，reload() 返回 False
  TC5 字节等价 — YAML 内容 == 默认值 → reload() 后完全一致
  TC6 compute 行为不变 — YAML 加载后 compute() 空输入返回空 DataFrame
"""
import os
import sys
import tempfile
import importlib

import pytest
import pandas as pd

# ============================================================
# 模块定位
# ============================================================
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

from scripts.memory_l4.bcrm2.macro_features import MacroFeatures


# ============================================================
# TC1: 接口不变
# ============================================================
class TestTC1Interface:
    def test_tc1_interface_unchanged(self):
        """FEATURE_TO_DIM 是 dict[str,str]，ALL_FEATURES 是 list[str]，len=37，REQUIRED_COLS 不变。"""
        assert isinstance(MacroFeatures.FEATURE_TO_DIM, dict), \
            f"FEATURE_TO_DIM 类型应为 dict，实际 {type(MacroFeatures.FEATURE_TO_DIM)}"
        for k, v in MacroFeatures.FEATURE_TO_DIM.items():
            assert isinstance(k, str), f"key {k!r} 不是 str"
            assert isinstance(v, str), f"value {v!r} 不是 str"
        assert isinstance(MacroFeatures.ALL_FEATURES, list), \
            f"ALL_FEATURES 类型应为 list，实际 {type(MacroFeatures.ALL_FEATURES)}"
        assert len(MacroFeatures.ALL_FEATURES) == 37, \
            f"ALL_FEATURES 长度应为 37，实际 {len(MacroFeatures.ALL_FEATURES)}"
        # REQUIRED_COLS 不变
        assert isinstance(MacroFeatures.REQUIRED_COLS, set)
        assert "fear_greed_index" in MacroFeatures.REQUIRED_COLS
        assert len(MacroFeatures.REQUIRED_COLS) == 12, \
            f"REQUIRED_COLS 长度应为 12，实际 {len(MacroFeatures.REQUIRED_COLS)}"


# ============================================================
# TC2: YAML 正常加载
# ============================================================
class TestTC2YamlLoad:
    def test_tc2_yaml_load_success(self, monkeypatch):
        """monkeypatch _YAML_PATH 指向临时文件 → reload() 返回 True，含临时特征。"""
        import scripts.memory_l4.bcrm2.macro_features as mod

        # 写临时 YAML 文件
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write("features:\n  test_feat_a: test_dim\n  test_feat_b: test_dim\n")
            tmp_path = f.name
        monkeypatch.setattr(mod, "_YAML_PATH", tmp_path)

        result = MacroFeatures.reload()
        assert result is True, f"reload() 应返回 True，实际 {result}"
        assert "test_feat_a" in MacroFeatures.FEATURE_TO_DIM, \
            f"FEATURE_TO_DIM 应含 test_feat_a，实际 {MacroFeatures.FEATURE_TO_DIM}"
        assert MacroFeatures.FEATURE_TO_DIM["test_feat_a"] == "test_dim"
        assert "test_feat_b" in MacroFeatures.ALL_FEATURES
        assert len(MacroFeatures.ALL_FEATURES) == 2

        # 清理：reload 回默认
        monkeypatch.undo()
        MacroFeatures.reload()
        os.unlink(tmp_path)


# ============================================================
# TC3: YAML 缺失 FAIL-OPEN
# ============================================================
class TestTC3YamlMissing:
    def test_tc3_yaml_missing_fallback(self, monkeypatch):
        """路径指向不存在文件 → reload() 返回 False，回退默认值。"""
        import scripts.memory_l4.bcrm2.macro_features as mod

        monkeypatch.setattr(mod, "_YAML_PATH", "/nonexistent/path/to/macro_features.yaml")
        result = MacroFeatures.reload()
        assert result is False, f"reload() 应返回 False，实际 {result}"
        # 应回退到默认值
        assert MacroFeatures.FEATURE_TO_DIM == mod._DEFAULT_FEATURE_TO_DIM, \
            "YAML 缺失时 FEATURE_TO_DIM 应等于 _DEFAULT_FEATURE_TO_DIM"
        assert len(MacroFeatures.ALL_FEATURES) == 37, \
            f"回退后 ALL_FEATURES 长度应为 37，实际 {len(MacroFeatures.ALL_FEATURES)}"

        # 恢复
        monkeypatch.undo()
        MacroFeatures.reload()


# ============================================================
# TC4: YAML 语法错误 FAIL-OPEN
# ============================================================
class TestTC4YamlSyntaxError:
    def test_tc4_yaml_syntax_error_fallback(self, monkeypatch):
        """临时文件写乱码 → reload() 返回 False，回退默认值。"""
        import scripts.memory_l4.bcrm2.macro_features as mod

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write("{{{{invalid yaml::: :::}}}\n  \t  - bad: [unclosed")
            tmp_path = f.name
        monkeypatch.setattr(mod, "_YAML_PATH", tmp_path)

        result = MacroFeatures.reload()
        assert result is False, f"reload() 应返回 False，实际 {result}"
        assert MacroFeatures.FEATURE_TO_DIM == mod._DEFAULT_FEATURE_TO_DIM, \
            "语法错误时 FEATURE_TO_DIM 应等于 _DEFAULT_FEATURE_TO_DIM"
        assert len(MacroFeatures.ALL_FEATURES) == 37

        monkeypatch.undo()
        MacroFeatures.reload()
        os.unlink(tmp_path)


# ============================================================
# TC5: 字节等价
# ============================================================
class TestTC5ByteEquivalent:
    def test_tc5_yaml_equals_defaults(self, monkeypatch):
        """YAML 内容 == 默认值 → reload() 后 FEATURE_TO_DIM 和 ALL_FEATURES 完全一致。"""
        import scripts.memory_l4.bcrm2.macro_features as mod

        # 从默认值生成 YAML 内容
        import yaml as _yaml
        yaml_content = _yaml.dump({"features": dict(mod._DEFAULT_FEATURE_TO_DIM)})

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write(yaml_content)
            tmp_path = f.name
        monkeypatch.setattr(mod, "_YAML_PATH", tmp_path)

        result = MacroFeatures.reload()
        assert result is True

        # FEATURE_TO_DIM key/value 完全一致
        assert MacroFeatures.FEATURE_TO_DIM == mod._DEFAULT_FEATURE_TO_DIM, \
            "YAML 内容 == 默认值时 FEATURE_TO_DIM 应完全一致"
        # ALL_FEATURES 长度和内容一致
        assert len(MacroFeatures.ALL_FEATURES) == len(mod._DEFAULT_FEATURE_TO_DIM)
        for feat in mod._DEFAULT_FEATURE_TO_DIM:
            assert feat in MacroFeatures.ALL_FEATURES, f"{feat} 不在 ALL_FEATURES 中"

        monkeypatch.undo()
        MacroFeatures.reload()
        os.unlink(tmp_path)


# ============================================================
# TC6: compute 行为不变
# ============================================================
class TestTC6ComputeBehavior:
    def test_tc6_compute_empty_macro_df(self, monkeypatch):
        """YAML 加载后 compute() 空 macro_df 返回空 DataFrame（行为不变）。"""
        import scripts.memory_l4.bcrm2.macro_features as mod

        # 先用默认值跑一次
        df = pd.DataFrame({"close": [100, 101, 102]})
        mf = MacroFeatures()
        result_default = mf.compute(df, macro_df=None, config={})
        assert isinstance(result_default, pd.DataFrame)
        assert result_default.empty, "空 macro_df 应返回空 DataFrame"

        # monkeypatch 一个最小 YAML（2个特征），reload 后再跑
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write("features:\n  test_feat: test_dim\n")
            tmp_path = f.name
        monkeypatch.setattr(mod, "_YAML_PATH", tmp_path)
        MacroFeatures.reload()

        mf2 = MacroFeatures()
        result_yaml = mf2.compute(df, macro_df=None, config={})
        assert isinstance(result_yaml, pd.DataFrame)
        assert result_yaml.empty, "YAML 加载后空 macro_df 仍应返回空 DataFrame"

        # 恢复
        monkeypatch.undo()
        MacroFeatures.reload()
        os.unlink(tmp_path)
