# 52-LobeHub 协议集成

> 版本：v0.11.0
> 更新：2026-11-11
> 状态：协议层 / 蒸馏桥 / 脑暴编排器已落地；云端部署（Phase 2）待开工

## 1. 这是什么

52 把 LobeHub 的 agent 协议模式（模型路由 + MCP 消费 + PlanCard 执行语义）以**协议层**形式接入
DreamOS(SACG) → DSH → L0 MCP → REA/涌现 的既有架构，使"接入任意大模型即可驱动现有能力"。

52 **不是**主骨架、**不是**能力实现层、**不是**认知记忆库、**不是**交易系统：

| 项 | 内容 |
|---|---|
| 集成形态 | 内置协议层（唯一前端仍是 3.1-FRONTEND，不部署任何独立 LobeHub 应用） |
| 唯一接口 | MCP（stdio 本地 / SSE 云端），无直连 DB、无直连 Python 模块旁路 |
| 不 fork | 不 vendor `lobehub/lobehub` 源码，只做协议语义对齐 |
| 上游 | 47-MCP 管理系统（L0 能力面唯一事实源）、46-DSH 架构 |
| 下游 | DreamOS/SACG 编排、33-REA / 48-涌现（反思与涌现回流） |

设计全文见 [SPEC.md](SPEC.md)；架构调研与评审见
[REVIEW-20261111-LobeHub代码架构调研与SPEC评审.md](REVIEW-20261111-LobeHub代码架构调研与SPEC评审.md)。

## 2. 目录结构

```text
52-lobehub协议集成/
├── SPEC.md                     # 协议层 SSoT（定位/决策/阶段/契约/风险/验收）
├── README.md                   # 本文件
├── REVIEW-20261111-...md       # 架构调研与 SPEC 评审（R1-R9）
├── decisions/
│   └── ADR-001-脑暴出关.md      # shadow → 限量实盘（live）的出关决策
├── schemas/
│   └── plancard.schema.json    # PlanCard JSON Schema（R8）
├── docs/
│   ├── ENGINEERING_INDEX.md    # 文件地图 / 依赖 / 测试矩阵
│   ├── TECHNICAL_DESIGN.md     # 进程模型 / 门禁评分 / 幂等 / 治理
│   ├── API_SPEC.md             # CLI、PlanCard、outbox、HTTP、MCP 契约
│   └── CHANGELOG.md            # 版本变更记录
├── orchestrator/               # 脑暴编排器（Python，标准库 + 可选 yaml）
│   ├── brainstorm_orchestrator.py  # 主流程 run() + CLI
│   ├── proposers.py                # side-A / side-B 双链提案（N-per-side）
│   ├── plancard.py                 # PlanCard 校验 + DreamOS intent → PlanCard
│   ├── registry_tools.py           # 47 registry 只读工具集
│   ├── scoring.py                  # G1-G4 门禁 / 结构分 / T1-T4 触发器
│   ├── domain_eval.py              # 45 域评测器适配层 + 结构分
│   ├── adjudicator.py              # 论证学裁决器（shadow A/B）
│   ├── debate_client.py            # agent.debate.mcp stdio 客户端
│   ├── router.py                   # 意图路由 r9-v1（零 token）
│   ├── live_policy.py / .json      # ADR-001 三道门 + 周预算账本
│   ├── shadow_batch.py             # shadow 批量跑（定时入口）
│   ├── ops/
│   │   ├── supervisor.py           # 每日守护（launchd 被 TCC 拦截时的替代）
│   │   ├── daily_pipeline.sh       # shadow → bridge 串联
│   │   └── com.dreambuddy.shadow.plist  # launchd 模板
│   └── tests/                      # 78 passed
└── bridge/                     # 蒸馏桥（outbox → cognition record）
    ├── distill_bridge.py           # 校验 + R6 映射 + 游标 + 内容指纹去重
    ├── test_distill_bridge.py      # 20 passed
    └── ops/com.dreambuddy.bridge.plist  # launchd 模板
```

