from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.artifacts import build_artifacts, check_readiness
from app.settings import Settings
from app.store import load_metadata

ROOT = Path(__file__).resolve().parents[1]


def test_build_artifacts_and_readiness(tmp_path: Path) -> None:
    source_path = ROOT / "cloudnova_invoices.csv"
    before = source_path.read_bytes()
    settings = Settings(
        project_root=ROOT,
        source_path=source_path,
        artifact_dir=tmp_path / ".cloudnova",
        top_k=5,
        embedding_dimensions=384,
        llm_enabled=False,
        llm_api_key=None,
        llm_base_url="https://api.openai.com/v1",
        llm_model=None,
    )

    report = build_artifacts(settings)

    assert source_path.read_bytes() == before
    assert report["source_sha256"] == hashlib.sha256(before).hexdigest()
    assert report["authoritative_invoice_count"] == 5000
    assert settings.store_path.is_file()
    assert settings.index_path.is_dir()
    assert settings.quality_report_path.is_file()

    quality_report = json.loads(settings.quality_report_path.read_text(encoding="utf-8"))
    assert quality_report["source_data_rows"] == 5125
    assert quality_report["disposition_counts"] == {
        "authoritative": 5000,
        "exact_duplicate": 82,
        "superseded": 43,
    }

    readiness = check_readiness(settings)
    assert readiness.ready
    assert readiness.reason is None
    assert readiness.structured_fingerprint == load_metadata(settings.store_path)[
        "structured_fingerprint"
    ]


def test_readiness_detects_changed_source(tmp_path: Path) -> None:
    source_path = tmp_path / "invoices.csv"
    source_path.write_bytes((ROOT / "cloudnova_invoices.csv").read_bytes())
    settings = Settings(
        project_root=tmp_path,
        source_path=source_path,
        artifact_dir=tmp_path / ".cloudnova",
        top_k=5,
        embedding_dimensions=384,
        llm_enabled=False,
        llm_api_key=None,
        llm_base_url="https://api.openai.com/v1",
        llm_model=None,
    )
    build_artifacts(settings)

    source_path.write_bytes(source_path.read_bytes() + b"\n")

    readiness = check_readiness(settings)
    assert not readiness.ready
    assert readiness.reason == "source_changed"