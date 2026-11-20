# 认知管家（CogSteward）— 接口规格

> **版本**: v1.4 | **更新日期**: 2026-11-20
> **定位**: 认知管家 CLI 对外的命令与数据契约，对齐 [DOC_STANDARD.md](../../../../0-系统文档管理/1-规范体系/DOC_STANDARD.md) §3.3
> **实现范围**: M2 / M2b / M3 / 契约治理（`init` / `scan` / `doctor` / `route` / `pack` / `triage` / `mark-done` / `rollback` / `config` / `index` / `skill lint` / `selfcheck`，以及独立脚本 `eval_golden.py` / `release_check.py`）

---

## 1. 接口概览

### 1.1 接口类型

| 类型 | 数量 | 说明 |
|------|------|------|
| CLI 命令 | 12 | `init` / `scan` / `doctor` / `route` / `pack` / `triage` / `mark-done` / `rollback` / `config` / `index` / `skill lint` / `selfcheck` |
| 独立脚本 | 2 | `eval_golden.py`（黄金集评估）/ `release_check.py`（发布闸门） |
| HTTP API | 0 | 不提供 |
| Python API | 0 | `core` 为内部模块，不承诺稳定性 |

入口：`python3 scripts/cm_cli.py <command> [options]`

### 1.2 接口列表

| 命令 | 作用 | 是否写盘 | 幂等 |
|------|------|----------|------|
| `init` | 创建工作区状态目录与配置 | 是（仅 `.cm/`） | 是（已有配置不覆盖） |
| `scan` | 全量 / 增量扫描登记 | 是（`index.db`） | 是（同输入同结果） |
| `doctor` | 体检 | 否（只读） | 是 |
| `route` | 路由判定与 patch 生成 | 默认否（plan）；apply 时写工作区 | 是（`idempotency_key` 去重） |
| `pack` | 按 token 预算打包上下文指针 | 否（只读） | 是 |
| `triage` | 分拣过期会话与待定项 | 默认否（演练）；显式开关才迁移状态 | 是（重复执行不重复丢弃） |
| `mark-done` | 登记一次真实执行 | 是（`executions`） | 否（每次一条执行记录） |
| `rollback` | 按备份逆序回滚 | 是（还原受影响文件） | 否（同一 run 只允许回滚一次） |
| `config` | 查看 / 修改配置 | 是（`config.yaml`） | 是（同值重复写入结果一致） |
| `index` | 索引总览 | 默认是（增量扫描写 `index.db`）；`--check` 否 | 是 |
| `skill lint` | 技能规范检查 | 否（只读） | 是 |
| `selfcheck` | 安装自检（契约 / 口径 / 版本） | 否（只读） | 是 |

---

## 2. 认证方式

无需认证。纯本地运行，不发起网络请求；写权限以工作区为边界，默认只写 `.cm/`。

---

## 3. 通用参数

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `--root` | string | 否 | 当前目录 | 工作区根目录 |
| `--version` | flag | 否 | — | 输出版本号 |
| `--json` | flag | 否 | false | 输出机器可读 JSON（`init` / `scan` / `doctor` 均支持） |

---

## 4. 接口详情

### 4.1 `cm init`

**作用**：创建工作区状态目录 `.cm/`、写入 `config.yaml`、建库建表。

**参数**：

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `--mode` | enum | 否 | `dev` | `dev` / `office` |
| `--scan` | flag | 否 | false | 初始化后立即扫描 |
| `--doctor` | flag | 否 | false | 初始化后立即体检 |
| `--full` | flag | 否 | false | 配合 `--scan`，忽略增量缓存 |
| `--force` | flag | 否 | false | 覆盖已有 `config.yaml`（索引保留） |

**示例**：

```bash
python3 scripts/cm_cli.py init --scan --doctor
python3 scripts/cm_cli.py --root ~/notes init --mode office --scan --doctor --json
```

**响应（`--json`）**：

```json
{
  "init": {
    "workspace": "/abs/path",
    "cm_dir": "/abs/path/.cm",
    "mode": "dev",
    "status": "created",
    "fts": true,
    "schema_version": 1
  },
  "scan": {
    "scanned": 7, "text": 4, "binary": 2, "skills": 1,
    "unchanged": 0, "errors": 0, "bytes": 2048,
    "missing": 0, "elapsed_seconds": 0.004
  },
  "doctor": { "...": "见 4.3" }
}
```

`status` 取值：`created`（新建）/ `existing`（沿用已有配置）。

