#!/usr/bin/env python3
"""Validate source and claim ledgers without pretending to verify semantics."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from validate_run import normalized_visible_package_text


PLACEHOLDER = re.compile(r"(?:\[NEEDS[^\]]*\]|\bTODO\b|\bTBD\b|<placeholder>)", re.IGNORECASE)
IDENTIFIER = re.compile(r"^[A-Za-z0-9._-]+$")
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,127}$")
RFC3339_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\Z"
)
SOURCE_TYPES = {"official", "primary", "first-party", "user-provided", "secondary", "competitor"}
SOURCE_ACQUISITIONS = {"agent-web", "user-provided"}
ACCESS_STATES = {"accessible", "partial", "archived", "unavailable"}
CLASSIFICATIONS = {"load-bearing", "supporting", "opinion", "inference"}
SUPPORT_STATES = {"verified", "qualified", "partial", "contradicted", "unsupported", "pending", "not-applicable"}
FRESHNESS_STATES = {"current", "stale", "unknown", "not-applicable"}
CLAIM_TYPES = {"factual", "numeric", "quote", "experience", "opinion", "inference"}
MATERIAL_CLAIM_TYPES = {"factual", "numeric", "quote", "experience"}
AUTHORITATIVE_SOURCE_TYPES = {"official", "primary", "first-party"}
# A few Unicode characters are categorized as letters or symbols even though
# they intentionally render as blank. General-category checks alone would let
# them satisfy an evidence field.
INVISIBLE_VISIBLE_CATEGORY_EXCEPTIONS = {"\u115f", "\u1160", "\u2800", "\u3164", "\uffa0"}
ACTOR_INVISIBLE_CHARACTERS = INVISIBLE_VISIBLE_CATEGORY_EXCEPTIONS | {"\u034f"}
DEFAULT_IGNORABLE_RANGES = (
    (0x00AD, 0x00AD), (0x034F, 0x034F), (0x061C, 0x061C),
    (0x115F, 0x1160), (0x17B4, 0x17B5), (0x180B, 0x180F),
    (0x200B, 0x200F), (0x202A, 0x202E), (0x2060, 0x206F),
    (0x3164, 0x3164), (0xFE00, 0xFE0F), (0xFEFF, 0xFEFF),
    (0xFFA0, 0xFFA0), (0xFFF0, 0xFFF8), (0x1BCA0, 0x1BCA3),
    (0x1D173, 0x1D17A), (0xE0000, 0xE0FFF),
)
VISIBLE_CATEGORY_PREFIXES = {"L", "N", "P", "S"}
ALPHANUMERIC_CATEGORY_PREFIXES = {"L", "N"}
ACTIVE_ROOT: Path | None = None
FUTURE_TOLERANCE = timedelta(minutes=5)


def finding(code: str, severity: str, message: str, **evidence: Any) -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message, "evidence": evidence}


class JsonArgumentParser(argparse.ArgumentParser):
    """Return machine-readable argument failures on stdout."""

    def error(self, message: str) -> None:
        emit_report(
            {
                "validator": "claims",
                "status": "unavailable",
                "findings": [finding("ARGUMENTS_INVALID", "P1", "Invalid command-line arguments", error=message)],
            }
        )
        raise SystemExit(2)


def emit_report(report: dict[str, Any], *, pretty: bool = False) -> None:
    # ASCII escaping keeps even hostile unpaired-surrogate input representable
    # as valid JSON on a UTF-8 terminal.
    print(json.dumps(report, indent=2 if pretty else None, ensure_ascii=True, allow_nan=False))


def reject_nonfinite_json_constant(token: str) -> Any:
    raise ValueError(f"non-finite JSON number is not allowed: {token}")


def parse_finite_json_float(token: str) -> float:
    value = float(token)
    if not math.isfinite(value):
        raise ValueError(f"non-finite JSON number is not allowed: {token}")
    return value


def reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key is not allowed: {key!r}")
        result[key] = value
    return result


def strict_json_loads(text: str) -> Any:
    return json.loads(
        text,
        parse_constant=reject_nonfinite_json_constant,
        parse_float=parse_finite_json_float,
        object_pairs_hook=reject_duplicate_json_keys,
    )


def read_json(path: Path) -> Any:
    return strict_json_loads(path.read_text(encoding="utf-8"))


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


def valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or RFC3339_TIMESTAMP.fullmatch(value) is None:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def future_timestamp(value: Any) -> bool:
    if not valid_timestamp(value):
        return False
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed > datetime.now(timezone.utc) + FUTURE_TOLERANCE


def valid_as_of(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        date.fromisoformat(value[:10])
    except ValueError:
        return False
    return len(value) == 10 or valid_timestamp(value)


def future_as_of(value: Any) -> bool:
    if not valid_as_of(value):
        return False
    if len(str(value)) == 10:
        return date.fromisoformat(str(value)) > datetime.now(timezone.utc).date()
    return future_timestamp(value)


def nonempty_string(value: Any, minimum: int = 1) -> bool:
    """Match the schemas' exact string type and minimum-length constraints."""

    return isinstance(value, str) and len(value) >= minimum


