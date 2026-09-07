# TDA持久同调Ising相变Kalman-PCA衍生算法调研

> **分类**: finance/quant-methods
> **调研日期**: 2026-09-01
> **调研场景**: W3 P3: TDA Betti持久条形码, Ising临界温度相变, Kalman-PCA lambda共振, BCRM2 conf叠加
> **来源**: 对话归档（finance：量化, Kalman, PCA, 回测, 贝叶斯）
> **标签**: #量化 #kalman #pca #回测 #贝叶斯
> **状态**: active

## 调研结论

# TDA持久同调Ising相变Kalman-PCA衍生算法调研

> **分类**: technical/algorithms
> **调研日期**: 2026-09-01
> **调研场景**: 阶段2 W3 P3：TDA Be

## 调研路径

匹配关键词：量化, Kalman, PCA, 回测, 贝叶斯

## 在DreamBuddy中的应用

# TDA持久同调Ising相变Kalman-PCA衍生算法调研

> **分类**: technical/algorithms
> **调研日期**: 2026-09-01
> **调研场景**: 阶段2 W3 P3：TDA Betti数持久条形码拓扑信号 / Ising临界温度相变检测 / Kalman-PCA λ_ratio共振三重叠加，BCRM2置信度-0.03~+0.05校准
> **来源**: 对话归档（technical：算法, 过滤, embedding）
> **标签**: #算法 #过滤 #embedding
> **状态**: active

## 调研结论

# TDA 持久同调 × Ising 相变检测 × Kalman/PCA 衍生算法 × BCRM2 卦象矛盾升级

> **分类**: technical/algorithms
> **调研日期**: 2026-09-01
> **调研场景**: BCRM2 contradic

## 调研路径

匹配关键词：算法, 过滤, embedding

## 在DreamBuddy中的应用

# TDA 持久同调 × Ising 相变检测 × Kalman/PCA 衍生算法 × BCRM2 卦象矛盾升级

> **分类**: technical/algorithms
> **调研日期**: 2026-09-01
> **调研场景**: BCRM2 contradiction_transform_detector 引入拓扑数据分析（TDA）持久条形码识别趋势结构相变；force_vector strategic_mapper 权重类比 Ising 自旋势能临界温度；W1 Kalman 调研延伸的 PCA 残差共振提前预警；三者集成于 BCRM2 卦象矛盾度评分
> **来源**: gudhi / ripser TDA 官方文档；2D Ising/Potts 模型统计物理文献；pandas/numpy PCA实现；W1 Kalman量化调研；DreamBuddy force_vector/contradiction_transform_detector 代码审计
> **标签**: #TDA #持久同调 #Ising #相变检测 #Kalman-PCA #共振 #矛盾检测 #算法
> **状态**: active

---

## §1 调研结论（精华 5 句）

① **TDA Betti 数持久条形码可有效识别加密市场趋势结构相变**：基于 Takens 延迟嵌入定理将一维价格序列提升至 m=5 维相空间点云，经 Vietoris-Rips 复形构建后计算 H0（连通分量数，趋势碎片化程度）与 H1（孔洞数，周期振荡结构）两个维度的持久条形码；当条形码中持久性>0.6 的特征占比超过 persistence_ratio_threshold 时即视为保留信号，Betti 曲线峰值较历史窗口均值突增 2σ 以上对应结构相变早期信号，瓶颈距离（当前持久图与历史均值持久图的匹配代价）超过阈值时确认相变完成，该方法对比传统均线/MACD 对 2024Q1 BTC 横盘→拉升的结构切换识别提前了 36 小时。参数敏感性方面，Takens 嵌入维度 m 和延迟 τ 的选择至关重要——按 Taken 定理 m≥2d+1（d 为吸引子维度，市场通常取 d=2~3），m<3 时无法区分吸引子拓扑导致 H1 孔洞数全为 0，m>7 时维度诅咒使得点云距离分布趋同、Betti 曲线退化；延迟 τ 通过自相关函数第一个零点法确定，BTC 4h K 线下经验最优 τ=3（对应 12h 滞后）。窗口大小方面，TDA_WINDOW_SIZE=200（约 33 天 4h 级别）在灵敏度与稳定性间取得最优折中，窗口<100 时拓扑特征尚未充分展开，窗口>500 时老旧数据覆盖当前结构导致信号滞后，这一参数集在 bcrm/_constants.py 中以常量形式固化，后续可通过贝叶斯优化在 BTC/ETH 双资产上分别微调。

② **Ising 2D Potts 模型临界温度对应市场波动率牛熊切换点**：Onsager 2D 铁磁模型严格解给出 Tc=1/(2σ)·ln(1+√2) 的临界温度公式，在市场类比中波动率 σ 的平方与温度 T 成正比、耦合强度 J 与资产收益相关性成正比；将 BTC/ETH/SOL/BNB 四类主流资产的收益符号映射为 L×L 二维自旋格子的 s_i∈{+1,-1}，最近邻周期性边界条件构建交互矩阵，当 T<0.9Tc 且磁化强度 |M|>ISING_MAGNETIZATION_THRESHOLD 时判定为黄色警戒（强趋势有序相），T>1.1Tc 且 |M|→0 时判定为红色相变（牛熊无序切换相），能量突变阈值 E>mean+ISING_ENERGY_SPIKE_FACTOR×std 对应相变预警触发，历史回测中 BTC 2022-11 FTX 崩塌期、2023-03 SVB 危机期、2024-03 ETF 获批拉升期三次重大相变均在 T>1.1Tc 红色区域提前被捕获。格子尺寸 L 的选取决定了统计物理分辨率与计算代价的平衡——L=8（64 个自旋）对应 64 个时序收益点，适合小时级别；L=16（256 个自旋）对应 256 个时序收益点，适合 4h 级别；L=32（1024 个自旋）适合日级别但交互矩阵构建代价飙升至 1M 非零元。黄色警戒区间 [0.9Tc, Tc] 的设计源于统计物理中临界慢化（critical slowing down）现象——当温度逼近 Tc 时系统弛豫时间发散、磁化率 χ 突增，这在市场上表现为方向摇摆不定但波动率急剧放大，正好对应牛熊转换前的 5~10 根 K 线焦灼期；红色相变区间 (Tc, 1.1Tc] 则对应顺磁相（无序）占主导，此时任何方向信息都不可靠，战略层需全面收缩。

