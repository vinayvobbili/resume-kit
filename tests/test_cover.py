import shutil
from types import SimpleNamespace

import pytest
from test_content import write_variant

from resume_kit import cover as cover_mod
from resume_kit.build import BuildError, BuildResult, build, page_text
from resume_kit.cli import main
from resume_kit.content import ContentError
from resume_kit.facts import Rule

NAME = "Alex Rivera"
CONTACT = ["alex.rivera@example.com", "Denver, CO (Remote)"]


def parse(markdown, **kw):
    return cover_mod.parse(markdown, NAME, CONTACT, **kw)


def test_a_letter_splits_into_greeting_paragraphs_and_closing():
    letter = parse("Dear Globex Team,\n\nFirst paragraph\nwrapped over two lines.\n\nSecond.\n\nWarm regards,\nAlex Rivera\n")
    assert letter.greeting == "Dear Globex Team,"
    assert letter.paragraphs == ["First paragraph wrapped over two lines.", "Second."]
    assert letter.closing == "Warm regards,"


def test_a_name_alone_at_the_end_is_the_sign_off_and_the_closing_defaults():
    letter = parse("Hello Initech,\n\nBody.\n\nThank you for your time.\n\nAlex\n")
    assert letter.paragraphs == ["Body.", "Thank you for your time."]
    assert letter.closing == "Sincerely,"


def test_a_letter_without_a_greeting_gets_one_and_to_replaces_it():
    assert parse("Body.\n").greeting == "Dear Hiring Team,"
    assert parse("Body.\n", to="Umbrella Recruiting").greeting == "Dear Umbrella Recruiting,"
    assert parse("Dear Globex,\n\nBody.\n", to="Initech").greeting == "Dear Initech,"


def test_a_first_line_heading_is_the_subject():
    letter = parse("# Staff Engineer, Req 42\n\nDear Globex,\n\nBody.\n")
    assert letter.subject == "Staff Engineer, Req 42"
    assert letter.greeting == "Dear Globex," and letter.paragraphs == ["Body."]


def test_a_last_paragraph_that_says_something_stays():
    assert parse("Dear Globex,\n\nFirst.\n\nThanks, and I look forward to it.\n").paragraphs == [
        "First.", "Thanks, and I look forward to it."]


def test_an_empty_letter_is_an_error():
    with pytest.raises(ContentError, match="no paragraphs"):
        parse("Dear Globex,\n\nSincerely,\nAlex Rivera\n")


def test_a_letter_is_found_in_the_content_letters_folder(content):
    assert cover_mod.find("acme-detection-engineer", content) == content / "letters" / "acme-detection-engineer.md"
    with pytest.raises(ContentError, match="letter not found"):
        cover_mod.find("nope", content)


def test_a_letter_that_trips_a_guardrail_is_refused(content, tmp_path):
    letter = tmp_path / "k8s.md"
    letter.write_text("Dear Globex,\n\nI ran Kubernetes clusters in production.\n")
    with pytest.raises(BuildError, match="kubernetes"):
        cover_mod.cover(letter, tmp_path / "out", content=content)
    assert not (tmp_path / "out").exists()


TERRAFORM = (Rule("terraform", r"\bTerraform\b", "No production Terraform to claim."),)


@pytest.mark.parametrize("sentence", [
    "I have not run Terraform in production.",
    "I haven't used Terraform at work.",
    "My work runs on-prem rather than on Terraform-managed clouds.",
    "I have never touched Terraform.",
    "I have no hands-on Terraform.",
    "I did not write the Terraform modules, though I reviewed them.",
    "I would learn Terraform instead of guessing.",
])
def test_a_sentence_that_denies_a_forbidden_term_passes_and_is_reported(sentence):
    assert cover_mod.check(f"Dear Globex,\n\nFine work. {sentence} More text.", TERRAFORM) == (
        [], [f"disclaimer, allowed: terraform: {sentence}"])


@pytest.mark.parametrize("sentence", [
    "I run Terraform in production.",
    "I have not only run Terraform but Kubernetes.",
    "I have not just used Terraform, I wrote its providers.",
    "I have run Terraform. I have not run Kubernetes.",  # the cue is in the other sentence
])
def test_a_plain_claim_still_fails(sentence):
    problems, notes = cover_mod.check(sentence, TERRAFORM)
    assert len(problems) == 1 and problems[0].startswith("terraform: found ['Terraform']") and notes == []


