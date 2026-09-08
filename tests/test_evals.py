from __future__ import annotations

import io
from pathlib import Path

from app.artifacts import build_artifacts
from app.settings import Settings
from evals.run import run_evaluations

ROOT = Path(__file__).resolve().parents[1]


def test_offline_evaluation_reports_passes_and_expected_limitation(tmp_path: Path) -> None:
    settings = Settings(
        project_root=ROOT,
        source_path=ROOT / "cloudnova_invoices.csv",
        artifact_dir=tmp_path / ".cloudnova",
        top_k=5,
        embedding_dimensions=384,
        llm_enabled=False,
        llm_api_key=None,
        llm_base_url="https://api.openai.com/v1",
        llm_model=None,
    )
    build_artifacts(settings)
    stdout = io.StringIO()

    exit_code = run_evaluations(settings, stdout=stdout)

    output = stdout.getvalue()
    assert exit_code == 0
    assert output.count("PASS  EVAL-") == 6
    assert "XFAIL EVAL-XFAIL-001" in output
    assert "Summary: 0 failed, 1 expected limitation, 6 passed" in output