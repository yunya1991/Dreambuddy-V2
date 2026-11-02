# REVIEW:Super-agent 融合三文档同行评审报告

> **版本**: v0.1 ｜ **日期**: 2026-11-02 ｜ **评审人**: AI 四角色(Journal-Fit/方法/统计/Devil's Advocate),人类最终决策
> **受审文档**:
> ① [SACG_A_SUPERAGENT_CONNECTION_SPEC v0.1](../../../../1-ARCHITECTURE/specs/SACG_A_SUPERAGENT_CONNECTION_SPEC.md)
> ② [SPEC-EVENT-DRIVEN-L1-GATEWAY v0.1](SPEC-EVENT-DRIVEN-L1-GATEWAY.md)
> ③ [DESIGN-SUPERAGENT-FUSION v0.1](DESIGN-SUPERAGENT-FUSION.md)
> **依据**: [ANALYSIS 双维梳理](ANALYSIS-SUPERAGENT-ARCH-DATAFLOW.md)、调研报告、v4.0 架构总览

---

## 评审摘要

- **整体决议**: 🟡 **修改后接受**(三份同判)
- **Major 意见**: 4 条(DA 评分 ≥4,按让步阈值协议**必须让步修改**)
- **Minor 意见**: 4 条

## 一、Journal-Fit Reviewer(方向契合度)

三份文档与项目方向高度契合:互补增强定位正确,"借壳灌芯"利用 DSH 同源事实是真正的巧妙点;45 入环补齐反馈流。方向无需调整。**通过**。

## 二、方法评审

- 映射有代码实证(okr_nodes/okr_builder 已读源码),非纸面类比 ✅
- 三份文档职责链清晰(调研→分析→设计→SPEC)✅
- **问题**:融合设计 F2「直通复用 route_confidence」是**类别错误**——route_confidence 语义是"L1/L2 分流置信度"(该不该 L1 处理),Thread 直通语义是"会话亲和性"(该送哪个已存在的会话),两者是不同函数,不能复用只能借鉴 → 见 DA-2(Major)
- **问题**:事件网关核心 `event_gateway.py`(Python)与现有 L1 意图注册表 `l1-intent-registry.ts`(TypeScript,3.1 前端侧)**跨语言归属未定义** → 见 Minor-2

## 三、统计评审

- SPEC#3 A5「有网关 vs 无网关成本对照」未定义回放集代表性与样本量 → Minor-3
- 45 shadow 转正判据(误拦率上限)未给数值 → Minor-4
- A→B 转正判据、F6 投机预取浪费上限为开放项(已在评审焦点,需评审会定值)

## 四、Devil's Advocate(主动反驳,评分制)

| # | 反驳 | 评分 | 让步判定 |
| --- | --- | --- | --- |
| DA-1 | **"灌芯"技术可行性未验证**:替换 Inline&Spill 为 fetchContext 假设 bundle 有上下文注入点,但 Inline&Spill 是 prototype 内部 store.py 实现,非 Harness 标准接口;未读 prototype 源码确认 hook 点,整个"借壳灌芯"可能无处可灌 | **4** | ⚠️ 必须让步:SPEC#2 P0 前置"hook 点验证"任务(读 store.py/session.py,确认或证伪) |
| DA-2 | **F2 复用 route_confidence 是类别错误**(见方法评审) | **4** | ⚠️ 必须让步:直通判据独立设计(thread_id 亲和表+TTL),route_confidence 仅作降级输入 |
| DA-3 | **事件网关无事件清单**:设计 Trigger 抽象与事件意图,但未盘点现有事件源(polling_trader 监控/13 timer/GitHub webhook/飞书),alert_confirm/event_triage 两意图是凭空命名,可能漏掉真实高频事件类型 | **4** | ⚠️ 必须让步:SPEC#3 P0 前置"事件源盘点"(源/速率/类型/现处理方),意图从盘点导出 |
| DA-4 | 2s 批合并窗口照搬 Super-agent passes 周期,无我们自身负载数据支撑 | 3 | 可坚持(已在评审焦点,初值后调) |
| DA-5 | SPEC#2 翻译器的 Mandate 目标格式**未对 prototype store.py 实证**,端到端验收 A4 依赖未验证契约 | **4** | ⚠️ 必须让步:与 DA-1 合并为"P0 前置任务:prototype 源码契约核实" |
| DA-6 | 模拟源验收说服力弱(真实事件分布未知) | 2 | 坚持原方案(P0 模拟源定位就是防真实渠道风险) |
| DA-7 | 未认真考虑替代方案"等待 DeepSeek 正式开源版" | 3 | 可坚持(原型 MIT 已在手,等待无收益;但应在 SPEC#2 补一句替代方案评估) |

## 五、7 模式阻断清单

| 模式 | 判定 | 说明 |
| --- | --- | --- |
| 1. 幻觉引用 | 🟡 通过带注 | 直通"+30%/+37%"等数据引自二手报道(IT之家/腾讯云),未核对原始实验数据;调研报告已标注"宣称值/待本地实测",可接受 |
| 2. 数据造假 | ✅ 通过 | 无实验数据宣称 |
| 3. 方法捏造 | ✅ 通过 | 映射基于源码实证 |
| 4. 框架锁定 | 🟡 通过带注 | 见 DA-7,替代方案评估偏薄 |
| 5. 结果幻觉 | ✅ 通过 | 设计文档无结果 |
| 6. 逻辑跳跃 | ❌ **不通过** | DA-2(route_confidence 复用) |
| 7. 边界忽略 | ✅ 通过 | 非目标/红线/评审焦点声明完整 |

## 六、Major/Minor 意见清单

### Major(必须修改)
- **M1**(DA-1+DA-5):SPEC#2 P0 增加前置任务「prototype 源码契约核实」——读 dsh-superagent-prototype 的 store.py/session.py,核实:① Mandate 字段 schema(翻译目标格式)② 上下文注入 hook 点是否存在(灌芯可行性)。**若 hook 点不存在,融合设计降级为"A 步仅借壳观察,灌芯改走 B 步自研"**
- **M2**(DA-2):融合设计 F2 修正——直通判据独立为「thread_id 亲和表 + TTL」,route_confidence 降为降级参考输入,删除"复用"表述
- **M3**(DA-3):SPEC#3 P0 增加前置任务「事件源盘点」——产出事件清单(源/速率/类型/现处理方),事件意图从清单导出而非预定义
- **M4**:三份文档互相引用处同步修订(SPEC#3 §六评审焦点、融合设计 §三 F2/F6)

### Minor(建议修改)
- m1: SPEC#2 补替代方案评估一句(等正式版 vs 试用原型)
- m2: SPEC#3 明确事件网关与 L1 意图注册表的跨语言归属(建议:网关在 34-core Python 侧,注册表经 IPC/文件契约对齐)
- m3: A5 成本对照补回放集定义与最小样本量
- m4: 45 shadow 转正判据给初始数值(建议误拦率 <5%、观察期 ≥2 周)

## 七、综合决议

**修改后接受**。方向、总纲、红线不动;4 条 Major 集中在**未实证的外部契约**(prototype 源码)与**一处类别错误**(F2),均为可局部修订项,不构成重新设计。修订后无需全量复审,仅复核 M1–M4 落点即可。

---
> 按让步阈值协议:DA-1/2/3/5 评分 4,作者必须让步;DA-4/6/7 评分 ≤3,维持原方案并记录论据。
