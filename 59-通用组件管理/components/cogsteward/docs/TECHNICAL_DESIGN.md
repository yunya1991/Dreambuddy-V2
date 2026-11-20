# 认知管家（CogSteward）— 技术设计

> **版本**: v1.4 | **更新日期**: 2026-11-20
> **定位**: 认知管家组件技术架构设计，对齐 [DOC_STANDARD.md](../../../../0-系统文档管理/1-规范体系/DOC_STANDARD.md) §3.2
> **实现范围**: M2（`init` / `scan` / `doctor` / `route` / `mark-done` / `rollback` / `config`）

---

## 1. 概述

### 1.1 系统定位

认知管家是工作区的**上下文治理层**：判断信息该不该记、该放哪、该调谁。它不是检索服务，也不托管向量库，只在本地登记与体检。

### 1.2 设计目标

- **零依赖**：仅 Python 标准库，用户无需安装任何包
- **本地优先**：状态全部在工作区 `.cm/`，默认不存正文、不发网络请求
- **可验收**：一次 `doctor` 给出九类可复核指标，而不是主观评价
- **可移植**：同一内核，Dev / Office 只差配置
- **安全默认**：所有写入默认 `plan`，`apply` 必须显式开启

### 1.3 业务边界

| 职责 | 归属 |
|---|---|
| 扫描登记、断链/孤儿/漂移、技能冲突、体检 | 本组件 |
| 文档正文检索、向量召回 | 不做（Pro / 外部工具） |
| 交易域策略、业务代码 | 不做 |
| 平台技能运行时、沙箱策略 | WorkBuddy 平台 |

---

## 2. 架构设计

### 2.1 分层架构

```
┌──────────────────────────────────────────┐
│ 入口层  cm_cli.py                         │
│ argparse 解析 → 命令分发 → 错误码映射       │
└───────────────────┬──────────────────────┘
                    ↓
┌──────────────────────────────────────────┐
│ 核心层  scripts/core/                     │
│  store.py     配置 / SQLite / schema       │
│  scanner.py   遍历 / 分类 / 哈希 / 链接     │
│  report.py    指标 / 建议 / 人类可读输出    │
│  signature.py 意图指纹归一化 + 加盐哈希     │
│  admission.py 记忆准入四问                  │
│  router.py    判定树 / confidence / patch  │
│  apply.py     快照 / 落盘 / 逆序回滚        │
│  pack.py      token 预算打包（只读）        │
│  triage.py    会话 / 待定项分拣              │
└───────────────────┬──────────────────────┘
                    ↓
┌──────────────────────────────────────────┐
│ 状态层  工作区 .cm/                        │
│  config.yaml  index.db(WAL)  traces/       │
│  backup/  cache/                           │
└──────────────────────────────────────────┘
```

约束：`core` 只允许导入标准库与同包模块；`report` 不写库；`scanner` 不打印；`cm_cli` 不直接拼 SQL。

### 2.2 模块关系

```
cm_cli ──▶ store ──▶ sqlite3
   │          ▲
   ├──▶ scanner ──┘
   ├──▶ report ──▶ scanner（复用哈希与遍历）
   ├──▶ router ──▶ signature / admission / apply / store
   ├──▶ pack ─────▶ signature / store（只读查询）
   ├──▶ triage ───▶ store（sessions / pending）
   └──▶ apply ───▶ store（备份目录与 apply_runs）
```

- `store` 是唯一 schema 与配置入口
- `scanner` 依赖 `store` 的连接与 YAML 解析
- `report` 只读连接，复用 `scanner.sha256_file()` 与 `scanner.iter_files()`
- `router` 只做判定与 patch 生成；落盘统一交给 `apply`，保证快照与回滚一致
- `pack` 只查 `docs` / `skills` / `edges`，不读正文、不写库
- `triage` 是唯一修改 `sessions` / `pending` 状态的模块，默认演练

---

## 3. 核心算法

### 3.1 增量扫描

**判定**：同一路径的 `size` 与记录一致时跳过读取（`--full` 强制重算）。

```
if not full and indexed.size == stat.size:
    unchanged += 1; continue
digest = sha256(file)
```

伪代码：

```python
for path in iter_files(root, ignore):
    if path.is_symlink(): continue
    if not full and cached_size(path) == stat.st_size:
        seen.add(rel); continue
    digest = sha256_file(path)
    if path.name.lower() == "skill.md":
        upsert_skill(parse_frontmatter(text))
    elif classify(path) == "text" and size <= max_text_bytes:
        upsert_doc(text, links=extract_links(text))
    else:
        upsert_doc(metadata_only=True)
mark_missing_as_orphan(seen)
commit()
```

