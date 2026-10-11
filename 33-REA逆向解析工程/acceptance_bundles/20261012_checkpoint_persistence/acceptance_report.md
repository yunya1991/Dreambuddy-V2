# 验收报告 — ModelCheckpoint 文件持久化（热重载状态丢失修复）

- 日期: 2026-10-12
- 范围: 3.1-FRONTEND/src/lib/{model-checkpoint.ts, 5×training-loop, replay-buffer, drift-detector-adapter, training-loop-registry} + src/app/api/training/ + .gitignore
- 任务: ModelCheckpoint 增加 JSON 文件持久化，解决 Next.js dev 热重载/重启导致内存训练状态归零

## 五维验收

| 维度 | 结果 | 证据 |
|------|------|------|
| 1. 症状复测 | ✅ PASS | repro_after.log：重启后 C step=88 / S step=77 从磁盘恢复（修复前归零） |
| 2. 日志证据 | ✅ PASS | dev log 含 2 条 `checkpoint restore failed` 降级告警（边界轮触发 FAIL-OPEN 路径证明已执行） |
| 3. 回归证据 | ✅ PASS | test.log: 549/549 全绿 (37 suites)；tsc 范围内错误=0 (tsc_scope_errors.txt) |
| 4. 影响面核查 | ✅ PASS | fix.diff 3363 行，全部位于声明范围（src/lib 训练系统 + .gitignore），无越界文件 |
| 5. 边界验证 | ✅ PASS | ①损坏 checkpoint（缺 ruleArchive）→ 服务不瘫痪、降级全新状态 ②NODE_ENV=test 跳过恢复（测试隔离） ③.persistDir 不放 .next/（next dev 清理） |

## 关键设计决策

1. **持久化目录**: `.training-checkpoints/`（项目根）而非 `.next/` — next dev 重编译会清空 .next 导致状态丢失
2. **原子写入**: tmp 文件 + rename，防止写一半崩溃损坏 JSON
3. **跨实例共享**: static `sharedStores` 以 persistDir 为 key，5 层循环共用同一 store 不互相覆盖
4. **测试隔离**: `NODE_ENV=test` 跳过磁盘恢复，避免测试间状态污染
5. **FAIL-OPEN 增强（本轮收尾发现并修复）**: restore 包 try/catch — 损坏/缺字段 checkpoint 只降级为全新状态并 console.error，不击穿 registry（否则训练系统永久瘫痪）

## 验收过程中发现并修复的缺陷

- **缺陷**: 边界轮复测发现手工种子缺 `ruleArchive` 字段 → C 层 restoreModel 抛 TypeError → 整个 registry 永久降级（每次请求都失败）
- **修复**: 5 个循环构造函数 restore 均包 try/catch，降级为全新状态
- **验证**: 边界轮 C step=0 服务正常 + 正常轮 C step=88/S step=77 完整恢复

## 预存问题登记（不在本任务范围）

- tsc 全仓仍有 29 个预存错误（cognitive-context-builder.test.ts×7、dsh-execution-engine.test×9 等），均为历史会话遗留，未由本任务引入

## 结论

✅ 验收通过（full），进入代码提交
