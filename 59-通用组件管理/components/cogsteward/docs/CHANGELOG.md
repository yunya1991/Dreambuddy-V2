# 认知管家（CogSteward）— 变更日志

> **版本**: v1.4 | **更新日期**: 2026-11-20
> **定位**: 记录每次变更的原因、内容、验证方式与回滚策略，对齐 [DOC_STANDARD.md](../../../../0-系统文档管理/1-规范体系/DOC_STANDARD.md) §3.5

---

## [v0.7.0 · 契约单一源] - 2026-11-20

### 新增

**指标契约 / 安装自检 / 发布闸门（三端口径收敛）**

- **变更内容**：
  - `cognition-manager/references/metrics-contract.json`：九项指标 + 五项占比的唯一口径源（标签 / 定义 / 阈值 / 权重 / 分母 / 动作）
  - `core/contract.py`：契约加载、结构校验、`health_of`、标签与阈值查询
  - `core/selfcheck.py` + `cm selfcheck`：安装后自检契约结构、`report` 口径与 health 分档
  - `scripts/release_check.py`：发版前校验三端契约副本 sha256 一致、版本号一致、health 抽样一致
  - `core/report.py`：`PROBLEM_KEYS` / `health_of` / 体检表标签改为读契约
  - Pro `scripts/report.py`：读包内契约副本，输出 `schema_version` 与 `coverage`；缺 `orphan_files` 时标记 `unavailable`，不再冒充 0
  - 后端 `src/cogsteward.js`：`require('./metrics-contract.json')` 驱动指标与占比，响应增加 `coverage`
  - `skills/skillpay-workflow/scripts/audit.sh deploy`：备份 → 安装 → 重启 → 健康/402 回归 → 失败自动回滚
  - `ops/patrol/RUNBOOK.md` S5 重写：以部署脚本为准，去掉失效的 GitHub 三段式
- **影响范围**：免费版 `doctor` 体检表标签与契约一致（「断链数」→「断链」）；Pro / 后端报告新增 `schema_version` / `coverage` 字段；阈值与权重无变化。
- **验证方式**：
  - `/tmp` 副本运行 85 项自检通过（2 项 N/A 跳过）
  - 后端 `/tmp/audit-api` 运行 13/13 通过
  - `release_check.py` 4 项 PASS，三端契约 sha256 同为 `41d77f6e…`
  - 云端 1.2.0 部署完成（`src/` + `package.json`，备份 `backups/app-20261120-174109`）：health ok、`/api/cogsteward` 402、报告含 `schema_version=1.0` 与 `coverage`
- **回滚策略**：删除 `core/contract.py`、`core/selfcheck.py`、`scripts/release_check.py`，`report.py` 恢复内置 `PROBLEM_KEYS`；三端契约副本可整体回退到上一提交。

### 修改

- 免费版 0.6.1 → 0.7.0；Pro 1.0.3 → 1.1.0；按次版 1.0.2 → 1.1.0；后端 1.1.1 → 1.2.0
- `SKILL.md`：命令表新增 `cm selfcheck`，「v0.6 规划」改为「v0.6 已落地」，补充契约说明
- `TECHNICAL_DESIGN.md` 升 v1.4：新增 §12 修复复盘与优化清单（OC-01~09）、偏差 D17–D19
- `ENGINEERING_INDEX.md` 升 v1.4：新增契约 / 自检 / 闸门文件条目与测试统计

### 修复

- Pro 在无 `.cm` 时把孤儿文件填 0 的「假健康」问题（改为 `coverage.orphan="unavailable"`）
- 三端阈值 / 权重 / 标签手工同步导致的漂移

### 删除

- 后端 `cogsteward.js` 中硬编码的 `METRICS` / `RATIOS` 常量（改为读契约）
- Pro `report.py` 中硬编码的 `RULES` / `RATIOS` 常量（改为读契约）

---

## [v0.5.0 · M3] - 2026-11-19

### 新增

**索引总览 / 技能规范检查 / V9 十二例（`index` / `skill lint`）**

- **变更内容**：
  - `core/indexer.py`：默认执行增量扫描后输出 `counts{docs, skills, broken_links, orphan_files, index_drift}`；`--check` 只读校验，不写 `index.db`
  - `core/skill_lint.py`：读取 `SKILL.md` frontmatter，检查缺版本、重名、触发词重叠、`triggers` 非列表、`depends_on` 指向不存在的技能
  - CLI 新增 `index` 子命令与 `skill lint` 子命令；`report.py` 新增两套人类可读输出
  - V9 十二例异常路径：10 项实测（空工作区、只读、超限、非 UTF-8、符号链接环、空格/中文、大小写、权限、损坏库、并发写），2 项 N/A 注明构造方法（磁盘满、中断恢复）
