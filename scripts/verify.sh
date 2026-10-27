#!/usr/bin/env bash
# Runs every offline check for all projects in this repository and prints PASS/FAIL/SKIP per check.
# Missing tools are reported as SKIP, never as PASS, so an incomplete toolchain cannot look like success.
#   ./scripts/verify.sh
set -u
cd "$(dirname "$0")/.." || exit 1

pass=0; fail=0; skip=0
run() {  # run "label" cmd...
  local label="$1"; shift
  local out
  if out=$("$@" 2>&1); then
    printf 'PASS  %s\n' "$label"; pass=$((pass+1))
  else
    printf 'FAIL  %s\n' "$label"; printf '%s\n' "$out" | sed 's/^/        /' | head -20; fail=$((fail+1))
  fi
}
need() {  # need tool label -> returns 1 and prints SKIP if the tool is absent
  command -v "$1" >/dev/null 2>&1 && return 0
  printf 'SKIP  %s (tool not installed: %s)\n' "$2" "$1"; skip=$((skip+1)); return 1
}
need_mod() {  # need_mod module label -> SKIP if python3 cannot import it
  python3 -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('$1') else 1)" 2>/dev/null && return 0
  printf 'SKIP  %s (python module not installed: %s)\n' "$2" "$1"; skip=$((skip+1)); return 1
}
in_dir() { local d="$1"; shift; ( cd "$d" && "$@" ); }

P=projects
echo "== 01 secure CI/CD"
if need ruff "ruff lint"; then run "ruff lint (01 app)" in_dir $P/01-secure-cicd-pipeline/app ruff check .; fi
run "unit tests (01 app)" in_dir $P/01-secure-cicd-pipeline/app python3 -m unittest discover -s tests
if need hadolint "hadolint Dockerfile"; then run "hadolint Dockerfile" hadolint $P/01-secure-cicd-pipeline/Dockerfile; fi

echo "== 02 Terraform"
if need terraform "terraform fmt"; then run "terraform fmt -check" in_dir $P/02-aws-terraform-platform terraform fmt -recursive -check; fi
run "module wiring check" python3 -I $P/02-aws-terraform-platform/scripts/check_wiring.py
if need ruff "ruff lint (02 scripts)"; then run "ruff lint (02 scripts)" in_dir $P/02-aws-terraform-platform ruff check .; fi

echo "== 03 Kubernetes + GitOps"
if need kustomize "kustomize build"; then
  for env in dev prod; do
    run "kustomize build ($env)" kustomize build $P/03-k8s-gitops/k8s/overlays/$env
    run "policy check ($env)" bash -c "kustomize build $P/03-k8s-gitops/k8s/overlays/$env | python3 -I $P/03-k8s-gitops/scripts/policy_check.py"
  done
  run "policy checker tests (mutation)" python3 -m unittest $P/03-k8s-gitops/scripts/test_policy_check.py
fi
if need ruff "ruff lint (03 scripts)"; then run "ruff lint (03 scripts)" in_dir $P/03-k8s-gitops ruff check .; fi

echo "== 04 observability"
D=$P/04-observability-slo
run "generated SLO rules up to date" python3 -I $D/prometheus/gen_slo_rules.py --check
run "generated dashboard up to date" python3 -I $D/grafana/build_dashboard.py --check
if need promtool "promtool"; then
  run "promtool check config" promtool check config $D/prometheus/prometheus.yml
  run "promtool check rules" promtool check rules $D/prometheus/rules/slo-recording.yml $D/prometheus/rules/slo-alerts.yml $D/prometheus/rules/service-alerts.yml
  run "promtool test rules (alert unit tests)" promtool test rules $D/prometheus/tests/slo_alerts_test.yml
fi
if need amtool "amtool check-config"; then run "amtool check-config" amtool check-config $D/alertmanager/alertmanager.yml; fi
if need docker "compose config"; then run "docker compose config" in_dir $D docker compose config -q; fi
if need ruff "ruff lint (04)"; then run "ruff lint (04)" in_dir $D ruff check .; fi

echo "== 05 AI reliability platform"
D=$P/05-ai-reliability-platform
if need ruff "ruff lint (05)"; then run "ruff lint (05)" in_dir $D ruff check .; fi
run "unit and e2e tests (05)" in_dir $D python3 -m unittest discover -s tests -t . -v
run "config validation (05)" in_dir $D python3 -I scripts/validate_configs.py
if need docker "compose config (05)"; then run "docker compose config (05)" in_dir $D docker compose config -q; fi

echo "== 06 self-service platform"
D=$P/06-self-service-platform
if need ruff "ruff lint (06)"; then
  run "ruff lint (06)" in_dir $D ruff check .
  run "ruff format --check (06)" in_dir $D ruff format --check .
fi
run "tests (06)" in_dir $D python3 -m unittest discover -s tests -t . -v
run "compliant example passes policy" in_dir $D python3 -m platformctl validate examples/generated/orders-api
run "non-compliant example is rejected" bash -c "! ( cd $D && python3 -m platformctl validate examples/non-compliant/legacy-batch >/dev/null 2>&1 )"

echo "== 07 SRE reliability lab"
D=$P/07-sre-reliability-lab
if need ruff "ruff lint (07)"; then
  run "ruff lint (07)" in_dir $D ruff check .
  run "ruff format --check (07)" in_dir $D ruff format --check .
fi
run "SLO definitions valid" bash -c "cd $D && python3 -m slogen check slo/*.yaml"
run "generated alert rules up to date" in_dir $D python3 -m slogen generate slo/shop-api.yaml -o generated/shop-api.rules.yml --check
run "config consistency (07)" in_dir $D python3 -I scripts/validate_configs.py
run "tests incl. live chaos runs (07)" in_dir $D python3 -m unittest discover -s tests -t . -v
if need promtool "promtool check rules (07)"; then run "promtool check rules (07)" promtool check rules $D/generated/shop-api.rules.yml; fi
if need docker "compose config (07)"; then run "docker compose config (07)" in_dir $D docker compose config -q; fi

echo "== 08 disaster recovery autopilot"
D=$P/08-disaster-recovery-autopilot
if need ruff "ruff lint (08)"; then
  run "ruff lint (08)" in_dir $D ruff check .
  run "ruff format --check (08)" in_dir $D ruff format --check .
fi
run "playbook validation (08)" in_dir $D python3 -m drpilot check
if need_mod pytest "pytest (08, needs PostgreSQL)"; then run "pytest (08)" in_dir $D python3 -m pytest -q; fi
if need promtool "promtool check rules (08)"; then run "promtool check rules (08)" promtool check rules $D/observability/rules/drpilot.rules.yml; fi

echo "== schematics and workflows"
if need mmdc "schematics compile"; then
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
  for f in "$P"/0[0-8]-*/docs/schematics/*.mmd; do
    run "schematic compiles: $(basename "$f")" mmdc -q -i "$f" -o "$tmp/$(basename "$f" .mmd).svg" -c scripts/mermaid.config.json -b white
  done
fi
if need actionlint "actionlint"; then run "actionlint (all workflows)" actionlint .github/workflows/*.yml; fi
if need shellcheck "shellcheck"; then run "shellcheck (this script)" shellcheck scripts/verify.sh; fi

printf '\nSummary: %d passed, %d failed, %d skipped\n' "$pass" "$fail" "$skip"
[ "$fail" -eq 0 ]
