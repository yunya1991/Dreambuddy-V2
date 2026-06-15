# 三层门禁集成

> 思维链门禁系统的完整运行流程 + 故障排查

---

## 完整执行流程

```
Session 开始
  │
  │ ① step_controller.py start "第X周交易升级"  ← 初话化 Session
  │ ② chain_guard.py init "权重中心化"         ← 初话化 三链
  │
  ▼
Step 1 ── 需求解析
  │ 输出格式: "需求已澄清。下一步：1️⃣继续 2️⃣跳过"
  │
  ▼
Step 2 ── 思维链调研 (D→Z→E 执行)
  │
  │ --- D 系列 ---
  │ chain_guard start d1
  │ → 执行 D1 调研
  │ chain_guard transition d1 d2     ← GATE 3 检查
  │ → 执行 D2 分析
  │ chain_guard transition d2 d3
  │ → 执行 D3 推演
  │ chain_guard transition d3 d4
  │ → 执行 D4 Spec
  │
  │ --- Z 系列 ---
  │ chain_guard transition d4 z1     ← GATE 3 跨链接力点
  │ → ...
  │ chain_guard transition z4 e1     ← GATE 3 跨链接力点
  │
  │ --- E 系列 ---
  │ → e1 → e2 → e3
  │
  ▼
Step 3 ── 知识库检索与回补
Step 4 ── A系列方法论借鉴
Step 5 ── 索引系统更新
Step 6 ── 飞书协作归档
  │
  ▼
Step 7 ── 记忆蒸馏
  │ step_controller.py step 7 "1️⃣部署 2️⃣回滚。推荐部署"
  │ └─ GATE 2 检查格式 ✅
  │
  ▼
🎉 全链完成
```

---

## 故障排查速查

| 现象 | 门禁 | 原因 | 修复 |
|:---|:---:|:---|:---|
| `step N` 被 BLOCKED | GATE 1 | 未 `start` | `step_controller.py start "任务"` |
| `check` 返回拒绝 | GATE 3 | 跳转不合法 | 检查三链顺序 |
| Step 7 出现 ⚠️ 警告 | GATE 2 | 格式缺数字选择/推荐 | `step 7 "1️⃣2️⃣3️⃣"` 重做 |
| `chain_guard.py` 报"状态未初始化" | GATE 3 | 未 `init` | `chain_guard.py init "描述"` |
| 想跳步但被 GATE 3 拦截 | GATE 3 | 同链跳步/非法跨链 | `chain_guard.py override d1 d3 "理由"` |

---

## 门禁优先级

```
GATE 1 (Session开工)  >  GATE 3 (三链跳步)  >  GATE 2 (输出格式)
    硬拦截                   硬拦截                  软警告
```

即：先过 Session 关 → 再过三链关 → 最后格式检查。
