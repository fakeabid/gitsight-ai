"""Turn raw LLM issues into API issues, dropping the ones we cannot trust."""

import logging
from collections.abc import Collection, Iterable

from app.schemas.llm import LLMIssue
from app.schemas.review import Issue

logger = logging.getLogger(__name__)


def resolve_path(raw: str, allowed: Collection[str]) -> str | None:
    """Map the model's path onto a path that really is in the diff (or None)."""
    candidate = raw.strip().replace("\\", "/")
    for variant in (
        candidate,
        candidate.removeprefix("./"),
        candidate.removeprefix("a/"),
        candidate.removeprefix("b/"),
    ):
        if variant in allowed:
            return variant
    return None


def sanitize_issues(issues: Iterable[LLMIssue], allowed_paths: Collection[str]) -> list[Issue]:
    clean: list[Issue] = []
    for raw in issues:
        path = resolve_path(raw.file_path, allowed_paths)
        comment = raw.comment.strip()
        if path is None or not comment:
            logger.info(
                "Dropping unusable issue (path=%r, has_comment=%s)",
                raw.file_path,
                bool(comment),
            )
            continue
        start = max(1, raw.start_line)
        end = max(start, raw.end_line)
        clean.append(
            Issue(
                file_path=path,
                start_line=start,
                end_line=end,
                issue_type=raw.issue_type,
                severity=raw.severity,
                comment=comment,
                suggested_removed_code=raw.suggested_removed_code,
                suggested_added_code=raw.suggested_added_code,
            )
        )
    return clean
