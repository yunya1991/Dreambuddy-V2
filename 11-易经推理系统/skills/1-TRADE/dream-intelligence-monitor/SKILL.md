---
name: dream-intelligence-monitor
description: |
  📡 情报监控 — 永不间断的市场雷达
  每小时运行，持续监控市场状态变化、异常信号、战略环境变更，
  当检测到重大变化时，触发相应的响应流程。
  ⚠️ v4.8新增: **Level 1.5 A2增量更新脚本** (2026-04-29修复)
  ⚠️ v4.9新增: **A6→做梦部自动复制脚本** (2026-04-29修复)
  ⚠️ v4.9新增: **Level 1.5 A2增量更新脚本** (2026-04-29修复)
  触发词：情报监控、市场监控、实时监控、异常告警、战略变更、P0告警、重大变化、A4上报、A4触发A6、宏观资产、共振信号、风险库检测、Exit Skill联动
license: Internal
version: 4.9.0
created: 2026-04-20
updated: 2026-04-29
---

# 📡 Dream-Intelligence-Monitor: 情报监控部 (v4.8)

## 【合规要求】⭐ v4.8 新增

### §合规 问题处理流程

> ⚠️ **合规约束**: 遇到任何问题必须按以下顺序处理：

```
遇到问题
    ↓
Step 1️⃣ 查FAQ
  → WORKSPACE/.workbuddy/faq/OKX_FAQ.md（OKX相关）
  → WORKSPACE/.workbuddy/faq/技术_FAQ.md（技术相关）
  → WORKSPACE/.workbuddy/faq/运营_FAQ.md（运营相关）
    ↓ 有解 → 执行 ✓
    ↓ 无解 → Step 2

Step 2️⃣ 查治理文档
  → ~/.workbuddy/skills/dream-governance-manager/governance_docs/
    ↓ 有解 → 执行 + 补充FAQ ✓
    ↓ 无解 → Step 3

Step 3️⃣ 联网搜索
  → 使用 tavily/agent-reach 搜索
    ↓ 有解 → 执行 + 归档经验 ✓
    ↓ 无解 → Step 4

Step 4️⃣ 自主分析
    ↓ 有解 → 执行 + 输出报告 + 归档 ✓
    ↓ 无解 → 升级处理
```

### §合规 常见问题索引

| 问题类型 | FAQ位置 | 备注 |
|:---|:---|:---|
| OKX API错误 | `faq/OKX_FAQ.md` | CLI命令/API签名 |
| 账户查询问题 | `faq/OKX_FAQ.md` | 权限/配置文件 |
| 技术实现问题 | `faq/技术_FAQ.md` | 脚本/工具问题 |
| 流程协作问题 | `faq/运营_FAQ.md` | 制度/规范问题 |
| 合规判定问题 | `dream-governance-manager/` | 治理文档 |

### §合规 违规处理

| 违规类型 | 判定条件 | 处罚 |
|:---|:---|:---|
| 跳步违规 | 未查FAQ直接联网/分析 | 记过一次 |
| FAQ缺失 | 问题存在但未查阅 | 警告 |
| 归档缺失 | 问题解决但未归档 | 记录 |

---

## 核心职能

> "知己知彼，百战不殆" — 持续监控战场态势

---

## 依赖 SKILL

- **dream-intelligence-analysis**: 情报分析核心理论与工具箱（v1.0.0）
  - **调用时机**：每次情报分析前
  - **调用方式**：`use_skill("dream-intelligence-analysis")`
  - **核心工具**：
    - 关键假设检查（必须用）
    - 竞争性假设分析 ACH（必须用）
    - 红队分析（必须用）
    - 魔鬼代言人（必须用）
    - 指标法（必须用）
    - 高影响/低概率分析法（必须用）
    - 结构化头脑风暴（推荐）
    - 情景分析法（推荐）
    - 决策树法（推荐）
    - 事前分析法（推荐）
  - **蒸馏来源**：
    - 《情报分析心理学》（Richards J. Heuer Jr.）
    - 《情报分析：结构化分析方法》（Heuer & Pherson）
  - **路径**：`~/.workbuddy/skills/dream-intelligence-analysis/SKILL.md`

- **dream-task-creator**: 任务创建专家（v2.0）
  - **调用时机**：需要创建临时任务时（如定时监控、自动化任务等）
  - **调用方式**：`use_skill("dream-task-creator")`
  - **核心功能**：
    - 快速创建各类自动化任务（定时/一次性）
    - 提供完整的工作流：创建 → 验证 → 压力测试
    - 支持 RRule 模板库（每小时/每天/每周等）
  - **关键发现**：`automation_update` 工具的 `suggested create` 模式不工作，必须使用直接写入 TOML 文件的方式
  - **创建步骤**：
    ```bash
    # 1. 创建任务目录
    mkdir -p ~/.workbuddy/automations/<task-name>
    
    # 2. 写入 automation.toml 文件
    cat > ~/.workbuddy/automations/<task-name>/automation.toml << 'EOF'
    [automation]
    name = "<Task-Name>"
    status = "ACTIVE"
    rrule = "FREQ=DAILY;BYHOUR=9;BYMINUTE=0"
    cwds = ["/Users/zhangjiangtao/WorkBuddy/20260415144304"]
    
    [prompt]
    text = """任务执行的具体指令..."""
    EOF
    ```
  - **路径**：`~/.workbuddy/skills/dream-task-creator/SKILL.md`

---

## 监控指标体系

- **monitoring_metrics.md**: A6 实战监控指标体系（v1.0.0）
  - **路径**：`~/.workbuddy/skills/dream-intelligence-monitor/monitoring_metrics.md`
  - **涵盖维度**：
    - **OKX 官方监控体系**：REST API + WebSocket + CLI命令
    - **链上数据监控体系**：Glassnode + CoinGlass + CryptoQuant
    - **宏观金融监控体系**：美联储政策 + 股票市场 + 黄金与大宗商品
    - **地缘政治监控体系**：中东局势 + 俄乌战争 + 中美关系
    - **技术发展监控体系**：Bitcoin核心技术 + Ethereum技术发展 + 机构入场
    - **加密政策监控体系**：美国政策 + 全球政策
  - **层级分类**：
    - **战略层**（周-月）：美联储政策、地缘战争、技术发展、加密政策
    - **战术层**（日-周）：链上数据、宏观金融、ETF资金流
    - **技术层**（小时-日）：OKX API、订单簿、爆仓数据
  - **监控频率**：
    - 实时（WebSocket推送）
    - 每5分钟（OKX账户/持仓/算法订单）
    - 每小时（OKX未平仓合约/多空比/链上流入流出）
    - 每天（宏观金融/链上数据/ETF资金流）
    - 每周（战略层指标）
  - **关键阈值**：每个指标都提供了关键阈值（如MVRV Ratio > 3.5 = 严重高估）
  - **异常检测算法**：价格波动异常、成交量异常、巨鲸交易异常、资金费率异常

---

### ⚠️ 自主判断规范（v4.1 新增 · 2026-04-25）

> **做梦部批判核心**：触发因素是做梦部的道德审判（"有操作空间但不用更不可原谅"）而非系统自主判断。
> **本SKILL必须实现**：**内部自主判断和驱动**，不依赖外部道德审判。

```
╔═══════════════════════════════════════════════════════════════════════╗
║          A6 自主判断规范（摆脱外部道德审判）                               ║
╠═══════════════════════════════════════════════════════════════════════╣
║                                                                          ║
║  ✅ 必须自主判断:                                                        ║
║  ├── 三屏信号分析（方向/斜率/加速度）                                    ║
║  ├── 基本面验证（A1-A3结论是否矛盾）                                    ║
║  ├── 确定性评估（WEAK/MODERATE/STRONG/VERY_STRONG）                    ║
║  ├── 触发类型决定（A4试探/A5执行/A1-A3重启）                           ║
║  └── 执行触发（use_skill调用对应链路）                                  ║
║                                                                          ║
║  ❌ 禁止依赖:                                                            ║
║  ├── 做梦部"道德审判"（"有操作空间但不用更不可原谅"）                   ║
║  ├── 用户外部指令（除非明确授权）                                        ║
║  ├── 其他Agent的"建议"（除非是顾问评审）                                ║
║  └── 历史决策的"惯性"（必须每轮重新判断）                              ║
║                                                                          ║
║  🔄 判断流程:                                                           ║
║  1. 读取三屏信号 → 自主分析 → 得出技术判断                             ║
║  2. 读取A1-A3结论 → 自主验证 → 是否矛盾                               ║
║  3. 评估确定性 → 自主决定 → 触发类型                                   ║
║  4. 执行触发 → 自主调用 → use_skill对应链路                            ║
║  5. 写入账本 → 记录判断依据 → 供后续审计                              ║
║                                                                          ║
╚═══════════════════════════════════════════════════════════════════════╝
```

> **宪法级约束**: 本节为A6的最高执行准则，优于任何旧版描述。A6必须自主判断，否则视为失职。

### ⚠️ A6双轨触发机制（v4.0 新增 · 2026-04-25）

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    A6 双轨触发机制（v4.0 确立）                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ════════════ A6是A1-A6系统的"决策中枢" ════════════                   │
│                                                                         │
│  【来源1: A6自主检测触发】                                               │
│  ├── 触发: 每小时自动运行，检测市场异常                                 │
│  ├── 类型: 技术指标突变/资金费率极端/宏观事件                            │
│  ├── A6自主决定链路深度                                                 │
│  └── 链路: 见下方"分级响应规则"                                        │
│                          ↓                                              │
│  【来源2: A4主动上报触发】⚠️ 新增                                       │
│  ├── 触发: A4在战术验证中发现T1-T5任一条件                           │
│  ├── 类型: 战略指令矛盾/Regime偏差/多次实践失败                         │
│  ├── A4上报 → A6接收 → 查询记忆账本 → A6判定链路深度                 │
│  └── A6内部use_skill依次调用对应链路                                   │
│                          ↓                                              │
│  ════════════ 两者区别 ════════════                                      │
│                                                                         │
│  ┌────────────────────────┐  ┌────────────────────────┐                │
│  │     A6自主检测         │  │     A4主动上报         │                │
│  ├────────────────────────┤  ├────────────────────────┤                │
│  │ 触发方: A6自身        │  │ 触发方: A4            │                │
│  │ 检测对象: 市场行情     │  │ 检测对象: A3指令质量  │                │
│  │ 矛盾: 市场vs当前指令   │  │ 矛盾: A3判断vs实时   │                │
│  │ 链路: A6自定          │  │ 链路: A6查账本自定    │                │
│  └────────────────────────┘  └────────────────────────┘                │
│                                                                         │
│  共同点:                                                                │
│  ├── 链路深度都由A6最终决定                                            │
│  ├── A6内部use_skill依次调用A1→A2→A3→A4→A5                        │
│  └── 不使用废弃的p0-alert-responder                                  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

## OKX CLI 查询命令 (v4.1 新增)

> **⚠️ 宪法§11 FAQ自愈**: 遇到OKX问题必须先查FAQ (`/.workbuddy/faq/OKX_FAQ.md`)，找到匹配项直接用已有方案。

### 核心查询命令（A6 监控专用）

| 命令 | 用途 | 示例 |
|:---|:---|:---|
| `okx account balance` | 查询账户余额 | `okx account balance --profile dreamdemo` |
| `okx swap positions` | 查询持仓 | `okx swap positions BTC-USDT-SWAP --profile dreamdemo` |
| `okx swap algo orders` | 查询算法订单 | `okx swap algo orders --instId BTC-USDT-SWAP --profile dreamdemo` |
| `okx market ticker` | 查询当前价格 | `okx market ticker BTC-USDT-SWAP --profile dreamdemo` |
| `okx account config` | 查询账户配置 | `okx account config --profile dreamdemo` |

### 宏观资产查询命令（v4.2 新增）

> **用途**: 监控宏观资产价格变化，识别跨资产共振信号

| 资产 | 查询命令 | 说明 |
|:---|:---|:---|
| **黄金** | `okx market ticker XAU-USDT-SWAP` | 黄金永续合约价格 |
| **特斯拉** | `okx market ticker TSLA-USDT-SWAP` | 特斯拉股票永续 |
| **Coinbase** | `okx market ticker COIN-USDT-SWAP` | Coinbase股票永续 |
| **原油** | `okx market ticker CL-USDT-SWAP` | 原油永续合约价格 |
| **铜** | `okx market ticker XCU-USDT-SWAP` | 铜永续合约价格 |

**批量查询脚本**（A6 自动监控时使用）:
```bash
# 批量查询宏观资产价格
for inst in "XAU-USDT-SWAP" "TSLA-USDT-SWAP" "COIN-USDT-SWAP" "CL-USDT-SWAP" "XCU-USDT-SWAP"; do
  okx market ticker $inst --profile dreamdemo 2>/dev/null | grep -E "last|change"
done
```

---

### 查询命令正确格式

#### 查询账户余额

```bash
# ✅ 查询 DEMO 模拟盘账户余额
okx account balance --profile dreamdemo

# 输出示例:
# Environment: demo (simulated trading)
# totalEq  availableBal  unrealizedPnl
# 5884.52   5800.12      84.40
```

#### 查询持仓

```bash
# ✅ 查询特定合约的持仓
okx swap positions BTC-USDT-SWAP --profile dreamdemo

# 输出示例:
# instId         posSide  sz     avgPx     upl       lever
# BTC-USDT-SWAP long     0.01   77312.2   -5.60    2
```

#### 查询算法订单（TP/SL/OCO/追踪止损）

```bash
# ✅ 查询当前算法订单
okx swap algo orders --instId BTC-USDT-SWAP --profile dreamdemo

# 输出示例:
# algoId               instId         type     side  sz    tpTrigger  slTrigger  state
# 3510986889505439744  BTC-USDT-SWAP  oco      sell  0.01  78500      76000      live
# 3510989466922024960  BTC-USDT-SWAP  move_order_stop  buy   0.01                        live
```

**算法订单类型说明**：
- `conditional`: 普通条件单（TP 或 SL）
- `oco`: OCO 订单（同时包含 TP 和 SL）
- `move_order_stop`: 追踪止损订单

---

### 常见错误与解决方案

| 错误 | 原因 | 解决方案 |
|:---|:---|:---|
| `okx-trade: command not found` | 命令名错误 | 使用 `okx` 而非 `okx-trade` |
| `HTTP 403: signature verification failed` | API 签名错误 | 检查 API Key/Secret/Passphrase 是否正确 |
| `sCode 50113: Invalid sign` | 签名格式错误 | 使用 `okx` CLI 而非 Python requests |
| `No algo orders` | 算法订单不存在或已取消 | 检查是否成功创建算法订单 |

### ⚠️ OKX API 403错误处理方案（FAQ §FAQ_API_403）

> **宪法§11 FAQ自愈**: 遇到403错误必须先查FAQ，本条目已包含完整解决方案。

#### 问题场景

A6监控时直接用Python urllib/requests调用OKX API返回403：
```python
# ❌ 错误：直接Python调用
import requests
requests.get('https://www.okx.com/api/v5/...')  # HTTP 403
```

#### 根因分析

1. **OKX Cloudflare防护**: OKX使用Cloudflare保护API，Python直接请求被识别为爬虫
2. **签名问题**: Python签名实现与OKX要求可能存在细微差异
3. **User-Agent缺失**: 缺少浏览器User-Agent字段

#### 解决方案（按优先级）

**方案1: OKX CLI（推荐）** ✅
```bash
# 行情数据
okx market ticker BTC-USDT-SWAP

# 账户数据
okx account balance --profile dreamdemo

# 持仓数据
okx swap positions BTC-USDT-SWAP --profile dreamdemo
```

**方案2: Python + User-Agent + OKX官方库** ⚠️
```python
# ✅ 正确：添加浏览器User-Agent
import urllib.request

headers = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json'
}

req = urllib.request.Request(url, headers=headers)
with urllib.request.urlopen(req, timeout=10) as r:
    data = json.loads(r.read())
```

**方案3: OKX官方Python SDK** 📦
```bash
# pip install okx
from okx import MarketData
market = MarketData()
ticker = market.ticker(instId="BTC-USDT-SWAP")
```

#### A6数据采集规范

```bash
# Phase 1数据采集（A6强制执行顺序）

# 1. 行情数据 → OKX CLI ✅
okx market ticker BTC-USDT-SWAP

# 2. 资金费率 → OKX CLI ✅
okx market funding-rate BTC-USDT-SWAP

# 3. 账户余额 → OKX CLI ✅
okx account balance --profile dreamdemo

# 4. 持仓数据 → OKX CLI ✅
okx swap positions --instId BTC-USDT-SWAP --profile dreamdemo

# 5. 算法订单 → OKX CLI ✅
okx swap algo orders --instId BTC-USDT-SWAP --profile dreamdemo

# ⚠️ 禁止：直接Python urllib/requests调用OKX API
# ⚠️ 禁止：自己实现签名逻辑调用REST API
```

