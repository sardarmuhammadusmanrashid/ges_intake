from datetime import date, timedelta
from decimal import Decimal


_READY_STATUSES = {"SATISFIED", "READY_FOR_DETERMINATION"}


def _is_current(document: dict, cel: dict, engagement_end: date, as_of: date) -> bool:
    fields = document["fields"]
    currentness = cel.get("currentness", {})
    rule = currentness.get("rule", "none")
    if rule == "none":
        return True
    if rule == "not_expired":
        expiration = fields.get("expiration")
        return expiration is not None and date.fromisoformat(expiration) >= as_of
    if rule == "tax_year":
        tax_year = fields.get("tax_year")
        return tax_year == engagement_end.year + currentness.get("offset", 0)
    if rule == "period_overlap":
        start = fields.get("period_start")
        end = fields.get("period_end")
        if start is None or end is None:
            return False
        return (
            date.fromisoformat(start) <= engagement_end
            and date.fromisoformat(end) >= date.fromisoformat(
                document["_engagement_start"]
            )
        )
    return False


def _usable_documents(requirement: dict, documents: list[dict], cel_by_id: dict,
                      engagement_start: date, engagement_end: date,
                      as_of: date) -> list[dict]:
    cel = cel_by_id[requirement["cel"]]
    allowed_provenance = set(cel.get("allowed_provenance", []))
    required_provenance = requirement.get("provenance")
    usable = []
    for document in documents:
        if document["status"] != "accepted" or document["cel"] != requirement["cel"]:
            continue
        if document["grade"] not in requirement.get("accepted_grades", []):
            continue
        if document["provenance"] not in allowed_provenance:
            continue
        if required_provenance and document["provenance"] not in required_provenance:
            continue
        candidate = dict(document)
        candidate["_engagement_start"] = engagement_start.isoformat()
        if not _is_current(candidate, cel, engagement_end, as_of):
            continue
        usable.append(document)
    return usable


def _coverage_gaps(documents: list[dict], start: date, end: date) -> list[list[str]]:
    intervals = []
    for document in documents:
        fields = document["fields"]
        period_start = fields.get("period_start")
        period_end = fields.get("period_end")
        if not period_start or not period_end:
            continue
        first = max(date.fromisoformat(period_start), start)
        last = min(date.fromisoformat(period_end), end)
        if first <= last:
            intervals.append((first, last))
    intervals.sort()

    gaps = []
    cursor = start
    for interval_start, interval_end in intervals:
        if interval_start > cursor:
            gaps.append([cursor.isoformat(), (interval_start - timedelta(days=1)).isoformat()])
        cursor = max(cursor, interval_end + timedelta(days=1))
        if cursor > end:
            break
    if cursor <= end:
        gaps.append([cursor.isoformat(), end.isoformat()])
    return gaps


def _evaluate_requirement(requirement: dict, documents: list[dict], cel_by_id: dict,
                          accounts: list[str], start: date, end: date,
                          as_of: date) -> tuple[bool, list[dict], list[str]]:
    usable = _usable_documents(
        requirement, documents, cel_by_id, start, end, as_of
    )
    coverage = requirement.get("coverage")
    missing = []
    if coverage is None:
        if not usable:
            missing.append({"cel": requirement["cel"]})
            return False, missing, []
        return True, [], [doc["document_id"] for doc in usable]

    if coverage == "engagement_period":
        gaps = _coverage_gaps(usable, start, end)
        if gaps:
            missing.append({"cel": requirement["cel"], "gaps": gaps})
            return False, missing, []
        return True, [], [doc["document_id"] for doc in usable]

    if coverage == "engagement_period_per_account":
        matched_ids = []
        for account in accounts:
            account_docs = [
                doc for doc in usable if doc["fields"].get("account") == account
            ]
            gaps = _coverage_gaps(account_docs, start, end)
            if gaps:
                missing.append({
                    "cel": requirement["cel"],
                    "account": account,
                    "gaps": gaps,
                })
            else:
                matched_ids.extend(doc["document_id"] for doc in account_docs)
        return not missing, missing, matched_ids

    raise ValueError(f"unknown coverage rule: {coverage}")


