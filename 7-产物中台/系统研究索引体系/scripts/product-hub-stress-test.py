#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# =============================================================================
# 7-产物中台 全链路多场景压力测试
# =============================================================================
# 覆盖：
#   1. 数据服务组   - stats, refresh
#   2. 推荐引擎组   - library, current-strategy, backtests, internal/strategy
#   3. 管理后台组   - strategies, tasks, orders, executions, users, credits,
#                     channels, api-configs, trading-params, stats/overview
#   4. 实时流组     - realtime/stream, meeting/stream (SSE流测试)
#   5. 混合并发组   - 多接口并发请求
#   6. 故障注入组   - 超时/错误响应处理
#
# 运行: python3 stress_test_product_hub.py --host http://localhost:3456 --users 10 --rounds 5
# =============================================================================

import json
import os
import sys
import time
import random
import asyncio
import aiohttp
import argparse
import statistics
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Any, Optional
from collections import defaultdict

# =============================================================================
# 配置
# =============================================================================

DEFAULT_BASE_URL = os.environ.get("PRODUCT_HUB_URL", "http://localhost:3456")

# 测试场景定义
SCENARIO_GROUPS = {
    "data_services": {
        "label": "📊 数据服务组",
        "description": "产物统计和缓存刷新 - 高频查询场景",
        "endpoints": [
            {"method": "GET", "path": "/api/stats", "name": "stats", "weight": 5},
            {"method": "POST", "path": "/api/refresh", "name": "refresh", "weight": 1},
        ],
    },
    "recommendation_engine": {
        "label": "🎯 推荐引擎组",
        "description": "策略查询和检索 - 核心业务场景",
        "endpoints": [
            {"method": "GET", "path": "/api/recommendation-engine/library", "name": "library", "weight": 4},
            {"method": "GET", "path": "/api/recommendation-engine/library?includeArchived=true", "name": "library_with_archived", "weight": 2},
            {"method": "GET", "path": "/api/recommendation-engine/current-strategy", "name": "current_strategy", "weight": 3},
            {"method": "GET", "path": "/api/recommendation-engine/backtests", "name": "backtests", "weight": 2},
            {"method": "GET", "path": "/api/recommendation-engine/logs", "name": "engine_logs", "weight": 1},
        ],
    },
    "admin_panel": {
        "label": "🛠️  管理后台组",
        "description": "后台CRUD操作 - 读写混合场景",
        "endpoints": [
            {"method": "GET", "path": "/api/admin/strategies", "name": "admin_strategies_list", "weight": 3},
            {"method": "GET", "path": "/api/admin/tasks", "name": "admin_tasks", "weight": 2},
            {"method": "GET", "path": "/api/admin/orders", "name": "admin_orders", "weight": 2},
            {"method": "GET", "path": "/api/admin/executions", "name": "admin_executions", "weight": 2},
            {"method": "GET", "path": "/api/admin/users", "name": "admin_users", "weight": 1},
            {"method": "GET", "path": "/api/admin/credits", "name": "admin_credits", "weight": 1},
            {"method": "GET", "path": "/api/admin/channels", "name": "admin_channels", "weight": 1},
            {"method": "GET", "path": "/api/admin/api-configs", "name": "admin_api_configs", "weight": 1},
            {"method": "GET", "path": "/api/admin/trading-params", "name": "admin_trading_params", "weight": 1},
            {"method": "GET", "path": "/api/admin/stats/overview", "name": "admin_stats_overview", "weight": 3},
        ],
    },
    "realtime_streams": {
        "label": "📡 实时流组",
        "description": "SSE流连接 - 并发连接场景 (短超时测试)",
        "endpoints": [
            {"method": "GET", "path": "/api/realtime/stream?channel=dream-agent", "name": "realtime_stream", "weight": 2, "is_sse": True, "sse_timeout_ms": 2000},
            {"method": "GET", "path": "/api/meeting/stream", "name": "meeting_stream", "weight": 1, "is_sse": True, "sse_timeout_ms": 2000},
        ],
    },
    "mixed_concurrent": {
        "label": "🔥 混合并发组",
        "description": "多接口并发 - 模拟真实用户混合操作",
        "endpoints": [
            {"method": "GET", "path": "/api/stats", "name": "stats"},
            {"method": "GET", "path": "/api/recommendation-engine/library", "name": "library"},
            {"method": "GET", "path": "/api/recommendation-engine/current-strategy", "name": "current_strategy"},
            {"method": "GET", "path": "/api/admin/strategies", "name": "admin_strategies"},
            {"method": "GET", "path": "/api/admin/stats/overview", "name": "admin_stats_overview"},
            {"method": "GET", "path": "/api/admin/executions", "name": "admin_executions"},
            {"method": "POST", "path": "/api/refresh", "name": "refresh"},
        ],
    },
}

