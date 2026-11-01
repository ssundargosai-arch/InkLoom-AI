import json

from sqlalchemy import create_engine, inspect, text

from app.database import migrate_review_json_columns


def _create_legacy_schema(engine):
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE review_approval_decisions (
                    id INTEGER PRIMARY KEY,
                    review_id INTEGER NOT NULL,
                    reviewer_id INTEGER NOT NULL,
                    version_id INTEGER NOT NULL DEFAULT 0,
                    decision VARCHAR(24) NOT NULL,
                    reason TEXT,
                    created_at DATETIME NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO review_approval_decisions
                    (id, review_id, reviewer_id, version_id, decision, reason, created_at)
                VALUES
                    (41, 12, 7, 3, 'approved', 'Historical approval', '2026-10-30 09:15:00')
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE review_visual_attachments (
                    id INTEGER PRIMARY KEY,
                    review_id INTEGER NOT NULL,
                    filename VARCHAR(160) NOT NULL,
                    media_type VARCHAR(80) NOT NULL,
                    file_data BLOB NOT NULL,
                    uploaded_by_id INTEGER,
                    created_at DATETIME NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO review_visual_attachments
                    (id, review_id, filename, media_type, file_data, uploaded_by_id, created_at)
                VALUES
                    (6, 12, 'review-12.png', 'image/png', X'89504E47', 7, '2026-10-30 09:15:00')
                """
            )
        )


def test_legacy_review_json_columns_are_added_with_safe_defaults_and_preserved_rows():
    engine = create_engine("sqlite://")
    try:
        _create_legacy_schema(engine)
        migrate_review_json_columns(engine)

        with engine.connect() as connection:
            decision_columns = {
                row[1]: row
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info('review_approval_decisions')"
                )
            }
            visual_columns = {
                row[1]: row
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info('review_visual_attachments')"
                )
            }
            assert decision_columns["acknowledged_warning_ids"][2].upper() == "JSON"
            assert decision_columns["acknowledged_warning_ids"][3] == 1
            assert decision_columns["acknowledged_warning_ids"][4] == "'[]'"
            assert visual_columns["analysis_metadata"][2].upper() == "JSON"
            assert visual_columns["analysis_metadata"][3] == 1
            assert visual_columns["analysis_metadata"][4] == "'{}'"

            decision = connection.execute(
                text(
                    """
                    SELECT id, review_id, reviewer_id, version_id, decision, reason,
                           acknowledged_warning_ids
                    FROM review_approval_decisions WHERE id = 41
                    """
                )
            ).one()
            attachment = connection.execute(
                text(
                    """
                    SELECT id, review_id, filename, media_type, file_data,
                           analysis_metadata
                    FROM review_visual_attachments WHERE id = 6
                    """
                )
            ).one()
            assert tuple(decision[:6]) == (
                41,
                12,
                7,
                3,
                "approved",
                "Historical approval",
            )
            assert json.loads(decision[6]) == []
            assert tuple(attachment[:5]) == (
                6,
                12,
                "review-12.png",
                "image/png",
                b"\x89PNG",
            )
            assert json.loads(attachment[5]) == {}

        migrate_review_json_columns(engine)
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT COUNT(*) FROM review_approval_decisions")
            ).scalar_one() == 1
            assert connection.execute(
                text("SELECT COUNT(*) FROM review_visual_attachments")
            ).scalar_one() == 1
            assert len(inspect(connection).get_columns("review_approval_decisions")) == 8
            assert len(inspect(connection).get_columns("review_visual_attachments")) == 8
    finally:
        engine.dispose()
