import json
import shutil
import subprocess

import pytest
import yaml

from resume_kit import apply, cli, facts
from resume_kit.content import ContentError, list_versions, load_profile, resolve


def write_variant(content, name, data):
    (content / "variants" / f"{name}.yaml").write_text(yaml.safe_dump(data, allow_unicode=True))


def test_example_versions():
    assert list_versions() == ["acme", "base"]


def test_facts_lists_every_id_and_numbers_a_versions_picks(capsys):
    assert cli.main(["facts", "northwind", "--version", "acme", "--width", "40"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("roles.northwind: Senior Security Engineer, Northwind Traders")
    assert any(line.startswith("   1 detection_as_code: Moved 300+") and line.endswith("…") for line in out)
    assert any(line.startswith("   3 iam_guardrails: ") for line in out)
    assert any(line.startswith("   - ") for line in out)  # a fact acme leaves out
    assert cli.main(["facts"]) == 0
    assert {line.split(":")[0] for line in capsys.readouterr().out.splitlines() if not line.startswith(" ")} \
        >= {"skills", "roles.northwind", "open_source", "certs"}


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


def test_drop_can_leave_a_role_off_and_undated_hides_its_dates(content):
    write_variant(content, "t", {"extends": "base", "output": "t", "drop": ["contoso"], "undated": ["northwind"]})
    spec, base = resolve("t"), resolve("base")
    assert [r["org"] for r in spec.roles] == [base.roles[0]["org"]]
    assert spec.roles[0]["dates"] == "" and spec.roles[0]["bullets"] == base.roles[0]["bullets"]
    assert f"{base.roles[0]['title']}  |  {base.roles[0]['org']}\n" in spec.text()
    write_variant(content, "u", {"extends": "base", "output": "u", "undated": ["acme"]})
    with pytest.raises(ContentError, match="unknown role id"):
        resolve("u")


def test_undated_education_leaves_graduation_dates_off(content):
    assert resolve("base").education[0]["degree"] == "BS in Computer Science, 2017"
    write_variant(content, "t", {"extends": "base", "output": "t", "undated_education": True})
    write_variant(content, "t2", {"extends": "t", "output": "t2"})
    for v in ("t", "t2"):
        spec = resolve(v)
        assert spec.education[0] == {"school": "University of Colorado Boulder", "degree": "BS in Computer Science"}
        assert "2017" not in spec.text().split("EDUCATION")[1]


def test_hide_contact_leaves_matching_entries_off_and_rejects_typos(content):
    assert "github.com/alex-rivera-example" in resolve("base").contact
    write_variant(content, "t", {"extends": "base", "output": "t", "hide_contact": ["github.com"]})
    write_variant(content, "t2", {"extends": "t", "output": "t2"})
    for v in ("t", "t2"):
        spec = resolve(v)
        assert spec.contact == ["alex.rivera@example.com", "+1 (555) 010-0199", "Denver, CO (Remote)"]
        assert "github.com" not in spec.text().splitlines()[2]
    write_variant(content, "u", {"extends": "base", "output": "u", "hide_contact": ["gitlab.com"]})
    with pytest.raises(ContentError, match="matches no contact entry"):
        resolve("u")


def test_education_gpa_follows_the_dates(content):
    profile = yaml.safe_load((content / "profile.yaml").read_text())
    profile["education"][0]["gpa"] = "3.9"
    (content / "profile.yaml").write_text(yaml.safe_dump(profile, allow_unicode=True))
    assert resolve("base").education[0]["degree"] == "BS in Computer Science, 2017 (GPA 3.9)"
    write_variant(content, "t", {"extends": "base", "output": "t", "undated_education": True})
    assert resolve("t").education[0]["degree"] == "BS in Computer Science (GPA 3.9)"


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


def test_waive_skips_a_required_rule_but_never_a_forbidden_one(content):
    (content / "guardrails.yaml").write_text(
        "forbidden:\n  - {id: k8s, pattern: Kubernetes, why: tutorial only}\n"
        "required:\n  - {id: gh, pattern: github\\.com, why: header link}\n")
    write_variant(content, "t", {"extends": "base", "output": "t", "hide_contact": ["github.com"]})
    assert facts.check(resolve("t")) == ["gh: missing (header link)"]
    write_variant(content, "t", {"extends": "base", "output": "t", "hide_contact": ["github.com"], "waive": ["gh"]})
    assert facts.check(resolve("t")) == [] and facts.check(resolve("t"), reuse=True) == []
    write_variant(content, "t2", {"extends": "t", "output": "t2"})  # a waiver is the version's own, not inherited
    assert facts.check(resolve("t2")) == ["gh: missing (header link)"]
    write_variant(content, "t3", {"extends": "base", "output": "t3", "waive": ["k8s"]})
    assert facts.check(resolve("t3")) == ["waive: 'k8s' is not a required rule"]


def test_case_sensitive_rules(content):
    (content / "guardrails.yaml").write_text(yaml.safe_dump({"forbidden": [
        {"id": "go", "pattern": r"(?<![\w-])Go(?=[,;/)])", "why": "no Go", "case_sensitive": True}]}))
    rails = facts.load()
    assert rails.violations("Python, Go, SQL")
    assert not rails.violations("years ago, then")


def test_since_skips_versions_applied_before_the_correction(content):
    (content / "guardrails.yaml").write_text(
        "forbidden:\n  - {id: cissp, pattern: CISSP, why: not certified, since: 2026-10-13}\n")
    rails = facts.load()
    assert rails.violations("CISSP")  # not applied yet: the rule holds
    assert rails.violations("CISSP", "2026-10-13")
    assert not rails.violations("CISSP", "2026-10-01")  # sent before the fact was corrected


def test_a_version_sent_again_is_held_to_every_rule(content, capsys):
    (content / "guardrails.yaml").write_text(
        "forbidden:\n  - {id: cissp, pattern: CISSP, why: not certified, since: 2026-10-13}\n")
    variant = content / "variants" / "base.yaml"
    variant.write_text(variant.read_text().replace("Security engineer with", "CISSP security engineer with")
                       + "applied: 2026-10-01\n")
    assert facts.check(resolve("base")) == []  # the record of what was sent checks clean
    assert facts.check(resolve("base"), reuse=True)[0].startswith("cissp: found ['CISSP']")
    assert cli.main(["check", "base"]) == 0
    assert cli.main(["check", "--reuse", "base"]) == 1 and "cissp" in capsys.readouterr().out


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
    ("https://careers-acme.icims.com/jobs/1/job", "icims"),
    ("https://acme.avature.net/careers/JobDetail/1", "avature"),
    ("https://jobs.smartrecruiters.com/Acme/744000000000000-engineer", "smartrecruiters"),
])
def test_ats_lookup_by_name_or_url(query, system):
    pb = apply.ats_playbook(query)
    assert pb["system"] == system
    assert pb["quirks"] and pb["rules"] and "setNativeValue" in pb["helpers"]


