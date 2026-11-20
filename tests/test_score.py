import json
import sys
from datetime import date, datetime
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


def test_the_paid_claude_backend_is_never_in_a_chain(fake_shortlist, tmp_path):
    assert "claude" not in score.BACKENDS
    assert not any(e.startswith("claude") for e in score.DEFAULT_CHAIN)
    assert not any(e.startswith("claude") for e in score.configured_chain(tmp_path))
    for asked in ("claude", "claude:claude-sonnet-5-5", "claude,claude:model-a"):
        with pytest.raises(score.ScoreError, match="never used"):
            score.score("acme", backend=asked)
    assert not fake_shortlist.exists()  # shortlist was never even started


def test_claude_in_a_shared_backend_list_is_skipped_with_a_notice(fake_shortlist):
    data = score.score("acme", backend="claude,agy,local")  # the same list $RESUME_KIT_BACKEND holds
    assert data["backend"] == "agy" and data["skipped_backends"] == ["claude"]
    assert fake_shortlist.exists() and "claude" not in json.loads(fake_shortlist.read_text())
    assert "⚠️  skipped claude: the paid claude backend is never used for scoring" in score.to_text(data)


UNTIL = "claude:claude-sonnet-5-5 until 2026-12-20"


@pytest.fixture
def on(monkeypatch):
    """Sets the New York day the credit window is judged on."""
    def set_day(text):
        monkeypatch.setattr(score, "today_eastern", lambda now=None: date.fromisoformat(text))
    return set_day


@pytest.mark.parametrize("now, open_", [
    ("2026-12-19T23:59:00-05:00", True),    # the day before
    ("2026-12-20T00:00:00-05:00", False),   # the day itself
    ("2026-12-21T09:00:00-05:00", False),   # after
    ("2026-12-20T04:59:00+00:00", True),    # still the 19th in New York
    ("2026-12-20T05:00:00+00:00", False),
])
def test_a_credit_entry_is_open_before_its_day_and_closed_on_and_after_it(now, open_):
    assert score.credit_open(UNTIL, datetime.fromisoformat(now)) is open_


@pytest.mark.parametrize("entry", ["claude:claude-sonnet-5-5", "claude until 2026-12-20", "agy until 2026-12-20",
                                   "claude:claude-sonnet-5-5 until 2026-13-40", "claude:claude-sonnet-5-5 until soon"])
def test_only_a_claude_entry_with_a_model_and_a_real_date_can_be_open(entry):
    assert not score.credit_open(entry, datetime.fromisoformat("2026-11-19T12:00:00-05:00"))


def test_a_dated_claude_entry_before_its_day_is_used_first_and_asked_for_as_plain_claude(fake_shortlist, on):
    on("2026-11-19")
    data = score.score("acme", backend=f"agy,{UNTIL},local")
    argv = json.loads(fake_shortlist.read_text())
    assert argv[-4:] == ["--backend", "claude", "--model", "claude-sonnet-5-5"]
    assert data["backend"] == "claude:claude-sonnet-5-5" and data["skipped_backends"] == []


def test_a_claude_only_list_works_with_the_date_and_errors_without_it(fake_shortlist, on):
    on("2026-11-19")
    assert score.score("acme", backend=UNTIL)["backend"] == "claude:claude-sonnet-5-5"
    fake_shortlist.unlink()
    with pytest.raises(score.ScoreError, match="never used"):
        score.score("acme", backend="claude:claude-sonnet-5-5")
    assert not fake_shortlist.exists()


def test_a_dated_claude_entry_on_or_after_its_day_is_skipped_with_a_notice_and_alone_it_errors(fake_shortlist, on):
    on("2026-12-20")
    data = score.score("acme", backend=f"{UNTIL},agy,local")
    assert data["backend"] == "agy" and data["skipped_backends"] == [UNTIL]
    assert "claude" not in json.loads(fake_shortlist.read_text())
    assert f"⚠️  skipped {UNTIL}: its credit window ended" in score.to_text(data)
    with pytest.raises(score.ScoreError, match="never used"):
        score.score("acme", backend=UNTIL)


def test_the_chain_from_jobwatch_yaml_can_carry_a_dated_claude_entry(tmp_path, fake_shortlist, on):
    on("2026-11-19")
    (tmp_path / "jobwatch.yaml").write_text(
        f"scoring:\n  backend: agy\n  model: model-a\n  fallback:\n  - {UNTIL}\n  - local\n")
    assert score.configured_chain(tmp_path) == ["agy:model-a", UNTIL, "local"]


