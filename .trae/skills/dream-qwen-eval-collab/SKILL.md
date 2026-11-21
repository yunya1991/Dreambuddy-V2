---
name: dream-qwen-eval-collab
description: "已弃用（2026-11-18）：取消千问/DeepSeek 角色分工，默认执行与评审均由 DeepSeek 承担。本文件仅作 bsk/百炼通道经验存档，不再触发。"
version: 3.0.0
created: 2026-09-21
updated: 2026-11-18
license: Internal
status: deprecated
category: orchestration
triggers: []
depends_on: [bailian-api, bsk, skill-creator]
provides: [qwen-exec-orchestration]
cognitive_links: [VM-1790001192903-2224e07e, VM-1790001702811-24bffe86]
---

> **状态：已弃用（2026-11-18）**
> 用户决定取消角色分工：**默认只有 DeepSeek 一个执行/评审者**，云端不使用千问。
> 弃用原因：千问通道不稳定（旧密钥全模型 `AccessDenied.Unpurchased`；云端到阿里云 cn-beijing 出网不通），协作收益不足以抵消编排成本。
> 保留内容：百炼端点/密钥纪律、bsk contenteditable 踩坑记录，供将来恢复时参考。**不要再按本文流程编排。**

## Autonomy Boundary

可自主执行：
- 任务包构建、上下文裁剪、千问调用、评审、落盘、跑测试
- 编排状态监控与汇报

需用户确认：
- 跨模块/跨子系统改动
- 删除文件、改核心编排规则、涉及实盘交易的变更

禁止：
- 把千问产出未经评审+测试直接落盘
- Trae 代写实现（仅允许修复评审发现的 P0 小问题，且必须在评审报告标注「Trae 代修 + 原因 + 行数」）
- 绕过 TDD/回归/门禁

# Dream Qwen Eval Collab — 千问执行 / DeepSeek 评审 编排 SKILL（已弃用）

> v1 是「千问调研、Trae 评估」，v2 曾按用户要求互换身份（千问执行、Trae 评审），
> v3（2026-11-18）**取消角色分工**，本 SKILL 停止使用，保留通道经验。

---

## 0. 角色定义（v2 起生效）

| 角色 | 承担者 | 职责 | 红线 |
|------|--------|------|------|
| 执行者 | 千问 `qwen3.8-max`（百炼 OpenAI 兼容） | 按任务包产出实现代码、补丁、测试、脚本 | 不读仓库、不执行命令、不直接改文件；不得输出省略号占位 |
| 评审者 | Trae（DeepSeek） | 任务包、上下文裁剪、5 维评审、应用补丁、跑测试、认知回写 | 不得代写实现；不得因「看起来对」跳过测试 |
| 用户 | 用户 | 需求确认、跨模块变更放行、最终验收 | — |

---

## 一、何时调用（触发条件）

满足任一条件即调用：

1. **用户要求切换执行者**：「千问执行」「千问来写」「让千问主导」「角色互换」「切换执行者」
2. **实现类任务**：需要产出代码/补丁/测试，且用户明确不走 Trae 直写
3. **返工**：评审 7.0–8.4 分，需把 P0/P1 改进项回送千问
4. **hermes 反思**：「形成 SKILL」「反思」「可复用经验」，决定是否衍生新 SKILL

不适用：纯侦察/定位类问题（直接读代码更快）、一句话改动、用户明确要求 Trae 直接实现。

---

## 二、5 步标准流程

### 步骤 1：执行任务包（Trae 主导）

**输入**：用户需求文本

**输出**：`<run_id>/task.md`，字段固定：

```yaml
目标: <一句话，可验证>
改动范围: [<目标文件绝对/相对路径>]
接口契约: <函数签名/类型/HTTP 契约/数据结构>
约束: [HC-1a, HC-9, FAIL-OPEN, 零回归, 模块化开关, ...]
输出格式: diff | 完整文件 | 测试 + 实现
验收标准: <可执行断言，如「pytest tests/x.py -q 全绿」>
禁止: [<不能碰的文件/依赖/全局变量>]
```

**run_id 约定**：`YYYYMMDD-HHMM-<slug>`，产物目录 `.trae/documents/qwen-exec/<run_id>/`。

### 步骤 2：上下文裁剪（Trae 主导）

千问看不到仓库，上下文由 Trae 供给。规则：

1. 只给**相关文件的片段**（带 `文件:行号` 标注），不给整仓
2. 必须给：接口定义、调用方、现有测试、错误日志原文
3. 单次 prompt ≤ 30k 字符；超出按「文件边界」拆成多轮，不要硬塞
4. 密钥、`.env` 值、用户隐私一律脱敏后再入 prompt

**输出**：`<run_id>/prompt.md`（system + user 合并稿）

### 步骤 3：千问执行（执行者产出）

**前置检查（每次必跑，失败即停，不得跳过）**

```bash
export PYTHONPATH="/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/16-调控系统/core"
python3 -c "
from qwen_client import chat_completion
r = chat_completion([{'role':'user','content':'只回复OK'}], max_tokens=16, timeout=40)
print('ok=', r.success, 'model=', r.model, 'err=', r.error[:200])
"
```

