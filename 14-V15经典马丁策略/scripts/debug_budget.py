#!/usr/bin/env python3
import sys, os
wd = '/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/14-V15经典马丁策略'
os.chdir(wd)
sys.path.insert(0, os.path.join(wd,'lib'))
from dotenv import load_dotenv
load_dotenv(os.path.join(wd,'config/.env.v15'))
print('配置当前值：')
for k in ['TOTAL_BUDGET','MAX_CONCURRENT_POSITIONS','BASE_POSITION_PCT','ADDON1_PCT','ADDON2_PCT','ADDON3_PCT','ADDON4_PCT','V15_CAPITAL_MODE','V15_USE_KELLY','MAX_POSITION_PCT','MIN_MARGIN_USD','LEVERAGE']:
    v = os.environ.get(k)
    print(f'  {k} = {v}')
print()
from capital_manager import _resolve_capital_budget, calculate_per_coin_allocation, TOTAL_BUDGET, V15_CAPITAL_MODE, BASE_POSITION_PCT, ADDON1_PCT, ADDON2_PCT, ADDON3_PCT, ADDON4_PCT, MAX_CONCURRENT_POSITIONS
print('capital_manager载入值：TOTAL_BUDGET=%.2f  MODE=%s  BASE=%.3f  ADD1/2/3/4=%.3f/%.3f/%.3f/%.3f  MAX_POS=%d' % (TOTAL_BUDGET, V15_CAPITAL_MODE, BASE_POSITION_PCT, ADDON1_PCT, ADDON2_PCT, ADDON3_PCT, ADDON4_PCT, MAX_CONCURRENT_POSITIONS))
cap = _resolve_capital_budget()
print('_resolve_capital_budget: mode=%s src=%s fallback=%s total_eq=$%.2f avail=$%.2f used_margin=$%.2f' % (cap['mode'], cap['budget_source'], cap['fallback_used'], cap['total_eq'], cap['avail_balance'], cap['used_margin']))
for sym, conf, elder, poso in [('BTC',72,{'direction':'STRONG_BULL','strength':80,'ema_trend':'up'},2), ('HYPE',72,{'direction':'STRONG_BULL','strength':70,'ema_trend':'up'},2)]:
    alloc = calculate_per_coin_allocation(sym, confidence=conf, elder_ray=elder, pos_count_override=poso)
    reason = '' if alloc['allowed'] else alloc.get('reason','资金不足')
    print('%s alloc(conf=%d,pos=%d): allowed=%s %s base=$%.2f total=$%.2f drawdown=$%.2f remaining=$%.2f avail=$%.2f per_budget=$%.2f slots=%d/%d' % (
        sym, conf, poso, alloc['allowed'], reason, alloc['base_usd'], alloc['total_usd'], alloc['drawdown_margin'], alloc['remaining_after'], alloc['available_budget'], alloc['per_coin_budget'], alloc['remaining_slots'], MAX_CONCURRENT_POSITIONS))
