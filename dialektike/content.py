"""Provider-neutral normalization for inert user-visible response content.

Provider adapters may use this module to translate their wire objects into one
small shared vocabulary.  The functions here never execute HTML, open a file,
or fetch a URL.  Authored strings are copied exactly: validation may inspect a
trimmed view for emptiness, but output is never stripped or Unicode-normalized.

Unknown or policy-blocked content becomes a readable ``unknown`` block instead
of invalidating the surrounding response.  Raw provider objects remain on the
owner-only evidence side of the adapter boundary and are not copied into that
fallback.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit


__all__ = [
    "CONTENT_BLOCK_SCHEMA_VERSION",
    "CONTENT_TYPES",
    "ContentNormalizationError",
    "ContentPolicy",
    "content_block_text",
    "content_blocks_text",
    "normalize_content_block",
    "normalize_content_blocks",
]


CONTENT_BLOCK_SCHEMA_VERSION = 1

CONTENT_TYPES = frozenset(
    {
        "markdown",
        "code",
        "diff",
        "math",
        "diagram",
        "citation",
        "file",
        "image",
        "audio",
        "video",
        "tool",
        "editor_reference",
        "unknown",
    }
)

MEDIA_TYPES = frozenset({"image", "audio", "video"})

_SAFE_OPAQUE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_SAFE_TYPE_LABEL = re.compile(r"[^A-Za-z0-9._-]")


class ContentNormalizationError(ValueError):
    """A value cannot safely cross the normalized content boundary."""


@dataclass(frozen=True, slots=True)
class ContentPolicy:
    """Explicit application-owned capabilities for content normalization.

    A provider cannot make a media reference trusted by naming it.  The
    supervising application must first ingest and validate the asset, then
    supply its opaque identifier in ``trusted_asset_ids``.
    """

    trusted_asset_ids: frozenset[str] = field(default_factory=frozenset)
    allow_http_citations: bool = True

    def __post_init__(self) -> None:
        if any(
            not isinstance(item, str) or _SAFE_OPAQUE_ID.fullmatch(item) is None
            for item in self.trusted_asset_ids
        ):
            raise ValueError("trusted asset identifiers must be safe opaque identifiers")
        if not isinstance(self.allow_http_citations, bool):
            raise ValueError("allow_http_citations must be a boolean")


def _required_text(raw: Mapping[str, Any], field_name: str) -> str | None:
    value = raw.get(field_name)
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def _optional_text(raw: Mapping[str, Any], field_name: str) -> str | None:
    value = raw.get(field_name)
    return value if isinstance(value, str) else None


def _copy_optional_text(
    output: dict[str, Any], raw: Mapping[str, Any], *field_names: str
) -> None:
    for field_name in field_names:
        value = _optional_text(raw, field_name)
        if value is not None:
            output[field_name] = value


def _safe_http_url(value: str) -> bool:
    # Keep Python's RFC-oriented parser and browser URL parsing from disagreeing
    # on whitespace, control characters, or backslashes in an authority.
    if any(ord(character) <= 0x20 or ord(character) == 0x7F for character in value):
        return False
    if "\\" in value:
        return False
    try:
        parsed = urlsplit(value)
        # Accessing port performs its validation (and can raise ValueError).
        parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme.casefold() in {"http", "https"}
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
    )


def _provider_type_label(value: str) -> str:
    clean = _SAFE_TYPE_LABEL.sub("", value)[:64]
    return clean or "unknown"


def _readable_text(raw: Mapping[str, Any]) -> str:
    """Select inert authored display text without serializing raw payloads."""

    for field_name in (
        "text",
        "summary",
        "description",
        "html",
        "source",
        "code",
        "diff",
        "label",
        "title",
        "name",
        "url",
        "path",
    ):
        value = raw.get(field_name)
        if isinstance(value, str) and value:
            return value
    return "No readable provider-authored text was available."


def _fallback(
    raw: Mapping[str, Any],
    *,
    provider_type: str,
    reason: str,
    display_text: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": CONTENT_BLOCK_SCHEMA_VERSION,
        "type": "unknown",
        "provider_type": _provider_type_label(provider_type),
        "title": "Unsupported provider content",
        "text": _readable_text(raw) if display_text is None else display_text,
        "reason": reason,
        "presentation": "inert-text",
    }


def content_block_text(block: Mapping[str, Any]) -> str:
    """Return the canonical inert text presented by one normalized block.

    This is the single provider-neutral projection used for persisted turn
    ``text``, model context, and derived search.  Only fields exposed by the
    shared renderer are included; URLs, asset identifiers, actions, and raw
    provider payloads never enter the projection.
    """

    if not isinstance(block, Mapping):
        raise ContentNormalizationError("normalized content block must be an object")
    block_type = block.get("type")
    fields_by_type: dict[str, tuple[str, ...]] = {
        "markdown": ("text",),
        "code": ("title", "language", "code"),
        "diff": ("title", "diff"),
        "math": ("text",),
        "diagram": ("title", "language", "source"),
        "tool": ("title", "status", "summary"),
        "citation": ("label",),
        "file": ("name", "mime_type", "size"),
        "image": ("label", "mime_type", "alt"),
        "audio": ("label", "mime_type", "alt"),
        "video": ("label", "mime_type", "alt"),
        "editor_reference": ("label", "path", "line", "column"),
        "unknown": ("title", "provider_type", "text"),
    }
    fields = fields_by_type.get(block_type) if isinstance(block_type, str) else None
    if fields is None:
        raise ContentNormalizationError(
            f"unsupported normalized content block {block_type!r}"
        )
    visible: list[str] = []
    for field_name in fields:
        value = block.get(field_name)
        if isinstance(value, str):
            if value:
                visible.append(value)
        elif (
            field_name in {"size", "line", "column"}
            and isinstance(value, int)
            and not isinstance(value, bool)
        ):
            visible.append(str(value))
    if not visible:
        raise ContentNormalizationError(
            f"normalized {block_type} block has no canonical presentation text"
        )
    return "\n".join(visible)


def content_blocks_text(blocks: Iterable[Mapping[str, Any]]) -> str:
    """Return the canonical text for ordered normalized content blocks."""

    return "\n\n".join(content_block_text(block) for block in blocks)


def _normalize_markdown(raw: Mapping[str, Any]) -> dict[str, Any]:
    text = _required_text(raw, "text")
    if text is None:
        return _fallback(
            raw,
            provider_type="markdown",
            reason="The Markdown block did not contain readable text.",
        )
    # Raw HTML deliberately remains part of the authored Markdown string.  A
    # renderer must treat it as text; this boundary never converts it to HTML.
    return {
        "schema_version": CONTENT_BLOCK_SCHEMA_VERSION,
        "type": "markdown",
        "text": text,
    }


def _normalize_code_like(
    raw: Mapping[str, Any], block_type: str, value_field: str, *optional_fields: str
) -> dict[str, Any]:
    value = _required_text(raw, value_field)
    if value is None:
        return _fallback(
            raw,
            provider_type=block_type,
            reason=f"The {block_type} block did not contain readable source text.",
        )
    output: dict[str, Any] = {
        "schema_version": CONTENT_BLOCK_SCHEMA_VERSION,
        "type": block_type,
        value_field: value,
    }
    _copy_optional_text(output, raw, *optional_fields)
    return output


def _normalize_math(raw: Mapping[str, Any]) -> dict[str, Any]:
    output = _normalize_code_like(raw, "math", "text")
    if output["type"] == "math":
        display = raw.get("display")
        output["display"] = display if isinstance(display, bool) else True
    return output


def _normalize_diagram(raw: Mapping[str, Any]) -> dict[str, Any]:
    source = _required_text(raw, "source")
    language = _required_text(raw, "language")
    if source is None or language is None:
        return _fallback(
            raw,
            provider_type="diagram",
            reason="The diagram did not contain both source text and a language.",
        )
    output: dict[str, Any] = {
        "schema_version": CONTENT_BLOCK_SCHEMA_VERSION,
        "type": "diagram",
        "source": source,
        "language": language,
    }
    _copy_optional_text(output, raw, "title")
    return output


def _normalize_citation(
    raw: Mapping[str, Any], policy: ContentPolicy
) -> dict[str, Any]:
    label = _required_text(raw, "label")
    url = _required_text(raw, "url")
    if label is None or url is None:
        return _fallback(
            raw,
            provider_type="citation",
            reason="The citation did not contain both a label and URL.",
        )
    if not policy.allow_http_citations or not _safe_http_url(url):
        return _fallback(
            raw,
            provider_type="citation",
            reason="The citation URL was blocked by the inert-content policy.",
            display_text=f"{label}\n{url}",
        )
    return {
        "schema_version": CONTENT_BLOCK_SCHEMA_VERSION,
        "type": "citation",
        "label": label,
        "url": url,
    }


def _normalize_file(raw: Mapping[str, Any]) -> dict[str, Any]:
    name = _required_text(raw, "name")
    if name is None:
        return _fallback(
            raw,
            provider_type="file",
            reason="The file block did not contain a display name.",
        )
    output: dict[str, Any] = {
        "schema_version": CONTENT_BLOCK_SCHEMA_VERSION,
        "type": "file",
        "name": name,
        # Files are metadata, not links or filesystem capabilities.
        "presentation": "inert-metadata",
    }
    _copy_optional_text(output, raw, "mime_type")
    size = raw.get("size")
    if isinstance(size, int) and not isinstance(size, bool) and size >= 0:
        output["size"] = size
    return output


def _normalize_media(
    raw: Mapping[str, Any], block_type: str, policy: ContentPolicy
) -> dict[str, Any]:
    asset_id = raw.get("asset_id")
    label = _required_text(raw, "label")
    if (
        not isinstance(asset_id, str)
        or asset_id not in policy.trusted_asset_ids
        or label is None
    ):
        return _fallback(
            raw,
            provider_type=block_type,
            reason=(
                "Model-authored media was not fetched. Only an "
                "application-ingested local asset may render."
            ),
        )
    output: dict[str, Any] = {
        "schema_version": CONTENT_BLOCK_SCHEMA_VERSION,
        "type": block_type,
        "asset_id": asset_id,
        "label": label,
    }
    _copy_optional_text(output, raw, "alt", "mime_type")
    # In particular, never copy a model-authored URL or path into a renderable
    # media block, even when a separate trusted asset id is present.
    return output


def _normalize_tool(raw: Mapping[str, Any]) -> dict[str, Any]:
    title = _required_text(raw, "title")
    if title is None:
        return _fallback(
            raw,
            provider_type="tool",
            reason="The tool activity block did not contain a title.",
        )
    output: dict[str, Any] = {
        "schema_version": CONTENT_BLOCK_SCHEMA_VERSION,
        "type": "tool",
        "title": title,
    }
    _copy_optional_text(output, raw, "summary", "status")
    return output


def _normalize_editor_reference(raw: Mapping[str, Any]) -> dict[str, Any]:
    path = _required_text(raw, "path")
    label = _required_text(raw, "label")
    if path is None or label is None:
        return _fallback(
            raw,
            provider_type="editor_reference",
            reason="The editor reference did not contain both a label and path.",
        )
    output: dict[str, Any] = {
        "schema_version": CONTENT_BLOCK_SCHEMA_VERSION,
        "type": "editor_reference",
        "path": path,
        "label": label,
        "presentation": "inert-reference",
    }
    for field_name in ("line", "column"):
        value = raw.get(field_name)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
            output[field_name] = value
    return output


def normalize_content_block(
    raw: Mapping[str, Any],
    *,
    declared_types: Collection[str] | None = None,
    policy: ContentPolicy | None = None,
) -> dict[str, Any]:
    """Normalize one provider-mapped block into the inert shared vocabulary."""

    if not isinstance(raw, Mapping):
        raise ContentNormalizationError("content block must be an object")
    raw_type = raw.get("type")
    provider_type = raw_type if isinstance(raw_type, str) and raw_type else "unknown"
    if declared_types is not None and provider_type not in declared_types:
        return _fallback(
            raw,
            provider_type=provider_type,
            reason="The provider emitted a content type absent from its descriptor.",
        )
    chosen_policy = policy or ContentPolicy()
    if provider_type == "markdown":
        return _normalize_markdown(raw)
    if provider_type == "code":
        return _normalize_code_like(raw, "code", "code", "language", "title")
    if provider_type == "diff":
        return _normalize_code_like(raw, "diff", "diff", "title")
    if provider_type == "math":
        return _normalize_math(raw)
    if provider_type == "diagram":
        return _normalize_diagram(raw)
    if provider_type == "citation":
        return _normalize_citation(raw, chosen_policy)
    if provider_type == "file":
        return _normalize_file(raw)
    if provider_type in MEDIA_TYPES:
        return _normalize_media(raw, provider_type, chosen_policy)
    if provider_type == "tool":
        return _normalize_tool(raw)
    if provider_type == "editor_reference":
        return _normalize_editor_reference(raw)
    return _fallback(
        raw,
        provider_type=provider_type,
        reason="No safe shared renderer is registered for this content type.",
    )


def normalize_content_blocks(
    raw_blocks: Iterable[Mapping[str, Any]],
    *,
    declared_types: Collection[str] | None = None,
    policy: ContentPolicy | None = None,
) -> tuple[dict[str, Any], ...]:
    """Normalize blocks in provider order without flattening their content."""

    return tuple(
        normalize_content_block(
            block,
            declared_types=declared_types,
            policy=policy,
        )
        for block in raw_blocks
    )
