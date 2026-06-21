# BTC Skill P0 覆盖率补齐（OKX 主源 + Gate/Binance 交叉兜底）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有基本面系统中完成 P0 集成：OKX `market-intel` + `cmc-okx` + `alpha-vantage` + `hyperliquid-analyzer` 作为 BTC 主源，Gate/Binance 作为交叉验证与兜底，输出可被 `/fundamental/*` 与多 Agent 消费的统一产物。

**Architecture:** 采用 Hub + 标准化架构：Skill 采集层写入 raw，标准化层映射为 `source_snapshot_v1`，研究层合成为 flow/narrative/macro 特征，Hub 层执行质量与覆盖率门禁并输出只读建议。保持 `execution_gate=readonly_advisory`，任何缺失或冲突触发 fail-closed。

**Tech Stack:** Python 3.10+（采集/标准化/测试），FastAPI（现有后端接口），JSON Schema（契约校验），pytest（回归测试）。

---

## File Structure（先锁定边界）

- Create: `ops/nanoclaw/core_task1/flow/scripts/okx_skill_collector.py`
- Create: `ops/nanoclaw/core_task1/schema/source_snapshot_v1.schema.json`
- Create: `ops/nanoclaw/core_task1/schema/feature_cube_v1.schema.json`
- Create: `shared/okx_flow_schema_map.json`
- Create: `tests/test_okx_skill_collector.py`
- Create: `tests/test_sync_web3_skill_snapshot_okx.py`
- Modify: `ops/nanoclaw/core_task1/flow/scripts/sync_web3_skill_snapshot.py`
- Modify: `backend/src/_embedded_ml_trade_service_source.py`
- Modify: `backend/src/ml_trade_service.py`（仅在必要时添加轻量包装，不改执行语义）
- Modify: `ops/nanoclaw/core_task1/scripts/multi_agent_bridge.mjs`
- Modify: `基本面研究文档.md`（补 P0 实施记录与字段口径）

---

### Task 1: 定义 OKX P0 数据契约与映射表

**Files:**
- Create: `ops/nanoclaw/core_task1/schema/source_snapshot_v1.schema.json`
- Create: `ops/nanoclaw/core_task1/schema/feature_cube_v1.schema.json`
- Create: `shared/okx_flow_schema_map.json`
- Test: `tests/test_sync_web3_skill_snapshot_okx.py`

- [ ] **Step 1: 写失败测试（schema 最小约束）**

```python
import json
from pathlib import Path

def test_source_snapshot_schema_has_required_fields():
    p = Path("ops/nanoclaw/core_task1/schema/source_snapshot_v1.schema.json")
    obj = json.loads(p.read_text(encoding="utf-8"))
    required = set(obj.get("required", []))
    assert {"schema", "asset", "asof_ts", "items", "execution_gate"} <= required
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_sync_web3_skill_snapshot_okx.py::test_source_snapshot_schema_has_required_fields -v`  
Expected: FAIL（文件不存在或 required 字段缺失）

- [ ] **Step 3: 实现最小 schema 与映射文件**

```json
{
  "type": "object",
  "required": ["schema", "asset", "asof_ts", "items", "execution_gate"]
}
```

```json
[
  { "key": "funding_rate_bps", "bindBase": "funding_rate_bps__btc__okx__perp" },
  { "key": "oi_usd", "bindBase": "oi_usd__btc__okx__perp" },
  { "key": "spread_bps", "bindBase": "spread_bps__btc__okx__spot" },
  { "key": "market_intel_heat", "bindBase": "social_heat_event_score__btc__okx__na" },
  { "key": "macro_pressure_score", "bindBase": "macro_event_pressure_score__btc__macro__na" },
  { "key": "whale_position_delta_usd", "bindBase": "whale_position_delta_usd__btc__hyperliquid__perp" }
]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_sync_web3_skill_snapshot_okx.py::test_source_snapshot_schema_has_required_fields -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ops/nanoclaw/core_task1/schema/source_snapshot_v1.schema.json ops/nanoclaw/core_task1/schema/feature_cube_v1.schema.json shared/okx_flow_schema_map.json tests/test_sync_web3_skill_snapshot_okx.py
git commit -m "feat(schema): add source snapshot and feature cube v1 contracts for okx p0"
```

