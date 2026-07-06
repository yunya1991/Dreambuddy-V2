# Trading Scheduler P0 Implementation Plan
 
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
 
**Goal:** 在主干新增可直接运行的 GitHub Actions 定时调度层，落地 A1-A3 阶梯与 A4/A5/A6/A8 定时触发，并确保“同 run 内触发下游阶段”的执行能力与产物留痕。
 
**Architecture:** 新增 5 个独立 workflow（schedule + workflow_dispatch）。每个 workflow 用 Python 内联脚本动态加载现有 `workflows/trading-decision/*` 模块并调用入口函数/编排器；所有输出统一写入 `artifacts/trading/` 并上传 artifact；不依赖跨 workflow dispatch。
 
**Tech Stack:** GitHub Actions, Python 3.11, pytest, Python stdlib (`importlib.util`, `json`, `pathlib`)
 
---
 
## Files Overview
 
**Create (workflows):**
 
- `.github/workflows/trading-ladder-a1-a3.yml`
- `.github/workflows/trading-a4-validation.yml`
- `.github/workflows/trading-a5-execution.yml`
- `.github/workflows/trading-a6-intelligence.yml`
- `.github/workflows/trading-a8-governance.yml`
 
**Create (tests):**
 
- `tests/test_ci_trading_scheduler_workflows_p0.py`
 
**Modify (CI gate):**
 
- `.github/workflows/safe-main-merge-gate.yml`（把新测试纳入 PR Gate Checks）
 
---
 
### Task 1: Add scheduler workflow for A1→A2→A3 ladder (Beijing 00:00)
 
**Files:**
 
- Create: `.github/workflows/trading-ladder-a1-a3.yml`
- Test: `tests/test_ci_trading_scheduler_workflows_p0.py`
 
- [ ] **Step 1: Write the failing test for ladder workflow presence + cron**
 
Add a test that asserts the workflow file exists and contains the expected UTC cron (`0 16 * * *`) and `workflow_dispatch`.
 
```python
from pathlib import Path
 
 
def _read(rel: str) -> str:
    root = Path(__file__).resolve().parents[1]
    return (root / rel).read_text(encoding="utf-8")
 
 
def test_trading_ladder_workflow_exists_and_has_cron():
    text = _read(".github/workflows/trading-ladder-a1-a3.yml")
    assert 'name: Trading Ladder A1-A3' in text
    assert "workflow_dispatch:" in text
    assert 'cron: "0 16 * * *"' in text
```
 
- [ ] **Step 2: Run test to verify it fails**
 
Run: `PYTHONPATH=. pytest -q tests/test_ci_trading_scheduler_workflows_p0.py::test_trading_ladder_workflow_exists_and_has_cron`  
Expected: FAIL with file not found.
 
- [ ] **Step 3: Create `.github/workflows/trading-ladder-a1-a3.yml`**
 
Use this workflow content (note: cron is UTC aligned for Beijing 00:00, and the job runs A1→A2→A3 in one run with shared `trace_id`).
 