def test_the_chain_comes_from_the_content_dirs_jobwatch_yaml(tmp_path):
    (tmp_path / "jobwatch.yaml").write_text(
        "scoring:\n  backend: agy\n  model: model-a\n  fallback:\n  - agy:model-b\n  - local\n")
    assert score.configured_chain(tmp_path) == ["agy:model-a", "agy:model-b", "local"]
    (tmp_path / "jobwatch.yaml").write_text("boards: []\n")
    assert score.configured_chain(tmp_path) == list(score.DEFAULT_CHAIN)


def test_scores_against_the_versions_own_posting(fake_shortlist, example_content):
    data = score.score("acme")
    argv = json.loads(fake_shortlist.read_text())
    assert argv[0] == "jobs"
    assert argv[2] == str(example_content / "postings" / "acme-detection-engineer.md")
    assert argv[-6:] == ["--format", "json", "--backend", "agy", "--model", "claude-sonnet-5-5-high"]
    assert data["matches"][0]["score"] == 71.4


def test_an_agy_model_out_of_quota_falls_to_the_next_model_then_local(fake_shortlist, monkeypatch, tmp_path):
    quota = tmp_path / "quota"  # exit 3 / RESOURCE_EXHAUSTED for every model but the second one and local
    quota.write_text(f"#!{sys.executable}\nimport sys\na = sys.argv\nm = a[a.index('--model') + 1] if '--model' in a else ''\n"
                     f"if a[a.index('--backend') + 1] == 'agy' and m != 'model-b':\n"
                     f"    sys.stderr.write('RESOURCE_EXHAUSTED: ' + m); sys.exit(3)\n"
                     f"print({json.dumps(json.dumps(CANNED))})\n")
    quota.chmod(0o755)
    monkeypatch.setenv("RESUME_KIT_SHORTLIST", str(quota))
    data = score.score("acme", backend="agy:model-a,agy:model-b,local")
    assert data["backend"] == "agy:model-b" and list(data["failed_backends"]) == ["agy:model-a"]
    assert "RESOURCE_EXHAUSTED: model-a" in data["failed_backends"]["agy:model-a"]
    data = score.score("acme", backend="agy:model-a,agy:model-c,local")
    assert data["backend"] == "local" and list(data["failed_backends"]) == ["agy:model-a", "agy:model-c"]


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
    posting = tmp_path / "other.md"
    posting.write_text("# Other job")
    score.score("base", [posting], backend="local")
    argv = json.loads(fake_shortlist.read_text())
    assert argv[2] == str(posting) and argv[-1] == "local"


def test_version_without_posting_needs_one(fake_shortlist):
    with pytest.raises(ContentError, match="no posting"):
        score.score("base")


def test_missing_posting_file(fake_shortlist):
    with pytest.raises(ContentError, match="posting not found"):
        score.score("base", [Path("/nonexistent/job.md")])


def test_a_failing_backend_falls_back_to_the_next(fake_shortlist, monkeypatch, tmp_path):
    picky = tmp_path / "picky"  # only the local backend answers, the way agy out of quota would fail
    picky.write_text(f"#!{sys.executable}\nimport sys\nif sys.argv[-1] != 'local':\n"
                     f"    sys.stderr.write(sys.argv[-1] + ' is out of quota'); sys.exit(1)\n"
                     f"print({json.dumps(json.dumps(CANNED))})\n")
    picky.chmod(0o755)
    monkeypatch.setenv("RESUME_KIT_SHORTLIST", str(picky))
    data = score.score("acme", backend="agy,local")
    assert data["backend"] == "local" and list(data["failed_backends"]) == ["agy"]
    text = score.to_text(data)
    assert "with local" in text and "⚠️  agy failed, so it fell back: shortlist failed (1): agy is out of quota" in text
    with pytest.raises(score.ScoreError, match=r"agy: shortlist failed \(1\):\nagy is out of quota"):
        score.score("acme", backend="agy")
    with pytest.raises(score.ScoreError, match="backend must be one of"):
        score.score("acme", backend="agy,gpt")


def test_a_failure_said_on_stdout_is_shown(fake_shortlist, monkeypatch, tmp_path):
    # shortlist --format json can report its error on stdout with an empty stderr: the reason must still show
    quiet = tmp_path / "quiet"
    quiet.write_text(f"#!{sys.executable}\nimport sys\nif sys.argv[-1] == 'local':\n    sys.exit(1)\n"
                     "print('{\"error\": \"quota is used up\"}'); sys.exit(1)\n")
    quiet.chmod(0o755)
    monkeypatch.setenv("RESUME_KIT_SHORTLIST", str(quiet))
    with pytest.raises(score.ScoreError, match=r"(?s)agy: shortlist failed \(1\):\n.*quota is used up.*"
                                               r"local: shortlist failed \(1\):\n\(it said nothing\)"):
        score.score("acme", backend="agy,local")


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
