# 应用记忆注册表 — App Memory Registry

> **版本**: v1.0
> **更新日期**: 2026-07-27
> **定位**: L1 总记忆系统的应用记忆索引，记录所有已注册的应用记忆系统

---

## 1. 已注册应用记忆

| 记忆ID | 名称 | 子系统 | 存储位置 | 状态 | 最后心跳 |
|--------|------|--------|----------|------|----------|
| AM-TRD-001 | 交易应用记忆 | 11-易经推理系统 | 11-易经推理系统/scripts/memory_l4/ | 🟢 在线 | 2026-07-27 |
| AM-RSK-001 | 风控应用记忆 | 13-通用风控模块 | 13-通用风控模块/memory/ | 🟢 在线 | 2026-07-27 |
| AM-OPS-001 | 运维应用记忆 | 15-监控告警系统 | 15-监控告警系统/memory/ | 🟢 在线 | 2026-07-27 |
| AM-EXP-001 | 实验应用记忆 | experiments/ab-trading | experiments/ab-trading/memory/ | 🟡 待接入 | - |

---

## 2. 接口规范

所有应用记忆系统必须实现统一接口规范（7个标准接口 + 2个便捷方法）：

```python
class AppMemoryInterface:
    # 标准接口
    def search(query, filters, memory_type, top_k) -> List[dict]
    def add(memory_entry) -> str
    def update(memory_id, updates) -> bool
    def get(memory_id) -> dict
    def stats() -> dict
    def distill_candidates(min_quality, limit) -> List[dict]
    def healthcheck() -> dict
    
    # 便捷方法
    def search_similar_cases(...) -> List[dict]
    def run_distill_from_review(...) -> str
```

**filters 语义隔离**：各应用记忆系统自行定义 filters 字段，总记忆系统不规定具体字段名。

---

## 3. 路由规则

总记忆系统根据查询类型路由到对应应用记忆：

| 查询类型 | 路由目标 | 典型查询 |
|---------|---------|---------|
| 交易相关 | AM-TRD-001 | "趋势向上时怎么做？" |
| 风控相关 | AM-RSK-001 | "爆仓预警案例" |
| 运维相关 | AM-OPS-001 | "CPU告警处理" |
| 实验相关 | AM-EXP-001 | "AB测试结果" |

---

## 4. 蒸馏上升规则

应用记忆 → 总记忆（MU-xxx）的上升路径：

```
AM-TRD-001 → MU-TRD（交易记忆单元）
AM-RSK-001 → MU-TRD（风控经验可成为交易原则）
AM-OPS-001 → MU-DEV（运维经验可成为开发原则）
AM-EXP-001 → MU-TRD 或 MU-DEV（视实验内容而定）
```

**上升阈值**：
- B级（待验证）：需1次验证
- A级（可信）：需3次独立验证
- S级（公理）：需10次独立验证

---

## 5. 健康状态

| 状态 | 含义 | 处理 |
|------|------|------|
| 🟢 在线 | 正常运行，可查询 | 正常路由 |
| 🟡 待接入 | 接口未实现或未测试 | 仅索引，不路由 |
| 🔴 离线 | 心跳超时或健康检查失败 | 告警，尝试恢复 |
| ⚫ 已废弃 | 不再使用 | 从索引移除 |

---

**文档版本**: v1.0
**最后更新**: 2026-07-27