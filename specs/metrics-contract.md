# CloudNova Metric Contract

Status: Approved for implementation  
Version: 1

## 1. Shared Rules

All calculations use authoritative canonical records from `specs/data-contract.md` and `Decimal` arithmetic.

- USD FX rates: USD `1.00`, EUR `1.08`, GBP `1.27`.
- List price per seat per month: Starter `$49`, Pro `$99`, Enterprise `$299`.
- Displayed USD values round to cents with `ROUND_HALF_UP` after aggregation.
- Percentages are computed from integer counts and displayed to two decimal places.
- Empty populations return a typed `no_data` result, not zero.
- Rankings sort by the requested metric descending, then stable identifier ascending.
- Every result returns structured intermediary counts, warnings, and evidence record IDs.
- Rows with `invoice_date_ambiguous` remain included under the locked parsing policy and contribute an ambiguity warning count.

## 2. METRIC-001: Recognized Revenue in 2024

**Question:** What was total recognized revenue in USD for paid invoices in 2024?

**Population:** authoritative invoices with canonical `invoice_date` from `2024-01-01` through `2024-12-31`, inclusive.

**Contribution:**

```text
paid       -> amount_usd_unrounded
refunded   -> amount_usd_unrounded only when amount_local < 0
pending    -> 0
failed     -> 0
void       -> 0
```

The metric is net recognized revenue: paid contributions plus negative refund contributions. `refund_non_negative` rows do not contribute and produce a warning. Annual invoices contribute the stored lump sum once; they are not multiplied, divided, or amortized.

**Result fields:** `net_revenue_usd`, `paid_revenue_usd`, `refund_impact_usd`, `paid_invoice_count`, `refunded_invoice_count`, `ambiguous_date_count`, `excluded_anomaly_count`.

**Evidence:** every contributing paid or valid negative refunded invoice, with signed USD contribution.

**Acceptance:** exact values to cents, exact counts and evidence membership, and `net = paid + refund_impact` before final display rounding.

## 3. METRIC-002: Highest Average MRR per Account by Region

**Question:** Which region has the highest average MRR per account?

**Population:** one latest account snapshot per `account_id` where `churned=false`. Snapshots where churn is true or unknown are excluded and counted separately.

**Account MRR:**

$$
\operatorname{MRR} = \operatorname{listPrice}(plan) \times seats \times \left(1 - \frac{discount\_pct}{100}\right)
$$

MRR is denominated in USD because list prices are USD. Invoice currency and billing cycle do not change MRR. In particular, annual invoice amount is not divided by 10 or 12 to derive MRR.

**Regional average:** sum account MRR for included account snapshots in the region, divided by the count of included unique accounts.

**Result fields:** ordered regions with `region`, `total_mrr_usd`, `account_count`, and `average_mrr_usd`; `winner`; `churned_excluded_count`; `unknown_churn_excluded_count`.

**Evidence:** the selected snapshot invoice for each included account, with its MRR inputs and contribution.

**Acceptance:** exact regional numerators, denominators, averages, winner, exclusion counts, and evidence membership. Region ties sort by region code ascending.

## 4. METRIC-003: Refunds Given Back

**Question:** How much have we given back in refunds?

**Population:** all authoritative invoices with canonical status `refunded` and negative `amount_local`.

**Calculations:**

- `amount_given_back_usd = abs(sum(amount_usd_unrounded))`
- `revenue_impact_usd = sum(amount_usd_unrounded)`

Non-negative refunded rows are excluded and counted as anomalies.

**Result fields:** `amount_given_back_usd`, `revenue_impact_usd`, `refund_invoice_count`, `excluded_anomaly_count`, and per-currency counts/local totals.

**Evidence:** every included refunded invoice with signed USD contribution.

**Acceptance:** exact values to cents, exact counts, `amount_given_back = abs(revenue_impact)`, and complete evidence membership.

## 5. METRIC-004: Enterprise Versus Starter Churn

**Question:** What is the churn rate among Enterprise accounts versus Starter?

