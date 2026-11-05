"""The demo video's scripts (scripts/demo): the slides quote real files and name real commands, and no path from the
machine that built the video leaks into a slide."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

from resume_kit.content import EXAMPLE_CONTENT

DEMO = Path(__file__).resolve().parents[1] / "scripts" / "demo"


def load(name):
    spec = importlib.util.spec_from_file_location(f"demo_{name}", DEMO / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


capture, build = load("capture"), load("build")


def test_slide_excerpts_are_lines_of_the_example_files():
    profile = (EXAMPLE_CONTENT / "profile.yaml").read_text().splitlines()
    guardrails = (EXAMPLE_CONTENT / "guardrails.yaml").read_text().splitlines()
    acme = (EXAMPLE_CONTENT / "variants" / "acme.yaml").read_text().splitlines()
    assert set(build.FACT_LINES) <= set(profile)
    assert set(build.GUARDRAIL_LINES) <= set(guardrails)
    assert set(build.VARIANT_LINES) <= {line.split("   #")[0].rstrip() for line in acme}


def test_steps_name_real_subcommands_and_fixtures():
    cli = (Path(__file__).resolve().parents[1] / "resume_kit" / "cli.py").read_text()
    for _key, shown, args, _may_fail in capture.STEPS:
        assert f'"{args[0]}"' in cli, shown
        assert shown.startswith(f"resume {args[0]}")
    assert (capture.FIXTURES / "variants" / "acme-everything.yaml").is_file()
    assert capture.SCORE_COMMAND == "resume score acme"
    assert "Production Kubernetes" in capture.SCORE_OUTPUT.read_text()


def test_prepare_adds_fixtures_and_leaves_the_example_alone(tmp_path):
    before = (EXAMPLE_CONTENT / "profile.yaml").read_text()
    content = capture.prepare(tmp_path)
    assert (EXAMPLE_CONTENT / "profile.yaml").read_text() == before
    assert (content / "variants" / "globex-k8s.yaml").is_file()
    profile = yaml.safe_load((content / "profile.yaml").read_text())
    bullets = {k for role in profile["roles"] for k in role["bullets"]}
    picked = yaml.safe_load((content / "variants" / "acme-everything.yaml").read_text())["roles"]
    assert {i for ids in picked.values() for i in ids} <= bullets


def test_clean_drops_this_machines_paths(tmp_path):
    text = f"wrote {tmp_path}/resumes/a.pdf and /private{tmp_path.resolve()}/x"
    assert "/Users" not in capture.clean(text, tmp_path)
    assert capture.clean(f"wrote {tmp_path}/resumes/a.pdf", tmp_path) == "wrote resumes/a.pdf"


def test_build_writes_slides_and_reel_with_the_agreed_settings(tmp_path):
    caps = {k: {"command": f"resume {k}", "output": "acme: ok\n  <b>", "ok": True}
            for k in ("list", "draft", "check", "build", "score")}
    (tmp_path / "captures.json").write_text(json.dumps(caps))
    spec = build.build(tmp_path)
    assert len(spec["slides"]) == 7
    assert spec["tts"]["voice"] == "af_heart" and spec["tts"]["provider"] == "mlx"
    assert spec["loudness"] == -16
    assert "music" not in spec  # no bed in the folder: voice only
    for entry in spec["slides"]:
        assert (tmp_path / entry["html_file"]).is_file()
    assert "&lt;b&gt;" in (tmp_path / "slides" / "03-draft.html").read_text()


def test_build_music_settings(tmp_path):
    caps = {k: {"command": k, "output": "", "ok": True} for k in ("list", "draft", "check", "build", "score")}
    (tmp_path / "captures.json").write_text(json.dumps(caps))
    for name in ("music_bed.wav", "intro_sting.wav", "outro_sting.wav"):
        (tmp_path / name).write_bytes(b"")
    spec = build.build(tmp_path)
    assert spec["music"]["volume"] == 0.3 and spec["music"]["duck_db"] == 16
    assert all(e["tail_pad"] == 1.3 for e in spec["slides"][1:-1])


def test_missing_music_dir_is_an_error(tmp_path):
    caps = {k: {"command": k, "output": "", "ok": True} for k in ("list", "draft", "check", "build", "score")}
    (tmp_path / "captures.json").write_text(json.dumps(caps))
    with pytest.raises(SystemExit):
        build.build(tmp_path, music=tmp_path / "nope")
