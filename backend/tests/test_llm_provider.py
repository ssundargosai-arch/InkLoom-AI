import asyncio
import json

import httpx
import pytest

from app.services import llm_analyzer


def _configure_mock_provider(monkeypatch, handler):
    monkeypatch.setattr(llm_analyzer, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(
        llm_analyzer, "LLM_API_BASE_URL", "https://provider.test/v1"
    )
    monkeypatch.setattr(llm_analyzer, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(llm_analyzer, "LLM_MODEL", "test-chat-model")

    original_client = llm_analyzer.httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def mocked_client(*args, **kwargs):
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(llm_analyzer.httpx, "AsyncClient", mocked_client)


def test_llm_chat_provider_uses_mocked_openai_compatible_endpoint(monkeypatch):
    async def handle_request(request):
        assert request.url.path == "/v1/chat/completions"
        authorization = request.headers.get("authorization", "")
        scheme, _, credential = authorization.partition(" ")
        assert scheme.lower() == "bearer"
        assert credential == "test-key"
        body = json.loads(request.content)
        assert body["model"] == "test-chat-model"
        assert body["temperature"] == 0
        assert body["max_completion_tokens"] == 1200
        assert body["response_format"]["type"] == "json_schema"
        assert body["response_format"]["json_schema"]["strict"] is True
        assert body["response_format"]["json_schema"]["schema"][
            "additionalProperties"
        ] is False
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "findings": [
                                        {
                                            "category": "tone_of_voice",
                                            "severity": "low",
                                            "title": "Review tone",
                                            "explanation": "A possible tone mismatch.",
                                            "matched_text": "sample draft",
                                            "suggestion": None,
                                            "guideline": None,
                                            "confidence": 0.7,
                                        }
                                    ]
                                }
                            )
                        },
                    }
                ]
            },
        )

    _configure_mock_provider(monkeypatch, handle_request)

    result = asyncio.run(
        llm_analyzer.analyze_with_llm("A sample draft.", [], [])
    )
    assert len(result) == 1
    assert result[0]["source"] == "AI-generated suggestion (configured LLM)"


@pytest.mark.parametrize(
    "response_body",
    [
        {"choices": []},
        {
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {"content": '{"findings": []}'},
                }
            ]
        },
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"refusal": "Cannot comply", "content": None},
                }
            ]
        },
        {
            "choices": [
                {"finish_reason": "stop", "message": {"content": "not-json"}}
            ]
        },
    ],
)
def test_unsupported_or_invalid_provider_responses_raise_safe_error(
    monkeypatch, response_body
):
    async def handle_request(_request):
        return httpx.Response(200, json=response_body)

    _configure_mock_provider(monkeypatch, handle_request)

    with pytest.raises(llm_analyzer.LLMProviderError):
        asyncio.run(llm_analyzer.analyze_with_llm("A sample draft.", [], []))


def test_provider_timeout_logs_no_key_or_content(monkeypatch, caplog):
    async def handle_request(_request):
        raise httpx.ReadTimeout("test-key A sample draft.")

    _configure_mock_provider(monkeypatch, handle_request)

    with pytest.raises(llm_analyzer.LLMProviderError, match="ReadTimeout"):
        asyncio.run(
            llm_analyzer.analyze_with_llm("A sample draft.", [], [])
        )

    assert "test-key" not in caplog.text
    assert "A sample draft." not in caplog.text
