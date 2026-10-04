# 链路打通实施 Spec — 前端 → DreamOS → dream-harness-bridge → DSH

> **版本**: v0.1（待用户审阅）
> **状态**: 📋 调研完成，待批准实施
> **日期**: 2026-09-23
> **前置文档**:
> - [SPEC.md](../SPEC.md) v0.4（项目起点 Spec，硬约束 HC-1~HC-11）
> - [docs/phase0-report.md](./phase0-report.md)（Phase 0 POC 全绿）
> - [docs/PHASE1_SPEC.md](./PHASE1_SPEC.md) v1.1（V1-1/2/5/6 PASS）
> **定位**: 针对 6 个链路缺失项的修复方案 + 验收标准 + 实施顺序
> **调研方法**: recall 认知记忆 + 3 个并行 Explore agent 代码审计

---

## 一、文档定位

本 Spec 是 SPEC.md v0.4 的**实施层补充**，不修改原 Spec 的设计原则和硬约束。

**解决的问题**：SPEC.md 定义了分层嵌入架构（路径 E）和 Phase 划分，但未覆盖"前端如何连到后端"的 HTTP 层细节。链路审计发现 6 个缺失项，本 Spec 给出修复方案。

**不包含**：Phase 2 TS 重写评估、DreamBuddy-v2 核心代码修改（HC-1a）。

---

## 二、链路现状审计（修正版）

### 2.1 五层架构现状

| 层 | 路径 | 接入状态 | 关键发现 |
|---|------|---------|---------|
| 前端 | `3-FRONTEND/` + `3.1-FRONTEND/` | ✅ 完整 | bridge-client.ts 默认连 `:3847`；intent-schema.ts 35型 SSOT 完整 |
| Bridge API (Flask) | `dream-harness-bridge/integration/run_api_server.py` | ⚠️ 端口不匹配 | 默认 `:8000`，前端连 `:3847`，**连不上** |
| Python IPC Server | `packages/python-server/server.py` | ⚠️ 2/21 mock | 21 个 method，19 已接入真实 DreamOS，仅 `c1_scan`/`intent_gateway` 是 POC_mock |
| DreamOS | `1-ARCHITECTURE/dreamos/` | ✅ 完整 | SACG 四层 + IntentEngine + CapabilityRouter + 交易节点全在 |
| DSH (Cordis) | `.dsh-home/profiles/` | ⚠️ web profile 不对称 | headless 8 enabled，web 仅 jev-judge 1 enabled |

### 2.2 三端口生态（新发现）

审计发现项目存在**三个独立 HTTP 服务，彼此无连接**：

| 端口 | 服务 | create_app 来源 | 前端是否连接 |
|------|------|---------------|-------------|
| `:3847` | `6-TRADING/bridge/run_server.py` | `bridge/api/dream_api_server.py` | ✅ 前端 bridge-client 默认连这里 |
| `:8000` | `dream-harness-bridge/integration/run_api_server.py` | `dreamos.apps.api_server.create_app` | ❌ 前端不连这里（端口不匹配） |
| `:3080` | DSH web profile (Cordis) | Cordis 内部 | ❌ 前端不连，仅 jev-judge |

**这是链路断裂的根因**：前端请求 `:3847`，但 dream-harness-bridge 的算法增强层在 `:8000`，两个服务完全独立。

### 2.3 路径三重不匹配（新发现）

前端 `IntentAPI.route()` 请求 `POST /api/intent/route`，但三个服务的 intent 路由注册各不相同：

| 服务 | intent_bp 注册路径 | 与前端是否匹配 |
|------|-------------------|---------------|
| 前端 bridge-client | 请求 `/api/intent/route` | — |
| 6-TRADING/bridge (`:3847`) | 注册在 `/route`（无 /api 前缀） | ❌ |
| run_api_server (`:8000`) | 注册在 `/intent/route`（url_prefix=`/intent`） | ❌ |

**即使端口对齐，路径也不匹配**。需要统一路由前缀。

---

## 三、缺失项修复方案

### P0-1: c1_scan + intent_gateway 接入真实 DreamOS

**现状**：server.py 21 个 IPC method 中，仅 2 个是 POC_mock：
- `_handle_c1_scan` (L177-215)：返回模拟技术指标
- `_handle_intent_gateway` (L612-672)：关键词匹配模拟意图识别

**真实接口已确认**：
- `C1TechScanNode.execute_core(state: State) -> NodeResult`（c1_tech_scan.py L23-38），从 `state.market` 提取数据（L218-224），与 `_handle_c2_momentum` 调用模式完全一致
- `IntentEngine.recognize(user_message, market, symbol, ...) -> IntentResult`（intent_engine.py L121-142）
- `canon_intent_bridge.objective9ToCanon()` 已实现 9型→35型转换（L283-291）

