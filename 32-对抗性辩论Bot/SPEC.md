# 32-对抗性辩论Bot — 设计规格 (SPEC)

> **版本**: v0.5 (修复评审全部 6 Major + 8 Minor + 3 Nit 问题，SPEC 设计定稿)
> **日期**: 2026-10-10
> **定位**: 营销型内容生产引擎 — 在社群中让两个持对立立场的 AI 辩手机器人围绕指定话题展开多轮辩论，产出有传播价值的话题内容
> **参考基准**: [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) 的 Bull/Bear 对抗辩论机制

---

## 一、背景与定位

### 1.1 问题定义

当前社群内容生产依赖人工或单 LLM 输出，存在：
- 单 LLM 易"墙头草"、观点平淡、缺乏冲突张力
- 内容缺少话题性和传播钩子，营销属性弱
- 人工撰写辩论内容成本高、不可持续

### 1.2 设计目标

让两个 AI 辩手在社群中围绕指定话题进行**可控的对抗性辩论**，产出：
1. 有观点碰撞的辩论实录（社群原生内容）
2. 可二次传播的营销素材（金句、话题标签、精华段落、短文案）

### 1.3 与 TradingAgents 的区别

| 维度 | TradingAgents | 本模块 |
|------|---------------|--------|
| 目标 | 交易决策（多空判断） | 内容生产（营销传播） |
| 辩论双方 | Bull/Bear 研究员 | 正反方辩手（可配置立场） |
| 输出 | 交易评级+仓位 | 辩论实录+营销素材 |
| 数据依赖 | 行情/财报/新闻 | 话题+可选背景材料 |
| 评判者 | Research Manager → Trader → Risk → PM | Judge（综合）+ Marketing Extractor |

**可复用的核心思想**：Prompt 锁立场 + 状态机控轮次 + 结构化输出约束。

---

## 二、核心架构

### 2.1 架构选型：单控制器 + 双 Bot Token

**为什么不用两个独立 bot 进程互相监听？**

Telegram Bot API 默认情况下，一个 bot **收不到另一个 bot 在群里发的消息**（即使关闭 Privacy Mode）。新版 Bot-to-Bot Communication Mode 有条件放开但坑多。

**本模块采用方案 A**：

```
                        ┌──────────────────────────┐
   社群用户/管理员触发 ──►│   DebateOrchestrator      │
   ( /debate <话题> )     │   (单进程·状态机·编排器)  │
                        └────────────┬─────────────┘
                                     │
              ┌──────────────────────┼──────────────────────┐
              ▼                      ▼                      ▼
      ┌──────────────┐      ┌──────────────┐      ┌──────────────────┐
      │  BullAgent   │      │  BearAgent   │      │  JudgeAgent      │
      │  (正方辩手)   │      │  (反方辩手)   │      │  (综合裁判·可选)  │
      │  LLM+立场Prompt│     │  LLM+立场Prompt│     │  LLM+综合Prompt  │
      └──────┬───────┘      └──────┬───────┘      └────────┬─────────┘
             │                     │                       │
             ▼                     ▼                       ▼
      ┌──────────────┐      ┌──────────────┐      ┌──────────────────┐
      │ TelegramBotA │      │ TelegramBotB │      │ MarketingExtractor│
      │  (正方Bot)   │      │  (反方Bot)    │      │ 金句/标签/短文案  │
      └──────────────┘      └──────────────┘      └──────────────────┘
```

**关键点**：
- 辩论编排由 `DebateOrchestrator` 统一控制，两个 bot 只是"发声器"
- bot 只响应人类触发消息，**从不监听对方 bot 的消息** → 从根上杜绝死循环
- 上下文（辩论历史）由控制器维护并注入双方 prompt

### 2.2 辩论状态机

