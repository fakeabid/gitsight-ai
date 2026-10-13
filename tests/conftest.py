import pytest

from app.core.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        service_api_key="test-key",
        gemini_api_key="fake-key",
        retry_backoff_seconds=0.0,
        max_chunk_chars=3_000,
        max_total_chunks=5,
        chunk_max_retries=2,
        _env_file=None,  # never read a developer's real .env in tests
    )