def substantive_string(value: Any, minimum: int = 1) -> bool:
    """Require human evidence text with a Unicode letter or number.

    Separators, controls, format characters (including U+200B), combining marks
    without a visible base, private-use characters, surrogates, and unassigned
    code points cannot make an evidence field substantive on their own. Neither
    can punctuation, emoji, or other symbols without any letter or number.
    ``minimum`` is counted over real visible characters, not raw code points.
    """

    if not isinstance(value, str):
        return False
    visible = [
        character
        for character in value
        if character not in INVISIBLE_VISIBLE_CATEGORY_EXCEPTIONS
        and unicodedata.category(character)[0] in VISIBLE_CATEGORY_PREFIXES
    ]
    return len(visible) >= minimum and any(
        character not in INVISIBLE_VISIBLE_CATEGORY_EXCEPTIONS
        and unicodedata.category(character)[0] in ALPHANUMERIC_CATEGORY_PREFIXES
        for character in visible
    )


def substantive_actor_identity(value: Any) -> bool:
    """Require a visible single-line actor label without spoofing characters."""

    if not substantive_string(value) or contains_placeholder(value):
        return False
    return not any(
        ord(character) < 0x20
        or ord(character) == 0x7F
        or unicodedata.category(character).startswith("C")
        or unicodedata.category(character) in {"Zl", "Zp"}
        or character in ACTOR_INVISIBLE_CHARACTERS
        or is_default_ignorable(character)
        for character in value
    )


def is_default_ignorable(character: str) -> bool:
    codepoint = ord(character)
    return any(start <= codepoint <= end for start, end in DEFAULT_IGNORABLE_RANGES)


def normalized_identity(value: Any) -> str:
    """Canonical actor identity used for independence and role binding."""

    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    visible = "".join(
        character
        for character in normalized
        if not unicodedata.category(character).startswith("C")
        and unicodedata.category(character) not in {"Zl", "Zp"}
        and character not in ACTOR_INVISIBLE_CHARACTERS
        and not is_default_ignorable(character)
    )
    return " ".join(visible.split())


def contains_placeholder(value: Any) -> bool:
    return isinstance(value, str) and PLACEHOLDER.search(unicodedata.normalize("NFKC", value)) is not None


