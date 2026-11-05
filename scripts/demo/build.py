"""The README's demo video: its slides and narration. Writes slides/*.html and reel.yaml into the demo's output
folder; then slidecast (https://pypi.org/project/slidecast/) renders the video:

    python scripts/demo/build.py scripts/demo/out [--music DIR]
    slidecast render scripts/demo/out/reel.yaml -o scripts/demo/out/resume-kit-demo.mp4 --poster

The folder holds captures.json, the real output of the demo's commands (from capture.py) on the bundled example: a
fictional candidate and made-up companies (Acme, Globex). The music bed and stings (music_bed.wav, intro_sting.wav,
outro_sting.wav) are read from --music, else from the folder itself; without them the video has the voice only.
"""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

import yaml

OUT = Path(__file__).resolve().parent / "out"

CSS = """
html { zoom: 1.5; }  /* designed at 1280x720, rendered at 1920x1080 */
* { box-sizing: border-box; margin: 0; padding: 0; }
body { width: 1280px; height: 720px; overflow: hidden; color: #eef4ff;
  font-family: -apple-system, "SF Pro Display", "Helvetica Neue", Arial, sans-serif;
  background: radial-gradient(1100px 650px at 90% -15%, #1c6fd1 0%, transparent 60%),
              radial-gradient(900px 600px at -10% 115%, #0d9e8f 0%, transparent 55%),
              radial-gradient(500px 300px at 55% 50%, rgba(255,200,87,.07) 0%, transparent 70%), #08162a; }
.brand { position: absolute; top: 26px; right: 40px; display: flex; align-items: center; gap: 10px;
  font-weight: 700; font-size: 20px; letter-spacing: -.01em; opacity: .92; }
.logo { width: 28px; height: 34px; border-radius: 5px; background: linear-gradient(145deg, #ffffff, #cfe3ff);
  position: relative; box-shadow: 0 4px 14px rgba(28,111,209,.5); }
.logo::before { content: ""; position: absolute; left: 5px; right: 5px; top: 7px; height: 3px; border-radius: 2px;
  background: #1f3a5f; box-shadow: 0 6px 0 #1f3a5f, 0 12px 0 #3d6fb0, 0 18px 0 #3d6fb0; }
.logo::after { content: ""; position: absolute; right: -6px; bottom: -6px; width: 16px; height: 16px;
  border-radius: 50%; background: linear-gradient(135deg, #2dd4bf, #0d9e8f); border: 2px solid #08162a; }
.brand b { color: #5fd8c9; }
header { position: absolute; top: 24px; left: 40px; right: 220px; }
.step { display: inline-flex; align-items: center; gap: 10px; font-size: 15px; font-weight: 700;
  letter-spacing: .08em; text-transform: uppercase; color: #7fd9cc; }
.step i { font-style: normal; width: 26px; height: 26px; border-radius: 50%; display: grid; place-items: center;
  background: linear-gradient(135deg, #2dd4bf, #1c6fd1); color: #fff; letter-spacing: 0; font-size: 14px; }
h1 { font-size: 38px; line-height: 1.1; letter-spacing: -.02em; margin-top: 8px; }
.sub { font-size: 19px; color: #b9cae6; margin-top: 8px; }
.frame { position: absolute; left: 40px; right: 40px; top: 160px; bottom: 28px; border-radius: 14px;
  overflow: hidden; background: #0c1526; box-shadow: 0 24px 60px rgba(0,0,0,.5), 0 0 0 1px rgba(127,217,204,.22),
  0 0 90px rgba(28,111,209,.25); }
.bar { height: 30px; background: #172338; display: flex; align-items: center; gap: 7px; padding: 0 12px; }
.bar span { width: 11px; height: 11px; border-radius: 50%; background: #ff5f57; }
.bar span:nth-child(2) { background: #febc2e; } .bar span:nth-child(3) { background: #28c840; }
.bar em { margin-left: 14px; font-style: normal; font-size: 12px; color: #8ea3c4; }
.term { position: absolute; top: 30px; left: 0; right: 0; bottom: 0; color: #e3ecfb;
  font: 15.5px/1.5 "SF Mono", Menlo, monospace; padding: 18px 26px; white-space: pre-wrap; }
.term .p { color: #5fd8c9; } .term .h { color: #fff; font-weight: 700; } .term .c { color: #7f93b4; }
.term .f { color: #ffc857; } .term .k { color: #8fb8ff; } .term .ok { color: #5fe0a0; } .term .bad { color: #ff7b7b; }
.cols { position: absolute; top: 30px; left: 0; right: 0; bottom: 0; display: flex; }
.cols > div { flex: 1; padding: 18px 26px; font: 14px/1.5 "SF Mono", Menlo, monospace; white-space: pre-wrap;
  color: #e3ecfb; }
.cols > div + div { border-left: 1px solid rgba(127,217,204,.2); }
.cols .t { font: 700 13px -apple-system, Arial, sans-serif; letter-spacing: .08em; text-transform: uppercase;
  color: #7fd9cc; margin-bottom: 12px; }
.note { position: absolute; bottom: 36px; right: 56px; font-size: 12px; color: #7f93b4; }
.center { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center;
  justify-content: center; text-align: center; padding: 0 120px; }
.center h1 { font-size: 64px; }
.center .sub { font-size: 24px; margin-top: 18px; max-width: 900px; line-height: 1.4; }
.chips { display: flex; flex-wrap: wrap; gap: 10px; justify-content: center; margin-top: 34px; }
.chips span { border: 1px solid rgba(127,217,204,.45); color: #d3f5ef; border-radius: 999px; padding: 7px 16px;
  font-size: 16px; background: rgba(13,158,143,.14); }
.big { transform: scale(2.6); margin-bottom: 44px; }
.cmd { margin-top: 34px; font: 20px "SF Mono", Menlo, monospace; background: rgba(0,0,0,.35);
  border: 1px solid rgba(255,255,255,.15); border-radius: 12px; padding: 14px 26px; color: #5fd8c9; }
"""

