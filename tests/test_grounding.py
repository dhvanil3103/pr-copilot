from shared.db import AgentName, Severity
from worker.diff import ChangedFile
from worker.findings import Finding
from worker.grounding import AttributedFinding, ground_findings

FILES = [
    ChangedFile(path="app.py", status="modified", patch="", added={10, 11, 12, 30}),
    ChangedFile(path="util.py", status="added", patch="", added={1, 2}),
]


def af(path, line, message="Possible None dereference", severity=Severity.warning, agent="review"):
    finding = Finding(file_path=path, line=line, severity=severity, category="bug", message=message)
    return AttributedFinding(agent=AgentName(agent), finding=finding)


def test_drops_findings_not_on_added_lines():
    result = ground_findings(
        [af("app.py", 10), af("app.py", 20), af("missing.py", 1), af("util.py", 2, "other")],
        FILES,
        max_comments=10,
    )
    assert [(k.finding.file_path, k.finding.line) for k in result.kept] == [
        ("app.py", 10),
        ("util.py", 2),
    ]
    assert result.dropped_ungrounded == 2


def test_dedupes_near_identical_findings_keeping_most_severe():
    result = ground_findings(
        [
            af("app.py", 10, "Possible None dereference of user", Severity.info),
            af("app.py", 11, "Possible None dereference of user!", Severity.error),
            af("app.py", 30, "Possible None dereference of user"),  # too far away
        ],
        FILES,
        max_comments=10,
    )
    assert [(k.finding.line, k.finding.severity) for k in result.kept] == [
        (11, Severity.error),
        (30, Severity.warning),
    ]
    assert result.dropped_duplicates == 1


def test_different_messages_on_same_line_are_kept():
    result = ground_findings(
        [af("app.py", 10, "SQL injection via f-string"), af("app.py", 10, "Add a test for None")],
        FILES,
        max_comments=10,
    )
    # Same agent and category, so one comment, but neither finding is lost.
    assert len(result.kept) == 1
    messages = [result.kept[0].finding.message, *(r.message for r in result.kept[0].related)]
    assert sorted(messages) == ["Add a test for None", "SQL injection via f-string"]


def test_cap_keeps_most_severe():
    findings = [
        af("app.py", 10, "first readability nit", Severity.info),
        af("app.py", 30, "a real bug", Severity.error),
        af("util.py", 1, "risky pattern", Severity.warning),
    ]
    result = ground_findings(findings, FILES, max_comments=2)
    assert {k.finding.severity for k in result.kept} == {Severity.error, Severity.warning}
    assert result.dropped_over_cap == 1


def test_test_suggestion_on_same_line_is_merged_into_review_comment():
    result = ground_findings(
        [
            af(
                "app.py", 10, "Test that a quote in email cannot inject SQL", Severity.error, "test"
            ),
            af("app.py", 10, "SQL injection via f-string", Severity.warning),
            af("app.py", 30, "Test that empty input raises", Severity.info, "test"),
        ],
        FILES,
        max_comments=10,
    )
    assert [(k.agent, k.finding.line) for k in result.kept] == [
        (AgentName.review, 10),
        (AgentName.test, 30),
    ]
    assert [t.message for t in result.kept[0].merged_tests] == [
        "Test that a quote in email cannot inject SQL"
    ]
    assert result.merged_tests == 1 and result.dropped_duplicates == 0


def finding_on(line, category, message, severity=Severity.warning, agent="review", path="app.py"):
    f = Finding(file_path=path, line=line, severity=severity, category=category, message=message)
    return AttributedFinding(agent=AgentName(agent), finding=f)


def test_test_suggestion_a_line_away_attaches_to_nearest_review_comment():
    result = ground_findings(
        [
            finding_on(12, "bug", "Race condition in reserve", Severity.error),
            finding_on(11, "test", "Test that two threads cannot oversell", agent="test"),
        ],
        FILES,
        max_comments=10,
    )
    assert len(result.kept) == 1 and result.merged_tests == 1


def test_same_category_findings_within_three_lines_become_one_comment():
    result = ground_findings(
        [
            finding_on(10, "security", "Order SKU reaches the page unescaped"),
            finding_on(
                11, "security", "customerNote is interpolated into innerHTML", Severity.error
            ),
            finding_on(12, "bug", "Unrelated off-by-one"),
            finding_on(30, "security", "Hardcoded key"),
        ],
        FILES,
        max_comments=10,
    )
    kept = {(k.finding.line, k.finding.category): k for k in result.kept}
    assert set(kept) == {(11, "security"), (12, "bug"), (30, "security")}
    assert [r.line for r in kept[(11, "security")].related] == [10]
    assert result.merged_related == 1 and result.dropped_duplicates == 0
