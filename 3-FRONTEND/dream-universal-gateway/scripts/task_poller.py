#!/usr/bin/env python3
"""
WorkBuddy Automation - 任务轮询器 v1.0
轮询 artifacts/tasks/，执行SKILL链路，写 artifacts/results/

核心业务规则：
- 对话任务(market_query/deep_analysis/simple_qa/scenario_sim/strategy_verify) → 单次执行
- 交易任务(execute_trade) → 需用户确认执行时间，写入scheduled字段等待确认

数据流：
  前端 → artifacts/tasks/{task_id}.json → 本脚本读取 → 执行SKILL → artifacts/results/result_{task_id}.json → 前端轮询
"""

import json
import os
import sys
import time
import uuid
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ============================================================
# 配置
# ============================================================
# 优先级: CLI --workspace > 环境变量 WORKSPACE > 脚本同级目录的父目录
_SCRIPT_DIR = Path(__file__).resolve().parent  # scripts/
_GATEWAY_DIR = _SCRIPT_DIR.parent              # dream-universal-gateway/
_WORKSPACE_DIR = _GATEWAY_DIR.parent.parent    # dreambuddy-v1/

WORKSPACE = Path(os.environ.get('WORKSPACE', str(_WORKSPACE_DIR)))
_ARTIFACTS_V2 = WORKSPACE / 'dreambuddy' / 'artifacts'
ARTIFACTS_DIR = _ARTIFACTS_V2 if _ARTIFACTS_V2.exists() else (WORKSPACE / 'artifacts')
TASKS_DIR = ARTIFACTS_DIR / 'tasks'
RESULTS_DIR = ARTIFACTS_DIR / 'results'

# 并发限制
MAX_CONCURRENT = 3

# 轮询间隔(秒)
POLL_INTERVAL = int(os.environ.get('POLL_INTERVAL', '10'))

# 任务超时(秒)
TASK_TIMEOUT = 30 * 60  # 30分钟

# ============================================================
# 意图类型分类
# ============================================================
# 对话任务 - 单次执行
CONVERSATION_INTENTS = {'market_query', 'deep_analysis', 'simple_qa', 'scenario_sim', 'strategy_verify', 'command'}

# 交易任务 - 需用户确认执行时间
TRADE_INTENTS = {'execute_trade'}

# ============================================================
# SKILL链路映射
# ============================================================
INTENT_CHAIN_MAP = {
    'market_query': {
        'quick': ['A6_intelligence'],
        'deep':  ['A1_research', 'A6_intelligence'],
    },
    'deep_analysis': {
        'quick': ['A1_research', 'A2_advisor'],
        'deep':  ['A1_research', 'A2_advisor', 'A3_strategy'],
    },
    'scenario_sim': {
        'quick': ['A3_strategy'],
        'deep':  ['A2_advisor', 'A3_strategy', 'A4_validation'],
    },
    'strategy_verify': {
        'quick': ['A4_validation'],
        'deep':  ['A3_strategy', 'A4_validation'],
    },
    'execute_trade': {
        'quick': ['A5_execution'],
        'deep':  ['A4_validation', 'A5_execution'],
    },
    'simple_qa': {
        'quick': ['A6_intelligence'],
        'deep':  ['A1_research', 'A6_intelligence'],
    },
    'command': {
        'quick': ['A6_intelligence'],
        'deep':  ['A6_intelligence'],
    },
}


# ============================================================
# 任务读取/写入
# ============================================================
def read_task(task_file: Path) -> Optional[dict]:
    """读取任务文件"""
    try:
        with open(task_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"[ERROR] Failed to read task {task_file.name}: {e}")
        return None


def update_task_status(task_file: Path, status: str):
    """更新任务状态"""
    task = read_task(task_file)
    if task:
        task['status'] = status
        task['updated_at'] = datetime.now(timezone.utc).isoformat()
        with open(task_file, 'w', encoding='utf-8') as f:
            json.dump(task, f, indent=2, ensure_ascii=False)


