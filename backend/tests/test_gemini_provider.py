import asyncio
import json

import httpx
import pytest

from app.services import llm_analyzer

ORIGINAL_ASYNC_CLIENT = httpx.AsyncClient


def _configure_mock_gemini(monkeypatch, handler):
    monkeypatch.setattr(llm_analyzer, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(llm_analyzer, "GEMINI_REQUEST_TIMEOUT_SECONDS", 90)
    monkeypatch.setattr(
        llm_analyzer,
        "LLM_API_BASE_URL",
        "https://generativelanguage.googleapis.com/v1beta",
    )
    monkeypatch.setattr(llm_analyzer, "LLM_API_KEY", "test-gemini-key")
    monkeypatch.setattr(llm_analyzer, "LLM_MODEL", "gemini-test-model")

    transport = httpx.MockTransport(handler)
    captured_timeouts = []

    def mocked_client(*args, **kwargs):
        captured_timeouts.append(kwargs["timeout"])
        kwargs["transport"] = transport
        return ORIGINAL_ASYNC_CLIENT(*args, **kwargs)

    monkeypatch.setattr(llm_analyzer.httpx, "AsyncClient", mocked_client)
    return captured_timeouts


def test_gemini_provider_sends_native_structured_request(monkeypatch):
    async def handle_request(request):
        assert request.url.path.endswith(
            "/v1beta/models/gemini-test-model:generateContent"
        )
        assert request.headers["x-goog-api-key"] == "test-gemini-key"
        assert "authorization" not in request.headers
        body = json.loads(request.content)
        assert body["contents"][0]["role"] == "user"
        assert body["systemInstruction"]["parts"][0]["text"].endswith(
            "Findings are advisory."
        )
        generation_config = body["generationConfig"]
        assert generation_config["temperature"] == 0
        assert generation_config["maxOutputTokens"] == 1200
        assert generation_config["responseMimeType"] == "application/json"
        schema = generation_config["responseSchema"]
        assert schema["type"] == "OBJECT"
        assert schema["required"] == ["findings"]
        finding_properties = schema["properties"]["findings"]["items"]["properties"]
        assert finding_properties["severity"]["enum"] == [
            "low",
            "medium",
            "high",
            "critical",
        ]
        assert finding_properties["suggestion"]["nullable"] is True
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "role": "model",
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "findings": [
                                                {
                                                    "category": "tone_of_voice",
                                                    "severity": "medium",
                                                    "title": "Check the tone",
                                                    "explanation": "Possible tone issue.",
                                                    "matched_text": "sample draft",
                                                    "suggestion": None,
                                                    "guideline": None,
                                                    "confidence": 0.6,
                                                }
                                            ]
                                        }
                                    )
                                }
                            ],
                        },
                    }
                ]
            },
        )

    timeouts = _configure_mock_gemini(monkeypatch, handle_request)
    findings = asyncio.run(
        llm_analyzer.analyze_with_llm("A sample draft.", [], [])
    )
    assert len(findings) == 1
    assert findings[0]["source"] == "AI-generated suggestion (configured LLM)"
    assert len(timeouts) == 1
    assert timeouts[0].read == 90
    assert timeouts[0].connect == 8


@pytest.mark.parametrize(
    "response_body",
    [
        {"promptFeedback": {"blockReason": "SAFETY"}},
        {
            "candidates": [
                {
                    "finishReason": "SAFETY",
                    "content": {"parts": [{"text": '{"findings": []}'}]},
                }
            ]
        },
        {
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {"parts": [{"text": "not-json"}]},
                }
            ]
        },
        {
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps(
                                    {
                                        "findings": [
                                            {
                                                "category": "claim",
                                                "severity": "high",
                                                "title": "Unsupported",
                                                "explanation": "Invalid phrase.",
                                                "matched_text": "not present",
                                                "suggestion": None,
                                                "guideline": None,
                                                "confidence": 0.9,
                                            }
                                        ]
                                    }
                                )
                            }
                        ]
                    },
                }
            ]
        },
    ],
)
def test_gemini_blocked_invalid_or_unverifiable_response_fails_safe(
    monkeypatch, response_body
):
    async def handle_request(_request):
        return httpx.Response(200, json=response_body)

    _configure_mock_gemini(monkeypatch, handle_request)
    with pytest.raises(llm_analyzer.LLMProviderError):
        asyncio.run(llm_analyzer.analyze_with_llm("A sample draft.", [], []))


def test_gemini_api_error_and_timeout_are_secret_safe(monkeypatch, caplog):
    api_error_attempts = 0

    async def api_error(_request):
        nonlocal api_error_attempts
        api_error_attempts += 1
        return httpx.Response(429, json={"error": {"message": "quota"}})

    _configure_mock_gemini(monkeypatch, api_error)
    with pytest.raises(llm_analyzer.LLMProviderError, match="HTTP 429"):
        asyncio.run(llm_analyzer.analyze_with_llm("draft", [], []))
    assert api_error_attempts == 1
    assert "test-gemini-key" not in caplog.text
    assert "draft" not in caplog.text

    timeout_attempts = 0

    async def timeout(_request):
        nonlocal timeout_attempts
        timeout_attempts += 1
        raise httpx.ReadTimeout("test-gemini-key draft")

    _configure_mock_gemini(monkeypatch, timeout)
    with pytest.raises(llm_analyzer.LLMProviderError, match="ReadTimeout"):
        asyncio.run(llm_analyzer.analyze_with_llm("draft", [], []))
    assert timeout_attempts == 2
    assert "test-gemini-key" not in caplog.text
    assert "draft" not in caplog.text


def test_gemini_retries_once_after_timeout_then_returns_success(monkeypatch):
    attempts = 0

    async def handle_request(_request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ReadTimeout("transient response timeout")
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [{"text": json.dumps({"findings": []})}]
                        },
                    }
                ]
            },
        )

    _configure_mock_gemini(monkeypatch, handle_request)
    findings = asyncio.run(
        llm_analyzer.analyze_with_llm("A sample draft.", [], [])
    )

    assert attempts == 2
    assert findings == []


def test_gemini_retries_once_after_connection_error(monkeypatch):
    attempts = 0

    async def handle_request(_request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("temporary connection failure")
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [{"text": json.dumps({"findings": []})}]
                        },
                    }
                ]
            },
        )

    _configure_mock_gemini(monkeypatch, handle_request)
    findings = asyncio.run(
        llm_analyzer.analyze_with_llm("A sample draft.", [], [])
    )

    assert attempts == 2
    assert findings == []


def test_gemini_provider_error_keeps_deterministic_analysis_available(
    client, monkeypatch
):
    attempts = 0

    async def timeout(_request):
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("provider response timed out")

    _configure_mock_gemini(monkeypatch, timeout)
    response = client.post(
        "/api/analyze",
        json={
            "content": (
                "Our service guarantees 100% success for every customer."
            )
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["analysis_engine"] == "rules"
    assert any(
        finding["category"] == "unsupported_claim"
        for finding in result["findings"]
    )
    assert any(
        "Gemini provider request failed (ReadTimeout)" in warning
        for warning in result["provider_warnings"]
    )
    assert attempts == 2
