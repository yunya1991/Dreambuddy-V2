# syntax=docker/dockerfile:1
# L0 MCP 角色网关镜像（P3a）
#
# 构建：
#   docker build -f deploy/mcp/Dockerfile -t l0-mcp .
# 运行（stdio MCP，宿主以 -i 接入）：
#   docker run -i --rm l0-mcp --role research
#
# 说明：
#   - 镜像内含仓库代码与内置壳运行时；不包含本地数据（认知库/轨迹/模型）。
#   - 需要云端单一事实源时，挂载 SSH 密钥并用 --ssh-host。
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 与 l0-contracts CI 对齐的最小依赖；缺失的可选依赖由各壳自行降级
RUN pip install --no-cache-dir \
    pyyaml numpy pandas scipy requests httpx jsonschema

COPY . /app

ENTRYPOINT ["python", "/app/mcp_shells/l0_gateway/server.py"]