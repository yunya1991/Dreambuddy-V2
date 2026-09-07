# 2026-09-01 V15 动态可用预算池设计（方案A·软额度下限保障型）

> 状态：初稿，等待用户review后进入实现
> 关联：14-V15经典马丁策略/lib/capital_manager.py · _resolve_capital_budget() · calculate_per_coin_allocation()
> 问题根因：OKX实盘avail_balance=$46（被L4 poll的BTC/ETH/SOL等仓位保证金占用$608.73），
>         per_coin_budget底仓=$8.53 < MIN_MARGIN_USD=$20 → 10个信号币全被"资金不足"门禁卡死。

---

## 1. 目标（成功标准）

1. V15策略有独立、可配置的「预算池」，不因L4/polling_trader占用全仓而永久无法开仓；
2. 满足用户「账户有多少可用余额就可以用」（马丁策略风险较低）：avail大时按avail全用；avail小时靠下限保障；
3. 总敞口不爆仓：硬上限钳制≤总权益×V15_MAX_RATIO_CAP；
4. 0配置生效：默认值下今日poll_once（2/3名额、conf=72%、STRONG_BULL）的BTC/HYPE等至少3币能通过资金门禁；
5. FAIL-OPEN：所有新配置读失败/类型错时回退硬编码安全默认值，不抛异常不阻塞交易。

---

## 2. 非目标

1. 不涉及OKX L4/polling_trader的资金与V15直接共享转账/拆账；
2. 不改变BASE_POSITION_PCT(22%)、ADDON1/2/3/4_PCT(5/10/20/35%)、LEVERAGE(5x)等马丁分配基线；
3. 不改变方向/信号/风控/加仓判定逻辑，只改预算池口径；
4. 不进行实际USDT入金，仅配置口径级动态计算。

---

## 3. 核心公式（§1 预算分子）

```python
# §1.1 预算池上限（含下限保障+上限钳制+利用系数放大）
raw_pool = max(V15_POOL_SIZE_USDT, OKX_avail_balance)  # 双下限取大：有现金属性优先，否则靠额度保障
pool_utilized = raw_pool * V15_BUDGET_UTIL_PCT          # 利用系数（1.0=原额；1.2=借20%保证金统一账户额度放大杠杆底仓可开）
cap_by_equity = OKX_total_eq * V15_MAX_RATIO_CAP        # 硬上限（总权益×比例，防止极端放大爆仓）
budget_pool_gross = clamp(pool_utilized, 0, cap_by_equity)  # 钳制到[0, 权益上限]
```

**今日账户场景（基线case）验算（默认值）**：
- V15_POOL_SIZE_USDT=200, OKX_avail=$46, OKX_eq=$654, UTIL=1.0, CAP=50%
- raw_pool = max(200, 46) = 200
- pool_utilized = 200 × 1.0 = 200
- cap_by_equity = 654 × 0.5 = 327
- budget_pool_gross = clamp(200, 0, 327) = $200 ✅
- 底仓 = 200 × 22% = $44 > $20 → 开仓允许 ✅

**avail大场景（L4清仓，avail=$500）验算**：
- raw_pool = max(200, 500) = 500 → 500 × 1.0 = 500 → 钳制≤327 = $327
- 底仓 = 327 × 22% = $72  → OK，不会all-in

---

## 4. 扣减项（§2 已用占用扣减）

```python
# §2.1 计算V15自己仓位的总占用（不含L4）
def _calc_v15_used(state_positions):
    """state中每个仓位pos.total_cost_usd（底仓+加仓+回撤保证金的预估）"""
    total = 0.0
    for pos in state_positions.values():
        # 用state已保存的per_coin_budget字段（开仓时已记录，是预算口径不是实际名义值）
        total += pos.get("per_coin_budget", 0) or 0
    return total

v15_used = _calc_v15_used(state["positions"]) if V15_DEDUCT_V15_USED else 0.0
budget_pool_net = max(budget_pool_gross - v15_used, 0)  # 净预算池，给remaining_slots分
```

