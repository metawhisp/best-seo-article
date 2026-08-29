#!/usr/bin/env python3
"""Check rewrite/refresh preservation invariants and produce a traceable diff report."""

from __future__ import annotations

import argparse
import difflib
import errno
import ipaddress
import json
import math
import os
import re
import secrets
import stat
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from validate_run import (
    contains_forbidden_document_control,
    contains_forbidden_single_line_control,
    substantive_string,
    valid_http_url,
)


HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)
LINK = re.compile(r"\[[^\]]+\]\(([^)\s]+)(?:\s+[^)]*)?\)")
FENCE_OPEN = re.compile(r"^ {0,3}(?P<fence>`{3,}|~{3,})(?P<info>.*)$")
REPORT_NAME = "diff-report.json"
URL_FIELDS = ("url", "original_url", "source_url", "canonical", "canonical_url", "page")
DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z", re.IGNORECASE)


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


def norm(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def blank_markdown(value: str) -> str:
    """Blank Markdown syntax/content while preserving line boundaries."""

    return "".join(character if character in "\r\n" else " " for character in value)


def strip_fenced_code(value: str) -> str:
    """Remove CommonMark-like fenced code blocks before structural extraction.

    Openers may be indented by up to three spaces and use at least three
    backticks or tildes. A closer must use the same character and at least the
    opener length. Unclosed fences consume the rest of the document, matching
    CommonMark's safety-relevant behavior.
    """

    output: list[str] = []
    fence_character: str | None = None
    fence_length = 0
    for line in value.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        if fence_character is None:
            match = FENCE_OPEN.fullmatch(content)
            if match is None:
                output.append(line)
                continue
            fence = match.group("fence")
            info = match.group("info")
            # A backtick fence cannot have a backtick in its info string.
            if fence[0] == "`" and "`" in info:
                output.append(line)
                continue
            fence_character = fence[0]
            fence_length = len(fence)
            output.append(blank_markdown(line))
            continue

        closer = re.fullmatch(rf" {{0,3}}{re.escape(fence_character)}{{{fence_length},}}[ \t]*", content)
        output.append(blank_markdown(line))
        if closer is not None:
            fence_character = None
            fence_length = 0

    return "".join(output)


def strip_inline_code(value: str) -> str:
    """Blank matched backtick code spans, including multiline spans.

    Delimiter runs close only on a run of the same length. Unmatched runs stay
    literal so they cannot accidentally hide a later ordinary heading or link.
    """

    output = list(value)
    cursor = 0
    length = len(value)
    while cursor < length:
        if value[cursor] != "`":
            cursor += 1
            continue
        opener_end = cursor + 1
        while opener_end < length and value[opener_end] == "`":
            opener_end += 1
        delimiter_length = opener_end - cursor

        search = opener_end
        closer_end: int | None = None
        while search < length:
            candidate = value.find("`", search)
            if candidate < 0:
                break
            candidate_end = candidate + 1
            while candidate_end < length and value[candidate_end] == "`":
                candidate_end += 1
            if candidate_end - candidate == delimiter_length:
                closer_end = candidate_end
                break
            search = candidate_end

        if closer_end is None:
            cursor = opener_end
            continue
        for index in range(cursor, closer_end):
            if output[index] not in "\r\n":
                output[index] = " "
        cursor = closer_end
    return "".join(output)


def markdown_for_structure(value: str) -> str:
    """Return Markdown with non-rendered code removed for heading/link checks."""

    return strip_inline_code(strip_fenced_code(value))


def finding(code: str, severity: str, message: str, **evidence: Any) -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message, "evidence": evidence}


def emit(report: dict[str, Any], pretty: bool) -> None:
    print(json.dumps(report, indent=2 if pretty else None, ensure_ascii=True, allow_nan=False))


