"""Twelve-factor configuration: everything comes from GATEWAY_* environment variables."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    host: str = "0.0.0.0"  # noqa: S104 - container workload, exposure is controlled by the platform
    port: int = 8080
    admin_token: str = ""  # empty => admin endpoints are disabled
    # "key1:tenant-a,key2:tenant-b". When set, /v1/chat requires `Authorization: Bearer <key>` and the tenant
    # comes from the key, never from the X-Tenant header. Empty keeps the unauthenticated lab mode.
    api_keys: str = ""
    request_timeout: float = 2.0
    attempt_timeout: float = 0.8
    max_attempts: int = 3
    retry_base: float = 0.05
    retry_cap: float = 0.4
    breaker_failure_threshold: int = 5
    breaker_recovery_timeout: float = 15.0
    rate_limit_rps: float = 20.0
    rate_limit_burst: float = 40.0
    # One bucket shared by every tenant: a client that invents tenant names gets a fresh per-tenant bucket
    # each time, so only a global ceiling bounds total throughput (and therefore provider spend).
    global_rate_limit_rps: float = 200.0
    global_rate_limit_burst: float = 400.0
    tenant_token_budget: int = 100_000
    budget_window_seconds: float = 3600.0
    cache_ttl: float = 300.0
    cache_max_entries: int = 1024
    primary_latency: float = 0.12
    fallback_latency: float = 0.25
    shutdown_grace: float = 5.0  # seconds /readyz reports not-ready before the server stops
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Config:
        env = os.environ if env is None else env
        defaults = cls()
        values = {}
        for field_name, default in defaults.__dict__.items():
            raw = env.get(f"GATEWAY_{field_name.upper()}")
            if raw is None or raw == "":
                continue
            try:
                values[field_name] = type(default)(raw)
            except ValueError as exc:
                raise ValueError(
                    f"GATEWAY_{field_name.upper()}={raw!r} is not a valid {type(default).__name__}"
                ) from exc
        return cls(**values)
