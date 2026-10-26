#!/usr/bin/env python3
"""Build LinkedIn-ready images and PDF carousels from the schematics.

For every project under projects/*/docs/schematics this writes, to assets/linkedin/<project>/:
  - one 1080x1350 PNG (rendered at 2x) per schematic, plus a cover and a closing card
  - <project>-carousel.pdf with all cards in order (LinkedIn "document" posts swipe like a carousel)

Metadata comes from comment lines at the top of each .mmd file:
    %% headline: the card title
    %% takeaway: one sentence under the title
    %% legend: class=Label,class=Label   (classes are the colour roles used in the diagram)
Run scripts/build_schematics.py first so the .svg files are current. Requires Playwright with Chromium and
the Inter font installed on the machine (falls back to a generic sans-serif).
"""

from __future__ import annotations

import base64
import html
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "linkedin"
REPO_URL = "github.com/Joxejaime/projects-2026"
AUTHOR = "Jaime Castillo Araujo"
W, H = 1080, 1350
PANEL_W, PANEL_H = 920, 820  # drawable area for the diagram inside the white panel
MAX_UPSCALE = 1.25

# Colour roles, shared with the .mmd files (fill, stroke).
ROLES = {
    "entry": ("#E0E7FF", "#4F46E5"),
    "app": ("#DBEAFE", "#2563EB"),
    "guard": ("#CCFBF1", "#0D9488"),
    "data": ("#FEF3C7", "#D97706"),
    "obs": ("#EDE9FE", "#7C3AED"),
    "alert": ("#FFE4E6", "#E11D48"),
    "ok": ("#DCFCE7", "#16A34A"),
    "cloud": ("#FFEDD5", "#EA580C"),
    "neutral": ("#F1F5F9", "#64748B"),
}

# Cover and closing copy. Every figure here comes from a measured run or a test count documented in the project.
PROJECTS = {
    "ai-reliability-platform": {
        "name": "AI reliability platform",
        "tagline": "A gateway that keeps answering when the AI provider goes down.",
        "facts": [
            (
                "ok",
                "180 of 180 requests succeeded while the primary provider was down.",
            ),
            (
                "data",
                "Median latency rose from about 140 ms to about 290 ms on the fallback.",
            ),
            (
                "app",
                "The circuit breaker opened, then closed by itself once the provider recovered.",
            ),
        ],
        "verified": [
            "40 unit and end-to-end tests",
            "A live outage drill with recorded results",
            "Alert rules, dashboard and Kubernetes manifests checked",
        ],
        "unverified": [
            "Docker image build",
            "Terraform validate and apply",
            "Prometheus firing the alerts live",
        ],
    },
    "self-service-platform": {
        "name": "Self-service platform",
        "tagline": "One command to a service that already follows the rules.",
        "facts": [
            (
                "ok",
                "A generated service passes its own policy check with 0 errors and 0 warnings.",
            ),
            (
                "alert",
                "A deliberately broken example fails with 14 errors and 3 warnings, each with a rule ID.",
            ),
            ("cloud", "Three reliability tiers decide replicas, resources and SLO."),
        ],
        "verified": [
            "29 tests, including generating and validating each tier",
            "Policy output recorded for good and bad examples",
            "Service catalog built from real spec files",
        ],
        "unverified": [
            "Terraform validate and apply",
            "The CI workflows on GitHub",
            "A real AWS account",
        ],
    },
    "sre-reliability-lab": {
        "name": "SRE reliability lab",
        "tagline": "Reliability stated as numbers, then tested by breaking things.",
        "facts": [
            (
                "data",
                "A 5% error incident for 30 minutes pages after 18 minutes and spends 3.47% of the monthly budget.",
            ),
            (
                "alert",
                "A latency fault caused zero errors, so an availability-only alert would have stayed silent.",
            ),
            (
                "guard",
                "Two game days run, each with a control route and a check against the service's own metrics.",
            ),
        ],
        "verified": [
            "33 tests, including live chaos experiments",
            "Alert rules regenerate identically from the SLO file",
            "Two recorded game-day reports",
        ],
        "unverified": [
            "Prometheus evaluating the rules",
            "Alerts firing in Alertmanager",
            "Docker Compose stack",
        ],
    },
}

