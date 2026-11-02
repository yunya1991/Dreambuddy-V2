# 4-MEMORY 测试失败案例登记（2026-11-02 排查 → 2026-11-02 修复完成）

> **背景**: P0（M1）验收过程中对 4-MEMORY/9-工具与接口/tests/ 全量回归，发现 12 项失败 + 2 项收集错误。已确认均与 M1② 统一信封改造无关（信封相关 6 项已同步修复：test_mcp_recall_processes 3 项 + test_tag_hooks 3 项）。
> **修复状态**: **全部 14 项（12 失败 + 2 收集错误）已修复并验证通过**。
> **验收证据**（云端 `/home/luke/venv-trading/bin/python -m pytest`，仓属主 luke）:
> - 6 个目标文件：`26 passed in 1.63s`（exit 0）
> - 模块全量：`285 passed, 12 warnings in 5.14s`（exit 0）

## 一、失败清单与根因（已修复）

### 1. test_quarantine_recall.py（4 项）— 隔离区子系统缺失 ✅ 已修复

| 测试 | 失败点 | 修复 |
|---|---|---|
| test_recall_excludes_quarantined_by_default | cle._quarantine 不存在 | 新增 QuarantineManager + 默认过滤隔离态 |
| test_recall_include_quarantined | 同上 | recall 新增 include_quarantined 参数 |
| test_restore_from_quarantine_resets_confidence | 方法缺失 | 新增 restore_from_quarantine（恢复 C 档 + confidence 0.4） |
| test_quarantine_status | 方法缺失 | 新增 quarantine_status（quarantined_count） |

**根因**: CognitiveLoopEntry 中从未实现隔离区子系统（TDD RED 阶段遗留）；向量接口仅在 `_QUALITY_ORDER` 里把 quarantined 定义为 rank=9（与 archived 同级）。

**修复实现**（`cognitive_loop_entry.py` / `vector_memory_interface.py`）:
- 新增 `QuarantineManager`（quarantine / is_quarantined / restore / count / status），基于 `update_quality(memory_id, "quarantined", 0.0)` 实现；
- `CognitiveLoopEntry.__init__` 挂载 `self._quarantine`；
- `recall(..., include_quarantined=False)`：默认路径在质量过滤后再按 memories 实时 `quality_level` 兜底排除 quarantined；`include_quarantined=True` 时改为不带质量过滤的 search（避免 sqlite-vec 的 `vec_memories.quality` 写入快照导致隔离记忆被误判）；
- 新增 `restore_from_quarantine()` 与 `quarantine_status()`。

**关键坑**: sqlite-vec 的 `vec_memories.quality` 是**写入时快照**，`update_quality()` 不同步该虚拟表，因此隔离判定必须以 `memories` 表实时 `quality_level` 为准。

### 2. test_vector_transaction_discipline.py（5 项）— 事务纪律缺失 ✅ 已修复

| 测试 | 原失败点 | 修复 |
|---|---|---|
| test_wal_mode_enabled_on_file_db | journal_mode=delete | 文件库初始化设 `PRAGMA journal_mode=WAL` |
| test_busy_timeout_at_least_30s | busy_timeout=5000 | 初始化设 `PRAGMA busy_timeout=30000` |
| test_add_rollback_on_failure | 失败后 in_transaction=True | add() 内 try/except rollback + raise |
| test_update_quality_rollback_on_failure | 同上 | update_quality() 同上 |
| test_delete_rollback_on_failure | 同上 | delete() 同上 |

**根因**: VectorMemoryInterface 未设置事务纪律 PRAGMA，且三个写入方法异常路径缺少显式 rollback（连接残留事务）。

**修复实现**: 新增 `_apply_tx_pragmas()`（FAIL-OPEN：PRAGMA 设置失败仅记日志不阻塞初始化；`:memory:` 跳过 WAL），在 `_select_engine()` 之后、`_init_schema()` 之前调用（sqlite-vec 可能替换连接对象，PRAGMA 必须作用于最终连接）；`add()` / `update_quality()` / `delete()` 的写事务整体包 `try/except: rollback(); raise`。

### 3. test_f3_noise_penalty.py（2 项）— 噪音惩罚被 PoE 降权叠加 ✅ 已修复

