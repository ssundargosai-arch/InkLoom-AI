import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
OPTIONAL_SETTINGS = {
    "LLM_API_BASE_URL": "",
    "LLM_API_KEY": "",
    "LLM_MODEL": "",
    "LLM_PROVIDER": "openai",
    "GEMINI_REQUEST_TIMEOUT_SECONDS": "",
    "EMBEDDING_MODEL": "",
    "MAX_RETRIEVAL_CHUNKS": "",
    "FACT_CHECK_PROVIDER": "",
    "FACT_CHECK_API_KEY": "",
    "TRUSTED_SOURCE_DOMAINS": "",
    "BRAND_PALETTE": "",
    "PALETTE_TOLERANCE": "",
    "MAX_IMAGE_PIXELS": "",
    "BRAND_ASSET_REFERENCE_PATHS": "",
}


def _run_config(overrides=None, script="import app.config as config"):
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "PYTHON_DOTENV_DISABLED": "1",
        **OPTIONAL_SETTINGS,
        **(overrides or {}),
    }
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND_DIR,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_missing_optional_provider_settings_preserve_local_fallback():
    result = _run_config(
        script=(
            "import json; import app.config as c; "
            "print(json.dumps({"
            "'llm': c.LLM_ENABLED, "
            "'llm_provider': c.LLM_PROVIDER, "
            "'gemini_timeout': c.GEMINI_REQUEST_TIMEOUT_SECONDS, "
            "'embeddings': c.EMBEDDINGS_ENABLED, "
            "'external_fact_check': c.FACT_CHECK_ENABLED, "
            "'palette': c.BRAND_PALETTE, "
            "'references': c.BRAND_ASSET_REFERENCES, "
            "'retrieval_limit': c.MAX_RETRIEVAL_CHUNKS, "
            "'palette_tolerance': c.PALETTE_TOLERANCE, "
            "'max_image_pixels': c.MAX_IMAGE_PIXELS"
            "}))"
        )
    )

    assert result.returncode == 0, result.stderr
    settings = json.loads(result.stdout)
    assert settings == {
        "llm": False,
        "llm_provider": "openai",
        "gemini_timeout": 90,
        "embeddings": False,
        "external_fact_check": False,
        "palette": [],
        "references": [],
        "retrieval_limit": 200,
        "palette_tolerance": 36,
        "max_image_pixels": 40_000_000,
    }


def test_optional_provider_and_visual_settings_parse_without_network_calls():
    result = _run_config(
        {
            "LLM_API_BASE_URL": "https://provider.example/v1",
            "LLM_API_KEY": "test-key",
            "LLM_MODEL": "test-chat-model",
            "EMBEDDING_MODEL": "test-embedding-model",
            "MAX_RETRIEVAL_CHUNKS": "12",
            "FACT_CHECK_PROVIDER": "brave",
            "FACT_CHECK_API_KEY": "test-fact-key",
            "TRUSTED_SOURCE_DOMAINS": "example.org, news.example.net",
            "BRAND_PALETTE": "#112233,445566",
            "PALETTE_TOLERANCE": "24",
            "MAX_IMAGE_PIXELS": "123456",
        },
        script=(
            "import json; import app.config as c; "
            "print(json.dumps({"
            "'llm': c.LLM_ENABLED, "
            "'llm_provider': c.LLM_PROVIDER, "
            "'gemini_timeout': c.GEMINI_REQUEST_TIMEOUT_SECONDS, "
            "'embeddings': c.EMBEDDINGS_ENABLED, "
            "'external_fact_check': c.FACT_CHECK_ENABLED, "
            "'domains': c.TRUSTED_SOURCE_DOMAINS, "
            "'palette': c.BRAND_PALETTE, "
            "'retrieval_limit': c.MAX_RETRIEVAL_CHUNKS, "
            "'palette_tolerance': c.PALETTE_TOLERANCE, "
            "'max_image_pixels': c.MAX_IMAGE_PIXELS"
            "}))"
        ),
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "llm": True,
        "llm_provider": "openai",
        "gemini_timeout": 90,
        "embeddings": True,
        "external_fact_check": True,
        "domains": ["example.org", "news.example.net"],
        "palette": ["#112233", "445566"],
        "retrieval_limit": 12,
        "palette_tolerance": 24,
        "max_image_pixels": 123456,
    }


def test_gemini_configuration_enables_chat_but_preserves_lexical_retrieval():
    result = _run_config(
        {
            "LLM_PROVIDER": "gemini",
            "LLM_API_BASE_URL": (
                "https://generativelanguage.googleapis.com/v1beta"
            ),
            "LLM_API_KEY": "test-key",
            "LLM_MODEL": "gemini-3.8-flash",
            "EMBEDDING_MODEL": "test-embedding-model",
        },
        script=(
            "import json; import app.config as c; "
            "print(json.dumps({"
            "'llm': c.LLM_ENABLED, "
            "'llm_provider': c.LLM_PROVIDER, "
            "'gemini_timeout': c.GEMINI_REQUEST_TIMEOUT_SECONDS, "
            "'embeddings': c.EMBEDDINGS_ENABLED"
            "}))"
        ),
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "llm": True,
        "llm_provider": "gemini",
        "gemini_timeout": 90,
        "embeddings": False,
    }


@pytest.mark.parametrize(
    ("setting", "value", "message"),
    [
        ("MAX_RETRIEVAL_CHUNKS", "not-a-number", "must be an integer"),
        ("MAX_RETRIEVAL_CHUNKS", "0", "must be at least 1"),
        ("PALETTE_TOLERANCE", "442", "must be between 0 and 441"),
        ("MAX_IMAGE_PIXELS", "0", "must be at least 1"),
        ("BRAND_PALETTE", "#12345G", "six-digit hex colours"),
        ("TRUSTED_SOURCE_DOMAINS", "https://example.org", "bare DNS domain names"),
        ("FACT_CHECK_PROVIDER", "unknown", "must be empty or 'brave'"),
        ("LLM_API_BASE_URL", "provider.example/v1", "HTTP or HTTPS base URL"),
        ("LLM_PROVIDER", "unknown", "must be 'openai' or 'gemini'"),
        ("GEMINI_REQUEST_TIMEOUT_SECONDS", "not-a-number", "must be an integer"),
        ("GEMINI_REQUEST_TIMEOUT_SECONDS", "0", "must be between 1 and 300"),
        ("GEMINI_REQUEST_TIMEOUT_SECONDS", "301", "must be between 1 and 300"),
    ],
)
def test_invalid_optional_configuration_fails_startup(
    setting, value, message
):
    result = _run_config({setting: value})

    assert result.returncode != 0
    assert message in result.stderr


@pytest.mark.parametrize(
    ("base_url", "model"),
    [
        ("https://provider.example/v1", "gemini-model"),
        (
            "https://generativelanguage.googleapis.com/v1beta",
            "provider-model",
        ),
    ],
)
def test_gemini_requires_official_endpoint_and_gemini_model(base_url, model):
    result = _run_config(
        {
            "LLM_PROVIDER": "gemini",
            "LLM_API_BASE_URL": base_url,
            "LLM_API_KEY": "test-key",
            "LLM_MODEL": model,
        }
    )

    assert result.returncode != 0