CSS = f"""
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{ background: #0B1B3A; }}
body {{ font-family: 'Inter', 'Helvetica Neue', Arial, sans-serif; color: #F8FAFC; -webkit-font-smoothing: antialiased; }}
.slide {{ width: {W}px; height: {H}px; background: #0B1B3A; padding: 58px 60px 40px; display: flex; flex-direction: column;
  page-break-after: always; break-after: page; overflow: hidden; position: relative; }}
.slide:last-child {{ page-break-after: auto; break-after: auto; }}
h1 {{ font-family: 'Inter Display', 'Inter', sans-serif; font-weight: 800; font-size: 58px; line-height: 1.07; letter-spacing: -0.025em; max-width: 940px; }}
.takeaway {{ margin-top: 20px; font-size: 28px; line-height: 1.38; color: #B7C5E3; max-width: 900px; font-weight: 400; }}
.head {{ height: 248px; flex: none; }}
.stage {{ flex: 1; display: flex; flex-direction: column; justify-content: center; }}
.strip {{ position: absolute; top: 0; left: 0; right: 0; height: 16px; display: flex; }}
.strip i {{ flex: 1; }}
.panel {{ flex: none; border-radius: 28px; background-color: #FFFFFF;
  background-image: linear-gradient(#EDF1F7 1px, transparent 1px), linear-gradient(90deg, #EDF1F7 1px, transparent 1px);
  background-size: 36px 36px; display: flex; align-items: center; justify-content: center; }}
.panel img {{ display: block; }}
.legend {{ margin-top: 22px; display: flex; flex-wrap: wrap; gap: 10px 20px; font-size: 19px; color: #D5DEF2; line-height: 1.2; }}
.legend span {{ display: inline-flex; align-items: center; gap: 9px; }}
.legend i {{ width: 22px; height: 22px; border-radius: 6px; border: 2.5px solid; display: inline-block; }}
.foot {{ margin-top: auto; display: flex; justify-content: space-between; align-items: baseline; font-size: 21px; color: #8EA0C6; }}
.foot b {{ color: #F8FAFC; font-weight: 600; }}
/* cover */
.cover h1 {{ font-size: 108px; line-height: 1.0; max-width: 960px; margin-top: 120px; }}
.cover .tag {{ margin-top: 34px; font-size: 38px; line-height: 1.3; color: #C9D5EE; max-width: 880px; }}
.facts {{ margin-top: 84px; display: flex; flex-direction: column; gap: 34px; }}
.fact {{ display: flex; gap: 26px; align-items: stretch; font-size: 31px; line-height: 1.32; color: #EAF0FC; max-width: 960px; }}
.fact .bar {{ width: 10px; border-radius: 5px; flex: none; }}
.cover .by {{ margin-top: auto; font-size: 26px; color: #B7C5E3; }}
.cover .by b {{ color: #FFFFFF; }}
/* closing */
.close h1 {{ font-size: 76px; margin-top: 110px; }}
.cols {{ margin-top: 70px; display: grid; grid-template-columns: 1fr 1fr; gap: 44px; }}
.col h2 {{ font-size: 34px; font-weight: 700; margin-bottom: 30px; }}
.col ul {{ list-style: none; display: flex; flex-direction: column; gap: 26px; }}
.col li {{ font-size: 30px; line-height: 1.3; color: #DCE5F6; padding-left: 26px; position: relative; }}
.col li::before {{ content: ''; position: absolute; left: 0; top: 13px; width: 13px; height: 13px; border-radius: 3px; background: var(--c); }}
.close .repo {{ margin-top: auto; font-size: 34px; font-weight: 700; color: #FFFFFF; }}
.close .repo small {{ display: block; margin-top: 10px; font-size: 24px; font-weight: 400; color: #B7C5E3; }}
"""


def meta(text: str, key: str) -> str:
    m = re.search(rf"^%% {key}: (.*)$", text, re.MULTILINE)
    return m.group(1).strip() if m else ""


def strip_html() -> str:
    return (
        '<div class="strip">'
        + "".join(
            f'<i style="background:{stroke}"></i>' for _, stroke in ROLES.values()
        )
        + "</div>"
    )


