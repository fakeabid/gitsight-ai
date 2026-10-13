"""Find which available model currently works and has remaining quota."""

import asyncio

from pydantic import BaseModel

from app.core.config import get_settings
from app.graph.llm import build_chat_model

CANDIDATES = [
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
    "gemini-pro-latest",
    "gemini-2.5-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3-flash-preview",
]


class Ping(BaseModel):
    message: str


async def test_model(model_name: str, settings) -> bool:
    try:
        chat = build_chat_model(model_name, settings)
        structured = chat.with_structured_output(Ping)
        res = await structured.ainvoke("Hi")
        print(f"  [SUCCESS] {model_name:<30} -> {res.message}")
        return True
    except Exception as exc:
        err_msg = str(exc)
        if "403" in err_msg or "PERMISSION_DENIED" in err_msg:
            status = "403 Permission Denied"
        elif "404" in err_msg or "NOT_FOUND" in err_msg:
            status = "404 Not Found"
        elif "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
            status = "429 Quota Exhausted"
        else:
            status = type(exc).__name__
        print(f"  [FAILED]  {model_name:<30} -> {status}")
        return False


async def main() -> None:
    settings = get_settings()
    print("Testing candidate models for remaining quota...\n")
    working = []
    for model in CANDIDATES:
        ok = await test_model(model, settings)
        if ok:
            working.append(model)
        await asyncio.sleep(0.5)

    print("\n--------------------------------------------------")
    if working:
        print(f"Found WORKING models with available quota: {working}")
        print(f"Recommended setting for .env: GEMINI_MODEL={working[0]}")
    else:
        print("None of the tested models succeeded.")
    print("--------------------------------------------------")


if __name__ == "__main__":
    asyncio.run(main())
