#!/usr/bin/env python3
"""
三链融合能力综合评估测试
评估维度：
1. 经典技术指标系统 - 模块化与基础能力
2. 基本面分析系统 - 模块化与基础能力
3. 三链协同能力（AI思维链 + 技术指标 + 基本面）
"""

import sys
import os
import json
import time
from pathlib import Path
from typing import Dict, Any, List, Tuple
from dataclasses import dataclass, asdict


@dataclass
class TestResult:
    name: str
    category: str
    passed: bool
    score: int
    details: str
    metrics: Dict[str, Any] = None
    error: str = None


class ThreeChainEvaluator:
    def __init__(self):
        self.results: List[TestResult] = []
        self.start_time = time.time()

    def add_result(self, result: TestResult):
        self.results.append(result)
        status = "✓" if result.passed else "✗"
        print(f"  [{len(self.results):2d}] {result.name}... {status} {result.score}分")
        if result.error:
            print(f"       错误: {result.error}")

    def run_all(self):
        print("=" * 80)
        print("  三链融合能力综合评估测试")
        print("=" * 80)
        print(f"  评估维度: 3个")
        print()

        # ===== 维度1: 经典技术指标系统 =====
        print("  --- 维度1: 经典技术指标系统 ---")
        self.test_talib_module_structure()
        self.test_talib_indicators_rsi()
        self.test_talib_indicators_macd()
        self.test_talib_indicators_bbands()
        self.test_talib_indicators_atr_adx()
        self.test_talib_fallback_pure_python()
        self.test_frontend_bridge_api()
        self.test_pipeline_integration()
        self.test_complex_strategies()
        print()

        # ===== 维度2: 基本面分析系统 =====
        print("  --- 维度2: 基本面分析系统 ---")
        self.test_fundamental_engine_structure()
        self.test_sentiment_engine()
        self.test_signal_engine()
        self.test_least_resistance_3d()
        self.test_fundamental_api_endpoints()
        self.test_fundamental_extension_modules()
        self.test_fundamental_modularity()
        print()

        # ===== 维度3: 三链协同能力 =====
        print("  --- 维度3: 三链协同能力 ---")
        self.test_cross_chain_bridge()
        self.test_strategy_pipeline_flow()
        self.test_knowledge_library_integration()
        self.test_fallback_code_driven()
        print()

        # 生成报告
        self.generate_report()

    # ============================================================
    # 维度1: 经典技术指标系统
    # ============================================================

    def test_talib_module_structure(self):
        """检查talib模块结构完整性"""
        try:
            talib_path = Path(__file__).parent / "talib"
            has_init = (talib_path / "__init__.py").exists()
            has_abstract = (talib_path / "abstract.py").exists()

            # 检查指标数量
            indicators = []
            if has_abstract:
                import importlib.util
                spec = importlib.util.spec_from_file_location(
                    "talib.abstract", talib_path / "abstract.py"
                )
                module = importlib.util.module_from_spec(spec)
                sys.modules["talib"] = type(sys)("talib")
                sys.modules["talib.abstract"] = module
                spec.loader.exec_module(module)

                indicators = [
                    name for name in dir(module)
                    if name.isupper() and callable(getattr(module, name))
                ]

            score = 0
            checks = []
            if has_init:
                score += 20
                checks.append("__init__.py存在")
            if has_abstract:
                score += 30
                checks.append("abstract.py存在")
            if len(indicators) >= 5:
                score += 30
                checks.append(f"指标数量: {len(indicators)}个")
            if len(indicators) >= 10:
                score += 20
                checks.append("指标丰富度达标")

            self.add_result(TestResult(
                name="技术指标 - 模块结构",
                category="经典技术指标系统",
                passed=score >= 60,
                score=score,
                details=f"模块结构检查: {', '.join(checks)}",
                metrics={"指标数量": len(indicators), "检查项": len(checks)},
            ))
        except Exception as e:
            self.add_result(TestResult(
                name="技术指标 - 模块结构",
                category="经典技术指标系统",
                passed=False,
                score=0,
                details=f"模块结构检查失败: {str(e)}",
                error=str(e),
            ))

    def test_talib_indicators_rsi(self):
        """测试RSI指标计算"""
        try:
            import pandas as pd
            import numpy as np

            talib_path = Path(__file__).parent / "talib"
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "talib.abstract", talib_path / "abstract.py"
            )
            ta = importlib.util.module_from_spec(spec)
            sys.modules["talib"] = type(sys)("talib")
            sys.modules["talib.abstract"] = ta
            spec.loader.exec_module(ta)

            # 生成测试数据
            close = pd.Series([100 + i * 0.5 + (i % 3) * 0.3 for i in range(50)])
            df = pd.DataFrame({"close": close})

            rsi = ta.RSI(df, timeperiod=14)

            # 验证
            checks = []
            score = 0

            if len(rsi) == len(df):
                score += 30
                checks.append("长度匹配")
            if all(0 <= v <= 100 for v in rsi.dropna()):
                score += 30
                checks.append("范围正确(0-100)")
            if not rsi.isna().all():
                score += 20
                checks.append("有有效值")

            last_rsi = rsi.iloc[-1] if not rsi.isna().all() else 50
            if 30 <= last_rsi <= 70:
                score += 20
                checks.append("数值合理")

            self.add_result(TestResult(
                name="技术指标 - RSI",
                category="经典技术指标系统",
                passed=score >= 60,
                score=score,
                details=f"RSI指标: {', '.join(checks)}, 最新值={last_rsi:.2f}",
                metrics={"最新RSI": round(float(last_rsi), 2), "数据点": len(rsi)},
            ))
        except Exception as e:
            self.add_result(TestResult(
                name="技术指标 - RSI",
                category="经典技术指标系统",
                passed=False,
                score=0,
                details=f"RSI测试失败: {str(e)}",
                error=str(e),
            ))

    def test_talib_indicators_macd(self):
        """测试MACD指标计算"""
        try:
            import pandas as pd

            talib_path = Path(__file__).parent / "talib"
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "talib.abstract", talib_path / "abstract.py"
            )
            ta = importlib.util.module_from_spec(spec)
            sys.modules["talib"] = type(sys)("talib")
            sys.modules["talib.abstract"] = ta
            spec.loader.exec_module(ta)

            close = pd.Series([100 + i * 0.5 + (i % 5) * 0.8 for i in range(60)])
            df = pd.DataFrame({"close": close})

            macd_result = ta.MACD(df, fastperiod=12, slowperiod=26, signalperiod=9)

            checks = []
            score = 0

            if isinstance(macd_result, dict):
                score += 25
                checks.append("返回dict格式")
                if "macd" in macd_result:
                    score += 15
                    checks.append("包含macd线")
                if "macdsignal" in macd_result:
                    score += 15
                    checks.append("包含signal线")
                if "macdhist" in macd_result:
                    score += 15
                    checks.append("包含histogram")
                if len(macd_result.get("macd", [])) == len(df):
                    score += 30
                    checks.append("长度匹配")
            else:
                score = 40
                checks.append("返回tuple格式")

            self.add_result(TestResult(
                name="技术指标 - MACD",
                category="经典技术指标系统",
                passed=score >= 60,
                score=score,
                details=f"MACD指标: {', '.join(checks)}",
                metrics={"返回类型": type(macd_result).__name__},
            ))
        except Exception as e:
            self.add_result(TestResult(
                name="技术指标 - MACD",
                category="经典技术指标系统",
                passed=False,
                score=0,
                details=f"MACD测试失败: {str(e)}",
                error=str(e),
            ))

    def test_talib_indicators_bbands(self):
        """测试布林带指标计算"""
        try:
            import pandas as pd

            talib_path = Path(__file__).parent / "talib"
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "talib.abstract", talib_path / "abstract.py"
            )
            ta = importlib.util.module_from_spec(spec)
            sys.modules["talib"] = type(sys)("talib")
            sys.modules["talib.abstract"] = ta
            spec.loader.exec_module(ta)

            close = pd.Series([100 + i * 0.3 + (i % 4) * 1.2 for i in range(50)])
            df = pd.DataFrame({"close": close})

            bb = ta.BBANDS(df, timeperiod=20, nbdevup=2.0, nbdevdn=2.0)

            checks = []
            score = 0

            if isinstance(bb, dict):
                score += 20
                checks.append("返回dict格式")
                if all(k in bb for k in ["upperband", "middleband", "lowerband"]):
                    score += 30
                    checks.append("三条带完整")

                # 验证上轨 >= 中轨 >= 下轨
                last_upper = bb["upperband"].iloc[-1]
                last_mid = bb["middleband"].iloc[-1]
                last_lower = bb["lowerband"].iloc[-1]
                if last_upper >= last_mid >= last_lower:
                    score += 30
                    checks.append("轨道顺序正确")

                # 验证宽度
                width = (last_upper - last_lower) / last_mid if last_mid > 0 else 0
                if 0 < width < 0.5:
                    score += 20
                    checks.append("带宽合理")
            else:
                score = 50
                checks.append("返回tuple格式")

            self.add_result(TestResult(
                name="技术指标 - 布林带",
                category="经典技术指标系统",
                passed=score >= 60,
                score=score,
                details=f"布林带: {', '.join(checks)}",
                metrics={"上轨": round(float(last_upper), 2),
                         "中轨": round(float(last_mid), 2),
                         "下轨": round(float(last_lower), 2)},
            ))
        except Exception as e:
            self.add_result(TestResult(
                name="技术指标 - 布林带",
                category="经典技术指标系统",
                passed=False,
                score=0,
                details=f"布林带测试失败: {str(e)}",
                error=str(e),
            ))

    def test_talib_indicators_atr_adx(self):
        """测试ATR和ADX指标"""
        try:
            import pandas as pd

            talib_path = Path(__file__).parent / "talib"
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "talib.abstract", talib_path / "abstract.py"
            )
            ta = importlib.util.module_from_spec(spec)
            sys.modules["talib"] = type(sys)("talib")
            sys.modules["talib.abstract"] = ta
            spec.loader.exec_module(ta)

            df = pd.DataFrame({
                "high": [100 + i * 0.5 + (i % 3) * 1.0 for i in range(50)],
                "low": [98 + i * 0.5 - (i % 3) * 0.5 for i in range(50)],
                "close": [99 + i * 0.5 + (i % 4) * 0.3 for i in range(50)],
                "volume": [1000 + i * 10 for i in range(50)],
            })

            atr = ta.ATR(df, timeperiod=14)
            adx = ta.ADX(df, timeperiod=14)

            checks = []
            score = 0

            if len(atr) == len(df):
                score += 20
                checks.append("ATR长度匹配")
            if all(v >= 0 for v in atr.dropna()):
                score += 15
                checks.append("ATR非负")
            if len(adx) == len(df):
                score += 20
                checks.append("ADX长度匹配")
            if all(0 <= v <= 100 for v in adx.dropna()):
                score += 15
                checks.append("ADX范围正确(0-100)")

            last_atr = atr.iloc[-1] if not atr.isna().all() else 0
            last_adx = adx.iloc[-1] if not adx.isna().all() else 0
            if last_atr > 0:
                score += 15
                checks.append("ATR有效值")
            if last_adx > 0:
                score += 15
                checks.append("ADX有效值")

            self.add_result(TestResult(
                name="技术指标 - ATR/ADX",
                category="经典技术指标系统",
                passed=score >= 60,
                score=score,
                details=f"ATR/ADX: {', '.join(checks)}",
                metrics={"最新ATR": round(float(last_atr), 4),
                         "最新ADX": round(float(last_adx), 2)},
            ))
        except Exception as e:
            self.add_result(TestResult(
                name="技术指标 - ATR/ADX",
                category="经典技术指标系统",
                passed=False,
                score=0,
                details=f"ATR/ADX测试失败: {str(e)}",
                error=str(e),
            ))

    def test_talib_fallback_pure_python(self):
        """测试纯Python回退模式（无talib依赖）"""
        try:
            import pandas as pd

            talib_path = Path(__file__).parent / "talib"
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "talib.abstract", talib_path / "abstract.py"
            )
            ta = importlib.util.module_from_spec(spec)
            sys.modules["talib"] = type(sys)("talib")
            sys.modules["talib.abstract"] = ta
            spec.loader.exec_module(ta)

            # 测试所有公开的大写函数
            indicators = [
                name for name in dir(ta)
                if name.isupper() and callable(getattr(ta, name))
            ]

            df = pd.DataFrame({
                "open": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
                "high": [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16],
                "low": [0.5, 1.5, 2.5, 3.0, 4.0, 5.0, 6.2, 7.1, 8.2, 9.1, 10.1, 11.1, 12.1, 13.1, 14.1],
                "close": [1.2, 2.2, 3.3, 4.2, 5.1, 6.0, 6.8, 7.9, 8.7, 9.8, 10.5, 11.3, 12.4, 13.2, 14.3],
                "volume": [10, 12, 11, 15, 14, 16, 15, 13, 18, 20, 22, 19, 21, 23, 25],
            })

            success_count = 0
            failed = []

            for ind_name in indicators:
                try:
                    func = getattr(ta, ind_name)
                    result = func(df)
                    if result is not None:
                        success_count += 1
                except Exception:
                    failed.append(ind_name)

            total = len(indicators)
            score = int((success_count / max(total, 1)) * 100)

            self.add_result(TestResult(
                name="技术指标 - 纯Python回退",
                category="经典技术指标系统",
                passed=score >= 70,
                score=score,
                details=f"纯Python回退模式: {success_count}/{total}个指标可运行, 失败: {', '.join(failed) if failed else '无'}",
                metrics={"成功数": success_count, "总数": total,
                         "失败指标": ", ".join(failed) if failed else "无"},
            ))
        except Exception as e:
            self.add_result(TestResult(
                name="技术指标 - 纯Python回退",
                category="经典技术指标系统",
                passed=False,
                score=0,
                details=f"回退模式测试失败: {str(e)}",
                error=str(e),
            ))

    def test_frontend_bridge_api(self):
        """检查前端桥接层API设计"""
        try:
            frontend_path = Path(__file__).parent / "frontend" / "src" / "lib"
            bridge_file = frontend_path / "classic-system-bridge.ts"
            pipeline_file = frontend_path / "classic-system-pipeline.ts"

            score = 0
            checks = []

            if bridge_file.exists():
                score += 30
                checks.append("bridge.ts存在")

                content = bridge_file.read_text()
                if "transformToClassicDraft" in content:
                    score += 20
                    checks.append("Draft转换函数")
                if "generateGateResult" in content:
                    score += 15
                    checks.append("Gate评估函数")
                if "S1ResearchOutput" in content and "S3DesignOutput" in content:
                    score += 15
                    checks.append("S链类型定义完整")

            if pipeline_file.exists():
                score += 20
                checks.append("pipeline.ts存在")

            self.add_result(TestResult(
                name="技术指标 - 前端桥接",
                category="经典技术指标系统",
                passed=score >= 60,
                score=score,
                details=f"前端桥接层: {', '.join(checks)}",
                metrics={"检查项数": len(checks)},
            ))
        except Exception as e:
            self.add_result(TestResult(
                name="技术指标 - 前端桥接",
                category="经典技术指标系统",
                passed=False,
                score=0,
                details=f"桥接层检查失败: {str(e)}",
                error=str(e),
            ))

    def test_pipeline_integration(self):
        """测试策略pipeline集成度"""
        try:
            pipeline_file = Path(__file__).parent / "frontend" / "src" / "lib" / "classic-system-pipeline.ts"

            score = 0
            checks = []

            if pipeline_file.exists():
                content = pipeline_file.read_text()

                stages = ["DRAFT", "GATE", "APPROVAL", "APPLY", "AUDIT"]
                stage_count = sum(1 for s in stages if s in content)
                score += int(stage_count / len(stages) * 30)
                checks.append(f"治理阶段: {stage_count}/{len(stages)}")

                if "StrategyLibraryAPI" in content:
                    score += 20
                    checks.append("策略库API")
                if "BacktestAPI" in content:
                    score += 20
                    checks.append("回测API")
                if "SystemMonitorAPI" in content:
                    score += 15
                    checks.append("系统监控API")
                if "runStrategyPipeline" in content:
                    score += 15
                    checks.append("完整pipeline函数")

            self.add_result(TestResult(
                name="技术指标 - Pipeline集成",
                category="经典技术指标系统",
                passed=score >= 60,
                score=score,
                details=f"Pipeline集成: {', '.join(checks)}",
                metrics={"集成模块数": len(checks)},
            ))
        except Exception as e:
            self.add_result(TestResult(
                name="技术指标 - Pipeline集成",
                category="经典技术指标系统",
                passed=False,
                score=0,
                details=f"Pipeline集成检查失败: {str(e)}",
                error=str(e),
            ))

    def test_complex_strategies(self):
        """测试复杂策略系统支持"""
        try:
            service_file = Path(__file__).parent / "ml_trade_service.py"

            score = 0
            checks = []
            strategies = []

            if service_file.exists():
                content = service_file.read_text()

                # 检查复杂策略定义
                strategy_patterns = [
                    ("Strategy005", "趋势策略"),
                    ("BreakoutStrategy", "突破策略"),
                    ("ThreeScreen", "三屏策略"),
                    ("RegimeHybridStrategy", "混合状态策略"),
                    ("MultiGroupStrategy", "多组策略"),
                    ("Bot2Strategy", "Bot2自适应策略"),
                    ("OttStrategy", "OTT策略"),
                ]

                found_strategies = 0
                for pattern, name in strategy_patterns:
                    if pattern in content:
                        found_strategies += 1
                        strategies.append(name)

                if found_strategies >= 4:
                    score += 30
                    checks.append(f"复杂策略: {found_strategies}个")

                # 检查策略家族
                families = ["trend", "mean_reversion", "carry", "breakout"]
                found_families = sum(1 for f in families if f'"family": "{f}"' in content.lower())
                if found_families >= 2:
                    score += 20
                    checks.append(f"策略家族: {found_families}类")

                # 检查策略阶段
                stages = ["research", "model", "deployment"]
                found_stages = sum(1 for s in stages if s in content)
                if found_stages >= 2:
                    score += 20
                    checks.append(f"策略阶段: {found_stages}级")

                # 检查策略生命周期
                lifecycle = ["approved", "deployed", "deprecated"]
                found_lifecycle = sum(1 for l in lifecycle if l in content)
                if found_lifecycle >= 2:
                    score += 15
                    checks.append(f"生命周期: {found_lifecycle}状态")

                # 检查策略注册API
                if "/strategy/registry" in content:
                    score += 15
                    checks.append("策略注册API")

            self.add_result(TestResult(
                name="技术指标 - 复杂策略支持",
                category="经典技术指标系统",
                passed=score >= 60,
                score=score,
                details=f"复杂策略: {', '.join(checks) if checks else '未找到'}",
                metrics={"策略数量": len(strategies), "策略列表": ", ".join(strategies)},
            ))
        except Exception as e:
            self.add_result(TestResult(
                name="技术指标 - 复杂策略支持",
                category="经典技术指标系统",
                passed=False,
                score=0,
                details=f"复杂策略检查失败: {str(e)}",
                error=str(e),
            ))

    # ============================================================
    # 维度2: 基本面分析系统
    # ============================================================

    def test_fundamental_engine_structure(self):
        """检查基本面引擎模块结构"""
        try:
            engines_path = Path(__file__).parent.parent / "9-基本面分析" / "engines"

            score = 0
            checks = []
            engines = []

            if engines_path.exists():
                init_file = engines_path / "__init__.py"
                if init_file.exists():
                    score += 20
                    checks.append("__init__.py存在")

                engine_files = list(engines_path.glob("*.py"))
                engine_names = [f.stem for f in engine_files if f.stem != "__init__"]
                engines = engine_names

                if len(engine_names) >= 2:
                    score += 30
                    checks.append(f"引擎数量: {len(engine_names)}个")
                if "signal_engine" in engine_names:
                    score += 15
                    checks.append("信号引擎")
                if "sentiment_engine" in engine_names:
                    score += 15
                    checks.append("情绪引擎")
                if "least_resistance" in engine_names:
                    score += 20
                    checks.append("三维度引擎")
            else:
                # 尝试从backend导入
                pass

            self.add_result(TestResult(
                name="基本面 - 引擎结构",
                category="基本面分析系统",
                passed=score >= 60,
                score=score,
                details=f"引擎模块: {', '.join(checks)}",
                metrics={"引擎列表": ", ".join(engines) if engines else "未找到"},
            ))
        except Exception as e:
            self.add_result(TestResult(
                name="基本面 - 引擎结构",
                category="基本面分析系统",
                passed=False,
                score=0,
                details=f"引擎结构检查失败: {str(e)}",
                error=str(e),
            ))

    def test_sentiment_engine(self):
        """测试情绪分析引擎"""
        try:
            engines_path = Path(__file__).parent.parent / "9-基本面分析" / "engines"
            sys.path.insert(0, str(engines_path.parent))

            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "sentiment_engine", engines_path / "sentiment_engine.py"
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            engine = module.SentimentEngine()

            # 测试正面文本
            pos_result = engine.analyze_text(
                "Bitcoin突破新高，机构资金大量流入，市场看涨情绪浓厚"
            )
            # 测试负面文本
            neg_result = engine.analyze_text(
                "监管政策收紧，交易所被调查，市场恐慌抛售加剧"
            )
            # 测试中性文本
            neu_result = engine.analyze_text("今日市场横盘整理，交易量平稳")

            score = 0
            checks = []

            if pos_result.get("sentiment") == "positive" or pos_result.get("score", 0) > 0:
                score += 30
                checks.append("正面情绪识别")
            if neg_result.get("sentiment") == "negative" or neg_result.get("score", 0) < 0:
                score += 30
                checks.append("负面情绪识别")
            if isinstance(neu_result.get("categories"), list):
                score += 20
                checks.append("分类功能正常")
            if "matches" in pos_result:
                score += 20
                checks.append("关键词匹配返回")

            self.add_result(TestResult(
                name="基本面 - 情绪引擎",
                category="基本面分析系统",
                passed=score >= 60,
                score=score,
                details=f"情绪引擎: {', '.join(checks)}",
                metrics={"正面得分": round(float(pos_result.get('score', 0)), 3),
                         "负面得分": round(float(neg_result.get('score', 0)), 3),
                         "正面分类数": len(pos_result.get('categories', []))},
            ))
        except Exception as e:
            self.add_result(TestResult(
                name="基本面 - 情绪引擎",
                category="基本面分析系统",
                passed=False,
                score=0,
                details=f"情绪引擎测试失败: {str(e)}",
                error=str(e),
            ))

    def test_signal_engine(self):
        """测试信号生成引擎"""
        try:
            engines_path = Path(__file__).parent.parent / "9-基本面分析" / "engines"
            sys.path.insert(0, str(engines_path.parent))

            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "signal_engine", engines_path / "signal_engine.py"
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            engine = module.SignalEngine()

            resistance_3d = {
                "direction": "up",
                "direction_score": 0.6,
                "velocity": 0.4,
                "acceleration": 0.2,
                "confidence": 0.75,
            }

            metrics = {
                "flow_score": 0.65,
                "sentiment_score": 0.55,
                "breadth_score": 0.7,
            }

            signals = engine.generate_signals(resistance_3d, metrics)

            score = 0
            checks = []

            if isinstance(signals, list):
                score += 30
                checks.append("返回信号列表")
            if len(signals) > 0:
                score += 30
                checks.append(f"生成{len(signals)}个信号")
            if all("type" in s for s in signals[:3]):
                score += 20
                checks.append("信号类型字段完整")
            if all("strength" in s or "confidence" in s for s in signals[:3]):
                score += 20
                checks.append("信号强度字段完整")

            self.add_result(TestResult(
                name="基本面 - 信号引擎",
                category="基本面分析系统",
                passed=score >= 60,
                score=score,
                details=f"信号引擎: {', '.join(checks)}",
                metrics={"信号数量": len(signals),
                         "信号类型": ", ".join(s.get('type', '?') for s in signals[:3])},
            ))
        except Exception as e:
            self.add_result(TestResult(
                name="基本面 - 信号引擎",
                category="基本面分析系统",
                passed=False,
                score=0,
                details=f"信号引擎测试失败: {str(e)}",
                error=str(e),
            ))

    def test_least_resistance_3d(self):
        """测试三维度阻力分析"""
        try:
            engines_path = Path(__file__).parent.parent / "9-基本面分析" / "engines"
            sys.path.insert(0, str(engines_path.parent))

            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "least_resistance", engines_path / "least_resistance.py"
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # 测试上升趋势
            hist_up = [0.1, 0.2, 0.3, 0.4, 0.5]
            result_up = module.compute_resistance_3d(0.6, hist_up)

            # 测试下降趋势
            hist_down = [0.5, 0.4, 0.3, 0.2, 0.1]
            result_down = module.compute_resistance_3d(-0.5, hist_down)

            score = 0
            checks = []

            required_fields = ["direction", "velocity", "acceleration", "confidence"]
            if all(f in result_up for f in required_fields):
                score += 30
                checks.append("三维度字段完整")
            if result_up.get("direction") == "up":
                score += 20
                checks.append("上升方向识别正确")
            if result_down.get("direction") == "down":
                score += 20
                checks.append("下降方向识别正确")
            if 0 <= result_up.get("confidence", 0) <= 1:
                score += 15
                checks.append("置信度范围正确")
            if "trend_summary" in result_up:
                score += 15
                checks.append("趋势摘要生成")

            self.add_result(TestResult(
                name="基本面 - 三维度分析",
                category="基本面分析系统",
                passed=score >= 60,
                score=score,
                details=f"三维度引擎: {', '.join(checks)}",
                metrics={"上升方向": result_up.get('direction', '?'),
                         "下降方向": result_down.get('direction', '?'),
                         "上升置信度": round(float(result_up.get('confidence', 0)), 3)},
            ))
        except Exception as e:
            self.add_result(TestResult(
                name="基本面 - 三维度分析",
                category="基本面分析系统",
                passed=False,
                score=0,
                details=f"三维度测试失败: {str(e)}",
                error=str(e),
            ))

    def test_fundamental_api_endpoints(self):
        """检查基本面API端点覆盖"""
        try:
            backend_path = Path(__file__).parent.parent / "9-基本面分析" / "backend" / "src"
            service_file = backend_path / "ml_trade_service.py"

            score = 0
            checks = []
            endpoints = []

            if service_file.exists():
                content = service_file.read_text()
                # 同时检查嵌入的源文件
                embedded_file = backend_path / "_embedded_ml_trade_service_source.py"
                if embedded_file.exists():
                    content += embedded_file.read_text()

                # 查找基本面相关API
                api_patterns = [
                    ("/fundamental/flows/brief", "资金流简报"),
                    ("/fundamental/narrative/brief", "叙事简报"),
                    ("/fundamental/trading/latest", "交易信号"),
                    ("/fundamental/overview/latest", "概览数据"),
                    ("/fundamental/news/gate_briefing", "新闻简报"),
                    ("/carry/status", "Carry交易状态"),
                    ("/carry/candidates", "Carry候选"),
                ]

                found = 0
                for pattern, name in api_patterns:
                    if pattern in content:
                        found += 1
                        endpoints.append(name)

                score = int((found / len(api_patterns)) * 100)
                checks.append(f"API覆盖: {found}/{len(api_patterns)}")

            self.add_result(TestResult(
                name="基本面 - API端点",
                category="基本面分析系统",
                passed=score >= 60,
                score=score,
                details=f"API端点: {', '.join(endpoints) if endpoints else '未找到'}",
                metrics={"端点数量": len(endpoints), "端点列表": ", ".join(endpoints)},
            ))
        except Exception as e:
            self.add_result(TestResult(
                name="基本面 - API端点",
                category="基本面分析系统",
                passed=False,
                score=0,
                details=f"API检查失败: {str(e)}",
                error=str(e),
            ))

    def test_fundamental_extension_modules(self):
        """检查基本面扩展模块（宏观/链上/叙事/新闻等）"""
        try:
            backend_path = Path(__file__).parent.parent / "9-基本面分析" / "backend" / "src"
            embedded_file = backend_path / "_embedded_ml_trade_service_source.py"

            score = 0
            checks = []
            modules = {}

            if embedded_file.exists():
                content = embedded_file.read_text()

                # 1. 宏观分析模块 (Macro)
                macro_apis = [
                    "/macro/series/trend", "/macro/btc/dir", "/macro/series/energy",
                    "/macro/series/flow", "/macro/btceth/overview", "/macro/gate/eval"
                ]
                macro_count = sum(1 for api in macro_apis if api in content)
                if macro_count >= 3:
                    score += 20
                    checks.append(f"宏观模块: {macro_count}个API")
                    modules["macro"] = macro_count

                # 2. 资金流模块 (Flow)
                flow_apis = [
                    "/fundamental/flows/brief", "/fundamental/flows/regime",
                    "/fundamental/flows/explain", "/fundamental/flows/min_resistance"
                ]
                flow_count = sum(1 for api in flow_apis if api in content)
                if flow_count >= 2:
                    score += 20
                    checks.append(f"资金流模块: {flow_count}个API")
                    modules["flow"] = flow_count

                # 3. 叙事分析模块 (Narrative)
                narrative_apis = [
                    "/fundamental/narrative/brief", "/fundamental/narrative/registry",
                    "/fundamental/narrative/automation"
                ]
                narrative_count = sum(1 for api in narrative_apis if api in content)
                if narrative_count >= 2:
                    score += 20
                    checks.append(f"叙事模块: {narrative_count}个API")
                    modules["narrative"] = narrative_count

                # 4. 新闻分析模块 (News)
                news_apis = [
                    "/fundamental/news/brief", "/fundamental/news/event_ledger",
                    "/fundamental/news/risk_action", "/fundamental/news/anchor_delta"
                ]
                news_count = sum(1 for api in news_apis if api in content)
                if news_count >= 2:
                    score += 20
                    checks.append(f"新闻模块: {news_count}个API")
                    modules["news"] = news_count

                # 5. Web3/链上模块
                web3_apis = [
                    "/automation/web3/market_digest", "/automation/web3/market_digest/freq_filter"
                ]
                web3_count = sum(1 for api in web3_apis if api in content)
                if web3_count >= 1:
                    score += 10
                    checks.append(f"Web3模块: {web3_count}个API")
                    modules["web3"] = web3_count

                # 6. 传统金融分析
                if "traditional_finance" in content.lower() or "格雷厄姆" in content or "价值投资" in content:
                    score += 10
                    checks.append("传统金融分析框架")
                    modules["traditional_finance"] = 1

            # 检查扩展模块脚本
            scripts_path = Path(__file__).parent.parent / "9-基本面分析" / "ops" / "nanoclaw" / "core_task1" / "scripts"
            if scripts_path.exists():
                script_files = list(scripts_path.glob("*.py"))
                script_names = [f.stem for f in script_files]

                # 检查关键脚本
                key_scripts = ["flow_brief_generator", "narrative_analyzer", "news_crawler",
                              "traditional_finance_analyzer", "regime_classifier", "signal_fusion"]
                found_scripts = [s for s in key_scripts if any(s in name for name in script_names)]
                if len(found_scripts) >= 4:
                    score += 10
                    checks.append(f"扩展脚本: {len(found_scripts)}个")
                    modules["scripts"] = len(found_scripts)

            # 检查schema定义
            schema_path = Path(__file__).parent.parent / "9-基本面分析" / "ops" / "nanoclaw" / "core_task1" / "schema"
            if schema_path.exists():
                schema_files = list(schema_path.glob("*.json"))
                if len(schema_files) >= 4:
                    score += 10
                    checks.append(f"数据契约: {len(schema_files)}个")
                    modules["schemas"] = len(schema_files)

            self.add_result(TestResult(
                name="基本面 - 扩展模块",
                category="基本面分析系统",
                passed=score >= 60,
                score=min(score, 100),
                details=f"扩展模块: {', '.join(checks) if checks else '未找到'}",
                metrics={"模块总数": len(modules), "详细": modules},
            ))
        except Exception as e:
            self.add_result(TestResult(
                name="基本面 - 扩展模块",
                category="基本面分析系统",
                passed=False,
                score=0,
                details=f"扩展模块检查失败: {str(e)}",
                error=str(e),
            ))

    def test_fundamental_modularity(self):
        """检查基本面系统模块化设计"""
        try:
            base_path = Path(__file__).parent.parent / "9-基本面分析"

            score = 0
            checks = []

            # 检查目录结构
            dirs = ["engines", "backend", "tests", "ops", "skills"]
            found_dirs = [d for d in dirs if (base_path / d).exists()]
            score += int(len(found_dirs) / len(dirs) * 30)
            checks.append(f"模块目录: {len(found_dirs)}/{len(dirs)}")

            # 检查测试覆盖
            tests_path = base_path / "tests"
            if tests_path.exists():
                test_files = list(tests_path.glob("test_*.py"))
                if len(test_files) >= 5:
                    score += 25
                    checks.append(f"测试文件: {len(test_files)}个")
                else:
                    score += 10
                    checks.append(f"测试文件: {len(test_files)}个")

            # 检查配置
            if (base_path / "requirements.txt").exists():
                score += 15
                checks.append("依赖声明")

            # 检查文档
            docs = list(base_path.glob("*.md"))
            if len(docs) >= 2:
                score += 15
                checks.append(f"文档: {len(docs)}份")
            else:
                score += 5

            # 检查skill合约
            skills_path = base_path / "skills" / "contracts"
            if skills_path.exists():
                contracts = list(skills_path.glob("*.json"))
                if len(contracts) >= 2:
                    score += 15
                    checks.append(f"Skill合约: {len(contracts)}个")

            self.add_result(TestResult(
                name="基本面 - 模块化设计",
                category="基本面分析系统",
                passed=score >= 60,
                score=score,
                details=f"模块化: {', '.join(checks)}",
                metrics={"模块目录数": len(found_dirs),
                         "测试文件数": len(test_files) if tests_path.exists() else 0,
                         "文档数": len(docs)},
            ))
        except Exception as e:
            self.add_result(TestResult(
                name="基本面 - 模块化设计",
                category="基本面分析系统",
                passed=False,
                score=0,
                details=f"模块化检查失败: {str(e)}",
                error=str(e),
            ))

    # ============================================================
    # 维度3: 三链协同能力
    # ============================================================

    def test_cross_chain_bridge(self):
        """测试跨链桥接能力"""
        try:
            frontend_lib = Path(__file__).parent / "frontend" / "src" / "lib"
            bridge_file = frontend_lib / "classic-system-bridge.ts"

            score = 0
            checks = []

            if bridge_file.exists():
                content = bridge_file.read_text()

                # S链输入接口
                s_interfaces = ["S1ResearchOutput", "S2AnalysisOutput",
                                "S3DesignOutput", "S4ValidateOutput", "S5ExecuteOutput"]
                s_count = sum(1 for s in s_interfaces if s in content)
                score += int(s_count / len(s_interfaces) * 30)
                checks.append(f"S链接口: {s_count}/{len(s_interfaces)}")

                # Classic系统输出
                classic_patterns = ["ClassicDraftPayload", "transformToClassicDraft",
                                   "generateGateResult", "generateEvidence"]
                c_count = sum(1 for p in classic_patterns if p in content)
                score += int(c_count / len(classic_patterns) * 30)
                checks.append(f"转换函数: {c_count}/{len(classic_patterns)}")

                # 审计溯源
                if "doc_refs" in content and "evidence" in content:
                    score += 20
                    checks.append("审计溯源支持")

                # 回测配置
                if "generateBacktestConfig" in content:
                    score += 20
                    checks.append("回测配置生成")

            self.add_result(TestResult(
                name="三链协同 - 跨链桥接",
                category="三链协同能力",
                passed=score >= 60,
                score=score,
                details=f"跨链桥接: {', '.join(checks)}",
                metrics={"S链接口数": s_count, "转换函数数": c_count},
            ))
        except Exception as e:
            self.add_result(TestResult(
                name="三链协同 - 跨链桥接",
                category="三链协同能力",
                passed=False,
                score=0,
                details=f"跨链桥接测试失败: {str(e)}",
                error=str(e),
            ))

    def test_strategy_pipeline_flow(self):
        """测试策略治理流程完整性"""
        try:
            pipeline_file = Path(__file__).parent / "frontend" / "src" / "lib" / "classic-system-pipeline.ts"

            score = 0
            checks = []

            if pipeline_file.exists():
                content = pipeline_file.read_text()

                # 五阶段治理
                stages = ["pushStrategyDraft", "runGateEval", "requestApproval",
                         "applyChangeset", "recordAudit"]
                stage_count = sum(1 for s in stages if s in content)
                score += int(stage_count / len(stages) * 40)
                checks.append(f"治理阶段: {stage_count}/{len(stages)}")

                # 完整pipeline
                if "runStrategyPipeline" in content:
                    score += 20
                    checks.append("完整编排函数")

                # 策略知识库
                if "StrategyLibraryAPI" in content:
                    score += 15
                    checks.append("策略知识库")

                # 回测集成
                if "BacktestAPI" in content:
                    score += 15
                    checks.append("回测集成")

                # 系统监控
                if "SystemMonitorAPI" in content:
                    score += 10
                    checks.append("系统监控")

            self.add_result(TestResult(
                name="三链协同 - 治理流程",
                category="三链协同能力",
                passed=score >= 60,
                score=score,
                details=f"治理流程: {', '.join(checks)}",
                metrics={"阶段数": stage_count, "集成模块数": len(checks)},
            ))
        except Exception as e:
            self.add_result(TestResult(
                name="三链协同 - 治理流程",
                category="三链协同能力",
                passed=False,
                score=0,
                details=f"治理流程测试失败: {str(e)}",
                error=str(e),
            ))

    def test_knowledge_library_integration(self):
        """测试策略库作为知识库的能力"""
        try:
            pipeline_file = Path(__file__).parent / "frontend" / "src" / "lib" / "classic-system-pipeline.ts"

            score = 0
            checks = []

            if pipeline_file.exists():
                content = pipeline_file.read_text()

                library_methods = ["listStrategies", "getStrategy",
                                   "getStrategyConfig", "previewStrategyParams"]
                m_count = sum(1 for m in library_methods if m in content)
                score += int(m_count / len(library_methods) * 50)
                checks.append(f"知识库方法: {m_count}/{len(library_methods)}")

                # 查询参数
                if "scope" in content and "status" in content and "search" in content:
                    score += 25
                    checks.append("多维查询支持")

                # 预览功能
                if "previewStrategyParams" in content:
                    score += 25
                    checks.append("参数预览")

            self.add_result(TestResult(
                name="三链协同 - 知识库集成",
                category="三链协同能力",
                passed=score >= 60,
                score=score,
                details=f"知识库: {', '.join(checks)}",
                metrics={"方法数": m_count},
            ))
        except Exception as e:
            self.add_result(TestResult(
                name="三链协同 - 知识库集成",
                category="三链协同能力",
                passed=False,
                score=0,
                details=f"知识库测试失败: {str(e)}",
                error=str(e),
            ))

    def test_fallback_code_driven(self):
        """测试纯代码驱动回退模式"""
        try:
            talib_path = Path(__file__).parent / "talib"
            engines_path = Path(__file__).parent.parent / "9-基本面分析" / "engines"

            score = 0
            checks = []

            # talib纯Python回退
            abstract_file = talib_path / "abstract.py"
            if abstract_file.exists():
                content = abstract_file.read_text()
                if "import numpy" in content and "import pandas" in content:
                    score += 30
                    checks.append("talib纯Python实现")
                if "def RSI(" in content and "def MACD(" in content:
                    score += 15
                    checks.append("核心指标自实现")

            # 基本面引擎纯代码
            if (engines_path / "sentiment_engine.py").exists():
                score += 15
                checks.append("情绪引擎纯代码")
            if (engines_path / "signal_engine.py").exists():
                score += 15
                checks.append("信号引擎纯代码")
            if (engines_path / "least_resistance.py").exists():
                score += 15
                checks.append("三维度引擎纯代码")

            # 无LLM依赖验证
            backend_path = Path(__file__).parent.parent / "9-基本面分析" / "backend" / "src"
            if (backend_path / "carry_service.py").exists():
                score += 10
                checks.append("Carry服务纯代码")

            self.add_result(TestResult(
                name="三链协同 - 纯代码回退",
                category="三链协同能力",
                passed=score >= 60,
                score=score,
                details=f"纯代码回退: {', '.join(checks)}",
                metrics={"回退模块数": len(checks)},
            ))
        except Exception as e:
            self.add_result(TestResult(
                name="三链协同 - 纯代码回退",
                category="三链协同能力",
                passed=False,
                score=0,
                details=f"回退模式测试失败: {str(e)}",
                error=str(e),
            ))

    # ============================================================
    # 报告生成
    # ============================================================

    def generate_report(self):
        categories = {}
        for r in self.results:
            if r.category not in categories:
                categories[r.category] = []
            categories[r.category].append(r)

        # 权重配置
        weights = {
            "经典技术指标系统": 0.35,
            "基本面分析系统": 0.35,
            "三链协同能力": 0.30,
        }

        total_score = 0
        category_scores = {}

        for cat, cat_results in categories.items():
            avg_score = sum(r.score for r in cat_results) / len(cat_results)
            category_scores[cat] = round(avg_score, 1)
            weight = weights.get(cat, 0.25)
            total_score += avg_score * weight

        total_score = round(total_score, 1)
        duration = round(time.time() - self.start_time, 2)

        print()
        print("=" * 80)
        print("  三链融合能力综合评估报告")
        print("=" * 80)
        print(f"  评估时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  测试用时: {duration}秒")
        print()
        print(f"  综合评分: {total_score} / 100")
        print(f"  测试用例: {len(self.results)}个")
        print(f"  通过用例: {sum(1 for r in self.results if r.passed)}个")
        print()

        print("-" * 80)
        print("  各维度得分")
        print("-" * 80)
        for cat, score in sorted(category_scores.items(), key=lambda x: -x[1]):
            cat_results = categories[cat]
            passed = sum(1 for r in cat_results if r.passed)
            bar_len = int(score / 5)
            bar = "█" * bar_len + " " * (20 - bar_len)
            weight = weights.get(cat, 0) * 100
            print(f"  {cat:<20s} [{bar}] {score:>3.0f}分 (权重{weight:.0f}%)")
            print(f"    测试项: {len(cat_results)}个, 通过{passed}个")

        print()
        print("-" * 80)
        print("  详细测试结果")
        print("-" * 80)

        for cat in ["经典技术指标系统", "基本面分析系统", "三链协同能力"]:
            if cat in categories:
                print()
                print(f"  ▸ {cat}:")
                for r in categories[cat]:
                    status = "✓" if r.passed else "✗"
                    bar_len = int(r.score / 10)
                    bar = "█" * bar_len + " " * (10 - bar_len)
                    print(f"    {status} {r.name:<30s} [{bar}] {r.score:>3d}分")
                    print(f"       {r.details}")

        # 优势与建议
        print()
        print("-" * 80)
        print("  ✅ 优势")
        print("-" * 80)

        strengths = []
        for cat, score in category_scores.items():
            if score >= 80:
                strengths.append(f"  • {cat}: {score:.0f}分 - 表现优秀")
            elif score >= 60:
                strengths.append(f"  • {cat}: {score:.0f}分 - 表现良好")

        for s in strengths:
            print(s)

        print()
        print("-" * 80)
        print("  💡 优化建议")
        print("-" * 80)

        weak_cats = [(cat, score) for cat, score in category_scores.items() if score < 80]
        if weak_cats:
            for i, (cat, score) in enumerate(sorted(weak_cats, key=lambda x: x[1])):
                weak_tests = [r.name for r in categories[cat] if not r.passed or r.score < 70]
                print(f"  {i+1}. 优先改进 {cat} ({score:.0f}分)")
                if weak_tests:
                    print(f"     薄弱项: {', '.join(weak_tests[:3])}")
        else:
            print("  系统整体表现良好，可考虑增加更多高级功能")

        print()
        print("=" * 80)
        print(f"  评估完成 | 总分: {total_score}/100")
        print("=" * 80)

        return total_score


def main():
    evaluator = ThreeChainEvaluator()
    evaluator.run_all()
    return 0


if __name__ == "__main__":
    sys.exit(main())
