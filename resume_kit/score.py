"""Score a built resume against job postings with shortlist-ai.

shortlist-ai (https://github.com/vinayvobbili/shortlist-ai) reads the PDF the way a
screener would: it turns each posting into requirements, judges each one with quotes
checked against the resume, and lists the must-haves the resume doesn't show. Each gap
is checked against the guardrails, so a gap you can't honestly close is labeled as one.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from . import facts
from .build import build
from .content import ContentError, content_dir, resolve

CACHE = Path(os.environ.get("RESUME_KIT_CACHE", Path.home() / ".cache" / "resume-kit"))
MARK = {"met": "✅", "partial": "🟡", "not_met": "❌"}


class ScoreError(RuntimeError):
    pass


def find_shortlist() -> str:
    exe = os.environ.get("RESUME_KIT_SHORTLIST") or shutil.which("shortlist")
    if not exe:
        raise ScoreError("shortlist-ai not found: pip install shortlist-ai, or set RESUME_KIT_SHORTLIST "
                         "to its `shortlist` executable")
    return exe


def score(version: str, postings: list[Path] | None = None, backend: str = "local",
          content: Path | None = None) -> dict:
    content = content or content_dir()
    spec = resolve(version, content)
    postings = [Path(p).expanduser().resolve() for p in postings] if postings else []
    if not postings:
        if not spec.posting:
            raise ContentError(f"no posting for {version!r}: pass one, or set `posting:` in the version")
        postings = [spec.posting.resolve()]  # shortlist runs from the cache dir
    for p in postings:
        if not p.exists():
            raise ContentError(f"posting not found: {p}")

    CACHE.mkdir(parents=True, exist_ok=True)
    built = build(version, CACHE / "builds", content=content)
    # cwd=CACHE so shortlist's .shortlist-cache/ lands there and reruns reuse extractions.
    proc = subprocess.run([find_shortlist(), "jobs", str(built.pdf), *map(str, postings),
                           "--format", "json", "--backend", backend],
                          cwd=CACHE, capture_output=True, text=True, check=False)
    if proc.returncode:
        raise ScoreError(f"shortlist failed ({proc.returncode}):\n{proc.stderr.strip()[-2000:]}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise ScoreError(f"shortlist returned non-JSON output:\n{proc.stdout[:500]}") from None

    rails = facts.load(content)
    for m in data.get("matches", []):
        m["gap_notes"] = {g: [f"{r.id}: {r.why}" for r in rails.forbidden if r.find(g)] for g in m.get("gaps", [])}
    data["pdf"] = str(built.pdf)
    data["pages"] = built.pages
    return data


def to_text(data: dict) -> str:
    out = [f"Scored {data['pdf']} ({data['pages']} page(s))"]
    out += [f"⚠️  resume flag: {f}" for f in data.get("flags", [])]
    for m in data.get("matches", []):
        out += ["", f"{m['job']['title']}: {m['score']:.0f}/100, must-haves {m['must_haves_met']}/{m['must_haves_total']}",
                f"  {m['summary']}"]
        if m["gaps"]:
            out.append("  Gaps (must-haves not fully met):")
            for g in m["gaps"]:
                notes = m["gap_notes"].get(g)
                out.append(f"    - {g}" + (f"\n      real gap, don't add it; guardrail {'; '.join(notes)}" if notes else ""))
        out.append("  Requirements:")
        for r in m["requirements"]:
            head = f"    {MARK[r['verdict']]} {r['requirement_id']} ({r['kind'].replace('_', '-')})"
            if r["evidence_verified"]:
                out.append(head + (f" “{r['evidence'][0]}”" if r["evidence"] else ""))
            else:  # shortlist only says some quote failed, so show them all
                out.append(head + " ⚠️ a quote was not found in the resume")
                out += [f"        “{q}”" for q in r["evidence"]]
    for job, err in data.get("errors", {}).items():
        out.append(f"\n{job}: failed: {err}")
    return "\n".join(out) + "\n"
