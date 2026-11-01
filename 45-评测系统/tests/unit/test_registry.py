# -*- coding: utf-8 -*-
"""
test_registry.py — P0-3 Threshold Registry 测试
================================================
验收（PLAN P0-3）：
- 版本化加载 config/thresholds.yaml（SPEC §8.1 全部 15 项）
- 缺字段拒绝、非法枚举拒绝、重复项拒绝、版本缺失拒绝
- get(category, item) 查询；未登记即 KeyError（默认拒绝）
- 变更审计：content_hash 随文件内容变化
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.registry import (  # noqa: E402
    CATEGORIES,
    ThresholdConfigError,
    ThresholdRegistry,
)

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "thresholds.yaml"


@pytest.fixture(scope="module")
def registry():
    return ThresholdRegistry.load(CONFIG_PATH)


def write_yaml(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "thresholds.yaml"
    p.write_text(text, encoding="utf-8")
    return p


MINIMAL_ITEM = """
  - item: F-H7
    category: finance
    value: 0.95
    metric: dsr
    min_n: 100
    kind: hard
"""


class TestRealConfig:
    """对仓库内真实 thresholds.yaml 的结构校验。"""

    def test_version(self, registry):
        assert registry.version == "TH-2026Q4@1"

    def test_all_15_items_loaded(self, registry):
        """SPEC §8.1 阈值表共 15 项。"""
        assert len(registry.all()) == 15

    def test_categories_cover_all(self, registry):
        cats = {t.category for t in registry.all()}
        assert cats == set(CATEGORIES)

    @pytest.mark.parametrize(
        "category,item,value,kind,direction,min_n",
        [
            ("finance", "F-W5", 0.70, "weighted", "gte", 100),
            ("finance", "F-H7", 0.95, "hard", "gte", 100),
            ("finance", "F-W2", 0.50, "weighted", "lte", 100),
            ("finance", "F-W3", 0.0, "weighted", "gte", 100),
            ("finance", "F-W4", 0.10, "weighted", "lte", 20),
            ("finance", "F-W1", 0.5, "weighted", "gte", 100),
            ("ai", "A-W1", 0.75, "weighted", "gte", 200),
            ("ai", "A-W2", 0.80, "weighted", "gte", 30),
            ("ai", "A-W3", 0.75, "weighted", "gte", 100),
            ("ai", "A-H4", 0.60, "hard", "gte", 200),
            ("engineering", "E-W1", 0.95, "weighted", "gte", 0),
            ("engineering", "E-W2", 0.60, "weighted", "gte", 0),
            ("engineering", "E-H4", 0.80, "hard", "gte", 0),
            ("engineering", "E-W5", 0.70, "weighted", "gte", 0),
            ("engineering", "E-W6", 7.0, "weighted", "gte", 0),
        ],
    )
    def test_spec_8_1_values(self, registry, category, item, value, kind, direction, min_n):
        t = registry.get(category, item)
        assert t.value == pytest.approx(value)
        assert t.kind == kind
        assert t.direction == direction
        assert t.min_n == min_n

    def test_composite_params(self, registry):
        """复合阈值：F-W3 附 MaxDD 1.5× 约束；A-H4 附 α≥0.67。"""
        assert registry.get("finance", "F-W3").params["maxdd_ratio_max"] == 1.5
        assert registry.get("ai", "A-H4").params["alpha_min"] == 0.67

    def test_by_category(self, registry):
        assert len(registry.by_category("finance")) == 6
        assert len(registry.by_category("ai")) == 4
        assert len(registry.by_category("engineering")) == 5

    def test_get_unregistered_rejected(self, registry):
        """§2.6 默认拒绝：未登记阈值查询即 KeyError。"""
        with pytest.raises(KeyError):
            registry.get("finance", "F-W99")
        with pytest.raises(KeyError):
            registry.get("trading", "F-H7")


class TestLoadValidation:
    def test_missing_file(self, tmp_path):
        with pytest.raises(ThresholdConfigError, match="不存在"):
            ThresholdRegistry.load(tmp_path / "nope.yaml")

    def test_missing_version(self, tmp_path):
        p = write_yaml(tmp_path, "items:\n" + MINIMAL_ITEM)
        with pytest.raises(ThresholdConfigError, match="version"):
            ThresholdRegistry.load(p)

    def test_empty_items(self, tmp_path):
        p = write_yaml(tmp_path, 'version: "TH-X@1"\nitems: []\n')
        with pytest.raises(ThresholdConfigError, match="非空列表"):
            ThresholdRegistry.load(p)

    def test_top_level_not_mapping(self, tmp_path):
        p = write_yaml(tmp_path, "- just\n- a\n- list\n")
        with pytest.raises(ThresholdConfigError, match="mapping"):
            ThresholdRegistry.load(p)

    @pytest.mark.parametrize("missing", ["category", "item", "value", "metric", "min_n", "kind"])
    def test_missing_required_field(self, tmp_path, missing):
        """缺字段拒绝（P0-3 验收核心）。"""
        item = {
            "item": "F-H7",
            "category": "finance",
            "value": 0.95,
            "metric": "dsr",
            "min_n": 100,
            "kind": "hard",
        }
        del item[missing]
        doc = yaml.safe_dump({"version": "TH-X@1", "items": [item]})
        p = write_yaml(tmp_path, doc)
        with pytest.raises(ThresholdConfigError, match=f"缺必填字段: {missing}"):
            ThresholdRegistry.load(p)

    def test_bad_category(self, tmp_path):
        bad = MINIMAL_ITEM.replace("category: finance", "category: trading")
        p = write_yaml(tmp_path, 'version: "TH-X@1"\nitems:\n' + bad)
        with pytest.raises(ThresholdConfigError, match="category 非法"):
            ThresholdRegistry.load(p)

    def test_bad_kind(self, tmp_path):
        bad = MINIMAL_ITEM.replace("kind: hard", "kind: reference")
        p = write_yaml(tmp_path, 'version: "TH-X@1"\nitems:\n' + bad)
        with pytest.raises(ThresholdConfigError, match="kind 非法"):
            ThresholdRegistry.load(p)

    def test_bad_direction(self, tmp_path):
        bad = MINIMAL_ITEM + "    direction: up\n"
        p = write_yaml(tmp_path, 'version: "TH-X@1"\nitems:\n' + bad)
        with pytest.raises(ThresholdConfigError, match="direction 非法"):
            ThresholdRegistry.load(p)

    def test_non_numeric_value(self, tmp_path):
        bad = MINIMAL_ITEM.replace("value: 0.95", 'value: "high"')
        p = write_yaml(tmp_path, 'version: "TH-X@1"\nitems:\n' + bad)
        with pytest.raises(ThresholdConfigError, match="value 必须是数值"):
            ThresholdRegistry.load(p)

    def test_negative_min_n(self, tmp_path):
        bad = MINIMAL_ITEM.replace("min_n: 100", "min_n: -1")
        p = write_yaml(tmp_path, 'version: "TH-X@1"\nitems:\n' + bad)
        with pytest.raises(ThresholdConfigError, match="min_n"):
            ThresholdRegistry.load(p)

    def test_bool_value_rejected(self, tmp_path):
        bad = MINIMAL_ITEM.replace("value: 0.95", "value: true")
        p = write_yaml(tmp_path, 'version: "TH-X@1"\nitems:\n' + bad)
        with pytest.raises(ThresholdConfigError, match="value 必须是数值"):
            ThresholdRegistry.load(p)

    def test_duplicate_item_rejected(self, tmp_path):
        p = write_yaml(tmp_path, 'version: "TH-X@1"\nitems:\n' + MINIMAL_ITEM + MINIMAL_ITEM)
        with pytest.raises(ThresholdConfigError, match="重复阈值项"):
            ThresholdRegistry.load(p)

    def test_default_direction_gte(self, tmp_path):
        p = write_yaml(tmp_path, 'version: "TH-X@1"\nitems:\n' + MINIMAL_ITEM)
        reg = ThresholdRegistry.load(p)
        assert reg.get("finance", "F-H7").direction == "gte"

    def test_content_hash_changes_with_content(self, tmp_path):
        """变更审计基础：内容变 → 哈希变。"""
        p1 = write_yaml(tmp_path, 'version: "TH-X@1"\nitems:\n' + MINIMAL_ITEM)
        h1 = ThresholdRegistry.load(p1).content_hash
        p2 = write_yaml(
            tmp_path,
            'version: "TH-X@2"\nitems:\n' + MINIMAL_ITEM.replace("0.95", "0.96"),
        )
        h2 = ThresholdRegistry.load(p2).content_hash
        assert h1 != h2 and len(h1) == 64
