# 51-OKX CLI 系统（OKX Venue Adapter）

> 版本：v0.1.0
> 状态：🟢 P1 骨架已落地；P2 trade-exec MCP 接线待评审
> 定位：**执行层（EXEC/L1.5）的 OKX 场所适配层**，不是交易系统、不是执行出口、不是 MCP 壳。

---

## 这个模块解决什么

把 OKX 官方 CLI（`@okx_ai/okx-trade-cli`）的命令面收束为**受治理的 Port**，供 trade-exec MCP 在 demo 模式下使用；同时收编 6-TRADING 里散落的 OKX CLI 封装，落地 49 SPEC 的 DEC-25 / R-L0-03。

**三条硬边界（2026-11-07 用户决策）：**

1. 51 = 场所适配层（不新建独立执行出口）
2. live 暂不交给 51，保持 11 域 okx_client 旁路
3. 6-TRADING 的 OKX CLI 封装迁入 51，legacy 直连路径 fail-closed

完整设计见 [SPEC.md](./SPEC.md)。

---

## 快速开始

### 1. 安装 OKX CLI（锁定版本）

```bash
npm install -g @okx_ai/okx-trade-cli@1.5.0
okx --version
```

> 生产环境建议预装并把 `OKX_VENUE_CLI` 指到固定路径；不要让运行时执行 `npm install`。

### 2. 配置 demo profile（只配 demo，不要配 live）

```bash
okx config init      # 选择站点并完成 OAuth / API Key 配置
okx --profile demo account balance
```

或手写 `~/.okx/config.toml`：

```toml
default_profile = "demo"

[profiles.demo]
api_key = "your-demo-api-key"
secret_key = "your-demo-secret-key"
passphrase = "your-demo-passphrase"
demo = true
```

**禁止**在 51 的 profile 中配置 live 密钥；live 由 11 域旁路独立管理。

### 3. 运行测试

```bash
python -m pytest "51-OKX CLI 系统/tests" -q
```

### 4. 在 Python 中使用

```python
from okx_venue import OkxCliVenue, VenueConfig

venue = OkxCliVenue(VenueConfig(profile="demo", mode="demo"))

print(venue.get_ticker("BTC-USDT-SWAP"))
print(venue.get_balance())
venue.place_order("BTC-USDT-SWAP", "buy", 1, td_mode="cross")
```

> 需要把 `51-OKX CLI 系统/src` 加入 `sys.path`，或安装为本地包。

---

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `OKX_VENUE_CLI` | `okx` | CLI 路径 |
| `OKX_VENUE_PROFILE` | `demo` | OKX profile 名 |
| `OKX_VENUE_MODE` | `demo` | `demo` / `live` |
| `OKX_VENUE_AUTH` | `api_key` | `api_key` / `oauth` |
| `OKX_VENUE_TIMEOUT_S` | `30` | 单条 CLI 超时 |
| `OKX_VENUE_ALLOW_LIVE_READ` | `0` | 允许 live 只读（写仍拒绝） |
| `OKX_VENUE_AUDIT_PATH` | `runtime/audit/venue_calls.jsonl` | 审计日志 |

**live 写永远拒绝**，不提供开关。

---

## 目录结构

```text
51-OKX CLI 系统/
├── SPEC.md                  # 设计规格（定位/Port/边界/迁移/阶段）
├── README.md                # 本文件
├── docs/
│   ├── ENGINEERING_INDEX.md # 工程索引
│   ├── TECHNICAL_DESIGN.md  # 技术设计
│   ├── API_SPEC.md          # Port API 契约
│   └── CHANGELOG.md         # 变更记录
├── src/okx_venue/
│   ├── config.py            # profile / mode / 环境变量
│   ├── catalog.py           # 命令白名单
│   ├── runner.py            # subprocess + JSON + 审计
│   ├── adapter.py           # Port 实现 + 结果归一化
│   └── errors.py            # 错误模型
├── tests/                   # 单元测试
└── runtime/audit/           # 审计 JSONL（运行时生成）
```

---

## 不做什么

- 不生成信号、不做策略、不做风控/定容
- 不承载 live 下单（live 唯一出口 = 11 旁路）
- 不新增 MCP shell / MCP 工具（trade-exec 仍 10 工具）
- 首期不做 bot / earn / event / 期权 / 交割

---

## 相关文档

- [SPEC-49 交易框架协议](../49-交易框架协议/SPEC.md)（DEC-25 / R-L0-03）
- [SPEC-L0-TRADE-EXEC-MCP-v0.1](../47-MCP管理系统/docs/tech/SPEC-L0-TRADE-EXEC-MCP-v0.1.md)
- [47-MCP 管理系统](../47-MCP管理系统/README.md)
- [6-TRADING 迁移说明](../6-TRADING/docs/MIGRATION-51-OKX-VENUE.md)