- **影响范围**：`index` 默认写 `.cm/index.db`（与 `scan` 相同）；`--check` 与 `skill lint` 只读。不改变既有命令语义。
- **验证方式**：
  - `/tmp` 副本运行 `python3 -m unittest discover -s scripts/tests -v`，70 项通过（2 项 N/A 跳过）
  - `index --check` 前后 `index.db` 不新增登记；`index` 可把孤儿归零
  - `skill lint` 五类问题均命中，发现 issues 仍退出 0，`cm skill` 无子命令退出 2
  - V1 1.91s、V2 1.08s、V6 / V8 0 命中
- **回滚策略**：删除 `core/indexer.py`、`core/skill_lint.py` 并回退 CLI 注册；既有 `.cm/` 数据不受影响。

### 修改

- `SKILL.md` 命令表与范围限制更新到 M3
- `API_SPEC.md` 升 v1.3：新增 4.11 `index`、4.12 `skill lint`
- `TECHNICAL_DESIGN.md` 升 v1.3：新增 3.11–3.12 算法、V9 异常路径表、偏差 D14–D16
- `ENGINEERING_INDEX.md` 升 v1.3：目录、职责、测试体系、验收证据与技术债
- `CHANGELOG.md` 遗留项中的 `index` / `skill lint` 与 V9 标记为已完成

### 修复

- 无。

### 删除

- 无。

---

## [v0.5.0 · M2b] - 2026-11-19

### 新增

**上下文打包 / 分拣 / 黄金集评估（`pack` / `triage` / `eval_golden`）**

- **变更内容**：
  - `core/pack.py`：关键词打分（标题 2.0 / 触发词 1.5 / 路径 1.0 / edges 一跳 0.5）+ token 预算贪心裁剪，只返回指针，不读正文、不落盘
  - `core/triage.py`：列出过期会话与 `pending.state='open'`；`--expire-sessions` 写 `triaged_at`，`--drop-pending` 按 `review_count>=3` 丢弃、其余 +1
  - `scripts/eval_golden.py`：每类 P/R/F1、宏平均、高置信分组精确率、ECE（10 桶）、Cohen's κ；缺数据退出码 2，不伪造
  - CLI 新增 `pack` / `triage` 子命令；`report.py` 新增两套人类可读输出
  - `references/pack.md` / `references/triage.md` / `references/golden/labeling-guide.md`
- **影响范围**：新增只读与 `.cm/` 内状态迁移，不改变路由与写入语义。
- **验证方式**：
  - `/tmp` 副本运行 `python3 -m unittest discover -s scripts/tests`，51/51 通过
  - `pack --budget {1,5,12,40}` 估算量恒不超预算，工作区文件字节级不变
  - `triage` 默认 dry-run 零修改；显式开关后状态按预期迁移
  - `eval_golden` 已知样例 P/R/F1 与 κ 精确匹配；缺预测 / 缺 confidence 均退出 2
  - V1 1.02s、V2 1.19s、V6 / V8 0 命中
- **回滚策略**：删除 `core/pack.py`、`core/triage.py`、`scripts/eval_golden.py` 并回退 CLI 注册；已有 `.cm/` 数据不受影响。

### 修改

- `SKILL.md` 命令表与范围限制更新到 M2b
- `API_SPEC.md` 升 v1.2：新增 4.8 `pack`、4.9 `triage`、4.10 `eval_golden.py`
- `TECHNICAL_DESIGN.md` 升 v1.2：新增 3.8–3.10 算法、4.6–4.7 数据流、偏差 D11–D13
- `ENGINEERING_INDEX.md` 升 v1.2：目录、职责、测试体系与验收证据
- `references/golden/README.md`：补充 JSONL 标注格式与评估命令

### 修复

- 无。

### 删除

- 无。

---

## [v0.5.0 · M2] - 2026-11-19

### 新增

**路由内核与安全写入（`route` / `mark-done` / `rollback` / `config`）**

- **变更内容**：新增 `core/signature.py`（字面归一化 + 动词映射 + 加盐哈希）、`core/admission.py`（A1–A4）、`core/router.py`（判定树、confidence、patch、plan/apply 决策）、`core/apply.py`（快照、manifest、三类 op、逆序回滚）；CLI 新增四个命令；`store` 增加 `apply_runs` 表与配置权重。
- **影响范围**：`scripts/` 与 `SKILL.md`；默认仍为 `plan`，未开启 `apply` 的工作区不产生业务文件写入。
- **验证方式**：
  - `/tmp` 副本运行 `python3 -m unittest discover -s scripts/tests -v`，40/40 通过
  - plan 不落盘、confidence 可由 `confidence_parts` 复算
  - 同一 `idempotency_key` 连续 5 次 apply，仅 1 次写入
  - create / modify / delete 三类 op 回滚后哈希 100% 还原；手改冲突整体中止
  - V1 0.89s、V2 1.66s、V6 / V8 0 命中
