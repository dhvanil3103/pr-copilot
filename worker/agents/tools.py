"""Read-only tools exposed to the agents.

No tool can write to GitHub. Posting happens later in deterministic code, after
the grounding filter, so a manipulated agent can at worst produce bad text.
"""

from langchain.tools import BaseTool, tool

from worker.agents.base import PRContext


def _numbered_patch(patch: str) -> str:
    """Prefix each patch line with its new-file line number so the model can cite lines."""
    out: list[str] = []
    new_line = 0
    for raw in patch.splitlines():
        if raw.startswith("@@"):
            new_line = int(raw.split("+", 1)[1].split(",")[0].split(" ")[0])
            out.append(raw)
        elif raw.startswith("-") or raw.startswith("\\"):
            out.append(f"     {raw}")
        else:
            out.append(f"{new_line:>4} {raw}")
            new_line += 1
    return "\n".join(out)


def build_tools(pr: PRContext, max_file_chars: int) -> list[BaseTool]:
    by_path = {f.path: f for f in pr.files}

    @tool
    def list_changed_files() -> str:
        """List the files changed in this pull request that are in scope for review."""
        return "\n".join(f"{f.path} ({f.status}, +{f.additions} -{f.deletions})" for f in pr.files)

    @tool
    def get_pr_diff(file_path: str) -> str:
        """Get the unified diff for one changed file, with new-file line numbers on the left."""
        f = by_path.get(file_path)
        if f is None:
            return f"No diff for {file_path!r}. Use a path from list_changed_files."
        return f"<untrusted_diff path={file_path!r}>\n{_numbered_patch(f.patch)}\n</untrusted_diff>"

    @tool
    async def get_file_content(file_path: str, ref: str = "") -> str:
        """Get a file's full content at a git ref. Defaults to the PR head commit."""
        try:
            content = await pr.github.get_file_content(
                pr.installation_id, pr.repo, file_path, ref or pr.head_sha
            )
        except Exception as exc:  # the model should see the failure and move on
            return f"Could not read {file_path!r}: {exc}"
        if len(content) > max_file_chars:
            content = content[:max_file_chars] + "\n... [truncated]"
        return f"<untrusted_file path={file_path!r}>\n{content}\n</untrusted_file>"

    return [list_changed_files, get_pr_diff, get_file_content]
