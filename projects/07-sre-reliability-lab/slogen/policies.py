"""Multi-window, multi-burn-rate alert policies (Google SRE Workbook, chapter 5).

Burn rate = observed error ratio / allowed error ratio. A burn rate of 1 uses exactly the whole
error budget over the SLO window; 14.4 over a 30-day window means 2% of the budget per hour.
Each policy needs BOTH windows above threshold: the long window shows the burn is significant,
the short window shows it is still happening (so the alert resets quickly after a fix).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BurnPolicy:
    name: str
    long_window: str
    short_window: str
    burn_rate: float
    severity: str
    for_minutes: int
    meaning: str


POLICIES = (
    BurnPolicy("FastBurn", "1h", "5m", 14.4, "page", 2, "2% of the error budget in 1 hour"),
    BurnPolicy("ModerateBurn", "6h", "30m", 6.0, "page", 5, "5% of the error budget in 6 hours"),
    BurnPolicy("SlowBurn", "1d", "2h", 3.0, "ticket", 15, "10% of the error budget in 1 day"),
    BurnPolicy("Drift", "3d", "6h", 1.0, "ticket", 15, "10% of the error budget in 3 days"),
)

RECORDING_WINDOWS = ("5m", "30m", "1h", "2h", "6h", "1d", "3d")
