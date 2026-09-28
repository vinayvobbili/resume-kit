"""Standard application-form answers and ATS playbooks."""

from __future__ import annotations

from pathlib import Path

import yaml

from .content import ContentError, content_dir

ATS_FILE = Path(__file__).with_name("ats.yaml")


def answers(section: str | None = None, content: Path | None = None) -> dict:
    path = (content or content_dir()) / "answers.yaml"
    if not path.exists():
        raise ContentError(f"{path} not found; copy examples/content/answers.example.yaml there and fill it in")
    data = yaml.safe_load(path.read_text()) or {}
    if section is None:
        return data
    if section not in data:
        raise ContentError(f"no section {section!r}; sections: {sorted(data)}")
    return {section: data[section]}


def ats_names() -> list[str]:
    return sorted(_ats()["systems"])


def ats_playbook(name: str) -> dict:
    """Quirks for one ATS, plus the shared rules and JavaScript helpers."""
    data = _ats()
    key = name.lower().strip()
    matches = [k for k, v in data["systems"].items()
               if key == k or any(key in h or h.lstrip("*.") in key for h in v.get("hosts", []))]
    if not matches:
        raise ContentError(f"unknown ATS {name!r}; known: {ats_names()}")
    return {"system": matches[0], **data["systems"][matches[0]], "rules": data["rules"], "helpers": data["helpers"]}


def _ats() -> dict:
    return yaml.safe_load(ATS_FILE.read_text())
