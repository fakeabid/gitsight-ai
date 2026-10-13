import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.graph.prompts.summary import SUMMARY_SYSTEM_PROMPT, build_summary_user_message
from app.graph.state import ReviewState

logger = logging.getLogger(__name__)


def make_synthesize_summary(llm: Any):
    """`llm` returns a SummaryOut (structured output, include_raw=False)."""

    async def synthesize_summary(state: ReviewState) -> dict:
        outcomes = sorted(state.get("chunk_results", []), key=lambda o: o.index)
        if len(outcomes) <= 1:  # a single chunk summary (or the empty summary) is already final
            return {}
        result = state["result"]
        messages = [
            SystemMessage(content=SUMMARY_SYSTEM_PROMPT),
            HumanMessage(
                content=build_summary_user_message(
                    pr_title=state["pr_title"],
                    pr_description=state.get("pr_description"),
                    chunk_summaries=[o.summary for o in outcomes],
                    issues=result.issues,
                )
            ),
        ]
        try:
            output = await llm.ainvoke(messages)
            summary = output.executive_summary.strip()
        except Exception as exc:  # noqa: BLE001 - fall back to the joined chunk summaries
            logger.warning(
                "Summary synthesis failed (%s); keeping joined chunk summaries", type(exc).__name__
            )
            return {}
        if not summary:
            return {}
        return {"result": result.model_copy(update={"executive_summary": summary})}

    return synthesize_summary
