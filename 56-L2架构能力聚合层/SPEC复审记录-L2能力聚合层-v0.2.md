# SPEC 复审记录 — 56-L2 架构能力聚合层 v0.1 → v0.2

- **复审对象**: [SPEC-56-L2架构能力聚合层.md](./SPEC-56-L2架构能力聚合层.md) v0.2 + [docs/TECHNICAL_DESIGN.md](./docs/TECHNICAL_DESIGN.md) v0.2
- **复审日期**: 2026-11-16
- **复审依据**: [SPEC评审报告-L2能力聚合层-v0.1.md](./SPEC评审报告-L2能力聚合层-v0.1.md) 复审清单 R1–R6
- **复审方式**: 逐条对照修订 + 独立复跑核验（未直接采信修订者自述）
- **复审结论**: ✅ **P0/P1 阻断全部关闭，通过** —— 可进入 P0-1（`L2Envelope` 落地）。R7（机器可读能力清单）与 P2 建议项按计划后置。

---

## 一、逐条复核

| # | 原问题 | 修订动作 | 独立核验证据 | 结论 |
|---|---|---|---|---|
| **R1** | 命令数 17、插件数 3 均错 | §1.1 改 **18**；`L2-P02` 改 **13 条 approved（实测 2026-11-16）** | 命令字典逐键枚举：8 个 `subagent.*` + `c-drive` + `c-drive.debate` + `synthesizer` + `orchestrator` + `orchestrator.status` + `knowledge.search` + `skill.index` + `user.memory` + `data.dal_query` + `shell.stats` = **18**；`grep -c 'status: "approved"' plugin_whitelist.yaml` = **13** | ✅ 关闭 |
| **R2** | `L2-E09` 把已实现的校验报成缺口 | 状态改 ✅，补 `validate_mcp_registry.py#L379-L435`；GAP-11 改写为「上限口径 10 vs 15」 | 校验器 L409 `0 < len(role_tools) <= max_tools_per_shell`；L184 取 `enums.max_tools_per_shell`，yaml L1177 = **15** | ✅ 关闭（并衍生新问题，见 §二） |
| **R3** | `cognition_signal` 零实现却判 🟡 | SPEC §0 第 4 条、§4.1 行改 ⬜；新增 **GAP-13**；P1-1 升级为「裁决层落地」 | 全仓 `*.py/*.ts/*.tsx` 再检索 `cognition_signal`：**仅命中 56 文档自身**，无实现代码 | ✅ 关闭 |
| **R4** | 45 门禁标 ✅ 过强；25–28 无证据 | 45 降 🟡（注入式，GAP-14）；25–28 补 `app.py` 行号 + env 变量；表下加 ✅ 口径说明 | 25 `#L307 STRATEGY_GEN_PORT=8095`；26 `#L467 STRATEGY_LIB_PORT=8093`；27 `#L568 GOVERNANCE_PORT=8094`；28 `#L460 SIGNAL_TRIGGER_PORT=8096`；45 `api/server.py#L11` | ✅ 关闭 |
| **R5** | 「C 层双实现」表述误导为技术债 | 改为「两宿主两实现」并给两侧落点；新增 **Q5** | `dreamos/apps/trading_agent/agent.py#L39` 导入 `core.compute.GraphExecutor`；34 侧 `sacg_orchestrator` → `CDriveV3Router.run_v3` | ✅ 关闭 |
| **R6** | 先冻结信封、后问是否合并 | §4.3 增 **D1（已采 A：在 0.1 上扩字段）**；§7 删除 Q1 并重排 Q1–Q5 | SPEC §4.3 决策块与 §7 表已一致，无残留「Q1 合并」表述 | ✅ 关闭 |

**复跑命令**（任何人可复现）：

```bash
python3 - <<'PY'
import re
s=open('34-前端应用训练系统/core/dsh_frontend_bridge.py').read()
print(len(re.findall(r'^\s{4}"([a-z0-9_\-\.]+)":\s*\{', s, re.M)))   # 期望 18
PY
grep -c 'status: "approved"' 53-DSH插件模块/plugin_whitelist.yaml        # 期望 13
grep -n 'max_tools_per_shell' 47-MCP管理系统/registry/mcp_capabilities.yaml  # 期望 15
```

---

## 二、复审中新发现的问题（v0.1 未覆盖）

### N1｜角色工具上限口径冲突：注册表 15 / 3+3 文档 ≤10

- **事实**：`mcp_capabilities.yaml` `enums.max_tools_per_shell: 15`，而 [3+3架构模块映射.md](../1-ARCHITECTURE/3+3架构模块映射.md) §二.2 写「Worker 角色池（≤10 工具/角色）」。校验器按 **15** 执行，即治理意图（≤10）被历史默认值覆盖。
- **处理**：已登记为 **GAP-11 + Q4**，建议采 B（以 ≤10 为准并改注册表）——收紧配额属治理动作，需一次性评估现有 5 个角色是否超 10。
- **风险等级**：P2（不阻断 P0，但影响工具面治理口径）。

### N2｜45 门禁生产注入点无证据

