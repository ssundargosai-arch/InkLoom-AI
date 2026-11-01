from sqlalchemy.orm import Session

from app.models.brand_voice import BrandVoiceConfiguration, BrandVoiceVersion
from app.models.user import User
from app.services.auth_service import hash_password


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


def _configuration(**overrides):
    configuration = {
        "desired_tones": ["professional", "friendly"],
        "voice_attributes": ["clear", "trustworthy"],
        "preferred_expressions": ["Thoughtfully made"],
        "prohibited_expressions": ["world-class"],
        "target_audiences": ["Small business owners"],
        "supported_channels": ["Website", "Email"],
        "messaging_principles": ["State benefits accurately"],
    }
    configuration.update(overrides)
    return configuration


def test_admin_brand_voice_configuration_persists_and_versions(client):
    initial = client.get("/api/guidelines/brand-voice")
    assert initial.status_code == 200
    assert initial.json()["version_number"] == 0
    assert initial.json()["desired_tones"] == []
    assert initial.json()["supported_channels"] == []

    created = client.put(
        "/api/guidelines/brand-voice",
        json=_configuration(),
    )
    assert created.status_code == 200
    assert created.json()["version_number"] == 1
    assert created.json()["preferred_expressions"] == ["Thoughtfully made"]

    updated = client.put(
        "/api/guidelines/brand-voice",
        json=_configuration(
            desired_tones=["formal"],
            messaging_principles=["Preserve the creator's meaning"],
        ),
    )
    assert updated.status_code == 200
    assert updated.json()["version_number"] == 2
    assert updated.json()["desired_tones"] == ["formal"]

    unchanged = client.put(
        "/api/guidelines/brand-voice",
        json=_configuration(
            desired_tones=["formal"],
            messaging_principles=["Preserve the creator's meaning"],
        ),
    )
    assert unchanged.json()["version_number"] == 2

    reloaded = client.get("/api/guidelines/brand-voice")
    assert reloaded.json()["desired_tones"] == ["formal"]
    assert reloaded.json()["messaging_principles"] == [
        "Preserve the creator's meaning"
    ]

    versions = client.get("/api/guidelines/brand-voice/versions")
    assert versions.status_code == 200
    assert [item["version_number"] for item in versions.json()] == [2, 1]
    assert versions.json()[0]["snapshot"]["desired_tones"] == ["formal"]
    assert versions.json()[1]["snapshot"]["desired_tones"] == [
        "professional",
        "friendly",
    ]


def test_reviewers_can_inspect_but_not_modify_brand_voice(client, test_engine):
    _add_user(test_engine, "brand-voice-reviewer@example.test", "reviewer")
    _add_user(test_engine, "brand-voice-contributor@example.test", "contributor")

    _login(client, "brand-voice-reviewer@example.test")
    assert client.get("/api/guidelines/brand-voice").status_code == 200
    assert client.put(
        "/api/guidelines/brand-voice",
        json=_configuration(),
    ).status_code == 403
    assert client.get("/api/guidelines/brand-voice/versions").status_code == 403

    _login(client, "brand-voice-contributor@example.test")
    assert client.get("/api/guidelines/brand-voice").status_code == 403
    assert client.put(
        "/api/guidelines/brand-voice",
        json=_configuration(),
    ).status_code == 403


def test_contributor_can_analyze_but_cannot_modify_brand_voice(
    client, test_engine
):
    configured = client.put(
        "/api/guidelines/brand-voice",
        json=_configuration(prohibited_expressions=["world-class"]),
    )
    assert configured.status_code == 200
    _add_user(test_engine, "brand-voice-analysis@example.test", "contributor")
    _login(client, "brand-voice-analysis@example.test")

    analysis = client.post(
        "/api/analyze",
        json={"content": "A world-class service for everyone."},
    )
    assert analysis.status_code == 200
    assert any(
        finding.get("category") == "brand_voice"
        and finding.get("finding_type") == "prohibited_expression"
        for finding in analysis.json()["findings"]
    )
    assert client.put(
        "/api/guidelines/brand-voice",
        json=_configuration(prohibited_expressions=["other phrase"]),
    ).status_code == 403


