
import hashlib
from pathlib import Path


def validate_file(inbox: Path, entry: dict, policy: dict) -> dict:
    """Validate one file before processing it."""

    source = entry.get("file")

    if not isinstance(source, str) or not source or "\0" in source:
        return {"status": "rejected", "reason": "unsafe_path"}

    path = Path(source)

    if path.is_absolute():
        return {"status": "rejected", "reason": "unsafe_path"}

    try:
        candidate = inbox / path
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(inbox.resolve())
    except (OSError, ValueError):
        return {"status": "rejected", "reason": "unsafe_path"}

    if not candidate.exists():
        return {"status": "rejected", "reason": "missing_file"}

    if candidate.is_symlink():
        return {"status": "rejected", "reason": "symlink"}

    if not candidate.is_file():
        return {"status": "rejected", "reason": "unsafe_path"}

    if candidate.suffix.lower() not in policy["allowed_extensions"]:
        return {"status": "rejected", "reason": "unsupported_type"}

    max_bytes = policy["max_bytes"]

    with candidate.open("rb") as file:
        raw = file.read(max_bytes + 1)

    if len(raw) > max_bytes:
        return {"status": "rejected", "reason": "too_large"}

    if not raw:
        return {"status": "rejected", "reason": "empty"}

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return {"status": "rejected", "reason": "not_utf8"}

    sha256 = hashlib.sha256(raw).hexdigest()

    return {
        "status": "valid",
        "raw": raw,
        "text": text,
        "sha256": sha256,
    }
