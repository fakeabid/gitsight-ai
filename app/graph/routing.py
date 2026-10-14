from langgraph.types import Send

from app.graph.state import ReviewState


def dispatch_chunks(state: ReviewState) -> list[Send | str]:
    """Fan out one analyze_chunk per chunk; with no chunks go straight to aggregate."""
    chunks = state.get("chunks", [])
    if not chunks:
        return ["aggregate"]
    return [
        Send(
            "analyze_chunk",
            {
                "chunk": chunk,
                "pr_title": state["pr_title"],
                "pr_description": state.get("pr_description"),
                "custom_rules": state.get("custom_rules", []),
            },
        )
        for chunk in chunks
    ]
