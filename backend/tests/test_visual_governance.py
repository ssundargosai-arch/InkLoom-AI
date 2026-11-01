from datetime import date, timedelta
from io import BytesIO

from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject
from sqlalchemy.orm import Session


def _png_bytes(color="white"):
    buffer = BytesIO()
    Image.new("RGB", (32, 24), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def _make_pdf(page_count=2):
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=612, height=792)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _make_pdf_with_embedded_image():
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    image = DecodedStreamObject()
    image.set_data(bytes([255, 255, 255] * 64))
    for key, value in {
        "/Type": "/XObject",
        "/Subtype": "/Image",
        "/Width": 8,
        "/Height": 8,
        "/ColorSpace": "/DeviceRGB",
        "/BitsPerComponent": 8,
    }.items():
        image[NameObject(key)] = (
            NameObject(value) if isinstance(value, str) else NumberObject(value)
        )
    image_ref = writer._add_object(image)
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/XObject"): DictionaryObject(
                {NameObject("/Im0"): image_ref}
            )
        }
    )
    content = DecodedStreamObject()
    content.set_data(b"q 8 0 0 8 0 0 cm /Im0 Do Q")
    page[NameObject("/Contents")] = writer._add_object(content)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _login_as_contributor(client, test_engine):
    from app.models.user import User
    from app.services.auth_service import hash_password

    with Session(test_engine) as db:
        existing = (
            db.query(User)
            .filter(User.email == "visual-contributor@example.test")
            .first()
        )
        if existing is None:
            db.add(
                User(
                    email="visual-contributor@example.test",
                    display_name="Visual Contributor",
                    password_hash=hash_password("visual-contributor-password"),
                    role="contributor",
                    is_active=True,
                    must_change_password=False,
                )
            )
        db.commit()
    response = client.post(
        "/api/auth/login",
        json={
            "email": "visual-contributor@example.test",
            "password": "visual-contributor-password",
        },
    )
    assert response.status_code == 200


def _login_as_admin(client):
    response = client.post(
        "/api/auth/login",
        json={
            "email": "admin@example.test",
            "password": "test-admin-password-123",
        },
    )
    assert response.status_code == 200


def test_wcag_contrast_ratio_uses_relative_luminance():
    from app.services.image_analyzer import contrast_ratio

    assert contrast_ratio((0, 0, 0), (255, 255, 255)) == 21.0
    assert contrast_ratio((255, 255, 255), (0, 0, 0)) == 21.0
    assert contrast_ratio((118, 118, 118), (255, 255, 255)) >= 4.5


def test_visual_asset_upload_approval_file_privacy_and_reapproval(client):
    upload = client.post(
        "/api/visual-assets",
        data={"name": "Primary mark", "asset_type": "logo"},
        files={"file": ("logo.png", _png_bytes(), "image/png")},
    )
    assert upload.status_code == 201
    asset = upload.json()
    assert asset["approval_status"] == "pending"
    assert asset["lifecycle_status"] == "pending"
    assert asset["version"] == 1

    approved = client.patch(
        "/api/visual-assets/{}/approval".format(asset["id"]),
        json={"status": "approved"},
    )
    assert approved.status_code == 200
    assert approved.json()["lifecycle_status"] == "approved"
    file_response = client.get(asset["file_url"])
    assert file_response.status_code == 200
    assert file_response.content == _png_bytes()
    assert file_response.headers["x-content-type-options"] == "nosniff"
    assert "logo.png" not in file_response.headers["content-disposition"]

    edited = client.patch(
        "/api/visual-assets/{}".format(asset["id"]),
        json={"description": "Revised logo usage."},
    )
    assert edited.status_code == 200
    assert edited.json()["approval_status"] == "pending"
    assert edited.json()["version"] == 2


def test_visual_asset_upload_rejects_mime_content_mismatch_and_invalid_pdf(client):
    mismatch = client.post(
        "/api/visual-assets",
        data={"asset_type": "logo"},
        files={"file": ("logo.png", b"%PDF-1.4", "image/png")},
    )
    assert mismatch.status_code == 422

    invalid_pdf = client.post(
        "/api/visual-assets",
        data={"asset_type": "template"},
        files={"file": ("template.pdf", b"%PDF-not-a-valid-document", "application/pdf")},
    )
    assert invalid_pdf.status_code == 422


def test_contributor_can_submit_but_cannot_inspect_or_approve_pending_asset(
    client, test_engine
):
    _login_as_contributor(client, test_engine)
    upload = client.post(
        "/api/visual-assets",
        data={"name": "Submitted icon", "asset_type": "brand_icon"},
        files={"file": ("icon.png", _png_bytes("blue"), "image/png")},
    )
    assert upload.status_code == 201
    asset_id = upload.json()["id"]
    assert upload.json()["approval_status"] == "pending"
    assert client.get("/api/visual-assets").json() == []
    assert client.get("/api/visual-assets/{}/file".format(asset_id)).status_code == 404
    assert client.patch(
        "/api/visual-assets/{}/approval".format(asset_id),
        json={"status": "approved"},
    ).status_code == 403
    assert client.patch(
        "/api/visual-assets/{}".format(asset_id),
        json={"name": "Unauthorized edit"},
    ).status_code == 403

    _login_as_admin(client)
    assert client.patch(
        "/api/visual-assets/{}/approval".format(asset_id),
        json={"status": "approved"},
    ).status_code == 200
    _login_as_contributor(client, test_engine)
    assert len(client.get("/api/visual-assets").json()) == 1
    assert client.get("/api/visual-assets/{}/file".format(asset_id)).status_code == 200


