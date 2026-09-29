"""MCP server exposing resume-kit to Claude: versions, builds, guardrails, scoring, form answers."""

from __future__ import annotations

from pathlib import Path

from mcp.server.mcpserver import MCPServer

from . import apply, draft, facts, score
from .build import DEFAULT_OUT, build, preview
from .content import content_dir, raw_version, resolve
from .content import list_versions as _list_versions

server = MCPServer(
    "resume-kit",
    instructions=(
        "Tailored resume versions built from one fact library (a content directory; list_versions shows "
        "which). To tailor a resume for a job, call draft_version with the posting (or write variants/<name>.yaml "
        "that picks and orders ids from profile.yaml), tailor its headline and summary, then call build_version; it must hit its page target and pass "
        "check_facts. score_version shows what a screener sees missing. Never add a claim to profile.yaml "
        "that the candidate has not confirmed, and never close a gap that a guardrail marks as real."
    ),
)


@server.tool()
def list_versions() -> dict:
    """List resume versions with their title and applied date, and the content directory in use."""
    out = []
    for name in _list_versions():
        v = raw_version(name)
        out.append({"version": name, "title": v.get("title", ""), "applied": v.get("applied"),
                    "output": v.get("output"), "posting": v.get("posting")})
    return {"content": str(content_dir()), "versions": out}


@server.tool()
def show_version(version: str) -> str:
    """The resolved resume as plain text (what the PDF will say)."""
    return resolve(version).text()


@server.tool()
def check_facts(version: str | None = None) -> dict:
    """Run the fact guardrails (forbidden claims, required facts) on one version or all of them."""
    names = [version] if version else _list_versions()
    return {n: facts.check(resolve(n)) or "ok" for n in names}


@server.tool()
def build_version(version: str, out_dir: str | None = None, with_preview: bool = False) -> dict:
    """Render .docx and .pdf (default ~/Downloads or RESUME_KIT_OUT), check the page target, report overflow."""
    r = build(version, Path(out_dir) if out_dir else DEFAULT_OUT)
    result = {"version": version, "pages": r.pages, "target_pages": r.target, "ok": r.ok,
              "docx": str(r.docx), "pdf": str(r.pdf)}
    if r.overflow:
        result["overflow_text"] = r.overflow
    if with_preview:
        result["preview_images"] = [str(p) for p in preview(r.pdf)]
    return result


@server.tool()
def draft_version(name: str, posting_text: str, title: str | None = None, parent: str | None = None,
                  force: bool = False) -> dict:
    """Draft a tailored version for a job posting: saves the posting, extends the closest existing version
    (or `parent`), and picks and orders skill, bullet and open-source ids by relevance to the posting,
    keeping the parent's counts so the page target holds. Headline and summary stay the parent's: rewrite
    them from confirmed facts only, then check_facts, build_version and score_version."""
    d = draft.draft(name, posting_text, title=title, parent=parent, force=force)
    return {"version": name, "file": str(d.path), "extends": d.parent, "posting": str(d.posting),
            "changes": {k: {"parent": a, "draft": b} for k, (a, b) in d.changed.items()},
            "posting_terms_not_in_profile": d.missing_terms, "summary": d.summary()}


@server.tool()
def score_version(version: str, postings: list[str] | None = None, backend: str = "local") -> dict:
    """Score the built resume against job postings (file paths; default: the version's posting) with
    shortlist-ai. Returns per-job score, must-haves met, gaps, and per-requirement verdicts with quotes.
    gap_notes marks gaps that a guardrail says are real, which must not be papered over."""
    return score.score(version, [Path(p) for p in postings] if postings else None, backend=backend)


@server.tool()
def application_answers(section: str | None = None) -> dict:
    """Standard answers for application forms: contact, work_authorization, experience_years, screening,
    salary, defaults, eeo. Omit section for everything."""
    return apply.answers(section)


@server.tool()
def ats_playbook(system: str) -> dict:
    """Quirks, shared rules, and JavaScript helpers for an applicant tracking system
    (greenhouse, ashby, taleo, workday, linkedin, eightfold) or a job-page host."""
    return apply.ats_playbook(system)


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