def write_result(task_id: str, result_data: dict):
    """写入结果文件"""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    result_file = RESULTS_DIR / f"result_{task_id}.json"
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result_data, f, indent=2, ensure_ascii=False)
    print(f"[RESULT] Written: {result_file.name}")


# ============================================================
# SKILL执行引擎（模拟/实际调用）
# ============================================================
def execute_skill_chain(task: dict) -> dict:
    """
    执行SKILL链路
    当前为模拟执行模式，后续可替换为实际SKILL调用
    """
    intent_type = task.get('intent', {}).get('type', 'simple_qa')
    thinking_mode = task.get('thinking_mode', 'quick')
    message = task.get('message', '')
    
    # 获取链路
    chain_config = INTENT_CHAIN_MAP.get(intent_type, INTENT_CHAIN_MAP['simple_qa'])
    chain = chain_config.get(thinking_mode, chain_config['quick'])
    
    start_time = time.time()
    execution_summary = {
        'chain_executed': chain,
        'total_steps': len(chain),
        'skipped_steps': [],
        'regime': 'RANGE_BOUND',
        'confidence': task.get('intent', {}).get('confidence', 0.6),
    }
    
    artifacts_produced = []
    
    # 判断是否为交易任务
    is_trade_task = intent_type in TRADE_INTENTS
    
    if is_trade_task:
        # 交易任务 - 需用户确认执行时间
        content = generate_trade_pending_response(task, chain)
        # 不自动执行，写入scheduled状态等待用户确认
        result_status = 'completed'  # 结果本身是completed，但content中包含待确认信息
    else:
        # 对话任务 - 单次执行
        content = execute_conversation_task(task, chain, artifacts_produced)
        result_status = 'completed'
    
    execution_time_ms = int((time.time() - start_time) * 1000)
    
    return {
        'task_id': task['task_id'],
        'status': result_status,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'execution_time_ms': execution_time_ms,
        'content': content,
        'content_type': 'markdown',
        'artifacts_produced': artifacts_produced,
        'execution_summary': execution_summary,
        'metadata': {
            'executor': 'workbuddy_automation_v1',
            'model': task.get('metadata', {}).get('llm_model', 'unknown'),
            'cost_credits': calculate_credits(chain, thinking_mode),
        },
    }


