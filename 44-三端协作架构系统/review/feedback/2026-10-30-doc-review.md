# 44 三端协作架构系统 - 技术文档评审报告

- 评审日期：2026-10-30
- 评审对象：docs/tech/ 下三份技术文档
- 评审方式：本地云端评审（只读评审，未改动任何文档原文）

## 一、评审对象

1. SPEC-three-tier-collab-management.md（三端协同管理体系规格）
2. dream-three-tier-collab-SKILL.md（编排型 SKILL 交付物）
3. three-tier-collab-qwen-research.md（千问调研报告，上游输入）

## 二、总体结论

**评审通过（有条件）**：三份文档构成完整的『调研 → 规格 → 交付物』证据链，SPEC 对千问报告 7 项 gap 的修正均有明确理由且与现有资产对齐，建议进入 P0 落地阶段，但需先处理下述必改项。

## 三、分文档评审意见

### 1. SPEC-three-tier-collab-management.md

**优点：**
- 立场正确：以『演进现有资产』为主，新建仅 2 项，避免了单人 4C8G 环境下的过度工程化；
- 对千问报告的修正合理：拒绝 MLflow（资源不允许）、拒绝第二套 SKILL 注册表（避免双注册表漂移）、G4 改用波动率分位门禁（适配加密货币 7×24 特性）均有据可依；
- 双轨模型生命周期（V15 实盘线 / 12-ML 研究线）边界清晰，禁止跨轨写入是关键硬约束；
- 门禁链 G1-G7、排查 SLA、红线清单完整可执行。

**必改项（P0 落地前）：**
- [ ] M1：D5 评审报告作为 12-ML promote 前置条件，需明确报告的时效定义（如『当次训练后、promote 前生成』的具体时间窗），否则『无报告不 promote』在实操中可能被过期报告绕过；
- [ ] M2：G4 门禁参数（ATR20 分位 >90%、资金费率阈值 0.001）需注明数据来源与计算周期，并说明参数本身的评审归属（建议纳入 D6 风控行为评审范围）；
- [ ] M3：预算基线 budget-baseline.md 尚未落盘，D8 月报首次执行前必须完成，建议列入 P0-0。

**建议项：**
- [ ] S1：yijing-polling-trader 日志停留 2026-10-17 的悬案应在 P0 阶段优先排查（静默服务按 D3 标准已属异常）；
- [ ] S2：P0 hotfix 豁免的『本人显式确认』建议补充确认渠道定义（如指定文件签名或命令行参数），避免口头确认无留痕。

### 2. dream-three-tier-collab-SKILL.md

**优点：**
- 与 SPEC 完全一致，无矛盾；RACI 表、门禁链实现细节（含具体脚本路径）、意图路由表可直接落地执行；
- 『只做路由，不重复实现』的编排型定位正确，depends_on/provides 元数据完整；
- 双位置存储设计（.trae/skills 与 1-ARCHITECTURE/skills）符合现有项目结构。

**必改项：**
- [ ] M4：SKILL 引用的依赖脚本（cloud-review.sh、g4-volatility-gate.py、precommit_secret_scan.py）目前尚不存在，属于 P0-0/P0-4 待交付项，SKILL status 建议在脚本就绪前标注为 draft 或在 depends_on 中注明交付状态，避免路由到不存在的入口。

**建议项：**
- [ ] S3：D1 评审命令使用 ssh dreambuddy-remote，需确认该 SSH 别名已在本地配置，建议在 SKILL 中补充前置检查说明。

### 3. three-tier-collab-qwen-research.md

**优点：**
- 四维度业界模式（传统金融/GitOps+SRE/MLflow/RACI）梳理完整，单人裁剪建议务实；
- 反模式识别（云端单点、SKILL 膨胀、无灾备演练）有价值，已被 SPEC 部分吸收。

**说明：**
- 该文档为上游输入，其中 MLflow、registry.yaml、金丝雀发布等建议已被 SPEC 明确否决并给出替代方案，此文档应保留作为决策依据存档，不作为执行依据；
- 文档末尾含对话残留内容（『需要我为你生成这份方案的初始代码框架吗？好的，帮我生成』），建议清理以保持文档纯净（非阻塞项）。

## 四、评审结论汇总

| 文档 | 结论 | 必改项 | 建议项 |
|---|---|---|---|
| SPEC | 通过（有条件） | M1/M2/M3 | S1/S2 |
| SKILL | 通过（有条件） | M4 | S3 |
| 千问调研报告 | 存档通过 | 无 | 清理对话残留 |

**后续动作建议：**
1. 处理 M1-M4 必改项后，SPEC 可从 review/pending 移入 review/approved；
2. 必改项处理完成后启动 P0 落地计划（P0-0 至 P0-4）；
3. S1 悬案（yijing-polling-trader 日志停滞）建议独立登记排查。

---

## 五、复核结论（2026-10-30，本地复核）

| 项 | 处置结果 | 落点 |
|---|---|---|
| M1 D5 报告时效 | 已定 24h 有效期 + 须晚于 `eval_gate.evaluated_at` | SPEC §一之五 |
| M2 G4 参数来源/周期 | 已注明 ATR20 日线 21 根 / 90 日分位 / funding 8h，变更归 D6 | SPEC §二 |
| M3 budget-baseline | 已纳入 P0-0 验收标准 | SPEC §六 |
| M4 脚本缺失 | `cloud-review.sh`/`g4-volatility-gate.py`/`precommit_secret_scan.py` 已入库 | 提交 `568c01582c`/`db3cbcf1d2`，关闭 |
| S2 hotfix 留痕 | 固定 `update.sh --g4-hotfix "原因"` + `hotfix-log.jsonl` | SPEC §二 |
| S3 SSH 前置检查 | 已补 `ssh dreambuddy-remote true` 前置门 | SKILL §零 |
| S1 静默服务悬案 | 转 D3 待办，不阻塞 | SPEC §一之六 |

**复核结论：条件已满足 → SPEC 由 `review/pending` 流转至 `review/approved`。**
