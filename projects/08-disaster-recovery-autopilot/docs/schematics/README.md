# Schematics: 08-disaster-recovery-autopilot

Diagrams are Mermaid, so GitHub renders them inline below. Each also has a rendered `.svg` next to its
`.mmd` source. Edit the `.mmd` file, then run `python3 scripts/build_schematics.py` from the repository root.

## System architecture

Two ways in: Prometheus and Alertmanager post to the responder's webhook, or the probe watcher turns a health endpoint into the same alert payloads. The responder opens an incident, picks the most specific playbook, runs its steps (commands without a shell, HTTP calls with secrets from the environment) and only calls the service recovered after consecutive healthy probes. When every alert in the incident has resolved, it renders a postmortem draft and can open it as a GitHub issue for review.

```mermaid
%% title: System architecture
%% headline: When something breaks, recover it and write it down
%% takeaway: An alert opens an incident, a playbook recovers and verifies, resolution writes the postmortem draft.
%% legend: app=Service,obs=Detection,guard=Responder,alert=Recovery actions,data=State and backups,ok=Postmortem
%% caption: Two ways in: Prometheus and Alertmanager post to the responder's webhook, or the probe watcher turns a health endpoint into the same alert payloads. The responder opens an incident, picks the most specific playbook, runs its steps (commands without a shell, HTTP calls with secrets from the environment) and only calls the service recovered after consecutive healthy probes. When every alert in the incident has resolved, it renders a postmortem draft and can open it as a GitHub issue for review.
flowchart LR
    subgraph svc["Service under test"]
        notes["notes service<br/>/healthz checks data"]
        data[("data file<br/>+ checksum")]
        snaps[("verified<br/>snapshots")]
        notes --- data
    end
    subgraph detect["Detection"]
        prom["Prometheus +<br/>Alertmanager"]
        watch["probe watcher"]
    end
    subgraph resp["drpilot responder"]
        hook["POST /alerts<br/>bearer token"]
        engine["incident engine"]
        books["playbooks<br/>RTO / RPO"]
        store[("incident store<br/>JSON")]
        hook --> engine
        books --> engine
        engine --> store
    end
    pm["postmortem draft<br/>Markdown"]
    gh["GitHub issue<br/>for review"]
    notes -. scrape / probe .-> prom
    notes -. probe .-> watch
    prom -->|webhook| hook
    watch -->|webhook| hook
    engine -->|"restore + reload"| notes
    snaps -->|restore| data
    engine -->|"verify: N healthy probes"| notes
    engine -->|"all alerts resolved"| pm --> gh

    classDef app fill:#DBEAFE,stroke:#2563EB,stroke-width:2.5px,color:#0B2A5B
    classDef guard fill:#CCFBF1,stroke:#0D9488,stroke-width:2.5px,color:#04443F
    classDef data fill:#FEF3C7,stroke:#D97706,stroke-width:2.5px,color:#5B3300
    classDef obs fill:#EDE9FE,stroke:#7C3AED,stroke-width:2.5px,color:#2E1065
    classDef alert fill:#FFE4E6,stroke:#E11D48,stroke-width:2.5px,color:#6B0A20
    classDef ok fill:#DCFCE7,stroke:#16A34A,stroke-width:2.5px,color:#0B3D1E
    class notes app
    class data,snaps,store data
    class prom,watch obs
    class hook,engine guard
    class books alert
    class pm,gh ok
    style svc fill:#EFF6FF,stroke:#93C5FD,stroke-width:2px,color:#1E3A8A
    style detect fill:#F5F3FF,stroke:#C4B5FD,stroke-width:2px,color:#4C1D95
    style resp fill:#F0FDFA,stroke:#5EEAD4,stroke-width:2px,color:#134E4A
```

[SVG](01-architecture.svg) · [source](01-architecture.mmd)

## Incident lifecycle

The states an incident moves through. Repeated notifications for a firing alert do not re-run recovery. An incident closes only when every alert in it has resolved and no recovery is still running, so the postmortem always includes the full automation record. With no matching playbook, or after the last failed attempt, the incident is escalated, and the draft says so and proposes the follow-up.

```mermaid
%% title: Incident lifecycle
%% headline: Automation tries first, a human is never skipped
%% takeaway: Every path ends in a postmortem draft, including the ones where automation failed.
%% legend: alert=Alert and escalation,guard=Automation,ok=Recovered and closed
%% caption: The states an incident moves through. Repeated notifications for a firing alert do not re-run recovery. An incident closes only when every alert in it has resolved and no recovery is still running, so the postmortem always includes the full automation record. With no matching playbook, or after the last failed attempt, the incident is escalated, and the draft says so and proposes the follow-up.
flowchart TB
    fire(["alert fires"]) --> open["Open<br/>detection time recorded"]
    open -->|playbook matches| rec["Recovering<br/>run steps, then verify<br/>retry up to max_attempts"]
    open -->|no playbook| esc["Escalated<br/>human paged"]
    rec -->|"steps ok and<br/>N healthy probes"| mit["Mitigated"]
    rec -->|out of attempts| esc
    mit -->|all alerts resolved| res["Resolved"]
    esc -->|"human fixes it,<br/>alerts resolve"| res
    res -->|"no recovery still running"| closed(["Closed<br/>postmortem draft written"])

    classDef guard fill:#CCFBF1,stroke:#0D9488,stroke-width:2.5px,color:#04443F
    classDef alert fill:#FFE4E6,stroke:#E11D48,stroke-width:2.5px,color:#6B0A20
    classDef ok fill:#DCFCE7,stroke:#16A34A,stroke-width:2.5px,color:#0B3D1E
    class fire,open,esc alert
    class rec guard
    class mit,res,closed ok
```

[SVG](02-incident-lifecycle.svg) · [source](02-incident-lifecycle.mmd)
