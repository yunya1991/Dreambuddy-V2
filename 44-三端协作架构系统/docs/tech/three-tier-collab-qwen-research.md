# 千问调研报告：Dreambuddy V2 三端协同体系

> 来源：dream-qwen-eval-collab 步骤2 | 日期：2026-10-29 | bsk session: wpsa | chat: 28239535281e4a1187842cd8faf33fad | 21篇来源

Dreambuddy V2 三端架构深度调研报告
一、四个维度的业界模式与单人裁剪
1. 传统金融：投研-交易-风控-运营分工
业界成熟模式
传统金融机构采用四层分离架构：
投研层：因子挖掘、策略假设、回测验证（投研委员会评审）
交易层：订单执行、滑点控制、成交监控（交易室独立操作）
风控层：独立于交易，拥有否决权与熔断权（VaR、压力测试、实时限额）
运营层：资金清算、合规留痕、审计归档
单人裁剪建议
你无法物理分人，但可以逻辑分角色。将30+ SKILL按角色分组，每个SKILL执行时自动打上角色标签（researcher/trader/risk/operator），形成"一人四帽"的审计链。关键约束：风控SKILL必须拥有独立熔断通道，不经过交易逻辑。
三端落地
角色	云端	GitHub	本地
角色	云端	GitHub	本地
投研	主训pipeline、回测引擎	策略代码版本、实验记录	技术方案评审、因子评估
交易	22个systemd服务实盘执行	Release assets分发模型	只读日志排查、信号验证
风控	独立风控timer、熔断服务	风控规则PR门禁	风控参数调优、压力测试
运营	数据留痕、MinIO归档	CI/CD审计日志	架构审查、变更审批
2. 技术开发：GitOps + SRE
业界成熟模式
GitOps：Git为唯一可信源，ArgoCD/Flux自动同步集群状态
分支策略：feature → dev → staging → main，PR逐级promotion
SRE：design doc评审、postmortem、错误预算、SLO/SLI监控
单人裁剪建议
省略staging环境（资源受限），但保留dev→main的PR门禁。SRE实践中，postmortem和错误预算对单人仍有价值——每次故障写一页复盘，错误预算转化为"每月允许的最大故障次数"。
三端落地
本地：写design doc → 开feature分支 → 提PR
GitHub：CI门禁（lint/test/build）→ PR自动merge到main → 触发deploy workflow
云端：systemd服务按Git tag版本拉取更新，健康检查失败自动回滚到上一tag
3. AI赛道：模型生命周期管理
业界成熟模式
MLflow Model Registry标准状态机：
文本
编辑
1
None → Staging → Production → Archived
训练完成自动注册为None
自动化评估通过→Staging
金丝雀验证通过→Production（自动archive旧版）
监控发现漂移→回滚到上一Production版本
单人裁剪建议
省略金丝雀发布（4C8G跑不动双模型），但保留自动评估+手动promote两道关。本地辅训的模型通过GitHub Release assets回传云端，由云端pipeline统一注册。
三端落地
云端主训：训练→MLflow注册→自动eval→tag为Staging→手动promote到Production→systemd热加载
本地辅训：训练→本地eval→上传GitHub Release→云端CI拉取→注册为Staging→同上流程
回滚：一键切换Production tag到上一版本，systemd reload
4. 产品管理：跨职能协作
业界成熟模式
RACI矩阵、双周评审节奏、变更管理（CAB变更咨询委员会）
单人裁剪建议
RACI保留但简化为自我RACI——每个变更明确自己是R（执行者）还是A（批准者）。评审节奏改为周度自我review，用GitHub Project追踪。变更管理简化为"重大变更必须开PR+写design doc"。
二、Q1：三端职责RACI矩阵（流程级）
流程节点	本地(macOS)	GitHub	云端(腾讯云)	说明
流程节点	本地(macOS)	GitHub	云端(腾讯云)	说明
技术方案设计	R/A	-	-	写design doc，本地评审
代码开发	R	托管	-	feature分支开发
Code Review	A	门禁执行	-	自我review+CI自动检查
CI构建/测试	-	R/A	-	GitHub Actions执行
模型训练（主）	-	触发	R	云端timer触发
模型训练（辅）	R	存储Release	-	本地训练后上传
模型注册	-	-	R/A	MLflow注册+eval
模型Promote	A	-	R	本地决策，云端执行
部署上线	-	触发	R	CI触发云端deploy
健康检查	只读查看	-	R	云端自检+本地只读日志
故障排查	R	查CI日志	R	本地主导，云端配合
Postmortem	R/A	归档	-	本地写复盘，GitHub存档
架构优化	R/A	-	-	本地审查数据流
评审时机：design doc在开PR前完成；PR merge前CI全绿；模型promote前本地确认eval指标。
排查SLA：P0（交易中断）→ 15分钟内响应，本地+云端并行排查；P1（数据延迟）→ 2小时；P2（非关键告警）→ 24小时。
问题升级路径：云端告警 → 本地收到通知 → 本地查日志定位 → 若无法定位 → 回滚到上一稳定版本 → 写postmortem。
三、Q2：完整CI/CD门禁链设计
文本
编辑
1
本地开发 → GitHub PR → CI门禁 → 云端部署 → 健康检查
门禁序号	门禁名称	执行位置	检查内容	失败处理
门禁序号	门禁名称	执行位置	检查内容	失败处理
G1	Pre-commit Hook	本地	lint、secret扫描、commit message规范	阻止commit，本地修复
G2	PR CI门禁	GitHub Actions	单元测试、集成测试、依赖安全扫描	PR标记failed，禁止merge
G3	Build门禁	GitHub Actions	Docker镜像构建、镜像大小检查	构建失败→通知本地，修复后重推
G4	Deploy门禁	GitHub Actions	检查云端健康状态、确认非交易时段	不满足条件→进入pending队列
G5	云端部署验证	云端	systemd服务启动检查、端口监听验证	启动失败→自动回滚到上一tag
G6	健康检查	云端	30秒内API响应、数据库连接、Redis连通性	连续3次失败→自动回滚+告警通知本地
G7	模型Eval门禁	云端	新模型vs生产模型指标对比	不达标→保持Staging，不promote
关键设计原则：
G5/G6失败自动回滚，无需人工干预
G2/G3失败必须本地修复，不允许force merge
交易时段（根据加密货币7×24特性，可定义"高波动时段"）禁止deploy
四、Q3：30+ SKILL治理注册体系
注册表设计（YAML + Git管理）
yaml
编辑
1
skills/