---

### 4.2 `cm scan`

**作用**：遍历工作区，登记文本 / 二进制 / 技能，重建本地链接。

**参数**：

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `--full` | flag | 否 | false | 忽略 size 缓存，全部重算哈希 |

**示例**：

```bash
python3 scripts/cm_cli.py scan
python3 scripts/cm_cli.py scan --full --json
```

**响应（`--json`）**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `scanned` | int | 本次实际处理（读哈希）的文件数 |
| `text` | int | 文本类数量 |
| `binary` | int | 二进制 / 超大 / 未知扩展名数量 |
| `skills` | int | 识别到的 `SKILL.md` 数量 |
| `unchanged` | int | 因 size 未变而跳过的文件数 |
| `errors` | int | 读取失败的文件数 |
| `bytes` | int | 处理文件总大小 |
| `missing` | int | 上次登记但本次磁盘上消失的文件数 |
| `elapsed_seconds` | float | 本次耗时 |

**示例**：

```json
{
  "scanned": 0, "text": 0, "binary": 0, "skills": 0,
  "unchanged": 7, "errors": 0, "bytes": 0,
  "missing": 0, "elapsed_seconds": 0.001
}
```

---

### 4.3 `cm doctor`

**作用**：只读体检，输出六类指标与最多 3 条建议。

**参数**：无（除通用参数）。

**响应（`--json`）**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `schema_version` | string | 当前 `1.0` |
| `command` | string | 固定 `doctor` |
| `workspace` | string | 绝对路径 |
| `mode` | string | `dev` / `office` |
| `generated_at` | string | ISO 8601，含时区 |
| `metrics.broken_links` | int | 指向不存在文件的本地引用数 |
| `metrics.orphan_files` | int | 磁盘存在但未登记的文件数 |
| `metrics.index_drift` | int | 哈希不一致或文件消失的条目数 |
| `metrics.skill_conflicts` | int | 重名 / 缺版本 / 触发词重叠数 |
| `metrics.stale_sessions` | int | 超过 TTL 50% 未分拣的会话数 |
| `metrics.pending_backlog` | int | `state='open'` 的待定条目数 |
| `metrics.oldest_pending_hours` | float | 最老待定条目等待小时（无则 0.0） |
| `details` | object | 各指标最多 20 条明细 + `documented` 总数 |
| `recommendations` | string[] | 0–3 条可执行建议 |
| `health` | enum | `good` / `attention` / `poor` |

**示例**：

```json
{
  "schema_version": "1.0",
  "command": "doctor",
  "workspace": "/abs/path",
  "mode": "dev",
  "generated_at": "2026-11-19T16:42:26+08:00",
  "metrics": {
    "broken_links": 1,
    "orphan_files": 0,
    "index_drift": 0,
    "skill_conflicts": 0,
    "stale_sessions": 0,
    "pending_backlog": 0,
    "oldest_pending_hours": 0.0
  },
  "details": {
    "broken_links": [{"src": "README.md", "dst": "docs/missing.md"}],
    "orphan_files": [],
    "index_drift": [],
    "skill_conflicts": [],
    "documented": 3
  },
  "recommendations": [
    "先修断链：1 条引用指向不存在的文件（例如 README.md → docs/missing.md），优先处理入口索引类文档"
  ],
  "health": "attention"
}
```

---

### 4.4 `cm route`

**作用**：按判定树给出主载体、从属引用与置信度；默认 `plan` 只输出 patch 摘要。

**参数**：

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `<content>` | string | 是 | — | 待路由内容（多段自动空格拼接） |
| `--apply` | flag | 否 | false | 请求落盘；需先 `cm config apply=on` |
| `--confirm` | flag | 否 | false | 写入用户确认（豁免确认，不计执行） |
| `--facts` | JSON | 否 | — | 记忆准入事实，见 §4.4.1 |