**取舍**：不比较 mtime，只比较 size。同尺寸内容修改会漏检，由 `doctor` 的哈希重算兜底（漂移检测）。

### 3.2 文件分类

| 类别 | 判定 | 处理 |
|---|---|---|
| 文本 | 扩展名在 `TEXT_EXTS`，且 `size ≤ max_text_bytes` | 读取正文，抽标题 / frontmatter / 链接 |
| 二进制 | 扩展名在 `BINARY_EXTS` 或未知扩展名 | 只登记路径、大小、哈希 |
| 超大 | `size > max_text_bytes` | 按二进制处理，避免 OOM |
| 技能 | 文件名 `SKILL.md`（大小写不敏感） | 解析 `name / version / triggers` |

排除目录：`.git` `node_modules` `__pycache__` `.cm` `.venv` `.idea` `.vscode` `.trae` `dist` `build`；符号链接一律跳过，避免环。

### 3.3 链接解析

```python
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
```

- 跳过 `http/https/mailto/tel/ftp/data/javascript`、纯锚点 `#...`、绝对路径 `/...`
- 去 `#fragment` 与 `?query`，URL 解码
- 相对 `src` 所在目录归一化；越出工作区（`../` 到根外）丢弃
- 结果写 `edges(src, dst, kind='references')`；每次重扫先删该 `src` 的旧引用

### 3.4 体检指标

| 指标 | 计算 | 说明 |
|---|---|---|
| 断链数 | `edges(kind='references')` 中 `dst` 不存在 | 只统计本地引用，`DISTINCT (src,dst)` |
| 孤儿文件 | 磁盘文件集合 − `docs.path ∪ skills.path` | 排除 ignore 规则 |
| 索引漂移 | 逐条重算哈希；缺失记 `missing`，不一致记 `hash_mismatch` | docs 与 skills 都检查 |
| 技能冲突 | 重名 / 缺 `version` / `triggers` 两两交集 | 每个冲突为一条明细 |
| 会话待分拣 | `triaged_at IS NULL` 且年龄 > TTL/2 | TTL 来自模式配置 |
| 待定积压 | `pending.state='open'` 计数 + 最老等待小时 | 无记录时为 0 |
| 行号越界 | 文档 `#L起-L止` 越界（起<1 / 止<起 / 止>文件行数） | 目标缺失归断链；同键去重 |
| 无文档代码 | 含 `INDEX.md` / `SKILL.md` 目录中未被任何已索引文档引用的源码 | 扩展名白名单 |
| 文档漂移 | 被引用文件 mtime 比引用文档晚 ≥3 天 | 索引/变更记录作为来源不计 |

九项指标的标签、阈值、权重与占比分母统一来自 `references/metrics-contract.json`（见 §12.4），代码只负责采集。

健康度：异常指标类别数 0 → `good`；1–2 → `attention`；≥3 → `poor`。

### 3.5 路由判定与置信度（M2）

判定树以关键词启发式落地，不调用模型：

| 分支 | 命中条件 | 主载体 |
|---|---|---|
| D1 可复用 | 强词（清单 / 流程 / 步骤 / 脚本 / 自动化 / SOP / runbook）或 2 个弱词 / 1 弱词 + 编号步骤 | `skill` |
| D2 稳定性 | 规范 / 标准 / 事实 / 定义 / 接口 / 架构 / 说明 / 文档 / 约定等 | `doc` |
| D3 经验性 | 坑 / 教训 / 结论 / 取舍 / 经验 / 反模式 / 注意等 | `memory`（须过准入） |
| 默认 | 以上均未命中 | `session` |

多命中按「可复用 > 稳定性 > 经验性」定主载体，其余进入 `attachments[]`（受 `max_attachments` 限制；Office 为 0）。分数并列且互斥时进入 `alternatives[]`，`conflict=0.5`。

```
confidence = 0.35·evidence + 0.30·consistency + 0.20·history + 0.15·(1 − conflict)
```

| 分量 | 实现 |
|---|---|
| `evidence` | 内容中出现已存在路径 / 近 90 天有执行 / 准入 derivable → 1.0；仅确认 → 0.6；否则 0.3 |
| `consistency` | 单命中 1.0；多命中且主载体明确 0.8；互斥未决 0.5；仅默认 0.2 |
| `history` | `min(executions / 5, 1.0)`，只统计 `source ∈ {record, mark_done}` |
| `conflict` | 仅 `alternatives` 非空时 0.5 |

D1 执行次数不足 2 时 `requires_user_confirm=true`；`cm route --confirm` 写 `intent_confirms`（默认 90 天），豁免确认但**不增加执行计数**。

