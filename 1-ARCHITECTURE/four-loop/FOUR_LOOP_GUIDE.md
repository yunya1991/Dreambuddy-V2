# DreamOS 四闭环系统定位指引

> **版本**: v1.0 | **创建**: 2026-08-17 | **维护**: DreamOS Team
> **定位**: 四闭环是 DreamOS 交易系统的核心能力域实现，既可编排单节点（SACG），也可实现子系统级调度（四闭环）

---

## 一、四闭环定义

四闭环是 DreamOS 交易系统（Dreambuddy OS 的核心能力域，术语规范见 SSoT §1.3.3）在 Hyperliquid 交易所上的完整交易流水线，由 F层调度器驱动，每小时:30触发一次完整编排周期。

**核心是两个并列的执行策略，共享 A层选币 和 B层易经信号：**

```
                    ┌─ 双腿对冲策略（一多一空，市场中性）
A选币 → B易经信号 ─┤
                    └─ V15马丁策略（仅多头，金字塔加仓）
 ↑                                              │
 └────────── confidence_adjustment 回填 ─────────┘
```

| 闭环 | 名称 | 核心组件 | 职责 |
|------|------|----------|------|
| **A** | 选币池 | CoinSelector + coin_pool.json | 从 hermes-weekly 选币 cron 产出的币池中取多池 Top6 |
| **B** | 易经推理信号 | YijingSignalGenerator + BCRM引擎 | 基于市场指标生成卦象、方向、置信度 |
| **C1** | 双腿对冲策略 | HedgeExecutor | 多池选conf最高LONG + 空池选conf最高SHORT，1:1对冲开仓 |
| **C2** | V15马丁策略 | V15Executor | 仅消费多池信号（long_only=True），金字塔加仓（首单+4档） |
| **D** | 信号路由 | SignalRouter | B+C 单次调用完成，统一路由 |
| **E** | 认知复盘 | CognitiveReviewer | 交易平仓后生成认知教训，回填 confidence_adjustment |
| **F** | 编排调度 | OrchestratorV2 + Scheduler | 驱动 A→B→C1/C2→D→E 全链路，每小时:30触发 |

### 双腿策略 vs 马丁策略

| 维度 | 双腿对冲策略 (C1) | V15马丁策略 (C2) |
|------|-------------------|------------------|
| 策略类型 | 市场中性（双腿对冲） | 马丁格尔（顺势加仓） |
| 方向 | 双向（多+空同时） | 单向（long_only=True） |
| 激活条件 | 仅 RANGE_BOUND regime | 全 regime |
| 仓位管理 | 1:1 双腿，无加仓 | 最多5单（首单+4档加仓） |
| 离场逻辑 | 合并 PnL +4%/-6% | A9 四层离场决策 |
| 账本 | hedge_positions.json | v15_positions.json |
| 并发上限 | 1 个对冲对 | 3 个持仓 |
| B层信号 | 复用 B层推导（双向验证） | 复用 B层推导（仅多头） |

---

## 二、代码位置映射

### 2.1 核心代码文件

| 闭环 | 文件路径 | 关键类/函数 |
|------|----------|-------------|
| **F** 编排 | `dreamos/cli/scheduler.py` | `DreamOSScheduler._orchestrate()` |
| **F** 编排 | `dreamos/capabilities/trading/orchestrator_v2.py` | `OrchestratorV2.run_cycle()` |
| **A** 选币 | `dreamos/capabilities/trading/coin_selector.py` | `CoinSelector._load_persisted_pools()` |
| **B** 易经 | `dreamos/capabilities/trading/yijing_signal_generator.py` | `YijingSignalGenerator` |
| **B** BCRM | `11-易经推理系统/scripts/memory_l4/bcrm/engine.py` | `BCRMEngine.infer()` |
| **C** 马丁 | `dreamos/capabilities/trading/v15_executor.py` | `V15Executor.execute_signal()` |
| **D** 路由 | `dreamos/capabilities/trading/signal_router.py` | `SignalRouter.route()` |
| **E** 认知 | `dreamos/capabilities/trading/cognitive_reviewer.py` | `CognitiveReviewer` |

### 2.2 配置文件

