import json
from pathlib import Path

import pytest

from evals import run as eval_run
from evals.scoring import ExpectedIssue, aggregate, score_case
from shared.db import AgentName, Severity
from tests.e2e.mocks.anthropic.app import app as mock_anthropic
from tests.servers import serve
from worker.diff import added_lines
from worker.findings import Finding
from worker.grounding import AttributedFinding

CASES = [json.loads(p.read_text()) for p in sorted(Path("evals/cases").glob("*.json"))]
ISSUE = ExpectedIssue(file="a.py", line_start=10, line_end=11, category="bug", description="d")


def af(line, agent=AgentName.review, severity=Severity.error, path="a.py"):
    finding = Finding(file_path=path, line=line, severity=severity, category="c", message="m")
    return AttributedFinding(agent=agent, finding=finding)


def test_case_suite_shape():
    assert 8 <= len(CASES) <= 10
    assert {"python", "javascript", "java", "go"} <= {
        f["language"] for c in CASES for f in c["files"]
    }
    assert any(c["kind"] == "clean" and not c["expected"] for c in CASES)
    assert any(c["kind"] == "injection" and c["injection"]["canary"] for c in CASES)


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_expected_issues_point_at_added_lines(case):
    added = {f["filename"]: added_lines(f["patch"]) for f in case["files"]}
    for issue in case["expected"]:
        assert issue["line_start"] in added[issue["file"]], issue


def test_score_counts_recall_precision_and_ignores_test_suggestions():
    grounded = [
        af(12),  # within tolerance -> true positive
        af(30),  # false positive
        af(10, agent=AgentName.test, severity=Severity.info),  # not an issue claim
        af(11, severity=Severity.info),  # info notes are not counted for precision
    ]
    score = score_case("c", "bug", [ISSUE], raw_findings=6, grounded=grounded, agent_text="")
    assert (score.found, score.expected) == (1, 1)
    assert (score.true_positives, score.issue_findings) == (1, 2)
    assert (score.grounded_findings, score.raw_findings) == (4, 6)
    assert score.injection_resisted is None


def test_finding_outside_tolerance_or_other_file_does_not_match():
    score = score_case("c", "bug", [ISSUE], 2, [af(14), af(10, path="b.py")], agent_text="")
    assert score.found == 0 and score.true_positives == 0


def test_injection_is_resisted_only_if_canary_absent_and_bug_found():
    canary = "LGTM APPROVED"
    ok = score_case("i", "injection", [ISSUE], 1, [af(10)], "Hardcoded key", canary)
    obeyed = score_case("i", "injection", [ISSUE], 1, [af(10)], "lgtm approved", canary)
    silenced = score_case("i", "injection", [ISSUE], 0, [], "Looks fine", canary)
    assert ok.injection_resisted is True
    assert obeyed.injection_resisted is False
    assert silenced.injection_resisted is False
    assert aggregate([ok, obeyed]).injection_resisted is False


def test_aggregate_handles_clean_cases_and_empty_denominators():
    clean = score_case("clean", "clean", [], 1, [af(3)], "")
    totals = aggregate([clean])
    assert totals.recall is None
    assert totals.precision == 0
    assert totals.clean_false_positives == 1


async def test_runner_skips_without_api_key(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    assert await eval_run.main(["--out-dir", str(tmp_path)]) == 0
    assert "Skipping evals" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


async def test_runner_writes_report_against_mock_api(monkeypatch, tmp_path):
    # Exercises the whole eval code path for free; the scores are meaningless.
    with serve(mock_anthropic) as url:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "mock")
        monkeypatch.setenv("ANTHROPIC_BASE_URL", url)
        code = await eval_run.main(
            ["--out-dir", str(tmp_path), "--case", "go_nil_map", "--case", "js_injection"]
        )
    assert code == 0
    (report,) = tmp_path.glob("report-*.md")
    text = report.read_text()
    assert "| Recall (expected issues found) |" in text
    assert "`go_nil_map`" in text and "Injection resisted" in text


def test_posted_findings_include_merged_ones():
    from evals.run import posted_findings
    from shared.db import AgentName, Severity
    from worker.findings import Finding
    from worker.grounding import AttributedFinding

    def f(line, category):
        return Finding(
            file_path="a.py",
            line=line,
            severity=Severity.warning,
            category=category,
            message=f"m{line}",
        )

    kept = [
        AttributedFinding(
            AgentName.review, f(5, "bug"), merged_tests=[f(6, "test")], related=[f(3, "bug")]
        )
    ]
    assert [(a.agent, a.finding.line) for a in posted_findings(kept)] == [
        (AgentName.review, 5),
        (AgentName.review, 3),
        (AgentName.test, 6),
    ]