#### 403错误降级策略

```
OKX CLI执行顺序:
├── Step 1: okx market ticker (行情) → 必执行
├── Step 2: okx account balance (余额) → 必执行
└── Step 3: okx swap positions (持仓) → 必执行

错误处理:
├── OKX CLI 403 → 降级到 Python + User-Agent
├── Python 403 → 降级到 web_search 行情数据
└── 全部失败 → 标记"数据源不可用"，基于上次数据估算
```

#### 关键教训

> **FAQ经验**: OKX官方CLI是OKX数据查询的最佳工具，优先于任何Python直接调用。
> Python urllib/requests仅用于非OKX数据源（如Trading Economics、FRED等）。

---

### 完整监控流程示例（A6 使用）

```bash
# 1. 查询账户余额
okx account balance --profile dreamdemo

# 2. 查询持仓
okx swap positions BTC-USDT-SWAP --profile dreamdemo

# 3. 查询算法订单
okx swap algo orders --instId BTC-USDT-SWAP --profile dreamdemo

# 4. 查询当前价格
okx market ticker BTC-USDT-SWAP --profile dreamdemo

# 5. 分析数据 → 检测异常 → 触发响应
```

---

### 真实测试验证（2026-04-26）

| 测试场景 | 结果 | 说明 |
|:---|:---:|:---|
| **查询账户余额** | ✅ 通过 | 正确返回 totalEq/availableBal/unrealizedPnl |
| **查询持仓** | ✅ 通过 | 正确返回 posSide/sz/avgPx/upl/lever |
| **查询算法订单** | ✅ 通过 | 正确返回 algoId/type/state |
| **查询当前价格** | ✅ 通过 | 正确返回 last/bid/ask |

**测试环境**: dreamdemo 模拟盘（`--profile dreamdemo`）

---

## ⚠️ 账户监控（v3.2 统一dreamdemo）

> **宪法§11.1 约束**：本节为强制执行项。
> **2026-04-24 更新**：系统开发期不稳定，**统一监控dreamdemo账户**，A5实盘暂停。

### 账户体系

| 维度 | dreamdemo (监控重点) | A5实盘 (暂停) |
|:---|:---|:---|
| **Profile** | `profiles.A5` (demo密钥) | `profiles.A5.live` (禁用) |
| **API Key** | `aa4daa46-...` (模拟盘) | `f9d0221c-...` (实盘) |
| **配置文件** | `~/.okx/config.toml` `[profiles.live]` | `~/.okx/config.toml` `[profiles.A5]` |
| **系统归属** | A4战术验证 + A5裁决 | 暂停监控 |
| **监控权重** | **100%（唯一）** | 0%（禁用） |
| **浮亏告警阈值** | >1% 🟡 / >2% 🔴 | — |
| **查询命令** | `okx account balance --profile A5` | — |

### 查询流程（每次监控必须执行）

```
Step 1: 查询 dreamdemo 账户
├── 方式: OKX CLI
├── 命令: okx account balance --profile A5
├── 命令: okx swap positions --instId BTC-USDT-SWAP --profile A5
└── 注意: profile=A5 实际使用demo密钥（2026-04-24配置）

Step 2: A5实盘状态（暂停监控）
├── 持仓: BTC LONG 6.09张@$78,561.71
├── 命令: okx account balance --profile A5

⚠️ A5实盘恢复流程
├── 删除 [profiles.A5] 下的 demo = true 标记
├── 移除 [profiles.A5.live] 下的 [disabled] 标记
└── 将 [profiles.A5] 的 api_key/secret_key/passphrase 换回实盘密钥
```

### 持仓监控维度（dreamdemo单一）

| 维度 | 指标 | dreamdemo 阈值 | 告警级别 |
|:---|:---|:---|:---|:---|
| **浮亏** | unrealizedPnl / margin | >1% 🟡 / >2% 🔴 | 🟡MEDIUM / 🔴HIGH |
| **方向异常** | 持仓方向与战略矛盾 | 任意 | 🔴HIGH |
| **杠杆超标** | leverage > 战略上限 | >2x | 🔴HIGH |
| **仓位追加** | 持仓数量非预期变化 | 任意变化 | 🟡MEDIUM |
| **余额异常** | 可用余额骤降 | >30% | 🔴HIGH |

---

## 监控维度

| 维度 | 指标 | 阈值 | 告警级别 |
|:---|:---|:---|:---|
| 价格 | 1H涨跌 | ±2% | 🟡MEDIUM |
| 趋势 | EMA20/60关系 | 死叉/金叉 | 🔴HIGH |
| 动量 | RSI极端 | <30 或 >70 | 🟡MEDIUM |
| 波动 | ATR突破 | >20日均值1.5x | 🟡MEDIUM |
| 资金 | Funding极端 | >0.01 | 🟡MEDIUM |
| ⭐ 费率翻转 | Funding变化率 | 日变化>30% | 🔴HIGH |
| ⭐ 费率翻转 | 费率转正 | 负→正 | 🔴HIGH |
| ⭐ 费率翻转 | 费率转负 | 正→负 | 🟡MEDIUM |
| 宏观 | 风险偏好切换 | risk_on ↔ risk_off | 🔴HIGH |
| **宏观资产-黄金** | XAU-USDT-SWAP 1H涨跌 | ±1.5% | 🟡MEDIUM |
| **宏观资产-原油** | CL-USDT-SWAP 1H涨跌 | ±2% | 🟡MEDIUM |
| **宏观资产-铜** | XCU-USDT-SWAP 1H涨跌 | ±2% | 🟡MEDIUM |
| **宏观资产-股票** | TSLA/COIN 1H涨跌 | ±3% | 🟡MEDIUM |
| **宏观共振** | 黄金↑ + BTC↑ | 同时发生 | 🔴HIGH |
| **宏观共振** | 黄金↑ + BTC↓ | 同时发生 | 🔴HIGH |
| **宏观共振** | COIN↑ + BTC↑ | 同时发生 | 🟢LOW |
| **持仓(dreamdemo)** | 仓位浮亏 | >1%🟡 / >2%🔴 | 🟡MEDIUM+🔴HIGH |
| 事件 | 重大新闻 | headline_risk ≥ 2 | 🔴HIGH |

## 输入（建议字段）

| 字段 | 类型 | 说明 |
|:---|:---|:---|
| `last_market_state` | object | 上次监控的市场状态 |
| `last_strategy_directive` | object | 当前有效的战略指令 |
| `open_positions_dreamdemo` | object[] | dreamdemo 当前持仓（重点） |

## 输出（必须结构化）

```json
{
  "monitoring_report": {
    "monitoring_id": "string",
    "monitoring_cycle": 1,
    "monitoring_time": "ISO时间戳",
    "market_state_snapshot": {
      "price": 74389.5,
      "price_change_1h_pct": 0.35,
      "trend_direction": "BULL",
      "rsi_14": 58.3,
      "atr_14": 185.2,
      "funding_rate": 0.0001,
      "funding_rate_prev": 0.0002,  # P005: 上次费率
      "funding_rate_change_pct": -50.0,  # P005: 变化率%
      "funding_flip_detected": false,  # P005: 翻转检测
      "oi_delta_pct": 1.2,
      "macro_sentiment": "risk_on"
    },
    "macro_assets": {               # v4.2 新增: 宏观资产池监控
      "assets": [
        {
          "inst_id": "XAU-USDT-SWAP",
          "name": "黄金",
          "price": 2350.50,
          "change_1h_pct": 1.2,
          "trend_direction": "UP",
          "correlation_with_btc": "NEGATIVE",
          "signal_to_btc": "黄金涨→BTC可能面临避险资金流出"
        },
        {
          "inst_id": "CL-USDT-SWAP",
          "name": "原油",
          "price": 78.50,
          "change_1h_pct": -0.8,
          "trend_direction": "DOWN",
          "correlation_with_btc": "POSITIVE",
          "signal_to_btc": "原油跌→通胀预期降温→BTC可能承压"
        }
      ],
      "resonance_signals": [
        {
          "signal_type": "INFLATION_EXPECTATION",
          "description": "黄金↑ + BTC↑ 同时发生",
          "assets_involved": ["XAU-USDT-SWAP", "BTC-USDT-SWAP"],
          "direction_implication": "UP",
          "strength": "STRONG",
          "action_suggestion": "可考虑加仓BTC多单"
        }
      ],
      "correlation_break_alert": {
        "detected": false,
        "description": "如果检测到相关性断裂，这里会有描述",
        "implication": "趋势可能反转，建议谨慎"
      },
      "last_update": "ISO时间戳"
    },
    "change_detection": {
      "has_significant_change": false,
      "changes": [],
      "change_summary": "无重大变化",
      "level_1_5_check": {                    // ⭐ v4.6 必填!
        "executed": true,                      // 是否执行了L1.5检查
        "triggered": false,                    // 是否触发
        "trigger_condition": null,
        "delta_values": {"si_index": 0, "edge": 0},
        "anti_shake": {
          "time_since_last_a2_update_h": 0,
          "edge_delta": 0, "si_delta": 0
        },
        "no_trigger_reason": ""
      }
    },
    "position_alerts": {
      "dreamdemo": {
        "has_open_position": false,
        "position_status": "HEALTHY|WARNING|CRITICAL",
        "floating_pnl_pct": -0.01,
        "usdt_balance": 679.03,
        "position_count": 0
      },
      "A5_suspended": {
        "has_open_position": false,
        "position_status": "HEALTHY|WARNING|CRITICAL",
        "floating_pnl_pct": -0.005,
        "usdt_balance": "暂停监控",
        "position_count": "暂停监控",
        "position_detail": "BTC LONG 6.09张@$78,561.71, 止损$76,900"
      },
      "combined_risk": "LOW|MEDIUM|HIGH|CRITICAL"
    },
    "strategic_environment": {
      "current_regime": "TREND_STRONG",
      "regime_changed": false,
      "strategy_still_valid": true
    }
  },
  "action_required": {
    "action": "NONE|MONITOR|ALERT|RESPONSE",
    "priority": "LOW|MEDIUM|HIGH|CRITICAL",
    "description": "如需行动，描述行动内容"
  }
}
```

---

## 宏观资产池监控（v4.2 新增 · 2026-04-26）

> **核心**: 监控黄金/原油/铜/TSLA/COIN 等宏观资产与BTC的联动关系，
> 识别跨资产共振信号，为战略制定提供宏观背景。

### 监控资产清单

| 资产 | instId | 与BTC相关性 | 监控指标 | 告警阈值 |
|---|---|---|---|---|
| 黄金 | `XAU-USDT-SWAP` | 负相关（避险） | 1H涨跌幅 | ±1.5% |
| 原油 | `CL-USDT-SWAP` | 正相关（通胀） | 1H涨跌幅 | ±2% |
| 铜 | `XCU-USDT-SWAP` | 正相关（经济） | 1H涨跌幅 | ±2% |
| TSLA | `TSLA-USDT-SWAP` | 正相关（风险偏好） | 1H涨跌幅 | ±3% |
| COIN | `COIN-USDT-SWAP` | 强正相关（行业β） | 1H涨跌幅 | ±3% |

### 宏观共振信号

| 信号类型 | 触发条件 | BTC方向暗示 | 告警级别 |
|---|---|---|---|
| INFLATION_EXPECTATION（通胀预期） | 黄金↑ + BTC↑ | UP | 🔴 HIGH |
| RISK_OFF（避险情绪） | 黄金↑ + BTC↓ | DOWN | 🔴 HIGH |
| INDUSTRY_BETA_CONFIRM（行业β确认） | COIN↑ + BTC↑ | UP | 🟢 MEDIUM |
| RISK_ON（风险偏好） | 黄金↓ + TSLA↑ | UP | 🟡 MEDIUM |
| STAGFLATION_FEAR（滞胀恐慌） | 原油↑ + 铜↓ | DOWN | 🔴 HIGH |

### 数据采集方式

```bash
# A6 监控时自动调用（追加到Phase 1）
for inst in "XAU-USDT-SWAP" "CL-USDT-SWAP" "XCU-USDT-SWAP" "TSLA-USDT-SWAP" "COIN-USDT-SWAP"; do
  result=$(okx market ticker $inst --profile dreamdemo 2>/dev/null)
  # 解析 last/change24h 字段
  price=$(echo "$result" | grep "last" | awk '{print $2}')
  change_pct=$(echo "$result" | grep "change24h" | awk '{print $2}')
  # 写入 macro_assets.assets[]
done

# 共振信号检测（在Phase 2 变化检测中追加）
# 检查 黄金↑ + BTC↑ / 黄金↑ + BTC↓ 等组合
```

### 与现有监控的集成

- **Phase 1（数据采集）**: 追加宏观资产价格查询
- **Phase 2（变化检测）**: 追加共振信号检测
- **Phase 3（持仓监控）**: 不影响现有逻辑
- **输出报告**: 追加 `macro_assets` 字段（已在上方JSON中定义）

---

### ⚠️ 产出文件规范 (v3.3 新增)

> **约束**: A6自动执行时，**仅产出2个核心文件**：
> - ✅ `intelligence_briefing_YYYYMMDD_HHMM.md` — 情报简报
> - ✅ `alert_log_YYYYMMDD.md` — 告警日志
>
> **暂停产出**:
> - ❌ `market_heatmap_YYYYMMDD_HHMM.html` — **暂停自动生成**
>   - 原因: token消耗过高，每次执行浪费~15K tokens
>   - 例外: 人工明确需求时，可单独调用生成

## 告警级别

| 级别 | 含义 | 响应时间 |
|:---|:---|:---|
| 🟢 LOW | 信息，正常波动 | 无需响应 |
| 🟡 MEDIUM | 警告，需要关注 | 下一周期观察 |
| 🔴 HIGH | 告警，需要行动 | 触发应急流程 |
| ⚫ CRITICAL | 紧急，立即行动 | 立即止损 |

## 执行流程

