from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from app.ingestion import ingest_csv

HEADER = [
    "invoice_id",
    "account_id",
    "account_name",
    "contact_email",
    "region",
    "industry",
    "plan",
    "billing_cycle",
    "seats",
    "currency",
    "amount",
    "discount_pct",
    "status",
    "payment_method",
    "signup_date",
    "invoice_date",
    "churned",
    "csat_score",
    "support_tickets",
]


def row(**overrides: str) -> dict[str, str]:
    values = {
        "invoice_id": "INV-1",
        "account_id": "ACC-1",
        "account_name": "Acme Corp",
        "contact_email": "billing@acme.test",
        "region": "NA",
        "industry": "Software",
        "plan": "Starter",
        "billing_cycle": "monthly",
        "seats": "10",
        "currency": "USD",
        "amount": "490.00",
        "discount_pct": "0",
        "status": "paid",
        "payment_method": "ACH",
        "signup_date": "2023-01-01",
        "invoice_date": "2024-01-01",
        "churned": "false",
        "csat_score": "4",
        "support_tickets": "1",
    }
    values.update(overrides)
    return values


def write_fixture(path: Path, rows: list[dict[str, str]]) -> bytes:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=HEADER)
        writer.writeheader()
        writer.writerows(rows)
    return path.read_bytes()


def test_ingestion_reconciles_dispositions_and_snapshots(tmp_path: Path) -> None:
    first = row()
    fixture_rows = [
        first,
        dict(first),
        row(status="pending", amount="500.00"),
        row(invoice_id="INV-BAD", amount="not-money"),
        row(
            invoice_id="INV-2",
            account_name="Acme Holdings",
            region="EMEA",
            invoice_date="2024-06-01",
        ),
        row(
            invoice_id="INV-3",
            account_name="Acme Holdings",
            region="EMEA",
            invoice_date="2024-06-01",
            status="paid",
        ),
    ]
    source_path = tmp_path / "invoices.csv"
    source_bytes = write_fixture(source_path, fixture_rows)

    result = ingest_csv(source_path)

    assert result.profile.source_data_rows == 6
    assert result.profile.disposition_counts == {
        "authoritative": 3,
        "exact_duplicate": 1,
        "quarantined": 1,
        "superseded": 1,
    }
    assert result.profile.source_sha256 == hashlib.sha256(source_bytes).hexdigest()
    assert source_path.read_bytes() == source_bytes

    dispositions = {item.source_row: item for item in result.dispositions}
    assert dispositions[2].disposition == "superseded"
    assert dispositions[2].related_source_row == 4
    assert dispositions[3].disposition == "exact_duplicate"
    assert dispositions[3].related_source_row == 2
    assert dispositions[4].disposition == "authoritative"
    assert dispositions[5].disposition == "quarantined"
    assert dispositions[5].reason == "invalid_amount"

    snapshot = result.account_snapshots["ACC-1"]
    assert snapshot.invoice.invoice_id == "INV-3"
    assert snapshot.invoice.source_row == 7
    assert snapshot.identity_conflicts == {
        "account_name": ("Acme Corp", "Acme Holdings"),
        "region": ("EMEA", "NA"),
    }
    assert "account_identity_conflict" in snapshot.quality_flags


def test_full_source_profile_matches_frozen_oracle() -> None:
    root = Path(__file__).resolve().parents[1]
    golden = json.loads((root / "evals" / "golden.json").read_text(encoding="utf-8"))

    result = ingest_csv(root / "cloudnova_invoices.csv")

    assert result.profile.source_sha256 == golden["dataset"]["source_sha256"]
    assert result.profile.source_bytes == golden["dataset"]["source_bytes"]
    assert result.profile.source_data_rows == golden["dataset"]["source_data_rows"]
    assert result.profile.authoritative_invoice_count == golden["dataset"][
        "authoritative_invoice_count"
    ]
    assert result.profile.account_snapshot_count == golden["dataset"]["account_snapshot_count"]
    assert result.profile.disposition_counts == golden["dataset"]["dispositions"]
    assert result.profile.quality_flag_counts == golden["dataset"]["quality_flag_counts"]