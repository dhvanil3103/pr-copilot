from collections import Counter

from worker.agents.base import AgentResult
from worker.diff import DiffSelection
from worker.grounding import AttributedFinding, GroundingResult

_AGENT_LABEL = {"review": "code review", "test": "test suggestion"}


def comment_body(af: AttributedFinding) -> str:
    f = af.finding
    body = f"**{f.severity.value.upper()} · {f.category}** ({_AGENT_LABEL[af.agent]} agent)\n\n"
    body += f.message
    if f.suggestion:
        body += f"\n\n**Suggestion:**\n{f.suggestion}"
    for t in af.merged_tests:
        body += f"\n\n**Suggested test** (test suggestion agent): {t.message}"
        if t.suggestion:
            body += f"\n\n{t.suggestion}"
    return body


def review_body(
    results: list[AgentResult], selection: DiffSelection, grounding: GroundingResult
) -> str:
    lines = ["## PR Copilot review", ""]
    for result in results:
        if result.output and result.output.summary:
            lines += [f"**{_AGENT_LABEL[result.agent].capitalize()}:** {result.output.summary}", ""]
        elif result.error:
            lines += [f"_The {_AGENT_LABEL[result.agent]} agent failed: {result.error}_", ""]

    if grounding.kept:
        counts = Counter(af.finding.severity.value for af in grounding.kept)
        parts = [f"{counts[s]} {s}" for s in ("error", "warning", "info") if counts[s]]
        lines.append(f"{len(grounding.kept)} inline comments ({', '.join(parts)}).")
    else:
        lines.append("No issues found on the changed lines.")

    notes = []
    if selection.truncated:
        notes.append(
            f"This PR is large, so {len(selection.truncated)} lower-priority files were not "
            f"reviewed: {', '.join(selection.truncated[:10])}"
            + (" and more." if len(selection.truncated) > 10 else ".")
        )
    if selection.skipped:
        notes.append(
            f"Skipped {len(selection.skipped)} lockfile, generated, vendored or binary files."
        )
    if grounding.dropped_over_cap:
        notes.append(f"{grounding.dropped_over_cap} lower-severity comments were omitted.")
    if notes:
        lines += [""] + [f"- {n}" for n in notes]
    return "\n".join(lines)
