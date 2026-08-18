import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


def _load_module():
    module_path = Path(__file__).resolve().parent.parent / "ops" / "nanoclaw" / "core_task1" / "scripts" / "push_report_api.py"
    spec = importlib.util.spec_from_file_location("core_task1_push_report_api", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _load_daily_transform_module():
    module_path = Path(__file__).resolve().parent.parent / "ops" / "nanoclaw" / "core_task1" / "scripts" / "daily_publish_transform.py"
    spec = importlib.util.spec_from_file_location("core_task1_daily_publish_transform", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


class TestPushReportApi(unittest.TestCase):
    def test_build_summary_filters_markdown_noise(self) -> None:
        mod = _load_module()
        content = "\n".join(
            [
                "# 标题",
                "",
                "## 小节",
                "| A | B |",
                "|---|---|",
                "这是第一句。",
                "```json",
                '{"x":1}',
                "```",
                "这是第二句。",
            ]
        )
        summary = mod._build_summary(content, limit=100)
        self.assertIn("这是第一句。", summary)
        self.assertIn("这是第二句。", summary)
        self.assertNotIn("#", summary)
        self.assertNotIn("|", summary)

    def test_dry_run_writes_receipt_with_required_fields(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            outputs = base / "outputs"
            raw = base / "raw"
            outputs.mkdir(parents=True, exist_ok=True)
            raw.mkdir(parents=True, exist_ok=True)
            artifact = outputs / "brief_v3_20260411_optimized.md"
            artifact.write_text("# T\n内容A\n内容B", encoding="utf-8")
            state_file = raw / "state.json"
            receipt_file = raw / "outbox.jsonl"

            import sys

            argv_backup = list(sys.argv)
            try:
                sys.argv = [
                    "push_report_api.py",
                    "--dry-run",
                    "--artifact",
                    str(artifact),
                    "--api-key",
                    "k",
                    "--state-file",
                    str(state_file),
                    "--receipt-file",
                    str(receipt_file),
                    "--api-base",
                    "http://8.209.238.108/api/v1",
                ]
                code = mod.main()
            finally:
                sys.argv = argv_backup

            self.assertEqual(code, 0)
            self.assertTrue(receipt_file.exists())
            line = receipt_file.read_text(encoding="utf-8").strip().splitlines()[-1]
            obj = json.loads(line)
            self.assertTrue(obj.get("ok"))
            self.assertTrue(obj.get("dry_run"))
            self.assertIn("trace_id", obj)
            self.assertIn("artifact_path", obj)
            self.assertIn("artifact_path_raw", obj)
            self.assertIn("artifact_path_public", obj)
            self.assertIn("transform_profile", obj)
            self.assertIn("report_id", obj)
            self.assertIn("http_status", obj)
            self.assertTrue(Path(obj["artifact_path_public"]).exists())

    def test_traditional_transform_outputs_sellside_style(self) -> None:
        mod = _load_module()
        raw = "\n".join(
            [
                "# 执行摘要",
                "- BTC 关注度提升，资金流回暖。",
                "## 市场动态",
                "- 宏观风险边际缓和，成交改善。",
                "## 风险提示",
                "- 波动率仍高，需控制仓位。",
            ]
        )
        title, summary, content, meta = mod._traditional_public_transform(raw, "测试简报", "trace_x")
        self.assertIn("对外发布版", title)
        self.assertIn("执行摘要", content)
        self.assertIn("市场背景与驱动", content)
        self.assertIn("关键信号与证据", content)
        self.assertIn("情景与风险提示", content)
        self.assertIn("观察清单", content)
        self.assertIn("合规声明", content)
        self.assertTrue(summary)
        self.assertEqual(meta.get("transform_profile"), "traditional_sellside_v1")

    def test_daily_report_v2_transform_removes_internal_fields_and_builds_sections(self) -> None:
        mod = _load_daily_transform_module()

        def fake_search(query: str, n: int):
            if "breaking" in query:
                return [
                    {"title": "ETF 资金净流入回升", "url": "https://example.com/n1", "content": "inflow up"},
                    {"title": "交易所上新带动成交放大", "url": "https://example.com/n2", "content": "volume up"},
                ]
            return [
                {"title": "本周将发布美国通胀数据", "url": "https://example.com/e1", "content": "macro event"},
                {"title": "头部项目治理投票窗口开启", "url": "https://example.com/e2", "content": "governance"},
            ]

        raw = "\n".join(
            [
                "# 执行摘要",
                "- 建议控制仓位并关注资金流持续性",
                "> 跟踪编号: abc",
                "- **分析框架**: V9.3 事件账本 + 市场状态识别 + 动态仓位管理",
                "## 市场背景",
                "- 关注点在资金流连续性与事件兑现",
            ]
        )
        out = mod.transform_daily_report_v2(
            raw_content=raw,
            title="AI 市场研究日报",
            tavily_api_key="k",
            search_fn=fake_search,
        )
        content = str(out.get("content") or "")
        self.assertIn("一、今日建议动作（执行摘要）", content)
        self.assertIn("二、市场状态与主要矛盾", content)
        self.assertIn("三、关键信号与证据（多维）", content)
        self.assertIn("四、交易约束与失效条件", content)
        self.assertIn("五、未来24-72小时关键事件日历", content)
        self.assertNotIn("跟踪编号", content)
        self.assertNotIn("分析框架", content)
        meta = out.get("meta") or {}
        self.assertTrue(meta.get("tavily_used"))
        self.assertGreaterEqual(len(meta.get("source_urls") or []), 2)

    def test_daily_report_v3_keeps_market_chart_and_signal_risk_and_watchlist(self) -> None:
        mod = _load_daily_transform_module()

        def fake_search(query: str, n: int):
            if "breaking" in query:
                return [
                    {"title": "ETF inflow jumps", "url": "https://example.com/n1", "content": "flow up"},
                    {"title": "SEC expands review", "url": "https://example.com/n2", "content": "policy"},
                ]
            return [
                {"title": "FOMC meeting this week", "url": "https://example.com/e1", "content": "macro"},
            ]

        def fake_llm(text: str) -> str:
            return f"中文标题：{text.replace('ETF', '交易所交易基金').replace('SEC', '美国证监会').replace('FOMC', '美联储议息会议')}"

        raw = "\n".join(
            [
                "# 加密市场晨报（V9.3/V9.8 优化版）",
                "**分析框架**: V9.3 事件账本 + 市场状态识别 + 动态仓位管理",
                "## 📊 市场状态诊断",
                "- 热度指数：72",
                "- 资金流状态：净流入",
                "- 波动状态：中高",
                "## 📰 新闻事件影响分析",
                "### 加密监管（crypto_regulation）",
                "- SEC starts new consultation",
                "### 项目动态（project_update）",
                "- ETH protocol upgrade is scheduled",
                "### 市场分析（market_analysis）",
                "- ETF inflow jumps",
                "## 📈 信号汇总",
                "- 综合信号：中性偏多",
                "- 资金流增强：是",
                "## ⚠️ 风险提示",
                "- 地缘风险升级可能引发波动放大",
                "## 📋 明日观察清单",
                "- 关注美联储官员讲话",
            ]
        )
        out = mod.transform_daily_report_v3(
            raw_content=raw,
            title="AI 市场研究日报",
            tavily_api_key="k",
            search_fn=fake_search,
            llm_fn=fake_llm,
        )
        content = str(out.get("content") or "")
        self.assertIn("二、市场状态与主要矛盾", content)
        self.assertIn("2.1 市场状态诊断图表（保留）", content)
        self.assertIn("三、重点新闻与分类解读（中文）", content)
        self.assertIn("监管与政策", content)
        self.assertIn("项目与技术", content)
        self.assertIn("市场与交易", content)
        self.assertIn("四、信号汇总与风险提示（保留）", content)
        self.assertNotIn("五、观察清单（24-72h）", content)
        self.assertNotIn("六、说明", content)
        self.assertNotIn("**分析框架**", content)
        self.assertNotIn("生成时间", content)
        self.assertNotIn("数据窗口", content)
        self.assertIn("中文标题:交易所交易基金", content)

    def test_daily_report_v3_outputs_sellside_meta_fields(self) -> None:
        mod = _load_daily_transform_module()

        def fake_search(query: str, n: int):
            return []

        raw = "\n".join(
            [
                "# 标题",
                "## 📊 市场状态诊断",
                "- BTC 当前价: 76000",
                "## 📈 信号汇总",
                "- 综合信号: 中性",
                "## ⚠️ 风险提示",
                "- 监管不确定性可能带来波动",
                "## 📋 明日观察清单",
                "- 关注宏观数据发布",
            ]
        )
        out = mod.transform_daily_report_v3(raw_content=raw, title="AI 市场研究日报", tavily_api_key="", search_fn=fake_search, llm_fn=lambda x: x)
        meta = out.get("meta") or {}
        self.assertIn("qa_gate", meta)
        self.assertIn("qa_score", meta)
        self.assertIn("qa_fail_reasons", meta)
        self.assertIn("diff_audit", meta)

    def test_daily_report_v3_converts_signal_table_and_fills_missing_signals_with_tavily(self) -> None:
        mod = _load_daily_transform_module()

        def fake_search(query: str, n: int):
            q = query.lower()
            if "breaking" in q:
                return [{"title": "ETF inflow jumps", "url": "https://example.com/n1", "content": "flow up"}]
            if "upcoming" in q:
                return [{"title": "FOMC meeting this week", "url": "https://example.com/e1", "content": "macro"}]
            if "funding rate" in q or "open interest" in q or "fear and greed" in q:
                return [
                    {"title": "BTC funding rate turns positive", "url": "https://example.com/s1", "content": ""},
                    {"title": "Bitcoin open interest rises 24h", "url": "https://example.com/s2", "content": ""},
                    {"title": "Crypto fear and greed index improves", "url": "https://example.com/s3", "content": ""},
                ][:n]
            return []

        raw = "\n".join(
            [
                "# 标题",
                "## 📊 市场状态诊断",
                "- 热度指数：72",
                "- 资金流状态：净流入",
                "- 波动状态：中高",
                "- 主线资产：BTC",
                "- 杠杆风险：中性",
                "- 流动性：改善",
                "## 📈 信号汇总",
                "| 信号类型 | 数值 | 阈值 | 解读 |",
                "|----------|------|------|------|",
                "| **综合信号** | **+0.052** | ±0.15 | 中性 |",
                "| 宏观信号 | +0.074 | ±0.15 | 宽松偏多 |",
                "## ⚠️ 风险提示",
                "- 监管不确定性可能带来波动",
                "## 📋 明日观察清单",
                "- 关注宏观数据发布",
            ]
        )
        out = mod.transform_daily_report_v3(
            raw_content=raw,
            title="AI 市场研究日报",
            tavily_api_key="k",
            search_fn=fake_search,
            llm_fn=lambda x: x,
        )
        content = str(out.get("content") or "")
        self.assertNotIn("- | 信号类型", content)
        self.assertIn("综合信号", content)
        self.assertIn("资金费率", content)
        meta = out.get("meta") or {}
        self.assertNotEqual(meta.get("qa_gate"), "fail", msg=str(meta))

    def test_daily_report_v3_drops_irrelevant_watch_events_and_falls_back(self) -> None:
        mod = _load_daily_transform_module()

        def fake_search(query: str, n: int):
            q = query.lower()
            if "breaking" in q:
                return []
            if "upcoming" in q:
                return [
                    {"title": "Dogecoin price prediction breaks 0.095", "url": "https://example.com/e1", "content": ""},
                    {"title": "Stage presale ends early for meme token", "url": "https://example.com/e2", "content": ""},
                ]
            return []

        raw = "\n".join(
            [
                "# 标题",
                "## 📊 市场状态诊断",
                "- 热度指数：72",
                "- 资金流状态：净流入",
                "- 波动状态：中高",
                "## 📈 信号汇总",
                "- 综合信号：中性",
                "## ⚠️ 风险提示",
                "- 监管不确定性可能带来波动",
                "## 📋 明日观察清单",
                "- 关注美联储官员讲话",
            ]
        )
        out = mod.transform_daily_report_v3(
            raw_content=raw,
            title="AI 市场研究日报",
            tavily_api_key="k",
            search_fn=fake_search,
            llm_fn=lambda x: x,
        )
        content = str(out.get("content") or "")
        self.assertNotIn("dogecoin", content.lower())
        self.assertNotIn("meme", content.lower())
        self.assertNotIn("## 五、观察清单", content)
        self.assertIn("宏观与地缘", content)
        self.assertIn("关注美联储官员讲话", content)

    def test_daily_report_v3_filters_low_quality_watch_items(self) -> None:
        mod = _load_daily_transform_module()

        def fake_search(query: str, n: int):
            return []

        raw = "\n".join(
            [
                "# 标题",
                "## 📊 市场状态诊断",
                "- 热度指数：72",
                "- 资金流状态：净流入",
                "- 波动状态：中高",
                "## 📈 信号汇总",
                "- 综合信号：中性",
                "## ⚠️ 风险提示",
                "- 监管不确定性可能带来波动",
                "## 📋 明日观察清单",
                "- 以太坊- ,",
            ]
        )
        out = mod.transform_daily_report_v3(
            raw_content=raw,
            title="AI 市场研究日报",
            tavily_api_key="k",
            search_fn=fake_search,
            llm_fn=lambda x: x,
        )
        content = str(out.get("content") or "")
        self.assertNotIn("以太坊- ,", content)
        self.assertNotIn("## 五、观察清单", content)

    def test_daily_report_v3_uses_source_events_for_drivers_and_labels_sources_and_filters_irrelevant_news(self) -> None:
        mod = _load_daily_transform_module()

        def fake_search(query: str, n: int):
            return []

        raw = "\n".join(
            [
                "# 加密市场晨报（V9.3/V9.8 优化版）",
                "## 🔔 今日要点（12 条）",
                "1. **[多家银行欲推出欧元稳定币，Fireblocks提供支持]** - ...（https://www.coindesk.com/business/2026/04/21/xxx，2026-04-21T08:00:00+00:00）",
                "2. **[派盾：KelpDAO攻击者已将75,700枚ETH转移至2个新地址]** - ...（https://m.theblockbeats.info/flash/342297，2026-04-21T07:48:45+00:00）",
                "## 🧭 按事件类型分节",
                "### 市场分析（market_analysis）",
                "- 钠电突破:安全技术提升能量密度逼近锂电开启量产（https://example.com/na，2026-04-21T07:00:00+00:00）",
                "### 加密监管（crypto_regulation）",
                "- Atkins执掌SEC一周年：加密监管从「执法打压」到「规则重建」（https://example.com/reg，2026-04-21T06:41:07+00:00）",
                "## 📊 市场状态诊断",
                "- 热度指数：72",
                "- 资金流状态：净流入",
                "- 波动状态：中高",
                "## 📈 信号汇总",
                "- 综合信号：中性",
                "## ⚠️ 风险提示",
                "- 监管不确定性可能带来波动",
                "## 📋 明日观察清单",
                "- 关注宏观数据发布",
            ]
        )
        out = mod.transform_daily_report_v3(
            raw_content=raw,
            title="AI 市场研究日报",
            tavily_api_key="",
            search_fn=fake_search,
            llm_fn=lambda x: x,
        )
        content = str(out.get("content") or "")
        self.assertIn("Top 3 驱动", content)
        self.assertIn("P0: BTC 主线资金与流动性", content)
        self.assertIn("P1: 监管与政策预期变化", content)
        self.assertIn("P2: 宏观与地缘事件扰动", content)
        self.assertIn("核心影响事件", content)
        self.assertIn("欧元稳定币", content)
        self.assertIn("KelpDAO", content)
        self.assertIn("来源=", content)
        self.assertNotIn("钠电突破", content)
        self.assertIn("多空新闻", content)

    def test_daily_report_v3_core_impact_events_excludes_altcoins(self) -> None:
        mod = _load_daily_transform_module()

        raw = "\n".join(
            [
                "# 加密市场晨报（V9.3/V9.8 优化版）",
                "## 🔔 今日要点（12 条）",
                "1. **[Binance将移除1INCH/BTC、WIF/BTC等现货交易对]** - ...（https://m.theblockbeats.info/flash/342290，2026-04-21T07:35:16+00:00）",
                "2. **[多家银行欲推出欧元稳定币，Fireblocks提供支持]** - ...（https://www.coindesk.com/business/2026/04/21/xxx，2026-04-21T08:00:00+00:00）",
                "3. **[派盾：KelpDAO攻击者已将75,700枚ETH转移至2个新地址]** - ...（https://m.theblockbeats.info/flash/342297，2026-04-21T07:48:45+00:00）",
                "## 📊 市场状态诊断",
                "- 热度指数：72",
                "- 资金流状态：净流入",
                "- 波动状态：中高",
                "## 📈 信号汇总",
                "- 综合信号：中性",
                "## ⚠️ 风险提示",
                "- 监管不确定性可能带来波动",
                "## 📋 明日观察清单",
                "- 关注宏观数据发布",
            ]
        )
        out = mod.transform_daily_report_v3(
            raw_content=raw,
            title="AI 市场研究日报",
            tavily_api_key="",
            search_fn=lambda q, n: [],
            llm_fn=lambda x: x,
        )
        content = str(out.get("content") or "")
        self.assertIn("核心影响事件", content)
        self.assertNotIn("1INCH", content)
        self.assertNotIn("WIF", content)
        self.assertIn("欧元稳定币", content)

    def test_daily_report_v3_drops_section_5_and_6_and_moves_events_to_news(self) -> None:
        mod = _load_daily_transform_module()

        raw = "\n".join(
            [
                "# 标题",
                "## 🔔 今日要点（12 条）",
                "1. **[多家银行欲推出欧元稳定币，Fireblocks提供支持]** - ...（https://www.coindesk.com/business/2026/04/21/xxx，2026-04-21T08:00:00+00:00）",
                "2. **[伊朗代表团未启程参与和平谈判]** - ...（https://m.theblockbeats.info/flash/342111，2026-04-21T07:48:45+00:00）",
                "## 📊 市场状态诊断",
                "- 热度指数：72",
                "- 资金流状态：净流入",
                "- 波动状态：中高",
                "## 📈 信号汇总",
                "- 综合信号：中性",
                "## ⚠️ 风险提示",
                "- 多家银行欲推出欧元稳定币，负责实施",
                "- 伊朗代表团未启程参与和平谈判",
                "## 📋 明日观察清单",
                "- 考虑发行人民币挂钩稳定币，提出建议——",
            ]
        )
        out = mod.transform_daily_report_v3(
            raw_content=raw,
            title="AI 市场研究日报",
            tavily_api_key="",
            search_fn=lambda q, n: [],
            llm_fn=lambda x: x,
        )
        content = str(out.get("content") or "")
        self.assertNotIn("## 五、观察清单", content)
        self.assertNotIn("## 六、说明", content)
        self.assertIn("## 三、重点新闻与分类解读", content)
        self.assertIn("欧元稳定币", content)
        self.assertIn("伊朗", content)

    def test_daily_report_v3_adds_more_indicators_and_analysis_section(self) -> None:
        mod = _load_daily_transform_module()

        mod._fetch_btc_indicators = lambda days=120: {
            "price": 76152.0,
            "ma20": 68759.0,
            "ma50": 68624.0,
            "ma100": 65000.0,
            "ma200": 60000.0,
            "rsi14": 52.3,
            "macd_hist": 12.0,
            "vol20": 0.34,
            "abs_ret20": 0.02,
            "ret7": 0.08,
            "ret30": 0.12,
        }
        raw = "\n".join(
            [
                "# 标题",
                "## 📊 市场状态诊断",
                "- 热度指数：72",
                "- 资金流状态：净流入",
                "- 波动状态：中高",
                "## 📈 信号汇总",
                "- 综合信号：中性",
                "## ⚠️ 风险提示",
                "- 监管不确定性可能带来波动",
                "## 📋 明日观察清单",
                "- 关注宏观数据发布",
            ]
        )
        out = mod.transform_daily_report_v3(
            raw_content=raw,
            title="AI 市场研究日报",
            tavily_api_key="",
            search_fn=lambda q, n: [],
            llm_fn=lambda x: x,
        )
        content = str(out.get("content") or "")
        self.assertIn("### 2.3 技术指标与解读", content)
        self.assertIn("MA100", content)
        self.assertIn("MA200", content)
        self.assertIn("7日涨跌幅", content)
        self.assertIn("20日波动率", content)

    def test_daily_report_v3_btc_extension_prefers_source_price(self) -> None:
        mod = _load_daily_transform_module()
        old_env = dict(os.environ)
        try:
            os.environ["REPORT_TRANSFORM_DISABLE_REMOTE"] = "1"
            raw = "\n".join(
                [
                    "# 加密市场晨报（V9.3/V9.8 优化版）",
                    "## 📊 市场状态诊断",
                    "| 指标 | 数值 | 阈值 | 状态 |",
                    "|------|------|------|------|",
                    "| BTC 当前价 | $76,152 | - | 突破 |",
                    "| MA20(20 日均线) | $68,759 | - | - |",
                    "## 📈 信号汇总",
                    "- 综合信号：中性",
                    "## ⚠️ 风险提示",
                    "- 监管不确定性可能带来波动",
                    "## 📋 明日观察清单",
                    "- 关注宏观数据发布",
                ]
            )
            out = mod.transform_daily_report_v3(
                raw_content=raw,
                title="AI 市场研究日报",
                tavily_api_key="",
                search_fn=lambda q, n: [],
                llm_fn=lambda x: x,
            )
            content = str(out.get("content") or "")
            self.assertIn("BTC=$76152", content)
            self.assertIn("MA20", content)
        finally:
            os.environ.clear()
            os.environ.update(old_env)

    def test_push_refuses_when_qa_fail(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            outputs = base / "outputs"
            raw_dir = base / "raw"
            outputs.mkdir(parents=True, exist_ok=True)
            raw_dir.mkdir(parents=True, exist_ok=True)
            artifact = outputs / "brief_v3_20260411_optimized.md"
            artifact.write_text("# T\n## ⚠️ 风险提示\n- 暂无\n", encoding="utf-8")
            state_file = raw_dir / "state.json"
            receipt_file = raw_dir / "outbox.jsonl"

            old_env = dict(os.environ)
            import sys
            argv_backup = list(sys.argv)
            try:
                os.environ["REPORT_PUSH_TRANSFORM_PROFILE"] = "daily_report_v3_llm"
                os.environ["REPORT_TRANSFORM_DISABLE_REMOTE"] = "1"
                sys.argv = [
                    "push_report_api.py",
                    "--artifact",
                    str(artifact),
                    "--api-base",
                    "http://8.209.238.108/api/v1",
                    "--api-key",
                    "k",
                    "--state-file",
                    str(state_file),
                    "--receipt-file",
                    str(receipt_file),
                ]
                code = mod.main()
            finally:
                os.environ.clear()
                os.environ.update(old_env)
                sys.argv = argv_backup
            self.assertEqual(code, 2)
            line = receipt_file.read_text(encoding="utf-8").strip().splitlines()[-1]
            obj = json.loads(line)
            self.assertFalse(obj.get("ok"))
            self.assertEqual(obj.get("qa_gate"), "fail")

    def test_preflight_fails_when_env_missing(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            mod.LOCAL_ENV_PATH = base / ".env"

            class Resp:
                status_code = 200
                text = "{}"

            orig_get = mod.requests.get
            mod.requests.get = lambda *args, **kwargs: Resp()  # type: ignore[assignment]
            import sys
            argv_backup = list(sys.argv)
            try:
                sys.argv = [
                    "push_report_api.py",
                    "--preflight",
                    "--api-base",
                    "http://8.209.238.108/api/v1",
                    "--api-key",
                    "k",
                ]
                code = mod.main()
            finally:
                mod.requests.get = orig_get
                sys.argv = argv_backup
            self.assertEqual(code, 2)

    def test_preflight_passes_when_env_and_key_and_api_ok(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            env_file = base / ".env"
            env_file.write_text("INTERNAL_API_KEY=abc\nREPORT_PUSH_MODE=prod\n", encoding="utf-8")
            mod.LOCAL_ENV_PATH = env_file

            class Resp:
                status_code = 200
                text = "{}"

            orig_get = mod.requests.get
            mod.requests.get = lambda *args, **kwargs: Resp()  # type: ignore[assignment]
            old_env = dict(os.environ)
            import sys
            argv_backup = list(sys.argv)
            try:
                os.environ.pop("INTERNAL_API_KEY", None)
                sys.argv = [
                    "push_report_api.py",
                    "--preflight",
                    "--api-base",
                    "http://8.209.238.108/api/v1",
                ]
                code = mod.main()
            finally:
                mod.requests.get = orig_get
                os.environ.clear()
                os.environ.update(old_env)
                sys.argv = argv_backup
            self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
