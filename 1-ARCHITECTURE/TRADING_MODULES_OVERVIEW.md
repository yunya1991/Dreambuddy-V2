# Dreambuddy V2 交易模块全景文档

> **版本**: v1.2 | **更新**: 2026-07-08
> **用途**: 快速了解各交易模块的设计目标、架构和运行方式，便于后期维护
> **最后全链路验证**: 2026-07-08（发现并修复3个Bug，记录1个已知问题）

---

## 全链路检查结果（2026-07-08）

| 模块 | 状态 | 备注 |
|------|------|------|
| Agent A 主链路 | ✅ 正常（LLM决策+离场+记忆+进化参数） | 执行失败见 Bug 1 |
| Agent B 主链路 | ✅ 正常（BAC三层+动态链+图压缩+记忆闭环）| 正常成交 |
| data_server :8765 | ✅ 正常 | 需从 `experiments/ab-trading/` 目录启动 |
| bridge_server :3847 | ✅ 正常 | 35模块 + 11节点（已修复自动加载）|
| 经典指标系统 :8092 | ✅ 正常 | Flask，正在处理信号 |
| 三层进化调度器 | ✅ 正常 | 独立进程，三层均完成一次运行 |
| report_loader | ✅ 已修复 Bug 3 | A1日报格式兼容新旧两种结构 |
| 三屏马丁 | ⚠️ OKX CLI 未安装 | 见 Bug 4 |
| 易经推理接口 | ✅ 正常 | ab_bridge 返回 141 条 bus_stats |
| 前端 :3000 | ✅ 启动（Next.js dev）| 需 nvm 环境 |
| 基本面系统 :9094 | ❌ Python 3.9 不兼容 | 需 Python 3.11+ |

### 发现的 Bug

| # | Bug | 影响 | 状态 |
|---|-----|------|------|
| Bug 1 | Agent A API Wallet 未授权：`0x3F5796...` 未在 Hyperliquid app 做 Enable API Wallet | 执行下单报错 `does not exist` | ⚠️ 待手动在 app 授权 |
| Bug 2 | 文档错误：`load_weekly_report()` → 实际函数名为 `load_weekly()` | 文档误导 | ✅ 已修正文档 |
| Bug 3 | `report_loader.load_a1_daily()` 期望旧格式（`market_regime` 嵌套字典），实际 A1 研报为新格式（顶层 `regime`/`si_index` 整数等） | A1日报加载失败，三屏系统获取不到 Screen2 战术数据 | ✅ 已修复（兼容新旧两种格式）|
| Bug 4 | OKX CLI（`okx` 命令）未安装，三屏系统 Screen1/2 依赖此工具 | 三屏引擎无法获取 K 线数据，`compute_screen1()` 返回空 | ⚠️ 需安装 `@okx_ai/okx-trade-cli` |

### 启动命令

```bash
cd /Users/luke.zhang/dream-v2/experiments/ab-trading

# 基础服务
python3 data_server.py &                              # 监控 :8765
BRIDGE_PORT=3847 python3 bridge_server.py &           # TS桥接 :3847

# 经典指标系统（独立）
cd /Users/luke.zhang/dream-v2/10-经典指标系统
python3 ml_trade_service.py &                         # :8092

# 进化调度器（独立）
cd /Users/luke.zhang/dream-v2/experiments/ab-trading
python3 evolution_scheduler.py &

# 前端（需 nvm 环境）
cd /Users/luke.zhang/dream-v2/3-FRONTEND/dream-universal-gateway
export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh"
pnpm dev &                                            # :3000
```

---

## 目录

