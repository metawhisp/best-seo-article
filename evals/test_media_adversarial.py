#!/usr/bin/env python3
"""Adversarial regressions for the offline media validator."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable


SKILL_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = SKILL_ROOT / "scripts/validate_media.py"
VALID_FIXTURE = SKILL_ROOT / "evals/fixtures/media-valid.json"
MEDIA_SCHEMA = SKILL_ROOT / "schemas/media-manifest.schema.json"
DATASET_SCHEMA = SKILL_ROOT / "schemas/dataset-manifest.schema.json"


def load_fixture() -> dict[str, Any]:
    """Load a fixture adjusted to the hardened chart contract."""
    manifest = json.loads(VALID_FIXTURE.read_text(encoding="utf-8"))
    chart = manifest["assets"][2]
    chart["output"]["path"] = "media/chart-monthly-clicks.webp"
    chart["output"]["mime_type"] = "image/webp"
    transform = manifest["datasets"][0]["transformations"][0]
    chart["chart_data"]["transform_output_sha256"] = transform["output_sha256"]
    return manifest


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def run_validator(path: Path, *extra: str) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    process = subprocess.run(
        [sys.executable, str(VALIDATOR), str(path), *extra],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    try:
        report = json.loads(process.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - assertion diagnostics
        raise AssertionError(
            f"validator returned non-JSON stdout; stderr={process.stderr!r} stdout={process.stdout!r}"
        ) from exc
    return process, report


def issue_codes(report: dict[str, Any]) -> set[str]:
    return {issue["code"] for issue in report.get("issues", [])}


def single_asset_manifest(index: int) -> dict[str, Any]:
    manifest = load_fixture()
    asset = copy.deepcopy(manifest["assets"][index])
    manifest["assets"] = [asset]
    if asset["type"] != "chart":
        manifest["datasets"] = []
    return manifest


def configure_output(asset: dict[str, Any], path: str, mime_type: str, payload: bytes) -> None:
    asset["output"].update(
        {
            "path": path,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "mime_type": mime_type,
            "bytes": len(payload),
            "variants": [],
        }
    )


def write_bound(root: Path, relative_path: str, payload: bytes) -> str:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def materialize_chart_manifest(
    root: Path,
    long_description: bytes = b"Monthly clicks rise from twelve to twenty across the reviewed period.\n",
    data_table: bytes = b"<table><caption>Monthly clicks</caption><tr><th>Month</th><th>Clicks</th></tr><tr><td>January</td><td>12</td></tr></table>",
) -> dict[str, Any]:
    manifest = load_fixture()
    manifest["assets"] = [copy.deepcopy(manifest["assets"][2])]
    dataset = manifest["datasets"][0]
    snapshot_sha = write_bound(root, dataset["snapshot_path"], b"month,clicks\n2026-01,12\n")
    dataset["snapshot_sha256"] = snapshot_sha
    transform = dataset["transformations"][0]
    spec_sha = write_bound(root, transform["spec_path"], b'{"group_by":"month"}\n')
    transform["spec_sha256"] = spec_sha
    transform["input_sha256"] = snapshot_sha
    transform["output_sha256"] = hashlib.sha256(b"2026-01,12\n").hexdigest()

    chart = manifest["assets"][0]
    chart_data = chart["chart_data"]
    chart_data["spec_sha256"] = spec_sha
    chart_data["transform_output_sha256"] = transform["output_sha256"]
    output_payload = b"RIFF\x04\x00\x00\x00WEBPVP8 "
    configure_output(chart, "media/chart.webp", "image/webp", output_payload)
    write_bound(root, "media/chart.webp", output_payload)
    accessibility = chart["accessibility"]
    accessibility["long_description_sha256"] = write_bound(
        root,
        accessibility["long_description_path"],
        long_description,
    )
    accessibility["data_table_sha256"] = write_bound(
        root,
        accessibility["data_table_path"],
        data_table,
    )
    return manifest


def materialize_video_manifest(
    root: Path,
    captions: bytes = b"WEBVTT\n\n00:00.000 --> 00:02.000\nThe research workflow begins with source verification.\n",
    transcript: bytes = b"The narrator explains how sources are verified before an article is approved.\n",
) -> dict[str, Any]:
    manifest = single_asset_manifest(0)
    asset = manifest["assets"][0]
    asset["type"] = "video"
    video_payload = b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isom"
    configure_output(asset, "media/workflow.mp4", "video/mp4", video_payload)
    write_bound(root, "media/workflow.mp4", video_payload)
    write_bound(root, "media/poster.webp", b"RIFF\x04\x00\x00\x00WEBPVP8 ")
    asset["video"] = {
        "meaningful_audio": True,
        "poster_path": "media/poster.webp",
        "captions_path": "captions/workflow.vtt",
        "captions_sha256": write_bound(root, "captions/workflow.vtt", captions),
        "transcript_path": "transcripts/workflow.txt",
        "transcript_sha256": write_bound(root, "transcripts/workflow.txt", transcript),
    }
    return manifest


def walk_refs(value: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "$ref" and isinstance(item, str):
                refs.append(item)
            refs.extend(walk_refs(item))
    elif isinstance(value, list):
        for item in value:
            refs.extend(walk_refs(item))
    return refs


class MediaAdversarialTests(unittest.TestCase):
    def test_pirated_rights_and_active_html_are_rejected(self) -> None:
        manifest = single_asset_manifest(0)
        asset = manifest["assets"][0]
        asset["type"] = "table"
        asset["performance"] = {
            "above_fold": False,
            "lcp_candidate": False,
            "loading": "lazy",
            "fetchpriority": "auto",
            "responsive": True,
        }
        asset["rights"]["usage_basis"] = "pirated"
        payload = b"<table><tr><td>safe</td></tr></table><script>alert(1)</script>"
        configure_output(asset, "media/table.html", "text/html", payload)

        with tempfile.TemporaryDirectory(prefix="media-active-html-") as temporary:
            root = Path(temporary)
            write_json(root / "media-manifest.json", manifest)
            output = root / "media/table.html"
            output.parent.mkdir(parents=True)
            output.write_bytes(payload)
            process, report = run_validator(root / "media-manifest.json", "--asset-root", str(root))

        self.assertEqual(process.returncode, 1)
        self.assertEqual(process.stderr, "")
        self.assertIn("V004_VALUE", issue_codes(report))
        self.assertIn("V094_ACTIVE_CONTENT_REJECTED", issue_codes(report))

    def test_static_html_table_is_allowed(self) -> None:
        manifest = single_asset_manifest(0)
        asset = manifest["assets"][0]
        asset["type"] = "table"
        asset["performance"] = {
            "above_fold": False,
            "lcp_candidate": False,
            "loading": "lazy",
            "fetchpriority": "auto",
            "responsive": True,
        }
        payload = b"<table><caption>Clicks</caption><tr><th>Month</th><td>12</td></tr></table>"
        configure_output(asset, "media/table.html", "text/html", payload)

        with tempfile.TemporaryDirectory(prefix="media-static-html-") as temporary:
            root = Path(temporary)
            write_json(root / "media-manifest.json", manifest)
            output = root / "media/table.html"
            output.parent.mkdir(parents=True)
            output.write_bytes(payload)
            process, report = run_validator(root / "media-manifest.json", "--asset-root", str(root))

        self.assertEqual(process.returncode, 0, report)
        self.assertEqual(report["status"], "clean")

    def test_active_svg_is_rejected_and_static_svg_is_allowed(self) -> None:
        cases = {
            "active": (
                b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
                1,
            ),
            "static": (
                b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><title>Dot</title><circle cx="5" cy="5" r="4" fill="#000"/></svg>',
                0,
            ),
        }
        for name, (payload, expected_exit) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory(prefix=f"media-svg-{name}-") as temporary:
                root = Path(temporary)
                manifest = single_asset_manifest(3)
                asset = manifest["assets"][0]
                configure_output(asset, "media/diagram.svg", "image/svg+xml", payload)
                write_json(root / "media-manifest.json", manifest)
                output = root / "media/diagram.svg"
                output.parent.mkdir(parents=True)
                output.write_bytes(payload)
                description = root / asset["accessibility"]["long_description_path"]
                description.parent.mkdir(parents=True)
                description_payload = b"A static dot diagram with one centered circle and no data encoding.\n"
                description.write_bytes(description_payload)
                asset["accessibility"]["long_description_sha256"] = hashlib.sha256(description_payload).hexdigest()
                write_json(root / "media-manifest.json", manifest)
                process, report = run_validator(root / "media-manifest.json", "--asset-root", str(root))

                self.assertEqual(process.returncode, expected_exit, report)
                if expected_exit:
                    self.assertIn("V094_ACTIVE_CONTENT_REJECTED", issue_codes(report))

    def test_chart_requires_exact_transform_linkage(self) -> None:
        mutations: dict[str, tuple[Callable[[dict[str, Any]], None], str]] = {
            "empty-id": (
                lambda chart: chart.__setitem__("transform_id", ""),
                "V004_VALUE",
            ),
            "different-spec": (
                lambda chart: chart.__setitem__("spec_path", "data/transforms/other.json"),
                "V090_TRANSFORM_LINK_MISMATCH",
            ),
            "different-output": (
                lambda chart: chart.__setitem__("transform_output_sha256", "f" * 64),
                "V091_TRANSFORM_OUTPUT_MISMATCH",
            ),
        }
        for name, (mutate, expected_code) in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory(prefix=f"media-chart-{name}-") as temporary:
                manifest = load_fixture()
                mutate(manifest["assets"][2]["chart_data"])
                path = Path(temporary) / "manifest.json"
                write_json(path, manifest)
                process, report = run_validator(path)

                self.assertEqual(process.returncode, 1, report)
                self.assertIn(expected_code, issue_codes(report))

    def test_first_party_dataset_can_use_local_provenance_and_rights(self) -> None:
        manifest = load_fixture()
        manifest["assets"] = []
        dataset = manifest["datasets"][0]
        dataset["transformations"] = []
        dataset.pop("source_url")
        dataset["source_path"] = "evidence/gsc-export-origin.json"
        dataset["license"].pop("license_url")
        dataset["license"]["evidence_path"] = "evidence/first-party-data-rights.json"

        with tempfile.TemporaryDirectory(prefix="media-local-data-") as temporary:
            root = Path(temporary)
            source_payload = b'{"export":"owned Search Console account"}\n'
            rights_payload = b'{"owner":"Example Company","use":"commercial"}\n'
            snapshot_payload = b"month,clicks\n2026-01,12\n"
            dataset["source_path_sha256"] = write_bound(root, dataset["source_path"], source_payload)
            dataset["license"]["evidence_sha256"] = write_bound(
                root,
                dataset["license"]["evidence_path"],
                rights_payload,
            )
            dataset["snapshot_sha256"] = write_bound(root, dataset["snapshot_path"], snapshot_payload)
            path = root / "manifest.json"
            write_json(path, manifest)
            process, report = run_validator(path, "--asset-root", str(root))

        self.assertEqual(process.returncode, 0, report)
        self.assertEqual(report["status"], "clean")

    def test_malformed_values_always_return_structured_json(self) -> None:
        mutations: dict[str, Callable[[dict[str, Any]], None]] = {
            "malformed-ipv6": lambda manifest: manifest["assets"][0]["source"].__setitem__("source_url", "https://["),
            "hostless-url": lambda manifest: manifest["assets"][0]["source"].__setitem__("source_url", "https://:443/path"),
            "space-in-url": lambda manifest: manifest["assets"][0]["source"].__setitem__("source_url", "https://example.test/path with space"),
            "unicode-idn-host": lambda manifest: manifest["assets"][0]["source"].__setitem__("source_url", "https://faß.de/reference"),
            "list-disclosure": lambda manifest: manifest["assets"][2]["chart_data"].__setitem__("disclosure", []),
            "nul-path": lambda manifest: manifest["assets"][0]["output"].__setitem__("path", "media/bad\u0000.webp"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory(prefix=f"media-malformed-{name}-") as temporary:
                manifest = load_fixture()
                mutate(manifest)
                path = Path(temporary) / "manifest.json"
                write_json(path, manifest)
                process, report = run_validator(path)

                self.assertEqual(process.returncode, 1, report)
                self.assertEqual(process.stderr, "")
                self.assertEqual(report["status"], "failed")

    def test_future_provenance_timestamp_is_rejected(self) -> None:
        manifest = load_fixture()
        manifest["assets"][0]["source"]["retrieved_at"] = (
            datetime.now(timezone.utc) + timedelta(days=1)
        ).isoformat().replace("+00:00", "Z")
        with tempfile.TemporaryDirectory(prefix="media-future-time-") as temporary:
            path = Path(temporary) / "manifest.json"
            write_json(path, manifest)
            process, report = run_validator(path)

        self.assertEqual(process.returncode, 1, report)
        self.assertIn("V015_FUTURE_TIMESTAMP", issue_codes(report))

    def test_provenance_timestamp_rejects_non_rfc3339_separator(self) -> None:
        manifest = load_fixture()
        manifest["assets"][0]["source"]["retrieved_at"] = "2026-08-29\n12:00:00Z"
        with tempfile.TemporaryDirectory(prefix="media-bad-time-") as temporary:
            path = Path(temporary) / "manifest.json"
            write_json(path, manifest)
            process, report = run_validator(path)

        self.assertEqual(process.returncode, 1, report)
        self.assertIn("V007_DATETIME", issue_codes(report))

    def test_arbitrary_top_level_json_types_fail_without_tracebacks(self) -> None:
        for value in (None, [], "manifest", 17, True):
            with self.subTest(value=value), tempfile.TemporaryDirectory(prefix="media-json-type-") as temporary:
                path = Path(temporary) / "manifest.json"
                write_json(path, value)
                process, report = run_validator(path)

                self.assertEqual(process.returncode, 1, report)
                self.assertEqual(process.stderr, "")
                self.assertEqual(report["status"], "failed")
                self.assertIn("V003_TYPE", issue_codes(report))

    def test_run_identity_and_claim_ids_are_bound_and_reported(self) -> None:
        manifest = single_asset_manifest(0)
        manifest["run_id"] = "media-run"
        manifest["assets"][0]["claim_ids"] = ["C-MISSING"]

        with tempfile.TemporaryDirectory(prefix="media-identity-") as temporary:
            root = Path(temporary)
            write_json(root / "media-manifest.json", manifest)
            write_json(root / "manifest.json", {"run_id": "article-run"})
            (root / "claims.jsonl").write_text('{"claim_id":"C-EXISTS"}\n', encoding="utf-8")
            process, report = run_validator(root)

        self.assertEqual(process.returncode, 1, report)
        self.assertIn("V088_ARTICLE_RUN_ID_MISMATCH", issue_codes(report))
        self.assertIn("V089_MEDIA_CLAIM_UNKNOWN", issue_codes(report))
        self.assertEqual(report["identity"]["run_id"], "media-run")
        self.assertEqual(report["identity"]["claim_ids"], ["C-MISSING"])
        self.assertIn("media/hero-seo-workflow.webp", report["identity"]["output_paths"])

        spec = importlib.util.spec_from_file_location("best_seo_media_validator", VALIDATOR)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader if spec is not None else None)
        module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        identity = module.collect_media_identity(manifest)
        self.assertEqual(identity, report["identity"])

    def test_run_media_manifest_symlink_is_rejected_before_reading(self) -> None:
        with tempfile.TemporaryDirectory(prefix="media-symlink-") as temporary:
            root = Path(temporary)
            write_json(root / "manifest-target.json", load_fixture())
            (root / "media-manifest.json").symlink_to("manifest-target.json")
            process, report = run_validator(root)

        self.assertEqual(process.returncode, 1, report)
        self.assertIn("V014_PATH_SYMLINK", issue_codes(report))

    def test_active_formats_require_local_inspection(self) -> None:
        manifest = single_asset_manifest(3)
        asset = manifest["assets"][0]
        asset["output"]["path"] = "media/diagram.svg"
        asset["output"]["mime_type"] = "image/svg+xml"

        with tempfile.TemporaryDirectory(prefix="media-uninspected-") as temporary:
            path = Path(temporary) / "manifest.json"
            write_json(path, manifest)
            process, report = run_validator(path)

        self.assertEqual(process.returncode, 1, report)
        self.assertIn("V096_ACTIVE_CONTENT_UNINSPECTED", issue_codes(report))

    def test_optional_dataset_field_types_match_schema(self) -> None:
        manifest = load_fixture()
        manifest["datasets"][0]["fields"][1]["unit"] = 123

        with tempfile.TemporaryDirectory(prefix="media-unit-type-") as temporary:
            path = Path(temporary) / "manifest.json"
            write_json(path, manifest)
            process, report = run_validator(path)

        self.assertEqual(process.returncode, 1, report)
        self.assertIn("V003_TYPE", issue_codes(report))

    def test_punctuation_and_symbol_only_media_evidence_is_rejected(self) -> None:
        mutations: dict[str, tuple[Callable[[dict[str, Any]], None], str]] = {
            "asset-purpose": (
                lambda manifest: manifest["assets"][0].__setitem__("purpose", "... ✓ 🔥"),
                "V004_VALUE",
            ),
            "source-creator": (
                lambda manifest: manifest["assets"][0]["source"].__setitem__("creator", "© —"),
                "V004_VALUE",
            ),
            "informative-alt": (
                lambda manifest: manifest["assets"][0]["accessibility"].__setitem__("alt", "!!!"),
                "V042_ALT_MISSING",
            ),
            "asset-attribution": (
                lambda manifest: manifest["assets"][2]["rights"].__setitem__("attribution_text", "© ✓"),
                "V004_VALUE",
            ),
            "dataset-title": (
                lambda manifest: manifest["datasets"][0].__setitem__("title", "— —"),
                "V004_VALUE",
            ),
            "dataset-methodology": (
                lambda manifest: manifest["datasets"][0].__setitem__("methodology", "✓✓✓"),
                "V004_VALUE",
            ),
            "dataset-field-description": (
                lambda manifest: manifest["datasets"][0]["fields"][0].__setitem__("description", "..."),
                "V004_VALUE",
            ),
            "transformation-description": (
                lambda manifest: manifest["datasets"][0]["transformations"][0].__setitem__("description", "🔥"),
                "V004_VALUE",
            ),
            "chart-disclosure": (
                lambda manifest: manifest["assets"][2]["chart_data"].__setitem__("disclosure", "✓"),
                "V004_VALUE",
            ),
            "ai-disclosure": (
                lambda manifest: manifest["assets"][3]["ai"].__setitem__("disclosure", "..."),
                "V064_AI_DISCLOSURE",
            ),
            "redaction-note": (
                lambda manifest: manifest["assets"][1]["screenshot"].__setitem__("redactions", ["***"]),
                "V003_TYPE",
            ),
        }
        for name, (mutate, expected_code) in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory(prefix=f"media-semantic-{name}-") as temporary:
                manifest = load_fixture()
                mutate(manifest)
                path = Path(temporary) / "manifest.json"
                write_json(path, manifest)
                process, report = run_validator(path)

                self.assertEqual(process.returncode, 1, report)
                self.assertIn(expected_code, issue_codes(report))

    def test_multilingual_human_evidence_is_accepted(self) -> None:
        manifest = load_fixture()
        dataset = manifest["datasets"][0]
        dataset.update(
            {
                "title": "شهری کلک",
                "publisher": "出版者",
                "methodology": "Данные сгруппированы по календарному месяцу.",
            }
        )
        dataset["fields"][0]["description"] = "التاريخ الشهري"
        dataset["transformations"][0]["description"] = "月ごとに集計します。"
        asset = manifest["assets"][0]
        asset["purpose"] = "Показывает проверяемый рабочий процесс."
        asset["source"]["creator"] = "设计团队"
        asset["accessibility"]["alt"] = "مراحل البحث والتحقق من الأدلة"
        asset["rights"]["attribution_required"] = True
        asset["rights"]["attribution_text"] = "Источник: команда дизайна"
        manifest["assets"][1]["screenshot"]["redactions"] = ["メールアドレスを削除"]

        with tempfile.TemporaryDirectory(prefix="media-semantic-multilingual-") as temporary:
            path = Path(temporary) / "manifest.json"
            write_json(path, manifest)
            process, report = run_validator(path)

        self.assertEqual(process.returncode, 0, report)
        self.assertEqual(report["status"], "clean")

    def test_machine_identifiers_and_symbol_units_remain_valid(self) -> None:
        manifest = load_fixture()
        dataset = manifest["datasets"][0]
        dataset["dataset_id"] = "---"
        dataset["transformations"][0]["transform_id"] = "..."
        dataset["fields"][1]["name"] = "$"
        chart = manifest["assets"][2]["chart_data"]
        chart["dataset_id"] = "---"
        chart["transform_id"] = "..."
        chart["field_names"][1] = "$"
        chart["units"] = "%"

        with tempfile.TemporaryDirectory(prefix="media-machine-identifiers-") as temporary:
            path = Path(temporary) / "manifest.json"
            write_json(path, manifest)
            process, report = run_validator(path)

        self.assertEqual(process.returncode, 0, report)
        self.assertEqual(report["status"], "clean")

    def test_local_provenance_and_rights_files_reject_empty_symlink_and_hash_mismatch(self) -> None:
        cases = ("uninspected", "empty", "rights-empty", "symlink", "symlink-component", "hash-mismatch")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory(prefix=f"media-local-evidence-{case}-") as temporary:
                root = Path(temporary)
                manifest = load_fixture()
                manifest["assets"] = []
                dataset = manifest["datasets"][0]
                dataset["transformations"] = []
                dataset.pop("source_url")
                dataset["source_path"] = "evidence/origin.json"
                dataset["license"].pop("license_url")
                dataset["license"]["evidence_path"] = "evidence/rights.json"
                snapshot = b"month,clicks\n2026-01,12\n"
                dataset["snapshot_sha256"] = write_bound(root, dataset["snapshot_path"], snapshot)
                source = b'{"origin":"first-party export"}\n'
                rights = b'{"rights":"owned and approved"}\n'
                dataset["source_path_sha256"] = hashlib.sha256(source).hexdigest()
                dataset["license"]["evidence_sha256"] = write_bound(root, dataset["license"]["evidence_path"], rights)
                if case == "uninspected":
                    write_bound(root, dataset["source_path"], source)
                elif case == "empty":
                    write_bound(root, dataset["source_path"], b"")
                    dataset["source_path_sha256"] = hashlib.sha256(b"").hexdigest()
                elif case == "rights-empty":
                    write_bound(root, dataset["source_path"], source)
                    dataset["license"]["evidence_sha256"] = write_bound(
                        root,
                        dataset["license"]["evidence_path"],
                        b"",
                    )
                elif case == "symlink":
                    target = root / "evidence/origin-target.json"
                    target.write_bytes(source)
                    (root / dataset["source_path"]).symlink_to(target.name)
                elif case == "symlink-component":
                    real_directory = root / "real-evidence"
                    real_directory.mkdir()
                    (real_directory / "origin.json").write_bytes(source)
                    (root / "evidence-link").symlink_to(real_directory, target_is_directory=True)
                    dataset["source_path"] = "evidence-link/origin.json"
                else:
                    write_bound(root, dataset["source_path"], source)
                    dataset["source_path_sha256"] = "f" * 64
                write_json(root / "manifest.json", manifest)
                process, report = (
                    run_validator(root / "manifest.json")
                    if case == "uninspected"
                    else run_validator(root / "manifest.json", "--asset-root", str(root))
                )

                self.assertEqual(process.returncode, 1, report)
                expected = {
                    "uninspected": "V098_LOCAL_FILE_UNINSPECTED",
                    "empty": "V099_EMPTY_FILE",
                    "rights-empty": "V099_EMPTY_FILE",
                    "symlink": "V014_PATH_SYMLINK",
                    "symlink-component": "V014_PATH_SYMLINK",
                    "hash-mismatch": "V010_HASH_MISMATCH",
                }[case]
                self.assertIn(expected, issue_codes(report))

    def test_manual_approval_requires_structured_review_and_risk_scope(self) -> None:
        bare = single_asset_manifest(1)
        bare["assets"][0]["rights"].pop("manual_review")
        with tempfile.TemporaryDirectory(prefix="media-bare-review-") as temporary:
            path = Path(temporary) / "manifest.json"
            write_json(path, bare)
            process, report = run_validator(path)
        self.assertEqual(process.returncode, 1, report)
        self.assertIn("V028_REVIEW_RECORD_INVALID", issue_codes(report))

        scoped = single_asset_manifest(0)
        rights = scoped["assets"][0]["rights"]
        rights.update(
            {
                "depicts_recognizable_people": True,
                "model_release_status": "verified",
                "manual_review_status": "approved",
                "manual_review": {
                    "reviewer": "Rights reviewer",
                    "reviewed_at": "2026-08-29T08:00:00Z",
                    "evidence": "Reviewed the signed model release against the depicted person.",
                    "scopes": ["general_rights"],
                },
            }
        )
        with tempfile.TemporaryDirectory(prefix="media-review-scope-") as temporary:
            path = Path(temporary) / "manifest.json"
            write_json(path, scoped)
            process, report = run_validator(path)
            self.assertEqual(process.returncode, 1, report)
            self.assertIn("V026_MODEL_RELEASE_REVIEW", issue_codes(report))
            rights["manual_review"]["scopes"].append("model_release")
            write_json(path, scoped)
            process, report = run_validator(path)
        self.assertEqual(process.returncode, 0, report)

    def test_ai_inputs_are_itemized_with_individual_rights(self) -> None:
        manifest = single_asset_manifest(3)
        ai = manifest["assets"][0]["ai"]
        ai["input_assets"] = [
            {
                "input_id": "brand-reference",
                "kind": "reference_image",
                "creator": "Example Company Design",
                "retrieved_at": "2026-08-29T09:00:00Z",
                "sha256": "7" * 64,
                "source_url": "https://example.com/brand/reference",
                "rights_status": "verified",
                "usage_basis": "owned",
                "commercial_use_allowed": True,
                "modification_allowed": True,
                "rights_evidence_url": "https://example.com/media-policy",
            }
        ]
        with tempfile.TemporaryDirectory(prefix="media-ai-input-") as temporary:
            path = Path(temporary) / "manifest.json"
            write_json(path, manifest)
            process, report = run_validator(path)
            self.assertEqual(process.returncode, 0, report)

            ai["input_assets"][0].pop("rights_evidence_url")
            write_json(path, manifest)
            process, report = run_validator(path)
        self.assertEqual(process.returncode, 1, report)
        self.assertIn("V023_LICENSE_EVIDENCE_MISSING", issue_codes(report))

    def test_accessibility_files_require_substantive_content(self) -> None:
        cases = {
            "long-description": (b"...\n", b"<table><caption>Monthly clicks</caption><tr><th>Month</th></tr><tr><td>January</td></tr></table>"),
            "table-structure": (b"The chart describes monthly clicks across the reviewed reporting period.\n", b"<p>Monthly clicks were twelve.</p>"),
            "table-content": (b"The chart describes monthly clicks across the reviewed reporting period.\n", b"<table><caption>...</caption><tr><th>!</th></tr><tr><td>?</td></tr></table>"),
        }
        for name, (description, table) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory(prefix=f"media-a11y-{name}-") as temporary:
                root = Path(temporary)
                manifest = materialize_chart_manifest(root, description, table)
                write_json(root / "manifest.json", manifest)
                process, report = run_validator(root / "manifest.json", "--asset-root", str(root))
                self.assertEqual(process.returncode, 1, report)
                self.assertIn("V100_ACCESSIBILITY_CONTENT", issue_codes(report))

        with tempfile.TemporaryDirectory(prefix="media-a11y-positive-") as temporary:
            root = Path(temporary)
            manifest = materialize_chart_manifest(root)
            write_json(root / "manifest.json", manifest)
            process, report = run_validator(root / "manifest.json", "--asset-root", str(root))
        self.assertEqual(process.returncode, 0, report)

    def test_captions_and_transcripts_require_spoken_content(self) -> None:
        cases = {
            "captions": (b"WEBVTT\n\n00:00.000 --> 00:02.000\n...\n", b"The transcript contains a complete explanation of the research workflow.\n"),
            "transcript": (b"WEBVTT\n\n00:00.000 --> 00:02.000\nThe workflow begins with verified sources.\n", b"... !!!\n"),
        }
        for name, (captions, transcript) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory(prefix=f"media-video-{name}-") as temporary:
                root = Path(temporary)
                manifest = materialize_video_manifest(root, captions, transcript)
                write_json(root / "manifest.json", manifest)
                process, report = run_validator(root / "manifest.json", "--asset-root", str(root))
                self.assertEqual(process.returncode, 1, report)
                self.assertIn("V100_ACCESSIBILITY_CONTENT", issue_codes(report))

        with tempfile.TemporaryDirectory(prefix="media-video-positive-") as temporary:
            root = Path(temporary)
            manifest = materialize_video_manifest(root)
            write_json(root / "manifest.json", manifest)
            process, report = run_validator(root / "manifest.json", "--asset-root", str(root))
        self.assertEqual(process.returncode, 0, report)

    def test_materialized_media_paths_require_canonical_literal_spelling(self) -> None:
        with tempfile.TemporaryDirectory(prefix="media-path-alias-") as temporary:
            root = Path(temporary)
            manifest = materialize_chart_manifest(root)
            manifest["assets"][0]["output"]["path"] += "/"
            write_json(root / "manifest.json", manifest)
            process, report = run_validator(root / "manifest.json", "--asset-root", str(root))
            self.assertEqual(process.returncode, 1, report)
            self.assertIn("V008_PATH", issue_codes(report))

    def test_schemas_are_offline_and_match_local_provenance_contract(self) -> None:
        media_schema = json.loads(MEDIA_SCHEMA.read_text(encoding="utf-8"))
        dataset_schema = json.loads(DATASET_SCHEMA.read_text(encoding="utf-8"))
        self.assertTrue(all(reference.startswith("#") for reference in walk_refs(media_schema)))
        self.assertTrue(all(reference.startswith("#") for reference in walk_refs(dataset_schema)))

        for schema in (media_schema, dataset_schema):
            pattern = schema["$defs"]["relativePath"]["pattern"]
            self.assertIsNone(re.fullmatch(pattern, "..\\secret"))
            semantic_text = schema["$defs"]["semanticText"]
            self.assertTrue(semantic_text["x-unicode-letter-or-number"])
            self.assertEqual(semantic_text["pattern"], "\\S")

        dataset = dataset_schema["$defs"]["dataset"]
        self.assertNotIn("source_url", dataset["required"])
        source_alternatives = {tuple(sorted(option["required"])) for option in dataset["anyOf"]}
        self.assertEqual(source_alternatives, {("source_path", "source_path_sha256"), ("source_url",)})
        license_schema = dataset_schema["$defs"]["license"]
        self.assertNotIn("license_url", license_schema["required"])
        license_alternatives = {tuple(sorted(option["required"])) for option in license_schema["anyOf"]}
        self.assertEqual(license_alternatives, {("evidence_path", "evidence_sha256"), ("license_url",)})
        chart = media_schema["$defs"]["chartData"]
        self.assertEqual(chart["properties"]["transform_id"], {"$ref": "#/$defs/nonEmptyString"})
        self.assertIn("transform_output_sha256", chart["required"])
        self.assertEqual(media_schema["$defs"]["asset"]["properties"]["purpose"], {"$ref": "#/$defs/semanticText"})
        self.assertEqual(media_schema["$defs"]["source"]["properties"]["creator"], {"$ref": "#/$defs/semanticText"})
        self.assertIn("manual_review", media_schema["$defs"]["rights"]["properties"])
        self.assertIn("reviewed_at", media_schema["$defs"]["reviewRecord"]["required"])
        self.assertIn("evidence", media_schema["$defs"]["reviewRecord"]["required"])
        self.assertIn("input_assets", media_schema["$defs"]["ai"]["required"])
        self.assertNotIn("input_rights_verified", media_schema["$defs"]["ai"]["properties"])
        self.assertEqual(media_schema["$defs"]["ai"]["properties"]["input_assets"]["items"], {"$ref": "#/$defs/aiInput"})
        accessibility = media_schema["$defs"]["accessibility"]
        self.assertEqual(accessibility["dependentRequired"]["long_description_path"], ["long_description_sha256"])
        self.assertEqual(accessibility["dependentRequired"]["data_table_path"], ["data_table_sha256"])

        ref_names = {
            "#/$defs/datasetLicense": "#/$defs/license",
            "#/$defs/datasetField": "#/$defs/field",
            "#/$defs/datasetTransformation": "#/$defs/transformation",
        }

        def normalize_refs(value: Any) -> Any:
            if isinstance(value, dict):
                return {
                    key: ref_names.get(item, item) if key == "$ref" else normalize_refs(item)
                    for key, item in value.items()
                }
            if isinstance(value, list):
                return [normalize_refs(item) for item in value]
            return value

        self.assertEqual(normalize_refs(media_schema["$defs"]["dataset"]), dataset_schema["$defs"]["dataset"])
        self.assertEqual(normalize_refs(media_schema["$defs"]["datasetLicense"]), dataset_schema["$defs"]["license"])
        self.assertEqual(normalize_refs(media_schema["$defs"]["datasetField"]), dataset_schema["$defs"]["field"])
        self.assertEqual(
            normalize_refs(media_schema["$defs"]["datasetTransformation"]),
            dataset_schema["$defs"]["transformation"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
