#!/usr/bin/env python3
"""Structural regression tests for best-seo-article validators."""

from __future__ import annotations

import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
VALIDATE_RUN = SKILL_ROOT / "scripts/validate_run.py"
CAPABILITY_PREFLIGHT = SKILL_ROOT / "scripts/capability_preflight.py"
VALIDATE_MEDIA = SKILL_ROOT / "scripts/validate_media.py"
FIXTURES = SKILL_ROOT / "evals/fixtures"
_TEST_CURRENT = datetime.now(timezone.utc).replace(microsecond=0)
_RUN_CREATED = _TEST_CURRENT - timedelta(days=30)


def iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


NOW = iso(_RUN_CREATED)
MEASURED_UPDATED_AT = iso(_TEST_CURRENT)
BASELINE_AT = iso(_RUN_CREATED)
PUBLISHED_AT = iso(_RUN_CREATED + timedelta(days=1))
LIVE_AT = iso(_RUN_CREATED + timedelta(days=1, minutes=5))
SNAPSHOT_AT = iso(_TEST_CURRENT)
REVIEW_BINDING_VERSION = "review-binding-v1"
MEASUREMENT_CONTRACT_VERSION = "measurement-v1"
CONTENT_REVIEW_PATHS = ("intake.json", "drafts/final.md", "claims.jsonl", "research/sources.jsonl")


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact_hashes(root: Path, *, include_package: bool = False) -> dict[str, str]:
    paths = list(CONTENT_REVIEW_PATHS)
    if include_package:
        paths.append("publish/publish-manifest.json")
    return {relative: sha256_file(root / relative) for relative in paths}


def bound_review(
    root: Path,
    review_type: str,
    reviewer: str,
    reviewed_at: str = NOW,
    *,
    include_package: bool = False,
    **extra: object,
) -> dict[str, object]:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    record: dict[str, object] = {
        "contract_version": REVIEW_BINDING_VERSION,
        "run_id": manifest["run_id"],
        "review_type": review_type,
        "status": "passed",
        "reviewer": reviewer,
        "reviewed_at": reviewed_at,
        "artifact_hashes": artifact_hashes(root, include_package=include_package),
        "findings": [],
    }
    record.update(extra)
    return record


def refresh_review_binding(root: Path, relative: str, *, include_package: bool = False) -> None:
    path = root / relative
    if not path.is_file():
        return
    review = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(review, dict) or not isinstance(review.get("review_type"), str):
        return
    review["artifact_hashes"] = artifact_hashes(root, include_package=include_package)
    write_json(path, review)


def refresh_content_reviews(root: Path) -> None:
    refresh_review_binding(root, "reviews/verification.json")
    refresh_review_binding(root, "reviews/editorial.json")


def sync_intake_authorization(root: Path, manifest: dict[str, object]) -> None:
    """Record the current user-authorized ceiling and refresh bound reviews."""

    intake_path = root / "intake.json"
    intake = json.loads(intake_path.read_text(encoding="utf-8"))
    intake["requested_status"] = manifest["requested_status"]
    intake["permissions"] = manifest["permissions"]
    intake["risk"] = manifest["risk"]
    intake["roles"] = manifest["roles"]
    intake["protected"] = manifest["protected"]
    intake["destination"] = manifest["destination"]
    write_json(intake_path, intake)
    refresh_content_reviews(root)


def base_manifest(mode: str = "new", status: str = "content-ready") -> dict[str, object]:
    return {
        "schema_version": "0.1",
        "run_id": "eval-run-0001",
        "mode": mode,
        "target": "How evidence-led content works",
        "language": "en",
        "locale": "en-US",
        "site": "https://example.test",
        "risk": {"ymyl": False, "jurisdiction": None},
        "permissions": {"web_research": True, "paid_tools": False, "cms_draft": False, "publish": False, "url_change": False},
        "requested_status": status,
        "actual_status": status,
        "roles": {"writer": "writer-pass", "verifier": "verifier-pass", "editor": "editor-pass", "technical_reviewer": "technical-pass", "expert_reviewer": None},
        "protected": {
            "reviewed": False,
            "rationale": None,
            "empty_selection_approved": False,
            "headings": [],
            "links": [],
        },
        "destination": {"format": "markdown", "url": None, "cms": None},
        "created_at": NOW,
        "updated_at": NOW,
        "warnings": [],
        "waivers": [],
    }


