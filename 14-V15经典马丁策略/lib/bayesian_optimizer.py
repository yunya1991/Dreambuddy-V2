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


def load_backtest_module():
    import sys
    core_path = str(STRATEGY_DIR / "core")
    if core_path not in sys.path:
        sys.path.insert(0, core_path)
    import v15_backtest
    return v15_backtest


class V15CapitalOptimizer:
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
        
        # 参数空间：资金分配 + 持仓时间
        self.params_space = {
            'addon1_pct': (0.05, 0.20),
            'addon2_pct': (0.05, 0.25),
            'addon3_pct': (0.10, 0.30),
            'max_concurrent_positions': (2, 6),
            'max_base_holding_hours': (24, 96),
            'max_post_addon_hours': (12, 48),
            'golden_window_hours': (4, 24),
        }
        
        self._klines_cache = {}
        self._preload_klines()
        
        self._coin_volatility = {}
        self._btc_volatility = 0.02
        self._calc_volatilities()
        
        self._level_stats = {}
        self._run_base_backtest()
        
        print(f"  固定参数: 底仓{self.fixed_base_position_pct*100:.0f}% | 杠杆{self.fixed_leverage:.0f}x | BTC止盈{self.fixed_tp_pct_btc*100:.0f}% | 趋势过滤: none")
        print(f"  优化参数空间:")
        for k, v in self.params_space.items():
            if k == 'max_concurrent_positions':
                print(f"    {k}: {int(v[0])} - {int(v[1])}")
            elif 'hours' in k:
                print(f"    {k}: {v[0]:.1f} - {v[1]:.1f}h")
            else:
                print(f"    {k}: {v[0]:.4f} - {v[1]:.4f}")
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
        """运行基准回测（无趋势过滤），统计各层收益特征"""
        print("  运行基准回测，统计各层收益特征...")
        
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
            
            capital_per_coin = self.initial_capital / len(self.coins)
            base_usd, addon_usd, total_per_position = self._calculate_capital_allocation(
                capital_per_coin, self.fixed_base_position_pct, 0.05, 0.05, 0.10
            )
            effective_base_pct = total_per_position / capital_per_coin
            
            coin_vol = self._coin_volatility.get(coin, self._btc_volatility)
            vol_ratio = coin_vol / self._btc_volatility if self._btc_volatility > 0 else 1.0
            vol_ratio = max(0.5, min(2.0, vol_ratio))
            tp_pct_coin = self.fixed_tp_pct_btc * vol_ratio
            
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
                trend_filter_mode="none",
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
            addon1_pct = params['addon1_pct']
            addon2_pct = params['addon2_pct']
            addon3_pct = params['addon3_pct']
            max_concurrent_positions = int(round(params['max_concurrent_positions']))
            max_base_holding_hours = params['max_base_holding_hours']
            max_post_addon_hours = params['max_post_addon_hours']
            golden_window_hours = params['golden_window_hours']
            
            trend_filter_mode = "none"
            trend_filter_period = 200
            
            coins_to_test = self.coins[:max_concurrent_positions]
            capital_per_coin = self.initial_capital / max_concurrent_positions
            
            base_usd, addon_usd, total_per_position = self._calculate_capital_allocation(
                capital_per_coin, self.fixed_base_position_pct, addon1_pct, addon2_pct, addon3_pct
            )
            
            effective_base_pct = total_per_position / capital_per_coin
            
            total_score = 0
            total_trades = 0
            valid_coins = 0
            
            for coin in coins_to_test:
                klines = self._klines_cache.get(coin)
                if not klines or len(klines) < 200:
                    continue
                
                # 按波动率放大止盈
                coin_vol = self._coin_volatility.get(coin, self._btc_volatility)
                vol_ratio = coin_vol / self._btc_volatility if self._btc_volatility > 0 else 1.0
                vol_ratio = max(0.5, min(2.0, vol_ratio))
                tp_pct_coin = self.fixed_tp_pct_btc * vol_ratio
                
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
                    trend_filter_mode=trend_filter_mode,
                    trend_filter_period=trend_filter_period,
                    max_base_holding_hours=max_base_holding_hours,
                    max_post_addon_hours=max_post_addon_hours,
                    golden_window_hours=golden_window_hours,
                )
                
                if "error" in result:
                    continue
                
                metrics = result["metrics"]
                
                capital_alloc = {
                    'base': base_usd,
                    'addon1': addon_usd[0],
                    'addon2': addon_usd[1],
                    'addon3': addon_usd[2],
                }
                
                score = self._calculate_objective_score(metrics, capital_alloc)
                
                total_score += score
                total_trades += metrics.get('total_trades', 0)
                valid_coins += 1
            
            if valid_coins == 0:
                return -1000.0
            
            avg_score = total_score / valid_coins
            
            param_dict = {
                'leverage': self.fixed_leverage,
                'base_position_pct': self.fixed_base_position_pct,
                'tp_pct_btc': self.fixed_tp_pct_btc,
                'trend_filter_mode': trend_filter_mode,
                'trend_filter_period': trend_filter_period,
                'addon1_pct': round(addon1_pct, 4),
                'addon2_pct': round(addon2_pct, 4),
                'addon3_pct': round(addon3_pct, 4),
                'max_concurrent_positions': max_concurrent_positions,
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
            'leverage': self.fixed_leverage,
            'base_position_pct': self.fixed_base_position_pct,
            'tp_pct_btc': self.fixed_tp_pct_btc,
            'trend_filter_mode': 'none',
            'trend_filter_period': 200,
            'addon1_pct': round(best_p['addon1_pct'], 4),
            'addon2_pct': round(best_p['addon2_pct'], 4),
            'addon3_pct': round(best_p['addon3_pct'], 4),
            'max_concurrent_positions': int(round(best_p['max_concurrent_positions'])),
            'max_base_holding_hours': round(best_p['max_base_holding_hours'], 1),
            'max_post_addon_hours': round(best_p['max_post_addon_hours'], 1),
            'golden_window_hours': round(best_p['golden_window_hours'], 1),
        }
        
        self.best_params = best_params
        
        max_concurrent = best_params['max_concurrent_positions']
        coins_to_test = self.coins[:max_concurrent]
        capital_per_coin = self.initial_capital / max_concurrent
        
        base_usd, addon_usd, total_per_position = self._calculate_capital_allocation(
            capital_per_coin, best_params['base_position_pct'],
            best_params['addon1_pct'], best_params['addon2_pct'], best_params['addon3_pct']
        )
        
        print(f"\n{'='*70}")
        print("  资金分配建议报告")
        print(f"{'='*70}")
        print(f"  验证币种: {coins_to_test}")
        print(f"  总资金: ${self.initial_capital:,.2f}")
        print(f"  可开仓数: {max_concurrent}")
        print(f"  单币种资金: ${capital_per_coin:,.2f}")
        print(f"  优化耗时: {elapsed:.1f}秒")
        
        print(f"\n  --- 策略定位 ---")
        p = best_params
        print(f"    底仓: {p['base_position_pct']*100:.0f}%资金 + {p['leverage']:.0f}x杠杆 ≈ {p['base_position_pct']*p['leverage']*100:.0f}%现货敞口")
        print(f"    止盈: BTC {p['tp_pct_btc']*100:.0f}%（其他币种按波动率放大）")
        print(f"    趋势过滤: none（动态止损线提供保护）")
        print(f"    优化目标: 回撤控制优先 + 资金效率")
        
        print(f"\n  --- 止盈比例（按波动率放大）---")
        tp_btc = p['tp_pct_btc']
        for coin in coins_to_test:
            coin_vol = self._coin_volatility.get(coin, self._btc_volatility)
            vol_ratio = coin_vol / self._btc_volatility if self._btc_volatility > 0 else 1.0
            vol_ratio = max(0.5, min(2.0, vol_ratio))
            print(f"    {coin}: {tp_btc*vol_ratio*100:.1f}% (波动率{vol_ratio:.2f}x)")
        
        print(f"\n  --- 单币种资金分配 ---")
        total_capital = base_usd + sum(addon_usd)
        addon_total = sum(addon_usd)
        print(f"    底仓:   ${base_usd:,.2f} ({base_usd/total_capital*100:.1f}%) ← 平时赚止盈")
        print(f"    加仓1:  ${addon_usd[0]:,.2f} ({addon_usd[0]/total_capital*100:.1f}%) ← 黑天鹅第1档")
        print(f"    加仓2:  ${addon_usd[1]:,.2f} ({addon_usd[1]/total_capital*100:.1f}%) ← 黑天鹅第2档")
        print(f"    加仓3:  ${addon_usd[2]:,.2f} ({addon_usd[2]/total_capital*100:.1f}%) ← 黑天鹅第3档")
        print(f"    单仓位: ${total_per_position:,.2f}")
        print(f"    加仓总资金: ${addon_total:,.2f} ({addon_total/total_capital*100:.1f}%)")
        
        print(f"\n  --- 验证回测结果 ---")
        effective_base_pct = total_per_position / capital_per_coin
        for coin in coins_to_test:
            klines = self._klines_cache.get(coin)
            if not klines or len(klines) < 200:
                continue
            
            coin_vol = self._coin_volatility.get(coin, self._btc_volatility)
            vol_ratio = coin_vol / self._btc_volatility if self._btc_volatility > 0 else 1.0
            vol_ratio = max(0.5, min(2.0, vol_ratio))
            tp_pct_coin = p['tp_pct_btc'] * vol_ratio
            
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
                trend_filter_mode=p['trend_filter_mode'],
                trend_filter_period=p['trend_filter_period'],
                max_base_holding_hours=p.get('max_base_holding_hours', 48.0),
                max_post_addon_hours=p.get('max_post_addon_hours', 24.0),
                golden_window_hours=p.get('golden_window_hours', 12.0),
            )
            
            if "error" in result:
                continue
            
            m = result["metrics"]
            leveraged_ret = m['total_return_pct'] * p['leverage']
            leveraged_dd = m['max_drawdown_pct'] * p['leverage']
            print(f"    {coin}: 收益{leveraged_ret:+.2f}% | 回撤{leveraged_dd:.2f}% | 胜率{m['win_rate']*100:.1f}% | {m['total_trades']}次交易")
        
        print(f"{'='*70}\n")
        
        if save:
            self._save_results()
        
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


if __name__ == "__main__":
    main()
