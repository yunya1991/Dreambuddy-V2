#!/usr/bin/env python3
"""
贝叶斯参数优化模块 - 马丁策略资金管理器专用

核心策略：底仓现货思维 + 黑天鹅加仓 + 动态止损
- 底仓22%资金 + 5倍杠杆 ≈ 110%现货敞口（平时略占优，有止盈机制）
- 加仓间距保持不变（8%基准），用于黑天鹅时拉低成本
- 止盈固定4%（BTC基准，其他币种按波动率放大）
- 动态止损：日线/周线MA200、EMA200提供保护，无需额外趋势过滤

优化参数（6个）：
- addon1_pct: 加仓1资金比例 (5%-20%)
- addon2_pct: 加仓2资金比例 (5%-25%)
- addon3_pct: 加仓3资金比例 (10%-30%)
- max_concurrent_positions: 可开仓数量 (2-6)
- max_base_holding_hours: 底仓最大持仓时间 (24-96h)
- max_post_addon_hours: 加仓后最大持仓时间 (12-48h)
- golden_window_hours: 黑天鹅反弹黄金窗口 (4-24h)

固定参数：
- base_position_pct: 22%（底仓）
- leverage: 5x（杠杆）
- tp_pct_btc: 4%（BTC止盈，其他币种按波动率放大）
- trend_filter_mode: none（趋势过滤已禁用，动态止损提供保护）

优化目标：
1. 回撤控制（最高权重）：资金管理+动态止损最小化回撤
2. 资金效率：加仓资金不闲置，但也留足弹药
3. 收益：在控制回撤的前提下追求收益
"""
import json
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).parent       # lib/ 目录
STRATEGY_DIR = BASE_DIR.parent          # 14-V15经典马丁策略/ 目录

try:
    import numpy as np
except ImportError:
    raise ImportError("需要安装 numpy 库: pip install numpy")

try:
    from bayes_opt import BayesianOptimization
except ImportError:
    raise ImportError("需要安装 bayesian-optimization 库: pip install bayesian-optimization")

from config_loader import get_config_int, get_config_float


def load_backtest_module():
    import sys
    core_path = str(STRATEGY_DIR / "core")
    if core_path not in sys.path:
        sys.path.insert(0, core_path)
    import v15_backtest
    return v15_backtest


