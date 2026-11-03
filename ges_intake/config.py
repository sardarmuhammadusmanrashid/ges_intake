
import json
import re
from pathlib import Path


def load_json(path: Path) -> dict:
    """Load a JSON configuration file."""
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_configuration(library_dir: Path) -> dict:
    """Load the evidence library and service definitions."""
    configuration = {
        "cel": load_json(library_dir / "cel.json"),
        "document_types": load_json(library_dir / "document_types.json"),
        "services": load_json(library_dir / "services.json"),
        "intake_policy": load_json(library_dir / "intake_policy.json"),
    }
    validate_configuration(configuration)
    return configuration


def validate_configuration(configuration: dict) -> None:
    for key in ("cel", "document_types", "services", "intake_policy"):
        if not isinstance(configuration.get(key), dict):
            raise ValueError(f"invalid {key} configuration")
    cel_library = configuration["cel"]
    cel_entries = cel_library.get("cel")
    document_types = configuration["document_types"].get("document_types")
    services = configuration["services"].get("services")
    policy = configuration["intake_policy"]
    if not isinstance(cel_library.get("library_version"), str):
        raise ValueError("invalid CEL library version")
    if not isinstance(cel_entries, list) or not isinstance(document_types, list):
        raise ValueError("invalid CEL or document type list")
    if not isinstance(services, list):
        raise ValueError("invalid services list")

    cel_ids = _unique_ids(cel_entries, "CEL")
    type_ids = _unique_ids(document_types, "document type")
    service_ids = _unique_ids(services, "service")
    if not cel_ids or not type_ids or not service_ids:
        raise ValueError("library lists must not be empty")

    for cel in cel_entries:
        if not isinstance(cel, dict):
            raise ValueError("invalid CEL entry")
        currentness = cel.get("currentness")
        if (
            not isinstance(cel.get("allowed_provenance"), list)
            or not set(cel["allowed_provenance"]).issubset({"P1", "P2", "P3", "P4"})
        ):
            raise ValueError(f"invalid allowed provenance for CEL {cel['id']}")
        if cel.get("criticality") not in {"C1", "C2", "C3", "C4"}:
            raise ValueError(f"invalid criticality for CEL {cel['id']}")
        if not isinstance(currentness, dict) or currentness.get("rule") not in {
            "none", "not_expired", "tax_year", "period_overlap"
        }:
            raise ValueError(f"invalid currentness rule for CEL {cel['id']}")
        if currentness.get("rule") == "tax_year" and not isinstance(
            currentness.get("offset"), int
        ):
            raise ValueError(f"invalid tax year offset for CEL {cel['id']}")

    for document_type in document_types:
        if not isinstance(document_type, dict):
            raise ValueError("invalid document type entry")
        if document_type.get("cel") not in cel_ids:
            raise ValueError(f"unknown CEL in document type {document_type['id']}")
        match = document_type.get("match")
        if not isinstance(match, dict) or not all(
            isinstance(match.get(key), list)
            and all(isinstance(phrase, str) for phrase in match[key])
            for key in ("all", "none")
        ):
            raise ValueError(f"invalid match rules for document type {document_type['id']}")
        provenance = document_type.get("provenance")
        if not isinstance(provenance, dict) or not isinstance(provenance.get("default"), str):
            raise ValueError(f"invalid provenance for document type {document_type['id']}")
        by_channel = provenance.get("by_channel", {})
        if not isinstance(by_channel, dict):
            raise ValueError(f"invalid channel provenance for document type {document_type['id']}")
        if not set([provenance["default"], *by_channel.values()]).issubset(
            {"P1", "P2", "P3", "P4"}
        ):
            raise ValueError(f"invalid provenance code for document type {document_type['id']}")
        fields = document_type.get("fields")
        if not isinstance(fields, dict):
            raise ValueError(f"invalid fields for document type {document_type['id']}")
        for field_name, specification in fields.items():
            if not isinstance(specification, dict):
                raise ValueError(
                    f"invalid field specification for {document_type['id']}.{field_name}"
                )
            try:
                pattern = re.compile(
                    specification["pattern"], re.MULTILINE | re.IGNORECASE
                )
            except (KeyError, TypeError, re.error) as error:
                raise ValueError(
                    f"invalid pattern for {document_type['id']}.{field_name}"
                ) from error
            field_type = specification.get("type")
            if field_type not in {
                "text", "date", "date_range", "money", "year",
                "ssn", "ein", "account",
            }:
                raise ValueError(
                    f"invalid field type for {document_type['id']}.{field_name}"
                )
            expected_groups = 2 if field_type == "date_range" else 1
            if pattern.groups != expected_groups:
                raise ValueError(
                    f"invalid capture groups for {document_type['id']}.{field_name}"
                )
        identity = document_type.get("identity", {})
        if not isinstance(identity, dict) or not set(identity.values()).issubset(fields):
            raise ValueError(f"unknown identity field in {document_type['id']}")
        required_fields = document_type.get("required_fields", [])
        if not isinstance(required_fields, list) or not set(required_fields).issubset(fields):
            raise ValueError(f"unknown required field in {document_type['id']}")
        supersede = document_type.get("supersede")
        if supersede:
            if not isinstance(supersede, dict) or not isinstance(
                supersede.get("key"), list
            ) or not isinstance(supersede.get("supersedes"), list):
                raise ValueError(f"invalid supersession rule in {document_type['id']}")
            unknown_types = set(supersede.get("supersedes", [])) - type_ids
            if unknown_types:
                raise ValueError(
                    f"unknown superseded document type in {document_type['id']}"
                )
            unknown_keys = set(supersede.get("key", [])) - (
                set(fields) | {
                    field_name + suffix
                    for field_name, spec in fields.items()
                    if spec["type"] == "date_range"
                    for suffix in ("_start", "_end")
                }
            )
            if unknown_keys:
                raise ValueError(f"unknown supersession key in {document_type['id']}")

    pda_ids = set()
    for service in services:
        if not isinstance(service, dict):
            raise ValueError("invalid service entry")
        pdas = service.get("pdas")
        if not isinstance(pdas, list):
            raise ValueError(f"invalid PDAs for service {service['id']}")
        for pda in pdas:
            if not isinstance(pda, dict) or not isinstance(pda.get("id"), str):
                raise ValueError(f"invalid PDA entry in service {service['id']}")
            if pda.get("id") in pda_ids:
                raise ValueError(f"duplicate PDA ID: {pda.get('id')}")
            pda_ids.add(pda.get("id"))
            pathways = pda.get("pathways")
            if not isinstance(pathways, list) or not pathways:
                raise ValueError(f"invalid pathways for PDA {pda.get('id')}")
            for pathway in pathways:
                if not isinstance(pathway, dict) or not isinstance(
                    pathway.get("requirements"), list
                ) or not pathway["requirements"]:
                    raise ValueError(f"invalid pathway for PDA {pda.get('id')}")
                for requirement in pathway["requirements"]:
                    if not isinstance(requirement, dict):
                        raise ValueError(f"invalid requirement in PDA {pda.get('id')}")
                    if requirement.get("cel") not in cel_ids:
                        raise ValueError(f"unknown CEL in PDA {pda.get('id')}")
                    if not set(requirement.get("accepted_grades", [])).issubset(
                        {"E1", "E3", "E4", "E5"}
                    ):
                        raise ValueError(f"invalid accepted grades in PDA {pda.get('id')}")
                    if requirement.get("coverage") not in {
                        None, "engagement_period", "engagement_period_per_account"
                    }:
                        raise ValueError(f"invalid coverage in PDA {pda.get('id')}")

    for service in services:
        for pda in service.get("pdas", []):
            dependencies = pda.get("depends_on", [])
            if not isinstance(dependencies, list) or not set(dependencies).issubset(pda_ids):
                raise ValueError(f"unknown PDA dependency in {pda.get('id')}")
    _validate_dependency_cycles(services)

    if not isinstance(policy.get("max_bytes"), int) or policy["max_bytes"] < 0:
        raise ValueError("invalid max_bytes in intake policy")
    if not isinstance(policy.get("allowed_extensions"), list) or not isinstance(
        policy.get("channels"), list
    ):
        raise ValueError("invalid intake policy")
    patterns = policy.get("suspicious_instruction_patterns", [])
    if not isinstance(patterns, list) or not all(
        isinstance(pattern, str) for pattern in patterns
    ):
        raise ValueError("invalid suspicious instruction patterns")
    try:
        for pattern in patterns:
            re.compile(pattern, re.IGNORECASE)
    except (TypeError, re.error) as error:
        raise ValueError("invalid suspicious instruction pattern") from error


def _unique_ids(entries: list, label: str) -> set[str]:
    if not all(isinstance(item, dict) and isinstance(item.get("id"), str) for item in entries):
        raise ValueError(f"invalid {label} entry")
    identifiers = [item["id"] for item in entries]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError(f"duplicate {label} ID")
    return set(identifiers)


def _validate_dependency_cycles(services: list) -> None:
    dependencies = {
        pda["id"]: pda.get("depends_on", [])
        for service in services for pda in service.get("pdas", [])
    }
    complete = set()

    def visit(pda_id: str, active: set[str]) -> None:
        if pda_id in active:
            raise ValueError("library contains a PDA dependency cycle")
        if pda_id in complete:
            return
        active.add(pda_id)
        for dependency in dependencies[pda_id]:
            visit(dependency, active)
        active.remove(pda_id)
        complete.add(pda_id)

    for pda_id in dependencies:
        visit(pda_id, set())