**Population:** latest account snapshots whose canonical plan is `enterprise` or `starter` and whose churn value is known. Unknown churn snapshots are excluded and counted by plan.

**Rate:**

$$
\operatorname{churnRate}(plan) = \frac{\text{unique accounts with churned=true}}{\text{unique accounts with known churn}} \times 100
$$

**Result fields:** for each plan, `churned_account_count`, `known_account_count`, `churn_rate_pct`, `unknown_excluded_count`; plus `percentage_point_difference` defined as Enterprise minus Starter.

**Evidence:** the selected snapshot invoice for every account in each known denominator, labelled churned or active.

**Acceptance:** exact unique-account counts, percentages, difference, unknown exclusions, and evidence membership. Invoice rows must never be used as the denominator.

## 6. METRIC-005: Top Five Accounts by Revenue and CSAT Risk

**Question:** List the top five accounts by revenue and flag any with CSAT at most 2.

**Population:** all authoritative invoices across all dates.

**Recognized contribution:** paid signed USD amounts plus valid negative refunded USD amounts; pending, failed, void, and non-negative refund anomalies contribute zero.

Revenue is grouped by `account_id`. The account's displayed name and CSAT come from its latest account snapshot.

**Ranking:** net recognized revenue descending, then `account_id` ascending. Return exactly five accounts when at least five have a non-zero recognized contribution.

**CSAT status:**

- numeric score at most 2 -> `low`;
- numeric score above 2 -> `ok`;
- null -> `unknown`.

**Result fields:** ranked entries with `rank`, `account_id`, `account_name`, `revenue_usd`, `csat_score`, `csat_status`, and `contributing_invoice_count`.

**Evidence:** every contributing paid/refunded invoice for each returned account, not only one sample.

**Acceptance:** exact ordered IDs, names from latest snapshots, revenue values, CSAT labels, counts, and complete evidence membership.

## 7. METRIC-006: Pending and Failed Exposure

**Question:** How many invoices are stuck in pending or failed, and what is the exposed amount?

**Population:** all authoritative invoices whose canonical status is `pending` or `failed`.

**Exposure contribution:** `abs(amount_usd_unrounded)`. A negative pending/failed amount is retained, flagged as anomalous, and contributes its absolute value because exposure is a magnitude.

**Result fields:** `invoice_count`, `exposure_usd`, and a breakdown for `pending` and `failed`, each containing count and USD exposure; `negative_amount_anomaly_count`.

**Evidence:** every pending/failed invoice with its absolute USD contribution.

**Acceptance:** exact overall and per-status counts/totals, exact anomaly count, and complete evidence membership.

## 8. Unsupported Metrics

The service must return `unsupported_metric` when required source data or an approved definition is absent. The response names the missing field or business rule and does not provide an estimated number.

Required expected limitation:

- “What was monthly churn in 2024?” cannot be calculated because the source contains a current churn flag but no churn date or active-period history.

Other unsupported examples include ARR, recognized-revenue amortization schedules, live-FX restatement, and churn cohorts.

## 9. Metric Test Requirements

| ID | Acceptance case |
| --- | --- |
| `BUS-001` | METRIC-001 exact totals, status counts, warnings, and evidence set match the independent oracle. |
| `BUS-002` | METRIC-002 exact regional values, winner, exclusions, and account-snapshot evidence match the oracle. |
| `BUS-003` | METRIC-003 exact positive giveback, negative impact, currency breakdown, anomalies, and evidence match. |
| `BUS-004` | METRIC-004 exact account numerators/denominators/rates/difference/exclusions and evidence match. |
| `BUS-005` | METRIC-005 exact order, tie-breaks, revenue, snapshot names/CSAT labels, and evidence match. |
| `BUS-006` | METRIC-006 exact counts, totals, breakdowns, anomalies, and evidence match. |
| `BUS-007` | Annual paid invoices contribute their stored amount once to revenue and use list-price MRR without a 10- or 12-month multiplier. |
| `BUS-008` | Every metric yields the same structured result with hosted synthesis disabled or failing. |