def contains_forbidden_record_control(value: Any) -> bool:
    """Reject controls that can reorder, hide, or split structured evidence."""

    if isinstance(value, str):
        return any(
            ord(character) < 0x20
            or ord(character) == 0x7F
            or unicodedata.category(character).startswith("C")
            or unicodedata.category(character) in {"Zl", "Zp"}
            or character in ACTOR_INVISIBLE_CHARACTERS
            or is_default_ignorable(character)
            for character in value
        )
    if isinstance(value, dict):
        return any(
            contains_forbidden_record_control(key)
            or contains_forbidden_record_control(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(contains_forbidden_record_control(item) for item in value)
    return False


def valid_identifier(value: Any) -> bool:
    return isinstance(value, str) and IDENTIFIER.fullmatch(value) is not None


def validate_manifest_contract(manifest: dict[str, Any], findings: list[dict[str, Any]]) -> tuple[bool, dict[str, str | None]]:
    """Validate the manifest fields that establish the claims-ledger context.

    This validator is intentionally usable on its own. It therefore cannot rely
    on validate_run.py to reject a malformed run identity or an invalid YMYL
    value before claim checks are applied.
    """

    basics = (("target", 1), ("language", 2))
    for field, minimum in basics:
        value = manifest.get(field)
        if not nonempty_string(value, minimum):
            findings.append(
                finding(
                    f"MANIFEST_{field.upper()}_INVALID",
                    "P1",
                    f"Manifest {field} must be a string with at least {minimum} character{'s' if minimum != 1 else ''}",
                    field=field,
                    value=value,
                )
            )

    run_id = manifest.get("run_id")
    if not isinstance(run_id, str) or RUN_ID.fullmatch(run_id) is None:
        findings.append(
            finding(
                "MANIFEST_RUN_ID_INVALID",
                "P1",
                "Manifest run_id must use 8-128 canonical ASCII identifier characters",
                field="run_id",
                value=run_id,
            )
        )

    risk = manifest.get("risk")
    ymyl = False
    if not isinstance(risk, dict):
        findings.append(finding("MANIFEST_RISK_INVALID", "P1", "Manifest risk must be an object", value=risk))
    else:
        ymyl_value = risk.get("ymyl")
        if not (type(ymyl_value) is bool or (isinstance(ymyl_value, str) and ymyl_value == "auto")):
            findings.append(
                finding(
                    "MANIFEST_YMYL_INVALID",
                    "P1",
                    "Manifest risk.ymyl must be exactly true, false, or 'auto'",
                    value=ymyl_value,
                )
            )
        else:
            ymyl = ymyl_value is True
        jurisdiction = risk.get("jurisdiction")
        if jurisdiction is not None and not isinstance(jurisdiction, str):
            findings.append(
                finding(
                    "MANIFEST_JURISDICTION_INVALID",
                    "P1",
                    "Manifest risk.jurisdiction must be a string or null",
                    value=jurisdiction,
                )
            )

    roles_value = manifest.get("roles", {})
    roles: dict[str, str | None] = {}
    if not isinstance(roles_value, dict):
        findings.append(finding("MANIFEST_ROLES_INVALID", "P1", "Manifest roles must be an object", value=roles_value))
    else:
        for role in ("writer", "verifier", "editor", "technical_reviewer", "expert_reviewer"):
            value = roles_value.get(role)
            if value is not None and not substantive_actor_identity(value):
                findings.append(
                    finding(
                        "MANIFEST_ROLE_INVALID",
                        "P1",
                        "Manifest role values must contain a Unicode letter or number, or be null",
                        role=role,
                        value=value,
                    )
                )
                roles[role] = None
            else:
                roles[role] = value
    return ymyl, roles


def read_jsonl(path: Path, label: str, findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if ACTIVE_ROOT is not None and path_uses_symlink(ACTIVE_ROOT, path):
        findings.append(finding("LEDGER_SYMLINK", "P0", f"Refusing to read {label} ledger through a symlink", path=str(path)))
        return []
    if not path.is_file():
        findings.append(finding("LEDGER_MISSING", "P1", f"Missing {label} ledger", path=str(path)))
        return []
    records: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        findings.append(finding("LEDGER_READ_FAILED", "P1", f"Cannot read {label} ledger", path=str(path), error=str(exc)))
        return records
    for line_number, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        try:
            value = strict_json_loads(raw)
        except ValueError as exc:
            findings.append(
                finding("LEDGER_JSON_INVALID", "P1", f"Invalid JSON in {label} ledger", path=str(path), line=line_number, error=str(exc))
            )
            continue
        if not isinstance(value, dict):
            findings.append(finding("LEDGER_RECORD_INVALID", "P1", f"{label} record must be an object", line=line_number))
            continue
        if contains_forbidden_record_control(value):
            findings.append(
                finding(
                    "LEDGER_UNICODE_CONTROL_INVALID",
                    "P1",
                    f"{label} record contains a forbidden line, bidi, zero-width, or surrogate control",
                    line=line_number,
                )
            )
        value["_line"] = line_number
        records.append(value)
    return records


def validate_ids(records: list[dict[str, Any]], field: str, label: str, findings: list[dict[str, Any]]) -> set[str]:
    seen: set[str] = set()
    for record in records:
        value = record.get(field)
        if not isinstance(value, str):
            findings.append(finding("ID_TYPE_INVALID", "P1", f"{label} {field} must be a string", value=value, line=record.get("_line")))
        elif not valid_identifier(value):
            findings.append(
                finding(
                    "ID_FORMAT_INVALID",
                    "P1",
                    f"{label} {field} must match ^[A-Za-z0-9._-]+$",
                    value=value,
                    line=record.get("_line"),
                )
            )
        elif value in seen:
            findings.append(finding("ID_DUPLICATE", "P1", f"Duplicate {field}", value=value, line=record.get("_line")))
        else:
            seen.add(value)
    return seen


def validate_string_array(
    value: Any,
    *,
    field: str,
    label: str,
    record_id: Any,
    findings: list[dict[str, Any]],
    identifiers: bool = False,
    substantive: bool = False,
    unique: bool = False,
) -> list[str]:
    if not isinstance(value, list):
        findings.append(
            finding(
                f"{label.upper()}_{field.upper()}_INVALID",
                "P1",
                f"{field} must be an array of strings",
                record_id=record_id,
                value=value,
            )
        )
        return []

    valid: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, str):
            findings.append(
                finding(
                    f"{label.upper()}_{field.upper()}_ITEM_INVALID",
                    "P1",
                    f"Every {field} item must be a string",
                    record_id=record_id,
                    index=index,
                    value=item,
                )
            )
            continue
        if identifiers and not valid_identifier(item):
            findings.append(
                finding(
                    f"{label.upper()}_{field.upper()}_ITEM_INVALID",
                    "P1",
                    f"Every {field} item must match ^[A-Za-z0-9._-]+$",
                    record_id=record_id,
                    index=index,
                    value=item,
                )
            )
            continue
        if substantive and not substantive_string(item):
            findings.append(
                finding(
                    f"{label.upper()}_{field.upper()}_ITEM_INVALID",
                    "P1",
                    f"Every {field} item must contain a Unicode letter or number",
                    record_id=record_id,
                    index=index,
                    value=item,
                )
            )
            continue
        if unique and item in seen:
            findings.append(
                finding(
                    f"{label.upper()}_{field.upper()}_DUPLICATE",
                    "P1",
                    f"{field} items must be unique",
                    record_id=record_id,
                    value=item,
                )
            )
            continue
        seen.add(item)
        valid.append(item)
    return valid


def validate_sources(sources: list[dict[str, Any]], findings: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    valid_ids = validate_ids(sources, "source_id", "source", findings)
    indexed: dict[str, dict[str, Any]] = {}
    required = (
        "source_id",
        "title",
        "locator",
        "publisher",
        "source_type",
        "acquisition",
        "retrieved_at",
        "access_status",
        "supported_claim_ids",
    )
    for source in sources:
        source_id = source.get("source_id")
        if valid_identifier(source_id) and source_id in valid_ids and source_id not in indexed:
            indexed[source_id] = source
        missing = [field for field in required if field not in source]
        if missing:
            findings.append(finding("SOURCE_FIELDS_MISSING", "P1", "Source record is incomplete", source_id=source_id, fields=missing))
        for field in ("title", "locator", "publisher"):
            value = source.get(field)
            if field in source and not substantive_string(value):
                findings.append(finding("SOURCE_FIELD_INVALID", "P1", "Required source fields must contain a Unicode letter or number", source_id=source_id, field=field, value=value))
        source_type = source.get("source_type")
        if not isinstance(source_type, str) or source_type not in SOURCE_TYPES:
            findings.append(finding("SOURCE_TYPE_INVALID", "P1", "Unknown source_type", source_id=source_id, value=source.get("source_type")))
        acquisition = source.get("acquisition")
        if not isinstance(acquisition, str) or acquisition not in SOURCE_ACQUISITIONS:
            findings.append(finding("SOURCE_ACQUISITION_INVALID", "P1", "Unknown source acquisition", source_id=source_id, value=acquisition))
        access_status = source.get("access_status")
        if not isinstance(access_status, str) or access_status not in ACCESS_STATES:
            findings.append(finding("SOURCE_ACCESS_INVALID", "P1", "Unknown access_status", source_id=source_id, value=source.get("access_status")))
        if not valid_timestamp(source.get("retrieved_at")):
            findings.append(finding("SOURCE_RETRIEVED_AT_INVALID", "P1", "Source retrieved_at must be a timezone-aware timestamp", source_id=source_id, value=source.get("retrieved_at")))
        elif future_timestamp(source.get("retrieved_at")):
            findings.append(finding("SOURCE_RETRIEVED_AT_FUTURE", "P1", "Source retrieved_at cannot be materially future-dated", source_id=source_id, value=source.get("retrieved_at")))
        for field in ("author", "published_at", "updated_at", "locale", "jurisdiction", "snapshot", "notes"):
            value = source.get(field)
            if value is not None and not isinstance(value, str):
                findings.append(finding("SOURCE_FIELD_TYPE_INVALID", "P1", "Optional source fields must be strings or null", source_id=source_id, field=field, value=value))
        for field in ("author", "notes"):
            value = source.get(field)
            if isinstance(value, str) and not substantive_string(value):
                findings.append(
                    finding(
                        "SOURCE_FIELD_INVALID",
                        "P1",
                        "Source author and notes must contain a Unicode letter or number when provided",
                        source_id=source_id,
                        field=field,
                        value=value,
                    )
                )
        if "supported_claim_ids" in source:
            validate_string_array(
                source.get("supported_claim_ids"),
                field="supported_claim_ids",
                label="source",
                record_id=source_id,
                findings=findings,
                identifiers=True,
                unique=True,
            )
        if "known_conflicts" in source:
            validate_string_array(
                source.get("known_conflicts"),
                field="known_conflicts",
                label="source",
                record_id=source_id,
                findings=findings,
                substantive=True,
            )
        for field in ("title", "locator", "publisher", "author", "jurisdiction", "notes"):
            value = source.get(field)
            if contains_placeholder(value):
                findings.append(finding("SOURCE_PLACEHOLDER", "P1", "Source record contains a placeholder", source_id=source_id, field=field))
        known_conflicts = source.get("known_conflicts")
        if isinstance(known_conflicts, list) and any(contains_placeholder(item) for item in known_conflicts):
            findings.append(finding("SOURCE_PLACEHOLDER", "P1", "Source record contains a placeholder", source_id=source_id, field="known_conflicts"))
    return indexed


def validate_claims(
    claims: list[dict[str, Any]],
    sources: dict[str, dict[str, Any]],
    ymyl: bool,
    roles: dict[str, str | None],
    draft_text: str,
    findings: list[dict[str, Any]],
) -> None:
    valid_claim_ids = validate_ids(claims, "claim_id", "claim", findings)
    claim_source_ids_by_id: dict[str, set[str]] = {}
    if not sources:
        findings.append(finding("SOURCE_LEDGER_EMPTY", "P1", "Content-ready evidence requires at least one valid source record"))
    if not claims:
        findings.append(finding("CLAIM_LEDGER_EMPTY", "P1", "Content-ready evidence requires at least one reviewed claim record"))
    writer = roles.get("writer")
    verifier_role = roles.get("verifier")
    visible_draft = normalized_visible_package_text(draft_text, ".md")
    normalized_draft = " ".join(re.findall(r"[^\W_]+", visible_draft, flags=re.UNICODE))
    if writer and verifier_role and normalized_identity(writer) == normalized_identity(verifier_role):
        findings.append(finding("REVIEW_NOT_INDEPENDENT", "P1", "Writer and verifier are the same recorded role", actor=writer))

    for claim in claims:
        claim_id = claim.get("claim_id")
        text = claim.get("text")
        classification = claim.get("classification")
        status = claim.get("support_status")
        freshness = claim.get("freshness_status")
        claim_type = claim.get("claim_type")
        source_ids = claim.get("source_ids")

        required = ("claim_id", "text", "location", "classification", "claim_type", "source_ids", "support_status", "freshness_status", "resolution")
        missing = [field for field in required if field not in claim]
        if missing:
            findings.append(finding("CLAIM_FIELDS_MISSING", "P1", "Claim record is incomplete", claim_id=claim_id, fields=missing))
        for field in ("text", "location", "resolution"):
            value = claim.get(field)
            if field in claim and not substantive_string(value):
                findings.append(finding("CLAIM_FIELD_INVALID", "P1", "Required claim fields must contain a Unicode letter or number", claim_id=claim_id, field=field, value=value))
        for field in ("text", "location", "resolution"):
            if contains_placeholder(claim.get(field)):
                findings.append(finding("CLAIM_PLACEHOLDER", "P0", "Claim record contains an unresolved placeholder", claim_id=claim_id, field=field))
        if not isinstance(classification, str) or classification not in CLASSIFICATIONS:
            findings.append(finding("CLAIM_CLASS_INVALID", "P1", "Unknown claim classification", claim_id=claim_id, value=classification))
        if not isinstance(status, str) or status not in SUPPORT_STATES:
            findings.append(finding("CLAIM_STATUS_INVALID", "P1", "Unknown support status", claim_id=claim_id, value=status))
        if not isinstance(freshness, str) or freshness not in FRESHNESS_STATES:
            findings.append(finding("CLAIM_FRESHNESS_INVALID", "P1", "Unknown freshness status", claim_id=claim_id, value=freshness))
        if not isinstance(claim_type, str) or claim_type not in CLAIM_TYPES:
            findings.append(finding("CLAIM_TYPE_INVALID", "P1", "Unknown claim_type", claim_id=claim_id, value=claim_type))
        elif isinstance(classification, str) and classification in CLASSIFICATIONS:
            allowed_classifications = (
                {"load-bearing", "supporting"}
                if claim_type in MATERIAL_CLAIM_TYPES
                else {claim_type}
            )
            if classification not in allowed_classifications:
                findings.append(
                    finding(
                        "CLAIM_TYPE_CLASSIFICATION_MISMATCH",
                        "P1",
                        "claim_type and classification describe incompatible evidence treatment",
                        claim_id=claim_id,
                        claim_type=claim_type,
                        classification=classification,
                    )
                )
        source_ids = validate_string_array(
            source_ids,
            field="source_ids",
            label="claim",
            record_id=claim_id,
            findings=findings,
            identifiers=True,
            unique=True,
        )
        if valid_identifier(claim_id) and claim_id in valid_claim_ids:
            claim_source_ids_by_id.setdefault(claim_id, set(source_ids))

        for field in ("exact_support", "verifier"):
            value = claim.get(field)
            if value is not None and not isinstance(value, str):
                findings.append(finding("CLAIM_FIELD_TYPE_INVALID", "P1", "Claim evidence fields must be strings or null", claim_id=claim_id, field=field, value=value))
            elif isinstance(value, str) and not substantive_string(value):
                findings.append(finding("CLAIM_FIELD_NOT_SUBSTANTIVE", "P1", "Claim evidence fields must contain a Unicode letter or number", claim_id=claim_id, field=field, value=value))
            elif contains_placeholder(value):
                findings.append(finding("CLAIM_PLACEHOLDER", "P0", "Claim evidence contains an unresolved placeholder", claim_id=claim_id, field=field))
        if claim.get("verifier") is not None and not substantive_actor_identity(claim.get("verifier")):
            findings.append(finding("CLAIM_VERIFIER_IDENTITY_INVALID", "P1", "Claim verifier must be a visible single-line actor identity", claim_id=claim_id))
        as_of = claim.get("as_of")
        if as_of is not None and not nonempty_string(as_of):
            findings.append(finding("CLAIM_FIELD_TYPE_INVALID", "P1", "Claim as_of must be a non-empty string or null", claim_id=claim_id, field="as_of", value=as_of))

        missing_sources = [source_id for source_id in source_ids if source_id not in sources]
        if missing_sources:
            findings.append(finding("CLAIM_SOURCE_UNKNOWN", "P1", "Claim references unknown sources", claim_id=claim_id, source_ids=missing_sources))

        material = isinstance(classification, str) and classification in {"load-bearing", "supporting"}
        normalized_claim_text = " ".join(
            re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", text).casefold(), flags=re.UNICODE)
        ) if isinstance(text, str) else ""
        if material and (not normalized_claim_text or normalized_claim_text not in normalized_draft):
            findings.append(
                finding(
                    "MATERIAL_CLAIM_NOT_IN_DRAFT",
                    "P0" if ymyl else "P1",
                    "Material claim text is not present in the current final draft",
                    claim_id=claim_id,
                )
            )
        if material and not source_ids:
            findings.append(finding("MATERIAL_CLAIM_UNSOURCED", "P0", "Material factual claim has no source", claim_id=claim_id))
        if material and (
            not substantive_string(claim.get("exact_support"))
            or contains_placeholder(claim.get("exact_support"))
        ):
            findings.append(finding("MATERIAL_EXACT_SUPPORT_MISSING", "P1", "Material claim lacks the verifier's exact source support or source-location note", claim_id=claim_id))
        if classification == "load-bearing" and status != "verified":
            findings.append(finding("LOAD_BEARING_NOT_VERIFIED", "P0", "Load-bearing claim is not verified", claim_id=claim_id, support_status=status))
        elif classification == "supporting" and status != "verified":
            findings.append(finding("SUPPORTING_NOT_VERIFIED", "P1", "Supporting factual claim is not verified", claim_id=claim_id, support_status=status))
        if status == "verified" and not source_ids:
            findings.append(finding("VERIFIED_WITHOUT_SOURCE", "P0", "Claim is marked verified without a source", claim_id=claim_id))
        if isinstance(status, str) and status in {"contradicted", "unsupported"}:
            findings.append(finding("CLAIM_UNRESOLVED", "P0" if classification == "load-bearing" else "P1", "Contradicted or unsupported claim remains in the ledger", claim_id=claim_id, support_status=status))
        if isinstance(status, str) and status in {"partial", "pending"} and material:
            findings.append(finding("CLAIM_PENDING", "P0" if classification == "load-bearing" else "P1", "Material claim remains partially supported or pending", claim_id=claim_id, support_status=status))
        if material and isinstance(freshness, str) and freshness in {"stale", "unknown"}:
            findings.append(finding("CLAIM_FRESHNESS_UNRESOLVED", "P1", "Material claim freshness is not current", claim_id=claim_id, freshness_status=freshness))
        if isinstance(classification, str) and classification in {"opinion", "inference"} and status == "verified":
            findings.append(finding("INFERENCE_MARKED_FACT", "P1", "Opinion or inference must not be marked verified fact", claim_id=claim_id))
        if isinstance(claim_type, str) and claim_type in {"quote", "numeric"} and (
            not substantive_string(claim.get("exact_support"))
            or contains_placeholder(claim.get("exact_support"))
        ):
            findings.append(finding("EXACT_SUPPORT_MISSING", "P1", "Quote or numeric claim lacks exact support context", claim_id=claim_id))
        verifier = claim.get("verifier")
        if material and (not substantive_string(verifier) or contains_placeholder(verifier)):
            findings.append(finding("CLAIM_VERIFIER_MISSING", "P1", "Material claim has no recorded verifier", claim_id=claim_id))
        if writer and verifier and normalized_identity(writer) == normalized_identity(verifier):
            findings.append(finding("CLAIM_SELF_VERIFIED", "P1", "Writer verified a material claim", claim_id=claim_id, actor=writer))
        if material and substantive_actor_identity(verifier) and (
            not substantive_actor_identity(verifier_role)
            or normalized_identity(verifier) != normalized_identity(verifier_role)
        ):
            findings.append(finding("CLAIM_VERIFIER_ROLE_MISMATCH", "P1", "Material claim verifier must match manifest.roles.verifier", claim_id=claim_id, verifier=verifier))

        usable_sources = [sources[source_id] for source_id in source_ids if source_id in sources]
        unavailable_sources = [source for source in usable_sources if source.get("access_status") == "unavailable"]
        if material and unavailable_sources:
            severity = "P1" if len(unavailable_sources) == len(usable_sources) else "P2"
            findings.append(finding("MATERIAL_SOURCE_UNAVAILABLE", severity, "A material claim depends on an unavailable source", claim_id=claim_id, source_ids=[source.get("source_id") for source in unavailable_sources]))
        if classification == "load-bearing" and usable_sources and all(s.get("source_type") == "competitor" for s in usable_sources):
            findings.append(finding("COMPETITOR_ONLY_EVIDENCE", "P1", "Load-bearing claim relies only on competitor content", claim_id=claim_id))
        if ymyl and material:
            if not valid_as_of(claim.get("as_of")):
                findings.append(finding("YMYL_AS_OF_MISSING", "P1", "Material YMYL claim requires a valid as_of date or timestamp", claim_id=claim_id))
            elif future_as_of(claim.get("as_of")):
                findings.append(finding("YMYL_AS_OF_FUTURE", "P1", "Material YMYL claim as_of cannot be future-dated", claim_id=claim_id))
            if not any(
                isinstance(source.get("source_type"), str)
                and source.get("source_type") in AUTHORITATIVE_SOURCE_TYPES
                and source.get("access_status") == "accessible"
                for source in usable_sources
            ):
                findings.append(finding("YMYL_AUTHORITATIVE_SOURCE_MISSING", "P1", "Material YMYL claim needs an accessible official, primary, or first-party source", claim_id=claim_id))

    # The ledgers form one evidence graph. Require an exact reciprocal edge so
    # neither side can silently claim support that the other side disowns.
    for claim_id, source_ids in claim_source_ids_by_id.items():
        for source_id in source_ids:
            source = sources.get(source_id)
            if source is None:
                continue  # CLAIM_SOURCE_UNKNOWN already reports this edge.
            supported = source.get("supported_claim_ids")
            if not isinstance(supported, list) or claim_id not in supported:
                findings.append(
                    finding(
                        "CLAIM_SOURCE_LINK_MISSING",
                        "P1",
                        "Claim-to-source evidence edge is not reciprocated by source.supported_claim_ids",
                        claim_id=claim_id,
                        source_id=source_id,
                    )
                )

    for source_id, source in sources.items():
        supported = source.get("supported_claim_ids")
        if not isinstance(supported, list):
            continue  # Source field/type validation already reports this.
        for claim_id in {item for item in supported if valid_identifier(item)}:
            if claim_id not in valid_claim_ids:
                findings.append(
                    finding(
                        "SOURCE_CLAIM_UNKNOWN",
                        "P1",
                        "Source references an unknown retained claim",
                        source_id=source_id,
                        claim_id=claim_id,
                    )
                )
            elif source_id not in claim_source_ids_by_id.get(claim_id, set()):
                findings.append(
                    finding(
                        "SOURCE_CLAIM_LINK_MISSING",
                        "P1",
                        "Source-to-claim evidence edge is not reciprocated by claim.source_ids",
                        source_id=source_id,
                        claim_id=claim_id,
                    )
                )


def main() -> int:
    argp = JsonArgumentParser(description=__doc__)
    argp.add_argument("run_dir", type=Path)
    argp.add_argument("--pretty", action="store_true")
    args = argp.parse_args()
    root = args.run_dir.expanduser().resolve()
    global ACTIVE_ROOT
    ACTIVE_ROOT = root
    findings: list[dict[str, Any]] = []

    manifest_path = root / "manifest.json"
    if path_uses_symlink(root, manifest_path):
        report = {"validator": "claims", "status": "failed", "findings": [finding("MANIFEST_SYMLINK", "P0", "Refusing to read manifest.json through a symlink", path=str(manifest_path))]}
        emit_report(report, pretty=args.pretty)
        return 1
    if not manifest_path.is_file():
        report = {"validator": "claims", "status": "unavailable", "findings": [finding("MANIFEST_MISSING", "P1", "manifest.json is missing", path=str(manifest_path))]}
        emit_report(report, pretty=args.pretty)
        return 2
    try:
        manifest = read_json(manifest_path)
    except (OSError, ValueError) as exc:
        report = {"validator": "claims", "status": "unavailable", "findings": [finding("MANIFEST_INVALID", "P1", "manifest.json cannot be read", error=str(exc))]}
        emit_report(report, pretty=args.pretty)
        return 2
    if not isinstance(manifest, dict):
        report = {"validator": "claims", "status": "unavailable", "findings": [finding("MANIFEST_TYPE_INVALID", "P1", "manifest.json must contain an object")]}
        emit_report(report, pretty=args.pretty)
        return 2

    source_records = read_jsonl(root / "research/sources.jsonl", "source", findings)
    claim_records = read_jsonl(root / "claims.jsonl", "claim", findings)
    ymyl, roles = validate_manifest_contract(manifest, findings)
    sources = validate_sources(source_records, findings)
    draft_path = root / "drafts/final.md"
    if path_uses_symlink(root, draft_path) or not draft_path.is_file():
        findings.append(finding("FINAL_DRAFT_UNAVAILABLE", "P1", "Material claim validation requires the current regular drafts/final.md artifact"))
        draft_text = ""
    else:
        try:
            draft_text = draft_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            findings.append(finding("FINAL_DRAFT_UNAVAILABLE", "P1", "Material claim validation could not read drafts/final.md"))
            draft_text = ""
    validate_claims(claim_records, sources, ymyl, roles, draft_text, findings)

    hard = [item for item in findings if item["severity"] in {"P0", "P1"}]
    report = {
        "validator": "claims",
        "status": "failed" if hard else "passed",
        "summary": {"sources": len(source_records), "claims": len(claim_records), "hard_failures": len(hard), "findings": len(findings)},
        "findings": findings,
        "limitations": ["Structural validation does not prove semantic entailment; an independent reviewer must inspect each material claim and source."],
    }
    emit_report(report, pretty=args.pretty)
    return 1 if hard else 0


if __name__ == "__main__":
    try:
        exit_code = main()
    except Exception as exc:  # Fail closed on hostile or structurally unexpected input.
        emit_report(
            {
                "validator": "claims",
                "status": "unavailable",
                "findings": [finding("VALIDATOR_INTERNAL_ERROR", "P1", "Claim validation could not complete safely", error_type=type(exc).__name__, error=str(exc))],
            }
        )
        exit_code = 2
    raise SystemExit(exit_code)
