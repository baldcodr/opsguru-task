from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from app.artifacts import build_artifacts
from app.cli import main
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
    settings = make_settings(tmp_path_factory.mktemp("cli-artifacts") / ".cloudnova")
    build_artifacts(settings)
    return settings


def test_cli_json_matches_shared_service(ready_settings: Settings) -> None:
    question = "How much have we given back in refunds?"
    expected = ApplicationService(ready_settings).ask(question)
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        ["ask", question, "--json"],
        settings=ready_settings,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    body = json.loads(stdout.getvalue())
    assert body["answer_id"] == expected.answer_id
    assert body["result"] == expected.result
    assert body["warnings"] == expected.to_dict()["warnings"]
    assert body["evidence"]["manifest_sha256"] == expected.evidence.manifest_sha256


def test_cli_input_and_artifact_errors_have_contract_exit_codes(tmp_path: Path) -> None:
    settings = make_settings(tmp_path / ".cloudnova")
    stdout = io.StringIO()
    stderr = io.StringIO()

    invalid_exit = main(
        ["ask", "   "],
        settings=settings,
        stdout=stdout,
        stderr=stderr,
    )
    stale_exit = main(
        ["ask", "How much have we given back in refunds?"],
        settings=settings,
        stdout=stdout,
        stderr=stderr,
    )

    assert invalid_exit == 2
    assert stale_exit == 3
    assert "traceback" not in stderr.getvalue().casefold()
    assert "python -m app index" in stderr.getvalue()


def test_cli_index_builds_artifacts(tmp_path: Path) -> None:
    settings = make_settings(tmp_path / ".cloudnova")
    stdout = io.StringIO()

    exit_code = main(["index"], settings=settings, stdout=stdout, stderr=io.StringIO())

    assert exit_code == 0
    assert settings.store_path.is_file()
    assert settings.index_path.is_dir()
    assert "5000" in stdout.getvalue()


def test_default_command_runs_interactive_prompt(ready_settings: Settings) -> None:
    answers = iter(["How much have we given back in refunds?", "exit"])
    stdout = io.StringIO()

    exit_code = main(
        [],
        settings=ready_settings,
        stdout=stdout,
        stderr=io.StringIO(),
        input_fn=lambda _prompt: next(answers),
    )

    assert exit_code == 0
    assert "8895263.77" in stdout.getvalue()