# Schematics: 02-aws-terraform-platform

Diagrams are Mermaid, so GitHub renders them inline below. Each also has a rendered `.svg` next to its
`.mmd` source. Edit the `.mmd` file, then run `python3 scripts/build_schematics.py` from the repository root.

## AWS architecture

modules/network and modules/ecs-service. dev uses two AZs and one shared NAT gateway with HTTP allowed; prod uses three AZs, a NAT gateway per AZ, HTTPS only and deletion protection. Task security groups accept traffic from the ALB only, and the task role starts with no permissions.

```mermaid
%% title: AWS architecture
%% headline: Private tasks behind a locked-down load balancer
%% takeaway: Only the ALB is public; tasks have no public IPs and only HTTPS egress.
%% legend: entry=Users and internet,cloud=AWS network,app=Workload,guard=Scaling and identity,obs=Logs,alert=Alarms
%% caption: modules/network and modules/ecs-service. dev uses two AZs and one shared NAT gateway with HTTP allowed; prod uses three AZs, a NAT gateway per AZ, HTTPS only and deletion protection. Task security groups accept traffic from the ALB only, and the task role starts with no permissions.
flowchart TB
  user(["Users"])
  user --> alb

  subgraph VPC["VPC, 2 to 3 AZs"]
    subgraph PUBS["Public subnets"]
      alb["Application Load Balancer<br/>drops invalid headers, TLS 1.3 policy<br/>HTTP redirects to HTTPS in prod"]
      nat["NAT gateway<br/>1 shared in dev, 1 per AZ in prod"]
    end
    subgraph PRIVS["Private subnets, no public IPs"]
      task["ECS Fargate tasks<br/>non-root, read-only root filesystem<br/>circuit breaker with auto rollback"]
    end
    igw["Internet gateway"]
  end

  alb -->|"app port, ALB security group only"| task
  task -->|"HTTPS 443 only"| nat
  nat --> igw
  igw --> net(["Internet<br/>image pulls, AWS APIs"])

  alb -->|"5xx, unhealthy hosts"| alarms["CloudWatch alarms"]
  alarms --> sns["SNS topic<br/>email subscription"]
  task -->|"app logs, plus VPC flow logs"| logs["CloudWatch Logs"]
  asg["Auto Scaling<br/>target 60 percent CPU"] -.->|"desired count"| task
  iam["IAM roles<br/>execution: pull image, write logs<br/>task: starts with no permissions"] -.-> task

    classDef entry fill:#E0E7FF,stroke:#4F46E5,stroke-width:2.5px,color:#1E1B4B
    classDef app fill:#DBEAFE,stroke:#2563EB,stroke-width:2.5px,color:#0B2A5B
    classDef guard fill:#CCFBF1,stroke:#0D9488,stroke-width:2.5px,color:#04443F
    classDef data fill:#FEF3C7,stroke:#D97706,stroke-width:2.5px,color:#5B3300
    classDef obs fill:#EDE9FE,stroke:#7C3AED,stroke-width:2.5px,color:#2E1065
    classDef alert fill:#FFE4E6,stroke:#E11D48,stroke-width:2.5px,color:#6B0A20
    classDef ok fill:#DCFCE7,stroke:#16A34A,stroke-width:2.5px,color:#052E16
    classDef cloud fill:#FFEDD5,stroke:#EA580C,stroke-width:2.5px,color:#431407
    classDef neutral fill:#F1F5F9,stroke:#64748B,stroke-width:2.5px,color:#0F172A
    class user,net entry
    class alb,nat,igw cloud
    class task app
    class alarms,sns alert
    class logs obs
    class asg,iam guard
```

[SVG](02a-aws-architecture.svg) · [source](02a-aws-architecture.mmd)

## Terraform delivery with OIDC

.github/workflows/02-terraform.yml and bootstrap/github-oidc.tf. Pull requests are validated and planned with a read-only role. Applying is a manual run that targets a protected GitHub Environment; the apply role's trust policy only accepts tokens for environment jobs, and state is locked in S3.

```mermaid
%% title: Terraform delivery with OIDC
%% headline: No stored AWS keys anywhere
%% takeaway: Plans use a read-only role; applies need an approved GitHub Environment.
%% caption: .github/workflows/02-terraform.yml and bootstrap/github-oidc.tf. Pull requests are validated and planned with a read-only role. Applying is a manual run that targets a protected GitHub Environment; the apply role's trust policy only accepts tokens for environment jobs, and state is locked in S3.
sequenceDiagram
  autonumber
  actor Dev as Developer
  participant GH as GitHub Actions
  participant STS as AWS STS (OIDC)
  participant S3 as S3 state bucket
  participant AWS as AWS account

  Dev->>GH: Open pull request
  GH->>GH: static job: tofu fmt, wiring check, init -backend=false, validate
  GH->>GH: security job: TFLint and Checkov, SARIF upload
  GH->>STS: AssumeRoleWithWebIdentity as plan role<br/>token subject repo:owner/repo:*
  STS-->>GH: Short-lived read-only credentials
  GH->>S3: Init remote state, lock with use_lockfile
  GH->>AWS: tofu plan (read-only calls)
  GH-->>Dev: Plan summary in the job summary
  Dev->>GH: Merge, then run workflow with apply_env = dev or prod
  Note over GH: Job targets a GitHub Environment,<br/>required reviewers must approve
  GH->>STS: AssumeRoleWithWebIdentity as apply role<br/>token subject repo:owner/repo:environment:*
  STS-->>GH: Short-lived credentials, no stored keys
  GH->>AWS: tofu apply (locked state in S3)
  GH->>S3: Write new state version
```

[SVG](02b-terraform-delivery.svg) · [source](02b-terraform-delivery.mmd)
