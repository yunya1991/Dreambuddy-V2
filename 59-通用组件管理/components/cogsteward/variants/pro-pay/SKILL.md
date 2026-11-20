---
name: cogsteward-pro
slug: cogsteward-pro
displayName: 认知管家 Pro（按次付费）
version: 1.1.1
summary: 按次付费的工作区体检：Agent 用可见工具采集断链、孤儿、技能冲突与代码-文档对应等九项指标，云端做基准对比，返回 A–D 等级、占比与 P0/P1 整改动作。
description: 按次付费的工作区体检：由 Agent 使用自身只读工具采集断链、孤儿文件、技能冲突、行号越界、无文档代码、文档漂移等九项指标，不上传文档正文；云端返回 A–D 等级、占比与按优先级排序的整改动作。
license: 商业授权（按次计费）
---

# 认知管家 Pro（按次付费）

当工作区文档频繁断链、索引与实际文件对不上、技能重名抢占触发词时使用本技能。

**采集与上传是两步，且彼此隔离**：指标由 Agent 用自身的只读工具（Glob / Grep / Read；必要时用 Bash 只读查询 `.cm/index.db`）采集，`scripts/pay.py` 只负责把 Agent 显式给出的计数 JSON 发送到体检查看服务。脚本不遍历目录、不读取文档、不访问本地数据库。

## 计费方式

- **按次收费**，每次调用 ¥0.99。
- 协议：HTTP 402（`Payment-Needed`）→ 支付宝支付 → 携带 `Payment-Proof` 重试。
- 计费单元：一次体检请求（一份指标快照）。

## 第一步：采集指标（Agent 工具，只读）

按顺序用工具统计，不需要运行任何脚本：

| 指标 | 采集方式（与免费版 0.7.0 口径一致） |
|---|---|
| `inventory.documents` | Glob `**/*.md`（排除 `node_modules`、`.git`、`.cm`）计文件数 |
| `inventory.skills` | Glob `**/SKILL.md` 计目录数 |
| `metrics.broken_links` | 仅在 `.md`/`.markdown`/`.mdx` 中取链接（含图片链接）；跳过 `#` 锚点与 `http(s)`/`mailto:`/`tel:`/`ftp:`/`data:`/`javascript:`；`file://` 与工作区内绝对路径先换算成相对路径；去掉 `#片段`/`?查询` 并 URL 解码；解析到工作区外的不计；同一（文档, 目标）只计 1 次 |
| `metrics.orphan_files` | 磁盘上存在、但未被索引登记（`docs` / `skills` 表中没有）的文件数；只读查询 `.cm/index.db` 统计；**未初始化 `.cm` 或索引不可读时省略该字段，不要填 0**（服务端标记 `coverage.orphan="unavailable"`，该项不参与评分） |
| `metrics.skill_conflicts` | 重名分组数 + 缺版本技能数 + 触发词重叠技能对数；`status=orphan` 不计 |
| `metrics.index_drift` | 已登记文件哈希不一致、缺失或不可读的条数 |
| `metrics.stale_sessions` | 超过会话 TTL 一半仍未分拣的会话数（Dev 7 天 → 3.5 天；Office 14 天 → 7 天） |
| `metrics.pending_backlog` | `state=open` 的待定项数量 |
| `metrics.anchor_out_of_range` | 仅统计 `](路径#L起-L止)` / `](路径#L行)`；目标文件不存在不计（归断链）；`起 < 1`、`止 < 起`、`止 > 目标文件行数` 计为越界；同一（文档, 目标, 起, 止）只计 1 次 |
| `metrics.code_without_doc` | 仅统计 `.py`/`.js`/`.ts`/`.tsx`/`.jsx`/`.sh`；仅限含 `INDEX.md` 或 `SKILL.md` 的目录；未被任何已索引文档链接引用者计 1；符号链接与忽略目录不计 |
| `metrics.doc_drift` | 被引用文件 mtime 比引用文档晚 ≥3 天才计；`CHANGELOG.md`/`INDEX.md`/`ENGINEERING_INDEX.md` 作为来源不计；同一（文档, 目标）只计 1 次 |

