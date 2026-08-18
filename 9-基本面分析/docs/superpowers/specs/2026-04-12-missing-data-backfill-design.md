# Missing Data Backfill Design

## 1. 缺失数据清单 (Discovery)
通过盘点 `http://localhost:8095/api/fundamental/*/latest` 接口以及前端的渲染逻辑，当前系统主要存在以下两个维度的数据缺失，导致面板出现红色的 `missing/suspect` 降级告警：
- **`polymarket_btc_term_structure`**：缺失于 `trading` 和 `narrative` 模块，缺少对 Polymarket 预测市场上 BTC 不同期限赔率的抓取。
- **`coverage_report`**：缺失于 `trading` 和 `news` 模块，缺少针对每日宏观和加密新闻的覆盖率总结报告。

## 2. 方案评估 (Tavily vs 本地千问)

针对您的担忧，我们对两种搜索补齐方案进行了深度对比：

### 方案 A：使用 Tavily-Search (推荐)
Tavily 是一款专为 AI Agent 构建的搜索引擎。
- **优势**：
  - **稳定性极高**：API 直出，无惧复杂的网页防爬虫机制。
  - **精准数据提取**：对 Polymarket 这种包含大量动态 JS 渲染的网页，或全网散落的新闻聚合，Tavily 能直接提取干净的上下文，极大降低解析成本。
- **劣势**：轻微的外部 API 依赖。

### 方案 B：依赖本地千问联网搜索 (高风险)
- **优势**：纯本地运行，数据隐私性好。
- **劣势（印证了您的担忧）**：
  - **极不稳定**：本地大模型调用本地搜索工具链时，常常受限于网络超时、节点解析失败。
  - **幻觉与格式失控**：处理 `coverage_report` 需要阅读大量新闻并输出严格的 JSON Schema，本地千问在处理长文本+复杂 JSON 契约时，极易输出截断或错乱的数据，导致下游流水线崩溃。

## 3. 架构设计与执行路径
**核心思路**：**扬长避短，使用 Tavily 做重度检索，规避本地大模型的不稳定性。**

- **Step 1: 开发补齐脚本 (`backfill_missing_data.py`)**
  - 接入 `tavily-search` 接口。
  - **任务 A**：向 Tavily 发起查询 `"Polymarket Bitcoin price prediction odds by end of month/year"`，提取赔率结构，并写入当前周期的 narrative JSON 中。
  - **Step B**：向 Tavily 聚合过去 24 小时的 `"Macro and Crypto major events coverage"`，生成标准的 `coverage_report_YYYYMMDD.json` 并落盘到 `ops/nanoclaw/core_task1/raw/`。
- **Step 2: 注入与修复**
  - 将生成的补齐数据对接到流水线，消除前端 3005 端口页面的 `missing_data` 红色告警，恢复 `quality=ok` 的绿灯状态。
