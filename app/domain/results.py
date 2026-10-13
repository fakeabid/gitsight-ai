"""Merging, ordering and counting. The single source of truth for ReviewResult counts."""

import uuid
from collections.abc import Iterable
from typing import Literal

from app.schemas.common import COMPLEXITY_ORDER, SEVERITY_ORDER, Complexity
from app.schemas.review import Issue, IssueSeveritySummary, ReviewMeta, ReviewResult


def dedupe_issues(issues: Iterable[Issue]) -> list[Issue]:
    seen: set[tuple[str, int, int, str]] = set()
    unique: list[Issue] = []
    for issue in issues:
        key = (issue.file_path, issue.start_line, issue.end_line, issue.issue_type)
        if key not in seen:
            seen.add(key)
            unique.append(issue)
    return unique


def sort_issues(issues: Iterable[Issue]) -> list[Issue]:
    return sorted(
        issues,
        key=lambda i: (SEVERITY_ORDER.index(i.severity), i.file_path, i.start_line),
    )


def max_complexity(values: Iterable[Complexity]) -> Complexity:
    ranks = [COMPLEXITY_ORDER.index(v) for v in values]
    return COMPLEXITY_ORDER[max(ranks)] if ranks else "Low"  # type: ignore[return-value]


def build_result(
    *,
    issues: list[Issue],
    summary: str,
    confidence: float,
    complexity: Complexity,
    test_coverage_impact: float,
    meta: ReviewMeta,
    review_id: str | None = None,
    status: Literal["completed", "failed", "queued", "processing"] = "completed",
    error_code: str | None = None,
    retryable: bool = False,
) -> ReviewResult:
    def count(kind: str) -> int:
        return sum(1 for issue in issues if issue.issue_type == kind)

    def count_severity(sev: str) -> int:
        return sum(1 for issue in issues if issue.severity.lower() == sev.lower())

    summary_counts = IssueSeveritySummary(
        total_issues=len(issues),
        critical=count_severity("Critical"),
        high=count_severity("High"),
        medium=count_severity("Medium"),
        low=count_severity("Low"),
    )

    return ReviewResult(
        review_id=review_id or f"rv_{uuid.uuid4().hex[:12]}",
        status=status,
        error_code=error_code,
        retryable=retryable,
        summary=summary_counts,
        issues=issues,
        executive_summary=summary,
        overall_confidence_score=round(min(1.0, max(0.0, confidence)), 2),
        final_suggestions_count=len(issues),
        security_issues_count=count("Security"),
        syntax_errors_count=0,
        breaches_count=count("Breach"),
        bugs_count=count("Bug"),
        performance_issues_count=count("Performance"),
        code_smells_count=count("CodeSmell"),
        test_coverage_impact=round(test_coverage_impact, 2),
        code_complexity=complexity,
        meta=meta,
    )
