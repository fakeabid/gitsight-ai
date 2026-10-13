import operator
from dataclasses import dataclass
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage

from app.domain.diff_chunker import Chunk
from app.schemas.common import Complexity
from app.schemas.llm import ChunkReview
from app.schemas.review import Issue, ReviewResult, SkippedFile


@dataclass(frozen=True)
class ChunkOutcome:
    """Sanitised result of one successfully reviewed chunk."""

    index: int
    issues: list[Issue]
    summary: str
    confidence: float
    complexity: Complexity
    test_coverage_impact: float


class ReviewState(TypedDict, total=False):
    pr_title: str
    pr_description: str | None
    raw_diff: str
    chunks: list[Chunk]
    skipped_files: list[SkippedFile]
    chunk_results: Annotated[list[ChunkOutcome], operator.add]
    failed_chunks: Annotated[list[int], operator.add]
    result: ReviewResult


class ChunkInput(TypedDict):
    """Payload of Send("analyze_chunk", ...)."""

    chunk: Chunk
    pr_title: str
    pr_description: str | None


class ChunkOutput(TypedDict):
    """The ONLY keys the subgraph hands back to the parent."""

    chunk_results: Annotated[list[ChunkOutcome], operator.add]
    failed_chunks: Annotated[list[int], operator.add]


class ChunkState(ChunkInput, ChunkOutput, total=False):
    messages: list[BaseMessage]
    parsed: ChunkReview | None
    error: str | None
    attempts: int
