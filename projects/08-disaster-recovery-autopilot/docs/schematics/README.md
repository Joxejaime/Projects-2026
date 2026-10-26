# Schematics: 08-disaster-recovery-autopilot

Diagrams are Mermaid, so GitHub renders them inline below. Each also has a rendered `.svg` next to its
`.mmd` source. Edit the `.mmd` file, then run `python3 scripts/build_schematics.py` from the repository root.

## System architecture

Project 04's Prometheus and Alertmanager detect the failure and route alerts labelled autoremediate to drpilot while still paging people. The responder opens an incident and runs the most specific playbook: restore the newest snapshot that proves itself (checksum, scratch restore and data checks, in that order), or re-apply project 02's Terraform for dev, or roll back project 03's Deployment. Recovery only counts after consecutive healthy probes and passing data checks. A scheduled restore test feeds metrics back to Prometheus, so a backup that stops restoring raises an alert before it is needed. When every alert has resolved the postmortem draft is written, optionally as a GitHub issue.

```mermaid
%% title: System architecture
%% headline: Detect with 04, recover with 02 and 03, write it down
%% takeaway: drpilot adds recovery and postmortems on top of the monitoring and deployment tooling already in the repo.
%% legend: app=Service and data,obs=Project 04 detection,guard=drpilot responder,alert=Recovery actions,data=Backups,ok=Postmortem
%% caption: Project 04's Prometheus and Alertmanager detect the failure and route alerts labelled autoremediate to drpilot while still paging people. The responder opens an incident and runs the most specific playbook: restore the newest snapshot that proves itself (checksum, scratch restore and data checks, in that order), or re-apply project 02's Terraform for dev, or roll back project 03's Deployment. Recovery only counts after consecutive healthy probes and passing data checks. A scheduled restore test feeds metrics back to Prometheus, so a backup that stops restoring raises an alert before it is needed. When every alert has resolved the postmortem draft is written, optionally as a GitHub issue.
flowchart LR
    subgraph svc["Service and data"]
        orders["orders service<br/>/healthz /metrics"]
        pg[("PostgreSQL")]
        orders --- pg
    end
    subgraph p04["Project 04: detection"]
        prom["Prometheus"]
        am["Alertmanager<br/>pager + ticket + drpilot route"]
        prom --> am
    end
    subgraph resp["drpilot responder"]
        hook["POST /alerts<br/>bearer token"]
        engine["incident engine"]
        books["playbooks<br/>RTO / RPO"]
        store[("incident store")]
        hook --> engine
        books --> engine
        engine --> store
    end
    subgraph act["Recovery actions"]
        restore["recover.py restore<br/>checksum, scratch restore, validate"]
        tf["terraform apply<br/>project 02, dev only"]
        k8s["kubectl rollout undo<br/>project 03"]
    end
    snaps[("snapshots<br/>local dir or S3 bucket<br/>dump + manifest")]
    rtest["restore-test<br/>scheduled"]
    pm["postmortem draft"]
    gh["GitHub issue<br/>for review"]
    orders -. metrics .-> prom
    am -->|webhook| hook
    engine --> restore
    engine --> tf
    engine --> k8s
    snaps --> restore
    restore -->|"pg_restore"| pg
    engine -->|"verify: probes + data checks"| orders
    snaps --> rtest
    rtest -. textfile metrics .-> prom
    engine -->|"all alerts resolved"| pm --> gh

    classDef app fill:#DBEAFE,stroke:#2563EB,stroke-width:2.5px,color:#0B2A5B
    classDef guard fill:#CCFBF1,stroke:#0D9488,stroke-width:2.5px,color:#04443F
    classDef data fill:#FEF3C7,stroke:#D97706,stroke-width:2.5px,color:#5B3300
    classDef obs fill:#EDE9FE,stroke:#7C3AED,stroke-width:2.5px,color:#2E1065
    classDef alert fill:#FFE4E6,stroke:#E11D48,stroke-width:2.5px,color:#6B0A20
    classDef ok fill:#DCFCE7,stroke:#16A34A,stroke-width:2.5px,color:#0B3D1E
    class orders,pg app
    class snaps,store,rtest data
    class prom,am obs
    class hook,engine guard
    class books,restore,tf,k8s alert
    class pm,gh ok
    style svc fill:#EFF6FF,stroke:#93C5FD,stroke-width:2px,color:#1E3A8A
    style p04 fill:#F5F3FF,stroke:#C4B5FD,stroke-width:2px,color:#4C1D95
    style resp fill:#F0FDFA,stroke:#5EEAD4,stroke-width:2px,color:#134E4A
    style act fill:#FFF1F2,stroke:#FDA4AF,stroke-width:2px,color:#881337
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
