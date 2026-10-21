# SPEC-v1.5 实体解析与槽位填充根本性修复

> **版本**: v1.1（已按评审意见修订：M1/M2/m1/m2/m3）
> **日期**: 2026-10-17
> **状态**: 评审通过（有条件通过→条件已满足，可进入实施）
> **背景**: 前端『查询以太坊价格』返回比特币价格（badcase 2026-10-17 01:20）
> **关联**: SPEC-v1.4-S-layer-design.md, SPEC-v0.7-data-query-intent.md, 3.1-FRONTEND/scripts/data_query_executor.py

---

## 1. 问题定义

### 1.1 现象
用户在前端输入『查询以太坊价格』，系统返回 BTC（比特币）实时价格。

### 1.2 根因
`data_query_executor.py` 的币种解析逻辑：

```python
m = re.search(r"([A-Z]{2,10})", message.upper())
symbol = m.group(1) if m else "BTC"   # ← 中文别名无法命中，静默回退 BTC
```

两个系统性缺陷：
1. **实体链接失败**：只匹配大写字母代号（ETH/BTC），中文别名（以太坊/以太/以太幣）无法识别
2. **静默降级（Silent Fallback）**：解析失败后不告知用户，直接采用默认值 BTC，用户无从察觉

受影响环节：`exec_price_query`、`exec_technical_analysis`、`exec_fundamental_valuation`、`exec_data_query`（多维交汇）——全部共用同一解析模式。

### 1.3 问题定性
这不是单点 bug，而是任务型对话系统（Task-Oriented Dialogue）中**实体链接 + 槽位填充**层的系统性缺失。

## 2. 设计目标

| 编号 | 目标 | 验收口径 |
|------|------|----------|
| G1 | 中文别名正确解析 | 『查询以太坊价格』返回 ETH 价格 |
| G2 | 消除静默降级 | 币种缺失时追问，降级时显式告知 |
| G3 | 单一数据源 | 别名表全环节共用（SSoT），无内嵌正则 |
| G4 | badcase 回流训练 | 负样本进入 S 层训练闭环 |
| G5 | 回归防护 | 别名/错别字/混合表达评测集守护 |

## 3. 分层方案

### 3.1 P0 — 实体别名表 + 归一化（基础层，立即实施）

**单一别名表** `3.1-FRONTEND/scripts/entity_aliases.json`，**初始版本必须覆盖交易池全部标的**（评审 M1，以当前交易池 19 标的为基准）：

```json
{
  "ETH": ["以太坊", "以太", "以太幣", "ethereum", "eth"],
  "BTC": ["比特币", "比特幣", "bitcoin", "btc"],
  "SOL": ["索拉纳", "solana", "sol"],
  "XRP": ["瑞波", "ripple", "xrp"],
  "DOGE": ["狗狗币", "dogecoin", "doge"],
  "UNI": ["uniswap", "uni"],
  "LINK": ["链环", "chainlink", "link"],
  "BNB": ["币安币", "bnb"],
  "OKB": ["okb"],
  "HYPE": ["hype"],
  "PUMP": ["pump"],
  "XAU": ["黄金", "金", "gold", "xau"],
  "XAG": ["白银", "银", "silver", "xag"],
  "GOOGL": ["谷歌", "google", "googl"],
  "NVDA": ["英伟达", "nvidia", "nvda"],
  "AMZN": ["亚马逊", "amazon", "amzn"],
  "MU": ["美光", "micron", "mu"],
  "SKHYNIX": ["sk海力士", "海力士", "skhynix"],
  "SNDK": ["闪迪", "sandisk", "sndk"],
  "SPCX": ["spacex", "spcx"]
}
```

- 解析顺序：中文别名（最长匹配优先，如『以太坊』优先于『以太』）→ 字母代号 → 失败
- **同步策略（评审 M1）**：别名表以交易池为基准源，sync_aliases.py 定期比对；**新标的入池而别名表未覆盖时输出告警日志并通知管理通道，禁止静默缺失**
- 所有执行器统一调用 `_resolve_symbol(message)`，删除各处内嵌正则

