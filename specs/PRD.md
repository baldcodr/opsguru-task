# CloudNova Invoice Q&A Product Requirements

Status: Draft for implementation  
Owner: Engineering  
Last updated: 2026-09-08

## 1. Product Summary

CloudNova Invoice Q&A is a local-first, retrieval-augmented question-answering service over `cloudnova_invoices.csv`. It converts a dirty invoice export into an auditable canonical dataset, answers supported financial questions with deterministic calculations, retrieves relevant invoice records semantically, and cites the records behind every answer.

The product exposes the same application service through:

- an interactive and one-shot command-line interface;
- a thin FastAPI `POST /ask` endpoint.

An OpenAI-compatible hosted model may classify or phrase answers, but it is never authoritative for arithmetic. Supported metrics remain available through deterministic formatting when no provider is configured or the provider fails.

## 2. Problem

Finance and revenue stakeholders need answers from a ledger containing inconsistent categories, mixed currencies and date formats, duplicate records, missing values, and conflicting account attributes. Semantic retrieval alone cannot reliably calculate totals, averages, rates, or rankings over the complete dataset. A trustworthy solution must combine retrieval with explicit business rules and preserve enough provenance for a stakeholder to audit every result.

## 3. Goals

1. Answer all six stakeholder questions in `BUSINESS_CONTEXT.md` using documented, deterministic metric definitions.
2. Support natural-language invoice and account lookup through a local vector index.
3. Normalize dirty source data without silently discarding uncertainty or conflicts.
4. Attach representative citations and a complete evidence manifest to every successful answer.
5. Run locally after setup through `python -m app` and expose `POST /ask` from the same service.
6. Provide reproducible offline evaluations, honest expected limitations, and CI enforcement.

## 4. Non-Goals

- A web frontend, authentication, multi-tenancy, or production hosting.
- Live FX rates or accounting-grade revenue deferral schedules.
- ARR, cohort churn, churn timing, or retention analysis requiring a churn date.
- Automatic reconciliation against CloudNova source systems.
- General-purpose natural-language-to-SQL.
- Editing or repairing the supplied raw CSV in place.

## 5. Users and Journeys

### Finance Analyst: Revenue Audit

The analyst asks for recognized revenue in 2024, receives the exact USD total and status breakdown, reviews representative citations, and opens the complete evidence manifest to reconcile every contributing invoice.

### Revenue Operations: Portfolio Analysis

The operator compares regional average MRR, plan churn rates, account rankings, refunds, and payment exposure. Calculations use explicit populations and report excluded unknown values rather than hiding them.

### Account Manager: Semantic Lookup

The manager asks a descriptive question such as which low-CSAT Enterprise accounts have support tickets. The service retrieves relevant canonical records and returns only source-backed claims with invoice citations.

### Auditor: Data-Quality Review

The auditor inspects normalization diagnostics, superseded duplicate records, ambiguous date flags, account identity conflicts, and source-row provenance without relying on generated prose.

## 6. Locked Product Decisions

- **Interfaces:** CLI and FastAPI, backed by one application service.
- **Retrieval:** local Chroma index with local deterministic embeddings.
- **Generation:** optional OpenAI-compatible hosted adapter for classification and synthesis.
- **Dates:** explicit ISO/year-first and month-name parsing; numeric slash dates are month-first; numeric trailing-year hyphen dates are day-first. Dates where both components are at most 12 are flagged as ambiguous.
- **Invoice conflicts:** exact duplicates collapse; otherwise, the last physical CSV row for an `invoice_id` is authoritative. Superseded rows and conflict details remain auditable.
- **Account snapshots:** the latest valid invoice date per `account_id` wins; source-row order breaks ties. Identity conflicts are reported.
- **Revenue:** canonical paid amounts plus canonical refunded negative amounts, converted to USD. Pending, failed, and void invoices do not contribute.
- **Regional MRR:** one latest account snapshot with known `churned=false`; churned and unknown accounts are excluded and counted.
- **Churn:** one latest account snapshot; only known booleans enter the denominator.
- **Exposure:** authoritative pending and failed invoices, using absolute USD invoice amounts with a status breakdown.
- **Rounding:** decimal arithmetic; sum unrounded converted values, then round displayed totals to cents.
- **Citations:** concise representative citations in the response and a complete JSON evidence manifest keyed by `answer_id`.