def _balance_issues(requirement: dict, documents: list[dict], cel_by_id: dict,
                    start: date, end: date, as_of: date) -> list[str]:
    if requirement.get("coverage") != "engagement_period_per_account":
        return []
    usable = _usable_documents(
        requirement, documents, cel_by_id, start, end, as_of
    )
    by_account = {}
    for document in usable:
        fields = document["fields"]
        account = fields.get("account")
        period_start = fields.get("period_start")
        period_end = fields.get("period_end")
        if not account or not period_start or not period_end:
            continue
        by_account.setdefault(account, []).append(document)

    issues = []
    for account, statements in by_account.items():
        statements.sort(key=lambda document: (
            document["fields"]["period_start"],
            document["fields"]["period_end"],
            document["document_id"],
        ))
        for previous, following in zip(statements, statements[1:]):
            previous_fields = previous["fields"]
            following_fields = following["fields"]
            previous_end = date.fromisoformat(previous_fields["period_end"])
            following_start = date.fromisoformat(following_fields["period_start"])
            if following_start != previous_end + timedelta(days=1):
                continue
            if Decimal(following_fields["beginning_balance"]) != Decimal(
                previous_fields["ending_balance"]
            ):
                issues.append(
                    f"balance_discontinuity:{account}:{following_fields['period_start']}"
                )
    return issues


def evaluate_readiness(client: dict, service: dict, cel_configuration: dict,
                       documents: list[dict], as_of: date) -> dict:
    engagement = client["engagement"]
    start = date.fromisoformat(engagement["period_start"])
    end = date.fromisoformat(engagement["period_end"])
    cel_by_id = {item["id"]: item for item in cel_configuration["cel"]}
    pdas = service["pdas"]

    evaluated = {}
    for pda in pdas:
        pathways = []
        first_satisfied = []
        satisfied_pathway_selected = False
        for pathway in pda["pathways"]:
            pathway_missing = []
            pathway_documents = []
            met = True
            for requirement in pathway["requirements"]:
                is_met, missing, found_documents = _evaluate_requirement(
                    requirement,
                    documents,
                    cel_by_id,
                    client.get("accounts", []),
                    start,
                    end,
                    as_of,
                )
                met = met and is_met
                pathway_missing.extend(missing)
                pathway_documents.extend(found_documents)
            pathways.append({
                "name": pathway["name"],
                "met": met,
                "missing": pathway_missing,
            })
            if met and not satisfied_pathway_selected:
                first_satisfied = sorted(set(pathway_documents))
                satisfied_pathway_selected = True

        relevant_cels = {
            requirement["cel"]
            for pathway in pda["pathways"]
            for requirement in pathway["requirements"]
        }
        issues = sorted({
            f"document:{document['document_id']}"
            for document in documents
            if document["status"] == "pending_review"
            and document.get("cel") in relevant_cels
        } | {
            issue
            for pathway in pda["pathways"]
            for requirement in pathway["requirements"]
            for issue in _balance_issues(
                requirement, documents, cel_by_id, start, end, as_of
            )
        })
        evaluated[pda["id"]] = {
            "id": pda["id"],
            "name": pda["name"],
            "pathways": pathways,
            "satisfied_by": first_satisfied,
            "issues": issues,
            "depends_on": pda.get("depends_on", []),
            "requires_cpa": pda.get("requires_cpa", False),
        }

    state = {}

    def determine(pda_id: str, visiting: set[str]) -> str:
        if pda_id in state:
            return state[pda_id]
        if pda_id in visiting:
            raise ValueError("library contains a PDA dependency cycle")
        item = evaluated.get(pda_id)
        if item is None:
            raise ValueError(f"unknown PDA dependency: {pda_id}")
        visiting.add(pda_id)
        if not any(pathway["met"] for pathway in item["pathways"]):
            status = "MISSING"
        elif item["issues"]:
            status = "PENDING_REVIEW"
        elif any(
            determine(dependency, visiting) not in _READY_STATUSES
            for dependency in item["depends_on"]
        ):
            status = "BLOCKED_BY_DEPENDENCY"
        elif item["requires_cpa"]:
            status = "READY_FOR_DETERMINATION"
        else:
            status = "SATISFIED"
        visiting.remove(pda_id)
        state[pda_id] = status
        return status

    output_pdas = []
    for pda in pdas:
        item = evaluated[pda["id"]]
        item["status"] = determine(pda["id"], set())
        output_pdas.append({
            key: value for key, value in item.items()
            if key != "requires_cpa"
        })

    security_holds = sorted({
        f"document:{document['document_id']}"
        for document in documents if document["status"] == "quarantined"
    })
    if security_holds:
        status = "BLOCKED"
    elif all(item["status"] in _READY_STATUSES for item in output_pdas):
        status = "READY"
    else:
        status = "NOT_READY"
    return {
        "client_id": client["client_id"],
        "service": service["id"],
        "as_of": as_of.isoformat(),
        "library_version": cel_configuration["library_version"],
        "status": status,
        "security_holds": security_holds,
        "pdas": output_pdas,
    }


