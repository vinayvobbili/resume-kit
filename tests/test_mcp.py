import asyncio
import json

from resume_kit.mcp_server import server


def call(name, args):
    result = asyncio.run(server.call_tool(name, args))
    assert not result.is_error, result.content
    text = result.content[0].text
    return json.loads(text) if text[:1] in "[{" else text


def test_tools_are_registered():
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == {"list_versions", "show_version", "check_facts", "build_version", "score_version",
                     "application_answers", "ats_playbook"}


def test_list_versions_reports_content_dir(example_content):
    data = call("list_versions", {})
    assert data["content"] == str(example_content)
    assert [v["version"] for v in data["versions"]] == ["acme", "base"]


def test_check_facts_all_versions_ok():
    assert set(call("check_facts", {}).values()) == {"ok"}


def test_show_version_is_plain_text():
    assert "Alex Rivera" in call("show_version", {"version": "base"})


def test_ats_playbook():
    assert call("ats_playbook", {"system": "taleo"})["system"] == "taleo"
