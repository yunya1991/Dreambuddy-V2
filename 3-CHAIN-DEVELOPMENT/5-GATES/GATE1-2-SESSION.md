# GATE 1 + GATE 2 — Session 级门禁

> **实现**: `scripts/step_controller.py`
> **位置**: `~/Dreambuddy-V2/scripts/step_controller.py`
> **版本**: v1.1

---

## GATE 1: 开工门禁 🔒（硬拦截）

### 触发条件
调用 `step N` / `skip N` / `jump N` / `all` 时，如果 `0-NOTEBOOK/.step_state.json` 中没有 `session_id`（即未调用过 `start`）。

### 效果
```bash
$ python3 scripts/step_controller.py step 1 "调研"
==================================================
🔒 开工门禁 BLOCKED：未启动任务
  请先运行: step_controller.py start "任务名"

  D-Z-E 项目级任务还需:
  chain_guard.py init "任务描述"   ← 三链阶段管理
==================================================
```

### 绕过方式
- **正确**: `step_controller.py start "任务名"` → 然后 `step 1` ✅
- **不支持**: 任何不经过 `start` 的 step/skip/jump/all 调用 ❌
- `status` 和 `start` 本身不受限

### CLI 验证
```bash
python3 scripts/step_controller.py status           # 检查是否已启动
python3 scripts/step_controller.py start "新任务"    # 启动新任务
python3 scripts/step_controller.py step 1 "调研"     # 通过门禁
```

---

## GATE 2: 收工格式门禁 🔔（软警告）

### 触发条件
`step 7 "备注"` 或 `all` 完成时，检查备注中是否包含：
1. **数字选择** — 含 1️⃣/2️⃣/3️⃣ 或 1./2./3. 或 "下一步"
2. **推荐意见** — 含 "推荐"/"建议"/"我建议"/"建议你"

### 效果
```bash
$ python3 scripts/step_controller.py step 7 "干完了，没想好"
🔔 Gate 2 收工门禁 — 输出格式警告:
  ⚠️ 步进结束格式: 缺少「推荐意见」
  建议修复后再提交，使用: step 7 "正确格式备注"
✅ Step 7 (🧪 记忆蒸馏) 完成
🎉 全部7步完成！
```

### 绕过方式
- **软门禁**: 警告但不阻塞（仍然标记完成）
- **修复**: `step_controller.py step 7 "1️⃣部署 2️⃣回滚 3️⃣暂停。推荐部署。"`

### 标准格式（Gate 2 要求）
```
✅ Step N 完成 — {步骤名}

{简要总结做了什么 + 产出}

下一步：
1️⃣ 继续 Step N+1 — {下一步名称}
2️⃣ 跳过下一步
3️⃣ 跳到 Step X
4️⃣ 直接执行全部
5️⃣ 暂停
```

---

## 实现参考

| 组件 | 行号 | 说明 |
|:---|---:|:---|
| `_require_active()` | L25-43 | Gate 1 核心：检查 session_id |
| `END_FORMAT_CHECK_LIST` | L47-51 | Gate 2 检查项定义 |
| `_check_end_format()` | L53-58 | Gate 2 核心：格式合规检查 |
| `cmd_step()` L103 | L103 | Gate 1 调用点 |
| `cmd_step()` L108-113 | L108-113 | Gate 2 调用点（step 7 时） |
| `cmd_skip()` L129 | L129 | Gate 1 调用点 |
| `cmd_jump()` L153 | L153 | Gate 1 调用点 |
| `cmd_all()` L168 | L168 | Gate 1 + Gate 2 调用点 |