```yaml
name: Trading Ladder A1-A3
 
on:
  workflow_dispatch:
    inputs:
      signals_json:
        description: 'JSON array of signals, e.g. ["macro"]'
        required: false
        default: '["macro"]'
      confidence:
        description: "A1 confidence (0-1)"
        required: false
        default: "0.8"
  schedule:
    - cron: "0 16 * * *"
 
permissions:
  contents: read
 
concurrency:
  group: trading-ladder-a1-a3-${{ github.ref }}
  cancel-in-progress: false
 
jobs:
  ladder:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
 
      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
 
      - name: Run A1 -> A2 -> A3 ladder
        run: |
          python - <<'PY'
          import importlib.util
          import json
          from pathlib import Path
 
          root = Path.cwd()
          trace_id = f"trade-{__import__('os').environ.get('GITHUB_RUN_ID','local')}"
 
          def load(path: Path, name: str):
              spec = importlib.util.spec_from_file_location(name, path)
              module = importlib.util.module_from_spec(spec)
              assert spec and spec.loader
              spec.loader.exec_module(module)
              return module
 
          a1 = load(root / "workflows" / "trading-decision" / "A1_research" / "entrypoint.py", "a1_entry")
          a2 = load(root / "workflows" / "trading-decision" / "A2_first-principles" / "entrypoint.py", "a2_entry")
          a3 = load(root / "workflows" / "trading-decision" / "A3_simulation" / "entrypoint.py", "a3_entry")
 
          signals_json = """${{ github.event.inputs.signals_json || '' }}""".strip() or '["macro"]'
          confidence = float("""${{ github.event.inputs.confidence || '' }}""".strip() or "0.8")
 
          payload = {
              "trace_id": trace_id,
              "signals": json.loads(signals_json),
              "confidence": confidence,
              "rsi": 52,
              "funding_rate": 0.0,
              "fgi": 55,
              "signal_score": 62,
              "volatility": 0.02,
              "market_regime": "trend",
          }
 
          out_dir = root / "artifacts" / "trading"
          out_dir.mkdir(parents=True, exist_ok=True)
 
          a1_out = a1.run_a1_research(payload, output_dir=out_dir)
          a2_out = a2.run_a2_first_principles({**payload, **a1_out.get("payload", {})}, output_dir=out_dir)
          a3_out = a3.run_a3_simulation({**payload, **a2_out.get("payload", {})}, output_dir=out_dir)
          print("trace_id:", trace_id)
          print("A1 header:", a1_out.get("header", {}))
          print("A2 header:", a2_out.get("header", {}))
          print("A3 header:", a3_out.get("header", {}))
          PY
 
      - name: Upload trading artifacts
        uses: actions/upload-artifact@v4
        with:
          name: trading-ladder-a1-a3-${{ github.run_id }}
          path: artifacts/trading/*.json
          if-no-files-found: error
```
 
- [ ] **Step 4: Run test to verify it passes**
 
Run: `PYTHONPATH=. pytest -q tests/test_ci_trading_scheduler_workflows_p0.py::test_trading_ladder_workflow_exists_and_has_cron`  
Expected: PASS.
 
- [ ] **Step 5: Commit**
 
```bash
git add .github/workflows/trading-ladder-a1-a3.yml tests/test_ci_trading_scheduler_workflows_p0.py
git commit -m "ci(trading): add A1-A3 ladder scheduler workflow"
```
 
---
 
### Task 2: Add scheduler workflow for A4 (4h) with same-run A5 trigger on PASS
 
**Files:**
 
- Create: `.github/workflows/trading-a4-validation.yml`
- Test: `tests/test_ci_trading_scheduler_workflows_p0.py`
 
- [ ] **Step 1: Write failing test for A4 workflow cron + naming**
 
```python
def test_trading_a4_workflow_exists_and_has_cron():
    text = _read(".github/workflows/trading-a4-validation.yml")
    assert 'name: Trading A4 Validation' in text
    assert 'cron: "0 */4 * * *"' in text
```
 
- [ ] **Step 2: Run the test to see it fail**
 
Run: `PYTHONPATH=. pytest -q tests/test_ci_trading_scheduler_workflows_p0.py::test_trading_a4_workflow_exists_and_has_cron`  
Expected: FAIL.
 
- [ ] **Step 3: Create `.github/workflows/trading-a4-validation.yml`**
 
