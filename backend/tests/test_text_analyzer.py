
from types import SimpleNamespace

from app.services.text_analyzer import analyze_text


def test_claim_and_accessibility_rules_are_advisory():
    findings = analyze_text(
        "This product guarantees 100% success. Click here.",
        [],
    )
    assert {item["category"] for item in findings} == {
        "unsupported_claim",
        "accessibility",
    }
    assert all(item["confidence"] is not None for item in findings)


def test_configured_term_and_expired_source_are_detected():
    guideline = SimpleNamespace(
        id=15,
        name="Factual evidence",
        category="factual_claim",
        severity="high",
        prohibited_terms=["amazing"],
        preferred_terms=["considered"],
        approved_sources=[
            {"name": "Old report", "expiry_date": "2000-01-01"}
        ],
    )
    findings = analyze_text("An amazing product grew by 40%.", [guideline])

    terminology = next(
        item for item in findings
        if item["category"] == "terminology"
    )
    factual = next(
        item for item in findings
        if item["category"] == "factual_claim"
    )

    assert "considered" in terminology["suggestion"]
    assert "expired" in factual["explanation"]


def test_current_retrieved_source_is_not_reported_as_missing():
    guideline = SimpleNamespace(
        id=10,
        name="Current facts",
        category="factual_claim",
        severity="medium",
        prohibited_terms=[],
        preferred_terms=[],
        approved_sources=[],
    )

    findings = analyze_text(
        "The annual subscription price is $240.",
        [guideline],
        evidence_matches=[
            {
                "id": 4,
                "name": "Current price sheet",
                "guideline_id": guideline.id,
                "freshness": "current",
                "excerpt": "The annual subscription price is $240.",
            }
        ],
    )

    factual = next(
        item for item in findings
        if item["category"] == "factual_claim"
    )

    assert factual["source"] == "Current facts"
    assert factual["guideline_id"] == guideline.id
    assert "none has established support" in factual["explanation"]
    assert "current approved source excerpt matched" not in factual["explanation"]


def test_quoted_promotional_claim_excludes_closing_quote():
    from app.services.claim_checker import check_promotional_claims

    text = (
        "Our product is "
        "“100% guaranteed to double your productivity in just 24 hours”."
    )

    findings = check_promotional_claims(text)
    finding = next(
        item for item in findings
        if item["category"] == "unsupported_claim"
    )

    assert finding["matched_text"].endswith("24 hours")
    assert not finding["matched_text"].endswith("”")


def test_claim_suggestion_does_not_contaminate_matched_text():
    findings = analyze_text(
        "Our product is 100% guaranteed to double your productivity in just 24 hours.",
        [],
    )

    finding = next(
        item for item in findings
        if item["category"] == "unsupported_claim"
    )

    assert finding["matched_text"].endswith("24 hours")
    assert "Revise" not in finding["matched_text"]
    assert "Revise" in finding["suggestion"]


def test_promotional_claim_extraction_covers_claim_types_with_original_offsets():
    from app.services.claim_checker import extract_promotional_claims

    text = (
        "A calm, lightweight dashboard. "
        "We help customers save $500 each year. "
        "Our platform automates monthly reporting."
    )
    claims = extract_promotional_claims(text)

    assert len(claims) == 2
    for claim in claims:
        start = claim["claim_start"]
        end = claim["claim_end"]
        assert text[start:end] == claim["matched_text"]
    assert claims[0]["matched_text"] == "We help customers save $500 each year"
    assert claims[1]["matched_text"] == "Our platform automates monthly reporting"


def test_claim_extraction_skips_prohibitions_and_ordinary_descriptions():
    from app.services.claim_checker import extract_promotional_claims

    text = (
        "The product is blue and lightweight. "
        "Do not claim that the service guarantees results. "
        "This helps explain the trend in the chart. "
        "Our thoughtful service supports your everyday work."
    )

    assert extract_promotional_claims(text) == []


def test_specific_product_capability_is_detected():
    from app.services.claim_checker import extract_promotional_claims

    finding = extract_promotional_claims("The platform supports SSO.")

    assert len(finding) == 1
    assert finding[0]["matched_text"] == "The platform supports SSO"


def test_duplicate_claims_keep_separate_locations():
    from app.services.claim_checker import extract_promotional_claims

    text = "Our product guarantees results. Our product guarantees results."
    findings = extract_promotional_claims(text)

    assert len(findings) == 2
    assert findings[0]["claim_start"] == 0
    assert findings[1]["claim_start"] > findings[0]["claim_start"]
    assert all(
        text[item["claim_start"]:item["claim_end"]] == item["matched_text"]
        for item in findings
    )


def test_factual_claim_occurrences_have_their_own_exact_draft_offsets():
    text = (
        "The annual subscription price is $240. "
        "The annual subscription price is $240."
    )
    findings = analyze_text(text, [])
    factual = [item for item in findings if item["category"] == "factual_claim"]

    assert len(factual) == 2
    assert text[factual[0]["claim_start"]:factual[0]["claim_end"]] == factual[0]["matched_text"]
    assert text[factual[1]["claim_start"]:factual[1]["claim_end"]] == factual[1]["matched_text"]
    assert factual[0]["claim_start"] == 0
    assert factual[1]["claim_start"] > factual[0]["claim_start"]
