from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal

from app.models import (
    AccountSnapshot,
    CanonicalInvoice,
    EvidenceRecord,
    JsonObject,
    MetricComputation,
    WarningRecord,
)

MONEY_QUANTUM = Decimal("0.01")
LIST_PRICE = {
    "starter": Decimal("49"),
    "pro": Decimal("99"),
    "enterprise": Decimal("299"),
}


def money(value: Decimal) -> str:
    return format(value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP), ".2f")


def calculate_mrr(invoice: CanonicalInvoice) -> Decimal:
    discount_multiplier = Decimal("1") - invoice.discount_pct / Decimal("100")
    return LIST_PRICE[invoice.plan] * invoice.seats * discount_multiplier


def recognized_contribution(invoice: CanonicalInvoice) -> Decimal:
    if invoice.status == "paid":
        return invoice.amount_usd_unrounded
    if invoice.status == "refunded" and invoice.amount_local < 0:
        return invoice.amount_usd_unrounded
    return Decimal("0")


def _evidence(
    invoice: CanonicalInvoice,
    reason: str,
    *,
    contribution: Decimal | None = None,
    fields: JsonObject | None = None,
) -> EvidenceRecord:
    base_fields: JsonObject = {
        "status": invoice.status,
        "plan": invoice.plan,
        "region": invoice.region,
        "invoice_date": invoice.invoice_date.isoformat(),
        "currency": invoice.currency,
        "amount_local": str(invoice.amount_local),
    }
    if fields:
        base_fields.update(fields)
    return EvidenceRecord(
        invoice_id=invoice.invoice_id,
        account_id=invoice.account_id,
        account_name=invoice.account_name,
        source_row=invoice.source_row,
        reason=reason,
        fields=base_fields,
        contribution_usd=money(contribution) if contribution is not None else None,
    )


def _sort_evidence(evidence: list[EvidenceRecord]) -> tuple[EvidenceRecord, ...]:
    return tuple(sorted(evidence, key=lambda item: (item.invoice_id, item.source_row)))


def _warning(code: str, message: str, count: int) -> tuple[WarningRecord, ...]:
    if count == 0:
        return ()
    return (WarningRecord(code=code, message=message, count=count),)


def recognized_revenue_2024(
    invoices: tuple[CanonicalInvoice, ...],
    snapshots: dict[str, AccountSnapshot],
) -> MetricComputation:
    del snapshots
    population = [invoice for invoice in invoices if invoice.invoice_date.year == 2024]
    paid = [invoice for invoice in population if invoice.status == "paid"]
    refunds = [
        invoice
        for invoice in population
        if invoice.status == "refunded" and invoice.amount_local < 0
    ]
    anomalies = [
        invoice
        for invoice in population
        if invoice.status == "refunded" and invoice.amount_local >= 0
    ]
    contributing = paid + refunds
    paid_total = sum((invoice.amount_usd_unrounded for invoice in paid), Decimal("0"))
    refund_total = sum((invoice.amount_usd_unrounded for invoice in refunds), Decimal("0"))
    ambiguous_count = sum(
        "invoice_date_ambiguous" in invoice.quality_flags for invoice in contributing
    )
    warnings = list(
        _warning(
            "ambiguous_dates_included",
            "Ambiguous dates were interpreted using the documented separator rule.",
            ambiguous_count,
        )
    )
    warnings.extend(
        _warning(
            "data_quality_anomaly_excluded",
            "Non-negative refund rows were excluded from recognized revenue.",
            len(anomalies),
        )
    )
    return MetricComputation(
        intent="recognized_revenue_2024",
        result={
            "net_revenue_usd": money(paid_total + refund_total),
            "paid_revenue_usd": money(paid_total),
            "refund_impact_usd": money(refund_total),
            "paid_invoice_count": len(paid),
            "refunded_invoice_count": len(refunds),
            "ambiguous_date_count": ambiguous_count,
            "excluded_anomaly_count": len(anomalies),
        },
        evidence=_sort_evidence(
            [
                _evidence(
                    invoice,
                    "recognized revenue contribution",
                    contribution=recognized_contribution(invoice),
                )
                for invoice in contributing
            ]
        ),
        warnings=tuple(warnings),
    )