| 配置 | 路径 | 说明 |
|------|------|------|
| Hyperliquid凭证 | `dreamos/.env` | AGENT_DREAM_OS_HYPERLIQUID_* |
| 节点注册表 | `dreamos/config/nodes.yaml` | 35+模块配置 |
| 选币池 | `dreamos/cli/scheduler_data/coin_pool.json` | hermes-weekly 产出 |
| 认知教训 | `dreamos/data/cognitive_lessons.json` | E层持久化 |
| 检查点 | `dreamos/data/graph_store/ckpt_*.json` | G层状态快照 |
| 扫描记录 | `dreamos/cli/scheduler_data/scan_history.json` | 每轮扫描结果 |
| 持仓快照 | `dreamos/cli/scheduler_data/position_snapshot.json` | 当前持仓 |

### 2.3 数据源

| 数据 | 来源 | API |
|------|------|-----|
| 衍生品（资金费率/持仓量/标记价） | Hyperliquid | `https://api.hyperliquid.xyz/info` type=metaAndAssetCtxs |
| K线行情 | Hyperliquid | `https://api.hyperliquid.xyz/info` type=candleSnapshot |
| 基本面（情绪/链上） | alternative.me / Blockchain.info | 公开免费API |
| 市值/成交量 | CoinGecko | 公开免费API（当前失败） |

---

## 三、数据流详解

```
F层调度器 (scheduler.py _orchestrate, 每小时:30)
  │
  ├─ A层: 加载 coin_pool.json
  │   → 多池 Top6 (LINK/BTC/HYPE/ETH/NEAR/UNI)
  │   → 来源: persisted:hermes-weekly
  │
  ├─ 指标注入: enrich_market_data(sym, md, trader._fetch_market_data)
  │   → ma5/ma10/ma20/momentum_direction/volatility
  │   → 数据源: Hyperliquid API
  │   → 修复 F-1 数据饥饿问题
  │
  ├─ B层: orch.run_cycle(md)
  │   ├─ E层上下文: CognitiveReviewer.get_cognitive_context()
  │   │   → confidence_adjustment 注入信号
  │   ├─ B层信号: YijingSignalGenerator
  │   │   → 卦象生成 + direction + confidence
  │   ├─ C层执行: V15Executor.execute_signal()
  │   │   → dry_run门禁 → REJECTED/HOLD/EXECUTE
  │   └─ D层路由: SignalRouter.route()
  │       → B+C+D 单次调用完成
  │
  ├─ 结果回写: coin_selector.record_dynamic_score()
  │   → B层 confidence 回写动态排名层
  │
  └─ E层: CognitiveReviewer
      → cognitive_lessons.json 记录教训
      → 下周期 confidence_adjustment 回填到B层
```

---

## 四、运行状态查询

### 4.1 快速状态检查

```bash
# 查看调度器进程
ps aux | grep start_scheduler | grep -v grep

# 查看最新日志
tail -30 /home/ubuntu/Dreambuddy-V2-main/1-ARCHITECTURE/dreamos/logs/scheduler.log

# 查看认知教训
cat /home/ubuntu/Dreambuddy-V2-main/1-ARCHITECTURE/dreamos/data/cognitive_lessons.json | python3 -m json.tool

# 查看最新检查点
ls -lt /home/ubuntu/Dreambuddy-V2-main/1-ARCHITECTURE/dreamos/data/graph_store/ | head -5

# 查看扫描历史
cat /home/ubuntu/Dreambuddy-V2-main/1-ARCHITECTURE/dreamos/cli/scheduler_data/scan_history.json | python3 -m json.tool | head -30

# 查看持仓快照
cat /home/ubuntu/Dreambuddy-V2-main/1-ARCHITECTURE/dreamos/cli/scheduler_data/position_snapshot.json | python3 -m json.tool
```

### 4.2 Hyperliquid 账户查询

```bash
# DreamOS 账户余额
python3 -c "
import requests
r = requests.post('https://api.hyperliquid.xyz/info', json={'type':'clearinghouseState','user':'0x81cA2cf32b57a5790338c2b0d7Ca847abC18838a'})
d = r.json()
ms = d.get('marginSummary',{})
print('equity:', ms.get('accountValue'))
print('avail:', ms.get('marginAvailable'))
print('positions:', len(d.get('assetPositions',[])))
"
```

### 4.3 四闭环状态检查脚本

```bash
python3 /home/ubuntu/Dreambuddy-V2-main/1-ARCHITECTURE/four-loop/check_four_loop_status.py
```

