#!/usr/bin/env python3
"""Validate best-seo-article media and embedded dataset manifests.

The validator is offline and works with the standard library alone; the free
``idna`` package optionally enables browser-stable internationalized hosts.
It emits one deterministic JSON report to stdout and never mutates the package.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import math
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree

try:  # Optional; absence fails internationalized A-labels closed.
    import idna as idna2008
except ImportError:  # pragma: no cover - exercised by portable fallback tests.
    idna2008 = None


VERSION = "0.1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RFC3339_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\Z"
)
PLACEHOLDER = re.compile(
    r"(?:\[NEEDS[^\]]*\]|\bTODO\b|\bTBD\b|<placeholder>|lorem ipsum)",
    re.IGNORECASE,
)
NEGATIVE_REVIEW_EVIDENCE = re.compile(
    r"(?:"
    r"\b(?:this|it|evidence|result|asset|review)?[ \t]*(?:was|is|were|are)[ \t]+not[ \t]+(?:checked|verified|observed|inspected|reviewed)\b"
    r"|\bcould[ \t]+not[ \t]+(?:check|verify|observe|inspect|review)\b"
    r"|\b(?:evidence|observation|verification|inspection|review)[ \t]+(?:is|was)[ \t]+unavailable\b"
    r"|\bno[ \t]+(?:observation|inspection|verification|review)[ \t]+(?:was|is)[ \t]+(?:made|performed|recorded)\b"
    r")",
    re.IGNORECASE,
)


def reject_nonfinite_json_constant(token: str) -> Any:
    raise json.JSONDecodeError(f"non-finite JSON number is not allowed: {token}", token, 0)


def parse_finite_json_float(token: str) -> float:
    value = float(token)
    if not math.isfinite(value):
        raise json.JSONDecodeError(f"non-finite JSON number is not allowed: {token}", token, 0)
    return value


def reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise json.JSONDecodeError(f"duplicate JSON object key is not allowed: {key!r}", key, 0)
        result[key] = value
    return result


def strict_json_loads(text: str) -> Any:
    return json.loads(
        text,
        parse_constant=reject_nonfinite_json_constant,
        parse_float=parse_finite_json_float,
        object_pairs_hook=reject_duplicate_json_keys,
    )
ASSET_TYPES = {"hero", "screenshot", "diagram", "table", "chart", "video"}
SOURCE_KINDS = {
    "first_party",
    "user_provided",
    "licensed_stock",
    "open_license",
    "screenshot",
    "derived_from_dataset",
    "ai_generated",
}
USAGE_BASES = {"owned", "permission", "licensed", "public_domain", "editorial_reviewed"}
SEVERITY_ORDER = {"error": 0, "warning": 1}
ACTIVE_MIME_TYPES = {"image/svg+xml", "text/html"}
MIME_EXTENSIONS: dict[str, set[str]] = {
    "image/png": {".png"},
    "image/jpeg": {".jpg", ".jpeg"},
    "image/webp": {".webp"},
    "image/gif": {".gif"},
    "image/avif": {".avif"},
    "image/svg+xml": {".svg"},
    "text/html": {".html", ".htm"},
    "video/mp4": {".mp4"},
    "video/webm": {".webm"},
}
RASTER_MIME_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif", "image/avif"}
MIME_TYPES_BY_ASSET: dict[str, set[str]] = {
    "hero": RASTER_MIME_TYPES,
    "screenshot": RASTER_MIME_TYPES,
    "diagram": RASTER_MIME_TYPES | {"image/svg+xml"},
    "chart": RASTER_MIME_TYPES | {"image/svg+xml"},
    "table": {"text/html"},
    "video": {"video/mp4", "video/webm"},
}
MAX_ACTIVE_CONTENT_BYTES = 2 * 1024 * 1024
INVISIBLE_VISIBLE_CATEGORY_EXCEPTIONS = {"\u115f", "\u1160", "\u2800", "\u3164", "\uffa0"}
DEFAULT_IGNORABLE_RANGES = (
    (0x00AD, 0x00AD),
    (0x034F, 0x034F),
    (0x061C, 0x061C),
    (0x115F, 0x1160),
    (0x17B4, 0x17B5),
    (0x180B, 0x180F),
    (0x200B, 0x200F),
    (0x202A, 0x202E),
    (0x2060, 0x206F),
    (0x3164, 0x3164),
    (0xFE00, 0xFE0F),
    (0xFEFF, 0xFEFF),
    (0xFFA0, 0xFFA0),
    (0xFFF0, 0xFFF8),
    (0x1BCA0, 0x1BCA3),
    (0x1D173, 0x1D17A),
    (0xE0000, 0xE0FFF),
)
VISIBLE_CATEGORY_PREFIXES = {"L", "N", "P", "S"}
ALPHANUMERIC_CATEGORY_PREFIXES = {"L", "N"}
STATIC_HTML_TAGS = {
    "abbr",
    "br",
    "caption",
    "col",
    "colgroup",
    "em",
    "p",
    "span",
    "strong",
    "sub",
    "sup",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
}
STATIC_HTML_ATTRIBUTES = {
    "abbr",
    "aria-label",
    "class",
    "colspan",
    "headers",
    "id",
    "rowspan",
    "scope",
    "span",
    "title",
}
STATIC_SVG_TAGS = {
    "circle",
    "clipPath",
    "defs",
    "desc",
    "ellipse",
    "g",
    "line",
    "linearGradient",
    "mask",
    "metadata",
    "path",
    "pattern",
    "polygon",
    "polyline",
    "radialGradient",
    "rect",
    "stop",
    "svg",
    "text",
    "title",
    "tspan",
    "use",
}

TransformRecord = dict[str, str]
DatasetRecord = tuple[set[str], dict[str, TransformRecord], bool | None]


class ValidatorUnavailable(RuntimeError):
    """Raised when the validator cannot perform a requested environmental check."""


class StaticHTMLValidator(HTMLParser):
    """Reject executable or destination-mutating markup in table fragments."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.problem: str | None = None
        self.seen_table = False
        self.seen_header_cell = False
        self.seen_data_cell = False
        self.table_has_aria_label = False
        self.caption_depth = 0
        self.caption_text: list[str] = []
        self.cell_text: list[str] = []

    def reject(self, message: str) -> None:
        if self.problem is None:
            self.problem = message

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.casefold()
        if normalized not in STATIC_HTML_TAGS:
            self.reject(f"Element <{normalized}> is not allowed in static table HTML.")
            return
        for name, _value in attrs:
            attribute = name.casefold()
            if attribute.startswith("on") or attribute not in STATIC_HTML_ATTRIBUTES:
                self.reject(f"Attribute {attribute!r} is not allowed in static table HTML.")

        if normalized == "table":
            self.seen_table = True
            self.table_has_aria_label = any(
                name.casefold() == "aria-label" and semantic_text(value)
                for name, value in attrs
                if isinstance(value, str)
            )
        elif normalized == "caption":
            self.caption_depth += 1
        elif normalized == "th":
            self.seen_header_cell = True
        elif normalized == "td":
            self.seen_data_cell = True

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "caption" and self.caption_depth:
            self.caption_depth -= 1

    def handle_data(self, data: str) -> None:
        self.cell_text.append(data)
        if self.caption_depth:
            self.caption_text.append(data)

    def handle_decl(self, decl: str) -> None:
        self.reject("HTML declarations are not allowed in a static table fragment.")

    def handle_pi(self, data: str) -> None:
        self.reject("Processing instructions are not allowed in a static table fragment.")


class Audit:
    def __init__(self, asset_root: Path | None) -> None:
        self.issues: list[dict[str, str]] = []
        self.asset_root = asset_root.resolve() if asset_root is not None else None
        self.checked_assets = 0
        self.checked_datasets = 0

    def add(self, severity: str, code: str, path: str, message: str) -> None:
        self.issues.append(
            {
                "severity": severity,
                "code": code,
                "path": path,
                "message": message,
            }
        )

    def error(self, code: str, path: str, message: str) -> None:
        self.add("error", code, path, message)

    def warning(self, code: str, path: str, message: str) -> None:
        self.add("warning", code, path, message)

    def verify_file(
        self,
        relative_path: Any,
        expected_sha256: Any,
        pointer: str,
        expected_bytes: Any | None = None,
        minimum_bytes: int = 0,
        require_asset_root: bool = False,
    ) -> Path | None:
        if self.asset_root is None:
            if require_asset_root and valid_relative_path(relative_path):
                self.error(
                    "V098_LOCAL_FILE_UNINSPECTED",
                    pointer,
                    "This local evidence file requires --asset-root for release validation.",
                )
            return None
        if not valid_relative_path(relative_path):
            return None

        unresolved = self.asset_root / str(relative_path)
        if path_uses_symlink(self.asset_root, unresolved):
            self.error(
                "V014_PATH_SYMLINK",
                pointer,
                "Referenced file traverses a symlink and is not accepted as local evidence.",
            )
            return None
        try:
            candidate = unresolved.resolve()
        except (OSError, RuntimeError, ValueError):
            self.error("V008_PATH", pointer, "Referenced path cannot be resolved safely.")
            return None
        if candidate != self.asset_root and self.asset_root not in candidate.parents:
            self.error(
                "V011_PATH_ESCAPE",
                pointer,
                "Referenced file resolves outside --asset-root.",
            )
            return None
        if not candidate.is_file():
            self.error("V012_FILE_MISSING", pointer, "Referenced path is not a regular file.")
            return None

        try:
            digest = hashlib.sha256()
            with candidate.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            actual_sha256 = digest.hexdigest()
            actual_bytes = candidate.stat().st_size
        except PermissionError as exc:
            raise ValidatorUnavailable(f"Cannot read referenced file: {candidate}") from exc
        except OSError as exc:
            raise ValidatorUnavailable(f"Cannot inspect referenced file: {candidate}") from exc

        if valid_sha256(expected_sha256) and actual_sha256 != expected_sha256:
            self.error("V010_HASH_MISMATCH", pointer, "Referenced file SHA-256 does not match.")
        if is_int(expected_bytes) and actual_bytes != expected_bytes:
            self.error("V013_SIZE_MISMATCH", pointer, "Referenced file byte size does not match.")
        if actual_bytes < minimum_bytes:
            self.error("V099_EMPTY_FILE", pointer, "Referenced evidence file must not be empty.")
        return candidate

    def verify_evidence_file(
        self,
        relative_path: Any,
        expected_sha256: Any,
        pointer: str,
    ) -> Path | None:
        """Require a checksum-bound, non-empty, local regular evidence file."""

        return self.verify_file(
            relative_path,
            expected_sha256,
            pointer,
            minimum_bytes=1,
            require_asset_root=True,
        )


def is_int(value: Any) -> bool:
    return type(value) is int


def is_bool(value: Any) -> bool:
    return type(value) is bool


def nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def is_default_ignorable(character: str) -> bool:
    codepoint = ord(character)
    return any(start <= codepoint <= end for start, end in DEFAULT_IGNORABLE_RANGES)