**响应（`--json`，`schema_version=1.1`）**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `schema_version` | string | 固定 `1.1` |
| `id` | string | `rt-YYYYMMDD-NNNN` |
| `idempotency_key` | string | `sha256:` + 归一化内容 / 主载体 / 目标路径的前 32 位 |
| `apply_mode` | enum | `plan` / `apply` |
| `primary` | enum | `skill` / `doc` / `memory` / `session`（唯一） |
| `attachments[]` | array | `{route, edge, materialize, target:{path}}`，0..max_attachments |
| `alternatives[]` | array | 互斥未决候选 `{route, confidence}` |
| `confidence` | float | 0–1，按四分量加权 |
| `confidence_parts` | object | `evidence / consistency / history / conflict`，必填 |
| `evidence[]` | array | `{kind, value}`，kind ∈ `execution_count/file/derivation/user_confirm/route_run` |
| `admission` | object | `{applicable, passed, pending, decision, checks, confidence_cap, ttl_days}` |
| `requires_user_confirm` | bool | D1 执行不足 / 准入 pending / 拒绝时 true |
| `target` | object | `{path, template}` |
| `next_action` | enum | `create_skill/create_doc/write_memory/keep_session/ask_user/write_pending` |
| `patch` | object\|null | `{summary, files:[{op,path,sha256,content}]}`；无写入时 null |
| `reasons[]` | string[] | 数据支撑的判定理由 |
| `signature` / `signature_normalized` / `signature_version` | string | 指纹复核用 |
| `apply` | object\|null | apply 结果 `{applied, replayed, run_id, files, backup}` |

**分档动作**：

| 条件 | `next_action` | patch |
|---|---|---|
| `confidence ≥ high` 且无需确认且准入通过 | `create_*` / `write_memory` | 有 |
| `low ≤ confidence < high` 或需确认 | `ask_user` | null |
| `confidence < low` | `ask_user` | null |
| 准入含 unknown | `write_pending` | null |
| 准入 A4=no | `ask_user` | null |

#### 4.4.1 准入事实格式

```json
{
  "a1": {"result": "not_derivable"},
  "a2": {"result": "ssot_path", "path": "docs/spec.md"},
  "a3": {"result": "evidence_ref", "ref": "docs/deploy.md"},
  "a4": {"result": "yes"}
}
```

- `a1.result`：`derivable_from`（必须带 `paths[]` 且路径存在）/ `not_derivable` / `unknown`
- `a2.result`：`ssot_path`（带 `path`）/ `none` / `unknown`
- `a3.result`：`evidence_ref`（带 `ref`）/ `none`（降级 observation，置信度上限 0.5）
- `a4.result`：`yes` / `no`（拒绝写入）/ `unknown`（TTL ≤ 30 天）

---

### 4.5 `cm mark-done`

**作用**：登记一次真实执行，是 D1 的唯一计数来源；用户确认不计入。

**参数**：`<content>`、`--source mark_done|record`、`--json`。

**响应**：`{signature, normalized, version, source, executions_90d}`。

---

### 4.6 `cm rollback`

**作用**：读取 `.cm/backup/<run_id>/manifest.json`，逆序恢复 create / modify / delete。

**参数**：`<run_id>`、`--json`。

**响应**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `rolled_back` | bool | 是否完成回滚 |
| `restored[]` | array | `{path, action}`，action ∈ `removed/restored` |
| `conflicts[]` | array | 后续手改导致中止时的 `{path, reason}` |

回滚前逐文件校验 `after_sha256`；任一不一致则整体中止，不做部分回滚。冲突返回退出码 5。

---

### 4.7 `cm config`

**作用**：查看或修改工作区配置。

**参数**：`key=value ...`（允许键：`apply` `high_threshold` `low_threshold` `session_ttl_days` `materialize` `max_attachments` `traces_summary`）、`--json`。

**示例**：

```bash
python3 scripts/cm_cli.py config apply=on
python3 scripts/cm_cli.py config high_threshold=0.82 low_threshold=0.5 --json
```

`high_threshold` 必须大于 `low_threshold`；`apply` 只接受 `on/off`。

---

### 4.8 `cm pack`

**作用**：按关键词从 `docs` / `skills` / `edges` 检索候选，按分数排序并用 token 预算裁剪，只返回指针，不读取正文、不写盘。

**参数**：

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `<query>` | string | 是 | — | 检索关键词 / 任务描述（多段自动空格拼接） |
| `--budget` | int | 否 | `2000` | token 预算，必须大于 0 |

**命中与排序**：标题命中 2.0 / 触发词命中 1.5 / 路径命中 1.0 / 一跳 `edges` 关联 0.5；同分按估算 token 与路径排序。估算公式：UTF-8 中文按 3 字节/字符、1.5 字符/token 粗估。

