"""Quick 1-call model tester to verify quota and structured output."""

import asyncio
import sys

from pydantic import BaseModel

from app.core.config import get_settings
from app.graph.llm import build_chat_model


class TestResponse(BaseModel):
    message: str


async def main(model_name: str) -> None:
    settings = get_settings()
    print(f"Testing model '{model_name}'...")
    try:
        chat = build_chat_model(model_name, settings)
        structured = chat.with_structured_output(TestResponse)
        response = await structured.ainvoke("Say hello in one word.")
        print(f"SUCCESS with {model_name}! Response: {response}")
    except Exception as exc:
        print(f"FAILED with {model_name}: {type(exc).__name__} - {exc}")


if __name__ == "__main__":
    model = sys.argv[1] if len(sys.argv) > 1 else "gemini-3.7-flash"
    asyncio.run(main(model))
