# Design notes

## Goals
1. A new service is deployable and observable on day one (paved road).
2. Guardrails are code that runs locally and in CI, with stable rule IDs people can look up and suppress by policy rather than by argument.
3. Teams declare intent (`tier`, `owner`); the platform owns the details.
4. Cloud changes are reviewable pull requests, never console clicks.

## Decisions and trade-offs

| Decision | Reason | Trade-off |
|---|---|---|
| Intent-based `service.yaml` with tiers | Consistency across the fleet; one place to change what "critical" means | Less flexibility; escape hatches must be deliberate (policy overrides) |
| Policy checks are plain Python functions returning findings with IDs | Easy to read, test and extend; no policy-language learning curve | Does not scale to hundreds of rules or cross-resource policies; OPA/Kyverno would take over there |
| Scaffolded output must pass the platform's own policy (tested for every tier) | The paved road can never contradict the guardrails | Templates and policy must evolve together |
| Custom Jinja delimiters (`[[ ]]`) | GitHub Actions `${{ }}` and HCL braces pass through untouched | Slightly unusual syntax in template files |
| Unknown spec fields are errors | Typos like `replicsa: 3` should fail loudly, not be silently ignored | Adding a field needs a schema update |
| Warnings vs errors, plus `--strict` | Roll out new rules as warnings first, then promote | Needs discipline to promote |
| OIDC deploy roles scoped to one repo and one ECR repository; prod only from a GitHub environment | No long-lived cloud credentials; blast radius of a compromised repo is one registry | Requires one-time OIDC provider setup per account |
| Env requests as generated `.tf` files in a shared root module | Reviewable diff, plan in CI, simple mental model | One state file per root module grows; split per team/account later |
| Catalog is derived from the repos, not hand-maintained | Cannot drift from reality | Only as good as the specs; ownership of a repo without a spec is invisible |

## Extending
- **New language**: add a template directory and a `language` value in `models.LANGUAGES`; the policy checks are language-agnostic.
- **New rule**: add a function in `policy.py`, give it an ID, add a mutation case in `tests/test_policy.py`.
- **Promote a warning to an error**: change the severity and update the table-driven test.

## Deliberately out of scope
Multi-cluster delivery (GitOps/Argo CD), a developer portal UI, secrets management, runtime policy enforcement (admission control).
