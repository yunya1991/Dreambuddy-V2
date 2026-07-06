# Trading Transport Demo

## HTTP Inbox Server

```bash
python scripts/trading_demo/http_server.py --host 0.0.0.0 --port 8080 --inbox-dir artifacts/trading/http_inbox
```

Send an envelope:

```bash
python scripts/trading_demo/e2e_http_smoke.py
```

## Redis Streams Consumer

Consume from a stream:

```bash
python scripts/trading_demo/redis_streams_consumer.py \
  --redis-url "$REDIS_URL" \
  --stream dream.intelligence.a6.L1 \
  --last-id 0-0 \
  --block-ms 5000 \
  --out-dir artifacts/trading/redis_inbox
```

