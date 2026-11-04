# G0:dsh-superagent-prototype 契约核实清单 v0.1

> **版本**: v0.1 ｜ **日期**: 2026-11-03 ｜ **状态**: 🟡 初稿——核实项已定义,原型源码**本地未找到**,待获取后执行
> **定位**: [SACG_A_SUPERAGENT_CONNECTION_SPEC v0.2](../../1-ARCHITECTURE/specs/SACG_A_SUPERAGENT_CONNECTION_SPEC.md) §2.1 G0 前置交付物
> **判定规则**: 本清单决定「借壳灌芯 A 步」是否可行——若核心核实项证伪,降级为「A 步仅借壳观察 + 灌芯走 B 步自研」(SPEC §五 风险表)
> **实测记录**: 每项核实后回填「结果 / 证据(文件:行) / 结论」三列

---

## 零、前置:原型获取(2026-11-03 实测)

| 检查 | 结果 |
|---|---|
| 本地 `.dsh-home` 存在 | ✅ `/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/.dsh-home`(profiles/web + storages + settings.yaml) |
| 本地存在 `superagent` profile | ❌ 仅 `web` profile |
| 全仓 find `*superagent*` 命中 | ❌ 仅文档(SACG_A SPEC),无源码/包 |
| **结论** | **dsh-superagent-prototype 源码当前不在本地** |

**获取途径待决(用户决策)**:
- [ ] D-a: 从 DeepSeek 官方渠道下载 MIT 原型 bundle(Harness bundle 格式)
- [ ] D-b: 若原型实为内部调研引用、无公开包,则 G0 降级——直接以 DSH 0.1.5-rc.2 现状核实「等效 hook 点」,走 B 步自研路径
- [ ] D-c: 其他获取途径

> ⚠️ 以下清单按「原型源码可获得」编排;若 D-b 成立,§一/§二 核实对象替换为现有 DSH 源码(`.dsh-home/profiles/web` 与 dream-harness-bridge)。

---

## 零·五、D-b 预研:现有 DSH 0.1.5-rc.2 等效 hook 点核实(2026-11-03 实测)

在用户决策 D-a/D-b 前,先对现有 DSH(web profile,cordis 插件架构)做等效 hook 点核实。**结果对两条路径都有效**(D-b 直接采用;D-a 可对照原型差异)。

### 实测发现:上下文注入 hook 点 **已存在且可外部注册**

| 核实项 | 结果 | 证据 |
|---|---|---|
| 插件架构 | ✅ cordis 事件驱动,`ctx.on(event, handler, {prepend})` 可注册中间件 | `.dsh-home/profiles/web/node_modules/@deepseek-ai/` 全量包 |
| **system prompt 组装 hook** | ✅ **`system-prompt/assemble` 瀑布事件**:handler 接收可变 `PromptAssembly`(sections/variables/tools),返回修改后 assembly;支持 `prepend:true` 在权威校验前注入 | `dsh-system-prompt/lib/invariant.js:33`;类型定义 `lib/types/index.d.ts:27` |
| 官方插件同机制 | ✅ `dsh-agent`、`dsh-scope` 均监听同一事件 | `dsh-agent/lib/index.js`、`dsh-scope/lib/invariant.js` |
| Assembly 可注入内容 | ✅ sections(静态文本或 provider 函数)、variables、tools schema;有 `renderPrompt(assembly)` 渲染管线 | `types/index.d.ts:57-147` |
| **初步判定** | 🟢 **D-b 可行性高**:L0 fetchContext 六维供给可实现为 cordis 插件,挂 `system-prompt/assemble` prepend,向 assembly 追加 section——无需 patch DSH 本体 | 本表 |

### 待补核实(下轮执行)

| # | 待核项 | 方法 |
|---|---|---|
| P-1 | `AssembleContext` 是否携带 thread/session 标识(关联 L0 引用链) | 读 `dsh-session` + `types/index.d.ts:36-56` 全量 |
| P-2 | 第三方插件注册方式(cordis.patch.yml 能否加载本地插件) | 读 web profile settings/bundle |
| P-3 | Mandate/Ticket 等效物:现有 DSH 会话是否有任务契约结构 | 读 `dsh-session` lib 全文 |
| P-4 | tools 在 assembly 中的裁剪机制(能力集 ≤10 的落点) | `types/index.d.ts:93-134` |

> ⚠️ 本预研**不替代** G0 正式核实:若用户选 D-a(拿到原型),§一/§二 仍需对原型源码执行;若选 D-b,本节即为主要依据,P-1~P-4 完成后 G0 闭环。

---

## 一、Mandate 字段 schema 核实(翻译目标格式)

> 目的:`okr_ticket_bridge.py` 的字段映射(SACG_A §4.2)必须落在原型真实 schema 上,不能按二手报道翻译。

