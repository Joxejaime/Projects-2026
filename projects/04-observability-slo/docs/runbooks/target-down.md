# Runbook: TargetDown / CrashLooping

**What it means:** Prometheus cannot scrape the service, or the process keeps restarting.

## Triage
1. Is the process running? (`docker compose ps`, `kubectl get pods -n release-tracker-<env>`, ECS service events.)
2. Why did it stop? Container exit code and last log lines: OOM-kill (exit 137), crash on start, failed
   health checks, failed image pull.
3. Is it a scrape problem rather than an outage? Check NetworkPolicy/security-group changes: Prometheus
   must reach port 8080 (`/metrics`). Compare with `curl` from inside the network.
4. Recent change? Roll back the release or configuration.

## Mitigate
- Restore a known-good version; for OOM, raise the memory limit (and find out why it grew).
- If only metrics are unreachable but user traffic is fine, downgrade urgency and fix the scrape path.