```yaml
name: Trading A4 Validation
 
on:
  workflow_dispatch:
    inputs:
      max_drawdown_pct:
        description: "Max drawdown percent"
        required: false
        default: "1.2"
      position_ratio:
        description: "Position ratio (0-1)"
        required: false
        default: "0.25"
      stop_loss_pct:
        description: "Stop loss percent"
        required: false
        default: "1.5"
      run_a5_on_pass:
        description: "Run A5 if risk_gate == PASS"
        required: false
        default: "true"
  schedule:
    - cron: "0 */4 * * *"
 
permissions:
  contents: read
 
concurrency:
  group: trading-a4-validation-${{ github.ref }}
  cancel-in-progress: false
 
jobs:
  a4:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
 
      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
 
      - name: Run A4 (and A5 when PASS)
        run: |
          python - <<'PY'
          import importlib.util
          from pathlib import Path
 
          root = Path.cwd()
          trace_id = f"trade-{__import__('os').environ.get('GITHUB_RUN_ID','local')}"
 
          def load(path: Path, name: str):
              spec = importlib.util.spec_from_file_location(name, path)
              module = importlib.util.module_from_spec(spec)
              assert spec and spec.loader
              spec.loader.exec_module(module)
              return module
 
          a4 = load(root / "workflows" / "trading-decision" / "A4_validation" / "entrypoint.py", "a4_entry")
          a5 = load(root / "workflows" / "trading-decision" / "A5_execution" / "entrypoint.py", "a5_entry")
 
          max_dd = float("""${{ github.event.inputs.max_drawdown_pct || '' }}""".strip() or "1.2")
          pos_ratio = float("""${{ github.event.inputs.position_ratio || '' }}""".strip() or "0.25")
          stop_loss = float("""${{ github.event.inputs.stop_loss_pct || '' }}""".strip() or "1.5")
          run_a5 = ("""${{ github.event.inputs.run_a5_on_pass || '' }}""".strip() or "true").lower() == "true"
 
          out_dir = root / "artifacts" / "trading"
          out_dir.mkdir(parents=True, exist_ok=True)
 
          payload = {
              "trace_id": trace_id,
              "max_drawdown_pct": max_dd,
              "position_ratio": pos_ratio,
              "stop_loss_pct": stop_loss,
              "direction": "LONG",
              "entry_price": 65000,
              "leverage": 2,
          }
 
          a4_out = a4.run_a4_validation(payload, output_dir=out_dir)
          a4_payload = a4_out.get("payload", {})
          print("A4 risk_gate:", a4_payload.get("risk_gate"))
 
          if run_a5 and a4_payload.get("risk_gate") == "PASS":
              a5_out = a5.run_a5_execution({**payload, **a4_payload}, output_dir=out_dir)
              print("A5 status:", a5_out.get("payload", {}).get("execution_status", "OK"))
          PY
 
      - name: Upload trading artifacts
        uses: actions/upload-artifact@v4
        with:
          name: trading-a4-validation-${{ github.run_id }}
          path: artifacts/trading/*.json
          if-no-files-found: error
```
 
- [ ] **Step 4: Run tests**
 
Run: `PYTHONPATH=. pytest -q tests/test_ci_trading_scheduler_workflows_p0.py::test_trading_a4_workflow_exists_and_has_cron`  
Expected: PASS.
 
- [ ] **Step 5: Commit**
 
```bash
git add .github/workflows/trading-a4-validation.yml tests/test_ci_trading_scheduler_workflows_p0.py
git commit -m "ci(trading): add A4 scheduler workflow"
```
 
---
 
### Task 3: Add scheduler workflow for A5 (8h) with same-run A6 notification
 
**Files:**
 
- Create: `.github/workflows/trading-a5-execution.yml`
- Test: `tests/test_ci_trading_scheduler_workflows_p0.py`
 
- [ ] **Step 1: Write failing test**
 
```python
def test_trading_a5_workflow_exists_and_has_cron():
    text = _read(".github/workflows/trading-a5-execution.yml")
    assert 'name: Trading A5 Execution' in text
    assert 'cron: "0 */8 * * *"' in text
```
 
- [ ] **Step 2: Run it (expect fail)**
 
Run: `PYTHONPATH=. pytest -q tests/test_ci_trading_scheduler_workflows_p0.py::test_trading_a5_workflow_exists_and_has_cron`
 
- [ ] **Step 3: Create `.github/workflows/trading-a5-execution.yml`**
 
