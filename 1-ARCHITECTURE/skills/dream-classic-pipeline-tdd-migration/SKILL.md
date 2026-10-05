---
name: "dream-classic-pipeline-tdd-migration"
description: "Orchestrates Classic Pipeline C0-C8 nine-node TDD migration: RED test (assert real business logic) → GREEN impl (simplified extraction from ml_trade_service.py) → REFACTOR (full suite no regression) → E2E serial validation → frontend agent-browser acceptance. Invoke for classic pipeline node migration, C0-C8 TDD, node RED-GREEN-REFACTOR cycle, or frontend pipeline acceptance testing."
---

## Autonomy Boundary

可自主执行：
- 治理规则检查与合规报告
- SKILL 索引与生命周期管理
- 架构同步校验
- 代码审查与合并建议

需用户确认：
- 执行代码合并（merge 到主分支）
- 修改治理规则本身
- 执行系统级重启或部署

禁止：
- 未经审查直接合并到主分支
- 修改核心治理规则而不经过审批


# Dream Classic Pipeline C0-C8 TDD Migration

Orchestrates the complete TDD migration of Classic Pipeline's 9 nodes (C0 EnvScan → C8 PerfAttribution) from skeleton stubs to real business logic.

## When to Invoke

- Migrating a new C-chain node (C0-C8) from skeleton to real implementation
- User mentions "classic pipeline migration", "C0-C8 TDD", "node RED-GREEN-REFACTOR"
- Adding a new stage to the classic pipeline with TDD discipline
- Frontend acceptance testing of the classic pipeline (agent-browser)

## Prerequisites

- Node skeleton files exist at `1-ARCHITECTURE/dreamos/capabilities/trading/nodes/c{x}_xxx.py` (execute_core returns empty NodeResult)
- Spec contract defined at `.trae/documents/classic-pipeline-c0-c8-node-spec.md`
- Source logic in `10-经典指标系统/ml_trade_service.py` (89000+ lines)

## TDD Migration Cycle (Per Node)

### Step 1: recall (Hard Constraint)

```
recall(context="C{x} {node_name} TDD migration business logic", top_k=5, min_quality="C")
```

### Step 2: RED — Write Failing Tests

File: `1-ARCHITECTURE/dreamos/capabilities/trading/nodes/tests/test_c{x}_xxx_real.py`

Test categories (minimum 15-25 tests per node):
1. **Contract tests**: import, node_id, chain, tags, BaseNode subclass
2. **FAIL-OPEN tests**: no market → SUCCESS+empty outputs; no upstream → SUCCESS+empty outputs
3. **Output contract tests**: required output fields present and correct types
4. **Business logic tests**: real computation results match expected values
5. **Edge case tests**: single symbol, mixed directions, missing fields, zero values
6. **Data flow tests**: upstream outputs correctly consumed

Key fixture pattern:
```python
def _make_state(
    upstream_outputs: dict | None = None,
    with_upstream: bool = True,
    market_data: dict | None = None,
    config: dict | None = None,
) -> State:
    state = State()
    state.config = config or {}
    state.market = {"market_data": market_data or {...}}
    if with_upstream:
        state.results["C{x-1}"] = NodeResult(
            node_id="C{x-1}", status=NodeStatus.SUCCESS,
            outputs=upstream_outputs or _make_default_upstream(),
        )
    return state
```

Fixture gotcha: use `if x is None else x` not `x or default` — empty dict `{}` is falsy and would be replaced by default.

Run RED: confirm most tests fail (skeleton returns empty outputs).

### Step 3: GREEN — Implement Real Business Logic

File: `1-ARCHITECTURE/dreamos/capabilities/trading/nodes/c{x}_xxx.py`

**Simplification strategy** (critical — source file too complex for direct extraction):
- Do NOT depend on global CONFIG / UNIVERSE_STATE / pandas / freqtrade
- All inputs via `state.market` + `state.config` + `state.get_result("C{x-1}").outputs`
- No market or no upstream → return `NodeStatus.SUCCESS` + empty outputs (FAIL-OPEN)
- Use lightweight algorithms based on `market_data` fields (trend, rsi, momentum, price)

Implementation skeleton:
```python
class CxXxxNode(BaseNode):
    node_id = "C{x}"
    chain = "C"
    tags = ["classic", "classic_v2", ...]

    def execute_core(self, state: State) -> NodeResult:
        # 1. FAIL-OPEN: no market → empty
        if not isinstance(state.market, dict):
            return NodeResult(node_id="C{x}", status=NodeStatus.SUCCESS,
                              confidence=0.0, outputs={...empty...},
                              error="C{x} 无 market 数据")

        # 2. FAIL-OPEN: no upstream → empty
        upstream = state.get_result("C{x-1}")
        if upstream is None or not upstream.outputs:
            return NodeResult(..., error="C{x} 无 C{x-1} 上游结果")

        # 3. Business logic (simplified)
        ...

        # 4. Return real outputs
        return NodeResult(node_id="C{x}", status=NodeStatus.SUCCESS,
                          confidence=..., outputs={...real...})
```

Run GREEN: all tests pass.

### Step 4: REFACTOR — Full Suite No Regression

