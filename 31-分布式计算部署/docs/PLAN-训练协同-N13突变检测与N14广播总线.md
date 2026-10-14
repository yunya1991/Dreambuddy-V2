# PLAN — 训练协同：N13 突变检测器 + N14 广播总线（TDD 落地）

- **状态**：待评审（用户已确认优先级：N13/N14 从 P1 提升为 **P0**）
- **日期**：2026-10-14
- **关联**：
  - [RESEARCH-训练协同-隔离单训与突变广播同步.md](./RESEARCH-训练协同-隔离单训与突变广播同步.md)（评估结论 §4.2/§4.3/§10）
  - [SPEC-分布式计算协同部署方案.md](./SPEC-分布式计算协同部署方案.md) §7.1 + §12.5（D-14~D-19）
  - [STATUS-已实现待实现清单.md](./STATUS-已实现待实现清单.md) §3.2
  - [SPEC-本地远端双写分叉治理与torch可用性.md](./SPEC-本地远端双写分叉治理与torch可用性.md)（复用 GeneVersionManager）

---

## 0. 背景与范围

三层异构协同下，"前端层=堆算力（两端都训练）"采取**隔离单训**。用户新想法（挖矿式突变广播）经评估后定为 **D-14 混合范式**：周期兜底 + 突变即时广播。本 PLAN 落地其**承载层**：

- **N13 MutationDetector**：判定"突变"（z>3 且 DSR≥0.95 或 t>3.0，+ 冷却窗 + 二次确认）
- **N14 广播总线 + 6h 兜底心跳**：Redis 承载 + 接收端「择优 + 部分迁移(1–5%)」+ last-known-good + 多样性预算

**范围外（YAGNI）**：完整联邦学习（N9）、多节点 ring 拓扑（N4/O5）、自动重训、云端推理改造。

---

## 1. 设计基线（已确认硬约束）

| 编号 | 约束 |
|---|---|
| D-16 / Q-6 | 突变阈值 **严格档**：相对改善 **z>3** 且（**DSR≥0.95** 或 **Harvey-Liu t>3.0**）+ **冷却窗** + **二次确认** |
| D-17 | 拉齐 = **择优 + 部分迁移(1–5%) 优先** → 合并（仅同初始化+验证门禁）→ warm-start；**禁止全量覆盖** |
| D-18 | 回滚 = last-known-good + GeneVersionManager |
| D-19 / Q-5 | 数据前提 = **同源异构**（非 IID） |
| Q-7 | 兜底心跳 = **6 小时** |
| HC-1a / HC-9 | FAIL-OPEN、零回归、模块化开关默认 OFF |

---

## 2. N13 MutationDetector 设计

### 2.1 接口（新模块 `phase8/mutation_detector.py`）

```python
@dataclass(frozen=True)
class MutationConfig:
    eps_rel: float = 0.015        # 相对改善下限（1–2%）
    z_threshold: float = 3.0
    cooldown_sec: int = 1800
    confirm_runs: int = 2
    min_samples_by_level: dict = None   # L0≥30 / L1≥50 / L2≥100
    min_samples_trading: int = 250      # 子交易系统层（金融域建议，取严）
    layer: str = "frontend"             # frontend | subsystem | cognition

@dataclass(frozen=True)
class MutationDecision:
    decision: bool
    reason: str                   # "ok" | "below_eps" | "below_z" | "cooldown" | "unconfirmed" | "insufficient_samples" | "failopen"
    delta_rel: float
    z: float
    dsr: float | None
    t_stat: float | None
    confirmed: bool

class MutationDetector:
    def __init__(self, config: MutationConfig): ...
    def evaluate(self, history: list[float], candidate: float,
                 campaign_n: int = 1, layer_stats: dict | None = None) -> MutationDecision: ...
```

### 2.2 判据流程（顺序短路，任一不满足即不广播）

```
1. 样本量门禁：len(history) ≥ min_samples（否则 insufficient_samples）
2. 相对改善：delta_rel = (prev - candidate)/|prev| > eps_rel        （否则 below_eps）
3. z-score：z = delta_rel / std(近 N 期 EMA 残差) > z_threshold     （否则 below_z）
   （可选增强：互信息/转移熵，见研究报告 §10）
4. 统计门禁（layer=subsystem/trading）：DSR≥0.95 或 Harvey-Liu t>3.0
5. 冷却窗：距上次广播 < cooldown_sec                                （否则 cooldown）
6. 二次确认：连续 confirm_runs 次均超阈                             （否则 unconfirmed）
→ decision=True
```