def build_content_ready(root: Path, mode: str = "new") -> dict[str, object]:
    manifest = base_manifest(mode)
    write_json(root / "manifest.json", manifest)
    write_json(
        root / "intake.json",
        {
            "schema_version": manifest["schema_version"],
            "run_id": manifest["run_id"],
            "mode": mode,
            "target": manifest["target"],
            "language": manifest["language"],
            "locale": manifest["locale"],
            "site": manifest["site"],
            "risk": manifest["risk"],
            "roles": manifest["roles"],
            "protected": manifest["protected"],
            "destination": manifest["destination"],
            "requested_status": manifest["requested_status"],
            "permissions": manifest["permissions"],
            "audience": "Editors responsible for evidence-led content",
            "reader_job": "Build a defensible article workflow",
            "business_goal": "Reduce unsupported claims and review rework",
            "conversion_action": None,
            "approved_product_facts": [],
            "constraints": ["Do not invent evidence"],
            "inferences_requiring_confirmation": [],
        },
    )
    preflight = subprocess.run(
        [sys.executable, str(CAPABILITY_PREFLIGHT), "--checked-at", NOW],
        check=True,
        capture_output=True,
        text=True,
    )
    write_json(root / "capabilities.json", json.loads(preflight.stdout))
    write_json(
        root / "research/serp.json",
        {
            "query": "evidence led content",
            "captured_at": NOW,
            "locale": "en-US",
            "device": "desktop",
            "status": "captured",
            "acquisition": "agent-web",
            "results": [{"url": "https://developers.google.com/search/docs", "opened": True}],
        },
    )
    source = {
        "source_id": "S1",
        "title": "Official documentation",
        "locator": "https://developers.google.com/search/docs",
        "publisher": "Google",
        "author": None,
        "published_at": None,
        "updated_at": None,
        "retrieved_at": NOW,
        "source_type": "official",
        "acquisition": "agent-web",
        "locale": "global",
        "jurisdiction": None,
        "access_status": "accessible",
        "supported_claim_ids": ["C1"],
        "known_conflicts": [],
        "snapshot": None,
        "notes": None,
    }
    claim = {
        "claim_id": "C1",
        "text": "Search documentation recommends evidence-led, useful content.",
        "location": "Evidence section",
        "classification": "load-bearing",
        "claim_type": "factual",
        "source_ids": ["S1"],
        "support_status": "verified",
        "freshness_status": "current",
        "exact_support": "Reviewer inspected the relevant guidance in context.",
        "verifier": "verifier-pass",
        "resolution": "approved",
        "as_of": NOW[:10],
    }
    write_jsonl(root / "research/sources.jsonl", [source])
    write_jsonl(root / "claims.jsonl", [claim])
    write_text(root / "research/query-decision.md", "# Query decision\n\nThe supplied reader job and observed SERP support the selected informational query; no same-intent page is known in the supplied corpus.\n")
    write_text(root / "research/intent-gap.md", "# Intent and gap\n\nOpened results show an informational intent. The draft adds an evidence-led decision boundary rather than repeating headings.\n")
    write_text(root / "research/source-plan.md", "# Source plan\n\nUse the official documentation for the only load-bearing factual claim and remove unsupported product assertions.\n")
    write_text(root / "opportunity.md", "# Opportunity\n\nNo same-intent page was found in the supplied corpus.\n")
    write_text(root / "brief.md", "# Brief\n\nHelp editors build evidence-led content.\n")
    write_text(root / "outline.md", "# Outline\n\n## Evidence\n\nMaps to C1.\n")
    final = "# How evidence-led content works\n\n## Evidence\n\nSearch documentation recommends evidence-led, useful content.\n"
    write_text(root / "drafts/final.md", final)
    write_text(root / "reviews/editorial.md", "# Editorial review\n\nPassed for clarity, intent, and evidence boundaries.\n")
    if mode in {"rewrite", "refresh"}:
        write_text(root / "baseline/original.md", "# How evidence-led content works\n\n## Evidence\n\nOld but useful section with [documentation](https://developers.google.com/search/docs).\n")
        write_json(root / "baseline/snapshot.json", {"captured_at": NOW, "status": "captured"})
        manifest["protected"] = {
            "reviewed": True,
            "rationale": "The evidence section and primary documentation link remain useful and accurate.",
            "empty_selection_approved": False,
            "headings": ["Evidence"],
            "links": ["https://developers.google.com/search/docs"],
        }
        write_json(root / "manifest.json", manifest)
        sync_intake_authorization(root, manifest)
        write_text(root / "drafts/final.md", final + "\nSee the [documentation](https://developers.google.com/search/docs).\n")
        write_json(root / "diff-report.json", {"material_changes": ["Updated evidence and explanation"], "url_changed": False, "date_modified_changed": mode == "refresh"})
    write_json(
        root / "reviews/verification.json",
        bound_review(
            root,
            "verification",
            "verifier-pass",
            independence_degraded=False,
            findings=[],
        ),
    )
    write_json(
        root / "reviews/editorial.json",
        bound_review(
            root,
            "editorial",
            "editor-pass",
            checks={
                "intent": {"status": "passed", "evidence": "The draft answers the documented reader job."},
                "clarity": {"status": "passed", "evidence": "The draft uses a direct evidence-led structure."},
            },
            findings=[],
        ),
    )
    return manifest


