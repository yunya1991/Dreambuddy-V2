# 4-GENERIC：通用工具
> **原始SKILL**: tavily, github, skill-creator, markdown-convert, ontology, find-skills

---

## Tavily 搜索
**定位**: 联网搜索（加密市场+宏观+地缘）

### 集成方式
- Tavily Client API (Python)
- 已配置 TAVILY_API_KEY (Gateway进程)
- search可用 ✅ | extract不可用 ❌

### 与6-TRADING的集成
- v15_signal.py中作为网络回退层(第2层)
- A1调研的地缘政治数据源
- A6情报监控的数据源

---

## GitHub 集成
**定位**: 代码版本管理+PR工作流

### 功能
- gh CLI v2.45.0
- 用户 yunya1991, 全仓库读写权限
- 已集成 repos: Dreambuddy-V2, dream-trading-automation, crypto-signal-bot, dream-multiskill-v2等11个

---

## Skill Creator（Skill创建器）
**定位**: 动态创建/更新Hermes Skill

### 架构
```
skill-creator/
├── skill-creator/      # 核心: 从定义→SKILL.md
├── global-plugin/      # 全局插件
├── workspace-plugin/   # 工作区插件
├── skill_agent.py      # 智能Agent
└── README.md
```

---

## Markdown Convert
各类文件格式↔Markdown转换

## Ontology
知识本体、实体关系定义、概念分类

## Find-Skills
全系统SKILL搜索发现引擎
