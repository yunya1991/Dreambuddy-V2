---
name: hermes-token-savings
description: "Hermes Token 节省指南 — config优化 + 记忆系统 + Prompt规范 + 压缩调优。触发词: token优化、节省token、记忆配置、压缩参数、prompt优化、hermes调优"
version: "1.0"
created: "2026-06-09"
status: "active"
category: system
---
---
priority: CRITICAL
scope: ALL_TASKS
---

# ⚠️ 宪法级规则 — 本 SKILL 必须优先调用

> **触发条件**: 任何 Hermes Agent 任务 (cron job / 用户对话 / 工具调用)
> **执行时机**: 执行任何操作之前, 必须先读取本 SKILL
> **违反后果**: 无谓消耗 Token, 可能导致流式超时 (Broken pipe)

## 第零条: 目录优先原则 (Token 节省宪法)

当 Agent 需要参考任何大型文件/文档时:

1. **先看目录** — 找对应的 `.toc` / 目录索引 / 文件头部结构
2. **按需读取** — 通过目录找到具体章节, 只读需要的部分
3. **绝不全文加载** — 禁止一次性加载整个大文件到上下文

适用对象:
- AGENTS.md → 先看 `AGENTS.md.toc`, 再按需读 `AGENTS.md.full.bak` 特定章节
- SKILL.md → 先看 SKILL 的 frontmatter + 目录结构, 再按需读具体章节
- 任何 >5KB 的文件 → 先看结构, 再按需读取

示例:
```
❌ 错误: 直接 read_file("AGENTS.md") → 加载 53KB → 13,260 tokens
✅ 正确: read_file("AGENTS.md.toc") → 找到行号 → read_line_range("AGENTS.md.full.bak", 820, 860) → ~200 tokens
```

## 第一条: 本 SKILL 优先

执行任何任务之前, 先检查本 SKILL 中是否有相关的 Token 节省建议。

## 第二条: Prompt 精简

新建或修改 cron job prompt 时:
- 控制在 2000 字符以内
- 不用 Python import 投递代码, 用 bash 命令
- 不引用不存在的 skill

## 第三条: 压缩优于加载

如果信息可以通过压缩/摘要获得, 不要加载原文。



# Hermes Token 节省 SKILL v1.0

> **定位**: 系统级优化指南，不嵌入执行流，作为 A 系列任务的性能基线参考。
> **目标**: 在不影响质量的前提下，每轮对话节省 15-25% Token。

---

## 一、config.yaml 最优参数（已应用）

```yaml
# ~/.hermes/config.yaml

memory:
  memory_enabled: true
  user_profile_enabled: true
  memory_char_limit: 4096        # 2200→4096，避免记忆截断
  user_char_limit: 2048          # 1375→2048，避免上下文截断
  provider: ""                   # 空=内置文件记忆，零API调用

compression:
  enabled: true
  threshold: 0.4                 # 0.5→0.4，更早触发压缩
  target_ratio: 0.15             # 0.2→0.15，压缩更狠
  protect_first_n: 3             # 保护系统prompt+前2轮
  protect_last_n: 15             # 20→15，省~5条消息
  hygiene_hard_message_limit: 300  # 400→300，更早强制压缩
  abort_on_summary_failure: false

prompt_caching:
  cache_ttl: "30m"               # 5m→30m，cron任务可复用缓存

sessions:
  auto_prune: true               # False→True，自动清理
  retention_days: 30             # 90→30，减少磁盘67%
  vacuum_after_prune: true
  min_interval_hours: 24
  write_json_snapshots: false

agent:
  max_turns: 100                 # 150→100，防止runaway
  task_completion_guidance: false  # True→False，省~200tokens/轮
  environment_probe: false       # True→False，启动不浪费token
  gateway_auto_continue_freshness: 1800  # 与cache TTL对齐
```

---

## 二、三层记忆架构（高质量+省Token）

### 2.1 架构设计

