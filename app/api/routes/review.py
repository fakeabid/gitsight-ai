from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_review_service, require_api_key
from app.schemas.review import ReviewRequest, ReviewResult
from app.services.review_service import ReviewService

router = APIRouter(tags=["reviews"], dependencies=[Depends(require_api_key)])


@router.post("/v1/reviews", response_model=ReviewResult)
@router.post("/api/reviews", response_model=ReviewResult)
@router.post("/reviews", response_model=ReviewResult)
@router.post("/review", response_model=ReviewResult)
async def create_review(
    payload: ReviewRequest,
    service: Annotated[ReviewService, Depends(get_review_service)],
) -> ReviewResult:
    return await service.review(payload)
