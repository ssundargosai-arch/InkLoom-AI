from datetime import date
from io import BytesIO
from pathlib import PurePath
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.config import MAX_IMAGE_PIXELS, MAX_UPLOAD_SIZE, OCR_ENABLED
from app.services.image_analyzer import (
    ImageAnalysisConfigurationError,
    inspect_image,
)

MAX_PDF_PAGES = 100
MAX_EMBEDDED_IMAGES_PER_PAGE = 30
MAX_EMBEDDED_IMAGES_PER_PDF = 20
MAX_EMBEDDED_IMAGE_BYTES_PER_PDF = 50 * 1024 * 1024
MAX_EXTRACTED_PDF_TEXT = 2_000_000
_MIME_BY_FORMAT = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
}
_HEX_COLOR = re.compile(r"(?<![0-9A-Fa-f])#?([0-9A-Fa-f]{6})(?![0-9A-Fa-f])")
_VISUAL_CATEGORIES = {
    "visual",
    "visual_brand",
    "visual_identity",
    "brand_color",
    "brand_colour",
    "brand_colors",
    "brand_colours",
    "logo",
    "accessibility",
}


def _normalized_category(value: Optional[str]) -> str:
    return (value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _guideline_colors(guidelines) -> List[Dict[str, Any]]:
    colors = []
    for guideline in guidelines:
        category = _normalized_category(guideline.category)
        if category not in _VISUAL_CATEGORIES:
            continue
        text = " ".join(
            [
                guideline.name or "",
                guideline.description or "",
                " ".join(guideline.examples or []),
            ]
        )
        for match in _HEX_COLOR.finditer(text):
            color = "#" + match.group(1).upper()
            if not any(item["color"] == color for item in colors):
                colors.append(
                    {
                        "color": color,
                        "guideline_id": guideline.id,
                        "guideline": guideline.name,
                    }
                )
    return colors


def _validate_image_bytes(image_bytes: bytes) -> Tuple[str, int, int]:
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image_format = image.format
            width, height = image.size
            if width < 1 or height < 1 or width * height > MAX_IMAGE_PIXELS:
                raise ValueError("Image dimensions exceed the configured pixel limit.")
            image.verify()
    except ValueError:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("The uploaded file is not a valid supported visual file.") from exc
    if image_format not in _MIME_BY_FORMAT:
        raise ValueError("Only PNG, JPEG, WEBP, and PDF visual files are supported.")
    return image_format, width, height


def validate_visual_upload(filename: str, media_type: Optional[str], file_bytes: bytes):
    extension = PurePath(filename).suffix.lower()
    if extension == ".pdf":
        if media_type and media_type not in {"application/pdf", "application/octet-stream"}:
            raise ValueError("The PDF extension does not match the declared content type.")
        if not file_bytes.startswith(b"%PDF-"):
            raise ValueError("The uploaded file is not a valid PDF.")
        _read_pdf(file_bytes)
        return "application/pdf"
    expected_extensions = {
        ".png": "PNG",
        ".jpg": "JPEG",
        ".jpeg": "JPEG",
        ".webp": "WEBP",
    }
    expected_format = expected_extensions.get(extension)
    if expected_format is None:
        raise ValueError("Only PNG, JPG, JPEG, WEBP, and PDF files are supported.")
    if media_type and media_type not in {
        _MIME_BY_FORMAT[expected_format],
        "application/octet-stream",
    }:
        raise ValueError("The image extension does not match the declared content type.")
    image_format, _, _ = _validate_image_bytes(file_bytes)
    if image_format != expected_format:
        raise ValueError("The image extension does not match the detected file contents.")
    return _MIME_BY_FORMAT[image_format]


def _read_pdf(file_bytes: bytes):
    try:
        reader = PdfReader(BytesIO(file_bytes), strict=True)
        if reader.is_encrypted:
            raise ValueError("Encrypted PDFs are not supported.")
        page_count = len(reader.pages)
        if page_count == 0:
            raise ValueError("The PDF contains no pages.")
        if page_count > MAX_PDF_PAGES:
            raise ValueError(
                "PDF contains more than the allowed {} pages.".format(MAX_PDF_PAGES)
            )
        return reader
    except ValueError:
        raise
    except (PdfReadError, OSError, KeyError) as exc:
        raise ValueError("The uploaded PDF could not be parsed.") from exc


def _image_findings(
    image_info: Dict[str, Any],
    page_number: Optional[int],
    image_index: Optional[int],
    guidelines: Iterable[Any],
) -> List[Dict[str, Any]]:
    findings = []
    visual_guidelines = [
        item
        for item in guidelines
        if _normalized_category(item.category) in _VISUAL_CATEGORIES
    ]
    guide_colors = _guideline_colors(visual_guidelines)
    expected_colors = [item["color"] for item in guide_colors]
    palette = image_info.get("palette_comparison")

    def add_finding(
        title,
        category,
        severity,
        explanation,
        suggestion,
        method,
        actual=None,
        expected=None,
        confidence=None,
        guideline=None,
        region=None,
        extra=None,
    ):
        visual_data = {
            "page_number": page_number,
            "image_index": image_index,
            "actual_value": actual,
            "expected_value": expected,
            "detection_method": method,
            "confidence": confidence,
            "region": region,
            "source_reference": (
                {"guideline_id": guideline.id, "title": guideline.name}
                if guideline
                else None
            ),
        }
        if extra:
            visual_data.update(extra)
        findings.append(
            {
                "category": category,
                "severity": severity,
                "title": title,
                "explanation": explanation,
                "matched_text": None,
                "suggestion": suggestion,
                "source": guideline.name if guideline else method,
                "guideline": guideline.name if guideline else None,
                "guideline_id": guideline.id if guideline else None,
                "confidence": confidence,
                "visual_data": visual_data,
            }
        )

    if palette and palette.get("potential_mismatch"):
        first_mismatch = next(
            (
                item
                for item in palette["colors"]
                if not item["within_tolerance"]
            ),
            None,
        )
        guideline = guide_colors[0] if guide_colors else None
        if guideline:
            guideline = next(
                (
                    candidate
                    for candidate in visual_guidelines
                    if candidate.id == guideline["guideline_id"]
                ),
                None,
            )
        add_finding(
            "Image colours may differ from the approved brand palette",
            "visual_brand",
            guideline.severity if guideline else "medium",
            "A measured dominant colour differs from the configured or guideline palette using an approximate RGB-distance heuristic. Human visual review is required.",
            "Compare the image with the approved palette and update only if the difference is unintended.",
            palette["method"],
            actual=first_mismatch["image_color"] if first_mismatch else None,
            expected=expected_colors or palette.get("expected_colors") or None,
            confidence=None,
            guideline=guideline,
            extra={"palette_comparison": palette},
        )

    similarity = image_info.get("brand_asset_similarity")
    if similarity and similarity.get("potential_mismatch"):
        best = max(
            similarity.get("references", []),
            key=lambda item: item["similarity_percent"],
            default=None,
        )
        compared_to_library = any(
            item.get("asset_id") is not None
            for item in similarity.get("references", [])
        )
        add_finding(
            "Image differs from an approved logo or brand asset"
            if compared_to_library
            else "Image differs from configured brand asset references",
            "visual_brand",
            "low",
            "The image's highest coarse similarity to an approved logo or configured reference is below the comparison threshold. Similarity does not establish whether an asset is authorized.",
            "Confirm this is an approved variant or replace it with the current approved asset.",
            "64-bit difference hash; coarse visual similarity only",
            actual=best["similarity_percent"] if best else None,
            expected=similarity.get("threshold_percent"),
            confidence=None,
            extra={
                "asset_candidates": similarity.get("references", []),
                "asset_library_comparison": True,
            },
        )

    layout_metrics = image_info.get("layout_metrics") or {}
    if layout_metrics.get("small_for_large_display"):
        add_finding(
            "Image resolution may be low for large-format display",
            "visual_brand",
            "low",
            "The longest image dimension is below 500 pixels. This is a scale heuristic only; suitability depends on intended placement and output resolution.",
            "Check the intended placement and use a higher-resolution approved source when needed.",
            "Image dimensions heuristic",
            actual={
                "width": image_info.get("width"),
                "height": image_info.get("height"),
            },
            expected={"longest_dimension_pixels": 500},
            confidence=None,
        )

    for contrast in image_info.get("text_contrast", []):
        if contrast.get("meets_wcag_aa_estimate"):
            continue
        add_finding(
            "Detected text may have insufficient contrast",
            "accessibility",
            "high",
            "OCR estimated a text/background contrast ratio of {0}:1 against an approximate WCAG AA threshold of {1}:1. Automated colour sampling may misidentify text or its background and is not a complete accessibility audit.".format(
                contrast["contrast_ratio"], contrast["threshold"]
            ),
            "Verify the text and background colours manually, then target at least 4.5:1 for normal text or 3:1 for large text.",
            contrast["method"],
            actual={
                "text": contrast["text"],
                "contrast_ratio": contrast["contrast_ratio"],
                "estimated_colors": contrast["foreground_background_estimate"],
            },
            expected={"wcag_aa_minimum": contrast["threshold"]},
            confidence=contrast["confidence"],
            region=contrast["region"],
            extra={"contrast_ratio": contrast["contrast_ratio"]},
        )
    return findings


def analyze_visual_file(
    filename: str,
    media_type: Optional[str],
    file_bytes: bytes,
    guidelines,
    approved_logo_assets,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    if not file_bytes:
        raise ValueError("Uploaded visual file is empty.")
    if len(file_bytes) > MAX_UPLOAD_SIZE:
        raise ValueError("Image or PDF exceeds the configured maximum upload size.")
    validated_media_type = validate_visual_upload(filename, media_type, file_bytes)
    guideline_colors = _guideline_colors(guidelines)
    approved_colors = [item["color"] for item in guideline_colors]
    findings = []
    if validated_media_type != "application/pdf":
        image_info = inspect_image(
            file_bytes,
            OCR_ENABLED,
            approved_asset_references=approved_logo_assets,
            approved_colors=approved_colors,
        )
        findings.extend(_image_findings(image_info, 1, None, guidelines))
        image_info["pages"] = [
            {
                "page_number": 1,
                "images": [
                    {
                        key: value
                        for key, value in image_info.items()
                        if key != "pages"
                    }
                ],
                "text_layer_detected": bool(image_info.get("extracted_text")),
                "rasterized": True,
            }
        ]
        return image_info, findings

    reader = _read_pdf(file_bytes)
    pages = []
    limitations = []
    extracted_text_length = 0
    total_embedded_images = 0
    total_embedded_image_bytes = 0
    for page_index, page in enumerate(reader.pages):
        page_number = page_index + 1
        try:
            page_text = page.extract_text() or ""
        except (KeyError, ValueError, OSError, PdfReadError):
            page_text = ""
            limitations.append(
                "Page {} text extraction failed; the page was not silently treated as analyzed.".format(
                    page_number
                )
            )
        remaining_text = max(0, MAX_EXTRACTED_PDF_TEXT - extracted_text_length)
        if len(page_text) > remaining_text:
            page_text = page_text[:remaining_text]
            limitations.append(
                "Extracted PDF text exceeded the configured analysis budget and was truncated."
            )
        extracted_text_length += len(page_text)
        page_result = {
            "page_number": page_number,
            "text": page_text,
            "text_layer_detected": bool(page_text.strip()),
            "text_characters": len(page_text),
            "images": [],
            "rasterized": False,
            "limitations": [
                "Full page rendering is unavailable; page layout, vector artwork, and placement were not raster-analyzed."
            ],
        }
        try:
            embedded_images = list(page.images)
        except (KeyError, ValueError, OSError, NotImplementedError, PdfReadError):
            embedded_images = []
            page_result["limitations"].append(
                "Embedded image extraction failed; this page's visual composition was not rasterized."
            )
        if len(embedded_images) > MAX_EMBEDDED_IMAGES_PER_PAGE:
            embedded_images = embedded_images[:MAX_EMBEDDED_IMAGES_PER_PAGE]
            page_result["limitations"].append(
                "Only the first {} embedded images on this page were inspected.".format(
                    MAX_EMBEDDED_IMAGES_PER_PAGE
                )
            )
        for image_index, embedded in enumerate(embedded_images, start=1):
            if (
                total_embedded_images >= MAX_EMBEDDED_IMAGES_PER_PDF
                or total_embedded_image_bytes >= MAX_EMBEDDED_IMAGE_BYTES_PER_PDF
            ):
                page_result["limitations"].append(
                    "The PDF reached the embedded-image analysis budget; remaining images were not inspected."
                )
                break
            try:
                image_bytes = embedded.data
                if len(image_bytes) > MAX_UPLOAD_SIZE:
                    page_result["limitations"].append(
                        "Embedded image {} exceeded the per-image size limit and was not inspected.".format(
                            image_index
                        )
                    )
                    continue
                if (
                    total_embedded_image_bytes + len(image_bytes)
                    > MAX_EMBEDDED_IMAGE_BYTES_PER_PDF
                ):
                    page_result["limitations"].append(
                        "The PDF reached the embedded-image byte budget; remaining images were not inspected."
                    )
                    break
                image_info = inspect_image(
                    image_bytes,
                    OCR_ENABLED,
                    approved_asset_references=approved_logo_assets,
                    approved_colors=approved_colors,
                )
            except ImageAnalysisConfigurationError:
                raise
            except (
                ValueError,
                OSError,
                PdfReadError,
                UnidentifiedImageError,
            ) as exc:
                page_result["limitations"].append(
                    "Embedded image {} could not be analyzed ({})".format(
                        image_index, type(exc).__name__
                    )
                )
                continue
            page_result["images"].append(image_info)
            total_embedded_images += 1
            total_embedded_image_bytes += len(image_bytes)
            page_result["limitations"].extend(image_info.get("limitations", []))
            findings.extend(
                _image_findings(
                    image_info, page_number, image_index, guidelines
                )
            )
        if not embedded_images:
            page_result["limitations"].append(
                "No supported embedded raster image was extracted. Text was extracted where available; page contrast and logo placement could not be assessed."
            )
        limitations.extend(page_result["limitations"])
        pages.append(page_result)
    return (
        {
            "format": "pdf",
            "page_count": len(pages),
            "pages": pages,
            "limitations": list(dict.fromkeys(limitations)),
            "detection_method": "PDF text extraction and supported embedded-raster-image analysis; page rendering is not configured.",
        },
        findings,
    )


def asset_lifecycle_status(asset, today: Optional[date] = None) -> str:
    today = today or date.today()
    if not asset.is_active:
        return "inactive"
    if asset.expiry_date and asset.expiry_date < today:
        return "expired"
    if asset.valid_from and asset.valid_from > today:
        return "not_yet_valid"
    return asset.approval_status


def visual_analysis_summary(report: Dict[str, Any]) -> Dict[str, Any]:
    if report.get("format") == "pdf":
        return {
            "format": "pdf",
            "page_count": report.get("page_count", 0),
            "detection_method": report.get("detection_method"),
            "limitations": report.get("limitations", []),
            "pages": [
                {
                    "page_number": page.get("page_number"),
                    "text_layer_detected": page.get("text_layer_detected", False),
                    "text_characters": page.get("text_characters", 0),
                    "images": [
                        _image_summary(image)
                        for image in page.get("images", [])
                    ],
                    "limitations": page.get("limitations", []),
                }
                for page in report.get("pages", [])
            ],
        }
    return _image_summary(report)


def _image_summary(image_info: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "format": image_info.get("format"),
        "width": image_info.get("width"),
        "height": image_info.get("height"),
        "dominant_colors": image_info.get("dominant_colors", []),
        "layout_metrics": image_info.get("layout_metrics"),
        "palette_comparison": image_info.get("palette_comparison"),
        "brand_asset_similarity": image_info.get("brand_asset_similarity"),
        "text_contrast": [
            {
                "contrast_ratio": item.get("contrast_ratio"),
                "threshold": item.get("threshold"),
                "meets_wcag_aa_estimate": item.get("meets_wcag_aa_estimate"),
                "confidence": item.get("confidence"),
                "region": item.get("region"),
            }
            for item in image_info.get("text_contrast", [])
        ],
        "limitations": image_info.get("limitations", []),
    }
