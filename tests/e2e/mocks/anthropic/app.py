"""Mock Anthropic Messages API for e2e tests. Never used in production.

It plays the agent deterministically, in the real wire format:
  turn 1: call list_changed_files
  turn 2: call get_pr_diff for every listed file (parallel tool use)
  turn 3: return structured JSON with one finding on the first added line of each file
"""

import json
import re
import uuid
from typing import Any

from fastapi import FastAPI, Request

app = FastAPI(title="Mock Anthropic")
# "  12 +code" lines from get_pr_diff output: new-file line number of an added line.
_ADDED_LINE = re.compile(r"^\s*(\d+) \+", re.MULTILINE)
_DIFF_PATH = re.compile(r"<untrusted_diff path='([^']+)'>")


def _tool_results(messages: list[dict]) -> list[tuple[str, str]]:
    """(tool name, result text) pairs in conversation order."""
    names: dict[str, str] = {}
    results: list[tuple[str, str]] = []
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if block.get("type") == "tool_use":
                names[block["id"]] = block["name"]
            elif block.get("type") == "tool_result":
                text = block.get("content", "")
                if isinstance(text, list):
                    text = "".join(b.get("text", "") for b in text)
                results.append((names.get(block["tool_use_id"], "?"), text))
    return results


def _tool_use(name: str, tool_input: dict) -> dict:
    return {
        "type": "tool_use",
        "id": f"toolu_{uuid.uuid4().hex[:20]}",
        "name": name,
        "input": tool_input,
    }


def _final_answer(results: list[tuple[str, str]], is_test_agent: bool) -> dict:
    findings = []
    for name, text in results:
        if name != "get_pr_diff":
            continue
        path, line = _DIFF_PATH.search(text), _ADDED_LINE.search(text)
        if path and line:
            findings.append(
                {
                    "file_path": path.group(1),
                    "line": int(line.group(1)),
                    "severity": "info" if is_test_agent else "warning",
                    "category": "test" if is_test_agent else "bug",
                    "message": "Mock test suggestion" if is_test_agent else "Mock review finding",
                    "suggestion": "Add a unit test" if is_test_agent else "Check this line",
                }
            )
    output = {"summary": f"Mock summary covering {len(findings)} files.", "findings": findings}
    return {"type": "text", "text": json.dumps(output)}


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/messages")
async def create_message(request: Request) -> dict[str, Any]:
    body = await request.json()
    system = body.get("system", "")
    if isinstance(system, list):
        system = " ".join(b.get("text", "") for b in system)
    is_test_agent = "specializes in testing" in system
    results = _tool_results(body["messages"])
    called = {name for name, _ in results}

    if "list_changed_files" not in called:
        content, stop = [_tool_use("list_changed_files", {})], "tool_use"
    elif "get_pr_diff" not in called:
        listing = next(text for name, text in results if name == "list_changed_files")
        paths = [line.split(" (")[0] for line in listing.splitlines() if line.strip()]
        content = [_tool_use("get_pr_diff", {"file_path": p}) for p in paths]
        stop = "tool_use"
    else:
        content, stop = [_final_answer(results, is_test_agent)], "end_turn"

    return {
        "id": f"msg_mock_{uuid.uuid4().hex[:16]}",
        "type": "message",
        "role": "assistant",
        "model": body["model"],
        "content": content,
        "stop_reason": stop,
        "stop_sequence": None,
        # Roughly 4 characters per token, so cost tracking has realistic numbers.
        "usage": {
            "input_tokens": len(json.dumps(body["messages"])) // 4,
            "output_tokens": len(json.dumps(content)) // 4,
        },
    }