1. [AB实验总体说明](#一ab实验总体说明)
2. [Agent A — LLM 原生驱动](#二agent-a--llm-原生驱动对照组)
3. [Agent B — Dreambuddy 框架验证](#三agent-b--dreambuddy-框架验证实验组1)
4. [Agent C — DreamOS 内核驱动](#四agent-c--dreamos-内核驱动实验组2)
5. [三屏马丁交易系统](#五三屏马丁交易系统独立)
6. [易经推理交易系统](#六易经推理交易系统独立仓库)
7. [三层进化系统](#七三层进化系统)
8. [关键文件索引](#八关键文件索引)

---

## 一、AB实验总体说明

```
实验目的: 验证"系统框架（Dreambuddy OS）"是否比"LLM原生推理"带来超额收益

三组对比实验:
  Agent A (对照) ─── 纯 LLM 驱动，无系统框架
  Agent B (实验) ─── Dreambuddy 图架构 + A0-A9 SKILL 框架
  Agent C (实验) ─── DreamOS SACG 四层内核驱动（独立于B）

公共底座:
  执行层:  execution/aster_spot.py (Hyperliquid EIP-712 签名下单)
  记分:    scoring/scorecard.py (决策日志)
  调度:    orchestrator.py (15分钟心跳 + 事件驱动，常规间隔1H)
  监控:    data_server.py (port:8765) + monitor.html
  桥接:    bridge_server.py (port:3847, FastAPI, 35模块+11节点)
```

---

## 二、Agent A — LLM 原生驱动（对照组）

### 设计目标
不依赖任何系统框架，让 LLM 直接作为"交易大师"做决策，验证原始 LLM 智能的边界。

### 完整执行流程（9步）

```
Step 1: 加载记忆
  ├── 当前大师风格（Jesse Livermore / Jones / Dennis 等）
  ├── Lessons（历史教训，按 普适性×重要性 评分淘汰）
  ├── 进化参数（evolution_engine 已采纳的参数，动态调整策略阈值）
  └── 连胜/连败/最大回撤统计

Step 2: 账户状态
  ├── 实盘模式（Hyperliquid API）
  └── 模拟模式（账户不可用时自动降级，使用 peak_equity 作虚拟资金）

Step 2.5: L1 离场检查（exit_module.run_exit_check）
  ├── ATR 动态止损（入场时自动计算，持续跟踪）
  ├── 移动止损（浮盈超阈值后上移止损锁利）
  └── 触发则平仓并记录 closed_trade

Step 2.6: 最大回撤保护
  └── 回撤≥15% → 强制 HOLD，暂停交易

Step 3: 扫描市场（20个标的）
  └── 采集K线 + 技术指标（EMA20/50/200, RSI14, 量比）

Step 4: LLM 决策（三级回退，SKILL框架驱动）
  1. Trae (trae.ai, claude-sonnet-4-5) — 免费额度，优先
     配额: 12次/天 (AGENT_A_TRAE_DAILY_LIMIT)
  2. DeepSeek V4 (deepseek-chat) — 付费备用
     配额: 24次/天 (AGENT_A_DEEPSEEK_DAILY_LIMIT)
  3. 规则引擎 — 硬编码兜底（0 Token，使用进化参数动态调整阈值）

  LLM 输入: 市场数据 + 记忆（Lessons+大师+进化参数）+ SKILL.md框架
  LLM 输出: action/coin/leverage/confidence/SL/TP/new_lesson/master_switch

Step 4.1: 连续HOLD保护
  └── ≥10轮 HOLD → _break_conservative_loop() 降低入场门槛强制寻找机会

Step 4.2: 连败保护
  └── ≥3次连败 → 强制本轮 HOLD

Step 4.5: L2 智能离场（LLM 主动建议）
  ├── exit_suggestions: LLM 建议平仓某持仓 → execute_exit()
  └── update_exit_levels: LLM 调整止损止盈价位

Step 5: 执行交易
  ├── open_long / open_short（Hyperliquid 市价单）
  └── 开仓成功 → init_position() 初始化 L1 止损跟踪

Step 6: 记录决策日志（DecisionLog）
  └── 包含: provider/master/top_lessons/active_positions/smart_exits

Step 7: 更新记忆
  ├── add_lesson()：写入新 Lesson（含评分，低分自动淘汰）
  ├── record_trade()：记录本次交易
  ├── maybe_switch_master()：根据 regime 评估是否切换大师
  └── update_hold_streak()：更新连续HOLD计数

Step 8: 自主调度（申请提前触发）
  ├── 高置信度信号(≥75%) → 1H后复查
  ├── 成交量异常(>2.5x) → 2H后复查
  ├── 连败≥3次 → 6H后强制复盘
  └── 置信度接近门槛(58-65%) → 1H后再试

Step 9: GitHub PR 评论同步（可选）
  └── 需配置 GITHUB_TOKEN + GITHUB_REPOSITORY + PR_NUMBER
```

### LLM 决策框架（SKILL）

Agent A 有专用 SKILL 文件：`skills/agent-a-trading/SKILL.md`

六维决策框架（每轮必走）：
```
目标 → 身份定位 → 三维分析 → 自我进化 → 向外学习 → 预算管理
       (当前大师)  技术+微观   LLM生成   外部信号   Token控制
                  +宏观跨市    Lesson
```

### 大师体系
| 大师 | 风格 | 切换触发 |
|------|------|----------|
| Jesse Livermore | 趋势跟踪（默认） | 初始 |
| Paul Tudor Jones | 宏观反转 | 连亏3次+震荡市 |
| Richard Dennis | 海龟系统 | 错过趋势行情 |
| Stanley Druckenmiller | 高确信押注 | 宏观信号极强 |

切换条件：`maybe_switch_master()` 根据 regime 自动判断

### 关键配置
```
账户:   AGENT_A_ASTER_USER=0x93842F1ea62E7E3c71494d9EA69EfC4F2D6e9934
入口:   agents/agent_a_runner.py
SKILL:  skills/agent-a-trading/SKILL.md
记忆:   data/agent_a_memory.json
配额:   data/agent_a_llm_quota.json
Trae:   TRAE_API_KEY + TRAE_MODEL=claude-sonnet-4-5
币种:   UNIVERSE_A = BTC/ETH/SOL/HYPE/AVAX/ARB/SUI/INJ/LINK/TIA（10个）
```

---

## 三、Agent B — Dreambuddy 框架验证（实验组1）

### 设计目标
验证"意图识别→动态链规划→A0-A9节点执行→图压缩记录→进化"这套完整框架的可行性。

### 完整执行流程

```
Step 1: 加载记忆 + DreamBuddy OS SKILL
  └── SKILL: 1-ARCHITECTURE/skills/dreambuddy-os/SKILL.md
  
Step 2: 账户状态

Step 2.5: A9 离场评估（动态链，按预算选路径）
  full模式:   C1技术 + A9综合(规则+LLM) + F链基本面 + 门禁
  standard:   C1技术 + A9综合 + 门禁
  lean模式:   C1纯代码（零Token，经典指标体系）

Step 3: 意图识别（intent_gateway.py）
  - 6种意图: TREND_FOLLOWING/MEAN_REVERSION/FUNDAMENTAL_PLAY
             BREAKOUT/UNCERTAIN/KNOWLEDGE_MATCH
  - 零Token本地打分（技术面+资金费率+RSI+Regime）
  - LLM策略评估（strategy_eval，每轮，可选三标的/策略类型建议）

Step 4: ChainPlanner 零Token规划（chain_planner.py）
  四维过滤:
    1. Token预算 → full/standard/lean 三档
    2. 知识库命中 → score≥80 升级快捷路径
    3. 历史表现 → 当前Regime+标的命中率
    4. 标的覆盖 → 小币降级/资金费率极端强制F2/F3

Step 5: ChainRouter 动态执行（chain_router.py）
  ├── 基础链必走（C1/F2/F3/A2/A4）
  ├── "一生二"：置信度不足 → 追加扩展节点
  ├── A0矛盾内置于 A2/A3（非独立节点）
  └── A2-LLM保护：LLM≥65%时防止A2规则压制到45%以下

Step 6: A4门禁（≥55%） → LONG/SHORT/HOLD

Step 7: 执行交易

Step 8: 图压缩记录（B/A/C三层）
  B层(Blueprint): 意图目标 + Regime
  A层(Architecture): 节点执行序列 + 置信度
  C层(Chronicle): 最终决策 + 执行结果

Step 9: trading_memory 建议闭环
  └── 生成: 待验证建议/风险建议/BAC调整/D-Z-E建议

Step 10: 自我进化
  └── gap_score → A7/A8治理环 → 做梦部
```

### 三环架构

```
🔵 执行环: A1→A2→A3→A4→A5→A9（A0矛盾内置于A2/A3）
🟠 情报环: A6每1H，5级放射驱动
           L0致命→A9离场 | L1→A4验证 | L1.5变→A2更新
           L2中→观察    | L3背离→A1+A3重启
🟣 治理环: A9离场→A7(实践记录)→A8(知行合一,gap_score路由)
           gap>0.5→A1重启 | gap 0.3-0.5→A2更新 | gap<0.3→A3优化
```

### 关键配置
```
账户:   AGENT_B_ASTER_USER=0x6632da9c91A959eEBf1343f8AFAbf2807414004A
入口:   agents/agent_b_runner.py
SKILL:  1-ARCHITECTURE/skills/dreambuddy-os/SKILL.md
记忆:   data/agent_b_memory.json
图日志: data/agent_b_graph.json
记忆闭环: core/trading_memory.py
门禁:   CONFIDENCE_GATE=0.55（做梦部修正）
币种:   20个（BTC/ETH/SOL/HYPE/UNI/LIT/XRP/ZEC/NEAR/WLD/ADA/SUI等）
```

---

## 四、Agent C — DreamOS 内核驱动（实验组2）

### 设计目标
独立于 Agent B，通过 DreamOS 操作系统的 SACG 四层内核动态调度模块能力完成交易，验证 OS 化调度的价值。与 Agent B 形成第二层对比：**图架构自定义框架 vs DreamOS 标准化OS内核**。

### SACG 四层架构

```
用户触发 / 市场数据
 ↓
S层 (Sense) — 意图识别
  dreamos.core.sense.IntentEngine
  → IntentResult (意图类型 + 置信度 + 推荐链路)
 ↓
A层 (Arrange) — 图编排
  dreamos.core.arrange.GraphPlanner
  → ExecutionPlan（从 NodeRegistry 动态选节点 + 预算分配）
 ↓
C层 (Compute) — 节点执行
  dreamos.core.compute.GraphExecutor
  → 运行注册表节点 + 反射决策（置信度不足 → 重跑或降级）
 ↓
G层 (GraphStore) — 状态存储
  dreamos.shared.state.State
  → 状态快照 + 历史记录 + 上下文压缩
 ↓
共用执行层
  HyperliquidClient（aster_spot.py）
  ← 复用 Agent B 的 Hyperliquid API 配置
```

### 与 Agent B 的核心区别

| 维度 | Agent B | Agent C |
|------|---------|---------|
| 框架来源 | 自定义 intent_gateway + chain_router | DreamOS 标准化 SACG 内核 |
| 节点发现 | 硬编码节点名字符串 | NodeRegistry 动态注册发现 |
| 编排逻辑 | ChainPlanner 规则化（Token预算四维过滤）| GraphPlanner 图化调度 |
| 状态管理 | JSON文件型记忆 | GraphStore 结构化状态 |
| 适配器 | 直接调用 Python 函数 | AdapterFramework 统一接口契约 |
| 验证目的 | 验证框架流水线的可行性 | 验证 OS 化调度的工程价值 |

### 关键配置
```
入口:    experiments/agent_c/agent_c.py → AgentC 类
账户:    复用 Agent B 的 Hyperliquid API（共用执行层）
历史:    experiments/ab-trading/data/agent_c_b/*.json
数据API: data_server.py /api/dreamos/analyze?symbol=BTC
DreamOS: 1-ARCHITECTURE/dreamos/ (Python包)
```

---

## 五、三屏马丁交易系统（独立）

### 设计目标
基于 Elder 三屏系统，前两屏由 AI 研报驱动做战略+战术判断，第三屏由经典指标负责精准执行，AI 不可用时全经典接管。

### 三屏分工（AI驱动，经典指标降级）

```
Screen 1 — 战略层（周报驱动）
  驱动源: A系列研报/周报/screen1_*.md（每周一更新）
  功能:   7维评分（技术40/链上15/减半10/矿工10/宏观10/跨市场10/情绪5）
          → 确定大方向（牛/熊/震荡）+ 关键价位
  降级:   经典技术指标（MA200三日确认/MACD趋势/RSI月线）
      ↓
Screen 2 — 战术层（A1日报驱动）
  驱动源: A系列研报/A1研报/a1_regime_*.json（每日更新）
  功能:   根据 Regime → V9马丁参数（加仓间隔/止盈倍数/vol_mult）
          → 预设入场方案（限价单位置/加仓梯级/止盈目标）
  降级1:  V15高级规则（信号权重自适应算法）
  降级2:  V9基线策略（固定参数马丁兜底）
      ↓
Screen 3 — 执行层（A6情报 + 经典指标执行）
  驱动源: A系列研报/A6研报/*.md（每4H更新）
          → 监控 P0/P1告警 + recommendation
  执行:   classic_executor.py
          - 接收 Screen1/2 的方向约束和币种池
          - ATR 动态止损（1.5x ATR）
          - 分级止盈（0-4%区间）
          - 双模式：AI主导（接收指令）/ 经典接管（自主决策）
          - OKX CLI 下单（BTC-USDT-SWAP 合约）
```

### 降级链（完整）

```
正常:     AI研报驱动 → Screen1方向 + Screen2参数 → Screen3经典执行
部分降级: A6不可用 → Screen3使用技术指标判断持仓（前两屏AI仍工作）
全降级1:  LLM不可用 → V15高级规则（信号权重自适应）
全降级2:  V15置信不足 → V9基线策略（固定参数，永远可用）
```

### 研报加载（report_loader.py）

```python
load_weekly()           # Screen1 战略参考，TTL 1H（⚠️ 注意：非 load_weekly_report）
load_a1_daily()         # Screen2 战术参考，TTL 30min（已修复：兼容新旧JSON格式）
load_a6_intel()         # Screen3 情报参考，TTL 15min
get_all_reports()       # 全量加载（weekly + a1_daily + a6_intel）
```

### 自主调度（screen_orchestrator.py）

```
触发条件:
  1. 1H常规心跳（NORMAL_INTERVAL_H=1）
  2. BTC 1H波动 > 2%（VOLATILITY_PCT=2.0）
  3. A6情报有新内容（check_new_intel 检测 date 变化）
  4. P0级告警（A6研报含 p0_alerts>0）
  5. 关键价位自主申请

守护进程: launchd plist → com.dreambuddy.screen_monitor.plist
```

### 关键配置
```
交易所:  OKX（okx-trade-cli，profile=screen_trade）
研报:    experiments/ab-trading/A系列研报/
入口:    screen_orchestrator.py (调度) → screen_executor.py (Screen3执行)
引擎:    screen_engine.py (三屏逻辑整合)
经典执行: classic_executor.py（ATR止损+OKX下单）
监控API: data_server.py /api/screen/status
```

---

## 六、易经推理交易系统（独立仓库）

### 设计目标
以易经六十四卦作为推理框架，配合完整的 A0-A9 SKILL 体系，形成完全独立的交易决策系统。

### 项目结构

```
11-易经推理系统/
  constraints/          ← 约束层（宪法+机器可读规范）
  workflows/            ← 工作流（记忆L4/治理/交易决策/知识/进化）
  skills/
    0-CORE/             ← 核心SKILL
    1-TRADE/            ← A0-A9完整SKILL副本（A7/A8/dream-first-principles等）
    2-INTELLIGENCE/     ← 情报SKILL
    3-SUPPORT/          ← 支撑SKILL
    4-GENERIC/          ← 通用SKILL
  scripts/
    memory_l4/
      ab_bridge.py      ← ⚡ 对外桥接接口（唯一入口）
  data/                 ← 运行时数据（记忆/Episode/产物）
```

### 接入方式

```python
# data_server.py 通过子进程调用（path 硬编码）
YIJING_PATHS = [
    "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统",
    Path(__file__).parent.parent.parent / "11-易经推理系统",  # 相对路径
]
subprocess.run(["python3", "-m", "scripts.memory_l4.ab_bridge", "yijing-status"])

# 对外 API（通过 data_server.py）
GET /api/yijing/status     ← 当前系统状态（模型信息/运行状态）
GET /api/yijing/trade      ← 持仓/余额/Algo单/绩效
```

### 守护进程
```
launchd: com.dreambuddy.yijing_monitor.plist
```

---

## 七、三层进化系统

### 架构

```
evolution_scheduler.py ← 独立调度进程（非 agent_a_runner 内部调用）
 ↓
EvolutionScheduler.run_all_evolution_checks()
  ├── A8 检验（每24H）
  │     a8_evolution.py → A8TheoryPracticeEvolution
  │     - 检验 A0-A7 理论与实践背离
  │     - 发现背离 → 提出假说 → SimpleBacktestEngine 验证
  │     - 生成进化提议（EvolutionSource.A8_THEORY_PRACTICE）
  │
  ├── 做梦部反思（每12H）
  │     dream_evolution.py → DreamOneirologyEvolution
  │     - 梦境解析：提取被系统压制的判断
  │     - 潜意识探测："想说但没说"的市场判断
  │     - 反事实推演：历史决策的替代路径
  │     - 四象限预言：乐观/中性/悲观/被忽视（各赋概率）
  │
  └── GitHub 成熟经验（每48H）
        github_evolution.py → GithubBestPracticeEvolution
        - 联网搜索高star开源交易策略
        - 提取策略参数和思路
        - 回测验证适用性
        - 生成进化提议（需联网权限）
```

### 进化生命周期

```
proposed → backtesting → observation → adopted
                      ↘ rejected
                      ↘ rolled_back
```

### 进化结果如何影响 Agent A

```python
# agent_a_runner.py Step 1
evolution_params = get_evolution_params(memory)
# 含: momentum_threshold/volume_threshold/rsi_oversold/use_ema_cross 等

# _break_conservative_loop() 使用进化参数动态调整入场阈值
mom_threshold = evo_params.get("momentum_threshold", 0.02)
rsi_oversold  = evo_params.get("rsi_oversold", 40)
use_ema_cross = evo_params.get("use_ema_cross", True)
```

### 当前接入状态

| 系统 | 进化接入情况 |
|------|------------|
| Agent A | ✅ 读取 `evolution_params` 用于调整规则阈值；三层进化由独立 `evolution_scheduler.py` 定时运行 |
| Agent B | ✅ `trading_memory.py` 建议闭环；治理环 gap_score → A8 |
| Agent C | 通过 DreamOS evolution 模块 |
| 独立进化调度 | `evolution_scheduler.py` 需独立启动，不随 agent_a_runner 自动运行 |

### 启动进化调度器
```bash
cd experiments/ab-trading
python3 evolution_scheduler.py
# 或后台运行
nohup python3 evolution_scheduler.py > logs/evolution_scheduler.log 2>&1 &
```

---

## 八、关键文件索引

### 入口文件
| 系统 | 文件 | 说明 |
|------|------|------|
| Agent A | `agents/agent_a_runner.py` | 9步执行流程 |
| Agent B | `agents/agent_b_runner.py` | Dreambuddy OS 验证 |
| Agent C | `../agent_c/agent_c.py` | DreamOS SACG驱动 |
| 三屏调度 | `screen_orchestrator.py` | 三屏自主调度 |
| 三屏执行 | `screen_executor.py` | Screen3 OKX执行 |
| 三屏引擎 | `screen_engine.py` | 三屏逻辑整合 |
| 经典执行 | `classic_executor.py` | ATR止损+双模式 |
| 研报加载 | `report_loader.py` | 周报/A1日报/A6情报 |
| 易经接口 | `../../11-易经推理系统/scripts/memory_l4/ab_bridge.py` | 唯一对外桥接 |
| 全局调度 | `orchestrator.py` | 15min心跳+事件驱动 |
| 进化调度 | `evolution_scheduler.py` | 三层进化（独立进程）|
| 监控服务 | `data_server.py` | port:8765 |
| 桥接服务 | `bridge_server.py` | port:3847，35模块 |

### 核心模块
| 模块 | 路径 | 说明 |
|------|------|------|
| Hyperliquid执行 | `execution/aster_spot.py` | EIP-712签名下单 |
| LLM三级回退 | `core/agent_a_llm.py` | Trae→DeepSeek→规则 |
| Agent A记忆 | `core/agent_a_memory.py` | Lessons+大师+进化参数 |
| 意图识别 | `core/intent_gateway.py` | 6种意图类型（B用）|
| 链路规划 | `core/chain_planner.py` | 零Token四维规划（B用）|
| 链路执行 | `core/chain_router.py` | 动态节点执行（B用）|
| 动态意图 | `core/intent_engine/dynamic_intent_recognizer.py` | S层LLM增强 |
| 离场模块 | `core/exit_module.py` | L1/L2/L3三层离场 |
| 进化引擎 | `core/evolution/evolution_engine.py` | 生命周期管理 |
| A8进化 | `core/evolution/a8_evolution.py` | 理论实践验证 |
| 做梦部进化 | `core/evolution/dream_evolution.py` | 潜意识反思 |
| GitHub进化 | `core/evolution/github_evolution.py` | 联网学习（需联网）|
| 回测引擎 | `core/evolution/backtest_engine.py` | 进化提议验证 |
| 交易记忆 | `core/trading_memory.py` | 建议→验证→复盘（B用）|
| 节点注册 | `core/nodes/node_registry.py` | 11节点（已修复自动加载）|
| 模块注册 | `core/modules/module_registry.py` | 35模块 |

### SKILL 文件
| SKILL | 路径 | 使用方 |
|-------|------|--------|
| Agent A 交易大师 | `skills/agent-a-trading/SKILL.md` | Agent A LLM提示词 |
| 三屏马丁交易 | `skills/screen-martin-trading/` | 三屏系统 |
| Dreambuddy OS | `../../1-ARCHITECTURE/skills/dreambuddy-os/SKILL.md` | Agent B |

### 数据目录
```
data/
  agent_a_memory.json         ← Agent A 记忆（Lessons/大师/进化参数）
  agent_a_llm_quota.json      ← Agent A LLM每日配额
  agent_b_memory.json         ← Agent B 记忆
  agent_b_graph.json          ← Agent B 图压缩记录
  agent_c_b/                  ← Agent C 历史决策
  evolution/
    a_evolution_pool.json     ← Agent A 进化提议池
    a_evolution_history.json  ← 历史进化记录
    dream_journal.json        ← 做梦部日志
    a8_inspection_log.json    ← A8检验日志
    github_search_log.json    ← GitHub搜索日志
  orchestrator_state.json     ← 调度状态
A系列研报/
  周报/screen1_*.md            ← Screen1 战略参考
  A1研报/a1_regime_*.json      ← Screen2 战术参考
  A6研报/*.md                  ← Screen3 情报参考
logs/                          ← 各系统运行日志
```

### 环境变量（config/.env）
```bash
# Hyperliquid 账户
AGENT_A_ASTER_USER=0x93842F1ea62E7E3c71494d9EA69EfC4F2D6e9934
AGENT_A_ASTER_SIGNER=...
AGENT_A_ASTER_SIGNER_PRIVATE_KEY=...
AGENT_B_ASTER_USER=0x6632da9c91A959eEBf1343f8AFAbf2807414004A
AGENT_B_ASTER_SIGNER=...
AGENT_B_ASTER_SIGNER_PRIVATE_KEY=...

# LLM
TRAE_API_KEY=...                        # Agent A 优先使用
TRAE_MODEL=claude-sonnet-4-5
DEEPSEEK_API_KEY=...                    # Agent A/B 备用
ANTHROPIC_API_KEY=                      # 可选
TAVILY_API_KEY=...                      # 搜索/A1研报

# LLM 配额
AGENT_A_TRAE_DAILY_LIMIT=12
AGENT_A_DEEPSEEK_DAILY_LIMIT=24

# GitHub PR 评论（可选）
GITHUB_TOKEN=...
GITHUB_REPOSITORY=yunya1991/Dreambuddy-V2
PR_NUMBER=52

# 运行模式
AUTO_EXECUTE=true
PER_TRADE_PCT=0.05
```

---

## 附：系统关系图

```
                    ┌──────────────── AB对比实验 ──────────────────────────┐
                    │                                                      │
         Agent A               Agent B                  Agent C           │
        (LLM原生)           (Dreambuddy框架)           (DreamOS内核)       │
   Jesse Livermore风格       意图→动态链→节点           SACG四层            │
   Trae→DeepSeek→规则        图压缩+记忆闭环           NodeRegistry        │
   进化系统(独立调度)        三环架构治理                AdapterFramework    │
         │                       │                         │              │
         └───────────── Hyperliquid 执行层（aster_spot.py）────────────────┘

   ┌──────────────────── 独立交易系统 ───────────────────────────┐
   │                                                             │
   │       三屏马丁交易系统                  易经推理交易系统      │
   │  Screen1 ← 周报(AI/降级=经典TA)    六十四卦推理框架          │
   │  Screen2 ← A1日报(AI/降级=V15/V9)  A0-A9 SKILL副本          │
   │  Screen3 ← A6情报+经典指标执行     独立约束层+工作流          │
   │  降级链: AI→V15→V9(全经典接管)    ab_bridge.py 对外接口      │
   │  OKX 合约马丁策略                  独立launchd守护            │
   └─────────────────────────────────────────────────────────────┘

   ┌──────────────────── 进化系统（独立调度）────────────────────┐
   │  evolution_scheduler.py（独立进程）                          │
   │  ├── A8 理论实践验证（24H）→ 检验理论与实践背离              │
   │  ├── 做梦部外部反思（12H）→ 潜意识视角+四象限预言            │
   │  └── GitHub成熟经验搜索（48H）→ 联网学习+回测验证            │
   │  进化结果 → memory.evolution.adopted_params → Agent A读取    │
   └──────────────────────────────────────────────────────────────┘

   ┌──────────────────── 基础设施 ──────────────────────────────┐
   │  data_server.py    :8765  统一监控 API（A/B/C/三屏/易经）   │
   │  bridge_server.py  :3847  TS桥接（35模块+11节点，FastAPI）  │
   │  orchestrator.py          15min调度（A/B公用）              │
   │  前端 Next.js      :3000  主前端仪表盘                      │
   │  经典指标系统      :8092  ml_trade_service.py（Flask）      │
   │  基本面系统        :9094  待 Python 3.11 启动               │
   └────────────────────────────────────────────────────────────┘
```