```
Phase 0: 信息搜索策略（强制优先级）← v2.1 新增
├── ⭐ 第一优先: Tavily AI Search skill
│   ├── 用途: FGI、地缘政治、ETF流向、宏观事件、市场新闻
│   ├── 原因: 结构化输出、token消耗低、结果质量高
│   └── 调用: use_skill("tavily-ai-search") → search(query="...")
├── 第二优先: web_search（仅Tavily信息不全时）
│   ├── 用途: Tavily未覆盖的特定数据源（如CNN/TheHill长文）
│   ├── 原因: token消耗高，仅作补充
│   └── 约束: 最多2次web_search，优先用web_fetch抓取具体URL
└── 第三优先: OKX CLI 直接查询
    ├── 用途: 行情、资金费率、账户余额、持仓（无需搜索）
    └── 命令: okx market ticker/candles/funding-rate + okx account balance/positions

Phase 1: 数据采集 (30s)
├── 当前价格/K线 (OKX CLI)
├── 资金费率/OI (OKX CLI)
├── ⭐ dreamdemo 账户持仓 (profile=A5, OKX CLI)

└── 宏观数据 (Tavily → web_search备选)

Phase 1.5: ⭐ 情报分析流程 (dream-intelligence-analysis 强制调用) ← v4.3 新增 ⚠️

> **⚠️ A6核心升级**: 每次监控必须调用dream-intelligence-analysis SKILL，
> 使用结构化情报分析方法论进行分析，而非简单数据罗列。

```
╔═══════════════════════════════════════════════════════════════════════════════╗
║               Phase 1.5: 情报分析核心流程 (dream-intelligence-analysis)       ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  Step 1: 加载情报分析方法论                                                  ║
║  ├── use_skill("dream-intelligence-analysis")                               ║
║  └── 读取: 认知偏见检查清单、ACH方法论、不确定性表达规范                       ║
║                                                                              ║
║  Step 2: 关键假设检查 (必须用) ← 识别分析前提                               ║
║  ├── "BTC当前牛市的前提假设是什么？"                                         ║
║  ├── "哪些假设如果被证伪，整个分析就会崩溃？"                                 ║
║  └── 输出: 假设清单 + 每个假设被证伪的概率                                    ║
║                                                                              ║
║  Step 3: 竞争性假设分析 ACH (必须用) ← 核心分析工具                          ║
║  ├── ACH1: 提出假设 (至少3个)                                                ║
║  │   ├── 假设A: 正常回调（资金费率正=顺势，BTC盘整=消化获利盘）                ║
║  │   ├── 假设B: 趋势反转（宏观恶化+技术面顶背离）                            ║
║  │   └── 假设C: 假突破洗盘（主力震仓获取筹码）                                ║
║  ├── ACH3: 搜集证据                                                         ║
║  │   ├── 支持假设A的证据: 费率正、周线BULL、S&P新高                          ║
║  │   ├── 支持假设B的证据: FGI背离、$78,200阻力                               ║
║  │   └── 支持假设C的证据: 冲高回落、量能萎缩                                 ║
║  ├── ACH4: 评估一致性                                                        ║
║  │   └── 对每个假设，从1-7打分一致性程度                                     ║
║  ├── ACH5: 评估诊断性                                                        ║
║  │   └── 识别最具诊断性的证据（如突破$78,200会证伪假设B）                     ║
║  └── ACH7: 选择结论                                                          ║
║      └── 输出: 最可能的假设 + 概率区间                                        ║
║                                                                              ║
║  Step 4: 红队分析 (必须用) ← 对抗性挑战                                      ║
║  ├── "站在空头视角：为什么BTC应该下跌？"                                     ║
║  │   ├── 理由1: 伊朗谈判可能破裂（概率？）                                   ║
║  │   ├── 理由2: BTC已经超涨（FGI=33=恐惧，但价格上涨）                        ║
║  │   └── 理由3: $78,200是强阻力，历史多次在此受挫                            ║
║  ├── "如果我是庄家，我会如何操作？"                                          ║
║  │   └── 策略: 突破$78,200诱多 → 止损扫损 → 砸盘                            ║
║  └── "这些反驳是否足够有力改变结论？"                                       ║
║                                                                              ║
║  Step 5: 魔鬼代言人 (必须用) ← 内部批判                                      ║
║  ├── "我是否陷入了确认偏见？"                                               ║
║  │   └── 自检: 我是否只看到支持多头的信息？                                  ║
║  ├── "我是否被锚定在早期信息？"                                             ║
║  │   └── 自检: 上次分析是Bull，现在是否还在找Bull证据？                       ║
║  └── "是否有被忽视的关键风险？"                                            ║
║      └── 自检: 伊朗/美联储/ETF到期 等是否考虑？                             ║
║                                                                              ║
║  Step 6: 高影响/低概率事件检查 (必须用) ← 黑天鹅防御                         ║
║  ├── "有哪些低概率但高影响的事件？"                                        ║
║  │   ├── P=5%: 美联储紧急降息 → BTC暴涨                                     ║
║  │   ├── P=8%: 伊朗正式封锁霍尔木兹 → 风险资产暴跌                         ║
║  │   └── P=3%: 交易所被盗 → BTC暴跌                                        ║
║  └── "这些尾部风险如何影响当前策略？"                                       ║
║      └── 建议: 设置止损/轻仓/期权对冲                                       ║
║                                                                              ║
║  Step 7: 不确定性表达 (必须量化) ← 禁止模糊表述                              ║
║  ├── ❌ 禁止: "可能"、"大概率"、"有一定风险"                               ║
║  └── ✅ 必须: 概率区间                                                       ║
║      ├── "BTC高概率(65%-85%)维持$77,000-$78,600区间震荡"                   ║
║      ├── "低概率(15%-30%)突破$78,200进入新上升通道"                         ║
║      └── "极低概率(5%-10%)发生黑天鹅事件"                                    ║
║                                                                              ║
║  Step 8: 顾问评审 (推荐)                                                    ║
║  ├── 调用: advisor_direct_call.advisors_review(scene="MACRO_ANALYSIS")      ║
║  └── 交叉验证: 获取advisor-mr + advisor-tr的独立判断                        ║
║                                                                              ║
║  输出格式:                                                                   ║
║  {                                                                            ║
║    "most_likely_hypothesis": "假设A: 正常回调",                             ║
║    "probability_range": "65%-80%",                                          ║
║    "confidence": "HIGH",  // HIGH/MEDIUM/LOW                               ║
║    "key_assumptions": ["费率正", "周线BULL", ...],                          ║
║    "assumption_risks": [                                                      ║
║      {"assumption": "费率持续正值", "prob_break": "20%", "impact": "HIGH"}  ║
║    ],                                                                         ║
║    "counter_arguments": ["空头观点1", "空头观点2"],                         ║
║    "tail_risks": [{"event": "...", "prob": "5%", "impact": "CRITICAL"}],   ║
║    "contradiction_check": "无矛盾 / 存在矛盾→需重启A1-A3"                  ║
║  }                                                                            ║
║                                                                              ║
╚═══════════════════════════════════════════════════════════════════════════════╝
```

Phase 2: 变化检测 (30s) — ⚠️ v4.6 强制集成 Level 1.5

> **⚠️ v4.6 修正 (2026-04-28 A8修复)**:
> Phase 2变化检测必须**强制执行**Level 1.5 SIGNIFICANT_SHIFT检查，
> 不再是可选参考。每轮A6执行都必须完成此检查并记录结果。

```
═════════════════════════════════════════════════════════
  Phase 2 变化检测完整流程 (v4.6)
╚═════════════════════════════════════════════════════════

Step 2.0: 基础变化检测（原有4项）
├── 价格变化 > 阈值 (±2%)
├── 趋势信号变化 (MA排列/金叉死叉)
├── 动量信号变化 (RSI极值区)
└── 宏观信号变化 (risk_on/risk_off切换)

Step 2.1: 📌 Level 1.5 SIGNIFICANT_SHIFT 检查 (⭐ v4.6 强制!)
│
│   【必须每轮执行! 不得跳过!】
│
│   Step 2.1a: 读取上次SI_Index / Edge值
│     ├── 来源: 最新episode JSON 或 上次情报简报
│     └── 若无历史值 → 记录初始值, 跳过本次(下轮开始比较)
│
│   Step 2.1b: 计算 delta 值
│     ├── delta_SI = |SI_current - SI_prev|
│     ├── delta_Edge = |Edge_current - Edge_prev|
│     └── 记录到 change_detection.level_1_5_check
│
│   Step 2.1c: 检查4个触发条件(T1-T4)
│     ├── T1: Edge从≥+20变为≤-10(或反向) [幅度≥15]
│     ├── T2: SI_Index从≥+30变为≤+10(或反向) [幅度≥20]
│     ├── T3: 1H趋势方向与日线趋势方向背离
│     └── T4: 费率从负转正/正转负(L_FUNDING_FLIP)
│
│   Step 2.1d: 检查3个防抖条件(全部满足才允许触发)
│     ├── ✅ 距上次A2更新≥2h (读取a2_contradiction_*时间戳)
│     ├── ✅ Edge变化幅度≥15 或 SI变化幅度≥15
│     └── ✅ 非静默时段(非00:00-01:00 CST)
│
│   Step 2.1e: 判定结果
│     ├── 触发 → 立即执行A2增量更新(见下方Level 1.5执行链路)
│     │   ├── 读取上次A2矛盾图谱
│     │   ├── 重新评估C1-C8权重
│     │   ├── 生成 a2_contradiction_incremental_{HHMM}.json
│     │   ├── 写入 monitoring/a0/{HHMM}.json
│     │   └── 更新A6账本 + 情报简报标记[LEVEL_1.5_TRIGGERED]
│     └── 未触发 → 记录NO_TRIGGER + 原因(如"Edge变化=3 < 阈值15")
│         └── ⚠️ 即使未触发也必须在change_detection中记录!
│            (确保A8可追溯每轮是否执行了L1.5检查)

【change_detection JSON 输出格式(v4.6扩展)】:
{
  "has_significant_change": true/false,
  "changes": [...],
  "change_summary": "...",
  "level_1_5_check": {                    // ← v4.6 新增必填!
    "executed": true,                      // 是否执行了L1.5检查
    "triggered": false,                    // 是否触发了L1.5
    "trigger_condition": null|T1|T2|T3|T4,
    "delta_values": {
      "si_index": ...,
      "edge": ...
    },
    "anti_shake": {                        // 防抖检查结果
      "time_since_last_a2_update_h": ...,  // 距上次A2更新小时数
      "edge_delta": ...,
      "si_delta": ...
    },
    "no_trigger_reason": "..."             // 未触发原因(仅未触发时)
  }
}
```

Phase 2.3: Exit Skill 风险库检测 (v4.7 新增 · 2026-04-28)

> **核心**: 在变化检测后，调用Exit Skill风险库进行静态风险检测，识别历史相似模式。
> **目的**: 提前发现与历史崩盘/回调事件相似的市场特征，触发预警。

### 风险库检测流程

```
Step 2.3a: 提取市场特征
├── 波动率分位 (ATR vs 历史)
├── 成交量比率 (当前 vs 历史)
├── 动能背离 (RSI vs 价格)
├── 资金费率
└── 价格结构

Step 2.3b: 调用 Exit Skill 快速检测
├── 命令: python ~/.workbuddy/skills/dream-exit-skill-v2/exit_quick_check.py
├── 输入: --volatility X --volume-ratio Y --divergence
└── 输出: JSON格式检测结果

Step 2.3c: 解析检测结果
├── action: hold/close/reduce
├── risk_level: low/medium/high/critical
├── risk_sources: 风险来源列表
└── should_escalate: 是否升级

Step 2.3d: 触发响应
├── critical → 立即触发A5出场
├── high → 触发A4试探 + 告警
├── medium → 记录监控，下一周期观察
└── low → 正常流程
```

### Exit Skill 快速检测命令

```bash
# 基础检测
cd ~/.workbuddy/skills/dream-exit-skill-v2
python exit_quick_check.py \
  --volatility 85 \
  --volume-ratio 0.3 \
  --divergence \
  --json

# 预设场景检测
python exit_quick_check.py --preset crash --json   # 崩盘场景
python exit_quick_check.py --preset correction --json  # 回调场景
python exit_quick_check.py --preset normal --json   # 正常场景
```

### 检测结果输出格式

```json
{
  "action": "close",
  "risk_level": "critical",
  "risk_sources": [
    {
      "type": "risk_library",
      "match_score": 0.85,
      "matched_events": ["RE_001: 2020-03-12 黑色星期四"],
      "reasons": ["高波动 + 低成交量 + 动能背离"]
    }
  ],
  "should_escalate": true,
  "recommendations": ["立即离场 - 风险库匹配"]
}
```

### 与A6监控的集成

| Exit Skill 输出 | A6 响应 | 触发链路 |
|:---|:---|:---|
| action=close, level=critical | 🔴 立即出场 | A5执行 |
| action=close, level=high | 🔴 告警 + 试探 | A4验证 |
| action=reduce, level=medium | 🟡 关注 | 记录监控 |
| action=hold, level=low | 🟢 正常 | 无操作 |

### 风险库同步（A6发现 → 风险库）

```bash
# A6发现新风险事件后，同步到风险库
cd ~/.knowledge_base/5_risk_library
python a6_sync_tool.py --auto-extract --hours 1

# 查看待审核事件
python a6_sync_tool.py --list-pending

# 批准事件入库
python a6_sync_tool.py --approve 20260428_001
```

---

Phase 2.5: 三屏MA趋势监控 (v3.1 新增) ⚠️

> **核心思想**: 以三屏（周线/日线/1小时线）MA均线为基础，构建"方向-斜率-斜率变化"三维向量分析，
> 类似运动学中的"位置-速度-加速度"，捕捉趋势的生命周期。

### 三屏周期

| 屏 | K线周期 | 分析目的 | MA参数 | 数据量 |
|:---|:-------:|:---------|:-------|:------:|
| **周线屏** | 1W | 长期趋势骨架 | MA10 / MA20 / MA50 | 100根 |
| **日线屏** | 1D | 中期趋势方向 | MA5 / MA10 / MA20 / MA60 | 120根 |
| **小时屏** | 1H | 短期交易节奏 | MA5 / MA10 / MA20 / MA60 | 200根 |

### 三维向量分析 (每屏独立计算)

```
三维向量 = (方向, 斜率, 斜率变化)

🟢 方向 (Position) — MA排列状态
│   "市场在哪里?"
├── 多头排列: MA5 > MA10 > MA20 > MA60 → BULL
├── 空头排列: MA5 < MA10 < MA20 < MA60 → BEAR
├── 缠绕/交叉: 排列不清晰 → NEUTRAL
├── 计算方法:
│   score = (MA5>MA10?1:-1) + (MA10>MA20?1:-1) + (MA20>MA60?1:-1)
│   score ≥ 2 → BULL | score ≤ -2 → BEAR | 其他 → NEUTRAL
└── 关键信号: 金叉(MA短期上穿长期) / 死叉(MA短期下穿长期)

📈 斜率 (Velocity) — MA变化速率
│   "趋势有多快?"
├── 计算方法: slope = (MA_current - MA_5bars_ago) / 5  (5根K线斜率，与MA参数对齐)
├── 斜率方向: slope > 0 → UP | slope < 0 → DOWN | |slope| < threshold → FLAT
├── 关键信号:
│   ├── 斜率加速: |当前斜率| > |5根前斜率| * 1.5
│   └── 斜率拐点: 斜率方向从UP→DOWN 或 DOWN→UP (连续2根确认)
└── 强度分级:
    |slope| / price > 0.1% → STRONG
    |slope| / price > 0.03% → MODERATE
    |slope| / price ≤ 0.03% → WEAK

🔄 斜率变化 (Acceleration) — 斜率的导数
│   "趋势在加速还是减速?"
├── 计算方法: accel = slope_current - slope_3bars_ago
├── 状态:
│   ├── 正加速 (accel > 0): 趋势加强
│   ├── 负加速 (accel < 0): 趋势减弱
│   └── 零加速 (|accel| ≈ 0): 趋势匀速
└── ⚠️ 关键信号: 加速度拐点 = 斜率从加速变为减速 (趋势即将反转的前兆!)
```

### 三屏综合研判（含买卖逻辑）⚠️ A6自主分析

> **核心原理（古典三屏交易法）**：
> 1. **大周期定方向**：周线/月线决定长期趋势，只做顺势
> 2. **中周期看趋势**：日线确认中期方向，与主周期同向
> 3. **小周期找买点**：小时线/30分钟找精确入场点，**回调买入/反弹卖出**
> 4. **⚠️ 斜率放缓 = 趋势减速 = 入场信号**：小时线BEAR但斜率放缓(负值绝对值减小) → 下跌动能衰竭 → 回调结束，可加仓
> 
> **⚠️ A6自主判断要求**：
> - A6必须**自主分析**三屏信号，不依赖做梦部或其他外部判断
> - 分析完成后，**自主决定**后续触发操作（A4/A5/A1-A3）
> - 分析过程必须记录在情报简报中，供后续审计

```
三屏综合 = (周线向量, 日线向量, 小时线向量)

═══════════════════════════════════════
  一、三屏同向（共振）— 强趋势，顺势操作
═══════════════════════════════════════
├── 周BULL + 日BULL + 小时BULL → 强上涨确认
│   └── 操作: 持有多头 / 小时线回调至MA5/MA10时加仓
└── 周BEAR + 日BEAR + 小时BEAR → 强下跌确认
    └── 操作: 持有空头 / 小时线反弹至MA5/MA10时加仓

═══════════════════════════════════════
  二、大周期顺向 + 小周期逆向（回调/反弹）— ⭐ 核心买卖区
═══════════════════════════════════════
├── 周BULL + 日BULL + 小时BEAR → 多头趋势中的回调（买入机会！）
│   ├── 判断: 小时线下跌 = 回调，非反转
│   ├── ⚠️ 小时斜率放缓？(负值绝对值减小 或 转正值) → 🟢 回调即将结束
│   ├── 操作: 🟢 **回调加仓信号**！小时线止跌企稳后买入
│   └── 止损: 近期小时线最低点下方
│
├── 周BULL + 日NEUTRAL + 小时BEAR → 多头趋势暂停，回调加深
│   ├── 判断: 日线转平说明中期整理，小时BEAR是整理中的回调
│   ├── 小时斜率放缓 → 🟢 整理即将结束，方向延续
│   ├── 操作: 🟢 分批加仓（日线MA20/MA60支撑附近）
│   └── 止损: 日线MA60下方
│
├── 周BEAR + 日BEAR + 小时BULL → 空头趋势中的反弹（卖出/做空机会！）
│   ├── 判断: 小时线上涨 = 反弹，非反转
│   ├── ⚠️ 小时斜率放缓？(正值绝对值减小 或 转负值) → 🔴 反弹即将结束
│   ├── 操作: 🔴 **反弹减仓/做空信号**！小时线滞涨后卖出
│   └── 止损: 近期小时线最高点上方
│
└── 周BEAR + 日NEUTRAL + 小时BULL → 空头趋势暂停，反弹加深
    ├── 判断: 日线转平说明中期整理，小时BULL是整理中的反弹
    ├── 小时斜率放缓 → 🔴 整理即将结束，方向延续
    ├── 操作: 🔴 分批减仓/做空（日线MA20/MA60压力附近）
    └── 止损: 日线MA60上方

═══════════════════════════════════════
  三、大周期逆向 + 小周期顺向（反转信号）— 谨慎操作
═══════════════════════════════════════
├── 周BEAR + 日BEAR + 小时BULL → ⚠️ 潜在底部反转
│   └── 操作: 轻仓试探，等待周线 bullish 确认
└── 周BULL + 日BULL + 小时BEAR → ⚠️ 潜在顶部反转
    └── 操作: 减仓观望，等待周线 bearish 确认

═══════════════════════════════════════
  四、三屏缠绕（无趋势）— 避免交易
