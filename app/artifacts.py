from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.ingestion import ingest_csv
from app.models import Readiness
from app.retrieval import build_vector_index, index_is_current, vector_fingerprint
from app.settings import Settings
from app.store import load_metadata, structured_fingerprint, write_canonical_store


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _replace_directory(temporary: Path, destination: Path) -> None:
    backup = destination.with_name(f"{destination.name}.backup")
    shutil.rmtree(backup, ignore_errors=True)
    if destination.exists():
        os.replace(destination, backup)
    try:
        os.replace(temporary, destination)
    except Exception:
        if backup.exists() and not destination.exists():
            os.replace(backup, destination)
        raise
    shutil.rmtree(backup, ignore_errors=True)


def build_artifacts(settings: Settings) -> dict[str, Any]:
    if not settings.source_path.is_file():
        raise FileNotFoundError(f"Invoice source not found: {settings.source_path}")
    settings.artifact_dir.mkdir(parents=True, exist_ok=True)

    ingestion = ingest_csv(settings.source_path)
    write_canonical_store(settings.store_path, ingestion)
    structured = structured_fingerprint(ingestion.profile.source_sha256)

    temporary_index = settings.index_path.with_name(f"{settings.index_path.name}.tmp")
    shutil.rmtree(temporary_index, ignore_errors=True)
    vector_metadata = build_vector_index(
        temporary_index,
        ingestion.invoices,
        structured_fingerprint_value=structured,
        dimensions=settings.embedding_dimensions,
    )
    _replace_directory(temporary_index, settings.index_path)

    profile = asdict(ingestion.profile)
    _write_json_atomic(settings.quality_report_path, profile)
    return {
        **profile,
        "structured_fingerprint": structured,
        **vector_metadata,
    }


def check_readiness(settings: Settings) -> Readiness:
    if not settings.source_path.is_file():
        return Readiness(ready=False, reason="source_missing")
    source_sha256 = hashlib.sha256(settings.source_path.read_bytes()).hexdigest()
    if not settings.store_path.is_file():
        return Readiness(
            ready=False,
            reason="structured_store_missing",
            source_sha256=source_sha256,
        )
    try:
        metadata = load_metadata(settings.store_path)
    except (OSError, ValueError):
        return Readiness(
            ready=False,
            reason="structured_store_invalid",
            source_sha256=source_sha256,
        )
    if metadata.get("source_sha256") != source_sha256:
        return Readiness(
            ready=False,
            reason="source_changed",
            source_sha256=source_sha256,
            structured_fingerprint=metadata.get("structured_fingerprint"),
        )

    expected_structured = structured_fingerprint(source_sha256)
    if metadata.get("structured_fingerprint") != expected_structured:
        return Readiness(
            ready=False,
            reason="normalization_changed",
            source_sha256=source_sha256,
            structured_fingerprint=metadata.get("structured_fingerprint"),
        )
    expected_vector = vector_fingerprint(
        expected_structured,
        dimensions=settings.embedding_dimensions,
    )
    if not index_is_current(settings.index_path, expected_vector):
        return Readiness(
            ready=False,
            reason="vector_index_missing_or_stale",
            source_sha256=source_sha256,
            structured_fingerprint=expected_structured,
            vector_fingerprint=expected_vector,
        )
    return Readiness(
        ready=True,
        reason=None,
        source_sha256=source_sha256,
        structured_fingerprint=expected_structured,
        vector_fingerprint=expected_vector,
    )