| 测试 | 原失败点 | 修复 |
|---|---|---|
| test_f3_noise_records_are_penalized | 噪音未被 ×0.5 | fixture 关闭 PoE 降权 |
| test_f3_valid_records_not_penalized | 有效记忆 ratio ≤ 0.9 | 同上 |

**根因**: 非代码缺陷。测试构造的记忆无 receipt，PoE soft 模式额外 ×0.5，与 F3 噪音惩罚 ×0.5 **正交叠加**（噪音 0.4949→0.1237，有效 0.1715→0.0858），导致比例断言失真。

**修复实现**: `tests/test_f3_noise_penalty.py` fixture 增加 `poe_enforcement="off"`，隔离被测维度（F3 评分），不改变生产默认行为（默认仍为 soft）。

### 4. test_skill_loader.py（1 项）— 技能数量硬编码漂移 ✅ 已修复

| 测试 | 原失败点 | 修复 |
|---|---|---|
| test_index_cache_rebuild_md5_match | 断言技能数 14，实际 15 | 三处硬编码 14 改为动态 `len(loader2.skills)` |

**根因**: 技能库新增 1 条技能，测试硬编码数量过期。

**修复实现**: 改为从 loader 实际加载结果推导 `expected_count`，避免后续技能增删再次漂移。

## 二、收集错误（2 项）✅ 已修复

| 文件 | 错误 | 状态 |
|---|---|---|
| test_final_signoff.py | ModuleNotFoundError: No module named 'scripts.final_signoff' | 已修复 |
| test_gray_release_checklist.py | ModuleNotFoundError: No module named 'scripts.gray_release_checklist' | 已修复 |

**根因（真实根因，非"路径不可达"）**: `11-易经推理系统/scripts` 是**常规包**（含 `__init__.py`），而本目录 `scripts/` 与仓库根 `scripts/` 都是**命名空间包**（无 `__init__.py`）。按 PEP 420，常规包优先于命名空间包；仓库根 `conftest.py` 把 `11-易经推理系统` 注入 `sys.path` 后，pytest 进程内 `import scripts` 命中常规包，本目录的 `scripts.final_signoff` 因此不可见（即便本目录已在 `sys.path[0]`、`scripts_dir_exists=True`）。

**修复实现**: 两个测试文件在 import 前显式注册命名空间包：`sys.modules["scripts"]` 若不存在/无 `__path__` 则创建 `types.ModuleType` 并置 `__path__`，按当前 `sys.path` 顺序收集所有 `scripts` 目录（本目录脚本目录置首位），复现无遮蔽时的命名空间解析语义；同时删除排查期临时 DEBUG print。

## 三、附带修复（环境性，非本次登记项）

全量回归时 `tests/test_quarantined_state.py` 3 项因 `PermissionError` 失败：`4-MEMORY/1-开发记忆单元/solution_paths/` 下部分测试产物（APP-neg/APP-track/APP-bad 等）与多批 `__pycache__/*.pyc` 为 **root 属主**（此前有人以 root 身份跑过测试）。已清理残留文件并对 `4-MEMORY` 下 root 属主对象执行 `chown luke:luke`，回归转绿。

**硬约束（沉淀）**: 云端跑 4-MEMORY 测试必须使用 `/home/luke/venv-trading/bin/python`，且**必须** `sudo -n -u luke -H` 执行；禁止以 root 身份直接跑测试（会在 `4-MEMORY` 下留下 root 属主产物，导致后续 PermissionError）。

## 四、最终验收

```text
# 6 个目标文件
26 passed in 1.63s      (exit 0)

# 模块全量回归
285 passed, 12 warnings in 5.14s   (exit 0)
```

- 12 项失败 + 2 项收集错误：**0 残留**
- 无新增回归（全量 285 项全绿）
- 变更文件: `vector_memory_interface.py`、`cognitive_loop_entry.py`、`tests/test_f3_noise_penalty.py`、`tests/test_skill_loader.py`、`tests/test_final_signoff.py`、`tests/test_gray_release_checklist.py`

## 五、环境备注

- 测试运行环境: `/home/luke/venv-trading/bin/python`（含 sqlite_vec v0.1.9）
- 系统 python3 无 sqlite_vec，会导致 recall 回退 numpy（单次 8-13 秒），测试务必用 venv-trading
- `-q` 是 `pyproject.toml` 中 addopts 的既有项，命令行再叠加 `-q` 会变成 `-qq` 并**吞掉** "N passed" 汇总行，取证时不要重复加 `-q`
