import asyncio
import json
import logging
from typing import Dict, List, Optional
from urllib.parse import quote

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.config import (
    GEMINI_REQUEST_TIMEOUT_SECONDS,
    LLM_API_BASE_URL,
    LLM_API_KEY,
    LLM_MODEL,
    LLM_PROVIDER,
)
from app.models.brand_guideline import BrandGuideline


logger = logging.getLogger(__name__)
MAX_COMPLETION_TOKENS = 1200
GEMINI_MAX_TRANSPORT_ATTEMPTS = 2
GEMINI_RETRY_DELAY_SECONDS = 0.25


class LLMProviderError(RuntimeError):
    pass


class LLMFinding(BaseModel):
    category: str = Field(min_length=1, max_length=80)
    severity: str
    title: str = Field(min_length=1, max_length=200)
    explanation: str = Field(min_length=1, max_length=2000)
    matched_text: Optional[str] = Field(default=None, max_length=1000)
    suggestion: Optional[str] = Field(default=None, max_length=2000)
    guideline: Optional[str] = Field(default=None, max_length=240)
    confidence: Optional[float] = Field(default=None, ge=0, le=1)

    def validate_severity(self) -> None:
        if self.severity.lower() not in {"low", "medium", "high", "critical"}:
            raise ValueError("LLM returned unsupported severity.")


def llm_enabled() -> bool:
    return bool(LLM_API_BASE_URL and LLM_API_KEY and LLM_MODEL)


def _finding_response_schema() -> Dict[str, object]:
    nullable_string = {"type": ["string", "null"]}
    properties = {
        "category": {"type": "string"},
        "severity": {
            "type": "string",
            "enum": ["low", "medium", "high", "critical"],
        },
        "title": {"type": "string"},
        "explanation": {"type": "string"},
        "matched_text": nullable_string,
        "suggestion": nullable_string,
        "guideline": nullable_string,
        "confidence": {"type": ["number", "null"]},
    }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "brand_review_findings",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "findings": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": properties,
                            "required": list(properties),
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["findings"],
                "additionalProperties": False,
            },
        },
    }


def _gemini_response_schema() -> Dict[str, object]:
    properties = {
        "category": {"type": "STRING"},
        "severity": {
            "type": "STRING",
            "enum": ["low", "medium", "high", "critical"],
        },
        "title": {"type": "STRING"},
        "explanation": {"type": "STRING"},
        "matched_text": {"type": "STRING", "nullable": True},
        "suggestion": {"type": "STRING", "nullable": True},
        "guideline": {"type": "STRING", "nullable": True},
        "confidence": {"type": "NUMBER", "nullable": True},
    }
    return {
        "type": "OBJECT",
        "properties": {
            "findings": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": properties,
                    "required": list(properties),
                },
            }
        },
        "required": ["findings"],
    }


def _validate_findings(
    raw_content: str,
    content: str,
    guidelines: List[BrandGuideline],
) -> List[Dict[str, object]]:
    try:
        decoded = json.loads(raw_content)
        raw_findings = decoded.get("findings")
        if not isinstance(raw_findings, list):
            raise ValueError("Provider response must contain a findings array.")
        validated = []
        guidelines_by_name = {item.name.casefold(): item for item in guidelines}
        for raw in raw_findings:
            finding = LLMFinding.model_validate(raw)
            finding.validate_severity()
            if finding.matched_text and finding.matched_text not in content:
                raise ValueError("Provider finding matched_text is not in submitted content.")
            guideline = guidelines_by_name.get((finding.guideline or "").casefold())
            validated.append(
                {
                    **finding.model_dump(),
                    "severity": finding.severity.lower(),
                    "source": "AI-generated suggestion (configured LLM)",
                    "guideline_id": guideline.id if guideline else None,
                }
            )
    except (json.JSONDecodeError, AttributeError, TypeError, ValueError, ValidationError) as exc:
        logger.warning(
            "LLM analysis provider returned an invalid findings response (%s).",
            type(exc).__name__,
        )
        raise LLMProviderError(
            "Configured LLM provider returned an invalid findings response."
        ) from exc
    return validated