```
         ┌──────┐
         │ idle │  等待 /debate <topic> 命令
         └──┬───┘
            │ 设置话题 + 校验
            ▼
     ┌──────────────┐
     │  preparing   │  初始化辩手、加载背景材料、构建初始 prompt
     └──────┬───────┘
            │
            ▼
     ┌──────────────┐   round < max_rounds
     │  bull_turn   │◄──────────────────┐
     │  (正方发言)   │                    │
     └──────┬───────┘                    │
            │ 写入 transcript             │
            ▼                            │
     ┌──────────────┐                    │
     │  bear_turn   │────────────────────┘
     │  (反方反驳)   │  round++
     └──────┬───────┘
            │ round >= max_rounds
            ▼
     ┌──────────────┐
     │  judging     │  Judge 综合双方论点（可选）
     └──────┬───────┘
            │
            ▼
     ┌──────────────┐
     │  marketing   │  提取金句/话题标签/短文案
     └──────┬───────┘
            │
            ▼
     ┌──────────────┐
     │  quality     │  辩论质量评估（S/A/B/C 分级）
     └──────┬───────┘
            │
            ▼
         ┌──────┐
         │ done │  输出完整记录，状态复位
         └──────┘
```

**人工介入状态**（详见第十章）：辩论中任意时刻可进入 `paused`（暂停）；`/stop` 不直接终止，而是跳过剩余辩论轮次，仍执行 judging → marketing → quality，最终 `done` 时 `status='stopped'`；`/inject` 不改变状态，仅向 transcript 注入观点。

**状态字段**：
- `topic: str` — 辩论话题（群主人工设置）
- `round: int` — 当前轮次
- `max_rounds: int` — 最大轮次（默认 2）
- `transcript: list[Turn]` — 完整辩论记录（含人工介入记录）
- `current_speaker: 'bull' | 'bear'`
- `status: idle | preparing | bull_turn | bear_turn | judging | marketing | quality | done | paused`
- `injected_views: list[str]` — 群主注入的观点列表

---

## 三、核心组件设计

### 3.1 DebateOrchestrator（辩论编排器）

**职责**：状态机驱动、轮次控制、上下文注入、结果收集。

```python
class DebateOrchestrator:
    def __init__(self, bull_agent, bear_agent, judge_agent, marketing_extractor,
                 quality_evaluator, telegram_dual_bot, config):
        ...

    async def run(self, topic: str, chat_id: int, max_rounds: int = 2,
                  background: str = "") -> DebateResult:
        """执行一场完整辩论。

        Args:
            topic: 辩论话题
            chat_id: Telegram 群 ID
            max_rounds: 最大辩论轮次
            background: 背景材料（可选，注入双方 prompt）

        Returns:
            DebateResult: 含完整 transcript + 营销素材
        """
        ...
```

**轮次编排循环**：
```
for round in range(max_rounds):
    bull_arg = await bull_agent.argue(topic, transcript, background)
    await telegram_dual_bot.send_as('bull', format_message(bull_arg))
    transcript.append(bull_turn)

    bear_arg = await bear_agent.rebut(topic, transcript, background)
    await telegram_dual_bot.send_as('bear', format_message(bear_arg))
    transcript.append(bear_turn)

if judge_enabled:
    verdict = await judge_agent.synthesize(topic, transcript)
    await telegram_dual_bot.send_as('judge', format_verdict(verdict))

material = marketing_extractor.extract(transcript)
quality_score = quality_evaluator.evaluate(topic, transcript, material)
return DebateResult(topic, transcript, verdict, material, quality_score)
```

**核心数据模型**：

```python
@dataclass
class Turn:
    speaker: str          # 'bull' | 'bear' | 'judge' | 'inject'
    round: int            # 第几轮（inject 记为 0）
    content: Argument | str  # 辩手为 Argument，inject 为纯文本
    timestamp: datetime

@dataclass
class DebateResult:
    topic: str
    transcript: list[Turn]
    verdict: Verdict | None
    material: MarketingMaterial
    quality_score: DebateQualityScore
    status: str           # 'completed' | 'stopped'
```

### 3.2 BullAgent / BearAgent（辩手）

**核心设计：Prompt 锁立场**（借鉴 TradingAgents，避免墙头草）

