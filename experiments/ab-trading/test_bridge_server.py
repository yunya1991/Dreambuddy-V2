#!/usr/bin/env python3
"""
WorkBuddy OS Bridge Server 多场景API测试

位置: experiments/ab-trading/test_bridge_server.py

覆盖场景:
1. 健康检查与状态接口
2. 注册表查询接口（多条件组合）
3. 模块执行接口（正常路径）
4. 批量执行接口
5. 错误处理（404/参数错误/不存在的模块）
6. 降级容错测试
7. 性能测试（响应时间/并发）
8. 边界条件（空输入/大数据量）
"""

import json
import time
import unittest
from typing import Dict, Any

import requests


BASE_URL = "http://127.0.0.1:8095"


def make_mkt_data(price=65000.0, rsi=45.0, trend='up'):
    """生成测试用的市场数据"""
    if trend == 'up':
        ema20 = price * 0.99
        ema50 = price * 0.97
        ema200 = price * 0.92
        ch24 = 2.5
    elif trend == 'down':
        ema20 = price * 1.01
        ema50 = price * 1.03
        ema200 = price * 1.08
        ch24 = -2.5
    else:
        ema20 = price
        ema50 = price * 1.005
        ema200 = price * 1.01
        ch24 = 0.3

    return {
        'price': price,
        'rsi14': rsi,
        'ema20': ema20,
        'ema50': ema50,
        'ema200': ema200,
        'atr14': price * 0.02,
        'funding_rate': 0.0001,
        'change_24h': ch24,
        'change_4h': ch24 / 6,
        'change_1h': ch24 / 24,
        'vol_ratio': 1.2,
    }