**响应（`--json`，`schema_version=1.0`）**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `query` / `keywords[]` | string / string[] | 原始查询与截断到 32 个的归一化关键词 |
| `budget` / `estimated_tokens` | int | 预算与入选条目估算总量（恒 ≤ 预算） |
| `items[]` | array | `{path, title, kind, doc_type, estimated_tokens, score, reason}`；技能另含 `version` |
| `item_count` / `skipped` / `truncated` | int / int / bool | 入选数、超预算跳过数、是否发生裁剪 |
| `read_only` | bool | 恒为 `true` |
| `notes[]` | string[] | 无命中 / 预算不足提示 |

预算不足时跳过放不下的候选，继续尝试更小的条目，绝不突破预算。

---

### 4.9 `cm triage`

**作用**：分拣过期会话与待定项；默认演练，只列不改。

**参数**：

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `--expire-sessions` | flag | 否 | false | 把 `expires_at < now` 且未分拣的会话写入 `triaged_at`（标记为已回收） |
| `--drop-pending` | flag | 否 | false | `review_count >= 3` 的待定项置 `dropped`，其余 `review_count += 1` |

**响应（`--json`，`schema_version=1.0`）**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `dry_run` | bool | 未给任何处理开关时为 `true` |
| `session_ttl_days` | int | 当前配置的会话 TTL |
| `sessions.expired` / `sessions.marked_expired` | int | 过期条数 / 本次实际回收条数 |
| `sessions.items[]` | array | `{id, content_ref, created_at, expires_at, overdue_hours}`，最多 20 条 |
| `pending.open` | int | `state='open'` 数量 |
| `pending.dropped` / `pending.incremented` | int | 本次丢弃 / 复核 +1 数量 |
| `pending.items[]` | array | `{id, kind, payload_ref, review_count, age_hours}`，最多 20 条 |
| `notes[]` | string[] | 演练提示与处理摘要 |

不启动后台守护进程；所有迁移都是前台一次性执行。

---

### 4.10 `eval_golden.py`

**作用**：只读评估黄金集，输出每类 P/R/F1、宏平均、准确率、高置信分组精确率、ECE 与 Cohen's κ；数据不足时明确报告「需人工标注」，不伪造指标。

**用法**：

```bash
python3 scripts/eval_golden.py --golden references/golden/dev.jsonl [--pred pred.jsonl] [--bins 10] [--json]
```

**输入（JSONL，每行一个对象）**：

```json
{"id": "g001", "label": "skill", "labeler": "A", "predicted": "skill", "confidence": 0.91}
```

- 同一 `id` 出现两次且 `labeler` 不同即为双人标注，用于 κ；
- `predicted` / `confidence` 可写在任意一行（同 id 后写覆盖先写）；
- `--pred` 可提供独立预测文件（JSONL 或 JSON 字典）。

**阈值**：`confidence ≥ 0.80` 为高置信分组；分组精确率 ≥ 0.90 或 ECE ≤ 0.15 视为达标。宏平均只统计真实出现过的类别（有标注或预测）。

**退出码**：0 达标 / 1 未达标 / 2 数据不足（需人工标注）/ 3 用法错误。

---

### 4.11 `cm index`

**作用**：汇总索引状态。默认先执行一次增量扫描，再输出文档 / 技能总数与断链、孤儿、漂移；`--check` 只读校验，不重建索引。

**参数**：

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `--check` | flag | 否 | false | 只读校验，不调用扫描、不写 `index.db` |

**响应（`--json`，`schema_version=1.0`）**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `command` | string | 恒为 `index` |
| `mode` | string | `incremental`（默认）/ `check` |
| `workspace` / `generated_at` | string | 工作区绝对路径与生成时间 |
| `counts.docs` / `counts.skills` | int | `status='active'` 的文档数与技能数 |
| `counts.broken_links` / `orphan_files` / `index_drift` | int | 复用 `doctor` 的三类索引指标 |
| `details.*` | array | 断链 / 孤儿 / 漂移样例，各最多 20 条 |
| `notes[]` | string[] | 扫描摘要与重建建议 |

写盘范围仅限 `.cm/index.db`（由扫描器负责）；`--check` 完全不写盘。

---

### 4.12 `cm skill lint`

**作用**：只读检查工作区内所有 `SKILL.md` 的 frontmatter 规范性。

**参数**：

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `--json` | flag | 否 | false | 输出机器可读 JSON |

**检查项**：

| `kind` | 严重级别 | 判定 |
|---|---|---|
| `missing_version` | warning | `version` 缺失或为空 |
| `duplicate_name` | error | 多个 `SKILL.md` 的 `name` 相同 |
| `trigger_overlap` | warning | 两个技能的触发词有交集 |
| `triggers_not_list` | warning | `triggers` 存在但不是列表（字符串需改为 `[a, b]`） |
| `missing_dependency` | error | `depends_on` 的条目按名称、相对路径、目录名均未找到 |

