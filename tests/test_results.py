import pytest

from app.domain.results import build_result, dedupe_issues, max_complexity, sort_issues
from app.schemas.review import Issue, ReviewMeta
from tests.helpers import assert_invariants


def make_issue(
    file_path="src/a.py",
    start=1,
    end=1,
    issue_type="Bug",
    severity="Medium",
    comment="comment",
) -> Issue:
    return Issue(
        file_path=file_path,
        start_line=start,
        end_line=end,
        issue_type=issue_type,
        severity=severity,
        comment=comment,
    )


def test_dedupe_issues_removes_duplicates_and_preserves_distinct_types():
    i1 = make_issue(start=5, end=6, issue_type="Bug", comment="c1")
    i2 = make_issue(start=5, end=6, issue_type="Bug", comment="c2")  # duplicate key
    i3 = make_issue(start=5, end=6, issue_type="Security", comment="c3")  # different type
    i4 = make_issue(start=10, end=11, issue_type="Bug", comment="c4")

    deduped = dedupe_issues([i1, i2, i3, i4])
    assert len(deduped) == 3
    assert deduped == [i1, i3, i4]


def test_sort_issues_by_severity_file_and_start_line():
    i_low = make_issue(file_path="src/z.py", start=1, severity="Low")
    i_crit_b = make_issue(file_path="src/b.py", start=10, severity="Critical")
    i_crit_a = make_issue(file_path="src/a.py", start=20, severity="Critical")
    i_crit_a_early = make_issue(file_path="src/a.py", start=5, severity="Critical")
    i_high = make_issue(file_path="src/a.py", start=1, severity="High")
    i_med = make_issue(file_path="src/a.py", start=1, severity="Medium")

    sorted_list = sort_issues([i_low, i_crit_b, i_crit_a, i_crit_a_early, i_high, i_med])
    assert sorted_list == [i_crit_a_early, i_crit_a, i_crit_b, i_high, i_med, i_low]


def test_max_complexity_ranking():
    assert max_complexity(["Low", "High", "Medium"]) == "High"
    assert max_complexity(["Low", "Medium"]) == "Medium"
    assert max_complexity(["Low"]) == "Low"
    assert max_complexity([]) == "Low"


@pytest.mark.parametrize(
    "types,expected_counts",
    [
        (
            ["Security", "Breach", "Bug", "Performance", "CodeSmell"],
            {"Security": 1, "Breach": 1, "Bug": 1, "Performance": 1, "CodeSmell": 1},
        ),
        (
            ["Security", "Security", "Bug"],
            {"Security": 2, "Breach": 0, "Bug": 1, "Performance": 0, "CodeSmell": 0},
        ),
        (
            [],
            {"Security": 0, "Breach": 0, "Bug": 0, "Performance": 0, "CodeSmell": 0},
        ),
        (
            ["Breach", "Breach", "Breach"],
            {"Security": 0, "Breach": 3, "Bug": 0, "Performance": 0, "CodeSmell": 0},
        ),
    ],
)
def test_build_result_counts_and_invariants(types, expected_counts):
    issues = [make_issue(issue_type=t) for t in types]
    res = build_result(
        issues=issues,
        summary="Summary text",
        confidence=0.854,
        complexity="Medium",
        test_coverage_impact=0.123,
        meta=ReviewMeta(),
    )
    assert_invariants(res)
    assert res.final_suggestions_count == len(issues)
    assert res.security_issues_count == expected_counts["Security"]
    assert res.breaches_count == expected_counts["Breach"]
    assert res.bugs_count == expected_counts["Bug"]
    assert res.performance_issues_count == expected_counts["Performance"]
    assert res.code_smells_count == expected_counts["CodeSmell"]
    assert res.syntax_errors_count == 0
    assert res.overall_confidence_score == 0.85
    assert res.test_coverage_impact == 0.12


def test_confidence_clamped_and_rounded():
    res_high = build_result(
        issues=[],
        summary="ok",
        confidence=1.5,
        complexity="Low",
        test_coverage_impact=0.0,
        meta=ReviewMeta(),
    )
    assert res_high.overall_confidence_score == 1.0

    res_low = build_result(
        issues=[],
        summary="ok",
        confidence=-0.5,
        complexity="Low",
        test_coverage_impact=0.0,
        meta=ReviewMeta(),
    )
    assert res_low.overall_confidence_score == 0.0
