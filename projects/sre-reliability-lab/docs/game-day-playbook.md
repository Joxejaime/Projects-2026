# Game day playbook

A game day is a planned, bounded failure exercise. The goal is to find out whether the system, the alerts and the
people behave the way the runbooks claim, **before** a real incident does it for you.

## Before
- [ ] Write a **hypothesis** that can be proven wrong (see `chaos/scenarios/`): what fails, what must stay healthy, how fast recovery happens.
- [ ] Define **steady state** with numbers (error ratio, latency) and check it first. The runner refuses to inject if it does not hold.
- [ ] Define the **abort condition** (the runner enforces it every second) and a human "stop" word.
- [ ] Pick a **control**: something that should *not* be affected, so blast radius is measured rather than assumed.
- [ ] Decide which alerts should fire and which should not.
- [ ] Tell the people who will see the pages. Never run a game day against production without sign-off.

## During
1. Confirm steady state. 2. Inject. 3. Watch the dashboard and the alerts, not just the runner.
4. Abort immediately if the guardrail trips or anything surprising happens. 5. Clear the fault and watch recovery.

The runner always clears faults on exit (including on errors and Ctrl-C), but verify with `GET /admin/state`-style checks anyway.

## After (same day)
- [ ] Record results: what was predicted vs observed.
- [ ] Did the expected alerts fire, how fast, and did anything fire that should not have? Was the runbook enough?
- [ ] Write findings as action items with owners. Treat a surprise as a success: you found it cheaply.

## Running the lab experiments
```bash
make up              # full stack (Prometheus, Alertmanager, Grafana) for watching alerts live
make chaos-errors    # 30% of /checkout fails for 20 s
make chaos-latency   # /checkout gains 400 ms for 20 s: slow, but not failing
```
Without Docker: `make demo` runs the demo service on :8081 and you can point the runner at it.
