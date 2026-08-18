# Task7 发布前门禁与灰度（含 pytest 稳定性治理）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 P0 主链路上线前门禁与灰度机制，并修复 `pytest tests -q` 长跑挂起问题，确保提测可重复、可回滚、可审计。

**Architecture:** 采用“测试稳定性治理 + 发布门禁脚本 + 灰度开关”三段式方案。先把挂起源从测试集剥离并改造成可控超时/可注入依赖，再将关键验收命令固化为发布前门禁，最后以灰度开关控制 `/fundamental` 新增字段对下游影响。

**Tech Stack:** pytest、Python 3.10+、Flask/FastAPI 现有后端、Node 脚本（multi-agent bridge）、shell 门禁脚本。

---

## File Structure

- Modify: `tests/test_web3_market_digest_automation.py`
- Create: `tests/test_web3_market_digest_automation_fast.py`
- Create: `ops/nanoclaw/core_task1/scripts/pre_release_gate.sh`
- Modify: `ops/launchd/fundamental_stack.sh`
- Modify: `backend/src/_embedded_ml_trade_service_source.py`
- Modify: `SKILL集成技术文档.md`
- Modify: `基本面研究文档.md`

---

### Task 7.1: 稳定性定位与快照基线固化

**Files:**
- Modify: `SKILL集成技术文档.md`
- Test: `tests/test_web3_market_digest_automation.py`

- [ ] **Step 1: 写失败观察记录**

在文档新增“稳定性基线”小节，记录逐文件超时探测结果（`test_web3_market_digest_automation.py` 超时）。

- [ ] **Step 2: 运行验证命令确认现象仍可复现**

Run:
`pytest tests/test_web3_market_digest_automation.py -q`

Expected:
在当前环境可能出现长时间阻塞或超时。

- [ ] **Step 3: 固化可重放探测命令**

```bash
python -c "import subprocess, pathlib, json, time; root=pathlib.Path('.'); files=sorted((root/'tests').glob('test_*.py')); res=[]; \
for p in files: \
 t=time.time(); \
 try: subprocess.run(['pytest', str(p), '-q'], cwd=root, timeout=20, check=False, capture_output=True, text=True); res.append((p.name,'ok',round(time.time()-t,2))); \
 except subprocess.TimeoutExpired: res.append((p.name,'timeout',round(time.time()-t,2))); \
print(json.dumps(res, ensure_ascii=False))"
```

- [ ] **Step 4: 记录结果并确认通过**

Expected:
能稳定识别阻塞文件，输出机器可读 JSON。

- [ ] **Step 5: Commit**

```bash
git add SKILL集成技术文档.md
git commit -m "docs(task7): record pytest stability baseline and timeout probe"
```

---

### Task 7.2: 将阻塞测试改造成可控快速测试

**Files:**
- Create: `tests/test_web3_market_digest_automation_fast.py`
- Modify: `tests/test_web3_market_digest_automation.py`

- [ ] **Step 1: 写失败测试（快速版）**

```python
def test_fundamental_overview_latest_fast_path():
    import ml_trade_service as svc
    c = svc.app.test_client()
    r = c.get("/fundamental/overview/latest")
    assert r.status_code == 200
```

- [ ] **Step 2: 运行快速测试确认失败（若存在导入副作用）**

Run:
`pytest tests/test_web3_market_digest_automation_fast.py::test_fundamental_overview_latest_fast_path -v`

Expected:
若失败，通常是导入时副作用或读取外部依赖阻塞。

- [ ] **Step 3: 最小实现（隔离外部依赖）**

通过 monkeypatch 注入：
- `_fundamental_*_pick_*` 文件读取函数返回 `None`
- `_fundamental_trading_advice_latest` 返回最小字典

并将原长跑用例打标记：

```python
import pytest
pytestmark = pytest.mark.slow
```

- [ ] **Step 4: 重跑并确认通过**

Run:
`pytest tests/test_web3_market_digest_automation_fast.py -q`

Expected:
PASS 且耗时 < 2s。

- [ ] **Step 5: Commit**

