# REVIEW — 主 SPEC v0.5 OOD 强制点复审

> **日期**：2026-11-09
> **复审对象**：[SPEC-EMERGENCE-EVOLUTION v0.5](../SPEC-EMERGENCE-EVOLUTION-v0.1.md) §5「涌现宣称门禁」中的 OOD walk-forward 隔离条款
> **复审范围**：① `evolution-case-ingest` 案例入库接口；② `bayesian_memory_updater.py` verify→贝叶斯升级路径
> **关联**：[SPEC-EMERGENCE-3D-v0.1](../SPEC-EMERGENCE-3D-v0.1.md) §11 P0-1 / §12 P0-1；[REVIEW-CHECKLIST v0.1](../REVIEW-CHECKLIST-v0.1.md) 维度 1（引用存在性）/ 维度 5（门禁强制等级）
> **裁决**：**P0 确认——主 SPEC 声称的代码级 OOD 强制点不存在**

---

## §1 主 SPEC 的原始宣称

[SPEC-EMERGENCE-EVOLUTION v0.5](../SPEC-EMERGENCE-EVOLUTION-v0.1.md) §5 原文：

> **OOD walk-forward 隔离**（**v0.4 P0#3 强制点**：案例库入库接口 `evolution-case-ingest` 加 `exclude_out_of_sample_interval` 参数强制拒绝黑名单区间行情；记忆 verify→贝叶斯升级路径 `bayesian_memory_updater.py` 加 `is_in_oos_interval` hook——无强制点则门禁只是自律口号，验收时会被判定为 P0 缺陷）

该条款把 OOD 隔离从“协议自律”升级为“代码强制”，并明确两个落点：

1. 案例入库：`evolution-case-ingest`
2. 记忆升级：`bayesian_memory_updater.py`

---

## §2 复审方法

1. **当前工作树全文件搜索**：精确搜索两个 hook 名称（含 Python/文档/配置）。
2. **本地 git 历史搜索**：`git log --all -S` 限定 `*.py`，确认是否曾有 Python 实现。
3. **实际实现下探**：
   - `1-ARCHITECTURE/dreamos/core/compute/case_ingest_gate.py`（CaseIngestGate）
   - `1-ARCHITECTURE/skills/evolution-case-ingest/SKILL.md`（案例入库流程）
   - `4-MEMORY/9-工具与接口/bayesian_memory_updater.py`（verify→贝叶斯升级）
4. **等价机制排查**：搜索 `OOS`/`out_of_sample`/`holdout`/`blacklist`/`exclude`/`embargo`/`purge`/`interval`，确认是否存在换名实现。
5. **其他 OOD 机制对照**：45 回测 purged k-fold/embargo、48 E0b 30% 时间切分、ablation gate IS/OOS 指标——确认它们是否覆盖“案例入库/记忆升级”路径。

---

## §3 证据

### 3.1 当前工作树：hook 只存在于文档

```text
grep -rn "exclude_out_of_sample_interval\|is_in_oos_interval" .
```

命中仅 3 处，全部是文档：

- `48-涌现架构/docs/tech/SPEC-EMERGENCE-EVOLUTION-v0.1.md`（主 SPEC 原文）
- `48-涌现架构/docs/tech/REVIEW-CHECKLIST-v0.1.md`（v0.4 实例引用）
- `48-涌现架构/docs/tech/SPEC-EMERGENCE-3D-v0.1.md`（本次复审引用）

**Python 代码 0 命中。**

### 3.2 本地 git 历史：从未有 Python 实现

```text
git log --all --oneline -S'exclude_out_of_sample_interval' -- '*.py'
git log --all --oneline -S'is_in_oos_interval' -- '*.py'
```

两条命令均无输出。`git log -S` 在未限定路径时命中的 `a0e7d87` / `dab265a` 是 **docs 同步提交**（提交信息 `docs(35,41,48,49,50): 多模块文档/SPEC 同步...`），其文件清单只包含 48 域 SPEC/README 等文档，不含 `*.py` 实现。

> 口径：本次只搜索本地全部分支/历史（`git branch -a` 可见 `main` / `feat/l0-mcp-generality-p0-p3` / `docs/nn-spec-adr-20261107` / `backup/pr84-local` / `origin/main` 等）。不排除云端或未拉取分支存在实现；若存在，需回传 commit + 测试证据后再关闭 P0-1。

### 3.3 实际案例入库实现：无 OOD 参数

[case_ingest_gate.py](../../../../1-ARCHITECTURE/dreamos/core/compute/case_ingest_gate.py) 的 `CaseIngestGate`：

- 只做 4 维学习价值评估：novelty / significance / anomaly / reproducibility；
- `_decide_ingest` 仅按 `overall_score` 阈值返回 `INGEST` / `DEFERRED` / `SKIP`；
- `evaluate_and_ingest(cycle_result, market_context)` **没有** `exclude_out_of_sample_interval`、时间区间、黑名单或 OOD 参数；
- `grep` 该文件 `OOS|out.of.sample|holdout|blacklist|exclude|embargo|purge|interval` → 0 命中。

