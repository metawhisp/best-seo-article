#!/usr/bin/env python3
"""Offline capability preflight for the best-seo-article skill.

The preflight intentionally performs no network calls. It only evaluates
capabilities that the caller explicitly declares with flags, environment
variable *names*, or file paths. Environment values are never emitted.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn


SCHEMA_VERSION = "0.1"
CAPABILITIES: tuple[str, ...] = (
    "serp",
    "keywords",
    "gsc",
    "ga4",
    "crawl",
    "cwv",
    "fact_check",
    "images",
    "charts",
    "cms",
)
STATUSES: tuple[str, ...] = (
    "AVAILABLE",
    "USER_EXPORT",
    "FALLBACK",
    "UNAVAILABLE",
)
ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PROVIDER_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+ -]*$")
RFC3339_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\Z"
)
FORBIDDEN_FORMAT_CODEPOINTS = {
    0x061C, 0x180E, 0x200B, 0x200E, 0x200F,
    0x202A, 0x202B, 0x202C, 0x202D, 0x202E,
    0x2060, 0x2061, 0x2062, 0x2063, 0x2064,
    0x2066, 0x2067, 0x2068, 0x2069, 0xFEFF,
}
DEFAULT_IGNORABLE_RANGES = (
    (0x00AD, 0x00AD), (0x034F, 0x034F), (0x061C, 0x061C),
    (0x115F, 0x1160), (0x17B4, 0x17B5), (0x180B, 0x180F),
    (0x200B, 0x200F), (0x202A, 0x202E), (0x2060, 0x206F),
    (0x3164, 0x3164), (0xFE00, 0xFE0F), (0xFEFF, 0xFEFF),
    (0xFFA0, 0xFFA0), (0xFFF0, 0xFFF8), (0x1BCA0, 0x1BCA3),
    (0x1D173, 0x1D17A), (0xE0000, 0xE0FFF),
)

DEFAULT_FALLBACKS: dict[str, str] = {
    "serp": "manual-serp-capture",
    "keywords": "first-party-semantic-research",
    "crawl": "bounded-sitemap-http-review",
    "cwv": "manual-performance-checklist",
    "fact_check": "primary-source-claim-ledger",
    "images": "image-brief-and-owned-assets",
    "charts": "sourced-table-or-svg-spec",
    "cms": "cms-neutral-publish-package",
}

ABSENCE_EFFECTS: dict[str, str] = {
    "serp": (
        "Use a dated manual browser snapshot; limit claims to the observed query, "
        "locale, device, and results, without implying exhaustive or repeatable rank tracking."
    ),
    "keywords": (
        "Build a semantic map from first-party inputs only; leave volume, CPC, "
        "and difficulty unavailable."
    ),
    "gsc": (
        "No existing-query, cannibalization, or Google post-publish baseline; "
        "keep GSC measurement pending."
    ),
    "ga4": (
        "Do not claim engagement or conversion lift; keep GA4 measurement pending."
    ),
    "crawl": (
        "Limit conclusions to explicitly inspected URLs; do not claim full-site "
        "or orphan-page coverage."
    ),
    "cwv": (
        "Do not report Core Web Vitals; keep performance QA incomplete."
    ),
    "fact_check": (
        "Remove, qualify, or mark unsupported material claims; unresolved YMYL "
        "claims block editorial readiness."
    ),
    "images": (
        "Return image briefs, dimensions, alt text, and provenance requirements; "
        "do not invent image files or URLs."
    ),
    "charts": (
        "Return a sourced table or chart specification only; do not chart missing data."
    ),
    "cms": (
        "Create an agreed portable package or stop at content-ready; never claim CMS validation or publication."
    ),
}


def contains_forbidden_control(value: str) -> bool:
    """Reject line controls, bidi/zero-width spoofing, and surrogates in CLI values."""

    return any(
        ord(character) < 0x20
        or ord(character) == 0x7F
        or ord(character) in FORBIDDEN_FORMAT_CODEPOINTS
        or unicodedata.category(character).startswith("C")
        or unicodedata.category(character) in {"Zl", "Zp"}
        or any(start <= ord(character) <= end for start, end in DEFAULT_IGNORABLE_RANGES)
        for character in value
    )


def substantive_label(value: str) -> bool:
    """Require a safe human/provider label containing a real letter or number."""

    if contains_forbidden_control(value) or "\\" in value:
        return False
    normalized = unicodedata.normalize("NFKC", value)
    return value == normalized and PROVIDER_LABEL_PATTERN.fullmatch(value) is not None


def canonicalize_file_reference(reference: str) -> str:
    """Return a stable absolute path or a structured CLI error."""

    try:
        canonical = str(Path(reference).expanduser().resolve(strict=False))
    except (OSError, RuntimeError, ValueError) as exc:
        raise CliError(f"cannot canonicalize --file path {reference!r}: {exc}") from exc
    if contains_forbidden_control(canonical):
        raise CliError("canonical --file path contains a forbidden control character")
    return canonical


class CliError(ValueError):
    """Raised when CLI declarations are invalid or ambiguous."""


class JsonArgumentParser(argparse.ArgumentParser):
    """Argument parser that lets the caller render failures as JSON."""

    def error(self, message: str) -> NoReturn:
        """Raise a structured CLI error instead of printing text and exiting."""
        raise CliError(message)


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser.

    Returns:
        Configured parser for the offline preflight.
    """
    parser = JsonArgumentParser(
        description=(
            "Report SEO workflow capability states without network calls or "
            "secret disclosure."
        )
    )
    parser.add_argument(
        "--available",
        action="append",
        default=[],
        metavar="CAPABILITY=LABEL",
        help="Explicitly declare a local tool or process available.",
    )
    parser.add_argument(
        "--env",
        action="append",
        default=[],
        metavar="CAPABILITY=ENV_NAME",
        help=(
            "Probe an explicitly named environment variable. Repeat for providers "
            "that require multiple variables; all named variables must be non-empty."
        ),
    )
    parser.add_argument(
        "--file",
        action="append",
        default=[],
        metavar="CAPABILITY=PATH",
        help=(
            "Probe an explicit local user-export path. Repeat to require multiple "
            "files; all paths must be readable regular files."
        ),
    )
    parser.add_argument(
        "--provider",
        action="append",
        default=[],
        metavar="CAPABILITY=NAME",
        help="Name the provider associated with an explicit probe.",
    )
    parser.add_argument(
        "--cost",
        action="append",
        default=[],
        metavar="CAPABILITY=free|paid|unknown",
        help=(
            "Classify the execution cost. Omitted non-file probes default to "
            "unknown and therefore require approval."
        ),
    )
    parser.add_argument(
        "--approve-cost",
        action="append",
        default=[],
        choices=CAPABILITIES,
        metavar="CAPABILITY",
        help="Explicitly approve possible paid use for one capability.",
    )
    parser.add_argument(
        "--fallback",
        action="append",
        default=[],
        metavar="CAPABILITY=LABEL",
        help="Replace or add a non-network fallback for one capability.",
    )
    parser.add_argument(
        "--disable-fallback",
        action="append",
        default=[],
        choices=CAPABILITIES,
        metavar="CAPABILITY",
        help="Disable the built-in fallback for one capability.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON instead of emitting compact JSON.",
    )
    parser.add_argument(
        "--checked-at",
        metavar="RFC3339",
        help=(
            "Override the UTC observation time for reproducible fixtures. "
            "Defaults to the current UTC time."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {SCHEMA_VERSION}",
    )
    return parser


def normalize_checked_at(value: str | None) -> str:
    """Return a canonical RFC 3339 UTC timestamp.

    Args:
        value: Optional caller-supplied timestamp. A timezone is mandatory when
            a value is supplied.

    Returns:
        UTC timestamp with second precision and a ``Z`` suffix.

    Raises:
        CliError: If the supplied timestamp is malformed or lacks a timezone.
    """
    if value is None:
        observed_at = datetime.now(timezone.utc)
    else:
        if RFC3339_TIMESTAMP.fullmatch(value) is None:
            raise CliError(
                f"--checked-at expects an RFC 3339 timestamp, got {value!r}"
            )
        try:
            observed_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise CliError(
                f"--checked-at expects an RFC 3339 timestamp, got {value!r}"
            ) from error
        if observed_at.tzinfo is None:
            raise CliError("--checked-at must include a timezone or Z suffix")
    try:
        return (
            observed_at.astimezone(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
    except (OverflowError, OSError, ValueError) as error:
        raise CliError(
            f"--checked-at cannot be normalized safely, got {value!r}"
        ) from error


def parse_single_assignments(
    values: Sequence[str], option_name: str
) -> dict[str, str]:
    """Parse unique ``CAPABILITY=value`` declarations.

    Args:
        values: Raw assignment strings from argparse.
        option_name: Human-readable option name for errors.

    Returns:
        Mapping from capability to its declared value.

    Raises:
        CliError: If syntax, capability, value, or uniqueness is invalid.
    """
    parsed: dict[str, str] = {}
    for raw_value in values:
        capability, separator, value = raw_value.partition("=")
        capability = capability.strip()
        value = value.strip()
        if not separator or not capability or not value:
            raise CliError(
                f"{option_name} expects CAPABILITY=value, got {raw_value!r}"
            )
        if contains_forbidden_control(value):
            raise CliError(f"{option_name} value contains a forbidden control character")
        if option_name in {"--available", "--provider", "--fallback"} and not substantive_label(value):
            raise CliError(f"{option_name} value must contain a substantive letter or number")
        if capability not in CAPABILITIES:
            raise CliError(
                f"unknown capability {capability!r} for {option_name}; "
                f"expected one of {', '.join(CAPABILITIES)}"
            )
        if capability in parsed:
            raise CliError(
                f"duplicate {option_name} declaration for {capability!r}"
            )
        parsed[capability] = value
    return parsed


def parse_multi_assignments(
    values: Sequence[str], option_name: str
) -> dict[str, list[str]]:
    """Parse repeatable ``CAPABILITY=value`` declarations.

    Args:
        values: Raw assignment strings from argparse.
        option_name: Human-readable option name for errors.

    Returns:
        Mapping from capability to one or more unique values.

    Raises:
        CliError: If syntax, capability, value, or uniqueness is invalid.
    """
    parsed: dict[str, list[str]] = {}
    for raw_value in values:
        capability, separator, value = raw_value.partition("=")
        capability = capability.strip()
        value = value.strip()
        if not separator or not capability or not value:
            raise CliError(
                f"{option_name} expects CAPABILITY=value, got {raw_value!r}"
            )
        if contains_forbidden_control(value):
            raise CliError(f"{option_name} value contains a forbidden control character")
        if capability not in CAPABILITIES:
            raise CliError(
                f"unknown capability {capability!r} for {option_name}; "
                f"expected one of {', '.join(CAPABILITIES)}"
            )
        entries = parsed.setdefault(capability, [])
        if value in entries:
            raise CliError(
                f"duplicate {option_name} value for {capability!r}: {value!r}"
            )
        entries.append(value)
    return parsed


def validate_inputs(
    available: Mapping[str, str],
    env_names: Mapping[str, list[str]],
    file_paths: Mapping[str, list[str]],
    providers: Mapping[str, str],
    costs: Mapping[str, str],
    approvals: set[str],
) -> None:
    """Reject ambiguous probes and unsafe cost declarations.

    Args:
        available: Explicit local availability declarations.
        env_names: Explicit environment variable names to probe.
        file_paths: Explicit export paths to probe.
        providers: Provider labels associated with probes.
        costs: Provider cost classifications.
        approvals: Capabilities with explicit cost approval.

    Raises:
        CliError: If declarations are ambiguous or inconsistent.
    """
    probe_capabilities = set(available) | set(env_names) | set(file_paths)
    for capability in CAPABILITIES:
        probe_kinds = sum(
            (
                capability in available,
                capability in env_names,
                capability in file_paths,
            )
        )
        if probe_kinds > 1:
            raise CliError(
                f"{capability!r} has multiple probe kinds; choose exactly one of "
                "--available, --env, or --file"
            )

    for capability in set(providers) | set(costs) | approvals:
        if capability not in probe_capabilities:
            raise CliError(
                f"{capability!r} declares provider/cost metadata without an "
                "explicit --available, --env, or --file probe"
            )

    for capability, names in env_names.items():
        invalid_names = [name for name in names if not ENV_NAME_PATTERN.fullmatch(name)]
        if invalid_names:
            raise CliError(
                f"invalid environment variable name for {capability!r}: "
                f"{invalid_names[0]!r}"
            )

    for capability, cost in costs.items():
        if cost not in {"free", "paid", "unknown"}:
            raise CliError(
                f"invalid cost for {capability!r}: {cost!r}; expected free, "
                "paid, or unknown"
            )
        if capability in file_paths:
            raise CliError(
                f"{capability!r} uses a local user export; do not attach "
                "provider execution cost to --file"
            )

    for capability in approvals:
        if capability in file_paths:
            raise CliError(
                f"{capability!r} uses a local user export and cannot require "
                "cost approval"
            )
        if costs.get(capability, "unknown") == "free":
            raise CliError(
                f"{capability!r} is declared free; --approve-cost is unnecessary"
            )


def inspect_probe(
    capability: str,
    available: Mapping[str, str],
    env_names: Mapping[str, list[str]],
    file_paths: Mapping[str, list[str]],
    environ: Mapping[str, str],
) -> tuple[str, list[str], bool, int, int]:
    """Inspect the one explicit probe allowed for a capability.

    Args:
        capability: Capability identifier.
        available: Explicit local availability declarations.
        env_names: Environment variable names to inspect.
        file_paths: User-export paths to inspect.
        environ: Environment mapping supplied by the caller.

    Returns:
        Probe kind, references, aggregate presence, present count, and required
        count. No environment value is returned.
    """
    if capability in available:
        return "explicit-flag", [available[capability]], True, 1, 1

    if capability in env_names:
        references = env_names[capability]
        present_count = sum(
            bool(environ.get(name, "").strip()) for name in references
        )
        required_count = len(references)
        return (
            "environment",
            list(references),
            present_count == required_count,
            present_count,
            required_count,
        )

    if capability in file_paths:
        references = file_paths[capability]
        present_count = 0
        for reference in references:
            path = Path(reference)
            try:
                usable = (
                    not path.is_symlink()
                    and path.is_file()
                    and path.stat().st_size > 0
                    and os.access(path, os.R_OK)
                )
            except OSError:
                usable = False
            present_count += int(usable)
        required_count = len(references)
        return (
            "file",
            list(references),
            present_count == required_count,
            present_count,
            required_count,
        )

    return "none", [], False, 0, 0


def select_fallback(
    capability: str,
    custom_fallbacks: Mapping[str, str],
    disabled_fallbacks: set[str],
) -> tuple[str | None, str]:
    """Resolve a configured or built-in fallback.

    Args:
        capability: Capability identifier.
        custom_fallbacks: Caller-provided fallback labels.
        disabled_fallbacks: Capabilities whose defaults are disabled.

    Returns:
        Fallback label and its selection source, or ``None`` and ``none``.
    """
    if capability in custom_fallbacks:
        return custom_fallbacks[capability], "configured-fallback"
    if capability in disabled_fallbacks:
        return None, "none"
    if capability in DEFAULT_FALLBACKS:
        return DEFAULT_FALLBACKS[capability], "builtin-fallback"
    return None, "none"


def build_capability_state(
    capability: str,
    available: Mapping[str, str],
    env_names: Mapping[str, list[str]],
    file_paths: Mapping[str, list[str]],
    providers: Mapping[str, str],
    costs: Mapping[str, str],
    approvals: set[str],
    custom_fallbacks: Mapping[str, str],
    disabled_fallbacks: set[str],
    environ: Mapping[str, str],
) -> dict[str, object]:
    """Build one deterministic capability state.

    Args:
        capability: Capability identifier.
        available: Explicit local availability declarations.
        env_names: Environment variable names to inspect.
        file_paths: User-export paths to inspect.
        providers: Provider labels associated with probes.
        costs: Provider cost classifications.
        approvals: Capabilities with explicit cost approval.
        custom_fallbacks: Caller-defined fallback labels.
        disabled_fallbacks: Capabilities with disabled default fallbacks.
        environ: Environment mapping supplied by the caller.

    Returns:
        JSON-serializable capability state.
    """
    probe_kind, references, present, present_count, required_count = inspect_probe(
        capability, available, env_names, file_paths, environ
    )

    if probe_kind == "none":
        candidate_provider: str | None = None
        cost_kind = "none"
    elif probe_kind == "file":
        candidate_provider = providers.get(capability, "user-export")
        cost_kind = "free"
    elif probe_kind == "explicit-flag":
        candidate_provider = providers.get(capability, available[capability])
        cost_kind = costs.get(capability, "unknown")
    else:
        candidate_provider = providers.get(capability, "environment-provider")
        cost_kind = costs.get(capability, "unknown")

    approval_required = cost_kind in {"paid", "unknown"}
    approved = approval_required and capability in approvals
    candidate_usable = present and (not approval_required or approved)
    fallback, fallback_source = select_fallback(
        capability, custom_fallbacks, disabled_fallbacks
    )

    if probe_kind == "file" and present:
        status = "USER_EXPORT"
        selected_provider = candidate_provider
        selected_by = "user-export"
        reason_code = "USER_EXPORT_PRESENT"
    elif probe_kind in {"explicit-flag", "environment"} and candidate_usable:
        status = "AVAILABLE"
        selected_provider = candidate_provider
        selected_by = probe_kind
        reason_code = "EXPLICIT_CAPABILITY_AVAILABLE"
    elif fallback is not None:
        status = "FALLBACK"
        selected_provider = fallback
        selected_by = fallback_source
        if probe_kind == "none":
            reason_code = "FREE_FALLBACK_SELECTED"
        elif not present:
            reason_code = "PROBE_NOT_PRESENT_FALLBACK_SELECTED"
        else:
            reason_code = "COST_APPROVAL_REQUIRED_FALLBACK_SELECTED"
    else:
        status = "UNAVAILABLE"
        selected_provider = None
        selected_by = "none"
        if probe_kind == "none":
            reason_code = "NO_PROVIDER_OR_EXPORT"
        elif not present:
            reason_code = "PROBE_NOT_PRESENT"
        else:
            reason_code = "COST_APPROVAL_REQUIRED"

    return {
        "status": status,
        "selected_provider": selected_provider,
        "selected_by": selected_by,
        "candidate": {
            "provider": candidate_provider,
            "probe": {
                "kind": probe_kind,
                "references": references,
                "present": present,
                "present_count": present_count,
                "required_count": required_count,
            },
            "cost": {
                "kind": cost_kind,
                "approval_required": approval_required,
                "approved": approved,
            },
        },
        "reason_code": reason_code,
        "absence_effect": ABSENCE_EFFECTS[capability],
    }


def build_report(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, object]:
    """Build the complete capability report from parsed declarations.

    Args:
        args: Parsed command-line arguments.
        environ: Environment mapping to inspect by explicit name only.

    Returns:
        JSON-serializable report conforming to capabilities.schema.json.

    Raises:
        CliError: If declarations are invalid or ambiguous.
    """
    available = parse_single_assignments(args.available, "--available")
    env_names = parse_multi_assignments(args.env, "--env")
    raw_file_paths = parse_multi_assignments(args.file, "--file")
    file_paths = {
        capability: [canonicalize_file_reference(reference) for reference in references]
        for capability, references in raw_file_paths.items()
    }
    for capability, references in file_paths.items():
        normalized_references = [unicodedata.normalize("NFC", reference) for reference in references]
        existing_identities: list[tuple[int, int]] = []
        for reference in references:
            try:
                stat_result = Path(reference).stat()
            except OSError:
                continue
            existing_identities.append((stat_result.st_dev, stat_result.st_ino))
        if (
            len(references) != len(set(references))
            or len(normalized_references) != len(set(normalized_references))
            or len(existing_identities) != len(set(existing_identities))
        ):
            raise CliError(
                f"duplicate --file paths for {capability!r} resolve to the same canonical file"
            )
    providers = parse_single_assignments(args.provider, "--provider")
    costs = parse_single_assignments(args.cost, "--cost")
    custom_fallbacks = parse_single_assignments(args.fallback, "--fallback")
    approvals = set(args.approve_cost)
    disabled_fallbacks = set(args.disable_fallback)
    checked_at = normalize_checked_at(args.checked_at)

    overlap = set(custom_fallbacks) & disabled_fallbacks
    if overlap:
        capability = sorted(overlap)[0]
        raise CliError(
            f"{capability!r} cannot use --fallback and --disable-fallback together"
        )

    validate_inputs(
        available, env_names, file_paths, providers, costs, approvals
    )

    capability_states = {
        capability: build_capability_state(
            capability,
            available,
            env_names,
            file_paths,
            providers,
            costs,
            approvals,
            custom_fallbacks,
            disabled_fallbacks,
            environ,
        )
        for capability in CAPABILITIES
    }

    counts = {
        status: sum(
            state["status"] == status for state in capability_states.values()
        )
        for status in STATUSES
    }
    usable_capabilities = [
        capability
        for capability, state in capability_states.items()
        if state["status"] != "UNAVAILABLE"
    ]
    unavailable_capabilities = [
        capability
        for capability, state in capability_states.items()
        if state["status"] == "UNAVAILABLE"
    ]
    cost_approval_blocked_capabilities = [
        capability
        for capability, state in capability_states.items()
        if state["candidate"]["probe"]["present"]
        and state["candidate"]["cost"]["approval_required"]
        and not state["candidate"]["cost"]["approved"]
    ]
    limitations = [
        f"{capability} [{state['status']}]: {state['absence_effect']}"
        for capability, state in capability_states.items()
        if state["status"] in {"FALLBACK", "UNAVAILABLE"}
    ]

    return {
        "schema_version": SCHEMA_VERSION,
        "checked_at": checked_at,
        "generated_by": "capability_preflight.py",
        "policy": {
            "network_calls_made": False,
            "secret_values_emitted": False,
            "paid_use_requires_explicit_approval": True,
            "unknown_cost_requires_explicit_approval": True,
        },
        "capabilities": capability_states,
        "limitations": limitations,
        "summary": {
            "counts": counts,
            "usable_capabilities": usable_capabilities,
            "unavailable_capabilities": unavailable_capabilities,
            "cost_approval_blocked_capabilities": (
                cost_approval_blocked_capabilities
            ),
            "all_capabilities_usable": not unavailable_capabilities,
            "degraded": bool(
                counts["FALLBACK"] or counts["UNAVAILABLE"]
            ),
        },
    }


def emit_error(message: str) -> None:
    """Emit a machine-readable CLI error without a traceback."""
    document = {
        "error": {
            "code": "INVALID_ARGUMENTS",
            "message": message,
        }
    }
    print(json.dumps(document, ensure_ascii=False, separators=(",", ":")), file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the preflight and emit exactly one JSON document.

    Args:
        argv: Optional argument sequence; defaults to ``sys.argv``.

    Returns:
        Process exit code: 0 for a report and 2 for invalid declarations.
    """
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        report = build_report(args, os.environ)
    except CliError as error:
        emit_error(str(error))
        return 2

    indent = 2 if args.pretty else None
    separators = None if args.pretty else (",", ":")
    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=indent,
            separators=separators,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