**重要发现**：`execute_c_chain` (L287-346) 内部已通过 GraphExecutor 真实调度 C1TechScanNode。单独的 `c1_scan` mock 是冗余的——修复后应直接调用 C1 节点，与 c2/c3 模式对齐。

**修复方案**（参照 `_handle_c2_momentum` 30 行模式）：

```python
# server.py _handle_c1_scan 改造
def _handle_c1_scan(params: dict[str, Any]) -> dict[str, Any]:
    market_data = params.get("market_data") or params.get("mkt") or {}
    symbol = params.get("symbol", "BTC")
    if not market_data:
        market_data = _get_market_data_for_chain(symbol)  # 复用 execute_c_chain 的数据获取
    if _DREAMOS_ARCH_DIR not in sys.path:
        sys.path.insert(0, _DREAMOS_ARCH_DIR)
    from dreamos.capabilities.trading.nodes.c1_tech_scan import C1TechScanNode
    from dreamos.shared.state import State
    state = State(market=market_data)
    node = C1TechScanNode()
    node_result = node.execute_core(state)
    return {
        "node_id": "C1_technical_scan", "symbol": symbol,
        "direction": node_result.direction, "confidence": node_result.confidence,
        "outputs": node_result.outputs,
        "phase": "real_dreamos_node",
    }
```

```python
# server.py _handle_intent_gateway 改造
def _handle_intent_gateway(params: dict[str, Any]) -> dict[str, Any]:
    user_input = params.get("user_input", "")
    market = params.get("market", {})
    symbol = params.get("symbol", "")
    if _DREAMOS_ARCH_DIR not in sys.path:
        sys.path.insert(0, _DREAMOS_ARCH_DIR)
    from dreamos.core.sense.intent_engine import IntentEngine
    from dreamos.core.capability.router import CapabilityRouter
    from dreamos.core.capability.registry import get_default_registry
    from integration.canon_intent_bridge import objective9ToCanon, dreamOSToCanon
    engine = IntentEngine()
    intent_result = engine.recognize(user_message=user_input, market=market, symbol=symbol)
    canon_intent = objective9ToCanon(getattr(intent_result, "objective_type", ""))
    registry = get_default_registry()
    router = CapabilityRouter(registry, default_capability_id="trading")
    routing = router.route(intent_result)
    return {
        "node_id": "S_intent_gateway",
        "canon_intent": canon_intent,
        "strategy_intent": getattr(intent_result, "intent_type", "UNCERTAIN"),
        "confidence": getattr(intent_result, "confidence", 0.0),
        "routing": routing.to_dict(),
        "phase": "real_dreamos_intent_engine",
    }
```

**工作量**：~60 行代码（2 个 method 各 30 行），参照已有模式，低风险。

**验收标准**：
- [ ] `c1_scan` 返回 `phase: "real_dreamos_node"`，不再含 `POC_mock`
- [ ] `intent_gateway` 返回 `phase: "real_dreamos_intent_engine"`，含 `canon_intent` 字段
- [ ] 单测覆盖：正常输入 + 异常输入（FAIL-OPEN 兜底）
- [ ] HC-7：DreamOS import 失败时返回中性默认值 + 6 层堆栈日志

---

### P0-2: 三端口统一 + 路径对齐（核心决策点）

**问题**：前端 `:3847` ↔ dream-harness-bridge `:8000` 端口不匹配 + `/api/intent/route` ↔ `/route` ↔ `/intent/route` 路径不匹配。

**方案选型**：

| 方案 | 描述 | 优点 | 缺点 |
|------|------|------|------|
| **A（推荐）** | dream-harness-bridge Flask 作为统一 HTTP 入口：run_api_server 默认端口 8000→3847，intent_bp url_prefix /intent→/api/intent | 前端零改动；统一入口清晰；6-TRADING/bridge 可逐步废弃 | 需迁移 6-TRADING/bridge 的端点到 dream-harness-bridge |
| B | 6-TRADING/bridge (:3847) 保持前端入口，内部转发到 dream-harness-bridge (:8000) | 前端零改动；6-TRADING/bridge 不动 | 多一跳转发延迟；两个 Flask 服务并存，角色重叠 |
| C | DSH web (:3080) 作为统一入口，通过 Cordis plugin 调用 Flask | 符合 SPEC.md 分层嵌入理念 | DSH web 无通用 HTTP API 层（仅 jev-judge）；工作量最大 |