def safe_human_text(value: Any, minimum: int = 1) -> bool:
    """Require visible single-line evidence text without spoofing controls."""

    return substantive_string(value, minimum) and not contains_forbidden_single_line_control(value)


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        emit(
            {
                "validator": "diff",
                "status": "unavailable",
                "findings": [finding("ARGUMENTS_INVALID", "P1", "Invalid command-line arguments", error=message)],
            },
            False,
        )
        raise SystemExit(2)


class ArtifactAccessError(Exception):
    def __init__(self, code: str, message: str, path: Path, error: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.path = path
        self.error = error

    def evidence(self) -> dict[str, Any]:
        result: dict[str, Any] = {"path": str(self.path), "reason": self.code}
        if self.error:
            result["error"] = self.error
        return result


FileIdentity = tuple[int, int, int]


def file_identity(file_stat: os.stat_result) -> FileIdentity:
    return (file_stat.st_dev, file_stat.st_ino, stat.S_IFMT(file_stat.st_mode))


def nofollow_flag() -> int:
    value = getattr(os, "O_NOFOLLOW", None)
    if value is None:
        raise ArtifactAccessError(
            "NOFOLLOW_UNAVAILABLE",
            "This platform cannot safely open artifacts without following symlinks",
            Path(REPORT_NAME),
        )
    return value


def read_regular_bytes(path: Path) -> tuple[bytes, FileIdentity]:
    try:
        before = os.lstat(path)
    except FileNotFoundError as exc:
        raise ArtifactAccessError("NOT_FOUND", "Artifact does not exist", path, str(exc)) from exc
    except OSError as exc:
        raise ArtifactAccessError("LSTAT_FAILED", "Artifact cannot be inspected", path, str(exc)) from exc
    if stat.S_ISLNK(before.st_mode):
        raise ArtifactAccessError("SYMLINK", "Artifact must not be a symlink", path)
    if not stat.S_ISREG(before.st_mode):
        raise ArtifactAccessError("NON_REGULAR", "Artifact must be a regular file", path)

    flags = os.O_RDONLY | nofollow_flag() | getattr(os, "O_CLOEXEC", 0)
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or file_identity(opened) != file_identity(before):
            raise ArtifactAccessError("CHANGED_DURING_OPEN", "Artifact changed while it was being opened", path)
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            return handle.read(), file_identity(opened)
    except ArtifactAccessError:
        raise
    except OSError as exc:
        raise ArtifactAccessError("OPEN_FAILED", "Artifact cannot be read safely", path, str(exc)) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def read_regular_text(path: Path) -> tuple[str, FileIdentity]:
    payload, identity = read_regular_bytes(path)
    try:
        return payload.decode("utf-8"), identity
    except UnicodeDecodeError as exc:
        raise ArtifactAccessError("UTF8_INVALID", "Artifact is not valid UTF-8", path, str(exc)) from exc


def read_regular_json(path: Path) -> tuple[Any, FileIdentity]:
    payload, identity = read_regular_text(path)
    try:
        return strict_json_loads(payload), identity
    except ValueError as exc:
        raise ArtifactAccessError("JSON_INVALID", "Artifact is not valid JSON", path, str(exc)) from exc


def optional_lstat(path: Path) -> os.stat_result | None:
    try:
        return os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ArtifactAccessError("LSTAT_FAILED", "Artifact cannot be inspected", path, str(exc)) from exc


def normalize_http_url(value: Any) -> str | None:
    if not valid_http_url(value):
        return None
    try:
        parsed = urlsplit(value)
        scheme = parsed.scheme.casefold()
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if (
        scheme not in {"http", "https"}
        or not parsed.netloc
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or "@" in parsed.netloc
    ):
        return None

    # urlsplit accepts an empty port ("host:") and several malformed host spellings.
    # Reject them before normalizing so browser-specific interpretations cannot become
    # authoritative URL evidence.
    if parsed.netloc.startswith("["):
        closing_bracket = parsed.netloc.find("]")
        allowed_suffix = "" if port is None else f":{port}"
        if closing_bracket < 0 or parsed.netloc[closing_bracket + 1 :] != allowed_suffix:
            return None
    elif parsed.netloc.count(":") > 1:
        return None
    elif ":" in parsed.netloc:
        raw_port = parsed.netloc.rsplit(":", 1)[1]
        if not raw_port or not raw_port.isascii() or not raw_port.isdigit():
            return None

    raw_host = hostname
    if not raw_host:
        return None
    try:
        address = ipaddress.ip_address(raw_host)
    except ValueError:
        if ":" in raw_host or re.fullmatch(r"[0-9.]+", raw_host):
            return None
        # Avoid transitional IDNA2003 folding. Unicode IDNs must arrive in
        # explicit ASCII/punycode form so browser-distinct hosts stay distinct.
        if not raw_host.isascii():
            return None
        host = raw_host.casefold()
        if len(host) > 253 or any(DNS_LABEL.fullmatch(label) is None for label in host.split(".")):
            return None
    else:
        if address.version == 6:
            return None
        host = address.compressed.casefold()

    if port is not None and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        host = f"{host}:{port}"
    path = parsed.path or "/"
    # Treat one conventional trailing slash as equivalent, but preserve
    # repeated slashes: servers and routers may assign them different meaning.
    if path != "/" and path.endswith("/") and not path.endswith("//"):
        path = path[:-1] or "/"
    return urlunsplit((scheme, host, path, parsed.query, ""))


def validate_redirect_plan(
    value: Any,
    baseline_url: str | None,
    destination_url: str | None,
    url_changed: bool | None,
    findings: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Validate and normalize the redirect contract recorded by the prior semantic review."""

    if value is None:
        if url_changed is True:
            findings.append(finding("REDIRECT_PLAN_MISSING", "P1", "URL change has no redirect plan"))
        return None
    if not isinstance(value, dict):
        findings.append(
            finding(
                "REDIRECT_PLAN_INVALID",
                "P1",
                "redirect_plan must be an object with source_url, target_url, status_code, and owner",
                actual_type=type(value).__name__,
            )
        )
        return None

    source_url = normalize_http_url(value.get("source_url"))
    target_url = normalize_http_url(value.get("target_url"))
    status_code = value.get("status_code")
    owner = value.get("owner")
    invalid_fields: list[str] = []
    if source_url is None:
        invalid_fields.append("source_url")
    if target_url is None:
        invalid_fields.append("target_url")
    if isinstance(status_code, bool) or not isinstance(status_code, int) or status_code not in {301, 308}:
        invalid_fields.append("status_code")
    if not safe_human_text(owner):
        invalid_fields.append("owner")
    if invalid_fields:
        findings.append(
            finding(
                "REDIRECT_PLAN_INVALID",
                "P1",
                "Redirect plan fields are invalid; URLs must be safe HTTP(S), status_code must be 301 or 308, and owner must be nonempty",
                fields=invalid_fields,
            )
        )
        return None

    assert source_url is not None and target_url is not None and isinstance(owner, str)
    normalized = {
        "source_url": source_url,
        "target_url": target_url,
        "status_code": status_code,
        "owner": owner.strip(),
    }
    if baseline_url is not None and source_url != baseline_url:
        findings.append(
            finding(
                "REDIRECT_PLAN_SOURCE_MISMATCH",
                "P1",
                "Redirect plan source_url does not match the immutable baseline URL",
                expected=baseline_url,
                actual=source_url,
            )
        )
    if destination_url is not None and target_url != destination_url:
        findings.append(
            finding(
                "REDIRECT_PLAN_TARGET_MISMATCH",
                "P1",
                "Redirect plan target_url does not match the manifest destination URL",
                expected=destination_url,
                actual=target_url,
            )
        )
    return normalized


def url_candidates(payload: dict[str, Any], artifact: str, findings: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    containers: list[tuple[str, dict[str, Any]]] = [(artifact, payload)]
    for nested_name in ("metadata", "original", "source"):
        nested = payload.get(nested_name)
        if isinstance(nested, dict):
            containers.append((f"{artifact}.{nested_name}", nested))

    result: list[tuple[str, str, str]] = []
    for container_name, container in containers:
        fields = URL_FIELDS + (("source",) if container is payload else ())
        for field in fields:
            value = container.get(field)
            if value in (None, ""):
                continue
            normalized = normalize_http_url(value)
            if normalized is None:
                # Scaffold snapshots allow a non-URL topic in `source`; it is not malformed URL evidence.
                if field != "source" or (isinstance(value, str) and value.casefold().startswith(("http:", "https:"))):
                    findings.append(
                        finding(
                            "BASELINE_URL_INVALID",
                            "P1",
                            "Baseline metadata contains a non-HTTP URL value",
                            artifact=container_name,
                            field=field,
                            value=value,
                        )
                    )
                continue
            result.append((normalized, str(value), f"{container_name}.{field}"))
    return result


def derive_baseline_url(root: Path, findings: list[dict[str, Any]]) -> tuple[str | None, list[str], bool]:
    candidates: list[tuple[str, str, str]] = []
    evidence_files: list[str] = []
    invalid_artifact = False
    for relative in ("baseline/snapshot.json", "baseline/metadata.json"):
        path = root / relative
        if optional_lstat(path) is None:
            continue
        evidence_files.append(relative)
        try:
            payload, _ = read_regular_json(path)
        except ArtifactAccessError as exc:
            findings.append(finding("BASELINE_METADATA_INVALID", "P1", "Baseline URL evidence cannot be read safely", **exc.evidence()))
            invalid_artifact = True
            continue
        if not isinstance(payload, dict):
            findings.append(finding("BASELINE_METADATA_INVALID", "P1", "Baseline URL evidence must be a JSON object", path=relative))
            invalid_artifact = True
            continue
        candidates.extend(url_candidates(payload, relative, findings))

    by_normalized: dict[str, list[tuple[str, str]]] = {}
    for normalized, original, source in candidates:
        by_normalized.setdefault(normalized, []).append((original, source))
    if len(by_normalized) > 1:
        findings.append(
            finding(
                "BASELINE_URL_CONFLICT",
                "P1",
                "Baseline metadata records conflicting source URLs",
                candidates=[{"url": url, "sources": [source for _, source in records]} for url, records in by_normalized.items()],
            )
        )
        return None, evidence_files, True
    if not by_normalized:
        return None, evidence_files, invalid_artifact
    return next(iter(by_normalized)), evidence_files, invalid_artifact


def protected_values(protected: dict[str, Any], key: str, findings: list[dict[str, Any]]) -> list[str]:
    value = protected.get(key, [])
    if not isinstance(value, list) or any(not safe_human_text(item) for item in value):
        findings.append(finding("PROTECTED_VALUES_INVALID", "P1", "Protected headings and links must be arrays of substantive control-free strings", field=key))
        return []
    return value


def read_prior_report(path: Path, findings: list[dict[str, Any]]) -> tuple[dict[str, Any], FileIdentity | None, bool]:
    file_stat = optional_lstat(path)
    if file_stat is None:
        return {}, None, False
    if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
        findings.append(
            finding(
                "DIFF_REPORT_TARGET_UNSAFE",
                "P1",
                "Existing diff-report.json must be a regular file and must not be a symlink",
                path=str(path),
                file_type="symlink" if stat.S_ISLNK(file_stat.st_mode) else "non-regular",
            )
        )
        return {}, None, True
    try:
        payload, identity = read_regular_json(path)
    except ArtifactAccessError as exc:
        # A regular but malformed report may be replaced atomically with a diagnostic report.
        identity = file_identity(file_stat)
        findings.append(finding("DIFF_REPORT_INVALID", "P1", "Existing diff-report.json is invalid", **exc.evidence()))
        return {}, identity, False
    if not isinstance(payload, dict):
        findings.append(finding("DIFF_REPORT_INVALID", "P1", "Existing diff-report.json must be a JSON object", path=str(path)))
        return {}, identity, False
    return payload, identity, False


def stat_at(directory_fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def verify_target_state(directory_fd: int, expected: FileIdentity | None, root: Path) -> None:
    current = stat_at(directory_fd, REPORT_NAME)
    if current is not None and (stat.S_ISLNK(current.st_mode) or not stat.S_ISREG(current.st_mode)):
        raise ArtifactAccessError("TARGET_UNSAFE", "diff-report.json became a symlink or non-regular file", root / REPORT_NAME)
    current_identity = file_identity(current) if current is not None else None
    if current_identity != expected:
        raise ArtifactAccessError("TARGET_CHANGED", "diff-report.json changed during validation; refusing to replace it", root / REPORT_NAME)


def atomic_write_report(root: Path, report: dict[str, Any], expected_target: FileIdentity | None) -> None:
    try:
        root_stat = os.lstat(root)
    except OSError as exc:
        raise ArtifactAccessError("ROOT_INVALID", "Run directory cannot be inspected", root, str(exc)) from exc
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise ArtifactAccessError("ROOT_UNSAFE", "Run directory must be a real directory, not a symlink", root)

    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow_flag() | getattr(os, "O_CLOEXEC", 0)
    directory_fd = -1
    temp_name: str | None = None
    try:
        directory_fd = os.open(root, directory_flags)
        opened_root = os.fstat(directory_fd)
        if not stat.S_ISDIR(opened_root.st_mode) or file_identity(opened_root) != file_identity(root_stat):
            raise ArtifactAccessError("ROOT_CHANGED", "Run directory changed while it was being opened", root)

        verify_target_state(directory_fd, expected_target, root)
        temp_name = f".{REPORT_NAME}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
        temp_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow_flag() | getattr(os, "O_CLOEXEC", 0)
        temp_fd = os.open(temp_name, temp_flags, 0o600, dir_fd=directory_fd)
        try:
            payload = (json.dumps(report, indent=2, ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")
            view = memoryview(payload)
            while view:
                written = os.write(temp_fd, view)
                if written <= 0:
                    raise OSError("short write while creating diff report")
                view = view[written:]
            os.fsync(temp_fd)
        finally:
            os.close(temp_fd)

        verify_target_state(directory_fd, expected_target, root)
        os.replace(temp_name, REPORT_NAME, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        temp_name = None
        try:
            os.fsync(directory_fd)
        except OSError as exc:
            unsupported = {errno.EINVAL, getattr(errno, "ENOTSUP", errno.EINVAL), getattr(errno, "EOPNOTSUPP", errno.EINVAL)}
            if exc.errno not in unsupported:
                raise
    except ArtifactAccessError:
        raise
    except (OSError, NotImplementedError) as exc:
        raise ArtifactAccessError("ATOMIC_WRITE_FAILED", "diff-report.json could not be replaced safely", root / REPORT_NAME, str(exc)) from exc
    finally:
        if directory_fd >= 0 and temp_name is not None:
            try:
                os.unlink(temp_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
            except OSError:
                pass
        if directory_fd >= 0:
            os.close(directory_fd)


def run(args: argparse.Namespace) -> int:
    root = args.run_dir.expanduser().resolve()
    findings: list[dict[str, Any]] = []

    try:
        manifest, _ = read_regular_json(root / "manifest.json")
    except ArtifactAccessError as exc:
        report = {"validator": "diff", "status": "unavailable", "findings": [finding("MANIFEST_INVALID", "P1", "Cannot read manifest", **exc.evidence())]}
        emit(report, args.pretty)
        return 2
    if not isinstance(manifest, dict):
        report = {"validator": "diff", "status": "unavailable", "findings": [finding("MANIFEST_INVALID", "P1", "Manifest must be a JSON object")]}
        emit(report, args.pretty)
        return 2

    mode = manifest.get("mode")
    if not isinstance(mode, str):
        report = {"validator": "diff", "status": "unavailable", "findings": [finding("MODE_INVALID", "P1", "Manifest mode must be a string", value=mode)]}
        emit(report, args.pretty)
        return 2
    if mode not in {"rewrite", "refresh"}:
        report = {"validator": "diff", "status": "not-applicable", "mode": mode, "findings": []}
        emit(report, args.pretty)
        return 0

    original_path = root / "baseline/original.md"
    final_path = root / "drafts/final.md"
    try:
        original, _ = read_regular_text(original_path)
        final, _ = read_regular_text(final_path)
    except ArtifactAccessError as exc:
        code = "DIFF_INPUT_MISSING" if exc.code == "NOT_FOUND" else "DIFF_INPUT_INVALID"
        report = {
            "validator": "diff",
            "status": "unavailable",
            "findings": [finding(code, "P1", "Rewrite/refresh requires safe regular UTF-8 baseline/original.md and drafts/final.md files", **exc.evidence())],
        }
        emit(report, args.pretty)
        return 2
    for label, text in (("baseline/original.md", original), ("drafts/final.md", final)):
        if contains_forbidden_document_control(text):
            findings.append(
                finding(
                    "DIFF_INPUT_CONTROL_INVALID",
                    "P1",
                    "Rewrite/refresh input contains a forbidden control character",
                    path=label,
                )
            )

    original_structure = markdown_for_structure(original)
    final_structure = markdown_for_structure(final)
    original_headings = HEADING.findall(original_structure)
    final_headings = HEADING.findall(final_structure)
    original_links = LINK.findall(original_structure)
    final_links = LINK.findall(final_structure)
    final_heading_norm = {norm(item) for item in final_headings}
    final_link_set = set(final_links)

    protected_value = manifest.get("protected")
    if not isinstance(protected_value, dict):
        findings.append(finding("PROTECTED_RECORD_INVALID", "P1", "Manifest protected record must be an object"))
        protected: dict[str, Any] = {}
    else:
        protected = protected_value
    protected_headings = protected_values(protected, "headings", findings)
    protected_links = protected_values(protected, "links", findings)

    if protected.get("reviewed") is not True:
        findings.append(finding("PROTECTED_REVIEW_MISSING", "P1", "Rewrite/refresh requires an explicit review of headings and links worth preserving"))
    rationale = protected.get("rationale")
    if not safe_human_text(rationale, 12):
        findings.append(finding("PROTECTED_RATIONALE_MISSING", "P1", "Protected-element selection needs a substantive rationale"))
    if not protected_headings and not protected_links and protected.get("empty_selection_approved") is not True:
        findings.append(finding("PROTECTED_SELECTION_EMPTY", "P1", "No protected headings or links were selected; explicitly approve an empty selection after review"))

    missing_headings = [item for item in protected_headings if norm(item) not in final_heading_norm]
    missing_links = [item for item in protected_links if item not in final_link_set]
    if missing_headings:
        findings.append(finding("PROTECTED_HEADINGS_REMOVED", "P1", "Protected headings are absent from final article", headings=missing_headings))
    if missing_links:
        findings.append(finding("PROTECTED_LINKS_REMOVED", "P1", "Protected links are absent from final article", links=missing_links))

    prior_path = root / REPORT_NAME
    prior_report, prior_identity, unsafe_report_target = read_prior_report(prior_path, findings)

    baseline_url, baseline_artifacts, baseline_invalid = derive_baseline_url(root, findings)
    destination = manifest.get("destination")
    if destination is None:
        destination = {}
    if not isinstance(destination, dict):
        findings.append(finding("DESTINATION_INVALID", "P1", "Manifest destination must be an object"))
        destination = {}
    raw_destination_url = destination.get("url")
    destination_url = None if raw_destination_url in (None, "") else normalize_http_url(raw_destination_url)
    if raw_destination_url not in (None, "") and destination_url is None:
        findings.append(finding("DESTINATION_URL_INVALID", "P1", "Manifest destination URL must be an absolute HTTP(S) URL", value=raw_destination_url))

    if destination_url is None:
        url_changed: bool | None = False
        url_change_basis = "no-destination-url"
    elif baseline_url is None:
        url_changed = None
        url_change_basis = "baseline-url-unavailable"
        if not baseline_invalid:
            findings.append(
                finding(
                    "BASELINE_URL_MISSING",
                    "P1",
                    "Cannot evaluate a destination URL change without an immutable baseline URL",
                    baseline_artifacts=baseline_artifacts,
                    destination_url=destination_url,
                )
            )
    else:
        url_changed = baseline_url != destination_url
        url_change_basis = "baseline-versus-manifest-destination"

    redirect_plan = validate_redirect_plan(
        prior_report.get("redirect_plan"),
        baseline_url,
        destination_url,
        url_changed,
        findings,
    )
    permissions = manifest.get("permissions") if isinstance(manifest.get("permissions"), dict) else {}
    if url_changed is True and permissions.get("url_change", False) is not True:
        findings.append(finding("URL_CHANGE_UNAUTHORIZED", "P0", "URL change is derived from the baseline without explicit permission"))

    material_changes = prior_report.get("material_changes", [])
    if not isinstance(material_changes, list) or any(not safe_human_text(item, 3) for item in material_changes):
        findings.append(finding("MATERIAL_CHANGES_INVALID", "P1", "material_changes must be an array of substantive control-free strings"))
        material_changes = []
    date_modified_changed = prior_report.get("date_modified_changed", False)
    if not isinstance(date_modified_changed, bool):
        findings.append(finding("DATE_MODIFIED_FLAG_INVALID", "P1", "date_modified_changed must be a boolean"))
        date_modified_changed = False
    if mode == "refresh" and date_modified_changed and not material_changes:
        findings.append(finding("DATE_MODIFIED_UNJUSTIFIED", "P1", "dateModified changed without recorded material changes"))

    similarity = difflib.SequenceMatcher(a=original, b=final).ratio()
    report = {
        "validator": "diff",
        "status": "failed" if any(item["severity"] in {"P0", "P1"} for item in findings) else "passed",
        "mode": mode,
        "similarity_ratio": round(similarity, 4),
        "original": {"headings": original_headings, "links": original_links, "characters": len(original)},
        "final": {"headings": final_headings, "links": final_links, "characters": len(final)},
        "removed_headings": [item for item in original_headings if norm(item) not in final_heading_norm],
        "removed_links": [item for item in original_links if item not in final_link_set],
        "protected_missing": {"headings": missing_headings, "links": missing_links},
        "material_changes": material_changes,
        "baseline_url": baseline_url,
        "destination_url": destination_url,
        "url_changed": url_changed,
        "url_change_basis": url_change_basis,
        "redirect_plan": redirect_plan,
        "date_modified_changed": date_modified_changed,
        "findings": findings,
        "limitations": [
            "Text similarity and extracted headings/links do not determine editorial quality or ranking impact.",
            "Baseline URL integrity depends on the run preserving its baseline artifacts; this validator does not provide cryptographic immutability.",
        ],
    }

    if args.write:
        if unsafe_report_target:
            report["status"] = "failed"
        else:
            try:
                atomic_write_report(root, report, prior_identity)
            except ArtifactAccessError as exc:
                findings.append(finding("DIFF_REPORT_WRITE_REJECTED", "P1", "Refused to write diff-report.json unsafely", **exc.evidence()))
                report["status"] = "failed"
                report["findings"] = findings

    emit(report, args.pretty)
    return 1 if report["status"] == "failed" else 0


def main() -> int:
    parser = JsonArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--write", action="store_true", help="Write diff-report.json into the run")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    try:
        return run(args)
    except Exception as exc:
        report = {
            "validator": "diff",
            "status": "unavailable",
            "findings": [
                finding(
                    "HOSTILE_INPUT_REJECTED",
                    "P1",
                    "diff_guard rejected an unexpected or hostile input without producing a traceback",
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
            ],
        }
        emit(report, getattr(args, "pretty", False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
