# Evolution P0 Contracts v0.1

## 1. Candidate Contract

### Required Fields

- `candidate_id`
- `trace_id`
- `constraint_version_base`
- `source_type` (`theory_practice` | `stats_evolution` | `dream_feedback` | `hybrid`)
- `source_refs[]`
- `hypothesis`
- `expected_effect`
- `risk_assessment`
- `evidence_refs[]`
- `schema_version`

### Example

```json
{
  "candidate_id": "cand-20260511-001",
  "trace_id": "trace-xyz-001",
  "constraint_version_base": "v0.1",
  "source_type": "hybrid",
  "source_refs": [
    "artifacts/memory/episode/ep_001.json",
    "artifacts/trading/a8_report_20260511.json"
  ],
  "hypothesis": "reduce false-positive entries by tightening regime filter",
  "expected_effect": "lower tail-loss frequency",
  "risk_assessment": {
    "risk_level": "medium",
    "main_risk": "under-trading in trend phase"
  },
  "evidence_refs": [
    "artifacts/evolution/feedback/evidence_pack_001.json"
  ],
  "schema_version": "evolution-p0-candidate-v0.1"
}
```

## 2. ValidationReport Contract

### Required Fields

- `candidate_id`
- `stage` (`audit` | `sandbox`)
- `pass`
- `metrics`
- `violations[]`
- `artifacts[]`
- `timestamp`

### Example

```json
{
  "candidate_id": "cand-20260511-001",
  "stage": "audit",
  "pass": true,
  "metrics": {
    "required_fields_coverage": 1.0,
    "evidence_ref_count": 1
  },
  "violations": [],
  "artifacts": [
    "artifacts/evolution/audit/audit_20260511_001.json"
  ],
  "timestamp": "2026-05-11T16:00:00Z"
}
```

## 3. PromotionRecord Contract

### Required Fields

- `candidate_id`
- `from_version`
- `to_version`
- `decision` (`approve` | `reject`)
- `rollback_pointer`
- `evidence_refs[]`
- `timestamp`

### Example

```json
{
  "candidate_id": "cand-20260511-001",
  "from_version": "v0.1",
  "to_version": "v0.1.1",
  "decision": "approve",
  "rollback_pointer": "constraints/releases/v0.1.json",
  "evidence_refs": [
    "artifacts/evolution/sandbox/sandbox_20260511_001.json"
  ],
  "timestamp": "2026-05-11T16:30:00Z"
}
```
