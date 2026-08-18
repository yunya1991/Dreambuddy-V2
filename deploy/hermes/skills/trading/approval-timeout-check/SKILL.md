---
name: approval-timeout-check
description: 审批超时守卫 — 检查 PENDING 审批单，超时后触发 AI 兜底决策。每 10 分钟 cron 触发。
category: trading
triggers:
  - cron: "*/10 * * * *"
---

# SKILL: approval-timeout-check
# 触发时机: 每 10 分钟 (cron: */10 * * * *)
# 角色: 审批超时守卫 — 检查 PENDING 审批，超时后触发 AI 兜底决策

## ⚠️ FIRST: 解决名称冲突（如果此 skill 加载失败）

本 skill 存在已知冲突：`skills/approval-timeout-check.md`（裸 .md 文件）与 `skills/trading/approval-timeout-check/SKILL.md`（目录版本）同名导致加载器歧义。

**如果 cron 触发时提示 "skill not found" 或有歧义错误，说明冲突仍存在。此时不要中止——直接按本 skill 的流程内联执行核心逻辑：**
1. 用 `execute_code` 运行 `approval_agent.py check`（或手动读取 `approval_state.json`）
2. 按下方的 AI 决策规则判断
3. 无待处理审批时输出 `[SILENT]`

长期修复：手动删除裸文件 `C:\Users\luke.zhang\.hermes\skills\approval-timeout-check.md`。

---

## 职责

检查 approval_state.json 中所有 PENDING 审批单。
超过 30 分钟未处理 → AI 基于 session 上下文做决策 → 自动执行审批。

---

## 执行

首选 `terminal` 工具执行：

```bash
python C:/tmp/Dreambuddy-V2/6-TRADING/scripts/approval_agent.py check
```

### 降级路径

若 `terminal` 因 CWD 解析失败（常见于 Windows/MSYS 环境，报 `cd: No such file or directory`），降级为 `execute_code` + `subprocess.run()`：

```python
import subprocess, sys
result = subprocess.run(
    [sys.executable, "C:/tmp/Dreambuddy-V2/6-TRADING/scripts/approval_agent.py", "check"],
    capture_output=True, text=True, timeout=30, cwd="C:/tmp"
)
print(result.stdout)
```

若脚本文件不存在（FileNotFoundError），输出 `[SILENT]` 并退出，不阻塞 cron 链。

---

## AI 决策规则

### Gate-C 自动批准（所有条件同时满足）
- composite_confidence >= 70%
- A7 评分 >= 32/40
- Screen1 得分 >= 55
- 价格漂移 < 5%
- red_team_flag = false

### Gate-C 强制拒绝（任意一条）
- composite_confidence < 60%
- Screen1 得分 < 40
- 连续 SKIP >= 3 次
- red_team_flag = true

### 灰色地带（60-70%）
保守拒绝 + 推送"建议人工再次确认"

### A9 离场决策
- exit_score >= 65 → 批准离场
- exit_score < 40  → 保持持仓
- 中间区间 → 遵从 A9 的 decision 字段

---

## 系统健康标注（无待审批时执行）

即使无待审批单，也读取 `project_trading_session_state.md` 并标注以下非阻塞风险：

| 检查项 | 字段/条件 | 风险信号 |
|--------|-----------|----------|
| Process D 复盘 | `last_process_d: null` | 学习闭环未启动 |
| Gate C 阈值不足 | `screen1_score < 60` | 即使入场信号触发也需人工覆盖 |
| 梦游告警 | `team_b_consecutive_skips >= 7` | 提前触发 Process D |
| 持仓离场超时 | `current_position.status: holding` + 无 A9 | 需人工确认离场 |
| Red Team 升级 | `screen1_red_team_flag: true` | Gate C 阈值提升至 70 |

## 输出

- 有决策：`approval_agent.py` 内部通过 `send_msg()`（lark-cli `im message send`）推送至 Trading-RiskControl，标注 `[AI代决]`
- **无待审批：输出 `[SILENT]`**（cron deliver 已设 `local`，不会推送到群）
- 提示可在飞书审批中心覆盖此决策

## 关键路径

| 文件 | 路径 | 备注 |
|------|------|------|
| 审批代理 | `C:/tmp/Dreambuddy-V2/6-TRADING/scripts/approval_agent.py` | v2: REST API（lark-cli 不支持 approval instances create，且 get 被 strict-mode 阻止） |
| 审批状态 | `C:/tmp/Dreambuddy-V2/6-TRADING/approval_state.json` | 由 `approval_agent.py` register 写入 |
| 会话状态 | `C:/Users/luke.zhang/.claude/projects/C--Users-luke-zhang/memory/project_trading_session_state.md` | |
| 风控群 | Trading-RiskControl (`oc_20fcedf0c35035568ea8fa947380f75d`) | |
| App ID | `cli_aa95b2dee3b85bd1`（云涯Hermes） | 已统一，不再使用旧 App `cli_aa9442` |

---

## 失败处理
- approval_agent.py 异常 → 打印错误，**不阻塞**，下次 cron 继续检查
- lark-cli approve/reject 失败 → 推送 `[AI代决失败]` 警告到风控群
- 脚本文件不存在 → 输出 `[SILENT]`，不阻塞 cron 链
- **terminal 工具不可用**（bash `cd:` 路径错误，exit_code 126） → 降级到 execute_code（见下方降级路径）；连续失败 ≥2 次后立即切换，不要再重试 terminal
- **read_file 不可用**（路径解析失败、"File not found" 但文件存在、"unchanged" 空内容 dedup 误判） → 降级到 execute_code 内 Python `open()` 读取同一文件；确认文件存在后直接在 execute_code 完成全部读取和解析
  - 特别注意 dedup 误判：当 read_file 返回 `"file unchanged since last read"` + `dedup: true` 但其内容从未在此 session 被成功读取时，这是假阳性 — 文件确实存在但 dedup 层出错，此时立即降级到 execute_code
- **search_files 不可用**（ripgrep 未安装、"rg not found"） → 降级到 execute_code 内 Python `os.walk()` / `glob.glob()` 搜索文件；不要因 search_files 失败而中止
- 无待处理审批（approval_state.json = `{}`）→ 输出 `[SILENT]`，这是最常见的正常情况
- **工具降级优先级**: execute_code > terminal > read_file > search_files。当 terminal 失败时直接跳到 execute_code，跳过 read_file/search_files — execute_code 可替代所有文件操作
