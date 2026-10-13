import secrets

from fastapi import Request, Security
from fastapi.security import APIKeyHeader

from app.core.errors import UnauthorizedError
from app.services.review_service import ReviewService

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(request: Request, provided: str | None = Security(_api_key_header)) -> None:
    expected = request.app.state.settings.service_api_key.get_secret_value()
    if not provided or not secrets.compare_digest(provided.encode(), expected.encode()):
        raise UnauthorizedError("Invalid or missing API key.")


def get_review_service(request: Request) -> ReviewService:
    return request.app.state.review_service
