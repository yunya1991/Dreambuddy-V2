"""conftest.py — pytest 全局 fixture

自动 mock asyncio.sleep，避免单元测试中真实延迟。
需要验证 sleep 行为的测试可自行 monkeypatch 覆盖。
"""
import asyncio

import pytest


@pytest.fixture(autouse=True)
def _mock_sleep():
    """全局自动 mock asyncio.sleep（零延迟）。"""
    real_sleep = asyncio.sleep

    async def _instant_sleep(seconds):
        # Yield control to event loop without real delay
        await real_sleep(0)

    asyncio.sleep = _instant_sleep
    try:
        yield
    finally:
        asyncio.sleep = real_sleep
