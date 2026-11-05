"""Run the demo's real resume-kit commands on a copy of the bundled example and save what they print.

    python scripts/demo/capture.py scripts/demo/out

Only the fictional candidate in examples/content is used: the copy lives in OUT/content, with the demo-only
variants, posting and extra bullets from scripts/demo/fixtures added, so the bundled example stays as it is. Every
command gets an explicit --content, so a real content folder is never read. Writes OUT/captures.json, which
build.py turns into the terminal slides. The score step is the one exception: `resume score` needs a local model,
so its output is the real run recorded in scripts/demo/score-output.txt (the same output the README showed).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EXAMPLE = ROOT / "examples" / "content"
FIXTURES = HERE / "fixtures"
SCORE_OUTPUT = HERE / "score-output.txt"

# (key, the command as shown, the arguments run after `resume --content content`, whether it should fail)
STEPS = [
    ("list", "resume list", ["list"], False),
    ("draft", "resume draft globex-appsec posting.md",
     ["draft", "globex-appsec", "content/postings/globex-appsec.md", "--title", "Globex — Application Security Engineer"], False),
    ("check", "resume check", ["check"], True),
    ("build", "resume build acme-everything", ["build", "acme-everything", "--out", "resumes"], True),
]
SCORE_COMMAND = "resume score acme"


def add_extra_bullets(content: Path, extra: Path = FIXTURES / "extra-bullets.yaml") -> None:
    """Add the demo's extra bullets (role id -> {fact id: text}) to the copy's profile.yaml."""
    path = content / "profile.yaml"
    profile = yaml.safe_load(path.read_text())
    wanted = yaml.safe_load(extra.read_text())
    for role in profile["roles"]:
        role["bullets"].update(wanted.get(role["id"], {}))
    path.write_text(yaml.safe_dump(profile, sort_keys=False, allow_unicode=True, width=120))


def prepare(out: Path) -> Path:
    """Copy the example into OUT/content and lay the demo fixtures over it; returns the copy."""
    content = out / "content"
    shutil.rmtree(content, ignore_errors=True)
    shutil.copytree(EXAMPLE, content)
    shutil.copytree(FIXTURES / "variants", content / "variants", dirs_exist_ok=True)
    shutil.copytree(FIXTURES / "postings", content / "postings", dirs_exist_ok=True)
    add_extra_bullets(content)
    return content


def clean(text: str, out: Path) -> str:
    """The output as a reader of the README would see it: no absolute paths from this machine."""
    for real in {str(out), str(out.resolve())}:
        text = text.replace(real + "/", "").replace(real, ".")
    return text.replace("/private", "").rstrip()


def run(out: Path, python: str = sys.executable) -> dict:
    """Run each step in OUT; returns {key: {"command": ..., "output": ..., "ok": ...}}."""
    out = out.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    prepare(out)
    resume = Path(python).parent / "resume"
    results = {}
    for key, shown, args, may_fail in STEPS:
        done = subprocess.run([str(resume), "--content", "content", *args], cwd=out, capture_output=True, text=True,
                              check=False)
        if done.returncode != 0 and not may_fail:
            raise SystemExit(f"`{shown}` failed ({done.returncode}):\n{done.stdout}{done.stderr}")
        results[key] = {"command": shown, "output": clean(done.stdout + done.stderr, out), "ok": done.returncode == 0}
    results["score"] = {"command": SCORE_COMMAND, "output": SCORE_OUTPUT.read_text().rstrip(), "ok": True}
    (out / "captures.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", nargs="?", type=Path, default=HERE / "out", help="the demo's output folder")
    args = ap.parse_args()
    for result in run(args.out).values():
        print(f"== {result['command']}\n{result['output']}\n")


if __name__ == "__main__":
    main()
