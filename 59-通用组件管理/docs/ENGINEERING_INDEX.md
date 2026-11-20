# 认知管家（CogSteward）— 工程索引

> **版本**: v1.4 | **更新日期**: 2026-11-20
> **定位**: 59-通用组件管理 下认知管家组件的文件级工程索引（L3），对齐 [DOC_STANDARD.md](../../0-系统文档管理/1-规范体系/DOC_STANDARD.md)
> **对应 SPEC**: [SPEC v0.5](../SPEC-认知管家-WorkBuddy技能封装-v0.5.md)

---

## 1. 模块定位

| 属性 | 值 |
|------|-----|
| 模块编号 | 59（通用组件管理） |
| 组件名称 | 认知管家 CogSteward（工程名 cognition-manager） |
| 核心职责 | 工作区上下文治理：扫描登记、断链/孤儿/漂移检测、技能冲突检测、体检报告、主载体路由与安全写入 |
| 主入口 | `cognition-manager/scripts/cm_cli.py` → `main()` |
| 运行形态 | WorkBuddy Skill（本地安装），零第三方依赖 |
| 依赖关系 | 上游：Python 3.10+、SQLite（FTS5 可选）；下游：无 |
| 当前阶段 | M3 + 契约治理（0.7.0：指标契约单一源 / `selfcheck` / `release_check`） |
| 文档状态 | ✅ 工程索引 / 技术设计 / 接口规格 / 变更日志 |

---

## 2. 目录地图

```
59-通用组件管理/
├── INDEX.md                          # 模块索引
├── SPEC-认知管家-...-v0.5.md          # 产品 SPEC（M0 收口）
├── SPIKE-...md / PRETEST-...md        # 平台取证 / 定性前测
├── docs/                             # 本目录（工程文档）
│   ├── ENGINEERING_INDEX.md          # 本文件
│   ├── TECHNICAL_DESIGN.md           # 技术设计
│   ├── API_SPEC.md                   # CLI 接口规格
│   └── CHANGELOG.md                  # 变更日志
└── cognition-manager/                # 可分发的 Skill 包
    ├── SKILL.md                      # 平台入口（frontmatter + 流程）
    ├── manifest.yaml                 # 版本 / 模式 / 权限 / 依赖
    ├── scripts/
    │   ├── cm_cli.py                 # 统一入口
    │   ├── eval_golden.py            # 黄金集评估（独立只读脚本）
    │   ├── release_check.py          # 发布前一致性闸门（三端契约 / 版本 / 口径）
    │   ├── core/
    │   │   ├── __init__.py           # 版本号
    │   │   ├── store.py              # SQLite + FTS5 + 配置
    │   │   ├── scanner.py            # 扫描 / 分类 / 链接
    │   │   ├── report.py             # 体检 + 人类可读报告
    │   │   ├── contract.py           # 指标契约加载 / 校验 / health
    │   │   ├── selfcheck.py          # 安装自检（cm selfcheck）
    │   │   ├── signature.py          # 意图指纹归一化 + 加盐哈希
    │   │   ├── admission.py          # 记忆准入四问
    │   │   ├── router.py             # 判定树 / confidence / patch
    │   │   ├── apply.py              # 快照 / 落盘 / 逆序回滚
    │   │   ├── pack.py               # token 预算打包（只读）
    │   │   ├── triage.py             # 会话 / 待定项分拣
    │   │   ├── indexer.py            # 索引总览（cm index）
    │   │   └── skill_lint.py         # 技能规范检查（cm skill lint）
    │   ├── modes/
    │   │   ├── dev.yaml              # Dev 阈值与词表
    │   │   └── office.yaml           # Office 阈值与词表
    │   └── tests/
    │       └── test_core.py          # 85 项自检（含 2 项 V9 N/A 跳过）
    ├── references/
    │   ├── metrics-contract.json     # 九项指标 / 占比唯一口径源（三端副本一致）
    │   ├── schema.md                 # 数据表 / 状态机 / 隐私
    │   ├── routing-matrix.md         # 判定树 / 关系 / confidence
    │   ├── confidence.md             # confidence 计算规范
    │   ├── intent-signature.md       # 指纹归一化规范
    │   ├── admission-rules.md        # 记忆准入四问
    │   ├── pack.md                   # 打包评分与预算规范
    │   ├── triage.md                 # 分拣状态迁移规范
    │   └── golden/
    │       ├── README.md             # 黄金集目录约定
    │       └── labeling-guide.md     # 双人标注与分歧裁定
    └── templates/                    # SPEC / ADR / INDEX / SKILL / 纪要
```

