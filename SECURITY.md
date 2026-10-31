# Security policy

This repository is a DevOps portfolio. Nothing here runs in production and no real AWS account or cluster
is attached, but the code is written to production standards and security reports are welcome.

## Reporting a vulnerability

Please **do not open a public issue** for a security problem.

- Use GitHub's private reporting: **Security tab → Report a vulnerability**, or
- email [castilloajosejaime@gmail.com](mailto:castilloajosejaime@gmail.com) with "SECURITY" in the subject.

Include what you found, where (file and line), and how to reproduce it. I aim to reply within 7 days.

## What is in scope

- Secrets or credentials committed to the repository or its history.
- Weaknesses in the CI/CD workflows (injection, excess permissions, unpinned or mutable dependencies).
- IAM trust policies, Terraform, Kubernetes manifests or container images that are weaker than they claim.
- Vulnerabilities in the sample services (the release tracker, the AI gateway, the SRE demo, the DR webhook).

## Known and accepted

Each project README ends with a verification table and the security docs list known gaps (for example the
AI gateway's opt-in authentication and the Checkov findings accepted with a written reason). Reports that
repeat a documented gap are still welcome if they show a way to exploit it.

## Supported versions

Only the `main` branch is maintained.