[evolution-case-ingest/SKILL.md](../../../../1-ARCHITECTURE/skills/evolution-case-ingest/SKILL.md) 是人工/半自动入库流程：确定案例库 → 构造 13 维特征 → 计算 pnl/reward → 写 `4-MEMORY/data/evolution_cases/{library_name}.json` → 验证。**没有** OOD 区间拒绝步骤，也没有黑名单参数。

### 3.4 贝叶斯升级路径：无 OOS hook

[bayesian_memory_updater.py](../../../../4-MEMORY/9-工具与接口/bayesian_memory_updater.py) 的 `BayesianMemoryUpdater.update_confidence(memory_id, observation_success, followed_memory)`：

- 直接按 Beta 似然 + 全概率 + 指数遗忘更新 posterior；
- 更新条件只有 `observation_success` / `followed_memory`；
- **没有** `observation_ts`、`is_in_oos_interval`、时间区间或 OOS 排除逻辑；
- `grep` 该文件 `OOS|out.of.sample|interval` → 0 命中。

这意味着：只要 verify 事件进入 `update_confidence`，无论该观察是否落在 OOS 黑名单区间，记忆置信度都会更新——正是主 SPEC 想禁止的“OOS 信息污染记忆升级”。

### 3.5 其他 OOD 机制不能替代这两个强制点

| 机制 | 位置 | 保护对象 | 为什么不能替代 |
|---|---|---|---|
| purged k-fold + embargo | 45-评测系统金融回测 | 回测评估切分 | 保护的是评测器，不是案例入库/记忆升级 |
| E0b 30% 时间窗切分 | `48-涌现架构/registry/run_human_baseline.py` | 人工基线 IS/OOS 划分 | 只影响基线统计，不拒绝入库 |
| ablation gate IS→OOS 退化 | `48-涌现架构/experiments/e2_hypothesis/ablation_gate.py` | 策略变体准入 | 只做指标判定，不拦截案例/记忆写入 |
| 45 Enforcer/Gate | `45-评测系统/core/enforcement.py` | 评测凭证签发 | 不覆盖 evolution-case-ingest / bayesian_memory_updater 的写入路径 |

结论：**没有等价机制**。主 SPEC 声称的两个代码强制点确实缺失。

---

## §4 影响

1. **主 SPEC 七关门禁失真**：OOD 隔离当前只是协议自律，不是代码门禁；任何依赖 OOD 的“涌现候选/已验证”结论都可能被数据泄漏污染。
2. **E2/E5/E-BIZ 风险**：策略变体/案例库/组合泛化的评估若使用含 OOS 区间的数据，且入库/记忆升级未隔离，指标会被高估。
3. **三维子 Spec 无法启动**：D2-A 架构复原 holdout、D3-A 意图预测时序 holdout 都依赖 OOD/时序隔离；P0-1 未关闭前，实验只能算探索性，不能申报候选。
4. **文档-现实偏差**：这是 REVIEW-CHECKLIST 维度 1（引用存在性）与维度 5（门禁强制等级）的典型 P0；主 SPEC v0.5 的“修改后接受”结论需附条件。

---

## §5 修复方案

### 方案 A（推荐）：实现两个 hook + 回归测试

**A1. 案例入库**

在 `CaseIngestGate.evaluate_and_ingest`（或 `evaluate_learning_value`）增加可选参数：

```python
def evaluate_and_ingest(
    self,
    cycle_result: Dict[str, Any],
    market_context: Optional[Dict[str, Any]] = None,
    oos_intervals: Optional[Sequence[Tuple[datetime, datetime]]] = None,
) -> IngestReport:
    ...
```

行为：

- 若 `cycle_result` 的时间戳落在任一 OOS 区间 → 直接返回 `IngestDecision.SKIP`，`reason="oos_interval_excluded"`，不调用 `ingest_fn`；
- 时间戳缺失 → 按预注册策略处理（建议 fail-closed：`SKIP`，除非调用方显式 `allow_missing_ts=True`）；
- 时间区间来源：`48-涌现架构/registry/ood_intervals.json`（或 45 的 dataset registry），带 `start/end/source/version`。

测试用例：

1. 区间内 → SKIP，`ingest_fn` 未被调用；
2. 区间外 → 正常走 4 维评估；
3. 缺时间戳 → 默认 SKIP（fail-closed）；
4. 多区间/边界时间 → 左闭右开，边界明确；
5. 回归：无参数时行为与现状一致（向后兼容）。

**A2. 记忆升级**

在 `BayesianMemoryUpdater.update_confidence` 增加可选参数：

