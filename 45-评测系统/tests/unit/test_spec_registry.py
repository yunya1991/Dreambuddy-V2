# -*- coding: utf-8 -*-
"""
test_spec_registry.py — P2-9 spec 注册表与全量 spec_hash 测试
=============================================================
验收（SPEC §3.1/§3.3，闭环 TODO(P2-9)）：
- register：必填字段校验；spec_id 重复注册拒绝（版本不可变）
- resolve：未注册即拒（fail-closed）
- spec_hash：sha256(canonical_json(完整 EvalSpec))；字段变更 → 哈希变化
- 与占位实现区分：全量哈希 ≠ 占位哈希
- Gateway 接入：注册表可用时受理按全量哈希；未注册 spec 拒绝受理
- 向后兼容：未提供注册表时保持占位实现
- FileSpecRegistry：list 与 {"specs": [...]} 两种文件形态
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest  # noqa: E402

from core.gateway import CategoriesConfig, Gateway, spec_hash_placeholder  # noqa: E402
from core.spec_registry import (  # noqa: E402
    FileSpecRegistry,
    SpecRegistry,
    SpecRegistryError,
    spec_hash_of,
)


def make_spec(**overrides) -> dict:
    spec = {
        "spec_id": "EVS-20261101-0001",
        "version": "1.0.0",
        "category": "finance",
        "object_type": "strategy",
        "evaluator_ref": "EV-finance.backtest@1.2.0",
        "scorers": [{"id": "SC-code@1.0.0", "role": "primary"}],
        "thresholds_ref": "TH-2026Q4@1",
        "created_by": "test",
    }
    spec.update(overrides)
    return spec


class TestSpecRegistry:
    def test_register_and_resolve(self):
        reg = SpecRegistry()
        spec = make_spec()
        reg.register(spec)
        assert reg.resolve("EVS-20261101-0001") == spec
        assert len(reg) == 1

    def test_register_missing_required_fields_rejected(self):
        reg = SpecRegistry()
        with pytest.raises(SpecRegistryError, match="缺必填字段"):
            reg.register({"spec_id": "EVS-x"})

    def test_register_duplicate_rejected(self):
        reg = SpecRegistry()
        reg.register(make_spec())
        with pytest.raises(SpecRegistryError, match="禁止原地修改"):
            reg.register(make_spec())

    def test_resolve_unregistered_fail_closed(self):
        reg = SpecRegistry()
        with pytest.raises(SpecRegistryError, match="spec 未注册"):
            reg.resolve("EVS-unknown")

    def test_spec_hash_is_full_hash(self):
        reg = SpecRegistry()
        spec = make_spec()
        reg.register(spec)
        assert reg.spec_hash("EVS-20261101-0001") == spec_hash_of(spec)

    def test_field_change_changes_hash(self):
        h1 = spec_hash_of(make_spec())
        h2 = spec_hash_of(make_spec(version="1.1.0"))
        assert h1 != h2  # 任何字段变更 → 哈希变化

    def test_full_hash_differs_from_placeholder(self):
        spec = make_spec()
        assert spec_hash_of(spec) != spec_hash_placeholder(spec["spec_id"])

    def test_hash_deterministic_across_key_order(self):
        a = make_spec()
        b = {k: a[k] for k in reversed(list(a.keys()))}
        assert spec_hash_of(a) == spec_hash_of(b)  # 键序无关

    def test_register_freezes_spec(self):
        reg = SpecRegistry()
        spec = make_spec()
        reg.register(spec)
        spec["version"] = "9.9.9"  # 外部修改不影响已登记内容
        assert reg.resolve("EVS-20261101-0001")["version"] == "1.0.0"


class TestFileSpecRegistry:
    def test_load_list_form(self, tmp_path):
        path = tmp_path / "specs.json"
        path.write_text(json.dumps([make_spec()]), encoding="utf-8")
        reg = FileSpecRegistry(path)
        assert len(reg) == 1

    def test_load_specs_key_form(self, tmp_path):
        path = tmp_path / "specs.json"
        path.write_text(json.dumps({"specs": [make_spec()]}), encoding="utf-8")
        reg = FileSpecRegistry(path)
        assert len(reg) == 1

    def test_missing_file_rejected(self, tmp_path):
        with pytest.raises(SpecRegistryError, match="文件不存在"):
            FileSpecRegistry(tmp_path / "nope.json")


class TestGatewayIntegration:
    def _make_gateway(self, spec_registry=None):
        from core.gateway import InMemoryEvalRequestStore

        store = InMemoryEvalRequestStore()
        categories = CategoriesConfig.load()
        return Gateway(store, categories, spec_registry=spec_registry), store

    def _payload(self, spec_id="EVS-20261101-0001"):
        return {
            "object_ref": "git://repo/strategy@abc000",
            "category": "finance",
            "object_type": "strategy",
            "submitter": "test",
            "purpose": "l0_settle",
            "spec_id": spec_id,
            "env_manifest": {
                "runtime": "docker",
                "endpoints": ["http://127.0.0.1:9000/health"],
                "resources": [],
            },
        }

    def test_submit_with_registry_uses_full_hash(self):
        reg = SpecRegistry()
        reg.register(make_spec())
        gw, _ = self._make_gateway(reg)
        result = gw.submit(self._payload(), idempotency_key="k-1")
        assert result.spec_hash == spec_hash_of(make_spec())

    def test_submit_unregistered_spec_rejected(self):
        reg = SpecRegistry()  # 空 注册表
        gw, _ = self._make_gateway(reg)
        with pytest.raises(SpecRegistryError, match="spec 未注册"):
            gw.submit(self._payload(), idempotency_key="k-1")

    def test_submit_without_registry_keeps_placeholder(self):
        gw, _ = self._make_gateway()  # 未提供注册表 → 向后兼容
        result = gw.submit(self._payload(), idempotency_key="k-1")
        assert result.spec_hash == spec_hash_placeholder("EVS-20261101-0001")
