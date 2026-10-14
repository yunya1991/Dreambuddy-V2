# REVIEW — 大模型+分布式计算成熟框架评估 与 评审定稿

- **状态**：**已定稿**（评审通过，裁决生效）
- **日期**：2026-10-14
- **关联**：
  - [RESEARCH-训练协同-隔离单训与突变广播同步.md](./RESEARCH-训练协同-隔离单训与突变广播同步.md)
  - [SPEC-分布式计算协同部署方案.md](./SPEC-分布式计算协同部署方案.md) §7.1 / §12.5（D-14~D-19）
  - [PLAN-训练协同-N13突变检测与N14广播总线.md](./PLAN-训练协同-N13突变检测与N14广播总线.md)
- **方法**：三域框架调研 + 架构差距映射 → 独立评审（6 角色 + Devil's Advocate + 让步阈值协议）→ 定稿

---

## 一、架构评估：与成熟框架逐条对照

| # | 机制 | 成熟实现 | 我们对应件 | 差距 | 结论 |
|---|---|---|---|---|---|
| 1 | 分片与重载 | FSDP2/DTensor、DeepSpeed ZeRO、Megatron | 无分片需求；N10 热加载 | 无统一 state_dict 抽象、delta 无寻址 | **不引入分片本体**；只借"分片 checkpoint 命名/重载约定" |
| 2 | 通信优化 | 1-bit Adam、PowerSGD、ZeRO++ | 仅传权重 delta | delta 未量化/稀疏化 | **适配**：大 payload 压缩默认 OFF；心跳只传元数据 |
| 3 | 低通信隔离训练 | DiLoCo / OpenDiLoCo、Hivemind、Petals | 6h 兜底 + 突变即时广播 | 未形式化 inner/outer；无异步伪梯度 | **直接借鉴**：OpenDiLoCo inner/outer 语义（Hivemind/Petals 不适用） |
| 4 | 联邦策略 | Flower Strategy、NVFlare | 择优+部分迁移→合并→warm-start | 无策略抽象/生命周期 | **适配**：自写≤1 文件薄接口（4 钩子）；**否决 Flower 本体** |
| 5 | 编排 | Ray、Prefect/Flyte/Argo | Redis Streams（消费者组） | 缺 DAG/重试/可观测 | **适配**：Streams 足够（借 Prefect 的 retry/幂等语义） |
| 6 | 模型仓库/热加载/灰度 | MLflow Registry、KServe/BentoML/Ray Serve | N10 热加载 | 无版本/alias/灰度/回滚 | **适配最小集**：内容寻址+atomic swap+LKG；**否决 Registry 服务端** |
| 7 | 弹性/容错 | TorchElastic、checkpoint/restart、Hivemind | 节点掉线 + SSH 超时 | 无 rendezvous/断点续传 | **否决 TorchElastic**；用 rsync 增量重试 + checkpoint/restart |
| 8 | 激励/反搭便车 | Bittensor、Gensyn、Prime Intellect | 算力悬殊（4C8G vs M3） | 无贡献计量/信誉 | **适配**：贡献度加权迁移 + 多样性预算（反同质化） |
| 9 | 版本/血缘/幂等 | OCI/DVC hash、OpenLineage | 广播幂等 + last-known-good | 无内容寻址 digest / 血缘 | **直接借鉴**：SHA256 内容寻址 + 广播幂等键 |

### 1.1 相对成熟框架的 3 个最大差距

1. **缺内容寻址 + 版本注册 + 血缘**：广播幂等与回滚全靠约定，无 digest/registry/lineage 兜底。
2. **缺策略抽象层**：择优/部分迁移/合并/warm-start 散为逻辑，无可插拔抽象与生命周期，难扩展与复盘。
3. **缺容错与断点续传**：SSH 超时/节点掉线无重试语义，同步可能**静默失败**。

### 1.2 最值得借鉴的 3 个成熟成果

1. **OpenDiLoCo** inner/outer 双优化器 + 异步伪梯度语义（轻量、CPU 可跑、~180 行参考实现）。
2. **内容寻址(SHA256 digest) + atomic swap + last-known-good** 最小版本/热加载集。
3. **策略薄接口（4 钩子）**：select / partial_migrate / merge / warm_start。

---

## 二、评审记录（6 角色 + Devil's Advocate + 让步阈值协议）

> 协议：每条建议评分 1–5，**≥4 才让步/采纳**；<4 坚持原立场并给更强论据。

### 2.1 逐条评分

| # | 建议 | 立场 | 分 | RFD 理由 |
|---|---|---|---|---|
| 1 | OpenDiLoCo inner/outer | **采纳** | **5** | ~180 行、零重依赖，把"突变广播"形式化为事件化 outer step，与现有混合同步同构 |
| 2 | SHA256 + MLflow Registry + LKG + TorchElastic | **拆分·部分让步** | **3** | 仅 digest + LKG 指针 + 幂等键采纳；**Registry 服务端 / TorchElastic 否决**（两节点无弹性需求，成本>收益） |
| 3 | Flower Strategy + 多样性门禁 | **拆分·部分让步** | **3** | **Flower 本体否决**（FL 服务端过重）；"策略可插拔"降为 **≤1 文件薄接口**；多样性硬门禁**采纳** |
| 4 | 通信压缩 + 6h 心跳 | **采纳** | **4** | 心跳只传元数据/哈希=必采纳；突变 payload 量化**默认 OFF**（量化即注噪） |
| 5 | DCP 统一 state_dict + atomic swap | **让步** | **4** | atomic swap + 内容寻址采纳；**DCP 分片本体不引入**（无分片需求），只借命名约定 |

