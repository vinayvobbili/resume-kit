"""Trace a version's headline and summary back to the fact library.

The guardrails catch claims known to be false; they can't catch a new one nobody has written a rule for
("stayed with each tool until it was in daily use"). A summary is written by hand for each job, so each of its
claims should rest on a fact in profile.yaml. This splits the headline and summary into claims and, for each,
names the fact that backs most of its words, how much of it that fact covers, and the words and numbers no fact
says anywhere. A claim with little backing, or a number no fact has, is flagged for a person to look at: the
match is by words, so a fair paraphrase can be flagged too, and the fix is either rewording or a confirmed fact.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .content import Spec, load_profile

# Words that carry no claim: function words, and résumé glue that every summary uses.
STOP = frozenset("""
a an and are as at be been being but by for from had has have i in into is it its me my of on or our so than that
the their them then these they this those to was we were what when where which while who with within without you
your also all any both each every more most other over some such very just only own same through about after
before during under up out off again across around per via one two three four five six seven eight nine ten
years year last first now earlier today work worked working built build building
""".split())

NUMBER = re.compile(r"\d[\d,.]*\+?%?")
WORD = re.compile(r"[a-z][a-z0-9'&/-]*")


def _stem(word: str) -> str:
    """Close enough to match "agents" with "agent", "deployed" with "deploy" and "quotes" with "quote"; not a
    real stemmer."""
    word = word.strip("'&")
    for suffix in ("ations", "ation", "ings", "ing", "ies", "ers", "ed", "es", "er", "ly", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            word = word[: -len(suffix)] + ("y" if suffix == "ies" else "")
            break
    return word.removesuffix("e") if len(word) > 4 else word


def terms(text: str) -> set[str]:
    """The words and numbers in text that make a claim: lowercased, stemmed, stop words left out. A hyphenated
    or slashed word counts as its parts ("financial-services", "Java/J2EE")."""
    text = text.lower()
    numbers = {n.rstrip(".,") for n in NUMBER.findall(text)}
    words = {_stem(p) for w in WORD.findall(NUMBER.sub(" ", text)) for p in re.split(r"[-/]", w) if p}
    return numbers | {w for w in words if len(w) > 2 and w not in STOP}


def claims(spec: Spec) -> list[tuple[str, str]]:
    """(where, claim): the headline's parts, then the summary's sentences, split again at semicolons and colons."""
    out = [("headline", p.strip()) for p in re.split(r"\s*[•|]\s*", spec.headline) if p.strip()]
    for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", " ".join(spec.summary.split())):
        out += [("summary", c.strip(" .")) for c in re.split(r"[;:]\s+", sentence) if len(c.strip(" .")) > 3]
    return out


def _strings(node, path: str):
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from _strings(v, f"{path}.{k}" if path else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _strings(v, f"{path}[{i}]")


def facts(content: Path | None = None) -> dict[str, set[str]]:
    """Every string in profile.yaml (role bullets, skills, open source, certs, education, titles), by where it is,
    as terms."""
    return {path: terms(text) for path, text in _strings(load_profile(content), "")}


@dataclass
class Traced:
    where: str
    claim: str
    best: list[str] = field(default_factory=list)  # the facts that back the claim, the one that backs most first
    covered: float = 0.0            # the share of the claim's terms those facts have
    unbacked: list[str] = field(default_factory=list)  # terms no fact has
    flagged: bool = False


MOST_FACTS = 3  # a summary sentence often joins a few facts: no more than this many back one claim


def trace(spec: Spec, content: Path | None = None, least: float = 0.5) -> list[Traced]:
    """Each claim in the headline and summary, with its backing: up to MOST_FACTS facts, picked greedily for the
    claim's terms they add. Flagged: under `least` of its terms in those facts, or a number no fact has."""
    library = facts(content)
    everything = set().union(*library.values())
    out = []
    for where, claim in claims(spec):
        want = terms(claim)
        if not want:
            continue
        best, have = [], set()
        for _ in range(MOST_FACTS):
            path, adds = max(((p, (want & t) - have) for p, t in library.items()), key=lambda x: len(x[1]))
            if not adds:
                break
            best.append(path)
            have |= adds
        unbacked = sorted(want - everything)
        covered = len(have) / len(want)
        out.append(Traced(where, claim, best, covered, unbacked,
                          covered < least or any(NUMBER.fullmatch(u) for u in unbacked)))
    return out