## 7. Functional Requirements

### FR-001: Data Ingestion

The system shall ingest every CSV source row without an unhandled exception. Each row shall receive exactly one disposition: authoritative, superseded, exact duplicate, or quarantined with a reason.

**Acceptance criteria**

- The reconciliation invariant `source = authoritative + superseded + exact_duplicates + quarantined` holds.
- Every retained record includes its 1-based source row.
- The source file is never modified.

### FR-002: Canonicalization

The system shall normalize documented plan, status, billing-cycle, boolean, currency, amount, date, and payment-method variants while preserving raw values and quality flags.

**Acceptance criteria**

- All documented variants pass table-driven tests.
- Unknown categories are flagged or quarantined rather than guessed.
- Malformed optional emails do not block ingestion and are not included in embeddings or answers.

### FR-003: Auditability

The system shall expose a data-quality summary, duplicate/conflict diagnostics, account identity conflicts, dataset fingerprint, and complete provenance.

**Acceptance criteria**

- Authoritative invoice IDs are unique.
- Every superseded record identifies its authoritative winner.
- Canonical values can be traced to raw values and source rows.

### FR-004: Deterministic Business Metrics

The system shall answer all six stakeholder questions through typed metric functions rather than top-k retrieval or LLM arithmetic.

**Acceptance criteria**

- Each metric matches its independent golden value, intermediary counts, ordering, warning set, and contribution set.
- Currency conversion uses USD `1.00`, EUR `1.08`, and GBP `1.27`.
- Results remain identical when hosted generation is disabled.

### FR-005: Semantic Retrieval

The system shall embed canonical invoice records locally and retrieve relevant records for descriptive invoice/account questions.

**Acceptance criteria**

- A labeled semantic lookup returns at least one expected record in the top five.
- Every returned citation resolves to an authoritative record and source row.
- Embedded text excludes contact email and configuration secrets.

### FR-006: Hybrid Query Routing

The system shall distinguish supported metric intents, semantic lookups, and unsupported requests.

**Acceptance criteria**

- Paraphrases of all six stakeholder questions route to the correct metric.
- Aggregate requests never calculate from a top-k subset.
- Unsupported metrics return a typed explanation identifying the missing data or rule.

### FR-007: Citations and Evidence

Every successful answer shall include source evidence appropriate to its result size.

**Acceptance criteria**

- Responses contain representative citations with invoice ID, account ID/name, source row, and relevance or contribution reason.
- Aggregate evidence manifests contain every and only contributing authoritative record.
- Contact email is never exposed in citations, manifests, logs, or model prompts.

### FR-008: Command-Line Interface

The system shall support interactive use and one-shot commands.

**Acceptance criteria**

- `python -m app` starts an interactive prompt.
- `python -m app ask "<question>"` returns one answer.
- `python -m app index`, `python -m app eval`, and `python -m app serve` perform their named operations.
- Invalid input produces concise guidance without a traceback.

### FR-009: HTTP API

The system shall expose `POST /ask` with the same semantics as the CLI.

**Acceptance criteria**

- Valid requests return schema-valid JSON and HTTP 200.
- Blank or malformed requests return HTTP 422.
- CLI and API calls to the shared service produce equivalent structured results and evidence IDs.
- Health and readiness endpoints distinguish process health from data/index readiness.

### FR-010: Hosted Synthesis and Fallback

The system may use an environment-configured OpenAI-compatible endpoint to phrase source-grounded results.

**Acceptance criteria**

- No API key is required for ingestion, metrics, retrieval, tests, or offline evaluations.
- Provider failure yields a deterministic answer plus a warning for supported metrics.
- Semantic retrieval returns ranked evidence without invented synthesis when the provider is unavailable.

### FR-011: Index Lifecycle

The system shall detect missing or stale structured/vector artifacts.

