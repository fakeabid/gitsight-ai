import re
import uuid
from typing import Any, Literal

from pydantic import Field, model_validator

from app.schemas.common import CamelModel, Complexity, IssueType, Severity


class ReviewRequest(CamelModel):
    pr_title: str = Field(min_length=1, max_length=500)
    pr_description: str | None = None
    diff: str = Field(min_length=1)
    repository: dict[str, Any] | None = None
    pull_request: dict[str, Any] | None = None
    files: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] | None = None
    graceful_failure: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_request(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)

            # 1. Resolve Title
            if "pr_title" not in data and "prTitle" not in data:
                title = data.get("title")
                pr_obj = data.get("pull_request") or data.get("pullRequest")
                if not title and isinstance(pr_obj, dict):
                    title = pr_obj.get("title") or pr_obj.get("pr_title") or pr_obj.get("prTitle")
                if title:
                    data["pr_title"] = title

            # 2. Resolve Description
            if "pr_description" not in data and "prDescription" not in data:
                desc = data.get("description")
                pr_obj = data.get("pull_request") or data.get("pullRequest")
                if not desc and isinstance(pr_obj, dict):
                    desc = (
                        pr_obj.get("description")
                        or pr_obj.get("pr_description")
                        or pr_obj.get("body")
                    )
                if desc:
                    data["pr_description"] = desc

            # 3. Resolve Diff
            diff = data.get("diff") or data.get("diff_text") or data.get("diffText")
            files = data.get("files")
            if not diff and isinstance(files, list) and files:
                diff_parts: list[str] = []
                for f in files:
                    if not isinstance(f, dict):
                        continue
                    path = f.get("path") or f.get("file_path") or f.get("filename") or "unknown"
                    patch = f.get("patch") or f.get("diff") or f.get("content") or ""
                    if patch:
                        if not patch.startswith("diff --git"):
                            header = f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
                            hunk = f"{header}{patch.strip()}\n"
                        else:
                            hunk = patch.strip() + "\n"
                        diff_parts.append(hunk)
                diff = "".join(diff_parts)

            if diff:
                if "diff --git " not in diff and "--- " in diff and "+++" in diff:
                    m = re.search(r"^\+\+\+ [b/]*(.+)$", diff, re.MULTILINE)
                    if m:
                        extracted_path = m.group(1).strip()
                        diff = f"diff --git a/{extracted_path} b/{extracted_path}\n{diff}"
                data["diff"] = diff

        return data


class Issue(CamelModel):
    file_path: str
    file: str = ""
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    issue_type: IssueType
    category: str = ""
    severity: Severity
    title: str = ""
    comment: str
    description: str = ""
    suggestion: str = ""
    suggested_removed_code: str = ""
    suggested_added_code: str = ""
    confidence: float = 0.9

    @model_validator(mode="before")
    @classmethod
    def _normalize_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            fp = data.get("file_path") or data.get("filePath") or data.get("file") or ""
            data["file_path"] = fp
            data["file"] = data.get("file") or fp

            it = data.get("issue_type") or data.get("issueType") or data.get("category") or "Bug"
            data["issue_type"] = it
            data["category"] = data.get("category") or it

            cmt = data.get("comment") or data.get("description") or ""
            data["comment"] = cmt
            data["description"] = data.get("description") or cmt

            if not data.get("title"):
                first_line = cmt.strip().split("\n")[0] if cmt else f"{it} issue"
                data["title"] = first_line[:100]

            if not data.get("suggestion"):
                added = data.get("suggested_added_code") or data.get("suggestedAddedCode") or ""
                data["suggestion"] = added or cmt
        return data


class SkippedFile(CamelModel):
    path: str
    reason: str


class ReviewMeta(CamelModel):
    """Not in the C# DTO; the caller may ignore it."""

    partial: bool = False
    chunk_count: int = 0
    failed_chunks: list[int] = Field(default_factory=list)
    skipped_files: list[SkippedFile] = Field(default_factory=list)


class IssueSeveritySummary(CamelModel):
    total_issues: int = 0
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0


class ReviewResult(CamelModel):
    review_id: str = Field(default_factory=lambda: f"rv_{uuid.uuid4().hex[:12]}")
    status: Literal["completed", "failed", "queued", "processing"] = "completed"
    error_code: str | None = None
    retryable: bool = False
    summary: IssueSeveritySummary = Field(default_factory=IssueSeveritySummary)
    issues: list[Issue] = Field(default_factory=list)
    executive_summary: str = ""
    overall_confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    final_suggestions_count: int = 0
    security_issues_count: int = 0
    syntax_errors_count: int = 0
    breaches_count: int = 0
    bugs_count: int = 0
    performance_issues_count: int = 0
    code_smells_count: int = 0
    test_coverage_impact: float = 0.0
    code_complexity: Complexity = "Low"
    meta: ReviewMeta = Field(default_factory=ReviewMeta)

    @classmethod
    def failure(
        cls,
        *,
        error_code: str = "AI_TEMPORARILY_UNAVAILABLE",
        message: str = "Review failed due to AI provider unavailability. Please retry.",
        retryable: bool = True,
        review_id: str | None = None,
        meta: ReviewMeta | None = None,
    ) -> "ReviewResult":
        return cls(
            review_id=review_id or f"rv_{uuid.uuid4().hex[:12]}",
            status="failed",
            error_code=error_code,
            retryable=retryable,
            executive_summary=message,
            meta=meta or ReviewMeta(),
        )
