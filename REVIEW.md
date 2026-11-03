# Legacy tagger review

## Findings

1. **Critical — SQL injection (lines 86–91).** `client_id`, `path`, `cel`, `level`, and `confidence` are interpolated into SQL. A crafted client ID, filename, or advisory response can alter the insert or readiness update; it can also corrupt rows for other clients. Use parameterized queries and validate the advisory response before persistence.

2. **Critical — Upload path traversal (lines 36–40).** `client_id` and `filename` are joined directly to the upload root without canonical containment checks. A filename such as `..\..\target` (or an absolute path) can write outside the client upload directory. Resolve and verify containment, reject symlinks, and use server-generated storage names.

3. **High — Readiness is granted on upload (line 91).** Any tagged upload sets a matching readiness row to `READY` without checking required evidence, document usability, review issues, or professional approval. A single unrelated or untrusted document can make work appear releasable. Readiness must be derived from configured requirements and must not imply approval or release.

4. **High — Sensitive documents and a credential are sent over plaintext HTTP (lines 16, 63–67).** The complete document text and the API key are included in a request to an `http://` endpoint. Network observers or the endpoint can capture client tax and identity data and the credential. Do not send sensitive data without an approved secure boundary, minimum necessary redaction, and managed credentials.

5. **High — Credential embedded in source (line 17).** The API key is a source-code literal, so anyone with repository access can reuse it. Revoke and rotate the exposed credential, then load secrets from an approved secret manager.

6. **High — Classification and provenance are inferred from filenames (lines 44–58).** A user-controlled filename containing `irs`, `official`, or `stmt` changes the assigned CEL or proof level. A renamed or misleading file can therefore be treated as official evidence without verification. Use governed content fingerprints for classification and derive provenance from the verified intake channel.

7. **High — Model failures become fabricated classifications (lines 68–69).** Every network or response error is converted into a confident-looking CEL fallback. A timeout or invalid response can silently label an unknown document as a tax return. Surface the failure for review and never apply an advisory suggestion as a classification.

8. **High — Raw document content is written to application logs (line 93).** The first 200 characters may contain an SSN, account number, or tax information. Logs are often more broadly accessible and retained longer than evidence storage. Log a generated document ID and safe metadata, not client text.

9. **Medium — Invalid UTF-8 is silently discarded (line 74).** `errors="ignore"` can remove bytes that affect classification or identifiers and then treat the altered text as valid. Reject invalid encoding or route the document for review without changing its content.

10. **Medium — Money comparisons use binary floating point (lines 97–102).** Decimal amounts such as `0.1` cannot be represented exactly as floats, so equal statement balances can compare unequal. Parse and compare with `Decimal`.

11. **Medium — Current time controls output and expiry (lines 83–84, 105–107).** The inferred tax year and expiry result vary by run date and timezone. `is_expired` also compares an expiry date at midnight with the current time, so a document can expire during its stated final day. Pass an explicit `as_of` date and compare dates.

## Recommendation

This code should not remain connected to production uploads while it is replaced: the path traversal, SQL construction, premature readiness update, and sensitive-data handling are release-blocking risks. First disable the upload handler's write/tag/readiness path, rotate the embedded credential, and review for prior exposure; then replace it with a contained, parameterized, evidence-governed pipeline and test the isolation boundaries.
