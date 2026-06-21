# Skills 索引查询示例（像数据库一样用）

数据文件：

- `skills/catalog/skills_index_current.json`
- `skills/catalog/minimal_skills_catalog.json`

> 说明：以下命令默认在仓库根目录执行（`经典指标机器学习系统/`）。不改后端代码的前提下，用 `jq` / `grep` 即可完成按 domain/category/level 的快速查询。

## 1) 快速列出所有 tool

```bash
jq -r '.items[].tool' skills/catalog/skills_index_current.json | sort
```

## 2) 按 category 查询（read/audit/sandbox/push/trade/governance/repo/contract/routing）

```bash
jq -r '.items[] | select(.category=="read") | .tool' skills/catalog/skills_index_current.json | sort
```

也可以把工具名和标题一起输出：

```bash
jq -r '.items[] | select(.category=="trade") | "\(.tool)\t\(.title // \"\")"' skills/catalog/skills_index_current.json | sort
```

## 3) 按 level 查询（R0/R1/R2/R3）

```bash
jq -r '.items[] | select(.level=="R0") | .tool' skills/catalog/skills_index_current.json | sort
```

## 4) 按 kind 查询（inproc/outbox_channel/host_script/sandbox_script/config_copy/schema…）

```bash
jq -r '.items[] | select(.kind=="host_script") | "\(.tool)\t\(.impl.file)"' skills/catalog/skills_index_current.json | sort
```

## 5) 组合查询：找“Binance + audit + R0”

```bash
jq -r '.items[]
  | select((.tool | startswith("binance_")) and .category=="audit" and .level=="R0")
  | "\(.tool)\t\(.title // \"\")"
' skills/catalog/skills_index_current.json | sort
```

## 6) 组合查询：找“push 类（Twitter/TG）”

```bash
jq -r '.items[]
  | select(.category=="push")
  | "\(.tool)\t\(.kind)\t\(.impl.file)"
' skills/catalog/skills_index_current.json | sort
```

## 7) 反查：某个工具对应的实现文件

```bash
TOOL="binance_spot.trade"
jq -r --arg t "$TOOL" '.items[] | select(.tool==$t) | .impl.file' skills/catalog/skills_index_current.json
```

## 8) 用 grep 快速检索（没有 jq 也能用）

查某个 tool 出现在哪里：

```bash
grep -R --line-number --fixed-string "binance_spot.trade" skills/catalog
```

查某个域（例如 twitter）相关条目：

```bash
grep -R --line-number --ignore-case "\"twitter" skills/catalog
```

## 9) 从 minimal catalog 查三大域（binance/twitter/news）

```bash
jq -r '.domains[].domain' skills/catalog/minimal_skills_catalog.json
```

列出某个 domain 下的所有 tool：

```bash
DOMAIN="binance"
jq -r --arg d "$DOMAIN" '.domains[] | select(.domain==$d) | .items[].tool' skills/catalog/minimal_skills_catalog.json | sort
```

## 10) 查询自动化控制面编排意图（Bugfix + 贝叶斯 + 四类触发）

```bash
jq -r '.items[]
  | select(
      .tool=="bugfix.triage_and_draft" or
      .tool=="bayes.optimize.strategy_scope" or
      .tool=="bayes.optimize.system_scope" or
      .tool=="nanoclaw.control.gtw_run" or
      .tool=="nanoclaw.control.shadow_loop_run" or
      .tool=="nanoclaw.control.paramopt_trigger" or
      .tool=="nanoclaw.control.system_monitor_run" or
      .tool=="qwen.control.gtw_run" or
      .tool=="qwen.control.shadow_loop_run" or
      .tool=="qwen.control.paramopt_trigger" or
      .tool=="qwen.control.system_monitor_run"
    )
  | "\(.tool)\t\(.level)\t\(.category)\t\(.gates // [])"
' skills/catalog/skills_index_current.json
```

从 minimal catalog 反查 automation domain：

```bash
jq -r '.domains[]
  | select(.domain=="automation")
  | .items[]
  | "\(.tool)\t\(.capability_level)\t\(.category)\t\(.gates // [])"
' skills/catalog/minimal_skills_catalog.json
```
