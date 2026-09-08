from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _boolean(value: str) -> bool:
    token = value.strip().casefold()
    if token in {"1", "true", "yes", "on"}:
        return True
    if token in {"0", "false", "no", "off", ""}:
        return False
    raise ValueError(f"invalid boolean setting: {value!r}")


def _resolve(root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


@dataclass(frozen=True, slots=True)
class Settings:
    project_root: Path
    source_path: Path
    artifact_dir: Path
    top_k: int
    embedding_dimensions: int
    llm_enabled: bool
    llm_api_key: str | None
    llm_base_url: str
    llm_model: str | None
    llm_timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if not 1 <= self.top_k <= 20:
            raise ValueError("top_k must be between 1 and 20")
        if self.embedding_dimensions < 16:
            raise ValueError("embedding_dimensions must be at least 16")
        if not 0 < self.llm_timeout_seconds <= 60:
            raise ValueError("llm_timeout_seconds must be greater than 0 and at most 60")
        if self.llm_enabled and (not self.llm_api_key or not self.llm_model):
            raise ValueError("enabled hosted synthesis requires API key and model")

    @property
    def store_path(self) -> Path:
        return self.artifact_dir / "canonical.sqlite3"

    @property
    def index_path(self) -> Path:
        return self.artifact_dir / "chroma"

    @property
    def evidence_dir(self) -> Path:
        return self.artifact_dir / "evidence"

    @property
    def quality_report_path(self) -> Path:
        return self.artifact_dir / "quality-report.json"

    @classmethod
    def from_env(cls, project_root: Path | None = None) -> Settings:
        root = (project_root or Path.cwd()).resolve()
        source_path = _resolve(root, os.getenv("CLOUDNOVA_SOURCE_PATH", "cloudnova_invoices.csv"))
        artifact_dir = _resolve(root, os.getenv("CLOUDNOVA_ARTIFACT_DIR", ".cloudnova"))
        api_key = os.getenv("CLOUDNOVA_LLM_API_KEY", "").strip() or None
        model = os.getenv("CLOUDNOVA_LLM_MODEL", "").strip() or None
        return cls(
            project_root=root,
            source_path=source_path,
            artifact_dir=artifact_dir,
            top_k=int(os.getenv("CLOUDNOVA_TOP_K", "5")),
            embedding_dimensions=int(os.getenv("CLOUDNOVA_EMBEDDING_DIMENSIONS", "384")),
            llm_enabled=_boolean(os.getenv("CLOUDNOVA_LLM_ENABLED", "false")),
            llm_api_key=api_key,
            llm_base_url=os.getenv(
                "CLOUDNOVA_LLM_BASE_URL",
                "https://api.openai.com/v1",
            ).rstrip("/"),
            llm_model=model,
            llm_timeout_seconds=float(os.getenv("CLOUDNOVA_LLM_TIMEOUT_SECONDS", "10")),
        )