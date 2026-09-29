"""Draft a tailored version from a job posting: confirmed facts only, ordered by relevance.

The draft extends the existing version that reads most like the posting and keeps its
shape (how many skills, bullets per role, and open-source items it shows, so the page
count holds), then picks and orders ids by how much of the posting's wording each fact
shares. Nothing is written or reworded: headline and summary stay the parent's until a
person tailors them, and every line still comes from profile.yaml, so the guardrails hold.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .content import ContentError, content_dir, list_versions, load_profile, raw_version, resolve

# A word block reads better than a 100-item list literal.
_STOP = set("""
a about above across after all also an and any are as at be been being both but by can could do does
each either etc for from had has have having how if in into is it its may more most must no not of on
once one or other our out over own per same should so some such than that the their them then there these
they this those through to too under up us using very via was we were what when where which while who
will with within would you your years year experience strong ability skills work working team teams
including across plus preferred required requirements role job new engineer engineering senior staff lead
principal manager ideal candidate looking help build company customer office environment technical product
end-to-end http https www com opportunity benefit salary equal employer apply location based full time use
building make get well like want need day week month hour today every many part way people world
lunch stipend dental vision medical health insurance 401k pto vacation parental leave wellness perk equity
compensation bonus visa relocation hybrid onsite remote city state country office headquarter
new york san francisco seattle austin boston chicago denver london toronto montreal vancouver
""".split())  # noqa: SIM905


def _singular(t: str) -> str:
    return t[:-1] if len(t) > 3 and t.endswith("s") and not t.endswith("ss") else t


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9][a-z0-9+#./-]*[a-z0-9+#]|[a-z0-9]", text.lower())


def tokens(text: str) -> list[str]:
    """Lowercase terms, stopwords dropped, plurals folded ("logs" -> "log")."""
    return [_singular(t) for t in _words(text) if t not in _STOP and _singular(t) not in _STOP]


class Relevance:
    """How much of a posting's wording a fact shares, weighting rarer terms (among the facts) higher."""

    def __init__(self, posting: str, facts: dict[str, str]):
        self.posting = Counter(tokens(posting))
        self.spelling: dict[str, str] = {}  # folded term -> as the posting first wrote it
        for w in _words(posting):
            self.spelling.setdefault(_singular(w), w)
        docs = {i: set(tokens(t)) for i, t in facts.items()}
        n = max(len(docs), 1)
        df = Counter(t for d in docs.values() for t in d)
        self.idf = {t: math.log(1 + n / c) for t, c in df.items()}
        self.docs = docs

    def score(self, fact_id: str) -> float:
        """Shared, weighted terms, divided by the root of the fact's length so long bullets don't win on size."""
        terms = self.docs.get(fact_id, set())
        hits = sum(math.log(1 + self.posting[t]) * self.idf.get(t, 0) for t in terms if t in self.posting)
        return hits / math.sqrt(len(terms) or 1)

    def overlaps(self, a: str, b: str, threshold: float = 0.6) -> bool:
        """Two wordings of one fact: most of the shorter one's terms are in the longer one."""
        ta, tb = self.docs.get(a, set()), self.docs.get(b, set())
        return bool(ta and tb) and len(ta & tb) / min(len(ta), len(tb)) >= threshold

    def order(self, ids: list[str]) -> list[str]:
        """Most relevant first; ties keep the given order."""
        return sorted(ids, key=lambda i: -self.score(i))

    def missing_terms(self, top: int = 15, ignore: set[str] = frozenset()) -> list[str]:
        """Posting terms used at least twice that no fact mentions: possible gaps (or just different wording).

        `ignore` holds terms that can't be gaps, such as the company's name.
        """
        known = set(self.idf) | ignore
        return [self.spelling.get(t, t) for t, n in self.posting.most_common()
                if n >= 2 and t not in known and len(t) > 2][:top]


@dataclass
class Draft:
    name: str
    parent: str
    path: Path
    posting: Path
    data: dict
    missing_terms: list[str] = field(default_factory=list)
    changed: dict[str, tuple[list, list]] = field(default_factory=dict)  # section -> (parent's, draft's)

    def summary(self) -> str:
        out = [f"Drafted {self.path} (extends {self.parent}); posting saved to {self.posting}"]
        for section, (before, after) in self.changed.items():
            added = [i for i in after if i not in before]
            dropped = [i for i in before if i not in after]
            note = "reordered" if not (added or dropped) else ", ".join(
                p for p in (f"added {added}" if added else "", f"dropped {dropped}" if dropped else "") if p)
            out.append(f"  {section}: {note}")
        out.append("  headline and summary are the parent's: tailor them with confirmed facts only")
        if self.missing_terms:
            out.append(f"  posting terms no fact mentions (gaps, or different wording): {', '.join(self.missing_terms)}")
        return "\n".join(out)


