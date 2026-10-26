.DEFAULT_GOAL := help
PY ?= python3

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

test: ## Run unit + end-to-end tests
	$(PY) -m unittest discover -s tests -t . -v

lint: ## Lint and format-check with ruff
	ruff check .
	ruff format --check .

run: ## Run the gateway locally (admin routes enabled with a lab token)
	GATEWAY_ADMIN_TOKEN=lab-only-token $(PY) -m gateway

up: ## Start gateway + Prometheus + Grafana (http://localhost:3000, admin/admin)
	docker compose up --build -d

down: ## Stop the local stack
	docker compose down -v

drill: ## Run the scripted provider-outage drill against a running stack
	ADMIN_TOKEN=lab-only-token ./scripts/incident_drill.sh

validate: ## Validate YAML and compose config
	$(PY) scripts/validate_configs.py
	docker compose config -q

.PHONY: help test lint run up down drill validate