**代码统计**：核心 Python 文件 18 个（入口 1 + 评估器 1 + 闸门 1 + core 14 + 自检 1），共约 5300 行（其中自检约 1360 行）。

---

## 3. 文件清单与职责

### 3.1 入口层

| 文件 | 函数数 | 职责 | 关键函数 |
|------|--------|------|----------|
| `scripts/cm_cli.py` | 13 | 参数解析、命令分发、错误码出口 | `build_parser()`, `main()`, `cmd_init()`, `cmd_scan()`, `cmd_doctor()`, `cmd_route()`, `cmd_pack()`, `cmd_triage()`, `cmd_mark_done()`, `cmd_rollback()`, `cmd_config()`, `cmd_index()`, `cmd_skill_lint()` |
| `scripts/eval_golden.py` | ~12 | 黄金集评估（P/R/F1、ECE、κ），只读，不进入 CLI | `evaluate()`, `_prf()`, `_calibration()`, `_kappa()`, `main()` |
| `scripts/release_check.py` | 6 | 发布前一致性闸门：三端契约 sha256、结构、版本号、health 抽样 | `run()`, `check_contract_copies()`, `check_contract_structure()`, `check_versions()`, `check_health_alignment()` |

### 3.2 核心层（scripts/core/）

| 文件 | 函数数 | 职责 | 关键函数 |
|------|--------|------|----------|
| `store.py` | ~16 | 工作区初始化、配置读写、SQLite 连接与 schema、扁平 YAML 子集解析 | `init_workspace()`, `connect()`, `ensure_schema()`, `load_config()`, `update_config()`, `default_config()`, `parse_flat_yaml()` |
| `scanner.py` | ~12 | 遍历文件、增量判定、文本/二进制分类、哈希、frontmatter、链接解析与入库 | `scan()`, `iter_files()`, `sha256_file()`, `classify()`, `resolve_link()`, `_upsert_doc()`, `_upsert_skill()` |
| `report.py` | 16 | 指标计算、Top-3 建议、路由 / 回滚 / 配置 / 索引 / 技能检查的人类可读输出 | `doctor()`, `recommendations()`, `health_of()`, `format_route()`, `format_rollback()`, `format_doctor()`, `format_index()`, `format_skill_lint()` |
| `contract.py` | 11 | 指标契约加载 / 结构校验 / `health_of` / 标签与阈值查询 | `load()`, `validate()`, `metrics()`, `ratios()`, `problem_keys()`, `labels()`, `thresholds()`, `health_of()` |
| `selfcheck.py` | 3 | 安装自检：契约结构、report 口径、health 分档、工作区状态 | `run()`, `format_selfcheck()` |
| `signature.py` | 6 | 清洗、动词归一、中文 bigram / 英文分词、停用词、加盐哈希 | `clean()`, `normalize_verbs()`, `tokenize()`, `normalize()`, `fingerprint()`, `describe()` |
| `admission.py` | 7 | A1–A4 校验与 pending / observation 降级 | `evaluate()`, `_check_a1()`, `_check_a2()`, `_check_a3()`, `_check_a4()` |
| `router.py` | ~20 | 判定树、confidence、attachments、patch、plan/apply 决策、执行计数 | `route()`, `mark_done()`, `confirm_intent()`, `_detect()`, `_build_patch()`, `_confidence_value()` |
| `apply.py` | ~10 | 快照、manifest、create/modify/delete、幂等查询、逆序回滚 | `apply_patch()`, `rollback()`, `find_applied()`, `_safe_path()`, `_validate()` |
| `pack.py` | 6 | 关键词打分、edges 一跳加分、token 估算与预算裁剪（只读） | `pack()`, `estimate_tokens()`, `_keywords()`, `_score_row()`, `_edge_boost()` |
| `triage.py` | 4 | 过期会话与 open 待定项的列出与状态迁移 | `triage()`, `_session_items()`, `_pending_items()` |
| `indexer.py` | 2 | 索引总览：默认增量扫描，`--check` 只读校验 | `index()`, `_now_iso()` |
| `skill_lint.py` | ~8 | 技能 frontmatter 检查：版本 / 重名 / 触发词 / 依赖 | `lint()`, `_collect()`, `_parse_frontmatter()`, `_as_list()` |

### 3.3 配置与模式

