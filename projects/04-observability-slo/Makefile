.PHONY: up down healthy outage slow logs-alerts check test-rules

up:
	docker compose up -d --build

down:
	docker compose down -v

# Failure drills: re-create only the load generator with a different fault mix.
healthy:
	ERROR_RATE=0 SLOW_RATE=0 docker compose up -d --force-recreate loadgen

outage:
	ERROR_RATE=0.5 docker compose up -d --force-recreate loadgen

slow:
	SLOW_RATE=0.5 SLOW_MS=600 docker compose up -d --force-recreate loadgen

logs-alerts:
	docker compose logs -f webhook-sink

check:
	python3 -I prometheus/gen_slo_rules.py --check
	promtool check config prometheus/prometheus.yml
	promtool check rules prometheus/rules/*.yml
	amtool check-config alertmanager/alertmanager.yml
	python3 -I grafana/build_dashboard.py --check

test-rules:
	promtool test rules prometheus/tests/slo_alerts_test.yml