═══════════════════════════════════════
└── 所有屏NEUTRAL → 盘整区间，等待方向选择
```

### ⭐ 回调加仓/反弹减仓 判定公式

```
回调加仓信号（多头）：
  条件:
    1. 周线BULL (方向 > 0)  ← 大周期定方向
    2. 小时线BEAR (方向 < 0)  ← 小周期逆向，存在回调
    3. 小时斜率 负值 且 |斜率_current| < |斜率_3周期前|  ← 斜率放缓！
    4. 基本面验证: A1-A3战略方向 ≠ SHORT（不矛盾）
  结论: 🟢 触发 A4试探 或 A5加仓

反弹减仓信号（空头）：
  条件:
    1. 周线BEAR (方向 < 0)  ← 大周期定方向
    2. 小时线BULL (方向 > 0)  ← 小周期逆向，存在反弹
    3. 小时斜率 正值 且 |斜率_current| < |斜率_3周期前|  ← 斜率放缓！
    4. 基本面验证: A1-A3战略方向 ≠ BUY（不矛盾）
  结论: 🔴 触发 A4试探 或 A5减仓
```


---

## 🔗 三屏信号 + 基本面验证 → 触发操作（v4.1 新增）⚠️ A6自主决定

> **核心逻辑**：三屏技术信号需与A1-A3基本面（宏观/链上/情绪）结合验证，根据确定性强度触发不同链路。
> 
> **⚠️ A6自主决定要求**：
> - A6必须**自主验证**三屏信号与A1-A3结论的关系（不矛盾/一致/背离）
> - A6必须**自主决定**触发类型（A4试探/A5执行/A1-A3重启）
> - A6必须**自主执行**触发（use_skill调用对应链路）
> - **禁止**等待做梦部"道德审判"后再行动

### 验证流程（A6自主执行）

```
三屏信号 
  ↓
基本面验证 (A1-A3结论)
  ↓
  ├── 无矛盾 + 确定性弱 → 触发 A4（小仓试探）
  ├── 无矛盾 + 确定性强 + 与A1-A3一致 → 触发 A5（正式执行）
  └── 有矛盾/背离 → 触发 A1-A3（重启战略分析）
```

### 操作类型一：触发 A4（确定性较弱）

**适用场景**：
- 三屏出现信号，但基本面支持力度较弱
- 与A1-A3结论**不矛盾**，但A1-A3结论可能是震荡/中性
- A6是最新判断，小仓按照预案进行尝试

**执行规则**：
```
触发条件:
  1. 三屏信号: 出现明确方向（回调加仓 OR 反弹减仓）
  2. 基本面验证: A1-A3战略方向 ≠ 相反方向（不矛盾即可）
  3. 确定性: WEAK → MODERATE
  
执行方式:
  ├── 调用 A4 (dream-tactical-validator)
  ├── A4使用模拟盘（dreamdemo）验证
  ├── 仓位: 小仓（≤10%）
  └── 记录: 写入记忆账本，标记"A6触发-A4验证"
```

### 操作类型二：触发 A5（确定性强）

**适用场景**：
- 三屏出现信号，**且**基本面强力支持
- **与A1-A3判断一致**（A1-A3也指向同一方向）
- 这是A4和A5的关键区别：A4可以是不违背，A5必须是一致

**执行规则**：
```
触发条件:
  1. 三屏信号: 出现明确方向（回调加仓 OR 反弹减仓）
  2. 基本面验证: A1-A3战略方向 = 相同方向（必须一致！）
  3. 确定性: STRONG → VERY_STRONG
  4. 门禁检查: A5三层权限检查通过
  
执行方式:
  ├── 调用 A5 (dream-tactical-executor)
  ├── A5可操作模拟盘（dreamdemo）
  ├── 仓位: 中仓（20-40%，根据score决定）
  ├── 必须经过 RM顾问评审（verdict ≠ DISAGREE）
  │   ⚠️ v4.2: 使用 `advisor_direct_call.advisors_review()` 内联调用
  └── 记录: 写入记忆账本，标记"A6触发-A5执行"
```

### 操作类型三：触发 A1-A3（信号与基本面背离）

**适用场景**：
- 三屏信号与A1-A3基本面分析**出现背离**
- 例如：三屏看多，但A1-A3宏观/地缘指向风险
- **只要有持仓，都需要检查此条件**

**执行规则**：
```
触发条件:
  1. 三屏信号: 出现明确方向
  2. 基本面验证: A1-A3战略方向 = 相反方向（背离！）
  3. 或: A1-A3已超过72小时未更新
  
执行方式:
  ├── 第一步: 检查现有持仓
  │   ├── 有持仓 → 触发止损/减仓（保护本金）
  │   └── 无持仓 → 跳过此步
  ├── 第二步: 重启 A1（深度调研）
  ├── 第三步: A1 → A2 → A3 完整链路
  ├── 第四步: 根据新A3结论，触发A4或A5
  └── 记录: 写入记忆账本，标记"A6触发-A1重启"
```

### 触发决策矩阵

| 三屏信号 | A1-A3结论 | 是否矛盾 | 触发操作 | 仓位 |
|:--------|:----------|:--------|:--------|:-----|
| 周BULL+小时BEAR（回调） | BULL/BUY | ❌ 不矛盾 | A4试探 | ≤10% |
| 周BULL+小时BEAR（回调） | BULL/BUY | ❌ 不矛盾 + 强支持 | A5执行 | 20-40% |
| 周BULL+小时BEAR（回调） | BEAR/SHORT | ✅ 背离！ | A1-A3重启 | 先平仓 |
| 周BEAR+小时BULL（反弹） | BEAR/SHORT | ❌ 不矛盾 | A4试探 | ≤10% |
| 周BEAR+小时BULL（反弹） | BEAR/SHORT | ❌ 不矛盾 + 强支持 | A5执行 | 20-40% |
| 周BEAR+小时BULL（反弹） | BULL/BUY | ✅ 背离！ | A1-A3重启 | 先平仓 |

### 与A4上报触发的区别

```
【A6自主检测 → 触发操作】
  └── A6每小时运行时检测三屏信号 + 基本面验证

【A4上报 → 触发A6】
  └── A4在战术验证中发现T1-T5条件 → 上报A6 → A6决定链路深度

两者并列，都是A6的触发来源，互不替代。
```

---

### 数据采集方式

```python
# 使用OKX CLI获取K线数据
# 周线: okx market candle BTC-USDT-SWAP --period 1W --limit 100
# 日线: okx market candle BTC-USDT-SWAP --period 1D --limit 120
# 小时: okx market candle BTC-USDT-SWAP --period 1H --limit 200

# MA计算: 使用pandas rolling mean
# df['MA5'] = df['close'].rolling(5).mean()
# df['MA10'] = df['close'].rolling(10).mean()
# df['MA20'] = df['close'].rolling(20).mean()
# df['MA60'] = df['close'].rolling(60).mean()

# 三维向量计算:
# direction = MA排列分数
# slope = (MA_current - MA_5bars_ago) / 5  # 5根K线斜率，与MA参数对齐
# acceleration = slope_current - slope_5bars_ago
```

### 输出格式 (报告模板)

```markdown
## 📊 三屏MA趋势监控

### 周线屏 (1W)
| 维度 | MA5/MA10/MA20/MA50 | 状态 |
|:-----|:-------------------|:-----|
| 🟢 方向 | 排列: MA5>MA10>MA20>MA50 | BULL (+3) |
| 📈 斜率 | +0.15%/bar (STRONG) | UP |
| 🔄 加速 | +0.02%/bar² | 正加速 |

### 日线屏 (1D)
| 维度 | MA5/MA10/MA20/MA60 | 状态 |
|:-----|:-------------------|:-----|
| 🟢 方向 | 排列: MA5>MA10>MA20>MA60 | BULL (+3) |
| 📈 斜率 | +0.08%/bar (MODERATE) | UP |
| 🔄 加速 | -0.01%/bar² | 负加速 ⚠️ |

### 小时屏 (1H)
| 维度 | MA5/MA10/MA20/MA60 | 状态 |
|:-----|:-------------------|:-----|
| 🟢 方向 | 排列: MA5<MA10, MA10>MA20 | NEUTRAL (0) |
| 📈 斜率 | -0.02%/bar (WEAK) | FLAT |
| 🔄 加速 | +0.01%/bar² | 正加速 |

### 三屏综合研判
- **周线**: BULL+UP+正加速 → 长期多头趋势完好
- **日线**: BULL+UP+负加速 ⚠️ → 中期多头减速中
- **小时**: NEUTRAL+FLAT → 短期方向不明
- **结论**: 多头减速信号，日线加速度拐点⚠️
- **信号等级**: 🟡 P1 (趋势减速)
```

---

Phase 3: 双账户持仓监控 (60s) ← v2.0 强化
├── 3a. dreamdemo 账户检查
│   ├── 计算浮盈亏
│   ├── 检查止损/止盈接近度
│   └── 简要状态判定
├── 3b. dreamdemo 账户检查（详细）
│   
│   ├── 检查杠杆是否>2x（战略上限）
│   ├── 检查持仓方向与当前战略是否矛盾
│   ├── 检测持仓数量非预期变化（追加/平仓）
│   ├── 检查可用余额骤降
│   └── 移动止损跟随状态
└── 3c. dreamdemo 账户风险评估
    ├── 综合风险等级判定
    └── 生成持仓摘要

Phase 4: 风险评估 (30s)
├── 战略环境是否仍有效
├── dreamdemo 账户状态是否需要人工介入
└── 是否需要重新评估

Phase 5: 报告生成 (30s)
├── 生成报告（dreamdemo持仓展示）
├── dreamdemo 账户单独段落（详细）
├── dreamdemo 账户一行摘要
└── 决定是否行动

Phase 6: P0/P1级战略-战术链路重评估 (v3.0 重构) ⚠️

> **⚠️ v3.0 架构升级**: 引入A6记忆账本 + 事件方向一致性判断，根据事件与上一次战略推演的方向关系，智能选择不同深度的交易链路，避免重复全链路执行。

---

## §A6记忆账本 (v3.0 新增)

### 账本定义

> A6记忆账本是A6情报监控的"战略记忆"，记录每次决策链路的战略推演方向、战术执行结果和核心假设。当新事件发生时，A6先查询账本判断方向一致性，再决定调用哪段链路。

### 账本文件

```
路径: $WORKSPACE/.workbuddy/memory/a6_ledger.md
格式: Markdown有序列表（最新在前）
维护: 每次执行完任意链路（全链路/子链路）后追加
容量: 保留最近20条，超过时归档到 a6_ledger_archive.md
```

### 账本条目模板

```markdown
## [编号] YYYY-MM-DD HH:MM UTC+8 | 级别: P0/P1/P2 | 链路: A1-A5/A3-A5/A4-A5/A5/A4
**编号**: A6-EP{NNN}
### 事件摘要
- 事件: [一句话描述触发事件]
- 类别: [地缘政治/市场/资金/持仓/情绪]
- 严重度: [CRITICAL/HIGH/MEDIUM]

### 战略推演方向
- 方向标签: [看空/看多/中性/观望]
- 核心假设: [一句话描述关键假设，如"伊朗扣押商船→谈判破裂概率65%→避险资金流出→BTC假突破"]
- 预期走势: [如"先冲高$79K后回落至$77K-78K区间"]

### 战术执行
- 链路深度: [A1-A5全链路 / A3-A5 / A4-A5 / A5直接 / A4试探]
- 决策: [BUY/SHORT/SKIP/WAIT]
- 仓位: [X张 / 0(空仓)]
- 入场价: [$XX,XXX / N/A]
- 止损: [$XX,XXX / N/A]

### 结果跟踪
- 后续验证: [待验证/已验证/已证伪]
- 实际走势: [填入后续实际走势，复盘时补充]
- 教训: [如果有，简述]
```

### 账本查询规则

```
当检测到P0/P1级事件时:
├── Step A: 读取账本最新1-3条
│   └── 路径: $WORKSPACE/.workbuddy/memory/a6_ledger.md
│   └── 提取: 方向标签 + 核心假设 + 事件类别
├── Step B: 方向一致性判定
│   ├── 🔄 REVERSAL (方向反转)
│   │   └── 新事件与上次战略方向完全相反
│   │   └── 例: 上次预测"谈判破裂→看空"，本次"谈判延期→看多"
│   │   └── 例: 上次"看多突破$80K"，本次"BTC跌破$77K→看空"
│   │
│   ├── ➡️ SAME_DIR (同方向)
│   │   └── 新事件是上次战略方向的延续/加强
│   │   └── 例: 上次"谈判破裂60%"，本次"破裂70%+扣押商船"
│   │   └── 例: 上次"假突破风险"，本次"FGI进一步背离+费率加深"
│   │
│   ├── ⏸️ WEAKER (事件弱化)
│   │   └── P0事件的严重度低于上一次
│   │   └── 例: 上次"停火正式破裂"，本次"紧张但仍在谈判"
│   │   └── 例: 上次"BTC跌破$77K"，本次"回到$78K震荡"
│   │
│   ├── ✅ CONFIRMED (确定性利好)
│   │   └── 事件发展方向完全符合战略预测
│   │   └── 例: 上次预测"谈判成功→看多"，本次"协议正式签署"
│   │   └── 例: 上次"假突破→回落"，本次"BTC确实回落至$77K"
│   │
│   └── ❓ UNCERTAIN (不确定性事件)
│       └── P1级事件，方向不明
│       └── 例: 某官员发表模棱两可的讲话
│       └── 例: ETF数据单日波动但趋势不明
└── Step C: 根据判定结果选择链路深度 (见§分级响应规则)
```

---

## §P0/P1分级响应规则 (v3.0 新增)

### 核心原则

> **不是所有P0都需要全链路。** 根据新事件与上次战略推演的方向一致性，选择最合适的链路深度，避免资源浪费和重复分析。

### 分级响应矩阵 (v3.2: 双系统独立触发)

| # | 方向判定 | 触发来源 | 链路深度 | 说明 | 耗时上限 |
|:--|:---------|:---------|:---------|:-----|:---------|
| 1 | 🔄 REVERSAL | P0事件 **或** 🔴T-P0 | **A1→A2→A3→A4→A5** | 方向反转 或 趋势反转确认 | 90min |
| 2 | ➡️ SAME_DIR | P0事件 **或** 🟠T-P1A | **A3→A4→A5** | 同方向升级 或 三屏背离 | 50min |
| 3 | ⏸️ WEAKER / P1级 | P1事件 **或** 🟡T-P1B | **A4→A5** | 事件弱化/P1级/加速度拐点 | 30min |
| 4 | ✅ CONFIRMED | P0事件 | **A5直接执行** | 确定性利好，战略已验证 | 15min |
| 5 | ❓ UNCERTAIN | P1事件 **或** 🟢T-P2 | **A4战术试探** | 不确定性事件/小屏反转信号 | 15min |

### 各级详细流程

#### Level 1: 🔄 REVERSAL — 全链路重评估 (A1-A5)

```
触发条件: P0级事件 + 与上次战略方向完全反转
执行链路: A1(调研)→A2(原理)→A3(战略)→A4(侦察)→A5(裁决)
产物要求: 全部6个报告文件（含chain_summary）
账本更新: 写入新条目，标记方向反转
```

> **示例**: 上次A3战略推演"美伊谈判破裂→看空BTC"，本次事件"美伊谈判突然延期并释放善意→看多"
> → 方向从看空反转为看多，必须从A1开始重新调研

#### Level 2: ➡️ SAME_DIR — 战略更新+战术 (A3-A5)

```
触发条件: P0级事件 + 与上次战略方向一致（事态升级/延续）
执行链路: A3(战略更新)→A4(侦察)→A5(裁决)
前置条件: 必须引用上次A1+A2产物作为输入基础
产物要求: a3_strategy_*.md + a4_scout_*.md + a5_execution_*.md + chain_summary_*.md
账本更新: 追加到上次条目（同一战略周期），更新严重度
```

> **示例**: 上次推演"伊朗扣押商船→破裂概率60%"，本次"伊朗又扣押第3艘+开火→破裂概率70%"
> → 方向一致（都在升级），战略假设仍有效，仅需A3更新战略细节+A4战术+A5裁决

#### Level 3: ⏸️ WEAKER / P1级 — 战术试探+落地 (A4-A5)

```
触发条件:
  - P0级事件但严重度低于上一次（事态弱化）
  - P1级事件（重要但不紧急）