`ok=False` → 进入 §三 的降级通道决策，禁止继续。

**执行调用**

```bash
export PYTHONPATH="/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/16-调控系统/core"
python3 - <<'PY'
import pathlib
from qwen_client import chat_completion

run = pathlib.Path(".trae/documents/qwen-exec/<run_id>")
prompt = (run / "prompt.md").read_text(encoding="utf-8")
system = (
    "你是实现者，只能根据给定片段与契约产出代码，不得臆造仓库中不存在的接口。"
    "输出必须是可直接落盘的完整片段：补丁用 unified diff（带 ---/+++ 与 @@ 行号）；"
    "新文件给完整内容；禁止省略号、TODO、伪代码。"
    "每个改动块前用一行注释标注目标文件路径。"
)
r = chat_completion(
    [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
    max_tokens=8000, temperature=0.2, timeout=300,
)
(r / "qwen_output.md").write_text(r.content, encoding="utf-8")
print("ok=", r.success, "model=", r.model, "chars=", len(r.content), "err=", r.error[:300])
PY
```

**输出**：`<run_id>/qwen_output.md`

### 步骤 4：评审（Trae 主导，一票否决制）

五维评分（0–10），逐维给证据（引用 qwen_output 行号 / 仓库行号）：

| 维度 | 评分要点 |
|------|---------|
| 正确性 | 是否满足接口契约、边界、异常路径完整 |
| 可落地性 | 补丁能否 `git apply`、新文件是否自洽、导入是否存在 |
| 工程合规 | HC-1a/HC-9/FAIL-OPEN/零回归/模块化开关 |
| 风险 | 安全、权限、密钥、并发、交易下单路径 |
| 最小改动 | 是否超范围重构、是否引入不必要依赖 |

**一票否决（直接 < 7.0）**：硬编码密钥、越权写、绕过风控、实盘下单未确认、删除既有测试。

**阈值与动作**

| 综合评分 | 动作 |
|---------|------|
| ≥ 8.5 | 进入步骤 5 落地 |
| 7.0–8.9 | 列出 P0/P1 返工项，回送千问（最多 2 轮；返工 prompt 必须附失败证据） |
| < 7.0 | 重做步骤 1 任务包（通常是任务包/上下文给错，而非模型能力） |

**输出**：`<run_id>/review.md`（评分表 + 证据 + 返工项 + 结论）

### 步骤 5：落地 + 验证 + 认知闭环（Trae 主导）

1. 应用补丁（`git apply --3way` 或按段写入），**逐文件核对**，不整包覆盖
2. 跑验收标准里的命令（pytest / tsc / 目标脚本），失败 → 附完整日志回步骤 3（计入返工轮次）
3. 通过后：更新受影响文档索引（如涉及）→ `record` 经验
4. **hermes 反思**：按 §六 决策树判断是否衍生 SKILL

**record 模板**

```
record(
  content="[千问执行] <目标一句话> | run_id <id> | 评审 <X.X> | 返工 <N> 轮 | 测试 <命令> 通过",
  quality_level="B",
  tags="千问执行,角色互换,输出纪律,评审门禁,<域标签>"
)
```

---

## 三、执行通道配置

### 主通道：百炼 API（OpenAI 兼容）

| 项 | 值 |
|----|----|
| Client | `16-调控系统/core/qwen_client.py`（`chat_completion`） |
| Key 来源 | `6-TRADING/scripts/.env` 的 `QWEN_API_KEY`（`sk-sp-` 为 token-plan 计划密钥） |
| Base URL | `QWEN_BASE_URL`，token-plan 计划指向 `https://token-plan.<region>.maas.aliyuncs.com/compatible-mode/v1` |
| 模型 | `QWEN_MODEL`，默认 `qwen3.8-max` |
| 端点区分 | `sk-sp-` 只能走 token-plan 端点；`sk-` 标准密钥走 `https://dashscope.aliyuncs.com/compatible-mode/v1`，两者不可混用 |

### 降级通道：网页版千问 + bsk

仅在用户确认后启用（慢、易断连，但有独立额度）。

```bash
bsk daemon start
bsk session open "https://www.qianwen.com"
bsk snapshot -i
# contenteditable 必须用 evaluate + execCommand，bsk fill 会返回 rc=3
bsk evaluate "document.querySelector('[contenteditable],textarea').focus();
              document.execCommand('insertText', false, '<prompt>');
              document.querySelector('[contenteditable],textarea')
                .dispatchEvent(new InputEvent('input', {bubbles: true}));"
bsk click @e<send_ref>
bsk evaluate "return document.body.innerText.slice(-8000);"
```

| 坑 | 现象 | 解决 |
|----|------|------|
| contenteditable 不响应 fill | `bsk fill` rc=3 | `evaluate` + `execCommand('insertText')` + dispatch `InputEvent` |
| 长回复截断 | `evaluate` 返回不完整 | `body.innerText.slice(oldLen)` 分段取 |
| session 被清理 | `idle_secs=65` | 重建 session |
| 取到用户消息 | 选择器命中输入框 | 用 `[class*=assistant]`/`[class*=reply]` 过滤 |