def test_a_denied_term_and_a_claimed_one_in_the_same_letter(content, tmp_path):
    letter = tmp_path / "mixed.md"
    letter.write_text("Dear Globex,\n\nI have not run Kubernetes in production. I hold a CISSP.\n")
    with pytest.raises(BuildError, match="cissp") as e:
        cover_mod.cover(letter, tmp_path, content=content)
    assert "kubernetes" not in str(e.value)


def test_cover_returns_the_disclaimers_and_the_summary_prints_them(content, tmp_path, monkeypatch):
    monkeypatch.setattr(cover_mod, "typeset", lambda letter, *a: BuildResult("t", tmp_path / "t.docx", tmp_path / "t.pdf",
                                                                             1, 1, ""))
    letter = tmp_path / "k8s.md"
    letter.write_text("Dear Globex,\n\nMy work runs on-prem rather than on Kubernetes.\n")
    result = cover_mod.cover(letter, tmp_path, content=content)
    assert result.notes == ["disclaimer, allowed: kubernetes: My work runs on-prem rather than on Kubernetes."]
    assert result.notes[0] in result.summary()


def test_a_resume_build_gets_no_such_leniency(content, tmp_path):
    variant = content / "variants" / "base.yaml"
    variant.write_text(variant.read_text().replace("Security engineer with", "I have not run Kubernetes; security engineer with"))
    with pytest.raises(BuildError, match="kubernetes"):
        build("base", tmp_path)


@pytest.fixture
def typeset_stub(monkeypatch):
    """Capture the letter instead of rendering it, for tests that only look at what would be rendered."""
    seen = []
    monkeypatch.setattr(cover_mod, "typeset", lambda letter, *a: seen.append(letter) or SimpleNamespace(fill=0))
    return seen


def test_required_resume_facts_are_not_demanded_of_a_letter(content, tmp_path, typeset_stub):
    letter = tmp_path / "ok.md"
    letter.write_text("Dear Globex,\n\nI like detection work.\n")
    cover_mod.cover(letter, tmp_path, content=content)  # the example's required degree line isn't in it
    assert len(typeset_stub) == 1


def test_the_letterhead_is_the_profile_name_and_contact_or_a_versions(content, tmp_path, typeset_stub):
    write_variant(content, "t", {"extends": "base", "output": "t", "hide_contact": ["github.com"]})
    letter = tmp_path / "ok.md"
    letter.write_text("Dear Globex,\n\nBody.\n\nSincerely,\nAlex Rivera\n")
    cover_mod.cover(letter, tmp_path, content=content)
    cover_mod.cover(letter, tmp_path, version="t", content=content)
    plain, hidden = typeset_stub
    assert plain.name == hidden.name == "Alex Rivera"
    assert any("github.com" in c for c in plain.contact) and not any("github.com" in c for c in hidden.contact)
    assert plain.to_render_json()["contact"] == "  |  ".join(plain.contact)


@pytest.mark.render
@pytest.mark.skipif(not all(shutil.which(t) for t in ("node", "soffice", "pdfinfo", "pdftotext")),
                    reason="needs node, LibreOffice, and poppler")
class TestRendered:
    def test_the_letter_renders_to_one_page_with_the_resume_letterhead(self, content, tmp_path):
        result = cover_mod.cover("acme-detection-engineer", tmp_path, name="Alex_Rivera_Cover_Acme", content=content)
        assert result.ok and result.docx.name == "Alex_Rivera_Cover_Acme.docx" and result.pdf.exists()
        text = page_text(result.pdf, 1)
        head = " ".join(text.split("Dear Acme Detection Team,")[0].split())
        assert head.startswith("Alex Rivera alex.rivera@example.com | +1 (555) 010-0199 | Denver, CO (Remote)")
        assert "moved 300+ detections to detection-as-code" in " ".join(text.split())
        assert text.rstrip().endswith("Sincerely,\n\nAlex Rivera") or text.rstrip().endswith("Alex Rivera")

    def test_a_long_letter_warns_it_spills(self, tmp_path):
        letter = tmp_path / "long.md"
        letter.write_text("Dear Globex,\n\n" + "\n\n".join(["A paragraph about detection work. " * 20] * 6))
        result = cover_mod.cover(letter, tmp_path / "out")
        assert not result.ok and "spills onto page 2" in result.summary()

    def test_cli_renders_a_letter_in_the_content_folder(self, content, tmp_path, capsys):
        letter = content / "letters" / "acme-detection-engineer.md"
        assert main(["--content", str(content), "cover", str(letter), "--out", str(tmp_path), "--to", "Initech"]) == 0
        assert "-> " + str(tmp_path / "acme-detection-engineer.pdf") in capsys.readouterr().out
        assert "Dear Initech," in page_text(tmp_path / "acme-detection-engineer.pdf", 1)
