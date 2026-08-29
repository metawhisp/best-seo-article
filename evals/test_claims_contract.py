#!/usr/bin/env python3
"""Claims-validator regressions for schema/runtime contract drift."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = SKILL_ROOT / "scripts/validate_claims.py"
TEST_NOW = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=1)
TEST_TIMESTAMP = TEST_NOW.isoformat().replace("+00:00", "Z")
TEST_DATE = TEST_NOW.date().isoformat()


def valid_manifest() -> dict[str, Any]:
    return {
        "run_id": "claims-contract-0001",
        "target": "Evidence-led SEO article",
        "language": "en",
        "risk": {"ymyl": False, "jurisdiction": None},
        "roles": {
            "writer": "writer-pass",
            "verifier": "verifier-pass",
            "editor": None,
            "expert_reviewer": None,
        },
    }


def valid_source() -> dict[str, Any]:
    return {
        "source_id": "S1",
        "title": "Official source",
        "locator": "https://example.test/source",
        "publisher": "Example",
        "retrieved_at": TEST_TIMESTAMP,
        "source_type": "official",
        "acquisition": "agent-web",
        "access_status": "accessible",
        "supported_claim_ids": ["C1"],
        "known_conflicts": [],
    }


def valid_claim() -> dict[str, Any]:
    return {
        "claim_id": "C1",
        "text": "The official source supports this material statement.",
        "location": "Evidence",
        "classification": "load-bearing",
        "claim_type": "factual",
        "source_ids": ["S1"],
        "support_status": "verified",
        "freshness_status": "current",
        "exact_support": "The verifier inspected the relevant source passage.",
        "verifier": "verifier-pass",
        "resolution": "approved",
        "as_of": TEST_DATE,
    }


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")


class ClaimsContractTests(unittest.TestCase):
    maxDiff = None

    def run_validator(
        self,
        *,
        manifest: dict[str, Any] | None = None,
        sources: list[dict[str, Any]] | None = None,
        claims: list[dict[str, Any]] | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
        with tempfile.TemporaryDirectory(prefix="best-seo-claims-") as temporary:
            root = Path(temporary)
            (root / "manifest.json").write_text(
                json.dumps(copy.deepcopy(manifest if manifest is not None else valid_manifest())),
                encoding="utf-8",
            )
            fixture_sources = copy.deepcopy(sources if sources is not None else [valid_source()])
            fixture_claims = copy.deepcopy(claims if claims is not None else [valid_claim()])
            write_jsonl(root / "research/sources.jsonl", fixture_sources)
            write_jsonl(root / "claims.jsonl", fixture_claims)
            visible_claims: list[str] = []
            for record in fixture_claims:
                text = record.get("text") if isinstance(record, dict) else None
                if not isinstance(text, str):
                    continue
                try:
                    text.encode("utf-8")
                except UnicodeEncodeError:
                    continue
                visible_claims.append(text)
            (root / "drafts").mkdir(parents=True, exist_ok=True)
            (root / "drafts/final.md").write_text(
                "# Claim contract fixture\n\n## Evidence\n\n" + "\n\n".join(visible_claims) + "\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(VALIDATOR), str(root)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertNotIn("Traceback", result.stdout + result.stderr)
        try:
            report = json.loads(result.stdout)
        except json.JSONDecodeError as exc:  # pragma: no cover - assertion detail
            self.fail(f"validator did not return structured JSON: {exc}\nstdout={result.stdout!r}\nstderr={result.stderr!r}")
        self.assertEqual(report.get("validator"), "claims")
        return result, report

    @staticmethod
    def codes(report: dict[str, Any]) -> set[str]:
        return {item.get("code") for item in report.get("findings", []) if isinstance(item, dict)}

    def assert_contract_failure(self, result: subprocess.CompletedProcess[str], report: dict[str, Any], code: str) -> None:
        self.assertEqual(result.returncode, 1)
        self.assertEqual(report.get("status"), "failed")
        self.assertIn(code, self.codes(report))

    def test_valid_claim_contract_passes(self) -> None:
        result, report = self.run_validator()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(report.get("status"), "passed")

    def test_future_source_retrieval_is_rejected(self) -> None:
        source = valid_source()
        source["retrieved_at"] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat().replace("+00:00", "Z")
        result, report = self.run_validator(sources=[source])
        self.assert_contract_failure(result, report, "SOURCE_RETRIEVED_AT_FUTURE")

    def test_source_timestamp_rejects_non_rfc3339_separator(self) -> None:
        source = valid_source()
        source["retrieved_at"] = source["retrieved_at"].replace("T", "\n")
        result, report = self.run_validator(sources=[source])
        self.assert_contract_failure(result, report, "SOURCE_RETRIEVED_AT_INVALID")

    def test_direct_validator_rejects_ymyl_enum_bypasses(self) -> None:
        invalid_values: list[Any] = [None, 0, 1, "true", "false", [], {}]
        for value in invalid_values:
            with self.subTest(value=value):
                manifest = valid_manifest()
                manifest["risk"]["ymyl"] = value
                result, report = self.run_validator(manifest=manifest)
                self.assert_contract_failure(result, report, "MANIFEST_YMYL_INVALID")

    def test_direct_validator_accepts_only_exact_ymyl_contract_values(self) -> None:
        for value in (True, False, "auto"):
            with self.subTest(value=value):
                manifest = valid_manifest()
                manifest["risk"]["ymyl"] = value
                result, report = self.run_validator(manifest=manifest)
                self.assertEqual(result.returncode, 0, report)
                self.assertEqual(report.get("status"), "passed")

    def test_direct_validator_rejects_invalid_manifest_identity_types_and_lengths(self) -> None:
        cases = (
            ("run_id", 7, "MANIFEST_RUN_ID_INVALID"),
            ("run_id", "short", "MANIFEST_RUN_ID_INVALID"),
            ("target", [], "MANIFEST_TARGET_INVALID"),
            ("target", "", "MANIFEST_TARGET_INVALID"),
            ("language", False, "MANIFEST_LANGUAGE_INVALID"),
            ("language", "e", "MANIFEST_LANGUAGE_INVALID"),
        )
        for field, value, code in cases:
            with self.subTest(field=field, value=value):
                manifest = valid_manifest()
                manifest[field] = value
                result, report = self.run_validator(manifest=manifest)
                self.assert_contract_failure(result, report, code)

    def test_direct_validator_rejects_noncanonical_run_ids(self) -> None:
        for value in (
            "run-good\nspoof",
            " run-good",
            "run/good",
            "a" * 129,
            "\u0437\u0430\u043f\u0443\u0441\u043a-0001",
        ):
            with self.subTest(value=repr(value)):
                manifest = valid_manifest()
                manifest["run_id"] = value
                result, report = self.run_validator(manifest=manifest)
                self.assert_contract_failure(result, report, "MANIFEST_RUN_ID_INVALID")

    def test_actor_aliases_cannot_self_verify_or_bypass_verifier_role_binding(self) -> None:
        for alias in (
            " WRITER-PASS ",
            "\uff37\uff32\uff29\uff34\uff25\uff32-pass",
            "writer\u200d-pass",
            "writer\ufe0f-pass",
            "writer\u034f-pass",
            "writer\u115f-pass",
            "writer\u3164-pass",
        ):
            with self.subTest(alias=repr(alias)):
                claim = valid_claim()
                claim["verifier"] = alias
                result, report = self.run_validator(claims=[claim])
                codes = self.codes(report)
                self.assertEqual(result.returncode, 1, report)
                self.assertTrue(
                    {"CLAIM_SELF_VERIFIED", "CLAIM_VERIFIER_IDENTITY_INVALID"} & codes,
                    report,
                )

        claim = valid_claim()
        claim["verifier"] = "different-independent-person"
        result, report = self.run_validator(claims=[claim])
        self.assert_contract_failure(result, report, "CLAIM_VERIFIER_ROLE_MISMATCH")

    def test_manifest_actor_roles_reject_default_ignorables(self) -> None:
        for character in (
            "\u200d", "\ufe0f", "\u034f", "\u115f", "\u3164",
            "\u180b", "\u180c", "\u180d", "\u180f", "\u2065",
            "\ufff0", "\ufff8", "\U000e0000",
        ):
            with self.subTest(character=f"U+{ord(character):04X}"):
                manifest = valid_manifest()
                manifest["roles"]["verifier"] = f"verifier{character}-pass"
                result, report = self.run_validator(manifest=manifest)
                self.assert_contract_failure(result, report, "MANIFEST_ROLE_INVALID")

    def test_source_ids_and_supported_claim_ids_are_typed_patterned_and_unique(self) -> None:
        source = valid_source()
        source["source_id"] = "bad source id"
        source["supported_claim_ids"] = ["C1", "C1", 7, None, {}, "bad claim id"]
        claim = valid_claim()
        claim["source_ids"] = ["bad source id"]
        result, report = self.run_validator(sources=[source], claims=[claim])
        codes = self.codes(report)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(report.get("status"), "failed")
        self.assertIn("ID_FORMAT_INVALID", codes)
        self.assertIn("SOURCE_SUPPORTED_CLAIM_IDS_ITEM_INVALID", codes)
        self.assertIn("SOURCE_SUPPORTED_CLAIM_IDS_DUPLICATE", codes)
        self.assertIn("CLAIM_SOURCE_IDS_ITEM_INVALID", codes)

    def test_claim_and_source_evidence_edges_must_be_exactly_reciprocal(self) -> None:
        source = valid_source()
        source["supported_claim_ids"] = []
        result, report = self.run_validator(sources=[source])
        self.assert_contract_failure(result, report, "CLAIM_SOURCE_LINK_MISSING")

        source = valid_source()
        source["supported_claim_ids"] = ["C1", "C404"]
        result, report = self.run_validator(sources=[source])
        self.assert_contract_failure(result, report, "SOURCE_CLAIM_UNKNOWN")

        source = valid_source()
        claim = valid_claim()
        claim["source_ids"] = []
        result, report = self.run_validator(sources=[source], claims=[claim])
        self.assert_contract_failure(result, report, "SOURCE_CLAIM_LINK_MISSING")

        source = valid_source()
        source.pop("supported_claim_ids")
        result, report = self.run_validator(sources=[source])
        self.assert_contract_failure(result, report, "SOURCE_FIELDS_MISSING")

    def test_claim_type_cannot_downgrade_factual_evidence_obligations(self) -> None:
        mismatches = (
            ("opinion", "factual"),
            ("inference", "numeric"),
            ("load-bearing", "opinion"),
            ("supporting", "inference"),
        )
        for classification, claim_type in mismatches:
            with self.subTest(classification=classification, claim_type=claim_type):
                claim = valid_claim()
                claim["classification"] = classification
                claim["claim_type"] = claim_type
                if classification in {"opinion", "inference"}:
                    claim.update(
                        {
                            "source_ids": [],
                            "support_status": "not-applicable",
                            "freshness_status": "not-applicable",
                            "exact_support": None,
                            "verifier": None,
                        }
                    )
                    source = valid_source()
                    source["supported_claim_ids"] = []
                else:
                    source = valid_source()
                result, report = self.run_validator(sources=[source], claims=[claim])
                self.assert_contract_failure(result, report, "CLAIM_TYPE_CLASSIFICATION_MISMATCH")

    def test_claim_ids_and_source_id_arrays_fail_closed_without_type_coercion(self) -> None:
        claim = valid_claim()
        claim["claim_id"] = {"looks": "truthy"}
        claim["source_ids"] = ["S1", "S1", 1, None, {}, []]
        result, report = self.run_validator(claims=[claim])
        codes = self.codes(report)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(report.get("status"), "failed")
        self.assertIn("ID_TYPE_INVALID", codes)
        self.assertIn("CLAIM_SOURCE_IDS_ITEM_INVALID", codes)
        self.assertIn("CLAIM_SOURCE_IDS_DUPLICATE", codes)
        self.assertNotIn("VALIDATOR_INTERNAL_ERROR", codes)

    def test_material_claim_fields_require_exact_schema_types(self) -> None:
        claim = valid_claim()
        claim.update(
            {
                "text": ["not", "a", "string"],
                "location": True,
                "classification": {"looks": "load-bearing"},
                "claim_type": ["factual"],
                "support_status": {"state": "verified"},
                "freshness_status": 1,
                "exact_support": {"quote": "not a string"},
                "verifier": 9,
                "resolution": ["approved"],
                "as_of": False,
            }
        )
        result, report = self.run_validator(claims=[claim])
        codes = self.codes(report)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(report.get("status"), "failed")
        self.assertIn("CLAIM_FIELD_INVALID", codes)
        self.assertIn("CLAIM_FIELD_TYPE_INVALID", codes)
        self.assertIn("CLAIM_CLASS_INVALID", codes)
        self.assertIn("CLAIM_TYPE_INVALID", codes)
        self.assertIn("CLAIM_STATUS_INVALID", codes)
        self.assertIn("CLAIM_FRESHNESS_INVALID", codes)
        self.assertNotIn("VALIDATOR_INTERNAL_ERROR", codes)

    def test_source_required_text_rejects_whitespace_and_unicode_invisibles(self) -> None:
        non_substantive_values = (
            "",
            " \t\r\n",
            "\u200b",
            "\u200b\u2060\ufeff",
            "\x00\x1f\x7f",
            "\u0301\ufe0f",
            "\u115f",
            "\u2800",
            "\ud800",
        )
        for field in ("title", "locator", "publisher"):
            for value in non_substantive_values:
                with self.subTest(field=field, value=repr(value)):
                    source = valid_source()
                    source[field] = value
                    result, report = self.run_validator(sources=[source])
                    self.assert_contract_failure(result, report, "SOURCE_FIELD_INVALID")

    def test_punctuation_and_symbol_only_source_evidence_is_rejected(self) -> None:
        for field in ("title", "locator", "publisher", "author", "notes"):
            for value in ("...", "---", "✓", "🔥", "— § /", "\u200b✓\u2060"):
                with self.subTest(field=field, value=value):
                    source = valid_source()
                    source[field] = value
                    result, report = self.run_validator(sources=[source])
                    self.assert_contract_failure(result, report, "SOURCE_FIELD_INVALID")

        source = valid_source()
        source["known_conflicts"] = ["?!"]
        result, report = self.run_validator(sources=[source])
        self.assert_contract_failure(result, report, "SOURCE_KNOWN_CONFLICTS_ITEM_INVALID")

    def test_claim_required_text_rejects_whitespace_and_unicode_invisibles(self) -> None:
        non_substantive_values = (" \t\n", "\u200b", "\u200b\u2060", "\x00\x1f", "\u0301\ufe0f", "\u3164", "\ud800")
        for field in ("text", "location", "resolution"):
            for value in non_substantive_values:
                with self.subTest(field=field, value=repr(value)):
                    claim = valid_claim()
                    claim[field] = value
                    result, report = self.run_validator(claims=[claim])
                    self.assert_contract_failure(result, report, "CLAIM_FIELD_INVALID")

    def test_ledgers_reject_embedded_bidi_and_zero_width_controls(self) -> None:
        mutations = (
            ("claim-text", "claim", "text", "safe\u202eevil"),
            ("claim-support", "claim", "exact_support", "safe\u2066hidden"),
            ("claim-joiner", "claim", "text", "safe\u200deffect"),
            ("source-locator", "source", "locator", "https://example.test/\u202eevil"),
        )
        for name, record_type, field, value in mutations:
            with self.subTest(name=name):
                source = valid_source()
                claim = valid_claim()
                if record_type == "claim":
                    claim[field] = value
                else:
                    source[field] = value
                result, report = self.run_validator(sources=[source], claims=[claim])
                self.assert_contract_failure(result, report, "LEDGER_UNICODE_CONTROL_INVALID")

    def test_material_exact_support_and_verifier_reject_invisible_only_text(self) -> None:
        non_substantive_values = (" \t\n", "\u200b", "\u200b\u2060\ufeff", "\x00\x7f", "\u0301", "\uffa0", "\ud800")
        expected_material_code = {
            "exact_support": "MATERIAL_EXACT_SUPPORT_MISSING",
            "verifier": "CLAIM_VERIFIER_MISSING",
        }
        for field in ("exact_support", "verifier"):
            for value in non_substantive_values:
                with self.subTest(field=field, value=repr(value)):
                    claim = valid_claim()
                    claim[field] = value
                    result, report = self.run_validator(claims=[claim])
                    self.assertEqual(result.returncode, 1)
                    codes = self.codes(report)
                    self.assertIn("CLAIM_FIELD_NOT_SUBSTANTIVE", codes)
                    self.assertIn(expected_material_code[field], codes)
                    self.assertNotIn("VALIDATOR_INTERNAL_ERROR", codes)

    def test_punctuation_and_symbol_only_claim_evidence_is_rejected(self) -> None:
        for field in ("text", "location", "resolution"):
            with self.subTest(field=field):
                claim = valid_claim()
                claim[field] = "... ✓ 🔥"
                result, report = self.run_validator(claims=[claim])
                self.assert_contract_failure(result, report, "CLAIM_FIELD_INVALID")

        expected_material_code = {
            "exact_support": "MATERIAL_EXACT_SUPPORT_MISSING",
            "verifier": "CLAIM_VERIFIER_MISSING",
        }
        for field, expected_code in expected_material_code.items():
            with self.subTest(field=field):
                claim = valid_claim()
                claim[field] = "— § ✓"
                result, report = self.run_validator(claims=[claim])
                self.assertEqual(result.returncode, 1)
                codes = self.codes(report)
                self.assertIn("CLAIM_FIELD_NOT_SUBSTANTIVE", codes)
                self.assertIn(expected_code, codes)

    def test_visible_multilingual_text_passes(self) -> None:
        manifest = valid_manifest()
        manifest["roles"]["verifier"] = "Проверяющий"
        source = valid_source()
        source.update(
            {
                "title": "Официальный источник",
                "locator": "urn:источник",
                "publisher": "出版者",
            }
        )
        claim = valid_claim()
        claim.update(
            {
                "text": "هذا ادعاء موثق",
                "location": "Раздел",
                "exact_support": "Проверено ✓",
                "verifier": "Проверяющий",
                "resolution": "承認済み",
            }
        )
        result, report = self.run_validator(manifest=manifest, sources=[source], claims=[claim])
        self.assertEqual(result.returncode, 0, report)
        self.assertEqual(report.get("status"), "passed")

    def test_checked_schemas_encode_the_same_id_and_material_constraints(self) -> None:
        article_schema = json.loads((SKILL_ROOT / "schemas/article-manifest.schema.json").read_text(encoding="utf-8"))
        source_schema = json.loads((SKILL_ROOT / "schemas/source.schema.json").read_text(encoding="utf-8"))
        claim_schema = json.loads((SKILL_ROOT / "schemas/claim.schema.json").read_text(encoding="utf-8"))

        self.assertEqual(article_schema["properties"]["risk"]["properties"]["ymyl"]["enum"], ["auto", True, False])
        supported = source_schema["properties"]["supported_claim_ids"]
        self.assertIn("supported_claim_ids", source_schema["required"])
        self.assertTrue(supported["uniqueItems"])
        self.assertEqual(supported["items"]["pattern"], "^[A-Za-z0-9._-]+$")
        source_ids = claim_schema["properties"]["source_ids"]
        self.assertTrue(source_ids["uniqueItems"])
        self.assertEqual(source_ids["items"]["pattern"], "^[A-Za-z0-9._-]+$")
        material_then = claim_schema["allOf"][0]["then"]
        self.assertIn("verifier", material_then["required"])
        self.assertEqual(material_then["properties"]["verifier"]["$ref"], "#/$defs/actor_identity")

        def substantive_definition(schema: dict[str, object], node: dict[str, object]) -> dict[str, object]:
            if "$ref" in node:
                return schema["$defs"][str(node["$ref"]).rsplit("/", 1)[-1]]  # type: ignore[index]
            for option in node.get("oneOf", []):  # type: ignore[union-attr]
                if isinstance(option, dict) and "$ref" in option:
                    return schema["$defs"][str(option["$ref"]).rsplit("/", 1)[-1]]  # type: ignore[index]
            return node

        for field in ("title", "locator", "publisher"):
            definition = substantive_definition(source_schema, source_schema["properties"][field])
            self.assertTrue(definition["x-unicode-substantive"])
            self.assertTrue(definition["x-unicode-letter-or-number"])
            self.assertEqual(definition["pattern"], "\\S")
        for field in ("text", "location", "resolution", "exact_support"):
            definition = substantive_definition(claim_schema, claim_schema["properties"][field])
            self.assertTrue(definition["x-unicode-substantive"])
            self.assertTrue(definition["x-unicode-letter-or-number"])
            self.assertEqual(definition["pattern"], "\\S")
        self.assertEqual(claim_schema["properties"]["verifier"]["oneOf"][0]["$ref"], "#/$defs/actor_identity")
        self.assertTrue(claim_schema["$defs"]["actor_identity"]["x-unicode-substantive"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
