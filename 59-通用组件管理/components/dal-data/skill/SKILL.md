---
name: dal-data
slug: dal-data
display_name: 19-DAL 数据访问（内部）
description: "19 数据访问层内部组件：本地只读查询（mm_metrics 时序、scope 上下文、能力清单）+ 云端只读快照同步；不注册任何 DAL 写能力。"
summary: 内部数据组件：读 19-DAL 只读镜像，按需从云端刷新快照；写入口唯一在云端。
tags: [19-DAL, 数据访问层, 只读镜像, 云端快照, 内部组件]
version: 0.1.0
license: MIT
allowed-tools: Read, Bash
---

# 19-DAL 数据访问（dal-data，内部）

59 域内部组件，把 19 数据访问层的**只读能力**接入统一 CLI，并复用既有链路从云端刷新只读快照。

## 能力

| 动作 | 安全级 | 作用 |
|---|---|---|
| `tools` | read | 列出 19-DAL 只读工具与输入 schema |
| `scopes` | read | 列出可用数据 scope |
| `read` | read | 按 `sub_category` + `metric_name` 查 `mm_metrics` |
| `fetch` | read | 按 scope 取数据上下文 |
| `status` | read | 本地只读镜像新鲜度与库清单 |
| `sync` | write | 从云端拉取只读快照（需 `--allow-write`） |

## 用法

```bash
python3 skill/scripts/dal.py read \
  --sub-category macro --metric-name DGS10 --limit 10
python3 skill/scripts/dal.py fetch --scope market --params '{"symbol":"BTC"}'
python3 skill/scripts/dal.py status
python3 skill/scripts/dal.py sync --allow-write --timeout 600
```

或经统一 CLI：

```bash
dreambuddy run dal-data read --sub-category macro --metric-name DGS10
```

## 输出

`output_contract: cogsteward.v1`：`schema_version` / `command` / `generated_at` / `ok` / `data`。

## 边界（硬约束）

- 云端 19 DAL 无对外 HTTP 接口，对接方式为**只读快照**（`cloud sync` 复用既有 dbsync，幂等）；
- 不注册 `data_store_write`：DAL 写入口唯一在云端，写入须 `sudo -u luke`；
- 组件 `internal: true`，所有动作 `mcp.expose: false`，不对外发布。