def test_unknown_ats():
    with pytest.raises(ContentError):
        apply.ats_playbook("successfactors")


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


@pytest.mark.parametrize("hides", [{"drop": ["iam_diff", "contoso"]}, {"undated": ["contoso"]}])
def test_draft_never_picks_a_parent_that_hides_work_history(content, hides):
    from resume_kit import draft

    acme = yaml.safe_load((content / "variants" / "acme.yaml").read_text())
    write_variant(content, "acme", {**acme, **hides})
    assert draft.draft("detect3", SRE_POSTING).parent == "base"  # acme reads closer, but leaves a role short
    assert draft.draft("detect4", SRE_POSTING, parent="acme").parent == "acme"  # still yours to choose


def test_draft_skips_facts_a_guardrail_forbids(content):
    from resume_kit import draft

    rails = content / "guardrails.yaml"
    rails.write_text(rails.read_text().replace("required:", (
        "  - id: retired-replay\n    pattern: replay against 30 days\n"
        "    why: The replay harness was retired.\n\nrequired:")))
    d = draft.draft("no-replay", SRE_POSTING, parent="base")
    northwind = yaml.safe_load(d.path.read_text())["roles"]["northwind"]
    assert "detection_as_code" not in northwind and len(northwind) == 4  # the rest of the role, not a stand-in
    assert d.forbidden == ["detection_as_code"] and "a guardrail forbids: detection_as_code" in d.summary()
    assert facts.check(resolve("no-replay")) == []


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


def test_trace_backs_each_summary_claim_with_facts(capsys):
    assert cli.main(["trace", "base", "acme"]) == 0
    out = capsys.readouterr().out
    assert "base: 5 claims, 0 flagged" in out and "backed by: about.years" in out


def test_trace_flags_a_claim_no_fact_backs(content, capsys):
    """A claim nobody wrote a guardrail for still shows: the words and numbers no fact has."""
    path = content / "variants" / "acme.yaml"
    path.write_text(path.read_text().replace(
        "and led incident\n  response for credential-stuffing and leaked-key events.",
        "and led incident\n  response for credential-stuffing and leaked-key events. Stayed with each team until "
        "the tool was in daily use by 500+ engineers."))
    assert cli.main(["trace", "acme", "--flagged"]) == 1
    out = capsys.readouterr().out
    assert "acme: 5 claims, 1 flagged" in out
    assert "!!" in out and "Stayed with each team" in out and "500+" in out and "daily" in out


def test_trace_text_checks_a_letter_but_not_its_greeting_or_signature(tmp_path, capsys):
    letter = tmp_path / "letter.md"
    letter.write_text(
        "Dear Acme hiring team,\n\n"
        "I automated phishing triage with a Python and SOAR pipeline, cutting median handling time from 25 to 6 "
        "minutes. sigma-lint, my Sigma rule linter, runs in CI for detection teams. I also managed a team of 40 "
        "engineers at a hospital.\n\n"
        "Thank you for your time.\n\n"
        "Alex Rivera\nalex.rivera@example.com · +1 (555) 010-0199\n")
    assert cli.main(["trace", "--text", str(letter)]) == 1
    out = capsys.readouterr().out
    assert f"{letter}: 3 claims, 1 flagged" in out
    assert "[letter] sigma-lint, my Sigma rule linter" in out
    assert "ok" in out and "!!" in out and "40" in out and "hospital" in out
    assert "Dear" not in out and "Thank you" not in out and "555" not in out
