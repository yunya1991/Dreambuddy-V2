# GATE 3 — D-Z-E 三链阶段门禁 🔒

> **实现**: `3-CHAIN-DEVELOPMENT/scripts/chain_guard.py`
> **位置**: `~/Dreambuddy-V2/3-CHAIN-DEVELOPMENT/scripts/chain_guard.py`
> **版本**: v1.0（367行）

---

## 功能

D→Z→E 三链执行时，确保阶段跳转合法：

| 跳转类型 | 规则 | 示例 |
|:---|:---|---:|
| 同链顺序 | ✅ 允许 | `d1→d2`, `z2→z3`, `e1→e2` |
| 同链跳步 | ❌ 拒绝 | `d1→d3`（须 override） |
| 跨链跨步 | ❌ 拒绝 | `d3→z1`, `z2→e1` |
| 跨链接力点 | ✅ 允许 | `d4→z1`, `z4→e1` |
| 用户跳过 | 🔄 override 记录理由 | `override d1 d3 "调研已有机"` |

---

## 三链阶段定义

```
D 系列（调研分析）
  d1 深度调研 → d2 分析诊断 → d3 推演验证 → d4 Spec合成
                      ↓
Z 系列（实施规划）
  z1 代码扫描 → z2 范围划分 → z3 路径设计 → z4 验收方案
                      ↓
E 系列（执行落地）
  e1 任务执行 → e2 测试验证 → e3 部署交付
```

---

## CLI 命令

| 命令 | 用途 | 示例 |
|:---|:---|---:|
| `init "描述"` | 初始化新任务 | `init "优化权重中心化接口"` |
| `status` | 查看完整状态 | `status` |
| `check <从> <到>` | 检查跳转合法性 | `check d2 d3` |
| `transition <从> <到>` | 执行合法跳转 | `transition d2 d3` |
| `override <从> <到> <理由>` | 用户指定跳过 | `override d1 d3 "调研已足够"` |
| `approve <阶段>` | 标记已批准 | `approve d1` |
| `start <阶段>` | 标记进行中 | `start e1` |

---

## 拦截效果

```bash
$ python3 chain_guard.py check d1 d3
❌ 拒绝: 同链跳转必须按顺序（d1→d3，但应为 d1→d2）

$ python3 chain_guard.py check d1 z1
❌ 拒绝: 跨链跳转 d1(d)→z1(z) 不允许（只允许 D4→Z1 和 Z4→E1）

$ python3 chain_guard.py override d1 d3 "已有现成方案"
🔄 跳过 d1 → d3: 已有现成方案
```

---

## 实现参考

| 组件 | 行号 | 说明 |
|:---|---:|:---|
| `PHASES_ORDER` | L24-28 | 11阶段定义 (d1→e3) |
| `_get_chain()` | L64-66 | 判断阶段所属链（d/z/e） |
| `chain_init()` | L97-120 | 初始化任务状态 |
| `chain_check()` | L123-175 | 🔒 **核心门禁**：4条跳转规则 |
| `chain_transition()` | L178-203 | 执行合法跳转 |
| `chain_override()` | L206-240 | 用户跳过（记录理由） |
| `chain_approve()` | L248-266 | 标记已批准 |