```python
BULL_SYSTEM_PROMPT = """你是正方辩手。你的立场是：**必须**支持话题"{topic}"。
规则：
1. 只输出支持该立场的论点和论据，禁止出现任何让步、中立或反对表述
2. 每轮提供 2-3 个论点，每个论点配一句论据
3. 针对反方上一轮的观点进行反驳（如果有）
4. 输出 JSON: {{"thesis": "...", "arguments": ["...", "..."], "quote": "金句", "confidence": 0.0-1.0}}
"""

BEAR_SYSTEM_PROMPT = """你是反方辩手。你的立场是：**必须**反对话题"{topic}"。
规则：
1. 只输出反对该立场的论点和论据，禁止出现任何让步、中立或支持表述
2. 每轮提供 2-3 个论点，每个论点配一句论据
3. 针对正方上一轮的观点进行反驳
4. 输出 JSON: {{"thesis": "...", "arguments": ["...", "..."], "quote": "金句", "confidence": 0.0-1.0}}
"""
```

**结构化输出契约**：
```python
@dataclass
class Argument:
    thesis: str           # 核心论点
    arguments: list[str]  # 论据列表
    quote: str            # 金句（用于营销提取）
    confidence: float     # 本方置信度（0-1）
    raw: str              # 原始 LLM 输出
```

### 3.3 JudgeAgent（综合裁判，可选）

综合双方论点，输出中立裁决 + 话题升华。用于辩论收尾，增强内容价值感。

```python
@dataclass
class Verdict:
    summary: str          # 辩论总结
    winner: str | None    # 'bull' | 'bear' | None(平局)
    key_insights: list[str]  # 核心洞察
    topic_angle: str      # 话题升华角度（用于营销）
```

### 3.4 MarketingExtractor（营销素材提取器）

**这是本模块的差异化核心**——将辩论转化为可传播的营销素材。

```python
@dataclass
class MarketingMaterial:
    quotes: list[str]              # 金句摘录（来自双方 quote 字段）
    hashtags: list[str]            # 话题标签（#xxx）
    highlight_paragraph: str       # 精华段落（可直接转发）
    short_copy: list[str]          # 短文案（小红书/推特风格，3-5 条）
    debate_title: str              # 辩论标题（吸引点击）
```

**提取策略**：
- 金句：直接取双方 `quote` 字段，按传播力排序
- 话题标签：从 topic + 高频关键词提取
- 精华段落：Judge 综合 + 双方最强论点拼接；**Judge 关闭时 fallback 为双方最强论点直接拼接**（无综合升华）
- 短文案：调用 LLM 基于 transcript 生成多风格短文案

### 3.5 TelegramDualBot（双 Bot 封装）

持有两个 bot token，按角色发消息。

```python
class TelegramDualBot:
    def __init__(self, bull_token: str, bear_token: str, judge_token: str | None = None):
        self.bull = Bot(bull_token)
        self.bear = Bot(bear_token)
        self.judge = Bot(judge_token) if judge_token else None

    async def send_as(self, role: str, chat_id: int, text: str) -> Message:
        """按角色发送消息。

        role: 'bull' | 'bear' | 'judge'
        """
        bot = {'bull': self.bull, 'bear': self.bear, 'judge': self.judge}[role]
        # 长消息自动分段（4096 字符限制）
        # 发送前 sleep 1-2s 规避 rate limit
        # 发送失败重试 1 次（指数退避 2s），仍失败则抛出异常由 orchestrator 处理
        ...
```

**Telegram 侧前置配置**：
1. @BotFather 创建 2-3 个 bot，获取 token
2. 全部拉入目标群，设为管理员
3. @BotFather 对每个 bot 执行 `/setprivacy` → Disable

---

## 四、复用现有基础设施

| 基础设施 | 来源 | 复用方式 |
|----------|------|----------|
| **LLM 工厂** | `30-真实环境交互系统/core/llm_factory.py` | 直接 `create_llm(config)` 获取 LangChain ChatModel，支持 qwen/openai/anthropic/ollama |
| **配置模式** | `30-真实环境交互系统/config.yaml` | 复用 `llm` 段配置结构，新增 `debate` 段 |
| **通知 Bot 模式** | `15-监控告警系统/feishu_alert.py` | 参考直接 HTTP API 调用模式（如不引入 python-telegram-bot） |
| **群管理模式** | `deploy/hermes/group_poller.py` | 参考群 ID 配置、轮询触发模式 |

