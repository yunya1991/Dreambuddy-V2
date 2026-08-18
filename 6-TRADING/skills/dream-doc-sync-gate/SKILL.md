---
title: "文档同步门禁 SKILL v1.0"
summary: "PR 提交/合并前检查文档是否与代码变更保持同步，输出待更新文档清单"
trigger:
  - "文档同步"
  - "doc sync"
  - "文档门禁"
  - "doc gate"
  - "PR 文档检查"
  - "dream-doc-sync-gate"
version: "1.0"
updated: "2026-05-27"
---

# 文档同步门禁 SKILL (dream-doc-sync-gate)

> **定位**: PR 提交/合并前置门禁，确保代码变更与文档保持同步
>
> **触发时机**: 每次 PR 创建 / PR 更新 / 手动审查
>
> **输出**: PASS（文档已同步）或 NEEDS_UPDATE（列出待更新文档清单）

---

## 一、门禁规则映射表

### 1.1 代码变更 → 必须更新的文档

| 变更范围 | 触发条件 | 必须更新的文档 |
|---------|---------|--------------|
| **新增 SKILL** | `skills/` 新增目录 | `DOC_INDEX.md`（SKILL表计数+行）<br>`CODE_STRUCTURE.md`（skills/计数） |
| **删除 SKILL** | `skills/` 删除目录 | `DOC_INDEX.md`（移除行）<br>`CODE_STRUCTURE.md`（计数-1） |
| **新增脚本** | `scripts/` 新增 `.py` | `CODE_STRUCTURE.md`（脚本索引表）<br>`DOC_INDEX.md`（Section 3.2） |
| **脚本版本变更** | `scripts/*.py` 修改且版本号变化 | `CODE_STRUCTURE.md`（版本列）<br>`DOC_INDEX.md`（版本列） |
| **新增文档** | `docs/` 新增 `.md` | `DOC_INDEX.md`（Section 2 文档表）<br>`CODE_STRUCTURE.md`（docs/计数） |
| **Sessions 结构变更** | `sessions/_template/` 修改 | `DOC_INDEX.md`（Section 3.1）<br>`README.md`（目录树） |
| **A 系逻辑变更** | `skills/A?-*/SKILL.md` 修改 | `A_SERIES_DETAIL.md`（对应章节）<br>`TRADING_SYSTEM.md`（对应章节） |
| **马丁策略变更** | 止盈止损比例/层数修改 | `TRADING_SYSTEM.md`（Section 3.2.1）<br>`FAQ.md`（Q7） |
| **Screen3 SKILL 变更** | `skills/dream-screen3-third/SKILL.md` | `dream-systematic-trading/docs/third-screen.md` |
| **API 凭证方案变更** | `dream_stop_loss_monitor.py` / `okx_cli.py` | `API_CONFIG_GUIDE.md`（Section 3） |
| **PR 模板变更** | `.github/pull_request_template.md` | 无需其他更新 |

### 1.2 文档变更 → 需检查一致性

| 变更的文档 | 需检查是否冲突的文档 |
|-----------|------------------|
| `TRADING_SYSTEM.md` | `A_SERIES_DETAIL.md`, `FAQ.md`, `dream-screen3-third/SKILL.md` |
| `DOC_INDEX.md` | `CODE_STRUCTURE.md`（计数一致性） |
| `sessions/_template/meta.json` | `ARTIFACT_STORAGE_GUIDE.md` |

---

## 二、执行步骤

### Step 1: 获取变更文件列表

```
输入: PR 的 changed files 列表（或 git diff --name-only）

来源:
  - PR 界面: Files Changed 标签页
  - 命令行: git diff main...HEAD --name-only
  - Claude Code: /diff 或读取 PR 信息
```

### Step 2: 匹配门禁规则

```yaml
对每个变更文件:
  1. 匹配上表"触发条件"
  2. 收集所有"必须更新的文档"
  3. 去重后输出待更新列表

特殊处理:
  - 如果变更的文件本身就是"必须更新的文档"之一 → 该条规则视为满足
  - 如果只修改了文档（无代码变更）→ 检查文档间一致性即可
```

### Step 3: 检查文档是否已更新