def svg_img(svg_path: Path) -> tuple[str, float]:
    svg = svg_path.read_text()
    m = re.search(r'viewBox="([\d.\- ]+)"', svg)
    _, _, w, h = (float(v) for v in m.group(1).split())
    scale = min(PANEL_W / w, PANEL_H / h, MAX_UPSCALE)
    # give the root element explicit pixel size so the <img> renders at the intended scale
    svg = re.sub(
        r"<svg\b[^>]*>",
        lambda t: re.sub(r'\s(width|height|style)="[^"]*"', "", t.group(0)).replace(
            "<svg", f'<svg width="{w * scale:.0f}" height="{h * scale:.0f}"', 1
        ),
        svg,
        count=1,
    )
    data = base64.b64encode(svg.encode()).decode()
    return (
        f'<img alt="" width="{w * scale:.0f}" height="{h * scale:.0f}" src="data:image/svg+xml;base64,{data}">',
        h * scale,
    )


def legend_html(spec: str) -> str:
    chips = []
    for part in spec.split(","):
        role, _, label = part.partition("=")
        fill, stroke = ROLES[role.strip()]
        chips.append(
            f'<span><i style="background:{fill};border-color:{stroke}"></i>{html.escape(label.strip())}</span>'
        )
    return '<div class="legend">' + "".join(chips) + "</div>"


def diagram_slide(project: str, idx: int, total: int, mmd: Path) -> str:
    text = mmd.read_text()
    img, img_h = svg_img(mmd.with_suffix(".svg"))
    panel_h = min(PANEL_H + 40, max(560, round(img_h) + 90))
    return f"""
<section class="slide">{strip_html()}
  <div class="head"><h1>{html.escape(meta(text, "headline"))}</h1><p class="takeaway">{html.escape(meta(text, "takeaway"))}</p></div>
  <div class="stage"><div class="panel" style="height:{panel_h}px">{img}</div>
  {legend_html(meta(text, "legend"))}</div>
  <div class="foot"><span><b>{html.escape(project)}</b>, schematic {idx} of {total}</span><span>{REPO_URL}</span></div>
</section>"""


def cover_slide(project: str, total: int) -> str:
    p = PROJECTS[project]
    facts = "".join(
        f'<div class="fact"><div class="bar" style="background:{ROLES[r][1]}"></div><div>{html.escape(t)}</div></div>'
        for r, t in p["facts"]
    )
    return f"""
<section class="slide cover">{strip_html()}
  <h1>{html.escape(p["name"])}</h1>
  <p class="tag">{html.escape(p["tagline"])}</p>
  <div class="facts">{facts}</div>
  <div class="by"><b>{AUTHOR}</b><br>{total} schematics follow. Code: {REPO_URL}</div>
</section>"""


def closing_slide(project: str) -> str:
    p = PROJECTS[project]
    ok = "".join(f"<li>{html.escape(t)}</li>" for t in p["verified"])
    no = "".join(f"<li>{html.escape(t)}</li>" for t in p["unverified"])
    return f"""
<section class="slide close">{strip_html()}
  <h1>What I ran, and what I did not</h1>
  <div class="cols">
    <div class="col" style="--c:{ROLES["ok"][1]}"><h2>Run and passing</h2><ul>{ok}</ul></div>
    <div class="col" style="--c:{ROLES["data"][1]}"><h2>Written, not yet run</h2><ul>{no}</ul></div>
  </div>
  <div class="repo">{REPO_URL}<small>projects/{project}, with tests, runbooks and these schematics</small></div>
</section>"""


def page(body: str) -> str:
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{body}</body></html>"


def main() -> int:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for folder in sorted(ROOT.glob("projects/*/docs/schematics")):
            project = folder.parent.parent.name
            if only and project != only:
                continue
            sources = sorted(folder.glob("*.mmd"))
            out = OUT / project
            out.mkdir(parents=True, exist_ok=True)
            slides = [("00-cover", cover_slide(project, len(sources)))]
            slides += [
                (mmd.stem, diagram_slide(project, i, len(sources), mmd))
                for i, mmd in enumerate(sources, 1)
            ]
            slides.append(("99-closing", closing_slide(project)))

            ctx = browser.new_context(
                viewport={"width": W, "height": H}, device_scale_factor=2
            )
            pg = ctx.new_page()
            for name, body in slides:
                pg.set_content(page(body))
                pg.evaluate("document.fonts.ready")
                pg.screenshot(path=str(out / f"{name}.png"))
            pg.set_content(page("".join(b for _, b in slides)))
            pg.evaluate("document.fonts.ready")
            pg.pdf(
                path=str(out / f"{project}-carousel.pdf"),
                width=f"{W}px",
                height=f"{H}px",
                print_background=True,
            )
            ctx.close()
            print(
                f"{project}: {len(slides)} cards + carousel PDF -> {out.relative_to(ROOT)}"
            )
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
