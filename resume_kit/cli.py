"""resume: build, check, compare, and score tailored resume versions."""

from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
from pathlib import Path

import yaml

from . import apply, draft, facts, score, trace
from .build import DEFAULT_OUT, BuildError, build, preview
from .content import ContentError, content_dir, library, list_versions, picked, raw_version, resolve


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


def cmd_facts(args) -> int:
    chosen = picked(args.version) if args.version else {}
    for key, heading, items in library():
        if args.section and args.section not in (key, key.removeprefix("roles.")):
            continue
        print(f"{key}: {heading}")
        order = chosen.get(key, [])
        for i, text in items.items():
            mark = f"{order.index(i) + 1:>2}" if i in order else ("  " if not args.version else " -")
            text = " ".join(str(text).split())
            if args.width and len(text) > args.width:
                text = text[:args.width - 1] + "…"
            print(f"  {mark} {i}: {text}")
    return 0


def cmd_trace(args) -> int:
    if not args.versions and not args.text:
        sys.exit("resume trace: name a version, or pass --text FILE")
    flagged = 0
    runs = [(name, lambda n=name: trace.trace(resolve(n), least=args.least)) for name in args.versions]
    runs += [(str(p), lambda p=p: trace.trace_text(Path(p).read_text(), least=args.least)) for p in args.text]
    for name, run in runs:
        rows = run()
        hits = [r for r in rows if r.flagged]
        flagged += len(hits)
        print(f"{name}: {len(rows)} claims, {len(hits)} flagged")
        for r in hits if args.flagged else rows:
            mark = "!!" if r.flagged else "ok"
            print(f"  {mark} {r.covered:4.0%} [{r.where}] {r.claim}")
            print(f"       backed by: {', '.join(r.best) or 'nothing'}"
                  + (f"; in no fact: {', '.join(r.unbacked)}" if r.unbacked else ""))
    return 1 if flagged else 0


def cmd_diff(args) -> int:
    a, b = resolve(args.a).text().splitlines(), resolve(args.b).text().splitlines()
    sys.stdout.writelines(line + "\n" for line in difflib.unified_diff(a, b, args.a, args.b, lineterm="", n=0))
    return 0


def cmd_check(args) -> int:
    failed = 0
    for name in args.versions or list_versions():
        problems = facts.check(resolve(name), reuse=args.reuse)
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
        try:
            result = build(name, Path(args.out), as_sent=args.as_sent)
        except BuildError as e:  # one version that can't be sent again doesn't stop the rest of --all
            print(f"error: {e}", file=sys.stderr)
            bad += 1
            continue
        print(result.summary())
        bad += not result.ok
        if args.preview:
            for img in preview(result.pdf):
                print(f"  preview: {img}")
    return 1 if bad else 0


def cmd_draft(args) -> int:
    text = sys.stdin.read() if args.posting == "-" else Path(args.posting).expanduser().read_text()
    d = draft.draft(args.name, text, title=args.title, parent=args.parent, output=args.output, force=args.force)
    print(d.summary())
    return 0


def cmd_score(args) -> int:
    data = score.score(args.version, [Path(p) for p in args.postings], backend=args.backend, keychain=args.keychain)
    print(json.dumps(data, indent=2, ensure_ascii=False) if args.json else score.to_text(data, brief=args.brief),
          end="")
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

    s = sub.add_parser("facts", help="every fact a version can pick, by id; with --version, its picks in order")
    s.add_argument("section", nargs="?", help="one section: skills, a role id, open_source or certs")
    s.add_argument("--version", help="number the facts this version picks, in its order; - marks the rest")
    s.add_argument("--width", type=int, default=0, help="cut each fact's text to this many characters")
    s.set_defaults(fn=cmd_facts)

    s = sub.add_parser("trace", help="each claim in a version's headline and summary, with the fact that backs it; "
                       "flags claims no fact backs (exit 1 if any)")
    s.add_argument("versions", nargs="*")
    s.add_argument("--text", action="append", default=[], metavar="FILE", help="also trace the sentences of a "
                   "cover letter or message (repeatable); the greeting and signature are skipped")
    s.add_argument("--least", type=float, default=0.5, help="flag a claim when no one fact has this share of its "
                   "words (default 0.5)")
    s.add_argument("--flagged", action="store_true", help="list only the flagged claims")
    s.set_defaults(fn=cmd_trace)

    s = sub.add_parser("diff", help="compare two versions line by line")
    s.add_argument("a")
    s.add_argument("b")
    s.set_defaults(fn=cmd_diff)

    s = sub.add_parser("check", help="run fact guardrails (default: every version)")
    s.add_argument("versions", nargs="*")
    s.add_argument("--reuse", action="store_true",
                   help="check versions already applied with against every rule, as `build` does before sending again")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("build", help="render .docx + .pdf and check the page target")
    s.add_argument("versions", nargs="*")
    s.add_argument("--all", action="store_true")
    s.add_argument("--out", default=str(DEFAULT_OUT), help=f"output directory (default {DEFAULT_OUT})")
    s.add_argument("--preview", action="store_true", help="also write page JPEGs")
    s.add_argument("--as-sent", action="store_true",
                   help="re-render a version already applied with as it was sent, without guardrails added since "
                        "(not a copy to send again)")
    s.set_defaults(fn=cmd_build)

    s = sub.add_parser("draft", help="draft a tailored version from a job posting (facts ordered by relevance)")
    s.add_argument("name", help="new version name, e.g. acme-sre")
    s.add_argument("posting", help="posting text file, or - to read it from stdin")
    s.add_argument("--title", help="version title (default: the name)")
    s.add_argument("--from", dest="parent", help="version to extend (default: the closest one that shows every role, with dates)")
    s.add_argument("--output", help="output file stem")
    s.add_argument("--force", action="store_true", help="overwrite an existing version")
    s.set_defaults(fn=cmd_draft)

    s = sub.add_parser("score", help="score a version against job postings with shortlist-ai")
    s.add_argument("version")
    s.add_argument("postings", nargs="*", help="posting files (.md/.txt/.pdf/.docx); default: the version's `posting:`")
    s.add_argument("--backend", choices=["local", "claude"], default=os.environ.get("RESUME_KIT_BACKEND", "local"),
                   help="local keeps the resume on this machine (default, or $RESUME_KIT_BACKEND); claude needs "
                        "ANTHROPIC_API_KEY or --keychain")
    s.add_argument("--keychain", default=os.environ.get("RESUME_KIT_KEYCHAIN", ""),
                   help="macOS keychain item holding the Anthropic API key, when ANTHROPIC_API_KEY isn't set "
                        "(default $RESUME_KIT_KEYCHAIN)")
    s.add_argument("--json", action="store_true", help="print shortlist's full JSON")
    s.add_argument("--brief", action="store_true",
                   help="print only the score, the gaps, and the requirements not fully met")
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
