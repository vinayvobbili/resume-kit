import json
import shutil
import subprocess

import pytest
import yaml

from resume_kit import apply, facts
from resume_kit.content import ContentError, list_versions, load_profile, resolve


def write_variant(content, name, data):
    (content / "variants" / f"{name}.yaml").write_text(yaml.safe_dump(data, allow_unicode=True))


def test_example_versions():
    assert list_versions() == ["acme", "base"]


@pytest.mark.parametrize("version", ["base", "acme"])
def test_example_versions_resolve_and_pass_guardrails(version):
    spec = resolve(version)
    assert facts.check(spec) == []
    assert spec.pages == 1


def test_profile_ids_are_globally_unique(content):
    load_profile()
    profile = (content / "profile.yaml").read_text()
    (content / "profile.yaml").write_text(profile.replace("  gcih: GIAC", "  detection: GIAC"))
    with pytest.raises(ContentError, match="duplicate id 'detection'"):
        load_profile()


def test_extends_inherits_and_drop_removes_everywhere(content):
    write_variant(content, "t", {"extends": "acme", "output": "t", "drop": ["vuln_program", "sigma_lint", "gcih"]})
    spec, acme = resolve("t"), resolve("acme")
    assert spec.headline == acme.headline and spec.certs_inline
    assert spec.roles[1]["bullets"] == acme.roles[1]["bullets"][:-1]
    assert spec.open_source == []
    assert spec.certs == ["AWS Certified Security – Specialty"]
    assert "OPEN SOURCE" not in spec.text()


def test_role_override_only_touches_that_role(content):
    write_variant(content, "t", {"extends": "base", "output": "t", "roles": {"contoso": ["soc_triage"]}})
    spec, base = resolve("t"), resolve("base")
    assert len(spec.roles[1]["bullets"]) == 1
    assert spec.roles[0] == base.roles[0]


def test_posting_and_pages_resolve_relative_to_content(content):
    write_variant(content, "t", {"extends": "base", "output": "t", "pages": 2,
                                 "posting": "postings/acme-detection-engineer.md"})
    spec = resolve("t")
    assert spec.pages == 2
    assert spec.posting == content / "postings" / "acme-detection-engineer.md"


def test_a_version_does_not_inherit_its_parents_application(content):
    # Tailoring a resume for job B from job A's version: B's content starts as A's, but A's
    # posting, applied date, notes and title belong to A.
    write_variant(content, "a", {"extends": "base", "output": "a", "title": "Job A", "applied": "2026-01-02",
                                 "notes": "referred", "posting": "postings/acme-detection-engineer.md",
                                 "headline": "A headline"})
    write_variant(content, "b", {"extends": "a", "output": "b"})
    spec = resolve("b")
    assert spec.headline == "A headline"
    assert (spec.title, spec.posting, spec.meta) == ("b", None, {})


@pytest.mark.parametrize("data, message", [
    ({"extends": "base", "output": "t", "skills": ["nope"]}, "unknown skills id"),
    ({"extends": "base", "output": "t", "roles": {"northwind": ["soc_triage"]}}, "unknown roles.northwind"),
    ({"extends": "base", "output": "t", "roles": {"acme": []}}, "unknown role id"),
    ({"extends": "t", "output": "t"}, "extends cycle"),
    ({"headline": "x"}, "has no 'output'"),
])
def test_bad_versions_fail_loudly(content, data, message):
    write_variant(content, "t", data)
    with pytest.raises(ContentError, match=message):
        resolve("t")


@pytest.mark.parametrize("bad, rule", [
    ("Secured production Kubernetes clusters", "kubernetes"),
    ("CISSP", "cissp"),
    ("adopted by 40 teams", "stale-team-count"),
])
def test_forbidden_rules_catch_claims(bad, rule):
    text = resolve("base").text() + bad
    assert any(v.startswith(f"{rule}:") for v in facts.load().violations(text))


def test_required_rules_catch_missing_facts():
    text = resolve("base").text().replace("BS in Computer Science", "BS in Physics")
    assert [v.split(":")[0] for v in facts.load().violations(text)] == ["degree"]


def test_case_sensitive_rules(content):
    (content / "guardrails.yaml").write_text(yaml.safe_dump({"forbidden": [
        {"id": "go", "pattern": r"(?<![\w-])Go(?=[,;/)])", "why": "no Go", "case_sensitive": True}]}))
    rails = facts.load()
    assert rails.violations("Python, Go, SQL")
    assert not rails.violations("years ago, then")


def test_no_guardrails_file_means_no_rules(content):
    (content / "guardrails.yaml").unlink()
    assert facts.check(resolve("base")) == []


def test_bad_guardrail_pattern_is_reported(content):
    (content / "guardrails.yaml").write_text("forbidden:\n  - {id: broken, pattern: '(', why: x}\n")
    with pytest.raises(ContentError, match="broken"):
        facts.load()