```python
def update_confidence(
    self,
    memory_id: str,
    observation_success: bool,
    followed_memory: bool,
    observation_ts: Optional[datetime] = None,
    oos_intervals: Optional[Sequence[Tuple[datetime, datetime]]] = None,
) -> Tuple[float, str]:
    ...
```

行为：

- 若 `observation_ts` 落在 OOS 区间 → **不更新** posterior/Beta/quality，返回 `(prior, current_quality)`，并记录 `oos_excluded` 审计事件；
- 缺 `observation_ts` 且未显式允许 → fail-closed，不更新；
- 无参数时行为不变（向后兼容）；
- 审计事件字段：`memory_id, observation_ts, interval, action="oos_excluded", source`。

测试用例：

1. 区间内 → 置信度不变，`verify_count` 不变；
2. 区间外 → 正常贝叶斯更新；
3. 缺时间戳 → 默认不更新；
4. 边界/多区间；
5. 回归：无参数时旧测试全绿。

**A3. 共享 OOD 区间源**

建议新增 `48-涌现架构/registry/ood_intervals.json`（或复用 45 dataset registry）：

```json
{
  "schema_version": "1.0",
  "generated_at": "2026-11-09T00:00:00Z",
  "intervals": [
    {"start": "2026-11-04T00:00:00Z", "end": "2026-11-05T00:00:00Z", "source": "E0b_oos", "version": "v0.1"}
  ],
  "known_gaps": []
}
```

所有权建议：48 定义格式与纪律；具体区间由 45/19 提供；消费方只读。

### 方案 B：若云端/其他分支已有实现

- 回传 commit + 测试输出 + artifact hash；
- 在当前分支 backport，并跑 A1/A2 回归测试；
- 更新主 SPEC v0.5 的引用为真实代码路径与 commit。

### 方案 C：降级宣称（临时）

- 把主 SPEC §5 的“代码级强制点”改为“协议级，待实现”；
- 在 OOD 实现前，任何依赖 OOD 的涌现候选只能记 `inconclusive`，不得升 `verified`；
- 这是临时措施，不替代 A/B。

**推荐**：A（两个 hook + 5+5 测试 + 区间 registry），在 P1 实验前完成；若排期不足，先执行 C 并在三维 Spec 中保持 P0-1 open。

---

## §6 处置与状态

| 项 | 状态 |
|---|---|
| P0-1 复审 | ✅ 完成（本报告） |
| P0-1 修复 | ❌ 未实施（本报告不含代码改动） |
| 主 SPEC v0.5 正文 | 不改；在 v0.6 增补附录登记本复审结果 |
| 三维子 Spec §11/§12 | 更新 P0-1 状态为“已确认缺失，待修复” |
| REVIEW-CHECKLIST §4 | 追加本次复审记录 |

**关闭条件**：方案 A 或 B 落地 + 回归测试通过 + 主 SPEC 引用更新为真实代码路径；否则 P0-1 保持 open，D2-A/D3-A 只能做探索性实验。

---

## §7 复现命令

```bash
# 1) 当前工作树精确搜索
grep -rn "exclude_out_of_sample_interval\|is_in_oos_interval" .

# 2) 本地 git 历史（仅 Python）
git log --all --oneline -S'exclude_out_of_sample_interval' -- '*.py'
git log --all --oneline -S'is_in_oos_interval' -- '*.py'

# 3) 实际实现下探
grep -nE "class |def |OOS|out.of.sample|interval|exclude|blacklist|embargo|purge" \
  1-ARCHITECTURE/dreamos/core/compute/case_ingest_gate.py \
  1-ARCHITECTURE/skills/evolution-case-ingest/SKILL.md \
  4-MEMORY/9-工具与接口/bayesian_memory_updater.py

# 4) 本地分支清单
git branch -a
```

---

## §8 参考

- [SPEC-EMERGENCE-EVOLUTION v0.5](../SPEC-EMERGENCE-EVOLUTION-v0.1.md) §5
- [SPEC-EMERGENCE-3D-v0.1](../SPEC-EMERGENCE-3D-v0.1.md) §11 P0-1 / §12
- [REVIEW-CHECKLIST v0.1](../REVIEW-CHECKLIST-v0.1.md) 维度 1 / 维度 5
- [case_ingest_gate.py](../../../../1-ARCHITECTURE/dreamos/core/compute/case_ingest_gate.py)
- [evolution-case-ingest/SKILL.md](../../../../1-ARCHITECTURE/skills/evolution-case-ingest/SKILL.md)
- [bayesian_memory_updater.py](../../../../4-MEMORY/9-工具与接口/bayesian_memory_updater.py)
- 45-评测系统 [SPEC-评测系统.md](../../../../45-评测系统/SPEC-评测系统.md) §5.1 / §7.2
- 48 E0b [run_human_baseline.py](../../../registry/run_human_baseline.py)
- 48 E2 [ablation_gate.py](../../../experiments/e2_hypothesis/ablation_gate.py)