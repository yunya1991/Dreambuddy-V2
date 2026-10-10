# 方向1-2：REA设计增强自进化系统

> **来源**: REA逆向工程思维三方向调研（2026-10-10）
> **REA借鉴**: Provider确定性选择 + 洋葱架构 + Ownership纪律
> **目标系统**: 23-四层闭环自进化交易架构
> **状态**: 待实施

---

## 1. 现状分析

| REA设计原则 | 自进化系统现状 | 差距 |
|---|---|---|
| Provider确定性选择 | `PrimaryContradictionIdentifier.identify()` 三步法（共振检测→冲突裁决→主导性评估）自动选8路径（bdsm/trend_following/grid_trading/bcrm/strategic/deep_reasoning/synthesized/l2_gene → C1-C8），可能静默降级 | 无ambiguous机制，无显式选择，失败自动fallback |
| 洋葱架构（引擎协议不进domain） | `dreambuddy_evolution/` 有 core/engines/adapters 三层 | 需审计core是否被engines/adapters协议污染 |
| Ownership纪律（PID+path≠ownership） | `11-易经推理系统/scripts/memory_l4/polling_trader.py` 用 `fcntl.flock` 单例锁（L18087-18109） | 文件锁不是进程ownership，进程reuse后失效 |

---

## 2. 增强任务

### T2.1 Provider确定性选择 → PrimaryContradictionIdentifier（P1）

**目标**：多路径支持同一target时，不自动选，报ambiguous+列候选+显式选择+会话内不摇摆+运行时失败无fallback。

**涉及文件**：
- `23-四层闭环自进化交易架构/dreambuddy_evolution/core/contradiction_identifier.py`
- 类：`PrimaryContradictionIdentifier`，方法：`identify(paths, market_data, r_out, weight_factor, causal_engine, meta_cognition_gate)`

**改动**：在现有 `identify()` 方法基础上增加 `selection_policy` 参数（不改变现有方法签名，通过构造函数注入）：

```python
class PrimaryContradictionIdentifier:
    def __init__(self, weight_learner=None, selection_policy: str = "auto"):
        # 保留现有 weight_learner 注入
        self._weight_learner = weight_learner or ContradictionWeightLearner()
        # 新增：selection_policy = "auto"(现有三步法) / "explicit"(ambiguous报错)
        self.selection_policy = selection_policy
        self._selected_path: str | None = None  # 会话内锁定

    def identify(self, paths, market_data=None, r_out=None, weight_factor=1.0,
                 causal_engine=None, meta_cognition_gate=None) -> dict:
        # 新增：explicit 模式下的 ambiguous 检查（在现有三步法之前）
        if self.selection_policy == "explicit" and self._selected_path is None:
            candidates = self._get_candidates(paths)  # 从 paths 提取候选
            if len(candidates) > 1:
                return {
                    "status": "ambiguous",
                    "candidates": candidates,
                    "message": "多个路径可用，请显式选择后重试",
                }
            self._selected_path = candidates[0]
        # 选定后运行时失败不自动切换 → 返回 path_unavailable 而非 fallback
        ...
        # 后续保持现有三步法：_detect_resonance → _arbitrate_conflicts → _evaluate_dominance

    def select_path_explicit(self, path_name: str) -> None:
        """供上层显式选择路径，选择后会话内锁定。"""
        self._selected_path = path_name
```

**关键设计**：
- `selection_policy="auto"`（默认）保持现有三步法行为不变
- `selection_policy="explicit"` 启用REA模式：ambiguous报错+显式选择
- `_selected_path` 一旦设定，运行时失败返回 `path_unavailable` 而非fallback
- 提供 `select_path_explicit(path_name)` 方法供上层显式选择
- 不修改现有 `identify()` 方法签名，`selection_policy` 通过构造函数注入

**与现有 `identify()` 集成的具体改造点**：

1. **构造函数**（L216 `__init__`）：增加 `selection_policy: str = "auto"` 参数，初始化 `self._selected_path = None`
2. **`identify()` 方法开头**（L246 try之后，L247路径数检查之后）：插入 explicit 模式检查代码块
3. **新增 `_get_candidates(paths)` 方法**：从 `paths` 列表提取每个 path 的 `source` 字段，去重后作为候选列表
4. **运行时失败处理**：现有 `_arbitrate_conflicts` / `_evaluate_dominance` 若返回异常或无效结果，在 explicit 模式下返回 `{"status": "path_unavailable", "selected_path": self._selected_path}`，不回退到其他路径
5. **新增 `select_path_explicit(path_name)` 方法**：设置 `self._selected_path = path_name`，后续 `identify()` 调用跳过 ambiguous 检查
6. **FAIL-OPEN**：`selection_policy` 取值非法时默认 "auto"，不抛异常

