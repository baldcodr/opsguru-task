# CloudNova — Business Context & Data Dictionary

> This is the "customer briefing" you'd get on day one of an embedding. Read it, then use it to write your spec. It is deliberately a mix of hard rules and soft context — part of the exercise is deciding what matters.

## The company

**CloudNova** is a (fictional) B2B SaaS company. It sells a workflow product to other businesses on a per-seat subscription. Finance exports the invoice ledger to cloudnova\_invoices.csv (\~5k rows). Each row is **one invoice** issued to a customer **account**. An account can appear on many invoices over time.

The export is dirty because it's stitched together from three source systems (an old billing tool, a CRM, and a spreadsheet the finance team maintains by hand). Nobody has owned data quality. That's why you're here.

## Pricing & revenue rules (the business logic)

- **List price per seat per month:** Starter $49, Pro $99, Enterprise $299 (USD).  
- **Billing cycle:** monthly or annual. **Annual invoices bill 10 months, not 12** — customers get 2 months free as an annual incentive.  
- **Discounts:** discount\_pct is applied to the gross invoice amount.  
- **Invoice amount** is stored in the account's local currency (USD/EUR/GBP). To compare or sum revenue, normalize to USD. Reference FX used to generate the data: EUR→USD 1.08, GBP→USD 1.27 (fine to treat as fixed for this exercise).  
- **MRR (monthly recurring revenue)** for an active subscription \= list\_price\[plan\] × seats × (1 − discount\_pct/100), in USD. (Annual invoices still map to the same underlying MRR — don't double-count the annual lump sum.)  
- **What counts as recognized revenue:** only invoices whose status normalizes to **paid**. pending/failed/void are **not** revenue. refunded rows carry a **negative** amount and should net against revenue.

## Status meanings (after you normalize them)

| Canonical | Dirty variants you'll see | Counts as revenue? |
| :---- | :---- | :---- |
| paid | Paid, PAID, Complete, completed, success | ✅ yes |
| pending | Pending, PENDING, in\_review, awaiting | ❌ no |
| failed | Failed, declined, error | ❌ no |
| refunded | Refunded, REFUND, charged\_back | ➖ negative (nets out) |
| void | Void, cancelled, canceled | ❌ no |

## Known data-quality issues (non-exhaustive — find the rest)

- **Inconsistent categories:** plan and status appear in many casings/spellings (Pro/pro/PRO/Professional/Tier 2). billing\_cycle mixes annual/Annual/annually/yearly.  
- **Mixed date formats:** 2024-01-05, 01/05/2024, 2024/01/05, Jan 5 2024, and some 05-01-2024 that are genuinely ambiguous (day-vs-month). Decide and document your parsing rule.  
- **Amounts as strings:** some are clean floats, others are "$4,900.00", "31432" (missing cents), or "1,200.00 EUR". Refunds are negative.  
- **Nulls:** contact\_email, industry, csat\_score are sometimes blank.  
- **Malformed emails:** a few have \_at\_ instead of @.  
- **Duplicates:** there are full-duplicate rows **and** near-duplicates (same invoice\_id, different status/amount) from the systems disagreeing. Decide which record wins and document the rule.  
- **Booleans:** churned shows up as true/TRUE/Yes/1/Y and false/FALSE/No/0/N.

## Column reference

| Column | Meaning |
| :---- | :---- |
| invoice\_id | Unique-ish invoice key (duplicated in the dirty near-dupes). |
| account\_id / account\_name | The customer account. |
| contact\_email | Billing contact (may be null/malformed). |
| region | NA / EMEA / APAC / LATAM. |
| industry | Account's industry (may be null). |
| plan | Starter / Pro / Enterprise (dirty). |
| billing\_cycle | monthly / annual (dirty). |
| seats | Licensed seats on the invoice. |
| currency | USD / EUR / GBP — invoice is in this currency. |
| amount | Invoice amount as a (often messy) string; negative if refunded. |
| discount\_pct | Percentage discount applied. |
| status | Payment status (dirty). |
| payment\_method | credit\_card / ACH / wire / invoice (dirty; may be blank). |
| signup\_date | When the account first signed up (dirty format). |
| invoice\_date | When this invoice was issued (dirty format). |
| churned | Whether the account has since churned (dirty boolean). |
| csat\_score | Latest CSAT 1–5 (may be null). |
| support\_tickets | Tickets opened by the account. |

## Questions a stakeholder might actually ask

Use these to seed your eval cases (and your NL-query / RAG test questions):

1. "What was our total recognized revenue in USD for **paid** invoices in 2024?"  
2. "Which **region** has the highest average MRR per account?"  
3. "How much have we given back in **refunds**?"  
4. "What's the **churn rate** among Enterprise accounts vs Starter?"  
5. "List the top 5 accounts by revenue, and flag any with **CSAT ≤ 2**."  
6. "How many invoices are stuck in **pending/failed** and what's the exposed $?"

>   
> A good submission can answer several of these **correctly and cite how**. A great one is honest about which ones it gets wrong and why (e.g. ambiguous dates, dedup choices).  
