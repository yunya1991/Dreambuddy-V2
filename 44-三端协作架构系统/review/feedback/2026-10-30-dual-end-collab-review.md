# 双端协作治理 SPEC — 独立评审报告

- 评审日期：2026-10-30
- 评审对象：`docs/tech/SPEC-dual-end-collab-governance.md`
- 评审方式：**独立评审会话**（非起草方，只读，不改动原文），对应 G3.5 角色分离要求

## 一、结论

**有条件通过**：方向正确（GitHub 单锁 + 单源），但方案对"端"的判定全部依赖自述文本，若不修 M1/M2/M3，租约与 G3.5 会形同虚设。

## 二、必改项

| 编号 | 意见 | 处置（v2） |
|---|---|---|
| M1 | 端身份不可验证：CI 只能读 PR 正文/分支名，两端共用同一账号，G3.5 仍可自证 | 承认残余风险；分层 L1 声明审计 / L2 邮箱白名单 / L3 签名身份（§3.6） |
| M2 | 租约路径未映射，申请租约的 PR 自身需先持租约（死锁） | 新增 `lease` 特例并豁免（§3.1） |
| M3 | 未接入分支保护；已有 bot 直推 main | 分支保护列为 P0 前置；明确直推白名单（§6.2/§6.3） |
| M4 | 云端全仓 pull 绕过 G4，且只校验 44 目录干净 | 改为 fetch + 44 路径 checkout（独立 worktree 语义）（§5.2） |
| M5 | ACK 文件不入库，另一端与 CI 不可见，构成第二真源 | 删除 ACK 文件，同步判定 = HEAD vs origin/main（§5.2） |
| M6 | test/review 强制 dev 前置，文档评审无法取租约 | test 可继承已释放 dev；review 不要求 dev（§3.3） |

## 三、建议项

| 编号 | 意见 | 处置 |
|---|---|---|
| S1 | `root` 过粗，改一次 `.github` 会锁全仓 | 拆 `root:ci` / `root:repo` |
| S2 | 不新建 SKILL，避免同 category+role 漂移 | 扩展 `dream-three-tier-collab` v1.2 |
| S3 | 状态载体过多 | 单一载体原则（§6.1） |
| S4 | hotfix 缺租约豁免 | `hotfix:<id>` 免租约 + 24h 补审 |

## 四、落地判断

可落地；先做最小版（`lease.py` + `lease-guard` + 分支保护），`docs_sync` 为第二优先。证据：
`shared/tools/test_lease.py` 14 项单测通过；`validate_registry.py` 通过。
