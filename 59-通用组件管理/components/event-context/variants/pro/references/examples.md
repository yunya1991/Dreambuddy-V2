# 返回样例（脱敏）

## 1. events（事件清单）

```bash
python3 scripts/pay.py --cmd events --subject AAPL --since 30 --proof <Payment-Proof>
```

```json
{
  "rows": [
    {
      "event_id": "e3b0c44298fc1c14",
      "occurred_at": "2026-10-30",
      "source": "SEC EDGAR",
      "type": "10-K",
      "subject": "AAPL",
      "key_facts": ["Revenues 412.3B", "NetIncomeLoss 102.4B"],
      "url": "https://www.sec.gov/Archives/edgar/...",
      "license": "public-domain",
      "retrieved_at": "2026-11-20T01:00:00+08:00"
    }
  ],
  "missing": [],
  "data_date": "2026-11-20",
  "sources": [{"name": "SEC EDGAR", "license": "public-domain"}],
  "method_ids": ["events.list_by_subject.v1"]
}
```

## 2. event-context（五层装配）

```bash
python3 scripts/pay.py --cmd event-context --subject AAPL --latest --proof <Payment-Proof>
```

```json
{
  "event": {"event_id": "e3b0c44298fc1c14", "subject": "AAPL", "type": "10-K", "occurred_at": "2026-10-30"},
  "entities": [{"name": "Apple Inc.", "cik": "0000320193", "role": "issuer"}],
  "analogues": {"n": 37, "window": "10y", "scope": "same subject + same form"},
  "sources": [{"name": "SEC EDGAR", "license": "public-domain", "retrieved_at": "2026-11-20T01:00:00+08:00"}],
  "assembly": {"layers": 5, "steps": ["event", "entities", "analogues", "sources", "assembly"]}
}
```

`analogues.n` 只表示同类事件的历史发生次数，不做统计推断。

## 3. 只检查请求体（不联网）

```text
$ python3 scripts/pay.py --cmd event-context --subject AAPL --latest --describe
{
  "skill": "event-context",
  "cmd": "event-context",
  "params": {"subject": "AAPL", "latest": true}
}
```

`--latest` 是布尔开关，不接收取值；写成 `--latest true` 会报参数错误。

## 4. 幂等重放

同一凭证再次提交时返回首次结果，末尾提示：

```text
（该订单此前已交付，本次为幂等重放，未重复扣费）
```
