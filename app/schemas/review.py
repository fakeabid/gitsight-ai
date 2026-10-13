from typing import Any

from pydantic import Field, model_validator

from app.schemas.common import CamelModel, Complexity, IssueType, Severity


class ReviewRequest(CamelModel):
    pr_title: str = Field(min_length=1, max_length=500)
    pr_description: str | None = None
    diff: str = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _normalize_diff(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "diff" not in data or not data["diff"]:
                alt = data.get("diffText") or data.get("diff_text")
                if alt:
                    data = dict(data)
                    data["diff"] = alt
        return data



class Issue(CamelModel):
    file_path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    issue_type: IssueType
    severity: Severity
    comment: str
    suggested_removed_code: str = ""
    suggested_added_code: str = ""


class SkippedFile(CamelModel):
    path: str
    reason: str


class ReviewMeta(CamelModel):
    """Not in the C# DTO; the caller may ignore it."""

    partial: bool = False
    chunk_count: int = 0
    failed_chunks: list[int] = Field(default_factory=list)
    skipped_files: list[SkippedFile] = Field(default_factory=list)


class ReviewResult(CamelModel):
    issues: list[Issue]
    executive_summary: str
    overall_confidence_score: float = Field(ge=0.0, le=1.0)
    final_suggestions_count: int
    security_issues_count: int
    syntax_errors_count: int = 0
    breaches_count: int
    bugs_count: int
    performance_issues_count: int
    code_smells_count: int
    test_coverage_impact: float
    code_complexity: Complexity
    meta: ReviewMeta = Field(default_factory=ReviewMeta)
