# 提案 PROP-20260809-BATCH1：架构系统治理 Cron 改造（批1）

**批次**: 批1（Cron架构适配改造三批之一）
**类别**: governance
**提交时间**: 2026-08-09
**批准方式**: 用户在飞书会话中明确确认（"先处理批次1，然后批次2"）
**状态**: ✅ 已实施（2026-08-09 13:0x）

---

## 一、提案内容（用户确认版）

**批1：架构系统治理（替换元链治理，周日22:00）**
- 删除：元链治理(ab18d891)、思维链门禁审计(0ee1dd42)
- 新建：五层链路完整性巡检——INDEX索引有效性→认知daemon健康→易经三引擎状态→DreamOS SACG编排→子系统运行，输出治理周报
- 健康仪表盘扩展：write_health_status.py 的 meta-governance→architecture-governance，删 gate-audit，加3个监控系统

## 二、实施记录

| 动作 | 对象 | 结果 |
|------|------|------|
| 删除 cron | Meta-Governance-Weekly (ab18d891e0e2) | ✅ removed |
| 删除 cron | Gate-Audit-Weekly (0ee1dd42a733) | ✅ removed |
| 新建 cron | Architecture-Governance-Weekly (**1863584b3833**)，周日22:00，skills=[dreambuddy-system-navigation, system-audit-workflow]，deliver=feishu | ✅ 今晚22:00首跑 |
| 修改脚本 | 16-调控系统/scripts/write_health_status.py | ✅ 系统列表更新 |

**write_health_status.py 系统列表（9个）**：
trading-evolution / memory-evolution / token-optimization / index-audit / knowledge-sync / **architecture-governance**(五层架构治理,替代meta-governance) / **yijing-engine**(新增) / **dreamos**(新增) / **v15-trading**(新增)
（gate-audit 已删除）

## 三、遗留发现

- ⚠️ **trading-evolution cron (67772b7c) 在 jobs.json 中缺失**（8/9 重建清单中有记录，当前不存在）→ 待用户决策是否重建
- 仪表盘系统数=9，与提案中"10系统"差1——若需第10个可补 approval-system（审批链路监控）

## 四、批2实施记录（✅ 已完成 2026-08-09）

**三个每日监控任务**（七步闭环：运转检查→Bug修复→交易评估→反思自进化→联网拓展→代码开发→回测上线）：

| cron | job_id | 时间 | skill | 健康上报系统 |
|------|--------|------|-------|------------|
| Yijing-Daily-Monitor | f780fa1217f4 | 每日08:30 | yijing-daily-monitor | yijing-engine |
| DreamOS-Daily-Monitor | 614eba831b7a | 每日09:00 | dreamos-daily-monitor | dreamos |
| V15-Martingale-Daily-Monitor | e38bb15763a7 | 每日09:30 | v15-daily-monitor | v15-trading |

硬门禁（写死在skill+prompt）：
- 回测不优于基线 → 回退+反思+调参；连续两次不过 → 放弃（ABANDONED）
- 代码改动/上线 → trading 审批（等人，永不自动）
- V9规则不可修改（V15专属红线，只能叠加）
- 基线锚点：6-TRADING/baselines/v15-six-trading-20260601

首跑：2026-08-10（明早）08:30/09:00/09:30

## 五、后续批次

- 批3：（待展开）


---

## 批3实施记录（2026-08-09，用户指令直接执行）

### 变更内容
1. **trading-evolution 删除**（不再重建）：remove Trading-Evolution-Weekly `1fb4e437d6ea`（周一10:00）
2. **认知系统每日监控新增**：Cognitive-Daily-Monitor `62412b13de1e`，每日10:00，skill=cognitive-daily-monitor
   - 七步：完整链路检查→认知更新→认知系统引用→bug修复→联网探索→评估验证→回测上线
3. **知识库更新任务改造**：Knowledge-Sync-Weekly `dcd28b0de994` → Knowledge-Update-Weekly（周四22:00不变），skill=knowledge-base-update
   - 用户定调：以现有系统为原点扩展搜索；蒸馏交易大师方法+交易经典理论；能落地+回测能提升系统能力；**每次≤3条**
4. **0-系统文档管理维护周报新增**：Doc-Maintenance-Weekly `13f50e09e473`，周五10:00，skill=doc-system-maintenance
   - 代码↔技术文档对齐审计（类似索引系统）+ 记忆同步规则审计（用户强调：每次任务完成后记忆系统必须同步更新，同步率<80%🟡/<50%🔴）

### 健康仪表盘同步更新
`16-调控系统/scripts/write_health_status.py` VALID_SYSTEMS 调整为10系统：
删除 trading-evolution；新增 cognitive-system(认知系统)、doc-maintenance(文档系统维护)；knowledge-sync 中文名改为"知识库更新"

### 记忆固化
- Hermes memory：Cron体系条目已更新
- 认知系统双写：VM-1786252954585-8959511f（tag=user-correction）


### 批3修订（2026-08-09 当日，用户选A）
认知每日监控从七步改为**六步稳定优先模式**：移除联网探索步骤。
决策依据：认知系统无客观裁决函数（A/B会话重放是自评估），冷启动期（17条记忆）瓶颈是实践引用不足；
进化只靠 bug修复/用户纠正双写/实践引用贝叶斯验证 三种被动触发；联网探索唯一通道=Knowledge-Update-Weekly。