| 文件 | 职责 | 关键内容 |
|------|------|----------|
| `scripts/modes/dev.yaml` | Dev 默认值 | `high=0.80` `low=0.50` `ttl=7d` `materialize=stub` |
| `scripts/modes/office.yaml` | Office 默认值 | `high=0.80` `low=0.55` `ttl=14d` `materialize=none` |
| `manifest.yaml` | 包清单 | 版本、入口、零依赖、权限边界（只写 `.cm/`） |

### 3.4 测试

| 文件 | 用例数 | 职责 | 关键覆盖 |
|------|--------|------|----------|
| `scripts/tests/test_core.py` | 85 | 功能 / 路由 / 打包 / 分拣 / 评估 / M3 / 契约 / 异常 / 约束 / 性能十类自检（2 项 V9 N/A 跳过） | 分类忽略、增量幂等、断链 30 条精确计数、漂移/孤儿、技能冲突、指纹一致、准入四问、confidence 复算、plan 不落盘、D1 两次执行、confirm 不计执行、幂等 5 次仅写 1 次、三类 op 回滚哈希还原、冲突中止、pack 预算与只读、triage 状态迁移、eval_golden P/R/F1 与 κ、index 增量/check、skill lint 五类问题、契约结构/三端副本/selfcheck/release_check/Pro coverage、V9 十二例、CLI 退出码、V1/V2/V6/V8 |

---

## 4. 核心流程索引

### 4.1 首次体验 `cm init --scan --doctor`

```
读取 --mode
  ↓                          ↓                          ↓
default_config()         load_mode()               init_workspace()
store.py                 store.py                  store.py
  ↓
load_config() → scan() → doctor()
store.py        scanner.py  report.py
  ↓
format_init() + format_scan() + format_doctor()
report.py
```

### 4.2 扫描（增量）

```
iter_files()  →  跳过 ignore / 符号链接
  ↓
size 未变且已有记录 → unchanged（不读文件）
  ↓
sha256_file() → classify()
  ├─ 文本：读正文 → title / frontmatter / links → upsert docs + edges
  ├─ 二进制 / 超大：只登记元数据 → upsert docs
  └─ SKILL.md：解析 name / version / triggers → upsert skills
  ↓
未出现的历史记录 → status='orphan'
  ↓
commit
```

### 4.3 体检

```
edges(kind=references) → 目标不存在 → broken_links
os.walk 文件集合 − 已登记集合      → orphan_files
逐条重算 sha256 对比索引           → index_drift
skills 重名 / 缺版本 / 触发词交集   → skill_conflicts
sessions 超过 TTL 50% 未分拣       → stale_sessions
pending(state='open')              → pending_backlog
codemap：行号越界 / 无文档代码 / 漂移 → anchor_out_of_range / code_without_doc / doc_drift
  ↓
recommendations() → contract.health_of(good / attention / poor)
```

### 4.4 路由与写入

```
route(content) → signature.describe() → _detect() → primary / attachments
  → executions(90d) + intent_confirms → admission.evaluate()
  → confidence_parts → confidence → patch
  → plan：只写 runs / pending
  → apply：apply_patch() → .cm/backup/<run_id>/ + manifest.json → apply_runs
rollback(run_id) → 校验 after_sha256 → 逆序还原 → manifest.status=rolled_back
```

### 4.5 打包与分拣

```
pack(query, budget) → keywords → docs/skills 打分 → edges 一跳 +0.5
  → 排序 → 预算内贪心 → items（指针）/ skipped / truncated

triage() → 过期会话列表 + open 待定项
  ├─ --expire-sessions → sessions.triaged_at = now
  └─ --drop-pending    → review_count>=3 → dropped；其余 +1
```

### 4.6 黄金集评估

```
eval_golden.py --golden x.jsonl [--pred p.jsonl]
  → reference / predictions / annotations
  → 每类 P/R/F1 + 宏平均 + 准确率
  → 高置信精确率（>=0.80）+ ECE（10 桶）+ Cohen's κ
  → pass / below_threshold / insufficient（退出码 0 / 1 / 2）
```

### 4.7 索引与技能检查

```
cm index [--check]
  ├─ 默认：scanner.scan(增量) → report.doctor()
  └─ --check：直接 report.doctor()（只读）
  → counts{docs, skills, broken_links, orphan_files, index_drift}

cm skill lint
  → 遍历 SKILL.md → 解析 frontmatter
  → missing_version / duplicate_name / trigger_overlap
  → triggers_not_list / missing_dependency
  → issues + summary（发现 issues 仍退出 0）
```

