# CHANGELOG — 47-MCP管理系统

## 2026-11-02 PLAN v0.2 修正（本地审查云端产出）

### 背景

云端产出 `PLAN-L0-MCP-P0-P3 v0.1` 后，本地与 SPEC v0.3 / ALIGNMENT v1.0 交叉比对发现 1 处冲突，修正为 v0.2。

### 修正

- **任务载体冲突（P1）**：v0.1 任务②新建 `0-系统文档管理/l0_capability_set.v1.yaml` 作为"DSH 能力集单一载体"，与 ALIGNMENT B4「单一载体 = `47/registry/mcp_capabilities.yaml`」冲突。修正为：任务①合并原任务②，mcp_capabilities.yaml 包含完整的**角色→能力标签→工具**三层映射；删除多余的 l0_capability_set.v1.yaml
- **任务编号重排**：因删除 1 个任务，M1 ①②③、M2 ④⑤⑥、M3 ⑦⑧⑨、M4 ⑩⑪（原 M4⑫→⑪）；K1 引用 M1③→M1②，K3 引用 M4⑫→M4⑪，§一 P3 引用同步
- **范围说明补充**：头部新增「本计划仅覆盖 47-MCP 侧」说明，46-DSH 侧见 DESIGN-DSH-ARCH-UPGRADE §五

### 评审判定

云端产出的其余部分（里程碑依赖、K1-K5 对策、出口判据、envelope 字段列表）均与 SPEC/ALIGNMENT 一致，无需修正。

## 2026-11-02 两端改动集成（本地 v0.3 + 云端修正）

### 集成说明

- 本地 46-DSH 会话产出 **SPEC v0.3**（B1-B6 / G1-G3 决议落定，见 §8）+ 新增 `docs/tech/ALIGNMENT-46-47-v1.0.md`
- 云端评审会话产出 README 断链修正 + SPEC §3.1/§3.5/§3.8 三处补充 + 本 CHANGELOG
- 两端改动经交叉核对**零语义冲突**，已合并为单一版本统一上传

### 本地修正（集成时并入）

- SPEC 状态措辞修正：「终审通过」→「决议落定，可开工；R8 终审待云端签发」（终审权归云端 R8）
- SPEC §3.2 勘误：45 PG「七表」→「八表」（`001_init.sql` 实测 8 个 CREATE TABLE，ALIGNMENT §八 指出但未回改）

## 2026-11-02 文档修正（评审后修订）

### 修正

- **断链引用修正（README）**: 外部关联文档表中 `ANALYSIS-L0-MCP-ENCAPSULATION v0.2` 与 `SPEC-L0-three-layer-architecture v0.5` 的版本号后缀与实际文件名不符，已去除版本后缀，与实际文件对齐
- **状态标注补充（README）**: 存量 MCP 面登记表前增加状态说明，明确契约注册表 `registry/mcp_capabilities.yaml` 与顶层 `mcp_shells/` 目录为 P0 交付物、当前尚未创建
- **时序矛盾消除（SPEC §3.8）**: 明确 D4 延迟数值为目标值，须在基线测量完成并产出基线报告后方可作为验收生效标准（先基线，后生效）
- **运维细节补充（SPEC §3.1/§3.5）**: 连接上限数值归属 19-DAL 治理方案定义；补充 ssh 云端拉起模式认证沿用宿主 ssh 密钥机制、壳进程异常退出由宿主负责重启的说明

### 新增

- 本 CHANGELOG 文件，对齐项目内其他模块（16/21 等）的文档规范
