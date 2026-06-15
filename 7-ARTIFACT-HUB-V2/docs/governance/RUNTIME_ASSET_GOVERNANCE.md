# Runtime Asset Governance

本文件冻结 `7-ARTIFACT-HUB-V2` 相关运行态资产的治理规则，用于区分“运行态证据 / 状态 / 配置”和“普通功能代码”。

## 1. Runtime Categories

- `dreambuddy/artifacts`
- `dreambuddy/meta`
- `dreambuddy/config`
- local backup directories

## 2. Rules

- Runtime artifacts are evidence or state, not ordinary feature files.
- Local backup directories must not be swept into feature commits.
- Shared config changes require explicit review because they affect multiple systems.

## 3. Governance Notes

- `dreambuddy/artifacts` 应被视为 repo-local 运行证据根，而不是普通功能目录。
- `dreambuddy/meta` 承载运行态元数据与状态，处理时应避免与页面功能改动混提。
- `dreambuddy/config` 归共享底座，修改前应明确影响范围，修改后应走独立审查线。
- 本地 backup 目录仅用于安全回滚或人工比对，不应纳入正常功能提交。

## 4. Scope Boundary

- 本规则只定义运行态资产治理边界，不要求迁移现有代码或运行目录。
- 如需提交运行态相关变化，应先依据 `CHANGE_CLASSIFICATION_POLICY.md` 进行分类，再决定是否单独处理。
