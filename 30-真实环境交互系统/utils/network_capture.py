"""网络请求捕获工具 — 捕获和分析浏览器网络请求"""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

from playwright.sync_api import Page, Request, Response


class NetworkCapture:
    """网络请求捕获器 — 捕获和分析浏览器网络请求"""

    def __init__(self):
        self._requests: List[Dict[str, Any]] = []
        self._responses: List[Dict[str, Any]] = []
        self._page: Optional[Page] = None
        self._on_request_handler: Optional[Callable] = None
        self._on_response_handler: Optional[Callable] = None

    def start(self, page: Page) -> None:
        """开始捕获网络请求。"""
        self._page = page
        self._requests = []
        self._responses = []

        def on_request(request: Request):
            self._requests.append({
                "url": request.url,
                "method": request.method,
                "headers": dict(request.headers),
                "post_data": request.post_data,
                "timestamp": time.time(),
            })

        def on_response(response: Response):
            try:
                body = ""
                content_type = response.headers.get("content-type", "")
                if "application/json" in content_type:
                    try:
                        body = response.json()
                    except Exception:
                        body = response.text()[:1000]
                elif "text/" in content_type:
                    body = response.text()[:500]
            except Exception:
                body = ""

            self._responses.append({
                "url": response.url,
                "status": response.status,
                "method": response.request.method,
                "headers": dict(response.headers),
                "body": body,
                "timestamp": time.time(),
            })

        self._on_request_handler = on_request
        self._on_response_handler = on_response

        page.on("request", on_request)
        page.on("response", on_response)

    def stop(self) -> None:
        """停止捕获网络请求。"""
        if self._page and self._on_request_handler:
            self._page.remove_listener("request", self._on_request_handler)
        if self._page and self._on_response_handler:
            self._page.remove_listener("response", self._on_response_handler)
        self._on_request_handler = None
        self._on_response_handler = None

    def get_requests(self, url_pattern: str = "", method: str = "") -> List[Dict]:
        """获取匹配的请求。"""
        requests = self._requests
        if url_pattern:
            requests = [r for r in requests if url_pattern in r["url"]]
        if method:
            requests = [r for r in requests if r["method"].upper() == method.upper()]
        return requests

    def get_responses(self, url_pattern: str = "", status: Optional[int] = None) -> List[Dict]:
        """获取匹配的响应。"""
        responses = self._responses
        if url_pattern:
            responses = [r for r in responses if url_pattern in r["url"]]
        if status is not None:
            responses = [r for r in responses if r["status"] == status]
        return responses

    def has_request(self, url_pattern: str, method: str = "") -> bool:
        """检查是否有匹配的请求。"""
        return len(self.get_requests(url_pattern, method)) > 0

    def has_response(self, url_pattern: str, status: Optional[int] = None) -> bool:
        """检查是否有匹配的响应。"""
        return len(self.get_responses(url_pattern, status)) > 0

    def wait_for_request(self, url_pattern: str, timeout: float = 10.0) -> Optional[Dict]:
        """等待匹配的请求出现。"""
        start = time.time()
        while time.time() - start < timeout:
            requests = self.get_requests(url_pattern)
            if requests:
                return requests[-1]
            time.sleep(0.1)
        return None

    def wait_for_response(self, url_pattern: str,
                          status: Optional[int] = None,
                          timeout: float = 10.0) -> Optional[Dict]:
        """等待匹配的响应出现。"""
        start = time.time()
        while time.time() - start < timeout:
            responses = self.get_responses(url_pattern, status)
            if responses:
                return responses[-1]
            time.sleep(0.1)
        return None

    def clear(self) -> None:
        """清空捕获的请求和响应。"""
        self._requests = []
        self._responses = []

    @property
    def all_requests(self) -> List[Dict]:
        return self._requests

    @property
    def all_responses(self) -> List[Dict]:
        return self._responses