def test_reviewer_can_inspect_but_not_approve_visual_assets(client, test_engine):
    from app.models.user import User
    from app.services.auth_service import hash_password

    pending = client.post(
        "/api/visual-assets",
        data={"name": "Reviewer inspection", "asset_type": "logo"},
        files={"file": ("logo.png", _png_bytes(), "image/png")},
    ).json()
    with Session(test_engine) as db:
        db.add(
            User(
                email="visual-reviewer@example.test",
                display_name="Visual Reviewer",
                password_hash=hash_password("visual-reviewer-password"),
                role="reviewer",
                is_active=True,
                must_change_password=False,
            )
        )
        db.commit()
    login = client.post(
        "/api/auth/login",
        json={
            "email": "visual-reviewer@example.test",
            "password": "visual-reviewer-password",
        },
    )
    assert login.status_code == 200
    assert client.get("/api/visual-assets/{}".format(pending["id"])).status_code == 200
    assert client.get(pending["file_url"]).status_code == 200
    assert client.patch(
        "/api/visual-assets/{}/approval".format(pending["id"]),
        json={"status": "approved"},
    ).status_code == 403


def test_mult_page_pdf_analysis_preserves_page_reports_and_private_preview(client):
    pdf_bytes = _make_pdf()
    response = client.post(
        "/api/analyze",
        data={"title": "Multi-page artwork", "content": "Please review this design."},
        files={"file": ("campaign.pdf", pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 200
    body = response.json()
    analysis = body["image_analysis"]
    assert analysis["format"] == "pdf"
    assert analysis["page_count"] == 2
    assert [page["page_number"] for page in analysis["pages"]] == [1, 2]
    assert all(
        "Full page rendering is unavailable" in " ".join(page["limitations"])
        for page in analysis["pages"]
    )

    review = client.get("/api/reviews/{}".format(body["id"]))
    assert review.status_code == 200
    attachment = review.json()["visual_attachment"]
    assert attachment["media_type"] == "application/pdf"
    assert attachment["analysis"]["page_count"] == 2
    assert [page["page_number"] for page in attachment["analysis"]["pages"]] == [1, 2]
    preview = client.get(attachment["url"])
    assert preview.status_code == 200
    assert preview.content == pdf_bytes
    assert preview.headers["x-content-type-options"] == "nosniff"


def test_visual_file_upload_rejects_unsupported_and_oversized_pdf(client, monkeypatch):
    from app.routes import analysis

    unsupported = client.post(
        "/api/analyze",
        data={"content": "Review this asset"},
        files={"file": ("asset.gif", b"GIF89a", "image/gif")},
    )
    assert unsupported.status_code == 422

    monkeypatch.setattr(analysis, "MAX_UPLOAD_SIZE", 4)
    oversized = client.post(
        "/api/analyze",
        data={"content": "Review this asset"},
        files={"file": ("asset.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert oversized.status_code == 413


def test_palette_visual_finding_contains_advisory_page_details(client, monkeypatch):
    from app.services import image_analyzer

    monkeypatch.setattr(image_analyzer, "BRAND_PALETTE", ["#000000"])
    monkeypatch.setattr(image_analyzer, "PALETTE_TOLERANCE", 0)
    response = client.post(
        "/api/analyze",
        data={"content": "Please review the campaign artwork."},
        files={"file": ("campaign.png", _png_bytes(), "image/png")},
    )
    assert response.status_code == 200
    finding = next(
        item
        for item in response.json()["findings"]
        if item["category"] == "visual_brand"
    )
    assert finding["visual_data"]["page_number"] == 1
    assert finding["visual_data"]["actual_value"] == "#FFFFFF"
    assert finding["visual_data"]["expected_value"] == ["#000000"]
    assert finding["matched_text"] is None
    assert "evidence_status" not in finding


def test_visual_guideline_is_referenced_and_inactive_guideline_is_ignored(
    client, monkeypatch
):
    from app.services import image_analyzer

    monkeypatch.setattr(image_analyzer, "BRAND_PALETTE", [])
    monkeypatch.setattr(image_analyzer, "PALETTE_TOLERANCE", 0)
    guideline = client.post(
        "/api/guidelines",
        json={
            "name": "Primary visual colour",
            "category": "visual_identity",
            "description": "Use #000000 as the primary brand colour.",
            "severity": "critical",
        },
    )
    assert guideline.status_code == 201
    response = client.post(
        "/api/analyze",
        data={
            "content": "Please review the campaign artwork.",
            "guideline_ids": "[{}]".format(guideline.json()["id"]),
        },
        files={"file": ("campaign.png", _png_bytes(), "image/png")},
    )
    assert response.status_code == 200
    visual_finding = next(
        item for item in response.json()["findings"]
        if item["category"] == "visual_brand"
    )
    assert visual_finding["guideline_id"] == guideline.json()["id"]
    assert visual_finding["severity"] == "critical"

    deactivated = client.delete(
        "/api/guidelines/{}".format(guideline.json()["id"])
    )
    assert deactivated.status_code in {200, 204}
    without_visual_rule = client.post(
        "/api/analyze",
        data={"content": "Please review the campaign artwork."},
        files={"file": ("campaign.png", _png_bytes(), "image/png")},
    )
    assert without_visual_rule.status_code == 200
    assert not any(
        item.get("guideline_id") == guideline.json()["id"]
        for item in without_visual_rule.json()["findings"]
    )


def test_visual_asset_rejection_requires_reason_and_approval_is_admin_only(
    client
):
    upload = client.post(
        "/api/visual-assets",
        data={"name": "Rejected icon", "asset_type": "brand_icon"},
        files={"file": ("icon.png", _png_bytes(), "image/png")},
    )
    asset_id = upload.json()["id"]
    assert client.patch(
        "/api/visual-assets/{}/approval".format(asset_id),
        json={"status": "rejected"},
    ).status_code == 422
    rejected = client.patch(
        "/api/visual-assets/{}/approval".format(asset_id),
        json={"status": "rejected", "note": "Incorrect variant."},
    )
    assert rejected.status_code == 200
    assert rejected.json()["approval_status"] == "rejected"


def test_expired_or_inactive_approved_assets_are_not_comparison_references(client):
    expired = (date.today() - timedelta(days=1)).isoformat()
    upload = client.post(
        "/api/visual-assets",
        data={
            "name": "Expired primary mark",
            "asset_type": "logo",
            "expiry_date": expired,
        },
        files={"file": ("expired.png", _png_bytes("black"), "image/png")},
    )
    assert upload.status_code == 201
    asset_id = upload.json()["id"]
    approved = client.patch(
        "/api/visual-assets/{}/approval".format(asset_id),
        json={"status": "approved"},
    )
    assert approved.json()["lifecycle_status"] == "expired"

    analysis = client.post(
        "/api/analyze",
        data={"content": "Review this visual."},
        files={"file": ("campaign.png", _png_bytes("white"), "image/png")},
    )
    assert analysis.status_code == 200
    comparison = analysis.json()["image_analysis"]["brand_asset_similarity"]
    assert comparison["configured"] is False
    assert comparison["references"] == []


def test_deactivated_asset_reactivation_does_not_restore_approval(client):
    uploaded = client.post(
        "/api/visual-assets",
        data={"name": "Temporary icon", "asset_type": "brand_icon"},
        files={"file": ("icon.png", _png_bytes(), "image/png")},
    ).json()
    asset_id = uploaded["id"]
    assert client.patch(
        "/api/visual-assets/{}/approval".format(asset_id),
        json={"status": "approved"},
    ).status_code == 200

    inactive = client.patch(
        "/api/visual-assets/{}".format(asset_id),
        json={"is_active": False},
    ).json()
    assert inactive["lifecycle_status"] == "inactive"
    assert inactive["approval_status"] == "pending"
    reactivated = client.patch(
        "/api/visual-assets/{}".format(asset_id),
        json={"is_active": True},
    ).json()
    assert reactivated["lifecycle_status"] == "pending"


def test_pdf_page_count_limit_is_enforced_for_visual_upload(client, monkeypatch):
    from app.services import visual_analysis

    monkeypatch.setattr(visual_analysis, "MAX_PDF_PAGES", 1)
    response = client.post(
        "/api/analyze",
        data={"content": "Review this multi-page document."},
        files={"file": ("campaign.pdf", _make_pdf(2), "application/pdf")},
    )
    assert response.status_code == 422
    assert "allowed 1 pages" in response.json()["detail"]


def test_pdf_embedded_raster_image_is_analyzed_with_page_reference(
    client, monkeypatch
):
    from app.services import image_analyzer

    monkeypatch.setattr(image_analyzer, "BRAND_PALETTE", ["#000000"])
    monkeypatch.setattr(image_analyzer, "PALETTE_TOLERANCE", 0)
    response = client.post(
        "/api/analyze",
        data={"content": "Review this PDF design."},
        files={
            "file": (
                "design.pdf",
                _make_pdf_with_embedded_image(),
                "application/pdf",
            )
        },
    )
    assert response.status_code == 200
    page = response.json()["image_analysis"]["pages"][0]
    assert page["page_number"] == 1
    assert len(page["images"]) == 1
    assert page["images"][0]["format"] == "png"
    finding = next(
        item
        for item in response.json()["findings"]
        if item.get("visual_data", {}).get("image_index") == 1
    )
    assert finding["visual_data"]["page_number"] == 1
