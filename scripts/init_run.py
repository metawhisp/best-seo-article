#!/usr/bin/env python3
"""Create a safe, provider-neutral best-seo-article run scaffold."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from capability_preflight import build_parser as build_capability_parser
from capability_preflight import build_report as build_capability_report
from validate_run import contains_forbidden_single_line_control, substantive_string, valid_document_url


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


class JsonArgumentParser(argparse.ArgumentParser):
    """Keep CLI failures machine-readable for orchestrators."""

    def error(self, message: str) -> None:
        print(
            json.dumps(
                {"error": "invalid_arguments", "message": message},
                ensure_ascii=True,
                allow_nan=False,
            ),
            file=sys.stderr,
        )
        raise SystemExit(2)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def write_text(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def parser() -> argparse.ArgumentParser:
    result = JsonArgumentParser(description=__doc__)
    result.add_argument("--mode", required=True, choices=("new", "rewrite", "refresh", "external"))
    result.add_argument("--target", required=True, help="Topic, URL, file, or source-text identifier")
    result.add_argument("--output", required=True, type=Path)
    result.add_argument("--language", default="auto")
    result.add_argument("--locale")
    result.add_argument("--site")
    result.add_argument("--ymyl", choices=("auto", "true", "false"), default="auto")
    result.add_argument("--jurisdiction", help="Required jurisdiction for --ymyl true")
    result.add_argument("--requested-status", choices=STATUSES, default="publish-package-ready")
    result.add_argument("--no-web-research", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()

    invalid_inputs: list[str] = []
    if not substantive_string(args.target) or contains_forbidden_single_line_control(args.target):
        invalid_inputs.append("target")
    if not substantive_string(args.language, 2) or contains_forbidden_single_line_control(args.language):
        invalid_inputs.append("language")
    if args.locale is not None and (
        not substantive_string(args.locale) or contains_forbidden_single_line_control(args.locale)
    ):
        invalid_inputs.append("locale")
    if args.site is not None and not valid_document_url(args.site):
        invalid_inputs.append("site")
    if args.jurisdiction is not None and (
        not substantive_string(args.jurisdiction, 2)
        or contains_forbidden_single_line_control(args.jurisdiction)
    ):
        invalid_inputs.append("jurisdiction")
    if args.ymyl == "true" and args.jurisdiction is None:
        invalid_inputs.append("jurisdiction_required_for_ymyl")
    if invalid_inputs:
        print(
            json.dumps(
                {"error": "invalid_input", "fields": sorted(set(invalid_inputs))},
                ensure_ascii=True,
                allow_nan=False,
            ),
            file=sys.stderr,
        )
        return 2

    requested_root = args.output.expanduser()
    if requested_root.is_symlink():
        print(json.dumps({"error": "output_symlink", "path": str(requested_root)}, allow_nan=False), file=sys.stderr)
        return 1
    root = requested_root.resolve()
    if root.exists():
        if not root.is_dir():
            print(json.dumps({"error": "output_not_directory", "path": str(root)}, allow_nan=False), file=sys.stderr)
            return 1
        if any(root.iterdir()):
            print(json.dumps({"error": "output_not_empty", "path": str(root)}, allow_nan=False), file=sys.stderr)
            return 1

    root.mkdir(parents=True, exist_ok=True)
    for relative in (
        "baseline",
        "research",
        "drafts",
        "reviews",
        "publish/assets",
        "measurement/evidence",
        "measurement/snapshots",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)

    now = utc_now()
    run_id = str(uuid.uuid4())
    ymyl: str | bool = args.ymyl
    if args.ymyl in ("true", "false"):
        ymyl = args.ymyl == "true"

    manifest = {
        "schema_version": "0.1",
        "run_id": run_id,
        "mode": args.mode,
        "target": args.target,
        "language": args.language,
        "locale": args.locale,
        "site": args.site,
        "risk": {"ymyl": ymyl, "jurisdiction": args.jurisdiction},
        "permissions": {
            "web_research": not args.no_web_research,
            "paid_tools": False,
            "cms_draft": False,
            "publish": False,
            "url_change": False,
        },
        "requested_status": args.requested_status,
        "actual_status": "blocked" if args.requested_status == "blocked" else "draft-only",
        "roles": {"writer": None, "verifier": None, "editor": None, "technical_reviewer": None, "expert_reviewer": None},
        "protected": {
            "reviewed": False,
            "rationale": None,
            "empty_selection_approved": False,
            "headings": [],
            "links": [],
        },
        "destination": {"format": "markdown", "url": None, "cms": None},
        "created_at": now,
        "updated_at": now,
        "warnings": [],
        "waivers": [],
    }
    intake = {
        "schema_version": "0.1",
        "run_id": run_id,
        "target": args.target,
        "mode": args.mode,
        "language": args.language,
        "locale": args.locale,
        "site": args.site,
        "risk": dict(manifest["risk"]),
        "roles": dict(manifest["roles"]),
        "protected": {
            **manifest["protected"],
            "headings": list(manifest["protected"]["headings"]),
            "links": list(manifest["protected"]["links"]),
        },
        "destination": dict(manifest["destination"]),
        "requested_status": args.requested_status,
        "permissions": dict(manifest["permissions"]),
        "audience": None,
        "reader_job": None,
        "business_goal": None,
        "conversion_action": None,
        "approved_product_facts": [],
        "constraints": [],
        "inferences_requiring_confirmation": [],
    }

    write_json(root / "manifest.json", manifest)
    write_json(root / "intake.json", intake)
    capability_args = build_capability_parser().parse_args(["--checked-at", now])
    write_json(root / "capabilities.json", build_capability_report(capability_args, {}))
    write_text(root / "research/sources.jsonl")
    write_text(root / "research/query-decision.md", "# Query decision\n\n[NEEDS RESEARCH]\n")
    write_text(root / "research/intent-gap.md", "# Intent and gap\n\n[NEEDS RESEARCH]\n")
    write_text(root / "research/source-plan.md", "# Source plan\n\n[NEEDS RESEARCH]\n")
    write_text(root / "claims.jsonl")
    write_text(root / "opportunity.md", "# Opportunity\n\n[NEEDS RESEARCH]\n")
    write_text(root / "brief.md", "# Content brief\n\n[NEEDS RESEARCH]\n")
    write_text(root / "outline.md", "# Evidence-bound outline\n\n[NEEDS EVIDENCE]\n")
    write_text(root / "drafts/final.md", f"# {args.target}\n\n[NEEDS EVIDENCE]\n")
    initial_status = manifest["actual_status"]
    write_text(root / "handoff.md", f"# Handoff\n\nStatus: {initial_status}\n")

    if args.mode in ("rewrite", "refresh"):
        write_text(root / "baseline/original.md", "[NEEDS ORIGINAL]\n")
        write_json(root / "baseline/snapshot.json", {"captured_at": now, "source": args.target, "status": "pending"})

    print(json.dumps({"created": str(root), "run_id": manifest["run_id"], "status": initial_status}, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    try:
        exit_code = main()
    except Exception as exc:  # Fail closed without a Python traceback.
        print(
            json.dumps(
                {"error": "scaffold_failed", "error_type": type(exc).__name__, "message": str(exc)},
                ensure_ascii=True,
                allow_nan=False,
            ),
            file=sys.stderr,
        )
        exit_code = 1
    raise SystemExit(exit_code)
