# CloudNova Canonical Data Contract

Status: Approved for implementation  
Version: 1

## 1. Purpose

This contract defines how `cloudnova_invoices.csv` becomes canonical, auditable invoice and account records. The raw file is immutable. Normalization must be deterministic and preserve enough provenance to reproduce every decision.

## 2. Source Contract

The source is a UTF-8 CSV with one header and these 19 columns in order:

1. `invoice_id`
2. `account_id`
3. `account_name`
4. `contact_email`
5. `region`
6. `industry`
7. `plan`
8. `billing_cycle`
9. `seats`
10. `currency`
11. `amount`
12. `discount_pct`
13. `status`
14. `payment_method`
15. `signup_date`
16. `invoice_date`
17. `churned`
18. `csat_score`
19. `support_tickets`

`source_row` is the 1-based physical file line, including the header as line 1. The first data record therefore has `source_row=2`.

Required source fields are `invoice_id`, `account_id`, `account_name`, `region`, `plan`, `billing_cycle`, `seats`, `currency`, `amount`, `discount_pct`, `status`, `signup_date`, `invoice_date`, and `support_tickets`. Optional fields are `contact_email`, `industry`, `payment_method`, `churned`, and `csat_score`.

## 3. Row Dispositions

Every source data row receives exactly one disposition:

- `authoritative`: the row used by canonical queries and retrieval;
- `superseded`: an earlier row sharing an `invoice_id` with a later row;
- `exact_duplicate`: an additional byte-equivalent parsed row after the first occurrence;
- `quarantined`: a row whose required identity, category, numeric value, or invoice date cannot be normalized safely.

The reconciliation invariant is:

```text
source_data_rows = authoritative + superseded + exact_duplicate + quarantined
```

Disposition precedence is:

1. quarantine structurally invalid rows;
2. mark repeated full raw-record values as exact duplicates, retaining the first occurrence for subsequent conflict resolution;
3. group remaining valid rows by normalized `invoice_id` and mark the greatest `source_row` authoritative;
4. mark every earlier row in that group superseded and link it to the winner.

This rule treats later export rows as later corrections because the source has no update timestamp. It does not assert that the chosen row reflects source-system truth.

## 4. Canonical Invoice Schema

| Field | Type | Rule |
| --- | --- | --- |
| `invoice_id` | string | Trimmed, non-empty, case preserved. |
| `account_id` | string | Trimmed, non-empty, case preserved. |
| `account_name` | string | Trimmed with internal whitespace collapsed. |
| `region` | enum | `NA`, `EMEA`, `APAC`, or `LATAM`. |
| `industry` | string/null | Trimmed; blank becomes null. |
| `plan` | enum | `starter`, `pro`, or `enterprise`. |
| `billing_cycle` | enum | `monthly` or `annual`. |
| `seats` | integer | Greater than zero. |
| `currency` | enum | `USD`, `EUR`, or `GBP`. |
| `amount_local` | Decimal | Signed amount parsed from `amount`. |
| `fx_to_usd` | Decimal | USD `1.00`, EUR `1.08`, GBP `1.27`. |
| `amount_usd_unrounded` | Decimal | `amount_local * fx_to_usd`. |
| `discount_pct` | Decimal | Inclusive range 0 through 100. |
| `status` | enum | `paid`, `pending`, `failed`, `refunded`, or `void`. |
| `payment_method` | string/null | Lowercase canonical value when known; blank is null. |
| `signup_date` | date/null | Parsed date; invalid optional date becomes null plus a flag. |
| `invoice_date` | date | Parsed date; invalid value quarantines the row. |
| `churned` | bool/null | Missing value remains unknown, never coerced to false. |
| `csat_score` | integer/null | Inclusive range 1 through 5; blank becomes null. |
| `support_tickets` | integer | Zero or greater. |
| `source_row` | integer | Physical source line. |
| `quality_flags` | set[string] | Sorted stable codes described below. |
| `raw_values` | object | Original string values required for audit. |

Contact email is retained only in the protected raw audit record. It is excluded from canonical chunks, prompts, logs, API responses, citations, and evidence manifests.

## 5. Category Normalization

All category matching trims surrounding whitespace and compares case-insensitively.

### Plans

| Canonical | Accepted values |
| --- | --- |
| `starter` | `starter`, `start`, `tier 1` |
| `pro` | `pro`, `professional`, `tier 2` |
| `enterprise` | `enterprise`, `ent`, `tier 3` |

### Billing Cycles

| Canonical | Accepted values |
| --- | --- |
| `monthly` | `monthly`, `month` |
| `annual` | `annual`, `annually`, `yearly`, `year` |

### Statuses

| Canonical | Accepted values |
| --- | --- |
| `paid` | `paid`, `complete`, `completed`, `success` |
| `pending` | `pending`, `in_review`, `awaiting` |
| `failed` | `failed`, `declined`, `error` |
| `refunded` | `refunded`, `refund`, `charged_back` |
| `void` | `void`, `cancelled`, `canceled` |