### 2.3 失败语义（HC-1a）

- 检测器抛异常 / 依赖不可用 → **返回 `decision=False`（failopen，不广播，不阻塞训练）**，并写 WARN 日志。
- 开关：`module_switches` 新增 `MUTATION_DETECT`（**默认 OFF**）。

---

## 3. N14 广播总线 + 6h 兜底心跳 设计

### 3.1 消息契约（`phase8/sync_bus.py`）

```
Redis Stream: dreambuddy:sync:mutation    （consumer group per node：XADD / XREADGROUP）
消息体 (JSON)：
{
  "schema": 1,
  "node": "cloud|local",
  "layer": "frontend|subsystem|cognition",
  "metric_name": "val_loss",
  "prev": 0.1234, "current": 0.1180,
  "delta_rel": 0.0437, "z": 4.2, "dsr": 0.97, "t_stat": 3.4,
  "checkpoint_ref": "minio://models/xxx/step-1200.pt",   // 仅传"择优检查点引用"，不传全模型本体
  "weights_delta_ref": "minio://deltas/xxx/lora-delta.bin", // N8：优先传增量
  "digest": "sha256:9f2c…",            // 【D-21 强制】内容寻址
  "base_version": "v-3f1a9c22",        // 【D-21 强制】基线版本
  "idempotency_key": "sha256:9f2c…:v-3f1a9c22",  // 【D-21 强制】幂等键
  "version": "v-<sha8>",
  "ts": 1791966000
}
```

### 3.2 接收端应用（`apply(event)`）——「拉齐」按 D-17 顺序降级

```
① 择优 + 部分迁移（首选）：以 event.checkpoint_ref 对本地做部分迁移（迁移率 1–5%），
   本地保留自身继续训练，不整体替换。
② 合并（仅当 同架构+同初始化 且 验证门禁通过）：SLERP / 加权 / DiLoCo 外层动量累积；
   合并后必须在共同验证集评估，劣于领先者 → 退化为 ①。
③ warm-start：以领先者权重初始化继续训练。
✗ 全量覆盖：禁止（除非 ① ② ③ 均不可用，且记为异常处置）。
```

**验证门禁**：每次 apply 后记录 `val_loss_before/after`；劣于 before → 回滚（last-known-good）。

### 3.3 兜底心跳（6h）

- 云端：`dreambuddy-sync-heartbeat.timer`（`OnUnitActiveSec=6h`）→ oneshot 执行 `heartbeat_rebase()`
- 本地：`com.dreambuddy.sync-heartbeat.plist`（`StartInterval=21600`）
- 动作：**低幅迁移（rebase）**——拉取对端最新择优检查点做小幅对齐（不等同全量覆盖），并**重算多样性预算**。

### 3.4 多样性预算（防"同步化死亡"，研究报告 §10）

- 指标：两端参数/伪梯度 **余弦相似度** + 输出 **KL**。
- 触发：余弦 > 0.99 且指标无差异 → emit `DiversityAlert` → 注入噪声/换种子/换数据窗口（PBT explore 语义）+ 上调迁移率。
- 只读告警优先（默认不自动动作），自动动作由开关 `DIVERSITY_GUARD`（**默认 OFF**）控制。

### 3.5 持久化与回滚

- `last_known_good` 注册表：复用 **GeneVersionManager** 快照，每次 apply 前后各存一版。
- 消息至少一次消费（Streams）；消费侧幂等（按 `idempotency_key` 去重）。
- **atomic swap**：热加载以内容寻址路径 + 原子切换（D-21），失败即切回 LKG。

### 3.6 策略薄接口（D-20，评审定稿）

不引入 Flower 本体，自写 **≤1 文件**薄接口 `phase8/sync_strategy.py`，抽象 **4 钩子**：

```python
class SyncStrategy(Protocol):
    def select(self, local_metrics, remote_event): ...        # 择优：选本地还是对端
    def partial_migrate(self, local_ckpt, remote_ckpt, rate): ...  # 部分迁移（rate ≤ 5%）
    def merge(self, local_ckpt, remote_ckpt): ...             # 仅同初始化 + 验证门禁
    def warm_start(self, remote_ckpt): ...                    # 退化路径
```

**借鉴 OpenDiLoCo（D-24）**：把"突变广播"形式化为**事件化 outer step**（inner = 本地多步 SGD；outer = 周期/事件同步伪梯度），与现有混合同步同构。

### 3.7 压缩策略（D-22，评审定稿）

