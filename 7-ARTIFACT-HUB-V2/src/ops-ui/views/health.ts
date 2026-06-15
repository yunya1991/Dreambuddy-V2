export function renderHealth(): string {
  return `<!doctype html><html><head><meta charset="utf-8" /><title>ops-ui health</title></head><body style="margin:18px;font:14px/1.4 system-ui;"><h1 style="margin:0 0 12px 0;font:600 18px/1.2 system-ui;">ops-ui</h1><ul style="margin:0;padding-left:18px;"><li><a href="/health">/health</a></li><li><a href="/api/ops/ledger/tasks">/api/ops/ledger/tasks</a></li><li><a href="/api/ops/ledger/rewards">/api/ops/ledger/rewards</a></li><li><a href="/">/</a></li></ul></body></html>`;
}
