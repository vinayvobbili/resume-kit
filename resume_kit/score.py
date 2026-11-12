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

import yaml

from . import facts
from .build import build
from .content import ContentError, content_dir, resolve

CACHE = Path(os.environ.get("RESUME_KIT_CACHE", Path.home() / ".cache" / "resume-kit"))
MARK = {"met": "✅", "partial": "🟡", "not_met": "❌"}
# Free scorers only, never shortlist-ai's paid `claude` (Anthropic API) backend: agy runs on the Antigravity
# subscription's quota, local is the shared on-device server. An entry is `backend` or `backend:model`.
BACKENDS = ("agy", "local")
DEFAULT_CHAIN = ("agy:claude-sonnet-5-5-high", "agy:gemini-4-hydrogen-medium", "agy:gemini-4-argon-high", "local")


class ScoreError(RuntimeError):
    pass


# [local] adds the on-device MLX backend, which is the default.
SHORTLIST_PIP = "shortlist-ai[local]"


def find_shortlist() -> str:
    exe = os.environ.get("RESUME_KIT_SHORTLIST") or shutil.which("shortlist")
    if not exe:
        raise ScoreError(f"shortlist-ai not found: pip install '{SHORTLIST_PIP}', or set "
                         "RESUME_KIT_SHORTLIST to its `shortlist` executable")
    return exe


def configured_chain(content: Path) -> list[str]:
    """The scoring chain from the content directory's jobwatch.yaml `scoring:` block (backend, model, fallback),
    else DEFAULT_CHAIN."""
    try:
        block = (yaml.safe_load((content / "jobwatch.yaml").read_text()) or {}).get("scoring") or {}
    except (OSError, yaml.YAMLError, AttributeError):
        block = {}
    first = block.get("backend")
    if not first:
        return list(DEFAULT_CHAIN)
    if block.get("model") and ":" not in first:
        first = f"{first}:{block['model']}"
    return [first, *map(str, block.get("fallback") or [])]


def _split(entry: str) -> tuple[str, str | None]:
    name, _, model = entry.partition(":")
    return name, model or None


def _shortlist(backend: str, pdf: Path, postings: list[Path]) -> dict:
    name, model = _split(backend)
    # cwd=CACHE so shortlist's .shortlist-cache/ lands there and reruns reuse extractions.
    proc = subprocess.run([find_shortlist(), "jobs", str(pdf), *map(str, postings), "--format", "json",
                           "--backend", name, *(["--model", model] if model else [])],
                          cwd=CACHE, capture_output=True, text=True, check=False)
    if proc.returncode:
        # With --format json shortlist can put its error on stdout and leave stderr empty: show whichever says why
        why = proc.stderr.strip() or proc.stdout.strip() or "(it said nothing)"
        raise ScoreError(f"shortlist failed ({proc.returncode}):\n{why[-2000:]}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise ScoreError(f"shortlist returned non-JSON output:\n{proc.stdout[:500]}") from None


def score(version: str, postings: list[Path] | None = None, backend: str | None = None,
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

    backends = [b.strip() for b in backend.split(",") if b.strip()] if backend else configured_chain(content)
    if not backends or any(_split(b)[0] not in BACKENDS for b in backends):
        raise ScoreError(f"backend must be one of {', '.join(BACKENDS)} (agy:<model> picks a model), or several in "
                         f"the order to try (agy,local); the paid claude backend is never used. Got {backend!r}")
    CACHE.mkdir(parents=True, exist_ok=True)
    built = build(version, CACHE / "builds", content=content)
    failed: dict[str, str] = {}
    for b in backends:  # in order: one that fails (no key, out of quota) hands the job to the next
        try:
            data = _shortlist(b, built.pdf, postings)
            break
        except ScoreError as e:
            failed[b] = str(e)
    else:
        raise ScoreError("\n".join(f"{b}: {why}" for b, why in failed.items()))
    data["backend"], data["failed_backends"] = b, failed

    rails = facts.load(content)
    for m in data.get("matches", []):
        m["gap_notes"] = {g: [f"{r.id}: {r.why}" for r in rails.forbidden if r.find(g)] for g in m.get("gaps", [])}
    data["pdf"] = str(built.pdf)
    data["pages"] = built.pages
    return data


def _why(why: str) -> str:
    """A failure on one line: its first ("shortlist failed (1):") and its last, where the reason is."""
    lines = [line.strip() for line in why.splitlines() if line.strip()] or ["(no reason given)"]
    return lines[0] if len(lines) == 1 else f"{lines[0]} {lines[-1]}"


def to_text(data: dict, brief: bool = False) -> str:
    """brief: only the score, the gaps, and the requirements not fully met (what's left to fix)."""
    by = f" with {data['backend']}" if data.get("backend") else ""
    out = [f"Scored {data['pdf']} ({data['pages']} page(s)){by}"]
    out += [f"⚠️  {b} failed, so it fell back: {_why(why)}" for b, why in data.get("failed_backends", {}).items()]
    out += [f"⚠️  resume flag: {f}" for f in data.get("flags", [])]
    for m in data.get("matches", []):
        out += ["", f"{m['job']['title']}: {m['score']:.0f}/100, must-haves {m['must_haves_met']}/{m['must_haves_total']}",
                f"  {m['summary']}"]
        if m["gaps"]:
            out.append("  Gaps (must-haves not fully met):")
            for g in m["gaps"]:
                notes = m["gap_notes"].get(g)
                out.append(f"    - {g}" + (f"\n      real gap, don't add it; guardrail {'; '.join(notes)}" if notes else ""))
        reqs = [r for r in m["requirements"] if not brief or r["verdict"] != "met"]
        if reqs:
            out.append("  Requirements not fully met:" if brief else "  Requirements:")
        for r in reqs:
            head = f"    {MARK[r['verdict']]} {r['requirement_id']} ({r['kind'].replace('_', '-')})"
            if r["evidence_verified"]:
                out.append(head + (f" “{r['evidence'][0]}”" if r["evidence"] else ""))
            else:
                out.append(head + " ⚠️ a quote was not found in the resume")
                # shortlist-ai >= 0.1.1 names the failing quotes; older versions only say one failed.
                missing = set(r.get("unverified_quotes", r["evidence"]))
                out += [f"        “{q}”" + ("  ← not found" if q in missing else "") for q in r["evidence"]]
    for job, err in data.get("errors", {}).items():
        out.append(f"\n{job}: failed: {err}")
    return "\n".join(out) + "\n"