2
├── registry.yaml          # 总注册表

3
├── research/              # 投研类SKILL

4
│   ├── factor_mining.skill

5
│   └── backtest_runner.skill

6
├── trading/               # 交易类SKILL

7
│   ├── order_executor.skill

8
│   └── signal_generator.skill

9
├── risk/                  # 风控类SKILL

10
│   ├── position_limiter.skill

11
│   └── circuit_breaker.skill

12
└── ops/                   # 运营类SKILL

13
    ├── data_archiver.skill

14
    └── log_rotator.skill
每个SKILL的元数据
yaml
编辑
1
skill_id: factor_mining_v2

2
version: 2.3.1

3
category: research

4
dependencies:

5
  - pandas>=2.0

6
  - mlflow>=2.10


7
  - skill: data_fetcher  # 依赖其他SKILL

8
  - skill: backtest_runner

9
lifecycle: active  # active/deprecated/archived

10
owner: researcher  # 角色标签

11
last_updated: 2026-10-29

12
compatibility:

13
  min_python: "3.10"

14
  max_python: "3.12"

15
conflicts_with: []  # 互斥SKILL列表
生命周期管理
注册：新SKILL提交PR→CI检查元数据完整性→merge后自动加入注册表
版本：语义化版本（MAJOR.MINOR.PATCH），breaking change必须升MAJOR
依赖解析：部署前运行依赖检查脚本，检测循环依赖和版本冲突
冲突检测：同一category下互斥SKILL不能同时active（如两个不同的order_executor）
废弃：deprecated标记后保留1个版本周期，之后archive
运行时治理
云端每个systemd服务启动时加载注册表，只激活所属category的SKILL。本地可通过CLI工具查询所有SKILL状态、依赖树和冲突情况。
五、Q4：模型生命周期状态机
文本
编辑
1
                    ┌─────────────────────────────────────┐

2
                    │                                     │

3
                    ▼                                     │

4
  ┌────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐│

5
  │ None   │──│ Staging  │──│Production│──│ Archived ││

