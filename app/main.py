from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import health, review
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import setup_logging
from app.graph.builder import build_review_graph
from app.services.review_service import ReviewService


def create_app(
    settings: Settings | None = None, review_service: ReviewService | None = None
) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app.state.review_service is None:  # tests inject a fake instead
            app.state.review_service = ReviewService(
                build_review_graph(settings=settings), settings
            )
        yield

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.state.settings = settings
    app.state.review_service = review_service
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(review.router)
    return app