def regional_average_mrr(
    invoices: tuple[CanonicalInvoice, ...],
    snapshots: dict[str, AccountSnapshot],
) -> MetricComputation:
    del invoices
    active = [snapshot for snapshot in snapshots.values() if snapshot.invoice.churned is False]
    churned_count = sum(snapshot.invoice.churned is True for snapshot in snapshots.values())
    unknown_count = sum(snapshot.invoice.churned is None for snapshot in snapshots.values())
    grouped: dict[str, list[AccountSnapshot]] = defaultdict(list)
    for snapshot in active:
        grouped[snapshot.invoice.region].append(snapshot)

    regions: list[JsonObject] = []
    sortable: list[tuple[Decimal, str, JsonObject]] = []
    for region, region_snapshots in grouped.items():
        total = sum(
            (calculate_mrr(snapshot.invoice) for snapshot in region_snapshots),
            Decimal("0"),
        )
        average = total / len(region_snapshots)
        item: JsonObject = {
            "region": region,
            "total_mrr_usd": money(total),
            "account_count": len(region_snapshots),
            "average_mrr_usd": money(average),
        }
        sortable.append((average, region, item))
    for _, _, item in sorted(sortable, key=lambda value: (-value[0], value[1])):
        regions.append(item)

    warnings = _warning(
        "unknown_churn_excluded",
        "Accounts with unknown churn state were excluded from active-account MRR.",
        unknown_count,
    )
    return MetricComputation(
        intent="regional_average_mrr",
        result={
            "regions": regions,
            "winner": regions[0]["region"] if regions else None,
            "churned_excluded_count": churned_count,
            "unknown_churn_excluded_count": unknown_count,
        },
        evidence=_sort_evidence(
            [
                _evidence(
                    snapshot.invoice,
                    "active account snapshot used for regional MRR",
                    contribution=calculate_mrr(snapshot.invoice),
                    fields={
                        "seats": snapshot.invoice.seats,
                        "discount_pct": str(snapshot.invoice.discount_pct),
                    },
                )
                for snapshot in active
            ]
        ),
        warnings=warnings,
    )


def refunds_total(
    invoices: tuple[CanonicalInvoice, ...],
    snapshots: dict[str, AccountSnapshot],
) -> MetricComputation:
    del snapshots
    refunds = [
        invoice
        for invoice in invoices
        if invoice.status == "refunded" and invoice.amount_local < 0
    ]
    anomalies = [
        invoice
        for invoice in invoices
        if invoice.status == "refunded" and invoice.amount_local >= 0
    ]
    revenue_impact = sum(
        (invoice.amount_usd_unrounded for invoice in refunds),
        Decimal("0"),
    )
    grouped: dict[str, list[CanonicalInvoice]] = defaultdict(list)
    for invoice in refunds:
        grouped[invoice.currency].append(invoice)
    currency_breakdown = [
        {
            "currency": currency,
            "invoice_count": len(group),
            "local_total_signed": money(
                sum((invoice.amount_local for invoice in group), Decimal("0"))
            ),
        }
        for currency, group in sorted(grouped.items())
    ]
    warnings = _warning(
        "data_quality_anomaly_excluded",
        "Non-negative refund rows were excluded from the refund total.",
        len(anomalies),
    )
    return MetricComputation(
        intent="refunds_total",
        result={
            "amount_given_back_usd": money(abs(revenue_impact)),
            "revenue_impact_usd": money(revenue_impact),
            "refund_invoice_count": len(refunds),
            "excluded_anomaly_count": len(anomalies),
            "currency_breakdown": currency_breakdown,
        },
        evidence=_sort_evidence(
            [
                _evidence(
                    invoice,
                    "refund contribution",
                    contribution=invoice.amount_usd_unrounded,
                )
                for invoice in refunds
            ]
        ),
        warnings=warnings,
    )


def plan_churn_comparison(
    invoices: tuple[CanonicalInvoice, ...],
    snapshots: dict[str, AccountSnapshot],
) -> MetricComputation:
    del invoices
    plans: JsonObject = {}
    rates: dict[str, Decimal] = {}
    evidence: list[EvidenceRecord] = []
    unknown_total = 0
    for plan in ("enterprise", "starter"):
        plan_snapshots = [
            snapshot for snapshot in snapshots.values() if snapshot.invoice.plan == plan
        ]
        known = [snapshot for snapshot in plan_snapshots if snapshot.invoice.churned is not None]
        churned = [snapshot for snapshot in known if snapshot.invoice.churned is True]
        rate = (
            Decimal(len(churned)) / Decimal(len(known)) * Decimal("100")
            if known
            else Decimal("0")
        )
        unknown_count = len(plan_snapshots) - len(known)
        unknown_total += unknown_count
        rates[plan] = rate
        plans[plan] = {
            "churned_account_count": len(churned),
            "known_account_count": len(known),
            "churn_rate_pct": money(rate),
            "unknown_excluded_count": unknown_count,
        }
        evidence.extend(
            _evidence(
                snapshot.invoice,
                "account snapshot in churn denominator",
                fields={"churned": snapshot.invoice.churned},
            )
            for snapshot in known
        )
    return MetricComputation(
        intent="plan_churn_comparison",
        result={
            "plans": plans,
            "percentage_point_difference": money(rates["enterprise"] - rates["starter"]),
        },
        evidence=_sort_evidence(evidence),
        warnings=_warning(
            "unknown_churn_excluded",
            "Accounts with unknown churn state were excluded from churn rates.",
            unknown_total,
        ),
    )


