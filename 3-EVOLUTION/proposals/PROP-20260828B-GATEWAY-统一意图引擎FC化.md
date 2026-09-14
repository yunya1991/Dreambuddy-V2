# PROP-20260828B — Gateway 统一意图引擎（方案 A+：FC 化 + Hermes 增强）

> D4 Spec | 2026-08-28 | D系列调研「Function Calling 集成」最终产出
> 前置：D1 调查（三链考古）→ D2 三问（双轨根因）→ D3 三景（方案 A 推演，风险:中，回滚:强）→ Hermes 实现考古
> 调研地图：`~/.hermes/skills/d-methodology/references/gateway-function-calling-map.md`

---

## 第一段：背景与目标

### 问题（一句话）
Gateway 意图识别双轨并行且脆弱：/api/chat 主链路用正则抠 JSON（15 意图），/api/orchestrate 用 function calling（5 意图），两套枚举不互通；DreamOS tools 管道零消费者；UI 硬编码 `symbol:'BTC'`。

### 为什么要做
1. **质量**：B 链正则解析是"抽奖"——模型输出稍偏 → 解析失败 → 降级规则匹配 = 意图漂移（A 链注释原话要消灭的模式）
2. **成本**：UI "orchestrate 优先 → chat 兜底"，失败时一条消息烧两条链 token；意图逻辑两处维护
3. **架构**：用户架构原则"LLM 只驱动编排"缺 FC 抓手；意图层无 SSoT，每次新入口接入都要重写一遍

### 成功标准（可量化）
| # | 标准 | 验证方式 |
|:---:|---|---|
| S1 | 黄金测试集通过率 ≥95%（20+ 真实话语） | `tests/intent-golden.test.ts` |
| S2 | 意图解析异常数 = 0（FC 结构化输出 + 修复级联兜底） | 日志统计 |
| S3 | /api/chat 与 /api/orchestrate 共享同一 intent-schema（单一 import 源） | grep 验证 |
| S4 | 角色门禁回归 100% 通过（execute_trade/scenario_sim FREE 拦截） | 门禁用例集 |
| S5 | `/command` 类指令零 LLM token 消耗 | 快路径计数日志 |
| S6 | FC 识别延迟 P95 ≤ 旧 JSON 版 ×1.3（保留 15s 超时预算） | 离线基准 |

### 不做范围（防 scope creep）
- ❌ 方案 B（DreamOS nodes.yaml → tool schema 桥接）——独立提案
- ❌ DreamOS Python 侧 `llm_client.py` 不动
- ❌ UI "orchestrate 优先 → chat 兜底"编排策略不动（独立话题）
- ❌ intent-memory 内部 Bayesian 算法不重构，只做字段重接
- ❌ A 系列交易 cron 链不碰

---

## 第二段：6 要素方案描述

### 架构（四层，对齐 Hermes 参考实现）

```
用户消息
  │
  ├─ L0 群聊/平台门控（已有，不动）
  │
  ├─ L1 确定性命令快路径【新增】
  │     text.startsWith('/') → command-fastpath → cmdRoute 直达
  │     硬化规则（抄 Hermes）：剥 @后缀 / 拒绝文件路径 / 零 LLM 成本
  │
  ├─ L2 统一意图引擎【重构核心】
  │     recognizeIntentFC() via llm-bridge functions（recognize_intent_full，15 枚举）
  │     ├─ FC 成功 → 结构化意图（tool_calls 优先）
  │     ├─ FC 畸形 → 修复级联【新增，抄 Hermes _repair_tool_call_arguments】
  │     │     strict=False 解析 → 去尾逗号 → 补未闭合括号 → 删多余闭合 → {} 兜底
  │     └─ 超时/失败 → 规则匹配 → 默认兜底（保留三层降级；enable_thinking:false 缓解必须保留）
  │
  └─ L3 路由与门禁
        smart-router：角色门禁收敛为策略表（对齐 Hermes slash_access 双轴模型）
        ├─ need_clarification → 结构化反问（≤4 选项 + "其他"）【新增，抄 Hermes clarify】
        └─ execute_trade → 确定性确认门禁（FC 参数解析失败 ≠ 触发交易）【新增，高危不走概率链路】
```

### 关键实现路径（模块级）

| # | 文件 | 改动 |
|:---:|---|---|
| 1 | `src/lib/intent/intent-schema.ts`【新建】 | SSoT：15 意图正典 + 环归属（执行/情报/治理/通用）+ 角色门禁标记 + A 链 5 类型别名映射表 |
| 2 | `src/lib/intent/command-fastpath.ts`【新建】 | 确定性命令解析，`/command` 零 LLM 直达 cmdRoute |
| 3 | `src/lib/intent/intent-args-repair.ts`【新建】 | 修复级联（移植 Hermes 算法到 TS） |
| 4 | `src/lib/intent/fallback-engine.ts`【重构】 | `recognizeWithLLM` → llm-bridge functions 调用；正则解析路径删除，修复级联接位 |
| 5 | `src/lib/intent/intent-memory.ts`【重接】 | recordRecognition/recordFeedback 字段映射到统一 schema（旧枚举→新枚举迁移函数） |
| 6 | `src/lib/orchestration/llm-planner.ts`【收敛】 | recognize_intent 切统一 schema（5 类型做别名层） |
| 7 | `src/app/v2/page.tsx` + `dashboard/page.tsx`【修复】 | 硬编码 `symbol:'BTC'` → 传 UI 实际选中 symbol |
| 8 | `tests/intent-golden.test.ts`【新建】 | 黄金集：20+ 真实话语（取自 intent-memory 历史）→ 期望意图；smart-router 分支全覆盖 |

