# 五层字段定义

> `rule_version: v1`。字段一旦发布不得静默改名；新增字段只能追加。

## 1. event

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `time` | string | ✅ | ISO8601；filings 为披露日 `YYYY-MM-DD`，RSS 为带时区时间 |
| `source` | string | ✅ | 展示名，如 `SEC EDGAR`、`美联储新闻发布` |
| `type` | string | ✅ | 表单类型（`8-K`/`10-Q`/`4`）或 `press-release` |
| `subject` | object | ✅ | `{ticker?, cik?, name?}`，至少一项 |
| `headline_facts` | string[] | ✅ | 结构化事实点，每项 ≤80 字 |
| `url` | string | ✅ | 原文链接，必须可访问 |

## 2. entities

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `tickers` | string[] | 可空 | 无 ticker 时为空数组并计入 `fields_empty` |
| `sector` | object/null | 可空 | `{code, label}`，取自 SEC SIC |
| `supply_chain` | string[] | 可空 | **无可靠来源时恒为空**，不臆造 |
| `entity_source` | string | ✅ | 实体来源说明 |

## 3. analogues

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `key` | object | ✅ | `{source, type, item}`，item 为 8-K 事项编号，可能为 null |
| `n` | int | ✅ | 同类事件次数（观察窗内），**不是概率** |
| `window` | string | ✅ | 计数观察窗，固定 `24m` |
| `stat` | object/null | ✅ | 收益统计；**无行情授权时恒为 null** |
| `stat_window` | string | ✅ | 统计窗口标签（本期 `T+5`，未启用） |
| `note` | string | ✅ | 固定说明，解释 n 的含义与 stat 为空的原因 |

## 4. sources

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `title` | string | ✅ | 条目标题，≤120 字 |
| `url` | string | ✅ | 原文链接 |
| `license` | string | ✅ | 必须与 `references/sources.md` 登记一致 |
| `retrieved_at` | string | ✅ | 本次取数时间 |

## 5. assembly

| 字段 | 类型 | 说明 |
|---|---|---|
| `rule_version` | string | 装配规则版本 |
| `fields_filled` | int | 已填充层数（1–5） |
| `fields_empty` | string[] | 明确为空的字段路径 |
| `generated_at` | string | 生成时间 |

## 6. 枚举与取值

| 枚举 | 取值 |
|---|---|
| 表单类型 | SEC 原样返回（`8-K` `10-K` `10-Q` `4` `144` 等），不做映射 |
| 事件源 | `sec-submissions` `sec-press` `fed-all` |
| 失败原因码 | `E_NET` `E_TLS` `E_HTTP_4xx` `E_SCHEMA` `E_EMPTY` `E_INPUT` `E_LICENSE` |
| 红线命中 | 返回 `E_SCHEMA`，整份拒绝输出 |

## 7. event_id 生成

```text
event_id = sha1("{source_key}:{type}:{accession 或 guid}")[:16]
```

性质：同一事件在任何时候、任何机器上生成的 id 相同；id 本身不携带来源信息，反查时需提供 `--subject` 或 `--feed` 范围。