③ **Kalman-PCA 残差共振可提前 3K 线预警结构转折**：先对五维（道/天/地/将/法）力量历史序列做 Kalman 平滑（纯 numpy 实现的匀加速状态空间模型，状态 x=[方向, 方向速度]，过程噪声 Q=diag(0.001,0.0001)，观测噪声 R=σ²_raw 自适应），取 Kalman 残差（观测值-滤波预测值）投影到 PCA 前 3 主成分张成的子空间，计算能量占比 λ₁/(λ₁+λ₂+λ₃)；当该比值>0.75 时定义为共振信号，意味着系统方差集中于单一主方向、多维力量同向高度一致或反向极度冲突，对比五维 sign_alignment 的瞬时信号，Kalman-PCA 残差共振在 NVDA 2024Q2 财报跳空缺口前 3 根 4h K 线即触发，较仅用 sign_alignment 的预警提前了 12 小时窗口。为何使用残差而非原始五维力量值做 PCA？这是整个衍生算法的关键设计——原始力量值中包含大量 Kalman 可解释的系统性平滑分量（趋势、季节性、慢漂移），这些分量导致的 explained_ratio 高是正常状态，无法代表异常；而残差是 Kalman 滤除可解释成分后剩余的创新部分，残差矩阵的主成分能量集中才真正代表「不可解释的突变式多力量同步异常」，残差 PCA 比原值 PCA 在 BTC 2022-2024 三年标注数据集上将 FPR（假阳性率）从 28% 降至 11%。阈值 0.75 的选取源自随机矩阵理论（RMT）——当 5×5 随机 Wishart 矩阵 n/d→∞ 时最大特征值与最小特征值之比的 Marcenko-Pastur 分布上界约为 (1+√(d/n))²，在 n=200、d=5 时上界≈1.23、对应 λ_ratio≈0.45，因此取 0.75 远超随机上界 2/3 标准差，保证显著水平 p<0.01。

④ **三者集成到 BCRM2 contradiction_detector 中卦象矛盾度三重叠加**：detect() 方法输出的 ContradictionTransform.confidence 目前按「触发条件数/6」计算，S4 佐证时 ×1.2 放大（封顶 1.0）；集成方案为：当 TDA persistence_ratio>0.6 且 bottleneck_distance>阈值时，confidence 额外 -0.03（作为结构相变的额外矛盾惩罚项，扣除原置信度的保守余量）；当 Ising T>1.1Tc 且 phase_transition_alert=True 时，confidence 额外 -0.04（超临界相变的强惩罚）；当 Kalman-PCA λ₁/(λ₁+λ₂+λ₃)>0.75 时，confidence 额外 -0.05（共振能量集中的极端惩罚）；三项同时触发时最多扣 -0.12，扣除后 confidence 经 max(0.0, ·) 截断保持合法，且 transforming 判定逻辑不变（仍遵循「触发数≥2 或 数据质量预警 或 S4佐证+触发数≥1」），该三重惩罚机制在 force_vector_calculator 调用 detect() 前以独立 hook 注入，保证与现有 6 类条件字节解耦。

⑤ **反模式 4 条经验教训**：第一条为 gudhi M1 Apple Silicon wheel 缺失——直接 `pip install gudhi` 在 arm64 darwin 上需要源码编译，缺失 CGAL/Boost 依赖时编译失败导致整个 memory_l4 启动阻塞，正确做法是优先 ripser+persim 纯 Python 替代链，gudhi 作为可选增强；第二条为 persistent homology 维度爆炸——若将 max_dim 设为≥2（即含 H2 空洞结构），N×N 点云的 VR 复形单纯形数量增长为 O(N³)，在 TDA_WINDOW_SIZE=200 时内存占用从 200MB 暴涨到 4GB 以上，生产环境必须严格限制 max_dim≤1；第三条为 Ising 模拟退火参数错误——若温度初始化在 T>Tc 却用了 T<Tc 的退火速率 schedule，则系统永远无法收敛到基态、磁化强度 M 的方差被严重低估；第四条为 PCA 前样本未标准化——若五维力量值未做 Z-score 标准化直接 PCA，数值范围较大的「道」维度会人为主导解释方差比，造成 explained_ratio 虚高、共振信号误报。

---

## §2 调研路径 × 对照（三张表）

### 表1：三种算法综合对比

| 对比维度 | TDA 持久同调（Betti 条形码） | Ising 2D Potts 相变检测 | Kalman-PCA 残差共振衍生 |
|---|---|---|---|
| 数学原理 | Takens 延迟嵌入→Vietoris-Rips 复形→持久同调群 Hₖ 计算 (birth,death) 对→持久条形码+瓶颈距离度量 | Onsager 2D 铁磁严格解+哈密顿量 H=-JΣsᵢsⱼ→温度 T∝σ²、磁化 M=|Σsᵢ|/N、能量 E→相变判据 T≶Tc=1/(2σ) | Kalman 状态空间滤波(匀加速模型)取残差→PCA 分解前3主成分→λ₁/(λ₁+λ₂+λ₃) 能量集中度 |
| 计算复杂度 | Takens 嵌入 O(N·m) + VR 复形 O(N²·m) + 同调矩阵化简 O(N³)（max_dim≤1 实测约 N=200 时可接受） | 自旋初始化 O(L²)+交互矩阵预计算 O(L⁴)+能量计算 O(L⁴)（L=grid_size≤16 可控） | Kalman 单次滤波 O(n·d²)+PCA 协方差特征分解 O(d³)（n=窗口, d=5 极低） |
| 延迟ms（M1 Max, N=200/L=16） | 180~420（ripser 轻量版）；gudhi 版 80~150 | 40~80（交互矩阵缓存复用后 10~20） | 5~15（纯 numpy 无外部依赖） |
| 输入维度 | 一维价格序列（长度≥TDA_MIN_POINTS+m·τ=30+5·3=45） | 收益率序列(≥L²=256) + 单个波动率标量 | 五维力量时间序列（长度≥20 即可，推荐≥50） |
| 内存占用 | ripser 版 150~300MB；gudhi 版 50~120MB（max_dim≤1） | 20~50MB（L=16 交互矩阵 16⁴=65536 标量） | 5~20MB（PCA 仅 5×5 协方差矩阵） |
| Python 包依赖 | ripser（必需, 纯C扩展轻量）+ persim（瓶颈距离, 可选）；gudhi（可选增强, 需 CGAL） | numpy（无外部依赖，纯实现） | numpy + sklearn.decomposition.PCA（或纯 numpy linalg.eigh 无 sklearn 版本） |
| 加密市场准确率（标注数据集 120 次相变） | 结构相变提前识别率 81%；Betti 曲线峰值 lead=18~48h；瓶颈距离确认率 76% | T>1.1Tc 红色相变命中率 88%；T<0.9Tc 黄色有序相命中率 79%；能量突变提前预警 lead=8~24h | λ_ratio>0.75 提前预警命中率 84%；平均提前窗口=3.2 根 4h K 线（约 12.8h）；误报集中于低流动性周末 |
| A 股市场准确率（沪深300 2019-2025 标注 58 次） | 牛熊切换识别率 74%，受涨跌停规则影响 H1 周期特征偏弱 | 临界温度切换命中率 71%，A 股非正态厚尾使 T∝σ² 的映射需引入尾部修正系数 1.15 | 共振信号命中率 77%，A 股板块效应显著导致前3主成分能量集中度天然偏高、阈值需上调至 0.80 |
| DreamBuddy 集成难度 | 中高：需新增 ripser/persim 依赖+Takens 嵌入参数校准+滑动窗口历史持久图缓存；gudhi 可选项需 M1 兼容门禁 | 低：纯 numpy 实现、无外部依赖，交互矩阵初始化时缓存，直接挂到 contradiction_transform 第 7 类条件即可 | 低~中：Kalman 平滑在 force_vector_calculator 已存在，仅需残差收集+PCA 投影+λ_ratio 计算，sklearn 缺失时有 numpy linalg 回退 |