**今日基线case验算（MU+LINK 2/3持仓）**：
- 假设 MU.per_coin_budget=$40, LINK.per_coin_budget=$40  → v15_used=$80
- budget_pool_net = 200 - 80 = $120（1个remaining_slot → base_per_coin=$120 × 22%=$26.4 > $20 ✅）

> 注：`calculate_per_coin_allocation(symbol, ..., pos_count_override=None, v15_used_usd=None, v15_state_positions=None)` 新增2个可选参数，不传递时回退0，保持向后兼容（FIX-C同样的override模式）。

---

## 5. MIN_MARGIN_USD 自适应（§3 小门不卡死小池）

```python
# §3.1 生效MIN_MARGIN = min( 配置MIN_MARGIN_USD=$20,  pool × V15_MIN_RATIO(10%),  硬地板$5 )
eff_min_margin = MIN_MARGIN_USD  # 默认20
if V15_DYNAMIC_MIN_MARGIN:
    ratio_bound = budget_pool_net * 0.10  # 预算池的10%作为MIN，保证≤10个独立单能平分
    eff_min_margin = max( 5.0, min(MIN_MARGIN_USD, ratio_bound) )
# 门禁改为：allowed = remaining_after > eff_min_margin AND base_usd >= eff_min_margin
```

**基线case**：pool_net=$120, ratio_bound=$12 → max($5, min($20, $12)) = $12。base_usd=$26.4>12 ✅。
**小池退化case**：pool_net=$30 → ratio_bound=$3 → min($20, $3)=$3→max(5,3)=$5。底仓=$30×22%=$6.6 ≥ $5 ✅，能开小微仓（之前会被$20卡死）。

---

## 6. 新增配置项（.env.v15，全部可选，不配置按默认生效）

| 变量名 | 默认 | 类型 | 说明 |
|--------|-----|------|------|
| V15_POOL_SIZE_USDT | 200.0 | float | 预算池下限保障（美元）。avail不足时按这张"信用卡额度"开仓。 |
| V15_BUDGET_UTIL_PCT | 1.0 | float | 利用系数，1.0=原始池，1.2=借20%保证金统一账户额度放大。 |
| V15_MAX_RATIO_CAP | 0.5 | float | 预算池硬上限 ≤ total_eq × ratio，防止all-in（0.5=≤50%权益）。 |
| V15_DEDUCT_V15_USED | true | bool | 是否扣减V15 state内已有仓位的per_coin_budget作为净预算池（推荐true）。 |
| V15_DYNAMIC_MIN_MARGIN | true | bool | 是否自适应MIN_MARGIN_USD（推荐true，小池不被20$硬门槛卡死）。 |
| V15_MIN_MARGIN_FLOOR | 5.0 | float | DYNAMIC_MIN的硬地板（美元），最小底仓名义值下限。 |

**读配置路径（FAIL-OPEN）**：capital_manager.py顶部 `get_config_float/get_config`，失败时用上方默认值；不抛异常（用 try/except 包裹，错类型/缺失→默认）。

---

## 7. 返回结构附带字段（日志/审计可观察）

`_resolve_capital_budget()` / `calculate_per_coin_allocation()` 返回的dict新增：

| 字段 | 类型 | 来源 |
|------|------|------|
| pool_size_usdt | float | 配置V15_POOL_SIZE_USDT实际生效值 |
| budget_pool_gross | float | §1钳制后的毛预算池 |
| v15_used_deducted | float | §2 V15仓位总占用（若DEDUCT=false则0） |
| budget_pool_net | float | §2净预算池=毛-已用（实际用于remaining_slots分配） |
| effective_min_margin | float | §3最终MIN门槛（$20或自适应） |
| dynamic_min_applied | bool | 是否启用了自适应MIN |

`_log`打印：资金分配日志中追加来源说明，例如
```
[BTC] 预算池: gross=$200 net=$120 min_margin=$12 source=POOL(avail=$46)
[BTC] 资金分配允许: base=$26.4 addon1/2/3/4=$6/$12/$24/$42 total=$110.4 remaining=$9.6
```

---

## 8. 变更点清单（实现范围）

