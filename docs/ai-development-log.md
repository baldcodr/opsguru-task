# AI-Assisted Development Log

This is a concise record of how GitHub Copilot was configured and steered. It records decisions made during development; it is not a reconstructed transcript.

## 2026-09-08: Requirements Review

**Context supplied to AI:** `prompt.md`, `BUSINESS_CONTEXT.md`, and representative rows from `cloudnova_invoices.csv`.

**Initial direction:** build a small RAG agent with citations and a runnable evaluation harness.

**Human/AI judgment:** pure vector retrieval was rejected as the authority for revenue, MRR, refunds, churn, rankings, and payment exposure. The selected architecture is hybrid: deterministic full-population metrics plus semantic retrieval.

## 2026-09-08: Clarifications Locked Before Code

The following product decisions were explicitly selected through clarification questions:

- ship both CLI and `POST /ask`;
- use local retrieval with optional hosted-LLM synthesis;
- target an OpenAI-compatible provider contract;
- parse slash dates month-first and trailing-year hyphen dates day-first, retaining ambiguity flags;
- resolve repeated invoice IDs using the last physical source row while preserving superseded rows;
- use the latest invoice date as the account snapshot;
- net negative refunds into recognized revenue;
- calculate regional average MRR over active accounts with known `churned=false`;
- exclude unknown churn flags from churn denominators;
- define pending/failed exposure as absolute normalized invoice amount;
- show representative citations and persist a complete evidence manifest.

## 2026-09-08: Specification Gate

Copilot was instructed not to begin application code until a PRD and supporting data, metric, query, and evaluation contracts existed. Requirement IDs and traceability were validated mechanically.

One AI-generated audit report was discarded because it contradicted the actual CSV header and cited a 1,001-row dataset while referencing rows above 3,500. Only directly verified source evidence was retained. This override prevented incorrect counts and schema names from entering the PRD.

Another suggested direction treated core churn and exposure aggregations as expected RAG failures. That was rejected: all six stakeholder questions are required supported behavior and use deterministic metric functions. The expected limitation is monthly/cohort churn, which lacks a churn date in the source.

## 2026-09-08: Architecture

The architecture was authored with the Archify skill from the approved contracts. The first design contained redundant model/fallback paths and route collisions; it was simplified so the response assembler is the single optional synthesis boundary.

Archify showcase validation passed all nine checks with zero errors and warnings. Initial browser evidence exposed vertical overflow despite deterministic validation. The authored vertical layout was compressed and redelivered. The final artifact passed all required desktop containment checks in light and dark themes and was reviewed visually.

## 2026-09-08: Test-Driven Implementation

Each implementation slice began with a focused failing acceptance test, followed immediately by the narrowest validation: normalization, ingestion/reconciliation, SQLite persistence, six metric functions, retrieval, routing, artifact readiness, the shared service, CLI, API, and offline evaluations.

Two generated implementation assumptions were corrected through tests:

- cosine ranking alone did not reliably prioritize an explicitly named invoice, so exact invoice-ID matches now precede distance ordering;
- removing email values was insufficient because `contact_email_*` quality-flag names still entered chunks, so those diagnostics were removed from retrieval text and the chunk version was bumped.

A final independent contract audit found that a user-supplied email could still be echoed into the response and persisted through the manifest's question field. A regression test reproduced the leak before a shared privacy boundary was added; validated questions are now redacted before routing, retrieval, provider use, response serialization, or manifest persistence.

The service keeps complete evidence out of model context, produces deterministic answer IDs and atomically written manifests, and logs operational metadata without questions or sensitive record content. Provider transport and malformed-output failures fall back to deterministic wording without changing metric results.

The final quality gate runs the independent oracle check, Ruff, strict mypy, the offline pytest suite, an artifact build, and the public evaluation command in CI.

## Continuing Rules

- The independent oracle establishes golden values before application metric code.
- Hosted-model wording is never an exact evaluation target.
- Application failures are fixed against the written contract, not by regenerating expected values.
- Material deviations from these specs must be recorded here before implementation changes.