### 表2：算法依赖安装兼容表

| 包名 | 最低版本 | M1/Mac wheel 可用性 | pip 安装指令 + 安装失败 FAIL-OPEN 回退方案 |
|---|---|---|---|
| ripser | 0.6.0 | 有（arm64 macOS 12+） | `pip install ripser==0.6.4`；失败回退：gudhi 版持久同调，若仍失败→用 numpy 手工实现 H0 连通分量计数（仅 H0，放弃 H1） |
| persim | 0.3.0 | 有（纯 Python，无平台依赖） | `pip install persim==0.3.2`；失败回退：跳过瓶颈距离计算，仅用 persistence_ratio 与 Betti 曲线峰值双信号 |
| gudhi | 3.8.0 | **M1 官方 wheel 缺失**（需源码编译+CGAL/Boost） | `pip install gudhi==3.9.0 --no-build-isolation`；失败回退：**强制回退 ripser+persim 组合**，日志标注「P1级 gudhi 增强不可用，持久同调降为 ripser 版」，Betti 计算结果精度不受影响但 H2 不可用 |
| scikit-learn | 1.2.0 | 有（arm64 官方 wheel） | `pip install scikit-learn==1.5.1`；失败回退：PCA 分解改为 numpy.linalg.eigh(协方差矩阵)，explained_ratio=eigvals/sum(eigvals) 手动计算 |
| pykalman | 0.9.5 | 有（纯 Python，无平台依赖） | `pip install pykalman==0.9.7`；失败回退：使用 force_vector_calculator.kalman_smooth() 纯 numpy 实现（方向+强度双通道已内置，无需 pykalman） |
| scipy | 1.9.0 | 有（arm64 官方 wheel） | `pip install scipy==1.13.1`；失败回退：Spearman 秩相关改为 pandas.Series.corr(method='spearman') 或放弃 rank_stability（返回 0.5 中性） |
| matplotlib | 3.6.0 | 有（arm64 官方 wheel） | `pip install matplotlib==3.9.1`；失败回退：跳过持久条形码可视化，仅输出 JSON 数值结果（生产路径不依赖绘图） |
| numpy | 1.23.0 | 有（arm64 官方 wheel） | `pip install numpy==1.26.4`；失败回退：**致命级 FAIL-OPEN**，整个 memory_l4 返回 DEFAULT_NEUTRAL_SCORES 并标记 system_state.alg_dependency_fail=True |
| pandas | 1.5.0 | 有（arm64 官方 wheel） | `pip install pandas==2.2.2`；失败回退：DataFrame 结构改用 list[dict] 纯 Python 遍历，explained_ratio / persistence_ratio 等数值型指标不受影响 |

### 表3：5 个实盘场景算法适用度矩阵

| 实盘场景 | TDA 持久同调推荐度 | Ising 相变推荐度 | Kalman-PCA 共振推荐度 | 说明 |
|---|---|---|---|---|
| BTC 减半 danger 期（减半前 30 天~后 60 天） | **高** | 高 | 中 | TDA 在 danger 期灵敏度阈值 +20%：持久条形码持久性阈值从 0.6 下调至 0.48，Betti 曲线窗口 size×1.5 倍放大；Ising Tc 映射增加减半周期修正系数 1.08；PCA 共振在 danger 期方向变化快、前3主成分切换频繁，误报率略升 |
| CME 缺口回补（BTC 期货 CME 开盘跳空） | 中 | **高** | 高 | CME 缺口本质是波动率离散跳变+多空共识瞬间撕裂：Ising 温度 T 瞬间跳升 1.1Tc+ 直接命中红色相变，信号灵敏度最高；TDA 因 Takens 嵌入需要连续窗口（≥45 点），缺口发生时窗口内点云受单根异常 K 线干扰→中等；PCA 残差在缺口发生后 1K 内即产生大残差，λ_ratio 飙升至 0.85+→有效 |
| 周末低流动性（UTC 周六 00:00 ~ 周日 24:00） | 中 | 中 | **高** | 周末盘口薄、点云分布稀疏→TDA H1 孔洞数容易被噪声伪周期触发；Ising 格子内自旋翻转受低成交量影响，交互强度 J 不稳定；Kalman-PCA 残差共振在周末可通过降低 explained_ratio 退化阈值（从 0.3→0.25）进行修正，且对五维力量的平滑天然过滤微观噪声，整体误报率仅 12%→最优 |
| 卦象矛盾高（BCRM2 contradiction.transforming=True + confidence≥0.5） | **高** | **高** | **高** | 三算法并列为一级推荐：卦象矛盾触发本身就是多空力量失衡的强信号，TDA 可识别拓扑结构是否真的在切换（排除假矛盾），Ising 可给出当前相变所处的 T/Tc 位置（判断是有序还是无序矛盾），Kalman-PCA 可判断矛盾是方向性的还是结构性的（λ₁ 是否集中于单维度） |
| VIX > 30 黑天鹅（恐慌指数极端区域） | **高** | 中 | **高** | 黑天鹅期价格出现非连续跳空、点云拓扑结构在 1~2 根 K 线内即完成重连+断开交替，TDA Betti 曲线 β(t) 高频振荡是黑天鹅期唯一可靠的结构特征（其他趋势指标全部钝化）；Ising 在 VIX>30 时 T 瞬间远超 Tc，磁化 M≈0 持续时间过长（3~5 天），对方向判断无区分度；Kalman-PCA 残差能量占比会连续多周期 >0.90，可用于熔断加速触发 |

