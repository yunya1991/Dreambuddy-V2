# 59-通用组件管理 治理入口（SPEC §8）
#
# make check   发版前必跑：kernel 注入一致性 + 独立性闸门 G1–G7 + INDEX 生成同步 + 规则/站点产物一致 + 规则测试
# make build   全量构建 4 商品族 8 变体到 dist/
# make release 先过闸门再构建
# make test    沙箱 16 场景回归

.PHONY: check build release test

check:
	python3 tools/sync_kernel.py --check
	python3 tools/check_boundaries.py
	python3 tools/gen_index.py --check
	python3 tools/sync_rules.py --check
	python3 platform/site/scripts/build_site.py --check
	node --test platform/services/skillhub-audit-api/test/*.test.js

build:
	python3 tools/build_product.py --all

release: check build

test:
	python3 platform/sandbox/run_cases.py
