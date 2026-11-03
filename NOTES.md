# Implementation notes

## What works

- Tier 1 intake, manifest ordering, bounded file reads, duplicate detection, rule-based classification, field extraction/masking, identity checks, channel-based provenance, grading, and status handling.
- Tier 2 readiness for configured pathways, currentness, date coverage gaps, per-account gaps, dependencies, and service status.
- Tier 3 supersession across batches, balance continuity issues, advisory classification with redaction, library reference/dependency-cycle validation, and deterministic report ordering.
- Stretch attention lists for client, EIC, CPA, and owner roles. Client-facing attention omits internal identifiers.
- Part B findings are recorded in `REVIEW.md`.

## Decisions and limits

- Unclassified documents remain pending review; advisory suggestions are recorded but never applied.
- Full identifier values used for identity or supersession checks are transient in memory only. Persisted fields and advisory text use masked/redacted values.
- Validation currently uses the supplied synthetic day-one/day-two fixtures and focused unit tests; an independent acceptance-test library has not been provided.

## Verification

- `python -m unittest discover -s tests -v` — 9 tests pass.
- `python -m compileall -q ges_intake tests` — passes.
- Day one matches the specified counts and PDA statuses; day one plus day two exercises corrections, supersession, and balance continuity.

## Next

- Run the evaluator's unseen-library and malformed-input cases when available.
- Review deployment-specific filesystem permissions, symlink behavior, and the approved external-classifier privacy boundary before production use.