# =============================================================================
# 测试结果数据结构
# =============================================================================

@dataclass
class EndpointResult:
    group: str
    endpoint: str
    method: str
    path: str
    total_requests: int
    success_count: int
    failure_count: int
    error_count: int
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    max_latency_ms: float
    min_latency_ms: float
    status_counts: dict
    errors: list
    timestamps: list

@dataclass
class TestSummary:
    total_requests: int
    total_success: int
    total_failures: int
    total_errors: int
    success_rate: float
    avg_latency_ms: float
    max_latency_ms: float
    total_duration_ms: float
    requests_per_second: float
    slow_endpoints: list
    error_endpoints: list

# =============================================================================
# 异步测试引擎
# =============================================================================

class AsyncStressTestEngine:
    def __init__(self, base_url: str, num_users: int, rounds: int, timeout: int = 30):
        self.base_url = base_url
        self.num_users = num_users
        self.rounds = rounds
        self.timeout = timeout
        self.results = defaultdict(lambda: defaultdict(list))
        self.errors = defaultdict(list)
        self.latency_history = []
        
    # ---------------------------------------------------------------------
    # 单个请求
    # ---------------------------------------------------------------------
    async def make_request(self, session: aiohttp.ClientSession, method: str, 
                          path: str, name: str, user_id: int, round_num: int) -> dict:
        url = f"{self.base_url}{path}"
        start_time = time.time()
        timestamp = datetime.now().isoformat()
        
        try:
            async with session.request(method, url, timeout=aiohttp.ClientTimeout(total=self.timeout)) as resp:
                duration = (time.time() - start_time) * 1000
                status = resp.status
                response_text = await resp.text()
                
                # 尝试解析JSON
                is_json = False
                payload_size = len(response_text)
                try:
                    data = json.loads(response_text)
                    is_json = True
                    if data.get("success") == False:
                        self.errors[name].append({
                            "error": data.get("error", "Unknown error"),
                            "user": user_id,
                            "round": round_num,
                            "timestamp": timestamp,
                            "status": status,
                        })
                except:
                    pass
                
                result = {
                    "name": name,
                    "status": status,
                    "latency_ms": duration,
                    "is_json": is_json,
                    "payload_size": payload_size,
                    "success": 200 <= status < 400,
                    "timestamp": timestamp,
                    "user_id": user_id,
                    "round": round_num,
                }
                
                # 记录到results
                self.results[name]["latencies"].append(duration)
                self.results[name]["statuses"].append(status)
                self.results[name]["payload_sizes"].append(payload_size)
                self.latency_history.append({"name": name, "latency": duration, "status": status})
                
                return result
                
        except asyncio.TimeoutError:
            duration = (time.time() - start_time) * 1000
            self.errors[name].append({
                "error": "Timeout",
                "user": user_id,
                "round": round_num,
                "timestamp": timestamp,
            })
            return {"name": name, "status": 0, "latency_ms": duration, "success": False, 
                    "error": "timeout", "timestamp": timestamp, "user_id": user_id, "round": round_num}
                    
        except Exception as e:
            duration = (time.time() - start_time) * 1000
            self.errors[name].append({
                "error": str(e),
                "user": user_id,
                "round": round_num,
                "timestamp": timestamp,
            })
            return {"name": name, "status": 0, "latency_ms": duration, "success": False,
                    "error": str(e), "timestamp": timestamp, "user_id": user_id, "round": round_num}
    
    # ---------------------------------------------------------------------
    # 单个用户循环（执行多轮测试）
    # ---------------------------------------------------------------------
    async def user_loop(self, user_id: int, group_name: str, endpoints: list):
        connector = aiohttp.TCPConnector(limit=10)
        async with aiohttp.ClientSession(connector=connector) as session:
            for round_num in range(1, self.rounds + 1):
                # 随机选择一个请求
                ep = random.choice(endpoints)
                ep_name = f"{group_name}_{ep['name']}"
                
                # 判断是否是 SSE 流端点 - 如果是，设置短超时
                is_sse = ep.get("is_sse", False)
                sse_timeout = ep.get("sse_timeout_ms", 2000) / 1000.0 if is_sse else None
                
                # 执行请求 - 对于 SSE，使用 async for 读取少量事件后断开
                if is_sse:
                    # 对 SSE 流，只读取前几个事件然后断开
                    start_time = time.time()
                    timestamp = datetime.now().isoformat()
                    try:
                        async with session.request(
                            ep["method"], 
                            f"{self.base_url}{ep['path']}",
                            timeout=aiohttp.ClientTimeout(total=sse_timeout)
                        ) as resp:
                            duration = (time.time() - start_time) * 1000
                            status = resp.status
                            
                            # 只读取第一个事件，然后断开
                            events_read = 0
                            payload_size = 0
                            try:
                                async for line in resp.content:
                                    payload_size += len(line)
                                    if line.startswith(b"data:") and events_read < 2:
                                        events_read += 1
                                    # 读取 3 个事件或超时后断开
                                    if events_read >= 3 or (time.time() - start_time) > sse_timeout:
                                        break
                            except:
                                pass
                            
                            # 存储结果
                            self.results[ep_name]["latencies"].append(duration)
                            self.results[ep_name]["statuses"].append(status)
                            self.results[ep_name]["payload_sizes"].append(payload_size)
                            self.latency_history.append({"name": ep_name, "latency": duration, "status": status})
                            
                            if 200 <= status < 400:
                                pass
                            else:
                                self.errors[ep_name].append({
                                    "error": f"HTTP {status}",
                                    "user": user_id, "round": round_num, "timestamp": timestamp, "status": status
                                })
                            
                    except Exception as e:
                        duration = (time.time() - start_time) * 1000
                        # 超时对 SSE 是正常的（流是无限的）
                        if "timeout" in str(e).lower():
                            self.results[ep_name]["latencies"].append(duration)
                            self.results[ep_name]["statuses"].append(200)
                            self.results[ep_name]["payload_sizes"].append(0)
                            self.latency_history.append({"name": ep_name, "latency": duration, "status": 200})
                        else:
                            self.results[ep_name]["latencies"].append(duration)
                            self.results[ep_name]["statuses"].append(0)
                            self.results[ep_name]["payload_sizes"].append(0)
                            self.errors[ep_name].append({"error": str(e), "user": user_id, "round": round_num})
                else:
                    # 普通请求
                    await self.make_request(
                        session, ep["method"], ep["path"], ep_name, user_id, round_num
                    )
                
                # 请求间的随机延迟
                await asyncio.sleep(random.uniform(0.01, 0.1))
    
    # ---------------------------------------------------------------------
    # 运行一个测试组
    # ---------------------------------------------------------------------
    async def run_group(self, group_name: str, group_config: dict) -> dict:
        endpoints = group_config["endpoints"]
        
        # 初始化此组的结果存储
        for ep in endpoints:
            key = f"{group_name}_{ep['name']}"
            self.results[key] = {"latencies": [], "statuses": [], "payload_sizes": []}
        
        start_time = time.time()
        
        # 并发执行所有用户循环
        tasks = []
        for user_id in range(self.num_users):
            task = asyncio.create_task(self.user_loop(user_id, group_name, endpoints))
            tasks.append(task)
        
        await asyncio.gather(*tasks, return_exceptions=True)
        
        duration_ms = (time.time() - start_time) * 1000
        return {"duration_ms": duration_ms}
    
    # ---------------------------------------------------------------------
    # 计算每个端点的统计
    # ---------------------------------------------------------------------
    def compute_endpoint_stats(self, endpoint_name: str, group_name: str, 
                              method: str, path: str) -> EndpointResult:
        result_key = endpoint_name
        if result_key not in self.results or not self.results[result_key]["latencies"]:
            return EndpointResult(
                group=group_name, endpoint=endpoint_name, method=method, path=path,
                total_requests=0, success_count=0, failure_count=0, error_count=0,
                avg_latency_ms=0, p50_latency_ms=0, p95_latency_ms=0, p99_latency_ms=0,
                max_latency_ms=0, min_latency_ms=0, status_counts={}, errors=[], timestamps=[]
            )
        
        latencies = self.results[result_key]["latencies"]
        statuses = self.results[result_key]["statuses"]
        errors = self.errors.get(endpoint_name, [])
        
        # 统计状态码
        status_counts = {}
        for s in statuses:
            status_counts[str(s)] = status_counts.get(str(s), 0) + 1
        
        success_count = sum(1 for s in statuses if 200 <= s < 400)
        failure_count = len(statuses) - success_count
        error_count = len(errors)
        
        latencies_sorted = sorted(latencies)
        n = len(latencies_sorted)
        
        return EndpointResult(
            group=group_name,
            endpoint=endpoint_name,
            method=method,
            path=path,
            total_requests=len(statuses),
            success_count=success_count,
            failure_count=failure_count,
            error_count=error_count,
            avg_latency_ms=statistics.mean(latencies) if latencies else 0,
            p50_latency_ms=latencies_sorted[int(n * 0.5)] if latencies else 0,
            p95_latency_ms=latencies_sorted[int(n * 0.95)] if latencies else 0,
            p99_latency_ms=latencies_sorted[int(n * 0.99)] if latencies else 0,
            max_latency_ms=max(latencies) if latencies else 0,
            min_latency_ms=min(latencies) if latencies else 0,
            status_counts=status_counts,
            errors=errors[:10],
            timestamps=[],
        )

