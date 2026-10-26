"""SLO definition model and validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

DURATION_RE = re.compile(r"^(\d+)([smhdw])$")
UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
METRIC_RE = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
MATCHER = r'[a-zA-Z_][a-zA-Z0-9_]*(?:=|!=|=~|!~)"[^"{}\\]*"'
SELECTOR_RE = re.compile(rf"^{MATCHER}(?:\s*,\s*{MATCHER})*$")
NAME_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
SLI_TYPES = {"availability", "latency"}


def parse_duration(text: str) -> int:
    match = DURATION_RE.match(str(text))
    if not match:
        raise ValueError(f"invalid duration {text!r} (examples: 30d, 4w, 90m)")
    return int(match.group(1)) * UNIT_SECONDS[match.group(2)]


@dataclass(frozen=True)
class SLO:
    service: str
    owner: str
    name: str
    description: str
    sli_type: str
    metric: str
    selector: str
    bad: str
    threshold_seconds: float | None
    objective: float  # percent, e.g. 99.9
    window: str
    runbook: str

    @property
    def window_seconds(self) -> int:
        return parse_duration(self.window)

    @property
    def error_budget(self) -> float:
        """Allowed bad-event fraction, e.g. 0.001 for 99.9%."""
        return round(1 - self.objective / 100, 12)


def load_slo_file(path: Path) -> tuple[list[SLO], list[str]]:
    """Return (slos, errors). Errors are human-readable and prefixed with the file name."""
    errors: list[str] = []

    def err(msg: str) -> None:
        errors.append(f"{path}: {msg}")

    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as exc:
        return [], [f"{path}: cannot read: {exc}"]
    if not isinstance(data, dict):
        return [], [f"{path}: top level must be a mapping"]

    service = data.get("service")
    if not isinstance(service, str) or not NAME_RE.match(service):
        err(f"'service' must be a lowercase dash-separated name, got {service!r}")
    owner = str(data.get("owner", ""))
    raw = data.get("slos")
    if not isinstance(raw, list) or not raw:
        err("'slos' must be a non-empty list")
        return [], errors

    slos: list[SLO] = []
    seen: set[str] = set()
    for i, item in enumerate(raw):
        label = f"slos[{i}]"
        if not isinstance(item, dict):
            err(f"{label} must be a mapping")
            continue
        name = item.get("name")
        label = f"slo {name!r}" if name else label
        if not isinstance(name, str) or not NAME_RE.match(name):
            err(f"{label}: 'name' must be lowercase dash-separated")
            continue
        if name in seen:
            err(f"{label}: duplicate name")
        seen.add(name)

        sli = item.get("sli") or {}
        sli_type = sli.get("type")
        if sli_type not in SLI_TYPES:
            err(f"{label}: sli.type must be one of {sorted(SLI_TYPES)}")
        metric = sli.get("metric", "")
        if not isinstance(metric, str) or not METRIC_RE.match(metric):
            err(f"{label}: sli.metric {metric!r} is not a valid Prometheus metric name")
        selector = (sli.get("selector") or "").strip()
        if selector and not SELECTOR_RE.match(selector):
            err(f'{label}: sli.selector {selector!r} must be comma-separated label matchers like job="x"')
        bad = (sli.get("bad") or "").strip()
        threshold = sli.get("threshold_seconds")
        if sli_type == "availability":
            if not bad or not SELECTOR_RE.match(bad):
                err(f'{label}: availability SLIs need sli.bad, a label matcher selecting bad events (e.g. code=~"5..")')
        elif sli_type == "latency" and (isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or threshold <= 0):
            err(f"{label}: latency SLIs need a positive sli.threshold_seconds that matches a histogram bucket")

        objective = item.get("objective")
        if isinstance(objective, bool) or not isinstance(objective, (int, float)) or not 0 < objective < 100:
            err(f"{label}: objective must be a percentage strictly between 0 and 100, got {objective!r}")
            continue
        window = str(item.get("window", "30d"))
        try:
            parse_duration(window)
        except ValueError as exc:
            err(f"{label}: {exc}")
            continue
        slos.append(
            SLO(
                service=str(service),
                owner=owner,
                name=name,
                description=str(item.get("description", "")).strip(),
                sli_type=str(sli_type),
                metric=metric,
                selector=selector,
                bad=bad,
                threshold_seconds=float(threshold) if threshold is not None and sli_type == "latency" else None,
                objective=float(objective),
                window=window,
                runbook=str(item.get("runbook", "")),
            )
        )
    return slos, errors
