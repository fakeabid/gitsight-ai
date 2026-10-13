from app.graph.builder import build_review_graph
from app.schemas.llm import SummaryOut
from tests.helpers import (
    FakeLLM,
    assert_invariants,
    llm_issue,
    make_new_file_diff,
    ok_output,
    paths_in_prompt,
)


def per_path_review(messages):
    return ok_output([llm_issue(p) for p in paths_in_prompt(messages)])


def two_chunk_diff() -> str:  # each file ~2.4 KB; max_chunk_chars is 3,000 in tests
    return make_new_file_diff("src/a.py", ["x" * 45] * 50) + make_new_file_diff(
        "src/b.py", ["x" * 45] * 50
    )


async def run(graph, diff):
    final = await graph.ainvoke(
        {"pr_title": "t", "pr_description": None, "raw_diff": diff},
        config={"max_concurrency": 3},
    )
    return final["result"]


async def test_two_chunks_are_reviewed_merged_and_summarised(settings):
    chunk_llm = FakeLLM(per_path_review)
    summary_llm = FakeLLM(lambda m: SummaryOut(executive_summary="FINAL"))
    graph = build_review_graph(settings=settings, chunk_llm=chunk_llm, summary_llm=summary_llm)
    result = await run(graph, two_chunk_diff())
    assert {i.file_path for i in result.issues} == {"src/a.py", "src/b.py"}
    assert result.executive_summary == "FINAL" and summary_llm.calls == 1
    assert result.meta.chunk_count == 2 and not result.meta.partial
    assert_invariants(result, two_chunk_diff())


async def test_single_chunk_skips_the_summary_call(settings):
    summary_llm = FakeLLM(lambda m: SummaryOut(executive_summary="NO"))
    graph = build_review_graph(
        settings=settings,
        chunk_llm=FakeLLM(lambda m: ok_output(summary="S")),
        summary_llm=summary_llm,
    )
    result = await run(graph, make_new_file_diff("src/a.py", ["x = 1"]))
    assert summary_llm.calls == 0 and result.executive_summary == "S"


async def test_one_failing_chunk_gives_a_partial_result(settings):
    def responder(messages):
        return (
            RuntimeError("boom")
            if "src/b.py" in paths_in_prompt(messages)
            else per_path_review(messages)
        )

    chunk_llm = FakeLLM(responder)
    graph = build_review_graph(
        settings=settings,
        chunk_llm=chunk_llm,
        summary_llm=FakeLLM(lambda m: SummaryOut(executive_summary="x")),
    )
    result = await run(graph, two_chunk_diff())
    assert result.meta.partial and len(result.meta.failed_chunks) == 1
    assert {i.file_path for i in result.issues} == {"src/a.py"}
    assert_invariants(result)


async def test_noise_only_diff_makes_no_llm_call(settings):
    chunk_llm = FakeLLM(per_path_review)
    graph = build_review_graph(
        settings=settings, chunk_llm=chunk_llm, summary_llm=FakeLLM(lambda m: None)
    )
    result = await run(graph, make_new_file_diff("package-lock.json", ["{}"]))
    assert chunk_llm.calls == 0 and result.issues == [] and result.meta.chunk_count == 0
    assert "No reviewable" in result.executive_summary


async def test_parallel_branches_merge_without_state_conflicts(settings):
    diff = "".join(make_new_file_diff(f"src/f{i}.py", ["x" * 45] * 50) for i in range(4))
    graph = build_review_graph(
        settings=settings,
        chunk_llm=FakeLLM(per_path_review),
        summary_llm=FakeLLM(lambda m: SummaryOut(executive_summary="x")),
    )
    result = await run(graph, diff)
    assert len(result.issues) == 4
