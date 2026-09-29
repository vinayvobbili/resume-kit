# resume-kit

**Tailored resume versions from one fact library, with guardrails that keep them honest.**

You keep every confirmed fact about your career in one file. Each job gets a short version file that picks and orders those facts, with its own headline and summary. resume-kit renders a version to `.docx` and `.pdf` and checks that it hits your page target. It won't build anything that breaks one of your guardrails: claims you've ruled out, or facts that must always appear. It can also score a version against a job posting with [shortlist-ai](https://github.com/vinayvobbili/shortlist-ai), the way a screener would read it.

All of this is also available as an MCP server, so an AI assistant can tailor, build, and score resumes for you without making things up.

## Why

Tailoring a resume for every job tends to produce a dozen near-copies that drift apart. A number gets corrected in one copy but not the others. A claim you walked back reappears. Page 3 appears without anyone noticing. With resume-kit:

- **Each fact lives in one place.** Versions refer to facts by id and never restate them, so a correction reaches every version.
- **Guardrails fail the build.** `guardrails.yaml` lists claims that must never appear (with the reason) and facts that must. They're checked on every build, which also makes it safe to let an AI assistant write versions.
- **The page count is checked.** The build fails unless the PDF hits its target, and it prints the text that spilled over, so you know what to trim.
- **Gaps get sorted.** `resume score` lists the must-haves a posting asks for that the resume doesn't show. A gap that matches a guardrail is labeled as a real gap, not a wording problem to paper over.

## Setup

```sh
git clone https://github.com/vinayvobbili/resume-kit && cd resume-kit
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
npm install                                          # docx-js, used by the renderer
brew install --cask libreoffice && brew install poppler   # PDF conversion and page checks
```

Try it on the bundled example (a fictional candidate):

```sh
resume --content examples/content build --all --out /tmp/resumes
```

## Your content

Content lives **outside this repo**, so your personal data never ends up in it:

```sh
cp -R examples/content ~/resume-content                 # then replace the facts with yours
mkdir -p ~/.config/resume-kit && ln -s ~/resume-content ~/.config/resume-kit/content
```

resume-kit looks for content in the `--content` flag, then `$RESUME_KIT_CONTENT`, then `~/.config/resume-kit/content`. If none of those exist, it falls back to the example and says so. Keep your content in its own private repo if you want history. Keep `answers.yaml` out of version control.

```
profile.yaml          every fact that can appear, keyed by id; `pages:` sets the page target
variants/<name>.yaml  one resume version: headline, summary, and which ids in what order
guardrails.yaml       forbidden claims and required facts, each with its reason
postings/             saved job descriptions, for `resume score`
answers.yaml          your standard application-form answers (copy answers.example.yaml)
```

A tailored version inherits the resume content it doesn't set. What belongs to one application (`title`, `output`, `posting`, `applied`, `notes`) is never inherited, so a version tailored from another doesn't pick up its posting or applied date:

```yaml
# variants/acme.yaml
extends: base
title: Acme Corp — Staff Detection Engineer
output: Alex_Rivera_Resume_Acme_Detection
posting: postings/acme-detection-engineer.md
headline: Staff Detection Engineer  •  Detection-as-Code, Threat Hunting & Incident Response
summary: >-
  ...
skills: [detection, cloud_security, engineering, appsec]
roles:
  northwind: [detection_as_code, ir_lead, iam_guardrails, paved_road]   # only the roles you change
drop: [iam_diff]                                                          # remove ids from any list
```

To start a tailored version from a job posting, let resume-kit draft it:

```sh
resume draft acme-sre posting.md --title "Acme — Senior SRE"   # or: some-command | resume draft acme-sre -
```

The draft extends the existing version that reads most like the posting and keeps its shape (how many skills, bullets and open-source items), so the page target holds. It picks and orders ids by how much of the posting's wording each fact shares, and uses only one wording of a fact when the profile keeps several. Nothing is reworded: the headline and summary stay the parent's until you tailor them, so the guardrails still hold. It also lists posting terms that no fact mentions: possible gaps, or just different wording.

## CLI

```sh
resume list                         # versions, the content dir in use, and applied dates
resume show acme                    # plain text of a version
resume diff base acme               # what a version changes
resume draft acme-sre posting.md    # draft a tailored version from a posting
resume check                        # guardrails on every version
resume build acme --preview         # -> ~/Downloads/<output>.{docx,pdf}; page JPEGs go to ~/.cache/resume-kit/previews
resume build --all --out /tmp/x     # RESUME_KIT_OUT also sets the default directory
resume score acme                   # score against the version's posting (or pass posting files)
resume answers eeo                  # standard form answers
resume ats jobs.ashbyhq.com --js    # quirks of the ATS behind a URL, with JS helpers
```

### Scoring

`resume score` builds the version and runs `shortlist jobs` on the PDF. shortlist-ai turns each posting into must-have and nice-to-have requirements, judges each one with quotes that it checks against the resume, and computes the score in code:

Real output for the bundled example (`resume --content examples/content score acme`, local backend):

```
Staff Detection Engineer: 79/100, must-haves 4/5
  Gaps (must-haves not fully met):
    - Production Kubernetes security experience
      real gap, don't add it; guardrail kubernetes: Only tutorial-level Kubernetes; nothing production.
  Requirements:
    ✅ years_experience (must-have) “Senior Security Engineer at Northwind Traders (5 yrs 6 mos, current role)”
    ✅ python (must-have) “Automated phishing triage with a Python and SOAR pipeline”
    ✅ sigma_or_siem_query (must-have) “Moved 300+ detections to detection-as-code: Sigma rules with unit tests ...”
    ✅ aws_security (must-have) “Designed organization-wide IAM guardrails (SCPs, permission boundaries) for 140 AWS accounts”
    ❌ kubernetes_security (must-have)
    ✅ giac_certifications (nice-to-have) “Certifications: AWS Certified Security – Specialty, GIAC Certified Incident Handler (GCIH)”
    🟡 open_source_tooling (nice-to-have) “Moved 300+ detections to detection-as-code”
```

A gap without a guardrail note usually means the experience is there but the resume doesn't show it clearly. That's worth a wording fix, backed by a fact in `profile.yaml`.

Install shortlist-ai separately (`pip install 'shortlist-ai[local]'`; drop `[local]` if you'll only use `--backend claude`), or point `RESUME_KIT_SHORTLIST` at its `shortlist` executable. `--backend local`, the default, runs an MLX model on Apple Silicon so the resume never leaves your machine. `--backend claude` uses the Anthropic API.

## MCP server

```sh
claude mcp add resume-kit -s user -- /path/to/resume-kit/.venv/bin/resume-kit-mcp
```

The server has these tools:
- `list_versions`
- `show_version`
- `check_facts`
- `build_version` (optionally with preview images)
- `score_version`
- `application_answers`
- `ats_playbook`

Its instructions tell the assistant never to add unconfirmed facts, and never to "close" a gap that a guardrail marks as real.

## Applicant tracking systems

`resume_kit/ats.yaml` collects quirks of Greenhouse, Ashby, Taleo, Workday, LinkedIn, and Eightfold, learned while filling in real applications. It also has JavaScript helpers for mapping an unfamiliar form's fields (labels, required flags, choices), setting React-controlled inputs and native selects, and listing required fields that are still empty. It's meant for an assistant filling in a form under your supervision, and its first rule is to stop before Submit.

## Tests

```sh
pytest -m "not render"   # fast: resolution, guardrails, scoring (with a fake shortlist), ATS lookup, MCP
pytest                   # also renders the examples and checks page targets and overflow reports
```

Tests only ever use the fictional example content.

## License

MIT