- 6h 心跳：**只传元数据/哈希（必开）**。
- 突变大 payload：top-k 稀疏 + 1-bit/SignSGD 量化 → **默认 OFF**（开关 `SYNC_COMPRESS`），须影子验证后启用。

---

## 4. 文件与目录（新增 `phase8/`）

| 文件 | 职责 |
|---|---|
| `phase8/mutation_detector.py` | **N13** 突变检测器 |
| `phase8/sync_bus.py` | **N14** 广播发布/消费 + apply + heartbeat |
| `phase8/sync_strategy.py` | **D-20** 策略薄接口（4 钩子）+ 多样性硬门禁（D-23） |
| `phase8/mutation_thresholds.yaml` | 阈值配置（严格档默认值） |
| `phase8/tests/test_mutation_detector.py` | N13 测试 |
| `phase8/tests/test_sync_bus.py` | N14 测试（用 fakeredis/mock 免真连） |
| `phase8/10-deploy-sync-bus.sh` | 幂等部署脚本（云端 systemd + 本地 LaunchAgent） |
| `phase8/dreambuddy-sync-heartbeat.timer` / `.service` | 云端 6h 心跳 |
| `phase8/com.dreambuddy.sync-heartbeat.plist` | 本地 6h 心跳 |

---

## 5. TDD 任务分解（RED → GREEN → REFACTOR）

> 遵循 TDD：先写断言真实行为的 RED 测试（对未实现模块应报 `ModuleNotFoundError`），再实现到 GREEN。

| # | 阶段 | 任务 | 验证（可执行） |
|---|---|---|---|
| T1 | RED | `test_mutation_detector.py`：断言 `import phase8.mutation_detector` → `ModuleNotFoundError`；并写判据用例（z/冷却/二次确认/样本不足） | `pytest` 全红 |
| T2 | GREEN | 实现 `mutation_detector.py`（最小可过 T1） | 上述测试全绿 |
| T3 | RED | `test_sync_bus.py`：消息契约 round-trip（publish→consume→apply），幂等去重 | 全红 |
| T4 | GREEN | 实现 `sync_bus.py` 发布/消费 + `apply`（择优+部分迁移） | 全绿 |
| T5 | RED | 验证门禁：apply 后 val_loss 劣化 → 回滚 last-known-good | 全红 |
| T6 | GREEN | 接入 GeneVersionManager 快照 | 全绿 |
| T7 | RED/GREEN | 多样性预算：余弦>0.99 → 触发 `DiversityAlert` | 全绿 |
| T8 | 部署 | `10-deploy-sync-bus.sh` + 6h timer/plist（幂等） | 云端 `systemctl`/本地 `launchctl` 状态 active |
| T9 | 集成 | **影子模式 E2E**：注入合成"突变"事件 → 两端对齐演练（不写权威模型，仅 log） | 演练日志显示 择优+部分迁移 生效 |
| T10 | 收尾 | 认知 `record` + 文档索引同步 + commit/push | 索引/文档更新，零回归 |

**回归要求（HC-9）**：每步 REFACTOR 后跑既有全量测试，零回归；所有新开关默认 OFF。

---

## 6. 验收门（Gate）

1. **单元**：N13/N14 测试全绿；既有测试零回归。
2. **FAIL-OPEN**：检测器/Redis 不可用时，训练与广播不阻塞（返回 failopen）。
3. **影子模式**：E2E 演练中"突变→广播→择优+部分迁移→验证门禁"链路可视；**不改权威模型**。
4. **可观测**：日志显式输出 `delta_rel/z/dsr/t/decision/reason`，消除隐性静默。
5. **阈值可配**：`mutation_thresholds.yaml` 可调，无需改代码。

---

## 7. 风险与回滚

| 风险 | 缓解 / 回滚 |
|---|---|
| 阈值过严 → 长期静默 | **6h 心跳兜底**（已定，不可省） |
| 阈值过松 → 抖动/带宽 | 冷却窗 + 二次确认 |
| 部分迁移仍致趋同 | 多样性预算护栏 |
| Redis 不可用 | FAIL-OPEN，广播降级为"心跳同步" |
| 影子演练误写权威模型 | 开关默认 OFF + 只写 shadow 路径 + 演练前后快照 |

---

## 8. 与待实现清单的对应

- **N13 / N14 优先级：P1 → P0**（本轮提升；见 STATUS §3.2）
- 依赖：**N8（权重 delta）** / **N10（模型同步/热加载）** 为 N13/N14 的上下游；`O1`（Redis Streams）复用承载。
- 复用：`module_switches`（新开关）、`GeneVersionManager`（快照回滚）、`BradleyTerryLearner`（择优打分可选）。