**验收**：
- auto模式行为不变
- explicit模式下多候选返回ambiguous
- 选定后失败不fallback

### T2.2 洋葱架构审计（P2）

**目标**：确保 `dreambuddy_evolution/core/` 不 import `engines/` 或 `adapters/`，引擎协议不进domain层。

**涉及文件**：
- `dreambuddy_evolution/core/` 下所有模块

**审计方法**：
```bash
# 检查core是否import了engines或adapters
grep -rn "from.*engines\|import.*engines\|from.*adapters\|import.*adapters" dreambuddy_evolution/core/
```

**整改**：
- 若core有import engines/adapters，将协议相关代码移到adapters
- core层只保留抽象接口（Protocol/ABC）

**验收**：
- `core/` 下无 `import engines` 或 `import adapters`
- engines/adapters 依赖 core，反之不成立

### T2.3 Ownership纪律 → polling_trader（P2）

**目标**：PID+path≠ownership，用进程组+supervision建立真实ownership。

**涉及文件**：
- `11-易经推理系统/scripts/memory_l4/polling_trader.py`（L18087-18109 flock实现处）

**现状**：
- `fcntl.flock` 防止并发启动（文件锁）
- 但进程退出/reuse后PID可能被复用，无法证明ownership

**改动**：
```python
class ProcessOwnership:
    def __init__(self):
        self.lock_fd = None
        self.pgid = None  # 进程组ID

    def acquire(self) -> bool:
        # 1. flock 保留（防止并发启动）
        # 2. 建立进程组 ownership
        self.pgid = os.getpgid(os.getpid())
        # 3. 写入 pidfile: {pid, pgid, start_time, executable_path}
        ...

    def verify(self) -> bool:
        # 验证进程组成员，PID+path+pgid三重校验
        ...

    def release(self):
        # 只释放能证明拥有的资源
        ...
```

**关键设计**：
- 保留 `fcntl.flock`（防止并发启动的第一道防线）
- 增加进程组 `pgid` 验证（PID可复用，pgid+成员更可靠）
- pidfile 记录 `{pid, pgid, start_time, executable_path}`，重启时三重校验
- **从不杀死无法证明拥有的进程**（REA铁律）

**验收**：
- 启动后pidfile记录pid+pgid+start_time
- 健康检查验证进程组成员
- 重启时不杀无法证明ownership的进程

---

## 3. 与 33-REA 的关系

33-REA工程是REA设计理念的"正向落地"（构建逆向工程工具）。本任务清单是REA设计理念的"反向应用"（用REA的工程原则增强现有交易系统）。两者共享同一套设计哲学，但落地在不同系统。

---

## 4. 实施顺序（TDD）

每个任务遵循 **RED → GREEN → REFACTOR** 循环：

### T2.1 Provider确定性选择（P1，1天）
- **RED**：写测试断言 `PrimaryContradictionIdentifier(selection_policy="explicit").identify([2条以上不同source的paths])` 返回 `{"status": "ambiguous", ...}`
- **GREEN**：构造函数加 `selection_policy`，`identify()` 开头加 explicit 检查，新增 `_get_candidates` + `select_path_explicit`
- **REFACTOR**：explicit 检查逻辑提取为独立方法，不侵入三步法主体

### T2.2 洋葱架构审计（P2，0.5天）
- **RED**：写脚本断言 `core/` 下无 `import engines` / `import adapapters`
- **GREEN**：审计出违规清单，按清单分批整改
- **REFACTOR**：违规模块的协议代码移至 `adapters/`，core 只留抽象接口

### T2.3 Ownership纪律（P2，1天）
- **RED**：写测试断言 `ProcessOwnership.acquire()` 后 pidfile 包含 pid+pgid+start_time
- **GREEN**：新增 `ProcessOwnership` 类，集成到 polling_trader 启动流程
- **REFACTOR**：flock 保留为第一道防线，pgid 验证为增量

---

## 5. 风险

| 风险 | 应对 |
|---|---|
| explicit模式破坏现有调用方 | 默认auto模式，explicit需显式启用 |
| 洋葱架构审计发现大量违规 | 先审计出清单，整改分批进行 |
| Ownership改动影响polling_trader稳定性 | 保留flock，pgid验证是增量，不替换原有机制 |
