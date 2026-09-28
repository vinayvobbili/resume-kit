import shutil

import pytest

from resume_kit.build import build, page_text
from resume_kit.content import EXAMPLE_CONTENT, list_versions

pytestmark = [
    pytest.mark.render,
    pytest.mark.skipif(not all(shutil.which(t) for t in ("node", "soffice", "pdfinfo", "pdftotext")),
                       reason="needs node, LibreOffice, and poppler"),
]


@pytest.mark.parametrize("version", list_versions(EXAMPLE_CONTENT))  # collected before fixtures run
def test_renders_to_its_page_target(version, tmp_path):
    result = build(version, tmp_path)
    assert result.docx.exists()
    assert result.ok, result.summary()


def test_pdf_carries_the_content(tmp_path):
    result = build("acme", tmp_path)
    text = " ".join(page_text(result.pdf, 1, result.pages).split())
    assert "Staff Detection Engineer" in text
    assert "Moved 300+ detections to detection-as-code" in text
    assert "iam-diff" not in text  # dropped by the acme version


def test_overflow_is_reported(content, tmp_path):
    variant = content / "variants" / "base.yaml"
    variant.write_text(variant.read_text().replace("summary: >-\n", "summary: >-\n  " + "Long filler text. " * 400 + "\n"))
    result = build("base", tmp_path)
    assert not result.ok and result.pages > 1
    assert "spills onto page 2" in result.summary()


def test_build_refuses_guardrail_violations(content, tmp_path):
    variant = content / "variants" / "base.yaml"
    variant.write_text(variant.read_text().replace("Security engineer with", "CISSP security engineer with"))
    with pytest.raises(Exception, match="cissp"):
        build("base", tmp_path)
