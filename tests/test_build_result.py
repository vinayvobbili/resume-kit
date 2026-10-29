"""What a build reports without rendering one: the file-name length warning."""

from pathlib import Path

from resume_kit.build import NAME_MAX, BuildResult


def result(name: str) -> BuildResult:
    pdf = Path("/out") / f"{name}.pdf"
    return BuildResult("v", pdf.with_suffix(".docx"), pdf, 1, 1, "")


def test_a_file_name_over_the_limit_is_reported():
    long = result("Jane_Example_Resume_Initech_Senior_Staff_Detection_Engineer")
    assert len(long.pdf.name) > NAME_MAX
    assert long.long_name.startswith(f"file name is {len(long.pdf.name)} characters")
    assert "shorten the version's output" in long.summary()


def test_a_short_file_name_says_nothing():
    short = result("Jane_Example_Resume_Initech")
    assert short.long_name == "" and "file name" not in short.summary()
