import os

import pytest

from app.core.config import get_settings
from app.graph.builder import build_review_graph
from app.schemas.review import ReviewRequest
from app.services.review_service import ReviewService
from tests.helpers import assert_invariants, make_new_file_diff

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.getenv("RUN_LIVE") != "1", reason="set RUN_LIVE=1 and GEMINI_API_KEY"),
]


async def test_real_gemini_flags_hardcoded_secret():
    diff = make_new_file_diff(
        "src/app.js", ['const API_KEY = "sk-live-1234567890abcdef";', "eval(userInput);"]
    )
    settings = get_settings()
    service = ReviewService(build_review_graph(settings=settings), settings)
    result = await service.review(ReviewRequest(pr_title="Add config", diff=diff))
    assert_invariants(result, diff)
    assert any(
        i.issue_type in {"Breach", "Security"} for i in result.issues
    )  # non-deterministic: keep loose