def build_publish_package(root: Path) -> dict[str, object]:
    manifest = build_content_ready(root)
    manifest["actual_status"] = "publish-package-ready"
    manifest["requested_status"] = "publish-package-ready"
    write_json(root / "manifest.json", manifest)
    sync_intake_authorization(root, manifest)
    article = (root / "drafts/final.md").read_text(encoding="utf-8")
    write_text(root / "publish/article.md", article)
    write_json(root / "publish/metadata.json", {"title": "How evidence-led content works", "description": "A practical evidence-led content workflow.", "slug": "evidence-led-content", "canonical": None})
    write_json(root / "publish/schema.json", {"@context": "https://schema.org", "@type": "Article", "headline": "How evidence-led content works"})
    file_records = []
    for relative in ("publish/article.md", "publish/metadata.json", "publish/schema.json"):
        payload = (root / relative).read_bytes()
        file_records.append({"path": relative, "sha256": hashlib.sha256(payload).hexdigest()})
    write_json(
        root / "publish/publish-manifest.json",
        {
            "schema_version": "0.1",
            "run_id": manifest["run_id"],
            "created_at": NOW,
            "destination": manifest["destination"],
            "publication_authorized": False,
            "files": file_records,
        },
    )
    write_json(
        root / "reviews/technical.json",
        bound_review(
            root,
            "technical",
            "technical-pass",
            include_package=True,
            scope="CMS-neutral Markdown package",
            checks={
                "single_h1": {"status": "passed", "evidence": "The package has one Markdown H1."},
                "metadata": {"status": "passed", "evidence": "Required metadata fields are present."},
                "schema": {"status": "passed", "evidence": "The schema decision matches visible content."},
                "links": {"status": "passed", "evidence": "Required links were checked."},
                "assets": {"status": "not-applicable", "evidence": "The fixture intentionally contains no assets."},
            },
            findings=[],
        ),
    )
    return manifest