---

## 五、调度器启动与重启

### 5.1 启动调度器

```bash
cd /home/ubuntu/Dreambuddy-V2-main/1-ARCHITECTURE/dreamos
nohup /home/ubuntu/.hermes/hermes-agent/venv/bin/python3 cli/start_scheduler.py > /tmp/dreamos_server.log 2>&1 &
```

### 5.2 重启调度器

```bash
# 停止
kill $(ps aux | grep start_scheduler | grep -v grep | awk '{print $2}')

# 清理暂停标记
rm -f /home/ubuntu/Dreambuddy-V2-main/1-ARCHITECTURE/dreamos/logs/SCHEDULER_PAUSED

# 启动
cd /home/ubuntu/Dreambuddy-V2-main/1-ARCHITECTURE/dreamos
nohup /home/ubuntu/.hermes/hermes-agent/venv/bin/python3 cli/start_scheduler.py > /tmp/dreamos_server.log 2>&1 &
```

### 5.3 调度器配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| exchange | hyperliquid | 交易所 |
| dry_run | True | 安全门禁（True=不下单） |
| long_only | True | V15纯多门禁 |
| confidence_threshold | 0.62 | 置信度门禁阈值 |
| min_trade_interval | 30分钟 | 最小交易间隔 |
| 4h去重 | 启用 | 同一4h周期不重复开仓 |

---

## 六、与 SACG 内核的关系

四闭环是 DreamOS 的**子系统级调度能力**，与 SACG 内核的**单节点级编排能力**互补：

| 维度 | SACG 内核 | 四闭环 |
|------|-----------|--------|
| 调度粒度 | 单节点（A0/A1/.../A9） | 子系统（BCRM/V15/CognitiveReviewer） |
| 编排方式 | GraphPlanner 动态选节点 | OrchestratorV2 固定流水线 |
| 数据流 | State 全局状态共享 | market_data 字典传递 |
| 适用场景 | 灵活编排、实验验证 | 生产实盘、稳定运行 |
| 代码位置 | dreamos/core/ | dreamos/capabilities/trading/ |

**两者共存**：DreamOS 既能通过 SACG 编排单节点，也能通过四闭环调度子系统。

---

## 七、已知问题与优化方向

### 7.1 当前已知问题

| 编号 | 问题 | 影响 | 状态 |
|------|------|------|------|
| F-1 | B层指标数据饥饿 | 已修复（enrich_market_data 注入） | ✅ 已修复 |
| F-2 | 交易所侧平仓无对账 | 真实pnl不进认知层 | ⚠️ 待修复 |
| LLM | LLM降级链全部失败 | LLM增强意图不可用 | ⚠️ 待修复 |
| Tavily | API Key无效 | flow/valuation/macro/news走Mock | ⚠️ 待修复 |
| CoinGecko | API失败 | 市值/成交量数据缺失 | 🟢 低优先级 |

### 7.2 优化方向

1. **F-2 修复**：添加持仓快照 diff + 成交历史查询对账
2. **LLM 修复**：检查 DeepSeek/Qwen API Key 余额和配置
3. **Tavily 修复**：更新 API Key 或替换为其他数据源
4. **卦象生成优化**：当前 BCRM 卦象为 N/A，需排查 ForceEngine/LiangyiEngine 输出
5. **Guardrail 执行顺序**：将 _auto_generate_contradictions 移到 Guardrail 验证之前
6. **inspect.py 重命名**：避免与标准库冲突

---

## 八、相关文档索引

| 文档 | 路径 | 说明 |
|------|------|------|
| 架构总览 | `1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md` | SSoT v3.0 |
| 交易模块全景 | `1-ARCHITECTURE/TRADING_MODULES_OVERVIEW.md` | Agent A/B/C 对比 |
| 模块化架构 | `1-ARCHITECTURE/WORKBUDDY_OS_MODULAR_ARCHITECTURE.md` | 五大能力域 |
| 四闭环验证 | `dreamos/capabilities/trading/reports/FOUR_LOOP_VERIFICATION_20260815.md` | 2026-08-15 验证报告 |
| BCRM引擎 | `11-易经推理系统/scripts/memory_l4/bcrm/engine.py` | 易经推理核心 |
| V15马丁 | `14-V15经典马丁策略/core/v15_trader.py` | 马丁策略核心 |
