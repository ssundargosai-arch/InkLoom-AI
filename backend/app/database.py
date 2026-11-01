from sqlalchemy import Boolean, Date, DateTime, Integer, JSON, String, Text, create_engine, inspect
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import DATABASE_URL

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def migrate_source_approval(target_engine) -> None:
    inspector = inspect(target_engine)
    if not inspector.has_table("source_documents"):
        return

    columns = {column["name"] for column in inspector.get_columns("source_documents")}
    source_table = target_engine.dialect.identifier_preparer.quote("source_documents")
    additions = {
        "approval_status": (String(24), "NOT NULL DEFAULT 'pending'"),
        "reviewed_by_id": (
            Integer(),
            "REFERENCES users(id) ON DELETE SET NULL",
        ),
        "reviewed_at": (DateTime(timezone=True), ""),
        "review_note": (Text(), ""),
    }
    with target_engine.begin() as connection:
        for name, (column_type, constraints) in additions.items():
            if name in columns:
                continue
            quoted_name = target_engine.dialect.identifier_preparer.quote(name)
            definition = "{} {}".format(
                column_type.compile(dialect=target_engine.dialect), constraints
            ).strip()
            connection.exec_driver_sql(
                "ALTER TABLE {} ADD COLUMN {} {}".format(
                    source_table, quoted_name, definition
                )
            )


def migrate_review_workflow(target_engine) -> None:
    inspector = inspect(target_engine)
    additions = {
        "content_reviews": {
            "assigned_reviewer_id": (
                Integer(),
                "REFERENCES users(id) ON DELETE SET NULL",
            ),
            "submitted_by_id": (
                Integer(),
                "REFERENCES users(id) ON DELETE SET NULL",
            ),
        },
        "review_revisions": {
            "author_id": (
                Integer(),
                "REFERENCES users(id) ON DELETE SET NULL",
            ),
        },
        "review_approval_decisions": {
            "version_id": (Integer(), "NOT NULL DEFAULT 0"),
        },
        "review_approval_bypasses": {
            "version_id": (Integer(), "NOT NULL DEFAULT 0"),
        },
        "review_comments": {
            "is_internal": (Boolean(), "NOT NULL DEFAULT 0"),
            "parent_id": (
                Integer(),
                "REFERENCES review_comments(id) ON DELETE CASCADE",
            ),
        },
    }
    preparer = target_engine.dialect.identifier_preparer
    with target_engine.begin() as connection:
        for table_name, columns_to_add in additions.items():
            if not inspector.has_table(table_name):
                continue
            existing = {
                column["name"] for column in inspector.get_columns(table_name)
            }
            quoted_table = preparer.quote(table_name)
            for name, (column_type, constraints) in columns_to_add.items():
                if name in existing:
                    continue
                quoted_name = preparer.quote(name)
                definition = "{} {}".format(
                    column_type.compile(dialect=target_engine.dialect),
                    constraints,
                ).strip()
                connection.exec_driver_sql(
                    "ALTER TABLE {} ADD COLUMN {} {}".format(
                        quoted_table, quoted_name, definition
                    )
                )


def migrate_review_json_columns(target_engine) -> None:
    additions = {
        "review_approval_decisions": ("acknowledged_warning_ids", "[]"),
        "review_visual_attachments": ("analysis_metadata", "{}"),
    }
    preparer = target_engine.dialect.identifier_preparer
    with target_engine.begin() as connection:
        for table_name, (column_name, default_json) in additions.items():
            quoted_table = preparer.quote(table_name)
            if target_engine.dialect.name == "sqlite":
                table_info = connection.exec_driver_sql(
                    "PRAGMA table_info({})".format(quoted_table)
                )
                existing_columns = {row[1] for row in table_info}
            else:
                inspector = inspect(connection)
                if not inspector.has_table(table_name):
                    continue
                existing_columns = {
                    column["name"]
                    for column in inspector.get_columns(table_name)
                }

            if column_name in existing_columns:
                continue

            quoted_column = preparer.quote(column_name)
            json_type = JSON().compile(dialect=target_engine.dialect)
            connection.exec_driver_sql(
                "ALTER TABLE {} ADD COLUMN {} {} NOT NULL DEFAULT '{}'".format(
                    quoted_table,
                    quoted_column,
                    json_type,
                    default_json,
                )
            )


def migrate_guidelines_and_sources(target_engine) -> None:
    inspector = inspect(target_engine)
    preparer = target_engine.dialect.identifier_preparer
    additions = {
        "brand_guidelines": {
            "examples": (JSON(), "NOT NULL DEFAULT '[]'"),
            "is_active": (Boolean(), "NOT NULL DEFAULT 1"),
            "created_by_id": (Integer(), "REFERENCES users(id) ON DELETE SET NULL"),
            "updated_by_id": (Integer(), "REFERENCES users(id) ON DELETE SET NULL"),
            "updated_at": (DateTime(timezone=True), ""),
        },
        "source_documents": {
            "description": (Text(), ""),
            "source_type": (String(48), "NOT NULL DEFAULT 'document'"),
            "is_active": (Boolean(), "NOT NULL DEFAULT 1"),
            "created_by_id": (Integer(), "REFERENCES users(id) ON DELETE SET NULL"),
            "updated_by_id": (Integer(), "REFERENCES users(id) ON DELETE SET NULL"),
            "updated_at": (DateTime(timezone=True), ""),
        },
    }
    existing_columns = {}
    for table_name in additions:
        if inspector.has_table(table_name):
            existing_columns[table_name] = {
                column["name"] for column in inspector.get_columns(table_name)
            }
    with target_engine.begin() as connection:
        for table_name, columns_to_add in additions.items():
            if table_name not in existing_columns:
                continue
            existing = existing_columns[table_name]
            quoted_table = preparer.quote(table_name)
            for name, (column_type, constraints) in columns_to_add.items():
                if name in existing:
                    continue
                quoted_name = preparer.quote(name)
                definition = "{} {}".format(
                    column_type.compile(dialect=target_engine.dialect), constraints
                ).strip()
                connection.exec_driver_sql(
                    "ALTER TABLE {} ADD COLUMN {} {}".format(
                        quoted_table, quoted_name, definition
                    )
                )
                if name == "updated_at" and "created_at" in existing:
                    connection.exec_driver_sql(
                        "UPDATE {} SET {} = created_at WHERE {} IS NULL".format(
                            quoted_table, quoted_name, quoted_name
                        )
                    )