```yaml
对每个"必须更新的文档":
  检查该文档是否出现在 PR 的 changed files 中:
    是 → ✅ 已更新
    否 → ❌ 待更新（加入阻塞清单）
```

### Step 4: 输出结果

```
PASS 条件: 所有"必须更新的文档"都出现在 changed files 中

NEEDS_UPDATE 条件: 有任何文档未同步

输出格式（见 Section 三）
```

---

## 三、输出格式

### PASS 输出

```markdown
## ✅ 文档同步门禁: PASS

变更文件数: {n}
文档检查项: {m} 项全部满足

已验证:
- ✅ CODE_STRUCTURE.md 已更新（新增 dream-screen3-third）
- ✅ DOC_INDEX.md 已更新（SKILL 计数 22→23）
```

### NEEDS_UPDATE 输出

```markdown
## ❌ 文档同步门禁: NEEDS_UPDATE

以下文档需要在合并前更新:

| 文档 | 原因 | 优先级 |
|------|------|--------|
| `DOC_INDEX.md` | 新增 SKILL dream-xxx 未在表中注册 | 🔴 高 |
| `CODE_STRUCTURE.md` | skills/ 计数未更新（当前写 22，实际 23） | 🔴 高 |
| `API_CONFIG_GUIDE.md` | okx_cli.py 凭证方式变更未反映 | 🟡 中 |

建议操作:
1. 更新上述文档中标注的内容
2. 重新提交 PR
3. 重新运行本门禁

阻塞提交: 是（🔴 高优先级项未更新不允许合并）
```

---

## 四、优先级定义

| 优先级 | 含义 | 是否阻塞合并 |
|--------|------|------------|
| 🔴 高 | 索引/计数/版本号不一致，导致文档误导 | **是** |
| 🟡 中 | 描述陈旧，不影响功能但影响理解 | 建议更新，不强制 |
| 🟢 低 | 说明文字优化，非必须 | 不阻塞 |

---

## 五、高优先级规则（P0，合并前必须满足）

```yaml
P0 规则（任一触发即阻塞合并）:
  1. skills/ 新增目录 → DOC_INDEX.md SKILL 计数必须更新
  2. scripts/*.py 版本号变更 → CODE_STRUCTURE.md 版本表必须更新
  3. 马丁策略核心参数（加仓次数/止损比例）变更 → TRADING_SYSTEM.md 必须同步
  4. sessions/_template/ 结构变更 → ARTIFACT_STORAGE_GUIDE.md 必须同步
  5. pretrade_gatekeeper.py 路径/接口变更 → dream-screen3-third/SKILL.md 必须同步
```

---

## 六、PR checklist 模板

在每个 PR description 中加入以下 checklist（已集成到 `.github/pull_request_template.md`）：

```markdown
## 📋 文档同步检查

> 根据 dream-doc-sync-gate 规则，请勾选已完成项：

- [ ] 无需文档更新（仅 bug fix / 测试 / 配置，无结构变化）
- [ ] `DOC_INDEX.md` 已同步（新增/删除 SKILL 或文档）
- [ ] `CODE_STRUCTURE.md` 已同步（计数/版本更新）
- [ ] `README.md` 已同步（目录结构变化）
- [ ] `TRADING_SYSTEM.md` 已同步（A 系逻辑/马丁策略变更）
- [ ] `API_CONFIG_GUIDE.md` 已同步（凭证/接口变更）
- [ ] `ARTIFACT_STORAGE_GUIDE.md` 已同步（sessions 结构变更）
- [ ] `A_SERIES_DETAIL.md` 已同步（A 系 SKILL 变更）

门禁运行: 手动触发 "dream-doc-sync-gate" SKILL 验证，或在 PR 描述中说明跳过原因。
```

---

## 七、快速参考

```
手动触发命令（在 Claude Code 中）:
  "运行文档同步门禁检查，当前 PR 变更了 [文件列表]"

自动触发条件:
  - 每次 PR 创建时在 PR 描述中提示
  - 每次 PR 请求合并时检查 checklist 是否全部勾选

豁免条件（不需要运行门禁）:
  - 仅修改 sessions/ 中的实际产物文件（非 _template）
  - 仅修改 .workbuddy/memory/ 中的记忆文件
  - 仅修改测试/回测相关文件（data/ reports/ test_results.json）
```
