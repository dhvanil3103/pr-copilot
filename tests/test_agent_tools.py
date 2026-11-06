from shared.db import AgentName
from tests.doubles.github import FakeGitHubClient
from worker.agents.base import PRContext
from worker.agents.langchain_runner import load_prompt
from worker.agents.tools import build_tools
from worker.diff import ChangedFile

PATCH = "@@ -10,3 +10,3 @@ def f():\n a = 1\n-b = 2\n+b = 3\n c = 4"


def make_tools(max_chars=1000):
    github = FakeGitHubClient(contents={"app.py": "x" * 50})
    pr = PRContext(
        repo="o/r",
        pr_number=1,
        head_sha="abc",
        installation_id=1,
        files=[ChangedFile(path="app.py", status="modified", patch=PATCH, additions=1)],
        github=github,
    )
    return {t.name: t for t in build_tools(pr, max_chars)}


def test_tools_are_read_only():
    assert set(make_tools()) == {"list_changed_files", "get_pr_diff", "get_file_content"}


async def test_diff_is_numbered_with_new_file_lines_and_marked_untrusted():
    out = await make_tools()["get_pr_diff"].ainvoke({"file_path": "app.py"})
    assert out.startswith("<untrusted_diff")
    assert "  11 +b = 3" in out
    assert "     -b = 2" in out


async def test_unknown_file_returns_hint_not_error():
    out = await make_tools()["get_pr_diff"].ainvoke({"file_path": "nope.py"})
    assert "list_changed_files" in out


async def test_file_content_is_truncated():
    out = await make_tools(max_chars=10)["get_file_content"].ainvoke({"file_path": "app.py"})
    assert "x" * 10 + "\n... [truncated]" in out


async def test_file_content_errors_are_reported_to_the_model():
    out = await make_tools()["get_file_content"].ainvoke({"file_path": "missing.py"})
    assert out.startswith("Could not read")


def test_prompts_declare_pr_content_untrusted():
    for agent in AgentName:
        assert "untrusted data" in load_prompt(agent)