### 3.6 准入（M2）

`admission.evaluate()` 只对 `memory` 生效，默认拒绝：

- A1 只接受 `derivable_from`（路径必须存在）/ `not_derivable` / `unknown`；`derivable_from` 仅存指针
- A2 有 `ssot_path` 时只写指针
- A3 `none` → 降级 `observation`，置信度上限 0.5
- A4 `no` → 拒绝写入；`unknown` → TTL ≤ 30 天
- 任意项 `unknown` → `pending`，写入 `pending` 表，不进入检索

### 3.7 写入与回滚（M2）

```
patch.files[] {op, path, sha256, content}
  → 校验 op / 重复路径 / 哈希 / 文件数 ≤ 10
  → 快照受影响文件到 .cm/backup/<run_id>/files/
  → 写 manifest.json(status=prepared)
  → create / modify 原子写；delete 删除；逐文件校验 sha256
  → manifest.status=applied；apply_runs 记录 idempotency_key
```

回滚：

```
读 manifest → 逆序处理
  → 先校验每个文件当前 sha256 == after_sha256
  → 任一不一致：整体中止，返回 conflicts
  → create → 删除；modify / delete → 从 backup 还原并校验 before_sha256
  → manifest.status=rolled_back
```

同一 `idempotency_key` 只允许一次 apply；重复调用返回 `replayed=true`，不写文件。

### 3.8 上下文打包（M2b）

`pack.pack()` 只读，不读正文，只用索引元数据与磁盘 `stat`：

```
query → signature.tokenize(clean(query)) → 去重，最多 32 个关键词
docs   ：标题命中 2.0 / 路径命中 1.0
skills ：name 作标题，triggers 命中 1.5，path 命中 1.0
edges  ：一跳关联（引用 / 被引用）各 +0.5
排序   ：(-score, estimated_tokens, path)
裁剪   ：used + cost ≤ budget 才入选，否则 skipped += 1
```

`estimated_tokens = max(1, round((size // 3) / 1.5))`：按 UTF-8 中文 3 字节/字符、1.5 字符/token 粗估。恒有 `estimated_tokens ≤ budget`，不产生任何文件写入。

### 3.9 分拣（M2b）

```
triage(root, config, conn, expire_sessions=False, drop_pending=False)
  sessions：triaged_at IS NULL AND expires_at < now → 列表
      --expire-sessions → triaged_at = now（标记已回收）
  pending ：state='open' → 列表
      --drop-pending → review_count >= 3 → state='dropped'
                        其余 → review_count += 1
```

默认 `dry_run=true`，只列不改；两个开关都未给出时不执行任何 UPDATE。`sessions` 表不新增状态列，用 `triaged_at` 表示「已处理（含过期回收）」；该取舍记录于 §10 D11。

### 3.10 黄金集评估（M2b）

`eval_golden.py` 是独立只读脚本，不进入 CLI：

```
JSONL 标注 → reference（同 id 首次 label）+ predictions（同 id 后写覆盖）+ annotations（按 labeler）
  → 每类 P/R/F1（tp/fp/fn）+ 宏平均（仅统计出现过的类别）+ 准确率
  → 高置信分组（confidence >= 0.80）精确率
  → ECE（10 桶，按样本占比加权）
  → Cohen's κ（同 id 双标注；无配对时 value=null）
  → 阈值：高分组精确率 >= 0.90 或 ECE <= 0.15
```

缺预测 / 缺 confidence 时 `status=insufficient` 并退出码 2，输出「需人工标注」，不填补任何默认值。

### 3.11 索引总览（M3）

`cm index` 分两种模式：

```
默认：scanner.scan(full=False) → report.doctor()
  → counts{docs, skills, broken_links, orphan_files, index_drift}
  → details（各最多 20 条）+ notes（扫描摘要）
--check：跳过扫描，直接 report.doctor()
  → 只读校验，不写 index.db
```

`docs` / `skills` 只统计 `status='active'`；断链 / 孤儿 / 漂移复用 `doctor` 的判定逻辑，避免两套口径。写盘仅限 `.cm/index.db`。

### 3.12 技能规范检查（M3）

`cm skill lint` 直接读取每个 `SKILL.md` 的 frontmatter（不依赖索引是否最新）：

```
iter_files → 过滤 SKILL.md → 解析 frontmatter（行内列表 + 缩进块列表）
  ├─ missing_version：version 为空
  ├─ duplicate_name：name 重复
  ├─ trigger_overlap：触发词两两求交
  ├─ triggers_not_list：triggers 存在但不是列表
  └─ missing_dependency：depends_on 按名称 / 相对路径 / 目录名均未命中
```

