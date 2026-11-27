# 验收报告：50 域按波动率自出 SL/TP

## 基本信息
- 验收对象：50 live 决策按标的 ATR 波动率声明 `sl_pct/tp_pct`（22 执行器最高优先级覆盖，不再固定 1.5%/3.0%）
- 验收时间：2026-11-28 01:40（CST）/ 2026-11-27T17:40Z（UTC）
- 关联 commit：`81a0cc44df`（本地 → GitHub → 云端 ff-only 同步，云端 HEAD 一致）
- 验收人：AI（五维证据见下）

## 需求与实现口径
- 需求：让 50 域自己按波动率出 SL/TP，写入 50 决策（`sl_pct/tp_pct` 顶层字段），22 已支持最高优先级覆盖，无需改 22。
- 实现：
  - `50/core/volatility.py`：Wilder ATR(14) → `sl_pct = clamp(2×ATR%, 类别下限, 8)`、`tp_pct = clamp(2×sl_pct, 2×类别下限, 16)`；ATR 缺失/脏值（>30%）退回类别下限（与 22 `sl_tp.asset_class` 对齐）。
  - `50/adapters/volatility_adapter.py`：OKX 公开 K 线（4H×60，5s 超时，无凭据），任何异常 fail-open 返回 0。
  - `50/tools/run_live.py`：执行权通过后写入决策顶层 `sl_pct/tp_pct` + `payload.sl_tp` 归因，M11 链路事件带 `sl_pct/tp_pct/atr_pct`。
  - 22 不改动：`_resolve_sl_tp` 既有优先级「决策自带 > symbols > asset_class > default」。

## 五维证据矩阵

| 维度 | 状态 | 证据 | 备注 |
|------|------|------|------|
| 症状复测 | ✅ | `repro_after.log` §2：定时器 17:37Z 轮次生产决策 `observed_symbol=XAG-USDT-SWAP observed_sl_pct=4.39 observed_tp_pct=8.78`，`payload.sl_tp.source=atr`（改造前该字段为 `None`） | 用生产定时器轮次而非手工造数 |
| 日志证据 | ✅ | `repro_after.log` §4：云端实跑适配器 `xag_atr_pct=2.2005` → `{'sl_pct': 4.4, 'tp_pct': 8.8, 'source': 'atr'}`；§3：22 `_resolve_sl_tp` 对决策自带值返回 `(4.39, 8.78)`，无声明时返回类别配置 `(3.0, 6.0)` | 决策路径 + 执行解析双端可 grep |
| 回归测试 | ✅ | `test.log`：本地 50 全域 `296 passed`，`LOCAL_EXIT=0`；云端 venv `20 passed`（新增两文件），`CLOUD_EXIT=0` | 单测已禁网（autouse fixture） |
| 影响面 | ✅ | `fix.diff`：5 文件 +335 行（2 新增实现 + 2 测试文件 + run_live 11 行接线），未触碰 22 与注册表 | 与需求「无需再改 22」一致 |
| 边界验证 | ✅ | 单测覆盖：ATR 样本不足=0、低波动退类别下限、高波动封顶（SL 8/TP 16，满足 22 的 `0<sl<10`/`0<tp<20`）、脏值 88% 退下限、未知类别默认 2.5%；生产 22 本轮 skip 原因为 `cooldown/symbol_already_open/symbol_not_allowed`，无 `invalid_sltp` | 22 边界由既有校验兜住 |

## 红旗清单
- 22 本轮无新成交（同批证据 `decision_id` 已 processed + 8h 冷静期），因此「新 sl/tp 随真实开仓落到 OCO」的实证需等新信号（代码路径由 §3 解析结果与既有 audit 保证）。非阻塞。

## 验收结论
- [x] 五维全通过 → 验收通过（红旗 1 项已说明，不影响结论）
- [ ] 有红旗 → 验收不通过

## 签字
AI 验收：2026-11-28
用户确认：（可选）
