"""resume: build, check, compare, and score tailored resume versions."""

from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
from pathlib import Path

import yaml

from . import apply, facts, score
from .build import DEFAULT_OUT, BuildError, build, preview
from .content import ContentError, content_dir, list_versions, raw_version, resolve


def cmd_list(args) -> int:
    print(f"content: {content_dir()}")
    for name in list_versions():
        v = raw_version(name)
        applied = f"  (applied {v['applied']})" if v.get("applied") else ""
        print(f"{name:<14} {v.get('title', '')}{applied}")
    return 0


def cmd_show(args) -> int:
    print(resolve(args.version).text(), end="")
    return 0


def cmd_diff(args) -> int:
    a, b = resolve(args.a).text().splitlines(), resolve(args.b).text().splitlines()
    sys.stdout.writelines(line + "\n" for line in difflib.unified_diff(a, b, args.a, args.b, lineterm="", n=0))
    return 0


def cmd_check(args) -> int:
    failed = 0
    for name in args.versions or list_versions():
        problems = facts.check(resolve(name))
        failed += bool(problems)
        print(f"{name}: " + ("ok" if not problems else "\n  " + "\n  ".join(problems)))
    return 1 if failed else 0


def cmd_build(args) -> int:
    names = list_versions() if args.all else args.versions
    if not names:
        print("name a version, or use --all", file=sys.stderr)
        return 2
    bad = 0
    for name in names:
        result = build(name, Path(args.out))
        print(result.summary())
        bad += not result.ok
        if args.preview:
            for img in preview(result.pdf):
                print(f"  preview: {img}")
    return 1 if bad else 0


def cmd_score(args) -> int:
    data = score.score(args.version, [Path(p) for p in args.postings], backend=args.backend)
    print(json.dumps(data, indent=2, ensure_ascii=False) if args.json else score.to_text(data), end="")
    return 1 if data.get("errors") else 0


def cmd_answers(args) -> int:
    print(yaml.safe_dump(apply.answers(args.section), sort_keys=False, allow_unicode=True), end="")
    return 0


def cmd_ats(args) -> int:
    if not args.name:
        print("\n".join(apply.ats_names()))
        return 0
    pb = apply.ats_playbook(args.name)
    if not args.js:
        pb.pop("helpers")
    print(yaml.safe_dump(pb, sort_keys=False, allow_unicode=True, width=110), end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="resume", description=__doc__)
    p.add_argument("--content", help="content directory (default: $RESUME_KIT_CONTENT, then ~/.config/resume-kit/content)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list resume versions").set_defaults(fn=cmd_list)

    s = sub.add_parser("show", help="print a version as plain text")
    s.add_argument("version")
    s.set_defaults(fn=cmd_show)

    s = sub.add_parser("diff", help="compare two versions line by line")
    s.add_argument("a")
    s.add_argument("b")
    s.set_defaults(fn=cmd_diff)

    s = sub.add_parser("check", help="run fact guardrails (default: every version)")
    s.add_argument("versions", nargs="*")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("build", help="render .docx + .pdf and check the page target")
    s.add_argument("versions", nargs="*")
    s.add_argument("--all", action="store_true")
    s.add_argument("--out", default=str(DEFAULT_OUT), help=f"output directory (default {DEFAULT_OUT})")
    s.add_argument("--preview", action="store_true", help="also write page JPEGs")
    s.set_defaults(fn=cmd_build)

    s = sub.add_parser("score", help="score a version against job postings with shortlist-ai")
    s.add_argument("version")
    s.add_argument("postings", nargs="*", help="posting files (.md/.txt/.pdf/.docx); default: the version's `posting:`")
    s.add_argument("--backend", choices=["local", "claude"], default="local",
                   help="local keeps the resume on this machine (default); claude needs ANTHROPIC_API_KEY")
    s.add_argument("--json", action="store_true", help="print shortlist's full JSON")
    s.set_defaults(fn=cmd_score)

    s = sub.add_parser("answers", help="standard application-form answers")
    s.add_argument("section", nargs="?")
    s.set_defaults(fn=cmd_answers)

    s = sub.add_parser("ats", help="quirks for an applicant tracking system (or list them)")
    s.add_argument("name", nargs="?", help="system name or a host, e.g. greenhouse, jobs.ashbyhq.com")
    s.add_argument("--js", action="store_true", help="include the JavaScript helpers")
    s.set_defaults(fn=cmd_ats)

    args = p.parse_args(argv)
    if args.content:
        os.environ["RESUME_KIT_CONTENT"] = args.content
    try:
        return args.fn(args)
    except (ContentError, BuildError, score.ScoreError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