```
~/.workbuddy/memory/
├── working_memory.md    (227 bytes)  工作记忆 — 当前交易状态
├── project_memory.md    (275 bytes)  项目记忆 — 系统架构/API/路径
├── lessons_memory.md    (272 bytes)  经验记忆 — 已解决/已知阻塞
└── a6_ledger.md         (161 bytes)  A6情报账本 — 事件记录
```

### 2.2 各层职责

| 层级 | 文件 | 内容 | 更新频率 | 保留 |
|---|---|---|---|---|
| 工作记忆 | working_memory.md | 当前持仓/最近决策/市场状态/阻塞项 | 每次A5/A6/A9后 | 7天滚动 |
| 项目记忆 | project_memory.md | 双架构设计/A系列职责/API配置/投递规范 | 架构变更时 | 永久 |
| 经验记忆 | lessons_memory.md | 已解决问题/已知阻塞/设计原则 | 发现问题时 | 永久 |
| A6账本 | a6_ledger.md | 情报监控事件/方向/假设 | 每次A6执行 | 永久 |

### 2.3 写入规范

```markdown
# working_memory.md 更新格式
## 当前持仓
- {方向} {币种} sz={数量} entry={价格}

## 最近决策
- 最后 A9: {HOLD/EXIT} ({时间})
- 最后 A1: {regime}, BTC {价格} ({时间})

## 阻塞项
- {问题描述}
```

```markdown
# lessons_memory.md 新增格式
### {问题简述} ({日期})
- 问题: {描述}
- 根因: {分析}
- 解决: {方案}
- 预防: {如何避免}
```

### 2.4 总 Token 占用

全部记忆文件总计 **~935 bytes ≈ 234 tokens**，远低于默认 memory_char_limit (4096)，确保每次加载完整不截断。

---

## 三、Prompt 编写规范（避免浪费）

### 3.1 ❌ 禁止引用不存在的 Skill

```yaml
# 错误 — 这些 skill 不存在:
use_skill("macro-monitor")      # ❌ 不存在
use_skill("odaily")             # ❌ 不存在
use_skill("artifact-alignment-manager")  # ❌ 不存在
```

```yaml
# 正确 — 使用实际可用工具:
- OKX CLI: okx market ticker BTC-USDT-SWAP --profile dreamdemo
- Tavily搜索: 通过 tavily_search 工具
- Web搜索: 使用 web_search 工具（backend=tavily）
- 文件操作: read_file / write_file / bash cp
```

### 3.2 ❌ 禁止在 Prompt 中写 Python 投递代码

Hermes Agent 沙箱无法执行 `import sys; from a_product_delivery import ...`

```bash
# 正确 — 使用 bash 命令:
TARGET1="/home/ubuntu/.workbuddy/skills/boss-secretary/reports/trading"
TARGET2="/home/ubuntu/archives/Dreambuddy-V2-main/6-TRADING/artifacts/{phase}"
mkdir -p $TARGET2
cp $TARGET1/{pattern} $TARGET2/ 2>/dev/null || true
```

### 3.3 Prompt 长度优化

- **精简原则**: 只保留必要信息，删除冗余解释
- **结构化**: 用表格/列表替代长段落
- **引用路径**: 写绝对路径，避免 Agent 搜索浪费时间
- **删除重复**: 同一约束不要在多处重复

---

## 四、AGENTS.md 按需加载（已实施）

### 4.1 问题与解决

AGENTS.md 53KB (6573词 ≈ 13,260 tokens) 已从 **自动加载全文** 改为 **TOC 目录索引 + 按需读取**。

| 文件 | 大小 | 用途 | 加载时机 |
|---|---|---|---|
| `AGENTS.md` | ~627 bytes (~156 tokens) | 轻量重定向, 指向 TOC | 每次自动加载 |
| `AGENTS.md.toc` | ~4,785 bytes (~1,196 tokens) | 目录索引, 含行号和查找表 | Agent 按需读取 |
| `AGENTS.md.full.bak` | 53KB (~13,260 tokens) | 完整开发文档备份 | 仅按需读取特定章节 |

