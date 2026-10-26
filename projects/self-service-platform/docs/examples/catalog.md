# Service catalog

5 valid service(s), 0 invalid.

| Service | Owner | Tier | SLO | Replicas | Environments | Spec |
|---|---|---|---|---|---|---|
| legacy-batch | team-ops | critical | 99.95% | 1 | dev, prod | `non-compliant/legacy-batch/service.yaml` |
| notifications | team-orders | best-effort | 99% | 1 | dev, prod | `catalog/notifications/service.yaml` |
| orders-api | team-orders | standard | 99.9% | 2 | dev, prod | `generated/orders-api/service.yaml` |
| payments-api | team-payments | critical | 99.95% | 3 | dev, prod | `catalog/payments-api/service.yaml` |
| search-indexer | team-search | standard | 99.9% | 2 | dev, prod | `catalog/search-indexer/service.yaml` |

## Summary

**By tier:** best-effort: 1, critical: 2, standard: 2
**By owner:** team-ops: 1, team-orders: 2, team-payments: 1, team-search: 1
