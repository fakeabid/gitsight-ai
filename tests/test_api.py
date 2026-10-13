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
    res = client(settings).post("/v1/reviews", json=body_diff_text, headers=HEADERS)
    assert res.status_code == 200

    body_diff_text_camel = {"prTitle": "t", "diffText": "diff --git a/a b/a\n"}
    res_camel = client(settings).post("/v1/reviews", json=body_diff_text_camel, headers=HEADERS)
    assert res_camel.status_code == 200



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


def test_authorization_bearer_token_accepted(settings):
    bearer_header = {"Authorization": "Bearer test-key"}
    response = client(settings).post("/v1/reviews", json=BODY, headers=bearer_header)
    assert response.status_code == 200


@pytest.mark.parametrize("path", ["/v1/reviews", "/api/reviews", "/reviews", "/review"])
def test_route_aliases_work(settings, path):
    response = client(settings).post(path, json=BODY, headers=HEADERS)
    assert response.status_code == 200


def test_dotnet_input_json_format_accepted(settings):
    diff = (
        "diff --git a/server/GitSight.Api/Controllers/UsersController.cs "
        "b/server/GitSight.Api/Controllers/UsersController.cs\n"
        "@@ -1,2 +1,3 @@\n-old\n+new"
    )
    payload = {
        "diff_text": diff,
        "pr_title": "Fix user lookup by ID",
        "pr_description": "Switched from FindAsync to raw SQL for performance reasons.",
    }
    response = client(settings).post("/api/reviews", json=payload, headers=HEADERS)
    assert response.status_code == 200


def test_github_structured_files_input_accepted(settings):
    payload = {
        "repository": {"owner": "abc", "name": "my-project"},
        "pullRequest": {"number": 41, "title": "Add authentication"},
        "files": [
            {
                "path": "AuthService.cs",
                "patch": "@@ -10,3 +10,4 @@\n context\n+new_line\n",
                "status": "modified",
            }
        ],
    }
    response = client(settings).post("/api/reviews", json=payload, headers=HEADERS)
    assert response.status_code == 200


def test_response_contains_architecture_changes_fields(settings):
    response = client(settings).post("/v1/reviews", json=BODY, headers=HEADERS)
    data = response.json()
    assert "reviewId" in data
    assert data["status"] == "completed"
    assert "summary" in data
    for k in ("totalIssues", "critical", "high", "medium", "low"):
        assert k in data["summary"]