def top_accounts_revenue(
    invoices: tuple[CanonicalInvoice, ...],
    snapshots: dict[str, AccountSnapshot],
) -> MetricComputation:
    grouped: dict[str, list[CanonicalInvoice]] = defaultdict(list)
    for invoice in invoices:
        if recognized_contribution(invoice) != 0:
            grouped[invoice.account_id].append(invoice)

    sortable: list[tuple[Decimal, str, JsonObject]] = []
    for account_id, group in grouped.items():
        revenue = sum((recognized_contribution(invoice) for invoice in group), Decimal("0"))
        if revenue == 0:
            continue
        snapshot = snapshots[account_id].invoice
        csat_status = (
            "unknown"
            if snapshot.csat_score is None
            else ("low" if snapshot.csat_score <= 2 else "ok")
        )
        sortable.append(
            (
                revenue,
                account_id,
                {
                    "account_id": account_id,
                    "account_name": snapshot.account_name,
                    "revenue_usd": money(revenue),
                    "csat_score": snapshot.csat_score,
                    "csat_status": csat_status,
                    "contributing_invoice_count": len(group),
                },
            )
        )
    top_five = sorted(sortable, key=lambda item: (-item[0], item[1]))[:5]
    accounts: list[JsonObject] = []
    top_ids: set[str] = set()
    for rank, (_, account_id, item) in enumerate(top_five, start=1):
        item["rank"] = rank
        accounts.append(item)
        top_ids.add(account_id)

    evidence = [
        _evidence(
            invoice,
            "recognized revenue for ranked account",
            contribution=recognized_contribution(invoice),
        )
        for invoice in invoices
        if invoice.account_id in top_ids and recognized_contribution(invoice) != 0
    ]
    return MetricComputation(
        intent="top_accounts_revenue",
        result={"accounts": accounts},
        evidence=_sort_evidence(evidence),
    )


def payment_exposure(
    invoices: tuple[CanonicalInvoice, ...],
    snapshots: dict[str, AccountSnapshot],
) -> MetricComputation:
    del snapshots
    exposed = [invoice for invoice in invoices if invoice.status in {"pending", "failed"}]
    breakdown: JsonObject = {}
    for status in ("pending", "failed"):
        status_invoices = [invoice for invoice in exposed if invoice.status == status]
        breakdown[status] = {
            "invoice_count": len(status_invoices),
            "exposure_usd": money(
                sum(
                    (abs(invoice.amount_usd_unrounded) for invoice in status_invoices),
                    Decimal("0"),
                )
            ),
        }
    negative_count = sum(invoice.amount_local < 0 for invoice in exposed)
    return MetricComputation(
        intent="payment_exposure",
        result={
            "invoice_count": len(exposed),
            "exposure_usd": money(
                sum(
                    (abs(invoice.amount_usd_unrounded) for invoice in exposed),
                    Decimal("0"),
                )
            ),
            "breakdown": breakdown,
            "negative_amount_anomaly_count": negative_count,
        },
        evidence=_sort_evidence(
            [
                _evidence(
                    invoice,
                    "pending or failed invoice exposure",
                    contribution=abs(invoice.amount_usd_unrounded),
                )
                for invoice in exposed
            ]
        ),
        warnings=_warning(
            "data_quality_anomaly_excluded",
            "Negative pending or failed amounts were treated as absolute exposure.",
            negative_count,
        ),
    )


MetricFunction = Callable[
    [tuple[CanonicalInvoice, ...], dict[str, AccountSnapshot]],
    MetricComputation,
]

METRIC_FUNCTIONS: dict[str, MetricFunction] = {
    "recognized_revenue_2024": recognized_revenue_2024,
    "regional_average_mrr": regional_average_mrr,
    "refunds_total": refunds_total,
    "plan_churn_comparison": plan_churn_comparison,
    "top_accounts_revenue": top_accounts_revenue,
    "payment_exposure": payment_exposure,
}