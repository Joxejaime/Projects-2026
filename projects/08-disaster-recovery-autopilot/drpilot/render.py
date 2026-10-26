"""Render an incident as a postmortem draft in Markdown.

Everything the responder observed (times, steps, verification, facts reported by restore scripts,
objective checks) is filled in. Everything it cannot know (root cause, contributing factors, owners)
is left as an explicit TODO for a human: an automated postmortem that guesses a root cause is worse
than none.
"""

from __future__ import annotations

from datetime import datetime

from .model import Incident, iso, parse_time

TODO = "**TODO (human):**"
RECOVERY_LABELS = {"succeeded": "succeeded (verified)", "failed": "failed, escalated", "no_playbook": "none: no playbook matched"}


def duration(seconds: float | None) -> str:
    if seconds is None:
        return "n/a"
    if seconds < 60:
        return f"{max(0.0, seconds):.1f}s"
    seconds = round(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    return f"{minutes}m {secs:02d}s"


def _between(start: str | None, end: str | None) -> float | None:
    a, b = parse_time(start), parse_time(end)
    return (b - a).total_seconds() if a and b else None


def cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def key_times(incident: Incident) -> dict[str, float | None]:
    """Restored means verified by automation, or else the alert resolving (a human fixed it)."""
    return {
        "detect": _between(incident.impact_started_at, incident.detected_at),
        "mitigate": _between(incident.detected_at, incident.mitigated_at),
        "recover": _between(incident.impact_started_at, incident.mitigated_at or incident.resolved_at),
        "impact": _between(incident.impact_started_at, incident.resolved_at),
    }


def objective_checks(incident: Incident) -> list[tuple[str, str, str, str]]:
    """(objective, target, observed, verdict) rows for the RTO/RPO declared in the playbook."""
    rows = []
    obj = incident.objectives
    if "rto_seconds" in obj:
        observed = key_times(incident)["recover"]
        met = observed is not None and observed <= obj["rto_seconds"]
        rows.append(("RTO (impact start to service restored)", duration(obj["rto_seconds"]), duration(observed), "met" if met else "MISSED"))
    if "rpo_seconds" in obj:
        age = incident.facts.get("snapshot_age_seconds")
        met = age is not None and float(age) <= obj["rpo_seconds"]
        observed = duration(float(age)) if age is not None else "unknown (no restore reported it)"
        rows.append(("RPO (age of the data restored)", duration(obj["rpo_seconds"]), observed, "met" if met else "MISSED"))
    return rows


def suggested_actions(incident: Incident) -> list[tuple[str, str]]:
    """Follow-ups implied by what was observed. Suggestions only: a human decides and assigns owners."""
    actions = []
    times = key_times(incident)
    if incident.recovery_state == "no_playbook":
        actions.append((f"Write and drill a recovery playbook for `{incident.labels.get('alertname')}`", "mitigate"))
    if incident.recovery_state == "failed":
        last = next((s for a in reversed(incident.attempts) for s in reversed(a.steps) if not s.ok), None)
        where = f" (last failure: {last.name}, {last.detail})" if last else ""
        actions.append(
            (f"Automation '{incident.playbook}' failed{where}: fix what it hit (playbook, or the system it depends on) and re-run the drill", "mitigate")
        )
    if times["detect"] is not None and times["detect"] > 300:
        actions.append((f"Detection took {duration(times['detect'])}; review the alert's `for:` duration and windows", "detect"))
    for name, target, observed, verdict in objective_checks(incident):
        if verdict == "MISSED":
            if name.startswith("RPO"):
                fix = (
                    "no verified restore happened, so test that backups restore on a schedule"
                    if observed.startswith("unknown")
                    else "take snapshots more often"
                )
            else:
                fix = "shorten the restore path"
            actions.append((f"{name.split(' ')[0]} missed ({observed} vs {target}): {fix}", "prevent" if name.startswith("RPO") else "mitigate"))
    if not incident.annotations.get("runbook_url"):
        actions.append(("Link a runbook from the alert's `runbook_url` annotation", "mitigate"))
    actions.append(("Find and fix what caused the failure in the first place", "prevent"))
    return actions


def render_postmortem(incident: Incident, generated_at: datetime) -> str:
    times = key_times(incident)
    automated = {
        "succeeded": f"service was recovered automatically by playbook `{incident.playbook}`",
        "failed": f"playbook `{incident.playbook}` could not recover the service, so a human was paged",
        "no_playbook": "no recovery playbook matched, so a human was paged",
    }.get(incident.recovery_state, "recovery state unknown")
    out = [
        f"# Postmortem: {incident.title}",
        "",
        f"> **Status: DRAFT, generated automatically** by drpilot on {iso(generated_at)}. Facts below come from",
        "> the alert, the responder's timeline and the recovery steps. Sections marked TODO need a human, and",
        "> the draft is not finished until they are filled in and the document is reviewed.",
        "",
        "| | |",
        "|---|---|",
        f"| Incident | `{incident.id}` |",
        f"| Service | {cell(incident.service)} |",
        f"| Severity | {cell(incident.severity)} |",
        f"| Alert | `{cell(incident.labels.get('alertname', ''))}` |",
        f"| Impact | {incident.impact_started_at} to {incident.resolved_at} ({duration(times['impact'])}) |",
        f"| Automated recovery | {RECOVERY_LABELS.get(incident.recovery_state, incident.recovery_state)} |",
        "",
        "## Summary",
        "",
        f"`{incident.labels.get('alertname')}` fired for **{incident.service}** at {incident.detected_at}. Outcome: "
        f"{automated}. Impact lasted {duration(times['impact'])}.",
    ]
    if incident.annotations.get("description"):
        out += ["", f"Alert description: {incident.annotations['description']}"]
    out += [
        "",
        f"{TODO} one or two sentences a non-engineer could follow: who was affected and how.",
        "",
        "## Key times",
        "",
        "| Measure | Value |",
        "|---|---|",
        f"| Time to detect (impact start to alert) | {duration(times['detect'])} |",
        f"| Time to mitigate (alert to verified recovery) | {duration(times['mitigate'])} |",
        f"| Time to recover (impact start to service restored) | {duration(times['recover'])} |",
        f"| Total impact (impact start to alert resolved) | {duration(times['impact'])} |",
    ]
    if incident.recovery_state == "succeeded":
        out += ["", "Automated recovery counts only once consecutive health probes pass, so it can finish slightly after the alert resolved."]
    checks = objective_checks(incident)
    if checks:
        out += ["", "## Recovery objectives", "", "| Objective | Target | Observed | Result |", "|---|---|---|---|"]
        out += [f"| {cell(a)} | {cell(b)} | {cell(c)} | **{d}** |" for a, b, c, d in checks]
    if incident.facts:
        out += ["", "## Facts reported by recovery steps", "", "| Fact | Value |", "|---|---|"]
        out += [f"| `{cell(k)}` | {cell(v)} |" for k, v in sorted(incident.facts.items())]
    out += ["", "## Timeline (UTC)", "", "| Time | Kind | Event |", "|---|---|---|"]
    out += [f"| {e.at} | {e.kind} | {cell(e.message)} |" for e in sorted(incident.events, key=lambda e: e.at)]
    out += ["", "## Automated recovery", ""]
    if not incident.attempts:
        out += ["No recovery was attempted." if incident.recovery_state == "no_playbook" else "No attempt was recorded."]
    for attempt in incident.attempts:
        out += [
            f"### Attempt {attempt.number}: {'verified recovery' if attempt.verified else 'did not recover'}",
            "",
            "| Step | Result | Took | Detail |",
            "|---|---|---|---|",
        ]
        out += [f"| {cell(s.name)} | {'ok' if s.ok else 'FAILED'} | {s.seconds:.2f}s | {cell(s.detail)} |" for s in attempt.steps]
        outputs = [s for s in attempt.steps if s.output.strip()]
        if outputs:
            out += ["", "<details><summary>Step output</summary>", ""]
            for s in outputs:
                out += [f"**{s.name}**", "", "```", s.output.strip().replace("```", "'''"), "```", ""]
            out += ["</details>"]
        out += [""]
    out += ["## Alert details", "", "| Label | Value |", "|---|---|"]
    out += [f"| `{cell(k)}` | {cell(v)} |" for k, v in sorted(incident.labels.items())]
    if incident.annotations.get("runbook_url"):
        out += ["", f"Runbook: {incident.annotations['runbook_url']}"]
    out += [
        "",
        "## Root cause and contributing factors",
        "",
        f"{TODO} the automation knows the symptom and what restored service, not why it broke. Describe systems",
        "and decisions, not people, and keep asking why until you reach something that can be fixed.",
        "",
        "## What went well / what went poorly / where we got lucky",
        "",
    ]
    if incident.recovery_state == "succeeded":
        out += [f"- Went well: automation restored service {duration(times['mitigate'])} after the alert, verified by health probes."]
    elif incident.recovery_state == "failed":
        out += ["- Went poorly: the recovery playbook ran but service was not verified healthy afterwards."]
    else:
        out += ["- Went poorly: there was no automated recovery for this alert."]
    out += [f"- {TODO} add what the timeline cannot show.", "", "## Action items", "", "| Action | Type | Owner | Due |", "|---|---|---|---|"]
    out += [f"| {cell(a)} | {t} | TODO | TODO |" for a, t in suggested_actions(incident)]
    if incident.published_url:
        out += ["", f"Review thread: {incident.published_url}"]
    return "\n".join(out) + "\n"
