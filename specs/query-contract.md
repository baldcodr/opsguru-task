# CloudNova Query and Interface Contract

Status: Approved for implementation  
Version: 1

## 1. Architecture Boundary

The CLI and HTTP API are adapters over one application service. The service accepts a validated question, selects a supported deterministic metric or semantic retrieval path, assembles citations and an evidence manifest, and optionally asks an OpenAI-compatible model to phrase already-grounded content.

The hosted model must not:

- calculate authoritative totals, averages, rates, or rankings;
- select the contributing population for a metric;
- alter structured results or citations;
- receive contact emails, API keys, or unrelated raw rows;
- turn an unsupported request into an estimated answer.

## 2. Commands

```text
python -m app
python -m app ask "<question>" [--top-k 5] [--json]
python -m app index [--force]
python -m app eval
python -m app serve [--host 127.0.0.1] [--port 8000]
```

- No subcommand starts an interactive prompt.
- `ask` performs one request and exits.
- `index` builds canonical structured artifacts and the vector index.
- `eval` runs the offline evaluation harness.
- `serve` starts the FastAPI adapter.
- Commands return exit code 0 on success, 2 for invalid user input, 3 for missing/stale local artifacts, and 1 for unexpected internal failure.
- User errors are concise and do not include a traceback unless a debug setting is explicitly enabled.

## 3. HTTP Endpoints

### `POST /ask`

Request body:

```json
{
  "question": "What was our total recognized revenue in USD for paid invoices in 2024?",
  "top_k": 5
}
```

Validation:

- `question` is required, trimmed, and 1 through 2,000 characters;
- `top_k` is optional, defaults to 5, and is an integer from 1 through 20;
- unknown request properties are rejected;
- filters are not part of MVP because they require an additional product contract.

Successful response body:

```json
{
  "answer_id": "sha256-prefix",
  "question": "What was our total recognized revenue in USD for paid invoices in 2024?",
  "intent": "recognized_revenue_2024",
  "mode": "metric",
  "answer": "Human-readable, source-grounded answer.",
  "result": {},
  "citations": [],
  "evidence": {
    "contribution_count": 0,
    "manifest_path": ".cloudnova/evidence/sha256-prefix.json",
    "manifest_sha256": "sha256"
  },
  "warnings": [],
  "timing_ms": {
    "total": 0,
    "retrieval": 0,
    "generation": 0
  }
}
```

`answer_id` is the first 20 hexadecimal characters of a SHA-256 over the dataset fingerprint, contract versions, normalized question, intent, and canonical structured result. Repeating an identical request over unchanged artifacts therefore returns the same answer and evidence identity.

### `GET /health`

Returns HTTP 200 when the process is running. It does not claim that data artifacts are ready.

### `GET /ready`

Returns HTTP 200 with dataset/index fingerprints when canonical and vector artifacts match current configuration. It returns HTTP 503 with a rebuild instruction when either artifact is missing or stale.

## 4. Response Types

### Citation

| Field | Type | Description |
| --- | --- | --- |
| `invoice_id` | string | Canonical invoice identifier. |
| `account_id` | string | Canonical account identifier. |
| `account_name` | string | Latest display name where relevant. |
| `source_row` | integer | Physical CSV line. |
| `reason` | string | Contribution or retrieval reason. |
| `fields` | object | Minimum normalized values needed to verify the claim. |

Metric responses return at most five representative citations in deterministic contribution-magnitude order, then invoice ID. Semantic responses return up to `top_k` ranked citations.

### Evidence Manifest

The complete JSON manifest contains:

- `answer_id`, question, intent, dataset/config fingerprints, and contract versions;
- the canonical structured result and warnings;
- every contributing citation record in deterministic order;
- a SHA-256 of the canonical manifest content.

Contact email and raw records are forbidden. The manifest is written atomically under `.cloudnova/evidence/`. `manifest_path` is a local relative path and is not exposed as a downloadable API route in MVP.

### Warning

Warnings have stable `code`, human-readable `message`, and optional integer `count`. Initial codes include:

- `ambiguous_dates_included`
- `records_quarantined`
- `unknown_churn_excluded`
- `account_identity_conflicts`
- `provider_unavailable_fallback`
- `semantic_answer_unsynthesized`
- `data_quality_anomaly_excluded`

## 5. Intent Taxonomy