BRAND = '<div class="brand"><div class="logo"></div><span>resume<b>-kit</b></span></div>'
HIDDEN_BRAND = BRAND.replace('class="brand"', 'class="brand" style="display:none"')


def page(body: str) -> str:
    return f'<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body>{body}</body></html>'


def head(n: int, label: str, title: str, sub: str) -> str:
    return (f'<header><div class="step"><i>{n}</i>{label}</div><h1>{title}</h1>'
            f'<div class="sub">{sub}</div></header>{BRAND}')


def window(inner: str, title: str = "Terminal") -> str:
    return f'<div class="frame"><div class="bar"><span></span><span></span><span></span><em>{title}</em></div>{inner}</div>'


def color(text: str) -> str:
    """Escape a command's output and mark what matters: passes, failures, flagged lines, and the demo's gaps."""
    out = []
    for line in html.escape(text).splitlines():
        if re.search(r": ok$", line):
            line = re.sub(r"^(\S+): (ok)$", r'\1: <span class="ok">\2</span>', line)
        elif re.match(r"\s*(kubernetes: found|spills onto|.*real gap)", line):
            line = f'<span class="bad">{line}</span>'
        elif "✅" in line:
            line = line.replace("✅", '<span class="ok">✅</span>')
        line = re.sub(r"^(\w[\w-]*): $", r'<span class="bad">\1: FAIL</span>', line)
        out.append(line)
    return "\n".join(out)


def command(cmd: str) -> str:
    return f'<span class="p">$</span> <span class="h">{html.escape(cmd)}</span>'


