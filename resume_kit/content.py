"""Load the fact library and resolve a resume version into a render-ready spec.

A content directory holds profile.yaml (every fact, keyed by id), variants/<name>.yaml
(one resume version each), and optionally guardrails.yaml, answers.yaml, and postings/.

A version may `extends:` another version and override any of: headline, summary,
skills, roles (per role id), open_source, certs, certs_inline, pages.
`drop:` removes ids from every list after overrides apply. What identifies one
application (title, output, posting, applied, notes) is never inherited: a version
tailored from another is a different application, not a copy of the first.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
USER_CONTENT = Path.home() / ".config" / "resume-kit" / "content"
EXAMPLE_CONTENT = REPO / "examples" / "content"

LIST_KEYS = ("skills", "open_source", "certs")
SCALAR_KEYS = ("headline", "summary", "certs_inline", "pages")
OWN_KEYS = ("title", "output", "posting", "applied", "notes")  # this version's own; not inherited


class ContentError(ValueError):
    pass


def content_dir() -> Path:
    """RESUME_KIT_CONTENT, else ~/.config/resume-kit/content, else the bundled example."""
    if env := os.environ.get("RESUME_KIT_CONTENT"):
        return Path(env).expanduser().resolve()
    if (USER_CONTENT / "profile.yaml").exists():
        return USER_CONTENT
    print(f"resume-kit: using example content; point RESUME_KIT_CONTENT or {USER_CONTENT} at your own",
          file=sys.stderr)
    return EXAMPLE_CONTENT


@dataclass
class Spec:
    """A fully resolved resume: plain strings in render order."""

    name: str
    version: str
    title: str
    output: str
    headline: str
    contact: list[str]
    summary: str
    skills: list[str]
    roles: list[dict]
    open_source_heading: str
    open_source: list[str]
    education: list[dict]
    certs: list[str]
    certs_inline: bool = False
    pages: int = 2
    posting: Path | None = None
    meta: dict = field(default_factory=dict)

    def to_render_json(self) -> dict:
        return {
            "name": self.name,
            "headline": self.headline,
            "contact": "  |  ".join(self.contact),
            "summary": self.summary,
            "skills": self.skills,
            "roles": self.roles,
            "open_source_heading": self.open_source_heading,
            "open_source": self.open_source,
            "education": self.education,
            "certs": self.certs,
            "certs_inline": self.certs_inline,
        }

    def text(self) -> str:
        """Plain-text rendering, used for diffs and guardrail checks."""
        out = [self.name, self.headline, "  |  ".join(self.contact), "", "SUMMARY", self.summary, "", "CORE SKILLS"]
        out += [f"• {s}" for s in self.skills]
        out += ["", "PROFESSIONAL EXPERIENCE"]
        for r in self.roles:
            out.append(f"{r['title']}  |  {r['org']}  —  {r['dates']}")
            out += [f"• {b}" for b in r["bullets"]]
        if self.open_source:
            out += ["", self.open_source_heading.upper()]
            out += [f"• {s}" for s in self.open_source]
        out += ["", "EDUCATION"]
        for e in self.education:
            out.append(f"{e['school']} — {e['degree']}")
            if e.get("coursework"):
                out.append(f"  Relevant coursework: {e['coursework']}")
        if self.certs:
            out += ["", "CERTIFICATIONS"]
            out += ["  •  ".join(self.certs)] if self.certs_inline else self.certs
        return "\n".join(out) + "\n"


def _read(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text()) or {}
    except FileNotFoundError:
        raise ContentError(f"not found: {path}") from None


def load_profile(content: Path | None = None) -> dict:
    profile = _read((content or content_dir()) / "profile.yaml")
    profile.setdefault("open_source", {"heading": "Open Source", "items": {}})
    profile.setdefault("certs", {})
    seen: dict[str, str] = {}

    def claim(i: str, where: str) -> None:
        if i in seen:
            raise ContentError(f"duplicate id {i!r} in {where} (already in {seen[i]})")
        seen[i] = where

    for i in profile["skills"]:
        claim(i, "skills")
    for r in profile["roles"]:
        for i in r["bullets"]:
            claim(i, f"roles.{r['id']}")
    for i in profile["open_source"]["items"]:
        claim(i, "open_source")
    for i in profile["certs"]:
        claim(i, "certs")
    return profile


def list_versions(content: Path | None = None) -> list[str]:
    return sorted(p.stem for p in ((content or content_dir()) / "variants").glob("*.yaml"))


def raw_version(name: str, content: Path | None = None) -> dict:
    """The version with its `extends:` chain merged, before ids are resolved."""
    variants = (content or content_dir()) / "variants"
    chain, cur = [], name
    while cur:
        if cur in chain:
            raise ContentError(f"extends cycle: {' -> '.join(chain + [cur])}")
        chain.append(cur)
        cur = _read(variants / f"{cur}.yaml").get("extends")
    merged: dict = {"roles": {}, "drop": []}
    for n in reversed(chain):
        v = _read(variants / f"{n}.yaml")
        for k in SCALAR_KEYS + LIST_KEYS:
            if k in v:
                merged[k] = v[k]
        merged["roles"].update(v.get("roles", {}))
        merged["drop"] += v.get("drop", [])
    own = _read(variants / f"{name}.yaml")
    merged.update({k: own[k] for k in OWN_KEYS if k in own})
    merged["version"] = name
    return merged


def resolve(name: str, content: Path | None = None) -> Spec:
    content = content or content_dir()
    profile = load_profile(content)
    v = raw_version(name, content)
    if "output" not in v:
        raise ContentError(f"version {name!r} has no 'output' (every version names its own file)")
    for k in ("headline", "summary", "skills"):
        if k not in v:
            raise ContentError(f"version {name!r} has no {k!r} (set it, or extend a version that does)")
    drop = set(v["drop"])

    def pick(ids: list[str], pool: dict, where: str) -> list[str]:
        missing = [i for i in ids if i not in pool]
        if missing:
            raise ContentError(f"{name}: unknown {where} id(s) {missing}; known: {sorted(pool)}")
        return [pool[i] for i in ids if i not in drop]

    roles = []
    for r in profile["roles"]:
        if r["id"] not in v["roles"]:
            raise ContentError(f"{name}: no bullet list for role {r['id']!r}")
        roles.append({"title": r["title"], "org": r["org"], "dates": r["dates"],
                      "bullets": pick(v["roles"][r["id"]], r["bullets"], f"roles.{r['id']}")})
    unknown_roles = set(v["roles"]) - {r["id"] for r in profile["roles"]}
    if unknown_roles:
        raise ContentError(f"{name}: unknown role id(s) {sorted(unknown_roles)}")

    return Spec(
        name=profile["name"],
        version=name,
        title=v.get("title", name),
        output=v["output"],
        headline=v["headline"],
        contact=profile["contact"],
        summary=v["summary"],
        skills=pick(v["skills"], profile["skills"], "skills"),
        roles=roles,
        open_source_heading=profile["open_source"]["heading"],
        open_source=pick(v.get("open_source", []), profile["open_source"]["items"], "open_source"),
        education=profile["education"],
        certs=pick(v.get("certs", []), profile["certs"], "certs"),
        certs_inline=bool(v.get("certs_inline", False)),
        pages=int(v.get("pages", profile.get("pages", 2))),
        posting=content / v["posting"] if v.get("posting") else None,
        meta={k: v[k] for k in ("applied", "notes") if k in v},
    )
