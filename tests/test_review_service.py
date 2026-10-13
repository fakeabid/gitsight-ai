import asyncio

import pytest

from app.core.errors import AllChunksFailedError, PayloadTooLargeError, ReviewTimeoutError
from app.domain.results import build_result
from app.graph.builder import build_review_graph
from app.schemas.llm import SummaryOut
from app.schemas.review import ReviewMeta, ReviewRequest
from app.services.review_service import ReviewService
from tests.helpers import FakeLLM, make_new_file_diff, ok_output


class DelayGraph:
    def __init__(self, delay: float) -> None:
        self.delay = delay

    async def ainvoke(self, initial, config=None):
        await asyncio.sleep(self.delay)
        return {"result": None}


class FakeResultGraph:
    def __init__(self, result) -> None:
        self.result = result

    async def ainvoke(self, initial, config=None):
        return {"result": self.result}


async def test_diff_longer_than_max_chars_raises_payload_too_large(settings):
    strict_settings = settings.model_copy(update={"max_diff_chars": 100})
    service = ReviewService(graph=None, settings=strict_settings)
    req = ReviewRequest(pr_title="PR", diff="x" * 150)
    with pytest.raises(PayloadTooLargeError):
        await service.review(req)


async def test_review_timeout_raises_review_timeout_error(settings):
    timeout_settings = settings.model_copy(update={"review_timeout_seconds": 1})
    # simulate timeout with a graph taking longer than timeout
    graph = DelayGraph(delay=2.0)
    service = ReviewService(graph=graph, settings=timeout_settings)
    req = ReviewRequest(pr_title="PR", diff="diff --git a/a b/a\n")
    with pytest.raises(ReviewTimeoutError):
        await service.review(req)


async def test_all_chunks_failed_raises_all_chunks_failed_error(settings):
    result = build_result(
        issues=[],
        summary="failed",
        confidence=0.0,
        complexity="Low",
        test_coverage_impact=0.0,
        meta=ReviewMeta(chunk_count=2, failed_chunks=[1, 2]),
    )
    service = ReviewService(graph=FakeResultGraph(result), settings=settings)
    req = ReviewRequest(pr_title="PR", diff="diff --git a/a b/a\n")
    with pytest.raises(AllChunksFailedError):
        await service.review(req)


async def test_partial_chunks_failed_returns_result_successfully(settings):
    result = build_result(
        issues=[],
        summary="partial",
        confidence=0.5,
        complexity="Low",
        test_coverage_impact=0.0,
        meta=ReviewMeta(chunk_count=2, failed_chunks=[1], partial=True),
    )
    service = ReviewService(graph=FakeResultGraph(result), settings=settings)
    req = ReviewRequest(pr_title="PR", diff="diff --git a/a b/a\n")
    res = await service.review(req)
    assert res.meta.partial is True
    assert res.meta.failed_chunks == [1]


async def test_max_concurrency_is_respected(settings):
    # 4 distinct files each around 2.4 KB (max_chunk_chars is 3000 in test settings)
    diff = "".join(make_new_file_diff(f"src/f{i}.py", ["x" * 45] * 50) for i in range(4))

    # Test with max_concurrency = 2
    llm_2 = FakeLLM(lambda m: ok_output(), delay=0.05)
    s_2 = settings.model_copy(update={"max_concurrency": 2})
    graph_2 = build_review_graph(
        settings=s_2,
        chunk_llm=llm_2,
        summary_llm=FakeLLM(lambda m: SummaryOut(executive_summary="s")),
    )
    service_2 = ReviewService(graph=graph_2, settings=s_2)
    await service_2.review(ReviewRequest(pr_title="PR", diff=diff))
    assert llm_2.max_in_flight == 2

    # Test with max_concurrency = 4
    llm_4 = FakeLLM(lambda m: ok_output(), delay=0.05)
    s_4 = settings.model_copy(update={"max_concurrency": 4})
    graph_4 = build_review_graph(
        settings=s_4,
        chunk_llm=llm_4,
        summary_llm=FakeLLM(lambda m: SummaryOut(executive_summary="s")),
    )
    service_4 = ReviewService(graph=graph_4, settings=s_4)
    await service_4.review(ReviewRequest(pr_title="PR", diff=diff))
    assert llm_4.max_in_flight > 2
