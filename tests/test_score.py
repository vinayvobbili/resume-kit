import json
import sys
from pathlib import Path

import pytest

from resume_kit import score
from resume_kit.build import BuildResult
from resume_kit.content import ContentError

CANNED = {
    "resume": "resume.pdf",
    "flags": [],
    "matches": [{
        "job_id": "acme-detection-engineer",
        "job": {"title": "Staff Detection Engineer", "requirements": []},
        "gaps": ["Production Kubernetes security experience", "Hands-on AWS security experience"],
        "candidate_id": "resume", "source_file": "resume.pdf", "score": 71.4,
        "must_haves_met": 3, "must_haves_total": 5, "summary": "Strong detection engineering.",
        "flags": [],
        "requirements": [
            {"requirement_id": "python", "verdict": "met", "evidence": ["Python"], "reasoning": "",
             "kind": "must_have", "evidence_verified": True},
            {"requirement_id": "kubernetes", "verdict": "not_met", "evidence": [], "reasoning": "",
             "kind": "must_have", "evidence_verified": True},
        ],
    }],
    "errors": {},
}


@pytest.fixture
def fake_shortlist(tmp_path, monkeypatch):
    """A stand-in `shortlist` that records its argv and prints canned JSON."""
    argv_file = tmp_path / "argv.json"
    exe = tmp_path / "shortlist"
    exe.write_text(f"#!{sys.executable}\nimport json, sys\n"
                   f"json.dump(sys.argv[1:], open({str(argv_file)!r}, 'w'))\n"
                   f"print({json.dumps(json.dumps(CANNED))})\n")
    exe.chmod(0o755)
    monkeypatch.setenv("RESUME_KIT_SHORTLIST", str(exe))
    monkeypatch.setattr(score, "CACHE", tmp_path / "cache")
    pdf = tmp_path / "resume.pdf"

    def fake_build(version, out_dir, content=None):
        return BuildResult(version, pdf.with_suffix(".docx"), pdf, 1, 1, "")

    monkeypatch.setattr(score, "build", fake_build)
    return argv_file


