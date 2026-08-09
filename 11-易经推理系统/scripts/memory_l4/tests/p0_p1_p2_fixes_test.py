"""TDD GREEN 阶段：验证 P1/P2/P4 修复按预期工作。

运行方式（项目根目录下）：
    cd 11-易经推理系统
    /opt/anaconda3/bin/python3 scripts/memory_l4/tests/p0_p1_p2_fixes_test.py
"""
import os
import sys
import json
from pathlib import Path

_roots = [
    Path(__file__).resolve().parents[3],
]
for r in _roots:
    if str(r) not in sys.path:
        sys.path.insert(0, str(r))

PASS = []
FAIL = []


def test(name, fn):
    try:
        fn()
        PASS.append(name)
        print(f"  PASS  {name}")
    except AssertionError as e:
        FAIL.append((name, f"AssertionError: {e}"))
        print(f"  FAIL  {name} -> {e}")
    except Exception as e:
        FAIL.append((name, f"{type(e).__name__}: {e}"))
        print(f"  ERROR {name} -> {type(e).__name__}: {e}")


# ============================
# P1：A_CONFIDENCE_FLOOR 改为可配置
# ============================
def test_p1_a_floor_uses_configurable_threshold():
    import inspect
    from scripts.memory_l4.polling_trader import PollingTrader

    src = inspect.getsource(PollingTrader._execute_trade)
    assert "A_CONFIDENCE_FLOOR = 0.7955" not in src, (
        "P1 FAIL：仍然存在硬编码常量 A_CONFIDENCE_FLOOR = 0.7955"
    )
    has_threshold_ref = (
        "self.confidence_threshold" in src
        or "_adjust_confidence_threshold" in src
        or "effective_a_floor" in src
        or "A_SAFETY_FLOOR" in src
    )
    assert has_threshold_ref, (
        "P1 FAIL：A项过滤未使用可配置阈值"
    )
    assert "0.40" in src or "A_SAFETY_FLOOR" in src or "safety_floor" in src, (
        "P1 FAIL：A项过滤无 safety floor 兜底"
    )


# ============================
# P2：place_order 失败日志包含 proxies
# ============================
def test_p2_place_order_failure_exposes_proxies():
    import inspect
    from scripts.memory_l4.okx_simulated import OKXSimulatedClient

    src = inspect.getsource(OKXSimulatedClient.place_order)
    assert "proxies" in src, (
        "P2 FAIL：place_order 失败分支未包含 proxies 信息"
    )
    assert "proxies=" in src, (
        "P2 FAIL：error 字段未包含 proxies= 诊断"
    )


# ============================
# P4：XAUT → XAU 规范化（方向修正）
# ============================
def test_p4_xaut_to_xau_normalization():
    import re
    from scripts.memory_l4.polling_trader import PollingTrader
    import inspect

    main_src = inspect.getsource(
        __import__("scripts.memory_l4.polling_trader", fromlist=["main"]).main
    )
    m = re.search(r'add_argument\("--coins".*?default="([^"]+)"', main_src, re.S)
    assert m, "找不到 --coins default 定义"
    coins_default_list = [c.strip().upper() for c in m.group(1).split(",")]
    assert "XAU" in coins_default_list, f"P4 FAIL(A)：--coins default 无 XAU -> {coins_default_list}"
    assert "XAUT" not in coins_default_list, f"P4 FAIL(A)：--coins default 仍含 XAUT（不存在的合约）-> {coins_default_list}"

    polling_src = inspect.getsource(PollingTrader)
    # 必须是 XAUT → XAU（而非反方向）
    has_correct_norm = (
        ".replace('XAUT', 'XAU')" in polling_src
        or "'XAUT': 'XAU'" in polling_src
        or '"XAUT": "XAU"' in polling_src
        or "c == 'XAUT'" in polling_src
        or "coin == 'XAUT'" in polling_src
    )
    assert has_correct_norm, (
        "P4 FAIL(B)：缺少 XAUT → XAU 规范化映射（OKX 实际存在 XAU-USDT-SWAP，XAUT 不存在）"
    )
    # 不应再有 XAU→XAUT 的错误反向映射
    wrong_back = (
        "'XAU': 'XAUT'" in polling_src
        or '"XAU": "XAUT"' in polling_src
        or ".replace('XAU', 'XAUT')" in polling_src
    )
    assert not wrong_back, (
        "P4 FAIL(C)：仍存在错误的 XAU→XAUT 反向映射，会把存在的合约改错！"
    )