def execute_conversation_task(task: dict, chain: list, artifacts_produced: list) -> str:
    """执行对话类任务（单次执行）"""
    intent_type = task.get('intent', {}).get('type', 'simple_qa')
    message = task.get('message', '')
    entities = task.get('intent', {}).get('entities', {})
    symbol = entities.get('symbol', 'BTC')
    timeframe = entities.get('timeframe', '4h')
    
    if intent_type == 'market_query':
        artifacts_produced.append({
            'file': f'a6_intelligence_brief_{datetime.now().strftime("%Y%m%d_%H%M")}.md',
            'type': 'intelligence_brief',
            'chain_phase': 'A6',
        })
        return f"""📊 **{symbol} 市场行情快报**

> 由 WorkBuddy Automation 自动生成 | 链路: {' → '.join(chain)}

---

**当前状态**
- 品种: {symbol}-USDT-SWAP
- 市场Regime: 区间震荡 (RANGE_BOUND)
- 时间框架: {timeframe}

**关键指标**
- 价格: $80,630 (近24h -0.23%)
- 24h最高: $81,500 | 最低: $79,700
- 资金费率: +0.0034% (偏多)
- 恐惧指数: 42 (恐惧)
- 200日SMA: $83,200 (价格在下方)

**支撑/阻力**
- 支撑: $79,700 → $78,500
- 阻力: $81,500 → $83,200

**摘要**
当前市场处于区间震荡状态，价格在200日均线下方运行，短期偏弱但支撑有效。CPI数据超预期后宏观偏鹰，降息预期推迟。

⚡ 快速思考模式 | 执行链路: {' → '.join(chain)}"""

    elif intent_type == 'deep_analysis':
        artifacts_produced.append({
            'file': f'a2_first_principles_{datetime.now().strftime("%Y%m%d_%H%M")}.md',
            'type': 'first_principles',
            'chain_phase': 'A2',
        })
        return f"""🔬 **{symbol} 深度分析报告**

> 由 WorkBuddy Automation 自动生成 | 链路: {' → '.join(chain)}

---

## 第一性原理分析

**核心矛盾**: 宏观偏鹰 vs 技术面超卖反弹需求
**主要矛盾方面**: 宏观压力 (Fed降息预期归零)
**次要矛盾方面**: 技术面支撑 (关键支撑位有效)

### 三维评分
| 维度 | 得分 | 说明 |
|------|------|------|
| 宏观 | 3/10 | CPI超预期，鹰派基调 |
| 技术 | 5/10 | 关键均线下方，支撑有效 |
| 情绪 | 4/10 | FGI=42恐惧，但非极端 |

### Edge分析
- 当前Edge: -15 (偏空但未达极端)
- 趋势动力: 不足 (区间震荡)
- 阻力最小方向: 横盘偏弱

### 建议
**SKIP** - 当前不满足开仓条件(评分<35且Edge<0)

🧠 思考模式: {task.get('thinking_mode', 'quick')} | 执行链路: {' → '.join(chain)}"""

    elif intent_type == 'scenario_sim':
        return f"""🎭 **{symbol} 情景推演**

> 由 WorkBuddy Automation 自动生成 | 链路: {' → '.join(chain)}

---

### 情景1: 区间延续 (概率 50%)
- 触发: 无重大事件，价格在$79,700-$81,500之间震荡
- 操作: 继续观望，等待突破信号

### 情景2: 向下突破 (概率 20%)
- 触发: 宏观利空加剧，跌破$79,700支撑
- 操作: 考虑SHORT，需A4验证

### 情景3: 向上反弹 (概率 18%)
- 触发: 降息预期回暖，突破$81,500阻力
- 操作: 轻仓做多，止损$79,700

### 情景4: 暴跌 (概率 8%)
- 触发: 黑天鹅事件(地缘/系统性风险)
- 操作: 紧急避险，全仓退出

执行链路: {' → '.join(chain)}"""

    elif intent_type == 'strategy_verify':
        return f"""✅ **策略验证结果**

> 由 WorkBuddy Automation 自动生成 | 链路: {' → '.join(chain)}

---

**验证状态**: 当前A3推演结论为SKIP(观望)
**验证时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}
**Regime**: RANGE_BOUND (置信度65%)

**验证项**
- [x] A3结论与当前Regime一致
- [x] Edge衰减在阈值内
- [x] 无P0事件触发
- [x] 持仓状态: 空仓

**结论**: 维持A3观望建议，不执行交易

执行链路: {' → '.join(chain)}"""

    else:  # simple_qa / command
        return f"""💬 **回复**

> 由 WorkBuddy Automation 自动生成

---

收到你的消息: "{message}"

当前系统状态:
- Regime: 区间震荡
- 持仓: 空仓
- 最新建议: 观望(SKIP)

如有具体问题，可以使用以下命令:
- /行情 - 查看市场行情
- /分析 - 深度分析
- /推演 - 情景推演
- /验证 - 策略验证
- /开仓 - 交易信号

执行链路: {' → '.join(chain)}"""


