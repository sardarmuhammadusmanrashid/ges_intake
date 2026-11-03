"""Entry point: python -m ges_intake --library DIR --clients DIR run --client ID --inbox DIR [--inbox DIR ...] --as-of DATE --outbox FILE

The argument parsing and output format below are provided so you can spend your time on the
engine. Everything else (modules, classes, how the stages fit together) is your design.
Exit codes: 0 success, 2 bad input / bad library / unknown client.
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from .classification import classify_document, normalize_text
from .config import load_configuration, load_json
from .extraction import extract_fields
from .governance import govern_document, redact_for_advisory
from .intake import validate_file
from .readiness import build_attention, evaluate_readiness
from vendor.advisory_stub import request_suggestion


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="ges_intake")
    p.add_argument("--library", required=True)
    p.add_argument("--clients", required=True)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--client", required=True)
    r.add_argument("--inbox", required=True, action="append", help="repeatable; processed in the given order")
    r.add_argument("--as-of", required=True, type=date.fromisoformat)
    r.add_argument("--outbox", required=True, help="file the advisory stub appends to")
    return p.parse_args(argv)


def run(args) -> dict:
    """Ingest every inbox in order, then evaluate readiness. Return the report described in TASK.md §3."""
    client_id = args.client
    if not isinstance(client_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", client_id):
        raise ValueError("invalid client ID")

    configuration = load_configuration(Path(args.library))
    clients_dir = Path(args.clients).resolve()
    client_path = (clients_dir / f"{client_id}.json").resolve()
    if client_path.parent != clients_dir:
        raise ValueError("invalid client ID")
    client = load_json(client_path)
    if not isinstance(client, dict) or client.get("client_id") != client_id:
        raise ValueError("client profile ID does not match")
    engagement = client.get("engagement")
    if (
        not isinstance(client.get("name"), str)
        or not isinstance(client.get("ssn"), str)
        or not isinstance(client.get("accounts"), list)
        or not isinstance(engagement, dict)
        or not isinstance(engagement.get("service"), str)
    ):
        raise ValueError("malformed client profile")
    try:
        engagement_start = date.fromisoformat(engagement["period_start"])
        engagement_end = date.fromisoformat(engagement["period_end"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("malformed client engagement period") from error
    if engagement_end < engagement_start:
        raise ValueError("invalid client engagement period")
    service_id = engagement["service"]
    service = next(
        (item for item in configuration["services"].get("services", [])
         if item.get("id") == service_id),
        None,
    )
    if service is None:
        raise ValueError(f"unknown service in client profile: {service_id}")

    inboxes = []
    for inbox_arg in args.inbox:
        inbox = Path(inbox_arg).resolve()
        manifest_path = inbox / "manifest.json"
        manifest = load_json(manifest_path)
        if (not isinstance(manifest, dict)
                or not isinstance(manifest.get("entries"), list)
                or manifest.get("client_id") != client_id
                or not isinstance(manifest.get("batch_id"), str)
                or not manifest["batch_id"]):
            raise ValueError(f"malformed manifest for inbox: {inbox}")
        inboxes.append((inbox, manifest))

    # Validate all batch manifests before the advisory outbox can be modified.
    documents_by_id = {}
    batch_reports = []
    document_types = configuration["document_types"].get("document_types")
    if not isinstance(document_types, list):
        raise ValueError("invalid document types configuration")
    document_types_by_id = {item["id"]: item for item in document_types}
    for inbox, manifest in inboxes:
        entries = manifest["entries"]
        valid_entries = []
        invalid_entries = []
        for entry in entries:
            if not isinstance(entry, dict):
                entry = {}
            source = entry.get("file")
            source_key = source if isinstance(source, str) else ""
            received_at = entry.get("received_at")
            parsed_at = _parse_received_at(received_at)
            if parsed_at is None:
                invalid_entries.append((source_key, entry))
            else:
                valid_entries.append((parsed_at, source_key, entry))
        ordered_entries = [
            item[2] for item in sorted(valid_entries, key=lambda item: (item[0], item[1]))
        ] + [item[1] for item in sorted(invalid_entries, key=lambda item: item[0])]

        referenced = {
            entry.get("file") for entry in entries
            if isinstance(entry, dict) and isinstance(entry.get("file"), str)
        }
        ignored = sorted(
            item.name for item in inbox.iterdir()
            if item.name != "manifest.json" and item.is_file() and item.name not in referenced
        )
        batch_report = {
            "batch_id": manifest["batch_id"],
            "client_id": client_id,
            "documents": [],
            "duplicates": [],
            "rejected": [],
            "ignored": ignored,
        }
        for entry in ordered_entries:
            source = entry.get("file")
            source = source if isinstance(source, str) else ""
            received_at = _parse_received_at(entry.get("received_at"))
            if received_at is None:
                batch_report["rejected"].append(
                    {"source": source, "reason": "invalid_timestamp"}
                )
                continue
            channel = entry.get("channel")
            if channel not in configuration["intake_policy"].get("channels", []):
                batch_report["rejected"].append(
                    {"source": source, "reason": "invalid_channel"}
                )
                continue

            result = validate_file(inbox, entry, configuration["intake_policy"])
            if result["status"] == "rejected":
                batch_report["rejected"].append(
                    {"source": source, "reason": result["reason"]}
                )
                continue

            document_id = "DOC-" + hashlib.sha256(
                f"{client_id}:{result['sha256']}".encode("utf-8")
            ).hexdigest()[:12]
            if document_id in documents_by_id:
                batch_report["duplicates"].append(
                    {"source": source, "document_id": document_id}
                )
                continue

            normalized_text = normalize_text(result["text"])
            classification = classify_document(normalized_text, document_types)
            flags = set(classification["flags"])
            phrase_view = re.sub(r"\s+", " ", normalized_text.casefold())
            for suspicious_pattern in configuration["intake_policy"].get(
                "suspicious_instruction_patterns", []
            ):
                if re.search(suspicious_pattern, phrase_view, re.IGNORECASE):
                    flags.add("suspicious_instructions")

            document_type = document_types_by_id.get(classification["doc_type"])
            extracted_fields = {}
            provenance = grade = None
            status = "pending_review"
            suggestion = None
            if document_type is not None:
                extracted_fields, extraction_flags, transient = extract_fields(
                    normalized_text, document_type
                )
                governed = govern_document(
                    extracted_fields,
                    transient,
                    document_type,
                    client,
                    channel,
                    sorted(flags.union(extraction_flags)),
                    configuration["intake_policy"],
                )
                extracted_fields = governed["fields"]
                flags = set(governed["flags"])
                provenance = governed["provenance"]
                grade = governed["grade"]
                status = governed["status"]
            else:
                suggestion = request_suggestion(
                    redact_for_advisory(normalized_text), args.outbox
                )

            document = {
                "document_id": document_id,
                "source": source,
                "doc_type": classification["doc_type"],
                "cel": classification["cel"],
                "provenance": provenance,
                "grade": grade,
                "status": status,
                "flags": sorted(flags),
                "fields": extracted_fields,
                "received_at": received_at.isoformat(),
                "_base_status": status,
                "_supersede_values": _supersede_values(
                    document_type, extracted_fields, transient
                ) if document_type is not None else {},
            }
            if suggestion is not None:
                document["suggestion"] = suggestion
            documents_by_id[document_id] = document
            batch_report["documents"].append({
                key: value for key, value in document.items()
                if key not in {"received_at", "suggestion"}
                and not key.startswith("_")
            })
        _apply_supersession(documents_by_id, document_types_by_id)
        for item in batch_report["documents"]:
            item["status"] = documents_by_id[item["document_id"]]["status"]
        batch_reports.append(batch_report)

    readiness_documents = [
        {
            key: value for key, value in document.items()
            if key not in {"source", "_base_status", "_supersede_values"}
        }
        for document in documents_by_id.values()
    ]
    readiness = evaluate_readiness(
        client, service, configuration["cel"], readiness_documents, args.as_of
    )
    attention = build_attention(
        readiness, service, configuration["cel"], readiness_documents
    )
    return {
        "client_id": client_id,
        "as_of": args.as_of.isoformat(),
        "batches": batch_reports,
        "documents": [
            {"document_id": document_id, "status": document["status"]}
            for document_id, document in sorted(documents_by_id.items())
        ],
        "readiness": readiness,
        "attention": attention,
    }


def _parse_received_at(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _apply_supersession(documents_by_id: dict, document_types_by_id: dict) -> None:
    for document in documents_by_id.values():
        document["status"] = document["_base_status"]

    documents = list(documents_by_id.values())
    for newer in documents:
        if newer["status"] == "quarantined" or newer["doc_type"] is None:
            continue
        supersede = document_types_by_id[newer["doc_type"]].get("supersede")
        if not supersede:
            continue
        newer_at = _parse_received_at(newer["received_at"])
        key_fields = supersede.get("key", [])
        if any(not _has_field(newer, key) for key in key_fields):
            continue
        for older in documents:
            if older is newer or older["status"] == "quarantined":
                continue
            if older["doc_type"] not in supersede.get("supersedes", []):
                continue
            if any(not _has_field(older, key) for key in key_fields):
                continue
            if any(
                _field_value(newer, key) != _field_value(older, key)
                for key in key_fields
            ):
                continue
            older_at = _parse_received_at(older["received_at"])
            if (newer_at, newer["document_id"]) > (older_at, older["document_id"]):
                older["status"] = "superseded"


def _has_field(document: dict, name: str) -> bool:
    return name in document.get("fields", {}) or name in document.get(
        "_supersede_values", {}
    )


def _field_value(document: dict, name: str):
    return document.get("_supersede_values", {}).get(
        name, document.get("fields", {}).get(name)
    )


def _supersede_values(document_type: dict, fields: dict, transient: dict) -> dict:
    supersede = document_type.get("supersede", {})
    keys = supersede.get("key", [])
    return {
        key: transient.get(key, fields.get(key))
        for key in keys
        if transient.get(key, fields.get(key)) is not None
    }


def main(argv=None) -> int:
    try:
        args = parse_args(argv)
        report = run(args)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        sys.stderr.write(f"ges_intake: {error}\n")
        return 2
    sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