### 3.2 P0 — 槽位显式化 + 澄清追问（关键层，立即实施）

- 币种作为显式槽位（slot），解析失败时**返回追问**而非默认值：
  `{"success": true, "need_clarification": true, "answer": "请问您想查询哪个币种？"}`
- **降级契约（评审 M2，FAIL-OPEN）**：`need_clarification` 为可选字段——前端 ChatPanel 未适配时按普通 answer 展示追问文案（功能不损失，仅样式降级），不阻塞 P0 上线；L2（SSE）路径透传该字段，未透传时同样按 answer 降级
- **原则：不确定时澄清，而非猜测**

### 3.3 P1 — 降级可观测（进阶层）

- 任何降级路径在响应中携带 `degraded: true` 与原因，answer 前缀显式提示
- 降级事件写入训练日志，纳入 DataQueryIntent 采集器观测范围

### 3.4 P1 — badcase 回流训练（系统特有优势）

- 本次 badcase（以太坊→BTC）构造为负样本：`{"message": "查询以太坊价格", "expected_slot": "ETH", "bad_output": "BTC"}`
- 喂入 S 层 DataQueryIntent 训练流，让模型逐步学会直接从中文消息提取币种槽位
- 前端记录『查询与返回不符』的用户反馈通道 → 自动进入训练样本

### 3.5 P2 — 评测集回归防护（验收层）

- 建立 `tests/test_entity_resolution.py` 评测集：中文别名、中英混合（查一下eth）、大小写混合、美股/贵金属中文名（黄金/英伟达/谷歌）
- **模糊匹配边界（评审 m1）**：P0/P1 不做错别字模糊匹配（避免误命中）；P2 若引入，限定编辑距离 ≤1、仅在无任何精确命中时触发、响应携带 `fuzzy_matched: true` 降级标记
- 每次别名表/规则/模型变更后必须通过评测集

## 4. 非目标

- 不改动 L1/L2 路由层结构（本 SPEC 只修实体解析层）
- 不引入外部 NER 模型服务（保持本地轻量，模型能力由 S 层训练逐步提供）

## 5. 验收标准

1. `python3 data_query_executor.py '{"intent":"price_query","message":"查询以太坊价格"}'` 返回 ETH 实时价格
2. `查询狗狗币价格` 返回 DOGE 价格；`查询黄金价格` 返回 XAU；`查询英伟达价格` 返回 NVDA（评审 M1 全标的覆盖验证）
3. `查询价格`（无币种）返回追问而非 BTC
4. 技术面/基本面/多维交汇环节同样通过别名解析
5. ChatPanel 与 L2（SSE）路径对 `need_clarification` 的透传验证：适配时展示追问样式，未适配时按 answer 降级展示（评审 M2 契约验证）
6. 评测集全部通过；现有 34 模块测试零回归

## 6. 实施路径

| 阶段 | 内容 | 工作量 |
|------|------|--------|
| P0 | 别名表 + 澄清追问 + 执行器统一改造 | 0.5 天 |
| P1 | 降级可观测 + badcase 回流 | 0.5 天 |
| P2 | 评测集 + 别名同步脚本 | 0.5 天 |

## 7. 风险与对策

- **别名表覆盖不全** → 同步脚本 + 新标的入池告警 + 用户反馈回流补充
- **追问打断体验** → 仅在完全无法解析时追问；有上下文时优先从会话历史提取槽位（P2 可选；**实施前须先核查 session-store → executor 的消息传递链路是否已打通**，评审 m3，避免设计悬空）
- **训练样本偏差** → badcase 样本与正样本按 1:3 配比（**初始经验值**，评审 m2；上线后观测 S 层意图/槽位准确率，按实际效果调整配比）