def test_brand_voice_validation_rejects_invalid_and_duplicate_values(client):
    invalid_payloads = [
        _configuration(desired_tones=["professional", "NOT_A_TONE"]),
        _configuration(desired_tones=["friendly", "FRIENDLY"]),
        _configuration(target_audiences=["General", " general "]),
        _configuration(
            preferred_expressions=["Use care"],
            prohibited_expressions=[" use CARE "],
        ),
        _configuration(supported_channels=[""]),
    ]

    for payload in invalid_payloads:
        response = client.put("/api/guidelines/brand-voice", json=payload)
        assert response.status_code == 422


def test_existing_guideline_terms_keep_existing_behavior(client):
    created = client.post(
        "/api/guidelines",
        json={
            "name": "Legacy wording rule",
            "category": "terminology",
            "description": "Use the configured terminology.",
            "prohibited_terms": ["world class"],
            "preferred_terms": ["well-made"],
        },
    )
    assert created.status_code == 201
    guideline = created.json()
    assert guideline.get("brand_voice") is None

    analysis = client.post(
        "/api/analyze",
        json={
            "content": "This is a world class product.",
            "guideline_ids": [guideline["id"]],
        },
    )
    assert analysis.status_code == 200
    term_finding = next(
        finding
        for finding in analysis.json()["findings"]
        if finding["category"] == "terminology"
    )
    assert term_finding["matched_text"] == "world class"
    assert "well-made" in term_finding["suggestion"]


def test_brand_voice_get_and_validation_do_not_create_versions(
    client, test_engine
):
    assert client.get("/api/guidelines/brand-voice").status_code == 200
    assert client.put(
        "/api/guidelines/brand-voice",
        json=_configuration(desired_tones=["unsupported"]),
    ).status_code == 422
    with Session(test_engine) as db:
        assert db.query(BrandVoiceConfiguration).count() == 0
        assert db.query(BrandVoiceVersion).count() == 0


def test_initial_analysis_and_reanalysis_use_current_voice_without_rewriting_history(
    client,
):
    original = client.post(
        "/api/analyze",
        json={
            "title": "Original wording",
            "content": "A simple update for the team.",
            "content_type": "Email",
        },
    )
    assert original.status_code == 200
    review_id = original.json()["id"]
    before_configuration = client.get(
        f"/api/reviews/{review_id}"
    ).json()
    original_snapshot = before_configuration["analysis_runs"][0]["findings"]
    assert original_snapshot == []

    configured = client.put(
        "/api/guidelines/brand-voice",
        json=_configuration(
            desired_tones=["formal"],
            prohibited_expressions=["world-class"],
        ),
    )
    assert configured.status_code == 200

    unchanged_review = client.get(f"/api/reviews/{review_id}").json()
    assert unchanged_review["analysis_runs"][0]["findings"] == original_snapshot
    assert unchanged_review["findings"] == []

    revised_content = "We're gonna use a world-class workflow."
    reanalyzed = client.post(
        f"/api/reviews/{review_id}/reanalyze",
        json={"content": revised_content, "title": "Voice checked revision"},
    )
    assert reanalyzed.status_code == 200
    detail = client.get(f"/api/reviews/{review_id}").json()
    reanalysis_snapshot = detail["analysis_runs"][-1]["findings"]
    voice_details = [
        voice_finding
        for finding in reanalysis_snapshot
        for voice_finding in (
            finding.get("brand_voice_findings", [])
            or ([finding] if finding.get("category") == "brand_voice" else [])
        )
    ]
    assert {item["finding_type"] for item in voice_details} == {
        "prohibited_expression",
        "tone_signal",
    }, reanalysis_snapshot
    assert detail["analysis_runs"][0]["findings"] == original_snapshot

    analyzed_again = client.post(
        "/api/analyze",
        json={
            "title": "Same voice rule",
            "content": revised_content,
            "content_type": "Email",
        },
    )
    assert analyzed_again.status_code == 200
    initial_voice_details = [
        voice_finding
        for finding in analyzed_again.json()["findings"]
        for voice_finding in (
            finding.get("brand_voice_findings", [])
            or ([finding] if finding.get("category") == "brand_voice" else [])
        )
    ]
    assert {item["finding_type"] for item in initial_voice_details} == {
        "prohibited_expression",
        "tone_signal",
    }
