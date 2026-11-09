from shared.db import AgentName, Severity
from worker.agents.base import AgentResult
from worker.diff import DiffSelection
from worker.findings import AgentOutput, Finding
from worker.grounding import AttributedFinding, GroundingResult
from worker.summary import comment_body, review_body


def test_review_body_reports_failures_and_truncation():
    finding = Finding(
        file_path="a.py", line=1, severity=Severity.error, category="bug", message="m"
    )
    results = [
        AgentResult(AgentName.review, "m", AgentOutput(summary="Looks risky.", findings=[finding])),
        AgentResult(AgentName.test, "m", None, error="timed out"),
    ]
    grounding = GroundingResult(
        kept=[AttributedFinding(AgentName.review, finding)],
        dropped_ungrounded=0,
        dropped_duplicates=0,
        dropped_over_cap=0,
    )
    selection = DiffSelection(files=[], skipped=["uv.lock"], truncated=["big.py"])
    body = review_body(results, selection, grounding)
    assert "Looks risky." in body
    assert "test suggestion agent failed: timed out" in body
    assert "1 inline comments (1 error)" in body
    assert "big.py" in body and "Skipped 1" in body


def test_comment_body_includes_suggestion_and_agent():
    finding = Finding(
        file_path="a.py",
        line=1,
        severity=Severity.warning,
        category="security",
        message="Uses eval",
        suggestion="Use ast.literal_eval",
    )
    body = comment_body(AttributedFinding(AgentName.review, finding))
    assert body.startswith("**WARNING · security** (code review agent)")
    assert "ast.literal_eval" in body


def test_comment_body_appends_merged_test_suggestion():
    review = Finding(
        file_path="a.py",
        line=1,
        severity=Severity.error,
        category="security",
        message="SQL injection",
    )
    test = Finding(
        file_path="a.py",
        line=1,
        severity=Severity.info,
        category="test",
        message="Test that a quote cannot inject SQL",
        suggestion="def test_quote(): ...",
    )
    body = comment_body(AttributedFinding(AgentName.review, review, merged_tests=[test]))
    assert "**Suggested test** (test suggestion agent): Test that a quote cannot inject SQL" in body
    assert "def test_quote(): ..." in body