1. **lib/capital_manager.py**：
   - 顶部新增6个配置项读取（安全默认值）；
   - `_resolve_capital_budget()`不改动（保持余额口径权威）；新增独立函数`_resolve_v15_budget_pool(cap, v15_used=0.0, state_positions=None)`专门算§1+§2；
   - `calculate_per_coin_allocation()`签名新增`v15_used_usd=None, v15_state_positions=None`两override参数（同FIX-C的override模式）；
   - alloc内§1用`_resolve_v15_budget_pool`替换`available_budget`；§3用新eff_min_margin替换固定MIN_MARGIN_USD门禁；
   - 返回结构追加6字段。

2. **core/v15_trader.py**：
   - 调用`calculate_per_coin_allocation`处（L1817-1823附近）多传2参数：
     `v15_used_usd = sum(p.get('per_coin_budget',0) for p in state['positions'].values())`；
   - 可选地打印一条"[币种] 预算池gross/net/min来源"debug级日志。

3. **config/.env.v15**：注释形式追加6个新配置说明（默认值即可=零配置生效，不显式赋值）。

4. **tests/**：
   - 新增tests/test_v15_budget_pool_dynamic.py：§1基线case（200/46/654→$200）、§1avail大case（500→$327上限）、§1UTIL=1.2（$200→240钳制≤327=$240）、§2 DEDUCT=true扣减（$80→net=$120）、§2 DEDUCT=false（net=$200）、§3 DYNAMIC_MIN小池$30→min=$5、§3 DYNAMIC=false→min=$20仍卡；
   - 断言 alloc["allowed"] 对基线case BTC conf72 pos2 = True（之前是False，根因修复验证）。

---

## 9. 风险与缓解

| 风险 | 等级 | 缓解 |
|------|------|------|
| 预算池按额度保障(POOL_SIZE=200)但OKX实际avail=$46，下单名义值>$46触发OKX端"Insufficient balance"拒单 | 中（资金路径） | ① U-Margin OKX在同一账户下跨仓位自动调保证金，$46名义/$608已用保证金统一账户$654权益远够；② 若拒单，`open_long/post_order`原有FAIL-OPEN流程不阻塞（log并回退state），③ 加配置开关`V15_REJECT_IF_CASH_LESS_THAN_BASE=true`(默认false)给强约束用户启用 |
| DEDUCT_V15_USED=true但state.positions中per_coin_budget字段不全/老仓缺失 → net预算高估 → V15净敞口超200 | 低 | per_coin_budget在state保存处（v15_trader L1015/L1982）已赋值3个月；老仓（如果有）=0则扣少 → net偏高但不超gross（钳制≤total_eq×CAP），整体安全 |
| UTIL>1.0借额度放大 → 名义敞口超权益×CAP → 爆仓风险 | 低（钳制层） | §1最后一步 clamp(0, eq×CAP) 永远约束，即使UTIL=5.0，raw_pool×5后仍被eq×0.5顶回$327 |
| DYNAMIC_MIN自适应到$5 → 底仓过小(>$1名义) → OKX最小名义值拒单 | 低 | V15_MIN_MARGIN_FLOOR=$5 且 OKX美股最小名义$1、加密币$0.1~1，$5安全；如后续发现某些币$5也拒→上调FLOOR |

---

## 10. 端到端验证清单（实现完成后必跑）

1. pytest tests/test_v15_budget_pool_dynamic.py exit 0；
2. pytest tests/test_v15_suite.py exit 0（回归无破坏）；
3. py_compile capital_manager.py + v15_trader.py 通过；
4. 跑`python3 run.py poll_once`（真实轮询17:08链路）：
   a. BTC(conf=72% strong_bull) alloc.allowed == True（之前=False，卡死根因）；
   b. 返回结构 budget_pool_gross=200, net≈120, effective_min_margin≈12；
   c. 日志打印 "预算池: gross=200 net=120 min_margin=12" 或类似；
   d. MU+LINK OCO挂单不被撤销（和上次poll_once一样0重挂）；
5. 手动脚本验证 6个新配置分别改值=生效，改乱（如非数字字符串）→ 回退默认值，不抛异常。
