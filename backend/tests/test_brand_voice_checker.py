from types import SimpleNamespace

from app.services.brand_voice_checker import check_brand_voice
from app.services.text_analyzer import analyze_text


def _voice(**overrides):
    configuration = {
        "desired_tones": [],
        "voice_attributes": [],
        "preferred_expressions": [],
        "prohibited_expressions": [],
        "target_audiences": [],
        "supported_channels": [],
        "messaging_principles": [],
    }
    configuration.update(overrides)
    return configuration


def test_missing_or_empty_configuration_preserves_existing_analysis():
    content = "A thoughtful service for everyday work."
    assert analyze_text(content, []) == analyze_text(
        content, [], brand_voice_configuration=None
    )
    assert analyze_text(content, [], brand_voice_configuration=_voice()) == []


def test_prohibited_expression_is_a_configured_rule_violation():
    findings = check_brand_voice(
        "Try this world-class service.",
        _voice(prohibited_expressions=["world-class"]),
    )

    assert len(findings) == 1
    finding = findings[0]
    assert finding["category"] == "brand_voice"
    assert finding["finding_type"] == "prohibited_expression"
    assert finding["assessment"] == "configured_rule_violation"
    assert finding["matched_text"] == "world-class"
    assert finding["configuration_rule"] == "world-class"
    assert finding["suggestion"] is None


def test_preferred_expressions_are_not_mandatory():
    assert check_brand_voice(
        "This draft does not contain the preferred expression.",
        _voice(preferred_expressions=["Made with care"]),
    ) == []


def test_formal_tone_colloquial_signal_is_advisory_only():
    findings = check_brand_voice(
        "We're gonna share the update.",
        _voice(desired_tones=["formal"]),
    )

    assert len(findings) == 1
    finding = findings[0]
    assert finding["finding_type"] == "tone_signal"
    assert finding["assessment"] == "advisory"
    assert finding["matched_text"] == "gonna"
    assert "not proof" in finding["explanation"]
    assert finding["suggestion"]


def test_prohibited_tone_marker_does_not_create_a_second_voice_finding():
    findings = check_brand_voice(
        "We're gonna share the update.",
        _voice(
            desired_tones=["formal"],
            prohibited_expressions=["gonna"],
        ),
    )

    assert len(findings) == 1
    assert findings[0]["finding_type"] == "prohibited_expression"
    assert findings[0]["assessment"] == "configured_rule_violation"


def test_audience_channel_labels_and_free_text_principles_do_not_invent_rules():
    findings = check_brand_voice(
        "A general message for readers.",
        _voice(
            target_audiences=["Enterprise buyers"],
            supported_channels=["Email"],
            messaging_principles=["Always be inspiring and distinctive."],
        ),
    )

    assert findings == []


def test_preferred_and_prohibited_duplicate_does_not_create_duplicate_finding():
    guideline = SimpleNamespace(
        id=1,
        name="Terminology",
        category="terminology",
        severity="medium",
        prohibited_terms=["world-class"],
        preferred_terms=[],
        approved_sources=[],
    )
    findings = analyze_text(
        "A world-class service.",
        [guideline],
        brand_voice_configuration=_voice(
            prohibited_expressions=["world-class"]
        ),
    )

    matching = [
        item
        for item in findings
        if item.get("matched_text", "").casefold() == "world-class"
    ]
    assert len(matching) == 1
    assert matching[0]["category"] == "terminology"
    assert len(matching[0]["brand_voice_findings"]) == 1
    assert (
        matching[0]["brand_voice_findings"][0]["assessment"]
        == "configured_rule_violation"
    )


def test_prohibited_expression_inside_claim_is_attached_not_duplicated():
    findings = analyze_text(
        "Our world-class platform guarantees results.",
        [],
        brand_voice_configuration=_voice(
            prohibited_expressions=["world-class"]
        ),
    )

    voice_findings = [
        item
        for finding in findings
        for item in finding.get("brand_voice_findings", [])
    ]
    assert len(voice_findings) == 1
    assert voice_findings[0]["matched_text"] == "world-class"
    assert not any(
        item["category"] == "brand_voice"
        and item.get("matched_text") == "world-class"
        for item in findings
    )