6
  │(刚注册) │   │(评估中)  │   │(实盘运行) │   │(已归档)  ││

7
  └────────┘   └──────────┘   └──────────┘   └──────────┘│

8
       ▲              │              │                    │

9
       │              │              │                    │

10
       │              ▼              │                    │

11
       │        ┌──────────┐        │                    │

12
       │        │ Rejected │────────┘                    │

13
       │        │(评估失败) │                             │

14
       │        └──────────┘                             │

15
       │                                                 │

16
       └─────────────────────────────────────────────────┘

17
                        (回滚)
云端主训路径
训练完成 → MLflow自动注册为None
自动Eval → 与当前Production模型对比指标 → 达标→Staging，不达标→Rejected→Archived
手动Promote → 本地确认Staging模型指标后，调用API transition到Production（自动archive旧版）
热加载 → systemd服务监听MLflow tag变化，检测到Production tag更新后，通过mlflow.pyfunc.load_model("models:/xxx/Production")热加载，无需重启服务
监控漂移 → 实时指标低于阈值 → 自动回滚：将上一Archived版本重新tag为Production
本地辅训路径
本地训练 → 本地eval → 达标后上传模型artifact到GitHub Release（带eval指标摘要）
云端CI监听GitHub Release → 自动下载 → 注册到MLflow为None
后续流程同云端主训路径（自动eval → Staging → 手动promote → Production）
回滚机制
快速回滚：直接调用MLflow API将上一版本tag为Production，systemd服务热加载（秒级）
完整回滚：Git revert到上一tag → 重新deploy整套服务（分钟级，用于代码+模型同时回滚）
六、风险与反模式识别
反模式	说明	建议
反模式	说明	建议
云端单点故障	4C8G单机跑22+服务+数据库，无冗余	至少将PG/Redis/MinIO做定期快照备份到MinIO异地bucket
本地成为瓶颈	后期本地转辅训，macOS算力有限	辅训仅做轻量微调，主训保留在云端；考虑按需租用GPU实例
过度工程化	单人维护ArgoCD/K8s等重型工具	当前systemd+Docker足够，GitOps用简单的"git pull + systemctl restart"即可
SKILL膨胀失控	30+ SKILL继续增长，依赖地狱	严格执行注册表治理，每季度做一次SKILL审计，合并功能重叠的SKILL
模型漂移无感知	缺少生产环境监控	至少部署基础指标监控（预测分布、置信度、交易胜率），异常时告警
GitHub单点依赖	CI/CD和模型分发全靠GitHub	关键模型artifact同时备份到云端MinIO
无灾备演练	从未测试过回滚流程	每季度做一次"模拟故障→回滚"演练，记录恢复时间
七、P0/P1/P2落地优先级建议
P0（立即实施，1-2周内）
CI门禁链G1-G3：pre-commit hook + GitHub Actions测试门禁，阻止坏代码进入main
模型注册中心：部署MLflow，实现None→Staging→Production基础状态机
SKILL注册表v1：建立registry.yaml，完成现有30+ SKILL的元数据采集
云端健康检查：为关键systemd服务添加watchdog，失败自动重启
P1（1个月内）
GitOps简化版：云端deploy脚本从GitHub拉取最新tag，systemd自动reload
模型热加载：实现Production tag变化时自动reload模型，无需重启服务
风控独立通道：将风控SKILL从交易链路中解耦，拥有独立熔断能力
GitHub Release辅训通道：打通本地训练→上传Release→云端注册的流程
P2（1-3个月）
SKILL依赖解析与冲突检测：实现完整的依赖树检查和互斥检测
监控与告警体系：部署基础指标监控（Prometheus+Grafana或轻量替代）
Postmortem模板化：建立故障复盘模板，GitHub归档
灾备演练：首次完整回滚演练，记录RTO/RPO
核心建议：你当前最大的杠杆点是把30+ SKILL纳入治理体系和建立模型状态机。这两项完成后，系统的可维护性和可追溯性会有质的飞跃。GitOps和SRE实践可以渐进式引入，避免一次性改造带来过大风险。
Dreambuddy V2 三端架构深度调研报告
已排版
创建于 10-29 20:45
需要我为你生成这份方案的初始代码框架吗？比如CI门禁链的GitHub Actions配置或SKILL注册表的Python解析脚本。
好的，帮我生成
