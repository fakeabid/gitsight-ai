"""Live check against real Gemini.  Usage: python -m scripts.smoke_test input.json OR sample.diff"""

import asyncio
import json
import sys
from pathlib import Path

from app.core.config import get_settings
from app.graph.builder import build_review_graph
from app.schemas.review import ReviewRequest
from app.services.review_service import ReviewService


async def main(path: str) -> None:
    settings = get_settings()
    service = ReviewService(build_review_graph(settings=settings), settings)
    content = Path(path).read_text(encoding="utf-8")
    if path.endswith(".json"):
        raw_data = json.loads(content)
        request = ReviewRequest.model_validate(raw_data)
    else:
        request = ReviewRequest(pr_title="Smoke test", diff=content)

    result = await service.review(request)
    print(result.model_dump_json(by_alias=True, indent=2))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
