.DEFAULT_GOAL := help
PY ?= python3

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-10s %s\n", $$1, $$2}'

test: ## Run the test suite
	$(PY) -m unittest discover -s tests -t . -v

lint: ## Lint and format-check with ruff
	ruff check .
	ruff format --check .

demo: ## Scaffold a service, validate it, and run its own tests
	rm -rf /tmp/platformctl-demo
	$(PY) -m platformctl new demo-api --owner team-demo --tier critical --out /tmp/platformctl-demo
	$(PY) -m platformctl validate /tmp/platformctl-demo --strict
	cd /tmp/platformctl-demo && $(PY) -m unittest discover -s tests -t .

catalog: ## Print the catalog of example services
	$(PY) -m platformctl catalog examples

.PHONY: help test lint demo catalog