严重级别：重名与缺依赖为 `error`，其余为 `warning`。发现 issues 仍返回 0；`cm skill` 不带子命令时返回 2。

---

## 4. 数据流

### 4.1 初始化

```
cm init --mode dev
  → 创建 .cm/{traces,backup,cache}
  → modes/dev.yaml → config.yaml（含随机 salt）
  → index.db：schema v1 + docs_fts
  → 返回 mode / fts / status(created|existing)
```

已有 `config.yaml` 时不覆盖（`--force` 才重写），索引保留。

### 4.2 扫描

```
磁盘文件 → iter_files → 增量判定 → 哈希/读取
  ├─ docs 表（文本 / 二进制）
  ├─ skills 表（SKILL.md）
  ├─ edges 表（本地链接）
  └─ docs_fts（path + title）
  → 消失的文件标 orphan
```

### 4.3 体检

```
index.db + 磁盘实际状态
  → 九类指标
  → recommendations（最多 3 条）
  → health
  → 人类可读报告 / JSON
```

体检只读，不修改索引；修复动作由 `scan` 承担。

### 4.4 路由

```
内容 → signature.describe（归一化 + 加盐哈希）
  → _detect（D1/D2/D3 关键词）
  → 主载体 + attachments + alternatives
  → 近 90 天 executions / intent_confirms
  → 准入（memory 专用）
  → confidence_parts → confidence
  → patch（目标路径 / 内容 / sha256）
  → plan 输出；apply 时 snapshot + 落盘 + apply_runs
  → runs 记录诊断
```

`plan` 只写 `runs` / `pending` 等 `.cm/` 内状态，不写工作区业务文件。

### 4.5 回滚

```
cm rollback <run_id>
  → .cm/backup/<run_id>/manifest.json
  → 校验当前哈希 → 逆序还原
  → manifest.status=rolled_back + apply_runs.rolled_back_at
```

### 4.6 打包

```
cm pack "<任务>" --budget N
  → 关键词切分（bigram / 英文词）
  → docs + skills 打分 → edges 一跳加分
  → 排序 → 预算内贪心入选
  → 输出指针（路径 / 标题 / 估算 token / 理由），不落盘
```

### 4.7 分拣

```
cm triage [--expire-sessions] [--drop-pending]
  → 列出过期会话与 open 待定项
  → 开关打开时迁移 triaged_at / review_count / state
  → 输出演练或处理摘要
```

---

## 5. 接口设计

对外只暴露 CLI（详见 [API_SPEC.md](./API_SPEC.md)）。内部关键签名：

| 模块 | 签名 | 说明 |
|---|---|---|
| store | `init_workspace(root, mode="dev", force=False) -> dict` | 幂等初始化 |
| store | `load_config(root) -> dict` | 未初始化抛 `NotInitialized` |
| store | `connect(root) -> sqlite3.Connection` | WAL；库损坏抛 `CmError(EXIT_DB)` |
| scanner | `scan(root, config, conn, full=False) -> dict` | 登记并返回统计 |
| scanner | `sha256_file(path, chunk_size=1MB) -> str` | 流式哈希 |
| scanner | `iter_files(root, ignore) -> Iterator[Path]` | 跳过符号链接与排除目录 |
| report | `doctor(root, config, conn) -> dict` | 六指标 + 建议 + health |
| report | `format_doctor(result) -> str` | 人类可读，CJK 宽度对齐 |
| signature | `normalize(text) -> str` | 字面归一化 + 去重排序 |
| signature | `describe(text, salt) -> dict` | 指纹 / 归一化串 / 版本 |
| admission | `evaluate(root, primary, facts) -> dict` | A1–A4 与 pending / cap |
| router | `route(root, config, conn, content, ...) -> dict` | 路由契约输出 |
| router | `mark_done(root, config, conn, content, source) -> dict` | 执行计数 |
| apply | `apply_patch(root, run_id, key, patch, conn) -> dict` | 快照 + 落盘 |
| apply | `rollback(root, run_id, conn) -> dict` | 逆序回滚 |
| pack | `pack(root, config, conn, query, budget=2000) -> dict` | 只读打包，预算内指针列表 |
| pack | `estimate_tokens(size_bytes) -> int` | 中文近似 token 估算 |
| triage | `triage(root, config, conn, *, expire_sessions, drop_pending) -> dict` | 默认演练，显式开关才迁移 |
| eval_golden | `evaluate(reference, predictions, annotations, bins) -> dict` | P/R/F1 + 校准 + κ |

