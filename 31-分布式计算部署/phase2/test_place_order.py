import sys
sys.path.insert(0, "/home/luke/dreambuddy/11-易经推理系统")
from scripts.memory_l4.okx_simulated import OKXSimulatedClient

c = OKXSimulatedClient()
print(f"dry_run={c.dry_run} simulated={c.simulated}")
print(f"has_credentials={c._has_credentials()}")
print(f"api_key_set={bool(c.api_key)}")

# 测试 dry_run 下单
r = c.place_order(
    inst_id="BTC-USDT-SWAP",
    side="buy",
    ord_type="market",
    sz=0.01,
    pos_side="long",
    reason="test_dry_run",
)
print(f"place_order result: ok={r.get('ok')} dry_run={r.get('dry_run')} error={r.get('error')}")
print(f"ord_id={r.get('ord_id')} estimated_price={r.get('estimated_price')}")
