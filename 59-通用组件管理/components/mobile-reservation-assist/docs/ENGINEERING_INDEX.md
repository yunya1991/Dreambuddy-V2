# 工程索引 — 手机预约助手（mobile-reservation-assist）

## 目录

```
mobile-reservation-assist/
├── component.yaml
├── docs/                      ENGINEERING_INDEX / TECHNICAL_DESIGN / API_SPEC / CHANGELOG
├── skill/
│   ├── SKILL.md
│   ├── scripts/
│   │   ├── mra.py             CLI 入口
│   │   ├── ingest.py          上游命中归一 + 入队
│   │   ├── store.py           SQLite（jobs/results/events）
│   │   ├── gateway.py         本地 HTTP 指令网关
│   │   ├── executor.py        作业→指令 + 门禁 + 回执落库
│   │   ├── notify.py          通知通道
│   │   ├── security.py        redact / Token / 容器判定
│   │   └── phone_adapters/    6 平台手机动作定义（平台专属信息仅在此）
│   └── references/            adapters.md / compliance.md
├── agent/
│   └── reservation_agent.js   Auto.js 手机端常驻 Agent（复用现有工程）
└── tests/                     contract/store/ingest/gateway/executor/architecture + golden + fixtures
```

## 关键契约

- 输出：`reservation.v1`（见 59域 contracts/output.schema.json）。
- 上游：只读消费 `reservation-assist` 的公开 CLI（`report --json` / `watch list --json`），不 import、不写死路径。
- 治理：通过 59域 `make check`（G1–G7）。

## 常用命令

```bash
python3 skill/scripts/mra.py ingest --source file:tests/fixtures/feed_basic.json
python3 skill/scripts/mra.py gateway --port 8765
python3 skill/scripts/mra.py jobs --json
python3 skill/scripts/mra.py report --json
```
