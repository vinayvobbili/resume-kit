"""Render a cover letter written as markdown to .docx and .pdf, with the resume's letterhead and look.

A letter is plain paragraphs separated by blank lines. An optional first line `# Subject` becomes a bold
subject line. A first paragraph that opens "Dear ...", "Hello ..." or "Hi ..." is the greeting; without one
(or with `to`) the greeting is "Dear <to>,". A last paragraph that is only a closing ("Sincerely,") and the
candidate's name is the sign-off; the name always comes from profile.yaml, so a letter and a resume sent
together carry the same one. The text is held to the content directory's forbidden guardrails, so a letter
can't claim what a resume can't, except that a sentence which denies a forbidden term ("I have not run X in
production", "rather than on X") passes, and the build prints it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import facts
from .build import DEFAULT_OUT, BuildError, BuildResult, typeset
from .content import ContentError, contact_line, content_dir, load_profile, resolve

PAGES = 1  # a cover letter is one page
DEFAULT_TO = "Hiring Team"
DEFAULT_CLOSING = "Sincerely,"
GREETING = re.compile(r"(dear|hello|hi|greetings)\b", re.IGNORECASE)
# A sentence with one of these denies or contrasts what it names: "I have not run X in production".
DISCLAIMER = re.compile(
    r"\b(have not|haven't|has not|hasn't|did not|didn't|do not have|don't have|not run|not yet|never|without"
    r"|no hands-on|no experience|rather than|instead of)\b", re.IGNORECASE)
NOT_A_CUE = re.compile(r"\bnot (only|just)\b", re.IGNORECASE)  # "have not only run X but Y" is a claim


@dataclass
class Letter:
    stem: str
    name: str
    contact: list[str]
    subject: str
    greeting: str
    paragraphs: list[str]
    closing: str

    def to_render_json(self) -> dict:
        return {"name": self.name, "headline": "", "contact": contact_line(self.contact),
                "letter": {"subject": self.subject, "greeting": self.greeting, "paragraphs": self.paragraphs,
                           "closing": self.closing}}

    def text(self) -> str:
        """Everything the letter says, for the guardrail check."""
        return "\n\n".join([s for s in (self.subject, self.greeting, *self.paragraphs, self.closing, self.name) if s])


def parse(markdown: str, name: str, contact: list[str], stem: str = "letter", to: str | None = None) -> Letter:
    """Split a markdown letter into subject, greeting, body paragraphs and closing."""
    blocks = [[ln.strip() for ln in b.strip().splitlines()] for b in re.split(r"\n\s*\n", markdown.strip()) if b.strip()]
    subject = ""
    if blocks and blocks[0][0].startswith("# "):
        subject = blocks[0].pop(0)[2:].strip()
        if not blocks[0]:
            blocks.pop(0)
    greeting = ""
    if blocks and len(blocks[0]) == 1 and GREETING.match(blocks[0][0]):
        greeting = blocks.pop(0)[0]
    closing = DEFAULT_CLOSING
    if blocks:  # a last block of only a closing and/or the name is the sign-off
        signed = [ln for ln in blocks[-1] if ln.casefold() not in (name.casefold(), name.split()[0].casefold())]
        if len(signed) <= 1 and all(ln.endswith(",") and len(ln) <= 40 for ln in signed):
            blocks.pop()
            closing = signed[0] if signed else DEFAULT_CLOSING
    paragraphs = [" ".join(b) for b in blocks]
    if not paragraphs:
        raise ContentError("the letter has no paragraphs")
    if to or not greeting:
        greeting = f"Dear {to or DEFAULT_TO},"
    return Letter(stem, name, contact, subject, greeting, paragraphs, closing)


def find(path: str | Path, content: Path) -> Path:
    """The letter file: the path as given, else letters/<path>[.md] in the content directory."""
    given = Path(path).expanduser()
    for candidate in (given, content / "letters" / given, content / "letters" / f"{given}.md"):
        if candidate.is_file():
            return candidate
    raise ContentError(f"letter not found: {path} (also looked in {content / 'letters'})")


def check(text: str, rules: tuple[facts.Rule, ...]) -> tuple[list[str], list[str]]:
    """What a letter's text breaks, and what it only disclaims: (problems, notes). A forbidden term inside a
    sentence that denies it ("I have not run X in production") is no claim, so it passes with a note; a plain
    claim fails."""
    problems, notes = [], []
    sentences = [s for line in text.splitlines() for s in re.split(r"(?<=[.!?])\s+", line) if s.strip()]
    for rule in rules:
        claims = []
        for sentence in sentences:
            if not rule.find(sentence):
                continue
            if DISCLAIMER.search(NOT_A_CUE.sub("", sentence)):
                notes.append(f"disclaimer, allowed: {rule.id}: {sentence.strip()}")
            else:
                claims += rule.find(sentence)
        if claims:
            problems.append(f"{rule.id}: found {claims[:3]} ({rule.why})")
    return problems, notes


def cover(path: str | Path, out_dir: Path = DEFAULT_OUT, name: str | None = None, to: str | None = None,
          version: str | None = None, content: Path | None = None) -> BuildResult:
    """Render the letter at `path` to out_dir/<name>.docx and .pdf (name defaults to the letter's file name).
    `version`: take the contact line from that resume version (one that hides or swaps a link), not the profile.
    Sentences that pass the guardrails only because they disclaim a forbidden term come back in `result.notes`."""
    content = content or content_dir()
    path = find(path, content)
    profile = load_profile(content)
    contact = resolve(version, content).contact if version else profile["contact"]
    letter = parse(path.read_text(), profile["name"], contact, path.stem, to)
    problems, notes = check(letter.text(), facts.load(content).forbidden)
    if problems:
        raise BuildError(f"{path} fails fact checks:\n  " + "\n  ".join(problems))
    result = typeset(letter, letter.stem, out_dir / f"{name or letter.stem}.docx", PAGES)
    result.fill = 1.0  # a letter is never padded to fill its page, so its last page isn't "mostly blank"
    result.notes = notes
    return result
