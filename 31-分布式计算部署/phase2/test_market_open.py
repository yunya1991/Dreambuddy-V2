import sys
sys.path.insert(0, "/home/luke/dreambuddy/11-易经推理系统")
from scripts.memory_l4.okx_simulated import OKXSimulatedClient

c = OKXSimulatedClient()
print(f"dry_run={c.dry_run} has_credentials={c._has_credentials()}")

# 测试 market_open_short（和 polling_trader 一样的调用）
r = c.market_open_short(
    inst_id="BTC-USDT-SWAP",
    usdt_amount=250,
    reason="test_full_link",
)
print(f"market_open_short: ok={r.get('ok')} dry_run={r.get('dry_run')} error={r.get('error')}")
print(f"ord_id={r.get('ord_id')} estimated_price={r.get('estimated_price')}")