**推荐方案 A**：理由——dream-harness-bridge 是 SPEC.md 定义的新项目主入口，6-TRADING/bridge 是遗留服务。统一到 dream-harness-bridge 符合架构演进方向。

**方案 A 实施细节**：

1. `run_api_server.py` 默认端口 8000→3847（L153: `os.environ.get("DHB_API_PORT", "3847")`）
2. intent_bp 注册 url_prefix `/intent`→`/api/intent`（L113: `app.register_blueprint(intent_bp, url_prefix="/api/intent")`）
3. 6-TRADING/bridge 的端点（/api/market/*, /api/trade/*, /api/skill/*）迁移到 dreamos.apps.api_server 或通过 Blueprint 注册
4. DSH :3080 不暴露给前端，仅通过 AlgorithmLayerBridge IPC 内部调用

**验收标准**：
- [ ] 前端 bridge-client.ts 零改动，`POST http://127.0.0.1:3847/api/intent/route` 可达
- [ ] 6-TRADING/bridge 的核心端点（market/trade/skill）在 :3847 可用
- [ ] DSH :3080 不直接暴露给前端

> ⚠️ **需用户决策**：方案 A/B/C 选择。本 Spec 后续 P2-1/P2-2 基于方案 A 编写。

---

### P1-1: web profile 对齐 headless

**现状**：`web/cordis.patch.yml` 仅 jev-judge enabled，dreambuddy-c1/intent-gateway/graph-planner/reflector 全部 `disabled: true`。headless profile 8 个 enabled。

**修复方案**：将 web profile 的 4 个 disabled 改为 false（或删除 disabled 字段），与 headless 对齐。

**工作量**：改 4 行 YAML。

**验收标准**：
- [ ] web profile 启用 dreambuddy-c1/intent-gateway/graph-planner/reflector
- [ ] `dsh web` 启动后 4 个 plugin 可加载
- [ ] 与 headless profile 行为一致

---

### P1-2: 意图三端一致性端到端测试

**现状**：
- 映射表已完整：intent-schema.ts（35型 SSOT）+ canon_intent_bridge.py（Python 三张表镜像）+ taxonomy.py（6×30 定义）
- 现有测试：test_canon_intent_bridge.py 覆盖 CANON_TO_DREAMOS（35→7型）和 KERNEL_TO_CANON（6×30→35型），有 round-trip 测试但**只测 7 型代表意图**（L188-221），非完整 35 型往返
- algorithm_enhanced_agent.py L232-255 已实际调用 `dreamOSToCanon()` 做 7型→35型转换
- **缺口**：缺完整 35 型 round-trip 测试 + TS↔Python 映射表逐条一致性自动化校验

**修复方案**：

1. **扩展 round-trip 测试**：35型→7型→35型 全覆盖（当前只测 7 型代表）
2. **TS↔Python 一致性校验脚本**：导出 TS 映射表为 JSON，与 Python 断言逐条对比，防止 drift
3. **三端闭环 E2E 测试**：前端识别 35型 → bridge 转 7型 → DreamOS IntentEngine → 6×30 → bridge 转回 35型

**工作量**：~150 行测试代码（扩展现有 test_canon_intent_bridge.py）。

**验收标准**：
- [ ] 35 型 round-trip 全覆盖（35型→7型→35型，验证可接受损耗）
- [ ] TS↔Python 映射表逐条一致（CI 防 drift）
- [ ] 三端闭环 E2E：前端输入 → DreamOS 输出 → 前端回显，意图不丢失

---

### P2-1: 结果回流路径（DreamOS → 前端）

**问题**：DreamOS 执行结果如何回流到前端？当前无设计。

**依赖**：P0-2 端口统一后，Flask :3847 是统一入口。

**方案选型**：

| 方案 | 描述 | 优点 | 缺点 |
|------|------|------|------|
| **SSE（推荐）** | Flask 提供 `GET /api/task/{id}/stream` SSE 端点，DreamOS 执行进度流式推送 | 单向流式，简单，与 HTTP 同端口 | 不支持双向交互 |
| 轮询 | 前端轮询 `GET /api/task/{id}/status` | 最简单 | 延迟高，浪费请求 |
| WebSocket | 双向 `ws://.../api/task/{id}/ws` | 实时双向 | 复杂度高，Flask 需gevent |

**推荐 SSE**：单向流式足够（DreamOS 执行结果→前端展示），简单且与 Flask 同端口。

**实施细节**：
- Flask 新增 `GET /api/task/{task_id}/stream` SSE 端点
- AlgorithmEnhancedAgent 执行时通过 IPC 把进度写入 task_store
- SSE 端点从 task_store 读取并推送给前端
- 前端 bridge-client.ts 新增 `TaskAPI.subscribe(taskId)` 使用 EventSource

**验收标准**：
- [ ] 前端可通过 SSE 接收 DreamOS 执行进度
- [ ] 连接断开自动重连
- [ ] FAIL-OPEN：DreamOS 异常时 SSE 推送错误事件，不挂起连接

---

### P2-2: DSH web vs Flask 角色分工

**依赖**：P0-2 方案 A 选定后，角色自然清晰：

| 服务 | 端口 | 角色 | 面向 |
|------|------|------|------|
| dream-harness-bridge Flask | :3847 | HTTP API 入口（前端直连） | 前端 |
| DSH Cordis | :3080（内部） | Agent runtime（Cordis plugin 编排） | Flask IPC 内部调用 |
| 6-TRADING/bridge | 废弃 | 遗留服务，端点迁移后下线 | — |

**原则**：DSH :3080 不直接暴露给前端，仅通过 AlgorithmLayerBridge（IPC stdio）被 Flask 内部调用。符合 HC-10（领域代码零 Harness 依赖）的镜像——Harness 不暴露 HTTP 给前端。

**验收标准**：
- [ ] 前端不直接请求 :3080
- [ ] Flask :3847 通过 IPC 调用 DSH Cordis plugin
- [ ] 6-TRADING/bridge 核心端点迁移完成后标记 deprecated

---

## 四、实施顺序与依赖图

```
Phase A (基础修复，无依赖):
  ├── P1-1: web profile 对齐 headless        [极小·改4行YAML]
  └── P0-1: c1_scan + intent_gateway 接入     [小·~60行代码]

Phase B (核心架构决策，需用户审批):
  └── P0-2: 三端口统一 + 路径对齐             [中·方案A/B/C选型]
        ├── 依赖: 用户决策方案 A/B/C
        └── 阻塞: P2-1, P2-2

Phase C (验证与回流，依赖 P0-2):
  ├── P1-2: 意图三端一致性测试                [小·~150行测试]
  ├── P2-1: 结果回流 SSE                      [中·新端点]
  └── P2-2: DSH vs Flask 角色分工             [依赖P0-2方案A]
```

**建议实施顺序**：
1. Phase A 并行启动（P1-1 + P0-1 无依赖，可立即开工）
2. Phase B 用户审批方案后启动（P0-2 是架构决策点）
3. Phase C 在 P0-2 完成后启动（P1-2/P2-1/P2-2 依赖端口统一）

---

## 五、硬约束遵守清单

| 硬约束 | 本 Spec 如何遵守 |
|--------|-----------------|
| HC-1a | 所有修改在 dream-harness-bridge/ 内，不修改 dreamos/ 核心代码（server.py 在 packages/python-server/ 内） |
| HC-1b | c1_scan/intent_gateway 通过 `import dreamos.*` 调用，不修改 dreamos |
| HC-7 | 所有 DreamOS import 失败时 FAIL-OPEN 返回中性默认值 |
| HC-9 | Flask 是透传层，不包含交易判断逻辑；判断在 DreamOS 内部 |
| HC-10 | dreamos/ 零 Harness 依赖；Flask 不 import Cordis 类型 |

---

## 六、风险与缓解

| 编号 | 风险 | 级别 | 缓解措施 |
|------|------|------|---------|
| R-C1 | 6-TRADING/bridge 端点迁移遗漏导致前端功能缺失 | 中 | 迁移前做端点全量对比，保留 :3847 兼容期 |
| R-C2 | C1TechScanNode 依赖外部数据源（8092 indicators） | 低 | 复用 execute_c_chain 的 `_get_market_data_for_chain` FAIL-OPEN 策略 |
| R-C3 | IntentEngine 输出格式与 canon_intent_bridge 不匹配 | 中 | objective9ToCanon 已覆盖 9型→35型，E2E 测试验证 |
| R-C4 | web profile 启用 4 plugin 后 DSH web 启动失败 | 低 | headless profile 已验证 8 plugin 可加载 |
| R-C5 | SSE 长连接在 Flask 默认开发服务器下不稳定 | 中 | 生产用 gunicorn + gevent worker，或 gunicorn stream 端点单独配置 |

---

## 七、开放问题（需用户决策）

1. **P0-2 方案选型**：A（dream-harness-bridge 统一入口）/ B（6-TRADING/bridge 转发）/ C（DSH web 统一）？
2. **P2-1 回流方案**：SSE / 轮询 / WebSocket？
3. **6-TRADING/bridge 迁移范围**：核心端点（market/trade/skill）全迁移还是分批？
4. **web profile 启用 4 plugin 后**：DSH web 是否需要暴露给浏览器使用（影响 P2-2 角色分工）？