```yaml
name: Trading A5 Execution
 
on:
  workflow_dispatch:
    inputs:
      direction:
        description: "Direction LONG/SHORT"
        required: false
        default: "LONG"
      entry_price:
        description: "Entry price"
        required: false
        default: "65000"
      leverage:
        description: "Leverage"
        required: false
        default: "2"
  schedule:
    - cron: "0 */8 * * *"
 
permissions:
  contents: read
 
concurrency:
  group: trading-a5-execution-${{ github.ref }}
  cancel-in-progress: false
 
jobs:
  a5:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
 
      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
 
      - name: Run A5 (and notify A6)
        run: |
          python - <<'PY'
          import importlib.util
          from pathlib import Path
 
          root = Path.cwd()
          trace_id = f"trade-{__import__('os').environ.get('GITHUB_RUN_ID','local')}"
 
          def load(path: Path, name: str):
              spec = importlib.util.spec_from_file_location(name, path)
              module = importlib.util.module_from_spec(spec)
              assert spec and spec.loader
              spec.loader.exec_module(module)
              return module
 
          a5 = load(root / "workflows" / "trading-decision" / "A5_execution" / "entrypoint.py", "a5_entry")
          a6 = load(root / "workflows" / "trading-decision" / "A6_intelligence" / "entrypoint.py", "a6_entry")
 
          direction = ("""${{ github.event.inputs.direction || '' }}""".strip() or "LONG").upper()
          entry_price = float("""${{ github.event.inputs.entry_price || '' }}""".strip() or "65000")
          leverage = int("""${{ github.event.inputs.leverage || '' }}""".strip() or "2")
 
          out_dir = root / "artifacts" / "trading"
          out_dir.mkdir(parents=True, exist_ok=True)
 
          payload = {
              "trace_id": trace_id,
              "direction": direction,
              "entry_price": entry_price,
              "leverage": leverage,
          }
 
          a5_out = a5.run_a5_execution(payload, output_dir=out_dir)
          a5_payload = a5_out.get("payload", {})
 
          a6_in = {
              "trace_id": trace_id,
              "alerts": [
                  {
                      "risk_score": 0.0,
                      "regime_change": False,
                      "theory_practice_score": 1.0,
                  }
              ],
              "signal_shift": 0.0,
          }
          a6_out = a6.run_a6_intelligence(a6_in, output_dir=out_dir)
          print("A5 header:", a5_out.get("header", {}))
          print("A6 route_summary:", a6_out.get("payload", {}).get("route_summary", {}))
          PY
 
      - name: Upload trading artifacts
        uses: actions/upload-artifact@v4
        with:
          name: trading-a5-execution-${{ github.run_id }}
          path: artifacts/trading/*.json
          if-no-files-found: error
```
 
- [ ] **Step 4: Run tests (expect pass)**
 
Run: `PYTHONPATH=. pytest -q tests/test_ci_trading_scheduler_workflows_p0.py::test_trading_a5_workflow_exists_and_has_cron`
 
- [ ] **Step 5: Commit**
 
```bash
git add .github/workflows/trading-a5-execution.yml tests/test_ci_trading_scheduler_workflows_p0.py
git commit -m "ci(trading): add A5 scheduler workflow"
```
 
---
 
### Task 4: Add scheduler workflow for A6 (1h) with same-run trigger execution
 
**Files:**
 
- Create: `.github/workflows/trading-a6-intelligence.yml`
- Test: `tests/test_ci_trading_scheduler_workflows_p0.py`
 
- [ ] **Step 1: Write failing test**
 
```python
def test_trading_a6_workflow_exists_and_has_cron():
    text = _read(".github/workflows/trading-a6-intelligence.yml")
    assert 'name: Trading A6 Intelligence' in text
    assert 'cron: "0 * * * *"' in text
```
 
- [ ] **Step 2: Run it (expect fail)**
 
Run: `PYTHONPATH=. pytest -q tests/test_ci_trading_scheduler_workflows_p0.py::test_trading_a6_workflow_exists_and_has_cron`
 
- [ ] **Step 3: Create `.github/workflows/trading-a6-intelligence.yml`**
 
