from typing import Any

from langgraph.graph import END, START, StateGraph

from app.core.config import Settings
from app.graph.nodes.chunk_nodes import (
    build_prompt,
    make_call_llm,
    make_route_after_validate,
    record_failure,
    validate,
)
from app.graph.state import ChunkInput, ChunkOutput, ChunkState


def build_chunk_subgraph(llm: Any, settings: Settings):
    graph = StateGraph(ChunkState, input_schema=ChunkInput, output_schema=ChunkOutput)
    graph.add_node("build_prompt", build_prompt)
    graph.add_node("call_llm", make_call_llm(llm, settings))
    graph.add_node("validate", validate)
    graph.add_node("record_failure", record_failure)

    graph.add_edge(START, "build_prompt")
    graph.add_edge("build_prompt", "call_llm")
    graph.add_edge("call_llm", "validate")
    graph.add_conditional_edges(
        "validate",
        make_route_after_validate(settings),
        {END: END, "call_llm": "call_llm", "record_failure": "record_failure"},
    )
    graph.add_edge("record_failure", END)
    return graph.compile()
