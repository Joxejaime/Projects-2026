"""Replay an incident through the burn-rate alert policies, and error-budget arithmetic.

Assumes constant traffic, so an error *ratio* averaged over a window equals the Prometheus
rate ratio. Time resolution is one minute. This answers: "if X% of requests fail for Y minutes,
which alerts fire, how long after the start, and how much budget is gone by then?"
"""

from __future__ import annotations

from dataclasses import dataclass

from .policies import POLICIES, BurnPolicy


def minutes(window: str) -> int:
    unit = {"m": 1, "h": 60, "d": 1440, "w": 10080}[window[-1]]
    return int(window[:-1]) * unit


@dataclass(frozen=True)
class Incident:
    start: int  # minute index at which the incident begins
    duration: int  # minutes
    error_ratio: float  # fraction of requests failing during the incident


@dataclass(frozen=True)
class PolicyResult:
    policy: BurnPolicy
    threshold: float
    fired: bool
    detection_delay: int | None  # minutes after incident start when the alert fires (including `for`)
    budget_consumed_at_detection: float | None  # fraction of the SLO-window budget
    resolved_after_end: int | None  # minutes after the incident ended until the alert stops firing


def budget_consumed(incident: Incident, error_budget: float, window_minutes: int, upto: int | None = None) -> float:
    """Fraction of the window's error budget consumed by the incident (optionally only up to a minute)."""
    elapsed = incident.duration if upto is None else max(0, min(incident.duration, upto - incident.start + 1))
    return incident.error_ratio * elapsed / (window_minutes * error_budget)


def simulate(objective: float, window: str, incident: Incident, policies=POLICIES, tail_minutes: int = 3 * 1440) -> list[PolicyResult]:
    error_budget = round(1 - objective / 100, 12)
    window_minutes = minutes(window)
    horizon = incident.start + incident.duration + tail_minutes
    series = [incident.error_ratio if incident.start <= t < incident.start + incident.duration else 0.0 for t in range(horizon)]
    prefix = [0.0]
    for value in series:
        prefix.append(prefix[-1] + value)

    def avg(t: int, width: int) -> float:  # mean of the last `width` minutes ending at minute t (missing history = 0)
        lo = max(0, t - width + 1)
        return (prefix[t + 1] - prefix[lo]) / width

    results = []
    for p in policies:
        threshold = p.burn_rate * error_budget
        long_w, short_w = minutes(p.long_window), minutes(p.short_window)
        consecutive, detected, resolved = 0, None, None
        for t in range(horizon):
            active = avg(t, long_w) > threshold and avg(t, short_w) > threshold
            consecutive = consecutive + 1 if active else 0
            if detected is None and consecutive >= p.for_minutes:
                detected = t
            if detected is not None and resolved is None and t >= incident.start + incident.duration and not active:
                resolved = t - (incident.start + incident.duration)
        results.append(
            PolicyResult(
                policy=p,
                threshold=threshold,
                fired=detected is not None,
                detection_delay=None if detected is None else detected - incident.start,
                budget_consumed_at_detection=None
                if detected is None
                else budget_consumed(incident, error_budget, window_minutes, upto=detected),
                resolved_after_end=resolved,
            )
        )
    return results


def budget_report(objective: float, window: str, good: int, total: int) -> dict:
    """Error-budget status from event counts over the SLO window."""
    if total <= 0 or not 0 <= good <= total:
        raise ValueError("need 0 <= good <= total and total > 0")
    error_budget = 1 - objective / 100
    allowed_bad = total * error_budget
    bad = total - good
    window_minutes = minutes(window)
    return {
        "sli": good / total,
        "objective": objective / 100,
        "allowed_bad_events": allowed_bad,
        "bad_events": bad,
        "budget_consumed": bad / allowed_bad,
        "budget_remaining": round(1 - bad / allowed_bad, 12) + 0.0,
        "full_outage_minutes_allowed": window_minutes * error_budget,
        # compare with a tolerance so an SLI exactly on the objective is "met" despite float rounding
        "met": bad <= allowed_bad * (1 + 1e-9),
    }
