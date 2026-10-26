#!/usr/bin/env bash
# Scripted incident drill: healthy baseline -> primary provider outage -> recovery.
# Works against a running gateway (docker compose up, or `python -m gateway`).
#
#   GATEWAY_URL=http://localhost:8080 ADMIN_TOKEN=lab-only-token ./scripts/incident_drill.sh
set -euo pipefail

URL="${GATEWAY_URL:-http://localhost:8080}"
TOKEN="${ADMIN_TOKEN:?set ADMIN_TOKEN to the value of GATEWAY_ADMIN_TOKEN}"
RPS="${RPS:-15}"
PHASE_SECONDS="${PHASE_SECONDS:-15}"
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${PYTHON:-python3}"

fault() {
  curl -fsS -X POST "$URL/admin/faults" -H "X-Admin-Token: $TOKEN" \
    -H 'Content-Type: application/json' -d "$1" >/dev/null
}
snapshot() {
  echo "--- $1: circuit/fault state"
  curl -fsS "$URL/admin/state" -H "X-Admin-Token: $TOKEN"; echo
  curl -fsS "$URL/metrics" | grep -E '^gateway_(requests_total|circuit_state)' | sort
}
phase() {
  echo; echo "=== $1 ($PHASE_SECONDS s @ ${RPS} rps)"
  "$PY" "$HERE/../loadtest/loadgen.py" --url "$URL" --rps "$RPS" --duration "$PHASE_SECONDS"
}

fault '{"reset": true}'
phase "PHASE 1: healthy baseline"
snapshot "after baseline"

echo; echo ">>> injecting fault: primary provider returns errors for 100% of calls"
fault '{"provider": "primary", "error_rate": 1.0}'
phase "PHASE 2: primary outage (expect degraded responses via fallback, circuit opens)"
snapshot "during outage"

echo; echo ">>> clearing fault"
fault '{"reset": true}'
sleep "${RECOVERY_WAIT:-17}"  # > GATEWAY_BREAKER_RECOVERY_TIMEOUT so a half-open probe can happen
phase "PHASE 3: recovery (expect primary traffic to resume, circuit closes)"
snapshot "after recovery"
