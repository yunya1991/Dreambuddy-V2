# 工程索引 — reservation-assist

| 项 | 值 |
|---|---|
| 组件 | `reservation-assist` v0.1.0（P0 骨架） |
| 契约 | `output_contract: reservation.v1`，`kernel_deps: []` |
| 依据 | `docs/SPEC-20261120-预约助手-reservation-assist-v0.2.md` |
| 测试 | `python3 -m unittest discover -s tests -v`（离线，FakeTransport / FakeNotifier） |
| 状态库 | `~/.reservation-assist/state.db`（0700，SQLite WAL） |

## 目录

| 路径 | 作用 |
|---|---|
| `skill/scripts/ra.py` | CLI 入口：watch / notify / doctor / reconcile / report / install |
| `skill/scripts/scheduler.py` | 对时、虚拟时钟、节拍、退避、熔断、唤醒检测 |
| `skill/scripts/store.py` | SQLite DDL、幂等、TTL、grant 表 |
| `skill/scripts/notify.py` | 通道协议、真实通道、只通知一次 |
| `skill/scripts/security.py` | redact、容器判定、grant 签发与提交门禁 |
| `skill/scripts/launchd.py` | plist 渲染/安装/卸载/自检 |
| `skill/scripts/adapters/` | 六个平台适配器 + 注册表 + fixture 契约 |
| `skill/templates/` | launchd 模板（`__HOME__` 占位，禁写死路径） |
| `skill/references/` | 适配器手册、合规边界、统计方法 |
| `tests/` | 7 个测试文件 + golden + fixtures |

## 关键约束

- 平台词只允许出现在 `adapters/`（`tests/test_architecture.py` 扫描）
- 自动提交三重门禁 + tty 一次性 grant；`SUBMIT_READY=False` 一律拒绝
- 不调用锁座/占座接口（`test_submit_gate.py` 断言）
- 测试期零外网；真实通道只在运行期使用
