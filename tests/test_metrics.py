from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from app.ingestion import ingest_csv
from app.metrics import METRIC_FUNCTIONS, calculate_mrr
from app.models import IngestionResult

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def ingestion() -> IngestionResult:
    return ingest_csv(ROOT / "cloudnova_invoices.csv")


@pytest.fixture(scope="module")
def golden() -> dict[str, object]:
    return json.loads((ROOT / "evals" / "golden.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("intent", sorted(METRIC_FUNCTIONS))
def test_metric_matches_independent_golden(
    intent: str,
    ingestion: IngestionResult,
    golden: dict[str, object],
) -> None:
    expected_metrics = golden["metrics"]
    assert isinstance(expected_metrics, dict)
    expected = expected_metrics[intent]
    assert isinstance(expected, dict)

    computation = METRIC_FUNCTIONS[intent](ingestion.invoices, ingestion.account_snapshots)

    assert computation.intent == intent
    assert computation.result == expected["result"]
    actual_evidence = []
    for item in computation.evidence:
        projected = {
            "invoice_id": item.invoice_id,
            "source_row": item.source_row,
        }
        if item.contribution_usd is not None:
            projected["contribution_usd"] = item.contribution_usd
        actual_evidence.append(projected)
    assert actual_evidence == expected["evidence"]


def test_mrr_uses_list_price_not_invoice_amount_or_cycle(ingestion: IngestionResult) -> None:
    invoice = ingestion.invoices[0]
    expected = Decimal("49") * invoice.seats * (
        Decimal("1") - invoice.discount_pct / Decimal("100")
    )

    starter = replace(invoice, plan="starter", billing_cycle="annual", currency="GBP")
    monthly = replace(starter, billing_cycle="monthly", amount_local=Decimal("0.01"))

    assert calculate_mrr(starter) == expected
    assert calculate_mrr(monthly) == expected


def test_all_required_metric_intents_exist() -> None:
    assert set(METRIC_FUNCTIONS) == {
        "recognized_revenue_2024",
        "regional_average_mrr",
        "refunds_total",
        "plan_churn_comparison",
        "top_accounts_revenue",
        "payment_exposure",
    }