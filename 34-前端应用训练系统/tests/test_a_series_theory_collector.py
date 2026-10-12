"""ASeriesTheoryCollector 单元测试 — v0.5 P1 DSH 层训练数据采集器.

测试覆盖:
  TR-2.1  ASeriesTheoryCollector 类存在且实现 TrainingDataProvider 接口
  TR-2.2  get_source_name() 返回 "a_series_theory"
  TR-2.3  get_quality_threshold() 返回 "A" (理论方法论=高置信度)
  TR-2.4  fetch_cases() 从 6-TRADING/skills/ 采集 TrainingCase
  TR-2.5  TrainingCase.intent 含 A 阶段标识 (a0-a9)
  TR-2.6  TrainingCase.actions (node_sequence) 长度 ≥5 (方法论链)
  TR-2.7  layer_tags 含 "DSH"
  TR-2.8  metadata.outcome == "success" (方法论=已验证可执行)
  TR-2.9  metadata 含 theory_skill 字段 (SKILL名称)
  TR-2.10 采集器识别多种理论类型 (≥2 个不同 A 阶段)
  TR-2.11 FAIL-OPEN: skills 目录不存在返回空列表
  TR-2.12 FAIL-OPEN: 单个 SKILL.md 解析异常不影响其他
  TR-2.13 node_sequence 含理论工作流节点 (step/phase/section/classify)
  TR-2.14 每个 SKILL 生成多条 case (按章节拆分)
"""
import os
import sys
import tempfile
import textwrap
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ADAPTERS_DIR = os.path.join(os.path.dirname(_THIS_DIR), "adapters")
_34_DIR = os.path.dirname(_THIS_DIR)

