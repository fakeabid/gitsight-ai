import asyncio
import re
from collections.abc import Callable
from typing import Any

from app.domain.diff_chunker import Chunk
from app.schemas.llm import ChunkReview, LLMIssue
from app.schemas.review import ReviewResult


def make_new_file_diff(path: str, lines: list[str]) -> str:
    body = "\n".join(f"+{line}" for line in lines)
    return (
        f"diff --git a/{path} b/{path}\nnew file mode 100644\nindex 0000000..1111111\n"
        f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{len(lines)} @@\n{body}\n"
    )


def llm_issue(path: str = "src/a.py", start: int = 1, end: int = 1, **overrides: Any) -> LLMIssue:
    data = dict(
        file_path=path,
        start_line=start,
        end_line=end,
        issue_type="Bug",
        severity="High",
        comment="Something is wrong.",
        suggested_removed_code="x",
        suggested_added_code="y",
    )
    return LLMIssue(**{**data, **overrides})


def ok_output(issues=(), summary="ok", confidence=0.9, complexity="Low", coverage=0.0) -> dict:
    review = ChunkReview(
        issues=list(issues),
        executive_summary=summary,
        overall_confidence_score=confidence,
        code_complexity=complexity,
        test_coverage_impact=coverage,
    )
    return {"raw": None, "parsed": review, "parsing_error": None}


def bad_output(reason: str = "bad json") -> dict:
    return {"raw": None, "parsed": None, "parsing_error": reason}


def make_chunk(index: int = 1, total: int = 1, paths: tuple[str, ...] = ("src/a.py",)) -> Chunk:
    return Chunk(
        index=index,
        total=total,
        text="diff --git a/src/a.py b/src/a.py\n",
        file_paths=paths,
    )


def paths_in_prompt(messages: list) -> list[str]:
    """File paths listed under 'FILES IN THIS PART' in the human message."""
    content = messages[-1].content
    block = re.search(r"FILES IN THIS PART:\n(.*?)\nUNIFIED DIFF:", content, re.S)
    return [line[2:] for line in block.group(1).splitlines()] if block else []


class FakeLLM:
    """Stand-in for a structured-output runnable.

    `responder(messages)` returns the value for `ainvoke`, or an Exception instance to raise.
    Tracks call count, the last messages received, and the maximum number of concurrent calls.
    """

    def __init__(self, responder: Callable[[list], Any], delay: float = 0.0) -> None:
        self._responder = responder
        self._delay = delay
        self.calls = 0
        self.in_flight = 0
        self.max_in_flight = 0
        self.last_messages: list = []

    async def ainvoke(self, messages: list, config: Any = None) -> Any:
        self.calls += 1
        self.last_messages = messages
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self._delay:
                await asyncio.sleep(self._delay)
            result = self._responder(messages)
            if isinstance(result, Exception):
                raise result
            return result
        finally:
            self.in_flight -= 1


def assert_invariants(result: ReviewResult, diff: str | None = None) -> None:
    """The response invariants from the API contract (section 6.2)."""
    assert result.final_suggestions_count == len(result.issues)
    assert (
        result.security_issues_count
        + result.breaches_count
        + result.bugs_count
        + result.performance_issues_count
        + result.code_smells_count
    ) == len(result.issues)
    assert result.syntax_errors_count == 0
    assert 0.0 <= result.overall_confidence_score <= 1.0
    for issue in result.issues:
        assert issue.start_line >= 1 and issue.end_line >= issue.start_line
        if diff is not None:
            assert issue.file_path in diff