def _slug(name: str) -> str:
    return "_".join(w.capitalize() for w in re.split(r"[^A-Za-z0-9]+", name) if w)


def draft(name: str, posting_text: str, title: str | None = None, parent: str | None = None,
          output: str | None = None, content: Path | None = None, force: bool = False) -> Draft:
    content = content or content_dir()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name):
        raise ContentError(f"version name {name!r}: use lowercase letters, digits and hyphens")
    path = content / "variants" / f"{name}.yaml"
    if path.exists() and not force:
        raise ContentError(f"{path} exists (pass force to overwrite)")
    if not posting_text.strip():
        raise ContentError("the posting is empty")

    profile = load_profile(content)
    facts: dict[str, str] = dict(profile["skills"])
    for role in profile["roles"]:
        facts.update(role["bullets"])
    facts.update(profile["open_source"]["items"])
    rel = Relevance(posting_text, facts)

    versions = [v for v in list_versions(content) if v != name]
    if parent is None:
        if not versions:
            raise ContentError("no versions to extend; create variants/base.yaml first")
        post = Counter(tokens(posting_text))
        # The version whose resume text shares the most posting terms, per term it uses.
        def closeness(v: str) -> float:
            words = Counter(tokens(resolve(v, content).text()))
            return sum(min(c, post[t]) for t, c in words.items() if t in post) / math.sqrt(sum(words.values()) or 1)
        parent = max(versions, key=closeness)
    elif parent not in versions:
        raise ContentError(f"unknown version {parent!r}")
    base = raw_version(parent, content)

    changed: dict[str, tuple[list, list]] = {}
    data: dict = {"extends": parent, "title": title or name, "output": output or
                  f"{profile['name'].replace(' ', '_')}_Resume_{_slug(name)}"}

    posting_path = content / "postings" / f"{name}.md"
    posting_path.parent.mkdir(parents=True, exist_ok=True)
    posting_path.write_text(posting_text.strip() + "\n", encoding="utf-8")
    data["posting"] = f"postings/{name}.md"

    dropped = set(base.get("drop", []))  # inherited, so the draft can't use these ids
    used: list[str] = []  # everything picked so far, across sections

    def pick(section: str, current: list[str], pool: list[str]) -> list[str]:
        current = [i for i in current if i not in dropped]
        # The parent's picks first, so ties keep its order; then the rest of the profile.
        pool = current + [i for i in pool if i not in current and i not in dropped]
        chosen: list[str] = []
        for i in rel.order(pool):
            if len(chosen) == len(current):
                break
            # Profiles keep alternate wordings of one fact (short and long, per audience): use one.
            if not any(rel.overlaps(i, j) for j in used + chosen):
                chosen.append(i)
        used.extend(chosen)
        if chosen != current:
            changed[section] = (current, chosen)
        return chosen

    data["skills"] = pick("skills", base.get("skills", []), list(profile["skills"]))
    data["roles"] = {}
    for role in profile["roles"]:
        current = base["roles"].get(role["id"], [])
        chosen = pick(f"roles.{role['id']}", current, list(role["bullets"]))
        if chosen != current:
            data["roles"][role["id"]] = chosen
    if not data["roles"]:
        del data["roles"]
    if base.get("open_source"):
        data["open_source"] = pick("open_source", base["open_source"], list(profile["open_source"]["items"]))
    for section in ("skills", "open_source"):
        if data.get(section) == base.get(section):
            del data[section]

    header = (f"# Drafted by `resume draft` from postings/{name}.md, extending {parent}.\n"
              "# Ids are ordered by relevance to the posting. headline and summary are inherited:\n"
              "# tailor them with confirmed facts, then `resume check`, `resume build`, `resume score`.\n")
    path.write_text(header + yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=110), encoding="utf-8")
    # The version's name and title usually name the company, which is never a gap.
    ignore = set(tokens(f"{name.replace('-', ' ')} {title or ''}"))
    return Draft(name, parent, path, posting_path, data, rel.missing_terms(ignore=ignore), changed)
