import pytest
from pydantic import ValidationError

from app.core.config import DEFAULT_NOISE_PATTERNS, Settings


def test_default_values_match_csharp_ports():
    s = Settings(
        service_api_key="key1",
        gemini_api_key="key2",
        _env_file=None,
    )
    assert s.max_chunk_chars == 15_000
    assert s.max_total_chunks == 5
    assert len(s.noise_patterns) == 21
    assert s.noise_patterns == list(DEFAULT_NOISE_PATTERNS)
    assert s.gemini_temperature == 0.2
    assert s.gemini_model == "gemini-3.8-flash"


def test_fallback_models_parse_csv_and_json():
    csv_settings = Settings(
        service_api_key="key1",
        gemini_api_key="key2",
        gemini_fallback_models="model-a, model-b",
        _env_file=None,
    )
    assert csv_settings.gemini_fallback_models == ["model-a", "model-b"]

    json_settings = Settings(
        service_api_key="key1",
        gemini_api_key="key2",
        gemini_fallback_models='["model-a", "model-b"]',
        _env_file=None,
    )
    assert json_settings.gemini_fallback_models == ["model-a", "model-b"]


def test_model_chain_order_and_deduplication():
    s = Settings(
        service_api_key="key1",
        gemini_api_key="key2",
        gemini_model="primary-model",
        gemini_fallback_models=["fallback-1", "primary-model", "fallback-2"],
        _env_file=None,
    )
    assert s.model_chain == ["primary-model", "fallback-1", "fallback-2"]


def test_missing_required_keys_raises_validation_error():
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
        )

    with pytest.raises(ValidationError):
        Settings(
            service_api_key="key1",
            _env_file=None,
        )


def test_repr_does_not_leak_secrets(settings):
    text = repr(settings)
    assert "test-key" not in text
    assert "fake-key" not in text
    assert "**********" in text