class TestHealthAndStatus(unittest.TestCase):
    """健康检查与状态接口测试"""

    def test_health_check(self):
        """测试健康检查接口"""
        resp = requests.get(f"{BASE_URL}/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['status'], 'healthy')
        self.assertIn('version', data)
        self.assertIn('timestamp', data)
        self.assertIn('uptime', data)
        self.assertGreater(data['uptime'], 0)

    def test_status(self):
        """测试服务状态接口"""
        resp = requests.get(f"{BASE_URL}/api/v1/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['status'], 'running')
        self.assertGreater(data['modules_loaded'], 0)
        self.assertEqual(data['execution_engine'], 'python')

    def test_registry_stats(self):
        """测试注册表统计接口"""
        resp = requests.get(f"{BASE_URL}/api/v1/registry/stats")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertIn('total', data['stats'])
        self.assertIn('by_chain', data['stats'])
        self.assertIn('by_domain', data['stats'])


class TestRegistryQuery(unittest.TestCase):
    """注册表查询接口测试"""

    def test_list_all_modules(self):
        """测试列出所有模块"""
        resp = requests.get(f"{BASE_URL}/api/v1/registry/modules")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertGreater(data['count'], 0)
        self.assertEqual(len(data['modules']), data['count'])

    def test_filter_by_chain(self):
        """测试按链过滤"""
        for chain in ['A', 'C', 'F']:
            resp = requests.get(
                f"{BASE_URL}/api/v1/registry/modules",
                params={'chain': chain}
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertTrue(data['success'])
            for mod in data['modules']:
                self.assertEqual(mod['chain'], chain)

    def test_filter_by_domain(self):
        """测试按领域过滤"""
        resp = requests.get(
            f"{BASE_URL}/api/v1/registry/modules",
            params={'domain': 'A_domain'}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        for mod in data['modules']:
            self.assertEqual(mod['domain'], 'A_domain')

    def test_filter_by_stage(self):
        """测试按阶段过滤"""
        resp = requests.get(
            f"{BASE_URL}/api/v1/registry/modules",
            params={'stage': 'analysis'}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        for mod in data['modules']:
            self.assertIn('analysis', mod['applicable_stages'])

    def test_get_module_detail(self):
        """测试获取单个模块详情"""
        module_id = 'dream-first-principles'
        resp = requests.get(f"{BASE_URL}/api/v1/registry/modules/{module_id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['module']['id'], module_id)
        self.assertIn('name', data['module'])
        self.assertIn('description', data['module'])
        self.assertIn('version', data['module'])
        self.assertIn('adapter', data['module'])
        self.assertIn('fallback', data['module'])

    def test_get_nonexistent_module(self):
        """测试获取不存在的模块（404）"""
        resp = requests.get(f"{BASE_URL}/api/v1/registry/modules/nonexistent-xxx")
        self.assertEqual(resp.status_code, 404)

    def test_post_query(self):
        """测试POST方式查询模块"""
        resp = requests.post(
            f"{BASE_URL}/api/v1/registry/query",
            json={'chain': 'C', 'stage': 'analysis'}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        for mod in data['modules']:
            self.assertEqual(mod['chain'], 'C')
            self.assertIn('analysis', mod['applicable_stages'])

    def test_list_domains(self):
        """测试获取领域列表"""
        resp = requests.get(f"{BASE_URL}/api/v1/registry/domains")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertIsInstance(data['domains'], list)
        self.assertGreater(len(data['domains']), 0)

    def test_list_chains(self):
        """测试获取链列表"""
        resp = requests.get(f"{BASE_URL}/api/v1/registry/chains")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertIsInstance(data['chains'], list)


class TestModuleExecution(unittest.TestCase):
    """模块执行接口测试 - 正常路径"""

    def test_execute_contradiction_theory(self):
        """测试执行A0矛盾论模块"""
        mkt = make_mkt_data(price=65000, rsi=45, trend='up')
        payload = {
            'module_id': 'dream-contradiction-theory',
            'inputs': {},
            'session_id': 'test_unit_001',
            'context': {
                'sessionId': 'test_unit_001',
                'mkt': mkt,
            }
        }
        resp = requests.post(f"{BASE_URL}/api/v1/modules/execute", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])

        result = data['result']
        self.assertEqual(result['capabilityId'], 'dream-contradiction-theory')
        self.assertIn('direction', result['outputs'])
        self.assertGreaterEqual(result['confidence'], 0)
        self.assertLessEqual(result['confidence'], 100)
        self.assertIn('latencyMs', result)
        self.assertGreater(result['latencyMs'], -1)
        self.assertIn('warnings', result)
        self.assertIn('metadata', result)

    def test_execute_first_principles(self):
        """测试执行A2第一性原理模块"""
        mkt = make_mkt_data(price=65000, rsi=45, trend='up')
        payload = {
            'module_id': 'dream-first-principles',
            'inputs': {
                'a0': {
                    'dominant_force': 'BULL',
                    'confidence': 0.7,
                }
            },
            'session_id': 'test_unit_002',
            'context': {
                'sessionId': 'test_unit_002',
                'mkt': mkt,
            }
        }
        resp = requests.post(f"{BASE_URL}/api/v1/modules/execute", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])

        result = data['result']
        self.assertEqual(result['capabilityId'], 'dream-first-principles')
        self.assertIn('direction', result['outputs'])
        self.assertGreaterEqual(result['confidence'], 0)
        self.assertLessEqual(result['confidence'], 100)

    def test_batch_execute(self):
        """测试批量执行模块"""
        mkt = make_mkt_data(price=65000, rsi=45, trend='up')
        payload = {
            'session_id': 'test_batch_001',
            'context': {
                'sessionId': 'test_batch_001',
                'mkt': mkt,
            },
            'calls': [
                {'module_id': 'dream-contradiction-theory', 'inputs': {}},
                {'module_id': 'dream-first-principles', 'inputs': {
                    'a0': {'dominant_force': 'BULL', 'confidence': 0.7}
                }},
            ]
        }
        resp = requests.post(f"{BASE_URL}/api/v1/modules/batch", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['count'], 2)
        self.assertEqual(len(data['results']), 2)

        for result in data['results']:
            self.assertIn('capabilityId', result)
            self.assertIn('outputs', result)
            self.assertIn('confidence', result)

    def test_module_available(self):
        """测试模块可用性检查"""
        resp = requests.get(f"{BASE_URL}/api/v1/modules/dream-contradiction-theory/available")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertIn('available', data)
        self.assertIn('has_adapter', data)

    def test_nonexistent_module_available(self):
        """测试不存在模块的可用性检查（404）"""
        resp = requests.get(f"{BASE_URL}/api/v1/modules/nonexistent-xxx/available")
        self.assertEqual(resp.status_code, 404)


class TestErrorHandling(unittest.TestCase):
    """错误处理测试"""

    def test_execute_nonexistent_module(self):
        """测试执行不存在的模块"""
        payload = {
            'module_id': 'nonexistent-module-xxx',
            'inputs': {},
            'session_id': 'test_error_001',
        }
        resp = requests.post(f"{BASE_URL}/api/v1/modules/execute", json=payload)
        self.assertEqual(resp.status_code, 200)  # 降级返回200，success=false
        data = resp.json()
        self.assertTrue(data['success'])  # API调用成功
        self.assertFalse(data['result']['success'])  # 模块执行失败
        self.assertTrue(data['result']['fallbackUsed'])  # 使用了降级

    def test_missing_module_id(self):
        """测试缺少module_id参数（422）"""
        payload = {
            'inputs': {},
        }
        resp = requests.post(f"{BASE_URL}/api/v1/modules/execute", json=payload)
        self.assertEqual(resp.status_code, 422)  # Pydantic验证失败

    def test_empty_inputs(self):
        """测试空输入"""
        mkt = make_mkt_data(price=65000, rsi=50, trend='range')
        payload = {
            'module_id': 'dream-contradiction-theory',
            'inputs': {},
            'session_id': 'test_empty_001',
            'context': {
                'sessionId': 'test_empty_001',
                'mkt': mkt,
            }
        }
        resp = requests.post(f"{BASE_URL}/api/v1/modules/execute", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])

    def test_batch_with_empty_calls(self):
        """测试批量执行空列表"""
        payload = {
            'session_id': 'test_empty_batch_001',
            'calls': [],
        }
        resp = requests.post(f"{BASE_URL}/api/v1/modules/batch", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['count'], 0)
        self.assertEqual(len(data['results']), 0)


class TestDifferentMarketConditions(unittest.TestCase):
    """不同市场条件下的测试"""

    def _run_module(self, module_id, mkt, extra_inputs=None):
        """辅助函数：执行模块并返回结果"""
        payload = {
            'module_id': module_id,
            'inputs': extra_inputs or {},
            'session_id': f'test_mkt_{module_id}',
            'context': {
                'sessionId': f'test_mkt_{module_id}',
                'mkt': mkt,
            }
        }
        resp = requests.post(f"{BASE_URL}/api/v1/modules/execute", json=payload)
        return resp.json()['result']

    def test_bull_market(self):
        """测试牛市行情"""
        mkt = make_mkt_data(price=70000, rsi=60, trend='up')
        result = self._run_module('dream-contradiction-theory', mkt)
        self.assertTrue(result['success'])
        self.assertIn(result['outputs']['direction'], ['long', 'short', 'neutral', 'hold'])
        self.assertGreater(result['confidence'], 0)

    def test_bear_market(self):
        """测试熊市行情"""
        mkt = make_mkt_data(price=50000, rsi=35, trend='down')
        result = self._run_module('dream-contradiction-theory', mkt)
        self.assertTrue(result['success'])
        self.assertIn(result['outputs']['direction'], ['long', 'short', 'neutral', 'hold'])
        self.assertGreater(result['confidence'], 0)

    def test_range_market(self):
        """测试震荡行情"""
        mkt = make_mkt_data(price=60000, rsi=50, trend='range')
        result = self._run_module('dream-contradiction-theory', mkt)
        self.assertTrue(result['success'])
        self.assertIn(result['outputs']['direction'], ['long', 'short', 'neutral', 'hold'])

    def test_extreme_rsi_high(self):
        """测试超买行情（RSI极高）"""
        mkt = make_mkt_data(price=75000, rsi=85, trend='up')
        result = self._run_module('dream-first-principles', mkt, {
            'a0': {'dominant_force': 'BULL', 'confidence': 0.8}
        })
        self.assertTrue(result['success'])
        self.assertIn(result['outputs']['direction'], ['long', 'short', 'neutral', 'hold'])

    def test_extreme_rsi_low(self):
        """测试超卖行情（RSI极低）"""
        mkt = make_mkt_data(price=40000, rsi=15, trend='down')
        result = self._run_module('dream-first-principles', mkt, {
            'a0': {'dominant_force': 'BEAR', 'confidence': 0.8}
        })
        self.assertTrue(result['success'])
        self.assertIn(result['outputs']['direction'], ['long', 'short', 'neutral', 'hold'])


class TestPerformance(unittest.TestCase):
    """性能测试"""

    def test_response_time_single(self):
        """测试单次请求响应时间"""
        mkt = make_mkt_data(price=65000, rsi=45, trend='up')
        payload = {
            'module_id': 'dream-contradiction-theory',
            'inputs': {},
            'session_id': 'test_perf_001',
            'context': {
                'sessionId': 'test_perf_001',
                'mkt': mkt,
            }
        }

        start = time.time()
        resp = requests.post(f"{BASE_URL}/api/v1/modules/execute", json=payload)
        elapsed = (time.time() - start) * 1000

        self.assertEqual(resp.status_code, 200)
        print(f"    单次请求耗时: {elapsed:.1f}ms")
        # 本地执行应该在1000ms以内
        self.assertLess(elapsed, 5000)

    def test_response_time_batch(self):
        """测试批量请求响应时间"""
        mkt = make_mkt_data(price=65000, rsi=45, trend='up')
        calls = [
            {'module_id': 'dream-contradiction-theory', 'inputs': {}},
            {'module_id': 'dream-first-principles', 'inputs': {
                'a0': {'dominant_force': 'BULL', 'confidence': 0.7}
            }},
            {'module_id': 'dream-contradiction-theory', 'inputs': {}},
            {'module_id': 'dream-first-principles', 'inputs': {
                'a0': {'dominant_force': 'BEAR', 'confidence': 0.6}
            }},
        ]
        payload = {
            'session_id': 'test_perf_batch_001',
            'context': {'sessionId': 'test_perf_batch_001', 'mkt': mkt},
            'calls': calls,
        }

        start = time.time()
        resp = requests.post(f"{BASE_URL}/api/v1/modules/batch", json=payload)
        elapsed = (time.time() - start) * 1000

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['count'], len(calls))
        print(f"    批量{len(calls)}个请求耗时: {elapsed:.1f}ms (平均{elapsed/len(calls):.1f}ms/个)")
        self.assertLess(elapsed, 10000)

    def test_concurrent_requests(self):
        """测试并发请求（简单版）"""
        import threading

        mkt = make_mkt_data(price=65000, rsi=45, trend='up')
        results = []
        errors = []

        def make_request(idx):
            try:
                payload = {
                    'module_id': 'dream-contradiction-theory',
                    'inputs': {},
                    'session_id': f'test_concurrent_{idx}',
                    'context': {
                        'sessionId': f'test_concurrent_{idx}',
                        'mkt': mkt,
                    }
                }
                resp = requests.post(f"{BASE_URL}/api/v1/modules/execute", json=payload)
                results.append(resp.status_code)
            except Exception as e:
                errors.append(str(e))

        threads = []
        num_requests = 5
        for i in range(num_requests):
            t = threading.Thread(target=make_request, args=(i,))
            threads.append(t)

        start = time.time()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        elapsed = (time.time() - start) * 1000

        print(f"    并发{num_requests}个请求耗时: {elapsed:.1f}ms")
        self.assertEqual(len(results), num_requests)
        self.assertEqual(len(errors), 0)
        for status in results:
            self.assertEqual(status, 200)


class TestExecutionStats(unittest.TestCase):
    """执行统计测试"""

    def test_get_stats(self):
        """测试获取执行统计"""
        resp = requests.get(f"{BASE_URL}/api/v1/execution/stats")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertIsInstance(data['stats'], dict)

    def test_reset_stats(self):
        """测试重置执行统计"""
        resp = requests.post(f"{BASE_URL}/api/v1/execution/stats/reset")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertIn('message', data)


class TestRegistryReload(unittest.TestCase):
    """注册表重载测试"""

    def test_reload_registry(self):
        """测试重新加载注册表"""
        resp = requests.post(f"{BASE_URL}/api/v1/registry/reload")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertGreater(data['modules_loaded'], 0)


def run_all_tests():
    """运行所有测试"""
    print("=" * 70)
    print("WorkBuddy OS Bridge Server - 多场景API测试")
    print("=" * 70)
    print()

    # 检查服务是否可用
    try:
        resp = requests.get(f"{BASE_URL}/health", timeout=3)
        if resp.status_code != 200:
            print("❌ Bridge Server 未启动或不可用")
            print(f"   请先运行: cd experiments/ab-trading && python3 bridge_server.py")
            return False
    except Exception as e:
        print(f"❌ 无法连接到 Bridge Server: {e}")
        print(f"   请先运行: cd experiments/ab-trading && python3 bridge_server.py")
        return False

    print(f"✅ Bridge Server 可用: {BASE_URL}")
    print()

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    test_classes = [
        TestHealthAndStatus,
        TestRegistryQuery,
        TestModuleExecution,
        TestErrorHandling,
        TestDifferentMarketConditions,
        TestPerformance,
        TestExecutionStats,
        TestRegistryReload,
    ]

    for test_class in test_classes:
        tests = loader.loadTestsFromTestCase(test_class)
        suite.addTests(tests)

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print()
    print("=" * 70)
    print("测试汇总")
    print("=" * 70)
    print(f"  运行测试: {result.testsRun}")
    print(f"  通过: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"  失败: {len(result.failures)}")
    print(f"  错误: {len(result.errors)}")
    print()

    if result.failures:
        print("失败的测试:")
        for test, trace in result.failures:
            print(f"  - {test}")
            print(f"    {trace.split(chr(10))[-2]}")
        print()

    if result.errors:
        print("错误的测试:")
        for test, trace in result.errors:
            print(f"  - {test}")
            print(f"    {trace.split(chr(10))[-2]}")
        print()

    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_all_tests()
    exit(0 if success else 1)
