
import re
import unicodedata


def normalize_text(text: str) -> str:
    text = text.lstrip("\ufeff")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFKC", text)


def classify_document(text: str, document_types: list) -> dict:
    normalized = normalize_text(text)
    phrase_view = re.sub(r"\s+", " ", normalized.casefold())

    matches = []

    for document_type in document_types:
        rules = document_type["match"]

        required = [
            phrase.casefold()
            for phrase in rules["all"]
        ]

        forbidden = [
            phrase.casefold()
            for phrase in rules["none"]
        ]

        if all(phrase in phrase_view for phrase in required):
            if not any(phrase in phrase_view for phrase in forbidden):
                matches.append(document_type)

    if len(matches) == 1:
        return {
            "doc_type": matches[0]["id"],
            "cel": matches[0]["cel"],
            "flags": [],
        }

    if not matches:
        return {
            "doc_type": None,
            "cel": None,
            "flags": ["no_match"],
        }

    return {
        "doc_type": None,
        "cel": None,
        "flags": ["ambiguous_type"],
    }