### 2.2 六角色质询要点

- **极简**：FL 抽象/注册表/DCP 分片 = 过度设计（YAGNI）。
- **风控**：任何自动替换须 **人工确认 + 影子期 + LKG 回滚**；量化 = 注噪，须影子验证。
- **性能**：纯 CPU 离线开销可接受；量化收益边际；6h 偏慢由突变即时广播补偿。
- **维护**：Flower/Celery 级依赖 = 长期债；自写薄接口可测。
- **跨学科**：择优 + 部分迁移 + 多样性预算 = 岛屿 GA 防同步化死亡（良性）；**全量覆盖 = 搭便车，须禁**。
- **复杂性**：2 节点下机制量 > 收益者为 MLflow 服务器 / TorchElastic / Flower；内容寻址 + atomic swap 收益 > 成本。

### 2.3 评审红线（不可绕过）

1. **禁止全量覆盖**；2. 合并**仅同初始化**；3. 部分迁移上限 **≤5%**（默认下限保多样性）；4. **多样性预算 + 贡献加权 = 硬门禁**，未达标禁 promote；5. 自动替换须**人工确认 + 影子期 + LKG 回滚**；6. 广播**强制 digest + base_version + 幂等键**；7. **不引入 NCCL / FSDP / K8s / FL 服务端本体**。

### 2.4 否决 / 降级项

- **否决**：MLflow Registry 服务端、TorchElastic rendezvous、Flower 框架、DCP 分片机制。
- **降级默认 OFF**：突变 payload 量化压缩。

---

## 三、评审定稿（裁决生效）

### 3.1 最终裁决

| 分类 | 项 |
|---|---|
| **可直接借鉴** | ① OpenDiLoCo inner/outer；② SHA256 内容寻址 + LKG 指针 + 幂等键；④ 6h 心跳元数据化 |
| **适配后借鉴（薄实现）** | ③ 策略薄接口（4 钩子）+ 多样性硬门禁；⑤ atomic swap / 命名 checkpoint 热加载；④ 突变压缩条件启用 |
| **不适用** | MLflow 注册表服务器、TorchElastic、Flower 本体、DCP 分片 |

### 3.2 定稿决策（追加至 SPEC §12.5）

| 编号 | 决策项 | 定稿值 | 依据 |
|---|---|---|---|
| **D-20** | 同步策略抽象 | **自写薄接口**（4 钩子：select / partial_migrate / merge / warm_start），**不引入 Flower 本体** | 评审评分 3，部分让步 |
| **D-21** | 版本/热加载 | **内容寻址(SHA256) + atomic swap + last-known-good 最小集**；**不上 Registry 服务端**；`digest` + `base_version` 升为**广播强制字段** | 评审评分 3/4 |
| **D-22** | 压缩策略 | **6h 心跳只传元数据/哈希（必开）**；突变大 payload 的 top-k/1-bit 压缩**默认 OFF**（超阈值 + 影子验证后启用） | 评审评分 4 |
| **D-23** | 硬门禁升格 | **多样性预算 + 贡献加权 + 禁止全量覆盖** = 不可绕过硬门禁（未达标禁 promote） | 评审红线 |
| **D-24** | 借鉴 OpenDiLoCo 语义 | "突变广播"形式化为**事件化 outer step**（inner 本地多步 / outer 周期或事件同步伪梯度） | 评审评分 5 |
| **否决** | — | MLflow Registry 服务端 / TorchElastic / Flower 本体 / DCP 分片 | 评审 §2.4 |

### 3.3 落地映射（对 PLAN 的修订）

| PLAN 项 | 定稿修订 |
|---|---|
| N14 §3.1 消息契约 | **新增强制字段** `digest`(SHA256) + `base_version` + `idempotency_key` |
| N14 §3.2 apply | 钩子化：`select → partial_migrate → merge → warm_start`（D-20 薄接口） |
| N14 §3.4 多样性预算 | 升为**硬门禁**（D-23），未达标禁 promote + 人工确认 |
| N14 §3.5 持久化 | digest 内容寻址 + atomic swap + LKG（D-21） |
| N13/N14 新增 | `策略薄接口` 单文件（可选 `sync_strategy.py`）；压缩模块默认 OFF（D-22） |
| 服务引入 | **不新增** Registry/TorchElastic/Flower 服务；复用 Redis + MinIO |

---

## 四、认知闭环

- 前置 `recall`：命中 VM-1791965563613（两节点开源选型，B 级），结论自洽。
- 后置 `record`：评审定稿（D-20~D-24 + 否决项）已写入认知库（硬约束级）。