**新增依赖**：
- `python-telegram-bot`（推荐，async 原生支持）或直接用 `requests` 调 Telegram Bot API（轻量，参考 feishu_alert）

**config.yaml 结构示例**：

```yaml
debate:
  max_rounds: 2
  judge_enabled: true
  pause_timeout_minutes: 30       # /pause 超时自动 stop
  models:
    debater: qwen-turbo           # 辩手用低成本模型
    judge: qwen-plus              # 裁判综合
    marketing: qwen-plus          # 营销素材生成
    quality: qwen-plus            # 质量评估
  budget:
    monthly_limit_yuan: 50.0      # 月 token 预算上限，超预算降级 qwen-turbo

telegram:
  bull_token: "env:TG_BULL_TOKEN"
  bear_token: "env:TG_BEAR_TOKEN"
  judge_token: null               # 不启用裁判 bot 时为 null
  allowed_chat_ids: [-1001234567890]  # 允许使用的群 ID 白名单
  message_interval_sec: 1.5       # 消息发送间隔，规避 rate limit

topic_filter:
  blacklist_keywords: []           # 敏感话题关键词黑名单
```

---

## 五、LLM 模型选型与成本控制

### 5.1 两条千问通路对比

项目现有两条千问接入通路，需根据辩论场景的特性选择：

| 通路 | 实现 | 计费 | 适用 |
|------|------|------|------|
| **DashScope API** | `16-调控系统/core/qwen_client.py`、`6-TRADING/skills/dream-bailian-integration/src/bailian_client.py`、`30-真实环境交互系统/core/llm_factory.py` | 按 token 计费 | 高频、低延迟、需结构化输出 ✅ 辩论主链路 |
| **qianwen.com 网页（bsk 自动化）** | `1-ARCHITECTURE/skills/dream-qwen-eval-collab/SKILL.md`，用 BrowserSkill 操作网页 | 免费（有每日限额） | 低频深度调研、不需结构化输出 ❌ 不适合辩论主循环 |

**为什么不用 bsk 网页方案跑辩论主循环**：
- 单次调用需 60–120s（填输入框 30s + 等回复 30s+ + 提取），一场辩论 6 次调用需 **4–12 分钟**，群聊用户无法等待
- 网页版不支持 JSON schema，辩手的 `{thesis, arguments, quote}` 无法可靠解析，立场锁效果打折
- UI 改版即挂、session 65s 空闲断连，维护成本高

### 5.2 单场辩论 Token 估算

按 2 轮（4 次辩手 + 1 次 Judge + 1 次营销提取 + 1 次质量评估 = 7 次调用）：

| 项目 | 单次 | × 7 次 |
|------|------|--------|
| 输入：system prompt + topic + transcript（均值） | ~1,500 tok | ~10,500 tok |
| 输出：辩手 500 + Judge 800 + 营销 1000 + 质量 500 | — | ~4,300 tok |
| **合计** | | **~14,800 tok/场** |

### 5.3 API 成本实测（千问当前定价）

| 模型 | 输入 ¥/M | 输出 ¥/M | 单场成本 | 10场/天·月成本 |
|------|----------|----------|----------|----------------|
| **qwen-turbo** | 0.3 | 0.6 | **¥0.006** | ¥1.7 |
| qwen-plus | 1.3 | 3.0 | ¥0.027 | ¥8.0 |
| deepseek-v4.1-flash | 1.0 | 4.0 | ¥0.028 | ¥8.3 |
| qwen3.8-max | 12 | 36 | ¥0.281 | ¥84.2 |

> API 免费额度：1M 输入 + 1M 输出 token（90 天），约等于 67 场 qwen3.8-max 或 13 万场 qwen-turbo。

### 5.4 模型分档策略（降本 90%+）

不同角色对模型能力要求不同，采用分档策略：

