# 常见问题与排错

## 1. 报「未知指标：xxx（已忽略）」

指标名拼错或不属于九项契约。可用指标：`broken_links`、`orphan_files`、`index_drift`、`skill_conflicts`、`stale_sessions`、`pending_backlog`、`anchor_out_of_range`、`code_without_doc`、`doc_drift`。

## 2. 报「必须是非负整数」

指标只接受计数：`0` 或正整数，上限 1000000。`3.5`、`"3"`、`-1`、`true` 都会被拒绝。

## 3. 没有 `.cm/index.db` 怎么办

`orphan_files` 无法采集时**省略该字段**，报告会标记 `coverage.orphan=unavailable` 且该项不参与评分。不要填 0，否则会把「没测」当成「没问题」。

## 4. 缺测指标为什么显示 unavailable

`index_drift` / `stale_sessions` / `pending_backlog` 等按需采集的指标缺省时不会按 0 计分，避免评分虚高。需要完整评分时补齐后再跑一次。

## 5. 只看前 3 条整改项不够

用 `--top 10` 展开，或 `--format json` 读取完整 `findings` 与 `total_findings`。

## 6. 重复运行会不会重复收费

不会。订阅制期内本地无限次运行；`scripts/report.py` 不联网、不产生订单。

## 7. 报告会上传我的文档吗

不会。脚本只接收命令行 JSON 中的计数，不读取文档正文、文件名、路径或数据库，也不联网。

## 8. 与按次付费版的区别

订阅版在本地纯计算；按次版把同一份计数 JSON 发往体检服务做基准对比。两者指标口径一致，按次版才涉及支付与 `--proof`。