`index_drift` / `stale_sessions` / `pending_backlog` 仅在用户明确要求时采集；**未采集就直接省略该字段**，不要填 `0`（填 0 会被当成健康项，服务端按 0 计分）。

汇总成一份 JSON（**只含计数，不含路径、文件名与正文**）：

```json
{
  "metrics": {"broken_links": 3, "orphan_files": 29, "index_drift": 0, "skill_conflicts": 0, "stale_sessions": 0, "pending_backlog": 0, "anchor_out_of_range": 0, "code_without_doc": 0, "doc_drift": 0},
  "inventory": {"documents": 47, "skills": 9},
  "mode": "dev"
}
```

把这份 JSON 原样展示给用户，确认后再执行第二步。

## 第二步：提交体检（按次付费）

```bash
# 第一次调用返回 402 与待支付订单
python3 scripts/pay.py --metrics '<上一步的 JSON>'

# 支付完成后，用支付凭证重试同一请求
python3 scripts/pay.py --metrics '<上一步的 JSON>' --proof <Payment-Proof>
```

服务地址：`https://www.neodrm.com/api/paid/cogsteward`（可用环境变量 `COGSTEWARD_ENDPOINT` 覆盖）。

| 参数 | 说明 |
|---|---|
| `--proof` | 支付完成后回传的凭证；同一凭证重复提交不重复计费 |
| `--timeout` | 单次请求超时秒数，默认 45 |
| `--retries` | 带凭证时的重试次数，默认 2；无凭证调用不自动重试 |
| `--describe` | 只打印请求体，不联网、不产生订单 |

网络错误会映射为 `E_NET` / `E_TIMEOUT` / `E_SSL` / `E_JSON`，不会抛 Python 栈；凭证来源：支付结果、平台订单页、支付回调或支付结果邮件。

## 输出约定

```json
{
  "schema_version": "1.0",
  "grade": "C",
  "score": 60,
  "health": "attention",
  "coverage": {"orphan": "complete"},
  "metrics": {"broken_links": 3, "orphan_files": 29},
  "ratios": {"broken_link_rate": {"value": 6.38, "status": "high"}},
  "findings": [
    {"id": "orphan_files", "priority": "P0", "value": 29, "action": "cm scan 重新登记未入索引文件；长期无引用的移出工作区"}
  ]
}
```

等级口径：`A` ≥ 90 分，`B` ≥ 75，`C` ≥ 60，`D` < 60。`health`：0 项异常 `good`、1–2 项 `attention`、≥3 项 `poor`。比率在分母为 0 时留空。服务端指标口径来自 `src/metrics-contract.json`（与免费版、Pro 版逐字节一致）。

## 服务端付费协议（实现说明）

1. **402 挑战**：无 `Payment-Proof` 时返回 `HTTP 402`，响应头 `Payment-Needed` 携带签名账单（`out_trade_no`、`amount`、`pay_before`、`resource_id`、`seller_signature`），同时落库为待支付订单。
2. **验付调用**：收到 `Payment-Proof` 后调用支付宝验付接口校验凭证，得到 `trade_no`、实付金额与 `resource_id`；任一项与本地订单不一致即重新返回 402。
3. **交付**：验付通过后生成报告并写入订单（`service_result`），同一凭证重复提交直接返回首次结果，不重复计费（幂等）。
4. **履约确认**：交付成功后调用履约确认接口，并把订单标记为 `FULFILLED`；确认失败返回 502，允许用同一凭证重试。

## 安全边界

- `scripts/pay.py` 只接受命令行显式传入的 JSON，不读写工作区文件、不遍历目录、不执行子进程。
- 上传内容只有计数与模式字段；不含文档正文、文件名、绝对路径、用户名、Token 或私钥。
- 除体检查看服务外不发起任何网络请求。
