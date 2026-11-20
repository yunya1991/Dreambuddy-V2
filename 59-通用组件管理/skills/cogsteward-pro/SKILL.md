---
name: 认知管家 Pro
slug: cogsteward-pro
displayName: 认知管家 Pro
version: 1.1.1
summary: 本地零上传的工作区体检：Agent 用可见工具采集断链、孤儿文件、技能重名、行号越界、无文档代码、文档漂移等指标，脚本只做纯计算，输出 A–D 等级、四类占比与 P0/P1 整改动作。
description: 本地零上传的工作区体检：由 Agent 使用自身只读工具采集断链、孤儿文件、技能重名、行号越界、无文档代码、文档漂移等指标，脚本只做纯计算并给出 A–D 等级、占比与按优先级排序的整改动作。不联网、不上传任何数据。
license: 商业授权（订阅制）
---

# 认知管家 Pro

当工作区文档频繁断链、索引与实际文件对不上、技能重名抢占触发词时使用本技能。

**采集与计算分离**：指标由 Agent 用自身只读工具（Glob / Grep / Read；必要时用 Bash 只读查询 `.cm/index.db`）采集，`scripts/report.py` 只做纯计算。脚本不遍历目录、不读取文档、不访问数据库、不联网。

## 计费方式

订阅制，由平台按月计费；订阅期内本地可无限次运行，不产生按次费用。

## 第一步：采集指标（Agent 工具，只读）

| 指标 | 采集方式（与免费版 0.7.0 口径一致） |
|---|---|
| `inventory.documents` | Glob `**/*.md`（排除 `node_modules`、`.git`、`.cm`）计文件数 |
| `inventory.skills` | Glob `**/SKILL.md` 计目录数 |
| `metrics.broken_links` | 仅在 `.md`/`.markdown`/`.mdx` 中取链接（含图片链接）；跳过 `#` 锚点与 `http(s)`/`mailto:`/`tel:`/`ftp:`/`data:`/`javascript:`；`file://` 与工作区内绝对路径先换算成相对路径；去掉 `#片段`/`?查询` 并 URL 解码；解析到工作区外的不计；同一（文档, 目标）只计 1 次，目标不存在计 1 条 |
| `metrics.orphan_files` | 磁盘上存在、但未被索引登记（`docs` / `skills` 表中没有）的文件数；只读查询 `.cm/index.db` 统计；符号链接与 `node_modules`/`dist`/`.git` 等忽略目录不计；**工作区未初始化 `.cm` 或索引不可读时省略该字段，不要填 0**（报告会标记 `coverage.orphan="unavailable"` 且该项不参与评分） |
| `metrics.skill_conflicts` | 三类之和：重复 `name` 的分组数（每组计 1）、`version` 为空的技能数、`triggers` 有交集的技能对数；已标记为孤立（`status=orphan`）的技能不计 |
| `metrics.index_drift` | 已登记文件哈希不一致、文件缺失或不可读的条数 |
| `metrics.stale_sessions` | 创建后超过会话 TTL 一半仍未分拣的会话数（Dev 7 天 → 3.5 天；Office 14 天 → 7 天） |
| `metrics.pending_backlog` | `state=open` 的待定项数量 |
| `metrics.anchor_out_of_range` | 仅统计 `](路径#L起-L止)` / `](路径#L行)`；目标文件不存在不计（归断链）；`起 < 1`、`止 < 起`、`止 > 目标文件行数` 计为越界；同一（文档, 目标, 起, 止）只计 1 次 |
| `metrics.code_without_doc` | 仅统计扩展名 `.py`/`.js`/`.ts`/`.tsx`/`.jsx`/`.sh` 的源码；仅限含 `INDEX.md` 或 `SKILL.md` 的目录；未被任何已索引文档链接引用者计 1；符号链接与 `node_modules`/`dist`/`.git` 不计 |
| `metrics.doc_drift` | 被引用文件 mtime 比引用文档 mtime 晚 ≥3 天才计；`CHANGELOG.md`/`INDEX.md`/`ENGINEERING_INDEX.md` 作为来源文档不计；同一（文档, 目标）只计 1 次；目标不存在不计 |

`index_drift` / `stale_sessions` / `pending_backlog` 仅在用户要求时采集；**未采集就直接省略该字段**，不要填 `0`（填 0 会被当成健康项，抬高评分）。报告会把缺失项标记为 `coverage.<指标>=unavailable` 且不参与评分。

汇总成一份 JSON（**只含计数，不含路径、文件名与正文**）：

```json
{
  "metrics": {"broken_links": 3, "orphan_files": 29, "index_drift": 0, "skill_conflicts": 0, "stale_sessions": 0, "pending_backlog": 0, "anchor_out_of_range": 0, "code_without_doc": 0, "doc_drift": 0},
  "inventory": {"documents": 47, "skills": 9},
  "mode": "dev"
}
```

## 第二步：生成报告（纯计算）

```bash
python3 scripts/report.py --metrics '<上一步的 JSON>'
python3 scripts/report.py --metrics @metrics.json --format json --top 10   # 机器可读 / 展开全部整改项
```

脚本只接收命令行里的 JSON，不读工作区文件。

脚本会按 `references/metrics-contract.json` 校验输入：

- 未知指标 → `WARN 未知指标：xxx（已忽略）`，不会静默吞掉；
- 负数、非整数、布尔值 → `ERR` 并以退出码 1 结束；
- 未采集指标 → 输出「覆盖：… 未采集（unavailable），不参与评分」；
- `--top N` 控制整改项展示条数（默认 3），`--format json` 输出完整结构化报告。

排错见 [references/faq.md](./references/faq.md)。

## 输出约定

```json
{
  "schema_version": "1.0",
  "grade": "C",
  "score": 60,
  "health": "attention",
  "coverage": {"orphan": "complete"},
  "ratios": {"orphan_rate": {"value": 61.7, "status": "high"}},
  "findings": [
    {"id": "orphan_files", "priority": "P0", "value": 29, "action": "把未登记文件纳入索引（执行 cm scan）或移出工作区"}
  ]
}
```

等级口径：`A` ≥ 90 分，`B` ≥ 75，`C` ≥ 60，`D` < 60。`health`：0 项异常 `good`、1–2 项 `attention`、≥3 项 `poor`。比率在分母为 0 时留空。指标阈值与权重来自 `references/metrics-contract.json`（与免费版、后端逐字节一致）。

## 安全边界

- `scripts/report.py` 只接受命令行显式传入的 JSON，不读写工作区、不遍历目录、不联网、不执行子进程。
- 不收集文档正文、文件名、绝对路径、用户名、Token 或私钥。
- 报告在用户本机生成，不落盘到工作区之外的位置。
