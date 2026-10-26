.DEFAULT_GOAL := help
PY ?= python3

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

install: ## Install Python dependencies (pytest, ruff, psycopg, pyyaml)
	$(PY) -m pip install -r requirements-dev.txt

test: ## Run the fast tests (no PostgreSQL needed)
	$(PY) -m pytest -m "not postgres"

test-all: ## Run everything, including the PostgreSQL integration tests and all three drills (about 1 minute)
	$(PY) -m pytest

lint: ## Lint and format-check with ruff
	ruff check .
	ruff format --check .

check: ## Validate every playbook
	$(PY) -m drpilot check

drill: ## Drop the orders tables; drpilot restores, validates and writes the postmortem to postmortems/drills/
	$(PY) -m drpilot drill --scenario dropped-table --out postmortems/drills

drill-poisoned: ## A backup taken from already-wrong data: recovery must skip it and fall back to an older snapshot
	$(PY) -m drpilot drill --scenario poisoned-backup --out postmortems/drills

drill-fail: ## The only snapshot has rotted: recovery must refuse to restore it and escalate
	$(PY) -m drpilot drill --scenario corrupt-backups --out postmortems/drills

drills: drill drill-poisoned drill-fail ## All three drills

replay: ## Replay a sample Alertmanager incident offline (no playbook matches: shows the escalation path)
	$(PY) -m drpilot replay examples/replica-lag-firing.json examples/replica-lag-resolved.json --state state/incidents --postmortems state/postmortems

serve: ## Run the webhook receiver on :9095 (set DRPILOT_TOKEN to require a bearer token)
	$(PY) -m drpilot serve --port 9095 --state state/incidents --postmortems state/postmortems

.PHONY: help install test test-all lint check drill drill-poisoned drill-fail drills replay serve
