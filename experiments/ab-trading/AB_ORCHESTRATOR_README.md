# AB-Trading 记忆与SKILL驱动调度器

## 系统状态

✅ **已成功启动后台守护进程**

## 执行机制

### 每4小时自动执行
- **执行路径**: `cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading && python3 orchestrator.py`
- **日志文件**: `logs/orchestrator.log`
- **启动脚本**: `run_orchestrator_daemon.sh`

### 触发条件（按优先级）

1. **Agent自主申请** (最高优先级)
   - 连败5次后6H强制复盘
   - 成交量异常放大触发
   - 高置信度信号触发

2. **市场极端波动**
   - BTC 1H波动 ≥ 2% 自动触发

3. **重要经济事件**
   - CPI、NFP、FOMC等重大事件前后30分钟内触发

4. **常规4H心跳** (兜底机制)

## 记忆与SKILL集成

### Agent A (LLM驱动)
- 大师风格: Stanley Druckenmiller / Jim Simons 等
- 记忆系统: 连胜/连败追踪, Lessons学习
- SKILL框架: 矛盾理论、第一性原理等

### Agent B (BAC架构)
- 架构: BAC全量架构 + LLM增强
- 记忆闭环: 交易记忆闭环验证
- SKILL工作流: 动态链式执行

### SKILL状态
- 5个核心SKILL全部可用:
  - dream-contradiction-theory (矛盾理论)
  - dream-first-principles (第一性原理)
  - dream-exit-skill-v2 (离场技能)
  - dream-regime-detector (市场状态检测)
  - dream-oneirology (梦学分析)

## 监控命令

### 查看实时日志
```bash
tail -f /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/logs/orchestrator.log
```

### 检查进程状态
```bash
ps aux | grep "run_orchestrator_daemon\|orchestrator.py" | grep -v grep
```

### 手动触发执行
```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading
python3 orchestrator.py
```

### 停止守护进程
```bash
pkill -f run_orchestrator_daemon.sh
```

## 最近执行记录

### 2026-07-15 16:04:46 (UTC+8)
- **触发原因**: Agent自主申请 - A连败5次，6H后强制复盘评估市场
- **Agent A**: 大师 Jim Simons, 42次交易, 连败5次, 回撤7.7%
- **Agent B**: 周期561, TREND_DOWN市场状态, 持仓包括 ARB/ZEC/LIT/NEAR/HYPE/ENA
- **SKILL状态**: 5/5 全部可用
- **执行时长**: 约1.5分钟
- **状态**: ✅ 成功完成，等待4小时后下一次执行

## 系统特性

1. **自主性**: Agent可申请提前执行
2. **记忆驱动**: 每次执行前加载双方记忆
3. **SKILL集成**: 动态编排A/C/F链节点
4. **事件响应**: 重要经济事件自动触发
5. **波动监控**: 市场极端波动实时响应
6. **闭环学习**: 每轮执行后更新记忆与状态