from pydantic import BaseModel, Field

from app.schemas.common import Complexity, IssueType, Severity


class LLMIssue(BaseModel):
    file_path: str = Field(
        description="Path exactly as in the diff header, WITHOUT the a/ or b/ prefix."
    )
    start_line: int = Field(description="First affected line number in the NEW file.")
    end_line: int = Field(description="Last affected line number in the NEW file (>= start_line).")
    issue_type: IssueType
    severity: Severity
    comment: str = Field(
        description="Clear, concise explanation: what is wrong, why it matters, how to fix it."
    )
    suggested_removed_code: str = Field(
        description="Exact code from the diff to remove or replace. Empty string if not applicable."
    )
    suggested_added_code: str = Field(
        description="Concrete replacement code. Empty string if not applicable."
    )


class ChunkReview(BaseModel):
    issues: list[LLMIssue]
    executive_summary: str = Field(
        description="2-3 sentence overview of this part of the PR and its code quality."
    )
    overall_confidence_score: float = Field(description="Confidence in this review, 0.0 to 1.0.")
    code_complexity: Complexity
    test_coverage_impact: float = Field(
        description="Estimated effect on test coverage, -1.0 to 1.0. Use 0.0 if unknown."
    )


class SummaryOut(BaseModel):
    executive_summary: str = Field(
        description="Concise 2-3 sentence overview of the whole PR's purpose and code quality."
    )
