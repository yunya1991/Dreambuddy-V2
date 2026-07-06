"""
Dream-MultiSkill 百炼API客户端
"""
import os
import json
import time
import logging
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class BailianClient:
    """百炼API标准客户端"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        timeout: int = 30,
        max_retries: int = 3,
        default_model: str = "qwen3.6-35b-a3b",
        trace_header: str = "X-Trace-Id"
    ):
        """
        初始化百炼客户端

        Args:
            api_key: API Key，默认从环境变量 BAILIAN_API_KEY 读取
            base_url: API Base URL
            timeout: 超时时间(秒)
            max_retries: 最大重试次数
            default_model: 默认模型
            trace_header: 追踪头名称
        """
        self.api_key = api_key or os.environ.get("BAILIAN_API_KEY")
        if not self.api_key:
            raise ValueError("API Key 未配置，请设置 BAILIAN_API_KEY 环境变量或传入 api_key 参数")

        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.default_model = default_model
        self.trace_header = trace_header

    def _generate_trace_id(self) -> str:
        """生成追踪ID"""
        return f"bailian_{int(time.time() * 1000)}"

    def _call_api(
        self,
        endpoint: str,
        data: Dict[str, Any],
        method: str = "POST",
        trace_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        通用API调用

        Args:
            endpoint: API端点
            data: 请求数据
            method: HTTP方法
            trace_id: 追踪ID

        Returns:
            API响应
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        trace_id = trace_id or self._generate_trace_id()

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            self.trace_header: trace_id
        }

        req = Request(
            url,
            data=json.dumps(data).encode(),
            headers=headers,
            method=method
        )

        # 重试逻辑
        for attempt in range(self.max_retries):
            try:
                with urlopen(req, timeout=self.timeout) as resp:
                    result = json.loads(resp.read().decode())
                    self._log_call(trace_id, endpoint, "success", resp.status)
                    return result

            except HTTPError as e:
                error_body = e.read().decode()
                self._log_call(trace_id, endpoint, "error", e.code, error_body)

                # 根据错误码决定是否重试
                if e.code in [429, 500, 503]:
                    if attempt < self.max_retries - 1:
                        wait_time = (2 ** attempt) * 1  # 指数退避
                        logger.warning(f"请求失败，{wait_time}s后重试 (尝试 {attempt+1}/{self.max_retries})")
                        time.sleep(wait_time)
                        continue

                raise BailianAPIError(
                    code=e.code,
                    message=error_body,
                    trace_id=trace_id
                )

            except URLError as e:
                self._log_call(trace_id, endpoint, "error", "url_error", str(e))
                if attempt < self.max_retries - 1:
                    wait_time = (2 ** attempt) * 1
                    logger.warning(f"网络错误，{wait_time}s后重试")
                    time.sleep(wait_time)
                    continue
                raise

        raise BailianAPIError(code=0, message="重试次数耗尽", trace_id=trace_id)

    def _log_call(
        self,
        trace_id: str,
        endpoint: str,
        status: str,
        status_code: Any = None,
        detail: str = None
    ):
        """记录API调用日志"""
        log_entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            "level": "INFO" if status == "success" else "ERROR",
            "trace_id": trace_id,
            "action": f"bailian_call:{endpoint}",
            "status": status,
            "status_code": status_code,
            "detail": detail
        }
        logger.info(json.dumps(log_entry))

    def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        stream: bool = False,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        top_p: float = 0.9,
        **kwargs
    ) -> Dict[str, Any]:
        """
        聊天补全

        Args:
            messages: 消息列表 [{"role": "user", "content": "..."}]
            model: 模型名称，默认使用 default_model
            stream: 是否流式输出
            max_tokens: 最大生成token数
            temperature: 随机性 (0-2)
            top_p: 核采样

        Returns:
            API响应
        """
        data = {
            "model": model or self.default_model,
            "messages": messages,
            "stream": stream
        }

        if max_tokens:
            data["max_tokens"] = max_tokens
        if temperature:
            data["temperature"] = temperature
        if top_p:
            data["top_p"] = top_p

        # 添加额外参数
        for key, value in kwargs.items():
            if value is not None:
                data[key] = value

        return self._call_api("/chat/completions", data)

    def embed(
        self,
        texts: List[str],
        model: str = "text-embedding-v3"
    ) -> Dict[str, Any]:
        """
        文本向量化

        Args:
            texts: 文本列表
            model: 向量化模型

        Returns:
            包含 embeddings 的响应
        """
        data = {
            "model": model,
            "input": texts
        }

        return self._call_api("/embeddings", data)

    def image_generate(
        self,
        prompt: str,
        model: str = "wanx-plus",
        n: int = 1,
        size: str = "1024*1024"
    ) -> Dict[str, Any]:
        """
        图像生成

        Args:
            prompt: 生成提示词
            model: 图像模型
            n: 生成数量
            size: 图像尺寸

        Returns:
            包含图像URL的响应
        """
        data = {
            "model": model,
            "prompt": prompt,
            "n": n,
            "size": size
        }

        return self._call_api("/images/generations", data)

    def health_check(self) -> bool:
        """健康检查"""
        try:
            self.chat([{"role": "user", "content": "hi"}], max_tokens=10)
            return True
        except:
            return False


class BailianAPIError(Exception):
    """百炼API错误"""

    def __init__(self, code: int, message: str, trace_id: str = None):
        self.code = code
        self.message = message
        self.trace_id = trace_id
        super().__init__(f"[{code}] {message} (trace_id: {trace_id})")

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "trace_id": self.trace_id
            }
        }


# 便捷函数
def create_client(**kwargs) -> BailianClient:
    """创建百炼客户端"""
    return BailianClient(**kwargs)


def chat(message: str, **kwargs) -> str:
    """便捷聊天调用"""
    client = BailianClient()
    response = client.chat([{"role": "user", "content": message}], **kwargs)
    return response["choices"][0]["message"]["content"]


def embed(text: str, **kwargs) -> List[float]:
    """便捷向量化调用"""
    client = BailianClient()
    response = client.embed([text], **kwargs)
    return response["data"][0]["embedding"]
