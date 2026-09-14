# Phase 1 实施 Spec — 5 项真协同落地

> **版本**: v1.0
> **状态**: ✅ 已完成
> **日期**: 2026-09-13
> **前置**: Phase 0 POC 全部通过（V0-1~V0-7）
> **定位**: 基于 Phase 0 验证的 IPC 链路和 Cordis plugin 机制，落地 5 项真协同
> **验收**: V1-1/V1-2/V1-3/V1-5/V1-6 全部通过，TS 104/104 + Python V1 全绿

---

## 一、Phase 1 目标

**从 Phase 0 的"链路打通"升级到"1+1>2 真协同验证"。**

Phase 0 证明了：Harness agent loop 可以调用 DreamBuddy C1 节点 + IntentGateway pre-step listener。
Phase 1 要证明：Harness 的 Subagent 并行化 + session log 事件流 + Model-as-Plugin 能给 DreamBuddy 带来真实增益。

---

## 二、实施范围

### 2.1 Subagent-1: 经典指标系统接入

| 维度 | 说明 |
|------|------|
| **现有系统** | `10-经典指标系统/ml_trade_service.py` (Flask, port 8092) |
| **接入方式** | Python server 新增 `technical_indicators` 方法，通过 HTTP 调用 8092 |
| **Cordis plugin** | 新增 `dreambuddy-indicators` plugin，注册 `get_technical_indicators` tool |
| **降级链** | 8092 不可达 → FAIL-OPEN 返回中性默认值 + 6 层堆栈日志 |
| **验收** | V1-1: 并行调用延迟显著低于串行; V1-2: 8092 故障不影响基本面 API |

### 2.2 Subagent-2: 基本面 API 接入

| 维度 | 说明 |
|------|------|
| **现有系统** | `9-基本面分析/ml_trade_service_v2.py` (Flask, port 3456 @ 49.233.123.96) |
| **接入方式** | Python server 新增 `fundamental_analysis` 方法，通过 HTTP 调用 3456 |
| **Cordis plugin** | 新增 `dreambuddy-fundamental` plugin，注册 `get_fundamental_analysis` tool |
| **降级链** | 3456 不可达 → FAIL-OPEN 返回中性默认值 + 6 层堆栈日志 |
| **验收** | V1-1: 并行调用延迟显著低于串行; V1-2: 3456 故障不影响指标系统 |

### 2.3 并行化 + 降级链验证

| 维度 | 说明 |
|------|------|
| **机制** | Harness dsh-tool-workflow 支持 `parallel()` hook，可并行编排多个 subagent |
| **实现** | 在 agent preset 中配置 parallel pipeline: [indicators, fundamental] |
| **降级** | 单个 API 失败 → 返回中性默认值，另一个正常返回；agent loop 不中断 |
| **验收** | V1-1: parallel 延迟 ≈ max(indicators, fundamental) << serial(indicators + fundamental) |

### 2.4 G 层 session log consumer

