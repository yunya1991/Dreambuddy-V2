---
name: dream-lint-risk-fix-verify
description: "有风险 lint 规则（I001/F401/F841/E402/E712/B905/B023 等）批量修复前的副作用检测门禁：静态风险扫描 + AST 等价校验 + 命名空间/冒烟对比 + 批次判定。Invoke when fixing ruff/black alerts in bulk or user says 批量修复告警/风险修复/确保功能正常/副作用检测。"
version: 0.1.0
created: 2026-11-08
updated: 2026-11-08
license: Internal
status: active
category: tooling
triggers: [批量修复告警, lint修复, ruff修复, 风险修复, 副作用检测, AST等价, I001, F401, F841, 确保功能正常]
depends_on: [dream-acceptance-verify, dream-code-commit-sync-workflow, safe-service-restart]
provides: [lint-risk-scan, ast-equivalence-gate, batch-fix-verification]
cognitive_links: []
---

## Autonomy Boundary

可自主执行：

- 运行 ruff 采集命中项、AST 解析、静态副作用扫描
- 在临时副本上试跑修复并做前后对比（不落盘到工作区）
- 生成风险报告与批次建议

需用户确认：

- 任何 high 风险文件的落盘修复
- 修改 pyproject 的 per-file-ignores / force-exclude
- 对常驻服务（polling_trader / gateway）相关文件动手后的重启窗口

禁止：

- 用 `ruff --fix` / `--unsafe-fixes` 对全仓库无差别扫描
- 删除 `__init__.py` 中的导入、带副作用的调用赋值
- 在未跑本 SKILL 检测的情况下宣称"批量修复完成、功能正常"
- 把"CI 绿"当作"功能正常"的证据（CI test 各 step 是 continue-on-error）

# Dream Lint Risk Fix Verify — 有风险 lint 修复的副作用检测门禁

> 背景（2026-11-08）：仓库 `ruff check .` 存量 20,557 条，其中约 9,500 条为纯风格（W293/W291/W292/F541/E401/C4xx 等），语义等价；约 7,400 条（I001 3,302 / F401 3,203 / F841 909）会**改变代码结构或执行顺序**，是批量修复中唯一能真正弄坏系统的一批。本 SKILL 把"修之前先量化风险、修之后用三类证据证明无副作用"固化为可复用流程。

## 一、风险分级矩阵

| 规则 | 规模 | 破坏机制 | 检测手段 | 默认策略 |
|---|---|---|---|---|
| W293/W291/W292 | 7,145 | 无（仅空白） | AST strict 等价 | auto |
| F541/E401/C4xx/B009/B010/E713/B033 | ≈2,400 | 近似无 | AST strict 等价 | auto |
| I001 导入排序 | 3,302 | 改变 import 执行顺序：sys.path/env/注册副作用 | 模块级副作用扫描 + import-order AST 等价 | per-file |
| F401 未用导入 | 3,203 | `__init__.py` 再导出消失；插件/模型注册丢失 | `__init__.py`/`__all__` 识别 + 公共命名空间对比 | per-file |
| F841 未用变量 | 909 | 右侧调用携带副作用（取数/写库/发信号） | AST 右侧副作用识别 + 删除行 diff 扫描 | per-file |
| E402 导入不在顶部 | 1,210 | 多为 sys.path hack 之后导入，移动即崩 | 静态标记 | ignore（per-file） |
| E712 `== True` | 44 | numpy/pandas 数组真值歧义 | 数组库导入 + 比较式识别 | 人工 |
| B905 `zip(strict=)` | 304 | Python 3.9 运行环境 TypeError | 运行环境版本匹配 | auto（3.9 路径排除） |
| B023 闭包循环变量 | 228 | 捕获对象从"最后值"变"当前值" | 行为差异，无法静态证明 | 人工 |
| E722 bare except | 63 | 不再吞 KeyboardInterrupt/SystemExit | 行为差异 | 人工 |
| F601 重复字典键 | 11 | 静默覆盖配置/风控阈值 | 重复键与双值输出 | 人工 |
| F821 未定义名 | 360 | 执行到即 NameError | 上下文分类（死代码/运行时路径） | 人工 |
| invalid-syntax | 30 | 文件无法编译 | 编译确认 | 优先修 |

## 二、硬约束

| 编号 | 约束 |
|---|---|
| HC-1 | 每批只允许一类规则；禁止混合 auto 与 per-file 规则同批提交 |
| HC-2 | auto 批必须证明 AST strict 等价（`verify_batch.py --mode strict`），否则回滚 |
| HC-3 | I001 批必须证明 import-order 等价且文件无模块级副作用，否则该文件降级为 per-file |
| HC-4 | F401 批必须证明公共命名空间未减少（`--mode namespace`），`__init__.py` 一律不进自动批 |
| HC-5 | F841 删除行若含调用/await/yield，一律标记 high，禁止自动删除 |
| HC-6 | 每批独立 commit，提交信息含规则名与文件数；失败批次用 `git checkout --` 回滚，禁止手动"抢救" |
| HC-7 | 常驻服务相关文件修复后按 safe-service-restart 流程重启，禁止带未提交改动重启 |
| HC-8 | 交付结论必须附带本 SKILL 的报告 JSON，禁止用"应该没问题"替代 |

