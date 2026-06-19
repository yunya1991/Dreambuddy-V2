# 🚧 思维链门禁系统 (Chain-of-Thought Gate System)

> 三扇物理门禁 + 完整的接力协议，确保每个任务按规范执行。
> **三层门禁**：Session级 → D-Z-E三链级 → 输出级

---

## 📋 门禁总览

| 门禁 | 层级 | 类型 | 实现 | 检测时机 |
|:---:|:---:|:---:|:---|:---:|
| **GATE 1** | Session | 🔒 硬拦截 | `step_controller.py` 内 `_require_active()` | step/skip/jump/all 时 |
| **GATE 2** | 输出格式 | 🔔 软警告 | `step_controller.py` 内 `_check_end_format()` | Step 7 或 `all` 完成时 |
| **GATE 3** | D-Z-E三链 | 🔒 硬拦截 | `chain_guard.py` 内 `chain_check()` | transition/check 时 |

---

## 🔗 执行顺序

```
Session 启动
  │
  │ step_controller.py start "任务"          ← 初始化 Session
  │ chain_guard.py init "D-Z-E任务"          ← 初始化 三链
  │
  ▼
Step 1 → Step 2 (三链执行)
  │
  │ chain_guard check d1 d2                 ← GATE 3: 检查跳转合法
  │ chain_guard transition d1 d2            ← ✅ 合法则执行
  │ chain_guard override d1 d3 "授权跳过"    ← 🔄 授权跳步
  │
  ▼
Step 3 → Step 4 → Step 5 → Step 6
  │
  ▼
Step 7 (完成)
  │
  │ ┌─────────────────────────────────────────────┐
  │ │ GATE 2: 检查输出格式                       │
  │ │ ✅ 有数字选择(1️⃣/2️⃣/3️⃣) + 推荐意见 → 通过   │
  │ │ ⚠️ 缺失 → 警告但不阻塞                       │
  │ └─────────────────────────────────────────────┘
  │
  ▼
🎉 全链完成
```

---

## 📂 文件索引

| 文件 | 用途 | 位置 |
|:---|:---|---:|
| `GATE1-2-SESSION.md` | GATE 1+2 详情：Session 开工 + 收工格式 | [查看](GATE1-2-SESSION.md) |
| `GATE3-CHAIN-PHASE.md` | GATE 3 详情：D-Z-E三链阶段跳转 | [查看](GATE3-CHAIN-PHASE.md) |
| `INTEGRATION.md` | 三层门禁集成：完整流程 + 故障排查 | [查看](INTEGRATION.md) |
| `../scripts/chain_guard.py` | GATE 3 实现脚本 | [查看](../scripts/chain_guard.py) |
| `../../scripts/step_controller.py` | GATE 1+2 实现脚本 | [查看](../../scripts/step_controller.py) |
| `../../AGENTS.md` | 使用时必须遵守的规则 | [查看](../../AGENTS.md) |
| `../4-PROTOCOL/PROTOCOL.md` | 三链接力协议 | [查看](../4-PROTOCOL/PROTOCOL.md) |

---

## 🚨 快速自检

| 症状 | 可能原因 | 解决 |
|:---|:---|---:|
| `step N` 返回 BLOCKED | 未启动 Session | `step_controller.py start "任务名"` |
| `check` 返回拒绝 | 三链跳转非法 | 确认顺序：D→D→D→Z→Z→Z→E→E→E |
| Step 7 出现格式警告 | 缺少数字选择/推荐 | `step 7 "1️⃣部署 2️⃣回滚 3️⃣暂停。推荐部署"` |
