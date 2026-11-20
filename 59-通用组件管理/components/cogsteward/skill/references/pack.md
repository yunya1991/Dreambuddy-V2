# 上下文打包（只读）

> 目标：在不读正文的前提下，用索引元数据给出「这次任务该看哪些文件」的指针清单。
> 实现：`scripts/core/pack.py`；CLI `cm pack "<任务>" [--budget 2000]`。

## 1. 输入

- 查询经 `signature.clean` + `signature.tokenize` 归一化，中文按 bigram、英文按词，去重后最多 32 个关键词；
- 只查 `docs`（`status='active'`）、`skills`（`status != 'orphan'`）与 `edges`（`kind='references'`）；
- 不读取文件正文，技能大小取 `stat().st_size`。

## 2. 打分

| 命中位置 | 权重 | 说明 |
|---|---|---|
| 文档标题 / 技能 name | 2.0 | 每个关键词计一次 |
| 技能 triggers | 1.5 | frontmatter 声明的触发词 |
| 路径 | 1.0 | 仅在标题未命中时计分 |
| edges 一跳 | +0.5 | 引用命中文件 / 被命中文件引用 |

同一关键词只取最高档位，不重复计分；`edges` 加分只加一次，避免环状互相抬高。

## 3. 预算与裁剪

```
estimated_tokens = max(1, round((size_bytes // 3) / 1.5))
```

- 按 UTF-8 中文 3 字节/字符、1.5 字符/token 粗估，仅用于预算，不代表真实分词；
- 排序：`(-score, estimated_tokens, path)`；
- 贪心入选：`used + cost <= budget` 才入选，否则 `skipped += 1` 并继续尝试更小的候选；
- 恒有 `estimated_tokens <= budget`，绝不通过截断正文来凑预算（因为不读正文）。

## 4. 输出契约

```json
{
  "command": "pack",
  "query": "发布检查",
  "keywords": ["发布", "检查"],
  "budget": 2000,
  "estimated_tokens": 420,
  "item_count": 2,
  "items": [
    {"path": "docs/deploy.md", "title": "发布流程", "kind": "doc",
     "doc_type": "doc", "estimated_tokens": 260, "score": 4.0,
     "reason": "标题命中：发布"}
  ],
  "skipped": 0,
  "truncated": false,
  "read_only": true,
  "notes": []
}
```

## 5. 边界

- 不做全文检索、不做向量召回、不返回正文片段；
- 不写 `.cm/` 以外的任何文件，也不修改 `index.db`；
- 无候选时返回空 `items` 并给出 `notes`，不伪造结果。
