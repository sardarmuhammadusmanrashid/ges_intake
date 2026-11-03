import re
import unicodedata


def _name_tokens(name: str) -> list[str]:
    name = unicodedata.normalize("NFKC", name).casefold().strip()
    if name.count(",") == 1:
        last, first = (part.strip() for part in name.split(",", 1))
        name = f"{first} {last}"
    name = "".join(character if character.isalpha() else " " for character in name)
    return [token for token in name.split() if len(token) > 1]


def _last_four(value: str) -> str:
    return re.sub(r"\D", "", value)[-4:]


def govern_document(fields: dict, transient_sensitive: dict, document_type: dict,
                    client: dict, channel: str, flags: list[str],
                    intake_policy: dict) -> dict:
    flags = set(flags)
    identity = document_type.get("identity", {})

    ssn_field = identity.get("ssn_field")
    if ssn_field and ssn_field in fields:
        client_ssn = re.sub(r"\D", "", str(client.get("ssn", "")))
        extracted_ssn = transient_sensitive.get(ssn_field)
        masked_ssn = fields[ssn_field]
        if client_ssn and (
            _last_four(masked_ssn) != client_ssn[-4:]
            or (extracted_ssn is not None and extracted_ssn != client_ssn)
        ):
            flags.add("identity_mismatch")
            return {
                "fields": {},
                "flags": sorted(flags),
                "provenance": None,
                "grade": "E5",
                "status": "quarantined",
            }

    name_field = identity.get("name_field")
    if name_field and name_field in fields:
        if _name_tokens(fields[name_field]) != _name_tokens(client.get("name", "")):
            flags.add("name_mismatch")

    account_field = identity.get("account_field")
    if account_field and account_field in fields:
        if fields[account_field] not in {str(value)[-4:] for value in client.get("accounts", [])}:
            flags.add("unknown_account")

    provenance_spec = document_type.get("provenance", {})
    by_channel = provenance_spec.get("by_channel", {})
    provenance = by_channel.get(channel, provenance_spec.get("default"))
    if provenance_spec.get("claims_official") and channel not in by_channel:
        flags.add("claimed_official_source_unverified")

    if flags.intersection(intake_policy.get("security_flags", [])):
        grade = "E5"
    elif flags.intersection(intake_policy.get("e4_flags", [])):
        grade = "E4"
    else:
        grade = "E1" if provenance in {"P1", "P2"} else "E3"

    status = (
        "quarantined" if grade == "E5"
        else "pending_review"
        if flags.intersection(intake_policy.get("review_flags", []))
        else "accepted"
    )
    return {
        "fields": fields,
        "flags": sorted(flags),
        "provenance": provenance,
        "grade": grade,
        "status": status,
    }


def redact_for_advisory(text: str) -> str:
    text = re.sub(
        r"(?im)^\s*(?:account number|account no\.?|license no\.?|"
        r"passport no\.?|social security number|ssn|(?:recipient|employee)'?s "
        r"(?:tin|ssn)|(?:payer)'?s tin)\s*:\s*.+$",
        "[REDACTED IDENTIFIER]",
        text,
    )
    text = re.sub(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)", "[REDACTED SSN]", text)
    text = re.sub(r"(?<!\d)\d{2}-\d{7}(?!\d)", "[REDACTED EIN]", text)
    text = re.sub(r"(?<!\d)\d{2}-\d{3}-\d{4}(?!\d)", "[REDACTED ID]", text)
    text = re.sub(r"(?<!\d)(?:\d[ -]?){8,}\d(?!\d)", "[REDACTED ACCOUNT]", text)
    text = re.sub(r"(?i)\b(?:XXX|\*{3})-(?:XX|\*{3})-\d{4}\b", "[REDACTED SSN]", text)
    return text
