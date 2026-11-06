"""Parse GitHub per-file patches and choose which files are worth reviewing."""

import re
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import PurePosixPath

_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

LOCKFILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "uv.lock",
    "Pipfile.lock", "Cargo.lock", "go.sum", "composer.lock", "Gemfile.lock",
}  # fmt: skip
SKIP_PATTERNS = [
    "vendor/*", "*/vendor/*", "node_modules/*", "*/node_modules/*", "third_party/*",
    "dist/*", "build/*", "*.min.js", "*.min.css", "*.map", "*_pb2.py", "*.pb.go",
    "*.generated.*", "*.lock", "*.svg", "*.snap",
]  # fmt: skip
SOURCE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rb", ".rs", ".kt",
    ".c", ".cc", ".cpp", ".h", ".cs", ".php", ".scala", ".swift", ".sql", ".sh",
}  # fmt: skip


def added_lines(patch: str) -> set[int]:
    """Line numbers (in the new file) of lines added or modified by a unified-diff patch.

    GitHub only accepts inline comments on lines that appear in the diff; we go
    further and only allow '+' lines, so every comment is about changed code.
    """
    lines: set[int] = set()
    new_line = 0
    in_hunk = False
    for raw in patch.splitlines():
        header = _HUNK_HEADER.match(raw)
        if header:
            new_line = int(header.group(1))
            in_hunk = True
            continue
        if not in_hunk or raw.startswith("\\"):  # "\ No newline at end of file"
            continue
        if raw.startswith("+"):
            lines.add(new_line)
            new_line += 1
        elif raw.startswith("-"):
            continue  # removed lines do not exist in the new file
        else:
            new_line += 1
    return lines


@dataclass
class ChangedFile:
    path: str
    status: str
    patch: str
    additions: int = 0
    deletions: int = 0
    added: set[int] = field(default_factory=set)


@dataclass
class DiffSelection:
    files: list[ChangedFile]
    skipped: list[str]  # filtered out as lockfile, generated, vendored or binary
    truncated: list[str]  # reviewable, but dropped to stay under the size cap


def is_skippable(path: str, patch: str | None) -> bool:
    if patch is None or patch == "":
        return True  # GitHub omits the patch for binaries and very large files
    name = PurePosixPath(path).name
    if name in LOCKFILES:
        return True
    return any(fnmatch(path, pattern) for pattern in SKIP_PATTERNS)


def _relevance(f: ChangedFile) -> tuple[int, int]:
    # Source code before config/docs, then larger changes first.
    is_source = PurePosixPath(f.path).suffix in SOURCE_EXTENSIONS
    return (0 if is_source else 1, -(f.additions + f.deletions))


def select_files(raw_files: list[dict], max_diff_chars: int) -> DiffSelection:
    """Drop noise files and keep the most relevant ones within the diff size budget."""
    candidates: list[ChangedFile] = []
    skipped: list[str] = []
    for item in raw_files:
        path, patch = item["filename"], item.get("patch")
        if item.get("status") == "removed" or is_skippable(path, patch):
            skipped.append(path)
            continue
        candidates.append(
            ChangedFile(
                path=path,
                status=item.get("status", "modified"),
                patch=patch,
                additions=item.get("additions", 0),
                deletions=item.get("deletions", 0),
                added=added_lines(patch),
            )
        )

    selected: list[ChangedFile] = []
    truncated: list[str] = []
    budget = max_diff_chars
    for f in sorted(candidates, key=_relevance):
        if len(f.patch) <= budget:
            selected.append(f)
            budget -= len(f.patch)
        else:
            truncated.append(f.path)
    return DiffSelection(files=selected, skipped=skipped, truncated=truncated)