def migrate_temporal_freshness(target_engine) -> None:
    inspector = inspect(target_engine)
    preparer = target_engine.dialect.identifier_preparer
    additions = {
        "source_documents": {
            "valid_from": (Date(), ""),
            "valid_until": (Date(), ""),
            "review_interval_days": (Integer(), "NOT NULL DEFAULT 90"),
            "last_verified_at": (DateTime(timezone=True), ""),
        },
        "brand_guidelines": {
            "review_interval_days": (Integer(), "NOT NULL DEFAULT 180"),
            "last_reviewed_at": (DateTime(timezone=True), ""),
            "last_reviewed_by_id": (
                Integer(),
                "REFERENCES users(id) ON DELETE SET NULL",
            ),
        },
    }
    existing_columns = {}
    for table_name in additions:
        if inspector.has_table(table_name):
            existing_columns[table_name] = {
                column["name"] for column in inspector.get_columns(table_name)
            }

    with target_engine.begin() as connection:
        for table_name, columns_to_add in additions.items():
            existing = existing_columns.get(table_name)
            if existing is None:
                continue
            quoted_table = preparer.quote(table_name)
            for name, (column_type, constraints) in columns_to_add.items():
                if name in existing:
                    continue
                quoted_name = preparer.quote(name)
                definition = "{} {}".format(
                    column_type.compile(dialect=target_engine.dialect),
                    constraints,
                ).strip()
                connection.exec_driver_sql(
                    "ALTER TABLE {} ADD COLUMN {} {}".format(
                        quoted_table, quoted_name, definition
                    )
                )

        source_columns = existing_columns.get("source_documents", set())
        if source_columns:
            source_table = preparer.quote("source_documents")
            for new_column, legacy_column in (
                ("valid_from", "source_date"),
                ("valid_until", "expiry_date"),
            ):
                if legacy_column in source_columns:
                    quoted_new = preparer.quote(new_column)
                    quoted_legacy = preparer.quote(legacy_column)
                    connection.exec_driver_sql(
                        "UPDATE {} SET {} = {} WHERE {} IS NULL".format(
                            source_table, quoted_new, quoted_legacy, quoted_new
                        )
                    )
            if "reviewed_at" in source_columns and "approval_status" in source_columns:
                connection.exec_driver_sql(
                    "UPDATE {} SET {} = {} WHERE {} IS NULL AND {} = 'approved'".format(
                        source_table,
                        preparer.quote("last_verified_at"),
                        preparer.quote("reviewed_at"),
                        preparer.quote("last_verified_at"),
                        preparer.quote("approval_status"),
                    )
                )

        guideline_columns = existing_columns.get("brand_guidelines", set())
        if guideline_columns:
            guideline_table = preparer.quote("brand_guidelines")
            if "updated_at" in guideline_columns:
                connection.exec_driver_sql(
                    "UPDATE {} SET {} = {} WHERE {} IS NULL".format(
                        guideline_table,
                        preparer.quote("last_reviewed_at"),
                        preparer.quote("updated_at"),
                        preparer.quote("last_reviewed_at"),
                    )
                )
            elif "created_at" in guideline_columns:
                connection.exec_driver_sql(
                    "UPDATE {} SET {} = {} WHERE {} IS NULL".format(
                        guideline_table,
                        preparer.quote("last_reviewed_at"),
                        preparer.quote("created_at"),
                        preparer.quote("last_reviewed_at"),
                    )
                )
            if "updated_by_id" in guideline_columns:
                connection.exec_driver_sql(
                    "UPDATE {} SET {} = {} WHERE {} IS NULL".format(
                        guideline_table,
                        preparer.quote("last_reviewed_by_id"),
                        preparer.quote("updated_by_id"),
                        preparer.quote("last_reviewed_by_id"),
                    )
                )


def migrate_secure_publish(target_engine) -> None:
    inspector = inspect(target_engine)
    if not inspector.has_table("content_reviews"):
        return
    Base.metadata.create_all(
        bind=target_engine,
        tables=[
            table
            for table in Base.metadata.sorted_tables
            if table.name in {
                "review_publications",
                "review_publish_audit_events",
            }
        ],
    )


def migrate_brand_voice(target_engine) -> None:
    if not inspect(target_engine).has_table("brand_guidelines"):
        return
    from app.models.brand_voice import BrandVoiceConfiguration, BrandVoiceVersion

    Base.metadata.create_all(
        bind=target_engine,
        tables=[
            BrandVoiceConfiguration.__table__,
            BrandVoiceVersion.__table__,
        ],
    )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
