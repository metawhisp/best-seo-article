#!/usr/bin/env python3
"""Regression locks for the final cross-artifact release contract."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from jsonschema import Draft202012Validator
except ImportError:  # Runtime remains usable without the optional schema library.
    Draft202012Validator = None  # type: ignore[assignment]


EVALS_ROOT = Path(__file__).resolve().parent
SKILL_ROOT = EVALS_ROOT.parent
if str(EVALS_ROOT) not in sys.path:
    sys.path.insert(0, str(EVALS_ROOT))
if str(SKILL_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from run_structural_evals import (  # noqa: E402
    NOW,
    artifact_hashes,
    build_content_ready,
    build_measured,
    build_publish_package,
    refresh_content_reviews,
    rehash_publish,
    sync_intake_authorization,
    validate,
    write_json,
    write_text,
)
from test_media_adversarial import (  # noqa: E402
    configure_output,
    issue_codes,
    load_fixture,
    run_validator,
    single_asset_manifest,
)
from validate_run import urls_match, valid_document_url, valid_http_url  # noqa: E402


def add_valid_hero_media(root: Path) -> None:
    """Attach one checksummed local media asset to an existing package fixture."""

    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    payload = b"RIFF\x04\x00\x00\x00WEBPVP8 "
    media = single_asset_manifest(0)
    media["run_id"] = manifest["run_id"]
    media["assets"][0]["source"]["retrieved_at"] = NOW
    configure_output(media["assets"][0], "media/hero.webp", "image/webp", payload)
    output = root / "media/hero.webp"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    write_json(root / "media-manifest.json", media)

    image = "\n![Evidence workflow](../media/hero.webp)\n"
    for relative in ("drafts/final.md", "publish/article.md"):
        path = root / relative
        write_text(path, path.read_text(encoding="utf-8") + image)
    refresh_content_reviews(root)

    package_path = root / "publish/publish-manifest.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package["files"].extend(
        [
            {"path": "media/hero.webp", "sha256": "0" * 64},
            {"path": "media-manifest.json", "sha256": "0" * 64},
        ]
    )
    write_json(package_path, package)
    technical_path = root / "reviews/technical.json"
    technical = json.loads(technical_path.read_text(encoding="utf-8"))
    technical["checks"]["assets"] = {
        "status": "passed",
        "evidence": "The checksummed declared hero asset was inspected in the static package.",
    }
    write_json(technical_path, technical)
    rehash_publish(root)


class FinalContractRegressions(unittest.TestCase):
    @unittest.skipIf(Draft202012Validator is None, "jsonschema is optional")
    def test_schemas_reject_lifecycle_date_and_core_check_bypasses(self) -> None:
        manifest_schema = json.loads((SKILL_ROOT / "schemas/article-manifest.schema.json").read_text(encoding="utf-8"))
        review_schema = json.loads((SKILL_ROOT / "schemas/review.schema.json").read_text(encoding="utf-8"))
        manifest_validator = Draft202012Validator(manifest_schema)
        review_validator = Draft202012Validator(review_schema)

        with tempfile.TemporaryDirectory(prefix="seo-schema-lifecycle-") as temporary:
            root = Path(temporary)
            manifest = build_measured(root)
            manifest["requested_status"] = "blocked"
            self.assertTrue(list(manifest_validator.iter_errors(manifest)))

        with tempfile.TemporaryDirectory(prefix="seo-schema-review-") as temporary:
            root = Path(temporary)
            build_publish_package(root)
            technical = json.loads((root / "reviews/technical.json").read_text(encoding="utf-8"))
            technical["checks"] = {
                "foo": {"status": "not-applicable", "evidence": "This arbitrary check has enough evidence."}
            }
            self.assertTrue(list(review_validator.iter_errors(technical)))

            technical = json.loads((root / "reviews/technical.json").read_text(encoding="utf-8"))
            technical["reviewed_at"] = "2025-02-29T12:00:00Z"
            self.assertTrue(list(review_validator.iter_errors(technical)))

    def test_browser_ambiguous_http_hosts_fail_closed(self) -> None:
        invalid = (
            "https://999.999.999.999/path",
            "https://2130706433/path",
            "https://0x7f000001/path",
            "https://0127.0.0.1/path",
            "https://example.test../path",
            "https://example.test./path",
            "https://example.test:0/path",
            "https://xn--a.com/path",
            "https://xn--bbg.com/path",
            "https://[::::]/path",
            "https://[::1]/path",
            "https://example.test:/path",
            "https://example.test:080/path",
            "https://example.test/a/../path",
            "https://example.test/a/%2e%2e/path",
            "https://example.test/a%2fpath",
        )
        for url in invalid:
            with self.subTest(url=url):
                self.assertFalse(valid_http_url(url))
        self.assertTrue(valid_http_url("https://example.test/path"))
        self.assertTrue(valid_http_url("https://192.0.2.1/path"))
        self.assertTrue(valid_http_url("https://example.test/path#section"))
        self.assertFalse(valid_document_url("https://example.test/path#section"))
        self.assertFalse(urls_match("https://example.test/path;", "https://example.test/path"))

    @unittest.skipIf(Draft202012Validator is None, "jsonschema is optional")
    def test_schemas_reject_placeholder_approvals_and_claim_evidence(self) -> None:
        review_schema = json.loads((SKILL_ROOT / "schemas/review.schema.json").read_text(encoding="utf-8"))
        media_schema = json.loads((SKILL_ROOT / "schemas/media-manifest.schema.json").read_text(encoding="utf-8"))
        claim_schema = json.loads((SKILL_ROOT / "schemas/claim.schema.json").read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory(prefix="seo-placeholder-schema-") as temporary:
            root = Path(temporary)
            build_publish_package(root)
            review = json.loads((root / "reviews/technical.json").read_text(encoding="utf-8"))
            review["reviewer"] = "TODO reviewer"
            self.assertTrue(list(Draft202012Validator(review_schema).iter_errors(review)))

        media = load_fixture()
        media["assets"][1]["rights"]["manual_review"]["evidence"] = "TBD rights evidence"
        self.assertTrue(list(Draft202012Validator(media_schema).iter_errors(media)))

        claim = {
            "claim_id": "C1", "text": "Supported claim", "location": "[NEEDS LOCATION]",
            "classification": "load-bearing", "claim_type": "factual", "source_ids": ["S1"],
            "support_status": "verified", "freshness_status": "current", "exact_support": "TODO",
            "verifier": "TODO reviewer", "resolution": "TBD", "as_of": "2026-08-29",
        }
        self.assertTrue(list(Draft202012Validator(claim_schema).iter_errors(claim)))

    @unittest.skipIf(Draft202012Validator is None, "jsonschema is optional")
    def test_schemas_reject_negative_observation_and_review_evidence(self) -> None:
        review_schema = json.loads((SKILL_ROOT / "schemas/review.schema.json").read_text(encoding="utf-8"))
        media_schema = json.loads((SKILL_ROOT / "schemas/media-manifest.schema.json").read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory(prefix="seo-negative-evidence-schema-") as temporary:
            root = Path(temporary)
            build_publish_package(root)
            review = json.loads((root / "reviews/technical.json").read_text(encoding="utf-8"))
            review["checks"]["links"]["evidence"] = "The links were not checked in the packaged article."
            self.assertTrue(list(Draft202012Validator(review_schema).iter_errors(review)))

        media = load_fixture()
        media["assets"][1]["rights"]["manual_review"]["evidence"] = "The releases were not reviewed for this asset."
        self.assertTrue(list(Draft202012Validator(media_schema).iter_errors(media)))

    def test_scope_change_invalidates_bound_content_reviews(self) -> None:
        with tempfile.TemporaryDirectory(prefix="seo-intake-binding-") as temporary:
            root = Path(temporary)
            manifest = build_content_ready(root)
            manifest["requested_status"] = "measured"
            manifest["permissions"]["publish"] = True
            write_json(root / "manifest.json", manifest)
            intake_path = root / "intake.json"
            intake = json.loads(intake_path.read_text(encoding="utf-8"))
            intake["requested_status"] = "measured"
            intake["permissions"] = manifest["permissions"]
            write_json(intake_path, intake)

            code, report = validate(root)
            hard_codes = {
                item.get("code")
                for item in report.get("findings", [])
                if item.get("severity") in {"P0", "P1"}
            }
            self.assertEqual(code, 1, report)
            self.assertIn("VERIFICATION_BINDING_MISSING", hard_codes)
            self.assertIn("EDITORIAL_REVIEW_BINDING_MISSING", hard_codes)

    def test_url_change_permission_is_explicit_in_both_bound_records(self) -> None:
        with tempfile.TemporaryDirectory(prefix="seo-url-permission-") as temporary:
            root = Path(temporary)
            manifest = build_content_ready(root)
            manifest["permissions"].pop("url_change")
            write_json(root / "manifest.json", manifest)
            intake = json.loads((root / "intake.json").read_text(encoding="utf-8"))
            intake["permissions"].pop("url_change")
            write_json(root / "intake.json", intake)
            refresh_content_reviews(root)

            code, report = validate(root)
            codes = {item.get("code") for item in report.get("findings", [])}
            self.assertEqual(code, 1, report)
            self.assertIn("PERMISSIONS_INVALID", codes)

    def test_risk_roles_and_protected_scope_cannot_change_after_bound_reviews(self) -> None:
        mutations = (
            ("risk", lambda manifest: manifest.__setitem__("risk", {"ymyl": True, "jurisdiction": "US"})),
            ("roles", lambda manifest: manifest["roles"].__setitem__("writer", "replacement-writer")),
            ("protected", lambda manifest: manifest["protected"].__setitem__("links", ["https://example.test/protected"])),
        )
        for name, mutate in mutations:
            with self.subTest(name=name), tempfile.TemporaryDirectory(prefix=f"seo-bound-{name}-") as temporary:
                root = Path(temporary)
                manifest = build_content_ready(root)
                mutate(manifest)
                write_json(root / "manifest.json", manifest)

                code, report = validate(root)
                codes = {item.get("code") for item in report.get("findings", [])}
                self.assertEqual(code, 1, report)
                self.assertIn("INTAKE_IDENTITY_MISMATCH", codes)

    def test_needs_expert_review_rejects_unresolved_final_draft_markers(self) -> None:
        with tempfile.TemporaryDirectory(prefix="seo-expert-placeholder-") as temporary:
            root = Path(temporary)
            manifest = build_content_ready(root)
            manifest["risk"] = {"ymyl": True, "jurisdiction": "US"}
            manifest["actual_status"] = "needs-expert-review"
            manifest["requested_status"] = "needs-expert-review"
            write_json(root / "manifest.json", manifest)
            sync_intake_authorization(root, manifest)
            write_text(root / "drafts/final.md", "# Expert review draft\n\n[NEEDS EVIDENCE]\n")
            refresh_content_reviews(root)
            write_json(
                root / "reviews/ymyl.json",
                {
                    "contract_version": "review-binding-v1",
                    "run_id": manifest["run_id"],
                    "review_type": "ymyl",
                    "review_required": True,
                    "status": "pending",
                    "requested_at": NOW,
                    "artifact_hashes": artifact_hashes(root),
                    "scope": "Material factual claims and reader actions",
                    "jurisdiction": "US",
                    "claims_requiring_review": ["C1"],
                    "findings": [],
                },
            )

            code, report = validate(root)
            codes = {item.get("code") for item in report.get("findings", [])}
            self.assertEqual(code, 1, report)
            self.assertIn("FINAL_DRAFT_PLACEHOLDER", codes)

    def test_publish_html_rejects_forbidden_visible_unicode_controls(self) -> None:
        with tempfile.TemporaryDirectory(prefix="seo-html-controls-") as temporary:
            root = Path(temporary)
            manifest = build_publish_package(root)
            manifest["destination"]["format"] = "html"
            write_json(root / "manifest.json", manifest)
            (root / "publish/article.md").unlink()
            write_text(
                root / "publish/article.html",
                "<h1>How evidence-led content works</h1><h2>Evidence</h2>"
                "<p>Search documentation recommends evidence-led, useful content.\u202e</p>",
            )
            package = json.loads((root / "publish/publish-manifest.json").read_text(encoding="utf-8"))
            package["files"][0]["path"] = "publish/article.html"
            write_json(root / "publish/publish-manifest.json", package)
            rehash_publish(root, sync_destination=True)

            code, report = validate(root)
            codes = {item.get("code") for item in report.get("findings", [])}
            self.assertEqual(code, 1, report)
            self.assertIn("PUBLISH_ARTICLE_UNICODE_CONTROL", codes)

    def test_publish_manifest_rejects_noncanonical_file_path_spellings(self) -> None:
        invalid_paths = ("publish/article.md/", "publish/article.md/./", "publish\\..\\outside.txt")
        for invalid_path in invalid_paths:
            with self.subTest(path=invalid_path), tempfile.TemporaryDirectory(prefix="seo-package-path-") as temporary:
                root = Path(temporary)
                build_measured(root)
                package_path = root / "publish/publish-manifest.json"
                package = json.loads(package_path.read_text(encoding="utf-8"))
                package["files"][0]["path"] = invalid_path
                write_json(package_path, package)
                code, report = validate(root)
                codes = {item.get("code") for item in report.get("findings", [])}
                self.assertEqual(code, 1, report)
                self.assertIn("PUBLISH_FILE_PATH_INVALID", codes)

    def test_publish_article_rejects_file_links_with_directory_alias_spelling(self) -> None:
        for href in ("asset.txt/", "..\\..\\outside.txt", "%2e%2e/%2e%2e/outside.txt"):
            with self.subTest(href=href), tempfile.TemporaryDirectory(prefix="seo-link-path-") as temporary:
                root = Path(temporary)
                build_publish_package(root)
                write_text(root / "publish/asset.txt", "Local package evidence.\n")
                article_path = root / "publish/article.md"
                article = article_path.read_text(encoding="utf-8") + f"\n[Asset]({href})\n"
                write_text(article_path, article)
                write_text(root / "drafts/final.md", article)
                refresh_content_reviews(root)
                package_path = root / "publish/publish-manifest.json"
                package = json.loads(package_path.read_text(encoding="utf-8"))
                package["files"].append({"path": "publish/asset.txt", "sha256": "0" * 64})
                write_json(package_path, package)
                rehash_publish(root)
                code, report = validate(root)
                codes = {item.get("code") for item in report.get("findings", [])}
                self.assertEqual(code, 1, report)
                self.assertIn("LOCAL_LINK_PATH_INVALID", codes)

    def test_publish_article_rejects_protocol_relative_external_hosts(self) -> None:
        for href in ("//2130706433/", "//evil.example./", "//[::1]/"):
            with self.subTest(href=href), tempfile.TemporaryDirectory(prefix="seo-network-link-") as temporary:
                root = Path(temporary)
                build_publish_package(root)
                article_path = root / "publish/article.md"
                article = article_path.read_text(encoding="utf-8") + f"\n[External]({href})\n"
                write_text(article_path, article)
                write_text(root / "drafts/final.md", article)
                refresh_content_reviews(root)
                rehash_publish(root)
                code, report = validate(root)
                codes = {item.get("code") for item in report.get("findings", [])}
                self.assertEqual(code, 1, report)
                self.assertIn("LINK_URL_INVALID", codes)

    def test_schema_and_media_not_applicable_are_bound_to_real_package_context(self) -> None:
        with tempfile.TemporaryDirectory(prefix="seo-schema-na-") as temporary:
            root = Path(temporary)
            build_publish_package(root)
            technical_path = root / "reviews/technical.json"
            technical = json.loads(technical_path.read_text(encoding="utf-8"))
            technical["checks"]["schema"] = {
                "status": "not-applicable",
                "evidence": "Structured data was declared outside this review scope.",
            }
            write_json(technical_path, technical)
            code, report = validate(root)
            codes = {item.get("code") for item in report.get("findings", [])}
            self.assertEqual(code, 1, report)
            self.assertIn("TECHNICAL_CORE_CHECKS_MISSING", codes)

        with tempfile.TemporaryDirectory(prefix="seo-schema-reason-") as temporary:
            root = Path(temporary)
            build_publish_package(root)
            write_json(root / "publish/schema.json", {"applicable": False, "reason": {"truthy": "object"}})
            rehash_publish(root)
            code, report = validate(root)
            codes = {item.get("code") for item in report.get("findings", [])}
            self.assertEqual(code, 1, report)
            self.assertIn("SCHEMA_DECISION_UNEXPLAINED", codes)

        with tempfile.TemporaryDirectory(prefix="seo-media-na-") as temporary:
            root = Path(temporary)
            build_publish_package(root)
            add_valid_hero_media(root)
            technical_path = root / "reviews/technical.json"
            technical = json.loads(technical_path.read_text(encoding="utf-8"))
            technical["checks"]["assets"] = {
                "status": "not-applicable",
                "evidence": "Media was incorrectly declared outside this review scope.",
            }
            write_json(technical_path, technical)
            code, report = validate(root)
            codes = {item.get("code") for item in report.get("findings", [])}
            self.assertEqual(code, 1, report)
            self.assertIn("TECHNICAL_CORE_CHECKS_MISSING", codes)

        with tempfile.TemporaryDirectory(prefix="seo-live-na-") as temporary:
            root = Path(temporary)
            build_measured(root)
            add_valid_hero_media(root)
            technical_path = root / "reviews/technical.json"
            technical = json.loads(technical_path.read_text(encoding="utf-8"))
            technical["checks"]["assets"] = {
                "status": "passed",
                "evidence": "The packaged hero asset was inspected and loaded.",
            }
            write_json(technical_path, technical)
            live_path = root / "reviews/live-verification.json"
            live = json.loads(live_path.read_text(encoding="utf-8"))
            live["checks"]["assets"] = {
                "status": "not-applicable",
                "evidence": "Media was incorrectly declared outside live verification.",
            }
            write_json(live_path, live)
            code, report = validate(root)
            codes = {item.get("code") for item in report.get("findings", [])}
            self.assertEqual(code, 1, report)
            self.assertIn("LIVE_VERIFICATION_CHECK_FAILED", codes)

    def test_malformed_optional_review_checks_are_gating(self) -> None:
        with tempfile.TemporaryDirectory(prefix="seo-review-checks-") as temporary:
            root = Path(temporary)
            build_content_ready(root)
            editorial_path = root / "reviews/editorial.json"
            editorial = json.loads(editorial_path.read_text(encoding="utf-8"))
            editorial["checks"] = "garbage"
            write_json(editorial_path, editorial)

            code, report = validate(root)
            codes = {item.get("code") for item in report.get("findings", [])}
            self.assertEqual(code, 1, report)
            self.assertIn("EDITORIAL_REVIEW_CHECKS_INVALID", codes)

    def test_measurement_snapshot_filename_controls_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="seo-snapshot-name-") as temporary:
            root = Path(temporary)
            build_measured(root)
            original = root / "measurement/snapshots/2026-08-29.json"
            original.rename(root / "measurement/snapshots/after\u202e.json")

            code, report = validate(root)
            codes = {item.get("code") for item in report.get("findings", [])}
            self.assertEqual(code, 1, report)
            self.assertIn("MEASUREMENT_SNAPSHOT_PATH_INVALID", codes)

    def test_measurement_evidence_paths_require_canonical_literal_spelling(self) -> None:
        with tempfile.TemporaryDirectory(prefix="seo-evidence-path-") as temporary:
            root = Path(temporary)
            build_measured(root)
            baseline_path = root / "measurement/baseline.json"
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            baseline["source_evidence"][0]["path"] += "/"
            write_json(baseline_path, baseline)
            code, report = validate(root)
            codes = {item.get("code") for item in report.get("findings", [])}
            self.assertEqual(code, 1, report)
            self.assertIn("MEASUREMENT_BASELINE_EVIDENCE_FILE_INVALID", codes)

    def test_init_rejects_inputs_that_would_create_an_invalid_scaffold(self) -> None:
        init = SKILL_ROOT / "scripts/init_run.py"
        cases = (
            ("--target", "topic\nspoof"),
            ("--language", ""),
            ("--site", "not-a-url"),
            ("--site", "https://example.test/#fragment"),
            ("--site", "https://example.test:/path"),
        )
        for flag, value in cases:
            with self.subTest(flag=flag), tempfile.TemporaryDirectory(prefix="seo-init-invalid-") as temporary:
                output = Path(temporary) / "run"
                command = [sys.executable, str(init), "--mode", "new", "--target", "topic", "--output", str(output)]
                command.extend([flag, value])
                result = subprocess.run(command, check=False, capture_output=True, text=True)
                self.assertEqual(result.returncode, 2, result)
                self.assertFalse(output.exists())
                self.assertEqual(json.loads(result.stderr)["error"], "invalid_input")

        with tempfile.TemporaryDirectory(prefix="seo-init-ymyl-") as temporary:
            output = Path(temporary) / "run"
            result = subprocess.run(
                [sys.executable, str(init), "--mode", "new", "--target", "topic", "--output", str(output), "--ymyl", "true"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 2, result)
            self.assertFalse(output.exists())

        with tempfile.TemporaryDirectory(prefix="seo-init-cli-") as temporary:
            output = Path(temporary) / "run"
            result = subprocess.run(
                [sys.executable, str(init), "--mode", "BAD", "--target", "topic", "--output", str(output)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 2, result)
            self.assertEqual(json.loads(result.stderr)["error"], "invalid_arguments")
            self.assertNotIn("usage:", result.stderr)

        with tempfile.TemporaryDirectory(prefix="seo-init-file-") as temporary:
            output = Path(temporary) / "run"
            output.write_text("occupied", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(init), "--mode", "new", "--target", "topic", "--output", str(output)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1, result)
            self.assertEqual(json.loads(result.stderr)["error"], "output_not_directory")
            self.assertNotIn("Traceback", result.stderr)

    def test_bound_scope_objects_use_the_closed_intake_shape(self) -> None:
        with tempfile.TemporaryDirectory(prefix="seo-scope-shape-") as temporary:
            root = Path(temporary)
            manifest = build_content_ready(root)
            manifest["risk"] = {"ymyl": False}
            manifest["roles"] = {"writer": "writer-pass", "verifier": "verifier-pass", "editor": "editor-pass"}
            manifest["protected"] = {}
            manifest["permissions"]["surprise"] = True
            write_json(root / "manifest.json", manifest)
            sync_intake_authorization(root, manifest)
            refresh_content_reviews(root)

            code, report = validate(root)
            codes = {item.get("code") for item in report.get("findings", [])}
            self.assertEqual(code, 1, report)
            self.assertTrue(
                {
                    "MANIFEST_RISK_SHAPE_INVALID",
                    "MANIFEST_ROLES_SHAPE_INVALID",
                    "MANIFEST_PROTECTED_SHAPE_INVALID",
                    "MANIFEST_PERMISSIONS_SHAPE_INVALID",
                }.issubset(codes),
                report,
            )

    def test_web_research_permission_is_bound_to_acquisition_provenance(self) -> None:
        with tempfile.TemporaryDirectory(prefix="seo-research-permission-") as temporary:
            root = Path(temporary)
            manifest = build_content_ready(root)
            manifest["permissions"]["web_research"] = False
            write_json(root / "manifest.json", manifest)
            sync_intake_authorization(root, manifest)
            refresh_content_reviews(root)
            code, report = validate(root)
            codes = {item.get("code") for item in report.get("findings", [])}
            self.assertEqual(code, 1, report)
            self.assertIn("WEB_RESEARCH_UNAUTHORIZED", codes)

            serp_path = root / "research/serp.json"
            serp = json.loads(serp_path.read_text(encoding="utf-8"))
            serp["acquisition"] = "user-provided"
            write_json(serp_path, serp)
            sources_path = root / "research/sources.jsonl"
            source = json.loads(sources_path.read_text(encoding="utf-8"))
            source["acquisition"] = "user-provided"
            write_text(sources_path, json.dumps(source) + "\n")
            refresh_content_reviews(root)
            code, report = validate(root)
            self.assertEqual(code, 0, report)

    def test_stale_serp_snapshot_cannot_claim_current_content_readiness(self) -> None:
        with tempfile.TemporaryDirectory(prefix="seo-serp-stale-") as temporary:
            root = Path(temporary)
            build_content_ready(root)
            serp_path = root / "research/serp.json"
            serp = json.loads(serp_path.read_text(encoding="utf-8"))
            serp["captured_at"] = "2010-01-01T00:00:00Z"
            write_json(serp_path, serp)
            code, report = validate(root)
            codes = {item.get("code") for item in report.get("findings", [])}
            self.assertEqual(code, 1, report)
            self.assertIn("SERP_CAPTURE_STALE", codes)

    def test_publish_manifest_cannot_export_internal_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="seo-package-boundary-") as temporary:
            root = Path(temporary)
            build_measured(root)
            article_path = root / "publish/article.md"
            article = article_path.read_text(encoding="utf-8") + "\n[Raw analytics](../measurement/evidence/gsc-baseline.csv)\n"
            write_text(article_path, article)
            write_text(root / "drafts/final.md", article)
            refresh_content_reviews(root)
            package_path = root / "publish/publish-manifest.json"
            package = json.loads(package_path.read_text(encoding="utf-8"))
            package["files"].append({"path": "measurement/evidence/gsc-baseline.csv", "sha256": "0" * 64})
            write_json(package_path, package)
            rehash_publish(root)

            code, report = validate(root)
            codes = {item.get("code") for item in report.get("findings", [])}
            self.assertEqual(code, 1, report)
            self.assertIn("PUBLISH_FILE_OUTSIDE_DELIVERABLE_SCOPE", codes)
            self.assertIn("LOCAL_LINK_UNLISTED", codes)

    def test_publish_tree_rejects_symlink_directories_and_special_nodes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="seo-package-nodes-") as temporary:
            base = Path(temporary)
            root = base / "run"
            external = base / "external"
            external.mkdir()
            write_text(external / "payload.txt", "external bytes\n")
            build_publish_package(root)
            (root / "publish/extra").symlink_to(external, target_is_directory=True)
            code, report = validate(root)
            codes = {item.get("code") for item in report.get("findings", [])}
            self.assertEqual(code, 1, report)
            self.assertIn("PUBLISH_ENTRY_SYMLINK", codes)

        if hasattr(os, "mkfifo"):
            with tempfile.TemporaryDirectory(prefix="seo-package-fifo-") as temporary:
                root = Path(temporary)
                build_publish_package(root)
                os.mkfifo(root / "publish/pipe")
                code, report = validate(root)
                codes = {item.get("code") for item in report.get("findings", [])}
                self.assertEqual(code, 1, report)
                self.assertIn("PUBLISH_ENTRY_SPECIAL", codes)

        with tempfile.TemporaryDirectory(prefix="seo-media-root-link-") as temporary:
            base = Path(temporary)
            root = base / "run"
            build_content_ready(root)
            (root / "media").symlink_to(base / "outside")
            code, report = validate(root)
            codes = {item.get("code") for item in report.get("findings", [])}
            self.assertEqual(code, 1, report)
            self.assertIn("MEDIA_DIRECTORY_SYMLINK", codes)

        if hasattr(os, "mkfifo"):
            with tempfile.TemporaryDirectory(prefix="seo-media-root-fifo-") as temporary:
                root = Path(temporary)
                build_content_ready(root)
                os.mkfifo(root / "media")
                code, report = validate(root)
                codes = {item.get("code") for item in report.get("findings", [])}
                self.assertEqual(code, 1, report)
                self.assertIn("MEDIA_DIRECTORY_SPECIAL", codes)

    def test_publish_tree_rejects_undeclared_extra_deliverables(self) -> None:
        with tempfile.TemporaryDirectory(prefix="seo-extra-deliverable-") as temporary:
            root = Path(temporary)
            build_publish_package(root)
            write_text(root / "publish/extra.html", "<script>run()</script>\n")
            package_path = root / "publish/publish-manifest.json"
            package = json.loads(package_path.read_text(encoding="utf-8"))
            package["files"].append({"path": "publish/extra.html", "sha256": "0" * 64})
            write_json(package_path, package)
            rehash_publish(root)
            code, report = validate(root)
            codes = {item.get("code") for item in report.get("findings", [])}
            self.assertEqual(code, 1, report)
            self.assertIn("PUBLISH_ENTRY_OUTSIDE_DELIVERABLE_SCOPE", codes)

        with tempfile.TemporaryDirectory(prefix="seo-declared-asset-positive-") as temporary:
            root = Path(temporary)
            build_publish_package(root)
            add_valid_hero_media(root)
            code, report = validate(root)
            self.assertEqual(code, 0, report)

    def test_schema_slug_and_headline_visibility_are_release_gates(self) -> None:
        schema_cases = (
            ({"@context": None, "@type": "Article", "headline": "How evidence-led content works"}, "SCHEMA_CONTEXT_INVALID"),
            ({"@context": "https://schema.org", "@type": "Organization", "headline": "How evidence-led content works"}, "SCHEMA_TYPE_INVALID"),
            ({"@context": "https://schema.org"}, "SCHEMA_TYPE_INVALID"),
        )
        for schema_payload, expected in schema_cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory(prefix="seo-schema-shape-") as temporary:
                root = Path(temporary)
                build_publish_package(root)
                write_json(root / "publish/schema.json", schema_payload)
                rehash_publish(root)
                code, report = validate(root)
                codes = {item.get("code") for item in report.get("findings", [])}
                self.assertEqual(code, 1, report)
                self.assertIn(expected, codes)

        with tempfile.TemporaryDirectory(prefix="seo-schema-hidden-") as temporary:
            root = Path(temporary)
            build_publish_package(root)
            hidden = "\n<!-- Hidden SEO headline --><span hidden>Hidden SEO headline</span><template>Hidden SEO headline</template>\n"
            for relative in ("drafts/final.md", "publish/article.md"):
                path = root / relative
                write_text(path, path.read_text(encoding="utf-8") + hidden)
            write_json(
                root / "publish/schema.json",
                {"@context": "https://schema.org", "@type": "Article", "headline": "Hidden SEO headline"},
            )
            refresh_content_reviews(root)
            rehash_publish(root)
            code, report = validate(root)
            codes = {item.get("code") for item in report.get("findings", [])}
            self.assertEqual(code, 1, report)
            self.assertIn("SCHEMA_NOT_VISIBLE", codes)

        with tempfile.TemporaryDirectory(prefix="seo-schema-nested-hidden-") as temporary:
            root = Path(temporary)
            build_publish_package(root)
            hidden = '<span hidden><span>inner</span>Hidden SEO headline</span>\n'
            for relative in ("drafts/final.md", "publish/article.md"):
                path = root / relative
                write_text(path, path.read_text(encoding="utf-8") + hidden)
            write_json(root / "publish/schema.json", {"@context": "https://schema.org", "@type": "Article", "headline": "Hidden SEO headline"})
            refresh_content_reviews(root)
            rehash_publish(root)
            code, report = validate(root)
            codes = {item.get("code") for item in report.get("findings", [])}
            self.assertEqual(code, 1, report)
            self.assertIn("SCHEMA_NOT_VISIBLE", codes)

        with tempfile.TemporaryDirectory(prefix="seo-schema-body-phrase-") as temporary:
            root = Path(temporary)
            build_publish_package(root)
            write_json(root / "publish/schema.json", {"@context": "https://schema.org", "@type": "Article", "headline": "Evidence"})
            rehash_publish(root)
            code, report = validate(root)
            codes = {item.get("code") for item in report.get("findings", [])}
            self.assertEqual(code, 1, report)
            self.assertIn("SCHEMA_NOT_VISIBLE", codes)

        for slug in ("../../admin", "hello world", "https://evil.example/x"):
            with self.subTest(slug=slug), tempfile.TemporaryDirectory(prefix="seo-slug-") as temporary:
                root = Path(temporary)
                build_publish_package(root)
                metadata_path = root / "publish/metadata.json"
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                metadata["slug"] = slug
                write_json(metadata_path, metadata)
                rehash_publish(root)
                code, report = validate(root)
                codes = {item.get("code") for item in report.get("findings", [])}
                self.assertEqual(code, 1, report)
                self.assertIn("METADATA_SLUG_INVALID", codes)

    def test_technical_check_aliases_cannot_mix_pass_and_not_applicable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="seo-tech-duplicates-") as temporary:
            root = Path(temporary)
            build_publish_package(root)
            technical_path = root / "reviews/technical.json"
            technical = json.loads(technical_path.read_text(encoding="utf-8"))
            checks = [
                {"check": name, "status": value["status"], "evidence": value["evidence"]}
                for name, value in technical["checks"].items()
            ]
            checks.append({"check": "schema", "status": "not-applicable", "evidence": "No schema observation was recorded for this duplicate."})
            technical["checks"] = checks
            write_json(technical_path, technical)
            code, report = validate(root)
            codes = {item.get("code") for item in report.get("findings", [])}
            self.assertEqual(code, 1, report)
            self.assertIn("TECHNICAL_CHECK_DUPLICATE", codes)
            self.assertIn("TECHNICAL_CHECK_CONTEXT_INVALID", codes)

    def test_bare_outcome_tokens_are_not_observation_evidence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="seo-live-evidence-") as temporary:
            root = Path(temporary)
            build_measured(root)
            live_path = root / "reviews/live-verification.json"
            live = json.loads(live_path.read_text(encoding="utf-8"))
            live["checks"]["http"]["evidence"] = "not-applicable"
            write_json(live_path, live)
            code, report = validate(root)
            codes = {item.get("code") for item in report.get("findings", [])}
            self.assertEqual(code, 1, report)
            self.assertIn("LIVE_VERIFICATION_CHECK_FAILED", codes)

    def test_yaml_anchor_cannot_hide_noindex(self) -> None:
        with tempfile.TemporaryDirectory(prefix="seo-yaml-anchor-") as temporary:
            root = Path(temporary)
            build_publish_package(root)
            prefix = "---\nnoindex: &disabled true\n---\n"
            for relative in ("drafts/final.md", "publish/article.md"):
                path = root / relative
                write_text(path, prefix + path.read_text(encoding="utf-8"))
            refresh_content_reviews(root)
            rehash_publish(root)
            code, report = validate(root)
            codes = {item.get("code") for item in report.get("findings", [])}
            self.assertEqual(code, 1, report)
            self.assertIn("PUBLISH_INDEXABILITY_CONFLICT", codes)

        for prefix in (
            'robots: "no\\u0069ndex"',
            '"no\\u0069ndex": true',
            'robots: "\\x6eofollow"',
            '? noindex\n: true',
            'key: &r noindex\n*r: true',
        ):
            with self.subTest(prefix=prefix), tempfile.TemporaryDirectory(prefix="seo-yaml-escape-") as temporary:
                root = Path(temporary)
                build_publish_package(root)
                frontmatter = f"---\n{prefix}\n---\n"
                for relative in ("drafts/final.md", "publish/article.md"):
                    path = root / relative
                    write_text(path, frontmatter + path.read_text(encoding="utf-8"))
                refresh_content_reviews(root)
                rehash_publish(root)
                code, report = validate(root)
                codes = {item.get("code") for item in report.get("findings", [])}
                self.assertEqual(code, 1, report)
                self.assertIn("PUBLISH_INDEXABILITY_CONFLICT", codes)

    def test_flow_frontmatter_cannot_supply_the_article_h1(self) -> None:
        with tempfile.TemporaryDirectory(prefix="seo-flow-frontmatter-") as temporary:
            root = Path(temporary)
            build_publish_package(root)
            article = '---\n{"title": "metadata"}\n# Fake hidden H1\n---\nVisible article body explains evidence.\n'
            write_text(root / "drafts/final.md", article)
            write_text(root / "publish/article.md", article)
            write_json(root / "publish/schema.json", {"@context": "https://schema.org", "@type": "Article", "headline": "Visible article body"})
            refresh_content_reviews(root)
            rehash_publish(root)
            code, report = validate(root)
            codes = {item.get("code") for item in report.get("findings", [])}
            self.assertEqual(code, 1, report)
            self.assertIn("PUBLISH_H1_COUNT", codes)

    def test_container_indexability_values_fail_closed(self) -> None:
        for field, value in (("noindex", [True]), ("index", [False])):
            with self.subTest(field=field), tempfile.TemporaryDirectory(prefix="seo-metadata-index-") as temporary:
                root = Path(temporary)
                build_publish_package(root)
                metadata_path = root / "publish/metadata.json"
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                metadata[field] = value
                write_json(metadata_path, metadata)
                rehash_publish(root)
                code, report = validate(root)
                codes = {item.get("code") for item in report.get("findings", [])}
                self.assertEqual(code, 1, report)
                self.assertIn("PUBLISH_INDEXABILITY_CONFLICT", codes)

    def test_lifecycle_evidence_is_bound_and_cannot_be_hidden_by_status_downgrade(self) -> None:
        with tempfile.TemporaryDirectory(prefix="seo-lifecycle-binding-") as temporary:
            root = Path(temporary)
            build_measured(root)
            for relative in ("drafts/final.md", "publish/article.md"):
                path = root / relative
                write_text(path, path.read_text(encoding="utf-8") + "\n## New reviewed section\n\nCurrent package bytes changed.\n")
            refresh_content_reviews(root)
            rehash_publish(root)
            code, report = validate(root)
            codes = {item.get("code") for item in report.get("findings", [])}
            self.assertEqual(code, 1, report)
            self.assertIn("PUBLISH_RECEIPT_PACKAGE_BINDING_INVALID", codes)

        with tempfile.TemporaryDirectory(prefix="seo-lifecycle-downgrade-") as temporary:
            root = Path(temporary)
            manifest = build_measured(root)
            manifest["actual_status"] = "publish-package-ready"
            manifest["requested_status"] = "publish-package-ready"
            manifest["permissions"]["publish"] = False
            write_json(root / "manifest.json", manifest)
            sync_intake_authorization(root, manifest)
            package_path = root / "publish/publish-manifest.json"
            package = json.loads(package_path.read_text(encoding="utf-8"))
            package["publication_authorized"] = False
            write_json(package_path, package)
            rehash_publish(root)
            code, report = validate(root)
            codes = {item.get("code") for item in report.get("findings", [])}
            self.assertEqual(code, 1, report)
            self.assertIn("PRESENT_PUBLICATION_UNAUTHORIZED", codes)
            self.assertIn("PRESENT_PUBLICATION_STATUS_CONTRADICTION", codes)
            self.assertIn("PRESENT_LIVE_STATUS_CONTRADICTION", codes)
            self.assertIn("PRESENT_MEASUREMENT_STATUS_CONTRADICTION", codes)

    def test_research_permission_is_presence_driven_and_claims_bind_to_draft(self) -> None:
        with tempfile.TemporaryDirectory(prefix="seo-research-downgrade-") as temporary:
            root = Path(temporary)
            manifest = build_content_ready(root)
            manifest["actual_status"] = "draft-only"
            manifest["requested_status"] = "draft-only"
            manifest["permissions"]["web_research"] = False
            write_json(root / "manifest.json", manifest)
            sync_intake_authorization(root, manifest)
            code, report = validate(root)
            codes = {item.get("code") for item in report.get("findings", [])}
            self.assertEqual(code, 1, report)
            self.assertIn("WEB_RESEARCH_UNAUTHORIZED", codes)

        with tempfile.TemporaryDirectory(prefix="seo-claim-draft-binding-") as temporary:
            root = Path(temporary)
            build_content_ready(root)
            write_text(root / "drafts/final.md", "# Gardening guide\n\nSoil, pruning, and seasonal care.\n")
            refresh_content_reviews(root)
            code, report = validate(root)
            codes = {item.get("code") for item in report.get("findings", [])}
            self.assertEqual(code, 1, report)
            self.assertIn("CLAIMS_VALIDATOR_FAILED", codes)

        hidden_templates = (
            "<!-- Search documentation recommends evidence-led, useful content. -->",
            "```text\nSearch documentation recommends evidence-led, useful content.\n```",
            "[hidden]: https://example.test/ \"Search documentation recommends evidence-led, useful content.\"",
        )
        for hidden in hidden_templates:
            with self.subTest(hidden=hidden[:20]), tempfile.TemporaryDirectory(prefix="seo-hidden-claim-") as temporary:
                root = Path(temporary)
                build_content_ready(root)
                write_text(root / "drafts/final.md", f"# Gardening guide\n\n## Evidence\n\nSoil and pruning.\n\n{hidden}\n")
                refresh_content_reviews(root)
                code, report = validate(root)
                codes = {item.get("code") for item in report.get("findings", [])}
                self.assertEqual(code, 1, report)
                self.assertIn("CLAIMS_VALIDATOR_FAILED", codes)

    def test_destination_and_present_package_authorization_are_bound_to_intake(self) -> None:
        with tempfile.TemporaryDirectory(prefix="seo-destination-binding-") as temporary:
            root = Path(temporary)
            manifest = build_content_ready(root)
            manifest["destination"] = {"format": "markdown", "url": "https://other.test/article", "cms": None}
            write_json(root / "manifest.json", manifest)
            refresh_content_reviews(root)
            code, report = validate(root)
            codes = {item.get("code") for item in report.get("findings", [])}
            self.assertEqual(code, 1, report)
            self.assertIn("INTAKE_IDENTITY_MISMATCH", codes)

        with tempfile.TemporaryDirectory(prefix="seo-present-auth-") as temporary:
            root = Path(temporary)
            manifest = build_publish_package(root)
            manifest["actual_status"] = "content-ready"
            manifest["requested_status"] = "content-ready"
            write_json(root / "manifest.json", manifest)
            sync_intake_authorization(root, manifest)
            package_path = root / "publish/publish-manifest.json"
            package = json.loads(package_path.read_text(encoding="utf-8"))
            package["publication_authorized"] = True
            write_json(package_path, package)
            code, report = validate(root)
            codes = {item.get("code") for item in report.get("findings", [])}
            self.assertEqual(code, 1, report)
            self.assertIn("PRESENT_PACKAGE_AUTHORIZATION_CONTRADICTION", codes)

    def test_reserved_ledgers_reject_symlinks_and_special_nodes_at_draft_status(self) -> None:
        for relative in ("research/sources.jsonl", "claims.jsonl"):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory(prefix="seo-ledger-link-") as temporary:
                base = Path(temporary)
                root = base / "run"
                build_content_ready(root)
                manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
                manifest["actual_status"] = "draft-only"
                manifest["requested_status"] = "draft-only"
                write_json(root / "manifest.json", manifest)
                sync_intake_authorization(root, manifest)
                path = root / relative
                path.unlink()
                outside = base / "outside.jsonl"
                write_text(outside, "{}\n")
                path.symlink_to(outside)
                code, report = validate(root)
                codes = {item.get("code") for item in report.get("findings", [])}
                self.assertEqual(code, 1, report)
                self.assertIn("RESERVED_ARTIFACT_SYMLINK", codes)

        if hasattr(os, "mkfifo"):
            with tempfile.TemporaryDirectory(prefix="seo-ledger-fifo-") as temporary:
                root = Path(temporary)
                build_content_ready(root)
                manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
                manifest["actual_status"] = "draft-only"
                manifest["requested_status"] = "draft-only"
                write_json(root / "manifest.json", manifest)
                sync_intake_authorization(root, manifest)
                path = root / "claims.jsonl"
                path.unlink()
                os.mkfifo(path)
                code, report = validate(root)
                codes = {item.get("code") for item in report.get("findings", [])}
                self.assertEqual(code, 1, report)
                self.assertIn("RESERVED_ARTIFACT_SPECIAL", codes)

    def test_all_validator_cli_argument_failures_are_machine_readable(self) -> None:
        validators = (
            SKILL_ROOT / "scripts/validate_run.py",
            SKILL_ROOT / "scripts/validate_claims.py",
            SKILL_ROOT / "scripts/validate_media.py",
        )
        for validator in validators:
            with self.subTest(validator=validator.name):
                result = subprocess.run(
                    [sys.executable, str(validator), "--bogus"],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 2, result)
                report = json.loads(result.stdout)
                self.assertEqual(report["status"], "unavailable")
                self.assertEqual(result.stderr, "")
                self.assertNotIn("usage:", result.stdout)

    def test_media_output_paths_are_unique_and_control_free(self) -> None:
        with tempfile.TemporaryDirectory(prefix="seo-media-duplicates-") as temporary:
            root = Path(temporary)
            manifest = load_fixture()
            manifest["assets"][1]["output"]["path"] = manifest["assets"][0]["output"]["path"]
            path = root / "manifest.json"
            write_json(path, manifest)
            process, report = run_validator(path)
            self.assertEqual(process.returncode, 1, report)
            self.assertIn("V100_DUPLICATE_OUTPUT_PATH", issue_codes(report))

        with tempfile.TemporaryDirectory(prefix="seo-media-controls-") as temporary:
            root = Path(temporary)
            manifest = load_fixture()
            manifest["assets"][0]["output"]["path"] = "media/hero\ufe0f.webp"
            path = root / "manifest.json"
            write_json(path, manifest)
            process, report = run_validator(path)
            self.assertEqual(process.returncode, 1, report)
            self.assertIn("V099_FORBIDDEN_STRUCTURED_CHARACTER", issue_codes(report))


if __name__ == "__main__":
    unittest.main(verbosity=2)