**Token 节省: ~13,104 tokens/请求 (-99%)**

### 4.2 Agent 使用流程

1. 需要参考开发文档时, 先读 `AGENTS.md.toc` 找到章节和行号
2. 用 `read_line_range("AGENTS.md.full.bak", start_line, end_line)` 读取具体章节
3. 不加载整个文件, 只加载需要的章节

例如:
- 添加 cron job → 读取 L820-L860 (~40行, ~200 tokens)
- 添加 skill → 读取 L587-L716 (~130行, ~650 tokens)
- 添加 tool → 读取 L263-L310 (~48行, ~240 tokens)

### 4.3 快速查找表

| 你需要... | 章节 | 行号 |
|:---|:---|:---|
| Cron 定时任务 | Cron | L820-L860 |
| Skills 技能系统 | Skills | L587-L716 |
| 添加新工具 | Adding New Tools | L263-L310 |
| 配置系统 (config/.env) | Adding Configuration | L334-L397 |
| Agent 核心循环 | Agent Loop | L119-L142 |
| 已知陷阱 | Known Pitfalls | L947-L1011 |
| 测试框架 | Testing | L1012-L1089 |
| 插件系统 | Plugins | L487-L586 |

完整目录见 `AGENTS.md.toc`

---

## 五、可用 Skill 清单（定期更新）

### 5.1 交易相关 (6-TRADING)

| Skill | 用途 |
|---|---|
| `dream-intelligence-monitor` | A6 情报监控 |
| `dream-contradiction-theory` | A0 矛盾论 |
| `dream-first-principles` | A2 第一性原理 |
| `dream-exit-skill-v2` | A9 离场决策 |
| `A7-practice-theory` | A7 实践论门禁 |
| `A8-theory-practice-verification` | A8 理论验证 |
| `dream-tactical-validator` | A4 战术验证 |
| `dream-tactical-executor` | A5 战术执行 |

### 5.2 通用工具

| Tool | 用途 |
|---|---|
| `okx` | OKX CLI（必须带 --profile dreamdemo） |
| `tavily_search` | 网络搜索（默认 backend） |
| `web_search` | 备选搜索 |
| `bash` | 执行命令 |
| `read_file` / `write_file` | 文件读写 |

---

## 六、Token 节省 Checklist

每次新建或修改 Hermes cron Job Prompt 时检查：

- [ ] 不引用不存在的 skill（macro-monitor, odaly, artifact-alignment-manager 等）
- [ ] 不用 Python import 投递代码，用 bash cp
- [ ] 路径用绝对路径，不写相对路径
- [ ] 约束只写一次，不重复
- [ ] 包含双通道投递指令（飞书 + 本地）
- [ ] 飞书群组 ID 写对（oc_xxx 格式）
- [ ] 本地路径: `~/.workbuddy/skills/boss-secretary/reports/trading/`
- [ ] 备份路径: `/home/ubuntu/archives/Dreambuddy-V2-main/6-TRADING/artifacts/{phase}/`
- [ ] OKX 命令带 `--profile dreamdemo`
- [ ] Prompt 长度控制在 2000 字符以内（除非必要）

---

## 七、性能基线

| 指标 | 优化前 | 优化后 | 改善 |
|---|---|---|---|
| Memory limit | 2200 chars | 4096 chars | +86% |
| Compression trigger | 50% context | 40% context | 更早 |
| Compression target | 20% | 15% | -25% |
| Prompt cache TTL | 5min | 30min | +500% |
| Session retention | 90 days | 30 days | -67% |
| Max turns | 150 | 100 | -33% |
| Memory system tokens | ~0 (截断) | ~234 (完整) | 质量↑ |
| 每轮 token 估算 | 基线 | 基线×0.75~0.85 | -15~25% |