```bash
cd 1-ARCHITECTURE && PYTHONPATH=$PWD python -m pytest dreamos/capabilities/trading/nodes/tests/ --tb=short
```

Confirm: previous tests still pass + new node tests pass.

## Node Contracts (C0-C8)

| Node | Outputs Key Fields | Simplification Strategy |
|------|-------------------|------------------------|
| C0 EnvScan | env_state, regime, macro_flags | btc_trend + btc_volatility → regime classification |
| C1 SymbolFilter | candidates, filter_log, rejected | _build_universe_stage_a + relax ladder + fallback |
| C2 SignalDetect | signals, signal_count, dominant_direction | trend direction + rsi/momentum correction → LONG/SHORT |
| C3 BacktestVerify | verified_signals, win_rate, sharpe, max_dd | confidence + trend/momentum → simulated win rate |
| C4 RiskAssess | position_size, stop_loss, take_profit, risk_budget | capital*risk/(price*sl_pct), max_budget scaling |
| C5 ParamOptimize | optimized_params, improvement_pct, optimization_log | confidence+win_rate → param micro-tuning |
| C6 PlanGenerate | trade_plan, changeset, strategy_name, trace_id | aggregate C4+C5+C3 → plan, uuid4 trace |
| C7 ExecMonitor | exec_status, filled_orders, alerts, exec_log | market_data price = fill price, slippage alerts |
| C8 PerfAttribution | pnl_attribution, lessons, memory_feedback | closed_trades pnl aggregation by symbol/direction |

## State Class API

```python
state.market          # dict, contains market_data, portfolio_state, etc.
state.config          # dict, configurable thresholds
state.results         # dict[str, NodeResult], keyed by node_id
state.get_result("C3")  # → NodeResult or None
state.get_result("C3").outputs  # → dict of node outputs
state.update(node_id, result)   # write result into state
state.trace           # list of execution step records
```

## E2E Serial Validation

File: `tests/test_classic_pipeline_real_e2e.py`

Construct complete `market` + `config` covering all 9 nodes' input needs, serial execute C0→C8, assert:
1. All 9 nodes return SUCCESS
2. Data flows correctly (C1 candidates ⊆ C0 universe, C6 symbols ⊆ C4 position_size, etc.)
3. trace_id propagates C6→C7→C8
4. Final C8 pnl_attribution total matches expected

## Frontend Acceptance (agent-browser)

### Backend: IPC Handler

File: `dream-harness-bridge/packages/python-server/server.py`

Add `_handle_run_classic_pipeline(params)`:
- Construct default market+config (if not provided)
- Serial execute C0→C8 via `node.execute(state)` + `state.update()`
- Return `{phases: [{phase, status, outputs, confidence}], trace_id}`

Register in method dispatch: `elif method == "run_classic_pipeline": result = _handle_run_classic_pipeline(params)`

### Frontend: Store + Panel

File: `3.1-FRONTEND/src/stores/classic-store.ts`

Add `runFullPipeline()` async method:
- Set all 9 phases to `running`
- Try fetch backend HTTP API → fallback to mock data (same data structure)
- Update each phase sequentially with 300ms delay for visual effect
- Set `isRunning` flag to prevent double-execution

File: `3.1-FRONTEND/src/components/features/classic/ClassicPhasePanel.tsx`

Replace `runPhase` button with `runFullPipeline` ("执行流水线" button).

### Browser Verification

```bash
agent-browser open http://localhost:3001/dashboard/classic
agent-browser wait --load networkidle
agent-browser snapshot -i  # find "执行流水线" button ref
agent-browser click @e13    # click execute
agent-browser wait 5000
agent-browser screenshot /tmp/classic-result.png
```

Verify: 9 phase progress bars all turn green (done), C8 shows pnl_attribution JSON output.

## Test Statistics Reference

| Node | Test Count |
|------|-----------|
| C0 | 9 |
| C1 | 13 |
| C2 | 18 |
| C3 | 15 |
| C4 | 16 |
| C5 | 13 |
| C6 | 28 |
| C7 | 24 |
| C8 | 25 |
| E2E | 24 |
| **Total** | **215** |

## Common Pitfalls

1. **Fixture falsy trap**: `position_size or {default}` replaces empty `{}` with default. Use `if x is None else x`.
2. **Import pollution**: python-server stdout contains DreamOS import noise. Filter for `schema_version + message_type='response'` JSON lines.
3. **Circular dependency**: C6 needs C3+C4+C5 simultaneously. All upstream results accumulate in `state.results`, access via `state.get_result("Cx")`.
4. **trace_id propagation**: C6 generates uuid4, C7 must read from C6 outputs and write to C7 exec_log, C8 must read from C7 exec_log.
5. **FAIL-OPEN not FAIL-STOP**: nodes return SUCCESS+empty (not FAILED) when upstream missing, so pipeline doesn't break on degraded data.

## Cognitive Closure

After completing all 9 nodes:
1. `recall` before starting (hard constraint)
2. `record` experience after finishing (if DB writable)
3. `verify` if prior memory validated
4. **hermes reflection**: this workflow reused 9 times + multi-step orchestration + bsk automation → SKILL-worthy
