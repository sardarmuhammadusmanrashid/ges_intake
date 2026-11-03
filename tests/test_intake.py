import contextlib
import io
import json
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from ges_intake.__main__ import main, run
from ges_intake.config import load_configuration, validate_configuration
from ges_intake.extraction import extract_fields
from ges_intake.governance import redact_for_advisory


ROOT = Path(__file__).resolve().parents[1]


class IntakePipelineTests(unittest.TestCase):
    def test_day_one_fixture_counts_and_readiness(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            report = run(SimpleNamespace(
                library=str(ROOT / "library"),
                clients=str(ROOT / "clients"),
                client="C-1001",
                inbox=[str(ROOT / "inbox" / "day1")],
                as_of=date(2026, 3, 1),
                outbox=str(Path(temporary_directory) / "outbox.jsonl"),
            ))

        batch = report["batches"][0]
        self.assertEqual(len(batch["documents"]), 20)
        self.assertEqual(len(batch["duplicates"]), 1)
        self.assertEqual(len(batch["rejected"]), 8)
        self.assertEqual(len(batch["ignored"]), 1)
        self.assertEqual(report["readiness"]["status"], "BLOCKED")
        self.assertEqual(
            [pda["status"] for pda in report["readiness"]["pdas"]],
            [
                "SATISFIED",
                "MISSING",
                "MISSING",
                "PENDING_REVIEW",
                "BLOCKED_BY_DEPENDENCY",
            ],
        )

    def test_advisory_outbox_contains_no_fixture_identifiers(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            outbox = Path(temporary_directory) / "outbox.jsonl"
            run(SimpleNamespace(
                library=str(ROOT / "library"),
                clients=str(ROOT / "clients"),
                client="C-1001",
                inbox=[str(ROOT / "inbox" / "day1")],
                as_of=date(2026, 3, 1),
                outbox=str(outbox),
            ))
            payload = outbox.read_text(encoding="utf-8")

        for identifier in ("900-12-3456", "900-98-7654", "58-7654321", "0004 5512 4821"):
            self.assertNotIn(identifier, payload)

    def test_report_is_deterministic_and_does_not_persist_full_identifiers(self):
        reports = []
        with tempfile.TemporaryDirectory() as temporary_directory:
            for index in range(2):
                reports.append(run(SimpleNamespace(
                    library=str(ROOT / "library"),
                    clients=str(ROOT / "clients"),
                    client="C-1001",
                    inbox=[str(ROOT / "inbox" / "day1")],
                    as_of=date(2026, 3, 1),
                    outbox=str(Path(temporary_directory) / f"outbox-{index}.jsonl"),
                )))

        self.assertEqual(reports[0], reports[1])
        report_text = json.dumps(reports[0])
        for identifier in (
            "900-12-3456",
            "900-98-7654",
            "58-1234567",
            "900123456",
            "581234567",
            "0571 2290 4410",
            "5512 90871",
            "0004 5512 4821",
        ):
            self.assertNotIn(identifier, report_text)

    def test_date_range_required_field_uses_derived_fields(self):
        document_type = {
            "fields": {
                "period": {
                    "pattern": r"^Period:\s*(.+?)\s+to\s+(.+)$",
                    "type": "date_range",
                }
            },
            "required_fields": ["period"],
        }
        fields, flags, _ = extract_fields(
            "Period: 2025-01-01 to 2025-01-31", document_type
        )
        self.assertEqual(fields, {
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
        })
        self.assertNotIn("missing_required_field", flags)

    def test_day_two_supersedes_versions_and_reports_balance_issue(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            report = run(SimpleNamespace(
                library=str(ROOT / "library"),
                clients=str(ROOT / "clients"),
                client="C-1001",
                inbox=[str(ROOT / "inbox" / "day1"), str(ROOT / "inbox" / "day2")],
                as_of=date(2026, 3, 3),
                outbox=str(Path(temporary_directory) / "outbox.jsonl"),
            ))

        self.assertEqual(
            sum(document["status"] == "superseded" for document in report["documents"]),
            2,
        )
        self.assertEqual(report["readiness"]["pdas"][1]["status"], "SATISFIED")
        bank_pda = report["readiness"]["pdas"][2]
        self.assertEqual(bank_pda["status"], "PENDING_REVIEW")
        self.assertIn(
            "balance_discontinuity:9930:2025-05-01",
            bank_pda["issues"],
        )

    def test_invalid_dependency_cycle_is_rejected(self):
        configuration = load_configuration(ROOT / "library")
        configuration["services"]["services"][0]["pdas"][0]["depends_on"] = [
            "PDA-A02"
        ]
        configuration["services"]["services"][0]["pdas"][1]["depends_on"] = [
            "PDA-A01"
        ]
        with self.assertRaisesRegex(ValueError, "dependency cycle"):
            validate_configuration(configuration)

    def test_invalid_library_exits_two_without_stdout(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            library = Path(temporary_directory) / "library"
            shutil.copytree(ROOT / "library", library)
            services_path = library / "services.json"
            services = json.loads(services_path.read_text(encoding="utf-8"))
            services["services"][0]["pdas"][0]["pathways"][0]["requirements"][0][
                "cel"
            ] = "CEL-DOES-NOT-EXIST"
            services_path.write_text(json.dumps(services), encoding="utf-8")

            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main([
                    "--library", str(library),
                    "--clients", str(ROOT / "clients"),
                    "run",
                    "--client", "C-1001",
                    "--inbox", str(ROOT / "inbox" / "day1"),
                    "--as-of", "2026-03-01",
                    "--outbox", str(Path(temporary_directory) / "outbox.jsonl"),
                ])

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("unknown CEL", stderr.getvalue())

    def test_advisory_redacts_short_account_and_document_identifier_labels(self):
        redacted = redact_for_advisory(
            "Account Number: 4821\nLicense No: 0571 2290 4410\n"
            "Employer EIN: 58-1234567\n"
        )
        for value in ("4821", "0571 2290 4410", "58-1234567"):
            self.assertNotIn(value, redacted)

    def test_attention_client_view_has_no_internal_keys_or_codes(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            report = run(SimpleNamespace(
                library=str(ROOT / "library"),
                clients=str(ROOT / "clients"),
                client="C-1001",
                inbox=[str(ROOT / "inbox" / "day1")],
                as_of=date(2026, 3, 1),
                outbox=str(Path(temporary_directory) / "outbox.jsonl"),
            ))

        client_items = report["attention"]["client"]
        self.assertTrue(client_items)
        self.assertTrue(all("key" not in item for item in client_items))
        client_text = str(client_items)
        for internal_code in ("PDA-", "CEL-", "DOC-", "DT-", "quarantin"):
            self.assertNotIn(internal_code, client_text)
        self.assertIn("account ending in 4821", client_text)


if __name__ == "__main__":
    unittest.main()
