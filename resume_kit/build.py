"""Render a version to .docx and .pdf, then check it hits its page target."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import facts
from .content import REPO, Spec, content_dir, resolve

RENDER_JS = Path(__file__).with_name("render.js")
DEFAULT_OUT = Path(os.environ.get("RESUME_KIT_OUT", Path.home() / "Downloads"))
# Page images are for looking at a build, not keeping, so they stay out of the output folder.
PREVIEWS = Path(os.environ.get("RESUME_KIT_CACHE", Path.home() / ".cache" / "resume-kit")) / "previews"


class BuildError(RuntimeError):
    pass


@dataclass
class BuildResult:
    version: str
    docx: Path
    pdf: Path
    pages: int
    target: int
    overflow: str  # text past the last allowed page, if any

    @property
    def ok(self) -> bool:
        return self.pages == self.target

    def summary(self) -> str:
        line = f"{self.version}: {self.pages} page(s) -> {self.pdf}"
        if self.pages > self.target:
            line += f"\n  spills onto page {self.target + 1}:\n    " + self.overflow.strip().replace("\n", "\n    ")
        elif self.pages < self.target:
            line += f"\n  under {self.target} page(s); room to add content"
        return line


def _need(tool: str, hint: str) -> str:
    path = shutil.which(tool)
    if not path:
        raise BuildError(f"{tool} not found; {hint}")
    return path


def ensure_node_deps() -> None:
    if not (REPO / "node_modules" / "docx").is_dir():
        npm = _need("npm", "install Node.js")
        subprocess.run([npm, "install", "--silent"], cwd=REPO, check=True)


def render_docx(spec: Spec, out: Path) -> None:
    ensure_node_deps()
    node = _need("node", "install Node.js")
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(spec.to_render_json(), f, ensure_ascii=False)
    try:
        subprocess.run([node, str(RENDER_JS), f.name, str(out)], check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        raise BuildError(f"render.js failed:\n{e.stderr}") from None
    finally:
        os.unlink(f.name)


def to_pdf(docx: Path) -> Path:
    soffice = _need("soffice", "brew install --cask libreoffice")
    subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(docx.parent), str(docx)],
                   check=True, capture_output=True)
    return docx.with_suffix(".pdf")


def page_count(pdf: Path) -> int:
    out = subprocess.run([_need("pdfinfo", "brew install poppler"), str(pdf)],
                         check=True, capture_output=True, text=True).stdout
    return int(re.search(r"^Pages:\s+(\d+)", out, re.MULTILINE).group(1))


def page_text(pdf: Path, first: int, last: int | None = None) -> str:
    return subprocess.run([_need("pdftotext", "brew install poppler"), "-layout", "-f", str(first),
                           "-l", str(last or first), str(pdf), "-"], check=True, capture_output=True, text=True).stdout


def build(version: str, out_dir: Path = DEFAULT_OUT, enforce_facts: bool = True,
          content: Path | None = None) -> BuildResult:
    content = content or content_dir()
    spec = resolve(version, content)
    if enforce_facts and (problems := facts.check(spec, content)):
        raise BuildError(f"{version} fails fact checks:\n  " + "\n  ".join(problems))
    out_dir.mkdir(parents=True, exist_ok=True)
    docx = out_dir / f"{spec.output}.docx"
    render_docx(spec, docx)
    pdf = to_pdf(docx)
    pages = page_count(pdf)
    overflow = page_text(pdf, spec.pages + 1, pages) if pages > spec.pages else ""
    return BuildResult(version, docx, pdf, pages, spec.pages, overflow)


def preview(pdf: Path, out_dir: Path | None = None, dpi: int = 80) -> list[Path]:
    """Render each page to JPEG (in the preview cache by default); returns the image paths."""
    out_dir = out_dir or PREVIEWS
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob(f"{pdf.stem}-*.jpg"):  # a longer earlier build would leave extra pages
        old.unlink()
    prefix = out_dir / pdf.stem
    subprocess.run([_need("pdftoppm", "brew install poppler"), "-jpeg", "-r", str(dpi), str(pdf), str(prefix)],
                   check=True)
    return sorted(out_dir.glob(f"{pdf.stem}-*.jpg"))
