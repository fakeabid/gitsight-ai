import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END

from app.core.config import Settings
from app.domain.sanitize import sanitize_issues
from app.graph.prompts.review import REVIEW_SYSTEM_PROMPT, build_review_user_message
from app.graph.state import ChunkOutcome, ChunkState

logger = logging.getLogger(__name__)


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def build_prompt(state: ChunkState) -> dict:
    chunk = state["chunk"]
    return {
        "messages": [
            SystemMessage(content=REVIEW_SYSTEM_PROMPT),
            HumanMessage(
                content=build_review_user_message(
                    chunk, state["pr_title"], state.get("pr_description")
                )
            ),
        ],
        "attempts": 0,
    }


def make_call_llm(llm: Any, settings: Settings) -> Callable[[ChunkState], Awaitable[dict]]:
    """`llm` is any object with `async ainvoke(messages)` returning {"parsed", "parsing_error", ...}."""

    async def call_llm(state: ChunkState) -> dict:
        attempts = state.get("attempts", 0) + 1
        index = state["chunk"].index
        if attempts > 1 and settings.retry_backoff_seconds > 0:
            backoff = settings.retry_backoff_seconds * (attempts - 1)
            prev_err = state.get("error") or ""
            if "RESOURCE_EXHAUSTED" in prev_err or "RateLimit" in prev_err or "retry in" in prev_err:
                match = re.search(r"retry in ([\d\.]+)s", prev_err) or re.search(
                    r"retryDelay['\":\s]+(\d+)", prev_err
                )
                if match:
                    try:
                        backoff = max(backoff, min(float(match.group(1)) + 1.0, 40.0))
                    except ValueError:
                        pass
                else:
                    backoff = max(backoff, 10.0)
            logger.info("Chunk %d: waiting %.1fs before attempt %d", index, backoff, attempts)
            await asyncio.sleep(backoff)
        try:
            output = await llm.ainvoke(state["messages"])
        except Exception as exc:  # noqa: BLE001 - every provider/network failure is handled alike
            logger.warning(
                "Chunk %d: LLM call failed (attempt %d): %s", index, attempts, type(exc).__name__
            )
            return {"attempts": attempts, "parsed": None, "error": f"{type(exc).__name__}: {exc}"}

        parsed = output.get("parsed")
        if parsed is None:
            logger.warning("Chunk %d: unparseable model output (attempt %d)", index, attempts)
            return {
                "attempts": attempts,
                "parsed": None,
                "error": f"unparseable: {output.get('parsing_error')}",
            }
        return {"attempts": attempts, "parsed": parsed, "error": None}

    return call_llm


def validate(state: ChunkState) -> dict:
    """Success → emit a ChunkOutcome. Failure → emit nothing; the router decides about a retry."""
    parsed = state.get("parsed")
    if parsed is None:
        return {}
    chunk = state["chunk"]
    outcome = ChunkOutcome(
        index=chunk.index,
        issues=sanitize_issues(parsed.issues, chunk.file_paths),
        summary=parsed.executive_summary.strip(),
        confidence=_clamp(parsed.overall_confidence_score, 0.0, 1.0),
        complexity=parsed.code_complexity,
        test_coverage_impact=_clamp(parsed.test_coverage_impact, -1.0, 1.0),
    )
    return {"chunk_results": [outcome]}


def make_route_after_validate(settings: Settings) -> Callable[[ChunkState], str]:
    def route(state: ChunkState) -> str:
        if state.get("chunk_results"):
            return END
        if state.get("attempts", 0) <= settings.chunk_max_retries:
            return "call_llm"
        return "record_failure"

    return route


def record_failure(state: ChunkState) -> dict:
    index = state["chunk"].index
    logger.error(
        "Chunk %d failed after %d attempt(s): %s",
        index,
        state.get("attempts", 0),
        state.get("error"),
    )
    return {"failed_chunks": [index]}
