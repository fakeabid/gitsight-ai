"""Domain errors and their HTTP mapping. Routes never build error JSON by hand."""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class ReviewServiceError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class UnauthorizedError(ReviewServiceError):
    status_code = 401
    code = "unauthorized"


class PayloadTooLargeError(ReviewServiceError):
    status_code = 413
    code = "diff_too_large"


class AllChunksFailedError(ReviewServiceError):
    status_code = 502
    code = "llm_unavailable"


class ReviewTimeoutError(ReviewServiceError):
    status_code = 504
    code = "review_timeout"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ReviewServiceError)
    async def _handle_service_error(_: Request, exc: ReviewServiceError) -> JSONResponse:
        logger.warning("Request failed: %s (%s)", exc.code, exc.message)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )
