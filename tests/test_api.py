import pytest
from fastapi.testclient import TestClient

from app.core.errors import AllChunksFailedError, PayloadTooLargeError, ReviewTimeoutError
from app.domain.results import build_result
from app.main import create_app
from app.schemas.review import ReviewMeta

BODY = {"prTitle": "t", "prDescription": None, "diff": "diff --git a/a b/a\n"}
HEADERS = {"X-API-Key": "test-key"}


class StubService:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def review(self, request):
        if self.error:
            raise self.error
        return build_result(
            issues=[],
            summary="ok",
            confidence=1.0,
            complexity="Low",
            test_coverage_impact=0.0,
            meta=ReviewMeta(),
        )


def client(settings, error=None) -> TestClient:
    return TestClient(create_app(settings=settings, review_service=StubService(error)))


def test_health_needs_no_auth(settings):
    assert client(settings).get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}])
def test_missing_or_wrong_key_is_401(settings, headers):
    response = client(settings).post("/v1/reviews", json=BODY, headers=headers)
    assert response.status_code == 401 and response.json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize(
    "body", [{}, {"prTitle": "", "diff": "x"}, {"prTitle": "t", "diff": ""}]
)
def test_invalid_body_is_422(settings, body):
    assert client(settings).post("/v1/reviews", json=body, headers=HEADERS).status_code == 422


def test_optional_pr_description_omitted_returns_200(settings):
    body_no_desc = {"prTitle": "t", "diff": "diff --git a/a b/a\n"}
    response = client(settings).post("/v1/reviews", json=body_no_desc, headers=HEADERS)
    assert response.status_code == 200


def test_diff_text_alias_accepted(settings):
    body_diff_text = {"pr_title": "t", "diff_text": "diff --git a/a b/a\n"}
    assert client(settings).post("/v1/reviews", json=body_diff_text, headers=HEADERS).status_code == 200

    body_diff_text_camel = {"prTitle": "t", "diffText": "diff --git a/a b/a\n"}
    assert client(settings).post("/v1/reviews", json=body_diff_text_camel, headers=HEADERS).status_code == 200



def test_success_uses_camel_case_and_includes_meta(settings):
    data = client(settings).post("/v1/reviews", json=BODY, headers=HEADERS).json()
    for key in (
        "issues",
        "executiveSummary",
        "overallConfidenceScore",
        "finalSuggestionsCount",
        "securityIssuesCount",
        "syntaxErrorsCount",
        "breachesCount",
        "bugsCount",
        "performanceIssuesCount",
        "codeSmellsCount",
        "testCoverageImpact",
        "codeComplexity",
        "meta",
    ):
        assert key in data
    assert "final_suggestions_count" not in data


@pytest.mark.parametrize(
    "error,status,code",
    [
        (PayloadTooLargeError("x"), 413, "diff_too_large"),
        (AllChunksFailedError("x"), 502, "llm_unavailable"),
        (ReviewTimeoutError("x"), 504, "review_timeout"),
    ],
)
def test_domain_errors_map_to_http(settings, error, status, code):
    response = client(settings, error).post("/v1/reviews", json=BODY, headers=HEADERS)
    assert response.status_code == status and response.json() == {
        "error": {"code": code, "message": "x"}
    }
