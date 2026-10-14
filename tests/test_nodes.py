import pytest

from app.domain.diff_chunker import (
    REASON_LIMIT_FULL,
    REASON_NOISE,
    Chunk,
)
from app.domain.results import build_result
from app.graph.nodes.aggregate import EMPTY_SUMMARY, aggregate
from app.graph.nodes.prepare_chunks import make_prepare_chunks
from app.graph.nodes.synthesize_summary import make_synthesize_summary
from app.graph.state import ChunkOutcome, ReviewState
from app.schemas.llm import SummaryOut
from app.schemas.review import Issue, ReviewMeta, SkippedFile
from tests.helpers import FakeLLM, make_new_file_diff


def test_prepare_chunks_node(settings):
    test_settings = settings.model_copy(update={"noise_patterns": ["package-lock.json"]})
    prepare = make_prepare_chunks(test_settings)
    diff = (
        make_new_file_diff("src/a.py", ["x = 1"])
        + make_new_file_diff("package-lock.json", ["{}"])
    )
    state: ReviewState = {"raw_diff": diff}
    out = prepare(state)
    assert len(out["chunks"]) == 1
    assert out["chunks"][0].file_paths == ("src/a.py",)
    assert len(out["skipped_files"]) == 1
    assert out["skipped_files"][0].path == "package-lock.json"


def test_aggregate_merges_sorts_and_computes_stats():
    i1 = Issue(
        file_path="src/b.py",
        start_line=10,
        end_line=10,
        issue_type="Bug",
        severity="Low",
        comment="c1",
    )
    i2 = Issue(
        file_path="src/a.py",
        start_line=5,
        end_line=5,
        issue_type="Security",
        severity="Critical",
        comment="c2",
    )
    # duplicate issue in outcome 2
    i3 = Issue(
        file_path="src/b.py",
        start_line=10,
        end_line=10,
        issue_type="Bug",
        severity="Low",
        comment="c1_dup",
    )

    o1 = ChunkOutcome(
        index=1,
        issues=[i1],
        summary="Summary 1.",
        confidence=0.8,
        complexity="Low",
        test_coverage_impact=0.2,
    )
    o2 = ChunkOutcome(
        index=2,
        issues=[i2, i3],
        summary="Summary 2.",
        confidence=0.6,
        complexity="High",
        test_coverage_impact=-0.4,
    )

    chunks = [
        Chunk(index=1, total=2, text="", file_paths=("src/b.py",)),
        Chunk(index=2, total=2, text="", file_paths=("src/a.py",)),
    ]

    state: ReviewState = {
        "chunk_results": [o2, o1],  # unordered
        "chunks": chunks,
        "skipped_files": [SkippedFile(path="p.lock", reason=REASON_NOISE)],
        "failed_chunks": [],
    }

    res_dict = aggregate(state)
    res = res_dict["result"]
    assert len(res.issues) == 2
    assert res.issues[0] == i2  # Critical first
    assert res.issues[1] == i1
    assert res.executive_summary == "Summary 1. Summary 2."
    assert res.overall_confidence_score == 0.70  # mean(0.8, 0.6)
    assert res.code_complexity == "High"  # max("Low", "High")
    assert res.test_coverage_impact == -0.10  # mean(0.2, -0.4)
    assert not res.meta.partial  # noise skip does not cause partial


def test_aggregate_partial_flag_on_failure_or_limit():
    state_failed: ReviewState = {
        "chunk_results": [],
        "chunks": [Chunk(index=1, total=1, text="", file_paths=())],
        "failed_chunks": [1],
    }
    assert aggregate(state_failed)["result"].meta.partial is True
    assert aggregate(state_failed)["result"].overall_confidence_score == 0.0

    state_limit: ReviewState = {
        "chunk_results": [],
        "chunks": [Chunk(index=1, total=1, text="", file_paths=())],
        "skipped_files": [SkippedFile(path="src/extra.py", reason=REASON_LIMIT_FULL)],
    }
    assert aggregate(state_limit)["result"].meta.partial is True


def test_aggregate_empty_diff_and_no_chunks():
    state_empty: ReviewState = {
        "chunk_results": [],
        "chunks": [],
        "skipped_files": [],
    }
    res = aggregate(state_empty)["result"]
    assert res.executive_summary == EMPTY_SUMMARY
    assert res.overall_confidence_score == 1.0
    assert res.issues == []


@pytest.mark.asyncio
async def test_synthesize_summary_skips_when_at_most_one_outcome():
    called = False

    def responder(m):
        nonlocal called
        called = True
        return SummaryOut(executive_summary="New summary")

    llm = FakeLLM(responder)
    node = make_synthesize_summary(llm)

    # 0 outcomes
    state_0: ReviewState = {"chunk_results": []}
    assert await node(state_0) == {}
    assert not called

    # 1 outcome
    o = ChunkOutcome(
        index=1,
        issues=[],
        summary="Only chunk",
        confidence=1.0,
        complexity="Low",
        test_coverage_impact=0.0,
    )
    state_1: ReviewState = {
        "chunk_results": [o],
        "result": build_result(
            issues=[],
            summary="Only chunk",
            confidence=1.0,
            complexity="Low",
            test_coverage_impact=0.0,
            meta=ReviewMeta(),
        ),
    }
    assert await node(state_1) == {}
    assert not called


@pytest.mark.asyncio
async def test_synthesize_summary_replaces_summary_when_multiple_outcomes():
    llm = FakeLLM(lambda m: SummaryOut(executive_summary="Unified executive summary."))
    node = make_synthesize_summary(llm)

    o1 = ChunkOutcome(
        index=1,
        issues=[],
        summary="Part 1",
        confidence=1.0,
        complexity="Low",
        test_coverage_impact=0.0,
    )
    o2 = ChunkOutcome(
        index=2,
        issues=[],
        summary="Part 2",
        confidence=1.0,
        complexity="Low",
        test_coverage_impact=0.0,
    )
    state: ReviewState = {
        "pr_title": "PR Title",
        "pr_description": "PR Desc",
        "chunk_results": [o1, o2],
        "result": build_result(
            issues=[],
            summary="Part 1 Part 2",
            confidence=1.0,
            complexity="Low",
            test_coverage_impact=0.0,
            meta=ReviewMeta(),
        ),
    }

    out = await node(state)
    assert out["result"].executive_summary == "Unified executive summary."


@pytest.mark.asyncio
async def test_synthesize_summary_fallback_on_llm_error_or_empty():
    failing_llm = FakeLLM(lambda m: RuntimeError("LLM error"))
    node = make_synthesize_summary(failing_llm)

    o1 = ChunkOutcome(
        index=1,
        issues=[],
        summary="Part 1",
        confidence=1.0,
        complexity="Low",
        test_coverage_impact=0.0,
    )
    o2 = ChunkOutcome(
        index=2,
        issues=[],
        summary="Part 2",
        confidence=1.0,
        complexity="Low",
        test_coverage_impact=0.0,
    )
    state: ReviewState = {
        "pr_title": "PR Title",
        "pr_description": None,
        "chunk_results": [o1, o2],
        "result": build_result(
            issues=[],
            summary="Part 1 Part 2",
            confidence=1.0,
            complexity="Low",
            test_coverage_impact=0.0,
            meta=ReviewMeta(),
        ),
    }
    assert await node(state) == {}

    empty_llm = FakeLLM(lambda m: SummaryOut(executive_summary="   "))
    node_empty = make_synthesize_summary(empty_llm)
    assert await node_empty(state) == {}
