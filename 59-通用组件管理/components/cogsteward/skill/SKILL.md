---
name: cognition-manager
slug: cogsteward
displayName: 认知管家
display_name: 认知管家
display_name_en: CogSteward
description: "上下文治理：判定信息的主载体与从属归属，分流到技能/文档/记忆/会话，并编译最小上下文包。用于工作区混乱、文档断链、技能重复、AI 反复摸索时。"
description_zh: 把资料、技能、要点和本次任务分开管，生成可读的工作区体检报告。
description_en: Context governance for skills, docs and memory, with a readable workspace health report.
summary: 把资料、技能、要点、本次任务分开管：扫描登记、工作区体检、路由归属、最小上下文打包，纯本地运行零依赖。
version: 0.7.0
license: MIT
author: CogSteward
allowed-tools: Read, Write, Glob, Grep, Bash
---

# 认知管家（CogSteward）

> 别人做「记得更多」，我们做「该不该记、该放哪、该调谁」。

## 何时使用

- 用户问「这个放哪」「要不要记下来」「文档太乱」「索引失效」
- 工作区第一次接入，需要一份能读懂的体检报告
- 需要判断同一内容属于技能 / 文档 / 记忆 / 会话
- 需要任务开始前的最小上下文包（M2）

## 反触发（不要调用）

- 单纯写代码、单纯查资料
- 单文件小修、一次性脚本
- 用户明确要求使用其他检索 / 记忆工具

## 首次使用

一次 Bash 调用完成初始化、扫描与体检，减少沙箱确认次数：

```bash
# 在目标工作区目录下执行
python3 scripts/cm_cli.py init --scan --doctor

# 或从别处指定工作区：--root 必须写在子命令之前
python3 scripts/cm_cli.py --root /path/to/workspace init --scan --doctor
```

30 秒内应输出一份「有指标、有结论、有下一步建议」的报告。

## 命令表（M3）

| 命令 | 作用 | 输出 |
|---|---|---|
| `cm init [--mode dev\|office]` | 创建工作区状态目录 `.cm/` | 模式、状态目录、FTS5 可用性 |
| `cm scan [--full]` | 全量 / 增量扫描并登记文件 | 文本 / 二进制 / 技能数量、耗时 |
| `cm doctor [--json]` | 工作区体检 | 九类指标 + Top-3 建议 |
| `cm index [--check]` | 索引总览（默认增量扫描；`--check` 只读） | 文档 / 技能总数、断链、孤儿、漂移 |
| `cm route "<描述>" [--apply] [--confirm] [--facts JSON]` | 判定主载体与从属归属，生成 patch | 路由 JSON / 摘要；默认 plan 不落盘 |
| `cm pack "<任务>" [--budget 2000]` | 按预算打包上下文指针（只读；**只按标题与关键词匹配，不读正文**） | 路径 / 标题 / 估算 token / 命中理由 |
| `cm triage [--expire-sessions] [--drop-pending]` | 分拣过期会话与待定项（默认演练） | 过期会话、待定积压、处理摘要 |
| `cm skill lint` | 检查技能版本 / 重名 / 触发词 / 依赖 | 问题列表与严重级别 |
| `cm selfcheck` | 安装自检：契约结构、report 口径、版本一致性 | 逐项 PASS/FAIL 与结论 |
| `cm mark-done "<描述>"` | 登记一次真实执行（D1 计数） | 指纹与近 90 天执行次数 |
| `cm rollback <run_id>` | 按备份逆序回滚一次 apply | 还原 / 删除清单 |
| `cm config apply=on\|off` | 查看或修改工作区配置 | 当前配置 |

黄金集评估为独立只读脚本：`python3 scripts/eval_golden.py --golden <标注.jsonl> [--pred <预测>]`，退出码 0 达标 / 1 未达标 / 2 需人工标注。

通用参数：`--root <目录>` 指定工作区（默认当前目录），**必须写在子命令之前**（`cm --root <目录> doctor`）；写在子命令之后会被当成未知参数直接报错。`--json` 输出机器可读结果。

`route` 的记忆准入事实通过 `--facts` 传入，例如：

```bash
cm route "踩坑经验：部署失败原因" --facts '{"a1":{"result":"not_derivable"},"a2":{"result":"none"},"a3":{"result":"evidence_ref","ref":"docs/deploy.md"},"a4":{"result":"yes"}}'
```

未提供 `--facts` 时记忆一律进入 `pending`，不写入检索。

## 路由模型（M2 已落地）

