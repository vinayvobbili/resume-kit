import shutil

import pytest

from resume_kit.content import EXAMPLE_CONTENT


@pytest.fixture(autouse=True)
def example_content(monkeypatch):
    """Every test runs against the bundled fictional example, never a real user's content."""
    monkeypatch.setenv("RESUME_KIT_CONTENT", str(EXAMPLE_CONTENT))
    return EXAMPLE_CONTENT


@pytest.fixture
def content(tmp_path, monkeypatch):
    """A writable copy of the example content, with answers.yaml filled from the example."""
    dst = tmp_path / "content"
    shutil.copytree(EXAMPLE_CONTENT, dst)
    shutil.copy(dst / "answers.example.yaml", dst / "answers.yaml")
    monkeypatch.setenv("RESUME_KIT_CONTENT", str(dst))
    return dst