- **事实**：`gate_45_adapter.py` 明确 `submit_fn/poll_fn` 由调用侧注入，文件本身不持网络与存储；未找到生产侧注入调用点。
- **处理**：已登记 **GAP-14**，状态 🟡。若要回 ✅，需给出调用侧文件行号或一次真实 submit→poll 日志。

---

## 三、未闭环项（按计划后置，不计入本次阻断）

| 项 | 内容 | 计划 |
|---|---|---|
| R7 | `56/config/l2_capability_manifest.yaml` 机器可读能力清单 + 校验脚本 | P0-1 之后（与信封同批，避免二次改表） |
| B10 | 「用户问题 → 技术含义 → 允许回答」映射表 | P1 文档补强 |
| B11 | §7.3 验收命令脚本化（`scripts/accept_l2.sh`） | P0-1 同批 |
| B12 | 逐能力禁止项（如「`l2.dreamos` 不下发原始节点权重」） | P1 |
| B13 | 48 verdict 快照标注日期 | 已顺手在能力表注「引自 48 README 2026-11-09」的状态未改，留 P2 |

---

## 四、评分变化

| 维度 | v0.1 | v0.2 | 变化原因 |
|---|---|---|---|
| 架构合理性 | 4.2 | 4.2 | 未改架构，仅修事实 |
| 事实准确性 | 2.5 | **4.2** | 4 处硬错误全部修正，且新增 2 项由「过度自信」转为「显式待核」 |
| 契约严谨度 | 3.6 | **4.0** | D1 消除自相矛盾；IF-L2-1~4 与 §7 一致 |
| 可验收性 | 3.4 | **3.8** | 端口/命令/插件数均带复跑命令；仍缺脚本化（B11） |
| 风险控制 | 3.8 | **4.0** | 新增 GAP-13/14 把隐藏风险显式化 |
| 兼容性 | 4.0 | 4.0 | 未变 |
| **综合** | **3.6** | **4.0** | **通过** |

---

## 五、结论与下一步

1. **P0（B1–B4）与 P1（B5–B9 中除 R7 外）全部关闭**，文档可作为实施依据。
2. **不宣称「L2 已完成」**：当前结论是「文档与代码事实一致」，实现缺口仍为 GAP-01（信封）、GAP-13（裁决层）、GAP-03（`l2.dsh`）三项。
3. **下一步**：按 TECHNICAL_DESIGN §7.1 开 **P0-1 `L2Envelope` 落地**（12 个 DreamOS 端点 + 4 个 L2 壳），同批交付 `scripts/accept_l2.sh` 与信封回归测试。
4. **Q4（角色上限 15→10）** 建议单独一次提交，避免与信封改动混在一个变更里。

---

## 六、补记（同日）：GAP-11 / GAP-14 已修复

### GAP-11 → ✅ 关闭

| 项 | 内容 |
|---|---|
| 改动 | `mcp_capabilities.yaml` enums 增 `max_tools_per_role: 10`（单壳上限仍 15）；`validate_mcp_registry.py` 读取该值并用于角色检查（L184 解析 / L~409 判定），错误文案同步为「每角色上限 10」 |
| 正向证据 | 真实注册表复跑：`0 ERR / 0 WARN`，退出码 0；现有 9 个角色工具数最大 = **10**（engineer），无一超限 |
| 负向证据 | 构造 11 工具角色 `_negtest` 注入临时注册表 → 退出码 1，报 `11 工具超出每角色上限 10（ADR-4）`，证明新校验真实生效 |
| 决策 | Q4 采 B 并落地；单壳 15 与角色 10 不再共用一个变量 |

### GAP-14 → ✅ 关闭

| 项 | 内容 |
|---|---|
| 改动 | 新增 [gate_45_runtime.py](../../34-前端应用训练系统/core/gate_45_runtime.py)：`resolve_settle_gate()` 解析开关并组合 transport；接入 2 处生产 settle——`data_query_executor.py#L1718`、`settle_case_cli.py#L50` |
| 默认关 | `DREAM_GATE_45_MODE` 未设置 → 返回 `None`，`settle` 与接线前字节等价（H2）；两种导入模式（`core.*` / 34-core 直连）均实测返回 `None` |
| 不伪造 payload | 45 `/submit` 要求 `category/object_type/object_ref/submitter/purpose/spec_id/env_manifest`；`spec_id` 与 `env_manifest` 属业务口径，未注册 `register_payload_builder` 时直接返回 `None`（FAIL-OPEN），不在运行时编造默认值 |
| 测试 | 新增 `tests/test_gate_45_runtime.py`（5 例：默认关 / 非法模式 / 无 builder / shadow 记录 BLOCK 仍放行 / hard 受 `enable_gate_45_hard` 约束）；与 `test_gate_45_adapter.py` 合并复跑 **17 passed** |
| 残留（配置项，非缺口） | 启用前需业务侧注册 payload builder 并设置 `DREAM_GATE_45_MODE`；本轮不替业务决定 `spec_id/env_manifest` |

### 文档同步

- TECHNICAL_DESIGN v0.3：§1.2 45 门禁回 ✅、§2.2 `L2-E09` 改角色上限 10、§5 工具面治理改口径、§6 GAP-11/14 标关闭、§7.1 P2 去掉已收口项。
- SPEC v0.3：Q4 标「已决 B（已落地）」；G-L2-4 补注入点。