执行链路: A4(战术试探)→A5(裁决)
前置条件: 必须引用上次A3战略指令作为输入
产物要求: a4_scout_*.md + a5_execution_*.md + chain_summary_*.md
账本更新: 追加到上次条目，标记事件弱化
```

> **示例**: 上次"停火正式破裂→全链路A1-A5"，本次"紧张但双方仍在谈判→事态弱化"
> → 战略不变，仅需A4试探当前市场反应+A5决定是否调整仓位

#### Level 4: ✅ CONFIRMED — 直接战术落地 (A5)

```
触发条件: P0级事件 + 事件发展方向完全符合上次战略预测（确定性利好）
执行链路: A5(直接执行裁决)
前置条件: 上次战略指令中有明确的入场/出场条件，且当前满足
产物要求: a5_execution_*.md + chain_summary_*.md
账本更新: 追加到上次条目，标记已验证+落地执行
```

> **示例**: 上次战略"假突破→等待BTC回落至$77,300附近做多"，本次"BTC确实回落至$77,350"
> → 预测已验证，直接A5执行做多决策

#### Level 5: ❓ UNCERTAIN — 仅战术试探 (A4)

```
触发条件: P1级事件 + 方向不确定
执行链路: A4(战术试探) — 仅试探，不做决策
前置条件: 引用上次A3战略指令中的试探条件
产物要求: a4_scout_*.md
账本更新: 追加到上次条目，标记试探中
后续: 试探结果在下一监控周期评估，如方向明确则升级到Level 3-4
```

> **示例**: 某官员发表模棱两可讲话，市场反应不明显
> → 仅A4小仓试探市场反应，等待下一周期确认方向

#### Level 1.5: 🔔 SIGNIFICANT_SHIFT — A2增量更新 (v4.3 新增 · v4.6 强制执行)

> **⚠️ v4.6 强制执行修正 (2026-04-28 A8修复)**:
> Level 1.5从"文档化设计"升级为**强制执行流程**。
> A8验证发现：EP70(11:16) SI_Index从25→10(骤降15点)，若Level 1.5存在应触发A2增量更新，
> 但实际无a2_incremental文件生成 → **确认未实施。现已修复。**

```
═════════════════════════════════════════════════════════
  Level 1.5 强制执行流程 (v4.6)
╚═════════════════════════════════════════════════════════

【强制执行时机】— Phase 2 变化检测完成后自动检查

Step L1.5_0: SIGNIFICANT_SHIFT 检测 (必须每轮执行!)
  ├── 读取上次SI_Index / Edge值（从最新episode或情报简报）
  ├── 计算变化幅度:
  │   ├── delta_SI = |SI_current - SI_prev|
  │   └── delta_Edge = |Edge_current - Edge_prev|
  └── 检查4个触发条件:

【触发条件(任一满足即触发)】:
├── T1: Edge从≥+20变为≤-10(或反向) — 信号方向剧变(幅度≥15) ⭐最常见
├── T2: SI_Index从≥+30变为≤+10(或反向) — 信号强度骤降(幅度≥20)
├── T3: 1H趋势方向与日线趋势方向背离 — 时间框架冲突
└── T4: 费率从负转正/正转负(L_FUNDING_FLIP) — 资金面翻转

【防抖条件(全部满足才允许触发)】:
├── ✅ 距上次A2更新≥2小时 (读取a2_contradiction_*时间戳)
├── ✅ Edge变化幅度≥15 或 SI_Index变化幅度≥15 (放宽至15以增加敏感度)
└── ✅ 非静默时段(非 00:00-01:00 CST)

【执行链路】(触发后必须执行! v4.9修复 · 2026-04-29):
├── ⭐ 推荐使用自动化脚本:
│   ```bash
│   # 一键执行Level 1.5 A2增量更新
│   python3 ~/.workbuddy/skills/dream-intelligence-monitor/scripts/level15_a2_incremental_updater.py \
│     --trigger T1 --si -20 --edge -35 --reason "测试:Edge剧变"
│   
│   # T4费率翻转专用
│   python3 ~/.workbuddy/skills/dream-intelligence-monitor/scripts/level15_a2_incremental_updater.py \
│     --trigger T4 --funding_flip negative_to_positive
│   ```
│
├── 手动执行 (备用):
│   ├── Step L1.5_1: 读取上次A2矛盾图谱 (reports/trading/a2_contradiction_*.json)
│   ├── Step L1.5_2: 基于新数据重新评估C1-C8矛盾权重
│   ├── Step L1.5_3: 生成增量更新JSON:
│   │   └── reports/trading/a2_contradiction_incremental_{HHMM}.json
│   ├── Step L1.5_4: 写入monitoring日志:
│   │   └── monitoring/a0/{YYYYMMDD_HHMM}.json (A0调用记录)
│   ├── Step L1.5_5: 更新A6账本:
│   │   └── 追加标记 "SIGNIFICANT_SHIFT+A2增量更新"
│   └── Step L1.5_6: 在情报简报中标记:
│       └── [LEVEL_1.5_TRIGGERED] + 触发原因 + 更新摘要

【产物模板】(与下方格式一致):
{
  "type": "A2_INCREMENTAL_UPDATE",
  "trigger": "Level_1.5_SIGNIFICANT_SHIFT",
  "timestamp": "ISO8601",
  "trigger_condition": "T1|T2|T3|T4",
  "delta_values": { "si_index": ..., "edge": ... },
  ...
}

【未触发时的记录】(每轮都必须记录!):
├── 在change_detection段追加:
│   └── level_1_5_check: "NO_TRIGGER" + 原因(如"Edge变化=3 < 阈值15")
└── 这确保A8可追溯每轮是否执行了L1.5检查
```

> **示例**: A2凌晨判定bear主导60%，但日内$78,500突破+1H趋势转多+Edge从+20→-10
> → Phase 2检测到T1(Edge剧变) + T3(1H/日线背离)
> → 距上次A2更新=6h(>2h✅) → **触发Level 1.5**
> → 生成a2_contradiction_incremental_1116.json: bull 55% vs bear 45%
> → 下次A5执行时读取更新后的A2矛盾图谱

**A2增量更新输出格式**:
```json
{
  "type": "A2_INCREMENTAL_UPDATE",
  "trigger": "Level_1.5_SIGNIFICANT_SHIFT",
  "timestamp": "ISO8601",
  "previous_assessment": {
    "bull_pct": 40,
    "bear_pct": 60,
    "primary_contradiction": "C1 vs C4",
    "source_report": "a2_contradiction_20260427.json"
  },
  "updated_assessment": {
    "bull_pct": 55,
    "bear_pct": 45,
    "primary_contradiction": "C1(ETF流入) vs C4(地缘残余)",
    "direction": "bull_dominant"
  },
  "change_reason": "$78,500突破+1H趋势转多+Edge转负",
  "trigger_conditions_met": ["Edge剧变(+20→-10)", "1H与日线背离"],
  "evidence_refs": ["reports/intelligence_briefing_*.md"]
}
```

### 分级响应决策树

```
【触发来源1: A6自主检测P0/P1事件】
检测到P0/P1级事件
├── Step 1: 读取A6记忆账本（最新1-3条）
├── Step 2: 方向一致性判定
│   ├── 🔄 REVERSAL → Level 1: A1-A5全链路
│   ├── 🔔 SIGNIFICANT_SHIFT → Level 1.5: A2增量更新 (v4.3新增)
│   ├── ➡️ SAME_DIR → Level 2: A3-A5
│   ├── ⏸️ WEAKER   → Level 3: A4-A5
│   ├── ✅ CONFIRMED → Level 4: A5直接
│   └── ❓ UNCERTAIN → Level 5: A4试探
├── Step 3: 执行对应链路
│   └── 产物归档到交易邮箱 (reports/trading/)
└── Step 4: 更新A6记忆账本
    └── 追加新条目或更新现有条目

【触发来源2: A4主动上报（v4.0新增）】
A4上报触发条件(T1-T5)
├── Step 1: 读取A4上报内容（触发类型+证据）
├── Step 2: 查询A6记忆账本
│   └── 读取A4近5次实践结果
├── Step 3: 链路深度判定（根据T类型）
│   ├── T1（战略指令矛盾）→ REVERSAL → Level 1: A1-A5全链路
│   ├── T2（Regime偏差）→ SAME_DIR → Level 2: A3-A5
│   │   └── SAME_DIR判定：A6查账本，战略方向标签未变（如账本记录"看多"，当前A3战略也是"看多"）→ SAME_DIR
│   ├── T3（极端事件）→ REVERSAL → Level 1: A1-A5全链路
│   ├── T4（多次失败）→ WEAKER → Level 3: A4-A5
│   └── T5（假设证伪）→ REVERSAL → Level 1: A1-A5全链路
├── Step 4: 执行对应链路
│   └── A6内部use_skill依次调用A1→A2→A3→A4→A5
└── Step 5: 更新A6记忆账本
    └── 记录A4上报内容+链路执行结果
```

### 账本条目编号规则

```
编号格式: A6-EP{NNN}
- NNN从001递增
- 每次执行任意链路后分配新编号
- 同一战略周期的追加更新共用编号，用子编号区分
  例: A6-EP001 (首次全链路) → A6-EP001.1 (同方向追加) → A6-EP001.2 (事件弱化)
- 方向反转时分配新编号: A6-EP002
```

### 禁止事项

1. ❌ **禁止跳过账本查询** — P0/P1事件必须先查账本再决定链路
2. ❌ **禁止跨级选择** — 必须严格按判定结果选择对应链路深度
3. ❌ **禁止手动覆盖方向判定** — 判定逻辑由事件对比自动产生
4. ❌ **禁止空链路执行** — 选择了链路深度就必须执行到底
5. ❌ **禁止不更新账本** — 执行完毕必须写入/更新账本条目

---

### ⚠️ A6→做梦部情报传导机制 (v4.9 新增 · 2026-04-29)

> **核心问题**: A6情报识别率95%，但传达率仅40%。
> **修复方案**: A6产出情报简报时，自动复制到做梦部输入目录，做梦部独立分析后提出批评建议。

#### 传导流程

```
A6情报监控
    │
    ├─→ Phase 5: 报告生成
    │       │
    │       ├─→ 产出 intelligence_briefing_*.md (原流程)
    │       │
    │       └─→ ⭐ 新增: 自动复制到做梦部
    │               │
    │               └─→ cp intelligence_briefing_*.md
    │                       ~/.workbuddy/skills/dream-oneirology/intelligence_input/
    │
    ▼
做梦部 (自动读取输入目录)
    │
    ├─→ 独立分析A6情报
    ├─→ 提出批评建议（不直接传导给A5）
    └─→ 输出洞察报告（供A5自主判断）
```

#### 自动复制实现 (v4.9 修复 · 2026-04-29)

**触发时机**: Phase 5 报告生成完成后

**⭐ 推荐使用自动化脚本**:
```bash
# A6产出情报后，一键复制到做梦部 + 秘书目录
python3 ~/.workbuddy/skills/dream-intelligence-monitor/scripts/a6_to_oneirology_broadcast.py --latest

# 或批量复制最近24小时的所有情报
python3 ~/.workbuddy/skills/dream-intelligence-monitor/scripts/a6_to_oneirology_broadcast.py --hours 24
```

**手动复制命令** (备用):
```bash
# 复制最新情报简报到做梦部
LATEST=$(ls -t $WORKSPACE/reports/intelligence_briefing_*.md | head -1)
cp "$LATEST" ~/.workbuddy/skills/dream-oneirology/intelligence_input/

# 同时复制到秘书报告目录
cp "$LATEST" ~/.workbuddy/skills/boss-secretary/reports/trading/
```

**做梦部读取规则**:
- 做梦部运行时自动扫描 `intelligence_input/` 目录
- 读取最新的N份情报简报（如最近3份）
- 基于情报独立分析，提出批评建议
- **不直接传导给A5**，而是输出洞察报告供A5自主判断

**做梦部洞察报告投递**:
```
投递位置: ~/.workbuddy/skills/boss-secretary/reports/trading/
命名格式: dream_insight_YYYYMMDD_HHMM.md
A5义务: A5报告必须包含"做梦部洞察评估段"
```

---

## §技术信号分级与链路触发 (v3.1 新增)

> 三屏MA趋势监控产生技术信号后，按信号严重度分级，与事件分级联动触发不同深度的交易链路。

### 技术信号等级

| 等级 | 信号名称 | 触发条件 | 市场含义 |
|:----|:---------|:---------|:---------|
| 🔴 **T-P0** | 趋势反转确认 | 周线或日线出现死叉/金叉 + 大屏斜率拐点(连续2根确认) | 趋势已反转，需要重新制定战略 |
| 🟠 **T-P1A** | 三屏背离 | 价格创周期新高/低（参照最大屏MA周期：周线屏看周线高低点、日线屏看日线高低点）但至少2屏MA方向不跟随 | 趋势力度衰竭，回调/反弹概率高 |
| 🟡 **T-P1B** | 加速度拐点 | 大屏(周/日)斜率从加速变为减速(负加速) | 趋势正在减速，可能即将反转 |
| 🟢 **T-P2** | 小屏反转信号 | 仅小时屏出现金叉/死叉或斜率拐点 | 短期节奏变化，中期趋势未变 |
| ⚪ **T-P3** | 正常波动 | 无上述信号 | 无需行动 |

### 各等级链路触发规则

```
技术信号链路触发:
├── 🔴 T-P0 (趋势反转确认):
│   ├── 判定: 周线或日线MA排列反转 + 斜率拐点确认
│   ├── 账本查询: 必须 — 判定是否与上次战略方向REVERSAL
│   ├── 链路: 与事件分级P0联动，按方向判定选择Level 1-4
│   ├── 特殊: 如果当前有持仓且方向相反 → 立即A5执行止损决策
│   └── 示例: 日线从多头排列变为空头排列 → 查账本→如果上次看多则REVERSAL→A1-A5
├── 🟠 T-P1A (三屏背离):
│   ├── 判定: 价格创新高但≥2屏MA方向不跟随
│   ├── 账本查询: 必须 — 判定趋势是否仍在加速
│   ├── 链路: 默认Level 2 (A3-A5) 或 Level 3 (A4-A5)
│   │   └── 如果账本显示同方向且趋势已弱化 → Level 3
│   │   └── 如果账本显示同方向但趋势仍在 → Level 2
│   └── 示例: BTC创新高$79K但日线MA斜率转负 → A3重新评估战略+A4战术
├── 🟡 T-P1B (加速度拐点):
│   ├── 判定: 大屏(周/日)斜率加速→减速
│   ├── 账本查询: 必须 — 确认趋势生命周期位置
│   ├── 链路: 默认Level 3 (A4-A5)
│   │   └── 如果加速度拐点出现在周线 → 升级为Level 2
│   └── 示例: 周线MA20斜率从+0.15%降至+0.08% → A4试探+A5决定
├── 🟢 T-P2 (小屏反转信号):
│   ├── 判定: 仅小时屏出现MA交叉或斜率拐点
│   ├── 账本查询: 可选 — 小屏信号影响有限
│   ├── 链路: 默认Level 5 (A4试探)
│   │   └── 如果与日线/周线方向一致 → 可能升级为Level 4
│   └── 示例: 小时MA5下穿MA10但日线仍多头 → A4小仓试探
└── ⚪ T-P3 (正常波动):
    └── 无需触发链路，正常监控
```

### 双系统独立触发 + 交叉验证 (v3.2 重构)

> **核心原则**: 技术信号系统与事件信号系统是**两个独立的触发源**，任一达到P0即可启动全链路。
> 两者可互相验证来评估信号可信度，但验证**不阻塞触发**。

```
独立触发规则 (任一即触发):
├── 🔴 事件系统:
│   ├── 事件 P0 → 独立触发 Level 1-4 (按方向判定)
│   └── 事件 P1 → 独立触发 Level 3-5 (按方向判定)
├── 🔴 技术系统:
│   ├── T-P0 → 独立触发 Level 1 (趋势反转确认)
│   ├── T-P1A → 独立触发 Level 2 (三屏背离)
│   ├── T-P1B → 独立触发 Level 3 (加速度拐点)
│   └── T-P2 → 独立触发 Level 5 (小屏反转试探)
├── 🔔 信号剧变系统 (v4.3新增):
│   ├── Edge剧变(≥15) → Level 1.5 (A2增量更新)
│   ├── SI骤降(≥20) → Level 1.5 (A2增量更新)
│   ├── 1H/日线背离 → Level 1.5 (A2增量更新)
│   └── 费率翻转(L_FUNDING_FLIP) → Level 1.5 (A2增量更新)
└── 🔄 交叉验证 (两者都存在时):
    ├── 验证目的: 评估信号可信度，附加到报告中
    ├── 一致 (同方向) → 可信度 ↑ 标记 [VERIFIED]
    ├── 不一致 (反方向) → 可信度 ↓ 标记 [CONFLICT] + 增加A4侦察深度
    └── ⚠️ 验证结果不影响触发决策，仅影响执行信心

