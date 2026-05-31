"""Shared visual/OCR/table coverage helpers for document intelligence."""
from __future__ import annotations

from typing import Any


VISUAL_CAPABILITIES_REQUIRING_DESCRIPTION = {
    "caption_alt_text",
    "chart_summary",
    "diagram_description",
    "figure_description",
    "screenshot_state",
}


def capabilities_for_image_ref(
    image_ref: dict[str, Any],
    fallback_capabilities: list[str] | tuple[str, ...] | set[str] | None,
) -> list[str]:
    """Return per-ref requested capabilities, falling back to request-wide capabilities."""
    per_ref = image_ref.get("requested_capabilities") or image_ref.get("required_capabilities")
    capabilities = per_ref if per_ref is not None else fallback_capabilities
    normalized = {str(item).strip() for item in capabilities or [] if str(item).strip()}
    return sorted(normalized)


def build_visual_coverage(
    *,
    visual_request: dict[str, Any],
    artifacts: list[dict[str, Any]],
    waivers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Summarize image-ref and per-capability visual coverage."""
    required_refs = [dict(ref) for ref in visual_request.get("image_refs") or [] if isinstance(ref, dict)]
    fallback_capabilities = list(visual_request.get("requested_capabilities") or [])
    normalized_waivers = [dict(waiver) for waiver in waivers or [] if isinstance(waiver, dict)]
    observed_keys: set[str] = set()
    for artifact in artifacts:
        observed_keys.update(visual_artifact_match_keys(artifact))

    missing_refs = [
        ref for ref in required_refs
        if not (visual_ref_match_keys(ref) & observed_keys)
    ]
    required_capability_count = 0
    covered_capability_count = 0
    missing_capabilities: list[dict[str, Any]] = []
    for ref in required_refs:
        matching_artifacts = [
            artifact for artifact in artifacts if artifact_matches_image_ref(artifact, ref)
        ]
        page_number = page_number_from_ref(ref)
        for capability in capabilities_for_image_ref(ref, fallback_capabilities):
            required_capability_count += 1
            if any(artifact_covers_capability(artifact, capability) for artifact in matching_artifacts):
                covered_capability_count += 1
                continue
            if waiver_covers(normalized_waivers, page_number=page_number, capability=capability):
                covered_capability_count += 1
                continue
            missing_capabilities.append(
                {
                    "page_number": page_number,
                    "capability": capability,
                    "image_ref": ref,
                }
            )

    return {
        "visual_request_id": visual_request.get("request_id"),
        "required_image_ref_count": len(required_refs),
        "covered_image_ref_count": len(required_refs) - len(missing_refs),
        "missing_image_refs": missing_refs,
        "required_capability_count": required_capability_count,
        "covered_capability_count": covered_capability_count,
        "missing_capabilities": missing_capabilities,
        "coverage_complete": not missing_refs and not missing_capabilities,
    }


def artifact_matches_image_ref(artifact: dict[str, Any], image_ref: dict[str, Any]) -> bool:
    return bool(visual_artifact_match_keys(artifact) & visual_ref_match_keys(image_ref))


def visual_artifact_match_keys(artifact: dict[str, Any]) -> set[str]:
    provenance = artifact.get("provenance") if isinstance(artifact.get("provenance"), dict) else {}
    source_ref = dict(provenance.get("source_ref") or {})
    source_artifact_id = provenance.get("source_artifact_id")
    if source_artifact_id and "source_artifact_id" not in source_ref:
        source_ref["source_artifact_id"] = source_artifact_id
    page_number = provenance.get("page_number")
    if page_number and "page_number" not in source_ref and "page" not in source_ref:
        source_ref["page_number"] = page_number
    return visual_ref_match_keys(source_ref)


def visual_ref_match_keys(ref: dict[str, Any]) -> set[str]:
    if not isinstance(ref, dict):
        return set()
    page_number = page_number_from_ref(ref)
    artifact_identifiers = [
        optional_ref_text(ref.get(field))
        for field in (
            "source_artifact_id",
            "source_artifact_ref",
            "artifact_id",
            "ref",
            "image_hash",
        )
    ]
    keys: set[str] = set()
    for identifier in artifact_identifiers:
        if not identifier:
            continue
        keys.add(f"artifact:{identifier}|page:{page_number}" if page_number is not None else f"artifact:{identifier}")
    if keys:
        return keys

    source_uri = optional_ref_text(ref.get("source_uri"))
    if source_uri:
        keys.add(f"source:{source_uri}|page:{page_number}" if page_number is not None else f"source:{source_uri}")
        return keys

    if page_number is not None:
        keys.add(f"page:{page_number}")
    return keys


def artifact_covers_capability(artifact: dict[str, Any], capability: str) -> bool:
    metadata = artifact.get("metadata") if isinstance(artifact.get("metadata"), dict) else {}
    covered = {str(item) for item in metadata.get("capabilities_covered") or [] if str(item).strip()}
    if capability in covered:
        return True
    artifact_type = str(artifact.get("artifact_type") or "")
    if capability == "ocr_text":
        return artifact_type.startswith("ocr") and bool(str(artifact.get("text") or "").strip())
    if capability == "table_structure":
        return artifact_type == "table" and (
            bool(str(artifact.get("text") or artifact.get("description") or "").strip())
            or metadata.get("table_present") is False
        )
    if capability in VISUAL_CAPABILITIES_REQUIRING_DESCRIPTION:
        return bool(str(artifact.get("description") or artifact.get("text") or "").strip())
    return False


def waiver_covers(waivers: list[dict[str, Any]], *, page_number: int | None, capability: str) -> bool:
    for waiver in waivers:
        if str(waiver.get("capability") or "") != capability:
            continue
        waiver_page = page_number_from_ref(waiver)
        if waiver_page is None or page_number is None or waiver_page == page_number:
            return True
    return False


def page_number_from_ref(value: dict[str, Any]) -> int | None:
    page = value.get("page_number") or value.get("page")
    if isinstance(page, bool):
        return None
    try:
        page_int = int(page)
    except (TypeError, ValueError):
        return None
    return page_int if page_int > 0 else None


def optional_ref_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None
