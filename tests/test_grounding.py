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
    assert len(result.kept) == 2


def test_cap_keeps_most_severe():
    findings = [
        af("app.py", 10, "first readability nit", Severity.info),
        af("app.py", 30, "a real bug", Severity.error),
        af("util.py", 1, "risky pattern", Severity.warning),
    ]
    result = ground_findings(findings, FILES, max_comments=2)
    assert {k.finding.severity for k in result.kept} == {Severity.error, Severity.warning}
    assert result.dropped_over_cap == 1