组合联动 (两者同时存在时，取更确信的方向):
├── 技术 🔴 T-P0 + 事件 P0 → 强制 Level 1 (A1-A5全链路) [VERIFIED]
├── 技术 🔴 T-P0 + 事件 P1 → Level 1 (技术信号主导) [CONFLICT if方向反]
├── 技术 🟠 T-P1A + 事件 P0 → Level 1 (事件信号主导) [CONFLICT if方向反]
├── 技术 🟠 T-P1A + 事件 P1 → Level 2 (A3-A5)
├── 技术 🟡 T-P1B + 事件 P0 → Level 2 (事件信号主导) [CONFLICT if方向反]
├── 技术 🟡 T-P1B + 事件 P1 → Level 3 (A4-A5)
├── 🔔 信号剧变 + 技术 T-P1A → Level 1.5→Level 2 (升级为A3-A5) [v4.3新增]
└── 🔔 信号剧变 + 事件 P1 → Level 1.5→Level 3 (升级为A4-A5) [v4.3新增]
├── 技术 🟢 T-P2 + 事件 P0 → Level 3 (事件信号主导)
├── 技术 🟢 T-P2 + 事件 P1 → Level 5 (A4试探)
└── 技术 ⚪ T-P3 + 事件 P1 → Level 5 (A4试探)

🔍 主导判断规则（取更确信的方向）:
├── 级别不同：取更高级别（P0 > P1 > P2）
├── 级别相同 + 方向相同 → 降级处理（CONFIRMED，可信度↑）
├── 级别相同 + 方向相反 → 升级处理（REVERSAL，需要全链路重新评估）
└── 确信度评估：
    ├── 事件有具体数据支持（如ETF流入金额、地缘冲突具体事件）→ 事件更确信
    ├── 技术有连续3根K线确认 → 技术更确信
    └── 无法判断时 → 默认事件主导（事件通常有更明确的因果链）
```

### 技术信号报告格式

每次检测到 ≥ T-P2 级别的技术信号时，在情报简报中追加：

```markdown
## 🔧 技术信号检测

### 信号摘要
| 屏 | 信号 | 等级 | 方向 | 斜率 | 加速度 |
|:---|:-----|:----:|:----:|:----:|:------:|
| 周线 | 多头排列完好 | T-P3 | BULL | UP(+0.12%) | 正加速 |
| 日线 | ⚠️ 斜率减速 | **T-P1B** | BULL | UP(+0.05%)↓ | **负加速** |
| 小时 | MA5死叉MA10 | **T-P2** | NEUTRAL | FLAT | — |

### 综合技术等级: 🟡 T-P1B (日线加速度拐点)
### 链路建议: Level 3 (A4-A5)
### 持仓影响: 当前空仓，无影响
```

---

### P0级触发条件

```yaml
P0_TRIGGERS:
  # 地缘政治类
  - ceasefire_collapse: "停火协议正式破裂"
  - major_escalation: "重大军事冲突升级"
  - strait_blockade: "霍尔木兹海峡封锁"
  
  # 市场类
  - btc_price_crash: "BTC价格跌破关键支撑（如$77,300）"
  - regime_change: "Regime状态机重大转换"
  - extreme_funding: "资金费率极端值（如<-0.01%）"
  
  # 持仓类
  - position_stop_loss: "止损被触发"
  - major_unrealized_loss: "浮亏超过5%"
  - margin_call_risk: "逼近强平价格"
  
  # 预警阈值
  - geopolitical_probability: "破裂概率≥55%"
  - break_probability_spike: "破裂概率单次跳升≥10%"

  # ⚠️ v3.1新增: 技术信号类
  - trend_reversal: "T-P0: 周线或日线MA排列反转+斜率拐点确认"
  - triple_divergence: "T-P1A: 三屏背离（价格创新高/低但≥2屏MA不跟随）"

P1_TRIGGERS:
  # v3.1新增: P1级触发条件
  - acceleration_inflection: "T-P1B: 大屏(周/日)斜率加速→减速"
  - small_tf_reversal: "T-P2: 小时屏MA交叉或斜率拐点"
  - funding_divergence: "资金费率与价格方向背离持续>6h"
  - fgi_extreme_divergence: "FGI与价格极端背离(强度>2.0)"
  - funding_flip_negative_to_positive: "费率从负转正(P005) — 空头平仓信号"
  - funding_flip_positive_to_negative: "费率从正转负(P005) — 多头平仓信号"
  - funding_velocity_spike: "费率变化速度>30%/日 — 方向选择前兆"
```

### P0/P1级响应流程 (v3.0 分级路由) ⚠️

> **核心原则**: 不再一刀切全链路。先查A6记忆账本判断方向一致性，再选择对应深度的链路。

```
P0/P1响应流程 (v3.0分级路由):
├── Step 0: P0/P1判定 (在Phase 4中完成)
│   ├── P0触发条件满足? → YES
│   └── P1事件检测? → YES
│           ↓
├── Step 0.5: 账本查询+方向判定 (v3.0新增, 强制) ⚠️
│   ├── 读取: a6_ledger.md 最新1-3条
│   ├── 判定: REVERSAL / SAME_DIR / WEAKER / CONFIRMED / UNCERTAIN
│   └── 选择: Level 1-5 对应链路深度
│           ↓
├── Level 1: 🔄 REVERSAL — A1→A2→A3→A4→A5 (全链路)
│   ├── A1调研 → A2原理 → A3战略 → A4侦察 → A5裁决
│   └── 产物: 6个报告 + chain_summary
├── Level 2: ➡️ SAME_DIR — A3→A4→A5 (战略更新)
│   ├── A3战略更新(引用上次A1+A2) → A4侦察 → A5裁决
│   └── 产物: a3 + a4 + a5 + chain_summary
├── Level 3: ⏸️ WEAKER/P1 — A4→A5 (战术试探+落地)
│   ├── A4试探(引用上次A3) → A5裁决
│   └── 产物: a4 + a5 + chain_summary
├── Level 4: ✅ CONFIRMED — A5直接执行 (战术落地)
│   ├── A5裁决(引用上次A3指令)
│   └── 产物: a5 + chain_summary
└── Level 5: ❓ UNCERTAIN — A4试探 (仅试探)
    ├── A4试探(引用上次A3指令)
    └── 产物: a4_scout_*.md
    └── 后续: 下一周期评估，可能升级
```

### P0/P1级响应时间要求 (v3.0 更新)

| 链路级别 | 依赖 | 最大耗时 | 适用场景 |
|:---------|:-----|:---------|:---------|
| Level 1: A1-A5 | 账本判定REVERSAL | **90min** | 方向完全反转 |
| Level 1.5: A2增量 | 信号剧变(SIGNIFICANT_SHIFT) | **20min** | 矛盾图谱更新(v4.3新增) |
| Level 2: A3-A5 | 账本判定SAME_DIR | **50min** | 同方向升级 |
| Level 3: A4-A5 | 账本判定WEAKER/P1 | **30min** | 事件弱化/P1级 |
| Level 4: A5 | 账本判定CONFIRMED | **15min** | 确定性利好 |
| Level 5: A4 | 账本判定UNCERTAIN | **15min** | 不确定性事件 |

> **注意**: 各级别独立计时，超时自动进入观望状态。

### 产物投递规范 (v3.0 更新)

```
投递规则 (按链路级别):
├── 所有链路产物归档到交易邮箱:
│   └── ~/.workbuddy/skills/boss-secretary/reports/trading/
├── Level 1 (A1-A5):
│   ├── a1_research_P0_*.md + a2_first_principles_P0_*.md
│   ├── a3_strategy_P0_*.md + a4_scout_P0_*.md
│   ├── a5_execution_P0_*.md + chain_summary_P0_*.md
│   └── 标记: _P0_ 前缀
├── Level 2 (A3-A5):
│   ├── a3_strategy_P0_*.md (备注: 同方向更新)
│   ├── a4_scout_P0_*.md + a5_execution_P0_*.md
│   └── chain_summary_P0_*.md
├── Level 3 (A4-A5):
│   ├── a4_scout_P0_*.md + a5_execution_P0_*.md
│   └── chain_summary_P0_*.md
├── Level 4 (A5):
│   ├── a5_execution_P0_*.md
│   └── chain_summary_P0_*.md (备注: 确定性利好直接落地)
└── Level 5 (A4):
    ├── a4_scout_P1_*.md
    └── 标记: _P1_ 前缀 (非P0)
```

### P0/P1响应示例 (v3.0 更新)

```markdown
## P0响应触发 — Level 1 (REVERSAL 全链路)

### 账本查询
- 上次条目: A6-EP001 | 方向: 看空 | 假设: "伊朗扣押商船→谈判破裂→BTC假突破"
- 方向判定: 🔄 REVERSAL — 本次事件"美伊谈判延期+释放善意"与上次完全反转

### 链路执行
| 阶段 | SKILL | 状态 | 输出 |
|:---|:---|:---:|:---|
| A1调研 | dream-strategy-research | ✅ 完成 | a1_research_P0_*.md |
| A2分析 | dream-first-principles | ✅ 完成 | a2_first_principles_P0_*.md |
| A3战略 | dream-strategy-designer | ✅ 完成 | a3_strategy_P0_*.md |
| A4侦察 | dream-tactical-validator | ✅ 完成 | a4_scout_P0_*.md |
| A5裁决 | dream-tactical-executor | ✅ 完成 | a5_execution_P0_*.md |

### 账本更新
- 新条目: A6-EP002 | 方向: 看多 | 链路: A1-A5 | Level 1

---

## P0响应触发 — Level 2 (SAME_DIR 战略更新)

### 账本查询
- 上次条目: A6-EP002 | 方向: 看多 | 假设: "谈判延期→避险情绪缓解→BTC突破$80K"
- 方向判定: ➡️ SAME_DIR — 本次事件"谈判进一步进展+ETF大额流入"与上次同方向

### 链路执行
| 阶段 | SKILL | 状态 | 输出 |
|:---|:---|:---:|:---|
| A3战略 | dream-strategy-designer | ✅ 完成 | a3_strategy_P0_*.md (引用A6-EP001/002) |
| A4侦察 | dream-tactical-validator | ✅ 完成 | a4_scout_P0_*.md |
| A5裁决 | dream-tactical-executor | ✅ 完成 | a5_execution_P0_*.md |

### 账本更新
- 追加: A6-EP002.1 | 严重度升级 | 链路: A3-A5 | Level 2

---

## P1响应触发 — Level 3 (WEAKER 战术试探+落地)

### 账本查询
- 上次条目: A6-EP002.1 | 方向: 看多
- 方向判定: ⏸️ WEAKER — 本次P1事件"某官员模棱两可讲话"，不影响战略方向

### 链路执行
| 阶段 | SKILL | 状态 | 输出 |
|:---|:---|:---:|:---|
| A4试探 | dream-tactical-validator | ✅ 完成 | a4_scout_P1_*.md |
| A5裁决 | dream-tactical-executor | ✅ 完成 | a5_execution_P1_*.md |

### 账本更新
- 追加: A6-EP002.2 | 事件弱化 | 链路: A4-A5 | Level 3
```

## 情报简报持仓区模板（v2.0）

```markdown
## 📊 持仓状态（双账户）

### 🎯 A5 子账户（重点监控）
| 项目 | 值 |
|------|-----|
| 方向 | SHORT / LONG / 空仓 |
| 数量 | X 张 |
| 入场价 | $XX,XXX |
| 浮盈亏 | +$X.XX (X.X%) |
| 杠杆 | Xx |
| 可用余额 | $XX.XX USDT |
| 状态 | 🟢HEALTHY / 🟡WARNING / 🔴CRITICAL |

### 📌 主账户（简要）
| 项目 | 值 |
|------|-----|
| 持仓 | 空仓 / SHORT X张 / LONG X张 |
| USDT | $XXX.XX |
| 状态 | 🟢 正常 |
```

## 变化检测规则

```yaml
change_detection_rules:
  price:
    threshold_pct: 2.0
    severity: MEDIUM
  trend:
    trigger: "EMA死叉/金叉"
    severity: HIGH
  momentum:
    trigger: "RSI进入<30或>70"
    severity: MEDIUM
  macro:
    trigger: "risk_on ↔ risk_off切换"
    severity: HIGH
  funding:
    threshold: 0.01
    severity: MEDIUM
  # v2.0 新增
  position_dreamdemo:
    floating_loss_warning: 1.0   # 1% 黄色告警
    floating_loss_critical: 2.0  # 2% 红色告警
    leverage_limit: 2            # 杠杆上限2x
    direction_mismatch: true     # 方向与战略矛盾
  position_A5_suspended:
    floating_loss: 2.0           # 2% 告警
```

## 集成

| 集成点 | 方向 | SKILL | 说明 |
|:---|:---|:---|:---|
| **P0触发→** | → | `dream-strategy-research` (A1) | ⚠️ v2.4新增：P0级直接调用 |
| **P0触发→** | → | `dream-first-principles` (A2) | ⚠️ v2.4新增：P0级直接调用 |
| **P0触发→** | → | `dream-strategy-designer` (A3) | ⚠️ v2.4新增：P0级直接调用 |
| **P0触发→** | → | `dream-tactical-validator` (A4) | ⚠️ v2.4新增：P0级直接调用 |
| **P0触发→** | → | `dream-tactical-executor` (A5) | ⚠️ v2.4新增：P0级直接调用 |
| **触发→** | → | `dream-pretrade-gatekeeper` | 持仓异常触发门禁 |
| **数据源←** | ← | OKX API (A5 demo) | main 账户实时行情+持仓 |
| **数据源←** | ← | OKX API (A5) | A5 子账户实时行情+持仓 |
| **搜索←** | ← | `tavily-ai-search` | ⭐ 搜索第一优先（FGI/地缘/ETF/宏观） |
| **搜索←** | ← | `web_search` | 仅Tavily信息不全时补充（最多2次） |

### P0级调用权限说明 (v2.4 新增)

> **核心升级**: P0级响应时，A6情报监控有权直接调用A1-A5完整链路，不再依赖临时任务分批执行。

```
P0权限层级:
├── A6 情报监控 (本SKILL)
│   └── P0触发 → 直接调用A1-A5
├── A1 战略调研 (dream-strategy-research)
│   └── 被A6直接调用，20min超时
├── A2 第一性原理 (dream-first-principles)
│   └── 被A6直接调用，20min超时
├── A3 战略制定 (dream-strategy-designer)
│   └── 被A6直接调用，20min超时
├── A4 战术侦察 (dream-tactical-validator)
│   └── 被A6直接调用，15min超时
└── A5 执行裁决 (dream-tactical-executor)
    └── 被A6直接调用，15min超时
```

> **⚠️ Tavily Key 配置**: `~/.zprofile` 中的 `TAVILY_API_KEY`（不要写 `~/.zshrc`，属root）。详见 FAQ 踩坑经验区。

## 搜索优先级策略（v2.1 强制）

> **核心原则**: Tavily优先，web_search兜底。web_search消耗token过高，严格控制使用。

```
信息搜索决策树:
├── 需要行情/资金费率/持仓?
│   └── ✅ 直接用 OKX CLI（不消耗搜索）
├── 需要 FGI / 地缘政治 / ETF流向 / 宏观新闻?
│   ├── ⭐ 第1步: Tavily AI Search (use_skill)
│   │   └── 优势: 结构化摘要、token低、实时性好
│   ├── 第2步: Tavily结果是否充分?
│   │   ├── ✅ 充分 → 直接使用，不调web_search
│   │   └── ❌ 不充分 → web_search (最多1-2次)
│   │       └── 搜索结果中的具体URL → web_fetch抓取详情
│   └── ⚠️ 禁止: 一上来就直接web_search
└── 需要抓取特定网页详情?
    └── ✅ web_fetch (精准抓取，不浪费token)
