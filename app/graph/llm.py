from typing import Any

from langchain_core.runnables import Runnable
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel

from app.core.config import Settings


def build_chat_model(model: str, settings: Settings) -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=settings.gemini_api_key.get_secret_value(),
        temperature=settings.gemini_temperature,
        max_retries=settings.gemini_sdk_max_retries,
        timeout=settings.gemini_timeout_seconds,
    )


def build_structured_llm(
    schema: type[BaseModel], settings: Settings, *, include_raw: bool
) -> Runnable[Any, Any]:
    """Structured-output runnable for every model in settings.model_chain, with fallbacks.

    include_raw=True returns {"raw", "parsed", "parsing_error"} instead of raising on bad output.
    Provider/network errors still raise, and that is what triggers the next fallback model.
    """
    runnables = [
        build_chat_model(model, settings).with_structured_output(schema, include_raw=include_raw)
        for model in settings.model_chain
    ]
    primary, *fallbacks = runnables
    return primary.with_fallbacks(fallbacks) if fallbacks else primary
