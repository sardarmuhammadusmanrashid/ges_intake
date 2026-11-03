# GES Engineering Onsite Exercise
## Offline Evidence Intake Engine

### 1. Project Overview

The GES Evidence Intake Engine is an offline Python-based command-line tool designed to process client documents and evaluate whether the required evidence is available for a service.

The system checks document safety, detects duplicate files, classifies documents, extracts relevant information, masks sensitive identifiers, and validates client identity and evidence trustworthiness.

Finally, it generates an evidence readiness report that identifies:

- Evidence that has been successfully received and verified
- Missing or incomplete evidence
- Documents that require human review

The system follows a rule-based approach and avoids making unsupported assumptions when a document is ambiguous.

### 2. Technology Requirements

- Python 3.10 or higher
- Command-line interface (CLI)
- Offline execution
- Rule-based document processing

### 3. Project Execution

Start by reviewing the `TASK.md` file to understand the exercise requirements.

#### Step 1: Generate the Inbox

Run the following command to generate sample client documents:

```bash
python tools/make_inbox.py inbox
```

#### Step 2: Run the Evidence Intake Workflow

Execute the following command to process the client's documents:

```bash
python -m ges_intake --library library --clients clients run --client C-1001 --inbox inbox\day1 --inbox inbox\day2 --as-of 2026-03-03 --outbox outbox.jsonl
```

#### Command Parameters

| Parameter | Description |
|---|---|
| `--library library` | Specifies the document library and supporting resources. |
| `--clients clients` | Specifies the client configuration directory. |
| `--client C-1001` | Identifies the client whose documents are being processed. |
| `--inbox inbox\day1` | Specifies the first document intake directory. |
| `--inbox inbox\day2` | Specifies the second document intake directory. |
| `--as-of 2026-03-03` | Sets the date used for evidence evaluation. |
| `--outbox outbox.jsonl` | Specifies the output file for the generated results. |

### 4. System Modules and Responsibilities

#### 4.1 `intake.py` — Document Intake and Safety

This module receives documents from the client inbox and performs initial file safety checks.

Its responsibilities include:

- Validating incoming files
- Checking file integrity and safety
- Detecting duplicate documents
- Preparing documents for further processing

#### 4.2 `classification.py` — Document Classification

This module identifies the type of document received.

For example, it determines whether a document is:

- A bank statement
- A utility bill

The classification process uses configured rules to identify the appropriate document category.

#### 4.3 `extraction.py` — Information Extraction

This module extracts the required information from classified documents.

Its responsibilities include:

- Identifying relevant document fields
- Extracting required information
- Masking sensitive identifiers
- Preparing structured data for validation

#### 4.4 `governance.py` — Identity and Evidence Validation

This module validates the identity of the client and evaluates the trustworthiness of the submitted evidence.

It checks:

- Client identity
- Evidence source and provenance
- Evidence trust level
- Whether the document meets the configured validation requirements

#### 4.5 `config.py` — Configuration and Rules

This module manages the system's configuration and validation rules.

It ensures that:

- Configuration files are valid
- Required settings are available
- Processing rules are correctly defined
- Invalid configurations are handled appropriately

#### 4.6 `readiness.py` — Evidence Readiness Evaluation

This module determines whether the available evidence is sufficient for the requested service.

It evaluates:

- Required evidence availability
- Missing documents or information
- Evidence completeness
- Items requiring human review

The module produces a readiness assessment based on the configured service requirements.

#### 4.7 `main.py` — Workflow Orchestration

This module acts as the main entry point of the application.

It coordinates the complete evidence intake workflow by executing the required stages in sequence:

1. Receive documents
2. Perform file safety and duplicate checks
3. Classify documents
4. Extract relevant information
5. Validate identity and evidence trustworthiness
6. Evaluate evidence readiness
7. Generate the final output

### 5. Expected Output

The system generates a JSON Lines (`.jsonl`) output file containing the results of the evidence intake process.

The output provides information about:

- Processed documents
- Document classifications
- Extracted information
- Identity and evidence validation results
- Evidence readiness status
- Missing evidence
- Human review requirements

### 6. Conclusion

The GES Evidence Intake Engine automates the initial processing and validation of client-submitted documents.

By combining file safety checks, document classification, information extraction, governance validation, and readiness evaluation, the system provides a structured and reliable way to determine whether the required evidence is available for a service.

The entire workflow operates offline, making it suitable for environments where document privacy, controlled processing, and predictable rule-based decisions are important.