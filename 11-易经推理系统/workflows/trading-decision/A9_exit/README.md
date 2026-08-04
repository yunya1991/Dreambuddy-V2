# A9 入口映射

- 职责：根据收益与风险输出离场动作建议。
- 入口：`run_a9_exit(payload, output_dir=None)`
- 输出：`stage_id="A9"` + `exit_action` + `artifact_path`。

## 离场模块架构

### 独立链路（polling_trader）

`YijingExitSystem`（主离场） → `ClassicExitSystem`（降级备用）

### DreamOS 链路（auto_trader）

`ExitModuleSelector` 按场景回测表现择优调用：
- `YijingExitAdapter` → 封装 YijingExitSystem（9→4 决策映射 + 三级卦象降级）
- `ClassicExitAdapter` → 封装 ClassicExitSystem（四优先级 CLOSE/REDUCE/RAISE_TP/HOLD）
- `SimpleExitAdapter` → 内置 ATR 逻辑镜像

详见技术设计文档 [TECHNICAL_DESIGN.md §9.8](../../docs/TECHNICAL_DESIGN.md#98-dreamos-离场模块集成yijingexitadapter--exitmoduleselector)。
