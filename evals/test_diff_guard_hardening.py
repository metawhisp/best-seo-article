#!/usr/bin/env python3
"""Focused regression tests for diff_guard URL provenance and safe report writes."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
DIFF_GUARD = SKILL_ROOT / "scripts/diff_guard.py"
OLD_URL = "https://example.test/guides/original"
NEW_URL = "https://example.test/guides/revised"


def redirect_plan(
    *,
    source_url: str = OLD_URL,
    target_url: str = NEW_URL,
    status_code: int = 301,
    owner: str = "Web platform team",
) -> dict[str, object]:
    return {
        "source_url": source_url,
        "target_url": target_url,
        "status_code": status_code,
        "owner": owner,
    }


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def build_run(
    root: Path,
    *,
    baseline_url: str | None = OLD_URL,
    destination_url: str | None = OLD_URL,
    url_change_permission: bool = False,
    prior_report: dict[str, object] | None = None,
    baseline_file: str = "snapshot",
) -> None:
    article = "# Evidence guide\n\n## Keep this section\n\nSee the [documentation](https://developers.google.com/search/docs).\n"
    manifest = {
        "mode": "rewrite",
        "permissions": {"url_change": url_change_permission},
        "destination": {"format": "markdown", "url": destination_url, "cms": None},
        "protected": {
            "reviewed": True,
            "rationale": "This section and primary documentation link retain reader value.",
            "empty_selection_approved": False,
            "headings": ["Keep this section"],
            "links": ["https://developers.google.com/search/docs"],
        },
    }
    write_json(root / "manifest.json", manifest)
    write_text(root / "baseline/original.md", article)
    write_text(root / "drafts/final.md", article + "\nUpdated explanation.\n")
    baseline = {"captured_at": "2026-08-29T00:00:00Z", "status": "captured"}
    if baseline_url is not None:
        baseline["url"] = baseline_url
    write_json(root / f"baseline/{baseline_file}.json", baseline)
    if prior_report is not None:
        write_json(root / "diff-report.json", prior_report)


class DiffGuardHardeningTests(unittest.TestCase):
    def invoke(self, root: Path, *extra: str) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
        result = subprocess.run(
            [sys.executable, str(DIFF_GUARD), str(root), *extra],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        try:
            report = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            self.fail(f"diff_guard did not return structured JSON: {exc}\nstdout={result.stdout!r}\nstderr={result.stderr!r}")
        self.assertEqual(result.stderr, "", result.stderr)
        return result, report

    @staticmethod
    def codes(report: dict[str, object]) -> set[str]:
        return {item["code"] for item in report.get("findings", []) if isinstance(item, dict) and "code" in item}

    def test_url_change_is_derived_even_when_prior_report_denies_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_run(
                root,
                destination_url=NEW_URL,
                prior_report={"url_changed": False, "redirect_plan": redirect_plan(), "material_changes": ["Updated evidence"]},
            )
            result, report = self.invoke(root)

            self.assertEqual(result.returncode, 1, report)
            self.assertIs(report["url_changed"], True)
            self.assertEqual(report["baseline_url"], OLD_URL)
            self.assertEqual(report["destination_url"], NEW_URL)
            self.assertIn("URL_CHANGE_UNAUTHORIZED", self.codes(report))
            self.assertNotIn("REDIRECT_PLAN_MISSING", self.codes(report))

    def test_forged_prior_url_change_is_ignored_when_urls_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_run(
                root,
                baseline_url="https://EXAMPLE.test/guides/original/",
                destination_url=OLD_URL,
                prior_report={"url_changed": True, "material_changes": ["Updated evidence"]},
            )
            result, report = self.invoke(root)

            self.assertEqual(result.returncode, 0, report)
            self.assertIs(report["url_changed"], False)
            self.assertNotIn("URL_CHANGE_UNAUTHORIZED", self.codes(report))
            self.assertNotIn("REDIRECT_PLAN_MISSING", self.codes(report))

    def test_repeated_trailing_slashes_remain_a_real_url_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_run(
                root,
                baseline_url="https://example.test/guides/original///",
                destination_url=OLD_URL,
                prior_report={"url_changed": False, "material_changes": ["Updated evidence"]},
            )
            result, report = self.invoke(root)
            self.assertEqual(result.returncode, 1, report)
            self.assertIs(report["url_changed"], True)
            self.assertIn("URL_CHANGE_UNAUTHORIZED", self.codes(report))

    def test_transitional_idna_host_is_not_folded_to_ascii_host(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_run(
                root,
                baseline_url="https://faß.de/guides/original",
                destination_url="https://fass.de/guides/original",
            )
            result, report = self.invoke(root)

            self.assertEqual(result.returncode, 1, report)
            self.assertIn("BASELINE_URL_INVALID", self.codes(report))
            self.assertIsNone(report["url_changed"])

    def test_explicit_permission_and_redirect_allow_derived_url_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_run(
                root,
                destination_url=NEW_URL,
                url_change_permission=True,
                prior_report={"url_changed": False, "redirect_plan": redirect_plan(), "material_changes": ["Updated evidence"]},
            )
            result, report = self.invoke(root)

            self.assertEqual(result.returncode, 0, report)
            self.assertIs(report["url_changed"], True)
            self.assertEqual(report["redirect_plan"], redirect_plan())

    def test_redirect_owner_rejects_control_and_invisible_only_values(self) -> None:
        for owner in ("\u202e", "\x00", "\u200b", "   "):
            with self.subTest(owner=repr(owner)), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                build_run(
                    root,
                    destination_url=NEW_URL,
                    url_change_permission=True,
                    prior_report={
                        "redirect_plan": redirect_plan(owner=owner),
                        "material_changes": ["Updated evidence"],
                    },
                )
                result, report = self.invoke(root)
                self.assertEqual(result.returncode, 1, report)
                self.assertIn("REDIRECT_PLAN_INVALID", self.codes(report))

    def test_refresh_material_changes_require_substantive_control_free_strings(self) -> None:
        invalid_values = (True, {}, None, "", "\u202e", "\x00")
        for value in invalid_values:
            with self.subTest(value=repr(value)), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                build_run(
                    root,
                    prior_report={"material_changes": [value], "date_modified_changed": True},
                )
                manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
                manifest["mode"] = "refresh"
                write_json(root / "manifest.json", manifest)
                result, report = self.invoke(root)
                self.assertEqual(result.returncode, 1, report)
                self.assertIn("MATERIAL_CHANGES_INVALID", self.codes(report))
                self.assertIn("DATE_MODIFIED_UNJUSTIFIED", self.codes(report))

    def test_boolean_redirect_plan_cannot_bypass_structured_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_run(
                root,
                destination_url=NEW_URL,
                url_change_permission=True,
                prior_report={"redirect_plan": True, "material_changes": ["Updated evidence"]},
            )
            result, report = self.invoke(root)

            self.assertEqual(result.returncode, 1, report)
            self.assertIn("REDIRECT_PLAN_INVALID", self.codes(report))
            self.assertIsNone(report["redirect_plan"])

    def test_prose_redirect_plan_cannot_replace_structured_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_run(
                root,
                destination_url=NEW_URL,
                url_change_permission=True,
                prior_report={"redirect_plan": "301 old URL to new URL", "material_changes": ["Updated evidence"]},
            )
            result, report = self.invoke(root)

            self.assertEqual(result.returncode, 1, report)
            self.assertIn("REDIRECT_PLAN_INVALID", self.codes(report))
            self.assertIsNone(report["redirect_plan"])

    def test_redirect_plan_must_bind_baseline_and_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_run(
                root,
                destination_url=NEW_URL,
                url_change_permission=True,
                prior_report={
                    "redirect_plan": redirect_plan(
                        source_url="https://example.test/not-the-baseline",
                        target_url="https://example.test/not-the-destination",
                    ),
                    "material_changes": ["Updated evidence"],
                },
            )
            result, report = self.invoke(root)

            self.assertEqual(result.returncode, 1, report)
            self.assertIn("REDIRECT_PLAN_SOURCE_MISMATCH", self.codes(report))
            self.assertIn("REDIRECT_PLAN_TARGET_MISMATCH", self.codes(report))

    def test_derived_url_change_still_requires_redirect_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_run(
                root,
                destination_url=NEW_URL,
                url_change_permission=True,
                prior_report={"url_changed": False, "material_changes": ["Updated evidence"]},
            )
            result, report = self.invoke(root)

            self.assertEqual(result.returncode, 1, report)
            self.assertIn("REDIRECT_PLAN_MISSING", self.codes(report))

    def test_baseline_metadata_file_is_accepted_as_url_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_run(
                root,
                baseline_file="metadata",
                destination_url=NEW_URL,
                url_change_permission=True,
                prior_report={"redirect_plan": redirect_plan(), "material_changes": ["Updated evidence"]},
            )
            result, report = self.invoke(root)

            self.assertEqual(result.returncode, 0, report)
            self.assertEqual(report["url_change_basis"], "baseline-versus-manifest-destination")
            self.assertIs(report["url_changed"], True)

    def test_destination_url_without_baseline_url_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_run(
                root,
                baseline_url=None,
                destination_url=NEW_URL,
                prior_report={"url_changed": False, "redirect_plan": redirect_plan()},
            )
            result, report = self.invoke(root)

            self.assertEqual(result.returncode, 1, report)
            self.assertIsNone(report["url_changed"])
            self.assertIn("BASELINE_URL_MISSING", self.codes(report))

    def test_destination_url_with_space_is_rejected_as_structured_finding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_run(root, destination_url="https://example.test/guides/bad path")

            result, report = self.invoke(root)

            self.assertEqual(result.returncode, 1, report)
            self.assertEqual(report["status"], "failed")
            self.assertIn("DESTINATION_URL_INVALID", self.codes(report))

    def test_hostile_http_url_spellings_are_rejected_without_traceback(self) -> None:
        invalid_urls = (
            "https://user:secret@example.test/path",
            "https://example.test\\attacker.test/path",
            "https://bad_host.test/path",
            "https://999.999.999.999/path",
            "https://example.test:99999/path",
            "https://example.test:/path",
            "https://example.test/path\nnext",
        )
        for invalid_url in invalid_urls:
            with self.subTest(url=invalid_url), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                build_run(root, destination_url=invalid_url)

                result, report = self.invoke(root)

                self.assertEqual(result.returncode, 1, report)
                self.assertIn("DESTINATION_URL_INVALID", self.codes(report))

    def test_protected_elements_inside_fenced_code_do_not_count_as_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_run(root)
            write_text(
                root / "drafts/final.md",
                "# Evidence guide\n\n"
                "````markdown\n"
                "## Keep this section\n\n"
                "See the [documentation](https://developers.google.com/search/docs).\n"
                "```\n"
                "````\n\n"
                "Updated explanation.\n",
            )

            result, report = self.invoke(root)

            self.assertEqual(result.returncode, 1, report)
            self.assertIn("PROTECTED_HEADINGS_REMOVED", self.codes(report))
            self.assertIn("PROTECTED_LINKS_REMOVED", self.codes(report))

    def test_protected_link_inside_inline_code_does_not_count_as_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_run(root)
            write_text(
                root / "drafts/final.md",
                "# Evidence guide\n\n"
                "## Keep this section\n\n"
                "``See `[documentation](https://developers.google.com/search/docs)`.``\n",
            )

            result, report = self.invoke(root)

            self.assertEqual(result.returncode, 1, report)
            self.assertNotIn("PROTECTED_HEADINGS_REMOVED", self.codes(report))
            self.assertIn("PROTECTED_LINKS_REMOVED", self.codes(report))

    def test_normal_structure_survives_code_filtering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_run(root)
            write_text(
                root / "drafts/final.md",
                "# Evidence guide\n\n"
                "`inline sample`\n\n"
                "## Keep this section\n\n"
                "See the [documentation](https://developers.google.com/search/docs).\n",
            )

            result, report = self.invoke(root)

            self.assertEqual(result.returncode, 0, report)
            self.assertNotIn("PROTECTED_HEADINGS_REMOVED", self.codes(report))
            self.assertNotIn("PROTECTED_LINKS_REMOVED", self.codes(report))

    def test_write_rejects_symlink_target_without_touching_referent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            container = Path(directory)
            root = container / "run"
            build_run(root)
            sentinel = container / "outside.json"
            sentinel.write_text('{"sentinel": true}\n', encoding="utf-8")
            os.symlink(sentinel, root / "diff-report.json")

            result, report = self.invoke(root, "--write")

            self.assertEqual(result.returncode, 1, report)
            self.assertIn("DIFF_REPORT_TARGET_UNSAFE", self.codes(report))
            self.assertTrue((root / "diff-report.json").is_symlink())
            self.assertEqual(sentinel.read_text(encoding="utf-8"), '{"sentinel": true}\n')

    def test_write_rejects_non_regular_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_run(root)
            (root / "diff-report.json").mkdir()

            result, report = self.invoke(root, "--write")

            self.assertEqual(result.returncode, 1, report)
            self.assertIn("DIFF_REPORT_TARGET_UNSAFE", self.codes(report))
            self.assertTrue((root / "diff-report.json").is_dir())

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO creation is unavailable on this platform")
    def test_write_rejects_fifo_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_run(root)
            os.mkfifo(root / "diff-report.json")

            result, report = self.invoke(root, "--write")

            self.assertEqual(result.returncode, 1, report)
            self.assertIn("DIFF_REPORT_TARGET_UNSAFE", self.codes(report))
            self.assertTrue(stat.S_ISFIFO(os.lstat(root / "diff-report.json").st_mode))

    def test_write_atomically_replaces_regular_in_root_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_run(root, prior_report={"url_changed": True, "material_changes": ["Updated evidence"]})

            result, report = self.invoke(root, "--write", "--pretty")

            target = root / "diff-report.json"
            self.assertEqual(result.returncode, 0, report)
            self.assertTrue(stat.S_ISREG(os.lstat(target).st_mode))
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), report)
            self.assertEqual(list(root.glob(".diff-report.json.*.tmp")), [])

    def test_hostile_manifest_type_still_returns_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / "manifest.json", [])

            result, report = self.invoke(root)

            self.assertEqual(result.returncode, 2, report)
            self.assertEqual(report["status"], "unavailable")
            self.assertIn("MANIFEST_INVALID", self.codes(report))

    def test_invalid_utf8_diff_input_still_returns_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_run(root)
            (root / "baseline/original.md").write_bytes(b"\xff\xfe")

            result, report = self.invoke(root)

            self.assertEqual(result.returncode, 2, report)
            self.assertEqual(report["status"], "unavailable")
            self.assertIn("DIFF_INPUT_INVALID", self.codes(report))

    def test_rewrite_baseline_rejects_document_control_characters(self) -> None:
        for control in ("\u202e", "\x00", "\x01", "\x7f"):
            with self.subTest(control=repr(control)), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                build_run(root)
                baseline = root / "baseline/original.md"
                baseline.write_text(baseline.read_text(encoding="utf-8") + control, encoding="utf-8")
                result, report = self.invoke(root)
                self.assertEqual(result.returncode, 1, report)
                self.assertIn("DIFF_INPUT_CONTROL_INVALID", self.codes(report))


if __name__ == "__main__":
    unittest.main(verbosity=2)
