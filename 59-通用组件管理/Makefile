# 59-通用组件管理 治理入口（SPEC §8）
#
# make check   发版前必跑：kernel 注入一致性 + 独立性闸门 G1–G7 + INDEX 生成同步 + 规则/站点产物一致 + 规则测试 + 路由基准夹具
# make build   全量构建 4 商品族 8 变体到 dist/
# make release 先过闸门再构建
# make test    沙箱 16 场景回归
# make verify  全量验证：check + 契约漂移 + 主仓同步 + 组件/引擎/MCP/沙箱测试
# make verify-live 联网校验：SkillHub 平台签名（未登录时 SKIP）
# make bench   可发现性路由基准（需 Qwen 配置；--dry-run 只校验夹具）

.PHONY: check build release test verify verify-live bench bench-dry

check:
	python3 tools/sync_kernel.py --check
	python3 tools/check_boundaries.py
	python3 tools/check_contracts.py
	python3 tools/lifecycle.py check
	python3 tools/skillset.py check
	python3 tools/supply_chain.py check
	python3 tools/sync_mobile.py --check-local
	python3 tools/gen_index.py --check
	python3 tools/sync_rules.py --check
	python3 platform/site/scripts/build_site.py --check
	python3 platform/bench/routing/run_bench.py --dry-run
	python3 platform/optimizer/cli.py card --check
	python3 platform/optimizer/cli.py gate --all --profile legacy --offline
	node --test platform/services/skillhub-audit-api/test/*.test.js

build:
	python3 tools/build_product.py --all

release: check build
	python3 platform/optimizer/cli.py gate --all --profile new --offline

test:
	python3 platform/sandbox/run_cases.py

verify: check
	python3 tools/sync_mobile.py --check
	python3 -m unittest discover -s tools/tests
	@for d in components/*/tests; do \
	  [ -d "$$d" ] || continue; \
	  echo "== $$d"; \
	  python3 -m unittest discover -s "$$d" -p "test_*.py" || exit 1; \
	done
	python3 -m unittest discover -s platform/optimizer/tests
	python3 -m unittest discover -s platform/bench/routing -p "test_*.py"
	python3 -m unittest discover -s ../mcp_shells/l0_components -p "test_*.py"
	python3 platform/sandbox/run_cases.py

verify-live:
	python3 tools/supply_chain.py verify --online

bench-dry:
	python3 platform/bench/routing/run_bench.py --dry-run

bench:
	python3 platform/bench/routing/run_bench.py --router qwen \
		--compare platform/ops/bench_history.jsonl \
		--archive platform/ops/bench_history.jsonl --trend