### 依赖
- `llm-bridge.ts` tools 能力已存在且 A 链生产验证（qwen3.8-max compatible-mode）
- intent-memory 历史识别记录（黄金集语料来源）
- 无新外部依赖、无 DB 变更、无 DreamOS 侧改动

### 风险项
| 风险 | 等级 | 缓解 |
|---|:---:|---|
| intent-memory 重接引入历史纠正失效 | 中高 | 迁移函数单测 + 双写过渡期 |
| smart-router 角色门禁漏测 → 越权/误拦 | 中高 | 门禁用例集 P0 验收，逐一覆盖 |
| FC 延迟超 15s 预算（B 链有 P0 前科） | 中 | enable_thinking:false 保留；S6 基准先行 |
| 历史反馈数据旧枚举映射边缘 | 中 | 映射表 + 未知枚举回退 default |

### 里程碑
- **M1**：intent-schema + 黄金测试集（可独立验收）
- **M2**：命令快路径 + B 链 FC 迁移 + 修复级联（feature flag 后）
- **M3**：memory 重接 + A 链统一 + symbol 修复
- **M4**：全量回归 + flag 切流 + 旧路径回收

---

## 第三段：多方案对比

| 维度 | **A+（主推）** | B（编排抓手） | C（最小修复） |
|---|---|---|---|
| 内容 | 统一意图引擎 + Hermes 四项增强 | nodes.yaml→tool schema，LLM 经 FC 调 node | 仅 B 链换 FC + 修 symbol |
| 收益 | 消灭双轨+脆弱解析；高危门禁强化；歧义体验升级 | "LLM 驱动编排"闭环 | 快速止血 |
| 风险 | 中（回滚强：flag 0 秒切回） | 中高（安全边界设计） | 低 |
| 工作量 | ⭐⭐⭐（~4 阶段） | ⭐⭐⭐⭐ | ⭐ |
| 根因解决 | ✅ | ✅（不同根因） | ❌ 双轨仍在 |
| 定位 | 本提案 | 后续独立提案（依赖 A+ 的 schema） | 不采用（已被 A+ 覆盖） |

---

## 第四段：实现路径与验收

### Phase 0：离线验证（零生产改动，先跑 D3 可验证假设）
- 步骤：从 intent-memory 历史取 20 条真实话语 → 离线跑 FC 版 vs JSON 版识别对比
- 验收：FC 版准确率 ≥ 旧版且零解析异常 → 才动生产代码

### Phase 1：Schema + 黄金集（M1）
- 步骤：建 `intent-schema.ts`（15 正典 + 别名映射 + 环归属）；写黄金测试集
- 验收：schema 编译通过；黄金集可运行（此时预期部分失败，为基线）

### Phase 2：快路径 + FC 迁移（M2）
- 步骤：command-fastpath 上线；recognizeWithLLM 迁 llm-bridge FC + 修复级联；`INTENT_ENGINE=fc|legacy` feature flag 双轨
- 验收：S2/S5/S6 达标；flag=legacy 行为与改动前完全一致

### Phase 3：memory 重接 + A 链统一（M3）
- 步骤：intent-memory 字段映射（双写过渡）；llm-planner 切统一 schema；symbol 动态化
- 验收：历史纠正回放有效；A/B 链 import 同一 schema（S3）

### Phase 4：回归 + 切流（M4）
- 步骤：黄金集全量 + 角色门禁用例集 → flag 切 fc → 观察一周 → 删 legacy 路径
- 验收：S1≥95%、S4 100%、观察期无意图相关故障

### 验收清单
| 等级 | 验收项 | 验证方式 |
|:---:|---|---|
| P0 | 黄金集 ≥95% | intent-golden.test.ts |
| P0 | 角色门禁零漏放（FREE 越权 = 阻塞级） | 门禁用例集 |
| P0 | execute_trade 必须确定性确认；解析失败不触发交易 | 用例 + 代码审查 |
| P0 | 解析异常 = 0（修复级联兜底生效） | 日志 |
| P1 | 延迟 P95 ≤ 旧版 ×1.3 | 基准脚本 |
| P1 | intent-memory 反馈回放有效 | 回放用例 |
| P2 | symbol 动态传递生效 | UI 手测 |
| P2 | function_calling_guide.md 补齐 | 文档 |
| P3 | 代码风格 / 注释 | lint |

### 回滚预案
| 阶段 | 回滚方式 | 影响 |
|---|---|---|
| Phase 2-3 | `INTENT_ENGINE=legacy` flag 切换 | 0 秒，行为回到旧链路 |
| Phase 4 切流后 | git revert + flag 恢复 | <5 分钟 |
| memory 双写期 | 旧字段仍在写，直接切回 | 无数据丢失 |

---

## 审批状态
- [ ] 飞书审批（系统升级类：代码改动，须过审批门禁后进 Z/E 链）
- 备注：本 Spec 为 D4 规划产出；实施需经 Z1 代码扫描细化 + 飞书批准后进入 E 链
