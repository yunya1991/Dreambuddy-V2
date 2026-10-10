"""TypeScript/JavaScript AST 分析器。

能力：
- 模块/类/函数清单
- import/export 依赖
- 调用关系
- 类型注解提取
"""

from __future__ import annotations

from .analyzer_base import AnalyzeResult, AnalyzerBase


class TSAnalyzer(AnalyzerBase):
    """TypeScript/JavaScript 源码静态分析器。"""

    def analyze(self, target: str, **kwargs) -> AnalyzeResult:
        # TODO: 实现 TS/JS AST 解析（可选集成 @babel/parser）
        raise NotImplementedError

    def supported_targets(self) -> list[str]:
        return ["typescript", "javascript"]
