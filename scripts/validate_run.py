#!/usr/bin/env python3
"""Validate an article run's observable artifact and status invariants."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import ipaddress
import json
import math
import os
import re
import subprocess
import sys
import unicodedata
from datetime import date, datetime, timedelta, timezone
from html import unescape as html_unescape
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlparse, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:  # Optional, free IDNA2008/UTS-46 validation; absence fails A-labels closed.
    import idna as idna2008
except ImportError:  # pragma: no cover - exercised by portable fallback tests.
    idna2008 = None

from capability_preflight import (
    ABSENCE_EFFECTS as CANONICAL_ABSENCE_EFFECTS,
    DEFAULT_FALLBACKS as CANONICAL_DEFAULT_FALLBACKS,
)


STATUSES = (
    "blocked",
    "draft-only",
    "needs-evidence",
    "needs-expert-review",
    "content-ready",
    "publish-package-ready",
    "published-pending-verification",
    "verified-live",
    "measured",
)
RANK = {status: index for index, status in enumerate(STATUSES)}
PLACEHOLDER = re.compile(r"(?:\[NEEDS[^\]]*\]|\bTODO\b|\bTBD\b|<placeholder>|lorem ipsum)", re.IGNORECASE)
NEGATIVE_EVIDENCE = re.compile(
    r"(?:"
    r"\b(?:this|it|evidence|result|page|asset|check|claim)?[ \t]*(?:was|is|were|are)[ \t]+not[ \t]+(?:checked|verified|observed|inspected|tested)\b"
    r"|\bcould[ \t]+not[ \t]+(?:check|verify|observe|inspect|test)\b"
    r"|\bunable[ \t]+to[ \t]+(?:check|verify|observe|inspect|test)\b"
    r"|\b(?:evidence|observation|verification|inspection|testing?)[ \t]+(?:is|was)[ \t]+unavailable\b"
    r"|\bno[ \t]+(?:observation|inspection|verification|test|check)[ \t]+(?:was|is)[ \t]+(?:made|performed|recorded)\b"
    r")",
    re.IGNORECASE,
)
MD_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)\n]*)\)")
MD_IMAGE = re.compile(r"!\[[^\]]*\]\(([^)\n]*)\)")
MD_ANY_INLINE_DESTINATION = re.compile(r"\]\(([^)\n]*)\)")
MD_REFERENCE_DEFINITION = re.compile(
    r'^[ \t]{0,3}\[([^\]\n]+)\]:[ \t]*(?:<([^>\n]*)>|(\S+))(?:[ \t]+(?:"[^"]*"|\'[^\']*\'|\([^\n)]*\)))?[ \t]*$',
    re.MULTILINE,
)
MD_REFERENCE_IMAGE = re.compile(r"!\[([^\]\n]*)\]\[([^\]\n]*)\]")
MD_SHORTCUT_IMAGE = re.compile(r"!\[([^\]\n]+)\](?![\[(])")
MD_REFERENCE_LINK = re.compile(r"(?<!!)\[([^\]\n]+)\]\[([^\]\n]*)\]")
MD_SHORTCUT_LINK = re.compile(r"(?<!!)\[([^\]\n]+)\](?![\[(])")
MD_AUTOLINK = re.compile(r"<([A-Za-z][A-Za-z0-9+.-]{1,31}):([^<>\s]*)>")
HTML_MEDIA = re.compile(r"<(?:img|picture|video|audio|source)\b", re.IGNORECASE)
# MDX accepts ESM declarations without whitespace after the keyword (for
# example a quote, comment, star, or brace). Treat every keyword token at the
# start of a logical line as active content, while avoiding prose words such as
# "important" and hyphenated text such as "export-quality".
MDX_ESM = re.compile(r"^\s*(?:import|export)(?![A-Za-z0-9_$-])", re.MULTILINE)
MDX_COMPONENT = re.compile(r"</?[A-Z][A-Za-z0-9_.:-]*(?:\s|/?>)")
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,127}$")
IDENTIFIER = re.compile(r"^[A-Za-z0-9._-]+$")
RFC3339_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\Z"
)
MACHINE_TOKEN = re.compile(r"^[a-z][a-z0-9:_-]*$")
PROVIDER_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+ -]*$")
MEASUREMENT_EVIDENCE_PATH = re.compile(
    r"^measurement/evidence/(?!\.\.(?:/|$))(?!.*?/\.\.(?:/|$))[^\x00-\x1F\x7F\\]+$"
)
MEDIA_SUFFIXES = {".avif", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp", ".mp4", ".webm", ".mov", ".vtt"}
CAPABILITY_ORDER = ("serp", "keywords", "gsc", "ga4", "crawl", "cwv", "fact_check", "images", "charts", "cms")
CAPABILITY_NAMES = set(CAPABILITY_ORDER)
CAPABILITY_STATES = {"AVAILABLE", "USER_EXPORT", "FALLBACK", "UNAVAILABLE"}
REVIEW_BINDING_VERSION = "review-binding-v1"
QUALITY_GATE_VERSION = "article-quality-gate-v2"
MEASUREMENT_CONTRACT_VERSION = "measurement-v1"
CONTENT_REVIEW_PATHS = (
    "intake.json",
    "drafts/final.md",
    "claims.jsonl",
    "research/sources.jsonl",
    "research/quality-gate.json",
)
EDITORIAL_QUALITY_CHECKS = {
    "answer_and_intent",
    "truth_and_boundaries",
    "information_gain",
    "practical_utility",
    "clarity_and_voice",
    "journey_and_conversion",
}
QUALITY_FORMATS = {"guide", "comparison", "how-to", "list", "category", "opinion", "other"}
COMPETITIVE_ADVANTAGE_KINDS = {"original-test", "original-data", "expert-input", "reader-tool", "none"}
EMPIRICAL_ADVANTAGE_KINDS = {"original-test", "original-data", "expert-input"}
ORIGINAL_EVIDENCE_SOURCE_TYPES = {"primary", "first-party", "user-provided"}
PAGE_FILTER_FIELDS = {
    "page", "search_type", "query", "country", "device", "device_category",
    "channel", "source", "medium", "campaign", "event_name", "content_group",
}
PAGE_SEGMENT_FIELDS = {
    "search_type", "query", "country", "device", "device_category", "channel",
    "source", "medium", "campaign", "event_name", "content_group", "user_type",
}
ACTIVE_ROOT: Path | None = None
FUTURE_TOLERANCE = timedelta(minutes=5)
CAPABILITY_MAX_AGE = timedelta(days=31)
SERP_MAX_AGE = timedelta(days=31)
RESEARCH_ACQUISITIONS = {"agent-web", "user-provided"}
ARTICLE_SCHEMA_TYPES = {
    "AdvertiserContentArticle",
    "AnalysisNewsArticle",
    "Article",
    "BackgroundNewsArticle",
    "BlogPosting",
    "MedicalScholarlyArticle",
    "NewsArticle",
    "OpinionNewsArticle",
    "Report",
    "ReportageNewsArticle",
    "ReviewNewsArticle",
    "SatiricalArticle",
    "ScholarlyArticle",
    "SocialMediaPosting",
    "TechArticle",
}
FORBIDDEN_UNICODE_FORMATS = {
    0x061C,
    0x180E,
    0x200B,
    0x200E,
    0x200F,
    0x202A,
    0x202B,
    0x202C,
    0x202D,
    0x202E,
    0x2060,
    0x2061,
    0x2062,
    0x2063,
    0x2064,
    0x2066,
    0x2067,
    0x2068,
    0x2069,
    0xFEFF,
}
INVISIBLE_VISIBLE_CATEGORY_EXCEPTIONS = {"\u115f", "\u1160", "\u2800", "\u3164", "\uffa0"}
ACTOR_INVISIBLE_CHARACTERS = INVISIBLE_VISIBLE_CATEGORY_EXCEPTIONS | {"\u034f"}
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
WORD_CATEGORY_PREFIXES = {"L", "N"}


def finding(code: str, severity: str, message: str, **evidence: Any) -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message, "evidence": evidence}


class JsonArgumentParser(argparse.ArgumentParser):
    """Return machine-readable argument failures on stdout."""

    def error(self, message: str) -> None:
        print(
            json.dumps(
                {
                    "validator": "run",
                    "status": "unavailable",
                    "findings": [finding("ARGUMENTS_INVALID", "P1", "Invalid command-line arguments", error=message)],
                    "child_reports": [],
                },
                ensure_ascii=True,
                allow_nan=False,
            )
        )
        raise SystemExit(2)


def contains_forbidden_unicode_control(value: Any) -> bool:
    """Reject zero-width/bidi controls that can spoof structured identities and URLs."""

    if isinstance(value, str):
        return any(
            ord(character) in FORBIDDEN_UNICODE_FORMATS
            or unicodedata.category(character) in {"Cs", "Zl", "Zp"}
            or (unicodedata.category(character) == "Cc" and ord(character) >= 0x80)
            or is_default_ignorable(character)
            for character in value
        )
    if isinstance(value, dict):
        return any(contains_forbidden_unicode_control(key) or contains_forbidden_unicode_control(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(contains_forbidden_unicode_control(item) for item in value)
    return False


def contains_forbidden_document_control(value: Any) -> bool:
    """Reject document controls while allowing normal tabs and line endings."""

    return not isinstance(value, str) or contains_forbidden_unicode_control(value) or any(
        (ord(character) < 0x20 and character not in {"\t", "\n", "\r"})
        or ord(character) == 0x7F
        for character in value
    )


def contains_forbidden_single_line_control(value: Any) -> bool:
    """Reject JSON line controls in addition to spoofing Unicode controls."""

    return not isinstance(value, str) or any(
        ord(character) < 0x20
        or ord(character) == 0x7F
        or ord(character) in FORBIDDEN_UNICODE_FORMATS
        or unicodedata.category(character).startswith("C")
        or unicodedata.category(character) in {"Zl", "Zp"}
        or character in INVISIBLE_VISIBLE_CATEGORY_EXCEPTIONS
        or is_default_ignorable(character)
        for character in value
    )


def contains_forbidden_json_string_control(value: Any) -> bool:
    """Recursively reject line/control characters from structured scalar text."""

    if isinstance(value, str):
        return contains_forbidden_single_line_control(value)
    if isinstance(value, dict):
        return any(
            contains_forbidden_json_string_control(key)
            or contains_forbidden_json_string_control(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(contains_forbidden_json_string_control(item) for item in value)
    return False


def substantive_provider_label(value: Any) -> bool:
    """Require an unambiguous single-line provider identifier."""

    return (
        substantive_string(value)
        and not contains_forbidden_single_line_control(value)
        and "\\" not in value
        and unicodedata.normalize("NFKC", value) == value
        and PROVIDER_LABEL.fullmatch(value) is not None
    )


def substantive_actor_identity(value: Any, minimum: int = 1) -> bool:
    """Require a visible, single-line reviewer or role identity."""

    if (
        not substantive_string(value, minimum)
        or contains_forbidden_single_line_control(value)
        or contains_placeholder(value)
    ):
        return False
    return not any(
        character in ACTOR_INVISIBLE_CHARACTERS
        or is_default_ignorable(character)
        for character in value
    )


def is_default_ignorable(character: str) -> bool:
    """Return whether a code point can invisibly alter an actor identity."""

    codepoint = ord(character)
    return any(start <= codepoint <= end for start, end in DEFAULT_IGNORABLE_RANGES)


def reject_nonfinite_json_constant(token: str) -> Any:
    """Reject Python's non-standard NaN and Infinity JSON extensions."""

    raise ValueError(f"non-finite JSON number is not allowed: {token}")


def parse_finite_json_float(token: str) -> float:
    value = float(token)
    if not math.isfinite(value):
        raise ValueError(f"non-finite JSON number is not allowed: {token}")
    return value


def reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build a JSON object while rejecting ambiguous duplicate names."""

    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key is not allowed: {key!r}")
        result[key] = value
    return result


def strict_json_loads(text: str) -> Any:
    """Parse portable RFC JSON without non-finite numbers or duplicate keys."""

    return json.loads(
        text,
        parse_constant=reject_nonfinite_json_constant,
        parse_float=parse_finite_json_float,
        object_pairs_hook=reject_duplicate_json_keys,
    )


def substantive_string(value: Any, minimum: int = 1) -> bool:
    """Require visible text with a meaningful letter/number component.

    Punctuation and symbols may contribute to the existing length threshold,
    but cannot create or pad a substantive record by themselves.
    """

    if not isinstance(value, str):
        return False
    normalized = unicodedata.normalize("NFKC", value)
    visible = [
        character
        for character in normalized
        if character not in INVISIBLE_VISIBLE_CATEGORY_EXCEPTIONS
        and unicodedata.category(character)[0] in VISIBLE_CATEGORY_PREFIXES
    ]
    word_characters = [
        character
        for character in visible
        if unicodedata.category(character)[0] in WORD_CATEGORY_PREFIXES
    ]
    required_word_characters = max(1, (minimum + 1) // 2)
    return len(visible) >= minimum and len(word_characters) >= required_word_characters


def substantive_evidence(value: Any, minimum: int = 12) -> bool:
    """Require an observation, not a padded restatement of its outcome."""

    if (
        not substantive_string(value, minimum)
        or contains_forbidden_single_line_control(value)
        or contains_placeholder(value)
        or contains_negative_evidence(value)
    ):
        return False
    normalized = unicodedata.normalize("NFKC", value).casefold()
    tokens = [
        token
        for token in re.findall(r"[^\W_]+", normalized, flags=re.UNICODE)
        if token
    ]
    bare_outcome_tokens = {
        "a",
        "applicable",
        "approve",
        "approved",
        "fail",
        "failed",
        "n",
        "no",
        "not",
        "ok",
        "pass",
        "passed",
        "success",
        "successful",
        "true",
        "yes",
    }
    return bool(tokens) and not set(tokens).issubset(bare_outcome_tokens)


def valid_dimension_value(value: Any) -> bool:
    """Accept only portable scalar values in measurement descriptor maps."""

    if isinstance(value, str):
        return substantive_string(value) and not contains_forbidden_single_line_control(value)
    if isinstance(value, bool):
        return True
    return isinstance(value, (int, float)) and math.isfinite(value)


def valid_dimension_map(value: Any) -> bool:
    """Require canonical machine keys and finite, single-line scalar values."""

    return isinstance(value, dict) and all(
        isinstance(key, str)
        and MACHINE_TOKEN.fullmatch(key) is not None
        and valid_dimension_value(item)
        for key, item in value.items()
    )


def valid_identifier(value: Any) -> bool:
    return isinstance(value, str) and IDENTIFIER.fullmatch(value) is not None


def contains_placeholder(value: Any) -> bool:
    return isinstance(value, str) and PLACEHOLDER.search(unicodedata.normalize("NFKC", value)) is not None


def contains_negative_evidence(value: Any) -> bool:
    """Reject evidence text that explicitly says the asserted check did not occur."""

    return isinstance(value, str) and NEGATIVE_EVIDENCE.search(unicodedata.normalize("NFKC", value)) is not None


def normalized_identity(value: Any) -> str:
    """Normalize an actor label only for conflict detection, not role binding."""

    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    without_format_controls = "".join(
        character
        for character in normalized
        if not unicodedata.category(character).startswith("C")
        and unicodedata.category(character) not in {"Zl", "Zp"}
        and character not in ACTOR_INVISIBLE_CHARACTERS
        and not is_default_ignorable(character)
    )
    return " ".join(without_format_controls.split())


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or RFC3339_TIMESTAMP.fullmatch(value) is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def timestamp_is_future(value: Any) -> bool:
    parsed = parse_timestamp(value)
    return parsed is not None and parsed > datetime.now(timezone.utc) + FUTURE_TOLERANCE


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


def valid_http_url(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    if (
        value != value.strip()
        or "\\" in value
        or contains_forbidden_unicode_control(value)
        or any(character.isspace() or unicodedata.category(character).startswith("C") for character in value)
    ):
        return False
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not hostname or parsed.username is not None or parsed.password is not None or port == 0:
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
    # Browsers remove literal and percent-encoded dot segments before fetching,
    # and may treat encoded slash/backslash as routing separators downstream.
    # Reject those aliases so an evidence, canonical, or live-verification URL
    # cannot name different bytes than the browser actually requests.
    if re.search(r"%(?:2f|5c)", parsed.path, re.IGNORECASE) or re.search(r"%(?![0-9A-Fa-f]{2})", parsed.path):
        return False
    try:
        decoded_path = unquote(parsed.path, encoding="utf-8", errors="strict")
    except UnicodeDecodeError:
        return False
    if (
        "\\" in decoded_path
        or contains_forbidden_unicode_control(decoded_path)
        or any(character.isspace() or unicodedata.category(character).startswith("C") for character in decoded_path)
        or any(segment in {".", ".."} for segment in decoded_path.split("/"))
    ):
        return False
    ip_candidate = hostname.strip("[]")
    try:
        return ipaddress.ip_address(ip_candidate).version == 4
    except ValueError:
        pass
    # Python's built-in ``idna`` codec is transitional IDNA2003 and can fold
    # distinct modern browser hosts (for example faß.de and fass.de). Require
    # callers to supply the browser-stable ASCII/punycode hostname instead.
    if not hostname.isascii():
        return False
    ascii_hostname = hostname.casefold()
    if ascii_hostname.endswith("."):
        return False
    if not ascii_hostname or len(ascii_hostname) > 253:
        return False
    labels = ascii_hostname.split(".")
    # WHATWG treats a host ending in a decimal, octal-looking, or hexadecimal
    # number as an IPv4 candidate.  Python's urlparse does not, so accepting it
    # here could bind evidence to a different browser host.  Canonical dotted
    # IPv4 was already accepted by ipaddress above; reject all other numeric
    # spellings and require a letter in a DNS terminal label.
    numeric_final = bool(labels) and re.fullmatch(r"(?:[0-9]+|0[xX][0-9A-Fa-f]+)", labels[-1]) is not None
    return (
        bool(labels)
        and not numeric_final
        and re.search(r"[A-Za-z]", labels[-1]) is not None
        and all(valid_ascii_dns_label(label) for label in labels)
    )


def valid_document_url(value: Any) -> bool:
    """Validate a fetchable document identity rather than an in-page link."""

    if not valid_http_url(value):
        return False
    try:
        return not urlsplit(value).fragment
    except ValueError:
        return False


def valid_article_slug(value: Any) -> bool:
    """Accept one canonical multilingual URL/CMS slug segment."""

    return (
        substantive_string(value)
        and not contains_forbidden_single_line_control(value)
        and unicodedata.normalize("NFC", value) == value
        and value == value.strip()
        and not value.startswith("-")
        and not value.endswith("-")
        and all(character == "-" or unicodedata.category(character)[0] in {"L", "N"} for character in value)
    )


def urls_match(left: Any, right: Any) -> bool:
    if not valid_document_url(left) or not valid_document_url(right):
        return False

    def identity(value: str) -> tuple[Any, ...]:
        parsed = urlsplit(value)
        hostname = (parsed.hostname or "").casefold()
        port = parsed.port
        if (parsed.scheme.casefold(), port) in {("http", 80), ("https", 443)}:
            port = None
        return (
            parsed.scheme.casefold(),
            hostname,
            port,
            parsed.path or "/",
            parsed.query,
            parsed.fragment,
        )

    return identity(left) == identity(right)


def technical_outcome(value: Any, *, allow_not_applicable: bool = True) -> bool:
    allowed = {"passed", "not-applicable"} if allow_not_applicable else {"passed"}
    return isinstance(value, str) and value in allowed


def normalized_check_name(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return unicodedata.normalize("NFKC", value).casefold().strip()


def technical_check_entries(checks: Any) -> list[tuple[str, Any]]:
    if isinstance(checks, dict):
        return [(name, value) for name, value in checks.items() if isinstance(name, str)]
    if isinstance(checks, list):
        return [
            (item.get("check"), item)
            for item in checks
            if isinstance(item, dict) and isinstance(item.get("check"), str)
        ]
    return []


def observed_check_acceptable(value: Any, *, allow_not_applicable: bool = False) -> bool:
    if not isinstance(value, dict):
        return False
    return technical_outcome(value.get("status"), allow_not_applicable=allow_not_applicable) and substantive_evidence(value.get("evidence"))


def named_check_passed(checks: Any, name: str) -> bool:
    if isinstance(checks, dict):
        value = checks.get(name)
        return isinstance(value, dict) and technical_outcome(value.get("status"), allow_not_applicable=False) and substantive_evidence(value.get("evidence"))
    if isinstance(checks, list):
        return any(
            isinstance(item, dict)
            and item.get("check") == name
            and technical_outcome(item.get("status"), allow_not_applicable=False)
            and substantive_evidence(item.get("evidence"))
            for item in checks
        )
    return False


def named_check_acceptable(checks: Any, name: str) -> bool:
    if isinstance(checks, dict):
        value = checks.get(name)
        return isinstance(value, dict) and technical_outcome(value.get("status")) and substantive_evidence(value.get("evidence"))
    if isinstance(checks, list):
        return any(
            isinstance(item, dict)
            and item.get("check") == name
            and technical_outcome(item.get("status"))
            and substantive_evidence(item.get("evidence"))
            for item in checks
        )
    return False


class PackageHTMLInspector(HTMLParser):
    """Collect structural and active-content defects from package HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.h1_count = 0
        self.active_content: list[str] = []
        self.indexability_conflicts: list[str] = []
        self.references: list[str] = []
        self.media_references: list[str] = []
        self.visible_text: list[str] = []
        self.h1_texts: list[str] = []
        self._h1_capture = False
        self._h1_parts: list[str] = []
        self._hidden_depth = 0
        self._element_stack: list[tuple[str, bool]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.casefold()
        attribute_values: dict[str, list[str]] = {}
        for name, value in attrs:
            attribute_values.setdefault(name.casefold(), []).append((value or "").strip())
        element_hidden = (
            lowered in {"head", "script", "style", "template", "datalist", "title"}
            or (lowered == "dialog" and "open" not in attribute_values)
            or "hidden" in attribute_values
            or "inert" in attribute_values
            or any(value.casefold() == "true" for value in attribute_values.get("aria-hidden", []))
        )
        if lowered == "h1" and not self._hidden_depth and not element_hidden:
            self.h1_count += 1
            self._h1_capture = True
            self._h1_parts = []
        if lowered in {"script", "iframe", "object", "embed", "applet", "form", "input", "button", "select", "textarea", "option", "style", "link", "base", "svg"}:
            self.active_content.append(f"tag:{lowered}")
        void_element = lowered in {
            "area", "base", "br", "col", "command", "embed", "hr", "img",
            "input", "keygen", "link", "meta", "param", "source", "track", "wbr",
        }
        if not void_element:
            self._element_stack.append((lowered, element_hidden))
            if element_hidden:
                self._hidden_depth += 1
        media_tag = lowered in {"img", "picture", "video", "audio", "source", "track"}
        for name, value in attrs:
            attr = name.casefold()
            normalized = (value or "").strip().casefold()
            if attr.startswith("on") or attr in {"style", "srcdoc", "action", "formaction"} or normalized.startswith(("javascript:", "vbscript:", "data:")):
                self.active_content.append(f"attribute:{attr}")
            if lowered == "meta" and attr == "http-equiv" and normalized == "refresh":
                self.active_content.append("tag:meta-refresh")
            if attr in {"href", "src", "poster"} and isinstance(value, str) and value.strip():
                self.references.append(value.strip())
                if media_tag and attr in {"src", "poster"}:
                    self.media_references.append(value.strip())
            if media_tag and attr == "srcset" and isinstance(value, str):
                for candidate in value.split(","):
                    reference = candidate.strip().split()[0] if candidate.strip() else ""
                    if reference:
                        self.media_references.append(reference)
        if lowered == "meta":
            robot_names = {
                value.casefold()
                for value in attribute_values.get("name", [])
                if value.casefold() in {"robots", "googlebot", "googlebot-news", "googleother", "googleother-image", "bingbot", "adsbot-google"}
                or value.casefold().endswith("bot")
                or value.casefold().startswith(("googlebot-", "googleother-", "bingbot-", "adsbot-"))
            }
            robot_names.update(
                "x-robots-tag"
                for value in attribute_values.get("http-equiv", [])
                if value.casefold() == "x-robots-tag"
            )
            for robot_name in sorted(robot_names):
                for content in attribute_values.get("content", []):
                    directives = {
                        token.strip().casefold()
                        for token in re.split(r"[,;\s]+", content)
                        if token.strip()
                    }
                    blocked = sorted(directives.intersection({"noindex", "nofollow", "none"}))
                    if blocked:
                        self.indexability_conflicts.append(f"meta:{robot_name}:{','.join(blocked)}")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if lowered == "h1" and self._h1_capture:
            heading = " ".join(" ".join(self._h1_parts).split())
            if heading:
                self.h1_texts.append(heading)
            self._h1_capture = False
            self._h1_parts = []
        matching_index = next(
            (index for index in range(len(self._element_stack) - 1, -1, -1) if self._element_stack[index][0] == lowered),
            None,
        )
        if matching_index is None:
            return
        closed = self._element_stack[matching_index:]
        del self._element_stack[matching_index:]
        self._hidden_depth = max(0, self._hidden_depth - sum(1 for _, hidden in closed if hidden))

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth and data.strip():
            self.visible_text.append(data)
            if self._h1_capture:
                self._h1_parts.append(data)


def _blank_like(value: str) -> str:
    return "".join("\n" if character == "\n" else " " for character in value)


def strip_fenced_code(text: str) -> str:
    """Blank CommonMark-style fenced blocks while preserving line positions."""

    output: list[str] = []
    marker: str | None = None
    minimum = 0
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        if marker is None:
            match = re.match(r"^[ ]{0,3}(`{3,}|~{3,})(.*)$", body)
            if match and not (match.group(1).startswith("`") and "`" in match.group(2)):
                marker = match.group(1)[0]
                minimum = len(match.group(1))
                output.append(_blank_like(line))
            else:
                output.append(line)
            continue
        closing = re.match(r"^[ ]{0,3}(`+|~+)[ \t]*$", body)
        output.append(_blank_like(line))
        if closing and closing.group(1)[0] == marker and len(closing.group(1)) >= minimum:
            marker = None
            minimum = 0
    return "".join(output)


def strip_inline_code(text: str) -> str:
    """Blank paired backtick spans using exact delimiter lengths."""

    output: list[str] = []
    cursor = 0
    while cursor < len(text):
        if text[cursor] != "`":
            output.append(text[cursor])
            cursor += 1
            continue
        end_run = cursor
        while end_run < len(text) and text[end_run] == "`":
            end_run += 1
        width = end_run - cursor
        delimiter = "`" * width
        closing = text.find(delimiter, end_run)
        while closing >= 0 and (
            (closing > 0 and text[closing - 1] == "`")
            or (closing + width < len(text) and text[closing + width] == "`")
        ):
            closing = text.find(delimiter, closing + 1)
        if closing < 0:
            output.append(delimiter)
            cursor = end_run
            continue
        span_end = closing + width
        output.append(_blank_like(text[cursor:span_end]))
        cursor = span_end
    return "".join(output)


def strip_code_for_mdx(text: str) -> str:
    # Front matter is metadata, not reader-visible article content. Strip it
    # before every H1/link/media/MDX scan so YAML comments or flow mappings
    # cannot manufacture a visible heading or reference.
    return strip_markdown_frontmatter(strip_inline_code(strip_fenced_code(text)))


def strip_markdown_frontmatter(text: str) -> str:
    match = re.match(r"\A(?:\ufeff)?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", text, re.DOTALL)
    if not match:
        return text
    return _blank_like(match.group(0)) + text[match.end() :]


def markdown_h1_count(text: str) -> int:
    inspected = strip_markdown_frontmatter(text)
    logical_lines: list[str] = []
    for raw_line in inspected.splitlines():
        line = raw_line
        for _ in range(4):
            previous = line
            line = re.sub(r"^[ ]{0,3}(?:>[ \t]?)+", "", line)
            line = re.sub(r"^[ ]{0,3}(?:[-+*]|\d{1,9}[.)])[ \t]+", "", line)
            if line == previous:
                break
        logical_lines.append(line)
    count = sum(re.match(r"^[ ]{0,3}#[ \t]+\S", line) is not None for line in logical_lines)
    for index in range(1, len(logical_lines)):
        underline = logical_lines[index]
        previous = logical_lines[index - 1]
        if re.match(r"^[ ]{0,3}=+[ \t]*$", underline) and previous.strip() and not previous.startswith(("    ", "\t")):
            count += 1
    return count


def markdown_destinations(pattern: re.Pattern[str], text: str) -> list[str]:
    destinations: list[str] = []
    for match in pattern.finditer(text):
        raw = match.group(1).strip()
        if not raw:
            destinations.append(raw)
            continue
        if raw.startswith("<"):
            closing = raw.find(">")
            if closing < 0:
                destinations.append(raw)
                continue
            destination = raw[1:closing]
            remainder = raw[closing + 1 :].strip()
        else:
            pieces = raw.split(maxsplit=1)
            destination = pieces[0]
            remainder = pieces[1].strip() if len(pieces) == 2 else ""
        if remainder and not remainder.startswith(('"', "'", "(")):
            destinations.append(raw)
        else:
            destinations.append(destination)
    return destinations


def normalize_reference_label(value: str) -> str:
    return " ".join(value.casefold().split())


def markdown_reference_definitions(text: str) -> dict[str, str]:
    definitions: dict[str, str] = {}
    for match in MD_REFERENCE_DEFINITION.finditer(text):
        label = normalize_reference_label(match.group(1))
        destination = match.group(2) if match.group(2) is not None else match.group(3)
        if label and isinstance(destination, str):
            definitions.setdefault(label, destination)
    return definitions


def markdown_reference_destinations(text: str, *, images: bool) -> list[str]:
    """Resolve full, collapsed, and shortcut reference-style destinations."""

    definitions = markdown_reference_definitions(text)
    if not definitions:
        return []
    without_definitions = MD_REFERENCE_DEFINITION.sub(lambda match: _blank_like(match.group(0)), text)
    full_pattern = MD_REFERENCE_IMAGE if images else MD_REFERENCE_LINK
    shortcut_pattern = MD_SHORTCUT_IMAGE if images else MD_SHORTCUT_LINK
    destinations: list[str] = []
    occupied: list[tuple[int, int]] = []
    for match in full_pattern.finditer(without_definitions):
        label = match.group(2) or match.group(1)
        destination = definitions.get(normalize_reference_label(label))
        if destination is not None:
            destinations.append(destination)
        occupied.append(match.span())
    for match in shortcut_pattern.finditer(without_definitions):
        if any(start <= match.start() < end for start, end in occupied):
            continue
        destination = definitions.get(normalize_reference_label(match.group(1)))
        if destination is not None:
            destinations.append(destination)
    return destinations


def markdown_autolinks(text: str) -> list[str]:
    return [f"{match.group(1)}:{match.group(2)}" for match in MD_AUTOLINK.finditer(text)]


def markdown_indexability_conflicts(text: str) -> list[str]:
    match = re.match(r"\A(?:\ufeff)?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", text, re.DOTALL)
    if not match:
        return []
    body = match.group(1)
    conflicts: list[str] = []
    yaml_advanced_syntax = re.compile(
        r"(?:^[ \t]*\?[ \t]+\S|^[ \t]*<<[ \t]*:|(?:^|[ \t])&[A-Za-z0-9_-]+|(?:^|[ \t])\*[A-Za-z0-9_-]+|(?:^|[ \t])!!|(?:^|[ \t])!<)",
        re.MULTILINE,
    )
    if yaml_advanced_syntax.search(body):
        conflicts.append("frontmatter:yaml-advanced-syntax:ambiguous")
    # YAML double-quoted scalars decode hexadecimal/Unicode escapes before a
    # CMS consumes them. The dependency-free gate cannot safely distinguish
    # an escaped robots directive from benign metadata, so such scalars fail
    # closed instead of letting noindex/nofollow hide behind \x/\u/\U.
    if re.search(r'"(?:[^"\\]|\\.)*\\(?:x[0-9A-Fa-f]{2}|u[0-9A-Fa-f]{4}|U[0-9A-Fa-f]{8})(?:[^"\\]|\\.)*"', body):
        conflicts.append("frontmatter:yaml-escaped-scalar:ambiguous")
    indexability_key = r"(?:robots|x-robots-tag|googlebot(?:-[A-Za-z0-9_-]+)?|googleother(?:-[A-Za-z0-9_-]+)?|bingbot(?:-[A-Za-z0-9_-]+)?|adsbot(?:-[A-Za-z0-9_-]+)?|noindex|no-index|nofollow|no-follow|index|indexable|follow)"
    yaml_indirection = re.compile(
        rf"^[ \t]*[\"']?({indexability_key})[\"']?[ \t]*:[^\n]*(?:&[A-Za-z0-9_-]+|\*[A-Za-z0-9_-]+|!!|!<|<<[ \t]*:)",
        re.IGNORECASE | re.MULTILINE,
    )
    for ambiguous in yaml_indirection.finditer(body):
        conflicts.append(f"frontmatter:{ambiguous.group(1).casefold()}:yaml-indirection")
    key_pattern = re.compile(
        r"^[ \t]*(robots|x-robots-tag|googlebot(?:-[A-Za-z0-9_-]+)?|googleother(?:-[A-Za-z0-9_-]+)?|bingbot(?:-[A-Za-z0-9_-]+)?|adsbot(?:-[A-Za-z0-9_-]+)?)[ \t]*:[ \t]*(.*)$",
        re.IGNORECASE,
    )
    for line in body.splitlines():
        key_match = key_pattern.match(line)
        if not key_match:
            continue
        directives = {
            token.strip(" \t\"'[]").casefold()
            for token in re.split(r"[,;\s]+", key_match.group(2))
            if token.strip(" \t\"'[]")
        }
        blocked = sorted(directives.intersection({"noindex", "nofollow", "none"}))
        if blocked:
            conflicts.append(f"frontmatter:{key_match.group(1).casefold()}:{','.join(blocked)}")

    # Common front matter uses booleans and nested/inline YAML mappings rather
    # than a robots directive string. A full YAML dependency would make the
    # validator provider-dependent, so scan the small indexability vocabulary
    # conservatively anywhere inside the front matter.
    boolean_pair = re.compile(
        r"(?<![A-Za-z0-9_-])[\"']?"
        r"(noindex|no-index|nofollow|no-follow|index|indexable|follow)"
        r"[\"']?[ \t]*:[ \t]*(?:!![A-Za-z0-9_-]+[ \t]*)?[\"']?"
        r"(true|yes|on|1|false|no|off|0|noindex|nofollow)[\"']?",
        re.IGNORECASE,
    )
    for pair in boolean_pair.finditer(body):
        key = pair.group(1).casefold()
        value = pair.group(2).casefold()
        negative_enabled = key in {"noindex", "no-index", "nofollow", "no-follow"} and value in {"true", "yes", "on", "1", "noindex", "nofollow"}
        positive_disabled = key in {"index", "indexable", "follow"} and value in {"false", "no", "off", "0", "noindex", "nofollow"}
        if negative_enabled or positive_disabled:
            conflicts.append(f"frontmatter:{key}:{value}")

    if re.search(r"^[ \t]*(?:robots|x-robots-tag)[ \t]*:[ \t]*(?:\r?\n|$)", body, re.IGNORECASE | re.MULTILINE):
        for directive in re.finditer(r"^[ \t]*-[ \t]*(noindex|nofollow|none)\b", body, re.IGNORECASE | re.MULTILINE):
            conflicts.append(f"frontmatter:robots-list:{directive.group(1).casefold()}")
    robot_context = re.search(
        r"(?<![A-Za-z0-9_-])[\"']?(?:robots|x-robots-tag|googlebot(?:-[A-Za-z0-9_-]+)?|googleother(?:-[A-Za-z0-9_-]+)?|bingbot(?:-[A-Za-z0-9_-]+)?|adsbot(?:-[A-Za-z0-9_-]+)?)[\"']?[ \t]*:",
        body,
        re.IGNORECASE,
    )
    if robot_context:
        for directive in re.finditer(r"(?<![A-Za-z0-9_-])(noindex|nofollow|none)(?![A-Za-z0-9_-])", body, re.IGNORECASE):
            conflicts.append(f"frontmatter:robots-context:{directive.group(1).casefold()}")
    return sorted(set(conflicts))


def metadata_indexability_conflicts(value: Any, path: str = "metadata") -> list[str]:
    """Find destination metadata that would suppress indexing or following."""

    def directive_tokens(item: Any) -> set[str]:
        if isinstance(item, str):
            return {
                token.strip(" \t\"'[]").casefold()
                for token in re.split(r"[,;\s]+", item)
                if token.strip(" \t\"'[]")
            }
        if isinstance(item, list):
            return set().union(*(directive_tokens(member) for member in item)) if item else set()
        if isinstance(item, dict):
            return set().union(*(directive_tokens(member) for member in item.values())) if item else set()
        if isinstance(item, bool):
            return {"true" if item else "false"}
        if isinstance(item, (int, float)) and item in {0, 1}:
            return {str(int(item))}
        return set()

    conflicts: list[str] = []
    if isinstance(value, dict):
        for raw_key, item in value.items():
            key = str(raw_key).casefold().replace("_", "-")
            item_path = f"{path}.{raw_key}"
            if (
                key in {"robots", "x-robots-tag", "googlebot", "googlebot-news", "googleother", "bingbot", "adsbot-google"}
                or key.endswith("bot")
                or key.startswith(("googlebot-", "googleother-", "bingbot-", "adsbot-"))
            ):
                if directive_tokens(item).intersection({"noindex", "nofollow", "none"}):
                    conflicts.append(item_path)
            semantic_tokens = directive_tokens(item)
            negative_enabled = bool(semantic_tokens.intersection({"true", "yes", "on", "1", "noindex", "nofollow"}))
            if key in {"noindex", "no-index", "nofollow", "no-follow"} and negative_enabled:
                conflicts.append(item_path)
            positive_disabled = bool(semantic_tokens.intersection({"false", "no", "off", "0", "noindex", "nofollow"}))
            if key in {"index", "indexable", "follow"} and positive_disabled:
                conflicts.append(item_path)
            if isinstance(item, (dict, list)):
                conflicts.extend(metadata_indexability_conflicts(item, item_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if isinstance(item, (dict, list)):
                conflicts.extend(metadata_indexability_conflicts(item, f"{path}[{index}]"))
    return sorted(set(conflicts))


def markdown_image_marker_count(text: str) -> int:
    """Count unescaped image openers so unsupported CommonMark forms fail closed."""

    count = 0
    cursor = 0
    while True:
        index = text.find("![", cursor)
        if index < 0:
            return count
        backslashes = 0
        probe = index - 1
        while probe >= 0 and text[probe] == "\\":
            backslashes += 1
            probe -= 1
        if backslashes % 2 == 0:
            count += 1
        cursor = index + 2


def mdx_active_features(text: str) -> list[str]:
    inspected = strip_code_for_mdx(text)
    features: list[str] = []
    if contains_forbidden_document_control(inspected):
        features.append("unicode-control")
    canonical = "".join(" " if ord(character) in FORBIDDEN_UNICODE_FORMATS else character for character in inspected)
    if MDX_ESM.search(canonical):
        features.append("esm")
    if MDX_COMPONENT.search(canonical):
        features.append("component")
    if "{" in canonical or "}" in canonical:
        features.append("expression")
    inspector = PackageHTMLInspector()
    try:
        inspector.feed(canonical)
        inspector.close()
    except Exception:
        features.append("unparseable-html")
    features.extend(inspector.active_content)
    return sorted(set(features))


def normalized_markdown_text(text: str) -> str:
    cleaned = strip_code_for_mdx(text)
    cleaned = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", cleaned)
    cleaned = re.sub(r"^---\s.*?^---\s*", " ", cleaned, flags=re.MULTILINE | re.DOTALL)
    cleaned = re.sub(r"^[#>*+\-]+\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"[*_~]", "", cleaned)
    return " ".join(cleaned.casefold().split())


def normalized_html_text(text: str) -> str:
    inspector = PackageHTMLInspector()
    try:
        inspector.feed(text)
        inspector.close()
    except Exception:
        return ""
    return " ".join(" ".join(inspector.visible_text).casefold().split())


def normalized_visible_package_text(text: str, suffix: str) -> str:
    """Extract reader-visible text while ignoring code, comments, and hidden HTML."""

    inspected = text
    if suffix in {".md", ".mdx"}:
        without_reference_definitions = MD_REFERENCE_DEFINITION.sub("", text)
        inspected = normalized_markdown_text(without_reference_definitions)
    inspector = PackageHTMLInspector()
    try:
        inspector.feed(inspected)
        inspector.close()
    except Exception:
        return ""
    return " ".join(" ".join(inspector.visible_text).casefold().split())


def normalized_heading_text(value: str) -> str:
    """Normalize a Markdown/HTML heading to its reader-visible identity."""

    markdown = normalized_markdown_text(value)
    inspector = PackageHTMLInspector()
    try:
        inspector.feed(markdown)
        inspector.close()
    except Exception:
        return ""
    return " ".join(" ".join(inspector.visible_text).casefold().split())


def package_h1_texts(text: str, suffix: str) -> list[str]:
    """Return exact normalized visible H1 labels from the package article."""

    if suffix == ".html":
        inspector = PackageHTMLInspector()
        try:
            inspector.feed(text)
            inspector.close()
        except Exception:
            return []
        return [" ".join(value.casefold().split()) for value in inspector.h1_texts]

    inspected = strip_code_for_mdx(text)
    labels: list[str] = []
    lines = inspected.splitlines()
    for index, line in enumerate(lines):
        atx = re.match(r"^[ ]{0,3}#[ \t]+(.+?)[ \t]*#*[ \t]*$", line)
        if atx:
            label = normalized_heading_text(atx.group(1))
            if label:
                labels.append(label)
        if index > 0 and re.match(r"^[ ]{0,3}=+[ \t]*$", line):
            label = normalized_heading_text(lines[index - 1])
            if label:
                labels.append(label)
    embedded = PackageHTMLInspector()
    try:
        embedded.feed(inspected)
        embedded.close()
    except Exception:
        return labels
    labels.extend(" ".join(value.casefold().split()) for value in embedded.h1_texts)
    return labels


def reviewable_scope_labels(root: Path) -> set[str]:
    """Return canonical draft headings, claim IDs, and claim locations."""

    labels: set[str] = set()
    draft = root / "drafts/final.md"
    if draft.is_file() and not path_uses_symlink(root, draft):
        inspected = strip_code_for_mdx(draft.read_text(encoding="utf-8"))
        for line in inspected.splitlines():
            match = re.match(r"^[ ]{0,3}#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$", line)
            if match:
                label = normalized_heading_text(match.group(1))
                if label:
                    labels.add(label)
    claims_path = root / "claims.jsonl"
    if claims_path.is_file() and not path_uses_symlink(root, claims_path):
        for raw in claims_path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            try:
                claim = strict_json_loads(raw)
            except ValueError:
                continue
            if not isinstance(claim, dict):
                continue
            for field in ("claim_id", "location"):
                value = claim.get(field)
                if isinstance(value, str):
                    normalized = " ".join(unicodedata.normalize("NFKC", value).casefold().split())
                    if normalized:
                        labels.add(normalized)
    return labels


def validate_bound_scope_shape(record: dict[str, Any], label: str, findings: list[dict[str, Any]]) -> None:
    """Validate the closed nested scope objects duplicated in manifest/intake."""

    prefix = label.upper()
    risk = record.get("risk")
    if not isinstance(risk, dict) or set(risk) != {"ymyl", "jurisdiction"}:
        findings.append(finding(f"{prefix}_RISK_SHAPE_INVALID", "P1", f"{label} risk must contain exactly ymyl and jurisdiction"))
    else:
        ymyl = risk.get("ymyl")
        jurisdiction = risk.get("jurisdiction")
        if not (ymyl is True or ymyl is False or ymyl == "auto") or (
            jurisdiction is not None
            and (
                not substantive_string(jurisdiction)
                or contains_forbidden_single_line_control(jurisdiction)
                or contains_placeholder(jurisdiction)
            )
        ):
            findings.append(finding(f"{prefix}_RISK_SHAPE_INVALID", "P1", f"{label} risk values are invalid"))

    role_names = {"writer", "verifier", "editor", "technical_reviewer", "expert_reviewer"}
    roles = record.get("roles")
    if (
        not isinstance(roles, dict)
        or set(roles) != role_names
        or any(value is not None and not substantive_actor_identity(value) for value in roles.values())
    ):
        findings.append(finding(f"{prefix}_ROLES_SHAPE_INVALID", "P1", f"{label} roles must contain exactly the five nullable actor identities"))

    permission_names = {"web_research", "paid_tools", "cms_draft", "publish", "url_change"}
    permissions = record.get("permissions")
    if (
        not isinstance(permissions, dict)
        or set(permissions) != permission_names
        or any(not isinstance(value, bool) for value in permissions.values())
    ):
        findings.append(finding(f"{prefix}_PERMISSIONS_SHAPE_INVALID", "P1", f"{label} permissions must contain exactly the five boolean action boundaries"))

    protected_names = {"reviewed", "rationale", "empty_selection_approved", "headings", "links"}
    protected = record.get("protected")
    protected_invalid = not isinstance(protected, dict) or set(protected) != protected_names
    if isinstance(protected, dict) and not protected_invalid:
        rationale = protected.get("rationale")
        if (
            not isinstance(protected.get("reviewed"), bool)
            or not isinstance(protected.get("empty_selection_approved"), bool)
            or (
                rationale is not None
                and (
                    not substantive_string(rationale)
                    or contains_forbidden_single_line_control(rationale)
                    or contains_placeholder(rationale)
                )
            )
        ):
            protected_invalid = True
        for field in ("headings", "links"):
            values = protected.get(field)
            if (
                not isinstance(values, list)
                or any(
                    not substantive_string(value)
                    or contains_forbidden_single_line_control(value)
                    or contains_placeholder(value)
                    for value in values
                )
            ):
                protected_invalid = True
                continue
            normalized = [unicodedata.normalize("NFKC", value).casefold().strip() for value in values]
            if len(normalized) != len(set(normalized)):
                protected_invalid = True
    if protected_invalid:
        findings.append(finding(f"{prefix}_PROTECTED_SHAPE_INVALID", "P1", f"{label} protected scope must match the closed reviewed/rationale/selection contract"))


def validate_manifest_contract(manifest: dict[str, Any], findings: list[dict[str, Any]]) -> None:
    if contains_forbidden_unicode_control(manifest):
        findings.append(finding("UNICODE_CONTROL_CHARACTER_INVALID", "P1", "Manifest contains a forbidden zero-width, bidi, or surrogate control character"))
    if manifest.get("schema_version") != "0.1":
        findings.append(finding("MANIFEST_SCHEMA_VERSION_INVALID", "P1", "Manifest schema_version must be 0.1"))
    validate_bound_scope_shape(manifest, "manifest", findings)
    field_codes = {
        "run_id": "MANIFEST_RUN_ID_INVALID",
        "target": "MANIFEST_TARGET_INVALID",
        "language": "MANIFEST_LANGUAGE_INVALID",
    }
    for field, minimum in (("run_id", 8), ("target", 1), ("language", 2)):
        value = manifest.get(field)
        if (
            not substantive_string(value, minimum)
            or (field in {"target", "language"} and contains_placeholder(value))
            or (field == "run_id" and RUN_ID.fullmatch(value) is None)
        ):
            findings.append(finding(field_codes[field], "P1", "Manifest field has an invalid type or length", field=field))
    for field in ("locale", "site"):
        value = manifest.get(field)
        if value is not None and (not substantive_string(value) or (field == "locale" and contains_placeholder(value))):
            findings.append(finding("MANIFEST_FIELD_INVALID", "P1", "Manifest optional field must be null or a non-empty string", field=field))
    destination = manifest.get("destination")
    if not isinstance(destination, dict) or set(destination) != {"format", "url", "cms"}:
        findings.append(finding("MANIFEST_DESTINATION_INVALID", "P1", "Manifest destination must contain exactly format, url, and cms"))
    else:
        if destination.get("format") not in {"markdown", "mdx", "html"}:
            findings.append(finding("MANIFEST_DESTINATION_INVALID", "P1", "Destination format must be markdown, mdx, or html", value=destination.get("format")))
        destination_url = destination.get("url")
        if destination_url is not None and not valid_document_url(destination_url):
            findings.append(finding("MANIFEST_DESTINATION_INVALID", "P1", "Destination URL must be null or a canonical fragment-free HTTP(S) document URL", value=destination_url))
        cms = destination.get("cms")
        if cms is not None and (
            not substantive_string(cms)
            or contains_forbidden_single_line_control(cms)
            or contains_placeholder(cms)
        ):
            findings.append(finding("MANIFEST_DESTINATION_INVALID", "P1", "Destination CMS must be null or a substantive single-line label", value=cms))
    if isinstance(manifest.get("site"), str) and not valid_document_url(manifest["site"]):
        findings.append(finding("MANIFEST_SITE_URL_INVALID", "P1", "Manifest site must be a canonical fragment-free HTTP(S) document URL", value=manifest.get("site")))

    risk = manifest.get("risk")
    if not isinstance(risk, dict):
        findings.append(finding("RISK_INVALID", "P0", "Manifest risk must be an object with an explicit YMYL classification"))
    else:
        ymyl = risk.get("ymyl")
        if not (ymyl is True or ymyl is False or ymyl == "auto"):
            findings.append(finding("YMYL_CLASSIFICATION_INVALID", "P0", "risk.ymyl must be true, false, or 'auto'", value=ymyl))
        jurisdiction = risk.get("jurisdiction")
        if jurisdiction is not None and (not substantive_string(jurisdiction) or contains_placeholder(jurisdiction)):
            findings.append(finding("YMYL_JURISDICTION_INVALID", "P1", "risk.jurisdiction must be null or a non-empty string"))
        if ymyl is True and (not substantive_string(jurisdiction) or contains_placeholder(jurisdiction)):
            findings.append(finding("YMYL_JURISDICTION_MISSING", "P0", "YMYL content requires an explicit jurisdiction"))

    permissions = manifest.get("permissions")
    required_permissions = ("web_research", "paid_tools", "cms_draft", "publish", "url_change")
    if not isinstance(permissions, dict) or any(not isinstance(permissions.get(name), bool) for name in required_permissions):
        findings.append(finding("PERMISSIONS_INVALID", "P1", "Manifest permissions must explicitly record boolean research, paid-tool, CMS-draft, publish, and URL-change boundaries"))

    for field in ("created_at", "updated_at"):
        if parse_timestamp(manifest.get(field)) is None:
            findings.append(finding("MANIFEST_TIME_INVALID", "P1", "Manifest timestamp must be timezone-aware", field=field))
    for field in ("warnings", "waivers"):
        value = manifest.get(field)
        if value is not None and not isinstance(value, list):
            findings.append(finding("MANIFEST_FIELD_INVALID", "P1", "Manifest field must be an array", field=field))


def validate_intake_contract(intake: dict[str, Any], manifest: dict[str, Any], findings: list[dict[str, Any]]) -> None:
    """Validate the immutable request/scope record and bind it to this run."""

    required = {
        "schema_version",
        "run_id",
        "mode",
        "target",
        "language",
        "locale",
        "site",
        "risk",
        "roles",
        "protected",
        "destination",
        "requested_status",
        "permissions",
        "audience",
        "reader_job",
        "business_goal",
        "conversion_action",
        "approved_product_facts",
        "constraints",
        "inferences_requiring_confirmation",
    }
    missing = sorted(required - set(intake))
    extra = sorted(set(intake) - required)
    if missing or extra:
        findings.append(finding("INTAKE_FIELDS_INVALID", "P1", "Intake contains missing or unexpected fields", missing=missing, extra=extra))
    if contains_forbidden_unicode_control(intake):
        findings.append(finding("UNICODE_CONTROL_CHARACTER_INVALID", "P1", "Intake contains a forbidden zero-width, bidi, or surrogate control character"))
    validate_bound_scope_shape(intake, "intake", findings)

    identity_fields = (
        "schema_version",
        "run_id",
        "mode",
        "target",
        "language",
        "locale",
        "site",
        "risk",
        "roles",
        "protected",
        "destination",
        "requested_status",
        "permissions",
    )
    mismatches = [field for field in identity_fields if intake.get(field) != manifest.get(field)]
    if mismatches:
        findings.append(finding("INTAKE_IDENTITY_MISMATCH", "P1", "Intake identity and scope do not match the run manifest", fields=mismatches))

    for field in ("target", "language"):
        if not substantive_string(intake.get(field)) or contains_placeholder(intake.get(field)):
            findings.append(finding("INTAKE_TEXT_INVALID", "P1", "Required intake text must contain substantive visible text", field=field))
    for field in ("locale", "site", "audience", "reader_job", "business_goal", "conversion_action"):
        value = intake.get(field)
        if value is not None and (not substantive_string(value) or contains_placeholder(value)):
            findings.append(finding("INTAKE_TEXT_INVALID", "P1", "Optional intake text must be null or contain substantive visible text", field=field))

    for field in ("approved_product_facts", "constraints", "inferences_requiring_confirmation"):
        value = intake.get(field)
        if not isinstance(value, list) or any(not substantive_string(item) or contains_placeholder(item) for item in value):
            findings.append(finding("INTAKE_LIST_INVALID", "P1", "Intake list fields must be arrays of substantive strings", field=field))
            continue
        normalized = [unicodedata.normalize("NFKC", item).casefold().strip() for item in value]
        if len(normalized) != len(set(normalized)):
            findings.append(finding("INTAKE_LIST_DUPLICATE", "P1", "Intake list fields must not contain duplicate values", field=field))


def nonempty_string(value: Any) -> bool:
    return substantive_string(value)


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


def validate_article_reference(
    root: Path,
    article_parent: Path,
    href: str,
    listed_package_paths: set[str],
    findings: list[dict[str, Any]],
) -> None:
    if not isinstance(href, str) or not href.strip():
        findings.append(finding("LINK_URL_INVALID", "P1", "Publish article contains an empty link destination"))
        return
    href = html_unescape(href)
    if contains_forbidden_unicode_control(href):
        findings.append(finding("UNICODE_CONTROL_CHARACTER_INVALID", "P1", "Publish article link contains a forbidden zero-width, bidi, or surrogate control character", href=href))
        return
    if href != href.strip() or any(character.isspace() or unicodedata.category(character) in {"Cc", "Cs"} for character in href):
        findings.append(finding("LINK_URL_INVALID", "P1", "Publish article contains whitespace or control characters in a link destination", href=href))
        return
    if href.startswith("#"):
        return
    try:
        parsed_href = urlparse(href)
    except ValueError:
        findings.append(finding("LINK_URL_INVALID", "P1", "Publish article contains a malformed link", href=href))
        return
    scheme = parsed_href.scheme.casefold()
    if scheme in {"http", "https"}:
        if not valid_http_url(href):
            findings.append(finding("LINK_URL_INVALID", "P1", "Publish article contains a malformed HTTP(S) link", href=href))
        return
    if scheme in {"mailto", "tel"}:
        if not parsed_href.path:
            findings.append(finding("LINK_URL_INVALID", "P1", "Publish article contains an empty mailto or tel destination", href=href))
        return
    if href.startswith("//") or parsed_href.netloc:
        findings.append(finding("LINK_URL_INVALID", "P1", "Publish article must use an explicit HTTP(S) scheme for external hosts", href=href))
        return
    if href.startswith("/"):
        return
    if parsed_href.scheme:
        findings.append(finding("UNSAFE_LINK_SCHEME", "P0", "Publish article contains an unsupported link scheme", href=href, scheme=scheme))
        return
    relative_part = href.split("#", 1)[0].split("?", 1)[0]
    if not relative_part:
        return
    if "\\" in relative_part or "%" in relative_part:
        findings.append(finding("LOCAL_LINK_PATH_INVALID", "P1", "Publish article local link must not use platform-dependent backslashes or percent-encoded path semantics", href=href))
        return
    pure_relative = PurePosixPath(relative_part)
    canonical_relative = pure_relative.as_posix()
    trailing_directory_form = relative_part.endswith("/") and relative_part[:-1] == canonical_relative
    if relative_part != canonical_relative and not trailing_directory_form:
        findings.append(finding("LOCAL_LINK_PATH_INVALID", "P1", "Publish article local link must use canonical POSIX spelling", href=href, canonical=canonical_relative))
        return
    unresolved_target = article_parent / relative_part
    target = unresolved_target.resolve()
    if target != root and root not in target.parents:
        findings.append(finding("LOCAL_LINK_PATH_ESCAPE", "P0", "Publish article local link resolves outside the article run", href=href))
        return
    if path_uses_symlink(root, unresolved_target):
        findings.append(finding("LOCAL_LINK_SYMLINK", "P1", "Publish article local link traverses a symlink", href=href))
        return
    if trailing_directory_form and target.is_file():
        findings.append(finding("LOCAL_LINK_PATH_INVALID", "P1", "Publish article adds a directory slash to a local file", href=href))
        return
    if not target.exists():
        findings.append(finding("LOCAL_LINK_BROKEN", "P1", "Publish article references a missing local file", href=href))
        return
    if target.is_dir():
        findings.append(finding("LOCAL_LINK_DIRECTORY_UNSUPPORTED", "P1", "Portable package links must name a checksum-listed file, not a local directory", href=href))
        return
    package_path = target.relative_to(root).as_posix()
    if package_path not in listed_package_paths:
        findings.append(finding("LOCAL_LINK_UNLISTED", "P1", "Publish article local link is not a checksum-listed deliverable", href=href, path=package_path))


def read_json(
    path: Path,
    findings: list[dict[str, Any]],
    code: str,
    severity: str = "P1",
    expected_type: type | tuple[type, ...] = dict,
) -> Any | None:
    if ACTIVE_ROOT is not None and path_uses_symlink(ACTIVE_ROOT, path):
        findings.append(finding(f"{code}_SYMLINK", "P0", f"Refusing to read {path.name} through a symlink", path=str(path)))
        return None
    if not path.is_file():
        findings.append(finding(f"{code}_MISSING", severity, f"Missing {path.name}", path=str(path)))
        return None
    try:
        payload = strict_json_loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        findings.append(finding(f"{code}_INVALID", severity, f"Invalid JSON in {path.name}", path=str(path), error=str(exc)))
        return None
    if not isinstance(payload, expected_type):
        findings.append(
            finding(
                f"{code}_TYPE_INVALID",
                severity,
                f"{path.name} must contain a {getattr(expected_type, '__name__', 'supported JSON type')}",
                path=str(path),
                actual_type=type(payload).__name__,
            )
        )
        return None
    if contains_forbidden_json_string_control(payload):
        findings.append(
            finding(
                f"{code}_UNICODE_CONTROL_INVALID",
                severity,
                f"{path.name} contains a line, invisible, bidi, surrogate, or other forbidden structured-text character",
                path=str(path),
            )
        )
    return payload


def require_file(root: Path, relative: str, findings: list[dict[str, Any]], severity: str = "P1") -> Path | None:
    path = root / relative
    if path_uses_symlink(root, path):
        findings.append(finding("ARTIFACT_SYMLINK", "P0", "Required artifact traverses a symlink", path=relative))
        return None
    if not path.is_file() or path.stat().st_size == 0:
        findings.append(finding("ARTIFACT_MISSING", severity, "Required artifact is missing or empty", path=relative))
        return None
    return path


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_binding_matches(root: Path, relative: str, claimed_sha256: Any) -> bool:
    """Verify a lowercase SHA-256 binding to one regular in-run file."""

    path = root / relative
    return (
        isinstance(claimed_sha256, str)
        and re.fullmatch(r"[0-9a-f]{64}", claimed_sha256) is not None
        and not path_uses_symlink(root, path)
        and path.is_file()
        and file_sha256(path) == claimed_sha256
    )


def validate_review_binding(
    root: Path,
    manifest: dict[str, Any],
    review: dict[str, Any],
    findings: list[dict[str, Any]],
    *,
    review_type: str,
    required_paths: tuple[str, ...],
    severity: str = "P1",
    time_field: str = "reviewed_at",
) -> datetime | None:
    """Bind an approval to exact run artifacts and its lifecycle timestamp."""

    prefix = review_type.upper().replace("-", "_")
    code_base = "VERIFICATION" if review_type == "verification" else f"{prefix}_REVIEW"
    binding_invalid = False
    if contains_forbidden_unicode_control(review) or contains_forbidden_json_string_control(review):
        findings.append(
            finding(
                f"{code_base}_UNICODE_CONTROL_INVALID",
                severity,
                "Review records cannot contain zero-width, bidi, or surrogate control characters",
            )
        )
        binding_invalid = True

    invalid_human_fields: list[str] = []
    human_minimums = {
        "credentials": 8,
        "scope": 12,
        "destination_scope": 1,
        "jurisdiction": 2,
    }
    if "reviewer" in review and not substantive_actor_identity(review.get("reviewer")):
        invalid_human_fields.append("reviewer")
    for field, minimum in human_minimums.items():
        if field in review and (
            not substantive_string(review.get(field), minimum)
            or contains_placeholder(review.get(field))
        ):
            invalid_human_fields.append(field)
    if "review_required" in review and not isinstance(review.get("review_required"), bool):
        invalid_human_fields.append("review_required")
    if "independence_degraded" in review and not isinstance(review.get("independence_degraded"), bool):
        invalid_human_fields.append("independence_degraded")
    for field in ("reviewed_at", "requested_at"):
        if field in review and parse_timestamp(review.get(field)) is None:
            invalid_human_fields.append(field)
    sections = review.get("sections_reviewed")
    if "sections_reviewed" in review and (
        not isinstance(sections, list)
        or not sections
        or any(not substantive_string(item, 3) or contains_placeholder(item) for item in sections)
        or len(sections) != len(set(sections))
    ):
        invalid_human_fields.append("sections_reviewed")
    claims_requiring_review = review.get("claims_requiring_review")
    if "claims_requiring_review" in review and (
        not isinstance(claims_requiring_review, list)
        or not claims_requiring_review
        or any(not substantive_string(item) or contains_placeholder(item) for item in claims_requiring_review)
        or len(claims_requiring_review) != len(set(claims_requiring_review))
    ):
        invalid_human_fields.append("claims_requiring_review")
    claims_reviewed = review.get("claims_reviewed")
    if "claims_reviewed" in review and (
        not isinstance(claims_reviewed, list)
        or not claims_reviewed
        or any(not valid_identifier(item) or contains_placeholder(item) for item in claims_reviewed)
        or len(claims_reviewed) != len(set(claims_reviewed))
    ):
        invalid_human_fields.append("claims_reviewed")
    if invalid_human_fields:
        findings.append(
            finding(
                f"{code_base}_FIELDS_INVALID",
                severity,
                "Review human-evidence fields must satisfy their typed, substantive, single-line contract",
                fields=sorted(set(invalid_human_fields)),
            )
        )
    if "checks" in review:
        checks = review.get("checks")
        required_observation_names = {
            "single_h1",
            "single_logical_h1",
            "metadata",
            "links",
            "local_links_and_assets",
        }

        def valid_bound_check(item: Any, *, name: Any = None) -> bool:
            if not isinstance(item, dict) or set(item) != {"status", "evidence"}:
                return False
            allow_not_applicable = name not in required_observation_names
            return technical_outcome(item.get("status"), allow_not_applicable=allow_not_applicable) and substantive_evidence(item.get("evidence"))

        checks_valid = False
        if isinstance(checks, dict) and checks:
            normalized_names = [normalized_check_name(name) for name in checks]
            checks_valid = all(
                substantive_string(name)
                and valid_bound_check(item, name=name)
                for name, item in checks.items()
            ) and len(normalized_names) == len(set(normalized_names))
        elif isinstance(checks, list) and checks:
            normalized_names = [normalized_check_name(item.get("check")) for item in checks if isinstance(item, dict)]
            checks_valid = all(
                isinstance(item, dict)
                and set(item) == {"check", "status", "evidence"}
                and substantive_string(item.get("check"))
                and valid_bound_check(
                    {"status": item.get("status"), "evidence": item.get("evidence")},
                    name=item.get("check"),
                )
                for item in checks
            ) and len(normalized_names) == len(checks) and len(normalized_names) == len(set(normalized_names))
        if not checks_valid:
            findings.append(
                finding(
                    f"{code_base}_CHECKS_INVALID",
                    severity,
                    "Review checks must be a non-empty typed map or list with acceptable outcomes and substantive evidence",
                )
            )
    if review.get("contract_version") != REVIEW_BINDING_VERSION or review.get("review_type") != review_type:
        binding_invalid = True
    if review.get("run_id") != manifest.get("run_id"):
        binding_invalid = True
    hashes = review.get("artifact_hashes")
    if not isinstance(hashes, dict) or set(hashes) != set(required_paths):
        binding_invalid = True
    else:
        for relative in required_paths:
            expected = hashes.get(relative)
            candidate = root / relative
            if (
                not isinstance(expected, str)
                or re.fullmatch(r"[0-9a-f]{64}", expected) is None
                or path_uses_symlink(root, candidate)
                or not candidate.is_file()
                or file_sha256(candidate) != expected
            ):
                binding_invalid = True
                break
    if binding_invalid:
        findings.append(
            finding(
                f"{code_base}_BINDING_MISSING",
                severity,
                "Review approval is not bound to the current run and exact reviewed artifact bytes",
                required_paths=list(required_paths),
            )
        )

    review_findings = review.get("findings")
    if not isinstance(review_findings, list):
        findings.append(finding(f"{code_base}_FINDINGS_INVALID", severity, "Machine-gating reviews must include a findings array"))
    else:
        malformed: list[int] = []
        unresolved: list[int] = []
        for index, item in enumerate(review_findings):
            if (
                not isinstance(item, dict)
                or item.get("severity") not in {"P0", "P1", "P2", "P3"}
                or not substantive_string(item.get("message"))
                or item.get("resolution") not in {"open", "resolved"}
            ):
                malformed.append(index)
                if review.get("status") in {"passed", "approved"}:
                    unresolved.append(index)
                continue
            item_severity = item.get("severity")
            resolution = item.get("resolution")
            if review.get("status") in {"passed", "approved"} and item_severity in {"P0", "P1"} and resolution != "resolved":
                unresolved.append(index)
        if malformed:
            findings.append(
                finding(
                    f"{code_base}_FINDINGS_INVALID",
                    severity,
                    "Every review finding requires a valid severity, substantive message, and open or resolved state",
                    indexes=malformed,
                )
            )
        if unresolved:
            findings.append(
                finding(
                    f"{code_base}_UNRESOLVED_FINDINGS",
                    severity,
                    "A passed or approved review cannot retain unresolved P0/P1 findings",
                    indexes=unresolved,
                )
            )

    reviewed_at = parse_timestamp(review.get(time_field))
    if reviewed_at is None:
        findings.append(finding(f"{code_base}_TIME_INVALID", severity, "Review requires a timezone-aware lifecycle timestamp", field=time_field))
        return None
    if timestamp_is_future(review.get(time_field)):
        findings.append(finding(f"{code_base}_TIME_FUTURE", severity, "Review timestamp cannot be materially future-dated"))
    created_at = parse_timestamp(manifest.get("created_at"))
    updated_at = parse_timestamp(manifest.get("updated_at"))
    if created_at is not None and reviewed_at < created_at:
        findings.append(finding(f"{code_base}_TIME_PRECEDES_RUN", severity, "Review timestamp predates the article run"))
    if updated_at is not None and reviewed_at > updated_at:
        findings.append(finding(f"{code_base}_TIME_AFTER_RUN_UPDATE", severity, "Review timestamp is later than manifest.updated_at"))
    return reviewed_at


def child_validator(script: Path, root: Path, *extra_args: str) -> tuple[int, dict[str, Any]]:
    if not script.is_file():
        return 2, {"validator": script.stem, "status": "unavailable", "findings": [finding("VALIDATOR_MISSING", "P1", "Validator script is missing", path=str(script))]}
    result = subprocess.run(
        [sys.executable, str(script), str(root), *extra_args],
        check=False,
        capture_output=True,
        text=True,
    )
    try:
        payload = strict_json_loads(result.stdout)
    except ValueError:
        payload = {
            "validator": script.stem,
            "status": "unavailable",
            "findings": [finding("VALIDATOR_OUTPUT_INVALID", "P1", "Validator did not return JSON", stderr=result.stderr[-1000:])],
        }
        return 2, payload
    return result.returncode, payload


def validate_serp(path: Path, findings: list[dict[str, Any]], *, web_research_allowed: bool) -> None:
    payload = read_json(path, findings, "SERP")
    if not isinstance(payload, dict):
        return
    required = ("query", "captured_at", "locale", "device", "status", "acquisition")
    missing = [field for field in required if not substantive_string(payload.get(field))]
    if missing:
        findings.append(finding("SERP_FIELDS_MISSING", "P1", "SERP snapshot is incomplete", fields=missing))
    if payload.get("status") != "captured":
        findings.append(finding("SERP_NOT_CAPTURED", "P1", "Current SERP evidence was not captured", status=payload.get("status")))
    acquisition = payload.get("acquisition")
    if acquisition not in RESEARCH_ACQUISITIONS:
        findings.append(finding("SERP_ACQUISITION_INVALID", "P1", "SERP snapshot must declare agent-web or user-provided acquisition"))
    elif acquisition == "agent-web" and not web_research_allowed:
        findings.append(finding("WEB_RESEARCH_UNAUTHORIZED", "P0", "Agent-acquired SERP evidence contradicts permissions.web_research=false"))
    captured_at = parse_timestamp(payload.get("captured_at"))
    if captured_at is None:
        findings.append(finding("SERP_CAPTURE_TIME_INVALID", "P1", "SERP captured_at must be a timezone-aware timestamp"))
    elif timestamp_is_future(payload.get("captured_at")):
        findings.append(finding("SERP_CAPTURE_TIME_FUTURE", "P1", "SERP captured_at cannot be materially future-dated"))
    elif datetime.now(timezone.utc) - captured_at > SERP_MAX_AGE:
        findings.append(finding("SERP_CAPTURE_STALE", "P1", "Content-ready SERP evidence must be no more than 31 days old", captured_at=payload.get("captured_at")))
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        findings.append(finding("SERP_RESULTS_EMPTY", "P1", "SERP snapshot has no opened result records"))
        return
    for index, result in enumerate(results):
        if not isinstance(result, dict):
            findings.append(finding("SERP_RESULT_INVALID", "P1", "SERP result must be an object", index=index))
            continue
        if contains_forbidden_unicode_control(result.get("url")):
            findings.append(finding("UNICODE_CONTROL_CHARACTER_INVALID", "P1", "SERP result URL contains a forbidden zero-width, bidi, or surrogate control character", index=index))
        if not valid_http_url(result.get("url")):
            findings.append(finding("SERP_RESULT_URL_INVALID", "P1", "SERP result lacks a valid absolute HTTP(S) URL", index=index, value=result.get("url")))
        if result.get("opened") is not True:
            findings.append(finding("SERP_RESULT_NOT_OPENED", "P1", "SERP result was not opened and inspected", index=index, opened=result.get("opened")))


def draft_heading_labels(root: Path) -> set[str]:
    """Return reader-visible Markdown headings from the final draft."""

    draft = root / "drafts/final.md"
    if not draft.is_file() or path_uses_symlink(root, draft):
        return set()
    labels: set[str] = set()
    inspected = strip_code_for_mdx(draft.read_text(encoding="utf-8"))
    for line in inspected.splitlines():
        match = re.match(r"^[ ]{0,3}#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$", line)
        if match:
            label = normalized_heading_text(match.group(1))
            if label:
                labels.add(label)
    return labels


def validate_quality_gate(root: Path, manifest: dict[str, Any], findings: list[dict[str, Any]]) -> None:
    """Require a reviewable reader-value assessment before content-ready status.

    This intentionally validates the *evidence shape*, not a universal writing
    score. The independent editor remains responsible for judging usefulness.
    """

    payload = read_json(root / "research/quality-gate.json", findings, "QUALITY_GATE")
    if not isinstance(payload, dict):
        return
    required = {
        "contract_version",
        "run_id",
        "operating_depth",
        "competitive_standard",
        "serp_assessment",
        "reader_path",
        "article_shape",
        "information_gain",
        "reader_advantage",
        "visual_data_decision",
    }
    if set(payload) != required:
        findings.append(finding("QUALITY_GATE_FIELDS_INVALID", "P1", "Quality gate fields do not match article-quality-gate-v2"))
    if payload.get("contract_version") != QUALITY_GATE_VERSION or payload.get("run_id") != manifest.get("run_id"):
        findings.append(finding("QUALITY_GATE_IDENTITY_INVALID", "P1", "Quality gate does not bind to this run and contract version"))

    depth = payload.get("operating_depth")
    if depth not in {"lite", "full"}:
        findings.append(finding("QUALITY_GATE_DEPTH_INVALID", "P1", "operating_depth must be lite or full"))

    serp = payload.get("serp_assessment")
    expected_serp = {"status", "relevant_results", "limitation"}
    if not isinstance(serp, dict) or set(serp) != expected_serp:
        findings.append(finding("QUALITY_SERP_ASSESSMENT_INVALID", "P1", "Quality gate must record SERP status, relevant results, and limitation"))
        serp = {}
    serp_status = serp.get("status")
    relevant_results = serp.get("relevant_results")
    if serp_status not in {"adequate", "sparse"}:
        findings.append(finding("QUALITY_SERP_STATUS_INVALID", "P1", "SERP assessment status must be adequate or sparse"))
    if not substantive_evidence(serp.get("limitation")):
        findings.append(finding("QUALITY_SERP_LIMITATION_INVALID", "P1", "SERP assessment must state a substantive evidence limitation"))
    if not isinstance(relevant_results, list) or not relevant_results:
        findings.append(finding("QUALITY_SERP_RESULTS_INVALID", "P1", "Quality gate requires at least one opened relevant SERP result"))
        relevant_results = []

    serp_payload = quiet_json_object(root / "research/serp.json")
    opened_urls = {
        result.get("url")
        for result in (serp_payload or {}).get("results", [])
        if isinstance(result, dict) and result.get("opened") is True and isinstance(result.get("url"), str)
    }
    seen_urls: set[str] = set()
    seen_positions: set[int] = set()
    expected_result = {"url", "position", "format", "reader_job", "main_content_words", "word_count_method", "gap"}
    for index, result in enumerate(relevant_results):
        if not isinstance(result, dict) or set(result) != expected_result:
            findings.append(finding("QUALITY_SERP_RESULT_INVALID", "P1", "Each quality SERP result must contain the required comparable observations", index=index))
            continue
        url = result.get("url")
        position = result.get("position")
        if not valid_http_url(url) or url not in opened_urls or url in seen_urls:
            findings.append(finding("QUALITY_SERP_RESULT_URL_INVALID", "P1", "Quality SERP results must reference unique opened snapshot URLs", index=index, url=url))
        if isinstance(url, str):
            seen_urls.add(url)
        if isinstance(position, bool) or not isinstance(position, int) or position < 1 or position in seen_positions:
            findings.append(finding("QUALITY_SERP_RESULT_POSITION_INVALID", "P1", "Quality SERP positions must be unique positive integers", index=index, position=position))
        elif isinstance(position, int):
            seen_positions.add(position)
        if isinstance(result.get("main_content_words"), bool) or not isinstance(result.get("main_content_words"), int) or result.get("main_content_words") < 1:
            findings.append(finding("QUALITY_SERP_RESULT_LENGTH_INVALID", "P1", "Each quality SERP result needs a positive main-content word count", index=index))
        for field in ("format", "reader_job", "word_count_method", "gap"):
            if not substantive_evidence(result.get(field)):
                findings.append(finding("QUALITY_SERP_RESULT_OBSERVATION_INVALID", "P1", "Each quality SERP result needs substantive format, reader-job, length-method, and gap observations", index=index, field=field))
    if depth == "full" and len(relevant_results) < 5:
        findings.append(finding("QUALITY_SERP_COVERAGE_INSUFFICIENT", "P1", "Full articles require five or more opened relevant SERP pages or a lower delivery status", observed=len(relevant_results)))
    if depth == "full" and serp_status != "adequate":
        findings.append(finding("QUALITY_SERP_COVERAGE_SPARSE", "P1", "A Full article with sparse SERP coverage remains draft-only until broader relevant research is captured"))

    headings = draft_heading_labels(root)
    all_claim_ids, _ = claim_scope_ids(root / "claims.jsonl")
    source_types: dict[str, str] = {}
    sources_path = root / "research/sources.jsonl"
    if sources_path.is_file() and not path_uses_symlink(root, sources_path):
        for raw in sources_path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            try:
                source = strict_json_loads(raw)
            except ValueError:
                continue
            if isinstance(source, dict) and valid_identifier(source.get("source_id")) and isinstance(source.get("source_type"), str):
                source_types[source["source_id"]] = source["source_type"]

    competitive_standard = payload.get("competitive_standard")
    if competitive_standard not in {"standard", "serp-competitive"}:
        findings.append(finding("QUALITY_COMPETITIVE_STANDARD_INVALID", "P1", "competitive_standard must be standard or serp-competitive"))
    elif depth == "full" and competitive_standard != "serp-competitive":
        findings.append(finding("QUALITY_FULL_COMPETITIVE_STANDARD_REQUIRED", "P1", "Full work must use the serp-competitive standard or be reduced to Lite scope"))

    reader_path = payload.get("reader_path")
    expected_reader_path = {"primary_job", "direct_answer_heading", "decision_criteria", "not_for_reader"}
    if not isinstance(reader_path, dict) or set(reader_path) != expected_reader_path:
        findings.append(finding("QUALITY_READER_PATH_INVALID", "P1", "Quality gate must define the reader job, direct answer, criteria, and exclusions"))
        reader_path = {}
    if not substantive_evidence(reader_path.get("primary_job")):
        findings.append(finding("QUALITY_READER_JOB_INVALID", "P1", "Quality gate primary_job must be substantive"))
    answer_heading = reader_path.get("direct_answer_heading")
    if not substantive_string(answer_heading) or " ".join(answer_heading.casefold().split()) not in headings:
        findings.append(finding("QUALITY_DIRECT_ANSWER_MISSING", "P1", "Quality gate direct answer must point to a real final-draft heading", heading=answer_heading))
    criteria = reader_path.get("decision_criteria")
    if not isinstance(criteria, list) or not criteria:
        findings.append(finding("QUALITY_DECISION_CRITERIA_INVALID", "P1", "Quality gate requires one or more decision criteria"))
        criteria = []
    article_shape = payload.get("article_shape")
    expected_shape = {"format", "sections", "word_count", "word_count_method", "serp_length_context"}
    if not isinstance(article_shape, dict) or set(article_shape) != expected_shape:
        findings.append(finding("QUALITY_ARTICLE_SHAPE_INVALID", "P1", "Quality gate must record the article format, sections, and contextual length evidence"))
        article_shape = {}
    article_format = article_shape.get("format")
    if article_format not in QUALITY_FORMATS:
        findings.append(finding("QUALITY_ARTICLE_FORMAT_INVALID", "P1", "Quality gate article format is unsupported"))
    if article_format == "comparison" and len(criteria) < 2:
        findings.append(finding("QUALITY_COMPARISON_CRITERIA_INSUFFICIENT", "P1", "A comparison requires at least two reader decision criteria"))
    for index, criterion in enumerate(criteria):
        expected_criterion = {"criterion", "reader_consequence", "evidence_basis", "claim_ids"}
        if not isinstance(criterion, dict) or set(criterion) != expected_criterion:
            findings.append(finding("QUALITY_DECISION_CRITERION_INVALID", "P1", "Decision criteria require criterion, consequence, evidence basis, and claim IDs", index=index))
            continue
        for field in ("criterion", "reader_consequence", "evidence_basis"):
            if not substantive_evidence(criterion.get(field)):
                findings.append(finding("QUALITY_DECISION_CRITERION_INVALID", "P1", "Decision criterion observation is not substantive", index=index, field=field))
        claim_ids = criterion.get("claim_ids")
        if not isinstance(claim_ids, list) or not claim_ids or any(not valid_identifier(item) for item in claim_ids) or not set(claim_ids).issubset(all_claim_ids):
            findings.append(finding("QUALITY_DECISION_CRITERION_CLAIMS_INVALID", "P1", "Decision criteria must cite existing claim IDs", index=index))
    exclusions = reader_path.get("not_for_reader")
    if not isinstance(exclusions, list) or not exclusions or any(not substantive_evidence(item) for item in exclusions):
        findings.append(finding("QUALITY_READER_EXCLUSIONS_INVALID", "P1", "Quality gate must name substantive not-for-reader cases"))

    sections = article_shape.get("sections")
    if not isinstance(sections, list) or not sections:
        findings.append(finding("QUALITY_SECTION_COVERAGE_INVALID", "P1", "Quality gate must map material sections to reader needs and evidence"))
        sections = []
    for index, section in enumerate(sections):
        expected_section = {"reader_need", "heading", "evidence_basis", "claim_ids"}
        if not isinstance(section, dict) or set(section) != expected_section:
            findings.append(finding("QUALITY_SECTION_INVALID", "P1", "Each quality section must map reader need, heading, evidence basis, and claims", index=index))
            continue
        for field in ("reader_need", "evidence_basis"):
            if not substantive_evidence(section.get(field)):
                findings.append(finding("QUALITY_SECTION_INVALID", "P1", "Section mapping is not substantive", index=index, field=field))
        heading = section.get("heading")
        if not substantive_string(heading) or " ".join(heading.casefold().split()) not in headings:
            findings.append(finding("QUALITY_SECTION_HEADING_MISSING", "P1", "Section mapping must point to a real final-draft heading", index=index, heading=heading))
        claim_ids = section.get("claim_ids")
        if not isinstance(claim_ids, list) or not claim_ids or any(not valid_identifier(item) for item in claim_ids) or not set(claim_ids).issubset(all_claim_ids):
            findings.append(finding("QUALITY_SECTION_CLAIMS_INVALID", "P1", "Section mappings must cite existing claim IDs", index=index))
    word_count = article_shape.get("word_count")
    if isinstance(word_count, bool) or not isinstance(word_count, int) or word_count < 1:
        findings.append(finding("QUALITY_ARTICLE_LENGTH_INVALID", "P1", "Quality gate requires a positive observed article word count"))
    for field in ("word_count_method", "serp_length_context"):
        if not substantive_evidence(article_shape.get(field)):
            findings.append(finding("QUALITY_ARTICLE_LENGTH_CONTEXT_INVALID", "P1", "Quality gate must explain article-length evidence without a fixed word-count target", field=field))

    information_gain = payload.get("information_gain")
    if not isinstance(information_gain, dict) or set(information_gain) != {"items"} or not isinstance(information_gain.get("items"), list) or not information_gain.get("items"):
        findings.append(finding("QUALITY_INFORMATION_GAIN_INVALID", "P1", "Quality gate requires one or more concrete information-gain items"))
    else:
        for index, item in enumerate(information_gain["items"]):
            expected_item = {"reader_outcome", "article_heading", "evidence_basis"}
            if not isinstance(item, dict) or set(item) != expected_item:
                findings.append(finding("QUALITY_INFORMATION_GAIN_ITEM_INVALID", "P1", "Information-gain items must name outcome, heading, and evidence basis", index=index))
                continue
            if not all(substantive_evidence(item.get(field)) for field in ("reader_outcome", "evidence_basis")):
                findings.append(finding("QUALITY_INFORMATION_GAIN_ITEM_INVALID", "P1", "Information-gain item is not substantive", index=index))
            heading = item.get("article_heading")
            if not substantive_string(heading) or " ".join(heading.casefold().split()) not in headings:
                findings.append(finding("QUALITY_INFORMATION_GAIN_HEADING_MISSING", "P1", "Information gain must point to a real final-draft heading", index=index, heading=heading))

    advantage = payload.get("reader_advantage")
    expected_advantage = {"status", "kind", "reader_problem", "article_heading", "method", "evidence_source_ids", "claim_ids", "limitation"}
    if not isinstance(advantage, dict) or set(advantage) != expected_advantage:
        findings.append(finding("QUALITY_READER_ADVANTAGE_INVALID", "P1", "Quality gate must describe the reader advantage and its evidence"))
        advantage = {}
    advantage_status = advantage.get("status")
    advantage_kind = advantage.get("kind")
    if advantage_status not in {"demonstrated", "not-demonstrated"}:
        findings.append(finding("QUALITY_READER_ADVANTAGE_STATUS_INVALID", "P1", "reader_advantage.status must be demonstrated or not-demonstrated"))
    if advantage_kind not in COMPETITIVE_ADVANTAGE_KINDS:
        findings.append(finding("QUALITY_READER_ADVANTAGE_KIND_INVALID", "P1", "reader_advantage.kind is unsupported"))
    if not substantive_evidence(advantage.get("reader_problem")) or not substantive_evidence(advantage.get("limitation")):
        findings.append(finding("QUALITY_READER_ADVANTAGE_CONTEXT_INVALID", "P1", "reader_advantage needs a substantive reader problem and limitation"))
    advantage_heading = advantage.get("article_heading")
    if not substantive_string(advantage_heading) or " ".join(advantage_heading.casefold().split()) not in headings:
        findings.append(finding("QUALITY_READER_ADVANTAGE_HEADING_MISSING", "P1", "reader_advantage must point to a real final-draft heading", heading=advantage_heading))
    source_ids = advantage.get("evidence_source_ids")
    claim_ids = advantage.get("claim_ids")
    source_ids_valid = isinstance(source_ids, list) and all(valid_identifier(item) for item in source_ids) and len(source_ids) == len(set(source_ids))
    claim_ids_valid = isinstance(claim_ids, list) and all(valid_identifier(item) for item in claim_ids) and len(claim_ids) == len(set(claim_ids))
    if not source_ids_valid or not claim_ids_valid:
        findings.append(finding("QUALITY_READER_ADVANTAGE_REFERENCES_INVALID", "P1", "reader_advantage source and claim IDs must be unique valid identifiers"))

    demonstrated = advantage_status == "demonstrated"
    if demonstrated:
        if advantage_kind == "none":
            findings.append(finding("QUALITY_READER_ADVANTAGE_CONTRADICTION", "P1", "A demonstrated reader advantage cannot use kind none"))
        if not substantive_evidence(advantage.get("method")):
            findings.append(finding("QUALITY_READER_ADVANTAGE_METHOD_INVALID", "P1", "A demonstrated reader advantage needs a reproducible method or provenance statement"))
        if not source_ids or not claim_ids or not set(source_ids).issubset(source_types) or not set(claim_ids).issubset(all_claim_ids):
            findings.append(finding("QUALITY_READER_ADVANTAGE_EVIDENCE_INVALID", "P1", "A demonstrated reader advantage must bind existing sources and claims"))
        if advantage_kind in EMPIRICAL_ADVANTAGE_KINDS:
            unsupported_sources = sorted(source_id for source_id in source_ids or [] if source_types.get(source_id) not in ORIGINAL_EVIDENCE_SOURCE_TYPES)
            if unsupported_sources:
                findings.append(finding("QUALITY_READER_ADVANTAGE_SOURCE_INVALID", "P1", "Original tests, data, or expert input require primary, first-party, or user-provided evidence", source_ids=unsupported_sources))
        if article_format == "comparison" and advantage_kind == "reader-tool":
            findings.append(finding("QUALITY_COMPARISON_EMPIRICAL_ADVANTAGE_REQUIRED", "P1", "A SERP-competitive comparison needs original test, data, or expert input; a generic decision tool alone is insufficient"))
    else:
        if advantage_kind != "none" or source_ids or claim_ids or substantive_evidence(advantage.get("method")):
            findings.append(finding("QUALITY_READER_ADVANTAGE_CONTRADICTION", "P1", "A non-demonstrated reader advantage must use kind none with empty evidence and method"))

    if competitive_standard == "serp-competitive" and not demonstrated:
        findings.append(finding("QUALITY_COMPETITIVE_ADVANTAGE_REQUIRED", "P1", "A SERP-competitive article needs demonstrated reader value beyond a sourced summary"))
    if competitive_standard == "serp-competitive" and article_format == "comparison" and advantage_kind not in EMPIRICAL_ADVANTAGE_KINDS:
        findings.append(finding("QUALITY_COMPARISON_EMPIRICAL_ADVANTAGE_REQUIRED", "P1", "A SERP-competitive comparison needs original test, data, or expert input tied to the decision"))

    visual = payload.get("visual_data_decision")
    expected_visual = {"decision", "rationale", "article_headings"}
    if not isinstance(visual, dict) or set(visual) != expected_visual:
        findings.append(finding("QUALITY_VISUAL_DECISION_INVALID", "P1", "Quality gate must record whether visual or data media helps the reader"))
        visual = {}
    if visual.get("decision") not in {"none", "table", "screenshot", "chart", "diagram", "mixed"}:
        findings.append(finding("QUALITY_VISUAL_DECISION_INVALID", "P1", "Visual/data decision is unsupported"))
    if not substantive_evidence(visual.get("rationale")):
        findings.append(finding("QUALITY_VISUAL_RATIONALE_INVALID", "P1", "Visual/data decision needs a substantive rationale"))
    visual_headings = visual.get("article_headings")
    if not isinstance(visual_headings, list) or not visual_headings or any(not isinstance(item, str) or " ".join(item.casefold().split()) not in headings for item in visual_headings):
        findings.append(finding("QUALITY_VISUAL_HEADINGS_INVALID", "P1", "Visual/data decision must point to one or more real final-draft headings"))


def validate_handoff(root: Path, manifest: dict[str, Any], findings: list[dict[str, Any]]) -> None:
    """Keep the human handoff's delivery status synchronized with the manifest."""

    handoff = require_file(root, "handoff.md", findings)
    if handoff is None:
        return
    try:
        lines = handoff.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return
    status_line = next((line.strip() for line in lines if line.strip().casefold().startswith("status:")), None)
    if status_line is None:
        findings.append(finding("HANDOFF_STATUS_MISSING", "P1", "Handoff must contain a Status: line"))
        return
    stated = status_line.split(":", 1)[1].strip()
    if stated != manifest.get("actual_status"):
        findings.append(finding("HANDOFF_STATUS_MISMATCH", "P1", "Handoff status must exactly match manifest.actual_status", handoff_status=stated, actual_status=manifest.get("actual_status")))


def validate_editorial_quality_checks(editorial: dict[str, Any], findings: list[dict[str, Any]]) -> None:
    """Require the editor to assess reader value, not merely state a pass."""

    checks = editorial.get("checks")
    if not isinstance(checks, dict):
        findings.append(finding("EDITORIAL_QUALITY_CHECKS_INCOMPLETE", "P1", "Editorial review must record all six reader-value checks"))
        return
    normalized = {normalized_check_name(name): value for name, value in checks.items()}
    missing = sorted(EDITORIAL_QUALITY_CHECKS - set(normalized))
    if missing:
        findings.append(finding("EDITORIAL_QUALITY_CHECKS_INCOMPLETE", "P1", "Editorial review is missing required reader-value checks", checks=missing))
    for name in EDITORIAL_QUALITY_CHECKS & set(normalized):
        check = normalized[name]
        if not isinstance(check, dict) or check.get("status") != "passed" or not substantive_evidence(check.get("evidence"), 20):
            findings.append(finding("EDITORIAL_QUALITY_CHECK_INVALID", "P1", "Editorial reader-value checks require a passed outcome and substantive evidence", check=name))


def validate_source_acquisition_permissions(path: Path, web_research_allowed: bool, findings: list[dict[str, Any]]) -> None:
    """Enforce the web-research permission against each source acquisition."""

    if not path.is_file() or path_uses_symlink(path.parent.parent, path):
        return
    agent_sources: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return
    for raw in lines:
        if not raw.strip():
            continue
        try:
            source = strict_json_loads(raw)
        except ValueError:
            continue
        if not isinstance(source, dict):
            continue
        acquisition = source.get("acquisition")
        if acquisition not in RESEARCH_ACQUISITIONS:
            findings.append(finding("SOURCE_ACQUISITION_INVALID", "P1", "Every source must declare agent-web or user-provided acquisition", source_id=source.get("source_id")))
        elif acquisition == "agent-web" and not web_research_allowed:
            agent_sources.append(str(source.get("source_id", "unknown")))
    if agent_sources:
        findings.append(finding("WEB_RESEARCH_UNAUTHORIZED", "P0", "Agent-acquired source evidence contradicts permissions.web_research=false", source_ids=sorted(agent_sources)))


def validate_capabilities(
    path: Path,
    findings: list[dict[str, Any]],
    *,
    manifest: dict[str, Any],
    paid_tools_allowed: bool,
) -> dict[str, Any] | None:
    payload = read_json(path, findings, "CAPABILITIES")
    if not isinstance(payload, dict):
        return None
    if contains_forbidden_unicode_control(payload) or contains_forbidden_json_string_control(payload):
        findings.append(
            finding(
                "CAPABILITY_UNICODE_CONTROL_INVALID",
                "P1",
                "Capability records cannot contain zero-width, bidi, or surrogate control characters",
            )
        )
    required = ("schema_version", "checked_at", "generated_by", "policy", "capabilities", "limitations", "summary")
    missing = [field for field in required if field not in payload]
    if missing:
        findings.append(finding("CAPABILITY_FIELDS_MISSING", "P1", "Capability report is incomplete", fields=missing))
    if set(payload) != set(required):
        findings.append(finding("CAPABILITY_TOP_LEVEL_FIELDS_INVALID", "P1", "Capability report contains missing or unexpected top-level fields"))
    if payload.get("schema_version") != "0.1" or payload.get("generated_by") != "capability_preflight.py":
        findings.append(finding("CAPABILITY_PROVENANCE_INVALID", "P1", "Capability report has unsupported provenance", schema_version=payload.get("schema_version"), generated_by=payload.get("generated_by")))
    checked_at = parse_timestamp(payload.get("checked_at"))
    if checked_at is None:
        findings.append(finding("CAPABILITY_CHECK_TIME_INVALID", "P1", "Capability checked_at must be a timezone-aware timestamp"))
    elif timestamp_is_future(payload.get("checked_at")):
        findings.append(finding("CAPABILITY_CHECK_TIME_FUTURE", "P1", "Capability checked_at cannot be materially future-dated"))
    else:
        run_created = parse_timestamp(manifest.get("created_at"))
        run_updated = parse_timestamp(manifest.get("updated_at"))
        stale_reasons: list[str] = []
        if run_created is not None and checked_at < run_created:
            stale_reasons.append("predates-run")
        if run_updated is not None and checked_at > run_updated:
            stale_reasons.append("postdates-run-update")
        if datetime.now(timezone.utc) - checked_at > CAPABILITY_MAX_AGE:
            stale_reasons.append("older-than-31-days")
        if stale_reasons:
            findings.append(
                finding(
                    "CAPABILITY_CHECK_TIME_STALE",
                    "P1",
                    "Capability preflight must belong to the current run and be refreshed at least every 31 days",
                    reasons=stale_reasons,
                    checked_at=payload.get("checked_at"),
                )
            )

    expected_policy = {
        "network_calls_made": False,
        "secret_values_emitted": False,
        "paid_use_requires_explicit_approval": True,
        "unknown_cost_requires_explicit_approval": True,
    }
    if payload.get("policy") != expected_policy:
        findings.append(finding("CAPABILITY_POLICY_INVALID", "P1", "Capability safety policy does not match the v0.1 preflight contract"))

    capabilities = payload.get("capabilities")
    if not isinstance(capabilities, dict):
        findings.append(finding("CAPABILITY_MAP_INVALID", "P1", "Capability report has no capability map"))
        return payload
    absent = sorted(CAPABILITY_NAMES - set(capabilities))
    extra = sorted(set(capabilities) - CAPABILITY_NAMES)
    if absent or extra:
        findings.append(finding("CAPABILITY_SET_INVALID", "P1", "Capability report does not match the v0.1 capability set", absent=absent, extra=extra))

    valid_states: dict[str, dict[str, Any]] = {}
    for name in CAPABILITY_ORDER:
        state = capabilities.get(name)
        if not isinstance(state, dict):
            findings.append(finding("CAPABILITY_STATE_INVALID", "P1", "Capability state must be an object", capability=name))
            continue
        required_state = ("status", "selected_provider", "selected_by", "candidate", "reason_code", "absence_effect")
        missing_state = [field for field in required_state if field not in state]
        if missing_state:
            findings.append(finding("CAPABILITY_STATE_FIELDS_MISSING", "P1", "Capability state is incomplete", capability=name, fields=missing_state))
        if set(state) != set(required_state):
            findings.append(finding("CAPABILITY_STATE_FIELDS_INVALID", "P1", "Capability state contains missing or unexpected fields", capability=name))
        status = state.get("status")
        if status not in CAPABILITY_STATES:
            findings.append(finding("CAPABILITY_STATUS_INVALID", "P1", "Capability has an invalid state", capability=name))
            continue
        valid_states[name] = state

        if not substantive_string(state.get("absence_effect"), 12):
            findings.append(finding("CAPABILITY_ABSENCE_EFFECT_MISSING", "P1", "Capability state lacks a usable absence effect", capability=name))
        elif state.get("absence_effect") != CANONICAL_ABSENCE_EFFECTS[name]:
            findings.append(
                finding(
                    "CAPABILITY_ABSENCE_EFFECT_INVALID",
                    "P1",
                    "Capability absence effects are fixed contract text and cannot be replaced by a weaker disclosure",
                    capability=name,
                )
            )

        candidate = state.get("candidate")
        if not isinstance(candidate, dict):
            findings.append(finding("CAPABILITY_CANDIDATE_INVALID", "P1", "Capability candidate must be an object", capability=name))
            continue
        if set(candidate) != {"provider", "probe", "cost"}:
            findings.append(finding("CAPABILITY_CANDIDATE_FIELDS_INVALID", "P1", "Capability candidate fields do not match the contract", capability=name))
        provider = candidate.get("provider")
        probe = candidate.get("probe")
        cost = candidate.get("cost")
        if not isinstance(probe, dict) or not isinstance(cost, dict):
            findings.append(finding("CAPABILITY_PROBE_OR_COST_INVALID", "P1", "Capability candidate requires probe and cost objects", capability=name))
            continue

        probe_kind = probe.get("kind")
        references = probe.get("references")
        present = probe.get("present")
        present_count = probe.get("present_count")
        required_count = probe.get("required_count")
        if set(probe) != {"kind", "references", "present", "present_count", "required_count"}:
            findings.append(finding("CAPABILITY_PROBE_FIELDS_INVALID", "P1", "Capability probe contains missing or unexpected fields", capability=name))
        if probe_kind not in {"none", "explicit-flag", "environment", "file"}:
            findings.append(finding("CAPABILITY_PROBE_KIND_INVALID", "P1", "Capability probe kind is invalid", capability=name, value=probe_kind))
        if not isinstance(references, list) or any(
            not isinstance(item, str) or not item or contains_forbidden_single_line_control(item)
            for item in references
        ):
            findings.append(finding("CAPABILITY_PROBE_REFERENCES_INVALID", "P1", "Capability probe references are invalid", capability=name))
            references = []
        elif len(references) != len(set(references)):
            findings.append(finding("CAPABILITY_PROBE_REFERENCES_INVALID", "P1", "Capability probe references must be unique", capability=name))
        elif probe_kind == "environment" and any(ENV_NAME.fullmatch(item) is None for item in references):
            findings.append(finding("CAPABILITY_ENV_REFERENCE_INVALID", "P1", "Environment probes may record variable names only, never values", capability=name))
        elif probe_kind == "file" and any(
            not Path(item).expanduser().is_absolute()
            or str(Path(item).expanduser().resolve(strict=False)) != item
            for item in references
        ):
            findings.append(
                finding(
                    "CAPABILITY_EXPORT_REFERENCE_INVALID",
                    "P1",
                    "File probes must retain the canonical absolute path observed during preflight",
                    capability=name,
                )
            )
        counts_valid = isinstance(present_count, int) and not isinstance(present_count, bool) and isinstance(required_count, int) and not isinstance(required_count, bool) and 0 <= present_count <= required_count
        if not counts_valid or not isinstance(present, bool):
            findings.append(finding("CAPABILITY_PROBE_COUNTS_INVALID", "P1", "Capability probe counts or present flag are invalid", capability=name))
        elif probe_kind == "none":
            if references or present is not False or present_count != 0 or required_count != 0:
                findings.append(finding("CAPABILITY_NONE_PROBE_INCONSISTENT", "P1", "A none probe must have no references and zero counts", capability=name))
        else:
            if required_count <= 0 or required_count != len(references) or present is not (present_count == required_count):
                findings.append(finding("CAPABILITY_PROBE_INCONSISTENT", "P1", "Capability probe presence does not match its references and counts", capability=name))

        cost_kind = cost.get("kind")
        approval_required = cost.get("approval_required")
        approved = cost.get("approved")
        if set(cost) != {"kind", "approval_required", "approved"}:
            findings.append(finding("CAPABILITY_COST_FIELDS_INVALID", "P1", "Capability cost contains missing or unexpected fields", capability=name))
        if cost_kind not in {"none", "free", "paid", "unknown"} or not isinstance(approval_required, bool) or not isinstance(approved, bool):
            findings.append(finding("CAPABILITY_COST_INVALID", "P1", "Capability cost record is invalid", capability=name))
        expected_approval = cost_kind in {"paid", "unknown"}
        if isinstance(approval_required, bool) and approval_required is not expected_approval:
            findings.append(finding("CAPABILITY_COST_POLICY_INCONSISTENT", "P1", "Cost approval requirement conflicts with cost class", capability=name))
        if cost_kind in {"none", "free"} and approved is not False:
            findings.append(finding("CAPABILITY_FREE_COST_APPROVED", "P1", "Free or absent cost must not claim paid approval", capability=name))
        if cost_kind in {"paid", "unknown"} and approved is True and paid_tools_allowed is not True:
            findings.append(
                finding(
                    "CAPABILITY_PAID_PERMISSION_MISMATCH",
                    "P0",
                    "Capability report claims paid or unknown-cost approval outside the manifest permission boundary",
                    capability=name,
                    cost_kind=cost_kind,
                )
            )
        if probe_kind == "none" and (provider is not None or cost_kind != "none"):
            findings.append(finding("CAPABILITY_NONE_CANDIDATE_INCONSISTENT", "P1", "A missing probe cannot claim a provider or execution cost", capability=name))
        if probe_kind != "none" and cost_kind == "none":
            findings.append(finding("CAPABILITY_COST_INVALID", "P1", "An explicit probe must declare free, paid, or unknown cost", capability=name))
        if probe_kind != "none" and not substantive_provider_label(provider):
            findings.append(finding("CAPABILITY_PROVIDER_MISSING", "P1", "An explicit probe requires a non-empty candidate provider", capability=name))
        if probe_kind == "file" and cost_kind != "free":
            findings.append(finding("CAPABILITY_EXPORT_COST_INVALID", "P1", "A user export must be classified as free local input", capability=name))

        candidate_usable = present is True and (approval_required is False or approved is True)
        selected_provider = state.get("selected_provider")
        selected_by = state.get("selected_by")
        reason_code = state.get("reason_code")
        if status == "USER_EXPORT" and probe_kind == "file" and present is True:
            for reference in references:
                export_path = Path(reference).expanduser()
                if not export_path.is_absolute():
                    export_path = path.parent / export_path
                try:
                    export_missing = (
                        export_path.is_symlink()
                        or not export_path.is_file()
                        or export_path.stat().st_size == 0
                        or not os.access(export_path, os.R_OK)
                    )
                except OSError:
                    export_missing = True
                if export_missing:
                    findings.append(
                        finding(
                            "CAPABILITY_EXPORT_MISSING",
                            "P1",
                            "A capability marked USER_EXPORT no longer has the regular non-empty file observed by preflight",
                            capability=name,
                            reference=reference,
                        )
                    )
        expected_reason: str | None = None
        if status == "AVAILABLE":
            expected_reason = "EXPLICIT_CAPABILITY_AVAILABLE"
            if probe_kind not in {"explicit-flag", "environment"} or not candidate_usable or selected_provider != provider or selected_by != probe_kind:
                findings.append(finding("CAPABILITY_AVAILABLE_INCONSISTENT", "P1", "AVAILABLE state is not backed by a usable explicit probe", capability=name))
        elif status == "USER_EXPORT":
            expected_reason = "USER_EXPORT_PRESENT"
            if probe_kind != "file" or present is not True or selected_provider != provider or selected_by != "user-export":
                findings.append(finding("CAPABILITY_EXPORT_INCONSISTENT", "P1", "USER_EXPORT state is not backed by a present local export", capability=name))
        elif status == "FALLBACK":
            if (
                not substantive_provider_label(selected_provider)
                or selected_by not in {"builtin-fallback", "configured-fallback"}
                or candidate_usable
            ):
                findings.append(finding("CAPABILITY_FALLBACK_INCONSISTENT", "P1", "FALLBACK state conflicts with candidate usability or selection metadata", capability=name))
            if probe_kind == "none":
                expected_reason = "FREE_FALLBACK_SELECTED"
            elif present is not True:
                expected_reason = "PROBE_NOT_PRESENT_FALLBACK_SELECTED"
            else:
                expected_reason = "COST_APPROVAL_REQUIRED_FALLBACK_SELECTED"
            if selected_by == "builtin-fallback" and selected_provider != CANONICAL_DEFAULT_FALLBACKS.get(name):
                findings.append(
                    finding(
                        "CAPABILITY_BUILTIN_FALLBACK_INVALID",
                        "P1",
                        "Built-in fallbacks must exist for the capability and use the canonical provider label",
                        capability=name,
                        selected_provider=selected_provider,
                    )
                )
        elif status == "UNAVAILABLE":
            if selected_provider is not None or selected_by != "none" or candidate_usable:
                findings.append(finding("CAPABILITY_UNAVAILABLE_INCONSISTENT", "P1", "UNAVAILABLE state conflicts with provider or candidate usability", capability=name))
            if probe_kind == "none":
                expected_reason = "NO_PROVIDER_OR_EXPORT"
            elif present is not True:
                expected_reason = "PROBE_NOT_PRESENT"
            else:
                expected_reason = "COST_APPROVAL_REQUIRED"
        if reason_code != expected_reason:
            findings.append(finding("CAPABILITY_REASON_INCONSISTENT", "P1", "Capability reason code does not match its observable state", capability=name, expected=expected_reason, actual=reason_code))

        if status == "AVAILABLE" and approval_required is True and approved is not True:
            findings.append(finding("CAPABILITY_COST_UNAPPROVED", "P0", "Paid or unknown-cost capability is marked available without approval", capability=name))

    if len(valid_states) != len(CAPABILITY_ORDER):
        return payload
    counts = {status: sum(state.get("status") == status for state in valid_states.values()) for status in CAPABILITY_STATES}
    usable = [name for name in CAPABILITY_ORDER if valid_states[name].get("status") != "UNAVAILABLE"]
    unavailable = [name for name in CAPABILITY_ORDER if valid_states[name].get("status") == "UNAVAILABLE"]
    cost_blocked = []
    expected_limitations = []
    for name in CAPABILITY_ORDER:
        state = valid_states[name]
        candidate = state.get("candidate") or {}
        probe = candidate.get("probe") or {}
        cost = candidate.get("cost") or {}
        if probe.get("present") is True and cost.get("approval_required") is True and cost.get("approved") is not True:
            cost_blocked.append(name)
        if state.get("status") in {"FALLBACK", "UNAVAILABLE"}:
            expected_limitations.append(f"{name} [{state.get('status')}]: {state.get('absence_effect')}")

    summary = payload.get("summary")
    expected_summary = {
        "counts": counts,
        "usable_capabilities": usable,
        "unavailable_capabilities": unavailable,
        "cost_approval_blocked_capabilities": cost_blocked,
        "all_capabilities_usable": not unavailable,
        "degraded": bool(counts["FALLBACK"] or counts["UNAVAILABLE"]),
    }
    if summary != expected_summary:
        findings.append(finding("CAPABILITY_SUMMARY_INCONSISTENT", "P1", "Capability summary does not match recomputed capability states"))
    if payload.get("limitations") != expected_limitations:
        findings.append(finding("CAPABILITY_LIMITATIONS_INCONSISTENT", "P1", "Capability limitations do not match degraded states"))
    degraded_capabilities = [
        {
            "capability": name,
            "status": valid_states[name].get("status"),
            "selected_provider": valid_states[name].get("selected_provider"),
            "absence_effect": valid_states[name].get("absence_effect"),
        }
        for name in CAPABILITY_ORDER
        if valid_states[name].get("status") in {"FALLBACK", "UNAVAILABLE"}
    ]
    if degraded_capabilities:
        findings.append(
            finding(
                "CAPABILITIES_DEGRADED",
                "P2",
                "One or more capabilities use a fallback or are unavailable; disclose the affected evidence limits",
                capabilities=degraded_capabilities,
            )
        )
    return payload


def jsonl_ids(path: Path, field: str) -> set[str]:
    values: set[str] = set()
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            record = strict_json_loads(raw)
        except ValueError:
            continue
        if isinstance(record, dict) and isinstance(record.get(field), str):
            values.add(record[field])
    return values


def claim_scope_ids(path: Path) -> tuple[set[str], set[str]]:
    """Return all and material claim IDs from the canonical claim ledger."""

    all_ids: set[str] = set()
    material_ids: set[str] = set()
    if not path.is_file() or (ACTIVE_ROOT is not None and path_uses_symlink(ACTIVE_ROOT, path)):
        return all_ids, material_ids
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            record = strict_json_loads(raw)
        except ValueError:
            continue
        claim_id = record.get("claim_id") if isinstance(record, dict) else None
        if not isinstance(claim_id, str) or not valid_identifier(claim_id):
            continue
        all_ids.add(claim_id)
        if record.get("classification") in {"load-bearing", "supporting"}:
            material_ids.add(claim_id)
    return all_ids, material_ids


def normalize_media_reference(root: Path, article_path: Path, reference: str, findings: list[dict[str, Any]]) -> str | None:
    reference = html_unescape(reference)
    if contains_forbidden_unicode_control(reference):
        findings.append(finding("UNICODE_CONTROL_CHARACTER_INVALID", "P1", "Media reference contains a forbidden zero-width, bidi, or surrogate control character", reference=reference))
        return None
    raw = reference.split("#", 1)[0].split("?", 1)[0].strip()
    if not raw:
        findings.append(finding("MEDIA_REFERENCE_INVALID", "P0", "Media reference is empty", reference=reference))
        return None
    if raw.startswith(("http://", "https://", "//", "/")):
        findings.append(finding("MEDIA_REFERENCE_UNVERIFIABLE", "P0", "Media reference must resolve to a declared local package asset", reference=reference))
        return None
    try:
        parsed = urlparse(raw)
    except ValueError:
        findings.append(finding("MEDIA_REFERENCE_INVALID", "P0", "Media reference is malformed", reference=reference))
        return None
    if parsed.scheme or "\\" in raw or any(character.isspace() or unicodedata.category(character).startswith("C") for character in raw):
        findings.append(finding("MEDIA_REFERENCE_INVALID", "P0", "Media reference uses an unsafe or unsupported path", reference=reference))
        return None
    unresolved = article_path.parent / raw
    resolved = unresolved.resolve()
    if (resolved != root and root not in resolved.parents) or path_uses_symlink(root, unresolved):
        findings.append(finding("MEDIA_REFERENCE_PATH_UNSAFE", "P0", "Media reference escapes the run or traverses a symlink", reference=reference))
        return None
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return None


def collect_media_work_paths(root: Path, findings: list[dict[str, Any]]) -> tuple[bool, set[str]]:
    work_detected = False
    required_paths: set[str] = set()
    for article_path in (root / "drafts/final.md", root / "publish/article.md", root / "publish/article.mdx", root / "publish/article.html"):
        if article_path.is_symlink() or (article_path.exists() and path_uses_symlink(root, article_path)):
            code = "PUBLISH_ARTICLE_SYMLINK" if article_path.parent.name == "publish" else "ARTIFACT_SYMLINK"
            findings.append(finding(code, "P0", "Article artifact traverses a symlink", path=article_path.relative_to(root).as_posix()))
            continue
        if not article_path.is_file():
            continue
        text = article_path.read_text(encoding="utf-8")
        inspected_text = strip_code_for_mdx(text) if article_path.suffix in {".md", ".mdx"} else text
        inline_references = markdown_destinations(MD_IMAGE, inspected_text)
        references = list(inline_references)
        reference_references: list[str] = []
        if article_path.suffix in {".md", ".mdx"}:
            reference_references = markdown_reference_destinations(inspected_text, images=True)
            references.extend(reference_references)
            marker_count = markdown_image_marker_count(inspected_text)
            if marker_count > len(inline_references) + len(reference_references):
                work_detected = True
                findings.append(
                    finding(
                        "MEDIA_REFERENCE_UNPARSED",
                        "P0",
                        "Article contains image-like Markdown syntax that could not be resolved safely",
                        path=article_path.relative_to(root).as_posix(),
                        markers=marker_count,
                        resolved=len(inline_references) + len(reference_references),
                    )
                )
        inspector = PackageHTMLInspector()
        try:
            inspector.feed(inspected_text)
            inspector.close()
        except Exception:
            inspector.media_references = []
        references.extend(inspector.media_references)
        if references or HTML_MEDIA.search(inspected_text):
            work_detected = True
        for reference in references:
            normalized = normalize_media_reference(root, article_path, reference, findings)
            if normalized:
                required_paths.add(normalized)

    for directory in (root / "media", root / "publish/assets"):
        relative_directory = directory.relative_to(root).as_posix()
        if directory.is_symlink() or (directory.exists() and path_uses_symlink(root, directory)):
            findings.append(finding("MEDIA_DIRECTORY_SYMLINK", "P0", "Media directory traverses a symlink", path=relative_directory))
            continue
        if directory.exists() and not directory.is_dir():
            findings.append(finding("MEDIA_DIRECTORY_SPECIAL", "P0", "Reserved media path must be a real directory", path=relative_directory))
            continue
        if directory.is_dir():
            for path in directory.rglob("*"):
                relative_entry = path.relative_to(root).as_posix()
                if path.is_symlink():
                    findings.append(finding("MEDIA_ENTRY_SYMLINK", "P0", "Media work contains a symlinked file or directory", path=relative_entry))
                    continue
                if path.is_dir():
                    continue
                if not path.is_file():
                    findings.append(finding("MEDIA_ENTRY_SPECIAL", "P0", "Media work contains a non-regular filesystem entry", path=relative_entry))
                    continue
                work_detected = True
                required_paths.add(path.resolve().relative_to(root).as_posix())

    publish_manifest_path = root / "publish/publish-manifest.json"
    if publish_manifest_path.is_symlink() or (publish_manifest_path.exists() and path_uses_symlink(root, publish_manifest_path)):
        findings.append(finding("PUBLISH_MANIFEST_SYMLINK", "P0", "Optional publish manifest traverses a symlink", path="publish/publish-manifest.json"))
        return work_detected, required_paths
    if publish_manifest_path.is_file():
        try:
            payload = strict_json_loads(publish_manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("files"), list):
            for record in payload["files"]:
                path_value = record.get("path") if isinstance(record, dict) else None
                if isinstance(path_value, str) and (PurePosixPath(path_value).suffix.casefold() in MEDIA_SUFFIXES or path_value.startswith(("media/", "publish/assets/"))):
                    work_detected = True
                    required_paths.add(path_value)
    return work_detected, required_paths


def validate_media_integration(
    root: Path,
    manifest: dict[str, Any],
    package_ready: bool,
    findings: list[dict[str, Any]],
    child_reports: list[dict[str, Any]],
) -> bool:
    media_path = root / "media-manifest.json"
    media_required, required_media_paths = collect_media_work_paths(root, findings)
    if media_required and not media_path.is_file():
        findings.append(finding("MEDIA_MANIFEST_REQUIRED", "P0", "Article or package contains media work without a provenance and rights manifest"))
        return media_required
    dataset_manifest_path = root / "dataset-manifest.json"
    if not media_path.is_file():
        if dataset_manifest_path.is_file():
            code, payload = child_validator(
                Path(__file__).with_name("validate_media.py"),
                dataset_manifest_path,
                "--dataset-only",
                "--asset-root",
                str(root),
            )
            child_reports.append(payload)
            if code == 2:
                findings.append(finding("DATASET_VALIDATOR_UNAVAILABLE", "P1", "Standalone dataset validation could not run"))
            elif code == 1:
                findings.append(finding("DATASET_VALIDATOR_FAILED", "P1", "Standalone dataset manifest has hard failures"))
            dataset_manifest = read_json(dataset_manifest_path, findings, "DATASET_MANIFEST", "P0")
            if isinstance(dataset_manifest, dict) and dataset_manifest.get("run_id") != manifest.get("run_id"):
                findings.append(finding("DATASET_RUN_ID_MISMATCH", "P0", "Dataset manifest run_id does not match the article run", dataset_run_id=dataset_manifest.get("run_id"), run_id=manifest.get("run_id")))
        return media_required

    code, payload = child_validator(Path(__file__).with_name("validate_media.py"), root)
    child_reports.append(payload)
    if code == 2:
        findings.append(finding("MEDIA_VALIDATOR_UNAVAILABLE", "P1", "Media validation could not run"))
    elif code == 1:
        findings.append(finding("MEDIA_VALIDATOR_FAILED", "P1", "Media manifest has hard failures"))

    identity = payload.get("identity") if isinstance(payload, dict) else None
    declared_paths = set(identity.get("output_paths", [])) if isinstance(identity, dict) and isinstance(identity.get("output_paths"), list) else set()
    undeclared_paths = sorted(path for path in required_media_paths if path not in declared_paths)
    if undeclared_paths:
        findings.append(finding("MEDIA_REFERENCE_UNDECLARED", "P0", "Article or package media paths are not declared by validated media assets", paths=undeclared_paths))

    media = read_json(media_path, findings, "MEDIA_MANIFEST", "P0")
    if not isinstance(media, dict):
        return media_required
    if media.get("run_id") != manifest.get("run_id"):
        findings.append(finding("MEDIA_RUN_ID_MISMATCH", "P0", "Media manifest run_id does not match the article run", media_run_id=media.get("run_id"), run_id=manifest.get("run_id")))
    known_claim_ids = jsonl_ids(root / "claims.jsonl", "claim_id")
    assets = media.get("assets")
    if isinstance(assets, list):
        package_paths: set[str] = set()
        if package_ready:
            publish_manifest = read_json(root / "publish/publish-manifest.json", findings, "PUBLISH_MANIFEST_MEDIA_LINK")
            if isinstance(publish_manifest, dict) and isinstance(publish_manifest.get("files"), list):
                package_paths = {
                    record.get("path")
                    for record in publish_manifest["files"]
                    if isinstance(record, dict) and isinstance(record.get("path"), str)
                }
        for index, asset in enumerate(assets):
            if not isinstance(asset, dict):
                continue
            unknown_claim_ids = sorted(
                claim_id
                for claim_id in (asset.get("claim_ids") if isinstance(asset.get("claim_ids"), list) else [])
                if isinstance(claim_id, str) and claim_id not in known_claim_ids
            )
            if unknown_claim_ids:
                findings.append(finding("MEDIA_CLAIM_ID_UNKNOWN", "P0", "Media asset references claim IDs absent from the claim ledger", asset_index=index, claim_ids=unknown_claim_ids))
            output = asset.get("output")
            if package_ready and isinstance(output, dict):
                output_paths = [output.get("path")]
                variants = output.get("variants")
                if isinstance(variants, list):
                    output_paths.extend(variant.get("path") for variant in variants if isinstance(variant, dict))
                unlisted = sorted(path for path in output_paths if isinstance(path, str) and path not in package_paths)
                if unlisted:
                    findings.append(finding("MEDIA_OUTPUT_UNLISTED", "P1", "Media output or variant is omitted from the publish manifest", asset_index=index, paths=unlisted))

    if dataset_manifest_path.is_file():
        dataset_manifest = read_json(dataset_manifest_path, findings, "DATASET_MANIFEST", "P0")
        if isinstance(dataset_manifest, dict) and dataset_manifest.get("run_id") != manifest.get("run_id"):
            findings.append(finding("DATASET_RUN_ID_MISMATCH", "P0", "Dataset manifest run_id does not match the article run", dataset_run_id=dataset_manifest.get("run_id"), run_id=manifest.get("run_id")))
    return media_required


def validate_publish(root: Path, manifest: dict[str, Any], media_work_detected: bool, findings: list[dict[str, Any]]) -> None:
    publish_dir = root / "publish"
    article_references: list[str] = []
    article_parent: Path | None = None
    listed_package_paths: set[str] = set()
    destination_conflicts = metadata_indexability_conflicts(manifest.get("destination"), "manifest.destination")
    if destination_conflicts:
        findings.append(finding("PUBLISH_INDEXABILITY_CONFLICT", "P1", "Manifest destination contains a noindex or nofollow directive", fields=destination_conflicts))
    article_candidates: list[Path] = []
    for path in (publish_dir / "article.md", publish_dir / "article.mdx", publish_dir / "article.html"):
        if path_uses_symlink(root, path):
            findings.append(finding("PUBLISH_ARTICLE_SYMLINK", "P0", "Publish article path traverses a symlink", path=path.relative_to(root).as_posix()))
        elif path.is_file():
            article_candidates.append(path)
    if len(article_candidates) != 1:
        findings.append(finding("PUBLISH_ARTICLE_COUNT", "P1", "Publish package must contain exactly one article.md, article.mdx, or article.html", count=len(article_candidates)))
        article_text = ""
    else:
        article_text = article_candidates[0].read_text(encoding="utf-8")
        article_parent = article_candidates[0].parent
        draft_path = root / "drafts/final.md"
        if article_candidates[0].suffix == ".md" and draft_path.is_file() and article_candidates[0].read_bytes() != draft_path.read_bytes():
            findings.append(finding("PUBLISH_ARTICLE_DRAFT_MISMATCH", "P1", "Publish article does not match the independently reviewed final draft"))
        destination_format = (manifest.get("destination") or {}).get("format")
        expected_suffix = {"markdown": ".md", "mdx": ".mdx", "html": ".html"}.get(destination_format) if isinstance(destination_format, str) else None
        if expected_suffix is not None and article_candidates[0].suffix != expected_suffix:
            findings.append(finding("PUBLISH_FORMAT_MISMATCH", "P1", "Publish article file does not match the declared destination format", expected=expected_suffix, actual=article_candidates[0].suffix))
        if contains_placeholder(article_text):
            findings.append(finding("PUBLISH_PLACEHOLDER", "P0", "Publish article contains an unresolved placeholder", path=str(article_candidates[0])))
        if contains_forbidden_document_control(article_text):
            findings.append(finding("PUBLISH_ARTICLE_UNICODE_CONTROL", "P1", "Publish article contains forbidden bidi, zero-width, surrogate, or line-separator controls", path=str(article_candidates[0])))
        if article_candidates[0].suffix in {".md", ".mdx"}:
            inspected_markdown = strip_code_for_mdx(article_text)
            embedded = PackageHTMLInspector()
            embedded.feed(inspected_markdown)
            embedded.close()
            h1_count = markdown_h1_count(inspected_markdown) + embedded.h1_count
            if h1_count != 1:
                findings.append(finding("PUBLISH_H1_COUNT", "P1", "Markdown/MDX publish article must contain one logical H1 across Markdown and embedded HTML", count=h1_count))
            active_features = list(embedded.active_content)
            if article_candidates[0].suffix == ".mdx":
                active_features.extend(mdx_active_features(article_text))
            if active_features:
                findings.append(finding("PUBLISH_ACTIVE_CONTENT", "P0", "Markdown/MDX package contains executable or destination-mutating content", evidence=sorted(set(active_features))))
            markdown_indexability = embedded.indexability_conflicts + markdown_indexability_conflicts(article_text)
            if markdown_indexability:
                findings.append(finding("PUBLISH_INDEXABILITY_CONFLICT", "P1", "Markdown/MDX package contains a noindex or nofollow robots directive", evidence=markdown_indexability))
            article_references.extend(markdown_destinations(MD_LINK, inspected_markdown))
            article_references.extend(markdown_destinations(MD_ANY_INLINE_DESTINATION, inspected_markdown))
            article_references.extend(markdown_reference_destinations(inspected_markdown, images=False))
            # Validate every definition, including nested-label forms that the
            # lightweight resolver may not fully understand. Unused unsafe or
            # broken definitions should not ship in a ready package.
            article_references.extend(markdown_reference_definitions(inspected_markdown).values())
            article_references.extend(markdown_autolinks(inspected_markdown))
            article_references.extend(embedded.references)
        elif article_candidates[0].suffix == ".html":
            inspector = PackageHTMLInspector()
            inspector.feed(article_text)
            inspector.close()
            if inspector.h1_count != 1:
                findings.append(finding("PUBLISH_H1_COUNT", "P1", "HTML publish article must contain one logical H1", count=inspector.h1_count))
            if inspector.active_content:
                findings.append(finding("PUBLISH_ACTIVE_CONTENT", "P0", "HTML package contains forbidden active content", evidence=inspector.active_content))
            if inspector.indexability_conflicts:
                findings.append(finding("PUBLISH_INDEXABILITY_CONFLICT", "P1", "HTML package contains a noindex or nofollow robots directive", evidence=inspector.indexability_conflicts))
            article_references.extend(inspector.references)
        if article_candidates[0].suffix in {".mdx", ".html"} and draft_path.is_file():
            reviewed_text = normalized_markdown_text(draft_path.read_text(encoding="utf-8"))
            packaged_text = normalized_markdown_text(article_text) if article_candidates[0].suffix == ".mdx" else normalized_html_text(article_text)
            similarity = difflib.SequenceMatcher(a=reviewed_text, b=packaged_text).ratio() if reviewed_text and packaged_text else 0.0
            if similarity < 0.9:
                findings.append(finding("RENDERED_CONTENT_CORRESPONDENCE_UNVERIFIED", "P1", "Transformed package content does not deterministically correspond to the reviewed draft", similarity=round(similarity, 4)))
    metadata = read_json(publish_dir / "metadata.json", findings, "METADATA")
    if isinstance(metadata, dict):
        metadata_conflicts = metadata_indexability_conflicts(metadata)
        if metadata_conflicts:
            findings.append(finding("PUBLISH_INDEXABILITY_CONFLICT", "P1", "Publish metadata contains a noindex or nofollow directive", fields=metadata_conflicts))
        for field in ("title", "description", "slug"):
            value = metadata.get(field)
            if not substantive_string(value):
                findings.append(finding("METADATA_FIELD_MISSING", "P1", "Required metadata field is missing", field=field))
            elif contains_placeholder(value):
                findings.append(finding("METADATA_PLACEHOLDER", "P0", "Metadata contains an unresolved placeholder", field=field))
        if not valid_article_slug(metadata.get("slug")):
            findings.append(finding("METADATA_SLUG_INVALID", "P1", "Metadata slug must be one canonical URL-safe segment containing only letters, numbers, and internal hyphens", value=metadata.get("slug")))
        destination_url = (manifest.get("destination") or {}).get("url")
        canonical = metadata.get("canonical")
        if destination_url is not None and destination_url != "" and not valid_document_url(destination_url):
            findings.append(finding("PACKAGE_DESTINATION_URL_INVALID", "P1", "Package destination URL is malformed", value=destination_url))
        elif valid_document_url(destination_url) and not urls_match(canonical, destination_url):
            findings.append(finding("METADATA_CANONICAL_MISMATCH", "P1", "Destination-specific package metadata canonical does not match the manifest URL", canonical=canonical, destination_url=destination_url))
        if (destination_url is None or destination_url == "") and canonical is not None and canonical != "":
            findings.append(finding("METADATA_CANONICAL_UNSCOPED", "P1", "Destinationless package must not invent a canonical URL", canonical=canonical))

    schema = read_json(publish_dir / "schema.json", findings, "SCHEMA")
    schema_applicable = True
    if isinstance(schema, dict):
        if contains_forbidden_json_string_control(schema):
            findings.append(finding("SCHEMA_CONTROL_INVALID", "P1", "Structured data contains forbidden control characters"))
        applicability = schema.get("applicable")
        if "applicable" in schema and not isinstance(applicability, bool):
            findings.append(finding("SCHEMA_APPLICABILITY_INVALID", "P1", "Structured-data applicability must be a boolean when provided"))
        if applicability is False:
            schema_applicable = False
            if not substantive_string(schema.get("reason")):
                findings.append(finding("SCHEMA_DECISION_UNEXPLAINED", "P1", "Non-applicable schema decision needs a reason"))
        else:
            schema_context = schema.get("@context")
            if not isinstance(schema_context, str) or schema_context not in {"https://schema.org", "https://schema.org/"}:
                findings.append(finding("SCHEMA_CONTEXT_INVALID", "P1", "Applicable article structured data requires the canonical schema.org context"))
            schema_type = schema.get("@type")
            if not isinstance(schema_type, str) or schema_type not in ARTICLE_SCHEMA_TYPES:
                findings.append(finding("SCHEMA_TYPE_INVALID", "P1", "Applicable article structured data requires a supported top-level article-family @type", value=schema_type))
            if not substantive_string(schema.get("headline")) or contains_placeholder(schema.get("headline")):
                findings.append(finding("SCHEMA_HEADLINE_MISSING", "P1", "Applicable article structured data requires a substantive visible headline"))
        headline = schema.get("headline")
        if isinstance(headline, str) and article_text:
            normalized_headline = " ".join(headline.casefold().split())
            visible_h1s = package_h1_texts(
                article_text,
                article_candidates[0].suffix if article_candidates else ".md",
            )
            if normalized_headline not in visible_h1s:
                findings.append(finding("SCHEMA_NOT_VISIBLE", "P1", "Structured-data headline must exactly match the sole reader-visible H1", headline=headline, visible_h1s=visible_h1s))

    publish_manifest = read_json(publish_dir / "publish-manifest.json", findings, "PUBLISH_MANIFEST")
    if isinstance(publish_manifest, dict):
        if publish_manifest.get("schema_version") != "0.1" or publish_manifest.get("run_id") != manifest.get("run_id"):
            findings.append(finding("PUBLISH_MANIFEST_IDENTITY_INVALID", "P1", "Publish manifest schema or run identity does not match the article run"))
        if parse_timestamp(publish_manifest.get("created_at")) is None:
            findings.append(finding("PUBLISH_MANIFEST_TIME_INVALID", "P1", "Publish manifest requires a timezone-aware created_at timestamp"))
        if publish_manifest.get("destination") != (manifest.get("destination") or {}):
            findings.append(finding("PUBLISH_MANIFEST_DESTINATION_MISMATCH", "P1", "Publish manifest destination does not match the run manifest"))
        publication_authorized = publish_manifest.get("publication_authorized")
        if not isinstance(publication_authorized, bool):
            findings.append(finding("PUBLISH_MANIFEST_PERMISSION_INVALID", "P1", "Publish manifest must explicitly record publication_authorized as a boolean"))
        elif publication_authorized is not (manifest.get("permissions") or {}).get("publish"):
            severity = "P0" if publication_authorized is True else "P1"
            findings.append(finding("PUBLISH_MANIFEST_PERMISSION_MISMATCH", severity, "Publish manifest authorization does not match the run permission boundary"))
        file_records = publish_manifest.get("files")
        required_package_paths: set[str] = set()
        allowed_package_paths: set[str] = set()
        actual_publish_files: set[str] = set()
        if path_uses_symlink(root, publish_dir):
            findings.append(finding("PUBLISH_DIRECTORY_SYMLINK", "P0", "Publish directory traverses a symlink"))
        elif publish_dir.is_dir():
            for path in publish_dir.rglob("*"):
                relative_entry = path.relative_to(root).as_posix()
                if path.is_symlink():
                    findings.append(finding("PUBLISH_ENTRY_SYMLINK", "P0", "Publish package contains a symlinked file or directory", path=relative_entry))
                    continue
                if path.is_dir():
                    continue
                if not path.is_file():
                    findings.append(finding("PUBLISH_ENTRY_SPECIAL", "P0", "Publish package contains a non-regular filesystem entry", path=relative_entry))
                    continue
                if path.name not in {"publish-manifest.json", "publish-receipt.json"}:
                    actual_publish_files.add(relative_entry)
        for core_path in ("publish/metadata.json", "publish/schema.json"):
            required_package_paths.add(core_path)
            allowed_package_paths.add(core_path)
        for adjacent_name in ("media-manifest.json", "dataset-manifest.json"):
            if (root / adjacent_name).is_file():
                required_package_paths.add(adjacent_name)
                allowed_package_paths.add(adjacent_name)
        media_manifest = quiet_json_object(root / "media-manifest.json")
        if isinstance(media_manifest, dict) and isinstance(media_manifest.get("assets"), list):
            for asset in media_manifest["assets"]:
                output = asset.get("output") if isinstance(asset, dict) else None
                if not isinstance(output, dict):
                    continue
                output_records = [output]
                variants = output.get("variants")
                if isinstance(variants, list):
                    output_records.extend(variant for variant in variants if isinstance(variant, dict))
                for output_record in output_records:
                    output_path = output_record.get("path")
                    if (
                        isinstance(output_path, str)
                        and output_path == PurePosixPath(output_path).as_posix()
                        and unicodedata.normalize("NFC", output_path) == output_path
                        and output_path.startswith(("media/", "publish/assets/"))
                    ):
                        allowed_package_paths.add(output_path)
        if article_candidates:
            article_package_path = article_candidates[0].relative_to(root).as_posix()
            required_package_paths.add(article_package_path)
            allowed_package_paths.add(article_package_path)
        undeclared_publish_files = sorted(actual_publish_files - allowed_package_paths)
        if undeclared_publish_files:
            findings.append(
                finding(
                    "PUBLISH_ENTRY_OUTSIDE_DELIVERABLE_SCOPE",
                    "P0",
                    "Publish tree contains undeclared files outside the static deliverable allowlist",
                    paths=undeclared_publish_files,
                )
            )
        seen_paths: set[str] = set()
        seen_normalized_paths: set[str] = set()
        seen_file_identities: set[tuple[int, int]] = set()
        if not isinstance(file_records, list) or not file_records:
            findings.append(finding("PUBLISH_MANIFEST_FILES_INVALID", "P1", "Publish manifest requires non-empty file checksum records"))
        else:
            for index, record in enumerate(file_records):
                if not isinstance(record, dict):
                    findings.append(finding("PUBLISH_FILE_RECORD_INVALID", "P1", "Publish file record must be an object", index=index))
                    continue
                relative = record.get("path")
                digest = record.get("sha256")
                pure_path = PurePosixPath(relative) if isinstance(relative, str) else None
                if pure_path is None or "\\" in relative or pure_path.is_absolute() or ".." in pure_path.parts or str(pure_path) in {"", "."}:
                    findings.append(finding("PUBLISH_FILE_PATH_INVALID", "P1", "Publish file record has an unsafe relative path", index=index, path=relative))
                    continue
                canonical_relative = pure_path.as_posix()
                if relative != canonical_relative:
                    findings.append(finding("PUBLISH_FILE_PATH_INVALID", "P1", "Publish file record path must use canonical POSIX spelling", index=index, path=relative, canonical=canonical_relative))
                    continue
                relative = canonical_relative
                normalized_relative = unicodedata.normalize("NFC", relative)
                if relative != normalized_relative:
                    findings.append(finding("PUBLISH_FILE_PATH_INVALID", "P1", "Publish file record path must use NFC Unicode normalization", index=index, path=relative, canonical=normalized_relative))
                    continue
                if relative in seen_paths or normalized_relative in seen_normalized_paths:
                    findings.append(finding("PUBLISH_FILE_DUPLICATE", "P1", "Publish manifest contains a duplicate file record", path=relative))
                seen_paths.add(relative)
                seen_normalized_paths.add(normalized_relative)
                if relative in allowed_package_paths:
                    listed_package_paths.add(relative)
                if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                    findings.append(finding("PUBLISH_FILE_HASH_INVALID", "P1", "Publish file record has an invalid SHA-256", path=relative))
                    continue
                unresolved_candidate = root / relative
                if path_uses_symlink(root, unresolved_candidate):
                    findings.append(finding("PUBLISH_FILE_SYMLINK", "P0", "Publish file record traverses a symlink", path=relative))
                    continue
                candidate = unresolved_candidate.resolve()
                if candidate != root and root not in candidate.parents:
                    findings.append(finding("PUBLISH_FILE_PATH_ESCAPE", "P0", "Publish file resolves outside the article run", path=relative))
                    continue
                if not candidate.is_file():
                    findings.append(finding("PUBLISH_FILE_MISSING", "P1", "Publish manifest references a missing file", path=relative))
                    continue
                stat_result = candidate.stat()
                file_identity = (stat_result.st_dev, stat_result.st_ino)
                if file_identity in seen_file_identities:
                    findings.append(finding("PUBLISH_FILE_DUPLICATE_TARGET", "P1", "Publish manifest paths resolve to the same filesystem file", path=relative))
                seen_file_identities.add(file_identity)
                actual_digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
                if actual_digest != digest:
                    findings.append(finding("PUBLISH_FILE_HASH_MISMATCH", "P1", "Publish file checksum does not match its contents", path=relative))
            missing_package_paths = sorted(required_package_paths - seen_paths)
            if missing_package_paths:
                findings.append(finding("PUBLISH_CORE_FILES_UNLISTED", "P1", "Publish manifest omits required package files", paths=missing_package_paths))
            outside_deliverable_scope = sorted(seen_paths - allowed_package_paths)
            if outside_deliverable_scope:
                findings.append(finding("PUBLISH_FILE_OUTSIDE_DELIVERABLE_SCOPE", "P0", "Publish manifest includes internal or undeclared files outside the deliverable allowlist", paths=outside_deliverable_scope))

    if article_parent is not None:
        for href in dict.fromkeys(article_references):
            validate_article_reference(root, article_parent, href, listed_package_paths, findings)

    technical = read_json(root / "reviews/technical.json", findings, "TECHNICAL_REVIEW")
    if isinstance(technical, dict):
        if technical.get("status") != "passed":
            findings.append(finding("TECHNICAL_REVIEW_NOT_PASSED", "P1", "Technical review did not pass", status=technical.get("status")))
        validate_review_binding(
            root,
            manifest,
            technical,
            findings,
            review_type="technical",
            required_paths=(*CONTENT_REVIEW_PATHS, "publish/publish-manifest.json"),
        )
        technical_reviewer = (manifest.get("roles") or {}).get("technical_reviewer")
        if not substantive_actor_identity(technical_reviewer) or technical.get("reviewer") != technical_reviewer:
            findings.append(finding("TECHNICAL_REVIEWER_ROLE_MISMATCH", "P1", "Technical reviewer must match manifest.roles.technical_reviewer"))
        scope = technical.get("destination_scope", technical.get("scope"))
        if not substantive_string(scope):
            findings.append(finding("TECHNICAL_REVIEW_SCOPE_MISSING", "P1", "Technical review must state its destination scope"))
        scope_text = scope if isinstance(scope, str) else ""
        checks = technical.get("checks")
        check_entries = technical_check_entries(checks)
        normalized_names = [normalized_check_name(name) for name, _ in check_entries]
        duplicate_names = sorted({name for name in normalized_names if normalized_names.count(name) > 1})
        if duplicate_names:
            findings.append(finding("TECHNICAL_CHECK_DUPLICATE", "P1", "Technical review check names must be unique after Unicode and case normalization", checks=duplicate_names))
        schema_aliases = {"schema", "schema_decision", "structured_data_decision"}
        asset_aliases = {"assets", "media_policy", "local_links_and_assets"}
        context_invalid_na = sorted(
            {
                normalized_check_name(name)
                for name, value in check_entries
                if isinstance(value, dict)
                and value.get("status") == "not-applicable"
                and (
                    (normalized_check_name(name) in schema_aliases and schema_applicable)
                    or (normalized_check_name(name) in asset_aliases and media_work_detected)
                )
            }
        )
        if context_invalid_na:
            findings.append(finding("TECHNICAL_CHECK_CONTEXT_INVALID", "P1", "A schema or asset check uses not-applicable despite applicable package work", checks=context_invalid_na))
        if isinstance(checks, list) and checks:
            for index, check in enumerate(checks):
                check_status = check.get("status") if isinstance(check, dict) else None
                if not isinstance(check, dict) or not isinstance(check_status, str) or check_status not in {"passed", "not-applicable"} or not substantive_string(check.get("check")) or not substantive_evidence(check.get("evidence")):
                    findings.append(finding("TECHNICAL_CHECK_INVALID", "P1", "Technical check lacks a passing outcome and evidence", index=index))
        elif isinstance(checks, dict) and checks:
            invalid_evidence = [
                name
                for name, value in checks.items()
                if not isinstance(value, dict)
                or not substantive_evidence(value.get("evidence"))
                or not technical_outcome(value.get("status"))
            ]
            if invalid_evidence:
                findings.append(finding("TECHNICAL_CHECK_EVIDENCE_MISSING", "P1", "Dictionary-form technical checks require an explicit acceptable status and non-empty evidence", checks=invalid_evidence))
            failed_checks = [name for name, value in checks.items() if not isinstance(value, dict) or not technical_outcome(value.get("status"))]
            if failed_checks:
                findings.append(finding("TECHNICAL_CHECK_NOT_PASSED", "P1", "One or more technical checks did not pass", checks=failed_checks))
        else:
            findings.append(finding("TECHNICAL_CHECKS_MISSING", "P1", "Technical review has no structured checks"))

        core_check_aliases = {
            "h1": ("single_h1", "single_logical_h1"),
            "metadata": ("metadata",),
            "schema": ("schema", "schema_decision", "structured_data_decision"),
            "links": ("links", "local_links_and_assets"),
            "assets": ("assets", "media_policy", "local_links_and_assets"),
        }
        core_checks_requiring_observation = {"h1", "metadata", "links"}
        if schema_applicable:
            core_checks_requiring_observation.add("schema")
        if media_work_detected:
            core_checks_requiring_observation.add("assets")
        missing_core_checks = [
            concept
            for concept, aliases in core_check_aliases.items()
            if not any(
                (named_check_passed if concept in core_checks_requiring_observation else named_check_acceptable)(checks, alias)
                for alias in aliases
            )
        ]
        if missing_core_checks:
            findings.append(finding("TECHNICAL_CORE_CHECKS_MISSING", "P1", "Technical review lacks required named package checks", checks=missing_core_checks))

        destination = manifest.get("destination") or {}
        destination_specific = bool(destination.get("cms")) or valid_document_url(destination.get("url"))
        if destination_specific:
            if not named_check_passed(checks, "destination_build_available") or not named_check_passed(checks, "destination_renderer_checked"):
                findings.append(finding("DESTINATION_RENDERER_NOT_VERIFIED", "P1", "Destination-specific package lacks a verified build and renderer"))
        elif not any(term in scope_text.casefold() for term in ("portable", "cms-neutral")):
            findings.append(finding("PORTABLE_PACKAGE_SCOPE_INVALID", "P1", "Destinationless package must explicitly identify a portable or CMS-neutral delivery scope"))
        if article_candidates and article_candidates[0].suffix != ".md" and not named_check_passed(checks, "reviewed_content_correspondence"):
            findings.append(finding("RENDERED_CONTENT_CORRESPONDENCE_MISSING", "P1", "Transformed MDX/HTML package lacks a passed correspondence check against the reviewed draft"))


def quiet_json_object(path: Path) -> dict[str, Any] | None:
    if ACTIVE_ROOT is not None and path_uses_symlink(ACTIVE_ROOT, path):
        return None
    try:
        payload = strict_json_loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def validate_event_timeline(
    root: Path,
    manifest: dict[str, Any],
    status_rank: int,
    findings: list[dict[str, Any]],
) -> None:
    """Bind declared lifecycle timestamps into one plausible, non-future chain."""

    now = datetime.now(timezone.utc)
    events: dict[str, datetime] = {}
    issues: list[dict[str, str]] = []

    def add_event(name: str, value: Any) -> None:
        parsed = parse_timestamp(value)
        if parsed is None:
            return
        events[name] = parsed
        if parsed > now + FUTURE_TOLERANCE:
            issues.append({"relation": "not-in-future", "event": name, "actual": parsed.isoformat(), "now": now.isoformat()})

    def require_order(earlier: str, later: str, *, strict: bool = False) -> None:
        if earlier not in events or later not in events:
            return
        invalid = events[earlier] >= events[later] if strict else events[earlier] > events[later]
        if invalid:
            issues.append(
                {
                    "relation": "strictly-before" if strict else "not-after",
                    "earlier": earlier,
                    "later": later,
                    "earlier_at": events[earlier].isoformat(),
                    "later_at": events[later].isoformat(),
                }
            )

    add_event("run.created_at", manifest.get("created_at"))
    add_event("run.updated_at", manifest.get("updated_at"))
    review_names: list[str] = []
    if status_rank >= RANK["content-ready"] or manifest.get("actual_status") == "needs-expert-review":
        serp = quiet_json_object(root / "research/serp.json")
        if serp is not None:
            add_event("research.serp", serp.get("captured_at"))
        sources_path = root / "research/sources.jsonl"
        source_times: list[datetime] = []
        if sources_path.is_file() and not path_uses_symlink(root, sources_path):
            try:
                for line in sources_path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    record = strict_json_loads(line)
                    parsed = parse_timestamp(record.get("retrieved_at")) if isinstance(record, dict) else None
                    if parsed is not None:
                        source_times.append(parsed)
            except (OSError, UnicodeError, ValueError):
                source_times = []
        if source_times:
            add_event("research.latest-source", max(source_times).isoformat())
        for name, relative in (
            ("review.verification", "reviews/verification.json"),
            ("review.editorial", "reviews/editorial.json"),
        ):
            review = quiet_json_object(root / relative)
            if review is not None:
                add_event(name, review.get("reviewed_at"))
                review_names.append(name)
        if status_rank >= RANK["content-ready"] and (manifest.get("risk") or {}).get("ymyl") is True:
            ymyl_review = quiet_json_object(root / "reviews/ymyl.json")
            if ymyl_review is not None:
                add_event("review.ymyl", ymyl_review.get("reviewed_at"))
                review_names.append("review.ymyl")
    if manifest.get("actual_status") == "needs-expert-review" and (manifest.get("risk") or {}).get("ymyl") is True:
        ymyl_review = quiet_json_object(root / "reviews/ymyl.json")
        if ymyl_review is not None:
            add_event("review.ymyl-request", ymyl_review.get("requested_at"))
            review_names.append("review.ymyl-request")
    if status_rank >= RANK["publish-package-ready"]:
        package = quiet_json_object(root / "publish/publish-manifest.json")
        if package is not None:
            add_event("package.created_at", package.get("created_at"))
        technical = quiet_json_object(root / "reviews/technical.json")
        if technical is not None:
            add_event("review.technical", technical.get("reviewed_at"))
            review_names.append("review.technical")
    if status_rank >= RANK["published-pending-verification"]:
        receipt = quiet_json_object(root / "publish/publish-receipt.json")
        if receipt is not None:
            add_event("publication.published_at", receipt.get("published_at"))
    if status_rank >= RANK["verified-live"]:
        live = quiet_json_object(root / "reviews/live-verification.json")
        if live is not None:
            add_event("live.checked_at", live.get("checked_at"))
    snapshot_names: list[str] = []
    if status_rank >= RANK["measured"]:
        baseline = quiet_json_object(root / "measurement/baseline.json")
        if baseline is not None:
            add_event("measurement.baseline", baseline.get("measured_at"))
        snapshot_dir = root / "measurement/snapshots"
        if snapshot_dir.is_dir():
            for index, snapshot_path in enumerate(sorted(snapshot_dir.glob("*.json"))):
                snapshot = quiet_json_object(snapshot_path)
                if snapshot is None:
                    continue
                name = f"measurement.snapshot[{index}]"
                snapshot_names.append(name)
                add_event(name, snapshot.get("measured_at"))

    require_order("run.created_at", "run.updated_at")
    for review_name in review_names:
        require_order("run.created_at", review_name)
    require_order("run.created_at", "research.serp")
    require_order("run.created_at", "research.latest-source")
    require_order("run.created_at", "measurement.baseline")
    require_order("research.serp", "review.verification")
    require_order("research.latest-source", "review.verification")
    require_order("review.verification", "review.editorial")
    require_order("review.editorial", "review.ymyl-request")
    require_order("review.editorial", "review.ymyl")
    require_order("review.editorial", "package.created_at")
    require_order("run.created_at", "package.created_at")
    if status_rank >= RANK["publish-package-ready"] and (manifest.get("risk") or {}).get("ymyl") is True:
        require_order("package.created_at", "review.ymyl")
        require_order("review.ymyl", "review.technical")
    else:
        require_order("review.verification", "review.ymyl")
    require_order("package.created_at", "review.technical")
    require_order("package.created_at", "measurement.baseline")
    require_order("review.technical", "publication.published_at")
    require_order("package.created_at", "publication.published_at")
    require_order("publication.published_at", "live.checked_at")
    require_order("measurement.baseline", "publication.published_at")
    for snapshot_name in snapshot_names:
        require_order("measurement.baseline", snapshot_name, strict=True)
        require_order("publication.published_at", snapshot_name)
        require_order("live.checked_at", snapshot_name)
    for milestone in ("research.serp", "research.latest-source", *review_names, "package.created_at", "publication.published_at", "live.checked_at", "measurement.baseline", *snapshot_names):
        require_order(milestone, "run.updated_at")

    if issues:
        findings.append(
            finding(
                "EVENT_TIMELINE_INVALID",
                "P1",
                "Run lifecycle timestamps are future-dated or contradict package, publication, verification, and measurement order",
                issues=issues,
            )
        )


def normalized_source_system(value: Any) -> str:
    return unicodedata.normalize("NFKC", value).casefold().strip() if isinstance(value, str) else ""


def measurement_capability_providers(capability_report: dict[str, Any] | None) -> dict[str, str]:
    """Return analytics systems and providers backed by current preflight evidence."""

    providers: dict[str, str] = {}
    capabilities = capability_report.get("capabilities") if isinstance(capability_report, dict) else None
    if not isinstance(capabilities, dict):
        return providers
    for capability_name in ("gsc", "ga4"):
        state = capabilities.get(capability_name)
        if not isinstance(state, dict) or state.get("status") not in {"AVAILABLE", "USER_EXPORT"}:
            continue
        provider = state.get("selected_provider")
        if substantive_provider_label(provider):
            providers[capability_name] = provider
    return providers


def parse_iso_day(value: Any) -> date | None:
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def validate_measurement_record(
    root: Path,
    payload: dict[str, Any],
    manifest: dict[str, Any],
    capability_providers: dict[str, str],
    findings: list[dict[str, Any]],
    *,
    record_type: str,
    path_label: str,
) -> dict[str, Any]:
    """Validate an immutable measurement record and return comparability metadata."""

    prefix = "MEASUREMENT_BASELINE" if record_type == "baseline" else "MEASUREMENT_SNAPSHOT"
    result: dict[str, Any] = {"window": None, "metrics": {}, "page_metrics": set(), "measured_at": None}
    if contains_forbidden_unicode_control(payload) or contains_forbidden_json_string_control(payload):
        findings.append(
            finding(
                f"{prefix}_UNICODE_CONTROL_INVALID",
                "P1",
                "Measurement records cannot contain zero-width, bidi, or surrogate control characters",
                path=path_label,
            )
        )
    required_top = {
        "contract_version",
        "run_id",
        "record_type",
        "page",
        "mode",
        "package_manifest_sha256",
        "measured_at",
        "comparison_window",
        "source_evidence",
        "metrics",
        "data_limitations",
    }
    if record_type == "snapshot":
        required_top.add("live_verification_sha256")
    if set(payload) != required_top:
        findings.append(finding(f"{prefix}_FIELDS_INVALID", "P1", "Measurement record fields do not match measurement-v1", path=path_label))
    if payload.get("contract_version") != MEASUREMENT_CONTRACT_VERSION:
        findings.append(finding(f"{prefix}_CONTRACT_INVALID", "P1", "Measurement record has an unsupported contract version", path=path_label))
    if payload.get("run_id") != manifest.get("run_id") or payload.get("record_type") != record_type:
        findings.append(finding(f"{prefix}_IDENTITY_INVALID", "P1", "Measurement record does not match this run and record type", path=path_label))
    if not urls_match(payload.get("page"), (manifest.get("destination") or {}).get("url")):
        findings.append(finding(f"{prefix}_PAGE_MISMATCH", "P1", "Measurement page does not match the published destination", path=path_label))
    if payload.get("mode") != manifest.get("mode"):
        findings.append(finding(f"{prefix}_MODE_MISMATCH", "P1", "Measurement mode does not match the article run", path=path_label))
    binding_fields = [("package_manifest_sha256", "publish/publish-manifest.json")]
    if record_type == "snapshot":
        binding_fields.append(("live_verification_sha256", "reviews/live-verification.json"))
    for field, relative in binding_fields:
        if not file_binding_matches(root, relative, payload.get(field)):
            findings.append(
                finding(
                    f"{prefix}_PACKAGE_BINDING_INVALID",
                    "P0",
                    "Measurement record is not bound to the currently published and live-verified package",
                    path=path_label,
                    field=field,
                    artifact=relative,
                )
            )

    measured_at = parse_timestamp(payload.get("measured_at"))
    run_created_at = parse_timestamp(manifest.get("created_at"))
    result["measured_at"] = measured_at
    if measured_at is None:
        findings.append(finding(f"{prefix}_TIME_INVALID", "P1", "Measurement record requires a timezone-aware measured_at", path=path_label))
    elif timestamp_is_future(payload.get("measured_at")):
        findings.append(finding(f"{prefix}_TIME_FUTURE", "P1", "Measurement record cannot be materially future-dated", path=path_label))
    elif run_created_at is not None and measured_at < run_created_at:
        findings.append(finding(f"{prefix}_TIME_PRECEDES_RUN", "P1", "Measurement records cannot predate the article run", path=path_label))

    window = payload.get("comparison_window")
    if not isinstance(window, dict) or set(window) != {"start", "end_exclusive", "timezone", "grain"}:
        findings.append(finding(f"{prefix}_WINDOW_INVALID", "P1", "Measurement comparison_window must use the measurement-v1 half-open structure", path=path_label))
    else:
        start = parse_iso_day(window.get("start"))
        end = parse_iso_day(window.get("end_exclusive"))
        zone_name = window.get("timezone")
        grain = window.get("grain")
        grain_valid = (
            isinstance(grain, str)
            and grain == normalized_source_system(grain)
            and MACHINE_TOKEN.fullmatch(grain) is not None
        )
        try:
            zone = ZoneInfo(zone_name) if substantive_string(zone_name) else None
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            zone = None
        if start is None or end is None or start >= end or zone is None or not grain_valid:
            findings.append(finding(f"{prefix}_WINDOW_INVALID", "P1", "Measurement window needs valid dates, IANA timezone, grain, and start before end_exclusive", path=path_label))
        else:
            result["window"] = (start, end, zone_name, grain)
            closes_at = datetime(end.year, end.month, end.day, tzinfo=zone)
            result["window_closes_at"] = closes_at
            if measured_at is not None and measured_at < closes_at:
                findings.append(finding(f"{prefix}_WINDOW_AFTER_MEASUREMENT", "P1", "measured_at must be at or after the comparison window closes", path=path_label))

    evidence_by_id: dict[str, dict[str, Any]] = {}
    evidence = payload.get("source_evidence")
    expected_evidence_fields = {"evidence_id", "source_system", "provider", "path", "sha256", "extracted_at"}
    if not isinstance(evidence, list) or not evidence:
        findings.append(finding(f"{prefix}_EVIDENCE_INVALID", "P1", "Measurement record requires checksummed source evidence", path=path_label))
    else:
        for index, item in enumerate(evidence):
            if not isinstance(item, dict) or set(item) != expected_evidence_fields:
                findings.append(finding(f"{prefix}_EVIDENCE_INVALID", "P1", "Measurement evidence fields do not match measurement-v1", path=path_label, index=index))
                continue
            evidence_id = item.get("evidence_id")
            source_system = item.get("source_system")
            provider = item.get("provider")
            relative = item.get("path")
            digest = item.get("sha256")
            if (
                not isinstance(evidence_id, str)
                or evidence_id != normalized_source_system(evidence_id)
                or MACHINE_TOKEN.fullmatch(evidence_id) is None
                or evidence_id in evidence_by_id
            ):
                findings.append(finding(f"{prefix}_EVIDENCE_ID_INVALID", "P1", "Measurement evidence IDs must be substantive and unique", path=path_label, index=index))
                continue
            normalized_source = normalized_source_system(source_system)
            if source_system not in {"gsc", "ga4"}:
                findings.append(finding(f"{prefix}_SOURCE_SYSTEM_INVALID", "P1", "Measurement source_system must be the exact canonical value gsc or ga4", path=path_label, source_system=source_system))
            expected_provider = capability_providers.get(normalized_source)
            if expected_provider is None or provider != expected_provider:
                findings.append(finding(f"{prefix}_SOURCE_UNAVAILABLE", "P1", "Measurement evidence source and provider are not backed by a current analytics capability", path=path_label, source_system=source_system, provider=provider))
            pure = PurePosixPath(relative) if isinstance(relative, str) else None
            safe_path = (
                pure is not None
                and not pure.is_absolute()
                and ".." not in pure.parts
                and relative == pure.as_posix()
                and unicodedata.normalize("NFC", relative) == relative
                and len(pure.parts) >= 3
                and pure.parts[:2] == ("measurement", "evidence")
                and isinstance(relative, str)
                and MEASUREMENT_EVIDENCE_PATH.fullmatch(relative) is not None
            )
            candidate = root / pure.as_posix() if safe_path and pure is not None else None
            if (
                candidate is None
                or path_uses_symlink(root, candidate)
                or not candidate.is_file()
                or candidate.stat().st_size == 0
                or not isinstance(digest, str)
                or re.fullmatch(r"[0-9a-f]{64}", digest) is None
                or file_sha256(candidate) != digest
            ):
                findings.append(finding(f"{prefix}_EVIDENCE_FILE_INVALID", "P1", "Measurement evidence must be a regular non-empty in-run file with a matching SHA-256", path=path_label, evidence_path=relative))
            extracted_at = parse_timestamp(item.get("extracted_at"))
            if extracted_at is None or timestamp_is_future(item.get("extracted_at")):
                findings.append(finding(f"{prefix}_EVIDENCE_TIME_INVALID", "P1", "Measurement evidence requires a non-future timezone-aware extracted_at", path=path_label, evidence_id=evidence_id))
            elif measured_at is not None and extracted_at > measured_at:
                findings.append(finding(f"{prefix}_EVIDENCE_AFTER_MEASUREMENT", "P1", "Evidence cannot be extracted after the measurement record", path=path_label, evidence_id=evidence_id))
            elif run_created_at is not None and extracted_at < run_created_at:
                findings.append(finding(f"{prefix}_EVIDENCE_BEFORE_RUN", "P1", "Measurement evidence cannot be extracted before the article run", path=path_label, evidence_id=evidence_id))
            window_closes_at = result.get("window_closes_at")
            if extracted_at is not None and isinstance(window_closes_at, datetime) and extracted_at < window_closes_at:
                findings.append(finding(f"{prefix}_EVIDENCE_BEFORE_WINDOW_CLOSE", "P1", "Evidence cannot be extracted before the comparison window closes", path=path_label, evidence_id=evidence_id))
            evidence_by_id[evidence_id] = item

    metrics = payload.get("metrics")
    expected_metric_fields = {"value", "unit", "aggregation", "source_system", "evidence_id", "entity", "channel", "domain", "filters", "segments"}
    if not isinstance(metrics, dict) or not metrics:
        findings.append(finding(f"{prefix}_METRICS_INVALID", "P1", "Measurement record requires structured finite metrics", path=path_label))
    else:
        for metric_id, metric in metrics.items():
            canonical_metric_id = normalized_source_system(metric_id)
            if (
                not isinstance(metric_id, str)
                or metric_id != canonical_metric_id
                or MACHINE_TOKEN.fullmatch(metric_id) is None
                or canonical_metric_id in result["metrics"]
                or not isinstance(metric, dict)
                or set(metric) != expected_metric_fields
            ):
                findings.append(finding(f"{prefix}_METRIC_INVALID", "P1", "Metric fields do not match measurement-v1", path=path_label, metric=metric_id))
                continue
            value = metric.get("value")
            unit = metric.get("unit")
            canonical_descriptor_fields = ("unit", "aggregation", "source_system", "entity", "channel")
            descriptor_canonical = all(
                isinstance(metric.get(field), str)
                and metric.get(field) == normalized_source_system(metric.get(field))
                and MACHINE_TOKEN.fullmatch(metric.get(field)) is not None
                for field in canonical_descriptor_fields
            )
            if metric.get("source_system") not in {"gsc", "ga4"}:
                descriptor_canonical = False
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                findings.append(finding(f"{prefix}_METRIC_VALUE_INVALID", "P1", "Metric values must be finite numbers and never booleans", path=path_label, metric=metric_id))
            elif unit == "count" and (value < 0 or not float(value).is_integer()):
                findings.append(finding(f"{prefix}_METRIC_VALUE_INVALID", "P1", "Count metrics must be non-negative integers", path=path_label, metric=metric_id))
            elif unit == "percent" and not 0 <= value <= 100:
                findings.append(finding(f"{prefix}_METRIC_VALUE_INVALID", "P1", "Percent metrics must be between 0 and 100", path=path_label, metric=metric_id))
            elif unit == "ratio" and not 0 <= value <= 1:
                findings.append(finding(f"{prefix}_METRIC_VALUE_INVALID", "P1", "Ratio metrics must be between 0 and 1", path=path_label, metric=metric_id))
            descriptor_fields = ("unit", "aggregation", "source_system", "evidence_id", "entity", "channel")
            if (
                not descriptor_canonical
                or not substantive_string(metric.get("evidence_id"))
                or metric.get("evidence_id") != metric.get("evidence_id", "").strip()
                or any(not substantive_string(metric.get(field)) for field in descriptor_fields)
                or not valid_dimension_map(metric.get("domain"))
                or not metric.get("domain")
                or not valid_dimension_map(metric.get("filters"))
                or not valid_dimension_map(metric.get("segments"))
            ):
                findings.append(finding(f"{prefix}_METRIC_DESCRIPTOR_INVALID", "P1", "Metric descriptor strings and domain/filter/segment objects are required", path=path_label, metric=metric_id))
                continue
            page_scoped = False
            if metric.get("entity") == "page":
                domain = metric["domain"]
                filters = metric["filters"]
                segments = metric["segments"]
                page_scoped = (
                    set(domain) == {"entity", "value"}
                    and domain.get("entity") == "page"
                    and urls_match(domain.get("value"), payload.get("page"))
                    and "page" in filters
                    and set(filters).issubset(PAGE_FILTER_FIELDS)
                    and urls_match(filters.get("page"), payload.get("page"))
                    and set(segments).issubset(PAGE_SEGMENT_FIELDS)
                )
                if not page_scoped:
                    findings.append(
                        finding(
                            f"{prefix}_METRIC_PAGE_SCOPE_INVALID",
                            "P1",
                            "Page metrics require an exact entity/value domain, a canonical matching filters.page, and only documented page descriptor keys",
                            path=path_label,
                            metric=metric_id,
                        )
                    )
                    continue
            evidence_item = evidence_by_id.get(metric.get("evidence_id"))
            source_system = normalized_source_system(metric["source_system"])
            if evidence_item is None or source_system != normalized_source_system(evidence_item.get("source_system", "")):
                findings.append(finding(f"{prefix}_METRIC_EVIDENCE_MISMATCH", "P1", "Metric source_system and evidence_id must reference declared source evidence", path=path_label, metric=metric_id))
                continue
            comparison_key = (
                normalized_source_system(metric["source_system"]),
                evidence_item.get("provider"),
                unicodedata.normalize("NFKC", metric_id).casefold().strip(),
                unicodedata.normalize("NFKC", metric["unit"]).casefold().strip(),
                unicodedata.normalize("NFKC", metric["aggregation"]).casefold().strip(),
                unicodedata.normalize("NFKC", metric["entity"]).casefold().strip(),
                unicodedata.normalize("NFKC", metric["channel"]).casefold().strip(),
                canonical_json(metric["domain"]),
                canonical_json(metric["filters"]),
                canonical_json(metric["segments"]),
            )
            result["metrics"][canonical_metric_id] = comparison_key
            if page_scoped:
                result["page_metrics"].add(canonical_metric_id)

    limitations = payload.get("data_limitations")
    if not isinstance(limitations, list) or any(
        not substantive_string(item) or contains_forbidden_single_line_control(item)
        for item in limitations
    ):
        findings.append(finding(f"{prefix}_LIMITATIONS_INVALID", "P1", "data_limitations must be an array of substantive strings, or an empty array", path=path_label))
    return result


def validate_reserved_artifact_nodes(root: Path, findings: list[dict[str, Any]]) -> None:
    """Reject symlinked or special-file substitutions for contract artifacts at every status."""

    reserved_files = (
        "manifest.json", "intake.json", "capabilities.json", "research/serp.json", "research/quality-gate.json",
        "research/sources.jsonl", "claims.jsonl", "drafts/final.md",
        "reviews/verification.json", "reviews/editorial.json", "reviews/ymyl.json",
        "reviews/technical.json", "reviews/live-verification.json",
        "publish/article.md", "publish/article.mdx", "publish/article.html",
        "publish/metadata.json", "publish/schema.json", "publish/publish-manifest.json",
        "publish/publish-receipt.json", "media-manifest.json", "dataset-manifest.json",
        "measurement/baseline.json", "measurement/decisions.md", "handoff.md",
    )
    for relative in reserved_files:
        path = root / relative
        if path.is_symlink() or path_uses_symlink(root, path):
            findings.append(finding("RESERVED_ARTIFACT_SYMLINK", "P0", "Reserved artifact path traverses a symlink", path=relative))
        elif path.exists() and not path.is_file():
            findings.append(finding("RESERVED_ARTIFACT_SPECIAL", "P0", "Reserved artifact path must be a regular file", path=relative))


def main() -> int:
    parser = JsonArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    root = args.run_dir.expanduser().resolve()
    global ACTIVE_ROOT
    ACTIVE_ROOT = root
    findings: list[dict[str, Any]] = []
    child_reports: list[dict[str, Any]] = []
    validate_reserved_artifact_nodes(root, findings)

    manifest = read_json(root / "manifest.json", findings, "MANIFEST")
    if not isinstance(manifest, dict):
        report = {"validator": "run", "status": "unavailable", "findings": findings, "child_reports": []}
        print(json.dumps(report, indent=2 if args.pretty else None, ensure_ascii=True, allow_nan=False))
        return 2

    required_manifest = ("schema_version", "run_id", "mode", "target", "language", "risk", "permissions", "requested_status", "actual_status", "created_at", "updated_at")
    missing_manifest = [field for field in required_manifest if field not in manifest]
    if missing_manifest:
        findings.append(finding("MANIFEST_FIELDS_MISSING", "P1", "Manifest is incomplete", fields=missing_manifest))
    validate_manifest_contract(manifest, findings)
    for object_field in ("risk", "permissions", "roles", "protected", "destination"):
        value = manifest.get(object_field)
        if not isinstance(value, dict):
            findings.append(finding("MANIFEST_OBJECT_FIELD_INVALID", "P1", "Manifest field must be an object", field=object_field, actual_type=type(value).__name__))
            manifest[object_field] = {}
    if manifest.get("schema_version") != "0.1":
        findings.append(finding("SCHEMA_VERSION_UNSUPPORTED", "P1", "Unsupported artifact schema version", value=manifest.get("schema_version")))
    created_at = parse_timestamp(manifest.get("created_at"))
    updated_at = parse_timestamp(manifest.get("updated_at"))
    if created_at is None or updated_at is None:
        findings.append(finding("MANIFEST_TIME_INVALID", "P1", "Manifest created_at and updated_at must be timezone-aware timestamps"))
    elif updated_at < created_at:
        findings.append(finding("MANIFEST_TIME_REVERSED", "P1", "Manifest updated_at predates created_at"))
    requested_status = manifest.get("requested_status")
    if not isinstance(requested_status, str) or requested_status not in RANK:
        findings.append(finding("REQUESTED_STATUS_INVALID", "P1", "Unknown requested_status", value=requested_status))
    permissions = manifest.get("permissions")
    required_permissions = ("web_research", "paid_tools", "cms_draft", "publish", "url_change")
    if not isinstance(permissions, dict) or any(not isinstance(permissions.get(name), bool) for name in required_permissions):
        findings.append(finding("PERMISSIONS_INVALID", "P1", "Manifest permissions must explicitly record boolean research, paid-tool, CMS-draft, publish, and URL-change boundaries"))

    status = manifest.get("actual_status")
    if not isinstance(status, str) or status not in RANK:
        findings.append(finding("STATUS_INVALID", "P1", "Unknown actual_status", value=status))
        status = "blocked"
    status_rank = RANK[status]
    if isinstance(requested_status, str) and requested_status in RANK and status_rank > RANK[requested_status]:
        findings.append(
            finding(
                "STATUS_EXCEEDS_REQUESTED_SCOPE",
                "P1",
                "Actual status exceeds the maximum state requested by the user",
                requested_status=requested_status,
                actual_status=status,
            )
        )
    mode = manifest.get("mode")
    if not isinstance(mode, str) or mode not in {"new", "rewrite", "refresh", "external"}:
        findings.append(finding("MODE_INVALID", "P1", "Unknown article mode", value=mode))

    present_publish_manifest_path = root / "publish/publish-manifest.json"
    if present_publish_manifest_path.exists() or present_publish_manifest_path.is_symlink():
        present_publish_manifest = read_json(present_publish_manifest_path, findings, "PUBLISH_MANIFEST_PRESENT")
        if (
            isinstance(present_publish_manifest, dict)
            and present_publish_manifest.get("publication_authorized") is True
            and (manifest.get("permissions") or {}).get("publish") is not True
        ):
            findings.append(finding("PRESENT_PACKAGE_AUTHORIZATION_CONTRADICTION", "P0", "Publish manifest claims publication authorization while manifest permission is false"))

    receipt_path = root / "publish/publish-receipt.json"
    receipt: dict[str, Any] | None = None
    if receipt_path.exists() or receipt_path.is_symlink():
        candidate_receipt = read_json(receipt_path, findings, "PUBLISH_RECEIPT_PRESENT")
        receipt = candidate_receipt if isinstance(candidate_receipt, dict) else None
        if isinstance(receipt, dict) and receipt.get("status") == "published":
            if (manifest.get("permissions") or {}).get("publish") is not True:
                findings.append(finding("PRESENT_PUBLICATION_UNAUTHORIZED", "P0", "A successful publication receipt exists while publish permission is false"))
            if status_rank < RANK["published-pending-verification"]:
                findings.append(finding("PRESENT_PUBLICATION_STATUS_CONTRADICTION", "P0", "A successful publication receipt cannot be hidden by downgrading the run status", actual_status=status))

    live_path = root / "reviews/live-verification.json"
    live: dict[str, Any] | None = None
    if live_path.exists() or live_path.is_symlink():
        candidate_live = read_json(live_path, findings, "LIVE_VERIFICATION_PRESENT")
        live = candidate_live if isinstance(candidate_live, dict) else None
        if isinstance(live, dict) and live.get("status") == "passed" and status_rank < RANK["verified-live"]:
            findings.append(finding("PRESENT_LIVE_STATUS_CONTRADICTION", "P0", "A passed live-verification record cannot be hidden by downgrading the run status", actual_status=status))

    snapshot_dir_for_presence = root / "measurement/snapshots"
    if status_rank < RANK["measured"] and snapshot_dir_for_presence.is_dir() and any(snapshot_dir_for_presence.glob("*.json")):
        findings.append(finding("PRESENT_MEASUREMENT_STATUS_CONTRADICTION", "P0", "Post-publication measurement snapshots cannot be hidden by downgrading the run status", actual_status=status))

    intake = read_json(root / "intake.json", findings, "INTAKE")
    if isinstance(intake, dict):
        validate_intake_contract(intake, manifest, findings)
    draft_path = require_file(root, "drafts/final.md", findings)
    if draft_path and (status_rank >= RANK["content-ready"] or status == "needs-expert-review") and contains_placeholder(draft_path.read_text(encoding="utf-8")):
        findings.append(finding("FINAL_DRAFT_PLACEHOLDER", "P0", "Delivery-stage draft contains an unresolved placeholder"))
    if draft_path and (status_rank >= RANK["content-ready"] or status == "needs-expert-review"):
        draft_text = draft_path.read_text(encoding="utf-8")
        if not substantive_string(draft_text) or contains_forbidden_document_control(draft_text):
            findings.append(finding("FINAL_DRAFT_NOT_SUBSTANTIVE", "P1", "Content-ready draft must contain substantive visible text without forbidden Unicode controls"))

    if status == "needs-evidence":
        require_file(root, "research/sources.jsonl", findings)
        require_file(root, "claims.jsonl", findings)

    permissions_for_presence = manifest.get("permissions") if isinstance(manifest.get("permissions"), dict) else {}
    capability_report: dict[str, Any] | None = None
    capability_path = root / "capabilities.json"
    if capability_path.exists() or capability_path.is_symlink():
        capability_report = validate_capabilities(
            capability_path,
            findings,
            manifest=manifest,
            paid_tools_allowed=permissions_for_presence.get("paid_tools") is True,
        )
    web_research_allowed = permissions_for_presence.get("web_research") is True
    serp_path = root / "research/serp.json"
    if serp_path.exists() or serp_path.is_symlink():
        validate_serp(serp_path, findings, web_research_allowed=web_research_allowed)
    validate_source_acquisition_permissions(root / "research/sources.jsonl", web_research_allowed, findings)

    if status_rank >= RANK["content-ready"] or status == "needs-expert-review":
        roles = manifest.get("roles")
        required_roles = ("writer", "verifier", "editor")
        if not isinstance(roles, dict) or any(not substantive_actor_identity(roles.get(role)) for role in required_roles):
            findings.append(finding("ROLE_ASSIGNMENTS_INVALID", "P1", "Content-ready work requires non-empty writer, verifier, and editor role identities"))
        for relative in ("capabilities.json", "opportunity.md", "brief.md", "outline.md", "research/serp.json", "research/quality-gate.json", "research/query-decision.md", "research/intent-gap.md", "research/source-plan.md", "research/sources.jsonl", "claims.jsonl", "reviews/verification.json", "reviews/editorial.md", "handoff.md"):
            artifact = require_file(root, relative, findings)
            if artifact and artifact.suffix == ".md":
                artifact_text = artifact.read_text(encoding="utf-8")
                if contains_placeholder(artifact_text):
                    findings.append(finding("CONTENT_ARTIFACT_PLACEHOLDER", "P1", "Content-ready artifact contains an unresolved placeholder", path=relative))
                if not substantive_string(artifact_text) or contains_forbidden_document_control(artifact_text):
                    findings.append(finding("CONTENT_ARTIFACT_NOT_SUBSTANTIVE", "P1", "Content-ready text artifact lacks substantive visible content or contains forbidden Unicode controls", path=relative))
        validate_quality_gate(root, manifest, findings)
        validate_handoff(root, manifest, findings)
        verification = read_json(root / "reviews/verification.json", findings, "VERIFICATION")
        if isinstance(verification, dict):
            if verification.get("status") != "passed":
                findings.append(finding("VERIFICATION_NOT_PASSED", "P1", "Independent claim review did not pass", status=verification.get("status")))
            if not substantive_actor_identity(verification.get("reviewer")):
                findings.append(finding("VERIFICATION_REVIEWER_MISSING", "P1", "Claim review has no recorded reviewer"))
            validate_review_binding(
                root,
                manifest,
                verification,
                findings,
                review_type="verification",
                required_paths=CONTENT_REVIEW_PATHS,
            )
            if "independence_degraded" not in verification:
                findings.append(finding("INDEPENDENCE_STATE_MISSING", "P1", "Claim review must state whether independence was degraded"))
            elif verification.get("independence_degraded") is True:
                findings.append(finding("INDEPENDENCE_DEGRADED", "P2", "Verification used an isolated pass rather than a genuinely separate reviewer"))
            elif verification.get("independence_degraded") is not False:
                findings.append(finding("INDEPENDENCE_STATE_INVALID", "P1", "independence_degraded must be a boolean"))
            if isinstance(roles, dict):
                reviewer = verification.get("reviewer")
                writer_role = roles.get("writer")
                verifier_role = roles.get("verifier")
                if not nonempty_string(verifier_role) or reviewer != verifier_role:
                    findings.append(finding("VERIFICATION_ROLE_MISMATCH", "P1", "Verification reviewer must match the manifest verifier role"))
                if (
                    verification.get("independence_degraded") is False
                    and normalized_identity(writer_role)
                    and normalized_identity(writer_role) == normalized_identity(verifier_role)
                ):
                    findings.append(finding("VERIFICATION_INDEPENDENCE_CONFLICT", "P1", "Writer and verifier cannot share an identity while claiming non-degraded independence"))
        editorial = read_json(root / "reviews/editorial.json", findings, "EDITORIAL_REVIEW")
        if (
            isinstance(roles, dict)
            and normalized_identity(roles.get("writer"))
            and normalized_identity(roles.get("writer")) == normalized_identity(roles.get("editor"))
        ):
            findings.append(
                finding(
                    "EDITORIAL_INDEPENDENCE_CONFLICT",
                    "P1",
                    "The writer cannot approve the same draft as its editorial reviewer",
                )
            )
        if isinstance(editorial, dict):
            if editorial.get("status") != "passed":
                findings.append(finding("EDITORIAL_REVIEW_NOT_PASSED", "P1", "Editorial review did not pass", status=editorial.get("status")))
            editor_role = roles.get("editor") if isinstance(roles, dict) else None
            if not substantive_actor_identity(editor_role) or editorial.get("reviewer") != editor_role:
                findings.append(finding("EDITORIAL_REVIEWER_ROLE_MISMATCH", "P1", "Editorial reviewer must match manifest.roles.editor"))
            validate_review_binding(
                root,
                manifest,
                editorial,
                findings,
                review_type="editorial",
                required_paths=CONTENT_REVIEW_PATHS,
            )
            if "independence_degraded" not in editorial:
                findings.append(finding("EDITORIAL_INDEPENDENCE_STATE_MISSING", "P1", "Editorial review must state whether reviewer independence was degraded"))
            elif editorial.get("independence_degraded") is True:
                findings.append(finding("EDITORIAL_INDEPENDENCE_DEGRADED", "P2", "Editorial review used an isolated pass rather than a genuinely separate reviewer"))
            elif editorial.get("independence_degraded") is not False:
                findings.append(finding("EDITORIAL_INDEPENDENCE_STATE_INVALID", "P1", "editorial independence_degraded must be a boolean"))
            validate_editorial_quality_checks(editorial, findings)
        code, payload = child_validator(Path(__file__).with_name("validate_claims.py"), root)
        child_reports.append(payload)
        if code == 2:
            findings.append(finding("CLAIMS_VALIDATOR_UNAVAILABLE", "P1", "Claim validation could not run"))
        elif code == 1:
            findings.append(finding("CLAIMS_VALIDATOR_FAILED", "P1", "Claim ledger has hard failures"))

    ymyl = (manifest.get("risk") or {}).get("ymyl")
    if status == "needs-expert-review" and ymyl is not True:
        findings.append(finding("EXPERT_REVIEW_STATUS_RISK_MISMATCH", "P1", "needs-expert-review is reserved for runs classified as YMYL"))
    if (status_rank >= RANK["content-ready"] or status == "needs-expert-review") and ymyl == "auto":
        findings.append(finding("YMYL_UNRESOLVED", "P1", "YMYL classification remains auto at delivery"))
    if ymyl is True and status == "needs-expert-review":
        ymyl_review = read_json(root / "reviews/ymyl.json", findings, "YMYL_REVIEW", "P0")
        if isinstance(ymyl_review, dict):
            validate_review_binding(
                root,
                manifest,
                ymyl_review,
                findings,
                review_type="ymyl",
                required_paths=CONTENT_REVIEW_PATHS,
                severity="P1",
                time_field="requested_at",
            )
            if ymyl_review.get("review_required") is not True:
                findings.append(finding("YMYL_PENDING_FLAG_MISSING", "P0", "Pending YMYL review must explicitly record review_required=true"))
            if ymyl_review.get("status") not in {"pending", "needs-changes", "rejected"}:
                findings.append(finding("YMYL_PENDING_STATUS_INVALID", "P0", "needs-expert-review requires a truthful pending or failed review status", status=ymyl_review.get("status")))
            for field in ("scope", "jurisdiction"):
                if not nonempty_string(ymyl_review.get(field)):
                    findings.append(finding("YMYL_PENDING_FIELD_MISSING", "P1", "Pending YMYL review record is incomplete", field=field))
            if ymyl_review.get("jurisdiction") != (manifest.get("risk") or {}).get("jurisdiction"):
                findings.append(finding("YMYL_PENDING_JURISDICTION_MISMATCH", "P1", "Pending YMYL request jurisdiction must match manifest.risk.jurisdiction"))
            claims_for_review = ymyl_review.get("claims_requiring_review")
            if (
                not isinstance(claims_for_review, list)
                or not claims_for_review
                or any(not valid_identifier(item) for item in claims_for_review)
                or len(claims_for_review) != len(set(claims_for_review))
            ):
                findings.append(finding("YMYL_REVIEW_SCOPE_EMPTY", "P1", "Pending YMYL review must identify the claims or decisions needing expert review"))
            else:
                all_claim_ids, material_claim_ids = claim_scope_ids(root / "claims.jsonl")
                unknown_claim_ids = sorted(set(claims_for_review) - all_claim_ids)
                missing_material_ids = sorted(material_claim_ids - set(claims_for_review))
                if unknown_claim_ids:
                    findings.append(finding("YMYL_REVIEW_SCOPE_UNKNOWN", "P1", "Pending YMYL review references claim IDs absent from claims.jsonl", claim_ids=unknown_claim_ids))
                if missing_material_ids:
                    findings.append(finding("YMYL_REVIEW_SCOPE_INCOMPLETE", "P1", "Pending YMYL review must cover every material claim in the bound ledger", claim_ids=missing_material_ids))
    if ymyl is True and status_rank >= RANK["content-ready"]:
        ymyl_review = read_json(root / "reviews/ymyl.json", findings, "YMYL_REVIEW", "P0")
        if isinstance(ymyl_review, dict):
            ymyl_required_paths = CONTENT_REVIEW_PATHS
            if status_rank >= RANK["publish-package-ready"]:
                ymyl_required_paths = (*CONTENT_REVIEW_PATHS, "publish/publish-manifest.json")
            validate_review_binding(
                root,
                manifest,
                ymyl_review,
                findings,
                review_type="ymyl",
                required_paths=ymyl_required_paths,
                severity="P0",
            )
            if ymyl_review.get("review_required") is not True:
                findings.append(finding("YMYL_REVIEW_FLAG_MISSING", "P0", "Approved YMYL review must record review_required=true"))
            qualification_minimums = {"reviewer": 3, "credentials": 8, "scope": 12, "jurisdiction": 2}
            invalid_qualification = [
                field
                for field, minimum in qualification_minimums.items()
                if (
                    not substantive_string(ymyl_review.get(field), minimum)
                    or (field == "reviewer" and not substantive_actor_identity(ymyl_review.get(field), minimum))
                    or contains_placeholder(ymyl_review.get(field))
                )
            ]
            reviewed_sections = ymyl_review.get("sections_reviewed")
            normalized_sections = {
                unicodedata.normalize("NFKC", item).casefold().strip()
                for item in reviewed_sections
                if isinstance(item, str)
            } if isinstance(reviewed_sections, list) else set()
            if (
                not isinstance(reviewed_sections, list)
                or not reviewed_sections
                or any(not substantive_string(item, 3) or contains_placeholder(item) for item in reviewed_sections)
                or len(reviewed_sections) != len(normalized_sections)
            ):
                invalid_qualification.append("sections_reviewed")
            elif isinstance(reviewed_sections, list):
                valid_scope_labels = reviewable_scope_labels(root)
                unknown_sections = sorted(
                    item
                    for item in reviewed_sections
                    if " ".join(unicodedata.normalize("NFKC", item).casefold().split()) not in valid_scope_labels
                )
                if unknown_sections:
                    invalid_qualification.append("sections_reviewed")
                    findings.append(
                        finding(
                            "YMYL_REVIEW_SCOPE_UNKNOWN",
                            "P0",
                            "Approved YMYL review scope must name real draft headings, claim IDs, or claim locations",
                            sections=unknown_sections,
                        )
                    )
            claims_reviewed = ymyl_review.get("claims_reviewed")
            if (
                not isinstance(claims_reviewed, list)
                or not claims_reviewed
                or any(not valid_identifier(item) or contains_placeholder(item) for item in claims_reviewed)
                or len(claims_reviewed) != len(set(claims_reviewed))
            ):
                invalid_qualification.append("claims_reviewed")
            else:
                all_claim_ids, material_claim_ids = claim_scope_ids(root / "claims.jsonl")
                unknown_claim_ids = sorted(set(claims_reviewed) - all_claim_ids)
                missing_material_ids = sorted(material_claim_ids - set(claims_reviewed))
                if unknown_claim_ids or missing_material_ids:
                    invalid_qualification.append("claims_reviewed")
                    findings.append(
                        finding(
                            "YMYL_REVIEW_CLAIM_SCOPE_INVALID",
                            "P0",
                            "Approved YMYL review must explicitly cover every material claim ID",
                            unknown_claim_ids=unknown_claim_ids,
                            missing_material_ids=missing_material_ids,
                        )
                    )
            if invalid_qualification:
                findings.append(finding("YMYL_REVIEW_QUALIFICATION_EVIDENCE_MISSING", "P0", "Approved YMYL review requires typed, non-empty reviewer qualification and scope evidence", fields=invalid_qualification))
            if ymyl_review.get("status") != "approved":
                findings.append(finding("YMYL_REVIEW_NOT_APPROVED", "P0", "YMYL content lacks an approved qualified review", status=ymyl_review.get("status")))
            if ymyl_review.get("jurisdiction") != (manifest.get("risk") or {}).get("jurisdiction"):
                findings.append(finding("YMYL_REVIEW_JURISDICTION_MISMATCH", "P0", "Approved review jurisdiction does not match the run manifest"))
            expert_role = (manifest.get("roles") or {}).get("expert_reviewer")
            if not substantive_actor_identity(expert_role) or ymyl_review.get("reviewer") != expert_role:
                findings.append(finding("YMYL_REVIEWER_ROLE_MISMATCH", "P0", "Approved YMYL reviewer does not match the manifest expert_reviewer role"))
            writer_role = (manifest.get("roles") or {}).get("writer")
            if normalized_identity(writer_role) and normalized_identity(writer_role) == normalized_identity(expert_role):
                findings.append(finding("YMYL_REVIEW_INDEPENDENCE_CONFLICT", "P0", "The writer cannot approve its own YMYL review"))

    if mode in {"rewrite", "refresh"} and (status_rank >= RANK["content-ready"] or status == "needs-expert-review"):
        code, payload = child_validator(Path(__file__).with_name("diff_guard.py"), root)
        child_reports.append(payload)
        if code == 2:
            findings.append(finding("DIFF_VALIDATOR_UNAVAILABLE", "P1", "Rewrite/refresh diff validation could not run"))
        elif code == 1:
            findings.append(finding("DIFF_VALIDATOR_FAILED", "P1", "Rewrite/refresh preservation checks failed"))

    media_work_detected = False
    if status_rank >= RANK["content-ready"] or status == "needs-expert-review":
        media_work_detected = validate_media_integration(
            root,
            manifest,
            status_rank >= RANK["publish-package-ready"],
            findings,
            child_reports,
        )

    if status_rank >= RANK["publish-package-ready"]:
        validate_publish(root, manifest, media_work_detected, findings)

    if status_rank >= RANK["published-pending-verification"]:
        permissions = manifest.get("permissions") or {}
        if permissions.get("publish") is not True:
            findings.append(finding("PUBLISH_UNAUTHORIZED", "P0", "Published status is claimed without explicit publish permission"))
        destination = manifest.get("destination") or {}
        destination_url = destination.get("url")
        if not valid_document_url(destination_url):
            findings.append(finding("PUBLISHED_URL_INVALID", "P1", "Published status requires a canonical fragment-free HTTP(S) destination URL", value=destination_url))
        if receipt is None:
            candidate_receipt = read_json(root / "publish/publish-receipt.json", findings, "PUBLISH_RECEIPT")
            receipt = candidate_receipt if isinstance(candidate_receipt, dict) else None
        if isinstance(receipt, dict):
            receipt_fields = {
                "status",
                "published_at",
                "url",
                "actor",
                "permission_confirmed",
                "package_manifest_sha256",
            }
            if set(receipt) != receipt_fields:
                findings.append(finding("PUBLISH_RECEIPT_FIELDS_INVALID", "P1", "Publish receipt fields do not match the closed publication contract"))
            if receipt.get("status") != "published":
                findings.append(finding("PUBLISH_RECEIPT_STATUS_INVALID", "P1", "Publish receipt does not record a successful publication", status=receipt.get("status")))
            if parse_timestamp(receipt.get("published_at")) is None:
                findings.append(finding("PUBLISH_RECEIPT_TIME_INVALID", "P1", "Publish receipt requires a timezone-aware published_at timestamp"))
            if not urls_match(receipt.get("url"), destination_url):
                findings.append(finding("PUBLISH_RECEIPT_URL_MISMATCH", "P1", "Publish receipt URL does not match the manifest destination", receipt_url=receipt.get("url"), destination_url=destination_url))
            if not substantive_actor_identity(receipt.get("actor")):
                findings.append(finding("PUBLISH_RECEIPT_ACTOR_MISSING", "P1", "Publish receipt must record the publishing actor or system"))
            if receipt.get("permission_confirmed") is not True:
                findings.append(finding("PUBLISH_RECEIPT_PERMISSION_MISSING", "P0", "Publish receipt must record that publish permission was confirmed"))
            if not file_binding_matches(root, "publish/publish-manifest.json", receipt.get("package_manifest_sha256")):
                findings.append(finding("PUBLISH_RECEIPT_PACKAGE_BINDING_INVALID", "P0", "Publish receipt is not bound to the current publish manifest bytes"))

    if status_rank >= RANK["verified-live"]:
        if live is None:
            candidate_live = read_json(root / "reviews/live-verification.json", findings, "LIVE_VERIFICATION")
            live = candidate_live if isinstance(candidate_live, dict) else None
        if isinstance(live, dict):
            live_fields = {
                "status",
                "checked_at",
                "url",
                "package_manifest_sha256",
                "publish_receipt_sha256",
                "checks",
            }
            if set(live) != live_fields:
                findings.append(finding("LIVE_VERIFICATION_FIELDS_INVALID", "P1", "Live verification fields do not match the closed live contract"))
            destination_url = (manifest.get("destination") or {}).get("url")
            if live.get("status") != "passed":
                findings.append(finding("LIVE_VERIFICATION_NOT_PASSED", "P1", "Live verification did not pass", status=live.get("status")))
            if parse_timestamp(live.get("checked_at")) is None:
                findings.append(finding("LIVE_VERIFICATION_TIME_INVALID", "P1", "Live verification requires a timezone-aware checked_at timestamp"))
            if not urls_match(live.get("url"), destination_url):
                findings.append(finding("LIVE_VERIFICATION_URL_MISMATCH", "P1", "Live verification URL does not match the published destination", live_url=live.get("url"), destination_url=destination_url))
            if not file_binding_matches(root, "publish/publish-manifest.json", live.get("package_manifest_sha256")):
                findings.append(finding("LIVE_VERIFICATION_PACKAGE_BINDING_INVALID", "P0", "Live verification is not bound to the current publish manifest bytes"))
            if not file_binding_matches(root, "publish/publish-receipt.json", live.get("publish_receipt_sha256")):
                findings.append(finding("LIVE_VERIFICATION_RECEIPT_BINDING_INVALID", "P0", "Live verification is not bound to the current publication receipt"))
            checks = live.get("checks")
            required_checks = ("http", "rendered_content", "canonical", "indexability", "schema", "links", "assets")
            if not isinstance(checks, dict):
                findings.append(finding("LIVE_VERIFICATION_CHECKS_MISSING", "P1", "Live verification has no structured technical checks"))
            else:
                package_schema = quiet_json_object(root / "publish/schema.json")
                schema_applicable = not (
                    isinstance(package_schema, dict)
                    and package_schema.get("applicable") is False
                    and substantive_string(package_schema.get("reason"))
                )
                for check in required_checks:
                    outcome = checks.get(check)
                    allow_not_applicable = (
                        (check == "schema" and not schema_applicable)
                        or (check == "assets" and not media_work_detected)
                    )
                    valid_outcome = observed_check_acceptable(outcome, allow_not_applicable=allow_not_applicable)
                    if not valid_outcome:
                        findings.append(finding("LIVE_VERIFICATION_CHECK_FAILED", "P1", "Live verification check is missing, lacks substantive observation evidence, or did not pass", check=check, outcome=outcome))

    if status_rank >= RANK["measured"]:
        capability_providers = measurement_capability_providers(capability_report)
        baseline = read_json(root / "measurement/baseline.json", findings, "MEASUREMENT_BASELINE")
        baseline_meta: dict[str, Any] = {"window": None, "metrics": {}, "measured_at": None}
        if isinstance(baseline, dict):
            baseline_meta = validate_measurement_record(
                root,
                baseline,
                manifest,
                capability_providers,
                findings,
                record_type="baseline",
                path_label="measurement/baseline.json",
            )

        snapshots_dir = root / "measurement/snapshots"
        if path_uses_symlink(root, snapshots_dir):
            findings.append(finding("MEASUREMENT_SNAPSHOT_DIRECTORY_SYMLINK", "P0", "Measurement snapshot directory traverses a symlink"))
            snapshots: list[Path] = []
        else:
            snapshots = sorted(snapshots_dir.glob("*.json")) if snapshots_dir.is_dir() else []
        if not snapshots:
            findings.append(finding("MEASUREMENT_SNAPSHOT_MISSING", "P1", "Measured status has no post-publish snapshot"))
        receipt = quiet_json_object(root / "publish/publish-receipt.json")
        published_at = parse_timestamp(receipt.get("published_at")) if isinstance(receipt, dict) else None
        for snapshot_path in snapshots:
            relative_snapshot = snapshot_path.relative_to(root).as_posix()
            if (
                contains_forbidden_single_line_control(relative_snapshot)
                or unicodedata.normalize("NFC", relative_snapshot) != relative_snapshot
            ):
                findings.append(
                    finding(
                        "MEASUREMENT_SNAPSHOT_PATH_INVALID",
                        "P1",
                        "Measurement snapshot filenames must be canonical single-line paths without invisible or control characters",
                        path=relative_snapshot,
                    )
                )
            if path_uses_symlink(root, snapshot_path):
                findings.append(finding("MEASUREMENT_SNAPSHOT_SYMLINK", "P0", "Measurement snapshot traverses a symlink", path=relative_snapshot))
                continue
            snapshot = read_json(snapshot_path, findings, "MEASUREMENT_SNAPSHOT")
            if not isinstance(snapshot, dict):
                continue
            snapshot_meta = validate_measurement_record(
                root,
                snapshot,
                manifest,
                capability_providers,
                findings,
                record_type="snapshot",
                path_label=relative_snapshot,
            )
            baseline_time = baseline_meta.get("measured_at")
            snapshot_time = snapshot_meta.get("measured_at")
            if isinstance(baseline_time, datetime) and isinstance(snapshot_time, datetime) and snapshot_time <= baseline_time:
                findings.append(finding("MEASUREMENT_SNAPSHOT_NOT_POST_BASELINE", "P1", "Measurement snapshot must be later than the baseline", path=relative_snapshot))

            baseline_window = baseline_meta.get("window")
            snapshot_window = snapshot_meta.get("window")
            if isinstance(baseline_window, tuple) and isinstance(snapshot_window, tuple):
                baseline_start, baseline_end, baseline_zone, baseline_grain = baseline_window
                snapshot_start, snapshot_end, snapshot_zone, snapshot_grain = snapshot_window
                windows_comparable = (
                    baseline_end - baseline_start == snapshot_end - snapshot_start
                    and baseline_zone == snapshot_zone
                    and baseline_grain == snapshot_grain
                )
                if published_at is not None:
                    try:
                        publication_day = published_at.astimezone(ZoneInfo(baseline_zone)).date()
                    except (ZoneInfoNotFoundError, ValueError, TypeError):
                        publication_day = None
                    windows_comparable = windows_comparable and publication_day is not None and baseline_end <= publication_day and snapshot_start > publication_day
                if not windows_comparable:
                    findings.append(
                        finding(
                            "MEASUREMENT_WINDOW_NOT_COMPARABLE",
                            "P1",
                            "Baseline and snapshot must use equal durations, timezone, grain, and clean pre/post-publication windows",
                            path=relative_snapshot,
                        )
                    )

            baseline_metrics = baseline_meta.get("metrics") if isinstance(baseline_meta.get("metrics"), dict) else {}
            snapshot_metrics = snapshot_meta.get("metrics") if isinstance(snapshot_meta.get("metrics"), dict) else {}
            baseline_page_metrics = baseline_meta.get("page_metrics") if isinstance(baseline_meta.get("page_metrics"), set) else set()
            snapshot_page_metrics = snapshot_meta.get("page_metrics") if isinstance(snapshot_meta.get("page_metrics"), set) else set()
            shared_metric_ids = set(baseline_metrics).intersection(snapshot_metrics)
            descriptor_mismatches = sorted(
                metric_id for metric_id in shared_metric_ids if baseline_metrics[metric_id] != snapshot_metrics[metric_id]
            )
            if descriptor_mismatches:
                findings.append(
                    finding(
                        "MEASUREMENT_METRIC_DESCRIPTOR_MISMATCH",
                        "P1",
                        "Matching metric names have different provider, unit, aggregation, entity, channel, filter, or segment semantics",
                        path=relative_snapshot,
                        metrics=descriptor_mismatches,
                    )
                )
            if not any(baseline_metrics[metric_id] == snapshot_metrics[metric_id] for metric_id in shared_metric_ids):
                findings.append(finding("MEASUREMENT_METRICS_NOT_COMPARABLE", "P1", "No exact metric descriptor is shared by baseline and snapshot", path=relative_snapshot))
            shared_page_metric_ids = shared_metric_ids.intersection(baseline_page_metrics, snapshot_page_metrics)
            if not any(baseline_metrics[metric_id] == snapshot_metrics[metric_id] for metric_id in shared_page_metric_ids):
                findings.append(finding("MEASUREMENT_PAGE_METRICS_NOT_COMPARABLE", "P1", "Measured status requires at least one exact page-scoped metric shared by baseline and snapshot", path=relative_snapshot))

        decisions_path = require_file(root, "measurement/decisions.md", findings)
        if decisions_path:
            decisions = decisions_path.read_text(encoding="utf-8")
            if not substantive_string(decisions, 80) or contains_placeholder(decisions) or contains_forbidden_document_control(decisions):
                findings.append(finding("MEASUREMENT_DECISION_INVALID", "P1", "Measurement decision log must contain substantive visible text without placeholders or forbidden controls"))

    validate_event_timeline(root, manifest, status_rank, findings)

    if status == "blocked":
        findings.append(finding("RUN_BLOCKED", "P1", "Run is honestly marked blocked; resolve its blocking findings before delivery"))

    hard = [item for item in findings if item["severity"] in {"P0", "P1"}]
    report = {
        "validator": "run",
        "status": "failed" if hard else "passed",
        "actual_status": status,
        "summary": {
            "p0": sum(item["severity"] == "P0" for item in findings),
            "p1": sum(item["severity"] == "P1" for item in findings),
            "p2": sum(item["severity"] == "P2" for item in findings),
            "p3": sum(item["severity"] == "P3" for item in findings),
        },
        "findings": findings,
        "child_reports": child_reports,
        "limitations": [
            "Passing validates observable artifacts and declared states, not ranking outcomes.",
            "Semantic truth, usefulness, source entailment, fair use, and visual relevance require independent human or model review.",
        ],
    }
    print(json.dumps(report, indent=2 if args.pretty else None, ensure_ascii=True, allow_nan=False))
    return 1 if hard else 0


if __name__ == "__main__":
    try:
        exit_code = main()
    except Exception as exc:  # Fail closed on hostile or structurally unexpected input.
        print(
            json.dumps(
                {
                    "validator": "run",
                    "status": "unavailable",
                    "findings": [finding("VALIDATOR_INTERNAL_ERROR", "P1", "Run validation could not complete safely", error_type=type(exc).__name__, error=str(exc))],
                },
                ensure_ascii=True,
            )
        )
        exit_code = 2
    raise SystemExit(exit_code)