- **回滚策略**：`cm rollback <run_id>` 回滚单次 apply；代码层删除四个 core 模块并回退 CLI 注册。

### 修改

**文档对齐 M2**

- `SKILL.md` 命令表、路由模型与范围限制更新
- `API_SPEC.md` 升 v1.1：新增 4.4–4.7 命令契约与准入事实格式
- `TECHNICAL_DESIGN.md` 升 v1.1：新增路由 / 准入 / 写入回滚算法、模块关系、偏差 D6–D10
- `ENGINEERING_INDEX.md` 升 v1.1：目录地图、文件职责、测试体系与 M2 验收证据

### 修复

- 无。

### 删除

- 无。

---

## [v0.5.0] - 2026-11-19

### 新增

**M1 技能包骨架（`init` / `scan` / `doctor`）**

- **变更内容**：新建 `cognition-manager/`，含平台入口 `SKILL.md`（8 项必填 frontmatter）、`manifest.yaml`、`scripts/cm_cli.py`、`scripts/core/{store,scanner,report}.py`、`scripts/modes/{dev,office}.yaml`、`references/` 与 `templates/`。实现工作区初始化、增量扫描与六指标体检。
- **影响范围**：新增目录，不改动既有业务代码。
- **验证方式**：
  - 复制到 `/tmp/cm-verify` 后运行 `python3 -m unittest discover -s scripts/tests -v`，20/20 通过
  - V1 首次体验 0.85s（≤30s，1000 文件）
  - V2 全量扫描 0.96s（≤3s，1000 文件）
  - V6 AST 扫描 0 个第三方 import
  - V8 敏感词扫描 0 命中
- **回滚策略**：删除 `59-通用组件管理/cognition-manager/` 整个目录；无运行时依赖，不影响其他模块。

**补齐路由契约参考文档**

- **变更内容**：新增 `references/confidence.md`（公式、分量、阈值、联调表、V13 校准）与 `references/intent-signature.md`（归一化步骤、停用词、50 条动词映射、示例与约束），补齐 SPEC §7 声明的参考文档缺口。
- **影响范围**：仅文档；M2 实现以此为准。
- **验证方式**：与 SPEC §5.3 / §5.5.1 逐条对照，无冲突；包内敏感词扫描仍为 0。
- **回滚策略**：删除两个文件，恢复为 SPEC 内嵌描述。

**工程文档四件套（`59-通用组件管理/docs/`）**

- **变更内容**：新增 `ENGINEERING_INDEX.md`、`TECHNICAL_DESIGN.md`、`API_SPEC.md`、`CHANGELOG.md`，覆盖文件级索引、架构与算法、CLI 契约、变更记录。
- **影响范围**：仅文档。
- **验证方式**：文档内链接逐条可达；函数数、命令参数与实际代码一致。
- **回滚策略**：删除 `docs/` 目录并还原索引条目。

### 修改

**模块索引状态对齐**

- **变更内容**：`59-通用组件管理/INDEX.md` 组件状态由「M0 已关闭，待 M1」改为「M1 进行中：init/scan/doctor 已实现，V1/V6/V8 自检通过」，并登记 docs 四件套；`0-系统文档管理/INDEX.md` 的 59 分节同步新增文档行、修正 INDEX 版本。
- **影响范围**：索引文档。
- **验证方式**：链接可达；版本号与文件头一致。
- **回滚策略**：`git revert` 对应提交。

### 修复

- 无。

### 删除

- 无。

---

## 遗留项（不阻塞 v0.5.0）

| # | 项 | 计划 |
|---|---|---|
| 1 | 黄金集（Dev ≥100 / Office ≥80，需人工标注） | 待人工标注 |
| 2 | ~~`cm index` / `cm skill lint`~~ | 已完成（M3） |
| 3 | ~~V9 十二条例外路径~~ | 已完成（M3：10 实测 + 2 N/A） |
| 4 | 磁盘满 / 中断恢复的故障注入 | 后续补自动化 |
| 5 | 3 位真实用户访谈 | M1 并行 |
| 6 | 平台付费技能是否强制云端执行 | 上架前确认 |
| 7 | V12 / V13 门禁与 apply 硬绑定 | V12 通过后 |

---

## 变更类型说明

| 类型 | 说明 |
|------|------|
| **新增** | 添加新功能、新文件、新接口 |
| **修改** | 修改已有功能、重构、优化 |
| **修复** | 修复 bug、缺陷、错误 |
| **删除** | 移除废弃功能、文件、接口 |

---

**文档版本**: v1.4
**最后更新**: 2026-11-20
