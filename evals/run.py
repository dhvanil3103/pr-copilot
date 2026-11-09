"""Run the real agents on the eval cases and write a Markdown report.

    uv run python -m evals.run                 # all cases
    uv run python -m evals.run --case js_xss   # one case

Calls the real Anthropic API (costs money) and needs ANTHROPIC_API_KEY. No GitHub,
Kafka or database: each case's diff is fed straight to the same agent runner,
diff selection and grounding filter the worker uses.
"""

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from evals.scoring import CaseScore, ExpectedIssue, aggregate, matches, score_case
from shared.config import Settings
from shared.cost import estimate_cost_usd
from shared.db import AgentName
from worker.agents.base import AgentResult, PRContext
from worker.agents.langchain_runner import PROMPT_FILES, LangChainAgentRunner
from worker.diff import select_files
from worker.grounding import AttributedFinding, ground_findings
from worker.processor import run_agents

ROOT = Path(__file__).resolve().parent
CONCURRENCY = 3


class CaseFiles:
    """Serves file contents from the case JSON; the agents' only GitHub read path."""

    def __init__(self, files: list[dict]):
        self._contents = {f["filename"]: f.get("content", "") for f in files}

    async def get_file_content(self, installation_id, repo, path, ref) -> str:
        if path not in self._contents:
            raise FileNotFoundError(path)
        return self._contents[path]


@dataclass
class CaseRun:
    case: dict
    score: CaseScore
    results: list[AgentResult]
    grounded: list[AttributedFinding]
    cost_usd: float


def posted_findings(kept: list[AttributedFinding]) -> list[AttributedFinding]:
    """Every finding that reaches the PR, including ones folded into another comment.

    Merging nearby findings changes how many comments are posted, not what is reported, so
    recall, precision and the grounding rate count the folded findings too.
    """
    out: list[AttributedFinding] = []
    for af in kept:
        out.append(af)
        out += [AttributedFinding(agent=af.agent, finding=f) for f in af.related]
        out += [AttributedFinding(agent=AgentName.test, finding=f) for f in af.merged_tests]
    return out


async def run_case(case: dict, settings: Settings, runner: LangChainAgentRunner) -> CaseRun:
    selection = select_files(case["files"], settings.max_diff_chars)
    pr = PRContext(
        repo="evals/" + case["id"],
        pr_number=1,
        head_sha="eval",
        installation_id=0,
        files=selection.files,
        github=CaseFiles(case["files"]),
    )
    results = await run_agents(settings, runner, pr)
    attributed = [
        AttributedFinding(agent=r.agent, finding=f)
        for r in results
        if r.output
        for f in r.output.findings
    ]
    # No comment cap here: we want to measure grounding on everything produced.
    grounding = ground_findings(attributed, selection.files, max_comments=10_000)
    posted = posted_findings(grounding.kept)
    texts = [r.output.summary for r in results if r.output]
    texts += [af.finding.message + " " + af.finding.suggestion for af in attributed]
    injection = case.get("injection")
    score = score_case(
        case["id"],
        case["kind"],
        [ExpectedIssue(**e) for e in case["expected"]],
        raw_findings=len(attributed),
        grounded=posted,
        agent_text="\n".join(texts),
        canary=injection["canary"] if injection else None,
    )
    cost = sum(
        estimate_cost_usd(r.model, r.input_tokens, r.output_tokens, settings.model_prices)
        for r in results
    )
    return CaseRun(case, score, results, posted, cost)


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def render_report(runs: list[CaseRun], settings: Settings, started: datetime) -> str:
    totals = aggregate([r.score for r in runs])
    tokens_in = sum(res.input_tokens for r in runs for res in r.results)
    tokens_out = sum(res.output_tokens for r in runs for res in r.results)
    cost = sum(r.cost_usd for r in runs)
    injection = {None: "n/a", True: "resisted", False: "**FAILED**"}[totals.injection_resisted]

    lines = [
        f"# Eval report {started:%Y-%m-%d %H:%M} UTC",
        "",
        f"- Models: review `{settings.model_for('review')}`, test `{settings.model_for('test')}`",
        f"- Prompts: review `{PROMPT_FILES[AgentName.review]}`, "
        f"test `{PROMPT_FILES[AgentName.test]}`",
        f"- Cases: {len(runs)}",
        "- Matching: same file and line range (±2 lines). No LLM judge is used; precision "
        "counts review-agent findings of severity warning or error.",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Recall (expected issues found) | {_pct(totals.recall)} |",
        f"| Precision (issue findings matching an expected issue) | {_pct(totals.precision)} |",
        f"| Grounding rate (findings that survived the filter) | {_pct(totals.grounding_rate)} |",
        f"| False positives on clean diffs | {totals.clean_false_positives} |",
        f"| Prompt injection | {injection} |",
        f"| Tokens (input / output) | {tokens_in:,} / {tokens_out:,} |",
        f"| Estimated cost | ${cost:.4f} |",
        "",
        "## Cases",
        "",
        "| Case | Kind | Found | Issue findings (TP) | Grounded / raw | Cost | Errors |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in runs:
        s = r.score
        errors = ", ".join(f"{res.agent}: {res.error}" for res in r.results if res.error) or ""
        lines.append(
            f"| `{s.case_id}` | {s.kind} | {s.found}/{s.expected} | "
            f"{s.issue_findings} ({s.true_positives}) | {s.grounded_findings}/{s.raw_findings} | "
            f"${r.cost_usd:.4f} | {errors} |"
        )

    lines += ["", "## Details", ""]
    for r in runs:
        expected = [ExpectedIssue(**e) for e in r.case["expected"]]
        lines += [f"### `{r.case['id']}`: {r.case['title']}", ""]
        for i, issue in enumerate(expected):
            mark = "found" if i in r.score.matched_issue_ids else "MISSED"
            lines.append(
                f"- Expected ({mark}): `{issue.file}:{issue.line_start}-{issue.line_end}` "
                f"{issue.description}"
            )
        if r.score.injection_resisted is not None:
            lines.append(f"- Injection resisted: {r.score.injection_resisted}")
        for af in r.grounded:
            f = af.finding
            hit = any(matches(af, e) for e in expected)
            lines.append(
                f"- {'✓' if hit else '·'} [{af.agent}/{f.severity.value}/{f.category}] "
                f"`{f.file_path}:{f.line}` {f.message}"
            )
        lines.append("")
    return "\n".join(lines)


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", help="run only these case ids")
    parser.add_argument("--cases-dir", type=Path, default=ROOT / "cases")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "reports")
    args = parser.parse_args(argv)

    settings = Settings()
    if not settings.anthropic_api_key:
        print("Skipping evals: ANTHROPIC_API_KEY is not set (evals call the real model).")
        return 0

    cases = [json.loads(p.read_text()) for p in sorted(args.cases_dir.glob("*.json"))]
    if args.case:
        cases = [c for c in cases if c["id"] in args.case]
    if not cases:
        print("No matching eval cases.", file=sys.stderr)
        return 1

    started = datetime.now(UTC)
    runner = LangChainAgentRunner(settings)
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def bounded(case: dict) -> CaseRun:
        async with semaphore:
            run = await run_case(case, settings, runner)
            print(f"{case['id']}: found {run.score.found}/{run.score.expected}", flush=True)
            return run

    runs = await asyncio.gather(*(bounded(c) for c in cases))
    report = render_report(list(runs), settings, started)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    path = args.out_dir / f"report-{started:%Y%m%d-%H%M%S}.md"
    path.write_text(report)
    print(f"\nReport written to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
