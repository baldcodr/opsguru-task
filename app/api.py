from __future__ import annotations

from dataclasses import asdict
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.artifacts import check_readiness
from app.service import ApplicationService, ArtifactsNotReadyError
from app.settings import Settings


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2_000)
    top_k: int = Field(default=5, ge=1, le=20)

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("question must not be blank")
        return stripped


class CitationResponse(BaseModel):
    invoice_id: str
    account_id: str
    account_name: str
    source_row: int
    reason: str
    fields: dict[str, Any]


class EvidenceResponse(BaseModel):
    contribution_count: int
    manifest_path: str
    manifest_sha256: str


class WarningResponse(BaseModel):
    code: str
    message: str
    count: int | None = None


class TimingResponse(BaseModel):
    total: int
    retrieval: int
    generation: int


class AskResponse(BaseModel):
    answer_id: str
    question: str
    intent: str
    mode: Literal["metric", "retrieval", "unsupported"]
    answer: str
    result: dict[str, Any]
    citations: list[CitationResponse]
    evidence: EvidenceResponse
    warnings: list[WarningResponse]
    timing_ms: TimingResponse


def create_app(settings: Settings | None = None) -> FastAPI:
    configured = settings or Settings.from_env()
    service = ApplicationService(configured)
    app = FastAPI(title="CloudNova Invoice Q&A", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    def ready() -> dict[str, Any]:
        readiness = check_readiness(configured)
        if not readiness.ready:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "artifacts_not_ready",
                    "reason": readiness.reason,
                    "message": "Artifacts are missing or stale; run `python -m app index`.",
                },
            )
        return asdict(readiness)

    @app.post("/ask", response_model=AskResponse)
    def ask(request: AskRequest) -> dict[str, Any]:
        try:
            return service.ask(request.question, top_k=request.top_k).to_dict()
        except ArtifactsNotReadyError as error:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "artifacts_not_ready",
                    "reason": error.reason,
                    "message": str(error),
                },
            ) from error

    return app