def contains_forbidden_structured_character(value: Any) -> bool:
    """Reject characters that can hide, reorder, alias, or split JSON fields."""

    if isinstance(value, str):
        return any(
            unicodedata.category(character).startswith("C")
            or unicodedata.category(character) in {"Zl", "Zp"}
            or character in INVISIBLE_VISIBLE_CATEGORY_EXCEPTIONS
            or is_default_ignorable(character)
            for character in value
        )
    if isinstance(value, dict):
        return any(
            contains_forbidden_structured_character(key)
            or contains_forbidden_structured_character(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(contains_forbidden_structured_character(item) for item in value)
    return False


def semantic_text(value: Any, minimum_visible: int = 1) -> bool:
    """Return whether human-facing evidence contains a real letter or number.

    Punctuation, emoji, invisible format controls, combining-only strings, and
    Unicode blank glyphs cannot stand in for provenance, rights, accessibility,
    or editorial evidence. Technical identifiers, paths, MIME types, and units
    continue to use their purpose-specific validators instead.
    """

    if not isinstance(value, str):
        return False
    normalized = unicodedata.normalize("NFKC", value)
    if PLACEHOLDER.search(normalized):
        return False
    visible = [
        character
        for character in normalized
        if character not in INVISIBLE_VISIBLE_CATEGORY_EXCEPTIONS
        and unicodedata.category(character)[0] in VISIBLE_CATEGORY_PREFIXES
    ]
    return len(visible) >= minimum_visible and any(
        unicodedata.category(character)[0] in ALPHANUMERIC_CATEGORY_PREFIXES
        for character in visible
    )


def valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def valid_ascii_dns_label(label: str) -> bool:
    """Accept a conservative browser-stable DNS label and A-label subset."""

    if (
        not label
        or len(label) > 63
        or re.fullmatch(r"[A-Za-z0-9-]+", label) is None
        or label.startswith("-")
        or label.endswith("-")
    ):
        return False
    if not label.casefold().startswith("xn--"):
        return True
    if idna2008 is None:
        return False
    try:
        decoded = idna2008.decode(label, strict=True, uts46=True, std3_rules=True)
        round_trip = idna2008.encode(decoded, strict=True, uts46=True, std3_rules=True).decode("ascii")
    except (UnicodeError, ValueError):
        return False
    if round_trip.casefold() != label.casefold() or not any(ord(character) > 0x7F for character in decoded):
        return False
    if unicodedata.normalize("NFC", decoded) != decoded or unicodedata.category(decoded[0]).startswith("M"):
        return False
    return all(
        character == "-"
        or unicodedata.category(character)[0] in {"L", "M", "N"}
        and not is_default_ignorable(character)
        for character in decoded
    )


def valid_https_url(value: Any) -> bool:
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if "\\" in value or contains_forbidden_structured_character(value) or any(character.isspace() for character in value):
        return False
    try:
        parsed = urlparse(value)
        hostname = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError):
        return False
    if parsed.scheme != "https" or not parsed.netloc or not hostname or parsed.username is not None or parsed.password is not None or port == 0:
        return False
    raw_authority = parsed.netloc.rsplit("@", 1)[-1]
    if raw_authority.startswith("["):
        closing_bracket = raw_authority.find("]")
        raw_port = raw_authority[closing_bracket + 1 :] if closing_bracket >= 0 else ""
        if raw_port and (not raw_port.startswith(":") or re.fullmatch(r"[1-9][0-9]{0,4}", raw_port[1:]) is None):
            return False
    elif ":" in raw_authority:
        raw_port = raw_authority.rsplit(":", 1)[1]
        if re.fullmatch(r"[1-9][0-9]{0,4}", raw_port) is None or int(raw_port) > 65535:
            return False
    if re.search(r"%(?:2f|5c)", parsed.path, re.IGNORECASE) or re.search(r"%(?![0-9A-Fa-f]{2})", parsed.path):
        return False
    try:
        decoded_path = unquote(parsed.path, encoding="utf-8", errors="strict")
    except UnicodeDecodeError:
        return False
    if (
        "\\" in decoded_path
        or contains_forbidden_structured_character(decoded_path)
        or any(character.isspace() or unicodedata.category(character).startswith("C") for character in decoded_path)
        or any(segment in {".", ".."} for segment in decoded_path.split("/"))
    ):
        return False
    try:
        return ipaddress.ip_address(hostname.strip("[]")).version == 4
    except ValueError:
        pass
    # Require browser-stable ASCII/punycode hostnames instead of Python's
    # transitional IDNA2003 mapping, which can collapse distinct hosts.
    if not hostname.isascii():
        return False
    ascii_hostname = hostname.casefold()
    if ascii_hostname.endswith("."):
        return False
    if not ascii_hostname or len(ascii_hostname) > 253:
        return False
    labels = ascii_hostname.split(".")
    numeric_final = bool(labels) and re.fullmatch(r"(?:[0-9]+|0[xX][0-9A-Fa-f]+)", labels[-1]) is not None
    return (
        bool(labels)
        and not numeric_final
        and re.search(r"[A-Za-z]", labels[-1]) is not None
        and all(valid_ascii_dns_label(label) for label in labels)
    )


def valid_datetime(value: Any) -> bool:
    if not isinstance(value, str) or RFC3339_TIMESTAMP.fullmatch(value) is None:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def valid_relative_path(value: Any) -> bool:
    if (
        not nonempty(value)
        or "\\" in value
        or contains_forbidden_structured_character(value)
    ):
        return False
    try:
        path = PurePosixPath(value)
    except (TypeError, ValueError):
        return False
    return (
        not path.is_absolute()
        and ".." not in path.parts
        and "." != str(path)
        and value == path.as_posix()
        and unicodedata.normalize("NFC", value) == value
    )


def local_name(name: str) -> str:
    """Return the local component of an XML qualified name."""
    return name.rsplit("}", 1)[-1]


def static_svg_problem(payload: bytes) -> str | None:
    """Return a reason when an SVG contains active or external content."""
    if len(payload) > MAX_ACTIVE_CONTENT_BYTES:
        return "SVG exceeds the static-inspection size limit."
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return "SVG is not valid UTF-8."
    lowered = text.casefold()
    if "<!doctype" in lowered or "<!entity" in lowered or "<?" in lowered:
        return "SVG declarations, entities, and processing instructions are not allowed."
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        return "SVG is not well-formed XML."
    if local_name(root.tag) != "svg":
        return "SVG document root must be <svg>."
    for element in root.iter():
        tag = local_name(element.tag)
        if tag not in STATIC_SVG_TAGS:
            return f"SVG element <{tag}> is not in the static allowlist."
        for raw_name, raw_value in element.attrib.items():
            name = local_name(raw_name).casefold()
            value = raw_value.strip()
            lowered_value = value.casefold()
            if name.startswith("on") or name == "style":
                return f"SVG attribute {name!r} can execute or import active content."
            if name == "href" and not value.startswith("#"):
                return "SVG href values must be local fragment references."
            if any(token in lowered_value for token in ("javascript:", "vbscript:", "data:", "@import")):
                return f"SVG attribute {name!r} contains an active or external scheme."
            if "url(" in lowered_value and re.fullmatch(r"url\(#[A-Za-z_][A-Za-z0-9_.:-]*\)", value) is None:
                return f"SVG attribute {name!r} contains a non-local URL reference."
    return None


def static_html_problem(payload: bytes) -> str | None:
    """Return a reason when table HTML is not a static allowlisted fragment."""
    if len(payload) > MAX_ACTIVE_CONTENT_BYTES:
        return "HTML exceeds the static-inspection size limit."
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return "HTML is not valid UTF-8."
    parser = StaticHTMLValidator()
    try:
        parser.feed(text)
        parser.close()
    except Exception:
        return "HTML could not be parsed safely."
    return parser.problem


def accessible_table_problem(payload: bytes) -> str | None:
    """Return a reason when a static table lacks usable accessible content."""

    active_problem = static_html_problem(payload)
    if active_problem is not None:
        return active_problem
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return "Accessible table is not valid UTF-8."
    parser = StaticHTMLValidator()
    try:
        parser.feed(text)
        parser.close()
    except Exception:
        return "Accessible table could not be parsed safely."
    if not parser.seen_table:
        return "Accessible table file must contain a <table> element."
    if not parser.seen_header_cell or not parser.seen_data_cell:
        return "Accessible table needs at least one header cell and one data cell."
    if not parser.table_has_aria_label and not semantic_text(" ".join(parser.caption_text)):
        return "Accessible table needs a substantive <caption> or table aria-label."
    if not semantic_text(" ".join(parser.cell_text), minimum_visible=2):
        return "Accessible table contains no substantive cell content."
    return None


def substantive_text_file_problem(payload: bytes, kind: str) -> str | None:
    """Validate human-facing text while ignoring caption timing boilerplate."""

    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        return f"{kind} file is not valid UTF-8."
    candidate = text
    if kind == "captions":
        content_lines: list[str] = []
        skip_note = False
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if line.startswith(("NOTE", "STYLE", "REGION")):
                skip_note = True
                continue
            if skip_note:
                if not line:
                    skip_note = False
                continue
            if (
                not line
                or line == "WEBVTT"
                or line.isdigit()
                or "-->" in line
                or re.fullmatch(r"(?:Kind|Language):\s*.*", line, re.IGNORECASE)
            ):
                continue
            content_lines.append(line)
        candidate = " ".join(content_lines)
    if not semantic_text(candidate, minimum_visible=10):
        return f"{kind} file lacks substantive accessible content."
    return None


def verify_accessibility_file(
    audit: Audit,
    relative_path: Any,
    expected_sha256: Any,
    pointer: str,
    kind: str,
) -> None:
    """Verify and inspect accessibility payloads during release validation."""

    candidate = audit.verify_file(
        relative_path,
        expected_sha256,
        pointer,
        minimum_bytes=1,
    )
    if candidate is None:
        return
    try:
        payload = candidate.read_bytes()
    except OSError as exc:
        raise ValidatorUnavailable(f"Cannot read accessibility file: {candidate}") from exc
    problem = accessible_table_problem(payload) if kind == "data table" else substantive_text_file_problem(payload, kind)
    if problem is not None:
        audit.error("V100_ACCESSIBILITY_CONTENT", pointer, problem)


def signature_matches(mime_type: str, header: bytes) -> bool:
    """Check deterministic magic bytes for non-active media formats."""
    if mime_type == "image/png":
        return header.startswith(b"\x89PNG\r\n\x1a\n")
    if mime_type == "image/jpeg":
        return header.startswith(b"\xff\xd8\xff")
    if mime_type == "image/webp":
        return len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"WEBP"
    if mime_type == "image/gif":
        return header.startswith((b"GIF87a", b"GIF89a"))
    if mime_type == "image/avif":
        return len(header) >= 12 and header[4:8] == b"ftyp" and header[8:12] in {b"avif", b"avis"}
    if mime_type == "video/mp4":
        return len(header) >= 12 and header[4:8] == b"ftyp"
    if mime_type == "video/webm":
        return header.startswith(b"\x1aE\xdf\xa3")
    return False


def inspect_media_file(audit: Audit, candidate: Path, mime_type: str, pointer: str) -> None:
    """Inspect file content after path, size, and digest verification."""
    try:
        if mime_type in ACTIVE_MIME_TYPES:
            payload = candidate.read_bytes()
            problem = static_svg_problem(payload) if mime_type == "image/svg+xml" else static_html_problem(payload)
            if problem is not None:
                audit.error("V094_ACTIVE_CONTENT_REJECTED", pointer, problem)
            return
        with candidate.open("rb") as handle:
            header = handle.read(32)
    except OSError as exc:
        raise ValidatorUnavailable(f"Cannot inspect media content: {candidate}") from exc
    if not signature_matches(mime_type, header):
        audit.error("V095_MEDIA_SIGNATURE_INVALID", pointer, "File signature does not match the declared MIME type.")


def validate_media_file(
    audit: Audit,
    record: dict[str, Any],
    path: str,
    visual_type: Any,
) -> None:
    """Validate one output or variant path, MIME declaration, and file content."""
    relative_path = record.get("path")
    mime_type = record.get("mime_type")
    allowed = MIME_TYPES_BY_ASSET.get(visual_type, set())
    if isinstance(mime_type, str) and mime_type not in allowed:
        audit.error(
            "V092_MIME_NOT_ALLOWED",
            f"{path}/mime_type",
            "Declared MIME type is not allowed for this asset type.",
        )
    if isinstance(mime_type, str) and isinstance(relative_path, str) and mime_type in MIME_EXTENSIONS:
        if PurePosixPath(relative_path).suffix.casefold() not in MIME_EXTENSIONS[mime_type]:
            audit.error(
                "V093_EXTENSION_MISMATCH",
                f"{path}/path",
                "File extension does not match the declared MIME type.",
            )
    if mime_type in ACTIVE_MIME_TYPES and audit.asset_root is None:
        audit.error(
            "V096_ACTIVE_CONTENT_UNINSPECTED",
            f"{path}/path",
            "SVG and HTML outputs require --asset-root so active content can be inspected.",
        )
    candidate = audit.verify_file(
        relative_path,
        record.get("sha256"),
        f"{path}/path",
        record.get("bytes"),
    )
    if candidate is not None and isinstance(mime_type, str) and mime_type in allowed:
        inspect_media_file(audit, candidate, mime_type, f"{path}/path")


def check_keys(
    audit: Audit,
    obj: Any,
    path: str,
    required: Iterable[str],
    allowed: Iterable[str],
) -> bool:
    if not isinstance(obj, dict):
        audit.error("V003_TYPE", path, "Expected an object.")
        return False
    required_set = set(required)
    allowed_set = set(allowed)
    for key in sorted(required_set - set(obj)):
        audit.error("V001_REQUIRED", f"{path}/{key}", "Required field is missing.")
    for key in sorted(set(obj) - allowed_set):
        audit.error("V002_UNKNOWN_FIELD", f"{path}/{key}", "Field is not allowed by v0.1.")
    return True


def require_nonempty(audit: Audit, obj: dict[str, Any], key: str, path: str) -> None:
    if key in obj and not nonempty(obj[key]):
        audit.error("V004_VALUE", f"{path}/{key}", "Expected a non-empty string.")


def require_semantic_text(audit: Audit, obj: dict[str, Any], key: str, path: str) -> None:
    if key in obj and not semantic_text(obj[key]):
        audit.error(
            "V004_VALUE",
            f"{path}/{key}",
            "Expected human-readable text containing a Unicode letter or number.",
        )


def require_bool(audit: Audit, obj: dict[str, Any], key: str, path: str) -> None:
    if key in obj and not is_bool(obj[key]):
        audit.error("V003_TYPE", f"{path}/{key}", "Expected a boolean.")


def require_int(audit: Audit, obj: dict[str, Any], key: str, path: str, minimum: int = 0) -> None:
    if key in obj and (not is_int(obj[key]) or obj[key] < minimum):
        audit.error("V004_VALUE", f"{path}/{key}", f"Expected an integer >= {minimum}.")


def require_sha(audit: Audit, obj: dict[str, Any], key: str, path: str) -> None:
    if key in obj and not valid_sha256(obj[key]):
        audit.error("V005_SHA256", f"{path}/{key}", "Expected 64 lowercase hexadecimal characters.")


def require_url(audit: Audit, obj: dict[str, Any], key: str, path: str) -> None:
    if key in obj and not valid_https_url(obj[key]):
        audit.error("V006_URL", f"{path}/{key}", "Expected an HTTPS URL without embedded credentials.")


def require_datetime(audit: Audit, obj: dict[str, Any], key: str, path: str) -> None:
    if key in obj and not valid_datetime(obj[key]):
        audit.error("V007_DATETIME", f"{path}/{key}", "Expected an ISO 8601 timestamp with timezone.")
    elif key in obj:
        parsed = datetime.fromisoformat(obj[key].replace("Z", "+00:00"))
        if parsed > datetime.now(timezone.utc) + timedelta(minutes=5):
            audit.error("V015_FUTURE_TIMESTAMP", f"{path}/{key}", "Observed provenance timestamps cannot be materially future-dated.")


def require_path(audit: Audit, obj: dict[str, Any], key: str, path: str) -> None:
    if key in obj and not valid_relative_path(obj[key]):
        audit.error("V008_PATH", f"{path}/{key}", "Expected a safe relative POSIX path.")


def validate_license(
    audit: Audit,
    license_obj: Any,
    path: str,
    commercial_use: bool,
) -> None:
    required = {
        "status",
        "license_id",
        "commercial_use_allowed",
        "attribution_required",
        "attribution_text",
    }
    allowed = required | {"license_url", "evidence_path", "evidence_sha256"}
    if not check_keys(audit, license_obj, path, required, allowed):
        return

    require_nonempty(audit, license_obj, "license_id", path)
    require_url(audit, license_obj, "license_url", path)
    require_path(audit, license_obj, "evidence_path", path)
    require_sha(audit, license_obj, "evidence_sha256", path)
    if not valid_https_url(license_obj.get("license_url")) and not valid_relative_path(license_obj.get("evidence_path")):
        audit.error(
            "V023_LICENSE_EVIDENCE_MISSING",
            path,
            "Dataset rights need either an HTTPS license URL or a local evidence record.",
        )
    if valid_relative_path(license_obj.get("evidence_path")) and not valid_sha256(license_obj.get("evidence_sha256")):
        audit.error(
            "V005_SHA256",
            f"{path}/evidence_sha256",
            "Local dataset rights evidence must be checksum-bound.",
        )
    require_bool(audit, license_obj, "commercial_use_allowed", path)
    require_bool(audit, license_obj, "attribution_required", path)
    if "attribution_text" in license_obj and not isinstance(license_obj["attribution_text"], str):
        audit.error("V003_TYPE", f"{path}/attribution_text", "Expected a string.")
    elif isinstance(license_obj.get("attribution_text"), str) and license_obj["attribution_text"] != "" and not semantic_text(license_obj["attribution_text"]):
        audit.error("V004_VALUE", f"{path}/attribution_text", "Attribution text must contain a Unicode letter or number.")

    if license_obj.get("status") != "verified":
        audit.error("V020_RIGHTS_UNVERIFIED", f"{path}/status", "Dataset license must be verified.")
    if commercial_use and license_obj.get("commercial_use_allowed") is not True:
        audit.error("V021_COMMERCIAL_CONFLICT", path, "License does not allow this commercial use.")
    if license_obj.get("attribution_required") is True and not semantic_text(license_obj.get("attribution_text")):
        audit.error("V022_ATTRIBUTION_MISSING", f"{path}/attribution_text", "Required attribution is empty.")
    if valid_relative_path(license_obj.get("evidence_path")):
        audit.verify_evidence_file(
            license_obj.get("evidence_path"),
            license_obj.get("evidence_sha256"),
            f"{path}/evidence_path",
        )


def validate_dataset(
    audit: Audit,
    dataset: Any,
    index: int,
    commercial_use: bool,
) -> tuple[str | None, set[str], dict[str, TransformRecord], bool | None]:
    path = f"/datasets/{index}"
    required = {
        "dataset_id",
        "title",
        "publisher",
        "retrieved_at",
        "snapshot_path",
        "snapshot_sha256",
        "provenance_status",
        "synthetic",
        "methodology",
        "license",
        "fields",
        "transformations",
    }
    allowed = required | {"source_url", "source_path", "source_path_sha256", "time_range", "sample_size"}
    if not check_keys(audit, dataset, path, required, allowed):
        return None, set(), {}, None
    audit.checked_datasets += 1

    require_nonempty(audit, dataset, "dataset_id", path)
    for key in ("title", "publisher", "methodology"):
        require_semantic_text(audit, dataset, key, path)
    require_url(audit, dataset, "source_url", path)
    require_path(audit, dataset, "source_path", path)
    require_sha(audit, dataset, "source_path_sha256", path)
    if not valid_https_url(dataset.get("source_url")) and not valid_relative_path(dataset.get("source_path")):
        audit.error(
            "V018_SOURCE_ORIGIN_MISSING",
            path,
            "Dataset needs either an HTTPS origin URL or a local provenance record.",
        )
    if valid_relative_path(dataset.get("source_path")) and not valid_sha256(dataset.get("source_path_sha256")):
        audit.error(
            "V005_SHA256",
            f"{path}/source_path_sha256",
            "Local dataset provenance must be checksum-bound.",
        )
    require_datetime(audit, dataset, "retrieved_at", path)
    require_path(audit, dataset, "snapshot_path", path)
    require_sha(audit, dataset, "snapshot_sha256", path)
    require_bool(audit, dataset, "synthetic", path)
    if "sample_size" in dataset:
        require_int(audit, dataset, "sample_size", path, 0)

    if dataset.get("provenance_status") != "verified":
        audit.error(
            "V030_DATASET_PROVENANCE_UNVERIFIED",
            f"{path}/provenance_status",
            "Dataset provenance must be verified before factual use.",
        )
    validate_license(audit, dataset.get("license"), f"{path}/license", commercial_use)

    fields: set[str] = set()
    field_items = dataset.get("fields")
    if not isinstance(field_items, list) or not field_items:
        audit.error("V003_TYPE", f"{path}/fields", "Expected a non-empty array.")
    else:
        for field_index, field in enumerate(field_items):
            field_path = f"{path}/fields/{field_index}"
            field_required = {"name", "data_type", "description"}
            field_allowed = field_required | {"unit", "source_field"}
            if not check_keys(audit, field, field_path, field_required, field_allowed):
                continue
            require_nonempty(audit, field, "name", field_path)
            require_semantic_text(audit, field, "description", field_path)
            for optional_string in ("unit", "source_field"):
                if optional_string in field and not isinstance(field[optional_string], str):
                    audit.error("V003_TYPE", f"{field_path}/{optional_string}", "Expected a string.")
            if field.get("data_type") not in {
                "string",
                "integer",
                "number",
                "boolean",
                "date",
                "datetime",
            }:
                audit.error("V004_VALUE", f"{field_path}/data_type", "Unsupported field data type.")
            name = field.get("name")
            if nonempty(name):
                if name in fields:
                    audit.error("V031_DUPLICATE_FIELD", f"{field_path}/name", "Dataset field names must be unique.")
                fields.add(name)

    transforms: dict[str, TransformRecord] = {}
    transform_items = dataset.get("transformations")
    if not isinstance(transform_items, list):
        audit.error("V003_TYPE", f"{path}/transformations", "Expected an array.")
    else:
        previous_sha = dataset.get("snapshot_sha256")
        for transform_index, transform in enumerate(transform_items):
            transform_path = f"{path}/transformations/{transform_index}"
            transform_required = {
                "transform_id",
                "description",
                "spec_path",
                "spec_sha256",
                "input_sha256",
                "output_sha256",
            }
            if not check_keys(audit, transform, transform_path, transform_required, transform_required):
                continue
            require_nonempty(audit, transform, "transform_id", transform_path)
            require_semantic_text(audit, transform, "description", transform_path)
            require_path(audit, transform, "spec_path", transform_path)
            for key in ("spec_sha256", "input_sha256", "output_sha256"):
                require_sha(audit, transform, key, transform_path)
            transform_id = transform.get("transform_id")
            if nonempty(transform_id):
                if transform_id in transforms:
                    audit.error(
                        "V032_DUPLICATE_TRANSFORM",
                        f"{transform_path}/transform_id",
                        "Transformation IDs must be unique within a dataset.",
                    )
                transforms[transform_id] = {
                    "spec_path": transform.get("spec_path"),
                    "spec_sha256": transform.get("spec_sha256"),
                    "input_sha256": transform.get("input_sha256"),
                    "output_sha256": transform.get("output_sha256"),
                }
            if valid_sha256(previous_sha) and transform.get("input_sha256") != previous_sha:
                audit.error(
                    "V033_TRANSFORM_CHAIN",
                    f"{transform_path}/input_sha256",
                    "Transformation input must match the dataset snapshot or previous output.",
                )
            previous_sha = transform.get("output_sha256")
            audit.verify_file(
                transform.get("spec_path"),
                transform.get("spec_sha256"),
                f"{transform_path}/spec_path",
            )

    audit.verify_file(
        dataset.get("snapshot_path"),
        dataset.get("snapshot_sha256"),
        f"{path}/snapshot_path",
    )
    if valid_relative_path(dataset.get("source_path")):
        audit.verify_evidence_file(
            dataset.get("source_path"),
            dataset.get("source_path_sha256"),
            f"{path}/source_path",
        )
    return dataset.get("dataset_id"), fields, transforms, dataset.get("synthetic")


REVIEW_SCOPES = {"general_rights", "model_release", "property_release", "ai_input_rights"}


def validate_review_record(audit: Audit, review: Any, path: str) -> set[str]:
    """Validate a human approval as evidence, not a bare status token."""

    required = {"reviewer", "reviewed_at", "evidence", "scopes"}
    allowed = required | {"evidence_path", "evidence_sha256"}
    if not check_keys(audit, review, path, required, allowed):
        return set()
    require_semantic_text(audit, review, "reviewer", path)
    require_datetime(audit, review, "reviewed_at", path)
    require_semantic_text(audit, review, "evidence", path)
    if isinstance(review.get("evidence"), str) and NEGATIVE_REVIEW_EVIDENCE.search(
        unicodedata.normalize("NFKC", review["evidence"])
    ):
        audit.error(
            "V028_REVIEW_RECORD_INVALID",
            f"{path}/evidence",
            "Approved review evidence explicitly says the review or observation did not occur.",
        )
    require_path(audit, review, "evidence_path", path)
    require_sha(audit, review, "evidence_sha256", path)
    scopes_value = review.get("scopes")
    scopes: set[str] = set()
    if (
        not isinstance(scopes_value, list)
        or not scopes_value
        or any(item not in REVIEW_SCOPES for item in scopes_value)
        or len(scopes_value) != len(set(scopes_value))
    ):
        audit.error(
            "V028_REVIEW_RECORD_INVALID",
            f"{path}/scopes",
            "Review scopes must be a non-empty unique list of supported review gates.",
        )
    else:
        scopes = set(scopes_value)
    if valid_relative_path(review.get("evidence_path")):
        if not valid_sha256(review.get("evidence_sha256")):
            audit.error(
                "V005_SHA256",
                f"{path}/evidence_sha256",
                "Local review evidence must be checksum-bound.",
            )
        audit.verify_evidence_file(
            review.get("evidence_path"),
            review.get("evidence_sha256"),
            f"{path}/evidence_path",
        )
    return scopes


def validate_rights(
    audit: Audit,
    rights: Any,
    source: dict[str, Any],
    output: dict[str, Any],
    path: str,
    commercial_use: bool,
) -> None:
    asset_path = path.rsplit("/rights", 1)[0]
    required = {
        "status",
        "usage_basis",
        "license_id",
        "commercial_use_allowed",
        "modification_allowed",
        "attribution_required",
        "attribution_text",
        "editorial_only",
        "depicts_recognizable_people",
        "model_release_status",
        "depicts_protected_property",
        "property_release_status",
        "manual_review_status",
    }
    allowed = required | {
        "license_url",
        "license_evidence_path",
        "license_evidence_sha256",
        "receipt_or_asset_id",
        "manual_review",
    }
    if not check_keys(audit, rights, path, required, allowed):
        return

    for key in ("usage_basis", "license_id"):
        require_nonempty(audit, rights, key, path)
    if rights.get("usage_basis") not in USAGE_BASES:
        audit.error("V004_VALUE", f"{path}/usage_basis", "Unsupported rights usage basis.")
    require_url(audit, rights, "license_url", path)
    require_path(audit, rights, "license_evidence_path", path)
    require_sha(audit, rights, "license_evidence_sha256", path)
    if not valid_https_url(rights.get("license_url")) and not valid_relative_path(rights.get("license_evidence_path")):
        audit.error(
            "V023_LICENSE_EVIDENCE_MISSING",
            path,
            "Rights need either an HTTPS license URL or a local evidence record.",
        )
    if valid_relative_path(rights.get("license_evidence_path")) and not valid_sha256(rights.get("license_evidence_sha256")):
        audit.error(
            "V005_SHA256",
            f"{path}/license_evidence_sha256",
            "Local asset rights evidence must be checksum-bound.",
        )
    if rights.get("usage_basis") in {"licensed", "public_domain", "editorial_reviewed"} and not valid_https_url(rights.get("license_url")):
        audit.error(
            "V006_URL",
            f"{path}/license_url",
            "This usage basis requires an authoritative HTTPS license URL.",
        )
    for key in (
        "commercial_use_allowed",
        "modification_allowed",
        "attribution_required",
        "editorial_only",
        "depicts_recognizable_people",
        "depicts_protected_property",
    ):
        require_bool(audit, rights, key, path)
    if "attribution_text" in rights and not isinstance(rights["attribution_text"], str):
        audit.error("V003_TYPE", f"{path}/attribution_text", "Expected a string.")
    elif isinstance(rights.get("attribution_text"), str) and rights["attribution_text"] != "" and not semantic_text(rights["attribution_text"]):
        audit.error("V004_VALUE", f"{path}/attribution_text", "Attribution text must contain a Unicode letter or number.")
    review_scopes: set[str] = set()
    if "manual_review" in rights:
        review_scopes = validate_review_record(audit, rights.get("manual_review"), f"{path}/manual_review")
    if rights.get("manual_review_status") == "approved" and not review_scopes:
        audit.error(
            "V028_REVIEW_RECORD_INVALID",
            f"{path}/manual_review",
            "Approved manual review requires reviewer, reviewed_at, substantive evidence, and scope.",
        )

    if rights.get("status") != "verified":
        audit.error("V020_RIGHTS_UNVERIFIED", f"{path}/status", "Asset rights must be verified.")
    if commercial_use and rights.get("commercial_use_allowed") is not True:
        audit.error("V021_COMMERCIAL_CONFLICT", path, "Rights do not allow this commercial use.")
    if commercial_use and rights.get("editorial_only") is True:
        audit.error("V024_EDITORIAL_ONLY", f"{path}/editorial_only", "Editorial-only media is blocked here.")
    if output.get("transformed") is True and rights.get("modification_allowed") is not True:
        audit.error("V025_MODIFICATION_FORBIDDEN", path, "The output is transformed but modification is forbidden.")
    if rights.get("attribution_required") is True and not semantic_text(rights.get("attribution_text")):
        audit.error("V022_ATTRIBUTION_MISSING", f"{path}/attribution_text", "Required attribution is empty.")
    if source.get("kind") == "licensed_stock":
        if not nonempty(rights.get("receipt_or_asset_id")):
            audit.error("V023_LICENSE_EVIDENCE_MISSING", f"{path}/receipt_or_asset_id", "Paid stock needs an asset or receipt ID.")
        if not valid_relative_path(rights.get("license_evidence_path")):
            audit.error("V023_LICENSE_EVIDENCE_MISSING", f"{path}/license_evidence_path", "Paid stock needs local license evidence.")
    if source.get("kind") in {"licensed_stock", "open_license"} and not valid_https_url(source.get("asset_page_url")):
        audit.error(
            "V019_ASSET_PAGE_MISSING",
            f"{asset_path}/source/asset_page_url",
            "Stock/open media needs its asset landing page.",
        )

    people_risk = rights.get("depicts_recognizable_people") is True
    people_clear = (
        rights.get("model_release_status") == "verified"
        or rights.get("manual_review_status") == "approved"
    ) and "model_release" in review_scopes
    if people_risk and not people_clear:
        audit.error("V026_MODEL_RELEASE_REVIEW", path, "Recognizable people require a verified release or approved review.")
    property_risk = rights.get("depicts_protected_property") is True
    property_clear = (
        rights.get("property_release_status") == "verified"
        or rights.get("manual_review_status") == "approved"
    ) and "property_release" in review_scopes
    if property_risk and not property_clear:
        audit.error("V027_PROPERTY_RELEASE_REVIEW", path, "Protected property requires a verified release or approved review.")

    if valid_relative_path(rights.get("license_evidence_path")):
        audit.verify_evidence_file(
            rights.get("license_evidence_path"),
            rights.get("license_evidence_sha256"),
            f"{path}/license_evidence_path",
        )


def validate_source(audit: Audit, source: Any, path: str) -> dict[str, Any]:
    required = {"kind", "retrieved_at", "creator"}
    allowed = required | {"source_url", "source_path", "source_path_sha256", "asset_page_url"}
    if not check_keys(audit, source, path, required, allowed):
        return {}
    if source.get("kind") not in SOURCE_KINDS:
        audit.error("V004_VALUE", f"{path}/kind", "Unsupported source kind.")
    require_url(audit, source, "source_url", path)
    require_path(audit, source, "source_path", path)
    require_sha(audit, source, "source_path_sha256", path)
    if not valid_https_url(source.get("source_url")) and not valid_relative_path(source.get("source_path")):
        audit.error(
            "V018_SOURCE_ORIGIN_MISSING",
            path,
            "Source needs either an HTTPS origin URL or a local provenance record.",
        )
    if valid_relative_path(source.get("source_path")) and not valid_sha256(source.get("source_path_sha256")):
        audit.error(
            "V005_SHA256",
            f"{path}/source_path_sha256",
            "Local asset provenance must be checksum-bound.",
        )
    require_url(audit, source, "asset_page_url", path)
    require_datetime(audit, source, "retrieved_at", path)
    require_semantic_text(audit, source, "creator", path)
    if valid_relative_path(source.get("source_path")):
        audit.verify_evidence_file(
            source.get("source_path"),
            source.get("source_path_sha256"),
            f"{path}/source_path",
        )
    return source


def validate_output(audit: Audit, output: Any, path: str, visual_type: Any) -> dict[str, Any]:
    required = {"path", "sha256", "mime_type", "bytes", "transformed", "variants"}
    allowed = required | {"width", "height"}
    if not check_keys(audit, output, path, required, allowed):
        return {}
    require_path(audit, output, "path", path)
    require_sha(audit, output, "sha256", path)
    require_nonempty(audit, output, "mime_type", path)
    require_int(audit, output, "bytes", path, 1)
    require_bool(audit, output, "transformed", path)
    if visual_type in {"hero", "screenshot", "diagram", "chart", "video"}:
        if "width" not in output:
            audit.error("V001_REQUIRED", f"{path}/width", "Visual output needs intrinsic width.")
        if "height" not in output:
            audit.error("V001_REQUIRED", f"{path}/height", "Visual output needs intrinsic height.")
    require_int(audit, output, "width", path, 1)
    require_int(audit, output, "height", path, 1)

    variants = output.get("variants")
    seen_paths: set[str] = set()
    main_output_path = output.get("path")
    if nonempty(main_output_path):
        seen_paths.add(main_output_path)
    if not isinstance(variants, list):
        audit.error("V003_TYPE", f"{path}/variants", "Expected an array.")
    else:
        for index, variant in enumerate(variants):
            variant_path = f"{path}/variants/{index}"
            keys = {"path", "sha256", "mime_type", "width", "height", "bytes"}
            if not check_keys(audit, variant, variant_path, keys, keys):
                continue
            require_path(audit, variant, "path", variant_path)
            require_sha(audit, variant, "sha256", variant_path)
            require_nonempty(audit, variant, "mime_type", variant_path)
            require_int(audit, variant, "width", variant_path, 1)
            require_int(audit, variant, "height", variant_path, 1)
            require_int(audit, variant, "bytes", variant_path, 1)
            variant_name = variant.get("path")
            if nonempty(variant_name):
                if variant_name in seen_paths:
                    audit.error("V014_DUPLICATE_VARIANT", f"{variant_path}/path", "Main and variant output paths must be unique.")
                seen_paths.add(variant_name)
            validate_media_file(audit, variant, variant_path, visual_type)

    validate_media_file(audit, output, path, visual_type)
    return output


def validate_accessibility(
    audit: Audit,
    accessibility: Any,
    path: str,
    visual_type: Any,
    evidence_use: Any,
    output: dict[str, Any],
) -> None:
    required = {"decorative", "alt"}
    allowed = required | {
        "long_description_path",
        "long_description_sha256",
        "data_table_path",
        "data_table_sha256",
        "color_not_sole_cue",
        "contrast_review_status",
    }
    if not check_keys(audit, accessibility, path, required, allowed):
        return
    require_bool(audit, accessibility, "decorative", path)
    if "alt" in accessibility and not isinstance(accessibility["alt"], str):
        audit.error("V003_TYPE", f"{path}/alt", "Expected a string.")
    require_path(audit, accessibility, "long_description_path", path)
    require_sha(audit, accessibility, "long_description_sha256", path)
    require_path(audit, accessibility, "data_table_path", path)
    require_sha(audit, accessibility, "data_table_sha256", path)
    if valid_relative_path(accessibility.get("long_description_path")) and not valid_sha256(accessibility.get("long_description_sha256")):
        audit.error(
            "V005_SHA256",
            f"{path}/long_description_sha256",
            "Long-description content must be checksum-bound.",
        )
    if valid_relative_path(accessibility.get("data_table_path")) and not valid_sha256(accessibility.get("data_table_sha256")):
        audit.error(
            "V005_SHA256",
            f"{path}/data_table_sha256",
            "Accessible chart table must be checksum-bound.",
        )

    decorative = accessibility.get("decorative")
    alt = accessibility.get("alt")
    if decorative is True:
        if alt != "":
            audit.error("V040_DECORATIVE_ALT", f"{path}/alt", "Decorative media must use an empty alt string.")
        if evidence_use is not False:
            audit.error("V041_DECORATIVE_EVIDENCE", path, "Decorative media cannot be factual evidence.")
    elif decorative is False and not semantic_text(alt):
        audit.error("V042_ALT_MISSING", f"{path}/alt", "Informative media needs non-empty contextual alt text.")

    if semantic_text(alt) and nonempty(output.get("path")):
        filename = PurePosixPath(output["path"]).stem.replace("-", " ").replace("_", " ").lower()
        if alt.strip().lower() == filename:
            audit.warning("V043_ALT_FILENAME", f"{path}/alt", "Alt text only repeats the filename.")

    if visual_type in {"chart", "diagram"}:
        if not valid_relative_path(accessibility.get("long_description_path")):
            audit.error("V044_LONG_DESCRIPTION_MISSING", path, "Charts and diagrams need a long description.")
        if accessibility.get("color_not_sole_cue") is not True:
            audit.error("V045_COLOR_ONLY", path, "Do not encode essential distinctions by color alone.")
        if accessibility.get("contrast_review_status") != "approved":
            audit.error("V046_CONTRAST_UNREVIEWED", path, "Complex visuals need an approved contrast review.")
    if visual_type == "chart" and not valid_relative_path(accessibility.get("data_table_path")):
        audit.error("V047_DATA_TABLE_MISSING", path, "Charts need an accessible HTML data table.")

    verify_accessibility_file(
        audit,
        accessibility.get("long_description_path"),
        accessibility.get("long_description_sha256"),
        f"{path}/long_description_path",
        "long description",
    )
    verify_accessibility_file(
        audit,
        accessibility.get("data_table_path"),
        accessibility.get("data_table_sha256"),
        f"{path}/data_table_path",
        "data table",
    )


def validate_performance(
    audit: Audit,
    performance: Any,
    path: str,
    visual_type: Any,
    output: dict[str, Any],
    policy: dict[str, Any],
) -> bool:
    asset_path = path.rsplit("/performance", 1)[0]
    keys = {"above_fold", "lcp_candidate", "loading", "fetchpriority", "responsive"}
    if not check_keys(audit, performance, path, keys, keys):
        return False
    for key in ("above_fold", "lcp_candidate", "responsive"):
        require_bool(audit, performance, key, path)
    if performance.get("loading") not in {"eager", "lazy", "auto"}:
        audit.error("V004_VALUE", f"{path}/loading", "Unsupported loading mode.")
    if performance.get("fetchpriority") not in {"high", "low", "auto"}:
        audit.error("V004_VALUE", f"{path}/fetchpriority", "Unsupported fetch priority.")

    lcp = performance.get("lcp_candidate") is True
    if lcp:
        if performance.get("above_fold") is not True:
            audit.error("V050_LCP_NOT_ABOVE_FOLD", path, "An LCP candidate must be above the fold.")
        if performance.get("loading") == "lazy":
            audit.error("V051_LCP_LAZY", f"{path}/loading", "Do not lazy-load the LCP candidate.")
        if performance.get("fetchpriority") != "high":
            audit.error("V052_LCP_PRIORITY", f"{path}/fetchpriority", "The declared LCP candidate must use high fetch priority.")
    if visual_type == "hero" and performance.get("responsive") is not True:
        audit.error("V053_HERO_NOT_RESPONSIVE", f"{path}/responsive", "Hero output must declare responsive variants.")

    budgets = policy.get("performance_budgets", {}) if isinstance(policy, dict) else {}
    budget_key = "video_max_bytes" if visual_type == "video" else "hero_max_bytes" if visual_type == "hero" else "inline_max_bytes"
    budget = budgets.get(budget_key) if isinstance(budgets, dict) else None
    if is_int(budget) and is_int(output.get("bytes")) and output["bytes"] > budget:
        audit.error("V054_BYTE_BUDGET", f"{asset_path}/output/bytes", f"Output exceeds {budget_key}.")
    return lcp


def validate_screenshot(audit: Audit, screenshot: Any, path: str) -> None:
    keys = {
        "captured_at",
        "viewport_width",
        "viewport_height",
        "locale",
        "authenticated",
        "pii_review_status",
        "redactions",
        "original_path",
        "original_sha256",
    }
    if not check_keys(audit, screenshot, path, keys, keys):
        return
    require_datetime(audit, screenshot, "captured_at", path)
    require_int(audit, screenshot, "viewport_width", path, 1)
    require_int(audit, screenshot, "viewport_height", path, 1)
    require_nonempty(audit, screenshot, "locale", path)
    require_bool(audit, screenshot, "authenticated", path)
    require_path(audit, screenshot, "original_path", path)
    require_sha(audit, screenshot, "original_sha256", path)
    if screenshot.get("pii_review_status") != "approved":
        audit.error("V060_PII_REVIEW", f"{path}/pii_review_status", "Screenshot PII/secret review must be approved.")
    redactions = screenshot.get("redactions")
    if not isinstance(redactions, list) or any(not semantic_text(item) for item in redactions):
        audit.error("V003_TYPE", f"{path}/redactions", "Expected an array of redaction notes containing letters or numbers.")
    audit.verify_file(
        screenshot.get("original_path"),
        screenshot.get("original_sha256"),
        f"{path}/original_path",
    )


def validate_ai_input(audit: Audit, record: Any, path: str, commercial_use: bool) -> str | None:
    """Validate one AI reference/input asset and its own rights trail."""

    required = {
        "input_id",
        "kind",
        "creator",
        "retrieved_at",
        "sha256",
        "rights_status",
        "usage_basis",
        "commercial_use_allowed",
        "modification_allowed",
    }
    allowed = required | {
        "source_url",
        "source_path",
        "rights_evidence_url",
        "rights_evidence_path",
        "rights_evidence_sha256",
    }
    if not check_keys(audit, record, path, required, allowed):
        return None
    require_nonempty(audit, record, "input_id", path)
    if record.get("kind") not in {"reference_image", "source_asset", "mask", "control_image"}:
        audit.error("V004_VALUE", f"{path}/kind", "Unsupported AI input asset kind.")
    require_semantic_text(audit, record, "creator", path)
    require_datetime(audit, record, "retrieved_at", path)
    require_sha(audit, record, "sha256", path)
    require_url(audit, record, "source_url", path)
    require_path(audit, record, "source_path", path)
    if not valid_https_url(record.get("source_url")) and not valid_relative_path(record.get("source_path")):
        audit.error("V018_SOURCE_ORIGIN_MISSING", path, "AI input needs an HTTPS origin or a local source file.")
    require_url(audit, record, "rights_evidence_url", path)
    require_path(audit, record, "rights_evidence_path", path)
    require_sha(audit, record, "rights_evidence_sha256", path)
    if not valid_https_url(record.get("rights_evidence_url")) and not valid_relative_path(record.get("rights_evidence_path")):
        audit.error("V023_LICENSE_EVIDENCE_MISSING", path, "AI input needs its own rights evidence.")
    if record.get("rights_status") != "verified":
        audit.error("V062_AI_INPUT_RIGHTS", f"{path}/rights_status", "AI input rights must be verified.")
    if record.get("usage_basis") not in USAGE_BASES:
        audit.error("V004_VALUE", f"{path}/usage_basis", "Unsupported AI input usage basis.")
    require_bool(audit, record, "commercial_use_allowed", path)
    require_bool(audit, record, "modification_allowed", path)
    if record.get("modification_allowed") is not True or (commercial_use and record.get("commercial_use_allowed") is not True):
        audit.error("V062_AI_INPUT_RIGHTS", path, "AI input rights must allow this generated derivative and the declared use.")
    if valid_relative_path(record.get("source_path")):
        audit.verify_file(
            record.get("source_path"),
            record.get("sha256"),
            f"{path}/source_path",
            minimum_bytes=1,
            require_asset_root=True,
        )
    if valid_relative_path(record.get("rights_evidence_path")):
        if not valid_sha256(record.get("rights_evidence_sha256")):
            audit.error(
                "V005_SHA256",
                f"{path}/rights_evidence_sha256",
                "Local AI-input rights evidence must be checksum-bound.",
            )
        audit.verify_evidence_file(
            record.get("rights_evidence_path"),
            record.get("rights_evidence_sha256"),
            f"{path}/rights_evidence_path",
        )
    return record.get("input_id") if nonempty(record.get("input_id")) else None


def validate_ai(audit: Audit, ai: Any, path: str, evidence_use: Any, commercial_use: bool) -> None:
    required = {
        "generated",
        "provider",
        "model",
        "generated_at",
        "prompt_sha256",
        "input_assets",
        "provenance_metadata_retained",
    }
    allowed = required | {"disclosure"}
    if not check_keys(audit, ai, path, required, allowed):
        return
    if ai.get("generated") is not True:
        audit.error("V004_VALUE", f"{path}/generated", "AI provenance must declare generated=true.")
    require_semantic_text(audit, ai, "provider", path)
    require_semantic_text(audit, ai, "model", path)
    require_datetime(audit, ai, "generated_at", path)
    require_sha(audit, ai, "prompt_sha256", path)
    require_bool(audit, ai, "provenance_metadata_retained", path)
    input_assets = ai.get("input_assets")
    if not isinstance(input_assets, list):
        audit.error("V003_TYPE", f"{path}/input_assets", "Expected an array; use [] when generation had no reference assets.")
    else:
        seen_input_ids: set[str] = set()
        for index, record in enumerate(input_assets):
            input_id = validate_ai_input(audit, record, f"{path}/input_assets/{index}", commercial_use)
            if input_id is not None:
                if input_id in seen_input_ids:
                    audit.error("V062_AI_INPUT_RIGHTS", f"{path}/input_assets/{index}/input_id", "AI input IDs must be unique.")
                seen_input_ids.add(input_id)
    if ai.get("provenance_metadata_retained") is not True:
        audit.error("V063_AI_PROVENANCE_STRIPPED", path, "Retain available AI provenance metadata.")
    if not semantic_text(ai.get("disclosure")):
        audit.error("V064_AI_DISCLOSURE", f"{path}/disclosure", "Published generated media needs a disclosure record.")
    if evidence_use is not False:
        audit.error("V061_AI_AS_EVIDENCE", path, "AI-generated media cannot be factual evidence.")


def validate_chart(
    audit: Audit,
    chart: Any,
    path: str,
    evidence_use: Any,
    datasets: dict[str, DatasetRecord],
) -> None:
    keys = {
        "dataset_id",
        "field_names",
        "transform_id",
        "transform_output_sha256",
        "spec_path",
        "spec_sha256",
        "units",
        "synthetic",
        "disclosure",
    }
    if not check_keys(audit, chart, path, keys, keys):
        return
    require_nonempty(audit, chart, "dataset_id", path)
    require_nonempty(audit, chart, "transform_id", path)
    require_sha(audit, chart, "transform_output_sha256", path)
    require_path(audit, chart, "spec_path", path)
    require_sha(audit, chart, "spec_sha256", path)
    require_nonempty(audit, chart, "units", path)
    require_bool(audit, chart, "synthetic", path)

    fields = chart.get("field_names")
    if not isinstance(fields, list) or not fields or any(not nonempty(item) for item in fields):
        audit.error("V003_TYPE", f"{path}/field_names", "Expected a non-empty array of field names.")
        fields = []
    elif len(fields) != len(set(fields)):
        audit.error("V034_DUPLICATE_CHART_FIELD", f"{path}/field_names", "Chart field names must be unique.")

    dataset_id = chart.get("dataset_id")
    if dataset_id not in datasets:
        audit.error("V035_DATASET_MISSING", f"{path}/dataset_id", "Chart dataset_id does not resolve.")
    else:
        dataset_fields, transforms, dataset_synthetic = datasets[dataset_id]
        for field in sorted(set(fields) - dataset_fields):
            audit.error("V036_FIELD_MISSING", f"{path}/field_names", f"Dataset has no field named {field!r}.")
        transform_id = chart.get("transform_id")
        if nonempty(transform_id) and transform_id not in transforms:
            audit.error("V037_TRANSFORM_MISSING", f"{path}/transform_id", "Chart transform_id does not resolve.")
        elif nonempty(transform_id):
            transform = transforms[transform_id]
            if chart.get("spec_path") != transform.get("spec_path") or chart.get("spec_sha256") != transform.get("spec_sha256"):
                audit.error(
                    "V090_TRANSFORM_LINK_MISMATCH",
                    path,
                    "Chart spec path and SHA-256 must match the selected dataset transformation.",
                )
            if chart.get("transform_output_sha256") != transform.get("output_sha256"):
                audit.error(
                    "V091_TRANSFORM_OUTPUT_MISMATCH",
                    f"{path}/transform_output_sha256",
                    "Chart must identify the exact selected transformation output.",
                )
        if is_bool(chart.get("synthetic")) and is_bool(dataset_synthetic) and chart["synthetic"] != dataset_synthetic:
            audit.error("V038_SYNTHETIC_MISMATCH", f"{path}/synthetic", "Chart and dataset synthetic flags disagree.")

    disclosure = chart.get("disclosure")
    if not isinstance(disclosure, str):
        audit.error("V003_TYPE", f"{path}/disclosure", "Expected a string.")
    elif disclosure != "" and not semantic_text(disclosure):
        audit.error("V004_VALUE", f"{path}/disclosure", "Chart disclosure must contain a Unicode letter or number.")
    if chart.get("synthetic") is True:
        if evidence_use is not False:
            audit.error("V039_SYNTHETIC_EVIDENCE", path, "Synthetic data cannot be factual evidence.")
        if not semantic_text(disclosure):
            audit.error("V040_SYNTHETIC_UNLABELED", f"{path}/disclosure", "Synthetic charts need a visible disclosure.")

    audit.verify_file(
        chart.get("spec_path"),
        chart.get("spec_sha256"),
        f"{path}/spec_path",
    )


def validate_video(audit: Audit, video: Any, path: str) -> None:
    required = {"meaningful_audio", "poster_path"}
    allowed = required | {
        "captions_path",
        "captions_sha256",
        "transcript_path",
        "transcript_sha256",
        "visual_description_path",
        "visual_description_sha256",
    }
    if not check_keys(audit, video, path, required, allowed):
        return
    require_bool(audit, video, "meaningful_audio", path)
    for key in ("poster_path", "captions_path", "transcript_path", "visual_description_path"):
        require_path(audit, video, key, path)
    for key in ("captions_sha256", "transcript_sha256", "visual_description_sha256"):
        require_sha(audit, video, key, path)
    if video.get("meaningful_audio") is True:
        if not valid_relative_path(video.get("captions_path")):
            audit.error("V048_CAPTIONS_MISSING", path, "Video with meaningful audio needs captions.")
        elif not valid_sha256(video.get("captions_sha256")):
            audit.error("V005_SHA256", f"{path}/captions_sha256", "Captions must be checksum-bound.")
        if not valid_relative_path(video.get("transcript_path")):
            audit.error("V049_TRANSCRIPT_MISSING", path, "Video with meaningful audio needs a transcript.")
        elif not valid_sha256(video.get("transcript_sha256")):
            audit.error("V005_SHA256", f"{path}/transcript_sha256", "Transcript must be checksum-bound.")
    if valid_relative_path(video.get("visual_description_path")) and not valid_sha256(video.get("visual_description_sha256")):
        audit.error("V005_SHA256", f"{path}/visual_description_sha256", "Visual description must be checksum-bound.")
    audit.verify_file(video.get("poster_path"), None, f"{path}/poster_path")
    verify_accessibility_file(
        audit,
        video.get("captions_path"),
        video.get("captions_sha256"),
        f"{path}/captions_path",
        "captions",
    )
    verify_accessibility_file(
        audit,
        video.get("transcript_path"),
        video.get("transcript_sha256"),
        f"{path}/transcript_path",
        "transcript",
    )
    verify_accessibility_file(
        audit,
        video.get("visual_description_path"),
        video.get("visual_description_sha256"),
        f"{path}/visual_description_path",
        "visual description",
    )


def validate_asset(
    audit: Audit,
    asset: Any,
    index: int,
    commercial_use: bool,
    policy: dict[str, Any],
    datasets: dict[str, DatasetRecord],
) -> tuple[str | None, bool]:
    path = f"/assets/{index}"
    required = {
        "asset_id",
        "type",
        "purpose",
        "claim_ids",
        "evidence_use",
        "source",
        "rights",
        "accessibility",
        "performance",
        "output",
    }
    allowed = required | {"screenshot", "ai", "chart_data", "video"}
    if not check_keys(audit, asset, path, required, allowed):
        return None, False
    audit.checked_assets += 1

    require_nonempty(audit, asset, "asset_id", path)
    require_semantic_text(audit, asset, "purpose", path)
    visual_type = asset.get("type")
    if visual_type not in ASSET_TYPES:
        audit.error("V004_VALUE", f"{path}/type", "Unsupported visual type.")
    require_bool(audit, asset, "evidence_use", path)
    claim_ids = asset.get("claim_ids")
    if not isinstance(claim_ids, list) or any(not nonempty(item) for item in claim_ids):
        audit.error("V003_TYPE", f"{path}/claim_ids", "Expected an array of non-empty claim IDs.")
    elif len(claim_ids) != len(set(claim_ids)):
        audit.error("V065_DUPLICATE_CLAIM", f"{path}/claim_ids", "Claim IDs must be unique.")
    if asset.get("evidence_use") is True and not claim_ids:
        audit.error("V066_EVIDENCE_CLAIM_MISSING", f"{path}/claim_ids", "Evidence media must map to at least one claim.")

    source = validate_source(audit, asset.get("source"), f"{path}/source")
    output = validate_output(audit, asset.get("output"), f"{path}/output", visual_type)
    validate_rights(audit, asset.get("rights"), source, output, f"{path}/rights", commercial_use)
    validate_accessibility(
        audit,
        asset.get("accessibility"),
        f"{path}/accessibility",
        visual_type,
        asset.get("evidence_use"),
        output,
    )
    lcp = validate_performance(
        audit,
        asset.get("performance"),
        f"{path}/performance",
        visual_type,
        output,
        policy,
    )

    if visual_type == "screenshot":
        if source.get("kind") != "screenshot":
            audit.error("V067_SCREENSHOT_SOURCE", f"{path}/source/kind", "Screenshots must declare screenshot provenance.")
        if "screenshot" not in asset:
            audit.error("V001_REQUIRED", f"{path}/screenshot", "Screenshot capture metadata is required.")
        else:
            validate_screenshot(audit, asset["screenshot"], f"{path}/screenshot")
    elif "screenshot" in asset:
        audit.error("V068_UNEXPECTED_SCREENSHOT", f"{path}/screenshot", "Screenshot metadata is only valid for screenshots.")

    if source.get("kind") == "ai_generated":
        if "ai" not in asset:
            audit.error("V001_REQUIRED", f"{path}/ai", "AI provenance metadata is required.")
        else:
            validate_ai(audit, asset["ai"], f"{path}/ai", asset.get("evidence_use"), commercial_use)
    elif "ai" in asset:
        audit.error("V069_UNEXPECTED_AI", f"{path}/ai", "AI metadata requires source.kind=ai_generated.")

    if visual_type == "chart":
        if source.get("kind") != "derived_from_dataset":
            audit.error("V070_CHART_SOURCE", f"{path}/source/kind", "Charts must declare dataset-derived provenance.")
        if "chart_data" not in asset:
            audit.error("V001_REQUIRED", f"{path}/chart_data", "Chart data linkage is required.")
        else:
            validate_chart(
                audit,
                asset["chart_data"],
                f"{path}/chart_data",
                asset.get("evidence_use"),
                datasets,
            )
    elif "chart_data" in asset:
        audit.error("V071_UNEXPECTED_CHART", f"{path}/chart_data", "Chart data is only valid for charts.")

    if visual_type == "video":
        if "video" not in asset:
            audit.error("V001_REQUIRED", f"{path}/video", "Video accessibility metadata is required.")
        else:
            validate_video(audit, asset["video"], f"{path}/video")
    elif "video" in asset:
        audit.error("V072_UNEXPECTED_VIDEO", f"{path}/video", "Video metadata is only valid for video assets.")

    return asset.get("asset_id"), lcp


def validate_policy(audit: Audit, policy: Any) -> dict[str, Any]:
    path = "/policy"
    keys = {"visuals_optional", "discover_mode", "performance_budgets"}
    if not check_keys(audit, policy, path, keys, keys):
        return {}
    if policy.get("visuals_optional") is not True:
        audit.error("V080_VISUAL_QUOTA", f"{path}/visuals_optional", "Visuals must remain optional; quotas are not allowed.")
    require_bool(audit, policy, "discover_mode", path)
    budgets = policy.get("performance_budgets")
    allowed_budgets = {"hero_max_bytes", "inline_max_bytes", "video_max_bytes"}
    if not check_keys(audit, budgets, f"{path}/performance_budgets", set(), allowed_budgets):
        return policy
    for key in allowed_budgets:
        require_int(audit, budgets, key, f"{path}/performance_budgets", 1)
    return policy


def validate_manifest(manifest: Any, audit: Audit) -> None:
    top_required = {"schema_version", "run_id", "commercial_use", "policy", "datasets", "assets"}
    if not check_keys(audit, manifest, "", top_required, top_required):
        return
    if manifest.get("schema_version") != VERSION:
        audit.error("V081_SCHEMA_VERSION", "/schema_version", f"Expected schema_version {VERSION!r}.")
    if contains_forbidden_structured_character(manifest):
        audit.error(
            "V099_FORBIDDEN_STRUCTURED_CHARACTER",
            "",
            "Manifest strings cannot contain line, invisible, bidi, surrogate, or other forbidden structured-text characters.",
        )
    require_nonempty(audit, manifest, "run_id", "")
    require_bool(audit, manifest, "commercial_use", "")
    commercial_use = manifest.get("commercial_use") is True
    policy = validate_policy(audit, manifest.get("policy"))

    dataset_index: dict[str, DatasetRecord] = {}
    datasets = manifest.get("datasets")
    if not isinstance(datasets, list):
        audit.error("V003_TYPE", "/datasets", "Expected an array; an empty array is valid.")
    else:
        for index, dataset in enumerate(datasets):
            dataset_id, fields, transforms, synthetic = validate_dataset(audit, dataset, index, commercial_use)
            if nonempty(dataset_id):
                if dataset_id in dataset_index:
                    audit.error("V082_DUPLICATE_DATASET", f"/datasets/{index}/dataset_id", "Dataset IDs must be unique.")
                dataset_index[dataset_id] = (fields, transforms, synthetic)

    assets = manifest.get("assets")
    if not isinstance(assets, list):
        audit.error("V003_TYPE", "/assets", "Expected an array; an empty array is valid.")
        return

    asset_ids: set[str] = set()
    output_path_owners: dict[str, str] = {}
    normalized_output_path_owners: dict[str, str] = {}
    output_file_owners: dict[tuple[int, int], str] = {}
    lcp_count = 0
    hero_indices: list[int] = []
    for index, asset in enumerate(assets):
        asset_id, lcp = validate_asset(audit, asset, index, commercial_use, policy, dataset_index)
        if nonempty(asset_id):
            if asset_id in asset_ids:
                audit.error("V083_DUPLICATE_ASSET", f"/assets/{index}/asset_id", "Asset IDs must be unique.")
            asset_ids.add(asset_id)
        if lcp:
            lcp_count += 1
        if isinstance(asset, dict) and asset.get("type") == "hero":
            hero_indices.append(index)
        output = asset.get("output") if isinstance(asset, dict) else None
        output_records: list[tuple[str, Any]] = []
        if isinstance(output, dict):
            output_records.append((f"/assets/{index}/output/path", output.get("path")))
            variants = output.get("variants")
            if isinstance(variants, list):
                output_records.extend(
                    (f"/assets/{index}/output/variants/{variant_index}/path", variant.get("path"))
                    for variant_index, variant in enumerate(variants)
                    if isinstance(variant, dict)
                )
        for pointer, output_path in output_records:
            if not valid_relative_path(output_path):
                continue
            normalized_path = unicodedata.normalize("NFC", output_path)
            prior_owner = output_path_owners.get(output_path) or normalized_output_path_owners.get(normalized_path)
            if prior_owner is not None:
                audit.error("V100_DUPLICATE_OUTPUT_PATH", pointer, f"Output path aliases an already declared output at {prior_owner}.")
            else:
                output_path_owners[output_path] = pointer
                normalized_output_path_owners[normalized_path] = pointer
            if audit.asset_root is not None:
                candidate = audit.asset_root / output_path
                try:
                    stat_result = candidate.stat()
                except OSError:
                    continue
                file_identity = (stat_result.st_dev, stat_result.st_ino)
                prior_file_owner = output_file_owners.get(file_identity)
                if prior_file_owner is not None and prior_file_owner != pointer:
                    audit.error("V101_DUPLICATE_OUTPUT_FILE", pointer, f"Output resolves to the same physical file as {prior_file_owner}.")
                else:
                    output_file_owners[file_identity] = pointer
    if lcp_count > 1:
        audit.error("V084_MULTIPLE_LCP", "/assets", "Declare at most one LCP candidate.")

    if policy.get("discover_mode") is True:
        for index in hero_indices:
            output = assets[index].get("output", {}) if isinstance(assets[index], dict) else {}
            width = output.get("width")
            height = output.get("height")
            if not is_int(width) or width < 1200:
                audit.error("V085_DISCOVER_WIDTH", f"/assets/{index}/output/width", "Discover hero must be at least 1200 px wide.")
            if not is_int(width) or not is_int(height) or width * height <= 300000:
                audit.error("V086_DISCOVER_PIXELS", f"/assets/{index}/output", "Discover hero must exceed 300,000 total pixels.")


def validate_dataset_manifest_document(document: Any, audit: Audit) -> dict[str, Any]:
    """Validate a standalone dataset manifest without inventing a media wrapper."""
    required = {"schema_version", "run_id", "datasets"}
    if not check_keys(audit, document, "", required, required):
        return {"asset_ids": [], "claim_ids": [], "dataset_ids": [], "output_paths": [], "run_id": None}
    if contains_forbidden_structured_character(document):
        audit.error(
            "V099_FORBIDDEN_STRUCTURED_CHARACTER",
            "",
            "Manifest strings cannot contain line, invisible, bidi, surrogate, or other forbidden structured-text characters.",
        )
    if document.get("schema_version") != VERSION:
        audit.error("V081_SCHEMA_VERSION", "/schema_version", f"Expected schema_version {VERSION!r}.")
    require_nonempty(audit, document, "run_id", "")
    datasets = document.get("datasets")
    dataset_ids: set[str] = set()
    if not isinstance(datasets, list):
        audit.error("V003_TYPE", "/datasets", "Expected an array; an empty array is valid.")
    else:
        for index, dataset in enumerate(datasets):
            dataset_id, _fields, _transforms, _synthetic = validate_dataset(audit, dataset, index, True)
            if nonempty(dataset_id):
                if dataset_id in dataset_ids:
                    audit.error("V082_DUPLICATE_DATASET", f"/datasets/{index}/dataset_id", "Dataset IDs must be unique.")
                dataset_ids.add(dataset_id)
    return {
        "asset_ids": [],
        "claim_ids": [],
        "dataset_ids": sorted(dataset_ids),
        "output_paths": [],
        "run_id": document.get("run_id") if nonempty(document.get("run_id")) else None,
    }


def collect_media_identity(manifest: Any) -> dict[str, Any]:
    """Return stable cross-validator identity fields without trusting manifest types."""
    if not isinstance(manifest, dict):
        return {
            "asset_ids": [],
            "claim_ids": [],
            "dataset_ids": [],
            "output_paths": [],
            "run_id": None,
        }
    asset_ids: set[str] = set()
    claim_ids: set[str] = set()
    output_paths: set[str] = set()
    assets = manifest.get("assets")
    if isinstance(assets, list):
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            asset_id = asset.get("asset_id")
            if nonempty(asset_id):
                asset_ids.add(asset_id)
            claims = asset.get("claim_ids")
            if isinstance(claims, list):
                claim_ids.update(claim for claim in claims if nonempty(claim))
            output = asset.get("output")
            if not isinstance(output, dict):
                continue
            output_path = output.get("path")
            if nonempty(output_path):
                output_paths.add(output_path)
            variants = output.get("variants")
            if isinstance(variants, list):
                for variant in variants:
                    if isinstance(variant, dict) and nonempty(variant.get("path")):
                        output_paths.add(variant["path"])
    dataset_ids: set[str] = set()
    datasets = manifest.get("datasets")
    if isinstance(datasets, list):
        for dataset in datasets:
            if isinstance(dataset, dict) and nonempty(dataset.get("dataset_id")):
                dataset_ids.add(dataset["dataset_id"])
    return {
        "asset_ids": sorted(asset_ids),
        "claim_ids": sorted(claim_ids),
        "dataset_ids": sorted(dataset_ids),
        "output_paths": sorted(output_paths),
        "run_id": manifest.get("run_id") if nonempty(manifest.get("run_id")) else None,
    }


def validate_run_binding(
    run_directory: Path,
    media_manifest: Any,
    identity: dict[str, Any],
    audit: Audit,
) -> None:
    """Bind a media manifest to its article run and claim ledger when available."""
    article_manifest_path = run_directory / "manifest.json"
    article_manifest = None
    if path_uses_symlink(run_directory, article_manifest_path):
        audit.error("V014_PATH_SYMLINK", "/run/manifest.json", "Article run manifest traverses a symlink.")
    else:
        try:
            article_manifest = load_json(article_manifest_path)
        except FileNotFoundError:
            audit.error("V097_RUN_CONTEXT_INVALID", "/run/manifest.json", "Article run manifest is missing.")
        except (json.JSONDecodeError, UnicodeError):
            audit.error("V097_RUN_CONTEXT_INVALID", "/run/manifest.json", "Article run manifest is invalid JSON.")
        except ValidatorUnavailable as exc:
            raise exc
    if article_manifest is not None and not isinstance(article_manifest, dict):
        audit.error("V097_RUN_CONTEXT_INVALID", "/run/manifest.json", "Article run manifest must be an object.")
    elif isinstance(article_manifest, dict) and isinstance(media_manifest, dict):
        if media_manifest.get("run_id") != article_manifest.get("run_id"):
            audit.error(
                "V088_ARTICLE_RUN_ID_MISMATCH",
                "/run_id",
                "Media and article manifests must use the same run_id.",
            )

    referenced_claim_ids = set(identity.get("claim_ids", []))
    if not referenced_claim_ids:
        return
    claims_path = run_directory / "claims.jsonl"
    if path_uses_symlink(run_directory, claims_path):
        audit.error("V014_PATH_SYMLINK", "/run/claims.jsonl", "Claim ledger traverses a symlink.")
        return
    if not claims_path.is_file():
        audit.error("V097_RUN_CONTEXT_INVALID", "/run/claims.jsonl", "Media claims cannot be resolved because claims.jsonl is missing.")
        return
    known_claim_ids: set[str] = set()
    try:
        lines = claims_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ValidatorUnavailable(f"Cannot read {claims_path}") from exc
    for line_number, raw_line in enumerate(lines, start=1):
        if not raw_line.strip():
            continue
        try:
            record = strict_json_loads(raw_line)
        except json.JSONDecodeError:
            audit.error(
                "V097_RUN_CONTEXT_INVALID",
                f"/run/claims.jsonl/{line_number}",
                "Claim ledger line is invalid JSON.",
            )
            continue
        claim_id = record.get("claim_id") if isinstance(record, dict) else None
        if nonempty(claim_id):
            known_claim_ids.add(claim_id)
        else:
            audit.error(
                "V097_RUN_CONTEXT_INVALID",
                f"/run/claims.jsonl/{line_number}",
                "Claim ledger record has no valid claim_id.",
            )
    for claim_id in sorted(referenced_claim_ids - known_claim_ids):
        audit.error(
            "V089_MEDIA_CLAIM_UNKNOWN",
            "/assets",
            f"Media references unknown claim_id {claim_id!r}.",
        )


def path_uses_symlink(root: Path, candidate: Path) -> bool:
    try:
        relative = candidate.absolute().relative_to(root.absolute())
    except ValueError:
        return True
    current = root.absolute()
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def load_json(path: Path, unavailable: bool = False) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(
                handle,
                parse_constant=reject_nonfinite_json_constant,
                parse_float=parse_finite_json_float,
                object_pairs_hook=reject_duplicate_json_keys,
            )
    except PermissionError as exc:
        raise ValidatorUnavailable(f"Cannot read {path}") from exc
    except FileNotFoundError:
        if unavailable:
            raise ValidatorUnavailable(f"Required validator resource is missing: {path}")
        raise
    except json.JSONDecodeError:
        if unavailable:
            raise ValidatorUnavailable(f"Required validator resource is invalid JSON: {path}")
        raise
    except UnicodeError:
        if unavailable:
            raise ValidatorUnavailable(f"Required validator resource is not valid UTF-8: {path}")
        raise
    except OSError as exc:
        raise ValidatorUnavailable(f"Cannot access {path}") from exc


def report_for(
    audit: Audit,
    input_name: str,
    status: str,
    identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    issues = sorted(
        audit.issues,
        key=lambda issue: (
            SEVERITY_ORDER.get(issue["severity"], 9),
            issue["code"],
            issue["path"],
            issue["message"],
        ),
    )
    errors = sum(issue["severity"] == "error" for issue in issues)
    warnings = sum(issue["severity"] == "warning" for issue in issues)
    return {
        "checked": {
            "assets": audit.checked_assets,
            "datasets": audit.checked_datasets,
            "local_files": audit.asset_root is not None,
        },
        "counts": {
            "errors": errors,
            "warnings": warnings,
        },
        "identity": identity if identity is not None else collect_media_identity(None),
        "input": input_name,
        "issues": issues,
        "status": status,
        "validator": {
            "name": "best-seo-article-media",
            "stdlib_only": True,
            "version": VERSION,
        },
    }


def unavailable_report(input_name: str, message: str) -> dict[str, Any]:
    return {
        "checked": {"assets": 0, "datasets": 0, "local_files": False},
        "counts": {"errors": 1, "warnings": 0},
        "identity": collect_media_identity(None),
        "input": input_name,
        "issues": [
            {
                "code": "V900_VALIDATOR_UNAVAILABLE",
                "message": message,
                "path": "",
                "severity": "error",
            }
        ],
        "status": "unavailable",
        "validator": {
            "name": "best-seo-article-media",
            "stdlib_only": True,
            "version": VERSION,
        },
    }


def emit(report: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True, allow_nan=False))
    sys.stdout.write("\n")


class JsonArgumentParser(argparse.ArgumentParser):
    """Return machine-readable argument failures on stdout."""

    def error(self, message: str) -> None:
        report = unavailable_report("<arguments>", f"Invalid command-line arguments: {message}")
        report["issues"][0]["code"] = "V901_ARGUMENTS_INVALID"
        emit(report)
        raise SystemExit(2)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = JsonArgumentParser(description=__doc__)
    parser.add_argument(
        "manifest",
        type=Path,
        help="Media manifest JSON or article-run directory to validate.",
    )
    parser.add_argument(
        "--dataset-only",
        action="store_true",
        help="Treat the positional JSON file as a standalone dataset manifest.",
    )
    parser.add_argument(
        "--asset-root",
        type=Path,
        help="Optional package root for path, SHA-256, and byte-size verification.",
    )
    parser.add_argument(
        "--dataset-manifest",
        action="append",
        default=[],
        type=Path,
        help="Optional standalone dataset manifest; repeat for multiple manifests.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Accepted for consistency; reports are already emitted as formatted JSON.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    input_name = str(args.manifest)
    manifest_path = args.manifest
    dataset_manifest_paths = list(args.dataset_manifest)
    asset_root = args.asset_root
    run_directory: Path | None = None
    if manifest_path.is_dir():
        run_directory = manifest_path.expanduser().resolve()
        manifest_path = run_directory / "media-manifest.json"
        if asset_root is None:
            asset_root = run_directory
        adjacent_dataset_manifest = run_directory / "dataset-manifest.json"
        if adjacent_dataset_manifest.is_file() and adjacent_dataset_manifest not in dataset_manifest_paths:
            dataset_manifest_paths.append(adjacent_dataset_manifest)
    script_root = Path(__file__).resolve().parent.parent
    schema_dir = script_root / "schemas"

    try:
        for schema_name in ("media-manifest.schema.json", "dataset-manifest.schema.json"):
            schema = load_json(schema_dir / schema_name, unavailable=True)
            if not isinstance(schema, dict):
                raise ValidatorUnavailable(f"Schema root must be an object in {schema_name}")
            version = schema.get("properties", {}).get("schema_version", {}).get("const")
            if version != VERSION:
                raise ValidatorUnavailable(f"Schema version mismatch in {schema_name}")
        if asset_root is not None and not asset_root.is_dir():
            raise ValidatorUnavailable("--asset-root is unavailable or is not a directory")
        audit = Audit(asset_root)
    except (OSError, RuntimeError, ValueError, ValidatorUnavailable) as exc:
        emit(unavailable_report(input_name, str(exc)))
        return 2

    unsafe_inputs: list[tuple[str, Path]] = []
    if run_directory is not None:
        if path_uses_symlink(run_directory, manifest_path):
            unsafe_inputs.append(("/media-manifest.json", manifest_path))
        for index, dataset_path in enumerate(dataset_manifest_paths):
            if path_uses_symlink(run_directory, dataset_path):
                unsafe_inputs.append((f"/external_dataset_manifests/{index}", dataset_path))
    else:
        if manifest_path.is_symlink():
            unsafe_inputs.append(("", manifest_path))
        for index, dataset_path in enumerate(dataset_manifest_paths):
            if dataset_path.is_symlink():
                unsafe_inputs.append((f"/external_dataset_manifests/{index}", dataset_path))
    if unsafe_inputs:
        for pointer, unsafe_path in unsafe_inputs:
            audit.error("V014_PATH_SYMLINK", pointer, f"Refusing to read manifest through a symlink: {unsafe_path}")
        emit(report_for(audit, input_name, "failed"))
        return 1

    try:
        manifest = load_json(manifest_path)
    except FileNotFoundError:
        audit.error("V901_INPUT_MISSING", "", "Manifest file does not exist.")
        emit(report_for(audit, input_name, "failed"))
        return 1
    except UnicodeError:
        audit.error("V902_INVALID_JSON", "", "Manifest is not valid UTF-8 JSON.")
        emit(report_for(audit, input_name, "failed"))
        return 1
    except json.JSONDecodeError as exc:
        audit.error(
            "V902_INVALID_JSON",
            "",
            f"Manifest is not valid JSON at line {exc.lineno}, column {exc.colno}.",
        )
        emit(report_for(audit, input_name, "failed"))
        return 1
    except ValidatorUnavailable as exc:
        emit(unavailable_report(input_name, str(exc)))
        return 2

    if args.dataset_only:
        if run_directory is not None or dataset_manifest_paths:
            audit.error("V005_MODE_CONFLICT", "", "--dataset-only accepts one dataset manifest file and no merged dataset manifests.")
        try:
            identity = validate_dataset_manifest_document(manifest, audit)
        except ValidatorUnavailable as exc:
            emit(unavailable_report(input_name, str(exc)))
            return 2
        except Exception as exc:
            identity = collect_media_identity(None)
            audit.error("V098_INPUT_VALIDATION_ERROR", "", f"Dataset input could not be validated safely ({type(exc).__name__}).")
        errors = sum(issue["severity"] == "error" for issue in audit.issues)
        status = "failed" if errors else "clean"
        emit(report_for(audit, input_name, status, identity))
        return 1 if errors else 0

    if isinstance(manifest, dict) and dataset_manifest_paths:
        embedded = manifest.get("datasets")
        merged_datasets = list(embedded) if isinstance(embedded, list) else embedded
        for index, dataset_path in enumerate(dataset_manifest_paths):
            external_pointer = f"/external_dataset_manifests/{index}"
            try:
                external = load_json(dataset_path)
            except FileNotFoundError:
                audit.error("V903_DATASET_MANIFEST_MISSING", external_pointer, "Dataset manifest file does not exist.")
                continue
            except (json.JSONDecodeError, UnicodeError) as exc:
                audit.error(
                    "V904_DATASET_MANIFEST_JSON",
                    external_pointer,
                    f"Dataset manifest is invalid JSON at line {exc.lineno}, column {exc.colno}.",
                )
                continue
            except ValidatorUnavailable as exc:
                emit(unavailable_report(input_name, str(exc)))
                return 2

            required = {"schema_version", "run_id", "datasets"}
            if not check_keys(audit, external, external_pointer, required, required):
                continue
            if external.get("schema_version") != VERSION:
                audit.error("V081_SCHEMA_VERSION", f"{external_pointer}/schema_version", f"Expected schema_version {VERSION!r}.")
            if external.get("run_id") != manifest.get("run_id"):
                audit.error("V087_RUN_ID_MISMATCH", f"{external_pointer}/run_id", "Dataset and media manifests must use the same run_id.")
            external_datasets = external.get("datasets")
            if not isinstance(external_datasets, list):
                audit.error("V003_TYPE", f"{external_pointer}/datasets", "Expected an array.")
                continue
            if isinstance(merged_datasets, list):
                merged_datasets.extend(external_datasets)
        manifest = dict(manifest)
        manifest["datasets"] = merged_datasets

    identity = collect_media_identity(manifest)
    try:
        validate_manifest(manifest, audit)
        if run_directory is not None:
            validate_run_binding(run_directory, manifest, identity, audit)
    except ValidatorUnavailable as exc:
        emit(unavailable_report(input_name, str(exc)))
        return 2
    except Exception as exc:
        audit.error(
            "V098_INPUT_VALIDATION_ERROR",
            "",
            f"Input could not be validated safely ({type(exc).__name__}).",
        )

    errors = sum(issue["severity"] == "error" for issue in audit.issues)
    status = "failed" if errors else "clean"
    emit(report_for(audit, input_name, status, identity))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