3.1 前端侧协议层能力件（非本目录）：`3.1-FRONTEND/src/lib/agent/{providers,mcp-client,plancard,plan-variant,distill-outbox}.ts`
及 `src/app/api/agent/{chat,plan,brainstorm}/route.ts`。

## 3. 快速开始

### 3.1 跑测试

```bash
cd 52-lobehub协议集成/orchestrator
python3 -m pytest tests -q          # 78 passed

cd ../bridge
python3 -m pytest -q                # 20 passed
```

### 3.2 单次脑暴（shadow）

```bash
cd 52-lobehub协议集成/orchestrator
python3 brainstorm_orchestrator.py --intent "对比两种回撤控制方案" --json-out
```

前置条件：side-A（3.1 `POST /api/agent/plan`，默认 `127.0.0.1:3001`）与
side-B（DreamOS `POST /api/v1/intent`，默认 `127.0.0.1:8000`）同时在线；否则提案失败但流程不崩。

### 3.3 批量 shadow + 蒸馏

```bash
python3 orchestrator/shadow_batch.py --max 2 --n-per-side 2
python3 bridge/distill_bridge.py --once
```

### 3.4 每日守护

```bash
# 前台调试：只看下一次触发时间
python3 orchestrator/ops/supervisor.py --dry-run

# 后台常驻（每日 22:30 触发 shadow → bridge）
nohup python3 orchestrator/ops/supervisor.py >> orchestrator/logs/supervisor.log 2>&1 &

# 停止
kill "$(cat orchestrator/ops/.supervisor.pid)"
```

> launchd 在本机恒返回 `Input/output error (5)`（与 plist 路径无关），因此默认用守护进程；
> `ops/*.plist` 仅作模板，可在有 launchd 注册权限的环境安装。

## 4. 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `SIDE_A_URL` | `http://127.0.0.1:3001` | 3.1 规划 API |
| `SIDE_B_URL` | `http://127.0.0.1:8000` | DreamOS 意图 API |
| `SIDE_A_MODEL` / `SIDE_B_MODEL` | `unknown` / `dreamos-intent-engine` | 多样性校验用 model 标识 |
| `PROPOSER_TIMEOUT_SEC` | `60` | 提案 HTTP 超时 |
| `BRAINSTORM_DEBATE_ROUNDS` | `1` | Debate 轮次 |
| `BRAINSTORM_EXECUTOR_MODULE` | 空 | 实盘执行器模块（须暴露 `execute(card)->dict`） |
| `COGNITION_MCP_CMD` / `COGNITION_MCP_SERVER` | `sys.executable` / 4-MEMORY 壳路径 | recall 取证通道 |
| `BRIDGE_OUTBOX_PATH` / `BRIDGE_SEEN_PATH` | 桥目录下 | 蒸馏桥输入与去重指纹 |
| `ORCHESTRATOR_PY` | `python3` | 3.1 `/api/agent/brainstorm` spawn 的 Python 路径 |

## 5. 已知限制

| 限制 | 影响 | 现状 |
|---|---|---|
| launchd / crontab 被 macOS TCC 拦截 | 无系统级定时 | 用 `ops/supervisor.py` 守护；重启后需重拉 |
| 45 评测器缺领域产物 | `verdict` 恒 `INCONCLUSIVE` | 只做契约接入，不编造分数；待 artifacts 落盘映射 |
| Phase 2 云端部署未开工 | 云端只有 stdio 不可用 | l0_gateway 需包 SSE/HTTP；44 未登记 52 拓扑 |
| 规划期无真实 trace 长跑 | 激活门槛未达 | shadow 累计 2-4 周后评审 |

## 6. 相关文档

- 协议层 SSoT：[SPEC.md](SPEC.md)
- 工程索引：[docs/ENGINEERING_INDEX.md](docs/ENGINEERING_INDEX.md)
- 技术设计：[docs/TECHNICAL_DESIGN.md](docs/TECHNICAL_DESIGN.md)
- 接口契约：[docs/API_SPEC.md](docs/API_SPEC.md)
- 变更记录：[docs/CHANGELOG.md](docs/CHANGELOG.md)
- 出关决策：[decisions/ADR-001-脑暴出关.md](decisions/ADR-001-脑暴出关.md)
