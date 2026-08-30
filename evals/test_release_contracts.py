#!/usr/bin/env python3
"""Red-first release-contract regressions for non-media article artifacts.

These tests describe hard release gates that are intentionally stricter than
the current validator.  They should remain red until validate_run.py binds
approvals, source exports, measurement semantics, and optional publish files to
the run being released.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:  # The runtime validators themselves remain standard-library only.
    Draft202012Validator = None  # type: ignore[assignment]
    FormatChecker = None  # type: ignore[assignment]


EVALS_ROOT = Path(__file__).resolve().parent
if str(EVALS_ROOT) not in sys.path:
    sys.path.insert(0, str(EVALS_ROOT))

from run_structural_evals import (  # noqa: E402
    CAPABILITY_PREFLIGHT,
    NOW,
    build_content_ready,
    build_measured,
    build_publish_package,
    rehash_publish,
    sync_handoff_status,
    sync_intake_authorization,
    validate,
    write_json,
    write_text,
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def before_run() -> str:
    created_at = datetime.fromisoformat(NOW.replace("Z", "+00:00"))
    return (created_at - timedelta(days=1)).isoformat().replace("+00:00", "Z")


def after_run(hours: int) -> str:
    created_at = datetime.fromisoformat(NOW.replace("Z", "+00:00"))
    return (created_at + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def content_artifact_hashes(root: Path, *, include_package: bool = False) -> dict[str, str]:
    paths = ["intake.json", "drafts/final.md", "claims.jsonl", "research/sources.jsonl", "research/quality-gate.json"]
    if include_package:
        paths.append("publish/publish-manifest.json")
    return {relative: sha256_file(root / relative) for relative in paths}


def approved_ymyl_review(root: Path, *, reviewed_at: str = NOW, bind: bool = True) -> None:
    manifest = build_content_ready(root)
    manifest["risk"] = {"ymyl": True, "jurisdiction": "US"}
    manifest["roles"]["expert_reviewer"] = "qualified-us-reviewer"
    write_json(root / "manifest.json", manifest)
    sync_intake_authorization(root, manifest)
    review: dict[str, Any] = {
        "review_required": True,
        "status": "approved",
        "reviewer": "qualified-us-reviewer",
        "credentials": "Licensed domain professional; release fixture only",
        "scope": "Material factual claims and reader actions in the final draft",
        "jurisdiction": "US",
        "reviewed_at": reviewed_at,
        "sections_reviewed": ["Evidence"],
        "claims_reviewed": ["C1"],
        "findings": [],
    }
    if bind:
        review.update(
            {
                "contract_version": "review-binding-v1",
                "run_id": manifest["run_id"],
                "review_type": "ymyl",
                "artifact_hashes": content_artifact_hashes(root),
            }
        )
    write_json(root / "reviews/ymyl.json", review)


def bound_review(root: Path, reviewer: str, checked_at: str, *, technical: bool = False) -> dict[str, Any]:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    review_type = "technical" if technical else ("editorial" if reviewer == "editor-pass" else "verification")
    return {
        "contract_version": "review-binding-v1",
        "status": "passed",
        "reviewer": reviewer,
        "review_type": review_type,
        "reviewed_at": checked_at,
        "run_id": manifest["run_id"],
        "artifact_hashes": content_artifact_hashes(root, include_package=technical),
        "findings": [],
    }


def package_as_mdx(root: Path, content: str) -> None:
    manifest = build_publish_package(root)
    old_article = root / "publish/article.md"
    old_article.unlink()
    write_text(root / "publish/article.mdx", content)
    manifest["destination"]["format"] = "mdx"
    write_json(root / "manifest.json", manifest)

    package = json.loads((root / "publish/publish-manifest.json").read_text(encoding="utf-8"))
    for record in package["files"]:
        if record["path"] == "publish/article.md":
            record["path"] = "publish/article.mdx"
    write_json(root / "publish/publish-manifest.json", package)
    rehash_publish(root, sync_destination=True)

    technical = json.loads((root / "reviews/technical.json").read_text(encoding="utf-8"))
    technical["scope"] = "Portable MDX package"
    technical["checks"]["reviewed_content_correspondence"] = {
        "status": "passed",
        "evidence": "The packaged visible prose corresponds to the independently reviewed draft.",
    }
    write_json(root / "reviews/technical.json", technical)


def add_structured_measurement_contract(
    root: Path,
    *,
    snapshot_start: str,
    snapshot_end: str,
    snapshot_unit: str = "count",
) -> None:
    baseline_path = root / "measurement/baseline.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline["comparison_window"] = {
        "start": "2026-07-12",
        "end_exclusive": "2026-08-08",
        "timezone": "UTC",
        "grain": "day",
    }
    write_json(baseline_path, baseline)

    snapshot_path = root / "measurement/snapshots/2026-08-29.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot["comparison_window"] = {
        "start": snapshot_start,
        "end_exclusive": snapshot_end,
        "timezone": "UTC",
        "grain": "day",
    }
    snapshot["metrics"]["clicks"]["unit"] = snapshot_unit
    write_json(snapshot_path, snapshot)


class ReleaseContractRegressions(unittest.TestCase):
    def run_fixture(self, builder: Callable[[Path], None]) -> tuple[int, dict[str, Any]]:
        with tempfile.TemporaryDirectory(prefix="best-seo-release-contract-") as temporary:
            root = Path(temporary)
            builder(root)
            code, report = validate(root)
            return code, report

    def assert_hard_code(self, code: int, report: dict[str, Any], expected: str) -> None:
        hard_codes = {
            item.get("code")
            for item in report.get("findings", [])
            if isinstance(item, dict) and item.get("severity") in {"P0", "P1"}
        }
        self.assertEqual(code, 1, report)
        self.assertIn(expected, hard_codes, report)

    def test_ymyl_approval_requires_run_and_content_hash_binding(self) -> None:
        code, report = self.run_fixture(lambda root: approved_ymyl_review(root, bind=False))
        self.assert_hard_code(code, report, "YMYL_REVIEW_BINDING_MISSING")

    def test_ymyl_approval_cannot_predate_run(self) -> None:
        code, report = self.run_fixture(
            lambda root: approved_ymyl_review(root, reviewed_at=before_run(), bind=True)
        )
        self.assert_hard_code(code, report, "YMYL_REVIEW_TIME_PRECEDES_RUN")

    def test_mdx_esm_hidden_by_leading_format_character_is_active_content(self) -> None:
        def builder(root: Path) -> None:
            build_content_ready(root)
            draft = (root / "drafts/final.md").read_text(encoding="utf-8")
            package_as_mdx(root, "\u200bimport'x'\n\n" + draft)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "PUBLISH_ACTIVE_CONTENT")

    def test_markdown_uri_is_canonicalized_before_scheme_validation(self) -> None:
        def builder(root: Path) -> None:
            build_publish_package(root)
            article_path = root / "publish/article.md"
            article = article_path.read_text(encoding="utf-8")
            article += "\n[Unsafe after entity decoding](javascript&#x3A;alert&#40;1&#41;)\n"
            write_text(article_path, article)
            write_text(root / "drafts/final.md", article)
            rehash_publish(root)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "UNSAFE_LINK_SCHEME")

    def test_punctuation_only_final_draft_is_not_content_ready(self) -> None:
        def builder(root: Path) -> None:
            build_content_ready(root)
            write_text(root / "drafts/final.md", "!!! --- ...\n")

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "FINAL_DRAFT_NOT_SUBSTANTIVE")

    def test_punctuation_only_content_artifacts_are_not_content_ready(self) -> None:
        artifact_paths = (
            "opportunity.md",
            "brief.md",
            "outline.md",
            "reviews/editorial.md",
        )
        for relative in artifact_paths:
            with self.subTest(path=relative):
                def builder(root: Path, relative: str = relative) -> None:
                    build_content_ready(root)
                    write_text(root / relative, "!!! --- ...\n")

                code, report = self.run_fixture(builder)
                self.assert_hard_code(code, report, "CONTENT_ARTIFACT_NOT_SUBSTANTIVE")

    def test_folded_frontmatter_noindex_is_rejected(self) -> None:
        def builder(root: Path) -> None:
            build_publish_package(root)
            article = (root / "publish/article.md").read_text(encoding="utf-8")
            article = "---\nseo:\n  robots: >\n    noindex,\n    follow\n---\n\n" + article
            write_text(root / "publish/article.md", article)
            write_text(root / "drafts/final.md", article)
            rehash_publish(root)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "PUBLISH_INDEXABILITY_CONFLICT")

    def test_flow_style_nested_frontmatter_noindex_is_rejected(self) -> None:
        def builder(root: Path) -> None:
            build_publish_package(root)
            article = (root / "publish/article.md").read_text(encoding="utf-8")
            article = "---\nseo: {robots: [noindex, follow]}\n---\n\n" + article
            write_text(root / "publish/article.md", article)
            write_text(root / "drafts/final.md", article)
            rehash_publish(root)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "PUBLISH_INDEXABILITY_CONFLICT")

    def test_verification_approval_requires_artifact_hashes(self) -> None:
        def builder(root: Path) -> None:
            build_content_ready(root)
            path = root / "reviews/verification.json"
            review = json.loads(path.read_text(encoding="utf-8"))
            review.pop("artifact_hashes")
            write_json(path, review)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "VERIFICATION_BINDING_MISSING")

    def test_verification_approval_cannot_predate_run(self) -> None:
        def builder(root: Path) -> None:
            build_content_ready(root)
            review = bound_review(root, "verifier-pass", before_run())
            review["independence_degraded"] = False
            write_json(root / "reviews/verification.json", review)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "VERIFICATION_TIME_PRECEDES_RUN")

    def test_editorial_approval_requires_artifact_hashes(self) -> None:
        def builder(root: Path) -> None:
            manifest = build_content_ready(root)
            write_json(
                root / "reviews/editorial.json",
                {
                    "status": "passed",
                    "reviewer": "editor-pass",
                    "reviewed_at": NOW,
                    "run_id": manifest["run_id"],
                    "artifact_hashes": {},
                },
            )

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "EDITORIAL_REVIEW_BINDING_MISSING")

    def test_editorial_approval_cannot_predate_run(self) -> None:
        def builder(root: Path) -> None:
            build_content_ready(root)
            write_json(root / "reviews/editorial.json", bound_review(root, "editor-pass", before_run()))

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "EDITORIAL_REVIEW_TIME_PRECEDES_RUN")

    def test_technical_approval_requires_artifact_hashes(self) -> None:
        def builder(root: Path) -> None:
            build_publish_package(root)
            path = root / "reviews/technical.json"
            review = json.loads(path.read_text(encoding="utf-8"))
            review.pop("artifact_hashes")
            write_json(path, review)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "TECHNICAL_REVIEW_BINDING_MISSING")

    def test_publish_package_rejects_unknown_or_empty_destination_format(self) -> None:
        for invalid_format in (None, "", "pdf"):
            with self.subTest(format=invalid_format):
                def builder(root: Path, invalid_format: Any = invalid_format) -> None:
                    manifest = build_publish_package(root)
                    manifest["destination"]["format"] = invalid_format
                    write_json(root / "manifest.json", manifest)
                    rehash_publish(root, sync_destination=True)

                code, report = self.run_fixture(builder)
                self.assert_hard_code(code, report, "MANIFEST_DESTINATION_INVALID")

    def test_technical_approval_cannot_predate_run(self) -> None:
        def builder(root: Path) -> None:
            build_publish_package(root)
            technical_path = root / "reviews/technical.json"
            technical = json.loads(technical_path.read_text(encoding="utf-8"))
            technical.update(bound_review(root, "technical-reviewer", before_run(), technical=True))
            write_json(technical_path, technical)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "TECHNICAL_REVIEW_TIME_PRECEDES_RUN")

    def test_deleted_user_export_invalidates_measured_capability(self) -> None:
        def builder(root: Path) -> None:
            build_measured(root)
            (root / "measurement/evidence/gsc-snapshot.csv").unlink()

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "CAPABILITY_EXPORT_MISSING")

    def test_measurement_windows_must_be_semantically_comparable(self) -> None:
        def builder(root: Path) -> None:
            build_measured(root)
            add_structured_measurement_contract(
                root,
                snapshot_start="2026-08-22",
                snapshot_end="2026-08-28",
            )

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "MEASUREMENT_WINDOW_NOT_COMPARABLE")

    def test_same_metric_name_cannot_hide_descriptor_mismatch(self) -> None:
        def builder(root: Path) -> None:
            build_measured(root)
            add_structured_measurement_contract(
                root,
                snapshot_start="2026-08-01",
                snapshot_end="2026-08-28",
                snapshot_unit="percent",
            )

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "MEASUREMENT_METRIC_DESCRIPTOR_MISMATCH")

    def test_optional_publish_article_symlink_is_rejected_at_content_ready(self) -> None:
        def builder(root: Path) -> None:
            build_content_ready(root)
            write_text(root / "publish/article-target.md", "# Optional package\n\nSafe-looking content.\n")
            (root / "publish/article.md").symlink_to("article-target.md")

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "PUBLISH_ARTICLE_SYMLINK")

    def test_optional_publish_manifest_symlink_is_rejected_at_content_ready(self) -> None:
        def builder(root: Path) -> None:
            build_content_ready(root)
            write_json(root / "publish/manifest-target.json", {"files": []})
            (root / "publish/publish-manifest.json").symlink_to("manifest-target.json")

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "PUBLISH_MANIFEST_SYMLINK")

    def test_one_byte_content_change_invalidates_bound_reviews(self) -> None:
        def builder(root: Path) -> None:
            build_content_ready(root)
            draft = root / "drafts/final.md"
            draft.write_bytes(draft.read_bytes() + b"\n")

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "VERIFICATION_BINDING_MISSING")
        self.assert_hard_code(code, report, "EDITORIAL_REVIEW_BINDING_MISSING")

    def test_review_copied_from_another_run_is_rejected(self) -> None:
        def builder(root: Path) -> None:
            build_content_ready(root)
            path = root / "reviews/verification.json"
            review = json.loads(path.read_text(encoding="utf-8"))
            review["run_id"] = "another-run-0001"
            write_json(path, review)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "VERIFICATION_BINDING_MISSING")

    def test_package_rehash_cannot_silently_reuse_technical_approval(self) -> None:
        def builder(root: Path) -> None:
            build_publish_package(root)
            metadata_path = root / "publish/metadata.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["description"] = "Changed after the technical approval was recorded."
            write_json(metadata_path, metadata)
            package_path = root / "publish/publish-manifest.json"
            package = json.loads(package_path.read_text(encoding="utf-8"))
            for record in package["files"]:
                record["sha256"] = sha256_file(root / record["path"])
            write_json(package_path, package)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "TECHNICAL_REVIEW_BINDING_MISSING")

    def test_passed_review_cannot_retain_unresolved_p1(self) -> None:
        def builder(root: Path) -> None:
            build_content_ready(root)
            path = root / "reviews/verification.json"
            review = json.loads(path.read_text(encoding="utf-8"))
            review["findings"] = [{"severity": "P1", "message": "Material claim remains unsupported."}]
            write_json(path, review)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "VERIFICATION_UNRESOLVED_FINDINGS")

    def test_qualified_acceptance_cannot_waive_p0(self) -> None:
        def builder(root: Path) -> None:
            build_content_ready(root)
            path = root / "reviews/verification.json"
            review = json.loads(path.read_text(encoding="utf-8"))
            review["findings"] = [
                {
                    "severity": "P0",
                    "message": "A truth or safety defect remains.",
                    "resolution": "accepted-by-qualified-reviewer",
                }
            ]
            write_json(path, review)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "VERIFICATION_UNRESOLVED_FINDINGS")

    def test_measurement_evidence_checksum_is_immutable(self) -> None:
        def builder(root: Path) -> None:
            build_measured(root)
            path = root / "measurement/evidence/gsc-baseline.csv"
            path.write_bytes(path.read_bytes() + b"tampered\n")

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "MEASUREMENT_BASELINE_EVIDENCE_FILE_INVALID")

    def test_measurement_evidence_symlink_is_rejected(self) -> None:
        def builder(root: Path) -> None:
            build_measured(root)
            path = root / "measurement/evidence/gsc-baseline.csv"
            target = path.with_name("gsc-baseline-target.csv")
            path.rename(target)
            path.symlink_to(target.name)
            baseline_path = root / "measurement/baseline.json"
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            baseline["source_evidence"][0]["sha256"] = sha256_file(target)
            write_json(baseline_path, baseline)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "MEASUREMENT_BASELINE_EVIDENCE_FILE_INVALID")

    def test_metric_filter_change_is_not_comparable(self) -> None:
        def builder(root: Path) -> None:
            build_measured(root)
            snapshot_path = root / "measurement/snapshots/2026-08-29.json"
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            snapshot["metrics"]["clicks"]["filters"]["search_type"] = "image"
            write_json(snapshot_path, snapshot)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "MEASUREMENT_METRIC_DESCRIPTOR_MISMATCH")

    def test_needs_expert_review_preserves_review_chronology(self) -> None:
        def builder(root: Path) -> None:
            manifest = build_content_ready(root)
            manifest["risk"] = {"ymyl": True, "jurisdiction": "US"}
            manifest["actual_status"] = "needs-expert-review"
            manifest["requested_status"] = "needs-expert-review"
            manifest["updated_at"] = after_run(4)
            write_json(root / "manifest.json", manifest)
            verification_path = root / "reviews/verification.json"
            verification = json.loads(verification_path.read_text(encoding="utf-8"))
            verification["reviewed_at"] = after_run(2)
            write_json(verification_path, verification)
            editorial_path = root / "reviews/editorial.json"
            editorial = json.loads(editorial_path.read_text(encoding="utf-8"))
            editorial["reviewed_at"] = after_run(1)
            write_json(editorial_path, editorial)
            write_json(
                root / "reviews/ymyl.json",
                {
                    "contract_version": "review-binding-v1",
                    "run_id": manifest["run_id"],
                    "review_type": "ymyl",
                    "review_required": True,
                    "status": "pending",
                    "requested_at": after_run(3),
                    "artifact_hashes": content_artifact_hashes(root),
                    "scope": "Material factual claims and reader actions",
                    "jurisdiction": "US",
                    "claims_requiring_review": ["C1"],
                    "findings": [],
                },
            )

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "EVENT_TIMELINE_INVALID")

    def test_pending_ymyl_scope_binds_to_material_claim_ids(self) -> None:
        def build_pending(root: Path, claim_ids: list[str], jurisdiction: str = "US") -> None:
            manifest = build_content_ready(root)
            manifest["risk"] = {"ymyl": True, "jurisdiction": "US"}
            manifest["actual_status"] = "needs-expert-review"
            manifest["requested_status"] = "needs-expert-review"
            write_json(root / "manifest.json", manifest)
            sync_intake_authorization(root, manifest)
            sync_handoff_status(root, manifest)
            write_json(
                root / "reviews/ymyl.json",
                {
                    "contract_version": "review-binding-v1",
                    "run_id": manifest["run_id"],
                    "review_type": "ymyl",
                    "review_required": True,
                    "status": "pending",
                    "requested_at": NOW,
                    "artifact_hashes": content_artifact_hashes(root),
                    "scope": "Material factual claims and reader actions",
                    "jurisdiction": jurisdiction,
                    "claims_requiring_review": claim_ids,
                    "findings": [],
                },
            )

        code, report = self.run_fixture(lambda root: build_pending(root, ["DOES-NOT-EXIST"]))
        self.assert_hard_code(code, report, "YMYL_REVIEW_SCOPE_UNKNOWN")
        self.assertIn(
            "YMYL_REVIEW_SCOPE_INCOMPLETE",
            {item.get("code") for item in report.get("findings", [])},
            report,
        )

        code, report = self.run_fixture(lambda root: build_pending(root, ["C1"]))
        self.assertEqual(code, 0, report)

        code, report = self.run_fixture(lambda root: build_pending(root, ["C1"], "RU"))
        self.assert_hard_code(code, report, "YMYL_PENDING_JURISDICTION_MISMATCH")

    def test_measurement_evidence_cannot_predate_its_window_close(self) -> None:
        def builder(root: Path) -> None:
            build_measured(root)
            snapshot_path = root / "measurement/snapshots/2026-08-29.json"
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            snapshot["source_evidence"][0]["extracted_at"] = "2000-01-01T00:00:00Z"
            write_json(snapshot_path, snapshot)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "MEASUREMENT_SNAPSHOT_EVIDENCE_BEFORE_WINDOW_CLOSE")

    def test_metric_units_must_use_canonical_semantics(self) -> None:
        def builder(root: Path) -> None:
            build_measured(root)
            for path in (
                root / "measurement/baseline.json",
                root / "measurement/snapshots/2026-08-29.json",
            ):
                record = json.loads(path.read_text(encoding="utf-8"))
                record["metrics"]["clicks"]["unit"] = "COUNT"
                write_json(path, record)
            snapshot_path = root / "measurement/snapshots/2026-08-29.json"
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            snapshot["metrics"]["clicks"]["value"] = -0.5
            write_json(snapshot_path, snapshot)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "MEASUREMENT_SNAPSHOT_METRIC_DESCRIPTOR_INVALID")

    def test_source_system_must_match_schema_canonical_value(self) -> None:
        def builder(root: Path) -> None:
            build_measured(root)
            for path in (
                root / "measurement/baseline.json",
                root / "measurement/snapshots/2026-08-29.json",
            ):
                record = json.loads(path.read_text(encoding="utf-8"))
                record["source_evidence"][0]["source_system"] = " GSC "
                for metric in record["metrics"].values():
                    metric["source_system"] = " GSC "
                write_json(path, record)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "MEASUREMENT_BASELINE_SOURCE_SYSTEM_INVALID")

    def test_measurement_decision_log_is_language_neutral(self) -> None:
        def builder(root: Path) -> None:
            build_measured(root)
            write_text(
                root / "measurement/decisions.md",
                "# Итог измерения\n\nОставить статью без изменений и продолжить сбор данных. "
                "Выборка пока мала, сезонность не исключена, поэтому причинный вывод делать нельзя.\n",
            )

        code, report = self.run_fixture(builder)
        self.assertEqual(code, 0, report)

    def test_verification_cannot_predate_research_evidence(self) -> None:
        def builder(root: Path) -> None:
            manifest = build_content_ready(root)
            manifest["updated_at"] = after_run(3)
            write_json(root / "manifest.json", manifest)
            source_path = root / "research/sources.jsonl"
            source = json.loads(source_path.read_text(encoding="utf-8"))
            source["retrieved_at"] = after_run(2)
            source_path.write_text(json.dumps(source) + "\n", encoding="utf-8")
            verification_path = root / "reviews/verification.json"
            verification = json.loads(verification_path.read_text(encoding="utf-8"))
            verification["artifact_hashes"] = content_artifact_hashes(root)
            verification["reviewed_at"] = after_run(1)
            write_json(verification_path, verification)
            editorial_path = root / "reviews/editorial.json"
            editorial = json.loads(editorial_path.read_text(encoding="utf-8"))
            editorial["artifact_hashes"] = content_artifact_hashes(root)
            editorial["reviewed_at"] = after_run(3)
            write_json(editorial_path, editorial)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "EVENT_TIMELINE_INVALID")

    def test_measurement_evidence_path_rejects_control_characters(self) -> None:
        def builder(root: Path) -> None:
            build_measured(root)
            original = root / "measurement/evidence/gsc-baseline.csv"
            renamed = root / "measurement/evidence/gsc-line\nbreak.csv"
            original.rename(renamed)
            baseline_path = root / "measurement/baseline.json"
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            baseline["source_evidence"][0]["path"] = "measurement/evidence/gsc-line\nbreak.csv"
            baseline["source_evidence"][0]["sha256"] = sha256_file(renamed)
            write_json(baseline_path, baseline)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "MEASUREMENT_BASELINE_EVIDENCE_FILE_INVALID")

    def test_bidi_spoofed_provider_is_rejected_everywhere(self) -> None:
        def builder(root: Path) -> None:
            build_measured(root)
            spoofed = "google\u202e-export"
            capability_path = root / "capabilities.json"
            capabilities = json.loads(capability_path.read_text(encoding="utf-8"))
            capabilities["capabilities"]["gsc"]["selected_provider"] = spoofed
            capabilities["capabilities"]["gsc"]["candidate"]["provider"] = spoofed
            write_json(capability_path, capabilities)
            for path in (
                root / "measurement/baseline.json",
                root / "measurement/snapshots/2026-08-29.json",
            ):
                record = json.loads(path.read_text(encoding="utf-8"))
                record["source_evidence"][0]["provider"] = spoofed
                write_json(path, record)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "CAPABILITY_UNICODE_CONTROL_INVALID")

    def test_measurement_grain_requires_canonical_machine_token(self) -> None:
        def builder(root: Path) -> None:
            build_measured(root)
            snapshot_path = root / "measurement/snapshots/2026-08-29.json"
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            snapshot["comparison_window"]["grain"] = "Day"
            write_json(snapshot_path, snapshot)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "MEASUREMENT_SNAPSHOT_WINDOW_INVALID")

    def test_unreadable_user_export_invalidates_capability(self) -> None:
        with tempfile.TemporaryDirectory(prefix="best-seo-unreadable-export-") as temporary:
            root = Path(temporary)
            build_measured(root)
            locked = root / "locked-capability.csv"
            locked.write_text("query,clicks\nexample,1\n", encoding="utf-8")
            capability_path = root / "capabilities.json"
            capabilities = json.loads(capability_path.read_text(encoding="utf-8"))
            capabilities["capabilities"]["gsc"]["candidate"]["probe"]["references"] = [str(locked.resolve())]
            write_json(capability_path, capabilities)
            locked.chmod(0)
            try:
                code, report = validate(root)
            finally:
                locked.chmod(0o600)
            self.assert_hard_code(code, report, "CAPABILITY_EXPORT_MISSING")

    def test_relative_export_is_bound_to_preflight_cwd(self) -> None:
        with tempfile.TemporaryDirectory(prefix="best-seo-canonical-export-") as temporary:
            base = Path(temporary)
            observed_cwd = base / "observed"
            run_root = base / "run"
            observed_cwd.mkdir()
            run_root.mkdir()
            observed = observed_cwd / "same.csv"
            observed.write_text("query,clicks\nobserved,1\n", encoding="utf-8")
            preflight = subprocess.run(
                [
                    sys.executable,
                    str(CAPABILITY_PREFLIGHT),
                    "--checked-at",
                    NOW,
                    "--file",
                    "gsc=same.csv",
                    "--provider",
                    "gsc=google-search-console-export",
                ],
                cwd=observed_cwd,
                check=True,
                capture_output=True,
                text=True,
            )
            capabilities = json.loads(preflight.stdout)
            reference = capabilities["capabilities"]["gsc"]["candidate"]["probe"]["references"][0]
            self.assertEqual(reference, str(observed.resolve()))
            build_measured(run_root)
            write_json(run_root / "capabilities.json", capabilities)
            (run_root / "same.csv").write_text("query,clicks\nunrelated,99\n", encoding="utf-8")
            code, report = validate(run_root)
            self.assertEqual(code, 0, report)
            observed.unlink()
            code, report = validate(run_root)
            self.assert_hard_code(code, report, "CAPABILITY_EXPORT_MISSING")

    def test_empty_export_is_not_reported_as_user_export(self) -> None:
        with tempfile.TemporaryDirectory(prefix="best-seo-empty-export-") as temporary:
            empty = Path(temporary) / "empty.csv"
            empty.touch()
            result = subprocess.run(
                [
                    sys.executable,
                    str(CAPABILITY_PREFLIGHT),
                    "--checked-at",
                    NOW,
                    "--file",
                    f"gsc={empty}",
                    "--provider",
                    "gsc=google-search-console-export",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            report = json.loads(result.stdout)
            self.assertEqual(report["capabilities"]["gsc"]["status"], "UNAVAILABLE")

    def test_preflight_rejects_unusable_labels_and_path_errors_as_json(self) -> None:
        cases = (
            ["--available", "gsc=-", "--provider", "gsc=-", "--cost", "gsc=free"],
            ["--file", "gsc=~definitely_no_such_user_98765/export.csv", "--provider", "gsc=provider"],
            ["--checked-at", "0001-01-01T00:00:00+14:00"],
            ["--checked-at", "2026-08-29\n12:00:00Z"],
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    [sys.executable, str(CAPABILITY_PREFLIGHT), *arguments],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 2, result.stderr)
                payload = json.loads(result.stderr)
                self.assertEqual(payload["error"]["code"], "INVALID_ARGUMENTS")
                self.assertNotIn("Traceback", result.stderr)

    def test_manifest_timestamps_require_strict_rfc3339_separator(self) -> None:
        def builder(root: Path) -> None:
            manifest = build_content_ready(root)
            manifest["created_at"] = manifest["created_at"].replace("T", "\n")
            manifest["updated_at"] = manifest["updated_at"].replace("T", "\n")
            write_json(root / "manifest.json", manifest)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "MANIFEST_TIME_INVALID")

    def test_pending_ymyl_review_rejects_malformed_findings(self) -> None:
        def builder(root: Path) -> None:
            manifest = build_content_ready(root)
            manifest["risk"] = {"ymyl": True, "jurisdiction": "US"}
            manifest["actual_status"] = "needs-expert-review"
            manifest["requested_status"] = "needs-expert-review"
            manifest["updated_at"] = after_run(2)
            write_json(root / "manifest.json", manifest)
            write_json(
                root / "reviews/ymyl.json",
                {
                    "contract_version": "review-binding-v1",
                    "run_id": manifest["run_id"],
                    "review_type": "ymyl",
                    "review_required": True,
                    "status": "pending",
                    "requested_at": after_run(1),
                    "artifact_hashes": content_artifact_hashes(root),
                    "scope": "Material factual claims and reader actions",
                    "jurisdiction": "US",
                    "claims_requiring_review": ["C1"],
                    "findings": [{}],
                },
            )

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "YMYL_REVIEW_FINDINGS_INVALID")

    def test_nonfinite_nested_measurement_json_is_rejected(self) -> None:
        def builder(root: Path) -> None:
            build_measured(root)
            baseline_path = root / "measurement/baseline.json"
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            baseline["metrics"]["clicks"]["filters"]["threshold"] = float("nan")
            baseline_path.write_text(json.dumps(baseline, allow_nan=True) + "\n", encoding="utf-8")

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "MEASUREMENT_BASELINE_INVALID")

    def test_measurement_schema_rejects_immediate_and_nested_parent_paths(self) -> None:
        schema = json.loads(
            (EVALS_ROOT.parent / "schemas/measurement-record.schema.json").read_text(encoding="utf-8")
        )
        pattern = schema["$defs"]["evidence"]["properties"]["path"]["pattern"]
        self.assertIsNone(re.fullmatch(pattern, "measurement/evidence/../outside.csv"))
        self.assertIsNone(re.fullmatch(pattern, "measurement/evidence/nested/../outside.csv"))
        self.assertIsNotNone(re.fullmatch(pattern, "measurement/evidence/nested/export.csv"))

    def test_stale_capability_preflight_cannot_support_release_statuses(self) -> None:
        for builder in (build_content_ready, build_measured):
            with self.subTest(builder=builder.__name__):
                def stale_fixture(root: Path, builder: Callable[[Path], Any] = builder) -> None:
                    builder(root)
                    capability_path = root / "capabilities.json"
                    capabilities = json.loads(capability_path.read_text(encoding="utf-8"))
                    capabilities["checked_at"] = "2000-01-01T00:00:00Z"
                    write_json(capability_path, capabilities)

                code, report = self.run_fixture(stale_fixture)
                self.assert_hard_code(code, report, "CAPABILITY_CHECK_TIME_STALE")

    def test_writer_cannot_self_approve_editorial_review(self) -> None:
        def builder(root: Path) -> None:
            manifest = build_content_ready(root)
            manifest["roles"]["editor"] = manifest["roles"]["writer"]
            write_json(root / "manifest.json", manifest)
            editorial_path = root / "reviews/editorial.json"
            editorial = json.loads(editorial_path.read_text(encoding="utf-8"))
            editorial["reviewer"] = manifest["roles"]["writer"]
            write_json(editorial_path, editorial)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "EDITORIAL_INDEPENDENCE_CONFLICT")

    @unittest.skipIf(Draft202012Validator is None, "jsonschema is optional for schema-only regressions")
    def test_capability_schema_rejects_forged_user_export(self) -> None:
        preflight = subprocess.run(
            [sys.executable, str(CAPABILITY_PREFLIGHT), "--checked-at", NOW],
            check=True,
            capture_output=True,
            text=True,
        )
        report = json.loads(preflight.stdout)
        report["capabilities"]["gsc"] = {
            "status": "USER_EXPORT",
            "selected_provider": "google-search-console-export",
            "selected_by": "user-export",
            "candidate": {
                "provider": "google-search-console-export",
                "probe": {
                    "kind": "file",
                    "references": ["/definitely/missing.csv"],
                    "present": False,
                    "present_count": 0,
                    "required_count": 1,
                },
                "cost": {"kind": "free", "approval_required": False, "approved": False},
            },
            "reason_code": "USER_EXPORT_PRESENT",
            "absence_effect": "The forged export must not satisfy the schema.",
        }
        schema = json.loads(
            (EVALS_ROOT.parent / "schemas/capabilities.schema.json").read_text(encoding="utf-8")
        )
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        self.assertTrue(list(validator.iter_errors(report)))

    def test_reviewer_identity_aliases_do_not_bypass_independence(self) -> None:
        cases = (
            ("verifier", "reviews/verification.json", "VERIFICATION_INDEPENDENCE_CONFLICT"),
            ("editor", "reviews/editorial.json", "EDITORIAL_INDEPENDENCE_CONFLICT"),
        )
        for role, review_relative, expected in cases:
            with self.subTest(role=role):
                def builder(root: Path, role: str = role, review_relative: str = review_relative) -> None:
                    manifest = build_content_ready(root)
                    manifest["roles"][role] = " WRITER-PASS "
                    write_json(root / "manifest.json", manifest)
                    review_path = root / review_relative
                    review = json.loads(review_path.read_text(encoding="utf-8"))
                    review["reviewer"] = " WRITER-PASS "
                    write_json(review_path, review)

                code, report = self.run_fixture(builder)
                self.assert_hard_code(code, report, expected)

    def test_approved_ymyl_review_must_follow_editorial_review(self) -> None:
        def builder(root: Path) -> None:
            approved_ymyl_review(root)
            manifest_path = root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["updated_at"] = after_run(4)
            write_json(manifest_path, manifest)
            verification_path = root / "reviews/verification.json"
            verification = json.loads(verification_path.read_text(encoding="utf-8"))
            verification["reviewed_at"] = after_run(1)
            write_json(verification_path, verification)
            ymyl_path = root / "reviews/ymyl.json"
            ymyl = json.loads(ymyl_path.read_text(encoding="utf-8"))
            ymyl["reviewed_at"] = after_run(2)
            write_json(ymyl_path, ymyl)
            editorial_path = root / "reviews/editorial.json"
            editorial = json.loads(editorial_path.read_text(encoding="utf-8"))
            editorial["reviewed_at"] = after_run(3)
            write_json(editorial_path, editorial)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "EVENT_TIMELINE_INVALID")

    def test_approved_ymyl_review_sections_must_exist_in_visible_draft(self) -> None:
        def builder(root: Path) -> None:
            approved_ymyl_review(root)
            ymyl_path = root / "reviews/ymyl.json"
            ymyl = json.loads(ymyl_path.read_text(encoding="utf-8"))
            ymyl["sections_reviewed"] = ["Invented hidden section"]
            write_json(ymyl_path, ymyl)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "YMYL_REVIEW_SCOPE_UNKNOWN")

    def test_approved_ymyl_review_must_cover_every_material_claim_id(self) -> None:
        def builder(root: Path) -> None:
            approved_ymyl_review(root)
            ymyl_path = root / "reviews/ymyl.json"
            ymyl = json.loads(ymyl_path.read_text(encoding="utf-8"))
            ymyl["claims_reviewed"] = ["UNKNOWN-CLAIM"]
            write_json(ymyl_path, ymyl)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "YMYL_REVIEW_CLAIM_SCOPE_INVALID")

    def test_measurement_baseline_cannot_predate_run(self) -> None:
        def builder(root: Path) -> None:
            build_measured(root)
            baseline_path = root / "measurement/baseline.json"
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            baseline["comparison_window"]["start"] = "1999-12-04"
            baseline["comparison_window"]["end_exclusive"] = "2000-01-01"
            baseline["measured_at"] = "2000-01-01T00:00:00Z"
            baseline["source_evidence"][0]["extracted_at"] = "2000-01-01T00:00:00Z"
            write_json(baseline_path, baseline)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "MEASUREMENT_BASELINE_TIME_PRECEDES_RUN")

    def test_run_id_rejects_line_injection_across_bound_records(self) -> None:
        def builder(root: Path) -> None:
            build_content_ready(root)
            poisoned = "run-good\nspoof"
            for relative in (
                "manifest.json",
                "intake.json",
                "reviews/verification.json",
                "reviews/editorial.json",
            ):
                path = root / relative
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["run_id"] = poisoned
                write_json(path, payload)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "MANIFEST_RUN_ID_INVALID")

    def test_role_and_reviewer_identities_must_be_single_line(self) -> None:
        def builder(root: Path) -> None:
            manifest = build_content_ready(root)
            manifest["roles"]["verifier"] = "verifier\npass"
            write_json(root / "manifest.json", manifest)
            review_path = root / "reviews/verification.json"
            review = json.loads(review_path.read_text(encoding="utf-8"))
            review["reviewer"] = "verifier\npass"
            write_json(review_path, review)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "ROLE_ASSIGNMENTS_INVALID")

    def test_provider_labels_reject_backslash_ambiguity(self) -> None:
        def builder(root: Path) -> None:
            build_measured(root)
            ambiguous = "google\\export"
            capability_path = root / "capabilities.json"
            capabilities = json.loads(capability_path.read_text(encoding="utf-8"))
            capabilities["capabilities"]["gsc"]["selected_provider"] = ambiguous
            capabilities["capabilities"]["gsc"]["candidate"]["provider"] = ambiguous
            write_json(capability_path, capabilities)
            for path in (
                root / "measurement/baseline.json",
                root / "measurement/snapshots/2026-08-29.json",
            ):
                record = json.loads(path.read_text(encoding="utf-8"))
                record["source_evidence"][0]["provider"] = ambiguous
                write_json(path, record)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "CAPABILITY_PROVIDER_MISSING")

    def test_capability_absence_effect_cannot_be_weakened(self) -> None:
        def builder(root: Path) -> None:
            build_content_ready(root)
            path = root / "capabilities.json"
            report = json.loads(path.read_text(encoding="utf-8"))
            old = report["capabilities"]["gsc"]["absence_effect"]
            weakened = "No limitations apply to this missing analytics source."
            report["capabilities"]["gsc"]["absence_effect"] = weakened
            report["limitations"] = [item.replace(old, weakened) for item in report["limitations"]]
            write_json(path, report)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "CAPABILITY_ABSENCE_EFFECT_INVALID")

    def test_builtin_fallback_must_exist_for_capability(self) -> None:
        def builder(root: Path) -> None:
            build_content_ready(root)
            path = root / "capabilities.json"
            report = json.loads(path.read_text(encoding="utf-8"))
            state = report["capabilities"]["gsc"]
            state["status"] = "FALLBACK"
            state["selected_provider"] = "invented-gsc-fallback"
            state["selected_by"] = "builtin-fallback"
            state["reason_code"] = "FREE_FALLBACK_SELECTED"
            write_json(path, report)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "CAPABILITY_BUILTIN_FALLBACK_INVALID")

    def test_duplicate_capability_file_references_are_rejected(self) -> None:
        def builder(root: Path) -> None:
            build_measured(root)
            path = root / "capabilities.json"
            report = json.loads(path.read_text(encoding="utf-8"))
            probe = report["capabilities"]["gsc"]["candidate"]["probe"]
            probe["references"] = [probe["references"][0], probe["references"][0]]
            probe["present_count"] = 2
            probe["required_count"] = 2
            write_json(path, report)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "CAPABILITY_PROBE_REFERENCES_INVALID")

    def test_canonicalized_export_path_rejects_bidi_cwd(self) -> None:
        with tempfile.TemporaryDirectory(prefix="best-seo-bidi-cwd-") as temporary:
            cwd = Path(temporary) / "unsafe\u202ecwd"
            cwd.mkdir()
            (cwd / "export.csv").write_text("query,clicks\nexample,1\n", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(CAPABILITY_PREFLIGHT),
                    "--file",
                    "gsc=export.csv",
                    "--provider",
                    "gsc=provider",
                ],
                cwd=cwd,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(json.loads(result.stderr)["error"]["code"], "INVALID_ARGUMENTS")

    def test_preflight_rejects_default_ignorables_and_unicode_path_aliases(self) -> None:
        with tempfile.TemporaryDirectory(prefix="best-seo-path-alias-") as temporary:
            root = Path(temporary)
            unsafe = root / "export\ufe0f.csv"
            unsafe.write_text("query,clicks\nexample,1\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(CAPABILITY_PREFLIGHT), "--file", f"gsc={unsafe}"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 2, result.stderr)

            nfc = root / "café.csv"
            nfd = root / "café.csv"
            nfc.write_text("query,clicks\nexample,1\n", encoding="utf-8")
            if not nfd.exists():
                nfd.write_text("query,clicks\nexample,1\n", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(CAPABILITY_PREFLIGHT),
                    "--file",
                    f"gsc={nfc}",
                    "--file",
                    f"gsc={nfd}",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 2, result.stderr)

    def test_publish_manifest_rejects_unicode_normalization_path_aliases(self) -> None:
        def builder(root: Path) -> None:
            build_publish_package(root)
            nfc_relative = "publish/café.txt"
            nfd_relative = "publish/café.txt"
            nfc_path = root / nfc_relative
            nfd_path = root / nfd_relative
            nfc_path.write_text("same content\n", encoding="utf-8")
            if not nfd_path.exists():
                nfd_path.write_text("same content\n", encoding="utf-8")
            publish_path = root / "publish/publish-manifest.json"
            publish = json.loads(publish_path.read_text(encoding="utf-8"))
            digest = sha256_file(nfc_path)
            publish["files"].extend(
                [
                    {"path": nfc_relative, "sha256": digest},
                    {"path": nfd_relative, "sha256": digest},
                ]
            )
            write_json(publish_path, publish)
            technical_path = root / "reviews/technical.json"
            technical = json.loads(technical_path.read_text(encoding="utf-8"))
            technical["artifact_hashes"]["publish/publish-manifest.json"] = sha256_file(publish_path)
            write_json(technical_path, technical)

        code, report = self.run_fixture(builder)
        hard_codes = {
            item.get("code")
            for item in report.get("findings", [])
            if isinstance(item, dict) and item.get("severity") in {"P0", "P1"}
        }
        self.assertEqual(code, 1, report)
        self.assertTrue({"PUBLISH_FILE_PATH_INVALID", "PUBLISH_FILE_DUPLICATE", "PUBLISH_FILE_DUPLICATE_TARGET"} & hard_codes, report)

    @unittest.skipIf(Draft202012Validator is None, "jsonschema is optional for schema-only regressions")
    def test_schema_machine_tokens_reject_terminal_line_controls(self) -> None:
        schema = json.loads(
            (EVALS_ROOT.parent / "schemas/measurement-record.schema.json").read_text(encoding="utf-8")
        )
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        with tempfile.TemporaryDirectory(prefix="best-seo-schema-measurement-") as temporary:
            root = Path(temporary)
            build_measured(root)
            record = json.loads((root / "measurement/baseline.json").read_text(encoding="utf-8"))
            for field, value in (
                ("grain", "day\n"),
                ("evidence_id", "gsc-baseline\n"),
                ("unit", "count\n"),
            ):
                with self.subTest(field=field):
                    mutated = json.loads(json.dumps(record))
                    if field == "grain":
                        mutated["comparison_window"][field] = value
                    elif field == "evidence_id":
                        mutated["source_evidence"][0][field] = value
                    else:
                        mutated["metrics"]["clicks"][field] = value
                    self.assertTrue(list(validator.iter_errors(mutated)))

    def test_measurement_limitations_reject_line_controls_at_runtime(self) -> None:
        def builder(root: Path) -> None:
            build_measured(root)
            for path in (
                root / "measurement/baseline.json",
                root / "measurement/snapshots/2026-08-29.json",
            ):
                record = json.loads(path.read_text(encoding="utf-8"))
                record["data_limitations"] = ["Known\nlimitation"]
                write_json(path, record)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "MEASUREMENT_BASELINE_LIMITATIONS_INVALID")

    def test_bound_review_human_fields_reject_line_controls_at_runtime(self) -> None:
        def builder(root: Path) -> None:
            build_content_ready(root)
            review_path = root / "reviews/verification.json"
            review = json.loads(review_path.read_text(encoding="utf-8"))
            review["findings"] = [
                {"severity": "P2", "message": "Known\nissue", "resolution": "resolved"}
            ]
            write_json(review_path, review)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "VERIFICATION_UNICODE_CONTROL_INVALID")

    @unittest.skipIf(Draft202012Validator is None, "jsonschema is optional for schema-only regressions")
    def test_review_schema_requires_ymyl_qualification_and_technical_scope(self) -> None:
        schema = json.loads((EVALS_ROOT.parent / "schemas/review.schema.json").read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        hashes = {path: "0" * 64 for path in ("intake.json", "drafts/final.md", "claims.jsonl", "research/sources.jsonl")}
        approved = {
            "contract_version": "review-binding-v1",
            "run_id": "eval-run-0001",
            "review_type": "ymyl",
            "status": "approved",
            "reviewer": "x",
            "reviewed_at": NOW,
            "artifact_hashes": hashes,
            "findings": [],
        }
        pending = {
            "contract_version": "review-binding-v1",
            "run_id": "eval-run-0001",
            "review_type": "ymyl",
            "status": "pending",
            "requested_at": NOW,
            "artifact_hashes": hashes,
            "findings": [],
        }
        technical = {
            "contract_version": "review-binding-v1",
            "run_id": "eval-run-0001",
            "review_type": "technical",
            "status": "passed",
            "reviewer": "technical-reviewer",
            "reviewed_at": NOW,
            "artifact_hashes": {**hashes, "publish/publish-manifest.json": "0" * 64},
            "findings": [],
        }
        for record in (approved, pending, technical):
            with self.subTest(review_type=record["review_type"], status=record["status"]):
                self.assertTrue(list(validator.iter_errors(record)))

        technical_with_null_list = {
            **technical,
            "scope": "CMS-neutral portable package",
            "checks": [None],
        }
        technical_with_null_object = {
            **technical,
            "scope": "CMS-neutral portable package",
            "checks": {"h1": None},
        }
        for record in (technical_with_null_list, technical_with_null_object):
            self.assertTrue(list(validator.iter_errors(record)))

        approved_whitespace = {
            **approved,
            "reviewer": "   ",
            "review_required": True,
            "credentials": "        ",
            "scope": "            ",
            "jurisdiction": "  ",
            "sections_reviewed": ["   "],
        }
        technical_whitespace = {
            **technical,
            "scope": "            ",
            "checks": {"single_h1": {"status": "passed", "evidence": "            "}},
        }
        verification_whitespace = {
            **technical,
            "review_type": "verification",
            "artifact_hashes": hashes,
            "independence_degraded": False,
            "findings": [{"severity": "P2", "message": " ", "resolution": "resolved"}],
        }
        for record in (approved_whitespace, technical_whitespace, verification_whitespace):
            self.assertTrue(list(validator.iter_errors(record)), record)

    @unittest.skipIf(Draft202012Validator is None, "jsonschema is optional for schema-only regressions")
    def test_critical_schema_shapes_do_not_depend_on_optional_format_checkers(self) -> None:
        schemas = EVALS_ROOT.parent / "schemas"
        review_schema = json.loads((schemas / "review.schema.json").read_text(encoding="utf-8"))
        review = {
            "contract_version": "review-binding-v1",
            "run_id": "eval-run-0001",
            "review_type": "verification",
            "status": "passed",
            "reviewer": "verifier-pass",
            "reviewed_at": "not-a-time",
            "independence_degraded": False,
            "artifact_hashes": {
                "intake.json": "0" * 64,
                "drafts/final.md": "0" * 64 + "\n",
                "claims.jsonl": "0" * 64,
                "research/sources.jsonl": "0" * 64,
            },
            "findings": [],
        }
        self.assertTrue(list(Draft202012Validator(review_schema).iter_errors(review)))

        with tempfile.TemporaryDirectory(prefix="schema-shape-measurement-") as temporary:
            root = Path(temporary)
            build_measured(root)
            measurement = json.loads((root / "measurement/baseline.json").read_text(encoding="utf-8"))
            measurement["measured_at"] = "not-a-time"
            measurement["source_evidence"][0]["extracted_at"] = "not-a-time"
            measurement["page"] = "https://"
            measurement["metrics"]["clicks"]["domain"]["value"] = "https://"
            measurement["metrics"]["clicks"]["filters"]["page"] = "https://"
            measurement_schema = json.loads((schemas / "measurement-record.schema.json").read_text(encoding="utf-8"))
            self.assertTrue(list(Draft202012Validator(measurement_schema).iter_errors(measurement)))

        preflight = subprocess.run(
            [sys.executable, str(CAPABILITY_PREFLIGHT), "--checked-at", NOW],
            check=True,
            capture_output=True,
            text=True,
        )
        capabilities = json.loads(preflight.stdout)
        capabilities["checked_at"] = "not-a-time"
        capability_schema = json.loads((schemas / "capabilities.schema.json").read_text(encoding="utf-8"))
        self.assertTrue(list(Draft202012Validator(capability_schema).iter_errors(capabilities)))

    def test_url_binding_does_not_collapse_repeated_trailing_slashes(self) -> None:
        def builder(root: Path) -> None:
            build_measured(root)
            for path in (
                root / "measurement/baseline.json",
                root / "measurement/snapshots/2026-08-29.json",
            ):
                record = json.loads(path.read_text(encoding="utf-8"))
                record["page"] += "///"
                write_json(path, record)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "MEASUREMENT_BASELINE_PAGE_MISMATCH")

    def test_url_binding_does_not_apply_transitional_idna_folding(self) -> None:
        def builder(root: Path) -> None:
            build_measured(root)
            unicode_page = "https://faß.de/article"
            for path in (
                root / "measurement/baseline.json",
                root / "measurement/snapshots/2026-08-29.json",
            ):
                record = json.loads(path.read_text(encoding="utf-8"))
                record["page"] = unicode_page
                for metric in record["metrics"].values():
                    metric["domain"]["value"] = unicode_page
                    metric["filters"]["page"] = unicode_page
                write_json(path, record)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "MEASUREMENT_BASELINE_PAGE_MISMATCH")

    def test_measurement_metrics_must_bind_to_article_page(self) -> None:
        def builder(root: Path) -> None:
            build_measured(root)
            unrelated = "https://other.example/unrelated"
            for path in (
                root / "measurement/baseline.json",
                root / "measurement/snapshots/2026-08-29.json",
            ):
                record = json.loads(path.read_text(encoding="utf-8"))
                for metric in record["metrics"].values():
                    metric["domain"]["value"] = unrelated
                    metric["filters"]["page"] = unrelated
                write_json(path, record)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "MEASUREMENT_BASELINE_METRIC_PAGE_SCOPE_INVALID")

    def test_page_metric_rejects_conflicting_url_aliases_and_unknown_descriptor_keys(self) -> None:
        mutations = (
            ("filters", "landing_page"),
            ("filters", "page_url"),
            ("filters", "page_path"),
            ("filters", "url"),
            ("segments", "landing_page"),
            ("segments", "page_url"),
            ("domain", "url"),
        )
        for container, key in mutations:
            with self.subTest(container=container, key=key):
                def builder(root: Path, container: str = container, key: str = key) -> None:
                    build_measured(root)
                    for path in (
                        root / "measurement/baseline.json",
                        root / "measurement/snapshots/2026-08-29.json",
                    ):
                        record = json.loads(path.read_text(encoding="utf-8"))
                        for metric in record["metrics"].values():
                            metric[container][key] = "https://other.example/unrelated"
                        write_json(path, record)

                code, report = self.run_fixture(builder)
                self.assert_hard_code(code, report, "MEASUREMENT_BASELINE_METRIC_PAGE_SCOPE_INVALID")

    def test_page_metric_requires_canonical_page_filter(self) -> None:
        def builder(root: Path) -> None:
            build_measured(root)
            for path in (
                root / "measurement/baseline.json",
                root / "measurement/snapshots/2026-08-29.json",
            ):
                record = json.loads(path.read_text(encoding="utf-8"))
                for metric in record["metrics"].values():
                    metric["filters"].pop("page")
                write_json(path, record)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "MEASUREMENT_BASELINE_METRIC_PAGE_SCOPE_INVALID")

    def test_explicit_probe_cannot_claim_cost_none(self) -> None:
        def builder(root: Path) -> None:
            build_content_ready(root)
            preflight = subprocess.run(
                [
                    sys.executable,
                    str(CAPABILITY_PREFLIGHT),
                    "--checked-at",
                    NOW,
                    "--available",
                    "serp=unknown-cost-tool",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            report = json.loads(preflight.stdout)
            state = report["capabilities"]["serp"]
            state["status"] = "AVAILABLE"
            state["selected_provider"] = "unknown-cost-tool"
            state["selected_by"] = "explicit-flag"
            state["candidate"]["cost"] = {"kind": "none", "approval_required": False, "approved": False}
            state["reason_code"] = "EXPLICIT_CAPABILITY_AVAILABLE"
            write_json(root / "capabilities.json", report)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "CAPABILITY_COST_INVALID")

    def test_writer_alias_cannot_self_approve_ymyl(self) -> None:
        def builder(root: Path) -> None:
            approved_ymyl_review(root)
            manifest_path = root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["roles"]["expert_reviewer"] = " WRITER-PASS "
            write_json(manifest_path, manifest)
            review_path = root / "reviews/ymyl.json"
            review = json.loads(review_path.read_text(encoding="utf-8"))
            review["reviewer"] = " WRITER-PASS "
            write_json(review_path, review)

        code, report = self.run_fixture(builder)
        self.assert_hard_code(code, report, "YMYL_REVIEW_INDEPENDENCE_CONFLICT")

    def test_default_ignorables_cannot_spoof_actor_independence(self) -> None:
        for character in (
            "\u200d", "\ufe0f", "\u034f", "\u115f", "\u3164",
            "\u180b", "\u180c", "\u180d", "\u180f", "\u2065",
            "\ufff0", "\ufff8", "\U000e0000",
        ):
            with self.subTest(character=f"U+{ord(character):04X}"):
                def builder(root: Path, character: str = character) -> None:
                    manifest = build_content_ready(root)
                    spoofed = f"writer{character}-pass"
                    manifest["roles"]["editor"] = spoofed
                    write_json(root / "manifest.json", manifest)
                    review_path = root / "reviews/editorial.json"
                    review = json.loads(review_path.read_text(encoding="utf-8"))
                    review["reviewer"] = spoofed
                    write_json(review_path, review)

                code, report = self.run_fixture(builder)
                hard_codes = {
                    item.get("code")
                    for item in report.get("findings", [])
                    if isinstance(item, dict) and item.get("severity") in {"P0", "P1"}
                }
                self.assertEqual(code, 1, report)
                self.assertTrue(
                    {"MANIFEST_ROLE_INVALID", "EDITORIAL_INDEPENDENCE_CONFLICT"} & hard_codes,
                    report,
                )

    def test_default_ignorables_cannot_hide_draft_placeholders(self) -> None:
        for character in ("\u2065", "\u180b", "\ufff0", "\U000e0000"):
            with self.subTest(character=f"U+{ord(character):04X}"):
                def builder(root: Path, character: str = character) -> None:
                    build_content_ready(root)
                    draft_path = root / "drafts/final.md"
                    draft_path.write_text(
                        draft_path.read_text(encoding="utf-8")
                        + f"\nTO{character}DO: unresolved factual claim.\n",
                        encoding="utf-8",
                    )
                    hashes = content_artifact_hashes(root)
                    for relative in ("reviews/verification.json", "reviews/editorial.json"):
                        review_path = root / relative
                        review = json.loads(review_path.read_text(encoding="utf-8"))
                        review["artifact_hashes"] = hashes
                        write_json(review_path, review)

                code, report = self.run_fixture(builder)
                self.assert_hard_code(code, report, "FINAL_DRAFT_NOT_SUBSTANTIVE")

    def test_nfkc_compatibility_glyphs_cannot_hide_placeholders(self) -> None:
        for placeholder in ("ＴＯＤＯ", "ＴＢＤ", "[ＮＥＥＤＳ EVIDENCE]", "𝚃𝙾𝙳𝙾"):
            with self.subTest(placeholder=placeholder):
                def builder(root: Path, placeholder: str = placeholder) -> None:
                    build_content_ready(root)
                    draft_path = root / "drafts/final.md"
                    draft_path.write_text(
                        draft_path.read_text(encoding="utf-8")
                        + f"\n{placeholder}: unresolved factual claim.\n",
                        encoding="utf-8",
                    )
                    hashes = content_artifact_hashes(root)
                    for relative in ("reviews/verification.json", "reviews/editorial.json"):
                        review_path = root / relative
                        review = json.loads(review_path.read_text(encoding="utf-8"))
                        review["artifact_hashes"] = hashes
                        write_json(review_path, review)

                code, report = self.run_fixture(builder)
                self.assert_hard_code(code, report, "FINAL_DRAFT_PLACEHOLDER")


if __name__ == "__main__":
    unittest.main(verbosity=2)
