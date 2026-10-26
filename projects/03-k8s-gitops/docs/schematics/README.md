# Schematics: 03-k8s-gitops

Diagrams are Mermaid, so GitHub renders them inline below. Each also has a rendered `.svg` next to its
`.mmd` source. Edit the `.mmd` file, then run `python3 scripts/build_schematics.py` from the repository root.

## GitOps promotion

.github/workflows/03-k8s-gitops.yml and argocd/. The promote job checks the tag format, bumps the overlay, re-renders and policy-checks the promoted manifests, then opens a pull request. Argo CD auto-syncs dev with prune and self-heal; prod has no automated sync and needs an explicit one.

```mermaid
%% title: GitOps promotion
%% headline: Promotion is a pull request; Git is the source of truth
%% takeaway: Dev syncs automatically, prod waits for a human, and rollback is a revert.
%% caption: .github/workflows/03-k8s-gitops.yml and argocd/. The promote job checks the tag format, bumps the overlay, re-renders and policy-checks the promoted manifests, then opens a pull request. Argo CD auto-syncs dev with prune and self-heal; prod has no automated sync and needs an explicit one.
sequenceDiagram
  autonumber
  actor Eng as Engineer
  participant GH as GitHub Actions (workflow 03)
  participant Git as Git main branch
  participant Argo as Argo CD
  participant Dev as Cluster: release-tracker-dev
  participant Prod as Cluster: release-tracker-prod

  Eng->>GH: Run workflow: environment, image_tag = sha-40hex
  GH->>GH: validate and policy-tests jobs on current main
  GH->>GH: Check tag format, kustomize edit set image
  GH->>GH: Re-render the bumped overlay: kubeconform, policy_check.py
  GH-->>Git: Open promotion pull request (only if all checks passed)
  Eng->>Git: Review checks, merge PR
  Argo->>Git: Poll or webhook, sees new overlay commit
  alt dev overlay changed
    Argo->>Dev: Automated sync with prune and selfHeal
    Dev-->>Argo: Healthy
  else prod overlay changed
    Argo-->>Eng: OutOfSync, waiting for a human
    Eng->>Argo: Press Sync or run argocd app sync
    Argo->>Prod: Apply with ServerSideApply
    Prod-->>Argo: Healthy
  end
  Note over Eng,Prod: Rollback = revert the promotion PR, then sync
```

[SVG](03a-gitops-promotion.svg) · [source](03a-gitops-promotion.mmd)

## Manifest guardrails

scripts/policy_check.py and scripts/test_policy_check.py. Overlays are rendered with kustomize, then checked against Kubernetes schemas and a policy script. 13 tests mutate known-good manifests and require the checker to reject them, so the policy is proven able to fail.

```mermaid
%% title: Manifest guardrails
%% headline: Two gates on every rendered manifest
%% takeaway: Schema validation plus tested policy checks, run on the final YAML.
%% legend: app=Manifests,guard=Render and gates,data=Tests of the gates,ok=Merge allowed
%% caption: scripts/policy_check.py and scripts/test_policy_check.py. Overlays are rendered with kustomize, then checked against Kubernetes schemas and a policy script. 13 tests mutate known-good manifests and require the checker to reject them, so the policy is proven able to fail.
flowchart TB
  base["k8s/base<br/>Deployment, Service, HPA, PDB,<br/>NetworkPolicy, Ingress, ServiceAccount"]
  dev["overlay dev<br/>1 replica, small HPA, PDB minAvailable 0"]
  prod["overlay prod<br/>3 replicas, HPA 3 to 10, PDB minAvailable 2,<br/>hard zone spread, bigger limits"]
  base --> dev
  base --> prod

  kb["kustomize build<br/>renders the final YAML per environment"]
  dev --> kb
  prod --> kb

  kc["kubeconform, strict<br/>Kubernetes 1.31 schemas plus Argo CD CRDs<br/>catches wrong fields and kinds"]
  pc["policy_check.py enforces<br/>non-root, read-only root filesystem, no privilege escalation<br/>drop ALL capabilities, seccomp RuntimeDefault<br/>requests and limits, probes, pinned image tag<br/>HPA and PDB exist, no host namespaces, no SA token<br/>default-deny NetworkPolicy, namespace Pod Security restricted"]
  kb --> kc
  kb --> pc

  tests["test_policy_check.py<br/>13 tests mutate good manifests<br/>and expect the checker to reject them"]
  tests -.->|"proves the checker can fail"| pc

  ok(["All gates green: merge allowed"])
  kc --> ok
  pc --> ok

    classDef entry fill:#E0E7FF,stroke:#4F46E5,stroke-width:2.5px,color:#1E1B4B
    classDef app fill:#DBEAFE,stroke:#2563EB,stroke-width:2.5px,color:#0B2A5B
    classDef guard fill:#CCFBF1,stroke:#0D9488,stroke-width:2.5px,color:#04443F
    classDef data fill:#FEF3C7,stroke:#D97706,stroke-width:2.5px,color:#5B3300
    classDef obs fill:#EDE9FE,stroke:#7C3AED,stroke-width:2.5px,color:#2E1065
    classDef alert fill:#FFE4E6,stroke:#E11D48,stroke-width:2.5px,color:#6B0A20
    classDef ok fill:#DCFCE7,stroke:#16A34A,stroke-width:2.5px,color:#052E16
    classDef cloud fill:#FFEDD5,stroke:#EA580C,stroke-width:2.5px,color:#431407
    classDef neutral fill:#F1F5F9,stroke:#64748B,stroke-width:2.5px,color:#0F172A
    class base,dev,prod app
    class kb,kc,pc guard
    class tests data
    class ok ok
```

[SVG](03b-manifest-guardrails.svg) · [source](03b-manifest-guardrails.mmd)
