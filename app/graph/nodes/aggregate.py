import logging
from statistics import fmean

from app.domain.diff_chunker import LIMIT_REASONS
from app.domain.results import build_result, dedupe_issues, max_complexity, sort_issues
from app.graph.state import ReviewState
from app.schemas.review import ReviewMeta

logger = logging.getLogger(__name__)

EMPTY_SUMMARY = (
    "No reviewable code changes were found: every file in this diff was generated, "
    "binary, or excluded by the noise filters."
)


def aggregate(state: ReviewState) -> dict:
    outcomes = sorted(state.get("chunk_results", []), key=lambda o: o.index)
    chunks = state.get("chunks", [])
    skipped = state.get("skipped_files", [])
    failed = sorted(state.get("failed_chunks", []))

    issues = sort_issues(dedupe_issues(issue for o in outcomes for issue in o.issues))
    summary = " ".join(o.summary for o in outcomes if o.summary) or EMPTY_SUMMARY
    if outcomes:
        confidence = fmean(o.confidence for o in outcomes)
        coverage = fmean(o.test_coverage_impact for o in outcomes)
    else:
        confidence = 1.0 if not chunks else 0.0  # nothing to review vs. everything failed
        coverage = 0.0

    meta = ReviewMeta(
        partial=bool(failed) or any(s.reason in LIMIT_REASONS for s in skipped),
        chunk_count=len(chunks),
        failed_chunks=failed,
        skipped_files=skipped,
    )
    result = build_result(
        issues=issues,
        summary=summary,
        confidence=confidence,
        complexity=max_complexity(o.complexity for o in outcomes),
        test_coverage_impact=coverage,
        meta=meta,
    )
    logger.info(
        "Aggregated %d issue(s) from %d/%d chunk(s)", len(issues), len(outcomes), len(chunks)
    )
    return {"result": result}