# ============================
# P0：session.proxies 直接赋值，且新增 _probe_proxy_or_log 诊断函数
#     以及 bcrm2.data_fetcher 的 fetch_okx_klines 带代理 & instId 现货→SWAP fallback
# ============================
def test_p0_proxy_assignment_and_probe():
    import inspect
    from scripts.memory_l4.okx_simulated import OKXSimulatedClient

    src_setup = inspect.getsource(OKXSimulatedClient._proxy_setup)
    # 必须使用直接赋值 self.session.proxies = dict(proxies) 而非仅 update
    assert "self.session.proxies = dict(proxies)" in src_setup or "self.session.proxies = {" in src_setup, (
        "P0 FAIL：_proxy_setup 中未使用直接赋值确保代理生效"
    )
    # 必须调用 probe
    assert "_probe_proxy_or_log" in src_setup, (
        "P0 FAIL：_proxy_setup 后未调用 _probe_proxy_or_log 诊断"
    )
    # 类中必须有 probe 方法
    assert hasattr(OKXSimulatedClient, "_probe_proxy_or_log"), (
        "P0 FAIL：OKXSimulatedClient 缺少 _probe_proxy_or_log 方法"
    )


def test_p0_bcrm2_fetch_okx_klines_has_proxy_and_swap_fallback():
    """P0/P4 联动：bcrm2 fetch_okx_klines 必须读取 os.environ 代理，且 51001 时回退 SWAP 合约"""
    import inspect
    from scripts.memory_l4.bcrm2 import data_fetcher

    src = inspect.getsource(data_fetcher.fetch_okx_klines)
    # 代理相关关键词
    has_env_proxy = any(k in src for k in ["HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "os.environ.get("])
    has_session_or_proxies = "Session(" in src and "proxies" in src
    assert has_env_proxy and has_session_or_proxies, (
        "P0 FAIL：bcrm2.fetch_okx_klines 未读取 os.environ 代理或未新建 Session 配置 proxies"
    )
    # 必须有 51001/SWAP fallback
    has_swap_fallback = (
        ("-USDT-SWAP" in src or "'-USDT-SWAP'" in src)
        and ("51001" in src or "candidates" in src or "inst_id" in src)
    )
    assert has_swap_fallback, (
        "P4 FAIL(bcrm2)：fetch_okx_klines 未实现 现货-USDT 51001 回退到 -USDT-SWAP"
    )


def test_p0_bcrm2_get_klines_spot_and_xau_swap_smoke():
    """实际 smoke 测试：BTC(现货) 必返回；XAU 必须通过 SWAP 候选 fallback 返回"""
    from scripts.memory_l4.bcrm2.data_fetcher import fetch_okx_klines

    df_btc = fetch_okx_klines("BTC", bar="1H", limit=20, max_pages=1)
    assert len(df_btc) > 0, "P0(bcrm2 smoke)：BTC-USDT K线拉取失败（代理/网络可能有问题）"
    df_xau = fetch_okx_klines("XAU", bar="1H", limit=20, max_pages=1)
    assert len(df_xau) > 0, (
        "P4(bcrm2 smoke)：XAU K线拉取失败，"
        "应该通过 -USDT-SWAP 候选回退（当前是否没走 fallback？）"
    )
    df_xaut = fetch_okx_klines("XAUT", bar="1H", limit=20, max_pages=1)
    assert len(df_xaut) > 0, (
        "P4(bcrm2 smoke)：XAUT 输入未规范化为 XAU，未返回有效 K线"
    )


if __name__ == "__main__":
    print("[GREEN阶段] 验证所有修复...")
    test("P1 - A项门槛可配置(safety floor)", test_p1_a_floor_uses_configurable_threshold)
    test("P2 - place_order失败带proxies", test_p2_place_order_failure_exposes_proxies)
    test("P4 - XAUT→XAU规范化(方向修正)", test_p4_xaut_to_xau_normalization)
    test("P0 - proxy直接赋值+probe诊断", test_p0_proxy_assignment_and_probe)
    test("P0/P4 - bcrm2 fetch_okx_klines代理+SWAP fallback代码", test_p0_bcrm2_fetch_okx_klines_has_proxy_and_swap_fallback)
    test("P0/P4 - bcrm2 现货/SWAP 实际拉取smoke", test_p0_bcrm2_get_klines_spot_and_xau_swap_smoke)
    print()
    print(f"PASS={len(PASS)} FAIL={len(FAIL)}")
    if FAIL:
        sys.exit(1)
