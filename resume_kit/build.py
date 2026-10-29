"""Render a version to .docx and .pdf, then check it hits its page target."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import facts
from .content import REPO, Spec, content_dir, resolve

RENDER_JS = Path(__file__).with_name("render.js")
DEFAULT_OUT = Path(os.environ.get("RESUME_KIT_OUT", Path.home() / "Downloads"))
# Page images are for looking at a build, not keeping, so they stay out of the output folder.
PREVIEWS = Path(os.environ.get("RESUME_KIT_CACHE", Path.home() / ".cache" / "resume-kit")) / "previews"


MARGIN_PT = 36  # render.js margins: 720 twips on every side
FULL = 0.9  # a last page filled less than this ends in blank space that reads as unfinished


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
    fill: float = 1.0  # how far down its usable height the last page's text reaches
    copies: list[Path] = field(default_factory=list)  # where copy_to put the PDF too

    @property
    def ok(self) -> bool:
        return self.pages == self.target

    def summary(self) -> str:
        line = f"{self.version}: {self.pages} page(s) -> {self.pdf}"
        line += "".join(f"\n  copied to {c}" for c in self.copies)
        if self.pages > self.target:
            line += f"\n  spills onto page {self.target + 1}:\n    " + self.overflow.strip().replace("\n", "\n    ")
        elif self.pages < self.target:
            line += f"\n  under {self.target} page(s); room to add content"
        elif self.fill < FULL:
            line += f"\n  page {self.pages} is {self.fill:.0%} full; add content so it doesn't end in blank space"
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


def fill(bbox_xml: str) -> float:
    """How far down the usable height (inside the margins) a page's text reaches, from `pdftotext -bbox-layout`."""
    height = float(re.search(r'<page width="[\d.]+" height="([\d.]+)"', bbox_xml).group(1))
    bottoms = [float(y) for y in re.findall(r'<block [^>]*yMax="([\d.]+)"', bbox_xml)]
    return (max(bottoms) - MARGIN_PT) / (height - 2 * MARGIN_PT) if bottoms else 0.0


def last_page_fill(pdf: Path, page: int) -> float:
    return fill(subprocess.run([_need("pdftotext", "brew install poppler"), "-bbox-layout", "-f", str(page),
                                "-l", str(page), str(pdf), "-"], check=True, capture_output=True, text=True).stdout)


def build(version: str, out_dir: Path = DEFAULT_OUT, enforce_facts: bool = True,
          content: Path | None = None, as_sent: bool = False) -> BuildResult:
    """Render a version. A build is a copy to send, so a version already applied with is held to every
    guardrail, the ones added since it was sent too (see facts.check); `as_sent` re-renders it as it was sent,
    without those."""
    content = content or content_dir()
    spec = resolve(version, content)
    if enforce_facts and (problems := facts.check(spec, content, reuse=not as_sent)):
        applied = spec.meta.get("applied")
        why = (f"\n{version} was sent on {applied}, before these rules: a copy to send again must pass them. "
               "Fix it (and set applied: to the new day), draft a new version, or re-render it as it was sent "
               "(--as-sent)." if applied and not as_sent and not facts.check(spec, content) else "")
        raise BuildError(f"{version} fails fact checks:\n  " + "\n  ".join(problems) + why)
    out_dir.mkdir(parents=True, exist_ok=True)
    docx = out_dir / f"{spec.output}.docx"
    render_docx(spec, docx)
    pdf = to_pdf(docx)
    pages = page_count(pdf)
    overflow = page_text(pdf, spec.pages + 1, pages) if pages > spec.pages else ""
    copies = []
    for folder in spec.meta.get("copy_to", []):
        dest = Path(folder).expanduser()
        dest.mkdir(parents=True, exist_ok=True)
        copies.append(Path(shutil.copy2(pdf, dest / pdf.name)))
    return BuildResult(version, docx, pdf, pages, spec.pages, overflow, last_page_fill(pdf, pages), copies)


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