async def _request_gemini(prompt: str) -> str:
    endpoint = "{}/models/{}:generateContent".format(
        LLM_API_BASE_URL,
        quote(LLM_MODEL, safe=""),
    )
    try:
        timeout = httpx.Timeout(
            GEMINI_REQUEST_TIMEOUT_SECONDS,
            connect=min(8.0, float(GEMINI_REQUEST_TIMEOUT_SECONDS)),
        )
        async with httpx.AsyncClient(timeout=timeout) as client:
            for attempt in range(GEMINI_MAX_TRANSPORT_ATTEMPTS):
                try:
                    response = await client.post(
                        endpoint,
                        headers={"x-goog-api-key": LLM_API_KEY},
                        json={
                            "systemInstruction": {
                                "parts": [
                                    {
                                        "text": "You are a cautious brand-compliance reviewer. Findings are advisory."
                                    }
                                ]
                            },
                            "contents": [
                                {"role": "user", "parts": [{"text": prompt}]}
                            ],
                            "generationConfig": {
                                "temperature": 0,
                                "maxOutputTokens": MAX_COMPLETION_TOKENS,
                                "responseMimeType": "application/json",
                                "responseSchema": _gemini_response_schema(),
                            },
                        },
                    )
                    break
                except (httpx.TimeoutException, httpx.ConnectError):
                    if attempt + 1 >= GEMINI_MAX_TRANSPORT_ATTEMPTS:
                        raise
                    logger.warning(
                        "Gemini analysis request encountered a transient transport failure; retrying once."
                    )
                    await asyncio.sleep(GEMINI_RETRY_DELAY_SECONDS)
            response.raise_for_status()
            response_body = response.json()
        if not isinstance(response_body, dict):
            raise ValueError("Gemini response must be an object.")
        prompt_feedback = response_body.get("promptFeedback")
        if isinstance(prompt_feedback, dict) and prompt_feedback.get("blockReason"):
            raise ValueError("Gemini blocked the prompt.")
        candidates = response_body.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ValueError("Gemini response has no candidates.")
        candidate = candidates[0]
        if not isinstance(candidate, dict) or candidate.get("finishReason") != "STOP":
            raise ValueError("Gemini response was refused, incomplete, or unsupported.")
        candidate_content = candidate.get("content")
        parts = (
            candidate_content.get("parts")
            if isinstance(candidate_content, dict)
            else None
        )
        if not isinstance(parts, list):
            raise ValueError("Gemini response has no content parts.")
        text_parts = [
            part["text"]
            for part in parts
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        ]
        if not text_parts or len(text_parts) != len(parts):
            raise ValueError("Gemini response contains unsupported content parts.")
        return "".join(text_parts)
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        detail = (
            "Configured Gemini provider rejected the request (HTTP {}).".format(status_code)
            if status_code
            else "Configured Gemini provider request failed ({}).".format(type(exc).__name__)
        )
        logger.warning("Gemini analysis provider request failed: %s", detail)
        raise LLMProviderError(detail) from exc


async def analyze_with_llm(
    content: str,
    guidelines: List[BrandGuideline],
    evidence: List[Dict[str, object]],
) -> List[Dict[str, object]]:
    rule_context = [
        {
            "name": item.name,
            "category": item.category,
            "description": item.description,
            "severity": item.severity,
            "prohibited_terms": item.prohibited_terms or [],
            "preferred_terms": item.preferred_terms or [],
        }
        for item in guidelines
    ]
    evidence_context = [
        {"name": item.get("name"), "excerpt": item.get("excerpt")}
        for item in evidence[:5]
    ]
    prompt = (
        "Review the submitted content against the supplied brand rules. Identify only "
        "specific, actionable issues. Preserve the author's intent. Do not claim any "
        "factual statement is verified or false; approved excerpts are candidate evidence "
        "only. Return strict JSON with one property, findings, an array whose items have "
        "category, severity (low|medium|high|critical), title, explanation, matched_text "
        "(exact substring of content or null), suggestion, guideline (name or null), and "
        "confidence (0..1 or null). Do not include markdown.\n\n"
        "RULES:\n{}\n\nCANDIDATE EVIDENCE (not authoritative verification):\n{}\n\n"
        "CONTENT:\n{}".format(
            json.dumps(rule_context, ensure_ascii=False),
            json.dumps(evidence_context, ensure_ascii=False),
            content,
        )
    )
    if LLM_PROVIDER == "gemini":
        raw_content = await _request_gemini(prompt)
        return _validate_findings(raw_content, content, guidelines)

    endpoint = "{}/chat/completions".format(LLM_API_BASE_URL)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=8.0)) as client:
            response = await client.post(
                endpoint,
                headers={"Authorization": "Bearer {}".format(LLM_API_KEY)},
                json={
                    "model": LLM_MODEL,
                    "temperature": 0,
                    "max_completion_tokens": MAX_COMPLETION_TOKENS,
                    "response_format": _finding_response_schema(),
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are a cautious brand-compliance reviewer. Findings are advisory.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                },
            )
            response.raise_for_status()
            response_body = response.json()
            if not isinstance(response_body, dict):
                raise ValueError("Provider response must be an object.")
            choices = response_body.get("choices")
            if not isinstance(choices, list) or not choices:
                raise ValueError("Provider response has no choices.")
            choice = choices[0]
            if not isinstance(choice, dict) or choice.get("finish_reason") != "stop":
                raise ValueError("Provider response was incomplete or unsupported.")
            message = choice.get("message")
            if not isinstance(message, dict) or message.get("refusal"):
                raise ValueError("Provider refused or omitted the requested response.")
            raw_content = message.get("content")
            if not isinstance(raw_content, str):
                raise ValueError("Provider response content must be text.")
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        detail = (
            "Configured LLM provider rejected the request (HTTP {}).".format(status_code)
            if status_code
            else "Configured LLM provider request failed ({}).".format(type(exc).__name__)
        )
        logger.warning("LLM analysis provider request failed: %s", detail)
        raise LLMProviderError(detail) from exc

    return _validate_findings(raw_content, content, guidelines)