- **主载体唯一**：`skill / doc / memory / session`
- **从属引用 0..3 条**：只记录关系与指针，不复制正文
- **默认写入模式 `plan`**：只输出建议与 patch 摘要，不落盘
- 判定树、关系枚举见 `references/routing-matrix.md`；置信度公式见 `references/confidence.md`；意图指纹见 `references/intent-signature.md`
- 记忆准入四问见 `references/admission-rules.md`

## 数据与隐私

状态全部在用户工作区 `.cm/`：

```
.cm/
├── config.yaml   # 模式 / 阈值 / 忽略规则 / signature_salt
├── index.db      # SQLite（WAL）
├── traces/       # 路由与体检记录（路径 / 哈希 / 理由）
├── memory/       # 记忆指针（只存引用，不存正文）
├── backup/       # apply 前快照与 manifest.json
└── cache/
```

- 只登记路径、大小、哈希、标题与类型，**不保存文档正文**
- 不发起网络请求；纯本地运行
- 表结构与状态机见 `references/schema.md`

## 体检输出契约

`cm doctor --json` 固定字段：

```json
{
  "schema_version": "1.0",
  "command": "doctor",
  "workspace": "/abs/path",
  "mode": "dev",
  "generated_at": "2026-11-19T17:00:00+08:00",
  "metrics": {
    "broken_links": 0,
    "orphan_files": 0,
    "index_drift": 0,
    "skill_conflicts": 0,
    "stale_sessions": 0,
    "pending_backlog": 0,
    "oldest_pending_hours": 0.0,
    "anchor_out_of_range": 0,
    "code_without_doc": 0,
    "doc_drift": 0
  },
  "details": {},
  "recommendations": ["..."],
  "health": "good"
}
```

`health` 取值：`good`（0 项异常）/ `attention`（1–2 项）/ `poor`（≥3 项）。

指标口径（名称 / 阈值 / 权重 / 分母）的唯一事实源是 `references/metrics-contract.json`；免费版、Pro 版与后端各带一份字节一致的副本，由 `cm selfcheck` 与 `scripts/release_check.py` 校验。改口径只改契约，不改三端代码。

## 代码-文档对应检查（v0.6 已落地）

基于索引库 `edges` 表中 `kind='references'` 的边（文档 → 被引用文件），扩展四类检查：

| 检查 | 判定口径 | 指标字段 | 典型症状 |
|---|---|---|---|
| 文档 → 代码有效 | 链接目标文件存在于工作区 | `broken_links`（已有） | 文档指向已删除/改名的代码 |
| 锚点/行号越界 | `#L<起>-L<止>` 的起止行需在目标文件实际行数内，且起 ≤ 止 | `anchor_out_of_range` | 代码删行后文档仍引用 `#L120-L140` |
| 代码 → 文档缺口 | 核心模块（含 `INDEX.md` 或 `SKILL.md` 的目录）中，源码文件未被任何已索引文档引用 | `code_without_doc` | 新增模块没有任何文档说明 |
| 文档漂移 | 被引用文件的内容哈希在文档最后一次更新之后发生变化 | `doc_drift` | 接口改了，README 未同步 |

实现口径：

- 只读查询 `edges` + `docs`/`files` 的 `content_hash`，不新增写路径；
- 「代码」按扩展名白名单（`.py` `.js` `.ts` `.sh` `.jsx` `.tsx`）判定，二进制与生成物不参与；
- 「缺口」只在核心模块内统计，`node_modules`、`dist`、`.git` 等沿用 `ignore` 配置；
- 四类检查全部进入 `cm doctor` 的 `metrics`；`cm map --gaps` 输出明细（文件对 + 行号 + 最近修改时间）。

命令形态：

```bash
cm map              # 文档 ↔ 代码映射摘要
cm map --gaps       # 只列三类缺口：行号越界 / 无文档代码 / 待复审漂移
cm map --json       # 供 Agent 消费
```

## 能力边界

- 做：扫描登记、断链 / 孤儿 / 漂移检测、技能冲突检测、体检报告
- 做：代码-文档对应检查（行号越界、无文档代码、文档漂移），见上节
- 不做：通用 RAG 服务、向量库托管、上传用户内容、交易域能力、代写业务代码
- 文本类按扩展名白名单索引；二进制仅登记元数据；正文抽取为 Pro，默认关闭

## 双版本

| 维度 | Dev | Office |
|---|---|---|
| 阈值 high / low | 0.80 / 0.50 | 0.80 / 0.55 |
| 会话 TTL | 7 天 | 14 天 |
| 从属物化 | `stub` | `none` |
| 词表 | 文档 / 技能 / 记忆 / 会话 | 资料 / 套路 / 要点 / 本次 |