---

### Task 2: 新增 OKX Skill 采集脚本（raw 落盘）

**Files:**
- Create: `ops/nanoclaw/core_task1/flow/scripts/okx_skill_collector.py`
- Test: `tests/test_okx_skill_collector.py`

- [ ] **Step 1: 写失败测试（采集输出结构）**

```python
from ops.nanoclaw.core_task1.flow.scripts.okx_skill_collector import build_snapshot_stub

def test_build_snapshot_stub_contains_p0_sources():
    out = build_snapshot_stub(asset="BTC")
    assert out["asset"] == "BTC"
    assert "okx:market-intel" in out["sources"]
    assert "okx:cmc-okx" in out["sources"]
    assert "okx:alpha-vantage" in out["sources"]
    assert "okx:hyperliquid-analyzer" in out["sources"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_okx_skill_collector.py::test_build_snapshot_stub_contains_p0_sources -v`  
Expected: FAIL（模块或函数不存在）

- [ ] **Step 3: 实现最小可运行采集器（先 stub + raw 写盘）**

```python
def build_snapshot_stub(asset: str = "BTC") -> dict:
    return {
        "schema": "okx_skill_raw_bundle_v1",
        "asset": asset,
        "sources": [
            "okx:market-intel",
            "okx:cmc-okx",
            "okx:alpha-vantage",
            "okx:hyperliquid-analyzer",
        ],
        "payload": {},
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_okx_skill_collector.py::test_build_snapshot_stub_contains_p0_sources -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ops/nanoclaw/core_task1/flow/scripts/okx_skill_collector.py tests/test_okx_skill_collector.py
git commit -m "feat(flow): add okx p0 skill collector scaffold with raw bundle output"
```

---

### Task 3: 扩展标准化脚本支持 OKX 四类 skill 输入

**Files:**
- Modify: `ops/nanoclaw/core_task1/flow/scripts/sync_web3_skill_snapshot.py`
- Test: `tests/test_sync_web3_skill_snapshot_okx.py`

- [ ] **Step 1: 写失败测试（新增 mode）**

```python
from ops.nanoclaw.core_task1.flow.scripts.sync_web3_skill_snapshot import _marketoverview_items

def test_okx_modes_generate_bindbase_items():
    raw = {"funding_rate_bps": 10, "oi_usd": 1000000}
    rows = _marketoverview_items(raw)
    assert isinstance(rows, list)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_sync_web3_skill_snapshot_okx.py::test_okx_modes_generate_bindbase_items -v`  
Expected: FAIL（函数/模式未覆盖 OKX）

- [ ] **Step 3: 最小实现（新增 mode 与映射函数）**

```python
parser.add_argument("--mode", choices=[
  "items", "coinanalysis", "gate-info-research", "gate-info-marketoverview",
  "okx-market-intel", "okx-cmc-okx", "okx-alpha-vantage", "okx-hyperliquid-analyzer"
])
```

```python
elif args.mode == "okx-cmc-okx":
    items = _okx_cmc_okx_items(raw)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_sync_web3_skill_snapshot_okx.py -v`  
Expected: PASS（至少覆盖新增 mode 的 bindBase 产出）

- [ ] **Step 5: Commit**

```bash
git add ops/nanoclaw/core_task1/flow/scripts/sync_web3_skill_snapshot.py tests/test_sync_web3_skill_snapshot_okx.py
git commit -m "feat(flow): normalize okx p0 skill payloads into source snapshot items"
```

---

### Task 4: 后端聚合 `/fundamental/*` 增加 OKX 主源与交叉验证摘要

**Files:**
- Modify: `backend/src/_embedded_ml_trade_service_source.py`
- Modify: `backend/src/ml_trade_service.py`（如需暴露包装函数）
- Test: `tests/test_web3_market_digest_automation.py`（新增用例）

- [ ] **Step 1: 写失败测试（overview 返回 p0 数据来源）**

