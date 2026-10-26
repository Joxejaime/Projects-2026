.DEFAULT_GOAL := help
PY ?= python3

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

test: ## Run all tests (about 30 s: includes live chaos experiments)
	$(PY) -m unittest discover -s tests -t . -v

lint: ## Lint and format-check with ruff
	ruff check .
	ruff format --check .

check: ## Validate SLO definitions and config files
	$(PY) -m slogen check slo/*.yaml
	$(PY) scripts/validate_configs.py
	docker compose config -q

generate: ## Regenerate Prometheus rules from slo/shop-api.yaml
	$(PY) -m slogen generate slo/shop-api.yaml -o generated/shop-api.rules.yml

generate-check: ## Fail if the committed rules are stale (used in CI)
	$(PY) -m slogen generate slo/shop-api.yaml -o generated/shop-api.rules.yml --check

simulate: ## Replay an example incident through the burn-rate alert policies
	$(PY) -m slogen simulate --objective 99.9 --window 30d --start-minute 10 --duration 30 --error-ratio 0.05

demo: ## Run the demo service on :8081 (no Docker needed; fault injection enabled)
	SHOP_ADMIN_TOKEN=lab-only-token PORT=8081 SHOP_HOST=127.0.0.1 $(PY) demo/shop.py

chaos-errors: ## Chaos experiment: 30% of /checkout fails (needs the demo service running)
	$(PY) chaos/runner.py chaos/scenarios/checkout-errors.yaml --report game-days/checkout-errors.md

chaos-latency: ## Chaos experiment: /checkout gets slow but does not fail
	$(PY) chaos/runner.py chaos/scenarios/checkout-latency.yaml --report game-days/checkout-latency.md

up: ## Full stack: service, traffic, Prometheus, Alertmanager, Grafana (http://localhost:3000)
	docker compose up --build -d

down: ## Stop the stack
	docker compose down -v

.PHONY: help test lint check generate generate-check simulate demo chaos-errors chaos-latency up down
