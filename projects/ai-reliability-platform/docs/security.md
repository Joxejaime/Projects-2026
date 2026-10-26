# Security notes

## Controls in place
- **Container**: non-root numeric UID, read-only root filesystem (compose/k8s/ECS), all capabilities
  dropped, `no-new-privileges`, no shell tooling beyond the Python runtime image.
- **Kubernetes**: `restricted` Pod Security level, `seccompProfile: RuntimeDefault`, no service-account
  token mount, default-deny NetworkPolicy with explicit DNS/443 egress.
- **AWS**: tasks in private subnets with no public IPs; task security group accepts traffic only from
  the ALB security group; immutable ECR tags with scan on push; empty task role (least privilege).
- **Input handling**: body size cap, prompt length cap, strict type validation, tenant-name allow-list
  regex, unknown routes collapsed to `other` in metrics (no label-cardinality attacks).
- **Memory safety**: per-tenant limiter and budget tables are LRU-bounded.
- **Admin surface**: fault-injection routes do not exist unless `GATEWAY_ADMIN_TOKEN` is set;
  comparison is constant-time. The compose file uses a documented lab-only token.
- **CI**: least-privilege `permissions`, image vulnerability scan (fails on fixable HIGH/CRITICAL),
  IaC misconfiguration scan (report-only), provenance and SBOM attached to release images.

## Known gaps (honest list)
- No authentication or authorization: `X-Tenant` is trusted. Put an authenticating proxy or API
  gateway in front, or add JWT validation.
- GitHub Actions are pinned to major version tags, not commit SHAs.
- Base image is pinned by tag, not digest.
- No TLS termination in the app; use the ALB (set `certificate_arn`) or an ingress controller.
- IaC scan findings are report-only until triaged.