```python
def test_fundamental_overview_contains_okx_p0_sources(client):
    r = client.get("/fundamental/overview/latest")
    j = r.json()
    src = j.get("source_summary", {})
    assert "okx:market-intel" in src.get("primary_sources", [])
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_web3_market_digest_automation.py::test_fundamental_overview_contains_okx_p0_sources -v`  
Expected: FAIL（字段不存在或源未接入）

- [ ] **Step 3: 最小实现（聚合逻辑）**

```python
source_summary = {
  "primary_sources": ["okx:market-intel", "okx:cmc-okx", "okx:alpha-vantage", "okx:hyperliquid-analyzer"],
  "cross_validation": ["gate-info-research", "gate-info-coinanalysis", "binance:crypto-market-rank"],
  "fallback_enabled": True,
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_web3_market_digest_automation.py::test_fundamental_overview_contains_okx_p0_sources -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/_embedded_ml_trade_service_source.py backend/src/ml_trade_service.py tests/test_web3_market_digest_automation.py
git commit -m "feat(api): expose okx p0 source summary and cross-validation fallback in fundamental overview"
```

---

### Task 5: 多 Agent 桥接接入 P0 字段并保持 fail-closed

**Files:**
- Modify: `ops/nanoclaw/core_task1/scripts/multi_agent_bridge.mjs`
- Test: `tests/test_p2_lifecycle_integration.py`（新增桥接断言）

- [ ] **Step 1: 写失败测试（桥接输出新增宏观与主源覆盖）**

```python
def test_bridge_outputs_macro_pressure_and_source_coverage():
    payload = load_latest_bridge_payload()
    assert "macroPressure" in payload["fundamental"]
    assert "sourceCoverage" in payload["fundamental"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_p2_lifecycle_integration.py::test_bridge_outputs_macro_pressure_and_source_coverage -v`  
Expected: FAIL

- [ ] **Step 3: 最小实现（桥接字段映射）**

```javascript
fundamental.macroPressure = toNum(snapshotMacroPressure) ?? 0
fundamental.sourceCoverage = clamp01(toNum(hub.coverage) ?? 0)
if (fundamental.sourceCoverage < 0.55) {
  fundamental.fundamentalSignal = "neutral"
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_p2_lifecycle_integration.py::test_bridge_outputs_macro_pressure_and_source_coverage -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ops/nanoclaw/core_task1/scripts/multi_agent_bridge.mjs tests/test_p2_lifecycle_integration.py
git commit -m "feat(bridge): add okx p0 macro pressure and coverage-aware fail-closed mapping"
```

---

### Task 6: 端到端回归与文档落位

**Files:**
- Modify: `基本面研究文档.md`
- Modify: `SKILL集成技术文档.md`

- [ ] **Step 1: 更新文档中的 P0 执行状态与字段口径**

```markdown
### P0 执行状态（BTC）
- 主源：okx market-intel/cmc-okx/alpha-vantage/hyperliquid-analyzer
- 交叉验证：gate-info-research/gate-info-coinanalysis/binance crypto-market-rank
- 门禁：coverage<0.55 => fail-closed
```

- [ ] **Step 2: 运行完整测试集**

Run: `pytest tests -q`  
Expected: 全部 PASS

- [ ] **Step 3: 运行后端与前端基础校验**

Run: `python -m py_compile backend/src/_embedded_ml_trade_service_source.py backend/src/ml_trade_service.py`  
Expected: 无输出（成功）

Run: `cd frontend && npm run lint`  
Expected: `eslint` 通过

- [ ] **Step 4: Commit**

```bash
git add 基本面研究文档.md SKILL集成技术文档.md
git commit -m "docs(fundamental): record p0 okx-first rollout and operational gates"
```

---

## Spec Coverage Self-Check

- P0 主源（OKX 四个 skill）有独立采集、标准化、聚合、桥接任务：✅
- Gate/Binance 交叉验证与兜底在 Hub 输出中显式列出：✅
- 只读建议与 fail-closed 门禁在 schema、聚合与桥接三处落地：✅
- 下游多 Agent 消费路径保持兼容并新增字段：✅
- 文档同步与回归测试纳入 DoD：✅
