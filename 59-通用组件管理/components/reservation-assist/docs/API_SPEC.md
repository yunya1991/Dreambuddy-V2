# API 契约 — reservation-assist

## 1. CLI

```
ra watch add --adapter <name> --target <json|@file> --rule <json|@file>
             --window "<start>/<end>" [--interval ms] [--notify feishu,local] [--submit]
ra watch list [--json]
ra watch rm <task_id>
ra watch grant <task_id>      # 必须 tty
ra watch revoke <task_id>
ra watch run [--task <id>] [--once] [--foreground]
ra watch pause-all | resume-all
ra notify test --channel <feishu|local>
ra doctor [--json] [--purge]
ra reconcile <task_id> [--close]
ra report [--date YYYY-MM-DD] [--json]
ra drill login --adapter <name> --state <ok|expired|unknown>
ra drill submit --adapter <name> --result <ok|wrong_target|duplicate> [--captcha none|manual|blocked]
ra drill check --adapter <name> [--json]
ra auth set --adapter <name>        # Cookie 从 stdin 读入
ra auth status [--json]
ra auth clear --adapter <name>
ra auth feishu                      # webhook 从 stdin 读入
ra watch notify <task_id> --channels feishu,local
ra notify test --channel feishu
ra install | uninstall
```

退出码：`0` 成功 / `2` 参数错误 / `3` 门禁拒绝（含就绪实验未通过） / `4` 登录态失效 / `5` 平台不可达 / `6` 需人工对账。

`ra drill check` 判定门槛：登录态 ≥3 个自然日、≥30 次采样；演练 ≥20 次；0 次错目标/重复单；0 次需人工验证。通过只代表「可人工开启 `SUBMIT_READY`」，代码不会自动开启。

## 2. `reservation.v1`

必填：`schema_version / command / generated_at / tasks / hits / events / limits`。

```json
{
  "schema_version": "1.0",
  "command": "report",
  "generated_at": "2026-11-20T20:00:00+08:00",
  "tasks": [{"id": "t1", "adapter": "railway", "status": "armed",
             "window_start": 1764547200000, "window_end": 1764547800000}],
  "hits": [{"task_id": "t1", "fingerprint": "…", "at": 1764547300000, "result": "notified"}],
  "events": [{"at": 1764547300000, "level": "info", "code": "hit", "task_id": "t1"}],
  "missing": [],
  "limits": "仅监控与官方页面跳转，不代抢、不转售、不支付。"
}
```

`tasks[].status ∈ {armed, hit, notified, submitted, unknown}`；`hits[].result` 取 `submit_state`，未提交时为 `hit` / `notified`。

## 3. 适配器协议

```python
class Adapter(Protocol):
    NAME: str
    MIN_INTERVAL_MS: int
    SUBMIT_READY: bool
    def probe(self, target: dict, transport: Transport) -> Snapshot: ...
    def match(self, snap: Snapshot, rule: dict, task_id: str = "") -> list[Hit]: ...
    def handoff(self, hit: Hit) -> str: ...
    def submit(self, hit: Hit, grant: Grant, transport: Transport) -> SubmitResult: ...
```

错误类型：`GateDenied / AuthExpired / RateLimited / PlatformChanged / TransportError / SubmitUnknown`。

fixture：`tests/fixtures/<adapter>/<case>/{request.json,response.txt,expected.json}`。
