from typing import Any

from langgraph.graph import END, START, StateGraph

from app.core.config import Settings
from app.graph.chunk_subgraph import build_chunk_subgraph
from app.graph.llm import build_structured_llm
from app.graph.nodes.aggregate import aggregate
from app.graph.nodes.prepare_chunks import make_prepare_chunks
from app.graph.nodes.synthesize_summary import make_synthesize_summary
from app.graph.routing import dispatch_chunks
from app.graph.state import ReviewState
from app.schemas.llm import ChunkReview, SummaryOut


def build_review_graph(*, settings: Settings, chunk_llm: Any = None, summary_llm: Any = None):
    """Compile the review graph. Pass fakes for `chunk_llm` / `summary_llm` in tests."""
    chunk_llm = chunk_llm or build_structured_llm(ChunkReview, settings, include_raw=True)
    summary_llm = summary_llm or build_structured_llm(SummaryOut, settings, include_raw=False)

    graph = StateGraph(ReviewState)
    graph.add_node("prepare_chunks", make_prepare_chunks(settings))
    graph.add_node("analyze_chunk", build_chunk_subgraph(chunk_llm, settings))
    graph.add_node("aggregate", aggregate)
    graph.add_node("synthesize_summary", make_synthesize_summary(summary_llm))

    graph.add_edge(START, "prepare_chunks")
    graph.add_conditional_edges("prepare_chunks", dispatch_chunks, ["analyze_chunk", "aggregate"])
    graph.add_edge("analyze_chunk", "aggregate")
    graph.add_edge("aggregate", "synthesize_summary")
    graph.add_edge("synthesize_summary", END)
    return graph.compile()
