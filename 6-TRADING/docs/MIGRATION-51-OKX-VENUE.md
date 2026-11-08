# 6-TRADING → 51 OKX 场所适配层迁移说明

> 版本：v0.1.0
> 日期：2026-11-07
> 关联：49 SPEC DEC-25 / R-L0-03、51-OKX CLI 系统 SPEC、47-MCP 硬约束
> 状态：🟡 迁移中（P1 守卫已落地；P3 完成封装替换）

---

## 1. 迁移结论

| 项 | 决策 |
|---|---|
| OKX CLI 封装归属 | 迁入 `51-OKX CLI 系统`（场所适配层） |
| 6-TRADING live 直连 | **退休**，默认 fail-closed |
| 6-TRADING demo/paper | 保留，但逐步改走 51 |
| 生产 live 唯一出口 | 11 域 `okx_client` 旁路（不变） |
| paper 唯一出口 | trade-exec MCP（不变） |

---

## 2. 资产映射

| 资产 | 原职责 | 迁移后 |
|---|---|---|
| `scripts/okx_cli.py` | CLI 封装（读/写） | 弃用兼容 shim；补齐 profile 注入；live 写 fail-closed |
| `scripts/okx_unified_toolkit.py` | spot/swap/option/grid/DCA 全能包 | 停止新增；spot/swap 由 51 承接；option/bot 单独立项 |
| `scripts/dream_trade_exec.py` | 直连 OKX `/api/v5/trade/order` | 降为调试/回放；默认退出；凭证默认不加载 |
| `bridge/api/trade_exec_api.py` | paper/live 双路径 | 下单仅 demo；live 余额查询保留（只读） |
| `scripts/dream_strategy_pipeline.py` | 自建 REST 签名客户端（含下单/算法单） | 读保留；live 写默认拒绝 |

> **补充发现（2026-11-07）**：`dream_strategy_pipeline.py` 内含第三套 OKX 签名客户端与 `place_order` / `place_algo_order`，原 R-L0-03 未列出。本轮已加 fail-closed 守卫，P3 需一并评估是否迁入 51 或标记只读。

---

## 3. 已落地的 fail-closed 守卫

### 3.1 总开关

```bash
# 默认 0：所有 legacy live 写路径拒绝
OKX_VENUE_LEGACY_LIVE=0

# 仅迁移期调试/回放；P3 完成后删除
OKX_VENUE_LEGACY_LIVE=1
```

**51 本身不读取该开关**，避免 legacy 语义污染新适配器。

### 3.2 文件级行为

| 文件 | 默认行为 | 开关打开后 |
|---|---|---|
| `scripts/okx_cli.py` | live profile 写操作返回 `live_trading_forbidden`；读操作正常 | 放行写操作（仍打印弃用告警） |
| `scripts/dream_trade_exec.py` | `main()` 立即退出（返回码 2）；`.env` 不加载 | 原逻辑运行（调试/回放） |
| `scripts/dream_strategy_pipeline.py` | `place_order` / `place_algo_order` 抛 `RuntimeError`；读操作正常 | 放行写操作 |
| `scripts/okx_unified_toolkit.py` | `profile=A5`（live）且非 `--dry-run` → `RuntimeError`；demo/dry-run 正常 | 放行 live 执行（调试） |
| `bridge/api/trade_exec_api.py` | 下单端点使用 `OKXCLI(profile='paper')` → demo；live 余额查询只读 | 不适用 |

### 3.3 同时修复的隐患

原 `okx_cli.py`：

- `__init__(profile=...)` 保存了 profile，但 `_run()` **从未注入** `--profile` → `OKXCLI(profile='live')` 实际可能走默认 profile；
- `get_balance` / `get_positions` 未传 `--json`，依赖文本解析；
- `get_ticker --json` 返回列表，但调用方按 dict 使用。

本轮已修复：强制注入 `--profile`、统一 `--json`、归一化列表输出。

---

## 4. 验收清单

- [x] `okx_cli.py` 注入 `--profile`，`paper` 映射到 demo profile
- [x] `okx_cli.py` live 写默认拒绝
- [x] `dream_trade_exec.py` 默认退出且不加载 `.env`
- [x] `dream_strategy_pipeline.py` live 写默认拒绝
- [x] `trade_exec_api.py` 下单端点仅 demo
- [x] 51 单元测试 35 用例全绿
- [ ] P3：`okx_cli.py` 改为真正的 51 shim
- [ ] P3：`okx_unified_toolkit.py` spot/swap 重复实现清理
- [ ] P3：49 SPEC R-L0-03 状态更新为“已收口”

---

## 5. 回滚

- 迁移期如必须恢复 legacy live：设置 `OKX_VENUE_LEGACY_LIVE=1`，并记录告警。
- **不得**通过修改 51 的代码或配置绕过；51 没有 live 写路径。
- P3 完成后该开关删除，回滚路径随之关闭。

---

## 6. 运行示例

```bash
# 默认：legacy live 脚本拒绝运行
python 6-TRADING/scripts/dream_trade_exec.py
# → dream_trade_exec.py is retired ... (exit 2)

# 迁移期调试（谨慎）
OKX_VENUE_LEGACY_LIVE=1 python 6-TRADING/scripts/dream_trade_exec.py

# 新路径：51 demo 适配器
python -m pytest "51-OKX CLI 系统/tests" -q
```