class V15CapitalOptimizer:
    # ── 版本1: 固定参数基线（纯马丁策略，无智能增强，138%收益）──
    # 止盈4%/底仓22%/加仓3次/间隔8%，无ATR/移动止盈/ELDER-RAY/风向标
    # 作为智能系统整体失效时的终极回退
    FIXED_BASELINE_PARAMS = {
        'base_position_pct': 0.22,
        'leverage': 5.0,
        'tp_pct_btc': 0.04,
        'max_addons': 3,
        'addon_pct': 0.08,
        'use_atr': False,
        'use_trailing_tp': False,
        'use_elder_ray': False,
        'long_only': True,
        'max_base_holding_hours': 48.0,
        'max_post_addon_hours': 24.0,
        'golden_window_hours': 12.0,
    }

    # ── 版本2: 智能参数基线（贝叶斯优化后，210.4%收益，2026-07-16）──
    # 智能系统全开（ATR+移动止盈+ELDER-RAY+风向标）+ 贝叶斯优化最优参数
    # 作为贝叶斯优化无效时的回退目标（不是固定参数基线）
    SMART_BASELINE_PARAMS = {
        'trailing_atr_mult': 1.0,
        'trailing_start_ratio': 0.8,
        'elder_ray_floor': 0.9,
        'elder_ray_ceil': 1.5,
        'btc_windvane_confirm_days': 3,
        'max_base_holding_hours': 29.9,
        'max_post_addon_hours': 37.7,
        'golden_window_hours': 11.1,
    }

    # 向后兼容：BASELINE_PARAMS = SMART_BASELINE_PARAMS
    # 优化无效时回退到此配置（智能参数基线，210.4%）
    BASELINE_PARAMS = SMART_BASELINE_PARAMS.copy()

    # 版本元数据
    VERSION_INFO = {
        'fixed_baseline': {
            'name': '固定参数基线 v1.0',
            'description': '纯马丁策略（止盈4%/底仓22%/加仓3次/间隔8%），无智能增强',
            'total_return_pct': 138.0,
            'params_key': 'FIXED_BASELINE_PARAMS',
            'created_date': '2026-07-15',
            'features': ['固定止盈4%', '固定加仓间隔8%', '无ATR', '无移动止盈', '无ELDER-RAY', '仅做多'],
        },
        'smart_baseline': {
            'name': '智能参数基线 v2.0',
            'description': '智能系统全开 + 贝叶斯优化最优参数',
            'total_return_pct': 210.4,
            'params_key': 'SMART_BASELINE_PARAMS',
            'created_date': '2026-07-16',
            'source': 'bayesian_optimization',
            'optimization_id': 'v15_optimization_20260715_192704',
            'best_score': 4112.87,
            'features': ['ATR动态止盈', '移动止盈', 'ELDER-RAY资金调度(0.9-1.5x)', 'BTC风向标3日确认', '多空方向门控'],
        },
    }

    # 优化调度配置
    SCHEDULE_CONFIG = {
        'loss_streak_trigger': 3,       # 连续亏损3笔触发（事件驱动）
        'weekly_trigger': False,        # 每周触发（默认关闭，避免过拟合）
        'monthly_trigger': True,        # 每月触发（周期驱动）
        'min_improve_pct': 2.0,         # 优化后收益需比基线高2%才采用，否则回退
        'cooldown_hours': 24,           # 冷却期：距上次优化24小时内不重复触发
    }

    def __init__(self, coins=None, initial_capital=10000.0):
        self.coins = coins or ["BTC", "ETH", "SOL", "ARB", "OP"]
        self.initial_capital = initial_capital
        self.bt_module = load_backtest_module()
        self.run_backtest = self.bt_module.run_backtest
        self.fetch_klines = self.bt_module.fetch_klines
        self.calc_30d_volatility = self.bt_module.calc_30d_volatility
        self.results = []
        self.best_params = None
        self.best_score = -float('inf')
        
        # 固定参数（底仓现货思维 + 固定止盈）
        self.fixed_base_position_pct = 0.22
        self.fixed_leverage = 5.0
        self.fixed_tp_pct_btc = 0.04
        
        # 熊市最抗跌：追求收益/回撤比（卡尔马比率思路）
        self.objective_weights = {
            'calmar': 0.40,
            'sharpe': 0.20,
            'win_rate': 0.15,
            'capital_efficiency': 0.25,
        }
        
        self.hard_constraints = {
            'max_drawdown_limit': 60.0,
            'min_win_rate': 0.40,
            'min_trades': 10,
        }
        
        # 参数空间：智能系统核心参数 + 资金分配 + 持仓时间
        # 扩展到智能系统的主要参数（ATR/移动止盈/ELDER-RAY/风向标）
        self.params_space = {
            # ── 智能系统参数 ──
            'trailing_atr_mult': (1.0, 2.5),           # 移动止盈ATR倍数
            'trailing_start_ratio': (0.3, 0.8),        # 移动止盈启动阈值（占止盈比例）
            'elder_ray_floor': (0.5, 0.9),             # ELDER-RAY仓位下限
            'elder_ray_ceil': (1.2, 1.5),              # ELDER-RAY仓位上限
            'btc_windvane_confirm_days': (1.0, 5.0),   # 风向标确认天数
            # ── 持仓时间参数 ──
            'max_base_holding_hours': (24, 96),        # 底仓最大持仓时间
            'max_post_addon_hours': (12, 48),          # 加仓后最大持仓时间
            'golden_window_hours': (4, 24),            # 黄金窗口
        }
        
        self._klines_cache = {}
        self._preload_klines()
        
        self._coin_volatility = {}
        self._btc_volatility = 0.02
        self._calc_volatilities()
        
        self._level_stats = {}
        self._run_base_backtest()
        
        print(f"  固定参数: 底仓{self.fixed_base_position_pct*100:.0f}% | 杠杆{self.fixed_leverage:.0f}x | BTC止盈{self.fixed_tp_pct_btc*100:.0f}%")
        print(f"  智能系统: ATR动态止盈✓ | 移动止盈✓ | ELDER-RAY资金调度✓ | 多空方向门控✓(智能模式)")
        print(f"  优化参数空间({len(self.params_space)}个):")
        for k, v in self.params_space.items():
            if 'hours' in k:
                print(f"    {k}: {v[0]:.1f} - {v[1]:.1f}h")
            elif 'days' in k:
                print(f"    {k}: {int(v[0])} - {int(v[1])}天")
            else:
                print(f"    {k}: {v[0]:.2f} - {v[1]:.2f}")
        print()
    
    def _preload_klines(self):
        print("  预加载K线数据...")
        for coin in self.coins:
            klines = self.fetch_klines(coin, "4h", 1500)
            if klines and len(klines) >= 200:
                self._klines_cache[coin] = klines
                print(f"    {coin}: {len(klines)} 根4H K线")
        print()
    
    def _calc_volatilities(self):
        """计算各币种日线波动率"""
        for coin in self.coins:
            klines_1d = self.fetch_klines(coin, "1d", 400)
            daily_vol = self.calc_30d_volatility(klines_1d) if klines_1d else 0.02
            self._coin_volatility[coin] = daily_vol
            if coin.upper() == "BTC":
                self._btc_volatility = daily_vol
    
    def _calculate_capital_allocation(self, capital_per_coin, base_pct, addon1_pct, addon2_pct, addon3_pct):
        base_usd = capital_per_coin * base_pct
        addon_usd = [
            capital_per_coin * addon1_pct,
            capital_per_coin * addon2_pct,
            capital_per_coin * addon3_pct,
        ]
        total_per_position = base_usd + sum(addon_usd)
        return base_usd, addon_usd, total_per_position
    
    def _run_base_backtest(self):
        """运行基准回测（智能系统默认配置），统计各层收益特征"""
        print("  运行基准回测（智能系统默认配置），统计各层收益特征...")
        
        level_stats = {
            1: {'count': 0, 'total_pnl': 0, 'wins': 0, 'losses': 0},
            2: {'count': 0, 'total_pnl': 0, 'wins': 0, 'losses': 0},
            3: {'count': 0, 'total_pnl': 0, 'wins': 0, 'losses': 0},
            4: {'count': 0, 'total_pnl': 0, 'wins': 0, 'losses': 0},
        }
        
        total_trades_all = 0
        
        for coin in self.coins:
            klines = self._klines_cache.get(coin)
            if not klines or len(klines) < 200:
                continue
            
            result = self.run_backtest(
                coin=coin,
                klines=klines,
                initial_capital=self.initial_capital / len(self.coins),
                base_position_pct=self.fixed_base_position_pct,
                max_addons=3,
                confidence_threshold=0,
                long_only=False,
                position_tf="4h",
                use_atr=True,
                use_trailing_tp=True,
                use_elder_ray=True,
            )
            
            if "error" in result:
                continue
            
            trades = result.get("trades", [])
            for trade in trades:
                level = trade.get("levels_used", 1)
                pnl = trade.get("pnl_pct", 0)
                
                level_stats[level]['count'] += 1
                level_stats[level]['total_pnl'] += pnl
                if pnl > 0:
                    level_stats[level]['wins'] += 1
                else:
                    level_stats[level]['losses'] += 1
            
            total_trades_all += len(trades)
        
        for level in [1, 2, 3, 4]:
            stats = level_stats[level]
            count = stats['count']
            if count > 0:
                print(f"    Level {level}: 触发{count}次 | 平均收益{stats['total_pnl']/count:+.2f}% | 胜率{stats['wins']/(stats['wins']+stats['losses'])*100:.1f}%")
        
        self._level_stats = {
            'level_stats': level_stats,
            'total_trades': total_trades_all,
        }
        print()
    
    def _calculate_objective_score(self, metrics, capital_alloc):
        """计算目标评分（趋势过滤 + 熊市最抗跌）
        
        核心思路：卡尔马比率（收益/回撤）最大化
        - 不是追求零回撤，而是追求有限回撤下的正收益
        - 趋势过滤要适度：过滤掉最危险的熊市，但保留震荡和牛市的交易机会
        """
        leverage = self.fixed_leverage
        total_return = metrics.get('total_return_pct', 0)
        max_drawdown = metrics.get('max_drawdown_pct', 0)
        sharpe_ratio = metrics.get('sharpe_ratio', 0)
        win_rate = metrics.get('win_rate', 0)
        level_dist = metrics.get('level_distribution', {})
        total_trades = metrics.get('total_trades', 0)
        
        leveraged_return = total_return * leverage
        leveraged_drawdown = max_drawdown * leverage
        
        base_score = 0
        
        # 卡尔马比率：收益/回撤（核心指标）
        if leveraged_drawdown > 0.1:
            calmar_ratio = leveraged_return / leveraged_drawdown
        else:
            calmar_ratio = leveraged_return * 10 if leveraged_return > 0 else -100
        
        base_score += self.objective_weights['calmar'] * calmar_ratio * 10
        
        # 夏普比率
        base_score += self.objective_weights['sharpe'] * sharpe_ratio * 10
        
        # 胜率
        base_score += self.objective_weights['win_rate'] * win_rate * 100
        
        # 硬约束：最大回撤超限，重罚
        if leveraged_drawdown > self.hard_constraints['max_drawdown_limit']:
            base_score -= 200
        
        # 硬约束：交易太少（过度过滤），重罚
        if total_trades < self.hard_constraints['min_trades']:
            base_score -= 150
        
        # 硬约束：亏损且回撤大，重罚
        if leveraged_return < -20 and leveraged_drawdown > 40:
            base_score -= 100
        
        # 资金效率评分
        efficiency_score = 0
        if capital_alloc and self._level_stats and total_trades > 0:
            base_usd = capital_alloc.get('base', 0)
            addon1_usd = capital_alloc.get('addon1', 0)
            addon2_usd = capital_alloc.get('addon2', 0)
            addon3_usd = capital_alloc.get('addon3', 0)
            total_capital = base_usd + addon1_usd + addon2_usd + addon3_usd
            
            if total_capital > 0:
                addon_total = addon1_usd + addon2_usd + addon3_usd
                addon_ratio = addon_total / total_capital
                
                total_trades_dist = sum(level_dist.values()) if level_dist else 0
                
                if total_trades_dist > 0:
                    level2_plus_trades = sum(v for k, v in level_dist.items() if k >= 2)
                    level2_plus_ratio = level2_plus_trades / total_trades_dist
                    
                    # 黑天鹅加仓效果
                    level_stats = self._level_stats.get('level_stats', {})
                    addon_avg_pnl = 0
                    addon_total_count = 0
                    for level in [2, 3, 4]:
                        stats = level_stats.get(level, {})
                        count = stats.get('count', 0)
                        if count > 0:
                            addon_total_count += count
                            addon_avg_pnl += stats.get('total_pnl', 0)
                    
                    if addon_total_count > 0:
                        addon_avg_pnl = addon_avg_pnl / addon_total_count
                        if addon_avg_pnl > 0:
                            efficiency_score += addon_avg_pnl * 2
                    
                    # 资金利用率
                    if addon_ratio > 0 and level2_plus_ratio > 0:
                        utilization_ratio = level2_plus_ratio / addon_ratio
                        if 0.3 <= utilization_ratio <= 3.0:
                            efficiency_score += 10
                        elif utilization_ratio < 0.3:
                            efficiency_score -= (0.3 - utilization_ratio) * 20
                        else:
                            efficiency_score -= (utilization_ratio - 3.0) * 10
                    
                    # 奖励：有加仓交易且盈利
                    if level2_plus_ratio > 0.01 and addon_avg_pnl > 0:
                        efficiency_score += level2_plus_ratio * 50
                    
                    # 惩罚：加仓资金闲置过多
                    if addon_ratio > 0.6 and level2_plus_ratio < 0.02:
                        efficiency_score -= (addon_ratio - 0.6) * 80
        
        total_score = base_score + self.objective_weights['capital_efficiency'] * efficiency_score
        return total_score
    
    def objective(self, **params):
        try:
            # 智能系统参数
            trailing_atr_mult = params['trailing_atr_mult']
            trailing_start_ratio = params['trailing_start_ratio']
            elder_ray_floor = params['elder_ray_floor']
            elder_ray_ceil = params['elder_ray_ceil']
            btc_windvane_confirm_days = int(round(params['btc_windvane_confirm_days']))
            max_base_holding_hours = params['max_base_holding_hours']
            max_post_addon_hours = params['max_post_addon_hours']
            golden_window_hours = params['golden_window_hours']

            # 动态设置ELDER-RAY调节范围（通过修改全局函数行为）
            # 由于calc_elder_ray_size_mult在v15_backtest中是独立函数，我们需要传递参数
            # 这里用临时修改模块级变量的方式
            bt = self.bt_module
            old_floor = getattr(bt, '_elder_ray_floor', 0.9)
            old_ceil = getattr(bt, '_elder_ray_ceil', 1.5)
            bt._elder_ray_floor = elder_ray_floor
            bt._elder_ray_ceil = elder_ray_ceil

            total_score = 0
            total_trades = 0
            valid_coins = 0

            for coin in self.coins:
                klines = self._klines_cache.get(coin)
                if not klines or len(klines) < 200:
                    continue

                result = self.run_backtest(
                    coin=coin,
                    klines=klines,
                    initial_capital=self.initial_capital / len(self.coins),
                    base_position_pct=self.fixed_base_position_pct,
                    max_addons=3,
                    confidence_threshold=0,
                    long_only=False,           # 智能模式：多空双向
                    position_tf="4h",
                    use_atr=True,              # ATR动态止盈
                    use_trailing_tp=True,      # 移动止盈
                    trailing_atr_mult=trailing_atr_mult,
                    trailing_start_pct_of_tp=trailing_start_ratio,
                    use_elder_ray=True,        # ELDER-RAY资金调度
                    btc_windvane_confirm_days=btc_windvane_confirm_days,
                    max_base_holding_hours=max_base_holding_hours,
                    max_post_addon_hours=max_post_addon_hours,
                    golden_window_hours=golden_window_hours,
                )

                if "error" in result:
                    continue

                metrics = result["metrics"]

                # 简化评分：卡尔马比率为主 + 夏普 + 胜率
                score = self._calculate_objective_score(metrics, None)

                total_score += score
                total_trades += metrics.get('total_trades', 0)
                valid_coins += 1

            # 恢复全局变量
            bt._elder_ray_floor = old_floor
            bt._elder_ray_ceil = old_ceil

            if valid_coins == 0:
                return -1000.0

            avg_score = total_score / valid_coins

            param_dict = {
                'trailing_atr_mult': round(trailing_atr_mult, 2),
                'trailing_start_ratio': round(trailing_start_ratio, 2),
                'elder_ray_floor': round(elder_ray_floor, 2),
                'elder_ray_ceil': round(elder_ray_ceil, 2),
                'btc_windvane_confirm_days': btc_windvane_confirm_days,
                'max_base_holding_hours': round(max_base_holding_hours, 1),
                'max_post_addon_hours': round(max_post_addon_hours, 1),
                'golden_window_hours': round(golden_window_hours, 1),
            }

            self.results.append({
                'params': param_dict,
                'score': round(avg_score, 4),
                'total_trades': total_trades,
                'timestamp': datetime.now(timezone.utc).isoformat(),
            })

            if avg_score > self.best_score:
                self.best_score = avg_score
                self.best_params = param_dict

            return avg_score

        except Exception as e:
            print(f"  objective error: {e}")
            return -1000.0
    
    def optimize(self, init_points=5, n_iter=20, save=True):
        print(f"\n开始贝叶斯优化（{init_points}个初始点 + {n_iter}次迭代）...\n")
        
        optimizer = BayesianOptimization(
            f=self.objective,
            pbounds=self.params_space,
            random_state=42,
            verbose=2,
        )
        
        start_time = time.time()
        optimizer.maximize(init_points=init_points, n_iter=n_iter)
        elapsed = time.time() - start_time
        
        best_p = optimizer.max['params']
        
        best_params = {
            'trailing_atr_mult': round(best_p['trailing_atr_mult'], 2),
            'trailing_start_ratio': round(best_p['trailing_start_ratio'], 2),
            'elder_ray_floor': round(best_p['elder_ray_floor'], 2),
            'elder_ray_ceil': round(best_p['elder_ray_ceil'], 2),
            'btc_windvane_confirm_days': int(round(best_p['btc_windvane_confirm_days'])),
            'max_base_holding_hours': round(best_p['max_base_holding_hours'], 1),
            'max_post_addon_hours': round(best_p['max_post_addon_hours'], 1),
            'golden_window_hours': round(best_p['golden_window_hours'], 1),
        }
        
        self.best_params = best_params
        
        # 设置ELDER-RAY范围为最优值用于验证回测
        bt = self.bt_module
        bt._elder_ray_floor = best_params['elder_ray_floor']
        bt._elder_ray_ceil = best_params['elder_ray_ceil']
        
        print(f"\n{'='*80}")
        print("  智能系统参数优化报告")
        print(f"{'='*80}")
        print(f"  验证币种: {self.coins}")
        print(f"  优化耗时: {elapsed:.1f}秒")
        print(f"  最优评分: {self.best_score:.4f}")
        
        print(f"\n  --- 最优参数 ---")
        p = best_params
        print(f"    移动止盈ATR倍数:     {p['trailing_atr_mult']:.2f}")
        print(f"    移动止盈启动阈值:     {p['trailing_start_ratio']:.2f} (占止盈比例)")
        print(f"    ELDER-RAY仓位范围:   {p['elder_ray_floor']:.2f}x - {p['elder_ray_ceil']:.2f}x")
        print(f"    风向标确认天数:       {p['btc_windvane_confirm_days']}天")
        print(f"    底仓最大持仓:         {p['max_base_holding_hours']:.1f}h")
        print(f"    加仓后最大持仓:       {p['max_post_addon_hours']:.1f}h")
        print(f"    黄金窗口:             {p['golden_window_hours']:.1f}h")
        
        print(f"\n  --- 验证回测结果（智能系统最优参数）---")
        for coin in self.coins:
            klines = self._klines_cache.get(coin)
            if not klines or len(klines) < 200:
                continue
            
            result = self.run_backtest(
                coin=coin, klines=klines,
                initial_capital=self.initial_capital / len(self.coins),
                base_position_pct=self.fixed_base_position_pct,
                max_addons=3, confidence_threshold=0,
                long_only=False, position_tf="4h",
                use_atr=True, use_trailing_tp=True,
                trailing_atr_mult=p['trailing_atr_mult'],
                trailing_start_pct_of_tp=p['trailing_start_ratio'],
                use_elder_ray=True,
                btc_windvane_confirm_days=p['btc_windvane_confirm_days'],
                max_base_holding_hours=p['max_base_holding_hours'],
                max_post_addon_hours=p['max_post_addon_hours'],
                golden_window_hours=p['golden_window_hours'],
            )
            
            if "error" in result:
                continue
            
            m = result["metrics"]
            lev = self.fixed_leverage
            print(f"    {coin}: 收益{m['total_return_pct']*lev:+.2f}% | 回撤{m['max_drawdown_pct']*lev:.2f}% | 胜率{m['win_rate']*100:.1f}% | {m['total_trades']}次交易 | 夏普{m['sharpe_ratio']:.4f}")
        
        print(f"{'='*80}\n")
        
        if save:
            self._save_results()
        
        # 恢复默认ELDER-RAY范围（贝叶斯优化最优值）
        bt._elder_ray_floor = 0.9
        bt._elder_ray_ceil = 1.5
        
        return best_params
    
    def _print_trend_filter_effect(self, best_params, coins_to_test, capital_per_coin, base_usd, addon_usd, total_per_position):
        """对比有/无趋势过滤的效果"""
        p = best_params
        effective_base_pct = total_per_position / capital_per_coin
        
        for coin in coins_to_test[:3]:
            klines = self._klines_cache.get(coin)
            if not klines or len(klines) < 200:
                continue
            
            coin_vol = self._coin_volatility.get(coin, self._btc_volatility)
            vol_ratio = coin_vol / self._btc_volatility if self._btc_volatility > 0 else 1.0
            vol_ratio = max(0.5, min(2.0, vol_ratio))
            tp_pct_coin = p['tp_pct_btc'] * vol_ratio
            
            # 无过滤
            result_no = self.run_backtest(
                coin=coin, klines=klines, initial_capital=capital_per_coin,
                base_position_pct=effective_base_pct, max_addons=3,
                confidence_threshold=0, long_only=True, position_tf="4h",
                custom_tp_pct=tp_pct_coin, trend_filter_mode="none",
                max_base_holding_hours=p.get('max_base_holding_hours', 48.0),
                max_post_addon_hours=p.get('max_post_addon_hours', 24.0),
                golden_window_hours=p.get('golden_window_hours', 12.0),
            )
            
            # 有过滤
            result_yes = self.run_backtest(
                coin=coin, klines=klines, initial_capital=capital_per_coin,
                base_position_pct=effective_base_pct, max_addons=3,
                confidence_threshold=0, long_only=True, position_tf="4h",
                custom_tp_pct=tp_pct_coin,
                trend_filter_mode=p['trend_filter_mode'],
                trend_filter_period=p['trend_filter_period'],
                max_base_holding_hours=p.get('max_base_holding_hours', 48.0),
                max_post_addon_hours=p.get('max_post_addon_hours', 24.0),
                golden_window_hours=p.get('golden_window_hours', 12.0),
            )
            
            if "error" in result_no or "error" in result_yes:
                continue
            
            m_no = result_no["metrics"]
            m_yes = result_yes["metrics"]
            
            dd_improve = (m_no['max_drawdown_pct'] - m_yes['max_drawdown_pct']) / m_no['max_drawdown_pct'] * 100 if m_no['max_drawdown_pct'] > 0 else 0
            trade_reduction = (m_no['total_trades'] - m_yes['total_trades']) / m_no['total_trades'] * 100 if m_no['total_trades'] > 0 else 0
            
            print(f"    {coin}: 回撤{m_no['max_drawdown_pct']*p['leverage']:.1f}% → {m_yes['max_drawdown_pct']*p['leverage']:.1f}% (改善{dd_improve:.1f}%) | 交易{m_no['total_trades']} → {m_yes['total_trades']}次 (减少{trade_reduction:.1f}%)")
    
    def _save_results(self):
        output_dir = STRATEGY_DIR / "data" / "bayesian_opt"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        
        output = {
            "best_params": self.best_params,
            "best_score": round(self.best_score, 4),
            "coins": self.coins,
            "initial_capital": self.initial_capital,
            "objective_weights": self.objective_weights,
            "hard_constraints": self.hard_constraints,
            "results_count": len(self.results),
            "top_10_results": sorted(self.results, key=lambda x: x['score'], reverse=True)[:10],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        filename = output_dir / f"v15_optimization_{timestamp}.json"
        with open(filename, 'w') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        
        print(f"  结果已保存: {filename}")
    
    def get_latest_result(self):
        if not self.results:
            return None
        return max(self.results, key=lambda x: x['score'])

    # ── 三轮反馈优化（回测→优化→回测验证→再优化，互相促进）──────────────

    def _run_verify_backtest(self, params: dict) -> dict:
        """用指定参数运行完整回测验证，返回详细指标"""
        max_concurrent = params['max_concurrent_positions']
        coins_to_test = self.coins[:max_concurrent]
        capital_per_coin = self.initial_capital / max_concurrent

        base_usd, addon_usd, total_per_position = self._calculate_capital_allocation(
            capital_per_coin, params['base_position_pct'],
            params['addon1_pct'], params['addon2_pct'], params['addon3_pct']
        )
        effective_base_pct = total_per_position / capital_per_coin

        total_return = 0
        total_max_dd = 0
        total_sharpe = 0
        total_win_rate = 0
        total_trades = 0
        valid_coins = 0
        coin_results = {}
        level_dist_aggregate = {}

        for coin in coins_to_test:
            klines = self._klines_cache.get(coin)
            if not klines or len(klines) < 200:
                continue

            coin_vol = self._coin_volatility.get(coin, self._btc_volatility)
            vol_ratio = coin_vol / self._btc_volatility if self._btc_volatility > 0 else 1.0
            vol_ratio = max(0.5, min(2.0, vol_ratio))
            tp_pct_coin = params['tp_pct_btc'] * vol_ratio

            result = self.run_backtest(
                coin=coin,
                klines=klines,
                initial_capital=capital_per_coin,
                base_position_pct=effective_base_pct,
                max_addons=3,
                confidence_threshold=0,
                long_only=True,
                position_tf="4h",
                custom_tp_pct=tp_pct_coin,
                trend_filter_mode=params['trend_filter_mode'],
                trend_filter_period=params['trend_filter_period'],
                max_base_holding_hours=params.get('max_base_holding_hours', 48.0),
                max_post_addon_hours=params.get('max_post_addon_hours', 24.0),
                golden_window_hours=params.get('golden_window_hours', 12.0),
            )

            if "error" in result:
                continue

            m = result["metrics"]
            lev = params['leverage']
            coin_results[coin] = {
                'total_return_pct': m['total_return_pct'] * lev,
                'max_drawdown_pct': m['max_drawdown_pct'] * lev,
                'sharpe_ratio': m['sharpe_ratio'],
                'win_rate': m['win_rate'],
                'total_trades': m['total_trades'],
                'level_distribution': m.get('level_distribution', {}),
            }

            total_return += m['total_return_pct'] * lev
            total_max_dd += m['max_drawdown_pct'] * lev
            total_sharpe += m['sharpe_ratio']
            total_win_rate += m['win_rate']
            total_trades += m['total_trades']
            valid_coins += 1

            for lvl, cnt in m.get('level_distribution', {}).items():
                level_dist_aggregate[lvl] = level_dist_aggregate.get(lvl, 0) + cnt

        if valid_coins == 0:
            return {'error': 'no valid coins'}

        avg_return = total_return / valid_coins
        avg_dd = total_max_dd / valid_coins
        avg_sharpe = total_sharpe / valid_coins
        avg_win_rate = total_win_rate / valid_coins

        calmar = avg_return / avg_dd if avg_dd > 0.1 else (avg_return * 10 if avg_return > 0 else -100)

        capital_alloc = {
            'base': base_usd,
            'addon1': addon_usd[0],
            'addon2': addon_usd[1],
            'addon3': addon_usd[2],
        }
        score = self._calculate_objective_score(
            {'total_return_pct': avg_return / lev, 'max_drawdown_pct': avg_dd / lev,
             'sharpe_ratio': avg_sharpe, 'win_rate': avg_win_rate,
             'total_trades': total_trades, 'level_distribution': level_dist_aggregate},
            capital_alloc
        )

        return {
            'avg_return_pct': round(avg_return, 2),
            'avg_max_drawdown_pct': round(avg_dd, 2),
            'avg_sharpe_ratio': round(avg_sharpe, 3),
            'avg_win_rate': round(avg_win_rate, 4),
            'calmar_ratio': round(calmar, 2),
            'total_trades': total_trades,
            'valid_coins': valid_coins,
            'objective_score': round(score, 4),
            'coin_results': coin_results,
            'level_distribution': level_dist_aggregate,
        }

    def _narrow_search_space(self, best_params: dict, shrink_pct: float) -> dict:
        """根据上一轮最优参数收敛搜索空间

        shrink_pct: 收缩比例，如 0.3 表示上下各30%
        """
        current_space = self.params_space.copy()
        new_space = {}

        for key, (low, high) in current_space.items():
            if key == 'max_concurrent_positions':
                best_val = best_params.get(key, 4)
                new_low = max(2, best_val - 1)
                new_high = min(6, best_val + 1)
                new_space[key] = (new_low, new_high)
            else:
                best_val = best_params.get(key, (low + high) / 2)
                half_range = (high - low) * shrink_pct
                new_low = max(low, best_val - half_range)
                new_high = min(high, best_val + half_range)
                if new_high - new_low < 0.01:
                    new_low = max(low, new_low - 0.005)
                    new_high = min(high, new_high + 0.005)
                new_space[key] = (new_low, new_high)

        return new_space

    def _analyze_round_result(self, round_name: str, verify_result: dict, params: dict) -> list:
        """分析本轮回测结果，给出诊断和优化建议"""
        advice = []

        avg_return = verify_result.get('avg_return_pct', 0)
        avg_dd = verify_result.get('avg_max_drawdown_pct', 0)
        total_trades = verify_result.get('total_trades', 0)
        win_rate = verify_result.get('avg_win_rate', 0)
        level_dist = verify_result.get('level_distribution', {})

        if avg_dd > 40:
            advice.append(f"回撤过大({avg_dd:.1f}%)，建议降低加仓资金或优化持仓时间")
        elif avg_dd < 10 and avg_return > 0:
            advice.append(f"回撤很小({avg_dd:.1f}%)且有正收益，可以考虑稍微激进一些")

        if total_trades < 20:
            advice.append(f"交易次数偏少({total_trades}次)，入场信号可能过严")
        elif total_trades > 200:
            advice.append(f"交易次数偏多({total_trades}次)，信号可能过于频繁")

        level2_plus = sum(v for k, v in level_dist.items() if int(k) >= 2)
        if total_trades > 0 and level2_plus / total_trades < 0.02:
            advice.append("加仓触发极少，加仓资金可能长期闲置")
        elif total_trades > 0 and level2_plus / total_trades > 0.3:
            advice.append("加仓触发频繁，需要关注加仓资金是否充足")

        if win_rate < 0.45:
            advice.append(f"胜率偏低({win_rate*100:.1f}%)，建议优化入场信号或提高止盈比例")

        if avg_return < 0:
            advice.append("整体亏损，需要重点排查信号质量和趋势过滤")

        if not advice:
            advice.append("指标健康，参数合理")

        return advice

    def iterate_optimize(self, rounds=3, init_points=5, n_iter=15, save=True):
        """三轮反馈优化：回测→贝叶斯优化→回测验证→再优化，迭代收敛

        机制：
        - 第1轮：基线探索，宽范围搜索 → 回测验证 → 分析瓶颈
        - 第2轮：基于第1轮最优参数，收敛到±30%范围 → 回测验证 → 对比提升
        - 第3轮：基于第2轮最优参数，收敛到±15%范围 → 回测验证 → 最终确认

        每轮都有完整的回测验证和指标对比，确保优化方向正确。
        """
        print(f"\n{'='*70}")
        print(f"  三轮反馈优化开始（共{rounds}轮）")
        print(f"  核心机制：回测 ↔ 贝叶斯优化 互相促进，迭代收敛")
        print(f"{'='*70}\n")

        round_results = []
        current_best = {
            'leverage': self.fixed_leverage,
            'base_position_pct': self.fixed_base_position_pct,
            'tp_pct_btc': self.fixed_tp_pct_btc,
            'trend_filter_mode': 'none',
            'trend_filter_period': 200,
            'addon1_pct': get_config_float("ADDON1_PCT", 0.20),
            'addon2_pct': get_config_float("ADDON2_PCT", 0.05),
            'addon3_pct': get_config_float("ADDON3_PCT", 0.10),
            'max_concurrent_positions': get_config_int("MAX_CONCURRENT_POSITIONS", 6),
            'max_base_holding_hours': get_config_float("V15_MAX_BASE_HOLDING_HOURS", 48.0),
            'max_post_addon_hours': get_config_float("V15_MAX_POST_ADDON_HOURS", 24.0),
            'golden_window_hours': get_config_float("V15_GOLDEN_WINDOW_HOURS", 12.0),
        }

        shrink_schedule = [None, 0.30, 0.15]

        for round_idx in range(1, rounds + 1):
            round_name = f"第{round_idx}轮"
            shrink_pct = shrink_schedule[round_idx - 1] if round_idx <= len(shrink_schedule) else 0.1

            print(f"\n{'─'*70}")
            print(f"  {round_name}：{'基线探索（宽范围）' if round_idx == 1 else f'收敛优化（±{int(shrink_pct*100)}%范围）'}")
            print(f"{'─'*70}\n")

            if shrink_pct is not None:
                self.params_space = self._narrow_search_space(current_best, shrink_pct)
                print(f"  搜索空间已收敛（基于上一轮最优参数 ±{int(shrink_pct*100)}%）：")
                for k, (lo, hi) in self.params_space.items():
                    if k == 'max_concurrent_positions':
                        print(f"    {k}: {int(lo)}-{int(hi)}")
                    elif 'hours' in k:
                        print(f"    {k}: {lo:.1f}-{hi:.1f}h")
                    else:
                        print(f"    {k}: {lo:.4f}-{hi:.4f}")
                print()

            print(f"  [{round_name}] 阶段1/3：贝叶斯参数优化...")
            round_best_params = self.optimize(
                init_points=init_points,
                n_iter=n_iter,
                save=False,
            )

            print(f"\n  [{round_name}] 阶段2/3：回测验证最优参数...")
            verify_result = self._run_verify_backtest(round_best_params)

            if 'error' in verify_result:
                print(f"  回测验证失败: {verify_result['error']}")
                continue

            print(f"    平均收益: {verify_result['avg_return_pct']:+.2f}%")
            print(f"    平均回撤: {verify_result['avg_max_drawdown_pct']:.2f}%")
            print(f"    卡尔马比率: {verify_result['calmar_ratio']:.2f}")
            print(f"    平均胜率: {verify_result['avg_win_rate']*100:.1f}%")
            print(f"    总交易次数: {verify_result['total_trades']}次")

            print(f"\n  [{round_name}] 阶段3/3：诊断分析...")
            advice = self._analyze_round_result(round_name, verify_result, round_best_params)
            for a in advice:
                print(f"    - {a}")

            round_results.append({
                'round': round_idx,
                'round_name': round_name,
                'params': round_best_params,
                'verify': verify_result,
                'advice': advice,
                'search_space': {k: list(v) for k, v in self.params_space.items()},
            })

            current_best = round_best_params

        # 三轮对比总结
        print(f"\n{'='*70}")
        print(f"  三轮优化对比总结")
        print(f"{'='*70}\n")

        if len(round_results) >= 2:
            print(f"  {'轮次':<10} {'收益%':>10} {'回撤%':>10} {'卡尔马':>10} {'胜率%':>10} {'交易数':>10}")
            print(f"  {'─'*60}")
            for r in round_results:
                v = r['verify']
                print(f"  {r['round_name']:<10} {v['avg_return_pct']:>+10.2f} {v['avg_max_drawdown_pct']:>10.2f} "
                      f"{v['calmar_ratio']:>10.2f} {v['avg_win_rate']*100:>9.1f}% {v['total_trades']:>10}")

            print(f"\n  参数演进：")
            param_keys = ['addon1_pct', 'addon2_pct', 'addon3_pct',
                          'max_concurrent_positions', 'max_base_holding_hours']
            for key in param_keys:
                vals = [f"{r['params'].get(key, '?')}" for r in round_results]
                print(f"    {key}: {' → '.join(vals)}")

        # 最终确认
        best_round = max(round_results, key=lambda r: r['verify'].get('calmar_ratio', -999))
        final_params = best_round['params']
        self.best_params = final_params
        self.best_score = best_round['verify'].get('objective_score', 0)

        print(f"\n  最终选择：{best_round['round_name']}（卡尔马比率最高）")
        print(f"  最终参数：")
        for k, v in final_params.items():
            print(f"    {k}: {v}")

        print(f"\n  优化建议汇总：")
        all_advice = set()
        for r in round_results:
            for a in r['advice']:
                all_advice.add(a)
        for a in list(all_advice)[:8]:
            print(f"    - {a}")

        print(f"\n{'='*70}\n")

        if save:
            self._save_iteration_results(round_results, final_params)

        return final_params, round_results

    def _save_iteration_results(self, round_results, final_params):
        output_dir = STRATEGY_DIR / "data" / "bayesian_opt"
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        output = {
            "optimization_type": "three_round_iterative",
            "rounds_count": len(round_results),
            "final_params": final_params,
            "round_results": round_results,
            "coins": self.coins,
            "initial_capital": self.initial_capital,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        filename = output_dir / f"v15_iterative_opt_{timestamp}.json"
        with open(filename, 'w') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        print(f"  三轮优化报告已保存: {filename}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="V15马丁策略贝叶斯参数优化")
    parser.add_argument("--coins", nargs="+", default=["BTC", "ETH", "SOL", "ARB", "OP"], help="测试币种列表")
    parser.add_argument("--capital", type=float, default=10000.0, help="初始资金")
    parser.add_argument("--init-points", type=int, default=5, help="初始探索点数")
    parser.add_argument("--iterations", type=int, default=20, help="优化迭代次数")
    parser.add_argument("--iterative", action="store_true", help="启用三轮反馈迭代优化模式")
    parser.add_argument("--rounds", type=int, default=3, help="迭代轮数（默认3轮）")
    parser.add_argument("--save", action="store_true", help="保存结果到文件")
    args = parser.parse_args()
    
    print(f"V15马丁策略贝叶斯参数优化")
    mode_str = "三轮反馈迭代优化" if args.iterative else "单次优化"
    print(f"模式: {mode_str}")
    print(f"测试币种: {args.coins}")
    print(f"初始资金: ${args.capital:,.2f}")
    print()
    
    optimizer = V15CapitalOptimizer(
        coins=args.coins,
        initial_capital=args.capital,
    )
    
    if args.iterative:
        best, round_results = optimizer.iterate_optimize(
            rounds=args.rounds,
            init_points=args.init_points,
            n_iter=args.iterations,
            save=args.save,
        )
    else:
        best = optimizer.optimize(
            init_points=args.init_points,
            n_iter=args.iterations,
            save=args.save,
        )
    
    print("最优参数:")
    for k, v in best.items():
        print(f"  {k}: {v}")


# ── 自动回退与调度机制 ────────────────────────────────────────────────────

# 基线参数和活跃参数的持久化路径
ACTIVE_PARAMS_FILE = STRATEGY_DIR / "data" / "bayesian_opt" / "active_params.json"
OPT_SCHEDULE_STATE_FILE = STRATEGY_DIR / "data" / "bayesian_opt" / "schedule_state.json"


def load_active_params() -> dict:
    """加载当前生效的参数（如果不存在则返回基线）"""
    if ACTIVE_PARAMS_FILE.exists():
        try:
            with open(ACTIVE_PARAMS_FILE) as f:
                data = json.load(f)
                return data.get("params", V15CapitalOptimizer.BASELINE_PARAMS.copy())
        except Exception:
            pass
    return V15CapitalOptimizer.BASELINE_PARAMS.copy()


def save_active_params(params: dict, source: str = "optimization", score: float = 0):
    """保存当前生效的参数"""
    ACTIVE_PARAMS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "params": params,
        "source": source,
        "score": round(score, 4),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with open(ACTIVE_PARAMS_FILE, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def rollback_to_baseline(reason: str = "optimization ineffective") -> dict:
    """回退到智能参数基线（210.4%，贝叶斯优化后的默认配置）

    这是贝叶斯优化无效时的回退目标，不是固定参数基线。
    """
    baseline = V15CapitalOptimizer.SMART_BASELINE_PARAMS.copy()
    save_active_params(baseline, source="smart_baseline_rollback", score=0)
    print(f"  ⚠ 已回退到智能参数基线（210.4%），原因: {reason}")
    return baseline


def rollback_to_fixed_baseline(reason: str = "smart system failure") -> dict:
    """终极回退：回退到固定参数基线（138%，纯马丁策略）

    仅在智能系统整体失效（如ATR/ELDER-RAY/风向标全部异常）时使用。
    回退后需手动排查智能系统问题，修复后重新启用智能参数基线。
    """
    baseline = V15CapitalOptimizer.FIXED_BASELINE_PARAMS.copy()
    save_active_params(baseline, source="fixed_baseline_rollback", score=0)
    print(f"  🚨 已终极回退到固定参数基线（138%，纯马丁策略），原因: {reason}")
    print(f"     请排查智能系统问题，修复后运行: python3 lib/bayesian_optimizer.py --reset-to-smart")
    return baseline


def print_version_info():
    """打印当前版本管理信息"""
    print(f"\n{'='*80}")
    print("  V15马丁策略 - 参数版本管理")
    print(f"{'='*80}")

    vi = V15CapitalOptimizer.VERSION_INFO

    # 固定参数基线
    fb = vi['fixed_baseline']
    print(f"\n  ── 版本1: {fb['name']} ──")
    print(f"  描述: {fb['description']}")
    print(f"  回测收益: {fb['total_return_pct']:.1f}%")
    print(f"  创建日期: {fb['created_date']}")
    print(f"  特性: {', '.join(fb['features'])}")

    # 智能参数基线
    sb = vi['smart_baseline']
    print(f"\n  ── 版本2: {sb['name']} ──")
    print(f"  描述: {sb['description']}")
    print(f"  回测收益: {sb['total_return_pct']:.1f}%")
    print(f"  创建日期: {sb['created_date']}")
    print(f"  优化来源: {sb['source']}")
    print(f"  优化ID: {sb['optimization_id']}")
    print(f"  最优评分: {sb['best_score']:.2f}")
    print(f"  特性: {', '.join(sb['features'])}")

    # 当前活跃参数
    active = load_active_params()
    active_data = {}
    if ACTIVE_PARAMS_FILE.exists():
        try:
            with open(ACTIVE_PARAMS_FILE) as f:
                active_data = json.load(f)
        except Exception:
            pass

    print(f"\n  ── 当前活跃参数 ──")
    print(f"  来源: {active_data.get('source', '未初始化（使用智能参数基线）')}")
    print(f"  时间: {active_data.get('timestamp', 'N/A')}")
    print(f"  评分: {active_data.get('score', 'N/A')}")

    # 判断当前是哪个版本
    if active == V15CapitalOptimizer.SMART_BASELINE_PARAMS:
        print(f"  状态: ✅ 使用智能参数基线（210.4%）")
    elif active == V15CapitalOptimizer.FIXED_BASELINE_PARAMS:
        print(f"  状态: 🚨 使用固定参数基线（138%，终极回退模式）")
    else:
        print(f"  状态: 📊 使用贝叶斯优化参数（自定义）")

    # 调度状态
    sched = load_schedule_state()
    print(f"\n  ── 调度状态 ──")
    print(f"  上次优化: {sched.get('last_optimize_ts', '从未运行')}")
    print(f"  上次动作: {sched.get('last_action', 'N/A')}")
    print(f"  收益改善: {sched.get('last_improvement', 0):+.2f}%")

    print(f"\n  ── 回退策略 ──")
    print(f"  贝叶斯优化无效（收益差<2%）→ 回退到智能参数基线（210.4%）")
    print(f"  智能系统整体失效 → 终极回退到固定参数基线（138%）")
    print(f"{'='*80}\n")


def run_optimization_with_rollback(coins=None, initial_capital=10000.0,
                                    init_points=5, n_iter=20) -> dict:
    """运行贝叶斯优化，并与基线对比，无效则自动回退

    流程：
    1. 用基线参数跑回测，记录基线收益
    2. 运行贝叶斯优化，获取最优参数
    3. 用最优参数跑回测，记录优化收益
    4. 如果优化收益 - 基线收益 < min_improve_pct（默认2%），回退基线
    5. 否则保存优化参数为活跃参数
    """
    coins = coins or ["BTC", "ETH", "SOL", "ARB", "OP", "UNI"]
    min_improve = V15CapitalOptimizer.SCHEDULE_CONFIG['min_improve_pct']

    print(f"\n{'='*80}")
    print("  贝叶斯优化 + 自动回退验证")
    print(f"  回退目标: 智能参数基线（210.4%，贝叶斯优化后）")
    print(f"{'='*80}")

    # Step 1: 智能参数基线回测（210.4%）
    print("\n  [1/4] 智能参数基线回测...")
    baseline_params = V15CapitalOptimizer.SMART_BASELINE_PARAMS.copy()
    bt = load_backtest_module()
    total_baseline = 0
    for coin in coins:
        klines = bt.fetch_klines(coin, "4h", 1500)
        if not klines or len(klines) < 200:
            continue
        bt._elder_ray_floor = baseline_params['elder_ray_floor']
        bt._elder_ray_ceil = baseline_params['elder_ray_ceil']
        r = bt.run_backtest(
            coin=coin, klines=klines,
            initial_capital=initial_capital / len(coins),
            base_position_pct=0.22, max_addons=3,
            confidence_threshold=0, long_only=False, position_tf="4h",
            use_atr=True, use_trailing_tp=True,
            trailing_atr_mult=baseline_params['trailing_atr_mult'],
            trailing_start_pct_of_tp=baseline_params['trailing_start_ratio'],
            use_elder_ray=True,
            btc_windvane_confirm_days=baseline_params['btc_windvane_confirm_days'],
            max_base_holding_hours=baseline_params['max_base_holding_hours'],
            max_post_addon_hours=baseline_params['max_post_addon_hours'],
            golden_window_hours=baseline_params['golden_window_hours'],
        )
        if "error" not in r:
            total_baseline += r['metrics']['total_return_pct']
    print(f"    智能基线总收益: {total_baseline:+.2f}%")

    # Step 2: 贝叶斯优化
    print(f"\n  [2/4] 贝叶斯参数优化（{init_points}初始+{n_iter}迭代）...")
    optimizer = V15CapitalOptimizer(coins=coins, initial_capital=initial_capital)
    opt_params = optimizer.optimize(init_points=init_points, n_iter=n_iter, save=True)

    # Step 3: 优化参数回测
    print("\n  [3/4] 优化参数回测验证...")
    total_optimized = 0
    bt._elder_ray_floor = opt_params['elder_ray_floor']
    bt._elder_ray_ceil = opt_params['elder_ray_ceil']
    for coin in coins:
        klines = optimizer._klines_cache.get(coin)
        if not klines or len(klines) < 200:
            continue
        r = bt.run_backtest(
            coin=coin, klines=klines,
            initial_capital=initial_capital / len(coins),
            base_position_pct=0.22, max_addons=3,
            confidence_threshold=0, long_only=False, position_tf="4h",
            use_atr=True, use_trailing_tp=True,
            trailing_atr_mult=opt_params['trailing_atr_mult'],
            trailing_start_pct_of_tp=opt_params['trailing_start_ratio'],
            use_elder_ray=True,
            btc_windvane_confirm_days=opt_params['btc_windvane_confirm_days'],
            max_base_holding_hours=opt_params['max_base_holding_hours'],
            max_post_addon_hours=opt_params['max_post_addon_hours'],
            golden_window_hours=opt_params['golden_window_hours'],
        )
        if "error" not in r:
            total_optimized += r['metrics']['total_return_pct']
    print(f"    优化总收益: {total_optimized:+.2f}%")

    # Step 4: 对比决定
    improvement = total_optimized - total_baseline
    print(f"\n  [4/4] 对比验证:")
    print(f"    智能基线收益: {total_baseline:+.2f}%")
    print(f"    优化收益:     {total_optimized:+.2f}%")
    print(f"    收益差:       {improvement:+.2f}%")
    print(f"    采用阈值:     +{min_improve:.1f}%")

    if improvement >= min_improve:
        save_active_params(opt_params, source="bayesian_optimization", score=optimizer.best_score)
        print(f"\n  ✅ 优化有效（+{improvement:.2f}% ≥ +{min_improve}%），已采用优化参数")
        result = {"action": "adopted", "params": opt_params, "improvement": round(improvement, 2)}
    else:
        rollback_to_baseline(f"优化收益差{improvement:+.2f}% < 阈值+{min_improve}%")
        print(f"\n  ❌ 优化无效（+{improvement:.2f}% < +{min_improve}%），已回退基线参数")
        result = {"action": "rolled_back", "params": baseline_params, "improvement": round(improvement, 2)}

    # 保存调度状态
    _save_schedule_state(result)
    return result


def _save_schedule_state(result: dict):
    """保存调度状态（用于判断下次何时触发）"""
    OPT_SCHEDULE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "last_optimize_ts": datetime.now(timezone.utc).isoformat(),
        "last_action": result.get("action"),
        "last_improvement": result.get("improvement", 0),
    }
    with open(OPT_SCHEDULE_STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def load_schedule_state() -> dict:
    """加载调度状态"""
    if OPT_SCHEDULE_STATE_FILE.exists():
        try:
            with open(OPT_SCHEDULE_STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_optimize_ts": None, "last_action": None, "last_improvement": 0}


def should_trigger_optimization(loss_streak: int = 0, trades_log: list = None) -> tuple:
    """判断是否应该触发优化

    触发条件（任一满足，且通过冷却期检查）：
    1. 连续亏损 ≥ loss_streak_trigger（默认3笔，事件驱动）
    2. 跨月（每月触发，周期驱动）

    冷却期：距上次优化 < cooldown_hours（默认24h）时，除连亏触发外不触发
    （连亏触发有最高优先级，冷却期内仍可触发，因为市场状态已变化）

    配置优先级：环境变量（.env.v15） > SCHEDULE_CONFIG 类常量

    返回: (should_trigger: bool, reason: str)
    """
    import os
    config = V15CapitalOptimizer.SCHEDULE_CONFIG.copy()
    # 从环境变量读取配置（覆盖默认值）
    config['loss_streak_trigger'] = int(os.environ.get('BAYESIAN_OPT_LOSS_STREAK_TRIGGER', config['loss_streak_trigger']))
    config['monthly_trigger'] = os.environ.get('BAYESIAN_OPT_MONTHLY', 'true').lower() == 'true'
    config['cooldown_hours'] = float(os.environ.get('BAYESIAN_OPT_COOLDOWN_HOURS', config.get('cooldown_hours', 24)))

    state = load_schedule_state()
    cooldown_h = config.get('cooldown_hours', 24)

    # 解析上次优化时间
    last_opt_ts = None
    if state.get("last_optimize_ts"):
        try:
            last_opt_ts = datetime.fromisoformat(state["last_optimize_ts"])
        except Exception:
            pass

    # 条件1：连续亏损触发（最高优先级，冷却期内仍可触发）
    if loss_streak >= config['loss_streak_trigger']:
        # 连亏触发也检查冷却期，避免短时间连续亏损导致频繁优化
        if last_opt_ts:
            hours_since = (datetime.now(timezone.utc) - last_opt_ts).total_seconds() / 3600
            if hours_since < cooldown_h:
                return False, f"连亏{loss_streak}笔但冷却期内（{hours_since:.1f}h < {cooldown_h}h）"
        return True, f"连续亏损{loss_streak}笔 ≥ {config['loss_streak_trigger']}笔触发阈值"

    # 首次运行：无历史记录直接触发
    if last_opt_ts is None:
        return True, "首次运行优化"

    # 冷却期检查（非连亏触发时）
    hours_since = (datetime.now(timezone.utc) - last_opt_ts).total_seconds() / 3600
    if hours_since < cooldown_h:
        return False, f"冷却期内（{hours_since:.1f}h < {cooldown_h}h）"

    # 条件2：每月触发（跨月检查，需 monthly_trigger=true）
    if config.get('monthly_trigger', True):
        now = datetime.now(timezone.utc)
        if last_opt_ts.month != now.month or last_opt_ts.year != now.year:
            return True, f"跨月触发（上次{last_opt_ts.strftime('%Y-%m')}）"

    return False, f"未达触发条件（距上次{hours_since:.1f}h）"


def get_loss_streak_from_trades(trades_log: list) -> int:
    """从交易日志中计算当前连续亏损笔数"""
    if not trades_log:
        return 0
    streak = 0
    for trade in reversed(trades_log):
        pnl = trade.get("pnl_pct", 0) if isinstance(trade, dict) else 0
        if pnl < 0:
            streak += 1
        else:
            break
    return streak


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="V15马丁策略贝叶斯参数优化")
    parser.add_argument("--coins", nargs="+", default=["BTC", "ETH", "SOL", "ARB", "OP", "UNI"], help="测试币种列表")
    parser.add_argument("--capital", type=float, default=10000.0, help="初始资金")
    parser.add_argument("--init-points", type=int, default=5, help="初始探索点数")
    parser.add_argument("--iterations", type=int, default=20, help="优化迭代次数")
    parser.add_argument("--iterative", action="store_true", help="启用三轮反馈迭代优化模式")
    parser.add_argument("--rounds", type=int, default=3, help="迭代轮数（默认3轮）")
    parser.add_argument("--save", action="store_true", help="保存结果到文件")
    parser.add_argument("--with-rollback", action="store_true", help="优化+自动回退验证（推荐定时调度使用）")
    parser.add_argument("--loss-streak", type=int, default=0, help="当前连续亏损笔数（用于触发判断）")
    parser.add_argument("--check-trigger", action="store_true", help="仅检查是否应该触发优化，不执行")
    parser.add_argument("--version-info", action="store_true", help="查看参数版本管理信息")
    parser.add_argument("--reset-to-smart", action="store_true", help="重置为智能参数基线（210.4%）")
    parser.add_argument("--reset-to-fixed", action="store_true", help="终极回退到固定参数基线（138%）")
    args = parser.parse_args()

    # 版本信息
    if args.version_info:
        print_version_info()
        exit(0)

    # 重置为智能参数基线
    if args.reset_to_smart:
        save_active_params(V15CapitalOptimizer.SMART_BASELINE_PARAMS.copy(),
                          source="manual_reset_to_smart", score=4112.87)
        print("✅ 已重置为智能参数基线（210.4%，贝叶斯优化后）")
        exit(0)

    # 终极回退到固定参数基线
    if args.reset_to_fixed:
        rollback_to_fixed_baseline("手动终极回退")
        exit(0)

    # 仅检查触发条件
    if args.check_trigger:
        should, reason = should_trigger_optimization(args.loss_streak)
        print(f"触发检查: {'是' if should else '否'} - {reason}")
        exit(0 if should else 1)

    # 优化+回退模式（定时调度推荐）
    if args.with_rollback:
        result = run_optimization_with_rollback(
            coins=args.coins, initial_capital=args.capital,
            init_points=args.init_points, n_iter=args.iterations,
        )
        print(f"\n最终结果: {result['action']} (收益差: {result['improvement']:+.2f}%)")
        exit(0)

    # 普通优化模式
    print(f"V15马丁策略贝叶斯参数优化")
    mode_str = "三轮反馈迭代优化" if args.iterative else "单次优化"
    print(f"模式: {mode_str}")
    print(f"测试币种: {args.coins}")
    print(f"初始资金: ${args.capital:,.2f}")
    print()

    optimizer = V15CapitalOptimizer(
        coins=args.coins,
        initial_capital=args.capital,
    )

    if args.iterative:
        best, round_results = optimizer.iterate_optimize(
            rounds=args.rounds,
            init_points=args.init_points,
            n_iter=args.iterations,
            save=args.save,
        )
    else:
        best = optimizer.optimize(
            init_points=args.init_points,
            n_iter=args.iterations,
            save=args.save,
        )

    print("最优参数:")
    for k, v in best.items():
        print(f"  {k}: {v}")