def test_claude_takes_the_api_key_from_the_keychain_item_only_for_shortlist(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return type("R", (), {"returncode": 0 if cmd[3] == "anthropic" else 44,
                              "stdout": "sk-test\n" if cmd[3] == "anthropic" else ""})()

    monkeypatch.setattr(score.subprocess, "run", fake_run)
    assert score.claude_env("anthropic")["ANTHROPIC_API_KEY"] == "sk-test"
    assert calls == [["security", "find-generic-password", "-s", "anthropic", "-w"]]
    with pytest.raises(score.ScoreError, match="no API key in the keychain item 'other'"):
        score.claude_env("other")
    with pytest.raises(score.ScoreError, match="--keychain"):
        score.claude_env("")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-set")
    assert score.claude_env("anthropic")["ANTHROPIC_API_KEY"] == "sk-set" and len(calls) == 2


def test_scores_against_the_versions_own_posting(fake_shortlist, example_content):
    data = score.score("acme")
    argv = json.loads(fake_shortlist.read_text())
    assert argv[0] == "jobs"
    assert argv[2] == str(example_content / "postings" / "acme-detection-engineer.md")
    assert argv[-4:] == ["--format", "json", "--backend", "local"]
    assert data["matches"][0]["score"] == 71.4


def test_gaps_matching_a_guardrail_are_labeled_real(fake_shortlist):
    data = score.score("acme")
    notes = data["matches"][0]["gap_notes"]
    assert notes["Production Kubernetes security experience"][0].startswith("kubernetes:")
    assert notes["Hands-on AWS security experience"] == []
    text = score.to_text(data)
    assert "71/100, must-haves 3/5" in text
    assert "real gap, don't add it" in text
    assert "❌ kubernetes (must-have)" in text


def test_explicit_postings_override(fake_shortlist, tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    posting = tmp_path / "other.md"
    posting.write_text("# Other job")
    score.score("base", [posting], backend="claude")
    argv = json.loads(fake_shortlist.read_text())
    assert argv[2] == str(posting) and argv[-1] == "claude"


def test_version_without_posting_needs_one(fake_shortlist):
    with pytest.raises(ContentError, match="no posting"):
        score.score("base")


def test_missing_posting_file(fake_shortlist):
    with pytest.raises(ContentError, match="posting not found"):
        score.score("base", [Path("/nonexistent/job.md")])


def test_a_failing_backend_falls_back_to_the_next(fake_shortlist, monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    picky = tmp_path / "picky"  # only the local backend answers, the way claude or agy out of quota would fail
    picky.write_text(f"#!{sys.executable}\nimport sys\nif sys.argv[-1] != 'local':\n"
                     f"    sys.stderr.write(sys.argv[-1] + ' is out of quota'); sys.exit(1)\n"
                     f"print({json.dumps(json.dumps(CANNED))})\n")
    picky.chmod(0o755)
    monkeypatch.setenv("RESUME_KIT_SHORTLIST", str(picky))
    data = score.score("acme", backend="claude,agy,local")
    assert data["backend"] == "local" and list(data["failed_backends"]) == ["claude", "agy"]
    text = score.to_text(data)
    assert "with local" in text and "⚠️  agy failed, so it fell back" in text
    with pytest.raises(score.ScoreError, match=r"claude: shortlist failed \(1\):\nclaude is out of quota\nagy: "):
        score.score("acme", backend="claude,agy")
    with pytest.raises(score.ScoreError, match="backend must be one of"):
        score.score("acme", backend="claude,gpt")


def test_shortlist_failure_is_reported(fake_shortlist, monkeypatch, tmp_path):
    bad = tmp_path / "bad"
    bad.write_text(f"#!{sys.executable}\nimport sys\nsys.stderr.write('Error: model not found')\nsys.exit(1)\n")
    bad.chmod(0o755)
    monkeypatch.setenv("RESUME_KIT_SHORTLIST", str(bad))
    with pytest.raises(score.ScoreError, match="model not found"):
        score.score("acme")


def test_shortlist_not_installed(monkeypatch):
    monkeypatch.delenv("RESUME_KIT_SHORTLIST", raising=False)
    monkeypatch.setattr(score.shutil, "which", lambda _: None)
    with pytest.raises(score.ScoreError, match=r"pip install 'shortlist-ai\[local\]'"):
        score.find_shortlist()


def test_relative_content_dir_gives_absolute_posting(fake_shortlist, monkeypatch, example_content):
    monkeypatch.chdir(example_content.parent.parent)
    monkeypatch.setenv("RESUME_KIT_CONTENT", "examples/content")
    score.score("acme")
    posting = Path(json.loads(fake_shortlist.read_text())[2])
    assert posting.is_absolute() and posting.exists()


def test_unverified_evidence_lists_every_quote():
    match = {**CANNED["matches"][0], "gap_notes": {}, "gaps": [], "requirements": [
        {"requirement_id": "llm", "verdict": "partial", "evidence": ["LLM agents", "invented quote"],
         "reasoning": "", "kind": "must_have", "evidence_verified": False}]}
    text = score.to_text({"pdf": "r.pdf", "pages": 2, "flags": [], "matches": [match]})
    assert "🟡 llm (must-have) ⚠️ a quote was not found in the resume" in text
    assert "“LLM agents”" in text and "“invented quote”" in text


def test_brief_keeps_only_what_is_left_to_fix():
    match = {**CANNED["matches"][0], "gap_notes": {}, "gaps": ["kubernetes"], "requirements": [
        {"requirement_id": "llm", "verdict": "met", "evidence": ["LLM agents"],
         "reasoning": "", "kind": "must_have", "evidence_verified": True},
        {"requirement_id": "kubernetes", "verdict": "partial", "evidence": ["Docker"],
         "reasoning": "", "kind": "must_have", "evidence_verified": True}]}
    data = {"pdf": "r.pdf", "pages": 2, "flags": [], "matches": [match]}
    text = score.to_text(data, brief=True)
    assert "/100" in text and "    - kubernetes" in text
    assert "🟡 kubernetes (must-have) “Docker”" in text
    assert "llm" not in text and "Requirements not fully met:" in text
    assert "✅ llm" in score.to_text(data)


def test_names_the_failing_quote_when_shortlist_reports_it():
    match = {**CANNED["matches"][0], "gap_notes": {}, "gaps": [], "requirements": [
        {"requirement_id": "llm", "verdict": "partial", "evidence": ["LLM agents", "invented quote"],
         "reasoning": "", "kind": "must_have", "evidence_verified": False, "unverified_quotes": ["invented quote"]}]}
    text = score.to_text({"pdf": "r.pdf", "pages": 2, "flags": [], "matches": [match]})
    assert "“invented quote”  ← not found" in text
    assert "“LLM agents”\n" in text
