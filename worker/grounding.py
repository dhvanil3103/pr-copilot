"""Deterministic filter between the agents and GitHub.

The model can hallucinate files or line numbers, and GitHub rejects a whole
review if a single inline comment points at a line outside the diff. Only
findings anchored to a real added line survive.
"""

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from shared.db import AgentName, Severity
from worker.diff import ChangedFile
from worker.findings import Finding

_SEVERITY_RANK = {Severity.error: 0, Severity.warning: 1, Severity.info: 2}
# Findings this close together with near-identical text are treated as one, and one agent's
# findings of the same category this close together are posted as one comment.
_NEAR_LINES = 3
# A test suggestion this close to a review finding is attached to that comment.
_TEST_MERGE_LINES = 2
_SIMILARITY = 0.8


@dataclass
class AttributedFinding:
    agent: AgentName
    finding: Finding
    # Test suggestions folded into this review comment because they target the same code.
    merged_tests: list[Finding] = field(default_factory=list)
    # Same-agent, same-category findings a few lines away, posted in this one comment.
    related: list[Finding] = field(default_factory=list)

    def lines(self) -> list[int]:
        return [self.finding.line, *(r.line for r in self.related)]


@dataclass
class GroundingResult:
    kept: list[AttributedFinding]
    dropped_ungrounded: int
    dropped_duplicates: int
    dropped_over_cap: int
    merged_tests: int = 0
    merged_related: int = 0


def _normalize(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def _is_duplicate(a: Finding, b: Finding) -> bool:
    if a.file_path != b.file_path or abs(a.line - b.line) > _NEAR_LINES:
        return False
    ratio = SequenceMatcher(None, _normalize(a.message), _normalize(b.message)).ratio()
    return ratio >= _SIMILARITY


def ground_findings(
    findings: list[AttributedFinding], files: list[ChangedFile], max_comments: int
) -> GroundingResult:
    added_by_path = {f.path: f.added for f in files}

    grounded = [
        af for af in findings if af.finding.line in added_by_path.get(af.finding.file_path, set())
    ]
    ungrounded = len(findings) - len(grounded)

    # Most severe first, so dedupe keeps the strongest version, comments are anchored on the
    # most severe finding, and the cap drops the least important. Review findings go first so
    # a test suggestion can be attached to the review comment for the same code.
    grounded.sort(key=lambda af: (af.agent != "review", _SEVERITY_RANK[af.finding.severity]))
    unique: list[AttributedFinding] = []
    merged = related = 0
    for af in grounded:
        f = af.finding
        if any(_is_duplicate(f, kept.finding) for kept in unique):
            continue
        if af.agent == "test":
            near_reviews = [
                kept
                for kept in unique
                if kept.agent == "review"
                and kept.finding.file_path == f.file_path
                and abs(kept.finding.line - f.line) <= _TEST_MERGE_LINES
            ]
            if near_reviews:
                target = min(near_reviews, key=lambda k: abs(k.finding.line - f.line))
                target.merged_tests.append(f)
                merged += 1
                continue
        anchor = next(
            (
                kept
                for kept in unique
                if kept.agent == af.agent
                and kept.finding.file_path == f.file_path
                and kept.finding.category.lower() == f.category.lower()
                and any(abs(line - f.line) <= _NEAR_LINES for line in kept.lines())
            ),
            None,
        )
        if anchor is not None:
            anchor.related.append(f)
            related += 1
        else:
            unique.append(af)
    unique.sort(key=lambda af: (_SEVERITY_RANK[af.finding.severity], af.agent != "review"))

    kept = unique[:max_comments]
    kept.sort(key=lambda af: (af.finding.file_path, af.finding.line))
    return GroundingResult(
        kept=kept,
        dropped_ungrounded=ungrounded,
        dropped_duplicates=len(grounded) - len(unique) - merged - related,
        dropped_over_cap=len(unique) - len(kept),
        merged_tests=merged,
        merged_related=related,
    )