def term_slide(n, label, title, sub, captured: dict, *, keep=None, note="", size=15.5):
    """A terminal showing a captured command and its output; `keep` picks which output lines to show."""
    lines = captured["output"].splitlines()
    if keep:
        lines = keep(lines)
    body = command(captured["command"]) + "\n" + color("\n".join(lines))
    inner = f'<div class="term" style="font-size:{size}px">{body}</div>'
    return page(head(n, label, title, sub) + window(inner) + (f'<div class="note">{note}</div>' if note else ""))


# What the library slide shows: lines of the example's own files, so the slide can't drift from them.
FACT_LINES = ["    paved_road: >-",
              "      Built a paved-road service template with secret scanning, SAST, and signed builds that 60 teams",
              "      adopted within two quarters"]
VARIANT_LINES = ["extends: base", "title: Acme Corp — Staff Detection Engineer", "skills: [detection, cloud_security, engineering, appsec]",
                 "roles:", "  northwind: [detection_as_code, ir_lead, iam_guardrails, paved_road]", "drop: [iam_diff]"]
GUARDRAIL_LINES = ["  - id: kubernetes", "    pattern: Kubernetes|\\bK8s\\b", "    why: Only tutorial-level Kubernetes; nothing production."]


def library_slide() -> str:
    left = ('<div class="t">profile.yaml: every fact, once, by id</div>' + html.escape("\n".join(FACT_LINES))
            + '\n\n<div class="t">guardrails.yaml: what must never appear</div>' + html.escape("\n".join(GUARDRAIL_LINES)))
    right = ('<div class="t">variants/acme.yaml: one version picks and orders ids</div>'
             + html.escape("\n".join(VARIANT_LINES)))
    inner = f'<div class="cols"><div>{left}</div><div>{right}</div></div>'
    return page(head(1, "One fact library", "Every fact lives in one place",
                     "A version picks facts by id. It never restates them, so a correction reaches every version.")
                + window(inner, "examples/content"))


def slides(caps: dict) -> list[tuple[str, str, str]]:
    """(file name, html, narration) for each slide, in order. `caps` is capture.py's output."""
    return [
        ("01-title",
         page(HIDDEN_BRAND + '<div class="center"><div class="logo big"></div><h1>resume-kit</h1>'
              '<div class="sub">Tailored resume versions from one fact library, with guardrails that keep them honest.'
              '</div><div class="chips"><span>.docx and .pdf</span><span>Page targets</span><span>Guardrails</span>'
              '<span>Gap scoring</span><span>MCP server</span></div></div>'),
         ("Tailoring a resume for every job leaves you with a dozen near-copies that drift apart. "
          "resume-kit keeps one library of facts, and builds each version from it.")),
        ("02-library", library_slide(),
         ("Every fact about your career lives once, in one file. A version picks facts by id, so a correction "
          "reaches all of them. Guardrails list the claims you've ruled out.")),
        ("03-draft",
         term_slide(2, "Draft from a posting", "Start a version from a job posting",
                    "It extends the closest version and picks the facts that share the posting's wording.",
                    caps["draft"], size=19),
         ("To start a version for a job, give resume draft the posting. It extends the closest version, "
          "and reorders and picks facts by how well they match. Nothing is reworded.")),
        ("04-guardrail",
         term_slide(3, "Guardrails", "A claim you ruled out fails the check",
                    "Here a summary says production Kubernetes. The rule says that was only tutorial-level.",
                    caps["check"], size=22),
         ("Say a version claims production Kubernetes, and your guardrails say that was tutorial-level. "
          "The check fails, and so does the build.")),
        ("05-pages",
         term_slide(4, "Page target", "Miss the page target, see what spilled",
                    "The build fails unless the PDF hits its target, and prints the text that ran over.",
                    caps["build"], size=22),
         ("The page target is checked too. This version runs onto a second page, so the build fails "
          "and prints exactly what spilled over, so you know what to trim.")),
        ("06-score",
         term_slide(5, "Score against a posting", "Gaps get sorted",
                    "A must-have the resume lacks, labelled a real gap when a guardrail says it is one.",
                    caps["score"], size=15.5, note="Output recorded from a local-model run on the example"),
         ("Score a version against a posting, and it lists the must-haves the resume doesn't show. "
          "When a gap matches a guardrail, it's labelled a real gap, not a wording problem to paper over.")),
        ("07-end",
         page(HIDDEN_BRAND + '<div class="center"><div class="step"><i>6</i>Also an MCP server</div>'
              '<h1 style="margin-top:18px">Never makes things up.</h1>'
              '<div class="sub">An AI assistant can draft, build and score versions through the same guardrails, '
              'and can never close a gap that a guardrail marks as real.</div>'
              '<div class="cmd">github.com/vinayvobbili/resume-kit</div></div>'),
         ("It's also an M C P server, so an AI assistant can tailor, build and score resumes through the same "
          "guardrails, without making things up. resume-kit is on GitHub.")),
    ]


