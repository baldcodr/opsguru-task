from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import pytest

from app.artifacts import build_artifacts
from app.service import ApplicationService
from app.settings import Settings

ROOT = Path(__file__).resolve().parents[1]


class FailingSynthesizer:
    def synthesize(
        self,
        question: str,
        intent: str,
        result: dict[str, Any],
        citations: list[dict[str, Any]],
    ) -> str:
        raise TimeoutError("provider timed out")


@pytest.fixture(scope="module")
def settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    artifact_dir = tmp_path_factory.mktemp("service-artifacts") / ".cloudnova"
    configured = Settings(
        project_root=ROOT,
        source_path=ROOT / "cloudnova_invoices.csv",
        artifact_dir=artifact_dir,
        top_k=5,
        embedding_dimensions=384,
        llm_enabled=False,
        llm_api_key=None,
        llm_base_url="https://api.openai.com/v1",
        llm_model=None,
    )
    build_artifacts(configured)
    return configured


def test_all_metric_cases_match_golden_and_write_complete_manifests(settings: Settings) -> None:
    cases = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))["cases"]
    golden = json.loads((ROOT / "evals" / "golden.json").read_text(encoding="utf-8"))
    service = ApplicationService(settings)

    for case in cases[:6]:
        response = service.ask(case["question"])
        expected = golden["metrics"][case["expected_intent"]]

        assert response.intent == case["expected_intent"]
        assert response.mode == "metric"
        assert response.result == expected["result"]
        assert response.evidence.contribution_count == len(expected["evidence"])
        assert len(response.citations) <= 5

        manifest_path = Path(response.evidence.manifest_path)
        assert manifest_path.is_file()
        manifest_bytes = manifest_path.read_bytes()
        assert hashlib.sha256(manifest_bytes).hexdigest() == response.evidence.manifest_sha256
        manifest = json.loads(manifest_bytes)
        projected = [
            {
                key: item[key]
                for key in ("invoice_id", "source_row", "contribution_usd")
                if item.get(key) is not None
            }
            for item in manifest["records"]
        ]
        assert projected == expected["evidence"]
        assert "contact_email" not in manifest_bytes.decode("utf-8")
        assert "@" not in manifest_bytes.decode("utf-8")


def test_answer_id_is_stable(settings: Settings) -> None:
    service = ApplicationService(settings)
    question = "How much have we given back in refunds?"

    first = service.ask(question)
    second = service.ask(question)

    assert first.answer_id == second.answer_id
    assert first.evidence.manifest_sha256 == second.evidence.manifest_sha256
    assert first.result == second.result


def test_semantic_lookup_returns_ranked_evidence_without_email(settings: Settings) -> None:
    response = ApplicationService(settings).ask(
        "Find the annual Starter invoice INV-104380 for Initech in LATAM"
    )

    assert response.intent == "semantic_lookup"
    assert response.mode == "retrieval"
    assert "INV-104380" in {citation.invoice_id for citation in response.citations}
    assert any(warning.code == "semantic_answer_unsynthesized" for warning in response.warnings)
    rendered = json.dumps(response.to_dict(), sort_keys=True)
    assert "contact_email" not in rendered
    assert "billing@" not in rendered


def test_expected_limitation_is_refused_without_numeric_result(settings: Settings) -> None:
    response = ApplicationService(settings).ask(
        "What was our monthly churn rate throughout 2024?"
    )

    assert response.intent == "unsupported_metric"
    assert response.mode == "unsupported"
    assert response.result["status"] == "unsupported_metric"
    assert response.result["missing_data"] == ["churn_date", "historical_active_periods"]
    assert "rate" not in response.result
    assert response.evidence.contribution_count == 0


def test_provider_failure_preserves_structured_result(settings: Settings) -> None:
    service = ApplicationService(settings, synthesizer=FailingSynthesizer())

    response = service.ask("How much have we given back in refunds?")

    assert response.result["amount_given_back_usd"] == "8895263.77"
    assert any(warning.code == "provider_unavailable_fallback" for warning in response.warnings)


def test_query_log_contains_operational_fields_without_question(
    settings: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    question = "How much was refunded for billing@example.com?"

    with caplog.at_level(logging.INFO, logger="cloudnova.service"):
        response = ApplicationService(settings).ask(question)

    record = next(record for record in caplog.records if record.message == "query_completed")
    assert record.intent == "refunds_total"
    assert record.evidence_count == response.evidence.contribution_count
    assert record.warning_codes == [warning.code for warning in response.warnings]
    assert record.total_ms >= 0
    serialized = json.dumps(record.__dict__, default=str)
    assert question not in serialized
    assert "billing@example.com" not in serialized
    response_json = json.dumps(response.to_dict(), sort_keys=True)
    manifest = Path(response.evidence.manifest_path).read_text(encoding="utf-8")
    assert "billing@example.com" not in response_json
    assert "billing@example.com" not in manifest
    assert "[redacted-email]" in response.question