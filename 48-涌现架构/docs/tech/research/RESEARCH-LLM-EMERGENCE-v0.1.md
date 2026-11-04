# RESEARCH-LLM-EMERGENCE v0.1

**主题**：LLM（GPT 系列 / Claude 等）"智能涌现"研究与工程做法调研
**目的**：为自进化交易系统（认知记忆贝叶斯升级 + 跨域耦合神经网络 + 做梦器策略寻优 + 辩论对抗 + CBR 案例库）评估"智能涌现"提供 LLM 领域的理论与工程参照系
**日期**：2026-11-05
**状态**：v0.1 初稿，关键论点均标注来源；争议处已诚实标注

---

## 1 大辩论与共识

### 1.1 Wei et al. 2022：涌现能力"存在论"

Wei 等人在 *Emergent Abilities of Large Language Models*（TMLR 2022，arXiv:2206.07682）中给出经典定义：涌现能力是"在小模型上不存在、但在大模型上出现的能力"，其特征是无法通过对小规模模型的性能外推来预测。在 scaling 曲线上表现为：性能在达到某个临界规模（critical threshold）前接近随机，之后突然跃升——即"相变"（phase transition）模式。论文整理了 BIG-Bench 等基准上大量此类曲线，涵盖多步算术、词形变换、多任务语言理解等任务。来源：[arXiv:2206.07682](https://arxiv.org/pdf/2206.07682v1)、[OpenReview](https://openreview.net/pdf?id=yzkSU5zdwD)。

同期 Wei 等人的思维链（Chain-of-Thought, CoT）论文（arXiv:2201.11903）发现：CoT 提示本身就是涌现能力——在约 100B 参数（约 10^23 训练 FLOPs）以下，CoT 不仅无增益，小模型还会生成"流畅但不合逻辑"的推理链，反而比直接回答更差。来源：[arXiv:2201.11903](https://arxiv.org/html/2201.11903v3)、[Stanford HAI](https://hai.stanford.edu/news/examining-emergent-abilities-large-language-models)。

### 1.2 Schaeffer et al. 2023：涌现能力"海市蜃楼论"

Schaeffer、Miranda、Koyejo 在 NeurIPS 2023 获奖论文 *Are Emergent Abilities of Large Language Models a Mirage?* 中提出替代解释：涌现表象源于研究者选择的度量，而非模型行为随规模发生根本变化。核心论证是：非线性/不连续度量（如 exact match、多选题答对才计分）会把底层平滑增长的"每 token 正确概率"放大成跳变；换成线性/连续度量（如 token 级 log 概率、编辑距离）后，同一任务呈现平滑、可预测的增长。他们在 29 个度量上检验，25 个不呈现涌现。来源：[NeurIPS 2023 论文](https://papers.neurips.cc/paper_files/paper/2023/file/adc98a266f45005c403b8311ca7e8bd7-Paper-Conference.pdf)、[Stanford HAI 报道](https://hai.stanford.edu/news/ais-ostensible-emergent-abilities-are-mirage)、[Stanford LDR 讲义](https://ldr.stanford.edu/assets/reform/05_03_2026_Emergent_abilities_2.pdf)。

### 1.3 后续共识（截至 2026 年的主流立场）

- **"度量敏感"是共识，"全部是假象"不是共识。** 多数综述认为 Schaeffer 的解释覆盖了大量原初案例（算术、音译、组词），但仍有残余能力（in-context learning、CoT、指令遵循）在换用连续度量后依然呈现随规模的质变特征。来源：[memx.app 综述](https://memx.app/glossary/emergent-capabilities/)、[IoT Digital Twin 2026 综述](https://iotdigitaltwinplm.com/emergent-abilities-llm-scale-explained-2026/)。
- **从 loss 视角看，涌现可以是"平滑损失下的宏观相变"。** NeurIPS 2024 论文 *Understanding Emergent Abilities from the Loss Perspective* 指出：即使预训练损失连续下降，下游任务表现仍可能出现宏观上的涌现点，两者并不矛盾。来源：[papers.neurips.cc](https://papers.nips.cc/paper_files/paper/2024/file/5f1eee2509599faeeb3570a887016a64-Paper-Conference.pdf)。
- **训练数据污染是重大混淆变量。** Tübingen 团队（arXiv:2407.07890）证明"在测试任务上训练"会伪造涌现曲线：模型家族间的涌现差异很大程度可由数据构成差异解释。来源：[arXiv:2407.07890](https://arxiv.org/html/2407.07890v1)。

**对本调研最重要的中间结论**："涌现"不是一个可以直接观察的属性，而是"度量 × 任务 × 规模"三元组的函数。任何涌现声明都必须附带：用了什么度量、该度量对底层连续量是否非线性、测试分布是否与训练分布隔离。

---

## 2 机制解释

### 2.1 Induction head 与 in-context learning 的相变

Anthropic 的可解释性研究（Olsson et al., *In-context Learning and Induction Heads*, arXiv:2209.11895）是目前对"涌现"最具体的机制性证据。Induction head 是实现 `[A][B]…[A] → [B]` 模式补全的注意力头（前辍匹配 + 复制）。关键发现：

- 在训练过程中存在一个**明确的相变窗口**：induction head 在此窗口内快速形成，同时模型的 in-context learning 能力（loss 随 token 位置下降的幅度）同步骤升，两者高度共变。
- 这是一个**训练时间轴上**的相变（不是模型规模轴），说明"涌现"可以是内部回路组装完成的标志，而非神秘质变。

来源：[arXiv:2209.11895](https://arxiv.org/pdf/2209.11895.pdf)、[transformer-circuits.pub](https://www.transformer-circuits.pub/feed.xml)。

### 2.2 Features、Circuits 与 Superposition（超位置假设）

Anthropic 后续的机制可解释性工作给出"能力何以存在"的微观图景：

- **Superposition 假设**：模型的神经元数量少于需要表示的概念数，因此把多个特征叠加（superpose）在同一组神经元上，以几乎正交的方向编码。这解释了为什么能力是"潜在"的——特征早已在表征空间中存在，只是缺乏被"读出"的回路。
- **Towards Monosemanticity（2023）**：用稀疏自编码器（sparse autoencoder）把 512 个神经元分解为 4000+ 单义特征（DNA 序列、法律文本等），证明叠加可以被解析。来源：[aiwiki.ai](https://www.aiwiki.ai/wiki/towards_monosemanticity)。
- **Scaling Monosemanticity（2024）**：把字典学习扩展到 Claude 3 Sonnet，提取出数百万高度抽象、多语言、多模态的特征，且可用于"steering"（定向激活以控制行为）。这证明大模型内部存在系统化的概念几何结构。来源：[Tom Henighan / Anthropic](https://tomhenighan.com/)。

**含义**：所谓"能力涌现"很可能是——表征（features）随预训练平滑积累，而"读出回路"（circuits，如 induction head）在某个临界点组装完成，使已有表征突然可被任务调用。这与"度量假象"论互补：度量决定你能否看见它，回路决定它是否真能用。

### 2.3 Grokking：时间轴上的顿悟

OpenAI 的 *Grokking: Generalization beyond overfitting on small algorithmic datasets*（Power et al., 2022）发现：小型 Transformer 在算法任务上先长时间死记硬背（训练准确率 100%、测试准确率随机），经过远超拟合所需的训练后**突然**泛化。机制研究表明这与权重范数下降（从"蛮力查表"解切换到"结构化"解）相关；无正则化则永远停留在记忆模式。来源：[集智百科](https://hub.baai.ac.cn/view/52163)、[量子位报道](http://m.toutiao.com/group/7266354199431250473/)、[集智斑图](https://pattern.swarma.org/mobile/article/239)。

**启示**：涌现可能需要在"已饱和"之后继续运行很长时间才出现——评估窗口太短会漏报。

### 2.4 涌现与 Scaling Law 的关系

Wei 的定义明确把涌现定位为"无法从 scaling law 外推"的部分；Schaeffer 则证明换度量后大部分案例**可以**被平滑外推。当前较稳妥的表述是：预训练 loss 平滑下降（scaling law 管辖）；下游能力曲线是否出现跳变，取决于度量形状与任务是否要求"全部子能力同时到位"（如多步推理要求每步都对）。来源：[NeurIPS 2024 Loss Perspective](https://papers.nips.cc/paper_files/paper/2024/file/5f1eee2509599faeeb3570a887016a64-Paper-Conference.pdf)。

---

## 3 工程做法

### 3.1 "创造条件让能力涌现"的训练实践

LLM 工程的一个核心经验是：涌现很少是"等来的"，更多是"设计条件诱发 + 解锁"的。

- **指令微调 / RLHF（OpenAI 路线）**：预训练模型已有潜在能力，RLHF 通过人类偏好奖励模型把这些能力"对齐到可调用形式"。GPT-4 的能力展示很大程度是解锁（unlocking）而非新增。来源：[perform.digital 综述](https://perform.digital/blogs/rlhf-to-verifiable-rewards/)。
- **Constitutional AI / RLAIF（Anthropic 路线）**：用一组明文原则（constitution）替代人类标注：模型自评→改写→自排序生成偏好数据，再训奖励模型做 RL。意义在于把"价值/约束"变成可规模化的训练信号，减少对昂贵人类反馈的依赖。来源：[Anthropic: Teaching Claude why](https://www.anthropic.com/research/teaching-claude-why)、[arXiv:2402.01651 对比分析](https://arxiv.org/pdf/2402.01651)。
- **可验证奖励（verifiable rewards）**：2024-2026 年趋势是从偏好模型转向规则可验证的奖励（数学答案对错、代码测试通过），用 RL 直接强化推理链，诱发长链推理能力的"涌现"（o1/R1 类模型）。来源：[perform.digital](https://perform.digital/blogs/rlhf-to-verifiable-rewards/)。
- **Tool use 与多步推理脚手架**：工具调用、检索、代码执行把"单步生成"扩展为"多步闭环"，使模型能力在系统层面组合放大——系统级涌现往往来自架构（回路）而非权重。

### 3.2 多智能体系统的涌现观测与教训

2023 年"寒武纪大爆发"：CAMEL、AutoGen、MetaGPT、Generative Agents 等集中出现。来源：[paperguru.ai 综述](https://paperguru.ai/benchmark/pdfs/llm-based-multi-agent.pdf)。

- **CAMEL（NeurIPS 2023, arXiv:2303.17760）**：首个显式 role-playing 框架，用 inception prompting 让两个 agent 对话协作。关键教训：纯角色扮演对话、无工具/无执行的系统，涌现出的"协作智能"不足以完成多数真实任务。来源：[zoeyli.com 反思](https://zoeyli.com/blog/The-Myth-of-Multi-Agent-as-Role-Playing/)。
- **MetaGPT**：把 SOP（标准操作流程）直接编码进 agent prompt（产品经理→架构师→工程师瀑布流），用结构化交付物（PRD、API 设计）作为下游严格输入。其"涌现"实为**工程化约束的产物**：通过把自由聊天变成结构化流水线降低幻觉，而非自发秩序。来源：[techrxiv 综述](https://www.techrxiv.org/doi/pdf/10.36227/techrxiv.177092236.62657640/v1)、[arXiv:2601.12560](https://arxiv.org/html/2601.12560)。
- **普遍教训**（多来源汇总）：①多 agent 涌现的"群体智能"高度依赖单 agent 基座能力，弱基座 + 多 agent ≈ 噪声放大器；②通信协议和角色分工的工程价值大于"涌现"叙事；③缺少可验证奖励/外部反馈时，agent 间互相强化错误（echo chamber）。来源：[arXiv:2503.21460 综述](https://arxiv.org/pdf/2503.21460)、[zoeyli.com](https://zoeyli.com/blog/The-Myth-of-Multi-Agent-as-Role-Playing/)。

---

## 4 可迁移判据（重点）

LLM 领域判定"涌现发生了"的可用指标与判据，按可靠性排序：

| # | 判据 | 具体做法 | 判什么 | 主要陷阱 | 来源 |
|---|------|----------|--------|----------|------|
| 1 | **度量敏感性检验** | 同一组系统输出，至少用 1 个非连续度量（exact match）+ 1 个连续度量（token logprob / 部分分 / 编辑距离）各画一条 scaling 曲线 | 涌现是否只是度量伪影 | 只报非连续度量 → 海市蜃楼 | [Schaeffer 2023](https://papers.neurips.cc/paper_files/paper/2023/file/adc98a266f45005c403b8311ca7e8bd7-Paper-Conference.pdf) |
| 2 | **相变曲线（双轴）** | 在规模轴（参数/FLOPs/数据/迭代轮数）与训练时间轴分别扫描，拟合断点；induction-head 式相变在时间轴上也可观测 | 是否存在临界点及临界变量 | 扫描点太稀 → 伪相变；窗口太短 → 漏报 grokking | [Wei 2022](https://arxiv.org/pdf/2206.07682v1)、[Olsson 2022](https://arxiv.org/pdf/2209.11895.pdf)、[Grokking](https://hub.baai.ac.cn/view/52163) |
| 3 | **OOD 泛化** | 测试分布与训练分布显式隔离；用训练 cutoff 之后的新数据（LiveCodeBench 模式） | 能力是真实泛化还是记忆/污染 | 训练集污染伪造涌现 | [arXiv:2407.07890](https://arxiv.org/html/2407.07890v1)、[Goodeye Labs 2025 评测年报](https://www.goodeyelabs.com/insights/llm-evaluation-2025-review) |
| 4 | **组合泛化基准** | SCAN（holdout 原语 "jump"）/ COGS / gSCAN：训练见过组件，测试要求新组合 | 系统性/组合性是否涌现 | 标准 seq2seq 在 SCAN 上接近 0 分，LLM 也非稳过；需要专门切分设计 | [SCAN 原论文引用页](https://arxiv.org/pdf/1904.09708)、[gSCAN](https://arxiv.org/html/2202.10745v1)、[同态误差预测 OOD（R²=0.73）](https://arxiv.org/html/2601.18858v1) |
| 5 | **机制证据（回路/特征级）** | 能否定位"读出回路"（类比 induction head）或表征结构（类比 SAE features），并证明共变 | 涌现有无内部机制支撑 | 只做行为曲线不做机制 → 无法区分假象与真实 | [Anthropic circuits](https://www.transformer-circuits.pub/feed.xml)、[Scaling Monosemanticity](https://tomhenighan.com/) |
| 6 | **下游解锁测试** | 同一基座 + 不同"解锁"手段（prompt/finetune/RL），能力增益曲线是否陡变 | 能力是"已有未解锁"还是"新产生" | 把解锁当涌现会高估系统进化 | [CoT 论文](https://arxiv.org/html/2201.11903v3) |
| 7 | **能力剖面一致性** | 用 prompt 扰动 / 选项乱序 / 变体题测稳健性（如 MMLU 选项重排可掉 13%） | 能力是模式匹配还是稳健理解 | 高方差 = 脆性模式匹配，非真能力 | [EsoLang-Bench](https://arxiv.org/html/2603.09678v1) |

**使用建议**：任何涌现声明必须同时通过 #1（双度量）、#3（OOD 隔离）、#7（稳健性）三关，才有资格进入"机制解释"讨论（#5）。

---

## 5 反面教训

1. **大部分原初涌现案例被度量证伪。** Schaeffer 2023：29 个度量中 25 个无涌现；算术、音译、组词等"明星案例"在换连续度量后跳变消失。教训：**先怀疑度量，再欢呼涌现。** 来源：[NeurIPS 2023](https://papers.neurips.cc/paper_files/paper/2023/file/adc98a266f45005c403b8311ca7e8bd7-Paper-Conference.pdf)。
2. **数据污染伪造涌现。** arXiv:2407.07890 证明训练集中混入测试任务会系统性伪造涌现曲线，且污染模型家族间不可比。来源：[arXiv:2407.07890](https://arxiv.org/html/2407.07890v1)。
3. **"Sparks of AGI"（Bubeck et al. 2023, arXiv:2303.12712）争议**：宣称 GPT-4 呈现通用智能火花，被批评为未经同行评审、AGI 定义含糊、在私有预发布模型上做实验不可复现、作者有商业利益；后续系统复测发现其在基础逻辑/算术上有系统性错误、同类问题高方差，"火花"多为模式匹配伪影。教训：**涌现叙事要警惕利益相关方的过度宣称与不可复现实验。** 来源：[AI Wiki: Bubeck](https://aiwiki.ai/wiki/sebastien_bubeck)、[harderproblem.org 复测](https://harderproblem.org/news/sparks-of-agi-revisited.html)。
4. **古德哈特定律在涌现度量中的三种表现**：
   - **基准过拟合**：LiveCodeBench 通过持续采集训练 cutoff 之后的新题，暴露模型对旧题基准的大幅过拟合——模型优化的是奖励信号而非目标能力。来源：[Goodeye Labs](https://www.goodeyelabs.com/insights/llm-evaluation-2025-review)。
   - **表层模式利用**：MMLU 仅调换选项顺序即可掉 13% 准确率，说明"能力"部分是选项分布的模式匹配。来源：[EsoLang-Bench](https://arxiv.org/html/2603.09678v1)。
   - **答案键本身有噪声**：Gema et al. 重标注 5700 道 MMLU 题，发现 6.49% 整体错误率（病毒学子集 57% 有问题）——度量天花板低于宣称值。来源：[explainx.ai](https://explainx.ai/blog/goodharts-law-ai-benchmark-contamination-gsm1k-mmlu-arena-2026)。
5. **多 agent 角色扮演的"涌现幻觉"**：CAMEL 式纯对话协作在无工具/无验证时被证明不足以解决真实任务；结构化产出（MetaGPT 式 SOP）的收益来自工程约束而非自发智能。教训：**把脚手架的贡献误归因于涌现，是最常见的工程误判。** 来源：[zoeyli.com](https://zoeyli.com/blog/The-Myth-of-Multi-Agent-as-Role-Playing/)。

---

## 6 对本系统的启示

结合本系统结构（认知记忆贝叶斯升级 + 跨域耦合神经网络 + 做梦器策略寻优 + 辩论对抗 + CBR 案例库），逐条给出可借鉴点：

1. **建立"涌现度量双轨制"（借鉴 §4 判据 #1）。** 对系统任何"能力指标"（策略胜率、regime 识别准确率、辩论裁决质量），同时维护一个非连续度量（如"交易信号是否命中目标"的 0/1）和一个连续度量（如信号的预期收益 logprob、夏普的平滑估计）。只有两条曲线同向且连续曲线平滑上行时，非连续曲线上的跳变才可申报为"涌现"，否则按度量伪影处理。这直接对应 Schaeffer 的教训，且实现成本低——本质是改评测脚本不改系统。

2. **给"做梦器"设置 grokking 式长窗口评估（借鉴 §2.3）。** Grokking 的教训是：泛化可能在训练饱和后很久才出现，且依赖正则化（权重范数下降）。做梦器的策略寻优应：①允许在"样本内已饱和"的策略上继续探索足够长的轮次再判死刑；②监控策略复杂度（参数量/规则数/案例引用数）作为"权重范数"类比物——真正的策略泛化往往伴随复杂度先升后降，若复杂度只升不降，大概率是记忆行情而非领悟规律。

3. **把辩论对抗改造成"可验证奖励 + Constitution"双信号（借鉴 §3.1）。** Constitutional AI 的核心是把裁判标准写成明文原则并让 AI 自评自改。本系统的辩论对抗可借鉴：①把交易纪律（止损规则、仓位上限、禁止事项）写成明文"宪法"，辩论裁决显式引用条款；②奖励信号分两层——可验证层（策略实盘/回测 PnL、风控违规次数，硬奖励）+ 辩论层（论点质量偏好模型，软奖励），避免纯辩论软奖励导致的"辩得好≠做得对"古德哈特陷阱。

4. **为认知记忆设计"induction head 式相变检测"（借鉴 §2.1、§4 判据 #5）。** Anthropic 的经验是涌现要有机制证据。认知记忆的贝叶斯升级体系中，可以定义并监控一个"回路组装"类比量：例如"新写入记忆被后续决策实际召回并改变行动"的比率（记忆→行动的读出率），或 CBR 案例从"被检索"到"被复用且盈利"的转化曲线。若该曲线在某临界点后陡升且与系统整体收益共变，这是比"累计记忆数"可靠得多的涌现机制证据。反之，记忆只写不读 = 超位置中没有读出回路的死特征。

5. **CBR 案例库的组合泛化测试集（借鉴 §4 判据 #4 SCAN/COGS）。** 仿照 SCAN 的 holdout 原语设计：故意把某类市场原语（如某种 regime 形态、某类黑天鹅事件模式）从案例库训练集中整体扣留，测试系统能否用其他案例**组合**出对该新形态的正确响应。这是区分"案例检索复述"与"组合式策略智能"的金标准。同时引入"同态误差"思想：检查行情结构相似性是否与案例表征相似性一致（结构相似的行情应激活相似的案例/因子组合），可用作 CBR 表征质量的连续监控指标。

6. **多模块涌现归因：区分"脚手架贡献"与"自发秩序"（借鉴 §5.5）。** MetaGPT 的教训适用于本系统的跨域耦合：模块间结构化接口（domain_transmission、认知记忆契约）带来的提升是**工程贡献**，不应计为涌现。申报涌现前需做消融：固定接口与数据流，仅让模块自适应部分（贝叶斯参数、耦合权重、做梦器变异）自由进化，观察超额收益是否仍出现。涌现声明 = 总收益 − 脚手架贡献 − 数据红利。

7. **OOD 与防污染纪律（借鉴 §4 判据 #3、§5.2）。** LLM 评测的最大翻车点是训练/测试泄漏。本系统天然高风险：回测区间、案例库、辩论训练数据若与"涌现验证集"重叠，涌现必为伪。硬要求：涌现验证必须使用时间上完全后置的 walk-forward 区间，且该区间行情不得进入案例库与记忆升级流程（类比 LiveCodeBench 的 cutoff 纪律）。

8. **能力剖面稳健性压测（借鉴 §4 判据 #7）。** 类比 MMLU 选项乱序：对系统同一决策情境做扰动（行情微小噪声、案例顺序打乱、辩论发言顺序轮换），若决策输出高方差，则"能力"是脆性模式匹配。稳健性方差应作为涌现申报的否决项。

**一句话总结**：LLM 领域四年辩论的最终教训是——涌现极少是"等出来的奇迹"，而是"平滑积累 + 回路组装 + 度量诚实 + 解锁工程"四者齐备时才被合法观测到的现象；本系统若想在涌现上不重蹈 LLM 评测的覆辙，应先把判据（§4 表）建成评测基础设施，再谈涌现。

---

## 附录 来源清单

| 来源 | URL | 访问日期 |
|------|-----|----------|
| Wei et al., Emergent Abilities of Large Language Models (TMLR 2022) | https://arxiv.org/pdf/2206.07682v1 | 2026-11-05 |
| Wei et al., Emergent Abilities（OpenReview 版） | https://openreview.net/pdf?id=yzkSU5zdwD | 2026-11-05 |
| Wei et al., Chain-of-Thought Prompting (2022) | https://arxiv.org/html/2201.11903v3 | 2026-11-05 |
| Stanford HAI: Examining Emergent Abilities | https://hai.stanford.edu/news/examining-emergent-abilities-large-language-models | 2026-11-05 |
| Schaeffer et al., Are Emergent Abilities a Mirage? (NeurIPS 2023) | https://papers.neurips.cc/paper_files/paper/2023/file/adc98a266f45005c403b8311ca7e8bd7-Paper-Conference.pdf | 2026-11-05 |
| Stanford HAI: AI's Ostensible Emergent Abilities Are a Mirage | https://hai.stanford.edu/news/ais-ostensible-emergent-abilities-are-mirage | 2026-11-05 |
| Stanford LDR 讲义：Emergent Abilities | https://ldr.stanford.edu/assets/reform/05_03_2026_Emergent_abilities_2.pdf | 2026-11-05 |
| Understanding Emergent Abilities from the Loss Perspective (NeurIPS 2024) | https://papers.nips.cc/paper_files/paper/2024/file/5f1eee2509599faeeb3570a887016a64-Paper-Conference.pdf | 2026-11-05 |
| MemX 综述：Emergent Abilities in LLMs | https://memx.app/glossary/emergent-capabilities/ | 2026-11-05 |
| IoT Digital Twin: Emergent Abilities 2026 综述 | https://iotdigitaltwinplm.com/emergent-abilities-llm-scale-explained-2026/ | 2026-11-05 |
| Olsson et al., In-context Learning and Induction Heads (2022) | https://arxiv.org/pdf/2209.11895.pdf | 2026-11-05 |
| Anthropic Transformer Circuits Thread | https://www.transformer-circuits.pub/feed.xml | 2026-11-05 |
| Towards Monosemanticity 释义（AI Wiki） | https://www.aiwiki.ai/wiki/towards_monosemanticity | 2026-11-05 |
| Scaling Monosemanticity（Tom Henighan / Anthropic） | https://tomhenighan.com/ | 2026-11-05 |
| 可解释性综述 arXiv:2402.10688 | https://arxiv.org/pdf/2402.10688 | 2026-11-05 |
| Grokking（集智百科词条） | https://hub.baai.ac.cn/view/52163 | 2026-11-05 |
| Grokking 报道（量子位/头条） | http://m.toutiao.com/group/7266354199431250473/ | 2026-11-05 |
| Omnigrok / 权重范数（集智斑图） | https://pattern.swarma.org/mobile/article/239 | 2026-11-05 |
| Anthropic: Teaching Claude why | https://www.anthropic.com/research/teaching-claude-why | 2026-11-05 |
| RLHF→Verifiable Rewards 综述 | https://perform.digital/blogs/rlhf-to-verifiable-rewards/ | 2026-11-05 |
| 伦理框架对比（CAI/RLHF）arXiv:2402.01651 | https://arxiv.org/pdf/2402.01651 | 2026-11-05 |
| LLM-based Multi-Agent 综述 | https://paperguru.ai/benchmark/pdfs/llm-based-multi-agent.pdf | 2026-11-05 |
| 多 Agent 角色扮演反思（zoeyli.com） | https://zoeyli.com/blog/The-Myth-of-Multi-Agent-as-Role-Playing/ | 2026-11-05 |
| Emergent Intelligence in Multi-Agent Systems 综述（TechRxiv） | https://www.techrxiv.org/doi/pdf/10.36227/techrxiv.177092236.62657640/v1 | 2026-11-05 |
| Agentic AI 架构综述 arXiv:2601.12560 | https://arxiv.org/html/2601.12560 | 2026-11-05 |
| LLM Agent 方法综述 arXiv:2503.21460 | https://arxiv.org/pdf/2503.21460 | 2026-11-05 |
| SCAN 组合泛化（引述页 arXiv:1904.09708） | https://arxiv.org/pdf/1904.09708 | 2026-11-05 |
| gSCAN arXiv:2202.10745 | https://arxiv.org/html/2202.10745v1 | 2026-11-05 |
| Representational Homomorphism 预测组合泛化 arXiv:2601.18858 | https://arxiv.org/html/2601.18858v1 | 2026-11-05 |
| Training on the Test Task Confounds Evaluation and Emergence | https://arxiv.org/html/2407.07890v1 | 2026-11-05 |
| Goodeye Labs: 2025 LLM 评测年报（Goodhart 证据） | https://www.goodeyelabs.com/insights/llm-evaluation-2025-review | 2026-11-05 |
| EsoLang-Bench（MMLU 选项乱序 -13%） | https://arxiv.org/html/2603.09678v1 | 2026-11-05 |
| explainx.ai: Goodhart's Law 与基准污染 | https://explainx.ai/blog/goodharts-law-ai-benchmark-contamination-gsm1k-mmlu-arena-2026 | 2026-11-05 |
| Bubeck et al., Sparks of AGI (2023) | https://arxiv.org/pdf/2303.12712 | 2026-11-05 |
| AI Wiki: Sébastien Bubeck（Sparks 争议） | https://aiwiki.ai/wiki/sebastien_bubeck | 2026-11-05 |
| Sparks of AGI Revisited（复测） | https://harderproblem.org/news/sparks-of-agi-revisited.html | 2026-11-05 |
