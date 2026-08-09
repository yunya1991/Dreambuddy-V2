#!/usr/bin/env python3
"""
test_config_wiring.py — PROP-20260810 验收测试（config.json 接线）

验收标准:
  1. config confidence_threshold=0.30 → from_config().min_confidence_threshold==0.30
  2. config 缺失/损坏/键越界 → 默认构造，不抛异常
  3. 生产路径零裸构造残留（grep 级验证在 E2 报告中，此处做导入级冒烟）
  4. E2E: 进化采纳 → config 固化 → 新引擎实例生效
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # 11-易经推理系统
sys.path.insert(0, str(ROOT))

from scripts.memory_l4.bcrm.engine import BCRMEngine, default_engine  # noqa: E402

DEFAULT_THRESHOLD = 0.25  # engine.py L65 构造默认值


class TestFromConfigInjection(unittest.TestCase):
    """验收 1: config 采纳值正确注入引擎"""

    def test_threshold_injected(self):
        """confidence_threshold=0.30 → min_confidence_threshold==0.30"""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg_path.write_text(json.dumps(
                {"confidence_threshold": 0.30}), encoding="utf-8")
            engine = BCRMEngine.from_config(cfg_path)
            self.assertAlmostEqual(engine.min_confidence_threshold, 0.30)

    def test_string_numeric_value_coerced(self):
        """config 值为字符串数字 '0.35' → 正确转换"""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg_path.write_text(json.dumps(
                {"confidence_threshold": "0.35"}), encoding="utf-8")
            engine = BCRMEngine.from_config(cfg_path)
            self.assertAlmostEqual(engine.min_confidence_threshold, 0.35)

    def test_other_config_keys_untouched(self):
        """config 含其他键（api_key 等）不影响构造"""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg_path.write_text(json.dumps({
                "confidence_threshold": 0.40,
                "api_key": "secret_should_not_leak",
                "daily_loss_limit": 50,
            }), encoding="utf-8")
            engine = BCRMEngine.from_config(cfg_path)
            self.assertAlmostEqual(engine.min_confidence_threshold, 0.40)


class TestFromConfigFallback(unittest.TestCase):
    """验收 2: 异常全回退默认构造（零风险）"""

    def test_missing_file_fallback(self):
        engine = BCRMEngine.from_config("/nonexistent_xyz/config.json")
        self.assertEqual(engine.min_confidence_threshold, DEFAULT_THRESHOLD)

    def test_corrupt_json_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg_path.write_text("{corrupt json!!", encoding="utf-8")
            engine = BCRMEngine.from_config(cfg_path)
            self.assertEqual(engine.min_confidence_threshold, DEFAULT_THRESHOLD)

    def test_non_dict_json_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg_path.write_text("[1, 2, 3]", encoding="utf-8")
            engine = BCRMEngine.from_config(cfg_path)
            self.assertEqual(engine.min_confidence_threshold, DEFAULT_THRESHOLD)

    def test_out_of_bounds_ignored(self):
        """越界值（>0.95 / <0.01）→ 忽略，用默认值（不带病注入）"""
        for bad_val in (1.5, -0.3, 0.999):
            with tempfile.TemporaryDirectory() as td:
                cfg_path = Path(td) / "config.json"
                cfg_path.write_text(json.dumps(
                    {"confidence_threshold": bad_val}), encoding="utf-8")
                engine = BCRMEngine.from_config(cfg_path)
                self.assertEqual(
                    engine.min_confidence_threshold, DEFAULT_THRESHOLD,
                    f"越界值 {bad_val} 不应被注入")

    def test_non_numeric_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg_path.write_text(json.dumps(
                {"confidence_threshold": "abc"}), encoding="utf-8")
            engine = BCRMEngine.from_config(cfg_path)
            self.assertEqual(engine.min_confidence_threshold, DEFAULT_THRESHOLD)

    def test_key_absent_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg_path.write_text(json.dumps(
                {"api_key": "only_other_keys"}), encoding="utf-8")
            engine = BCRMEngine.from_config(cfg_path)
            self.assertEqual(engine.min_confidence_threshold, DEFAULT_THRESHOLD)


class TestProductionConstructionSites(unittest.TestCase):
    """验收 3: 生产构造点已全部接线（导入级冒烟）"""

    def test_default_engine_factory_wired(self):
        """default_engine() 工厂走 from_config（无 config 时回退默认）"""
        engine = default_engine()
        self.assertIsInstance(engine, BCRMEngine)
        self.assertIsInstance(engine.min_confidence_threshold, float)

    def test_production_files_have_no_bare_construction(self):
        """grep 级验证: 生产文件不存在裸 BCRMEngine() 构造"""
        import re
        mem_dir = ROOT / "scripts" / "memory_l4"
        prod_files = ["polling_trader.py", "yijing_monitor.py", "ab_bridge.py"]
        pattern = re.compile(r"=\s*BCRMEngine\(\)")
        for fname in prod_files:
            text = (mem_dir / fname).read_text(encoding="utf-8")
            matches = pattern.findall(text)
            self.assertEqual(
                len(matches), 0,
                f"{fname} 仍有 {len(matches)} 处裸 BCRMEngine() 构造")


class TestEndToEndEvolutionWiring(unittest.TestCase):
    """验收 4 (E2E): 进化采纳 → config 固化 → 新引擎实例生效"""

    def test_adopted_threshold_reaches_new_engine(self):
        """模拟完整闭环: _apply_adopted_to_config 写入的值，
        新 from_config 引擎实例能读到"""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            # 模拟 self_evolution_engine._apply_adopted_to_config 的写入
            # （映射: param_key min_confidence_threshold → config 键 confidence_threshold）
            adopted_value = 0.32
            cfg_path.write_text(json.dumps(
                {"confidence_threshold": adopted_value}), encoding="utf-8")

            # 模拟生产引擎重启/新建实例
            engine = BCRMEngine.from_config(cfg_path)
            self.assertAlmostEqual(
                engine.min_confidence_threshold, adopted_value,
                places=5,
                msg="进化采纳值未到达生产引擎（闭环最后一跳断裂）")


if __name__ == "__main__":
    unittest.main(verbosity=2)
