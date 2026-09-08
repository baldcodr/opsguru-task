from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from typing import TextIO

from app.artifacts import build_artifacts, check_readiness
from app.service import ApplicationService, ArtifactsNotReadyError
from app.settings import Settings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app",
        description="Query CloudNova's canonical invoice ledger.",
    )
    commands = parser.add_subparsers(dest="command")

    ask = commands.add_parser("ask", help="answer one invoice question")
    ask.add_argument("question")
    ask.add_argument("--top-k", type=int, default=None)
    ask.add_argument("--json", action="store_true", dest="as_json")

    index = commands.add_parser("index", help="build canonical and vector artifacts")
    index.add_argument("--force", action="store_true")

    commands.add_parser("eval", help="run the offline evaluation suite")

    serve = commands.add_parser("serve", help="start the FastAPI service")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    return parser


def _render_human(response: dict[str, object], stdout: TextIO) -> None:
    stdout.write(f"{response['answer']}\n")
    stdout.write(f"Answer ID: {response['answer_id']}\n")
    stdout.write("Result:\n")
    stdout.write(json.dumps(response["result"], indent=2, sort_keys=True) + "\n")
    citations = response["citations"]
    if isinstance(citations, list) and citations:
        stdout.write("Citations:\n")
        for citation in citations:
            if isinstance(citation, dict):
                stdout.write(
                    f"- {citation['invoice_id']} (CSV row {citation['source_row']}): "
                    f"{citation['reason']}\n"
                )
    evidence = response["evidence"]
    if isinstance(evidence, dict):
        stdout.write(
            f"Evidence: {evidence['contribution_count']} records in "
            f"{evidence['manifest_path']}\n"
        )
    warnings = response["warnings"]
    if isinstance(warnings, list):
        for warning in warnings:
            if isinstance(warning, dict):
                stdout.write(f"Warning [{warning['code']}]: {warning['message']}\n")


def _ask_once(
    service: ApplicationService,
    question: str,
    *,
    top_k: int | None,
    as_json: bool,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    try:
        response = service.ask(question, top_k=top_k).to_dict()
    except ValueError as error:
        stderr.write(f"Invalid input: {error}\n")
        return 2
    except ArtifactsNotReadyError as error:
        stderr.write(f"{error}\n")
        return 3
    if as_json:
        stdout.write(json.dumps(response, indent=2, sort_keys=True) + "\n")
    else:
        _render_human(response, stdout)
    return 0


def _interactive(
    service: ApplicationService,
    *,
    stdout: TextIO,
    stderr: TextIO,
    input_fn: Callable[[str], str],
) -> int:
    stdout.write("CloudNova Invoice Q&A. Type 'exit' to quit.\n")
    while True:
        try:
            question = input_fn("cloudnova> ")
        except (EOFError, KeyboardInterrupt):
            stdout.write("\n")
            return 0
        if question.strip().casefold() in {"exit", "quit"}:
            return 0
        exit_code = _ask_once(
            service,
            question,
            top_k=None,
            as_json=False,
            stdout=stdout,
            stderr=stderr,
        )
        if exit_code == 3:
            return exit_code


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    input_fn: Callable[[str], str] = input,
) -> int:
    args = _parser().parse_args(argv)
    try:
        configured = settings or Settings.from_env()
    except ValueError as error:
        stderr.write(f"Invalid configuration: {error}\n")
        return 2

    if args.command == "index":
        readiness = check_readiness(configured)
        if readiness.ready and not args.force:
            stdout.write("Artifacts are current; use --force to rebuild.\n")
            return 0
        try:
            report = build_artifacts(configured)
        except (OSError, ValueError) as error:
            stderr.write(f"Index build failed: {error}\n")
            return 1
        stdout.write(
            f"Indexed {report['authoritative_invoice_count']} authoritative invoices "
            f"from {report['source_data_rows']} source rows.\n"
        )
        return 0

    if args.command == "eval":
        from evals.run import run_evaluations

        return run_evaluations(configured, stdout=stdout)

    if args.command == "serve":
        import uvicorn

        from app.api import create_app

        uvicorn.run(create_app(configured), host=args.host, port=args.port)
        return 0

    service = ApplicationService(configured)
    if args.command == "ask":
        return _ask_once(
            service,
            args.question,
            top_k=args.top_k,
            as_json=args.as_json,
            stdout=stdout,
            stderr=stderr,
        )
    return _interactive(
        service,
        stdout=stdout,
        stderr=stderr,
        input_fn=input_fn,
    )