**Acceptance criteria**

- The fingerprint covers source bytes, normalization version, chunk version, and embedding configuration.
- A mismatch marks the relevant artifact stale and provides a rebuild command.
- Rebuilding from unchanged inputs produces the same structured records and vector IDs.

### FR-012: Honest Limitations

The system shall refuse unsupported calculations rather than fabricate a result.

**Acceptance criteria**

- Monthly or cohort churn requests return `unsupported_metric` because no churn date exists.
- Date-sensitive answers report relevant ambiguity/quarantine counts.
- README and evaluations distinguish retrieval limitations from data limitations.

## 8. Non-Functional Requirements

### NFR-001: Reproducibility

Dependencies and artifact versions shall be pinned. Fixed data and configuration shall produce identical structured values, dispositions, evidence sets, and vector IDs.

### NFR-002: Numerical Precision

Financial arithmetic shall use `Decimal`; displayed currency shall round to cents only after aggregation. Golden tests shall compare exact values, not percentage tolerances.

### NFR-003: Local-First Operation

Ingestion, analytics, retrieval, deterministic answers, and offline evaluations shall run without network access after dependencies are installed.

### NFR-004: Configuration and Secrets

Paths, model names, retrieval limits, provider URL/model, and API key shall be externally configurable. Secrets and generated local artifacts shall be ignored by Git.

### NFR-005: Reliability

Malformed input, stale indexes, provider errors, and unsupported questions shall produce typed failures or documented fallbacks. User-caused errors shall not emit stack traces.

### NFR-006: Observability and Privacy

Structured logs shall include intent, timing, fingerprints, warning codes, evidence counts, and provider fallback status. They shall exclude contact emails, prompts containing unnecessary personal data, and API keys.

### NFR-007: Documentation

The README shall explain the product, setup, single demo command, architecture, tests, trade-offs, pure-RAG limitations, known data assumptions, and next-day improvements in a three-minute stakeholder read.

### NFR-008: CI Quality Gate

GitHub Actions shall run formatting/lint checks, type checks, unit and contract tests, and offline evaluations from a clean checkout.

## 9. Success Measures

- Six of six required stakeholder metric evaluations pass exactly.
- All normalization, reconciliation, CLI/API contract, and citation-completeness tests pass.
- The expected unsupported cohort-churn case refuses a numeric answer with the correct reason.
- No hosted provider or secret is needed for CI.
- A stakeholder can run the documented demo and inspect evidence without reading source code.

## 10. Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| Ambiguous dates alter period totals | Apply the locked separator rule, flag ambiguity, report sensitivity counts. |
| Duplicate policy selects the wrong business truth | Preserve every row, expose conflicts, and document last-row precedence. |
| Account attributes change across invoices | Use a deterministic latest snapshot and report identity conflicts. |
| Top-k retrieval produces incomplete aggregates | Route all supported metrics to full-dataset deterministic functions. |
| Hosted model changes wording or fails | Keep structured results authoritative and provide deterministic fallback text. |
| Evidence becomes too large for terminal output | Show representative citations and persist the complete manifest. |

## 11. Release Gate

The MVP is releasable when:

1. Supporting data, metric, query, and evaluation contracts contain no unresolved placeholders.
2. Every functional requirement maps to at least one executable acceptance test.
3. All six golden metric evaluations and evidence-set checks pass.
4. CLI and API parity, offline provider fallback, stale-index detection, and privacy checks pass.
5. The expected cohort-churn limitation is reported honestly.
6. The Archify architecture passes showcase validation, delivery, browser checks, and post-build reconciliation.
7. CI and the README's clean setup, demo, and evaluation commands succeed.

## 12. Traceability

- Canonical schema and cleaning rules: `specs/data-contract.md`
- Financial definitions: `specs/metrics-contract.md`
- CLI/API and response behavior: `specs/query-contract.md`
- Executable evaluation requirements: `specs/evaluation-contract.md`
- Architecture source and artifact: `docs/architecture.archify.json`, `docs/architecture.html`
- Source business briefing: `BUSINESS_CONTEXT.md`