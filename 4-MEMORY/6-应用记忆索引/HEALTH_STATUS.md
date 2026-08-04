# 应用记忆健康状态 — Health Status

> **更新日期**: 2026-07-27 19:15
> **更新频率**: 实时（每次查询前检查）

---

## 1. 实时状态

| 记忆ID | 状态 | 最后心跳 | 存储大小 | 索引同步 |
|--------|------|----------|----------|----------|
| AM-TRD-001 | 🟢 healthy | 2026-07-27 19:15 | - | ✅ 已同步 |
| AM-RSK-001 | 🟢 healthy | 2026-07-27 19:15 | 1 case | ✅ 已同步 |
| AM-OPS-001 | 🟢 healthy | 2026-07-27 19:15 | 1 incident, 1 playbook | ✅ 已同步 |
| AM-EXP-001 | 🟡 pending | - | - | ⏳ 待接入 |

---

## 2. 健康检查详情

### AM-TRD-001（交易应用记忆）
```json
{
  "status": "healthy",
  "memory_id": "AM-TRD-001",
  "cases_count": "N/A",
  "last_check": "2026-07-27T19:15:00"
}
```

### AM-RSK-001（风控应用记忆）
```json
{
  "status": "healthy",
  "memory_id": "AM-RSK-001",
  "cases_count": 1,
  "distills_count": 0,
  "last_check": "2026-07-27T19:15:00"
}
```

### AM-OPS-001（运维应用记忆）
```json
{
  "status": "healthy",
  "memory_id": "AM-OPS-001",
  "incidents_count": 1,
  "playbooks_count": 1,
  "last_check": "2026-07-27T19:15:00"
}
```

---

## 3. 离线处理策略

当应用记忆离线时：

1. **标记状态为 🔴 offline**
2. **告警通知**：发送飞书通知
3. **降级策略**：
   - 路由到总记忆中的历史索引
   - 或返回"服务暂时不可用"
4. **恢复流程**：
   - 检测到心跳恢复后，自动更新状态为 🟢 healthy
   - 触发索引同步

---

**文档版本**: v1.0
**最后更新**: 2026-07-27