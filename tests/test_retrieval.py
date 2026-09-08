from __future__ import annotations

import math
from pathlib import Path

from app.ingestion import ingest_csv
from app.retrieval import (
    EMBEDDING_VERSION,
    build_vector_index,
    embed_text,
    index_is_current,
    render_invoice_document,
    search,
    vector_fingerprint,
)
from app.store import structured_fingerprint

ROOT = Path(__file__).resolve().parents[1]


def test_feature_hash_embedding_is_deterministic_and_normalized() -> None:
    first = embed_text("Paid Enterprise invoice in EMEA", dimensions=64)
    second = embed_text("Paid Enterprise invoice in EMEA", dimensions=64)

    assert first == second
    assert len(first) == 64
    assert math.isclose(math.sqrt(sum(value * value for value in first)), 1.0)


def test_invoice_document_excludes_contact_email() -> None:
    invoice = ingest_csv(ROOT / "cloudnova_invoices.csv").invoices[0]

    document = render_invoice_document(invoice)

    assert invoice.invoice_id in document
    assert invoice.account_name in document
    assert invoice.raw_values["contact_email"] not in document
    assert "contact_email" not in document


def test_chroma_index_retrieves_labeled_invoice_and_tracks_fingerprint(tmp_path: Path) -> None:
    ingestion = ingest_csv(ROOT / "cloudnova_invoices.csv")
    index_path = tmp_path / "chroma"
    structured = structured_fingerprint(ingestion.profile.source_sha256)
    expected_fingerprint = vector_fingerprint(structured, dimensions=384)

    metadata = build_vector_index(
        index_path,
        ingestion.invoices,
        structured_fingerprint_value=structured,
        dimensions=384,
    )

    assert metadata["vector_fingerprint"] == expected_fingerprint
    assert metadata["embedding_version"] == EMBEDDING_VERSION
    assert metadata["record_count"] == 5000
    assert index_is_current(index_path, expected_fingerprint)
    assert not index_is_current(index_path, "not-the-current-fingerprint")

    hits = search(
        index_path,
        "Find the annual Starter invoice INV-104380 for Initech in LATAM",
        top_k=5,
        expected_fingerprint=expected_fingerprint,
        dimensions=384,
    )

    assert "INV-104380" in {hit.invoice_id for hit in hits}
    assert all(hit.source_row >= 2 for hit in hits)
    assert all("@" not in hit.document for hit in hits)