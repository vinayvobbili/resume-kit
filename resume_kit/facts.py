"""Guardrails: claims that must never appear on a resume, and facts that must.

Rules live in the content directory's guardrails.yaml, each with the reason it exists,
so a failing check explains itself. `build` refuses to render a version that trips one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .content import ContentError, Spec, content_dir


@dataclass(frozen=True)
class Rule:
    id: str
    pattern: str
    why: str
    case_sensitive: bool = False

    def find(self, text: str) -> list[str]:
        flags = 0 if self.case_sensitive else re.IGNORECASE
        return [m.group(0) for m in re.finditer(self.pattern, text, flags=flags)]


@dataclass(frozen=True)
class Guardrails:
    forbidden: tuple[Rule, ...] = ()
    required: tuple[Rule, ...] = ()

    def violations(self, text: str) -> list[str]:
        problems = [f"{r.id}: found {r.find(text)[:3]} ({r.why})" for r in self.forbidden if r.find(text)]
        problems += [f"{r.id}: missing ({r.why})" for r in self.required if not r.find(text)]
        return problems


def load(content: Path | None = None) -> Guardrails:
    path = (content or content_dir()) / "guardrails.yaml"
    if not path.exists():
        return Guardrails()
    data = yaml.safe_load(path.read_text()) or {}

    def rules(key: str) -> tuple[Rule, ...]:
        out = []
        for r in data.get(key, []):
            try:
                re.compile(r["pattern"])
                out.append(Rule(r["id"], r["pattern"], r["why"], bool(r.get("case_sensitive", False))))
            except (KeyError, re.error) as e:
                raise ContentError(f"{path}: bad {key} rule {r.get('id', r)!r}: {e}") from None
        return tuple(out)

    return Guardrails(rules("forbidden"), rules("required"))


def check(spec: Spec, content: Path | None = None) -> list[str]:
    return load(content).violations(spec.text())
