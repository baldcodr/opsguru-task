from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Literal

Plan = Literal["starter", "pro", "enterprise"]
BillingCycle = Literal["monthly", "annual"]
InvoiceStatus = Literal["paid", "pending", "failed", "refunded", "void"]
Currency = Literal["USD", "EUR", "GBP"]
DispositionKind = Literal["authoritative", "superseded", "exact_duplicate", "quarantined"]
RouteMode = Literal["metric", "retrieval", "unsupported"]


@dataclass(frozen=True, slots=True)
class CanonicalInvoice:
    invoice_id: str
    account_id: str
    account_name: str
    region: str
    industry: str | None
    plan: Plan
    billing_cycle: BillingCycle
    seats: int
    currency: Currency
    amount_local: Decimal
    fx_to_usd: Decimal
    amount_usd_unrounded: Decimal
    discount_pct: Decimal
    status: InvoiceStatus
    payment_method: str | None
    signup_date: date | None
    invoice_date: date
    churned: bool | None
    csat_score: int | None
    support_tickets: int
    source_row: int
    quality_flags: tuple[str, ...]
    raw_values: dict[str, str]


@dataclass(frozen=True, slots=True)
class SourceDisposition:
    source_row: int
    disposition: DispositionKind
    reason: str | None = None
    related_source_row: int | None = None
    invoice_id: str | None = None


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    invoice: CanonicalInvoice
    identity_conflicts: dict[str, tuple[str, ...]]

    @property
    def quality_flags(self) -> tuple[str, ...]:
        flags = set(self.invoice.quality_flags)
        if self.identity_conflicts:
            flags.add("account_identity_conflict")
        return tuple(sorted(flags))


@dataclass(frozen=True, slots=True)
class IngestionProfile:
    source_sha256: str
    source_bytes: int
    source_data_rows: int
    disposition_counts: dict[str, int]
    authoritative_invoice_count: int
    account_snapshot_count: int
    quality_flag_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class IngestionResult:
    invoices: tuple[CanonicalInvoice, ...]
    dispositions: tuple[SourceDisposition, ...]
    account_snapshots: dict[str, AccountSnapshot]
    profile: IngestionProfile


JsonObject = dict[str, Any]


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    invoice_id: str
    account_id: str
    account_name: str
    source_row: int
    reason: str
    fields: JsonObject
    contribution_usd: str | None = None


@dataclass(frozen=True, slots=True)
class WarningRecord:
    code: str
    message: str
    count: int | None = None


@dataclass(frozen=True, slots=True)
class MetricComputation:
    intent: str
    result: JsonObject
    evidence: tuple[EvidenceRecord, ...]
    warnings: tuple[WarningRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    vector_id: str
    invoice_id: str
    account_id: str
    account_name: str
    source_row: int
    document: str
    distance: float
    metadata: JsonObject


@dataclass(frozen=True, slots=True)
class RouteDecision:
    intent: str
    mode: RouteMode
    reason: str


@dataclass(frozen=True, slots=True)
class Readiness:
    ready: bool
    reason: str | None
    source_sha256: str | None = None
    structured_fingerprint: str | None = None
    vector_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class EvidenceSummary:
    contribution_count: int
    manifest_path: str
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class ServiceResponse:
    answer_id: str
    question: str
    intent: str
    mode: RouteMode
    answer: str
    result: JsonObject
    citations: tuple[EvidenceRecord, ...]
    evidence: EvidenceSummary
    warnings: tuple[WarningRecord, ...]
    timing_ms: dict[str, int]

    def to_dict(self) -> JsonObject:
        return {
            "answer_id": self.answer_id,
            "question": self.question,
            "intent": self.intent,
            "mode": self.mode,
            "answer": self.answer,
            "result": self.result,
            "citations": [
                {
                    "invoice_id": item.invoice_id,
                    "account_id": item.account_id,
                    "account_name": item.account_name,
                    "source_row": item.source_row,
                    "reason": item.reason,
                    "fields": item.fields,
                }
                for item in self.citations
            ],
            "evidence": {
                "contribution_count": self.evidence.contribution_count,
                "manifest_path": self.evidence.manifest_path,
                "manifest_sha256": self.evidence.manifest_sha256,
            },
            "warnings": [
                {
                    "code": item.code,
                    "message": item.message,
                    **({"count": item.count} if item.count is not None else {}),
                }
                for item in self.warnings
            ],
            "timing_ms": self.timing_ms,
        }