```

### Token消耗控制规则

| 操作 | 估算Token | 使用规则 |
|:---|:---|:---|
| Tavily Search | ~500-1000 | ⭐ 默认使用 |
| web_search | ~2000-5000 | 仅Tavily不足时，最多2次 |
| web_fetch | ~1000-3000 | 抓取具体URL，优先使用 |
| OKX CLI | ~100-300 | 行情数据，不消耗搜索token |

## 约束

1. **实时性**: 单次监控循环不超过3分钟
2. **准确性**: 所有数据必须标注来源和时间
3. **及时性**: CRITICAL告警必须立即触发响应
4. **连续性**: 每小时自动运行，不间断
5. **双账户强制**: 每次监控必须查询 main + A5 两个账户，不得遗漏（v2.0 新增）
6. **A5 侧重**: 子账户持仓展示权重70%，告警阈值更严格（v2.0 新增）
7. **搜索优先级**: Tavily优先，web_search最多2次且仅作补充，禁止直接web_search（v2.1 新增）
8. **P0直接调用**: P0触发时直接调用链路，禁止创建临时任务分批执行（v2.4 新增）
9. **账本先行**: ⚠️ P0/P1事件必须先查A6记忆账本，根据方向判定选择链路深度（v3.0 新增）
10. **分级响应**: 严格按方向判定结果(5级)选择对应链路深度，禁止手动覆盖（v3.0 新增）
11. **三屏MA强制**: 每次监控必须执行三屏MA(周/日/1H)三维向量分析，不得跳过（v3.1 新增）
12. **双系统独立触发**: 技术信号与事件信号是两个独立触发系统，任一达到P0即可启动全链路；两者同时存在时交叉验证评估可信度，但不阻塞触发（v3.2 重构）
13. **A4上报接收**: ⚠️ A6可接收A4上报，按T类型决定链路深度；不使用p0-alert-responder（v4.0 新增）

## 调度

- **自动化**: `dream-intelligence-monitor` (每小时)
- **持续运行**: 是（与交易日同步）
- **触发词**: "情报监控"、"市场监控"、"实时告警"


---

## 邮件投递规范（宪法§12强制）

> **⚠️ 宪法§12规定：本部门完成工作后，必须将工作总结写入指定邮箱目录。没有投递 = 工作未完成。**

### 投递配置

| 项目 | 值 |
|:---|:---|
| **部门名称** | 情报监控部 (A6) |
| **目标邮箱** | 交易邮箱 (trading) — 统一路径 |
| **邮箱路径** | `~/.workbuddy/skills/boss-secretary/reports/trading/` |
| **投递方式** | 直接写入Markdown文件到指定目录 |
| **文件名格式** | `intelligence_briefing_{YYYYMMDD}_{HHMM}.md` |
| **frontmatter必须（完整7字段）** | 见下方YAML代码块 |
| **双通道投递** | 秘书邮箱 + 前端产物中心（`artifact-alignment-manager` SKILL §一） |


> **前端产物center文件frontmatter完整模板（双通道均需包含）**：
> ```yaml
> ---
> title: "产物标题"
> department: trading
> chain_phase: A6
> date: "YYYY-MM-DDTHH:MM:SS"
> type: intelligence_brief
> status: completed
> tags: "a6 a6 情报"
> by_a_phase: A6
> ---
> ```
> 完整规范参见 `artifact-alignment-manager` SKILL §三

### 投递检查清单
- [ ] 文件写入 `reports/trading/` 目录
- [ ] 文件名符合 `intelligence_briefing_{YYYYMMDD}_{HHMM}.md`
- [ ] 包含完整 YAML frontmatter
- [ ] 投递后通过 `ls reports/trading/intelligence_briefing_*` 验证

### 代码入口

- **投递方式**: 直接写入Markdown文件到 `~/.workbuddy/skills/boss-secretary/reports/trading/`
- **查看邮箱**: `ls ~/.workbuddy/skills/boss-secretary/reports/`

---

## 新增: 价格-情绪背离检测 (v2.3 回测落地)

> **P04提案验证通过 | 监控FGI与价格背离**

### 背离定义

| 类型 | 条件 | 信号 |
|:-----|:-----|:-----|
| 正背离 | 价格涨+FGI不涨 | 机构吸筹预警 🟡 |
| 负背离 | 价格跌+FGI不跌 | 机构出货预警 🟠 |
| 极度背离 | 价格涨+FGI下降 | 即将回调预警 🔴 |

### 检测阈值

```
背离强度 = |price_change_pct - fgi_change| / fgi_change

- 强度 < 0.5: 无背离
- 强度 0.5-1.0: 轻度背离
- 强度 1.0-2.0: 中度背离 → 警告
- 强度 > 2.0: 极度背离 → 阻断
```

### 信号触发规则

```python
# 正背离场景 (机构吸筹)
if price_24h_change > 0.05 and fgi_change < 0.1:
    alert("POSITIVE_DIVERGENCE", level="WARNING")
    # 建议: 谨慎追多，等待回踩

# 极度背离场景 (即将回调)
if price_24h_change > 0.08 and fgi_change < 0:
    alert("EXTREME_DIVERGENCE", level="CRITICAL")
    # 建议: 平多/开空，止损设在近期高点
```

### 整合到信号评分

- 背离信号作为"情绪维度"的修正因子
- 正背离时降低追多信号权重
- 极度背离时触发交易阻断
- 假阳性率超过40%时告警

### 落地参数 (回测验证)

```yaml
divergence_threshold_mild: 0.5
divergence_threshold_moderate: 1.0
divergence_threshold_extreme: 2.0
false_positive_alert: 0.40
```

---

---

## §UPL蒸发止损规则 (P001提案落地 | 2026-04-27)

> **P001浮盈蒸发止损**: UPL衰减≥90%+持续30min→强制锁利
> **验证**: shadow_verification_report_20260427_2215.md | **rollback**: ROLLBACK-UPL-DECAY-001

### UPL蒸发止损触发条件

```yaml
UPL_DECAY_TRIGGER:
  条件A: 当前浮盈 ≤ 峰值浮盈 × 10% (蒸发≥90%)
  条件B: 持仓时间 ≥ 2小时 (排除初期波动)
  条件C: Edge < 0 (信号为负)
  
执行等级:
  Level 1 (90%≤蒸发<95%): P1告警 + 建议主动平仓
  Level 2 (95%≤蒸发<99%): P0告警 + 强制评估主动止损
  Level 3 (蒸发≥99%): 自动止损建议 + 写入episode

例外:
  - 当前价格 > 开仓价 → Level降一级
  - FOMC前24h内 → 告警级别+1，不强制执行
冷却期: 同一仓位4h内不重复触发
```

### A6集成: 每轮简报新增UPL_DECAY指标

```yaml
A6_UPL_MONITOR:
  每轮简报必须输出:
    - 峰值浮盈: $XX
    - 当前浮盈: $XX
    - 蒸发比例: XX%
    - 蒸发时长: Xh
    - 当前Level: L1/L2/L3
    - 建议动作: [HOLD/主动平仓/锁利]
```

---

## §Edge加速衰减响应规则 (P002提案落地 | 2026-04-27)

> **P002 Edge加速衰减响应**: dEdge/dt分级触发响应
> **验证**: shadow_verification_report_20260427_2215.md | **rollback**: ROLLBACK-EDGE-ACCEL-002

### Edge加速衰减触发条件

```yaml
EDGE_ACCEL_TRIGGER:
  条件A: d(Edge)/dt < -15/h (Edge每小时恶化超15点)
  条件B: Edge从>-20跌至<-40的时间窗口<3h
  条件C: 连续2次评估Edge均下降且降幅>30%

响应等级:
  Level 1 (dEdge/dt < -15/h):
    - 立即触发A1-A3快速重评估 (跳过正常队列)
    - SI_Index强制刷新 (不等下一周期)
    
  Level 2 (dEdge/dt < -25/h OR Edge < -40):
    - 触发P0告警: 信号正在加速恶化
    - 强制评估当前仓位是否需要立即减仓
    - 通知用户 (非静默处理)
    
  Level 3 (Edge < -50):
    - 自动建议全部平仓至≤0.05张或空仓
    - 写入紧急episode
    - 阻止任何新的BUY操作 (至少4h冷却)

Edge_Vel指标:
  计算: (Edge_current - Edge_prev) / (time_current - time_prev)
  单位: 点/小时
  阈值:
    正常: -5 ~ +5/h
    注意: -15 ~ -5/h 或 +5 ~ +15/h
    警告: <-15/h 或 >+15/h
    危急: <-25/h 或 >+25/h
```

### A6集成: 每轮简报新增Edge_Vel指标

```yaml
A6_EDGE_MONITOR:
  每轮简报必须输出:
    - Edge当前值: XX
    - Edge前一值: XX
    - Edge_Vel: X点/h
    - 当前Level: L1/L2/L3
    - 4h内恶化幅度: XX点
    - 建议动作: [监控/强制评估/建议减仓]
```

### 风险发现SLA (P002新增)

```yaml
RISK_FACTOR_SLA:
  新风险因子发现到纳入Edge计算: ≤1h
  SI_Index重新评估周期: 当|Edge|>20时从4h→2h
  做梦洞察→A6响应延迟: ≤90min
```

---

## §信号质变分级响应SLA (P003提案落地 | 2026-04-26)

> **P003费率质变SLA**: 区分"量变信号"(渐进)和"质变信号"(突变)，对质变信号设置更短SLA
> **rollback**: ROLLBACK-DREAM-PROPOSAL-20260426-003

### 质变信号判定标准 (Q1-Q4):

| 代码 | 条件 | 类型 |
|:---|:---|:---|
| **Q1** | 费率从负转正 (零轴穿越) | 质变 |
| **Q2** | 费率日变化幅度 > 200% (如从-0.001%→+0.004%) | 质变 |
| **Q3** | Regime状态切换 (如RANGE_BOUND→TREND_STRONG) | 质变 |
| **Q4** | FGI单日变化 > 20点 (L_FGI_001已有此规则) | 质变 |

### 量变信号判定 (V1-V3):

| 代码 | 条件 | 类型 |
|:---|:---|:---|
| **V1** | 费率收窄/扩大但不穿零轴 | 量变 |
| **V2** | 价格在区间内波动 | 量变 |
| **V3** | FGI每日微调 <10点 | 量变 |

### SLA响应规定:

| 信号类型 | 响应SLA | 动作要求 |
|:---|:---|:---|
| **质变信号(Q)** | ≤4小时 | A4必须在4h内评估并输出建议仓位 |
| **量变信号(V)** | ≤8小时 | A4在下次轮次中评估即可 |
| **P0告警** | ≤1小时 | A5必须在1h内响应(已有规则) |

### A6质变标记职责:

```yaml
# A6检测到质变信号时必须:
1. 立即在简报中标记 [QUALITY_SHIFT_Q{n}]
2. 跳过常规的"观察确认"步骤
3. 直接向A4发送加速评估请求（含信号详情+SLA计时）
4. A4必须在SLA内(4h)输出:
   a. 是否确认质变 (CONFIRM/DENY)
   b. 确认后的推荐仓位 (按SIGNAL-POSITION-MATRIX)
   c. 止损位 + 入场价位
5. SLA超时未响应 → 自动升级为P1告警
```

### 质变信号加速通道 (QUALITY-SHIFT-FAST-TRACK):

```
触发条件: A6检测到Q1-Q4任一质变信号
执行流程:
  1. A6立即标记 [QUALITY_SHIFT_Q{n}]
  2. A6跳过"观察2轮"等待期
  3. A6直接触发A4评估请求
  4. A4输出CONFIRM/DENY + 仓位建议 + 止损位
  5. SLA计时开始: 质变检测时刻 → 4h截止
  6. 超时 → A6自动升级为P1告警
```

### 监控维度增强:

在现有监控维度中追加质变检测:

| 维度 | 指标 | 阈值 | 告警级别 |
|:---|:---|:---|:---|
| ⭐ **费率翻转** | Funding翻转(负→正) | Q1质变 | 🔴HIGH + [QUALITY_SHIFT_Q1] |
| ⭐ **费率质变** | 日变化>200% | Q2质变 | 🔴HIGH + [QUALITY_SHIFT_Q2] |
| ⭐ **Regime切换** | 状态机重大转换 | Q3质变 | 🔴HIGH + [QUALITY_SHIFT_Q3] |
| ⭐ **FGI突变** | 单日变化>20点 | Q4质变 | 🔴HIGH + [QUALITY_SHIFT_Q4] |

### 情报简报增强格式:

当检测到质变信号时，在情报简报中追加:

```yaml
## ⚡ 质变信号检测 [QUALITY_SHIFT]

### 信号摘要:
| 项目 | 值 |
|:---|:---|
| 质变类型 | Q{n}: [描述] |
| 检测时间 | YYYY-MM-DD HH:MM |
| SLA截止 | YYYY-MM-DD HH:MM (+4h) |
| 信号强度 | [描述] |
| 关联信号 | [如有] |

### SLA状态:
- [ ] A4评估请求已发送
- [ ] A4确认/否认待返回
- [ ] SLA倒计时: Xh Ym

### A4响应要求:
响应截止时间: SLA截止前30min
必须输出:
  1. CONFIRM/DENY: [质变是否确认]
  2. 推荐仓位: [X张 / %]
  3. 入场价位: [$XX,XXX]
  4. 止损价位: [$XX,XXX]
```

---

## §清算价计算模块 (P006提案落地 | 2026-04-25)

> **P006清算价公式修正**: frozen→equity + sanity check
> **验证**: dream_verification_20260425.md §P0验证 | **rollback**: ROLLBACK-DREAM-006-20260425

### 清算价计算函数 v2.0

```python
def calculate_liquidation_price(position_info, account_info):
    """
    计算清算价 - 使用正确的权益口径
    
    ⚠️ L_LIQ_EQUITY口径: 必须使用avail_equity (available margin)
    ❌ NOT: total_equity (包含unrealized P&L)
    ❌ NOT: frozen margin only
    
    Args:
        position_info: {size, avg_price, leverage, side, unrealized_pnl}
        account_info: {total_equity, avail_equity, frozen_margin, usdt_available}
    
    Returns:
        liquidation_price: float
        calculation_method: str (用于审计追溯)
    """
    # ★ 核心修正: 使用 avail_equity 作为风险缓冲
    risk_buffer = account_info['avail_equity']
    
    if position_info['side'] == 'long':
        # 多头清算价 = 入场价 * (1 - 风险缓冲 / (仓位价值))
        liq = position_info['avg_price'] * (
            1 - risk_buffer / (position_info['size'] * position_info['contract_value'])
        )
    else:
        # 空头清算价 = 入场价 * (1 + 风险缓冲 / (仓位价值))
        liq = position_info['avg_price'] * (
            1 + risk_buffer / (position_info['size'] * position_info['contract_value'])
        )
    
    return {
        'price': round(liq, 2),
        'method': 'L_LIQ_EQUITY_AVAIL',  # 审计字段: 标注使用的计算方法
        'risk_buffer_source': 'avail_equity',
        'risk_buffer_amount': risk_buffer,
        'sanity_check': _sanity_check_liq_price(liq, position_info['avg_price'], position_info['side'])
    }


def _sanity_check_liq_price(liq_price, entry_price, side):
    """清算价数值合理性校验"""
    deviation_pct = abs(liq_price - entry_price) / entry_price * 100
    
    warnings = []
    
    # 清算价偏离入场价超过20%通常意味着计算错误
    if deviation_pct > 20:
        warnings.append(f"⚠️ LIQ_SANITY_001: 清算价偏离入场价{deviation_pct:.1f}%, 可能存在计算错误")
    
    # 多头: 清算价应低于入场价; 空头: 清算价应高于入场价
    if side == 'long' and liq_price > entry_price:
        warnings.append("🔴 LIQ_SANITY_002: 多头清算价高于入场价! 公式方向错误")
    elif side == 'short' and liq_price < entry_price:
        warnings.append("🔴 LIQ_SANITY_002: 空头清算价低于入场价! 公式方向错误")
    
    return {
        'passed': len([w for w in warnings if w.startswith('🔴')]) == 0,
        'deviation_pct': round(deviation_pct, 2),
        'warnings': warnings
    }
```

### A6情报报告增强

每次产出intelligence_briefing时追加:
```yaml
# === P006新增: 清算价计算元数据 ===
liquidation_metadata:
  calculation_method: "L_LIQ_EQUITY_AVAIL"
  risk_buffer: "$X,XXX (avail_equity)"
  sanity_check: "PASSED" | "FAILED: [具体警告]"
  last_verified: "YYYY-MM-DD HH:MM"
```

---

## §A1-A3战略输出质量审计 (P005提案落地 | 2026-04-25)

> **P005 A1-A3审计**: 检测战略僵化 & 连续一致输出
> **验证**: dream_verification_20260425.md §P2验证 | **rollback**: ROLLBACK-DREAM-005-20260425

### A1-A3 输出质量检测器 v1.0

```
┌─────────────────────────────────────────────────────────────┐
│  A1-A3 输出质量检测器 v1.0                                   │
│  目标: 检测战略僵化 & 连续一致输出                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  🔍 检测指标:                                               │
│  ─────────────────                                          │
│                                                             │
│  ① 连续一致性检测:                                         │
│     - 连续 N≥4 天输出相同决策(SKIP/HOLD)                    │
│     - 触发 → 标记 "STRATEGIC_RIGIDITY_WARNING"              │
│     - 上报 A6 → 强制 A1-A3 附加"反事实分析"                  │
│                                                             │
│  ② 信号-决策背离检测:                                       │
│     - 当正向信号数量 ≥ 2 且 决策 = SKIP                      │
│     - 触发 → 标记 "SIGNAL_DECISION_DIVERGENCE"             │
│     - 要求 A3 在报告中显式解释"为什么有信号但不行动"          │
│                                                             │
│  ③ 历史对比检测:                                            │
│     - 当前 Regime 与过去 30 天相同 Regime 的历史决策对比      │
│     - 如果历史显示该 Regime 下正期望值行动存在                │
│     - 但当前选择不行动 → 标记 "HISTORICAL_ANOMALY"          │
│                                                             │
│  ⚡ 自动响应规则:                                           │
│  ─────────────────                                          │
│  • STRATEGIC_RIGIDITY (连续4天+):                          │
│    → A6在下一轮情报中添加"A1-A3审计提醒"段落                │
│    → 要求A1提供"替代方案"                                   │
│                                                             │
│  • SIGNAL_DECISION_DIVERGENCE (信号≥2但SKIP):              │
│    → A3必须在战略报告中新增"忽略信号理由"字段               │
│    → 不能用"Regime不支持"笼统解释，必须逐信号回应            │
│                                                             │
│  • HISTORICAL_ANOMALY (历史对比异常):                       │
│    → 触发 A2 第一性原理深度分析                             │
│    → "当前环境和历史环境到底有什么不同？"                     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### A3 报告格式增强