## 三、六步流程

```
基线采集 → 分类分批 → 修复前预检 → 单批修复 → 修复后检测 → 判定与提交
```

1. **基线采集**
   `ruff check . --statistics` + `ruff check . --output-format=json > baseline.json`
   记录每规则数量、涉及文件数，写入本批报告。
2. **分类分批**
   按上表拆批：auto（空白/等价改写）→ I001 → F401 → F841 → 人工规则 → black 全量。
3. **修复前预检**
   `risk_scan.py --rules <本批规则>`：输出每个命中项的 high/medium/low 与原因，high 文件移出本批。
4. **单批修复**
   只对本批通过预检的文件执行 `ruff check --select <规则> --fix`（I001/F401/F841 不启用 `--unsafe-fixes`）。
5. **修复后检测**
   `verify_batch.py --rule <规则> --files <本批文件>`：
   - 规则类证据：strict / import-order / namespace / side-effect 四选一
   - 动态证据：`compile` 必跑；`--smoke import` 用于库模块；受影响的 pytest suite 必跑
6. **判定与提交**
   `block` 文件回滚并降级为 per-file-ignore；`pass/warn` 文件 commit。
   提交后把报告写入 `.workbuddy/lint-risk/<rule>-<date>.json`（不入库亦可）。

## 四、三类检测手段

### 1. AST 等价（结构层）

- `strict`：格式化前后 `ast.dump(include_attributes=False)` 完全一致 → 证明零语义变化。
- `import-order`：仅允许 import 节点重排/别名排序，其余语句序列必须一致 → 证明 I001 只是顺序调整。

### 2. 静态副作用扫描（风险层）

- 模块级非定义语句（`Expr(Call)`、`If/Try/With/For`、`sys.path` / `os.environ` 变更）→ I001 high。
- `__init__.py`、`__all__` 中出现的名字 → F401 high。
- 赋值右侧含 `Call/Await/Yield` → F841 high。
- 同时导入 numpy/pandas 且出现 `== True/False` → E712 high。
- 字典字面量重复常量键 → F601 high，并输出两个值供人工裁决。

### 3. 动态证据（行为层）

- `compile`：语法可编译（所有批必跑）。
- `import` 冒烟：子进程导入，比对 `dir()` 公共命名空间与 `__all__`（F401 必跑）。
- pytest：受影响目录的 suite 通过数不得低于基线；`exit 4`（空集合）视为未覆盖，必须显式记录。

## 五、命令速查

```bash
# 1) 全仓风险扫描（评估用，不修改任何文件）
python3 1-ARCHITECTURE/skills/dream-lint-risk-fix-verify/scripts/risk_scan.py \
  --root . --output /tmp/lint-risk.json --summary

# 2) 单规则预检
python3 .../scripts/risk_scan.py --root . --rules F841 --only-risky --summary

# 3) 批次校验（按规则选择检测模式）
python3 .../scripts/verify_batch.py --rule I001 --files-from /tmp/batch.txt
python3 .../scripts/verify_batch.py --rule F401 --files-from /tmp/batch.txt --mode namespace --smoke import
python3 .../scripts/verify_batch.py --rule F841 --files-from /tmp/batch.txt --mode side-effect
python3 .../scripts/verify_batch.py --rule W293 --files-from /tmp/batch.txt --mode strict
```

## 六、判定标准

| 判定 | 条件 | 动作 |
|---|---|---|
| pass | 规则类证据等价 + compile 通过 + 冒烟/测试无回归 | 进 commit |
| warn | AST 等价但风险扫描存在 medium | 进 commit，报告中标注人工复核 |
| block | high 风险 / 命名空间减少 / 编译失败 / 测试通过数下降 | 回滚该文件，降级 per-file-ignore 或人工修 |

## 七、反模式

| 反模式 | 后果 |
|---|---|
| `ruff --fix` 全仓一把梭 | 2,000+ 文件同时变更，无法定位回归来源 |
| 先改后验 | 无可比对基线，检测失去意义 |
| 把 `__init__.py` 纳入 F401 自动批 | 外部 import 静默失效 |
| 只看 CI 绿灯 | pytest step 是 continue-on-error，红灯也不会出现 |
| 用 `--no-verify` 绕过本地 hook | 门禁与审查同时失效 |
| 给整个目录加 per-file-ignores | 新增代码永久失去检查，形成盲区 |

## 八、与其他 SKILL 的边界

- `dream-acceptance-verify`：面向"功能/bug 是否修好"的五维验收；本 SKILL 面向"批量重构是否零副作用"的批次门禁。
- `dream-code-commit-sync-workflow`：负责提交动作本身；本 SKILL 负责提交前的判定。
- `safe-service-restart`：负责重启时序；本 SKILL 只判定代码变更是否安全。
