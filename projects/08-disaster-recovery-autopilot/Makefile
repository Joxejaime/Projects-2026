.DEFAULT_GOAL := help
PY ?= python3

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

test: ## Run all tests (about 10 s; includes a full disaster-recovery drill)
	$(PY) -m unittest discover -s tests -t . -v

lint: ## Lint and format-check with ruff
	ruff check .
	ruff format --check .

check: ## Validate every playbook
	$(PY) -m drpilot check

drill: ## Corrupt the demo service's data, let drpilot recover it, write the postmortem to postmortems/drills/
	$(PY) -m drpilot drill --out postmortems/drills

drill-fail: ## Same, but every snapshot is corrupt too: automation must escalate, not restore garbage
	$(PY) -m drpilot drill --scenario corrupt-backups --out postmortems/drills

replay: ## Replay a sample Alertmanager incident offline (no playbook matches: shows the escalation path)
	$(PY) -m drpilot replay examples/replica-lag-firing.json examples/replica-lag-resolved.json --state state/incidents --postmortems state/postmortems

serve: ## Run the webhook receiver on :9095 (set DRPILOT_TOKEN to require a bearer token)
	$(PY) -m drpilot serve --port 9095 --state state/incidents --postmortems state/postmortems

.PHONY: help test lint check drill drill-fail replay serve
