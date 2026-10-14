from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/")
@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
