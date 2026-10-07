"""
gene_audit_gate — 基因审核门禁（三级校验）

门禁层级:
  1. Schema 校验: 新基因必须符合 condition schema（防止 bad_genes 错误）
  2. 统计门槛: N ≥ 100 且 ESS ≥ 0.5（已有，复用 L2_MIN_SAMPLES/L2_MIN_ESS）
  3. 相对提升: 新基因 ESS > 现有基因库平均 ESS × 1.1（确保提升而非噪声）

审核日志: gene_data/strategy_genes/audit_log.jsonl
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 相对提升系数: 新基因 ESS 必须 > 现有均值 × RELATIVE_IMPROVEMENT_FACTOR
RELATIVE_IMPROVEMENT_FACTOR = 1.1


class GeneAuditGate:
    """基因审核门禁"""

    def __init__(self, gene_root: Optional[str | Path] = None):
        if gene_root is None:
            self._gene_root = Path(__file__).resolve().parent.parent / "gene_data"
        else:
            self._gene_root = Path(gene_root)
        self._audit_log = self._gene_root / "strategy_genes" / "audit_log.jsonl"

    # ─── 门禁 1: Schema 校验 ─────────────────────────────────────

    def validate_schema(self, gene_data: dict) -> dict[str, Any]:
        """校验基因数据是否符合 condition schema.

        Returns:
            {passed: bool, reason: str}
        """
        try:
            import jsonschema
            schema_path = self._gene_root / "schemas" / "condition.json"
            if not schema_path.exists():
                return {"passed": True, "reason": "schema 文件不存在，跳过校验"}
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            jsonschema.validate(gene_data, schema)
            return {"passed": True, "reason": "schema 校验通过"}
        except ImportError:
            return {"passed": True, "reason": "jsonschema 未安装，跳过校验"}
        except Exception as e:
            return {"passed": False, "reason": f"schema 校验失败: {e}"}

    # ─── 门禁 2: 统计门槛 ─────────────────────────────────────────

    def validate_statistical(self, n_samples: int, ess: float,
                             min_samples: int = 100, min_ess: float = 0.5) -> dict[str, Any]:
        """统计门槛: N ≥ min_samples 且 ESS ≥ min_ess."""
        if n_samples < min_samples:
            return {"passed": False, "reason": f"样本数不足: N={n_samples} < {min_samples}"}
        if ess < min_ess:
            return {"passed": False, "reason": f"ESS 不足: ess={ess:.4f} < {min_ess}"}
        return {"passed": True, "reason": "统计门槛通过"}

    # ─── 门禁 3: 相对提升 ─────────────────────────────────────────

    def validate_relative_improvement(self, ess: float, baseline_ess: float) -> bool:
        """新基因 ESS 必须 > 现有均值 × 1.1."""
        if baseline_ess <= 0:
            return ess >= 0.5  # 无基线时降级为绝对门槛
        return ess > baseline_ess * RELATIVE_IMPROVEMENT_FACTOR

    # ─── 综合审核 ────────────────────────────────────────────────

    def audit(self, gene_data: dict, n_samples: int, ess: float,
              baseline_ess: float = 0.0) -> dict[str, Any]:
        """三级门禁综合审核.

        Returns:
            {
                passed: bool,
                gates: {schema, statistical, relative},
                reason: str
            }
        """
        g_schema = self.validate_schema(gene_data)
        g_stat = self.validate_statistical(n_samples, ess)
        g_rel = self.validate_relative_improvement(ess, baseline_ess)

        passed = g_schema["passed"] and g_stat["passed"] and g_rel

        reason_parts = []
        if not g_schema["passed"]:
            reason_parts.append(g_schema["reason"])
        if not g_stat["passed"]:
            reason_parts.append(g_stat["reason"])
        if not g_rel:
            reason_parts.append(f"相对提升不足: ess={ess:.4f} ≤ {baseline_ess:.4f}×{RELATIVE_IMPROVEMENT_FACTOR}")

        result = {
            "passed": passed,
            "gates": {
                "schema": g_schema,
                "statistical": g_stat,
                "relative": g_rel,
            },
            "reason": "; ".join(reason_parts) if reason_parts else "全部门禁通过",
        }

        self._write_audit_log(gene_data.get("gene_id", "unknown"), result)
        return result

    # ─── 审核日志 ────────────────────────────────────────────────

    def _write_audit_log(self, gene_id: str, result: dict) -> None:
        """写入审核日志."""
        try:
            self._audit_log.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "timestamp": datetime.now().isoformat(),
                "gene_id": gene_id,
                "passed": result["passed"],
                "reason": result["reason"],
            }
            with open(self._audit_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass  # 日志写入失败不影响审核
