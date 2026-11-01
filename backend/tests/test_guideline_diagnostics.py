from sqlalchemy.orm import Session

from app.models.brand_guideline import (
    BrandGuideline,
    GuidelineReviewEvent,
    GuidelineVersion,
)
from app.models.user import User
from app.services.auth_service import hash_password
from app.services.guideline_diagnostics import diagnose_guidelines


def _guideline(
    guideline_id,
    name,
    category,
    description,
    *,
    active=True,
    preferred_terms=None,
):
    return {
        "id": guideline_id,
        "name": name,
        "category": category,
        "description": description,
        "examples": [],
        "preferred_terms": preferred_terms or [],
        "is_active": active,
    }


def test_detects_narrow_opposing_directives_and_marks_scope_unclear():
    result = diagnose_guidelines(
        [
            _guideline(1, "Formal voice", "Tone", "Always use a formal tone."),
            _guideline(2, "Casual voice", "tone", "Use a casual tone."),
        ]
    )

    assert len(result["potential_conflicts"]) == 1
    conflict = result["potential_conflicts"][0]
    assert conflict["diagnostic_type"] == "potential_conflict"
    assert conflict["guideline_ids"] == [1, 2]
    assert conflict["guideline_names"] == ["Formal voice", "Casual voice"]
    assert conflict["matched_text"] == [
        "Always use a formal tone",
        "Use a casual tone",
    ]
    assert conflict["scope_status"] == "unclear"
    assert "Category is only a grouping hint" in conflict["explanation"]
    assert conflict["human_review_recommendation"]


def test_vague_wording_is_a_separate_clarification_suggestion():
    result = diagnose_guidelines(
        [
            _guideline(
                1,
                "Modern style",
                "Brand",
                "Make content modern and engaging.",
            )
        ]
    )

    assert result["potential_conflicts"] == []
    assert [item["matched_text"] for item in result["needs_clarification"]] == [
        ["Modern"],
        ["engaging"],
    ]
    assert all(
        item["diagnostic_type"] == "needs_clarification"
        for item in result["needs_clarification"]
    )
    assert all("not a conflict" in item["explanation"] for item in result["needs_clarification"])


def test_compatible_rules_and_preferred_terms_are_not_conflicts():
    result = diagnose_guidelines(
        [
            _guideline(
                1,
                "Clear voice",
                "Tone",
                "Use clear language.",
                preferred_terms=["formal"],
            ),
            _guideline(2, "Friendly voice", "Tone", "Use a friendly tone."),
        ]
    )

    assert result == {"potential_conflicts": [], "needs_clarification": []}


def test_directive_pair_in_different_categories_is_not_a_conflict():
    result = diagnose_guidelines(
        [
            _guideline(1, "Formal voice", "Email", "Use a formal tone."),
            _guideline(2, "Casual voice", "Social", "Use a casual tone."),
        ]
    )

    assert result["potential_conflicts"] == []


def test_negated_directive_is_not_reported_as_a_conflict():
    result = diagnose_guidelines(
        [
            _guideline(
                1,
                "Avoid formal voice",
                "Tone",
                "Do not use a formal tone.",
            ),
            _guideline(2, "Casual voice", "Tone", "Use a casual tone."),
        ]
    )

    assert result["potential_conflicts"] == []


def test_guideline_containing_both_directives_is_not_forced_into_a_conflict():
    result = diagnose_guidelines(
        [
            _guideline(
                1,
                "Channel-specific voice",
                "Tone",
                "Use a formal tone for notices and a casual tone for social posts.",
            ),
            _guideline(2, "Casual voice", "Tone", "Use a casual tone."),
        ]
    )

    assert result["potential_conflicts"] == []


def test_inactive_guidelines_are_excluded_from_all_diagnostics():
    result = diagnose_guidelines(
        [
            _guideline(1, "Formal voice", "Tone", "Use a formal tone."),
            _guideline(
                2,
                "Casual voice",
                "Tone",
                "Use a casual tone and make it engaging.",
                active=False,
            ),
        ]
    )

    assert result == {"potential_conflicts": [], "needs_clarification": []}


def _add_user(test_engine, email, role):
    with Session(test_engine) as db:
        db.add(
            User(
                email=email,
                display_name=role.title(),
                password_hash=hash_password("strong-test-password"),
                role=role,
                is_active=True,
                must_change_password=False,
            )
        )
        db.commit()


def _login(client, email):
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": "strong-test-password"},
    )
    assert response.status_code == 200


def test_diagnostics_endpoint_permissions_and_read_only(client, test_engine):
    for name, description in (
        ("Formal voice", "Use a formal tone."),
        ("Casual voice", "Use a casual tone."),
    ):
        response = client.post(
            "/api/guidelines",
            json={
                "name": name,
                "category": "Tone",
                "description": description,
            },
        )
        assert response.status_code == 201

    def counts():
        with Session(test_engine) as db:
            return (
                db.query(BrandGuideline).count(),
                db.query(GuidelineVersion).count(),
                db.query(GuidelineReviewEvent).count(),
            )

    before = counts()
    result = client.get("/api/guidelines/diagnostics")
    assert result.status_code == 200
    assert len(result.json()["potential_conflicts"]) == 1
    assert counts() == before

    _add_user(test_engine, "diagnostic-reviewer@example.test", "reviewer")
    _login(client, "diagnostic-reviewer@example.test")
    assert client.get("/api/guidelines/diagnostics").status_code == 200

    _add_user(test_engine, "diagnostic-contributor@example.test", "contributor")
    _login(client, "diagnostic-contributor@example.test")
    assert client.get("/api/guidelines/diagnostics").status_code == 403
