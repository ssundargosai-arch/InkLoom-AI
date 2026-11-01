from datetime import datetime, timedelta, timezone

from app.services.factual_verifier import classify_claim, verification_fields


def source(name, excerpt, **extra):
    return {
        "name": name,
        "excerpt": excerpt,
        "freshness": "current",
        "approval_status": "approved",
        **extra,
    }


def test_matching_approved_evidence_verifies_numeric_claim():
    evidence = [source("Approved report", "Our product increases revenue by 30%.")]
    status, confidence, citations = classify_claim(
        "Our product increases revenue by 30%", evidence
    )
    assert status == "verified"
    assert confidence == 0.9
    assert citations == evidence


def test_conflicting_approved_values_are_not_silently_marked_verified():
    supporting = source("Approved report A", "Our product increases revenue by 30%.")
    conflicting = source("Approved report B", "Our product increases revenue by 20%.")
    status, confidence, citations = classify_claim(
        "Our product increases revenue by 30%", [supporting, conflicting]
    )
    assert status == "conflicting_evidence"
    assert confidence == 0.55
    assert supporting in citations
    assert conflicting in citations


def test_conflicting_evidence_has_explanation_and_both_citations():
    fields = verification_fields(
        "Our product increases revenue by 30%",
        [
            source("Approved report A", "Our product increases revenue by 30%"),
            source("Approved report B", "Our product increases revenue by 20%"),
        ],
    )
    assert fields["verification_status"] == "conflicting_evidence"
    assert "heuristic matches with different values" in fields["verification_explanation"]
    assert len(fields["citations"]) == 2


def test_external_search_result_alone_does_not_verify_claim():
    evidence = [
        source(
            "External result",
            "Our product increases revenue by 30%.",
            source_type="external_trusted_source",
        )
    ]
    status, _, citations = classify_claim(
        "Our product increases revenue by 30%", evidence
    )
    assert status == "unverified"
    assert citations == []


def test_unapproved_internal_source_cannot_verify_claim():
    evidence = [
        source(
            "Pending report",
            "Our product increases revenue by 30%.",
            source_type="approved_internal_source",
            approval_status="pending",
            source_id=42,
        )
    ]

    status, _, citations = classify_claim(
        "Our product increases revenue by 30%", evidence
    )

    assert status == "unverified"
    assert citations == []


def test_inactive_approved_source_is_not_used_as_expired_or_current_evidence():
    inactive = source(
        "Deactivated report",
        "Our product increases revenue by 30%.",
        source_type="approved_internal_source",
        approval_status="approved",
        is_active=False,
        source_id=43,
        expiry_date=(
            datetime.now(timezone.utc).date() - timedelta(days=1)
        ).isoformat(),
    )
    fields = verification_fields(
        "Our product increases revenue by 30%.", [inactive]
    )
    assert fields["evidence_status"] == "unverified"
    assert fields["citations"] == []


def test_source_without_explicit_approval_cannot_verify_claim():
    evidence = [
        {
            "name": "Legacy report",
            "excerpt": "Our product increases revenue by 30%.",
            "freshness": "current",
        }
    ]

    fields = verification_fields("Our product increases revenue by 30%.", evidence)

    assert fields["evidence_status"] == "unverified"
    assert fields["citations"] == []


def test_approved_internal_source_preserves_structured_provenance():
    evidence = [
        source(
            "Approved report",
            "Our product increases revenue by 30%.",
            source_type="approved_internal_source",
            approval_status="approved",
            source_id=42,
            guideline_id=7,
            url="https://example.com/report",
        )
    ]

    status, _, citations = classify_claim(
        "Our product increases revenue by 30%", evidence
    )

    assert status == "verified"
    assert citations[0]["source_id"] == 42
    assert citations[0]["source_type"] == "approved_internal_source"
    assert citations[0]["approval_status"] == "approved"
    assert citations[0]["guideline_id"] == 7
    assert citations[0]["url"] == "https://example.com/report"


def test_different_numeric_value_is_unsupported_with_the_conflicting_source():
    evidence = [
        source(
            "Current pricing sheet",
            "The annual subscription price is $240.",
            source_type="approved_internal_source",
            approval_status="approved",
            source_id=14,
        )
    ]

    fields = verification_fields(
        "The annual subscription price is $300.", evidence
    )

    assert fields["evidence_status"] == "unsupported"
    assert fields["verification_status"] == "contradicted"
    assert fields["citations"] == evidence
    assert "different values" in fields["evidence_reason"]


def test_partial_or_irrelevant_keyword_overlap_is_not_proof():
    partial = source(
        "Partial report",
        "Our product supports faster onboarding.",
        source_type="approved_internal_source",
        approval_status="approved",
        source_id=8,
    )
    irrelevant = source(
        "Unrelated report",
        "The annual subscription includes customer support.",
        source_type="approved_internal_source",
        approval_status="approved",
        source_id=9,
    )

    fields = verification_fields(
        "Our product increases customer revenue by 30%.",
        [partial, irrelevant],
    )

    assert fields["evidence_status"] == "unverified"
    assert fields["citations"] == []
    assert "substantiates the complete claim" in fields["evidence_reason"]


