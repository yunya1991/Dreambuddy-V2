# Execution Order

本文件冻结完整架构归档梳理的执行顺序与停止条件，确保恢复与治理工作先统一认知，再恢复实现。

## Phase 1

- 冻结边界文档：[SYSTEM_BOUNDARIES.md](../architecture/SYSTEM_BOUNDARIES.md)
- 冻结单一真相源：[SOURCE_OF_TRUTH.md](../architecture/SOURCE_OF_TRUTH.md)
- 冻结归档信息模型：[ARCHIVE_INFORMATION_MODEL.md](../architecture/ARCHIVE_INFORMATION_MODEL.md)

## Phase 2

- 冻结上下游承接关系：[UPSTREAM_DOWNSTREAM_MATRIX.md](../integration/UPSTREAM_DOWNSTREAM_MATRIX.md)
- 冻结运行态治理口径：[CHANGE_CLASSIFICATION_POLICY.md](../governance/CHANGE_CLASSIFICATION_POLICY.md)
- 冻结归档账本：[ARCHIVE_LEDGER.md](./ARCHIVE_LEDGER.md)

## Phase 3

- 仅在上述治理骨架可读、可链接、可导航后，恢复 `/feed` 或其他实现主线
- 若新增文档尚未完成归类或入口链接缺失，停止物理迁移与实现扩展

## Stop Conditions

- 任一冻结文档不存在或入口链接断裂时，停止后续实现工作
- `docs/recovery/README.md` 未收口治理入口时，不继续推进恢复类执行动作
- 当前阶段只允许补全文档骨架与链接，不允许借本顺序文档触发代码迁移
