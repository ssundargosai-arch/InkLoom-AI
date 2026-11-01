import asyncio
from contextlib import suppress
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Engine, event
from sqlalchemy.orm import Session, sessionmaker
from starlette.types import ASGIApp

from app.config import (
    API_VERSION,
    CORS_ORIGINS,
    FRESHNESS_CHECK_INTERVAL_SECONDS,
)
from app.database import (
    Base,
    engine,
    get_db,
    migrate_guidelines_and_sources,
    migrate_review_workflow,
    migrate_review_json_columns,
    migrate_source_approval,
    migrate_temporal_freshness,
    migrate_secure_publish,
    migrate_brand_voice,
)
from app.models import BrandGuideline
from app.routes import (
    analytics,
    analysis,
    auth,
    guidelines,
    health,
    reviews,
    sources,
    freshness,
    visual_assets,
)
from app.services.auth_service import bootstrap_admin
from app.services.freshness_service import run_freshness_scheduler

SEED_GUIDELINES = [
    {
        "name": "Substantiated promotional claims",
        "category": "claims",
        "description": "Absolute and performance-related promotional claims should be supported by current evidence.",
        "severity": "high",
    },
    {
        "name": "Approved terminology",
        "category": "terminology",
        "description": "Use configured preferred terminology and avoid configured prohibited terms.",
        "severity": "medium",
    },
    {
        "name": "Current factual evidence",
        "category": "factual_claim",
        "description": "Check factual statements against current approved sources; never imply verification without evidence.",
        "severity": "medium",
    },
]


def _enable_sqlite_foreign_keys(target_engine: Engine) -> None:
    if target_engine.dialect.name != "sqlite":
        return

    @event.listens_for(target_engine, "connect")
    def set_sqlite_pragma(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def create_app(database_engine: Engine = engine) -> ASGIApp:
    _enable_sqlite_foreign_keys(database_engine)
    local_sessions = sessionmaker(
        bind=database_engine, autoflush=False, autocommit=False
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        Base.metadata.create_all(bind=database_engine)
        migrate_source_approval(database_engine)
        migrate_review_workflow(database_engine)
        migrate_review_json_columns(database_engine)
        migrate_guidelines_and_sources(database_engine)
        migrate_temporal_freshness(database_engine)
        migrate_secure_publish(database_engine)
        migrate_brand_voice(database_engine)
        db = local_sessions()
        try:
            if db.query(BrandGuideline).count() == 0:
                for item in SEED_GUIDELINES:
                    db.add(
                        BrandGuideline(
                            **item,
                            is_seed=True,
                            last_reviewed_at=datetime.now(timezone.utc),
                        )
                    )
                db.commit()
            bootstrap_admin(db)
        finally:
            db.close()
        scheduler_task = asyncio.create_task(
            run_freshness_scheduler(
                local_sessions, FRESHNESS_CHECK_INTERVAL_SECONDS
            )
        )
        try:
            yield
        finally:
            scheduler_task.cancel()
            with suppress(asyncio.CancelledError):
                await scheduler_task

    app = FastAPI(
        title="InkLoom AI API",
        description=(
            "Brand-governance review API. Rule-based findings are advisory heuristics, "
            "not legal advice, factual verification, or a full accessibility audit."
        ),
        version=API_VERSION,
        lifespan=lifespan,
    )
    @app.middleware("http")
    async def validate_session_request_origin(request, call_next):
        if (
            request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and request.headers.get("origin") is not None
            and request.headers.get("origin") not in CORS_ORIGINS
        ):
            return JSONResponse(
                status_code=403,
                content={"detail": "Request origin is not allowed for this session."},
            )
        return await call_next(request)

    def get_app_db():
        db: Session = local_sessions()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = get_app_db
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(guidelines.router)
    app.include_router(analysis.router)
    app.include_router(reviews.router)
    app.include_router(sources.router)
    app.include_router(freshness.router)
    app.include_router(visual_assets.router)
    app.include_router(analytics.router)
    return CORSMiddleware(
        app=app,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-Reviewer"],
    )


app = create_app()