def test_weak_predicate_overlap_does_not_support_or_contradict_claim():
    fields = verification_fields(
        "Our platform guarantees customers 30% savings.",
        [
            source(
                "Savings report",
                "Our platform helps customers track savings of 30%.",
            )
        ],
    )

    assert fields["evidence_status"] == "unverified"
    assert fields["verification_status"] == "unverified"


def test_ambiguous_negation_never_establishes_support_or_contradiction():
    fields = verification_fields(
        "The product does not increase revenue by 30%.",
        [
            source(
                "Revenue report",
                "The product increases revenue by 30%.",
            )
        ],
    )

    assert fields["evidence_status"] == "unverified"
    assert fields["verification_status"] == "unverified"
    assert fields["citations"]


def test_negated_contraction_is_not_treated_as_positive_support():
    fields = verification_fields(
        "The product doesn't increase revenue.",
        [
            source(
                "Revenue report",
                "The product doesn't increase revenue.",
            )
        ],
    )

    assert fields["evidence_status"] == "unverified"
    assert fields["verification_status"] == "unverified"


def test_matching_number_without_matching_claim_context_is_not_proof():
    fields = verification_fields(
        "The annual subscription price is $240.",
        [
            source(
                "Revenue report",
                "Revenue increased by $240 during the annual period.",
            )
        ],
    )

    assert fields["evidence_status"] == "unverified"
    assert fields["verification_status"] == "unverified"


def test_scope_qualifier_blocks_support_even_when_number_matches():
    fields = verification_fields(
        "Our plan serves 10 customers.",
        [
            source(
                "Capacity report",
                "Our plan serves up to 10 customers.",
            )
        ],
    )

    assert fields["evidence_status"] == "unverified"
    assert fields["verification_status"] == "unverified"


def test_different_numeric_values_require_identical_claim_context_to_conflict():
    fields = verification_fields(
        "The annual subscription price is $300.",
        [
            source(
                "Mixed report",
                "Annual subscription price and revenue target are $240.",
            )
        ],
    )

    assert fields["evidence_status"] == "unverified"
    assert fields["verification_status"] == "unverified"


def test_expired_relevant_evidence_is_returned_but_never_current_support():
    expired = source(
        "Expired product report",
        "Our product increases revenue by 30%.",
        source_type="approved_internal_source",
        approval_status="approved",
        source_id=18,
        expiry_date=(
            datetime.now(timezone.utc).date() - timedelta(days=1)
        ).isoformat(),
    )

    fields = verification_fields("Our product increases revenue by 30%.", [expired])

    assert fields["evidence_status"] == "expired_evidence"
    assert fields["verification_status"] == "expired_evidence"
    assert fields["citations"] == [expired]
    assert fields["evidence_strength"] == 0.0


def test_future_validity_evidence_is_not_used_for_current_verification():
    future = source(
        "Future pricing sheet",
        "The annual subscription price is $240.",
        source_type="approved_internal_source",
        approval_status="approved",
        source_id=19,
        source_date=(
            datetime.now(timezone.utc).date() + timedelta(days=1)
        ).isoformat(),
    )

    fields = verification_fields("The annual subscription price is $240.", [future])

    assert fields["evidence_status"] == "unverified"
    assert fields["verification_status"] == "unverified"
    assert fields["citations"] == [future]


def test_multiple_claims_are_classified_independently():
    supported = source(
        "Pricing sheet",
        "The annual subscription price is $240.",
        approval_status="approved",
        source_type="approved_internal_source",
        source_id=1,
    )
    unsupported = source(
        "Performance report",
        "Our product increases revenue by 20%.",
        approval_status="approved",
        source_type="approved_internal_source",
        source_id=2,
    )

    price = verification_fields(
        "The annual subscription price is $240.", [supported, unsupported]
    )
    growth = verification_fields(
        "Our product increases revenue by 30%.", [supported, unsupported]
    )

    assert price["evidence_status"] == "supported"
    assert price["citations"] == [supported]
    assert growth["evidence_status"] == "unsupported"
    assert growth["citations"] == [unsupported]


def test_invalid_claim_and_evidence_inputs_fail_closed():
    assert verification_fields("", [])["evidence_status"] == "unverified"
    assert verification_fields(None, [])["verification_confidence"] == 0.0
    assert verification_fields(
        "Our product increases revenue by 30%.", None
    )["citations"] == []


def test_confidence_and_evidence_strength_are_separate():
    fields = verification_fields(
        "Our product increases revenue by 30%.",
        [source("Report", "Our product increases revenue by 30%.")],
    )

    assert fields["verification_confidence"] == 0.9
    assert fields["evidence_strength"] == 0.9
    assert fields["verification_status"] == "verified"


def test_one_source_with_both_supporting_and_conflicting_sentences_is_conflicting():
    evidence = [
        source(
            "Report with inconsistent figures",
            "Our product increases revenue by 30%. "
            "Our product increases revenue by 20%.",
        )
    ]

    fields = verification_fields("Our product increases revenue by 30%.", evidence)

    assert fields["evidence_status"] == "conflicting"
    assert fields["citations"] == evidence


def test_common_inflected_verb_forms_compare_without_keyword_false_negative():
    evidence = [
        source(
            "Customer savings report",
            "Our product saved customers $500.",
        )
    ]

    fields = verification_fields(
        "Our product saves customers $500.", evidence
    )

    assert fields["evidence_status"] == "supported"
    assert fields["citations"] == evidence