### 通道状态（2026-11-18 实测）

- **主通道可用**：`QWEN_API_KEY`（`sk-sp-`，token-plan `cn-beijing`）+ `qwen3.8-max`，预检 `ok=True`
- 密钥位置：本地 `6-TRADING/scripts/.env`、`experiments/ab-trading/config/.env`；云端 `/home/luke/dreambuddy/6-TRADING/scripts/.env`（2026-11-18 新建，`chmod 600`，属主 `luke`）
- **云端出网限制（2026-11-18 实测）**：云端主机 DNS 正常（cn-beijing → IPv6 + `39.106.104.16`），但到 `token-plan.cn-beijing` / `cn-hangzhou` 的 443 全部超时；同机访问 `baidu.com`(200)、`api.deepseek.com`(401) 正常；`ap-southeast-1` 端点 TCP 可达但密钥报 `InvalidApiKey`（该密钥仅限 cn-beijing）
- 结论：**云端无法直连千问主通道**，需要出网白名单/代理才能云侧调用；执行链在本地不受影响
- 端点纪律：`sk-sp-` 只能走 token-plan 端点；标准 `sk-` 走 `dashscope.aliyuncs.com`；混用必报 `invalid_api_key`
- 历史：旧 `sk-sp-` 密钥全模型 `AccessDenied.Unpurchased`，已替换为当前密钥

---

## 四、输入输出契约

| 阶段 | 输入 | 输出 | 落盘位置 |
|------|------|------|---------|
| 步骤 1 | 用户需求 | task.md | `<run_id>/task.md` |
| 步骤 2 | task.md + 仓库片段 | prompt.md | `<run_id>/prompt.md` |
| 步骤 3 | prompt.md | qwen_output.md | `<run_id>/qwen_output.md` |
| 步骤 4 | qwen_output.md + 仓库 | review.md | `<run_id>/review.md` |
| 步骤 5 | review.md 通过 | 已应用改动 + 测试结果 + 认知记录 | 仓库 + 认知系统 |

---

## 五、硬约束（不可违反）

1. 千问产出**永不直接落盘**：必须先评审、再应用、再测试
2. 评审必须引用证据（行号/日志），不得只给结论
3. 返工 ≤ 2 轮；仍不达标则重做任务包，不得无限循环
4. 上下文脱敏：密钥、`.env` 值、个人隐私不得进入 prompt
5. 一票否决项不参与评分讨论，直接退回
6. 涉及实盘交易/风控的产出，必须用户确认后才能应用

---

## 六、hermes 反思决策树

```
本次是否值得形成/衍生 SKILL？
├── 是（任一）：复用 ≥2 次 / 编排 ≥3 步 / 含自动化调用 / 用户明确要求
│   → skill-creator 创建，record tags 含「SKILL,hermes反思」
└── 否（全部）：一次性 / 无自动化 / 无复用价值
    → 仅 record
```

延伸建议（用户原话）：调研/开发/bug 修复/工程管理四域均应形成协作 SKILL。

| 域 | 建议 SKILL | 触发词 |
|----|-----------|--------|
| 调研 | `dream-research-workflow` | 深度调研、市场调研、技术调研 |
| 开发 | `dream-tdd-dev-workflow` | TDD 开发、红-绿-重构 |
| bug 修复 | `dream-bugfix-workflow` | bug 修复、根因分析 |
| 工程管理 | `dream-eng-mgmt-workflow` | 工程管理、排期、里程碑 |

---

## 七、认知闭环

任务开始前（硬约束）：

```
recall(context="千问执行协作 <本次目标关键词>", top_k=5, min_quality="C")
```

任务完成后：`record`（模板见步骤 5），已验证记忆则 `verify(memory_id=..., success=true)`。

---

## 八、相关 SKILL

| 类型 | 名称 | 用途 |
|------|------|------|
| 通道 | `16-调控系统/core/qwen_client.py` | 千问 OpenAI 兼容客户端 |
| 通道 | `bsk`（腾讯 BrowserSkill） | 网页版千问降级通道 |
| 上游 | `dream-bailian-integration` | 百炼平台配置与客户端参考 |
| 下游 | `tee-red-green-progress` | 落地阶段 TDD 循环 |
| 下游 | `dream-acceptance-verify` | 落地后的证据验收门禁 |
| 元 | `skill-creator` | hermes 反思后创建新 SKILL |
| 认知 | `recall`/`record`/`verify` | 认知闭环 |

---

## 九、版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-09-21 | 初始版本：千问调研 + Trae 评估，5 步 + bsk 模板 + hermes 反思 |
| 2.0.0 | 2026-11-18 | 角色互换：千问执行产出，Trae 只做任务包/评审/落地/验证；主通道改百炼 API，bsk 降为备用；新增评审一票否决、返工上限、上下文脱敏、通道状态记录 |
| 3.0.0 | 2026-11-18 | **弃用**：取消角色分工，默认仅用 DeepSeek；云端不使用千问；清空触发词，保留百炼/bsk 经验存档 |
