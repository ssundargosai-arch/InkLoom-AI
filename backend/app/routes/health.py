from fastapi import APIRouter

from app.config import API_VERSION, BRAND_ASSET_REFERENCES, EMBEDDINGS_ENABLED
from app.config import AUTH_COOKIE_SECURE, BOOTSTRAP_ADMIN_EMAIL
from app.config import (
    BRAND_PALETTE,
    FACT_CHECK_ENABLED,
    FACT_CHECK_PROVIDER,
    OCR_ENABLED,
    PALETTE_TOLERANCE,
    SMTP_ENABLED,
    TRUSTED_SOURCE_DOMAINS,
)
from app.services.llm_analyzer import llm_enabled

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health():
    return {
        "status": "ok",
        "version": API_VERSION,
        "authentication_enabled": True,
        "secure_auth_cookie": AUTH_COOKIE_SECURE,
        "bootstrap_admin_configured": bool(BOOTSTRAP_ADMIN_EMAIL),
        "password_recovery_enabled": SMTP_ENABLED,
        "analysis_mode": "rules+configured_llm" if llm_enabled() else "rules",
        "evidence_retrieval_mode": (
            "embedding_cosine" if EMBEDDINGS_ENABLED else "bm25_lexical"
        ),
        "embedding_model_configured": EMBEDDINGS_ENABLED,
        "external_fact_check_configured": FACT_CHECK_ENABLED,
        "external_fact_check_provider": FACT_CHECK_PROVIDER or None,
        "trusted_source_domains": list(TRUSTED_SOURCE_DOMAINS),
        "ocr_enabled": OCR_ENABLED,
        "brand_palette_configured": bool(BRAND_PALETTE),
        "palette_tolerance": PALETTE_TOLERANCE if BRAND_PALETTE else None,
        "brand_palette": BRAND_PALETTE,
        "brand_asset_references_configured": len(BRAND_ASSET_REFERENCES),
        "collaboration": "websocket_process_local",
    }