| 角色 | 推荐模型 | 理由 |
|------|----------|------|
| Bull/Bear 辩手 | **qwen-turbo** 或 **deepseek-v4.1-flash** | 只需按立场输出论点+论据，无需深度推理，turbo 足够且支持结构化输出 |
| Judge 综合 | **qwen-plus** | 需综合双方论点并升华，稍强模型 |
| 营销素材提取 | **qwen-plus** | 需创造力生成多风格短文案 |
| 质量评估 | **qwen-plus** | 需语义判断冲突强度、评估话题升华度 |
| 精品辩论（可选） | qwen3.8-max | 仅重要场次启用 |

分档后单场成本从 ¥0.281 降至 **~¥0.016**（4×turbo 辩手 + 3×plus 裁判/营销/质量），10 场/天月成本约 **¥4.7**。

### 5.5 上下文瘦身（再降 50%）

- **Transcript 不全文传递**：每轮只传对方上一轮的发言摘要，而非完整历史
- **背景材料可选**：无背景时不传
- **输出限长**：辩手 `max_tokens` 限制在 600，避免啰嗦
- **立场 prompt 精简**：去除冗余说明，保留核心约束

### 5.6 Token 预算门禁

在 `DebateOrchestrator` 内置成本追踪器，超预算自动降级或拒绝：

```python
class TokenBudget:
    monthly_limit_yuan: float = 50.0   # 月预算上限
    def check(self) -> bool: ...        # 超预算则拒绝新辩论 / 降级到 qwen-turbo
    def record(self, model, in_tok, out_tok): ...  # 累计并记录日志
```

降级策略：超预算时强制所有角色用 qwen-turbo，而非拒绝服务。

### 5.7 bsk 网页方案的可选旁路

仅用于**精品辩论的最终营销文案打磨**（非实时步骤，可接受分钟级延迟）：
- 每周挑 1 场最精彩辩论
- 用 `dream-qwen-eval-collab` skill 调 qianwen.com 的 qwen3.8-max 做最终文案润色
- 免费获得旗舰模型的高质量输出

---

## 六、模块结构

```
32-对抗性辩论Bot/
├── SPEC.md                    # 本文件
├── README.md
├── config.yaml                # 配置（llm 段复用 + debate 段 + telegram 段）
├── core/
│   ├── __init__.py
│   ├── orchestrator.py        # DebateOrchestrator 状态机
│   ├── agents.py              # BullAgent / BearAgent / JudgeAgent
│   ├── prompts.py             # 立场 prompt 模板
│   ├── marketing.py           # MarketingExtractor
│   ├── quality.py             # DebateQualityEvaluator 辩论质量评估
│   ├── telegram_bot.py        # TelegramDualBot 封装 + 管理员命令处理
│   └── models.py              # Turn / Argument / Verdict / MarketingMaterial / DebateQualityScore / DebateResult 数据模型
├── cli.py                     # CLI 入口（手动触发辩论）
├── requirements.txt
└── tests/
    ├── test_orchestrator.py
    ├── test_agents.py
    ├── test_quality.py
    └── test_marketing.py
```

---

## 七、关键接口契约

### 7.1 DebateOrchestrator.run()

```
输入: topic, chat_id, max_rounds=2, background=""
  - topic: 群主通过 /debate <话题> 设置
  - background: 背景材料，默认空；群主可通过 /debate <话题> --bg <背景> 提供，后续可与 9-基本面分析联动
输出: DebateResult(topic, transcript, verdict, material, quality_score)
失败: 异常向上抛出，bot 端发送"辩论中断"提示
```

### 7.2 BullAgent.argue(topic, transcript, background) -> Argument

```
输入: 话题、历史辩论记录、背景材料
处理: 构建 prompt（立场锁 + 历史注入）→ LLM 调用 → JSON 解析
输出: Argument
重试: JSON 解析失败时重试 1 次（prompt 追加"请严格输出 JSON"），仍失败才走兜底
FAIL-OPEN: LLM 调用失败或重试后 JSON 仍解析失败时，返回兜底 Argument（thesis="...", arguments=[], quote="", confidence=0）
```