---

## 6. 状态管理

### 6.1 状态目录

```
.cm/
├── config.yaml   # 唯一运行时配置
├── index.db      # SQLite，WAL
├── traces/       # 预留：路由与体检流水（jsonl）
├── backup/       # 预留：apply 前快照
└── cache/        # 预留
```

### 6.2 状态机

| 对象 | 状态 |
|---|---|
| doc | `active` → `stale` → `orphan` → `archived`（M1 只写 `active` / `orphan`） |
| skill | `draft` → `active` → `deprecated` → `archived`（M1 只写 `active` / `orphan`） |
| pending | `open` → `reviewed` → `accepted` / `dropped`（M2 只写 `open`） |
| session | `open` → `triaged` / `expired`（M2 只写入） |
| apply run | `prepared` → `applied` → `rolled_back`（manifest 状态机） |

### 6.3 隐私

- 不保存正文；`docs` 无 body/content 列（自检用例断言）
- `traces_summary=false` 时不写摘要
- 指纹加盐，salt 随工作区生成，不跨工作区复用

---

## 7. 配置管理

优先级与完整参数见 [ENGINEERING_INDEX.md](./ENGINEERING_INDEX.md#5-配置参数索引)。

要点：

- `modes/*.yaml` 只在 `init` 时参与生成 `config.yaml`
- 运行期只读 `config.yaml`，因此**双版本切换不改内核**
- 缺失键回落到 `default_config()` 内置值，旧配置可向前兼容
- 布尔值支持 `true/false/on/off/yes/no`，由内置扁平 YAML 子集解析器处理

---

## 8. 错误处理

### 8.1 退出码

| 码 | 含义 | 触发 |
|---|---|---|
| 0 | 成功 | 正常完成（体检异常不算错误） |
| 2 | 用法错误 | 缺少子命令 / 非法参数 |
| 3 | 未初始化 | `.cm/config.yaml` 或 `index.db` 不存在 |
| 4 | 数据库不可用 | 损坏、schema 缺失 |
| 5 | 文件系统错误 | 权限拒绝、路径不可写 |
| 130 | 用户中断 | Ctrl-C |

### 8.2 降级策略

| 场景 | 行为 |
|---|---|
| FTS5 不可用 | `docs_fts` 创建失败被捕获，核心登记继续，`init` 报告 `fts=false` |
| 单个文件读取失败 | 计入 `errors`，继续扫描，不中断整体 |
| 超大文件 | 按二进制登记，不读正文 |
| 符号链接 | 跳过，避免环 |
| `apply` 被沙箱拦截（M2） | 自动回落 `plan`，不重试 |

---

## 9. 扩展性设计

| 新增内容 | 步骤 |
|---|---|
| 新命令 | `cm_cli.build_parser()` 注册 → `cmd_xxx()` → 复用 `store/report`；在 SKILL.md 命令表登记 |
| 新指标 | `report.doctor()` 增加计算 → `metrics` / `details` → `recommendations()` 增加建议 → 更新 API_SPEC |
| 新模式 | 新增 `scripts/modes/<mode>.yaml` → `init --mode` 可选值 → 不改内核 |
| 新文本类型 | `scanner.TEXT_EXTS` 增加扩展名 → 同步 `DOC_TYPE_BY_EXT` |
| 新关系类型 | `edges.kind` 枚举扩展 → 更新 `references/schema.md` 与 routing-matrix |

---

## 10. 与 SPEC v0.5 的偏差

| # | 偏差 | 原因 | 影响 |
|---|---|---|---|
| D1 | `skills` 表增加 `id` 主键，`path` 唯一 | 同名技能不应互相覆盖，冲突需可诊断 | 表结构多一列，`name` 不再唯一 |
| D2 | `init` 增加 `--force` | 否则模式无法切换（默认不覆盖用户配置） | 无 |
| D3 | 自检放 `scripts/tests/` | 平台只允许 `SKILL.md/references/scripts/templates`，根级 `tests/` 有风险 | 无 |
| D4 | `references/golden/` 仅占位 README | 黄金集按 SPEC 为 M2 交付 | V4 验收延后 |
| D5 | SPEC §7 的 `signature.py/router.py/...` 尚未创建 | 属于 M2/M3 能力 | M2 已补齐核心四模块 |
| D6 | A1 的 `not_derivable` 视为合法判定，不拒写 | SPEC §5.4 表格写「not_derivable → 拒写」，但 §5.5 输出示例为 `passed=true`；按示例与「记忆只存指针」语义实现 | 需要在 SPEC 升版时统一措辞 |
| D7 | `patch.files[]` 增加 `content` 字段 | SPEC 仅列 `op/path/sha256`，没有内容无法落盘 | 对外契约新增可选字段，旧消费者可忽略 |
| D8 | 技能目标默认 `skills/<slug>/`，同名不同内容时用 `skills/<slug>-<sig8>/` | 防止覆盖用户既有技能 | 路径可读性略降 |
| D9 | `apply` 未与 V12 验收门禁硬绑定 | V12/V13 尚未完成，M2 需要可执行的回滚闭环 | V12 通过前只建议在测试工作区开启 |
| D10 | `evidence` 的文件证据来自内容中真实存在的路径引用 | 不做全文检索，避免把「碰巧相关」当证据 | 无路径引用时 evidence 回落到 0.3 / 0.6 |
| D11 | 过期会话用 `sessions.triaged_at` 标记，不新增 `state` 列 | 避免 schema v3 迁移；`triaged_at` 已能表达「已处理」 | 无法区分「人工分拣」与「过期回收」，只能看创建/过期时间 |
| D12 | `triage --drop-pending` 不校验准入是否仍为 unknown | `pending` 表未持久化准入结果，只有 `payload_ref` | `review_count>=3` 一律丢弃，可能误丢已可判定的条目 |
| D13 | `pack` 的 token 估算基于文件字节数而非真实分词 | 只读且不保存正文，无法精确分词 | 中英混排文件会有 ±30% 误差，仅用于预算裁剪 |
| D14 | `skill lint` 直接读取 `SKILL.md`，不查 `skills` 表 | 避免「未扫描 / 索引过期」导致漏检；lint 的对象就是文件本身 | 每次 lint 需读取全部技能文件，技能量大时有 IO 成本 |
| D15 | `index --check` 仍对全部登记文件做哈希校验 | 漂移判定必须比对真实哈希；与 `doctor` 共用同一套只读逻辑 | 大型工作区 `--check` 耗时与 `doctor` 相同 |
| D16 | `depends_on` 同时接受名称、相对路径与目录名 | 三种写法在现有技能仓库中并存，严格只认一种会大量误报 | 依赖解析偏宽松，可能漏掉「同名不同路径」的歧义 |
| D17 | 指标契约用 JSON 而非 YAML | 保持零第三方依赖（免 PyYAML），Node 后端可直接 `require` | 契约无注释；变更说明写在 CHANGELOG |
| D18 | 三端各带一份契约副本，而非构建期生成 | 免费版本地安装、Pro 经 SkillHub 分发、后端独立部署，无共享构建流程 | 必须由 `release_check.py` 保证逐字节一致 |
| D19 | 契约含 `stale_session_rate`，但标记 `informational` | 后端历史上输出该占比，保留以兼容 | 免费版 / Pro 报告多一行「参考」占比，不参与评分 |

以上偏差不改变产品契约；如后续 SPEC 升版，应合并进正式版本记录。

### 10.1 V9 十二例异常路径

| # | 场景 | 处理方式 | 自检 |
|---|---|---|---|
| 1 | 空工作区 | 扫描 0 文件，体检 `good` | 实测 |
| 2 | 只读工作区 | `init` 失败，退出码 5 | 实测（root 跳过） |
| 3 | 超过 `max_text_bytes` | 按二进制登记，不读正文、不建 edges | 实测 |
| 4 | 非 UTF-8 文本 | `errors="ignore"` 读取，标题回落到文件名 | 实测 |
| 5 | 符号链接环 | `followlinks=False` 且跳过 symlink 文件 | 实测 |
| 6 | 空格 / 中文文件名 | 原样登记为 POSIX 相对路径 | 实测 |
| 7 | 大小写差异路径 | 保留原始大小写，重复扫描不产生重复行 | 实测 |
| 8 | 权限拒绝 | 计入 `errors`，不中断整轮扫描 | 实测（root 跳过） |
| 9 | 数据库损坏 | `store.connect` 抛 `EXIT_DB`，CLI 退出码 4 | 实测 |
| 10 | 并发写 | 3 线程同时全量扫描，WAL + 5s busy timeout | 实测 |
| 11 | 磁盘空间不足 | N/A：需 mock `os.write` 抛 `ENOSPC`，当前回归未覆盖 | 跳过并注明构造方法 |
| 12 | 中断恢复 | N/A：增量扫描幂等，重跑可自愈；SIGINT 注入需改产线代码 | 跳过并注明构造方法 |

N/A 共 2 项，其余 10 项均有可执行用例。

---

## 11. 已知限制与下一步

| 限制 | 下一步 |
|---|---|
| 黄金集仅有占位 README | 需人工标注 Dev ≥100 / Office ≥80 条后接入 `eval_golden.py` |
| `pack` token 估算为字节近似 | 真实语料校准后再决定是否引入分词表 |
| 路由启发式未做真实语料校准 | V13 校准验收 |
| 无真实用户访谈 | M1 并行完成 3 位访谈 |
| 平台付费形态未定 | 上架前确认是否强制云端执行 |

---

## 12. 修复复盘与优化清单（v1.4）

### 12.1 背景与现状

把「工作区文档索引整理」当作一次真实回归场景跑完后，暴露出核心问题：**同一套指标被手工抄成三份**（免费版 / Pro 订阅 / 按次后端），任何一次口径调整都要改三处，且没有闸门阻止漏改。本轮把口径收敛为单一契约，并补齐自检与部署工程化。

| 端 | 版本 | 指标数 | 口径来源 | 状态 |
|---|---|---|---|---|
| 免费版 `cognition-manager` | 0.7.0 | 9 | `references/metrics-contract.json` | 已落地，85 项自检（2 项 N/A 跳过） |
| Pro 订阅 `cogsteward-pro` | 1.1.0 | 9 | 包内契约副本 | 已落地，纯计算脚本读契约 |
| 按次版 `cogsteward-pro-pay` | 1.1.0 | 9 | 云端后端契约 | 已落地，SKILL 口径对齐 |
| 后端 `skillhub-audit-api` | 1.2.0 | 9 | `src/metrics-contract.json` | 已部署（`src/` + `package.json`，备份 `app-20261120-174109`），13/13 测试通过 |
| 工程文档 | v1.4 | — | — | 本轮更新 |

### 12.2 复盘发现的 8 项问题

| # | 问题 | 表现 | 根因 | 影响 |
|---|---|---|---|---|
| 1 | 三端口径手工同步 | Pro 仍是 6 项旧口径、按次版落后免费版 | 阈值/权重/标签写死在各自代码里 | 同一工作区三端结论不一致，商品可信度受损 |
| 2 | `health` 只统计六项 | 只有代码-文档异常时仍显示 `good` | 新增三项后未同步 `health` 判定 | 报告结论与明细自相矛盾（0.6.1 已修） |
| 3 | 后端与本地各写一份阈值 | 改一处漏两处 | 无共享事实源 | 云端与本地评分不同 |
| 4 | 发布无一致性闸门 | 只能人眼 diff 三份常量 | 缺少自动校验 | 漂移在上线后才被发现 |
| 5 | 安装后无自检 | 用户装错版本 / 契约缺失不自知 | 无 `selfcheck` | 排障成本高 |
| 6 | 部署靠手写 `rsync + restart` | 无备份、无回归、无回滚 | 脚本只做同步 | 一次坏发布即长时间不可用 |
| 7 | Pro 无 `.cm` 时把孤儿填 0 | 未采集却显示「0 个问题」 | 用 0 冒充「无异常」 | 结论偏乐观，误导用户 |
| 8 | 文档状态漂移 | `SKILL.md` 仍写「v0.6 规划」，docs 未覆盖 0.6/1.0.x | 文档未随实现更新 | 用户按旧预期使用 |

### 12.3 优化清单（OC-01 ~ OC-09）

| ID | 优先级 | 优化项 | 落地方式 | 验收标准 |
|---|---|---|---|---|
| OC-01 | P0 | 指标契约单一源 | 新增 `references/metrics-contract.json` 与 `core/contract.py` | 契约含 9 指标 + 5 占比；结构校验通过 |
| OC-02 | P0 | 阈值数据驱动 + `schema_version` | `report.py` 读契约；三端输出 `schema_version` | 改契约即改口径，代码无需改动 |
| OC-03 | P0 | 发布前一致性闸门 | 新增 `scripts/release_check.py` | 三端契约逐字节一致、版本一致、health 抽样一致 |
| OC-04 | P1 | 安装自检 | 新增 `core/selfcheck.py` 与 `cm selfcheck` | 契约/口径/health 三项 PASS/FAIL 可视 |
| OC-05 | P1 | 三端一致性 fixture 测试 | `ContractCase` 7 项用例（含副本 sha256 比对） | 任一副本漂移即测试失败 |
| OC-06 | P1 | 部署工程化 | `audit.sh deploy`：备份 → 安装 → 重启 → 覆盖回归 → 失败回滚；RUNBOOK S5 重写 | 回归失败自动回滚，无需人工干预 |
| OC-07 | P2 | Pro 孤儿口径透明 | 未提供 `orphan_files` 时输出 `coverage.orphan="unavailable"`，不冒充 0 | 报告显式提示且该项不参与评分 |
| OC-08 | P2 | 商品文案生成 | 由契约生成商品页指标文案 | **未实施**，待商品页改版 |
| OC-09 | P2 | `schema_version` 观测 | 三端响应均带 `schema_version`，后端开始记录 | 响应字段已落地；聚合报表待下期 |

### 12.4 契约 JSON 结构

契约固定四段：`schema_version`、`problem_metrics`（参与 `health` 的指标顺序）、`metrics`（逐项口径）、`ratios`（占比与分母）。

```json
{
  "schema_version": "1.0",
  "problem_metrics": ["broken_links", "orphan_files", "..."],
  "metrics": [
    {
      "key": "broken_links",
      "label": "断链",
      "definition": "索引中的本地引用指向不存在的文件；同一（文档, 目标）只计 1 次",
      "warn_at": 1,
      "high_at": 5,
      "weight": 30,
      "action": "cm index --check 定位失效链接，逐个修复或移入归档目录"
    }
  ],
  "ratios": [
    {
      "id": "broken_link_rate",
      "label": "断链占比",
      "metric": "broken_links",
      "denominator": "documents",
      "warn_at": 1,
      "high_at": 5,
      "weight": 10,
      "informational": false,
      "action": "cm index --check 逐条修复断链"
    }
  ],
  "health": {"ok_max_problems": 0, "attention_max_problems": 2}
}
```

校验规则（`core.contract.validate`）：指标 key 唯一且与 `problem_metrics` 顺序一致；`0 ≤ warn_at < high_at`；`weight ≥ 0`；占比的 `metric` 必须已定义、分母只能取 `documents / skills / sessions`；`0 ≤ ok_max_problems < attention_max_problems`。

### 12.5 发布闸门与安装自检

| 入口 | 位置 | 检查项 | 失败行为 |
|---|---|---|---|
| `scripts/release_check.py` | 发版前 | 三端副本 sha256、契约结构、`manifest/SKILL/__version__` 一致、health 三档抽样 | 退出 1，阻断发版 |
| `cm selfcheck` | 安装后 | 契约结构、`report.PROBLEM_KEYS` 与 `health` 对齐、工作区是否初始化 | 退出 2，输出逐项 PASS/FAIL |

```bash
python3 scripts/release_check.py          # 发版前
python3 scripts/cm_cli.py selfcheck        # 安装后 / 排障时
```

### 12.6 部署与回滚（工程化）

```
bash skills/skillpay-workflow/scripts/audit.sh deploy
  → 远端备份 /opt/skillhub-audit/backups/app-<ts>/（src/ + package.json）
  → 同步 src/ 与 package.json → systemctl restart
  → 回归：is-active + /health + /api/cogsteward 期望 402
  → 任一失败：trap 触发 restore（还原 src/ 与 package.json + 重启）
```

约束：只允许同步 `src/` 与 `package.json`，不覆盖整个 `app/`；密钥不出现在命令输出；回归失败必须回滚而非「先上线再看」。RUNBOOK S5 同步改写（远端 `/home/luke/dreambuddy` 已非 git 仓库，旧的 GitHub 三段式不再适用）。

### 12.7 验收结果

| 项 | 结果 |
|---|---|
| 免费版测试 | 85 项通过（2 项 N/A 跳过），V1 0.90s / V2 0.89s |
| 后端测试 | 13/13 通过（含 9 项指标与占比断言） |
| 发布闸门 | 4 项全 PASS，契约 sha256 三端一致 |
| Pro 覆盖透明 | 缺 `orphan_files` 时输出「未提供孤儿文件指标」 |
| 文档一致性 | `SKILL.md`「v0.6 规划」改为「v0.6 已落地」；本文件与 CHANGELOG / ENGINEERING_INDEX 同步 v1.4 |

### 12.8 遗留与下一步

| 项 | 说明 | 下一步 |
|---|---|---|
| OC-08 商品文案生成 | 契约已可导出标签/阈值，文案模板未做 | 商品页改版时接入 |
| OC-09 观测聚合 | 仅落地响应字段 | 后端按 `schema_version` 聚合成功率与分布 |
| 后端 1.2.0 部署 | 已走 `audit.sh deploy` 上线（`src/` + `package.json`，备份 `app-20261120-174109`），health/402 回归通过 | 完成 |
| 模块 git 跟踪 | `59-通用组件管理/` 整体未跟踪 | 先 `git add` 再 commit，否则无提交记录 |

---

**文档版本**: v1.4
**最后更新**: 2026-11-20
