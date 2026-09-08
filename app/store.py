from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from app.models import (
    AccountSnapshot,
    BillingCycle,
    CanonicalInvoice,
    Currency,
    DispositionKind,
    IngestionResult,
    InvoiceStatus,
    Plan,
    SourceDisposition,
)

NORMALIZATION_VERSION = "1"


def structured_fingerprint(source_sha256: str) -> str:
    payload = f"source={source_sha256}\nnormalization={NORMALIZATION_VERSION}\n"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA journal_mode = DELETE;
        PRAGMA foreign_keys = ON;

        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE invoices (
            source_row INTEGER PRIMARY KEY,
            invoice_id TEXT NOT NULL UNIQUE,
            account_id TEXT NOT NULL,
            account_name TEXT NOT NULL,
            region TEXT NOT NULL,
            industry TEXT,
            plan TEXT NOT NULL,
            billing_cycle TEXT NOT NULL,
            seats INTEGER NOT NULL,
            currency TEXT NOT NULL,
            amount_local TEXT NOT NULL,
            fx_to_usd TEXT NOT NULL,
            amount_usd_unrounded TEXT NOT NULL,
            discount_pct TEXT NOT NULL,
            status TEXT NOT NULL,
            payment_method TEXT,
            signup_date TEXT,
            invoice_date TEXT NOT NULL,
            churned INTEGER,
            csat_score INTEGER,
            support_tickets INTEGER NOT NULL,
            quality_flags_json TEXT NOT NULL,
            raw_values_json TEXT NOT NULL
        );

        CREATE INDEX invoices_account_id_idx ON invoices(account_id);
        CREATE INDEX invoices_status_idx ON invoices(status);
        CREATE INDEX invoices_invoice_date_idx ON invoices(invoice_date);

        CREATE TABLE dispositions (
            source_row INTEGER PRIMARY KEY,
            disposition TEXT NOT NULL,
            reason TEXT,
            related_source_row INTEGER,
            invoice_id TEXT
        );

        CREATE TABLE account_snapshots (
            account_id TEXT PRIMARY KEY,
            selected_source_row INTEGER NOT NULL,
            identity_conflicts_json TEXT NOT NULL,
            FOREIGN KEY(selected_source_row) REFERENCES invoices(source_row)
        );
        """
    )


def write_canonical_store(path: Path, ingestion: IngestionResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    temporary_path.unlink(missing_ok=True)

    metadata = {
        "source_sha256": ingestion.profile.source_sha256,
        "source_bytes": str(ingestion.profile.source_bytes),
        "source_data_rows": str(ingestion.profile.source_data_rows),
        "authoritative_invoice_count": str(ingestion.profile.authoritative_invoice_count),
        "account_snapshot_count": str(ingestion.profile.account_snapshot_count),
        "disposition_counts": _json(ingestion.profile.disposition_counts),
        "quality_flag_counts": _json(ingestion.profile.quality_flag_counts),
        "normalization_version": NORMALIZATION_VERSION,
        "structured_fingerprint": structured_fingerprint(ingestion.profile.source_sha256),
    }

    try:
        with sqlite3.connect(temporary_path) as connection:
            _create_schema(connection)
            connection.executemany(
                "INSERT INTO metadata(key, value) VALUES (?, ?)",
                sorted(metadata.items()),
            )
            connection.executemany(
                """
                INSERT INTO invoices(
                    source_row, invoice_id, account_id, account_name, region, industry,
                    plan, billing_cycle, seats, currency, amount_local, fx_to_usd,
                    amount_usd_unrounded, discount_pct, status, payment_method,
                    signup_date, invoice_date, churned, csat_score, support_tickets,
                    quality_flags_json, raw_values_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        invoice.source_row,
                        invoice.invoice_id,
                        invoice.account_id,
                        invoice.account_name,
                        invoice.region,
                        invoice.industry,
                        invoice.plan,
                        invoice.billing_cycle,
                        invoice.seats,
                        invoice.currency,
                        str(invoice.amount_local),
                        str(invoice.fx_to_usd),
                        str(invoice.amount_usd_unrounded),
                        str(invoice.discount_pct),
                        invoice.status,
                        invoice.payment_method,
                        invoice.signup_date.isoformat() if invoice.signup_date else None,
                        invoice.invoice_date.isoformat(),
                        None if invoice.churned is None else int(invoice.churned),
                        invoice.csat_score,
                        invoice.support_tickets,
                        _json(invoice.quality_flags),
                        _json(invoice.raw_values),
                    )
                    for invoice in ingestion.invoices
                ],
            )
            connection.executemany(
                """
                INSERT INTO dispositions(
                    source_row, disposition, reason, related_source_row, invoice_id
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.source_row,
                        item.disposition,
                        item.reason,
                        item.related_source_row,
                        item.invoice_id,
                    )
                    for item in ingestion.dispositions
                ],
            )
            connection.executemany(
                """
                INSERT INTO account_snapshots(
                    account_id, selected_source_row, identity_conflicts_json
                ) VALUES (?, ?, ?)
                """,
                [
                    (
                        account_id,
                        snapshot.invoice.source_row,
                        _json(snapshot.identity_conflicts),
                    )
                    for account_id, snapshot in sorted(ingestion.account_snapshots.items())
                ],
            )
        os.replace(temporary_path, path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _connect(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(f"Canonical store not found: {path}")
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def load_metadata(path: Path) -> dict[str, str]:
    with _connect(path) as connection:
        rows = connection.execute("SELECT key, value FROM metadata ORDER BY key").fetchall()
    return {cast(str, row["key"]): cast(str, row["value"]) for row in rows}


def _invoice_from_row(row: sqlite3.Row) -> CanonicalInvoice:
    raw_values = json.loads(cast(str, row["raw_values_json"]))
    quality_flags = json.loads(cast(str, row["quality_flags_json"]))
    return CanonicalInvoice(
        invoice_id=cast(str, row["invoice_id"]),
        account_id=cast(str, row["account_id"]),
        account_name=cast(str, row["account_name"]),
        region=cast(str, row["region"]),
        industry=cast(str | None, row["industry"]),
        plan=cast(Plan, row["plan"]),
        billing_cycle=cast(BillingCycle, row["billing_cycle"]),
        seats=cast(int, row["seats"]),
        currency=cast(Currency, row["currency"]),
        amount_local=Decimal(cast(str, row["amount_local"])),
        fx_to_usd=Decimal(cast(str, row["fx_to_usd"])),
        amount_usd_unrounded=Decimal(cast(str, row["amount_usd_unrounded"])),
        discount_pct=Decimal(cast(str, row["discount_pct"])),
        status=cast(InvoiceStatus, row["status"]),
        payment_method=cast(str | None, row["payment_method"]),
        signup_date=(
            date.fromisoformat(cast(str, row["signup_date"]))
            if row["signup_date"] is not None
            else None
        ),
        invoice_date=date.fromisoformat(cast(str, row["invoice_date"])),
        churned=None if row["churned"] is None else bool(row["churned"]),
        csat_score=cast(int | None, row["csat_score"]),
        support_tickets=cast(int, row["support_tickets"]),
        source_row=cast(int, row["source_row"]),
        quality_flags=tuple(cast(list[str], quality_flags)),
        raw_values=cast(dict[str, str], raw_values),
    )


def load_invoices(path: Path) -> tuple[CanonicalInvoice, ...]:
    with _connect(path) as connection:
        rows = connection.execute("SELECT * FROM invoices ORDER BY source_row").fetchall()
    return tuple(_invoice_from_row(row) for row in rows)


def load_dispositions(path: Path) -> tuple[SourceDisposition, ...]:
    with _connect(path) as connection:
        rows = connection.execute("SELECT * FROM dispositions ORDER BY source_row").fetchall()
    return tuple(
        SourceDisposition(
            source_row=cast(int, row["source_row"]),
            disposition=cast(DispositionKind, row["disposition"]),
            reason=cast(str | None, row["reason"]),
            related_source_row=cast(int | None, row["related_source_row"]),
            invoice_id=cast(str | None, row["invoice_id"]),
        )
        for row in rows
    )


def load_account_snapshots(path: Path) -> dict[str, AccountSnapshot]:
    invoices = {invoice.source_row: invoice for invoice in load_invoices(path)}
    with _connect(path) as connection:
        rows = connection.execute(
            "SELECT * FROM account_snapshots ORDER BY account_id"
        ).fetchall()
    snapshots: dict[str, AccountSnapshot] = {}
    for row in rows:
        conflicts = cast(
            dict[str, list[str]],
            json.loads(cast(str, row["identity_conflicts_json"])),
        )
        snapshots[cast(str, row["account_id"])] = AccountSnapshot(
            invoice=invoices[cast(int, row["selected_source_row"])],
            identity_conflicts={key: tuple(values) for key, values in conflicts.items()},
        )
    return snapshots