当 action=SKIP 时，A3报告必须包含:
```yaml
directive:
  action: SKIP
  primary_reason: "Regime=RANGE_BOUND"
  
  # === P005新增: skip_justification ===
  skip_justification:
    signals_ignored:
      - signal: "[信号描述]"
        ignore_reason: "[忽略理由]"
        strength: HIGH|MEDIUM|LOW
        counter_argument: "[反驳理由或null]"
    
    alternative_scenario:
      - if_action: "[备选行动]"
        expected_pnl_range: "[预期盈亏]"
        risk_amount: "[风险敞口]"
        probability_assessment: "[概率评估]"
    
    consistency_check:
      consecutive_skip_days: N
      historical_same_regime_outcome: "[历史结果]"
    rigidity_warning: "⚠️ 已连续N天输出SKIP"
```

### P1/P2检测增强 (新增战略僵化信号)

在现有P1/P2触发条件中追加:
```yaml
# P1新增
STRATEGIC_RIGIDITY_WARNING:
  - consecutive_skip_days >= 4
  - action: "A6在情报中追加审计提醒段落"

# P2新增
SIGNAL_DECISION_DIVERGENCE:
  - positive_signals >= 2 AND action == SKIP
  - action: "要求A3逐信号解释"

HISTORICAL_ANOMALY:
  - regime_same_as_history BUT action_different
  - action: "触发A2深度分析"
```

---

## §周末Gap三情景预案 (P001提案落地 | 2026-04-25)

> **P001 Gap预案**: 周末Gap三情景预案机制
> **验证**: dream_verification_20260425.md §P0验证 | **rollback**: ROLLBACK-DREAM-001-20260425

### Gap预案触发条件

- **触发时间**: 周五15:00-17:00
- **前置条件**: 当前持仓≤10%
- **产出截止**: 周五17:30

### 三情景预案模板

```
┌─────────────────────────────────────────────────────────────┐
│  周末Gap三情景预案 v1.0                                      │
│  触发条件: 周五15:00-17:00 且 当前持仓≤10%                    │
│  产出截止: 周五17:30                                         │
├──────────┬──────────────┬────────────────┬───────────────────┤
│ 情景      │ 触发条件       │ 预设行动         │ 仓位/止损         │
├──────────┼──────────────┼────────────────┼───────────────────┤
│ A: Gap Up │ 周一开盘>+1.5% │ 不追多! 等回踩   │ 若回踩至突破点附近→ │
│          │              │ 至$78,400-$78,600│ 小仓试多2-3%      │
│          │              │                │ 止损: 入场价-2%     │
├──────────┼──────────────┼────────────────┼───────────────────┤
│ B: Gap Flat│ 开盘±1%内    │ 区间下部建底仓   │ $77,000-$77,500 →│
│          │ $77K-$78.6K  │                │ LONG 2-3%         │
│          │              │                │ 止损: $76,900      │
├──────────┼──────────────┼────────────────┼───────────────────┤
│ C: Gap Down│ 开盘<-2%     │ 评估做空机会     │ 若跌破$77,000且  │
│          │ <$75,800     │ (例外激活)      │ 结构完好→SHORT 2-3% │
│          │              │                │ 止损: 入场价+1.5%   │
│          │              │                │ ⚠️ 待P002落地后激活 │
└──────────┴──────────────┴────────────────┴───────────────────┘
```

### T5-b触发条件新增 (A4 SKILL)

> **T5-b: 周末前无Gap预案** — 当时间为周五14:00+且当前空仓/低仓(<10%)且不存在有效gap_scenario_plan时，A4应触发A6重启A1-A3以紧急生成预案。

---

## §A4 T5触发条件补充 (P001联动)

> **T5-b新增**: 周末前无预案触发
> **落地时间**: 2026-04-25

### T5-b子条件

**触发条件**:
- 时间: 周五14:00-17:00
- 持仓: 空仓或 <10%
- gap_scenario_plan: 不存在或已过期

**响应动作**:
1. 标记 "WEEKEND_GAP_PLAN_MISSING"
2. 上报A6，请求紧急生成预案
3. A6判定链路深度(建议Level 2: A3-A5)

---

## 16. SI_Index 信号强度监控 (v4.3新增)

### 16.1 信号强度追踪

A6需要持续追踪SI_Index的日度变化：

```
【A6每日SI_Index追踪】
si_index_daily:
  date: "YYYY-MM-DD"
  positive_signals: [list of active positive signals]
  negative_signals: [list of active negative signals]
  si_index: "+55"
  si_grade: "STRONG_BULL"
  position_taken: "0.1张"
  position_recommended: "0.8张"
  gap_ratio: "8x"
  alert_level: "ALERT"  # 1-3x=INFO, 3-5x=WARN, 5-10x=ALERT, >10x=P0
```

### 16.2 信号强度告警规则

| 差距倍数 | 告警级别 | A6动作 |
|:---:|:---:|:---|
| 1-3x | INFO | 正常记录 |
| 3-5x | WARN | A6检查仓位同步 |
| 5-10x | ALERT | 人工确认 + 建议补仓 |
| >10x | P0 | 强制评审 + 记录教训 |

**04-26告警**：差距=8x → ALERT级别

### 16.3 信号里程碑检测

| 里程碑 | 条件 | A6动作 |
|:---|:---|:---|
| 最强信号日 | SI_Index > 历史最高 | 记录 + 分析 |
| 信号转折日 | SI翻正/翻负 | 上报 + 重评 |
| 信号持续日 | 同向信号连续3天 | 仓位累积提示 |

### 16.4 做梦洞察落地追踪

A6需要追踪做梦洞察中的仓位建议是否被采纳：

```
【做梦洞察落地追踪】
oneirology_insight:
  date: "04-26"
  insight: "04-26是8天最强信号日(4正向+0负向+费率翻转)"
  recommended_position: "0.8张"
  actual_position: "0.1张"
  gap: "8x"
  action: "记录为进化里程碑"
```

### 16.5 仓位进化进度追踪

| 进化阶段 | 状态 | 完成时间 |
|:---|:---:|:---|
| Phase 1: SI_Index量化 | ✅ 完成 | 2026-04-26 |
| Phase 2: A4→A5同步协议 | ✅ 完成 | 2026-04-26 |
| Phase 3: A6信号监控 | 🔄 进行中 | 2026-04-26 |
| Phase 4: 回测验证 | ⏳ 待开始 | 2026-04-27 |
| Phase 5: 实战部署 | ⏳ 待开始 | 2026-04-28 |

---

*P情报监控协议更新 | v4.3 | 2026-04-26 SI_Index信号强度监控 + 仓位进化追踪*

## 版本历史

| 版本 | 日期 | 变更内容 |
|:---|:---:|:---|
| v4.3 | 2026-04-26 | SI_Index信号强度监控 + 仓位进化进度追踪 |
| v4.2 | 2026-04-26 | **宏观资产池监控**（黄金/原油/铜/TSLA/COIN）+ **宏观共振信号输出** + 多资产OKX CLI命令 |
| v4.1 | 2026-04-25 | **P006清算价修正** + **P005 A1-A3审计** + **P001周末Gap预案** |
| v4.0 | 2026-04-25 | A6双轨触发(A4上报) + A4→A6→A1-A3完整闭环 |
| v3.2 | 2026-04-22 | **双系统独立触发**: 技术信号与事件信号任一即触发 |
| v3.1 | 2026-04-22 | 三屏MA趋势监控(周/日/1H)+三维向量+技术信号分级 |
| v3.0 | 2026-04-22 | A6记忆账本+P0/P1分级响应(5级)+方向一致性判定 |
| v2.5 | 2026-04-22 | 修正为串行链路，强调产物消费+交易邮箱投递 |
| v2.4 | 2026-04-22 | P0级直接调用A1-A5链路(串行依赖) |
| v2.3 | 2026-04-22 | 价格-情绪背离检测落地 |
| v2.1 | 2026-04-21 | 搜索优先级策略优化 |
| v2.0 | 2026-04-20 | 双账户持仓监控强化 |

---

## 17. SI_Index 自动化监控 (v4.3新增)

### 17.1 自动化监控配置

A6可以使用自动化脚本进行SI_Index实时监控和告警：

```bash
# 运行SI_Index监控（获取当前状态）
python3 scripts/si_index_automation.py --mode automation --symbol BTC-USDT-SWAP --dry-run

# 输出示例:
# SI_Index: +55
# 分级: STRONG_BULL
# PTSD: 04-23创伤，降级0.5x
# 建议仓位: 0.32张
```

### 17.2 监控指标

| 指标 | 告警阈值 | 动作 |
|:---|:---|:---|
| SI_Index变化 | ±15 | A6记录 |
| 仓位差距 | >5x | ALERT |
| PTSD触发 | 是 | 降仓50% |
| 新信号出现 | 是 | 重新计算 |

### 17.3 自动化报告输出

自动化脚本输出JSON格式报告，可供A6直接消费：

```json
{
  "timestamp": "2026-04-26T22:30:00Z",
  "symbol": "BTC-USDT-SWAP",
  "si_index": 55,
  "grade": "STRONG_BULL",
  "position_coefficient": 0.8,
  "pstd_adjustment": 0.5,
  "final_position": 0.32,
  "decision": "BUY",
  "adjustment": 0.27
}
```

### 17.4 A6自动化任务中调用SI_Index系统 (v4.3.1新增 · 2026-04-26)

> **架构定位**：A6 每2小时自动化运行一次 → 评估市场综合信号 → 超阈值才调用 SI_Index → SI_Index 触发 A5

```
┌─────────────────────────────────────────────────────────────────────────┐
│         A6自动化运行 → SI_Index → A5 完整链路 (v4.3.1)                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  【Step 1: A6自动化任务触发】                                            │
│  └── 每2小时自动运行，执行标准监控流程                                 │
│                          ↓                                              │
│  【Step 2: A6自主综合评估】                                              │
│  ├── 三屏信号分析（周线/日线/小时线方向/斜率/加速度）                │
│  ├── 基本面验证（A1-A3结论是否矛盾）                                    │
│  ├── 资金费率状态 + FGI + 宏观共振                                     │
│  └── 确定性评估: WEAK / MODERATE / STRONG / VERY_STRONG              │
│                          ↓                                              │
│  【Step 3: 阈值判断 — 是否调用SI_Index】                               │
│  ├── A6确定性 = WEAK → 不调用SI_Index，本次结束                      │
│  └── A6确定性 ≥ MODERATE → 调用SI_Index计算                          │
│                          ↓                                              │
│  【Step 4: 调用SI_Index计算】                                           │
│  ├── 脚本: `python3 scripts/si_index_automation.py --dry-run`         │
│  ├── 获取: SI_Index分值 + 分级 + 仓位建议                             │
│  └── 记录: 写入情报简报 si_index_result 字段                          │
│                          ↓                                              │
│  【Step 5: SI_Index阈值判断 — 是否触发A5】                             │
│  ├── SI_Index ≥ +15 (BUY方向) → 触发A5请求加仓                       │
│  ├── SI_Index ≤ -15 (SHORT方向) → 触发A5请求做空                      │
│  └── |SI_Index| < 15 → 不触发A5，本轮结束                             │
│                          ↓                                              │
│  【Step 6: 触发A5执行】                                                 │
│  ├── 构造仓位同步请求（传递A6评估结果 + SI_Index结果）               │
│  ├── 传递: A6三屏分析 + SI_Index分值 + 目标仓位                       │
│  └── use_skill("dream-tactical-executor") 调用A5                     │
│                                                                         │
│  ⚠️ 注意: A6和A4独立评估，互不依赖。两者的SI_Index结果可以同时触发A5  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

**阈值参数**：

| 参数 | 值 | 说明 |
|:---|:---:|:---|
| SI_Index 调用阈值 | ≥ MODERATE | A6确定性≥MODERATE才调用SI_Index |
| A5 触发阈值(做多) | ≥ +15 | SI_Index ≥ +15 才触发做多 |
| A5 触发阈值(做空) | ≤ -15 | SI_Index ≤ -15 才触发做空 |
| A5 强烈触发(做多) | ≥ +30 | SI_Index ≥ +30 → 建议大仓(30-40%) |
| A5 强烈触发(做空) | ≤ -20 | SI_Index ≤ -20 → 建议大仓(20-30%) |

**调用示例**：

```bash
# A6自动化任务末尾，监控流程完成后执行
python3 scripts/si_index_automation.py --mode automation --symbol BTC-USDT-SWAP --dry-run

# 预期输出:
# SI_Index: +55
# 分级: STRONG_BULL
# PTSD: 04-23创伤，降级0.5x
# 建议仓位: 0.32张
# → 触发A5请求补仓至0.32张
```

**A6情报简报SI_Index字段（必须包含）**：

```yaml
si_index_result:
  triggered: true  # SI_Index是否被调用
  a6_confidence: "STRONG"  # A6自身确定性
  si_index: +55
  grade: "STRONG_BULL"
  position_coefficient: 0.8
  pstd_adjustment: 0.5
  final_position: 0.32
  a5_triggered: true  # 是否触发A5
  trigger_reason: "SI_Index=+55 ≥ +15阈值，A6三屏BULL共振"
```

### 17.5 A6与A4的SI_Index关系

> **重要说明**：A6和A4独立运行，各自评估，各自调用SI_Index

| 对比项 | A4 (dream-tactical-validator) | A6 (dream-intelligence-monitor) |
|:---|:---|:---|
| 触发频率 | 每4小时 | 每2小时 |
| 评估角度 | A4侦察结果 + 市场试探反馈 | 三屏技术 + 宏观 + 资金费率 |
| 评估重点 | "A4的试探是否值得放大？" | "市场整体信号是否足够强？" |
| SI_Index调用条件 | A4置信度≥MODERATE | A6确定性≥MODERATE |
| A5触发条件 | SI_Index ≥ +15 或 ≤ -15 | SI_Index ≥ +15 或 ≤ -15 |
| 独立性 | 独立评估，不依赖A6 | 独立评估，不依赖A4 |
| 共存 | 可以同时触发A5 | 可以同时触发A5 |

**两者同时触发A5的处理**：
- 优先采用 SI_Index 分值更高的触发源
- 如分值接近，取平均值作为目标仓位
- A5收到请求后自行执行门禁检查（§2五大约束）



---

## ⚠️⚠️⚠️ Level 1.5 强制输出段 (v4.6 必填 - 每轮简报必须包含!)

> **P0 级强制要求 (2026-04-28 A8修复确认)**:
> 以下 Level 1.5 SIGNIFICANT_SHIFT 检查结果是**每轮情报简报的必填项**。
> 即使未触发，也必须输出 NO_TRIGGER + 原因。**缺少此段 = A6执行不完整 = A8应标记FAIL**

### 情报简报必须包含的 Level 1.5 段

在情报简报的 **Edge评估段落后方**，必须追加：

```markdown
## Level 1.5 SIGNIFICANT_SHIFT 检查结果 (v4.6 强制)

| 字段 | 值 |
|:---|:---|
| executed | true (是否运行了L1.5) |
| triggered | false / true |
| trigger_condition | null / T1 / T2 / T3 / T4 |
| delta_SI | X.X |
| delta_Edge | X.X |
| 距上次A2更新 | X.Xh / 无记录 |
| 防抖结果 | PASS / FAIL |
| action | NO_ACTION / TRIGGER_A2_INCREMENTAL_UPDATE |
```

### AI Agent 自检清单 (每轮输出前确认)

- [ ] executed = true
- [ ] delta_SI 和 delta_Edge 有实际数值
- [ ] triggered=false 时 no_trigger_reason 已填写
- [ ] triggered=true 时 trigger_condition 标注了T1/T2/T3/T4

> 缺少此段的简报视为 A6 执行失败，A8 应标记为 L1_5_MISSING

### 投递后验证（强制调用AD SKILL）

完成秘书邮箱投递后，必须调用 `artifact-alignment-manager` SKILL 执行双通道验证：

1. **调用方式**: 触发词「产物投递验证」或加载 `artifact-alignment-manager` SKILL
2. **验证内容**:
   - ✅ 秘书邮箱文件存在 + frontmatter完整（含 tags, by_a_phase）
   - ✅ 前端产物中心文件存在（`~/.workbuddy/artifacts/trading/`）
   - ✅ `index.json` 已更新（含 `chain_phase` + `tags`）
   - ✅ 前端详情页返回 200
3. **不通过**: 按 AD SKILL 第四章步骤修复，重新验证
4. **通过**: 投递完成

> ⚠️ 没有 AD SKILL 验证通过 = 投递未完成