### Booleans

| Canonical | Accepted values |
| --- | --- |
| `true` | `true`, `yes`, `1`, `y` |
| `false` | `false`, `no`, `0`, `n` |
| null | blank |

Unknown values in required categories quarantine the row with `unknown_<field>`. An unknown nonblank boolean becomes null with `unknown_churned` because churn is nullable.

## 6. Numeric and Currency Parsing

1. Trim whitespace.
2. Remove a single leading currency symbol (`$`, `€`, `£`), grouping commas, and one trailing currency code.
3. Parse the remaining signed decimal text with `Decimal`; never parse through binary float.
4. Treat integer text such as `31432` as exactly `31432.00`, not missing cents.
5. The explicit `currency` column controls FX. If a symbol or suffix disagrees, retain the row, use the column, and add `amount_currency_marker_mismatch`.
6. A non-numeric amount, non-positive seats, invalid discount, invalid CSAT, or negative support-ticket count quarantines the row.
7. A refunded row with a non-negative amount is retained but flagged `refund_non_negative`; it contributes zero to recognized revenue/refund metrics until reconciled.
8. A non-refunded negative amount is retained but flagged `unexpected_negative_amount`; signed revenue rules still apply only where the metric contract permits it.

FX calculations retain full `Decimal` precision. Currency values are rounded to two decimal places using `ROUND_HALF_UP` only for display and golden-output comparison after aggregation.

## 7. Date Parsing

Parsing is strict and attempted in this order:

1. `YYYY-MM-DD`
2. `YYYY/MM/DD`
3. abbreviated or full English month name followed by day and year, such as `Jan 5 2024`
4. numeric slash `MM/DD/YYYY`
5. numeric hyphen `DD-MM-YYYY`

For rules 4 and 5, if both numeric day/month components are between 1 and 12, add `<field>_date_ambiguous`. The locked separator rule still selects the canonical date; ambiguity is disclosed rather than guessed away.

Invalid `invoice_date` quarantines the row. Invalid `signup_date` yields null plus `signup_date_invalid`. Dates outside the supported forms are invalid even if a permissive parser could infer them.

## 8. Quality Flags

Stable codes include:

- `invoice_date_ambiguous`
- `signup_date_ambiguous`
- `signup_date_invalid`
- `amount_currency_marker_mismatch`
- `refund_non_negative`
- `unexpected_negative_amount`
- `contact_email_missing`
- `contact_email_malformed`
- `industry_missing`
- `payment_method_missing`
- `churned_unknown`
- `csat_unknown`
- `account_identity_conflict`

Quality flags do not alter row disposition unless a rule above explicitly says so.

## 9. Account Snapshot Contract

Account-level metrics use one snapshot per `account_id` selected from authoritative invoices:

1. greatest canonical `invoice_date`;
2. greatest `source_row` as the deterministic tie-breaker.

The snapshot supplies account name, region, plan, seats, discount, churn, CSAT, and other account attributes. If authoritative history for an account contains multiple normalized account names, regions, or industries, add `account_identity_conflict` to the snapshot and report the distinct values in diagnostics. The system does not merge accounts based on similar names or email domains.

## 10. Provenance and Artifacts

The canonical store records:

- source-file SHA-256;
- normalization contract version;
- ingestion timestamp as metadata only, never as a business tie-breaker;
- each source row's disposition and reason;
- authoritative/superseded links by source row;
- canonical fields, raw values, and quality flags.

Generated stores and indexes live outside tracked source files and are reproducible from the CSV plus versioned configuration.

## 11. Data Acceptance Tests

| ID | Acceptance case |
| --- | --- |
| `DATA-001` | Every documented plan, status, cycle, and boolean alias maps exactly; unknowns follow the null/quarantine policy. |
| `DATA-002` | Symbols, grouping commas, suffixes, integer amounts, negatives, FX values, and marker mismatches parse as specified. |
| `DATA-003` | Every supported date form, both ambiguity cases, and invalid dates produce the specified date/flag/disposition. |
| `DATA-004` | Exact duplicates collapse; repeated invoice IDs select the greatest source row and preserve superseded provenance. |
| `DATA-005` | Latest valid invoice date selects the account snapshot; source row breaks ties; identity conflicts are reported. |
| `DATA-006` | Reconciliation holds and all authoritative invoice IDs are unique. |
| `DATA-007` | Raw CSV remains byte-identical after ingestion. |
| `DATA-008` | Contact email appears in no chunk, prompt, log, citation, or evidence manifest. |

## 12. Known Limitations

- Separator-based date interpretation is deterministic but may differ from source intent.
- Last-row duplicate precedence is an export heuristic, not source-system reconciliation.
- Latest invoice attributes are a proxy for current account state.
- A current churn flag cannot establish when churn occurred.
- Fixed exercise FX rates are not suitable for audited production accounting.