"""Render golden-path templates: new service repositories and Terraform environment requests."""

from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .models import ENV_NAMES, NAME_RE, OWNER_RE, TIER_DEFAULTS, ServiceSpec

TEMPLATES = Path(__file__).parent / "templates"
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class ScaffoldError(Exception):
    pass


def _env() -> Environment:
    # Custom delimiters so GitHub Actions `${{ }}` and HCL braces pass through untouched.
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        variable_start_string="[[",
        variable_end_string="]]",
        block_start_string="[%",
        block_end_string="%]",
        comment_start_string="[#",
        comment_end_string="#]",
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        autoescape=False,  # noqa: S701 - generating YAML/HCL/Python source, not HTML
    )


def render_service(spec: ServiceSpec, out_dir: Path, force: bool = False) -> list[Path]:
    """Create a new service repository from the golden-path templates."""
    if out_dir.exists() and any(out_dir.iterdir()) and not force:
        raise ScaffoldError(f"{out_dir} already exists and is not empty (use --force to overwrite)")
    env = _env()
    defaults = TIER_DEFAULTS[spec.tier]
    context = {
        "name": spec.name,
        "module": spec.name.replace("-", "_"),
        "owner": spec.owner,
        "tier": spec.tier,
        "port": spec.port,
        "replicas": spec.replicas,
        "registry": spec.registry.rstrip("/"),
        "slo_availability": spec.slo_availability,
        "environments": spec.environments,
        **{k: v for k, v in defaults.items() if k not in {"replicas", "slo_availability"}},
    }
    written = []
    service_root = TEMPLATES / "service"
    for template in sorted(service_root.rglob("*.j2")):
        rel = template.relative_to(TEMPLATES)
        target = out_dir / template.relative_to(service_root).with_suffix("")  # drop .j2
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(env.get_template(rel.as_posix()).render(**context))
        written.append(target)
    return written


def render_environment(service: str, environment: str, repo: str, owner: str, tier: str,
                       budget: int, out_dir: Path, force: bool = False) -> Path:  # fmt: skip
    """Render a Terraform module call that provisions one service/environment pair."""
    problems = []
    if not NAME_RE.match(service):
        problems.append(f"service {service!r} is not a valid name")
    if environment not in ENV_NAMES:
        problems.append(f"environment must be one of {sorted(ENV_NAMES)}")
    if not REPO_RE.match(repo):
        problems.append(f"repo {repo!r} must look like 'org/name'")
    if not OWNER_RE.match(owner):
        problems.append(f"owner {owner!r} must look like 'team-<name>'")
    if tier not in TIER_DEFAULTS:
        problems.append(f"tier must be one of {sorted(TIER_DEFAULTS)}")
    if budget < 1:
        problems.append("budget must be a positive number of USD")
    if problems:
        raise ScaffoldError("; ".join(problems))

    target = out_dir / f"{service}-{environment}.tf"
    if target.exists() and not force:
        raise ScaffoldError(f"{target} already exists (use --force to overwrite)")
    out_dir.mkdir(parents=True, exist_ok=True)
    context = {
        "service": service,
        "module_name": f"{service}_{environment}".replace("-", "_"),
        "environment": environment,
        "repo": repo,
        "owner": owner,
        "tier": tier,
        "budget": budget,
    }
    target.write_text(_env().get_template("env/service-environment.tf.j2").render(**context))
    return target