差异只写在 `scripts/modes/*.yaml`，内核不改。已有工作区不会被 `cm init --mode` 覆盖；确需切换模式时用 `cm init --mode office --force`（重写 `config.yaml`，索引保留）。

## 参考

- `references/schema.md`：数据表、状态机、隐私约束
- `references/routing-matrix.md`：判定树、关系枚举、主载体与从属引用
- `references/confidence.md`：confidence 公式、阈值联调与校准（M2 实现）
- `references/intent-signature.md`：意图指纹归一化与 50 条动词映射（M2 实现）
- `references/admission-rules.md`：记忆准入四问与反例
- `references/metrics-contract.json`：九项指标 / 占比的唯一口径源（三端副本一致）
- `references/pack.md`：打包评分、token 估算与预算裁剪（M2b 实现）
- `references/triage.md`：会话 / 待定项状态迁移（M2b 实现）
- `references/golden/`：黄金集格式、双人标注与 `eval_golden.py` 用法
- `templates/`：SPEC / ADR / INDEX / SKILL / 会议纪要模板

## M2 / M3 范围与限制

- 已实现：`init` / `scan` / `doctor` / `route` / `pack` / `triage` / `mark-done` / `rollback` / `config` / `index` / `skill lint`，SQLite + FTS5，零第三方依赖
- `route` 默认 `plan` 只输出建议与 patch 摘要；`apply` 必须 `cm config apply=on` 且单次调用加 `--apply`
- **`apply` 还有置信度门槛**：置信度低于 `high_threshold`（默认 0.8）时，即使两个条件都满足也**只会输出 plan、不落盘**，且不报错；`--confirm` 只登记"用户已确认"，不解除该门槛。要落盘需提高置信度（补 `--facts` / 增加关键词）或调低 `high_threshold`（`cm config high_threshold=0.6`）
- **`orphan_files` 语义**：指"磁盘上有、索引里没有"的文件（执行 `cm scan` 即归零），**不是"没有任何文档引用它"**
- `pack` 只按标题与关键词匹配，不读正文；正文里的词不会带来命中
- D1 只统计近 90 天 `executions`（`record` / `mark_done`）；用户确认写入 `intent_confirms`，豁免确认但不计执行
- `apply` 前快照到 `.cm/backup/<run_id>/`，单次最多 10 个文件；回滚遇到后续手改会整体中止
- `pack` 只读，token 按字节近似估算，预算内贪心入选，不读正文
- `triage` 默认演练；`--expire-sessions` / `--drop-pending` 才迁移状态，不启动后台进程
- `index` 默认增量扫描后汇报；`--check` 只读校验，不重建索引
- `skill lint` 只读检查 `SKILL.md`；发现 issues 仍退出 0，由调用方按 `summary.error` 决定是否阻断
- `selfcheck` 只读校验契约与口径，不写任何文件；契约不一致时退出 2
- 指标阈值 / 权重 / 标签统一由 `references/metrics-contract.json` 提供，`doctor` 不再硬编码九项明细
- V9 十二例异常路径已覆盖 10 项实测 + 2 项 N/A（磁盘满、中断恢复）
- 首次运行如需写入 `.cm/` 被沙箱拦截，报告可降级为纯 `plan` 输出

## 更新日志

### 0.7.0（2026-11-20）

**指标契约单一源**：新增 `references/metrics-contract.json`，九项指标与四项占比的标签 / 阈值 / 权重 / 分母统一由契约提供，免费版、Pro 版、后端各带一份字节一致的副本。

1. 新增 `core/contract.py`（加载 + 结构校验 + `health_of`）与 `core/selfcheck.py`
2. 新增 `cm selfcheck` 子命令与 `scripts/release_check.py` 发布闸门
3. `core/report.py` 的 `PROBLEM_KEYS` / `health_of` / 体检表标签改为读契约
4. 修正 `SKILL.md` 中「v0.6 规划」字样：代码-文档对应检查已在 0.6 落地

### 0.5.1（2026-11-19）

**只改文档，不改内核**，修 4 处"文档与真实行为不一致"：

1. `--root` 补写"必须位于子命令之前"，并给出两种调用示例（此前照抄示例会直接报未知参数）
2. `pack` 明确"只按标题与关键词匹配、不读正文"（此前正文命中预期会落空）
3. `apply` 补写置信度门槛：低于 `high_threshold` 时静默降级为 plan，`--confirm` 不解除门槛
4. `orphan_files` 明确为"磁盘有、索引无"，不是"未被引用"

### 0.5.0

首个可发布版本：`init` / `scan` / `doctor` / `route` / `pack` / `triage` / `mark-done` / `rollback` / `config` / `index` / `skill lint`。