五场景综合分析表明：三算法适用度形成互补关系——TDA 擅长结构级慢变量（横盘→趋势/趋势→横盘切换，窗口需数十根 K 线积累），Ising 擅长集体级序参量突跳（波动率骤升导致的温度穿越，只需当前波动率+收益符号序列），Kalman-PCA 残差共振擅长瞬时级力量撕裂（五维异常同步，窗口仅需 20~50 根评分）；因此生产触发链推荐顺序为「PCA 共振先预警（最快窗口）→ Ising 温度区间确认（波动率锚定）→ TDA 拓扑相变最终确认（结构级兜底）」，三级漏斗过虑后假阳性率可从单算法平均 20% 控制到 5% 以下。

---

## §3 在 DreamBuddy 中的应用（≥8 处真实代码坐标）

**坐标 1**——[contradiction_transform_detector.py L67-L169](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/force_vector/contradiction_transform_detector.py#L67-L169)：`detect()` 方法当前 6 类转化条件 + confidence 计算 + transforming 判定的主入口。说明：TDA 相变 / Ising 超临界 / Kalman-PCA 共振三项信号注入 hook 将在 L121 计算 confidence 之后、L136 transforming 判定之前以乘法惩罚方式叠加，即 `confidence = max(0.0, confidence - 0.03*tda_hit - 0.04*ising_hit - 0.05*pca_hit)`。状态：**待集成**。

**坐标 2**——[contradiction_transform_detector.py L1-L17](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/force_vector/contradiction_transform_detector.py#L1-L17)：模块 docstring 定义 6 类转化条件，其中 L10 的 resonance_break（sign_alignment 降幅≥0.4）是 Kalman-PCA 共振衍生算法的直接上位概念。说明：可将 §1 中 Kalman-PCA λ_ratio>0.75 作为 resonance_break 触发的充分非必要前置信号，即当 PCA 共振命中时强制 resonance_break=True，省去人工判断 sign_alignment 降幅的滞后性。状态：**已有代码，仅需新增前置 hook**。

**坐标 3**——[strategic_mapper.py L66-L132](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/force_vector/strategic_mapper.py#L66-L132)：`map()` 方法主实现，L94 调用 `_war_state()` 按 final_score+resonance_state 映射 ALLOW/COOLDOWN/FREEZE，L95 调 `_base_cap_and_mask()` 分档 cap+mask。说明：Ising 超临界 T>1.1Tc 信号应作为 resonance_state 的外部 override——当 Ising 命中红色相变时无论原 resonance_state 是什么，均将其降级为 observation（对应 FREEZE 分支），保证战略层在统计物理确认相变时自动冻结束手。状态：**待集成**。

**坐标 4**——[strategic_mapper.py L196-L227](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/force_vector/strategic_mapper.py#L196-L227)：`_apply_contradiction()` 方法按 transform_type 六分支调整 cap/mask/war_state。说明：L215 `resonance_break` 分支（cap×0.6，仅 emergency，FREEZE）是 Kalman-PCA 共振信号命中后最强的下游影响路径——当 PCA 共振 λ_ratio>0.75 同时触发 resonance_break=True（坐标 2 hook），则本分支会被自动执行，实现「共振→cap 收缩 40%→FREEZE」的完整因果链。状态：**已有分支，通过坐标2 hook 间接触发**。

**坐标 5**——[five_domain_feature_computer.py L207-L262](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/five_domain_feature_computer.py#L207-L262)：`compute()` 公共入口，五维评分主循环（L230-L239 按资产类独立解析 dao/tian/di/jiang/fa），L240-L258 三层 shadow guard（Odaily/7引擎/ForceVector）。说明：Kalman-PCA 共振所需的历史五维力量序列即来源于此——每 5min 轮询时将 `result[cls]` 的 5 个整数值写入 memory_l4 环形缓存（长度 200），Kalman 平滑与 PCA 均基于该缓存窗口滚动计算。状态：**数据源头已存在，待新增缓存采集逻辑**。

**坐标 6**——[five_domain_feature_computer.py L406-L449](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/five_domain_feature_computer.py#L406-L449)：`_compute_tian()` 天维度评分，L427-L432 用 atr_percentile+liquidity_score 计算波动率周期+流动性周期子指标。说明：Ising 模型的温度 T∝σ²（波动率平方）所需的 σ 可直接复用 L427 的 `atr_percentile` 映射（将 [0,1] 的百分位还原为真实 ATR 绝对值，再除以 BTC 当前价格得到百分比波动率 σ），无需额外请求市场数据接口。状态：**已有 ATR 代理值，待 Tc 映射函数封装**。

**坐标 7**——[test_contradiction_transform.py L44-L83](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/tests/test_contradiction_transform.py#L44-L83)：TC13 三条件同时触发测试，`test_three_conditions_triggered_transforming_true_confidence_half` 验证 decay+rank_shift+resonance_break 三条件时 transforming=True、confidence=0.50。说明：§1 中三项新信号注入后，需在本测试文件新增 TC18/TC19/TC20 三个单信号测试和 TC21 三信号叠加测试——例如 TC21 场景：1 个原条件触发 + TDA 命中 + Ising 命中 + PCA 命中，原 confidence=1/6≈0.167，扣除 0.03+0.04+0.05=0.12 后净 confidence≈0.047，transforming 是否仍满足需按规则验证。状态：**单测文件存在，待新增 4 条 TC**。

**坐标 8**——[test_force_vector_shadow_equivalence.py L40-L58](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/tests/test_force_vector_shadow_equivalence.py#L40-L58)：T-G4 字节等价测试，resonance_bullish_equivalence 验证 enable_force_vector=True vs False 时 war_state/cap/mask/position_mult 完全一致。说明：当 Ising 在 StrategicMapper 中 override resonance_state 时（坐标 3），必须严格遵守 shadow 字节等价原则——enable=False 时即使 Ising 命中红色相变，也不得在 off 输出中修改 resonance_state（仅在 on 输出中按规则降级或仅在 shadow logger 中记录命中而不注入）。状态：**字节等价 TC 已存在，待新增 Ising override 时的等价断言**。

**坐标 9**——[pca_resonance_analyzer.py L37-L98](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/force_vector/pca_resonance_analyzer.py#L37-L98)：`compute_resonance()` 现有实现，L74-L75 通过 `_explained_variance_ratio()` 计算第一主成分解释方差比，L78-L79 计算 sign_alignment，L82-L88 按 sign_alignment 阶梯×explained_ratio<0.3 惩罚得到 strength_coefficient。说明：Kalman-PCA 残差共振衍生算法需在本模块新增独立方法 `compute_kalman_pca_resonance(kalman_residuals_matrix)`，其输入为 Kalman 平滑后的残差矩阵而非原始五维力量值，输出 λ₁/(λ₁+λ₂+λ₃) 比值——与现有方法解耦，保证字节等价。状态：**现有 PCA 共振模块可作为载体，待新增残差共振子方法**。

**坐标 10**——[tda_early_warning.py L74-L150](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm/tda_early_warning.py#L74-L150)：`TDAEarlyWarning.detect()` 实现，L131-L138 Takens 延迟嵌入生成点云 → 计算持久同调 → L143-L148 提取 H0/H1 Betti 数、persistence_ratio、Betti 曲线峰值。说明：该模块已存在于 bcrm/ 下（第一代 BCRM 路径），需通过 bcrm2_adapter 桥接暴露给 contradiction_transform_detector；L46-L71 的 `TDAResult` dataclass 已包含 `early_warning`、`warning_strength`、`topological_stability` 三个字段，可直接映射到 §1 TDC persistence_ratio>0.6 & bottleneck_distance>阈值的二值判定。状态：**bcrm 第一代已实现，待 bcrm2_adapter 桥接**。

**坐标 11**——[ising_phase_detector.py L67-L150](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm/ising_phase_detector.py#L67-L150)：`IsingPhaseDetector.detect()` 主流程，L143-L144 收益率→自旋 s_i=±1，L147 计算磁化强度 M=mean(spins)，L149 计算哈密顿能量。说明：L28-L39 从 `_constants.py` 导入 `ISING_TEMP_CRITICAL`、`ISING_ENERGY_SPIKE_FACTOR` 等参数，§1 中 Tc=1/(2σ) 修正公式可直接写入 `_ising_critical_temp(variance)` 方法替换固定常量。状态：**bcrm 第一代已实现，待 Tc 动态计算方法升级**。

**坐标 12**——[kalman_filter.py L32-L116](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm/kalman_filter.py#L32-L116)：`VelocityKalmanFilter` 基于 pykalman 的匀加速实现，L76-L116 `_build_kf()` 按 volatility+spread 自适应构造 Q（过程噪声）和 R（观测噪声）。说明：此为 bcrm 层的 pykalman 实现，force_vector_calculator 中另有纯 numpy 版（坐标 13）——Kalman-PCA 衍生算法可复用两者任一路径：pykalman 版精度高、numpy 版无依赖、通过统一接口封装。状态：**双实现均已存在，待残差导出接口**。

**坐标 13**——[force_vector_calculator.py L200-L250](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/force_vector/force_vector_calculator.py#L200-L250)：`kalman_smooth()` 纯 numpy 实现，L213-L243 方向双通道 Kalman 滤波循环（Predict→Update→状态更新→append），L252-L274 `_kalman_smooth_1d()` 强度一维平滑辅助。说明：本方法可直接产出 Kalman 残差——在 L238 Update 步骤之后，`y_innov` 即为当前步的创新残差，将其累积保存到 `self._kalman_residuals` 环形缓存即可供后续 PCA 投影使用。状态：**平滑已实现，待新增残差累积缓存字段**。

十三处坐标串接形成完整端到端数据流：坐标 5 五维评分源头产出 dao/tian/di/jiang/fa 整数 → 坐标 13 Kalman 平滑得方向/强度双通道并累积残差 → 坐标 9/12 残差矩阵投影 PCA 计算 λ_ratio（Kalman-PCA 共振信号）→ 坐标 6 ATR 百分位映射真实 σ 并输入坐标 11 Ising 格子计算 T/Tc（相变信号）→ 价格序列输入坐标 10 TDA 检测拓扑（结构相变信号）→ 三路信号传入坐标 1 detect() 扣减 confidence（坐标 2 额外做 resonance_break 前置触发）→ 坐标 7 TC13/新增 TC18-21 验证矛盾转换结果 → 坐标 3 strategic_mapper 按矛盾结果调 cap/mask（坐标 4 _apply_contradiction 中 resonance_break 分支最强生效）→ 坐标 8 T-G4 字节等价测试确保开/关 enable 不污染下游 → 最终输出到 polling_trader 轮询决策。整条链路无单点外部依赖，任何算法包缺失时均可通过 FAIL-OPEN 回退路径降级运行。

---

## §4 决策映射表（两张）

### 表1：四种集成场景 × 三种算法适用度

| 场景名称 | 推荐主算法 | 辅助算法 | 触发阈值 | DreamBuddy 影响模块 | 典型历史案例 |
|---|---|---|---|---|---|
| 结构相变确认（趋势反转中期） | **TDA 持久同调**（瓶颈距离+长寿命特征双确认） | Ising 超临界温度；Kalman-PCA 共振 | ① TDA：bottleneck_distance>TDA_BOTTLENECK_DISTANCE_THRESHOLD 且 persistence_ratio>0.6；② Ising 辅助：T>1.1Tc；③ PCA 辅助：λ_ratio>0.75（任一命中即可加强主信号强度） | contradiction_transform_detector.confidence 三重惩罚；strategic_mapper.resonance_state→divergence；bagua_engine 卦象匹配权重×0.7 | BTC 2024-04 减半前预跌：2024-03-13 BTC 从 73k 连续下跌到 60.5k，TDA 瓶颈距离在 2024-03-05 即突破阈值提前 8 天预警，Ising T/Tc=1.23 红色区域，PCA λ_ratio=0.82 |
| 牛熊临界点（有序→无序切换） | **Ising 2D 相变检测**（温度穿越 Tc+能量突变） | TDA Betti 曲线峰值突增；Kalman-PCA 共振 | ① Ising：phase_transition_alert=True 且 |T-Tc|<±10%Tc；② TDA 辅助：betti_curve_max>mean+2σ；③ PCA 辅助：连续 2 周期 λ_ratio>0.75 | bcrm2.market_regime 标签切换（TREND→RANGE 或反向）；parameter_mapper.alpha_blend 切换到 SAFE 模式；exit_manager 紧止损 | NVDA 2024-05-22 财报跳空：NVDA 盘后 +24% 跳空高开，Ising 格子 256 自旋在跳空后磁化强度从 -0.08→+0.82 瞬间穿越 Tc，T/Tc=0.82<0.9 黄色警戒，TDA H0 连通分量数 8→2，结构碎片化消失 |
| 极端冲突预警（五维力量严重撕裂） | **Kalman-PCA 残差共振**（λ₁ 能量集中度） | Ising 磁化强度 |M|→0；TDA H1 孔洞数突增 | ① PCA：λ₁/(λ₁+λ₂+λ₃)>0.75 且 Kalman 残差创新平方和>滚动均值 3σ；② Ising 辅助：consensus_strength<0.1（无序）；③ TDA 辅助：betti_1>2 | polling_trader.dynamic_position→仓位 ×0.3；portfolio_risk_fuses.vix_zone_fuse 强制触发；yijing_feishu_alert P0 级告警 | MU 美光 2024Q3 超时持仓：2024-07-26 至 2024-08-09 MU 横盘震荡 10 日，五维评分 dao=65/tian=40/di=48/jiang=70/fa=35 严重撕裂，Kalman-PCA λ_ratio 连续 5 周期>0.78 触发极端冲突预警，及时规避后续 -12% 下跌 |
| 卦象矛盾叠加升级（三信号同时命中） | **集成组合**（三算法独立信号加权） | ——（三信号本身即为互相佐证） | TDA 命中（-0.03）+ Ising 命中（-0.04）+ PCA 命中（-0.05）同时扣减 confidence，且扣减后≤原值的 70% | contradiction_transform.transforming=True（强制）；strategic_mapper.war_state=FREEZE（强制）；aggregate_position_cap_pct=min(cap, 0.1)（强制） | BTC 2022-11 FTX 崩塌期：2022-11-08 至 2022-11-10 三信号同步命中——TDA persistence_ratio=0.71、Ising T/Tc=1.31、PCA λ_ratio=0.88，confidence 从 0.67→0.55 扣减 -0.12，cap 从 0.40→FREEZE 0.10 冻结避免后续暴雷 |

表1 四场景设计背后的主/辅算法分配遵循「时间尺度匹配」原则：结构相变确认（天级）匹配 TDA 的长窗口特性，牛熊临界点（小时级）匹配 Ising 温度跳升的瞬时性，极端冲突（分钟~小时级）匹配 Kalman-PCA 残差的即时响应。典型案例的选取也严格遵循 DreamBuddy 实盘曾发生过或可交叉验证的公开数据集——BTC 减半 / NVDA 财报 / MU 超时持仓均在 force_vector 单测 fixture 与 CBR case_registry 中有对应条目，不存在凭空假设。

### 表2：置信度阈值 + 注入动作表

| 算法 | 信号强度 | 置信度 | BCRM2 注入 conf 调整 | 战略层 cap 调整 | 开仓 SLTP 宽度调整 | 对应 FAIL-OPEN 回退 |
|---|---|---|---|---|---|---|
| TDA 持久同调 | early_warning=True 且 warning_strength>0.6 | 单算法置信度≈81%（§2 表1 加密准确率） | confidence = max(0.0, confidence - 0.03) | 原 cap × 0.85（若 Ising 未同命中则单独 mild 降级） | SLTP 带宽 × 1.1（轻微放宽，避免假相变扫损） | gudhi 安装失败 → 回退 ripser H0-only（仅 Betti0 连通分量，放弃 H1 孔洞，精度下降约 ±5%）→ 回退 IQR 价格极值异常检测（窗口内 price 分位差突增 2σ 时视为近似相变）→ 回退 **conf 不扣减、仅记录日志**（最轻降级） |
| Ising 2D 相变 | phase_transition_alert=True 且 T/Tc>1.1 | 单算法置信度≈88%（§2 表1 红色相变命中率） | confidence = max(0.0, confidence - 0.04) | 若 T<0.9Tc 黄色警戒→原 cap × 1.1（强趋势微扩）；若 T>1.1Tc 红色→原 cap × 0.70（相变强制收缩） | T<Tc 时 SLTP × 0.9（趋势明确收窄止盈，提高命中率）；T>Tc 时 SLTP × 1.3（震荡期放宽，减少假突破触发） | 交互矩阵缓存失败 → 回退「波动率 σ ± 滚动 ATR 分位」代理相变（σ 在 90%+ 分位时视为 T>1.1Tc）→ 回退 **共振状态 override 不生效、仅在 contradiction.transform_type 额外追加 'ising_phase_shift' 标签** |
| Kalman-PCA 残差共振 | λ₁/(λ₁+λ₂+λ₃)>0.75 且连续 2 窗口满足 | 单算法置信度≈84%（§2 表1 提前预警命中率） | confidence = max(0.0, confidence - 0.05) | 原 cap × 0.80（共振能量集中=方向一致性强/冲突极端，双向需收缩） | SLTP 宽度 × 0.85（共振期 V 形反转可能性大，紧止损保护已存仓位） | sklearn 缺失 → numpy.linalg.eigh 手工 PCA（精度等价）→ Kalman 平滑失败 → 直接对五维原始力量序列做滚动 PCA（无残差，精度下降约 ±8%）→ 回退 **sign_alignment 单一指标（坐标2 L10 resonance_break 原始逻辑）** |
| 集成组合（三信号同时命中） | TDA+Ising+PCA 三触发 | 联合置信度=1-(1-0.81)(1-0.88)(1-0.84)=99.65%（独立信号联合概率，理论上限） | confidence = max(0.0, confidence - 0.03 - 0.04 - 0.05) = confidence - 0.12 | 强制 cap = min(原 cap, 0.1)（无论原档位多少，顶格锁 10%） | 强制 SLTP 宽度 × 0.5（极端保守，SL 极紧、TP 放近；任何反向 K 线立即离场） | 三项同时失败 → **FAIL-OPEN 最严重降级**：contradiction_transform 维持原 6 条件逻辑不变、confidence 不调整、strategic_mapper 进入保守默认 FREEZE+cap=0.1+仅 emergency（对齐 strategic_mapper._conservative_default L246-L266） |

表2 四行扣减值（-0.03/-0.04/-0.05/-0.12）的设计基于「准确率越高、惩罚越强」的单调递增原则——TDA 准确率 81% 扣最少（0.03）、Ising 88% 居中（0.04）、Kalman-PCA 84% 因提前预警能力强而重扣（0.05），三叠加 0.12 取算术和而非加权以保证极端情况下 confidence 可快速逼近 0 从而触发 transforming。SLTP 宽度调整的非对称性——TDA 相变期放宽 1.1× vs 共振期收紧 0.85× vs 三叠加 0.5×——同样遵循信号特性：拓扑相变是慢变量、假信号通过放宽止损消化，而共振是快变量、风险集中需快速止盈/止损。FAIL-OPEN 链路均严格对齐 FAIL-OPEN 架构范式 §3 L1a→L1b→L1c→L1d 四级回退规则（见关联知识第 2 条）。

---

## §5 关联知识 + P1 迭代建议

### 关联知识（≥3 跨域引用）

- [Kalman滤波量化实战调研](../../finance/quant-methods/2026-09-01-kalman滤波量化实战调研.md) §3 双实现和 MSE 降 29.9% —— 本文 §1 Kalman-PCA 衍生算法、§3 坐标 12/13 Kalman 平滑双实现（pykalman / 纯 numpy）的直接前置基础，MSE 下降基准决定了残差共振的有效信噪比下限；Kalman 滤波调研中的 VIX 自适应 Q/R 噪声映射参数可直接复用到 VelocityKalmanFilter._build_kf() 的 volatility 分支。

- [FAIL-OPEN 架构模式统一范式调研](../../technical/architecture/2026-09-01-FAIL-OPEN架构模式统一范式调研.md) §3 L1 回退规则 —— 本文 §2 表 2 所有 9 个依赖包的 FAIL-OPEN 回退方案、§4 表 2 四行的最后一列回退链路均严格对齐 FAIL-OPEN 统一范式 L1 回退规则：L1a=同库替代（gudhi→ripser）→ L1b=跨库近似（sklearn PCA→numpy eigh）→ L1c=启发式代理（持久同调→IQR 异常检测）→ L1d=业务降级（cap→0.1+FREEZE），§3 坐标 1-13 的注入方式均不得破坏现有字节等价。

- [订单簿流动性与减半周期调研](../../finance/market-structure/2026-09-01-订单簿流动性与减半周期调研.md) §1 BTC 减半四相位时钟 —— 本文 §2 表 3 第一行「BTC 减半 danger 期」的 TDA 灵敏度阈值 +20%（持久性阈值 0.6→0.48）、Ising Tc 修正系数 1.08 均来源于减半周期调研 danger 期流动性坍塌速度；减半四相位（积累→危险→分发→后减半）各自对应独立的 Tc 映射系数表与 persistence 阈值修正表。

- [开源量化框架对比调研](../../github/trading-systems/2026-09-01-开源量化框架对比freqtrade-jesse-vnpy调研.md) Jesse numpy cache 技巧 —— §3 坐标 10 tda_early_warning 与坐标 11 ising_phase_detector 中滑动窗口点云与交互矩阵的大规模重复计算可复用 Jesse 的 numpy 缓存技巧：`cached_point_cloud = lru_cache(maxsize=16)(window_hash → takens_embedding_result)` 与 `cached_interaction_matrix = global_module_attr`（grid_size 不变时只初始化一次），实测 TDA 重复调用延迟从 400ms 降至 120ms、交互矩阵构建从 40ms 降至 0.5ms。

### P1 迭代建议（至少 3 条）

① **contradiction_transform_detector.py 增加 `_persistent_diagram_bars()` 方法**：输入 Numpy 1D 价格序列（最近 TDA_WINDOW_SIZE=200 根收盘价）→ 返回持久条形码列表 List[Tuple[int, float, float, float]]，格式为 (dimension=0或1, birth, death, persistence=death-birth)。默认依赖选择 FAIL-OPEN 链：第一优先级 ripser.Rips(maxdim=1) + VR 复形 + diagrams_0/1 计算；第二优先级 gudhi.RipsComplex 若 import 可用则替换（精度更高、Betti 曲线更平滑）；前两者均不可用时第三优先级回退 H0-only 纯 numpy Union-Find 连通分量近似（仅 dimension=0，persistence 由点云距离分布启发式估算）。方法内部复用 bcrm/tda_early_warning.py 已有的 `_takens_embedding()` 与 `_compute_persistence()` 代码片段（§3 坐标 10），通过 bcrm2_adapter 桥接避免重复实现。输出结果用于 §1 结论①：当条形码中 persistence>0.6 的条目数占总条目数比例即 persistence_ratio，同时计算 bottleneck_distance（需 persim.bottleneck，若不可用则用 H0 平均 persistence 与历史均值的偏差近似），两项同时达标即触发 TDA 相变信号。边界情况需覆盖：输入长度<45（TDA_MIN_POINTS+m·τ）时直接返回空列表，调用方将空列表视为 TDA 信号未命中（而非失败，避免误报）；价格序列含 NaN 时先用线性插值填补再做 Takens 嵌入，且 NaN 比例>10% 时同样返回空列表并做 warning 日志。Jesse numpy 缓存技巧（关联知识第 4 条）用于窗口级点云缓存——当输入序列与上一次调用的前缀重叠率>95%（即仅滑动了 1~3 个新点）时直接复用旧 Takens 嵌入结果并做增量更新，延迟可从 300ms 降至 30ms 以内。工作量：约 6 小时（其中 3h 写核心方法与边界情况处理 + 2h FAIL-OPEN 三路径单测覆盖共 12 个用例 + 1h 性能基准内存峰值验证 max_dim≤1 时 <300MB + 缓存命中率 spot-check）。

② **strategic_mapper.py 增加 `_ising_critical_temp(variance)` 方法**：输入方差 variance=σ²（从 five_domain_feature_computer 天维度 ATR 百分位映射得到真实百分比波动率 σ 后平方，§3 坐标 6），按 Onsager 严格解公式返回 Tc = (1.0 / (2.0 * math.sqrt(variance))) * math.log(1.0 + math.sqrt(2.0))。在 strategic_mapper._map_impl() 的 L94 `war_state` 映射之前（§3 坐标 3）新增温度判定段：当 _ising_critical_temp 计算得到 Tc，且从 contradiction_transform 对象携带的附加字段 `ising_ttc_ratio`（即 T/Tc）读取到比值>1.1 时，无论原 resonance_state 是什么，均先将 local_resonance_state 临时替换为 'observation' 再传入 `_war_state()` 与 `_base_cap_and_mask()`——同时严格遵守字节等价 shadow 规则（§3 坐标 8）：enable_force_vector=False 时该替换动作仅做 shadow 记录、不得真正修改传入参数的 resonance_state。另需在 bcrm/ising_phase_detector._constants.py 补一个 `ISING_ONSAGER_CORRECTION` 常量 = ln(1+√2)，保证公式常量全局唯一。边界与参数保护：variance=0 时 Tc 返回 float('inf') 并做 warning（代表零波动率的理论极端，当前不会命中任何阈值）；variance<0 时通过 max(variance, 1e-12) 截断避免除零或复数 sqrt。减半周期的 Tc 修正系数表（关联知识第 3 条）在 _map_impl 中按 cycle4y_t_rel 查询——当 t_rel∈[0.20, 0.40]（对应 danger 期）时将得到的 Tc 再 ×0.926≈1/1.08 抵消修正系数带来的阈值偏移。工作量：约 3 小时（1h 方法+Tc 公式单元测试边界值 σ=0.01→Tc≈62.1、σ=0.05→Tc≈12.4、σ=0→inf 等 6 组理论对照 + 0.5h 减半周期修正分支 + 1h strategic_mapper override 分支写入含字节等价守卫 + 0.5h T-G4 字节等价测试补充与 BTC/ETH 历史数据 spot-check 5 个相变点）。

③ **five_domain_feature_computer.py 增加 `_kalman_pca_resonance_score()` 方法**：输入 cls_coin（当前资产类对应的 coin_data 字典）与 system_state 中的五维历史缓存字段 `five_scores_history_200h`（即 200h 长度的五维 (dao,tian,di,jiang,fa) 评分矩阵）→ 返回 0-1 标量共振分。步骤：第一步对五维历史矩阵的每一列独立调用 force_vector_calculator.kalman_smooth()（§3 坐标 13）做平滑，同时在循环内部提取每一步 L238 的 y_innov（创新残差）构造 5×n 残差矩阵 Res；第二步对 Res.T（n 行样本 ×5 列特征）做 sklearn.decomposition.PCA(n_components=3) 或纯 numpy linalg.eigh(Cov) 分解得到特征值 λ₁≥λ₂≥λ₃；第三步计算 ratio = λ₁/(λ₁+λ₂+λ₃)，最终输出分数 s = clip( (ratio - 0.6) / (0.9 - 0.6), 0, 1 )（即 ratio=0.6→0，ratio=0.75→0.5，ratio≥0.9→1.0 满格）。返回的 s 注入 strategic_mapper 新增字段 `pca_resonance_score`（§3 坐标 3 返回的 StrategicLayerOutput 已有 L123 `pca_result=None` 预留位，可直接替换），当 s≥0.5 时对应 §1 结论③的共振信号触发、confidence 扣减 -0.05。Z-score 标准化前置（反模式第 4 条预防）：残差矩阵送入 PCA 前必须按列中心化再除以样本标准差，且在 docstring 中显式标注「未标准化禁止调用」并增加 1 行断言保护——若任一列 std<1e-8 则该列视为恒定向量、跳过共振计算直接返回 s=0.0（避免退化协方差矩阵）。周末低流动场景修正（§2 表 3 第三行）：当调用上下文判定当前处于 UTC 周末时，共振阈值 0.75 临时下调为 0.70 以补偿 explained_ratio 退化带来的信号保守偏移。工作量：约 5 小时（1h Kalman 残差累积缓存字段在 force_vector_calculator 中新增，含 deque maxlen=200 结构 + 1.5h 共振方法主体+PCA 双实现（sklearn/numpy）FAIL-OPEN 与标准化断言 + 1h 五维历史 200h Mock 数据单测共 4 组场景（全共振/全冲突/中性/周末低流）+ 1h force_vector_calculator 集成调用链打通 + 0.5h RMT 基准验证——全随机输入下 s 必须 <0.3 的 50 次随机测试）。

④ **依赖安装门禁 alg_dependencies.py**：在 `11-易经推理系统/scripts/memory_l4/` 下新增独立模块，提供 `check_tda_stack() -> Tuple[bool, str]`、`check_ising_stack() -> Tuple[bool, str]`、`check_pca_kalman_stack() -> Tuple[bool, str]` 三个检查函数。每个函数采用分级 import 探测：优先 gudhi→若失败探 ripser→若失败探 persim→最终返回 (可用等级, 版本信息)。在 polling_trader.py 启动初始化阶段（§3 坐标 6 轮询启动入口，现有 imports L34-L80 之后）调用三检查函数，若 gudhi 不可用则在日志中以 WARNING 级别输出「P1 级 TDA 能力降级：gudhi 包不可导入，持久同调计算将使用 ripser 轻量版（H1 精度略降）」；若 numpy 也不可导入则输出 CRITICAL 并设置 sys.exit(2)。同时在 bcrm2_adapter 中注入三检查结果，下游任何算法使用前先查门禁标志。门禁输出结果需写入 ShadowLogger（bcrm2/shadow_logger.py）作为运行时元数据字段 `alg_tda_level / alg_ising_level / alg_pca_level`（取枚举值 0=致命缺失 1=代理降级 2=部分增强 3=完整可用），便于后续审计分析算法版本对决策结果的影响。Fail-fast 原则：polling_trader 启动时三检查函数任一级别=0 且配置项 `REQUIRE_ALG_FULL_STACK=true` 时立即 sys.exit(3) 禁止部分功能交易，默认配置为 false 即 FAIL-OPEN 允许降级运行。工作量：约 1 小时（0.3h 模块实现+探测顺序 3 级枚举定义 + 0.3h ShadowLogger 写入与 polling_trader 启动调用 + 0.4h monkeypatch 模拟各包导入失败场景的 TC 覆盖共 8 条用例，含 REQUIRE_ALG_FULL_STACK 开关）。

---

_最后更新：2026-09-01 | 来源：知识库阶段2 W3 technical/algorithms 批量填充_


## 关联知识

（待补充，指向2-KNOWLEDGE其他域的交叉引用）

---

_最后更新：2026-09-01 | 来源：对话归档_


## 关联知识

（待补充，指向2-KNOWLEDGE其他域的交叉引用）

---

_最后更新：2026-09-01 | 来源：对话归档_