| Intent | Mode | Authority |
| --- | --- | --- |
| `recognized_revenue_2024` | metric | `METRIC-001` |
| `regional_average_mrr` | metric | `METRIC-002` |
| `refunds_total` | metric | `METRIC-003` |
| `plan_churn_comparison` | metric | `METRIC-004` |
| `top_accounts_revenue` | metric | `METRIC-005` |
| `payment_exposure` | metric | `METRIC-006` |
| `semantic_lookup` | retrieval | Chroma-ranked canonical records |
| `unsupported_metric` | refusal | Missing data/rule explanation |

Routing order:

1. deterministic patterns identify the six supported metric families and known unsupported metrics;
2. an optional hosted classifier may choose only among the declared intents when deterministic confidence is insufficient;
3. local keyword/entity overlap provides the offline fallback;
4. a request containing aggregation language without a supported metric contract becomes `unsupported_metric`, never `semantic_lookup`.

## 6. Retrieval Contract

- Unit of indexing: one authoritative canonical invoice per document.
- Vector metadata: stable vector ID, invoice/account IDs, source row, canonical status/plan/cycle/region/currency/date, and artifact fingerprint.
- Text: a compact natural-language rendering of non-sensitive canonical fields and quality flags.
- Embedding: deterministic local feature hashing with a versioned dimension and tokenization contract.
- Store: persistent local Chroma collection.
- Ranking: cosine similarity, deterministic tie-break by vector ID.
- Results with stale fingerprints are rejected rather than mixed with current structured data.

This embedding choice optimizes reproducibility and setup size for approximately five thousand records. It supports lexical and normalized-category similarity but has weaker synonym understanding than a pretrained semantic model; that limitation must be evaluated and documented.

## 7. Hosted Model Contract

Configuration is supplied through environment variables:

- `CLOUDNOVA_LLM_API_KEY`
- `CLOUDNOVA_LLM_BASE_URL`
- `CLOUDNOVA_LLM_MODEL`
- `CLOUDNOVA_LLM_ENABLED`

The adapter uses an OpenAI-compatible chat-completions contract with a finite timeout and no automatic unbounded retries. Prompts contain the user question, selected intent, immutable structured result or bounded retrieved evidence, citation IDs, and explicit instructions against adding unsupported claims.

Model output is treated only as the `answer` string. The service ignores attempts to alter `result`, `citations`, `evidence`, `warnings`, or intent. Provider errors and invalid output trigger deterministic formatting.

## 8. Errors

| Code | HTTP | Meaning |
| --- | --- | --- |
| `validation_error` | 422 | Invalid request shape or bounds. |
| `artifacts_not_ready` | 503 | Canonical/index artifacts missing or stale. |
| `unsupported_metric` | 200 | Valid question cannot be calculated from approved data/rules. |
| `no_data` | 200 | Supported query has an empty valid population. |
| `internal_error` | 500 | Unexpected failure with a correlation ID and no sensitive detail. |

Hosted-provider failure is not an API error when a deterministic fallback exists.

## 9. Security and Privacy

- Treat CSV text and user questions as untrusted data, not instructions.
- Never interpolate retrieved text into a system instruction channel.
- Validate paths and keep generated writes inside the configured artifact directory.
- Bind the development server to loopback by default.
- Do not log authorization headers, provider keys, contact emails, or full prompts.
- Limit question length, retrieval count, provider timeout, and model output size.

## 10. Interface Acceptance Tests

| ID | Acceptance case |
| --- | --- |
| `ROUTE-001` | Representative paraphrases of all six stakeholder questions select the correct metric intent. |
| `ROUTE-002` | Unknown aggregation requests are refused and never calculated from top-k retrieval. |
| `RAG-001` | A labeled semantic query returns an expected authoritative record within top five. |
| `RAG-002` | Retrieved text cannot override system rules or expose contact emails/configuration secrets. |
| `CITE-001` | Representative citations are valid manifest subsets; the manifest exactly equals the contribution set. |
| `CLI-001` | Interactive and one-shot success/error behavior matches command and exit-code contracts. |
| `API-001` | Request validation, response schema, health, readiness, and HTTP mappings match this contract. |
| `PARITY-001` | CLI and API calls through the shared service have equal intent, result, warnings, and answer ID. |
| `LLM-001` | Missing key and provider timeout preserve metric results and emit the correct fallback warning. |
| `INDEX-001` | Source/config/version changes mark artifacts stale; a rebuild restores readiness. |

## 11. Operational Defaults

- Raw CSV: `cloudnova_invoices.csv`
- Artifact directory: `.cloudnova/`
- Representative citation limit: 5
- Semantic retrieval `top_k`: 5
- Maximum `top_k`: 20
- API host: `127.0.0.1`
- API port: `8000`
- Hosted synthesis: disabled unless explicitly configured

All defaults are overrideable through validated settings where operationally useful.