def generate_trade_pending_response(task: dict, chain: list) -> str:
    """
    交易任务 - 生成待确认响应
    交易任务需要用户确认执行时间，不自动执行
    """
    intent_type = task.get('intent', {}).get('type', 'execute_trade')
    entities = task.get('intent', {}).get('entities', {})
    symbol = entities.get('symbol', 'BTC')
    
    return f"""⚠️ **交易任务 - 需确认执行时间**

> 由 WorkBuddy Automation 生成 | 链路: {' → '.join(chain)}

---

**任务类型**: 交易执行 (execute_trade)
**品种**: {symbol}-USDT-SWAP
**状态**: ⏳ 等待确认

---

### 🔒 交易任务需要你的确认

交易类任务不会自动执行，请确认以下信息后设置执行时间：

1. **交易方向**: 待确认 (需A4验证后决定)
2. **执行链路**: {' → '.join(chain)}
3. **风控检查**: 将在执行前自动触发

### 确认方式
在前端回复以下内容之一：
- `确认执行` - 立即执行
- `定时 HH:MM` - 指定时间执行(如"定时 14:30")
- `取消` - 取消本次交易

---

📋 任务ID: {task.get('task_id', 'unknown')}
⏰ 创建时间: {task.get('created_at', 'unknown')}

> ⚠️ 注意: 交易任务涉及真实资金操作，系统不会自动执行未经确认的交易。"""


def calculate_credits(chain: list, thinking_mode: str) -> int:
    """计算积分消耗"""
    base = {
        'A1_research': 50,
        'A2_advisor': 80,
        'A3_strategy': 100,
        'A4_validation': 120,
        'A5_execution': 150,
        'A6_intelligence': 30,
    }
    total = sum(base.get(s, 50) for s in chain)
    if thinking_mode == 'deep':
        total = int(total * 1.5)
    return total


# ============================================================
# 主轮询循环
# ============================================================
def poll_and_execute():
    """轮询tasks目录并执行待处理任务"""
    # 确保目录存在
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    
    # 查找pending任务
    pending_tasks = []
    try:
        for f in sorted(TASKS_DIR.glob('task_*.json')):
            task = read_task(f)
            if task and task.get('status') == 'pending':
                # 检查超时
                created_at = task.get('created_at', '')
                if created_at:
                    try:
                        created_time = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                        if (datetime.now(timezone.utc) - created_time).total_seconds() > TASK_TIMEOUT:
                            # 标记超时
                            update_task_status(f, 'timeout')
                            write_result(task['task_id'], {
                                'task_id': task['task_id'],
                                'status': 'failed',
                                'created_at': datetime.now(timezone.utc).isoformat(),
                                'content': '任务超时（30分钟），WorkBuddy未能及时处理',
                                'content_type': 'text',
                                'error': 'timeout',
                                'metadata': {'executor': 'workbuddy_automation_v1'},
                            })
                            print(f"[TIMEOUT] {task['task_id']}")
                            continue
                    except Exception:
                        pass
                pending_tasks.append((f, task))
    except Exception as e:
        print(f"[ERROR] Failed to scan tasks: {e}")
        return 0
    
    if not pending_tasks:
        return 0
    
    # 并发限制
    executable = pending_tasks[:MAX_CONCURRENT]
    
    executed = 0
    for task_file, task in executable:
        task_id = task.get('task_id', 'unknown')
        intent_type = task.get('intent', {}).get('type', 'unknown')
        
        print(f"[EXEC] Processing: {task_id} | intent: {intent_type}")
        
        try:
            # 标记为processing
            update_task_status(task_file, 'processing')
            
            # 执行SKILL链路
            result = execute_skill_chain(task)
            
            # 写入结果
            write_result(task_id, result)
            
            # 更新任务状态为completed
            update_task_status(task_file, 'completed')
            
            executed += 1
            print(f"[DONE] {task_id} | status: completed | time: {result.get('execution_time_ms', 0)}ms")
            
        except Exception as e:
            print(f"[ERROR] Failed to execute {task_id}: {e}")
            traceback.print_exc()
            
            # 标记失败
            update_task_status(task_file, 'failed')
            write_result(task_id, {
                'task_id': task_id,
                'status': 'failed',
                'created_at': datetime.now(timezone.utc).isoformat(),
                'content': f'任务执行失败: {str(e)}',
                'content_type': 'text',
                'error': str(e),
                'metadata': {'executor': 'workbuddy_automation_v1'},
            })
    
    return executed