```yaml
name: Trading A6 Intelligence
 
on:
  workflow_dispatch:
    inputs:
      risk_score:
        description: "risk_score (0-1), drives L0/L1/L2"
        required: false
        default: "0.0"
      regime_change:
        description: "true/false, drives L1.5"
        required: false
        default: "false"
      theory_practice_score:
        description: "drives L3 when < 0.7"
        required: false
        default: "1.0"
  schedule:
    - cron: "0 * * * *"
 
permissions:
  contents: read
 
concurrency:
  group: trading-a6-intelligence-${{ github.ref }}
  cancel-in-progress: false
 
jobs:
  a6:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
 
      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
 
      - name: Run A6 and execute routed stages in same run
        run: |
          python - <<'PY'
          import importlib.util
          from pathlib import Path
 
          root = Path.cwd()
          trace_id = f"trade-{__import__('os').environ.get('GITHUB_RUN_ID','local')}"
 
          def load(path: Path, name: str):
              spec = importlib.util.spec_from_file_location(name, path)
              module = importlib.util.module_from_spec(spec)
              assert spec and spec.loader
              spec.loader.exec_module(module)
              return module
 
          a1 = load(root / "workflows" / "trading-decision" / "A1_research" / "entrypoint.py", "a1_entry")
          a2 = load(root / "workflows" / "trading-decision" / "A2_first-principles" / "entrypoint.py", "a2_entry")
          a3 = load(root / "workflows" / "trading-decision" / "A3_simulation" / "entrypoint.py", "a3_entry")
          a4 = load(root / "workflows" / "trading-decision" / "A4_validation" / "entrypoint.py", "a4_entry")
          a5 = load(root / "workflows" / "trading-decision" / "A5_execution" / "entrypoint.py", "a5_entry")
          a6 = load(root / "workflows" / "trading-decision" / "A6_intelligence" / "entrypoint.py", "a6_entry")
          a9 = load(root / "workflows" / "trading-decision" / "A9_exit" / "entrypoint.py", "a9_entry")
 
          out_dir = root / "artifacts" / "trading"
          out_dir.mkdir(parents=True, exist_ok=True)
 
          risk_score = float("""${{ github.event.inputs.risk_score || '' }}""".strip() or "0.0")
          regime_change = ("""${{ github.event.inputs.regime_change || '' }}""".strip() or "false").lower() == "true"
          theory_practice_score = float("""${{ github.event.inputs.theory_practice_score || '' }}""".strip() or "1.0")
 
          a6_in = {
              "trace_id": trace_id,
              "alerts": [
                  {
                      "risk_score": risk_score,
                      "regime_change": regime_change,
                      "theory_practice_score": theory_practice_score,
                  }
              ],
              "signal_shift": 0.0,
          }
          a6_out = a6.run_a6_intelligence(a6_in, output_dir=out_dir)
          routed = list(a6_out.get("payload", {}).get("routed_events", []))
          print("route_summary:", a6_out.get("payload", {}).get("route_summary", {}))
 
          base_payload = {
              "trace_id": trace_id,
              "signals": ["macro"],
              "confidence": 0.8,
              "rsi": 52,
              "funding_rate": 0.0,
              "fgi": 55,
              "signal_score": 62,
              "volatility": 0.02,
              "market_regime": "trend",
              "max_drawdown_pct": 1.2,
              "position_ratio": 0.25,
              "stop_loss_pct": 1.5,
              "direction": "LONG",
              "entry_price": 65000,
              "leverage": 2,
              "unrealized_pnl_pct": 1.0,
              "risk_level": "low",
          }
 
          for msg in routed:
              tgt = str((msg.get("header") or {}).get("target") or "")
              if tgt == "A2":
                  a2_out = a2.run_a2_first_principles(base_payload, output_dir=out_dir)
                  a3.run_a3_simulation({**base_payload, **a2_out.get("payload", {})}, output_dir=out_dir)
              elif tgt == "A4":
                  a4_out = a4.run_a4_validation(base_payload, output_dir=out_dir)
                  if a4_out.get("payload", {}).get("risk_gate") == "PASS":
                      a5.run_a5_execution({**base_payload, **a4_out.get("payload", {})}, output_dir=out_dir)
              elif tgt == "A9":
                  a9.run_a9_exit(base_payload, output_dir=out_dir)
              elif tgt == "A1":
                  a1.run_a1_research(base_payload, output_dir=out_dir)
              elif tgt == "A3":
                  a3.run_a3_simulation(base_payload, output_dir=out_dir)
              else:
                  print("OBSERVE:", tgt)
          PY
 
      - name: Upload trading artifacts
        uses: actions/upload-artifact@v4
        with:
          name: trading-a6-intelligence-${{ github.run_id }}
          path: artifacts/trading/*.json
          if-no-files-found: error
```
 
