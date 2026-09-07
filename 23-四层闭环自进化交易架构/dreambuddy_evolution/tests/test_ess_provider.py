"""test_ess_provider.py — ESSDirectionProvider 单元测试
覆盖: 基因库加载+ESS排序, top1 direction提取, n_samples=0降级, 库缓存, 空library FO
"""
from __future__ import annotations

import pytest

from dreambuddy_evolution.adapters.ess_provider import ESSDirectionProvider


class TestESSDirectionProvider:

    def test_real_gene_library(self):
        """从真实 gene_data 库加载 ESS 排序"""
        import sys
        from pathlib import Path
        # tests/ → dreambuddy_evolution/ → 23-四层闭环自进化交易架构/
        evo_pkg = Path(__file__).resolve().parents[1]  # dreambuddy_evolution/
        evo_root = evo_pkg.parent  # 23-四层闭环自进化交易架构/
        if str(evo_root) not in sys.path:
            sys.path.insert(0, str(evo_root))

        gene_root = str(evo_pkg / "gene_data")
        provider = ESSDirectionProvider(gene_root, min_sample=0)
        result = provider.get_top_direction()

        assert "ess_top_direction" in result
        assert "ess_top1_id" in result
        # 库中有 CB-GRID-001 (n=255) 和 CB-GRID-002 (n=488)
        # min_sample=0 时应有结果
        assert result["ess_top1_id"] != ""
        # top1 应该是 long（目前所有组合都是 entry_long）
        assert result["ess_top_direction"] in ("long", "short", "")

    def test_empty_library_fo(self, tmp_path):
        """空基因库 → ess_top_direction=''"""
        provider = ESSDirectionProvider(str(tmp_path), min_sample=0)
        result = provider.get_top_direction()
        # 不 crash，返回空字符串
        assert result["ess_top_direction"] == ""

    def test_cache(self):
        """6h 缓存：第二次调用不重新计算"""
        import sys
        from pathlib import Path
        evo_pkg = Path(__file__).resolve().parents[1]
        evo_root = evo_pkg.parent
        if str(evo_root) not in sys.path:
            sys.path.insert(0, str(evo_root))

        gene_root = str(evo_pkg / "gene_data")
        provider = ESSDirectionProvider(gene_root, min_sample=0)

        r1 = provider.get_top_direction()
        r2 = provider.get_top_direction()
        # 缓存命中 → 结果一致
        assert r1["ess_top1_id"] == r2["ess_top1_id"]
        assert r1["ess_top_direction"] == r2["ess_top_direction"]

    def test_invalidate_cache(self):
        """手动失效缓存"""
        import sys
        from pathlib import Path
        evo_pkg = Path(__file__).resolve().parents[1]
        evo_root = evo_pkg.parent
        if str(evo_root) not in sys.path:
            sys.path.insert(0, str(evo_root))

        gene_root = str(evo_pkg / "gene_data")
        provider = ESSDirectionProvider(gene_root, min_sample=0)
        r1 = provider.get_top_direction()
        provider.invalidate_cache()
        r2 = provider.get_top_direction()
        # 重新计算 → 结果应一致
        assert r1["ess_top1_id"] == r2["ess_top1_id"]

    def test_min_sample_filter(self):
        """min_sample 过高 → 过滤掉所有组合 → 空结果"""
        import sys
        from pathlib import Path
        evo_pkg = Path(__file__).resolve().parents[1]
        evo_root = evo_pkg.parent
        if str(evo_root) not in sys.path:
            sys.path.insert(0, str(evo_root))

        gene_root = str(evo_pkg / "gene_data")
        # min_sample=99999 过滤掉所有
        provider = ESSDirectionProvider(gene_root, min_sample=99999)
        result = provider.get_top_direction()
        assert result["ess_top_direction"] == ""