def execute_single_task(task_id: str):
    """执行单个指定任务（由API route异步调用）"""
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    
    # 查找任务文件
    task_file = TASKS_DIR / f"{task_id}.json"
    if not task_file.exists():
        print(f"[ERROR] Task file not found: {task_id}")
        return 0
    
    task = read_task(task_file)
    if not task:
        print(f"[ERROR] Failed to read task: {task_id}")
        return 0
    
    if task.get('status') not in ('pending', 'processing'):
        print(f"[SKIP] Task {task_id} status is {task.get('status')}, not pending")
        return 0
    
    intent_type = task.get('intent', {}).get('type', 'unknown')
    print(f"[EXEC] Single task: {task_id} | intent: {intent_type}")
    
    try:
        # 标记为processing
        update_task_status(task_file, 'processing')
        
        # 执行SKILL链路
        result = execute_skill_chain(task)
        
        # 写入结果
        write_result(task_id, result)
        
        # 更新任务状态为completed
        update_task_status(task_file, 'completed')
        
        print(f"[DONE] {task_id} | status: completed | time: {result.get('execution_time_ms', 0)}ms")
        return 1
        
    except Exception as e:
        print(f"[ERROR] Failed to execute {task_id}: {e}")
        traceback.print_exc()
        
        # 标记失败
        update_task_status(task_file, 'failed')
        write_result(task_id, {
            'task_id': task_id,
            'status': 'failed',
            'created_at': datetime.now(timezone.utc).isoformat(),
            'content': f'任务执行失败: {str(e)}',
            'content_type': 'text',
            'error': str(e),
            'metadata': {'executor': 'workbuddy_poller_v1'},
        })
        return 0


def main():
    """主入口"""
    global WORKSPACE, ARTIFACTS_DIR, TASKS_DIR, RESULTS_DIR

    # 解析 --workspace 参数（覆盖默认路径）
    if '--workspace' in sys.argv:
        idx = sys.argv.index('--workspace')
        if idx + 1 < len(sys.argv):
            WORKSPACE = Path(sys.argv[idx + 1])
            ARTIFACTS_DIR = WORKSPACE / 'artifacts'
            TASKS_DIR = ARTIFACTS_DIR / 'tasks'
            RESULTS_DIR = ARTIFACTS_DIR / 'results'
        else:
            print("[ERROR] --workspace requires a directory path argument")
            return

    print(f"=" * 60)
    print(f"WorkBuddy Task Poller v1.2")
    print(f"=" * 60)
    print(f"WORKSPACE:   {WORKSPACE}")
    print(f"TASKS_DIR:   {TASKS_DIR}")
    print(f"RESULTS_DIR: {RESULTS_DIR}")
    print(f"POLL_INTERVAL: {POLL_INTERVAL}s")
    print(f"MAX_CONCURRENT: {MAX_CONCURRENT}")
    print(f"=" * 60)
    
    # 单任务执行模式（由API route通过child_process调用）
    if '--task-id' in sys.argv:
        idx = sys.argv.index('--task-id')
        if idx + 1 < len(sys.argv):
            task_id = sys.argv[idx + 1]
            count = execute_single_task(task_id)
            print(f"\n[SUMMARY] Executed {count} task(s)")
        else:
            print("[ERROR] --task-id requires a task_id argument")
        return
    
    # 批量扫描执行模式（供定时任务调用）
    if '--once' in sys.argv:
        count = poll_and_execute()
        print(f"\n[SUMMARY] Executed {count} task(s)")
        return
    
    # 持续轮询模式
    print(f"[INFO] Starting continuous polling (interval: {POLL_INTERVAL}s)")
    print(f"[INFO] Press Ctrl+C to stop\n")
    
    try:
        while True:
            count = poll_and_execute()
            if count > 0:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Executed {count} task(s)")
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        print("\n[INFO] Stopped by user")


if __name__ == '__main__':
    main()