- [ ] **Step 4: Run tests (expect pass)**
 
Run: `PYTHONPATH=. pytest -q tests/test_ci_trading_scheduler_workflows_p0.py::test_trading_a6_workflow_exists_and_has_cron`
 
- [ ] **Step 5: Commit**
 
```bash
git add .github/workflows/trading-a6-intelligence.yml tests/test_ci_trading_scheduler_workflows_p0.py
git commit -m "ci(trading): add A6 scheduler workflow"
```
 
---
 
### Task 5: Add scheduler workflow for A8 governance loop (Beijing 14:00)
 
**Files:**
 
- Create: `.github/workflows/trading-a8-governance.yml`
- Test: `tests/test_ci_trading_scheduler_workflows_p0.py`
 
- [ ] **Step 1: Write failing test for A8 cron (UTC 06:00)**
 
```python
def test_trading_a8_workflow_exists_and_has_cron():
    text = _read(".github/workflows/trading-a8-governance.yml")
    assert 'name: Trading A8 Governance' in text
    assert 'cron: "0 6 * * *"' in text
```
 
- [ ] **Step 2: Run it (expect fail)**
 
Run: `PYTHONPATH=. pytest -q tests/test_ci_trading_scheduler_workflows_p0.py::test_trading_a8_workflow_exists_and_has_cron`
 
- [ ] **Step 3: Create `.github/workflows/trading-a8-governance.yml`**
 
```yaml
name: Trading A8 Governance
 
on:
  workflow_dispatch:
    inputs:
      hypothesis_score:
        description: "A8 hypothesis_score"
        required: false
        default: "0.8"
      practice_score:
        description: "A8 practice_score"
        required: false
        default: "0.8"
  schedule:
    - cron: "0 6 * * *"
 
permissions:
  contents: read
 
concurrency:
  group: trading-a8-governance-${{ github.ref }}
  cancel-in-progress: false
 
jobs:
  gov:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
 
      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
 
      - name: Run governance loop A7 -> A8 -> A1/A2/A3
        run: |
          python - <<'PY'
          import importlib.util
          from pathlib import Path
 
          root = Path.cwd()
          trace_id = f"trade-{__import__('os').environ.get('GITHUB_RUN_ID','local')}"
 
          def load(path: Path, name: str):
              spec = importlib.util.spec_from_file_location(name, path)
              module = importlib.util.module_from_spec(spec)
              assert spec and spec.loader
              spec.loader.exec_module(module)
              return module
 
          gov = load(root / "workflows" / "trading-decision" / "orchestrator" / "governance_loop.py", "gov_loop")
 
          out_dir = root / "artifacts" / "trading"
          out_dir.mkdir(parents=True, exist_ok=True)
 
          hypothesis_score = float("""${{ github.event.inputs.hypothesis_score || '' }}""".strip() or "0.8")
          practice_score = float("""${{ github.event.inputs.practice_score || '' }}""".strip() or "0.8")
 
          payload = {
              "trace_id": trace_id,
              "hypothesis_score": hypothesis_score,
              "practice_score": practice_score,
          }
          out = gov.run_governance_loop(payload, output_dir=out_dir)
          print("visited:", out.get("visited_stages"))
          print("reputation:", out.get("reputation"))
          PY
 
      - name: Upload trading artifacts
        uses: actions/upload-artifact@v4
        with:
          name: trading-a8-governance-${{ github.run_id }}
          path: artifacts/trading/*.json
          if-no-files-found: error
```
 
- [ ] **Step 4: Run tests (expect pass)**
 
Run: `PYTHONPATH=. pytest -q tests/test_ci_trading_scheduler_workflows_p0.py::test_trading_a8_workflow_exists_and_has_cron`
 
- [ ] **Step 5: Commit**
 
```bash
git add .github/workflows/trading-a8-governance.yml tests/test_ci_trading_scheduler_workflows_p0.py
git commit -m "ci(trading): add A8 scheduler workflow"
```
 
---
 
### Task 6: Wire new scheduler tests into PR Gate
 
**Files:**
 
- Modify: `.github/workflows/safe-main-merge-gate.yml`
- Test: `tests/test_ci_trading_scheduler_workflows_p0.py`
 
