# CloudNova AI Development Instructions

## Product Contract

- Treat `specs/PRD.md`, `specs/data-contract.md`, `specs/metrics-contract.md`, `specs/query-contract.md`, and `specs/evaluation-contract.md` as the implementation authority.
- Do not change a locked business definition merely to make a test pass. Record and review contract changes first.
- All six stakeholder aggregations must scan the complete authoritative population through deterministic code. Never calculate them from top-k retrieval or model output.
- The OpenAI-compatible model may classify ambiguous intent or phrase grounded content only. It must not alter structured results, citations, warnings, or evidence membership.

## Data Safety and Auditability

- Never mutate `cloudnova_invoices.csv`.
- Preserve the physical 1-based CSV source row and raw audit values for every source record.
- Every source row must reconcile to authoritative, superseded, exact duplicate, or quarantined.
- Keep contact emails out of chunks, prompts, logs, responses, citations, and evidence manifests.
- Use `Decimal` for money. Do not parse or calculate currency through binary float.
- Unknown and ambiguous values must follow the written flag/null/quarantine policy; do not silently guess.

## Development Workflow

1. Write or update the acceptance test before implementation behavior.
2. Run the narrowest test that can falsify the change immediately after the first edit.
3. Keep the independent reference oracle under `evals/` free of imports from `app`.
4. Keep offline tests and evaluations independent of network access and API keys.
5. Preserve deterministic IDs, sort order, fingerprints, and evidence order.
6. Record material AI suggestions, human overrides, failures, and contract changes in `docs/ai-development-log.md`.

## Scope Guardrails

- MVP includes CLI, FastAPI, SQLite canonical data, Chroma retrieval, six metric functions, evidence manifests, offline evals, and CI.
- Do not add a frontend, authentication, live FX, ARR, revenue amortization, cohort churn, or general natural-language-to-SQL.
- Return `unsupported_metric` when required source data or an approved formula is absent.