# Kokoro's dictionary only knows the verb ("ri-ZOOM"), so the noun ("REZ-oo-may") is spelled out with misaki's own
# override, "[word](/phonemes/)". Applied in this order: plural, singular, then the name's hyphen.
RESUME_SOUND = "ɹˈɛzəmˌA"
PHONETIC = {r"\bresumes\b": f"[resumes](/{RESUME_SOUND}z/)",
            r"\bresume\b": f"[resume](/{RESUME_SOUND}/)",
            r"(?<=\))-kit\b": " kit",
            r"\bMCP\b": "M C P",
            r"\bPDF\b": "P D F"}

# The music bed and stings (`slidecast compose -o DIR` makes them), and how loud each plays.
AUDIO = {"music": ("music_bed.wav", {"volume": 0.3, "fade_in": 1.0, "fade_out": 3.0, "duck": True, "duck_db": 16}),
         "intro": ("intro_sting.wav", {"volume": 0.75}),
         "outro": ("outro_sting.wav", {"volume": 0.7})}


def build(out: Path, music: Path | None = None) -> dict:
    """Write slides/*.html and reel.yaml into `out`, which holds captures.json. The music bed and stings come
    from `music`, else from `out`; without them the reel has the voice only. Returns the reel's spec."""
    out = out.expanduser().resolve()
    (out / "slides").mkdir(exist_ok=True)
    caps = json.loads((out / "captures.json").read_text())
    entries = []
    for name, body, narration in slides(caps):
        (out / "slides" / f"{name}.html").write_text(body, encoding="utf-8")
        entries.append({"html_file": f"slides/{name}.html", "narration": narration, "tail_pad": 1.3})
    entries[0]["tail_pad"] = 1.0
    entries[-1]["tail_pad"] = 1.6
    spec = {"width": 1920, "height": 1080, "fps": 25,
            "tts": {"provider": "mlx", "voice": "af_heart",  # Kokoro in-process: pip install 'slidecast[mlx]'
                    "phonetic": PHONETIC}}
    where = (music or out).expanduser().resolve()
    missing = [name for name, _ in AUDIO.values() if not (where / name).is_file()]
    if music and missing:
        raise SystemExit(f"{where} has no {', '.join(missing)}: `slidecast compose -o {where}` makes them")
    if not missing:
        for key, (name, opts) in AUDIO.items():
            spec[key] = {"file": name if where == out else str(where / name), **opts}
    spec.update({"lead_in": 1.8, "loudness": -16, "slides": entries})
    (out / "reel.yaml").write_text(yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=120))
    return spec


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", nargs="?", type=Path, default=OUT, help=f"the demo's output folder (default: {OUT})")
    ap.add_argument("--music", type=Path, metavar="DIR",
                    help="the folder holding music_bed.wav, intro_sting.wav and outro_sting.wav")
    args = ap.parse_args()
    spec = build(args.out, args.music)
    print(f"Wrote {len(spec['slides'])} slides and {args.out / 'reel.yaml'}"
          + ("" if "music" in spec else " (no music: voice only)"))


if __name__ == "__main__":
    main()