**响应（`--json`，`schema_version=1.0`）**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `command` | string | 恒为 `skill lint` |
| `issues[]` | array | `{severity, kind, skills[], detail}` |
| `summary.skills` | int | 扫描到的技能文件数 |
| `summary.error` / `summary.warning` / `summary.total` | int | 按严重级别的问题数 |

发现 issues 仍返回退出码 0（与 `doctor` 一致），由调用方按 `summary.error` 决定是否阻断；用法错误返回 2。

---

### 4.13 `cm selfcheck`

**作用**：只读校验当前安装的这份技能是否自洽：指标契约结构、`report` 口径、`health` 分档，以及（可选的）工作区初始化状态。

**参数**：

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `--json` | flag | 否 | false | 输出机器可读 JSON |

**响应（`--json`）**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `ok` | bool | 全部检查通过 |
| `version` | string | 包版本 |
| `contract_version` | string | 契约 `schema_version` |
| `checks[]` | array | `{check, ok, detail}`：指标契约 / report 口径 / health 分档 |
| `workspace.initialized` | bool | `.cm/config.yaml` 与 `index.db` 是否同时存在 |

全部通过退出 0；任一检查失败退出 2。

**独立脚本**：`python3 scripts/release_check.py [--json]` 检查三端契约副本 sha256、契约结构、`manifest/SKILL/__version__` 版本一致与 health 抽样，失败退出 1。

---

## 5. 错误码

| 退出码 | 场景 | stderr 示例 |
|---|---|---|
| 0 | 成功 | — |
| 2 | 用法错误 | argparse 自动输出 |
| 3 | 未初始化 | `错误：工作区尚未初始化：/path（请先执行 cm init）` |
| 4 | 数据库不可用 | `错误：索引数据库不可用：...` |
| 5 | 文件系统错误 | `错误：文件系统访问失败：...` |
| 130 | 用户中断 | `已中断` |

约定：`doctor` 发现异常仍返回 0；是否阻断由调用方按 `health` 判定。`eval_golden.py` 使用独立退出码：0 达标 / 1 未达标 / 2 数据不足 / 3 用法错误。

---

## 6. 版本管理

- CLI 版本与包版本一致（当前 `0.7.0`）
- `doctor` / `pack` / `triage` / `eval_golden` / `index` / `skill lint` JSON 的 `schema_version` 独立演进（当前 `1.0`）；`route` 为 `1.1`
- 指标契约 `references/metrics-contract.json` 的 `schema_version` 当前为 `1.0`；免费版 / Pro / 后端三份副本必须逐字节一致
- 新增字段视为兼容；删除 / 重命名字段必须提升 `schema_version`
- M3 已新增 `index` / `skill lint`；0.7.0 新增 `selfcheck` 与 `release_check.py`，命令表与本文档已同步

---

## 7. 幂等与并发

| 命令 | 幂等性 | 并发 |
|---|---|---|
| `init` | 已有配置不覆盖；`--force` 显式覆盖 | 同一工作区并发初始化未加锁，建议单进程 |
| `scan` | 同输入重复执行结果一致；未变化文件跳过 | SQLite WAL + 5s busy timeout |
| `doctor` | 只读，重复执行结果一致（时间戳除外） | 可与 `scan` 并行读取 |
| `route` | 同一 `idempotency_key` 只允许一次 apply | apply 前快照，manifest 记录前后哈希 |
| `pack` | 只读，重复执行结果一致（时间戳除外） | 只读连接，可与 `scan` 并行 |
| `triage` | 重复执行不重复丢弃；已回收会话不再计入 | WAL 单写，建议单进程 |
| `mark-done` | 非幂等，每次写入一条执行记录 | 追加写，WAL |
| `rollback` | 同一 run 只允许回滚一次（manifest 状态机） | 冲突时整体中止 |
| `config` | 同值重复写入结果一致 | 建议单进程修改 |
| `index` | 默认增量扫描幂等；`--check` 只读 | 与 `scan` 相同，WAL + 5s busy timeout |
| `skill lint` | 只读，重复执行结果一致 | 可与 `scan` 并行读取 |
| `selfcheck` | 只读，重复执行结果一致 | 无写操作 |

---

**文档版本**: v1.4
**最后更新**: 2026-11-20
