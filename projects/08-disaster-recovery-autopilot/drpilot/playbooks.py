"""Recovery playbooks: which alert they handle, the steps that recover, and how recovery is verified.

A playbook is YAML (see playbooks/). Steps are either a command (argv list, never a shell) or an HTTP
call. Values may use placeholders:

    {python}            the interpreter running drpilot
    {playbook_dir}      the directory holding the playbook file
    {env.NAME}          an environment variable (must be set)
    {label.NAME}        a label of the alert that opened the incident

HTTP steps take secrets by environment variable name (bearer_token_env), so playbooks hold no secrets.

Label values come from whoever can reach the webhook, so they are only substituted when they match a
conservative character set; anything else fails the step instead of reaching a command line.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .model import StepResult

SAFE_LABEL = re.compile(r"^[A-Za-z0-9._:/-]{1,128}$")
PLACEHOLDER = re.compile(r"\{([a-z_]+(?:\.[A-Za-z0-9_]+)?)\}")
OUTPUT_LIMIT = 2000


class PlaybookError(ValueError):
    pass


@dataclass(frozen=True)
class Step:
    name: str
    run: list[str] | None = None
    http: dict | None = None
    timeout: float = 30.0


@dataclass(frozen=True)
class Verify:
    """Recovered means: N consecutive healthy probes of `url` (if given), then every data check passes.

    Probes prove the service answers; checks prove the data is right. A health endpoint cannot tell a
    restored database from an empty one, which is why recovery validation is a separate, mandatory-to-pass list.
    """

    url: str | None = None
    expect_status: int = 200
    successes: int = 3
    interval_seconds: float = 1.0
    timeout_seconds: float = 60.0
    checks: tuple[Step, ...] = ()


@dataclass(frozen=True)
class Playbook:
    name: str
    path: Path
    match: dict
    steps: list[Step]
    verify: Verify | None
    max_attempts: int = 1
    objectives: dict = field(default_factory=dict)

    def matches(self, labels: dict) -> bool:
        return all(labels.get(k) == v for k, v in self.match.items())


def _parse_steps(path: Path, items: object, label: str) -> list[Step]:
    if not isinstance(items, list):
        raise PlaybookError(f"{path}: {label}s must be a list")
    steps = []
    for i, s in enumerate(items, 1):
        if not isinstance(s, dict) or "name" not in s or (("run" in s) == ("http" in s)):
            raise PlaybookError(f"{path}: {label} {i} needs a name and exactly one of 'run' or 'http'")
        if "run" in s and not (isinstance(s["run"], list) and s["run"] and all(isinstance(a, str) for a in s["run"])):
            raise PlaybookError(f"{path}: {label} {i} 'run' must be a non-empty list of strings (no shell)")
        if "http" in s and not (isinstance(s["http"], dict) and "url" in s["http"]):
            raise PlaybookError(f"{path}: {label} {i} 'http' needs a url")
        steps.append(Step(s["name"], s.get("run"), s.get("http"), float(s.get("timeout", 30))))
    return steps


def load(path: Path) -> Playbook:
    path = Path(path)
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise PlaybookError(f"{path}: not a mapping")
    for key in ("name", "match", "steps"):
        if key not in raw:
            raise PlaybookError(f"{path}: missing '{key}'")
    if not isinstance(raw["match"], dict) or "alertname" not in raw["match"]:
        raise PlaybookError(f"{path}: match must be a mapping that names at least an alertname")
    if not isinstance(raw["steps"], list) or not raw["steps"]:
        raise PlaybookError(f"{path}: steps must be a non-empty list")
    steps = _parse_steps(path, raw["steps"], "step")
    verify = None
    if raw.get("verify"):
        spec = dict(raw["verify"])
        checks = tuple(_parse_steps(path, spec.pop("checks", []) or [], "verify check"))
        try:
            verify = Verify(**spec, checks=checks)
        except TypeError as err:
            raise PlaybookError(f"{path}: bad verify section ({err})") from err
        if verify.url is None and not checks:
            raise PlaybookError(f"{path}: verify needs a url, checks, or both")
    objectives = raw.get("objectives") or {}
    unknown = set(objectives) - {"rto_seconds", "rpo_seconds"}
    if unknown:
        raise PlaybookError(f"{path}: unknown objectives {sorted(unknown)}")
    attempts = int(raw.get("max_attempts", 1))
    if not 1 <= attempts <= 5:
        raise PlaybookError(f"{path}: max_attempts must be between 1 and 5")
    match = {str(k): str(v) for k, v in raw["match"].items()}
    return Playbook(str(raw["name"]), path, match, steps, verify, attempts, objectives)


def load_dir(directory: Path) -> list[Playbook]:
    books = [load(p) for p in sorted(Path(directory).glob("*.y*ml"))]
    names = [b.name for b in books]
    if len(names) != len(set(names)):
        raise PlaybookError("playbook names must be unique")
    return books


def select(playbooks: list[Playbook], labels: dict) -> Playbook | None:
    """The most specific matching playbook (most match keys); None if nothing matches."""
    candidates = [b for b in playbooks if b.matches(labels)]
    return max(candidates, key=lambda b: len(b.match)) if candidates else None


def render(value: str, playbook: Playbook, labels: dict) -> str:
    def sub(m: re.Match) -> str:
        ref = m.group(1)
        if ref == "python":
            return sys.executable
        if ref == "playbook_dir":
            return str(playbook.path.parent)
        ns, _, name = ref.partition(".")
        if ns == "env" and name:
            if name not in os.environ:
                raise PlaybookError(f"environment variable {name} is not set")
            return os.environ[name]
        if ns == "label" and name:
            val = labels.get(name)
            if val is None or not SAFE_LABEL.match(val):
                raise PlaybookError(f"label {name!r} is missing or contains unsafe characters")
            return val
        raise PlaybookError(f"unknown placeholder {{{ref}}}")

    return PLACEHOLDER.sub(sub, value)


def _facts(output: str) -> dict:
    """A step may report facts (e.g. snapshot age) as a JSON object on its last output line."""
    lines = [ln for ln in output.strip().splitlines() if ln.strip()]
    if not lines:
        return {}
    try:
        parsed = json.loads(lines[-1])
    except ValueError:
        return {}
    return parsed.get("facts", {}) if isinstance(parsed, dict) and isinstance(parsed.get("facts"), dict) else {}


def run_step(step: Step, playbook: Playbook, labels: dict) -> tuple[StepResult, dict]:
    start = time.monotonic()
    try:
        if step.run:
            argv = [render(a, playbook, labels) for a in step.run]
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=step.timeout, cwd=playbook.path.parent, check=False)  # noqa: S603
            output = (proc.stdout + proc.stderr)[-OUTPUT_LIMIT:]
            ok = proc.returncode == 0
            detail = f"exit {proc.returncode}"
            last_error = next((ln.strip() for ln in reversed(proc.stderr.splitlines()) if ln.strip()), "")
            if not ok and last_error:
                detail += f": {last_error[:200]}"
            return StepResult(step.name, ok, round(time.monotonic() - start, 3), detail, output), _facts(proc.stdout)
        spec = step.http or {}
        url = render(spec["url"], playbook, labels)
        if not url.startswith(("http://", "https://")):
            raise PlaybookError(f"refusing non-HTTP url {url!r}")
        expect = int(spec.get("expect_status", 200))
        body = json.dumps(spec["body"]).encode() if "body" in spec else None
        headers = {"Content-Type": "application/json"}
        if spec.get("bearer_token_env"):
            token = os.environ.get(spec["bearer_token_env"])
            if not token:
                raise PlaybookError(f"environment variable {spec['bearer_token_env']} is not set")
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(url, data=body, method=spec.get("method", "GET"), headers=headers)  # noqa: S310
        status, text = _fetch(req, step.timeout)
        ok = status == expect
        return StepResult(step.name, ok, round(time.monotonic() - start, 3), f"HTTP {status} (expected {expect})", text[-OUTPUT_LIMIT:]), {}
    except subprocess.TimeoutExpired:
        return StepResult(step.name, False, round(time.monotonic() - start, 3), f"timed out after {step.timeout:g}s"), {}
    except (PlaybookError, OSError) as err:
        return StepResult(step.name, False, round(time.monotonic() - start, 3), f"error: {err}"), {}


def _fetch(req: urllib.request.Request, timeout: float) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310  (scheme checked by callers)
            return resp.status, resp.read(OUTPUT_LIMIT).decode(errors="replace")
    except urllib.error.HTTPError as err:
        return err.code, err.read(OUTPUT_LIMIT).decode(errors="replace")


def verify(playbook: Playbook, labels: dict, sleep=time.sleep) -> tuple[list[StepResult], dict]:
    """Health probes first, then each data check once, in order, stopping at the first failure.

    Returns every result (so the postmortem shows what ran) and the facts the checks reported.
    """
    v = playbook.verify
    if v is None:
        return [StepResult("Verify", True, 0.0, "no verification configured; steps succeeded")], {}
    results: list[StepResult] = []
    facts: dict = {}
    if v.url is not None:
        probes = _probe(playbook, v, labels, sleep)
        results.append(probes)
        if not probes.ok:
            return results, facts
    for check in v.checks:
        result, check_facts = run_step(check, playbook, labels)
        results.append(result)
        facts |= check_facts
        if not result.ok:
            break
    return results, facts


def _probe(playbook: Playbook, v: Verify, labels: dict, sleep) -> StepResult:
    """Recovered means N consecutive healthy probes before the deadline, not a single lucky one."""
    start = time.monotonic()
    try:
        url = render(v.url, playbook, labels)
    except PlaybookError as err:
        return StepResult("Verify", False, 0.0, f"error: {err}")
    if not url.startswith(("http://", "https://")):
        return StepResult("Verify", False, 0.0, f"error: refusing non-HTTP url {url!r}")
    streak = probes = 0
    last = "no probe ran"
    while time.monotonic() - start < v.timeout_seconds:
        probes += 1
        try:
            status, _ = _fetch(urllib.request.Request(url), min(5.0, v.interval_seconds + 2))  # noqa: S310
            last = f"HTTP {status}"
        except OSError as err:
            status, last = 0, f"unreachable ({err.__class__.__name__})"
        streak = streak + 1 if status == v.expect_status else 0
        if streak >= v.successes:
            return StepResult("Health probes", True, round(time.monotonic() - start, 3), f"{streak} consecutive healthy probes ({probes} total)")
        sleep(v.interval_seconds)
    return StepResult("Health probes", False, round(time.monotonic() - start, 3), f"not healthy after {v.timeout_seconds:g}s; last probe {last}")