def build_measured(root: Path) -> dict[str, object]:
    manifest = build_publish_package(root)
    page = "https://example.test/evidence-led-content"
    manifest["actual_status"] = "measured"
    manifest["requested_status"] = "measured"
    manifest["permissions"]["publish"] = True
    manifest["destination"]["url"] = page
    manifest["updated_at"] = MEASURED_UPDATED_AT
    write_json(root / "manifest.json", manifest)
    sync_intake_authorization(root, manifest)
    baseline_export = root / "measurement/evidence/gsc-baseline.csv"
    snapshot_export = root / "measurement/evidence/gsc-snapshot.csv"
    write_text(
        baseline_export,
        "page,impressions,clicks\n/evidence-led-content,0,0\n",
    )
    write_text(
        snapshot_export,
        "page,impressions,clicks\n/evidence-led-content,120,18\n",
    )
    measured_preflight = subprocess.run(
        [
            sys.executable,
            str(CAPABILITY_PREFLIGHT),
            "--checked-at",
            NOW,
            "--file",
            f"gsc={snapshot_export}",
            "--provider",
            "gsc=google-search-console-export",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    write_json(root / "capabilities.json", json.loads(measured_preflight.stdout))
    metadata = json.loads((root / "publish/metadata.json").read_text(encoding="utf-8"))
    metadata["canonical"] = page
    write_json(root / "publish/metadata.json", metadata)
    publish_manifest = json.loads((root / "publish/publish-manifest.json").read_text(encoding="utf-8"))
    publish_manifest["destination"] = manifest["destination"]
    publish_manifest["publication_authorized"] = True
    for record in publish_manifest["files"]:
        record["sha256"] = hashlib.sha256((root / record["path"]).read_bytes()).hexdigest()
    write_json(root / "publish/publish-manifest.json", publish_manifest)
    technical = json.loads((root / "reviews/technical.json").read_text(encoding="utf-8"))
    technical["scope"] = "Destination-specific Markdown package"
    technical["checks"]["destination_build_available"] = {"status": "passed", "evidence": "The fixture destination build is available."}
    technical["checks"]["destination_renderer_checked"] = {"status": "passed", "evidence": "The fixture renderer was checked."}
    technical["artifact_hashes"] = artifact_hashes(root, include_package=True)
    write_json(root / "reviews/technical.json", technical)
    package_manifest_sha256 = sha256_file(root / "publish/publish-manifest.json")
    write_json(
        root / "publish/publish-receipt.json",
        {
            "status": "published",
            "published_at": PUBLISHED_AT,
            "url": page,
            "actor": "eval-publisher",
            "permission_confirmed": True,
            "package_manifest_sha256": package_manifest_sha256,
        },
    )
    publish_receipt_sha256 = sha256_file(root / "publish/publish-receipt.json")
    write_json(
        root / "reviews/live-verification.json",
        {
            "status": "passed",
            "checked_at": LIVE_AT,
            "url": page,
            "package_manifest_sha256": package_manifest_sha256,
            "publish_receipt_sha256": publish_receipt_sha256,
            "checks": {
                "http": {"status": "passed", "evidence": "Final destination returned HTTP 200."},
                "rendered_content": {"status": "passed", "evidence": "Expected article identity and body were observed."},
                "canonical": {"status": "passed", "evidence": "Rendered canonical matched the final destination URL."},
                "indexability": {"status": "passed", "evidence": "Rendered robots directives allowed indexing."},
                "schema": {"status": "passed", "evidence": "Visible Article schema matched the rendered article."},
                "links": {"status": "passed", "evidence": "Required rendered links resolved successfully."},
                "assets": {"status": "passed", "evidence": "Required rendered assets loaded successfully."},
            },
        },
    )
    publication_day = (_RUN_CREATED + timedelta(days=1)).date()
    baseline_end = _RUN_CREATED.date()
    baseline_start = baseline_end - timedelta(days=28)
    snapshot_start = publication_day + timedelta(days=1)
    snapshot_end = snapshot_start + timedelta(days=28)
    def evidence(evidence_id: str, path: str, extracted_at: str) -> list[dict[str, object]]:
        return [
            {
                "evidence_id": evidence_id,
                "source_system": "gsc",
                "provider": "google-search-console-export",
                "path": path,
                "sha256": sha256_file(root / path),
                "extracted_at": extracted_at,
            }
        ]

    def metric(value: int, evidence_id: str) -> dict[str, object]:
        return {
            "value": value,
            "unit": "count",
            "aggregation": "sum",
            "source_system": "gsc",
            "evidence_id": evidence_id,
            "entity": "page",
            "channel": "web-search",
            "domain": {
                "entity": "page",
                "value": page,
            },
            "filters": {"page": page, "search_type": "web"},
            "segments": {"country": "all", "device": "all"},
        }

    common = {
        "contract_version": MEASUREMENT_CONTRACT_VERSION,
        "run_id": manifest["run_id"],
        "page": page,
        "mode": "new",
        "package_manifest_sha256": package_manifest_sha256,
    }
    write_json(
        root / "measurement/baseline.json",
        {
            **common,
            "record_type": "baseline",
            "measured_at": BASELINE_AT,
            "source_evidence": evidence(
                "gsc-baseline",
                "measurement/evidence/gsc-baseline.csv",
                BASELINE_AT,
            ),
            "comparison_window": {
                "start": baseline_start.isoformat(),
                "end_exclusive": baseline_end.isoformat(),
                "timezone": "UTC",
                "grain": "day",
            },
            "metrics": {
                "impressions": metric(0, "gsc-baseline"),
                "clicks": metric(0, "gsc-baseline"),
            },
            "data_limitations": ["New URL has no page-level pre-publication history."],
        },
    )
    write_json(
        root / "measurement/snapshots/2026-08-29.json",
        {
            **common,
            "record_type": "snapshot",
            "live_verification_sha256": sha256_file(root / "reviews/live-verification.json"),
            "measured_at": SNAPSHOT_AT,
            "source_evidence": evidence(
                "gsc-snapshot",
                "measurement/evidence/gsc-snapshot.csv",
                SNAPSHOT_AT,
            ),
            "comparison_window": {
                "start": snapshot_start.isoformat(),
                "end_exclusive": snapshot_end.isoformat(),
                "timezone": "UTC",
                "grain": "day",
            },
            "metrics": {
                "impressions": metric(120, "gsc-snapshot"),
                "clicks": metric(18, "gsc-snapshot"),
            },
            "data_limitations": ["Early sample; no causal attribution."],
        },
    )
    write_text(
        root / "measurement/decisions.md",
        "# Measurement decision\n\nDecision: retain the article unchanged while collecting a larger sample. "
        "Evidence: early impressions and clicks exist, but the observation window is too short for causal claims.\n",
    )
    return manifest


def rehash_publish(root: Path, *, sync_destination: bool = False) -> None:
    publish_manifest = json.loads((root / "publish/publish-manifest.json").read_text(encoding="utf-8"))
    if sync_destination:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        publish_manifest["destination"] = manifest["destination"]
    for record in publish_manifest["files"]:
        record["sha256"] = hashlib.sha256((root / record["path"]).read_bytes()).hexdigest()
    write_json(root / "publish/publish-manifest.json", publish_manifest)
    refresh_review_binding(root, "reviews/technical.json", include_package=True)


def validate(root: Path) -> tuple[int, dict[str, object]]:
    result = subprocess.run([sys.executable, str(VALIDATE_RUN), str(root)], check=False, capture_output=True, text=True)
    return result.returncode, json.loads(result.stdout)


class StructuralEvals(unittest.TestCase):
    def run_in_temp(self, builder):
        with tempfile.TemporaryDirectory(prefix="best-seo-article-eval-") as tmp:
            root = Path(tmp)
            builder(root)
            return validate(root)

    def test_new_content_ready_passes(self):
        code, report = self.run_in_temp(lambda root: build_content_ready(root, "new"))
        self.assertEqual(code, 0, report)

    def test_unverified_load_bearing_claim_fails(self):
        def builder(root: Path) -> None:
            build_content_ready(root)
            claim = json.loads((root / "claims.jsonl").read_text(encoding="utf-8"))
            claim["support_status"] = "pending"
            write_jsonl(root / "claims.jsonl", [claim])

        code, report = self.run_in_temp(builder)
        self.assertEqual(code, 1)
        child_findings = [finding for child in report["child_reports"] for finding in child.get("findings", [])]
        self.assertTrue(any(finding["code"] == "LOAD_BEARING_NOT_VERIFIED" for finding in child_findings), report)

    def test_unused_unavailable_source_is_not_a_hard_failure(self):
        def builder(root: Path) -> None:
            build_content_ready(root)
            source = json.loads((root / "research/sources.jsonl").read_text(encoding="utf-8"))
            unused = dict(source)
            unused["source_id"] = "S-unused"
            unused["locator"] = "https://example.test/unavailable-research-lead"
            unused["access_status"] = "unavailable"
            unused["supported_claim_ids"] = []
            write_jsonl(root / "research/sources.jsonl", [source, unused])
            refresh_content_reviews(root)

        code, report = self.run_in_temp(builder)
        self.assertEqual(code, 0, report)

    def test_rewrite_preserves_protected_elements(self):
        code, report = self.run_in_temp(lambda root: build_content_ready(root, "rewrite"))
        self.assertEqual(code, 0, report)

    def test_refresh_requires_material_date_change(self):
        def builder(root: Path) -> None:
            build_content_ready(root, "refresh")
            write_json(root / "diff-report.json", {"material_changes": [], "url_changed": False, "date_modified_changed": True})

        code, report = self.run_in_temp(builder)
        self.assertEqual(code, 1)
        child_findings = [finding for child in report["child_reports"] for finding in child.get("findings", [])]
        self.assertTrue(any(finding["code"] == "DATE_MODIFIED_UNJUSTIFIED" for finding in child_findings), report)

    def test_publish_package_passes(self):
        code, report = self.run_in_temp(build_publish_package)
        self.assertEqual(code, 0, report)

    def test_publish_package_checksum_tampering_fails(self):
        def builder(root: Path) -> None:
            build_publish_package(root)
            metadata = json.loads((root / "publish/metadata.json").read_text(encoding="utf-8"))
            metadata["description"] = "Tampered after package checksum creation."
            write_json(root / "publish/metadata.json", metadata)

        code, report = self.run_in_temp(builder)
        self.assertEqual(code, 1)
        self.assertTrue(any(item["code"] == "PUBLISH_FILE_HASH_MISMATCH" for item in report["findings"]), report)

    def test_publish_package_requires_named_core_checks(self):
        def builder(root: Path) -> None:
            build_publish_package(root)
            write_json(
                root / "reviews/technical.json",
                bound_review(
                    root,
                    "technical",
                    "technical-pass",
                    include_package=True,
                    scope="Portable Markdown package",
                    checks={"foo": {"status": "passed", "evidence": "A non-core check."}},
                ),
            )

        code, report = self.run_in_temp(builder)
        self.assertEqual(code, 1)
        self.assertTrue(any(item["code"] == "TECHNICAL_CORE_CHECKS_MISSING" for item in report["findings"]), report)

    def test_publish_package_accepts_documented_core_check_aliases(self):
        def builder(root: Path) -> None:
            build_publish_package(root)
            write_json(
                root / "reviews/technical.json",
                bound_review(
                    root,
                    "technical",
                    "technical-pass",
                    include_package=True,
                    scope="Portable Markdown package",
                    checks={
                        "single_h1": {"status": "passed", "evidence": "The fixture has one logical H1."},
                        "metadata": {"status": "passed", "evidence": "Metadata checked."},
                        "schema_decision": {"status": "passed", "evidence": "Schema applicability checked."},
                        "links": {"status": "passed", "evidence": "Links checked."},
                        "assets": {"status": "not-applicable", "evidence": "No assets in fixture."},
                    },
                ),
            )

        code, report = self.run_in_temp(builder)
        self.assertEqual(code, 0, report)

    def test_publish_package_blocks_active_content(self):
        def builder(root: Path) -> None:
            build_publish_package(root)
            article = (root / "publish/article.md").read_text(encoding="utf-8") + "\n<script>alert(1)</script>\n"
            write_text(root / "publish/article.md", article)
            write_text(root / "drafts/final.md", article)
            rehash_publish(root)

        code, report = self.run_in_temp(builder)
        self.assertEqual(code, 1)
        self.assertTrue(any(item["code"] == "PUBLISH_ACTIVE_CONTENT" for item in report["findings"]), report)

    def test_html_package_requires_h1_and_blocks_active_content(self):
        def builder(root: Path) -> None:
            manifest = build_publish_package(root)
            (root / "publish/article.md").unlink()
            html = "<html><body><p>No heading</p><script>alert(1)</script></body></html>"
            write_text(root / "publish/article.html", html)
            manifest["destination"]["format"] = "html"
            write_json(root / "manifest.json", manifest)
            publish_manifest = json.loads((root / "publish/publish-manifest.json").read_text(encoding="utf-8"))
            publish_manifest["destination"] = manifest["destination"]
            for record in publish_manifest["files"]:
                if record["path"] == "publish/article.md":
                    record["path"] = "publish/article.html"
                record["sha256"] = hashlib.sha256((root / record["path"]).read_bytes()).hexdigest()
            write_json(root / "publish/publish-manifest.json", publish_manifest)
            technical = json.loads((root / "reviews/technical.json").read_text(encoding="utf-8"))
            technical["scope"] = "Portable HTML package"
            technical["checks"]["reviewed_content_correspondence"] = {"status": "passed", "evidence": "Rendered text corresponds to the reviewed fixture draft."}
            write_json(root / "reviews/technical.json", technical)

        code, report = self.run_in_temp(builder)
        self.assertEqual(code, 1)
        codes = {item["code"] for item in report["findings"]}
        self.assertIn("PUBLISH_H1_COUNT", codes, report)
        self.assertIn("PUBLISH_ACTIVE_CONTENT", codes, report)

    def test_publish_package_blocks_local_path_escape(self):
        def builder(root: Path) -> None:
            build_publish_package(root)
            article = (root / "publish/article.md").read_text(encoding="utf-8") + "\n[Outside](../../outside.txt)\n"
            write_text(root / "publish/article.md", article)
            write_text(root / "drafts/final.md", article)
            rehash_publish(root)

        code, report = self.run_in_temp(builder)
        self.assertEqual(code, 1)
        self.assertTrue(any(item["code"] == "LOCAL_LINK_PATH_ESCAPE" for item in report["findings"]), report)

    def test_destinationless_package_rejects_invented_canonical(self):
        def builder(root: Path) -> None:
            manifest = build_publish_package(root)
            manifest["destination"]["url"] = ""
            write_json(root / "manifest.json", manifest)
            metadata = json.loads((root / "publish/metadata.json").read_text(encoding="utf-8"))
            metadata["canonical"] = "https://invented.example/article"
            write_json(root / "publish/metadata.json", metadata)
            rehash_publish(root, sync_destination=True)

        code, report = self.run_in_temp(builder)
        self.assertEqual(code, 1)
        self.assertTrue(any(item["code"] == "METADATA_CANONICAL_UNSCOPED" for item in report["findings"]), report)

    def test_publish_media_file_requires_media_manifest(self):
        def builder(root: Path) -> None:
            build_publish_package(root)
            write_text(root / "publish/assets/hero.png", "not-a-real-png")
            publish_manifest = json.loads((root / "publish/publish-manifest.json").read_text(encoding="utf-8"))
            publish_manifest["files"].append(
                {
                    "path": "publish/assets/hero.png",
                    "sha256": hashlib.sha256((root / "publish/assets/hero.png").read_bytes()).hexdigest(),
                }
            )
            write_json(root / "publish/publish-manifest.json", publish_manifest)

        code, report = self.run_in_temp(builder)
        self.assertEqual(code, 1)
        self.assertTrue(any(item["code"] == "MEDIA_MANIFEST_REQUIRED" for item in report["findings"]), report)

    def test_media_manifest_run_and_claim_ids_must_match(self):
        def builder(root: Path) -> None:
            manifest = build_publish_package(root)
            media = json.loads((FIXTURES / "media-valid.json").read_text(encoding="utf-8"))
            media["run_id"] = "wrong-run-id"
            write_json(root / "media-manifest.json", media)
            publish_manifest = json.loads((root / "publish/publish-manifest.json").read_text(encoding="utf-8"))
            publish_manifest["files"].append(
                {"path": "media-manifest.json", "sha256": hashlib.sha256((root / "media-manifest.json").read_bytes()).hexdigest()}
            )
            write_json(root / "publish/publish-manifest.json", publish_manifest)

        code, report = self.run_in_temp(builder)
        self.assertEqual(code, 1)
        codes = {item["code"] for item in report["findings"]}
        self.assertIn("MEDIA_RUN_ID_MISMATCH", codes, report)
        self.assertIn("MEDIA_CLAIM_ID_UNKNOWN", codes, report)

    def test_publish_json_objects_reject_array_top_levels(self):
        def builder(root: Path) -> None:
            build_publish_package(root)
            for relative in (
                "publish/metadata.json",
                "publish/schema.json",
                "publish/publish-manifest.json",
                "reviews/technical.json",
            ):
                write_json(root / relative, [])

        code, report = self.run_in_temp(builder)
        self.assertEqual(code, 1)
        codes = {item["code"] for item in report["findings"]}
        self.assertIn("METADATA_TYPE_INVALID", codes, report)
        self.assertIn("SCHEMA_TYPE_INVALID", codes, report)
        self.assertIn("PUBLISH_MANIFEST_TYPE_INVALID", codes, report)
        self.assertIn("TECHNICAL_REVIEW_TYPE_INVALID", codes, report)

    def test_published_state_requires_permission(self):
        def builder(root: Path) -> None:
            manifest = build_publish_package(root)
            manifest["actual_status"] = "published-pending-verification"
            manifest["requested_status"] = "published-pending-verification"
            manifest["destination"]["url"] = "https://example.test/evidence-led-content"
            write_json(root / "manifest.json", manifest)
            write_json(root / "publish/publish-receipt.json", {"status": "published", "created_at": NOW})

        code, report = self.run_in_temp(builder)
        self.assertEqual(code, 1)
        self.assertTrue(any(item["code"] == "PUBLISH_UNAUTHORIZED" for item in report["findings"]), report)

    def test_ymyl_needs_qualified_review(self):
        def builder(root: Path) -> None:
            manifest = build_content_ready(root)
            manifest["risk"] = {"ymyl": True, "jurisdiction": "US"}
            write_json(root / "manifest.json", manifest)

        code, report = self.run_in_temp(builder)
        self.assertEqual(code, 1)
        self.assertTrue(any(item["code"].startswith("YMYL_REVIEW") for item in report["findings"]), report)

    def test_ymyl_qualified_review_passes(self):
        def builder(root: Path) -> None:
            manifest = build_content_ready(root)
            manifest["risk"] = {"ymyl": True, "jurisdiction": "US"}
            manifest["roles"]["expert_reviewer"] = "qualified-us-reviewer"
            write_json(root / "manifest.json", manifest)
            sync_intake_authorization(root, manifest)
            write_json(
                root / "reviews/ymyl.json",
                bound_review(
                    root,
                    "ymyl",
                    "qualified-us-reviewer",
                    review_required=True,
                    credentials="Licensed domain professional; fixture only",
                    scope="Material factual claims and reader actions",
                    jurisdiction="US",
                    sections_reviewed=["Evidence"],
                    claims_reviewed=["C1"],
                    findings=[],
                    status="approved",
                ),
            )

        code, report = self.run_in_temp(builder)
        self.assertEqual(code, 0, report)

    def test_ymyl_claims_require_authoritative_current_evidence(self):
        def builder(root: Path) -> None:
            manifest = build_content_ready(root)
            manifest["risk"] = {"ymyl": True, "jurisdiction": "US"}
            manifest["roles"]["expert_reviewer"] = "qualified-us-reviewer"
            write_json(root / "manifest.json", manifest)
            source = json.loads((root / "research/sources.jsonl").read_text(encoding="utf-8"))
            source["source_type"] = "secondary"
            source["retrieved_at"] = "not-a-date"
            write_jsonl(root / "research/sources.jsonl", [source])
            claim = json.loads((root / "claims.jsonl").read_text(encoding="utf-8"))
            claim["claim_type"] = "invented"
            claim.pop("as_of")
            write_jsonl(root / "claims.jsonl", [claim])
            write_json(
                root / "reviews/ymyl.json",
                {
                    "review_required": True,
                    "status": "approved",
                    "reviewer": "qualified-us-reviewer",
                    "credentials": "Licensed domain professional; fixture only",
                    "scope": "Material factual claims and reader actions",
                    "jurisdiction": "US",
                    "reviewed_at": NOW,
                    "sections_reviewed": ["Evidence"],
                    "claims_reviewed": ["C1"],
                    "findings": [],
                },
            )

        code, report = self.run_in_temp(builder)
        self.assertEqual(code, 1)
        child_findings = [finding for child in report["child_reports"] for finding in child.get("findings", [])]
        codes = {item["code"] for item in child_findings}
        self.assertIn("SOURCE_RETRIEVED_AT_INVALID", codes, report)
        self.assertIn("CLAIM_TYPE_INVALID", codes, report)
        self.assertIn("YMYL_AS_OF_MISSING", codes, report)
        self.assertIn("YMYL_AUTHORITATIVE_SOURCE_MISSING", codes, report)

    def test_serp_empty_record_fails(self):
        def builder(root: Path) -> None:
            build_content_ready(root)
            serp = json.loads((root / "research/serp.json").read_text(encoding="utf-8"))
            serp["results"] = [{}]
            write_json(root / "research/serp.json", serp)

        code, report = self.run_in_temp(builder)
        self.assertEqual(code, 1)
        self.assertTrue(any(item["code"].startswith("SERP_RESULT_") for item in report["findings"]), report)

    def test_malformed_url_returns_structured_failure(self):
        def builder(root: Path) -> None:
            build_content_ready(root)
            serp = json.loads((root / "research/serp.json").read_text(encoding="utf-8"))
            serp["results"] = [{"url": "https://[broken", "opened": True}]
            write_json(root / "research/serp.json", serp)

        code, report = self.run_in_temp(builder)
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "failed", report)
        self.assertTrue(any(item["code"] == "SERP_RESULT_URL_INVALID" for item in report["findings"]), report)

    def test_material_claim_requires_type_and_exact_support(self):
        def builder(root: Path) -> None:
            build_content_ready(root)
            claim = json.loads((root / "claims.jsonl").read_text(encoding="utf-8"))
            claim.pop("claim_type")
            claim.pop("exact_support")
            write_jsonl(root / "claims.jsonl", [claim])

        code, report = self.run_in_temp(builder)
        self.assertEqual(code, 1)
        child_findings = [finding for child in report["child_reports"] for finding in child.get("findings", [])]
        codes = {item["code"] for item in child_findings}
        self.assertIn("CLAIM_FIELDS_MISSING", codes, report)
        self.assertIn("MATERIAL_EXACT_SUPPORT_MISSING", codes, report)

    def test_empty_evidence_ledgers_fail(self):
        def builder(root: Path) -> None:
            build_content_ready(root)
            write_text(root / "research/sources.jsonl", "\n")
            write_text(root / "claims.jsonl", "\n")

        code, report = self.run_in_temp(builder)
        self.assertEqual(code, 1)
        child_findings = [finding for child in report["child_reports"] for finding in child.get("findings", [])]
        codes = {item["code"] for item in child_findings}
        self.assertIn("SOURCE_LEDGER_EMPTY", codes, report)
        self.assertIn("CLAIM_LEDGER_EMPTY", codes, report)

    def test_wrong_json_top_level_types_fail_closed(self):
        def builder(root: Path) -> None:
            build_content_ready(root)
            for relative in ("capabilities.json", "research/serp.json", "reviews/verification.json"):
                write_json(root / relative, [])

        code, report = self.run_in_temp(builder)
        self.assertEqual(code, 1)
        codes = {item["code"] for item in report["findings"]}
        self.assertIn("CAPABILITIES_TYPE_INVALID", codes, report)
        self.assertIn("SERP_TYPE_INVALID", codes, report)
        self.assertIn("VERIFICATION_TYPE_INVALID", codes, report)

    def test_forged_capability_state_and_summary_fail(self):
        def builder(root: Path) -> None:
            build_content_ready(root)
            capabilities = json.loads((root / "capabilities.json").read_text(encoding="utf-8"))
            capabilities["capabilities"]["serp"]["status"] = "AVAILABLE"
            capabilities["capabilities"]["serp"]["selected_provider"] = "invented-provider"
            capabilities["summary"]["counts"] = {"AVAILABLE": 10, "USER_EXPORT": 0, "FALLBACK": 0, "UNAVAILABLE": 0}
            write_json(root / "capabilities.json", capabilities)

        code, report = self.run_in_temp(builder)
        self.assertEqual(code, 1)
        codes = {item["code"] for item in report["findings"]}
        self.assertIn("CAPABILITY_AVAILABLE_INCONSISTENT", codes, report)
        self.assertIn("CAPABILITY_SUMMARY_INCONSISTENT", codes, report)

    def test_pending_ymyl_review_record_is_required(self):
        def builder(root: Path) -> None:
            manifest = build_content_ready(root)
            manifest["risk"] = {"ymyl": True, "jurisdiction": "US"}
            manifest["actual_status"] = "needs-expert-review"
            manifest["requested_status"] = "needs-expert-review"
            write_json(root / "manifest.json", manifest)

        code, report = self.run_in_temp(builder)
        self.assertEqual(code, 1)
        self.assertTrue(any(item["code"] == "YMYL_REVIEW_MISSING" for item in report["findings"]), report)

    def test_ymyl_review_rejects_array_top_level(self):
        def builder(root: Path) -> None:
            manifest = build_content_ready(root)
            manifest["risk"] = {"ymyl": True, "jurisdiction": "US"}
            manifest["roles"]["expert_reviewer"] = "qualified-us-reviewer"
            write_json(root / "manifest.json", manifest)
            write_json(root / "reviews/ymyl.json", [])

        code, report = self.run_in_temp(builder)
        self.assertEqual(code, 1)
        self.assertTrue(any(item["code"] == "YMYL_REVIEW_TYPE_INVALID" for item in report["findings"]), report)

    def test_rewrite_empty_protected_selection_fails(self):
        def builder(root: Path) -> None:
            manifest = build_content_ready(root, "rewrite")
            manifest["protected"] = {
                "reviewed": True,
                "rationale": "The original was reviewed before the rewrite.",
                "empty_selection_approved": False,
                "headings": [],
                "links": [],
            }
            write_json(root / "manifest.json", manifest)

        code, report = self.run_in_temp(builder)
        self.assertEqual(code, 1)
        child_findings = [finding for child in report["child_reports"] for finding in child.get("findings", [])]
        self.assertTrue(any(item["code"] == "PROTECTED_SELECTION_EMPTY" for item in child_findings), report)

    def test_forged_measured_state_fails(self):
        def builder(root: Path) -> None:
            manifest = build_publish_package(root)
            manifest["actual_status"] = "measured"
            manifest["requested_status"] = "measured"
            manifest["permissions"]["publish"] = True
            manifest["destination"]["url"] = "https://example.test/evidence-led-content"
            write_json(root / "manifest.json", manifest)
            write_json(root / "publish/publish-receipt.json", {})
            write_json(root / "reviews/live-verification.json", {})
            write_json(root / "measurement/baseline.json", {})
            write_json(root / "measurement/snapshots/empty.json", {})
            write_text(root / "measurement/decisions.md", "Decision: pretend the empty snapshot is enough for a measured state. " * 2)

        code, report = self.run_in_temp(builder)
        self.assertEqual(code, 1)
        codes = {item["code"] for item in report["findings"]}
        self.assertIn("PUBLISH_RECEIPT_TIME_INVALID", codes, report)
        self.assertIn("LIVE_VERIFICATION_CHECKS_MISSING", codes, report)
        self.assertIn("MEASUREMENT_SNAPSHOT_METRICS_INVALID", codes, report)

    def test_measured_wrong_json_types_fail_closed(self):
        def builder(root: Path) -> None:
            build_measured(root)
            for relative in (
                "publish/publish-receipt.json",
                "reviews/live-verification.json",
                "measurement/baseline.json",
                "measurement/snapshots/2026-08-29.json",
            ):
                write_json(root / relative, [])

        code, report = self.run_in_temp(builder)
        self.assertEqual(code, 1)
        codes = {item["code"] for item in report["findings"]}
        self.assertIn("PUBLISH_RECEIPT_TYPE_INVALID", codes, report)
        self.assertIn("LIVE_VERIFICATION_TYPE_INVALID", codes, report)
        self.assertIn("MEASUREMENT_BASELINE_TYPE_INVALID", codes, report)
        self.assertIn("MEASUREMENT_SNAPSHOT_TYPE_INVALID", codes, report)

    def test_valid_measured_state_passes(self):
        code, report = self.run_in_temp(build_measured)
        self.assertEqual(code, 0, report)

    def test_media_valid_fixture_passes(self):
        result = subprocess.run(
            [sys.executable, str(VALIDATE_MEDIA), str(FIXTURES / "media-valid.json")],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_media_invalid_fixture_fails(self):
        result = subprocess.run(
            [sys.executable, str(VALIDATE_MEDIA), str(FIXTURES / "media-invalid.json")],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        report = json.loads(result.stdout)
        self.assertGreater(report["counts"]["errors"], 0, report)


if __name__ == "__main__":
    unittest.main(verbosity=2)