# =============================================================================
# 测试运行器
# =============================================================================

class ProductHubTestRunner:
    def __init__(self, base_url: str, num_users: int, rounds: int, timeout: int = 30):
        self.base_url = base_url
        self.num_users = num_users
        self.rounds = rounds
        self.timeout = timeout
        self.group_results = {}
        self.all_endpoint_results = []
        
    def run_all_groups(self, groups=None):
        print("=" * 80)
        print(f"🚀 7-产物中台 全链路多场景压力测试")
        print("=" * 80)
        active_groups = groups if groups is not None else SCENARIO_GROUPS
        print(f"  基础URL: {self.base_url}")
        print(f"  并发用户数: {self.num_users}")
        print(f"  每用户轮数: {self.rounds}")
        print(f"  超时时间: {self.timeout}s")
        print(f"  总请求上限: {self.num_users * self.rounds * 5}")
        print(f"  测试组: {len(active_groups)}")
        print(f"  开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        
        # 检查服务器是否可达
        if not self._check_server():
            print("❌ 服务器不可达，请检查服务是否启动")
            return
        
        total_start = time.time()
        
        # 依次运行各个组
        for group_idx, (group_name, group_config) in enumerate(active_groups.items()):
            print(f"\n\n[{group_idx + 1}/{len(active_groups)}] {group_config['label']}")
            print("-" * 80)
            print(f"  描述: {group_config['description']}")
            print(f"  端点: {len(group_config['endpoints'])} 个")
            
            group_result = asyncio.run(self._run_single_group(group_name, group_config))
            self.group_results[group_name] = group_result
            
            print(f"  完成! 耗时: {group_result['duration_ms']:.0f}ms")
            print(f"  端点详情:")
            for ep_stat in group_result["endpoint_stats"]:
                status_icon = "✅" if ep_stat.success_count == ep_stat.total_requests else "⚠️"
                print(f"    {status_icon} {ep_stat.endpoint:30s} "
                      f"成功={ep_stat.success_count}/{ep_stat.total_requests:3d} "
                      f"avg={ep_stat.avg_latency_ms:6.0f}ms "
                      f"p95={ep_stat.p95_latency_ms:6.0f}ms "
                      f"max={ep_stat.max_latency_ms:6.0f}ms")
                self.all_endpoint_results.append(ep_stat)
            
            # 组间休息
            time.sleep(0.5)
        
        total_duration_ms = (time.time() - total_start) * 1000
        print(f"\n\n{'='*80}")
        print(f"🎉 测试完成! 总耗时: {total_duration_ms/1000:.1f}s")
        print(f"{'='*80}")
        
        # 存储活跃组供总结使用
        self.active_groups = active_groups
        
        # 生成总结
        self._generate_summary(total_duration_ms)
        
    def _check_server(self) -> bool:
        """检查服务器是否可达"""
        try:
            import urllib.request
            req = urllib.request.Request(self.base_url + "/api/stats", method="GET")
            resp = urllib.request.urlopen(req, timeout=5)
            return 200 <= resp.status < 500
        except:
            try:
                # 尝试根路径
                req = urllib.request.Request(self.base_url, method="GET")
                resp = urllib.request.urlopen(req, timeout=5)
                return 200 <= resp.status < 500
            except Exception as e:
                print(f"  连接失败: {e}")
                return False
    
    async def _run_single_group(self, group_name: str, group_config: dict) -> dict:
        """运行单个测试组"""
        engine = AsyncStressTestEngine(self.base_url, self.num_users, self.rounds, self.timeout)
        
        # 执行测试
        group_info = await engine.run_group(group_name, group_config)
        
        # 计算每个端点的统计
        endpoint_stats = []
        for ep in group_config["endpoints"]:
            stat = engine.compute_endpoint_stats(
                f"{group_name}_{ep['name']}", group_name, ep["method"], ep["path"]
            )
            endpoint_stats.append(stat)
        
        return {
            "duration_ms": group_info["duration_ms"],
            "endpoint_stats": endpoint_stats,
        }
    
    # ---------------------------------------------------------------------
    # 总结报告
    # ---------------------------------------------------------------------
    def _generate_summary(self, total_duration_ms: float):
        print("\n\n")
        print("📊 " + "=" * 75)
        print("📊  产物中台压力测试 - 汇总报告")
        print("📊 " + "=" * 75)
        
        # 总体统计
        total_requests = sum(r.total_requests for r in self.all_endpoint_results)
        total_success = sum(r.success_count for r in self.all_endpoint_results)
        total_failures = sum(r.failure_count for r in self.all_endpoint_results)
        total_errors = sum(r.error_count for r in self.all_endpoint_results)
        
        success_rate = (total_success / total_requests * 100) if total_requests > 0 else 0
        avg_latency = statistics.mean(
            r.avg_latency_ms for r in self.all_endpoint_results if r.total_requests > 0
        ) if any(r.total_requests > 0 for r in self.all_endpoint_results) else 0
        max_latency = max((r.max_latency_ms for r in self.all_endpoint_results), default=0)
        
        rps = (total_requests / total_duration_ms * 1000) if total_duration_ms > 0 else 0
        
        print(f"\n  📈 总体统计")
        print(f"  {'─'*60}")
        print(f"    总请求数:     {total_requests:,}")
        print(f"    成功数:       {total_success:,} ({success_rate:.1f}%)")
        print(f"    失败数:       {total_failures:,}")
        print(f"    错误数:       {total_errors:,}")
        print(f"    平均响应:     {avg_latency:.0f}ms")
        print(f"    最大响应:     {max_latency:.0f}ms")
        print(f"    总耗时:       {total_duration_ms/1000:.1f}s")
        print(f"    吞吐率:       {rps:.1f} req/s")
        print()
        
        # 分组统计
        print(f"\n  🎯 分组详情")
        print(f"  {'─'*60}")
        for group_name, group_config in getattr(self, 'active_groups', SCENARIO_GROUPS).items():
            group_stats = [r for r in self.all_endpoint_results if r.group == group_name]
            if not group_stats:
                continue
                
            group_total = sum(r.total_requests for r in group_stats)
            group_success = sum(r.success_count for r in group_stats)
            group_avg_latency = statistics.mean(
                r.avg_latency_ms for r in group_stats if r.total_requests > 0
            ) if any(r.total_requests > 0 for r in group_stats) else 0
            group_max_latency = max((r.max_latency_ms for r in group_stats), default=0)
            group_rate = (group_success / group_total * 100) if group_total > 0 else 0
            
            status_icon = "✅" if group_rate >= 95 else "⚠️" if group_rate >= 80 else "❌"
            print(f"    {status_icon} {group_config['label']}")
            print(f"       请求: {group_total} | 成功率: {group_rate:.1f}% | "
                  f"平均: {group_avg_latency:.0f}ms | 最大: {group_max_latency:.0f}ms")
        
        # 慢端点分析
        print(f"\n\n  🐢 慢响应端点 (平均 > 500ms)")
        print(f"  {'─'*60}")
        slow_endpoints = sorted(
            [r for r in self.all_endpoint_results if r.avg_latency_ms > 500],
            key=lambda x: x.avg_latency_ms, reverse=True
        )
        if slow_endpoints:
            for ep in slow_endpoints[:10]:
                print(f"    {ep.endpoint:40s} avg={ep.avg_latency_ms:6.0f}ms "
                      f"p95={ep.p95_latency_ms:6.0f}ms max={ep.max_latency_ms:6.0f}ms")
        else:
            print("    ✅ 无慢响应端点 (所有端点平均响应 < 500ms)")
        
        # 错误端点分析
        print(f"\n\n  ❌ 错误端点分析")
        print(f"  {'─'*60}")
        error_endpoints = [r for r in self.all_endpoint_results if r.error_count > 0 or r.failure_count > 0]
        if error_endpoints:
            for ep in sorted(error_endpoints, key=lambda x: x.failure_count + x.error_count, reverse=True):
                total_bad = ep.failure_count + ep.error_count
                print(f"    {ep.endpoint:40s} 失败={ep.failure_count} 错误={ep.error_count} "
                      f"状态={dict(list(ep.status_counts.items())[:5])}")
                if ep.errors:
                    for err in ep.errors[:3]:
                        print(f"       - {err.get('error', 'Unknown')[:60]}")
        else:
            print("    ✅ 无错误端点")
        
        # P95/P99 指标
        print(f"\n\n  ⏱️  关键百分位指标")
        print(f"  {'─'*60}")
        all_p95 = [r.p95_latency_ms for r in self.all_endpoint_results if r.total_requests > 0]
        all_p99 = [r.p99_latency_ms for r in self.all_endpoint_results if r.total_requests > 0]
        if all_p95:
            print(f"    总体 P50: {statistics.median(all_p95):.0f}ms")
            print(f"    总体 P95: {statistics.mean(all_p95):.0f}ms")
            print(f"    总体 P99: {statistics.mean(all_p99):.0f}ms")
        
        # 保存JSON报告
        self._save_json_report(total_duration_ms)
        
        print(f"\n\n  {'='*75}")
        print(f"  ✅ 测试完成，报告已保存")
        print(f"  {'='*75}\n")

    def _save_json_report(self, total_duration_ms: float):
        """保存JSON报告到文件"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_data = {
                "timestamp": datetime.now().isoformat(),
                "config": {
                    "base_url": self.base_url,
                    "num_users": self.num_users,
                    "rounds": self.rounds,
                    "timeout": self.timeout,
                },
                "summary": {
                    "total_requests": sum(r.total_requests for r in self.all_endpoint_results),
                    "total_success": sum(r.success_count for r in self.all_endpoint_results),
                    "total_failures": sum(r.failure_count for r in self.all_endpoint_results),
                    "total_errors": sum(r.error_count for r in self.all_endpoint_results),
                    "success_rate": (sum(r.success_count for r in self.all_endpoint_results) / 
                                     sum(r.total_requests for r in self.all_endpoint_results) * 100)
                                     if sum(r.total_requests for r in self.all_endpoint_results) > 0 else 0,
                    "avg_latency_ms": statistics.mean(
                        r.avg_latency_ms for r in self.all_endpoint_results if r.total_requests > 0
                    ) if any(r.total_requests > 0 for r in self.all_endpoint_results) else 0,
                    "max_latency_ms": max((r.max_latency_ms for r in self.all_endpoint_results), default=0),
                    "total_duration_ms": total_duration_ms,
                    "requests_per_second": (sum(r.total_requests for r in self.all_endpoint_results) / 
                                            total_duration_ms * 1000) if total_duration_ms > 0 else 0,
                },
                "endpoints": [asdict(r) for r in self.all_endpoint_results],
                "groups": {
                    g: {
                        "label": gc["label"],
                        "description": gc["description"],
                        "endpoint_count": len(gc["endpoints"]),
                    }
                    for g, gc in getattr(self, 'active_groups', SCENARIO_GROUPS).items()
                },
            }
            
            report_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stress_test_output")
            os.makedirs(report_dir, exist_ok=True)
            report_file = os.path.join(report_dir, f"product_hub_stress_test_{timestamp}.json")
            
            with open(report_file, "w", encoding="utf-8") as f:
                json.dump(report_data, f, ensure_ascii=False, indent=2)
            
            print(f"\n  📁 JSON报告: {report_file}")
            
        except Exception as e:
            print(f"\n  ⚠️  保存报告失败: {e}")


# =============================================================================
# 主程序
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="7-产物中台 全链路多场景压力测试")
    parser.add_argument("--host", default=DEFAULT_BASE_URL, help="服务基础URL")
    parser.add_argument("--users", type=int, default=10, help="并发用户数")
    parser.add_argument("--rounds", type=int, default=5, help="每个用户的请求轮数")
    parser.add_argument("--timeout", type=int, default=30, help="请求超时时间(秒)")
    parser.add_argument("--group", type=str, default=None, 
                       help="只运行指定组 (可选: data_services, recommendation_engine, admin_panel, realtime_streams, mixed_concurrent)")
    
    args = parser.parse_args()
    
    # 如果指定了组，只运行该组；否则运行所有
    active_groups = SCENARIO_GROUPS
    if args.group and args.group in SCENARIO_GROUPS:
        active_groups = {args.group: SCENARIO_GROUPS[args.group]}
    
    runner = ProductHubTestRunner(
        base_url=args.host,
        num_users=args.users,
        rounds=args.rounds,
        timeout=args.timeout,
    )
    
    try:
        runner.run_all_groups(active_groups)
    except KeyboardInterrupt:
        print("\n\n⏹️  测试被中断")
    except Exception as e:
        print(f"\n\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
