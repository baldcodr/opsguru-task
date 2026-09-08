from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from app.artifacts import check_readiness
from app.metrics import METRIC_FUNCTIONS
from app.models import (
    EvidenceRecord,
    EvidenceSummary,
    JsonObject,
    RouteMode,
    ServiceResponse,
    WarningRecord,
)
from app.provider import OpenAICompatibleSynthesizer, ProviderError
from app.retrieval import search
from app.router import route_question
from app.settings import Settings
from app.store import load_account_snapshots, load_invoices

CONTRACT_VERSIONS = {"data": 1, "metrics": 1, "query": 1, "evaluation": 1}
LOGGER = logging.getLogger("cloudnova.service")


class ArtifactsNotReadyError(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(f"Artifacts are not ready ({reason}); run `python -m app index`.")
        self.reason = reason


class Synthesizer(Protocol):
    def synthesize(
        self,
        question: str,
        intent: str,
        result: JsonObject,
        citations: list[JsonObject],
    ) -> str: ...


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _normalized_question(question: str) -> str:
    return " ".join(question.casefold().split())


def _warning_dict(warning: WarningRecord) -> JsonObject:
    value: JsonObject = {"code": warning.code, "message": warning.message}
    if warning.count is not None:
        value["count"] = warning.count
    return value


def _evidence_dict(record: EvidenceRecord) -> JsonObject:
    return asdict(record)


def _citation_dict(record: EvidenceRecord) -> JsonObject:
    value = _evidence_dict(record)
    value.pop("contribution_usd", None)
    return value


def _representative_citations(
    records: tuple[EvidenceRecord, ...],
) -> tuple[EvidenceRecord, ...]:
    return tuple(
        sorted(
            records,
            key=lambda item: (
                -abs(Decimal(item.contribution_usd or "0")),
                item.invoice_id,
                item.source_row,
            ),
        )[:5]
    )


def _answer_id(
    *,
    structured_fingerprint: str,
    question: str,
    intent: str,
    result: JsonObject,
) -> str:
    identity = {
        "contracts": CONTRACT_VERSIONS,
        "dataset_fingerprint": structured_fingerprint,
        "intent": intent,
        "question": _normalized_question(question),
        "result": result,
    }
    return hashlib.sha256(_canonical_json(identity)).hexdigest()[:20]


def _deterministic_answer(intent: str, result: JsonObject) -> str:
    if intent == "recognized_revenue_2024":
        return (
            f"2024 recognized net revenue was ${result['net_revenue_usd']}, "
            f"including ${result['paid_revenue_usd']} from paid invoices and "
            f"${result['refund_impact_usd']} in refund impact."
        )
    if intent == "regional_average_mrr":
        regions = result["regions"]
        if not isinstance(regions, list) or not regions:
            return "No active accounts were available for regional average MRR."
        winner = regions[0]
        return (
            f"{winner['region']} had the highest average MRR at "
            f"${winner['average_mrr_usd']} per active account."
        )
    if intent == "refunds_total":
        return (
            f"CloudNova gave back ${result['amount_given_back_usd']} across "
            f"{result['refund_invoice_count']} valid refund invoices."
        )
    if intent == "plan_churn_comparison":
        plans = result["plans"]
        return (
            f"Enterprise churn was {plans['enterprise']['churn_rate_pct']}% versus "
            f"{plans['starter']['churn_rate_pct']}% for Starter, a "
            f"{result['percentage_point_difference']} percentage-point difference."
        )
    if intent == "top_accounts_revenue":
        accounts = result["accounts"]
        if not isinstance(accounts, list) or not accounts:
            return "No accounts had recognized revenue."
        names = ", ".join(str(account["account_name"]) for account in accounts)
        return f"The top five accounts by recognized revenue were: {names}."
    if intent == "payment_exposure":
        return (
            f"{result['invoice_count']} pending or failed invoices represent "
            f"${result['exposure_usd']} in exposure."
        )
    if intent == "unsupported_metric":
        return str(result["reason"])
    matches = result.get("matches", [])
    if not isinstance(matches, list) or not matches:
        return "No matching authoritative invoices were found."
    return f"Found {len(matches)} matching authoritative invoice records."


def _manifest_path(settings: Settings, answer_id: str) -> tuple[Path, str]:
    path = settings.evidence_dir / f"{answer_id}.json"
    try:
        display_path = str(path.relative_to(settings.project_root))
    except ValueError:
        display_path = str(path)
    return path, display_path


def _write_manifest(
    settings: Settings,
    *,
    answer_id: str,
    question: str,
    intent: str,
    mode: RouteMode,
    result: JsonObject,
    warnings: tuple[WarningRecord, ...],
    records: tuple[EvidenceRecord, ...],
    structured_fingerprint: str,
    vector_fingerprint: str,
) -> EvidenceSummary:
    payload: JsonObject = {
        "answer_id": answer_id,
        "question": question,
        "intent": intent,
        "mode": mode,
        "dataset_fingerprints": {
            "structured": structured_fingerprint,
            "vector": vector_fingerprint,
        },
        "contract_versions": CONTRACT_VERSIONS,
        "result": result,
        "warnings": [_warning_dict(warning) for warning in warnings],
        "records": [_evidence_dict(record) for record in records],
    }
    payload["content_sha256"] = hashlib.sha256(_canonical_json(payload)).hexdigest()
    manifest_bytes = json.dumps(
        payload,
        ensure_ascii=True,
        indent=2,
        sort_keys=True,
    ).encode("utf-8") + b"\n"
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    path, display_path = _manifest_path(settings, answer_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_bytes(manifest_bytes)
    os.replace(temporary, path)
    return EvidenceSummary(
        contribution_count=len(records),
        manifest_path=display_path,
        manifest_sha256=manifest_sha256,
    )


class ApplicationService:
    def __init__(
        self,
        settings: Settings,
        *,
        synthesizer: Synthesizer | None = None,
    ) -> None:
        self._settings = settings
        self._synthesizer: Synthesizer | None
        if synthesizer is not None:
            self._synthesizer = synthesizer
        elif settings.llm_enabled:
            self._synthesizer = OpenAICompatibleSynthesizer(
                api_key=settings.llm_api_key or "",
                base_url=settings.llm_base_url,
                model=settings.llm_model or "",
                timeout_seconds=settings.llm_timeout_seconds,
            )
        else:
            self._synthesizer = None

    def ask(self, question: str, *, top_k: int | None = None) -> ServiceResponse:
        started = time.perf_counter()
        question = question.strip()
        if not question:
            raise ValueError("question must not be blank")
        if len(question) > 2_000:
            raise ValueError("question must not exceed 2000 characters")
        requested_top_k = self._settings.top_k if top_k is None else top_k
        if not 1 <= requested_top_k <= 20:
            raise ValueError("top_k must be between 1 and 20")

        readiness = check_readiness(self._settings)
        if (
            not readiness.ready
            or readiness.structured_fingerprint is None
            or readiness.vector_fingerprint is None
        ):
            raise ArtifactsNotReadyError(readiness.reason or "unknown")

        route = route_question(question)
        retrieval_ms = 0
        if route.mode == "metric":
            invoices = load_invoices(self._settings.store_path)
            snapshots = load_account_snapshots(self._settings.store_path)
            computation = METRIC_FUNCTIONS[route.intent](invoices, snapshots)
            result = computation.result
            records = computation.evidence
            warnings = computation.warnings
            citations = _representative_citations(records)
        elif route.mode == "retrieval":
            retrieval_started = time.perf_counter()
            hits = search(
                self._settings.index_path,
                question,
                top_k=requested_top_k,
                expected_fingerprint=readiness.vector_fingerprint,
                dimensions=self._settings.embedding_dimensions,
            )
            retrieval_ms = round((time.perf_counter() - retrieval_started) * 1000)
            records = tuple(
                EvidenceRecord(
                    invoice_id=hit.invoice_id,
                    account_id=hit.account_id,
                    account_name=hit.account_name,
                    source_row=hit.source_row,
                    reason="semantic retrieval match",
                    fields={
                        **hit.metadata,
                        "distance": round(hit.distance, 8),
                        "document": hit.document,
                    },
                )
                for hit in hits
            )
            citations = records
            result = {
                "matches": [
                    {
                        "invoice_id": hit.invoice_id,
                        "account_id": hit.account_id,
                        "account_name": hit.account_name,
                        "source_row": hit.source_row,
                        "distance": round(hit.distance, 8),
                        "document": hit.document,
                    }
                    for hit in hits
                ]
            }
            warnings = (
                WarningRecord(
                    code="semantic_answer_unsynthesized",
                    message=(
                        "Semantic results are locally ranked records without hosted synthesis."
                    ),
                ),
            ) if self._synthesizer is None else ()
        else:
            missing_data = (
                ["churn_date", "historical_active_periods"]
                if "churn" in _normalized_question(question)
                else []
            )
            result = {
                "status": "unsupported_metric",
                "reason": route.reason,
                "missing_data": missing_data,
            }
            records = ()
            citations = ()
            warnings = ()

        answer = _deterministic_answer(route.intent, result)
        generation_ms = 0
        if self._synthesizer is not None and route.mode != "unsupported":
            generation_started = time.perf_counter()
            try:
                generated = self._synthesizer.synthesize(
                    question,
                    route.intent,
                    result,
                    [_citation_dict(citation) for citation in citations],
                ).strip()
                if not generated:
                    raise ValueError("provider returned an empty answer")
                answer = generated
            except (OSError, ProviderError, TimeoutError, ValueError):
                warnings = (
                    *warnings,
                    WarningRecord(
                        code="provider_unavailable_fallback",
                        message="Hosted synthesis was unavailable; deterministic wording was used.",
                    ),
                )
            generation_ms = round((time.perf_counter() - generation_started) * 1000)

        answer_id = _answer_id(
            structured_fingerprint=readiness.structured_fingerprint,
            question=question,
            intent=route.intent,
            result=result,
        )
        evidence = _write_manifest(
            self._settings,
            answer_id=answer_id,
            question=question,
            intent=route.intent,
            mode=route.mode,
            result=result,
            warnings=warnings,
            records=records,
            structured_fingerprint=readiness.structured_fingerprint,
            vector_fingerprint=readiness.vector_fingerprint,
        )
        total_ms = round((time.perf_counter() - started) * 1000)
        response = ServiceResponse(
            answer_id=answer_id,
            question=question,
            intent=route.intent,
            mode=route.mode,
            answer=answer,
            result=result,
            citations=citations,
            evidence=evidence,
            warnings=warnings,
            timing_ms={
                "total": total_ms,
                "retrieval": retrieval_ms,
                "generation": generation_ms,
            },
        )
        LOGGER.info(
            "query_completed",
            extra={
                "answer_id": answer_id,
                "intent": route.intent,
                "mode": route.mode,
                "evidence_count": evidence.contribution_count,
                "warning_codes": [warning.code for warning in warnings],
                "structured_fingerprint": readiness.structured_fingerprint,
                "total_ms": total_ms,
                "retrieval_ms": retrieval_ms,
                "generation_ms": generation_ms,
            },
        )
        return response