### 7.3 BearAgent.rebut(topic, transcript, background) -> Argument

同 BullAgent，立场相反。

### 7.4 MarketingExtractor.extract(transcript) -> MarketingMaterial

```
输入: 完整辩论记录
处理: 提取金句 → 生成标签 → 拼接精华 → 生成短文案（可选 LLM 增强）
输出: MarketingMaterial
```

---

## 八、风险与边界

| 风险 | 对策 |
|------|------|
| **Bot 死循环** | 控制器只响应 `from_user.is_bot == False` 的消息，bot 间不互相监听 |
| **LLM 跑题/中立** | Prompt 硬性锁立场 + JSON schema 校验，不合格则重试 |
| **Telegram 速率限制** | 每条消息间隔 1-2s，长消息分段 |
| **单条消息超 4096 字符** | 自动分段发送 |
| **敏感话题** | 话题黑名单关键词过滤（简易版，群主设置时命中黑名单则二次确认） |
| **并发辩论** | 单群同一时刻只允许一场辩论。**默认单进程部署**，按 chat_id 维度用 `asyncio.Lock` 互斥；若需多进程/多 worker 部署，须改用 Redis 分布式锁 |

---

## 九、辩论质量评估

### 9.1 评估目标

辩论的核心价值是**营销传播力**，质量评估用于：
1. 自动筛选高质量辩论做精品分发（综合分 ≥ 阈值的场自动标记为"推荐"）
2. 反馈优化 prompt（连续低分场自动触发立场强度或话题适配调整）
3. 数据统计（哪些话题/辩手配置产出质量高）

### 9.2 五维评估体系

| 维度 | 含义 | 量化方式 | 类型 |
|------|------|----------|------|
| **金句密度** | 可直接摘录的传播性句子 | 金句数量 / 总输出字数（千字含金句数） | 规则 |
| **观点多样性** | 论点覆盖面，不重复、多角度 | 去重后论点数 / 总论点数（重复率低 = 多样性高） | 规则 |
| **冲突强度** | 双方是否真在对抗，而非各说各的 | LLM 评分 0-10（qwen-plus 判断反驳命中率） | LLM |
| **话题升华度** | 是否从表层争论上升到深度洞察 | LLM 评分 0-10（qwen-plus 评估） | LLM |
| **文案可转化度** | 产出短文案的吸引力 | LLM 评分 0-10（qwen-plus 模拟用户转发意愿） | LLM |

**辅助信号（不纳入综合分，用于标记）**：
- **立场均衡度** = 1 - |bull_avg_confidence - bear_avg_confidence|。双方置信度差异大（>0.4）表示辩论一边倒，标记为"失衡"，可触发 prompt 调整弱势方立场强度。

### 9.3 综合评分算法

```
规则分（确定性，权重 40%）：
  rule_score = 金句密度×0.5 + 观点多样性×0.5

LLM 分（qwen-plus，权重 60%）：
  llm_score = 冲突强度×0.3 + 话题升华度×0.35 + 文案可转化度×0.35

综合分 = rule_score × 0.4 + llm_score × 0.6  （归一化到 0-10）
```

> 注：冲突强度需语义判断"是否针对对方上轮论点"，无法纯规则计算，故归入 LLM 分。规则分仅保留可确定性计算的两个维度。

**质量分级**：
- ≥ 8.0：S 级（精品，自动推荐分发）
- 6.0–7.9：A 级（优质，正常分发）
- 4.0–5.9：B 级（一般，仅存档）
- < 4.0：C 级（不合格，触发 prompt 优化复盘）

### 9.4 DebateQualityScore 数据模型

```python
@dataclass
class DebateQualityScore:
    overall: float              # 综合分 0-10
    grade: str                  # S/A/B/C
    dimensions: dict            # 各维度分
    rule_score: float
    llm_score: float
    highlights: list[str]       # 质量亮点描述
    suggestions: list[str]      # 改进建议（低分时给出）
```

### 9.5 评估时机

- 辩论结束后自动执行（在 marketing 提取之后）
- 评估结果写入 `DebateResult.quality_score`，随完整记录一起输出
- 不额外发群消息（避免刷屏），仅记录在完整记录中

