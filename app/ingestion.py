from __future__ import annotations

import csv
import hashlib
from collections import Counter, defaultdict
from pathlib import Path

from app.models import (
    AccountSnapshot,
    CanonicalInvoice,
    IngestionProfile,
    IngestionResult,
    SourceDisposition,
)
from app.normalization import NormalizationError, normalize_invoice


def select_account_snapshots(
    invoices: tuple[CanonicalInvoice, ...] | list[CanonicalInvoice],
) -> dict[str, AccountSnapshot]:
    grouped: dict[str, list[CanonicalInvoice]] = defaultdict(list)
    for invoice in invoices:
        grouped[invoice.account_id].append(invoice)

    snapshots: dict[str, AccountSnapshot] = {}
    for account_id, group in grouped.items():
        selected = max(group, key=lambda invoice: (invoice.invoice_date, invoice.source_row))
        conflicts: dict[str, tuple[str, ...]] = {}
        for field in ("account_name", "region", "industry"):
            values = tuple(
                sorted(
                    {
                        value
                        for invoice in group
                        if (value := getattr(invoice, field)) is not None
                    }
                )
            )
            if len(values) > 1:
                conflicts[field] = values
        snapshots[account_id] = AccountSnapshot(
            invoice=selected,
            identity_conflicts=conflicts,
        )
    return snapshots


def ingest_csv(path: Path) -> IngestionResult:
    source_bytes = path.read_bytes()
    with path.open(newline="", encoding="utf-8") as source_file:
        reader = csv.DictReader(source_file)
        if reader.fieldnames is None:
            raise ValueError("CSV header is missing")
        fieldnames = tuple(reader.fieldnames)
        raw_rows = list(reader)

    dispositions: dict[int, SourceDisposition] = {}
    first_raw_occurrence: dict[tuple[str, ...], int] = {}
    valid_nonduplicates: list[CanonicalInvoice] = []

    for source_row, raw in enumerate(raw_rows, start=2):
        try:
            invoice = normalize_invoice(raw, source_row)
        except NormalizationError as error:
            dispositions[source_row] = SourceDisposition(
                source_row=source_row,
                disposition="quarantined",
                reason=error.code,
                invoice_id=raw.get("invoice_id", "").strip() or None,
            )
            continue

        raw_key = tuple(raw[field] for field in fieldnames)
        if raw_key in first_raw_occurrence:
            dispositions[source_row] = SourceDisposition(
                source_row=source_row,
                disposition="exact_duplicate",
                related_source_row=first_raw_occurrence[raw_key],
                invoice_id=invoice.invoice_id,
            )
            continue

        first_raw_occurrence[raw_key] = source_row
        valid_nonduplicates.append(invoice)

    invoice_groups: dict[str, list[CanonicalInvoice]] = defaultdict(list)
    for invoice in valid_nonduplicates:
        invoice_groups[invoice.invoice_id].append(invoice)

    authoritative: list[CanonicalInvoice] = []
    for invoice_id, group in invoice_groups.items():
        ordered = sorted(group, key=lambda invoice: invoice.source_row)
        winner = ordered[-1]
        dispositions[winner.source_row] = SourceDisposition(
            source_row=winner.source_row,
            disposition="authoritative",
            invoice_id=invoice_id,
        )
        authoritative.append(winner)
        for superseded in ordered[:-1]:
            dispositions[superseded.source_row] = SourceDisposition(
                source_row=superseded.source_row,
                disposition="superseded",
                related_source_row=winner.source_row,
                invoice_id=invoice_id,
            )

    ordered_invoices = tuple(sorted(authoritative, key=lambda invoice: invoice.source_row))
    ordered_dispositions = tuple(dispositions[row] for row in sorted(dispositions))
    snapshots = select_account_snapshots(ordered_invoices)
    disposition_counts = Counter(item.disposition for item in ordered_dispositions)
    quality_counts = Counter(
        flag for invoice in ordered_invoices for flag in invoice.quality_flags
    )

    if len(ordered_dispositions) != len(raw_rows):
        raise AssertionError("source row dispositions do not reconcile")
    if len({invoice.invoice_id for invoice in ordered_invoices}) != len(ordered_invoices):
        raise AssertionError("authoritative invoice IDs are not unique")

    profile = IngestionProfile(
        source_sha256=hashlib.sha256(source_bytes).hexdigest(),
        source_bytes=len(source_bytes),
        source_data_rows=len(raw_rows),
        disposition_counts=dict(sorted(disposition_counts.items())),
        authoritative_invoice_count=len(ordered_invoices),
        account_snapshot_count=len(snapshots),
        quality_flag_counts=dict(sorted(quality_counts.items())),
    )
    return IngestionResult(
        invoices=ordered_invoices,
        dispositions=ordered_dispositions,
        account_snapshots=snapshots,
        profile=profile,
    )