---
name: site-blog
slug: site-blog
display_name: 研究博客发布
description: "把带 front matter 的 Markdown 研究稿发布到 59 研究博客：写入 posts、复制图表、构建校验、rsync 部署并做 HTTP 200 校验。"
summary: 研究稿一键上线 59 站点：写 md + 拷图 + build + check + 部署 + 校验，写动作必须显式 --allow-write。
tags: [研究博客, 站点发布, build_site, rsync, 内容运营]
version: 1.0.0
license: MIT
allowed-tools: Read, Write, Bash
---

# 研究博客发布（site-blog）

把 OKA 内容 run 产出的 `blog.md` 上线到 59 研究博客。

## 前置条件

- Markdown 必须带完整 front matter：`title` / `date`（YYYY-MM-DD）/ `summary`；
- 配图先落到 `platform/site/assets/charts/<run_id>/`，正文引用需以 `../assets/charts/<run_id>/` 开头；
- 写动作必须显式 `--allow-write`；
- 部署目录取 `--remote-dir` 或环境变量 `DREAMBUDDY_SITE_REMOTE_DIR`，两者都为空时拒绝部署。

## 用法

```bash
python3 skill/scripts/publish.py publish \
  --file /path/to/blog.md \
  --slug gold-liquidity-2026-11 \
  --run-id 20261122T101500 \
  --image /path/to/chart1.png \
  --allow-write
```

只构建不部署：加 `--no-deploy`。

## 输出

`output_contract: cogsteward.v1`：`schema_version` / `command` / `generated_at` 之外，附
`status`（done/failed）、`slug`、`url`、`build_ok`、`deployed`、`http_status`、`images`、`post`。

## 边界

- 不生成文章、不生成图表；不做小红书/抖音等社媒发布（走 mobile-reservation-assist）；
- 构建或校验失败时直接失败返回，不做半部署。