- [ ] **Step 1: Ensure the scheduler test file covers all 5 workflows**
 
Add one aggregate test to reduce omission risk:
 
```python
def test_all_trading_scheduler_workflows_present():
    required = [
        ".github/workflows/trading-ladder-a1-a3.yml",
        ".github/workflows/trading-a4-validation.yml",
        ".github/workflows/trading-a5-execution.yml",
        ".github/workflows/trading-a6-intelligence.yml",
        ".github/workflows/trading-a8-governance.yml",
    ]
    root = Path(__file__).resolve().parents[1]
    missing = [p for p in required if not (root / p).exists()]
    assert not missing, f"missing workflows: {missing}"
```
 
- [ ] **Step 2: Run the full test file locally**
 
Run: `PYTHONPATH=. pytest -q tests/test_ci_trading_scheduler_workflows_p0.py`  
Expected: PASS.
 
- [ ] **Step 3: Update Safe Main Merge Gate to run the new test**
 
Add the file to the existing “Run trading system loop gate tests” step:
 
```yaml
      - name: Run trading system loop gate tests
        run: |
          pytest tests/test_ci_trading_scheduler_workflows_p0.py \
            tests/test_trading_protocol_fail_closed_p0.py \
            tests/test_trading_governance_orchestrator_p1.py \
            tests/test_trading_system_loop_e2e_p1p2.py \
            tests/test_trading_replay_observability_p2.py \
            tests/test_trading_memory_l4_contract_e2e.py \
            tests/test_ci_trading_traceability_guard.py \
            ... -q
```
 
- [ ] **Step 4: Commit**
 
```bash
git add .github/workflows/safe-main-merge-gate.yml tests/test_ci_trading_scheduler_workflows_p0.py
git commit -m "test(trading): gate trading scheduler workflows"
```
 
---
 
### Task 7: PR, CI verification, and manual workflow_dispatch smoke
 
**Files:**
 
- All above
 
- [ ] **Step 1: Open PR**
 
```bash
git push -u origin feature/trading-scheduler-p0
gh pr create --base main --head feature/trading-scheduler-p0 --title "ci(trading): add P0 trading schedulers" --body "Adds scheduled workflows for A1-A3 ladder and A4/A5/A6/A8. Same-run triggers; artifacts under artifacts/trading."
```
 
- [ ] **Step 2: Wait for PR Gate Checks**
 
Run: `gh pr view --json statusCheckRollup -q .statusCheckRollup`  
Expected: scheduler workflow tests included and PASS.
 
- [ ] **Step 3: Manual smoke via workflow_dispatch**
 
Trigger each workflow once:
 
```bash
gh workflow run "Trading Ladder A1-A3" -f signals_json='["macro"]' -f confidence=0.8
gh workflow run "Trading A4 Validation" -f max_drawdown_pct=1.2 -f position_ratio=0.25 -f stop_loss_pct=1.5 -f run_a5_on_pass=true
gh workflow run "Trading A5 Execution" -f direction=LONG -f entry_price=65000 -f leverage=2
gh workflow run "Trading A6 Intelligence" -f risk_score=0.0 -f regime_change=false -f theory_practice_score=1.0
gh workflow run "Trading A8 Governance" -f hypothesis_score=0.8 -f practice_score=0.8
```
 
- [ ] **Step 4: Verify artifacts exist**
 
For each run, download artifacts and confirm `artifacts/trading/*.json` exists.
 
- [ ] **Step 5: Merge PR**
 
```bash
gh pr merge --merge --delete-branch
```
 
---
 
## Self-Review Checklist
 
- Spec coverage: A1-A3 00:00 北京时间、A4 4h、A5 8h、A6 1h、A8 14:00 北京时间全部有 workflow 与 cron
- No placeholders: plan 中每个新增文件都给出完整 YAML/测试/命令
- Cron correctness: Beijing 00:00 -> UTC 16:00；Beijing 14:00 -> UTC 06:00
- Same-run triggers: A4->A5、A5->A6、A6->A2/A4/A9/A1/A3、A8->治理环编排均覆盖
 