for _p in [_THIS_DIR, _ADAPTERS_DIR, _34_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


class ASeriesTheoryCollectorTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """创建临时 6-TRADING/skills/ 目录 + 样本 SKILL.md 文件."""
        cls._tmpdir = tempfile.mkdtemp(prefix="a_series_theory_test_")

        # 构造 skills/ 目录
        cls._skills_dir = os.path.join(cls._tmpdir, "6-TRADING", "skills")
        os.makedirs(cls._skills_dir, exist_ok=True)

        # 样本1: A0 矛盾论 (dream-contradiction-theory)
        a0_dir = os.path.join(cls._skills_dir, "dream-contradiction-theory")
        os.makedirs(a0_dir, exist_ok=True)
        a0_file = os.path.join(a0_dir, "SKILL.md")
        with open(a0_file, "w") as f:
            f.write(textwrap.dedent('''
                ---
                name: dream-contradiction-theory
                version: 1.1.0
                ---
                # A0 矛盾分析理论

                ## 一、哲学基础 — 三源蒸馏

                | 原理 | 核心要义 | 交易映射 |
                |:-----|:---------|:---------|
                | 矛盾普遍性 | 矛盾存在于一切事物中 | 利好利空永远同时存在 |
                | 主要矛盾 | 复杂事物中必有一个矛盾起主导作用 | 抓住主要矛盾 |
                | 矛盾转化 | 矛盾双方在一定条件下相互转化 | 设定转化条件监控点 |

                ## 二、矛盾分类体系 — 7大矛盾维度

                | 编号 | 矛盾维度 | 对立面A (多方) | 对立面B (空方) |
                |:-----|:---------|:--------------|:--------------|
                | C1 | 资金面矛盾 | ETF净流入 | ETF净流出 |
                | C2 | 情绪面矛盾 | FGI贪婪 | FGI恐惧 |
                | C3 | 技术面矛盾 | EMA多头排列 | EMA空头排列 |
                | C4 | 宏观矛盾 | 降息/QE | 加息/QT |
                | C5 | 地缘矛盾 | 地缘紧张 | 地缘缓和 |
                | C6 | 时序矛盾 | 短期看多 | 长期看空 |
                | C7 | 隐性矛盾 | 被压制的信号 | 显性主流信号 |

                ## 三、A0三步法 — 发现→抓住→利用

                ### Step 1: 发现矛盾 (Discovery)
                - 遍历8大矛盾维度(C1-C8)
                - 对每个矛盾对标注属性
                - 过滤无效矛盾
                - 输出矛盾清单

                ### Step 2: 抓住矛盾 (Analysis)
                - 从A1的contradiction_list中筛选主要矛盾
                - 方法: 4维评分法
                - 识别矛盾的主要方面
                - 判断矛盾转化可能性

                ### Step 3: 利用矛盾 (Utilization)
                - 顺着主要矛盾方向行动
                - 矛盾驱动的仓位调节
                - 矛盾转化预判
                - 利用次要矛盾

                ## 四、矛盾论5大铁律
                | 铁律编号 | 铁律内容 |
                |:---------|:---------|
                | A0-IRON-1 | 矛盾普遍存在 |
                | A0-IRON-2 | 主要矛盾只有一个 |
                | A0-IRON-3 | 矛盾的主要方面决定方向 |
                | A0-IRON-4 | 禁止用矛盾未消解作为等待理由 |
                | A0-IRON-5 | 矛盾会转化 |
            ''').strip())

        # 样本2: A2 第一性原理 (dream-first-principles)
        a2_dir = os.path.join(cls._skills_dir, "dream-first-principles")
        os.makedirs(a2_dir, exist_ok=True)
        a2_file = os.path.join(a2_dir, "SKILL.md")
        with open(a2_file, "w") as f:
            f.write(textwrap.dedent('''
                ---
                name: dream-first-principles
                version: 2.6.1
                ---
                # A2 第一性原理分析

                ## 核心理论框架

                ### 原理1: 阻力最小路径
                | 阻力类型 | 量化指标 | 来源 |
                |:---|:---|:---|
                | 成本摩擦 | costs.total_cost_bps | OKX订单簿 |
                | 流动性摩擦 | depth_1pct_usdt | OKX订单簿 |
                | 拥挤摩擦 | funding_rate | OKX |
                | 波动摩擦 | atr_pct | 技术指标 |

                ### 原理2: 趋势延续性
                趋势阶段: 启动期 → 加速期 → 衰竭期 → 逆转/盘整

                ## 执行流程
                Phase 0: A0强制调度门禁
                - use_skill("dream-contradiction-theory")
                - 获取A0矛盾论方法论

                Phase 1: 基本面分析
                - 资金流分析
                - 情绪指标分析
                - 地缘政治分析
                - 政策金融刺激分析

                Phase 2: 技术面分析
                - 趋势指标
                - 动量指标
                - 波动指标
                - 支撑阻力识别

                Phase 3: 左右脑辩证 + A0抓住矛盾
                - A0矛盾分析
                - 左脑确定性量化
                - 右脑模糊性模式识别
                - 辩证统一

                Phase 4: 阻力分析
                Phase 5: 趋势追踪
                Phase 6: 综合推演
                Phase 7: Regime分类
                Phase 8: 顾问评审
            ''').strip())

        # 样本3: A5 战术执行 (dream-tactical-executor)
        a5_dir = os.path.join(cls._skills_dir, "dream-tactical-executor")
        os.makedirs(a5_dir, exist_ok=True)
        a5_file = os.path.join(a5_dir, "SKILL.md")
        with open(a5_file, "w") as f:
            f.write(textwrap.dedent('''
                ---
                name: dream-tactical-executor
                version: 3.8.0
                ---
                # A5 战术执行部

                ## 决策链路
                - A4验证报告输入
                - A6情报输入
                - 综合判断
                - 决策执行
                - 仓位同步

                ## 执行前检查
                1. A4信号确定性检查 (SI≥±30)
                2. Edge同向检查 (≥20)
                3. A7实践论门禁检查
                4. RM顾问评审否决权检查

                ## 执行流程
                Phase 1: 信号接收
                Phase 2: 综合判断
                Phase 3: 风险评估
                Phase 4: 仓位计算
                Phase 5: 下单执行
                Phase 6: 仓位同步
            ''').strip())

        # 样本4: A9 离场决策 (dream-exit-skill-v2)
        a9_dir = os.path.join(cls._skills_dir, "dream-exit-skill-v2")
        os.makedirs(a9_dir, exist_ok=True)
        a9_file = os.path.join(a9_dir, "SKILL.md")
        with open(a9_file, "w") as f:
            f.write(textwrap.dedent('''
                ---
                name: dream-exit-skill-v2
                version: 2.0.0
                ---
                # A9 离场决策部

                ## 四层决策链
                ### 第一层: 风险事件离场
                - 黑天鹅事件触发
                - 交易所安全事件
                - 监管打击事件

                ### 第二层: 止损离场
                - 硬止损触发
                - 移动止损触发
                - 时间止损触发

                ### 第三层: 止盈离场
                - 目标价到达
                - 分批止盈
                - 移动止盈

                ### 第四层: 信号反转离场
                - 趋势反转信号
                - 矛盾转化触发
                - A0方向改变
            ''').strip())

        # 样本5: 非 A 系列 SKILL (不应被采集)
        other_dir = os.path.join(cls._skills_dir, "dream-data-analysis")
        os.makedirs(other_dir, exist_ok=True)
        other_file = os.path.join(other_dir, "SKILL.md")
        with open(other_file, "w") as f:
            f.write(textwrap.dedent('''
                ---
                name: dream-data-analysis
                ---
                # 数据分析部
                这是一个工具SKILL，不是A系列理论。
            ''').strip())

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    # ===== TR-2.1: 类存在且实现接口 =====
    def test_2_1_class_exists_and_implements_interface(self):
        """TR-2.1: ASeriesTheoryCollector 应存在且实现 TrainingDataProvider."""
        from a_series_theory_collector import ASeriesTheoryCollector
        from interfaces.training_data_provider import TrainingDataProvider
        collector = ASeriesTheoryCollector()
        self.assertIsInstance(collector, TrainingDataProvider)

    # ===== TR-2.2: get_source_name =====
    def test_2_2_source_name(self):
        """TR-2.2: get_source_name() 返回 'a_series_theory'."""
        from a_series_theory_collector import ASeriesTheoryCollector
        collector = ASeriesTheoryCollector()
        self.assertEqual(collector.get_source_name(), "a_series_theory")

    # ===== TR-2.3: get_quality_threshold =====
    def test_2_3_quality_threshold(self):
        """TR-2.3: get_quality_threshold() 返回 'A' (理论方法论=高置信度)."""
        from a_series_theory_collector import ASeriesTheoryCollector
        collector = ASeriesTheoryCollector()
        self.assertEqual(collector.get_quality_threshold(), "A")

    # ===== TR-2.4: fetch_cases 采集 TrainingCase =====
    def test_2_4_fetch_cases_returns_training_cases(self):
        """TR-2.4: fetch_cases() 从 6-TRADING/skills/ 采集 TrainingCase."""
        from a_series_theory_collector import ASeriesTheoryCollector
        collector = ASeriesTheoryCollector()
        collector.skills_root = self._skills_dir  # 注入测试路径
        cases = collector.fetch_cases(limit=100)
        self.assertGreater(len(cases), 0, "应至少采集到 1 条 case")
        from interfaces.training_data_provider import TrainingCase
        for c in cases:
            self.assertIsInstance(c, TrainingCase)

    # ===== TR-2.5: intent 含 A 阶段标识 =====
    def test_2_5_intent_contains_a_phase(self):
        """TR-2.5: intent 含 A 阶段标识 (a0-a9)."""
        from a_series_theory_collector import ASeriesTheoryCollector
        collector = ASeriesTheoryCollector()
        collector.skills_root = self._skills_dir
        cases = collector.fetch_cases(limit=100)
        self.assertGreater(len(cases), 0)
        phase_keywords = ["a0", "a1", "a2", "a3", "a4", "a5", "a6", "a7", "a8", "a9"]
        for c in cases:
            intent_lower = c.intent.lower()
            self.assertTrue(
                any(kw in intent_lower for kw in phase_keywords),
                f"intent '{c.intent}' 应含 A 阶段标识"
            )

    # ===== TR-2.6: node_sequence 长度 ≥5 =====
    def test_2_6_node_sequence_min_length(self):
        """TR-2.6: node_sequence 长度 ≥5 (方法论决策链)."""
        from a_series_theory_collector import ASeriesTheoryCollector
        collector = ASeriesTheoryCollector()
        collector.skills_root = self._skills_dir
        cases = collector.fetch_cases(limit=100)
        self.assertGreater(len(cases), 0)
        for c in cases:
            self.assertGreaterEqual(
                len(c.actions), 5,
                f"intent='{c.intent}' node_sequence 长度 {len(c.actions)} < 5"
            )

    # ===== TR-2.7: layer_tags 含 DSH =====
    def test_2_7_layer_tags_contains_dsh(self):
        """TR-2.7: layer_tags 含 'DSH'."""
        from a_series_theory_collector import ASeriesTheoryCollector
        collector = ASeriesTheoryCollector()
        collector.skills_root = self._skills_dir
        cases = collector.fetch_cases(limit=100)
        for c in cases:
            self.assertIn("DSH", c.layer_tags)

    # ===== TR-2.8: outcome == success =====
    def test_2_8_outcome_is_success(self):
        """TR-2.8: metadata.outcome == 'success' (方法论=已验证可执行)."""
        from a_series_theory_collector import ASeriesTheoryCollector
        collector = ASeriesTheoryCollector()
        collector.skills_root = self._skills_dir
        cases = collector.fetch_cases(limit=100)
        for c in cases:
            self.assertEqual(c.metadata.get("outcome"), "success")

    # ===== TR-2.9: metadata 含 theory_skill =====
    def test_2_9_metadata_contains_theory_skill(self):
        """TR-2.9: metadata 含 theory_skill 字段 (SKILL名称)."""
        from a_series_theory_collector import ASeriesTheoryCollector
        collector = ASeriesTheoryCollector()
        collector.skills_root = self._skills_dir
        cases = collector.fetch_cases(limit=100)
        for c in cases:
            self.assertIn("theory_skill", c.metadata)
            self.assertTrue(c.metadata["theory_skill"])

    # ===== TR-2.10: 识别多种理论类型 =====
    def test_2_10_recognizes_multiple_theory_types(self):
        """TR-2.10: 识别多种理论类型 (≥2 个不同 A 阶段)."""
        from a_series_theory_collector import ASeriesTheoryCollector
        collector = ASeriesTheoryCollector()
        collector.skills_root = self._skills_dir
        cases = collector.fetch_cases(limit=100)
        phases = {c.metadata.get("phase", "") for c in cases}
        self.assertGreaterEqual(
            len(phases), 2,
            f"应识别 ≥2 种 A 阶段理论, 实际: {phases}"
        )

    # ===== TR-2.11: FAIL-OPEN 目录不存在 =====
    def test_2_11_fail_open_when_dir_not_exist(self):
        """TR-2.11: FAIL-OPEN: skills 目录不存在返回空列表."""
        from a_series_theory_collector import ASeriesTheoryCollector
        collector = ASeriesTheoryCollector()
        collector.skills_root = "/nonexistent/skills/path"
        cases = collector.fetch_cases(limit=100)
        self.assertEqual(cases, [])

    # ===== TR-2.12: FAIL-OPEN 单个 SKILL 异常 =====
    def test_2_12_fail_open_on_single_skill_error(self):
        """TR-2.12: FAIL-OPEN: 单个 SKILL.md 解析异常不影响其他."""
        from a_series_theory_collector import ASeriesTheoryCollector
        # 在测试目录下加一个损坏的 SKILL.md
        bad_dir = os.path.join(self._skills_dir, "dream-broken-skill")
        os.makedirs(bad_dir, exist_ok=True)
        bad_file = os.path.join(bad_dir, "SKILL.md")
        with open(bad_file, "w") as f:
            f.write("\x00\x01\x02binary garbage \xff\xfe")

        collector = ASeriesTheoryCollector()
        collector.skills_root = self._skills_dir
        cases = collector.fetch_cases(limit=100)
        # 应跳过损坏文件，仍返回其他正常 SKILL 的 cases
        self.assertGreater(len(cases), 0)

    # ===== TR-2.13: node_sequence 含理论工作流节点 =====
    def test_2_13_node_sequence_contains_theory_nodes(self):
        """TR-2.13: node_sequence 含理论工作流节点 (step/phase/section/classify)."""
        from a_series_theory_collector import ASeriesTheoryCollector
        collector = ASeriesTheoryCollector()
        collector.skills_root = self._skills_dir
        cases = collector.fetch_cases(limit=100)
        theory_keywords = ["step", "phase", "section", "classify", "identify",
                           "analyze", "assess", "determine", "resolution",
                           "iron_law", "contradiction", "principle", "resistance"]
        has_theory_node = False
        for c in cases:
            node_str = " ".join(c.actions).lower()
            if any(kw in node_str for kw in theory_keywords):
                has_theory_node = True
                break
        self.assertTrue(has_theory_node, "至少一条 case 应含理论工作流节点关键词")

    # ===== TR-2.14: 每个 SKILL 生成多条 case =====
    def test_2_14_multiple_cases_per_skill(self):
        """TR-2.14: 每个 SKILL 按章节拆分生成多条 case (至少1个SKILL产出≥2条)."""
        from a_series_theory_collector import ASeriesTheoryCollector
        collector = ASeriesTheoryCollector()
        collector.skills_root = self._skills_dir
        cases = collector.fetch_cases(limit=200)
        # 按理论SKILL分组统计
        skill_counts = {}
        for c in cases:
            skill_name = c.metadata.get("theory_skill", "unknown")
            skill_counts[skill_name] = skill_counts.get(skill_name, 0) + 1
        # 至少有一个 SKILL 产出 ≥2 条 case (章节拆分)
        max_count = max(skill_counts.values()) if skill_counts else 0
        self.assertGreaterEqual(
            max_count, 2,
            f"至少1个SKILL应产出≥2条case(章节拆分), 实际分布: {skill_counts}"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