---

## 十、人工介入机制

### 10.1 设计原则

- **仅群主/管理员可操作**：通过 Telegram `chat_member` 权限判断（`status in ('creator', 'administrator')`）
- **软中断**：`/stop` 和 `/pause` 等当前 LLM 调用完成后再停，不强行杀进程，避免半成品状态
- **可追溯**：所有介入操作记录到 transcript，保留完整辩论轨迹
- **不破坏辩论完整性**：介入后的辩论仍可生成完整记录

### 10.2 管理员命令集

| 命令 | 作用 | 状态转换 |
|------|------|----------|
| `/debate <话题>` | 群主发起一场辩论 | idle → preparing → 辩论中 |
| `/stop` | 终止辩论（当前轮完成后停），跳过剩余轮次，仍执行 judging+marketing+quality，输出完整记录（status=stopped） | 辩论中 → judging → marketing → quality → done(stopped) |
| `/pause` | 暂停辩论（当前轮完成后停住）；**超时 30 分钟未 /resume 则自动 /stop** | 辩论中 → paused |
| `/resume` | 恢复暂停的辩论 | paused → 原状态 |
| `/change_topic <新话题>` | 终止当前辩论（隐式 /stop），用新话题立即重开一场 | 辩论中 → done(stopped) → 新 preparing |
| `/inject <观点>` | 注入群主观点，下一轮双方辩手必须回应此观点 | 辩论中（注入 transcript） |

### 10.3 状态机扩展

在原状态机基础上增加 `paused` 状态；`/stop` 不新增终态，而是短路到 judging：

```
辩论中 ──/pause──► paused ──/resume──► 辩论中
   │
   ├──/stop──► judging → marketing → quality → done (status='stopped')
   │
   └──/inject──► 记录注入观点 → 辩论中（下一轮带上注入观点）
```

### 10.4 /inject 的实现

群主注入的观点作为"第三方立场"写入 transcript（`injected_views` 列表），下一轮 Bull 和 Bear 的 prompt 中增加：

> 群主提出了以下观点，请在你的论点中逐一回应（支持或反驳，取决于你的立场）：
> 1. 「<inject_content_1>」
> 2. 「<inject_content_2>」
> ...

**多次注入**：所有注入观点累计保留，prompt 中逐条列出；群主可通过 `/inject clear` 清空已注入观点。

这样群主可以引导辩论方向，增加话题性和互动感。

### 10.5 权限校验

```python
def is_admin(update) -> bool:
    member = update.effective_chat.get_member(update.effective_user.id)
    return member.status in ("creator", "administrator")
```

非管理员发送上述命令时，bot 回复"仅群主/管理员可操作此命令"，不改变状态。

---

## 十一、已定决策汇总

> 以下决策已确认，从待调研中移除。

| 决策项 | 结论 |
|--------|------|
| 话题来源 | **群主人工设置**（`/debate <话题>` 命令触发） |
| 多社群适配 | **仅 Telegram 社群**，不兼容飞书 |
| 素材分发渠道 | 模块只负责**整理完整记录**（transcript + verdict + material + quality_score），分发渠道由外部优化后处理 |

---

## 十二、验收标准（初稿）

- [ ] 两个 bot 能在同一 Telegram 群中交替发言辩论
- [ ] 辩论轮次受 max_rounds 控制，不会无限循环
- [ ] 双方立场稳定，不出现中立/让步
- [ ] 输出结构化 Argument，JSON 解析成功率 > 95%
- [ ] 能提取至少 2 条金句 + 3 个话题标签 + 1 段精华段落
- [ ] LLM 调用失败时有明确降级，不崩溃
- [ ] 辩论结束后自动生成质量评分（含 S/A/B/C 分级）
- [ ] 管理员 `/stop` `/pause` `/resume` 命令生效，非管理员无权限
- [ ] `/inject <观点>` 后下一轮辩手能回应注入观点
- [ ] 输出完整辩论记录（transcript + verdict + material + quality_score）供外部分发
