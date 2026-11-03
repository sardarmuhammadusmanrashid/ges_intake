import re
from datetime import datetime
from decimal import Decimal, InvalidOperation


_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y")


def _parse_date(value: str) -> str:
    for date_format in _DATE_FORMATS:
        try:
            return datetime.strptime(value.strip(), date_format).date().isoformat()
        except ValueError:
            continue
    raise ValueError("invalid date")


def _parse_money(value: str) -> str:
    value = value.strip()
    negative = value.startswith("(") and value.endswith(")")
    if negative:
        value = value[1:-1].strip()
    elif value.startswith("(") or value.endswith(")"):
        raise ValueError("invalid money")
    if value.startswith("-"):
        negative = True
        value = value[1:].strip()
    value = value.removeprefix("$").strip()
    if not re.fullmatch(
        r"(?:(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?|\.\d+)", value
    ):
        raise ValueError("invalid money")
    value = value.replace(",", "")
    amount = Decimal(value)
    if not amount.is_finite():
        raise ValueError("invalid money")
    if negative:
        amount = -amount
    return format(amount.quantize(Decimal("0.01")), ".2f")


def _parse_value(value: str, field_type: str):
    value = value.strip()
    if field_type == "text":
        if not value:
            raise ValueError("empty text")
        return value
    if field_type == "date":
        return _parse_date(value)
    if field_type == "money":
        return _parse_money(value)
    if field_type == "year":
        if not re.fullmatch(r"\d{4}", value):
            raise ValueError("invalid year")
        return int(value)
    if field_type == "ssn":
        digits = re.sub(r"\D", "", value)
        if re.fullmatch(r"\d{3}-\d{2}-\d{4}", value):
            return f"***-**-{digits[-4:]}", digits
        if re.fullmatch(r"(?:XXX|\*\*\*)-(?:XX|\*\*\*)-\d{4}", value, re.IGNORECASE):
            return f"***-**-{digits[-4:]}", None
        raise ValueError("invalid SSN")
    if field_type == "ein":
        digits = re.sub(r"\D", "", value)
        if not re.fullmatch(r"\d{2}-\d{7}", value):
            raise ValueError("invalid EIN")
        return f"**-***{digits[-4:]}", digits
    if field_type == "account":
        if not re.fullmatch(r"[\d -]+", value):
            raise ValueError("invalid account")
        digits = re.sub(r"\D", "", value)
        if len(digits) < 4:
            raise ValueError("invalid account")
        return digits[-4:]
    raise ValueError(f"unsupported field type: {field_type}")


def extract_fields(text: str, document_type: dict) -> tuple[dict, list[str], dict]:
    """Return safe fields, flags, and transient sensitive values for identity checks."""
    fields = {}
    flags = set()
    sensitive_values = {}

    for name, specification in document_type.get("fields", {}).items():
        pattern = re.compile(specification["pattern"], re.MULTILINE | re.IGNORECASE)
        match = pattern.search(text)
        if match is None:
            continue
        try:
            if specification["type"] == "date_range":
                if len(match.groups()) != 2:
                    raise ValueError("date range needs two captures")
                start = _parse_date(match.group(1).strip())
                end = _parse_date(match.group(2).strip())
                fields[name + "_start"] = start
                fields[name + "_end"] = end
                if end < start:
                    flags.add("invalid_period")
            elif specification["type"] in {"ssn", "ein"}:
                safe_value, raw_value = _parse_value(match.group(1), specification["type"])
                fields[name] = safe_value
                if raw_value is not None:
                    sensitive_values[name] = raw_value
            else:
                fields[name] = _parse_value(match.group(1), specification["type"])
        except (ValueError, InvalidOperation):
            flags.add("unparseable_field")

    for required in document_type.get("required_fields", []):
        specification = document_type.get("fields", {}).get(required, {})
        present = required in fields
        if specification.get("type") == "date_range":
            present = required + "_start" in fields and required + "_end" in fields
        if not present:
            flags.add("missing_required_field")

    return fields, sorted(flags), sensitive_values
