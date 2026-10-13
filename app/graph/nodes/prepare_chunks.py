import logging
from collections.abc import Callable

from app.core.config import Settings
from app.domain.diff_chunker import build_chunks
from app.graph.state import ReviewState

logger = logging.getLogger(__name__)


def make_prepare_chunks(settings: Settings) -> Callable[[ReviewState], dict]:
    def prepare_chunks(state: ReviewState) -> dict:
        result = build_chunks(
            state["raw_diff"],
            noise_patterns=settings.noise_patterns,
            max_chunk_chars=settings.max_chunk_chars,
            max_total_chunks=settings.max_total_chunks,
        )
        logger.info(
            "Prepared %d chunk(s); skipped %d file(s); diff size %d chars",
            len(result.chunks),
            len(result.skipped),
            len(state["raw_diff"]),
        )
        return {"chunks": result.chunks, "skipped_files": result.skipped}

    return prepare_chunks