def build_attention(readiness: dict, service: dict, cel_configuration: dict,
                    documents: list[dict]) -> dict:
    level_order = {"NOW": 0, "NEXT": 1, "WATCH": 2}
    roles = {"client": {}, "eic": {}, "cpa": {}, "owner": {}}
    cel_by_id = {item["id"]: item for item in cel_configuration["cel"]}

    def add(role: str, internal_key: str, item: dict) -> None:
        existing = roles[role].get(internal_key)
        if existing is None:
            roles[role][internal_key] = item
            return
        if item.get("gaps"):
            existing.setdefault("gaps", []).extend(item["gaps"])
        if item.get("missing"):
            existing.setdefault("missing", []).extend(item["missing"])

    client_missing = {}
    for pda in readiness["pdas"]:
        if pda["status"] == "MISSING" and pda["pathways"]:
            for missing in pda["pathways"][0]["missing"]:
                cel = cel_by_id[missing["cel"]]
                criticality = cel.get("criticality")
                if criticality == "C4":
                    continue
                level = "NOW" if criticality == "C1" else "NEXT"
                key = f"missing:{missing['cel']}"
                staff_item = {
                    "level": level,
                    "kind": "missing_evidence",
                    "key": key,
                    "message": f"{pda['id']} needs {missing['cel']} evidence.",
                    "missing": [missing],
                }
                for role in ("eic", "client"):
                    add(
                        role,
                        key,
                        dict(staff_item) if role == "eic" else {
                            "level": level,
                            "kind": "missing_evidence",
                            "message": "",
                        },
                    )
                client_missing.setdefault(missing["cel"], []).append(missing)
                roles["client"][key]["message"] = _client_missing_message(
                    cel, client_missing[missing["cel"]]
                )

    issue_ids = {
        issue
        for pda in readiness["pdas"]
        for issue in pda["issues"]
    }
    issue_ids.update(
        f"document:{document['document_id']}"
        for document in documents if document["status"] == "pending_review"
    )
    quarantined_ids = {
        hold.removeprefix("document:")
        for hold in readiness["security_holds"]
    }
    for issue in sorted(issue_ids):
        if issue.startswith("document:") and issue.removeprefix("document:") in quarantined_ids:
            continue
        key = f"issue:{issue}"
        item = {
            "level": "NOW",
            "kind": "review_required",
            "key": key,
            "message": f"Review required for {issue}.",
        }
        add("eic", key, item)
        add("cpa", key, {**item, "level": "WATCH"})

    for document_id in sorted(quarantined_ids):
        key = f"issue:document:{document_id}"
        item = {
            "level": "NOW",
            "kind": "security_incident",
            "key": key,
            "message": f"Security incident requires review for document:{document_id}.",
        }
        add("eic", key, item)
        add("cpa", key, {**item, "level": "WATCH"})
        add("owner", key, item)

    for pda in readiness["pdas"]:
        if pda["status"] == "READY_FOR_DETERMINATION":
            key = f"pda:{pda['id']}"
            add("cpa", key, {
                "level": "NOW",
                "kind": "ready_for_determination",
                "key": key,
                "message": f"{pda['id']} is ready for CPA determination.",
            })
        elif pda["status"] == "BLOCKED_BY_DEPENDENCY":
            key = f"pda:{pda['id']}"
            add("cpa", key, {
                "level": "WATCH",
                "kind": "blocked_by_dependency",
                "key": key,
                "message": f"{pda['id']} is waiting on a prerequisite determination.",
            })

    result = {}
    for role, items in roles.items():
        ordered = sorted(
            items.items(),
            key=lambda pair: (
                level_order[pair[1]["level"]],
                pair[1]["kind"],
                pair[0],
            ),
        )
        result[role] = [item for _, item in ordered]
    return result


def _client_missing_message(cel: dict, missing: list[dict]) -> str:
    details = []
    for item in missing:
        account = item.get("account")
        for start, end in item.get("gaps", []):
            detail = f"{start} through {end}"
            if account:
                detail += f" for the account ending in {account}"
            details.append(detail)
    if details:
        return f"Please provide {cel['client_label']} covering " + "; ".join(sorted(set(details))) + "."
    return f"Please provide {cel['client_label']}."
