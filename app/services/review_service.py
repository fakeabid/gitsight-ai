import asyncio
import logging
from typing import Any

from app.core.config import Settings
from app.core.errors import AllChunksFailedError, PayloadTooLargeError, ReviewTimeoutError
from app.schemas.review import ReviewRequest, ReviewResult

logger = logging.getLogger(__name__)


class ReviewService:
    def __init__(self, graph: Any, settings: Settings) -> None:
        self._graph = graph
        self._settings = settings

    async def review(self, request: ReviewRequest) -> ReviewResult:
        if len(request.diff) > self._settings.max_diff_chars:
            msg = (
                f"Diff has {len(request.diff)} characters; "
                f"the limit is {self._settings.max_diff_chars}."
            )
            raise PayloadTooLargeError(msg)
        initial = {
            "pr_title": request.pr_title,
            "pr_description": request.pr_description,
            "raw_diff": request.diff,
        }
        config = {"max_concurrency": self._settings.max_concurrency, "run_name": "pr_review"}
        try:
            final = await asyncio.wait_for(
                self._graph.ainvoke(initial, config=config),
                timeout=self._settings.review_timeout_seconds,
            )
        except TimeoutError as exc:
            if request.graceful_failure or self._settings.graceful_failure:
                logger.error(
                    "Review timed out after %ds; returning graceful failure",
                    self._settings.review_timeout_seconds,
                )
                return ReviewResult.failure(
                    error_code="AI_TIMEOUT",
                    message=f"Review exceeded {self._settings.review_timeout_seconds}s.",
                    retryable=True,
                )
            raise ReviewTimeoutError(
                f"Review exceeded {self._settings.review_timeout_seconds}s."
            ) from exc

        result: ReviewResult = final["result"]
        meta = result.meta
        if meta.chunk_count > 0 and len(meta.failed_chunks) == meta.chunk_count:
            if request.graceful_failure or self._settings.graceful_failure:
                logger.error(
                    "All %d chunk(s) failed; returning graceful failure", meta.chunk_count
                )
                return ReviewResult.failure(
                    error_code="AI_TEMPORARILY_UNAVAILABLE",
                    message="The language model could not review any part of the diff.",
                    retryable=True,
                    meta=meta,
                )
            raise AllChunksFailedError("The language model could not review any part of the diff.")
        logger.info(
            "Review done: %d issue(s), partial=%s, chunks=%d",
            len(result.issues),
            meta.partial,
            meta.chunk_count,
        )
        return result