### 4.8 契约与自检

```
references/metrics-contract.json（唯一事实源）
  ├─ 免费版：core.contract.load → report.PROBLEM_KEYS / health_of / 体检表标签
  ├─ Pro：report.py 读包内副本 → schema_version / ratios / coverage
  └─ 后端：cogsteward.js require 副本 → METRICS / RATIOS / health

cm selfcheck → 契约结构 / report 口径 / health 三档 / 工作区是否初始化
scripts/release_check.py → 三端副本 sha256 / 契约结构 / 版本号 / health 抽样
```

---

## 5. 配置参数索引

加载优先级：

```
内置默认值（store.default_config）
    ↓ 覆盖
scripts/modes/<mode>.yaml（仅 init 时读取）
    ↓ 覆盖
工作区 .cm/config.yaml（运行时唯一事实来源）
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `mode` | `dev` | `dev` / `office` |
| `apply` | `false` | 写入模式，M1 恒为 plan |
| `signature_salt` | 随机 32 位十六进制 | 每工作区独立，指纹加盐 |
| `high_threshold` | 0.80 | confidence 高阈值 |
| `low_threshold` | Dev 0.50 / Office 0.55 | confidence 低阈值 |
| `session_ttl_days` | Dev 7 / Office 14 | 会话 TTL |
| `materialize` | Dev `stub` / Office `none` | 从属引用物化策略 |
| `max_attachments` | Dev 3 / Office 0 | 从属引用上限 |
| `max_text_bytes` | 10 MB | 超过按二进制登记，不读正文 |
| `traces_summary` | `false` | 是否记录 200 字摘要 |
| `weight_evidence` | 0.35 | confidence 证据权重 |
| `weight_consistency` | 0.30 | confidence 一致性权重 |
| `weight_history` | 0.20 | confidence 历史权重 |
| `weight_conflict` | 0.15 | confidence 冲突权重 |
| `confirm_ttl_days` | 90 | 用户确认有效期 |
| `ignore` | `.git` `node_modules` `__pycache__` `.cm` `.venv` `.idea` `.vscode` `.trae` `dist` `build` | 扫描排除目录 |

---

## 6. 测试体系

运行方式（需在仓库外副本执行，工作区不可信）：

```bash
cp -R cognition-manager /tmp/cm-verify
cd /tmp/cm-verify
python3 -m unittest discover -s scripts/tests -v
```

| 类别 | 用例 | 结果 |
|------|------|------|
| 核心功能 | 初始化、增量幂等、分类忽略、断链/孤儿/漂移、技能冲突、会话积压、CLI | 16/16 通过 |
| 路由 / 回滚 | 指纹一致与加盐、A1–A4、confidence 复算、plan 不落盘、D1 两次执行、confirm 不计执行、幂等、三类 op 回滚与冲突中止 | 16/16 通过 |
| 打包 / 分拣 / 评估 | pack 预算与只读、triage 演练与迁移、eval_golden P/R/F1、κ、阈值与退出码 | 11/11 通过 |
| M3 索引 / 技能检查 | index 增量与 `--check` 只读、skill lint 五类问题与退出码 | 8/8 通过 |
| 契约治理 | 契约结构 / 阈值单调 / 三端副本 sha256 / selfcheck / release_check / Pro coverage | 7/7 通过 |
| 约束 | V6 零第三方依赖、V8 无内部私有数据、平台目录、frontmatter 必填 | 4/4 通过 |
| 验收 | V1 首次体验、V2 1000 文件扫描 | 通过，见 §7 |
| 异常（V9） | 空工作区、只读、超限、非 UTF-8、符号链接环、空格/中文、大小写、权限、损坏库、并发写；磁盘满 / 中断恢复 N/A | 10 实测 + 2 跳过 |

---

## 7. 验收证据（M1 / M2）

| 标准 | 判定 | 实测 |
|------|------|------|
| V1 首次体验 ≤ 30s | 1000 文件 fixture，冷启动 `init --scan --doctor` | **0.89s** |
| V2 1000 文件索引 ≤ 3s | 同一 fixture，`scan --full` | **1.66s** |
| V6 零第三方依赖 | AST 扫描 `scripts/core/*.py` + `cm_cli.py` | 0 命中 |
| V8 无内部私有数据 | 敏感词扫描（内部模块名、绝对路径等） | 0 命中 |
| 报告可读性 | 六指标 + 结论 + Top-3 建议，断链定位到具体文件 | 通过（人工走查） |
| 路由契约 | `route --json` 字段齐全，confidence 可由 parts 复算 | 通过（自检） |
| plan 不落盘 | 高置信 doc 路由后工作区文件集合不变 | 通过（自检） |
| 写入幂等 | 同一 key 连续 5 次 apply，仅 1 条 apply_runs / 1 个文件 | 通过（自检） |
| 回滚完整性 | create / modify / delete 三类 op 哈希 100% 还原 | 通过（自检） |
| 回滚安全 | 后续手改导致冲突时整体中止，不部分回滚 | 通过（自检） |
| 打包预算 | `pack --budget {1,5,12,40}` 估算量恒不超预算，工作区文件不变 | 通过（自检） |
| 分拣默认安全 | `triage` 默认 dry-run 不修改状态；显式开关才迁移 | 通过（自检） |
| 评估器不伪造 | 缺预测 / 缺 confidence 时 `status=insufficient`，退出码 2 | 通过（自检） |
| 索引只读校验 | `index --check` 不新增登记、不改变 `index.db` 内容 | 通过（自检） |
| 技能检查不误阻断 | `skill lint` 发现问题仍退出 0，仅用法错误退 2 | 通过（自检） |
| 三端口径一致 | 三份 `metrics-contract.json` sha256 相同，`release_check.py` 4 项 PASS | 通过（自检） |
| 安装自检 | `cm selfcheck` 契约 / 口径 / health 三项 PASS | 通过（自检） |
| Pro 覆盖透明 | 缺 `orphan_files` 时输出 `coverage.orphan=unavailable`，不冒充 0 | 通过（自检） |

环境：macOS，Python 3.12.7，SQLite 3.45.3，FTS5 可用。

---

## 8. 技术债

| # | 项 | 影响 | 计划 |
|---|---|---|---|
| T1 | ~~V9 十二条例外路径仅覆盖 3 条~~ | M3 已补齐 10 条实测 + 2 条 N/A 说明 | 已完成 |
| T2 | ~~`pack` / `triage` 未实现~~ | 已在 M2b 交付 | 已完成 |
| T3 | 黄金集仅占位，`eval_golden.py` 尚未接入真实标注 | V4 / V13 无法验收 | 需人工标注 Dev ≥100 / Office ≥80 条 |
| T4 | 路由启发式未用真实语料校准 | 关键词阈值可能偏松 / 偏紧 | V13 校准 |
| T5 | 3 位真实用户访谈未完成 | Office 词表与模型缺外部证据 | M1 并行 |
| T6 | 平台付费技能是否强制云端执行未知（SPIKE U1） | 影响分发形态 | 上架前向平台确认 |
| T7 | apply 未与 V12 门禁硬绑定 | 存在误开启风险 | V12 通过后补门禁 |
| T8 | `pack` token 估算按字节近似 | 中英混排偏差约 ±30% | 真实语料校准后再定 |
| T9 | V9 磁盘满 / 中断恢复未自动化 | 极端环境未实测 | 后续引入故障注入或小容量 tmpfs |
| T10 | 三端契约副本靠闸门约束一致 | 若绕过 `release_check.py` 直接发版仍可能漂移 | 发版流程固定先跑闸门；后续考虑构建期生成 |
| T11 | ~~后端 1.2.0 尚未部署~~ | 2026-11-20 已通过 `audit.sh deploy` 部署（`src/` + `package.json`，备份 `app-20261120-174109`），health 与 402 回归通过 | 已完成 |
| T12 | OC-08 商品文案生成 / OC-09 观测聚合未完成 | 商品页仍手写指标文案；后端未按 schema_version 聚合 | 商品页改版时接入 |

---

## 9. 快速导航

| 想了解 | 去看 |
|---|---|
| 产品契约与验收标准 | [SPEC v0.5](../SPEC-认知管家-WorkBuddy技能封装-v0.5.md) |
| 架构、算法、数据流、异常与扩展 | [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md) |
| 命令参数、JSON 输出、退出码 | [API_SPEC.md](./API_SPEC.md) |
| 每次变更的原因与回滚 | [CHANGELOG.md](./CHANGELOG.md) |
| 数据表与状态机 | [references/schema.md](../cognition-manager/references/schema.md) |
| 路由判定与 confidence | [references/routing-matrix.md](../cognition-manager/references/routing-matrix.md) |

---

**文档版本**: v1.4
**最后更新**: 2026-11-20
