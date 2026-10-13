from app.graph.chunk_subgraph import build_chunk_subgraph
from tests.helpers import FakeLLM, bad_output, llm_issue, make_chunk, ok_output

INPUT = lambda: {"chunk": make_chunk(), "pr_title": "t", "pr_description": None}  # noqa: E731


async def test_success_emits_one_outcome(settings):
    llm = FakeLLM(lambda m: ok_output([llm_issue("src/a.py")]))
    out = await build_chunk_subgraph(llm, settings).ainvoke(INPUT())
    assert [o.index for o in out["chunk_results"]] == [1]
    assert out.get("failed_chunks", []) == []


async def test_unparseable_output_is_retried_then_succeeds(settings):
    answers = iter([bad_output(), ok_output([llm_issue("src/a.py")])])
    llm = FakeLLM(lambda m: next(answers))
    out = await build_chunk_subgraph(llm, settings).ainvoke(INPUT())
    assert llm.calls == 2 and len(out["chunk_results"]) == 1


async def test_exhausted_retries_record_a_failure(settings):
    llm = FakeLLM(lambda m: RuntimeError("429"))
    out = await build_chunk_subgraph(llm, settings).ainvoke(INPUT())
    assert llm.calls == 1 + settings.chunk_max_retries
    assert out["failed_chunks"] == [1] and out.get("chunk_results", []) == []


async def test_hallucinated_paths_are_dropped(settings):
    llm = FakeLLM(lambda m: ok_output([llm_issue("src/a.py"), llm_issue("nope/other.py")]))
    out = await build_chunk_subgraph(llm, settings).ainvoke(INPUT())
    assert [i.file_path for i in out["chunk_results"][0].issues] == ["src/a.py"]


async def test_prompt_has_system_message_and_part_label(settings):
    llm = FakeLLM(lambda m: ok_output())
    await build_chunk_subgraph(llm, settings).ainvoke(INPUT())
    system, human = llm.last_messages
    assert system.type == "system" and human.type == "human"
    assert "Part 1 of 1" in human.content and "src/a.py" in human.content
