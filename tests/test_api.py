from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.artifacts import build_artifacts
from app.service import ApplicationService
from app.settings import Settings

ROOT = Path(__file__).resolve().parents[1]


def make_settings(artifact_dir: Path) -> Settings:
    return Settings(
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


@pytest.fixture(scope="module")
def ready_settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    settings = make_settings(tmp_path_factory.mktemp("api-artifacts") / ".cloudnova")
    build_artifacts(settings)
    return settings


def test_health_is_process_only_and_ready_requires_artifacts(tmp_path: Path) -> None:
    client = TestClient(create_app(make_settings(tmp_path / ".cloudnova")))

    assert client.get("/health").json() == {"status": "ok"}
    readiness = client.get("/ready")
    assert readiness.status_code == 503
    assert readiness.json()["detail"]["code"] == "artifacts_not_ready"
    assert "python -m app index" in readiness.json()["detail"]["message"]


def test_ready_returns_matching_fingerprints(ready_settings: Settings) -> None:
    response = TestClient(create_app(ready_settings)).get("/ready")

    assert response.status_code == 200
    assert response.json()["ready"] is True
    assert len(response.json()["structured_fingerprint"]) == 64
    assert len(response.json()["vector_fingerprint"]) == 64


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"question": "   "},
        {"question": "x" * 2001},
        {"question": "Find invoices", "top_k": 0},
        {"question": "Find invoices", "top_k": 21},
        {"question": "Find invoices", "extra": True},
    ],
)
def test_ask_rejects_invalid_requests(
    payload: dict[str, object],
    ready_settings: Settings,
) -> None:
    response = TestClient(create_app(ready_settings)).post("/ask", json=payload)

    assert response.status_code == 422


def test_ask_matches_shared_service(ready_settings: Settings) -> None:
    question = "How much have we given back in refunds?"
    expected = ApplicationService(ready_settings).ask(question)

    response = TestClient(create_app(ready_settings)).post(
        "/ask",
        json={"question": question, "top_k": 5},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer_id"] == expected.answer_id
    assert body["intent"] == expected.intent
    assert body["result"] == expected.result
    assert body["warnings"] == expected.to_dict()["warnings"]
    assert body["evidence"]["manifest_sha256"] == expected.evidence.manifest_sha256