def test_answers(content):
    assert apply.answers("defaults")["defaults"]["sms_opt_in"] is False
    with pytest.raises(ContentError, match="no section"):
        apply.answers("nope")


def test_missing_answers_file_explains_itself():
    with pytest.raises(ContentError, match="answers.example.yaml"):
        apply.answers()


@pytest.mark.parametrize("query, system", [
    ("greenhouse", "greenhouse"),
    ("https://jobs.ashbyhq.com/acme/123/application", "ashby"),
    ("acme.taleo.net", "taleo"),
    ("acme.eightfold.ai", "eightfold"),
    ("https://www.linkedin.com/jobs/view/1", "linkedin"),
])
def test_ats_lookup_by_name_or_url(query, system):
    pb = apply.ats_playbook(query)
    assert pb["system"] == system
    assert pb["quirks"] and pb["rules"] and "setNativeValue" in pb["helpers"]


def test_unknown_ats():
    with pytest.raises(ContentError):
        apply.ats_playbook("icims")


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
@pytest.mark.parametrize("name", list(apply.ats_playbook("lever")["helpers"]))
def test_ats_helpers_are_valid_javascript(name, tmp_path):
    # Helpers are pasted into a page as-is, so a syntax error only shows up mid-application.
    script = tmp_path / "helper.js"
    script.write_text(f"new Function({json.dumps(apply.ats_playbook('lever')['helpers'][name])});\n")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, check=False)
    assert run.returncode == 0, run.stderr


SRE_POSTING = """Staff Detection Engineer. You will own detection-as-code: Sigma rules, unit tests and log replay in CI.
Lead incident response and postmortems. Automate phishing triage with Python and SOAR. Splunk SPL a plus.
Kubernetes experience; you will run detections on Kubernetes."""


def test_draft_orders_confirmed_facts_by_relevance(content):
    from resume_kit import draft

    d = draft.draft("acme-staff", SRE_POSTING, title="Acme — Staff Detection Engineer", parent="base")
    data = yaml.safe_load(d.path.read_text())
    assert data["extends"] == "base" and data["posting"] == "postings/acme-staff.md"
    assert data["output"] == "Alex_Rivera_Resume_Acme_Staff"
    assert (content / "postings" / "acme-staff.md").read_text().startswith("Staff Detection Engineer")
    # Detection first; the parent's counts are kept.
    assert data["skills"][0] == "detection" and len(data["skills"]) == 4
    assert data["roles"]["northwind"][0] == "detection_as_code"
    assert data["roles"]["contoso"][0] == "phishing_automation"
    assert len(data["roles"]["northwind"]) == 5
    # Every id is from the profile, so the draft resolves and passes the guardrails as is.
    spec = resolve("acme-staff")
    assert facts.check(spec) == []
    assert spec.headline == resolve("base").headline
    # Terms the profile never mentions are reported (plurals folded, title words ignored).
    assert "kubernetes" in d.missing_terms
    assert not {"log", "postmortem", "splunk", "staff", "engineer"} & set(d.missing_terms)


def test_draft_picks_the_closest_parent_and_respects_its_drops(content):
    from resume_kit import draft

    d = draft.draft("detect2", SRE_POSTING)
    assert d.parent == "acme"
    assert "iam_diff" not in yaml.safe_load(d.path.read_text()).get("open_source", [])


def test_draft_refuses_to_overwrite_and_bad_names(content):
    from resume_kit import draft

    with pytest.raises(ContentError, match="exists"):
        draft.draft("acme", SRE_POSTING)
    with pytest.raises(ContentError, match="lowercase"):
        draft.draft("Acme Staff", SRE_POSTING)
    with pytest.raises(ContentError, match="empty"):
        draft.draft("x", "  ")


def test_draft_cli_reads_the_posting_from_stdin(content, monkeypatch, capsys):
    import io

    from resume_kit import cli

    monkeypatch.setattr("sys.stdin", io.StringIO(SRE_POSTING))
    assert cli.main(["draft", "from-stdin", "-", "--from", "base"]) == 0
    assert "Drafted" in capsys.readouterr().out
    assert (content / "variants" / "from-stdin.yaml").exists()


def test_draft_uses_one_wording_of_a_fact(content):
    from resume_kit import draft

    profile = (content / "profile.yaml").read_text()
    longer = ("    phishing_automation_long: >-\n      Automated phishing triage with a Python and SOAR pipeline, "
              "cutting median handling time from 25 to\n      6 minutes, with Splunk enrichment\n")
    (content / "profile.yaml").write_text(profile.replace("    vuln_program: >-", longer + "    vuln_program: >-"))
    d = draft.draft("phish", SRE_POSTING, parent="base")
    contoso = yaml.safe_load(d.path.read_text())["roles"]["contoso"]
    assert len({"phishing_automation", "phishing_automation_long"} & set(contoso)) == 1
    assert len(contoso) == 3