```bash
git add tests/test_web3_market_digest_automation.py tests/test_web3_market_digest_automation_fast.py
git commit -m "test(task7): split slow digest tests and add fast deterministic overview checks"
```

---

### Task 7.3: 发布前门禁脚本

**Files:**
- Create: `ops/nanoclaw/core_task1/scripts/pre_release_gate.sh`
- Modify: `ops/launchd/fundamental_stack.sh`

- [ ] **Step 1: 写失败测试（脚本存在性与执行顺序）**

在 `tests/test_p1_structure_governance.py` 新增断言：
- `pre_release_gate.sh` 必须存在
- 包含顺序：schema/test/lint/compile

- [ ] **Step 2: 运行测试确认失败**

Run:
`pytest tests/test_p1_structure_governance.py -v`

- [ ] **Step 3: 最小实现门禁脚本**

```bash
set -euo pipefail
pytest tests/test_sync_web3_skill_snapshot_okx.py tests/test_okx_skill_collector.py tests/test_fundamental_overview_sources.py tests/test_p2_lifecycle_integration.py -q
python -m py_compile backend/src/_embedded_ml_trade_service_source.py backend/src/ml_trade_service.py
(cd frontend && npm run lint)
```

- [ ] **Step 4: 重跑测试确认通过**

Run:
`pytest tests/test_p1_structure_governance.py -v`

- [ ] **Step 5: Commit**

```bash
git add ops/nanoclaw/core_task1/scripts/pre_release_gate.sh ops/launchd/fundamental_stack.sh tests/test_p1_structure_governance.py
git commit -m "chore(task7): add pre-release gate script for p0 chain"
```

---

### Task 7.4: 灰度开关（source_summary / sourceCoverage）

**Files:**
- Modify: `backend/src/_embedded_ml_trade_service_source.py`

- [ ] **Step 1: 写失败测试（开关关闭时不输出新字段）**

在 `tests/test_fundamental_overview_sources.py` 新增：
- `FUNDAMENTAL_GRAY_V1=0` 时 `source_summary` 可选隐藏
- `FUNDAMENTAL_GRAY_V1=1` 时必须存在

- [ ] **Step 2: 运行测试确认失败**

Run:
`pytest tests/test_fundamental_overview_sources.py -v`

- [ ] **Step 3: 最小实现**

```python
gray_on = str(os.getenv("FUNDAMENTAL_GRAY_V1", "1")).strip() == "1"
if gray_on:
    rep["source_summary"] = source_summary
```

- [ ] **Step 4: 重跑测试确认通过**

Run:
`pytest tests/test_fundamental_overview_sources.py -v`

- [ ] **Step 5: Commit**

```bash
git add backend/src/_embedded_ml_trade_service_source.py tests/test_fundamental_overview_sources.py
git commit -m "feat(task7): add gray switch for overview source summary fields"
```

---

### Task 7.5: 最终回归与文档收口

**Files:**
- Modify: `SKILL集成技术文档.md`
- Modify: `基本面研究文档.md`

- [ ] **Step 1: 更新文档**

补充：
- Task7 门禁命令
- 灰度开关默认值与回滚策略
- 长跑测试拆分原则

- [ ] **Step 2: 运行发布前门禁**

Run:
`bash ops/nanoclaw/core_task1/scripts/pre_release_gate.sh`

Expected:
全部通过，退出码 0。

- [ ] **Step 3: 运行全量测试（允许 slow 分组单独执行）**

Run:
`pytest tests -q -m "not slow"`

Run:
`pytest tests -q -m slow --maxfail=1`

- [ ] **Step 4: Commit**

```bash
git add SKILL集成技术文档.md 基本面研究文档.md
git commit -m "docs(task7): publish gate and gray rollout acceptance summary"
```

---

## Spec Coverage Self-Check

- 发布前门禁：✅（脚本化 + 结构测试）
- 灰度控制：✅（字段可开关 + 可回滚）
- pytest 稳定性排查：✅（超时探测 + slow 拆分）
- 与 P0 约束一致性（readonly/fail-closed/coverage）：✅（无语义回退）
