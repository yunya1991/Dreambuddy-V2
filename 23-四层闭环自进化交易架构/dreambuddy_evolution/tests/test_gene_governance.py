"""TDD-GENE-GOV: 基因创新版本控制+审核门禁测试."""
import json
import os
import tempfile
from pathlib import Path


def test_gene_version_snapshot():
    """GeneVersionManager 应能快照当前基因库."""
    from dreambuddy_evolution.adapters.gene_version_manager import GeneVersionManager
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # 创建模拟基因库
        cond_dir = root / "strategy_genes" / "conditions"
        cond_dir.mkdir(parents=True)
        (cond_dir / "CD-TEST.json").write_text(json.dumps({"gene_id": "CD-TEST"}))
        (cond_dir / "CD-TEST2.json").write_text(json.dumps({"gene_id": "CD-TEST2"}))

        mgr = GeneVersionManager(root / "strategy_genes")
        version_id = mgr.snapshot(trigger_source="test")
        assert version_id is not None
        versions = mgr.list_versions()
        assert len(versions) >= 1
        assert versions[0]["version_id"] == version_id
        assert versions[0]["n_genes"] == 2


def test_gene_version_rollback():
    """GeneVersionManager 应能回滚到指定版本."""
    from dreambuddy_evolution.adapters.gene_version_manager import GeneVersionManager
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cond_dir = root / "strategy_genes" / "conditions"
        cond_dir.mkdir(parents=True)
        (cond_dir / "CD-ORIGINAL.json").write_text(json.dumps({"gene_id": "CD-ORIGINAL"}))

        mgr = GeneVersionManager(root / "strategy_genes")
        v1 = mgr.snapshot("initial")

        # 修改基因库（删除一个基因）
        (cond_dir / "CD-ORIGINAL.json").unlink()
        (cond_dir / "CD-NEW.json").write_text(json.dumps({"gene_id": "CD-NEW"}))

        # 回滚
        assert mgr.rollback(v1) is True
        assert (cond_dir / "CD-ORIGINAL.json").exists()
        assert not (cond_dir / "CD-NEW.json").exists()


def test_gene_audit_schema_validation():
    """GeneAuditGate 应校验基因 schema."""
    from dreambuddy_evolution.adapters.gene_audit_gate import GeneAuditGate
    gate = GeneAuditGate()

    valid_gene = {
        "gene_id": "CD-TEST-VALID",
        "category": "momentum",
        "condition_type": "indicator",
        "expression": "vol_ratio > 1.3",
        "parameters": {"vol": {"value": 1.3, "range": {"low": 1.0, "high": 3.0}}},
        "code_ref": {"file": "test.py", "lines": {"low": 1, "high": 10}},
        "version": "1.0",
    }
    result = gate.validate_schema(valid_gene)
    assert result["passed"] is True

    # 额外字段应失败
    invalid_gene = {**valid_gene, "description": "extra field"}
    result2 = gate.validate_schema(invalid_gene)
    assert result2["passed"] is False


def test_gene_audit_relative_improvement():
    """GeneAuditGate 应校验相对提升."""
    from dreambuddy_evolution.adapters.gene_audit_gate import GeneAuditGate
    gate = GeneAuditGate()

    # ESS > 均值×1.1 → 通过
    assert gate.validate_relative_improvement(ess=0.6, baseline_ess=0.5) is True
    # ESS ≤ 均值×1.1 → 拒绝
    assert gate.validate_relative_improvement(ess=0.5, baseline_ess=0.5) is False
    assert gate.validate_relative_improvement(ess=0.54, baseline_ess=0.5) is False


def test_gene_innovation_with_audit():
    """GeneInnovationEngine 写入前应通过审核门禁+快照."""
    from dreambuddy_evolution.adapters.ftc_gene_innovation import GeneInnovationEngine, GeneCandidate
    with tempfile.TemporaryDirectory() as tmp:
        engine = GeneInnovationEngine(gene_root=tmp)
        cand = GeneCandidate(
            gene_id="CD-AUDIT-TEST",
            gene_type="condition",
            category="momentum",
            condition_type="indicator",
            description="test",
            expression="vol_ratio > 1.3",
            parameters={"vol": {"value": 1.3, "range": {"low": 1.0, "high": 3.0}}},
            source="test",
            tags=["test"],
        )
        # N 不足 → 拒绝
        assert engine.validate_candidate("CD-AUDIT-TEST", n_samples=50, ess=0.6) is False
        # N 足够但 ESS 不足 → 拒绝
        assert engine.validate_candidate("CD-AUDIT-TEST", n_samples=100, ess=0.4) is False
        # 都满足 → 通过
        assert engine.validate_candidate("CD-AUDIT-TEST", n_samples=100, ess=0.6) is True


def test_agi_config_gene_innovation_switch():
    """agi_config 应有 enable_gene_innovation 开关."""
    from dreambuddy_evolution.agi_config import AGI_SWITCHES
    assert "enable_gene_innovation" in AGI_SWITCHES
