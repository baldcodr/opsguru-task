from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, TextIO, cast

from app.service import ApplicationService
from app.settings import Settings


def _load_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _manifest_path(settings: Settings, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else settings.project_root / path


def _project_evidence(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    for record in records:
        item: dict[str, Any] = {
            "invoice_id": record["invoice_id"],
            "source_row": record["source_row"],
        }
        if record.get("contribution_usd") is not None:
            item["contribution_usd"] = record["contribution_usd"]
        projected.append(item)
    return projected


def _metric_failure(
    settings: Settings,
    response: Any,
    expected_intent: str,
    expected: dict[str, Any],
) -> str | None:
    if response.intent != expected_intent:
        return f"routed to {response.intent}"
    if response.result != expected["result"]:
        return "structured result differs from golden"
    path = _manifest_path(settings, response.evidence.manifest_path)
    if not path.is_file():
        return "evidence manifest is missing"
    manifest_bytes = path.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != response.evidence.manifest_sha256:
        return "evidence manifest hash differs"
    manifest = cast(dict[str, Any], json.loads(manifest_bytes))
    records = cast(list[dict[str, Any]], manifest.get("records", []))
    if _project_evidence(records) != expected["evidence"]:
        return "complete evidence membership differs from golden"
    expected_members = {
        (item["invoice_id"], item["source_row"])
        for item in cast(list[dict[str, Any]], expected["evidence"])
    }
    if any(
        (citation.invoice_id, citation.source_row) not in expected_members
        for citation in response.citations
    ):
        return "representative citation is not in complete evidence"
    return None


def run_evaluations(settings: Settings, *, stdout: TextIO) -> int:
    golden = _load_json(settings.project_root / "evals" / "golden.json")
    cases_document = _load_json(settings.project_root / "evals" / "cases.json")
    source_sha256 = hashlib.sha256(settings.source_path.read_bytes()).hexdigest()
    expected_source_sha256 = cast(dict[str, Any], golden["dataset"])["source_sha256"]
    if source_sha256 != expected_source_sha256:
        stdout.write("FAIL  DATASET  source fingerprint differs from golden.json\n")
        stdout.write("Summary: 1 failed, 0 expected limitations, 0 passed\n")
        return 1

    service = ApplicationService(settings)
    passed = 0
    expected_limitations = 0
    failed = 0
    cases = cast(list[dict[str, Any]], cases_document["cases"])
    metrics = cast(dict[str, dict[str, Any]], golden["metrics"])

    for case in cases:
        case_id = cast(str, case["id"])
        expected_intent = cast(str, case["expected_intent"])
        try:
            response = service.ask(cast(str, case["question"]))
        except Exception as error:
            stdout.write(f"FAIL  {case_id}  {type(error).__name__}: {error}\n")
            failed += 1
            continue

        if case["expected_status"] == "xfail":
            missing_data = response.result.get("missing_data")
            if (
                response.intent == "unsupported_metric"
                and response.mode == "unsupported"
                and missing_data == ["churn_date", "historical_active_periods"]
            ):
                stdout.write(
                    f"XFAIL {case_id}  monthly churn requires missing churn dates/history\n"
                )
                expected_limitations += 1
            else:
                stdout.write(f"XPASS {case_id}  unsupported monthly churn was answered\n")
                failed += 1
            continue

        failure = _metric_failure(
            settings,
            response,
            expected_intent,
            metrics[expected_intent],
        )
        if failure is None:
            stdout.write(f"PASS  {case_id}  values and complete evidence match\n")
            passed += 1
        else:
            stdout.write(f"FAIL  {case_id}  {failure}\n")
            failed += 1

    stdout.write(
        f"Summary: {failed} failed, {expected_limitations} expected limitation, "
        f"{passed} passed\n"
    )
    return 0 if failed == 0 else 1