| # | 核实项 | 方法 | 结果 | 证据 | 结论 |
|---|---|---|---|---|---|
| 1.1 | Ticket 数据结构定义位置 | 读 `store.py`(或等效)全量字段 | 待核 | | |
| 1.2 | `mandate.goal` 字段存在性与类型 | 对照 §4.2 映射表逐字段 | 待核 | | |
| 1.3 | `mandate.acceptance` 存在性与类型 | 同上 | 待核 | | |
| 1.4 | `mandate.evidence_refs[]` 存在性 | 同上 | 待核 | | |
| 1.5 | `external_ref` 字段(Chain of Recall 锚点) | 同上 | 待核 | | |
| 1.6 | Budget 字段(token/时长/成本上限) | 同上;ADR-5 依赖此项 | 待核 | | |
| 1.7 | Ticket 状态枚举(官方称 8 态) | 枚举值全量列出,与 ADR-3 四态映射 | 待核 | | |
| 1.8 | 工具授权字段(允许调用的工具集) | 与 Mandate 授权语义核对(G1/B2 依赖) | 待核 | | |

**通过标准**:1.1-1.8 全部字段找到且类型明确 → 翻译器 schema 冻结;任一字段缺失 → 翻译器需补默认值并在 SPEC 登记偏差。

---

## 二、上下文注入 hook 点核实(灌芯可行性,**最高优先级**)

> 目的:决定 L0 六维供给(fetchContext)能否在 Worker 执行前注入。这是整个「灌芯」策略的证伪点。

| # | 核实项 | 方法 | 结果 | 证据 | 结论 |
|---|---|---|---|---|---|
| 2.1 | Worker 执行前是否存在 context 组装函数 | 读 `session.py`,定位 prompt/context 构建入口 | 待核 | | |
| 2.2 | 该函数是否可外部注入(参数/回调/子类) | 检查签名与调用点 | 待核 | | |
| 2.3 | 注入点是否带 thread_id(可关联 L0 引用链) | 同上 | 待核 | | |
| 2.4 | bundle 配置层是否暴露注入开关 | 读 bundle manifest/cordis.patch.yml 示例 | 待核 | | |
| 2.5 | Worker 返回格式(SubagentOutput 压缩摘要) | 对照 DSH_SUBAGENT_ARCHITECTURE_SPEC | 待核 | | |

**判定矩阵**:

| 2.1 | 2.2 | 判定 |
|---|---|---|
| ✅ | ✅ | **灌芯可行**,B1 翻译器按 A 步推进 |
| ✅ | ❌ | 半可行——需 patch 原型(独立 profile 内允许),登记改造清单 |
| ❌ | — | **证伪 → 降级 B 步自研**:A 步仅借壳观察(独立 profile 跑 bundle 学行为),Worker 灌芯在 dream-harness-bridge 自研实现 |

---

## 三、事件与生命周期核实(P1 输入,不阻塞 P0)

| # | 核实项 | 方法 | 结果 | 证据 | 结论 |
|---|---|---|---|---|---|
| 3.1 | Trigger 抽象定义(字段/注册方式) | 读原型 trigger 模块 | 待核 | | |
| 3.2 | Thread/Subscription 实现机制 | 同上 | 待核 | | |
| 3.3 | paused/resume 持久化位置(存算分离验证) | 读 store 层 | 待核 | | |
| 3.4 | Watchdog 独立会话形态 | 读 watchdog 模块(如有) | 待核 | | |
| 3.5 | Policy 白名单机制(SACG_A §4.1 依赖) | 读 bundle policy 配置 | 待核 | | |

---

## 四、隔离与安全核实(HC-3/HC-4 依赖)

| # | 核实项 | 方法 | 结果 | 证据 | 结论 |
|---|---|---|---|---|---|
| 4.1 | profile 级状态目录隔离机制 | storages 目录结构 | 待核 | | |
| 4.2 | 凭据读取范围(是否可限定测试仓 token) | 配置项核实 | 待核 | | |
| 4.3 | BYOM/设备接入开关默认状态 | 配置项核实(SPEC 非目标:不启用) | 待核 | | |
| 4.4 | 网络出口(是否外呼非预期域名) | 依赖与配置静态审查 | 待核 | | |

---

## 五、核实执行方式(拿到源码后)

1. 源码放置:`.dsh-home/vendor/dsh-superagent-prototype/`(不入库或 gitignore,MIT 版权头保留)
2. 逐项核实并回填本清单「结果/证据/结论」三列(证据 = `文件:行号`)
3. 产出**核实纪要**(本文件升 v1.0)+ 判定结论(灌芯可行 / patch 后可行 / 证伪降级)
4. 判定结果回填 SACG_A SPEC §2.1 G0 行 + 触发对应路径(A 步推进 / patch 清单 / B 步自研)
5. 认知闭环:record(结论 + 关键 schema 事实,tags=G0,借壳灌芯,46-DSH架构)

---

## 六、当前阻塞与解锁条件

| 阻塞 | 解锁条件 | 负责人 |
|---|---|---|
| 原型源码不在本地 | 用户决策获取途径(§零 D-a/D-b/D-c)。**2026-11-03 预研已证实 D-b 可行**(§零·五),若用户认可 D-b 可直接解锁 P-1~P-4 | 用户 |

> **本清单价值**:即使最终 D-b(原型不可得),§一/§二 核实项可直接平移到现有 DSH 源码核实,不返工。
