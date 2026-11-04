"""Typst compile wrapper. Content is passed to templates as JSON, never as markup."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mappe.config import PROJECT_ROOT

TEMPLATES_DIR = PROJECT_ROOT / "typst"
FONTS_DIR = TEMPLATES_DIR / "fonts"  # Inter, Instrument Serif, JetBrains Mono (OFL)


@dataclass
class RenderResult:
    ok: bool
    pdf_path: Path | None = None
    error: str | None = None


def typst_available() -> bool:
    return shutil.which("typst") is not None


def render(
    template: str,
    data: dict[str, Any],
    out_pdf: Path,
    timeout: float = 60.0,
    app_fonts: bool = False,
) -> RenderResult:
    """Compile ``typst/<template>.typ`` with ``data`` available as ``data.json``.

    Templates read their input via ``json("data.json")``; this keeps all escaping
    concerns inside Typst. ``app_fonts`` adds the fonts of the Mappe UI (``typst/fonts``).
    """
    src = TEMPLATES_DIR / f"{template}.typ"
    if not src.exists():
        return RenderResult(ok=False, error=f"template not found: {src}")

    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        shutil.copytree(
            TEMPLATES_DIR, workdir, dirs_exist_ok=True, ignore=shutil.ignore_patterns("fonts")
        )
        (workdir / "data.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        fonts = ["--font-path", str(FONTS_DIR)] if app_fonts else []
        proc = subprocess.run(
            ["typst", "compile", *fonts, "--root", str(workdir), str(workdir / src.name)]
            + [str(out_pdf)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    if proc.returncode != 0:
        return RenderResult(ok=False, error=proc.stderr.strip())
    return RenderResult(ok=True, pdf_path=out_pdf)


def pdf_to_text(pdf: Path) -> str:
    """Extract text the way a simple ATS parser would (poppler's pdftotext)."""
    proc = subprocess.run(
        ["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True, check=True
    )
    return proc.stdout
