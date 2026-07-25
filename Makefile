.PHONY: help install dev lint format test test-cov test-v15 test-risk test-screen clean coverage-html

.DEFAULT_GOAL := help

PYTHON := python3
PIP := pip3
PROJECT_DIR := $(shell pwd)

help:
	@echo "DreamBuddy-V2 Makefile - 工程化工具命令"
	@echo ""
	@echo "安装与环境:"
	@echo "  make install          安装生产依赖"
	@echo "  make dev              安装开发依赖（含lint/test工具）"
	@echo "  make pre-commit       安装pre-commit钩子"
	@echo ""
	@echo "代码质量:"
	@echo "  make lint             运行 ruff lint 检查"
	@echo "  make lint-fix         运行 ruff 自动修复"
	@echo "  make format           运行 black 代码格式化"
	@echo "  make format-check     检查格式是否符合规范"
	@echo "  make mypy             运行 mypy 类型检查（渐进式）"
	@echo "  make quality          完整质量检查（lint + format-check + test）"
	@echo ""
	@echo "测试:"
	@echo "  make test             运行所有单元测试"
	@echo "  make test-cov         运行测试并生成覆盖率报告"
	@echo "  make test-v15         运行 V15 马丁策略测试"
	@echo "  make test-risk        运行通用风控模块测试"
	@echo "  make test-screen      运行三屏趋势测试"
	@echo "  make test-yijing      运行易经推理测试"
	@echo "  make test-slow        运行慢速测试"
	@echo ""
	@echo "覆盖率:"
	@echo "  make coverage-html    生成 HTML 覆盖率报告"
	@echo "  make coverage-report  显示覆盖率摘要"
	@echo ""
	@echo "工程化:"
	@echo "  make ci               CI 完整流程（lint + format-check + test）"
	@echo "  make clean            清理缓存文件"
	@echo "  make debt-review      技术债评审（列出TODO/FIXME）"
	@echo ""

install:
	$(PIP) install -e ".[trading]"

dev:
	$(PIP) install -e ".[dev,trading]"

pre-commit:
	pre-commit install
	@echo "pre-commit hooks 已安装"

lint:
	ruff check .

lint-fix:
	ruff check --fix .

format:
	black .

format-check:
	black --check .

mypy:
	mypy --config-file pyproject.toml 14-V15经典马丁策略/core 13-通用风控模块/core

quality: lint format-check test

test:
	pytest -x -q

test-cov:
	pytest --cov=. --cov-report=term-missing --cov-config=pyproject.toml -q

test-v15:
	cd 14-V15经典马丁策略 && pytest tests/ -v

test-risk:
	cd 13-通用风控模块 && pytest tests/ -v

test-screen:
	cd 12-三屏趋势系统 && pytest tests/ -v

test-yijing:
	cd 11-易经推理系统 && pytest tests/ -v

test-slow:
	pytest -m slow -v

coverage-html:
	pytest --cov=. --cov-report=html --cov-config=pyproject.toml -q
	@echo "HTML 覆盖率报告已生成: htmlcov/index.html"

coverage-report:
	pytest --cov=. --cov-report=term --cov-config=pyproject.toml -q

ci: lint format-check test
	@echo "CI 检查全部通过 ✓"

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	rm -rf htmlcov/ coverage.xml .coverage
	@echo "缓存文件已清理"

debt-review:
	@echo "=== 技术债评审: TODO/FIXME/HACK 统计 ==="
	@grep -rn "TODO\|FIXME\|HACK\|XXX" --include="*.py" . \
		| grep -v "__pycache__" \
		| grep -v ".pytest_cache" \
		| grep -v ".ruff_cache" \
		| grep -v "node_modules" \
		| grep -v ".venv" \
		| grep -v "venv" \
		|| echo "未找到技术债标记"
	@echo ""
	@echo "总计: $$(grep -rn "TODO\|FIXME\|HACK\|XXX" --include="*.py" . | grep -v "__pycache__" | grep -v ".pytest_cache" | wc -l) 处"
