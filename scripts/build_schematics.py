#!/usr/bin/env python3
"""Render every docs/schematics/*.mmd to SVG and regenerate each project's docs/schematics/README.md.

The .mmd files are the source of truth. Each starts with two comment lines:
    %% title: ...
    %% caption: ...
Optional arguments: project names to rebuild (default: all). Requires mermaid-cli (`mmdc`). Set MMDC_PUPPETEER_CONFIG to a puppeteer JSON config if the
default browser lookup fails (for example {"executablePath": "...", "args": ["--no-sandbox"]}).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = (
    Path(__file__).resolve().parent / "mermaid.config.json"
)  # plain SVG text, no foreignObject: renders in any viewer


def meta(text: str) -> tuple[str, str]:
    title = caption = ""
    for line in text.splitlines():
        if line.startswith("%% title:"):
            title = line.split(":", 1)[1].strip()
        elif line.startswith("%% caption:"):
            caption = line.split(":", 1)[1].strip()
    return title, caption


def render(src: Path, dst: Path) -> None:
    cmd = [
        "mmdc",
        "-i",
        str(src),
        "-o",
        str(dst),
        "-c",
        str(CONFIG),
        "-b",
        "white",
        "-q",
    ]
    cfg = os.environ.get("MMDC_PUPPETEER_CONFIG")
    if cfg:
        cmd += ["-p", cfg]
    subprocess.run(cmd, check=True, timeout=180)


def main() -> int:
    only_md = "--md-only" in sys.argv
    only = {a for a in sys.argv[1:] if not a.startswith("--")}  # optional: project names to rebuild
    for folder in sorted(ROOT.glob("projects/*/docs/schematics")):
        sources = sorted(folder.glob("*.mmd"))
        if not sources:
            continue
        project = folder.parent.parent.name
        if only and project not in only:
            continue
        lines = [
            f"# Schematics: {project}",
            "",
            "Diagrams are Mermaid, so GitHub renders them inline below. Each also has a rendered `.svg` next to its",
            "`.mmd` source. Edit the `.mmd` file, then run `python3 scripts/build_schematics.py` from the repository root.",
            "",
        ]
        for src in sources:
            title, caption = meta(src.read_text())
            if not only_md:
                render(src, src.with_suffix(".svg"))
            body = src.read_text().rstrip() + "\n"
            lines += [
                f"## {title}",
                "",
                caption,
                "",
                "```mermaid",
                body.rstrip(),
                "```",
                "",
                f"[SVG]({src.stem}.svg) · [source]({src.name})",
                "",
            ]
        (folder / "README.md").write_text("\n".join(lines))
        print(f"{project}: {len(sources)} diagram(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