| 维度 | 说明 |
|------|------|
| **机制** | Harness session log 是 append-only 事件流（session.v3.jsonl.zstd） |
| **实现** | 新增 `session-consumer` Cordis plugin，监听 `session/event` 事件，投影为 DreamBuddy G 层执行图 |
| **投影规则** | tool/call → node_execution; tool/result → node_result; step/* → graph_node; agent/pre-step → intent_gate |
| **验收** | V1-3: 从 session log 投影出的执行图与原快照等价 |

### 2.5 LLM 降级链 Model-as-Plugin

| 维度 | 说明 |
|------|------|
| **机制** | Harness 支持通过配置切换 LLM provider（DeepSeek/OpenAI/Pi-AI） |
| **实现** | 在 profile 配置中定义降级链: deepseek-flash → deepseek-chat → fallback-model |
| **验收** | V1-5: 修改配置文件切换 LLM，不改代码 |

---

## 三、技术设计

### 3.1 Python Server 增强

```python
# server.py 新增方法

def _handle_technical_indicators(params):
    """调用经典指标系统 (http://127.0.0.1:8092)
    FAIL-OPEN: 不可达时返回中性默认值
    """
    import urllib.request
    symbol = params.get("symbol", "BTC")
    try:
        url = f"http://127.0.0.1:8092/api/indicators?symbol={symbol}"
        with urllib.request.urlopen(url, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception as e:
        _send_stderr("WARN", f"经典指标系统不可达: {e}")
        return {
            "node_id": "technical_indicators",
            "symbol": symbol,
            "status": "degraded",
            "neutral_default": {"signal": "neutral", "confidence": 0.0},
            "error": str(e),
        }

def _handle_fundamental_analysis(params):
    """调用基本面 API (http://49.233.123.96:3456)
    FAIL-OPEN: 不可达时返回中性默认值
    """
    import urllib.request
    symbol = params.get("symbol", "BTC")
    try:
        url = f"http://49.233.123.96:3456/fundamental/overview?symbol={symbol}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        _send_stderr("WARN", f"基本面 API 不可达: {e}")
        return {
            "node_id": "fundamental_analysis",
            "symbol": symbol,
            "status": "degraded",
            "neutral_default": {"signal": "neutral", "confidence": 0.0},
            "error": str(e),
        }
```

### 3.2 Cordis Plugin: dreambuddy-indicators

```
packages/cordis-plugin-indicators/
├── package.json    # peerDependencies: dsh-tools
├── lib/index.js    # defineTool: get_technical_indicators
└── tsconfig.json
```

关键设计：
- 与 dreambuddy-c1 相同的 IPC 模式
- `@deepseek-ai/dsh-tools` 必须为 peerDependencies（Phase 0 教训）
- 工具参数: `{ symbol: string, indicator_type?: string }`

### 3.3 Cordis Plugin: dreambuddy-fundamental

```
packages/cordis-plugin-fundamental/
├── package.json    # peerDependencies: dsh-tools
├── lib/index.js    # defineTool: get_fundamental_analysis
└── tsconfig.json
```

### 3.4 Session Consumer Plugin

```
packages/cordis-plugin-session-consumer/
├── package.json
├── lib/index.js    # ctx.on("session/event", ...) → 投影 G 层执行图
└── tsconfig.json
```

关键设计：
- 监听 `session/event` 事件
- 将 Harness 事件投影为 DreamBuddy G 层格式
- 写入 DreamBuddy 内部的 session consumer 队列（通过 IPC）
- 不持有交易状态（HC-3）

### 3.5 Profile 配置增强

```yaml
# headless/cordis.patch.yml
- insert:
    - id: dreambuddy-c1
      ...
    - id: dreambuddy-intent-gateway
      ...
    - id: dreambuddy-indicators
      name: dreambuddy-indicators
      config:
        pythonServerPath: "..."
        pythonExecutable: "python3"
    - id: dreambuddy-fundamental
      name: dreambuddy-fundamental
      config:
        pythonServerPath: "..."
        pythonExecutable: "python3"
    - id: dreambuddy-session-consumer
      name: dreambuddy-session-consumer
      config:
        pythonServerPath: "..."
        pythonExecutable: "python3"
```

---

## 四、验收门槛

| 门槛 | 验证方式 | 预期结果 |
|------|---------|---------|
| V1-1 | 并行 vs 串行延迟对比 | parallel ≈ max(api1, api2) << serial(api1 + api2) |
| V1-2 | 故障注入：杀掉 8092 或 3456 | 另一个 API 正常返回，agent loop 不中断 |
| V1-3 | session log 投影 vs 原快照对比 | 执行图节点和边等价 |
| V1-4 | A7/A8 自进化回测对比 | 事件流数据效率提升 |
| V1-5 | 修改配置切换 LLM | 不改代码，切换生效 |
| V1-6 | 集成测试覆盖 HC-2 | 所有硬约束在新架构下仍生效 |

---

## 五、实施顺序

1. **P1-A**: Python server 增强（technical_indicators + fundamental_analysis 方法）
2. **P1-B**: Cordis plugin 创建（indicators + fundamental + session-consumer）
3. **P1-C**: Profile 配置 + 并行化验证（V1-1, V1-2）
4. **P1-D**: Session consumer 实现 + G 层投影验证（V1-3）
5. **P1-E**: LLM 降级链配置驱动验证（V1-5）
6. **P1-F**: 硬约束集成测试（V1-6）
7. **P1-G**: A7/A8 自进化效率验证（V1-4）

---

## 六、硬约束保持

| 硬约束 | Phase 1 保持方式 |
|--------|-----------------|
| HC-1a | 新增 plugin 在 dream-harness-bridge/ 内 |
| HC-1b | Python server 通过 HTTP 调用外部 API，不直接 import DreamBuddy |
| HC-3 | session-consumer 只消费事件流，不持有交易状态 |
| HC-5 | reward 信号仍由 DreamBuddy 内部计算 |
| HC-7 | 所有 HTTP 调用 FAIL-OPEN |

---

## 七、风险与缓解

| 风险 | 缓解 |
|------|------|
| 8092/3456 服务未运行 | FAIL-OPEN 返回中性默认值，测试可 mock |
| session log 事件 schema 不够 | F-12 事件信封模式，payload 是 DreamBuddy 领域类型 |
| 并行化引入竞态 | Python server 是单进程串行处理，Harness 侧并行调用不同方法 |
