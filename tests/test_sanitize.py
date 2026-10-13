import pytest

from app.domain.sanitize import resolve_path, sanitize_issues
from tests.helpers import llm_issue


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("src/app.py", "src/app.py"),
        ("a/src/app.py", "src/app.py"),
        ("b/src/app.py", "src/app.py"),
        ("./src/app.py", "src/app.py"),
        ("src\\app.py", "src/app.py"),
        ("a/src\\app.py", "src/app.py"),
    ],
)
def test_path_resolution_variants(raw, expected):
    allowed = {"src/app.py"}
    assert resolve_path(raw, allowed) == expected


def test_unknown_path_returns_none_and_issue_is_dropped():
    allowed = {"src/valid.py"}
    assert resolve_path("unknown/file.py", allowed) is None

    issues = [
        llm_issue(path="unknown/file.py"),
        llm_issue(path="src/valid.py"),
    ]
    cleaned = sanitize_issues(issues, allowed)
    assert len(cleaned) == 1
    assert cleaned[0].file_path == "src/valid.py"


def test_empty_or_whitespace_comment_dropped():
    allowed = {"src/app.py"}
    issues = [
        llm_issue(path="src/app.py", comment=""),
        llm_issue(path="src/app.py", comment="   \n\t  "),
        llm_issue(path="src/app.py", comment="Valid comment"),
    ]
    cleaned = sanitize_issues(issues, allowed)
    assert len(cleaned) == 1
    assert cleaned[0].comment == "Valid comment"


def test_line_numbers_clamped_and_ordered():
    allowed = {"src/app.py"}
    issues = [
        llm_issue(path="src/app.py", start=0, end=-5),
        llm_issue(path="src/app.py", start=10, end=5),
        llm_issue(path="src/app.py", start=15, end=20),
    ]
    cleaned = sanitize_issues(issues, allowed)
    assert len(cleaned) == 3
    # start_line=0 -> 1, end_line < start_line -> end_line == start_line
    assert cleaned[0].start_line == 1
    assert cleaned[0].end_line == 1

    assert cleaned[1].start_line == 10
    assert cleaned[1].end_line == 10

    assert cleaned[2].start_line == 15
    assert cleaned[2].end_line == 20


def test_fields_carried_over_accurately():
    allowed = {"src/app.py"}
    raw = llm_issue(
        path="src/app.py",
        start=5,
        end=8,
        issue_type="Security",
        severity="Critical",
        comment="SQL injection possible",
        suggested_removed_code="query = f'SELECT...'",
        suggested_added_code="query = 'SELECT...'",
    )
    cleaned = sanitize_issues([raw], allowed)[0]
    assert cleaned.issue_type == "Security"
    assert cleaned.severity == "Critical"
    assert cleaned.comment == "SQL injection possible"
    assert cleaned.suggested_removed_code == "query = f'SELECT...'"
    assert cleaned.suggested_added_code == "query = 'SELECT...'"
